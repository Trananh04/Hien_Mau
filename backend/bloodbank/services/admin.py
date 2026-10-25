"""UC-AUT-04/05, UC-HOS-01, UC-CAT-01/02, cấu hình hệ thống."""
from django.db.models import Q

from accounts.models import User
from accounts.services import revoke_tokens
from bloodbank.models import (
    Campaign, Hospital, HospitalRequest, Product, ProductSpec, RequestOffer, Staff, SystemSetting,
)

from .common import BusinessError, as_id, audit, business_transaction, notify, require, snapshot

# ---------------------------------------------------------------- Người dùng (Admin)
def set_user_status(actor, user_id, status, request=None):
    require(status in ("active", "locked", "deleted"), "ERR-VALIDATION")
    with business_transaction():
        user = User.objects.select_for_update().filter(pk=as_id(user_id)).first()
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
            require(full_name, "ERR-VALIDATION", "Email này chưa có tài khoản. Nhập họ tên để tạo tài khoản nhân viên mới.")
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
        # BR-03, BR-04: mỗi nhân viên chỉ có một hồ sơ phân công, tại một bệnh viện
        existing = Staff.objects.select_for_update().filter(user=user).first()
        if existing and existing.is_active:
            raise BusinessError("ERR-STAFF-DUPLICATE" if existing.hospital_id == hospital.pk else "ERR-STAFF-OTHER-HOSPITAL")
        if existing:
            # Phân công cũ đã thu hồi → kích hoạt lại, chuyển sang bệnh viện mới nếu khác
            existing.hospital = hospital
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
        staff = Staff.objects.select_for_update().filter(pk=as_id(staff_id), hospital=hospital).first()
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
        require(h.status in ("active", "inactive"), "ERR-STATE-INVALID",
                "Bệnh viện đang chờ duyệt hoặc đã bị từ chối: dùng Duyệt / Từ chối.")
        if status == "inactive":
            busy_offers = RequestOffer.objects.filter(
                Q(supplier_hospital=h) | Q(request__requesting_hospital=h), status__in=["accepted", "in_transit"]
            ).exists()
            if busy_offers or Campaign.objects.filter(hospital=h, status="open").exists():
                raise BusinessError("ERR-STATE-INVALID",
                                    "Còn đề nghị đang giữ chỗ/vận chuyển hoặc đợt hiến đang mở, chưa thể ngừng hoạt động.")
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


# ---------------------------------------------------------------- Cấu hình
def save_setting(actor, key, raw, request=None):
    import json

    require(key in SystemSetting.DEFAULTS, "ERR-NOT-FOUND")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise BusinessError("ERR-VALIDATION", "Giá trị phải là JSON hợp lệ (ví dụ: 5, \"abc\", true).")
    default = SystemSetting.DEFAULTS[key][0]
    if isinstance(default, bool):
        require(isinstance(value, bool), "ERR-VALIDATION", "Giá trị phải là true hoặc false.")
    elif isinstance(default, int):
        require(isinstance(value, int) and not isinstance(value, bool) and value > 0, "ERR-VALIDATION",
                "Giá trị phải là số nguyên dương.")
    with business_transaction():
        row, _ = SystemSetting.objects.get_or_create(
            setting_key=key, defaults={"setting_value": value, "description": SystemSetting.DEFAULTS[key][1]})
        old = row.setting_value
        row.setting_value, row.updated_by = value, actor
        row.save()
        audit(actor, row, "update", old={"value": old}, new={"value": value}, entity_type="system_settings",
              entity_id=0, request=request)
    return row


# ---------------------------------------------------------------- Giám sát (chỉ đọc)
def system_alerts(now=None):
    """Việc cần Quản trị đôn đốc trên toàn hệ thống. Không làm thay bệnh viện, không lộ tên bệnh nhân."""
    from datetime import timedelta

    from django.utils import timezone

    from bloodbank.models import PatientRequest
    from bloodbank.services import inventory as inv

    now = now or timezone.now()
    late_minutes = SystemSetting.get("prq_escalate_admin_minutes")
    ttl_hours = SystemSetting.get("offer_response_ttl_hours")
    late_prq = list(PatientRequest.objects.filter(
        status__in=PatientRequest.WAITING_STATUSES, created_at__lte=now - timedelta(minutes=late_minutes),
        hospital__status="active").select_related("hospital", "blood_product").order_by("created_at"))
    overdue_support = list(HospitalRequest.objects.filter(
        status__in=HospitalRequest.OPEN_STATUSES, closed_at__isnull=True, needed_by__lt=now)
        .select_related("requesting_hospital", "product_spec__product").order_by("needed_by"))
    stale_offers = list(RequestOffer.objects.filter(
        status=RequestOffer.Status.PENDING, created_at__lte=now - timedelta(hours=ttl_hours / 2))
        .select_related("supplier_hospital", "request__requesting_hospital").order_by("created_at"))
    shortages = []
    for h in Hospital.objects.filter(status="active").order_by("name"):
        rows = [r for r in inv.shortages(h) if r["shortage"] > 0]
        if rows:
            shortages.append({"hospital": h, "rows": rows, "total": sum(r["shortage"] for r in rows)})
    shortages.sort(key=lambda x: -x["total"])
    return {"late_prq": late_prq, "late_minutes": late_minutes, "overdue_support": overdue_support,
            "stale_offers": stale_offers, "ttl_hours": ttl_hours, "stale_after_hours": ttl_hours // 2 if ttl_hours % 2 == 0 else ttl_hours / 2,
            "shortages": shortages,
            "urgent_count": len(late_prq) + len(overdue_support)}


