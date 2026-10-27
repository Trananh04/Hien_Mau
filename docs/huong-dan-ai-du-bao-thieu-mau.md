# Hướng dẫn huấn luyện AI dự báo thiếu hụt máu — Hien_Mau

Tài liệu đọc trước khi làm. Mọi tên bảng, tên file dưới đây là **tên thật trong code hiện tại** của dự án.

---

## 1. Làm gì, và AI nằm ở đâu

Trang **Kho máu → Dự báo thiếu hụt** đã chạy được ([`bloodbank/services/forecast.py`](../backend/bloodbank/services/forecast.py)).
Nó làm 2 việc:

1. **Dự báo nhu cầu:** mỗi ngày tới, bệnh viện sẽ xuất bao nhiêu đơn vị cho người bệnh, theo từng
   *bệnh viện × nhóm máu × quy cách* (ví dụ: BV Hải Châu · O+ · Khối hồng cầu 350 ml).
   Hiện làm bằng hàm `daily_usage()`: **trung bình lượng xuất 28 ngày gần nhất** — đây là *baseline*.
2. **Tính thiếu hụt:** lấy nhu cầu dự báo, cộng nhu cầu có kế hoạch, so với tồn khả dụng trong 14 ngày →
   xếp mức "sắp thiếu" (< 7 ngày) / "cần lên kế hoạch" (7–14 ngày) → nối sang Gợi ý người hiến, Kêu gọi.

**AI chỉ thay phần 1.** Phần 2 là phép tính nghiệp vụ, giữ nguyên quy tắc để bệnh viện hiểu được vì sao bị
báo thiếu. Giao diện, ngưỡng, gợi ý người hiến dùng chung kết quả nên không phải sửa.

```
stock_txns (lịch sử xuất) ──► [AI dự báo lượng xuất từng ngày, 14 ngày tới] ──┐
demands (nhu cầu có kế hoạch) ───────────────────────────────────────────────┤
stocks / stock_lots (tồn khả dụng, hạn dùng) ──────────────────────────────────┼─► mô phỏng tồn kho từng ngày
request_offers đã chấp thuận / đang giao, lượt hiến chờ xét nghiệm (sắp nhận) ┘     → ngày nào xuống dưới mức tối thiểu
                                                                                     → cảnh báo + gợi ý xử lý
```

> Không dùng Ollama / LLM cho việc này. Dự báo số lượng theo thời gian là bài toán hồi quy chuỗi thời gian —
> mô hình như XGBoost rẻ hơn, nhanh hơn, đo được sai số và giải thích được.

---

## 2. Dữ liệu lấy ở đâu

### 2.1. Dữ liệu đã có sẵn trong Hien_Mau

| Cần cho dự báo | Bảng / trường trong dự án | Ghi chú |
|---|---|---|
| Lượng xuất cho người bệnh theo ngày | `stock_txns` với `txn_type = "issue"`, `occurred_at`, `quantity_change` (âm) | **Nguồn chính để huấn luyện.** Không tính `transfer_out` (điều chuyển liên viện) và `adjustment` |
| Hủy / hết hạn | `stock_txns` `txn_type = "adjustment"`, `adjustment_reason` = `expired`, `damaged`, `quality_failed` | Dùng khi mô phỏng tồn kho |
| Nhập kho | `stock_txns` `txn_type = "receive"` (có `donation` nếu từ lượt hiến) | |
| Tồn hiện tại | `stocks.quantity_on_hand`, `quantity_reserved`, `min_stock_level` | Khả dụng = tồn − giữ chỗ |
| Hạn dùng | `stock_lots.expires_at`, `quantity_on_hand` | Để biết lô nào sẽ hết hạn trong 14 ngày |
| Nhu cầu có kế hoạch | `demands` (ca mổ lên lịch, điều trị định kỳ) | Cộng thêm vào nhu cầu, không cho AI học |
| Nhu cầu chưa đáp ứng | `patient_requests` đã xác minh nhưng chưa xuất đủ | Xem mục 2.3 |
| Máu sắp nhận (chắc chắn) | `request_offers` trạng thái `accepted` / `in_transit` | Chỉ tính nguồn đã xác nhận |
| Máu có thể nhận | `donations` `lab_status = "pending"` | Chưa chắc đạt xét nghiệm → tính riêng, không cộng mặc định |

