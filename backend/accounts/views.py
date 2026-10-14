from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from bloodbank import access
from bloodbank.services.common import BusinessError

from . import services
from .forms import ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm
from .models import AuthToken


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
        "greeting": "Xin chào", "art_title": "NGÂN HÀNG MÁU SỐNG VIỆT NAM",
        "art_text": "Hãy đăng ký tham gia cùng chúng tôi để tạo ra nguồn máu vô tận, sẵn sàng giúp đỡ cộng đồng và lan tỏa những giá trị nhân văn cao đẹp.",
    },
    access.HOSPITAL: {
        "title": "Đăng nhập bệnh viện", "lead": "Dành cho nhân viên bệnh viện đã được Quản trị hệ thống cấp tài khoản.",
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
                hint = {"label": access.ROLE_LABELS.get(own), "url": reverse(access.LOGIN_URLS.get(own, "accounts:login"))}
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
    portals = [{"code": c, "label": l, "url": reverse(u), "icon": i, "current": c == role}
               for c, l, u, _, i in access.ROLES]
    return render(request, "accounts/login.html", {
        "form": form, "error": error, "hint": hint, "next": request.GET.get("next", ""), "portal": portal,
        "role": role, "portals": portals,
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
        user, link = services.register(form.cleaned_data, request)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Tạo tài khoản thành công. Chúng tôi đã gửi email xác thực tới hộp thư của bạn.")
        _dev_link(request, "Liên kết xác thực email", link)
        return redirect(_safe_next(request, reverse("bloodbank:campaigns")))
    return render(request, "accounts/register.html", {"form": form, "next": request.GET.get("next", "")})


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
    link = services.send_email_verification(request.user, request)
    if link is None:
        messages.warning(request, "Bạn vừa yêu cầu gửi lại nhiều lần. Vui lòng kiểm tra hộp thư hoặc thử lại sau ít phút.")
        return redirect("bloodbank:profile")
    messages.success(request, "Đã gửi lại email xác thực.")
    _dev_link(request, "Liên kết xác thực email", link)
    return redirect("bloodbank:profile")
