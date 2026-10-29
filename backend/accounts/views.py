from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from bloodbank import access
from bloodbank.services.common import BusinessError
from bloodbank.services.mailer import unsubscribe_user_id

from . import services
from .forms import ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm, ward_options
from .models import AuthToken, User


def _safe_next(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default


def _home_for(user):
    return access.home_for(user)


# Ba cổng đăng nhập — mỗi cổng chỉ nhận tài khoản đúng vai trò (xem bloodbank/access.py)
PORTALS = {
    access.MEMBER: {
        "title": "Đăng nhập", "lead": "Dành cho người hiến máu và người nhà bệnh nhân.", "icon": "log-in",
        "greeting": "Xin chào", "art_title": "GIỌT HỒNG",
        "art_text": "Một tài khoản cho cả hai việc: đăng ký hiến máu và gửi yêu cầu khi người nhà cần máu.",
    },
    access.HOSPITAL: {
        "title": "Đăng nhập bệnh viện", "lead": "Dành cho quản lý và nhân viên của bệnh viện đã được duyệt.",
        "icon": "hospital", "greeting": "Cổng bệnh viện", "art_title": "KHU LÀM VIỆC BỆNH VIỆN",
        "art_text": "Quản lý đợt hiến, điểm hiến, kho máu, điều phối liên viện và yêu cầu cần máu của bệnh viện.",
    },
    access.ADMIN: {
        "title": "Đăng nhập quản trị", "lead": "Chỉ dành cho Quản trị hệ thống.", "icon": "shield-check",
        "greeting": "Cổng quản trị", "art_title": "QUẢN TRỊ HỆ THỐNG",
        "art_text": "Quản lý người dùng, bệnh viện, tài khoản nhân viên, danh mục chế phẩm, cấu hình và phân quyền.",
    },
}


def _dev_link(request, label, link):
    # Chỉ ở chế độ phát triển (email in ra console): hiện liên kết để thử luồng ngay trên trình duyệt
    if settings.DEBUG and link and settings.EMAIL_BACKEND.endswith("console.EmailBackend"):
        messages.info(request, f"(Chế độ phát triển) {label}: {link}")


def _login(request, role):
    portal = PORTALS[role]
    if request.user.is_authenticated and request.user.role == role:
        return redirect(_home_for(request.user))
    form = LoginForm(request.POST if request.method == "POST" else None)
    error, hint = None, None
    if request.method == "POST" and form.is_valid():
        try:
            user = services.authenticate_user(form.cleaned_data["email"], form.cleaned_data["password"], request, role=role)
        except BusinessError as exc:
            error = exc.message
            if exc.code == "ERR-AUTH-PORTAL":
                own = getattr(exc, "user_role", access.MEMBER)
                if own == access.ADMIN:   # không tiết lộ đường dẫn cổng quản trị
                    error = "Tài khoản này không đăng nhập được tại cổng này."
                else:
                    hint = {"label": access.ROLE_LABELS.get(own),
                            "url": reverse(access.LOGIN_URLS.get(own, "accounts:login"))}
                    error = f"Đây là tài khoản {hint['label']}, không đăng nhập được tại cổng này."
        else:
            if request.user.is_authenticated:
                logout(request)  # đang đăng nhập vai trò khác → thay phiên
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"Chào mừng {user.short_name} quay lại!")
            nxt = _safe_next(request, None)
            if nxt and not access.can_open(user, _route_of(nxt)):
                nxt = None
            return redirect(nxt or reverse(_home_for(user)))
    # Người dùng / Bệnh viện chuyển qua lại bằng 2 tab trên trang; không bao giờ liệt kê cổng quản trị
    return render(request, "accounts/login.html", {
        "form": form, "error": error, "hint": hint, "next": request.GET.get("next", ""), "portal": portal,
        "role": role,
    })


def _route_of(path):
    from django.urls import Resolver404, resolve

    try:
        return resolve(path.split("?")[0]).view_name
    except Resolver404:
        return None


def login_view(request):
    return _login(request, access.MEMBER)


def hospital_login_view(request):
    return _login(request, access.HOSPITAL)


def admin_login_view(request):
    return _login(request, access.ADMIN)


def register_view(request):
    if request.user.is_authenticated:
        return redirect(_home_for(request.user))
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user, code = services.register(form.cleaned_data, request)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Tạo tài khoản thành công. Nhập mã 6 số vừa gửi tới email của bạn để hoàn tất.")
        _dev_link(request, "Mã xác thực email", code)
        # Bắt buộc xác thực ngay: trang nhập mã, xong mới về trang người dùng định tới
        nxt = _safe_next(request, reverse("bloodbank:campaigns"))
        return redirect(f"{reverse('accounts:verify_otp')}?{urlencode({'next': nxt})}")
    return render(request, "accounts/register.html", {"form": form, "next": request.GET.get("next", "")})


