"""SCR-30..33: tồn kho, phiếu nhập/xuất/điều chỉnh, sổ kho, nhu cầu & thiếu hụt."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import BLOOD_GROUPS
from bloodbank.forms import DemandForm
from bloodbank.models import Demand, PatientRequest, Product, ProductSpec, Stock, StockTxn
from bloodbank.permissions import staff_required
from bloodbank.services import inventory as inv
from bloodbank.services import callout, lab
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
            msg = "Phiếu đã được ghi trước đó (gửi lại cùng mã) — không ghi trùng." if txn.replayed else "Đã ghi phiếu."
            messages.success(request, f"{msg} Tồn sau: {txn.quantity_after} đơn vị.")
            return redirect("bloodbank:stock_ledger")
    stocks = Stock.objects.filter(hospital=h).select_related("product_spec__product").order_by(
        "product_spec__product__name", "blood_group")
    if mode == "issue":
        stocks = [s for s in stocks if s.available > 0] or list(stocks)
    initial_stock = request.GET.get("stock") or data.get("stock_id")
    prqs = PatientRequest.objects.filter(hospital=h, status__in=PatientRequest.ACTIVE_STATUSES).order_by("-created_at")
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
    qs = Demand.objects.filter(hospital=h).select_related("product_spec__product")
    if status:
        qs = qs.filter(status=status)
    return render(request, "hospital/demands.html", {
        "form": form, "demand": demand, "page": paginate(request, qs, 20), "status": status,
        "shortages": callout.with_callout_info(h, inv.shortages(h)),
    })


@staff_required
@require_POST
def donor_callout(request):
    bg = request.POST.get("blood_group")
    attempt(request, lambda: callout.donor_callout(request.staff, bg, request),
            lambda res: f"Đã gửi lời kêu gọi nhóm {bg} tới {res[0]} người hiến phù hợp"
                        + (f", kèm đợt hiến \"{res[1].name}\"." if res[1] else ". Chưa có đợt hiến đang mở — cân nhắc tạo đợt."))
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
    """Lượt hiến đã ghi nhận, chờ kết quả xét nghiệm. Đạt → nhập kho một lần bấm; phiếu nhập gắn với lượt hiến."""
    page = paginate(request, lab.lab_queue(request.hospital), 30)
    for d in page:
        d.suggested_spec = lab.default_spec(d)
        d.form_key = new_key()
    recent = (StockTxn.objects.filter(stock__hospital=request.hospital, donation__isnull=False)
              .select_related("donation__donor", "stock__product_spec__product").order_by("-occurred_at")[:8])
    return render(request, "hospital/lab_queue.html", {
        "page": page, "blood_groups": BLOOD_GROUPS, "recent": recent,
        "specs": ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
        .order_by("product__name", "-is_default", "name"),
    })


@staff_required
@require_POST
def lab_result(request, pk):
    result = request.POST.get("result")
    attempt(request, lambda: lab.record_lab_result(request.staff, pk, result, request.POST,
                                                   request.POST.get("idempotency_key"), request),
            lambda d: (f"Đã nhập kho từ lượt hiến {d.code} — nhóm {d.get_lab_blood_group_display()}."
                       if d.lab_status == "passed" else f"Đã ghi nhận lượt hiến {d.code} không đạt xét nghiệm."))
    return safe_next(request, "bloodbank:lab_queue")
