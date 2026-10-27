"""Tác vụ định kỳ (chạy bởi `manage.py run_jobs`, container `scheduler`, mặc định 5 phút/lần).

Không phụ thuộc việc có người mở trang:
  1. Yêu cầu liên viện quá hạn → hết hạn, giải phóng giữ chỗ trong kho bên cấp.
  2. Đề nghị liên viện không được phản hồi quá `offer_response_ttl_hours` → tự hủy, báo bên yêu cầu mời BV khác.
  3. Yêu cầu cần máu chưa ai nhận xác minh: sau `prq_escalate_staff_minutes` nhắc lại toàn bộ nhân viên (kèm email),
     sau `prq_escalate_admin_minutes` báo lên Quản trị hệ thống. Mỗi mức chỉ nhắc một lần.
  4. Điền kết quả lời kêu gọi người hiến; nhắc người hiến đã đủ thời gian nghỉ; làm mới dự báo nhu cầu (mỗi ngày).
  5. Dự báo nhu cầu: lưu dự báo mỗi ngày để đo độ chính xác thật; huấn luyện lại mô hình khi đến hạn / được yêu cầu.
"""
import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from bloodbank.models import HospitalRequest, Notification, PatientRequest, RequestOffer, SystemSetting

from . import badges
from .common import alert, audit, business_transaction, hospital_staff_users, notify_hospital_staff
from .transfers import expire_overdue, recompute_status

O, H = RequestOffer.Status, HospitalRequest.Status
ESCALATE_STAFF, ESCALATE_ADMIN = "prq_escalated_staff", "prq_escalated_admin"


def cancel_stale_offers(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(hours=SystemSetting.get("offer_response_ttl_hours"))
    urgent_cutoff = now - timedelta(minutes=SystemSetting.get("offer_response_ttl_urgent_minutes"))
    open_reqs = [H.OPEN, H.IN_PROGRESS, H.PARTIALLY_FULFILLED]
    ids = list(RequestOffer.objects.filter(status=O.PENDING, request__status__in=open_reqs)
               .filter(Q(created_at__lt=cutoff) | Q(request__priority="urgent", created_at__lt=urgent_cutoff))
               .values_list("pk", flat=True))
    done = 0
    for offer_id in ids:
        with business_transaction():
            offer = RequestOffer.objects.select_for_update().select_related("request", "supplier_hospital").get(pk=offer_id)
            if offer.status != O.PENDING:
                continue
            offer.status = O.CANCELLED
            offer.note = ((offer.note or "") + "\nTự hủy: quá hạn phản hồi.").strip()
            offer.save(update_fields=["status", "note", "updated_at"])
            req = HospitalRequest.objects.select_for_update().get(pk=offer.request_id)
            recompute_status(req, now)
            audit(None, offer, "auto_cancel", new={"status": "cancelled", "reason": "response_timeout"},
                  hospital=req.requesting_hospital)
            notify_hospital_staff(req.requesting_hospital, "offer_timeout",
                                  f"{offer.supplier_hospital.name} chưa phản hồi yêu cầu {req.request_code}",
                                  "Đề nghị đã tự hủy do quá hạn phản hồi. Hãy mời bệnh viện khác.", entity=req)
            notify_hospital_staff(offer.supplier_hospital, "offer_cancelled",
                                  f"Đề nghị cho yêu cầu {req.request_code} đã tự hủy do quá hạn phản hồi", entity=offer)
            done += 1
    return done


def _already(type_, prq):
    return Notification.objects.filter(type=type_, entity_type="patient_requests", entity_id=prq.pk).exists()


def escalate_patient_requests(now=None):
    now = now or timezone.now()
    staff_after = timedelta(minutes=SystemSetting.get("prq_escalate_staff_minutes"))
    admin_after = timedelta(minutes=SystemSetting.get("prq_escalate_admin_minutes"))
    counts = {"staff": 0, "admin": 0}
    waiting = PatientRequest.objects.filter(status=PatientRequest.Status.SUBMITTED,
                                            created_at__lt=now - staff_after).select_related("hospital")
    admins = None
    for prq in waiting:
        age = int((now - prq.created_at).total_seconds() // 60)
        what = f"Yêu cầu {prq.request_code} ({prq.quantity_units} đơn vị{' nhóm ' + prq.blood_group if prq.blood_group else ''})"
        with business_transaction():
            if not _already(ESCALATE_STAFF, prq):
                alert(hospital_staff_users(prq.hospital), ESCALATE_STAFF, f"[Nhắc lại] {what} chưa được xác minh",
                      f"Đã chờ {age} phút tại {prq.hospital.name}. Vui lòng nhận xác minh ngay.", entity=prq)
                audit(None, prq, "escalate", new={"level": "staff", "minutes": age}, hospital=prq.hospital)
                counts["staff"] += 1
            if now - prq.created_at >= admin_after and not _already(ESCALATE_ADMIN, prq):
                if admins is None:
                    admins = list(User.objects.filter(role="admin", status="active"))
                alert(admins, ESCALATE_ADMIN, f"{what} chưa được xác minh sau {age} phút",
                      f"Bệnh viện: {prq.hospital.name}. Hãy liên hệ bệnh viện để xử lý.", entity=prq)
                audit(None, prq, "escalate", new={"level": "admin", "minutes": age}, hospital=prq.hospital)
                counts["admin"] += 1
    return counts


def run_all(now=None):
    expired_before = HospitalRequest.objects.filter(status=H.EXPIRED).count()
    expire_overdue(None)
    return {
        "expired_requests": HospitalRequest.objects.filter(status=H.EXPIRED).count() - expired_before,
        "cancelled_offers": cancel_stale_offers(now),
        "escalations": escalate_patient_requests(now),
        "eligible_reminders": badges.remind_eligible_again(now),
        "chat_purged": _purge_chat(now),
        **_forecast(now),
    }


def _forecast(now=None):
    # Dự báo hỏng (kể cả thiếu thư viện numpy/xgboost) không được chặn các tác vụ nghiệp vụ
    try:
        from bloodbank.services.forecast_ml import monitor

        return {"forecast_snapshots": monitor.record_snapshots(now), "forecast_retrain": monitor.nightly_check(now)}
    except Exception:
        logging.getLogger(__name__).exception("Tác vụ dự báo thất bại")
        return {"forecast_snapshots": "error"}


def _purge_chat(now=None):
    from bloodbank.assistant.service import purge_old_conversations

    return purge_old_conversations(now)
