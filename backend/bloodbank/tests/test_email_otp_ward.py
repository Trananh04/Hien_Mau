"""Đăng ký xong phải nhập mã OTP gửi qua email; ô Phường/Xã phụ thuộc Tỉnh/thành (đăng ký + hồ sơ)."""
import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import AuthToken, User
from accounts.provinces import PROVINCES, WARDS, wards_of

from . import factories as f

PW = "MatKhau!2026"


def code_in(msg):
    return re.search(r"Mã xác thực của bạn: (\d{6})", msg.body).group(1)


class EmailOtpTests(TestCase):
    def register(self, **extra):
        return self.client.post(reverse("accounts:register"), {
            "full_name": "Nguyễn Thanh", "email": "thanh@test.vn", "password": PW, "password2": PW,
            "accept_terms": "on", "next": reverse("bloodbank:my_history"), **extra,
        })

    def test_register_goes_straight_to_otp_and_code_verifies(self):
        r = self.register()
        self.assertRedirects(r, reverse("accounts:verify_otp") + "?next=%2Ftai-khoan%2Flich-su-hien%2F",
                             fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        code = code_in(msg)
        self.assertIn(code, msg.subject)
        self.assertRegex(msg.body, r"/xac-thuc-email/[^/\s]+/")                  # liên kết vẫn có (mở từ máy khác)
        page = self.client.get(r["Location"])
        self.assertContains(page, "thanh@test.vn")
        self.assertContains(page, 'autocomplete="one-time-code"')

        r = self.client.post(reverse("accounts:verify_otp"), {"code": code, "next": "/tai-khoan/lich-su-hien/"})
        self.assertRedirects(r, "/tai-khoan/lich-su-hien/", fetch_redirect_response=False)
        user = User.objects.get(email="thanh@test.vn")
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(self.client.get(reverse("bloodbank:profile")).status_code, 200)
        # Đã xác thực → liên kết trong email không còn hiệu lực nhưng bấm vẫn báo thành công
        link = re.search(r"/xac-thuc-email/[^/\s]+/", msg.body).group(0)
        self.assertContains(self.client.get(link, follow=True), "đã được xác thực")

    def test_unverified_member_is_held_on_otp_page(self):
        self.register()
        for url in (reverse("bloodbank:profile"), reverse("bloodbank:campaigns"), "/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r["Location"].startswith(reverse("accounts:verify_otp")), url)
        self.assertEqual(self.client.get(reverse("bloodbank:api_my_history")).status_code, 403)
        # Vẫn đăng xuất được
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_staff_accounts_are_not_held(self):
        hosp = f.hospital()
        staff = f.staff(hosp, f.user(role="hospital", email_verified_at=None))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("bloodbank:hospital_dashboard")).status_code, 200)

    def test_wrong_code_counts_down_then_code_is_revoked(self):
        self.register()
        code = code_in(mail.outbox[0])
        wrong = "000000" if code != "000000" else "111111"
        r = self.client.post(reverse("accounts:verify_otp"), {"code": wrong})
        self.assertContains(r, "Bạn còn 4 lần thử")
        for _ in range(4):
            r = self.client.post(reverse("accounts:verify_otp"), {"code": wrong})
        self.assertContains(r, "nhập sai quá nhiều lần")
        r = self.client.post(reverse("accounts:verify_otp"), {"code": code})       # mã đúng cũng hết tác dụng
        self.assertContains(r, "đã hết hạn")
        self.assertIsNone(User.objects.get(email="thanh@test.vn").email_verified_at)

    def test_resend_replaces_code(self):
        self.register()
        old = code_in(mail.outbox[0])
        r = self.client.post(reverse("accounts:resend_verification"), {"next": "/dot-hien/"})
        self.assertRedirects(r, reverse("accounts:verify_otp") + "?next=%2Fdot-hien%2F", fetch_redirect_response=False)
        new = code_in(mail.outbox[1])
        if old != new:
            r = self.client.post(reverse("accounts:verify_otp"), {"code": old})       # mã cũ đã bị thay
            self.assertContains(r, "Mã xác thực không đúng")
        self.client.post(reverse("accounts:verify_otp"), {"code": new})
        self.assertIsNotNone(User.objects.get(email="thanh@test.vn").email_verified_at)

    def test_codes_are_stored_hashed_and_unique_per_issue(self):
        user = f.user(email_verified_at=None)
        AuthToken.issue_code(user, AuthToken.Purpose.EMAIL_OTP, ttl=timedelta(minutes=5))
        token = AuthToken.current_code(user, AuthToken.Purpose.EMAIL_OTP)
        self.assertEqual(len(token.token_hash), 64)
        self.assertFalse(token.matches_code("12345"))


