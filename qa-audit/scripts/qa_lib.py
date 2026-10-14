"""Thư viện dùng chung cho bộ kiểm thử QA: cấu hình, client HTTP theo vai trò, truy vấn DB QA, ghi bằng chứng.

Chỉ chạy với môi trường QA cô lập (docker project `hienmau-qa`). Script tự từ chối nếu BASE_URL không phải localhost.
"""
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]          # qa-audit/
CONFIG = ROOT / "config"


def load_env(path=CONFIG / "qa.env"):
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith("QA_")})
    return env


ENV = load_env()
BASE = ENV.get("QA_BASE_URL", "http://127.0.0.1:8091").rstrip("/")
PASSWORD = ENV.get("QA_ACCOUNT_PASSWORD")
CONTAINER = ENV.get("QA_WEB_CONTAINER", "hienmau-qa-qa-web-1")
SCOPE = json.loads((CONFIG / "scope.json").read_text(encoding="utf-8"))

host = urlparse(BASE).hostname
if host not in SCOPE["allowed_hosts"]:
    sys.exit(f"Từ chối chạy: {BASE} không nằm trong phạm vi cho phép {SCOPE['allowed_hosts']}")
if not PASSWORD:
    sys.exit("Thiếu QA_ACCOUNT_PASSWORD trong qa-audit/config/qa.env")

RUN_ID = os.environ.get("QA_RUN_ID") or time.strftime("%Y%m%d-%H%M%S")
RUN_DIR = ROOT / "evidence" / "runs" / RUN_ID
RUN_DIR.mkdir(parents=True, exist_ok=True)
TIMEOUT = SCOPE["limits"]["request_timeout_s"]

ACCOUNTS = {  # tài khoản do seed_demo tạo trong DB QA (dữ liệu giả)
    "admin": "admin@hienmau.vn",
    "h1": "benhvien1@hienmau.vn",   # BV 1 (+ phân công BV 2)
    "h2": "benhvien2@hienmau.vn",
    "h3": "benhvien3@hienmau.vn",
    "m_an": "an.nguyen@demo.vn",
    "m_binh": "binh.tran@demo.vn",
    "m_cuong": "cuong.le@demo.vn",
    "m_lan": "lan.bui@demo.vn",
}
PORTAL = {"admin": "/quan-tri/dang-nhap/", "h": "/benh-vien/dang-nhap/", "m": "/dang-nhap/"}


def redact(text):
    """Che thông tin nhạy cảm trong bằng chứng: cookie phiên, csrf, mật khẩu, SĐT, email người dùng."""
    text = re.sub(r"(sessionid=)[^;\s\"']+", r"\1<redacted>", text)
    text = re.sub(r"(csrftoken=)[^;\s\"']+", r"\1<redacted>", text)
    text = re.sub(r'(name="csrfmiddlewaretoken" value=")[^"]+', r"\1<redacted>", text)
    text = re.sub(r"(csrfmiddlewaretoken=)[^&\s]+", r"\1<redacted>", text)
    if PASSWORD:
        text = text.replace(PASSWORD, "<password>")
    text = re.sub(r"\b0\d{9,10}\b", "<phone>", text)
    return text


class Client:
    """Phiên trình duyệt giả lập: tự lấy CSRF, đăng nhập đúng cổng, ghi lại request/response gần nhất."""

    def __init__(self, who=None):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "qa-audit/1.0 (+local QA env)"
        self.who = who
        self.log = []
        if who:
            self.login(who)

    @property
    def csrf(self):
        tok = self.s.cookies.get("csrftoken")
        if not tok:
            self.get("/dang-nhap/")
            tok = self.s.cookies.get("csrftoken")
        return tok

    def _rec(self, method, path, data, r):
        body = r.text if "text" in r.headers.get("Content-Type", "") or "json" in r.headers.get("Content-Type", "") else ""
        self.log.append({"method": method, "path": path, "data": {k: v for k, v in (data or {}).items()
                                                                if k != "csrfmiddlewaretoken"},
                         "status": r.status_code, "location": r.headers.get("Location"), "body": body[:4000]})
        return r

    def get(self, path, **kw):
        r = self.s.get(BASE + path, allow_redirects=False, timeout=TIMEOUT, **kw)
        return self._rec("GET", path, kw.get("params"), r)

    def post(self, path, data=None, csrf=True, headers=None, **kw):
        data = dict(data or {})
        h = {"Referer": BASE + path, **(headers or {})}
        if csrf:
            data["csrfmiddlewaretoken"] = self.csrf
        r = self.s.post(BASE + path, data=data, allow_redirects=False, timeout=TIMEOUT, headers=h, **kw)
        return self._rec("POST", path, data, r)

    def follow(self, r, limit=5):
        while r.is_redirect and limit:
            loc = r.headers["Location"]
            r = self.get(loc if loc.startswith("/") else urlparse(loc).path)
            limit -= 1
        return r

    def login(self, who, password=None):
        email = ACCOUNTS.get(who, who)
        portal = PORTAL["admin"] if who == "admin" else PORTAL["h"] if who.startswith("h") else PORTAL["m"]
        self.get(portal)
        r = self.post(portal, {"email": email, "password": password or PASSWORD})
        if r.status_code != 302:
            raise RuntimeError(f"Đăng nhập {who} thất bại: HTTP {r.status_code}")
        return r

    def messages(self, r):
        """Lấy thông báo flash (toast) từ trang HTML."""
        return [m.strip() for m in re.findall(r'class="toast[^"]*"[^>]*>(?:.*?)<span[^>]*>(.*?)</span>', r.text, re.S)]


