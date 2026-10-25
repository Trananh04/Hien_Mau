from django.conf import settings
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("dang-nhap/", views.login_view, name="login"),
    path("benh-vien/dang-nhap/", views.hospital_login_view, name="hospital_login"),
    path("benh-vien/dang-ky/", views.hospital_register_view, name="hospital_register"),
    path(settings.ADMIN_LOGIN_PATH, views.admin_login_view, name="admin_login"),
    path("dang-ky/", views.register_view, name="register"),
    path("dang-xuat/", views.logout_view, name="logout"),
    path("quen-mat-khau/", views.forgot_password_view, name="forgot_password"),
    path("dat-lai-mat-khau/<str:token>/", views.reset_password_view, name="reset_password"),
    path("xac-thuc-email/<str:token>/", views.verify_email_view, name="verify_email"),
    path("xac-thuc-email-gui-lai/", views.resend_verification_view, name="resend_verification"),
]
