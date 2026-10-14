"""Tối ưu luồng: (a) xét nghiệm → nhập kho, (b) tác vụ định kỳ, (c) nhắc yêu cầu khẩn,
(d) gợi ý nguồn liên viện, (e) cảnh báo khoảng cách hiến, (f) hành động từ dòng thiếu hụt."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import Donation, Stock, StockTxn
from bloodbank.services import donations as don
from bloodbank.services import lab
from bloodbank.services.common import BusinessError

from . import factories as f


def local(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


class LabQueueTests(TestCase):
    """(a) Ghi nhận lượt hiến → Chờ xét nghiệm → Đạt thì nhập kho (gắn với lượt hiến) / Không đạt thì không."""

    @classmethod
    def setUpTestData(cls):
        cls.h, cls.other_h = f.hospital(), f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.staff = cls.staff_user.staffs.get()
        cls.other_staff = f.staff(cls.other_h).staffs.get()
        cls.donor = f.user(blood_group="A+")  # nhóm tự khai, KHÔNG được dùng để nhập kho

    def donation(self, volume=350):
        c = f.campaign(self.h, start_offset_h=-2)
        reg = f.registration(c, self.donor, status="attended")
        return don.record_donation(self.staff, reg.pk, {"donation_type": "whole_blood", "donated_at": timezone.now(),
                                                        "volume_ml": volume})

    def test_recorded_donation_waits_for_lab_and_not_in_stock(self):
        d = self.donation()
        self.assertEqual(d.lab_status, "pending")
        self.assertFalse(Stock.objects.filter(hospital=self.h).exists())
        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:lab_queue"))
        self.assertContains(r, d.code)
        self.assertEqual(lab.default_spec(d).code, "350ML")  # túi đúng thể tích

    def test_passed_lab_receives_into_stock_once_with_traceability(self):
        d = self.donation()
        self.client.force_login(self.staff_user)
        url = reverse("bloodbank:lab_result", args=[d.pk])
        spec = f.spec("WB", "350ML")
        data = {"result": "passed", "blood_group": "O-", "product_spec_id": spec.pk, "quantity": 1, "idempotency_key": "k1"}
        self.client.post(url, data)
        self.client.post(url, data)  # bấm 2 lần → không nhập 2 lần
        d.refresh_from_db()
        self.assertEqual((d.lab_status, d.lab_blood_group, d.lab_checked_by_id), ("passed", "O-", self.staff_user.pk))
        stock = Stock.objects.get(hospital=self.h, product_spec=spec)
        self.assertEqual((stock.blood_group, stock.quantity_on_hand), ("O-", 1))  # theo xét nghiệm, không theo A+ tự khai
        txn = StockTxn.objects.get(donation=d)
        self.assertEqual((txn.txn_type, txn.quantity_change), ("receive", 1))
        self.assertNotContains(self.client.get(reverse("bloodbank:lab_queue")), f"lab-{d.pk}")
        self.assertContains(self.client.get(reverse("bloodbank:stock_ledger")), d.code)

    def test_failed_lab_needs_note_and_does_not_touch_stock(self):
        d = self.donation()
        with self.assertRaises(BusinessError):
            lab.record_lab_result(self.staff, d.pk, "failed", {}, "k2")
        lab.record_lab_result(self.staff, d.pk, "failed", {"lab_note": "HBsAg dương tính"}, "k2")
        d.refresh_from_db()
        self.assertEqual(d.lab_status, "failed")
        self.assertFalse(StockTxn.objects.exists())
        with self.assertRaises(BusinessError):  # đã có kết quả thì không đổi sang kết quả khác
            lab.record_lab_result(self.staff, d.pk, "passed", {"blood_group": "O+", "product_spec_id": f.spec("WB", "250ML").pk}, "k3")

    def test_passed_requires_lab_blood_group(self):
        d = self.donation()
        with self.assertRaises(BusinessError):
            lab.record_lab_result(self.staff, d.pk, "passed", {"product_spec_id": f.spec("WB", "250ML").pk}, "k4")
        self.assertEqual(Donation.objects.get(pk=d.pk).lab_status, "pending")

    def test_other_hospital_and_voided_donation_rejected(self):
        d = self.donation()
        with self.assertRaises(BusinessError):
            lab.record_lab_result(self.other_staff, d.pk, "failed", {"lab_note": "x"}, "k5")
        don.void_donation(self.staff, d.pk, "Ghi nhầm", "not_donated")
        with self.assertRaises(BusinessError):
            lab.record_lab_result(self.staff, d.pk, "failed", {"lab_note": "x"}, "k6")
        self.assertNotIn(d, list(lab.lab_queue(self.h)))


class ScheduledJobTests(TestCase):
    """(b) Tác vụ định kỳ chạy độc lập với việc có người mở trang; (c) nhắc yêu cầu cần máu chưa xác minh."""

    @classmethod
    def setUpTestData(cls):
        from bloodbank.services import inventory as inv

        cls.req_h, cls.sup_h, cls.sup2_h = f.hospital(), f.hospital(), f.hospital()
        cls.req_staff = f.staff(cls.req_h).staffs.get()
        cls.sup_staff = f.staff(cls.sup_h).staffs.get()
        cls.sup2_staff = f.staff(cls.sup2_h).staffs.get()
        cls.spec = f.spec()
        for s in (cls.sup_staff, cls.sup2_staff):
            inv.receive(s, cls.spec.pk, "O-", 6, f"seed-{s.pk}")
            st = Stock.objects.get(hospital=s.hospital)
            inv.update_stock_settings(s, st.pk, 5, 0, st.version)
        cls.admin = f.user(role="admin")
        cls.member = f.user()

    def make_request(self, suppliers, needed_by=None):
        from bloodbank.services import transfers as trf

        return trf.create_request(self.req_staff, {"blood_group": "O-", "product_spec_id": self.spec.pk,
                                                   "quantity_needed": 4, "needed_by": needed_by},
                                  [(h.pk, 2) for h in suppliers])

    def test_overdue_request_expires_and_releases_reservation_without_page_view(self):
        from datetime import timedelta

        from bloodbank.models import HospitalRequest
        from bloodbank.services import jobs, transfers as trf

        req = self.make_request([self.sup_h], needed_by=timezone.now() + timedelta(hours=1))
        offer = req.offers.get()
        trf.accept_offer(self.sup_staff, offer.pk, 2)
        self.assertEqual(Stock.objects.get(hospital=self.sup_h).quantity_reserved, 2)
        HospitalRequest.objects.filter(pk=req.pk).update(needed_by=timezone.now() - timedelta(minutes=1))
        result = jobs.run_all()
        req.refresh_from_db()
        self.assertEqual((req.status, result["expired_requests"]), ("expired", 1))
        self.assertEqual(Stock.objects.get(hospital=self.sup_h).quantity_reserved, 0)  # giữ chỗ được giải phóng

    def test_unanswered_offer_is_auto_cancelled(self):
        from datetime import timedelta

        from bloodbank.models import Notification, RequestOffer
        from bloodbank.services import jobs, transfers as trf

        req = self.make_request([self.sup_h, self.sup2_h])
        stale, fresh = req.offers.order_by("pk")
        trf.accept_offer(self.sup2_staff, fresh.pk, 2)  # đã phản hồi → không bị hủy
        RequestOffer.objects.filter(pk__in=[stale.pk, fresh.pk]).update(created_at=timezone.now() - timedelta(hours=13))
        self.assertEqual(jobs.cancel_stale_offers(), 1)
        stale.refresh_from_db(), fresh.refresh_from_db(), req.refresh_from_db()
        self.assertEqual((stale.status, fresh.status, req.status), ("cancelled", "accepted", "in_progress"))
        self.assertTrue(Notification.objects.filter(user=self.req_staff.user, type="offer_timeout").exists())
        self.assertEqual(jobs.cancel_stale_offers(), 0)  # chạy lại không làm gì thêm

    def test_patient_request_alerts_and_escalates_once_per_level(self):
        from datetime import timedelta

        from django.core import mail

        from bloodbank.models import Notification, PatientRequest
        from bloodbank.services import jobs, patients

        with self.captureOnCommitCallbacks(execute=True):
            prq = patients.submit(self.member, {"consent": True, "hospital_id": self.req_h.pk, "quantity_units": 2,
                                                "blood_group": "O-", "contact_name": "A", "contact_phone": "0905000111"})
        self.assertEqual([m.to for m in mail.outbox], [[self.req_staff.user.email]])  # email ngay khi gửi
        self.assertNotIn("Lê", mail.outbox[0].body)
        # Chưa tới 15 phút → chưa nhắc
        self.assertEqual(jobs.escalate_patient_requests(), {"staff": 0, "admin": 0})
        PatientRequest.objects.filter(pk=prq.pk).update(created_at=timezone.now() - timedelta(minutes=20))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(jobs.escalate_patient_requests(), {"staff": 1, "admin": 0})
        PatientRequest.objects.filter(pk=prq.pk).update(created_at=timezone.now() - timedelta(minutes=40))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(jobs.escalate_patient_requests(), {"staff": 0, "admin": 1})
            self.assertEqual(jobs.escalate_patient_requests(), {"staff": 0, "admin": 0})  # mỗi mức một lần
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(mail.outbox[2].to, [self.admin.email])
        email_rows = Notification.objects.filter(channel="email")
        self.assertEqual(set(email_rows.values_list("delivery_status", flat=True)), {"sent"})
        # Đã có người nhận xác minh → không nhắc nữa
        prq2 = PatientRequest.objects.create(**{k: getattr(prq, k) for k in (
            "requester", "contact_name", "contact_phone", "hospital", "quantity_units", "consent_at")},
            request_code="PR-TEST-2", status="verifying")
        PatientRequest.objects.filter(pk=prq2.pk).update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(jobs.escalate_patient_requests(), {"staff": 0, "admin": 0})

    def test_email_rows_do_not_duplicate_in_app_list(self):
        from bloodbank.services import patients

        patients.submit(self.member, {"consent": True, "hospital_id": self.req_h.pk, "quantity_units": 1,
                                      "contact_name": "A", "contact_phone": "0905000111"})
        self.client.force_login(self.req_staff.user)
        r = self.client.get(reverse("bloodbank:notifications"))
        self.assertEqual(len(r.context["page"].object_list), 1)

    def test_run_jobs_command(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("run_jobs", stdout=out)
        self.assertIn("expired_requests", out.getvalue())


class SourceSuggestionTests(TestCase):
    """(d) Xếp hạng nguồn theo khoảng cách, tự chia số cần cho nhiều bệnh viện, gửi bằng một lần bấm."""

    @classmethod
    def setUpTestData(cls):
        from bloodbank.services import inventory as inv

        cls.me = f.hospital(latitude=16.0678, longitude=108.2208)
        cls.near = f.hospital(name="BV Gần", latitude=16.0640, longitude=108.1880)   # ~3,5 km
        cls.far = f.hospital(name="BV Xa", latitude=15.5730, longitude=108.4740)     # ~60 km
        cls.nocoord = f.hospital(name="BV Không tọa độ")
        cls.staff_user = f.staff(cls.me)
        cls.spec = f.spec()
        for h, share in ((cls.near, 2), (cls.far, 5), (cls.nocoord, 9)):
            s = f.staff(h).staffs.get()
            inv.receive(s, cls.spec.pk, "O-", 10, f"seed-{h.pk}")
            st = Stock.objects.get(hospital=h)
            inv.update_stock_settings(s, st.pk, share, 0, st.version)

    def test_ranking_and_allocation(self):
        from bloodbank.services import transfers as trf

        rows = trf.search_sources(self.me, "O-", self.spec.product_id)
        self.assertEqual([r["hospital"].name for r in rows], ["BV Gần", "BV Xa", "BV Không tọa độ"])
        self.assertLess(rows[0]["distance_km"], rows[1]["distance_km"])
        self.assertIsNone(rows[2]["distance_km"])
        self.assertEqual(trf.suggest_allocation(rows, 6, self.spec.pk), {self.near.pk: 2, self.far.pk: 4})
        self.assertEqual(trf.suggest_allocation(rows, 20, self.spec.pk), {self.near.pk: 2, self.far.pk: 5, self.nocoord.pk: 9})
        self.assertEqual(trf.suggest_allocation(rows, 3, f.spec("RBC", "350ML").pk), {})  # sai quy cách thì không gợi ý

    def test_one_click_send_with_suggestion(self):
        from bloodbank.models import HospitalRequest

        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:source_search"), {"blood_group": "O-", "product": self.spec.product_id,
                                                                 "spec": self.spec.pk, "qty": 6})
        self.assertEqual(r.context["plan"], {self.near.pk: 2, self.far.pk: 4})
        self.assertContains(r, f'name="qty_{self.far.pk}" value="4"')
        # Gửi đúng như gợi ý (những gì trình duyệt gửi khi bấm nút)
        self.client.post(reverse("bloodbank:support_request_create"), {
            "blood_group": "O-", "product_spec_id": self.spec.pk, "quantity_needed": 6, "priority": "urgent",
            "supplier": [self.near.pk, self.far.pk], f"qty_{self.near.pk}": 2, f"qty_{self.far.pk}": 4})
        req = HospitalRequest.objects.get()
        self.assertEqual(dict(req.offers.values_list("supplier_hospital_id", "quantity_requested")),
                         {self.near.pk: 2, self.far.pk: 4})


class DonationIntervalWarningTests(TestCase):
    """(e) Cảnh báo — không chặn — khi chưa đủ khoảng cách giữa 2 lần hiến."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.donor = f.user()

    def past_donation(self, days, donation_type="whole_blood"):
        from datetime import timedelta

        c = f.campaign(self.h, start_offset_h=-24 * days - 2)
        reg = f.registration(c, self.donor, status="donated")
        extra = {"volume_ml": 350} if donation_type == "whole_blood" else {
            "component_product": f.spec("PLT", "STANDARD").product, "component_quantity": 1, "component_unit": "unit"}
        return Donation.objects.create(donor=self.donor, registration=reg, hospital=self.h, donation_type=donation_type,
                                       donated_at=timezone.now() - timedelta(days=days), confirmed_by=self.staff_user, **extra)

    def test_rules(self):
        self.assertIsNone(don.interval_warning(self.donor))  # chưa hiến lần nào
        d = self.past_donation(40)
        w = don.interval_warning(self.donor)
        self.assertEqual((w["days"], w["min_days"], w["remaining"]), (40, 84, 44))
        Donation.objects.filter(pk=d.pk).update(donated_at=timezone.now() - timezone.timedelta(days=90))
        self.assertIsNone(don.interval_warning(self.donor))

    def test_component_interval_and_voided_ignored(self):
        self.past_donation(20, "component")
        self.assertIsNone(don.interval_warning(self.donor))  # thành phần: 14 ngày
        d = self.past_donation(5)
        self.assertIsNotNone(don.interval_warning(self.donor))
        don.void_donation(self.staff_user.staffs.get(), d.pk, "Ghi nhầm", "not_donated")
        self.assertIsNone(don.interval_warning(self.donor))

    def test_checkin_screen_warns_but_still_allows_checkin(self):
        self.past_donation(30)
        c = f.campaign(self.h, start_offset_h=-1)
        reg = f.registration(c, self.donor, status="approved")
        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:checkin", args=[c.pk]) + f"?reg={reg.pk}")
        self.assertContains(r, "Chưa đủ khoảng cách giữa 2 lần hiến")
        r = self.client.post(reverse("bloodbank:checkin_action", args=[reg.pk]), {"action": "checkin"}, follow=True)
        reg.refresh_from_db()
        self.assertEqual(reg.status, "attended")  # không chặn
        self.assertContains(r, "cách đây 30 ngày")


