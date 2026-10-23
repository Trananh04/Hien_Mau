"""Điều hướng bằng HTMX (hx-boost): cấu hình an toàn với CSP, trang có script riêng được tải đầy đủ."""
import json
import re

from django.test import TestCase
from django.urls import reverse

from . import factories as f

HX = {"HTTP_HX_REQUEST": "true", "HTTP_HX_BOOSTED": "true"}


class HtmxTests(TestCase):
    def test_layout_boosts_navigation_with_csp_safe_config(self):
        r = self.client.get(reverse("bloodbank:home"))
        html = r.content.decode()
        self.assertIn('hx-boost="true"', html)
        self.assertIn("vendor/htmx.min.js", html)
        config = json.loads(re.search(r"name=\"htmx-config\" content='([^']+)'", html).group(1))
        self.assertFalse(config["allowEval"])                  # CSP không cho eval
        self.assertFalse(config["includeIndicatorStyles"])     # CSP không cho chèn <style>
        self.assertFalse(config["allowScriptTags"])            # không chạy lại script khi thay <body>
        self.assertIn({"code": ".*", "swap": True}, config["responseHandling"])   # trang lỗi 403/404 vẫn hiện
        self.assertIn("HX-Request", r["Vary"])

    def test_pages_with_own_scripts_are_loaded_in_full(self):
        h = f.hospital(latitude="16.054", longitude="108.202")
        c = f.campaign(h, start_offset_h=48)
        for url in (reverse("bloodbank:map"), reverse("bloodbank:process"),
                    reverse("bloodbank:campaign_detail", args=[c.pk])):
            r = self.client.get(url + "?x=1", **HX)
            self.assertEqual(r["HX-Redirect"], url + "?x=1")
            self.assertEqual(r.content, b"")
            self.assertEqual(self.client.get(url).status_code, 200)   # tải thường: trang đầy đủ

    def test_normal_pages_are_swapped_in_place(self):
        r = self.client.get(reverse("bloodbank:campaigns"), **HX)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("HX-Redirect", r)
        self.assertContains(r, "<body")
