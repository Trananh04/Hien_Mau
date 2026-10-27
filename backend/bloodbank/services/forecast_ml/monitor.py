"""Vận hành dự báo (gọi từ jobs.run_all, container scheduler) — dự đoán MỖI ĐÊM MỘT LẦN, học lại CHỈ KHI CÓ LÝ DO.

record_snapshots: lần chạy đầu tiên mỗi ngày, mỗi bệnh viện × nhóm máu × quy cách lưu dự báo 14 ngày (từ hôm nay) dựa
    trên lịch sử đến HẾT HÔM QUA: cách đang hiển thị (AI nếu bật và đủ điều kiện, không thì trung bình) + trung bình
    28 ngày để so sánh. Trang Dự báo thiếu hụt ĐỌC bảng này (latest) thay vì tự tính mỗi lượt mở trang; bật/tắt AI hay
    đổi phiên bản thì tính lại ngay (refresh_snapshots).
accuracy: so dự báo đã lưu với nhu cầu thực tế (history.daily_demand) theo từng tuần — tính MỘT lần mỗi ngày
    (cùng lúc lưu dự báo) vào last_accuracy.json; trang quản trị chỉ đọc kết quả (store_accuracy / weekly).
nightly_check: một lần mỗi đêm trong khung giờ vắng (FORECAST_TRAIN_HOURS) — dọn dữ liệu cũ, tự bảo vệ, rồi chỉ học lại
    khi có lý do (retrain_reason):
      "first"     chưa có mô hình nào;
      "real_data" bản đang dùng là mô phỏng mà sổ kho vừa đủ dữ liệu thật;
      "drift"     AI (phiên bản đang dùng) thua trung bình 28 ngày DRIFT_WEEKS tuần trọn vẹn liền;
      "new_data"  bản dữ liệu thật đã dùng ≥ `forecast_retrain_days` ngày (có thêm ngần ấy ngày dữ liệu mới).
    Hai lần học lại tự động cách nhau ít nhất MIN_GAP_DAYS ngày. Quản trị bấm "Huấn luyện lại ngay" thì chạy ở lần kế.
protect: AI thua trung bình PROTECT_WEEKS tuần liền → tự tắt AI, trang quay về trung bình, báo Quản trị.
"""
import logging
import shutil
from collections import defaultdict
from datetime import datetime, time, timedelta

import numpy as np
from django.conf import settings
from django.utils import timezone

from . import history, registry

log = logging.getLogger(__name__)
WINDOW_DAYS = 28
DRIFT_WEEKS = 2
PROTECT_WEEKS = 3
MIN_GAP_DAYS = 7
MIN_WEEK_ROWS = 28            # tuần quá ít dòng dự báo AI thì chưa đủ để kết luận
KEEP_SNAPSHOT_DAYS = 365
KEEP_VERSIONS = 10


# ---------------------------------------------------------------- Dự đoán mỗi đêm
def record_snapshots(now=None, refresh=False):
    from bloodbank.models import ForecastSnapshot, Hospital

    from . import predict

    today = timezone.localdate(now)
    origin = today - timedelta(days=1)
    if refresh:
        ForecastSnapshot.objects.filter(origin=origin).delete()
    elif ForecastSnapshot.objects.filter(origin=origin).exists():
        return 0
    as_of = timezone.make_aware(datetime.combine(origin, time(23, 59)))
    version = (predict.active_meta() or {}).get("version") if predict.enabled() else None
    rows = []
    for hospital in Hospital.objects.filter(stocks__isnull=False).distinct():
        recent = history.recent(hospital, origin, WINDOW_DAYS)
        ai = predict.forecast(hospital, as_of)
        for key in set(recent) | set(ai):
            base = float(recent[key].sum()) / WINDOW_DAYS if key in recent else 0.0
            daily = ai.get(key)
            if daily is None and base == 0:
                continue
            for h in range(1, 15):
                rows.append(ForecastSnapshot(
                    hospital=hospital, blood_group=key[0], product_spec_id=key[1], origin=origin,
                    target_date=origin + timedelta(days=h), h=h, baseline=base,
                    method="ai" if daily is not None else "avg",
                    predicted=float(daily[h - 1]) if daily is not None else base,
                    model_version=version if daily is not None else None))
    ForecastSnapshot.objects.bulk_create(rows, ignore_conflicts=True, batch_size=1000)
    return len(rows)


