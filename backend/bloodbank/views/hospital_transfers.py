"""SCR-34..37: tìm nguồn liên viện, yêu cầu đã gửi, đề nghị đến bệnh viện tôi, yêu cầu người cần máu."""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.forms import PROVINCES
from accounts.models import BLOOD_GROUPS
from bloodbank.forms import SupportRequestForm
from bloodbank.models import Campaign, HospitalRequest, PatientRequest, Product, ProductSpec, RequestOffer, Stock
from bloodbank.permissions import staff_required
from bloodbank.services import patients as prq_service
from bloodbank.services import transfers as trf
from bloodbank.services.common import BusinessError

from .helpers import attempt, int_or_none, new_key, paginate


@staff_required
def source_search(request):
    """SCR-34: bộ lọc bắt buộc nhóm máu + chế phẩm; chỉ hiện số chia sẻ hiệu lực."""
    g = request.GET
    rows, searched = [], False
    product_id, spec_id, min_qty = int_or_none(g.get("product")), int_or_none(g.get("spec")), int_or_none(g.get("min_qty"))
    if g.get("blood_group") and product_id:
        searched = True
        rows = trf.search_sources(request.hospital, g["blood_group"], product_id, spec_id, min_qty,
                                  g.get("province") or None)
    prefill = {
        "blood_group": g.get("blood_group"), "product_spec_id": spec_id or "",
        "quantity_needed": g.get("qty") or g.get("min_qty") or "", "priority": "normal",
    }
    if not prefill["product_spec_id"] and product_id:
        d = ProductSpec.objects.filter(product_id=product_id, is_default=True).first()
        prefill["product_spec_id"] = d.pk if d else ""
    form = SupportRequestForm(initial=prefill)
    # Gợi ý: chia số cần cho các nguồn gần nhất, đúng quy cách — nhân viên vẫn sửa được trước khi gửi
    plan = trf.suggest_allocation(rows, prefill["quantity_needed"], prefill["product_spec_id"])
    for r in rows:
        r["suggested"] = plan.get(r["hospital"].pk) if str(r["spec"].pk) == str(prefill["product_spec_id"]) else None
    planned = sum(plan.values())
    return render(request, "hospital/source_search.html", {
        "plan": plan, "planned": planned, "plan_short": max(0, int(prefill["quantity_needed"] or 0) - planned)
        if str(prefill["quantity_needed"] or "").isdigit() else 0,
        "rows": rows, "searched": searched, "g": g, "blood_groups": BLOOD_GROUPS, "provinces": PROVINCES,
        "products": Product.objects.filter(is_active=True),
        "specs": ProductSpec.objects.select_related("product").filter(is_active=True), "form": form,
        "patient_request": PatientRequest.objects.filter(pk=int_or_none(g.get("patient_request")), hospital=request.hospital).first(),
    })


@staff_required
@require_POST
def support_request_create(request):
    form = SupportRequestForm(request.POST)
    suppliers = [(hid, request.POST.get(f"qty_{hid}")) for hid in request.POST.getlist("supplier")]
    if not form.is_valid():
        messages.error(request, "Thông tin yêu cầu chưa hợp lệ: " + "; ".join(e for errs in form.errors.values() for e in errs))
        return redirect("bloodbank:source_search")
    try:
        req = trf.create_request(request.staff, form.cleaned_data, suppliers, request.POST.get("patient_request_id") or None,
                                 request)
    except BusinessError as exc:
        messages.error(request, exc.message)
        return redirect("bloodbank:source_search")
    messages.success(request, f"Đã tạo yêu cầu {req.request_code}"
                              + (f" và gửi đề nghị tới {len(suppliers)} bệnh viện." if suppliers else "."))
    return redirect("bloodbank:support_request_detail", pk=req.pk)


@staff_required
def support_requests(request):
    trf.expire_overdue(request.hospital)
    qs = HospitalRequest.objects.filter(requesting_hospital=request.hospital).select_related("product_spec__product")
    status = request.GET.get("status") or ""
    if status == "open":
        qs = qs.filter(status__in=["open", "in_progress", "partially_fulfilled"], closed_at__isnull=True)
    elif status:
        qs = qs.filter(status=status)
    page = paginate(request, qs, 20)
    for r in page:
        r.numbers = trf.request_numbers(r)
    return render(request, "hospital/support_requests.html", {"page": page, "status": status,
                                                              "statuses": HospitalRequest.Status.choices})


