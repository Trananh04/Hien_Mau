"""Quản trị: cảnh báo toàn hệ thống (chỉ đọc, không lộ tên bệnh nhân) và theo dõi / bật tắt AI của trợ lý."""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bloodbank.assistant import llm
from bloodbank.models import AuditLog, Demand, PatientRequest, SystemSetting
from bloodbank.services import admin as admin_service
from bloodbank.services.common import BusinessError

from . import factories as f


class SystemAlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = f.user(email="admin-monitor@test.vn", role="admin")
        cls.h = f.hospital(name="BV Cảnh báo", phone="0236111222")
        donor = f.user(email="nguoinha@test.vn")
        cls.late = PatientRequest.objects.create(
            requester=donor, contact_name="Người nhà", contact_phone="0905000333", patient_name="Bệnh Nhân Kín",
            hospital=cls.h, quantity_units=2, consent_at=timezone.now(), request_code="PR-LATE-0001")
        PatientRequest.objects.filter(pk=cls.late.pk).update(created_at=timezone.now() - timedelta(minutes=45))
        PatientRequest.objects.create(requester=donor, contact_name="Người nhà", contact_phone="0905000333",
                                      hospital=cls.h, quantity_units=1, consent_at=timezone.now(),
                                      request_code="PR-FRESH-0002")     # mới gửi → chưa cần đôn đốc
        Demand.objects.create(hospital=cls.h, blood_group="O-", product_spec=f.spec(), required_quantity=3)

    def test_alerts_list_late_requests_and_shortages_without_patient_name(self):
        a = admin_service.system_alerts()
        self.assertEqual([p.request_code for p in a["late_prq"]], ["PR-LATE-0001"])
        self.assertEqual([(s["hospital"].pk, s["total"]) for s in a["shortages"]], [(self.h.pk, 3)])
        self.assertEqual(a["urgent_count"], 1)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("bloodbank:admin_alerts"), follow=True)   # cảnh báo đã gộp vào Tổng quan
        self.assertEqual(r.redirect_chain[-1][0], reverse("bloodbank:admin_stats") + "#canh-bao")
        self.assertEqual([k["count"] for k in r.context["kpis"]][:2], [1, 1])
        self.assertContains(r, "PR-LATE-0001")
        self.assertNotContains(r, "PR-FRESH-0002")
        self.assertNotContains(r, "Bệnh Nhân Kín")          # tên bệnh nhân chỉ bệnh viện điều trị được xem
        self.assertNotContains(r, "0905000333")             # không lộ số người nhà; chỉ số bệnh viện
        self.assertContains(r, 'href="tel:0236111222"')
        # Menu Quản trị có số việc khẩn
        self.assertContains(r, '<span class="count" aria-label="1 chờ xử lý">1</span>')

    def test_alerts_is_admin_only(self):
        self.client.force_login(f.staff(self.h))
        self.assertEqual(self.client.get(reverse("bloodbank:admin_alerts")).status_code, 404)


@override_settings(ANTHROPIC_API_KEY="test-key", CHATBOT_USE_LLM=True)
class AssistantMonitorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = f.user(email="admin-ai@test.vn", role="admin")
        for mode, intent in (("llm", "faq"), ("llm", "suggest_campaigns"), ("rules", "history"), ("guard", "emergency")):
            AuditLog.objects.create(action="assistant_query", entity_type="assistant", entity_id=0,
                                    new_values={"mode": mode, "intent": intent})

    def test_stats_by_mode_and_topic(self):
        s = admin_service.assistant_stats()
        self.assertEqual(s["total"], 4)
        self.assertEqual({m["key"]: m["count"] for m in s["modes"]}, {"llm": 2, "rules": 1, "guard": 1, "limit": 0})
        self.assertIn(("Tìm đợt hiến", 1), s["intents"])
        self.assertEqual(s["days"][-1]["total"], 4)
        self.assertTrue(s["enabled"])

    def test_admin_switches_ai_off_and_on_with_audit(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("bloodbank:admin_assistant")), "AI đang trả lời")
        self.client.post(reverse("bloodbank:admin_assistant"), {"ai": "off"})
        self.assertFalse(SystemSetting.get("chatbot_ai_enabled"))
        self.assertFalse(llm.enabled())                     # trợ lý chuyển sang chế độ từ khóa
        self.assertTrue(AuditLog.objects.filter(entity_type="system_settings", new_values__value=False).exists())
        self.client.post(reverse("bloodbank:admin_assistant"), {"ai": "on"})
        self.assertTrue(llm.enabled())

    def test_save_setting_validates_booleans_and_ints(self):
        admin_service.save_setting(self.admin, "chatbot_ai_enabled", "false")
        self.assertIs(SystemSetting.get("chatbot_ai_enabled"), False)
        for key, raw in (("chatbot_ai_enabled", "1"), ("chat_retention_days", "true"), ("chat_retention_days", "0")):
            with self.assertRaises(BusinessError):
                admin_service.save_setting(self.admin, key, raw)


class DailyCounterTests(TestCase):
    def test_counter_reseeded_from_audit_when_cache_lost(self):
        """Cache bị dọn mất bộ đếm → đếm lại từ nhật ký, hạn mức ngày không bị đặt về 0."""
        from django.core.cache import cache

        from bloodbank.assistant import service

        for _ in range(3):
            AuditLog.objects.create(action="assistant_query", entity_type="assistant", entity_id=0,
                                    new_values={"mode": "llm", "intent": "faq"})
        cache.delete(service.llm_day_key())
        self.assertEqual(service.llm_calls_today(), 3)
        with override_settings(CHATBOT_DAILY_LIMIT=3):
            self.assertIsNone(service._llm_slot())        # đã chạm hạn mức → không gọi AI

    def test_intent_labels_hide_technical_names(self):
        for intent in ("shell", "history:login_required"):
            AuditLog.objects.create(action="assistant_query", entity_type="assistant", entity_id=0,
                                    new_values={"mode": "rules", "intent": intent})
        labels = dict(admin_service.assistant_stats()["intents"])
        self.assertEqual(labels, {"Khác": 1, "Lịch sử hiến": 1})
