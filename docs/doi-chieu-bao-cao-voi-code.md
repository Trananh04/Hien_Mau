# Đối chiếu báo cáo đồ án với code

Tài liệu được đối chiếu: bản báo cáo "Xây dựng nền tảng website ngân hàng máu và điều phối máu nhân đạo tích hợp AI".
Code được đối chiếu: thư mục `backend/` (Django) của dự án, nhánh `trien-khai-that`.

Mỗi mục ghi: **Báo cáo đang viết** → **Code thực tế** → **Nên sửa thành**.
Mức độ: 🔴 sai so với code · 🟠 thiếu chức năng có trong code · 🟡 lỗi trình bày.

---

## 1. Lỗi trình bày chung

| # | Mức | Vị trí | Vấn đề | Nên sửa |
|---|---|---|---|---|
| 1.1 | 🟡 | Hai trang bìa | "điều phối **máy** nhân đạo" | "điều phối **máu** nhân đạo" |
| 1.2 | 🟡 | Chương 3 | "3.1. Thiết kế cơ sở dữ liệu" và "3.2. Thiết kế cơ sở dữ liệu" trùng tên; các mục AI 3.2.1–3.2.3 lại nằm dưới phần cơ sở dữ liệu | 3.1.1 ERD logic · 3.1.2 ERD vật lý · **3.1.3 Mô tả các bảng** (các ảnh bảng) · **3.2 Thiết kế tích hợp AI** (3.2.1–3.2.3) · 3.3 Giao diện |
| 1.3 | 🔴 | Use case "Quản lý tồn kho chế phẩm" | Phần *Các yêu cầu đặc biệt*, *Tiền điều kiện*, *Hậu điều kiện* bị chép nhầm từ use case "Xem lịch sử hiến máu" ("Chỉ tính bản ghi đã xác nhận…", "Lịch sử cá nhân được hiển thị…") | Xem mục 4.1 bên dưới |
| 1.4 | 🟡 | Use case "Tra cứu đợt hiến máu" | Luồng rẽ nhánh xếp 4a, 5a rồi mới 2a | Xếp theo thứ tự bước: 2a, 4a, 5a |
| 1.5 | 🟡 | Use case "Nhận thông báo" | Thứ tự 3a, 5a, 1a, 5b | 1a, 3a, 5a, 5b |

---

## 2. Tài khoản và đăng nhập

### 2.1 🔴 Use case Đăng ký tài khoản — thiếu bước xác thực email bằng OTP
- **Báo cáo:** khách nhập thông tin → hệ thống tạo tài khoản và thông báo thành công.
- **Code** (`accounts/views.py: register_view`, `accounts/services.py: verify_email_code`):
  - Đăng ký xong hệ thống **đăng nhập luôn** và gửi **mã OTP 6 số** tới email.
  - Người dùng **bắt buộc nhập mã** mới dùng được hệ thống (middleware `EmailVerifiedMiddleware` chặn và đưa về trang nhập mã).
  - Nhập sai quá số lần cấu hình (`email_otp_max_attempts`) thì mã bị hủy, phải bấm gửi mã mới.
  - Biểu mẫu có chọn **Tỉnh/thành → Phường/Xã** (danh sách phường/xã tải theo tỉnh).
- **Nên sửa:** thêm bước 5 "Hệ thống gửi mã OTP tới email; người dùng nhập mã để kích hoạt", thêm luồng rẽ nhánh "Nhập sai mã / mã hết hạn / gửi lại mã". Hậu điều kiện: tài khoản được tạo ở trạng thái **chưa xác thực email** cho tới khi nhập đúng mã.

### 2.2 🔴 Use case Đăng nhập — code có 3 cổng đăng nhập riêng
- **Báo cáo:** một trang đăng nhập, đăng nhập xong "chuyển đến trang phù hợp với vai trò".
- **Code** (`accounts/views.py: login_view, hospital_login_view, admin_login_view`):
  - Có **3 cổng**: Người dùng, Bệnh viện (2 tab trên cùng một trang), và cổng Quản trị riêng (không hiện liên kết công khai).
  - Mật khẩu đúng nhưng **sai cổng** → từ chối, không tạo phiên (`ERR-AUTH-PORTAL`), gợi ý cổng đúng (trừ tài khoản quản trị).
  - Tài khoản bệnh viện mà **bệnh viện chưa được duyệt** → không đăng nhập được (`ERR-AUTH-HOSPITAL-PENDING`).
  - Sai mật khẩu quá `login_max_failed_attempts` lần → khóa tạm `login_lock_minutes` phút.