@staff_required
def support_request_detail(request, pk):
    req = get_object_or_404(HospitalRequest.objects.select_related("product_spec__product", "created_by"), pk=pk,
                            requesting_hospital=request.hospital)
    offers = list(req.offers.select_related("supplier_hospital").order_by("created_at"))
    for o in offers:
        o.actions = trf.offer_actions(o, "requester", request.staff)
    invite_rows = []
    if not req.is_final and req.closed_at is None:
        existing = {o.supplier_hospital_id for o in offers}
        invite_rows = [r for r in trf.search_sources(request.hospital, req.blood_group, req.product_spec.product_id,
                                                     req.product_spec_id) if r["hospital"].pk not in existing]
    return render(request, "hospital/support_request_detail.html", {
        "r": req, "offers": offers, "n": trf.request_numbers(req), "invite_rows": invite_rows, "key": new_key(),
        "patient_requests": req.patient_requests.all(),
    })


@staff_required
@require_POST
def support_request_action(request, pk):
    req = get_object_or_404(HospitalRequest, pk=pk, requesting_hospital=request.hospital)
    action = request.POST.get("action")
    if action == "invite":
        attempt(request, lambda: trf.invite_more(request.staff, req.pk, request.POST.get("hospital_id"),
                                                 request.POST.get("quantity") or None, request), "Đã gửi đề nghị.")
    elif action in ("cancel", "close"):
        attempt(request, lambda: trf.cancel_or_close_request(request.staff, req.pk, action, request.POST.get("reason"),
                                                             request),
                "Đã hủy yêu cầu." if action == "cancel" else "Đã đóng yêu cầu.")
    elif action == "cancel_offer":
        attempt(request, lambda: trf.cancel_offer_by_requester(request.staff, request.POST.get("offer_id"), request),
                "Đã hủy đề nghị.")
    elif action == "reinvite":
        offer = get_object_or_404(RequestOffer, pk=int_or_none(request.POST.get("offer_id")), request=req)
        attempt(request, lambda: trf.invite_more(request.staff, req.pk, offer.supplier_hospital_id,
                                                 request.POST.get("quantity") or offer.quantity_requested, request),
                "Đã mời lại.")
    elif action == "receive":
        attempt(request, lambda: trf.confirm_received(
            request.staff, request.POST.get("offer_id"), request.POST.get("quantity_received"),
            request.POST.get("idempotency_key"), request.POST.get("returned") == "1", request.POST.get("note"), request),
            "Đã xác nhận nhận hàng và cộng vào kho.")
    return redirect("bloodbank:support_request_detail", pk=pk)


def support_request_for_offer(request, pk):
    offer = get_object_or_404(RequestOffer, pk=pk)
    return redirect("bloodbank:support_request_detail", pk=offer.request_id)


@staff_required
def incoming_offers(request):
    trf.expire_overdue(request.hospital)
    qs = RequestOffer.objects.filter(supplier_hospital=request.hospital).select_related(
        "request__requesting_hospital", "request__product_spec__product")
    status = request.GET.get("status") or ""
    if status:
        qs = qs.filter(status=status)
    return render(request, "hospital/incoming_offers.html", {"page": paginate(request, qs, 20), "status": status,
                                                             "statuses": RequestOffer.Status.choices})


@staff_required
def offer_detail(request, pk):
    """SCR-36: chi tiết đề nghị — không thấy offer của bệnh viện khác."""
    offer = get_object_or_404(RequestOffer.objects.select_related("request__requesting_hospital",
                                                                  "request__product_spec__product"),
                              pk=pk, supplier_hospital=request.hospital)
    req = offer.request
    stock = Stock.objects.filter(hospital=request.hospital, blood_group=req.blood_group,
                                 product_spec_id=req.product_spec_id).first()
    n = trf.request_numbers(req)
    available = stock.available if stock else 0
    suggested = min(x for x in [offer.quantity_requested or n["remaining"], available, n["remaining"]] if x is not None)
    return render(request, "hospital/offer_detail.html", {
        "o": offer, "r": req, "stock": stock, "available": available, "remaining": n["remaining"],
        "suggested": max(suggested, 0), "actions": trf.offer_actions(offer, "supplier", request.staff), "key": new_key(),
    })


