"""UC-SRC-01, UC-HRQ-01..04, UC-TRF-01..04: tra cứu, yêu cầu hỗ trợ, điều chuyển liên viện.

Thứ tự khóa chuẩn: hospital_requests → request_offers → stocks (BR-45).
"""
from django.db.models import Q
from django.utils import timezone

from bloodbank.models import Hospital, HospitalRequest, PatientRequest, ProductSpec, RequestOffer, Stock, StockTxn

from .common import (
    BusinessError, alert, as_id, audit, business_transaction, create_with_code, hospital_staff_users,
    notify_hospital_staff, positive_int, require, snapshot,
)
from .inventory import apply_txn, change_reserved, get_or_create_stock_locked

O = RequestOffer.Status
H = HospitalRequest.Status


# ---------------------------------------------------------------- Tra cứu (BR-16, BR-42)
def distance_km(a, b):
    """Khoảng cách đường chim bay giữa 2 bệnh viện (km); None nếu thiếu tọa độ."""
    import math

    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return None
    lat1, lng1, lat2, lng2 = map(lambda v: math.radians(float(v)), (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


def search_sources(hospital, blood_group, product_id, spec_id=None, min_qty=None, province=None):
    """Nguồn có thể hỗ trợ, xếp hạng: gần trước (cùng chuyến đi nhanh hơn), cùng khoảng cách thì nhiều hơn trước."""
    qs = Stock.objects.filter(
        blood_group=blood_group, product_spec__product_id=product_id, hospital__status="active",
        shareable_quantity__gt=0,
    ).exclude(hospital=hospital).select_related("hospital", "product_spec__product")
    if spec_id:
        qs = qs.filter(product_spec_id=spec_id)
    if province:
        qs = qs.filter(hospital__province=province)
    rows = []
    for s in qs:
        can = s.effective_shareable  # chỉ số chia sẻ hiệu lực, không lộ on_hand/reserved
        if can <= 0 or (min_qty and can < int(min_qty)):
            continue
        rows.append({"stock_id": s.pk, "hospital": s.hospital, "spec": s.product_spec, "can_support": can,
                     "updated_at": s.updated_at, "distance_km": distance_km(hospital, s.hospital)})
    rows.sort(key=lambda r: (r["distance_km"] is None, r["distance_km"] or 0, -r["can_support"], r["hospital"].name))
    return rows


def suggest_allocation(rows, quantity, spec_id):
    """Chia số cần cho các nguồn theo thứ hạng (tham lam): lấy hết phần chia sẻ của nguồn gần nhất rồi tới nguồn kế.

    Chỉ tính nguồn đúng quy cách của yêu cầu (đề nghị phải cùng quy cách). Trả về {hospital_id: số đề nghị}.
    """
    try:
        remaining = int(quantity or 0)
    except (TypeError, ValueError):
        return {}
    plan = {}
    for r in rows:
        if remaining <= 0:
            break
        if str(r["spec"].pk) != str(spec_id) or r["hospital"].pk in plan:
            continue
        take = min(r["can_support"], remaining)
        plan[r["hospital"].pk] = take
        remaining -= take
    return plan


# ---------------------------------------------------------------- Số liệu yêu cầu (Ch.4 mục 4.0)
def request_numbers(req):
    offers = list(req.offers.all())
    committed = sum(o.quantity or 0 for o in offers if o.status == O.ACCEPTED)
    transit = sum(o.quantity or 0 for o in offers if o.status == O.IN_TRANSIT)
    received = sum(o.quantity_received or 0 for o in offers if o.status == O.COMPLETED)
    remaining = max(0, req.quantity_needed - committed - transit - received)
    return {"needed": req.quantity_needed, "committed": committed, "transit": transit, "received": received,
            "remaining": remaining}


def recompute_status(req, now=None):
    """BR-46: trạng thái yêu cầu suy ra từ offer; gọi trong cùng giao dịch."""
    if req.status in (H.FULFILLED, H.CANCELLED, H.EXPIRED):
        return req
    n = request_numbers(req)
    statuses = set(req.offers.values_list("status", flat=True))
    if n["received"] >= req.quantity_needed:
        req.status, req.closed_at = H.FULFILLED, now or timezone.now()
        _release_open_offers(req, None)   # đã đủ: đề nghị còn chờ / đã giữ chỗ ở bệnh viện khác không cần nữa
    elif O.COMPLETED in statuses:
        req.status = H.PARTIALLY_FULFILLED
    elif statuses & {O.ACCEPTED, O.IN_TRANSIT}:
        req.status = H.IN_PROGRESS
    else:
        req.status = H.OPEN
    req.save(update_fields=["status", "closed_at", "updated_at"])
    return req


def expire_overdue(hospital=None):
    """Yêu cầu quá needed_by và không còn hàng đang chuyển → expired (giải phóng giữ chỗ).

    Đã nhận một phần thì không "hết hạn" mà được ĐÓNG (giữ trạng thái đáp ứng một phần), cũng trả giữ chỗ còn treo.
    """
    now = timezone.now()
    qs = HospitalRequest.objects.filter(needed_by__lt=now, closed_at__isnull=True,
                                        status__in=[H.OPEN, H.IN_PROGRESS, H.PARTIALLY_FULFILLED])
    if hospital is not None:
        qs = qs.filter(Q(requesting_hospital=hospital) | Q(offers__supplier_hospital=hospital)).distinct()
    for req_id in list(qs.values_list("pk", flat=True)):
        with business_transaction():
            req = HospitalRequest.objects.select_for_update().get(pk=req_id)
            if (req.status not in (H.OPEN, H.IN_PROGRESS, H.PARTIALLY_FULFILLED) or req.closed_at
                    or req.offers.filter(status=O.IN_TRANSIT).exists()):
                continue
            _release_open_offers(req, None)
            if req.status == H.PARTIALLY_FULFILLED:
                req.closed_at = now
                req.save(update_fields=["closed_at", "updated_at"])
                audit(None, req, "status_change", new={"closed_at": now, "reason": "overdue"},
                      hospital=req.requesting_hospital)
                notify_hospital_staff(req.requesting_hospital, "request_expired",
                                      f"Yêu cầu hỗ trợ {req.request_code} quá hạn, đã đóng (nhận một phần)", entity=req)
                continue
            req.status, req.closed_at = H.EXPIRED, now
            req.save(update_fields=["status", "closed_at", "updated_at"])
            audit(None, req, "status_change", new={"status": "expired"}, hospital=req.requesting_hospital)
            notify_hospital_staff(req.requesting_hospital, "request_expired",
                                  f"Yêu cầu hỗ trợ {req.request_code} đã hết hạn", entity=req)


def _release_open_offers(req, actor):
    for offer in req.offers.select_for_update().filter(status__in=[O.PENDING, O.ACCEPTED]):
        if offer.status == O.ACCEPTED:
            stock = Stock.objects.select_for_update().get(
                hospital_id=offer.supplier_hospital_id, blood_group=req.blood_group, product_spec_id=req.product_spec_id
            )
            change_reserved(stock, -offer.quantity)
            audit(actor, stock, "reserve_release", new={"offer": offer.pk, "quantity": -offer.quantity},
                  hospital=offer.supplier_hospital)
        offer.status = O.CANCELLED
        offer.save(update_fields=["status", "updated_at"])
        notify_hospital_staff(offer.supplier_hospital, "offer_cancelled",
                              f"Đề nghị cho yêu cầu {req.request_code} đã bị hủy", entity=offer)


# ---------------------------------------------------------------- Bên yêu cầu
def _supplier_list(staff, suppliers):
    clean = []
    for hospital_id, qty in suppliers:
        hospital_id = as_id(hospital_id)
        require(hospital_id is not None, "ERR-NOT-FOUND")
        if hospital_id == staff.hospital_id:
            raise BusinessError("ERR-HRQ-SELF-SUPPLY")
        hospital = Hospital.objects.filter(pk=hospital_id, status="active").first()
        require(hospital is not None, "ERR-NOT-FOUND")
        clean.append((hospital, positive_int(qty, "ERR-TRF-QTY-MISMATCH") if qty not in (None, "") else None))
    return clean


def create_request(staff, data, suppliers, patient_request_id=None, request=None):
    """UC-HRQ-01: tạo phiếu + mời bệnh viện cấp (offer pending)."""
    qty = positive_int(data.get("quantity_needed"))
    spec = ProductSpec.objects.filter(pk=as_id(data.get("product_spec_id")), is_active=True, product__is_active=True).first()
    require(spec is not None, "ERR-CAT-INACTIVE")
    priority = data.get("priority") or "normal"
    require(priority in ("low", "normal", "high", "urgent"), "ERR-VALIDATION")
    clean_suppliers = _supplier_list(staff, suppliers)
    with business_transaction():
        prq = None
        if patient_request_id:
            prq = PatientRequest.objects.select_for_update().filter(pk=as_id(patient_request_id)).first()
            if prq is None or prq.hospital_id != staff.hospital_id:
                raise BusinessError("ERR-PRQ-WRONG-HOSPITAL")
            if prq.status not in (PatientRequest.Status.VERIFIED, PatientRequest.Status.PROCESSING):
                raise BusinessError("ERR-PRQ-NOT-VERIFIED")
        req = create_with_code(
            HospitalRequest, "request_code", "HR", requesting_hospital=staff.hospital, blood_group=data["blood_group"],
            product_spec=spec, quantity_needed=qty, priority=priority, needed_by=data.get("needed_by"),
            note=data.get("note") or None, created_by=staff.user,
        )
        audit(staff.user, req, "create", new=snapshot(req), hospital=staff.hospital, request=request)
        for hospital, q in clean_suppliers:
            _invite(staff, req, hospital, q, request)
        if prq:
            old = prq.status
            prq.linked_support_request = req
            if prq.status == PatientRequest.Status.VERIFIED:
                prq.status = PatientRequest.Status.PROCESSING
            prq.save(update_fields=["linked_support_request", "status", "updated_at"])
            audit(staff.user, prq, "link_support_request", old={"status": old},
                  new={"status": prq.status, "linked_support_request_id": req.pk}, hospital=staff.hospital,
                  request=request)
    return req


def _invite(staff, req, hospital, qty, request):
    offer = RequestOffer.objects.select_for_update().filter(request=req, supplier_hospital=hospital).first()
    if offer:
        require(offer.status in (O.REJECTED, O.CANCELLED), "ERR-STATE-INVALID", "Bệnh viện này đã có đề nghị đang mở.")
        require(offer.dispatched_at is None, "ERR-STATE-INVALID", "Đề nghị đã từng xuất hàng, không thể mời lại.")
        offer.status, offer.quantity_requested, offer.quantity = O.PENDING, qty, None
        offer.reject_reason = offer.responded_at = offer.responded_by = None
        offer.save()
        action = "reinvite"
    else:
        offer = RequestOffer.objects.create(request=req, supplier_hospital=hospital, quantity_requested=qty)
        action = "create"
    audit(staff.user, offer, action, new=snapshot(offer), hospital=staff.hospital, request=request)
    title = f"{'[Khẩn] ' if req.priority == 'urgent' else ''}Đề nghị hỗ trợ mới: {req.request_code} ({req.blood_group})"
    body = f"{staff.hospital.name} đề nghị hỗ trợ {qty or ''} đơn vị.".replace("  ", " ")
    if req.priority in ("urgent", "high"):   # cần phản hồi nhanh: thông báo trong ứng dụng + email
        alert(hospital_staff_users(hospital), "offer_received", title, body, entity=offer)
    else:
        notify_hospital_staff(hospital, "offer_received", title, body, entity=offer)
    return offer


def invite_more(staff, req_id, hospital_id, qty, request=None):
    with business_transaction():
        req = HospitalRequest.objects.select_for_update().filter(pk=req_id, requesting_hospital=staff.hospital).first()
        if req is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(not req.is_final and req.closed_at is None, "ERR-HRQ-CLOSED")
        (hospital, q), = _supplier_list(staff, [(hospital_id, qty)])
        return _invite(staff, req, hospital, q, request)


def _lock_request_offer(offer_id, **offer_filter):
    offer = RequestOffer.objects.filter(pk=as_id(offer_id), **offer_filter).first()
    if offer is None:
        raise BusinessError("ERR-NOT-FOUND")
    req = HospitalRequest.objects.select_for_update().get(pk=offer.request_id)
    offer = RequestOffer.objects.select_for_update().select_related("supplier_hospital").get(pk=offer.pk)
    return req, offer


def _supplier_stock(req, offer):
    return Stock.objects.select_for_update().filter(
        hospital_id=offer.supplier_hospital_id, blood_group=req.blood_group, product_spec_id=req.product_spec_id
    ).first()


def cancel_offer_by_requester(staff, offer_id, request=None):
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, request__requesting_hospital=staff.hospital)
        require(offer.status in (O.PENDING, O.ACCEPTED), "ERR-STATE-INVALID")
        if offer.status == O.ACCEPTED:
            stock = _supplier_stock(req, offer)
            change_reserved(stock, -offer.quantity)
            audit(staff.user, stock, "reserve_release", new={"offer": offer.pk, "quantity": -offer.quantity},
                  hospital=offer.supplier_hospital, request=request)
        old = offer.status
        offer.status = O.CANCELLED
        offer.save(update_fields=["status", "updated_at"])
        audit(staff.user, offer, "status_change", old={"status": old}, new={"status": offer.status},
              hospital=staff.hospital, request=request)
        recompute_status(req)
        notify_hospital_staff(offer.supplier_hospital, "offer_cancelled",
                              f"{req.requesting_hospital.name} đã rút đề nghị {req.request_code}", entity=offer)
    return offer


def confirm_received(staff, offer_id, received_qty, key, returned_to_supplier=False, note=None, request=None):
    """UC-TRF-03: bên nhận xác nhận số thực nhận r ≤ q → transfer_in +r; phần chênh lệch có thể quay về bên cấp."""
    try:
        r = int(received_qty)
    except (TypeError, ValueError):
        raise BusinessError("ERR-TRF-QTY-MISMATCH")
    require(r >= 0, "ERR-TRF-QTY-MISMATCH")
    now = timezone.now()
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, request__requesting_hospital=staff.hospital)
        if offer.status == O.COMPLETED and StockTxn.objects.filter(idempotency_key=key).exists():
            return offer  # gửi lại cùng khóa
        require(offer.status == O.IN_TRANSIT, "ERR-STATE-INVALID")
        if r > offer.quantity:
            raise BusinessError("ERR-TRF-RECEIVED-EXCEEDS")
        if r > 0:
            stock = get_or_create_stock_locked(staff.hospital, req.blood_group, req.product_spec)
            apply_txn(stock, StockTxn.Type.TRANSFER_IN, r, staff.user, key, offer=offer)
        if returned_to_supplier and r < offer.quantity:
            sup = _supplier_stock(req, offer)
            apply_txn(sup, StockTxn.Type.TRANSFER_RETURN, offer.quantity - r, staff.user, f"{key}:return", offer=offer)
        offer.status, offer.quantity_received, offer.received_by, offer.received_at = O.COMPLETED, r, staff.user, now
        if note:
            offer.note = ((offer.note + "\n") if offer.note else "") + note
        offer.save()
        audit(staff.user, offer, "received", new={"quantity_received": r, "returned": returned_to_supplier},
              hospital=staff.hospital, request=request)
        recompute_status(req, now)
        notify_hospital_staff(offer.supplier_hospital, "offer_received_confirmed",
                              f"{staff.hospital.name} đã xác nhận nhận {r} đơn vị ({req.request_code})", entity=offer)
    return offer


