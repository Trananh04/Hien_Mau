# 03 · Báo cáo lỗi chức năng / nghiệp vụ

Đợt kiểm thử: 14/10/2026 · Môi trường: QA cô lập `127.0.0.1:8091` (DB riêng, dữ liệu giả) + DB test của Django.
Chỉ ghi lỗi **đã tái hiện có bằng chứng** (Confirmed). Nghi vấn chưa chứng minh nằm ở mục cuối.

| ID | Mức | Tiêu đề | Trạng thái |
|---|---|---|---|
| BUG-01 | **Cao** | Sửa lượt hiến luôn lỗi 500 | Confirmed → **Đã sửa** |
| BUG-02 | Trung bình | Hủy hiệu lực lượt hiến đã nhập kho không trừ kho | Confirmed → **Đã sửa** |
| BUG-03 | Trung bình | Không giới hạn số đơn vị nhập kho từ 1 lượt hiến | Confirmed → **Đã sửa** |
| BUG-04 | Trung bình | 12 điểm nhận tham số sai kiểu gây lỗi 500 | Confirmed → **Đã sửa** |
| BUG-05 | Thấp | Sửa giờ đợt hiến làm lượt hiến đã xác nhận nằm ngoài khung giờ đợt | Confirmed → **Đã sửa** |
| BUG-06 | Thấp | Hủy đợt hiến để lại đơn "Đã check-in" treo | Confirmed → **Đã sửa** |
| BUG-07 | Thấp | `__all__` của `bloodbank.models` còn tên model đã xóa | Confirmed · **đã sửa** |

---

## BUG-01 · Sửa lượt hiến luôn lỗi 500 — Cao

- **Module:** Lượt hiến (SCR-25) · `POST /benh-vien/luot-hien/<id>/quan-ly/` `action=edit`
- **Điều kiện:** đăng nhập Nhân viên bệnh viện; lượt hiến `confirmed` của bệnh viện mình.
- **Các bước:** mở chi tiết lượt hiến → "Sửa" → nhập lý do → Lưu.
- **Kỳ vọng:** số liệu được cập nhật, ghi nhật ký old/new.
- **Thực tế:** HTTP 500 với **mọi** lượt hiến. Chức năng UC-DON-03 không dùng được.
- **Bằng chứng:**
  - HTTP thật trên môi trường QA: `POST /benh-vien/luot-hien/1/quan-ly/ → HTTP 500` (`evidence/runs/confirm-live/confirm_live.txt`)
  - Log server: `psycopg.errors.FeatureNotSupported: FOR UPDATE cannot be applied to the nullable side of an outer join`
  - Test `InventoryIntegrityTests.test_edit_donation_type_after_stock_in_blocked` → ERROR cùng lỗi (`evidence/django-qa-audit-tests.txt`)
