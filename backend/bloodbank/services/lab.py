"""Luồng sau ghi nhận lượt hiến: Chờ xét nghiệm → Đạt (nhập kho, gắn với lượt hiến) / Không đạt.

Máu chưa xét nghiệm chưa được dùng nên KHÔNG nhập thẳng vào kho khi ghi nhận lượt hiến.
Nhóm máu nhập kho lấy từ kết quả xét nghiệm, không dùng nhóm máu người hiến tự khai.
"""
from django.db.models import Q, Sum
from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES
from bloodbank.models import Donation, ProductSpec, StockTxn, SystemSetting

from .common import BusinessError, as_id, audit, business_transaction, positive_int, require, snapshot
from .inventory import apply_txn, get_or_create_stock_locked

L = Donation.LabStatus


def lab_queue(hospital, q=None):
    """Lượt hiến chờ xét nghiệm, cũ trước (xử lý theo thứ tự đến)."""
    qs = (Donation.objects.filter(hospital=hospital, status=Donation.Status.CONFIRMED, lab_status=L.PENDING)
          .select_related("donor", "registration__campaign", "component_product").order_by("donated_at"))
    return search(qs, q)


def lab_history(hospital, q=None):
    """Lượt hiến đã có kết quả xét nghiệm (mới trước), kèm số đơn vị đã nhập kho từ lượt hiến đó."""
    qs = (Donation.objects.filter(hospital=hospital, lab_status__in=[L.PASSED, L.FAILED])
          .select_related("donor", "lab_checked_by", "component_product")
          .annotate(units=Sum("stock_txns__quantity_change", filter=Q(stock_txns__txn_type=StockTxn.Type.RECEIVE)))
          .order_by("-lab_checked_at", "-pk"))
    return search(qs, q)


def search(qs, q):
    """Tìm theo mã lượt hiến (LH-000013 hoặc 13), tên hoặc số điện thoại người hiến."""
    q = (q or "").strip()
    if not q:
        return qs
    digits = q.upper().removeprefix("LH-").lstrip("0")
    cond = Q(donor__full_name__icontains=q) | Q(donor__phone__icontains=q)
    if digits.isdigit():
        cond |= Q(pk=int(digits))
    return qs.filter(cond)


# Quy tắc điều chế mặc định: (mã chế phẩm, mã quy cách, số đơn vị). Túi ≥ 300 ml dùng quy cách "350ML".
SEPARATE = {"350ML": [("RBC", "350ML", 1), ("FFP", "STANDARD", 1)], "250ML": [("RBC", "250ML", 1), ("FFP", "STANDARD", 1)]}
WHOLE = {"350ML": [("WB", "350ML", 1)], "250ML": [("WB", "250ML", 1)]}


def yield_plan(donation, mode="tach"):
    """Chế phẩm thu được từ một lượt hiến đạt xét nghiệm: [(ProductSpec, số đơn vị)].

    mode "tach": máu toàn phần → khối hồng cầu + huyết tương; hiến thành phần → đúng chế phẩm đã gạn.
    mode "nguyen": giữ máu toàn phần (không tách). Trả [] nếu không có quy tắc phù hợp → nhân viên chọn tay.
    """
    active = ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
    if donation.donation_type == "component":
        if not donation.component_product_id:
            return []
        spec = active.filter(product_id=donation.component_product_id).order_by("-is_default", "pk").first()
        qty = int(donation.component_quantity) if donation.component_unit == "unit" and donation.component_quantity else 1
        return [(spec, max(1, qty))] if spec else []
    if donation.donation_type != "whole_blood":
        return []
    size = "250ML" if donation.volume_ml and donation.volume_ml < 300 else "350ML"
    out = []
    for product, code, qty in (SEPARATE if mode == "tach" else WHOLE)[size]:
        spec = active.filter(product__code=product, code=code).first()
        if spec is None:
            return []          # thiếu quy cách trong danh mục → không đoán, để nhân viên chọn tay
        out.append((spec, qty))
    return out


