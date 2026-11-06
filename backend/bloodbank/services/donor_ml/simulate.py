"""Sinh lịch sử kêu gọi người hiến MÔ PHỎNG (chỉ để demo / huấn luyện thử khi chưa đủ dữ liệu thật — không ghi vào CSDL).

Thế giới mô phỏng (mỗi tham số ở PARAMS có `value` và `source` — tất cả là GIẢ ĐỊNH, phải ghi rõ khi trình bày):
  - vài bệnh viện trong một tỉnh/thành, người hiến sống rải quanh bệnh viện gần nhà;
  - mỗi người có "mức nhiệt tình" ẩn (không quan sát được) → ảnh hưởng cả việc tự đi hiến lẫn việc nhận lời;
  - người hiến tự đi hiến rải rác (tạo lịch sử), bệnh viện thỉnh thoảng gửi lời kêu gọi (thiếu kho / khẩn);
  - danh sách mời được chọn đúng như hệ thống thật: lọc cứng (đủ thời gian nghỉ, không bị mời quá dày, khẩn: trong
    10 km) rồi lấy phần lớn người điểm luật cao + một phần ngẫu nhiên (để có dữ liệu về cả người điểm thấp);
  - xác suất nhận lời = logistic(hệ số × yếu tố); có TƯƠNG TÁC mà chấm điểm luật cộng dồn không diễn tả được
    (gần + cuối tuần, khoảng cách quan trọng hơn khi khẩn, người lâu không hiến khó gọi lại);
  - người nhận lời đăng ký; phần lớn đến hiến, một phần vắng → lịch sử "đến đúng hẹn" thay đổi theo thời gian.
Đặc trưng xuất ra đúng định nghĩa của features.compute (chỉ dữ liệu có trước lời mời).
"""
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .features import FEATURES

PARAMS = {
    "hospitals": {"value": 5, "source": "Giả định: 5 bệnh viện trong một tỉnh/thành"},
    "donors": {"value": 3000, "source": "Giả định: 3.000 người hiến đã có tài khoản"},
    "warmup_days": {"value": 180, "source": "Giả định: 6 tháng đầu chỉ có hiến tự nguyện, tạo lịch sử ban đầu"},
    "days": {"value": 540, "source": "Giả định: 18 tháng có kêu gọi"},
    "spread_km": {"value": 9.0, "source": "Giả định: nơi ở cách bệnh viện gần nhà trung bình khoảng 9 km"},
    "callouts_per_week": {"value": 1.5, "source": "Giả định: mỗi bệnh viện kêu gọi 1–2 lần một tuần"},
    "urgent_share": {"value": 0.2, "source": "Giả định: 20% lần kêu gọi là khẩn"},
    "campaign_share": {"value": 0.7, "source": "Giả định: 70% lần kêu gọi thiếu kho có đợt hiến đang mở kèm theo"},
    "invite_size": {"value": 25, "source": "Giả định: mỗi lần mời khoảng 25 người"},
    "explore_share": {"value": 0.4, "source": "Giả định: 40% người được mời chọn ngẫu nhiên, 60% theo điểm luật"},
    "daily_self_donation": {"value": 1 / 450, "source": "Giả định: người đủ điều kiện tự đi hiến ~ 1 lần / 15 tháng"},
    "show_intercept": {"value": 1.4, "source": "Giả định: ~80% người đã đăng ký đến hiến"},
    "verify_prob": {"value": 0.85, "source": "Giả định: 85% lượt hiến có kết quả nhóm máu xét nghiệm"},
    "response": {"value": {
        "intercept": -1.6, "propensity": 1.0, "per_km": -0.06, "per_km_urgent": -0.14, "near_weekend": 0.6,
        "campaign": 0.5, "urgent": -0.3, "per_recent_invite": -0.45, "verified": 0.25, "per_donation": 0.12,
        "lapsed": -0.5, "first_time": -0.6, "evening": 0.25,
    }, "source": "Giả định: người ở gần, có đợt hiến cụ thể, được nhắc vào cuối tuần / buổi tối dễ nhận lời; bị gọi "
                 "dày, lâu không hiến (> 1 năm) hoặc chưa từng hiến thì khó nhận lời hơn"},
}
INTERVAL_DAYS = 84
COOLDOWN = {"stock": 7, "urgent": 3}
MAX_90 = 4
WINDOW = 7
URGENT_RADIUS = 10
KM_LAT = 111.0


