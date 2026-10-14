# 02 · Test case đã chạy

Trạng thái: **Pass** · **Fail** (lỗi đã tái hiện) · **Error** (test không chạy hết vì lỗi hệ thống) · **Blocked** · **Not Run**.
Mọi test dưới đây đã chạy thật ngày 14/10/2026.

## A. Test kiểm chứng nghi vấn — `backend/bloodbank/tests/test_qa_audit.py` (DB test PostgreSQL)

Bằng chứng: `qa-audit/evidence/django-qa-audit-tests.txt`. Chạy lại: `docker compose exec web python manage.py test --tag qa_audit`.

| ID | Module | Ưu tiên | Bước chính | Kỳ vọng | Thực tế | Trạng thái | Bug |
|---|---|---|---|---|---|---|---|
| QA-VAL-01 | Nhiều màn hình | P2 | 13 request với tham số sai kiểu (`abc`, ngày 2026-13-45) | Không có 5xx | 12/13 trả 500 (`min_qty=abc` OK) | **Fail** | BUG-04 |
| QA-BL-01 | Lượt hiến ↔ kho | P1 | Ghi nhận → xét nghiệm đạt → hủy hiệu lực | Kho −1 hoặc chặn hủy | Hủy được, kho giữ nguyên | **Fail** | BUG-02 |
| QA-BL-02 | Xét nghiệm → kho | P1 | Kết quả đạt với `quantity=100000` | Từ chối | Chấp nhận | **Fail** | BUG-03 |
| QA-BL-03 | Lượt hiến | P1 | Đổi loại lượt hiến sau khi nhập kho | Từ chối | `NotSupportedError` khi sửa bất kỳ lượt hiến | **Error** | BUG-01 (S-01 Blocked) |
| QA-BL-04 | Đợt hiến | P2 | Sửa giờ bắt đầu sau thời điểm lượt hiến đã có | Từ chối | Chấp nhận | **Fail** | BUG-05 |
| QA-BL-05 | Đợt hiến | P3 | Hủy đợt có đơn đã check-in | Đơn không còn `attended` | Vẫn `attended` | **Fail** | BUG-06 |
| QA-SEC-01 | Nhật ký | P2 | Đăng nhập kèm `X-Forwarded-For` giả | Ghi IP thật | Ghi IP giả | **Fail** | SEC-01 |
| QA-SEC-02 | Điều hướng | P2 | `next="/\t/evil"`, `"/\\evil"` ở 2 màn hình | Không dẫn ra ngoài | `Location` được mã hóa thành đường dẫn nội bộ | **Pass** | — |
| QA-SEC-03 | Đăng nhập | P3 | Sai mật khẩu: tài khoản khóa vs email không có | Cùng thông báo | Khác thông báo | **Fail** | SEC-02 |
| QA-SEC-04 | Quên mật khẩu | P3 | 8 yêu cầu liên tiếp | ≤ 3 email | 8 email | **Fail** | SEC-03 |
| QA-AZ-01 | Phân quyền | P1 | Nhân viên BV B: 4 GET + 3 POST vào dữ liệu BV A | 404, dữ liệu không đổi | Đúng kỳ vọng | **Pass** | — |

## B. Kiểm tra trên ứng dụng QA đang chạy (HTTP thật)

Bằng chứng: `evidence/runs/confirm-live/confirm_live.txt` + log container. Script: `scripts/confirm_live.py`.

| ID | Request | Kỳ vọng | Thực tế | Trạng thái |
|---|---|---|---|---|
| LIVE-01 | `GET /benh-vien/luot-hien/1/` (benhvien1) | 200 | 200 | Pass |
| LIVE-02 | `POST /benh-vien/luot-hien/1/quan-ly/ action=edit` | 302 + cập nhật | **500** (`FeatureNotSupported`) | **Fail** (BUG-01) |
| LIVE-03 | `GET /benh-vien/nguoi-hien/?donor=abc` | 404 | **500** | **Fail** (BUG-04) |
| LIVE-04 | `GET /benh-vien/kho/lich-su/?from=2026-13-45` | 200 + bỏ lọc | **500** | **Fail** (BUG-04) |
| LIVE-05 | `GET /benh-vien/tim-nguon/?blood_group=O+&product=abc` | 200/400 | **500** | **Fail** (BUG-04) |
| LIVE-06 | `GET /dang-nhap/?next="><b>qa` | Giá trị được escape | Escape đúng | Pass |