- **Nên sửa:** bước 1 ghi "Tác nhân chọn cổng đăng nhập (Người dùng / Bệnh viện / Quản trị)"; thêm rẽ nhánh 3d "Sai cổng", 3e "Bệnh viện chưa được duyệt", 3f "Nhập sai quá số lần → khóa tạm". Bỏ 3c "Không kết nối được dịch vụ xác thực" (hệ thống tự xác thực, không có dịch vụ ngoài).

### 2.3 🟠 Thiếu use case: Bệnh viện đăng ký tham gia hệ thống
- **Code** (`services/hospital_signup.py`): bệnh viện **tự đăng ký** (thông tin bệnh viện + tài khoản quản lý) → trạng thái **Chờ duyệt** → **Quản trị viên duyệt hoặc từ chối kèm lý do** → sau khi duyệt, Quản lý bệnh viện tự cấp tài khoản cho nhân viên.
- Bảng `hospitals` có trạng thái `pending / active / inactive / rejected` và cột `reject_reason` — báo cáo chưa giải thích.
- **Nên thêm:** use case "Đăng ký bệnh viện" (tác nhân: khách) và bổ sung vào use case "Quản lý bệnh viện" của quản trị viên luồng **Duyệt / Từ chối bệnh viện đăng ký**.

### 2.4 🟠 Chức năng tài khoản có trong code nhưng báo cáo chưa nêu
- Đổi mật khẩu; đặt lại mật khẩu qua liên kết email (báo cáo chỉ nhắc "hỗ trợ quên mật khẩu" trong yêu cầu đặc biệt).
- Tắt nhận email kêu gọi/nhắc hiến (liên kết hủy đăng ký nhận email, cột `users.email_reminders`).
- Đồng ý điều khoản khi đăng ký (`users.terms_accepted_at`).

---

## 3. Hiến máu

### 3.1 🟠 Use case Đăng ký hiến máu / Quản lý đơn đăng ký — thiếu trạng thái và luồng
- **Code** (`models/campaigns.py: Registration.Status`): đơn có 8 trạng thái: Chờ duyệt, Đã duyệt, Bị từ chối, Đã hủy, Đã check-in, Đã hiến, **Có mặt nhưng không hiến**, **Vắng mặt**.
- Có **đăng ký tại điểm hiến** (walk-in, `registrations.source = walk_in`) do nhân viên tạo cho người đến trực tiếp.
- Người dùng **hủy đơn** và **đăng ký lại** sau khi đã hủy (`member.cancel_registration`, `member.reregister`).
- Mã đơn dạng **DK-000123** (đúng với báo cáo "hiển thị mã đơn").
- **Nên sửa:** trong "Quản lý đơn đăng ký" liệt kê đủ các trạng thái trên; thêm luồng "Check-in tại điểm hiến" và "Đăng ký tại chỗ". Trong "Đăng ký hiến máu" thêm điều kiện **tài khoản đã xác thực email**.

### 3.2 🔴 Use case Ghi nhận kết quả hiến máu — sai về nhập kho và thiếu bước xét nghiệm
- **Báo cáo:** "Ghi nhận hiến và nhập kho chế phẩm là nghiệp vụ riêng; không tự suy ra sản lượng chế phẩm từ thể tích hiến. Không bổ sung bước khám sàng lọc."
- **Code** (`services/donations.py`, `services/lab.py`):
  - Ghi nhận lượt hiến → lượt hiến ở trạng thái **Chờ xét nghiệm** (`donations.lab_status = pending`), **chưa nhập kho**.
  - Nhân viên nhập **kết quả xét nghiệm**: *Đạt* → chọn nhóm máu theo xét nghiệm (`lab_blood_group`) và hệ thống **tự tính chế phẩm thu được** theo quy tắc điều chế (`yield_plan`: máu toàn phần → khối hồng cầu + huyết tương, theo cỡ túi 250/350/450 ml; hoặc giữ nguyên máu toàn phần; hoặc nhân viên chọn tay) rồi **nhập kho gắn với lượt hiến**; *Không đạt* → bắt buộc ghi chú, không nhập kho.
  - Có **cảnh báo (không chặn)** khi lần hiến trước chưa đủ khoảng cách tối thiểu (`interval_warning`) và khi thể tích ngoài ngưỡng (`volume_warning`, phải xác nhận).
  - Hủy hiệu lực lượt hiến đã nhập kho → hệ thống **tự ghi phiếu điều chỉnh trừ** đúng số đã nhập.
- **Nên sửa:** bỏ câu "không tự suy ra sản lượng chế phẩm"; thêm **use case mới "Ghi nhận kết quả xét nghiệm và nhập kho"** (màn "Chờ xét nghiệm"). "Không khám sàng lọc" vẫn đúng — hệ thống không làm khám sàng lọc, chỉ ghi kết quả xét nghiệm máu sau khi hiến.

