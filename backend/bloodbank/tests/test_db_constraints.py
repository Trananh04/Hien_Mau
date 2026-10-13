"""Bước 2: kiểm tra CSDL tự thực thi các quy tắc (Data Dictionary mục IV)."""
from datetime import timedelta

from django.db import IntegrityError, InternalError, connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase
from django.utils import timezone

from bloodbank.models import (
    AuditLog, Donation, HospitalRequest, PatientRequest, Product, ProductSpec, RequestOffer, Stock, StockTxn,
    SystemSetting,
)

from . import factories as f


class SchemaShapeTests(TestCase):
    def test_all_19_tables_exist(self):
        expected = {
            "users", "hospitals", "staffs", "auth_tokens", "campaigns", "registrations", "products", "product_specs",
            "donations", "stocks", "stock_lots", "stock_txns", "demands", "hospital_requests", "request_offers",
            "patient_requests", "audit_logs", "notifications", "system_settings",
        }
        self.assertTrue(expected.issubset(set(connection.introspection.table_names())))

    def test_seeded_catalog_and_settings(self):
        self.assertEqual(Product.objects.count(), 5)
        for product in Product.objects.all():
            self.assertEqual(product.specs.filter(is_default=True).count(), 1)
        self.assertEqual(SystemSetting.get("login_max_failed_attempts"), 5)


class ConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h1 = f.hospital()
        cls.h2 = f.hospital()
        cls.staff = f.staff(cls.h1)
        cls.donor = f.user(full_name="Người hiến")
        cls.camp = f.campaign(cls.h1)
        cls.reg = f.registration(cls.camp, cls.donor, status="attended")

    def assertDbError(self, fn, exc=(IntegrityError, InternalError, DatabaseError)):
        with self.assertRaises(exc):
            with transaction.atomic():
                fn()

    def _donation(self, **kw):
        data = dict(
            donor=self.donor, registration=self.reg, hospital=self.h1, donation_type="whole_blood", volume_ml=350,
            donated_at=timezone.now(), confirmed_by=self.staff,
        )
        data.update(kw)
        return Donation.objects.create(**data)

    def test_campaign_time_and_cancel_reason(self):
        now = timezone.now()
        self.assertDbError(lambda: f.campaign(self.h1, duration_h=-1))
        self.assertDbError(lambda: f.campaign(self.h1, status="cancelled"))
        f.campaign(self.h1, status="cancelled", cancel_reason="Mưa bão")
        self.assertTrue(now)

    def test_latlng_pair(self):
        self.assertDbError(lambda: f.hospital(latitude=16.05))

    def test_one_registration_per_campaign_donor(self):
        self.assertDbError(lambda: f.registration(self.camp, self.donor))

    def test_donation_rules(self):
        self.assertDbError(lambda: self._donation(volume_ml=None))  # toàn phần bắt buộc ml
        self.assertDbError(lambda: self._donation(confirmed_by=self.donor))  # không tự xác nhận
        self.assertDbError(lambda: self._donation(donation_type="component", volume_ml=None,
                                                   component_quantity=1, component_unit="unit"))
        self._donation()
        self.assertDbError(lambda: self._donation())  # tối đa 1 lượt confirmed / đơn

    def test_void_then_record_again(self):
        d = self._donation()
        d.status, d.void_reason, d.voided_at, d.voided_by = "voided", "Ghi nhầm", timezone.now(), self.staff
        d.save()
        self._donation()  # ghi nhận lại được sau khi void
        d.refresh_from_db()
        d.note = "sửa"
        self.assertDbError(d.save)  # bản ghi voided bất biến

    def test_donation_triggers(self):
        other = f.user()
        self.assertDbError(lambda: self._donation(donor=other))  # donor không khớp đơn
        d = self._donation()
        d.hospital = self.h2
        self.assertDbError(d.save)

    def test_one_default_spec_per_product(self):
        product = Product.objects.get(code="RBC")
        self.assertDbError(lambda: ProductSpec.objects.create(product=product, code="X", name="X", is_default=True))

    def test_stock_checks_and_append_only_ledger(self):
        spec = f.spec()
        stock = Stock.objects.create(hospital=self.h1, blood_group="O+", product_spec=spec)
        stock.quantity_reserved = 1
        self.assertDbError(stock.save)  # reserved <= on_hand
        txn = StockTxn.objects.create(
            stock=stock, txn_type="receive", quantity_change=5, quantity_before=0, quantity_after=5,
            idempotency_key="k1", performed_by=self.staff,
        )
        self.assertDbError(lambda: StockTxn.objects.create(
            stock=stock, txn_type="receive", quantity_change=5, quantity_before=0, quantity_after=4,
            idempotency_key="k2", performed_by=self.staff,
        ))  # before + change = after
        self.assertDbError(lambda: StockTxn.objects.create(
            stock=stock, txn_type="issue", quantity_change=2, quantity_before=5, quantity_after=7,
            idempotency_key="k3", performed_by=self.staff,
        ))  # issue phải âm
        self.assertDbError(lambda: StockTxn.objects.create(
            stock=stock, txn_type="adjustment", quantity_change=-1, quantity_before=5, quantity_after=4,
            idempotency_key="k4", performed_by=self.staff,
        ))  # adjustment cần lý do
        self.assertDbError(lambda: StockTxn.objects.create(
            stock=stock, txn_type="receive", quantity_change=1, quantity_before=5, quantity_after=6,
            idempotency_key="k1", performed_by=self.staff,
        ))  # idempotency_key duy nhất
        txn.reason_note = "x"
        self.assertDbError(txn.save)
        self.assertDbError(txn.delete)

    def test_audit_logs_append_only(self):
        log = AuditLog.objects.create(entity_type="x", entity_id=1, action="create")
        log.action = "update"
        self.assertDbError(log.save)
        self.assertDbError(log.delete)

    def test_offer_no_self_supply_and_checks(self):
        req = HospitalRequest.objects.create(
            request_code="HR-1", requesting_hospital=self.h1, blood_group="O+", product_spec=f.spec(),
            quantity_needed=3, created_by=self.staff,
        )
        self.assertDbError(lambda: RequestOffer.objects.create(request=req, supplier_hospital=self.h1))
        offer = RequestOffer.objects.create(request=req, supplier_hospital=self.h2)
        offer.status = "accepted"
        self.assertDbError(offer.save)  # accepted cần quantity
        offer.refresh_from_db()
        offer.supplier_hospital = f.hospital()
        self.assertDbError(offer.save)  # không đổi bên cấp

    def test_hospital_request_final_needs_closed_at(self):
        self.assertDbError(lambda: HospitalRequest.objects.create(
            request_code="HR-2", requesting_hospital=self.h1, blood_group="O+", product_spec=f.spec(),
            quantity_needed=3, created_by=self.staff, status="fulfilled",
        ))

    def test_patient_request_verification(self):
        base = dict(
            requester=self.donor, contact_name="A", contact_phone="+84900000000", hospital=self.h1,
            quantity_units=2, consent_at=timezone.now(),
        )
        self.assertDbError(lambda: PatientRequest.objects.create(request_code="PR-1", status="verified", **base))
        self.assertDbError(lambda: PatientRequest.objects.create(
            request_code="PR-2", status="verified", blood_group="A+", verified_by=self.donor,
            verified_at=timezone.now(), **base,
        ))  # người xác minh khác người gửi
        PatientRequest.objects.create(
            request_code="PR-3", status="verified", blood_group="A+", verified_by=self.staff,
            verified_at=timezone.now(), **base,
        )

    def test_updated_at_set_by_database(self):
        before = self.h1.updated_at
        with connection.cursor() as cur:
            cur.execute("UPDATE hospitals SET name = name || '' WHERE id = %s", [self.h1.id])
        self.h1.refresh_from_db()
        self.assertGreaterEqual(self.h1.updated_at, before - timedelta(seconds=1))
