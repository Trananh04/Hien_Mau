"""Địa chỉ ↔ tọa độ, gợi ý địa điểm và chỉ đường cho bản đồ (Goong; dự phòng OpenStreetMap Nominatim).

Gọi từ máy chủ: API key Goong không lộ ra trình duyệt, CSP của trang chỉ cho kết nối về chính hệ thống.
Kết quả được lưu cache (Goong tính phí theo lượt gọi; Nominatim giới hạn ~1 yêu cầu/giây).
"""
import hashlib
import json
import logging
import ssl
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

GOONG = "https://rsapi.goong.io"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "GiotHong-HienMau/1.0 (du an hoc tap)"
CACHE_TTL = 7 * 24 * 3600
TIMEOUT = 6
VEHICLES = ("car", "bike", "taxi", "truck", "hd")


def _key(kind, *parts):
    raw = "|".join(str(p).lower() for p in parts)
    return f"geo:{kind}:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _get_json(url, params):
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    # Một số máy chủ (Nominatim) cắt kết nối TLS không khai báo ALPN (urllib mặc định không gửi) → khai báo http/1.1
    ctx = ssl.create_default_context()
    ctx.set_alpn_protocols(["http/1.1"])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Gọi dịch vụ bản đồ thất bại (%s): %s", url, exc)
        return None


def _goong(path, **params):
    return _get_json(GOONG + path, {**params, "api_key": settings.GOONG_API_KEY})


def _cached(key, fetch):
    """Lỗi mạng (fetch trả None) không lưu cache để lần sau thử lại; "không tìm thấy" lưu dạng rỗng."""
    hit = cache.get(key)
    if hit is not None:
        return hit or None
    value = fetch()
    if value is None:
        return None
    cache.set(key, value, CACHE_TTL)
    return value or None


def _clean(text, limit):
    return " ".join((text or "").split())[:limit]


# ---------------------------------------------------------------- Địa chỉ → tọa độ
def lookup(address, province=""):
    """Trả {"lat", "lng", "label"} hoặc None nếu không tìm thấy / dịch vụ lỗi."""
    address, province = _clean(address, 300), _clean(province, 100)
    if len(address) < 4:
        return None
    query = f"{address}, {province}" if province and province.lower() not in address.lower() else address
    return _cached(_key("lookup", query), lambda: _lookup_goong(query) if settings.GOONG_API_KEY
                   else _lookup_nominatim(query))


def _lookup_goong(query):
    data = _goong("/geocode", address=query)
    if data is None:
        return None
    rows = data.get("results") or []
    if not rows:
        return {}
    loc = rows[0]["geometry"]["location"]
    return {"lat": round(float(loc["lat"]), 6), "lng": round(float(loc["lng"]), 6),
            "label": rows[0].get("formatted_address", "")}


def _lookup_nominatim(query):
    rows = _get_json(NOMINATIM, {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "vn",
                                 "accept-language": "vi"})
    if rows is None:
        return None
    if not rows:
        return {}
    return {"lat": round(float(rows[0]["lat"]), 6), "lng": round(float(rows[0]["lon"]), 6),
            "label": rows[0].get("display_name", "")}


# ---------------------------------------------------------------- Tọa độ → địa chỉ (ghim trên bản đồ → điền địa chỉ)
def reverse(lat, lng):
    if not settings.GOONG_API_KEY:
        return None
    lat, lng = round(float(lat), 5), round(float(lng), 5)

    def fetch():
        data = _goong("/geocode", latlng=f"{lat},{lng}")
        if data is None:
            return None
        rows = data.get("results") or []
        if not rows:
            return {}
        comps = [c.get("long_name", "") for c in rows[0].get("address_components") or []]
        return {"label": rows[0].get("formatted_address", ""), "street": comps[0] if comps else ""}
    return _cached(_key("reverse", lat, lng), fetch)


