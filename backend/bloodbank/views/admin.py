"""SCR-50..54: quản trị hệ thống (chỉ role = admin)."""
from django.db.models import Case, Count, Q, When
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from bloodbank import access
from bloodbank.forms import HospitalForm
from bloodbank.models import AuditLog, Hospital, SystemSetting
from bloodbank.permissions import admin_required
from bloodbank.services import admin as admin_service
from bloodbank.services import hospital_signup

from .helpers import attempt, audit_filters, map_center, paginate


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
    # Bệnh viện tự đăng ký chờ duyệt lên đầu (BV_014)
    qs = (Hospital.objects.annotate(staff_count=Count("staffs", filter=Q(staffs__is_active=True)),
                                    pending_first=Case(When(status="pending", then=0), default=1))
          .order_by("pending_first", "-status", "name"))
    q = request.GET.get("q") or ""
    status = request.GET.get("status") if request.GET.get("status") in dict(Hospital.Status.choices) else ""
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(province__icontains=q))
    if status:
        qs = qs.filter(status=status)
    return render(request, "admin/hospitals.html", {
        "page": paginate(request, qs, 25), "q": q, "status": status,
        "pending_count": Hospital.objects.filter(status="pending").count(),
    })


@admin_required
def hospital_form(request, pk=None):
    hospital = get_object_or_404(Hospital, pk=pk) if pk else None
    initial = {k: getattr(hospital, k) for k in admin_service.HOSPITAL_FIELDS} if hospital else {}
    form = HospitalForm(request.POST if request.POST.get("form") == "hospital" else None, initial=initial)
    if request.method == "POST":
        action = request.POST.get("form")
        if action == "hospital" and form.is_valid():
            ok, saved = attempt(request, lambda: admin_service.save_hospital(request.user, form.cleaned_data, hospital,
                                                                             request=request), "Đã lưu bệnh viện.")
            if ok:
                return redirect("bloodbank:admin_hospital_edit", pk=saved.pk)
        elif action in ("approve", "reject") and hospital:
            if action == "approve":
                attempt(request, lambda: hospital_signup.approve(request.user, hospital.pk, request),
                        "Đã duyệt bệnh viện. Quản lý bệnh viện đã nhận thông báo.")
            else:
                attempt(request, lambda: hospital_signup.reject(request.user, hospital.pk, request.POST.get("reason"),
                                                                request), "Đã từ chối đăng ký bệnh viện.")
            return redirect("bloodbank:admin_hospital_edit", pk=hospital.pk)
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
    return render(request, "admin/hospital_form.html", {"form": form, "h": hospital, "staffs": staffs,
                                                        **map_center(hospital)})


@admin_required
def audit(request):
    hospital_id = request.GET.get("hospital") or ""
    base = AuditLog.objects.select_related("actor", "hospital")
    if hospital_id:
        base = base.filter(hospital_id=hospital_id)
    qs, f, actions = audit_filters(request, base)
    f["hospital"] = hospital_id
    return render(request, "shared/audit.html", {
        "page": paginate(request, qs, 50), "f": f, "scope": "system", "hospitals": Hospital.objects.all(),
        "actions": actions,
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


@admin_required
def alerts(request):
    """SCR-57: liên kết cũ trong thông báo nhắc quá hạn → danh sách bệnh viện (liên hệ bệnh viện chậm xử lý)."""
    return redirect("bloodbank:admin_hospitals")


@admin_required
def forecast_monitor(request):
    """SCR-59: dự báo AI — bật/tắt, phiên bản đang dùng, độ chính xác thật theo tuần, quay lại bản cũ, huấn luyện lại."""
    from bloodbank.services.forecast_ml import monitor

    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("ai", "auto"):
            key = "forecast_ai_enabled" if action == "ai" else "forecast_auto_retrain"
            on = request.POST.get("value") == "on"
            label = "Dự báo AI" if action == "ai" else "Tự huấn luyện lại"
            ok, _ = attempt(request, lambda: admin_service.save_setting(request.user, key, "true" if on else "false",
                                                                       request), f"Đã {'bật' if on else 'tắt'} {label.lower()}.")
            if ok and action == "ai":
                monitor.refresh_snapshots()                 # trang Dự báo đổi ngay, không chờ đêm
        elif action == "activate":
            version = request.POST.get("version")
            ok, _ = attempt(request, lambda: admin_service.forecast_activate(request.user, version, request),
                            f"Đang dùng phiên bản {version}.")
            if ok:
                monitor.refresh_snapshots()
        elif action == "train":
            attempt(request, lambda: admin_service.forecast_request_training(request.user, request),
                    "Đã xếp lịch huấn luyện lại — tác vụ định kỳ sẽ chạy trong vài phút tới.")
        return redirect("bloodbank:admin_forecast")
    return render(request, "admin/forecast.html", {"s": monitor.dashboard()})


@admin_required
def assistant_monitor(request):
    """SCR-58: theo dõi trợ lý hỏi đáp; bật/tắt AI (ghi qua cấu hình hệ thống, có nhật ký)."""
    if request.method == "POST":
        on = request.POST.get("ai") == "on"
        attempt(request, lambda: admin_service.save_setting(request.user, "chatbot_ai_enabled",
                                                            "true" if on else "false", request),
                "Đã bật AI cho trợ lý." if on else "Đã tắt AI: trợ lý trả lời bằng chế độ từ khóa.")
        return redirect("bloodbank:admin_assistant")
    return render(request, "admin/assistant.html", {"s": admin_service.assistant_stats()})

