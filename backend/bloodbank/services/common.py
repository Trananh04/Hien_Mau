"""Hạ tầng dùng chung cho mọi nghiệp vụ: lỗi ERR-*, audit log, thông báo, mã phiếu."""
import uuid
from contextlib import contextmanager
from decimal import Decimal

from django.db import IntegrityError, InternalError, models, transaction
from django.db.utils import DatabaseError
from django.forms.models import model_to_dict
from django.utils import timezone

from bloodbank.models import AuditLog, Notification

ERROR_MESSAGES = {
    "ERR-AUTH-UNAUTHENTICATED": "Bạn cần đăng nhập để tiếp tục.",
    "ERR-AUTH-FORBIDDEN": "Bạn không có quyền thực hiện thao tác này.",
    "ERR-NOT-FOUND": "Không tìm thấy dữ liệu.",
    "ERR-VALIDATION": "Dữ liệu chưa hợp lệ, vui lòng kiểm tra lại các trường được đánh dấu.",
    "ERR-CONFLICT": "Dữ liệu vừa được người khác thay đổi. Vui lòng tải lại trang rồi thử lại.",
    "ERR-STATE-INVALID": "Thao tác không hợp lệ với trạng thái hiện tại.",
    "ERR-INTERNAL": "Chưa xác định được kết quả. Bấm Thử lại — hệ thống sẽ không ghi trùng.",
    "ERR-AUTH-EMAIL-TAKEN": "Email này đã được đăng ký.",
    "ERR-AUTH-PHONE-TAKEN": "Số điện thoại này đã được đăng ký.",
    "ERR-AUTH-INVALID-CREDENTIALS": "Email hoặc mật khẩu không đúng.",
    "ERR-AUTH-LOCKED": "Tài khoản đang bị khóa. Vui lòng liên hệ quản trị viên hoặc thử lại sau.",
    "ERR-AUTH-WEAK-PASSWORD": "Mật khẩu chưa đủ mạnh.",
    "ERR-STAFF-DUPLICATE": "Tài khoản này đã được phân công tại bệnh viện.",
    "ERR-STAFF-LAST-ADMIN": "Hệ thống phải còn ít nhất một Quản trị hệ thống đang hoạt động.",
    "ERR-STAFF-ROLE": "Email này thuộc tài khoản Người dùng hoặc Quản trị. Tài khoản nhân viên bệnh viện phải là tài khoản riêng.",
    "ERR-AUTH-PORTAL": "Tài khoản này không đăng nhập được tại cổng này.",
    "ERR-CMP-TIME-RANGE": "Thời gian kết thúc phải sau thời gian bắt đầu.",
    "ERR-CMP-NOT-OPEN": "Đợt hiến không ở trạng thái nhận đăng ký.",
    "ERR-CMP-HAS-DONATIONS": "Không thể hủy đợt đã có lượt hiến được xác nhận.",
    "ERR-REG-DUPLICATE": "Bạn đã có đơn đăng ký cho đợt này.",
    "ERR-REG-CLOSED": "Đợt hiến đã ngừng nhận đăng ký.",
    "ERR-REG-TOO-LATE": "Đợt hiến đã kết thúc.",
    "ERR-DON-REG-STATE": "Đơn phải được check-in trước khi ghi nhận lượt hiến.",
    "ERR-DON-DUPLICATE": "Đơn này đã có lượt hiến được xác nhận.",
    "ERR-DON-VOLUME-REQUIRED": "Hiến toàn phần bắt buộc nhập thể tích (ml) dương.",
    "ERR-DON-COMPONENT-REQUIRED": "Hiến thành phần bắt buộc chọn loại thành phần, số lượng và đơn vị.",
    "ERR-DON-SELF-CONFIRM": "Nhân viên không được xác nhận lượt hiến của chính mình.",
    "ERR-DON-TIME-OUTSIDE": "Thời điểm hiến phải nằm trong thời gian đợt và không ở tương lai.",
    "ERR-DON-HOSPITAL-MISMATCH": "Đợt hiến không thuộc bệnh viện đang làm việc.",
    "ERR-DON-REASON-REQUIRED": "Vui lòng nhập lý do.",
    "ERR-DON-VOIDED-IMMUTABLE": "Lượt hiến đã hủy hiệu lực, không thể sửa.",
    "ERR-DON-DONOR-MISMATCH": "Người hiến không khớp với đơn đăng ký.",
    "ERR-DON-IMMUTABLE-FIELD": "Không được sửa người hiến, đơn, bệnh viện hoặc người xác nhận.",
    "ERR-CAT-CODE-TAKEN": "Mã này đã tồn tại.",
    "ERR-CAT-IN-USE": "Danh mục đang được sử dụng, chỉ có thể ngừng dùng.",
    "ERR-CAT-INACTIVE": "Danh mục đã ngừng dùng.",
    "ERR-INV-QTY-POSITIVE": "Số lượng phải là số nguyên dương.",
    "ERR-INV-INSUFFICIENT": "Không đủ tồn khả dụng.",
    "ERR-INV-REASON-REQUIRED": "Vui lòng chọn lý do (và ghi chú khi lý do là Khác).",
    "ERR-INV-IDEMPOTENCY-MISMATCH": "Mã thao tác đã được dùng cho một phiếu khác. Vui lòng tải lại biểu mẫu.",
    "ERR-HRQ-SELF-SUPPLY": "Bệnh viện không thể tự cấp cho yêu cầu của chính mình.",
    "ERR-HRQ-OVER-NEEDED": "Tổng số cam kết vượt quá số cần.",
    "ERR-HRQ-CLOSED": "Yêu cầu hỗ trợ đã đóng.",
    "ERR-HRQ-HAS-IN-TRANSIT": "Còn đề nghị đang vận chuyển, chưa thể hủy/đóng yêu cầu.",
    "ERR-HRQ-IMMUTABLE": "Không được đổi yêu cầu hoặc bệnh viện cấp.",
    "ERR-TRF-NOT-SHAREABLE": "Bệnh viện này hiện không chia sẻ chế phẩm phù hợp.",
    "ERR-TRF-QTY-MISMATCH": "Số lượng không hợp lệ.",
    "ERR-TRF-RECEIVED-EXCEEDS": "Số thực nhận không được vượt số đã xuất.",
    "ERR-TRF-FAILURE-REASON-REQUIRED": "Vui lòng nhập lý do giao nhận thất bại.",
    "ERR-PRQ-NOT-VERIFIED": "Yêu cầu chưa được xác minh nên chưa thể điều phối.",
    "ERR-PRQ-WRONG-HOSPITAL": "Yêu cầu không thuộc bệnh viện đang làm việc.",
    "ERR-PRQ-FINAL-STATE": "Yêu cầu đã ở trạng thái cuối.",
    "ERR-APPEND-ONLY": "Dữ liệu chỉ cho phép thêm mới.",
}

