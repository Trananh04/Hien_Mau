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

# Cổng quản trị không có liên kết công khai. Khi chạy thật nên đổi đường dẫn đăng nhập thành chuỗi khó đoán
# và (tùy chọn) chỉ cho phép một số IP; ngoài danh sách → trang 404 như thể không tồn tại.
ADMIN_LOGIN_PATH = (os.environ.get("ADMIN_LOGIN_PATH", "quan-tri/dang-nhap").strip("/") or "quan-tri/dang-nhap") + "/"
ADMIN_ALLOWED_IPS = env_list("ADMIN_ALLOWED_IPS")
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
    "bloodbank.middleware.HtmxPageMiddleware",
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
# MAX_ENTRIES mặc định chỉ 300: vượt ngưỡng Django xóa bớt theo thứ tự khóa → có thể xóa mất bộ đếm lượt gọi AI
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "django_cache",
                      "OPTIONS": {"MAX_ENTRIES": 50000}}}

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

# Bản đồ Goong (https://help.goong.io): Map key hiển thị bản đồ trên trình duyệt (bắt buộc lộ ra trang — giới hạn
# theo tên miền ở account.goong.io); API key chỉ dùng trên máy chủ (tra địa chỉ, gợi ý địa điểm, chỉ đường).
GOONG_MAP_KEY = os.environ.get("GOONG_MAP_KEY", "")
GOONG_API_KEY = os.environ.get("GOONG_API_KEY", "")
# Chạy test: không gọi dịch vụ bản đồ thật (test tự giả lập khi cần)
if len(sys.argv) > 1 and sys.argv[1] == "test":
    GOONG_MAP_KEY = GOONG_API_KEY = ""

# Trợ lý hỏi đáp: mô hình chạy tại chỗ qua Ollama (dữ liệu không rời máy chủ). Không gọi được Ollama → chế độ từ khóa.
CHATBOT_USE_LLM = os.environ.get("CHATBOT_USE_LLM", "1") == "1"
# Trong Docker: tên service `ollama`; Ollama chạy ngoài Docker trên cùng máy: http://host.docker.internal:11434
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))          # đủ cho quy tắc + tài liệu + 6 lượt hội thoại
OLLAMA_NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "512"))   # câu trả lời ngắn (2–5 câu)
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.3"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")          # giữ mô hình trong bộ nhớ giữa các câu hỏi
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "90"))           # lần đầu nạp mô hình vào GPU mất vài chục giây
# Chế độ "suy nghĩ" (mô hình có hỗ trợ): tắt mặc định — chậm hơn nhiều mà câu trả lời ngắn không cần.
# Mặc định dùng bản qwen3 *instruct* vì bản `qwen3:4b` (thinking) vẫn viết suy luận ra câu trả lời dù tắt.
OLLAMA_THINK = {"1": True, "true": True, "0": False, "false": False}.get(
    os.environ.get("OLLAMA_THINK", "false").lower())
if len(sys.argv) > 1 and sys.argv[1] == "test":
    OLLAMA_BASE_URL = ""   # bộ test không gọi mô hình thật — test AI dùng client giả lập
CHATBOT_RATE_LIMIT = int(os.environ.get("CHATBOT_RATE_LIMIT", "20"))     # số câu / 5 phút / người dùng (hoặc phiên)
# Số câu gửi AI cùng lúc (toàn hệ thống); vượt → trả lời ngay bằng chế độ từ khóa. Card 4 GB: 1–2.
CHATBOT_MAX_CONCURRENT = int(os.environ.get("CHATBOT_MAX_CONCURRENT", "2"))

# AI dự báo nhu cầu (XGBoost): mô hình + metadata do `manage.py train_forecast` ghi ra; không commit vào Git
FORECAST_MODEL_DIR = Path(os.environ.get("FORECAST_MODEL_DIR", BASE_DIR / "var" / "forecast"))

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "Giọt Hồng <no-reply@hienmau.local>"

MESSAGE_TAGS = {10: "info", 20: "info", 25: "success", 30: "warning", 40: "error"}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
