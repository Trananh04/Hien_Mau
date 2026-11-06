# AI gợi ý người hiến máu phù hợp

Tài liệu mô tả chức năng **dự đoán khả năng nhận lời** dùng để xếp hạng danh sách gợi ý người hiến. Nội dung dùng được cho mục **3.2.3.1. Luồng xử lý AI gợi ý người hiến máu phù hợp** của báo cáo.

Code: `backend/bloodbank/services/donor_ml/` · Lệnh huấn luyện: `python manage.py train_donor_model` · Trang quản trị: **Quản trị → AI gợi ý người hiến** (`/quan-tri/goi-y-ai/`).

---

## 1. Bài toán

Khi bệnh viện thiếu một nhóm máu, nhân viên cần biết **nên mời ai trước**. Mỗi lời mời gửi đi đều làm phiền người hiến, và mỗi người chỉ được mời giới hạn số lần, nên mời đúng người quan trọng hơn mời nhiều người.

Bài toán được phát biểu thành **dự đoán khả năng phản hồi** (response prediction):

> Với người hiến *u*, bệnh viện *h*, thời điểm gửi *t*: ước lượng **P(u nhận lời trong 7 ngày sau lời mời)**.

"Nhận lời" là trong `donor_invite_response_days` ngày (mặc định 7) sau lời mời, người đó **đăng ký một đợt hiến của bệnh viện đã mời** (không tự hủy) hoặc **hiến máu tại bệnh viện đó**. Đây cũng là định nghĩa hệ thống dùng để tính tỷ lệ hưởng ứng ở màn hình bệnh viện.

### Vì sao không dùng lọc cộng tác (kiểu gợi ý phim)?

| Lý do | Giải thích |
|---|---|
| Khởi đầu lạnh | Mỗi lời kêu gọi là một "sản phẩm" mới, chưa ai từng phản hồi, nên không có dữ liệu tương tác để so "người giống nhau" |
| Dữ liệu thưa | Một người hiến tối đa khoảng 4 lần mỗi năm, nên ma trận người × lời kêu gọi gần như trống |
| An toàn | Điều kiện hiến (thời gian nghỉ, tuổi) không được để mô hình quyết định |
| Giải thích | Nhân viên y tế cần biết vì sao một người được xếp trên, điều mà lọc cộng tác khó trả lời |

---

## 2. Kiến trúc hai tầng

```
Người dùng cùng tỉnh/thành
   │
   ▼  TẦNG 1 — LUẬT (donor_match.suggest), không bao giờ nới:
   │     đúng nhóm máu (ưu tiên nhóm đã xét nghiệm) · trong độ tuổi hiến · đủ thời gian nghỉ theo loại lần hiến trước
   │     · không nhận lời kêu gọi nào trong thời gian chờ · chưa vượt số lời kêu gọi tối đa trong 90 ngày · trong bán kính
Tập ứng viên an toàn
   │
   ▼  TẦNG 2 — AI (donor_ml.predict): ước lượng khả năng nhận lời → XẾP LẠI thứ tự, giải thích, dành chỗ cho người mới
Danh sách gợi ý (mã ẩn danh) ──► nhân viên chọn ──► hệ thống gửi lời mời (thông báo + email)
```

- AI **chỉ đổi thứ tự**, không thêm và không bớt người; tập ứng viên luôn do luật quyết định. Khi gửi, máy chủ tính lại tập ứng viên bằng luật và chỉ gửi tới mã còn trong tập.
- Khi AI tắt, chưa có mô hình hoặc mô hình bị chốt chặn loại, danh sách xếp theo **chấm điểm luật** như trước (điểm 0–100 có trọng số cố định).
- Nhân viên vẫn chỉ thấy **mã ẩn danh**, không thấy tên hay số điện thoại.

---

## 3. Đặc trưng (features.py)

Tất cả đặc trưng được tính **tại thời điểm gửi lời mời và chỉ dùng dữ liệu có trước thời điểm đó**, để mô hình không "nhìn trước tương lai". Cùng một hàm `features.compute` được dùng cho cả lúc học (thời điểm là lúc gửi lời mời cũ) và lúc dùng (thời điểm là bây giờ), nên lúc học và lúc dùng không bị lệch định nghĩa.

