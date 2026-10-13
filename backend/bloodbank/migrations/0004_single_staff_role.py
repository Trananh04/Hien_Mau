"""Gộp 3 vai trò bệnh viện (hospital_admin / donation_coordinator / inventory_manager) thành một vai trò `staff`.

Tài khoản đang có phân công bệnh viện chuyển sang users.role = 'hospital' (cổng đăng nhập Bệnh viện).
Quản trị hệ thống từng có phân công: giữ vai trò admin, thu hồi phân công (mỗi vai trò một tài khoản riêng).
"""

from django.db import migrations, models


def merge_roles(apps, schema_editor):
    Staff = apps.get_model("bloodbank", "Staff")
    User = apps.get_model("accounts", "User")
    Staff.objects.exclude(staff_role="staff").update(staff_role="staff")
    Staff.objects.filter(user__role="admin").update(is_active=False)
    User.objects.filter(role="member", pk__in=Staff.objects.values("user_id")).update(role="hospital")


class Migration(migrations.Migration):

    dependencies = [
        ('bloodbank', '0003_system_settings_defaults'),
        ('accounts', '0002_hospital_role'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='staff',
            name='chk_staffs_role',
        ),
        migrations.AlterField(
            model_name='staff',
            name='staff_role',
            field=models.CharField(choices=[('staff', 'Nhân viên bệnh viện')], default='staff', max_length=30),
        ),
        migrations.RunPython(merge_roles, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='staff',
            constraint=models.CheckConstraint(condition=models.Q(('staff_role__in', ['staff'])), name='chk_staffs_role'),
        ),
    ]
