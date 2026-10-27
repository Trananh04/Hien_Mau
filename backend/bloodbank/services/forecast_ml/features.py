"""Đặc trưng cho dự báo TRỰC TIẾP nhiều bước: đứng ở ngày gốc t (cuối ngày), dự báo nhu cầu ngày t + h, h = 1…14.

Mọi đặc trưng "lịch sử" chỉ dùng nhu cầu các ngày ≤ t (không rò rỉ tương lai); đặc trưng "lịch" (thứ, tháng, Tết)
thuộc ngày được dự báo — biết trước được. Một mô hình chung cho mọi chuỗi (bệnh viện × nhóm máu × quy cách): không
dùng mã bệnh viện làm đặc trưng nên mô hình áp được cho bệnh viện mới — mức nhu cầu của chuỗi nằm trong các trung bình.
"""
import numpy as np
import pandas as pd

HORIZON = 14
HISTORY_DAYS = 28                      # cần tối thiểu 28 ngày lịch sử để có đủ đặc trưng
BLOOD_GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
FEATURES = ["h", "dow", "month", "tet", "blood_group",
            "last_1", "last_7", "last_14", "mean_7", "mean_28", "std_28", "nonzero_28", "same_weekday_4"]


def _origin_stats(demand):
    """Thống kê tại mỗi ngày gốc t (chỉ dùng demand[≤ t]); same_weekday[o] = TB 4 ngày t−o, t−o−7, t−o−14, t−o−21."""
    s = pd.Series(demand, dtype=float)
    stats = {
        "last_1": s, "last_7": s.shift(6), "last_14": s.shift(13),
        "mean_7": s.rolling(7).mean(), "mean_28": s.rolling(28).mean(), "std_28": s.rolling(28).std(),
        "nonzero_28": (s > 0).astype(float).rolling(28).mean(),
    }
    same_weekday = [(s.shift(o) + s.shift(o + 7) + s.shift(o + 14) + s.shift(o + 21)) / 4 for o in range(7)]
    return stats, same_weekday


def build(series_df, tet_of, with_target=True, origins=None):
    """series_df: một chuỗi, cột date (liên tục từng ngày) + demand. Trả về các dòng (ngày gốc × h) có đặc trưng.

    origins: chỉ số các ngày gốc cần dựng (mặc định: mọi ngày đủ 28 ngày lịch sử).
    with_target: thêm cột target = nhu cầu ngày t + h (bỏ dòng không có target)."""
    dates = pd.DatetimeIndex(series_df["date"])
    demand = series_df["demand"].to_numpy(dtype=float)
    stats, same_weekday = _origin_stats(demand)
    n = len(demand)
    idx = np.arange(HISTORY_DAYS - 1, n) if origins is None else np.asarray(origins)
    parts = []
    for h in range(1, HORIZON + 1):
        t = idx[idx + h < n] if with_target else idx
        target_dates = dates[t] + pd.Timedelta(days=h) if len(t) else pd.DatetimeIndex([])
        dow = target_dates.dayofweek.to_numpy()
        offset = (dates[t].dayofweek.to_numpy() - dow) % 7      # ngày gần nhất ≤ t cùng thứ với ngày dự báo
        sw = np.vstack([same_weekday[o].to_numpy() for o in range(7)])
        part = pd.DataFrame({
            "origin": dates[t], "target_date": target_dates, "h": h, "dow": dow,
            "month": target_dates.month.to_numpy(), "tet": tet_of(target_dates),
            **{k: v.to_numpy()[t] for k, v in stats.items()},
            "same_weekday_4": sw[offset, t] if len(t) else [],
        })
        if with_target:
            part["target"] = demand[t + h]
        parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    return out.dropna(subset=["mean_28", "same_weekday_4"])


def build_all(daily, tet_of, with_target=True):
    """daily: date, series, blood_group, demand (mỗi chuỗi đủ mọi ngày). Ghép đặc trưng mọi chuỗi."""
    frames = []
    for (series, group), df in daily.groupby(["series", "blood_group"], sort=False):
        part = build(df.sort_values("date"), tet_of, with_target)
        part["series"], part["blood_group"] = series, group
        frames.append(part)
    out = pd.concat(frames, ignore_index=True)
    out["blood_group"] = pd.Categorical(out["blood_group"], categories=BLOOD_GROUPS)
    return out


def fill_days(daily, start=None, end=None):
    """Mỗi chuỗi có đủ mọi ngày trong [start, end] — ngày không có phiếu = 0."""
    frames = []
    for (series, group), df in daily.groupby(["series", "blood_group"], sort=False):
        lo = start or df["date"].min()
        hi = end or df["date"].max()
        full = pd.DataFrame({"date": pd.date_range(lo, hi, freq="D")})
        merged = full.merge(df[["date", "demand"]], on="date", how="left").fillna({"demand": 0})
        merged["series"], merged["blood_group"] = series, group
        frames.append(merged)
    return pd.concat(frames, ignore_index=True)
