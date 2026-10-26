"""Công cụ truy vấn dữ liệu cho trợ lý — CHỈ ĐỌC, luôn giới hạn theo người đang hỏi (ctx.user).

Không công cụ nào nhận id người dùng / bệnh viện từ phía mô hình: dữ liệu cá nhân chỉ lấy theo phiên đăng nhập,
nên câu hỏi kiểu "đơn của người khác" không thể trả về dữ liệu của người khác. Không trả tên bệnh nhân,
số điện thoại hay ghi chú — chỉ mã, trạng thái, bệnh viện, thời gian và đường dẫn.
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.provinces import normalize_province
from bloodbank.content import _norm
from bloodbank.models import Campaign, PatientRequest, Registration

WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


@dataclass
class Ctx:
    user: object = None          # request.user (có thể ẩn danh)
    lat: float | None = None     # vị trí trình duyệt — chỉ dùng trong request này, không lưu
    lng: float | None = None
    now: datetime = field(default_factory=timezone.now)

    @property
    def member(self):
        u = self.user
        return u is not None and u.is_authenticated and u.role == "member"


def _login_needed(ctx, what):
    """Câu hỏi về dữ liệu của chính người hỏi nhưng chưa có tài khoản Người dùng → câu trả lời cố định, không tra cứu."""
    user = ctx.user
    if user is not None and user.is_authenticated:      # nhân viên bệnh viện / quản trị
        return {"login_required": True, "links": [],
                "message": f"Mục {what} chỉ dành cho tài khoản Người dùng (người hiến máu, người nhà bệnh nhân). "
                           "Bạn đang đăng nhập bằng tài khoản công tác nên mình không tra cứu được."}
    return {"login_required": True,
            "message": f"Bạn chưa đăng nhập nên mình chưa xem được {what}. "
                       "Hãy đăng nhập tài khoản Người dùng rồi hỏi lại, mình sẽ tra cứu ngay cho bạn. "
                       "Chưa có tài khoản? Bạn có thể tạo mới trong khoảng 1 phút.",
            "links": [{"label": "Đăng nhập", "url": reverse("accounts:login")},
                      {"label": "Tạo tài khoản", "url": reverse("accounts:register")}]}


def _km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(math.radians, map(float, (lat1, lng1, lat2, lng2)))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def campaign_card(c, distance=None):
    start, end = timezone.localtime(c.start_time), timezone.localtime(c.end_time)
    return {
        "id": c.pk, "name": c.name, "hospital": c.hospital.name,
        "place": c.location_name, "address": c.address, "province": c.province or c.hospital.province,
        "time": f"{start:%H:%M}–{end:%H:%M} {WEEKDAYS[start.weekday()]} {start:%d/%m/%Y}",
        "start": start.isoformat(), "distance_km": distance,
        "url": reverse("bloodbank:campaign_detail", args=[c.pk]),
    }


# ---------------------------------------------------------------- Ngày được hiến lại
def my_eligibility(ctx):
    if not ctx.member:
        return _login_needed(ctx, "ngày bạn được hiến lại")
    from bloodbank.services.badges import next_eligible

    info = next_eligible(ctx.user, ctx.now)
    if info is None:
        return {"has_donation": False,
                "message": "Bạn chưa có lượt hiến nào được bệnh viện xác nhận trên hệ thống, nên có thể đăng ký "
                           "bất kỳ đợt hiến nào đang mở (bác sĩ vẫn khám sàng lọc trước khi hiến).",
                "links": [{"label": "Xem đợt hiến", "url": reverse("bloodbank:campaigns")}]}
    last = info["last"]
    return {
        "has_donation": True, "eligible_from": info["date"].isoformat(), "ready_now": info["ready"],
        "days_left": info["days_left"],
        "last_donation": {"date": timezone.localdate(last.donated_at).isoformat(),
                          "type": last.get_donation_type_display(), "hospital": last.hospital.name},
        "note": "Đây là khuyến nghị khoảng cách tối thiểu; bác sĩ khám sàng lọc quyết định.",
        "links": [{"label": "Lịch sử hiến máu", "url": reverse("bloodbank:my_history")}],
    }


# ---------------------------------------------------------------- Gợi ý đợt hiến
def suggest_campaigns(ctx, area=None, date_from=None, date_to=None, time_of_day=None, limit=3):
    """Đợt đang mở, chưa kết thúc; với Người dùng: bỏ đợt đã đăng ký và đợt kết thúc trước ngày được hiến lại.
    Xếp: gần trước (khi có vị trí) / đúng khu vực trước → sớm trước."""
    limit = max(1, min(int(limit or 3), 6))
    qs = Campaign.objects.public().filter(status=Campaign.Status.OPEN, end_time__gt=ctx.now).order_by("start_time")
    d_from, d_to = _parse_date(date_from), _parse_date(date_to)
    if d_from:
        qs = qs.filter(end_time__date__gte=d_from)
    if d_to:
        qs = qs.filter(start_time__date__lte=d_to)
    campaigns = list(qs[:200])
    if time_of_day in ("morning", "afternoon", "evening"):
        rng = {"morning": (0, 12), "afternoon": (12, 18), "evening": (17, 24)}[time_of_day]
        campaigns = [c for c in campaigns if rng[0] <= timezone.localtime(c.start_time).hour < rng[1]]

    excluded = {"already_registered": [], "before_eligible": 0}
    eligible_from = None
    if ctx.member:
        from bloodbank.services.badges import next_eligible

        info = next_eligible(ctx.user, ctx.now)
        if info and not info["ready"]:
            eligible_from = info["date"]
        mine = {r.campaign_id: r for r in Registration.objects.filter(donor=ctx.user).exclude(status="cancelled")
                .select_related("campaign")}
        kept = []
        for c in campaigns:
            if c.pk in mine:
                excluded["already_registered"].append({"name": c.name, "status": mine[c.pk].get_status_display(),
                                                       "url": reverse("bloodbank:my_registrations")})
            elif eligible_from and timezone.localdate(c.end_time) < eligible_from:
                excluded["before_eligible"] += 1
            else:
                kept.append(c)
        campaigns = kept

    area = normalize_province(area) or area    # tên tỉnh cũ (vd Bình Dương) → tên hiện hành
    area_n = _norm(area or "")
    def text_of(c):
        return _norm(" ".join(filter(None, [c.name, c.location_name, c.address, c.province, c.hospital.name,
                                            c.hospital.address, c.hospital.district, c.hospital.province])))
    matched = [c for c in campaigns if area_n and area_n in text_of(c)]
    area_found = bool(matched) if area_n else None
    if area_n and matched:
        campaigns = matched

    def coords(c):
        if c.latitude is not None:
            return c.latitude, c.longitude
        if c.hospital.latitude is not None:
            return c.hospital.latitude, c.hospital.longitude
        return None

    own_province = _norm(getattr(ctx.user, "province", "") or "") if ctx.member else ""
    rows = []
    for c in campaigns:
        dist = None
        if ctx.lat is not None and ctx.lng is not None and coords(c):
            dist = _km(ctx.lat, ctx.lng, *coords(c))
        same_prov = bool(own_province) and own_province == _norm(c.province or c.hospital.province or "")
        rows.append((c, dist, same_prov))
    rows.sort(key=lambda r: (r[1] is None, r[1] or 0, not r[2], r[0].start_time))
    cards = [campaign_card(c, d) for c, d, _ in rows[:limit]]
    return {
        "campaigns": cards, "total_found": len(rows), "area": area or None, "area_found": area_found,
        "eligible_from": eligible_from.isoformat() if eligible_from else None,
        "excluded": excluded, "used_location": ctx.lat is not None,
        "links": [{"label": "Tất cả đợt hiến", "url": reverse("bloodbank:campaigns")},
                  {"label": "Bản đồ điểm hiến", "url": reverse("bloodbank:map")}],
    }


# ---------------------------------------------------------------- Đơn đăng ký & yêu cầu cần máu của chính mình
def my_registrations(ctx):
    if not ctx.member:
        return _login_needed(ctx, "đơn đăng ký hiến của bạn")
    regs = (Registration.objects.filter(donor=ctx.user).select_related("campaign__hospital")
            .order_by("-campaign__start_time")[:6])
    return {
        "registrations": [{
            "code": r.code, "campaign": r.campaign.name,
            "hospital": r.campaign.hospital.name, "status": r.get_status_display(),
            "time": campaign_card(r.campaign)["time"],
            "upcoming": r.campaign.end_time > ctx.now,
            "url": reverse("bloodbank:campaign_detail", args=[r.campaign_id]),
        } for r in regs],
        "links": [{"label": "Đơn đăng ký của tôi", "url": reverse("bloodbank:my_registrations")}],
    }


def my_patient_requests(ctx):
    if not ctx.member:
        return _login_needed(ctx, "yêu cầu cần máu bạn đã gửi")
    prqs = PatientRequest.objects.filter(requester=ctx.user).select_related("hospital").order_by("-created_at")[:5]
    return {
        # Không trả tên bệnh nhân / SĐT / ghi chú — chỉ thông tin trạng thái
        "requests": [{
            "code": p.request_code, "hospital": p.hospital.name, "status": p.get_status_display(),
            "blood_group": p.blood_group, "units": p.quantity_units,
            "created": timezone.localtime(p.created_at).strftime("%H:%M %d/%m/%Y"),
            "url": reverse("bloodbank:my_patient_request_detail", args=[p.pk]),
        } for p in prqs],
        "links": [{"label": "Yêu cầu cần máu của tôi", "url": reverse("bloodbank:my_patient_requests")},
                  {"label": "Gửi yêu cầu mới", "url": reverse("bloodbank:patient_request_new")}],
    }


# ---------------------------------------------------------------- CHAT-06 Lịch sử hiến máu
def my_donation_history(ctx):
    """Chỉ tính lượt hiến đã được bệnh viện xác nhận (giống trang Lịch sử hiến máu)."""
    if not ctx.member:
        return _login_needed(ctx, "lịch sử hiến máu của bạn")
    from bloodbank.models import Donation
    from bloodbank.services.donations import summarize

    qs = Donation.objects.filter(donor=ctx.user)
    s = summarize(qs)
    recent = qs.filter(status="confirmed").select_related("hospital").order_by("-donated_at")[:5]
    return {
        "confirmed_count": s["count"], "whole_blood_count": s["whole_count"], "whole_blood_ml": s["whole_ml"],
        "component_count": s["component_count"],
        "last_donation": timezone.localdate(s["last"]).isoformat() if s["last"] else None,
        "recent": [{"date": timezone.localdate(d.donated_at).isoformat(), "type": d.get_donation_type_display(),
                    "volume_ml": d.volume_ml, "hospital": d.hospital.name} for d in recent],
        "note": "Chỉ tính các lượt hiến đã được bệnh viện xác nhận.",
        "links": [{"label": "Lịch sử hiến máu", "url": reverse("bloodbank:my_history")}],
    }


# ---------------------------------------------------------------- CHAT-02 Kiểm tra sơ bộ (luật cố định)
def preliminary_check(ctx, age=None, weight_kg=None, gender=None):
    """Đối chiếu thông tin người dùng nêu (hoặc hồ sơ) với ngưỡng THAM KHẢO trong Cấu hình. KHÔNG kết luận "đủ điều
    kiện": chỉ cho biết tiêu chí nào trong/ngoài ngưỡng, còn thiếu gì; bác sĩ khám sàng lọc quyết định."""
    from bloodbank.models import SystemSetting

    g = SystemSetting.get
    user = ctx.user if ctx.member else None
    if age is None and user and user.date_of_birth:
        dob, today = user.date_of_birth, timezone.localdate(ctx.now)
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if gender is None and user and user.gender in ("male", "female"):
        gender = user.gender
    gender = {"nam": "male", "nữ": "female", "nu": "female"}.get(str(gender).lower(), gender) if gender else None
    checks, missing = [], []
    lo, hi = g("donor_min_age"), g("donor_max_age")
    if age is None:
        missing.append("tuổi")
    else:
        try:
            age = int(age)
        except (TypeError, ValueError):
            return {"error": "Tuổi không hợp lệ."}
        checks.append({"criterion": "Tuổi", "value": f"{age} tuổi", "reference": f"{lo}–{hi} tuổi",
                       "within": lo <= age <= hi})
    w_male, w_female = g("donor_min_weight_male_kg"), g("donor_min_weight_female_kg")
    if weight_kg is None:
        missing.append("cân nặng")
    else:
        try:
            weight = float(weight_kg)
        except (TypeError, ValueError):
            return {"error": "Cân nặng không hợp lệ."}
        if gender in ("male", "female"):
            need = w_male if gender == "male" else w_female
            checks.append({"criterion": "Cân nặng", "value": f"{weight:g} kg",
                           "reference": f"≥ {need} kg ({'nam' if gender == 'male' else 'nữ'})", "within": weight >= need})
        elif weight >= max(w_male, w_female):
            checks.append({"criterion": "Cân nặng", "value": f"{weight:g} kg", "reference": f"≥ {w_female}–{w_male} kg",
                           "within": True})
        elif weight < min(w_male, w_female):
            checks.append({"criterion": "Cân nặng", "value": f"{weight:g} kg", "reference": f"≥ {w_female}–{w_male} kg",
                           "within": False})
        else:
            missing.append("giới tính (ngưỡng cân nặng nam và nữ khác nhau)")
    interval = None
    if user:
        from bloodbank.services.donations import interval_warning

        warn = interval_warning(user, ctx.now)
        interval = {"criterion": "Khoảng nghỉ từ lần hiến trước", "within": warn is None,
                    "value": "đủ khoảng nghỉ" if warn is None else f"còn {warn['remaining']} ngày",
                    "reference": f"≥ {warn['min_days']} ngày" if warn else "theo loại hiến gần nhất"}
        checks.append(interval)
    else:
        missing.append("lần hiến gần nhất (đăng nhập để hệ thống tự kiểm tra)")
    outside = [c for c in checks if not c["within"]]
    return {
        "checks": checks, "missing": missing,
        "summary": ("outside_reference" if outside else ("need_more_info" if missing else "within_reference")),
        "note": "Kết quả chỉ là đối chiếu sơ bộ với ngưỡng tham khảo, KHÔNG phải kết luận đủ điều kiện. "
                "Bác sĩ khám sàng lọc tại điểm hiến quyết định.",
        "links": [{"label": "Xem đợt hiến", "url": reverse("bloodbank:campaigns")}],
    }


