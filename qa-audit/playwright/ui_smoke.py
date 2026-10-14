"""Kiểm thử giao diện (Playwright, Chromium headless) trên môi trường QA.

Với từng vai trò × kích thước màn hình: mở các trang chính, ghi lỗi console, request lỗi (≥400 / failed),
tràn ngang (scrollWidth > viewport) và chụp ảnh màn hình. Chỉ đọc — không gửi form thay đổi dữ liệu.

Chạy (Docker):
  docker run --rm --add-host=host.docker.internal:host-gateway -e QA_BASE_URL=http://host.docker.internal:8091 \
    -e QA_ACCOUNT_PASSWORD=... -v <repo>/qa-audit:/qa -w /qa mcr.microsoft.com/playwright/python:v1.48.0-jammy \
    python playwright/ui_smoke.py
"""
import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE_URL", "http://host.docker.internal:8091").rstrip("/")
PW = os.environ["QA_ACCOUNT_PASSWORD"]
OUT = Path(os.environ.get("QA_UI_OUT", f"evidence/runs/ui-{time.strftime('%Y%m%d-%H%M%S')}"))
OUT.mkdir(parents=True, exist_ok=True)

ROLES = {
    "anon": (None, None, ["/", "/dot-hien/", "/dot-hien/2/", "/ban-do/", "/dang-nhap/", "/dang-ky/", "/quen-mat-khau/",
                          "/benh-vien/dang-nhap/", "/quan-tri/dang-nhap/", "/khong-ton-tai/"]),
    "member": ("/dang-nhap/", "an.nguyen@demo.vn", ["/tai-khoan/", "/tai-khoan/don-dang-ky/", "/tai-khoan/lich-su-hien/",
                                                    "/tai-khoan/yeu-cau-can-mau/", "/can-mau/gui-yeu-cau/", "/thong-bao/"]),
    "hospital": ("/benh-vien/dang-nhap/", "benhvien1@hienmau.vn", [
        "/benh-vien/", "/benh-vien/dot-hien/", "/benh-vien/dot-hien/2/", "/benh-vien/dot-hien/2/diem-hien/",
        "/benh-vien/cho-xet-nghiem/", "/benh-vien/kho/", "/benh-vien/kho/phieu/xuat/", "/benh-vien/kho/lich-su/",
        "/benh-vien/nhu-cau/", "/benh-vien/tim-nguon/?blood_group=O%2B&product=2", "/benh-vien/yeu-cau-ho-tro/",
        "/benh-vien/de-nghi-den/", "/benh-vien/yeu-cau-can-mau/", "/benh-vien/luot-hien/1/", "/benh-vien/nguoi-hien/",
        "/benh-vien/bao-cao-tiep-nhan/", "/benh-vien/nhat-ky/"]),
    "admin": ("/quan-tri/dang-nhap/", "admin@hienmau.vn", ["/quan-tri/thong-ke/", "/quan-tri/nguoi-dung/",
                                                          "/quan-tri/benh-vien/", "/quan-tri/nhat-ky/", "/quan-tri/cau-hinh/",
                                                          "/quan-tri/phan-quyen/", "/danh-muc/"]),
}
VIEWPORTS = {"desktop": (1366, 850), "mobile": (390, 844)}
EXPECTED_STATUS = {"/khong-ton-tai/": 404}

results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for vp_name, (w, hgt) in VIEWPORTS.items():
        for role, (login_url, email, pages) in ROLES.items():
            ctx = browser.new_context(viewport={"width": w, "height": hgt}, locale="vi-VN")
            page = ctx.new_page()
            console, bad_req = [], []
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
            page.on("requestfailed", lambda r: bad_req.append(f"FAILED {r.url} {r.failure}"))
            page.on("response", lambda r: bad_req.append(f"{r.status} {r.url}") if r.status >= 400 else None)
            if login_url:
                page.goto(BASE + login_url)
                page.fill("input[name=email]", email)
                page.fill("input[name=password]", PW)
                page.click("form button[type=submit]")
                page.wait_for_load_state("networkidle")
            for path in pages:
                console.clear(); bad_req.clear()
                resp = page.goto(BASE + path, wait_until="networkidle")
                status = resp.status if resp else None
                overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                clipped = page.evaluate("""() => [...document.querySelectorAll('button, a.btn, .badge, th, td, h1, h2')]
                    .filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflow !== 'visible'
                                 && getComputedStyle(e).textOverflow !== 'ellipsis')
                    .slice(0, 5).map(e => e.tagName + ':' + (e.innerText || '').trim().slice(0, 40))""")
                name = f"{vp_name}_{role}_{path.strip('/').replace('/', '_').replace('?', '_') or 'home'}"[:120]
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
                expected = EXPECTED_STATUS.get(path, 200)
                issues = []
                if status != expected:
                    issues.append(f"HTTP {status} (kỳ vọng {expected})")
                if overflow > 1:
                    issues.append(f"tràn ngang {overflow}px")
                if clipped:
                    issues.append(f"nội dung bị cắt: {clipped}")
                errs = [c for c in console if "favicon" not in c]
                if errs:
                    issues.append(f"console: {errs[:3]}")
                reqs = [b for b in bad_req if not b.startswith("404 " + BASE + path)]
                if reqs and expected == 200:
                    issues.append(f"request lỗi: {reqs[:3]}")
                results.append({"viewport": vp_name, "role": role, "path": path, "status": status, "issues": issues,
                                "screenshot": f"{name}.png"})
                print(f"[{'OK ' if not issues else 'BAD'}] {vp_name:7} {role:8} {path} {'; '.join(issues)}", flush=True)
            ctx.close()
    browser.close()
(OUT / "ui_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{sum(not r['issues'] for r in results)}/{len(results)} trang không có vấn đề. Ảnh: {OUT}")