def value(key):
    return PARAMS[key]["value"]


def _sig(x):
    return 1 / (1 + np.exp(-x))


def simulate(seed=7, end=None):
    """DataFrame: callout_id, at, hospital_id, mode, <FEATURES>, label, is_synthetic=1."""
    rng = np.random.default_rng(seed)
    nh, n = value("hospitals"), value("donors")
    warm, days = value("warmup_days"), value("days")
    km_lng = KM_LAT * math.cos(math.radians(21.0))
    hosp = np.column_stack([rng.normal(0, 6, nh), rng.normal(0, 6, nh)])              # km quanh trung tâm
    home_of = rng.integers(0, nh, n)
    home = hosp[home_of] + rng.normal(0, value("spread_km") / 1.25, (n, 2))
    spot = home + rng.normal(0, 1.0, (n, 2))                                           # nơi hiến ≈ gần nhà
    dist_true = np.linalg.norm(home[:, None, :] - hosp[None, :, :], axis=2)            # (n, nh)
    dist_spot = np.linalg.norm(spot[:, None, :] - hosp[None, :, :], axis=2)
    nearest = dist_true.argmin(axis=1)
    prop = rng.normal(0, 1, n)

    n_don = np.zeros(n)
    last = np.full(n, np.nan)
    here = np.zeros((n, nh), dtype=bool)
    verified = np.zeros(n)
    came = np.zeros(n)
    missed = np.zeros(n)
    known = np.zeros(n, dtype=bool)
    inv_days = np.full((n, MAX_90), -1e9)                     # 4 lời mời gần nhất (vòng)
    last_invite = np.full(n, -1e9)
    asked = np.zeros(n)
    answered = np.zeros(n)
    pending = []                                               # (ngày, người, có nhận lời) chưa hết cửa sổ theo dõi
    r = value("response")
    end = end or datetime.now().date()
    start = datetime.combine(end - timedelta(days=warm + days), datetime.min.time())
    rows, cid = [], 0

    def donate(idx, h_idx, d):
        n_don[idx] += 1
        last[idx] = d
        here[idx, h_idx] = True
        known[idx] = True
        verified[idx] = np.maximum(verified[idx], rng.random(len(idx)) < value("verify_prob"))

    for d in range(warm + days):
        rested = np.isnan(last) | (d - last >= INTERVAL_DAYS)
        self_go = rested & (rng.random(n) < value("daily_self_donation") * np.exp(0.6 * prop))
        idx = np.flatnonzero(self_go)
        if len(idx):
            came[idx] += 1
            donate(idx, nearest[idx], d)
        while pending and pending[0][0] + WINDOW <= d:          # lời mời đã hết thời gian theo dõi
            _, who, yes = pending.pop(0)
            asked[who] += 1
            answered[who] += yes
        if d < warm:
            continue
        dow = (start + timedelta(days=d)).weekday()
        for h in range(nh):
            if rng.random() >= value("callouts_per_week") / 7:
                continue
            mode = "urgent" if rng.random() < value("urgent_share") else "stock"
            has_campaign = mode == "stock" and rng.random() < value("campaign_share")
            hour = int(rng.integers(7, 21))
            rested = np.isnan(last) | (d - last >= INTERVAL_DAYS)       # tính lại: lần kêu gọi trước trong ngày có người vừa hiến
            recent = (inv_days >= d - 90).sum(axis=1)
            dist_feat = np.where(known, dist_spot[:, h], np.nan)
            elig = rested & (d - last_invite >= COOLDOWN[mode]) & (recent < MAX_90)
            if mode == "urgent":
                elig &= known & (dist_feat <= URGENT_RADIUS)
            pool = np.flatnonzero(elig)
            if not len(pool):
                continue
            # Danh sách mời: phần lớn theo điểm luật (gần, hay nhận lời, đến đúng hẹn, kinh nghiệm), phần còn lại ngẫu nhiên
            seen = came[pool] + missed[pool]
            rule = (np.where(np.isnan(dist_feat[pool]), 0.3, np.clip(1 - dist_feat[pool] / 50, 0, None)) * 20
                    + np.where(asked[pool] > 0, answered[pool] / np.maximum(asked[pool], 1), 0.5) * 15
                    + np.where(seen > 0, came[pool] / np.maximum(seen, 1), 0.5) * 15
                    + np.minimum(n_don[pool], 5) / 5 * 10 + verified[pool] * 15
                    + np.clip(1 - recent[pool] / MAX_90, 0, None) * 15 + here[pool, h] * 10)
            k = min(value("invite_size"), len(pool))
            k_rule = int(round(k * (1 - value("explore_share"))))
            order = pool[np.argsort(-rule, kind="stable")]
            top = order[:k_rule]
            rest = order[k_rule:]
            chosen = np.concatenate([top, rng.choice(rest, size=min(k - k_rule, len(rest)), replace=False)])

            days_since = np.where(np.isnan(last[chosen]), np.nan, d - last[chosen])
            seen_c = came[chosen] + missed[chosen]
            dist_c = dist_true[chosen, h]
            urgent = mode == "urgent"
            weekend = dow >= 4
            logit = (r["intercept"] + r["propensity"] * prop[chosen]
                     + (r["per_km_urgent"] if urgent else r["per_km"]) * dist_c
                     + r["near_weekend"] * ((dist_c < 5) & weekend & (not urgent))
                     + r["campaign"] * has_campaign + r["urgent"] * urgent
                     + r["per_recent_invite"] * recent[chosen] + r["verified"] * verified[chosen]
                     + r["per_donation"] * np.minimum(n_don[chosen], 5)
                     + r["lapsed"] * (np.nan_to_num(days_since, nan=0) > 365)
                     + r["first_time"] * (n_don[chosen] == 0) + r["evening"] * (17 <= hour <= 21))
            yes = rng.random(len(chosen)) < _sig(logit)
            at = start + timedelta(days=d, hours=hour)
            for j, i in enumerate(chosen):
                rows.append({
                    "callout_id": cid, "at": at, "hospital_id": h, "mode": mode,
                    "dist_km": dist_feat[i], "days_since": days_since[j], "n_donations": n_don[i],
                    "verified": verified[i], "here": float(here[i, h]),
                    "show_rate": came[i] / seen_c[j] if seen_c[j] else np.nan, "appointments": seen_c[j],
                    "asked": asked[i], "resp_rate": answered[i] / asked[i] if asked[i] else np.nan,
                    "recent_90d": recent[i], "urgent": int(urgent), "has_campaign": int(has_campaign),
                    "weekend": int(weekend), "hour": hour, "label": int(yes[j]), "is_synthetic": 1,
                })
            cid += 1
            # Cập nhật thế giới sau lời mời
            slot = np.argmin(inv_days[chosen], axis=1)
            inv_days[chosen, slot] = d
            last_invite[chosen] = d
            for i, y in zip(chosen, yes):
                pending.append((d, i, int(y)))
            accepted = chosen[yes]
            if len(accepted):
                show = rng.random(len(accepted)) < _sig(value("show_intercept") + 0.8 * prop[accepted])
                came[accepted[show]] += 1
                missed[accepted[~show]] += 1
                donate(accepted[show], np.full(int(show.sum()), h), d)
        pending.sort(key=lambda e: e[0])
    cols = ["callout_id", "at", "hospital_id", "mode", *FEATURES, "label", "is_synthetic"]
    return pd.DataFrame(rows, columns=cols)
