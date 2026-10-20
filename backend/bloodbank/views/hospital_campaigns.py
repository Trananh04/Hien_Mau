"""SCR-21..27: đợt hiến (quản lý), điểm hiến, lượt hiến, tra cứu người hiến, báo cáo tiếp nhận."""
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.forms import PROVINCES
from accounts.models import BLOOD_GROUP_VALUES, User, normalize_phone
from bloodbank.forms import CampaignForm
from bloodbank.models import AuditLog, Campaign, Donation, Product, Registration
from bloodbank.permissions import staff_required
from bloodbank.services import campaigns as cmp
from bloodbank.services import donations as don
from bloodbank.services.common import BusinessError

from .helpers import apply_field_errors, attempt, date_or_none, int_or_none, paginate, parse_local_dt, safe_next



def _campaign(request, pk):
    return get_object_or_404(Campaign, pk=pk, hospital=request.hospital)


@staff_required
def campaigns(request):
    qs = Campaign.objects.filter(hospital=request.hospital).annotate(
        reg_count=Count("registrations", distinct=True),
        donated=Count("registrations", filter=Q(registrations__status="donated"), distinct=True),
    )
    status = request.GET.get("status") or ""
    if status:
        qs = qs.filter(status=status)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(location_name__icontains=q))
    qs = qs.order_by("-start_time")
    return render(request, "hospital/campaigns.html", {
        "page": paginate(request, qs, 20), "status": status, "q": q, "statuses": Campaign.Status.choices,
        "can_edit": True,
    })


@staff_required
def campaign_form(request, pk=None):
    campaign = _campaign(request, pk) if pk else None
    if campaign and not campaign.is_editable:
        messages.error(request, "Đợt đã kết thúc hoặc đã hủy, không thể sửa.")
        return redirect("bloodbank:hospital_campaign_detail", pk=campaign.pk)
    initial = {"province": request.hospital.province}
    bg = request.GET.get("blood_group")
    if not campaign and bg in BLOOD_GROUP_VALUES:
        initial.update(cmp.urgent_campaign_initial(request.hospital, bg))   # tạo nhanh từ dòng thiếu hụt
    if campaign:
        initial = cmp.campaign_form_initial(campaign)
    form = CampaignForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            if campaign:
                campaign = cmp.update_campaign(request.staff, campaign, form.cleaned_data, request)
                messages.success(request, "Đã cập nhật đợt hiến.")
            else:
                campaign = cmp.create_campaign(request.staff, form.cleaned_data, request)
                messages.success(request, "Đã tạo đợt hiến ở trạng thái Nháp. Bấm Công bố để hiển thị công khai.")
        except BusinessError as exc:
            apply_field_errors(form, exc)
            messages.error(request, exc.message)
        else:
            return redirect("bloodbank:hospital_campaign_detail", pk=campaign.pk)
    return render(request, "hospital/campaign_form.html", {
        "form": form, "campaign": campaign, "provinces": PROVINCES,
        "default_lat": request.hospital.latitude or 16.0544, "default_lng": request.hospital.longitude or 108.2022,
    })


@staff_required
def campaign_detail(request, pk):
    campaign = _campaign(request, pk)
    tab = request.GET.get("tab", "info")
    ctx = {"c": campaign, "tab": tab, "can_edit": True,
           "actions": cmp.campaign_actions(campaign),
           "summary": cmp.campaign_summary(campaign), "reg_statuses": Registration.Status.choices}
    if tab == "registrations":
        regs = campaign.registrations.select_related("donor").order_by("status", "registered_at")
        status = request.GET.get("status") or ""
        if status:
            regs = regs.filter(status=status)
        q = (request.GET.get("q") or "").strip()
        if q:
            regs = regs.filter(Q(donor__full_name__icontains=q) | Q(donor__email__icontains=q)
                               | Q(donor__phone__icontains=normalize_phone(q) or q))
        ctx.update(page=paginate(request, regs, 30), status=status, q=q)
    return render(request, "hospital/campaign_detail.html", ctx)


@staff_required
@require_POST
def campaign_action(request, pk):
    campaign = _campaign(request, pk)
    action = request.POST.get("action")
    labels = {"publish": "Đã công bố đợt hiến.", "close": "Đã ngừng nhận đăng ký.", "reopen": "Đã mở lại đăng ký.",
              "complete": "Đã hoàn tất đợt hiến.", "cancel": "Đã hủy đợt hiến; các đơn chưa xử lý đã được hủy và thông báo."}
    attempt(request, lambda: cmp.transition_campaign(request.staff, campaign, action, request.POST.get("reason"), request),
            labels.get(action))
    return redirect("bloodbank:hospital_campaign_detail", pk=pk)


