"""Trợ lý hỏi đáp cho Người dùng.

Kiến trúc:
  guard     — chặn trước (khẩn cấp, dữ liệu người khác, mua bán máu, câu lệnh lạ) — không gọi LLM
  tools     — truy vấn dữ liệu THẬT, chỉ đọc, giới hạn theo người đang đăng nhập (dùng chung cho 2 chế độ)
  rules     — chế độ không cần AI: nhận diện ý định bằng từ khóa → tools / kho kiến thức
  llm       — chế độ Claude (khi có ANTHROPIC_API_KEY): hiểu câu hỏi tự do, gọi tools, diễn đạt lại
  knowledge — nội dung đã duyệt (nguồn duy nhất cho câu hỏi kiến thức)
  service   — điểm vào: answer(request, question, lat, lng)
"""
