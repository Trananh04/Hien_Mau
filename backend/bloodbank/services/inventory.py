"""UC-INV-01..06, UC-DEM-01..03: tồn kho, phiếu kho, sổ kho, nhu cầu & thiếu hụt.

TX-STOCK: khóa dòng tồn FOR UPDATE → kiểm tra → ghi đúng 1 dòng stock_txns (before/after) → cập nhật số dư.
"""
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from bloodbank.models import Demand, PatientRequest, ProductSpec, Stock, StockTxn

from .common import BusinessError, as_id, audit, business_transaction, positive_int, require, snapshot

T = StockTxn.Type


def get_or_create_stock_locked(hospital, blood_group, spec):
    """BR-36: tạo dòng tồn lười, không sinh trùng khi đồng thời; trả về dòng đã khóa."""
    stock = Stock.objects.select_for_update().filter(hospital=hospital, blood_group=blood_group, product_spec=spec).first()
    if stock:
        return stock
    try:
        with transaction.atomic():
            Stock.objects.create(hospital=hospital, blood_group=blood_group, product_spec=spec)
    except IntegrityError:
        pass  # tạo đồng thời — dòng đã có
    return Stock.objects.select_for_update().get(hospital=hospital, blood_group=blood_group, product_spec=spec)


def change_reserved(stock, delta):
    """Giữ chỗ chỉ đổi khi chấp thuận/hủy/xuất offer (BR-38); luôn tăng version."""
    if stock.quantity_reserved + delta < 0 or stock.quantity_reserved + delta > stock.quantity_on_hand:
        raise BusinessError("ERR-INV-INSUFFICIENT", f"Chỉ còn {stock.available} đơn vị khả dụng.")
    stock.quantity_reserved += delta
    stock.version = F("version") + 1
    stock.save(update_fields=["quantity_reserved", "version", "updated_at"])
    stock.refresh_from_db()


def _replay(key, stock_id, txn_type, change):
    """EX-COM-07 / BR-40: cùng khóa + cùng nội dung → trả kết quả cũ; khác nội dung → lỗi."""
    existing = StockTxn.objects.filter(idempotency_key=key).first()
    if existing is None:
        return None
    if existing.stock_id == stock_id and existing.txn_type == txn_type and existing.quantity_change == change:
        existing.replayed = True
        return existing
    raise BusinessError("ERR-INV-IDEMPOTENCY-MISMATCH")


def apply_txn(stock, txn_type, change, user, key, *, reason=None, note=None, offer=None, patient_request=None,
              reserved_delta=0, donation=None):
    """Ghi một biến động trên dòng tồn ĐÃ KHÓA (gọi bên trong transaction)."""
    require(key, "ERR-VALIDATION", "Thiếu mã thao tác (idempotency_key).")
    replay = _replay(key, stock.pk, txn_type, change)
    if replay:
        return replay
    before = stock.quantity_on_hand
    after = before + change
    if after < 0 or after < stock.quantity_reserved + reserved_delta:
        raise BusinessError("ERR-INV-INSUFFICIENT", f"Chỉ còn {stock.available} đơn vị khả dụng.")
    txn = StockTxn.objects.create(
        stock=stock, txn_type=txn_type, quantity_change=change, quantity_before=before, quantity_after=after,
        adjustment_reason=reason, reason_note=note, offer=offer, patient_request=patient_request, donation=donation,
        idempotency_key=key, performed_by=user, occurred_at=timezone.now(),
    )
    stock.quantity_on_hand = after
    stock.quantity_reserved += reserved_delta
    stock.version = F("version") + 1
    stock.save(update_fields=["quantity_on_hand", "quantity_reserved", "version", "updated_at"])
    stock.refresh_from_db()
    txn.replayed = False
    return txn


def receive(staff, spec_id, blood_group, quantity, key, note=None, request=None):
    """UC-INV-01: nhập kho theo số thực tế (BR-08)."""
    qty = positive_int(quantity)
    spec = ProductSpec.objects.select_related("product").filter(pk=as_id(spec_id)).first()
    require(spec is not None, "ERR-VALIDATION", "Chọn quy cách chế phẩm.")
    require(spec.is_active and spec.product.is_active, "ERR-CAT-INACTIVE")
    require(blood_group in dict(Stock._meta.get_field("blood_group").choices), "ERR-VALIDATION", "Chọn nhóm máu.")
    with business_transaction():
        stock = get_or_create_stock_locked(staff.hospital, blood_group, spec)
        txn = apply_txn(stock, T.RECEIVE, qty, staff.user, key, note=(note or None))
        if not txn.replayed:
            audit(staff.user, txn, "create", new=snapshot(txn), hospital=staff.hospital, request=request)
    return txn


