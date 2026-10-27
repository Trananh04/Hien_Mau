"""Huấn luyện XGBoost dự báo nhu cầu 14 ngày, so với 2 baseline, đánh giá bằng backtest trượt theo thời gian.

Baseline (không cần học):
    B0 "TB 28 ngày"   = trung bình 28 ngày gần nhất — cách trang Dự báo thiếu hụt đang dùng;
    B1 "TB cùng thứ"  = trung bình 4 ngày gần nhất cùng thứ với ngày được dự báo.
Chỉ số: MAE (đơn vị/ngày), WAPE = Σ|thực − dự báo| ÷ Σ thực, Bias = Σ(dự báo − thực) ÷ Σ thực (âm = dự báo thiếu),
và WAPE của TỔNG 14 ngày mỗi chuỗi (đúng con số trang Dự báo thiếu hụt dùng để so với tồn kho).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .features import BLOOD_GROUPS, FEATURES, HORIZON

MODELS = {"B0": "TB 28 ngày", "B1": "TB cùng thứ", "XGB": "XGBoost"}
# API gốc của XGBoost (không cần scikit-learn). count:poisson vì nhu cầu là số đếm, nhiều ngày bằng 0.
XGB_PARAMS = {"objective": "count:poisson", "eta": 0.05, "max_depth": 4, "subsample": 0.8, "colsample_bytree": 0.8,
              "min_child_weight": 5, "tree_method": "hist", "max_cat_to_onehot": 8, "seed": 42, "nthread": 4}
MAX_ROUNDS = 600
EARLY_STOP = 40
VAL_DAYS = 42                # 6 tuần cuối của tập train dùng để dừng sớm


class Forecaster:
    """Bọc Booster: predict(DataFrame) chỉ dùng số cây tốt nhất tìm được khi dừng sớm."""

    def __init__(self, booster):
        self.booster = booster

    @property
    def best_iteration(self):
        return int(self.booster.attr("best_iteration") or self.booster.num_boosted_rounds() - 1)

    def predict(self, rows):
        xgb = _xgb()
        return self.booster.predict(xgb.DMatrix(rows[FEATURES], enable_categorical=True),
                                    iteration_range=(0, self.best_iteration + 1))

    def save_model(self, path):
        self.booster.save_model(path)


def _threads():
    try:
        from django.conf import settings

        return settings.FORECAST_TRAIN_THREADS
    except Exception:                  # dùng ngoài Django
        return XGB_PARAMS["nthread"]


def _xgb():
    import xgboost as xgb

    return xgb


def train(examples, cutoff=None):
    """Học trên các dòng có ngày được dự báo < cutoff (mặc định: mọi dòng). Dừng sớm theo 6 tuần cuối."""
    data = examples if cutoff is None else examples[examples["target_date"] < cutoff]
    split = data["target_date"].max() - pd.Timedelta(days=VAL_DAYS)
    fit, val = data[data["target_date"] <= split], data[data["target_date"] > split]
    xgb = _xgb()
    dfit = xgb.DMatrix(fit[FEATURES], label=fit["target"], enable_categorical=True)
    dval = xgb.DMatrix(val[FEATURES], label=val["target"], enable_categorical=True)
    booster = xgb.train({**XGB_PARAMS, "nthread": _threads()}, dfit, num_boost_round=MAX_ROUNDS, evals=[(dval, "val")],
                        early_stopping_rounds=EARLY_STOP, verbose_eval=False)
    return Forecaster(booster)


def predict(model, rows):
    out = {"B0": rows["mean_28"].to_numpy(), "B1": rows["same_weekday_4"].to_numpy()}
    if model is not None:
        out["XGB"] = model.predict(rows)
    return out


def scores(y, p):
    total = max(float(np.sum(y)), 1e-9)
    return {"mae": float(np.mean(np.abs(y - p))), "wape": float(np.sum(np.abs(y - p)) / total),
            "bias": float(np.sum(p - y) / total)}


def backtest(examples, folds=12, step=14, log=None):
    """Lần lượt lùi `folds` mốc, mỗi mốc cách nhau `step` ngày: học trên quá khứ trước mốc, dự báo 14 ngày từ ngày
    ngay trước mốc, so với thực tế. Trả về (bảng tổng hợp theo mô hình, bảng theo h, bảng từng mốc)."""
    last_origin = examples["origin"].max() - pd.Timedelta(days=HORIZON)
    cutoffs = [last_origin + pd.Timedelta(days=1) - pd.Timedelta(days=step * k) for k in range(folds)][::-1]
    rows, per_fold = [], []
    for i, cutoff in enumerate(cutoffs, 1):
        model = train(examples, cutoff)
        test = examples[examples["origin"] == cutoff - pd.Timedelta(days=1)]
        preds = predict(model, test)
        part = test[["series", "blood_group", "h", "target"]].copy()
        for name, p in preds.items():
            part[name] = p
        part["fold"] = i
        rows.append(part)
        fold_score = {name: scores(part["target"].to_numpy(), part[name].to_numpy())["wape"] for name in preds}
        per_fold.append({"fold": i, "origin": (cutoff - pd.Timedelta(days=1)).date().isoformat(), **fold_score,
                         "trees": int(model.best_iteration + 1)})
        if log:
            log(f"  mốc {i}/{folds} ({per_fold[-1]['origin']}): " + ", ".join(f"{k} WAPE {v:.1%}"
                                                                        for k, v in fold_score.items()))
    allp = pd.concat(rows, ignore_index=True)
    y = allp["target"].to_numpy()
    summary = []
    sums = allp.groupby(["fold", "series", "blood_group"], observed=True)[["target", *MODELS]].sum()
    for name, label in MODELS.items():
        s = scores(y, allp[name].to_numpy())
        s14 = scores(sums["target"].to_numpy(), sums[name].to_numpy())
        summary.append({"model": name, "label": label, "mae": s["mae"], "wape": s["wape"], "bias": s["bias"],
                        "wape_14d_total": s14["wape"]})
    by_h = (allp.groupby("h").apply(lambda g: pd.Series({n: scores(g["target"].to_numpy(), g[n].to_numpy())["wape"]
                                                         for n in MODELS}), include_groups=False).reset_index())
    return pd.DataFrame(summary), by_h, pd.DataFrame(per_fold)


# ---------------------------------------------------------------- Lưu / tải
def save(model, directory, meta):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model.save_model(directory / "model.json")
    meta = {**meta, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "features": FEATURES, "blood_groups": BLOOD_GROUPS, "horizon": HORIZON}
    (directory / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str),
                                             encoding="utf-8")
    return meta


def load(directory):
    """(mô hình, metadata) hoặc (None, None) nếu chưa có / hỏng."""
    directory = Path(directory)
    try:
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        booster = _xgb().Booster()
        booster.load_model(directory / "model.json")
        model = Forecaster(booster)
    except (OSError, ValueError):
        return None, None
    if meta.get("features") != FEATURES or meta.get("blood_groups") != BLOOD_GROUPS:
        return None, None              # mô hình cũ không khớp đặc trưng hiện tại → không dùng
    return model, meta
