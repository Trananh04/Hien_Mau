"""Dự báo nhu cầu 14 ngày cho các dòng tồn kho của một bệnh viện, từ lịch sử XUẤT CHO NGƯỜI BỆNH trong sổ kho.

Chỉ dùng mô hình khi: Quản trị bật `forecast_ai_enabled`, có file mô hình hợp lệ, và dòng tồn có ≥ 28 ngày lịch sử
(tính từ phiếu đầu tiên). Ngược lại trả về {} cho dòng đó → trang Dự báo thiếu hụt dùng trung bình 28 ngày như cũ.
Nhu cầu lịch sử lấy từ history.py (cùng nguồn với trung bình 28 ngày và với lúc huấn luyện).
"""
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import history
from .constants import BLOOD_GROUPS, FEATURES, HISTORY_DAYS, HORIZON

_cache = {"mtime": None, "model": None, "meta": None}
_meta_cache = {"mtime": None, "meta": None}


def model_dir():
    return settings.FORECAST_MODEL_DIR


def loaded():
    """(mô hình, metadata) — tải lại khi file trên đĩa đổi (sau mỗi lần huấn luyện)."""
    path = model_dir() / "model.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _cache.update(mtime=None, model=None, meta=None)
        return None, None
    if _cache["mtime"] != mtime:
        from . import model as M

        model, meta = M.load(model_dir())
        _cache.update(mtime=mtime, model=model, meta=meta)
    return _cache["model"], _cache["meta"]


def active_meta():
    """Metadata của mô hình đang dùng nếu hợp lệ — chỉ đọc file JSON (không nạp xgboost), lưu đệm theo mtime."""
    try:
        mtime = (model_dir() / "model.json").stat().st_mtime
    except OSError:
        return None
    if _meta_cache["mtime"] != mtime:
        try:
            meta = json.loads((model_dir() / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = None
        if meta and (meta.get("features") != FEATURES or meta.get("blood_groups") != BLOOD_GROUPS):
            meta = None
        _meta_cache.update(mtime=mtime, meta=meta)
    return _meta_cache["meta"]


def enabled():
    from bloodbank.models import SystemSetting

    return bool(SystemSetting.get("forecast_ai_enabled")) and active_meta() is not None


def forecast(hospital, now=None):
    """{(nhóm máu, quy cách): mảng 14 số — nhu cầu dự báo từ ngày mai}; {} nếu không dùng mô hình."""
    if not enabled():
        return {}
    import numpy as np
    import pandas as pd

    from . import model as M
    from .features import build
    from .simulate import tet_flags

    model, _ = loaded()
    if model is None:
        return {}
    today = timezone.localdate(now)
    recent = history.recent(hospital, today, HISTORY_DAYS)
    # Chỉ chuỗi đã có sổ kho đủ 28 ngày (trước đó là "chưa dùng hệ thống", không phải "nhu cầu bằng 0")
    first = {(bg, spec): d for (_, bg, spec), d in history.first_seen([hospital.pk]).items()}
    oldest_ok = today - timedelta(days=HISTORY_DAYS - 1)
    out = {}
    dates = pd.date_range(today - timedelta(days=HISTORY_DAYS - 1), today, freq="D")
    for key, demand in recent.items():
        if key not in first or first[key] > oldest_ok:
            continue
        rows = build(pd.DataFrame({"date": dates, "demand": demand}), tet_flags, with_target=False,
                     origins=[HISTORY_DAYS - 1])
        rows["blood_group"] = pd.Categorical([key[0]] * len(rows), categories=M.BLOOD_GROUPS)
        rows = rows.sort_values("h")
        out[key] = np.clip(M.predict(model, rows)["XGB"], 0, None)
        assert len(out[key]) == HORIZON
    return out
