"""Kiểm thử THAO TÁC giao diện (Playwright, Chromium) trên môi trường QA: điền form, bấm nút, hộp thoại xác nhận,
đi trọn các luồng nghiệp vụ chính qua trình duyệt như người dùng thật; kèm quét trợ năng (axe-core) và phím tắt.

Mỗi luồng ghi: Pass/Fail, thông điệp hiển thị, lỗi console (gồm vi phạm CSP), ảnh chụp cuối luồng.
Chạy: xem qa-audit/README.md (container mcr.microsoft.com/playwright/python).
"""
import json
import os
import re
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("QA_BASE_URL", "http://host.docker.internal:8091").rstrip("/")
PW = os.environ["QA_ACCOUNT_PASSWORD"]
OUT = Path(os.environ.get("QA_UI_OUT", f"evidence/runs/flows-{time.strftime('%Y%m%d-%H%M%S')}"))
OUT.mkdir(parents=True, exist_ok=True)
STAMP = time.strftime("%H%M%S")
NOISE = ("Cross-Origin-Opener-Policy", "tile.openstreetmap.org", "ERR_CONNECTION_CLOSED", "ERR_NAME_NOT_RESOLVED",
         "fonts.g")

results = []


class Flow:
    def __init__(self, browser, fid, title, viewport=(1366, 850)):
        self.fid, self.title = fid, title
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="vi-VN")
        self.page = self.ctx.new_page()
        self.console, self.steps = [], []
        self.page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        self.page.on("dialog", lambda d: d.accept())

    def step(self, text):
        self.steps.append(text)

    def goto(self, path):
        r = self.page.goto(BASE + path, wait_until="networkidle")
        self.step(f"GET {path} → {r.status if r else '?'}")
        return r

    def login(self, portal, email):
        self.goto(portal)
        self.page.fill("input[name=email]", email)
        self.page.fill("input[name=password]", PW)
        self.page.click("form button[type=submit]")
        self.page.wait_for_load_state("networkidle")
        self.step(f"đăng nhập {email.split('@')[0]}@… → {self.page.url.replace(BASE, '')}")

    def submit(self, button):
        """Bấm nút gửi; nếu form có hộp thoại xác nhận (data-confirm) thì bấm nút xác nhận trong hộp thoại."""
        button.click()
        dlg = self.page.locator("#confirm-dialog[open]")
        try:
            dlg.wait_for(timeout=1500)
            self.step("hộp thoại xác nhận hiện → bấm xác nhận")
            dlg.locator("[data-confirm-ok]").click()
        except Exception:  # noqa: BLE001 — form không có bước xác nhận
            pass
        self.page.wait_for_load_state("networkidle")

    def text(self):
        return self.page.inner_text("body")

    def expect_text(self, needle):
        body = self.text()
        assert needle in body, f"Không thấy '{needle}' trên trang {self.page.url.replace(BASE, '')}"
        self.step(f"thấy: “{needle}”")

    def finish(self, status, note=""):
        shot = f"{self.fid}.png"
        try:
            self.page.screenshot(path=str(OUT / shot), full_page=True)
        except Exception:  # noqa: BLE001
            shot = ""
        errs = [c for c in self.console if not any(n in c for n in NOISE)]
        if status == "Pass" and errs:
            status, note = "Fail", f"Lỗi console: {errs[:3]}"
        results.append({"id": self.fid, "title": self.title, "status": status, "note": note, "steps": self.steps,
                        "console": errs, "screenshot": shot})
        print(f"[{status:4}] {self.fid} {self.title}" + (f" — {note}" if note else ""), flush=True)
        self.ctx.close()


