"""Gợi ý người hiến phù hợp cho một nhóm máu đang thiếu — luật cố định + điểm minh bạch, không dùng mô hình học máy.

Cách làm học theo BloodNet (lọc nhóm máu + bán kính → xếp theo khoảng cách) nhưng không cần bảng / cột mới:
vị trí gần đúng của người hiến = địa điểm đợt hiến gần nhất họ đã có mặt (đợt hiến có tọa độ).

1) Lọc cứng (không đạt → loại):
   - tài khoản Người dùng đang hoạt động, cùng tỉnh/thành với bệnh viện;
   - nhóm máu khớp: ưu tiên nhóm đã xét nghiệm (`donations.lab_blood_group`), chưa có thì dùng nhóm tự khai;
   - trong độ tuổi hiến (nếu có ngày sinh);
   - đủ thời gian nghỉ THEO LOẠI của lần hiến gần nhất (toàn phần / thành phần);
   - không nhận lời kêu gọi nào trong `donor_invite_cooldown_days` ngày (khẩn: `donor_invite_urgent_cooldown_days`),
     tính trên mọi bệnh viện;
   - chia đều lượt gọi: đã nhận `donor_invite_max_90_days` lời kêu gọi trong 90 ngày (mọi bệnh viện) → tạm không gợi ý;
   - nếu chọn bán kính: chỉ người có vị trí gần đúng nằm trong bán kính.
2) Điểm phù hợp 0–100 kèm lý do, để nhân viên hiểu vì sao người đó được gợi ý:
   - khoảng cách là QUÃNG ĐƯỜNG ĐI THẬT từ bệnh viện (Goong Distance Matrix, lưu cache vì điểm đến là địa điểm đợt
     hiến công khai); dịch vụ lỗi / chưa cấu hình → đường chim bay;
   - ưu tiên người TỪNG NHẬN LỜI KÊU GỌI (tỷ lệ hưởng ứng của chính người đó), không phải số lần hiến;
   - người ít bị kêu gọi gần đây được cộng điểm và xếp trước khi bằng điểm → lượt gọi chia đều.

Bảo mật: nhân viên chỉ thấy MÃ ẩn danh + đặc điểm, không thấy tên / liên hệ. Mã là HMAC theo bệnh viện; khi gửi, máy chủ
tính lại danh sách và chỉ chấp nhận mã nằm trong đó. Hàm `suggest` chỉ đọc — mở trang không ghi gì vào CSDL.
"""
import hashlib
import hmac
import math
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES, User
from django.core.cache import cache

from bloodbank.models import Donation, DonorCallout, Notification, Registration, SystemSetting

# Hai chế độ (tổng trọng số mỗi chế độ = 100):
# - "stock" (thiếu kho, vài ngày–vài tuần): mời người hiến tin cậy trong cả tỉnh tới đợt hiến;
# - "urgent" (khẩn, vài giờ): người GẦN quan trọng nhất, bán kính mặc định nhỏ, thời gian chờ giữa 2 lời mời ngắn hơn.
# Thời gian nghỉ giữa 2 lần hiến và độ tuổi KHÔNG BAO GIỜ được nới ở bất kỳ chế độ nào.
MODES = {
    "stock": {"near": 20, "verified": 15, "experience": 10, "reliable": 15, "responsive": 15, "local": 10, "rested": 15,
              "near_full_km": 50, "default_radius": None, "rate_factor": 1.0,
              "cooldown_setting": "donor_invite_cooldown_days"},
    "urgent": {"near": 40, "verified": 15, "experience": 5, "reliable": 10, "responsive": 15, "local": 5, "rested": 10,
               "near_full_km": 25, "default_radius": 10, "rate_factor": 0.5,
               "cooldown_setting": "donor_invite_urgent_cooldown_days"},
}
RADIUS_CHOICES = (10, 25, 50)
MAX_SEND = 50                # số người tối đa trong một lần gửi
DEFAULT_RESPONSE_RATE = 0.3  # tỷ lệ hưởng ứng giả định khi bệnh viện chưa có lần kêu gọi nào đã hết hạn theo dõi
CAME = ("attended", "donated", "not_donated")


def donor_code(hospital, user_id):
    digest = hmac.new(settings.SECRET_KEY.encode(), f"donor:{hospital.pk}:{user_id}".encode(), hashlib.sha256).digest()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    n = int.from_bytes(digest[:5], "big")
    return "".join(alphabet[(n >> (5 * i)) & 31] for i in range(6))


