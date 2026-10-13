"""Hàm tạo dữ liệu dùng chung cho test."""
import itertools
from datetime import timedelta

from django.utils import timezone

from accounts.models import User
from bloodbank.models import Campaign, Hospital, ProductSpec, Registration, Staff

_seq = itertools.count(1)


def user(full_name="Người dùng", role="member", **kw):
    n = next(_seq)
    kw.setdefault("email", f"user{n}@test.vn")
    kw.setdefault("phone", f"090{n:07d}")
    return User.objects.create_user(password=kw.pop("password", "MatKhau!2026"), full_name=full_name, role=role, **kw)


def hospital(name=None, **kw):
    n = next(_seq)
    kw.setdefault("code", f"BV{n:03d}")
    kw.setdefault("address", "1 Đường Mẫu")
    kw.setdefault("province", "Đà Nẵng")
    kw.setdefault("district", "Hải Châu")
    return Hospital.objects.create(name=name or f"Bệnh viện mẫu {n}", **kw)


def staff(hosp, usr=None):
    """Tài khoản Nhân viên bệnh viện (một vai trò chung) được phân công tại `hosp`."""
    usr = usr or user(full_name="Nhân viên bệnh viện", role="hospital")
    Staff.objects.create(hospital=hosp, user=usr)
    return usr


def campaign(hosp, status="open", start_offset_h=-1, duration_h=6, **kw):
    start = timezone.now() + timedelta(hours=start_offset_h)
    kw.setdefault("name", "Đợt hiến mẫu")
    kw.setdefault("location_name", "Hội trường")
    kw.setdefault("address", "2 Đường Mẫu")
    kw.setdefault("province", hosp.province)
    return Campaign.objects.create(
        hospital=hosp, start_time=start, end_time=start + timedelta(hours=duration_h), status=status, **kw
    )


def registration(camp, donor, status="pending", **kw):
    return Registration.objects.create(campaign=camp, donor=donor, status=status, **kw)


def spec(product_code="RBC", spec_code="250ML"):
    return ProductSpec.objects.get(product__code=product_code, code=spec_code)