### 3.3 🟡 Use case Thống kê và báo cáo
- **Code:** có báo cáo tiếp nhận theo khoảng ngày, **theo tháng và theo đợt hiến** (`donation_report`), tổng quan bệnh viện; **không có chức năng xuất file** (Excel/PDF).
- **Nên sửa:** bỏ bước 5 "chọn xuất báo cáo" và luồng 5a, hoặc ghi rõ là hướng phát triển.

---

## 4. Kho, nhu cầu, liên viện, yêu cầu cần máu

### 4.1 🔴 Use case Quản lý tồn kho chế phẩm — sửa phần chép nhầm
Thay 3 ô bị chép nhầm bằng nội dung đúng với code (`services/inventory.py`):
- **Các yêu cầu đặc biệt:** Khả dụng = tồn thực tế − giữ chỗ; xuất và điều chỉnh giảm chỉ trên phần khả dụng. Mỗi biến động ghi một dòng sổ kho (`stock_txns`) với số trước / biến động / số sau, người thực hiện. Khóa chống gửi lặp (`idempotency_key`) và khóa phiên bản (`stocks.version`) khi sửa mức tối thiểu / chia sẻ. Điều chỉnh bắt buộc lý do: hết hạn, không đạt chất lượng, hư hỏng, kiểm kê, nhập sai dữ liệu, hao hụt điều chuyển, khác.
- **Tiền điều kiện:** Nhân viên bệnh viện đã đăng nhập, phân công còn hiệu lực.
- **Hậu điều kiện:** Thành công: dòng tồn và sổ kho được cập nhật trong cùng giao dịch. Thất bại: tồn kho giữ nguyên.

### 4.2 🟡 Use case Quản lý nhu cầu chế phẩm — bảng `demands` không có trong phần thiết kế CSDL
- Use case này (và ca khẩn cấp, dự báo) dùng bảng **`demands`** (trạng thái: Đang cần / Đã đáp ứng / Đã hủy; có cờ `is_emergency`). Bảng này **không có** trong 19 bảng ở mục 3.1/3.2.
- **Nên sửa:** thêm bảng `demands` vào ERD và mô tả bảng; hoặc ghi chú rằng ERD chỉ vẽ bảng chính. Tương tự `audit_logs` (dùng cho "Tra cứu nhật ký") và `system_settings` (dùng cho "Cấu hình hệ thống").
- Code tính **thiếu hụt = MAX(0, tổng nhu cầu đang cần cùng nhóm máu + quy cách − khả dụng)** (`inventory.shortages`) — nên đưa công thức vào báo cáo.

### 4.3 🟠 Thiếu use case: Xử lý ca khẩn cấp
- **Code** (`services/emergency.py`, nút "Khẩn cấp"): tạo ca cần máu trong vài giờ, hệ thống xử lý theo 3 bước: (1) xuất từ **kho mình** phần khả dụng; (2) phần thiếu **tự chia cho bệnh viện gần còn dư** và gửi đề nghị khẩn (quá `offer_response_ttl_urgent_minutes` không phản hồi thì tự hủy, có nút "xin thêm bệnh viện"); (3) chỉ khi vẫn thiếu mới **kêu gọi người hiến khẩn**.
- **Nên thêm** use case "Xử lý ca khẩn cấp" cho nhân viên bệnh viện.

### 4.4 🔴 Use case Quản lý hỗ trợ liên viện — chiều gửi đề nghị bị ngược
- **Báo cáo:** bệnh viện cần hỗ trợ đăng yêu cầu → hiển thị cho các bệnh viện → "bệnh viện cung cấp **gửi đề nghị** với số lượng có thể hỗ trợ".
- **Code** (`services/transfers.py`):
  1. Bên cần **tra cứu nguồn** (`search_sources`): xếp **gần trước**, cùng khoảng cách thì nhiều hàng trước; hệ thống **gợi ý chia số lượng** cho các nguồn (`suggest_allocation`).
  2. Bên cần **tạo yêu cầu và mời trực tiếp** các bệnh viện cung cấp (tạo đề nghị trạng thái *Chờ phản hồi*); có thể mời thêm sau.
  3. Bên cung cấp **chấp thuận** với số lượng q ≤ MIN(khả dụng, còn thiếu) → **giữ chỗ**; hoặc **từ chối** (bắt buộc lý do).
  4. Bên cung cấp **xác nhận xuất** → trừ tồn, giải phóng giữ chỗ → *Đang vận chuyển*.
  5. Bên cần **xác nhận nhận** số thực nhận r ≤ q; phần chênh lệch có thể **trả về bên cung cấp** (`transfer_return`).
  6. Bên cung cấp có thể **báo giao nhận thất bại** kèm lý do và số quay về kho.
  7. Yêu cầu tự tính trạng thái: Đang mở → Đang xử lý → **Đáp ứng một phần** → Đã đáp ứng đủ; quá hạn `needed_by` → **Hết hạn** (tác vụ định kỳ tự chạy, giải phóng giữ chỗ).
