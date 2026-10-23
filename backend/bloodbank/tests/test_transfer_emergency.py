"""Liên viện khi thiếu máu khẩn: đề nghị thừa được hủy khi đã đủ, quá hạn trả giữ chỗ, khẩn tự hủy nhanh + email."""
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import HospitalRequest, Notification, RequestOffer, Stock
from bloodbank.services import inventory as inv
from bloodbank.services import jobs
from bloodbank.services import transfers as trf

from . import factories as f


class EmergencyTransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.spec = f.spec()
        cls.asker, cls.a, cls.b = f.hospital(), f.hospital(), f.hospital()
        cls.s_asker, cls.s_a, cls.s_b = (f.staff(h).staffs.get() for h in (cls.asker, cls.a, cls.b))
        for s in (cls.s_a, cls.s_b):
            inv.receive(s, cls.spec.pk, "O-", 5, f"seed-{s.pk}")

    def ask(self, qty=3, priority="urgent", needed_by=None):
        return trf.create_request(self.s_asker, {"blood_group": "O-", "product_spec_id": self.spec.pk,
                                                 "quantity_needed": qty, "priority": priority, "needed_by": needed_by},
                                  [(self.a.pk, qty), (self.b.pk, qty)])

    def stock(self, h):
        return Stock.objects.get(hospital=h, blood_group="O-", product_spec=self.spec)

    def test_fulfilled_request_cancels_other_open_offers_and_releases_reservation(self):
        req = self.ask(qty=3)
        oa = req.offers.get(supplier_hospital=self.a)
        trf.accept_offer(self.s_a, oa.pk, 3)
        trf.dispatch_offer(self.s_a, oa.pk, "d1")
        trf.confirm_received(self.s_asker, oa.pk, 3, "r1")
        req.refresh_from_db()
        self.assertEqual(req.status, "fulfilled")
        ob = req.offers.get(supplier_hospital=self.b)
        self.assertEqual(ob.status, "cancelled")                  # B không còn treo trong "Cần xử lý"
        self.assertEqual(self.stock(self.b).quantity_reserved, 0)

    def test_overdue_partial_request_is_closed_and_reservation_released(self):
        req = self.ask(qty=4, priority="high", needed_by=timezone.now() + timedelta(hours=1))
        oa, ob = req.offers.get(supplier_hospital=self.a), req.offers.get(supplier_hospital=self.b)
        trf.accept_offer(self.s_a, oa.pk, 2)
        trf.dispatch_offer(self.s_a, oa.pk, "d2")
        trf.confirm_received(self.s_asker, oa.pk, 2, "r2")
        trf.accept_offer(self.s_b, ob.pk, 2)                      # B giữ chỗ 2 nhưng chưa xuất
        HospitalRequest.objects.filter(pk=req.pk).update(needed_by=timezone.now() - timedelta(minutes=5))
        trf.expire_overdue()
        req.refresh_from_db()
        self.assertEqual((req.status, req.closed_at is not None), ("partially_fulfilled", True))
        self.assertEqual(self.stock(self.b).quantity_reserved, 0)  # giữ chỗ được trả lại

    def test_urgent_offer_times_out_fast_and_notifies_by_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            req = self.ask(priority="urgent")
        self.assertTrue(any("[Khẩn]" in m.subject for m in mail.outbox))   # khẩn: có email cho bên cấp
        RequestOffer.objects.filter(request=req).update(created_at=timezone.now() - timedelta(minutes=61))
        self.assertEqual(jobs.cancel_stale_offers(), 2)              # khẩn: tự hủy sau 60 phút (không chờ 12 giờ)
        self.assertTrue(Notification.objects.filter(type="offer_timeout").exists())
        normal = self.ask(priority="normal")
        RequestOffer.objects.filter(request=normal).update(created_at=timezone.now() - timedelta(minutes=61))
        self.assertEqual(jobs.cancel_stale_offers(), 0)              # thường: vẫn chờ 12 giờ

    def test_urgent_shortage_link_prefills_urgent_priority_and_deadline(self):
        self.client.force_login(self.s_asker.user)
        deadline = timezone.now() + timedelta(hours=5)
        r = self.client.get(reverse("bloodbank:source_search"), {
            "blood_group": "O-", "product": self.spec.product_id, "spec": self.spec.pk, "qty": 3,
            "priority": "urgent", "needed_by": deadline.isoformat()})
        self.assertEqual(r.context["form"].initial["priority"], "urgent")
        self.assertEqual(r.context["form"].initial["needed_by"], timezone.localtime(deadline).strftime("%Y-%m-%dT%H:%M"))
        self.assertEqual(r.context["rows"], [])          # A, B chưa khai số chia sẻ nên không hiện trong kết quả