def cancel_or_close_request(staff, req_id, action, reason=None, request=None):
    """UC-HRQ-04: hủy (chưa có in_transit, giải phóng giữ chỗ) hoặc đóng khi đáp ứng một phần."""
    now = timezone.now()
    with business_transaction():
        req = HospitalRequest.objects.select_for_update().filter(pk=req_id, requesting_hospital=staff.hospital).first()
        if req is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(not req.is_final and req.closed_at is None, "ERR-HRQ-CLOSED")
        if req.offers.filter(status=O.IN_TRANSIT).exists():
            raise BusinessError("ERR-HRQ-HAS-IN-TRANSIT")
        old = req.status
        _release_open_offers(req, staff.user)
        if action == "cancel":
            require(req.status in (H.OPEN, H.IN_PROGRESS), "ERR-STATE-INVALID",
                    "Yêu cầu đã nhận một phần. Hãy dùng Đóng yêu cầu.")
            req.status = H.CANCELLED
        elif action == "close":
            require(req.status == H.PARTIALLY_FULFILLED, "ERR-STATE-INVALID")
        else:
            raise BusinessError("ERR-STATE-INVALID")
        req.closed_at = now
        if reason:
            req.note = ((req.note + "\n") if req.note else "") + f"[Đóng/hủy] {reason}"
        req.save()
        audit(staff.user, req, "status_change", old={"status": old},
              new={"status": req.status, "closed_at": now, "reason": reason}, hospital=staff.hospital, request=request)
    return req


