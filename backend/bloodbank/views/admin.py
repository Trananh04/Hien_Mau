"""SCR-50..54: quản trị hệ thống (chỉ role = admin)."""
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import BLOOD_GROUP_VALUES, User
from bloodbank import access
from bloodbank.forms import HospitalForm
from bloodbank.models import (
    AuditLog, Campaign, Donation, Hospital, HospitalRequest, PatientRequest, Registration, RequestOffer, Stock,
    SystemSetting,
)
from bloodbank.permissions import admin_required
from bloodbank.services import admin as admin_service
from bloodbank.services import donations as don

from .helpers import attempt, paginate
from .hospital import _audit_filters


@admin_required
def stats(request):
    """SCR-54: thống kê toàn hệ thống (DON-05 A1, INV-02 A2) — số liệu tính toán từ bảng gốc."""
    summary = don.summarize(Donation.objects.all())
    by_hospital = (
        Hospital.objects.annotate(
            donation_count=Count("donations", filter=Q(donations__status="confirmed"), distinct=True),
            ml=Sum("donations__volume_ml", filter=Q(donations__status="confirmed", donations__donation_type="whole_blood")),
        ).order_by("-donation_count", "name")
    )
    stock_by_group = {bg: {"on_hand": 0, "available": 0} for bg in BLOOD_GROUP_VALUES}
    for s in Stock.objects.filter(hospital__status="active"):
        stock_by_group[s.blood_group]["on_hand"] += s.quantity_on_hand
        stock_by_group[s.blood_group]["available"] += s.available
    max_avail = max([v["on_hand"] for v in stock_by_group.values()] or [0])
    return render(request, "admin/stats.html", {
        "summary": summary, "by_hospital": by_hospital, "stock_by_group": stock_by_group, "max_avail": max_avail,
        "counts": {
            "users": User.objects.exclude(status="deleted").count(),
            "hospitals": Hospital.objects.filter(status="active").count(),
            "open_campaigns": Campaign.objects.filter(status="open").count(),
            "registrations": Registration.objects.count(),
            "open_requests": HospitalRequest.objects.filter(status__in=["open", "in_progress", "partially_fulfilled"],
                                                            closed_at__isnull=True).count(),
            "in_transit": RequestOffer.objects.filter(status="in_transit").count(),
            "patient_waiting": PatientRequest.objects.filter(status__in=["submitted", "verifying"]).count(),
        },
    })


@admin_required
def users(request):
    if request.method == "POST":
        action, uid = request.POST.get("action"), request.POST.get("user_id")
        if action in ("lock", "unlock", "delete"):
            status = {"lock": "locked", "unlock": "active", "delete": "deleted"}[action]
            attempt(request, lambda: admin_service.set_user_status(request.user, uid, status, request),
                    "Đã cập nhật trạng thái tài khoản.")
        elif action == "role":
            attempt(request, lambda: admin_service.set_user_role(request.user, uid, request.POST.get("role"), request),
                    "Đã cập nhật vai trò.")
        return redirect(request.get_full_path())
    qs = User.objects.annotate(staff_count=Count("staffs", filter=Q(staffs__is_active=True))).order_by("-created_at")
    f = {k: request.GET.get(k) or "" for k in ("q", "status", "role")}
    if f["q"]:
        qs = qs.filter(Q(full_name__icontains=f["q"]) | Q(email__icontains=f["q"]) | Q(phone__icontains=f["q"]))
    if f["status"]:
        qs = qs.filter(status=f["status"])
    if f["role"]:
        qs = qs.filter(role=f["role"])
    return render(request, "admin/users.html", {"page": paginate(request, qs, 25), "f": f, "roles": User.Role.choices})


@admin_required
def hospitals(request):
    qs = Hospital.objects.annotate(staff_count=Count("staffs", filter=Q(staffs__is_active=True))).order_by("-status", "name")
    q = request.GET.get("q") or ""
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(province__icontains=q))
    return render(request, "admin/hospitals.html", {"page": paginate(request, qs, 25), "q": q})


