"""SCR-01..05: trang chủ, đợt hiến công khai, bản đồ, chatbot."""
from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.forms import PROVINCES
from bloodbank import content
from bloodbank.forms import RegistrationForm
from bloodbank.assistant import service as assistant
from bloodbank.models import Campaign, Hospital, Registration
from bloodbank.permissions import deny
from bloodbank.services import campaigns as cmp
from bloodbank.services.common import BusinessError

from .helpers import paginate

def home(request):
    now = timezone.now()
    upcoming = Campaign.objects.public().filter(status="open", end_time__gt=now).order_by("start_time")[:3]
    return render(request, "public/home.html", {"upcoming": upcoming, "news": content.NEWS})


def campaign_list(request):
    now = timezone.now()
    qs = Campaign.objects.public()
    when = request.GET.get("when", "upcoming")
    if when == "upcoming":
        qs = qs.filter(end_time__gt=now).exclude(status="completed").order_by("start_time")
    else:
        qs = qs.filter(Q(end_time__lte=now) | Q(status="completed")).order_by("-start_time")
    province = request.GET.get("province")
    if province:
        qs = qs.filter(Q(province=province) | Q(province__isnull=True, hospital__province=province))
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(location_name__icontains=q) | Q(address__icontains=q)
                       | Q(hospital__name__icontains=q))
    page = paginate(request, qs.annotate(reg_count=Count("registrations")), 12)
    my = {}
    if request.user.is_authenticated:
        my = dict(Registration.objects.filter(donor=request.user, campaign__in=[c.pk for c in page])
                  .values_list("campaign_id", "status"))
    return render(request, "public/campaign_list.html", {
        "page": page, "when": when, "province": province, "q": q, "provinces": PROVINCES, "my": my,
        "filtered": bool(province or q),
    })


def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign.objects.public(), pk=pk)
    reg = None
    if request.user.is_authenticated:
        reg = Registration.objects.filter(campaign=campaign, donor=request.user).first()
    state = cmp.registration_view_state(campaign, reg)
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        if request.user.role != "member":
            deny(request, "member_role")
        if form.is_valid():
            try:
                cmp.register_for_campaign(request.user, campaign, form.cleaned_data["donation_type"],
                                          form.cleaned_data["note"], request)
            except BusinessError as exc:
                messages.error(request, exc.message)
            else:
                messages.success(request, "Đã gửi đơn đăng ký, chờ bệnh viện xác nhận.")
                return redirect("bloodbank:my_registrations")
    return render(request, "public/campaign_detail.html", {"c": campaign, "reg": reg, "state": state, "form": form})


def map_view(request):
    return render(request, "public/map.html", {"provinces": PROVINCES})


def map_data(request):
    """MAP-01: chỉ dữ liệu công khai; không lưu vị trí người dùng."""
    now = timezone.now()
    hospitals = [
        {"type": "hospital", "id": h.pk, "name": h.name, "address": h.address, "area": h.area, "province": h.province,
         "phone": h.phone or "", "lat": float(h.latitude), "lng": float(h.longitude)}
        for h in Hospital.objects.filter(status="active", latitude__isnull=False)
    ]
    camps = [
        {"type": "campaign", "id": c.pk, "name": c.name, "address": f"{c.location_name}, {c.address}",
         "area": c.hospital.name, "province": c.province or c.hospital.province,
         "time": f"{timezone.localtime(c.start_time):%H:%M %d/%m} – {timezone.localtime(c.end_time):%H:%M %d/%m}",
         "url": reverse("bloodbank:campaign_detail", args=[c.pk]),
         "lat": float(c.latitude if c.latitude is not None else c.hospital.latitude),
         "lng": float(c.longitude if c.longitude is not None else c.hospital.longitude)}
        for c in Campaign.objects.public().filter(status="open", end_time__gt=now)
        if c.latitude is not None or c.hospital.latitude is not None
    ]
    return JsonResponse({"hospitals": hospitals, "campaigns": camps})


@require_POST
def chatbot(request):
    """BOT-01: trợ lý hỏi đáp — nội dung đã duyệt + dữ liệu của chính người hỏi (chỉ đọc), không kết luận lâm sàng."""
    from .api import chat_message   # tránh vòng import: api ↔ public

    if request.POST.get("reset") == "1":
        assistant.reset(request)
        return JsonResponse({"ok": True})
    return chat_message(request)   # dùng chung xử lý với POST /api/chatbot/message