def default_spec(donation):
    """Quy cách gợi ý: thành phần → quy cách mặc định của chế phẩm; toàn phần → túi đúng thể tích (nếu có)."""
    specs = ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
    if donation.donation_type == "component" and donation.component_product_id:
        return specs.filter(product_id=donation.component_product_id).order_by("-is_default", "pk").first()
    whole = specs.filter(product__kind="whole_blood")
    if donation.volume_ml:
        exact = whole.filter(unit_volume_ml=donation.volume_ml).first()
        if exact:
            return exact
    return whole.order_by("-is_default", "pk").first()


def record_lab_result(staff, donation_id, result, data, key, request=None):
    """result = 'passed' (nhập kho) | 'failed' (không nhập, bắt buộc ghi chú)."""
    require(result in (L.PASSED, L.FAILED), "ERR-VALIDATION", "Chọn kết quả xét nghiệm.")
    note = (data.get("lab_note") or "").strip()[:500] or None
    with business_transaction():
        d = Donation.objects.select_for_update().filter(pk=donation_id, hospital=staff.hospital).first()
        if d is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(d.status == Donation.Status.CONFIRMED, "ERR-DON-VOIDED-IMMUTABLE")
        if d.lab_status != L.PENDING:
            # Gửi lại cùng thao tác (bấm 2 lần) → trả kết quả cũ, không nhập kho 2 lần
            if d.lab_status == result:
                return d
            raise BusinessError("ERR-STATE-INVALID", "Lượt hiến này đã có kết quả xét nghiệm.")
        old = snapshot(d, ["lab_status", "lab_blood_group", "lab_note"])
        now = timezone.now()
        if result == L.PASSED:
            blood_group = data.get("blood_group")
            require(blood_group in BLOOD_GROUP_VALUES, "ERR-VALIDATION", "Chọn nhóm máu theo kết quả xét nghiệm.")
            mode = data.get("mode")
            if mode in ("tach", "nguyen"):          # hệ thống tự tính chế phẩm theo quy tắc điều chế
                items = yield_plan(d, mode)
                require(items, "ERR-VALIDATION", "Không có quy tắc điều chế cho lượt hiến này — chọn chế phẩm thủ công.")
            else:                                   # nhân viên tự chọn một chế phẩm (trường hợp đặc biệt)
                spec = ProductSpec.objects.select_related("product").filter(pk=as_id(data.get("product_spec_id"))).first()
                require(spec is not None, "ERR-VALIDATION", "Chọn chế phẩm / quy cách nhập kho.")
                require(spec.is_active and spec.product.is_active, "ERR-CAT-INACTIVE")
                items = [(spec, positive_int(data.get("quantity") or 1))]
            max_units = SystemSetting.get("lab_max_units_per_donation")
            require(sum(q for _, q in items) <= max_units, "ERR-VALIDATION",
                    f"Một lượt hiến nhập tối đa {max_units} đơn vị (chỉnh ở Quản trị, mục Cấu hình).")
            for i, (spec, qty) in enumerate(items):
                stock = get_or_create_stock_locked(staff.hospital, blood_group, spec)
                txn = apply_txn(stock, StockTxn.Type.RECEIVE, qty, staff.user, key if i == 0 else f"{key}:{i}", donation=d,
                                note=f"Nhập từ lượt hiến {d.code} (xét nghiệm đạt)")
                audit(staff.user, txn, "create", new=snapshot(txn), hospital=staff.hospital, request=request)
            d.lab_blood_group = blood_group
        else:
            require(note, "ERR-VALIDATION", "Ghi rõ lý do không đạt.")
        d.lab_status, d.lab_note, d.lab_checked_by, d.lab_checked_at = result, note, staff.user, now
        d.save(update_fields=["lab_status", "lab_blood_group", "lab_note", "lab_checked_by", "lab_checked_at",
                              "updated_at"])
        audit(staff.user, d, "lab_result", old=old, new=snapshot(d, ["lab_status", "lab_blood_group", "lab_note"]),
              hospital=staff.hospital, request=request)
    return d