### 2.2. Dữ liệu hiện có đủ để huấn luyện chưa? — **Chưa**

Kiểm tra DB dev (26/10/2026): `stock_txns` có **398 phiếu trong 56 ngày** (266 xuất, 130 nhập), chỉ **8 dòng tồn**,
và toàn bộ do lệnh `seed_usage_demo` **tự sinh** (mô phỏng 8 tuần cho trang dự báo có số liệu).

Muốn huấn luyện có ý nghĩa cần ít nhất:

- **≥ 6 tháng** liên tục (tốt nhất ≥ 1 năm để thấy Tết, hè, mùa tai nạn) cho mỗi chuỗi cần dự báo;
- nhiều chuỗi (nhiều bệnh viện × nhóm máu × quy cách) để mô hình học chung.

→ **Giai đoạn đồ án: huấn luyện trên dữ liệu mô phỏng**, thiết kế sẵn để khi có dữ liệu thật thì chỉ việc chạy lại.

### 2.3. Bẫy quan trọng: "đã xuất" ≠ "nhu cầu"

Nếu bệnh viện cần 5 đơn vị O− nhưng kho chỉ còn 2 → xuất 2. Nếu AI học từ lượng xuất, nó học rằng nhu cầu là 2,
và **dự báo thấp đúng vào lúc đang thiếu**. Nhu cầu thật nên là:

```
nhu cầu ngày d = lượng xuất cho người bệnh ngày d + lượng đã yêu cầu nhưng chưa đáp ứng ngày d
```

Trong Hien_Mau, phần "chưa đáp ứng" lấy được từ `patient_requests` (đã xác minh, `quantity_units` − số đã xuất
cho yêu cầu đó qua `stock_txns.patient_request`) và yêu cầu liên viện chưa đủ (`hospital_requests` /
`request_offers`). Dữ liệu mô phỏng cũng phải sinh theo cách này: sinh *nhu cầu* trước, rồi mới tính
*xuất được bao nhiêu* tùy tồn kho.

### 2.4. Dữ liệu bên ngoài

| Nguồn | Dùng được gì | Hạn chế |
|---|---|---|
| Bộ "Blood Bank Inventory & Demand" (Kaggle / Database Sample) | Xem cấu trúc, thử pipeline | Giả lập, 60 ngày, nhóm máu châu Âu, tồn kho không khớp với cấp phát |
| Nghiên cứu Việt Nam (vd. tỷ lệ chế phẩm sử dụng tại BV Nguyễn Tri Phương 2021–2023; số đơn vị máu tiếp nhận toàn quốc do Viện Huyết học – Truyền máu TW công bố) | **Tham số cho dữ liệu mô phỏng**: cơ cấu chế phẩm, cơ cấu nhóm máu, quy mô | Chỉ là số tổng hợp, không phải chuỗi theo ngày |
| Dữ liệu bệnh viện thật | Huấn luyện và đánh giá thật | Cần bệnh viện cấp phép, ẩn danh |

> Khi lấy số từ nghiên cứu để đặt tham số mô phỏng, ghi rõ nguồn và năm trong báo cáo. Cơ cấu nhóm máu người
> Việt (O nhiều nhất, rồi B, A, AB; Rh âm rất hiếm) cần đối chiếu số liệu cụ thể từ tài liệu trước khi dùng.

---

## 3. Tạo dữ liệu mô phỏng để huấn luyện

