"""Tra tọa độ từ địa chỉ (OpenStreetMap Nominatim) cho ô chọn vị trí trên bản đồ.

Gọi từ máy chủ (CSP của trang chỉ cho kết nối về chính hệ thống). Nominatim yêu cầu User-Agent riêng và tối đa
~1 yêu cầu/giây → kết quả được lưu cache, mỗi địa chỉ chỉ tra một lần.
"""
import json
import logging
import ssl
import urllib.parse
import urllib.request

from django.core.cache import cache

log = logging.getLogger(__name__)

URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GiotHong-HienMau/1.0 (du an hoc tap)"
CACHE_TTL = 7 * 24 * 3600
TIMEOUT = 6


def _key(query):
    return "geocode:" + urllib.parse.quote(query.lower())[:200]


def lookup(address, province=""):
    """Trả {"lat", "lng", "label"} hoặc None nếu không tìm thấy / dịch vụ lỗi."""
    address = " ".join((address or "").split())[:300]
    province = " ".join((province or "").split())[:100]
    if len(address) < 4:
        return None
    query = f"{address}, {province}" if province and province.lower() not in address.lower() else address
    key = _key(query)
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "vn",
                                     "accept-language": "vi"})
    req = urllib.request.Request(f"{URL}?{params}", headers={"User-Agent": USER_AGENT})
    # Máy chủ Nominatim cắt kết nối TLS không khai báo ALPN (urllib mặc định không gửi) → khai báo http/1.1
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["http/1.1"])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Tra địa chỉ thất bại: %s", exc)
        return None       # lỗi mạng: không lưu cache để lần sau thử lại
    result = {}
    if rows:
        result = {"lat": round(float(rows[0]["lat"]), 6), "lng": round(float(rows[0]["lon"]), 6),
                  "label": rows[0].get("display_name", "")}
    cache.set(key, result, CACHE_TTL)
    return result or None
