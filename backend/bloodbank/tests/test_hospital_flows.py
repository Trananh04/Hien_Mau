"""Bước 5–8: nghiệp vụ bệnh viện qua HTTP + kiểm thử phân quyền âm tính (Ch.9 mục 9.6)."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from bloodbank.models import (
    AuditLog, Donation, HospitalRequest, Notification, Registration, Stock, StockTxn,
)
from bloodbank.services import inventory as inv
from bloodbank.services.common import BusinessError

from . import factories as f


def local(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%dT%H:%M")


class CampaignAndDonationFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.other_h = f.hospital()
        cls.ha = f.staff(cls.h)
        cls.dc = f.staff(cls.h)
        cls.im = f.staff(cls.h)
        cls.donor = f.user(full_name="Người Hiến Một")

    def test_dashboard_lists_only_pending_work(self):
        from django.utils import timezone

        from bloodbank.models import PatientRequest

        self.client.force_login(self.ha)
        r = self.client.get(reverse("bloodbank:hospital_dashboard"))
        self.assertEqual([k["count"] for k in r.context["kpis"]], [0, 0, 0, 0])   # 4 chỉ số luôn hiện, đều 0
        self.assertEqual(r.context["others"], [])
        self.assertNotContains(r, "is-danger")
        PatientRequest.objects.create(requester=self.donor, contact_name="A", contact_phone="0905000999",
                                      hospital=self.h, quantity_units=1, consent_at=timezone.now(),
                                      request_code="PR-DASH-0001")
        r = self.client.get(reverse("bloodbank:hospital_dashboard"))
        kpi = {k["label"]: k for k in r.context["kpis"]}
        self.assertEqual(kpi["Yêu cầu chờ xác minh"]["count"], 1)
        self.assertContains(r, 'class="kpi is-danger"')
        self.assertContains(r, "PR-DASH-0001")
        self.assertNotContains(r, "Thông báo gần đây")   # đã có chuông trên thanh trên cùng

    def test_campaign_lifecycle_publish_close_cancel(self):
        self.client.force_login(self.dc)
        start = timezone.now() + timedelta(days=2)
        r = self.client.post(reverse("bloodbank:hospital_campaign_create"), {
            "name": "Đợt thử", "start_time": local(start), "end_time": local(start + timedelta(hours=4)),
            "location_name": "Sảnh", "address": "1 Đường", "province": "Đà Nẵng",
        })
        self.assertEqual(r.status_code, 302)
        from bloodbank.models import Campaign

        c = Campaign.objects.get(name="Đợt thử")
        self.assertEqual((c.status, c.hospital_id), ("draft", self.h.pk))
        act = reverse("bloodbank:hospital_campaign_action", args=[c.pk])
        self.client.post(act, {"action": "publish"})
        c.refresh_from_db()
        self.assertEqual(c.status, "open")
        reg = f.registration(c, self.donor, status="approved")
        self.client.post(act, {"action": "cancel"})  # thiếu lý do
        c.refresh_from_db()
        self.assertEqual(c.status, "open")
        self.client.post(act, {"action": "cancel", "reason": "Mưa bão"})
        c.refresh_from_db()
        reg.refresh_from_db()
        self.assertEqual((c.status, reg.status), ("cancelled", "cancelled"))
        self.assertTrue(Notification.objects.filter(user=self.donor, type="campaign_cancelled").exists())

    def test_end_before_start_rejected(self):
        self.client.force_login(self.dc)
        start = timezone.now() + timedelta(days=2)
        r = self.client.post(reverse("bloodbank:hospital_campaign_create"), {
            "name": "Sai giờ", "start_time": local(start), "end_time": local(start - timedelta(hours=1)),
            "location_name": "S", "address": "A",
        })
        self.assertContains(r, "Thời gian kết thúc phải sau thời gian bắt đầu.")
        self.assertNotContains(r, "(ERR-")

    def test_checkin_record_void_and_history(self):
        c = f.campaign(self.h, start_offset_h=-2)
        reg = f.registration(c, self.donor, status="approved")
        self.client.force_login(self.dc)
        self.assertEqual(self.client.get(reverse("bloodbank:checkin", args=[c.pk])).status_code, 200)
        self.client.post(reverse("bloodbank:checkin_action", args=[reg.pk]), {"action": "checkin"})
        reg.refresh_from_db()
        self.assertEqual(reg.status, "attended")
        url = reverse("bloodbank:record_donation", args=[reg.pk])
        self.client.post(url, {"donation_type": "whole_blood", "donated_at": local(timezone.now())})  # thiếu ml
        self.assertFalse(Donation.objects.exists())
        self.client.post(url, {"donation_type": "whole_blood", "donated_at": local(timezone.now()), "volume_ml": "900"})
        self.assertFalse(Donation.objects.exists())  # ngoài ngưỡng → cần xác nhận
        self.client.post(url, {"donation_type": "whole_blood", "donated_at": local(timezone.now()), "volume_ml": "350"})
        d = Donation.objects.get()
        reg.refresh_from_db()
        self.assertEqual((reg.status, d.confirmed_by_id, d.volume_ml), ("donated", self.dc.pk, 350))
        # Ghi lại lần 2 → bị chặn (một đơn tối đa một lượt confirmed)
        self.client.post(url, {"donation_type": "whole_blood", "donated_at": local(timezone.now()), "volume_ml": "350"})
        self.assertEqual(Donation.objects.count(), 1)
        # Hủy hiệu lực: bắt buộc lý do
        self.client.post(reverse("bloodbank:donation_manage", args=[d.pk]), {"action": "void", "reason": "",
                                                                            "target_status": "not_donated"})
        d.refresh_from_db()
        self.assertEqual(d.status, "confirmed")
        self.client.force_login(self.ha)
        self.client.post(reverse("bloodbank:donation_manage", args=[d.pk]), {"action": "void", "reason": "Ghi nhầm",
                                                                            "target_status": "not_donated"})
        d.refresh_from_db()
        reg.refresh_from_db()
        self.assertEqual((d.status, reg.status), ("voided", "not_donated"))
        self.client.force_login(self.donor)
        self.assertEqual(self.client.get(reverse("bloodbank:my_history")).context["summary"]["count"], 0)

    def test_staff_cannot_confirm_own_donation(self):
        c = f.campaign(self.h, start_offset_h=-2)
        reg = f.registration(c, self.dc, status="attended")
        self.client.force_login(self.dc)
        r = self.client.post(reverse("bloodbank:record_donation", args=[reg.pk]),
                             {"donation_type": "whole_blood", "donated_at": local(timezone.now()), "volume_ml": "350"},
                             follow=True)
        self.assertContains(r, "không được xác nhận lượt hiến của chính mình")
        self.assertFalse(Donation.objects.exists())

    def test_walk_in_creates_attended_registration(self):
        c = f.campaign(self.h, start_offset_h=-1)
        self.client.force_login(self.dc)
        self.client.post(reverse("bloodbank:walk_in", args=[c.pk]), {"lookup": self.donor.phone_display})
        reg = Registration.objects.get(campaign=c, donor=self.donor)
        self.assertEqual((reg.status, reg.source), ("attended", "walk_in"))

    def test_other_hospital_campaign_is_404(self):
        c = f.campaign(self.other_h)
        self.client.force_login(self.dc)
        self.assertEqual(self.client.get(reverse("bloodbank:hospital_campaign_detail", args=[c.pk])).status_code, 404)
        reg = f.registration(c, self.donor)
        self.client.post(reverse("bloodbank:registration_action", args=[reg.pk]), {"action": "approve"})
        reg.refresh_from_db()
        self.assertEqual(reg.status, "pending")

    def test_single_hospital_role_opens_every_hospital_screen(self):
        for u in (self.ha, self.dc, self.im):  # mọi nhân viên cùng một vai trò → cùng quyền
            self.client.force_login(u)
            for url in [reverse("bloodbank:hospital_campaign_create"), reverse("bloodbank:donor_lookup"),
                        reverse("bloodbank:stock_txn", args=["nhap"]), reverse("bloodbank:stock"),
                        reverse("bloodbank:hospital_staff"), reverse("bloodbank:hospital_audit")]:
                self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.force_login(self.donor)
        self.assertEqual(self.client.get(reverse("bloodbank:hospital_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("bloodbank:admin_users")).status_code, 404)
        self.assertTrue(AuditLog.objects.filter(action="access_denied").exists())


class InventoryFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.im = f.staff(cls.h)
        cls.spec = f.spec()

    def test_receive_issue_adjust_and_idempotency(self):
        self.client.force_login(self.im)
        url = reverse("bloodbank:stock_txn", args=["nhap"])
        data = {"product_spec_id": self.spec.pk, "blood_group": "O+", "quantity": "10", "idempotency_key": "k-1"}
        self.client.post(url, data)
        self.client.post(url, data)  # gửi lại cùng khóa → không ghi trùng
        stock = Stock.objects.get(hospital=self.h, blood_group="O+")
        self.assertEqual(stock.quantity_on_hand, 10)
        self.assertEqual(StockTxn.objects.count(), 1)
        r = self.client.post(url, {**data, "quantity": "5"}, follow=True)
        self.assertContains(r, "Mã thao tác đã được dùng")
        xuat = reverse("bloodbank:stock_txn", args=["xuat"])
        r = self.client.post(xuat, {"stock_id": stock.pk, "quantity": "11", "idempotency_key": "k-2"}, follow=True)
        self.assertContains(r, "Chỉ còn 10 đơn vị khả dụng")
        self.client.post(xuat, {"stock_id": stock.pk, "quantity": "4", "idempotency_key": "k-3"})
        dc = reverse("bloodbank:stock_txn", args=["dieu-chinh"])
        self.client.post(dc, {"stock_id": stock.pk, "direction": "decrease", "quantity": "1", "reason": "other",
                              "idempotency_key": "k-4"})  # lý do Khác cần ghi chú
        self.client.post(dc, {"stock_id": stock.pk, "direction": "count", "counted": "3", "reason": "stocktake_correction",
                              "idempotency_key": "k-5"})
        stock.refresh_from_db()
        self.assertEqual(stock.quantity_on_hand, 3)
        total = sum(StockTxn.objects.filter(stock=stock).values_list("quantity_change", flat=True))
        self.assertEqual(total, stock.quantity_on_hand)  # đối soát: SUM(change) = on_hand
        self.assertEqual(self.client.get(reverse("bloodbank:stock_ledger")).status_code, 200)

    def test_optimistic_lock_on_stock_settings(self):
        inv.receive(self.im.staffs.get(), self.spec.pk, "A+", 5, "r1")
        stock = Stock.objects.get(blood_group="A+")
        self.client.force_login(self.im)
        url = reverse("bloodbank:stock_settings", args=[stock.pk])
        self.client.post(url, {"shareable_quantity": "3", "min_stock_level": "2", "version": stock.version})
        r = self.client.post(url, {"shareable_quantity": "4", "min_stock_level": "2", "version": stock.version}, follow=True)
        self.assertContains(r, "vừa được người khác thay đổi")
        stock.refresh_from_db()
        self.assertEqual(stock.shareable_quantity, 3)

    def test_shortage_formula(self):
        staff = self.im.staffs.get()
        inv.receive(staff, self.spec.pk, "O-", 2, "r2")
        inv.save_demand(staff, {"blood_group": "O-", "product_spec_id": self.spec.pk, "required_quantity": 3})
        inv.save_demand(staff, {"blood_group": "O-", "product_spec_id": self.spec.pk, "required_quantity": 4})
        row = inv.shortages(self.h)[0]
        self.assertEqual((row["required"], row["available"], row["shortage"]), (7, 2, 5))  # trừ khả dụng một lần


class TransferFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.req_h, cls.sup_h = f.hospital(), f.hospital()
        cls.req_im = f.staff(cls.req_h)
        cls.sup_im = f.staff(cls.sup_h)
        cls.sup_ha = f.staff(cls.sup_h)
        cls.spec = f.spec()
        staff = cls.sup_im.staffs.get()
        inv.receive(staff, cls.spec.pk, "O-", 6, "seed")
        st = Stock.objects.get(hospital=cls.sup_h)
        inv.update_stock_settings(staff, st.pk, 4, 0, st.version)

    def stock(self, h):
        return Stock.objects.filter(hospital=h, blood_group="O-").first()

    def test_full_transfer_flow(self):
        self.client.force_login(self.req_im)
        r = self.client.get(reverse("bloodbank:source_search"), {"blood_group": "O-", "product": self.spec.product_id})
        self.assertEqual([row["can_support"] for row in r.context["rows"]], [4])  # chỉ số chia sẻ hiệu lực
        self.assertNotContains(r, "Hiện có")
        self.client.post(reverse("bloodbank:support_request_create"), {
            "blood_group": "O-", "product_spec_id": self.spec.pk, "quantity_needed": "3", "priority": "urgent",
            "supplier": [self.sup_h.pk], f"qty_{self.sup_h.pk}": "3",
        })
        req = HospitalRequest.objects.get()
        self.assertRegex(req.request_code, r"^HR-\d{8}-0001$")
        offer = req.offers.get()
        # Bên cấp: không được chấp thuận vượt còn thiếu
        self.client.force_login(self.sup_im)
        act = reverse("bloodbank:offer_action", args=[offer.pk])
        r = self.client.post(act, {"action": "accept", "quantity": "5"}, follow=True)
        self.assertContains(r, "chỉ còn thiếu 3")
        self.client.post(act, {"action": "accept", "quantity": "3"})
        s = self.stock(self.sup_h)
        self.assertEqual((s.quantity_on_hand, s.quantity_reserved), (6, 3))
        req.refresh_from_db()
        self.assertEqual(req.status, "in_progress")
        self.client.post(act, {"action": "dispatch", "idempotency_key": "d-1"})
        self.client.post(act, {"action": "dispatch", "idempotency_key": "d-1"})  # bấm lặp
        s.refresh_from_db()
        self.assertEqual((s.quantity_on_hand, s.quantity_reserved), (3, 0))
        # Bên nhận xác nhận r ≤ q
        self.client.force_login(self.req_im)
        url = reverse("bloodbank:support_request_action", args=[req.pk])
        r = self.client.post(url, {"action": "receive", "offer_id": offer.pk, "quantity_received": "4",
                                   "idempotency_key": "rcv-1"}, follow=True)
        self.assertContains(r, "không được vượt số đã xuất")
        self.client.post(url, {"action": "receive", "offer_id": offer.pk, "quantity_received": "2",
                               "idempotency_key": "rcv-1", "returned": "1"})
        req.refresh_from_db()
        offer.refresh_from_db()
        self.assertEqual((offer.status, offer.quantity_received, req.status), ("completed", 2, "partially_fulfilled"))
        self.assertEqual(self.stock(self.req_h).quantity_on_hand, 2)
        self.assertEqual(self.stock(self.sup_h).quantity_on_hand, 4)  # 1 đơn vị quay về bên cấp
        self.client.post(url, {"action": "close"})
        req.refresh_from_db()
        self.assertIsNotNone(req.closed_at)

    def test_cancel_request_releases_reservation(self):
        from bloodbank.services import transfers as trf

        req = trf.create_request(self.req_im.staffs.get(), {"blood_group": "O-", "product_spec_id": self.spec.pk,
                                                            "quantity_needed": 2}, [(self.sup_h.pk, 2)])
        offer = req.offers.get()
        trf.accept_offer(self.sup_im.staffs.get(), offer.pk, 2)
        self.assertEqual(self.stock(self.sup_h).quantity_reserved, 2)
        self.client.force_login(self.req_im)
        self.client.post(reverse("bloodbank:support_request_action", args=[req.pk]), {"action": "cancel"})
        req.refresh_from_db()
        self.assertEqual((req.status, self.stock(self.sup_h).quantity_reserved), ("cancelled", 0))
        self.assertIsNotNone(req.closed_at)

    def test_self_supply_and_supplier_isolation(self):
        from bloodbank.services import transfers as trf

        with self.assertRaises(BusinessError) as ctx:
            trf.create_request(self.req_im.staffs.get(), {"blood_group": "O-", "product_spec_id": self.spec.pk,
                                                          "quantity_needed": 1}, [(self.req_h.pk, 1)])
        self.assertEqual(ctx.exception.code, "ERR-HRQ-SELF-SUPPLY")
        req = trf.create_request(self.req_im.staffs.get(), {"blood_group": "O-", "product_spec_id": self.spec.pk,
                                                            "quantity_needed": 1}, [(self.sup_h.pk, 1)])
        offer = req.offers.get()
        self.client.force_login(self.req_im)  # bên yêu cầu không mở được màn hình của bên cấp
        self.assertEqual(self.client.get(reverse("bloodbank:offer_detail", args=[offer.pk])).status_code, 404)

    def test_supplier_reports_delivery_failure(self):
        from bloodbank.services import transfers as trf

        req = trf.create_request(self.req_im.staffs.get(), {"blood_group": "O-", "product_spec_id": self.spec.pk,
                                                            "quantity_needed": 2}, [(self.sup_h.pk, 2)])
        offer = req.offers.get()
        trf.accept_offer(self.sup_im.staffs.get(), offer.pk, 2)
        trf.dispatch_offer(self.sup_im.staffs.get(), offer.pk, "dx")
        act = reverse("bloodbank:offer_action", args=[offer.pk])
        self.client.force_login(self.req_im)  # bên yêu cầu không báo thất bại thay bên cấp được
        self.client.post(act, {"action": "fail", "reason": "Hỏng xe", "returned_qty": "2", "idempotency_key": "f0"})
        offer.refresh_from_db()
        self.assertEqual(offer.status, "in_transit")
        self.client.force_login(self.sup_ha)
        self.client.post(act, {"action": "fail", "reason": "Hỏng xe", "returned_qty": "2", "idempotency_key": "f1"})
        offer.refresh_from_db()
        self.assertEqual(offer.status, "failed")
        self.assertEqual(self.stock(self.sup_h).quantity_on_hand, 6)


class PatientRequestHospitalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h, cls.h2 = f.hospital(), f.hospital()
        cls.im = f.staff(cls.h)
        cls.im2 = f.staff(cls.h2)
        cls.member = f.user()
        cls.spec = f.spec()
        from bloodbank.services import patients

        cls.prq = patients.submit(cls.member, {"consent": True, "hospital_id": cls.h.pk, "quantity_units": 2,
                                               "blood_group": "B+", "blood_product_id": f.spec().product_id,
                                               "contact_name": "A", "contact_phone": "0905999888",
                                               "patient_name": "Nguyễn Bệnh Nhân"})

    def test_list_masks_name_detail_logs_view(self):
        self.client.force_login(self.im)
        r = self.client.get(reverse("bloodbank:hospital_patient_requests"))
        self.assertNotContains(r, "Nguyễn Bệnh Nhân")
        r = self.client.get(reverse("bloodbank:hospital_patient_request_detail", args=[self.prq.pk]))
        self.assertContains(r, "Nguyễn Bệnh Nhân")
        self.assertTrue(AuditLog.objects.filter(action="view_sensitive", entity_id=self.prq.pk).exists())
        self.client.force_login(self.im2)  # bệnh viện khác
        self.assertEqual(self.client.get(reverse("bloodbank:hospital_patient_request_detail",
                                                 args=[self.prq.pk])).status_code, 404)

    def test_issue_requires_verification(self):
        staff = self.im.staffs.get()
        inv.receive(staff, self.spec.pk, "B+", 5, "pr-r")
        stock = Stock.objects.get(hospital=self.h)
        with self.assertRaises(BusinessError) as ctx:
            inv.issue(staff, stock.pk, 1, "pr-i0", patient_request_id=self.prq.pk)
        self.assertEqual(ctx.exception.code, "ERR-PRQ-NOT-VERIFIED")
        self.client.force_login(self.im)
        url = reverse("bloodbank:hospital_patient_request_action", args=[self.prq.pk])
        self.client.post(url, {"action": "verify", "blood_group": "X+"})  # nhóm máu không hợp lệ
        self.prq.refresh_from_db()
        self.assertEqual(self.prq.status, "submitted")
        self.client.post(url, {"action": "verify", "blood_group": "B+"})
        self.client.post(reverse("bloodbank:stock_txn", args=["xuat"]), {
            "stock_id": stock.pk, "quantity": "2", "idempotency_key": "pr-i1", "patient_request_id": self.prq.pk})
        self.prq.refresh_from_db()
        self.assertEqual(self.prq.status, "processing")
        self.client.post(url, {"action": "fulfill", "resolution_note": "Đã cấp 2 đơn vị"})
        self.prq.refresh_from_db()
        self.assertEqual(self.prq.status, "fulfilled")
        self.assertTrue(Notification.objects.filter(user=self.member, type="patient_request_status").exists())


class AdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = f.user(role="admin", email="adm@test.vn")
        cls.h = f.hospital()
        cls.ha = f.staff(cls.h)

    def test_admin_creates_hospital_account_and_staff_list_is_read_only(self):
        self.client.force_login(self.admin)
        url = reverse("bloodbank:admin_hospital_edit", args=[self.h.pk])
        self.client.post(url, {"form": "staff_add", "email": "moi@bv.vn", "full_name": "Nhân Viên Mới",
                               "password": "Benhvien@2026"})
        u = User.objects.get(email="moi@bv.vn")
        self.assertEqual(u.role, "hospital")
        self.assertTrue(u.staffs.filter(hospital=self.h, is_active=True).exists())
        # Tài khoản Người dùng không được dùng làm tài khoản bệnh viện
        member = f.user(email="nguoidung@test.vn")
        r = self.client.post(url, {"form": "staff_add", "email": member.email}, follow=True)
        self.assertContains(r, "phải là tài khoản riêng")
        self.assertFalse(member.staffs.exists())
        # Thu hồi phân công
        st = u.staffs.get()
        self.client.post(url, {"form": "staff_update", "staff_id": st.pk, "op": "deactivate"})
        st.refresh_from_db()
        self.assertFalse(st.is_active)
        # Bệnh viện chỉ xem danh sách nhân viên, không có thao tác thêm/thu hồi
        self.client.force_login(self.ha)
        r = self.client.get(reverse("bloodbank:hospital_staff"))
        self.assertContains(r, "Nhân Viên Mới")
        self.assertNotContains(r, "Thu hồi")

    def test_staff_belongs_to_single_hospital(self):
        # BR-03, BR-04: nhân viên đang làm ở bệnh viện này không được gán thêm vào bệnh viện khác
        other = f.hospital()
        self.client.force_login(self.admin)
        url = reverse("bloodbank:admin_hospital_edit", args=[other.pk])
        r = self.client.post(url, {"form": "staff_add", "email": self.ha.email}, follow=True)
        self.assertContains(r, "đang làm việc tại bệnh viện khác")
        self.assertEqual(list(self.ha.staffs.values_list("hospital_id", flat=True)), [self.h.pk])
        # Thu hồi phân công cũ rồi gán lại → chuyển sang bệnh viện mới, vẫn chỉ một hồ sơ phân công
        st = self.ha.staffs.get()
        self.client.post(reverse("bloodbank:admin_hospital_edit", args=[self.h.pk]),
                         {"form": "staff_update", "staff_id": st.pk, "op": "deactivate"})
        self.client.post(url, {"form": "staff_add", "email": self.ha.email})
        st = self.ha.staffs.get()
        self.assertEqual((st.hospital_id, st.is_active), (other.pk, True))

    def test_admin_locks_user_and_manages_catalog(self):
        u = f.user()
        self.client.force_login(self.admin)
        self.client.post(reverse("bloodbank:admin_users"), {"action": "lock", "user_id": u.pk})
        u.refresh_from_db()
        self.assertEqual(u.status, "locked")
        self.client.post(reverse("bloodbank:catalog"), {"action": "add_product", "code": "gran", "name": "Bạch cầu hạt",
                                                       "kind": "component"})
        from bloodbank.models import Product

        p = Product.objects.get(code="GRAN")
        self.client.post(reverse("bloodbank:catalog"), {"action": "add_spec", "product_id": p.pk, "code": "std",
                                                       "name": "Tiêu chuẩn"})
        self.client.post(reverse("bloodbank:catalog"), {"action": "add_spec", "product_id": p.pk, "code": "big",
                                                       "name": "Lớn", "is_default": "on"})
        self.assertEqual(list(p.specs.filter(is_default=True).values_list("code", flat=True)), ["BIG"])

    def test_hospital_cannot_deactivate_with_open_campaign(self):
        f.campaign(self.h, status="open")
        self.client.force_login(self.admin)
        r = self.client.post(reverse("bloodbank:admin_hospital_edit", args=[self.h.pk]),
                             {"form": "status", "status": "inactive"}, follow=True)
        self.assertContains(r, "chưa thể ngừng hoạt động")
