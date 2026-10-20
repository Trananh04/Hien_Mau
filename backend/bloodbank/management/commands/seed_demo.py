"""Nạp dữ liệu mẫu để chạy thử. Idempotent: đã có tài khoản admin mẫu thì bỏ qua.

Mọi tên bệnh viện, người dùng, số liệu đều là DỮ LIỆU MẪU của dự án học tập.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from bloodbank.models import Campaign, Hospital, ProductSpec, Registration, Staff
from bloodbank.services import donations as don
from bloodbank.services import inventory as inv
from bloodbank.services import patients as prq
from bloodbank.services import transfers as trf

ADMIN_EMAIL = "admin@hienmau.vn"
PW = "Demo@2026"

HOSPITALS = [
    ("BVM-HC", "Bệnh viện Mẫu Hải Châu", "12 Đường Mẫu A, Hải Châu", "Đà Nẵng", "Hải Châu", 16.0678, 108.2208, "02363000001"),
    ("BVM-TK", "Bệnh viện Mẫu Thanh Khê", "45 Đường Mẫu B, Thanh Khê", "Đà Nẵng", "Thanh Khê", 16.0640, 108.1880, "02363000002"),
    ("BVM-ST", "Bệnh viện Mẫu Sơn Trà", "8 Đường Mẫu C, Sơn Trà", "Đà Nẵng", "Sơn Trà", 16.0860, 108.2420, "02363000003"),
    ("BVM-LC", "Bệnh viện Mẫu Liên Chiểu", "101 Đường Mẫu D, Liên Chiểu", "Đà Nẵng", "Liên Chiểu", 16.0740, 108.1500, "02363000004"),
    ("BVM-TKY", "Bệnh viện Mẫu Tam Kỳ", "20 Đường Mẫu E, Tam Kỳ", "Quảng Nam", "Tam Kỳ", 15.5730, 108.4740, "02353000005"),
]

DONORS = [
    ("Nguyễn Văn An", "an.nguyen@demo.vn", "0905100001", "O+", "male"),
    ("Trần Thị Bình", "binh.tran@demo.vn", "0905100002", "A+", "female"),
    ("Lê Hoàng Cường", "cuong.le@demo.vn", "0905100003", "B+", "male"),
    ("Phạm Thu Dung", "dung.pham@demo.vn", "0905100004", "O-", "female"),
    ("Hoàng Minh Đức", "duc.hoang@demo.vn", "0905100005", "AB+", "male"),
    ("Võ Thị Hà", "ha.vo@demo.vn", "0905100006", "A-", "female"),
    ("Đặng Quốc Huy", "huy.dang@demo.vn", "0905100007", "O+", "male"),
    ("Bùi Ngọc Lan", "lan.bui@demo.vn", "0905100008", None, "female"),
]


class Command(BaseCommand):
    help = "Nạp dữ liệu mẫu (idempotent)."

    def handle(self, *args, **options):
        if User.objects.filter(email=ADMIN_EMAIL).exists():
            created = self._ensure_hospital_accounts()
            self.stdout.write(f"Dữ liệu mẫu đã có — bỏ qua (bổ sung {created} tài khoản nhân viên mẫu)." if created
                              else "Dữ liệu mẫu đã có — bỏ qua.")
            return
        with transaction.atomic():
            self._seed()
        self.stdout.write(self.style.SUCCESS("Đã nạp dữ liệu mẫu. Mật khẩu mọi tài khoản mẫu: " + PW))

    def _user(self, name, email, phone=None, **kw):
        return User.objects.create_user(email=email, password=PW, full_name=name, phone=phone,
                                        terms_accepted_at=timezone.now(), email_verified_at=timezone.now(), **kw)

    def _ensure_hospital_accounts(self):
        """Mỗi bệnh viện mẫu một tài khoản Nhân viên bệnh viện `benhvienN@hienmau.vn`; benhvien1 làm thêm ở BV 2."""
        created = 0
        hospitals = {h.code: h for h in Hospital.objects.filter(code__in=[c for c, *_ in HOSPITALS])}
        for i, (code, *_rest) in enumerate(HOSPITALS, start=1):
            h = hospitals.get(code)
            if h is None:
                continue
            email = f"benhvien{i}@hienmau.vn"
            u = User.objects.filter(email=email).first()
            if u is None:
                u = self._user(f"Nhân viên {h.name.replace('Bệnh viện ', 'BV ')}", email, f"0912000{i:03d}", role="hospital")
                created += 1
            Staff.objects.get_or_create(user=u, defaults={"hospital": h})
        return created

    def _seed(self):
        now = timezone.now()
        self._user("Quản trị hệ thống", ADMIN_EMAIL, role="admin")
        hospitals = [
            Hospital.objects.create(code=c, name=n, address=a, province=p, district=d, latitude=lat, longitude=lng, phone=ph,
                                    email=f"lienhe.{c.lower()}@demo.vn")
            for c, n, a, p, d, lat, lng, ph in HOSPITALS
        ]
        h1, h2, h3, h4, h5 = hospitals

        # Một vai trò chung cho nhân viên bệnh viện; mỗi nhân viên thuộc đúng một bệnh viện (BR-03, BR-04)
        self._ensure_hospital_accounts()
        staff = {i: Staff.objects.get(hospital=h, user__email=f"benhvien{i}@hienmau.vn")
                 for i, h in enumerate(hospitals, start=1)}

        donors = [self._user(n, e, ph, blood_group=bg, gender=g, province="Đà Nẵng") for n, e, ph, bg, g in DONORS]

        s1, s2, s3, s4, s5 = (staff[i] for i in range(1, 6))

        # ---- Đợt hiến
        def mk(h, name, start, hours, status, loc, addr, desc=""):
            return Campaign.objects.create(hospital=h, name=name, start_time=start, end_time=start + timedelta(hours=hours),
                                           status=status, location_name=loc, address=addr, province=h.province,
                                           description=desc or None)

        past = mk(h1, "Ngày hội hiến máu mùa thu (mẫu)", now - timedelta(days=12), 8, "closed", "Hội trường Bệnh viện Mẫu Hải Châu",
                  "12 Đường Mẫu A, Hải Châu", "Đợt hiến mẫu đã diễn ra — dùng để minh họa lịch sử hiến và báo cáo.")
        today = mk(h1, "Hiến máu cuối tuần tại Hải Châu (mẫu)", now - timedelta(hours=2), 8, "open", "Sảnh khu B",
                   "12 Đường Mẫu A, Hải Châu", "Đợt hiến đang diễn ra — dùng để thử check-in và ghi nhận tại điểm hiến.")
        mk(h1, "Giọt hồng tháng 11 (mẫu)", now + timedelta(days=5), 6, "open", "Nhà văn hóa phường (mẫu)",
           "30 Đường Mẫu F, Hải Châu", "Mang theo giấy tờ tùy thân. Ăn nhẹ trước khi hiến.")
        mk(h2, "Hiến máu sinh viên Thanh Khê (mẫu)", now + timedelta(days=9), 5, "open", "Hội trường trường học (mẫu)",
           "45 Đường Mẫu B, Thanh Khê")
        mk(h5, "Chủ nhật đỏ Tam Kỳ (mẫu)", now + timedelta(days=14), 7, "open", "Quảng trường (mẫu)", "20 Đường Mẫu E, Tam Kỳ")
        mk(h3, "Đợt hiến dự kiến tháng 12 (nháp)", now + timedelta(days=40), 6, "draft", "Sảnh chính", "8 Đường Mẫu C, Sơn Trà")

        # Đợt đã diễn ra: 5 người hiến, 1 lượt hủy hiệu lực
        for i, d in enumerate(donors[:6]):
            reg = Registration.objects.create(campaign=past, donor=d, status="attended",
                                              donation_type="component" if i == 4 else "whole_blood")
            data = {"donation_type": reg.donation_type, "donated_at": past.start_time + timedelta(minutes=40 + 25 * i),
                    "volume_ml": [350, 250, 350, 450, None, 350][i]}
            if i == 4:
                data.update(component_product_id=ProductSpec.objects.get(product__code="PLT", is_default=True).product_id,
                            component_quantity="1", component_unit="unit")
            donation = don.record_donation(s1, reg.pk, data, confirm_volume=True)
            if i == 5:
                don.void_donation(s1, donation.pk, "Ghi nhầm người hiến (dữ liệu mẫu)", "not_donated")
        Registration.objects.create(campaign=past, donor=donors[6], status="no_show")
        Campaign.objects.filter(pk=past.pk).update(status="completed")

        # Đợt đang diễn ra: đơn ở nhiều trạng thái
        for d, st in zip(donors, ["approved", "pending", "attended", "approved", "pending", "cancelled", "approved", "pending"]):
            Registration.objects.create(campaign=today, donor=d, status=st, donation_type="whole_blood" if st != "pending" else None)

        # ---- Kho (qua sổ kho)
        rbc = ProductSpec.objects.get(product__code="RBC", code="250ML")
        rbc350 = ProductSpec.objects.get(product__code="RBC", code="350ML")
        ffp = ProductSpec.objects.get(product__code="FFP", is_default=True)
        plt = ProductSpec.objects.get(product__code="PLT", is_default=True)
        stock_plan = {
            s1: [("O+", rbc, 14), ("A+", rbc, 9), ("B+", rbc, 6), ("O-", rbc, 1), ("AB+", ffp, 5), ("O+", plt, 3)],
            s2: [("O+", rbc, 20), ("O-", rbc, 8), ("A+", rbc350, 7), ("B+", ffp, 10)],
            s3: [("O-", rbc, 5), ("O+", rbc, 12), ("A-", rbc, 3), ("O+", plt, 6)],
            s4: [("A+", rbc, 11), ("B-", rbc, 2)],
            s5: [("O+", rbc, 9), ("AB-", ffp, 2)],
        }
        for s, rows in stock_plan.items():
            for bg, spec, qty in rows:
                inv.receive(s, spec.pk, bg, qty, f"seed-{s.hospital.code}-{bg}-{spec.pk}", "Nhập kho mẫu")
        from bloodbank.models import Stock

        def setting(hosp, bg, spec, share, minimum):
            st = Stock.objects.get(hospital=hosp, blood_group=bg, product_spec=spec)
            inv.update_stock_settings(Staff.objects.filter(hospital=hosp, user__role="hospital").order_by("pk").first(),
                                      st.pk, share, minimum, st.version)

        setting(h1, "O+", rbc, None, 10)
        setting(h1, "O-", rbc, None, 4)
        setting(h1, "B+", rbc, None, 8)
        setting(h2, "O-", rbc, 6, 2)
        setting(h2, "O+", rbc, 10, 5)
        setting(h3, "O-", rbc, 4, 1)
        setting(h3, "O+", plt, 3, 1)
        setting(h4, "A+", rbc, 5, 2)
        inv.issue(s1, Stock.objects.get(hospital=h1, blood_group="A+", product_spec=rbc).pk, 2, "seed-issue-1",
                  "Cấp cho khoa Hồi sức (mẫu)")
        inv.adjust(s1, Stock.objects.get(hospital=h1, blood_group="B+", product_spec=rbc).pk, "decrease", 1,
                   "expired", "Hết hạn sử dụng (mẫu)", "seed-adjust-1")

        # Nhu cầu → thiếu hụt O- tại BV1
        inv.save_demand(s1, {"blood_group": "O-", "product_spec_id": rbc.pk, "required_quantity": 6,
                              "needed_by": now + timedelta(days=2), "note": "Dự trù phẫu thuật (mẫu)"})
        inv.save_demand(s1, {"blood_group": "O+", "product_spec_id": rbc.pk, "required_quantity": 8, "needed_by": None})

        # ---- Liên viện: BV1 xin O- từ BV2 (chấp thuận) và BV3 (chờ phản hồi)
        req = trf.create_request(s1, {"blood_group": "O-", "product_spec_id": rbc.pk, "quantity_needed": 5,
                                       "priority": "urgent", "needed_by": now + timedelta(days=1),
                                       "note": "Bệnh nhân phẫu thuật cấp cứu (mẫu)"}, [(h2.pk, 3), (h3.pk, 2)])
        offer2 = req.offers.get(supplier_hospital=h2)
        trf.accept_offer(s2, offer2.pk, 3, "Có thể giao trong 2 giờ (mẫu)")
        # BV2 xin tiểu cầu từ BV3 — đã xuất, chờ nhận
        req2 = trf.create_request(s2, {"blood_group": "O+", "product_spec_id": plt.pk, "quantity_needed": 2,
                                        "priority": "high"}, [(h3.pk, 2)])
        offer3 = req2.offers.get()
        trf.accept_offer(s3, offer3.pk, 2)
        trf.dispatch_offer(s3, offer3.pk, "seed-dispatch-1")

        # ---- Người cần máu
        prq.submit(donors[1], {"consent": True, "hospital_id": h1.pk, "quantity_units": 2, "blood_group": "A+",
                               "contact_name": "Trần Thị Bình", "contact_phone": "0905100002",
                               "patient_name": "Trần Văn Mẫu", "note": "Bệnh nhân sau tai nạn giao thông (mẫu)",
                               "needed_by": now + timedelta(hours=10)})
        p2 = prq.submit(donors[2], {"consent": True, "hospital_id": h1.pk, "quantity_units": 3, "blood_group": "O-",
                                    "contact_name": "Lê Hoàng Cường", "contact_phone": "0905100003",
                                    "patient_name": "Lê Thị Mẫu"})
        prq.hospital_action(s1, p2.pk, "verify", {"blood_group": "O-"})
        prq.submit(donors[0], {"consent": True, "hospital_id": h2.pk, "quantity_units": 1, "contact_name": "Nguyễn Văn An",
                               "contact_phone": "0905100001"})