def refresh_snapshots():
    """Sau khi bật/tắt AI hoặc đổi phiên bản: tính lại dự báo hôm nay để trang hiển thị ngay theo cấu hình mới."""
    try:
        return record_snapshots(refresh=True)
    except Exception:
        log.exception("Tính lại dự báo thất bại")   # trang vẫn chạy: không có dự báo đêm qua thì tự tính trực tiếp
        return 0


def latest(hospital, now=None):
    """{(nhóm máu, quy cách): {"method", "daily" (14 số từ hôm nay), "baseline"}} của dự báo đêm qua; None nếu chưa có."""
    from bloodbank.models import ForecastSnapshot

    origin = timezone.localdate(now) - timedelta(days=1)
    rows = (ForecastSnapshot.objects.filter(hospital=hospital, origin=origin)
            .values_list("blood_group", "product_spec", "h", "method", "predicted", "baseline"))
    out = {}
    for bg, spec, h, method, predicted, baseline in rows:
        s = out.setdefault((bg, spec), {"method": method, "daily": np.zeros(14), "baseline": baseline})
        s["daily"][h - 1] = predicted
    return out or None


# ---------------------------------------------------------------- Đo sai số thật
def _wape(err, total):
    return err / total if total > 0 else None


def accuracy(weeks=12, now=None, version=None):
    """Theo tuần (thứ 2 của tuần có ngày được dự báo), chỉ các ngày đã qua:
    {"week", "complete", "n", "n_ai", "ai", "ai_base", "ai_bias", "avg"} — ai / ai_base: WAPE của AI và của trung bình
    28 ngày trên CÙNG các dòng dùng AI (so công bằng); avg: WAPE trên các dòng chỉ dùng trung bình.
    `version`: chỉ tính dự báo AI của phiên bản đó."""
    from bloodbank.models import ForecastSnapshot

    end = timezone.localdate(now) - timedelta(days=1)
    start = end - timedelta(days=7 * weeks - 1)
    start -= timedelta(days=start.weekday())
    qs = ForecastSnapshot.objects.filter(target_date__gte=start, target_date__lte=end)
    if version is not None:
        qs = qs.filter(method="ai", model_version=version)
    if not qs.exists():
        return []
    actual = history.daily_demand(start, end)
    acc = defaultdict(lambda: defaultdict(float))
    rows = qs.values_list("hospital", "blood_group", "product_spec", "target_date", "method", "predicted", "baseline")
    for hosp, bg, spec, target, method, predicted, baseline in rows.iterator(chunk_size=5000):
        series = actual.get((hosp, bg, spec))
        a = float(series[(target - start).days]) if series is not None else 0.0
        w = acc[target - timedelta(days=target.weekday())]
        w["n"] += 1
        if method == "ai":
            w["n_ai"] += 1
            w["ai_err"] += abs(a - predicted)
            w["ai_base_err"] += abs(a - baseline)
            w["ai_actual"] += a
            w["ai_bias"] += predicted - a
        else:
            w["avg_err"] += abs(a - baseline)
            w["avg_actual"] += a
    out = []
    for week in sorted(acc):
        w = acc[week]
        out.append({"week": week, "complete": week + timedelta(days=6) <= end, "n": int(w["n"]),
                    "n_ai": int(w["n_ai"]), "ai": _wape(w["ai_err"], w["ai_actual"]),
                    "ai_base": _wape(w["ai_base_err"], w["ai_actual"]),
                    "ai_bias": _wape(w["ai_bias"], w["ai_actual"]), "avg": _wape(w["avg_err"], w["avg_actual"])})
    return out


