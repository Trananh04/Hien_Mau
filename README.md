# Giọt Hồng — Hệ thống hiến máu

Hệ thống kết nối người hiến máu, người nhà bệnh nhân cần máu và các bệnh viện: đăng ký đợt hiến, ghi nhận lượt hiến,
quản lý kho máu, điều phối máu giữa các bệnh viện và xử lý yêu cầu cần máu.

- **Backend:** Django 5.2 · PostgreSQL 16 · pgAdmin 4 · tác vụ định kỳ (scheduler), chạy toàn bộ bằng Docker
- **Giao diện:** Django template kết xuất phía máy chủ + **HTMX 2** (chuyển trang, gửi form, lọc không tải lại trang) · CSS riêng · icon Lucide · bản đồ Leaflet. Không cần Node.js, an toàn với CSP chặt (không script/style nội tuyến)
- **Đặc tả:** BLOOD-SRS-001 v1.1 (*Tài liệu thiết kế CSDL hiến máu*)

> Dự án học tập. Mọi bệnh viện, người dùng và số liệu đều là **dữ liệu mẫu**.

---

## 1. Yêu cầu

| Phần mềm | Ghi chú |
|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Đã bật và đang chạy (Windows / macOS / Linux) |
| [Git](https://git-scm.com/) | Để clone mã nguồn |

Không cần cài Python hay PostgreSQL trên máy, vì mọi thứ chạy trong container.

## 2. Chạy lần đầu

```bash
git clone https://github.com/trananh0612/Hien_Mau.git
cd Hien_Mau

# Tạo file cấu hình từ mẫu
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env

# Build và khởi động
docker compose up -d --build
```

Lần đầu mất vài phút để tải image. Khi khởi động, container `web` tự động:
1. chạy migration (tạo 19 bảng, ràng buộc, trigger),
2. gom file tĩnh,
3. nạp **dữ liệu mẫu** (chỉ nạp một lần, chạy lại không bị nhân bản).

Xem tiến trình: `docker compose logs -f web`. Khi thấy dòng `Listening at: http://0.0.0.0:8000` là đã sẵn sàng.

## 3. Địa chỉ truy cập

| Dịch vụ | Địa chỉ | Đăng nhập |
|---|---|---|
| Website | http://localhost:8080 | xem mục 4 |
| pgAdmin 4 (quản lý CSDL) | http://localhost:5050 | `admin@hienmau.vn` / `admin123`. Server "Hiến máu (Docker)" đã cấu hình sẵn, mật khẩu DB: `hienmau_dev_pw` |
| PostgreSQL (kết nối từ máy) | `localhost:5433` | DB `hien_mau`, user `hienmau`, mật khẩu `hienmau_dev_pw` |

Ngoài ra container `scheduler` chạy tác vụ định kỳ 5 phút/lần (xem mục 5a). Xem log: `docker compose logs -f scheduler`.

## 4. Vai trò và tài khoản mẫu

Mật khẩu chung cho mọi tài khoản mẫu: **`Demo@2026`**

Hệ thống có **3 vai trò tách biệt**. Mỗi vai trò đăng nhập ở **trang riêng** và chỉ mở được màn hình của mình.

| Vai trò | Trang đăng nhập | Tài khoản mẫu |
|---|---|---|
| **Người dùng** (người hiến máu, người nhà bệnh nhân) | http://localhost:8080/dang-nhap/ | `an.nguyen@demo.vn`, `binh.tran@demo.vn`, … |
| **Nhân viên bệnh viện** (Quản lý / Nhân viên) | http://localhost:8080/benh-vien/dang-nhap/ | `benhvien1@hienmau.vn` … `benhvien5@hienmau.vn` (đều là Quản lý bệnh viện) |
| **Quản trị hệ thống** | http://localhost:8080/quan-tri/dang-nhap/ | `admin@hienmau.vn` |

- `benhvien1@hienmau.vn` làm việc ở 2 bệnh viện nên có bộ chọn bệnh viện trên thanh bên trái.
- Đăng nhập sai cổng sẽ bị từ chối, kèm link sang đúng cổng — trừ tài khoản quản trị (không bao giờ chỉ đường tới cổng quản trị).
- **Cổng quản trị không có liên kết nào trên giao diện** và không được Google lập chỉ mục. Người chưa đăng nhập / không phải quản trị mở bất kỳ trang `/quan-tri/...` nào đều nhận **404** (như thể không tồn tại); lần dò của tài khoản đã đăng nhập được ghi nhật ký `access_denied`. Khi chạy thật nên đặt `ADMIN_LOGIN_PATH` (đường dẫn khó đoán) và `ADMIN_ALLOWED_IPS`.
- Cổng bệnh viện chỉ có một liên kết nhỏ "Dành cho nhân viên bệnh viện" ở chân trang (nhân viên nên lưu dấu trang).
- Người dùng tự đăng ký tại `/dang-ky/`.
- Bệnh viện tự đăng ký tại `/benh-vien/dang-ky/` (kèm tài khoản **Quản lý bệnh viện**) → Quản trị duyệt ở **Quản trị → Bệnh viện → Chờ duyệt** → Quản lý đăng nhập và tự cấp / thu hồi tài khoản nhân viên ở **Bệnh viện → Nhân viên**. Chưa được duyệt hoặc bị từ chối thì không đăng nhập được (báo rõ lý do). Quản trị vẫn cấp được tài khoản nhân viên tại trang chi tiết bệnh viện.
- Email (xác thực, quên mật khẩu) không gửi thật mà được in ra log: `docker compose logs -f web`. Ở chế độ phát triển, link cũng hiện ngay trên trang.

### Phân quyền màn hình

Toàn bộ quyền "vai trò nào mở được màn hình nào" nằm trong **một file**: [`backend/bloodbank/access.py`](backend/bloodbank/access.py).

- Mỗi màn hình khai báo các đường dẫn của nó và các vai trò được phép.
- `ScreenAccessMiddleware` kiểm tra **mọi request** theo bảng này. Đường dẫn chưa khai báo sẽ bị chặn.
- Menu và màn hình **Quản trị → Phân quyền** đọc từ cùng bảng, nên luôn khớp với quyền thật.

## 5. Các lệnh thường dùng

```bash
docker compose ps                     # xem trạng thái container
docker compose logs -f web            # xem log web
docker compose stop                   # tạm dừng
docker compose start                  # chạy lại
docker compose down                   # dừng và xóa container (GIỮ dữ liệu)
docker compose down -v                # dừng và XÓA LUÔN dữ liệu CSDL (lần sau tự nạp lại dữ liệu mẫu)

# Chạy lệnh Django trong container
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_demo
docker compose exec web python manage.py shell
```

Thư mục `backend/` được mount vào container và gunicorn chạy chế độ `--reload`, nên **sửa code Python/template là thấy ngay**,
không cần build lại. Sau khi sửa CSS/JS trong `backend/static/`, chạy thêm:

```bash
docker compose exec web python manage.py collectstatic --noinput
```

## 5a. Các luồng tự động hóa

| Luồng | Cách hoạt động |
|---|---|
| **Lượt hiến → kho** | Ghi nhận lượt hiến xong, lượt hiến vào hàng **Kho máu → Chờ xét nghiệm**. Xét nghiệm *Đạt*: một lần bấm nhập kho, nhóm máu lấy theo kết quả xét nghiệm, phiếu nhập gắn với lượt hiến (truy xuất được trong sổ kho). *Không đạt*: không nhập kho, bắt buộc ghi lý do. |
| **Tác vụ định kỳ** (`scheduler`) | Yêu cầu liên viện quá hạn → hết hạn và giải phóng giữ chỗ. Đề nghị không được phản hồi quá 12 giờ → tự hủy, báo bên yêu cầu mời bệnh viện khác. Chạy tay: `docker compose exec web python manage.py run_jobs`. |
| **Yêu cầu cần máu khẩn** | Gửi ngay thông báo + email cho mọi nhân viên bệnh viện. Sau 15 phút chưa ai nhận xác minh: nhắc lại toàn bộ nhân viên. Sau 30 phút: báo lên Quản trị hệ thống. Mỗi mức nhắc một lần. |
| **Gợi ý nguồn liên viện** | Nhập "Số cần" ở Tìm nguồn: xếp bệnh viện gần trước, tự chia số lượng cho các nguồn đúng quy cách và đánh dấu sẵn, bấm một lần để gửi. |
| **Cảnh báo khoảng cách hiến** | Khi check-in, nếu lần hiến trước chưa đủ 84 ngày (toàn phần) / 14 ngày (thành phần) thì hiện cảnh báo. Chỉ cảnh báo, không chặn: bác sĩ khám sàng lọc quyết định. |
| **Xử lý thiếu hụt** | Mỗi dòng thiếu có 3 nút: *Xin hỗ trợ* (mở Tìm nguồn điền sẵn), *Tạo đợt hiến* (điền sẵn), *Kêu gọi* người dùng cùng khu vực, nhóm máu tự khai trùng, đã đủ thời gian nghỉ. Nhân viên chỉ thấy số người nhận; mỗi nhóm máu kêu gọi tối đa 1 lần/24 giờ. |
| **Ngày hiến lại** | Trang Lịch sử hiến: ngày có thể hiến lại và đợt hiến gần nhất. Tác vụ định kỳ nhắc một lần khi đã đủ thời gian nghỉ. |

Mọi ngưỡng (số ngày, số phút, số giờ) chỉnh tại **Quản trị → Cấu hình**. Email ở môi trường dev in ra log `web` / `scheduler`.

## 5b. Trợ lý hỏi đáp (chatbot)

Nút tròn góc phải mọi trang. Luồng xử lý:

```
Câu hỏi → chặn trước (khẩn cấp / y khoa cá nhân / dữ liệu người khác / mua bán / câu lệnh lạ)
        → truy xuất tài liệu đã duyệt (RAG) + tra cứu sẵn dữ liệu theo ý định (chỉ đọc, đúng người đăng nhập)
        → Claude tổng hợp (nếu có API key) → KIỂM TRA (mã DK-/PR- phải có trong dữ liệu thật; câu khẳng định
          "đủ điều kiện" luôn kèm nhắc bác sĩ) → không qua / AI lỗi → chế độ từ khóa
        → lưu hội thoại → trả lời + nguồn (tiêu đề tài liệu, phiên bản) + thẻ đợt hiến / nút liên kết
```

| Mã | Chức năng | Ví dụ | Cách làm |
|---|---|---|---|
| CHAT-01 | Kiến thức hiến máu | Hiến máu có ảnh hưởng sức khỏe không? | RAG |
| CHAT-02 | Kiểm tra điều kiện sơ bộ | Tôi 20 tuổi, nặng 48kg có hiến được không? | Luật cố định + RAG; thiếu giới tính/tuổi → hỏi lại; không bao giờ kết luận "đủ điều kiện" |
| CHAT-03 | Trước / sau khi hiến | Trước khi hiến có được ăn sáng không? | RAG |
| CHAT-04 | Tìm đợt hiến | Hà Nội có đợt nào sắp diễn ra? | Truy vấn DB (khu vực, thời gian, vị trí; bỏ đợt đã đăng ký / trước ngày được hiến lại) |
| CHAT-05 | Hướng dẫn đăng ký | Đăng ký hiến máu thế nào? | RAG |
| CHAT-06 | Lịch sử hiến | Tôi đã hiến bao nhiêu lần? | DB (chỉ lượt đã xác nhận) |
| CHAT-07 | Ngày hiến tiếp | Bao giờ tôi hiến tiếp được? | DB + luật khoảng nghỉ |
| CHAT-08 | Lịch đăng ký | Tôi đã đăng ký ngày nào? | DB |
| CHAT-09 | Chế phẩm máu | Tiểu cầu và hồng cầu khác nhau thế nào? | RAG |
| CHAT-10 | Dùng website | Thay đổi thông tin cá nhân thế nào? | RAG |

**Tài liệu RAG** nằm trong `backend/bloodbank/assistant/kb/*.md` — mỗi file có `id`, `title`, `source`, `version`,
`reviewed`, `keywords`; sửa nội dung thì tăng `version` (git giữ lịch sử). Truy xuất BM25 không dấu (không cần dịch vụ
embedding); khi tài liệu lớn có thể bổ sung pgvector. Nội dung y khoa cần cơ sở y tế rà soát trước khi dùng thật.

**Ghi nhớ hội thoại:** người đã đăng nhập — lưu DB (`chat_conversations`, `chat_messages`), mở lại trợ lý là thấy cuộc
trò chuyện trước; chỉ chủ tài khoản xem/xóa được; tự xóa sau `chat_retention_days` (mặc định 30) ngày. Khách — chỉ
trong phiên. Nhật ký hệ thống chỉ ghi ý định/chế độ, không ghi nội dung câu hỏi.

**API** (JSON, xác thực bằng phiên đăng nhập; POST/DELETE cần CSRF; chưa đăng nhập → 401, sai vai trò → 403,
hội thoại của người khác → 404):

| API | Quyền | Chức năng |
|---|---|---|
| `POST /api/chatbot/message` | Công khai | Gửi câu hỏi `{message, conversation_id?, lat?, lng?}` |
| `GET /api/chatbot/conversations` | Đã đăng nhập | Danh sách hội thoại của chính mình |
| `GET` / `DELETE /api/chatbot/conversations/{id}` | Đã đăng nhập | Xem / xóa một hội thoại của chính mình |
| `GET /api/donations/me/history` | Người dùng | Lịch sử hiến (đã xác nhận) |
| `GET /api/donations/me/eligibility?age=&weight_kg=&gender=` | Người dùng | Ngày được hiến lại + đối chiếu sơ bộ |
| `GET /api/donation-campaigns?area=&date_from=&date_to=&time_of_day=&limit=&lat=&lng=` | Công khai | Tìm đợt hiến |
| `GET /api/donation-registrations/me` | Người dùng | Lịch đăng ký và trạng thái |

**Hai chế độ:** không có `ANTHROPIC_API_KEY` → chế độ từ khóa (miễn phí). Có key → Claude (mặc định
`claude-haiku-5-5`; dùng dịch vụ trung gian tương thích `/v1/messages` bằng `CHATBOT_BASE_URL`). Trợ lý chỉ đọc —
không đăng ký/hủy thay người dùng; nếu sau này thêm, bắt buộc có bước xác nhận rõ ràng trước khi thực hiện.

## 5c. Phạm vi toàn quốc (tỉnh/thành)

- Danh sách **34 tỉnh/thành hiện hành** (Nghị quyết 202/2025/QH15, từ 01/7/2025) nằm ở một chỗ duy nhất: `backend/accounts/provinces.py`. Mọi ô chọn tỉnh/thành (đăng ký, hồ sơ, bệnh viện, đợt hiến, bộ lọc, bản đồ) và trợ lý đều đọc từ đây.
- Tên tỉnh cũ được tự quy về tên mới: người dùng hỏi trợ lý "đợt hiến ở Bình Dương / Quảng Nam / Sóc Trăng" vẫn được hiểu là TP. Hồ Chí Minh / Đà Nẵng / Cần Thơ. Migration `bloodbank/0009_provinces_2025` chuyển dữ liệu cũ sang tên mới.
- Bản đồ mặc định nhìn toàn quốc; form đợt hiến đặt điểm ban đầu theo vị trí bệnh viện, chưa có thì theo trung tâm tỉnh của bệnh viện.
- Khi có thay đổi địa giới hành chính: sửa `PROVINCES`, `LEGACY`, `CENTERS` trong file trên và thêm một migration dữ liệu tương tự.

## 6. Kiểm thử

```bash
docker compose run --rm --no-deps web python manage.py test bloodbank.tests
```

Bộ test (170 test) chạy trên PostgreSQL thật, gồm:
- ràng buộc CSDL (CHECK / UNIQUE / trigger),
- các luồng nghiệp vụ qua HTTP (đợt hiến, điểm hiến, kho, điều phối liên viện, yêu cầu cần máu),
- phân quyền: mọi đường dẫn × mọi vai trò, 3 cổng đăng nhập,
- các luồng tự động hóa ở mục 5a,
- smoke test mở mọi màn hình với từng vai trò trên dữ liệu mẫu,
- test hồi quy cho các lỗi tìm được trong đợt QA audit (`test_qa_audit.py`, xem `qa-audit/`),
- kiểm thử đồng thời nhiều luồng trên PostgreSQL thật (`test_concurrency.py`),
- trợ lý hỏi đáp + bộ 47 câu hỏi mẫu (`test_assistant.py`, `assistant_eval.json`; phần Claude dùng client giả lập, không tốn phí).

## 7. Cấu hình (`.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `WEB_HOST_PORT` | `8080` | Cổng website trên máy |
| `DB_HOST_PORT` | `5433` | Cổng PostgreSQL — chỉ mở cho chính máy (`127.0.0.1`) |
| `PGADMIN_HOST_PORT` | `5050` | Cổng pgAdmin — chỉ mở cho chính máy (`127.0.0.1`, pgAdmin chạy không cần đăng nhập) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `hien_mau` / `hienmau` / `hienmau_dev_pw` | Thông tin CSDL |
| `PGADMIN_EMAIL` / `PGADMIN_PASSWORD` | `admin@hienmau.vn` / `admin123` | Tài khoản pgAdmin |
| `SEED_DEMO` | `1` | `1` = tự nạp dữ liệu mẫu khi khởi động (mật khẩu mẫu công khai — **đặt `0` khi triển khai thật**) |
| `JOBS_INTERVAL_SECONDS` | `300` | Chu kỳ chạy tác vụ định kỳ (giây) |
| `DJANGO_DEBUG` | `1` | Chế độ phát triển |
| `DJANGO_SECRET_KEY` | (chuỗi mẫu) | **Phải đổi** nếu triển khai thật; bắt buộc khi `DJANGO_DEBUG=0` (thiếu thì ứng dụng không khởi động) |
| `ANTHROPIC_API_KEY` | (trống) | Khóa Claude API cho trợ lý hỏi đáp. Trống = chế độ từ khóa (không cần AI, miễn phí) |
| `CHATBOT_MODEL` | `claude-haiku-5-5` | Mô hình Claude của trợ lý (rẻ, nhanh) |
| `CHATBOT_RATE_LIMIT` | `20` | Số câu hỏi tối đa / 5 phút / người dùng |
| `CHATBOT_MAX_CONCURRENT` | `8` | Số câu gửi AI cùng lúc (khóa advisory PostgreSQL, áp cho mọi worker); vượt → trả lời ngay bằng chế độ từ khóa thay vì xếp hàng |
| `CHATBOT_DAILY_LIMIT` | `2000` | Hạn mức gọi AI mỗi ngày (chặn chi phí bất thường); hết → chế độ từ khóa |
| `DJANGO_HTTPS` | `0` | `1` khi chạy sau HTTPS: chuyển hướng HTTPS, HSTS, cookie Secure |
| `ADMIN_LOGIN_PATH` | `quan-tri/dang-nhap` | Đường dẫn trang đăng nhập quản trị. Khi chạy thật đặt chuỗi khó đoán (vd `quan-tri-7f3k9/vao`) |
| `ADMIN_ALLOWED_IPS` | (trống) | Danh sách IP được vào cổng quản trị, cách nhau dấu phẩy. Trống = không giới hạn; IP khác nhận 404 |
| `TRUSTED_PROXY_COUNT` | `0` | Số reverse proxy tin cậy đứng trước ứng dụng. `0` = ghi IP nhật ký theo kết nối thật, không tin header `X-Forwarded-For` |

> `.env` chứa mật khẩu nên không được đưa lên git. Chỉ `.env.example` được commit.

## 8. Xử lý lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `port is already allocated` | Cổng đang bị chương trình khác dùng. Đổi `WEB_HOST_PORT` / `DB_HOST_PORT` / `PGADMIN_HOST_PORT` trong `.env` rồi `docker compose up -d` |
| `env file .env not found` | Chưa tạo `.env`: chạy `cp .env.example .env` |
| Container `web` báo `/bin/sh^M` hoặc `entrypoint.sh: not found` | File `.sh` bị đổi sang CRLF. Repo đã có `.gitattributes`; clone lại, hoặc chạy `git add --renormalize .` |
| Trang không có CSS sau khi sửa | Chạy `collectstatic` (mục 5) rồi tải lại trang bằng Ctrl+F5 |
| Muốn làm lại dữ liệu từ đầu | `docker compose down -v` rồi `docker compose up -d` |
| Bản đồ hoặc phông chữ không hiện | Cần có internet (ô bản đồ OpenStreetMap, Google Fonts) |

## 9. Cấu trúc thư mục

```
docker-compose.yml          db (postgres:16) · pgadmin (pgadmin4) · web (Django + gunicorn) · scheduler (tác vụ định kỳ)
.env.example                mẫu cấu hình
pgadmin/servers.json        server pgAdmin cấu hình sẵn
backend/
  Dockerfile, entrypoint.sh migrate → collectstatic → nạp dữ liệu mẫu → gunicorn
  config/                   settings, urls
  accounts/                 bảng users, auth_tokens; đăng ký, 3 cổng đăng nhập, khôi phục mật khẩu
  bloodbank/
    access.py               BẢNG PHÂN QUYỀN màn hình theo vai trò
    middleware.py           kiểm tra quyền cho mọi request
    models/                 18 bảng nghiệp vụ còn lại, đúng tên bảng/cột của Data Dictionary
    migrations/             0002: trigger PostgreSQL · 0003: cấu hình + danh mục · 0004: gộp vai trò bệnh viện
                            0005: xét nghiệm lượt hiến, liên kết phiếu nhập ↔ lượt hiến, tham số tác vụ
                            0006: nhật ký kêu gọi người hiến
    services/               nghiệp vụ: máy trạng thái, kho (TX-STOCK), idempotency, nhật ký, thông báo,
                            lab (xét nghiệm → kho), jobs (tác vụ định kỳ), callout + donor_match (gợi ý và
                            kêu gọi người hiến), shortage (danh sách "Cần xử lý"), badges (huy hiệu)
    views/                  public · member · hospital_* · admin
    management/commands/    seed_demo (dữ liệu mẫu) · seed_hanoi_demo (dữ liệu mẫu Hà Nội, --xoa để gỡ)
                            · run_jobs (tác vụ định kỳ)
    tests/                  bộ kiểm thử
  templates/                giao diện (công khai / cá nhân / khu làm việc bệnh viện, quản trị)
  static/                   css (site.css: trang công khai, ui.css: thành phần dùng chung), js (app.js: tương tác +
                            khởi tạo lại sau mỗi lần HTMX thay nội dung, maps.js), ảnh, vendor (htmx, lucide, leaflet)
```

### Giao diện với HTMX

- `<body hx-boost="true">`: liên kết và form được gửi bằng AJAX, máy chủ trả trang HTML đầy đủ, HTMX chỉ thay `<body>`
  (không tải lại CSS/JS/font) và cập nhật thanh địa chỉ. Tắt JS thì mọi thứ vẫn chạy như web thường.
- Cấu hình trong thẻ `<meta name="htmx-config">` của `base.html`: không eval, không chèn style, không chạy script trong
  nội dung mới (giữ CSP chặt); trang lỗi 403/404 vẫn được hiển thị.
- `static/js/app.js`: sự kiện gắn một lần ở `document` + hàm `init(root)` chạy lại sau mỗi lần thay nội dung.
- Trang có script riêng (bản đồ, quy trình) được tải đầy đủ: `HtmxPageMiddleware` trả `HX-Redirect`.
- Khung trợ lý giữ nguyên khi chuyển trang (`hx-preserve`).

## 10. Ghi chú chuyển đổi MySQL → PostgreSQL

Đặc tả gốc viết cho MySQL. Các điểm đã chuyển sang PostgreSQL mà vẫn giữ nguyên ngữ nghĩa:
- Cột sinh `default_product_id`, `active_registration_id` + UNIQUE ⇒ **UNIQUE có điều kiện** (partial unique index).
- `ON UPDATE CURRENT_TIMESTAMP(6)` ⇒ trigger `fn_set_updated_at`.
- 8 trigger MySQL ⇒ trigger PL/pgSQL báo lỗi bằng mã `ERR-…`; tầng ứng dụng ánh xạ sang thông báo tiếng Việt.
- Thời gian lưu UTC (`timestamptz`), hiển thị giờ Việt Nam.
