"""Khu làm việc bệnh viện: cảnh báo kho trên Tổng quan, thanh bên thu gọn được, cột thao tác của bảng."""
from django.test import TestCase
from django.urls import reverse

from bloodbank.models import Demand, Stock
from bloodbank.services import inventory as inv

from . import factories as f


class StockAlertTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff = f.staff(cls.h)
        cls.rbc = f.spec()

    def test_alerts_use_available_not_on_hand_and_merge_by_key(self):
        # Hiện có 10 nhưng giữ chỗ 8 → khả dụng 2 < tối thiểu 5 → cảnh báo "dưới tối thiểu", thiếu 3
        Stock.objects.create(hospital=self.h, blood_group="O+", product_spec=self.rbc,
                             quantity_on_hand=10, quantity_reserved=8, min_stock_level=5)
        # Nhu cầu 6 đơn vị A- nhưng không có tồn → "thiếu theo nhu cầu", đứng trước
        Demand.objects.create(hospital=self.h, blood_group="A-", product_spec=self.rbc, required_quantity=6)
        a = inv.stock_alerts(self.h)
        self.assertEqual([(r["blood_group"], r["level"], r["available"], r["shortage"]) for r in a["rows"]],
                         [("A-", "danger", 0, 6), ("O+", "warn", 2, 3)])
        self.assertEqual((a["on_hand"], a["reserved"], a["available"]), (10, 8, 2))
        self.assertEqual((a["danger"], a["warn"]), (1, 1))

    def test_dashboard_shows_alerts_requests_and_reads_only(self):
        Demand.objects.create(hospital=self.h, blood_group="A-", product_spec=self.rbc, required_quantity=2)
        self.client.force_login(self.staff)
        r = self.client.get(reverse("bloodbank:hospital_dashboard"))
        self.assertContains(r, "Thiếu theo nhu cầu")
        self.assertContains(r, "Xử lý thiếu hụt")
        self.assertContains(r, "Số liệu lúc")
        self.assertEqual([t["label"] for t in r.context["todo"]], ["Nhu cầu đang thiếu máu"])
        self.assertEqual(Demand.objects.get().status, Demand.Status.ACTIVE)   # mở tổng quan không ghi gì


class SidebarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.staff = f.staff(cls.h)

    def test_groups_collapsible_and_state_rendered_from_cookie(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse("bloodbank:hospital_dashboard")).content.decode()
        self.assertIn('<details class="ws-sec" data-ws-sec="kho-mau" open>', html)
        self.assertNotIn("is-collapsed", html)
        # Nhóm "Kho máu" đã đóng + thanh bên thu nhỏ → máy chủ dựng sẵn đúng trạng thái
        self.client.cookies["ws_closed"] = "kho-mau.lien-vien"
        self.client.cookies["ws_collapsed"] = "1"
        html = self.client.get(reverse("bloodbank:hospital_dashboard")).content.decode()
        self.assertIn('<details class="ws-sec" data-ws-sec="kho-mau">', html)
        self.assertIn('class="ws-shell is-collapsed"', html)
        self.assertIn('aria-pressed="true"', html)
        # Đang ở trang thuộc nhóm đã đóng → nhóm đó vẫn mở để thấy mục hiện tại
        html = self.client.get(reverse("bloodbank:stock")).content.decode()
        self.assertIn('<details class="ws-sec" data-ws-sec="kho-mau" open>', html)

    def test_urgent_group_first_and_pending_badges(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse("bloodbank:hospital_dashboard")).content.decode()
        self.assertLess(html.index('data-ws-sec="nguoi-can-mau"'), html.index('data-ws-sec="hien-mau"'))

    def test_action_cells_use_shared_wrapper(self):
        """Cột thao tác dùng .table-actions → được ghim ở mép phải khi bảng cuộn ngang (laptop/tablet)."""
        from pathlib import Path

        from django.conf import settings

        for name in ("hospital/patient_requests.html", "hospital/support_requests.html", "admin/hospitals.html"):
            self.assertIn('<div class="table-actions">',
                          (Path(settings.BASE_DIR) / "templates" / name).read_text(encoding="utf-8"), name)


class NotificationCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from bloodbank.models import Notification

        cls.h = f.hospital()
        cls.staff = f.staff(cls.h)
        mk = lambda t, title, read=False: Notification.objects.create(  # noqa: E731
            user=cls.staff, type=t, title=title, channel="in_app", delivery_status="sent")
        mk("patient_request_new", "Yêu cầu cần máu mới PR-1")
        mk("offer_accepted", "Bệnh viện B đã chấp thuận")
        mk("staff_assigned", "Bạn được phân công")

    def test_categories_urgent_relative_time(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("bloodbank:notifications"))
        html = r.content.decode()
        self.assertEqual([k for k, _ in r.context["categories"]], ["nguoi-can-mau", "lien-vien", "tai-khoan"])
        self.assertEqual(html.count('<span class="tag danger">Khẩn</span>'), 1)   # chỉ yêu cầu cần máu mới
        self.assertIn("vừa xong</time>", html)
        self.assertEqual(html.count('class="notif-dot"'), 3)

    def test_filter_by_category_keeps_unread_filter(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("bloodbank:notifications") + "?cat=lien-vien&unread=1")
        self.assertEqual([n.title for n in r.context["page"]], ["Bệnh viện B đã chấp thuận"])
        self.assertContains(r, 'href="?cat=lien-vien&amp;unread=1" class="chip-link is-active" aria-current="true"')
        r = self.client.get(reverse("bloodbank:notifications") + "?cat=khong-co")   # giá trị lạ → bỏ qua bộ lọc
        self.assertEqual(len(r.context["page"]), 3)


class AgoFilterTests(TestCase):
    def test_vietnamese_relative_time(self):
        from datetime import timedelta

        from django.utils import timezone

        from bloodbank.templatetags.ui import ago

        now = timezone.now()
        cases = [(timedelta(seconds=20), "vừa xong"), (timedelta(minutes=5), "5 phút trước"),
                 (timedelta(hours=3, minutes=50), "3 giờ trước"), (timedelta(days=6, hours=22), "6 ngày trước"),
                 (timedelta(days=15), "2 tuần trước")]
        for delta, expected in cases:
            self.assertEqual(ago(now - delta, now), expected)
        old = now - timedelta(days=40)
        self.assertEqual(ago(old, now), timezone.localtime(old).strftime("%d/%m/%Y"))
