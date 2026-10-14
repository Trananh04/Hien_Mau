"""Nhóm 9 (mở rộng ngoài đặc tả gốc): nhật ký kêu gọi người hiến (dùng cho thời gian chờ và liên kết thông báo)."""
from django.conf import settings
from django.db import models
from django.db.models import Q

from accounts.models import BLOOD_GROUP_VALUES, BLOOD_GROUPS

from .campaigns import Campaign
from .hospitals import Hospital


class DonorCallout(models.Model):
    """Một lần bệnh viện kêu gọi người hiến cho một nhóm máu đang thiếu."""

    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="callouts")
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS)
    campaign = models.ForeignKey(Campaign, on_delete=models.SET_NULL, null=True, blank=True, related_name="callouts")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="created_by",
                                  related_name="+")
    recipient_count = models.IntegerField()  # số người đủ điều kiện đã được gửi lời mời
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "donor_callouts"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["hospital", "blood_group", "created_at"], name="idx_callouts_hosp_bg")]
        constraints = [
            models.CheckConstraint(condition=Q(blood_group__in=BLOOD_GROUP_VALUES), name="chk_callouts_blood_group"),
            models.CheckConstraint(condition=Q(recipient_count__gt=0), name="chk_callouts_counts"),
        ]
