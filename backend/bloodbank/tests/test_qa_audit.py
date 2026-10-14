"""Test hồi quy cho các lỗi tìm được trong đợt QA audit (qa-audit/reports/03_BUG_REPORT.md, 04_SECURITY_REPORT.md).

Mỗi test khẳng định HÀNH VI ĐÚNG; trước khi sửa, các test này đã FAIL (bằng chứng: qa-audit/evidence/).
Chạy riêng nhóm này:  python manage.py test --tag qa_audit
"""
from datetime import timedelta

from django.test import TestCase, tag
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import AuditLog, Donation, Registration, Stock
from bloodbank.services import campaigns as cmp
from bloodbank.services import donations as don
from bloodbank.services import lab
from bloodbank.services.common import BusinessError

from . import factories as f


def recorded_donation(hospital, staff_user, campaign=None):
    """Lượt hiến toàn phần vừa được ghi nhận (chờ xét nghiệm) tại `hospital`."""
    camp = campaign or f.campaign(hospital, start_offset_h=-2)
    reg = f.registration(camp, f.user(blood_group="O+"), status="attended")
    return don.record_donation(staff_user.staffs.get(hospital=hospital), reg.pk,
                               {"donation_type": "whole_blood", "volume_ml": 350,
                                "donated_at": timezone.now() - timedelta(minutes=5)})


