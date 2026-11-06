"""Xếp hạng lúc gợi ý: khả năng nhận lời của từng ứng viên ĐÃ QUA LỌC CỨNG, kèm yếu tố chính và chỗ cho người mới.

Chỉ dùng mô hình khi Quản trị bật `donor_ai_enabled` và có mô hình hợp lệ; ngược lại danh sách giữ thứ tự chấm điểm luật.
Mô hình chỉ đổi THỨ TỰ — không thêm, không bớt người (tập ứng viên do luật quyết định).

Dành chỗ cho người mới (khám phá): nếu chỉ mời người có xác suất cao, hệ thống không bao giờ biết người mới / ít dữ liệu
có nhận lời không → mãi không được mời. Cứ mỗi ⌈1 ÷ `donor_ai_explore_share`⌉ vị trí, một vị trí dành cho người
CHƯA CÓ lịch sử hẹn / kêu gọi có xác suất cao nhất còn lại. Cách chọn cố định (không ngẫu nhiên) → mở lại trang vẫn
thấy cùng danh sách.
"""
import json
import math

from django.conf import settings
from django.utils import timezone

from .features import CONTEXT, FEATURES, compute, describe

_cache = {"mtime": None, "model": None, "meta": None}
_meta_cache = {"mtime": None, "meta": None}
SHOW_FACTORS = 3


def model_dir():
    return settings.DONOR_AI_MODEL_DIR


def active_meta():
    """Metadata bản đang dùng — chỉ đọc JSON (không nạp numpy / xgboost), lưu đệm theo mtime của model.json."""
    try:
        mtime = (model_dir() / "model.json").stat().st_mtime
    except OSError:
        return None
    if _meta_cache["mtime"] != mtime:
        try:
            meta = json.loads((model_dir() / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = None
        if meta and meta.get("features") != FEATURES:
            meta = None
        _meta_cache.update(mtime=mtime, meta=meta)
    return _meta_cache["meta"]


def loaded():
    try:
        mtime = (model_dir() / "model.json").stat().st_mtime
    except OSError:
        _cache.update(mtime=None, model=None, meta=None)
        return None, None
    if _cache["mtime"] != mtime:
        from . import model as M

        m, meta = M.load(model_dir())
        _cache.update(mtime=mtime, model=m, meta=meta)
    return _cache["model"], _cache["meta"]


def enabled():
    from bloodbank.models import SystemSetting

    return bool(SystemSetting.get("donor_ai_enabled")) and active_meta() is not None


def _has_campaign(hospital, mode, now):
    from bloodbank.services import callout

    return mode != "urgent" and callout.next_campaign(hospital, now) is not None


def score(hospital, ids, mode, now=None, has_campaign=None):
    """{user_id: (xác suất, [(đặc trưng, giá trị, đóng góp), ...])} hoặc {} nếu không dùng được mô hình."""
    if not ids or not enabled():
        return {}
    m, _ = loaded()
    if m is None:
        return {}
    import numpy as np

    now = now or timezone.now()
    if has_campaign is None:
        has_campaign = _has_campaign(hospital, mode, now)
    feats = compute(hospital, ids, now, mode, has_campaign)
    ids = list(feats)
    X = np.array([[np.nan if feats[u][f] is None else float(feats[u][f]) for f in FEATURES] for u in ids])
    probs = m.predict(X)
    contrib = m.contributions(X)
    out = {}
    for i, uid in enumerate(ids):
        parts = [(f, feats[uid][f], float(contrib[i, j])) for j, f in enumerate(FEATURES) if f not in CONTEXT]
        out[uid] = (float(probs[i]), parts)
    return out


def apply(hospital, rows, mode, now=None):
    """Gắn "prob", "factors", "explore" vào từng dòng và xếp lại `rows` tại chỗ. Trả về metadata mô hình hoặc None."""
    from bloodbank.models import SystemSetting

    scored = score(hospital, [r["user_id"] for r in rows], mode, now)
    if not scored:
        return None
    for r in rows:
        p, parts = scored[r["user_id"]]
        r["prob"] = p
        r["prob_pct"] = round(100 * p)
        top = sorted(parts, key=lambda x: -abs(x[2]))[:SHOW_FACTORS]
        r["factors"] = [{"text": describe(f, v), "up": c > 0} for f, v, c in top if abs(c) >= 0.01]
        r["explore"] = False
    ranked = sorted(rows, key=lambda r: (-r["prob"], r["recent_invites"], r["code"]))
    share = float(SystemSetting.get("donor_ai_explore_share") or 0)
    every = math.ceil(1 / share) if share > 0 else 0
    newcomers = [r for r in ranked if not r["asked"] and not r["history_seen"]]
    out, used = [], set()

    def first(items):
        return next((r for r in items if r["code"] not in used), None)

    while len(out) < len(ranked):
        best = first(ranked)
        pick = first(newcomers) if every and (len(out) + 1) % every == 0 else None
        if pick is not None and pick is not best:
            pick["explore"] = True                 # được đẩy lên nhờ chỗ dành cho người mới
        out.append(pick or best)
        used.add((pick or best)["code"])
    rows[:] = out
    _, meta = loaded()
    return meta


def count_for(rows, shortage, cap):
    """Số người nên mời: ít nhất k người đầu danh sách sao cho TỔNG khả năng nhận lời ≥ số đơn vị thiếu (tối đa `cap`)."""
    if not shortage or shortage <= 0:
        return 0
    total = 0.0
    for k, r in enumerate(rows, 1):
        total += r.get("prob") or 0
        if total >= shortage or k >= cap:
            return k
    return min(len(rows), cap)


def expected(rows, k):
    return sum((r.get("prob") or 0) for r in rows[:k])
