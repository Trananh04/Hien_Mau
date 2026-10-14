"""Kiểm thử đồng thời (race condition) trên PostgreSQL thật.

Mỗi luồng dùng kết nối DB riêng và giao dịch thật (TransactionTestCase), các luồng được thả cùng lúc bằng Barrier —
mô phỏng nhiều người / bấm đúp / gửi lại request cùng lúc. Kiểm tra bất biến dữ liệu sau khi tất cả kết thúc.
"""
import threading
from datetime import timedelta

from django.db import connection
from django.test import TransactionTestCase, tag
from django.utils import timezone

from accounts.services import authenticate_user
from bloodbank.models import AuditLog, Donation, HospitalRequest, Registration, RequestOffer, Stock, StockTxn
from bloodbank.services import campaigns as cmp
from bloodbank.services import donations as don
from bloodbank.services import inventory as inv
from bloodbank.services import lab
from bloodbank.services import transfers as trf
from bloodbank.services.common import BusinessError

from . import factories as f


def run_together(fns):
    """Chạy các hàm cùng lúc; trả về list kết quả (giá trị hoặc exception)."""
    barrier = threading.Barrier(len(fns))
    out = [None] * len(fns)

    def worker(i):
        try:
            barrier.wait(timeout=10)
            out[i] = fns[i]()
        except Exception as exc:  # noqa: BLE001
            out[i] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(fns))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return out


def ok(results):
    return [r for r in results if not isinstance(r, Exception)]


def unexpected(results):
    """Lỗi không phải lỗi nghiệp vụ (vd. deadlock, IntegrityError lọt ra ngoài) → luôn là bug."""
    return [r for r in results if isinstance(r, Exception) and not isinstance(r, BusinessError)]


