"""Đặc trưng của một lời mời (người hiến u, bệnh viện h, thời điểm gửi `at`) — CHỈ dùng dữ liệu có trước `at`.

Một hàm duy nhất cho dữ liệu học (mỗi lời mời trong quá khứ, at = lúc gửi) và lúc gợi ý (at = bây giờ) → mô hình học và
dùng cùng một định nghĩa. Không dùng tuổi, giới tính, nhóm máu làm đặc trưng: chỉ hành vi hiến / hưởng ứng, khoảng cách
và hoàn cảnh lời mời — tránh để mô hình ưu tiên hay loại người theo đặc điểm cá nhân.

Giá trị None = chưa có thông tin (chưa rõ vị trí, chưa hiến lần nào, chưa từng được mời...): XGBoost tự xử lý, hồi quy
logistic điền trung vị và thêm cột "thiếu thông tin" (model.LogReg).
"""
from datetime import timedelta

FEATURES = ["dist_km", "days_since", "n_donations", "verified", "here", "show_rate", "appointments", "asked",
            "resp_rate", "recent_90d", "urgent", "has_campaign", "weekend", "hour"]

# Đặc trưng của HOÀN CẢNH lời mời — giống nhau với mọi người trong cùng một danh sách, nên không dùng để giải thích
# vì sao người này đứng trên người kia
CONTEXT = {"urgent", "has_campaign", "weekend", "hour"}

LABELS = {
    "dist_km": "Khoảng cách tới bệnh viện (km, đường chim bay từ nơi hiến gần nhất)",
    "days_since": "Số ngày từ lần hiến gần nhất",
    "n_donations": "Số lần đã hiến",
    "verified": "Nhóm máu đã xét nghiệm",
    "here": "Từng hiến tại bệnh viện này",
    "show_rate": "Tỷ lệ đến đúng hẹn khi đã đăng ký",
    "appointments": "Số lần hẹn trước đây (đến hoặc vắng)",
    "asked": "Số lời kêu gọi trước đây (đã hết thời gian theo dõi)",
    "resp_rate": "Tỷ lệ nhận lời kêu gọi trước đây",
    "recent_90d": "Số lời kêu gọi đã nhận trong 90 ngày",
    "urgent": "Kêu gọi khẩn",
    "has_campaign": "Có đợt hiến kèm theo lời mời",
    "weekend": "Gửi vào thứ 6 – chủ nhật",
    "hour": "Giờ gửi",
}


def _pct(v):
    return f"{round(100 * v)}%"


def describe(name, value):
    """Câu ngắn cho nhân viên: "Khoảng cách: 3,2 km"."""
    short = {"dist_km": "Khoảng cách", "days_since": "Nghỉ từ lần hiến trước", "n_donations": "Đã hiến",
             "verified": "Nhóm máu đã xét nghiệm", "here": "Từng hiến tại bệnh viện này", "show_rate": "Đến đúng hẹn",
             "appointments": "Số lần hẹn", "asked": "Lời kêu gọi trước đây", "resp_rate": "Nhận lời trước đây",
             "recent_90d": "Bị gọi trong 90 ngày"}[name]
    if value is None or value != value:            # None / NaN
        missing = {"dist_km": "chưa rõ vị trí", "days_since": "chưa hiến lần nào", "show_rate": "chưa có lịch hẹn",
                   "resp_rate": "chưa từng được mời"}
        return f"{short}: {missing.get(name, 'chưa có')}"
    if name == "dist_km":
        return f"{short}: {value:.1f} km".replace(".", ",")
    if name == "days_since":
        return f"{short}: {value:.0f} ngày"
    if name in ("verified", "here"):
        return f"{short}: {'có' if value else 'chưa'}"
    if name in ("show_rate", "resp_rate"):
        return f"{short}: {_pct(value)}"
    return f"{short}: {value:.0f} lần"


def compute(hospital, ids, at, mode, has_campaign):
    """{user_id: {đặc trưng: giá trị}} tại thời điểm `at` (aware datetime)."""
    from django.db.models import Count, Max, Q
    from django.utils import timezone

    from bloodbank.models import Donation, Notification, Registration
    from bloodbank.services import donor_match as dm

    ids = list(ids)
    if not ids:
        return {}
    confirmed = Donation.objects.filter(status=Donation.Status.CONFIRMED, donor_id__in=ids, donated_at__lt=at)
    stats = {r["donor_id"]: r for r in confirmed.values("donor_id").annotate(
        n=Count("id"), last=Max("donated_at"), here=Count("id", filter=Q(hospital=hospital)))}
    verified = set(confirmed.filter(lab_blood_group__isnull=False, lab_checked_at__lt=at)
                   .values_list("donor_id", flat=True))
    past = Registration.objects.filter(donor_id__in=ids, campaign__start_time__lt=at)
    regs = {r["donor_id"]: r for r in past.values("donor_id").annotate(
        came=Count("id", filter=Q(status__in=dm.CAME)), missed=Count("id", filter=Q(status="no_show")))}
    spots = {}
    if hospital.latitude is not None:
        for r in (past.filter(status__in=dm.CAME, campaign__latitude__isnull=False)
                  .order_by("donor_id", "-campaign__start_time")
                  .values("donor_id", "campaign__latitude", "campaign__longitude")):
            spots.setdefault(r["donor_id"], (r["campaign__latitude"], r["campaign__longitude"]))
    invites_90d = dict(Notification.objects.filter(type="donor_callout", channel="in_app", user_id__in=ids,
                                                   created_at__gte=at - timedelta(days=90), created_at__lt=at)
                       .values_list("user_id").annotate(n=Count("id")).values_list("user_id", "n"))
    answered = dm.callout_responses(ids, at)
    local = timezone.localtime(at)
    context = {"urgent": int(mode == "urgent"), "has_campaign": int(bool(has_campaign)),
               "weekend": int(local.weekday() >= 4), "hour": local.hour}
    out = {}
    for uid in ids:
        s = stats.get(uid)
        r = regs.get(uid, {"came": 0, "missed": 0})
        seen = r["came"] + r["missed"]
        asked, came_back = answered.get(uid, (0, 0))
        spot = spots.get(uid)
        out[uid] = {
            "dist_km": dm._km(hospital.latitude, hospital.longitude, *spot) if spot else None,
            "days_since": (at - s["last"]).days if s else None,
            "n_donations": s["n"] if s else 0,
            "verified": int(uid in verified),
            "here": int(bool(s and s["here"])),
            "show_rate": r["came"] / seen if seen else None,
            "appointments": seen,
            "asked": asked,
            "resp_rate": came_back / asked if asked else None,
            "recent_90d": invites_90d.get(uid, 0),
            **context,
        }
    return out