- **Nên sửa:** viết lại luồng cơ bản theo 7 bước trên. Sửa luồng 6a: code **không** có bước "chờ đối soát" — bên nhận ghi số thực nhận, đề nghị hoàn tất với số đó, yêu cầu chuyển *Đáp ứng một phần* nếu còn thiếu. Sửa yêu cầu đặc biệt "không tự hủy điều chuyển đã xuất để hoàn kho" thành "hàng đã xuất chỉ quay về kho bên cấp qua thao tác báo thất bại / trả lại có ghi sổ".

### 4.5 🔴 Use case Gửi yêu cầu hỗ trợ máu và Xử lý yêu cầu người cần máu
- **Gửi yêu cầu** (`services/patients.py: submit`, `forms.PatientRequestForm`):
  - Loại chế phẩm là **bắt buộc** (báo cáo ghi "loại chế phẩm nếu biết"); nhóm máu, bệnh viện, số điện thoại (≥ 11 ký tự số) bắt buộc; tên bệnh nhân, thời điểm cần không bắt buộc.
  - Bắt buộc tick **đồng ý chia sẻ thông tin với bệnh viện điều trị** (`consent_at`).
  - Chỉ **tài khoản Người dùng** được gửi (tài khoản bệnh viện / quản trị bị từ chối).
  - Người gửi **được tự hủy** khi yêu cầu còn ở trạng thái Đã gửi / Đang xác minh / Đã xác minh — báo cáo chưa có luồng này.
- **Xử lý yêu cầu:** trạng thái: Đã gửi → (Đang xác minh) → Đã xác minh / Bị từ chối → Đang xử lý → Đã hoàn tất / Đã hủy. **Người xác minh phải khác người gửi**. Xuất kho, tạo yêu cầu liên viện hoặc liên kết đợt hiến đều tự chuyển sang "Đang xử lý". Mỗi lần nhân viên xem thông tin nhạy cảm được ghi nhật ký (`log_sensitive_view`).
- **Nên sửa:** cập nhật biểu mẫu, thêm điều kiện đồng ý, thêm luồng "Người gửi hủy yêu cầu", ghi rõ ràng buộc "người xác minh ≠ người gửi".

### 4.6 🟡 Use case Quản lý nhân viên bệnh viện
- **Báo cáo:** "thêm phân công, **sửa vai trò** hoặc ngừng hiệu lực".
- **Code** (`views/hospital.py: hospital_staff`, `services/admin.py: assign_staff`): Quản lý bệnh viện **cấp tài khoản nhân viên mới** (theo email; email chưa có thì tạo tài khoản), **thu hồi** và **kích hoạt lại**. **Không có chức năng đổi vai trò** Nhân viên ↔ Quản lý. Quản lý không tự thu hồi mình và không thao tác trên Quản lý khác. Tài khoản Người dùng / Quản trị không được dùng làm tài khoản bệnh viện.
- **Nên sửa:** bỏ "sửa vai trò", thêm các ràng buộc trên.

---

## 5. Quản trị viên

### 5.1 🟡 Use case Quản lý tài khoản người dùng
- **Code** (`services/admin.py`): khóa / mở khóa (`set_user_status`); đổi vai trò **chỉ giữa Người dùng ↔ Quản trị hệ thống**; tài khoản nhân viên bệnh viện quản lý ở màn Bệnh viện. Nên ghi rõ.

### 5.2 🟠 Chức năng quản trị có trong code nhưng báo cáo chưa có use case
| Màn hình (URL) | Chức năng |
|---|---|
| `quan-tri/canh-bao/` | Cảnh báo toàn hệ thống: việc khẩn cần đôn đốc các bệnh viện |
| `quan-tri/cau-hinh/` | **Cấu hình hệ thống** (bảng `system_settings`): ngưỡng thể tích, khoảng cách giữa 2 lần hiến, số lần đăng nhập sai, thời gian chờ đề nghị, bật/tắt AI dự báo… |
| `quan-tri/phan-quyen/` | Xem bảng phân quyền màn hình theo vai trò (chỉ đọc) |
| `quan-tri/tro-ly/` | **Theo dõi trợ lý AI**: số câu hỏi theo ý định / chế độ, lượt gọi AI hôm nay, trạng thái máy chủ mô hình |
| `quan-tri/du-bao-ai/` | **Theo dõi dự báo AI**: sai số thực tế theo tuần, phiên bản mô hình, kích hoạt phiên bản, yêu cầu huấn luyện lại |
| `quan-tri/benh-vien/` | Duyệt / từ chối bệnh viện đăng ký (xem 2.3), gắn nhân viên vào bệnh viện |

