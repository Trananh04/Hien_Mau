"""Sinh danh mục route/màn hình/vai trò từ chính mã nguồn Django (không dựa vào menu giao diện).

Chạy bên trong container web của môi trường QA:
    docker exec -i hienmau-qa-qa-web-1 python manage.py shell < qa-audit/scripts/build_inventory.py > qa-audit/inventory/routes.json
"""
import inspect
import json

from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from bloodbank import access


def walk(patterns, prefix="", ns=None):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from walk(p.url_patterns, prefix + str(p.pattern), p.namespace or ns)
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), (f"{ns}:{p.name}" if ns else p.name), p.callback


def methods(cb):
    """Suy ra phương thức HTTP từ decorator require_POST / code xử lý POST."""
    src = ""
    fn = cb
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pass
    try:
        full = inspect.getsource(inspect.getmodule(cb))
    except (OSError, TypeError):
        full = ""
    name = fn.__name__
    decorated_post = f"@require_POST\ndef {name}(" in full
    handles_post = "request.POST" in src or 'request.method == "POST"' in src
    if decorated_post:
        return ["POST"]
    return ["GET", "POST"] if handles_post else ["GET"]


def guard(cb):
    try:
        full = inspect.getsource(inspect.getmodule(cb))
    except (OSError, TypeError):
        return ""
    fn = cb
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    for dec in ("staff_required", "member_required", "admin_required", "signed_in_required"):
        if f"@{dec}\n" in full.split(f"def {fn.__name__}(")[0][-200:]:
            return dec
    return ""


rows = []
screen_of = {r: s for s in access.SCREENS for r in s.routes}
for path, name, cb in walk(get_resolver().url_patterns):
    sc = screen_of.get(name)
    fn = cb
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    rows.append({
        "path": "/" + path.replace("^", "").replace("$", ""), "name": name,
        "view": f"{fn.__module__}.{fn.__name__}", "methods": methods(cb), "decorator": guard(cb),
        "screen": sc.code if sc else None, "screen_title": sc.title if sc else None,
        "roles": list(sc.roles) if sc else None, "has_pk": "<int:pk>" in path or "<str:token>" in path,
    })
print(json.dumps(rows, ensure_ascii=False, indent=1))