# ---------------------------------------------------------------- Bên cấp
def accept_offer(staff, offer_id, quantity, note=None, request=None):
    """UC-TRF-01: chấp thuận q ≤ MIN(khả dụng, còn thiếu) → giữ chỗ reserved +q."""
    q = positive_int(quantity, "ERR-TRF-QTY-MISMATCH")
    now = timezone.now()
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, supplier_hospital=staff.hospital)
        require(offer.status == O.PENDING, "ERR-STATE-INVALID")
        require(not req.is_final and req.closed_at is None, "ERR-HRQ-CLOSED")
        remaining = request_numbers(req)["remaining"]
        if q > remaining:
            raise BusinessError("ERR-HRQ-OVER-NEEDED", f"Yêu cầu chỉ còn thiếu {remaining} đơn vị.")
        stock = _supplier_stock(req, offer)
        available = stock.available if stock else 0
        if stock is None or q > available:
            raise BusinessError("ERR-INV-INSUFFICIENT", f"Chỉ còn {available} đơn vị khả dụng.")
        change_reserved(stock, q)
        audit(staff.user, stock, "reserve", new={"offer": offer.pk, "quantity": q}, hospital=staff.hospital,
              request=request)
        offer.status, offer.quantity, offer.responded_by, offer.responded_at = O.ACCEPTED, q, staff.user, now
        if note:
            offer.note = note
        offer.save()
        audit(staff.user, offer, "status_change", old={"status": "pending"}, new={"status": "accepted", "quantity": q},
              hospital=staff.hospital, request=request)
        recompute_status(req)
        notify_hospital_staff(req.requesting_hospital, "offer_accepted",
                              f"{staff.hospital.name} chấp thuận {q} đơn vị cho {req.request_code}", entity=offer)
    return offer


