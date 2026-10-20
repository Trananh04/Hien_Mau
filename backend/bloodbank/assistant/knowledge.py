"""RAG — truy xuất tài liệu kiến thức ĐÃ DUYỆT (thư mục kb/, có phiên bản + nguồn).

- Mỗi tài liệu: front matter (id, title, source, version, reviewed, keywords) + nội dung.
- Truy xuất: BM25 trên từ đơn + cụm 2 từ, chuẩn hóa không dấu (hiểu "hien mau" = "hiến máu"); tiêu đề và từ khóa
  được tăng trọng số. Không cần dịch vụ embedding bên ngoài, kết quả xác định (dễ kiểm thử).
- Nâng cấp sau này khi tài liệu lớn: thêm pgvector (PostgreSQL) cho tìm kiếm ngữ nghĩa, giữ BM25 cho từ khóa (hybrid).
"""
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from bloodbank.content import _norm

KB_DIR = Path(__file__).parent / "kb"
MIN_SCORE = 5.0        # dưới ngưỡng → coi như không có tài liệu liên quan (trả lời "chưa có thông tin")
REL_SCORE = 0.35       # tài liệu phụ phải đạt ≥ 35% điểm tài liệu đứng đầu
STOP = {"toi", "ban", "minh", "co", "khong", "la", "thi", "va", "cua", "cho", "duoc", "nao", "gi", "the", "nhu",
        "de", "mot", "nhung", "cac", "can", "o", "a", "nhe", "vay", "ko", "k", "hay", "voi", "em", "anh", "chi"}


def _tokens(text):
    words = [w for w in _norm(text).split() if w not in STOP]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


def _parse(path):
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"{path.name}: thiếu front matter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    for key in ("id", "title", "source", "version", "reviewed"):
        if not meta.get(key):
            raise ValueError(f"{path.name}: thiếu '{key}'")
    return {**meta, "body": m.group(2).strip()}


@lru_cache(maxsize=1)
def _docs():
    docs = [_parse(p) for p in sorted(KB_DIR.glob("*.md")) if p.name != "README.md"]
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids)), "Trùng id tài liệu"
    for d in docs:
        # tiêu đề ×3, từ khóa ×3, nội dung ×1
        d["_tf"] = Counter(_tokens(d["title"]) * 3 + _tokens(d.get("keywords", "").replace(",", " ")) * 3
                           + _tokens(d["body"]))
        d["_len"] = sum(d["_tf"].values())
    return docs


def _values():
    from bloodbank.models import SystemSetting

    g = SystemSetting.get
    return {"whole": g("donation_interval_whole_blood_days"), "component": g("donation_interval_component_days"),
            "min_age": g("donor_min_age"), "max_age": g("donor_max_age"),
            "min_w_male": g("donor_min_weight_male_kg"), "min_w_female": g("donor_min_weight_female_kg"),
            "retention": g("chat_retention_days")}


def _render(doc, values=None):
    values = values or _values()
    try:
        return doc["body"].format(**values)
    except (KeyError, IndexError):
        return doc["body"]


def search(query, k=3):
    """Trả về tối đa k tài liệu liên quan nhất (đã thay giá trị cấu hình), mỗi mục kèm score."""
    docs = _docs()
    q = _tokens(query)
    if not q:
        return []
    n = len(docs)
    avg = sum(d["_len"] for d in docs) / n
    df = Counter(t for d in docs for t in set(d["_tf"]))
    k1, b = 1.4, 0.6
    scored = []
    for d in docs:
        s = 0.0
        for t in set(q):
            tf = d["_tf"].get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * d["_len"] / avg))
        if s >= MIN_SCORE:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    if scored:
        top = scored[0][0]
        scored = [(s, d) for s, d in scored if s >= top * REL_SCORE]
    values = _values()
    return [{"id": d["id"], "title": d["title"], "source": d["source"], "version": d["version"],
             "reviewed": d["reviewed"], "score": round(s, 2), "text": _render(d, values)} for s, d in scored[:k]]


def get(doc_id):
    d = next((d for d in _docs() if d["id"] == doc_id), None)
    return None if d is None else {"id": d["id"], "title": d["title"], "source": d["source"], "version": d["version"],
                                   "text": _render(d)}


def index_text():
    """Danh mục tài liệu (cho system prompt) — ổn định giữa các request."""
    return "\n".join(f"- [{d['id']}] {d['title']} (v{d['version']})" for d in _docs())


def cite(doc):
    return f"{doc['title']} — {doc['source']}, phiên bản {doc['version']}"
