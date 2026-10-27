FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# var/forecast: nơi lưu mô hình dự báo (volume khi chạy thật) — tạo sẵn thuộc user app để volume mới nhận đúng quyền
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh \
    && mkdir -p /app/var/forecast \
    && useradd --create-home --uid 1000 app && chown -R app:app /app

# Không chạy bằng root
USER app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# Cấu hình chạy thật: không --reload (docker-compose.yml bật --reload cho môi trường dev)
# gthread: mỗi worker 8 luồng — request chờ dịch vụ ngoài (trợ lý AI) không chặn các trang khác; timeout 120s cho AI chậm
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "gthread", "--threads", "8", "--timeout", "120", "--access-logfile", "-"]
