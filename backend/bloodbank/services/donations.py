"""UC-DON-01..05, UC-HIS-01..04: lượt hiến thực tế, sửa/hủy có kiểm soát, lịch sử và thống kê."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from bloodbank.models import Campaign, Donation, Product, Registration, SystemSetting

from .common import BusinessError, as_id, audit, business_transaction, notify, require, snapshot

R = Registration.Status
EDITABLE = ["donation_type", "volume_ml", "component_product_id", "component_quantity", "component_unit",
            "donated_at", "note"]


def _clean_result(data):
    """Chuẩn hóa dữ liệu kết quả hiến (BR-32, BR-33)."""
    dtype = data.get("donation_type") or "whole_blood"
    require(dtype in ("whole_blood", "component", "other"), "ERR-VALIDATION")
    out = {"donation_type": dtype, "note": (data.get("note") or "").strip() or None,
           "volume_ml": None, "component_product_id": None, "component_quantity": None, "component_unit": None}
    volume = data.get("volume_ml")
    if dtype == "whole_blood":
        try:
            out["volume_ml"] = int(volume)
        except (TypeError, ValueError):
            raise BusinessError("ERR-DON-VOLUME-REQUIRED", field_errors={"volume_ml": "Bắt buộc nhập ml."})
        require(out["volume_ml"] > 0, "ERR-DON-VOLUME-REQUIRED")
    elif volume not in (None, ""):
        try:
            out["volume_ml"] = int(volume)
        except (TypeError, ValueError):
            raise BusinessError("ERR-VALIDATION", "Thể tích phải là số nguyên.")
        require(out["volume_ml"] > 0, "ERR-DON-VOLUME-REQUIRED")
    if dtype == "component":
        try:
            qty = Decimal(str(data.get("component_quantity")).replace(",", "."))
        except (InvalidOperation, TypeError):
            qty = None
        product = Product.objects.filter(pk=as_id(data.get("component_product_id")), is_active=True).first()
        unit = data.get("component_unit")
        if product is None or qty is None or qty <= 0 or unit not in ("ml", "unit", "dose"):
            raise BusinessError("ERR-DON-COMPONENT-REQUIRED")
        out.update(component_product_id=product.pk, component_quantity=qty, component_unit=unit)
    donated_at = data.get("donated_at")
    require(donated_at is not None, "ERR-VALIDATION", "Vui lòng nhập thời điểm hiến.")
    out["donated_at"] = donated_at
    return out


def volume_warning(volume_ml):
    """Ngoài ngưỡng cảnh báo cấu hình → yêu cầu xác nhận (BR-32, ngưỡng OI-25)."""
    if volume_ml is None:
        return None
    lo, hi = SystemSetting.get("whole_blood_volume_warn_min_ml"), SystemSetting.get("whole_blood_volume_warn_max_ml")
    if volume_ml < lo or volume_ml > hi:
        return f"Thể tích {volume_ml} ml nằm ngoài khoảng thường gặp ({lo}–{hi} ml). Hãy kiểm tra lại trước khi ghi nhận."
    return None


def interval_warning(donor, now=None):
    """Cảnh báo (KHÔNG chặn) nếu lần hiến được xác nhận gần nhất chưa đủ khoảng cách tối thiểu.

    Khoảng cách tính theo hình thức của lần hiến trước (toàn phần / thành phần). Quyết định hiến hay không
    thuộc bác sĩ khám sàng lọc, nên hệ thống chỉ hiển thị thông tin.
    """
    now = now or timezone.now()
    last = (Donation.objects.filter(donor=donor, status=Donation.Status.CONFIRMED, donated_at__lte=now)
            .select_related("hospital").order_by("-donated_at").first())
    if last is None:
        return None
    key = "donation_interval_component_days" if last.donation_type == "component" else "donation_interval_whole_blood_days"
    min_days = SystemSetting.get(key)
    days = (timezone.localdate(now) - timezone.localdate(last.donated_at)).days
    if days >= min_days:
        return None
    return {"last": last.donated_at, "days": days, "min_days": min_days, "remaining": min_days - days,
            "type": last.get_donation_type_display().lower(), "hospital": last.hospital.name,
            "text": f"Lần hiến {last.get_donation_type_display().lower()} gần nhất cách đây {days} ngày "
                    f"(khuyến nghị tối thiểu {min_days} ngày, còn {min_days - days} ngày). Bác sĩ khám sàng lọc quyết định."}


def _check_time(campaign, donated_at, now, check_grace=True):
    grace = timedelta(hours=SystemSetting.get("donation_record_grace_hours"))
    if donated_at > now + timedelta(minutes=1) or donated_at < campaign.start_time or donated_at > campaign.end_time:
        raise BusinessError("ERR-DON-TIME-OUTSIDE")
    if check_grace and campaign.status == Campaign.Status.COMPLETED and now > campaign.end_time + grace:
        raise BusinessError("ERR-DON-REG-STATE", "Đã quá thời hạn ghi nhận sau khi đợt hoàn tất.")


def record_donation(staff, reg_id, data, request=None, confirm_volume=False):
    """UC-DON-01: ghi nhận = xác nhận (confirmed); đơn → donated trong cùng giao dịch (BR-31)."""
    now = timezone.now()
    clean = _clean_result(data)
    warning = volume_warning(clean["volume_ml"]) if clean["donation_type"] == "whole_blood" else None
    if warning and not confirm_volume:
        raise BusinessError("ERR-VALIDATION", warning, field_errors={"volume_ml": warning, "_needs_confirm": True})
    with business_transaction():
        reg = (
            Registration.objects.select_for_update(of=("self",)).select_related("campaign", "donor")
            .filter(pk=reg_id).first()
        )
        if reg is None or reg.campaign.hospital_id != staff.hospital_id:
            raise BusinessError("ERR-DON-HOSPITAL-MISMATCH" if reg else "ERR-NOT-FOUND")
        camp = reg.campaign
        require(reg.status == R.ATTENDED, "ERR-DON-REG-STATE")
        require(camp.status in (Campaign.Status.OPEN, Campaign.Status.CLOSED, Campaign.Status.COMPLETED),
                "ERR-DON-REG-STATE")
        if reg.donor_id == staff.user_id:
            raise BusinessError("ERR-DON-SELF-CONFIRM")
        _check_time(camp, clean["donated_at"], now)
        donation = Donation.objects.create(
            donor=reg.donor, registration=reg, hospital=camp.hospital, confirmed_by=staff.user, confirmed_at=now,
            status=Donation.Status.CONFIRMED, **clean,
        )
        reg.status = R.DONATED
        reg.donation_type = clean["donation_type"]
        reg.save(update_fields=["status", "donation_type", "updated_at"])
        audit(staff.user, donation, "create", new=snapshot(donation), hospital=staff.hospital, request=request)
        notify(reg.donor, "donation_recorded", "Lượt hiến máu của bạn đã được ghi nhận",
               f"Cảm ơn bạn đã hiến máu tại đợt \"{camp.name}\".", entity=donation)
    return donation


def _reverse_stock_in(staff, donation, reason, request=None):
    """Hủy lượt hiến đã nhập kho → ghi phiếu điều chỉnh trừ đúng số đã nhập (cùng giao dịch).

    Chỉ trừ trên phần khả dụng: nếu đơn vị đã bị xuất / giữ chỗ thì chặn hủy để nhân viên xử lý kho trước.
    """
    from bloodbank.models import Stock, StockTxn

    from .inventory import apply_txn

    total = 0
    receipts = StockTxn.objects.filter(donation=donation, txn_type=StockTxn.Type.RECEIVE).order_by("id")
    for txn in receipts:
        stock = Stock.objects.select_for_update().get(pk=txn.stock_id)
        if txn.quantity_change > stock.available:
            raise BusinessError("ERR-INV-INSUFFICIENT",
                                f"Lượt hiến đã nhập kho {txn.quantity_change} đơn vị nhưng kho chỉ còn {stock.available} "
                                "khả dụng (đã xuất hoặc đang giữ chỗ). Hãy điều chỉnh kho trước khi hủy hiệu lực.")
        apply_txn(stock, StockTxn.Type.ADJUSTMENT, -txn.quantity_change, staff.user, f"void-donation:{txn.pk}",
                  reason=StockTxn.Reason.DATA_ENTRY, note=f"Hủy hiệu lực lượt hiến {donation.code}: {reason}"[:500])
        # (phiếu nhập gốc giữ liên kết donation; phiếu trừ truy vết qua idempotency_key "void-donation:<id phiếu nhập>")
        total += txn.quantity_change
    return total


def void_donation(staff, donation_id, reason, target_status, request=None):
    """UC-DON-02: HA hủy hiệu lực; đơn → not_donated / no_show."""
    reason = (reason or "").strip()
    require(reason, "ERR-DON-REASON-REQUIRED")
    require(target_status in (R.NOT_DONATED, R.NO_SHOW), "ERR-VALIDATION", "Chọn trạng thái đơn sau khi hủy.")
    with business_transaction():
        d = Donation.objects.select_for_update().filter(pk=donation_id, hospital=staff.hospital).first()
        if d is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(d.status == Donation.Status.CONFIRMED, "ERR-DON-VOIDED-IMMUTABLE")
        old = snapshot(d)
        reversed_units = _reverse_stock_in(staff, d, reason, request)
        d.status, d.void_reason, d.voided_at, d.voided_by = Donation.Status.VOIDED, reason[:500], timezone.now(), staff.user
        d.save()
        if d.registration_id:
            reg = Registration.objects.select_for_update().get(pk=d.registration_id)
            if reg.status == R.DONATED:
                reg.status = target_status
                reg.save(update_fields=["status", "updated_at"])
        audit(staff.user, d, "void", old=old, new={**snapshot(d), "reason": reason, "stock_reversed": reversed_units},
              hospital=staff.hospital, request=request)
        notify(d.donor, "donation_voided", "Một lượt hiến của bạn đã bị hủy hiệu lực",
               "Bệnh viện đã hủy ghi nhận do sai sót. Lịch sử hiến được tính lại.", entity=d)
    return d


def edit_donation(staff, donation_id, data, reason, request=None):
    """UC-DON-03: HA sửa số liệu, bắt buộc lý do, audit old/new."""
    reason = (reason or "").strip()
    require(reason, "ERR-DON-REASON-REQUIRED")
    clean = _clean_result(data)
    now = timezone.now()
    with business_transaction():
        # registration là FK cho phép NULL (LEFT JOIN) → chỉ khóa dòng donations, PostgreSQL không khóa được phía NULL
        d = Donation.objects.select_for_update(of=("self",)).select_related("registration__campaign").filter(
            pk=donation_id, hospital=staff.hospital
        ).first()
        if d is None:
            raise BusinessError("ERR-NOT-FOUND")
        require(d.status == Donation.Status.CONFIRMED, "ERR-DON-VOIDED-IMMUTABLE")
        if d.lab_status == Donation.LabStatus.PASSED:
            # Đã nhập kho theo loại/chế phẩm hiện tại → không đổi loại nữa (kho sẽ lệch)
            require(clean["donation_type"] == d.donation_type
                    and clean["component_product_id"] == d.component_product_id, "ERR-STATE-INVALID",
                    "Lượt hiến đã nhập kho sau xét nghiệm — không đổi được hình thức hiến / chế phẩm.")
        if d.registration_id:
            _check_time(d.registration.campaign, clean["donated_at"], now, check_grace=False)
        old = snapshot(d, EDITABLE)
        for k, v in clean.items():
            setattr(d, k, v)
        d.save()
        audit(staff.user, d, "update", old=old, new={**snapshot(d, EDITABLE), "reason": reason},
              hospital=staff.hospital, request=request)
        notify(d.donor, "donation_updated", "Thông tin một lượt hiến của bạn đã được cập nhật", entity=d)
    return d


# ---------------------------------------------------------------- Lịch sử & thống kê (tính toán, không lưu)
def summarize(qs):
    confirmed = qs.filter(status="confirmed")
    agg = confirmed.aggregate(
        count=Count("id"),
        whole_count=Count("id", filter=Q(donation_type="whole_blood")),
        whole_ml=Sum("volume_ml", filter=Q(donation_type="whole_blood")),
        component_count=Count("id", filter=Q(donation_type="component")),
        other_count=Count("id", filter=Q(donation_type="other")),
        last=Max("donated_at"),
    )
    agg["whole_ml"] = agg["whole_ml"] or 0
    agg["components"] = list(
        confirmed.filter(donation_type="component")
        .values("component_product__name", "component_unit")
        .annotate(n=Count("id"), qty=Sum("component_quantity"))
        .order_by("component_product__name", "component_unit")
    )
    return agg


def donor_history(user):
    return Donation.objects.filter(donor=user).select_related("hospital", "registration__campaign", "component_product")
