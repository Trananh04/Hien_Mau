# Bộ tài liệu kiến thức của trợ lý (RAG)

Mỗi file `.md` (trừ README) là MỘT tài liệu đã duyệt, có phần đầu (front matter) bắt buộc:

    ---
    id: an-toan            # mã duy nhất, không đổi khi sửa nội dung
    title: Tiêu đề
    source: Tên nguồn / tài liệu gốc
    version: 1.0           # TĂNG khi sửa nội dung
    reviewed: 2026-10-15   # ngày người có chuyên môn duyệt
    keywords: tu khoa khong dau, phan cach bang dau phay
    ---

Quy trình sửa: sửa nội dung → tăng `version` → cập nhật `reviewed` sau khi được duyệt → commit (git giữ lịch sử).
Trợ lý luôn ghi `title` + `version` của tài liệu đã dùng khi trả lời. Biến `{whole}`, `{min_age}`... được thay bằng
giá trị cấu hình hiện hành (Quản trị → Cấu hình).

Nội dung y khoa ở đây là bản tham khảo chung cho dự án; trước khi dùng thật cần cơ sở y tế rà soát theo quy định hiện hành.