def _km(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = (math.radians(float(v)) for v in (lat1, lng1, lat2, lng2))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


def _age(dob, today):
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def radius_or_none(value, hospital):
    """Bán kính hợp lệ (km) — chỉ khi bệnh viện có tọa độ; còn lại None = cả tỉnh/thành."""
    try:
        r = int(value)
    except (TypeError, ValueError):
        return None
    return r if r in RADIUS_CHOICES and hospital.latitude is not None else None


def _latest(qs, field):
    """{donor_id: giá trị của bản ghi mới nhất} — qs đã sắp theo donor_id, mới → cũ."""
    out = {}
    for row in qs:
        out.setdefault(row["donor_id"], row[field])
    return out


ROAD_TTL = 30 * 24 * 3600


def road_km(hospital, points):
    """{(lat, lng): km đường đi từ bệnh viện} cho các điểm (địa điểm đợt hiến). Điểm không tra được → không có trong kết quả.

    Điểm đến là địa điểm đợt hiến công khai (không phải địa chỉ người hiến) nên lưu cache dài được."""
    from bloodbank.services import geocode as geo

    if hospital.latitude is None or not points or not settings.GOONG_API_KEY:
        return {}
    origin = (float(hospital.latitude), float(hospital.longitude))

    def key(pt):
        return f"road-km:{origin[0]:.5f},{origin[1]:.5f}:{pt[0]:.5f},{pt[1]:.5f}"

    pts = list(dict.fromkeys((float(la), float(ln)) for la, ln in points))
    out, missing = {}, []
    for pt in pts:
        hit = cache.get(key(pt))
        if hit is not None:
            out[pt] = hit
        else:
            missing.append(pt)
    for i in range(0, len(missing), geo.MAX_DESTINATIONS):
        chunk = missing[i:i + geo.MAX_DESTINATIONS]
        res = geo.distances(origin, chunk)
        if res is None:
            break                                    # dịch vụ lỗi → các điểm còn lại dùng đường chim bay
        for pt, r in zip(chunk, res):
            if r:
                out[pt] = round(r["meters"] / 1000, 1)
                cache.set(key(pt), out[pt], ROAD_TTL)
    return out


def callout_responses(ids, now):
    """{user_id: (số lời kêu gọi đã hết thời gian theo dõi, số lần hưởng ứng)} trong 365 ngày, mọi bệnh viện.

    Hưởng ứng = trong `donor_invite_response_days` ngày sau lời mời, người đó đăng ký đợt hiến (không tự hủy) hoặc hiến
    máu tại chính bệnh viện đã mời (cùng định nghĩa với `response_stats`)."""
    window = timedelta(days=SystemSetting.get("donor_invite_response_days"))
    since = now - timedelta(days=365)
    invites = list(Notification.objects.filter(type="donor_callout", channel="in_app", entity_type="donor_callouts",
                                               user_id__in=ids, created_at__gte=since, created_at__lte=now - window)
                   .values_list("user_id", "entity_id", "created_at"))
    if not invites:
        return {}
    hosp = dict(DonorCallout.objects.filter(pk__in={e for _, e, _ in invites}).values_list("pk", "hospital_id"))
    users = {u for u, _, _ in invites}
    acts = {}
    for uid, h, at in (Registration.objects.filter(donor_id__in=users, registered_at__gte=since)
                       .exclude(status=Registration.Status.CANCELLED)
                       .values_list("donor_id", "campaign__hospital_id", "registered_at")):
        acts.setdefault((uid, h), []).append(at)
    for uid, h, at in (Donation.objects.filter(donor_id__in=users, status=Donation.Status.CONFIRMED, donated_at__gte=since)
                       .values_list("donor_id", "hospital_id", "donated_at")):
        acts.setdefault((uid, h), []).append(at)
    out = {}
    for uid, callout_id, at in invites:
        h = hosp.get(callout_id)
        hit = any(at <= t < at + window for t in acts.get((uid, h), []))
        sent, came = out.get(uid, (0, 0))
        out[uid] = (sent + 1, came + (1 if hit else 0))
    return out


def mode_of(value):
    return "urgent" if value == "urgent" else "stock"


def suggest(hospital, blood_group, radius_km=None, now=None, mode="stock"):
    """Ứng viên đã xếp hạng (cao → thấp). Mỗi dòng: user_id, code, score, level, reasons, distance_km, ..."""
    if blood_group not in BLOOD_GROUP_VALUES:
        return []
    m = MODES[mode_of(mode)]
    now = now or timezone.now()
    today = timezone.localdate(now) if timezone.is_aware(now) else date.today()
    intervals = {"whole_blood": SystemSetting.get("donation_interval_whole_blood_days"),
                 "component": SystemSetting.get("donation_interval_component_days")}
    min_age, max_age = SystemSetting.get("donor_min_age"), SystemSetting.get("donor_max_age")
    confirmed = Donation.objects.filter(status=Donation.Status.CONFIRMED)

    base = User.objects.filter(role="member", status="active")
    if hospital.province:
        base = base.filter(province=hospital.province)
    lab = _latest(confirmed.filter(donor__in=base, lab_blood_group__isnull=False)
                  .order_by("donor_id", "-donated_at").values("donor_id", "lab_blood_group"), "lab_blood_group")
    lab_match = [uid for uid, bg in lab.items() if bg == blood_group]
    people = {u["id"]: u for u in base.filter(Q(pk__in=lab_match) | (Q(blood_group=blood_group) & ~Q(pk__in=list(lab))))
              .values("id", "date_of_birth")}
    ids = list(people)
    if not ids:
        return []

    max_90d = max(1, int(SystemSetting.get("donor_invite_max_90_days")))
    since_invite = now - timedelta(days=SystemSetting.get(m["cooldown_setting"]))
    invites = Notification.objects.filter(type="donor_callout", channel="in_app", user_id__in=ids)
    invited = set(invites.filter(created_at__gte=since_invite).values_list("user_id", flat=True))
    invites_90d = dict(invites.filter(created_at__gte=now - timedelta(days=90))
                       .values_list("user_id").annotate(n=Count("id")).values_list("user_id", "n"))
    stats = {r["donor_id"]: r for r in confirmed.filter(donor_id__in=ids).values("donor_id")
             .annotate(n=Count("id"), last=Max("donated_at"), here=Count("id", filter=Q(hospital=hospital)))}
    last_type = _latest(confirmed.filter(donor_id__in=ids).order_by("donor_id", "-donated_at")
                        .values("donor_id", "donation_type"), "donation_type")
    regs = {r["donor_id"]: r for r in Registration.objects.filter(donor_id__in=ids).values("donor_id").annotate(
        came=Count("id", filter=Q(status__in=CAME)), missed=Count("id", filter=Q(status="no_show")))}
    # Vị trí gần đúng: đợt hiến gần nhất người đó đã có mặt (có tọa độ)
    spots = {}
    if hospital.latitude is not None:
        for r in (Registration.objects.filter(donor_id__in=ids, status__in=CAME, campaign__latitude__isnull=False)
                  .order_by("donor_id", "-campaign__start_time")
                  .values("donor_id", "campaign__latitude", "campaign__longitude")):
            spots.setdefault(r["donor_id"], (r["campaign__latitude"], r["campaign__longitude"]))
    roads = road_km(hospital, spots.values())
    answered = callout_responses(ids, now)

    rows = []
    for uid in ids:
        dob = people[uid]["date_of_birth"]
        recent = invites_90d.get(uid, 0)
        if uid in invited or recent >= max_90d or (dob and not min_age <= _age(dob, today) <= max_age):
            continue
        s = stats.get(uid)
        days_since = (now - s["last"]).days if s else None
        need = intervals.get(last_type.get(uid), intervals["whole_blood"])
        if days_since is not None and days_since < need:
            continue                                     # chưa đủ thời gian nghỉ theo loại lần hiến gần nhất
        spot = spots.get(uid)
        road = roads.get((float(spot[0]), float(spot[1]))) if spot else None
        dist = road if road is not None else (_km(hospital.latitude, hospital.longitude, *spot) if spot else None)
        if radius_km and (dist is None or dist > radius_km):
            continue

        n = s["n"] if s else 0
        r = regs.get(uid, {"came": 0, "missed": 0})
        seen = r["came"] + r["missed"]
        show_rate = r["came"] / seen if seen else None
        verified = uid in lab
        asked, came_back = answered.get(uid, (0, 0))

        # Lý do hiện cạnh mỗi người — chỉ nhân viên bệnh viện thấy (không kèm tên / liên hệ)
        reasons = [f"Đúng nhóm {blood_group} ({'đã xét nghiệm' if verified else 'tự khai'})"]
        if dist is not None:
            km = f"{dist:g}".replace(".", ",")
            reasons.append(f"cách {km} km đường đi" if road is not None else f"cách khoảng {km} km (đường chim bay)")
        reasons.append(f"đã nghỉ đủ {days_since} ngày" if days_since is not None else "chưa hiến lần nào")
        if asked:
            reasons.append(f"nhận lời {came_back}/{asked} lần kêu gọi")
        if seen >= 2:
            reasons.append(f"đến {r['came']}/{seen} lần hẹn")
        if s and s["here"]:
            reasons.append("từng hiến tại bệnh viện này")
        reasons.append(f"được gọi {recent} lần trong 90 ngày" if recent else "chưa được gọi trong 90 ngày")
        # Điểm từng tiêu chí (nhãn, điểm đạt, tối đa) — hiện cho nhân viên xem vì sao người này được xếp hạng
        parts = [
            # chưa rõ vị trí nhưng cùng tỉnh/thành → 30%
            ("Gần bệnh viện (đường đi)" if road is not None else "Gần bệnh viện",
             m["near"] * (max(0.0, 1 - dist / m["near_full_km"]) if dist is not None else 0.3), m["near"]),
            # chưa từng được kêu gọi → trung lập
            ("Từng nhận lời kêu gọi", m["responsive"] * (came_back / asked if asked else 0.5), m["responsive"]),
            ("Đến đúng hẹn", m["reliable"] * (0.5 if show_rate is None else show_rate), m["reliable"]),
            ("Kinh nghiệm hiến", m["experience"] * min(n, 5) / 5, m["experience"]),
            ("Nhóm máu đã xét nghiệm", m["verified"] if verified else 0, m["verified"]),
            # chia đều lượt gọi: càng ít bị gọi trong 90 ngày càng được ưu tiên
            ("Ít bị kêu gọi gần đây", m["rested"] * max(0.0, 1 - recent / max_90d), m["rested"]),
            ("Từng hiến tại bệnh viện này", m["local"] if s and s["here"] else 0, m["local"]),
        ]
        score = round(sum(p[1] for p in parts))
        rows.append({
            "user_id": uid, "code": donor_code(hospital, uid), "score": score,
            "level": "high" if score >= 70 else "medium" if score >= 45 else "low",
            "reasons": reasons, "verified": verified, "donations": n, "days_since": days_since,
            "distance_km": dist, "road": road is not None, "first_time": n == 0, "recent_invites": recent,
            "asked": asked, "answered": came_back,
            "parts": [{"label": label, "points": round(got), "max": top} for label, got, top in parts],
        })
    # Bằng điểm: người ít bị gọi gần đây trước (chia đều lượt gọi), rồi người gần hơn
    rows.sort(key=lambda x: (-x["score"], x["recent_invites"],
                             x["distance_km"] if x["distance_km"] is not None else 1e9, x["code"]))
    return rows


def response_stats(hospital, now=None):
    """Hiệu quả kêu gọi của bệnh viện — không cần bảng mới.

    Người được mời (thông báo `donor_callout` gắn với lần kêu gọi) tính là ĐÃ HƯỞNG ỨNG nếu trong
    `donor_invite_response_days` ngày sau lời mời họ đăng ký một đợt hiến của bệnh viện (trừ đơn đã tự hủy) hoặc có lượt
    hiến tại bệnh viện. Tỷ lệ chỉ tính trên các lần kêu gọi đã hết thời gian theo dõi.
    """
    now = now or timezone.now()
    window = timedelta(days=SystemSetting.get("donor_invite_response_days"))
    callouts = list(DonorCallout.objects.filter(hospital=hospital, created_at__gte=now - timedelta(days=180))
                    .order_by("-created_at")[:30])
    sent_done = responded_done = 0
    last = None
    for c in callouts:
        users = set(Notification.objects.filter(type="donor_callout", channel="in_app", entity_type="donor_callouts",
                                                entity_id=c.pk).values_list("user_id", flat=True))
        end = c.created_at + window
        came = set(Registration.objects.filter(donor_id__in=users, campaign__hospital=hospital,
                                               registered_at__gte=c.created_at, registered_at__lt=end)
                   .exclude(status=Registration.Status.CANCELLED).values_list("donor_id", flat=True))
        came |= set(Donation.objects.filter(donor_id__in=users, hospital=hospital, status=Donation.Status.CONFIRMED,
                                            donated_at__gte=c.created_at, donated_at__lt=end)
                    .values_list("donor_id", flat=True))
        done = end <= now
        if last is None:
            last = {"callout": c, "sent": len(users), "responded": len(came), "done": done, "until": end}
        if done:
            sent_done += len(users)
            responded_done += len(came)
    return {"last": last, "sent": sent_done, "responded": responded_done,
            "rate": responded_done / sent_done if sent_done else None}


def suggested_count(shortage, rate=None, mode="stock"):
    """Số người nên mời để bù `shortage` đơn vị: ⌈thiếu ÷ tỷ lệ hưởng ứng⌉, trong khoảng 1..MAX_SEND.

    Kêu gọi khẩn chỉ có vài giờ nên ít người kịp đến: tỷ lệ dùng để tính giảm một nửa → mời nhiều người hơn.
    """
    if not shortage or shortage <= 0:
        return 0
    rate = (rate if rate and rate > 0 else DEFAULT_RESPONSE_RATE) * MODES[mode_of(mode)]["rate_factor"]
    return max(1, min(MAX_SEND, math.ceil(shortage / rate)))
