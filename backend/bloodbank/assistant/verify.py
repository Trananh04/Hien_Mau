"""Kiểm tra câu trả lời của AI trước khi gửi người dùng (bước "AI tổng hợp và KIỂM TRA").

1. Mã tham chiếu (DK-…, PR-…, LH-…) trong câu trả lời phải xuất hiện trong dữ liệu thật đã tra cứu
   (kết quả công cụ / tài liệu) — có mã lạ → coi như bịa → dùng câu trả lời của chế độ từ khóa.
2. Câu trả lời lẫn chữ Hán / Kana / Hangul (mô hình nhỏ đôi khi chen tiếng Trung) → không dùng.
3. Câu khẳng định "đủ điều kiện / chắc chắn hiến được" → luôn kèm nhắc bác sĩ khám sàng lọc quyết định.
"""
import re

from bloodbank.content import _norm

CODE = re.compile(r"\b(?:DK-\d{6}|LH-\d{6}|PR-\d{8}-\d{4})\b")
FOREIGN_SCRIPT = re.compile("[぀-ヿ㐀-䶿一-鿿가-힯]")
OVERCLAIM = ["ban du dieu kien hien", "ban hoan toan co the hien", "chac chan hien duoc", "ban hien duoc",
             "ban co the hien mau binh thuong", "ban du tieu chuan"]
DISCLAIMER = "Lưu ý: đây chỉ là thông tin sơ bộ — bác sĩ khám sàng lọc tại điểm hiến sẽ quyết định bạn có hiến được không."


class Unverified(Exception):
    pass


def check(answer, evidence, remind_doctor=False):
    """evidence: chuỗi chứa toàn bộ dữ liệu đã đưa cho AI. Trả về câu trả lời (có thể đã bổ sung lưu ý).
    remind_doctor: câu trả lời về điều kiện / ngày được hiến → luôn có lời nhắc bác sĩ khám sàng lọc quyết định."""
    unknown = sorted({c for c in CODE.findall(answer) if c not in evidence})
    if unknown:
        raise Unverified(f"mã không có trong dữ liệu: {unknown}")
    if FOREIGN_SCRIPT.search(answer):
        raise Unverified("câu trả lời lẫn chữ không phải tiếng Việt")
    if (remind_doctor or any(p in _norm(answer) for p in OVERCLAIM)) and "bac si" not in _norm(answer):
        answer = answer.rstrip() + "\n\n" + DISCLAIMER
    return answer