@admin_required
def hospital_form(request, pk=None):
    hospital = get_object_or_404(Hospital, pk=pk) if pk else None
    initial = {k: getattr(hospital, k) for k in admin_service.HOSPITAL_FIELDS} if hospital else {"province": "Đà Nẵng"}
    form = HospitalForm(request.POST if request.POST.get("form") == "hospital" else None, initial=initial)
    if request.method == "POST":
        action = request.POST.get("form")
        if action == "hospital" and form.is_valid():
            ok, saved = attempt(request, lambda: admin_service.save_hospital(request.user, form.cleaned_data, hospital,
                                                                             request=request), "Đã lưu bệnh viện.")
            if ok:
                return redirect("bloodbank:admin_hospital_edit", pk=saved.pk)
        elif action == "status" and hospital:
            attempt(request, lambda: admin_service.set_hospital_status(request.user, hospital.pk, request.POST.get("status"),
                                                                       request), "Đã cập nhật trạng thái bệnh viện.")
            return redirect("bloodbank:admin_hospital_edit", pk=hospital.pk)
        elif action == "staff_add" and hospital:
            attempt(request, lambda: admin_service.assign_staff(request.user, hospital, request.POST, request),
                    "Đã cấp tài khoản nhân viên cho bệnh viện.")
            return redirect("bloodbank:admin_hospital_edit", pk=hospital.pk)
        elif action == "staff_update" and hospital:
            attempt(request, lambda: admin_service.update_staff(request.user, hospital, request.POST.get("staff_id"),
                                                                request.POST.get("op") == "activate", request),
                    "Đã cập nhật phân công.")
            return redirect("bloodbank:admin_hospital_edit", pk=hospital.pk)
    staffs = hospital.staffs.select_related("user").order_by("-is_active", "user__full_name") if hospital else []
    return render(request, "admin/hospital_form.html", {"form": form, "h": hospital, "staffs": staffs})


@admin_required
def audit(request):
    qs, f = _audit_filters(request, AuditLog.objects.select_related("actor", "hospital"))
    hospital_id = request.GET.get("hospital") or ""
    if hospital_id:
        qs = qs.filter(hospital_id=hospital_id)
    f["hospital"] = hospital_id
    return render(request, "shared/audit.html", {
        "page": paginate(request, qs, 30), "f": f, "scope": "system", "hospitals": Hospital.objects.all(),
        "entities": AuditLog.objects.values_list("entity_type", flat=True).distinct().order_by("entity_type"),
        "actions": AuditLog.objects.values_list("action", flat=True).distinct().order_by("action"),
    })


@admin_required
def settings_view(request):
    if request.method == "POST":
        attempt(request, lambda: admin_service.save_setting(request.user, request.POST.get("key"),
                                                            request.POST.get("value"), request), "Đã lưu cấu hình.")
        return redirect("bloodbank:admin_settings")
    rows = {s.setting_key: s for s in SystemSetting.objects.select_related("updated_by")}
    items = [{"key": k, "default": v[0], "description": v[1], "row": rows.get(k)} for k, v in SystemSetting.DEFAULTS.items()]
    return render(request, "admin/settings.html", {"items": items})


@admin_required
def permissions_view(request):
    """SCR-56: bảng phân quyền màn hình theo vai trò — đọc trực tiếp từ bloodbank/access.py (nguồn duy nhất)."""
    columns = [(access.PUBLIC, "Khách (chưa đăng nhập)", "globe")] + [(c, l, i) for c, l, _, _, i in access.ROLES]
    rows = []
    for sc in access.SCREENS:
        public = access.PUBLIC in sc.roles
        rows.append({"screen": sc, "cells": [public or code in sc.roles for code, _, _ in columns]})
    portals = [{"code": c, "label": l, "login": login, "icon": i,
                "count": sum(1 for sc in access.SCREENS if c in sc.roles)} for c, l, login, _, i in access.ROLES]
    return render(request, "admin/permissions.html", {
        "columns": columns, "rows": rows, "portals": portals, "route_count": len(access.ROUTE_ROLES),
        "user_counts": dict(User.objects.exclude(status="deleted").values_list("role").annotate(n=Count("id"))),
    })
