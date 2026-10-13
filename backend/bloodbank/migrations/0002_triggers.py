"""Trigger PostgreSQL tương đương các trigger MySQL trong `hien_mau_v2.sql`.

Mỗi trigger báo lỗi bằng thông điệp bắt đầu bằng mã ERR-* để tầng ứng dụng ánh xạ sang lỗi nghiệp vụ.
"""
from django.db import migrations

UPDATED_AT_TABLES = [
    "users", "hospitals", "staffs", "campaigns", "registrations", "products", "product_specs", "donations",
    "stocks", "stock_lots", "demands", "hospital_requests", "request_offers", "patient_requests", "system_settings",
]

FORWARD = r"""
-- updated_at do CSDL tự cập nhật (tương đương ON UPDATE CURRENT_TIMESTAMP(6))
CREATE OR REPLACE FUNCTION fn_set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$ LANGUAGE plpgsql;

-- trg_donations_donor_match_ins: donor_id phải khớp người đăng ký của đơn
CREATE OR REPLACE FUNCTION fn_donations_donor_match() RETURNS trigger AS $$
DECLARE reg_donor bigint;
BEGIN
  IF NEW.registration_id IS NOT NULL THEN
    SELECT donor_id INTO reg_donor FROM registrations WHERE id = NEW.registration_id;
    IF reg_donor IS DISTINCT FROM NEW.donor_id THEN
      RAISE EXCEPTION 'ERR-DON-DONOR-MISMATCH: donor_id không khớp đơn đăng ký' USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_donations_donor_match_ins BEFORE INSERT ON donations
  FOR EACH ROW EXECUTE FUNCTION fn_donations_donor_match();

-- trg_donations_immutable_upd: không sửa người hiến/đơn/bệnh viện/người xác nhận; bản ghi voided bất biến
CREATE OR REPLACE FUNCTION fn_donations_immutable() RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'voided' THEN
    RAISE EXCEPTION 'ERR-DON-VOIDED-IMMUTABLE: lượt hiến đã hủy hiệu lực không được sửa' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.donor_id <> OLD.donor_id
     OR NEW.registration_id IS DISTINCT FROM OLD.registration_id
     OR NEW.hospital_id <> OLD.hospital_id
     OR NEW.confirmed_by <> OLD.confirmed_by THEN
    RAISE EXCEPTION 'ERR-DON-IMMUTABLE-FIELD: không được sửa người hiến, đơn, bệnh viện, người xác nhận'
      USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_donations_immutable_upd BEFORE UPDATE ON donations
  FOR EACH ROW EXECUTE FUNCTION fn_donations_immutable();

-- Sổ kho và nhật ký chỉ thêm (BR-41)
CREATE OR REPLACE FUNCTION fn_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'ERR-APPEND-ONLY: bảng % chỉ cho phép thêm mới', TG_TABLE_NAME USING ERRCODE = 'P0001';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_stock_txns_no_update BEFORE UPDATE ON stock_txns FOR EACH ROW EXECUTE FUNCTION fn_append_only();
CREATE TRIGGER trg_stock_txns_no_delete BEFORE DELETE ON stock_txns FOR EACH ROW EXECUTE FUNCTION fn_append_only();
CREATE TRIGGER trg_audit_logs_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW EXECUTE FUNCTION fn_append_only();
CREATE TRIGGER trg_audit_logs_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW EXECUTE FUNCTION fn_append_only();

-- trg_offers_no_self_supply_ins/upd: bên cấp khác bên yêu cầu; không đổi request/supplier (BR-44)
CREATE OR REPLACE FUNCTION fn_offers_no_self_supply() RETURNS trigger AS $$
DECLARE requester bigint;
BEGIN
  IF TG_OP = 'UPDATE' AND (NEW.request_id <> OLD.request_id OR NEW.supplier_hospital_id <> OLD.supplier_hospital_id) THEN
    RAISE EXCEPTION 'ERR-HRQ-IMMUTABLE: không được đổi yêu cầu hoặc bệnh viện cấp' USING ERRCODE = 'P0001';
  END IF;
  SELECT requesting_hospital_id INTO requester FROM hospital_requests WHERE id = NEW.request_id;
  IF requester = NEW.supplier_hospital_id THEN
    RAISE EXCEPTION 'ERR-HRQ-SELF-SUPPLY: bệnh viện không thể tự cấp cho yêu cầu của mình' USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_offers_no_self_supply_ins BEFORE INSERT ON request_offers
  FOR EACH ROW EXECUTE FUNCTION fn_offers_no_self_supply();
CREATE TRIGGER trg_offers_no_self_supply_upd BEFORE UPDATE ON request_offers
  FOR EACH ROW EXECUTE FUNCTION fn_offers_no_self_supply();
""" + "\n".join(
    f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();"
    for t in UPDATED_AT_TABLES
)

BACKWARD = "\n".join(
    [f"DROP TRIGGER IF EXISTS trg_{t}_updated_at ON {t};" for t in UPDATED_AT_TABLES]
    + [
        "DROP TRIGGER IF EXISTS trg_offers_no_self_supply_upd ON request_offers;",
        "DROP TRIGGER IF EXISTS trg_offers_no_self_supply_ins ON request_offers;",
        "DROP TRIGGER IF EXISTS trg_audit_logs_no_delete ON audit_logs;",
        "DROP TRIGGER IF EXISTS trg_audit_logs_no_update ON audit_logs;",
        "DROP TRIGGER IF EXISTS trg_stock_txns_no_delete ON stock_txns;",
        "DROP TRIGGER IF EXISTS trg_stock_txns_no_update ON stock_txns;",
        "DROP TRIGGER IF EXISTS trg_donations_immutable_upd ON donations;",
        "DROP TRIGGER IF EXISTS trg_donations_donor_match_ins ON donations;",
        "DROP FUNCTION IF EXISTS fn_offers_no_self_supply();",
        "DROP FUNCTION IF EXISTS fn_append_only();",
        "DROP FUNCTION IF EXISTS fn_donations_immutable();",
        "DROP FUNCTION IF EXISTS fn_donations_donor_match();",
        "DROP FUNCTION IF EXISTS fn_set_updated_at();",
    ]
)


class Migration(migrations.Migration):
    dependencies = [("bloodbank", "0001_initial"), ("accounts", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
