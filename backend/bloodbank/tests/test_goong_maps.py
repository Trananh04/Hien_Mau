"""Bản đồ Goong: dịch vụ tra địa chỉ / gợi ý / chỉ đường (giả lập API Goong, không gọi mạng) và các endpoint /dia-chi/…"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from bloodbank.services import geocode as geo

GEOCODE = {"results": [{"formatted_address": "54 Nguyễn Lương Bằng, Liên Chiểu, Đà Nẵng",
                        "geometry": {"location": {"lat": 16.0735971, "lng": 108.1498681}},
                        "address_components": [{"long_name": "54 Nguyễn Lương Bằng"}]}], "status": "OK"}
SUGGEST = {"predictions": [{"place_id": "p1", "description": "Bệnh viện Đà Nẵng, 124 Hải Phòng",
                            "structured_formatting": {"main_text": "Bệnh viện Đà Nẵng", "secondary_text": "124 Hải Phòng"}}]}
DETAIL = {"result": {"name": "Bệnh viện Đà Nẵng", "formatted_address": "124 Hải Phòng",
                     "geometry": {"location": {"lat": 16.0721, "lng": 108.2156}}}, "status": "OK"}
ROUTE = {"routes": [{"legs": [{"distance": {"text": "8.71 km", "value": 8710}, "duration": {"text": "13 phút", "value": 780}}],
                     "overview_polyline": {"points": "_p~iF~ps|U_ulLnnqC"}}]}


@override_settings(GOONG_API_KEY="test-api", GOONG_MAP_KEY="test-map")
class GoongServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_lookup_uses_goong_and_caches(self):
        with mock.patch.object(geo, "_get_json", return_value=GEOCODE) as call:
            r1 = geo.lookup("54 Nguyễn Lương Bằng", "Đà Nẵng")
            r2 = geo.lookup("54 Nguyễn Lương Bằng", "Đà Nẵng")
        self.assertEqual(r1, {"lat": 16.073597, "lng": 108.149868, "label": "54 Nguyễn Lương Bằng, Liên Chiểu, Đà Nẵng"})
        self.assertEqual(r1, r2)
        self.assertEqual(call.call_count, 1)                                # lần 2 lấy từ cache
        url, params = call.call_args.args
        self.assertEqual(url, "https://rsapi.goong.io/geocode")
        self.assertEqual(params["api_key"], "test-api")

    def test_network_error_is_not_cached(self):
        with mock.patch.object(geo, "_get_json", return_value=None) as call:
            self.assertIsNone(geo.lookup("12 Trần Phú", "Đà Nẵng"))
            self.assertIsNone(geo.lookup("12 Trần Phú", "Đà Nẵng"))
        self.assertEqual(call.call_count, 2)

    @override_settings(GOONG_API_KEY="")
    def test_falls_back_to_nominatim_without_key(self):
        rows = [{"lat": "16.05", "lon": "108.2", "display_name": "Đà Nẵng"}]
        with mock.patch.object(geo, "_get_json", return_value=rows) as call:
            self.assertEqual(geo.lookup("Đà Nẵng xyz")["lat"], 16.05)
        self.assertEqual(call.call_args.args[0], geo.NOMINATIM)
        self.assertEqual(geo.suggest("bệnh viện"), [])                      # gợi ý chỉ có khi dùng Goong

    def test_suggest_place_reverse(self):
        with mock.patch.object(geo, "_get_json", return_value=SUGGEST):
            self.assertEqual(geo.suggest("bệnh viện đà", near=(16.05, 108.2)),
                             [{"place_id": "p1", "main": "Bệnh viện Đà Nẵng", "secondary": "124 Hải Phòng",
                               "label": "Bệnh viện Đà Nẵng, 124 Hải Phòng"}])
        with mock.patch.object(geo, "_get_json", return_value=DETAIL):
            self.assertEqual(geo.place("p1")["lat"], 16.0721)
        with mock.patch.object(geo, "_get_json", return_value=GEOCODE):
            self.assertEqual(geo.reverse(16.0736, 108.1499)["street"], "54 Nguyễn Lương Bằng")

    def test_directions_not_cached(self):
        with mock.patch.object(geo, "_get_json", return_value=ROUTE) as call:
            r = geo.directions((16.05, 108.2), (16.07, 108.15), "bike")
            geo.directions((16.05, 108.2), (16.07, 108.15), "bike")
        self.assertEqual((r["distance"], r["meters"], r["duration"]), ("8.71 km", 8710, "13 phút"))
        self.assertEqual(call.call_count, 2)            # vị trí người dùng không được lưu vào cache
        self.assertEqual(call.call_args.args[1]["vehicle"], "bike")


MATRIX = {"rows": [{"elements": [
    {"distance": {"text": "5.86 km", "value": 5859}, "duration": {"text": "16 phút", "value": 963}, "status": "OK"},
    {"status": "ZERO_RESULTS"}]}]}


@override_settings(GOONG_API_KEY="test-api", GOONG_MAP_KEY="test-map")
class GoongDistanceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_distances_keep_order_and_mark_unreachable(self):
        with mock.patch.object(geo, "_get_json", return_value=MATRIX) as call:
            r = self.client.get(reverse("bloodbank:geo_distances"),
                                {"from": "21.03,105.79", "to": "21.01,105.82|16.07,108.15"})
        self.assertEqual(r.json()["items"], [{"meters": 5859, "seconds": 963, "distance": "5.86 km",
                                              "duration": "16 phút"}, None])
        self.assertEqual(call.call_args.args[1]["destinations"], "21.01000,105.82000|16.07000,108.15000")

    def test_distances_errors(self):
        self.assertEqual(self.client.get(reverse("bloodbank:geo_distances"), {"from": "21,105"}).status_code, 400)
        with mock.patch.object(geo, "_get_json", return_value=None):
            r = self.client.get(reverse("bloodbank:geo_distances"), {"from": "21,105", "to": "16,108"})
        self.assertEqual(r.status_code, 503)


@override_settings(GOONG_API_KEY="test-api", GOONG_MAP_KEY="test-map")
class GoongEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_endpoints(self):
        with mock.patch.object(geo, "_get_json", return_value=SUGGEST):
            r = self.client.get(reverse("bloodbank:geo_suggest"), {"q": "bệnh viện", "lat": "16.05", "lng": "108.2"})
        self.assertEqual(r.json()["items"][0]["place_id"], "p1")
        with mock.patch.object(geo, "_get_json", return_value=DETAIL):
            self.assertEqual(self.client.get(reverse("bloodbank:geo_place"), {"id": "p1"}).json()["lng"], 108.2156)
        with mock.patch.object(geo, "_get_json", return_value=ROUTE):
            r = self.client.get(reverse("bloodbank:geo_route"), {"from": "16.05,108.2", "to": "16.07,108.15"})
        self.assertEqual(r.json()["distance"], "8.71 km")

    def test_bad_input(self):
        self.assertEqual(self.client.get(reverse("bloodbank:geo_route"), {"from": "abc", "to": "1,2"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("bloodbank:geo_reverse"), {"lat": "95", "lng": "1"}).status_code, 400)
        with mock.patch.object(geo, "_get_json", return_value={"routes": []}):
            r = self.client.get(reverse("bloodbank:geo_route"), {"from": "16.05,108.2", "to": "16.07,108.15"})
        self.assertEqual(r.status_code, 404)

    def test_rate_limit(self):
        with mock.patch.object(geo, "_get_json", return_value={"routes": []}):
            codes = [self.client.get(reverse("bloodbank:geo_route"), {"from": "1,2", "to": "1,2"}).status_code
                     for _ in range(31)]
        self.assertEqual(codes[-1], 429)

    def test_map_page_exposes_only_map_key(self):
        r = self.client.get(reverse("bloodbank:map"))
        self.assertContains(r, 'data-map-key="test-map"')
        self.assertNotContains(r, "test-api")                               # API key chỉ nằm ở máy chủ
        self.assertContains(r, "maplibre-gl.js")
        self.assertIn("https://tiles.goong.io", r["Content-Security-Policy"])
