# 01 · Danh mục hệ thống

Sinh tự động từ URL resolver của Django + `bloodbank/access.py` (`scripts/build_inventory.py`), không dựa vào menu giao diện.

## Kiến trúc

- **Backend:** Django 5.2.7 (render HTML phía server, không có REST API riêng; 2 endpoint JSON: `/ban-do/du-lieu/`, `/api/chatbot/`).
- **CSDL:** PostgreSQL 16, 19 bảng nghiệp vụ + trigger (sổ kho chỉ-thêm, kiểm tra ràng buộc).
- **Phân quyền 3 lớp:** (1) `ScreenAccessMiddleware` đối chiếu mọi route với bảng `access.SCREENS` (route chưa khai báo bị chặn), (2) decorator `staff_required/member_required/admin_required` + phân công bệnh viện lấy từ phiên, (3) lọc theo `hospital`/`donor` trong từng truy vấn.
- **Giao dịch:** `business_transaction()` + `select_for_update` + khóa idempotency cho phiếu kho; khóa lạc quan `version` cho cấu hình tồn.
- **Tác vụ định kỳ:** container `scheduler` (`run_jobs --loop`): hết hạn yêu cầu liên viện, hủy đề nghị quá hạn, nhắc yêu cầu cần máu, nhắc hiến lại.
- **Tích hợp ngoài:** gửi email (console ở dev), Google Fonts, ô bản đồ OpenStreetMap. Không có cổng thanh toán / API bên thứ ba.

## Vai trò

| Vai trò | Cổng đăng nhập | Phạm vi |
|---|---|---|
| Khách | — | Trang công khai, đăng ký, khôi phục mật khẩu |
| Người dùng (member) | `/dang-nhap/` | Đăng ký hiến, lịch sử, gửi yêu cầu cần máu (của chính mình) |
| Nhân viên bệnh viện (hospital) | `/benh-vien/dang-nhap/` | Dữ liệu của bệnh viện đang được phân công (chọn trong phiên) |
| Quản trị (admin) | `/quan-tri/dang-nhap/` | Người dùng, bệnh viện, danh mục, cấu hình, nhật ký toàn hệ thống |

## Routes (80)

