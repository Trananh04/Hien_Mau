"""Nhóm 7: người cần máu (`patient_requests`)."""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from accounts.models import BLOOD_GROUP_VALUES, BLOOD_GROUPS

from .campaigns import Campaign
from .catalog import Product
from .hospitals import Hospital
from .transfers import HospitalRequest


class PatientRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Đã gửi"
        VERIFYING = "verifying", "Đang xác minh"
        VERIFIED = "verified", "Đã xác minh"
        REJECTED = "rejected", "Bị từ chối"
        PROCESSING = "processing", "Đang xử lý"
        FULFILLED = "fulfilled", "Đã hoàn tất"
        CANCELLED = "cancelled", "Đã hủy"

    FINAL_STATUSES = ("rejected", "fulfilled", "cancelled")

    request_code = models.CharField(max_length=30, unique=True)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="patient_requests")
    contact_name = models.CharField(max_length=150)
    contact_phone = models.CharField(max_length=20)
    patient_name = models.CharField(max_length=150, null=True, blank=True)  # nhạy cảm
    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="patient_requests")
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, null=True, blank=True)
    blood_product = models.ForeignKey(Product, on_delete=models.RESTRICT, null=True, blank=True, related_name="+")
    quantity_units = models.IntegerField()
    needed_by = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    consent_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="verified_by", null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=500, null=True, blank=True)
    resolution_note = models.TextField(null=True, blank=True)
    linked_support_request = models.ForeignKey(
        HospitalRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="patient_requests"
    )
    linked_campaign = models.ForeignKey(
        Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="patient_requests"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "patient_requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["hospital", "status"], name="idx_prq_hospital_status"),
            models.Index(fields=["requester", "created_at"], name="idx_prq_requester_time"),
            models.Index(fields=["status", "needed_by"], name="idx_prq_status_needed_by"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(verified_by__isnull=True) | ~Q(verified_by=F("requester")), name="chk_patient_req_not_self"
            ),
            models.CheckConstraint(condition=Q(quantity_units__gt=0), name="chk_patient_req_qty"),
            models.CheckConstraint(
                condition=~Q(status="rejected") | Q(reject_reason__isnull=False), name="chk_patient_req_reject_reason"
            ),
            models.CheckConstraint(
                condition=~Q(status="fulfilled") | Q(resolution_note__isnull=False), name="chk_patient_req_resolution"
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["verified", "processing", "fulfilled"])
                | Q(verified_by__isnull=False, verified_at__isnull=False, blood_group__isnull=False),
                name="chk_patient_req_verified",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=["submitted", "verifying", "verified", "rejected", "processing", "fulfilled", "cancelled"]
                ),
                name="chk_patient_req_status",
            ),
            models.CheckConstraint(
                condition=Q(blood_group__isnull=True) | Q(blood_group__in=BLOOD_GROUP_VALUES),
                name="chk_patient_req_blood_group",
            ),
        ]

    @property
    def is_final(self):
        return self.status in self.FINAL_STATUSES
