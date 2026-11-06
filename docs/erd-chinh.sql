-- ERD chính – Hệ thống quản lý hiến máu (PostgreSQL)
-- 19 bảng nghiệp vụ, 29 quan hệ chính. Dùng cho Visual Paradigm: Tools > DB > Reverse DDL

CREATE TABLE users (
    id BIGINT NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20) UNIQUE,
    password_hash VARCHAR(255),
    full_name VARCHAR(150),
    role VARCHAR(10),
    status VARCHAR(10),
    date_of_birth DATE,
    gender VARCHAR(10),
    blood_group VARCHAR(3),
    address VARCHAR(500),
    province VARCHAR(100),
    ward VARCHAR(100),
    email_verified_at TIMESTAMP,
    email_reminders BOOLEAN,
    terms_accepted_at TIMESTAMP,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE chat_conversations (
    id BIGINT NOT NULL,
    user_id BIGINT,
    title VARCHAR(120),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE chat_messages (
    id BIGINT NOT NULL,
    conversation_id BIGINT,
    role VARCHAR(10),
    text TEXT,
    cards JSONB,
    links JSONB,
    source VARCHAR(300),
    mode VARCHAR(10),
    created_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (conversation_id) REFERENCES chat_conversations (id)
);

CREATE TABLE notifications (
    id BIGINT NOT NULL,
    user_id BIGINT,
    type VARCHAR(50),
    title VARCHAR(200),
    body VARCHAR(1000),
    entity_type VARCHAR(50),
    entity_id BIGINT,
    channel VARCHAR(10),
    delivery_status VARCHAR(10),
    attempts SMALLINT,
    sent_at TIMESTAMP,
    read_at TIMESTAMP,
    created_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE auth_tokens (
    id BIGINT NOT NULL,
    user_id BIGINT,
    purpose VARCHAR(20),
    token_hash VARCHAR(64) UNIQUE,
    expires_at TIMESTAMP,
    used_at TIMESTAMP,
    revoked_at TIMESTAMP,
    created_ip VARCHAR(45),
    created_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE hospitals (
    id BIGINT NOT NULL,
    code VARCHAR(30) UNIQUE,
    name VARCHAR(255),
    address VARCHAR(500),
    province VARCHAR(100),
    district VARCHAR(100),
    ward VARCHAR(100),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    phone VARCHAR(20),
    email VARCHAR(255),
    status VARCHAR(10),
    reject_reason VARCHAR(500),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE campaigns (
    id BIGINT NOT NULL,
    hospital_id BIGINT,
    name VARCHAR(255),
    description TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    location_name VARCHAR(255),
    address VARCHAR(500),
    province VARCHAR(100),
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    status VARCHAR(10),
    cancel_reason VARCHAR(500),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (id)
);

CREATE TABLE products (
    id INTEGER NOT NULL,
    code VARCHAR(30) UNIQUE,
    name VARCHAR(150),
    kind VARCHAR(15),
    description VARCHAR(500),
    is_active BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE product_specs (
    id INTEGER NOT NULL,
    product_id INTEGER,
    code VARCHAR(30),
    name VARCHAR(150),
    unit_volume_ml INTEGER,
    is_default BOOLEAN,
    is_active BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE TABLE hospital_requests (
    id BIGINT NOT NULL,
    request_code VARCHAR(30) UNIQUE,
    requesting_hospital_id BIGINT,
    blood_group VARCHAR(3),
    product_spec_id INTEGER,
    quantity_needed INTEGER,
    priority VARCHAR(10),
    needed_by TIMESTAMP,
    status VARCHAR(20),
    note TEXT,
    created_by BIGINT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    closed_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (requesting_hospital_id) REFERENCES hospitals (id),
    FOREIGN KEY (product_spec_id) REFERENCES product_specs (id)
);

CREATE TABLE patient_requests (
    id BIGINT NOT NULL,
    request_code VARCHAR(30) UNIQUE,
    requester_id BIGINT,
    contact_name VARCHAR(150),
    contact_phone VARCHAR(20),
    patient_name VARCHAR(150),
    hospital_id BIGINT,
    blood_group VARCHAR(3),
    blood_product_id INTEGER,
    quantity_units INTEGER,
    needed_by TIMESTAMP,
    note TEXT,
    consent_at TIMESTAMP,
    status VARCHAR(12),
    verified_by BIGINT,
    verified_at TIMESTAMP,
    reject_reason VARCHAR(500),
    resolution_note TEXT,
    linked_support_request_id BIGINT,
    linked_campaign_id BIGINT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (requester_id) REFERENCES users (id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (id),
    FOREIGN KEY (linked_support_request_id) REFERENCES hospital_requests (id),
    FOREIGN KEY (linked_campaign_id) REFERENCES campaigns (id)
);

CREATE TABLE staffs (
    id BIGINT NOT NULL,
    hospital_id BIGINT,
    user_id BIGINT UNIQUE,
    staff_role VARCHAR(30),
    is_active BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

CREATE TABLE registrations (
    id BIGINT NOT NULL,
    campaign_id BIGINT,
    donor_id BIGINT,
    donation_type VARCHAR(15),
    status VARCHAR(15),
    source VARCHAR(10),
    note TEXT,
    registered_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id),
    FOREIGN KEY (donor_id) REFERENCES users (id)
);

CREATE TABLE donor_callouts (
    id BIGINT NOT NULL,
    hospital_id BIGINT,
    blood_group VARCHAR(3),
    campaign_id BIGINT,
    created_by BIGINT,
    recipient_count INTEGER,
    created_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
);

CREATE TABLE donations (
    id BIGINT NOT NULL,
    donor_id BIGINT,
    registration_id BIGINT,
    hospital_id BIGINT,
    donation_type VARCHAR(15),
    volume_ml INTEGER,
    component_product_id INTEGER,
    component_quantity DECIMAL(10,2),
    component_unit VARCHAR(5),
    donated_at TIMESTAMP,
    status VARCHAR(10),
    confirmed_by BIGINT,
    confirmed_at TIMESTAMP,
    void_reason VARCHAR(500),
    voided_by BIGINT,
    voided_at TIMESTAMP,
    note TEXT,
    lab_status VARCHAR(10),
    lab_blood_group VARCHAR(3),
    lab_note VARCHAR(500),
    lab_checked_by BIGINT,
    lab_checked_at TIMESTAMP,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (registration_id) REFERENCES registrations (id)
);

CREATE TABLE stocks (
    id BIGINT NOT NULL,
    hospital_id BIGINT,
    blood_group VARCHAR(3),
    product_spec_id INTEGER,
    quantity_on_hand INTEGER,
    quantity_reserved INTEGER,
    min_stock_level INTEGER,
    shareable_quantity INTEGER,
    version INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (id),
    FOREIGN KEY (product_spec_id) REFERENCES product_specs (id)
);

CREATE TABLE request_offers (
    id BIGINT NOT NULL,
    request_id BIGINT,
    supplier_hospital_id BIGINT,
    status VARCHAR(15),
    quantity_requested INTEGER,
    quantity INTEGER,
    quantity_received INTEGER,
    reject_reason VARCHAR(500),
    failure_reason VARCHAR(500),
    responded_by BIGINT,
    responded_at TIMESTAMP,
    dispatched_by BIGINT,
    dispatched_at TIMESTAMP,
    received_by BIGINT,
    received_at TIMESTAMP,
    note TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (request_id) REFERENCES hospital_requests (id),
    FOREIGN KEY (supplier_hospital_id) REFERENCES hospitals (id)
);

CREATE TABLE stock_txns (
    id BIGINT NOT NULL,
    stock_id BIGINT,
    lot_id BIGINT,
    txn_type VARCHAR(20),
    quantity_change INTEGER,
    quantity_before INTEGER,
    quantity_after INTEGER,
    adjustment_reason VARCHAR(25),
    reason_note VARCHAR(500),
    offer_id BIGINT,
    patient_request_id BIGINT,
    demand_id BIGINT,
    donation_id BIGINT,
    idempotency_key VARCHAR(100) UNIQUE,
    performed_by BIGINT,
    occurred_at TIMESTAMP,
    created_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (stock_id) REFERENCES stocks (id),
    FOREIGN KEY (offer_id) REFERENCES request_offers (id),
    FOREIGN KEY (patient_request_id) REFERENCES patient_requests (id),
    FOREIGN KEY (donation_id) REFERENCES donations (id)
);

CREATE TABLE forecast_snapshots (
    id BIGINT NOT NULL,
    hospital_id BIGINT,
    blood_group VARCHAR(3),
    product_spec_id INTEGER,
    origin DATE,
    target_date DATE,
    h SMALLINT,
    method VARCHAR(3),
    predicted DOUBLE PRECISION,
    baseline DOUBLE PRECISION,
    model_version VARCHAR(40),
    created_at TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (id),
    FOREIGN KEY (product_spec_id) REFERENCES product_specs (id)
);