| Đặc trưng | Ý nghĩa |
|---|---|
| `dist_km` | Khoảng cách đường chim bay từ bệnh viện tới nơi hiến gần nhất của người đó (vị trí gần đúng, không dùng địa chỉ nhà) |
| `days_since` | Số ngày từ lần hiến gần nhất |
| `n_donations` | Số lần đã hiến |
| `verified` | Nhóm máu đã có kết quả xét nghiệm |
| `here` | Từng hiến tại bệnh viện này |
| `show_rate`, `appointments` | Tỷ lệ đến đúng hẹn và số lần hẹn trước đây |
| `asked`, `resp_rate` | Số lời kêu gọi trước đây (đã hết thời gian theo dõi) và tỷ lệ đã nhận lời |
| `recent_90d` | Số lời kêu gọi đã nhận trong 90 ngày (mức độ bị làm phiền) |
| `urgent`, `has_campaign`, `weekend`, `hour` | Hoàn cảnh lời mời: khẩn hay thường, có đợt hiến kèm theo, gửi cuối tuần, giờ gửi |

**Không dùng** tuổi, giới tính, nhóm máu làm đặc trưng, để mô hình không ưu tiên hay loại người theo đặc điểm cá nhân. Giá trị chưa có (chưa rõ vị trí, chưa từng được mời…) được giữ là "thiếu": XGBoost tự xử lý, hồi quy logistic điền trung vị và thêm cột "thiếu thông tin".

---

## 4. Dữ liệu học

- **Dữ liệu thật** (`history.py`): mỗi lời mời trong quá khứ là một dòng, gồm đặc trưng tại lúc gửi và nhãn có nhận lời hay không. Chỉ lấy lần kêu gọi **đã hết thời gian theo dõi** (biết chắc kết quả). Chế độ (thiếu kho / khẩn) lấy từ nhật ký gửi kêu gọi.
- **Dữ liệu mô phỏng** (`simulate.py`): dùng khi lịch sử thật chưa đủ (dưới 30 lần kêu gọi hoặc dưới 300 lời mời đã biết kết quả).
  - Thế giới mô phỏng: 5 bệnh viện và 3.000 người hiến. 6 tháng đầu chỉ có hiến tự nguyện, sau đó 18 tháng có kêu gọi.
  - Danh sách mời được chọn giống hệ thống thật: lọc cứng, rồi 60% theo điểm luật và 40% ngẫu nhiên.
  - Xác suất nhận lời có các **tương tác** mà điểm luật cộng dồn không diễn tả được: gần kết hợp cuối tuần; khoảng cách quan trọng hơn khi khẩn; người lâu không hiến khó gọi lại.
  - Mỗi tham số ghi rõ là **giả định**.
- Ở chế độ `auto`, hệ thống tự chuyển sang dữ liệu thật ở lần học lại đầu tiên sau khi đủ.

> ⚠️ Kết quả trong mục 6 là trên **dữ liệu mô phỏng**. Khi trình bày phải ghi rõ, không trình bày như kết quả thực tế.

---

## 5. Mô hình và cách đánh giá (model.py)

Ba cách xếp hạng được chấm trên **cùng các lần kêu gọi**:

| Mã | Cách | Ghi chú |
|---|---|---|
| RULE | Chấm điểm luật hiện tại | Mốc so sánh. Dùng đúng hàm `donor_match.rule_parts` mà màn hình đang dùng (có test bảo đảm hai nơi cho cùng điểm) |
| LR | Hồi quy logistic | Học trọng số cho từng yếu tố. Tự cài bằng numpy (Newton, điều chuẩn L2) |
| XGB | XGBoost (`binary:logistic`) | Học được tương tác giữa các yếu tố; dừng sớm theo 15% dữ liệu cuối (theo thời gian) |

