"""Phân quyền 3 lớp: (1) bảng màn hình theo vai trò (access.py + ScreenAccessMiddleware)
→ (2) phân công tại bệnh viện đang chọn → (3) sở hữu bản ghi (lọc theo hospital/donor trong từng view)."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from bloodbank import access
from bloodbank.models import Staff

SESSION_HOSPITAL = "hospital_id"


def assignments(user):
    if not user.is_authenticated or user.role != access.HOSPITAL:
        return Staff.objects.none()
    return (
        Staff.objects.filter(user=user, is_active=True, hospital__status="active")
        .select_related("hospital")
        .order_by("hospital__name")
    )


def current_staff(request):
    """Phân công đang chọn; `hospital_id` luôn lấy từ phiên, không lấy từ dữ liệu client gửi."""
    if hasattr(request, "_staff_cache"):
        return request._staff_cache
    staff = None
    user = request.user
    if user.is_authenticated and user.is_active and user.role == access.HOSPITAL:
        rows = list(assignments(user))
        chosen = request.session.get(SESSION_HOSPITAL)
        staff = next((s for s in rows if s.hospital_id == chosen), None)
        if staff is None and len(rows) >= 1:
            staff = rows[0]
            request.session[SESSION_HOSPITAL] = staff.hospital_id
    request._staff_cache = staff
    return staff


def _deny(request, reason="forbidden"):
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
    except Exception:  # nhật ký không được làm hỏng phản hồi 403
        pass
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
            _deny(request, "member_role")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(view):
    """Tài khoản Nhân viên bệnh viện, có phân công active tại một bệnh viện active."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _login(request, access.HOSPITAL)
        if request.user.role != access.HOSPITAL:
            _deny(request, "hospital_role")
        staff = current_staff(request)
        if staff is None:
            _deny(request, "no_staff_assignment")
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
            _deny(request, "admin_role")
        return view(request, *args, **kwargs)

    return wrapper


def select_hospital(request, hospital_id):
    rows = assignments(request.user)
    staff = rows.filter(hospital_id=hospital_id).first()
    if staff is None:
        _deny(request, "hospital_scope")
    request.session[SESSION_HOSPITAL] = staff.hospital_id
    return redirect("bloodbank:hospital_dashboard")
