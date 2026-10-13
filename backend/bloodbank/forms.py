from django import forms

from accounts.forms import PROVINCES, BaseForm
from accounts.models import BLOOD_GROUPS
from bloodbank.models import DONATION_TYPES, PRIORITIES, Hospital, Product, ProductSpec

DT_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"]
NOTE_HINT = "Không nhập kết quả khám/xét nghiệm hoặc bệnh án."


def dt_field(label, required=True, **kw):
    return forms.DateTimeField(
        label=label, required=required, input_formats=DT_FORMATS,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), **kw
    )


def spec_choices():
    return [("", "-- Chọn quy cách --")] + [
        (s.pk, f"{s.product.name} — {s.name}")
        for s in ProductSpec.objects.select_related("product").filter(is_active=True, product__is_active=True)
    ]


class CampaignForm(BaseForm):
    name = forms.CharField(label="Tên đợt hiến", max_length=255)
    description = forms.CharField(label="Mô tả", required=False, widget=forms.Textarea(attrs={"rows": 4}))
    start_time = dt_field("Bắt đầu")
    end_time = dt_field("Kết thúc")
    location_name = forms.CharField(label="Tên địa điểm", max_length=255)
    address = forms.CharField(label="Địa chỉ", max_length=500)
    province = forms.ChoiceField(label="Tỉnh/thành", required=False, choices=[("", "-- Chọn --")] + [(p, p) for p in PROVINCES])
    latitude = forms.DecimalField(label="Vĩ độ", required=False, max_digits=9, decimal_places=6, min_value=-90, max_value=90)
    longitude = forms.DecimalField(label="Kinh độ", required=False, max_digits=9, decimal_places=6, min_value=-180, max_value=180)

    def clean(self):
        data = super().clean()
        if data.get("start_time") and data.get("end_time") and data["end_time"] <= data["start_time"]:
            self.add_error("end_time", "Thời gian kết thúc phải sau thời gian bắt đầu (ERR-CMP-TIME-RANGE).")
        if (data.get("latitude") is None) != (data.get("longitude") is None):
            self.add_error("longitude", "Vĩ độ và kinh độ phải nhập cùng nhau.")
        return data


class RegistrationForm(BaseForm):
    donation_type = forms.ChoiceField(
        label="Hình thức dự kiến", required=False, widget=forms.RadioSelect,
        choices=[("", "Chưa rõ")] + [c for c in DONATION_TYPES if c[0] != "other"], initial="",
    )
    note = forms.CharField(label="Ghi chú cho bệnh viện", required=False, max_length=1000,
                           widget=forms.Textarea(attrs={"rows": 3, "placeholder": "VD: Tôi có thể đến sau 9 giờ"}),
                           help_text=NOTE_HINT)


class PatientRequestForm(BaseForm):
    contact_name = forms.CharField(label="Họ tên người liên hệ", max_length=150)
    contact_phone = forms.CharField(label="Số điện thoại liên hệ", max_length=20,
                                    widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "autocomplete": "tel"}))
    hospital_id = forms.ChoiceField(label="Bệnh viện đang điều trị")
    blood_group = forms.ChoiceField(label="Nhóm máu bệnh nhân", required=False,
                                    choices=[("", "Chưa rõ — bệnh viện sẽ xác minh")] + BLOOD_GROUPS)
    blood_product_id = forms.ChoiceField(label="Loại chế phẩm cần (nếu biết)", required=False)
    quantity_units = forms.IntegerField(label="Số đơn vị cần", min_value=1, max_value=100,
                                        widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    needed_by = dt_field("Cần trước thời điểm", required=False)
    patient_name = forms.CharField(label="Tên bệnh nhân", required=False, max_length=150,
                                   help_text="Chỉ bệnh viện điều trị được xem.")
    note = forms.CharField(label="Ghi chú", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 3}),
                           help_text=NOTE_HINT)
    consent = forms.BooleanField(
        label="Tôi đồng ý chia sẻ các thông tin trên với bệnh viện điều trị để xác minh và điều phối.",
        error_messages={"required": "Bạn cần đồng ý để gửi yêu cầu."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hospital_id"].choices = [("", "-- Chọn bệnh viện --")] + [
            (h.pk, f"{h.name} ({h.area})") for h in Hospital.objects.filter(status="active")
        ]
        self.fields["blood_product_id"].choices = [("", "Chưa rõ")] + [
            (p.pk, p.name) for p in Product.objects.filter(is_active=True)
        ]


class DemandForm(BaseForm):
    blood_group = forms.ChoiceField(label="Nhóm máu", choices=[("", "-- Chọn --")] + BLOOD_GROUPS)
    product_spec_id = forms.ChoiceField(label="Chế phẩm / quy cách")
    required_quantity = forms.IntegerField(label="Số đơn vị cần", min_value=1)
    needed_by = dt_field("Cần trước", required=False)
    note = forms.CharField(label="Ghi chú", required=False, max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_spec_id"].choices = spec_choices()


class SupportRequestForm(BaseForm):
    blood_group = forms.ChoiceField(label="Nhóm máu", choices=[("", "-- Chọn --")] + BLOOD_GROUPS)
    product_spec_id = forms.ChoiceField(label="Chế phẩm / quy cách")
    quantity_needed = forms.IntegerField(label="Số đơn vị cần", min_value=1)
    priority = forms.ChoiceField(label="Mức ưu tiên", choices=PRIORITIES, initial="normal")
    needed_by = dt_field("Cần trước", required=False)
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


class ProductForm(BaseForm):
    code = forms.CharField(label="Mã chế phẩm", max_length=30)
    name = forms.CharField(label="Tên chế phẩm", max_length=150)
    kind = forms.ChoiceField(label="Loại", choices=Product.Kind.choices)
    description = forms.CharField(label="Mô tả", max_length=500, required=False)


class SpecForm(BaseForm):
    code = forms.CharField(label="Mã quy cách", max_length=30, help_text="VD: 250ML, 350ML, STANDARD")
    name = forms.CharField(label="Tên quy cách", max_length=150)
    unit_volume_ml = forms.IntegerField(label="Thể tích/đơn vị (ml)", required=False, min_value=1)
    is_default = forms.BooleanField(label="Quy cách mặc định", required=False)
