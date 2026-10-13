"""UC-CMP-01..04, UC-REG-01..06: đợt hiến và đơn đăng ký (máy trạng thái Ch.4 mục 4.3, 4.4)."""
from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts.models import User, normalize_phone
from bloodbank.models import Campaign, Donation, Registration, Staff

from .common import BusinessError, audit, business_transaction, notify, require, snapshot

CAMPAIGN_FIELDS = ["name", "description", "start_time", "end_time", "location_name", "address", "province",
                   "latitude", "longitude"]
R = Registration.Status
C = Campaign.Status


# ---------------------------------------------------------------- Đợt hiến
def _check_campaign_data(data):
    if data["end_time"] <= data["start_time"]:
        raise BusinessError("ERR-CMP-TIME-RANGE", field_errors={"end_time": "Phải sau thời gian bắt đầu."})
    if (data.get("latitude") is None) != (data.get("longitude") is None):
        raise BusinessError("ERR-VALIDATION", "Vĩ độ và kinh độ phải nhập cùng nhau.")


def create_campaign(staff, data, request=None):
    _check_campaign_data(data)
    with business_transaction():
        campaign = Campaign.objects.create(hospital=staff.hospital, status=C.DRAFT, **{k: data.get(k) for k in CAMPAIGN_FIELDS})
        audit(staff.user, campaign, "create", new=snapshot(campaign), hospital=staff.hospital, request=request)
    return campaign


def update_campaign(staff, campaign, data, request=None):
    _check_campaign_data(data)
    with business_transaction():
        campaign = Campaign.objects.select_for_update().get(pk=campaign.pk, hospital=staff.hospital)
        require(campaign.status not in (C.COMPLETED, C.CANCELLED), "ERR-STATE-INVALID")
        old = snapshot(campaign, CAMPAIGN_FIELDS)
        time_or_place_changed = any(
            str(getattr(campaign, k)) != str(data.get(k)) for k in ("start_time", "end_time", "location_name", "address")
        )
        for k in CAMPAIGN_FIELDS:
            setattr(campaign, k, data.get(k))
        campaign.save()
        audit(staff.user, campaign, "update", old=old, new=snapshot(campaign, CAMPAIGN_FIELDS), hospital=staff.hospital,
              request=request)
        if time_or_place_changed and campaign.status in (C.OPEN, C.CLOSED):
            for reg in campaign.registrations.filter(status__in=[R.PENDING, R.APPROVED]).select_related("donor"):
                notify(reg.donor, "campaign_changed", f"Đợt hiến \"{campaign.name}\" thay đổi thời gian/địa điểm",
                       "Vui lòng xem lại thông tin đợt hiến trước khi đến.", entity=campaign)
    return campaign


def campaign_actions(campaign, now=None):
    """Nút hiển thị theo trạng thái (Ch.7 mục 7.7)."""
    now = now or timezone.now()
    s = campaign.status
    has_donation = Donation.objects.filter(registration__campaign=campaign, status="confirmed").exists()
    actions = []
    if s in (C.DRAFT, C.OPEN, C.CLOSED):
        actions.append("edit")
    if s == C.DRAFT and campaign.end_time > now:
        actions.append("publish")
    if s == C.OPEN:
        actions.append("close")
    if s == C.CLOSED and campaign.end_time > now:
        actions.append("reopen")
    if s in (C.OPEN, C.CLOSED) and now >= campaign.end_time:
        actions.append("complete")
    if s == C.DRAFT or (s in (C.OPEN, C.CLOSED) and not has_donation):
        actions.append("cancel")
    return actions


TRANSITIONS = {
    "publish": (C.DRAFT,), "close": (C.OPEN,), "reopen": (C.CLOSED,),
    "complete": (C.OPEN, C.CLOSED), "cancel": (C.DRAFT, C.OPEN, C.CLOSED),
}
TARGET = {"publish": C.OPEN, "close": C.CLOSED, "reopen": C.OPEN, "complete": C.COMPLETED, "cancel": C.CANCELLED}


def transition_campaign(staff, campaign, action, reason=None, request=None):
    require(action in TRANSITIONS, "ERR-STATE-INVALID")
    now = timezone.now()
    with business_transaction():
        campaign = Campaign.objects.select_for_update().get(pk=campaign.pk, hospital=staff.hospital)
        require(campaign.status in TRANSITIONS[action], "ERR-STATE-INVALID")
        if action in ("publish", "reopen"):
            require(campaign.end_time > now, "ERR-STATE-INVALID", "Đợt hiến đã qua thời gian kết thúc.")
        if action == "complete":
            require(now >= campaign.end_time, "ERR-STATE-INVALID", "Chỉ hoàn tất sau thời gian kết thúc.")
        if action == "cancel":
            reason = (reason or "").strip()
            require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do hủy đợt.")
            if Donation.objects.filter(registration__campaign=campaign, status="confirmed").exists():
                raise BusinessError("ERR-CMP-HAS-DONATIONS")
        old_status = campaign.status
        campaign.status = TARGET[action]
        if action == "cancel":
            campaign.cancel_reason = reason[:500]
        campaign.save()
        audit(staff.user, campaign, "status_change", old={"status": old_status},
              new={"status": campaign.status, "reason": reason}, hospital=staff.hospital, request=request)
        if action == "cancel":
            regs = campaign.registrations.filter(status__in=[R.PENDING, R.APPROVED]).select_related("donor")
            for reg in regs:
                reg.status = R.CANCELLED
                reg.save(update_fields=["status", "updated_at"])
                notify(reg.donor, "campaign_cancelled", f"Đợt hiến \"{campaign.name}\" đã bị hủy",
                       f"Lý do: {reason}", entity=campaign)
    return campaign


