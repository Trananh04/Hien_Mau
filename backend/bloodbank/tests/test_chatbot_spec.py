"""Kiểm thử theo đặc tả chatbot CHAT-01..10: RAG có phiên bản/nguồn, kiểm tra sơ bộ, lịch sử hiến, ghi nhớ hội thoại,
7 API (phân quyền + cô lập dữ liệu), bước kiểm tra câu trả lời AI, tự xóa hội thoại cũ."""
import json
from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bloodbank.assistant import knowledge, llm, rules, service, tools, verify
from bloodbank.assistant.tools import Ctx
from bloodbank.models import ChatConversation, ChatMessage

from .test_assistant import AssistantData, fake_response, text, tool_use
from .test_badges import donate


class KnowledgeBaseTests(TestCase):
    """CHAT-01/03/05/09/10: truy xuất tài liệu đã duyệt (RAG) có phiên bản + nguồn."""

    def test_every_document_has_version_source_and_review_date(self):
        docs = knowledge._docs()
        self.assertGreaterEqual(len(docs), 15)
        for d in docs:
            with self.subTest(doc=d["id"]):
                self.assertRegex(d["version"], r"^\d+\.\d+$")
                self.assertTrue(d["source"])
                date.fromisoformat(d["reviewed"])
                self.assertNotIn("{", knowledge._render(d))      # mọi biến cấu hình đã được thay

    def test_retrieval_top1(self):
        cases = {
            "Hiến máu có ảnh hưởng đến sức khỏe không?": "an-toan",              # CHAT-01
            "hien mau co nguy hiem khong": "an-toan",
            "Trước khi hiến máu có được ăn sáng không?": "chuan-bi",             # CHAT-03
            "hiến xong về cần kiêng gì": "sau-khi-hien",
            "Tôi muốn đăng ký hiến máu thì làm thế nào?": "dang-ky",             # CHAT-05
            "Tiểu cầu và hồng cầu khác nhau thế nào?": "che-pham",               # CHAT-09
            "Tôi muốn thay đổi thông tin cá nhân thì làm sao?": "tai-khoan",     # CHAT-10
            "người nhà cần máu gấp phải làm gì": "yeu-cau-can-mau",
        }
        for q, doc in cases.items():
            with self.subTest(q=q):
                self.assertEqual(knowledge.search(q)[0]["id"], doc)
        self.assertEqual(knowledge.search("giá vàng hôm nay"), [])           # không liên quan → không bịa

    def test_config_values_rendered_from_settings(self):
        from bloodbank.models import SystemSetting

        SystemSetting.objects.update_or_create(setting_key="donor_min_age", defaults={"setting_value": 17})
        self.assertIn("Tuổi khoảng 17–60", knowledge.get("dieu-kien-chung")["text"])

    def test_rules_answer_cites_title_and_version(self):
        a = rules.answer("Tiểu cầu và hồng cầu khác nhau thế nào?", Ctx())
        self.assertIn("Tiểu cầu", a["answer"])
        self.assertIn("phiên bản 1.0", a["source"])


