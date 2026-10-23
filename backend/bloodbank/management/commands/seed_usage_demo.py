"""Dữ liệu MÔ PHỎNG lượng dùng máu 8 tuần để trang Dự báo thiếu hụt có số liệu (demo / đồ án).

Mô phỏng NGƯỢC từ tồn kho cuối: mỗi ngày xuất cho người bệnh (Chủ nhật ít hơn), vài ngày nhập một lô — nên chuỗi
"trước → sau" của sổ kho luôn khớp và không âm. Chỉ tạo cho dòng tồn CHƯA có phiếu nào (không làm lệch sổ kho thật).
Sổ kho chỉ-thêm (không xóa được) → lệnh chạy một lần, chạy lại sẽ bỏ qua.

    python manage.py seed_usage_demo
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bloodbank.models import Hospital, ProductSpec, Staff, Stock, StockTxn

DAYS = 56
# (mã bệnh viện, mã chế phẩm, mã quy cách, nhóm máu, dùng trung bình / ngày, tồn cuối) — đủ kiểu: sắp hết / lên kế hoạch / đủ
PLAN = [
    ("BVM-HC", "RBC", "350ML", "O+", 2.2, 6),     # ~3 ngày → sắp hết
    ("BVM-HC", "RBC", "350ML", "O-", 0.6, 2),     # ~3 ngày → sắp hết (nhóm hiếm)
    ("BVM-HC", "RBC", "350ML", "B+", 1.0, 11),    # ~11 ngày → lên kế hoạch
    ("BVM-HC", "RBC", "350ML", "AB+", 0.4, 18),   # đủ dùng
    ("BVM-HN1", "RBC", "250ML", "O+", 2.8, 5),    # sắp hết
    ("BVM-HN1", "RBC", "250ML", "A+", 1.4, 15),   # lên kế hoạch
    ("BVM-HN1", "RBC", "250ML", "B+", 1.1, 4),    # sắp hết
    ("BVM-HN1", "RBC", "250ML", "AB+", 0.3, 12),  # đủ dùng
]


def _poisson(rng, lam):
    # Knuth — đủ dùng cho lam nhỏ
    import math

    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class Command(BaseCommand):
    help = "Mô phỏng 8 tuần dùng máu (sổ kho) cho trang Dự báo thiếu hụt."

    def handle(self, *args, **opts):
        if StockTxn.objects.filter(idempotency_key__startswith="demo-usage-").exists():
            self.stdout.write("Dữ liệu mô phỏng lượng dùng đã có — bỏ qua.")
            return
        rng = random.Random(2026)
        now = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        made = 0
        with transaction.atomic():
            for code, product, spec_code, bg, mean, end in PLAN:
                h = Hospital.objects.filter(code=code).first()
                spec = ProductSpec.objects.filter(product__code=product, code=spec_code).first()
                staff = Staff.objects.filter(hospital=h).select_related("user").first() if h else None
                if not (h and spec and staff):
                    continue
                stock, _ = Stock.objects.get_or_create(hospital=h, blood_group=bg, product_spec=spec)
                if stock.txns.exists():
                    continue        # dòng tồn đã có sổ thật — không chèn lịch sử giả
                events, v = [], end  # đi ngược thời gian từ tồn cuối
                for back in range(1, DAYS + 1):
                    day = now - timedelta(days=back)
                    use = _poisson(rng, mean * (0.5 if day.weekday() == 6 else 1.1))
                    if use:
                        events.append((day + timedelta(hours=9), "issue", -use, v + use))   # (lúc, loại, đổi, trước)
                        v += use
                    if back % 4 == 0 and v > 0:          # nhập một lô mỗi ~4 ngày
                        r = min(v, max(1, round(mean * 4 + rng.randint(-1, 2))))
                        events.append((day + timedelta(hours=7), "receive", r, v - r))
                        v -= r
                for i, (at, kind, change, before) in enumerate(sorted(events)):
                    StockTxn.objects.create(
                        stock=stock, txn_type=kind, quantity_change=change, quantity_before=before,
                        quantity_after=before + change, performed_by=staff.user, occurred_at=at,
                        idempotency_key=f"demo-usage-{stock.pk}-{i}",
                        reason_note="Xuất cho người bệnh (mô phỏng)" if kind == "issue" else "Nhập lô (mô phỏng)",
                    )
                    made += 1
                Stock.objects.filter(pk=stock.pk).update(quantity_on_hand=end)
        self.stdout.write(self.style.SUCCESS(f"Đã tạo {made} phiếu kho mô phỏng ({DAYS} ngày)."))
