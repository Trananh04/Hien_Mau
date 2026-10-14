"""Cấu hình phân quyền màn hình — NGUỒN DUY NHẤT quyết định vai trò nào mở được màn hình nào.

Ba vai trò tách biệt, mỗi vai trò một trang đăng nhập riêng:
  member   — Người dùng (người hiến máu, người nhà bệnh nhân)   → /dang-nhap/
  hospital — Nhân viên bệnh viện (một vai trò chung)             → /benh-vien/dang-nhap/
  admin    — Quản trị hệ thống                                   → /quan-tri/dang-nhap/

Mọi route phải được khai báo trong SCREENS. ScreenAccessMiddleware kiểm tra MỌI request theo bảng này;
route chưa khai báo bị chặn (fail-closed). Muốn mở/đóng một màn hình cho vai trò nào, sửa cột `roles` tại đây.
Màn hình Quản trị → Phân quyền hiển thị đúng bảng này.
"""
from dataclasses import dataclass

PUBLIC, MEMBER, HOSPITAL, ADMIN = "public", "member", "hospital", "admin"
SIGNED_IN = (MEMBER, HOSPITAL, ADMIN)
WORKSPACE = (HOSPITAL, ADMIN)

# (mã vai trò, nhãn, trang đăng nhập, trang chủ sau khi đăng nhập, icon)
ROLES = [
    (MEMBER, "Người dùng", "accounts:login", "bloodbank:home", "user-round"),
    (HOSPITAL, "Nhân viên bệnh viện", "accounts:hospital_login", "bloodbank:hospital_dashboard", "hospital"),
    (ADMIN, "Quản trị hệ thống", "accounts:admin_login", "bloodbank:admin_stats", "shield-check"),
]
ROLE_LABELS = {code: label for code, label, *_ in ROLES}
LOGIN_URLS = {code: login for code, _, login, *_ in ROLES}
HOME_URLS = {code: home for code, _, _, home, _ in ROLES}


@dataclass(frozen=True)
class Screen:
    code: str
    title: str
    area: str
    roles: tuple
    routes: tuple