Viết lệnh mới `python manage.py simulate_usage --days 540 --out data/sim/` sinh **file CSV riêng**, không ghi vào
`stock_txns` của DB (sổ kho là chỉ-thêm, không xóa được; trộn dữ liệu giả vào sẽ làm sai sổ kho thật).

Mỗi chuỗi (bệnh viện × nhóm máu × quy cách) sinh theo công thức có thể giải thích:

```
nhu cầu kỳ vọng(d) = mức nền
                     × hệ số thứ trong tuần (Chủ nhật thấp, thứ 2 cao — ca mổ dồn đầu tuần)
                     × xu hướng (tăng/giảm nhẹ theo tháng)
                     × hệ số dịp đặc biệt (Tết, nghỉ lễ dài: giảm ca mổ phiên, tăng tai nạn)
nhu cầu(d)         ~ Poisson(nhu cầu kỳ vọng(d))      + thỉnh thoảng 1 ca lớn (đa chấn thương)
xuất(d)            = min(nhu cầu(d), tồn khả dụng(d))   → phần còn lại là "chưa đáp ứng"
nhập(d)            = theo lịch đợt hiến + lượt hiến đạt xét nghiệm (trễ 1–2 ngày)
hết hạn(d)         = các lô quá hạn (hồng cầu ~35–42 ngày, tiểu cầu ~5 ngày, huyết tương đông lạnh ~1 năm)
```

Nguyên tắc:

- Mỗi file có cột `is_synthetic = 1` và ghi lại **seed + tham số** đã dùng (file `params.json`).
- Mức nền theo quy mô bệnh viện (nhỏ / vừa / lớn) và cơ cấu nhóm máu, chế phẩm lấy từ mục 2.4.
- Thêm nhiễu ngẫu nhiên đủ lớn — nếu dữ liệu quá "sạch", AI nào cũng thắng và kết quả vô nghĩa.

> **Giới hạn phải nói rõ:** mô hình huấn luyện trên dữ liệu mô phỏng chỉ học lại đúng quy luật người mô phỏng đặt
> ra. Kết quả chứng minh **pipeline hoạt động đúng**, không chứng minh độ chính xác trên bệnh viện thật.

---

## 4. Chuẩn bị bảng huấn luyện (mỗi dòng = 1 chuỗi × 1 ngày)

Gom `stock_txns` (hoặc CSV mô phỏng) thành bảng ngày, **lấp ngày không có phiếu bằng 0**:

| Cột | Ví dụ |
|---|---|
| `date` | 2026-10-20 |
| `hospital_id`, `blood_group`, `product_spec_id` | 3, O+, 7 |
| `demand` (mục tiêu = xuất + chưa đáp ứng) | 4 |

**Đặc trưng (features)** — chỉ dùng thông tin có trước ngày cần dự báo:

| Nhóm | Đặc trưng |
|---|---|
| Lịch | thứ trong tuần, ngày trong tháng, tháng, có phải ngày lễ / cận Tết |
| Trễ (lag) | nhu cầu cách đây 1, 7, 14 ngày |
| Trung bình trượt | trung bình 7, 14, 28 ngày; độ lệch chuẩn 28 ngày; số ngày có xuất trong 28 ngày |
| Chuỗi | bệnh viện, nhóm máu, chế phẩm, quy cách (dạng mã), quy mô bệnh viện |

Dự báo 14 ngày: huấn luyện **một mô hình theo "khoảng cách dự báo" h = 1…14 ngày** (dùng đặc trưng tại ngày gốc,
mục tiêu là nhu cầu ngày gốc + h) — đơn giản và không bị dồn sai số như dự báo nối tiếp từng ngày.

---

## 5. Mô hình — luôn so với baseline

| Mô hình | Mô tả | Vai trò |
|---|---|---|
| **B0 — đang dùng** | Trung bình xuất 28 ngày | Mốc phải thắng |
| **B1** | Trung bình theo thứ trong tuần (4 tuần gần nhất) | Baseline mạnh hơn, vẫn giải thích được |
| **XGBoost** | Một mô hình chung cho mọi chuỗi, `objective="count:poisson"` (vì nhu cầu là số đếm, nhiều ngày = 0) | Mô hình AI |