# UNIQUE/CHECK dự kiến → mã nghiệp vụ (Ch.3 "Quy tắc ghi dữ liệu dùng chung")
CONSTRAINT_CODES = {
    "uq_donations_active_registration": "ERR-DON-DUPLICATE",
    "chk_record_not_self_confirm": "ERR-DON-SELF-CONFIRM",
    "chk_record_whole_blood_volume": "ERR-DON-VOLUME-REQUIRED",
    "chk_record_volume_positive": "ERR-DON-VOLUME-REQUIRED",
    "chk_record_component_fields": "ERR-DON-COMPONENT-REQUIRED",
    "uq_registrations_campaign_donor": "ERR-REG-DUPLICATE",
    "uq_staffs_hospital_user": "ERR-STAFF-DUPLICATE",
    "uq_offers_request_supplier": "ERR-STATE-INVALID",
    "uq_txn_offer_type": "ERR-STATE-INVALID",
    "uq_txn_idempotency": "ERR-INV-IDEMPOTENCY-MISMATCH",
    "chk_stock_on_hand": "ERR-INV-INSUFFICIENT",
    "chk_stock_reserved": "ERR-INV-INSUFFICIENT",
    "chk_txn_after_non_negative": "ERR-INV-INSUFFICIENT",
    "chk_campaign_time": "ERR-CMP-TIME-RANGE",
    "users_email_key": "ERR-AUTH-EMAIL-TAKEN",
    "users_phone_key": "ERR-AUTH-PHONE-TAKEN",
    "products_code_key": "ERR-CAT-CODE-TAKEN",
    "uq_specs_product_code": "ERR-CAT-CODE-TAKEN",
    "hospitals_code_key": "ERR-CAT-CODE-TAKEN",
}


