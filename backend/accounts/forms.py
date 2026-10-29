from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.urls import reverse

from .models import BLOOD_GROUPS, User, normalize_phone

from .provinces import PROVINCES, wards_of  # PROVINCES: giữ đường import cũ cho các module khác

WARD_PLACEHOLDER = "-- Chọn phường / xã --"


def ward_options(province):
    """Lựa chọn của ô Phường/Xã theo tỉnh; chưa chọn tỉnh → chỉ có dòng nhắc."""
    if not wards_of(province):
        return [("", "-- Chọn tỉnh trước --")]
    return [("", WARD_PLACEHOLDER)] + [(w, w) for w in wards_of(province)]


def add_ward_field(form, initial_province, keep=None):
    """Ô Phường/Xã phụ thuộc ô Tỉnh/thành: đổi tỉnh → HTMX tải lại danh sách (accounts:wards), không cần JS riêng.

    Lựa chọn hợp lệ = xã của tỉnh đang gửi lên, nên xã không thuộc tỉnh đã chọn bị từ chối ngay ở bước kiểm tra.
    Ô tỉnh bị khóa (không gửi lên) → dùng tỉnh ban đầu. `keep`: giá trị đang lưu không có trong danh sách (tên trước
    sắp xếp 01/7/2025) vẫn được giữ, để lưu form không âm thầm xóa mất."""
    province = (form.data.get("province") or initial_province) if form.is_bound else initial_province
    choices = ward_options(province)
    if keep and province == initial_province and keep not in wards_of(province):
        choices.insert(1, (keep, f"{keep} (tên cũ)"))
    form.fields["ward"] = forms.ChoiceField(
        label="Phường/Xã", required=False, choices=choices,
        error_messages={"invalid_choice": "Phường/Xã không thuộc tỉnh/thành đã chọn."},
    )
    form.fields["province"].widget.attrs.update({
        "hx-get": reverse("accounts:wards"), "hx-target": "#id_ward", "hx-swap": "innerHTML",
        "hx-trigger": "change", "hx-include": "this", "hx-sync": "this:replace",
    })


class BaseForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            css = "field-select" if isinstance(widget, forms.Select) else (
                "field-textarea" if isinstance(widget, forms.Textarea) else "field-input"
            )
            widget.attrs.setdefault("class", css)


def check_password_strength(password, user=None):
    try:
        password_validation.validate_password(password, user)
    except ValidationError as exc:
        raise ValidationError(list(exc.messages))


class RegisterForm(BaseForm):
    full_name = forms.CharField(label="Họ và tên", max_length=150)
    email = forms.EmailField(label="Email", max_length=255)
    phone = forms.CharField(label="Số điện thoại", max_length=20, required=False)
    blood_group = forms.ChoiceField(label="Nhóm máu (tự khai, nếu biết)", required=False,
                                    choices=[("", "Chưa rõ")] + BLOOD_GROUPS)
    province = forms.ChoiceField(label="Tỉnh/thành", required=False, choices=[("", "-- Chọn --")] + [(p, p) for p in PROVINCES])
    password = forms.CharField(label="Mật khẩu", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Nhập lại mật khẩu", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    accept_terms = forms.BooleanField(
        label="Tôi đồng ý với điều khoản sử dụng và việc xử lý dữ liệu cá nhân theo Chính sách bảo mật.",
        error_messages={"required": "Bạn cần đồng ý điều khoản để tạo tài khoản."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_ward_field(self, None)
        self.fields["ward"].widget.attrs["class"] = "field-select"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email này đã được đăng ký. Bạn có thể đăng nhập hoặc dùng email khác.")
        return email

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if phone and not phone[1:].isdigit():
            raise ValidationError("Số điện thoại không hợp lệ.")
        if phone and len(phone) < 11:
            raise ValidationError("Số điện thoại không hợp lệ.")
        if phone and User.objects.filter(phone=phone).exists():
            raise ValidationError("Số điện thoại này đã được đăng ký.")
        return phone

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Mật khẩu nhập lại không khớp.")
        if p1:
            try:
                check_password_strength(p1, User(email=data.get("email") or "", full_name=data.get("full_name") or ""))
            except ValidationError as exc:
                self.add_error("password", exc)
        return data


class LoginForm(BaseForm):
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))
    password = forms.CharField(label="Mật khẩu", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class ForgotPasswordForm(BaseForm):
    email = forms.EmailField(label="Email đã đăng ký")


class ResetPasswordForm(BaseForm):
    password = forms.CharField(label="Mật khẩu mới", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Nhập lại mật khẩu mới", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password") != data.get("password2"):
            self.add_error("password2", "Mật khẩu nhập lại không khớp.")
        if data.get("password"):
            try:
                check_password_strength(data["password"], self.user)
            except ValidationError as exc:
                self.add_error("password", exc)
        return data


class ChangePasswordForm(ResetPasswordForm):
    old_password = forms.CharField(label="Mật khẩu hiện tại", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    field_order = ["old_password", "password", "password2"]

    def clean_old_password(self):
        value = self.cleaned_data["old_password"]
        if not self.user.check_password(value):
            raise ValidationError("Mật khẩu hiện tại không đúng.")
        return value


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "phone", "date_of_birth", "gender", "blood_group", "address", "province", "ward",
                  "email_reminders"]
        labels = {
            "full_name": "Họ và tên", "phone": "Số điện thoại", "date_of_birth": "Ngày sinh", "gender": "Giới tính",
            "blood_group": "Nhóm máu (tự khai)", "address": "Địa chỉ (số nhà, đường, thôn/xóm)", "province": "Tỉnh/thành",
            "email_reminders": "Nhận email khi bệnh viện kêu gọi hiến máu và khi tôi đủ thời gian để hiến lại",
        }
        help_texts = {"email_reminders": "Email về đơn đăng ký, đợt hiến bạn đã đăng ký và bảo mật tài khoản vẫn luôn được gửi."}
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gender"].choices = [("", "-- Chọn --")] + list(User.Gender.choices)
        self.fields["blood_group"].choices = [("", "Chưa rõ")] + BLOOD_GROUPS
        self.fields["province"] = forms.ChoiceField(
            label="Tỉnh/thành", required=False, choices=[("", "-- Chọn --")] + [(p, p) for p in PROVINCES]
        )
        add_ward_field(self, self.instance.province, keep=self.instance.ward)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            css = "field-select" if isinstance(field.widget, forms.Select) else "field-input"
            field.widget.attrs.setdefault("class", css)

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if phone and User.objects.filter(phone=phone).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Số điện thoại này đã được đăng ký.")
        return phone


class WorkProfileForm(forms.ModelForm):
    """Hồ sơ tài khoản công tác (Nhân viên bệnh viện / Quản trị): chỉ họ tên và số điện thoại."""

    class Meta:
        model = User
        fields = ["full_name", "phone"]
        labels = {"full_name": "Họ và tên", "phone": "Số điện thoại"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "field-input")

    clean_phone = ProfileForm.clean_phone
