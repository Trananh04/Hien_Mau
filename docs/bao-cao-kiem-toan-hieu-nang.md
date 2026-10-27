# Báo cáo kiểm toán kiến trúc và hiệu năng — Hiến Máu (Giọt Hồng)

Ngày đo: 27/10/2026 · Nhánh `main` (commit `097f14c`) · Giai đoạn 1: chỉ phân tích, **chưa sửa code**.
Ký hiệu: **[Đo]** = số liệu đo thật trên staging; **[Dự đoán]** = ước tính, cần đo lại sau khi làm.

## 1. Kết luận chính

1. **Nút thắt là truy vấn PostgreSQL, không phải Python hay thiếu cache.** Lúc 25 người dùng đồng thời, DB dùng
   ~12–13 nhân CPU, web chỉ ~2 nhân [Đo]. Hệ thống bão hòa ở **~45 request/giây** [Đo].
2. **Chỉ thêm 4 index** (không đổi code) đã nâng lên **~59 request/giây (+31%)**, p95 lúc 25 người dùng từ 1,6 s xuống
   1,2 s [Đo]. Viết lại 2 truy vấn nóng sẽ giảm thêm (truy vấn lịch sử nhu cầu 59 ms → 9 ms [Đo]).
3. **Chưa cần thêm công nghệ hạ tầng mới** (Redis, Celery, RabbitMQ, Kafka, Elasticsearch, WebSocket, CDN, Load
   Balancer): không có bằng chứng hệ thống đang gặp vấn đề mà chúng giải quyết.
4. Cần làm trước khi chạy thật: index + sửa truy vấn, gửi email ra khỏi luồng request, cache file tĩnh dài hạn,
   cấu hình production riêng (bỏ pgAdmin, có reverse proxy HTTPS), tinh chỉnh PostgreSQL.
5. Nghiệp vụ đúng khi đồng thời: 20 lượt xuất kho cùng lúc trên dòng tồn còn 10 → đúng 10 thành công, tồn = 0 [Đo].

## 2. Kiến trúc hiện tại

```
Trình duyệt (HTML server-render + HTMX + JS thuần, CSP chặt, MapLibre/Goong)
      │ HTTP (chưa có reverse proxy / HTTPS trong compose)
      ▼
gunicorn  3 worker × 8 luồng (gthread)  ── Django 5.2 + WhiteNoise (file tĩnh)
      │        │                         └─ SSE: trợ lý hỏi đáp stream (tối đa 2 câu AI cùng lúc)
      │        └──────────► Ollama (LLM tại chỗ, qwen3 4B)          Goong API (bản đồ, khoảng cách)
      ▼
PostgreSQL 16  ◄── scheduler (manage.py run_jobs, vòng 5 phút: hết hạn yêu cầu, nhắc, dự báo, học lại)
  · dữ liệu nghiệp vụ · phiên đăng nhập · cache (DatabaseCache) · bảng dự báo đã lưu
pgAdmin (công cụ dev)
```

Công nghệ đang dùng: Django 5.2.7, psycopg 3.2, gunicorn 23 (gthread), WhiteNoise 6.11, argon2, ollama-python,
numpy/pandas/xgboost-cpu (dự báo), PostgreSQL 16-alpine, Docker Compose (db, web, scheduler, ollama, pgadmin),
HTMX, Lucide, MapLibre. Mã nguồn ~12 400 dòng Python, 87 template, ~3 900 dòng JS/CSS.

## 3. Phương pháp đo

- **Staging tách biệt:** DB `hien_mau_perf` sao chép từ DB dev bằng `pg_dump` (không đụng DB đang dùng), nhân dữ liệu
  lên quy mô một thành phố: 40 000 người hiến, 1 168 đợt hiến, 43 919 đăng ký, 26 370 lượt hiến, **400 000 phiếu kho**
  (2 năm), 300 000 thông báo, 500 000 nhật ký, 3,1 triệu dòng dự báo đã lưu (1 năm). DB staging: 1,2 GB.
- **Server giống production:** gunicorn riêng cổng 8001, `DEBUG=0`, không `--reload`, 3 worker × 8 luồng (như Dockerfile).
- **Load test:** chỉ GET, client chạy ở container khác (`scheduler`), hỗn hợp 10 trang (khách / người hiến / nhân viên
  bệnh viện), 20 giây mỗi mức 1/10/25/50 người dùng đồng thời.