def reject_offer(staff, offer_id, reason, request=None):
    reason = (reason or "").strip()
    require(reason, "ERR-DON-REASON-REQUIRED", "Vui lòng nhập lý do từ chối.")
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, supplier_hospital=staff.hospital)
        require(offer.status == O.PENDING, "ERR-STATE-INVALID")
        offer.status, offer.reject_reason = O.REJECTED, reason[:500]
        offer.responded_by, offer.responded_at = staff.user, timezone.now()
        offer.save()
        audit(staff.user, offer, "status_change", old={"status": "pending"}, new={"status": "rejected", "reason": reason},
              hospital=staff.hospital, request=request)
        recompute_status(req)
        notify_hospital_staff(req.requesting_hospital, "offer_rejected",
                              f"{staff.hospital.name} từ chối đề nghị {req.request_code}", reason, entity=offer)
    return offer


def cancel_offer_by_supplier(staff, offer_id, reason=None, request=None):
    """Hủy trước khi xuất: reserved −q."""
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, supplier_hospital=staff.hospital)
        require(offer.status == O.ACCEPTED, "ERR-STATE-INVALID")
        stock = _supplier_stock(req, offer)
        change_reserved(stock, -offer.quantity)
        audit(staff.user, stock, "reserve_release", new={"offer": offer.pk, "quantity": -offer.quantity},
              hospital=staff.hospital, request=request)
        offer.status = O.CANCELLED
        if reason:
            offer.note = ((offer.note + "\n") if offer.note else "") + f"[Hủy] {reason}"
        offer.save()
        audit(staff.user, offer, "status_change", old={"status": "accepted"}, new={"status": "cancelled"},
              hospital=staff.hospital, request=request)
        recompute_status(req)
        notify_hospital_staff(req.requesting_hospital, "offer_cancelled",
                              f"{staff.hospital.name} đã hủy phần hỗ trợ cho {req.request_code}", reason, entity=offer)
    return offer