S = Screen
SCREENS = [
    # ---------------------------------------------------------------- Công khai
    S("SCR-01", "Trang chủ & chatbot", "Công khai", (PUBLIC,), ("bloodbank:home", "bloodbank:chatbot")),
    S("SCR-02", "Danh sách đợt hiến", "Công khai", (PUBLIC,), ("bloodbank:campaigns",)),
    S("SCR-03", "Chi tiết đợt hiến (đăng ký hiến: chỉ Người dùng)", "Công khai", (PUBLIC,), ("bloodbank:campaign_detail",)),
    S("SCR-04", "Bản đồ điểm hiến", "Công khai", (PUBLIC,), ("bloodbank:map", "bloodbank:map_data")),
    S("SCR-06", "Đăng nhập, đăng ký, khôi phục mật khẩu", "Công khai", (PUBLIC,), (
        "accounts:login", "accounts:hospital_login", "accounts:admin_login", "accounts:register",
        "accounts:forgot_password", "accounts:reset_password", "accounts:verify_email")),

    # ---------------------------------------------------------------- Người dùng
    S("SCR-07", "Hồ sơ cá nhân", "Người dùng", (MEMBER,), ("bloodbank:profile", "accounts:resend_verification")),
    S("SCR-08", "Đơn đăng ký hiến của tôi", "Người dùng", (MEMBER,), (
        "bloodbank:my_registrations", "bloodbank:cancel_registration", "bloodbank:reregister")),
    S("SCR-09", "Lịch sử hiến máu", "Người dùng", (MEMBER,), ("bloodbank:my_history", "bloodbank:my_donation_detail")),
    S("SCR-11", "Gửi yêu cầu cần máu", "Người dùng", (MEMBER,), ("bloodbank:patient_request_new",)),
    S("SCR-12", "Yêu cầu cần máu của tôi", "Người dùng", (MEMBER,), (
        "bloodbank:my_patient_requests", "bloodbank:my_patient_request_detail", "bloodbank:cancel_patient_request")),

    # ---------------------------------------------------------------- Dùng chung khi đã đăng nhập
    S("SCR-14", "Thông báo", "Dùng chung", SIGNED_IN, ("bloodbank:notifications", "bloodbank:notifications_read")),
    S("SCR-15", "Tài khoản công tác (hồ sơ, đổi mật khẩu)", "Dùng chung", WORKSPACE, ("bloodbank:work_account",)),
    S("SCR-16", "Đăng xuất", "Dùng chung", SIGNED_IN, ("accounts:logout",)),

    # ---------------------------------------------------------------- Bệnh viện
    S("SCR-20", "Tổng quan bệnh viện", "Bệnh viện", (HOSPITAL,), ("bloodbank:hospital_dashboard", "bloodbank:select_hospital")),
    S("SCR-21", "Quản lý đợt hiến", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:hospital_campaigns", "bloodbank:hospital_campaign_create", "bloodbank:hospital_campaign_detail",
        "bloodbank:hospital_campaign_edit", "bloodbank:hospital_campaign_action", "bloodbank:registration_action")),
    S("SCR-24", "Điểm hiến (check-in, ghi nhận)", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:checkin", "bloodbank:walk_in", "bloodbank:checkin_action", "bloodbank:record_donation")),
    S("SCR-25", "Lượt hiến (xem, hủy hiệu lực, sửa)", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:hospital_donation_detail", "bloodbank:donation_manage")),
    S("SCR-26", "Tra cứu người hiến", "Bệnh viện", (HOSPITAL,), ("bloodbank:donor_lookup",)),
    S("SCR-27", "Báo cáo tiếp nhận", "Bệnh viện", (HOSPITAL,), ("bloodbank:donation_report",)),
    S("SCR-29", "Chờ xét nghiệm → nhập kho", "Bệnh viện", (HOSPITAL,), ("bloodbank:lab_queue", "bloodbank:lab_result")),
    S("SCR-30", "Tồn kho", "Bệnh viện", (HOSPITAL,), ("bloodbank:stock", "bloodbank:stock_settings", "bloodbank:stock_threshold")),
    S("SCR-31", "Phiếu nhập / xuất / điều chỉnh", "Bệnh viện", (HOSPITAL,), ("bloodbank:stock_txn",)),
    S("SCR-32", "Lịch sử biến động kho", "Bệnh viện", (HOSPITAL,), ("bloodbank:stock_ledger",)),
    S("SCR-33", "Nhu cầu & thiếu hụt", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:demands", "bloodbank:demand_edit", "bloodbank:demand_close", "bloodbank:donor_callout")),
    S("SCR-34", "Tìm nguồn liên viện", "Bệnh viện", (HOSPITAL,), ("bloodbank:source_search",)),
    S("SCR-35", "Yêu cầu hỗ trợ đã gửi", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:support_requests", "bloodbank:support_request_create", "bloodbank:support_request_detail",
        "bloodbank:support_request_action", "bloodbank:support_request_for_offer", "bloodbank:offer_open")),
    S("SCR-36", "Đề nghị đến bệnh viện", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:incoming_offers", "bloodbank:offer_detail", "bloodbank:offer_action")),
    S("SCR-37", "Xử lý yêu cầu cần máu", "Bệnh viện", (HOSPITAL,), (
        "bloodbank:hospital_patient_requests", "bloodbank:hospital_patient_request_detail",
        "bloodbank:hospital_patient_request_action")),
    S("SCR-38", "Nhân viên bệnh viện (xem)", "Bệnh viện", (HOSPITAL,), ("bloodbank:hospital_staff",)),
    S("SCR-39", "Thông tin bệnh viện", "Bệnh viện", (HOSPITAL,), ("bloodbank:hospital_info",)),
    S("SCR-40", "Nhật ký bệnh viện", "Bệnh viện", (HOSPITAL,), ("bloodbank:hospital_audit",)),
    S("SCR-52", "Danh mục chế phẩm (bệnh viện xem, quản trị sửa)", "Bệnh viện / Quản trị", WORKSPACE, ("bloodbank:catalog",)),

    # ---------------------------------------------------------------- Quản trị hệ thống
    S("SCR-54", "Thống kê toàn hệ thống", "Quản trị", (ADMIN,), ("bloodbank:admin_stats",)),
    S("SCR-50", "Người dùng", "Quản trị", (ADMIN,), ("bloodbank:admin_users",)),
    S("SCR-51", "Bệnh viện & tài khoản nhân viên", "Quản trị", (ADMIN,), (
        "bloodbank:admin_hospitals", "bloodbank:admin_hospital_create", "bloodbank:admin_hospital_edit")),
    S("SCR-53", "Nhật ký hệ thống", "Quản trị", (ADMIN,), ("bloodbank:admin_audit",)),
    S("SCR-55", "Cấu hình hệ thống", "Quản trị", (ADMIN,), ("bloodbank:admin_settings",)),
    S("SCR-56", "Phân quyền màn hình", "Quản trị", (ADMIN,), ("bloodbank:admin_permissions",)),
]
del S

ROUTE_ROLES = {}
for _screen in SCREENS:
    for _route in _screen.routes:
        assert _route not in ROUTE_ROLES, f"Route {_route} khai báo 2 lần"
        ROUTE_ROLES[_route] = _screen.roles


def roles_for(route_name):
    """Vai trò được mở route; None = route chưa khai báo (bị chặn)."""
    return ROUTE_ROLES.get(route_name)


def can_open(user, route_name):
    roles = roles_for(route_name)
    if roles is None:
        return False
    if PUBLIC in roles:
        return True
    return bool(user and user.is_authenticated and user.is_active and user.role in roles)


def login_url_for(roles):
    """Trang đăng nhập đúng cổng cho một màn hình (vai trò đầu tiên được phép)."""
    for code in roles:
        if code in LOGIN_URLS:
            return LOGIN_URLS[code]
    return LOGIN_URLS[MEMBER]


def home_for(user):
    return HOME_URLS.get(getattr(user, "role", None), "bloodbank:home")