class EmergencyCaseTests(TestCase):
    """Nút Khẩn cấp: kho mình → bệnh viện gần còn dư → người hiến (chỉ khi bệnh viện không đủ)."""

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal

        cls.spec = f.spec()
        cls.h = f.hospital(latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        cls.near = f.hospital(latitude=Decimal("16.060"), longitude=Decimal("108.210"))
        cls.far = f.hospital(latitude=Decimal("16.300"), longitude=Decimal("108.250"))
        cls.staff = f.staff(cls.h).staffs.get()
        cls.s_near, cls.s_far = f.staff(cls.near).staffs.get(), f.staff(cls.far).staffs.get()
        inv.receive(cls.staff, cls.spec.pk, "O-", 1, "own")              # kho mình có 1
        for s, share in ((cls.s_near, 2), (cls.s_far, 5)):
            inv.receive(s, cls.spec.pk, "O-", 5, f"seed-{s.pk}")
            st = Stock.objects.get(hospital=s.hospital, blood_group="O-", product_spec=cls.spec)
            inv.update_stock_settings(s, st.pk, share, 0, st.version)

    def start(self, qty):
        from bloodbank.services import emergency

        return emergency.start(self.staff, {"blood_group": "O-", "product_spec_id": self.spec.pk, "quantity": qty})

    def test_own_stock_enough_asks_nobody(self):
        from bloodbank.services import emergency

        d = self.start(1)
        self.assertIsNone(d.support_request)
        self.assertEqual(emergency.state(d)["step"], "issue")

    def test_shortage_asks_nearest_hospitals_first_then_donors_only_after_refusal(self):
        from bloodbank.services import emergency

        d = self.start(5)                                   # thiếu 4: gần nhất chia sẻ 2, xa hơn chia sẻ 5 → 2 + 2
        req = d.support_request
        self.assertEqual(req.priority, "urgent")
        self.assertEqual({o.supplier_hospital_id: o.quantity_requested for o in req.offers.all()},
                         {self.near.pk: 2, self.far.pk: 2})
        st = emergency.state(d)
        self.assertEqual((st["step"], st["donors_needed"]), ("hospitals", 0))   # đang chờ bệnh viện → chưa gọi người hiến
        trf.reject_offer(self.s_far, req.offers.get(supplier_hospital=self.far).pk, "Không đủ")
        st = emergency.state(d)
        self.assertEqual((st["step"], st["donors_needed"]), ("donors", 2))      # bị từ chối → mới tới người hiến
        with self.assertRaises(Exception):                  # không còn bệnh viện nào khác để xin
            emergency.ask_more_hospitals(self.staff, d.pk)

    def test_pages_button_and_no_double_counting_with_patient_request(self):
        from bloodbank.models import PatientRequest

        self.client.force_login(self.staff.user)
        r = self.client.get(reverse("bloodbank:hospital_dashboard"))
        self.assertContains(r, 'class="sos-fab"')                       # nút Khẩn cấp nổi
        self.assertContains(r, reverse("bloodbank:emergency_new"))
        self.assertNotContains(r, reverse("bloodbank:source_search"))       # menu Liên viện đã ẩn
        prq = PatientRequest.objects.create(requester=f.user(), contact_name="A", contact_phone="0905000111",
                                            hospital=self.h, blood_group="O-", quantity_units=3,
                                            consent_at=timezone.now(), status="verified", request_code="PR-EMG-1",
                                            verified_by=self.staff.user, verified_at=timezone.now())
        r = self.client.post(reverse("bloodbank:emergency_new") + f"?patient_request={prq.pk}", {
            "blood_group": "O-", "product_spec_id": self.spec.pk, "quantity": 3})
        d = prq.emergency_demands.get()
        self.assertRedirects(r, reverse("bloodbank:emergency_case", args=[d.pk]))
        self.assertEqual(inv.urgent_requests(self.h), [])   # yêu cầu đã có ca khẩn → không tính thiếu trùng
        self.assertTrue(any(r["urgent"] for r in inv.shortages(self.h)))
        r = self.client.get(reverse("bloodbank:emergency_case", args=[d.pk]))
        self.assertContains(r, "Bệnh viện gần còn dư")
        self.assertContains(r, self.near.name)


class ForecastTests(TestCase):
    """Dự báo thiếu hụt: đủ dùng = khả dụng ÷ dùng/ngày (28 ngày xuất cho người bệnh) + nhu cầu có kế hoạch."""

    def test_days_cover_levels_and_public_sos_button(self):
        from bloodbank.services import forecast as fc

        h = f.hospital()
        staff = f.staff(h).staffs.get()
        spec = f.spec()
        inv.receive(staff, spec.pk, "O+", 30, "r")
        st = Stock.objects.get(hospital=h, blood_group="O+", product_spec=spec)
        for i in range(14):                                  # 28 đơn vị trong 28 ngày → 1 đơn vị / ngày
            inv.issue(staff, st.pk, 2, f"i{i}")
        rows = {r["blood_group"]: r for r in fc.forecast(h)}
        self.assertEqual(round(rows["O+"]["per_day"], 2), 1.0)
        self.assertEqual((round(rows["O+"]["days"]), rows["O+"]["level"]), (2, "soon"))
        inv.receive(staff, spec.pk, "O+", 8, "r2")             # 10 → đủ 10 ngày: cần lên kế hoạch
        self.assertEqual(fc.forecast(h)[0]["level"], "plan")
        inv.receive(staff, spec.pk, "O+", 20, "r3")            # 30 → đủ 30 ngày
        self.assertEqual(fc.forecast(h)[0]["level"], "ok")
        # Nút Khẩn cấp chỉ dành cho bệnh viện: khách / người dùng không thấy
        r = self.client.get(reverse("bloodbank:home"))
        self.assertNotContains(r, "sos-fab")
        self.client.force_login(f.user())
        self.assertNotContains(self.client.get(reverse("bloodbank:home")), "sos-fab")
        self.client.force_login(staff.user)
        self.assertContains(self.client.get(reverse("bloodbank:home")), 'class="sos-fab"')
