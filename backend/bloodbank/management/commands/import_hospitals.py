"""Nạp danh sách bệnh viện THẬT (đã được duyệt) kèm tài khoản Quản lý bệnh viện từ file JSON.

    python manage.py import_hospitals var/benhvien_hanoi.json
    # Máy chủ (image không chứa var/): chép file vào container rồi nạp. KHÔNG dùng `Get-Content … |` trên
    # Windows PowerShell 5.1 — ống dẫn sang chương trình ngoài đổi chữ có dấu thành "?".
    docker compose -f docker-compose.prod.yml cp backend/var/benhvien_hanoi.json web:/tmp/benhvien_hanoi.json
    docker compose -f docker-compose.prod.yml exec -T web python manage.py import_hospitals /tmp/benhvien_hanoi.json

Mỗi phần tử: ma_co_so, ten_benh_vien, dien_thoai, email, dia_chi, tinh_thanh, phuong_xa, nguoi_quan_ly,
email_dang_nhap, sdt_quan_ly, mat_khau. File chứa mật khẩu → để trong backend/var/ (không đưa lên git / image).

- Tên tỉnh, phường / xã được chuẩn hóa về đơn vị hành chính sau sắp xếp 01/7/2025 (tên cũ → OLD_WARDS).
- Tọa độ tra theo địa chỉ (Goong, dự phòng OpenStreetMap) để bệnh viện hiện trên bản đồ; không tìm thấy → để trống,
  bệnh viện tự ghim ở "Thông tin bệnh viện".
- Chạy lại an toàn: mã cơ sở đã có thì bỏ qua (không sửa, không đổi mật khẩu).
"""
import json
import sys
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User, normalize_phone
from accounts.provinces import normalize_province, wards_of
from bloodbank.models import Hospital, Staff
from bloodbank.services import geocode
from bloodbank.services.common import audit, snapshot

# (tỉnh, tên phường / xã / thị trấn cũ) → tên mới. Phường cũ bị chia cho 2 phường mới: chọn theo vị trí bệnh viện
# (bảng đối chiếu VietMap admin_mapping_old_to_new_10_25) — kiểm tra lại nếu có thông báo chính thức khác.
OLD_WARDS = {
    ("Hà Nội", "Phường Yên Hòa"): "Phường Yên Hoà",
    ("Hà Nội", "Phường Bạch Đằng"): "Phường Hai Bà Trưng",       # cũ → Hồng Hà / Hai Bà Trưng
    ("Hà Nội", "Phường Láng Thượng"): "Phường Láng",
    ("Hà Nội", "Phường Nghĩa Tân"): "Phường Nghĩa Đô",
    ("Hà Nội", "Phường Nguyễn Du"): "Phường Hai Bà Trưng",
    ("Hà Nội", "Phường Thịnh Quang"): "Phường Đống Đa",          # cũ → Đống Đa / Kim Liên
    ("Hà Nội", "Phường Trung Tự"): "Phường Kim Liên",            # (Phương Liên - Trung Tự) → Kim Liên / Văn Miếu
    ("Hà Nội", "Phường Mai Dịch"): "Phường Từ Liêm",             # cũ → Phú Diễn / Từ Liêm
    ("Hà Nội", "Phường Phúc Xá"): "Phường Hồng Hà",
    ("Hà Nội", "Thị trấn Tây Đằng"): "Xã Quảng Oai",             # cũ → Quảng Oai / Minh Châu
    ("Hà Nội", "Thị trấn Vân Đình"): "Xã Vân Đình",
    ("Hà Nội", "Thị trấn Sóc Sơn"): "Xã Sóc Sơn",
}


def _nfc(text):
    return unicodedata.normalize("NFC", (text or "").strip())


def _ward(province, name):
    name = _nfc(name)
    current = wards_of(province)
    if name in current:
        return name
    new = OLD_WARDS.get((province, name))
    if new is None:   # khác cách bỏ dấu (Hòa / Hoà, Thủy / Thuỷ…)
        fold = {w.replace("oà", "òa").replace("uỷ", "ủy"): w for w in current}
        new = fold.get(name.replace("oà", "òa").replace("uỷ", "ủy"))
    return new


