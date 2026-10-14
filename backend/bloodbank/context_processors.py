"""Ngữ cảnh dùng chung: menu theo vai trò (Ch.7 mục 7.2, 7.11), bệnh viện đang làm việc, số thông báo chưa đọc.

Menu chỉ hiện mục mà vai trò hiện tại mở được theo bảng `bloodbank/access.py`.
"""
from django.urls import reverse

from bloodbank import access
from bloodbank.models import Donation, Notification, PatientRequest, RequestOffer
from bloodbank.permissions import assignments, current_staff

# (nhóm, nhãn, url name, icon)
HOSPITAL_NAV = [
    ("", "Tổng quan", "bloodbank:hospital_dashboard", "layout-dashboard"),
    ("Hiến máu", "Đợt hiến máu", "bloodbank:hospital_campaigns", "calendar-heart"),
    ("Hiến máu", "Tra cứu người hiến", "bloodbank:donor_lookup", "user-search"),
    ("Hiến máu", "Báo cáo tiếp nhận", "bloodbank:donation_report", "chart-column"),
    ("Kho máu", "Chờ xét nghiệm", "bloodbank:lab_queue", "flask-conical"),
    ("Kho máu", "Tồn kho", "bloodbank:stock", "warehouse"),
    ("Kho máu", "Lịch sử biến động", "bloodbank:stock_ledger", "history"),
    ("Kho máu", "Nhu cầu & thiếu hụt", "bloodbank:demands", "clipboard-list"),
    ("Liên viện", "Tìm nguồn liên viện", "bloodbank:source_search", "search"),
    ("Liên viện", "Yêu cầu đã gửi", "bloodbank:support_requests", "send"),
    ("Liên viện", "Đề nghị đến bệnh viện", "bloodbank:incoming_offers", "inbox"),
    ("Người cần máu", "Yêu cầu cần máu", "bloodbank:hospital_patient_requests", "heart-handshake"),
    ("Bệnh viện", "Thông tin bệnh viện", "bloodbank:hospital_info", "building-2"),
    ("Bệnh viện", "Nhân viên", "bloodbank:hospital_staff", "users"),
    ("Bệnh viện", "Danh mục chế phẩm", "bloodbank:catalog", "package"),
    ("Bệnh viện", "Nhật ký bệnh viện", "bloodbank:hospital_audit", "scroll-text"),
]

ADMIN_NAV = [
    ("Quản trị", "Thống kê hệ thống", "bloodbank:admin_stats", "chart-pie"),
    ("Quản trị", "Người dùng", "bloodbank:admin_users", "users"),
    ("Quản trị", "Bệnh viện", "bloodbank:admin_hospitals", "hospital"),
    ("Quản trị", "Danh mục chế phẩm", "bloodbank:catalog", "package"),
    ("Hệ thống", "Phân quyền", "bloodbank:admin_permissions", "key-round"),
    ("Hệ thống", "Cấu hình", "bloodbank:admin_settings", "sliders-horizontal"),
    ("Hệ thống", "Nhật ký hệ thống", "bloodbank:admin_audit", "scroll-text"),
]


def _nav(user, items, counts=None):
    groups = []
    for group, label, url, icon in items:
        if not access.can_open(user, url):
            continue
        if not groups or groups[-1]["name"] != group:
            groups.append({"name": group, "items": []})
        groups[-1]["items"].append({"label": label, "url": url, "icon": icon, "href": reverse(url),
                                    "count": (counts or {}).get(url)})
    return groups


def workspace(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"unread_count": 0}

    staff = current_staff(request)
    ctx = {
        "unread_count": Notification.objects.filter(user=user, channel="in_app", read_at__isnull=True).count(),
        "current_staff": staff,
        "current_hospital": staff.hospital if staff else None,
        "staff_assignments": list(assignments(user)) if staff else [],
        "is_staff_user": staff is not None,
        "workspace_mode": "admin" if user.role == access.ADMIN else "hospital",
        "role_label": access.ROLE_LABELS.get(user.role),
    }
    if staff:
        counts = {
            "bloodbank:incoming_offers": RequestOffer.objects.filter(supplier_hospital=staff.hospital, status="pending").count(),
            "bloodbank:lab_queue": Donation.objects.filter(hospital=staff.hospital, status="confirmed",
                                                           lab_status="pending").count(),
            "bloodbank:hospital_patient_requests": PatientRequest.objects.filter(
                hospital=staff.hospital, status__in=["submitted", "verifying"]).count(),
        }
        ctx["hospital_nav"] = _nav(user, HOSPITAL_NAV, counts)
    if user.role == access.ADMIN:
        ctx["admin_nav"] = _nav(user, ADMIN_NAV)
    return ctx
