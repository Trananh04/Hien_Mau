"""Nhóm 6: hỗ trợ liên viện (`hospital_requests`, `request_offers`)."""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from accounts.models import BLOOD_GROUP_VALUES, BLOOD_GROUPS

from .catalog import ProductSpec
from .hospitals import Hospital

PRIORITIES = [("low", "Thấp"), ("normal", "Bình thường"), ("high", "Cao"), ("urgent", "Khẩn cấp")]


class HospitalRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Đang mở"
        IN_PROGRESS = "in_progress", "Đang xử lý"
        PARTIALLY_FULFILLED = "partially_fulfilled", "Đáp ứng một phần"
        FULFILLED = "fulfilled", "Đã đáp ứng đủ"
        CANCELLED = "cancelled", "Đã hủy"
        EXPIRED = "expired", "Hết hạn"

    FINAL_STATUSES = ("fulfilled", "cancelled", "expired")
    OPEN_STATUSES = ("open", "in_progress", "partially_fulfilled")

    request_code = models.CharField(max_length=30, unique=True)
    requesting_hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="support_requests")
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS)
    product_spec = models.ForeignKey(ProductSpec, on_delete=models.RESTRICT, related_name="support_requests")
    quantity_needed = models.IntegerField()
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="normal")
    needed_by = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    note = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="created_by", related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hospital_requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["blood_group", "product_spec"], name="idx_hrq_key"),
            models.Index(fields=["requesting_hospital", "status"], name="idx_hrq_requester_status"),
            models.Index(fields=["status", "needed_by"], name="idx_hrq_status_needed_by"),
            models.Index(fields=["status", "priority", "needed_by"], name="idx_hrq_status_priority"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(status__in=["fulfilled", "cancelled", "expired"]) | Q(closed_at__isnull=False),
                name="chk_hrq_closed",
            ),
            models.CheckConstraint(condition=Q(quantity_needed__gt=0), name="chk_support_qty"),
            models.CheckConstraint(condition=Q(priority__in=["low", "normal", "high", "urgent"]), name="chk_hrq_priority"),
            models.CheckConstraint(
                condition=Q(
                    status__in=["open", "in_progress", "partially_fulfilled", "fulfilled", "cancelled", "expired"]
                ),
                name="chk_hrq_status",
            ),
            models.CheckConstraint(condition=Q(blood_group__in=BLOOD_GROUP_VALUES), name="chk_hrq_blood_group"),
        ]

    @property
    def is_final(self):
        return self.status in self.FINAL_STATUSES


class RequestOffer(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Chờ phản hồi"
        ACCEPTED = "accepted", "Đã chấp thuận"
        REJECTED = "rejected", "Bị từ chối"
        CANCELLED = "cancelled", "Đã hủy"
        IN_TRANSIT = "in_transit", "Đang vận chuyển"
        COMPLETED = "completed", "Đã nhận"
        FAILED = "failed", "Giao nhận thất bại"

    request = models.ForeignKey(HospitalRequest, on_delete=models.RESTRICT, related_name="offers")
    supplier_hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="supply_offers")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    quantity_requested = models.IntegerField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    quantity_received = models.IntegerField(null=True, blank=True)
    reject_reason = models.CharField(max_length=500, null=True, blank=True)
    failure_reason = models.CharField(max_length=500, null=True, blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="responded_by", null=True, blank=True, related_name="+"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="dispatched_by", null=True, blank=True, related_name="+"
    )
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="received_by", null=True, blank=True, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "request_offers"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["request", "status"], name="idx_offers_request_status"),
            models.Index(fields=["status", "dispatched_at"], name="idx_offers_status_dispatched"),
            models.Index(fields=["supplier_hospital", "status"], name="idx_offers_supplier_status"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["request", "supplier_hospital"], name="uq_offers_request_supplier"),
            models.CheckConstraint(
                condition=~Q(status__in=["accepted", "in_transit", "completed", "failed"]) | Q(quantity__isnull=False),
                name="chk_offer_accepted_qty",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["in_transit", "completed", "failed"]) | Q(dispatched_at__isnull=False),
                name="chk_offer_dispatched",
            ),
            models.CheckConstraint(
                condition=~Q(status="failed") | Q(failure_reason__isnull=False), name="chk_offer_failed"
            ),
            models.CheckConstraint(condition=Q(quantity__isnull=True) | Q(quantity__gt=0), name="chk_offer_qty"),
            models.CheckConstraint(
                condition=Q(quantity_received__isnull=True)
                | Q(quantity_received__gte=0, quantity_received__lte=F("quantity")),
                name="chk_offer_qty_received",
            ),
            models.CheckConstraint(
                condition=Q(quantity_requested__isnull=True) | Q(quantity_requested__gt=0),
                name="chk_offer_qty_requested",
            ),
            models.CheckConstraint(
                condition=~Q(status="completed") | Q(received_at__isnull=False, quantity_received__isnull=False),
                name="chk_offer_received",
            ),
            models.CheckConstraint(
                condition=~Q(status="rejected") | Q(reject_reason__isnull=False), name="chk_offer_reject_reason"
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=["pending", "accepted", "rejected", "cancelled", "in_transit", "completed", "failed"]
                ),
                name="chk_offers_status",
            ),
        ]
