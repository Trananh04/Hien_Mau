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
            require(change != 0, "ERR-VALIDATION", "Số đếm thực tế bằng tồn hiện có, không cần điều chỉnh.")
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
        require(version is not None, "ERR-VALIDATION", "Thiếu phiên bản dữ liệu. Vui lòng tải lại trang.")
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


def stock_overview(hospital, product_id=None):
    """SCR-30: ma trận nhóm máu × quy cách, danh sách chi tiết và số tổng — lọc theo chế phẩm nếu có."""
    from accounts.models import BLOOD_GROUP_VALUES

    specs = list(ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
                 .order_by("product__kind", "product__name", "code"))
    rows = {(s.blood_group, s.product_spec_id): s for s in Stock.objects.filter(hospital=hospital)}
    short = {(r["blood_group"], r["spec"].pk): r["shortage"] for r in shortages(hospital)}
    shown_specs = [s for s in specs if not product_id or str(s.product_id) == str(product_id)]
    matrix = [{"bg": bg, "cells": [{"spec": spec, "stock": rows.get((bg, spec.pk)), "short": short.get((bg, spec.pk), 0)}
                                   for spec in shown_specs]} for bg in BLOOD_GROUP_VALUES]
    by_pk = {s.pk: s for s in specs}
    detail = sorted(rows.values(), key=lambda s: (s.product_spec_id, s.blood_group))
    for s in detail:
        s.spec = by_pk.get(s.product_spec_id)
    detail = [s for s in detail if s.spec and (not product_id or str(s.spec.product_id) == str(product_id))]
    totals = {"on_hand": sum(s.quantity_on_hand for s in rows.values()),
              "reserved": sum(s.quantity_reserved for s in rows.values()),
              "low": sum(1 for s in rows.values() if s.below_min), "short": sum(1 for v in short.values() if v > 0)}
    return {"matrix": matrix, "specs": shown_specs, "detail": detail, "totals": totals, "all_specs": specs}


def stock_alerts(hospital, limit=8):
    """Tổng quan: các dòng kho cần chú ý, gộp theo (nhóm máu, quy cách).

    level "danger" = nhu cầu đang mở vượt tồn khả dụng (thiếu); "warn" = khả dụng dưới mức tối thiểu đã khai.
    Khả dụng = hiện có − đang giữ chỗ (không dùng tổng tồn). Chỉ đọc, không ghi gì.
    """
    stocks = {(s.blood_group, s.product_spec_id): s
              for s in Stock.objects.filter(hospital=hospital).select_related("product_spec__product")}
    rows = {}
    for r in shortages(hospital):
        if r["shortage"] <= 0:
            continue
        st = stocks.get((r["blood_group"], r["spec"].pk))
        rows[(r["blood_group"], r["spec"].pk)] = {
            "blood_group": r["blood_group"], "spec": r["spec"], "available": r["available"],
            "min_level": st.min_stock_level if st else 0, "required": r["required"], "shortage": r["shortage"],
            "level": "danger", "stock": st,
        }
    for key, st in stocks.items():
        if st.below_min and key not in rows:
            rows[key] = {"blood_group": st.blood_group, "spec": st.product_spec, "available": st.available,
                         "min_level": st.min_stock_level, "required": None,
                         "shortage": st.min_stock_level - st.available, "level": "warn", "stock": st}
    ordered = sorted(rows.values(), key=lambda r: (r["level"] != "danger", -r["shortage"], r["blood_group"]))
    on_hand = sum(s.quantity_on_hand for s in stocks.values())
    reserved = sum(s.quantity_reserved for s in stocks.values())
    return {"rows": ordered[:limit], "more": max(0, len(ordered) - limit),
            "danger": sum(1 for r in ordered if r["level"] == "danger"),
            "warn": sum(1 for r in ordered if r["level"] == "warn"),
            "on_hand": on_hand, "reserved": reserved, "available": on_hand - reserved}


def urgent_deadline(now=None):
    """Mốc phân loại: cần trước thời điểm này = KHẨN (cấu hình `shortage_urgent_hours`)."""
    from datetime import timedelta

    from bloodbank.models import SystemSetting

    return (now or timezone.now()) + timedelta(hours=SystemSetting.get("shortage_urgent_hours"))


def shortages(hospital, now=None):
    """BR-43: Thiếu = MAX(0, SUM nhu cầu active cùng khóa − khả dụng); tính một lần mỗi khóa.

    Mỗi dòng có thêm mức: KHẨN nếu một nhu cầu cùng khóa cần trước `shortage_urgent_hours` giờ tới, còn lại THIẾU KHO.
    Dòng khẩn xếp trước, rồi tới dòng thiếu nhiều.
    """
    from django.db.models import Min

    deadline = urgent_deadline(now)
    rows = (
        Demand.objects.filter(hospital=hospital, status=Demand.Status.ACTIVE)
        .values("blood_group", "product_spec")
        .annotate(required=Sum("required_quantity"), needed_by=Min("needed_by"))
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
        shortage = max(0, r["required"] - available)
        result.append({
            "blood_group": r["blood_group"], "spec": specs[r["product_spec"]], "required": r["required"],
            "available": available, "shortage": shortage,
            "below_min": bool(stock and stock.below_min), "needed_by": r["needed_by"],
            "urgent": bool(shortage and r["needed_by"] and r["needed_by"] <= deadline),
        })
    result.sort(key=lambda x: (not x["urgent"], -x["shortage"], x["blood_group"]))
    return result


def urgent_requests(hospital):
    """Yêu cầu cần máu ĐÃ XÁC MINH còn thiếu — luôn là KHẨN (có người bệnh đang chờ).

    Còn thiếu = số đơn vị yêu cầu − số đã xuất kho cho yêu cầu. Kèm số khả dụng đúng nhóm máu (và chế phẩm, nếu yêu cầu
    có ghi) để nhân viên biết xuất ngay được hay phải xin liên viện / kêu gọi khẩn.
    """
    P = PatientRequest.Status
    prqs = list(PatientRequest.objects.filter(hospital=hospital, status__in=[P.VERIFIED, P.PROCESSING],
                                              blood_group__isnull=False)
                .exclude(emergency_demands__status=Demand.Status.ACTIVE)
                .select_related("blood_product", "linked_support_request").order_by("needed_by", "created_at"))
    issued = dict(StockTxn.objects.filter(patient_request__in=prqs, txn_type=T.ISSUE).values_list("patient_request")
                  .annotate(n=Sum("quantity_change")).values_list("patient_request", "n"))
    result = []
    for p in prqs:
        remaining = p.quantity_units + (issued.get(p.pk) or 0)          # quantity_change của phiếu xuất là số âm
        if remaining <= 0:
            continue
        stocks = Stock.objects.filter(hospital=hospital, blood_group=p.blood_group)
        if p.blood_product_id:
            stocks = stocks.filter(product_spec__product_id=p.blood_product_id)
        available = sum(s.available for s in stocks)
        result.append({"prq": p, "blood_group": p.blood_group, "remaining": remaining, "available": available,
                       "covered": available >= remaining, "shortage": max(0, remaining - available)})
    return result
