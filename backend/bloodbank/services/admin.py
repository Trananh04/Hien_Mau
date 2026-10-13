"""UC-AUT-04/05, UC-HOS-01, UC-CAT-01/02, cấu hình hệ thống."""
from django.db.models import Q

from accounts.models import User
from accounts.services import revoke_tokens
from bloodbank.models import (
    Campaign, Demand, Hospital, HospitalRequest, Product, ProductSpec, RequestOffer, Staff, Stock, SystemSetting,
)

from .common import BusinessError, audit, business_transaction, notify, require, snapshot

# ---------------------------------------------------------------- Người dùng (Admin)
def set_user_status(actor, user_id, status, request=None):
    require(status in ("active", "locked", "deleted"), "ERR-VALIDATION")
    with business_transaction():
        user = User.objects.select_for_update().filter(pk=user_id).first()
        if user is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(user.pk != actor.pk, "ERR-AUTH-FORBIDDEN", "Không thể tự khóa/xóa tài khoản của chính mình.")
        require(user.status != "deleted", "ERR-STATE-INVALID", "Tài khoản đã xóa là trạng thái cuối.")
        if status != "active" and user.role == "admin":
            others = User.objects.filter(role="admin", status="active").exclude(pk=user.pk).exists()
            require(others, "ERR-STAFF-LAST-ADMIN", "Hệ thống phải còn ít nhất một quản trị viên đang hoạt động.")
        old = user.status
        user.status = status
        user.save(update_fields=["status", "updated_at"])
        if status != "active":
            revoke_tokens(user)
        audit(actor, user, "status_change", old={"status": old}, new={"status": status}, request=request)
    return user


def set_user_role(actor, user_id, role, request=None):
    """Đổi giữa Người dùng ↔ Quản trị hệ thống. Tài khoản Nhân viên bệnh viện được quản lý tại màn hình Bệnh viện."""
    require(role in ("member", "admin"), "ERR-VALIDATION")
    with business_transaction():
        user = User.objects.select_for_update().get(pk=user_id)
        require(user.role != "hospital", "ERR-STAFF-ROLE",
                "Tài khoản nhân viên bệnh viện được quản lý tại màn hình Bệnh viện, không đổi vai trò ở đây.")
        require(user.pk != actor.pk, "ERR-AUTH-FORBIDDEN", "Không thể tự đổi vai trò của chính mình.")
        if role == "member" and user.role == "admin":
            require(User.objects.filter(role="admin", status="active").exclude(pk=user.pk).exists(),
                    "ERR-STAFF-LAST-ADMIN")
        old = user.role
        user.role = role
        user.save(update_fields=["role", "updated_at"])
        if old != role:
            revoke_tokens(user)
        audit(actor, user, "role_change", old={"role": old}, new={"role": role}, request=request)
    return user


# ---------------------------------------------------------------- Tài khoản nhân viên bệnh viện (Admin)
def assign_staff(actor, hospital, data, request=None):
    """Gắn tài khoản Nhân viên bệnh viện vào bệnh viện. Email chưa có → tạo tài khoản mới (role = hospital).

    Tài khoản Người dùng / Quản trị không được dùng làm tài khoản bệnh viện — mỗi vai trò một tài khoản riêng.
    """
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    from accounts.models import normalize_phone

    email = (data.get("email") or "").strip().lower()
    require(email and "@" in email, "ERR-VALIDATION", "Nhập email hợp lệ.")
    with business_transaction():
        user = User.objects.select_for_update().filter(email=email).first()
        if user is None:
            full_name = (data.get("full_name") or "").strip()
            password = data.get("password") or ""
            require(full_name, "ERR-VALIDATION", "Email chưa có tài khoản — nhập họ tên để tạo tài khoản nhân viên mới.")
            try:
                validate_password(password, User(email=email, full_name=full_name))
            except ValidationError as exc:
                raise BusinessError("ERR-AUTH-WEAK-PASSWORD", " ".join(exc.messages))
            phone = normalize_phone(data.get("phone"))
            if phone and User.objects.filter(phone=phone).exists():
                raise BusinessError("ERR-AUTH-PHONE-TAKEN")
            user = User.objects.create_user(email=email, password=password, full_name=full_name, phone=phone,
                                            role="hospital")
            audit(actor, user, "create", new={"email": email, "role": "hospital"}, hospital=hospital, request=request)
        else:
            require(user.role == "hospital", "ERR-STAFF-ROLE")
            require(user.status == "active", "ERR-AUTH-LOCKED", "Tài khoản nhân viên này đang bị khóa hoặc đã xóa.")
        existing = Staff.objects.select_for_update().filter(hospital=hospital, user=user).first()
        if existing and existing.is_active:
            raise BusinessError("ERR-STAFF-DUPLICATE")
        if existing:
            existing.is_active = True
            existing.save()
            staff, action = existing, "reactivate"
        else:
            staff = Staff.objects.create(hospital=hospital, user=user, staff_role=Staff.Role.STAFF)
            action = "create"
        audit(actor, staff, action, new=snapshot(staff), hospital=hospital, request=request)
        notify(user, "staff_assigned", f"Bạn được phân công tại {hospital.name}",
               "Vai trò: Nhân viên bệnh viện.", entity=staff)
    return staff


