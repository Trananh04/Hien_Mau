from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("bloodbank.urls")),
]

handler403 = "bloodbank.views.errors.permission_denied"
handler404 = "bloodbank.views.errors.page_not_found"
handler500 = "bloodbank.views.errors.server_error"