class BusinessError(Exception):
    def __init__(self, code, message=None, field_errors=None):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, code)
        self.field_errors = field_errors or {}
        super().__init__(f"{code}: {self.message}")

    def __str__(self):
        return self.message


def translate_db_error(exc):
    """Ánh xạ lỗi CSDL dự kiến sang BusinessError; lỗi khác giữ nguyên (EX-COM-08)."""
    text = str(exc)
    for name, code in CONSTRAINT_CODES.items():
        if name in text:
            return BusinessError(code)
    if text.startswith("ERR-") or "ERR-" in text:
        code = text[text.index("ERR-"):].split(":")[0].strip()
        return BusinessError(code)
    return None


@contextmanager
def business_transaction():
    """Một transaction cho nghiệp vụ + audit; lỗi ràng buộc dự kiến → BusinessError."""
    try:
        with transaction.atomic():
            yield
    except (IntegrityError, InternalError, DatabaseError) as exc:
        mapped = translate_db_error(exc)
        if mapped:
            raise mapped from exc
        raise


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


SENSITIVE_FIELDS = {"password", "password_hash"}


def snapshot(instance, fields=None):
    if instance is None:
        return None
    data = model_to_dict(instance, fields=fields)
    for f in instance._meta.concrete_fields:
        if isinstance(f, (models.DateTimeField, models.DateField)) and (fields is None or f.name in fields):
            data[f.name] = getattr(instance, f.name)
    return {k: _jsonable(v) for k, v in data.items() if k not in SENSITIVE_FIELDS}


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return ip[:45] if ip else None


def audit(actor, entity, action, old=None, new=None, hospital=None, request=None, entity_type=None, entity_id=None):
    """Ghi audit_logs (gọi bên trong cùng transaction với nghiệp vụ)."""
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        hospital=hospital,
        entity_type=entity_type or entity._meta.db_table,
        entity_id=entity_id if entity_id is not None else entity.pk,
        action=action,
        old_values=old,
        new_values=new,
        request_id=getattr(request, "request_id", None) or uuid.uuid4().hex,
        ip_address=client_ip(request),
    )


def notify(user, type_, title, body=None, entity=None, entity_type=None, entity_id=None):
    """BR-48: tạo thông báo trong cùng transaction; nội dung không chứa dữ liệu nhạy cảm."""
    if user is None:
        return None
    return Notification.objects.create(
        user=user,
        type=type_,
        title=title[:200],
        body=(body or "")[:1000] or None,
        entity_type=entity_type or (entity._meta.db_table if entity is not None else None),
        entity_id=entity_id if entity_id is not None else (entity.pk if entity is not None else None),
        channel=Notification.Channel.IN_APP,
        delivery_status=Notification.Delivery.SENT,
        sent_at=timezone.now(),
    )


def notify_hospital_staff(hospital, type_, title, body=None, entity=None, exclude=None):
    """Thông báo cho mọi nhân viên đang hiệu lực của bệnh viện (một vai trò chung)."""
    from bloodbank.models import Staff

    staffs = Staff.objects.filter(hospital=hospital, is_active=True, user__status="active").select_related("user")
    for s in staffs:
        if s.user != exclude:
            notify(s.user, type_, title, body, entity=entity)


def next_code(model, field, prefix):
    """Sinh mã dạng PREFIX-YYYYMMDD-NNNN (giờ Việt Nam)."""
    day = timezone.localtime().strftime("%Y%m%d")
    base = f"{prefix}-{day}-"
    last = (
        model.objects.filter(**{f"{field}__startswith": base}).order_by(f"-{field}").values_list(field, flat=True).first()
    )
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{base}{seq:04d}"


def create_with_code(model, field, prefix, **values):
    """Tạo bản ghi có mã duy nhất; thử lại khi va chạm UNIQUE do tạo đồng thời."""
    for _ in range(5):
        values[field] = next_code(model, field, prefix)
        try:
            with transaction.atomic():
                return model.objects.create(**values)
        except IntegrityError as exc:
            if field not in str(exc) and "request_code" not in str(exc):
                raise
    raise BusinessError("ERR-CONFLICT")


def require(condition, code, message=None):
    if not condition:
        raise BusinessError(code, message)


def positive_int(value, code="ERR-INV-QTY-POSITIVE"):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise BusinessError(code)
    if number <= 0:
        raise BusinessError(code)
    return number