def _lock_own_stock(staff, stock_id):
    stock = Stock.objects.select_for_update().filter(pk=as_id(stock_id), hospital=staff.hospital).first()
    if stock is None:
        raise BusinessError("ERR-NOT-FOUND")
    return stock


def issue(staff, stock_id, quantity, key, purpose=None, patient_request_id=None, request=None):
    """UC-INV-04: xuất kho trên phần khả dụng (BR-39); liên kết yêu cầu người cần máu chỉ khi verified/processing (BR-47)."""
    qty = positive_int(quantity)
    with business_transaction():
        prq = None
        if patient_request_id:
            prq = PatientRequest.objects.select_for_update().filter(pk=as_id(patient_request_id)).first()
            if prq is None:
                raise BusinessError("ERR-NOT-FOUND")
            if prq.hospital_id != staff.hospital_id:
                raise BusinessError("ERR-PRQ-WRONG-HOSPITAL")
            if prq.status not in (PatientRequest.Status.VERIFIED, PatientRequest.Status.PROCESSING):
                raise BusinessError("ERR-PRQ-NOT-VERIFIED")
        stock = _lock_own_stock(staff, stock_id)
        if qty > stock.available and not StockTxn.objects.filter(idempotency_key=key).exists():
            raise BusinessError("ERR-INV-INSUFFICIENT", f"Chỉ còn {stock.available} đơn vị khả dụng.")
        txn = apply_txn(stock, T.ISSUE, -qty, staff.user, key, note=(purpose or None), patient_request=prq)
        if not txn.replayed:
            audit(staff.user, txn, "create", new=snapshot(txn), hospital=staff.hospital, request=request)
            if prq and prq.status == PatientRequest.Status.VERIFIED:
                prq.status = PatientRequest.Status.PROCESSING
                prq.save(update_fields=["status", "updated_at"])
                audit(staff.user, prq, "status_change", old={"status": "verified"}, new={"status": "processing"},
                      hospital=staff.hospital, request=request)
    return txn


def adjust(staff, stock_id, direction, quantity, reason, note, key, counted=None, request=None):
    """UC-INV-05: điều chỉnh ± có lý do; giảm chỉ trên phần khả dụng. direction: increase/decrease/count."""
    require(reason in dict(StockTxn.Reason.choices) and reason != StockTxn.Reason.TRANSFER_SHORTFALL,
            "ERR-INV-REASON-REQUIRED")
    note = (note or "").strip() or None
    if reason == StockTxn.Reason.OTHER and not note:
        raise BusinessError("ERR-INV-REASON-REQUIRED")
    with business_transaction():
        stock = _lock_own_stock(staff, stock_id)
        if direction == "count":
            try:
                counted = int(counted)
            except (TypeError, ValueError):
                raise BusinessError("ERR-INV-QTY-POSITIVE", "Nhập số đếm thực tế (số nguyên ≥ 0).")
            require(counted >= 0, "ERR-INV-QTY-POSITIVE")
            change = counted - stock.quantity_on_hand
            require(change != 0, "ERR-VALIDATION", "Số đếm thực tế bằng tồn hiện có — không cần điều chỉnh.")
        else:
            qty = positive_int(quantity)
            change = qty if direction == "increase" else -qty
        if change < 0 and -change > stock.available and not StockTxn.objects.filter(idempotency_key=key).exists():
            raise BusinessError("ERR-INV-INSUFFICIENT", f"Chỉ còn {stock.available} đơn vị khả dụng.")
        txn = apply_txn(stock, T.ADJUSTMENT, change, staff.user, key, reason=reason, note=note)
        if not txn.replayed:
            audit(staff.user, txn, "create", new=snapshot(txn), hospital=staff.hospital, request=request)
    return txn