- **Công cụ:** `CaptureQueriesContext` (đếm truy vấn từng trang), cProfile, `EXPLAIN (ANALYZE, BUFFERS)`, `docker stats`,
  `pg_stat_activity`, `/proc/*/status`. Script và kết quả thô: `backend/var/perf/` (không commit).
- **Giới hạn:** đo trên máy dev 16 nhân (DB, web, client cùng máy); dữ liệu nhân bản có phân bố đơn giản hơn thật
  (vd. nhật ký nhân bản cùng một loại thao tác → kết quả index nhật ký có thể lạc quan). Số tuyệt đối sẽ khác trên máy
  chủ thật; **tỷ lệ trước/sau** là phần đáng tin.

## 4. Số liệu baseline

### 4.1 Từng trang (1 người dùng, staging, chế độ production) [Đo]

Trung vị 76 trang: **12,8 ms**; p90: **66 ms**. Không có N+1 rõ ràng (nhiều nhất 39 truy vấn/trang, không câu nào lặp > 3 lần).

| Trang | Thời gian | Thời gian DB | Truy vấn | Nguyên nhân chính |
|---|---:|---:|---:|---|
| Quản trị → Dự báo AI | **3 092 ms** | 879 ms | 17 | Kéo 733 000 dòng dự báo 12 tuần vào Python để tính sai số |
| Bệnh viện → Lịch sử kho | 308 ms | 289 ms | 12 | Sắp xếp toàn bộ ~171 000 phiếu của bệnh viện để lấy 30 dòng (thiếu index) |
| Bệnh viện → Nhật ký | 163 ms | 148 ms | 12 | Index quét 500 000 dòng rồi lọc bỏ thao tác đăng nhập |
| Bệnh viện → Tổng quan | 140 ms | 105 ms | 39 | Lịch sử nhu cầu lọc bằng ép kiểu ngày (không dùng được index) + đếm quy cách trên toàn bộ lịch sử |
| Bệnh viện → Dự báo thiếu hụt | 122 ms | 90 ms | 21 | Như trên |
| Bệnh viện → Người hiến | 120 ms | 105 ms | 13 | Gộp nhóm toàn bộ lượt hiến để sắp theo lần hiến gần nhất |
| Quản trị → Nhật ký | 90 ms | 71 ms | 8 | Đếm cả bảng nhật ký |

Ở chế độ dev (`DEBUG=1`), ~31% thời gian trang là đọc lại template mỗi request — **chỉ ở dev** (cố ý để sửa template
thấy ngay); production đã có cache template.

### 4.2 Load test [Đo]

| Người dùng đồng thời | Request/giây | p50 | p95 | p99 | Lỗi |
|---:|---:|---:|---:|---:|---:|
| 1 | 8,4 | 27 ms | 325 ms | 1 935 ms* | 0 |
| 10 | 37,6 | 93 ms | 859 ms | 1 377 ms | 0 |
| 25 | **45,3** | 355 ms | 1 596 ms | 2 132 ms | 0 |
| 50 | **45,3** | 927 ms | 2 437 ms | 3 143 ms | 0 |

\* request đầu của mỗi worker nạp numpy/pandas/xgboost.
CPU lúc 25 người dùng: **PostgreSQL 1 216–1 308%**, web 198–236% → DB là nút thắt.
Kết nối DB lúc 50 người dùng: 29 (giới hạn 100). RAM: worker web 159 MB (staging) / 53 MB (dev); RSS ổn định giữa các
lượt tải (458 → 497 MB tổng), không thấy rò rỉ trong thời gian đo.

## 5. Thử nghiệm trên staging (trước / sau) [Đo]

Mỗi truy vấn chạy 5 lần, lấy trung vị thời gian thực thi. Index chỉ tạo trên DB staging.