## C. Giao diện — Playwright (Chromium 1.48, headless)

Script: `playwright/ui_smoke.py` · Kết quả: `evidence/runs/ui/ui_results.json` + 80 ảnh chụp.

| Phạm vi | Số lượt | Kiểm tra | Kết quả |
|---|---|---|---|
| 4 vai trò × 2 khung nhìn (1366×850, 390×844) × 40 trang | 80 | HTTP đúng kỳ vọng (404 cho trang không tồn tại), lỗi JS/console, request ≥400, tràn ngang, chữ bị cắt | **80/80 Pass** |

Bị loại khỏi kết quả vì do môi trường chứ không phải lỗi ứng dụng:
- Cảnh báo Cross-Origin-Opener-Policy bị bỏ qua: trình duyệt bỏ qua header này trên origin HTTP không phải `localhost`.
- Không tải được ô bản đồ OpenStreetMap: container kiểm thử không có Internet.

## D. Quét tự động

| ID | Công cụ | Kết quả | Trạng thái |
|---|---|---|---|
| SCAN-01 | Semgrep 276 rule | 24 cảnh báo → 1 thật (SEC-04), 23 false positive (xem 04_SECURITY_REPORT) | Done |
| SCAN-02 | ZAP baseline (thụ động) | 56 PASS · 11 WARN · 0 FAIL | Done |
| SCAN-03 | Nuclei (template an toàn) | 7 info | Done |
| SCAN-04 | Django `check --deploy` | 4 cảnh báo HTTPS/cookie | Done |

## E. Bộ test hồi quy có sẵn của dự án

`python manage.py test --exclude-tag qa_audit` → **98/98 Pass**. Gồm ràng buộc CSDL, luồng nghiệp vụ qua HTTP, ma trận phân quyền mọi route × vai trò, 3 cổng đăng nhập và smoke test mọi màn hình.

## F. Chưa chạy

| ID | Nội dung | Trạng thái | Lý do |
|---|---|---|---|
| NR-01 | Đổi loại lượt hiến sau nhập kho | Blocked | Phụ thuộc BUG-01 |
| NR-02 | Kiểm thử đồng thời (đăng nhập sai song song, xuất kho / chấp thuận đề nghị song song) | Not Run | Chưa thực hiện trong vòng này |
| NR-03 | ZAP active scan | Blocked | Chờ phê duyệt |
| NR-04 | Strix / Shannon / Hercules | Blocked | Cần API key LLM + phê duyệt chi phí; Shannon khai thác thật |
| NR-05 | Kiểm tra trợ năng chi tiết (axe), điều hướng bàn phím | Not Run | Ngoài vòng 1 |

---

# Vòng 2 (14/10/2026) — đồng thời, thao tác giao diện, trợ năng, quét chủ động

## G. Kiểm thử đồng thời — `backend/bloodbank/tests/test_concurrency.py` (TransactionTestCase, PostgreSQL thật, nhiều luồng thả cùng lúc)

