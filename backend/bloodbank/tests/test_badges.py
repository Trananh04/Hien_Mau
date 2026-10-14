"""Huy hiệu theo mốc + nhắc hiến lại khi đủ thời gian nghỉ."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import Donation, Notification

from . import factories as f


def donate(hospital, staff_user, donor, days_ago, donation_type="whole_blood"):
    c = f.campaign(hospital, start_offset_h=-24 * days_ago - 2)
    reg = f.registration(c, donor, status="donated")
    extra = {"volume_ml": 350} if donation_type == "whole_blood" else {
        "component_product": f.spec("PLT", "STANDARD").product, "component_quantity": 1, "component_unit": "unit"}
    return Donation.objects.create(donor=donor, registration=reg, hospital=hospital, donation_type=donation_type,
                                   donated_at=timezone.now() - timedelta(days=days_ago), confirmed_by=staff_user, **extra)


class BadgeTests(TestCase):
    """(5) Huy hiệu theo mốc, tính từ lượt hiến confirmed; nhắc một lần khi đủ thời gian nghỉ."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital(province="Đà Nẵng")
        cls.staff_user = f.staff(cls.h)
        cls.donor = f.user(province="Đà Nẵng")

    def test_milestones(self):
        from bloodbank.services.badges import badges_for

        b = badges_for(0)
        self.assertEqual((b["earned"], b["next"]["count"], b["next"]["remaining"]), ([], 1, 1))
        b = badges_for(4)
        self.assertEqual([x["count"] for x in b["earned"]], [1, 3])
        self.assertEqual((b["next"]["count"], b["next"]["remaining"], b["next"]["progress"]), (5, 1, 50))
        self.assertIsNone(badges_for(40)["next"])

    def test_voided_donation_does_not_count_and_page_shows_badges(self):
        from bloodbank.services import donations as don

        d1 = donate(self.h, self.staff_user, self.donor, 200)
        donate(self.h, self.staff_user, self.donor, 100)
        donate(self.h, self.staff_user, self.donor, 20)
        don.void_donation(self.staff_user.staffs.get(), d1.pk, "Ghi nhầm", "not_donated")
        self.client.force_login(self.donor)
        r = self.client.get(reverse("bloodbank:my_history"))
        self.assertEqual([x["count"] for x in r.context["badges"]["earned"]], [1])  # 2 lượt confirmed
        self.assertContains(r, "Giọt máu đầu tiên")
        e = r.context["eligible"]
        self.assertFalse(e["ready"])
        self.assertEqual(e["days_left"], 64)  # 84 − 20
        self.assertContains(r, "Bạn có thể hiến lại từ")

    def test_eligible_again_reminder_once_with_campaign(self):
        from bloodbank.services.badges import remind_eligible_again

        donate(self.h, self.staff_user, self.donor, 90)
        camp = f.campaign(self.h, start_offset_h=72, name="Đợt tuần sau")
        other = f.user()
        donate(self.h, self.staff_user, other, 30)  # chưa đủ 84 ngày → không nhắc
        self.assertEqual(remind_eligible_again(), 1)
        n = Notification.objects.get(type="eligible_again")
        self.assertEqual(n.user, self.donor)
        self.assertIn(camp.name, n.body)
        self.assertEqual(remind_eligible_again(), 0)  # chỉ nhắc một lần cho mỗi lượt hiến