Vì sao **một mô hình chung**: từng chuỗi riêng (vd. O− ở một bệnh viện) quá ít dữ liệu; mô hình chung học được quy
luật dùng chung (thứ trong tuần, Tết) rồi phân biệt chuỗi qua đặc trưng.

Không cần LSTM / Prophet ở giai đoạn này: ít dữ liệu thì mô hình phức tạp dễ học vẹt, khó giải thích.

---

## 6. Đánh giá — phần quan trọng nhất của báo cáo

### 6.1. Chia dữ liệu theo thời gian, không chia ngẫu nhiên

Chia ngẫu nhiên → mô hình "nhìn thấy tương lai" → sai số đẹp giả. Dùng **đánh giá trượt (rolling-origin backtest)**:

```
Lần 1: học [tháng 1 … tháng 9]   → dự báo 14 ngày đầu tháng 10 → đo sai số
Lần 2: học [tháng 1 … 14/10]     → dự báo 14 ngày tiếp theo     → đo sai số
...    (8–12 lần), lấy trung bình
```

### 6.2. Chỉ số

| Chỉ số | Ý nghĩa |
|---|---|
| **MAE** | Sai trung bình bao nhiêu đơn vị / ngày |
| **WAPE** = Σ\|thực − dự báo\| ÷ Σ thực | Sai bao nhiêu % — so sánh được giữa chuỗi lớn và nhỏ |
| **Bias** = Σ(dự báo − thực) ÷ Σ thực | Dự báo thiếu hay thừa có hệ thống (thiếu nguy hiểm hơn thừa) |
| **Phát hiện thiếu** (precision / recall) | Trong những lần *thực tế* xuống dưới mức tối thiểu, hệ thống báo trước được bao nhiêu lần; báo động giả bao nhiêu |

Bảng kết quả trong báo cáo nên có dạng:

| Mô hình | MAE | WAPE | Bias | Recall cảnh báo | Precision cảnh báo |
|---|---|---|---|---|---|
| B0 (TB 28 ngày) | … | … | … | … | … |
| B1 (TB theo thứ) | … | … | … | … | … |
| XGBoost | … | … | … | … | … |

**Quy tắc chọn:** chỉ đưa XGBoost vào chạy thật nếu thắng B1 rõ ràng ở WAPE **và** không làm giảm recall cảnh báo.
Nếu không thắng, ghi đúng như vậy trong báo cáo — đó vẫn là một kết quả hợp lệ.

---

## 7. Tính thiếu hụt: mô phỏng từng ngày, không cộng gộp

Phép tính gộp "tồn 20 + nhận 4 − hết hạn 2 = 22 < nhu cầu 27" bỏ sót trường hợp máu về ngày 6 nhưng thiếu từ ngày 3.
Cách đúng, với mỗi chuỗi và mỗi ngày d = 1…14:

```
tồn(d) = tồn(d−1) + nhận chắc chắn(d) − hết hạn(d) − nhu cầu dự báo(d) − nhu cầu có kế hoạch(d)
ngày thiếu đầu tiên = ngày đầu tiên tồn(d) < mức tối thiểu (min_stock_level, hoặc 0)
thiếu dự kiến       = mức tối thiểu − tồn thấp nhất trong 14 ngày
```

- "Nhận chắc chắn": đề nghị liên viện `accepted` / `in_transit` (theo ngày dự kiến giao).
- Lượt hiến chờ xét nghiệm: hiện riêng "có thể nhận thêm", không cộng mặc định.
- Nên chạy thêm phương án bi quan: dùng cận trên của dự báo (vd. phân vị 80%) để không báo "đủ" quá lạc quan.

---

## 8. Tích hợp vào Hien_Mau

