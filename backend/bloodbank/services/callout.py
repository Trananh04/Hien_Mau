"""Kêu gọi người hiến khi bệnh viện thiếu một nhóm máu (từ dòng thiếu hụt).

Người nhận — luật cố định: tài khoản Người dùng đang hoạt động, cùng tỉnh/thành với bệnh viện, nhóm máu TỰ KHAI trùng
nhóm đang thiếu (chỉ dùng để gửi lời mời, không phải căn cứ y khoa), không có lượt hiến confirmed trong khoảng cách tối thiểu.
Nhân viên chỉ thấy số lượng, không thấy danh sách người nhận. Mỗi nhóm máu kêu gọi tối đa 1 lần / `donor_callout_cooldown_hours`.
"""
from datetime import timedelta

from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES, User
from bloodbank.models import Campaign, Donation, DonorCallout, SystemSetting

from .common import BusinessError, alert, audit, business_transaction, require


def candidates(hospital, blood_group, now=None):
    now = now or timezone.now()
    recent = now - timedelta(days=SystemSetting.get("donation_interval_whole_blood_days"))
    busy = Donation.objects.filter(status=Donation.Status.CONFIRMED, donated_at__gte=recent).values("donor_id")
    qs = User.objects.filter(role="member", status="active", blood_group=blood_group).exclude(pk__in=busy)
    if hospital.province:
        qs = qs.filter(province=hospital.province)
    return qs


def last_callout(hospital, blood_group):
    return DonorCallout.objects.filter(hospital=hospital, blood_group=blood_group).order_by("-created_at").first()


def next_campaign(hospital, now=None):
    now = now or timezone.now()
    return (Campaign.objects.filter(hospital=hospital, status=Campaign.Status.OPEN, end_time__gt=now)
            .order_by("start_time").first())


def donor_callout(staff, blood_group, request=None):
    require(blood_group in BLOOD_GROUP_VALUES, "ERR-VALIDATION", "Chọn nhóm máu cần kêu gọi.")
    hospital, now = staff.hospital, timezone.now()
    cooldown = timedelta(hours=SystemSetting.get("donor_callout_cooldown_hours"))
    with business_transaction():
        last = last_callout(hospital, blood_group)
        if last and last.created_at > now - cooldown:
            again = timezone.localtime(last.created_at + cooldown)
            raise BusinessError("ERR-STATE-INVALID", f"Đã kêu gọi nhóm {blood_group} lúc "
                                f"{timezone.localtime(last.created_at):%H:%M %d/%m}. Có thể kêu gọi lại sau {again:%H:%M %d/%m}.")
        users = list(candidates(hospital, blood_group, now))
        require(users, "ERR-NOT-FOUND", f"Chưa có người dùng phù hợp (nhóm {blood_group}, cùng khu vực, đủ thời gian nghỉ).")
        campaign = next_campaign(hospital, now)
        callout = DonorCallout.objects.create(hospital=hospital, blood_group=blood_group, campaign=campaign,
                                              created_by=staff.user, recipient_count=len(users))
        if campaign:
            where = (f"Đợt hiến \"{campaign.name}\" bắt đầu {timezone.localtime(campaign.start_time):%H:%M %d/%m} "
                     f"tại {campaign.location_name}. Bấm để đăng ký.")
        else:
            where = f"Liên hệ {hospital.name}{(' — ' + hospital.phone) if hospital.phone else ''} để được hướng dẫn hiến máu."
        alert(users, "donor_callout", f"{hospital.name} đang cần máu nhóm {blood_group}",
              f"Bạn đã đủ thời gian nghỉ giữa 2 lần hiến. {where} Bác sĩ sẽ khám sàng lọc trước khi hiến.", entity=callout)
        audit(staff.user, callout, "donor_callout",
              new={"blood_group": blood_group, "recipients": len(users),
                   "campaign_id": campaign.pk if campaign else None}, hospital=hospital, request=request)
    return len(users), campaign