@tag("concurrency")
class ConcurrencyTests(TransactionTestCase):
    serialized_rollback = True  # giữ dữ liệu danh mục do migration nạp

    def setUp(self):
        self.h = f.hospital()
        self.staff_user = f.staff(self.h)
        self.staff = self.staff_user.staffs.get()
        self.spec = f.spec("RBC", "250ML")

    def stock_with(self, qty, hospital=None, staff=None, bg="O+"):
        txn = inv.receive(staff or self.staff, self.spec.pk, bg, qty, f"recv-{hospital and hospital.pk}-{bg}-{qty}")
        return Stock.objects.get(pk=txn.stock_id)

    def assert_ledger_consistent(self, stock):
        """Chuỗi before/after liên tục và khớp số dư cuối."""
        stock.refresh_from_db()
        running = 0
        for t in StockTxn.objects.filter(stock=stock).order_by("id"):
            self.assertEqual(t.quantity_before, running, f"Sổ kho đứt chuỗi ở phiếu {t.pk}")
            running = t.quantity_after
            self.assertGreaterEqual(running, 0)
        self.assertEqual(running, stock.quantity_on_hand)
        self.assertLessEqual(stock.quantity_reserved, stock.quantity_on_hand)
        self.assertGreaterEqual(stock.quantity_reserved, 0)

    # ------------------------------------------------------------------ Xác thực
    def test_login_lockout_holds_under_concurrent_failures(self):
        """12 lần sai mật khẩu đồng thời → chỉ đúng 5 lần được kiểm tra/ghi nhận, phần còn lại bị khóa."""
        u = f.user(email="race@test.vn", password="MatKhau!2026")
        res = run_together([lambda i=i: authenticate_user("race@test.vn", f"Sai!{i}") for i in range(12)])
        self.assertEqual(unexpected(res), [])
        codes = [r.code for r in res]
        self.assertEqual(AuditLog.objects.filter(entity_id=u.pk, action="login_failed").count(), 5)
        self.assertEqual(codes.count("ERR-AUTH-INVALID-CREDENTIALS"), 5)
        self.assertEqual(codes.count("ERR-AUTH-LOCKED"), 7)
        with self.assertRaises(BusinessError) as ctx:  # mật khẩu đúng cũng bị chặn trong thời gian khóa
            authenticate_user("race@test.vn", "MatKhau!2026")
        self.assertEqual(ctx.exception.code, "ERR-AUTH-LOCKED")

    # ------------------------------------------------------------------ Kho
    def test_concurrent_issues_never_oversell(self):
        """Tồn 10, 8 phiếu xuất 3 đơn vị cùng lúc (khóa thao tác khác nhau) → tối đa 3 phiếu thành công, không âm."""
        stock = self.stock_with(10)
        res = run_together([lambda i=i: inv.issue(self.staff, stock.pk, 3, f"issue-{i}") for i in range(8)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 3)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity_on_hand, 1)
        self.assert_ledger_consistent(stock)

    def test_double_submit_same_key_writes_once(self):
        """Bấm đúp / gửi lại cùng idempotency_key 6 lần cùng lúc → đúng 1 phiếu, các lần sau trả lại phiếu cũ."""
        stock = self.stock_with(5)
        res = run_together([lambda: inv.issue(self.staff, stock.pk, 1, "same-key") for _ in range(6)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(StockTxn.objects.filter(idempotency_key="same-key").count(), 1)
        self.assertEqual(len({r.pk for r in ok(res)}), 1)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity_on_hand, 4)

    def test_concurrent_adjust_and_issue_stay_consistent(self):
        stock = self.stock_with(6)
        fns = [lambda i=i: inv.issue(self.staff, stock.pk, 2, f"mix-i{i}") for i in range(3)]
        fns += [lambda i=i: inv.adjust(self.staff, stock.pk, "decrease", 2, "damaged", None, f"mix-a{i}") for i in range(3)]
        res = run_together(fns)
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 3)
        self.assert_ledger_consistent(stock)

    # ------------------------------------------------------------------ Điều phối liên viện
    def _request_with_offer(self, requester_staff, supplier, qty):
        req = trf.create_request(requester_staff, {"quantity_needed": qty, "product_spec_id": self.spec.pk,
                                                   "blood_group": "O+", "priority": "urgent"}, [(supplier.pk, qty)])
        return RequestOffer.objects.get(request=req, supplier_hospital=supplier)

    def test_two_requests_cannot_over_reserve_supplier_stock(self):
        """BV cấp có 5 khả dụng; 2 bệnh viện xin 5 — chấp thuận cả 2 cùng lúc → chỉ 1 thành công, giữ chỗ ≤ tồn."""
        supplier, sup_staff = self.h, self.staff
        stock = self.stock_with(5)
        a, b = f.hospital(), f.hospital()
        offer_a = self._request_with_offer(f.staff(a).staffs.get(), supplier, 5)
        offer_b = self._request_with_offer(f.staff(b).staffs.get(), supplier, 5)
        res = run_together([lambda o=o: trf.accept_offer(sup_staff, o.pk, 5) for o in (offer_a, offer_b)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 1)
        stock.refresh_from_db()
        self.assertEqual(stock.quantity_reserved, 5)
        self.assert_ledger_consistent(stock)

    def test_two_suppliers_cannot_overcommit_one_request(self):
        """Yêu cầu cần 5; 2 bệnh viện cùng chấp thuận 5 → tổng cam kết không vượt số cần."""
        requester = f.hospital()
        req_staff = f.staff(requester).staffs.get()
        s1, s2 = f.hospital(), f.hospital()
        st1, st2 = f.staff(s1).staffs.get(), f.staff(s2).staffs.get()
        self.stock_with(5, s1, st1)
        self.stock_with(5, s2, st2)
        req = trf.create_request(req_staff, {"quantity_needed": 5, "product_spec_id": self.spec.pk, "blood_group": "O+",
                                             "priority": "urgent"}, [(s1.pk, 5), (s2.pk, 5)])
        o1, o2 = (RequestOffer.objects.get(request=req, supplier_hospital=s) for s in (s1, s2))
        res = run_together([lambda: trf.accept_offer(st1, o1.pk, 5), lambda: trf.accept_offer(st2, o2.pk, 5)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 1)
        self.assertEqual(trf.request_numbers(HospitalRequest.objects.get(pk=req.pk))["committed"], 5)
        self.assertEqual(sum(Stock.objects.filter(hospital__in=[s1, s2]).values_list("quantity_reserved", flat=True)), 5)

    def test_receive_and_failure_report_race(self):
        """Hàng đang chuyển: bên nhận xác nhận và bên cấp báo thất bại cùng lúc → chỉ 1 kết quả cuối, kho khớp."""
        requester = f.hospital()
        req_staff = f.staff(requester).staffs.get()
        stock = self.stock_with(4)
        offer = self._request_with_offer(req_staff, self.h, 4)
        trf.accept_offer(self.staff, offer.pk, 4)
        trf.dispatch_offer(self.staff, offer.pk, "disp-1")
        res = run_together([lambda: trf.confirm_received(req_staff, offer.pk, 4, "recv-final"),
                            lambda: trf.report_failure(self.staff, offer.pk, "Xe hỏng", 4, "fail-final")])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 1)
        offer.refresh_from_db()
        self.assertIn(offer.status, ("completed", "failed"))
        stock.refresh_from_db()
        got = Stock.objects.filter(hospital=requester).values_list("quantity_on_hand", flat=True).first() or 0
        self.assertEqual(stock.quantity_on_hand + got, 4, "Tổng số đơn vị hai bên phải bằng số ban đầu")
        self.assert_ledger_consistent(stock)

    # ------------------------------------------------------------------ Lượt hiến / đăng ký
    def _attended_reg(self):
        camp = f.campaign(self.h, start_offset_h=-2)
        return f.registration(camp, f.user(blood_group="O+"), status="attended")

    def test_double_record_donation_creates_one(self):
        reg = self._attended_reg()
        data = {"donation_type": "whole_blood", "volume_ml": 350, "donated_at": timezone.now() - timedelta(minutes=5)}
        res = run_together([lambda: don.record_donation(self.staff, reg.pk, dict(data)) for _ in range(4)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 1)
        self.assertEqual(Donation.objects.filter(registration=reg).count(), 1)
        self.assertEqual(Registration.objects.get(pk=reg.pk).status, "donated")

    def test_concurrent_lab_pass_stocks_in_once(self):
        reg = self._attended_reg()
        d = don.record_donation(self.staff, reg.pk, {"donation_type": "whole_blood", "volume_ml": 350,
                                                     "donated_at": timezone.now() - timedelta(minutes=5)})
        data = {"blood_group": "O+", "product_spec_id": self.spec.pk, "quantity": 1}
        res = run_together([lambda i=i: lab.record_lab_result(self.staff, d.pk, "passed", data, f"lab-{i}")
                            for i in range(4)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(StockTxn.objects.filter(donation=d).count(), 1)
        stock = Stock.objects.get(hospital=self.h, blood_group="O+", product_spec=self.spec)
        self.assertEqual(stock.quantity_on_hand, 1)

    def test_concurrent_void_and_issue_keep_stock_consistent(self):
        """Hủy lượt hiến (trừ kho) và xuất kho cùng lúc trên cùng đơn vị → không âm kho, không mất dấu."""
        reg = self._attended_reg()
        d = don.record_donation(self.staff, reg.pk, {"donation_type": "whole_blood", "volume_ml": 350,
                                                     "donated_at": timezone.now() - timedelta(minutes=5)})
        lab.record_lab_result(self.staff, d.pk, "passed", {"blood_group": "O+", "product_spec_id": self.spec.pk}, "lab-v")
        stock = Stock.objects.get(hospital=self.h, blood_group="O+", product_spec=self.spec)
        res = run_together([lambda: don.void_donation(self.staff, d.pk, "Ghi nhầm", "not_donated"),
                            lambda: inv.issue(self.staff, stock.pk, 1, "issue-v")])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 1)
        self.assert_ledger_consistent(stock)
        self.assertEqual(stock.quantity_on_hand, 0)

    def test_concurrent_registration_same_member(self):
        camp = f.campaign(self.h, start_offset_h=2)
        member = f.user()
        res = run_together([lambda: cmp.register_for_campaign(member, camp) for _ in range(5)])
        self.assertEqual(unexpected(res), [])
        self.assertEqual(len(ok(res)), 1)
        self.assertEqual(Registration.objects.filter(campaign=camp, donor=member).count(), 1)