def db(code):
    """Chạy đoạn Python trong container QA (Django shell); đoạn code phải `print(json.dumps(...))` ở dòng cuối."""
    full = "import json\n" + code
    p = subprocess.run(["docker", "exec", "-i", CONTAINER, "python", "manage.py", "shell"], input=full.encode("utf-8"),
                       capture_output=True, timeout=120)
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[-2000:])
    for line in reversed(out):
        line = line.strip()
        if line.startswith(("{", "[")) or line in ("null", "true", "false") or re.fullmatch(r"-?\d+", line):
            return json.loads(line)
    raise RuntimeError("Không đọc được kết quả JSON: " + "\n".join(out[-5:]))


def parallel(fns, workers=None):
    """Chạy đồng thời (giới hạn theo scope.json). Trả về danh sách kết quả hoặc exception theo thứ tự."""
    workers = min(workers or len(fns), SCOPE["limits"]["max_concurrency"])
    results = [None] * len(fns)
    barrier = threading.Barrier(min(workers, len(fns)))

    def run(i):
        try:
            if len(fns) <= workers:
                barrier.wait(timeout=10)
            results[i] = fns[i]()
        except Exception as exc:  # noqa: BLE001
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@dataclass
class Result:
    id: str
    module: str
    title: str
    priority: str
    category: str
    preconditions: str = ""
    steps: str = ""
    expected: str = ""
    actual: str = ""
    status: str = "Not Run"     # Pass / Fail / Blocked / Not Run
    evidence: str = ""
    bug: str = ""
    duration_s: float = 0.0
    extra: dict = field(default_factory=dict)


REGISTRY = []


def case(id, module, title, priority="P2", category="Functional", pre="", steps="", expected=""):
    def deco(fn):
        REGISTRY.append((Result(id, module, title, priority, category, pre, steps, expected), fn))
        return fn
    return deco


def save_evidence(res, clients, extra_text=""):
    path = RUN_DIR / f"{res.id}.txt"
    lines = [f"# {res.id} — {res.title}", f"Status: {res.status}", f"Expected: {res.expected}", f"Actual: {res.actual}", ""]
    if extra_text:
        lines += ["## Ghi chú / dữ liệu DB", extra_text, ""]
    for c in clients:
        for e in c.log[-12:]:
            lines.append(f"## [{c.who or 'anon'}] {e['method']} {e['path']} → HTTP {e['status']}"
                         + (f"  Location: {e['location']}" if e["location"] else ""))
            if e["data"]:
                lines.append("data: " + json.dumps(e["data"], ensure_ascii=False))
            if e["status"] >= 500 or e["body"].lstrip().startswith("{"):
                lines.append(e["body"][:1500])
            lines.append("")
    path.write_text(redact("\n".join(lines)), encoding="utf-8")
    return str(path.relative_to(ROOT)).replace("\\", "/")


def run_all(selected=None):
    out = []
    for res, fn in REGISTRY:
        if selected and not any(res.id.startswith(s) for s in selected):
            continue
        t0 = time.time()
        clients, note = [], ""
        try:
            ret = fn(res) or {}
            clients, note = ret.get("clients", []), ret.get("note", "")
        except AssertionError as exc:
            res.status, res.actual = "Fail", res.actual or str(exc)
        except Exception as exc:  # noqa: BLE001
            res.status, res.actual = "Blocked", f"Lỗi khi chạy test: {type(exc).__name__}: {exc}"[:600]
        res.duration_s = round(time.time() - t0, 2)
        res.evidence = save_evidence(res, clients, note)
        out.append(res)
        print(f"[{res.status:7}] {res.id:10} {res.title}"[:150], flush=True)
    write_outputs(out)
    return out


def write_outputs(results):
    rows = [asdict(r) for r in results]
    (RUN_DIR / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(RUN_DIR / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[k for k in rows[0] if k != "extra"]) if rows else None
        if w:
            w.writeheader()
            for r in rows:
                r.pop("extra", None)
                w.writerow(r)
    # JUnit XML cho CI
    from xml.sax.saxutils import escape
    tests = [f'<testsuite name="qa-audit" tests="{len(results)}" failures="{sum(r.status == "Fail" for r in results)}" '
             f'skipped="{sum(r.status != "Pass" and r.status != "Fail" for r in results)}">']
    for r in results:
        tests.append(f'<testcase classname="{escape(r.module)}" name="{escape(r.id + " " + r.title)}" time="{r.duration_s}">')
        if r.status == "Fail":
            tests.append(f'<failure message="{escape(r.actual[:300], {chr(34): "&quot;"})}">{escape(r.evidence)}</failure>')
        elif r.status != "Pass":
            tests.append(f'<skipped message="{escape(r.actual[:300], {chr(34): "&quot;"})}"/>')
        tests.append("</testcase>")
    tests.append("</testsuite>")
    (RUN_DIR / "junit.xml").write_text("\n".join(tests), encoding="utf-8")
