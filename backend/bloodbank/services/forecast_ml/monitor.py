"""Theo dõi độ chính xác THẬT và huấn luyện lại định kỳ (gọi từ jobs.run_all, container scheduler).

record_snapshots: mỗi ngày một lần, với mỗi bệnh viện × nhóm máu × quy cách lưu dự báo 14 ngày (từ hôm nay) dựa trên
    lịch sử đến HẾT HÔM QUA: cả cách đang hiển thị (AI nếu bật và đủ điều kiện, không thì trung bình) lẫn trung bình
    28 ngày để so sánh. Ghi lặp lại cùng ngày không tạo trùng.
accuracy: so các dự báo đã lưu với nhu cầu thực tế (history.daily_demand) theo từng tuần.
maybe_retrain: huấn luyện lại khi Quản trị yêu cầu, hoặc khi đến hạn (`forecast_retrain_days`, bật
    `forecast_auto_retrain`). Bỏ qua khi chưa có dữ liệu thật mà bản đang dùng đã là bản mô phỏng (học lại cũng như cũ).
"""
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from . import history, registry, training

log = logging.getLogger(__name__)
WINDOW_DAYS = 28


def record_snapshots(now=None):
    from bloodbank.models import ForecastSnapshot, Hospital

    from . import predict

    today = timezone.localdate(now)
    origin = today - timedelta(days=1)
    if ForecastSnapshot.objects.filter(origin=origin).exists():
        return 0
    as_of = timezone.make_aware(datetime.combine(origin, time(23, 59)))
    version = (predict.loaded()[1] or {}).get("version") if predict.enabled() else None
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


def _wape(err, total):
    return err / total if total > 0 else None


def accuracy(weeks=12, now=None):
    """Theo tuần (thứ 2 của tuần có ngày được dự báo), chỉ các ngày đã qua:
    {"week", "days", "actual", "ai", "ai_base", "avg"} — ai / ai_base: WAPE của AI và của trung bình 28 ngày trên
    CÙNG các dòng dùng AI (so công bằng); avg: WAPE trên các dòng chỉ dùng trung bình."""
    from bloodbank.models import ForecastSnapshot

    end = timezone.localdate(now) - timedelta(days=1)
    start = end - timedelta(days=7 * weeks - 1)
    start -= timedelta(days=start.weekday())
    snaps = list(ForecastSnapshot.objects.filter(target_date__gte=start, target_date__lte=end)
                 .values("hospital", "blood_group", "product_spec", "target_date", "method", "predicted", "baseline"))
    if not snaps:
        return []
    actual = history.daily_demand(start, end)
    acc = defaultdict(lambda: defaultdict(float))
    for s in snaps:
        series = actual.get((s["hospital"], s["blood_group"], s["product_spec"]))
        a = float(series[(s["target_date"] - start).days]) if series is not None else 0.0
        w = acc[s["target_date"] - timedelta(days=s["target_date"].weekday())]
        w["n"] += 1
        if s["method"] == "ai":
            w["ai_err"] += abs(a - s["predicted"])
            w["ai_base_err"] += abs(a - s["baseline"])
            w["ai_actual"] += a
            w["ai_bias"] += s["predicted"] - a
        else:
            w["avg_err"] += abs(a - s["baseline"])
            w["avg_actual"] += a
    out = []
    for week in sorted(acc):
        w = acc[week]
        out.append({"week": week, "n": int(w["n"]), "ai": _wape(w["ai_err"], w["ai_actual"]),
                    "ai_base": _wape(w["ai_base_err"], w["ai_actual"]),
                    "ai_bias": _wape(w["ai_bias"], w["ai_actual"]), "avg": _wape(w["avg_err"], w["avg_actual"])})
    return out


def retrain_due(now=None):
    from django.conf import settings

    from bloodbank.models import SystemSetting

    if not settings.FORECAST_SCHEDULED_TRAINING:
        return None
    if registry.training_requested():
        return "requested"
    if not SystemSetting.get("forecast_auto_retrain"):
        return None
    last = registry.last_run()
    if last:
        at = datetime.fromisoformat(last["at"])
        if (now or timezone.now()) - at < timedelta(days=SystemSetting.get("forecast_retrain_days")):
            return None
    return "scheduled"


def maybe_retrain(now=None):
    reason = retrain_due(now)
    if reason is None:
        return None
    current = registry.active_meta()
    if reason == "scheduled" and current and current.get("synthetic") and training.db_frame()[1] < training.MIN_DB_SERIES:
        registry.record_run({"version": None, "promoted": False, "source": "sim",
                             "reasons": ["chưa đủ dữ liệu thật — giữ bản mô phỏng đang dùng"]})
        return "skipped"
    registry.clear_request()
    try:
        meta = training.run(log=log.info)
    except Exception as exc:                          # không để lỗi huấn luyện làm dừng các tác vụ khác
        log.exception("Huấn luyện dự báo thất bại")
        registry.record_run({"version": None, "promoted": False, "source": None, "reasons": [f"lỗi: {exc}"]})
        return "error"
    return "promoted" if meta["promoted"] else "kept"


def _scores(meta):
    return {r["model"]: r for r in (meta or {}).get("backtest") or []}


def dashboard(now=None):
    """Số liệu cho trang Quản trị → Dự báo AI."""
    from bloodbank.models import SystemSetting

    from . import predict

    model, meta = predict.loaded()
    weeks = accuracy(now=now)
    peak = max([w[k] or 0 for w in weeks for k in ("ai", "ai_base", "avg")] or [0])
    _, real_series = training.db_frame()
    versions = registry.versions()[:10]
    for v in versions:
        v["scores"] = _scores(v)
    last = registry.last_run()
    retrain_days = SystemSetting.get("forecast_retrain_days")
    next_due = (datetime.fromisoformat(last["at"]) + timedelta(days=retrain_days)) if last else None
    return {
        "enabled": bool(SystemSetting.get("forecast_ai_enabled")), "ready": model is not None,
        "meta": meta, "scores": _scores(meta), "versions": versions, "last": last,
        "last_at": datetime.fromisoformat(last["at"]) if last else None, "next_due": next_due,
        "requested": registry.training_requested(), "auto": bool(SystemSetting.get("forecast_auto_retrain")),
        "retrain_days": retrain_days, "weeks": weeks, "peak": peak or 1,
        "real_series": real_series, "min_series": training.MIN_DB_SERIES, "min_days": training.MIN_DB_DAYS,
        "trained_at": datetime.fromisoformat(meta["trained_at"]) if meta and meta.get("trained_at") else None,
    }