class PrecheckAndHistoryTests(AssistantData):
    """CHAT-02 kiểm tra sơ bộ (luật cố định) · CHAT-06 lịch sử hiến · CHAT-07 ngày hiến tiếp."""

    def test_parse_profile(self):
        self.assertEqual(rules.parse_profile("Tôi 20 tuổi, nặng 48kg có hiến được không?"),
                         {"age": 20, "weight_kg": 48.0, "gender": None})
        self.assertEqual(rules.parse_profile("con gái 19 tuổi 43,5 kg")["gender"], "female")
        self.assertEqual(rules.parse_profile("tôi ở Quảng Nam 25 tuổi")["gender"], None)   # "Nam" trong địa danh
        self.assertEqual(rules.detect_intent("Tôi 20 tuổi, nặng 48kg có hiến được không?"), "precheck")

    def test_precheck_outcomes_never_conclude(self):
        c = Ctx(user=None)
        r = tools.preliminary_check(c, age=20, weight_kg=48)
        self.assertEqual(r["summary"], "within_reference" if not r["missing"] else "need_more_info")
        self.assertTrue(all(x["within"] for x in r["checks"]))
        r = tools.preliminary_check(c, age=17, weight_kg=60)
        self.assertEqual(r["summary"], "outside_reference")
        r = tools.preliminary_check(c, age=30, weight_kg=43)                  # giữa ngưỡng nữ 42 và nam 45
        self.assertIn("giới tính (ngưỡng cân nặng nam và nữ khác nhau)", r["missing"])
        self.assertEqual(tools.preliminary_check(c, age=30, weight_kg=43, gender="female")["checks"][1]["within"], True)
        self.assertEqual(tools.preliminary_check(c, age=30, weight_kg=43, gender="male")["checks"][1]["within"], False)
        a = rules.answer("Tôi 20 tuổi, nặng 48kg có hiến được không?", Ctx(user=None))
        self.assertIn("ngưỡng tham khảo", a["answer"])
        self.assertIn("KHÔNG phải kết luận", a["answer"])
        self.assertNotIn("đủ điều kiện hiến", a["answer"].replace("KHÔNG phải kết luận đủ điều kiện", ""))
        a = rules.answer("tôi nặng 43kg hiến máu được không", Ctx(user=None))
        self.assertIn("cho mình biết thêm", a["answer"])                     # thiếu thông tin → hỏi lại

    def test_precheck_uses_profile_and_interval_for_member(self):
        self.donor.date_of_birth = date(2000, 1, 1)
        self.donor.gender = "male"
        self.donor.save()
        r = tools.preliminary_check(Ctx(user=self.donor), weight_kg=60)
        crit = {x["criterion"]: x for x in r["checks"]}
        self.assertTrue(crit["Tuổi"]["within"])
        self.assertFalse(crit["Khoảng nghỉ từ lần hiến trước"]["within"])     # hiến 30 ngày trước
        self.assertEqual(r["summary"], "outside_reference")

    def test_history_counts_only_confirmed(self):
        donate(self.hc, self.staff_user, self.donor, 200)
        d = donate(self.hc, self.staff_user, self.donor, 300)
        from bloodbank.services import donations as don

        don.void_donation(self.staff_user.staffs.get(), d.pk, "Ghi nhầm", "not_donated")
        h = tools.my_donation_history(Ctx(user=self.donor))
        self.assertEqual((h["confirmed_count"], h["whole_blood_ml"]), (2, 700))
        a = rules.answer("Tôi đã hiến máu bao nhiêu lần?", Ctx(user=self.donor))
        self.assertIn("Bạn đã hiến 2 lần", a["answer"])
        self.assertTrue(tools.my_donation_history(Ctx(user=None))["login_required"])


class VerifyTests(TestCase):
    def test_unknown_codes_rejected_and_overclaim_gets_disclaimer(self):
        with self.assertRaises(verify.Unverified):
            verify.check("Đơn DK-000999 đã được duyệt.", "dữ liệu chỉ có DK-000015")
        self.assertEqual(verify.check("Đơn DK-000015 đã duyệt.", '{"code": "DK-000015"}'), "Đơn DK-000015 đã duyệt.")
        out = verify.check("Với 50kg bạn đủ điều kiện hiến.", "")
        self.assertIn("bác sĩ khám sàng lọc", out)


