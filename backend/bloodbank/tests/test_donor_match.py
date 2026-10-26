"""Gợi ý người hiến: lọc cứng, chấm điểm, bán kính, hiệu quả kêu gọi, số người nên mời."""
from datetime import date, timedelta
from decimal import Decimal

from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bloodbank.models import Donation, DonorCallout, Notification
from bloodbank.services import donor_match

from . import factories as f


def donate(donor, hosp, staff_user, days_ago, lab_group=None, campaign=None):
    camp = campaign or f.campaign(hosp, status="completed", start_offset_h=-24 * days_ago - 2)
    reg = f.registration(camp, donor, status="donated")
    extra = {}
    if lab_group:
        extra = {"lab_status": "passed", "lab_blood_group": lab_group, "lab_checked_at": timezone.now(),
                 "lab_checked_by": staff_user}
    return Donation.objects.create(donor=donor, registration=reg, hospital=hosp, volume_ml=350,
                                   donated_at=timezone.now() - timedelta(days=days_ago), confirmed_by=staff_user, **extra)


class SuggestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital(province="Đà Nẵng", latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        cls.other_h = f.hospital(province="Đà Nẵng")
        cls.staff_user = f.staff(cls.h)

    def mk(self, **kw):
        return f.user(**{"blood_group": "A+", "province": "Đà Nẵng", **kw})

    def ids(self, **kw):
        return [r["user_id"] for r in donor_match.suggest(self.h, "A+", **kw)]

    def test_lab_group_overrides_self_declared(self):
        declared_a_lab_b = self.mk()
        donate(declared_a_lab_b, self.h, self.staff_user, 200, lab_group="B+")
        declared_o_lab_a = self.mk(blood_group="O+")
        donate(declared_o_lab_a, self.h, self.staff_user, 200, lab_group="A+")
        got = self.ids()
        self.assertNotIn(declared_a_lab_b.pk, got)
        self.assertIn(declared_o_lab_a.pk, got)

    def test_age_rest_interval_and_cross_hospital_cooldown(self):
        too_young = self.mk(date_of_birth=date.today().replace(year=date.today().year - 16))
        rested = self.mk()
        donate(rested, self.h, self.staff_user, 100)
        not_rested = self.mk()
        donate(not_rested, self.h, self.staff_user, 40)
        invited_elsewhere = self.mk()
        callout = DonorCallout.objects.create(hospital=self.other_h, blood_group="A+", created_by=self.staff_user,
                                              recipient_count=1)
        Notification.objects.create(user=invited_elsewhere, type="donor_callout", title="Cần máu",
                                    entity_type="donor_callouts", entity_id=callout.pk)
        got = self.ids()
        self.assertIn(rested.pk, got)
        for u in (too_young, not_rested, invited_elsewhere):
            self.assertNotIn(u.pk, got)

    def test_experienced_reliable_near_donor_ranks_first_with_reasons(self):
        newcomer = self.mk()
        regular = self.mk()
        near = f.campaign(self.h, status="completed", start_offset_h=-24 * 300,
                          latitude=Decimal("16.060"), longitude=Decimal("108.210"))
        donate(regular, self.h, self.staff_user, 300, lab_group="A+", campaign=near)
        donate(regular, self.h, self.staff_user, 150, lab_group="A+")
        rows = donor_match.suggest(self.h, "A+")
        self.assertEqual([r["user_id"] for r in rows], [regular.pk, newcomer.pk])
        top = rows[0]
        self.assertIsNotNone(top["distance_km"])
        self.assertEqual(top["reasons"][0], "Đúng nhóm A+ (đã xét nghiệm)")
        self.assertIn("đã nghỉ đủ 150 ngày", top["reasons"])
        self.assertIn("(đường chim bay)", top["reasons"][1])           # chưa cấu hình Goong → đường chim bay
        self.assertIn("từng hiến tại bệnh viện này", top["reasons"])
        self.assertTrue(rows[1]["first_time"])
        # Lọc 10 km: người chưa có vị trí bị loại
        self.assertEqual(self.ids(radius_km=10), [regular.pk])

    def test_codes_are_stable_per_hospital_and_differ_across_hospitals(self):
        u = self.mk()
        self.assertEqual(donor_match.donor_code(self.h, u.pk), donor_match.donor_code(self.h, u.pk))
        self.assertNotEqual(donor_match.donor_code(self.h, u.pk), donor_match.donor_code(self.other_h, u.pk))


class FairRankingTests(TestCase):
    """Quãng đường đi thật, ưu tiên người từng nhận lời kêu gọi, chia đều lượt gọi."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital(province="Đà Nẵng", latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        cls.staff_user = f.staff(cls.h)

    def mk(self, **kw):
        return f.user(**{"blood_group": "A+", "province": "Đà Nẵng", **kw})

    def invite(self, user, days_ago, hospital=None):
        c = DonorCallout.objects.create(hospital=hospital or self.h, blood_group="A+", created_by=self.staff_user,
                                        recipient_count=1)
        n = Notification.objects.create(user=user, type="donor_callout", title="Cần máu", entity_type="donor_callouts",
                                        entity_id=c.pk)
        Notification.objects.filter(pk=n.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return c

    def test_donor_who_answered_callouts_ranks_above_one_who_ignored(self):
        answered, ignored = self.mk(), self.mk()
        for u in (answered, ignored):
            donate(u, self.h, self.staff_user, 200)
            self.invite(u, 120)
        # Người thứ nhất đăng ký đợt hiến của bệnh viện 2 ngày sau lời mời → tính là đã nhận lời
        camp = f.campaign(self.h, status="completed", start_offset_h=-24 * 110)
        reg = f.registration(camp, answered, status="donated")
        reg.__class__.objects.filter(pk=reg.pk).update(registered_at=timezone.now() - timedelta(days=118))
        rows = {r["user_id"]: r for r in donor_match.suggest(self.h, "A+")}
        self.assertEqual((rows[answered.pk]["asked"], rows[answered.pk]["answered"]), (1, 1))
        self.assertEqual((rows[ignored.pk]["asked"], rows[ignored.pk]["answered"]), (1, 0))
        self.assertIn("nhận lời 1/1 lần kêu gọi", rows[answered.pk]["reasons"])
        self.assertGreater(rows[answered.pk]["score"], rows[ignored.pk]["score"])

    def test_calls_are_spread_out(self):
        often, never = self.mk(), self.mk()
        for u in (often, never):
            donate(u, self.h, self.staff_user, 200)
        for days in (20, 40, 60):
            self.invite(often, days)
        rows = donor_match.suggest(self.h, "A+")
        self.assertEqual([r["user_id"] for r in rows], [never.pk, often.pk])     # ít bị gọi → lên trước
        self.assertIn("được gọi 3 lần trong 90 ngày", rows[1]["reasons"])
        self.invite(often, 80)                                                     # lần thứ 4 trong 90 ngày → tạm loại
        self.assertEqual([r["user_id"] for r in donor_match.suggest(self.h, "A+")], [never.pk])

    @override_settings(GOONG_API_KEY="test-api")
    def test_uses_road_distance_and_caches_it(self):
        cache.clear()
        u = self.mk()
        spot = f.campaign(self.h, status="completed", start_offset_h=-24 * 200,
                          latitude=Decimal("16.060"), longitude=Decimal("108.210"))
        donate(u, self.h, self.staff_user, 200, campaign=spot)
        road = [{"meters": 3240, "seconds": 600, "distance": "3.24 km", "duration": "10 phút"}]
        with mock.patch("bloodbank.services.geocode.distances", return_value=road) as call:
            row = donor_match.suggest(self.h, "A+")[0]
            donor_match.suggest(self.h, "A+")
        self.assertEqual(call.call_count, 1)                     # điểm đợt hiến công khai → lưu cache
        self.assertEqual(row["distance_km"], 3.2)
        self.assertTrue(row["road"])
        self.assertIn("cách 3,2 km đường đi", row["reasons"])
        self.assertEqual(row["parts"][0]["label"], "Gần bệnh viện (đường đi)")


class ResponseStatsTests(TestCase):
    def test_counts_registrations_within_window_and_suggests_invite_count(self):
        h = f.hospital()
        staff_user = f.staff(h)
        came, ignored = f.user(), f.user()
        callout = DonorCallout.objects.create(hospital=h, blood_group="O+", created_by=staff_user, recipient_count=2)
        DonorCallout.objects.filter(pk=callout.pk).update(created_at=timezone.now() - timedelta(days=10))
        for u in (came, ignored):
            Notification.objects.create(user=u, type="donor_callout", title="Cần máu", entity_type="donor_callouts",
                                        entity_id=callout.pk)
        reg = f.registration(f.campaign(h, start_offset_h=48), came)
        type(reg).objects.filter(pk=reg.pk).update(registered_at=timezone.now() - timedelta(days=8))

        stats = donor_match.response_stats(h)
        self.assertEqual((stats["sent"], stats["responded"]), (2, 1))
        self.assertEqual(stats["rate"], 0.5)
        self.assertTrue(stats["last"]["done"])
        self.assertEqual(donor_match.suggested_count(3, stats["rate"]), 6)
        self.assertEqual(donor_match.suggested_count(3, None), 10)       # mặc định 30%
        self.assertEqual(donor_match.suggested_count(100, 0.3), donor_match.MAX_SEND)
        self.assertEqual(donor_match.suggested_count(0, 0.5), 0)


class HanoiDistanceTests(TestCase):
    """Dữ liệu mẫu Hà Nội (lệnh seed_hanoi_demo): khoảng cách thật tới bệnh viện và lọc theo bán kính."""

    @classmethod
    def setUpTestData(cls):
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_hanoi_demo", stdout=StringIO())
        from bloodbank.models import Hospital

        cls.h = Hospital.objects.get(code="BVM-HN1")

    def test_distances_match_known_values(self):
        # Đống Đa → Ba Vì ≈ 46,7 km; → Cầu Giấy ≈ 4,4 km (tọa độ trung tâm quận gần đúng)
        self.assertAlmostEqual(donor_match._km(self.h.latitude, self.h.longitude, "21.1990", "105.4230"), 46.7, delta=0.2)
        self.assertAlmostEqual(donor_match._km(self.h.latitude, self.h.longitude, "21.0330", "105.7900"), 4.4, delta=0.2)

    def test_radius_filter_and_exclusions(self):
        from accounts.models import User

        everyone = donor_match.suggest(self.h, "O+")
        for radius in donor_match.RADIUS_CHOICES:
            got = donor_match.suggest(self.h, "O+", radius)
            self.assertTrue(got)
            self.assertTrue(all(r["distance_km"] is not None and r["distance_km"] <= radius for r in got))
            self.assertLessEqual(len(got), len(everyone))
        ids = {r["user_id"] for r in everyone}
        members = User.objects.filter(email__startswith="hn.demo", blood_group="O+")
        self.assertEqual(len(ids), members.count() - 2)        # 1 người vừa hiến 40 ngày + 1 người 61 tuổi bị loại
        # Cùng hồ sơ thân thiết: người gần bệnh viện đứng trên người xa
        loyal = [r for r in everyone if r["donations"] == 3 and r["verified"]]
        self.assertEqual([r["distance_km"] for r in loyal], sorted(r["distance_km"] for r in loyal))


class UrgencyTests(TestCase):
    """Hai trường hợp thiếu máu: KHẨN (cần trong vài giờ) và THIẾU KHO — phân loại, nút xử lý, kêu gọi khẩn."""

    @classmethod
    def setUpTestData(cls):
        from bloodbank.services import inventory as inv
        from bloodbank.services import patients as prq

        cls.h = f.hospital(province="Đà Nẵng", latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        cls.staff_user = f.staff(cls.h)
        cls.staff = cls.staff_user.staffs.get()
        rbc = f.spec()
        now = timezone.now()
        inv.save_demand(cls.staff, {"blood_group": "O+", "product_spec_id": rbc.pk, "required_quantity": 3,
                                    "needed_by": now + timedelta(hours=6)})
        inv.save_demand(cls.staff, {"blood_group": "A+", "product_spec_id": rbc.pk, "required_quantity": 4,
                                    "needed_by": now + timedelta(days=5)})
        cls.requester = f.user()
        p = prq.submit(cls.requester, {"consent": True, "hospital_id": cls.h.pk, "quantity_units": 2, "blood_group": "B+",
                                       "blood_product_id": f.spec().product_id,
                                       "contact_name": "Người nhà", "contact_phone": "0905123456"})
        cls.prq = prq.hospital_action(cls.staff, p.pk, "verify", {"blood_group": "B+"})
        # Người hiến O+: một người gần (~1 km) hiến 1 lần; một người xa (~20 km) đã hiến 5 lần
        cls.near = f.user(blood_group="O+", province="Đà Nẵng")
        cls.far = f.user(blood_group="O+", province="Đà Nẵng")
        donate(cls.near, cls.h, cls.staff_user, 200, campaign=f.campaign(
            cls.h, status="completed", start_offset_h=-24 * 200 - 2, latitude=Decimal("16.060"), longitude=Decimal("108.210")))
        for days in (700, 550, 400, 250, 100):
            donate(cls.far, cls.h, cls.staff_user, days, campaign=f.campaign(
                cls.h, status="completed", start_offset_h=-24 * days - 2, latitude=Decimal("16.230"),
                longitude=Decimal("108.202")))

    def test_classification(self):
        from bloodbank.services import inventory as inv

        rows = {r["blood_group"]: r for r in inv.shortages(self.h)}
        self.assertTrue(rows["O+"]["urgent"])
        self.assertFalse(rows["A+"]["urgent"])
        self.assertEqual(inv.shortages(self.h)[0]["blood_group"], "O+")          # khẩn xếp đầu
        urgent = inv.urgent_requests(self.h)
        self.assertEqual([(u["prq"].pk, u["remaining"], u["covered"]) for u in urgent], [(self.prq.pk, 2, False)])

    def test_demands_screen_is_forecast_not_emergency(self):
        """Trang Dự báo: nhu cầu có kế hoạch vượt tồn trong 7 ngày → sắp hết → mời người hiến (đúng số thiếu)."""
        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:demands"))
        levels = {(x["blood_group"]): x["level"] for x in r.context["rows"]}
        self.assertEqual((levels["O+"], levels["A+"]), ("soon", "soon"))
        self.assertContains(r, "Dự báo thiếu hụt")
        self.assertContains(r, "thieu=3")                       # mời người hiến cho đúng 3 đơn vị thiếu (O+)
        self.assertNotContains(r, "Xin liên viện")
        self.assertNotContains(r, self.prq.request_code)        # ca khẩn / yêu cầu khẩn không nằm ở trang dự báo
        r = self.client.get(reverse("bloodbank:hospital_dashboard"))
        self.assertContains(r, "Thiếu máu khẩn")
        self.assertEqual({k["label"]: k["count"] for k in r.context["kpis"]}["Sắp thiếu (7 ngày)"], 2)

    def test_urgent_mode_ranks_near_first_and_defaults_to_10km(self):
        stock = [r["user_id"] for r in donor_match.suggest(self.h, "O+")]
        urgent = [r["user_id"] for r in donor_match.suggest(self.h, "O+", mode="urgent")]
        self.assertEqual(stock, [self.far.pk, self.near.pk])        # thiếu kho: người hiến nhiều lần lên trước
        self.assertEqual(urgent, [self.near.pk, self.far.pk])       # khẩn: người gần lên trước
        self.client.force_login(self.staff_user)
        r = self.client.get(reverse("bloodbank:donor_suggest") + "?blood_group=O-&mode=urgent")
        self.assertEqual(r.context["radius"], 10)
        r = self.client.get(reverse("bloodbank:donor_suggest") + "?blood_group=O%2B&mode=urgent&radius=all")
        self.assertIsNone(r.context["radius"])
        self.assertEqual(len(r.context["rows"]), 2)
        self.assertEqual(r.context["shortage"], 3)
        self.assertEqual(donor_match.suggested_count(3, None, "urgent"), 20)   # 3 ÷ 15%

    def test_urgent_callout_invites_to_hospital_today_and_uses_short_cooldown(self):
        from bloodbank.models import AuditLog
        from bloodbank.services import callout

        code = donor_match.donor_code(self.h, self.near.pk)
        n, campaign, skipped = callout.donor_callout(self.staff, "O+", [code], None, mode="urgent")
        self.assertEqual((n, campaign, skipped), (1, None, 0))
        note = Notification.objects.get(user=self.near, channel="in_app")
        self.assertTrue(note.title.startswith("[Khẩn]"))
        self.assertIn("hôm nay", note.body)
        self.assertEqual(AuditLog.objects.get(action="donor_callout").new_values["mode"], "urgent")
        # 4 ngày sau: hết thời gian chờ khẩn (3 ngày) nhưng chưa hết thời gian chờ thường (7 ngày)
        later = timezone.now() + timedelta(days=4)
        self.assertIn(self.near.pk, [r["user_id"] for r in donor_match.suggest(self.h, "O+", now=later, mode="urgent")])
        self.assertNotIn(self.near.pk, [r["user_id"] for r in donor_match.suggest(self.h, "O+", now=later)])


class MemberNotificationLinkTests(TestCase):
    """Thông báo của người dùng luôn mở trang của người dùng (lỗi cũ: 'đủ điều kiện hiến lại' trỏ tới trang bệnh viện → 403)."""

    def test_eligible_again_opens_member_page_and_invitation_page_works(self):
        from bloodbank.services import callout

        h = f.hospital(province="Đà Nẵng", latitude=Decimal("16.054"), longitude=Decimal("108.202"), phone="0236111222")
        staff_user = f.staff(h)
        donor = f.user(blood_group="O+", province="Đà Nẵng")
        d = donate(donor, h, staff_user, 120)
        Notification.objects.create(user=donor, type="eligible_again", title="Bạn có thể hiến lại",
                                    entity_type="donations", entity_id=d.pk)
        callout.donor_callout(staff_user.staffs.get(), "O+", [donor_match.donor_code(h, donor.pk)], mode="urgent")
        self.client.force_login(donor)
        r = self.client.get(reverse("bloodbank:notifications"))
        self.assertContains(r, reverse("bloodbank:my_donation_detail", args=[d.pk]))
        self.assertNotContains(r, "/benh-vien/luot-hien/")
        invite = Notification.objects.get(user=donor, type="donor_callout", channel="in_app")
        url = reverse("bloodbank:my_invitation", args=[invite.entity_id])
        self.assertContains(r, url)
        r = self.client.get(url)
        self.assertContains(r, "Gọi bệnh viện")
        self.assertContains(r, "destination=16.054")
        # Người không được mời không xem được lời mời
        self.client.force_login(f.user())
        self.assertEqual(self.client.get(url).status_code, 404)



class PublicMapTests(TestCase):
    def test_map_data_has_campaign_times_and_no_user_location(self):
        h = f.hospital(latitude=Decimal("16.054"), longitude=Decimal("108.202"))
        live = f.campaign(h, start_offset_h=-1)
        later = f.campaign(h, start_offset_h=72)
        data = self.client.get(reverse("bloodbank:map_data")).json()
        camps = {c["id"]: c for c in data["campaigns"]}
        self.assertTrue(camps[live.pk]["live"])
        self.assertFalse(camps[later.pk]["live"])
        self.assertIn("start", camps[later.pk])
        self.assertIn("end", camps[later.pk])
        self.assertNotIn("needs", data["hospitals"][0])
        r = self.client.get(reverse("bloodbank:map"))
        self.assertContains(r, "Tìm nơi gần tôi")
        self.assertContains(r, "7 ngày tới")
