"""Đơn vị hành chính cấp tỉnh của Việt Nam — nguồn dữ liệu địa lý duy nhất của hệ thống.

Theo Nghị quyết 202/2025/QH15 (hiệu lực 01/7/2025): 34 đơn vị gồm 6 thành phố trực thuộc Trung ương và 28 tỉnh.
- PROVINCES: danh sách hiển thị trong mọi ô chọn tỉnh/thành (xếp theo bảng chữ cái).
- LEGACY: tên tỉnh trước sắp xếp → tên hiện hành (dữ liệu cũ, người dùng quen gọi tên cũ khi hỏi trợ lý).
- CENTERS: tọa độ gần đúng trung tâm hành chính, dùng để định vị bản đồ khi chưa có tọa độ cụ thể.
"""
import re
import unicodedata

PROVINCES = [
    "An Giang", "Bắc Ninh", "Cà Mau", "Cao Bằng", "Cần Thơ", "Đà Nẵng", "Đắk Lắk", "Điện Biên", "Đồng Nai",
    "Đồng Tháp", "Gia Lai", "Hà Nội", "Hà Tĩnh", "Hải Phòng", "Huế", "Hưng Yên", "Khánh Hòa", "Lai Châu",
    "Lâm Đồng", "Lạng Sơn", "Lào Cai", "Nghệ An", "Ninh Bình", "Phú Thọ", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị",
    "Sơn La", "Tây Ninh", "Thái Nguyên", "Thanh Hóa", "TP. Hồ Chí Minh", "Tuyên Quang", "Vĩnh Long",
]

LEGACY = {
    "Thừa Thiên Huế": "Huế", "Thừa Thiên - Huế": "Huế",
    "Hà Giang": "Tuyên Quang", "Yên Bái": "Lào Cai", "Bắc Kạn": "Thái Nguyên",
    "Vĩnh Phúc": "Phú Thọ", "Hòa Bình": "Phú Thọ", "Bắc Giang": "Bắc Ninh", "Thái Bình": "Hưng Yên",
    "Hải Dương": "Hải Phòng", "Hà Nam": "Ninh Bình", "Nam Định": "Ninh Bình", "Quảng Bình": "Quảng Trị",
    "Quảng Nam": "Đà Nẵng", "Kon Tum": "Quảng Ngãi", "Bình Định": "Gia Lai", "Ninh Thuận": "Khánh Hòa",
    "Đắk Nông": "Lâm Đồng", "Bình Thuận": "Lâm Đồng", "Phú Yên": "Đắk Lắk",
    "Bình Dương": "TP. Hồ Chí Minh", "Bà Rịa - Vũng Tàu": "TP. Hồ Chí Minh", "Bà Rịa Vũng Tàu": "TP. Hồ Chí Minh",
    "Vũng Tàu": "TP. Hồ Chí Minh", "Hồ Chí Minh": "TP. Hồ Chí Minh", "TP Hồ Chí Minh": "TP. Hồ Chí Minh",
    "Thành phố Hồ Chí Minh": "TP. Hồ Chí Minh", "Sài Gòn": "TP. Hồ Chí Minh", "HCM": "TP. Hồ Chí Minh",
    "TPHCM": "TP. Hồ Chí Minh",
    "Bình Phước": "Đồng Nai", "Long An": "Tây Ninh", "Sóc Trăng": "Cần Thơ", "Hậu Giang": "Cần Thơ",
    "Bến Tre": "Vĩnh Long", "Trà Vinh": "Vĩnh Long", "Tiền Giang": "Đồng Tháp", "Bạc Liêu": "Cà Mau",
    "Kiên Giang": "An Giang",
}

CENTERS = {
    "An Giang": (10.0125, 105.0809), "Bắc Ninh": (21.2731, 106.1946), "Cà Mau": (9.1769, 105.1524),
    "Cao Bằng": (22.6657, 106.2570), "Cần Thơ": (10.0452, 105.7469), "Đà Nẵng": (16.0544, 108.2022),
    "Đắk Lắk": (12.6667, 108.0500), "Điện Biên": (21.3860, 103.0230), "Đồng Nai": (10.9574, 106.8427),
    "Đồng Tháp": (10.3600, 106.3600), "Gia Lai": (13.7820, 109.2192), "Hà Nội": (21.0285, 105.8542),
    "Hà Tĩnh": (18.3428, 105.9057), "Hải Phòng": (20.8449, 106.6881), "Huế": (16.4637, 107.5909),
    "Hưng Yên": (20.6464, 106.0511), "Khánh Hòa": (12.2388, 109.1967), "Lai Châu": (22.3964, 103.4582),
    "Lâm Đồng": (11.9404, 108.4583), "Lạng Sơn": (21.8537, 106.7610), "Lào Cai": (21.7229, 104.9113),
    "Nghệ An": (18.6796, 105.6813), "Ninh Bình": (20.2506, 105.9745), "Phú Thọ": (21.3227, 105.4019),
    "Quảng Ngãi": (15.1214, 108.8044), "Quảng Ninh": (20.9599, 107.0425), "Quảng Trị": (17.4689, 106.6223),
    "Sơn La": (21.3256, 103.9188), "Tây Ninh": (10.5359, 106.4137), "Thái Nguyên": (21.5942, 105.8482),
    "Thanh Hóa": (19.8067, 105.7852), "TP. Hồ Chí Minh": (10.7769, 106.7009), "Tuyên Quang": (21.8236, 105.2140),
    "Vĩnh Long": (10.2537, 105.9722),
}
VIETNAM_CENTER = (16.0, 106.3)   # nhìn được toàn quốc ở mức zoom 5

assert len(PROVINCES) == 34 and set(CENTERS) == set(PROVINCES) and set(LEGACY.values()) <= set(PROVINCES)


def _key(text):
    text = unicodedata.normalize("NFD", (text or "").lower()).replace("đ", "d")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\b(tinh|thanh pho|tp)\b", " ", re.sub(r"[^a-z0-9 ]", " ", text))
    return re.sub(r"\s+", " ", text).strip()


_LOOKUP = {**{_key(p): p for p in PROVINCES}, **{_key(old): new for old, new in LEGACY.items()}}


def normalize_province(name):
    """Tên tỉnh bất kỳ (có/không dấu, tên trước sắp xếp, có/không "tỉnh", "TP.") → tên hiện hành, hoặc None."""
    return _LOOKUP.get(_key(name)) if name else None


def center_of(province):
    """Tọa độ trung tâm tỉnh (đã chuẩn hóa tên); không rõ tỉnh → giữa Việt Nam."""
    return CENTERS.get(normalize_province(province) or "", VIETNAM_CENTER)


def area_names():
    """Mọi tên địa danh cấp tỉnh trợ lý nhận ra (tên hiện hành + tên cũ), dài trước để khớp cụm dài trước."""
    return sorted(set(PROVINCES) | set(LEGACY), key=len, reverse=True)