@override_settings(ANTHROPIC_API_KEY="test-key", CHATBOT_USE_LLM=True, CHATBOT_EFFORT="")
class LLMRagTests(AssistantData):
    def test_retrieved_docs_injected_without_extra_search_round(self):
        client = mock.Mock()
        client.messages.create.side_effect = [fake_response([text("Hiến máu đúng quy trình là an toàn. "
                                                                  "(Nguồn: Hiến máu có an toàn..., phiên bản 1.0)")])]
        with mock.patch.object(llm, "client", return_value=client):
            res = llm.ask("Hiến máu có nguy hiểm không?", Ctx())
        first = client.messages.create.call_args_list[0].kwargs
        self.assertIn('<doc id="an-toan"', first["messages"][0]["content"])          # RAG: tài liệu trong lượt hỏi
        self.assertNotIn("output_config", first)                                    # Haiku 4.5: không gửi effort
        self.assertNotIn("search_knowledge", [t["name"] for t in first["tools"]])   # đã có tài liệu → 1 lần gọi
        self.assertEqual(client.messages.create.call_count, 1)
        self.assertEqual(res["doc_ids"][0], "an-toan")

    def test_follow_up_without_docs_can_search(self):
        client = mock.Mock()
        client.messages.create.side_effect = [
            fake_response([tool_use("search_knowledge", {"query": "chế phẩm tiểu cầu"})], "tool_use"),
            fake_response([text("Tiểu cầu giúp cầm máu. (Nguồn: Các loại chế phẩm máu, phiên bản 1.0)")]),
        ]
        with mock.patch.object(llm, "client", return_value=client):
            res = llm.ask("còn cái kia thì sao", Ctx(), docs=[])
        first = client.messages.create.call_args_list[0].kwargs
        self.assertIn("search_knowledge", [t["name"] for t in first["tools"]])
        self.assertIn("che-pham", res["doc_ids"])
        self.assertIn("Tiểu cầu", res["evidence"])

    def test_prefetched_data_injected_and_cards_returned(self):
        from bloodbank.assistant import rules

        client = mock.Mock()
        client.messages.create.side_effect = [fake_response([text("Có 1 đợt ở Tam Kỳ, chi tiết ở bên dưới.")])]
        pre = rules.prefetch("có đợt hiến nào ở Tam Kỳ không", Ctx())
        with mock.patch.object(llm, "client", return_value=client):
            res = llm.ask("có đợt hiến nào ở Tam Kỳ không", Ctx(), docs=[], prefetched=pre[1:])
        content = client.messages.create.call_args_list[0].kwargs["messages"][0]["content"]
        self.assertIn("DỮ LIỆU HỆ THỐNG ĐÃ TRA CỨU SẴN", content)
        self.assertIn("Đợt Tam Kỳ", content)
        self.assertEqual(client.messages.create.call_count, 1)                    # không cần vòng gọi công cụ
        self.assertEqual([c["name"] for c in res["cards"]], ["Đợt Tam Kỳ"])

    def test_incomplete_answer_falls_back(self):
        client = mock.Mock()
        client.messages.create.side_effect = [fake_response([text("Mình kiểm tra đơn đăng ký của bạn.")])]
        self.client.force_login(self.newbie)
        with mock.patch.object(llm, "client", return_value=client):
            r = self.client.post(reverse("bloodbank:api_chat_message"), {"message": "Tôi đã đăng ký hiến máu ngày nào?"}).json()
        self.assertEqual(r["mode"], "rules")
        self.assertIn("Đợt Thanh Khê chiều", r["answer"])

    def test_fabricated_code_falls_back_to_rules(self):
        client = mock.Mock()
        client.messages.create.side_effect = [fake_response([text("Đơn DK-123456 của bạn đã duyệt.")])]
        self.client.force_login(self.newbie)
        with mock.patch.object(llm, "client", return_value=client):
            r = self.client.post(reverse("bloodbank:api_chat_message"), {"message": "đơn đăng ký của tôi"}).json()
        self.assertEqual(r["mode"], "rules")
        self.assertNotIn("DK-123456", r["answer"])
        self.assertIn("Đợt Thanh Khê chiều", r["answer"])