TOOLS = {
    "suggest_campaigns": suggest_campaigns,
    "my_eligibility": my_eligibility,
    "my_registrations": my_registrations,
    "my_patient_requests": my_patient_requests,
    "my_donation_history": my_donation_history,
    "preliminary_check": preliminary_check,
}
WITH_ARGS = {"suggest_campaigns", "preliminary_check"}

def _fn(name, description, properties=None, required=()):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required)}}}


# Định nghĩa công cụ gửi cho mô hình (định dạng Ollama /api/chat). Schema giữ tối giản — mô hình nhỏ điền đúng hơn khi
# tham số đều tùy chọn và có mô tả cụ thể; giá trị sai kiểu được run_tool chuẩn hóa / loại bỏ.
TOOL_SPECS = [
    _fn("suggest_campaigns",
        "Tìm đợt hiến máu đang mở đăng ký. Dùng khi người dùng hỏi về đợt hiến, lịch hiến, nơi hiến máu, đợt gần họ.",
        {"area": {"type": "string", "description": "Địa danh người dùng nêu: quận/huyện, tỉnh, bệnh viện "
                                                    "(vd 'Cầu Giấy', 'Đà Nẵng'). Bỏ trống nếu không nêu."},
         "date_from": {"type": "string", "description": "Ngày bắt đầu khoảng tìm, dạng YYYY-MM-DD."},
         "date_to": {"type": "string", "description": "Ngày kết thúc khoảng tìm, dạng YYYY-MM-DD."},
         "time_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"],
                         "description": "Buổi: sáng / chiều / tối."},
         "limit": {"type": "integer", "description": "Số đợt trả về, 1–6. Mặc định 3."}}),
    _fn("my_eligibility", "Ngày sớm nhất người đang hỏi được hiến lại. Chỉ cho chính người đang đăng nhập."),
    _fn("my_registrations", "Các đơn đăng ký hiến máu của chính người đang hỏi và trạng thái (chờ duyệt, đã duyệt...)."),
    _fn("my_patient_requests", "Trạng thái các yêu cầu cần máu mà chính người đang hỏi đã gửi (mã PR-...)."),
    _fn("my_donation_history", "Lịch sử hiến máu của chính người đang hỏi: số lần đã xác nhận, tổng ml, lần gần nhất."),
    _fn("preliminary_check",
        "Đối chiếu SƠ BỘ tuổi, cân nặng, giới tính với ngưỡng tham khảo khi người dùng hỏi có hiến được không. "
        "Không bao giờ kết luận đủ điều kiện; thiếu thông tin thì hỏi lại người dùng.",
        {"age": {"type": "integer", "description": "Tuổi người dùng nêu."},
         "weight_kg": {"type": "number", "description": "Cân nặng (kg)."},
         "gender": {"type": "string", "enum": ["male", "female"], "description": "Giới tính nếu người dùng nêu."}}),
]
PARAMS = {t["function"]["name"]: t["function"]["parameters"]["properties"] for t in TOOL_SPECS}