---

## 6. Ba chức năng AI — use case chương 2 và nội dung cần viết cho mục 3.2

> Mục 3.2.1–3.2.3 trong báo cáo đang để trống. Dưới đây là phần sai trong use case chương 2 và **các ý đúng với code** để viết vào mục 3.2.

### 6.1 Gợi ý người hiến máu phù hợp

**Sai trong use case chương 2:**
- 🔴 *Đầu vào:* báo cáo ghi "chọn nhu cầu hoặc nhập nhóm máu, loại hiến, khu vực và thời điểm cần". Code: mở từ **dòng thiếu hụt** của một **nhóm máu**, chọn **chế độ** (*Thiếu kho* hoặc *Khẩn*) và **bán kính** 10 / 25 / 50 km hoặc cả tỉnh. Không có ô loại hiến / thời điểm cần.
- 🔴 *Bước 5:* "xem chi tiết và lựa chọn người cần liên hệ". Code: nhân viên **chỉ thấy mã ẩn danh** (6 ký tự, HMAC theo bệnh viện) + đặc điểm, **không thấy tên, số điện thoại**. Nhân viên chọn tối đa **50 người** và bấm gửi → **hệ thống gửi lời kêu gọi** (thông báo + email) kèm đợt hiến đang mở gần nhất (chế độ khẩn: mời đến thẳng bệnh viện trong ngày).
- 🟡 *Luồng 4a "Bộ phận xếp hạng AI lỗi":* (đã cập nhật code) xếp hạng AI giờ là **mô hình học máy dự đoán khả năng nhận lời** (`services/donor_ml/`). Khi AI tắt, chưa có mô hình hoặc mô hình không qua chốt chặn, danh sách **tự xếp theo chấm điểm luật**, không báo lỗi. Nên sửa 4a thành: "AI chưa sẵn sàng: hệ thống xếp theo chấm điểm luật và ghi rõ cách xếp".
- 🟡 *Yêu cầu đặc biệt:* "không tự gửi lời mời" — đúng là chỉ gửi khi nhân viên bấm gửi; nhưng khi gửi, máy chủ **tính lại danh sách** và chỉ gửi tới mã còn đủ điều kiện (tránh mời người vừa hiến / vừa được bệnh viện khác mời).

**Nội dung đúng để viết 3.2.3.1:** đã có tài liệu đầy đủ ở **[ai-goi-y-nguoi-hien.md](ai-goi-y-nguoi-hien.md)** (kiến trúc 2 tầng luật → AI, đặc trưng, dữ liệu, so sánh 3 cách, chốt chặn, kết quả, vận hành). Phần dưới là tầng **luật** (tầng 1, và là mốc so sánh của AI) (`services/donor_match.py`, `services/callout.py`):
1. *Lọc cứng:* tài khoản Người dùng đang hoạt động, cùng tỉnh/thành; nhóm máu khớp (ưu tiên nhóm máu **đã xét nghiệm**, chưa có thì nhóm tự khai); trong độ tuổi hiến; **đủ thời gian nghỉ theo loại lần hiến trước** (toàn phần / thành phần); không nhận lời kêu gọi nào trong N ngày gần đây (khẩn: thời gian ngắn hơn); chưa vượt số lời kêu gọi tối đa trong 90 ngày; nằm trong bán kính nếu có chọn.
2. *Chấm điểm 0–100 kèm lý do:* 7 tiêu chí có trọng số khác nhau theo chế độ:

   | Tiêu chí | Thiếu kho | Khẩn |
   |---|---|---|
   | Gần (quãng đường đi thật, Goong Distance Matrix; lỗi thì đường chim bay) | 20 | 40 |
   | Nhóm máu đã xét nghiệm | 15 | 15 |
   | Kinh nghiệm hiến (số lần đã hiến, tối đa tính 5 lần) | 10 | 5 |
   | Đến đúng hẹn (tỷ lệ có mặt khi đã đăng ký) | 15 | 10 |
   | Từng nhận lời kêu gọi (tỷ lệ hưởng ứng của chính người đó) | 15 | 15 |
   | Từng hiến tại bệnh viện này | 10 | 5 |
   | Ít bị kêu gọi trong 90 ngày (chia đều lượt gọi) | 15 | 10 |

   Mức: **cao** ≥ 70, **trung bình** ≥ 45, còn lại **thấp**. Bằng điểm thì người **ít bị kêu gọi gần đây** xếp trước (chia đều lượt gọi).
