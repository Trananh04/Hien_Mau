"""Chế độ không cần AI: nhận diện ý định bằng từ khóa (có/không dấu) → công cụ dữ liệu hoặc truy xuất tài liệu (RAG).

Cũng là phương án dự phòng khi gọi LLM lỗi / hết hạn mức / câu trả lời AI không qua bước kiểm tra.
"""
import re
from datetime import date

from django.utils import timezone

from bloodbank.content import FALLBACK_ANSWER, _norm
from bloodbank.models import Campaign, Hospital

from . import knowledge, tools

ELIGIBILITY = ["hien lai", "khi nao duoc hien", "bao gio duoc hien", "khi nao toi duoc hien", "bao lau nua",
               "du thoi gian nghi", "lan hien tiep", "hien tiep", "khi nao co the hien", "bao gio hien duoc"]
HISTORY = ["hien may lan", "hien bao nhieu lan", "da hien bao nhieu", "so lan hien cua toi", "toi da hien",
           "lan gan nhat toi hien", "lan hien gan nhat", "lich su hien cua toi", "tong so lan hien",
           "lich su hien mau cua toi", "lich su cua toi"]
MY_REGS = ["don dang ky", "don cua toi", "duoc duyet chua", "da duyet chua", "dang ky cua toi", "toi da dang ky",
           "lich dang ky", "dang ky ngay nao", "dang ky hien mau ngay nao"]
MY_PRQ = ["yeu cau can mau cua toi", "yeu cau cua toi", "yeu cau toi da gui", "yeu cau xin mau cua toi", "pr "]
CAMPAIGNS = ["dot hien", "lich hien", "hien mau o dau", "hien o dau", "cho nao hien", "noi nao hien", "gan toi",
             "gan day", "gan nha", "sap dien ra", "sap toi", "dot nao", "cuoi tuan", "dia diem hien", "diem hien mau",
             "muon hien mau o"]
NOT_CAMPAIGN = ["lich su", "so lan hien", "mat khau", "bao mat", "ban do"]
TIME_PHRASES = [("hom nay", "today"), ("ngay mai", "tomorrow"), ("cuoi tuan", "weekend"), ("tuan nay", "this_week"),
                ("tuan sau", "next_week"), ("tuan toi", "next_week")]
# "bao giờ tôi có thể hiến máu tiếp", "khi nào mình hiến lại được", "hiến máu lại"...
ELIGIBILITY_RE = re.compile(r"\b(khi nao|bao gio|bao lau|luc nao|ngay nao)\b.*\bhien\b.*\b(lai|tiep)\b"
                            r"|\bhien( mau)? (lai|tiep)\b")
AGE = re.compile(r"\b(\d{1,3})\s*tuoi\b")
WEIGHT = re.compile(r"\b(\d{2,3}(?:[.,]\d)?)\s*(?:kg|ky|ki lo|kilo|can)\b")
MALE = re.compile(r"\b(nam gioi|con trai|dan ong|gioi tinh nam|la nam|toi nam)\b|\b(tuoi|kg|ky|can)\s+nam\b")
FEMALE = re.compile(r"\b(nu gioi|con gai|phu nu|gioi tinh nu|la nu|toi nu)\b|\b(tuoi|kg|ky|can)\s+nu\b")


def _has(q, words):
    return any(w in q for w in words)


def parse_profile(question):
    q = _norm(question)
    age = AGE.search(q)
    weight = WEIGHT.search(q)
    gender = "male" if MALE.search(q) else ("female" if FEMALE.search(q) else None)
    return {"age": int(age.group(1)) if age else None,
            "weight_kg": float(weight.group(1).replace(",", ".")) if weight else None, "gender": gender}


def detect_intent(question):
    q = _norm(question)
    p = parse_profile(question)
    if (p["age"] is not None or p["weight_kg"] is not None) and "hien" in q:
        return "precheck"
    if _has(q, ELIGIBILITY) or ELIGIBILITY_RE.search(q):
        return "eligibility"
    if _has(q, HISTORY):
        return "history"
    if _has(q, MY_PRQ) or re.search(r"\bpr \d{8}", q):
        return "my_patient_requests"
    if _has(q, MY_REGS):
        return "my_registrations"
    # "lịch sử hiến máu ở đâu" là hỏi về trang lịch sử, không phải tìm đợt hiến
    if _has(q, CAMPAIGNS) and not _has(q, NOT_CAMPAIGN):
        return "campaigns"
    return "faq"