def verify_otp_view(request):
    """Nhập mã OTP xác thực email. Người dùng chưa xác thực bị EmailVerifiedMiddleware đưa về đây."""
    user = request.user
    nxt = _safe_next(request, reverse("bloodbank:campaigns"))
    if user.email_verified_at:
        return redirect(nxt)
    error = None
    if request.method == "POST":
        try:
            services.verify_email_code(user, request.POST.get("code"), request)
        except BusinessError as exc:
            error = exc.message
        else:
            messages.success(request, "Email của bạn đã được xác thực. Chào mừng bạn đến với Giọt Hồng!")
            return redirect(nxt)
    return render(request, "accounts/verify_otp.html", {"error": error, "next": nxt})


def wards_view(request):
    """<option> Phường/Xã của một tỉnh cho ô chọn phụ thuộc (HTMX)."""
    return render(request, "partials/ward_options.html", {"options": ward_options(request.GET.get("province"))})


def hospital_register_view(request):
    """BV_014: bệnh viện tự đăng ký (kèm tài khoản Quản lý) → chờ Quản trị hệ thống duyệt."""
    from accounts.provinces import center_of
    from bloodbank.forms import HospitalSignupForm
    from bloodbank.services import hospital_signup

    if request.user.is_authenticated:
        return redirect(_home_for(request.user))
    form = HospitalSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            hospital, _ = hospital_signup.register_hospital(form.cleaned_data, request)
        except BusinessError as exc:
            messages.error(request, exc.message)
        else:
            return render(request, "accounts/hospital_register_done.html", {"hospital": hospital,
                                                                             "email": form.cleaned_data["manager_email"]})
    lat, lng = center_of(form["province"].value() or "")
    return render(request, "accounts/hospital_register.html", {"form": form, "center_lat": lat, "center_lng": lng})


@require_POST
def logout_view(request):
    role = request.user.role if request.user.is_authenticated else access.MEMBER
    logout(request)
    messages.success(request, "Bạn đã đăng xuất.")
    # Nhân viên / quản trị quay về đúng cổng đăng nhập của mình
    return redirect("bloodbank:home" if role == access.MEMBER else access.LOGIN_URLS[role])


def forgot_password_view(request):
    form = ForgotPasswordForm(request.POST or None)
    sent = False
    if request.method == "POST" and form.is_valid():
        link = services.request_password_reset(form.cleaned_data["email"], request)
        _dev_link(request, "Liên kết đặt lại mật khẩu", link)
        sent = True
    return render(request, "accounts/forgot.html", {"form": form, "sent": sent})


def reset_password_view(request, token):
    record = AuthToken.find_valid(token, AuthToken.Purpose.PASSWORD_RESET)
    if record is None:
        return render(request, "accounts/reset.html", {"invalid": True})
    form = ResetPasswordForm(request.POST or None, user=record.user)
    if request.method == "POST" and form.is_valid():
        services.reset_password(record, form.cleaned_data["password"], request)
        messages.success(request, "Đã đặt lại mật khẩu. Vui lòng đăng nhập bằng mật khẩu mới.")
        return redirect(access.LOGIN_URLS.get(record.user.role, "accounts:login"))
    return render(request, "accounts/reset.html", {"form": form})


def verify_email_view(request, token):
    try:
        services.verify_email(token)
    except BusinessError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "Email của bạn đã được xác thực.")
    if request.user.is_authenticated:
        return redirect("bloodbank:profile" if request.user.role == access.MEMBER else access.home_for(request.user))
    return redirect("accounts:login")


@require_POST
def resend_verification_view(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    back = f"{reverse('accounts:verify_otp')}?{urlencode({'next': _safe_next(request, reverse('bloodbank:campaigns'))})}"
    if request.user.email_verified_at:
        messages.info(request, "Email của bạn đã được xác thực.")
        return redirect("bloodbank:profile")
    code = services.send_email_verification(request.user, request)
    if code is None:
        messages.warning(request, "Bạn vừa yêu cầu gửi lại nhiều lần. Vui lòng kiểm tra hộp thư hoặc thử lại sau ít phút.")
        return redirect(back)
    messages.success(request, "Đã gửi mã xác thực mới tới email của bạn.")
    _dev_link(request, "Mã xác thực email", code)
    return redirect(back)


# Nút "Hủy đăng ký" của Gmail / Outlook gửi POST một lần bấm, không có cookie CSRF (RFC 8058). Liên kết đã ký nên không
# đoán được; nó chỉ TẮT email kêu gọi / nhắc hiến, không đổi gì khác.
@csrf_exempt
def unsubscribe_view(request, token):
    user_id = unsubscribe_user_id(token)
    user = User.objects.filter(pk=user_id).first() if user_id is not None else None
    if user is not None and request.method == "POST":
        services.set_email_reminders(user, False, request)
    return render(request, "accounts/unsubscribe.html", {"target": user, "done": request.method == "POST"})
