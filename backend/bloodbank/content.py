"""Nội dung tĩnh: tin tức (nội dung mockup chuyển từ frontend/src/data/newsData.ts) và kho câu trả lời chatbot đã duyệt."""
import re
import unicodedata

NEWS = [
    {
        "id": 1, "date": "22/06/2026", "category": "su-kien",
        "title": "Đà Nẵng ngày càng có nhiều người tham gia hiến máu tình nguyện",
        "excerpt": "Chiều 22/6, tại Đà Nẵng, Ban Chỉ đạo vận động hiến máu tình nguyện thành phố Đà Nẵng tổ chức Lễ tôn vinh, khen thưởng phong trào hiến máu tình nguyện thành phố Đà Nẵng năm 2024.",
        "image": "/static/assets/news/01-hospital-blood-donation.png",
        "fullContent": "Chiều 22/6, tại Đà Nẵng, Ban Chỉ đạo vận động hiến máu tình nguyện thành phố Đà Nẵng đã trang trọng tổ chức Lễ tôn vinh, khen thưởng các tập thể, cá nhân và gia đình tiêu biểu trong phong trào hiến máu tình nguyện thành phố Đà Nẵng. Phong trào ngày càng lan tỏa mạnh mẽ, thu hút đông đảo các tầng lớp nhân dân nhiệt tình hưởng ứng tham gia, góp phần quan trọng vào sự nghiệp chăm sóc và bảo vệ sức khỏe nhân dân.",
    },
    {
        "id": 2, "date": "29/12/2025", "category": "su-kien",
        "title": "Công an TP Đà Nẵng tổ chức hiến máu tình nguyện đợt 3, thu hơn 400 đơn vị máu",
        "excerpt": "Sáng 29/12, Công an TP Đà Nẵng phối hợp Khoa Huyết học Bệnh viện Đà Nẵng tổ chức Chương trình Hiến máu tình nguyện đợt 3 năm 2023 với chủ đề 'Giọt máu hồng người chiến sĩ'.",
        "image": "/static/assets/news/02-volunteers-in-red.png",
        "fullContent": "Sáng 29/12, Công an TP Đà Nẵng phối hợp cùng Khoa Huyết học - Truyền máu Bệnh viện Đà Nẵng tổ chức Chương trình Hiến máu tình nguyện đợt 3 với chủ đề 'Giọt máu hồng người chiến sĩ'. Đông đảo cán bộ, chiến sĩ công an từ các đơn vị nghiệp vụ đã hăng hái tham gia, đóng góp hơn 400 đơn vị máu an toàn vào ngân hàng máu dự trữ của thành phố.",
    },
    {
        "id": 3, "date": "15/10/2026", "category": "khan-cap",
        "title": "03 CBCS Phòng Cảnh sát PCCC và CNCH Công an TP Đà Nẵng đến tận bệnh viện hiến máu cứu người",
        "excerpt": "Ngay sau khi nhận được tin báo có bệnh nhân đang điều trị tại Bệnh viện đa khoa khu vực Quảng Nam đang cần gấp 03 đơn vị máu nhóm O, 03 CBCS Phòng Cảnh sát PCCC và CNCH Công an TP Đà Nẵng đã xung phong đến tận bệnh viện để hiến máu cứu bệnh nhân vượt qua cơn nguy kịch...",
        "image": "/static/assets/news/03-donation-close-up.png",
        "fullContent": "Ngay sau khi nhận được tin báo có bệnh nhân nặng đang điều trị tại Bệnh viện đa khoa khu vực Quảng Nam cần truyền gấp 03 đơn vị máu nhóm O để phẫu thuật khẩn cấp, 03 cán bộ chiến sĩ thuộc Phòng Cảnh sát PCCC và CNCH Công an TP Đà Nẵng đã lập tức xung phong đến tận bệnh viện, trực tiếp hiến máu giúp bệnh nhân qua cơn nguy kịch. Nghĩa cử cao đẹp này đã nhận được sự cảm phục sâu sắc từ gia đình bệnh nhân và y bác sĩ.",
    },
    {
        "id": 4, "date": "18/01/2026", "category": "su-kien",
        "title": "Hơn 1.000 thanh niên Đà Nẵng hiến máu tình nguyện trong ngày 'Chủ Nhật Đỏ'",
        "excerpt": "Sự kiện hiến máu tình nguyện 'Chủ Nhật Đỏ' đã thu hút hơn 2.000 sinh viên và cán bộ giảng viên tham gia, tiếp nhận gần 1.500 đơn vị máu an toàn.",
        "image": "/static/assets/news/04-blood-storage-bags.png",
        "fullContent": "Chương trình 'Chủ Nhật Đỏ' lần thứ XVI với thông điệp 'Hiến máu cứu người - Sinh mệnh của bạn và tôi' đã diễn ra sôi nổi tại Đà Nẵng. Sự kiện thu hút hơn 2.000 đoàn viên, thanh niên, sinh viên và cán bộ giảng viên các trường đại học tham gia, tiếp nhận gần 1.500 đơn vị máu quý giá phục vụ cấp cứu dịp đầu năm mới.",
    },
    {
        "id": 5, "date": "10/09/2026", "category": "khan-cap",
        "title": "Bệnh viện Đa khoa Tam Kỳ kêu gọi khẩn cấp nhóm máu A và O cho các ca mổ tim",
        "excerpt": "Do nhu cầu phẫu thuật tim mạch tăng đột biến, lượng máu dự trữ nhóm A và O tại Bệnh viện Đa khoa Quảng Nam (Tam Kỳ) đang ở mức báo động. Rất cần sự chung tay của cộng đồng.",
        "image": "/static/assets/news/05-hands-red-heart.png",
        "fullContent": "Do nhu cầu phẫu thuật tim mạch và điều trị hồi sức cấp cứu tăng cao đột biến, lượng máu dự trữ nhóm A và nhóm O tại Bệnh viện Đa khoa Quảng Nam (Tam Kỳ) đang ở mức báo động đỏ. Ban giám đốc bệnh viện tha thiết kêu gọi các tình nguyện viên, người dân có đủ điều kiện sức khỏe đến tham gia hiến máu để hỗ trợ kịp thời cho các bệnh nhân hiểm nghèo.",
    },
    {
        "id": 6, "date": "12/08/2026", "category": "su-kien",
        "title": "Công an Đà Nẵng tổ chức ngày hội 'Giọt hồng người chiến sĩ'",
        "excerpt": "Sáng 12/8, Công an thành phố Đà Nẵng tổ chức Ngày hội hiến máu tình nguyện 'Giọt hồng người chiến sĩ' năm 2025. Chương trình đã tiếp nhận khoảng 500 đơn vị máu từ cán bộ, chiến sĩ, đoàn viên thanh niên công an các đơn vị trực thuộc Công an thành phố và công an các xã, phường.",
        "image": "/static/assets/news/06-volunteer-event.png",
        "fullContent": "Sáng 12/8, Công an thành phố Đà Nẵng tổ chức Ngày hội hiến máu tình nguyện 'Giọt hồng người chiến sĩ' năm 2025. Chương trình tiếp nhận khoảng 500 đơn vị máu từ cán bộ, chiến sĩ, đoàn viên thanh niên công an các đơn vị trực thuộc Công an thành phố và công an các xã, phường, thể hiện tinh thần xung kích vì cộng đồng.",
    },
    {
        "id": 7, "date": "05/08/2026", "category": "chia-se",
        "title": "Hiến máu an toàn và sức khỏe cộng đồng",
        "excerpt": "Tuân thủ quy trình, đảm bảo an toàn cho người hiến máu và người nhận máu. Những quy định và hướng dẫn y tế cần ghi nhớ trước khi tham gia hiến máu.",
        "image": "/static/assets/news/07-safe-donation.png",
        "fullContent": "Các chuyên gia y tế khuyến cáo người tham gia hiến máu cần tuân thủ đầy đủ các nguyên tắc sức khỏe: ngủ đủ giấc đêm trước ngày hiến máu, ăn nhẹ trước khi hiến (không ăn đồ nhiều dầu mỡ), uống nhiều nước, và tránh sử dụng chất kích thích. Quy trình lấy máu hoàn toàn khép kín, sử dụng dụng cụ vô trùng một lần, tuyệt đối an toàn cho sức khỏe người hiến.",
    },
]

