"""Thẻ template dùng chung: icon Lucide, chip nhóm máu, nhãn trạng thái, định dạng giờ Việt Nam."""
from decimal import Decimal

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import urlencode

from accounts.models import display_phone

register = template.Library()

# Màu nhãn theo trạng thái — dùng nhất quán trên mọi màn hình
STATUS_TONES = {
    # đợt hiến
    "draft": "neutral", "open": "ok", "closed": "warn", "completed": "info", "cancelled": "neutral",
    # đơn đăng ký
    "pending": "warn", "approved": "info", "rejected": "danger", "attended": "info", "donated": "ok",
    "not_donated": "neutral", "no_show": "neutral",
    # lượt hiến
    "confirmed": "ok", "voided": "danger",
    # nhu cầu / yêu cầu
    "active": "ok", "fulfilled": "ok", "in_progress": "info", "partially_fulfilled": "warn", "expired": "neutral",
    "accepted": "info", "in_transit": "info", "failed": "danger",
    "submitted": "warn", "verifying": "info", "verified": "ok", "processing": "info",
    # tài khoản / bệnh viện
    "locked": "danger", "deleted": "neutral", "inactive": "neutral",
    # ưu tiên
    "low": "neutral", "normal": "info", "high": "warn", "urgent": "danger",
}


@register.simple_tag
def icon(name, size=None, cls=""):
    # Kích thước bằng class (ui.css: .icon-14 … .icon-26) — không dùng style inline (CSP không có 'unsafe-inline')
    classes = " ".join(c for c in (cls, f"icon-{int(size)}" if size else "") if c)
    return format_html('<i data-lucide="{}" class="{}" aria-hidden="true"></i>', name, classes)


@register.simple_tag
def map_head():
    """CSS bản đồ + cấu hình Goong cho maps.js (Map key chỉ dùng hiển thị bản đồ; giới hạn tên miền ở account.goong.io).
    Chưa cấu hình GOONG_MAP_KEY → maps.js dùng ô bản đồ OpenStreetMap."""
    from django.conf import settings
    from django.templatetags.static import static
    from django.urls import reverse

    return format_html(
        '<link rel="stylesheet" href="{}">'
        '<meta name="map-config" data-map-key="{}" data-suggest-url="{}" data-place-url="{}" data-reverse-url="{}" '
        'data-route-url="{}" data-distances-url="{}">',
        static("vendor/maplibre/maplibre-gl.css"), settings.GOONG_MAP_KEY, reverse("bloodbank:geo_suggest"),
        reverse("bloodbank:geo_place"), reverse("bloodbank:geo_reverse"), reverse("bloodbank:geo_route"),
        reverse("bloodbank:geo_distances"),
    )


@register.simple_tag
def map_scripts():
    from django.templatetags.static import static

    return format_html('<script src="{}"></script><script src="{}"></script>',
                       static("vendor/maplibre/maplibre-gl.js"), static("js/maps.js"))


@register.filter
def back_button(url):
    """Nút "Quay lại" đầu trang khu làm việc; trang con khai báo `{% block back %}<url trang cha>{% endblock %}`."""
    url = (url or "").strip()
    if not url:
        return ""
    return format_html('<a href="{}" class="ws-back">{} Quay lại</a>', url, icon("arrow-left", 16))


@register.simple_tag
def blood(value, size=""):
    if not value:
        return format_html('<span class="blood unknown {}" title="Chưa rõ nhóm máu"><span>?</span></span>', size)
    label = value.replace("-", "−")
    neg = " rh-neg" if value.endswith("-") else ""
    return format_html('<span class="blood{} {}" title="Nhóm máu {}"><span>{}</span></span>', neg, size, label, label)


@register.simple_tag
def status_badge(obj_or_value, field="status", label=None):
    if hasattr(obj_or_value, field):
        value = getattr(obj_or_value, field)
        label = label or getattr(obj_or_value, f"get_{field}_display")()
    else:
        value = obj_or_value
        label = label or value
    tone = STATUS_TONES.get(value, "neutral")
    return format_html('<span class="badge {}">{}</span>', tone, label)


@register.filter
def ago(value, now=None):
    """Thời gian tương đối tiếng Việt, một đơn vị: "vừa xong", "5 phút trước", "3 giờ trước", "6 ngày trước",
    "2 tuần trước"; quá 30 ngày → ngày cụ thể (dd/mm/yyyy)."""
    if not value:
        return ""
    seconds = int(((now or timezone.now()) - value).total_seconds())
    if seconds < 60:
        return "vừa xong"
    for limit, unit, size in ((3600, "phút", 60), (86400, "giờ", 3600), (7 * 86400, "ngày", 86400),
                              (30 * 86400, "tuần", 7 * 86400)):
        if seconds < limit:
            return f"{seconds // size} {unit} trước"
    return timezone.localtime(value).strftime("%d/%m/%Y")