| Thành phần | Việc làm |
|---|---|
| Thư viện | Thêm `pandas`, `xgboost-cpu` vào `requirements.txt` (bản `xgboost` thường kéo thêm thư viện GPU vài trăm MB, không cần) |
| Lệnh tạo dữ liệu | `manage.py simulate_usage` → CSV trong `data/sim/` (mục 3) |
| Lệnh huấn luyện | `manage.py train_forecast [--source db\|csv] [--backtest]` → in bảng mục 6, lưu `models/forecast-YYYYMMDD.json` + `metadata.json` (ngày huấn luyện, nguồn dữ liệu, chỉ số, có phải dữ liệu mô phỏng) |
| Lưu mô hình | Thư mục `models/` nằm trong volume Docker, không commit vào Git |
| Dùng mô hình | `forecast.daily_usage()` → gọi mô hình nếu có file hợp lệ và đủ lịch sử cho chuỗi đó; **không có thì dùng baseline B0** như hiện tại |
| Chạy định kỳ | Dự báo: tính khi mở trang (nhanh, mô hình nhỏ). Huấn luyện lại: hằng tuần trong container `scheduler` |
| Hiển thị | Trang Dự báo thiếu hụt ghi "Dự báo bằng: XGBoost (huấn luyện dd/mm, WAPE x%)" hoặc "Trung bình 28 ngày"; biểu đồ tồn kho dự kiến 14 ngày cho từng dòng |
| Quản trị | Trang cấu hình: bật/tắt dùng mô hình AI (giống công tắc AI của trợ lý) |
| Test | Test với dữ liệu nhỏ cố định: đặc trưng không dùng dữ liệu tương lai, baseline đúng công thức, thiếu mô hình thì quay về baseline, mô phỏng tồn kho từng ngày đúng |

Không cần FastAPI / service riêng: backend đã là Python (Django), gọi mô hình trực tiếp.

---

## 9. Các bước làm và thời gian ước lượng

| # | Việc | Kết quả | Ước lượng |
|---|---|---|---|
| 1 | Viết `simulate_usage` (mục 3) | CSV 18 tháng, nhiều bệnh viện, có nhu cầu chưa đáp ứng | 0,5–1 ngày |
| 2 | Tạo bảng ngày + đặc trưng (mục 4) | Hàm dùng chung cho cả CSV và DB | 0,5 ngày |
| 3 | Baseline B0, B1 + backtest + chỉ số (mục 5–6) | Bảng kết quả baseline | 0,5 ngày |
| 4 | Huấn luyện XGBoost, so sánh | Bảng so sánh đầy đủ | 0,5–1 ngày |
| 5 | Mô phỏng tồn kho từng ngày + nguồn sắp nhận (mục 7) | Thay phép tính gộp trong `forecast.py` | 0,5–1 ngày |
| 6 | Tích hợp vào trang + quay về baseline khi thiếu mô hình (mục 8) | Trang hiện nguồn dự báo, biểu đồ 14 ngày | 1 ngày |
| 7 | Test + viết phần báo cáo | | 0,5–1 ngày |

Nên làm theo đúng thứ tự: **bước 5 có ích ngay cả khi không dùng AI**, và bước 3 phải xong trước bước 4 để có
mốc so sánh.

---

## 10. Viết báo cáo đồ án — nói gì và không nói gì

**Được nói:**
- Hệ thống có pipeline đầy đủ: thu thập từ sổ kho → đặc trưng → huấn luyện → đánh giá trượt theo thời gian → dự báo → cảnh báo.
- Trên dữ liệu mô phỏng (ghi rõ tham số), XGBoost đạt WAPE x% so với y% của baseline.
- Hệ thống tự quay về cách tính đơn giản khi chưa đủ dữ liệu, và bệnh viện thấy được dự báo đến từ đâu.

