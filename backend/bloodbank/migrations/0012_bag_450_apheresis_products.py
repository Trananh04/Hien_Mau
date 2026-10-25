"""Túi 450 ml (máu toàn phần, khối hồng cầu) và 2 chế phẩm gạn tách: hồng cầu đôi, bạch cầu hạt.

Hiến thành phần gồm 4 loại: tiểu cầu, huyết tương, hồng cầu đôi, bạch cầu hạt.
"""
from django.db import migrations

SPECS_450 = [("WB", "450ML", "Túi 450 ml"), ("RBC", "450ML", "Từ 450 ml máu")]
NEW_PRODUCTS = [
    ("RBC2", "Hồng cầu đôi", "Đơn vị gạn tách"),
    ("GRAN", "Bạch cầu hạt", "Đơn vị gạn tách"),
]


def forward(apps, schema_editor):
    Product = apps.get_model("bloodbank", "Product")
    ProductSpec = apps.get_model("bloodbank", "ProductSpec")
    for product_code, code, name in SPECS_450:
        product = Product.objects.filter(code=product_code).first()
        if product:
            ProductSpec.objects.get_or_create(product=product, code=code,
                                              defaults={"name": name, "unit_volume_ml": 450, "is_default": False})
    for code, name, spec_name in NEW_PRODUCTS:
        product, _ = Product.objects.get_or_create(code=code, defaults={"name": name, "kind": "component"})
        ProductSpec.objects.get_or_create(product=product, code="STANDARD",
                                          defaults={"name": spec_name, "unit_volume_ml": None, "is_default": True})


class Migration(migrations.Migration):
    dependencies = [("bloodbank", "0011_donation_multi_products")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