@tag("qa_audit")
class MalformedInputTests(TestCase):
    """QA-VAL-01: tham số sai kiểu phải trả 4xx/thông báo, không được gây lỗi 500."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.member = f.user()
        cls.admin = f.user(role="admin")
        cls.camp = f.campaign(cls.h)

    def setUp(self):
        self.client.raise_request_exception = False

    def check(self, who, method, url, data=None):
        self.client.force_login(who)
        r = self.client.post(url, data or {}) if method == "POST" else self.client.get(url, data or {})
        return r.status_code

    def test_no_500_on_malformed_ids(self):
        rbc = f.spec()
        cases = [
            (self.staff_user, "GET", reverse("bloodbank:checkin", args=[self.camp.pk]), {"reg": "abc"}),
            (self.staff_user, "GET", reverse("bloodbank:donor_lookup"), {"donor": "abc"}),
            (self.staff_user, "GET", reverse("bloodbank:stock_ledger"), {"spec": "abc"}),
            (self.staff_user, "GET", reverse("bloodbank:stock_ledger"), {"stock": "abc"}),
            (self.staff_user, "GET", reverse("bloodbank:stock_ledger"), {"from": "2026-13-45"}),
            (self.staff_user, "GET", reverse("bloodbank:source_search"), {"blood_group": "O+", "product": "abc"}),
            (self.staff_user, "GET", reverse("bloodbank:source_search"),
             {"blood_group": "O+", "product": rbc.product_id, "min_qty": "abc"}),
            (self.staff_user, "GET", reverse("bloodbank:source_search"), {"patient_request": "abc"}),
            (self.staff_user, "POST", reverse("bloodbank:stock_txn", args=["xuat"]),
             {"stock_id": "abc", "quantity": "1", "idempotency_key": "k-abc"}),
            (self.staff_user, "POST", reverse("bloodbank:support_request_create"),
             {"blood_group": "O+", "product_spec_id": rbc.pk, "quantity_needed": "1", "priority": "normal",
              "supplier": "abc"}),
            (self.member, "POST", reverse("bloodbank:notifications_read"), {"id": "abc"}),
            (self.admin, "GET", reverse("bloodbank:catalog"), {"product": "abc"}),
        ]
        from bloodbank.services import inventory as inv

        txn = inv.receive(self.staff_user.staffs.get(), rbc.pk, "O+", 3, "k-recv")
        cases.append((self.staff_user, "POST", reverse("bloodbank:stock_settings", args=[txn.stock_id]),
                      {"shareable_quantity": "1", "min_stock_level": "0", "version": "abc"}))
        failures = []
        for who, method, url, data in cases:
            with self.subTest(url=url, data=data):
                code = self.check(who, method, url, data)
                if code >= 500:
                    failures.append(f"{method} {url} {data} → {code}")
        self.assertEqual(failures, [], "Các request trả 500:\n" + "\n".join(failures))


@tag("qa_audit")
class InventoryIntegrityTests(TestCase):
    """QA-BL-01..03: tính nhất quán giữa lượt hiến và kho."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.staff = cls.staff_user.staffs.get()

    def pass_lab(self, d, qty=1, key="lab-1"):
        return lab.record_lab_result(self.staff, d.pk, "passed",
                                     {"blood_group": "O+", "product_spec_id": f.spec("WB", "350ML").pk, "quantity": qty},
                                     key)

    def stock(self):
        return Stock.objects.get(hospital=self.h, blood_group="O+", product_spec=f.spec("WB", "350ML"))

    def test_void_after_lab_passed_keeps_stock_consistent(self):
        """QA-BL-01: hủy hiệu lực lượt hiến đã nhập kho → phải trừ kho tương ứng hoặc chặn thao tác hủy."""
        from bloodbank.models import StockTxn

        d = recorded_donation(self.h, self.staff_user)
        self.pass_lab(d, qty=2)
        before = self.stock().quantity_on_hand
        don.void_donation(self.staff, d.pk, "Ghi nhầm người hiến", "not_donated")
        self.assertEqual(Donation.objects.get(pk=d.pk).status, "voided")
        self.assertEqual(self.stock().quantity_on_hand, before - 2,
                         f"Lượt hiến đã hủy hiệu lực nhưng {before} đơn vị nhập từ nó vẫn còn trong kho "
                         f"(không có phiếu điều chỉnh/hoàn kho).")
        adj = StockTxn.objects.get(stock=self.stock(), txn_type="adjustment")
        self.assertEqual((adj.quantity_change, adj.adjustment_reason), (-2, "data_entry_error"))
        self.assertIn(d.code, adj.reason_note)

    def test_void_blocked_when_units_already_issued(self):
        """Đơn vị nhập từ lượt hiến đã được xuất dùng → không tự trừ được, phải chặn hủy (kho không âm / không lệch)."""
        from bloodbank.services import inventory as inv

        d = recorded_donation(self.h, self.staff_user)
        self.pass_lab(d, key="lab-issued")
        inv.issue(self.staff, self.stock().pk, 1, "issue-1")
        with self.assertRaises(BusinessError) as ctx:
            don.void_donation(self.staff, d.pk, "Ghi nhầm", "not_donated")
        self.assertEqual(ctx.exception.code, "ERR-INV-INSUFFICIENT")
        self.assertEqual(Donation.objects.get(pk=d.pk).status, "confirmed")
        self.assertEqual(self.stock().quantity_on_hand, 0)

    def test_void_without_stock_in_still_works(self):
        d = recorded_donation(self.h, self.staff_user)
        don.void_donation(self.staff, d.pk, "Ghi nhầm", "not_donated")
        self.assertEqual(Donation.objects.get(pk=d.pk).status, "voided")

    def test_edit_donation_works(self):
        """BUG-01: sửa lượt hiến (UC-DON-03) không còn lỗi FOR UPDATE + outer join; HTTP trả về trang chi tiết."""
        d = recorded_donation(self.h, self.staff_user)
        don.edit_donation(self.staff, d.pk, {"donation_type": "whole_blood", "volume_ml": 400,
                                             "donated_at": d.donated_at, "note": "Sửa thể tích"}, "Cân lại túi")
        d.refresh_from_db()
        self.assertEqual(d.volume_ml, 400)
        self.client.force_login(self.staff_user)
        local = timezone.localtime(d.donated_at).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("bloodbank:donation_manage", args=[d.pk]),
                             {"action": "edit", "reason": "Cân lại", "donation_type": "whole_blood", "volume_ml": "420",
                              "donated_at": local}, follow=True)
        self.assertContains(r, "Đã cập nhật lượt hiến")
        d.refresh_from_db()
        self.assertEqual(d.volume_ml, 420)

    def test_lab_quantity_bounded(self):
        """QA-BL-02: một lượt hiến 350 ml không thể nhập kho 100.000 đơn vị."""
        d = recorded_donation(self.h, self.staff_user)
        with self.assertRaises(BusinessError, msg="Nhập kho 100000 đơn vị từ 1 lượt hiến được chấp nhận"):
            self.pass_lab(d, qty=100000, key="lab-big")
        with self.assertRaises(BusinessError):
            self.pass_lab(d, qty=4, key="lab-4")      # mặc định tối đa 3
        self.pass_lab(d, qty=3, key="lab-3")
        self.assertEqual(self.stock().quantity_on_hand, 3)

    def test_edit_donation_type_after_stock_in_blocked(self):
        """QA-BL-03: đã nhập kho theo toàn phần thì không được đổi lượt hiến sang thành phần."""
        d = recorded_donation(self.h, self.staff_user)
        self.pass_lab(d, key="lab-edit")
        plt = f.spec("PLT", "STANDARD").product
        with self.assertRaises(BusinessError, msg="Đổi loại hiến sau khi đã nhập kho vẫn được chấp nhận"):
            don.edit_donation(self.staff, d.pk, {"donation_type": "component", "component_product_id": plt.pk,
                                                 "component_quantity": "1", "component_unit": "unit",
                                                 "donated_at": d.donated_at}, "Sửa loại")