**Không được nói:**
- "AI dự báo chính xác x% tình trạng thiếu máu tại Việt Nam" — chưa có dữ liệu thật để chứng minh.
- Dùng số liệu nghiên cứu như thể đó là dữ liệu huấn luyện.

**Hướng phát triển:** thu thập ≥ 1 năm dữ liệu thật từ bệnh viện (đã ẩn danh), huấn luyện và đánh giá lại; thêm
yếu tố bên ngoài (lịch nghỉ lễ, mùa dịch sốt xuất huyết — nhu cầu tiểu cầu tăng).

---

## 11. Cần bạn quyết định trước khi làm

1. **Phạm vi dự báo:** chỉ khối hồng cầu (phổ biến nhất, dễ mô phỏng) hay mọi chế phẩm? → Đề xuất: bắt đầu với hồng cầu.
2. **Khoảng dự báo:** giữ 14 ngày như trang hiện tại, hay 7 ngày? → Đề xuất: giữ 14 (đã có ngưỡng 7/14).
3. **Số bệnh viện mô phỏng:** dùng đúng các bệnh viện mẫu đang có (Đà Nẵng, Hà Nội) hay thêm? → Đề xuất: dùng bệnh viện mẫu, gán quy mô nhỏ / vừa / lớn.
4. **Có cần biểu đồ** tồn kho dự kiến 14 ngày trên trang không (thêm khoảng 0,5 ngày)?

---

## 12. Đã làm — cách chạy và kết quả thật (27/10/2026, nhánh `du-bao-ai`)

### Code

| File | Việc |
|---|---|
| `bloodbank/services/forecast_ml/params.py` | Tham số mô phỏng, mỗi số có `source` (hoặc ghi "GIẢ ĐỊNH") |
| `bloodbank/services/forecast_ml/simulate.py` | Sinh nhu cầu theo ngày: quy mô × nhóm máu × thứ × Tết × dao động tháng × xu hướng, Poisson + ca đa chấn thương |
| `bloodbank/services/forecast_ml/features.py` | 13 đặc trưng, dự báo trực tiếp h = 1…14, không dùng dữ liệu sau ngày gốc (có test) |
| `bloodbank/services/forecast_ml/model.py` | XGBoost (`count:poisson`, API gốc, không cần scikit-learn), 2 baseline, backtest trượt, lưu/tải |
| `bloodbank/services/forecast_ml/predict.py` | Dự báo cho dòng tồn kho thật từ sổ kho; chỉ khi bật cấu hình + có mô hình + dòng đủ 28 ngày |
| `bloodbank/services/forecast.py` | Dòng đủ điều kiện dùng dự báo AI từng ngày; còn lại giữ trung bình 28 ngày |
| `templates/hospital/demands.html` | Cột "Dự báo bằng", khung ghi rõ nguồn dữ liệu huấn luyện và sai số |
| `tests/test_forecast_ml.py` | 11 test: tái lập mô phỏng, chống rò rỉ, công thức baseline, lưu/tải, quay về trung bình |

Thư viện thêm: `numpy==2.5.3`, `pandas==3.0.6`, `xgboost-cpu==3.4.1`. Mô hình và dữ liệu mô phỏng nằm ở `backend/var/forecast/` (không commit).

### Cách chạy

```bash
docker compose exec web python manage.py simulate_demand --days 540 --seed 42   # sinh CSV mô phỏng + params.json
docker compose exec web python manage.py train_forecast --backtest              # backtest 12 mốc rồi train bản cuối
# Bật: Quản trị → Cấu hình → forecast_ai_enabled = true  (mặc định tắt)
```

Khi có dữ liệu thật: xuất sổ kho thành CSV (`date, series, blood_group, demand`) rồi `train_forecast --data <file> --backtest`.

### Kết quả backtest trên dữ liệu MÔ PHỎNG (seed 42, 540 ngày, 6 bệnh viện × 8 nhóm máu, 12 mốc × 14 ngày)