3. *Số người nên mời* = ⌈số đơn vị thiếu ÷ tỷ lệ hưởng ứng của bệnh viện⌉, trong khoảng 1–50 (`suggested_count`). Khi dùng AI: ít nhất k người đầu sao cho tổng khả năng nhận lời ≥ số đơn vị thiếu.
4. *Gửi lời kêu gọi:* lưu bảng `donor_callouts`, gửi `notifications` (trong ứng dụng + email), ghi `audit_logs`.
5. *Đo hiệu quả:* tỷ lệ hưởng ứng = trong N ngày sau lời mời, người được mời đăng ký đợt hiến hoặc hiến tại bệnh viện đó (`response_stats`).

> Cách gọi trong báo cáo: "**dự đoán khả năng nhận lời bằng học máy (hồi quy logistic / XGBoost), xếp hạng trên tập ứng viên đã lọc bằng luật**". Ghi rõ kết quả hiện tại là trên **dữ liệu mô phỏng**.

### 6.2 Dự báo nhu cầu và cảnh báo thiếu máu

**Sai trong use case chương 2:**
- 🔴 *Bước 1:* "chọn nhóm máu, chế phẩm và kỳ dự báo". Code: **không có ô chọn**; kỳ dự báo **cố định 14 ngày**; hệ thống hiển thị sẵn mọi dòng **nhóm máu × quy cách** của bệnh viện ở trang Tổng quan và trang Nhu cầu.
- 🔴 *Bước 2–3:* dự báo **không chạy khi mở trang**; tác vụ định kỳ dự báo **mỗi đêm một lần** (lịch sử đến hết hôm qua), lưu vào bảng `forecast_snapshots`; trang chỉ đọc kết quả.
- 🟡 *Luồng 3a:* khi AI tắt / thiếu dữ liệu / AI kém, hệ thống **tự dùng trung bình 28 ngày** và ghi rõ phương pháp (`forecast_snapshots.method = ai | avg`).

**Nội dung đúng để viết 3.2.3.2** (`services/forecast.py`, `services/forecast_ml/*`):
1. *Dữ liệu:* nhu cầu thường ngày lấy từ **sổ kho**: phiếu xuất cho người bệnh **không gắn ca đã khai** + yêu cầu người cần máu đã xác minh. **Không tính** điều chuyển, điều chỉnh (tránh cộng trùng với nhu cầu có kế hoạch; đếm cả phần "cần mà kho không có" để mô hình không học sai rằng thiếu máu = ít nhu cầu).
2. *Mô hình:* **XGBoost** (`objective = count:poisson` vì nhu cầu là số đếm, nhiều ngày bằng 0), dự báo trực tiếp từng ngày h = 1…14. 13 đặc trưng: h, thứ trong tuần, tháng, cờ Tết, nhóm máu, nhu cầu 1/7/14 ngày trước, trung bình 7 và 28 ngày, độ lệch chuẩn 28 ngày, số ngày có nhu cầu trong 28 ngày, trung bình 4 ngày cùng thứ. Cần tối thiểu 28 ngày lịch sử.
3. *So sánh với 2 mốc đơn giản:* B0 = trung bình 28 ngày, B1 = trung bình cùng thứ; đánh giá **backtest trượt theo thời gian**, chỉ số **WAPE** và **độ lệch (bias)**.
4. *Chốt chặn phiên bản* (`registry.py`): bản mới chỉ được dùng nếu WAPE **thấp hơn cả B0 và B1**, **không dự báo thiếu quá 5%**, và không thay bản học từ dữ liệu thật bằng bản học từ dữ liệu mô phỏng. Mọi phiên bản lưu riêng, quản trị kích hoạt lại được.
5. *Dữ liệu huấn luyện:* ưu tiên sổ kho thật (≥ 3 chuỗi, ≥ 180 ngày); chưa đủ thì dùng **dữ liệu mô phỏng** (Poisson theo quy mô bệnh viện × tỷ lệ nhóm máu × hệ số thứ × hệ số Tết × mùa), tự chuyển sang dữ liệu thật khi đủ.
6. *Vận hành tự động* (`monitor.py`): mỗi đêm dự báo + đo sai số thực tế theo tuần; **học lại chỉ khi có lý do** (chưa có mô hình / vừa đủ dữ liệu thật / AI thua trung bình 2 tuần liền / đủ số ngày dữ liệu mới), hai lần học lại cách nhau ≥ 7 ngày; **AI thua trung bình 3 tuần liền → tự tắt AI**, quay về trung bình và báo quản trị.
7. *Cảnh báo thiếu* (quy tắc nghiệp vụ, không phải AI): cần 14 ngày = tổng dự báo 14 ngày + nhu cầu có kế hoạch còn lại; **thiếu dự kiến = MAX(0, cần 14 ngày − khả dụng)**; đủ dùng = số ngày đến khi nhu cầu cộng dồn vượt khả dụng. Mức **Sắp thiếu** (< 7 ngày) → gợi ý mời người hiến; **Cần lên kế hoạch** (7–14 ngày) → gợi ý tạo đợt hiến; **Đủ**.

