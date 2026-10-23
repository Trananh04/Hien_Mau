"""Kêu gọi người hiến khi bệnh viện thiếu một nhóm máu (từ dòng thiếu hụt).

Người nhận do nhân viên CHỌN trên màn "Gợi ý người hiến" (xếp hạng ở `donor_match.suggest`). Nhân viên chỉ thấy mã ẩn
danh, không thấy tên / liên hệ. Khi gửi, máy chủ khóa các tài khoản liên quan, tính lại danh sách gợi ý và chỉ gửi tới
mã còn nằm trong đó — nên không thể gửi tới người không đủ điều kiện hay vừa được bệnh viện khác kêu gọi. Chống làm
phiền theo từng người: mỗi người tối đa 1 lời kêu gọi / `donor_invite_cooldown_days` ngày (mọi bệnh viện); kêu gọi
KHẨN dùng `donor_invite_urgent_cooldown_days` và mời đến thẳng bệnh viện trong ngày thay vì đợt hiến.
"""
from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES, User
from bloodbank.models import Campaign, DonorCallout

from . import donor_match
from .common import alert, audit, business_transaction, require


def last_callout(hospital, blood_group):
    return DonorCallout.objects.filter(hospital=hospital, blood_group=blood_group).order_by("-created_at").first()


def next_campaign(hospital, now=None):
    now = now or timezone.now()
    return (Campaign.objects.filter(hospital=hospital, status=Campaign.Status.OPEN, end_time__gt=now)
            .order_by("start_time").first())


def default_radius(hospital, mode):
    """Bán kính mặc định của chế độ (khẩn: 10 km) — chỉ khi bệnh viện có tọa độ."""
    return donor_match.radius_or_none(donor_match.MODES[donor_match.mode_of(mode)]["default_radius"], hospital)


def with_callout_info(hospital, rows):
    """Gắn số người phù hợp (theo chế độ của dòng: khẩn / thiếu kho) và lần kêu gọi gần nhất cho mỗi dòng thiếu."""
    seen = {}
    for r in rows:
        mode = "urgent" if r.get("urgent") else "stock"
        key = (r["blood_group"], mode)
        if r["shortage"] and key not in seen:
            seen[key] = (len(donor_match.suggest(hospital, r["blood_group"], default_radius(hospital, mode), mode=mode)),
                         last_callout(hospital, r["blood_group"]))
        r["mode"] = mode
        r["callout_count"], r["last_callout"] = seen.get(key, (0, None))
    return rows


def donor_callout(staff, blood_group, codes, radius_km=None, request=None, mode="stock"):
    """Gửi lời kêu gọi tới các mã đã chọn. Trả về (số người nhận, đợt hiến kèm theo, số mã bị bỏ qua)."""
    require(blood_group in BLOOD_GROUP_VALUES, "ERR-VALIDATION", "Chọn nhóm máu cần kêu gọi.")
    codes = list(dict.fromkeys(c for c in (codes or []) if c))
    require(codes, "ERR-VALIDATION", "Chọn ít nhất một người hiến để gửi lời mời.")
    require(len(codes) <= donor_match.MAX_SEND, "ERR-VALIDATION",
            f"Mỗi lần gửi tối đa {donor_match.MAX_SEND} người. Bỏ bớt lựa chọn rồi gửi lại.")
    mode = donor_match.mode_of(mode)
    hospital, now = staff.hospital, timezone.now()
    with business_transaction():
        first = {r["code"]: r["user_id"] for r in donor_match.suggest(hospital, blood_group, radius_km, now, mode)}
        # Khóa tài khoản được chọn để hai nhân viên (hoặc hai bệnh viện) gửi cùng lúc không mời trùng người
        list(User.objects.select_for_update().filter(pk__in=[first[c] for c in codes if c in first]).order_by("pk"))
        pool = {r["code"]: r["user_id"] for r in donor_match.suggest(hospital, blood_group, radius_km, now, mode)}
        ids = [pool[c] for c in codes if c in pool]
        require(ids, "ERR-STATE-INVALID",
                "Những người đã chọn không còn đủ điều kiện (vừa được kêu gọi hoặc vừa hiến máu). Tải lại danh sách gợi ý.")
        users = list(User.objects.filter(pk__in=ids))
        # Khẩn: mời đến thẳng bệnh viện hôm nay (không chờ đợt hiến); thiếu kho: kèm đợt hiến sắp tới nếu có
        campaign = None if mode == "urgent" else next_campaign(hospital, now)
        callout = DonorCallout.objects.create(hospital=hospital, blood_group=blood_group, campaign=campaign,
                                              created_by=staff.user, recipient_count=len(users))
        contact = f"{hospital.name}{(' (' + hospital.phone + ')') if hospital.phone else ''}"
        if mode == "urgent":
            title = f"[Khẩn] {hospital.name} cần máu nhóm {blood_group} ngay hôm nay"
            where = (f"Nếu có thể, mời bạn đến hiến máu trong hôm nay tại {hospital.name}"
                     f"{(', ' + hospital.address) if hospital.address else ''}. Gọi trước {contact} để được đón tiếp.")
        elif campaign:
            where = (f"Đợt hiến \"{campaign.name}\" bắt đầu {timezone.localtime(campaign.start_time):%H:%M %d/%m} "
                     f"tại {campaign.location_name}. Bấm để đăng ký.")
        else:
            where = f"Liên hệ {contact} để được hướng dẫn hiến máu."
        if mode != "urgent":
            title = f"{hospital.name} đang cần máu nhóm {blood_group}"
        alert(users, "donor_callout", title,
              f"Bạn đã đủ thời gian nghỉ giữa 2 lần hiến. {where} Bác sĩ sẽ khám sàng lọc trước khi hiến.", entity=callout)
        audit(staff.user, callout, "donor_callout",
              new={"blood_group": blood_group, "mode": mode, "recipients": len(users), "codes": [c for c in codes if c in pool],
                   "campaign_id": campaign.pk if campaign else None}, hospital=hospital, request=request)
    return len(users), campaign, len(codes) - len(users)
