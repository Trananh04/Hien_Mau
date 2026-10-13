"""Nhóm 3: danh mục chế phẩm (`products`, `product_specs`)."""
from django.db import models
from django.db.models import Q


class Product(models.Model):
    class Kind(models.TextChoices):
        WHOLE_BLOOD = "whole_blood", "Máu toàn phần"
        COMPONENT = "component", "Chế phẩm"

    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=15, choices=Kind.choices, default=Kind.COMPONENT)
    description = models.CharField(max_length=500, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["whole_blood", "component"]), name="chk_products_kind"),
        ]

    def __str__(self):
        return self.name


class ProductSpec(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.RESTRICT, related_name="specs")
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    unit_volume_ml = models.IntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "product_specs"
        ordering = ["product__name", "code"]
        constraints = [
            models.UniqueConstraint(fields=["product", "code"], name="uq_specs_product_code"),
            # Tương đương cột sinh default_product_id + UNIQUE của MySQL: đúng 1 quy cách mặc định / chế phẩm
            models.UniqueConstraint(fields=["product"], condition=Q(is_default=True), name="uq_specs_one_default"),
            models.CheckConstraint(
                condition=Q(unit_volume_ml__isnull=True) | Q(unit_volume_ml__gt=0), name="chk_spec_volume"
            ),
        ]

    def __str__(self):
        return f"{self.product.name} — {self.name}"