@staff_required
@require_POST
def offer_action(request, pk):
    offer = get_object_or_404(RequestOffer, pk=pk, supplier_hospital=request.hospital)
    action = request.POST.get("action")
    if action == "accept":
        attempt(request, lambda: trf.accept_offer(request.staff, offer.pk, request.POST.get("quantity"),
                                                  request.POST.get("note"), request), "Đã chấp thuận và giữ chỗ trong kho.")
    elif action == "reject":
        attempt(request, lambda: trf.reject_offer(request.staff, offer.pk, request.POST.get("reason"), request),
                "Đã từ chối đề nghị.")
    elif action == "cancel":
        attempt(request, lambda: trf.cancel_offer_by_supplier(request.staff, offer.pk, request.POST.get("reason"), request),
                "Đã hủy và giải phóng giữ chỗ.")
    elif action == "dispatch":
        attempt(request, lambda: trf.dispatch_offer(request.staff, offer.pk, request.POST.get("idempotency_key"), request),
                "Đã xác nhận xuất kho điều chuyển.")
    elif action == "fail":
        attempt(request, lambda: trf.report_failure(request.staff, offer.pk, request.POST.get("reason"),
                                                    request.POST.get("returned_qty"),
                                                    request.POST.get("idempotency_key"), request),
                "Đã ghi nhận giao nhận thất bại.")
    return redirect("bloodbank:offer_detail", pk=pk)


# ---------------------------------------------------------------- SCR-37 Yêu cầu người cần máu (bệnh viện)
@staff_required
def patient_requests(request):
    qs = PatientRequest.objects.filter(hospital=request.hospital).select_related("blood_product")
    status = request.GET.get("status", "waiting")
    if status == "waiting":
        qs = qs.filter(status__in=["submitted", "verifying"])
    elif status == "active":
        qs = qs.filter(status__in=["verified", "processing"])
    elif status:
        qs = qs.filter(status=status)
    return render(request, "hospital/patient_requests.html", {"page": paginate(request, qs, 20), "status": status})


@staff_required
def patient_request_detail(request, pk):
    prq = get_object_or_404(PatientRequest.objects.select_related("requester", "blood_product", "verified_by",
                                                                  "linked_support_request", "linked_campaign"),
                            pk=pk, hospital=request.hospital)
    prq_service.log_sensitive_view(request.staff, prq, request)
    stocks = []
    if prq.blood_group:
        stocks = Stock.objects.filter(hospital=request.hospital, blood_group=prq.blood_group).select_related(
            "product_spec__product")
        if prq.blood_product_id:
            stocks = stocks.filter(product_spec__product_id=prq.blood_product_id)
    issued = prq.txns.select_related("stock__product_spec__product").all()
    return render(request, "hospital/patient_request_detail.html", {
        "prq": prq, "actions": prq_service.hospital_actions(prq), "stocks": stocks, "issued": issued,
        "blood_groups": BLOOD_GROUPS,
        "campaigns": Campaign.objects.filter(hospital=request.hospital, status__in=["draft", "open", "closed"]),
    })


@staff_required
@require_POST
def patient_request_action(request, pk):
    action = request.POST.get("action")
    labels = {"start_verify": "Đã nhận xác minh.", "verify": "Đã xác minh yêu cầu.", "reject": "Đã từ chối yêu cầu.",
              "start_processing": "Đã bắt đầu xử lý.", "link_campaign": "Đã kết nối với đợt hiến.",
              "fulfill": "Đã hoàn tất yêu cầu.", "cancel": "Đã hủy yêu cầu."}
    attempt(request, lambda: prq_service.hospital_action(request.staff, pk, action, request.POST.dict(), request),
            labels.get(action))
    return redirect("bloodbank:hospital_patient_request_detail", pk=pk)
