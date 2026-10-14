"""Nhóm 4: lượt hiến thực tế (`donations`)."""
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES, BLOOD_GROUPS

from .campaigns import DONATION_TYPES, Registration
from .catalog import Product
from .hospitals import Hospital


class Donation(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Đã xác nhận"
        VOIDED = "voided", "Đã hủy hiệu lực"

    class ComponentUnit(models.TextChoices):
        ML = "ml", "ml"
        UNIT = "unit", "đơn vị"
        DOSE = "dose", "liều"

    class LabStatus(models.TextChoices):
        # Máu chưa xét nghiệm chưa được dùng: chỉ khi "Đạt" mới nhập vào kho
        PENDING = "pending", "Chờ xét nghiệm"
        PASSED = "passed", "Đạt — đã nhập kho"
        FAILED = "failed", "Không đạt"

    donor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="donations")
    registration = models.ForeignKey(
        Registration, on_delete=models.RESTRICT, null=True, blank=True, related_name="donations"
    )
    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="donations")
    donation_type = models.CharField(max_length=15, choices=DONATION_TYPES, default="whole_blood")
    volume_ml = models.IntegerField(null=True, blank=True)
    component_product = models.ForeignKey(
        Product, on_delete=models.RESTRICT, null=True, blank=True, related_name="component_donations"
    )
    component_quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    component_unit = models.CharField(max_length=5, choices=ComponentUnit.choices, null=True, blank=True)
    donated_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="confirmed_by", related_name="confirmed_donations"
    )
    confirmed_at = models.DateTimeField(default=timezone.now)
    void_reason = models.CharField(max_length=500, null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="voided_by", null=True, blank=True, related_name="voided_donations"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    # Kết quả xét nghiệm sàng lọc (luồng: ghi nhận → chờ xét nghiệm → đạt thì nhập kho)
    lab_status = models.CharField(max_length=10, choices=LabStatus.choices, default=LabStatus.PENDING)
    lab_blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, null=True, blank=True)
    lab_note = models.CharField(max_length=500, null=True, blank=True)
    lab_checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="lab_checked_by", null=True, blank=True,
        related_name="+",
    )
    lab_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "donations"
        ordering = ["-donated_at"]
        indexes = [
            models.Index(fields=["confirmed_by"], name="idx_donations_confirmed_by"),
            models.Index(fields=["donor", "status", "donated_at"], name="idx_donations_donor_date"),
            models.Index(fields=["hospital", "donated_at"], name="idx_donations_hospital_date"),
            models.Index(fields=["status", "donated_at"], name="idx_donations_status_date"),
            models.Index(fields=["hospital", "lab_status"], name="idx_donations_lab_queue"),
        ]
        constraints = [
            # Tương đương cột sinh active_registration_id + UNIQUE: mỗi đơn tối đa 1 lượt confirmed
            models.UniqueConstraint(
                fields=["registration"],
                condition=Q(status="confirmed", registration__isnull=False),
                name="uq_donations_active_registration",
            ),
            models.CheckConstraint(
                condition=Q(component_product__isnull=True, component_quantity__isnull=True, component_unit__isnull=True)
                | Q(
                    donation_type="component",
                    component_product__isnull=False,
                    component_quantity__gt=0,
                    component_unit__isnull=False,
                ),
                name="chk_record_component_fields",
            ),
            models.CheckConstraint(condition=~Q(confirmed_by=F("donor")), name="chk_record_not_self_confirm"),
            models.CheckConstraint(
                condition=Q(status="confirmed", void_reason__isnull=True, voided_at__isnull=True)
                | Q(status="voided", void_reason__isnull=False, voided_at__isnull=False),
                name="chk_record_void_fields",
            ),
            models.CheckConstraint(
                condition=Q(volume_ml__isnull=True) | Q(volume_ml__gt=0), name="chk_record_volume_positive"
            ),
            models.CheckConstraint(
                condition=~Q(donation_type="whole_blood") | Q(volume_ml__isnull=False),
                name="chk_record_whole_blood_volume",
            ),
            models.CheckConstraint(
                condition=Q(donation_type__in=["whole_blood", "component", "other"]), name="chk_donations_type"
            ),
            models.CheckConstraint(condition=Q(status__in=["confirmed", "voided"]), name="chk_donations_status"),
            models.CheckConstraint(condition=Q(lab_status__in=["pending", "passed", "failed"]), name="chk_donations_lab_status"),
            models.CheckConstraint(
                condition=Q(lab_status="pending", lab_checked_at__isnull=True)
                | Q(lab_status="passed", lab_blood_group__in=BLOOD_GROUP_VALUES, lab_checked_at__isnull=False,
                    lab_checked_by__isnull=False)
                | Q(lab_status="failed", lab_note__isnull=False, lab_checked_at__isnull=False, lab_checked_by__isnull=False),
                name="chk_donations_lab_fields",
            ),
            models.CheckConstraint(
                condition=Q(component_unit__isnull=True) | Q(component_unit__in=["ml", "unit", "dose"]),
                name="chk_donations_component_unit",
            ),
        ]

    @property
    def code(self):
        return f"LH-{self.id:06d}"