| Truy vấn | Trước | Sau | Cách |
|---|---:|---:|---|
| 30 phiếu kho mới nhất (Lịch sử kho) | 32,5 ms | **0,1 ms** | index `stock_txns(occurred_at DESC, id DESC)` |
| Nhu cầu 28 ngày — điều kiện hiện tại (ép kiểu ngày) | 59,1 ms | 58,4 ms | index **không giúp** |
| Nhu cầu 28 ngày — lọc theo khoảng thời gian | 38,4 ms | **9,3 ms** | viết lại điều kiện + index `stock_txns(stock_id, occurred_at) WHERE txn_type='issue'` |
| Quy cách xuất nhiều nhất — toàn lịch sử | 30,8 ms | 16,9 ms | index |
| Quy cách xuất nhiều nhất — 90 ngày | 30,3 ms | **2,4 ms** | giới hạn 90 ngày + index |
| Nhật ký bệnh viện (bỏ đăng nhập) | 40,2 ms | **0,07 ms** | index một phần `audit_logs(hospital_id, created_at DESC) WHERE action NOT IN (...)` |
| Đếm nhật ký (quản trị) | 29,5 ms | **0,04 ms** | index một phần tương tự |
| Đếm thông báo chưa đọc | 0,34 ms | 0,35 ms | đã tốt, không cần |
| Dự báo đã lưu 12 tuần (trang quản trị) | 117 ms | 119 ms | index không giúp; cần tính trước mỗi đêm |

Dung lượng index thêm: 12 MB + 7,4 MB (400 000 phiếu kho), 2 index nhật ký rất nhỏ.

Load test lại khi **chỉ thêm index** (code giữ nguyên):

| Người dùng | Request/giây | p95 |
|---:|---:|---:|
| 10 | 37,6 → **49,7** | 859 → 613 ms |
| 25 | 45,3 → **58,3** | 1 596 → 1 175 ms |
| 50 | 45,3 → **59,3** | 2 437 → 2 174 ms |

Lịch sử kho p95 (25 người dùng): 2 466 → 1 199 ms. CPU DB lúc 50 người dùng: ~1 250% → 839%.
Phần còn lại cần sửa code (truy vấn nhu cầu, trang Dự báo AI) nên chưa đo được ở mức trang.

## 6. Phát hiện khác

| # | Phát hiện | Bằng chứng |
|---|---|---|
| F1 | Email khẩn gửi **tuần tự trong luồng request** (`transaction.on_commit` → `send_mail` từng người); quên mật khẩu / xác thực email cũng gửi đồng bộ | Mã: `services/common.py` `alert()`, `accounts/services.py`. SMTP thật ~0,3–2 s/email × số nhân viên → request chậm vài giây, có thể chạm timeout 120 s **[Dự đoán]**. Bảng `notifications` đã có `delivery_status/attempts` (sẵn sàng làm hàng đợi gửi) |
| F2 | File tĩnh chỉ cache 60 giây | Header `Cache-Control: max-age=60` cho `ui.css`, `lucide.min.js` (80 KB gzip)… vì dùng `CompressedStaticFilesStorage` (tên file không có mã băm) [Đo] |
| F3 | Worker web nạp pandas + xgboost dù trang chỉ đọc dự báo đã lưu | Nạp thêm: pandas 33 MB, xgboost 28 MB mỗi worker [Đo]; worker staging 159 MB so với 53 MB |
| F4 | PostgreSQL dùng cấu hình mặc định | `shared_buffers` 128 MB, `work_mem` 4 MB; tỷ lệ trúng bộ đệm 67,6% trên DB 1,2 GB; sắp xếp tràn ra đĩa (2,9 MB) ở truy vấn dự báo [Đo] |
| F5 | `docker-compose.yml` là cấu hình dev (mount mã nguồn, chạy root, `--reload`, pgAdmin mật khẩu mặc định `admin123`, chưa có HTTPS) | File compose. Production phải có cấu hình riêng |
| F6 | Không có polling định kỳ, ô gợi ý địa chỉ có debounce + giới hạn tần suất | `maps.js` (`setTimeout`), `_geo_rate_limited` → không có request trùng đáng kể [Đo bằng đọc mã] |
| F7 | Trợ lý AI giữ 1 luồng gunicorn trong lúc stream | Giới hạn `CHATBOT_MAX_CONCURRENT=2` → tối đa 2/24 luồng bị giữ; câu vượt suất trả lời ngay bằng từ khóa. Đủ an toàn ở quy mô hiện tại |
| F8 | Dự báo đã lưu tăng ~10 000 dòng/ngày ở quy mô 30 bệnh viện | 3,1 triệu dòng/năm với 7 bệnh viện × 88 tổ hợp [Đo]; đã có dọn sau 1 năm; truy vấn có index vẫn nhanh |

## 7. Đánh giá công nghệ

