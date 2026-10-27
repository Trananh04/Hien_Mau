"""Nhóm 8: giám sát và cấu hình (`audit_logs`, `notifications`, `system_settings`)."""
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q

from .hospitals import Hospital


# Nhóm nhật ký: "Nghiệp vụ" (mặc định) là thao tác thay đổi dữ liệu; "Bảo mật" là đăng nhập / truy cập;
# câu hỏi trợ lý chỉ hiện ở "Tất cả". Index một phần idx_audit_*_business khớp đúng bộ lọc "Nghiệp vụ".
AUDIT_SECURITY_ACTIONS = ("login", "login_failed", "login_wrong_portal", "access_denied", "view_sensitive",
                          "password_reset", "password_reset_requested", "password_changed", "email_verified")
AUDIT_NOISE_ACTIONS = ("assistant_query",)
_BUSINESS = ~Q(action__in=AUDIT_SECURITY_ACTIONS + AUDIT_NOISE_ACTIONS)


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
            # Trang Nhật ký (tab Nghiệp vụ, mặc định) của bệnh viện và của quản trị
            models.Index(fields=["hospital", "-created_at", "-id"], condition=_BUSINESS,
                         name="idx_audit_hosp_business"),
            models.Index(fields=["-created_at", "-id"], condition=_BUSINESS, name="idx_audit_business"),
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
        "donation_interval_whole_blood_days": (84, "Khoảng cách tối thiểu giữa 2 lần hiến máu toàn phần (ngày) — chỉ cảnh báo khi check-in"),
        "donation_interval_component_days": (14, "Khoảng cách tối thiểu sau lần hiến thành phần (ngày) — chỉ cảnh báo khi check-in"),
        "offer_response_ttl_hours": (12, "Đề nghị liên viện không được phản hồi sau số giờ này sẽ tự hủy"),
        "offer_response_ttl_urgent_minutes": (60, "Yêu cầu liên viện KHẨN: đề nghị không được phản hồi sau số phút này tự hủy để mời bệnh viện khác"),
        "prq_escalate_staff_minutes": (15, "Yêu cầu cần máu chưa được xác minh sau số phút này: nhắc lại toàn bộ nhân viên (kèm email)"),
        "prq_escalate_admin_minutes": (30, "Yêu cầu cần máu chưa được xác minh sau số phút này: báo lên Quản trị hệ thống"),
        "auth_email_max_per_window": (3, "Số email đặt lại mật khẩu / xác thực tối đa cho một tài khoản trong khung thời gian"),
        "auth_email_window_minutes": (15, "Khung thời gian giới hạn gửi email đặt lại mật khẩu / xác thực (phút)"),
        "donor_min_age": (18, "Kiểm tra sơ bộ (trợ lý): tuổi tối thiểu thường áp dụng"),
        "donor_max_age": (60, "Kiểm tra sơ bộ (trợ lý): tuổi tối đa thường áp dụng"),
        "donor_min_weight_male_kg": (45, "Kiểm tra sơ bộ (trợ lý): cân nặng tối thiểu của nam (kg)"),
        "donor_min_weight_female_kg": (42, "Kiểm tra sơ bộ (trợ lý): cân nặng tối thiểu của nữ (kg)"),
        "chat_retention_days": (30, "Lịch sử trò chuyện với trợ lý được tự xóa sau số ngày này"),
        "chatbot_ai_enabled": (True, "Trợ lý dùng AI (true) hay chỉ chế độ từ khóa (false, không tốn phí)"),
        "lab_max_units_per_donation":(3, "Số đơn vị tối đa được nhập kho từ một lượt hiến khi xét nghiệm đạt"),
        "donor_invite_cooldown_days": (7, "Mỗi người hiến nhận tối đa 1 lời kêu gọi trong số ngày này (tính trên mọi bệnh viện)"),
        "shortage_urgent_hours": (24, "Nhu cầu cần máu trước số giờ này được xếp mức Khẩn (ưu tiên xuất kho, xin liên viện, kêu gọi khẩn)"),
        "donor_invite_urgent_cooldown_days": (3, "Kêu gọi khẩn: người hiến không nhận lời kêu gọi nào trong số ngày này mới được mời"),
        "forecast_ai_enabled": (False, "Dự báo thiếu hụt dùng mô hình AI (XGBoost) thay cho trung bình 28 ngày — chỉ bật khi mô hình đã huấn luyện và thắng baseline"),
        "forecast_auto_retrain": (True, "Tự học lại mô hình dự báo khi có lý do: lần đầu đủ dữ liệu thật, AI dự báo kém hơn trung bình, hoặc có thêm dữ liệu mới (bản mới chỉ được dùng khi qua chốt chặn)"),
        "forecast_retrain_days": (30, "Mô hình học từ dữ liệu thật được học lại để cập nhật dữ liệu mới sau số ngày này"),
        "donor_invite_max_90_days": (4, "Chia đều lượt kêu gọi: người đã nhận số lời kêu gọi này trong 90 ngày (mọi bệnh viện) tạm không được gợi ý"),
        "donor_invite_response_days": (7, "Người được mời đăng ký đợt hiến hoặc hiến máu tại bệnh viện trong số ngày này sau lời mời thì tính là đã hưởng ứng"),
    }

    @classmethod
    def get(cls, key):
        row = cls.objects.filter(setting_key=key).first()
        if row is not None:
            return row.setting_value
        return cls.DEFAULTS[key][0]
