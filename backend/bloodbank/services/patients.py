"""UC-PRQ-01..04: yêu cầu từ người cần máu (máy trạng thái Ch.4 mục 4.14)."""
from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES, normalize_phone
from bloodbank.models import Campaign, Hospital, PatientRequest, Product

from .common import (
    BusinessError, audit, business_transaction, create_with_code, notify, notify_hospital_staff, positive_int, require,
    snapshot,
)

P = PatientRequest.Status


def submit(user, data, request=None):
    """UC-PRQ-01: người dùng gửi yêu cầu; trả về mã PR-… ngay khi đã commit."""
    require(user.role == "member", "ERR-AUTH-FORBIDDEN", "Chỉ tài khoản Người dùng mới gửi yêu cầu cần máu được.")
    require(data.get("consent"), "ERR-VALIDATION", "Bạn cần đồng ý chia sẻ thông tin với bệnh viện điều trị.")
    hospital = Hospital.objects.filter(pk=data.get("hospital_id"), status="active").first()
    require(hospital is not None, "ERR-VALIDATION", "Chọn bệnh viện đang điều trị.")
    qty = positive_int(data.get("quantity_units"))
    bg = data.get("blood_group") or None
    require(bg is None or bg in BLOOD_GROUP_VALUES, "ERR-VALIDATION")
    product = Product.objects.filter(pk=data.get("blood_product_id") or None, is_active=True).first()
    phone = normalize_phone(data.get("contact_phone"))
    require(phone and len(phone) >= 11, "ERR-VALIDATION", "Số điện thoại liên hệ không hợp lệ.")
    with business_transaction():
        prq = create_with_code(
            PatientRequest, "request_code", "PR", requester=user, contact_name=data["contact_name"].strip(),
            contact_phone=phone, patient_name=(data.get("patient_name") or "").strip() or None, hospital=hospital,
            blood_group=bg, blood_product=product, quantity_units=qty, needed_by=data.get("needed_by"),
            note=(data.get("note") or "").strip() or None, consent_at=timezone.now(),
        )
        audit(user, prq, "create", new={"request_code": prq.request_code, "hospital_id": hospital.pk,
                                        "quantity_units": qty, "blood_group": bg}, hospital=hospital, request=request)
        notify_hospital_staff(hospital, "patient_request_new", f"Yêu cầu cần máu mới {prq.request_code}",
                              f"Cần {qty} đơn vị{(' nhóm ' + bg) if bg else ''}. Vui lòng xác minh.", entity=prq)
        notify(user, "patient_request_submitted", f"Đã tiếp nhận yêu cầu {prq.request_code}",
               "Bệnh viện điều trị sẽ xác minh và liên hệ theo số điện thoại bạn cung cấp.", entity=prq)
    return prq


def cancel_by_requester(user, prq_id, request=None):
    with business_transaction():
        prq = PatientRequest.objects.select_for_update().filter(pk=prq_id, requester=user).first()
        if prq is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(prq.status in (P.SUBMITTED, P.VERIFYING, P.VERIFIED), "ERR-PRQ-FINAL-STATE"
                if prq.is_final else "ERR-STATE-INVALID")
        old = prq.status
        prq.status = P.CANCELLED
        prq.save(update_fields=["status", "updated_at"])
        audit(user, prq, "status_change", old={"status": old}, new={"status": "cancelled"}, hospital=prq.hospital,
              request=request)
        notify_hospital_staff(prq.hospital, "patient_request_cancelled",
                              f"Người gửi đã hủy yêu cầu {prq.request_code}", entity=prq)
    return prq


def hospital_actions(prq):
    """Nút theo trạng thái (Ch.7 mục 7.7)."""
    return {
        P.SUBMITTED: ["start_verify", "verify", "reject"],
        P.VERIFYING: ["verify", "reject"],
        P.VERIFIED: ["start_processing", "issue", "support", "link_campaign", "cancel"],
        P.PROCESSING: ["issue", "support", "link_campaign", "fulfill", "cancel"],
    }.get(prq.status, [])


def hospital_action(staff, prq_id, action, data, request=None):
    """UC-PRQ-03/04 — chỉ bệnh viện điều trị (BR-47)."""
    now = timezone.now()
    with business_transaction():
        prq = PatientRequest.objects.select_for_update().filter(pk=prq_id).first()
        if prq is None or prq.hospital_id != staff.hospital_id:
            raise BusinessError("ERR-NOT-FOUND")
        if prq.is_final:
            raise BusinessError("ERR-PRQ-FINAL-STATE")
        require(action in hospital_actions(prq), "ERR-STATE-INVALID")
        old = snapshot(prq, ["status", "blood_group", "linked_campaign"])
        msg = None
        if action == "start_verify":
            prq.status = P.VERIFYING
        elif action == "verify":
            bg = data.get("blood_group") or prq.blood_group
            require(bg in BLOOD_GROUP_VALUES, "ERR-VALIDATION", "Xác minh bắt buộc có nhóm máu.")
            require(prq.requester_id != staff.user_id, "ERR-AUTH-FORBIDDEN", "Người xác minh phải khác người gửi.")
            prq.blood_group, prq.status, prq.verified_by, prq.verified_at = bg, P.VERIFIED, staff.user, now
            msg = "Yêu cầu đã được bệnh viện xác minh và đang được điều phối."
        elif action == "reject":
            reason = (data.get("reason") or "").strip()
            require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do từ chối.")
            prq.status, prq.reject_reason = P.REJECTED, reason[:500]
            msg = f"Yêu cầu không được tiếp nhận. Lý do: {reason}"
        elif action == "start_processing":
            prq.status = P.PROCESSING
        elif action == "link_campaign":
            camp = Campaign.objects.filter(pk=data.get("campaign_id"), hospital=staff.hospital).first()
            require(camp is not None, "ERR-VALIDATION", "Chọn đợt hiến của bệnh viện.")
            prq.linked_campaign = camp
            if prq.status == P.VERIFIED:
                prq.status = P.PROCESSING
        elif action == "fulfill":
            note = (data.get("resolution_note") or "").strip()
            require(note, "ERR-VALIDATION", "Vui lòng nhập kết quả xử lý.")
            prq.status, prq.resolution_note = P.FULFILLED, note
            msg = "Yêu cầu đã được bệnh viện xử lý hoàn tất."
        elif action == "cancel":
            reason = (data.get("reason") or "").strip()
            require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do hủy.")
            prq.status = P.CANCELLED
            prq.resolution_note = f"Hủy: {reason}"
            msg = f"Bệnh viện đã hủy yêu cầu. Lý do: {reason}"
        else:
            raise BusinessError("ERR-STATE-INVALID")
        prq.save()
        audit(staff.user, prq, "status_change" if action != "link_campaign" else "link_campaign", old=old,
              new=snapshot(prq, ["status", "blood_group", "linked_campaign"]), hospital=staff.hospital, request=request)
        if msg or prq.status != old["status"]:
            notify(prq.requester, "patient_request_status", f"Yêu cầu {prq.request_code}: {prq.get_status_display()}",
                   msg, entity=prq)
    return prq


def log_sensitive_view(staff, prq, request=None):
    """Xem chi tiết có tên bệnh nhân/SĐT → ghi log view_sensitive (Ch.7 mục 7.11)."""
    audit(staff.user, prq, "view_sensitive", new={"fields": ["patient_name", "contact_phone"]},
          hospital=staff.hospital, request=request)