class Command(BaseCommand):
    help = "Nạp bệnh viện (đã duyệt) + tài khoản Quản lý từ file JSON (\"-\" = đọc từ stdin)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Đường dẫn file JSON, hoặc - để đọc từ stdin")
        parser.add_argument("--khong-tra-toa-do", action="store_true", dest="no_geo",
                            help="Không tra tọa độ (để trống, bệnh viện tự ghim sau)")

    def handle(self, *args, **opts):
        try:
            raw = sys.stdin.read() if opts["path"] == "-" else open(opts["path"], encoding="utf-8").read()
            rows = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise CommandError(f"Không đọc được danh sách bệnh viện: {exc}")

        # Kiểm tra cả file trước khi ghi: lỗi dữ liệu → không nạp gì
        problems, plan = [], []
        for i, r in enumerate(rows, start=1):
            code = _nfc(r.get("ma_co_so")).upper()
            province = normalize_province(r.get("tinh_thanh"))
            ward = _ward(province, r.get("phuong_xa")) if province else None
            if not (code and r.get("ten_benh_vien") and r.get("dia_chi") and r.get("email_dang_nhap")
                    and r.get("mat_khau") and r.get("nguoi_quan_ly")):
                problems.append(f"#{i} {code or '?'}: thiếu mã / tên / địa chỉ / người quản lý / email / mật khẩu")
            elif province is None:
                problems.append(f"#{i} {code}: không nhận ra tỉnh/thành \"{r.get('tinh_thanh')}\"")
            elif r.get("phuong_xa") and ward is None:
                problems.append(f"#{i} {code}: \"{r['phuong_xa']}\" không thuộc {province} (thêm vào OLD_WARDS)")
            else:
                plan.append((r, code, province, ward))
        if problems:
            raise CommandError("Dữ liệu chưa hợp lệ, chưa nạp gì:\n  " + "\n  ".join(problems))

        created = skipped = no_pin = 0
        for r, code, province, ward in plan:
            if Hospital.objects.filter(code=code).exists():
                skipped += 1
                self.stdout.write(f"  bỏ qua {code} (đã có)")
                continue
            email = _nfc(r["email_dang_nhap"]).lower()
            if User.objects.filter(email=email).exists():
                skipped += 1
                self.stdout.write(self.style.WARNING(f"  bỏ qua {code}: email {email} đã có tài khoản khác"))
                continue
            address = _nfc(r["dia_chi"])
            pin = None if opts["no_geo"] else geocode.lookup(f"{address}, {ward or ''}", province)
            phone = normalize_phone(r.get("sdt_quan_ly"))
            if phone and User.objects.filter(phone=phone).exists():
                self.stdout.write(self.style.WARNING(f"  {code}: SĐT quản lý {r['sdt_quan_ly']} đã dùng — để trống"))
                phone = None
            with transaction.atomic():
                hospital = Hospital.objects.create(
                    code=code, name=_nfc(r["ten_benh_vien"]), address=address, province=province, ward=ward,
                    phone=_nfc(r.get("dien_thoai")) or None, email=_nfc(r.get("email")).lower() or None,
                    latitude=pin["lat"] if pin else None, longitude=pin["lng"] if pin else None,
                    status=Hospital.Status.ACTIVE,
                )
                user = User.objects.create_user(email=email, password=r["mat_khau"], full_name=_nfc(r["nguoi_quan_ly"]),
                                                phone=phone, role=User.Role.HOSPITAL,
                                                email_verified_at=timezone.now())
                Staff.objects.create(hospital=hospital, user=user, staff_role=Staff.Role.MANAGER)
                audit(None, hospital, "create", new={**snapshot(hospital, ["code", "name", "province", "ward"]),
                                                     "manager": email, "source": "import_hospitals"}, hospital=hospital)
            created += 1
            no_pin += pin is None
            where = f"{pin['lat']}, {pin['lng']}" if pin else "chưa có tọa độ"
            self.stdout.write(f"  + {code} {hospital.name} · {ward or '—'} · {where}")
        summary = f"Đã nạp {created} bệnh viện, bỏ qua {skipped}."
        if no_pin:
            summary += f" {no_pin} bệnh viện chưa có tọa độ (tự ghim trong \"Thông tin bệnh viện\")."
        self.stdout.write(self.style.SUCCESS(summary))
