"""Dữ liệu học từ lịch sử kêu gọi THẬT: mỗi lời mời (một người trong một lần kêu gọi) = một dòng.

    đặc trưng = features.compute(..., at = lúc gửi lời kêu gọi)      → chỉ dữ liệu có trước lời mời
    nhãn      = 1 nếu trong `donor_invite_response_days` ngày sau lời mời, người đó đăng ký một đợt hiến của bệnh viện
                đã mời (không tự hủy) hoặc hiến máu tại bệnh viện đó — cùng định nghĩa "hưởng ứng" với
                donor_match.response_stats / callout_responses.

Chỉ lấy lần kêu gọi ĐÃ HẾT thời gian theo dõi (biết chắc kết quả). Chế độ (thiếu kho / khẩn) lấy từ nhật ký kêu gọi.
"""
from datetime import timedelta

from django.utils import timezone

from .features import FEATURES, compute


def window():
    from bloodbank.models import SystemSetting

    return timedelta(days=SystemSetting.get("donor_invite_response_days"))


def recipients(callout_ids):
    """{callout_id: [user_id, ...]} — người nhận lấy từ thông báo trong ứng dụng gắn với lần kêu gọi."""
    from bloodbank.models import Notification

    out = {}
    for uid, cid in (Notification.objects.filter(type="donor_callout", channel="in_app", entity_type="donor_callouts",
                                                 entity_id__in=list(callout_ids))
                     .values_list("user_id", "entity_id")):
        out.setdefault(cid, []).append(uid)
    return out


def responders(callout, users, win=None):
    """Tập người trong `users` đã hưởng ứng lần kêu gọi `callout` (trong cửa sổ theo dõi)."""
    from bloodbank.models import Donation, Registration

    end = callout.created_at + (win or window())
    came = set(Registration.objects.filter(donor_id__in=users, campaign__hospital_id=callout.hospital_id,
                                           registered_at__gte=callout.created_at, registered_at__lt=end)
               .exclude(status=Registration.Status.CANCELLED).values_list("donor_id", flat=True))
    came |= set(Donation.objects.filter(donor_id__in=users, hospital_id=callout.hospital_id,
                                        status=Donation.Status.CONFIRMED,
                                        donated_at__gte=callout.created_at, donated_at__lt=end)
                .values_list("donor_id", flat=True))
    return came


def callout_modes(callout_ids):
    """{callout_id: "stock" | "urgent"} từ nhật ký gửi lời kêu gọi (không có nhật ký → "stock")."""
    from bloodbank.models import AuditLog

    out = {}
    for eid, new in (AuditLog.objects.filter(entity_type="donor_callouts", action="donor_callout",
                                             entity_id__in=list(callout_ids)).values_list("entity_id", "new_values")):
        out[eid] = (new or {}).get("mode") or "stock"
    return out


def closed_callouts(now=None):
    from bloodbank.models import DonorCallout

    now = now or timezone.now()
    return DonorCallout.objects.filter(created_at__lte=now - window()).select_related("hospital").order_by("created_at")


def size(now=None):
    """(số lần kêu gọi đã hết thời gian theo dõi, số lời mời) — đếm nhanh, không tính đặc trưng."""
    from bloodbank.models import Notification

    ids = list(closed_callouts(now).values_list("pk", flat=True))
    n = Notification.objects.filter(type="donor_callout", channel="in_app", entity_type="donor_callouts",
                                    entity_id__in=ids).count() if ids else 0
    return len(ids), n


def dataset(now=None):
    """DataFrame: callout_id, at, hospital_id, mode, <FEATURES>, label, is_synthetic=0."""
    import pandas as pd

    win = window()
    callouts = list(closed_callouts(now))
    who = recipients([c.pk for c in callouts])
    modes = callout_modes([c.pk for c in callouts])
    rows = []
    for c in callouts:
        users = who.get(c.pk) or []
        if not users:
            continue
        mode = modes.get(c.pk, "stock")
        feats = compute(c.hospital, users, c.created_at, mode, c.campaign_id is not None)
        yes = responders(c, users, win)
        for uid in users:
            rows.append({"callout_id": c.pk, "at": c.created_at, "hospital_id": c.hospital_id, "mode": mode,
                         **feats[uid], "label": int(uid in yes), "is_synthetic": 0})
    cols = ["callout_id", "at", "hospital_id", "mode", *FEATURES, "label", "is_synthetic"]
    return pd.DataFrame(rows, columns=cols)