| Mô hình | MAE (đơn vị/ngày) | WAPE theo ngày | Bias | WAPE tổng 14 ngày |
|---|---|---|---|---|
| TB 28 ngày (đang dùng) | 0,388 | 55,8% | +0,9% | 17,7% |
| TB cùng thứ | 0,409 | 58,8% | +0,9% | 17,7% |
| **XGBoost** | **0,378** | **54,4%** | −1,7% | **16,4%** |

Đọc kết quả:
- XGBoost thắng cả hai baseline, nhưng **chênh lệch nhỏ** (khoảng 1,3–1,4 điểm %) và thắng ở 8/12 mốc.
- WAPE theo ngày cao (~55%) là bình thường với chuỗi nhỏ: 76% số ngày-chuỗi bằng 0, nhu cầu là số đếm ngẫu nhiên (Poisson) nên
  không mô hình nào đoán đúng từng ngày. Con số có ý nghĩa cho bài toán thiếu máu là **tổng 14 ngày: sai khoảng 16–18%**.
- Bias −1,7%: XGBoost hơi dự báo thiếu — chiều nguy hiểm hơn với kho máu, cần theo dõi khi có dữ liệu thật.
- "TB cùng thứ" thua "TB 28 ngày": hệ số thứ trong tuần mô phỏng nhỏ so với nhiễu, trung bình 4 ngày quá ít mẫu.
- **Giới hạn:** mô hình học lại đúng quy luật mô phỏng đặt ra — kết quả chứng minh pipeline đúng, chưa chứng minh độ chính xác thật.

## 13. Chạy thật (nhánh `du-bao-ai-san-pham`)

**Dữ liệu đầu vào** (`forecast_ml/history.py`, một nguồn cho cả trang Dự báo, dự đoán và huấn luyện):
nhu cầu ngày = phiếu xuất cho người bệnh **không** gắn ca mổ đã khai + số đơn vị yêu cầu người cần máu được xác minh
trong ngày (tính một lần, kể cả phần kho không có). Phiếu xuất có ô **"Ca mổ đã khai"**: chọn ca thì lượng đó không bị
đếm thêm vào "dùng thường ngày"; xuất đủ số đã khai thì ca tự chuyển "Đã đáp ứng"; phần "có kế hoạch" chỉ tính số còn lại.

**Chưa có dữ liệu thật?** `train_forecast` (mặc định `--source auto`) dùng sổ kho khi có ≥ 3 chuỗi đủ 180 ngày, chưa
đủ thì tự dùng dữ liệu mô phỏng. Trang Quản trị → Dự báo AI hiện "Dữ liệu thật: x / 3 chuỗi".

**Phiên bản và chốt chặn:** mỗi lần huấn luyện lưu `var/forecast/versions/<thời điểm>/`. Bản mới chỉ được dùng khi
sai số thấp hơn cả 2 cách đơn giản, không dự báo thiếu quá 5%, và không thay bản dữ liệu thật bằng bản mô phỏng.
Quay lại bản cũ: nút "Dùng bản này" hoặc `train_forecast --activate <phiên bản>`; xem danh sách: `--list`.

**Tự động** (container `scheduler`):
- mỗi ngày lưu dự báo 14 ngày (AI và trung bình 4 tuần) vào bảng `forecast_snapshots`; khi ngày đó qua thì so với thực
  tế → biểu đồ "Sai số thực tế theo tuần";
- mỗi `forecast_retrain_days` ngày (mặc định 7) huấn luyện lại, bỏ qua nếu chưa có dữ liệu thật mà bản đang dùng đã là
  bản mô phỏng. Tắt bằng nút "Tắt tự động"; "Huấn luyện lại ngay" xếp lịch cho lần chạy kế (≤ 5 phút).

Vì sao huấn luyện lại: để tự chuyển sang dữ liệu thật khi đủ, và theo kịp thay đổi nhu cầu. Chốt chặn đảm bảo bản kém
hơn không bao giờ được dùng.
