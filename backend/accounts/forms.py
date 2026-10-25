from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import BLOOD_GROUPS, User, normalize_phone

from .provinces import PROVINCES  # noqa: F401 — giữ đường import cũ cho các module khác


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
        raise ValidationError(["Mật khẩu chưa đủ mạnh."] + list(exc.messages))


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
        fields = ["full_name", "phone", "date_of_birth", "gender", "blood_group", "address", "province"]
        labels = {
            "full_name": "Họ và tên", "phone": "Số điện thoại", "date_of_birth": "Ngày sinh", "gender": "Giới tính",
            "blood_group": "Nhóm máu (tự khai)", "address": "Địa chỉ", "province": "Tỉnh/thành",
        }
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gender"].choices = [("", "-- Chọn --")] + list(User.Gender.choices)
        self.fields["blood_group"].choices = [("", "Chưa rõ")] + BLOOD_GROUPS
        self.fields["province"] = forms.ChoiceField(
            label="Tỉnh/thành", required=False, choices=[("", "-- Chọn --")] + [(p, p) for p in PROVINCES]
        )
        for field in self.fields.values():
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
