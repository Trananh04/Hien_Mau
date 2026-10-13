"""SCR-30..33: tồn kho, phiếu nhập/xuất/điều chỉnh, sổ kho, nhu cầu & thiếu hụt."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import BLOOD_GROUP_VALUES, BLOOD_GROUPS
from bloodbank.forms import DemandForm
from bloodbank.models import Demand, PatientRequest, Product, ProductSpec, Stock, StockTxn
from bloodbank.permissions import staff_required
from bloodbank.services import inventory as inv
from bloodbank.services.common import BusinessError

from .helpers import attempt, new_key, paginate, safe_next



@staff_required
def stock(request):
    """Ma trận nhóm máu × chế phẩm/quy cách; nhân viên sửa nhanh Chia sẻ/Tối thiểu."""
    h = request.hospital
    specs = list(ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
                 .order_by("product__kind", "product__name", "code"))
    rows = {(s.blood_group, s.product_spec_id): s for s in Stock.objects.filter(hospital=h)}
    shortages = {(r["blood_group"], r["spec"].pk): r["shortage"] for r in inv.shortages(h)}
    product_id = request.GET.get("product")
    shown_specs = [s for s in specs if not product_id or str(s.product_id) == product_id]
    matrix = []
    for bg in BLOOD_GROUP_VALUES:
        cells = []
        for spec in shown_specs:
            st = rows.get((bg, spec.pk))
            cells.append({"spec": spec, "stock": st, "short": shortages.get((bg, spec.pk), 0)})
        matrix.append({"bg": bg, "cells": cells})
    detail = sorted(rows.values(), key=lambda s: (s.product_spec_id, s.blood_group))
    for s in detail:
        s.spec = next((x for x in specs if x.pk == s.product_spec_id), None)
    detail = [s for s in detail if s.spec and (not product_id or str(s.spec.product_id) == product_id)]
    totals = {"on_hand": sum(s.quantity_on_hand for s in rows.values()),
              "reserved": sum(s.quantity_reserved for s in rows.values()),
              "low": sum(1 for s in rows.values() if s.below_min), "short": sum(1 for v in shortages.values() if v > 0)}
    return render(request, "hospital/stock.html", {
        "matrix": matrix, "specs": shown_specs, "detail": detail, "totals": totals,
        "products": Product.objects.filter(is_active=True), "product_id": product_id,
        "can_edit": True, "blood_groups": BLOOD_GROUPS, "all_specs": specs,
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
    prqs = PatientRequest.objects.filter(hospital=h, status__in=["verified", "processing"]).order_by("-created_at")
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
        "stock__product_spec__product", "performed_by", "offer__request", "patient_request")
    f = {k: request.GET.get(k) or "" for k in ("type", "blood_group", "spec", "from", "to", "stock")}
    if f["type"]:
        qs = qs.filter(txn_type=f["type"])
    if f["blood_group"]:
        qs = qs.filter(stock__blood_group=f["blood_group"])
    if f["spec"]:
        qs = qs.filter(stock__product_spec_id=f["spec"])
    if f["stock"]:
        qs = qs.filter(stock_id=f["stock"])
    if f["from"]:
        qs = qs.filter(occurred_at__date__gte=f["from"])
    if f["to"]:
        qs = qs.filter(occurred_at__date__lte=f["to"])
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
        "shortages": inv.shortages(h),
    })


@staff_required
@require_POST
def demand_close(request, pk):
    attempt(request, lambda: inv.close_demand(request.staff, pk, request.POST.get("status"), request),
            "Đã cập nhật nhu cầu.")
    return redirect("bloodbank:demands")