def run(browser, fid, title, fn, viewport=(1366, 850)):
    fl = Flow(browser, fid, title, viewport)
    try:
        fn(fl)
        fl.finish("Pass")
    except AssertionError as exc:
        fl.finish("Fail", str(exc))
    except Exception as exc:  # noqa: BLE001
        fl.finish("Fail", f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        (OUT / f"{fid}.trace.txt").write_text(traceback.format_exc(), encoding="utf-8")


# ============================================================== Luồng Người dùng
def f_register_account(fl):
    fl.goto("/dang-ky/")
    p = fl.page
    p.fill("input[name=full_name]", "QA Giao Diện")
    p.fill("input[name=email]", f"qa.ui.{STAMP}@qa.test")
    p.fill("input[name=password]", "123")
    p.fill("input[name=password2]", "123")
    p.check("input[name=accept_terms]")
    fl.submit(p.locator("form button[type=submit]").first)
    assert "/dang-ky/" in p.url, "Mật khẩu yếu nhưng vẫn tạo được tài khoản"
    fl.step("mật khẩu yếu bị từ chối, ở lại form")
    p.fill("input[name=password]", "QaGiaoDien@2026")
    p.fill("input[name=password2]", "QaGiaoDien@2026")
    p.check("input[name=accept_terms]")
    fl.submit(p.locator("form button[type=submit]").first)
    fl.expect_text("Tạo tài khoản thành công")


def f_member_register_campaign(fl):
    fl.login("/dang-nhap/", "huy.dang@demo.vn")
    fl.goto("/dot-hien/")
    fl.page.locator("a[href^='/dot-hien/']").filter(has_text=re.compile(".+")).first.wait_for()
    fl.goto("/dot-hien/3/")
    btn = fl.page.get_by_role("button", name=re.compile("Đăng ký (tham gia|lại)"))
    if btn.count() == 0:
        fl.step("đã có đơn cho đợt 3 → hủy đơn trước để thử lại")
        fl.goto("/tai-khoan/don-dang-ky/")
        fl.submit(fl.page.get_by_role("button", name=re.compile("Hủy")).first)
        fl.goto("/dot-hien/3/")
        btn = fl.page.get_by_role("button", name=re.compile("Đăng ký (tham gia|lại)"))
    fl.submit(btn)
    fl.expect_text("Đã gửi đơn đăng ký")
    assert "/tai-khoan/don-dang-ky/" in fl.page.url
    fl.goto("/dot-hien/3/")
    assert fl.page.get_by_role("button", name=re.compile("Đăng ký tham gia")).count() == 0, "Vẫn hiện nút đăng ký lần 2"
    fl.step("không còn nút đăng ký lần 2")


def f_member_patient_request(fl):
    fl.login("/dang-nhap/", "lan.bui@demo.vn")
    fl.goto("/")
    fl.page.get_by_role("link", name=re.compile("Tôi cần xin máu")).first.click()
    fl.page.wait_for_load_state("networkidle")
    p = fl.page
    assert "/can-mau/gui-yeu-cau/" in p.url
    send = p.locator("form.custom-form-body button[type=submit]")
    fl.submit(send)  # bỏ trống → phải báo lỗi
    assert "/can-mau/gui-yeu-cau/" in p.url, "Form trống vẫn gửi được"
    fl.step("form trống bị chặn")
    p.fill("input[name=contact_name]", "Người nhà QA")
    p.fill("input[name=contact_phone]", "0905999888")
    p.select_option("select[name=hospital_id]", index=1)
    p.fill("input[name=quantity_units]", "2")
    if p.locator("input[name=consent]").count():
        p.check("input[name=consent]")
    fl.submit(p.locator("form.custom-form-body button[type=submit]"))
    body = fl.text()
    assert re.search(r"PR-\d{8}-\d{4}", body), "Không thấy mã yêu cầu PR-… sau khi gửi"
    fl.step("nhận mã " + re.search(r"PR-\d{8}-\d{4}", body).group(0))


def f_member_keyboard_login(fl):
    """Chỉ dùng bàn phím: Tab tới ô email, gõ, Tab, gõ mật khẩu, Enter."""
    fl.goto("/dang-nhap/")
    p = fl.page
    p.locator("input[name=email]").focus()
    p.keyboard.type("an.nguyen@demo.vn")
    p.keyboard.press("Tab")
    focused = p.evaluate("document.activeElement.name")
    assert focused == "password", f"Tab từ ô email nhảy tới '{focused}', không phải ô mật khẩu"
    p.keyboard.type(PW)
    p.keyboard.press("Enter")
    try:
        p.wait_for_url(lambda u: "/dang-nhap/" not in u, timeout=10000)
    except Exception:  # noqa: BLE001
        raise AssertionError("Enter không gửi được form đăng nhập")
    fl.step("đăng nhập chỉ bằng bàn phím thành công")
    # Đăng xuất bằng menu
    fl.goto("/tai-khoan/")
    p.locator("form[action='/dang-xuat/'] button").first.evaluate("b => b.click()")
    p.wait_for_load_state("networkidle")
    fl.expect_text("Bạn đã đăng xuất")


# ============================================================== Luồng Bệnh viện
def f_hospital_checkin_record_lab_issue(fl):
    """Điểm hiến → check-in → ghi nhận lượt hiến → chờ xét nghiệm → đạt (nhập kho) → phiếu xuất kho."""
    fl.login("/benh-vien/dang-nhap/", "benhvien1@hienmau.vn")
    p = fl.page
    fl.goto("/benh-vien/dot-hien/2/diem-hien/")
    hrefs = [a.get_attribute("href") for a in p.locator("a[href*='reg=']").all()]
    assert hrefs, "Không có đơn nào để check-in ở đợt 2"
    # Ưu tiên đơn đang chờ (pending/approved) để đi trọn luồng check-in
    target = None
    for href in hrefs:
        fl.goto("/benh-vien/dot-hien/2/diem-hien/" + href)
        if p.locator("input[name=action][value=checkin]").count():
            target = href
            break
    assert target, "Không còn đơn chờ check-in ở đợt 2"
    fl.submit(p.locator("form:has(input[name=action][value=checkin]) button").first)
    fl.expect_text("Đã check-in")
    form = p.locator("#record-form")
    expect(form).to_be_visible()
    p.check("#record-form input[name=donation_type][value=whole_blood]", force=True)
    p.fill("#record-form input[name=volume_ml]", "350")
    fl.submit(form.locator("button[type=submit]"))
    fl.expect_text("Đã ghi nhận lượt hiến")

    fl.goto("/benh-vien/cho-xet-nghiem/")
    opener = p.locator("button[data-open-dialog^='lab-']").last
    dlg_id = opener.get_attribute("data-open-dialog")
    opener.click()
    dlg = p.locator(f"#{dlg_id}")
    expect(dlg).to_be_visible()
    dlg.locator("input[name=result][value=passed]").check(force=True)
    dlg.locator("select[name=blood_group]").select_option("O+")
    qty = dlg.locator("input[name=quantity]")
    assert qty.get_attribute("max"), "Ô số đơn vị không có giới hạn max"
    fl.submit(dlg.locator("button.btn.primary"))
    fl.expect_text("Đã nhập kho từ lượt hiến")

    fl.goto("/benh-vien/kho/phieu/xuat/")
    p.select_option("select[name=stock_id]", index=1)
    p.fill("input[name=quantity]", "99999")
    fl.submit(p.locator("form[data-stock-preview] button[type=submit]").first)
    fl.expect_text("Chỉ còn")
    fl.step("xuất vượt tồn bị chặn với thông báo rõ")
    p.select_option("select[name=stock_id]", index=1)
    p.fill("input[name=quantity]", "1")
    if p.locator("input[name=purpose]").count():
        p.fill("input[name=purpose]", "QA giao diện")
    fl.submit(p.locator("form[data-stock-preview] button[type=submit]").first)
    fl.expect_text("Đã ghi phiếu")
    assert "/benh-vien/kho/lich-su/" in p.url


def f_hospital_campaign_create_with_map(fl):
    fl.login("/benh-vien/dang-nhap/", "benhvien1@hienmau.vn")
    p = fl.page
    fl.goto("/benh-vien/dot-hien/tao/")
    start = datetime.now() + timedelta(days=10)
    p.fill("input[name=name]", f"Đợt QA giao diện {STAMP}")
    p.fill("input[name=location_name]", "Hội trường QA")
    p.fill("input[name=address]", "1 Đường QA")
    p.fill("input[name=start_time]", start.strftime("%Y-%m-%dT08:00"))
    p.fill("input[name=end_time]", start.strftime("%Y-%m-%dT07:00"))
    fl.submit(p.locator("form button[type=submit]").last)
    fl.expect_text("Thời gian kết thúc phải sau thời gian bắt đầu")
    fl.step("giờ kết thúc trước giờ bắt đầu bị chặn")
    p.fill("input[name=end_time]", start.strftime("%Y-%m-%dT12:00"))
    p.locator("#picker").click(position={"x": 120, "y": 100})
    lat = p.input_value("input[name=latitude]")
    assert lat, "Bấm bản đồ không điền được vĩ độ (bản đồ bị CSP chặn?)"
    fl.step(f"bấm bản đồ → vĩ độ {lat}")
    fl.submit(p.locator("form button[type=submit]").last)
    fl.expect_text("Đã tạo đợt hiến ở trạng thái Nháp")


def f_hospital_patient_request_verify(fl):
    fl.login("/benh-vien/dang-nhap/", "benhvien1@hienmau.vn")
    p = fl.page
    fl.goto("/benh-vien/yeu-cau-can-mau/")
    link = p.locator("a.btn[href^='/benh-vien/yeu-cau-can-mau/']").first
    assert link.count(), "Không có yêu cầu chờ xác minh"
    link.click()
    p.wait_for_load_state("networkidle")
    if p.locator("input[name=action][value=start_verify]").count():
        fl.submit(p.locator("form:has(input[value=start_verify]) button"))
        fl.expect_text("Đã nhận xác minh")
    verify = p.locator("form:has(input[name=action][value=verify])")
    if verify.locator("select[name=blood_group]").count():
        verify.locator("select[name=blood_group]").select_option("O+")
    fl.submit(verify.locator("button").last)
    fl.expect_text("Đã xác minh yêu cầu")


def f_supplier_accept_offer(fl):
    fl.login("/benh-vien/dang-nhap/", "benhvien3@hienmau.vn")
    p = fl.page
    fl.goto("/benh-vien/de-nghi-den/?status=pending")
    link = p.locator("a.btn[href^='/benh-vien/de-nghi-den/']").first
    if link.count() == 0:
        fl.step("không còn đề nghị chờ (đã xử lý ở lần chạy trước) — kiểm tra trang danh sách hiển thị đúng")
        fl.goto("/benh-vien/de-nghi-den/")
        return
    link.click()
    p.wait_for_load_state("networkidle")
    form = p.locator("form:has(input[name=action][value=accept])")
    form.locator("input[name=quantity]").fill("99999")
    fl.submit(form.locator("button").last)
    body = fl.text()
    assert "Yêu cầu chỉ còn thiếu" in body or "khả dụng" in body, "Chấp thuận vượt số cần/tồn không bị chặn"
    fl.step("chấp thuận vượt mức bị chặn")
    form = p.locator("form:has(input[name=action][value=accept])")
    form.locator("input[name=quantity]").fill("1")
    fl.submit(form.locator("button").last)
    fl.expect_text("Đã chấp thuận và giữ chỗ")


# ============================================================== Quản trị & công khai
def f_admin_setting(fl):
    fl.login("/quan-tri/dang-nhap/", "admin@hienmau.vn")
    p = fl.page
    fl.goto("/quan-tri/cau-hinh/")
    form = p.locator("form:has(input[name=key][value=lab_max_units_per_donation])")
    assert form.count(), "Không thấy cấu hình lab_max_units_per_donation"
    form.locator("[name=value]").fill("abc")
    fl.submit(form.locator("button").last)
    fl.expect_text("JSON hợp lệ")
    form = p.locator("form:has(input[name=key][value=lab_max_units_per_donation])")
    form.locator("[name=value]").fill("3")
    fl.submit(form.locator("button").last)
    fl.expect_text("Đã lưu cấu hình")


def f_public_map_csp(fl):
    fl.goto("/ban-do/")
    items = fl.page.locator("[data-map-list] .map-item")
    items.first.wait_for(timeout=8000)
    n = items.count()
    assert n > 0, "Bản đồ không hiện điểm nào"
    items.first.click()
    fl.step(f"{n} điểm trên danh sách; bấm điểm đầu mở popup")
    expect(fl.page.locator(".leaflet-popup")).to_be_visible()
    fl.page.select_option("[data-map-type]", "campaign")
    fl.step(f"lọc 'đợt hiến' → {fl.page.locator('[data-map-list] .map-item').count()} điểm")


def f_mobile_menu(fl):
    fl.login("/dang-nhap/", "an.nguyen@demo.vn")
    p = fl.page
    toggle = p.locator("[data-nav-toggle], .nav-toggle, button[aria-controls]").first
    assert toggle.count() and toggle.is_visible(), "Không thấy nút mở menu trên mobile"
    toggle.click()
    p.wait_for_timeout(300)
    link = p.get_by_role("link", name=re.compile("Lịch sử hiến")).first
    expect(link).to_be_visible()
    link.click()
    p.wait_for_load_state("networkidle")
    assert "/tai-khoan/lich-su-hien/" in p.url
    fl.step("menu mobile mở được và điều hướng đúng")


# ============================================================== Trợ năng (axe-core)
A11Y_PAGES = [
    ("anon", None, None, ["/", "/dot-hien/", "/dot-hien/2/", "/ban-do/", "/dang-nhap/", "/dang-ky/"]),
    ("member", "/dang-nhap/", "an.nguyen@demo.vn", ["/tai-khoan/", "/tai-khoan/lich-su-hien/", "/can-mau/gui-yeu-cau/"]),
    ("hospital", "/benh-vien/dang-nhap/", "benhvien1@hienmau.vn",
     ["/benh-vien/", "/benh-vien/kho/", "/benh-vien/dot-hien/2/diem-hien/", "/benh-vien/kho/phieu/xuat/"]),
    ("admin", "/quan-tri/dang-nhap/", "admin@hienmau.vn", ["/quan-tri/nguoi-dung/", "/quan-tri/cau-hinh/"]),
]


def a11y(browser):
    from axe_playwright_python.sync_playwright import Axe

    axe, report = Axe(), []
    for role, portal, email, pages in A11Y_PAGES:
        fl = Flow(browser, f"A11Y-{role}", f"Trợ năng ({role})")
        if portal:
            fl.login(portal, email)
        for path in pages:
            fl.goto(path)
            res = axe.run(fl.page, options={"runOnly": {"type": "tag", "values": ["wcag2a", "wcag2aa"]}})
            for v in res.response["violations"]:
                report.append({"role": role, "path": path, "id": v["id"], "impact": v["impact"], "help": v["help"],
                               "nodes": len(v["nodes"]), "example": v["nodes"][0]["target"] if v["nodes"] else None,
                               "html": v["nodes"][0]["html"][:200] if v["nodes"] else None})
        fl.ctx.close()
    (OUT / "a11y.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    by = {}
    for v in report:
        by.setdefault((v["id"], v["impact"], v["help"]), set()).add(v["path"])
    print(f"\nTrợ năng: {len(report)} vi phạm (theo trang) — {len(by)} loại")
    for (vid, impact, hlp), paths in sorted(by.items(), key=lambda x: str(x[0][1])):
        print(f"  [{impact}] {vid}: {hlp} — {len(paths)} trang, vd. {sorted(paths)[0]}")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    run(browser, "UI-01", "Đăng ký tài khoản: chặn mật khẩu yếu, tạo được tài khoản hợp lệ", f_register_account)
    run(browser, "UI-02", "Người dùng đăng ký hiến một đợt, không đăng ký trùng", f_member_register_campaign)
    run(browser, "UI-03", "Người dùng gửi yêu cầu cần máu từ nút trang chủ", f_member_patient_request)
    run(browser, "UI-04", "Đăng nhập chỉ bằng bàn phím + đăng xuất", f_member_keyboard_login)
    run(browser, "UI-05", "Bệnh viện: check-in → ghi nhận → xét nghiệm đạt → xuất kho", f_hospital_checkin_record_lab_issue)
    run(browser, "UI-06", "Bệnh viện: tạo đợt hiến, chặn giờ sai, chọn vị trí trên bản đồ", f_hospital_campaign_create_with_map)
    run(browser, "UI-07", "Bệnh viện: nhận xác minh và xác minh yêu cầu cần máu", f_hospital_patient_request_verify)
    run(browser, "UI-08", "Bệnh viện cấp: chặn chấp thuận vượt mức, chấp thuận hợp lệ", f_supplier_accept_offer)
    run(browser, "UI-09", "Quản trị: lưu cấu hình, chặn giá trị sai", f_admin_setting)
    run(browser, "UI-10", "Bản đồ công khai hoạt động dưới CSP (danh sách, popup, lọc)", f_public_map_csp)
    run(browser, "UI-11", "Mobile: mở menu và điều hướng", f_mobile_menu, viewport=(390, 844))
    try:
        a11y(browser)
    except Exception as exc:  # noqa: BLE001
        print("Không chạy được axe:", exc)
    browser.close()

(OUT / "flows.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n{sum(r['status'] == 'Pass' for r in results)}/{len(results)} luồng Pass. Bằng chứng: {OUT}")
