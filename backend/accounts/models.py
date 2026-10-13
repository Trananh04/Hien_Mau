"""Bảng `users` và `auth_tokens` (Data Dictionary mục 1, 4)."""
import hashlib
import re
import secrets
from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone

BLOOD_GROUPS = [
    ("A+", "A+"), ("A-", "A−"), ("B+", "B+"), ("B-", "B−"),
    ("AB+", "AB+"), ("AB-", "AB−"), ("O+", "O+"), ("O-", "O−"),
]
BLOOD_GROUP_VALUES = [value for value, _ in BLOOD_GROUPS]


def normalize_phone(raw):
    """Chuẩn hóa số điện thoại Việt Nam về E.164 (+84...). Trả None nếu rỗng."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if digits.startswith("+"):
        return digits
    if digits.startswith("84"):
        return "+" + digits
    if digits.startswith("0"):
        return "+84" + digits[1:]
    return "+84" + digits


def display_phone(e164):
    if not e164:
        return ""
    if e164.startswith("+84"):
        return "0" + e164[3:]
    return e164


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email bắt buộc")
        email = email.strip().lower()
        if "phone" in extra:
            extra["phone"] = normalize_phone(extra["phone"])
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser):
    class Role(models.TextChoices):
        # Ba vai trò tách biệt, mỗi vai trò một cổng đăng nhập (xem bloodbank/access.py)
        MEMBER = "member", "Người dùng"
        HOSPITAL = "hospital", "Nhân viên bệnh viện"
        ADMIN = "admin", "Quản trị hệ thống"

    class Status(models.TextChoices):
        ACTIVE = "active", "Đang hoạt động"
        LOCKED = "locked", "Đã khóa"
        DELETED = "deleted", "Đã xóa"

    class Gender(models.TextChoices):
        MALE = "male", "Nam"
        FEMALE = "female", "Nữ"
        OTHER = "other", "Khác"

    email = models.CharField(max_length=255, unique=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    password = models.CharField(max_length=255, db_column="password_hash")
    full_name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, null=True, blank=True)
    # Nhóm máu tự khai — không dùng cho quyết định nào
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS, null=True, blank=True)
    address = models.CharField(max_length=500, null=True, blank=True)
    province = models.CharField(max_length=100, null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True, db_column="last_login_at")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(condition=Q(role__in=["member", "hospital", "admin"]), name="chk_users_role"),
            models.CheckConstraint(condition=Q(status__in=["active", "locked", "deleted"]), name="chk_users_status"),
            models.CheckConstraint(
                condition=Q(gender__isnull=True) | Q(gender__in=["male", "female", "other"]), name="chk_users_gender"
            ),
            models.CheckConstraint(
                condition=Q(blood_group__isnull=True) | Q(blood_group__in=BLOOD_GROUP_VALUES),
                name="chk_users_blood_group",
            ),
            models.CheckConstraint(condition=Q(email=models.functions.Lower("email")), name="chk_users_email_lower"),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    # BR-23: locked/deleted không đăng nhập được
    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN and self.is_active

    @property
    def is_member(self):
        return self.role == self.Role.MEMBER and self.is_active

    @property
    def is_hospital_user(self):
        return self.role == self.Role.HOSPITAL and self.is_active

    @property
    def phone_display(self):
        return display_phone(self.phone)

    @property
    def short_name(self):
        parts = (self.full_name or "").split()
        return parts[-1] if parts else self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthToken(models.Model):
    class Purpose(models.TextChoices):
        REFRESH = "refresh", "Phiên"
        PASSWORD_RESET = "password_reset", "Đặt lại mật khẩu"
        EMAIL_VERIFY = "email_verify", "Xác thực email"

    user = models.ForeignKey(User, on_delete=models.RESTRICT, related_name="auth_tokens")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_ip = models.CharField(max_length=45, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "auth_tokens"
        indexes = [
            models.Index(fields=["expires_at"], name="idx_auth_tokens_expires"),
            models.Index(fields=["user", "purpose", "revoked_at"], name="idx_auth_tokens_user_purpose"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(expires_at__gt=models.F("created_at")), name="chk_auth_tokens_expiry"),
            models.CheckConstraint(
                condition=Q(purpose__in=["refresh", "password_reset", "email_verify"]), name="chk_auth_tokens_purpose"
            ),
        ]

    @classmethod
    def issue(cls, user, purpose, ttl=timedelta(hours=1), ip=None):
        """Tạo token; chỉ lưu SHA-256, trả về chuỗi gốc để gửi cho người dùng."""
        raw = secrets.token_urlsafe(32)
        now = timezone.now()
        cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True, revoked_at__isnull=True).update(
            revoked_at=now
        )
        cls.objects.create(
            user=user, purpose=purpose, token_hash=hash_token(raw), expires_at=now + ttl, created_ip=ip, created_at=now
        )
        return raw

    @classmethod
    def find_valid(cls, raw, purpose):
        return (
            cls.objects.select_related("user")
            .filter(
                token_hash=hash_token(raw),
                purpose=purpose,
                used_at__isnull=True,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
