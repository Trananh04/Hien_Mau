"""Lịch sử NHU CẦU thường ngày theo ngày, lấy từ sổ kho — một nguồn duy nhất cho trang Dự báo, dự đoán và huấn luyện.

nhu cầu ngày d (nhóm máu × quy cách) =
    phiếu XUẤT ngày d không gắn ca mổ đã khai (ca đã khai nằm ở phần "có kế hoạch" → tránh cộng trùng)
                     và không gắn yêu cầu người cần máu (phần này tính ở dòng dưới)
  + số đơn vị của yêu cầu người cần máu được XÁC MINH ngày d — tính MỘT lần, dù sau đó cấp đủ, thiếu hay bị hủy,
    nên lượng "cần mà kho không có" cũng được đếm (nếu chỉ đếm lượng đã xuất, mô hình sẽ học rằng thiếu máu = ít nhu cầu).
Yêu cầu chỉ ghi chế phẩm (không ghi quy cách) → gán vào quy cách bệnh viện đó xuất nhiều nhất của chế phẩm ấy.
Một chuỗi chỉ "có lịch sử" từ phiếu kho đầu tiên của nó; trước đó là chưa dùng hệ thống, không phải nhu cầu bằng 0.
"""
from collections import defaultdict
from datetime import timedelta

import numpy as np
from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone


def _tz():
    return timezone.get_current_timezone()


def _main_spec(hospital_ids):
    """{(bệnh viện, chế phẩm): quy cách xuất nhiều nhất} — để gán yêu cầu người cần máu vào một dòng tồn."""
    from bloodbank.models import ProductSpec, StockTxn

    best = {}
    rows = (StockTxn.objects.filter(stock__hospital__in=hospital_ids, txn_type=StockTxn.Type.ISSUE)
            .values("stock__hospital", "stock__product_spec__product", "stock__product_spec")
            .annotate(n=Count("id")).order_by("-n"))
    for r in rows:
        best.setdefault((r["stock__hospital"], r["stock__product_spec__product"]), r["stock__product_spec"])
    fallback = {}
    for s in ProductSpec.objects.filter(is_active=True).order_by("pk"):
        fallback.setdefault(s.product_id, s.pk)
    return best, fallback


def daily_demand(start, end, hospitals=None):
    """{(bệnh viện id, nhóm máu, quy cách id): mảng số đơn vị/ngày từ `start` đến `end` (gồm cả hai đầu)}."""
    from bloodbank.models import PatientRequest, StockTxn

    days = (end - start).days + 1
    out = defaultdict(lambda: np.zeros(days))
    txns = StockTxn.objects.filter(txn_type=StockTxn.Type.ISSUE, demand__isnull=True, patient_request__isnull=True,
                                   occurred_at__date__gte=start, occurred_at__date__lte=end)
    prqs = PatientRequest.objects.filter(verified_at__date__gte=start, verified_at__date__lte=end,
                                         blood_group__isnull=False).exclude(status=PatientRequest.Status.REJECTED)
    if hospitals is not None:
        txns, prqs = txns.filter(stock__hospital__in=hospitals), prqs.filter(hospital__in=hospitals)
    for r in (txns.annotate(day=TruncDate("occurred_at", tzinfo=_tz()))
              .values("stock__hospital", "stock__blood_group", "stock__product_spec", "day")
              .annotate(n=Sum("quantity_change"))):
        out[(r["stock__hospital"], r["stock__blood_group"], r["stock__product_spec"])][(r["day"] - start).days] -= r["n"]
    prq_rows = list(prqs.annotate(day=TruncDate("verified_at", tzinfo=_tz()))
                    .values("hospital", "blood_group", "blood_product", "day").annotate(n=Sum("quantity_units")))
    if prq_rows:
        best, fallback = _main_spec({r["hospital"] for r in prq_rows})
        for r in prq_rows:
            spec = best.get((r["hospital"], r["blood_product"])) or fallback.get(r["blood_product"])
            if spec is not None:
                out[(r["hospital"], r["blood_group"], spec)][(r["day"] - start).days] += r["n"] or 0
    return dict(out)


def first_seen(hospitals=None):
    """{(bệnh viện id, nhóm máu, quy cách id): ngày có phiếu kho đầu tiên}."""
    from bloodbank.models import StockTxn

    qs = StockTxn.objects.all() if hospitals is None else StockTxn.objects.filter(stock__hospital__in=hospitals)
    return {(r["stock__hospital"], r["stock__blood_group"], r["stock__product_spec"]): timezone.localdate(r["first"])
            for r in qs.values("stock__hospital", "stock__blood_group", "stock__product_spec")
            .annotate(first=Min("occurred_at"))}


def recent(hospital, today, days):
    """{(nhóm máu, quy cách): mảng `days` ngày kết thúc tại `today`} cho một bệnh viện."""
    data = daily_demand(today - timedelta(days=days - 1), today, hospitals=[hospital.pk])
    return {(bg, spec): arr for (_, bg, spec), arr in data.items()}


def training_frame(end, min_days):
    """DataFrame (date, series, blood_group, demand) cho mọi chuỗi có ≥ `min_days` ngày lịch sử tính đến `end`
    (thường là hôm qua — hôm nay chưa hết ngày). Mỗi chuỗi bắt đầu từ ngày có phiếu kho đầu tiên."""
    import pandas as pd

    first = {k: d for k, d in first_seen().items() if (end - d).days + 1 >= min_days}
    if not first:
        return pd.DataFrame(columns=["date", "series", "blood_group", "demand"])
    start = min(first.values())
    data = daily_demand(start, end)
    dates = pd.date_range(start, end, freq="D")
    parts = []
    for key, d0 in first.items():
        arr = data.get(key, np.zeros(len(dates)))
        i = (d0 - start).days
        parts.append(pd.DataFrame({"date": dates[i:], "series": f"H{key[0]}-S{key[2]}", "blood_group": key[1],
                                   "demand": arr[i:]}))
    return pd.concat(parts, ignore_index=True)