| Module | Chức năng (màn hình) | Route | Phương thức | Vai trò | Lớp kiểm soát | Rủi ro |
|---|---|---|---|---|---|---|
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/dang-nhap/` | GET/POST | public | middleware | Thấp |
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/benh-vien/dang-nhap/` | GET/POST | public | middleware | Thấp |
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/quan-tri/dang-nhap/` | GET/POST | public | middleware | Thấp |
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/dang-ky/` | GET/POST | public | middleware | Thấp |
| Xác thực | SCR-16 Đăng xuất | `/dang-xuat/` | POST | member, hospital, admin | middleware | Cao (dữ liệu y tế, kho) |
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/quen-mat-khau/` | GET/POST | public | middleware | Thấp |
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/dat-lai-mat-khau/<str:token>/` | GET/POST | public | middleware | Thấp |
| Xác thực | SCR-06 Đăng nhập, đăng ký, khôi phục mật khẩu | `/xac-thuc-email/<str:token>/` | GET | public | middleware | Thấp |
| Xác thực | SCR-07 Hồ sơ cá nhân | `/xac-thuc-email-gui-lai/` | POST | member | middleware | Trung bình (dữ liệu cá nhân) |
| Công khai | SCR-01 Trang chủ & chatbot | `/` | GET | public | middleware | Thấp |
| Đợt hiến / điểm hiến | SCR-02 Danh sách đợt hiến | `/dot-hien/` | GET | public | middleware | Thấp |
| Đợt hiến / điểm hiến | SCR-03 Chi tiết đợt hiến (đăng ký hiến: chỉ Người dùng) | `/dot-hien/<int:pk>/` | GET/POST | public | middleware | Thấp |
| Công khai | SCR-04 Bản đồ điểm hiến | `/ban-do/` | GET | public | middleware | Thấp |
| Công khai | SCR-04 Bản đồ điểm hiến | `/ban-do/du-lieu/` | GET | public | middleware | Thấp |
| Công khai | SCR-01 Trang chủ & chatbot | `/api/chatbot/` | POST | public | middleware | Thấp |
| Tài khoản | SCR-07 Hồ sơ cá nhân | `/tai-khoan/` | GET/POST | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Tài khoản | SCR-08 Đơn đăng ký hiến của tôi | `/tai-khoan/don-dang-ky/` | GET | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Tài khoản | SCR-08 Đơn đăng ký hiến của tôi | `/tai-khoan/don-dang-ky/<int:pk>/huy/` | POST | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Tài khoản | SCR-08 Đơn đăng ký hiến của tôi | `/tai-khoan/don-dang-ky/<int:pk>/dang-ky-lai/` | POST | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Đợt hiến / điểm hiến | SCR-09 Lịch sử hiến máu | `/tai-khoan/lich-su-hien/` | GET | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Đợt hiến / điểm hiến | SCR-09 Lịch sử hiến máu | `/tai-khoan/lich-su-hien/<int:pk>/` | GET | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Yêu cầu cần máu | SCR-11 Gửi yêu cầu cần máu | `/can-mau/gui-yeu-cau/` | GET/POST | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Yêu cầu cần máu | SCR-12 Yêu cầu cần máu của tôi | `/tai-khoan/yeu-cau-can-mau/` | GET | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Yêu cầu cần máu | SCR-12 Yêu cầu cần máu của tôi | `/tai-khoan/yeu-cau-can-mau/<int:pk>/` | GET | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Yêu cầu cần máu | SCR-12 Yêu cầu cần máu của tôi | `/tai-khoan/yeu-cau-can-mau/<int:pk>/huy/` | POST | member | middleware + member_required | Trung bình (dữ liệu cá nhân) |
| Thông báo | SCR-14 Thông báo | `/thong-bao/` | GET | member, hospital, admin | middleware + signed_in_required | Cao (dữ liệu y tế, kho) |
| Thông báo | SCR-14 Thông báo | `/thong-bao/da-doc/` | POST | member, hospital, admin | middleware + signed_in_required | Cao (dữ liệu y tế, kho) |
| Tài khoản | SCR-15 Tài khoản công tác (hồ sơ, đổi mật khẩu) | `/tai-khoan-cong-tac/` | GET/POST | hospital, admin | middleware + signed_in_required | Cao (dữ liệu y tế, kho) |
| Bệnh viện | SCR-20 Tổng quan bệnh viện | `/benh-vien/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Bệnh viện | SCR-20 Tổng quan bệnh viện | `/benh-vien/chon/` | POST | hospital | middleware | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-21 Quản lý đợt hiến | `/benh-vien/dot-hien/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-21 Quản lý đợt hiến | `/benh-vien/dot-hien/tao/` | GET/POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-21 Quản lý đợt hiến | `/benh-vien/dot-hien/<int:pk>/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-21 Quản lý đợt hiến | `/benh-vien/dot-hien/<int:pk>/sua/` | GET/POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-21 Quản lý đợt hiến | `/benh-vien/dot-hien/<int:pk>/trang-thai/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-24 Điểm hiến (check-in, ghi nhận) | `/benh-vien/dot-hien/<int:pk>/diem-hien/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-24 Điểm hiến (check-in, ghi nhận) | `/benh-vien/dot-hien/<int:pk>/tai-cho/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-21 Quản lý đợt hiến | `/benh-vien/don/<int:pk>/xu-ly/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-24 Điểm hiến (check-in, ghi nhận) | `/benh-vien/don/<int:pk>/diem-hien/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-24 Điểm hiến (check-in, ghi nhận) | `/benh-vien/don/<int:pk>/ghi-nhan/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-25 Lượt hiến (xem, hủy hiệu lực, sửa) | `/benh-vien/luot-hien/<int:pk>/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-25 Lượt hiến (xem, hủy hiệu lực, sửa) | `/benh-vien/luot-hien/<int:pk>/quan-ly/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-26 Tra cứu người hiến | `/benh-vien/nguoi-hien/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Đợt hiến / điểm hiến | SCR-27 Báo cáo tiếp nhận | `/benh-vien/bao-cao-tiep-nhan/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-29 Chờ xét nghiệm → nhập kho | `/benh-vien/cho-xet-nghiem/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-29 Chờ xét nghiệm → nhập kho | `/benh-vien/luot-hien/<int:pk>/xet-nghiem/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-30 Tồn kho | `/benh-vien/kho/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-30 Tồn kho | `/benh-vien/kho/<int:pk>/cau-hinh/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-30 Tồn kho | `/benh-vien/kho/muc-ton/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-31 Phiếu nhập / xuất / điều chỉnh | `/benh-vien/kho/phieu/<slug:kind>/` | GET/POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Kho máu | SCR-32 Lịch sử biến động kho | `/benh-vien/kho/lich-su/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Nhu cầu & kêu gọi | SCR-33 Nhu cầu & thiếu hụt | `/benh-vien/nhu-cau/` | GET/POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Nhu cầu & kêu gọi | SCR-33 Nhu cầu & thiếu hụt | `/benh-vien/nhu-cau/<int:pk>/sua/` | GET/POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Nhu cầu & kêu gọi | SCR-33 Nhu cầu & thiếu hụt | `/benh-vien/nhu-cau/<int:pk>/dong/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Nhu cầu & kêu gọi | SCR-33 Nhu cầu & thiếu hụt | `/benh-vien/nhu-cau/keu-goi/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-34 Tìm nguồn liên viện | `/benh-vien/tim-nguon/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-35 Yêu cầu hỗ trợ đã gửi | `/benh-vien/yeu-cau-ho-tro/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-35 Yêu cầu hỗ trợ đã gửi | `/benh-vien/yeu-cau-ho-tro/tao/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-35 Yêu cầu hỗ trợ đã gửi | `/benh-vien/yeu-cau-ho-tro/<int:pk>/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-35 Yêu cầu hỗ trợ đã gửi | `/benh-vien/yeu-cau-ho-tro/<int:pk>/xu-ly/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-35 Yêu cầu hỗ trợ đã gửi | `/benh-vien/de-nghi/<int:pk>/yeu-cau/` | GET | hospital | middleware | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-35 Yêu cầu hỗ trợ đã gửi | `/benh-vien/de-nghi/<int:pk>/mo/` | GET | hospital | middleware | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-36 Đề nghị đến bệnh viện | `/benh-vien/de-nghi-den/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-36 Đề nghị đến bệnh viện | `/benh-vien/de-nghi-den/<int:pk>/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Điều phối liên viện | SCR-36 Đề nghị đến bệnh viện | `/benh-vien/de-nghi-den/<int:pk>/xu-ly/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Yêu cầu cần máu | SCR-37 Xử lý yêu cầu cần máu | `/benh-vien/yeu-cau-can-mau/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Yêu cầu cần máu | SCR-37 Xử lý yêu cầu cần máu | `/benh-vien/yeu-cau-can-mau/<int:pk>/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Yêu cầu cần máu | SCR-37 Xử lý yêu cầu cần máu | `/benh-vien/yeu-cau-can-mau/<int:pk>/xu-ly/` | POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Bệnh viện | SCR-39 Thông tin bệnh viện | `/benh-vien/thong-tin/` | GET/POST | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Bệnh viện | SCR-38 Nhân viên bệnh viện (xem) | `/benh-vien/nhan-vien/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Bệnh viện | SCR-40 Nhật ký bệnh viện | `/benh-vien/nhat-ky/` | GET | hospital | middleware + staff_required | Cao (dữ liệu y tế, kho) |
| Quản trị | SCR-52 Danh mục chế phẩm (bệnh viện xem, quản trị sửa) | `/danh-muc/` | GET/POST | hospital, admin | middleware | Cao (dữ liệu y tế, kho) |
| Quản trị | SCR-54 Thống kê toàn hệ thống | `/quan-tri/thong-ke/` | GET | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-50 Người dùng | `/quan-tri/nguoi-dung/` | GET/POST | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-51 Bệnh viện & tài khoản nhân viên | `/quan-tri/benh-vien/` | GET | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-51 Bệnh viện & tài khoản nhân viên | `/quan-tri/benh-vien/tao/` | GET/POST | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-51 Bệnh viện & tài khoản nhân viên | `/quan-tri/benh-vien/<int:pk>/` | GET/POST | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-53 Nhật ký hệ thống | `/quan-tri/nhat-ky/` | GET | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-55 Cấu hình hệ thống | `/quan-tri/cau-hinh/` | GET/POST | admin | middleware + admin_required | Cao (toàn hệ thống) |
| Quản trị | SCR-56 Phân quyền màn hình | `/quan-tri/phan-quyen/` | GET | admin | middleware + admin_required | Cao (toàn hệ thống) |

## Điểm rủi ro chính (đầu vào cho test case)

| Khu vực | Quy tắc nghiệp vụ | Rủi ro |
|---|---|---|
| Kho máu | Sổ kho chỉ-thêm; tồn ≥ giữ chỗ ≥ 0; idempotency_key | Âm kho, ghi trùng, lệch kho khi hủy chứng từ nguồn |
| Lượt hiến ↔ kho | Chỉ nhập kho sau xét nghiệm đạt, 1 lần / lượt | Nhập vượt, không đảo khi hủy lượt hiến |
| Điều phối liên viện | Tổng cam kết ≤ số cần; giữ chỗ khi chấp thuận | Vượt số cần, giữ chỗ quá tồn khi đồng thời |
| Đợt hiến / đơn | Máy trạng thái đợt + đơn; lượt hiến trong khung giờ đợt | Trạng thái treo, dữ liệu lệch khi sửa/hủy đợt |
| Yêu cầu cần máu | Chỉ bệnh viện điều trị xử lý; người xác minh ≠ người gửi | IDOR, lộ dữ liệu bệnh nhân |
| Xác thực | Khóa sau 5 lần sai; token đặt lại 1 lần | Liệt kê tài khoản, vượt khóa, spam email |
