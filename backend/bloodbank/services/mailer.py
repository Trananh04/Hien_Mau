"""Soạn email Giọt Hồng: bản văn bản + bản HTML (nút bấm tới đúng trang), liên kết hủy nhận email lời kêu gọi.

HTML viết style inline (không dùng template trong templates/): trình đọc mail bỏ qua file CSS, còn trang web thì cấm
style inline theo CSP. Liên kết tuyệt đối theo SITE_URL vì email gửi từ luồng nền / tác vụ định kỳ không có request.
"""
import logging

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils.html import format_html, format_html_join

log = logging.getLogger(__name__)
BRAND = "Giọt Hồng"
PRIMARY = "#d90429"
UNSUBSCRIBE_SALT = "email-unsubscribe"


def absolute(path, request=None):
    if not path or path.startswith(("http://", "https://")):
        return path
    if request is not None:
        return request.build_absolute_uri(path)
    return f"{settings.SITE_URL}{path}" if settings.SITE_URL else path


def unsubscribe_token(user):
    return signing.dumps(user.pk, salt=UNSUBSCRIBE_SALT)


def unsubscribe_user_id(token):
    """Id người dùng trong liên kết hủy nhận email; liên kết sai / bị sửa → None. Không hết hạn (email cũ vẫn dùng được)."""
    try:
        return signing.loads(token, salt=UNSUBSCRIBE_SALT)
    except signing.BadSignature:
        return None


def build(user, subject, lines, action=None, unsubscribe=False, request=None):
    """Một email gửi `user`. `lines`: các đoạn nội dung; `action`: (nhãn nút, đường dẫn); `unsubscribe`: kèm liên kết hủy
    nhận (chỉ cho email kêu gọi / nhắc hiến — email nghiệp vụ, bảo mật luôn gửi)."""
    lines = [line for line in lines if line]
    label, url = action if action else (None, None)
    url = absolute(url, request)
    unsub_url = absolute(reverse("accounts:unsubscribe", args=[unsubscribe_token(user)]), request) if unsubscribe else None

    text = [f"Chào {user.full_name},", "", *lines]
    if url:
        text += ["", f"{label}: {url}"]
    text += ["", "—", f"Email tự động từ {BRAND}, vui lòng không trả lời email này."]
    if unsub_url:
        text.append(f"Không muốn nhận lời kêu gọi / nhắc hiến máu qua email: {unsub_url}")

    button = format_html(
        '<p style="margin:24px 0 8px"><a href="{}" style="display:inline-block;background:{};color:#ffffff;'
        'text-decoration:none;font-weight:600;padding:12px 22px;border-radius:8px">{}</a></p>', url, PRIMARY, label,
    ) if url else ""
    unsub = format_html('<br><a href="{}" style="color:#64748b">Hủy nhận lời kêu gọi / nhắc hiến máu qua email</a>',
                        unsub_url) if unsub_url else ""
    html = format_html(
        '<!doctype html><html lang="vi"><body style="margin:0;background:#f5f5f4;font-family:Arial,Helvetica,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f4;padding:24px 12px">'
        '<tr><td align="center"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden">'
        '<tr><td style="background:{};color:#ffffff;padding:16px 24px;font-size:18px;font-weight:700">{}</td></tr>'
        '<tr><td style="padding:24px;color:#334155;font-size:15px;line-height:1.6">'
        '<p style="margin:0 0 12px;color:#0f172a;font-size:17px;font-weight:600">{}</p>'
        '<p style="margin:0 0 12px">Chào {},</p>{}{}</td></tr>'
        '<tr><td style="padding:16px 24px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:12px;line-height:1.5">'
        'Email tự động từ {}, vui lòng không trả lời email này.{}</td></tr>'
        '</table></td></tr></table></body></html>',
        PRIMARY, BRAND, subject, user.full_name,
        format_html_join("", '<p style="margin:0 0 12px">{}</p>', ((line,) for line in lines)),
        button, BRAND, unsub,
    )
    headers = {}
    if unsub_url:
        # Nút "Hủy đăng ký" sẵn có của Gmail / Outlook (RFC 8058: một lần bấm, gửi POST tới liên kết)
        headers = {"List-Unsubscribe": f"<{unsub_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    msg = EmailMultiAlternatives(subject, "\n".join(text), settings.DEFAULT_FROM_EMAIL, [user.email], headers=headers)
    msg.attach_alternative(html, "text/html")
    return msg


def send_quietly(msg):
    """Gửi ngay trong request (email xác thực / đặt lại mật khẩu). Máy chủ mail lỗi không làm hỏng đăng ký — người
    dùng bấm "Gửi lại" sau. Trả về True nếu gửi được."""
    try:
        msg.send()
        return True
    except Exception:
        log.exception("Gửi email thất bại tới %s", msg.to)
        return False
