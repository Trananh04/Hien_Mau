"""Huấn luyện một lần: chọn dữ liệu → backtest → huấn luyện bản cuối → lưu phiên bản → chốt chặn → (dùng bản mới).

Nguồn dữ liệu (`source`):
  "db"   sổ kho thật (history.training_frame) — cần ≥ MIN_DB_SERIES chuỗi có ≥ MIN_DB_DAYS ngày;
  "csv"  file CSV (cột date, series|hospital, blood_group, demand; tùy chọn is_synthetic);
  "auto" dùng sổ kho nếu đủ, chưa đủ thì dùng dữ liệu mô phỏng (tự sinh nếu chưa có file) — hệ thống vẫn chạy được
         khi chưa có dữ liệu thật, và tự chuyển sang dữ liệu thật ở lần huấn luyện đầu tiên sau khi đủ.
Dùng chung cho `manage.py train_forecast` và tác vụ huấn luyện lại hằng tuần.
"""
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.utils import timezone

from . import features, history, model, registry, simulate
from .features import HISTORY_DAYS, HORIZON

MIN_DB_DAYS = 180            # ~6 tháng: đủ cho vài mốc backtest + 6 tuần dừng sớm
MIN_DB_SERIES = 3


class NotEnoughData(Exception):
    pass


def sim_path():
    return settings.FORECAST_MODEL_DIR / "sim" / "demand.csv"


def db_frame(end=None):
    end = end or timezone.localdate() - timedelta(days=1)            # hôm nay chưa hết ngày
    frame = history.training_frame(end, MIN_DB_DAYS)
    return frame, (frame["series"].nunique() if len(frame) else 0)


def load(source="auto", data=None, log=print):
    """(daily DataFrame đã đủ ngày, thông tin nguồn)."""
    if source in ("auto", "db") and not data:
        frame, n = db_frame()
        if n >= MIN_DB_SERIES:
            return features.fill_days(frame), {"source": "db", "synthetic": False, "data_file": "sổ kho",
                                               "series": int(n)}
        msg = (f"Sổ kho mới có {n} chuỗi đủ {MIN_DB_DAYS} ngày (cần ≥ {MIN_DB_SERIES})")
        if source == "db":
            raise NotEnoughData(msg)
        log(msg + " → dùng dữ liệu mô phỏng.")
    path = Path(data) if data else sim_path()
    if not path.exists():
        if data:
            raise NotEnoughData(f"Không thấy {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        simulate.simulate().to_csv(path, index=False)
        log(f"Chưa có dữ liệu mô phỏng → đã sinh {path}")
    raw = pd.read_csv(path, parse_dates=["date"])
    if "series" not in raw:
        raw["series"] = raw["hospital"]
    synthetic = bool(raw["is_synthetic"].max()) if "is_synthetic" in raw else False
    daily = features.fill_days(raw[["date", "series", "blood_group", "demand"]])
    return daily, {"source": "sim" if synthetic else "csv", "synthetic": synthetic, "data_file": path.name,
                   "series": int(daily["series"].nunique())}


def fold_count(daily, wanted):
    """Số mốc backtest vừa với độ dài dữ liệu (cần 28 ngày lịch sử + 6 tuần dừng sớm + ít nhất 4 tuần để học)."""
    span = (daily["date"].max() - daily["date"].min()).days + 1
    return max(2, min(wanted, (span - HISTORY_DAYS - HORIZON - model.VAL_DAYS - 28) // 14))


def run(source="auto", data=None, folds=12, promote=True, force=False, out=None, log=print):
    """Trả về metadata của bản vừa huấn luyện (gồm "version", "guard", "promoted"). `out` (thư mục) chỉ để thử:
    lưu thẳng vào đó, không qua phiên bản."""
    daily, info = load(source, data, log)
    t0 = time.time()
    examples = features.build_all(daily, simulate.tet_flags)
    log(f"Dữ liệu: {info['data_file']} · {info['series']} chuỗi · {daily['date'].nunique()} ngày · "
        f"{len(examples):,} dòng huấn luyện ({time.time() - t0:.1f}s)" + (" · MÔ PHỎNG" if info["synthetic"] else ""))
    meta = {**info, "rows": len(examples), "date_from": str(daily["date"].min().date()),
            "date_to": str(daily["date"].max().date())}
    folds = fold_count(daily, folds)
    log(f"Backtest trượt {folds} mốc, mỗi mốc 14 ngày:")
    summary, by_h, per_fold = model.backtest(examples, folds=folds, log=log)
    meta["backtest"] = summary.to_dict(orient="records")
    meta["folds"] = folds
    t0 = time.time()
    final = model.train(examples)
    meta["trees"] = int(final.best_iteration + 1)
    log(f"Huấn luyện bản cuối: {meta['trees']} cây ({time.time() - t0:.1f}s)")
    if out is not None:
        return model.save(final, out, meta)
    current = registry.active_meta()
    passed, reasons = registry.guard(meta, current)
    meta["guard"] = {"passed": passed, "reasons": reasons}
    version, meta = registry.save_version(final, meta)
    target = registry.versions_dir() / version
    summary.to_csv(target / "evaluation.csv", index=False)
    by_h.to_csv(target / "evaluation_by_h.csv", index=False)
    per_fold.to_csv(target / "evaluation_folds.csv", index=False)
    meta["promoted"] = bool(promote and (passed or force))
    if meta["promoted"]:
        registry.activate(version)
    registry.record_run({"version": version, "promoted": meta["promoted"], "reasons": reasons,
                         "source": info["source"]})
    return meta
