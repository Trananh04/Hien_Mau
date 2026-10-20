"""Cấu hình Django cho Giọt Hồng."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("dev-only-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Thiếu DJANGO_SECRET_KEY (bắt buộc khi DJANGO_DEBUG=0).")
# Số reverse proxy tin cậy đứng trước ứng dụng (0 = không tin header X-Forwarded-For, dùng REMOTE_ADDR)
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0") or 0)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:8080")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "accounts",
    "bloodbank",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "bloodbank.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.ActiveUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "bloodbank.middleware.ScreenAccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "bloodbank.context_processors.workspace",
            ],
            "builtins": ["bloodbank.templatetags.ui"],
        },
    }
]

if DEBUG:
    # gunicorn --reload chỉ nạp lại khi file .py đổi: tắt lưu đệm template để sửa template là thấy ngay
    TEMPLATES[0]["APP_DIRS"] = False
    TEMPLATES[0]["OPTIONS"]["loaders"] = [
        "django.template.loaders.filesystem.Loader",
        "django.template.loaders.app_directories.Loader",
    ]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "hien_mau"),
        "USER": os.environ.get("POSTGRES_USER", "hienmau"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "TEST": {"NAME": "test_hien_mau"},
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "bloodbank:home"

# BR-22: băm mật khẩu bằng thuật toán chậm có salt (Argon2)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"  # hiển thị giờ Việt Nam; CSDL lưu UTC (USE_TZ)
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache dùng chung cho MỌI worker/luồng (bảng PostgreSQL) — giới hạn tần suất & số cuộc gọi AI đồng thời phải đếm chung
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "django_cache"}}

# Triển khai sau HTTPS: đặt DJANGO_HTTPS=1 → chuyển hướng HTTPS, HSTS, cookie chỉ gửi qua HTTPS
if os.environ.get("DJANGO_HTTPS", "0") == "1":
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False

# Trợ lý hỏi đáp: có ANTHROPIC_API_KEY → dùng Claude; không có → chế độ từ khóa (không cần AI)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if "test" in sys.argv[1:2]:
    ANTHROPIC_API_KEY = ""  # bộ test không bao giờ gọi API thật (tốn phí, không ổn định) — test LLM dùng client giả lập
CHATBOT_USE_LLM = os.environ.get("CHATBOT_USE_LLM", "1") == "1"
CHATBOT_MODEL = os.environ.get("CHATBOT_MODEL", "claude-haiku-5-5")
# Địa chỉ API tương thích Claude Messages (để trống = API chính thức của Anthropic). Dịch vụ trung gian sẽ nhận
# toàn bộ câu hỏi + kết quả công cụ — chỉ dùng nhà cung cấp tin cậy.
CHATBOT_BASE_URL = os.environ.get("CHATBOT_BASE_URL", "").rstrip("/") or None
CHATBOT_MAX_TOKENS = int(os.environ.get("CHATBOT_MAX_TOKENS", "4096"))
# Mức effort; để trống = không gửi (Claude Haiku 4.5 / Sonnet 4.5 không hỗ trợ tham số effort)
CHATBOT_EFFORT = os.environ.get("CHATBOT_EFFORT", "" if any(v in CHATBOT_MODEL for v in ("4.5", "4-5")) else "low")
CHATBOT_TIMEOUT = float(os.environ.get("CHATBOT_TIMEOUT", "20"))
CHATBOT_RATE_LIMIT = int(os.environ.get("CHATBOT_RATE_LIMIT", "20"))
CHATBOT_MAX_CONCURRENT = int(os.environ.get("CHATBOT_MAX_CONCURRENT", "8"))  # số câu gửi AI cùng lúc tối đa (toàn hệ thống)
CHATBOT_DAILY_LIMIT = int(os.environ.get("CHATBOT_DAILY_LIMIT", "2000"))   # số câu gửi AI / ngày (kiểm soát chi phí)  # số câu / 5 phút / người dùng (hoặc phiên)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "Giọt Hồng <no-reply@hienmau.local>"

MESSAGE_TAGS = {10: "info", 20: "info", 25: "success", 30: "warning", 40: "error"}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