### 6.3 Chatbot tư vấn và hướng dẫn hiến máu

**Sai trong use case chương 2:**
- 🔴 *Luồng 4a "Dịch vụ AI lỗi: báo tạm thời không thể trả lời":* code **vẫn trả lời** — tự chuyển sang **chế độ từ khóa** (không cần AI) và đánh dấu AI "tạm ngắt" 60 giây để câu sau không phải chờ.
- 🟡 *Tiền điều kiện:* **khách chưa đăng nhập vẫn dùng được** chatbot; hội thoại của khách chỉ lưu trong phiên, của người đã đăng nhập lưu vào `chat_conversations` / `chat_messages` (chỉ chủ tài khoản xem/xóa, tự xóa sau `chat_retention_days` ngày).
- 🟠 *Thiếu:* giới hạn **20 câu / 5 phút** mỗi người; tối đa 2 câu xử lý AI cùng lúc; nhật ký chỉ ghi ý định / chế độ, **không ghi nội dung câu hỏi**.

**Nội dung đúng để viết 3.2.3.3** (`bloodbank/assistant/*`):

Luồng: **Câu hỏi → Chặn trước (guard) → Truy xuất tài liệu (RAG) + tra cứu dữ liệu (tools) → Mô hình ngôn ngữ (Ollama) → Kiểm tra câu trả lời (verify) → Trả lời kèm nguồn**; AI lỗi hoặc không qua kiểm tra → **chế độ từ khóa**.

1. *Chặn trước, không gọi AI* (`guard.py`), theo thứ tự: tình huống **khẩn cấp** (đang chảy máu, bất tỉnh… → hướng dẫn gọi ngay 115), hỏi **dữ liệu người khác**, **mua bán máu**, câu lệnh dò/phá quy tắc (prompt injection), hỏi **y khoa cá nhân** (bệnh nền, thuốc, mang thai… → khuyên hỏi bác sĩ).
2. *RAG* (`knowledge.py`): kho kiến thức **16 tài liệu đã duyệt** trong `kb/` (an toàn, chuẩn bị, quy trình, khoảng cách giữa 2 lần hiến, thể tích, chế phẩm, điều kiện chung, sau khi hiến…), mỗi tài liệu có nguồn, phiên bản, ngày duyệt. Truy xuất bằng **BM25** trên từ đơn + cụm 2 từ, chuẩn hóa không dấu ("hien mau" = "hiến máu"), tăng trọng số tiêu đề và từ khóa; dưới ngưỡng điểm thì trả lời "chưa có thông tin".
3. *Công cụ dữ liệu, chỉ đọc* (`tools.py`): đợt hiến gần bạn (theo vị trí / khu vực / thời gian), **khi nào hiến lại được**, lịch sử hiến, đơn đăng ký của tôi, yêu cầu cần máu của tôi, kiểm tra sơ bộ (tuổi, cân nặng, giới tính). Dữ liệu cá nhân **chỉ lấy theo phiên đăng nhập** — mô hình không truyền được id người khác; không trả tên bệnh nhân, số điện thoại, ghi chú.
4. *Mô hình ngôn ngữ chạy tại chỗ:* **Ollama**, mô hình **Qwen3 4B** (lượng tử hóa 4-bit), dữ liệu không rời máy chủ; tối đa 4 vòng gọi công cụ.
5. *Kiểm tra câu trả lời* (`verify.py`): mã tham chiếu (DK-, LH-, PR-) phải có trong dữ liệu đã tra cứu, nếu không coi là bịa; câu lẫn chữ Hán/Hàn/Nhật bị loại; câu khẳng định "đủ điều kiện hiến" luôn kèm nhắc "bác sĩ khám sàng lọc sẽ quyết định".
6. *Chế độ từ khóa* (`rules.py`, `smalltalk.py`): nhận diện ý định bằng từ khóa có/không dấu → gọi cùng bộ công cụ / tài liệu; xử lý câu chào hỏi.
7. *Hiển thị:* trả lời dần (streaming SSE), kèm **nguồn (tiêu đề + phiên bản tài liệu)** và liên kết.