def update_stock_settings(staff, stock_id, shareable, min_level, version, request=None):
    """UC-INV-03: sửa nhanh Chia sẻ / Tối thiểu — khóa lạc quan theo `version`, không tạo giao dịch kho."""
    def parse(v, allow_null):
        if v in (None, ""):
            if allow_null:
                return None
            return 0
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise BusinessError("ERR-VALIDATION", "Giá trị phải là số nguyên ≥ 0.")
        require(n >= 0, "ERR-VALIDATION", "Giá trị phải là số nguyên ≥ 0.")
        return n

    shareable, min_level = parse(shareable, True), parse(min_level, False)
    with business_transaction():
        stock = Stock.objects.filter(pk=as_id(stock_id), hospital=staff.hospital).first()
        if stock is None:
            raise BusinessError("ERR-NOT-FOUND")
        version = as_id(version)
        require(version is not None, "ERR-VALIDATION", "Thiếu phiên bản dữ liệu — vui lòng tải lại trang.")
        old = {"shareable_quantity": stock.shareable_quantity, "min_stock_level": stock.min_stock_level}
        updated = Stock.objects.filter(pk=stock.pk, version=version).update(
            shareable_quantity=shareable, min_stock_level=min_level, version=F("version") + 1, updated_at=timezone.now()
        )
        if not updated:
            raise BusinessError("ERR-CONFLICT")
        audit(staff.user, stock, "update", old=old, new={"shareable_quantity": shareable, "min_stock_level": min_level},
              hospital=staff.hospital, request=request)


def ensure_stock_row(staff, spec_id, blood_group, min_level, shareable, request=None):
    """Khai mức tối thiểu cho khóa chưa có dòng tồn (BR-36)."""
    spec = ProductSpec.objects.filter(pk=as_id(spec_id), is_active=True).first()
    require(spec is not None, "ERR-VALIDATION", "Chọn quy cách.")
    with business_transaction():
        stock = get_or_create_stock_locked(staff.hospital, blood_group, spec)
    update_stock_settings(staff, stock.pk, shareable, min_level, stock.version, request=request)
    return stock


# ---------------------------------------------------------------- Nhu cầu & thiếu hụt
def save_demand(staff, data, demand=None, request=None):
    qty = positive_int(data.get("required_quantity"))
    spec = ProductSpec.objects.filter(pk=as_id(data.get("product_spec_id")), is_active=True, product__is_active=True).first()
    require(spec is not None, "ERR-CAT-INACTIVE")
    with business_transaction():
        if demand is None:
            demand = Demand.objects.create(
                hospital=staff.hospital, blood_group=data["blood_group"], product_spec=spec, required_quantity=qty,
                needed_by=data.get("needed_by"), note=data.get("note") or None,
            )
            audit(staff.user, demand, "create", new=snapshot(demand), hospital=staff.hospital, request=request)
        else:
            demand = Demand.objects.select_for_update().get(pk=demand.pk, hospital=staff.hospital)
            require(demand.status == Demand.Status.ACTIVE, "ERR-STATE-INVALID", "Nhu cầu không còn hiệu lực, không sửa được.")
            old = snapshot(demand)
            demand.blood_group, demand.product_spec, demand.required_quantity = data["blood_group"], spec, qty
            demand.needed_by, demand.note = data.get("needed_by"), data.get("note") or None
            demand.save()
            audit(staff.user, demand, "update", old=old, new=snapshot(demand), hospital=staff.hospital, request=request)
    return demand


def close_demand(staff, demand_id, status, request=None):
    require(status in (Demand.Status.FULFILLED, Demand.Status.CANCELLED), "ERR-STATE-INVALID")
    with business_transaction():
        demand = Demand.objects.select_for_update().filter(pk=demand_id, hospital=staff.hospital).first()
        if demand is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(demand.status == Demand.Status.ACTIVE, "ERR-STATE-INVALID")
        demand.status = status
        demand.save(update_fields=["status", "updated_at"])
        audit(staff.user, demand, "status_change", old={"status": "active"}, new={"status": status},
              hospital=staff.hospital, request=request)
    return demand


def shortages(hospital):
    """BR-43: Thiếu = MAX(0, SUM nhu cầu active cùng khóa − khả dụng); tính một lần mỗi khóa."""
    rows = (
        Demand.objects.filter(hospital=hospital, status=Demand.Status.ACTIVE)
        .values("blood_group", "product_spec")
        .annotate(required=Sum("required_quantity"))
    )
    stocks = {
        (s.blood_group, s.product_spec_id): s
        for s in Stock.objects.filter(hospital=hospital).select_related("product_spec__product")
    }
    specs = {s.pk: s for s in ProductSpec.objects.select_related("product").filter(pk__in=[r["product_spec"] for r in rows])}
    result = []
    for r in rows:
        stock = stocks.get((r["blood_group"], r["product_spec"]))
        available = stock.available if stock else 0
        result.append({
            "blood_group": r["blood_group"], "spec": specs[r["product_spec"]], "required": r["required"],
            "available": available, "shortage": max(0, r["required"] - available),
            "below_min": bool(stock and stock.below_min),
        })
    result.sort(key=lambda x: (-x["shortage"], x["blood_group"]))
    return result