def urgent_alert_count(now=None):
    """Số việc khẩn để hiện trên menu Quản trị (2 truy vấn đếm, không tính thiếu hụt theo từng bệnh viện)."""
    from datetime import timedelta

    from django.utils import timezone

    from bloodbank.models import PatientRequest

    now = now or timezone.now()
    late = now - timedelta(minutes=SystemSetting.get("prq_escalate_admin_minutes"))
    return (PatientRequest.objects.filter(status__in=PatientRequest.WAITING_STATUSES, created_at__lte=late,
                                          hospital__status="active").count()
            + HospitalRequest.objects.filter(status__in=HospitalRequest.OPEN_STATUSES, closed_at__isnull=True,
                                             needed_by__lt=now).count())


ASSISTANT_MODES = {"llm": "AI trả lời", "rules": "Chế độ từ khóa", "guard": "Chặn an toàn", "limit": "Quá giới hạn"}
ASSISTANT_INTENTS = {
    "faq": "Hỏi đáp kiến thức", "chat": "Hỏi đáp kiến thức", "campaigns": "Tìm đợt hiến",
    "suggest_campaigns": "Tìm đợt hiến", "eligibility": "Ngày được hiến lại", "my_eligibility": "Ngày được hiến lại",
    "history": "Lịch sử hiến", "my_donation_history": "Lịch sử hiến", "precheck": "Kiểm tra điều kiện sơ bộ",
    "preliminary_check": "Kiểm tra điều kiện sơ bộ", "my_registrations": "Đơn đăng ký của tôi",
    "my_patient_requests": "Yêu cầu cần máu của tôi", "emergency": "Tình huống khẩn cấp",
    "privacy": "Hỏi dữ liệu người khác", "trade": "Mua bán máu", "injection": "Cố vượt quyền",
    "clinical": "Câu hỏi y khoa", "unknown": "Không hiểu câu hỏi",
}


def assistant_stats(days=7, now=None):
    """Theo dõi trợ lý từ nhật ký `assistant_query` (không có nội dung câu hỏi) + bộ đếm lượt gọi AI hôm nay."""
    from datetime import timedelta

    from django.conf import settings
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    from bloodbank.assistant import llm
    from bloodbank.assistant.service import llm_calls_today
    from bloodbank.models import AuditLog

    now = now or timezone.now()
    today = timezone.localdate(now)
    start_day = today - timedelta(days=days - 1)
    tz = timezone.get_current_timezone()
    qs = AuditLog.objects.filter(action="assistant_query",
                                 created_at__date__gte=start_day)
    per_day = {start_day + timedelta(days=i): {"total": 0, **{m: 0 for m in ASSISTANT_MODES}} for i in range(days)}
    for row in (qs.annotate(d=TruncDate("created_at", tzinfo=tz)).values("d", "new_values__mode")
                .annotate(n=Count("id"))):
        day = per_day.get(row["d"])
        if day is not None:
            day["total"] += row["n"]
            mode = row["new_values__mode"]
            if mode in ASSISTANT_MODES:
                day[mode] += row["n"]
    totals = {m: sum(d[m] for d in per_day.values()) for m in ASSISTANT_MODES}
    total = sum(d["total"] for d in per_day.values())
    intents = {}
    for row in qs.values("new_values__intent").annotate(n=Count("id")).order_by("-n"):
        for part in str(row["new_values__intent"] or "unknown").split(","):
            label = ASSISTANT_INTENTS.get(part.split(":")[0].strip(), "Khác")
            intents[label] = intents.get(label, 0) + row["n"]
    peak = max([d["total"] for d in per_day.values()] or [0])
    return {
        "days": [{"date": d, **v} for d, v in sorted(per_day.items())], "peak": peak, "total": total,
        "modes": [{"key": k, "label": label, "count": totals[k]} for k, label in ASSISTANT_MODES.items()],
        "intents": sorted(intents.items(), key=lambda kv: -kv[1])[:8],
        "ai_calls_today": llm_calls_today(),
        "daily_limit": settings.CHATBOT_DAILY_LIMIT, "max_concurrent": settings.CHATBOT_MAX_CONCURRENT,
        "configured": llm.configured(), "enabled": llm.enabled(),
        "switch_on": bool(SystemSetting.get("chatbot_ai_enabled")), "model": settings.CHATBOT_MODEL,
    }