def dispatch_offer(staff, offer_id, key, request=None):
    """UC-TRF-02: xác nhận xuất → transfer_out (on_hand −q, reserved −q)."""
    now = timezone.now()
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, supplier_hospital=staff.hospital)
        if offer.status == O.IN_TRANSIT and StockTxn.objects.filter(idempotency_key=key).exists():
            return offer
        require(offer.status == O.ACCEPTED, "ERR-STATE-INVALID")
        stock = _supplier_stock(req, offer)
        apply_txn(stock, StockTxn.Type.TRANSFER_OUT, -offer.quantity, staff.user, key, offer=offer,
                  reserved_delta=-offer.quantity)
        offer.status, offer.dispatched_by, offer.dispatched_at = O.IN_TRANSIT, staff.user, now
        offer.save()
        audit(staff.user, offer, "dispatched", new={"quantity": offer.quantity}, hospital=staff.hospital,
              request=request)
        recompute_status(req)
        notify_hospital_staff(req.requesting_hospital, "offer_dispatched",
                              f"{staff.hospital.name} đã xuất {offer.quantity} đơn vị cho {req.request_code}",
                              "Vui lòng xác nhận số thực nhận khi hàng tới.", entity=offer)
    return offer


def report_failure(staff, offer_id, reason, returned_qty, key, request=None):
    """UC-TRF-04: bên cấp báo giao nhận thất bại; hàng quay về → transfer_return."""
    reason = (reason or "").strip()
    require(reason, "ERR-TRF-FAILURE-REASON-REQUIRED")
    try:
        back = int(returned_qty or 0)
    except (TypeError, ValueError):
        raise BusinessError("ERR-TRF-QTY-MISMATCH")
    with business_transaction():
        req, offer = _lock_request_offer(offer_id, supplier_hospital=staff.hospital)
        require(offer.status == O.IN_TRANSIT, "ERR-STATE-INVALID")
        require(0 <= back <= offer.quantity, "ERR-TRF-QTY-MISMATCH", f"Số quay về tối đa {offer.quantity}.")
        if back > 0:
            stock = _supplier_stock(req, offer)
            apply_txn(stock, StockTxn.Type.TRANSFER_RETURN, back, staff.user, key, offer=offer)
        offer.status, offer.failure_reason = O.FAILED, reason[:500]
        offer.save()
        audit(staff.user, offer, "status_change", old={"status": "in_transit"},
              new={"status": "failed", "reason": reason, "returned": back}, hospital=staff.hospital, request=request)
        recompute_status(req)
        notify_hospital_staff(req.requesting_hospital, "offer_failed",
                              f"Giao nhận {req.request_code} từ {staff.hospital.name} thất bại", reason, entity=offer)
    return offer


def suggested_offer_quantity(offer, available):
    """Số gợi ý khi bệnh viện cấp chấp thuận: không vượt số được hỏi, số còn thiếu và số khả dụng trong kho."""
    remaining = request_numbers(offer.request)["remaining"]
    asked = offer.quantity_requested or remaining
    return max(min(x for x in (asked, available, remaining) if x is not None), 0)


def offer_actions(offer, side, staff):
    """Nút theo trạng thái (Ch.7 mục 7.7)."""
    s = offer.status
    if side == "supplier":
        acts = {"pending": ["accept", "reject"], "accepted": ["dispatch", "cancel"]}.get(s, [])
        if s == O.IN_TRANSIT:
            acts = ["fail"]
        return acts
    acts = {"pending": ["cancel"], "accepted": ["cancel"], "in_transit": ["receive"]}.get(s, [])
    if s in (O.REJECTED, O.CANCELLED) and offer.dispatched_at is None:
        acts = ["reinvite"]
    return acts
