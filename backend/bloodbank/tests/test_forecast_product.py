"""Dự báo AI thành sản phẩm: nhu cầu lịch sử không cộng trùng, phiếu xuất gắn ca mổ đã khai, phiên bản + chốt chặn
+ quay lại, tự chọn dữ liệu thật / mô phỏng, lưu dự báo hằng ngày và đo sai số thật, trang Quản trị → Dự báo AI."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from bloodbank.models import AuditLog, Demand, ForecastSnapshot, PatientRequest, Stock, StockTxn, SystemSetting, Staff
from bloodbank.services import forecast as fc
from bloodbank.services import inventory as inv
from bloodbank.services.common import BusinessError
from bloodbank.services.forecast_ml import history, monitor, predict, registry, simulate, training

from . import factories as f


def txn(stock, user, qty, days_ago, **kw):
    return StockTxn.objects.create(stock=stock, txn_type="issue", quantity_change=-qty, quantity_before=100,
                                   quantity_after=100 - qty, performed_by=user, occurred_at=timezone.now()
                                   - timedelta(days=days_ago), idempotency_key=f"t-{StockTxn.objects.count()}", **kw)


class TmpModelDir:
    """Mỗi test có thư mục mô hình riêng."""

    def setUp(self):
        super().setUp()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        override = override_settings(FORECAST_MODEL_DIR=self.dir)
        override.enable()
        self.addCleanup(override.disable)
        predict._cache["mtime"] = None

    def small_sim(self, days=150):
        path = self.dir / "sim" / "demand.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = simulate.simulate(days=days, seed=4)
        raw[raw["hospital"].isin(["SIM-LON-1", "SIM-VUA-1"])].to_csv(path, index=False)
        return path


class DemandHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.user = f.staff(cls.h)
        cls.staff = Staff.objects.get(user=cls.user)
        cls.spec = f.spec()
        cls.stock = Stock.objects.create(hospital=cls.h, blood_group="O+", product_spec=cls.spec,
                                         quantity_on_hand=20)
        cls.demand = Demand.objects.create(hospital=cls.h, blood_group="O+", product_spec=cls.spec,
                                           required_quantity=4, needed_by=timezone.now() + timedelta(days=3))
        cls.prq = PatientRequest.objects.create(
            requester=f.user(), contact_name="Người nhà", contact_phone="0905000111", hospital=cls.h,
            blood_group="O+", blood_product=cls.spec.product, quantity_units=3, consent_at=timezone.now(),
            request_code="PR-FC-0001", status="verified", verified_at=timezone.now() - timedelta(days=1),
            verified_by=cls.user)

    def test_daily_demand_counts_each_need_once(self):
        txn(self.stock, self.user, 2, 1)                                  # dùng thường ngày
        txn(self.stock, self.user, 5, 1, demand=self.demand)              # cho ca đã khai → không tính
        txn(self.stock, self.user, 1, 1, patient_request=self.prq)        # đã tính qua yêu cầu (3 đơn vị)
        today = timezone.localdate()
        arr = history.recent(self.h, today, 3)[("O+", self.spec.pk)]
        self.assertEqual(list(arr), [0, 2 + 3, 0])

    def test_issue_for_demand_validates_and_fulfils(self):
        other = Stock.objects.create(hospital=self.h, blood_group="A+", product_spec=self.spec, quantity_on_hand=9)
        with self.assertRaises(BusinessError):
            inv.issue(self.staff, other.pk, 1, "k-wrong", demand_id=self.demand.pk)       # sai nhóm máu
        inv.issue(self.staff, self.stock.pk, 3, "k-1", demand_id=self.demand.pk)
        self.demand.refresh_from_db()
        self.assertEqual(self.demand.status, "active")
        row = {r["blood_group"]: r for r in fc.forecast(self.h)}["O+"]
        self.assertEqual(row["planned"], 1)                                # 4 đã khai − 3 đã xuất
        inv.issue(self.staff, self.stock.pk, 1, "k-2", demand_id=self.demand.pk)
        self.demand.refresh_from_db()
        self.assertEqual(self.demand.status, "fulfilled")
        self.assertEqual(StockTxn.objects.filter(demand=self.demand).count(), 2)
        with self.assertRaises(BusinessError):
            inv.issue(self.staff, self.stock.pk, 1, "k-3", demand_id=self.demand.pk)       # ca đã đóng

    def test_stock_form_offers_planned_demands(self):
        self.client.force_login(self.user)
        page = self.client.get("/benh-vien/kho/phieu/xuat/")
        self.assertContains(page, 'name="demand_id"')


class RegistryTests(TmpModelDir, TestCase):
    def meta(self, xgb, bias=0.0, b0=0.5, synthetic=True):
        return {"synthetic": synthetic, "backtest": [{"model": "B0", "wape": b0}, {"model": "B1", "wape": 0.6},
                                                     {"model": "XGB", "wape": xgb, "bias": bias}]}

    def test_guard(self):
        self.assertEqual(registry.guard(self.meta(0.4)), (True, []))
        self.assertFalse(registry.guard(self.meta(0.55))[0])                       # không thắng baseline
        self.assertFalse(registry.guard(self.meta(0.4, bias=-0.08))[0])            # dự báo thiếu > 5%
        self.assertFalse(registry.guard(self.meta(0.3), current={"synthetic": False})[0])   # thật → mô phỏng
        self.assertTrue(registry.guard(self.meta(0.3, synthetic=False), current={"synthetic": True})[0])

    def test_train_versions_promote_and_rollback(self):
        self.small_sim()
        first = training.run(source="auto", log=lambda *_: None)
        self.assertEqual(first["source"], "sim")                                   # chưa có sổ kho → mô phỏng
        if first["promoted"]:
            self.assertEqual(predict.loaded()[1]["version"], first["version"])
        second = training.run(source="csv", force=True, log=lambda *_: None)
        self.assertTrue(second["promoted"])
        self.assertEqual(predict.loaded()[1]["version"], second["version"])
        self.assertEqual(len(registry.versions()), 2)
        registry.activate(first["version"])                                         # quay lại bản cũ
        self.assertEqual(predict.loaded()[1]["version"], first["version"])
        self.assertTrue((self.dir / "versions" / second["version"] / "evaluation.csv").exists())
        self.assertEqual(registry.last_run()["version"], second["version"])

    def test_db_source_requires_enough_history(self):
        with self.assertRaises(training.NotEnoughData):
            training.load("db", log=lambda *_: None)


class MonitorTests(TmpModelDir, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.user = f.staff(cls.h)
        cls.spec = f.spec()
        cls.stock = Stock.objects.create(hospital=cls.h, blood_group="O+", product_spec=cls.spec, quantity_on_hand=50)
        for d in range(40, 0, -1):
            txn(cls.stock, cls.user, 2, d)

    def test_snapshots_once_per_day_and_accuracy(self):
        n = monitor.record_snapshots()
        self.assertEqual(n, 14)
        self.assertEqual(monitor.record_snapshots(), 0)                             # cùng ngày → không trùng
        snap = ForecastSnapshot.objects.get(h=1)
        self.assertEqual(snap.method, "avg")
        self.assertAlmostEqual(snap.baseline, 2.0)
        # Giả sử dự báo lập từ 10 ngày trước, nay đã có thực tế (2 đơn vị/ngày) → sai số trung bình = 0
        ForecastSnapshot.objects.update(origin=timezone.localdate() - timedelta(days=11),
                                        target_date=timezone.localdate() - timedelta(days=5))
        weeks = monitor.accuracy()
        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0]["avg"], 0)
        self.assertIsNone(weeks[0]["ai"])

    @override_settings(FORECAST_SCHEDULED_TRAINING=True)
    def test_retrain_skipped_without_real_data_and_runs_on_request(self):
        self.small_sim()
        training.run(source="csv", force=True, log=lambda *_: None)
        registry.record_run({"version": None})
        self.assertIsNone(monitor.maybe_retrain())                                  # chưa đến hạn
        registry._write(self.dir / "last_run.json", {"at": "2020-01-01T00:00:00+00:00"})
        self.assertEqual(monitor.maybe_retrain(), "skipped")                         # mô phỏng → học lại vô ích
        registry.request_training()
        self.assertIn(monitor.maybe_retrain(), ("promoted", "kept"))
        self.assertFalse(registry.training_requested())

    def test_scheduled_training_off_in_tests_by_default(self):
        registry.request_training()
        self.assertIsNone(monitor.retrain_due())


class AdminPageTests(TmpModelDir, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = f.user(role="admin")

    def test_page_toggle_rollback_and_train_request(self):
        self.small_sim()
        a = training.run(source="csv", force=True, log=lambda *_: None)
        b = training.run(source="csv", force=True, log=lambda *_: None)
        self.client.force_login(self.admin)
        page = self.client.get("/quan-tri/du-bao-ai/")
        self.assertContains(page, b["version"])
        self.assertContains(page, "Mô phỏng")
        self.client.post("/quan-tri/du-bao-ai/", {"action": "ai", "value": "on"})
        self.assertTrue(SystemSetting.get("forecast_ai_enabled"))
        self.client.post("/quan-tri/du-bao-ai/", {"action": "activate", "version": a["version"]})
        self.assertEqual(registry.active_meta()["version"], a["version"])
        self.client.post("/quan-tri/du-bao-ai/", {"action": "activate", "version": "../../khong-co"})
        self.assertEqual(registry.active_meta()["version"], a["version"])
        self.client.post("/quan-tri/du-bao-ai/", {"action": "train"})
        self.assertTrue(registry.training_requested())
        self.assertEqual(AuditLog.objects.filter(entity_type="forecast_model").count(), 2)

    def test_hospital_staff_cannot_open(self):
        h = f.hospital()
        self.client.force_login(f.staff(h))
        self.assertNotEqual(self.client.get("/quan-tri/du-bao-ai/").status_code, 200)
