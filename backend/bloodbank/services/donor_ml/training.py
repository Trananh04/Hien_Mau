"""Huấn luyện một lần: chọn dữ liệu → backtest 3 cách (luật / LR / XGB) → chọn cách tốt nhất → chốt chặn → lưu phiên bản.

Nguồn dữ liệu (`source`):
  "db"   lịch sử kêu gọi thật (history.dataset) — cần ≥ MIN_REAL_CALLOUTS lần kêu gọi và ≥ MIN_REAL_ROWS lời mời đã
         biết kết quả;
  "sim"  dữ liệu mô phỏng (simulate.py, sinh một lần rồi lưu file);
  "auto" dùng dữ liệu thật nếu đủ, chưa đủ thì mô phỏng — hệ thống vẫn có mô hình để demo khi chưa có dữ liệu thật và tự
         chuyển sang dữ liệu thật ở lần học lại đầu tiên sau khi đủ (monitor.retrain_reason "real_data").
Dùng chung cho `manage.py train_donor_model` và tác vụ học lại tự động.
"""
import time

import pandas as pd
from django.conf import settings

from . import history, model, registry, simulate

MIN_REAL_CALLOUTS = 30
MIN_REAL_ROWS = 300


class NotEnoughData(Exception):
    pass


def sim_path():
    return settings.DONOR_AI_MODEL_DIR / "sim" / "invites.csv"


def _normalize(df):
    df = df.copy()
    df["at"] = pd.to_datetime(df["at"], utc=True)
    for col in model.FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["label"] = df["label"].astype(int)
    return df


def load(source="auto", log=print):
    """(DataFrame lời mời, thông tin nguồn)."""
    if source in ("auto", "db"):
        calls, rows = history.size()
        if calls >= MIN_REAL_CALLOUTS and rows >= MIN_REAL_ROWS:
            return _normalize(history.dataset()), {"source": "db", "synthetic": False, "data_file": "lịch sử kêu gọi"}
        msg = (f"Lịch sử thật mới có {calls} lần kêu gọi / {rows} lời mời đã biết kết quả "
               f"(cần ≥ {MIN_REAL_CALLOUTS} / {MIN_REAL_ROWS})")
        if source == "db":
            raise NotEnoughData(msg)
        log(msg + " → dùng dữ liệu mô phỏng.")
    path = sim_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        simulate.simulate().to_csv(path, index=False)
        log(f"Chưa có dữ liệu mô phỏng → đã sinh {path}")
    return _normalize(pd.read_csv(path)), {"source": "sim", "synthetic": True, "data_file": path.name}


def run(source="auto", folds=4, promote=True, force=False, log=print):
    """Trả về metadata bản vừa huấn luyện (gồm "version", "chosen", "guard", "promoted")."""
    from bloodbank.models import SystemSetting

    df, info = load(source, log)
    window_days = SystemSetting.get("donor_invite_response_days")
    max_90d = max(1, int(SystemSetting.get("donor_invite_max_90_days")))
    calls = df["callout_id"].nunique()
    log(f"Dữ liệu: {info['data_file']} · {calls:,} lần kêu gọi · {len(df):,} lời mời · tỷ lệ nhận lời "
        f"{df['label'].mean():.1%}" + (" · MÔ PHỎNG" if info["synthetic"] else ""))
    if df["label"].nunique() < 2:
        raise NotEnoughData("Dữ liệu chỉ có một loại kết quả (toàn nhận lời hoặc toàn không) — chưa học được.")
    meta = {**info, "rows": len(df), "callouts": int(calls), "base_rate": float(df["label"].mean()),
            "date_from": str(df["at"].min().date()), "date_to": str(df["at"].max().date())}
    t0 = time.time()
    log(f"Backtest {folds} đoạn theo thời gian (nửa sau của dữ liệu):")
    summary, per_fold, _ = model.backtest(df, window_days, max_90d, folds=folds, log=log)
    clean = lambda records: [{k: model._clean(v) for k, v in r.items()} for r in records]   # NaN → None (JSON)
    meta["backtest"] = clean(summary.to_dict(orient="records"))
    meta["folds"] = clean(per_fold.to_dict(orient="records"))
    meta["chosen"] = registry.best_kind(meta)
    log(f"Backtest xong ({time.time() - t0:.1f}s). Chọn: {model.MODELS.get(meta['chosen'], '—')}")
    if not meta["chosen"]:
        raise NotEnoughData("Không đủ dữ liệu để backtest.")
    final = model.train(df, meta["chosen"])
    current = registry.active_meta()
    passed, reasons = registry.guard(meta, current)
    meta["guard"] = {"passed": passed, "reasons": reasons}
    version, meta = registry.save_version(final, meta)
    meta["promoted"] = bool(promote and (passed or force))
    if meta["promoted"]:
        registry.activate(version)
    registry.record_run({"version": version, "promoted": meta["promoted"], "reasons": reasons,
                         "source": info["source"], "chosen": meta["chosen"]})
    return meta