def store_accuracy(now=None):
    """Tính sai số 12 tuần một lần (tác vụ định kỳ, sau khi lưu dự báo mỗi ngày) → last_accuracy.json."""
    from . import training

    weeks = accuracy(now=now)
    registry.set_state("last_accuracy", {"date": timezone.localdate(now).isoformat(),
                                         "weeks": [{**w, "week": w["week"].isoformat()} for w in weeks],
                                         "real_series": training.db_frame()[1]})   # quét sổ kho 1 lần / ngày
    return weeks


def weekly(now=None):
    """Sai số theo tuần đã tính sẵn; chưa có (hoặc cũ hơn hôm nay) thì tính một lần rồi lưu."""
    from datetime import date

    state = registry.state("last_accuracy")
    if not state or state.get("date") != timezone.localdate(now).isoformat():
        return store_accuracy(now)
    return [{**w, "week": date.fromisoformat(w["week"])} for w in state["weeks"]]


def losing_weeks(now=None):
    """Số tuần trọn vẹn GẦN NHẤT liên tiếp mà AI (phiên bản đang dùng) sai nhiều hơn trung bình 28 ngày."""
    version = (registry.active_meta() or {}).get("version")
    if not version:
        return 0
    n = 0
    for w in reversed([w for w in accuracy(weeks=PROTECT_WEEKS + 1, now=now, version=version) if w["complete"]]):
        if w["n_ai"] < MIN_WEEK_ROWS or w["ai"] is None or w["ai_base"] is None or w["ai"] <= w["ai_base"]:
            break
        n += 1
    return n


# ---------------------------------------------------------------- Mỗi đêm: dọn, tự bảo vệ, học lại khi có lý do
def _in_window(now):
    start, end = settings.FORECAST_TRAIN_HOURS
    return start <= timezone.localtime(now).hour < end


def _since(iso, now):
    return (now or timezone.now()) - datetime.fromisoformat(iso) if iso else None


def retrain_reason(now=None, losing=0, real_series=0):
    from bloodbank.models import SystemSetting

    from . import training

    if not SystemSetting.get("forecast_auto_retrain"):
        return None
    current = registry.active_meta()
    if not current:
        return "first"
    gap = _since((registry.last_run() or {}).get("at"), now)
    if gap is not None and gap < timedelta(days=MIN_GAP_DAYS):
        return None
    if current.get("synthetic"):
        return "real_data" if real_series >= training.MIN_DB_SERIES else None
    if losing >= DRIFT_WEEKS:
        return "drift"
    age = _since(current.get("trained_at"), now)
    if age is not None and age >= timedelta(days=SystemSetting.get("forecast_retrain_days")):
        return "new_data"
    return None


REASONS = {"requested": "Quản trị yêu cầu", "first": "chưa có mô hình", "real_data": "đã đủ dữ liệu thật",
           "drift": f"AI thua trung bình {DRIFT_WEEKS} tuần liền", "new_data": "đã có thêm dữ liệu mới"}


def _retrain(reason):
    from . import training

    registry.clear_request()
    try:
        meta = training.run(log=log.info)
    except Exception as exc:                          # không để lỗi huấn luyện làm dừng các tác vụ khác
        log.exception("Huấn luyện dự báo thất bại")
        registry.record_run({"version": None, "promoted": False, "source": None, "trigger": reason,
                             "reasons": [f"lỗi: {exc}"]})
        return "error"
    registry.record_run({**registry.last_run(), "trigger": reason})
    if meta["promoted"]:
        refresh_snapshots()
    return "promoted" if meta["promoted"] else "kept"