### 6.4 Nội dung đúng để viết 3.2.1 (kiến trúc tích hợp AI)
- Ba chức năng "AI" dùng **ba kỹ thuật khác nhau**: (1) gợi ý người hiến = **luật lọc an toàn + học máy dự đoán khả năng nhận lời** (hồi quy logistic / XGBoost, so với chấm điểm luật, có chốt chặn); (2) dự báo nhu cầu = **học máy XGBoost** có mốc so sánh và chốt chặn; (3) chatbot = **RAG + mô hình ngôn ngữ chạy tại chỗ** có kiểm tra đầu ra.
- Các container Docker: `web` (Django + Gunicorn), `scheduler` (tác vụ định kỳ: dự báo mỗi đêm, huấn luyện lại, hết hạn yêu cầu, tự hủy đề nghị quá hạn), `db` (PostgreSQL 16), `ollama` (mô hình ngôn ngữ, không mở cổng ra ngoài).
- Nguyên lý chung: **AI chỉ gợi ý, con người quyết định**; AI **chỉ đọc**, không có thao tác ghi dữ liệu nghiệp vụ; luôn có **phương án dự phòng** khi AI lỗi (trung bình 28 ngày / chế độ từ khóa / khoảng cách đường chim bay); mọi kết quả AI đều **giải thích được** (lý do gợi ý, phương pháp dự báo, nguồn tài liệu).

### 6.5 Nội dung đúng để viết 3.2.2 (quy trình xử lý tri thức)
- Nguồn tri thức: các file `kb/*.md` có front matter `id, title, source, version, reviewed, keywords`.
- Quy trình cập nhật: sửa nội dung → **tăng version** → cập nhật ngày `reviewed` sau khi người có chuyên môn duyệt → commit (git giữ lịch sử).
- Giá trị cấu hình (tuổi tối thiểu, số ngày giữa 2 lần hiến…) được chèn vào tài liệu từ `system_settings` (biến `{whole}`, `{min_age}`…), nên đổi cấu hình thì câu trả lời đổi theo, không phải sửa tài liệu.
- Lập chỉ mục BM25 khi khởi động; câu trả lời luôn ghi tiêu đề + phiên bản tài liệu đã dùng.
- Hướng phát triển: thêm **pgvector** để tìm kiếm ngữ nghĩa kết hợp BM25 (hybrid).

---

## 7. Phần cơ sở dữ liệu
- Code có **23 bảng nghiệp vụ**; ERD và mục mô tả bảng chỉ có 19. Bốn bảng không có: `demands` (nhu cầu, ca khẩn — **nên thêm** vì nhiều use case dùng), `audit_logs` (nhật ký), `system_settings` (cấu hình), `stock_lots` (lô — có trong CSDL nhưng code chưa dùng, có thể bỏ qua).
- Nếu giữ 19 bảng, nên ghi một câu: "Sơ đồ trình bày các bảng nghiệp vụ chính; các bảng phụ trợ `demands`, `audit_logs`, `system_settings` được mô tả ở phụ lục."
- Ảnh mô tả bảng trong `docs/cau-truc-bang/` và ERD `docs/erd-chinh.png` đã khớp với code.

---

## 8. Những phần đã khớp với code (không cần sửa)
- 5 trạng thái đợt hiến (Nháp, Đang nhận đăng ký, Ngừng nhận đăng ký, Đã hoàn tất, Đã hủy); chỉ đợt đang mở nhận đăng ký; không công khai đợt nháp.
- Mỗi người tối đa một đơn trong một đợt (ràng buộc `uq_registrations_campaign_donor`, an toàn khi gửi đồng thời).
- Mỗi đơn tối đa một lượt hiến; sửa / hủy hiệu lực lượt hiến bắt buộc lý do, có nhật ký; lịch sử chỉ tính lượt còn hiệu lực.
- Email, số điện thoại không trùng; mật khẩu băm; khóa tạm khi đăng nhập sai nhiều lần.
- Mỗi tài khoản chỉ thuộc một bệnh viện (`uq_staffs_user`).
- Khả dụng = tồn − giữ chỗ; chống gửi lặp bằng khóa `idempotency_key`; khóa phiên bản `stocks.version`.
- Một bệnh viện tối đa một đề nghị cho một yêu cầu (`uq_offers_request_supplier`); bên cấp khác bên cần (trigger CSDL); mỗi đề nghị tối đa một phiếu xuất và một phiếu nhập (`uq_txn_offer_type`).
- Mỗi chế phẩm có tối đa một quy cách mặc định (`uq_specs_one_default`); ngừng dùng thay vì xóa.
- Nhật ký hệ thống chỉ đọc; thông báo trong ứng dụng + email.
- Chatbot không chẩn đoán, không xác nhận đủ điều kiện hiến, không thay đổi dữ liệu nghiệp vụ.
- Dự báo: AI dự báo nhu cầu, thiếu hụt do quy tắc tính; không tự cấp phát / điều chuyển.
