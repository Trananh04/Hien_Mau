"""Phân quyền 3 lớp: (1) bảng màn hình theo vai trò (access.py + ScreenAccessMiddleware)
→ (2) phân công tại bệnh viện của nhân viên → (3) sở hữu bản ghi (lọc theo hospital/donor trong từng view)."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse

from bloodbank import access
from bloodbank.models import Staff


def current_staff(request):
    """Phân công duy nhất của nhân viên (BR-03, BR-04); bệnh viện luôn lấy từ phân công, không từ dữ liệu client gửi."""
    if hasattr(request, "_staff_cache"):
        return request._staff_cache
    staff = None
    user = request.user
    if user.is_authenticated and user.is_active and user.role == access.HOSPITAL:
        staff = (
            Staff.objects.filter(user=user, is_active=True, hospital__status="active").select_related("hospital").first()
        )
    request._staff_cache = staff
    return staff


def deny(request, reason="forbidden", hide=False):
    """Ghi nhật ký access_denied rồi chặn: 403, hoặc 404 khi `hide` (khu quản trị không xác nhận là mình tồn tại)."""
    from bloodbank.services.common import audit

    try:
        audit(
            request.user if request.user.is_authenticated else None,
            None,
            "access_denied",
            new={"path": request.path, "reason": reason},
            entity_type="route",
            entity_id=0,
            request=request,
        )
    except Exception:  # nhật ký không được làm hỏng phản hồi
        pass
    if hide:
        raise Http404
    raise PermissionDenied


def _login(request, role):
    return redirect_to_login(request.get_full_path(), reverse(access.LOGIN_URLS[role]))


def signed_in_required(view):
    """Màn hình dùng chung khi đã đăng nhập; vai trò cụ thể do bảng access.py quyết định."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login(request, access.MEMBER)
        return view(request, *args, **kwargs)

    return wrapper


def member_required(view):
    """Màn hình của Người dùng (người hiến / người nhà bệnh nhân)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login(request, access.MEMBER)
        if request.user.role != access.MEMBER:
            deny(request, "member_role")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(view):
    """Tài khoản Nhân viên bệnh viện, có phân công active tại một bệnh viện active."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login(request, access.HOSPITAL)
        if request.user.role != access.HOSPITAL:
            deny(request, "hospital_role")
        staff = current_staff(request)
        if staff is None:
            deny(request, "no_staff_assignment")
        request.staff = staff
        request.hospital = staff.hospital
        return view(request, *args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login(request, access.ADMIN)
        if not request.user.is_admin:
            deny(request, "admin_role")
        return view(request, *args, **kwargs)

    return wrapper

