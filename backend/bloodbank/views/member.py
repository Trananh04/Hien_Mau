"""SCR-07..13: khu vực cá nhân (chỉ dữ liệu của chính mình — BR-13)."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db.models import Q
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
from bloodbank.services import badges
from bloodbank.services import campaigns as cmp
from bloodbank.services import donations as don
from bloodbank.services import patients as prq_service
from bloodbank.services.common import BusinessError, mark_notifications_read

from .helpers import attempt, int_or_none, paginate, safe_next


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
        qs = qs.filter(status__in=Registration.ACTIVE_STATUSES)
    elif status == "done":
        qs = qs.exclude(status__in=Registration.ACTIVE_STATUSES)
    now = timezone.now()
    page = paginate(request, qs, 15)
    for reg in page:
        reg.reregister_allowed = reg.can_reregister(now)
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
        "eligible": badges.next_eligible(request.user),
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
    return render(request, "member/patient_request_detail.html", {
        "prq": prq, "just_created": just_created, "steps": PatientRequest.PROGRESS_STEPS,
        "current": prq.progress_index, "can_cancel": prq.can_cancel, "tab": "patient",
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
    "hospitals": lambda n: reverse("bloodbank:campaigns"),
    # Lời kêu gọi hiến máu: trang lời mời (bệnh viện, địa chỉ, nút gọi / chỉ đường, đợt hiến kèm theo nếu có)
    "donor_callouts": lambda n: reverse("bloodbank:my_invitation", args=[n.entity_id]),
}


@member_required
def my_invitation(request, pk):
    """Lời mời hiến máu người dùng đã nhận. Chỉ người được mời mở được (người khác → 404)."""
    from bloodbank.models import DonorCallout

    note = (Notification.objects.filter(user=request.user, type="donor_callout", channel="in_app",
                                        entity_type="donor_callouts", entity_id=pk).order_by("-created_at").first())
    callout = DonorCallout.objects.select_related("hospital", "campaign").filter(pk=pk).first()
    if note is None or callout is None:
        raise Http404
    mark_notifications_read(request.user, note.pk)
    return render(request, "member/invitation.html", {
        "c": callout, "h": callout.hospital, "note": note, "urgent": note.title.startswith("[Khẩn]"),
        "campaign": callout.campaign if callout.campaign and callout.campaign.status == "open" else None,
    })


def notification_link(n):
    # Chọn trang theo VAI TRÒ người nhận (không theo danh sách loại thông báo): người dùng luôn tới trang của mình,
    # nhân viên tới trang bệnh viện — tránh liên kết nhầm cổng (vd "đủ điều kiện hiến lại" từng trỏ tới trang bệnh viện)
    staff_side = n.user.role != "member"
    if n.entity_type == "patient_requests":
        name = "hospital_patient_request_detail" if staff_side else "my_patient_request_detail"
        return reverse(f"bloodbank:{name}", args=[n.entity_id])
    if n.entity_type == "donations":
        name = "hospital_donation_detail" if staff_side else "my_donation_detail"
        return reverse(f"bloodbank:{name}", args=[n.entity_id])
    if n.entity_type == "hospitals" and n.user.role == "admin":      # bệnh viện mới đăng ký → trang duyệt
        return reverse("bloodbank:admin_hospital_edit", args=[n.entity_id])
    if n.entity_type == "hospitals" and n.user.role == "hospital":
        return reverse("bloodbank:hospital_dashboard")
    fn = ENTITY_LINKS.get(n.entity_type)
    try:
        return fn(n) if fn else None
    except Exception:
        return None


# Loại thông báo theo nghiệp vụ: (nhãn, icon, tiền tố mã loại)
NOTIF_CATEGORIES = {
    "nguoi-can-mau": ("Người cần máu", "heart-pulse", ("patient_request_", "prq_")),
    "lien-vien": ("Liên viện", "truck", ("offer_", "request_")),
    "hien-mau": ("Hiến máu", "calendar-heart", ("registration_", "donation_", "campaign_", "eligible_", "donor_callout")),
    "tai-khoan": ("Tài khoản", "user-cog", ("staff_", "hospital_")),
}
# Cần phản ứng ngay: yêu cầu cần máu mới / bị nhắc lại, bệnh viện khác xin cấp máu, lời kêu gọi hiến, đợt hiến bị hủy
URGENT_TYPES = {"hospital_signup", "patient_request_new", "prq_escalated_staff", "prq_escalated_admin", "offer_received",
                "donor_callout", "campaign_cancelled"}


def notification_category(n):
    for key, (label, icon, prefixes) in NOTIF_CATEGORIES.items():
        if n.type.startswith(prefixes):
            return key, label, icon
    return "khac", "Khác", "bell"


@signed_in_required
def notifications(request):
    base = Notification.objects.filter(user=request.user, channel="in_app").select_related("user")
    qs = base
    unread_only = request.GET.get("unread") == "1"
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    cat = request.GET.get("cat") or ""
    if cat in NOTIF_CATEGORIES:
        cond = Q()
        for prefix in NOTIF_CATEGORIES[cat][2]:
            cond |= Q(type__startswith=prefix)
        qs = qs.filter(cond)
    else:
        cat = ""
    page = paginate(request, qs, 20)
    for n in page:
        n.link = notification_link(n)
        n.cat_key, n.cat_label, n.cat_icon = notification_category(n)
        n.urgent = n.type in URGENT_TYPES
    # Chỉ hiện bộ lọc loại có thông báo, để không có nút lọc trống
    present = set(base.values_list("type", flat=True).distinct())
    categories = [(k, label) for k, (label, _, prefixes) in NOTIF_CATEGORIES.items()
                  if any(t.startswith(prefixes) for t in present)]
    # Người dùng xem trong khu cá nhân; Nhân viên bệnh viện / Quản trị xem trong khu làm việc
    template = "member/notifications.html" if request.user.role == "member" else "shared/notifications.html"
    return render(request, template, {"page": page, "unread_only": unread_only, "cat": cat,
                                      "categories": categories, "tab": "notifications"})


@signed_in_required
@require_POST
def notifications_read(request):
    nid = request.POST.get("id")
    if not nid or int_or_none(nid) is not None:   # id sai kiểu → không đánh dấu gì (không phải "tất cả")
        mark_notifications_read(request.user, int_or_none(nid))
    return safe_next(request, "bloodbank:notifications")


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
