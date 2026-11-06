"""Vận hành AI gợi ý người hiến (gọi từ jobs.run_all, container scheduler).

weekly: theo tuần gửi lời mời (chỉ lời mời đã hết thời gian theo dõi) — số lời mời, số nhận lời; riêng các lời mời gửi khi
    danh sách do AI xếp hạng: tổng xác suất AI đã dự đoán (lưu trong nhật ký lúc gửi) để so với số nhận lời thực tế.
nightly_check: mỗi đêm trong khung giờ vắng (FORECAST_TRAIN_HOURS) — tính số liệu tuần, tự bảo vệ, rồi chỉ học lại khi có
    lý do (retrain_reason):
      "first"     chưa có mô hình nào;
      "real_data" bản đang dùng học từ mô phỏng mà lịch sử thật vừa đủ;
      "drift"     4 tuần gần nhất: tỷ lệ nhận lời thực tế lệch AI dự đoán quá DRIFT_GAP (≥ MIN_DRIFT_INVITES lời mời);
      "new_data"  bản học từ dữ liệu thật đã dùng ≥ `donor_ai_retrain_days` ngày.
    Hai lần học lại tự động cách nhau ít nhất MIN_GAP_DAYS ngày. Quản trị bấm "Huấn luyện lại ngay" thì chạy ở lần kế.
protect: lệch quá PROTECT_GAP (≥ MIN_PROTECT_INVITES lời mời) → tự tắt AI (danh sách quay về chấm điểm luật), báo Quản trị.
"""
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone

from . import history, registry

log = logging.getLogger(__name__)
WEEKS = 12
RECENT_WEEKS = 4
DRIFT_GAP = 0.10
MIN_DRIFT_INVITES = 100
PROTECT_GAP = 0.20
MIN_PROTECT_INVITES = 200
MIN_GAP_DAYS = 7
KEEP_VERSIONS = 10
REASONS = {"requested": "Quản trị yêu cầu", "first": "chưa có mô hình", "real_data": "đã đủ dữ liệu thật",
           "drift": "tỷ lệ nhận lời thực tế lệch dự đoán", "new_data": "đã có thêm dữ liệu mới"}


# ---------------------------------------------------------------- Số liệu thực tế theo tuần
def weekly_stats(now=None, weeks=WEEKS):
    """[{"week", "sent", "responded", "ai_sent", "ai_responded", "ai_expected"}] — tuần cũ trước."""
    from bloodbank.models import AuditLog, DonorCallout
    from bloodbank.services.donor_match import donor_code

    now = now or timezone.now()
    win = history.window()
    start = timezone.localdate(now) - timedelta(days=7 * weeks)
    callouts = {c.pk: c for c in DonorCallout.objects.filter(created_at__date__gte=start,
                                                             created_at__lte=now - win).select_related("hospital")}
    if not callouts:
        return []
    ai_info = {eid: (new or {}).get("ai") for eid, new in
               AuditLog.objects.filter(entity_type="donor_callouts", action="donor_callout",
                                       entity_id__in=list(callouts)).values_list("entity_id", "new_values")}
    who = history.recipients(callouts)
    acc = defaultdict(lambda: defaultdict(float))
    for cid, c in callouts.items():
        users = who.get(cid) or []
        if not users:
            continue
        yes = history.responders(c, users, win)
        day = timezone.localdate(c.created_at)
        w = acc[day - timedelta(days=day.weekday())]
        w["sent"] += len(users)
        w["responded"] += len(yes)
        ai = ai_info.get(cid)
        if ai and ai.get("probs"):
            probs = ai["probs"]
            for uid in users:
                p = probs.get(donor_code(c.hospital, uid))
                if p is None:
                    continue
                w["ai_sent"] += 1
                w["ai_expected"] += p
                w["ai_responded"] += uid in yes
    return [{"week": wk, **{k: (int(v) if k != "ai_expected" else round(v, 2)) for k, v in acc[wk].items()}}
            for wk in sorted(acc)]


def gap(weeks):
    """(lệch = (thực tế − dự đoán) ÷ số lời mời, số lời mời) trên RECENT_WEEKS tuần gần nhất có lời mời do AI xếp hạng."""
    recent = [w for w in weeks if w.get("ai_sent")][-RECENT_WEEKS:]
    sent = sum(w["ai_sent"] for w in recent)
    if not sent:
        return None, 0
    return (sum(w["ai_responded"] for w in recent) - sum(w["ai_expected"] for w in recent)) / sent, sent


def store_weekly(now=None):
    weeks = weekly_stats(now)
    calls, rows = history.size(now)
    registry.set_state("last_accuracy", {"date": timezone.localdate(now).isoformat(), "real_callouts": calls,
                                         "real_rows": rows,
                                         "weeks": [{**w, "week": w["week"].isoformat()} for w in weeks]})
    return weeks


def weekly(now=None):
    state = registry.state("last_accuracy")
    if not state or state.get("date") != timezone.localdate(now).isoformat():
        store_weekly(now)
        state = registry.state("last_accuracy")
    return [{**w, "week": date.fromisoformat(w["week"])} for w in state["weeks"]], state


# ---------------------------------------------------------------- Mỗi đêm
def _since(iso, now):
    return (now or timezone.now()) - datetime.fromisoformat(iso) if iso else None


