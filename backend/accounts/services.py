"""UC-AUT-01..04: đăng ký, đăng nhập, khôi phục mật khẩu, quản lý tài khoản."""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import AuditLog, SystemSetting
from bloodbank.services.common import BusinessError, audit, business_transaction, snapshot

from .models import AuthToken, User


def register(data, request=None):
    with business_transaction():
        user = User.objects.create_user(
            email=data["email"],
            password=data["password"],
            full_name=data["full_name"].strip(),
            phone=data.get("phone") or None,
            blood_group=data.get("blood_group") or None,
            province=data.get("province") or None,
            terms_accepted_at=timezone.now(),
        )
        audit(user, user, "create", new=snapshot(user, ["email", "full_name", "phone", "role"]), request=request)
    link = send_email_verification(user, request)
    return user, link


def _absolute(request, path):
    return request.build_absolute_uri(path) if request else path


def send_email_verification(user, request=None):
    hours = SystemSetting.get("email_verify_ttl_hours")
    raw = AuthToken.issue(user, AuthToken.Purpose.EMAIL_VERIFY, ttl=timedelta(hours=hours),
                          ip=request.META.get("REMOTE_ADDR") if request else None)
    link = _absolute(request, reverse("accounts:verify_email", args=[raw]))
    send_mail(
        "Xác thực email — Ngân Hàng Máu Sống",
        f"Chào {user.full_name},\n\nBấm vào liên kết sau để xác thực email (hết hạn sau {hours} giờ):\n{link}\n",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
    return link


def verify_email(raw):
    token = AuthToken.find_valid(raw, AuthToken.Purpose.EMAIL_VERIFY)
    if token is None:
        raise BusinessError("ERR-NOT-FOUND", "Liên kết xác thực không hợp lệ hoặc đã hết hạn.")
    with business_transaction():
        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])
        user = token.user
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at", "updated_at"])
        audit(user, user, "email_verified")
    return user


def _recent_failures(user):
    minutes = SystemSetting.get("login_lock_minutes")
    since = timezone.now() - timedelta(minutes=minutes)
    last_ok = (
        AuditLog.objects.filter(entity_type="users", entity_id=user.id, action="login")
        .order_by("-created_at").values_list("created_at", flat=True).first()
    )
    if last_ok and last_ok > since:
        since = last_ok
    return AuditLog.objects.filter(
        entity_type="users", entity_id=user.id, action="login_failed", created_at__gte=since
    ).count()


def authenticate_user(email, password, request=None, role=None):
    """Trả về user hoặc raise BusinessError (ERR-AUTH-INVALID-CREDENTIALS / ERR-AUTH-LOCKED / ERR-AUTH-PORTAL).

    `role`: cổng đăng nhập đang dùng. Mật khẩu đúng nhưng sai cổng → ERR-AUTH-PORTAL, không tạo phiên.
    """
    user = User.objects.filter(email=(email or "").strip().lower()).first()
    if user is None or user.status == User.Status.DELETED:
        User().set_password(password)  # cân bằng thời gian phản hồi
        raise BusinessError("ERR-AUTH-INVALID-CREDENTIALS")
    if user.status == User.Status.LOCKED:
        raise BusinessError("ERR-AUTH-LOCKED")
    if _recent_failures(user) >= SystemSetting.get("login_max_failed_attempts"):
        raise BusinessError(
            "ERR-AUTH-LOCKED",
            f"Bạn đã nhập sai quá nhiều lần. Vui lòng thử lại sau {SystemSetting.get('login_lock_minutes')} phút.",
        )
    if not user.check_password(password):
        audit(user, user, "login_failed", request=request)
        raise BusinessError("ERR-AUTH-INVALID-CREDENTIALS")
    if role is not None and user.role != role:
        audit(user, user, "login_wrong_portal", new={"portal": role}, request=request)
        exc = BusinessError("ERR-AUTH-PORTAL")
        exc.user_role = user.role
        raise exc
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])
    audit(user, user, "login", request=request)
    return user


def request_password_reset(email, request=None):
    """Luôn trả về như nhau để không lộ email có tồn tại hay không."""
    user = User.objects.filter(email=(email or "").strip().lower(), status=User.Status.ACTIVE).first()
    if user is None:
        return None
    minutes = SystemSetting.get("password_reset_ttl_minutes")
    raw = AuthToken.issue(user, AuthToken.Purpose.PASSWORD_RESET, ttl=timedelta(minutes=minutes),
                          ip=request.META.get("REMOTE_ADDR") if request else None)
    link = _absolute(request, reverse("accounts:reset_password", args=[raw]))
    send_mail(
        "Đặt lại mật khẩu — Ngân Hàng Máu Sống",
        f"Chào {user.full_name},\n\nBấm vào liên kết sau để đặt lại mật khẩu (hết hạn sau {minutes} phút):\n{link}\n\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua email này.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
    audit(user, user, "password_reset_requested", request=request)
    return link


def reset_password(token, password, request=None):
    with business_transaction():
        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])
        user = token.user
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        revoke_tokens(user)
        audit(user, user, "password_reset", request=request)
    return user


def change_password(user, password, request=None):
    with business_transaction():
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        revoke_tokens(user)
        audit(user, user, "password_changed", request=request)


def revoke_tokens(user):
    AuthToken.objects.filter(user=user, revoked_at__isnull=True, used_at__isnull=True).update(revoked_at=timezone.now())


def update_profile(user, form, request=None):
    with business_transaction():
        old = snapshot(User.objects.get(pk=user.pk), form.Meta.fields)
        saved = form.save()
        audit(user, saved, "update", old=old, new=snapshot(saved, form.Meta.fields), request=request)
    return saved
