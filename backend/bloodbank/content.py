"""Nội dung tĩnh: tin tức hiến máu (bài báo thật, dẫn link nguồn), kho câu trả lời chatbot đã duyệt
và hàm chuẩn hóa tiếng Việt dùng chung cho trợ lý."""
import re
import unicodedata
from datetime import date

# --------------------------------------------------------------------------
# Tin tức trang chủ: bài báo thật về hiến máu (ưu tiên Đà Nẵng – Quảng Nam), mới nhất trước.
# Ảnh đại diện lấy từ bài gốc, lưu tại static/assets/news/ (CSP chỉ cho ảnh cùng máy chủ); bản quyền thuộc tòa soạn.
# Bấm vào thẻ → mở bài gốc trên trang báo.
# --------------------------------------------------------------------------
NEWS = [
    {
        "title": "Gần 300 tình nguyện viên 4 xã tham gia ngày hội hiến máu",
        "excerpt": "Sáng 18/10, tại xã Tiên Phước, 4 xã Tiên Phước, Thạnh Bình, Sơn Cẩm Hà và Lãnh Ngọc phối hợp tổ chức "
                   "Ngày hội hiến máu tình nguyện tháng 10 năm 2026.",
        "source": "Báo Đà Nẵng", "date": date(2026, 10, 18), "image": "assets/news/2026-10-tien-phuoc.jpg",
        "url": "https://baodanang.vn/gan-300-tinh-nguyen-vien-4-xa-tham-gia-ngay-hoi-hien-mau-3355697.html",
    },
    {
        "title": "Hành trình Đỏ 2026 tiếp nhận hơn 168.770 đơn vị máu, vượt xa mục tiêu ban đầu",
        "excerpt": "Sau 2 tháng tại 32 tỉnh, thành phố, chương trình lần thứ XIV đã tiếp nhận hơn 168.770 đơn vị máu, "
                   "vượt mục tiêu 120.000 đơn vị; sau 14 kỳ, tổng cộng hơn 1,23 triệu đơn vị.",
        "source": "VietnamPlus", "date": date(2026, 8, 15), "image": "assets/news/2026-08-hanh-trinh-do.jpg",
        "url": "https://www.vietnamplus.vn/hanh-trinh-do-2026-tiep-nhan-hon-168770-don-vi-mau-vuot-xa-muc-tieu-ban-dau-post1130314.vnp",
    },
    {
        "title": "Đà Nẵng: UBND thành phố tôn vinh, khen thưởng phong trào hiến máu tình nguyện năm 2026",
        "excerpt": "Ngày 14-8, UBND TP.Đà Nẵng, Ban Chỉ đạo vận động hiến máu tình nguyện tổ chức chương trình tôn vinh, "
                   "khen thưởng phong trào hiến máu tình nguyện năm 2026.",
        "source": "Giác Ngộ", "date": date(2026, 8, 16), "image": "assets/news/2026-08-ton-vinh.jpg",
        "url": "https://giacngo.vn/da-nang-ubnd-thanh-pho-ton-vinh-khen-thuong-phong-trao-hien-mau-tinh-nguyen-nam-2026-post80625.html",
    },
    {
        "title": "Đà Nẵng: Gần 700 đơn vị máu thu được tại Hành trình Đỏ",
        "excerpt": "Ngày 5/7, Ban Chỉ đạo vận động hiến máu tình nguyện thành phố phối hợp phường Thanh Khê tổ chức "
                   "ngày hội hiến máu \"Giọt hồng Đà Nẵng\" trong khuôn khổ Hành trình Đỏ.",
        "source": "Báo Nhân Dân", "date": date(2026, 7, 5), "image": "assets/news/2026-07-giot-hong-da-nang.jpg",
        "url": "https://nhandan.vn/da-nang-gan-700-don-vi-mau-thu-duoc-tai-hanh-trinh-do-post973678.html",
    },
    {
        "title": "Hơn 300 người tham gia hiến máu hưởng ứng \"Ngày toàn dân hiến máu tình nguyện 7-4\"",
        "excerpt": "Ban Chỉ đạo vận động hiến máu tình nguyện TP Đà Nẵng tổ chức lễ phát động và tiếp nhận máu tại "
                   "Phân hiệu Học viện Hành chính và Quản trị công.",
        "source": "Công an Đà Nẵng", "date": date(2026, 4, 6), "image": "assets/news/2026-04-cong-an-7-4.jpg",
        "url": "https://cadn.com.vn/hon-300-nguoi-tham-gia-hien-mau-huong-ung-ngay-toan-dan-hien-mau-tinh-nguyen-7-4-post339280.html",
    },
    {
        "title": "Đà Nẵng dự kiến tiếp nhận hơn 56.000 đơn vị máu trong năm 2026",
        "excerpt": "Sáng 4/4, Ban Chỉ đạo vận động hiến máu tình nguyện TP. Đà Nẵng phát động hưởng ứng \"Ngày toàn dân "
                   "hiến máu tình nguyện 7/4\"; năm 2026 thành phố dự kiến khoảng 200 đợt hiến máu.",
        "source": "Dân Việt", "date": date(2026, 4, 4), "image": "assets/news/2026-04-56000-don-vi.jpg",
        "url": "https://etime.danviet.vn/da-nang-du-kien-tiep-nhan-hon-56000-don-vi-mau-trong-nam-2026-d1415774.html",
    },
    {
        "title": "Lan tỏa nghĩa cử hiến máu tình nguyện đầu năm 2026",
        "excerpt": "Với thông điệp \"Mỗi giọt máu cho đi - một cuộc đời ở lại\", phong trào hiến máu tình nguyện đầu năm 2026 "
                   "thu hút đông đảo cán bộ, đoàn viên, thanh niên và nhân dân thành phố.",
        "source": "Báo Đà Nẵng", "date": date(2026, 1, 11), "image": "assets/news/2026-01-dau-nam.jpg",
        "url": "https://baodanang.vn/lan-toa-nghia-cu-hien-mau-tinh-nguyen-dau-nam-2026-3319460.html",
    },
    {
        "title": "Báo động cạn kiệt nguồn máu dự trữ: Hãy chung tay hiến máu cứu người",
        "excerpt": "Nhiều địa phương báo động cạn kiệt nguồn máu dự trữ; các bệnh viện và trung tâm hiến máu cả nước "
                   "kêu gọi người dân tham gia hiến máu nhân đạo.",
        "source": "Tuổi Trẻ", "date": date(2025, 7, 12), "image": "assets/news/2025-07-can-kiet.jpg",
        "url": "https://tuoitre.vn/bao-dong-can-kiet-nguon-mau-du-tru-hay-chung-tay-hien-mau-cuu-nguoi-20250712082854084.htm",
    },
    {
        "title": "Hơn 700 sinh viên hiến máu tình nguyện, sẻ chia yêu thương",
        "excerpt": "Ngày hội hiến máu đợt 1 năm 2025 tại Đại học Đông Á (Đà Nẵng) thu hút hơn 700 lượt đăng ký và "
                   "tiếp nhận 354 đơn vị máu.",
        "source": "Báo Văn hóa", "date": date(2025, 5, 14), "image": "assets/news/2025-05-dong-a.jpg",
        "url": "https://baovanhoa.vn/doi-song/hon-700-sinh-vien-hien-mau-tinh-nguyen-se-chia-yeu-thuong-134580.html",
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