| Công nghệ | Hiện trạng | Vấn đề phát hiện | Bằng chứng / số liệu | Cần dùng? | Phương án thay thế | Ưu tiên | Lợi ích dự kiến | Chi phí & rủi ro | **Kết luận** |
|---|---|---|---|---|---|---|---|---|---|
| **Database indexing** | Có index cơ bản; thiếu index cho các truy vấn nóng | Sort/quét toàn bộ phiếu kho, nhật ký | 32→0,1 ms; 40→0,07 ms; +31% throughput [Đo] | Có | (a) chỉ thêm index; (b) index + viết lại truy vấn | P1 | Throughput +31% [Đo], hơn nữa khi sửa truy vấn [Dự đoán] | ~20 MB/400k phiếu; ghi chậm hơn không đáng kể | **NÊN TRIỂN KHAI** |
| **Tối ưu truy vấn (không thêm công nghệ)** | Lọc ngày bằng ép kiểu; đếm toàn lịch sử; tính sai số dự báo trong Python | Không dùng được index; trang quản trị 3,1 s | 59→9 ms; 31→2,4 ms; 733k dòng/lượt [Đo] | Có | (a) viết lại điều kiện; (b) tính trước mỗi đêm vào bảng nhỏ | P1 | Trang Dự báo AI 3,1 s → < 100 ms [Dự đoán] | Vài giờ code + test | **NÊN TRIỂN KHAI** |
| **PostgreSQL tuning** | Mặc định | Bộ đệm nhỏ, sort tràn đĩa | Trúng bộ đệm 67,6%; `work_mem` 4 MB [Đo] | Có | (a) `shared_buffers` ~25% RAM, `effective_cache_size` ~70%, `work_mem` 16 MB; (b) giữ nguyên | P2 | Giảm I/O và CPU DB [Dự đoán] | Chỉ cấu hình; đặt sai `work_mem` có thể tốn RAM | **CẦN KIỂM CHỨNG THÊM** (đo trên máy chủ thật) |
| **Background worker** | Có: container `scheduler` (`run_jobs` 5 phút) | Email vẫn gửi trong request | Mã `alert()` [Đọc mã] | Có (đã có) | (a) dùng `scheduler` gửi hàng đợi email từ bảng `notifications`; (b) Celery | P1 | Request không chờ SMTP [Dự đoán] | Thấp; email trễ ≤ 1 vòng (có thể rút vòng xuống 30–60 s) | **NÊN TRIỂN KHAI** (dùng cái đang có) |
| **Celery** | Không dùng | Không có tác vụ nặng/khối lượng lớn cần phân tán | Tác vụ định kỳ < 1 s; học lại ~1–2 phút/tháng | Không | `scheduler` hiện tại | — | — | Thêm broker + worker + giám sát | **CHƯA CẦN** |
| **RabbitMQ** | Không dùng | Không có nhu cầu message broker | — | Không | Bảng DB làm hàng đợi | — | — | Thêm dịch vụ cần vận hành | **CHƯA CẦN** |
| **Kafka** | Không dùng | Không có luồng sự kiện khối lượng lớn | Ghi nghiệp vụ vài chục/giây | Không | — | — | — | Rất phức tạp so với quy mô | **CHƯA CẦN** (không phù hợp quy mô) |
| **BullMQ** | Không dùng | Thư viện Node.js, stack là Python | — | Không | — | — | — | Không áp dụng | **CHƯA CẦN** (không áp dụng) |
| **Redis** | Không dùng; cache = DatabaseCache | Cache dùng cho giới hạn tần suất, trạng thái AI, cache bản đồ — ít thao tác | Kết nối 29/100; truy vấn cache ~1 ms; nút thắt ở truy vấn nghiệp vụ, không ở cache [Đo] | Chưa | (a) giữ DatabaseCache; (b) Redis khi có ≥ 2 máy web và lưu lượng giới hạn tần suất lớn | P3 | Nhỏ ở quy mô hiện tại [Dự đoán] | Thêm dịch vụ, bảo mật, sao lưu | **CHƯA CẦN** |
| **Elasticsearch / OpenSearch** | Không dùng; tìm bằng `icontains` (14 chỗ) | Không | Trang quản trị người dùng 40 000 tài khoản: 66 ms [Đo] | Không | (a) giữ nguyên; (b) `pg_trgm` index khi tìm kiếm chậm | P3 | — | Cụm tìm kiếm riêng, đồng bộ dữ liệu | **CHƯA CẦN** |
| **WebSocket** | Không dùng | Không có polling, không cần đẩy 2 chiều | Không có `hx-trigger every` / `setInterval` [Đọc mã] | Không | SSE (đã có) | — | — | Cần ASGI, sticky session | **CHƯA CẦN** |
| **SSE** | Dùng cho stream trả lời trợ lý | Giữ 1 luồng/câu | Tối đa 2 câu AI cùng lúc / 24 luồng | Có | Không stream (chờ trả lời đầy đủ) | — | Trải nghiệm tốt | Thấp | **Giữ nguyên** |
| **CDN** | Không dùng; WhiteNoise phục vụ file tĩnh gzip | Cache trình duyệt chỉ 60 s | Header `max-age=60` [Đo]; tổng file tĩnh 3,9 MB | Chưa | (a) `CompressedManifestStaticFilesStorage` → cache 1 năm; (b) CDN khi người dùng ở xa / lưu lượng lớn | P2 (a) | Giảm request lặp lại file tĩnh [Dự đoán] | (a) gần như không; (b) chi phí, cấu hình | **(a) NÊN TRIỂN KHAI · CDN CHƯA CẦN** |
| **Reverse proxy (Caddy / Nginx)** | Chưa có; gunicorn nhận HTTP trực tiếp | Không có HTTPS trong compose | File compose | Có (khi chạy thật) | Caddy (tự cấp HTTPS) hoặc Nginx | P1 khi triển khai | HTTPS, giới hạn kích thước, đệm client chậm | Thấp | **NÊN TRIỂN KHAI** (lúc lên production) |
| **Load Balancer** | Không | 1 máy web đủ tải | ~45–59 req/s trên 1 máy [Đo] ≫ nhu cầu ước tính 5–10 req/s giờ cao điểm [Dự đoán] | Chưa | Tăng worker theo số nhân CPU trước | P3 | — | Thêm máy, đồng bộ phiên/file | **CHƯA CẦN** |
| **Connection pooling** | `CONN_MAX_AGE=60` (giữ kết nối) | Không | 29 kết nối lúc 50 người dùng / giới hạn 100 [Đo] | Chưa | (a) giữ nguyên; (b) pool sẵn của Django 5.2 (`OPTIONS.pool`) hoặc PgBouncer khi ≥ 3 máy web | P3 | — | PgBouncer thêm 1 dịch vụ | **CHƯA CẦN** |
| **gunicorn gthread 3×8** | Đang dùng | Web không phải nút thắt | Web ~2/16 nhân lúc bão hòa [Đo] | Có | Tăng worker = 2×nhân khi DB đã nhẹ | — | — | — | **Giữ nguyên** |
| **DatabaseCache** | Đang dùng | Không | Bảng cache rất nhỏ | Có | LocMem (không chia sẻ giữa worker → sai giới hạn tần suất) | — | — | — | **Giữ nguyên** |
| **numpy / pandas / xgboost trong web** | Nạp ở mỗi worker | Tốn RAM, trang chỉ đọc kết quả đã lưu | +61 MB/worker [Đo] | Chỉ cần ở scheduler | Nạp chậm (chỉ khi huấn luyện / tính trực tiếp) | P2 | −~180 MB RAM với 3 worker [Dự đoán dựa trên số đo] | Thấp | **NÊN TRIỂN KHAI** (tối ưu code) |
| **Ollama (LLM tại chỗ)** | Container riêng | Tốn RAM/GPU; cần cho yêu cầu dữ liệu không rời máy chủ | Model 4B q4 (~2,5 GB) | Có (theo yêu cầu bảo mật) | Tắt AI → chỉ từ khóa (đã có công tắc) | — | — | Đặt máy có GPU riêng khi mở rộng | **Giữ nguyên** |
| **pgAdmin** | Có trong compose | Công cụ dev, mật khẩu mặc định | 188 MB RAM | Không ở production | Chỉ chạy khi dev (`profiles: [dev]`) | P1 khi triển khai | Giảm bề mặt tấn công | Không | **NÊN LOẠI BỎ** (khỏi production) |
| **Phân vùng bảng (partitioning)** | Không | Dự báo đã lưu ~3 triệu dòng/năm | Truy vấn có index vẫn nhanh; đã dọn sau 1 năm | Chưa | Giữ chính sách dọn | P3 | — | Phức tạp migration | **CHƯA CẦN** |