def known_areas():
    """Địa danh có trong dữ liệu (quận/huyện, tỉnh của bệnh viện và đợt hiến) + 63 tỉnh/thành."""
    from accounts.provinces import area_names

    names = set(area_names())
    for district, province in Hospital.objects.filter(status="active").values_list("district", "province"):
        names.update(filter(None, [district, province]))
    names.update(filter(None, Campaign.objects.filter(status="open").values_list("province", flat=True)))
    return sorted(names, key=len, reverse=True)


def extract_area(question):
    q = _norm(question)
    for name in known_areas():
        n = _norm(name)
        if n and re.search(rf"\b{re.escape(n)}\b", q):
            from accounts.provinces import normalize_province

            return normalize_province(name) or name    # "Quảng Nam" → "Đà Nẵng" (sau sắp xếp 2025)
    return None


def extract_time(question, today=None):
    q = _norm(question)
    today = today or timezone.localdate()
    for phrase, key in TIME_PHRASES:
        if phrase in q:
            return tools.week_range(today, key)
    m = re.search(r"\bthang (\d{1,2})\b", q)
    if m and 1 <= int(m.group(1)) <= 12:
        month = int(m.group(1))
        year = today.year + (1 if month < today.month else 0)
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1) - timezone.timedelta(days=1)
        return start, end
    return None, None


def time_of_day(question):
    q = _norm(question)
    if "buoi sang" in q or re.search(r"\bsang\b", q):
        return "morning"
    if "buoi chieu" in q or re.search(r"\bchieu\b", q):
        return "afternoon"
    if "buoi toi" in q:
        return "evening"
    return None