@staff_required
@require_POST
def registration_action(request, pk):
    reg = get_object_or_404(Registration, pk=pk, campaign__hospital=request.hospital)
    action = request.POST.get("action")
    labels = {"approve": "Đã duyệt đơn.", "reject": "Đã từ chối đơn.", "checkin": "Đã check-in.",
              "undo_checkin": "Đã hoàn tác check-in.", "no_show": "Đã đánh dấu vắng mặt.",
              "not_donated": "Đã ghi nhận có mặt nhưng không hiến."}
    attempt(request, lambda: cmp.staff_registration_action(request.staff, reg.pk, action, request.POST.get("reason"), request),
            labels.get(action))
    return safe_next(request, f"{reverse('bloodbank:hospital_campaign_detail', args=[reg.campaign_id])}?tab=registrations")


# ---------------------------------------------------------------- SCR-24 Điểm hiến
@staff_required
def checkin(request, pk):
    campaign = _campaign(request, pk)
    if not campaign.checkin_open:
        messages.error(request, "Chỉ mở điểm hiến cho đợt đang mở hoặc đã ngừng nhận đăng ký.")
        return redirect("bloodbank:hospital_campaign_detail", pk=pk)
    regs = campaign.registrations.select_related("donor").exclude(status="cancelled")
    q = (request.GET.get("q") or "").strip()
    if q:
        cond = Q(donor__full_name__icontains=q) | Q(donor__email__icontains=q)
        phone = normalize_phone(q)
        if phone and phone[1:].isdigit():
            cond |= Q(donor__phone=phone)
        code = q.upper().replace("DK-", "")
        if code.isdigit():
            cond |= Q(pk=int(code))
        regs = regs.filter(cond)
    status = request.GET.get("status", "waiting")
    if status == "waiting":
        regs = regs.filter(status__in=Registration.WAITING_STATUSES)
    elif status == "attended":
        regs = regs.filter(status=Registration.Status.ATTENDED)
    elif status == "done":
        regs = regs.filter(status__in=Registration.DONE_STATUSES)
    regs = regs.order_by("donor__full_name")
    selected = None
    reg_id = int_or_none(request.GET.get("reg"))
    if reg_id:
        selected = campaign.registrations.select_related("donor").filter(pk=reg_id).first()
    counts = dict(campaign.registrations.values_list("status").annotate(n=Count("id")))
    now = timezone.localtime()
    default_time = min(max(now, timezone.localtime(campaign.start_time)), timezone.localtime(campaign.end_time))
    return render(request, "hospital/checkin.html", {
        "c": campaign, "regs": regs[:200], "q": q, "status": status, "selected": selected, "counts": counts,
        "waiting_count": counts.get("pending", 0) + counts.get("approved", 0),
        "products": Product.objects.filter(is_active=True, kind="component"), "default_time": default_time,
        "started": timezone.now() >= campaign.start_time, "form_data": request.session.pop("donation_form", None),
        "needs_confirm": request.session.pop("donation_needs_confirm", None),
        "selected_donation": selected.donations.filter(status="confirmed").first() if selected else None,
        "interval_warning": don.interval_warning(selected.donor)
        if selected and selected.status in Registration.ACTIVE_STATUSES else None,
    })


def _checkin_url(campaign_id, reg_id=None, status=None):
    url = reverse("bloodbank:checkin", args=[campaign_id])
    params = []
    if reg_id:
        params.append(f"reg={reg_id}")
    if status:
        params.append(f"status={status}")
    return url + ("?" + "&".join(params) if params else "")


