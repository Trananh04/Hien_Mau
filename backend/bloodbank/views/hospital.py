"""SCR-20, SCR-38..40, SCR-52: tổng quan bệnh viện, nhân viên, thông tin, nhật ký, danh mục."""
from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bloodbank.forms import HospitalForm, ProductForm, SpecForm
from bloodbank.models import (
    AuditLog, Campaign, Notification, PatientRequest, Product, ProductSpec, Registration, RequestOffer, Staff, Stock,
)
from bloodbank.permissions import current_staff, select_hospital, staff_required
from bloodbank.services import admin as admin_service
from bloodbank.services import inventory as inv
from bloodbank.services import lab
from bloodbank.services import transfers as trf

from .helpers import attempt, int_or_none, paginate



@staff_required
def dashboard(request):
    h = request.hospital
    now = timezone.now()
    trf.expire_overdue(h)
    ctx = {"now": now}
    ctx["active_campaigns"] = Campaign.objects.filter(hospital=h, status__in=["open", "closed"]).order_by("start_time")[:5]
    ctx["pending_regs"] = Registration.objects.filter(campaign__hospital=h, status="pending",
                                                      campaign__status__in=["open", "closed"]).count()
    ctx["today_campaigns"] = Campaign.objects.filter(hospital=h, status__in=["open", "closed"],
                                                     start_time__lte=now + timedelta(hours=12), end_time__gte=now)
    stocks = list(Stock.objects.filter(hospital=h).select_related("product_spec__product"))
    ctx["low_stocks"] = [s for s in stocks if s.below_min][:8]
    ctx["stock_total"] = sum(s.quantity_on_hand for s in stocks)
    ctx["stock_available"] = sum(s.available for s in stocks)
    ctx["shortages"] = [s for s in inv.shortages(h) if s["shortage"] > 0][:6]
    ctx["incoming_pending"] = RequestOffer.objects.filter(supplier_hospital=h, status="pending").count()
    ctx["to_receive"] = RequestOffer.objects.filter(request__requesting_hospital=h, status="in_transit").count()
    ctx["to_dispatch"] = RequestOffer.objects.filter(supplier_hospital=h, status="accepted").count()
    ctx["prq_waiting"] = PatientRequest.objects.filter(hospital=h, status__in=["submitted", "verifying"]).count()
    ctx["prq_recent"] = PatientRequest.objects.filter(hospital=h).exclude(
        status__in=["fulfilled", "cancelled", "rejected"]).order_by("-created_at")[:5]
    ctx["lab_pending"] = lab.lab_queue(h).count()
    ctx["notifications"] = Notification.objects.filter(user=request.user, channel="in_app").order_by("-created_at")[:6]
    return render(request, "hospital/dashboard.html", ctx)


