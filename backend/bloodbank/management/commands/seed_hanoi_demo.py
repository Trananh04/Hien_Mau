"""Dữ liệu mẫu Hà Nội để thử "Gợi ý người hiến" theo khoảng cách.

Tạo 2 bệnh viện mẫu (Đống Đa, Hà Đông) có tọa độ; ở Đống Đa: thiếu O+ KHẨN, thiếu B+ trong kho và một yêu cầu cần máu
A+ đã xác minh (khẩn); các đợt hiến đã qua ở 16 quận/huyện
(tọa độ trung tâm gần đúng) và 48 người hiến với lịch sử khác nhau. Vị trí gần đúng của người hiến = đợt hiến gần nhất họ
đến, nên khoảng cách tới bệnh viện trải từ ~1 km (Đống Đa) đến ~45 km (Ba Vì).

    python manage.py seed_hanoi_demo          # tạo (bỏ qua nếu đã có)
    python manage.py seed_hanoi_demo --xoa    # gỡ toàn bộ dữ liệu mẫu Hà Nội

Mọi tên người, bệnh viện, số điện thoại đều là DỮ LIỆU MẪU. Mật khẩu: Demo@2026.
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, RestrictedError
from django.utils import timezone

from accounts.models import User
from bloodbank.models import (Campaign, Demand, Donation, DonorCallout, Hospital, Notification, PatientRequest,
                              ProductSpec, Registration, Staff)

PW = "Demo@2026"
PROVINCE = "Hà Nội"
HOSPITALS = [
    # code, tên, quận, lat, lng, email nhân viên
    ("BVM-HN1", "Bệnh viện Mẫu Đống Đa", "Đống Đa", "21.0170", "105.8290", "benhvien.hn@hienmau.vn"),
    ("BVM-HN2", "Bệnh viện Mẫu Hà Đông", "Hà Đông", "20.9710", "105.7790", "benhvien.hd@hienmau.vn"),
]
# Tọa độ trung tâm quận/huyện (gần đúng)
DISTRICTS = [
    ("Đống Đa", "21.0180", "105.8290"), ("Ba Đình", "21.0340", "105.8140"), ("Hoàn Kiếm", "21.0285", "105.8542"),
    ("Hai Bà Trưng", "21.0060", "105.8570"), ("Thanh Xuân", "20.9930", "105.8110"), ("Cầu Giấy", "21.0330", "105.7900"),
    ("Tây Hồ", "21.0700", "105.8190"), ("Hoàng Mai", "20.9740", "105.8630"), ("Long Biên", "21.0470", "105.8890"),
    ("Nam Từ Liêm", "21.0120", "105.7650"), ("Hà Đông", "20.9710", "105.7790"), ("Gia Lâm", "21.0220", "105.9370"),
    ("Đông Anh", "21.1370", "105.8490"), ("Sóc Sơn", "21.2570", "105.8490"), ("Sơn Tây", "21.1380", "105.5050"),
    ("Ba Vì", "21.1990", "105.4230"),
]
WEST = {"Cầu Giấy", "Nam Từ Liêm", "Hà Đông", "Sơn Tây", "Ba Vì"}   # đợt hiến do BV Hà Đông tổ chức
CAMPAIGN_DAYS_AGO = (330, 210, 110, 40)
GROUPS = ["O+", "B+", "O+", "A+", "B+", "O+", "AB+", "O+", "B+", "A+", "O-", "B+"]
HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Ngô", "Dương", "Lý"]
DEM = ["Văn", "Thị", "Minh", "Thu", "Quang", "Ngọc", "Đức", "Thanh", "Hải", "Phương"]
TEN = ["Anh", "Bảo", "Châu", "Dũng", "Giang", "Hiếu", "Hương", "Khánh", "Linh", "Long", "Mai", "Nam", "Ngân", "Phúc",
       "Quân", "Sơn", "Tâm", "Thảo", "Trang", "Tú", "Vân", "Việt", "Yến", "Hùng"]
N_DONORS = 48


class Command(BaseCommand):
    help = "Dữ liệu mẫu Hà Nội để thử gợi ý người hiến theo khoảng cách (--xoa để gỡ)."

    def add_arguments(self, parser):
        parser.add_argument("--xoa", action="store_true", help="Gỡ dữ liệu mẫu Hà Nội")

    def handle(self, *args, **opts):
        if opts["xoa"]:
            return self._remove()
        if Hospital.objects.filter(code=HOSPITALS[0][0]).exists():
            self.stdout.write("Dữ liệu mẫu Hà Nội đã có — bỏ qua. Dùng --xoa để gỡ rồi tạo lại.")
            return
        with transaction.atomic():
            n = self._seed()
        self.stdout.write(self.style.SUCCESS(
            f"Đã tạo 2 bệnh viện, {n} người hiến ở Hà Nội. Đăng nhập cổng bệnh viện: {HOSPITALS[0][5]} / {PW}"))

    def _user(self, name, email, phone, **kw):
        now = timezone.now()
        return User.objects.create_user(email=email, password=PW, full_name=name, phone=phone, terms_accepted_at=now,
                                        email_verified_at=now, **kw)

    def _seed(self):
        rng = random.Random(2026)
        now = timezone.now()
        hospitals, staff = {}, {}
        for i, (code, name, district, lat, lng, email) in enumerate(HOSPITALS, start=1):
            h = Hospital.objects.create(code=code, name=name, address=f"{10 * i} Đường Mẫu, {district}", province=PROVINCE,
                                        district=district, latitude=Decimal(lat), longitude=Decimal(lng),
                                        phone=f"02439000{i:03d}", email=f"lienhe.{code.lower()}@demo.vn")
            u = self._user(f"Nhân viên {name.replace('Bệnh viện ', 'BV ')}", email, f"0912900{i:03d}", role="hospital")
            Staff.objects.create(hospital=h, user=u, staff_role=Staff.Role.MANAGER)
            hospitals[code], staff[code] = h, u
        main, west = hospitals["BVM-HN1"], hospitals["BVM-HN2"]

        rbc = ProductSpec.objects.get(product__code="RBC", code="250ML")
        # Hai trường hợp thiếu máu: O+ KHẨN (cần trong 6 giờ) và B+ THIẾU KHO (cần trong 10 ngày)
        Demand.objects.create(hospital=main, blood_group="O+", product_spec=rbc, required_quantity=10,
                              needed_by=now + timedelta(hours=6), note="Ca mổ cấp cứu chiều nay (mẫu)")
        Demand.objects.create(hospital=main, blood_group="B+", product_spec=rbc, required_quantity=4,
                              needed_by=now + timedelta(days=10), note="Dự trù phẫu thuật kế hoạch (mẫu)")

        # Đợt hiến đã qua: mỗi quận 4 đợt, tại tọa độ trung tâm quận
        camps = {}
        for district, lat, lng in DISTRICTS:
            host = west if district in WEST else main
            for days in CAMPAIGN_DAYS_AGO:
                start = now - timedelta(days=days, hours=3)
                camps[(district, days)] = Campaign.objects.create(
                    hospital=host, name=f"Hiến máu {district} (mẫu)", location_name=f"Nhà văn hóa {district}",
                    address=f"Trung tâm {district}, Hà Nội", province=PROVINCE, latitude=Decimal(lat),
                    longitude=Decimal(lng), start_time=start, end_time=start + timedelta(hours=6), status="completed")

        def give(donor, district, days, verified):
            c = camps[(district, days)]
            reg = Registration.objects.create(campaign=c, donor=donor, status="donated", donation_type="whole_blood")
            lab = {"lab_status": "passed", "lab_blood_group": donor.blood_group, "lab_checked_at": c.end_time,
                   "lab_checked_by": staff[c.hospital.code]} if verified else {}
            Donation.objects.create(donor=donor, registration=reg, hospital=c.hospital, volume_ml=350,
                                    donated_at=c.start_time + timedelta(hours=1), confirmed_by=staff[c.hospital.code], **lab)

        def miss(donor, district, days):
            Registration.objects.create(campaign=camps[(district, days)], donor=donor, status="no_show")

        # Kiểu lịch sử: thân thiết / thỉnh thoảng / hay vắng / mới / vừa hiến (bị loại) / ngoài độ tuổi (bị loại)
        kinds = ["loyal", "occasional", "unreliable", "new", "loyal", "occasional", "recent", "new", "loyal", "too_old",
                 "occasional", "unreliable"]
        for i in range(N_DONORS):
            district = DISTRICTS[i % len(DISTRICTS)][0]
            kind = kinds[(i + i // len(GROUPS)) % len(kinds)]   # lệch chu kỳ để mỗi nhóm máu có đủ các kiểu
            age = 61 if kind == "too_old" else rng.randint(19, 55)
            gender = rng.choice(["male", "female"])
            name = f"{HO[i % len(HO)]} {rng.choice(DEM)} {TEN[i % len(TEN)]}"
            u = self._user(name, f"hn.demo{i + 1:02d}@demo.vn", f"0988{i + 1:06d}", blood_group=GROUPS[i % len(GROUPS)],
                           gender=gender, province=PROVINCE, date_of_birth=date(date.today().year - age, 3, 15))
            if kind == "loyal":
                for days in (330, 210, 110):
                    give(u, district, days, verified=True)
            elif kind == "occasional":
                give(u, district, 210, verified=rng.random() < 0.5)
                give(u, district, 110, verified=False)
            elif kind == "unreliable":
                give(u, district, 330, verified=False)
                miss(u, district, 210)
                miss(u, district, 110)
            elif kind == "recent":
                give(u, district, 40, verified=True)          # mới hiến 40 ngày → chưa đủ 84 ngày nghỉ
            elif kind == "too_old":
                give(u, district, 210, verified=True)
            # "new": chưa hiến, không có vị trí

        # Yêu cầu cần máu của người nhà bệnh nhân, đã được bệnh viện xác minh — kho chưa có A+ nên là KHẨN
        requester = User.objects.get(email="hn.demo04@demo.vn")
        PatientRequest.objects.create(
            request_code="PR-HN-MAU01", requester=requester, contact_name=requester.full_name,
            contact_phone=requester.phone, patient_name="Bệnh nhân mẫu", hospital=main, blood_group="A+",
            blood_product=rbc.product, quantity_units=2, needed_by=now + timedelta(hours=4),
            note="Bệnh nhân sau tai nạn giao thông (mẫu)", consent_at=now, status=PatientRequest.Status.VERIFIED,
            verified_by=staff["BVM-HN1"], verified_at=now)
        return N_DONORS

    def _remove(self):
        hospitals = list(Hospital.objects.filter(code__in=[h[0] for h in HOSPITALS]))
        users = User.objects.filter(email__in=[h[5] for h in HOSPITALS]) | User.objects.filter(email__startswith="hn.demo",
                                                                                                email__endswith="@demo.vn")
        try:
            with transaction.atomic():
                Notification.objects.filter(user__in=users).delete()
                DonorCallout.objects.filter(hospital__in=hospitals).delete()
                Donation.objects.filter(hospital__in=hospitals).delete()
                Registration.objects.filter(campaign__hospital__in=hospitals).delete()
                Campaign.objects.filter(hospital__in=hospitals).delete()
                Demand.objects.filter(hospital__in=hospitals).delete()
                PatientRequest.objects.filter(hospital__in=hospitals).delete()
                Staff.objects.filter(hospital__in=hospitals).delete()
                n = users.count()
                users.delete()
                Hospital.objects.filter(pk__in=[h.pk for h in hospitals]).delete()
            self.stdout.write(self.style.SUCCESS(f"Đã gỡ dữ liệu mẫu Hà Nội ({n} tài khoản)."))
        except (IntegrityError, ProtectedError, RestrictedError):
            # Đã phát sinh nhật ký (audit / sổ kho chỉ ghi thêm) → không xóa được; khóa lại để không xuất hiện nữa
            users.update(status=User.Status.LOCKED)
            Hospital.objects.filter(pk__in=[h.pk for h in hospitals]).update(status="inactive")
            self.stdout.write(self.style.WARNING(
                "Dữ liệu mẫu Hà Nội đã có nhật ký (ví dụ đã gửi lời mời) nên không xóa hẳn được; "
                "đã khóa các tài khoản và ngừng hoạt động 2 bệnh viện."))