@staff_required
@require_POST
def record_donation(request, pk):
    reg = get_object_or_404(Registration, pk=pk, campaign__hospital=request.hospital)
    data = request.POST.dict()
    data["donated_at"] = parse_local_dt(data.get("donated_at"))
    try:
        don.record_donation(request.staff, reg.pk, data, request, confirm_volume=data.get("confirm_volume") == "1")
    except BusinessError as exc:
        messages.error(request, exc.message)
        request.session["donation_form"] = {k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"}
        if exc.field_errors.get("_needs_confirm"):
            request.session["donation_needs_confirm"] = exc.message
        return redirect(_checkin_url(reg.campaign_id, reg.pk, "attended"))
    messages.success(request, f"Đã ghi nhận lượt hiến của {reg.donor.full_name}. Lượt hiến đã vào hàng Chờ xét nghiệm.")
    return redirect(_checkin_url(reg.campaign_id, None, "attended"))


@staff_required
@require_POST
def checkin_action(request, pk):
    """Check-in / Không hiến / Vắng / Hoàn tác từ màn hình điểm hiến."""
    reg = get_object_or_404(Registration, pk=pk, campaign__hospital=request.hospital)
    action = request.POST.get("action")
    ok, _ = attempt(request, lambda: cmp.staff_registration_action(request.staff, reg.pk, action,
                                                                   request.POST.get("reason"), request),
                    {"checkin": f"Đã check-in {reg.donor.full_name}.", "not_donated": "Đã ghi nhận: có mặt, không hiến.",
                     "no_show": "Đã đánh dấu vắng mặt.", "undo_checkin": "Đã hoàn tác check-in.",
                     "approve": "Đã duyệt đơn."}.get(action))
    if ok and action == "checkin":
        warn = don.interval_warning(reg.donor)
        if warn:
            messages.warning(request, f"Lưu ý {reg.donor.full_name}: {warn['text']}")
    status = "attended" if action == "checkin" and ok else request.POST.get("status")
    return redirect(_checkin_url(reg.campaign_id, reg.pk if action == "checkin" and ok else None, status))


@staff_required
@require_POST
def walk_in(request, pk):
    campaign = _campaign(request, pk)
    donor = cmp.find_donor(request.POST.get("lookup"))
    if donor is None:
        messages.error(request, "Không tìm thấy tài khoản với email/số điện thoại này. Người hiến cần có tài khoản trên nền tảng.")
        return redirect(_checkin_url(pk))
    ok, reg = attempt(request, lambda: cmp.walk_in(request.staff, campaign, donor, request.POST.get("donation_type"),
                                                   request.POST.get("reason"), request),
                      f"Đã tạo đơn tại chỗ và check-in cho {donor.full_name}.")
    if ok:
        warn = don.interval_warning(donor)
        if warn:
            messages.warning(request, f"Lưu ý {donor.full_name}: {warn['text']}")
    return redirect(_checkin_url(pk, reg.pk if ok else None, "attended" if ok else None))


# ---------------------------------------------------------------- SCR-25 Lượt hiến (bệnh viện)
@staff_required
def donation_detail(request, pk):
    d = get_object_or_404(
        Donation.objects.select_related("donor", "registration__campaign", "confirmed_by", "voided_by", "component_product"),
        pk=pk, hospital=request.hospital,
    )
    logs = AuditLog.objects.filter(entity_type="donations", entity_id=d.pk).select_related("actor")
    summary_before = don.summarize(Donation.objects.filter(donor=d.donor))
    return render(request, "hospital/donation_detail.html", {
        "d": d, "logs": logs, "can_manage": d.status == Donation.Status.CONFIRMED, "summary": summary_before,
        "products": Product.objects.filter(is_active=True, kind="component"),
    })


@staff_required
@require_POST
def donation_manage(request, pk):
    d = get_object_or_404(Donation, pk=pk, hospital=request.hospital)
    action = request.POST.get("action")
    if action == "void":
        attempt(request, lambda: don.void_donation(request.staff, d.pk, request.POST.get("reason"),
                                                   request.POST.get("target_status"), request),
                "Đã hủy hiệu lực lượt hiến. Thống kê đã được tính lại.")
    elif action == "edit":
        data = request.POST.dict()
        data["donated_at"] = parse_local_dt(data.get("donated_at"))
        attempt(request, lambda: don.edit_donation(request.staff, d.pk, data, request.POST.get("reason"), request),
                "Đã cập nhật lượt hiến.")
    return redirect("bloodbank:hospital_donation_detail", pk=pk)


# ---------------------------------------------------------------- SCR-26 Tra cứu người hiến
@staff_required
def donor_lookup(request):
    q = (request.GET.get("q") or "").strip()
    donors, selected, history, regs = [], None, None, None
    scope = Q(donations__hospital=request.hospital) | Q(registrations__campaign__hospital=request.hospital)
    if q:
        cond = Q(full_name__icontains=q) | Q(email__icontains=q.lower())
        phone = normalize_phone(q)
        if phone and phone[1:].isdigit():
            cond |= Q(phone=phone)
        donors = User.objects.filter(cond).filter(scope).distinct().order_by("full_name")[:50]
    if request.GET.get("donor"):
        donor_id = int_or_none(request.GET["donor"])
        selected = User.objects.filter(scope).filter(pk=donor_id).distinct().first() if donor_id else None
        if selected is None:
            raise Http404
        hd = Donation.objects.filter(donor=selected, hospital=request.hospital).select_related("registration__campaign")
        history = {"summary": don.summarize(hd), "rows": hd.order_by("-donated_at")}
        regs = Registration.objects.filter(donor=selected, campaign__hospital=request.hospital).select_related("campaign")
    return render(request, "hospital/donor_lookup.html", {"q": q, "donors": donors, "selected": selected,
                                                          "history": history, "regs": regs})


# ---------------------------------------------------------------- SCR-27 Báo cáo tiếp nhận
@staff_required
def donation_report(request):
    today = timezone.localdate()
    start = date_or_none(request.GET.get("from")) or today.replace(day=1) - timedelta(days=150)
    end = date_or_none(request.GET.get("to")) or today
    campaign_id = request.GET.get("campaign") or ""
    report = don.donation_report(request.hospital, start, end, int_or_none(campaign_id))
    return render(request, "hospital/donation_report.html", {
        **report, "from": start, "to": end, "campaign_id": campaign_id,
        "campaigns": Campaign.objects.filter(hospital=request.hospital).order_by("-start_time"),
    })