@require_POST
def choose_hospital(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    try:
        hospital_id = int(request.POST.get("hospital_id"))
    except (TypeError, ValueError):
        raise Http404
    return select_hospital(request, hospital_id)


def offer_open(request, pk):
    """Liên kết thông báo về một đề nghị: chuyển tới màn hình đúng bên (cấp / yêu cầu)."""
    staff = current_staff(request)
    if staff is None:
        raise Http404
    offer = get_object_or_404(RequestOffer.objects.select_related("request"), pk=pk)
    if offer.supplier_hospital_id == staff.hospital_id:
        return redirect("bloodbank:offer_detail", pk=offer.pk)
    if offer.request.requesting_hospital_id == staff.hospital_id:
        return redirect("bloodbank:support_request_detail", pk=offer.request_id)
    raise Http404


# ---------------------------------------------------------------- SCR-39 Thông tin bệnh viện
@staff_required
def hospital_info(request):
    h = request.hospital
    can_edit = True
    initial = {k: getattr(h, k) for k in admin_service.HOSPITAL_FIELDS}
    form = HospitalForm(request.POST or None, initial=initial)
    for name in admin_service.HOSPITAL_FIELDS:
        if name not in admin_service.STAFF_EDITABLE:
            form.fields[name].disabled = True
    if request.method == "POST":
        if not can_edit:
            raise Http404
        if form.is_valid():
            data = {k: form.cleaned_data.get(k) for k in admin_service.STAFF_EDITABLE}
            ok, _ = attempt(request, lambda: admin_service.save_hospital(request.user, data, h, admin_service.STAFF_EDITABLE,
                                                                         request), "Đã cập nhật thông tin bệnh viện.")
            if ok:
                return redirect("bloodbank:hospital_info")
    return render(request, "hospital/hospital_info.html", {"form": form, "can_edit": can_edit, "h": h,
                                                           "staff_count": h.staffs.filter(is_active=True).count()})


# ---------------------------------------------------------------- SCR-38 Nhân viên (xem)
@staff_required
def hospital_staff(request):
    """Danh sách đồng nghiệp tại bệnh viện. Tạo / thu hồi tài khoản nhân viên do Quản trị hệ thống thực hiện (SCR-51)."""
    staffs = (Staff.objects.filter(hospital=request.hospital).select_related("user")
              .order_by("-is_active", "user__full_name"))
    return render(request, "hospital/staff.html", {"staffs": staffs})


# ---------------------------------------------------------------- SCR-40 Nhật ký bệnh viện
def _audit_filters(request, qs):
    f = {k: request.GET.get(k) or "" for k in ("entity", "action", "actor", "from", "to")}
    if f["entity"]:
        qs = qs.filter(entity_type=f["entity"])
    if f["action"]:
        qs = qs.filter(action=f["action"])
    if f["actor"]:
        qs = qs.filter(Q(actor__email__icontains=f["actor"]) | Q(actor__full_name__icontains=f["actor"]))
    if f["from"]:
        qs = qs.filter(created_at__date__gte=f["from"])
    if f["to"]:
        qs = qs.filter(created_at__date__lte=f["to"])
    return qs, f


@staff_required
def hospital_audit(request):
    qs, f = _audit_filters(request, AuditLog.objects.filter(hospital=request.hospital).select_related("actor"))
    return render(request, "shared/audit.html", {
        "page": paginate(request, qs, 30), "f": f, "scope": "hospital",
        "entities": AuditLog.objects.filter(hospital=request.hospital).values_list("entity_type", flat=True).distinct(),
        "actions": AuditLog.objects.filter(hospital=request.hospital).values_list("action", flat=True).distinct(),
    })


# ---------------------------------------------------------------- SCR-52 Danh mục chế phẩm (nhân viên xem, Admin sửa)
def catalog(request):
    # Middleware chỉ cho Nhân viên bệnh viện (xem) và Quản trị hệ thống (sửa)
    is_admin = request.user.is_admin
    staff = current_staff(request)
    if not is_admin and staff is None:
        raise Http404
    if staff is not None:
        request.staff, request.hospital = staff, staff.hospital
    if request.method == "POST":
        if not is_admin:
            raise Http404
        _catalog_post(request)
        return redirect("bloodbank:catalog")
    products = Product.objects.prefetch_related("specs").order_by("-is_active", "name")
    edit_product = Product.objects.filter(pk=int_or_none(request.GET.get("product"))).first() if is_admin else None
    return render(request, "shared/catalog.html", {
        "products": products, "is_admin": is_admin, "product_form": ProductForm(), "spec_form": SpecForm(),
        "edit_product": edit_product,
    })


def _catalog_post(request):
    action = request.POST.get("action")
    if action in ("add_product", "edit_product"):
        form = ProductForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Thông tin chế phẩm chưa hợp lệ: " + "; ".join(e for errs in form.errors.values() for e in errs))
            return
        product = Product.objects.filter(pk=int_or_none(request.POST.get("product_id"))).first() if action == "edit_product" else None
        attempt(request, lambda: admin_service.save_product(request.user, form.cleaned_data, product, request),
                "Đã lưu chế phẩm.")
    elif action in ("add_spec", "edit_spec"):
        form = SpecForm(request.POST)
        product = get_object_or_404(Product, pk=int_or_none(request.POST.get("product_id")))
        if not form.is_valid():
            messages.error(request, "Thông tin quy cách chưa hợp lệ: " + "; ".join(e for errs in form.errors.values() for e in errs))
            return
        spec = ProductSpec.objects.filter(pk=int_or_none(request.POST.get("spec_id")), product=product).first() if action == "edit_spec" else None
        attempt(request, lambda: admin_service.save_spec(request.user, product, form.cleaned_data, spec, request),
                "Đã lưu quy cách.")
    elif action in ("toggle_product", "toggle_spec"):
        model = Product if action == "toggle_product" else ProductSpec
        obj = get_object_or_404(model, pk=int_or_none(request.POST.get("id")))
        attempt(request, lambda: admin_service.toggle_catalog(request.user, obj, request.POST.get("active") == "1", request),
                "Đã cập nhật trạng thái sử dụng.")
