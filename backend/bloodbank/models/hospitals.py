"""Nhóm 1: bệnh viện, phân công nhân viên (`hospitals`, `staffs`)."""
from django.conf import settings
from django.db import models
from django.db.models import Q

LATLNG_PAIR = Q(latitude__isnull=True, longitude__isnull=True) | Q(latitude__isnull=False, longitude__isnull=False)


class Hospital(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Đang hoạt động"
        INACTIVE = "inactive", "Ngừng hoạt động"

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500)
    province = models.CharField(max_length=100)
    district = models.CharField(max_length=100, null=True, blank=True)
    ward = models.CharField(max_length=100, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hospitals"
        ordering = ["name"]
        indexes = [models.Index(fields=["province", "district"], name="idx_hospitals_prov_district")]
        constraints = [
            models.CheckConstraint(
                condition=Q(latitude__isnull=True) | Q(latitude__gte=-90, latitude__lte=90), name="chk_hospitals_lat"
            ),
            models.CheckConstraint(
                condition=Q(longitude__isnull=True) | Q(longitude__gte=-180, longitude__lte=180),
                name="chk_hospitals_lng",
            ),
            models.CheckConstraint(condition=LATLNG_PAIR, name="chk_hospitals_latlng_pair"),
            models.CheckConstraint(condition=Q(status__in=["active", "inactive"]), name="chk_hospitals_status"),
        ]

    def __str__(self):
        return self.name

    @property
    def area(self):
        return ", ".join(p for p in [self.district, self.province] if p)


class Staff(models.Model):
    class Role(models.TextChoices):
        # Một vai trò chung cho mọi nhân viên bệnh viện
        STAFF = "staff", "Nhân viên bệnh viện"

    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="staffs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="staffs")
    staff_role = models.CharField(max_length=30, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staffs"
        indexes = [models.Index(fields=["user"], name="idx_staffs_user")]
        constraints = [
            models.UniqueConstraint(fields=["hospital", "user"], name="uq_staffs_hospital_user"),
            models.CheckConstraint(
                condition=Q(staff_role__in=["staff"]),
                name="chk_staffs_role",
            ),
        ]

    def __str__(self):
        return f"{self.user} @ {self.hospital}"

