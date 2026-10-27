"""Tối ưu hiệu năng (docs/bao-cao-kiem-toan-hieu-nang.md): lọc ngày theo khoảng thời gian vẫn đúng ranh giới ngày
địa phương, email khẩn gửi qua hàng đợi (không gửi trùng, có gửi lại), trang web không nạp pandas/xgboost, sai số dự
báo tính sẵn, file tĩnh băm tên bỏ qua sourcemap."""
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from bloodbank.models import Notification, Stock, StockTxn
from bloodbank.services import common, outbox
from bloodbank.services.forecast_ml import constants, history, monitor, predict, registry

from . import factories as f


class DayBoundaryTests(TestCase):
    """occurred_at__date (ép kiểu) → khoảng [00:00, 00:00 hôm sau) giờ địa phương: kết quả phải y như cũ."""

    def test_issue_late_evening_counts_on_that_local_day(self):
        h = f.hospital()
        user = f.staff(h)
        spec = f.spec()
        stock = Stock.objects.create(hospital=h, blood_group="O+", product_spec=spec, quantity_on_hand=50)
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        tz = timezone.get_current_timezone()
        for i, (day, hh, mm, qty) in enumerate([(yesterday, 23, 59, 2), (today, 0, 0, 3), (today, 0, 1, 1)]):
            StockTxn.objects.create(stock=stock, txn_type="issue", quantity_change=-qty, quantity_before=50,
                                    quantity_after=50 - qty, performed_by=user, idempotency_key=f"b-{i}",
                                    occurred_at=timezone.make_aware(datetime.combine(day, time(hh, mm)), tz))
        arr = history.recent(h, today, 2)[("O+", spec.pk)]
        self.assertEqual(list(arr), [2, 4])


class OutboxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = [f.user(role="hospital"), f.user(role="hospital")]

    def alert(self):
        with self.captureOnCommitCallbacks(execute=True):
            common.alert(self.users, "test_alert", "Thiếu máu O-")

    def test_alert_sends_each_email_once(self):
        self.alert()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted(u.email for u in self.users))
        rows = Notification.objects.filter(type="test_alert", channel="email")
        self.assertEqual(set(rows.values_list("delivery_status", "attempts")), {("sent", 1)})
        outbox.send(list(rows.values_list("pk", flat=True)))                     # gửi lại id đã gửi → bỏ qua
        self.assertEqual(len(mail.outbox), 2)

    def test_failed_email_is_retried_by_scheduler_then_given_up(self):
        with mock.patch("bloodbank.services.outbox.send_mail", side_effect=OSError("smtp down")):
            self.alert()
            self.assertEqual(outbox.sweep(), 0)                                   # chưa đủ 2 phút → chưa gửi lại
            later = timezone.now() + timedelta(minutes=3)
            outbox.sweep(later)
            outbox.sweep(later)
        rows = Notification.objects.filter(type="test_alert", channel="email")
        self.assertEqual(set(rows.values_list("delivery_status", "attempts")), {("failed", 3)})
        self.assertEqual(outbox.sweep(later), 0)                                  # quá 3 lần → thôi
        Notification.objects.filter(type="test_alert", channel="email").update(attempts=1)
        self.assertEqual(outbox.sweep(later), 2)                                  # máy chủ mail ổn lại → gửi được
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(EMAIL_ASYNC=True)
    def test_request_does_not_wait_for_mail_server(self):
        started = []

        class FakeThread:
            def __init__(self, target, args, **kw):
                started.append((target, args))

            def start(self):
                pass

        with mock.patch("bloodbank.services.outbox.threading.Thread", FakeThread):
            self.alert()
        self.assertEqual(len(started), 1)                                         # giao cho luồng nền
        self.assertEqual(len(mail.outbox), 0)                                     # request không tự gửi
        target, args = started[0]
        with mock.patch("bloodbank.services.outbox.connection"):
            target(*args)                                                         # luồng nền chạy → email đi
        self.assertEqual(len(mail.outbox), 2)


class LightWebTests(TestCase):
    def test_page_modules_do_not_import_training_libraries(self):
        code = ("import os, sys, django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
                "django.setup(); import bloodbank.services.forecast, bloodbank.services.forecast_ml.monitor, "
                "bloodbank.services.forecast_ml.predict, bloodbank.views.hospital_inventory, bloodbank.views.admin; "
                "print(json.dumps(['pandas' in sys.modules, 'xgboost' in sys.modules]))").replace(
            "import os", "import json, os")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=settings.BASE_DIR,
                             timeout=120)
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [False, False], out.stderr[-500:])

    def test_enabled_reads_metadata_without_loading_model(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "model.json").write_text("{}", encoding="utf-8")
        (d / "metadata.json").write_text(json.dumps({"version": "v1", "features": constants.FEATURES,
                                                     "blood_groups": constants.BLOOD_GROUPS}), encoding="utf-8")
        with override_settings(FORECAST_MODEL_DIR=d):
            predict._cache.update(mtime=None, model=None, meta=None)
            predict._meta_cache.update(mtime=None, meta=None)
            self.assertEqual(predict.active_meta()["version"], "v1")
            self.assertIsNone(predict._cache["model"])                           # chưa nạp xgboost
            (d / "metadata.json").write_text(json.dumps({"features": ["khac"]}), encoding="utf-8")
            predict._meta_cache.update(mtime=None, meta=None)
            self.assertIsNone(predict.active_meta())                              # mô hình cũ không khớp → không dùng


class AccuracyCacheTests(TestCase):
    def test_admin_page_reads_precomputed_accuracy(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        with override_settings(FORECAST_MODEL_DIR=d):
            with mock.patch.object(monitor, "accuracy", return_value=[]) as calc:
                monitor.weekly()
                monitor.weekly()
                self.assertEqual(calc.call_count, 1)                              # tính 1 lần / ngày
            self.assertEqual(registry.state("last_accuracy")["date"], timezone.localdate().isoformat())


class StaticStorageTests(TestCase):
    def test_manifest_storage_ignores_sourcemaps(self):
        from bloodbank.storage import StaticStorage

        flat = json.dumps([[p[0] if isinstance(p, tuple) else p for p in items] for _, items in StaticStorage.patterns])
        self.assertNotIn("sourceMappingURL", flat)
        self.assertIn("@import", flat)                                            # vẫn xử lý url() / @import trong CSS
        self.assertFalse(StaticStorage.manifest_strict)