## 8. Kiến trúc đề xuất cho quy mô hiện tại

```
Internet ── Caddy (HTTPS, nén, cache file tĩnh 1 năm)
              │
              ▼
           gunicorn gthread (worker = 2 × số nhân, 8 luồng) — Django + WhiteNoise
              │   (không nạp pandas/xgboost)
              ▼
           PostgreSQL 16 (đã tinh chỉnh + index mới)  ◄── scheduler: tác vụ định kỳ, gửi email từ hàng đợi,
                                                          dự báo mỗi đêm, học lại khi có lý do
           Ollama (cùng máy hoặc máy có GPU riêng)
```

Không thêm dịch vụ mới ngoài reverse proxy (bắt buộc cho HTTPS). Cấu hình production riêng: không mount mã nguồn, không
`--reload`, chạy user `app`, không pgAdmin, sao lưu DB định kỳ (`pg_dump` theo lịch).

## 9. Lộ trình mở rộng

| Quy mô (ước tính) | Dấu hiệu cần chuyển | Làm gì |
|---|---|---|
| **Hiện tại** — 1 tỉnh/thành, ≤ 50 người dùng đồng thời | — | Mục 8 + giai đoạn 2 dưới đây |
| **100–300 đồng thời** | CPU DB > 70% kéo dài; p95 > 1 s | Tách PostgreSQL sang máy riêng; tăng worker; bật pool kết nối sẵn của Django; theo dõi `pg_stat_statements` |
| **Nhiều tỉnh, ≥ 2 máy web** | 1 máy web không đủ CPU | Load balancer (Caddy/Nginx) + ≥ 2 máy web; PgBouncer; Redis cho cache/giới hạn tần suất/phiên dùng chung; CDN cho file tĩnh |
| **Báo cáo / thống kê nặng** | Truy vấn báo cáo làm chậm nghiệp vụ | Bản sao đọc (read replica) cho báo cáo |
| **Tác vụ nền nhiều, cần thử lại / ưu tiên** | Vòng `scheduler` không kịp, email/SMS số lượng lớn | Lúc đó mới cân nhắc Celery + Redis (broker) |
| **Trợ lý AI nhiều người dùng** | Nhiều câu bị chuyển sang chế độ từ khóa vì hết suất | Máy GPU riêng cho Ollama, tăng `OLLAMA_NUM_PARALLEL` / `CHATBOT_MAX_CONCURRENT` |