# --------------------------------------------------------------------------
# Chatbot (UC-BOT-01): chỉ trả lời từ nội dung đã kiểm duyệt, từ chối kết luận lâm sàng (BR-20)
# --------------------------------------------------------------------------
FAQ = [
    {
        "keys": ["quy trinh", "may buoc", "cac buoc", "dien ra the nao", "hien mau nhu the nao"],
        "answer": "Quy trình gồm 4 bước:\n1. Đăng ký & điền phiếu thông tin.\n2. Khám sức khỏe sàng lọc (huyết áp, khám lâm sàng, xét nghiệm nhanh nhóm máu và huyết sắc tố).\n3. Tiến hành hiến máu: 5–10 phút, thể tích 250–450 ml.\n4. Nghỉ ngơi 15–20 phút và nhận giấy chứng nhận.",
        "source": "Quy trình tham gia hiến máu tình nguyện",
    },
    {
        "keys": ["chuan bi", "truoc khi hien", "an gi", "ngu", "uong nuoc"],
        "answer": "Trước ngày hiến: ngủ đủ giấc, ăn nhẹ (tránh đồ nhiều dầu mỡ), uống nhiều nước và tránh chất kích thích. Mang theo giấy tờ tùy thân. Nhân viên y tế sẽ khám sàng lọc và quyết định bạn có hiến được trong ngày hay không.",
        "source": "Tin: Hiến máu an toàn và sức khỏe cộng đồng",
    },
    {
        "keys": ["dang ky hien", "dang ky dot", "tham gia dot", "dang ky tinh nguyen", "lam sao dang ky"],
        "answer": "Vào mục \"Đợt hiến máu\", chọn đợt đang nhận đăng ký rồi bấm \"Đăng ký tham gia\" (cần đăng nhập). Đơn ở trạng thái Chờ duyệt cho tới khi bệnh viện xác nhận; bạn theo dõi trong mục \"Đơn đăng ký hiến\".",
        "source": "Hướng dẫn sử dụng nền tảng",
    },
    {
        "keys": ["can mau", "xin mau", "yeu cau mau", "nguoi nha", "benh nhan can"],
        "answer": "Bấm \"Tôi cần xin máu\" ở trang chủ (cần đăng nhập), điền bệnh viện đang điều trị, số đơn vị cần và thông tin liên hệ rồi gửi. Bạn nhận ngay mã yêu cầu (PR-…). Bệnh viện điều trị sẽ xác minh trước khi điều phối; theo dõi trạng thái trong mục \"Yêu cầu cần máu\".",
        "source": "Hướng dẫn sử dụng nền tảng",
    },
    {
        "keys": ["lich su", "so lan hien", "da hien bao nhieu", "tong ml"],
        "answer": "Mục \"Lịch sử hiến máu\" chỉ tính các lượt hiến đã được bệnh viện xác nhận. Đơn đăng ký chưa được tính là đã hiến. Máu toàn phần (ml) và hiến thành phần được thống kê riêng.",
        "source": "Hướng dẫn sử dụng nền tảng",
    },
    {
        "keys": ["bao mat", "du lieu", "thong tin ca nhan", "rieng tu"],
        "answer": "Nhóm máu và số điện thoại chỉ hiển thị cho người có quyền; tên bệnh nhân chỉ bệnh viện điều trị được xem, và mỗi lần xem dữ liệu nhạy cảm đều được ghi nhật ký. Thông tin không được chia sẻ cho bên thứ ba vì mục đích thương mại.",
        "source": "Chính sách bảo mật thông tin",
    },
    {
        "keys": ["the tich", "bao nhieu ml", "lay bao nhieu", "250", "350", "450"],
        "answer": "Mỗi lần hiến máu toàn phần thường lấy 250–450 ml, trong 5–10 phút. Thể tích cụ thể do nhân viên y tế quyết định khi khám sàng lọc.",
        "source": "Quy trình tham gia hiến máu tình nguyện",
    },
    {
        "keys": ["tieu cau", "thanh phan", "huyet tuong"],
        "answer": "Ngoài máu toàn phần, bệnh viện có thể tiếp nhận hiến thành phần (ví dụ tiểu cầu). Khi đăng ký đợt hiến, bạn có thể chọn hình thức dự kiến; hình thức thực tế do bệnh viện quyết định tại điểm hiến.",
        "source": "Hướng dẫn sử dụng nền tảng",
    },
    {
        "keys": ["ban do", "o dau", "dia diem", "gan toi", "diem hien"],
        "answer": "Mục \"Bản đồ\" hiển thị các bệnh viện tham gia và địa điểm các đợt hiến đang mở. Bấm vào một điểm để xem địa chỉ và chỉ đường.",
        "source": "Hướng dẫn sử dụng nền tảng",
    },
    {
        "keys": ["mat khau", "quen", "dang nhap khong duoc"],
        "answer": "Ở trang Đăng nhập, bấm \"Quên mật khẩu?\" và nhập email đã đăng ký để nhận liên kết đặt lại. Sau nhiều lần nhập sai liên tiếp, đăng nhập sẽ tạm khóa trong ít phút.",
        "source": "Hướng dẫn sử dụng nền tảng",
    },
]

