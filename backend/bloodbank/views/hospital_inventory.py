"""SCR-30..33: tồn kho, phiếu nhập/xuất/điều chỉnh, sổ kho, nhu cầu & thiếu hụt."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import BLOOD_GROUPS
from bloodbank.forms import DemandForm
from bloodbank.models import Demand, Donation, PatientRequest, Product, ProductSpec, Stock, StockTxn
from bloodbank.permissions import staff_required
from bloodbank.services import inventory as inv
from bloodbank.services import callout, donor_match, lab
from bloodbank.services import forecast as fc
from bloodbank.services.common import BusinessError

from .helpers import attempt, date_or_none, int_or_none, new_key, paginate, safe_next



@staff_required
def stock(request):
    """Ma trận nhóm máu × chế phẩm/quy cách; nhân viên sửa nhanh Chia sẻ/Tối thiểu."""
    product_id = request.GET.get("product")
    return render(request, "hospital/stock.html", {
        **inv.stock_overview(request.hospital, product_id),
        "products": Product.objects.filter(is_active=True), "product_id": product_id,
        "can_edit": True, "blood_groups": BLOOD_GROUPS,
    })


@staff_required
@require_POST
def stock_settings(request, pk):
    attempt(request, lambda: inv.update_stock_settings(request.staff, pk, request.POST.get("shareable_quantity"),
                                                       request.POST.get("min_stock_level"), request.POST.get("version"),
                                                       request), "Đã cập nhật.")
    return safe_next(request, "bloodbank:stock")


@staff_required
@require_POST
def stock_threshold(request):
    """Khai mức tối thiểu/chia sẻ cho khóa chưa có dòng tồn."""
    attempt(request, lambda: inv.ensure_stock_row(request.staff, request.POST.get("product_spec_id"),
                                                  request.POST.get("blood_group"), request.POST.get("min_stock_level"),
                                                  request.POST.get("shareable_quantity"), request), "Đã lưu mức tồn.")
    return redirect("bloodbank:stock")


TXN_FORMS = {"nhap": "receive", "xuat": "issue", "dieu-chinh": "adjust"}


@staff_required
def stock_txn_form(request, kind):
    """SCR-31: phiếu nhập / xuất / điều chỉnh có xem trước tồn trước/sau."""
    if kind not in TXN_FORMS:
        return redirect("bloodbank:stock")
    mode = TXN_FORMS[kind]
    h = request.hospital
    data = request.POST.dict() if request.method == "POST" else {}
    if request.method == "POST":
        key = data.get("idempotency_key")
        try:
            if mode == "receive":
                txn = inv.receive(request.staff, data.get("product_spec_id"), data.get("blood_group"), data.get("quantity"),
                                  key, data.get("note"), request)
            elif mode == "issue":
                txn = inv.issue(request.staff, data.get("stock_id"), data.get("quantity"), key, data.get("purpose"),
                                data.get("patient_request_id") or None, request)
            else:
                txn = inv.adjust(request.staff, data.get("stock_id"), data.get("direction"), data.get("quantity"),
                                 data.get("reason"), data.get("note"), key, data.get("counted"), request)
        except BusinessError as exc:
            messages.error(request, exc.message)
        else:
            msg = "Phiếu này đã được ghi trước đó (gửi lại cùng mã), không ghi trùng." if txn.replayed else "Đã ghi phiếu."
            messages.success(request, f"{msg} Tồn sau: {txn.quantity_after} đơn vị.")
            return redirect("bloodbank:stock_ledger")
    stocks = Stock.objects.filter(hospital=h).select_related("product_spec__product").order_by(
        "product_spec__product__name", "blood_group")
    if mode == "issue":
        stocks = [s for s in stocks if s.available > 0] or list(stocks)
    initial_stock = request.GET.get("stock") or data.get("stock_id")
    prqs = (PatientRequest.objects.filter(hospital=h, status__in=PatientRequest.ACTIVE_STATUSES)
            .select_related("blood_product").order_by("-created_at"))
    return render(request, "hospital/stock_txn_form.html", {
        "mode": mode, "kind": kind, "stocks": stocks, "specs": ProductSpec.objects.select_related("product").filter(
            is_active=True, product__is_active=True), "products": Product.objects.filter(is_active=True),
        "blood_groups": BLOOD_GROUPS, "reasons": [r for r in StockTxn.Reason.choices if r[0] != "transfer_shortfall"],
        "key": data.get("idempotency_key") or new_key(), "data": data, "initial_stock": initial_stock,
        "patient_requests": prqs, "initial_prq": request.GET.get("patient_request") or data.get("patient_request_id"),
    })


@staff_required
def stock_ledger(request):
    qs = StockTxn.objects.filter(stock__hospital=request.hospital).select_related(
        "stock__product_spec__product", "performed_by", "offer__request", "patient_request", "donation")
    f = {k: request.GET.get(k) or "" for k in ("type", "blood_group", "spec", "from", "to", "stock")}
    if f["type"]:
        qs = qs.filter(txn_type=f["type"])
    if f["blood_group"]:
        qs = qs.filter(stock__blood_group=f["blood_group"])
    # Giá trị lọc sai kiểu (id không phải số, ngày không hợp lệ) → bỏ qua bộ lọc đó thay vì lỗi 500
    if int_or_none(f["spec"]):
        qs = qs.filter(stock__product_spec_id=int_or_none(f["spec"]))
    if int_or_none(f["stock"]):
        qs = qs.filter(stock_id=int_or_none(f["stock"]))
    if date_or_none(f["from"]):
        qs = qs.filter(occurred_at__date__gte=date_or_none(f["from"]))
    if date_or_none(f["to"]):
        qs = qs.filter(occurred_at__date__lte=date_or_none(f["to"]))
    return render(request, "hospital/stock_ledger.html", {
        "page": paginate(request, qs.order_by("-occurred_at", "-id"), 30), "f": f, "types": StockTxn.Type.choices,
        "blood_groups": BLOOD_GROUPS, "specs": ProductSpec.objects.select_related("product"),
    })


@staff_required
def demands(request, pk=None):
    """Dự báo thiếu hụt (kế hoạch): đủ dùng bao nhiêu ngày, thiếu dự kiến 14 ngày, việc nên làm; khai nhu cầu có kế hoạch.

    Ca cần máu trong vài giờ không xử lý ở đây — dùng nút Khẩn cấp (ca khẩn).
    """
    h = request.hospital
    demand = get_object_or_404(Demand, pk=pk, hospital=h) if pk else None
    initial = {}
    if demand:
        initial = {"blood_group": demand.blood_group, "product_spec_id": demand.product_spec_id,
                   "required_quantity": demand.required_quantity, "needed_by": demand.needed_by, "note": demand.note}
    form = DemandForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        ok, _ = attempt(request, lambda: inv.save_demand(request.staff, form.cleaned_data, demand, request),
                        "Đã lưu nhu cầu.")
        if ok:
            return redirect("bloodbank:demands")
    status = request.GET.get("status", "active")
    qs = (Demand.objects.filter(hospital=h, is_emergency=False).select_related("product_spec__product")
          .order_by("needed_by", "-created_at"))
    if status:
        qs = qs.filter(status=status)
    rows = fc.forecast(h)
    return render(request, "hospital/demands.html", {
        "form": form, "demand": demand, "page": paginate(request, qs, 20), "status": status,
        "rows": rows, "sum": fc.summary(rows), "window": fc.WINDOW_DAYS, "horizon": fc.HORIZON_DAYS,
        "campaign": callout.next_campaign(h), "ai": _ai_info(rows),
        "groups": [{"label": "Cần xử lý", "rows": [r for r in rows if r["level"] != "ok"]},
                   {"label": "Đủ dùng", "rows": [r for r in rows if r["level"] == "ok"]}],
        "any_planned": any(r["planned"] for r in rows),
    })


def _ai_info(rows):
    """Thông tin mô hình AI cho trang Dự báo thiếu hụt — chỉ khi có dòng thực sự dùng dự báo AI."""
    from bloodbank.services.forecast_ml import predict as ml

    if not any(r.get("method") == "ai" for r in rows):
        return None
    _, meta = ml.loaded()
    scores = {r["model"]: r for r in meta.get("backtest", [])}

    def pct(name, key):
        v = scores.get(name, {}).get(key)
        return v * 100 if v is not None else None
    return {"trained_at": meta.get("trained_at", ""), "synthetic": meta.get("synthetic", True),
            "wape": pct("XGB", "wape"), "wape_b0": pct("B0", "wape"),
            # sai số TỔNG 14 ngày — đúng con số dùng để so với tồn kho
            "wape14": pct("XGB", "wape_14d_total"), "wape14_b0": pct("B0", "wape_14d_total")}


@staff_required
def donor_suggest(request):
    """Gợi ý người hiến cho một nhóm máu đang thiếu: xếp hạng, mã ẩn danh, lý do; chọn sẵn số người nên mời.

    `mode=urgent` (kêu gọi khẩn): ưu tiên người gần, mặc định bán kính 10 km, mời đến bệnh viện ngay hôm nay.
    """
    h = request.hospital
    bg = request.GET.get("blood_group")
    if bg not in dict(BLOOD_GROUPS):
        messages.error(request, "Chọn nhóm máu cần kêu gọi từ bảng thiếu hụt.")
        return redirect("bloodbank:demands")
    mode = donor_match.mode_of(request.GET.get("mode"))
    raw_radius = request.GET.get("radius")
    radius = (callout.default_radius(h, mode) if raw_radius is None
              else donor_match.radius_or_none(raw_radius, h))
    rows_short = [r for r in inv.shortages(h) if r["blood_group"] == bg]
    if mode == "urgent":
        shortage = (sum(r["shortage"] for r in rows_short if r["urgent"])
                    + sum(p["shortage"] for p in inv.urgent_requests(h) if p["blood_group"] == bg))
    else:
        shortage = 0
    shortage = shortage or sum(r["shortage"] for r in rows_short)
    case_pk = int_or_none(request.GET.get("ca"))
    if int_or_none(request.GET.get("thieu")):
        shortage = int_or_none(request.GET.get("thieu"))    # từ dự báo (thiếu dự kiến) hoặc ca khẩn (phần bệnh viện chưa lo)
    rows = donor_match.suggest(h, bg, radius, mode=mode)
    stats = donor_match.response_stats(h)
    n_suggest = min(donor_match.suggested_count(shortage, stats["rate"], mode), len(rows))
    for i, r in enumerate(rows):
        r["preselected"] = i < n_suggest
    return render(request, "hospital/donor_suggest.html", {
        "blood_group": bg, "mode": mode, "radius": radius, "radius_choices": donor_match.RADIUS_CHOICES,
        "can_radius": h.latitude is not None, "shortage": shortage, "rows": rows, "stats": stats,
        "n_suggest": n_suggest, "max_send": donor_match.MAX_SEND,
        "rate_pct": round(100 * (stats["rate"] or donor_match.DEFAULT_RESPONSE_RATE)
                          * donor_match.MODES[mode]["rate_factor"]),
        "last_callout": callout.last_callout(h, bg),
        "back_url": reverse("bloodbank:emergency_case", args=[case_pk]) if case_pk else None,
    })


@staff_required
@require_POST
def donor_callout(request):
    bg = request.POST.get("blood_group")
    mode = donor_match.mode_of(request.POST.get("mode"))
    radius = donor_match.radius_or_none(request.POST.get("radius"), request.hospital)

    def done(res):
        msg = f"Đã gửi lời mời {'khẩn ' if mode == 'urgent' else ''}nhóm {bg} tới {res[0]} người hiến"
        if res[2]:
            msg += f" ({res[2]} người đã chọn không còn đủ điều kiện nên được bỏ qua)"
        if mode == "urgent":
            return msg + ". Máu hiến mới còn phải xét nghiệm, nên vẫn cần xin hỗ trợ liên viện cho ca cần ngay."
        if res[1]:
            return msg + f", kèm đợt hiến \"{res[1].name}\"."
        return msg + ". Chưa có đợt hiến đang mở, nên tạo một đợt để người hiến đăng ký."

    attempt(request, lambda: callout.donor_callout(request.staff, bg, request.POST.getlist("code"), radius, request,
                                                   mode), done)
    return safe_next(request, "bloodbank:demands")


@staff_required
@require_POST
def demand_close(request, pk):
    attempt(request, lambda: inv.close_demand(request.staff, pk, request.POST.get("status"), request),
            "Đã cập nhật nhu cầu.")
    return redirect("bloodbank:demands")


# ---------------------------------------------------------------- SCR-29 Chờ xét nghiệm → nhập kho
@staff_required
def lab_queue(request):
    """Màn xét nghiệm kiểu phần mềm kho: lưới dữ liệu, nhập kết quả ngay trên dòng được chọn (?chon=).

    Tab "cho": lượt hiến chờ xét nghiệm (cũ trước). Chỉ mở hàng nhập khi người dùng chọn một dòng; lưu xong tự mở
    lượt kế tiếp (next_pk) để xử lý liên tục. Tab "da": đã có kết quả.
    """
    h, q = request.hospital, (request.GET.get("q") or "").strip()
    tab = "da" if request.GET.get("tab") == "da" else "cho"
    queue = lab.lab_queue(h, q)
    ctx = {"tab": tab, "q": q, "pending_count": lab.lab_queue(h).count()}
    if tab == "da":
        page = paginate(request, lab.lab_history(h, q), 50)
        ctx.update(page=page, passed=sum(1 for d in page if d.lab_status == "passed"),
                   units=sum(d.units or 0 for d in page))
    else:
        page = paginate(request, queue, 50)
        rows = list(page)
        chosen = int_or_none(request.GET.get("chon"))
        selected = next((d for d in rows if d.pk == chosen), None)
        next_pk = None
        if selected:
            selected.suggested_spec = lab.default_spec(selected)
            selected.form_key = new_key()
            selected.plan_tach, selected.plan_nguyen = lab.yield_plan(selected, "tach"), lab.yield_plan(selected, "nguyen")
            # Nhóm máu từ lần xét nghiệm trước của chính người hiến (không dùng nhóm tự khai) — vẫn để nhân viên kiểm tra
            selected.known_group = (Donation.objects.filter(donor_id=selected.donor_id, status="confirmed",
                                                            lab_blood_group__isnull=False)
                                    .order_by("-donated_at").values_list("lab_blood_group", flat=True).first())
            after = rows[rows.index(selected) + 1:] + rows[:rows.index(selected)]
            next_pk = after[0].pk if after else None
        ctx.update(page=page, selected=selected, next_pk=next_pk, total_ml=sum(d.volume_ml or 0 for d in rows),
                   blood_groups=BLOOD_GROUPS,
                   specs=ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
                   .order_by("product__name", "-is_default", "name"))
    return render(request, "hospital/lab_queue.html", ctx)


@staff_required
@require_POST
def lab_result(request, pk):
    result = request.POST.get("result")
    attempt(request, lambda: lab.record_lab_result(request.staff, pk, result, request.POST,
                                                   request.POST.get("idempotency_key"), request),
            lambda d: (f"Đã nhập kho từ lượt hiến {d.code}, nhóm {d.get_lab_blood_group_display()}."
                       if d.lab_status == "passed" else f"Đã ghi nhận lượt hiến {d.code} không đạt xét nghiệm."))
    return safe_next(request, "bloodbank:lab_queue")
