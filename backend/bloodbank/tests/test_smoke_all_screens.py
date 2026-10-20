"""Bước 9: nạp dữ liệu mẫu rồi mở MỌI màn hình với từng vai trò — không được có lỗi 500/template."""
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from bloodbank.models import (
    Campaign, Donation, HospitalRequest, PatientRequest, Registration, RequestOffer, Staff,
)


class SmokeAllScreens(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.admin = User.objects.get(email="admin@hienmau.vn")
        cls.member = User.objects.get(email="an.nguyen@demo.vn")
        cls.staff = User.objects.get(email="benhvien1@hienmau.vn")

    def get(self, url, expect=200):
        r = self.client.get(url)
        self.assertEqual(r.status_code, expect, f"{url} → {r.status_code}")
        return r

    def test_public_pages(self):
        c = Campaign.objects.filter(status="open").first()
        for url in ["/", reverse("bloodbank:campaigns"), reverse("bloodbank:campaigns") + "?when=past",
                    reverse("bloodbank:campaign_detail", args=[c.pk]), reverse("bloodbank:map"),
                    reverse("bloodbank:map_data"), reverse("accounts:login"), reverse("accounts:register"),
                    reverse("accounts:forgot_password"), reverse("accounts:hospital_login"),
                    reverse("accounts:admin_login")]:
            self.get(url)

    def test_member_pages(self):
        self.client.force_login(self.member)
        d = Donation.objects.filter(donor=self.member).first()
        p = PatientRequest.objects.filter(requester=self.member).first()
        for url in [reverse("bloodbank:profile"), reverse("bloodbank:my_registrations"), reverse("bloodbank:my_history"),
                    reverse("bloodbank:my_history") + "?voided=1", reverse("bloodbank:my_donation_detail", args=[d.pk]),
                    reverse("bloodbank:patient_request_new"), reverse("bloodbank:my_patient_requests"),
                    reverse("bloodbank:my_patient_request_detail", args=[p.pk]), reverse("bloodbank:notifications"), "/"]:
            self.get(url)

    def _hospital_urls(self):
        h = Staff.objects.get(user=self.staff, hospital__code="BVM-HC").hospital
        today = Campaign.objects.get(hospital=h, status="open", name__startswith="Hiến máu cuối tuần")
        reg = Registration.objects.filter(campaign=today, status="attended").first()
        don = Donation.objects.filter(hospital=h).first()
        sreq = HospitalRequest.objects.filter(requesting_hospital=h).first()
        prq = PatientRequest.objects.filter(hospital=h).first()
        return [
            reverse("bloodbank:hospital_dashboard"), reverse("bloodbank:hospital_campaigns"),
            reverse("bloodbank:hospital_campaign_detail", args=[today.pk]),
            reverse("bloodbank:hospital_campaign_detail", args=[today.pk]) + "?tab=registrations",
            reverse("bloodbank:hospital_campaign_detail", args=[today.pk]) + "?tab=summary",
            reverse("bloodbank:hospital_campaign_create"), reverse("bloodbank:hospital_campaign_edit", args=[today.pk]),
            reverse("bloodbank:checkin", args=[today.pk]), reverse("bloodbank:checkin", args=[today.pk]) + f"?reg={reg.pk}&status=attended",
            reverse("bloodbank:hospital_donation_detail", args=[don.pk]), reverse("bloodbank:donor_lookup") + "?q=a",
            reverse("bloodbank:donor_lookup") + f"?q=a&donor={don.donor_id}", reverse("bloodbank:donation_report"),
            reverse("bloodbank:stock"), reverse("bloodbank:stock_txn", args=["nhap"]),
            reverse("bloodbank:stock_txn", args=["xuat"]), reverse("bloodbank:stock_txn", args=["dieu-chinh"]),
            reverse("bloodbank:stock_ledger"), reverse("bloodbank:demands"),
            reverse("bloodbank:source_search") + f"?blood_group=O-&product={sreq.product_spec.product_id}",
            reverse("bloodbank:support_requests"), reverse("bloodbank:support_request_detail", args=[sreq.pk]),
            reverse("bloodbank:incoming_offers"), reverse("bloodbank:hospital_patient_requests"),
            reverse("bloodbank:hospital_patient_request_detail", args=[prq.pk]), reverse("bloodbank:hospital_info"),
            reverse("bloodbank:hospital_staff"), reverse("bloodbank:hospital_audit"), reverse("bloodbank:catalog"),
            reverse("bloodbank:notifications"), reverse("bloodbank:work_account"),
        ]

    def test_hospital_staff_sees_every_hospital_screen(self):
        self.client.force_login(self.staff)
        for url in self._hospital_urls():
            self.get(url)

    def test_supplier_offer_screen(self):
        offer = RequestOffer.objects.filter(status="accepted").first()
        supplier = Staff.objects.filter(hospital=offer.supplier_hospital).order_by("pk").first().user
        self.client.force_login(supplier)
        self.get(reverse("bloodbank:offer_detail", args=[offer.pk]))
        self.get(reverse("bloodbank:offer_open", args=[offer.pk]), expect=302)

    def test_staff_works_at_single_hospital(self):
        # BR-03, BR-04: mỗi nhân viên chỉ thuộc một bệnh viện → không có bộ chọn bệnh viện
        self.assertEqual(Staff.objects.filter(user=self.staff).count(), 1)
        self.client.force_login(self.staff)
        r = self.get(reverse("bloodbank:hospital_dashboard"))
        self.assertContains(r, "ws-rail")
        self.assertNotContains(r, 'name="hospital_id"')

    def test_admin_pages(self):
        self.client.force_login(self.admin)
        h = Staff.objects.filter(user=self.staff).first().hospital
        for url in [reverse("bloodbank:admin_stats"), reverse("bloodbank:admin_users"), reverse("bloodbank:admin_hospitals"),
                    reverse("bloodbank:admin_hospital_create"), reverse("bloodbank:admin_hospital_edit", args=[h.pk]),
                    reverse("bloodbank:admin_audit"), reverse("bloodbank:admin_settings"), reverse("bloodbank:catalog"),
                    reverse("bloodbank:admin_permissions"), reverse("bloodbank:work_account"),
                    reverse("bloodbank:notifications")]:
            self.get(url)

    def test_seed_is_idempotent(self):
        before = User.objects.count()
        call_command("seed_demo", verbosity=0)
        self.assertEqual(User.objects.count(), before)
