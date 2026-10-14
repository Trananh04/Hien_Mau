"""Xác nhận một số lỗi trên ứng dụng QA đang chạy (HTTP thật, 1 request mỗi ca, không đồng thời)."""
import re
from qa_lib import Client, RUN_DIR, redact

out = []
def rec(title, r, extra=""):
    line = f"{title}: HTTP {r.status_code} {r.headers.get('Location') or ''} {extra}".strip()
    out.append(line); print(line)

h1 = Client("h1")
page = h1.get("/benh-vien/luot-hien/1/")
rec("GET chi tiết lượt hiến #1 (benhvien1)", page)
r = h1.post("/benh-vien/luot-hien/1/quan-ly/", {"action": "edit", "reason": "QA kiểm tra sửa", "donation_type": "whole_blood",
            "volume_ml": "350", "donated_at": re.search(r'name="donated_at"[^>]*value="([^"]+)"', page.text).group(1)
            if 'name="donated_at"' in page.text else ""})
rec("POST sửa lượt hiến #1", r)
for path in ["/benh-vien/nguoi-hien/?donor=abc", "/benh-vien/kho/lich-su/?from=2026-13-45",
             "/benh-vien/tim-nguon/?blood_group=O%2B&product=abc"]:
    rec("GET " + path, h1.get(path))
r = Client().get("/dang-nhap/?next=%22%3E%3Cb%3Eqa")
rec("GET /dang-nhap/?next=\"><b>qa (ZAP: phản chiếu next)", r,
    "| escaped=" + str("&quot;&gt;&lt;b&gt;qa" in r.text or "&#x27;" in r.text) + " raw=" + str('"><b>qa' in r.text))
(RUN_DIR / "confirm_live.txt").write_text(redact("\n".join(out)), encoding="utf-8")
