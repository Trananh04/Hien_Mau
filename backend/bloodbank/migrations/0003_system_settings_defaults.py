"""Giá trị khởi tạo `system_settings` (đề xuất, chờ stakeholder chốt) và danh mục chế phẩm cơ bản."""
from django.db import migrations

PRODUCTS = [
    # code, name, kind, [(spec_code, spec_name, ml, default)]
    ("WB", "Máu toàn phần", "whole_blood", [("250ML", "Túi 250 ml", 250, True), ("350ML", "Túi 350 ml", 350, False)]),
    ("RBC", "Khối hồng cầu", "component", [("250ML", "Từ 250 ml máu", 250, True), ("350ML", "Từ 350 ml máu", 350, False)]),
    ("FFP", "Huyết tương tươi đông lạnh", "component", [("STANDARD", "Túi tiêu chuẩn", None, True)]),
    ("PLT", "Khối tiểu cầu", "component", [("STANDARD", "Đơn vị tiêu chuẩn", None, True)]),
    ("CRYO", "Tủa lạnh", "component", [("STANDARD", "Đơn vị tiêu chuẩn", None, True)]),
]


def forward(apps, schema_editor):
    SystemSetting = apps.get_model("bloodbank", "SystemSetting")
    from bloodbank.models.system import SystemSetting as Real

    for key, (value, description) in Real.DEFAULTS.items():
        SystemSetting.objects.get_or_create(
            setting_key=key, defaults={"setting_value": value, "description": description}
        )

    Product = apps.get_model("bloodbank", "Product")
    ProductSpec = apps.get_model("bloodbank", "ProductSpec")
    for code, name, kind, specs in PRODUCTS:
        product, _ = Product.objects.get_or_create(code=code, defaults={"name": name, "kind": kind})
        for spec_code, spec_name, ml, default in specs:
            ProductSpec.objects.get_or_create(
                product=product,
                code=spec_code,
                defaults={"name": spec_name, "unit_volume_ml": ml, "is_default": default},
            )


class Migration(migrations.Migration):
    dependencies = [("bloodbank", "0002_triggers")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