# Câu hỏi mang tính lâm sàng → từ chối kết luận (BR-20)
CLINICAL = [
    "du dieu kien", "co duoc hien", "hien duoc khong", "co the hien khong", "bi benh", "co benh", "benh nen",
    "uong thuoc", "dung thuoc", "mang thai", "cho con bu", "huyet ap", "viem gan", "hiv", "tieu duong",
    "chan doan", "trieu chung", "co sao khong", "nguy hiem khong", "bi sot", "cam cum", "ket qua xet nghiem",
]

CLINICAL_ANSWER = (
    "Tôi không thể đưa ra kết luận y khoa (đủ điều kiện hiến, chẩn đoán hay điều trị). "
    "Việc bạn có hiến được hay không do nhân viên y tế quyết định khi khám sàng lọc tại điểm hiến. "
    "Nếu có vấn đề sức khỏe, hãy hỏi trực tiếp bác sĩ hoặc cơ sở y tế."
)
FALLBACK_ANSWER = (
    "Câu hỏi này nằm ngoài nội dung tôi được duyệt để trả lời. Bạn có thể hỏi về: quy trình hiến máu, "
    "chuẩn bị trước khi hiến, cách đăng ký đợt hiến, cách gửi yêu cầu cần máu, lịch sử hiến, bản đồ hoặc bảo mật dữ liệu."
)


def _norm(text):
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def answer(question):
    q = _norm(question or "")
    if not q:
        return {"answer": FALLBACK_ANSWER, "source": None, "matched": False}
    if any(k in q for k in CLINICAL):
        return {"answer": CLINICAL_ANSWER, "source": "Quy tắc BR-20", "matched": True}
    best, score = None, 0
    for item in FAQ:
        s = sum(len(k) for k in item["keys"] if k in q)
        if s > score:
            best, score = item, s
    if best:
        return {"answer": best["answer"], "source": best["source"], "matched": True}
    return {"answer": FALLBACK_ANSWER, "source": None, "matched": False}