def update_staff(actor, hospital, staff_id, is_active, request=None):
    with business_transaction():
        staff = Staff.objects.select_for_update().filter(pk=staff_id, hospital=hospital).first()
        if staff is None:
            raise BusinessError("ERR-NOT-FOUND")
        old = snapshot(staff, ["is_active"])
        staff.is_active = is_active
        staff.save()
        audit(actor, staff, "update", old=old, new=snapshot(staff, ["is_active"]), hospital=hospital, request=request)
        if is_active is False:
            notify(staff.user, "staff_revoked", f"Phân công tại {hospital.name} đã được thu hồi", entity=staff)
    return staff


# ---------------------------------------------------------------- Bệnh viện
HOSPITAL_FIELDS = ["code", "name", "address", "province", "district", "ward", "latitude", "longitude", "phone", "email"]
STAFF_EDITABLE = ["address", "district", "ward", "latitude", "longitude", "phone", "email"]


def save_hospital(actor, data, hospital=None, fields=HOSPITAL_FIELDS, request=None):
    data = {k: (data.get(k) if data.get(k) not in ("",) else None) for k in fields}
    if "code" in data and data["code"]:
        data["code"] = data["code"].strip().upper()
        clash = Hospital.objects.filter(code=data["code"]).exclude(pk=getattr(hospital, "pk", None)).exists()
        if clash:
            raise BusinessError("ERR-CAT-CODE-TAKEN", "Mã cơ sở y tế đã tồn tại.")
    with business_transaction():
        if hospital is None:
            hospital = Hospital.objects.create(**data)
            audit(actor, hospital, "create", new=snapshot(hospital), hospital=hospital, request=request)
        else:
            hospital = Hospital.objects.select_for_update().get(pk=hospital.pk)
            old = snapshot(hospital, fields)
            for k, v in data.items():
                setattr(hospital, k, v)
            hospital.save()
            audit(actor, hospital, "update", old=old, new=snapshot(hospital, fields), hospital=hospital, request=request)
    return hospital


def set_hospital_status(actor, hospital_id, status, request=None):
    """Ngừng hoạt động chỉ khi không còn offer accepted/in_transit và đợt open (Ch.4 mục 4.2)."""
    require(status in ("active", "inactive"), "ERR-VALIDATION")
    with business_transaction():
        h = Hospital.objects.select_for_update().get(pk=hospital_id)
        if status == "inactive":
            busy_offers = RequestOffer.objects.filter(
                Q(supplier_hospital=h) | Q(request__requesting_hospital=h), status__in=["accepted", "in_transit"]
            ).exists()
            if busy_offers or Campaign.objects.filter(hospital=h, status="open").exists():
                raise BusinessError("ERR-STATE-INVALID",
                                    "Còn đề nghị đang giữ chỗ/vận chuyển hoặc đợt hiến đang mở — chưa thể ngừng hoạt động.")
        old = h.status
        h.status = status
        h.save(update_fields=["status", "updated_at"])
        audit(actor, h, "status_change", old={"status": old}, new={"status": status}, hospital=h, request=request)
    return h