@tag("qa_audit")
class CampaignIntegrityTests(TestCase):
    """QA-BL-04..05: sửa/hủy đợt hiến không làm dữ liệu liên quan sai lệch."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.staff = cls.staff_user.staffs.get()

    def test_edit_time_cannot_exclude_existing_donations(self):
        """QA-BL-04: không được đổi giờ đợt để lượt hiến đã xác nhận nằm ngoài khung giờ đợt."""
        camp = f.campaign(self.h, start_offset_h=-3, duration_h=6)
        d = recorded_donation(self.h, self.staff_user, camp)
        data = {k: getattr(camp, k) for k in cmp.CAMPAIGN_FIELDS}
        data["start_time"] = d.donated_at + timedelta(minutes=30)
        data["end_time"] = d.donated_at + timedelta(hours=5)
        with self.assertRaises(BusinessError) as ctx:
            cmp.update_campaign(self.staff, camp, data)
        self.assertEqual(ctx.exception.code, "ERR-CMP-TIME-RANGE")
        # Khung giờ mới vẫn bao trọn lượt hiến → được sửa
        data["start_time"] = d.donated_at - timedelta(hours=1)
        data["end_time"] = d.donated_at + timedelta(hours=1)
        cmp.update_campaign(self.staff, camp, data)
        camp.refresh_from_db()
        self.assertTrue(camp.start_time <= d.donated_at <= camp.end_time)

    def test_cancel_campaign_closes_checked_in_registrations(self):
        """QA-BL-05: hủy đợt → đơn đã check-in (chưa hiến) không được treo ở trạng thái 'Đã check-in'."""
        camp = f.campaign(self.h, start_offset_h=-1)
        reg = f.registration(camp, f.user(), status="attended")
        cmp.transition_campaign(self.staff, camp, "cancel", "Thời tiết xấu")
        reg.refresh_from_db()
        self.assertNotEqual(reg.status, Registration.Status.ATTENDED,
                            "Đợt đã hủy nhưng đơn vẫn ở trạng thái 'attended'")


@tag("qa_audit")
class SecurityControlTests(TestCase):
    """QA-SEC-*: kiểm soát bảo mật ở tầng ứng dụng."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.member = f.user(email="nguoidung@test.vn", password="MatKhau!2026")

    def test_audit_ip_not_taken_from_spoofable_header(self):
        """QA-SEC-01: IP trong nhật ký phải là địa chỉ kết nối thật, không lấy theo header client tự gửi."""
        self.client.post(reverse("accounts:login"), {"email": "nguoidung@test.vn", "password": "MatKhau!2026"},
                         HTTP_X_FORWARDED_FOR="203.0.113.77", REMOTE_ADDR="10.0.0.5")
        log = AuditLog.objects.filter(action="login", entity_id=self.member.pk).latest("created_at")
        self.assertEqual(log.ip_address, "10.0.0.5", f"Nhật ký ghi IP giả mạo {log.ip_address}")

    def test_audit_ip_behind_trusted_proxy(self):
        """Sau 1 reverse proxy tin cậy: lấy địa chỉ do proxy ghi (phần tử cuối), bỏ phần client tự chèn phía trước."""
        from django.test import override_settings

        with override_settings(TRUSTED_PROXY_COUNT=1):
            self.client.post(reverse("accounts:login"), {"email": "nguoidung@test.vn", "password": "MatKhau!2026"},
                             HTTP_X_FORWARDED_FOR="203.0.113.77, 198.51.100.9", REMOTE_ADDR="10.0.0.1")
        log = AuditLog.objects.filter(action="login", entity_id=self.member.pk).latest("created_at")
        self.assertEqual(log.ip_address, "198.51.100.9")

    def test_next_redirect_rejects_browser_normalised_external_urls(self):
        """QA-SEC-02: tham số next không được dẫn ra ngoài khi trình duyệt chuẩn hóa ký tự tab/backslash."""
        self.client.force_login(self.member)
        bad = []
        for nxt in ["/\t/evil.example/", "/\\evil.example/"]:
            r = self.client.post(reverse("bloodbank:notifications_read"), {"next": nxt})
            if r.status_code == 302 and r["Location"] == nxt:
                bad.append(repr(nxt))
        self.client.force_login(self.staff_user)
        for nxt in ["/\t/evil.example/"]:
            r = self.client.post(reverse("bloodbank:lab_result", args=[999999]), {"next": nxt})
            if r.status_code == 302 and r["Location"] == nxt:
                bad.append(repr(nxt) + " (lab_result)")
        self.assertEqual(bad, [], "Location trả nguyên giá trị next: " + ", ".join(bad))

    def test_locked_account_not_distinguishable_before_password_check(self):
        """QA-SEC-03: khi mật khẩu SAI, tài khoản bị khóa và email không tồn tại phải nhận cùng thông báo."""
        locked = f.user(email="dakhoa@test.vn", password="MatKhau!2026", status="locked")
        a = self.client.post(reverse("accounts:login"), {"email": locked.email, "password": "Sai!12345"})
        b = self.client.post(reverse("accounts:login"), {"email": "khongtontai@test.vn", "password": "Sai!12345"})
        self.assertEqual(a.context["error"], b.context["error"],
                         f"Bị khóa: '{a.context['error']}' ≠ không tồn tại: '{b.context['error']}'")

    def test_password_reset_requests_rate_limited(self):
        """QA-SEC-04: gửi liên tục yêu cầu quên mật khẩu cho 1 email phải bị giới hạn tần suất."""
        from django.core import mail

        pages = [self.client.post(reverse("accounts:forgot_password"), {"email": "nguoidung@test.vn"}) for _ in range(8)]
        self.assertLessEqual(len(mail.outbox), 3, f"8 yêu cầu → {len(mail.outbox)} email đặt lại được gửi")
        # Vượt hạn mức vẫn hiện cùng một trang "đã gửi" (không lộ thông tin)
        self.assertEqual({r.status_code for r in pages}, {200})
        self.assertEqual(pages[0].context["sent"], pages[-1].context["sent"])

    def test_resend_verification_rate_limited(self):
        from django.core import mail

        self.client.force_login(self.member)
        for _ in range(6):
            r = self.client.post(reverse("accounts:resend_verification"), follow=True)
        self.assertLessEqual(len(mail.outbox), 3)
        self.assertContains(r, "yêu cầu gửi lại nhiều lần")

    def test_locked_account_with_correct_password_is_told_locked(self):
        """Đúng mật khẩu thì vẫn báo rõ 'bị khóa' để chủ tài khoản biết liên hệ quản trị."""
        f.user(email="khoa2@test.vn", password="MatKhau!2026", status="locked")
        r = self.client.post(reverse("accounts:login"), {"email": "khoa2@test.vn", "password": "MatKhau!2026"})
        self.assertContains(r, "đang bị khóa")