**Backtest theo thời gian:**
- Nửa sau của các lần kêu gọi được chia thành 4 đoạn liên tiếp.
- Mỗi đoạn được dự đoán bởi mô hình **chỉ học từ các lời mời đã biết kết quả trước đoạn đó**, tức gửi trước mốc ít nhất 7 ngày.
- Như vậy mô hình luôn được thử trên dữ liệu "tương lai" mà nó chưa thấy, giống lúc dùng thật.

**Chỉ số:**
- **Nhận lời trong 10 người đầu (p@10)** là chỉ số chính, vì nhân viên chọn người ở đầu danh sách.
- **Số người nhận lời thêm so với chấm điểm luật** trong 10 người đầu mỗi lần kêu gọi, kèm **khoảng tin cậy 95%**. Khoảng tin cậy tính bằng bootstrap theo lần kêu gọi, so cặp trên cùng một lần kêu gọi.
- **AUC:** xác suất một người nhận lời được xếp trên một người không nhận lời.
- **Lệch xác suất** (calibration) = trung bình xác suất dự đoán − tỷ lệ thực tế. Chỉ số này cần gần 0 vì xác suất được dùng để tính số người cần mời.

**Chốt chặn** (`registry.guard`). Mô hình tốt nhất (LR hoặc XGB, theo p@10) chỉ được dùng khi đạt **cả** các điều kiện sau:
1. Phần hơn chấm điểm luật **chắc chắn dương**: cận dưới khoảng tin cậy 95% lớn hơn 0. Không đặt ngưỡng tùy ý.
2. AUC cao hơn chấm điểm luật.
3. Xác suất lệch thực tế không quá ±5%.
4. Có ít nhất 20 lần kêu gọi để kiểm tra.
5. Không thay bản học từ dữ liệu thật bằng bản học từ dữ liệu mô phỏng.

---

## 6. Kết quả (dữ liệu mô phỏng)

556 lần kêu gọi · 13.900 lời mời · tỷ lệ nhận lời 24,0%. Kiểm tra trên 278 lần kêu gọi ở nửa sau.

| Cách xếp hạng | Nhận lời trong 10 người đầu | Người nhận lời / lần | Hơn chấm điểm luật (KTC 95%) | AUC | Lệch xác suất |
|---|---|---|---|---|---|
| Chấm điểm luật | 38,7% | 3,87 | — | 0,710 | — |
| **Hồi quy logistic** | **40,1%** | **4,01** | **+0,14 (+0,03 → +0,26)** | **0,746** | +3,0% |
| XGBoost | 39,1% | 3,91 | +0,04 (−0,08 → +0,17) | 0,733 | +1,4% |

**Nhận xét:**
- Hồi quy logistic **qua chốt chặn**: hơn chấm điểm luật một cách chắc chắn, cả ở 10 người đầu và trên toàn danh sách (AUC 0,746 so với 0,710). Hệ thống chọn LR.
- XGBoost **không hơn** LR. Phần hơn so với luật chưa chắc chắn vì khoảng tin cậy chứa 0. Với lượng dữ liệu này, mô hình đơn giản hơn tổng quát tốt hơn.
- Mức cải thiện **khiêm tốn**: khoảng 0,14 người nhận lời thêm trong 10 người đầu mỗi lần kêu gọi, tức 3,6% tương đối. Nguyên nhân là chấm điểm luật vốn đã dựa trên các yếu tố hợp lý, và yếu tố quan trọng nhất (mức nhiệt tình của từng người) không quan sát được trực tiếp.
- Giá trị lớn hơn của AI là cho **xác suất dùng được** (lệch +3%): biết cần mời bao nhiêu người để đủ số đơn vị thiếu, thay cho một tỷ lệ chung của cả bệnh viện. AI cũng **tự học lại** khi có dữ liệu thật.
- Đây là kết quả trên dữ liệu mô phỏng. Hiệu quả thật phải đo lại khi có lịch sử kêu gọi thật (xem mục 8).

---

## 7. Dùng lúc gợi ý (predict.py)