def retrain_reason(now=None, drift=None, real=(0, 0)):
    from bloodbank.models import SystemSetting

    from . import training

    if not SystemSetting.get("donor_ai_auto_retrain"):
        return None
    current = registry.active_meta()
    if not current:
        return "first"
    since = _since((registry.last_run() or {}).get("at"), now)
    if since is not None and since < timedelta(days=MIN_GAP_DAYS):
        return None
    if current.get("synthetic"):
        enough = real[0] >= training.MIN_REAL_CALLOUTS and real[1] >= training.MIN_REAL_ROWS
        return "real_data" if enough else None
    g, sent = drift or (None, 0)
    if g is not None and sent >= MIN_DRIFT_INVITES and abs(g) > DRIFT_GAP:
        return "drift"
    age = _since(current.get("trained_at"), now)
    if age is not None and age >= timedelta(days=SystemSetting.get("donor_ai_retrain_days")):
        return "new_data"
    return None


def _retrain(reason):
    from . import training

    registry.clear_request()
    try:
        meta = training.run(log=log.info)
    except Exception as exc:                          # lỗi huấn luyện không được dừng các tác vụ khác
        log.exception("Huấn luyện AI gợi ý người hiến thất bại")
        registry.record_run({"version": None, "promoted": False, "source": None, "trigger": reason,
                             "reasons": [f"lỗi: {exc}"]})
        return "error"
    registry.record_run({**registry.last_run(), "trigger": reason})
    return "promoted" if meta["promoted"] else "kept"


def protect(drift, now=None):
    """Lệch quá PROTECT_GAP → tắt AI (danh sách quay về chấm điểm luật), báo Quản trị một lần."""
    from accounts.models import User
    from bloodbank.models import AuditLog, SystemSetting

    from .. import common

    g, sent = drift or (None, 0)
    if g is None or sent < MIN_PROTECT_INVITES or abs(g) <= PROTECT_GAP or not SystemSetting.get("donor_ai_enabled"):
        return False
    with common.business_transaction():
        row, _ = SystemSetting.objects.get_or_create(
            setting_key="donor_ai_enabled",
            defaults={"setting_value": False, "description": SystemSetting.DEFAULTS["donor_ai_enabled"][1]})
        row.setting_value = False
        row.save()
        AuditLog.objects.create(entity_type="system_settings", entity_id=0, action="update",
                                old_values={"value": True}, new_values={"value": False, "reason": "donor_ai_protect"})
        common.alert(list(User.objects.filter(role="admin", status="active")), "donor_ai_disabled",
                     "AI gợi ý người hiến đã tự tắt",
                     f"{RECENT_WEEKS} tuần gần nhất, tỷ lệ nhận lời thực tế lệch AI dự đoán {g:+.0%}. Danh sách gợi ý "
                     "đang xếp theo chấm điểm luật; xem Quản trị → AI gợi ý người hiến.")
    return True


def cleanup():
    import shutil

    for v in registry.versions()[KEEP_VERSIONS:]:
        if not v["active"]:
            shutil.rmtree(registry.versions_dir() / v["version"], ignore_errors=True)


def nightly_check(now=None):
    """Kết quả học lại ("promoted" / "kept" / "error") hoặc None nếu không học."""
    if not settings.FORECAST_SCHEDULED_TRAINING:
        return None
    if registry.training_requested():
        return _retrain("requested")
    today = timezone.localdate(now).isoformat()
    start, end = settings.FORECAST_TRAIN_HOURS
    if not start <= timezone.localtime(now).hour < end or (registry.state("last_check") or {}).get("date") == today:
        return None
    cleanup()
    weeks = store_weekly(now)
    drift = gap(weeks)
    real = history.size(now)
    registry.set_state("last_check", {"date": today, "gap": drift[0], "ai_sent": drift[1], "real_callouts": real[0],
                                      "real_rows": real[1]})
    protect(drift, now)
    reason = retrain_reason(now, drift, real)
    return _retrain(reason) if reason else None


# ---------------------------------------------------------------- Trang quản trị
def dashboard(now=None):
    from bloodbank.models import SystemSetting

    from . import model, predict, training

    meta = predict.active_meta()
    weeks, state = weekly(now)
    g, sent = gap(weeks)
    versions = registry.versions()[:KEEP_VERSIONS]
    for v in versions:
        v["scores"] = registry.scores(v)
    last = registry.last_run()
    for w in weeks:
        w["rate"] = w["responded"] / w["sent"] if w.get("sent") else None
        w["ai_rate"] = w["ai_responded"] / w["ai_sent"] if w.get("ai_sent") else None
        w["ai_pred"] = w["ai_expected"] / w["ai_sent"] if w.get("ai_sent") else None
    return {
        "enabled": bool(SystemSetting.get("donor_ai_enabled")), "ready": meta is not None, "meta": meta,
        "scores": registry.scores(meta), "labels": model.MODELS,
        "compare": [registry.scores(meta)[k] for k in model.MODELS if k in registry.scores(meta)], "versions": versions, "last": last,
        "last_at": datetime.fromisoformat(last["at"]) if last else None,
        "trigger": REASONS.get((last or {}).get("trigger")), "check": registry.state("last_check") or {},
        "requested": registry.training_requested(), "auto": bool(SystemSetting.get("donor_ai_auto_retrain")),
        "retrain_days": SystemSetting.get("donor_ai_retrain_days"),
        "explore_pct": round(100 * float(SystemSetting.get("donor_ai_explore_share") or 0)),
        "weeks": weeks, "gap": g, "gap_sent": sent, "drift_gap": DRIFT_GAP, "protect_gap": PROTECT_GAP,
        "recent_weeks": RECENT_WEEKS, "hours": settings.FORECAST_TRAIN_HOURS,
        "real_callouts": state.get("real_callouts", 0), "real_rows": state.get("real_rows", 0),
        "min_callouts": training.MIN_REAL_CALLOUTS, "min_rows": training.MIN_REAL_ROWS,
        "max_calibration": registry.MAX_CALIBRATION,
        "trained_at": datetime.fromisoformat(meta["trained_at"]) if meta and meta.get("trained_at") else None,
    }
