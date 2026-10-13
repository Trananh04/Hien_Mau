# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: người nhà bệnh nhân cần máu gấp.** Đang ở bệnh viện, căng thẳng, thường dùng điện thoại, có thể vào ban đêm. Việc cần làm: gửi yêu cầu máu (nhóm máu, số đơn vị, tiểu cầu, bệnh viện, khu vực, người liên hệ) nhanh nhất có thể và biết chắc yêu cầu đã được tiếp nhận.
- **Secondary: người hiến máu tình nguyện.** Người dân Đà Nẵng – Quảng Nam muốn đăng ký vào mạng lưới sẵn sàng hiến khi có ca khẩn cấp phù hợp. Việc cần làm: khai báo thông tin, nhóm máu/Rh, khả năng hiến tiểu cầu, và các khu vực có thể đến hiến.

Khi hai nhóm tranh chấp ưu tiên trên trang chủ, người cần máu gấp được ưu tiên.

## Product Purpose

"Ngân Hàng Máu Sống Việt Nam" (khẩu hiệu "Trọn tình người Việt") là một mạng lưới người hiến máu "sống": thay vì máu trong kho, đây là danh sách người hiến sẵn sàng được gọi khi có ca cần. Thành công nghĩa là rút ngắn thời gian từ lúc gia đình bệnh nhân gửi yêu cầu đến lúc có người hiến phù hợp đến bệnh viện.

Đây là **đồ án / dự án học tập**, chưa vận hành thật.

## Positioning

Ghép trực tiếp yêu cầu máu với người hiến theo **nhóm máu + Rh + khu vực địa lý** (theo các cụm quận/huyện Đà Nẵng – Quảng Nam), thay vì kêu gọi chung chung trên mạng xã hội. Có hỗ trợ riêng cho nhóm máu hiếm (Rh-) và hiến tiểu cầu.

## Operating Context

- Người cần máu thường gửi yêu cầu từ bệnh viện, trên điện thoại, trong tình huống khẩn cấp.
- Liên lạc ở Việt Nam chủ yếu qua số điện thoại và Zalo (form người hiến thu cả hai).
- Vùng phục vụ hiện tại: Đà Nẵng (Hải Châu, Thanh Khê, Sơn Trà, Ngũ Hành Sơn, Liên Chiểu, Cẩm Lệ, Hòa Vang) và Quảng Nam, chia theo 7 cụm khu vực trong form tình nguyện viên.
- Quy trình hiến máu 4 bước được mô tả trên trang: đăng ký & khai phiếu → khám sàng lọc → hiến máu (5–10 phút, 250–450ml) → nghỉ ngơi & nhận giấy chứng nhận.

## Capabilities and Constraints

- Stack hiện có: React 19 + TypeScript + Vite, icon lucide-react, font Be Vietnam Pro và Dancing Script (Google Fonts). Ngôn ngữ giao diện: tiếng Việt (`lang="vi"`).
- Trang hiện có: một landing page gồm Navbar, Hero (2 hành động chính: "Đăng ký Tình nguyện viên" và "Tôi cần xin máu"), mục Tin tức, Footer; các modal: đăng ký tình nguyện viên, phiếu yêu cầu máu, chi tiết tin, thông tin (Về chúng tôi / Quy trình / Bảo mật); toast phản hồi.
- **Chưa có backend.** Hai form chỉ giả lập gửi (setTimeout) và hiện toast.
- **Hướng dự kiến:** hệ thống tự động ghép yêu cầu với người hiến theo nhóm máu + khu vực và gửi thông báo cho người hiến. Kênh thông báo, cơ chế xác nhận, và ai duyệt yêu cầu: **chưa quyết định**.
- Thuật ngữ đang dùng: "tình nguyện viên", "người hiến máu", "phiếu yêu cầu máu", "đơn vị máu", "tiểu cầu", "nhóm máu / Rh".

## Brand Commitments

- Tên: "Ngân Hàng Máu Sống Việt Nam"; khẩu hiệu "Trọn tình người Việt".
- Tài sản có sẵn trong `frontend/public/assets/`: logo mark (đỏ và trắng), hình trái tim + giọt máu, họa tiết trống đồng Đông Sơn, nền hero, sóng ribbon, nền footer. Đây là tài sản dựng lại từ một ảnh mockup do AI tạo (xem `frontend/public/assets/README.md`). Bản sắc thị giác **chưa được cam kết** là cố định.

## Evidence on Hand

- Nội dung quy trình hiến máu và chính sách bảo mật: `frontend/src/components/InfoModal.tsx`.
- Tin tức trong `frontend/src/data/newsData.ts` và ảnh `frontend/public/assets/news/*.png` là **nội dung mockup**: ảnh thumbnail nhỏ (~200×88px) cắt từ ảnh AI, sự kiện không có thật.
- **Không có:** số liệu thật (số người hiến, số ca đã cứu), lời chứng thực, đối tác bệnh viện, hay chứng nhận. Không được bịa ra những thứ này. Mọi con số hiển thị phải được ghi rõ là dữ liệu mẫu.

## Product Principles

1. **Khẩn cấp đi trước.** Đường gửi yêu cầu máu phải ngắn, rõ ràng và dùng được bằng một tay trên điện thoại trong lúc hoảng loạn.
2. **Chỉ hỏi thông tin dùng để ghép.** Mỗi trường trong form phải phục vụ việc ghép theo nhóm máu, Rh, tiểu cầu, khu vực, hoặc liên lạc.
3. **Nói thật.** Đây là dự án học tập: không tuyên bố số liệu, đối tác, hay cam kết y tế mà dự án không có.
4. **Tôn trọng dữ liệu sức khỏe.** Nhóm máu và số điện thoại là thông tin nhạy cảm; trang phải nói rõ khi nào và vì sao người hiến bị liên hệ.
5. **Trấn an sau khi gửi.** Người gửi phải biết ngay yêu cầu đã được nhận và bước tiếp theo là gì.

## Accessibility & Inclusion

Người dùng chính đang căng thẳng và thường dùng điện thoại, nên cần chữ dễ đọc, vùng chạm lớn, lỗi form rõ ràng. Hành động chính không được phụ thuộc vào hover (các nút ở Hero hiện đổi chữ khi hover). Chưa có tiêu chuẩn bắt buộc; mặc định hướng tới WCAG 2.1 AA.
