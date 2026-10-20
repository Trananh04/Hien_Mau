"""Điểm vào của trợ lý:

    câu hỏi → chặn trước (guard) → truy xuất tài liệu (RAG) → Claude (nếu bật) → KIỂM TRA câu trả lời (verify)
            → nếu AI lỗi / không qua kiểm tra: chế độ từ khóa → lưu hội thoại → trả lời + nguồn/liên kết

- Giới hạn tần suất theo người dùng / phiên (CHATBOT_RATE_LIMIT câu / 5 phút).
- Ghi nhớ hội thoại:
    • đã đăng nhập: lưu DB (ChatConversation/ChatMessage) — chỉ chủ tài khoản xem/xóa được, tự xóa sau
      `chat_retention_days` ngày;
    • khách: chỉ trong phiên (session), không lưu DB.
  Lịch sử đưa vào AI lấy từ máy chủ (không nhận "lịch sử" do trình duyệt gửi lên).
- Nhật ký hệ thống (audit_logs) chỉ ghi ý định / chế độ / tài liệu đã dùng — KHÔNG ghi nội dung câu hỏi.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Count
from django.utils import timezone

from bloodbank.models import ChatConversation, ChatMessage, SystemSetting
from bloodbank.services.common import BusinessError, audit

from . import guard, knowledge, llm, rules, verify
from .tools import Ctx

log = logging.getLogger(__name__)
SESSION_HISTORY = "assistant_history"
MAX_TURNS = 6


def _rate_key(request):
    if request.user.is_authenticated:
        return f"assistant-rate:u{request.user.pk}"
    if not request.session.session_key:
        request.session.save()
    return f"assistant-rate:s{request.session.session_key}"


def rate_limited(request):
    key = _rate_key(request)
    n = cache.get(key, 0)
    if n >= settings.CHATBOT_RATE_LIMIT:
        return True
    cache.set(key, n + 1, 300) if n == 0 else cache.incr(key)
    return False


# ---------------------------------------------------------------- Bảo vệ khi nhiều người hỏi cùng lúc
LLM_LOCK_CLASS = 7311   # không gian khóa advisory riêng của trợ lý


def _llm_slot():
    """Giữ 1 trong CHATBOT_MAX_CONCURRENT suất gọi AI; trả về số suất, hoặc None nếu hết suất / hết hạn mức ngày
    → khi đó trả lời bằng chế độ từ khóa ngay (nhanh, miễn phí) thay vì xếp hàng chờ dịch vụ AI.

    Suất = khóa advisory của PostgreSQL: nguyên tử trên mọi worker/luồng, và tự nhả khi kết nối đóng
    (worker chết không làm kẹt suất). Hạn mức ngày đếm trên cache — gần đúng, đủ để chặn chi phí bất thường."""
    day = f"assistant-llm-day:{timezone.localdate().isoformat()}"
    if cache.get(day, 0) >= settings.CHATBOT_DAILY_LIMIT:
        return None
    with connection.cursor() as cur:
        for slot in range(settings.CHATBOT_MAX_CONCURRENT):
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", [LLM_LOCK_CLASS, slot])
            if cur.fetchone()[0]:
                break
        else:
            return None
    if cache.add(day, 1, 2 * 86400) is False:
        try:
            cache.incr(day)
        except ValueError:
            pass
    return slot


def _llm_release(slot):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s, %s)", [LLM_LOCK_CLASS, slot])
    except Exception:   # không nhả được (vd. giao dịch lỗi) → đóng kết nối, PostgreSQL tự nhả khóa
        log.exception("Không nhả được suất gọi AI — đóng kết nối")
        connection.close()


def _coord(value, lo, hi):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if lo <= v <= hi else None


def location(lat, lng):
    """Vị trí do trình duyệt gửi → (lat, lng) hợp lệ, hoặc (None, None) nếu thiếu / sai một trong hai."""
    lat, lng = _coord(lat, -90, 90), _coord(lng, -180, 180)
    return (lat, lng) if lat is not None and lng is not None else (None, None)


# ---------------------------------------------------------------- Hội thoại
def own_conversation(user, conversation_id):
    """Hội thoại của chính người dùng; id của người khác / không tồn tại → BusinessError ERR-NOT-FOUND."""
    conv = ChatConversation.objects.filter(pk=conversation_id, user=user).first() if conversation_id else None
    if conversation_id and conv is None:
        raise BusinessError("ERR-NOT-FOUND", "Không tìm thấy cuộc trò chuyện.")
    return conv


def list_conversations(user, limit=50):
    return (ChatConversation.objects.filter(user=user).annotate(message_count=Count("messages"))
            .order_by("-updated_at")[:limit])


def delete_conversation(user, conversation_id):
    """Xóa hội thoại của chính người dùng (kèm tin nhắn); của người khác / không tồn tại → ERR-NOT-FOUND."""
    conv = own_conversation(user, conversation_id)
    if conv is None:
        raise BusinessError("ERR-NOT-FOUND", "Không tìm thấy cuộc trò chuyện.")
    conv.delete()


def _history(request, conv):
    if conv is not None:
        msgs = list(conv.messages.order_by("-created_at", "-id")[:2 * MAX_TURNS])[::-1]
        return [{"role": m.role, "text": m.text} for m in msgs]
    if not request.user.is_authenticated:
        return request.session.get(SESSION_HISTORY, [])
    return []


def _remember(request, conv, question, result):
    if request.user.is_authenticated:
        if conv is None:
            conv = ChatConversation.objects.create(user=request.user, title=question[:120])
        ChatMessage.objects.create(conversation=conv, role="user", text=question)
        ChatMessage.objects.create(conversation=conv, role="assistant", text=result["answer"], cards=result["cards"],
                                   links=result["links"], source=(result["source"] or "")[:300] or None,
                                   mode=result["mode"])
        conv.save(update_fields=["updated_at"])
        return conv
    hist = request.session.get(SESSION_HISTORY, []) + [{"role": "user", "text": question},
                                                       {"role": "assistant", "text": result["answer"]}]
    request.session[SESSION_HISTORY] = hist[-2 * MAX_TURNS:]
    return None


def purge_old_conversations(now=None):
    """Tác vụ định kỳ: xóa hội thoại không hoạt động quá `chat_retention_days` ngày."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=SystemSetting.get("chat_retention_days"))
    deleted, _ = ChatConversation.objects.filter(updated_at__lt=cutoff).delete()
    return deleted


