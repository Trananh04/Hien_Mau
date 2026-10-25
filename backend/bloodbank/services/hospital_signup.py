"""BV_014: bệnh viện tự đăng ký → Quản trị hệ thống duyệt → Quản lý bệnh viện tự cấp tài khoản nhân viên.

Đăng ký tạo cùng lúc: bệnh viện (trạng thái Chờ duyệt) + tài khoản Quản lý bệnh viện (role = hospital,
phân công staff_role = manager). Bệnh viện chưa được duyệt thì Quản lý chưa đăng nhập được khu làm việc.
"""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import User, normalize_phone
from bloodbank.models import Hospital, Staff

from .admin import HOSPITAL_FIELDS
from .common import BusinessError, alert, as_id, audit, business_transaction, require, snapshot


def register_hospital(data, request=None):
    """data: các trường bệnh viện (HOSPITAL_FIELDS) + manager_name, manager_email, manager_phone, password."""
    email = (data.get("manager_email") or "").strip().lower()
    full_name = (data.get("manager_name") or "").strip()
    phone = normalize_phone(data.get("manager_phone"))
    code = (data.get("code") or "").strip().upper()
    require(code and data.get("name") and data.get("address") and data.get("province"), "ERR-VALIDATION",
            "Nhập đủ mã cơ sở, tên, địa chỉ và tỉnh/thành của bệnh viện.")
    require(full_name and "@" in email, "ERR-VALIDATION", "Nhập họ tên và email của người quản lý.")
    try:
        validate_password(data.get("password") or "", User(email=email, full_name=full_name))
    except ValidationError as exc:
        raise BusinessError("ERR-AUTH-WEAK-PASSWORD", " ".join(exc.messages))
    with business_transaction():
        if Hospital.objects.filter(code=code).exists():
            raise BusinessError("ERR-CAT-CODE-TAKEN", "Mã cơ sở y tế đã được đăng ký.")
        if User.objects.filter(email=email).exists():
            raise BusinessError("ERR-AUTH-EMAIL-TAKEN", "Email người quản lý đã có tài khoản. Dùng email khác.")
        if phone and User.objects.filter(phone=phone).exists():
            raise BusinessError("ERR-AUTH-PHONE-TAKEN")
        values = {k: (data.get(k) if data.get(k) not in ("",) else None) for k in HOSPITAL_FIELDS}
        values["code"] = code
        hospital = Hospital.objects.create(**values, status=Hospital.Status.PENDING)
        user = User.objects.create_user(email=email, password=data["password"], full_name=full_name, phone=phone,
                                        role="hospital")
        staff = Staff.objects.create(hospital=hospital, user=user, staff_role=Staff.Role.MANAGER)
        audit(user, hospital, "create", new={**snapshot(hospital, ["code", "name", "province", "status"]),
                                             "manager": email}, hospital=hospital, request=request)
        admins = User.objects.filter(role="admin", status="active")
        alert(admins, "hospital_signup", f"Bệnh viện mới đăng ký: {hospital.name}",
              f"Mã cơ sở {hospital.code} · {hospital.province}. Vui lòng xem xét và duyệt.", entity=hospital)
    return hospital, staff


def _pending(hospital_id):
    h = Hospital.objects.select_for_update().filter(pk=as_id(hospital_id)).first()
    if h is None:
        raise BusinessError("ERR-NOT-FOUND")
    require(h.status == Hospital.Status.PENDING, "ERR-STATE-INVALID", "Bệnh viện này không ở trạng thái chờ duyệt.")
    return h


def _managers(h):
    return [s.user for s in h.staffs.filter(staff_role=Staff.Role.MANAGER).select_related("user")]


def approve(actor, hospital_id, request=None):
    with business_transaction():
        h = _pending(hospital_id)
        h.status, h.reject_reason = Hospital.Status.ACTIVE, None
        h.save(update_fields=["status", "reject_reason", "updated_at"])
        audit(actor, h, "status_change", old={"status": "pending"}, new={"status": "active"}, hospital=h,
              request=request)
        alert(_managers(h), "hospital_approved", f"{h.name} đã được duyệt",
              "Bạn có thể đăng nhập cổng Bệnh viện và cấp tài khoản cho nhân viên.", entity=h)
    return h


def reject(actor, hospital_id, reason, request=None):
    reason = (reason or "").strip()
    require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do từ chối.")
    with business_transaction():
        h = _pending(hospital_id)
        h.status, h.reject_reason = Hospital.Status.REJECTED, reason[:500]
        h.save(update_fields=["status", "reject_reason", "updated_at"])
        audit(actor, h, "status_change", old={"status": "pending"}, new={"status": "rejected", "reason": reason},
              hospital=h, request=request)
        alert(_managers(h), "hospital_rejected", f"Đăng ký {h.name} không được duyệt", f"Lý do: {reason}", entity=h)
    return h


def require_manager(staff):
    require(staff is not None and staff.is_manager, "ERR-AUTH-FORBIDDEN",
            "Chỉ Quản lý bệnh viện được cấp hoặc thu hồi tài khoản nhân viên.")


def check_staff_target(manager, staff_id):
    """Quản lý không tự thu hồi mình và không thao tác trên tài khoản Quản lý khác."""
    target = Staff.objects.filter(pk=as_id(staff_id), hospital=manager.hospital).first()
    if target is None:
        raise BusinessError("ERR-NOT-FOUND")
    require(target.pk != manager.pk, "ERR-AUTH-FORBIDDEN", "Không thể tự thu hồi phân công của chính mình.")
    require(not target.is_manager, "ERR-AUTH-FORBIDDEN", "Không thao tác trên tài khoản Quản lý bệnh viện khác.")
    return target