class ShortageActionTests(TestCase):
    """(f) Từ dòng thiếu hụt: xin hỗ trợ, tạo đợt hiến (điền sẵn), kêu gọi người hiến cùng nhóm ở gần."""

    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta

        from bloodbank.services import inventory as inv

        cls.h = f.hospital(province="Đà Nẵng")
        cls.staff_user = f.staff(cls.h)
        inv.save_demand(cls.staff_user.staffs.get(), {"blood_group": "O-", "product_spec_id": f.spec().pk,
                                                      "required_quantity": 5, "needed_by": None})
        mk = lambda **kw: f.user(**{"blood_group": "O-", "province": "Đà Nẵng", **kw})  # noqa: E731
        cls.ok1, cls.ok2 = mk(), mk()
        cls.other_group = mk(blood_group="A+")
        cls.other_province = mk(province="Quảng Nam")
        cls.recent_donor = mk()
        cls.staff_other = f.user(role="hospital", blood_group="O-", province="Đà Nẵng")
        c = f.campaign(cls.h, start_offset_h=-30 * 24)
        reg = f.registration(c, cls.recent_donor, status="donated")
        Donation.objects.create(donor=cls.recent_donor, registration=reg, hospital=cls.h, volume_ml=350,
                                donated_at=timezone.now() - timedelta(days=30), confirmed_by=cls.staff_user)
        cls.open_campaign = f.campaign(cls.h, start_offset_h=48, name="Đợt cứu O−")

    def test_candidates_follow_fixed_rules(self):
        from bloodbank.services import callout

        self.assertEqual(set(callout.candidates(self.h, "O-")), {self.ok1, self.ok2})

    def test_demands_screen_shows_three_actions(self):
        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:demands"))
        self.assertContains(r, "Xin hỗ trợ")
        self.assertContains(r, reverse("bloodbank:hospital_campaign_create") + "?blood_group=O-")
        self.assertContains(r, "Kêu gọi (2)")
        r = self.client.get(reverse("bloodbank:hospital_campaign_create") + "?blood_group=O-")
        self.assertEqual(r.context["form"].initial["name"], "Hiến máu khẩn — cần nhóm O-")

    def test_callout_notifies_and_has_cooldown(self):
        from django.core import mail

        from bloodbank.models import AuditLog, Notification

        self.client.force_login(self.staff_user)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("bloodbank:donor_callout"), {"blood_group": "O-"}, follow=True)
        self.assertContains(r, "tới 2 người hiến phù hợp")
        got = Notification.objects.filter(type="donor_callout", channel="in_app")
        self.assertEqual(set(got.values_list("user_id", flat=True)), {self.ok1.pk, self.ok2.pk})
        self.assertEqual(set(got.values_list("entity_type", flat=True)), {"donor_callouts"})
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(AuditLog.objects.get(action="donor_callout").new_values["recipients"], 2)
        # Gửi lại ngay → bị chặn bởi thời gian chờ
        r = self.client.post(reverse("bloodbank:donor_callout"), {"blood_group": "O-"}, follow=True)
        self.assertContains(r, "Có thể kêu gọi lại sau")
        self.assertEqual(got.count(), 2)
        # Người nhận mở thông báo → tới trang đợt hiến để đăng ký
        self.client.force_login(self.ok1)
        r = self.client.get(reverse("bloodbank:notifications"))
        self.assertContains(r, reverse("bloodbank:campaign_detail", args=[self.open_campaign.pk]))

    def test_callout_requires_candidates(self):
        from bloodbank.services import callout

        with self.assertRaises(BusinessError):
            callout.donor_callout(self.staff_user.staffs.get(), "AB-")
