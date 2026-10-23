"""Ngữ cảnh dùng chung: menu theo vai trò (Ch.7 mục 7.2, 7.11), bệnh viện đang làm việc, số thông báo chưa đọc.

Menu chỉ hiện mục mà vai trò hiện tại mở được theo bảng `bloodbank/access.py`.
"""
from django.urls import reverse

from bloodbank import access
from bloodbank.models import Campaign, Donation, Notification, PatientRequest, Registration, RequestOffer
from bloodbank.permissions import current_staff

# (nhóm, nhãn, url name, icon)
HOSPITAL_NAV = [
    ("", "Tổng quan", "bloodbank:hospital_dashboard", "layout-dashboard"),
    ("Người cần máu", "Yêu cầu cần máu", "bloodbank:hospital_patient_requests", "heart-handshake"),
    ("Hiến máu", "Đợt hiến máu", "bloodbank:hospital_campaigns", "calendar-heart"),
    ("Hiến máu", "Tra cứu người hiến", "bloodbank:donor_lookup", "user-search"),
    ("Hiến máu", "Báo cáo tiếp nhận", "bloodbank:donation_report", "chart-column"),
    ("Kho máu", "Chờ xét nghiệm", "bloodbank:lab_queue", "flask-conical"),
    ("Kho máu", "Tồn kho", "bloodbank:stock", "warehouse"),
    ("Kho máu", "Lịch sử biến động", "bloodbank:stock_ledger", "history"),
    ("Kho máu", "Dự báo thiếu hụt", "bloodbank:demands", "chart-line"),
    ("Bệnh viện", "Thông tin bệnh viện", "bloodbank:hospital_info", "building-2"),
    ("Bệnh viện", "Nhân viên", "bloodbank:hospital_staff", "users"),
    ("Bệnh viện", "Danh mục chế phẩm", "bloodbank:catalog", "package"),
    ("Bệnh viện", "Nhật ký bệnh viện", "bloodbank:hospital_audit", "scroll-text"),
]

ADMIN_NAV = [
    ("Quản trị", "Tổng quan", "bloodbank:admin_stats", "layout-dashboard"),
    ("Quản trị", "Người dùng", "bloodbank:admin_users", "users"),
    ("Quản trị", "Bệnh viện", "bloodbank:admin_hospitals", "hospital"),
    ("Quản trị", "Danh mục chế phẩm", "bloodbank:catalog", "package"),
    ("Hệ thống", "Phân quyền", "bloodbank:admin_permissions", "key-round"),
    ("Hệ thống", "Trợ lý hỏi đáp", "bloodbank:admin_assistant", "message-circle-heart"),
    ("Hệ thống", "Cấu hình", "bloodbank:admin_settings", "sliders-horizontal"),
    ("Hệ thống", "Nhật ký hệ thống", "bloodbank:admin_audit", "scroll-text"),
]


def _nav(user, items, counts=None, request=None):
    groups = []
    for group, label, url, icon in items:
        if not access.can_open(user, url):
            continue
        if not groups or groups[-1]["name"] != group:
            groups.append({"name": group, "items": []})
        groups[-1]["items"].append({"label": label, "url": url, "icon": icon, "href": reverse(url),
                                    "count": (counts or {}).get(url)})
    closed = set(request.COOKIES.get("ws_closed", "").split(".")) if request else set()
    path = request.path if request else ""
    for g in groups:   # tổng số chờ xử lý của nhóm: hiện cạnh tên nhóm khi nhóm đang thu gọn
        g["count"] = sum(i["count"] or 0 for i in g["items"])
        g["key"] = _slug(g["name"] or "home")
        has_active = any(path.startswith(i["href"]) for i in g["items"])
        g["open"] = has_active or g["key"] not in closed      # nhóm chứa trang hiện tại luôn mở
    return groups


def _slug(text):
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip("-")


def workspace(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"unread_count": 0}

    staff = current_staff(request)
    ctx = {
        "unread_count": Notification.objects.filter(user=user, channel="in_app", read_at__isnull=True).count(),
        "current_staff": staff,
        "current_hospital": staff.hospital if staff else None,
        "is_staff_user": staff is not None,
        "workspace_mode": "admin" if user.role == access.ADMIN else "hospital",
        "role_label": access.ROLE_LABELS.get(user.role),
        "ws_collapsed": request.COOKIES.get("ws_collapsed") == "1",
    }
    if staff:
        counts = {
            "bloodbank:incoming_offers": RequestOffer.objects.filter(supplier_hospital=staff.hospital, status="pending").count(),
            "bloodbank:lab_queue": Donation.objects.filter(hospital=staff.hospital, status="confirmed",
                                                           lab_status="pending").count(),
            "bloodbank:hospital_patient_requests": PatientRequest.objects.filter(
                hospital=staff.hospital, status__in=PatientRequest.WAITING_STATUSES).count(),
            # Đơn đăng ký chờ duyệt trong các đợt đang tiếp nhận; hàng liên viện đang trên đường tới
            "bloodbank:hospital_campaigns": Registration.objects.filter(
                campaign__hospital=staff.hospital, status=Registration.Status.PENDING,
                campaign__status__in=Campaign.RUNNING_STATUSES).count(),
            "bloodbank:support_requests": RequestOffer.objects.filter(
                request__requesting_hospital=staff.hospital, status="in_transit").count(),
        }
        ctx["hospital_nav"] = _nav(user, HOSPITAL_NAV, counts, request)
    if user.role == access.ADMIN:
        from bloodbank.services.admin import urgent_alert_count

        ctx["admin_nav"] = _nav(user, ADMIN_NAV, {"bloodbank:admin_stats": urgent_alert_count()}, request)
    return ctx