## 10. Đề xuất giai đoạn 2 (cần bạn duyệt trước khi sửa code)

| Ưu tiên | Việc | Đo lại bằng |
|---|---|---|
| P1 | Migration 4 index + viết lại lọc ngày trong `forecast_ml/history.py` + giới hạn 90 ngày cho quy cách chính | Load test cùng kịch bản (mục 4.2) |
| P1 | Trang Quản trị → Dự báo AI: tính sai số theo tuần mỗi đêm, trang chỉ đọc | Thời gian trang (hiện 3,1 s) |
| P1 | Gửi email qua hàng đợi `notifications` do `scheduler` xử lý (có thử lại) | Thời gian request có gửi email (với SMTP thật / giả lập trễ) |
| P2 | `CompressedManifestStaticFilesStorage` (cache file tĩnh 1 năm) | Header `Cache-Control` |
| P2 | Không nạp pandas/xgboost ở worker web | RAM worker |
| P2 | `docker-compose.prod.yml`: Caddy HTTPS, bỏ pgAdmin, không `--reload`, tinh chỉnh PostgreSQL | Kiểm tra trên máy chủ thật |

DB staging `hien_mau_perf` (1,2 GB) được giữ lại để đo trước/sau ở giai đoạn 2; xóa được bất cứ lúc nào.

## 11. Kết quả giai đoạn 2 — đã sửa (nhánh `toi-uu-hieu-nang`) [Đo]

Cùng DB staging, cùng kịch bản load test, cùng máy. Đã làm:

| Việc | Thay đổi |
|---|---|
| Index (migration `0015`, `CREATE INDEX CONCURRENTLY` — không khóa ghi khi triển khai) | `stock_txns(occurred_at DESC, id DESC)`; `audit_logs` 2 index một phần khớp đúng bộ lọc tab "Nghiệp vụ" |
| Truy vấn nhu cầu | Lọc theo khoảng thời gian `[00:00, 00:00 hôm sau)` giờ địa phương thay vì ép kiểu ngày → dùng được index sẵn có `(stock, occurred_at, id)`; không cần thêm index phiếu xuất |
| Quy cách xuất nhiều nhất | Xét 90 ngày gần nhất + lưu đệm 1 giờ |
| Trang Quản trị → Dự báo AI | Sai số theo tuần và số chuỗi dữ liệu thật tính 1 lần / ngày ở scheduler (~3 s), trang chỉ đọc; đọc dự báo đã lưu theo khối (không giữ 733 000 dòng trong RAM) |
| Email khẩn | Gửi ở luồng nền sau commit (request không chờ máy chủ mail); hàng đợi = bảng `notifications`; scheduler gửi lại email lỗi / bỏ dở sau 2 phút, tối đa 3 lần; giành dòng bằng UPDATE có điều kiện → không gửi trùng |
| File tĩnh | `bloodbank.storage.StaticStorage` (tên kèm mã băm, bỏ qua sourcemap) → `Cache-Control: max-age=315360000, public, immutable` |
| RAM web | Hằng số mô hình tách sang `forecast_ml/constants.py`; pandas / xgboost chỉ nạp khi huấn luyện hoặc tính trực tiếp |
| Triển khai | `docker-compose.prod.yml` + `Caddyfile` (HTTPS tự động, SSE không gom bộ đệm), không pgAdmin, không `--reload`, PostgreSQL tinh chỉnh qua `PG_*`, volume mô hình; `.dockerignore` bỏ `var/` (trước đây mô hình, script đo và mã phiên staging bị chép vào image); `.gitignore` chặn `.env.*` |

### Từng trang (1 người dùng)

| Trang | Trước | Sau |
|---|---:|---:|
| Quản trị → Dự báo AI | 3 092 ms | **40 ms** |
| Bệnh viện → Lịch sử kho | 308 ms | **42 ms** |
| Bệnh viện → Nhật ký | 163 ms | **24 ms** |
| Bệnh viện → Tổng quan | 140 ms | **79 ms** |
| Bệnh viện → Dự báo thiếu hụt | 122 ms | **59 ms** |
| Quản trị → Nhật ký | 90 ms | **19 ms** |
| p90 (76 trang) | 66 ms | **42 ms** |

### Load test

| Người dùng | Baseline (3×8) | Chỉ thêm index (3×8) | Code mới (3×8) | Code mới, **8×4** |
|---:|---|---|---|---|
| 10 | 37,6 req/s · p95 859 ms | 49,7 · 613 ms | 104,3 · 258 ms | 87,9 · 355 ms |
| 25 | 45,3 · 1 596 ms | 58,3 · 1 175 ms | 70,8 · 1 276 ms | 90,1 · 818 ms |
| 50 | 45,3 · 2 437 ms | 59,3 · 2 174 ms | 75,5 · 2 504 ms | **136,7 · 970 ms** |

Lỗi: 0 ở mọi lượt. CPU lúc 25 người dùng với code mới (3×8): **DB ~2 nhân** (trước 12–13), web ~2,8 nhân = 3 worker × 1 nhân (GIL)
→ nút thắt đã chuyển từ DB sang số tiến trình web; tăng lên 8 worker × 4 luồng: throughput ×3 so với baseline, p95 −60%.
RAM mỗi worker: 159 → **84–87 MB**, không còn nạp pandas / xgboost. Kết nối DB lúc 50 người dùng (8 worker): 33 / 100.
Số ở mức 10 người dùng dao động giữa các lần chạy (client load test cũng là 1 tiến trình Python).

### Còn lại / chưa đo

- Bệnh viện → Người hiến (~120 ms, gộp nhóm toàn bộ lượt hiến) và Quản trị → Người dùng (~65 ms) chưa tối ưu — chưa là
  nút thắt; khi cần: lưu sẵn "lần hiến gần nhất" theo người hiến hoặc giới hạn phạm vi.
- Tinh chỉnh PostgreSQL (`PG_*` trong `docker-compose.prod.yml`) **chưa đo** — cần đo trên máy chủ thật theo RAM thực tế.
- HTTPS / Caddy đã kiểm tra cú pháp (`caddy validate`) và `docker compose config`, chưa chạy với tên miền thật.
