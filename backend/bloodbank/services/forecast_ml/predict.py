"""Dự báo nhu cầu 14 ngày cho các dòng tồn kho của một bệnh viện, từ lịch sử XUẤT CHO NGƯỜI BỆNH trong sổ kho.

Chỉ dùng mô hình khi: Quản trị bật `forecast_ai_enabled`, có file mô hình hợp lệ, và dòng tồn có ≥ 28 ngày lịch sử
(tính từ phiếu đầu tiên). Ngược lại trả về {} cho dòng đó → trang Dự báo thiếu hụt dùng trung bình 28 ngày như cũ.
Nhu cầu lịch sử lấy từ history.py (cùng nguồn với trung bình 28 ngày và với lúc huấn luyện).
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from django.conf import settings
from django.utils import timezone

from . import history
from . import model as M
from .features import HISTORY_DAYS, HORIZON, build
from .simulate import tet_flags

_cache = {"mtime": None, "model": None, "meta": None}


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
        model, meta = M.load(model_dir())
        _cache.update(mtime=mtime, model=model, meta=meta)
    return _cache["model"], _cache["meta"]


def enabled():
    from bloodbank.models import SystemSetting

    return bool(SystemSetting.get("forecast_ai_enabled")) and loaded()[0] is not None


def forecast(hospital, now=None):
    """{(nhóm máu, quy cách): mảng 14 số — nhu cầu dự báo từ ngày mai}; {} nếu không dùng mô hình."""
    if not enabled():
        return {}
    model, _ = loaded()
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
