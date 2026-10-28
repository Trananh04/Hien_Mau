"""Trang đích của một thông báo — dùng chung cho danh sách thông báo trong ứng dụng và nút "Xem chi tiết" trong email."""
from django.urls import reverse

ENTITY_LINKS = {
    "registrations": lambda n: reverse("bloodbank:my_registrations"),
    "donations": lambda n: reverse("bloodbank:my_donation_detail", args=[n.entity_id]),
    "campaigns": lambda n: reverse("bloodbank:campaign_detail", args=[n.entity_id]),
    "request_offers": lambda n: reverse("bloodbank:offer_open", args=[n.entity_id]),
    "hospital_requests": lambda n: reverse("bloodbank:support_request_detail", args=[n.entity_id]),
    "hospitals": lambda n: reverse("bloodbank:campaigns"),
    "staff": lambda n: reverse("bloodbank:hospital_dashboard"),
    # Lời kêu gọi hiến máu: trang lời mời (bệnh viện, địa chỉ, nút gọi / chỉ đường, đợt hiến kèm theo nếu có)
    "donor_callouts": lambda n: reverse("bloodbank:my_invitation", args=[n.entity_id]),
}

def notification_link(n):
    # Chọn trang theo VAI TRÒ người nhận (không theo danh sách loại thông báo): người dùng luôn tới trang của mình,
    # nhân viên tới trang bệnh viện — tránh liên kết nhầm cổng (vd "đủ điều kiện hiến lại" từng trỏ tới trang bệnh viện)
    staff_side = n.user.role != "member"
    if n.entity_type == "patient_requests":
        name = "hospital_patient_request_detail" if staff_side else "my_patient_request_detail"
        return reverse(f"bloodbank:{name}", args=[n.entity_id])
    if n.entity_type == "donations":
        name = "hospital_donation_detail" if staff_side else "my_donation_detail"
        return reverse(f"bloodbank:{name}", args=[n.entity_id])
    if n.entity_type == "hospitals" and n.user.role == "admin":      # bệnh viện mới đăng ký → trang duyệt
        return reverse("bloodbank:admin_hospital_edit", args=[n.entity_id])
    if n.entity_type == "hospitals" and n.user.role == "hospital":
        return reverse("bloodbank:hospital_dashboard")
    fn = ENTITY_LINKS.get(n.entity_type)
    try:
        return fn(n) if fn else None
    except Exception:
        return None