# ---------------------------------------------------------------- Danh mục chế phẩm (BR-35)
def save_product(actor, data, product=None, request=None):
    code = (data.get("code") or "").strip().upper()
    require(code, "ERR-VALIDATION")
    if Product.objects.filter(code=code).exclude(pk=getattr(product, "pk", None)).exists():
        raise BusinessError("ERR-CAT-CODE-TAKEN")
    with business_transaction():
        if product is None:
            product = Product.objects.create(code=code, name=data["name"], kind=data["kind"],
                                             description=data.get("description") or None)
            audit(actor, product, "create", new=snapshot(product), request=request)
        else:
            old = snapshot(product)
            product.code, product.name, product.kind = code, data["name"], data["kind"]
            product.description = data.get("description") or None
            product.save()
            audit(actor, product, "update", old=old, new=snapshot(product), request=request)
    return product


def save_spec(actor, product, data, spec=None, request=None):
    code = (data.get("code") or "").strip().upper()
    require(code, "ERR-VALIDATION")
    if ProductSpec.objects.filter(product=product, code=code).exclude(pk=getattr(spec, "pk", None)).exists():
        raise BusinessError("ERR-CAT-CODE-TAKEN")
    make_default = bool(data.get("is_default")) or not product.specs.filter(is_default=True).exclude(
        pk=getattr(spec, "pk", None)).exists()
    with business_transaction():
        if make_default:
            # Đổi mặc định: bỏ cờ cũ trước rồi đặt cờ mới trong cùng giao dịch
            product.specs.filter(is_default=True).exclude(pk=getattr(spec, "pk", None)).update(is_default=False)
        if spec is None:
            spec = ProductSpec.objects.create(product=product, code=code, name=data["name"],
                                              unit_volume_ml=data.get("unit_volume_ml"), is_default=make_default)
            audit(actor, spec, "create", new=snapshot(spec), request=request)
        else:
            old = snapshot(spec)
            spec.code, spec.name, spec.unit_volume_ml = code, data["name"], data.get("unit_volume_ml")
            spec.is_default = make_default or spec.is_default
            spec.save()
            audit(actor, spec, "update", old=old, new=snapshot(spec), request=request)
    return spec


def toggle_catalog(actor, obj, active, request=None):
    """Ngừng dùng bằng is_active (không xóa khi đã tham chiếu). Mỗi chế phẩm ≥ 1 quy cách active."""
    with business_transaction():
        if isinstance(obj, ProductSpec) and not active:
            require(obj.product.specs.filter(is_active=True).exclude(pk=obj.pk).exists(), "ERR-CAT-IN-USE",
                    "Chế phẩm phải còn ít nhất một quy cách đang dùng.")
            require(not obj.is_default, "ERR-CAT-IN-USE", "Hãy đặt quy cách khác làm mặc định trước khi ngừng dùng.")
        obj.is_active = active
        obj.save(update_fields=["is_active", "updated_at"])
        audit(actor, obj, "status_change", new={"is_active": active}, request=request)
    return obj


def catalog_in_use(spec):
    return (Stock.objects.filter(product_spec=spec).exists() or Demand.objects.filter(product_spec=spec).exists()
            or HospitalRequest.objects.filter(product_spec=spec).exists())


# ---------------------------------------------------------------- Cấu hình
def save_setting(actor, key, raw, request=None):
    import json

    require(key in SystemSetting.DEFAULTS, "ERR-NOT-FOUND")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise BusinessError("ERR-VALIDATION", "Giá trị phải là JSON hợp lệ (ví dụ: 5, \"abc\", true).")
    default = SystemSetting.DEFAULTS[key][0]
    if isinstance(default, int):
        require(isinstance(value, int) and value > 0, "ERR-VALIDATION", "Giá trị phải là số nguyên dương.")
    with business_transaction():
        row, _ = SystemSetting.objects.get_or_create(
            setting_key=key, defaults={"setting_value": value, "description": SystemSetting.DEFAULTS[key][1]})
        old = row.setting_value
        row.setting_value, row.updated_by = value, actor
        row.save()
        audit(actor, row, "update", old={"value": old}, new={"value": value}, entity_type="system_settings",
              entity_id=0, request=request)
    return row
