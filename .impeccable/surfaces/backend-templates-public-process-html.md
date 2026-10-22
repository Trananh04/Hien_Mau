---
version: 1
slug: "backend-templates-public-process-html"
primary_target: "backend/templates/public/process.html"
related_targets: []
---

## Scope
Trang công khai "Quy trình tham gia hiến máu" (/quy-trinh-hien-mau/). Mode: Read. Thay hộp thoại info-process. Kế thừa thế giới thị giác hiện có (đỏ #d90429, Be Vietnam Pro, họa tiết trống đồng); không đổi DESIGN.

## Audience & job
Người lần đầu hiến máu muốn biết một buổi hiến diễn ra thế nào, mất bao lâu, cần chuẩn bị gì, sau đó làm gì — để bớt lo và đăng ký đợt hiến. Nguồn nội dung: kb/quy-trinh, chuan-bi, sau-khi-hien, dieu-kien-chung, khoang-cach, the-tich, an-toan; số liệu điều kiện lấy từ SystemSetting.

## Direction contract
THESIS: Một buổi hiến máu kể theo đồng hồ — ~60 phút, 4 chặng đặt trên trục thời gian.
FIRST VIEWPORT: Tiêu đề "Một buổi hiến máu của bạn", lời hứa "khoảng 30–60 phút", 4 mốc chặng và đồng hồ vẽ tay: kim giọt máu chạy một vòng 60', tô 4 cung chặng.
VISITOR PATH: Trục thời gian 4 chặng (hình vẽ SVG, bạn làm / nhân viên y tế làm / mẹo) → Trước ngày hiến → Sau khi hiến → Câu hỏi thường gặp. Không breadcrumb, không khối kêu gọi cuối trang (người dùng yêu cầu bỏ).
SIGNATURE INTERACTION: Cuộn trang làm ống thời gian đầy dần màu máu, giọt máu chạy theo, đồng hồ dính đầu trang đếm phút; hình vẽ mỗi chặng hé lộ và tự kể việc của chặng (đánh dấu phiếu, kim huyết áp, túi máu đầy, đóng dấu chứng nhận).
CROSS-SURFACE REACH: Menu/footer "Quy trình tham gia" trỏ tới trang; số liệu đồng bộ với trợ lý.
HONEST RISK: Hình vẽ phẳng tự làm — đơn giản hơn ảnh thật; mốc phút là ước tính, ghi rõ trên trang.
