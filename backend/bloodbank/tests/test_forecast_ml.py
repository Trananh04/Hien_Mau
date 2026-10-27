"""AI dự báo nhu cầu: mô phỏng (tái lập được, đúng tham số), đặc trưng không rò rỉ tương lai, baseline đúng công thức,
huấn luyện + lưu/tải, trang Dự báo thiếu hụt dùng AI khi bật và quay về trung bình khi không đủ điều kiện."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from bloodbank.models import Stock, StockTxn, SystemSetting
from bloodbank.services import forecast as fc
from bloodbank.services.forecast_ml import features, model, params, predict, simulate

from . import factories as f


def series(values, start="2026-01-01"):
    return pd.DataFrame({"date": pd.date_range(start, periods=len(values), freq="D"), "demand": values})


class SimulateTests(TestCase):
    def test_reproducible_and_matches_parameters(self):
        a = simulate.simulate(days=120, end=pd.Timestamp("2026-06-30").date(), seed=1)
        b = simulate.simulate(days=120, end=pd.Timestamp("2026-06-30").date(), seed=1)
        pd.testing.assert_frame_equal(a, b)                              # cùng seed → cùng dữ liệu
        self.assertTrue((a["is_synthetic"] == 1).all())
        self.assertTrue(((a["issued"] + a["unmet"]) == a["demand"]).all())
        big = simulate.simulate(days=730, seed=3)
        share = big.groupby(big["blood_group"].str[:-1])["demand"].sum() / big["demand"].sum()
        for abo, expected in params.value("abo_share").items():
            self.assertAlmostEqual(share[abo], expected, delta=0.03)
        weekday = big.groupby(big["date"].dt.dayofweek)["demand"].mean()
        self.assertGreater(weekday[0], weekday[6])                       # thứ 2 > chủ nhật (giả định)

    def test_every_parameter_has_a_source(self):
        for key, p in params.SIM_PARAMS.items():
            self.assertTrue(p.get("source"), key)


class FeatureTests(TestCase):
    def test_no_future_leakage(self):
        """Đổi nhu cầu SAU ngày gốc không được làm đổi đặc trưng tại ngày gốc."""
        values = np.arange(60) % 5
        base = features.build(series(values), simulate.tet_flags, with_target=False, origins=[40])
        changed = values.copy()
        changed[41:] = 99
        after = features.build(series(changed), simulate.tet_flags, with_target=False, origins=[40])
        cols = [c for c in features.FEATURES if c != "blood_group"]
        pd.testing.assert_frame_equal(base[cols].reset_index(drop=True), after[cols].reset_index(drop=True))

    def test_values_and_target(self):
        values = np.arange(40, dtype=float)
        rows = features.build(series(values), simulate.tet_flags, with_target=True, origins=[30])
        h1 = rows[rows["h"] == 1].iloc[0]
        self.assertEqual(h1["last_1"], 30)
        self.assertEqual(h1["last_7"], 24)
        self.assertEqual(h1["mean_28"], np.mean(values[3:31]))
        self.assertEqual(h1["target"], 31)
        # Cùng thứ với ngày dự báo (ngày 31): 4 ngày gần nhất ≤ 30 cùng thứ là 24, 17, 10, 3
        self.assertEqual(h1["same_weekday_4"], np.mean([24, 17, 10, 3]))
        self.assertEqual(sorted(rows["h"]), list(range(1, 10)))         # h > 9 vượt quá dữ liệu → bỏ

    def test_tet_flag(self):
        days = pd.date_range("2026-02-14", "2026-02-22")
        self.assertEqual(list(simulate.tet_flags(days)), [0, 1, 1, 1, 1, 1, 1, 1, 0])   # 15/2 → 21/2


class TrainTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = Path(tempfile.mkdtemp())
        raw = simulate.simulate(days=200, seed=5)
        raw["series"] = raw["hospital"]
        daily = features.fill_days(raw[raw["hospital"].isin(["SIM-LON-1", "SIM-VUA-1"])]
                                   [["date", "series", "blood_group", "demand"]])
        cls.examples = features.build_all(daily, simulate.tet_flags)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def test_backtest_trains_only_on_past_and_reports_all_models(self):
        summary, by_h, folds = model.backtest(self.examples, folds=2, step=14)
        self.assertEqual(list(summary["model"]), ["B0", "B1", "XGB"])
        self.assertEqual(len(folds), 2)
        self.assertEqual(sorted(by_h["h"]), list(range(1, 15)))
        self.assertTrue((summary["wape"] > 0).all())

    def test_save_load_roundtrip(self):
        trained = model.train(self.examples)
        model.save(trained, self.dir, {"synthetic": True})
        loaded, meta = model.load(self.dir)
        rows = self.examples.head(20)
        np.testing.assert_allclose(loaded.predict(rows), trained.predict(rows), rtol=1e-5)
        self.assertEqual(loaded.best_iteration, trained.best_iteration)
        self.assertTrue(meta["synthetic"])
        self.assertEqual(model.load(self.dir / "khong-co"), (None, None))


class ForecastPageTests(TestCase):
    """Dòng đủ 28 ngày lịch sử dùng AI khi bật; dòng mới vẫn dùng trung bình 28 ngày."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.user = f.staff(cls.h)
        cls.spec = f.spec()
        now = timezone.now()
        cls.old = Stock.objects.create(hospital=cls.h, blood_group="O+", product_spec=cls.spec, quantity_on_hand=10)
        cls.new = Stock.objects.create(hospital=cls.h, blood_group="A+", product_spec=cls.spec, quantity_on_hand=10)
        for stock, days in ((cls.old, 35), (cls.new, 10)):
            for d in range(days, 0, -1):
                StockTxn.objects.create(stock=stock, txn_type="issue", quantity_change=-1, quantity_before=11,
                                        quantity_after=10, performed_by=cls.user, idempotency_key=f"{stock.pk}-{d}",
                                        occurred_at=now - timedelta(days=d))

    def setUp(self):
        cache.clear()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        raw = simulate.simulate(days=120, seed=2)
        raw["series"] = raw["hospital"]
        examples = features.build_all(features.fill_days(raw[["date", "series", "blood_group", "demand"]]),
                                      simulate.tet_flags)
        model.save(model.train(examples), self.dir, {"synthetic": True,
                                                     "backtest": [{"model": "XGB", "wape": 0.4},
                                                                  {"model": "B0", "wape": 0.5}]})
        predict._cache["mtime"] = None

    def rows(self):
        with override_settings(FORECAST_MODEL_DIR=self.dir):
            return {r["blood_group"]: r for r in fc.forecast(self.h)}

    def test_off_by_default_uses_average(self):
        self.assertEqual({r["method"] for r in self.rows().values()}, {"avg"})

    def test_enabled_uses_ai_only_for_series_with_history(self):
        SystemSetting.objects.update_or_create(setting_key="forecast_ai_enabled", defaults={"setting_value": True})
        rows = self.rows()
        self.assertEqual(rows["O+"]["method"], "ai")
        self.assertEqual(len(rows["O+"]["daily"]), 14)
        self.assertGreater(rows["O+"]["per_day"], 0)
        self.assertEqual(rows["A+"]["method"], "avg")                   # mới 10 ngày → chưa đủ, dùng trung bình
        self.client.force_login(self.user)
        with override_settings(FORECAST_MODEL_DIR=self.dir):
            page = self.client.get("/benh-vien/nhu-cau/")
        self.assertContains(page, "Nguồn dữ liệu huấn luyện: Mô phỏng")
        self.assertContains(page, "WAPE 40,0%")

    def test_missing_model_falls_back(self):
        SystemSetting.objects.update_or_create(setting_key="forecast_ai_enabled", defaults={"setting_value": True})
        with override_settings(FORECAST_MODEL_DIR=self.dir / "trong"):
            predict._cache["mtime"] = None
            self.assertEqual({r["method"] for r in fc.forecast(self.h)}, {"avg"})

    def test_days_covered_uses_daily_demand(self):
        self.assertEqual(fc._days_covered(5, [2, 2, 2] + [0] * 11), 2.5)
        self.assertIsNone(fc._days_covered(5, [0] * 14))
