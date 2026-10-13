"""Nhóm 8: giám sát và cấu hình (`audit_logs`, `notifications`, `system_settings`)."""
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q

from .hospitals import Hospital


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, null=True, blank=True, related_name="+"
    )
    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, null=True, blank=True, related_name="+")
    entity_type = models.CharField(max_length=50)
    entity_id = models.BigIntegerField()
    action = models.CharField(max_length=50)
    old_values = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    new_values = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    request_id = models.CharField(max_length=64, null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["actor", "created_at"], name="idx_audit_actor_time"),
            models.Index(fields=["entity_type", "entity_id", "created_at"], name="idx_audit_entity"),
            models.Index(fields=["hospital", "created_at"], name="idx_audit_hospital_time"),
        ]


class Notification(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", "Trong ứng dụng"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class Delivery(models.TextChoices):
        PENDING = "pending", "Chờ gửi"
        SENT = "sent", "Đã gửi"
        FAILED = "failed", "Lỗi"
        SKIPPED = "skipped", "Bỏ qua"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="notifications")
    type = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=1000, null=True, blank=True)
    entity_type = models.CharField(max_length=50, null=True, blank=True)
    entity_id = models.BigIntegerField(null=True, blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.IN_APP)
    delivery_status = models.CharField(max_length=10, choices=Delivery.choices, default=Delivery.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["delivery_status", "channel", "created_at"], name="idx_notif_outbox"),
            models.Index(fields=["user", "read_at", "created_at"], name="idx_notif_user_unread"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(channel__in=["in_app", "email", "sms"]), name="chk_notif_channel"),
            models.CheckConstraint(
                condition=Q(delivery_status__in=["pending", "sent", "failed", "skipped"]), name="chk_notif_delivery"
            ),
        ]


class SystemSetting(models.Model):
    setting_key = models.CharField(max_length=100, primary_key=True)
    setting_value = models.JSONField()
    description = models.CharField(max_length=500, null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="updated_by", null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "system_settings"
        ordering = ["setting_key"]

    DEFAULTS = {
        "login_max_failed_attempts": (5, "Số lần đăng nhập sai liên tiếp trước khi tạm khóa"),
        "login_lock_minutes": (15, "Thời gian tạm khóa đăng nhập (phút)"),
        "password_reset_ttl_minutes": (60, "Thời hạn token đặt lại mật khẩu (phút)"),
        "email_verify_ttl_hours": (48, "Thời hạn token xác thực email (giờ)"),
        "whole_blood_volume_warn_min_ml": (250, "Ngưỡng cảnh báo thể tích toàn phần thấp (ml) — OI-25"),
        "whole_blood_volume_warn_max_ml": (450, "Ngưỡng cảnh báo thể tích toàn phần cao (ml) — OI-25"),
        "donation_record_grace_hours": (48, "Ân hạn ghi nhận sau khi đợt hoàn tất (giờ) — OI-23"),
    }

    @classmethod
    def get(cls, key):
        row = cls.objects.filter(setting_key=key).first()
        if row is not None:
            return row.setting_value
        return cls.DEFAULTS[key][0]