# ---------------------------------------------------------------- Gợi ý khi gõ địa chỉ
def suggest(text, near=None, limit=6):
    """[{"place_id", "main", "secondary", "label"}] — rỗng nếu chưa cấu hình Goong hoặc gõ quá ngắn."""
    text = _clean(text, 200)
    if not settings.GOONG_API_KEY or len(text) < 3:
        return []
    params = {"input": text, "limit": limit}
    if near:
        params["location"] = f"{near[0]:.4f},{near[1]:.4f}"

    def fetch():
        data = _goong("/place/autocomplete", **params)
        if data is None:
            return None
        out = []
        for p in data.get("predictions") or []:
            fmt = p.get("structured_formatting") or {}
            out.append({"place_id": p.get("place_id"), "main": fmt.get("main_text") or p.get("description", ""),
                        "secondary": fmt.get("secondary_text", ""), "label": p.get("description", "")})
        return out
    return _cached(_key("suggest", text, params.get("location", "")), fetch) or []


def place(place_id):
    """Tọa độ của một gợi ý đã chọn: {"lat", "lng", "label", "name"}."""
    place_id = _clean(place_id, 300)
    if not settings.GOONG_API_KEY or not place_id:
        return None

    def fetch():
        data = _goong("/place/detail", place_id=place_id)
        if data is None:
            return None
        res = data.get("result") or {}
        loc = (res.get("geometry") or {}).get("location")
        if not loc:
            return {}
        return {"lat": round(float(loc["lat"]), 6), "lng": round(float(loc["lng"]), 6),
                "label": res.get("formatted_address", ""), "name": res.get("name", "")}
    return _cached(_key("place", place_id), fetch)


# ---------------------------------------------------------------- Chỉ đường
def directions(origin, destination, vehicle="car"):
    """origin/destination = (lat, lng). Trả {"distance", "duration", "meters", "seconds", "polyline"} hoặc None.
    Không lưu cache: điểm xuất phát là vị trí của người dùng, chỉ dùng cho lượt hỏi này."""
    if not settings.GOONG_API_KEY:
        return None
    vehicle = vehicle if vehicle in VEHICLES else "car"
    o = f"{origin[0]:.5f},{origin[1]:.5f}"
    d = f"{destination[0]:.5f},{destination[1]:.5f}"

    data = _goong("/direction", origin=o, destination=d, vehicle=vehicle)
    routes = (data or {}).get("routes") or []
    if not routes:
        return None
    leg = routes[0]["legs"][0]
    return {"distance": leg["distance"]["text"], "meters": leg["distance"]["value"],
            "duration": leg["duration"]["text"], "seconds": leg["duration"]["value"],
            "polyline": routes[0]["overview_polyline"]["points"]}


MAX_DESTINATIONS = 25


def distances(origin, destinations, vehicle="car"):
    """Quãng đường đi thật từ origin tới từng điểm (Goong Distance Matrix), cùng thứ tự với destinations:
    [{"meters", "seconds", "distance", "duration"} | None, …]. None nếu dịch vụ lỗi. Không lưu cache (vị trí người dùng)."""
    if not settings.GOONG_API_KEY or not destinations:
        return None
    vehicle = vehicle if vehicle in VEHICLES else "car"
    dests = destinations[:MAX_DESTINATIONS]
    data = _goong("/distancematrix", origins=f"{origin[0]:.5f},{origin[1]:.5f}", vehicle=vehicle,
                  destinations="|".join(f"{la:.5f},{ln:.5f}" for la, ln in dests))
    rows = (data or {}).get("rows") or []
    if not rows:
        return None
    out = []
    for el in rows[0].get("elements") or []:
        if el.get("status") != "OK":
            out.append(None)
            continue
        out.append({"meters": el["distance"]["value"], "seconds": el["duration"]["value"],
                    "distance": el["distance"]["text"], "duration": el["duration"]["text"]})
    return out if len(out) == len(dests) else None
