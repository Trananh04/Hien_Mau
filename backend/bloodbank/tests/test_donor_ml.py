"""AI gợi ý người hiến: đặc trưng không rò rỉ tương lai, nhãn đúng định nghĩa "hưởng ứng", mốc so sánh trùng điểm luật,
mô hình học / lưu / tải, chốt chặn, xếp hạng chỉ đổi THỨ TỰ (không đổi tập ứng viên), chỗ cho người mới, theo dõi thực tế."""
import shutil
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import numpy as np
import pandas as pd
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import AuditLog, DonorCallout, Notification, Registration, SystemSetting
from bloodbank.services import callout, donor_match
from bloodbank.services.donor_ml import features, history, model, monitor, predict, registry, simulate, training

from . import factories as f
from .test_donor_match import donate

_SIM = {}


def sim():
    """Dữ liệu mô phỏng dùng chung (sinh một lần cho cả bộ test)."""
    if "df" not in _SIM:
        _SIM["df"] = training._normalize(simulate.simulate(seed=3))
    return _SIM["df"]


class CleanModelDir:
    """Mỗi test bắt đầu với thư mục mô hình rỗng (thư mục tạm riêng cho test, xem settings)."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(settings.DONOR_AI_MODEL_DIR, ignore_errors=True)
        predict._cache.update(mtime=None, model=None, meta=None)
        predict._meta_cache.update(mtime=None, meta=None)

    def tearDown(self):
        shutil.rmtree(settings.DONOR_AI_MODEL_DIR, ignore_errors=True)
        super().tearDown()

    def install_model(self, kind="LR", synthetic=True):
        trained = model.train(sim(), kind)
        version, _ = registry.save_version(trained, {"synthetic": synthetic, "chosen": kind, "source": "sim"})
        registry.activate(version)
        return version

    def enable(self, on=True):
        SystemSetting.objects.update_or_create(setting_key="donor_ai_enabled", defaults={"setting_value": on})


class SimulateTests(TestCase):
    def test_reproducible_and_respects_hard_filters(self):
        a, b = simulate.simulate(seed=5), simulate.simulate(seed=5)
        pd.testing.assert_frame_equal(a, b)
        self.assertTrue((a["is_synthetic"] == 1).all())
        self.assertTrue(0.1 < a["label"].mean() < 0.4)
        # Người được mời luôn đủ thời gian nghỉ và chưa bị mời quá 3 lần trong 90 ngày (lọc cứng như hệ thống thật)
        self.assertTrue((a["days_since"].isna() | (a["days_since"] >= simulate.INTERVAL_DAYS)).all())
        self.assertTrue((a["recent_90d"] < simulate.MAX_90).all())
        self.assertLess(a[a["mode"] == "urgent"]["label"].mean(), a[a["mode"] == "stock"]["label"].mean())
        self.assertEqual(list(a.columns[4:4 + len(features.FEATURES)]), features.FEATURES)

    def test_every_parameter_has_a_source(self):
        for key, p in simulate.PARAMS.items():
            self.assertIn("Giả định", p["source"], key)


class FeatureAndLabelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital(province="Đà Nẵng", latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        cls.staff_user = f.staff(cls.h)

    def test_features_only_use_data_before_the_invite(self):
        u = f.user(blood_group="A+", province="Đà Nẵng")
        spot = f.campaign(self.h, status="completed", start_offset_h=-24 * 200 - 2,
                          latitude=Decimal("16.060"), longitude=Decimal("108.210"))
        first = donate(u, self.h, self.staff_user, 200, lab_group="A+", campaign=spot)
        type(first).objects.filter(pk=first.pk).update(lab_checked_at=first.donated_at + timedelta(days=1))
        at = timezone.now() - timedelta(days=30)
        donate(u, self.h, self.staff_user, 10)                           # sau lời mời → không được tính
        f.registration(f.campaign(self.h, start_offset_h=-24 * 5), u, status="no_show")
        x = features.compute(self.h, [u.pk], at, "urgent", False)[u.pk]
        self.assertEqual((x["n_donations"], x["days_since"], x["verified"], x["here"]), (1, 170, 1, 1))
        self.assertEqual((x["appointments"], x["show_rate"]), (1, 1.0))
        self.assertAlmostEqual(x["dist_km"], donor_match._km(16.054, 108.202, 16.060, 108.210))
        self.assertEqual((x["urgent"], x["has_campaign"], x["asked"], x["resp_rate"]), (1, 0, 0, None))

    def test_label_matches_response_definition_and_mode_comes_from_audit(self):
        c = DonorCallout.objects.create(hospital=self.h, blood_group="A+", created_by=self.staff_user,
                                        recipient_count=3)
        sent = timezone.now() - timedelta(days=20)
        DonorCallout.objects.filter(pk=c.pk).update(created_at=sent)
        AuditLog.objects.create(entity_type="donor_callouts", entity_id=c.pk, action="donor_callout",
                                new_values={"mode": "urgent"})
        came, cancelled, late = (f.user(blood_group="A+") for _ in range(3))
        for u in (came, cancelled, late):
            Notification.objects.create(user=u, type="donor_callout", title="Cần máu", entity_type="donor_callouts",
                                        entity_id=c.pk)
        camp = f.campaign(self.h, start_offset_h=-24 * 15)
        for u, days_after, status in ((came, 2, "pending"), (cancelled, 2, "cancelled"), (late, 10, "pending")):
            reg = f.registration(camp, u, status=status)
            Registration.objects.filter(pk=reg.pk).update(registered_at=sent + timedelta(days=days_after))
        df = history.dataset()
        self.assertEqual(len(df), 3)
        self.assertEqual(sorted(df["label"]), [0, 0, 1])
        self.assertTrue((df["mode"] == "urgent").all())
        self.assertEqual(history.size(), (1, 3))

    def test_recent_callout_not_used_until_window_closes(self):
        c = DonorCallout.objects.create(hospital=self.h, blood_group="A+", created_by=self.staff_user,
                                        recipient_count=1)
        Notification.objects.create(user=f.user(), type="donor_callout", title="Cần máu",
                                    entity_type="donor_callouts", entity_id=c.pk)
        self.assertEqual(len(history.dataset()), 0)                     # chưa biết kết quả → chưa học

    def test_rule_baseline_equals_live_rule_score(self):
        """Mốc so sánh khi huấn luyện chấm đúng công thức đang hiển thị cho nhân viên."""
        u = f.user(blood_group="A+", province="Đà Nẵng")
        spot = f.campaign(self.h, status="completed", start_offset_h=-24 * 150 - 2,
                          latitude=Decimal("16.100"), longitude=Decimal("108.250"))
        donate(u, self.h, self.staff_user, 150, lab_group="A+", campaign=spot)
        now = timezone.now()
        live = donor_match.suggest(self.h, "A+", now=now, rank=False)[0]
        x = features.compute(self.h, [u.pk], now, "stock", False)[u.pk]
        row = pd.DataFrame([{"mode": "stock", **x}])
        got = model.rule_scores(row, SystemSetting.get("donor_invite_max_90_days"))[0]
        self.assertEqual(round(got), live["score"])


class ModelTests(CleanModelDir, TestCase):
    def test_logreg_learns_save_load_and_explains(self):
        df = sim()
        m = model.train(df, "LR")
        X = model.matrix(df.head(200))
        p = m.predict(X)
        self.assertTrue(((p > 0) & (p < 1)).all())
        self.assertGreater(model.auc(df["label"].to_numpy(), m.predict(model.matrix(df))), 0.65)
        # Đóng góp từng đặc trưng + hệ số chặn = log-odds
        logit = np.log(p / (1 - p))
        self.assertTrue(np.allclose(m.contributions(X).sum(axis=1) + m.s["w"][0], logit, atol=1e-6))
        version, _ = registry.save_version(m, {"chosen": "LR", "synthetic": True})
        again, meta = model.load(registry.versions_dir() / version)
        self.assertEqual(meta["kind"], "LR")
        self.assertTrue(np.allclose(again.predict(X), p))

    def test_xgb_trains_and_explains(self):
        m = model.train(sim(), "XGB")
        X = model.matrix(sim().head(50))
        self.assertEqual(m.contributions(X).shape, (50, len(features.FEATURES)))

    def test_top_k_and_lift(self):
        df = pd.DataFrame({"callout_id": [1, 1, 1, 2, 2, 2], "label": [1, 0, 0, 0, 1, 0],
                           "RULE": [0.1, 0.9, 0.5, 0.9, 0.1, 0.5], "LR": [0.9, 0.1, 0.5, 0.1, 0.9, 0.5]})
        self.assertEqual(model.top_k(df, "LR", k=1), (1.0, 1.0))
        self.assertEqual(model.top_k(df, "RULE", k=1), (0.0, 0.0))
        self.assertEqual(model.auc(np.array([1, 0, 1, 0]), np.array([0.9, 0.1, 0.8, 0.2])), 1.0)
        self.assertIsNone(model.auc(np.array([1, 1]), np.array([0.2, 0.3])))


class GuardAndTrainingTests(CleanModelDir, TestCase):
    def meta(self, low=0.05, auc=0.75, cal=0.01, synthetic=True, callouts=100):
        return {"chosen": "LR", "synthetic": synthetic, "backtest": [
            {"model": "RULE", "p_at_10": 0.38, "auc": 0.70, "calibration": None, "test_callouts": callouts},
            {"model": "LR", "p_at_10": 0.40, "auc": auc, "calibration": cal, "lift": 0.1, "lift_low": low,
             "lift_high": 0.2, "test_callouts": callouts}]}

    def test_guard_conditions(self):
        self.assertEqual(registry.guard(self.meta()), (True, []))
        for bad in (self.meta(low=-0.01), self.meta(auc=0.69), self.meta(cal=0.08), self.meta(callouts=5)):
            self.assertFalse(registry.guard(bad)[0])
        ok, reasons = registry.guard(self.meta(), current={"synthetic": False})
        self.assertFalse(ok)
        self.assertIn("dữ liệu thật", reasons[0])

    def test_run_on_simulated_data_saves_version_and_compares_three_ways(self):
        meta = training.run("sim", folds=3, log=lambda *_: None)
        self.assertTrue(meta["synthetic"])
        self.assertEqual({r["model"] for r in meta["backtest"]}, {"RULE", "LR", "XGB"})
        self.assertIn(meta["chosen"], ("LR", "XGB"))
        self.assertIsNone(registry.scores(meta)["RULE"]["calibration"])           # NaN đã đổi thành None
        self.assertEqual(registry.versions()[0]["version"], meta["version"])
        self.assertEqual(meta["promoted"], meta["guard"]["passed"])
        self.assertEqual(registry.last_run()["version"], meta["version"])

    def test_db_source_refuses_without_enough_real_data(self):
        with self.assertRaises(training.NotEnoughData):
            training.load("db", log=lambda *_: None)

    def test_retrain_reasons(self):
        self.assertEqual(monitor.retrain_reason(), "first")
        self.install_model(synthetic=True)
        self.assertIsNone(monitor.retrain_reason(real=(5, 50)))
        self.assertEqual(monitor.retrain_reason(real=(40, 400)), "real_data")
        SystemSetting.objects.update_or_create(setting_key="donor_ai_auto_retrain", defaults={"setting_value": False})
        self.assertIsNone(monitor.retrain_reason(real=(40, 400)))


class RankingTests(CleanModelDir, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital(province="Đà Nẵng", latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        cls.staff_user = f.staff(cls.h)
        cls.staff = cls.staff_user.staffs.get()
        cls.people = []
        for i, days in enumerate((100, 200, 300, 400)):
            u = f.user(blood_group="A+", province="Đà Nẵng")
            spot = f.campaign(cls.h, status="completed", start_offset_h=-24 * days - 2,
                              latitude=Decimal("16.06") + Decimal(i) / 20, longitude=Decimal("108.21"))
            donate(u, cls.h, cls.staff_user, days, lab_group="A+", campaign=spot)
            cls.people.append(u)
        cls.newcomer = f.user(blood_group="A+", province="Đà Nẵng")
        cls.too_soon = f.user(blood_group="A+", province="Đà Nẵng")
        donate(cls.too_soon, cls.h, cls.staff_user, 20)

    def ids(self, rows):
        return {r["user_id"] for r in rows}

    def test_ai_only_reorders_the_same_safe_candidates(self):
        self.install_model()
        self.enable()
        plain = donor_match.suggest(self.h, "A+", rank=False)
        ranked = donor_match.suggest(self.h, "A+")
        self.assertEqual(self.ids(ranked), self.ids(plain))               # không thêm / bớt người
        self.assertNotIn(self.too_soon.pk, self.ids(ranked))              # luật lọc cứng vẫn áp dụng
        self.assertTrue(all(0 < r["prob"] < 1 for r in ranked))
        self.assertTrue(all(r["factors"] for r in ranked if not r["explore"]))
        self.assertFalse(any("prob" in r for r in plain))

    def test_disabled_or_missing_model_keeps_rule_order(self):
        self.enable()
        rows = donor_match.suggest(self.h, "A+")                           # bật nhưng chưa có mô hình
        self.assertFalse(any("prob" in r for r in rows))
        self.install_model()
        self.enable(False)
        self.assertFalse(any("prob" in r for r in donor_match.suggest(self.h, "A+")))

    def test_exploration_slot_for_newcomers_is_deterministic(self):
        rows = [{"user_id": i, "code": f"C{i}", "recent_invites": 0, "asked": 1, "history_seen": 1}
                for i in range(8)]
        rows += [{"user_id": 100 + i, "code": f"N{i}", "recent_invites": 0, "asked": 0, "history_seen": 0}
                 for i in range(2)]
        probs = {i: (0.9 - i * 0.1, []) for i in range(8)} | {100: (0.05, []), 101: (0.01, [])}
        with mock.patch.object(predict, "score", return_value=probs), mock.patch.object(predict, "loaded",
                                                                                       return_value=(None, None)):
            predict.apply(self.h, rows, "stock")
        order = [r["code"] for r in rows]
        self.assertEqual(order[6], "N0")                                    # vị trí thứ 7 dành cho người mới
        self.assertTrue(rows[6]["explore"])
        self.assertEqual(order[:6], ["C0", "C1", "C2", "C3", "C4", "C5"])
        self.assertEqual(sorted(order), sorted(r["code"] for r in rows))

    def test_count_uses_probabilities(self):
        rows = [{"prob": 0.5}] * 10
        self.assertEqual(predict.count_for(rows, 2, 50), 4)                 # 4 × 0,5 = 2 người dự kiến nhận lời
        self.assertEqual(predict.count_for(rows, 99, 6), 6)
        self.assertEqual(predict.count_for(rows, 0, 50), 0)

    def test_suggest_page_and_callout_record_ai_probabilities(self):
        self.install_model()
        self.enable()
        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:donor_suggest") + "?blood_group=A%2B")
        self.assertTrue(r.context["ai"])
        self.assertContains(r, "Khả năng nhận lời")
        code = r.context["rows"][0]["code"]
        callout.donor_callout(self.staff, "A+", [code], None)
        ai = AuditLog.objects.get(action="donor_callout").new_values["ai"]
        self.assertIn(code, ai["probs"])
        self.assertEqual(ai["version"], registry.active_meta()["version"])


class MonitorTests(CleanModelDir, TestCase):
    def test_weekly_compares_actual_with_predicted(self):
        h = f.hospital()
        staff_user = f.staff(h)
        yes, no = f.user(), f.user()
        c = DonorCallout.objects.create(hospital=h, blood_group="O+", created_by=staff_user, recipient_count=2)
        sent = timezone.now() - timedelta(days=10)
        DonorCallout.objects.filter(pk=c.pk).update(created_at=sent)
        probs = {donor_match.donor_code(h, yes.pk): 0.6, donor_match.donor_code(h, no.pk): 0.2}
        AuditLog.objects.create(entity_type="donor_callouts", entity_id=c.pk, action="donor_callout",
                                new_values={"mode": "stock", "ai": {"version": "x", "probs": probs}})
        for u in (yes, no):
            Notification.objects.create(user=u, type="donor_callout", title="Cần máu", entity_type="donor_callouts",
                                        entity_id=c.pk)
        reg = f.registration(f.campaign(h, start_offset_h=24), yes)
        Registration.objects.filter(pk=reg.pk).update(registered_at=sent + timedelta(days=1))
        weeks = monitor.weekly_stats()
        self.assertEqual(len(weeks), 1)
        w = weeks[0]
        self.assertEqual((w["sent"], w["responded"], w["ai_sent"], w["ai_responded"]), (2, 1, 2, 1))
        self.assertAlmostEqual(w["ai_expected"], 0.8)
        self.assertAlmostEqual(monitor.gap(weeks)[0], (1 - 0.8) / 2)

    def test_admin_page(self):
        admin = f.user(role="admin")
        self.client.force_login(admin)
        r = self.client.get(reverse("bloodbank:admin_donor_ai"))
        self.assertContains(r, "AI gợi ý người hiến")
        self.assertContains(r, "Chưa có phiên bản nào")
        self.install_model()
        r = self.client.get(reverse("bloodbank:admin_donor_ai"))
        self.assertContains(r, "Đang dùng")
        self.client.post(reverse("bloodbank:admin_donor_ai"), {"action": "train"})
        self.assertTrue(registry.training_requested())
        self.client.post(reverse("bloodbank:admin_donor_ai"), {"action": "ai", "value": "on"})
        self.assertTrue(SystemSetting.get("donor_ai_enabled"))
