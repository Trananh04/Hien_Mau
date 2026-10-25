"""Góp ý vòng 2 (sheet TT_/BV_/QT_): giao diện người dùng, luồng bệnh viện, bệnh viện tự đăng ký, quản trị."""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from accounts.provinces import PROVINCES
from bloodbank.models import Donation, Hospital, Notification, PatientRequest, Product, Staff
from bloodbank.services import hospital_signup, lab
from bloodbank.services import patients as prq_service
from bloodbank.services.common import BusinessError

from . import factories as f

PW = "MatKhau!2026"


class MemberPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        f.staff(cls.h)
        cls.member = f.user()

    def setUp(self):
        self.client.force_login(self.member)

    def test_profile_order_and_no_role_badge_or_notes(self):
        r = self.client.get(reverse("bloodbank:profile"))
        html = r.content.decode()
        # TT_004: Thông tin cá nhân → Đóng góp của bạn → Đổi mật khẩu
        self.assertLess(html.index("Thông tin cá nhân"), html.index("Đóng góp của bạn"))
        self.assertLess(html.index("Đóng góp của bạn"), html.index("Đổi mật khẩu"))
        self.assertNotIn("Chỉ để bạn tự theo dõi", html)                        # TT_002
        self.assertNotIn('plain">Người dùng</span>', html)                      # TT_003
        self.assertContains(r, 'class="container page-body text-lg"')          # TT_001

    def test_register_page_has_no_notes(self):
        self.client.logout()
        r = self.client.get(reverse("accounts:register"))
        self.assertNotContains(r, "Chỉ mất khoảng một phút")
        self.assertNotContains(r, "Tối thiểu 8 ký tự")

    def test_history_has_no_badges(self):
        self.assertNotContains(self.client.get(reverse("bloodbank:my_history")), "Huy hiệu của bạn")   # TT_007

    def test_patient_request_requires_group_and_product_and_future_time(self):
        url = reverse("bloodbank:patient_request_new")
        r = self.client.get(url)
        self.assertNotContains(r, "Chưa rõ")                                    # TT_006
        self.assertNotContains(r, "Lưu ý quan trọng")
        self.assertContains(r, 'min="')                                         # TT_005: khóa ngày đã qua
        base = {"contact_name": "A", "contact_phone": "0905000111", "hospital_id": self.h.pk, "quantity_units": 1,
                "consent": "on"}
        r = self.client.post(url, base)
        self.assertContains(r, "Chọn nhóm máu của bệnh nhân.")
        self.assertContains(r, "Chọn loại chế phẩm cần.")
        product = f.spec().product_id
        past = (timezone.localtime() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(url, {**base, "blood_group": "A+", "blood_product_id": product, "needed_by": past})
        self.assertContains(r, "Không chọn thời điểm đã qua.")
        self.assertFalse(PatientRequest.objects.exists())
        r = self.client.post(url, {**base, "blood_group": "A+", "blood_product_id": product})
        self.assertEqual(PatientRequest.objects.get().blood_product_id, product)
        with self.assertRaises(BusinessError):     # gọi thẳng service cũng bắt buộc
            prq_service.submit(self.member, {**base, "consent": True, "blood_group": ""})


class HospitalPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff_user = f.staff(cls.h)
        cls.staff = cls.staff_user.staffs.get()
        cls.member = f.user(blood_group="O+")

    def setUp(self):
        self.client.force_login(self.staff_user)

    def _prq(self, **kw):
        return prq_service.submit(self.member, {"consent": True, "hospital_id": self.h.pk, "quantity_units": 2,
                                                "blood_group": "O+", "blood_product_id": f.spec().product_id,
                                                "contact_name": "A", "contact_phone": "0905000111", **kw})

    def test_patient_request_without_intermediate_steps_and_tab_counts(self):
        p = self._prq()
        self.assertEqual(prq_service.hospital_actions(p), ["verify", "reject"])          # BV_003
        r = self.client.get(reverse("bloodbank:hospital_patient_request_detail", args=[p.pk]))
        self.assertNotContains(r, "Nhận xác minh")
        self.assertNotContains(r, "Bắt đầu xử lý")
        r = self.client.get(reverse("bloodbank:hospital_patient_requests"))
        self.assertContains(r, "Chờ xác minh (1)")                                         # BV_004
        self.assertContains(r, "Đang điều phối (0)")
        p = prq_service.hospital_action(self.staff, p.pk, "verify", {"blood_group": "O+"})
        self.assertIn("fulfill", prq_service.hospital_actions(p))                         # hoàn tất ngay sau xác minh
        p = prq_service.hospital_action(self.staff, p.pk, "fulfill", {"resolution_note": "Đã cấp"})
        self.assertEqual(p.status, "fulfilled")
        with self.assertRaises(BusinessError):
            prq_service.hospital_action(self.staff, self._prq().pk, "start_verify", {})

    def test_stock_issue_options_show_product(self):
        p = prq_service.hospital_action(self.staff, self._prq().pk, "verify", {"blood_group": "O+"})
        r = self.client.get(reverse("bloodbank:stock_txn", args=["xuat"]))
        self.assertContains(r, f"{p.request_code} · O+ · {f.spec().product.name} · 2 đơn vị")     # BV_010

    def test_sidebar_highlights_single_item(self):
        r = self.client.get(reverse("bloodbank:stock_ledger"))                           # BV_011
        self.assertEqual(r.content.decode().count('class="ws-link active"'), 1)

    def test_back_button_replaces_breadcrumbs(self):
        c = f.campaign(self.h)
        r = self.client.get(reverse("bloodbank:hospital_campaign_detail", args=[c.pk]))     # BV_001
        self.assertContains(r, f'href="{reverse("bloodbank:hospital_campaigns")}" class="ws-back"')

    def test_checkin_selected_shows_only_form_with_apheresis_types(self):
        c = f.campaign(self.h)
        reg = f.registration(c, self.member, status="attended")
        detail = reverse("bloodbank:hospital_campaign_detail", args=[c.pk]) + "?tab=registrations"
        r = self.client.get(reverse("bloodbank:checkin", args=[c.pk]), {"reg": reg.pk, "status": "attended",
                                                                         "next": detail})
        self.assertContains(r, 'id="record-form"')
        self.assertNotContains(r, 'class="list-select"')                                 # BV_002: chỉ còn form
        self.assertContains(r, 'class="ws-back"')
        for label in ("Tiểu cầu", "Huyết tương", "Hồng cầu đôi", "Bạch cầu hạt"):
            self.assertContains(r, f">{label}</option>")
        r = self.client.post(reverse("bloodbank:record_donation", args=[reg.pk]), {
            "donation_type": "whole_blood", "volume_ml": "450", "next": detail,
            "donated_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")})
        self.assertRedirects(r, detail, fetch_redirect_response=False)                  # quay lại trang đã mở

    def test_450ml_bag_goes_to_450_spec(self):
        c = f.campaign(self.h)
        reg = f.registration(c, self.member, status="donated")
        d = Donation.objects.create(donor=self.member, registration=reg, hospital=self.h, volume_ml=450,
                                    donated_at=timezone.now(), confirmed_by=self.staff_user)
        self.assertEqual([(s.product.code, s.code) for s, _ in lab.yield_plan(d, "nguyen")], [("WB", "450ML")])
        self.assertEqual([(s.product.code, s.code) for s, _ in lab.yield_plan(d, "tach")],
                         [("RBC", "450ML"), ("FFP", "STANDARD")])                        # BV_009

    def test_donor_lookup_all_tab_first_and_detail_page(self):
        c = f.campaign(self.h)
        f.registration(c, self.member)
        url = reverse("bloodbank:donor_lookup")
        r = self.client.get(url)
        self.assertEqual(r.context["tab"], "tat-ca")                                      # BV_007
        html = r.content.decode()
        self.assertLess(html.index("Tất cả <span"), html.index("Đã hiến <span"))
        self.assertContains(r, self.member.full_name)
        detail = reverse("bloodbank:donor_detail", args=[self.member.pk])
        self.assertContains(r, detail)                                                    # BV_008: trang riêng
        self.assertContains(self.client.get(detail), "Đơn đăng ký")
        self.assertRedirects(self.client.get(url, {"donor": self.member.pk}), detail, fetch_redirect_response=False)
        self.client.force_login(f.staff(f.hospital()))                                    # bệnh viện khác
        self.assertEqual(self.client.get(detail).status_code, 404)

    def test_campaign_form_blocks_past_start_but_allows_unchanged(self):
        c = f.campaign(self.h, status="draft")
        url = reverse("bloodbank:hospital_campaign_edit", args=[c.pk])
        local = timezone.localtime
        data = {"name": c.name, "location_name": c.location_name, "address": c.address, "province": PROVINCES[0],
                "start_time": local(c.start_time).strftime("%Y-%m-%dT%H:%M"),
                "end_time": local(c.end_time).strftime("%Y-%m-%dT%H:%M")}
        self.client.post(url, data)       # giờ bắt đầu cũ (đã qua) không đổi → vẫn lưu được
        c.refresh_from_db()
        self.assertEqual(c.province, PROVINCES[0])
        data["start_time"] = (local() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.assertContains(self.client.post(url, data), "Không chọn thời điểm đã qua.")

    def test_home_navbar_links_to_hospital_workspace(self):
        r = self.client.get(reverse("bloodbank:home"))                                    # BV_013
        self.assertContains(r, f'href="{reverse("bloodbank:hospital_dashboard")}" class="nav-cta-btn">Quản lý bệnh viện')


class GeocodeTests(TestCase):
    def test_geocode_endpoint(self):
        url = reverse("bloodbank:geocode")
        with mock.patch("bloodbank.services.geocode.lookup", return_value={"lat": 16.07, "lng": 108.15, "label": "x"}):
            r = self.client.get(url, {"address": "54 Nguyễn Lương Bằng", "province": "Đà Nẵng"})
        self.assertEqual(r.json()["lat"], 16.07)
        with mock.patch("bloodbank.services.geocode.lookup", return_value=None):
            self.assertEqual(self.client.get(url, {"address": "không có"}).status_code, 404)


class HospitalSignupTests(TestCase):
    """BV_014: bệnh viện tự đăng ký → Quản trị duyệt → Quản lý tự cấp tài khoản nhân viên."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = f.user(role="admin", email="qt@test.vn")

    def _signup(self, code="BVTEST", email="quanly@bv.vn"):
        return self.client.post(reverse("accounts:hospital_register"), {
            "code": code, "name": "Bệnh viện Đăng Ký", "address": "1 Đường Mẫu", "province": PROVINCES[0],
            "phone": "0236000111", "email": "lienhe@bv.vn", "manager_name": "Quản Lý A", "manager_email": email,
            "manager_phone": "0905777888", "password": PW, "password2": PW, "accept_terms": "on"})

    def _login(self, email):
        return self.client.post(reverse("accounts:hospital_login"), {"email": email, "password": PW})

    def test_signup_approve_and_manager_adds_staff(self):
        r = self._signup()
        self.assertContains(r, "đang chờ Quản trị hệ thống duyệt")
        h = Hospital.objects.get(code="BVTEST")
        self.assertEqual(h.status, "pending")
        manager = Staff.objects.get(hospital=h)
        self.assertTrue(manager.is_manager)
        self.assertTrue(Notification.objects.filter(user=self.admin, type="hospital_signup").exists())
        # Chưa duyệt → không đăng nhập được, báo rõ lý do
        self.assertContains(self._login("quanly@bv.vn"), "đang chờ Quản trị hệ thống duyệt")
        self.assertNotIn("_auth_user_id", self.client.session)
        # Quản trị thấy ở tab Chờ duyệt và duyệt
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("bloodbank:admin_hospitals")), "Chờ duyệt (1)")
        self.client.post(reverse("bloodbank:admin_hospital_edit", args=[h.pk]), {"form": "approve"})
        h.refresh_from_db()
        self.assertEqual(h.status, "active")
        self.assertTrue(Notification.objects.filter(user=manager.user, type="hospital_approved").exists())
        # Quản lý đăng nhập, cấp tài khoản nhân viên
        self.client.logout()
        self.assertRedirects(self._login("quanly@bv.vn"), reverse("bloodbank:hospital_dashboard"),
                             fetch_redirect_response=False)
        url = reverse("bloodbank:hospital_staff")
        self.assertContains(self.client.get(url), 'data-open-dialog="add-staff"')
        self.client.post(url, {"form": "staff_add", "email": "nv1@bv.vn", "full_name": "Nhân Viên Một",
                               "password": PW})
        new = Staff.objects.get(user__email="nv1@bv.vn")
        self.assertEqual((new.hospital_id, new.staff_role, new.user.role), (h.pk, "staff", "hospital"))
        # Quản lý không tự thu hồi mình; thu hồi được nhân viên
        self.client.post(url, {"form": "staff_update", "op": "deactivate", "staff_id": manager.pk})
        manager.refresh_from_db()
        self.assertTrue(manager.is_active)
        self.client.post(url, {"form": "staff_update", "op": "deactivate", "staff_id": new.pk})
        new.refresh_from_db()
        self.assertFalse(new.is_active)
        # Nhân viên thường chỉ xem, không cấp được tài khoản
        new.is_active = True
        new.save()
        self.client.force_login(new.user)
        self.assertNotContains(self.client.get(url), 'data-open-dialog="add-staff"')
        self.client.post(url, {"form": "staff_add", "email": "nv2@bv.vn", "full_name": "Nhân Viên Hai",
                               "password": PW})
        self.assertFalse(User.objects.filter(email="nv2@bv.vn").exists())

    def test_reject_and_duplicates(self):
        self._signup()
        h = Hospital.objects.get(code="BVTEST")
        with self.assertRaises(BusinessError):
            hospital_signup.reject(self.admin, h.pk, "")                  # bắt buộc lý do
        hospital_signup.reject(self.admin, h.pk, "Mã cơ sở không khớp")
        h.refresh_from_db()
        self.assertEqual(h.status, "rejected")
        self.assertContains(self._login("quanly@bv.vn"), "Mã cơ sở không khớp")
        r = self._signup(code="BVTEST", email="khac@bv.vn")
        self.assertContains(r, "Mã cơ sở này đã được đăng ký.")
        r = self._signup(code="BVKHAC", email="quanly@bv.vn")
        self.assertContains(r, "Email này đã có tài khoản.")
        with self.assertRaises(BusinessError):
            hospital_signup.approve(self.admin, h.pk)                     # đã từ chối → không duyệt lại


class AdminOverviewRemovedTests(TestCase):
    def test_admin_lands_on_users_and_has_no_overview(self):
        admin = f.user(role="admin", email="qt2@test.vn")
        r = self.client.post(reverse("accounts:admin_login"), {"email": admin.email, "password": PW})
        self.assertRedirects(r, reverse("bloodbank:admin_users"), fetch_redirect_response=False)   # QT_001
        r = self.client.get(reverse("bloodbank:admin_users"))
        self.assertNotContains(r, "Tổng quan")
        self.assertEqual(Product.objects.filter(code__in=["RBC2", "GRAN"]).count(), 2)
