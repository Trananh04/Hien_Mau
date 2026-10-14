import uuid

from django.contrib import messages
from django.core.paginator import Paginator

from bloodbank.services.common import BusinessError


def paginate(request, qs, per_page=20):
    page = Paginator(qs, per_page).get_page(request.GET.get("page"))
    return page


def int_or_none(value):
    """Tham số id/số từ client → int, hoặc None nếu rỗng/sai kiểu (tránh lỗi 500 khi lọc theo chuỗi bất kỳ)."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def date_or_none(value):
    """Chuỗi YYYY-MM-DD → date, hoặc None nếu rỗng/không hợp lệ."""
    from datetime import date

    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def new_key():
    """idempotency_key sinh khi hiển thị form — gửi lại cùng khóa sẽ không ghi trùng (BR-40)."""
    return uuid.uuid4().hex


def attempt(request, fn, success=None):
    """Chạy nghiệp vụ; hiển thị thành công chỉ khi đã commit, lỗi nghiệp vụ hiển thị theo mã."""
    try:
        result = fn()
    except BusinessError as exc:
        messages.error(request, exc.message)
        return False, exc
    if success:
        messages.success(request, success(result) if callable(success) else success)
    return True, result


def apply_field_errors(form, exc):
    for field, msg in (exc.field_errors or {}).items():
        if field in form.fields:
            form.add_error(field, msg)


def parse_local_dt(value):
    """Chuỗi datetime-local (giờ Việt Nam) → datetime có múi giờ; None nếu rỗng/sai."""
    from django import forms
    from django.core.exceptions import ValidationError

    from bloodbank.forms import DT_FORMATS

    try:
        return forms.DateTimeField(input_formats=DT_FORMATS, required=False).clean(value)
    except ValidationError:
        return None


def safe_next(request, default):
    """Chỉ chấp nhận đường dẫn nội bộ (chặn open redirect)."""
    from django.shortcuts import redirect

    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return redirect(nxt)
    return redirect(default)
