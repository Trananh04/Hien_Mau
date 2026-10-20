"""Nhóm 2: đợt hiến và đơn đăng ký (`campaigns`, `registrations`)."""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .hospitals import LATLNG_PAIR, Hospital

DONATION_TYPES = [("whole_blood", "Toàn phần"), ("component", "Thành phần"), ("other", "Khác")]


class CampaignQuerySet(models.QuerySet):
    def public(self):
        """Đợt hiến hiển thị công khai: đã công bố (mở / ngừng nhận / hoàn tất) của bệnh viện đang hoạt động."""
        return self.filter(status__in=Campaign.PUBLIC_STATUSES, hospital__status="active").select_related("hospital")


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Nháp"
        OPEN = "open", "Đang nhận đăng ký"
        CLOSED = "closed", "Ngừng nhận đăng ký"
        COMPLETED = "completed", "Đã hoàn tất"
        CANCELLED = "cancelled", "Đã hủy"

    PUBLIC_STATUSES = ("open", "closed", "completed")
    RUNNING_STATUSES = ("open", "closed")                  # đang diễn ra / tiếp nhận người hiến
    CHECKIN_STATUSES = ("open", "closed", "completed")     # mở được màn hình điểm hiến

    objects = CampaignQuerySet.as_manager()

    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="campaigns")
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    location_name = models.CharField(max_length=255)
    address = models.CharField(max_length=500)
    province = models.CharField(max_length=100, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    cancel_reason = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "campaigns"
        ordering = ["start_time"]
        indexes = [
            models.Index(fields=["hospital", "start_time"], name="idx_campaigns_hospital_start"),
            models.Index(fields=["province", "start_time"], name="idx_campaigns_province_start"),
            models.Index(fields=["status", "start_time"], name="idx_campaigns_status_start"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="chk_campaign_time"),
            models.CheckConstraint(
                condition=~Q(status="cancelled") | Q(cancel_reason__isnull=False), name="chk_campaign_cancel_reason"
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True) | Q(latitude__gte=-90, latitude__lte=90), name="chk_campaign_lat"
            ),
            models.CheckConstraint(
                condition=Q(longitude__isnull=True) | Q(longitude__gte=-180, longitude__lte=180),
                name="chk_campaign_lng",
            ),
            models.CheckConstraint(condition=LATLNG_PAIR, name="chk_campaign_latlng_pair"),
            models.CheckConstraint(
                condition=Q(status__in=["draft", "open", "closed", "completed", "cancelled"]),
                name="chk_campaign_status",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_editable(self):
        return self.status not in (self.Status.COMPLETED, self.Status.CANCELLED)

    @property
    def checkin_open(self):
        return self.status in self.CHECKIN_STATUSES


class Registration(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Chờ duyệt"
        APPROVED = "approved", "Đã duyệt"
        REJECTED = "rejected", "Bị từ chối"
        CANCELLED = "cancelled", "Đã hủy"
        ATTENDED = "attended", "Đã check-in"
        DONATED = "donated", "Đã hiến"
        NOT_DONATED = "not_donated", "Có mặt, không hiến"
        NO_SHOW = "no_show", "Vắng mặt"

    WAITING_STATUSES = ("pending", "approved")                       # chờ đến điểm hiến; người hiến còn hủy được
    ACTIVE_STATUSES = ("pending", "approved", "attended")            # đơn chưa kết thúc
    DONE_STATUSES = ("donated", "not_donated", "no_show", "rejected")

    class Source(models.TextChoices):
        ONLINE = "online", "Trực tuyến"
        WALK_IN = "walk_in", "Tại điểm hiến"

    campaign = models.ForeignKey(Campaign, on_delete=models.RESTRICT, related_name="registrations")
    donor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="registrations")
    donation_type = models.CharField(max_length=15, choices=DONATION_TYPES, null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ONLINE)
    note = models.TextField(null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "registrations"
        indexes = [
            models.Index(fields=["campaign", "status"], name="idx_reg_campaign_status"),
            models.Index(fields=["donor", "registered_at"], name="idx_registrations_donor_time"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["campaign", "donor"], name="uq_registrations_campaign_donor"),
            models.CheckConstraint(
                condition=Q(donation_type__isnull=True) | Q(donation_type__in=["whole_blood", "component", "other"]),
                name="chk_registrations_type",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "pending", "approved", "rejected", "cancelled", "attended", "donated", "not_donated", "no_show"
                    ]
                ),
                name="chk_registrations_status",
            ),
            models.CheckConstraint(condition=Q(source__in=["online", "walk_in"]), name="chk_registrations_source"),
        ]

    @property
    def code(self):
        return f"DK-{self.id:06d}"

    @property
    def can_cancel(self):
        return self.status in self.WAITING_STATUSES

    def can_reregister(self, now):
        c = self.campaign
        return self.status == self.Status.CANCELLED and c.status == Campaign.Status.OPEN and c.end_time > now