def _coerce(value, spec):
    """Giá trị mô hình điền → đúng kiểu trong schema; sai kiểu / ngoài enum → None (coi như không nêu)."""
    if value in (None, "", "null", "None"):
        return None
    try:
        if spec["type"] == "integer":
            value = int(float(value))
        elif spec["type"] == "number":
            value = float(str(value).replace(",", "."))
        else:
            value = str(value).strip()[:100]
    except (TypeError, ValueError):
        return None
    if "enum" in spec and value not in spec["enum"]:
        return None
    return value


def run_tool(name, args, ctx):
    """Chạy công cụ theo tên mô hình yêu cầu. Chỉ nhận tham số khai báo trong schema; công cụ lạ / tham số hỏng → trả
    lỗi cho mô hình (không raise), để vòng gọi tiếp tục và mô hình tự sửa."""
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"Không có công cụ {name}."}
    spec = PARAMS[name]
    clean = {k: _coerce(v, spec[k]) for k, v in (args if isinstance(args, dict) else {}).items() if k in spec}
    clean = {k: v for k, v in clean.items() if v is not None}
    try:
        return fn(ctx, **clean) if name in WITH_ARGS else fn(ctx)
    except (TypeError, ValueError):
        return {"error": "Tham số không hợp lệ."}


def week_range(today, phrase):
    """Khoảng ngày cho cụm từ thời gian thường gặp (chế độ từ khóa)."""
    wd = today.weekday()
    if phrase == "today":
        return today, today
    if phrase == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if phrase == "weekend":
        if wd == 6:                      # hôm nay Chủ nhật → chỉ còn hôm nay
            return today, today
        sat = today + timedelta(days=5 - wd)
        return sat, sat + timedelta(days=1)
    if phrase == "this_week":
        return today, today + timedelta(days=6 - wd)
    if phrase == "next_week":
        start = today + timedelta(days=7 - wd)
        return start, start + timedelta(days=6)
    return None, None
