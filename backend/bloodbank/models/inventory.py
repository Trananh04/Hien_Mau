"""Nhóm 5: tồn kho (`stocks`, `stock_lots`, `stock_txns`, `demands`)."""
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES, BLOOD_GROUPS

from .catalog import ProductSpec
from .hospitals import Hospital


class Stock(models.Model):
    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="stocks")
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS)
    product_spec = models.ForeignKey(ProductSpec, on_delete=models.RESTRICT, related_name="stocks")
    quantity_on_hand = models.IntegerField(default=0)
    quantity_reserved = models.IntegerField(default=0)
    min_stock_level = models.IntegerField(default=0)
    shareable_quantity = models.IntegerField(null=True, blank=True)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stocks"
        indexes = [
            models.Index(fields=["blood_group", "product_spec", "shareable_quantity"], name="idx_stocks_search"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["hospital", "blood_group", "product_spec"], name="uq_stocks_key"),
            models.CheckConstraint(condition=Q(min_stock_level__gte=0), name="chk_stock_min"),
            models.CheckConstraint(condition=Q(quantity_on_hand__gte=0), name="chk_stock_on_hand"),
            models.CheckConstraint(
                condition=Q(quantity_reserved__gte=0, quantity_reserved__lte=F("quantity_on_hand")),
                name="chk_stock_reserved",
            ),
            models.CheckConstraint(
                condition=Q(shareable_quantity__isnull=True) | Q(shareable_quantity__gte=0), name="chk_stock_shareable"
            ),
            models.CheckConstraint(condition=Q(blood_group__in=BLOOD_GROUP_VALUES), name="chk_stocks_blood_group"),
        ]

    @property
    def available(self):
        return self.quantity_on_hand - self.quantity_reserved

    @property
    def effective_shareable(self):
        """BR-42: MIN(COALESCE(shareable, 0), khả dụng)."""
        return max(0, min(self.shareable_quantity or 0, self.available))

    @property
    def below_min(self):
        return self.min_stock_level > 0 and self.available < self.min_stock_level


class StockLot(models.Model):
    stock = models.ForeignKey(Stock, on_delete=models.RESTRICT, related_name="lots")
    lot_code = models.CharField(max_length=50)
    expires_at = models.DateTimeField(null=True, blank=True)
    quantity_on_hand = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stock_lots"
        indexes = [models.Index(fields=["stock", "expires_at"], name="idx_stock_lots_expiry")]
        constraints = [
            models.UniqueConstraint(fields=["stock", "lot_code"], name="uq_stock_lots_code"),
            models.CheckConstraint(condition=Q(quantity_on_hand__gte=0), name="chk_stock_lots_qty"),
        ]


