from datetime import datetime, timedelta

from django import forms
from django.utils import timezone

from accounts.forms import BaseForm
from accounts.provinces import PROVINCES
from accounts.models import BLOOD_GROUPS
from bloodbank.models import DONATION_TYPES, PRIORITIES, Hospital, Product, ProductSpec

DT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]
PAST_SLACK = timedelta(minutes=5)   # thời gian người dùng điền form: chọn 11:31, bấm gửi lúc 11:33 vẫn hợp lệ


class FutureDateTimeInput(forms.DateTimeInput):
    """Ô chọn ngày giờ khóa các thời điểm đã qua (min = bây giờ). Giá trị cũ đã ở quá khứ (sửa đợt đang chạy)
    thì không đặt min, để trình duyệt không chặn lưu."""

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        now = timezone.localtime()
        if isinstance(value, datetime) and timezone.is_naive(value):   # giá trị ban đầu đã đổi sang giờ địa phương
            value = timezone.make_aware(value)
        if not (isinstance(value, datetime) and value < now):
            ctx["widget"]["attrs"]["min"] = now.strftime("%Y-%m-%dT%H:%M")
        return ctx


class FutureDateTimeField(forms.DateTimeField):
    pass


def dt_field(label, required=True, future=False, **kw):
    field, widget = (FutureDateTimeField, FutureDateTimeInput) if future else (forms.DateTimeField, forms.DateTimeInput)
    return field(
        label=label, required=required, input_formats=DT_FORMATS,
        widget=widget(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), **kw
    )


class FutureDatesForm(BaseForm):
    """Trường ngày giờ `future=True` không nhận thời điểm đã qua — chỉ kiểm khi người dùng đổi giá trị."""

    def clean(self):
        data = super().clean()
        limit = timezone.now() - PAST_SLACK
        for name, field in self.fields.items():
            value = data.get(name)
            if not (isinstance(field, FutureDateTimeField) and value and value < limit):
                continue
            initial = self.get_initial_for_field(field, name)
            if isinstance(initial, datetime) and abs(value - initial) < timedelta(minutes=1):
                continue      # giữ nguyên giá trị cũ (ô nhập chỉ tới phút) → không bắt sửa
            self.add_error(name, "Không chọn thời điểm đã qua.")
        return data


def spec_choices():
    return [("", "-- Chọn quy cách --")] + [
        (s.pk, f"{s.product.name} — {s.name}")
        for s in ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
    ]