# ---------------------------------------------------------------- Trả lời
def answer(request, question, lat=None, lng=None, conversation_id=None):
    question = (question or "").strip()[:300]
    conv = own_conversation(request.user, conversation_id) if request.user.is_authenticated else None
    if not question:
        return {"answer": "Bạn muốn hỏi gì về hiến máu?", "links": [], "cards": [], "source": None, "mode": "rules",
                "conversation_id": conv.pk if conv else None}
    if rate_limited(request):
        return {"answer": "Bạn hỏi hơi nhanh — vui lòng đợi vài phút rồi thử lại.", "links": [], "cards": [],
                "source": None, "mode": "limit", "conversation_id": conv.pk if conv else None}
    ctx = Ctx(request.user, *location(lat, lng))

    result = None
    blocked = guard.check(question)
    if blocked:
        result = {**blocked, "mode": "guard"}
    else:
        docs = knowledge.search(question)                       # RAG: truy xuất 1 lần, dùng cho cả 2 chế độ
        pre = rules.prefetch(question, ctx)                     # câu hỏi về dữ liệu → tra cứu sẵn (chỉ đọc)
        slot = _llm_slot() if llm.enabled() else None
        if slot is not None:
            try:
                res = llm.ask(question, ctx, _history(request, conv), docs=docs,
                              prefetched=pre[1:] if pre else None)
                res["answer"] = verify.check(res["answer"], res["evidence"])
                result = {**res, "mode": "llm", "intent": ",".join(res["tools_used"]) or "chat", "source": None}
            except llm.LLMUnavailable as exc:
                log.warning("Chatbot chuyển sang chế độ từ khóa: %s", exc)
            except verify.Unverified as exc:
                log.warning("Câu trả lời AI không qua kiểm tra (%s) — dùng chế độ từ khóa", exc)
            finally:
                _llm_release(slot)
        elif llm.enabled():
            log.info("Chatbot: AI đang bận / hết hạn mức ngày — trả lời bằng chế độ từ khóa")
        if result is None:
            result = {**rules.answer(question, ctx, docs=docs, pre=pre), "mode": "rules"}

    result.setdefault("links", [])
    result.setdefault("cards", [])
    result.setdefault("source", None)
    conv = _remember(request, conv, question, result)
    try:
        audit(request.user if request.user.is_authenticated else None, None, "assistant_query",
              new={"mode": result["mode"], "intent": result.get("intent"), "location": ctx.lat is not None,
                   "cards": len(result["cards"]), "docs": result.get("doc_ids", [])},
              entity_type="assistant", entity_id=0, request=request)
    except Exception:  # nhật ký không được làm hỏng câu trả lời
        log.exception("Không ghi được nhật ký trợ lý")
    out = {k: result[k] for k in ("answer", "links", "cards", "source", "mode")}
    out["conversation_id"] = conv.pk if conv else None
    return out


def reset(request):
    request.session.pop(SESSION_HISTORY, None)
