"""Email: soạn thư (HTML + nút tới đúng trang), chỉ gửi địa chỉ đã xác thực, hủy nhận lời kêu gọi, nhắc lịch, đổi mật khẩu."""
import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import services as account_services
from bloodbank.models import Notification
from bloodbank.services import campaigns, common, mailer, outbox

from . import factories as f


@override_settings(SITE_URL="https://gothong.online")
class EmailTests(TestCase):
    def alert(self, users, type_="test_alert", **kw):
        with self.captureOnCommitCallbacks(execute=True):
            common.alert(users, type_, "Tiêu đề", "Nội dung", **kw)

    def test_html_email_links_to_site(self):
        h = f.hospital()
        camp = f.campaign(h)
        donor = f.user()
        self.alert([donor], "campaign_cancelled", entity=camp)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Tiêu đề")                              # không còn "[Khẩn]" cho mọi email
        self.assertNotIn("cổng bệnh viện", msg.body)
        html = msg.alternatives[0][0]
        self.assertIn(f'href="https://gothong.online{reverse("bloodbank:campaign_detail", args=[camp.pk])}"', html)
        self.assertNotIn("List-Unsubscribe", msg.extra_headers)               # email nghiệp vụ: không có hủy nhận

    def test_urgent_type_gets_prefix_once(self):
        staff = f.user(role="hospital")
        self.alert([staff], "patient_request_new")
        self.assertEqual(mail.outbox[0].subject, "[Khẩn] Tiêu đề")

    def test_unverified_member_gets_in_app_only(self):
        user = f.user(email_verified_at=None)
        self.alert([user])
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(user=user, channel="in_app", type="test_alert").exists())

    def test_staff_account_without_verification_still_gets_email(self):
        staff = f.user(role="hospital", email_verified_at=None)              # tài khoản do hệ thống cấp
        self.alert([staff], "patient_request_new")
        self.assertEqual(mail.outbox[0].to, [staff.email])

    def test_opt_out_skips_callout_but_not_business_email(self):
        user = f.user(email_reminders=False)
        self.alert([user], "donor_callout")
        self.assertEqual(len(mail.outbox), 0)
        self.alert([user], "campaign_cancelled")
        self.assertEqual(len(mail.outbox), 1)

    def test_callout_email_has_working_unsubscribe(self):
        user = f.user()
        self.alert([user], "donor_callout")
        msg = mail.outbox[0]
        url = msg.extra_headers["List-Unsubscribe"].strip("<>")
        self.assertTrue(url.startswith("https://gothong.online/"))
        path = url.removeprefix("https://gothong.online")
        self.client.get(path)
        user.refresh_from_db()
        self.assertTrue(user.email_reminders)                                 # mở trang (máy quét link) chưa hủy
        self.client.post(path)                                                # một lần bấm, không cần CSRF
        user.refresh_from_db()
        self.assertFalse(user.email_reminders)

    def test_tampered_unsubscribe_link_changes_nothing(self):
        user = f.user()
        token = mailer.unsubscribe_token(user)
        r = self.client.post(reverse("accounts:unsubscribe", args=[token[:-2] + "xx"]))
        self.assertEqual(r.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.email_reminders)

    def test_campaign_reminder_once_within_24h(self):
        h = f.hospital()
        soon, later = f.campaign(h, start_offset_h=20), f.campaign(h, start_offset_h=30)
        donor = f.user()
        f.registration(soon, donor, status="approved")
        f.registration(later, donor, status="approved")
        f.registration(soon, f.user(), status="cancelled")
        self.assertEqual(campaigns.remind_upcoming(), 1)
        self.assertEqual(campaigns.remind_upcoming(), 0)                       # đã nhắc → không nhắc lại
        self.assertEqual(len(mail.outbox), 0)                                 # gửi dần ở lượt chạy sau
        self.assertEqual(outbox.sweep(timezone.now() + timedelta(minutes=5)), 1)
        self.assertIn("Nhắc lịch hiến máu", mail.outbox[0].subject)

    def test_password_change_sends_security_email(self):
        user = f.user()
        with self.captureOnCommitCallbacks(execute=True):
            account_services.change_password(user, "MatKhauMoi!2026")
        self.assertEqual(mail.outbox[0].to, [user.email])
        self.assertIn("vừa được thay đổi", mail.outbox[0].subject)
        self.assertIn(reverse("accounts:forgot_password"), mail.outbox[0].body)        # email: lối đặt lại nếu không phải mình
        self.client.force_login(user)
        r = self.client.get(reverse("bloodbank:notifications"))
        self.assertNotContains(r, reverse("accounts:forgot_password"))                 # trong ứng dụng: không dẫn đi đâu


class VerifyEmailTests(TestCase):
    def register(self):
        from accounts.models import User

        account_services.register({"email": "moi@test.vn", "password": "MatKhau2026", "full_name": "Người Mới"})
        link = re.search(r"/xac-thuc-email/[^/\s]+/", mail.outbox[-1].body).group(0)
        return User.objects.get(email="moi@test.vn"), link

    def test_second_click_or_link_scanner_still_shows_success(self):
        user, link = self.register()
        self.client.get(link)                                                 # Gmail quét trước / lần bấm đầu
        r = self.client.get(link, follow=True)                                # người dùng bấm (lần 2)
        self.assertContains(r, "đã được xác thực")
        self.assertNotContains(r, "không hợp lệ")
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)

    def test_changing_password_keeps_verification_link_working(self):
        user, link = self.register()
        account_services.change_password(user, "MatKhauKhac2026")
        self.client.get(link)
        user.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)

    def test_resend_when_already_verified_sends_nothing(self):
        user = f.user()
        self.client.force_login(user)
        self.client.post(reverse("accounts:resend_verification"))
        self.assertEqual(len(mail.outbox), 0)
