"""Dùng được trên toàn quốc: 34 tỉnh/thành hiện hành, nhận tên tỉnh cũ, không còn mặc định Đà Nẵng."""
from django.test import TestCase
from django.urls import reverse

from accounts.forms import RegisterForm
from accounts.provinces import CENTERS, PROVINCES, VIETNAM_CENTER, center_of, normalize_province
from bloodbank.assistant import rules, tools
from bloodbank.assistant.tools import Ctx

from . import factories as f


class ProvinceTests(TestCase):
    def test_34_current_units_everywhere(self):
        self.assertEqual(len(PROVINCES), 34)
        choices = [v for v, _ in RegisterForm().fields["province"].choices if v]
        self.assertEqual(choices, PROVINCES)
        for name in ("Hà Nội", "TP. Hồ Chí Minh", "Cần Thơ", "Lào Cai", "An Giang"):
            self.assertIn(name, PROVINCES)
        for old in ("Quảng Nam", "Bình Dương", "Khác"):
            self.assertNotIn(old, PROVINCES)

    def test_normalize_legacy_and_loose_names(self):
        cases = {"Quảng Nam": "Đà Nẵng", "quang nam": "Đà Nẵng", "Bình Dương": "TP. Hồ Chí Minh",
                 "tp hcm": "TP. Hồ Chí Minh", "HCM": "TP. Hồ Chí Minh", "Thành phố Hồ Chí Minh": "TP. Hồ Chí Minh",
                 "Thừa Thiên Huế": "Huế",
                 "tỉnh Kiên Giang": "An Giang", "Hà Nội": "Hà Nội", "Khác": None, "": None}
        for given, expected in cases.items():
            self.assertEqual(normalize_province(given), expected, given)
        self.assertEqual(center_of("Quảng Nam"), CENTERS["Đà Nẵng"])
        self.assertEqual(center_of(None), VIETNAM_CENTER)

    def test_assistant_understands_old_province_names(self):
        h = f.hospital(name="BV Cần Thơ QA", province="Cần Thơ", district="Ninh Kiều")
        f.campaign(h, start_offset_h=48, name="Đợt Cần Thơ")
        self.assertEqual(rules.extract_area("có đợt hiến nào ở Sóc Trăng không"), "Cần Thơ")
        data = tools.suggest_campaigns(Ctx(user=None), area="Hậu Giang")
        self.assertTrue(data["area_found"])
        self.assertEqual([c["name"] for c in data["campaigns"]], ["Đợt Cần Thơ"])

    def test_no_da_nang_default_for_new_hospital_or_campaign_map(self):
        h = f.hospital(name="BV Hà Nội QA", province="Hà Nội", latitude=None, longitude=None)
        self.client.force_login(f.staff(h))
        r = self.client.get(reverse("bloodbank:hospital_campaign_create"))
        self.assertEqual((r.context["default_lat"], r.context["default_lng"]), CENTERS["Hà Nội"])
