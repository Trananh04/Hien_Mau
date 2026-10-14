# 05 · Độ bao phủ

Không có số liệu đo "% dòng code" cho vòng này (chưa chạy coverage.py). Bảng dưới đánh giá bao phủ theo chức năng, dựa trên những gì đã thực sự chạy.

| Module | Routes | Đã kiểm thử vòng này | Bộ test gốc (98) | Mức bao phủ | Kết quả |
|---|---|---|---|---|---|
| Xác thực (3 cổng, đăng ký, quên mật khẩu) | 9 | Khóa tài khoản / liệt kê, giới hạn email, IP nhật ký, escape `next` | Có | Tốt | 3 lỗi bảo mật thấp–TB |
| Phân quyền & cô lập bệnh viện | 80 | Cô lập BV A/B (GET + POST) | Ma trận route × vai trò | Tốt | Pass |
| Đợt hiến / điểm hiến / lượt hiến | 16 | Sửa giờ đợt, hủy đợt, sửa lượt hiến, tham số sai | Có | Khá | BUG-01, 05, 06 |
| Xét nghiệm → kho | 2 | Giới hạn số lượng, hủy lượt hiến sau nhập kho | Có | Khá | BUG-02, 03 |
| Kho (nhập/xuất/điều chỉnh/sổ kho) | 6 | Tham số sai | Có (idempotency, âm kho, trigger) | Khá | BUG-04 |
| Điều phối liên viện | 12 | Tham số sai | Có | Trung bình — **chưa thử đồng thời** | BUG-04 |
| Yêu cầu cần máu | 6 | — | Có | Trung bình | — |
| Nhu cầu & kêu gọi | 4 | — | Có | Trung bình | — |
| Quản trị | 8 | Tham số sai (danh mục) | Có | Trung bình | BUG-04 |
| Giao diện (40 trang, 2 khung nhìn) | — | Playwright 80 lượt | Smoke test HTML | Tốt cho hiển thị; **chưa** test thao tác form qua trình duyệt | Pass |
| Cấu hình / header / phụ thuộc | — | Semgrep, ZAP baseline, Nuclei, check --deploy | — | Tốt (thụ động) | SEC-04..07 |

## Giới hạn của kết quả
- **Đồng thời:** chưa chạy kiểm thử song song trong vòng này. Bộ test gốc kiểm tra khóa dòng và idempotency theo từng request, không phải tải song song thật. Nghi vấn S-02 (vượt ngưỡng khóa đăng nhập) chưa được chứng minh.
- **Bảo mật chủ động:** chỉ quét thụ động. Chưa chạy ZAP active scan, Strix, Shannon.
- **Không có REST API**, nên "API testing" ở đây là các endpoint form/JSON phía server.
- Môi trường QA chạy HTTP. Các kiểm tra phụ thuộc HTTPS (HSTS, cookie Secure) chỉ đánh giá qua cấu hình.
- Tập dữ liệu là dữ liệu mẫu nhỏ (5 bệnh viện, 8 người dùng). Chưa kiểm thử hiệu năng hay khối lượng lớn.