@register.filter
def vn_dt(value, fmt="%H:%M %d/%m/%Y"):
    if not value:
        return "—"
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(fmt)


@register.filter
def vn_date(value):
    if not value:
        return "—"
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y")


WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


@register.filter
def weekday_vi(value):
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return WEEKDAYS[value.weekday()]


@register.filter
def vn_time(value):
    return vn_dt(value, "%H:%M")


@register.filter
def dt_input(value):
    """Giá trị cho <input type=datetime-local> theo giờ Việt Nam."""
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime("%Y-%m-%dT%H:%M")


@register.filter
def phone(value):
    return display_phone(value)


@register.filter
def initials(name):
    parts = (name or "?").split()
    if len(parts) >= 2:
        return (parts[-2][0] + parts[-1][0]).upper()
    return parts[0][:2].upper()


@register.filter
def vnum(value):
    """Số có dấu chấm ngăn nghìn kiểu Việt Nam; bỏ phần thập phân .00."""
    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal) and value == value.to_integral():
        value = int(value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    return str(value).replace(".", ",")


@register.filter
def mask_name(name):
    """Ẩn tên nhạy cảm ở danh sách (BR-19)."""
    if not name:
        return "—"
    parts = name.split()
    return " ".join(p[0] + "." for p in parts[:-1]) + (" " if len(parts) > 1 else "") + parts[-1][0] + "***"


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Giữ tham số lọc hiện tại, thay các khóa được truyền vào."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + urlencode(params, doseq=True) if params else "?"


@register.simple_tag(takes_context=True)
def active(context, *prefixes, exact=False):
    path = context["request"].path
    for p in prefixes:
        if (exact and path == p) or (not exact and path.startswith(p)):
            return "active"
    return ""


@register.filter
def get_item(mapping, key):
    if not hasattr(mapping, "get"):
        return None
    return mapping.get(key)


@register.filter
def pct(part, whole):
    try:
        return max(0, min(100, round(100 * float(part) / float(whole), 2)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


ACTION_LABELS = {
    "create": "Tạo mới", "update": "Cập nhật", "status_change": "Đổi trạng thái", "void": "Hủy hiệu lực",
    "access_denied": "Truy cập bị từ chối", "view_sensitive": "Xem dữ liệu nhạy cảm", "export": "Xuất dữ liệu",
    "login": "Đăng nhập", "login_failed": "Đăng nhập sai", "password_reset": "Đặt lại mật khẩu",
    "password_reset_requested": "Yêu cầu đặt lại mật khẩu", "password_changed": "Đổi mật khẩu",
    "email_verified": "Xác thực email", "reserve": "Giữ chỗ kho", "reserve_release": "Giải phóng giữ chỗ",
    "dispatched": "Xuất điều chuyển", "received": "Xác nhận nhận hàng", "reinvite": "Mời lại", "reactivate": "Kích hoạt lại",
    "role_change": "Đổi vai trò", "link_campaign": "Kết nối đợt hiến", "link_support_request": "Liên kết yêu cầu liên viện",
    "lab_result": "Kết quả xét nghiệm", "auto_cancel": "Tự hủy (quá hạn)", "escalate": "Nhắc khẩn",
    "donor_callout": "Kêu gọi người hiến", "login_wrong_portal": "Đăng nhập sai cổng",
    "assistant_query": "Hỏi trợ lý", "emergency_start": "Báo ca khẩn",
}

ENTITY_LABELS = {
    "users": "Tài khoản", "hospitals": "Bệnh viện", "staffs": "Phân công", "campaigns": "Đợt hiến",
    "registrations": "Đơn đăng ký", "donations": "Lượt hiến", "products": "Chế phẩm", "product_specs": "Quy cách",
    "stocks": "Tồn kho", "stock_txns": "Sổ kho", "demands": "Nhu cầu", "hospital_requests": "Yêu cầu hỗ trợ",
    "request_offers": "Đề nghị", "patient_requests": "Yêu cầu cần máu", "system_settings": "Cấu hình", "route": "Đường dẫn",
    "donor_callouts": "Lời mời người hiến", "assistant": "Trợ lý",
}

# Cột "Nội dung" của nhật ký: chỉ những trường có ý nghĩa nghiệp vụ, bỏ mã nội bộ / dấu thời gian kỹ thuật
AUDIT_FIELDS = {
    "status": "Trạng thái", "lab_status": "Xét nghiệm", "blood_group": "Nhóm máu", "lab_blood_group": "Nhóm máu XN",
    "volume_ml": "Thể tích (ml)", "quantity_change": "Số lượng", "quantity_after": "Tồn sau", "quantity_needed": "Cần",
    "quantity_requested": "Xin", "required_quantity": "Cần", "quantity_units": "Số đơn vị", "priority": "Ưu tiên",
    "txn_type": "Loại phiếu", "reason": "Lý do", "reason_note": "Ghi chú", "void_reason": "Lý do hủy",
    "reject_reason": "Lý do từ chối", "failure_reason": "Lý do", "lab_note": "Ghi chú XN", "role": "Vai trò",
    "level": "Nhắc tới", "min_stock_level": "Tồn tối thiểu", "shareable_quantity": "Có thể chia sẻ", "recipients": "Số người nhận",
    "request_code": "Mã yêu cầu", "path": "Đường dẫn", "portal": "Cổng", "fields": "Trường đã xem", "full_name": "Họ tên",
    "value": "Giá trị", "setting_key": "Cấu hình", "mode": "Chế độ",
}
AUDIT_VALUES = {
    "pending": "chờ", "approved": "đã duyệt", "rejected": "từ chối", "cancelled": "đã hủy", "expired": "hết hạn",
    "confirmed": "đã xác nhận", "voided": "đã hủy", "passed": "đạt", "failed": "không đạt", "active": "đang mở",
    "closed": "đã đóng", "fulfilled": "đã đủ", "verified": "đã xác minh", "receive": "nhập", "issue": "xuất",
    "adjust": "điều chỉnh", "urgent": "khẩn", "high": "cao", "normal": "thường", "response_timeout": "quá hạn phản hồi",
    "open": "đang mở", "completed": "hoàn tất", "partially_fulfilled": "đáp ứng một phần", "in_progress": "đang xử lý",
    "member": "người dùng", "staff": "nhân viên", "admin": "quản trị", "hospital": "bệnh viện", "stock": "bổ sung kho",
    "online": "trực tuyến", "walk_in": "tại chỗ", "True": "có", "False": "không",
}


def _audit_val(v):
    if v is None or v == "":
        return "—"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    v = str(v)
    return AUDIT_VALUES.get(v, v if len(v) <= 60 else v[:57] + "…")


@register.filter
def audit_summary(log):
    """Danh sách "Trường: cũ → mới" (cập nhật) hoặc "Trường: giá trị" (tạo mới / sự kiện)."""
    old, new = log.old_values or {}, log.new_values or {}
    out = []
    for k, label in AUDIT_FIELDS.items():
        if k in old and k in new:
            if old[k] != new[k]:
                out.append(f"{label}: {_audit_val(old[k])} → {_audit_val(new[k])}")
        elif k in new and new[k] not in (None, ""):
            out.append(f"{label}: {_audit_val(new[k])}")
        elif k in old and old[k] not in (None, ""):
            out.append(f"{label}: {_audit_val(old[k])}")
    return out


@register.filter
def action_label(value):
    return ACTION_LABELS.get(value, value)


@register.filter
def entity_label(value):
    return ENTITY_LABELS.get(value, value)


@register.filter
def absval(value):
    try:
        return abs(value)
    except TypeError:
        return value


@register.filter
def setting(key):
    """Giá trị cấu hình hệ thống hiện hành: {{ "khoa"|setting }}."""
    from bloodbank.models import SystemSetting

    return SystemSetting.get(key)


@register.filter
def vn_since(value):
    """Khoảng thời gian đã qua bằng tiếng Việt: "12 ngày", "3 tuần", "2 tháng", "1 năm 2 tháng"."""
    if not value:
        return ""
    from django.utils import timezone

    days = (timezone.localdate() - timezone.localdate(value)).days if hasattr(value, "tzinfo") else (
        timezone.localdate() - value).days
    if days <= 0:
        return "hôm nay"
    if days < 14:
        return f"{days} ngày"
    if days < 60:
        return f"{days // 7} tuần"
    months = days // 30
    if months < 12:
        return f"{months} tháng"
    years, rest = divmod(months, 12)
    return f"{years} năm" + (f" {rest} tháng" if rest else "")
