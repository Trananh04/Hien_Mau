"""Lớp phân quyền thứ nhất: mọi request được đối chiếu với bảng màn hình trong `bloodbank/access.py`."""
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

from bloodbank import access


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
            from bloodbank.permissions import _deny

            _deny(request, "route_not_configured")
        if access.PUBLIC in roles:
            return None
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse(access.login_url_for(roles)))
        if user.role not in roles:
            from bloodbank.permissions import _deny

            _deny(request, "screen_role")
        return None