# ---------------------------------------------------------------- Diễn đạt kết quả công cụ
def _d(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def render(intent, data):
    if data.get("login_required"):
        return {"answer": data["message"], "links": data["links"]}
    if intent == "eligibility":
        if not data.get("has_donation"):
            return {"answer": data["message"], "links": data["links"]}
        last = data["last_donation"]
        head = f"Bạn hiến {last['type'].lower()} gần nhất ngày {_d(last['date'])} tại {last['hospital']}. "
        if data["ready_now"]:
            body = "Bạn đã đủ khoảng nghỉ khuyến nghị và có thể đăng ký đợt hiến tiếp theo."
        else:
            body = f"Bạn có thể hiến lại từ ngày {_d(data['eligible_from'])} (còn {data['days_left']} ngày)."
        return {"answer": head + body + " " + data["note"], "links": data["links"]}
    if intent == "history":
        if not data["confirmed_count"]:
            return {"answer": "Bạn chưa có lượt hiến nào được bệnh viện xác nhận. " + data["note"], "links": data["links"]}
        parts = [f"Bạn đã hiến {data['confirmed_count']} lần được bệnh viện xác nhận"]
        if data["whole_blood_count"]:
            parts.append(f"trong đó {data['whole_blood_count']} lần máu toàn phần (tổng {data['whole_blood_ml']} ml)")
        if data["component_count"]:
            parts.append(f"{data['component_count']} lần hiến thành phần")
        text = ", ".join(parts) + f". Lần gần nhất: {_d(data['last_donation'])}."
        return {"answer": text, "links": data["links"]}
    if intent == "precheck":
        if "error" in data:
            return {"answer": data["error"], "links": []}
        lines = [f"• {c['criterion']}: {c['value']} — ngưỡng tham khảo {c['reference']} "
                 f"({'trong ngưỡng' if c['within'] else 'NGOÀI ngưỡng'})" for c in data["checks"]]
        if data["summary"] == "outside_reference":
            head = "Theo đối chiếu sơ bộ, có tiêu chí nằm ngoài ngưỡng tham khảo:"
        elif data["checks"]:
            head = "Các tiêu chí bạn nêu nằm trong ngưỡng tham khảo:"
        else:
            head = "Mình cần thêm thông tin để đối chiếu."
        text = head + ("\n" + "\n".join(lines) if lines else "")
        ask = [m for m in data["missing"] if not m.startswith("lần hiến gần nhất")]
        if ask:
            text += f"\nBạn cho mình biết thêm {', '.join(ask)} nhé."
        return {"answer": text + "\n" + data["note"], "links": data["links"]}
    if intent == "campaigns":
        cards = data["campaigns"]
        parts = []
        if data.get("eligible_from"):
            parts.append(f"Bạn có thể hiến lại từ {_d(data['eligible_from'])}, nên mình chỉ gợi ý các đợt từ ngày đó.")
        if data.get("area") and data.get("area_found") is False:
            parts.append(f"Chưa có đợt phù hợp ở {data['area']}; dưới đây là các đợt khác đang mở.")
        if cards:
            parts.append(f"Có {data['total_found']} đợt phù hợp" + (", xếp theo khoảng cách từ vị trí của bạn."
                                                                    if data.get("used_location") else ", sớm nhất trước."))
        else:
            parts.append("Hiện chưa có đợt hiến nào phù hợp. Bạn có thể xem bản đồ hoặc quay lại sau.")
        regs = data["excluded"]["already_registered"]
        if regs:
            parts.append("Bạn đã đăng ký: " + "; ".join(f"{r['name']} ({r['status']})" for r in regs) + ".")
        if data.get("ask_area"):
            parts.append("Bạn muốn tìm ở tỉnh/quận nào? Hoặc bấm \"Đợt hiến gần tôi\" để dùng vị trí hiện tại.")
        return {"answer": " ".join(parts), "cards": cards, "links": data["links"]}
    if intent == "my_registrations":
        regs = data["registrations"]
        if not regs:
            return {"answer": "Bạn chưa có đơn đăng ký hiến nào.", "links": data["links"]}
        lines = [f"• {r['code']} — {r['campaign']}, {r['time']}: {r['status']}" for r in regs]
        return {"answer": "Đơn đăng ký hiến của bạn:\n" + "\n".join(lines), "links": data["links"]}
    if intent == "my_patient_requests":
        reqs = data["requests"]
        if not reqs:
            return {"answer": "Bạn chưa gửi yêu cầu cần máu nào.", "links": data["links"]}
        lines = [f"• {r['code']} — {r['hospital']}: {r['status']} (gửi {r['created']})" for r in reqs]
        return {"answer": "Yêu cầu cần máu bạn đã gửi:\n" + "\n".join(lines), "links": data["links"]}
    return {"answer": "", "links": []}


TOOL_OF = {"eligibility": "my_eligibility", "history": "my_donation_history", "precheck": "preliminary_check",
           "my_registrations": "my_registrations", "my_patient_requests": "my_patient_requests",
           "campaigns": "suggest_campaigns"}


def prefetch(question, ctx, intent=None):
    """Tra cứu dữ liệu theo ý định câu hỏi. Trả về (intent, tên công cụ, dữ liệu) hoặc None nếu là câu hỏi kiến thức.
    Dùng cho cả chế độ từ khóa lẫn chế độ AI (đưa sẵn dữ liệu cho mô hình)."""
    intent = intent or detect_intent(question)
    if intent not in TOOL_OF:
        return None
    if intent == "eligibility":
        data = tools.my_eligibility(ctx)
    elif intent == "history":
        data = tools.my_donation_history(ctx)
    elif intent == "precheck":
        data = tools.preliminary_check(ctx, **parse_profile(question))
    elif intent == "my_registrations":
        data = tools.my_registrations(ctx)
    elif intent == "my_patient_requests":
        data = tools.my_patient_requests(ctx)
    else:
        d_from, d_to = extract_time(question, timezone.localdate(ctx.now))
        area = extract_area(question)
        data = tools.suggest_campaigns(ctx, area=area, date_from=d_from and d_from.isoformat(),
                                       date_to=d_to and d_to.isoformat(), time_of_day=time_of_day(question))
        # Không biết người hỏi ở đâu → vẫn liệt kê, nhưng hỏi lại khu vực
        data["ask_area"] = (not area and ctx.lat is None
                            and not (ctx.member and getattr(ctx.user, "province", None)))
    return intent, TOOL_OF[intent], data


def answer(question, ctx, docs=None, pre=None):
    pre = pre if pre is not None else prefetch(question, ctx)
    if pre is None:
        docs = knowledge.search(question) if docs is None else docs
        if not docs:
            return {"answer": FALLBACK_ANSWER, "source": None, "intent": "unknown"}
        top = docs[0]
        from .llm import plain_text

        return {"answer": plain_text(top["text"]), "source": knowledge.cite(top), "intent": "faq",
                "doc_ids": [top["id"]]}
    intent, _, data = pre
    if data.get("login_required"):                    # chưa đăng nhập: không trích nguồn, không kèm kiến thức chung
        return {**render(intent, data), "intent": intent, "source": None}
    return {**render(intent, data), "intent": intent, "source": "Dữ liệu hệ thống"}