class StockTxn(models.Model):
    class Type(models.TextChoices):
        RECEIVE = "receive", "Nhập kho"
        ISSUE = "issue", "Xuất kho"
        TRANSFER_OUT = "transfer_out", "Xuất điều chuyển"
        TRANSFER_IN = "transfer_in", "Nhận điều chuyển"
        TRANSFER_RETURN = "transfer_return", "Hàng điều chuyển quay về"
        ADJUSTMENT = "adjustment", "Điều chỉnh"

    class Reason(models.TextChoices):
        EXPIRED = "expired", "Hết hạn"
        QUALITY_FAILED = "quality_failed", "Không đạt chất lượng"
        DAMAGED = "damaged", "Hư hỏng"
        STOCKTAKE = "stocktake_correction", "Kiểm kê"
        DATA_ENTRY = "data_entry_error", "Nhập sai dữ liệu"
        TRANSFER_SHORTFALL = "transfer_shortfall", "Hao hụt điều chuyển"
        OTHER = "other", "Khác"

    stock = models.ForeignKey(Stock, on_delete=models.RESTRICT, related_name="txns")
    lot = models.ForeignKey(StockLot, on_delete=models.RESTRICT, null=True, blank=True, related_name="txns")
    txn_type = models.CharField(max_length=20, choices=Type.choices)
    quantity_change = models.IntegerField()
    quantity_before = models.IntegerField()
    quantity_after = models.IntegerField()
    adjustment_reason = models.CharField(max_length=25, choices=Reason.choices, null=True, blank=True)
    reason_note = models.CharField(max_length=500, null=True, blank=True)
    offer = models.ForeignKey(
        "bloodbank.RequestOffer", on_delete=models.RESTRICT, null=True, blank=True, related_name="txns"
    )
    patient_request = models.ForeignKey(
        "bloodbank.PatientRequest", on_delete=models.RESTRICT, null=True, blank=True, related_name="txns"
    )
    # Truy xuất nguồn gốc: phiếu nhập tạo từ lượt hiến đã xét nghiệm đạt
    donation = models.ForeignKey(
        "bloodbank.Donation", on_delete=models.RESTRICT, null=True, blank=True, related_name="stock_txns"
    )
    idempotency_key = models.CharField(max_length=100, unique=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, db_column="performed_by", related_name="stock_txns")
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_txns"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["performed_by", "occurred_at"], name="idx_txn_performed_by"),
            models.Index(fields=["stock", "occurred_at", "id"], name="idx_txn_stock_time"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["offer", "txn_type"], name="uq_txn_offer_type"),
            # Mỗi lượt hiến nhập kho tối đa một lần
            models.UniqueConstraint(fields=["donation"], condition=Q(donation__isnull=False), name="uq_txn_donation"),
            models.CheckConstraint(condition=Q(donation__isnull=True) | Q(txn_type="receive"), name="chk_txn_donation_receive"),
            models.CheckConstraint(
                condition=Q(txn_type="adjustment", adjustment_reason__isnull=False)
                | (~Q(txn_type="adjustment") & Q(adjustment_reason__isnull=True)),
                name="chk_txn_adjustment_reason",
            ),
            models.CheckConstraint(condition=Q(quantity_after__gte=0), name="chk_txn_after_non_negative"),
            models.CheckConstraint(
                condition=Q(quantity_after=F("quantity_before") + F("quantity_change")), name="chk_txn_balance"
            ),
            models.CheckConstraint(condition=Q(quantity_before__gte=0), name="chk_txn_before_non_negative"),
            models.CheckConstraint(condition=~Q(quantity_change=0), name="chk_txn_change_nonzero"),
            models.CheckConstraint(
                condition=Q(txn_type__in=["transfer_in", "transfer_out", "transfer_return"], offer__isnull=False)
                | (~Q(txn_type__in=["transfer_in", "transfer_out", "transfer_return"]) & Q(offer__isnull=True))
                | Q(txn_type="adjustment", adjustment_reason="transfer_shortfall", offer__isnull=False),
                name="chk_txn_offer_link",
            ),
            models.CheckConstraint(
                condition=Q(adjustment_reason__isnull=True) | ~Q(adjustment_reason="other") | Q(reason_note__isnull=False),
                name="chk_txn_other_note",
            ),
            models.CheckConstraint(
                condition=Q(patient_request__isnull=True) | Q(txn_type="issue"), name="chk_txn_patient_link"
            ),
            models.CheckConstraint(
                condition=~Q(txn_type__in=["receive", "transfer_in", "transfer_return"]) | Q(quantity_change__gt=0),
                name="chk_txn_sign_in",
            ),
            models.CheckConstraint(
                condition=~Q(txn_type__in=["issue", "transfer_out"]) | Q(quantity_change__lt=0), name="chk_txn_sign_out"
            ),
            models.CheckConstraint(
                condition=Q(
                    txn_type__in=["receive", "issue", "transfer_out", "transfer_in", "transfer_return", "adjustment"]
                ),
                name="chk_txn_type",
            ),
        ]


class Demand(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Đang cần"
        FULFILLED = "fulfilled", "Đã đáp ứng"
        CANCELLED = "cancelled", "Đã hủy"

    hospital = models.ForeignKey(Hospital, on_delete=models.RESTRICT, related_name="demands")
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUPS)
    product_spec = models.ForeignKey(ProductSpec, on_delete=models.RESTRICT, related_name="demands")
    required_quantity = models.IntegerField()
    needed_by = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    note = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "demands"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["hospital", "status", "blood_group", "product_spec"], name="idx_demands_hospital_key"
            ),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(required_quantity__gt=0), name="chk_demand_qty"),
            models.CheckConstraint(condition=Q(status__in=["active", "fulfilled", "cancelled"]), name="chk_demands_status"),
            models.CheckConstraint(condition=Q(blood_group__in=BLOOD_GROUP_VALUES), name="chk_demands_blood_group"),
        ]