| ID | Kịch bản | Bất biến kiểm tra | Kết quả |
|---|---|---|---|
| CC-01 | 12 lần đăng nhập sai đồng thời | Chỉ 5 lần được kiểm tra mật khẩu; 7 lần bị khóa; mật khẩu đúng cũng bị chặn | **Fail trên code cũ (12/12 được kiểm tra)** → sửa → Pass |
| CC-02 | Tồn 10, 8 phiếu xuất 3 cùng lúc | Đúng 3 phiếu thành công, tồn còn 1, sổ kho liền mạch | Pass |
| CC-03 | Bấm đúp: 6 request cùng idempotency_key | Đúng 1 phiếu, các lần sau trả phiếu cũ | Pass |
| CC-04 | Xuất kho + điều chỉnh giảm xen kẽ cùng lúc | Không âm kho, sổ kho liền mạch | Pass |
| CC-05 | 2 bệnh viện xin cùng 5 đơn vị của 1 bên cấp, chấp thuận cùng lúc | 1 thành công, giữ chỗ = 5 ≤ tồn | Pass |
| CC-06 | 2 bên cấp chấp thuận cùng 1 yêu cầu cần 5 | Tổng cam kết = 5 | Pass |
| CC-07 | Bên nhận xác nhận + bên cấp báo thất bại cùng lúc | 1 kết quả cuối; tổng đơn vị 2 bên bảo toàn | Pass |
| CC-08 | Ghi nhận lượt hiến 4 lần cùng lúc cho 1 đơn | Đúng 1 lượt hiến | Pass |
| CC-09 | Kết quả xét nghiệm "đạt" 4 lần cùng lúc (khóa khác nhau) | Nhập kho đúng 1 lần | Pass |
| CC-10 | Hủy lượt hiến (trừ kho) và xuất kho cùng lúc trên cùng đơn vị | 1 thao tác thành công, không âm kho | Pass |
| CC-11 | 5 lần đăng ký cùng 1 đợt cùng lúc | Đúng 1 đơn | Pass |

## H. Thao tác giao diện — `playwright/ui_flows.py` (Chromium, trên ứng dụng QA thật)

| ID | Luồng | Kết quả |
|---|---|---|
| UI-01 | Đăng ký tài khoản: mật khẩu yếu bị chặn, tài khoản hợp lệ được tạo | Pass |
| UI-02 | Người dùng đăng ký hiến 1 đợt; không còn nút đăng ký lần 2 | Pass |
| UI-03 | "Tôi cần xin máu" từ trang chủ: form trống bị chặn, gửi hợp lệ nhận mã PR-… | Pass |
| UI-04 | Đăng nhập chỉ bằng bàn phím (Tab/Enter) + đăng xuất | Pass |
| UI-05 | Bệnh viện: check-in → ghi nhận lượt hiến → xét nghiệm đạt (nhập kho) → xuất vượt tồn bị chặn → xuất hợp lệ | Pass |
| UI-06 | Tạo đợt hiến: giờ kết thúc sai bị chặn; bấm bản đồ điền tọa độ; tạo thành công | Pass |
| UI-07 | Nhận xác minh → xác minh yêu cầu cần máu | Pass |
| UI-08 | Bên cấp: chấp thuận vượt mức bị chặn, chấp thuận hợp lệ | Pass |
| UI-09 | Quản trị: giá trị cấu hình sai bị chặn, lưu hợp lệ | Pass |
| UI-10 | Bản đồ công khai dưới CSP: danh sách, popup, lọc | Pass |
| UI-11 | Mobile 390px: mở menu, điều hướng | Pass |

Lần chạy đầu có 5 luồng Fail. Cả 5 đã được kiểm tra lại và là **lỗi kịch bản test**, không phải lỗi web:
- Selector chọn nhầm nút "Đăng xuất" đang ẩn trong menu.
- Kiểm tra URL trước khi trang chuyển xong (ảnh chụp cho thấy đăng nhập đã thành công).
- Selector liên kết chưa đúng với cấu trúc trang thật.

Đã sửa kịch bản và chạy lại: 11/11 Pass.

## I. Trợ năng — axe-core (WCAG 2 A/AA), 15 trang × 4 vai trò

| Lần | Kết quả |
|---|---|
| Trước khi sửa | 5 vi phạm: thiếu tên ghim bản đồ (serious) · ô email thiếu nhãn (critical) · tương phản chữ huy hiệu (serious) · bảng cuộn không dùng được bàn phím (serious) · nút chỉ có biểu tượng (critical) |
| Sau khi sửa | **0 vi phạm** |

## J. Hiển thị sau mọi thay đổi (CSP, JS, CSS)
`ui_smoke.py`: 80/80 lượt trang không có vấn đề thật (CSP không chặn nhầm tài nguyên nào).
