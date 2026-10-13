"""SCR-07..13: khu vực cá nhân (chỉ dữ liệu của chính mình — BR-13)."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import services as account_services
from accounts.forms import ChangePasswordForm, ProfileForm, WorkProfileForm
from bloodbank.forms import PatientRequestForm
from bloodbank.models import Donation, Hospital, Notification, PatientRequest, Registration
from bloodbank.permissions import current_staff, member_required, signed_in_required
from bloodbank.services import campaigns as cmp
from bloodbank.services import donations as don
from bloodbank.services import patients as prq_service
from bloodbank.services.common import BusinessError

from .helpers import attempt, paginate


@member_required
def profile(request):
    user = request.user
    form = ProfileForm(request.POST if request.POST.get("form") == "profile" else None, instance=user)
    pw_form = ChangePasswordForm(request.POST if request.POST.get("form") == "password" else None, user=user)
    if request.method == "POST":
        if request.POST.get("form") == "profile" and form.is_valid():
            account_services.update_profile(user, form, request)
            messages.success(request, "Đã cập nhật hồ sơ.")
            return redirect("bloodbank:profile")
        if request.POST.get("form") == "password" and pw_form.is_valid():
            account_services.change_password(user, pw_form.cleaned_data["password"], request)
            update_session_auth_hash(request, user)
            messages.success(request, "Đã đổi mật khẩu.")
            return redirect("bloodbank:profile")
    summary = don.summarize(Donation.objects.filter(donor=user))
    return render(request, "member/profile.html", {"form": form, "pw_form": pw_form, "summary": summary,
                                                   "tab": "profile"})


@member_required
def my_registrations(request):
    qs = Registration.objects.filter(donor=request.user).select_related("campaign__hospital").order_by("-registered_at")
    status = request.GET.get("status")
    if status == "active":
        qs = qs.filter(status__in=["pending", "approved", "attended"])
    elif status == "done":
        qs = qs.exclude(status__in=["pending", "approved", "attended"])
    now = timezone.now()
    page = paginate(request, qs, 15)
    for reg in page:
        reg.can_cancel = reg.status in ("pending", "approved")
        reg.can_reregister = reg.status == "cancelled" and reg.campaign.status == "open" and reg.campaign.end_time > now
    return render(request, "member/registrations.html", {"page": page, "status": status, "tab": "registrations"})


@member_required
@require_POST
def cancel_registration(request, pk):
    reg = get_object_or_404(Registration, pk=pk, donor=request.user)
    attempt(request, lambda: cmp.cancel_registration(request.user, reg, request), "Đã hủy đơn đăng ký.")
    return redirect("bloodbank:my_registrations")


@member_required
@require_POST
def reregister(request, pk):
    reg = get_object_or_404(Registration, pk=pk, donor=request.user)
    attempt(request, lambda: cmp.register_for_campaign(request.user, reg.campaign, reg.donation_type, reg.note, request),
            "Đã đăng ký lại, chờ bệnh viện xác nhận.")
    return redirect("bloodbank:my_registrations")


@member_required
def my_history(request):
    """SCR-09: 4 thẻ tổng quan + bộ lọc + danh sách; voided chỉ khi bật tùy chọn."""
    base = Donation.objects.filter(donor=request.user)
    summary = don.summarize(base)
    qs = don.donor_history(request.user)
    show_voided = request.GET.get("voided") == "1"
    if not show_voided:
        qs = qs.filter(status="confirmed")
    f = {k: request.GET.get(k) or "" for k in ("year", "hospital", "type")}
    if f["year"]:
        qs = qs.filter(donated_at__year=f["year"])
    if f["hospital"]:
        qs = qs.filter(hospital_id=f["hospital"])
    if f["type"]:
        qs = qs.filter(donation_type=f["type"])
    years = sorted({d.year for d in base.dates("donated_at", "year")}, reverse=True)
    hospitals = Hospital.objects.filter(donations__donor=request.user).distinct()
    page = paginate(request, qs, 15)
    return render(request, "member/history.html", {
        "summary": summary, "page": page, "show_voided": show_voided, "f": f, "years": years, "hospitals": hospitals,
        "has_any": base.exists(), "filtered": any(f.values()), "tab": "history",
    })


@member_required
def my_donation_detail(request, pk):
    d = Donation.objects.select_related("hospital", "registration__campaign", "component_product").filter(
        pk=pk, donor=request.user
    ).first()
    if d is None:
        raise Http404  # truy cập trái quyền → 404 (BR-13)
    return render(request, "member/donation_detail.html", {"d": d, "tab": "history"})


@member_required
def patient_request_new(request):
    """SCR-11: gửi yêu cầu cần máu — tối giản, dùng được một tay trên điện thoại."""
    user = request.user
    initial = {"contact_name": user.full_name, "contact_phone": user.phone_display}
    form = PatientRequestForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            prq = prq_service.submit(user, form.cleaned_data, request)
        except BusinessError as exc:
            messages.error(request, exc.message)
        else:
            return redirect("bloodbank:my_patient_request_detail", pk=prq.pk)
    return render(request, "member/patient_request_form.html", {"form": form})


@member_required
def my_patient_requests(request):
    qs = PatientRequest.objects.filter(requester=request.user).select_related("hospital")
    page = paginate(request, qs, 15)
    return render(request, "member/patient_requests.html", {"page": page, "tab": "patient"})


@member_required
def my_patient_request_detail(request, pk):
    prq = PatientRequest.objects.select_related("hospital", "blood_product").filter(pk=pk, requester=request.user).first()
    if prq is None:
        raise Http404
    just_created = (timezone.now() - prq.created_at).total_seconds() < 120 and prq.status == "submitted"
    steps = [
        ("submitted", "Đã gửi", "Hệ thống đã tiếp nhận yêu cầu."),
        ("verifying", "Bệnh viện xác minh", "Bệnh viện điều trị kiểm tra thông tin và nhóm máu."),
        ("processing", "Đang điều phối", "Bệnh viện tìm nguồn máu phù hợp."),
        ("fulfilled", "Hoàn tất", "Bệnh viện xác nhận đã xử lý xong."),
    ]
    order = {"submitted": 0, "verifying": 1, "verified": 1, "processing": 2, "fulfilled": 3}
    return render(request, "member/patient_request_detail.html", {
        "prq": prq, "just_created": just_created, "steps": steps, "current": order.get(prq.status, -1),
        "can_cancel": prq.status in ("submitted", "verifying", "verified"), "tab": "patient",
    })


@member_required
@require_POST
def cancel_patient_request(request, pk):
    attempt(request, lambda: prq_service.cancel_by_requester(request.user, pk, request), "Đã hủy yêu cầu.")
    return redirect("bloodbank:my_patient_request_detail", pk=pk)


ENTITY_LINKS = {
    "registrations": lambda n: reverse("bloodbank:my_registrations"),
    "donations": lambda n: reverse("bloodbank:my_donation_detail", args=[n.entity_id]),
    "campaigns": lambda n: reverse("bloodbank:campaign_detail", args=[n.entity_id]),
    "request_offers": lambda n: reverse("bloodbank:offer_open", args=[n.entity_id]),
    "hospital_requests": lambda n: reverse("bloodbank:support_request_detail", args=[n.entity_id]),
}


def notification_link(n):
    if n.entity_type == "patient_requests":
        if n.type in ("patient_request_new", "patient_request_cancelled"):
            return reverse("bloodbank:hospital_patient_request_detail", args=[n.entity_id])
        return reverse("bloodbank:my_patient_request_detail", args=[n.entity_id])
    if n.entity_type == "donations" and n.type not in ("donation_recorded", "donation_voided", "donation_updated"):
        return reverse("bloodbank:hospital_donation_detail", args=[n.entity_id])
    fn = ENTITY_LINKS.get(n.entity_type)
    try:
        return fn(n) if fn else None
    except Exception:
        return None


@signed_in_required
def notifications(request):
    qs = Notification.objects.filter(user=request.user)
    if request.GET.get("unread") == "1":
        qs = qs.filter(read_at__isnull=True)
    page = paginate(request, qs, 20)
    for n in page:
        n.link = notification_link(n)
    # Người dùng xem trong khu cá nhân; Nhân viên bệnh viện / Quản trị xem trong khu làm việc
    template = "member/notifications.html" if request.user.role == "member" else "shared/notifications.html"
    return render(request, template, {"page": page, "unread_only": request.GET.get("unread") == "1",
                                      "tab": "notifications"})


@signed_in_required
@require_POST
def notifications_read(request):
    qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
    if request.POST.get("id"):
        qs = qs.filter(pk=request.POST["id"])
    qs.update(read_at=timezone.now())
    target = request.POST.get("next")
    if target and target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect("bloodbank:notifications")


@signed_in_required
def work_account(request):
    """SCR-15: tài khoản công tác của Nhân viên bệnh viện / Quản trị — họ tên, điện thoại, đổi mật khẩu."""
    user = request.user
    if user.role == "hospital":
        staff = current_staff(request)
        if staff is not None:
            request.staff, request.hospital = staff, staff.hospital
    form = WorkProfileForm(request.POST if request.POST.get("form") == "profile" else None, instance=user)
    pw_form = ChangePasswordForm(request.POST if request.POST.get("form") == "password" else None, user=user)
    if request.method == "POST":
        if request.POST.get("form") == "profile" and form.is_valid():
            account_services.update_profile(user, form, request)
            messages.success(request, "Đã cập nhật thông tin tài khoản.")
            return redirect("bloodbank:work_account")
        if request.POST.get("form") == "password" and pw_form.is_valid():
            account_services.change_password(user, pw_form.cleaned_data["password"], request)
            update_session_auth_hash(request, user)
            messages.success(request, "Đã đổi mật khẩu.")
            return redirect("bloodbank:work_account")
    return render(request, "shared/account.html", {"form": form, "pw_form": pw_form})
