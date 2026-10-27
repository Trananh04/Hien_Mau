"""Dự báo thiếu hụt (kế hoạch vài ngày – vài tuần; ca cần máu trong vài giờ đi theo nút Khẩn cấp, không ở đây).

Mỗi dòng = nhóm máu × quy cách:
  dùng/ngày   = lượng XUẤT CHO NGƯỜI BỆNH trung bình `WINDOW_DAYS` ngày gần nhất (không tính điều chuyển, điều chỉnh);
  cần 14 ngày = dùng/ngày × 14 + nhu cầu CÓ KẾ HOẠCH (đã khai, cần trong 14 ngày, không phải ca khẩn);
  đủ dùng     = khả dụng ÷ dùng/ngày;  thiếu dự kiến = MAX(0, cần 14 ngày − khả dụng).
Mức: "soon" (hết trong < 7 ngày hoặc thiếu ngay) → mời người hiến; "plan" (7–14 ngày) → tạo đợt hiến; "ok".

Mốc cơ sở là trung bình động. Khi Quản trị bật `forecast_ai_enabled` và có mô hình đã huấn luyện
(`manage.py train_forecast`), dòng nào đủ 28 ngày lịch sử dùng dự báo XGBoost từng ngày (forecast_ml) thay cho trung
bình: "cần 14 ngày" = tổng dự báo 14 ngày, "đủ dùng" = ngày nhu cầu cộng dồn vượt tồn khả dụng. Dòng không đủ điều
kiện vẫn dùng trung bình — giao diện, ngưỡng và gợi ý người hiến không đổi.
"""
import math
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from bloodbank.models import Demand, ProductSpec, Stock, StockTxn

WINDOW_DAYS = 28
HORIZON_DAYS = 14
SOON_DAYS = 7


def daily_usage(hospital, now=None):
    """{(nhóm máu, quy cách): đơn vị dùng / ngày} — trung bình xuất cho người bệnh trong WINDOW_DAYS ngày."""
    since = (now or timezone.now()) - timedelta(days=WINDOW_DAYS)
    rows = (StockTxn.objects.filter(stock__hospital=hospital, txn_type=StockTxn.Type.ISSUE, occurred_at__gte=since)
            .values("stock__blood_group", "stock__product_spec").annotate(n=Sum("quantity_change")))
    return {(r["stock__blood_group"], r["stock__product_spec"]): -r["n"] / WINDOW_DAYS for r in rows}


def _days_covered(available, daily):
    """Số ngày tồn khả dụng đủ dùng theo nhu cầu dự báo từng ngày (nội suy trong ngày; quá 14 ngày thì ngoại suy)."""
    used = 0.0
    for i, d in enumerate(daily):
        if used + d > available:
            return i + (available - used) / d
        used += d
    mean = sum(daily) / len(daily)
    return len(daily) + (available - used) / mean if mean > 0 else None


def forecast(hospital, now=None):
    from bloodbank.services.forecast_ml import predict as ml

    now = now or timezone.now()
    today = timezone.localdate(now)
    usage = daily_usage(hospital, now)
    ai = ml.forecast(hospital, now)
    horizon = now + timedelta(days=HORIZON_DAYS)
    planned = {}
    for d in Demand.objects.filter(hospital=hospital, status=Demand.Status.ACTIVE, is_emergency=False):
        if d.needed_by is None or d.needed_by <= horizon:
            key = (d.blood_group, d.product_spec_id)
            p = planned.setdefault(key, {"qty": 0, "first": None})
            p["qty"] += d.required_quantity
            if d.needed_by and (p["first"] is None or d.needed_by < p["first"]):
                p["first"] = d.needed_by
    stocks = {(s.blood_group, s.product_spec_id): s for s in Stock.objects.filter(hospital=hospital)}
    keys = set(usage) | set(ai) | set(planned) | {k for k, s in stocks.items() if s.min_stock_level}
    specs = {s.pk: s for s in ProductSpec.objects.select_related("product").filter(pk__in={k[1] for k in keys})}
    rows = []
    for key in keys:
        bg, spec_id = key
        st = stocks.get(key)
        available = st.available if st else 0
        plan = planned.get(key, {"qty": 0, "first": None})
        daily = ai.get(key)
        if daily is not None:                       # AI: nhu cầu từng ngày 14 ngày tới
            per_day = float(daily.mean())
            need = float(daily.sum()) + plan["qty"]
            days = _days_covered(available, daily) if per_day > 0 else None
        else:                                       # trung bình 28 ngày
            per_day = usage.get(key, 0.0)
            need = per_day * HORIZON_DAYS + plan["qty"]
            days = available / per_day if per_day > 0 else None
        shortage = max(0, math.ceil(need - available))
        run_out = today + timedelta(days=int(days)) if days is not None and days < 60 else None
        below_min = bool(st and st.min_stock_level and available < st.min_stock_level)
        planned_soon = plan["qty"] > available and (plan["first"] is None or plan["first"] <= now + timedelta(days=SOON_DAYS))
        if planned_soon or (days is not None and days < SOON_DAYS) or (per_day > 0 and available == 0):
            level = "soon"
        elif shortage or below_min or (days is not None and days < HORIZON_DAYS):
            level = "plan"
        else:
            level = "ok"
        rows.append({
            "blood_group": bg, "spec": specs[spec_id], "available": available, "per_day": per_day,
            "planned": plan["qty"], "planned_first": plan["first"], "need": math.ceil(need), "shortage": shortage,
            "days": days, "run_out": run_out, "below_min": below_min, "min_level": st.min_stock_level if st else 0,
            "method": "ai" if daily is not None else "avg",
            "daily": [round(float(x), 1) for x in daily] if daily is not None else None,
            "level": level, "cover_pct": min(100, round(100 * days / HORIZON_DAYS)) if days is not None else 100,
            # tạo đợt hiến trước ngày hết máu ~ 5 ngày (xét nghiệm, nhập kho) — không sớm hơn ngày mai
            "campaign_by": max(today + timedelta(days=1), run_out - timedelta(days=5)) if run_out else None,
        })
    order = {"soon": 0, "plan": 1, "ok": 2}
    rows.sort(key=lambda r: (order[r["level"]], r["days"] if r["days"] is not None else 999, -r["shortage"],
                             r["blood_group"]))
    return rows


def summary(rows):
    return {"soon": sum(1 for r in rows if r["level"] == "soon"), "plan": sum(1 for r in rows if r["level"] == "plan")}