1. Nhân viên mở **Gợi ý người hiến** cho một nhóm máu đang thiếu. Luật lọc ra tập ứng viên an toàn.
2. Quản trị đã bật `donor_ai_enabled` và có mô hình hợp lệ thì hệ thống tính đặc trưng và khả năng nhận lời cho từng người.
3. Xếp theo khả năng nhận lời, **dành chỗ cho người mới**: cứ khoảng 7 vị trí (`donor_ai_explore_share` = 15%) có một vị trí cho người **chưa có lịch sử hẹn / kêu gọi**. Nếu không có bước này, mô hình chỉ biết về những người đã từng được mời, người mới sẽ không bao giờ được mời, và lượt mời dồn vào một nhóm. Cách chọn cố định, mở lại trang vẫn thấy cùng danh sách.
4. Mỗi người hiện **"Khả năng nhận lời 68%"** và **2–3 yếu tố chính** (▲ tăng / ▼ giảm). Yếu tố chính tính từ đóng góp của từng đặc trưng vào log-odds: hệ số × giá trị với LR, giá trị SHAP với XGBoost. Điểm luật vẫn hiện bên cạnh để đối chiếu.
5. **Số người nên mời**: ít nhất k người đầu danh sách sao cho **tổng khả năng nhận lời ≥ số đơn vị thiếu**, tối đa 50 người. Màn hình ghi "dự kiến khoảng X người nhận lời".
6. Khi gửi, nhật ký lưu **xác suất AI đã dự đoán** cho từng mã, để sau này so với thực tế.

---

## 8. Vận hành và theo dõi (monitor.py, trang quản trị)

| Việc | Cách làm |
|---|---|
| Phiên bản | Mỗi lần huấn luyện lưu một thư mục `var/donor_ai/versions/<phiên bản>/`; quản trị quay lại bản cũ được |
| Theo dõi thật | Theo tuần: số lời mời, số nhận lời; riêng lời mời gửi khi AI xếp hạng thì so **tỷ lệ thực tế** với **tỷ lệ AI dự đoán** |
| Học lại tự động (mỗi đêm 2h–5h) | Chỉ khi có lý do: chưa có mô hình · bản đang dùng học từ mô phỏng mà dữ liệu thật vừa đủ · 4 tuần gần nhất thực tế lệch dự đoán > 10% · đã 30 ngày có dữ liệu mới. Hai lần học lại cách nhau ít nhất 7 ngày |
| Tự bảo vệ | Lệch > 20% (≥ 200 lời mời) thì tự tắt AI, danh sách quay về chấm điểm luật, báo quản trị |
| Cấu hình | `donor_ai_enabled`, `donor_ai_auto_retrain`, `donor_ai_retrain_days`, `donor_ai_explore_share` |

---

## 9. Hạn chế

- Kết quả hiện tại chỉ trên **dữ liệu mô phỏng** với tham số giả định. Mức cải thiện thật chưa được đo.
- Chỉ đánh giá được trên **những người đã được mời**. Không biết người không được mời sẽ phản hồi thế nào; đây là thiên lệch do cách chọn mời. Chỗ dành cho người mới giúp giảm một phần thiên lệch này.
- Vị trí người hiến là **gần đúng** (nơi hiến gần nhất), không dùng địa chỉ nhà vì lý do riêng tư.
- Mô hình dự đoán **đăng ký hoặc đến hiến**, không dự đoán người đó có đủ điều kiện sức khỏe. Việc đó vẫn do bác sĩ khám sàng lọc.

---

## 10. Cách chạy

```bash
# Huấn luyện (tự chọn dữ liệu thật nếu đủ, chưa đủ thì mô phỏng); bản mới chỉ được dùng khi qua chốt chặn
docker compose exec web python manage.py train_donor_model

# Xem các phiên bản / quay lại bản cũ
docker compose exec web python manage.py train_donor_model --list
docker compose exec web python manage.py train_donor_model --activate 20261104-090000
```

Sau khi có mô hình, vào **Quản trị → AI gợi ý người hiến** và bấm **Bật AI**.
