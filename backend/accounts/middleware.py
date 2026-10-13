from django.contrib.auth import logout


class ActiveUserMiddleware:
    """BR-23: tài khoản bị khóa/xóa mất quyền ở request kế tiếp."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_active:
            logout(request)
        return self.get_response(request)
