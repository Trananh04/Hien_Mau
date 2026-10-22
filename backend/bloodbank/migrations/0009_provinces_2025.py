"""Chuẩn hóa tỉnh/thành theo 34 đơn vị hành chính hiện hành (Nghị quyết 202/2025/QH15).

Người dùng / đợt hiến: tên cũ → tên mới; giá trị không nhận ra (vd "Khác") → để trống để người dùng chọn lại.
Bệnh viện (bắt buộc có tỉnh): tên cũ → tên mới; không nhận ra thì giữ nguyên để quản trị sửa tay.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    from accounts.provinces import normalize_province

    for app, model, required in (("accounts", "User", False), ("bloodbank", "Hospital", True),
                                 ("bloodbank", "Campaign", False)):
        Model = apps.get_model(app, model)
        for value in Model.objects.exclude(province__isnull=True).exclude(province="").values_list(
                "province", flat=True).distinct():
            new = normalize_province(value)
            if new and new != value:
                Model.objects.filter(province=value).update(province=new)
            elif not new and not required:
                Model.objects.filter(province=value).update(province=None)


class Migration(migrations.Migration):
    dependencies = [
        ("bloodbank", "0008_staff_single_hospital_donation_registration"),
        ("accounts", "0002_hospital_role"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
