"""Ghi nhận người hiến: huy hiệu theo mốc số lần hiến được xác nhận + nhắc khi đã đủ thời gian nghỉ.

Không có bảng xếp hạng công khai: so sánh giữa người hiến có thể khuyến khích hiến dày quá mức cho phép.
Huy hiệu tính trực tiếp từ lượt hiến `confirmed` (hủy hiệu lực thì tự mất) — không lưu riêng.
"""
from datetime import timedelta

from django.utils import timezone

from bloodbank.models import Campaign, Donation, Notification, SystemSetting

from .common import notify

# (số lần hiến, tên, icon lucide, lời ghi nhận)
BADGES = [
    (1, "Giọt máu đầu tiên", "droplet", "Cảm ơn bạn đã hiến máu lần đầu."),
    (3, "Người hiến quay lại", "repeat", "Bạn đã quay lại hiến máu 3 lần."),
    (5, "Trái tim bền bỉ", "heart-pulse", "5 lần hiến — một nguồn máu đáng tin cậy."),
    (10, "Mạch máu cộng đồng", "heart-handshake", "10 lần hiến, cộng đồng biết ơn bạn."),
    (20, "Ngọn lửa đỏ", "flame", "20 lần hiến — tấm gương cho mọi người."),
    (30, "Huyền thoại hiến máu", "award", "30 lần hiến máu tình nguyện."),
]


def badges_for(count):
    """Trả về huy hiệu đã đạt, huy hiệu kế tiếp và tiến độ tới mốc kế tiếp."""
    earned = [{"count": n, "name": name, "icon": icon, "text": text} for n, name, icon, text in BADGES if count >= n]
    upcoming = next(((n, name, icon) for n, name, icon, _ in BADGES if count < n), None)
    nxt = None
    if upcoming:
        prev = earned[-1]["count"] if earned else 0
        nxt = {"count": upcoming[0], "name": upcoming[1], "icon": upcoming[2], "remaining": upcoming[0] - count,
               "progress": round(100 * (count - prev) / (upcoming[0] - prev))}
    return {"count": count, "earned": earned, "next": nxt,
            "all": [{"count": n, "name": name, "icon": icon, "earned": count >= n} for n, name, icon, _ in BADGES]}


def _interval_days(donation):
    key = ("donation_interval_component_days" if donation.donation_type == "component"
           else "donation_interval_whole_blood_days")
    return SystemSetting.get(key)


def next_eligible(donor, now=None):
    """Ngày sớm nhất nên hiến lại (theo khuyến nghị khoảng cách) + đợt hiến mở gần nhất từ ngày đó, cùng tỉnh."""
    now = now or timezone.now()
    last = (Donation.objects.filter(donor=donor, status=Donation.Status.CONFIRMED, donated_at__lte=now)
            .order_by("-donated_at").first())
    if last is None:
        return None
    date = timezone.localdate(last.donated_at) + timedelta(days=_interval_days(last))
    campaigns = Campaign.objects.filter(status=Campaign.Status.OPEN, end_time__gt=now).select_related("hospital")
    if donor.province:
        campaigns = campaigns.filter(province=donor.province)
    from_dt = max(now, timezone.make_aware(timezone.datetime.combine(date, timezone.datetime.min.time())))
    campaign = campaigns.filter(end_time__gte=from_dt).order_by("start_time").first()
    return {"date": date, "ready": timezone.localdate(now) >= date, "days_left": max(0, (date - timezone.localdate(now)).days),
            "last": last, "campaign": campaign}


def remind_eligible_again(now=None):
    """Tác vụ định kỳ: nhắc (trong ứng dụng) một lần khi người hiến đã đủ thời gian nghỉ kể từ lượt hiến gần nhất."""
    now = now or timezone.now()
    sent = 0
    whole = SystemSetting.get("donation_interval_whole_blood_days")
    comp = SystemSetting.get("donation_interval_component_days")
    # Lượt hiến gần nhất của từng người đã qua mốc khoảng cách (chỉ xét 60 ngày gần đây để tránh nhắc chuyện cũ)
    window_start = now - timedelta(days=max(whole, comp) + 60)
    latest = {}
    for d in (Donation.objects.filter(status=Donation.Status.CONFIRMED, donated_at__gte=window_start,
                                      donor__status="active", donor__role="member")
              .select_related("donor").order_by("donor_id", "-donated_at")):
        latest.setdefault(d.donor_id, d)
    for d in latest.values():
        if now < d.donated_at + timedelta(days=_interval_days(d)):
            continue
        if Notification.objects.filter(user=d.donor, type="eligible_again", entity_type="donations", entity_id=d.pk).exists():
            continue
        info = next_eligible(d.donor, now)
        where = (f" Đợt gần bạn: \"{info['campaign'].name}\" ({timezone.localtime(info['campaign'].start_time):%d/%m})."
                 if info and info["campaign"] else "")
        notify(d.donor, "eligible_again", "Bạn đã đủ thời gian nghỉ để hiến máu lại",
               f"Lần hiến gần nhất: {timezone.localtime(d.donated_at):%d/%m/%Y}.{where} Bác sĩ sẽ khám sàng lọc trước khi hiến.",
               entity=d)
        sent += 1
    return sent
