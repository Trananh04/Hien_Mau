"""Trợ lý đáp câu giao tiếp thường ngày như người thật (không báo "ngoài phạm vi"), câu có nội dung vẫn đi tra cứu."""
from django.test import SimpleTestCase

from bloodbank.assistant import smalltalk


class SmalltalkTests(SimpleTestCase):
    def test_everyday_phrases_get_a_human_reply(self):
        for q in ["hi", "Hello", "xin chào", "chào bạn!", "alo", "cảm ơn nhé", "thanks", "tạm biệt",
                  "bạn là ai?", "bạn giúp được gì", "ok", "dạ", "bạn khỏe không"]:
            res = smalltalk.reply(q)
            self.assertIsNotNone(res, q)
            self.assertNotIn("nằm ngoài", res["answer"], q)

    def test_questions_with_content_are_not_smalltalk(self):
        for q in ["chào bạn, tôi muốn hiến máu ở Đà Nẵng", "cảm ơn, khi nào tôi hiến lại được",
                  "hiến máu có đau không", "giá vàng hôm nay"]:
            self.assertIsNone(smalltalk.reply(q), q)