def campaign_summary(campaign):
    """UC-CMP-04: số liệu tính toán, không lưu."""
    by_status = dict(campaign.registrations.values_list("status").annotate(n=Count("id")))
    don = Donation.objects.filter(registration__campaign=campaign, status="confirmed")
    agg = don.aggregate(
        count=Count("id"),
        whole_count=Count("id", filter=Q(donation_type="whole_blood")),
        whole_ml=Sum("volume_ml", filter=Q(donation_type="whole_blood")),
        component_count=Count("id", filter=Q(donation_type="component")),
    )
    components = list(
        don.filter(donation_type="component")
        .values("component_product__name", "component_unit")
        .annotate(n=Count("id"), qty=Sum("component_quantity"))
        .order_by("component_product__name")
    )
    return {"by_status": by_status, "total": sum(by_status.values()), **agg, "components": components,
            "unprocessed": by_status.get(R.PENDING, 0) + by_status.get(R.APPROVED, 0)}


# ---------------------------------------------------------------- Đơn đăng ký (người hiến)
def register_for_campaign(user, campaign, donation_type=None, note=None, request=None):
    require(user.role == "member", "ERR-AUTH-FORBIDDEN", "Chỉ tài khoản Người dùng mới đăng ký hiến máu được.")
    now = timezone.now()
    with business_transaction():
        campaign = Campaign.objects.select_for_update().get(pk=campaign.pk)
        if campaign.status != C.OPEN:
            raise BusinessError("ERR-REG-CLOSED")
        if now >= campaign.end_time:
            raise BusinessError("ERR-REG-TOO-LATE")
        reg = Registration.objects.select_for_update().filter(campaign=campaign, donor=user).first()
        if reg and reg.status != R.CANCELLED:
            raise BusinessError("ERR-REG-DUPLICATE")
        if reg:  # đăng ký lại tái sử dụng dòng cancelled (BR-27)
            old = snapshot(reg, ["status", "donation_type", "note"])
            reg.status, reg.donation_type, reg.note, reg.source = R.PENDING, donation_type or None, note or None, "online"
            reg.save()
            audit(user, reg, "status_change", old=old, new=snapshot(reg, ["status", "donation_type", "note"]),
                  hospital=campaign.hospital, request=request)
        else:
            reg = Registration.objects.create(campaign=campaign, donor=user, donation_type=donation_type or None,
                                              note=note or None, status=R.PENDING, source="online")
            audit(user, reg, "create", new=snapshot(reg), hospital=campaign.hospital, request=request)
    return reg


def cancel_registration(user, reg, request=None):
    with business_transaction():
        reg = Registration.objects.select_for_update().select_related("campaign").get(pk=reg.pk, donor=user)
        require(reg.status in (R.PENDING, R.APPROVED), "ERR-STATE-INVALID")
        old = reg.status
        reg.status = R.CANCELLED
        reg.save(update_fields=["status", "updated_at"])
        audit(user, reg, "status_change", old={"status": old}, new={"status": reg.status},
              hospital=reg.campaign.hospital, request=request)
    return reg


def registration_view_state(campaign, reg, now=None):
    """Nhãn/nút trên SCR-03: Đăng ký chỉ khi open và chưa có đơn (cancelled → Đăng ký lại)."""
    now = now or timezone.now()
    can_register = campaign.status == C.OPEN and now < campaign.end_time
    if reg is None:
        return {"can_register": can_register, "label": None, "rereg": False}
    if reg.status == R.CANCELLED:
        return {"can_register": can_register, "label": None, "rereg": True}
    return {"can_register": False, "label": reg.get_status_display(), "rereg": False}


# ---------------------------------------------------------------- Đơn đăng ký (bệnh viện)
def _lock_reg(staff, reg_id):
    reg = (
        Registration.objects.select_for_update(of=("self",))
        .select_related("campaign", "donor")
        .filter(pk=reg_id, campaign__hospital=staff.hospital)
        .first()
    )
    if reg is None:
        raise BusinessError("ERR-NOT-FOUND")
    return reg


