# 04 · Báo cáo bảo mật

Phạm vi: mã nguồn repo + ứng dụng QA cô lập `http://127.0.0.1:8091` (DEBUG tắt, dữ liệu giả).
Chỉ dùng kiểm tra thụ động / không phá hủy. Không có quét chủ động, khai thác hay brute force.

## Công cụ đã chạy

| Công cụ | Phiên bản | Cấu hình | Kết quả thô |
|---|---|---|---|
| Semgrep | 1.179.0 (Docker) | `p/django p/python p/secrets p/security-audit p/dockerfile`, 276 rule, 159 file | `security/raw/semgrep.json` (24 cảnh báo) |
| OWASP ZAP | stable (Docker) | `zap-baseline.py` — spider 3 phút + quét **thụ động** | `security/raw/zap-baseline.{json,html}` (56 PASS, 11 WARN, 0 FAIL) |
| Nuclei | latest + template chính thức (Docker) | tags `misconfig,exposure,headers,tech,config,panel`; loại `dos,fuzz,intrusive,bruteforce`; 20 req/s | `security/raw/nuclei.jsonl` (7 kết quả, đều mức info) |
| Django `check --deploy` | Django 5.2.7 | trên container QA | `security/raw/django-check-deploy.txt` (4 cảnh báo) |
| Test kiểm chứng | Django TestCase | `bloodbank/tests/test_qa_audit.py` | `evidence/django-qa-audit-tests.txt` |

**Không chạy (Blocked):** ZAP active scan, Strix, Shannon, Hercules — cần phê duyệt riêng và (Strix/Shannon/Hercules) API key LLM có tính phí.

## Lỗ hổng đã xác nhận

| ID | Mức | CWE | Tiêu đề | Công cụ |
|---|---|---|---|---|
| SEC-01 | Trung bình | CWE-348 | IP trong nhật ký lấy từ header `X-Forwarded-For` do client tự gửi | Test + đọc code |
| SEC-02 | Thấp | CWE-204 | Phân biệt được tài khoản bị khóa trước khi kiểm tra mật khẩu | Test |
| SEC-03 | Thấp | CWE-770 | Không giới hạn tần suất email đặt lại mật khẩu | Test |
| SEC-04 | Thấp | CWE-250 | Container ứng dụng chạy bằng root | Semgrep |
| SEC-05 | Trung bình* | CWE-693 | Thiếu Content-Security-Policy, Permissions-Policy | ZAP |
| SEC-06 | Cấu hình | CWE-614/319 | Chưa bật HSTS / SSL redirect / cookie Secure | Django check, Nuclei |
| SEC-07 | Cấu hình | CWE-1188/798 | Cấu hình mặc định nguy hiểm nếu đem đi triển khai | Đọc cấu hình |

\* Mức theo ZAP; thực tế giảm nhẹ nhờ Django tự escape template và không có script inline từ dữ liệu người dùng.

