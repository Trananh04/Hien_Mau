"""Bước 3–4: trang chủ, xác thực, đợt hiến công khai, khu vực cá nhân, chatbot, bản đồ."""
import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuthToken, User
from bloodbank.models import AuditLog, Donation, Notification, PatientRequest, Registration

from . import factories as f

PW = "MatKhau!2026"


class HomeAndAuthTests(TestCase):
    def test_home_renders_same_brand_fonts_and_hero(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        for needle in ["GIỌT HỒNG", "Be+Vietnam+Pro", "Dancing+Script", "btn-heart-theme",
                       "btn-cross-theme", "Tôi cần xin máu", "TIN TỨC HOẠT ĐỘNG HIẾN MÁU", "lucide.min.js",
                       "footer-section"]:
            self.assertIn(needle, html)

    def test_register_login_logout(self):
        r = self.client.post(reverse("accounts:register"), {
            "full_name": "Nguyễn Văn An", "email": "An@Test.VN", "phone": "0905 123 456", "password": PW,
            "password2": PW, "accept_terms": "on", "blood_group": "O+",
        })
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email="an@test.vn")
        self.assertEqual(user.phone, "+84905123456")
        self.assertIsNotNone(user.terms_accepted_at)
        self.assertTrue(user.password.startswith("argon2"))
        token = AuthToken.objects.get(user=user, purpose="email_verify")
        self.assertEqual(len(token.token_hash), 64)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"/xac-thuc-email/[^/\s]+/", mail.outbox[0].body).group(0)
        self.assertNotIn(token.token_hash, link)  # chỉ lưu SHA-256
        self.client.get(link)
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(reverse("bloodbank:profile")).status_code, 302)
        r = self.client.post(reverse("accounts:login"), {"email": "an@test.vn", "password": PW})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(reverse("bloodbank:profile")).status_code, 200)

    def test_register_validation(self):
        f.user(email="x@test.vn", phone="0901111111")
        r = self.client.post(reverse("accounts:register"), {
            "full_name": "A", "email": "x@test.vn", "phone": "0901111111", "password": "123", "password2": "456",
        })
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("ERR-AUTH-EMAIL-TAKEN", html)
        self.assertIn("ERR-AUTH-PHONE-TAKEN", html)
        self.assertIn("Bạn cần đồng ý điều khoản", html)

    def test_login_lockout_after_failures(self):
        u = f.user(email="lock@test.vn")
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"email": "lock@test.vn", "password": "sai"})
        r = self.client.post(reverse("accounts:login"), {"email": "lock@test.vn", "password": PW})
        self.assertContains(r, "sai quá nhiều lần")
        self.assertEqual(AuditLog.objects.filter(entity_id=u.id, action="login_failed").count(), 5)

    def test_locked_account_cannot_login_and_loses_session(self):
        u = f.user(email="l2@test.vn")
        self.client.force_login(u)
        User.objects.filter(pk=u.pk).update(status="locked")
        r = self.client.get(reverse("bloodbank:profile"))
        self.assertEqual(r.status_code, 302)  # mất quyền ở request kế tiếp (BR-23)
        r = self.client.post(reverse("accounts:login"), {"email": "l2@test.vn", "password": PW})
        self.assertContains(r, "đang bị khóa")

    def test_password_reset(self):
        f.user(email="reset@test.vn")
        r = self.client.post(reverse("accounts:forgot_password"), {"email": "reset@test.vn"})
        self.assertContains(r, "Nếu email này đã đăng ký")
        link = re.search(r"/dat-lai-mat-khau/[^/\s]+/", mail.outbox[-1].body).group(0)
        new = "MatKhauMoi!2026"
        r = self.client.post(link, {"password": new, "password2": new})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.get(email="reset@test.vn").check_password(new))
        self.assertContains(self.client.get(link), "không hợp lệ")  # token dùng một lần
        r = self.client.post(reverse("accounts:forgot_password"), {"email": "khongco@test.vn"})
        self.assertContains(r, "Nếu email này đã đăng ký")  # không lộ email tồn tại

    def test_open_redirect_blocked(self):
        f.user(email="r@test.vn")
        r = self.client.post(reverse("accounts:login") + "?next=https://evil.example",
                             {"email": "r@test.vn", "password": PW, "next": "https://evil.example"})
        self.assertNotIn("evil", r["Location"])

    def test_error_pages_styled(self):
        r = self.client.get("/khong-ton-tai/")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Không tìm thấy trang", r.content.decode())


class CampaignRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital(latitude=16.06, longitude=108.21)
        cls.open = f.campaign(cls.h, start_offset_h=24, name="Đợt mở")
        cls.draft = f.campaign(cls.h, status="draft", start_offset_h=24, name="Đợt nháp ẩn")
        cls.closed = f.campaign(cls.h, status="closed", start_offset_h=24, name="Đợt ngừng")
        cls.donor = f.user(full_name="Trần Thị Bình")

    def test_public_list_hides_draft(self):
        html = self.client.get(reverse("bloodbank:campaigns")).content.decode()
        self.assertIn("Đợt mở", html)
        self.assertNotIn("Đợt nháp ẩn", html)
        self.assertEqual(self.client.get(reverse("bloodbank:campaign_detail", args=[self.draft.pk])).status_code, 404)

    def test_register_cancel_reregister_reuses_row(self):
        url = reverse("bloodbank:campaign_detail", args=[self.open.pk])
        self.assertEqual(self.client.post(url, {}).status_code, 302)  # chưa đăng nhập → login
        self.client.force_login(self.donor)
        self.client.post(url, {"donation_type": "whole_blood", "note": "Sau 9h"})
        reg = Registration.objects.get(campaign=self.open, donor=self.donor)
        self.assertEqual(reg.status, "pending")
        r = self.client.post(url, {}, follow=True)
        self.assertContains(r, "Bạn đã có đơn đăng ký")  # ERR-REG-DUPLICATE (không hiện nút)
        self.client.post(reverse("bloodbank:cancel_registration", args=[reg.pk]))
        reg.refresh_from_db()
        self.assertEqual(reg.status, "cancelled")
        self.client.post(reverse("bloodbank:reregister", args=[reg.pk]))
        self.assertEqual(Registration.objects.filter(campaign=self.open, donor=self.donor).count(), 1)
        reg.refresh_from_db()
        self.assertEqual(reg.status, "pending")

    def test_cannot_register_closed_campaign(self):
        self.client.force_login(self.donor)
        r = self.client.post(reverse("bloodbank:campaign_detail", args=[self.closed.pk]), {}, follow=True)
        self.assertContains(r, "ngừng nhận đăng ký")
        self.assertFalse(Registration.objects.filter(campaign=self.closed).exists())

    def test_cannot_cancel_other_users_registration(self):
        reg = f.registration(self.open, f.user())
        self.client.force_login(self.donor)
        self.assertEqual(self.client.post(reverse("bloodbank:cancel_registration", args=[reg.pk])).status_code, 404)

    def test_map_data_public_only(self):
        data = self.client.get(reverse("bloodbank:map_data")).json()
        self.assertEqual(len(data["hospitals"]), 1)
        names = [c["name"] for c in data["campaigns"]]
        self.assertIn("Đợt mở", names)
        self.assertNotIn("Đợt nháp ẩn", names)


class HistoryAndPatientRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff = f.staff(cls.h)
        cls.donor = f.user()
        cls.other = f.user()
        camp = f.campaign(cls.h, start_offset_h=-3)
        reg = f.registration(camp, cls.donor, status="donated")
        now = timezone.now()
        cls.d1 = Donation.objects.create(donor=cls.donor, registration=reg, hospital=cls.h, volume_ml=350,
                                         donated_at=now - timedelta(hours=1), confirmed_by=cls.staff)
        reg2 = f.registration(f.campaign(cls.h, start_offset_h=-3), cls.donor, status="not_donated")
        Donation.objects.create(donor=cls.donor, registration=reg2, hospital=cls.h, volume_ml=250,
                                donated_at=now - timedelta(hours=1), confirmed_by=cls.staff, status="voided",
                                void_reason="Ghi nhầm", voided_at=now, voided_by=cls.staff)

    def test_history_counts_only_confirmed(self):
        self.client.force_login(self.donor)
        r = self.client.get(reverse("bloodbank:my_history"))
        self.assertEqual(r.context["summary"]["count"], 1)
        self.assertEqual(r.context["summary"]["whole_ml"], 350)
        self.assertEqual(len(r.context["page"].object_list), 1)
        r = self.client.get(reverse("bloodbank:my_history") + "?voided=1")
        self.assertEqual(len(r.context["page"].object_list), 2)

    def test_other_users_donation_is_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("bloodbank:my_donation_detail", args=[self.d1.pk])).status_code, 404)
        r = self.client.get(reverse("bloodbank:my_history"))
        self.assertContains(r, "Bạn chưa có lượt hiến được xác nhận")

    def test_patient_request_flow(self):
        url = reverse("bloodbank:patient_request_new")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.donor)
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {"contact_name": "A", "contact_phone": "0905000111", "hospital_id": self.h.pk,
                                   "quantity_units": 2})
        self.assertContains(r, "Bạn cần đồng ý")
        r = self.client.post(url, {"contact_name": "A", "contact_phone": "0905000111", "hospital_id": self.h.pk,
                                   "quantity_units": 2, "blood_group": "O-", "consent": "on", "patient_name": "Lê C"})
        prq = PatientRequest.objects.get(requester=self.donor)
        self.assertRedirects(r, reverse("bloodbank:my_patient_request_detail", args=[prq.pk]))
        self.assertRegex(prq.request_code, r"^PR-\d{8}-0001$")
        self.assertContains(self.client.get(r["Location"]), f"Đã tiếp nhận yêu cầu {prq.request_code}")
        self.assertTrue(Notification.objects.filter(user=self.staff, type="patient_request_new").exists())
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(r["Location"]).status_code, 404)
        self.client.force_login(self.donor)
        self.client.post(reverse("bloodbank:cancel_patient_request", args=[prq.pk]))
        prq.refresh_from_db()
        self.assertEqual(prq.status, "cancelled")

    def test_notifications_mark_read(self):
        Notification.objects.create(user=self.donor, type="x", title="Thông báo thử")
        self.client.force_login(self.donor)
        self.assertContains(self.client.get(reverse("bloodbank:notifications")), "Thông báo thử")
        self.client.post(reverse("bloodbank:notifications_read"))
        self.assertFalse(Notification.objects.filter(user=self.donor, read_at__isnull=True).exists())

    def test_profile_update(self):
        self.client.force_login(self.donor)
        r = self.client.post(reverse("bloodbank:profile"), {"form": "profile", "full_name": "Tên Mới", "phone": "0912345678",
                                                            "blood_group": "B+"})
        self.assertEqual(r.status_code, 302)
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.full_name, "Tên Mới")
        self.assertTrue(AuditLog.objects.filter(entity_type="users", entity_id=self.donor.pk, action="update").exists())


class ChatbotTests(TestCase):
    def test_answers_from_approved_content(self):
        r = self.client.post(reverse("bloodbank:chatbot"), {"q": "Quy trình hiến máu gồm mấy bước?"}).json()
        self.assertIn("4 bước", r["answer"])
        self.assertTrue(r["source"])

    def test_refuses_clinical_conclusion(self):
        r = self.client.post(reverse("bloodbank:chatbot"), {"q": "Tôi bị tiểu đường có được hiến không?"}).json()
        self.assertIn("không thể kết luận", r["answer"])
        self.assertIn("bác sĩ", r["answer"].lower())

    def test_hospital_word_is_not_clinical(self):
        r = self.client.post(reverse("bloodbank:chatbot"), {"q": "Bệnh viện nào gần tôi trên bản đồ?"}).json()
        self.assertIn("Bản đồ", r["answer"])
