from django.shortcuts import render


def permission_denied(request, exception=None):
    from django.urls import reverse

    from bloodbank import access

    match = getattr(request, "resolver_match", None)
    roles = access.roles_for(match.view_name) if match else None
    allowed = [code for code in (roles or ()) if code in access.ROLE_LABELS]
    text = "Trang hoặc thao tác này dành cho vai trò khác."
    portals = []
    if allowed:
        text = "Trang này chỉ dành cho: " + ", ".join(access.ROLE_LABELS[c] for c in allowed) + "."
        portals = [{"label": access.ROLE_LABELS[c], "url": reverse(access.LOGIN_URLS[c])} for c in allowed]
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        text += f" Bạn đang đăng nhập với tài khoản {access.ROLE_LABELS.get(user.role, '')}."
    return render(request, "errors/error.html", {
        "code": 403, "title": "Bạn không có quyền mở trang này", "text": text, "portals": portals,
        "home_url": reverse(access.home_for(user)) if user is not None and user.is_authenticated else reverse("bloodbank:home"),
    }, status=403)


def page_not_found(request, exception=None):
    return render(request, "errors/error.html", {
        "code": 404, "title": "Không tìm thấy trang",
        "text": "Đường dẫn không tồn tại hoặc dữ liệu nằm ngoài phạm vi bạn được xem.",
    }, status=404)


def server_error(request):
    return render(request, "errors/error.html", {
        "code": 500, "title": "Chưa xác định được kết quả",
        "text": "Hệ thống gặp sự cố. Thao tác có thể chưa được ghi nhận. Bạn thử lại được, hệ thống sẽ không ghi trùng.",
    }, status=500)
