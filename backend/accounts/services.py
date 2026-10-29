"""UC-AUT-01..04: đăng ký, đăng nhập, khôi phục mật khẩu, quản lý tài khoản."""
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import AuditLog, Staff, SystemSetting
from bloodbank.services import mailer
from bloodbank.services.common import BusinessError, alert, audit, business_transaction, snapshot

from .models import AuthToken, User, hash_token


def register(data, request=None):
    with business_transaction():
        user = User.objects.create_user(
            email=data["email"],
            password=data["password"],
            full_name=data["full_name"].strip(),
            phone=data.get("phone") or None,
            blood_group=data.get("blood_group") or None,
            province=data.get("province") or None,
            ward=data.get("ward") or None,
            terms_accepted_at=timezone.now(),
        )
        audit(user, user, "create", new=snapshot(user, ["email", "full_name", "phone", "role"]), request=request)
    code = send_email_verification(user, request)
    return user, code


def _too_many_tokens(user, purpose):
    """Giới hạn gửi email: tối đa `auth_email_max_per_window` token cùng loại trong `auth_email_window_minutes` phút."""
    since = timezone.now() - timedelta(minutes=SystemSetting.get("auth_email_window_minutes"))
    sent = AuthToken.objects.filter(user=user, purpose=purpose, created_at__gte=since).count()
    return sent >= SystemSetting.get("auth_email_max_per_window")


def send_email_verification(user, request=None):
    """Gửi mã OTP 6 số (nhập ngay trên trang) kèm liên kết xác thực (mở từ thiết bị khác vẫn được).

    Trả về mã đã gửi, hoặc None nếu đã vượt hạn mức gửi lại."""
    if _too_many_tokens(user, AuthToken.Purpose.EMAIL_VERIFY):
        return None
    ip = request.META.get("REMOTE_ADDR") if request else None
    hours = SystemSetting.get("email_verify_ttl_hours")
    minutes = SystemSetting.get("email_otp_ttl_minutes")
    raw = AuthToken.issue(user, AuthToken.Purpose.EMAIL_VERIFY, ttl=timedelta(hours=hours), ip=ip)
    code = AuthToken.issue_code(user, AuthToken.Purpose.EMAIL_OTP, ttl=timedelta(minutes=minutes), ip=ip)
    link = mailer.absolute(reverse("accounts:verify_email", args=[raw]), request)
    mailer.send_quietly(mailer.build(
        user, f"{code} là mã xác thực email Giọt Hồng",
        [f"Mã xác thực của bạn: {code}", f"Nhập mã này trên trang Giọt Hồng. Mã hết hạn sau {minutes} phút.",
         f"Hoặc bấm nút bên dưới (liên kết hết hạn sau {hours} giờ).",
         "Nếu bạn không đăng ký tài khoản Giọt Hồng, hãy bỏ qua email này."],
        ("Xác thực email", link), request=request))
    return code


def _mark_verified(user):
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at", "updated_at"])
    # Đã xác thực → mã / liên kết còn lại không còn tác dụng
    AuthToken.objects.filter(
        user=user, purpose__in=[AuthToken.Purpose.EMAIL_VERIFY, AuthToken.Purpose.EMAIL_OTP],
        used_at__isnull=True, revoked_at__isnull=True,
    ).update(revoked_at=timezone.now())
    audit(user, user, "email_verified")