class WardTests(TestCase):
    def test_dataset_covers_all_34_provinces(self):
        self.assertEqual(set(WARDS), set(PROVINCES))
        self.assertEqual(sum(map(len, WARDS.values())), 3321)
        self.assertIn("Phường Ba Đình", wards_of("Hà Nội"))
        self.assertEqual(wards_of(""), [])

    def test_wards_endpoint_returns_options_for_province(self):
        r = self.client.get(reverse("accounts:wards"), {"province": "Lai Châu"})
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertEqual(html.count("<option"), len(wards_of("Lai Châu")) + 1)
        self.assertIn('<option value="">-- Chọn phường / xã --</option>', html)
        r = self.client.get(reverse("accounts:wards"))
        self.assertContains(r, "Chọn tỉnh trước")

    def test_register_saves_ward(self):
        ward = wards_of("Lai Châu")[0]
        self.client.post(reverse("accounts:register"), {
            "full_name": "Lò Văn A", "email": "a@test.vn", "password": PW, "password2": PW, "accept_terms": "on",
            "province": "Lai Châu", "ward": ward,
        })
        self.assertEqual(User.objects.get(email="a@test.vn").ward, ward)

    def test_profile_shows_ward_select_and_rejects_ward_of_other_province(self):
        user = f.user(province="Lai Châu")
        self.client.force_login(user)
        r = self.client.get(reverse("bloodbank:profile"))
        self.assertContains(r, 'hx-get="/dia-chi/phuong-xa/"')
        self.assertContains(r, wards_of("Lai Châu")[0])
        data = {"form": "profile", "full_name": user.full_name, "province": "Lai Châu",
                "ward": wards_of("Hà Nội")[0], "email_reminders": "on"}
        r = self.client.post(reverse("bloodbank:profile"), data)
        self.assertContains(r, "Phường/Xã không thuộc tỉnh/thành đã chọn.")
        data["ward"] = wards_of("Lai Châu")[1]
        self.client.post(reverse("bloodbank:profile"), data)
        user.refresh_from_db()
        self.assertEqual(user.ward, wards_of("Lai Châu")[1])


class HospitalWardTests(TestCase):
    def test_signup_form_has_province_then_ward_then_address_and_no_district(self):
        html = self.client.get(reverse("accounts:hospital_register")).content.decode()
        self.assertNotIn("Quận/huyện", html)
        self.assertLess(html.index('id="id_province"'), html.index('id="id_ward"'))
        self.assertLess(html.index('id="id_ward"'), html.index('id="id_address"'))

    def test_boosted_tab_to_hospital_signup_loads_full_page_for_map(self):
        r = self.client.get(reverse("accounts:hospital_register"), HTTP_HX_REQUEST="true", HTTP_HX_BOOSTED="true")
        self.assertEqual(r.headers.get("HX-Redirect"), reverse("accounts:hospital_register"))

    def test_hospital_info_keeps_legacy_ward(self):
        h = f.hospital(province="Hà Nội", ward="Phường Nguyễn Du")
        manager = f.staff(h)
        self.client.force_login(manager)
        r = self.client.get(reverse("bloodbank:hospital_info"))
        self.assertContains(r, "Phường Nguyễn Du (tên cũ)")


class ImportHospitalsTests(TestCase):
    def run_import(self, rows):
        import io
        import json
        import tempfile

        from django.core.management import call_command

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
        out = io.StringIO()
        call_command("import_hospitals", fh.name, "--khong-tra-toa-do", stdout=out)
        return out.getvalue()

    ROW = {"ma_co_so": "01010", "ten_benh_vien": "Bệnh viện Thử", "dien_thoai": "02438263616", "email": "bv@test.vn",
           "dia_chi": "Số 29 Phố Nguyễn Bỉnh Khiêm", "tinh_thanh": "Thành phố Hà Nội", "phuong_xa": "Phường Nguyễn Du",
           "nguoi_quan_ly": "Lý Thị Nam", "email_dang_nhap": "Admin.Thu@test.vn", "sdt_quan_ly": "0922334455",
           "mat_khau": "ThuNghiem@2026"}

    def test_creates_active_hospital_with_manager_and_maps_old_ward(self):
        from bloodbank.models import Hospital, Staff

        self.run_import([self.ROW])
        h = Hospital.objects.get(code="01010")
        self.assertEqual((h.province, h.ward, h.status), ("Hà Nội", "Phường Hai Bà Trưng", "active"))
        staff = Staff.objects.get(hospital=h)
        self.assertEqual(staff.staff_role, "manager")
        self.assertEqual(staff.user.email, "admin.thu@test.vn")
        self.assertTrue(staff.user.check_password("ThuNghiem@2026"))
        r = self.client.post(reverse("accounts:hospital_login"), {"email": "admin.thu@test.vn",
                                                                  "password": "ThuNghiem@2026"})
        self.assertRedirects(r, reverse("bloodbank:hospital_dashboard"), fetch_redirect_response=False)
        self.assertIn("bỏ qua 01010", self.run_import([self.ROW]))                    # chạy lại: không trùng
        self.assertEqual(Hospital.objects.filter(code="01010").count(), 1)

    def test_unknown_ward_aborts_whole_file(self):
        from django.core.management.base import CommandError

        from bloodbank.models import Hospital

        bad = {**self.ROW, "ma_co_so": "01099", "phuong_xa": "Phường Không Có"}
        with self.assertRaisesMessage(CommandError, "Phường Không Có"):
            self.run_import([self.ROW, bad])
        self.assertFalse(Hospital.objects.filter(code="01010").exists())