def staff_registration_action(staff, reg_id, action, reason=None, request=None):
    """approve / reject / checkin / undo_checkin / no_show / not_donated."""
    now = timezone.now()
    reason = (reason or "").strip() or None
    with business_transaction():
        reg = _lock_reg(staff, reg_id)
        camp = reg.campaign
        old = reg.status
        if action in ("approve", "reject"):
            require(reg.status == R.PENDING, "ERR-STATE-INVALID")
            require(camp.status not in (C.CANCELLED, C.COMPLETED), "ERR-STATE-INVALID")
            if action == "reject":
                require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do từ chối.")
            reg.status = R.APPROVED if action == "approve" else R.REJECTED
        elif action == "checkin":
            require(reg.status in (R.PENDING, R.APPROVED), "ERR-STATE-INVALID")
            require(camp.status in (C.OPEN, C.CLOSED), "ERR-STATE-INVALID", "Chỉ check-in khi đợt đang mở hoặc đã ngừng nhận đăng ký.")
            require(now >= camp.start_time, "ERR-STATE-INVALID", "Chưa tới thời gian bắt đầu đợt.")
            reg.status = R.ATTENDED
        elif action == "undo_checkin":
            require(reg.status == R.ATTENDED, "ERR-STATE-INVALID")
            require(not reg.donations.exists(), "ERR-STATE-INVALID", "Đơn đã có lượt hiến, không thể hoàn tác.")
            require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do hoàn tác.")
            reg.status = R.APPROVED
        elif action == "no_show":
            require(reg.status in (R.PENDING, R.APPROVED), "ERR-STATE-INVALID")
            require(now >= camp.start_time, "ERR-STATE-INVALID", "Chỉ đánh dấu vắng sau thời gian bắt đầu.")
            reg.status = R.NO_SHOW
        elif action == "not_donated":
            require(reg.status == R.ATTENDED, "ERR-STATE-INVALID")
            reg.status = R.NOT_DONATED
        else:
            raise BusinessError("ERR-STATE-INVALID")
        if reason:
            reg.note = ((reg.note + "\n") if reg.note else "") + f"[{timezone.localtime(now):%d/%m %H:%M}] {reason}"
        reg.save()
        audit(staff.user, reg, "status_change", old={"status": old}, new={"status": reg.status, "reason": reason},
              hospital=staff.hospital, request=request)
        if action in ("approve", "reject"):
            title = (f"Đơn đăng ký đợt \"{camp.name}\" đã được duyệt" if action == "approve"
                     else f"Đơn đăng ký đợt \"{camp.name}\" không được duyệt")
            notify(reg.donor, f"registration_{reg.status}", title, reason, entity=reg)
    return reg


def find_donor(query):
    """Tìm tài khoản theo email hoặc SĐT (để tạo đơn tại điểm hiến)."""
    q = (query or "").strip()
    if not q:
        return None
    if "@" in q:
        return User.objects.filter(email=q.lower(), status="active", role="member").first()
    return User.objects.filter(phone=normalize_phone(q), status="active", role="member").first()


def walk_in(staff, campaign, donor, donation_type=None, reason=None, request=None):
    """UC-DON-04: ghi nhận tại chỗ — tạo/tái dùng đơn và check-in ngay."""
    now = timezone.now()
    with business_transaction():
        campaign = Campaign.objects.select_for_update().get(pk=campaign.pk, hospital=staff.hospital)
        require(campaign.status in (C.OPEN, C.CLOSED), "ERR-STATE-INVALID", "Đợt không ở trạng thái tiếp nhận.")
        require(now >= campaign.start_time, "ERR-STATE-INVALID", "Chưa tới thời gian bắt đầu đợt.")
        require(donor.pk != staff.user_id, "ERR-DON-SELF-CONFIRM")
        reg = Registration.objects.select_for_update().filter(campaign=campaign, donor=donor).first()
        if reg is None:
            reg = Registration.objects.create(campaign=campaign, donor=donor, status=R.ATTENDED, source="walk_in",
                                              donation_type=donation_type or None)
            audit(staff.user, reg, "create", new=snapshot(reg), hospital=staff.hospital, request=request)
            return reg
        old = reg.status
        if reg.status in (R.PENDING, R.APPROVED, R.CANCELLED):
            reg.status = R.ATTENDED
        elif reg.status in (R.REJECTED, R.NO_SHOW, R.NOT_DONATED):
            # E2: bắt buộc có lý do
            require((reason or "").strip(), "ERR-DON-REASON-REQUIRED")
            reg.status = R.ATTENDED
        elif reg.status == R.ATTENDED:
            return reg
        else:
            raise BusinessError("ERR-DON-DUPLICATE")
        reg.save()
        audit(staff.user, reg, "status_change", old={"status": old}, new={"status": reg.status, "reason": reason},
              hospital=staff.hospital, request=request)
    return reg
