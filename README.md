# Hiến Máu — Ngân Hàng Máu Sống Việt Nam

Hệ thống kết nối người hiến máu, người nhà bệnh nhân cần máu và các bệnh viện: đăng ký đợt hiến, ghi nhận lượt hiến,
quản lý kho máu, điều phối máu giữa các bệnh viện và xử lý yêu cầu cần máu.

- **Backend:** Django 5.2 · PostgreSQL 16 · pgAdmin 4 · tác vụ định kỳ (scheduler), chạy toàn bộ bằng Docker
- **Giao diện:** cùng phông chữ (Be Vietnam Pro, Dancing Script), màu và bộ icon Lucide với trang chủ React trong `frontend/`
- **Đặc tả:** BLOOD-SRS-001 v1.1 (*Tài liệu thiết kế CSDL hiến máu*)

> Dự án học tập. Mọi bệnh viện, người dùng, tin tức và số liệu đều là **dữ liệu mẫu**.

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
| **Nhân viên bệnh viện** | http://localhost:8080/benh-vien/dang-nhap/ | `benhvien1@hienmau.vn` … `benhvien5@hienmau.vn` |
| **Quản trị hệ thống** | http://localhost:8080/quan-tri/dang-nhap/ | `admin@hienmau.vn` |

- `benhvien1@hienmau.vn` làm việc ở 2 bệnh viện nên có bộ chọn bệnh viện trên thanh bên trái.
- Đăng nhập sai cổng sẽ bị từ chối, kèm link sang đúng cổng.
- Người dùng tự đăng ký tại `/dang-ky/`. Tài khoản nhân viên bệnh viện do Quản trị hệ thống cấp tại **Quản trị → Bệnh viện → Cấp tài khoản**.
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
| **Huy hiệu người hiến** | Trang Lịch sử hiến: huy hiệu theo mốc 1/3/5/10/20/30 lần hiến được xác nhận (hủy hiệu lực thì tự mất), ngày có thể hiến lại và đợt hiến gần nhất. Tác vụ định kỳ nhắc một lần khi đã đủ thời gian nghỉ. Không có bảng xếp hạng. |

Mọi ngưỡng (số ngày, số phút, số giờ) chỉnh tại **Quản trị → Cấu hình**. Email ở môi trường dev in ra log `web` / `scheduler`.

## 6. Kiểm thử

```bash
docker compose run --rm --no-deps web python manage.py test bloodbank.tests
```

Bộ test (115 test) chạy trên PostgreSQL thật, gồm:
- ràng buộc CSDL (CHECK / UNIQUE / trigger),
- các luồng nghiệp vụ qua HTTP (đợt hiến, điểm hiến, kho, điều phối liên viện, yêu cầu cần máu),
- phân quyền: mọi đường dẫn × mọi vai trò, 3 cổng đăng nhập,
- các luồng tự động hóa ở mục 5a,
- smoke test mở mọi màn hình với từng vai trò trên dữ liệu mẫu,
- test hồi quy cho các lỗi tìm được trong đợt QA audit (`test_qa_audit.py`, xem `qa-audit/`).

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
                            lab (xét nghiệm → kho), jobs (tác vụ định kỳ), callout (kêu gọi người hiến),
                            badges (huy hiệu)
    views/                  public · member · hospital_* · admin
    management/commands/    seed_demo (dữ liệu mẫu) · run_jobs (tác vụ định kỳ)
    tests/                  bộ kiểm thử
  templates/                giao diện (công khai / cá nhân / khu làm việc bệnh viện, quản trị)
  static/                   css (site.css = CSS trang chủ React, ui.css), js, ảnh, thư viện vendor
frontend/                   trang chủ React gốc (Vite), tham chiếu thiết kế
```

### Chạy trang chủ React gốc (không bắt buộc)

```bash
cd frontend
npm install
npm run dev
```

## 10. Ghi chú chuyển đổi MySQL → PostgreSQL

Đặc tả gốc viết cho MySQL. Các điểm đã chuyển sang PostgreSQL mà vẫn giữ nguyên ngữ nghĩa:
- Cột sinh `default_product_id`, `active_registration_id` + UNIQUE ⇒ **UNIQUE có điều kiện** (partial unique index).
- `ON UPDATE CURRENT_TIMESTAMP(6)` ⇒ trigger `fn_set_updated_at`.
- 8 trigger MySQL ⇒ trigger PL/pgSQL báo lỗi bằng mã `ERR-…`; tầng ứng dụng ánh xạ sang thông báo tiếng Việt.
- Thời gian lưu UTC (`timestamptz`), hiển thị giờ Việt Nam.