- **Nguyên nhân:** [donations.py:158](../../backend/bloodbank/services/donations.py#L158) — `Donation.objects.select_for_update().select_related("registration__campaign")`; `registration` là FK cho phép NULL → LEFT JOIN; PostgreSQL không khóa được phía NULL của outer join. Bộ test hiện có không có test nào gọi `edit_donation` nên lỗi lọt qua.
- **Đề xuất sửa:** `select_for_update(of=("self",))` (như `record_donation` đang làm), hoặc bỏ `select_related` và lấy campaign sau khi khóa.
- **Regression test:** gọi `don.edit_donation(...)` thành công trên PostgreSQL + HTTP POST trả 302.

## BUG-02 · Hủy hiệu lực lượt hiến đã nhập kho không trừ kho — Trung bình

- **Module:** Lượt hiến ↔ Kho (SCR-25, SCR-29)
- **Các bước:** ghi nhận lượt hiến → xét nghiệm **Đạt** (nhập kho 1 đơn vị) → Hủy hiệu lực lượt hiến ("Ghi nhầm người hiến").
- **Kỳ vọng:** chặn hủy khi đã nhập kho, hoặc tự sinh phiếu trừ kho tương ứng.
- **Thực tế:** lượt hiến chuyển `voided`, kho vẫn giữ đơn vị nhập từ lượt hiến đó; không có phiếu điều chỉnh. Tồn kho cao hơn thực tế, có thể bị xuất dùng.
- **Bằng chứng:** `test_void_after_lab_passed_keeps_stock_consistent` → `AssertionError: 1 != 0 : Lượt hiến đã hủy hiệu lực nhưng 1 đơn vị nhập từ nó vẫn còn trong kho`.
- **Vị trí:** [donations.py:126-148](../../backend/bloodbank/services/donations.py#L126) (`void_donation` không xét `lab_status` / `stock_txns`).
- **Đề xuất:** nếu `lab_status == passed`: chặn hủy (yêu cầu điều chỉnh kho trước) hoặc ghi phiếu `adjustment` âm trên đúng dòng tồn trong cùng giao dịch (kiểm tra phần khả dụng).
- **Regression test:** test trên (chuyển sang PASS).

## BUG-03 · Không giới hạn số đơn vị nhập kho từ 1 lượt hiến — Trung bình

- **Module:** Chờ xét nghiệm → nhập kho (SCR-29) · `POST /benh-vien/luot-hien/<id>/xet-nghiem/`
- **Các bước:** lượt hiến toàn phần 350 ml → kết quả Đạt với `quantity=100000`.
- **Kỳ vọng:** từ chối (1 túi toàn phần = 1 đơn vị; chế phẩm có giới hạn hợp lý).
- **Thực tế:** chấp nhận, kho +100.000 đơn vị.
- **Bằng chứng:** `test_lab_quantity_bounded` → `BusinessError not raised : Nhập kho 100000 đơn vị từ 1 lượt hiến được chấp nhận`.
- **Vị trí:** [lab.py:57](../../backend/bloodbank/services/lab.py#L57) — `positive_int(data.get("quantity") or 1)` không có cận trên.
- **Đề xuất:** toàn phần cố định 1; thành phần giới hạn theo cấu hình (vd. `lab_max_units_per_donation`).

## BUG-04 · Tham số sai kiểu gây lỗi 500 — Trung bình

Nhân viên/quản trị đã đăng nhập gửi giá trị không phải số → lỗi 500 thay vì 400/404/thông báo. Ảnh hưởng: trải nghiệm, nhiễu log lỗi, có thể bị lợi dụng để làm đầy log.

| # | Request | Nguyên nhân |
|---|---|---|
| 1 | `GET /benh-vien/dot-hien/<id>/diem-hien/?reg=abc` | `filter(pk=request.GET["reg"])` — [hospital_campaigns.py:160](../../backend/bloodbank/views/hospital_campaigns.py#L160) |
| 2 | `GET /benh-vien/nguoi-hien/?donor=abc` | [hospital_campaigns.py:286](../../backend/bloodbank/views/hospital_campaigns.py#L286) |
| 3–5 | `GET /benh-vien/kho/lich-su/?spec=abc` · `?stock=abc` · `?from=2026-13-45` | lọc trực tiếp bằng chuỗi — [hospital_inventory.py](../../backend/bloodbank/views/hospital_inventory.py) `stock_ledger` |
| 6 | `GET /benh-vien/tim-nguon/?blood_group=O%2B&product=abc` | `search_sources(... product_id)` |
| 7 | `GET /benh-vien/tim-nguon/?patient_request=abc` | [hospital_transfers.py:46](../../backend/bloodbank/views/hospital_transfers.py#L46) |
| 8 | `POST /benh-vien/kho/phieu/xuat/` `stock_id=abc` | `_lock_own_stock` — [inventory.py:91](../../backend/bloodbank/services/inventory.py#L91) |
| 9 | `POST /benh-vien/yeu-cau-ho-tro/tao/` `supplier=abc` | `int(hospital_id)` — [transfers.py:141](../../backend/bloodbank/services/transfers.py#L141) |
| 10 | `POST /thong-bao/da-doc/` `id=abc` | [member.py:216](../../backend/bloodbank/views/member.py#L216) |
| 11 | `GET /danh-muc/?product=abc` (quản trị) | [hospital.py:149](../../backend/bloodbank/views/hospital.py#L149) |
| 12 | `POST /benh-vien/kho/<id>/cau-hinh/` `version=abc` | `int(version)` — [inventory.py:172](../../backend/bloodbank/services/inventory.py#L172) |

Ghi chú: `min_qty=abc` ở Tìm nguồn **không** lỗi (đã kiểm tra, PASS).

- **Bằng chứng:** `test_no_500_on_malformed_ids` (liệt kê đủ 12 request → 500); HTTP thật trên QA cho #2, #5, #6 → 500, log `ValueError` / `ValidationError`.
- **Đề xuất:** một helper `int_or_404()` / `int_or_none()` cho tham số GET/POST; dùng Form để kiểm tra ngày; ở service, `positive_int`/`BusinessError("ERR-VALIDATION")` thay cho `int()` trần.

## BUG-05 · Sửa giờ đợt làm lượt hiến nằm ngoài khung giờ — Thấp

- **Các bước:** đợt đang mở có lượt hiến lúc 07:14 → sửa giờ bắt đầu thành 07:44.
- **Thực tế:** chấp nhận; lượt hiến 07:14 nằm ngoài đợt 07:44–12:14 (trong khi `record_donation`/`edit_donation` bắt buộc thời điểm hiến nằm trong khung đợt).
- **Bằng chứng:** `test_edit_time_cannot_exclude_existing_donations`.
- **Vị trí:** [campaigns.py:32](../../backend/bloodbank/services/campaigns.py#L32) `update_campaign`.
- **Đề xuất:** khi đợt đã có lượt hiến confirmed, chỉ cho phép khung giờ mới bao trọn mọi `donated_at`.

## BUG-06 · Hủy đợt để lại đơn "Đã check-in" — Thấp

- **Các bước:** đợt mở, 1 đơn đã check-in (chưa ghi nhận hiến) → Hủy đợt.
- **Thực tế:** đơn vẫn `attended`; chỉ đơn `pending/approved` được hủy. Đơn treo vĩnh viễn (không ghi nhận hiến được vì đợt đã hủy).
- **Bằng chứng:** `test_cancel_campaign_closes_checked_in_registrations`.
- **Vị trí:** [campaigns.py:103-109](../../backend/bloodbank/services/campaigns.py#L103).
- **Đề xuất:** hủy đợt thì chuyển cả đơn `attended` sang `not_donated` (hoặc `cancelled`) và thông báo.

## BUG-07 · `__all__` còn tên model đã xóa — Thấp · đã sửa

- Lỗi do lần gỡ tính năng AI trước đó để sót: `from bloodbank.models import *` → `AttributeError: CalloutRecipient`.
- Đã sửa [models/__init__.py](../../backend/bloodbank/models/__init__.py); `import *` chạy được; 98 test gốc đạt.

---

## Nghi vấn chưa chứng minh (Suspected / Blocked)

| ID | Nội dung | Trạng thái | Lý do |
|---|---|---|---|
| S-01 | Đổi loại lượt hiến (toàn phần → thành phần) sau khi đã nhập kho | **Confirmed → Đã sửa** | Kiểm được sau khi sửa BUG-01: trước đó được phép; nay chặn khi đã nhập kho |
| S-02 | Gửi đồng thời nhiều lần đăng nhập sai có thể vượt ngưỡng khóa 5 lần (đếm số lần sai trước khi kiểm tra mật khẩu, không khóa dòng) | **Suspected** | Có dấu hiệu trong code ([accounts/services.py:88](../../backend/accounts/services.py#L88)); chưa chạy kiểm thử đồng thời |
| S-03 | Bên nhận tự đánh dấu "hàng quay về bên cấp" làm tăng kho bên cấp không cần bên cấp xác nhận | **Suspected (thiết kế)** | Cần chủ sản phẩm xác nhận quy trình |

---

## Kết quả sau khi sửa (14/10/2026)

| Lỗi | Cách sửa | Kiểm chứng |
|---|---|---|
| BUG-01 | `select_for_update(of=("self",))` | Test service + HTTP; QA thật: `POST /benh-vien/luot-hien/1/quan-ly/` → 302, nhật ký có bản ghi `update` |
| BUG-02 | Hủy lượt hiến đã nhập kho → tự ghi phiếu `adjustment` âm (lý do "Nhập sai dữ liệu", ghi chú mã lượt hiến); nếu đơn vị đã xuất/giữ chỗ → chặn hủy | 3 test: trừ đúng 2 đơn vị · chặn khi đã xuất · lượt chưa nhập kho vẫn hủy được |
| BUG-03 | Cấu hình mới `lab_max_units_per_donation` (mặc định 3), ô nhập có `max` | 100000 và 4 bị từ chối, 3 được nhận |
| BUG-04 | Helper `int_or_none`/`date_or_none` (view) và `as_id` (service) cho mọi id/ngày từ client; thêm vài chỗ cùng loại tìm được khi rà (`offer_id`, `spec_id`, `product_spec_id`, `campaign_id`, id trong danh mục, quản trị) | 13 request → không còn 500; QA thật: 404/200 |
| BUG-05 | Đợt đã có lượt hiến: khung giờ mới phải bao trọn mọi `donated_at` (ERR-CMP-TIME-RANGE) | Thu hẹp sai bị chặn, sửa hợp lệ vẫn được |
| BUG-06 | Hủy đợt → hủy cả đơn `attended` + thông báo | Test |
| S-01 | Lượt hiến đã nhập kho không đổi được hình thức / chế phẩm | Test |

Bộ test: **115/115 PASS** (98 cũ + 17 hồi quy trong `test_qa_audit.py`). Playwright sau khi sửa: 80/80 lượt không có vấn đề thật.