@override_settings(ANTHROPIC_API_KEY="")
class ConversationAndApiTests(AssistantData):
    def post(self, message, **extra):
        return self.client.post(reverse("bloodbank:api_chat_message"), {"message": message, **extra})

    def test_member_conversation_persisted_and_continued(self):
        self.client.force_login(self.newbie)
        r1 = self.post("Quy trình hiến máu gồm mấy bước?").json()
        cid = r1["conversation_id"]
        self.assertIsNotNone(cid)
        r2 = self.post("đơn đăng ký của tôi", conversation_id=cid).json()
        self.assertEqual(r2["conversation_id"], cid)
        conv = ChatConversation.objects.get(pk=cid)
        self.assertEqual((conv.user, conv.messages.count()), (self.newbie, 4))
        lst = self.client.get(reverse("bloodbank:api_conversations")).json()["conversations"]
        self.assertEqual([c["id"] for c in lst], [cid])
        detail = self.client.get(reverse("bloodbank:api_conversation", args=[cid])).json()
        self.assertEqual([m["role"] for m in detail["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertIn("4 bước", detail["messages"][1]["text"])

    def test_cannot_read_or_continue_other_users_conversation(self):
        conv = ChatConversation.objects.create(user=self.other, title="Riêng tư")
        ChatMessage.objects.create(conversation=conv, role="user", text="bí mật")
        self.client.force_login(self.newbie)
        self.assertEqual(self.client.get(reverse("bloodbank:api_conversation", args=[conv.pk])).status_code, 404)
        r = self.client.delete(reverse("bloodbank:api_conversation", args=[conv.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.post("xin chào", conversation_id=conv.pk).status_code, 404)
        self.assertEqual(conv.messages.count(), 1)
        self.assertEqual(self.client.get(reverse("bloodbank:api_conversations")).json()["conversations"], [])

    def test_delete_own_conversation_and_retention(self):
        self.client.force_login(self.newbie)
        cid = self.post("quy trình hiến máu").json()["conversation_id"]
        self.assertEqual(self.client.delete(reverse("bloodbank:api_conversation", args=[cid])).json(), {"deleted": True})
        self.assertFalse(ChatConversation.objects.filter(pk=cid).exists())
        old = ChatConversation.objects.create(user=self.newbie, title="cũ")
        ChatConversation.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=31))
        fresh = ChatConversation.objects.create(user=self.newbie, title="mới")
        self.assertEqual(service.purge_old_conversations(), 1)
        self.assertEqual(list(ChatConversation.objects.values_list("pk", flat=True)), [fresh.pk])

    def test_anonymous_not_persisted(self):
        r = self.post("quy trình hiến máu").json()
        self.assertIsNone(r["conversation_id"])
        self.assertFalse(ChatConversation.objects.exists())

    def test_personal_apis_auth_and_scoping(self):
        urls = [reverse("bloodbank:api_my_history"), reverse("bloodbank:api_my_eligibility"),
                reverse("bloodbank:api_my_registrations")]
        for url in urls:                                                     # khách → 401 JSON
            r = self.client.get(url)
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "ERR-AUTH-UNAUTHENTICATED"))
        self.client.force_login(self.staff_user)                             # không phải Người dùng → 403
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.donor)
        h = self.client.get(urls[0]).json()
        self.assertEqual(h["confirmed_count"], 1)
        e = self.client.get(urls[1], {"age": "25", "weight_kg": "55", "gender": "female"}).json()
        self.assertEqual(e["next_eligible"]["days_left"], 54)
        self.assertEqual(e["preliminary"]["summary"], "outside_reference")    # khoảng nghỉ chưa đủ
        self.assertEqual(self.client.get(urls[1], {"age": "abc"}).status_code, 400)
        self.client.force_login(self.newbie)
        regs = self.client.get(urls[2]).json()["registrations"]
        self.assertEqual([r["campaign"] for r in regs], ["Đợt Thanh Khê chiều"])
        # Tham số lạ không đổi được người được tra cứu
        self.assertEqual(self.client.get(urls[2], {"user_id": self.donor.pk}).json()["registrations"][0]["campaign"],
                         "Đợt Thanh Khê chiều")

    def test_campaign_api_public_with_filters(self):
        r = self.client.get(reverse("bloodbank:api_campaigns"), {"area": "Tam Kỳ"}).json()
        self.assertEqual([c["name"] for c in r["campaigns"]], ["Đợt Tam Kỳ"])
        r = self.client.get(reverse("bloodbank:api_campaigns"), {"time_of_day": "afternoon", "limit": "abc"}).json()
        self.assertEqual([c["name"] for c in r["campaigns"]], ["Đợt Thanh Khê chiều"])

    def test_post_requires_csrf(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse("bloodbank:api_chat_message"), {"message": "hi"}).status_code, 403)

    def test_json_body_supported(self):
        r = self.client.post(reverse("bloodbank:api_chat_message"), json.dumps({"message": "quy trình hiến máu"}),
                             content_type="application/json").json()
        self.assertIn("4 bước", r["answer"])

    def test_campaign_question_without_location_asks_back(self):
        a = rules.answer("có đợt hiến nào không", Ctx(user=None))
        self.assertIn("tỉnh/quận nào", a["answer"])
        a = rules.answer("có đợt hiến nào không", Ctx(user=self.donor))       # hồ sơ có tỉnh → không hỏi
        self.assertNotIn("tỉnh/quận nào", a["answer"])

    def setUp(self):
        super().setUp()
        cache.clear()