@tag("qa_audit")
class CrossHospitalIsolationTests(TestCase):
    """QA-AZ-*: nhân viên bệnh viện B không xem/sửa được dữ liệu bệnh viện A (đối chứng — kỳ vọng PASS)."""

    @classmethod
    def setUpTestData(cls):
        cls.a, cls.b = f.hospital(), f.hospital()
        cls.staff_a, cls.staff_b = f.staff(cls.a), f.staff(cls.b)
        cls.donation = recorded_donation(cls.a, cls.staff_a)
        cls.camp = cls.donation.registration.campaign

    def test_other_hospital_gets_404_and_data_unchanged(self):
        self.client.force_login(self.staff_b)
        d = self.donation
        gets = [reverse("bloodbank:hospital_donation_detail", args=[d.pk]),
                reverse("bloodbank:hospital_campaign_detail", args=[self.camp.pk]),
                reverse("bloodbank:checkin", args=[self.camp.pk]),
                reverse("bloodbank:hospital_campaign_edit", args=[self.camp.pk])]
        for url in gets:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        posts = [(reverse("bloodbank:donation_manage", args=[d.pk]), {"action": "void", "reason": "x",
                                                                      "target_status": "not_donated"}),
                 (reverse("bloodbank:lab_result", args=[d.pk]), {"result": "failed", "lab_note": "x"}),
                 (reverse("bloodbank:hospital_campaign_action", args=[self.camp.pk]), {"action": "close"})]
        for url, data in posts:
            with self.subTest(url=url):
                self.assertIn(self.client.post(url, data).status_code, (302, 404))
        d.refresh_from_db()
        self.camp.refresh_from_db()
        self.assertEqual((d.status, d.lab_status, self.camp.status), ("confirmed", "pending", "open"))
