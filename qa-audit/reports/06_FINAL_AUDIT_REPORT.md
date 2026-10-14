# 06 · Báo cáo tổng hợp — Vòng kiểm thử 1

> **Cập nhật vòng 2:** kiểm thử đồng thời 11 kịch bản (1 lỗi race ở khóa đăng nhập, đã xác nhận và đã sửa) · 11/11 luồng thao tác giao diện · trợ năng axe 0 vi phạm · CSP + cấu hình HTTPS · ZAP active scan 0 FAIL / 136 PASS · kiểm tra UI/UX trước/sau (07_UI_UX_REPORT.md) · 126/126 test Django.
>
> **Cập nhật sau khi sửa (vòng 1):** BUG-01…06, S-01, SEC-01…04 và phần lớn SEC-07 đã sửa. 115/115 test đạt; xác nhận lại trên ứng dụng QA (không còn lỗi 500), Playwright 80/80, Semgrep hết cảnh báo root. Còn mở: SEC-05 (CSP), SEC-06 (bật khi có HTTPS), S-02 (kiểm thử đồng thời đăng nhập), S-03 (xác nhận quy trình).

**Ngày:** 14/10/2026 · **Đối tượng:** Ngân Hàng Máu Sống (Django 5.2 + PostgreSQL 16) · **Môi trường:** QA cô lập `127.0.0.1:8091`, DB riêng, dữ liệu giả. Không tác động môi trường dev (8080) hay production.

## Số liệu

| Nhóm | Đã chạy | Pass | Fail | Error | Blocked / Not Run |
|---|---|---|---|---|---|
| Test kiểm chứng (Django) | 11 (13 ca con ở VAL) | 2 | 8 | 1 | — |
| Kiểm tra HTTP thật trên QA | 6 | 2 | 4 | — | — |
| Giao diện Playwright | 80 lượt trang | 80 | 0 | — | — |
| Bộ test hồi quy gốc | 98 | 98 | 0 | — | — |
| Quét tự động | 4 công cụ | — | — | — | ZAP active, Strix, Shannon, Hercules: Blocked |
| Kịch bản đồng thời | — | — | — | — | Not Run |

**Lỗi đã xác nhận: 7 lỗi chức năng (1 cao, 3 trung bình, 3 thấp, 1 đã sửa) + 7 vấn đề bảo mật/cấu hình.** Không phát hiện lỗi phân quyền hay rò dữ liệu giữa các bệnh viện.

## Ưu tiên sửa

1. **BUG-01 (Cao)** — Sửa lượt hiến luôn lỗi 500. Một dòng: `select_for_update(of=("self",))` ở `donations.py:158`. Kèm test gọi `edit_donation` (hiện không có test nào gọi hàm này).
2. **BUG-02 (TB)** — Hủy lượt hiến đã nhập kho → kho lệch. Chặn hủy hoặc tự sinh phiếu trừ kho.
3. **BUG-03 (TB)** — Giới hạn số đơn vị nhập kho từ 1 lượt hiến.
4. **BUG-04 (TB)** — 12 điểm lỗi 500 do tham số sai kiểu: thêm helper kiểm tra số/ngày.
5. **SEC-01 (TB)** — IP nhật ký lấy từ `X-Forwarded-For`.
6. **SEC-07 (cấu hình)** — Trước khi triển khai: bind DB/pgAdmin về `127.0.0.1`, bỏ `SECRET_KEY` dự phòng, `SEED_DEMO=0`, bỏ `--reload`, bật HTTPS settings, thêm CSP, `USER` không phải root.
7. BUG-05, BUG-06, SEC-02, SEC-03 — mức thấp.

## Ảnh hưởng nghiệp vụ
- **Tồn kho có thể sai lệch so với thực tế** (BUG-02, BUG-03). Với ngân hàng máu, đây là rủi ro trực tiếp: hệ thống hiển thị máu "khả dụng" không tồn tại → có thể chấp thuận đề nghị liên viện hoặc xuất kho dựa trên số liệu sai.
- **Không sửa được sai sót lượt hiến** (BUG-01). Nhân viên chỉ còn cách hủy hiệu lực, mà hủy lại gây lệch kho (BUG-02).
- **Nhật ký kiểm toán không đáng tin về IP** (SEC-01) khi cần truy vết truy cập dữ liệu bệnh nhân.

## Điểm tốt đã xác minh
- Phân quyền 3 lớp hoạt động đúng: ma trận route × vai trò, cô lập bệnh viện, cổng đăng nhập theo vai trò.
- Có bảo vệ CSRF, escape template (không phát hiện XSS), chống open redirect. Cookie phiên có HttpOnly và SameSite=Lax.
- Có các header X-Frame-Options, nosniff, Referrer-Policy.
- Giao diện 40 trang × 2 khung nhìn không lỗi JS, không tràn ngang.

## Bước tiếp theo đề xuất
1. Sửa BUG-01 rồi chạy lại `--tag qa_audit` để mở khóa S-01.
2. Vòng 2 — kiểm thử đồng thời trên DB QA: đăng nhập sai song song (S-02), xuất kho và chấp thuận đề nghị song song, gửi trùng form.
3. ZAP active scan trên môi trường QA (cần phê duyệt).
4. Strix / Shannon nếu có API key và ngân sách (cần phê duyệt).
5. Đo coverage dòng code (`coverage run manage.py test`).

## Tài liệu
`01_SYSTEM_INVENTORY.md` · `02_TEST_CASES.md` · `03_BUG_REPORT.md` · `04_SECURITY_REPORT.md` · `05_COVERAGE_REPORT.md` · bằng chứng trong `../evidence/` và `../security/raw/`.
