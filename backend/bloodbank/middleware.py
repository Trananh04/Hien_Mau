"""Lớp phân quyền thứ nhất: mọi request được đối chiếu với bảng màn hình trong `bloodbank/access.py`."""
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.urls import reverse

from bloodbank import access


class SecurityHeadersMiddleware:
    """Header bảo vệ trình duyệt bổ sung cho SecurityMiddleware của Django: CSP + Permissions-Policy.

    CSP chỉ cho chạy script / CSS từ chính máy chủ (không script, thẻ style hay thuộc tính style inline, không eval)
    → chặn phần lớn XSS và chèn CSS kể cả khi lọt dữ liệu. Template dùng class (ui.css), JS gán style qua CSSOM.
    """

    CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: https://*.tile.openstreetmap.org",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])
    # geolocation=(self): chỉ trang của chính hệ thống được xin vị trí (nút "Dùng vị trí của tôi" trong trợ lý)
    PERMISSIONS = "camera=(), microphone=(), geolocation=(self), payment=(), usb=(), interest-cohort=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.CSP)
        response.headers.setdefault("Permissions-Policy", self.PERMISSIONS)
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


class ScreenAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if match is None:
            return None
        roles = access.roles_for(match.view_name)
        if roles is None:
            from bloodbank.permissions import deny

            deny(request, "route_not_configured")
        if access.PUBLIC in roles:
            return None
        user = request.user
        api = request.path.startswith("/api/")
        if not user.is_authenticated:
            if api:
                return JsonResponse({"error": {"code": "ERR-AUTH-UNAUTHENTICATED", "message": "Bạn cần đăng nhập."}},
                                    status=401)
            return redirect_to_login(request.get_full_path(), reverse(access.login_url_for(roles)))
        if user.role not in roles:
            from bloodbank.permissions import deny

            if api:
                try:
                    deny(request, "screen_role")
                except Exception:  # noqa: BLE001 — deny ghi nhật ký rồi raise PermissionDenied
                    pass
                return JsonResponse({"error": {"code": "ERR-AUTH-FORBIDDEN",
                                               "message": "Bạn không có quyền truy cập."}}, status=403)
            deny(request, "screen_role")
        return None