def protect(losing, now=None):
    """AI thua trung bình PROTECT_WEEKS tuần liền → tắt AI (trang dùng trung bình 28 ngày), báo Quản trị một lần."""
    from accounts.models import User
    from bloodbank.models import AuditLog, SystemSetting

    from .. import common

    if losing < PROTECT_WEEKS or not SystemSetting.get("forecast_ai_enabled"):
        return False
    with common.business_transaction():
        row, _ = SystemSetting.objects.get_or_create(
            setting_key="forecast_ai_enabled",
            defaults={"setting_value": False, "description": SystemSetting.DEFAULTS["forecast_ai_enabled"][1]})
        row.setting_value = False
        row.save()
        AuditLog.objects.create(entity_type="system_settings", entity_id=0, action="update",
                                old_values={"value": True}, new_values={"value": False, "reason": "forecast_protect"})
        common.alert(list(User.objects.filter(role="admin", status="active")), "forecast_ai_disabled",
                     "Dự báo AI đã tự tắt",
                     f"AI dự báo kém hơn trung bình 4 tuần {losing} tuần liền. Trang Dự báo thiếu hụt đang dùng "
                     "trung bình 4 tuần; xem Quản trị → Dự báo AI.")
    refresh_snapshots()
    return True


def cleanup(now=None):
    from bloodbank.models import ForecastSnapshot

    cutoff = timezone.localdate(now) - timedelta(days=KEEP_SNAPSHOT_DAYS)
    removed = ForecastSnapshot.objects.filter(origin__lt=cutoff).delete()[0]
    for v in registry.versions()[KEEP_VERSIONS:]:
        if not v["active"]:
            shutil.rmtree(registry.versions_dir() / v["version"], ignore_errors=True)
    return removed


def nightly_check(now=None):
    """Trả về kết quả học lại ("promoted" / "kept" / "error") hoặc None nếu không học."""
    from . import training

    if not settings.FORECAST_SCHEDULED_TRAINING:
        return None
    if registry.training_requested():                 # Quản trị bấm → chạy ở lần kế, không chờ đêm
        return _retrain("requested")
    today = timezone.localdate(now).isoformat()
    if not _in_window(now) or (registry.state("last_check") or {}).get("date") == today:
        return None
    cleanup(now)
    losing = losing_weeks(now)
    current = registry.active_meta()
    real_series = training.db_frame()[1] if not current or current.get("synthetic") else None
    registry.set_state("last_check", {"date": today, "losing_weeks": losing, "real_series": real_series})
    protect(losing, now)
    reason = retrain_reason(now, losing, real_series or 0)
    return _retrain(reason) if reason else None


# ---------------------------------------------------------------- Trang quản trị
def _scores(meta):
    return {r["model"]: r for r in (meta or {}).get("backtest") or []}


def dashboard(now=None):
    """Số liệu cho trang Quản trị → Dự báo AI."""
    from bloodbank.models import SystemSetting

    from . import predict, training

    meta = predict.active_meta()
    weeks = weekly(now)
    peak = max([w[k] or 0 for w in weeks for k in ("ai", "ai_base", "avg")] or [0])
    check = registry.state("last_check") or {}
    real_series = check.get("real_series")
    if real_series is None:                           # tính sẵn mỗi ngày cùng sai số (weekly ở trên)
        real_series = (registry.state("last_accuracy") or {}).get("real_series", 0)
    versions = registry.versions()[:KEEP_VERSIONS]
    for v in versions:
        v["scores"] = _scores(v)
    last = registry.last_run()
    return {
        "enabled": bool(SystemSetting.get("forecast_ai_enabled")), "ready": meta is not None,
        "meta": meta, "scores": _scores(meta), "versions": versions, "last": last,
        "last_at": datetime.fromisoformat(last["at"]) if last else None,
        "trigger": REASONS.get((last or {}).get("trigger")), "check": check,
        "requested": registry.training_requested(), "auto": bool(SystemSetting.get("forecast_auto_retrain")),
        "retrain_days": SystemSetting.get("forecast_retrain_days"), "weeks": weeks, "peak": peak or 1,
        "drift_weeks": DRIFT_WEEKS, "protect_weeks": PROTECT_WEEKS, "hours": settings.FORECAST_TRAIN_HOURS,
        "real_series": real_series, "min_series": training.MIN_DB_SERIES, "min_days": training.MIN_DB_DAYS,
        "trained_at": datetime.fromisoformat(meta["trained_at"]) if meta and meta.get("trained_at") else None,
    }