class CampaignForm(FutureDatesForm):
    name = forms.CharField(label="Tên đợt hiến", max_length=255)
    description = forms.CharField(label="Mô tả", required=False, widget=forms.Textarea(attrs={"rows": 4}))
    start_time = dt_field("Bắt đầu", future=True)
    end_time = dt_field("Kết thúc", future=True)
    location_name = forms.CharField(label="Tên địa điểm", max_length=255)
    address = forms.CharField(label="Địa chỉ", max_length=500)
    province = forms.ChoiceField(label="Tỉnh/thành", required=False, choices=[("", "-- Chọn --")] + [(p, p) for p in PROVINCES])
    latitude = forms.DecimalField(label="Vĩ độ", required=False, max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = forms.DecimalField(label="Kinh độ", required=False, max_digits=9, decimal_places=6, min_value=-180, max_value=180)

    def clean(self):
        data = super().clean()
        if data.get("start_time") and data.get("end_time") and data["end_time"] <= data["start_time"]:
            self.add_error("end_time", "Thời gian kết thúc phải sau thời gian bắt đầu.")
        if (data.get("latitude") is None) != (data.get("longitude") is None):
            self.add_error("longitude", "Vĩ độ và kinh độ phải nhập cùng nhau.")
        return data


class RegistrationForm(BaseForm):
    donation_type = forms.ChoiceField(
        label="Hình thức dự kiến", required=False, widget=forms.RadioSelect,
        choices=[("", "Chưa rõ")] + [c for c in DONATION_TYPES if c[0] != "other"], initial="",
    )
    note = forms.CharField(label="Ghi chú cho bệnh viện", required=False, max_length=1000,
                           widget=forms.Textarea(attrs={"rows": 3, "placeholder": "VD: Tôi có thể đến sau 9 giờ"}))


class PatientRequestForm(FutureDatesForm):
    contact_name = forms.CharField(label="Họ tên người liên hệ", max_length=150)
    contact_phone = forms.CharField(label="Số điện thoại liên hệ", max_length=20,
                                    widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel"}))
    hospital_id = forms.ChoiceField(label="Bệnh viện đang điều trị")
    blood_group = forms.ChoiceField(label="Nhóm máu bệnh nhân", choices=BLOOD_GROUPS,
                                    error_messages={"required": "Chọn nhóm máu của bệnh nhân."})
    blood_product_id = forms.ChoiceField(label="Loại chế phẩm cần",
                                         error_messages={"required": "Chọn loại chế phẩm cần."})
    quantity_units = forms.IntegerField(label="Số đơn vị cần", min_value=1, max_value=100,
                                        widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    needed_by = dt_field("Cần trước thời điểm", required=False, future=True)
    patient_name = forms.CharField(label="Tên bệnh nhân", required=False, max_length=150)
    note = forms.CharField(label="Ghi chú", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    consent = forms.BooleanField(
        label="Tôi đồng ý chia sẻ các thông tin trên với bệnh viện điều trị để xác minh và điều phối.",
        error_messages={"required": "Bạn cần đồng ý để gửi yêu cầu."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hospital_id"].choices = [("", "-- Chọn bệnh viện --")] + [
            (h.pk, f"{h.name} ({h.area})") for h in Hospital.objects.filter(status="active")
        ]
        self.fields["blood_product_id"].choices = [("", "-- Chọn chế phẩm --")] + [
            (p.pk, p.name) for p in Product.objects.filter(is_active=True)
        ]


class DemandForm(FutureDatesForm):
    blood_group = forms.ChoiceField(label="Nhóm máu", choices=[("", "-- Chọn --")] + BLOOD_GROUPS)
    product_spec_id = forms.ChoiceField(label="Chế phẩm / quy cách")
    required_quantity = forms.IntegerField(label="Số đơn vị cần", min_value=1)
    needed_by = dt_field("Cần trước", required=False, future=True)
    note = forms.CharField(label="Ghi chú", required=False, max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_spec_id"].choices = spec_choices()


class SupportRequestForm(FutureDatesForm):
    blood_group = forms.ChoiceField(label="Nhóm máu", choices=[("", "-- Chọn --")] + BLOOD_GROUPS)
    product_spec_id = forms.ChoiceField(label="Chế phẩm / quy cách")
    quantity_needed = forms.IntegerField(label="Số đơn vị cần", min_value=1)
    priority = forms.ChoiceField(label="Mức ưu tiên", choices=PRIORITIES, initial="normal")
    needed_by = dt_field("Cần trước", required=False, future=True)
    note = forms.CharField(label="Ghi chú", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_spec_id"].choices = spec_choices()


class HospitalForm(BaseForm):
    code = forms.CharField(label="Mã cơ sở", max_length=30)
    name = forms.CharField(label="Tên bệnh viện", max_length=255)
    address = forms.CharField(label="Địa chỉ", max_length=500)
    province = forms.ChoiceField(label="Tỉnh/thành", choices=[(p, p) for p in PROVINCES])
    district = forms.CharField(label="Quận/huyện", max_length=100, required=False)
    ward = forms.CharField(label="Phường/xã", max_length=100, required=False)
    latitude = forms.DecimalField(label="Vĩ độ", required=False, max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = forms.DecimalField(label="Kinh độ", required=False, max_digits=9, decimal_places=6, min_value=-180, max_value=180)
    phone = forms.CharField(label="Điện thoại", max_length=20, required=False)
    email = forms.EmailField(label="Email", max_length=255, required=False)

    def clean(self):
        data = super().clean()
        if (data.get("latitude") is None) != (data.get("longitude") is None):
            self.add_error("longitude", "Vĩ độ và kinh độ phải nhập cùng nhau.")
        return data


class HospitalSignupForm(HospitalForm):
    """BV_014: bệnh viện tự đăng ký + tài khoản Quản lý bệnh viện (chờ Quản trị hệ thống duyệt)."""
    manager_name = forms.CharField(label="Họ tên người quản lý", max_length=150)
    manager_email = forms.EmailField(label="Email đăng nhập", max_length=255)
    manager_phone = forms.CharField(label="Số điện thoại người quản lý", max_length=20, required=False)
    password = forms.CharField(label="Mật khẩu", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Nhập lại mật khẩu", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(
        label="Tôi xác nhận thông tin bệnh viện là chính xác và tôi được bệnh viện giao quản lý tài khoản này.",
        error_messages={"required": "Bạn cần xác nhận để gửi đăng ký."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].label = "Mã cơ sở khám chữa bệnh"
        self.fields["province"].choices = [("", "-- Chọn --")] + list(self.fields["province"].choices)

    def clean_manager_email(self):
        from accounts.models import User

        email = self.cleaned_data["manager_email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Email này đã có tài khoản. Dùng email khác cho tài khoản bệnh viện.")
        return email

    def clean_code(self):
        code = self.cleaned_data["code"].strip().upper()
        if Hospital.objects.filter(code=code).exists():
            raise forms.ValidationError("Mã cơ sở này đã được đăng ký.")
        return code

    def clean(self):
        from accounts.forms import check_password_strength
        from accounts.models import User

        data = super().clean()
        p1, p2 = data.get("password"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Mật khẩu nhập lại không khớp.")
        if p1:
            try:
                check_password_strength(p1, User(email=data.get("manager_email") or "",
                                                 full_name=data.get("manager_name") or ""))
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return data


class ProductForm(BaseForm):
    code = forms.CharField(label="Mã chế phẩm", max_length=30)
    name = forms.CharField(label="Tên chế phẩm", max_length=150)
    kind = forms.ChoiceField(label="Loại", choices=Product.Kind.choices)
    description = forms.CharField(label="Mô tả", max_length=500, required=False)


class SpecForm(BaseForm):
    code = forms.CharField(label="Mã quy cách", max_length=30,
                           widget=forms.TextInput(attrs={"placeholder": "VD: 250ML"}))
    name = forms.CharField(label="Tên quy cách", max_length=150)
    unit_volume_ml = forms.IntegerField(label="Thể tích/đơn vị (ml)", required=False, min_value=1)
    is_default = forms.BooleanField(label="Quy cách mặc định", required=False)



class EmergencyForm(FutureDatesForm):
    """Báo ca khẩn cấp: chỉ những gì cần để bắt đầu tìm máu ngay."""
    blood_group = forms.ChoiceField(label="Nhóm máu", choices=[("", "-- Chọn --")] + list(BLOOD_GROUPS))
    product_spec_id = forms.ChoiceField(label="Chế phẩm / quy cách", choices=())
    quantity = forms.IntegerField(label="Số đơn vị cần", min_value=1, max_value=100)
    needed_by = dt_field("Cần trước", required=False, future=True)
    note = forms.CharField(label="Ghi chú", required=False, max_length=500,
                           widget=forms.TextInput(attrs={"placeholder": "VD: mổ cấp cứu, khoa Hồi sức"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_spec_id"].choices = [("", "-- Chọn --")] + [
            (s.pk, f"{s.product.name} — {s.name}") for s in ProductSpec.objects.select_related("product")
            .filter(is_active=True, product__is_active=True).order_by("product__name", "-is_default", "name")]
