"""SCR-20, SCR-38..40, SCR-52: tổng quan bệnh viện, nhân viên, thông tin, nhật ký, danh mục."""
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from bloodbank.forms import HospitalForm, ProductForm, SpecForm
from bloodbank.models import (
    AuditLog, Campaign, PatientRequest, Product, ProductSpec, Registration, RequestOffer, Staff,
)
from bloodbank.permissions import current_staff, staff_required
from bloodbank.services import admin as admin_service
from bloodbank.services import forecast as fc
from bloodbank.services import hospital_signup as signup
from bloodbank.services import inventory as inv
from bloodbank.services import lab
from bloodbank.services import transfers as trf

from .helpers import attempt, audit_filters, int_or_none, map_center, paginate



@staff_required
def dashboard(request):
    """Tổng quan bệnh viện: việc cần xử lý, kho cần chú ý, yêu cầu cần máu, đợt hiến. Chỉ đọc."""
    h = request.hospital
    now = timezone.now()
    trf.expire_overdue(h)
    alerts = inv.stock_alerts(h)
    counts = {
        "prq_waiting": PatientRequest.objects.filter(hospital=h, status__in=PatientRequest.WAITING_STATUSES).count(),
        "pending_regs": Registration.objects.filter(campaign__hospital=h, status="pending",
                                                    campaign__status__in=Campaign.RUNNING_STATUSES).count(),
        "lab_pending": lab.lab_queue(h).count(),
        "incoming_pending": RequestOffer.objects.filter(supplier_hospital=h, status="pending").count(),
        "to_dispatch": RequestOffer.objects.filter(supplier_hospital=h, status="accepted").count(),
        "to_receive": RequestOffer.objects.filter(request__requesting_hospital=h, status="in_transit").count(),
    }
    # 4 chỉ số chính (luôn hiện, bấm để tới màn xử lý) + việc phụ (chỉ hiện khi có)
    urgent = sum(1 for r in inv.shortages(h, now) if r["urgent"]) + len(inv.urgent_requests(h))
    plan = [r for r in fc.forecast(h, now) if r["level"] != "ok"]   # dự báo: sắp thiếu / cần lên kế hoạch
    kpis = [
        {"label": "Thiếu máu khẩn", "count": urgent, "icon": "siren", "url": reverse("bloodbank:demands"),
         "tone": "danger", "hint": "cần trong 24 giờ"},
        {"label": "Yêu cầu chờ xác minh", "count": counts["prq_waiting"], "icon": "heart-pulse",
         "url": reverse("bloodbank:hospital_patient_requests"), "tone": "danger", "hint": "từ người nhà bệnh nhân"},
        {"label": "Chờ xét nghiệm", "count": counts["lab_pending"], "icon": "flask-conical",
         "url": reverse("bloodbank:lab_queue"), "tone": "warn", "hint": "lượt hiến chưa nhập kho"},
        {"label": "Sắp thiếu (7 ngày)", "count": sum(1 for r in plan if r["level"] == "soon"), "icon": "chart-line",
         "url": reverse("bloodbank:demands"), "tone": "warn", "hint": f"khả dụng {alerts['available']} đơn vị"},
    ]
    others = [
        (counts["to_receive"], "hàng liên viện đang tới", reverse("bloodbank:support_requests") + "?status=open"),
        (counts["incoming_pending"], "đề nghị cấp máu chờ phản hồi", reverse("bloodbank:incoming_offers") + "?status=pending"),
        (counts["to_dispatch"], "đề nghị đã chấp thuận chờ xuất", reverse("bloodbank:incoming_offers") + "?status=accepted"),
        (counts["pending_regs"], "đơn đăng ký hiến chờ duyệt", reverse("bloodbank:hospital_campaigns") + "?status=open"),
    ]
    # Yêu cầu cần máu đang mở: chờ xác minh trước, rồi hạn cần sớm nhất
    open_statuses = PatientRequest.WAITING_STATUSES + PatientRequest.ACTIVE_STATUSES
    prqs = sorted(PatientRequest.objects.filter(hospital=h, status__in=open_statuses).select_related("blood_product"),
                  key=lambda p: (p.status not in PatientRequest.WAITING_STATUSES, p.needed_by or p.created_at))[:5]
    campaigns = (Campaign.objects.filter(hospital=h, status__in=Campaign.RUNNING_STATUSES)
                 .annotate(reg_count=Count("registrations",
                                           filter=Q(registrations__status__in=Registration.ACTIVE_STATUSES)),
                           pending_count=Count("registrations", filter=Q(registrations__status="pending")))
                 .order_by("start_time")[:5])
    for c in campaigns:   # "đang diễn ra" theo thời gian thật; mở điểm hiến từ 12 giờ trước giờ bắt đầu
        c.live = c.start_time <= now <= c.end_time
        c.checkin_ready = c.start_time - timedelta(hours=12) <= now <= c.end_time
    return render(request, "hospital/dashboard.html", {
        "now": now, "alerts": alerts, "prqs": prqs, "campaigns": campaigns, "kpis": kpis, "plan": plan[:6],
        "plan_more": max(0, len(plan) - 6),
        "others": [{"count": n, "label": label, "url": url} for n, label, url in others if n],
    })


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
                                                           "staff_count": h.staffs.filter(is_active=True).count(),
                                                           **map_center(h)})


# ---------------------------------------------------------------- SCR-38 Nhân viên
@staff_required
def hospital_staff(request):
    """Danh sách nhân viên. Quản lý bệnh viện cấp tài khoản mới / thu hồi / kích hoạt lại (BV_014); nhân viên chỉ xem."""
    is_manager = request.staff.is_manager
    if request.method == "POST":
        action = request.POST.get("form")

        def add():
            signup.require_manager(request.staff)
            return admin_service.assign_staff(request.user, request.hospital, request.POST, request)

        def update():
            signup.require_manager(request.staff)
            target = signup.check_staff_target(request.staff, request.POST.get("staff_id"))
            return admin_service.update_staff(request.user, request.hospital, target.pk,
                                              request.POST.get("op") == "activate", request)

        if action == "staff_add":
            attempt(request, add, "Đã cấp tài khoản nhân viên.")
        elif action == "staff_update":
            attempt(request, update, "Đã cập nhật phân công.")
        return redirect("bloodbank:hospital_staff")
    staffs = (Staff.objects.filter(hospital=request.hospital).select_related("user")
              .order_by("-is_active", "-staff_role", "user__full_name"))
    return render(request, "hospital/staff.html", {"staffs": staffs, "is_manager": is_manager})


# ---------------------------------------------------------------- SCR-40 Nhật ký bệnh viện
@staff_required
def hospital_audit(request):
    qs, f, actions = audit_filters(request, AuditLog.objects.filter(hospital=request.hospital).select_related("actor"))
    return render(request, "shared/audit.html", {"page": paginate(request, qs, 50), "f": f, "scope": "hospital",
                                                 "actions": actions})


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
