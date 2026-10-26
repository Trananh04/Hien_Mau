"""SCR-01..05: trang chủ, đợt hiến công khai, bản đồ, chatbot."""
from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.provinces import PROVINCES
from bloodbank.forms import RegistrationForm
from bloodbank import content
from bloodbank.assistant import service as assistant
from bloodbank.models import Campaign, Hospital, Registration, SystemSetting
from bloodbank.permissions import deny
from bloodbank.services import campaigns as cmp
from bloodbank.services.common import BusinessError

from .helpers import paginate

def home(request):
    news = sorted(content.NEWS, key=lambda n: n["date"], reverse=True)
    return render(request, "public/home.html", {"news": news})


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


def process(request):
    """SCR-05: quy trình tham gia hiến máu — điều kiện & khoảng nghỉ lấy từ cấu hình hệ thống."""
    g = SystemSetting.get
    return render(request, "public/process.html", {
        "min_age": g("donor_min_age"), "max_age": g("donor_max_age"),
        "min_w_male": g("donor_min_weight_male_kg"), "min_w_female": g("donor_min_weight_female_kg"),
        "interval_whole": g("donation_interval_whole_blood_days"),
        "interval_component": g("donation_interval_component_days"),
    })


def map_view(request):
    return render(request, "public/map.html", {"provinces": PROVINCES})


def _geo_rate_limited(request, per_minute=60):
    """Chặn lạm dụng các API bản đồ (Goong tính phí theo lượt): tối đa `per_minute` lượt / phút / địa chỉ IP."""
    from django.core.cache import cache

    key = f"geo-rate:{request.META.get('REMOTE_ADDR', '')}"
    cache.add(key, 0, 60)
    return cache.incr(key) > per_minute


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


TOO_MANY = {"error": "Tra cứu quá nhiều, thử lại sau ít phút."}


def geocode(request):
    """GET ?address=…&province=… → {"lat", "lng", "label"} (404 nếu không tìm thấy). Dùng cho ô chọn vị trí bản đồ."""
    from bloodbank.services import geocode as geo

    if _geo_rate_limited(request):
        return JsonResponse(TOO_MANY, status=429)
    found = geo.lookup(request.GET.get("address"), request.GET.get("province"))
    if not found:
        return JsonResponse({"error": "Không tìm thấy địa chỉ trên bản đồ. Hãy bấm lên bản đồ để ghim."}, status=404)
    return JsonResponse(found)


def geo_suggest(request):
    """GET ?q=…[&lat=&lng=] → {"items": [{place_id, main, secondary, label}]} — gợi ý khi gõ địa chỉ."""
    from bloodbank.services import geocode as geo

    if _geo_rate_limited(request, 120):
        return JsonResponse(TOO_MANY, status=429)
    lat, lng = _float(request.GET.get("lat")), _float(request.GET.get("lng"))
    return JsonResponse({"items": geo.suggest(request.GET.get("q"), (lat, lng) if lat is not None and lng is not None
                                              else None)})


def geo_place(request):
    """GET ?id=<place_id> → {"lat", "lng", "label", "name"} của gợi ý đã chọn."""
    from bloodbank.services import geocode as geo

    if _geo_rate_limited(request):
        return JsonResponse(TOO_MANY, status=429)
    found = geo.place(request.GET.get("id"))
    if not found:
        return JsonResponse({"error": "Không lấy được vị trí địa điểm."}, status=404)
    return JsonResponse(found)


def geo_reverse(request):
    """GET ?lat=&lng= → {"label", "street"}: bấm ghim trên bản đồ thì gợi ý địa chỉ tương ứng."""
    from bloodbank.services import geocode as geo

    if _geo_rate_limited(request):
        return JsonResponse(TOO_MANY, status=429)
    lat, lng = _float(request.GET.get("lat")), _float(request.GET.get("lng"))
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JsonResponse({"error": "Tọa độ không hợp lệ."}, status=400)
    found = geo.reverse(lat, lng)
    if not found:
        return JsonResponse({"error": "Không tìm được địa chỉ tại điểm này."}, status=404)
    return JsonResponse(found)


def geo_distances(request):
    """GET ?from=lat,lng&to=lat,lng|lat,lng…[&vehicle=] → {"items": [{meters, seconds, distance, duration} | null]}:
    quãng đường đi thật để xếp "Tìm nơi gần tôi" từ gần đến xa. Vị trí người dùng không lưu."""
    from bloodbank.services import geocode as geo

    if _geo_rate_limited(request, 30):
        return JsonResponse(TOO_MANY, status=429)
    pts = []
    for raw in [request.GET.get("from") or ""] + (request.GET.get("to") or "").split("|")[:geo.MAX_DESTINATIONS]:
        parts = raw.split(",")
        lat, lng = (_float(parts[0]), _float(parts[1])) if len(parts) == 2 else (None, None)
        if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return JsonResponse({"error": "Tọa độ không hợp lệ."}, status=400)
        pts.append((lat, lng))
    if len(pts) < 2:
        return JsonResponse({"error": "Thiếu điểm đến."}, status=400)
    items = geo.distances(pts[0], pts[1:], request.GET.get("vehicle") or "car")
    if items is None:
        return JsonResponse({"error": "Không tính được quãng đường."}, status=503)
    return JsonResponse({"items": items})


def geo_route(request):
    """GET ?from=lat,lng&to=lat,lng[&vehicle=car|bike] → quãng đường, thời gian, polyline. Vị trí xuất phát của người
    dùng chỉ dùng cho lượt hỏi này, không lưu."""
    from bloodbank.services import geocode as geo

    if _geo_rate_limited(request, 30):
        return JsonResponse(TOO_MANY, status=429)
    pts = []
    for name in ("from", "to"):
        parts = (request.GET.get(name) or "").split(",")
        lat, lng = (_float(parts[0]), _float(parts[1])) if len(parts) == 2 else (None, None)
        if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return JsonResponse({"error": "Tọa độ không hợp lệ."}, status=400)
        pts.append((lat, lng))
    route = geo.directions(pts[0], pts[1], request.GET.get("vehicle") or "car")
    if not route:
        return JsonResponse({"error": "Không tìm được đường đi."}, status=404)
    return JsonResponse(route)


def map_data(request):
    """MAP-01: chỉ dữ liệu công khai; không lưu vị trí người dùng (khoảng cách "gần tôi" tính trên trình duyệt).

    Đợt hiến kèm thời gian bắt đầu / kết thúc để lọc hôm nay / 7 ngày tới.
    """
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
         "start": c.start_time.isoformat(), "end": c.end_time.isoformat(), "live": c.start_time <= now,
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

