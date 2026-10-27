"""Dự báo nhu cầu 14 ngày cho các dòng tồn kho của một bệnh viện, từ lịch sử XUẤT CHO NGƯỜI BỆNH trong sổ kho.

Chỉ dùng mô hình khi: Quản trị bật `forecast_ai_enabled`, có file mô hình hợp lệ, và dòng tồn có ≥ 28 ngày lịch sử
(tính từ phiếu đầu tiên). Ngược lại trả về {} cho dòng đó → trang Dự báo thiếu hụt dùng trung bình 28 ngày như cũ.
Hạn chế hiện tại: nhu cầu lịch sử = lượng đã xuất (chưa cộng phần yêu cầu chưa đáp ứng).
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from django.conf import settings
from django.db.models import Min, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

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


def daily_issues(hospital, today, days):
    """{(nhóm máu, quy cách): mảng `days` số đơn vị xuất cho người bệnh/ngày, kết thúc tại `today`}."""
    from bloodbank.models import StockTxn

    start = today - timedelta(days=days - 1)
    tz = timezone.get_current_timezone()
    rows = (StockTxn.objects.filter(stock__hospital=hospital, txn_type=StockTxn.Type.ISSUE,
                                    occurred_at__date__gte=start)
            .annotate(day=TruncDate("occurred_at", tzinfo=tz))
            .values("stock__blood_group", "stock__product_spec", "day").annotate(n=Sum("quantity_change")))
    out = {}
    for r in rows:
        key = (r["stock__blood_group"], r["stock__product_spec"])
        arr = out.setdefault(key, np.zeros(days))
        i = (r["day"] - start).days
        if 0 <= i < days:
            arr[i] += -r["n"]
    return out


def forecast(hospital, now=None):
    """{(nhóm máu, quy cách): mảng 14 số — nhu cầu dự báo từ ngày mai}; {} nếu không dùng mô hình."""
    if not enabled():
        return {}
    from bloodbank.models import StockTxn

    model, _ = loaded()
    today = timezone.localdate(now)
    history = daily_issues(hospital, today, HISTORY_DAYS)
    # Chỉ chuỗi đã có sổ kho đủ 28 ngày (trước đó là "chưa dùng hệ thống", không phải "nhu cầu bằng 0")
    first = dict(((r["stock__blood_group"], r["stock__product_spec"]), r["first"]) for r in
                 StockTxn.objects.filter(stock__hospital=hospital).values("stock__blood_group", "stock__product_spec")
                 .annotate(first=Min("occurred_at")))
    oldest_ok = today - timedelta(days=HISTORY_DAYS - 1)
    out = {}
    dates = pd.date_range(today - timedelta(days=HISTORY_DAYS - 1), today, freq="D")
    for key, demand in history.items():
        if key not in first or timezone.localdate(first[key]) > oldest_ok:
            continue
        rows = build(pd.DataFrame({"date": dates, "demand": demand}), tet_flags, with_target=False,
                     origins=[HISTORY_DAYS - 1])
        rows["blood_group"] = pd.Categorical([key[0]] * len(rows), categories=M.BLOOD_GROUPS)
        rows = rows.sort_values("h")
        out[key] = np.clip(M.predict(model, rows)["XGB"], 0, None)
        assert len(out[key]) == HORIZON
    return out
