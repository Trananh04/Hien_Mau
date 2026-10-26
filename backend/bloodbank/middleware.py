"""Lớp phân quyền thứ nhất: mọi request được đối chiếu với bảng màn hình trong `bloodbank/access.py`."""
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.cache import patch_vary_headers

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
        # Bản đồ: ô bản đồ / kiểu / font chữ của Goong (dự phòng OSM); MapLibre chạy web worker từ blob
        "img-src 'self' data: blob: https://tiles.goong.io https://tile.openstreetmap.org",
        "connect-src 'self' https://tiles.goong.io https://tile.openstreetmap.org",
        "worker-src 'self' blob:",
        "child-src blob:",
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


def admin_ip_allowed(request):
    """ADMIN_ALLOWED_IPS trống → không giới hạn. IP lấy theo client_ip (chỉ tin X-Forwarded-For sau proxy tin cậy)."""
    allowed = settings.ADMIN_ALLOWED_IPS
    if not allowed:
        return True
    from bloodbank.services.common import client_ip

    return client_ip(request) in allowed


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
        if match.view_name == "accounts:admin_login" or access.is_admin_only(roles):
            # Cổng quản trị không xác nhận là mình tồn tại: chưa đăng nhập, sai vai trò hay IP ngoài danh sách đều 404
            from bloodbank.permissions import deny

            if not admin_ip_allowed(request):
                deny(request, "admin_ip_not_allowed", hide=True)
            if match.view_name != "accounts:admin_login":
                if not request.user.is_authenticated:
                    raise Http404          # khách / bot dò đường dẫn: không ghi nhật ký cho khỏi ngập
                if request.user.role != access.ADMIN:
                    deny(request, "admin_only", hide=True)
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


class HtmxPageMiddleware:
    """Điều hướng bằng HTMX (hx-boost) chỉ thay <body>, không chạy script của trang mới.

    Trang cần script riêng (bản đồ Leaflet, hiệu ứng cuộn) được tải đầy đủ: trả `HX-Redirect` TRƯỚC khi chạy view
    (để thông báo flash chưa bị tiêu thụ). Chỉ áp dụng cho GET; form trên các trang này gửi kiểu thường (hx-boost=false).
    """

    FULL_PAGE = {"bloodbank:map", "bloodbank:campaign_detail", "bloodbank:process",
                 "bloodbank:hospital_campaign_create", "bloodbank:hospital_campaign_edit", "bloodbank:hospital_info",
                 "bloodbank:admin_hospital_create", "bloodbank:admin_hospital_edit"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        patch_vary_headers(response, ["HX-Request"])   # cùng URL, khác cách tải → không dùng chung bộ đệm
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if (request.method == "GET" and request.headers.get("HX-Request") == "true"
                and match is not None and match.view_name in self.FULL_PAGE):
            response = HttpResponse(status=200)
            response["HX-Redirect"] = request.get_full_path()
            return response
        return None
