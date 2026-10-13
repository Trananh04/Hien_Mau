from django.urls import path

from .views import admin, hospital, hospital_campaigns as hc, hospital_inventory as hi, hospital_transfers as ht
from .views import member, public

app_name = "bloodbank"

urlpatterns = [
    # Công khai (SCR-01..05)
    path("", public.home, name="home"),
    path("dot-hien/", public.campaign_list, name="campaigns"),
    path("dot-hien/<int:pk>/", public.campaign_detail, name="campaign_detail"),
    path("ban-do/", public.map_view, name="map"),
    path("ban-do/du-lieu/", public.map_data, name="map_data"),
    path("api/chatbot/", public.chatbot, name="chatbot"),

    # Cá nhân (SCR-07..13)
    path("tai-khoan/", member.profile, name="profile"),
    path("tai-khoan/don-dang-ky/", member.my_registrations, name="my_registrations"),
    path("tai-khoan/don-dang-ky/<int:pk>/huy/", member.cancel_registration, name="cancel_registration"),
    path("tai-khoan/don-dang-ky/<int:pk>/dang-ky-lai/", member.reregister, name="reregister"),
    path("tai-khoan/lich-su-hien/", member.my_history, name="my_history"),
    path("tai-khoan/lich-su-hien/<int:pk>/", member.my_donation_detail, name="my_donation_detail"),
    path("can-mau/gui-yeu-cau/", member.patient_request_new, name="patient_request_new"),
    path("tai-khoan/yeu-cau-can-mau/", member.my_patient_requests, name="my_patient_requests"),
    path("tai-khoan/yeu-cau-can-mau/<int:pk>/", member.my_patient_request_detail, name="my_patient_request_detail"),
    path("tai-khoan/yeu-cau-can-mau/<int:pk>/huy/", member.cancel_patient_request, name="cancel_patient_request"),
    path("thong-bao/", member.notifications, name="notifications"),
    path("thong-bao/da-doc/", member.notifications_read, name="notifications_read"),
    path("tai-khoan-cong-tac/", member.work_account, name="work_account"),

    # Bệnh viện (SCR-20..40)
    path("benh-vien/", hospital.dashboard, name="hospital_dashboard"),
    path("benh-vien/chon/", hospital.choose_hospital, name="select_hospital"),
    path("benh-vien/dot-hien/", hc.campaigns, name="hospital_campaigns"),
    path("benh-vien/dot-hien/tao/", hc.campaign_form, name="hospital_campaign_create"),
    path("benh-vien/dot-hien/<int:pk>/", hc.campaign_detail, name="hospital_campaign_detail"),
    path("benh-vien/dot-hien/<int:pk>/sua/", hc.campaign_form, name="hospital_campaign_edit"),
    path("benh-vien/dot-hien/<int:pk>/trang-thai/", hc.campaign_action, name="hospital_campaign_action"),
    path("benh-vien/dot-hien/<int:pk>/diem-hien/", hc.checkin, name="checkin"),
    path("benh-vien/dot-hien/<int:pk>/tai-cho/", hc.walk_in, name="walk_in"),
    path("benh-vien/don/<int:pk>/xu-ly/", hc.registration_action, name="registration_action"),
    path("benh-vien/don/<int:pk>/diem-hien/", hc.checkin_action, name="checkin_action"),
    path("benh-vien/don/<int:pk>/ghi-nhan/", hc.record_donation, name="record_donation"),
    path("benh-vien/luot-hien/<int:pk>/", hc.donation_detail, name="hospital_donation_detail"),
    path("benh-vien/luot-hien/<int:pk>/quan-ly/", hc.donation_manage, name="donation_manage"),
    path("benh-vien/nguoi-hien/", hc.donor_lookup, name="donor_lookup"),
    path("benh-vien/bao-cao-tiep-nhan/", hc.donation_report, name="donation_report"),

    path("benh-vien/kho/", hi.stock, name="stock"),
    path("benh-vien/kho/<int:pk>/cau-hinh/", hi.stock_settings, name="stock_settings"),
    path("benh-vien/kho/muc-ton/", hi.stock_threshold, name="stock_threshold"),
    path("benh-vien/kho/phieu/<slug:kind>/", hi.stock_txn_form, name="stock_txn"),
    path("benh-vien/kho/lich-su/", hi.stock_ledger, name="stock_ledger"),
    path("benh-vien/nhu-cau/", hi.demands, name="demands"),
    path("benh-vien/nhu-cau/<int:pk>/sua/", hi.demands, name="demand_edit"),
    path("benh-vien/nhu-cau/<int:pk>/dong/", hi.demand_close, name="demand_close"),

    path("benh-vien/tim-nguon/", ht.source_search, name="source_search"),
    path("benh-vien/yeu-cau-ho-tro/", ht.support_requests, name="support_requests"),
    path("benh-vien/yeu-cau-ho-tro/tao/", ht.support_request_create, name="support_request_create"),
    path("benh-vien/yeu-cau-ho-tro/<int:pk>/", ht.support_request_detail, name="support_request_detail"),
    path("benh-vien/yeu-cau-ho-tro/<int:pk>/xu-ly/", ht.support_request_action, name="support_request_action"),
    path("benh-vien/de-nghi/<int:pk>/yeu-cau/", ht.support_request_for_offer, name="support_request_for_offer"),
    path("benh-vien/de-nghi/<int:pk>/mo/", hospital.offer_open, name="offer_open"),
    path("benh-vien/de-nghi-den/", ht.incoming_offers, name="incoming_offers"),
    path("benh-vien/de-nghi-den/<int:pk>/", ht.offer_detail, name="offer_detail"),
    path("benh-vien/de-nghi-den/<int:pk>/xu-ly/", ht.offer_action, name="offer_action"),
    path("benh-vien/yeu-cau-can-mau/", ht.patient_requests, name="hospital_patient_requests"),
    path("benh-vien/yeu-cau-can-mau/<int:pk>/", ht.patient_request_detail, name="hospital_patient_request_detail"),
    path("benh-vien/yeu-cau-can-mau/<int:pk>/xu-ly/", ht.patient_request_action, name="hospital_patient_request_action"),

    path("benh-vien/thong-tin/", hospital.hospital_info, name="hospital_info"),
    path("benh-vien/nhan-vien/", hospital.hospital_staff, name="hospital_staff"),
    path("benh-vien/nhat-ky/", hospital.hospital_audit, name="hospital_audit"),
    path("danh-muc/", hospital.catalog, name="catalog"),

    # Quản trị (SCR-50..54)
    path("quan-tri/thong-ke/", admin.stats, name="admin_stats"),
    path("quan-tri/nguoi-dung/", admin.users, name="admin_users"),
    path("quan-tri/benh-vien/", admin.hospitals, name="admin_hospitals"),
    path("quan-tri/benh-vien/tao/", admin.hospital_form, name="admin_hospital_create"),
    path("quan-tri/benh-vien/<int:pk>/", admin.hospital_form, name="admin_hospital_edit"),
    path("quan-tri/nhat-ky/", admin.audit, name="admin_audit"),
    path("quan-tri/cau-hinh/", admin.settings_view, name="admin_settings"),
    path("quan-tri/phan-quyen/", admin.permissions_view, name="admin_permissions"),
]
