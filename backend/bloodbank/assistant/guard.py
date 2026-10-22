"""Chặn trước — trả lời mẫu, KHÔNG gọi LLM. Áp dụng cho cả 2 chế độ.

Thứ tự ưu tiên: khẩn cấp → dữ liệu người khác → mua bán máu → câu lệnh dò quy tắc → hỏi y khoa cá nhân.
Hỏi "khi nào tôi được hiến lại" là hỏi ngày (công cụ trả lời được), KHÔNG coi là câu hỏi y khoa.
"""
from django.urls import reverse

from bloodbank.content import _norm

EMERGENCY = ["cap cuu", "mat mau nhieu", "nguy kich", "dang chay mau", "bat tinh", "hon me", "nguy hiem tinh mang",
             "can mau gap ngay", "sap chet"]
OTHERS_DATA = ["so dien thoai cua", "sdt cua", "dia chi cua", "danh sach nguoi hien", "danh sach nguoi dung",
               "liet ke nguoi", "thong tin nguoi khac", "tat ca nguoi dung", "don cua nguoi khac", "email cua",
               "ai co nhom mau", "nguoi nao co nhom"]
TRADE = ["ban mau", "mua mau", "tra tien", "bao nhieu tien mot", "gia mot tui", "kiem tien"]
INJECTION = ["bo qua huong dan", "bo qua cac huong dan", "bo qua quy tac", "ignore previous", "ignore all",
             "system prompt", "lo prompt", "dong vai quan tri", "ban la admin", "che do nha phat trien"]
# Câu hỏi về bệnh, thuốc, tình trạng sức khỏe CỤ THỂ của người hỏi → không kết luận
CLINICAL = ["bi benh", "co benh", "benh nen", "uong thuoc", "dung thuoc", "dang dieu tri", "mang thai", "cho con bu",
            "huyet ap", "viem gan", "hiv", "tieu duong", "chan doan", "trieu chung", "bi sot", "cam cum",
            "ket qua xet nghiem", "thieu mau", "hbsag", "tim mach", "ung thu", "phau thuat", "xam hinh"]
CLINICAL_CONTEXT = ["hien", "duoc khong", "co sao", "nguy hiem", "anh huong", "co nen"]


def _has(q, words):
    return any(w in q for w in words)


def check(question):
    """Trả về dict câu trả lời mẫu nếu cần chặn, None nếu cho đi tiếp."""
    q = _norm(question or "")
    if _has(q, EMERGENCY):
        return {"answer": "Nếu đang có người nguy kịch, hãy gọi ngay 115 hoặc báo bác sĩ đang điều trị, đừng chờ "
                          "trên ứng dụng. Khi bệnh nhân đã được điều trị tại bệnh viện, người nhà có thể gửi yêu cầu "
                          "cần máu để bệnh viện điều phối nguồn máu.",
                "links": [{"label": "Gửi yêu cầu cần máu", "url": reverse("bloodbank:patient_request_new")}],
                "source": "Quy tắc an toàn của trợ lý", "intent": "emergency"}
    if _has(q, OTHERS_DATA):
        return {"answer": "Mình không thể cung cấp thông tin của người khác (tên, số điện thoại, nhóm máu, đơn đăng ký). "
                          "Dữ liệu cá nhân chỉ người có quyền xem được. Nếu cần máu, hãy gửi yêu cầu để bệnh viện "
                          "điều trị xác minh và điều phối.",
                "links": [{"label": "Gửi yêu cầu cần máu", "url": reverse("bloodbank:patient_request_new")}],
                "source": "Chính sách bảo mật thông tin", "intent": "privacy"}
    if _has(q, TRADE):
        return {"answer": "Hiến máu là tình nguyện, không mua bán. Nền tảng không hỗ trợ trao đổi máu lấy tiền. "
                          "Nếu người nhà cần máu, hãy gửi yêu cầu để bệnh viện điều trị xử lý.",
                "links": [{"label": "Gửi yêu cầu cần máu", "url": reverse("bloodbank:patient_request_new")}],
                "source": "Quy tắc an toàn của trợ lý", "intent": "trade"}
    if _has(q, INJECTION):
        return {"answer": "Mình chỉ hỗ trợ các câu hỏi về hiến máu và cách dùng nền tảng. Quyền truy cập dữ liệu do hệ "
                          "thống kiểm soát, không thay đổi theo lời nhắn.",
                "source": "Quy tắc an toàn của trợ lý", "intent": "injection"}
    if _has(q, CLINICAL) and _has(q, CLINICAL_CONTEXT):
        return {"answer": "Mình không thể kết luận về sức khỏe hay việc bạn có hiến được không khi có bệnh/thuốc/tình "
                          "trạng cụ thể. Bác sĩ tại điểm hiến sẽ khám sàng lọc và quyết định. Nếu có vấn đề sức khỏe, "
                          "hãy hỏi trực tiếp bác sĩ hoặc cơ sở y tế.",
                "source": "Quy tắc BR-20 (không kết luận lâm sàng)", "intent": "clinical"}
    return None