### SEC-01 · Giả mạo IP trong nhật ký kiểm toán
- **Bằng chứng:** đăng nhập với `REMOTE_ADDR=10.0.0.5`, `X-Forwarded-For: 203.0.113.77` → `audit_logs.ip_address = 203.0.113.77` (`test_audit_ip_not_taken_from_spoofable_header`).
- **Vị trí:** [common.py:150](../../backend/bloodbank/services/common.py#L150) `client_ip()`.
- **Ảnh hưởng:** người dùng tự ghi IP tùy ý vào nhật ký (đăng nhập, xem dữ liệu nhạy cảm của yêu cầu cần máu) → nhật ký không đáng tin khi điều tra. Không ảnh hưởng khóa đăng nhập (khóa theo tài khoản, không theo IP).
- **Khắc phục:** chỉ tin `X-Forwarded-For` khi request đi qua proxy tin cậy (cấu hình danh sách proxy / số hop); mặc định dùng `REMOTE_ADDR`.

### SEC-02 · Liệt kê tài khoản qua thông báo "bị khóa"
- **Bằng chứng:** mật khẩu SAI — tài khoản bị khóa → "Tài khoản đang bị khóa…"; email không tồn tại → "Email hoặc mật khẩu không đúng." (`test_locked_account_not_distinguishable_before_password_check`).
- **Vị trí:** [accounts/services.py:86](../../backend/accounts/services.py#L86) — kiểm tra `status == LOCKED` trước `check_password`.
- **Khắc phục:** chỉ báo "bị khóa" khi mật khẩu đúng; mật khẩu sai luôn trả thông báo chung.

### SEC-03 · Không giới hạn yêu cầu đặt lại mật khẩu
- **Bằng chứng:** 8 yêu cầu liên tiếp cho cùng 1 email → 8 email gửi đi (`test_password_reset_requests_rate_limited`). Tương tự cho "Gửi lại email xác thực".
- **Ảnh hưởng:** spam hộp thư người dùng, tốn hạn mức gửi mail.
- **Khắc phục:** giới hạn theo email + IP (vd. 3 lần / 15 phút), dùng bảng `auth_tokens` sẵn có để đếm.

### SEC-04 · Container chạy bằng root
- **Bằng chứng:** Semgrep `dockerfile.security.missing-user` — [Dockerfile:17-18](../../backend/Dockerfile#L17) không có `USER`.
- **Khắc phục:** tạo user không đặc quyền và `USER app` trước `ENTRYPOINT`.

### SEC-05 · Thiếu header bảo vệ trình duyệt
- **Bằng chứng ZAP:** thiếu `Content-Security-Policy` (5 URL), `Permissions-Policy`, `Cross-Origin-Embedder-Policy`, `Cross-Origin-Resource-Policy`; stylesheet Google Fonts không có SRI.
- **Đã có (PASS):** `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`.
- **Khắc phục:** thêm CSP (Django 6 có sẵn; với 5.2 dùng `django-csp` hoặc middleware nhỏ), cho phép `fonts.googleapis.com`/`fonts.gstatic.com`; thêm `Permissions-Policy`.

### SEC-06 · Cấu hình HTTPS (Django `check --deploy`)
- W004 `SECURE_HSTS_SECONDS` chưa đặt · W008 `SECURE_SSL_REDIRECT` chưa bật · W012 `SESSION_COOKIE_SECURE` · W016 `CSRF_COOKIE_SECURE`.
- Bình thường với môi trường HTTP nội bộ; **bắt buộc** bật khi triển khai thật (đọc từ biến môi trường).

### SEC-07 · Mặc định nguy hiểm khi triển khai
Đọc từ `docker-compose.yml`, `Dockerfile`, `.env.example`, `settings.py`:
- Postgres publish `0.0.0.0:5433` với mật khẩu mặc định trong compose; pgAdmin `0.0.0.0:5050` chế độ desktop (`SERVER_MODE=False`, không cần đăng nhập) — ai cùng mạng LAN cũng vào được DB.
- `SECRET_KEY` có giá trị dự phòng `dev-only-insecure-key` khi thiếu biến môi trường ([settings.py:13](../../backend/config/settings.py#L13)).
- `SEED_DEMO=1` mặc định; mật khẩu chung của mọi tài khoản mẫu (kể cả quản trị) nằm trong mã nguồn công khai (`seed_demo.py`).
- Gunicorn chạy `--reload` trong `CMD` của Dockerfile.
- **Khắc phục:** chỉ bind `127.0.0.1` cho DB/pgAdmin; bỏ giá trị dự phòng của `SECRET_KEY` khi `DEBUG=0` (dừng khởi động); `SEED_DEMO=0` mặc định; tách `--reload` sang compose dev.

## Đã kiểm tra — không phải lỗ hổng (False Positive / Pass)

| Cảnh báo | Kết luận | Căn cứ |
|---|---|---|
| Semgrep `django-no-csrf-token` × 10 template | **False positive** | Mọi form POST đều có `{% csrf_token %}` ở dòng kế tiếp |
| Semgrep `unvalidated-password` × 4 | **False positive** | Form gọi `password_validation.validate_password` ([accounts/forms.py:25](../../backend/accounts/forms.py#L25)); `services.py:84` chỉ băm giả để cân bằng thời gian |
| Semgrep `open-redirect` `member.py:218` | **False positive** | Test `next="/\\evil"`, `"/\t/evil"`: Django mã hóa thành `%5C`/`%09` trong `Location` → đường dẫn nội bộ |
| Semgrep `open-redirect` `public.py:67` | **False positive** | `next` lấy từ `request.path` (nội bộ) |
| Semgrep `var-in-href` × 7 | **False positive** | Giá trị lấy từ `{% url %}`/dữ liệu nội bộ, đã escape |
| ZAP "User controllable HTML attribute" (`/dang-nhap/?next=`) | **Pass** | HTTP thật: `next="><b>qa` được escape (`&quot;&gt;…`), không thực thi |
| ZAP/Nuclei "csrftoken không HttpOnly" | **Chấp nhận** | Thiết kế của Django (`CSRF_COOKIE_HTTPONLY=False`); sessionid có HttpOnly |
| ZAP "Cross-Domain Misconfiguration" | **Rủi ro thấp** | `Access-Control-Allow-Origin: *` chỉ trên file tĩnh công khai (WhiteNoise) |
| Nuclei `waf-detect apachegeneric`, `tech-detect` | Info | Nhận diện công nghệ, không phải lỗ hổng |
| Cô lập dữ liệu giữa bệnh viện (IDOR) | **Pass** | `CrossHospitalIsolationTests`: 4 GET + 3 POST vào dữ liệu bệnh viện khác → 404/không đổi dữ liệu; cộng 98 test gốc gồm ma trận phân quyền mọi route × vai trò |

---

## Kết quả sau khi sửa (14/10/2026)

| ID | Trạng thái | Cách sửa |
|---|---|---|
| SEC-01 | **Đã sửa** | `client_ip()` dùng `REMOTE_ADDR`; chỉ tin `X-Forwarded-For` khi đặt `TRUSTED_PROXY_COUNT` (lấy địa chỉ do proxy tin cậy ghi). Test cả 2 trường hợp |
| SEC-02 | **Đã sửa** (một phần) | Tài khoản bị khóa + mật khẩu sai → cùng thông báo như email không tồn tại; mật khẩu đúng vẫn báo "bị khóa". **Còn lại:** khóa tạm do sai 5 lần vẫn hiện thông báo riêng (cần thiết để chặn đoán mật khẩu; chỉ lộ sau 5 lần thử trên đúng email đó) |
| SEC-03 | **Đã sửa** | Tối đa 3 email đặt lại mật khẩu / xác thực mỗi 15 phút cho 1 tài khoản (cấu hình được); vượt hạn mức: trang phản hồi giống hệt |
| SEC-04 | **Đã sửa** | Dockerfile tạo user `app` (uid 1000), `USER app`. Semgrep chạy lại: hết cảnh báo. Compose dev vẫn chạy root vì mount mã nguồn từ máy |
| SEC-05 | Chưa sửa | Thêm CSP cần rà các script inline (bản đồ, thông báo) để không làm hỏng giao diện — đề xuất làm riêng |
| SEC-06 | Chưa sửa | Chỉ áp dụng khi chạy HTTPS — bật lúc triển khai |
| SEC-07 | **Đã sửa phần lớn** | Postgres/pgAdmin chỉ bind `127.0.0.1`; `SECRET_KEY` bắt buộc khi `DEBUG=0` (thiếu → dừng khởi động); `--reload` chỉ ở compose dev; `.env.example` ghi chú tắt `SEED_DEMO` khi triển khai |

---

## Vòng 2 (14/10/2026)

**ZAP active scan** (`zap-full-scan.py`, chủ dự án cho phép, chỉ nhắm QA localhost, giới hạn 12 phút / 2 phút mỗi quy tắc, 3 GB RAM). Kết quả: `security/raw/zap-full.{json,html}`.
- **0 FAIL · 136 PASS.** Các mục PASS gồm SQL Injection (nhiều biến thể), XSS (reflected / persistent / DOM), Server Side Template Injection, Remote OS Command Injection, Path Traversal, Remote File Inclusion, XXE, CRLF Injection, NoSQL Injection, phân tích Insecure HTTP Method.
- **6 WARN, không có lỗ hổng mới:**
  - `csrftoken` không có HttpOnly: thiết kế của Django.
  - CSP `style-src 'unsafe-inline'`: chủ ý, vì template dùng thuộc tính style; `script-src` vẫn là `'self'`.
  - `Access-Control-Allow-Origin: *` chỉ trên file tĩnh.
  - HTTP Only Site: bản QA chạy HTTP; khi triển khai thì bật `DJANGO_HTTPS=1`.
  - SRI cho stylesheet Google Fonts.
  - Thiếu COEP: không dùng tài nguyên cần cô lập.
- **Giới hạn:** chỉ quét phần không đăng nhập (ZAP chưa được cấu hình phiên). Phần sau đăng nhập đã được kiểm qua test phân quyền, ma trận route × vai trò và kiểm thử đồng thời.
- Lần chạy đầu không giới hạn đã làm treo Docker Desktop vì hết bộ nhớ. Đã chạy lại với giới hạn tài nguyên.

**Đã sửa thêm trong vòng 2:**
- Race condition khóa đăng nhập (CC-01): đã xác nhận trên code cũ, 12/12 lần sai đồng thời đều được kiểm tra mật khẩu. Đã sửa bằng cách khóa dòng tài khoản.
- **SEC-05 (CSP) đã sửa**: `script-src 'self'`, không còn script inline; thêm `Permissions-Policy`, `Cross-Origin-Resource-Policy`.
- **SEC-06 đã có cấu hình**: đặt `DJANGO_HTTPS=1` là bật SSL redirect, HSTS và cookie Secure (`check --deploy` sạch, trừ tùy chọn preload).
