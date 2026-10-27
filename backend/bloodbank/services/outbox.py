"""Hàng đợi email: mỗi email là một dòng `notifications` (channel = email, delivery_status = pending).

Gửi NGAY nhưng KHÔNG chặn request: sau khi giao dịch commit, một luồng nền gửi các dòng vừa tạo (dispatch). Dòng nào
lỗi (máy chủ mail trục trặc) hoặc bị bỏ dở (worker khởi động lại giữa chừng) được tác vụ định kỳ gửi lại (sweep), tối
đa MAX_ATTEMPTS lần. Mỗi lần gửi "giành" dòng bằng UPDATE có điều kiện trên `attempts`, nên luồng nền và tác vụ định
kỳ không gửi trùng cùng một lần thử.
"""
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import connection
from django.db.models import F
from django.utils import timezone

from bloodbank.models import Notification

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=2)       # dòng chưa gửi được sau 2 phút → tác vụ định kỳ gửi lại
D = Notification.Delivery


def _send_one(row):
    claimed = Notification.objects.filter(pk=row.pk, attempts=row.attempts,
                                          delivery_status__in=(D.PENDING, D.FAILED)).update(attempts=F("attempts") + 1)
    if not claimed:
        return None                                    # nơi khác đang / đã gửi
    try:
        send_mail(f"[Khẩn] {row.title}", (row.body or row.title) + "\n\nĐăng nhập cổng bệnh viện để xử lý.",
                  settings.DEFAULT_FROM_EMAIL, [row.user.email])
        status = D.SENT
    except Exception:                                  # máy chủ mail lỗi: ghi nhận để gửi lại
        log.exception("Gửi email thất bại (thông báo %s)", row.pk)
        status = D.FAILED
    Notification.objects.filter(pk=row.pk).update(delivery_status=status, sent_at=timezone.now())
    return status


def send(ids):
    """Gửi các email theo id (bỏ qua dòng đã gửi). Trả về số email gửi thành công."""
    rows = Notification.objects.filter(pk__in=ids, channel=Notification.Channel.EMAIL,
                                       delivery_status__in=(D.PENDING, D.FAILED),
                                       attempts__lt=MAX_ATTEMPTS).select_related("user")
    return sum(_send_one(r) == D.SENT for r in rows)


def _background(ids):
    try:
        send(ids)
    finally:
        connection.close()                             # luồng nền: trả kết nối DB riêng của luồng


def dispatch(ids):
    """Gọi trong transaction.on_commit. EMAIL_ASYNC (mặc định bật) → luồng nền; tắt (test) → gửi ngay tại chỗ."""
    if not ids:
        return
    if getattr(settings, "EMAIL_ASYNC", True):
        threading.Thread(target=_background, args=(list(ids),), daemon=True, name="email-outbox").start()
    else:
        send(ids)


def sweep(now=None):
    """Tác vụ định kỳ: gửi lại email lỗi / bị bỏ dở cũ hơn RETRY_AFTER."""
    cutoff = (now or timezone.now()) - RETRY_AFTER
    ids = list(Notification.objects.filter(channel=Notification.Channel.EMAIL,
                                           delivery_status__in=(D.PENDING, D.FAILED), attempts__lt=MAX_ATTEMPTS,
                                           created_at__lt=cutoff).values_list("pk", flat=True)[:200])
    return send(ids) if ids else 0
