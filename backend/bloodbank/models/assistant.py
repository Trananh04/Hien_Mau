"""Lịch sử trò chuyện với trợ lý (chỉ người đã đăng nhập; khách chỉ có lịch sử trong phiên).

Chỉ chủ tài khoản xem được qua API; tự xóa sau `chat_retention_days` ngày (tác vụ định kỳ) hoặc khi người dùng xóa.
"""
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q


class ChatConversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_conversations")
    title = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "chat_conversations"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "updated_at"], name="idx_chat_conv_user")]


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Người dùng"
        ASSISTANT = "assistant", "Trợ lý"

    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField()
    cards = models.JSONField(encoder=DjangoJSONEncoder, default=list, blank=True)
    links = models.JSONField(encoder=DjangoJSONEncoder, default=list, blank=True)
    source = models.CharField(max_length=300, null=True, blank=True)
    mode = models.CharField(max_length=10, null=True, blank=True)   # llm / rules / guard
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_messages"
        ordering = ["created_at", "id"]
        constraints = [models.CheckConstraint(condition=Q(role__in=["user", "assistant"]), name="chk_chat_msg_role")]
