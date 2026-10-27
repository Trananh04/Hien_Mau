"""Sinh lịch sử nhu cầu khối hồng cầu MÔ PHỎNG theo ngày (chỉ để demo / huấn luyện thử — không ghi vào sổ kho).

Mỗi ngày, mỗi bệnh viện × nhóm máu:
    nhu cầu kỳ vọng = quy mô bệnh viện × tỷ lệ nhóm máu × hệ số thứ × hệ số Tết × dao động tháng × xu hướng năm
    nhu cầu         ~ Poisson(nhu cầu kỳ vọng) + thỉnh thoảng ca đa chấn thương
    chưa đáp ứng    ~ Binomial(nhu cầu, 1 − tỷ lệ đáp ứng);   đã xuất = nhu cầu − chưa đáp ứng
Tham số và nguồn: params.SIM_PARAMS. Cùng `seed` → cùng bộ dữ liệu (kết quả báo cáo kiểm tra lại được).
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import params as P
from .features import BLOOD_GROUPS


def tet_flags(dates):
    """1 nếu ngày nằm trong khoảng Tết (TET_WINDOW quanh mùng 1)."""
    flags = np.zeros(len(dates), dtype=int)
    for day in P.TET_DATES.values():
        start = pd.Timestamp(day) + pd.Timedelta(days=P.TET_WINDOW[0])
        end = pd.Timestamp(day) + pd.Timedelta(days=P.TET_WINDOW[1])
        flags |= ((dates >= start) & (dates <= end)).astype(int)
    return flags


def group_shares():
    abo, rh = P.value("abo_share"), P.value("rh_negative_share")
    out = {}
    for g in BLOOD_GROUPS:
        out[g] = abo[g[:-1]] * (rh if g.endswith("-") else 1 - rh)
    return out


def simulate(days=540, end=None, seed=42):
    """DataFrame: date, hospital, tier, blood_group, demand, issued, unmet, is_synthetic."""
    rng = np.random.default_rng(seed)
    end = end or date.today()
    dates = pd.date_range(end - timedelta(days=days - 1), end, freq="D")
    weekday = np.array(P.value("weekday_factor"))[dates.dayofweek]
    tet = np.where(tet_flags(dates) == 1, P.value("tet_factor"), 1.0)
    years = (dates - dates[0]).days / 365.25
    trend = (1 + P.value("yearly_trend")) ** years
    shares = group_shares()
    spike = P.value("trauma_spike")
    frames = []
    for hospital, tier in P.value("hospitals"):
        scale = P.value("hospital_rbc_per_day")[tier]
        # dao động theo tháng: mỗi (bệnh viện, tháng) một hệ số chung cho mọi nhóm máu
        months = dates.to_period("M")
        month_factor = {m: rng.lognormal(0, P.value("monthly_cv")) for m in months.unique()}
        monthly = np.array([month_factor[m] for m in months])
        # ca đa chấn thương: ngày nào xảy ra, tổng số đơn vị thêm (chia cho nhóm máu theo tỷ lệ)
        trauma_days = rng.random(len(dates)) < spike["daily_prob"]
        trauma_extra = np.where(trauma_days, rng.poisson(spike["extra_mean"], len(dates)), 0)
        for group, share in shares.items():
            mean = scale * share * weekday * tet * monthly * trend
            demand = rng.poisson(mean) + rng.binomial(trauma_extra, share)
            unmet = rng.binomial(demand, 1 - P.value("fill_rate"))
            frames.append(pd.DataFrame({
                "date": dates, "hospital": hospital, "tier": tier, "blood_group": group,
                "demand": demand, "issued": demand - unmet, "unmet": unmet, "is_synthetic": 1,
            }))
    return pd.concat(frames, ignore_index=True)
