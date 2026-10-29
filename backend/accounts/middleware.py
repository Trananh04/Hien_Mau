from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode


class ActiveUserMiddleware:
    """BR-23: tài khoản bị khóa/xóa mất quyền ở request kế tiếp."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_active:
            logout(request)
        return self.get_response(request)


class EmailVerifiedMiddleware:
    """Người dùng (member) phải nhập mã OTP xác thực email trước khi dùng bất kỳ trang nào khác.

    Chỉ mở các route cần để xác thực / thoát ra; nhân viên bệnh viện và quản trị do hệ thống cấp nên không áp dụng.
    """

    ALLOWED = {"accounts:verify_otp", "accounts:resend_verification", "accounts:verify_email", "accounts:logout",
               "accounts:unsubscribe", "accounts:wards"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        match = request.resolver_match
        if (match is None or match.view_name in self.ALLOWED or not user.is_authenticated
                or user.role != user.Role.MEMBER or user.email_verified_at is not None):
            return None
        if request.path.startswith("/api/"):
            return JsonResponse({"error": {"code": "ERR-AUTH-EMAIL-UNVERIFIED",
                                           "message": "Bạn cần xác thực email trước."}}, status=403)
        nxt = request.get_full_path() if request.method == "GET" else ""
        url = reverse("accounts:verify_otp")
        return redirect(f"{url}?{urlencode({'next': nxt})}" if nxt else url)