def verify_email_code(user, code, request=None):
    """Kiểm tra mã OTP người dùng nhập. Sai quá `email_otp_max_attempts` lần → hủy mã, phải gửi mã mới."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    with transaction.atomic():
        token = (AuthToken.objects.select_for_update()
                 .filter(pk=getattr(AuthToken.current_code(user, AuthToken.Purpose.EMAIL_OTP), "pk", None)).first())
        if token is None:
            raise BusinessError("ERR-NOT-FOUND", "Mã xác thực đã hết hạn. Bấm \"Gửi lại mã\" để nhận mã mới.")
        if len(code) != 6 or not token.matches_code(code):
            failed = AuditLog.objects.filter(entity_type="users", entity_id=user.id, action="email_otp_failed",
                                             created_at__gte=token.created_at).count() + 1
            audit(user, user, "email_otp_failed", request=request)
            left = SystemSetting.get("email_otp_max_attempts") - failed
            if left <= 0:
                token.revoked_at = timezone.now()
                token.save(update_fields=["revoked_at"])
                error = BusinessError("ERR-VALIDATION", "Bạn đã nhập sai quá nhiều lần. Bấm \"Gửi lại mã\" để nhận mã mới.")
            else:
                error = BusinessError("ERR-VALIDATION", f"Mã xác thực không đúng. Bạn còn {left} lần thử.")
        else:
            token.used_at = timezone.now()
            token.save(update_fields=["used_at"])
            _mark_verified(user)
            error = None
    if error:   # raise sau khi commit để lần sai luôn được ghi lại
        raise error
    return user


def verify_email(raw):
    token = AuthToken.find_valid(raw, AuthToken.Purpose.EMAIL_VERIFY)
    if token is None:
        # Liên kết đã dùng (bấm lần 2, hoặc Gmail / Outlook tự mở trước để quét an toàn) mà email đã xác thực → coi là
        # thành công, không báo "không hợp lệ" gây hoang mang
        used = (AuthToken.objects.select_related("user")
                .filter(token_hash=hash_token(raw), purpose=AuthToken.Purpose.EMAIL_VERIFY).first())
        if used is not None and used.user.email_verified_at is not None:
            return used.user
        raise BusinessError("ERR-NOT-FOUND", "Liên kết xác thực không hợp lệ hoặc đã hết hạn. "
                                             "Đăng nhập và bấm \"Gửi lại email xác thực\" trong Hồ sơ của tôi.")
    with business_transaction():
        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])
        user = token.user
        _mark_verified(user)
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


def _hospital_not_approved(user):
    """Bệnh viện tự đăng ký chưa được duyệt / bị từ chối → thông báo lý do thay vì cho vào rồi chặn 403 (BV_014)."""
    staff = Staff.objects.filter(user=user, is_active=True).select_related("hospital").first()
    if staff is None:
        return None
    if staff.hospital.status == "pending":
        return f"{staff.hospital.name} đang chờ Quản trị hệ thống duyệt. Bạn sẽ nhận email khi được duyệt."
    if staff.hospital.status == "rejected":
        return f"Đăng ký {staff.hospital.name} không được duyệt. Lý do: {staff.hospital.reject_reason or '—'}"
    return None


def authenticate_user(email, password, request=None, role=None):
    """Trả về user hoặc raise BusinessError (ERR-AUTH-INVALID-CREDENTIALS / ERR-AUTH-LOCKED / ERR-AUTH-PORTAL).

    `role`: cổng đăng nhập đang dùng. Mật khẩu đúng nhưng sai cổng → ERR-AUTH-PORTAL, không tạo phiên.
    """
    error = None
    # Khóa dòng tài khoản trong suốt lúc đếm lần sai → kiểm tra mật khẩu → ghi lần sai: các lần đăng nhập ĐỒNG THỜI
    # vào cùng tài khoản được xử lý lần lượt, nên không vượt được ngưỡng khóa. Lỗi được raise SAU khi commit
    # để bản ghi login_failed luôn được lưu.
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email=(email or "").strip().lower()).first()
        if user is None or user.status == User.Status.DELETED:
            User().set_password(password)  # cân bằng thời gian phản hồi
            error = BusinessError("ERR-AUTH-INVALID-CREDENTIALS")
        elif user.status == User.Status.LOCKED:
            # Mật khẩu sai → cùng thông báo như email không tồn tại (không lộ tài khoản có tồn tại / đang bị khóa)
            error = BusinessError("ERR-AUTH-LOCKED" if user.check_password(password) else "ERR-AUTH-INVALID-CREDENTIALS")
        elif _recent_failures(user) >= SystemSetting.get("login_max_failed_attempts"):
            error = BusinessError(
                "ERR-AUTH-LOCKED",
                f"Bạn đã nhập sai quá nhiều lần. Vui lòng thử lại sau {SystemSetting.get('login_lock_minutes')} phút.",
            )
        elif not user.check_password(password):
            audit(user, user, "login_failed", request=request)
            error = BusinessError("ERR-AUTH-INVALID-CREDENTIALS")
        elif role is not None and user.role != role:
            audit(user, user, "login_wrong_portal", new={"portal": role}, request=request)
            error = BusinessError("ERR-AUTH-PORTAL")
            error.user_role = user.role
        elif user.role == User.Role.HOSPITAL and (blocked := _hospital_not_approved(user)):
            error = BusinessError("ERR-AUTH-HOSPITAL-PENDING", blocked)
        else:
            user.last_login = timezone.now()
            user.save(update_fields=["last_login", "updated_at"])
            audit(user, user, "login", request=request)
    if error:
        raise error
    return user


def request_password_reset(email, request=None):
    """Luôn trả về như nhau để không lộ email có tồn tại hay không."""
    user = User.objects.filter(email=(email or "").strip().lower(), status=User.Status.ACTIVE).first()
    if user is None or _too_many_tokens(user, AuthToken.Purpose.PASSWORD_RESET):
        return None  # vượt hạn mức: im lặng, phản hồi vẫn giống hệt (không lộ thông tin)
    minutes = SystemSetting.get("password_reset_ttl_minutes")
    raw = AuthToken.issue(user, AuthToken.Purpose.PASSWORD_RESET, ttl=timedelta(minutes=minutes),
                          ip=request.META.get("REMOTE_ADDR") if request else None)
    link = mailer.absolute(reverse("accounts:reset_password", args=[raw]), request)
    mailer.send_quietly(mailer.build(
        user, "Đặt lại mật khẩu Giọt Hồng",
        [f"Bấm nút bên dưới để đặt lại mật khẩu. Liên kết hết hạn sau {minutes} phút.",
         "Nếu bạn không yêu cầu, hãy bỏ qua email này — mật khẩu hiện tại vẫn giữ nguyên."],
        ("Đặt lại mật khẩu", link), request=request))
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
        _alert_password_changed(user)
    return user


def change_password(user, password, request=None):
    with business_transaction():
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        revoke_tokens(user)
        audit(user, user, "password_changed", request=request)
        _alert_password_changed(user)


def _alert_password_changed(user):
    """Báo qua email mỗi lần đổi mật khẩu — chủ tài khoản phát hiện ngay nếu không phải mình đổi."""
    alert([user], "password_changed", "Mật khẩu tài khoản Giọt Hồng vừa được thay đổi",
          f"Mật khẩu của tài khoản {user.email} đã được đổi lúc {timezone.localtime():%H:%M ngày %d/%m/%Y}. "
          "Nếu không phải bạn, hãy đặt lại mật khẩu ngay và báo cho quản trị viên.")


def revoke_tokens(user):
    """Đổi / đặt lại mật khẩu: hủy phiên & liên kết đặt lại mật khẩu còn treo. Giữ liên kết xác thực email (không liên
    quan mật khẩu — trước đây đổi mật khẩu trước khi xác thực làm liên kết trong email hỏng)."""
    (AuthToken.objects.filter(user=user, revoked_at__isnull=True, used_at__isnull=True)
     .exclude(purpose=AuthToken.Purpose.EMAIL_VERIFY).update(revoked_at=timezone.now()))


def set_email_reminders(user, enabled, request=None):
    """Bật / tắt email kêu gọi và nhắc hiến máu (hồ sơ, hoặc liên kết hủy nhận trong email)."""
    with business_transaction():
        old = {"email_reminders": user.email_reminders}
        user.email_reminders = enabled
        user.save(update_fields=["email_reminders", "updated_at"])
        audit(user, user, "update", old=old, new={"email_reminders": enabled}, request=request)


def update_profile(user, form, request=None):
    with business_transaction():
        old = snapshot(User.objects.get(pk=user.pk), form.Meta.fields)
        saved = form.save()
        audit(user, saved, "update", old=old, new=snapshot(saved, form.Meta.fields), request=request)
    return saved
