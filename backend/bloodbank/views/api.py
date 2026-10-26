"""API JSON cho trợ lý hỏi đáp và dữ liệu cá nhân của Người dùng (xác thực bằng phiên đăng nhập + CSRF).

Phân quyền: bảng `access.py` (middleware trả JSON 401/403 cho đường dẫn /api/) + kiểm tra lại trong view.
Dữ liệu cá nhân luôn lấy theo người đang đăng nhập — không nhận id người dùng từ client.
"""
import json
import logging

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods, require_POST

from bloodbank.assistant import service, tools
from bloodbank.assistant.tools import Ctx
from bloodbank.services.common import BusinessError

log = logging.getLogger(__name__)


def _err(status, code, message):
    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


def _member(request):
    if not request.user.is_authenticated:
        return _err(401, "ERR-AUTH-UNAUTHENTICATED", "Bạn cần đăng nhập.")
    if request.user.role != "member":
        return _err(403, "ERR-AUTH-FORBIDDEN", "Chỉ tài khoản Người dùng.")
    return None


def _payload(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body or b"{}")
        except ValueError:
            return {}
    return request.POST


# ---------------------------------------------------------------- Trợ lý
@require_POST
def chat_message(request):
    """POST /api/chatbot/message — {message, conversation_id?, lat?, lng?}"""
    data = _payload(request)
    try:
        res = service.answer(request, data.get("message") or data.get("q"), data.get("lat"), data.get("lng"),
                             data.get("conversation_id") or None)
    except BusinessError as exc:
        return _err(404, exc.code, exc.message)
    return JsonResponse(res)


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@require_POST
def chat_stream(request):
    """POST /api/chatbot/stream — như /message nhưng trả câu trả lời dần dần (Server-Sent Events):
        event: delta  {"text": "..."}   phần chữ mới
        event: reset  {}                xóa phần chữ đã hiện (AI chuyển sang tra dữ liệu / bị thay bằng câu dự phòng)
        event: done   {answer, links, cards, source, mode, conversation_id}   câu trả lời cuối — luôn có, thay toàn bộ
    Kết quả công cụ / dữ liệu nội bộ không bao giờ được stream ra; chỉ chữ của câu trả lời."""
    data = _payload(request)
    conv_id = data.get("conversation_id") or None
    if request.user.is_authenticated:
        try:
            service.own_conversation(request.user, conv_id)    # kiểm tra quyền trước khi mở luồng
        except BusinessError as exc:
            return _err(404, exc.code, exc.message)

    def events():
        try:
            for kind, payload in service.answer_events(request, data.get("message") or data.get("q"),
                                                       data.get("lat"), data.get("lng"), conv_id):
                if kind == "delta":
                    yield _sse("delta", {"text": payload})
                elif kind == "reset":
                    yield _sse("reset", {})
                else:
                    yield _sse("done", payload)
        except Exception:      # lỗi bất ngờ giữa luồng: báo cho khung chat thay vì cắt ngang im lặng
            log.exception("Lỗi khi stream câu trả lời trợ lý")
            yield _sse("error", {"message": "Trợ lý đang gặp sự cố. Vui lòng thử lại sau ít phút."})

    resp = StreamingHttpResponse(events(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"      # proxy (nginx) không gom lại cả câu mới gửi
    return resp


@require_http_methods(["GET"])
def conversations(request):
    """GET /api/chatbot/conversations — hội thoại của chính người dùng (mới nhất trước)."""
    if not request.user.is_authenticated:
        return _err(401, "ERR-AUTH-UNAUTHENTICATED", "Bạn cần đăng nhập.")
    return JsonResponse({"conversations": [
        {"id": c.pk, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at,
         "messages": c.message_count} for c in service.list_conversations(request.user)]})


@require_http_methods(["GET", "DELETE"])
def conversation(request, pk):
    """GET/DELETE /api/chatbot/conversations/{id} — chỉ hội thoại của chính mình (người khác → 404)."""
    if not request.user.is_authenticated:
        return _err(401, "ERR-AUTH-UNAUTHENTICATED", "Bạn cần đăng nhập.")
    try:
        if request.method == "DELETE":
            service.delete_conversation(request.user, pk)
            return JsonResponse({"deleted": True})
        conv = service.own_conversation(request.user, pk)
    except BusinessError as exc:
        return _err(404, exc.code, exc.message)
    return JsonResponse({"id": conv.pk, "title": conv.title, "messages": [
        {"role": m.role, "text": m.text, "cards": m.cards, "links": m.links, "source": m.source,
         "created_at": m.created_at} for m in conv.messages.all()]})


# ---------------------------------------------------------------- Dữ liệu (dùng chung các công cụ của trợ lý)
@require_http_methods(["GET"])
def campaigns(request):
    """GET /api/donation-campaigns?area=&date_from=&date_to=&time_of_day=&limit=&lat=&lng="""
    g = request.GET
    ctx = Ctx(request.user, *service.location(g.get("lat"), g.get("lng")))
    try:
        limit = int(g.get("limit") or 10)
    except ValueError:
        limit = 10
    tod = g.get("time_of_day") if g.get("time_of_day") in ("morning", "afternoon", "evening") else None
    return JsonResponse(tools.suggest_campaigns(ctx, area=g.get("area") or None, date_from=g.get("date_from"),
                                                date_to=g.get("date_to"), time_of_day=tod, limit=limit))


@require_http_methods(["GET"])
def my_history(request):
    """GET /api/donations/me/history"""
    return _member(request) or JsonResponse(tools.my_donation_history(Ctx(user=request.user)))


@require_http_methods(["GET"])
def my_eligibility(request):
    """GET /api/donations/me/eligibility?age=&weight_kg=&gender= — ngày được hiến lại + đối chiếu sơ bộ."""
    denied = _member(request)
    if denied:
        return denied
    g = request.GET
    ctx = Ctx(user=request.user)
    gender = g.get("gender") if g.get("gender") in ("male", "female") else None
    pre = tools.preliminary_check(ctx, age=g.get("age") or None, weight_kg=g.get("weight_kg") or None, gender=gender)
    if "error" in pre:
        return _err(400, "ERR-VALIDATION", pre["error"])
    return JsonResponse({"next_eligible": tools.my_eligibility(ctx), "preliminary": pre})


@require_http_methods(["GET"])
def my_registrations(request):
    """GET /api/donation-registrations/me"""
    return _member(request) or JsonResponse(tools.my_registrations(Ctx(user=request.user)))
