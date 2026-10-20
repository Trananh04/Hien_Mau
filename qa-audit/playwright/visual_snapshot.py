                                                                    """Chụp ảnh toàn trang mọi màn hình (máy tính + điện thoại) để so sánh giao diện trước / sau khi refactor.

  QA_BASE_URL=... QA_ACCOUNT_PASSWORD=... QA_SNAP_OUT=evidence/runs/snap-before python playwright/visual_snapshot.py
  python playwright/visual_snapshot.py --diff evidence/runs/snap-before evidence/runs/snap-after

Chỉ đọc — không gửi form thay đổi dữ liệu. Ảnh động (bản đồ) được ẩn để so sánh ổn định.
"""
import os
import sys
from pathlib import Path

if len(sys.argv) == 4 and sys.argv[1] == "--diff":
    from PIL import Image, ImageChops

    a_dir, b_dir = Path(sys.argv[2]), Path(sys.argv[3])
    changed = 0
    for a in sorted(a_dir.glob("*.png")):
        b = b_dir / a.name
        if not b.exists():
            print("THIẾU", a.name); changed += 1; continue
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        if ia.size != ib.size:
            print(f"KHÁC KÍCH THƯỚC {a.name}: {ia.size} → {ib.size}"); changed += 1; continue
        box = ImageChops.difference(ia, ib).getbbox()
        if box:
            print(f"KHÁC {a.name}: vùng {box}"); changed += 1
    print(f"{changed} ảnh khác / {len(list(a_dir.glob('*.png')))}")
    sys.exit(0)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("QA_BASE_URL", "http://host.docker.internal:8080").rstrip("/")
PW = os.environ["QA_ACCOUNT_PASSWORD"]
OUT = Path(os.environ.get("QA_SNAP_OUT", "evidence/runs/snap"))
OUT.mkdir(parents=True, exist_ok=True)

ROLES = {
    "anon": (None, None, ["/", "/dot-hien/", "/dot-hien/2/", "/ban-do/", "/dang-nhap/", "/dang-ky/", "/quen-mat-khau/",
                          "/benh-vien/dang-nhap/", "/quan-tri/dang-nhap/", "/khong-ton-tai/"]),
    "member": ("/dang-nhap/", "an.nguyen@demo.vn", [
        "/", "/dot-hien/2/", "/tai-khoan/", "/tai-khoan/don-dang-ky/", "/tai-khoan/lich-su-hien/",
        "/tai-khoan/yeu-cau-can-mau/", "/can-mau/gui-yeu-cau/", "/thong-bao/"]),
    "hospital": ("/benh-vien/dang-nhap/", "benhvien1@hienmau.vn", [
        "/benh-vien/", "/benh-vien/dot-hien/", "/benh-vien/dot-hien/tao/", "/benh-vien/dot-hien/2/sua/", "/benh-vien/dot-hien/2/",
        "/benh-vien/dot-hien/2/?tab=registrations", "/benh-vien/dot-hien/2/diem-hien/",
        "/benh-vien/cho-xet-nghiem/", "/benh-vien/kho/", "/benh-vien/kho/phieu/nhap/", "/benh-vien/kho/phieu/xuat/",
        "/benh-vien/kho/phieu/dieu-chinh/", "/benh-vien/kho/lich-su/", "/benh-vien/nhu-cau/",
        "/benh-vien/tim-nguon/?blood_group=O%2B&product=2", "/benh-vien/yeu-cau-ho-tro/", "/benh-vien/de-nghi-den/",
        "/benh-vien/yeu-cau-can-mau/", "/benh-vien/luot-hien/1/", "/benh-vien/nguoi-hien/",
        "/benh-vien/nguoi-hien/?q=a", "/benh-vien/bao-cao-tiep-nhan/", "/benh-vien/nhat-ky/", "/benh-vien/thong-tin/",
        "/benh-vien/nhan-vien/", "/tai-khoan-cong-tac/", "/danh-muc/"]),
    "admin": ("/quan-tri/dang-nhap/", "admin@hienmau.vn", [
        "/quan-tri/thong-ke/", "/quan-tri/nguoi-dung/", "/quan-tri/benh-vien/", "/quan-tri/benh-vien/1/",
        "/quan-tri/benh-vien/tao/", "/quan-tri/nhat-ky/", "/quan-tri/cau-hinh/", "/quan-tri/phan-quyen/", "/danh-muc/"]),
}
VIEWPORTS = {"desktop": (1366, 850), "mobile": (390, 844)}
FREEZE = """
  *, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; }
  .leaflet-container, [data-map] { visibility: hidden !important; }
"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    for vp, (w, h) in VIEWPORTS.items():
        for role, (login_url, email, pages) in ROLES.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh",
                                      bypass_csp=True)
            page = ctx.new_page()
            if login_url:
                page.goto(BASE + login_url)
                page.fill("input[name=email]", email)
                page.fill("input[name=password]", PW)
                page.click("form button[type=submit]")
                page.wait_for_load_state("networkidle")
            for path in pages:
                page.goto(BASE + path, wait_until="networkidle")
                page.add_style_tag(content=FREEZE)
                page.evaluate("document.querySelectorAll('.flash, .messages, [data-flash]').forEach(e => e.remove())")
                name = f"{vp}_{role}_{path.strip('/').replace('/', '_').replace('?', '_').replace('=', '-') or 'home'}"[:120]
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            ctx.close()
    browser.close()
print("Đã chụp vào", OUT)
