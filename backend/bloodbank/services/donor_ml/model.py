"""Mô hình dự đoán khả năng nhận lời + so sánh với cách xếp hạng cũ, đánh giá bằng backtest theo thời gian.

Ba cách xếp hạng cùng được chấm trên cùng các lần kêu gọi:
    RULE "Chấm điểm luật"   — điểm 0–100 hiện tại (donor_match.rule_parts), mốc để so sánh;
    LR   "Hồi quy logistic" — học trọng số cho từng yếu tố (đơn giản, dễ giải thích);
    XGB  "XGBoost"          — cây quyết định tăng cường, học được tương tác giữa các yếu tố.
Chỉ số (trên các lần kêu gọi ở giai đoạn KIỂM TRA, mô hình chưa từng thấy):
    p_at_10   — trong 10 người xếp đầu mỗi lần kêu gọi, tỷ lệ người thực tế nhận lời (chỉ số chính: nhân viên chọn
                người ở đầu danh sách);
    hits_at_10 — số người nhận lời trung bình trong 10 người đầu mỗi lần kêu gọi;
    auc       — xác suất một người nhận lời được xếp trên một người không nhận lời (0,5 = đoán bừa);
    calibration — trung bình xác suất dự đoán − tỷ lệ nhận lời thực tế (gần 0 thì xác suất dùng được để tính số người
                cần mời); chỉ có ở LR / XGB;
    lift      — số người nhận lời THÊM trong 10 người đầu mỗi lần kêu gọi so với chấm điểm luật, kèm khoảng tin cậy 95%
                (bootstrap theo lần kêu gọi: so cặp trên cùng một lần kêu gọi) — để biết hơn thật hay chỉ do may rủi.
Không cần scikit-learn: hồi quy logistic tự cài bằng numpy (Newton, có điều chuẩn L2).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .features import FEATURES

MODELS = {"RULE": "Chấm điểm luật", "LR": "Hồi quy logistic", "XGB": "XGBoost"}
TOP_K = 10
XGB_PARAMS = {"objective": "binary:logistic", "eval_metric": "logloss", "eta": 0.05, "max_depth": 4,
              "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 10, "tree_method": "hist", "seed": 42}
MAX_ROUNDS = 500
EARLY_STOP = 30
VAL_SHARE = 0.15             # phần cuối (theo thời gian) của tập học dùng để dừng sớm


def matrix(df):
    return df[FEATURES].astype(float).to_numpy()


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


# ---------------------------------------------------------------- Hồi quy logistic
class LogReg:
    kind = "LR"

    def __init__(self, state=None):
        self.s = state

    def _prep(self, X):
        s = self.s
        miss = np.isnan(X[:, s["miss_cols"]]).astype(float)
        X = np.where(np.isnan(X), np.array(s["median"]), X)
        Z = (np.column_stack([X, miss]) - np.array(s["mean"])) / np.array(s["std"])
        return Z

    def fit(self, X, y, l2=1.0, iters=30):
        med = np.nanmedian(np.where(np.isnan(X).all(axis=0), 0, X), axis=0)
        med = np.where(np.isnan(med), 0, med)
        miss_cols = [j for j in range(X.shape[1]) if np.isnan(X[:, j]).any()]
        raw = np.column_stack([np.where(np.isnan(X), med, X), np.isnan(X[:, miss_cols]).astype(float)])
        std = raw.std(axis=0)
        self.s = {"median": med.tolist(), "miss_cols": miss_cols, "mean": raw.mean(axis=0).tolist(),
                  "std": np.where(std > 0, std, 1).tolist()}
        Z = np.column_stack([np.ones(len(X)), self._prep(X)])
        w = np.zeros(Z.shape[1])
        reg = np.full(Z.shape[1], l2)
        reg[0] = 0                                            # không điều chuẩn hệ số chặn
        for _ in range(iters):
            p = _sigmoid(Z @ w)
            grad = Z.T @ (p - y) + reg * w
            hess = (Z * (p * (1 - p))[:, None]).T @ Z + np.diag(reg)
            step = np.linalg.solve(hess, grad)
            w -= step
            if np.abs(step).max() < 1e-6:
                break
        self.s["w"] = w.tolist()
        return self

    def predict(self, X):
        w = np.array(self.s["w"])
        return _sigmoid(w[0] + self._prep(X) @ w[1:])

    def contributions(self, X):
        """(n, số đặc trưng): đóng góp vào log-odds của từng đặc trưng (gộp cả cột "thiếu thông tin" của nó)."""
        w = np.array(self.s["w"])[1:]
        part = self._prep(X) * w
        d = X.shape[1]
        out = part[:, :d].copy()
        for k, j in enumerate(self.s["miss_cols"]):
            out[:, j] += part[:, d + k]
        return out

    def save(self, path):
        Path(path).write_text(json.dumps(self.s), encoding="utf-8")

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------- XGBoost
def _xgb():
    import xgboost as xgb

    return xgb


def _threads():
    try:
        from django.conf import settings

        return settings.FORECAST_TRAIN_THREADS
    except Exception:
        return 2


class XGB:
    kind = "XGB"

    def __init__(self, booster=None):
        self.booster = booster

    @property
    def best_iteration(self):
        return int(self.booster.attr("best_iteration") or self.booster.num_boosted_rounds() - 1)

    def fit(self, X, y, X_val, y_val):
        xgb = _xgb()
        dfit, dval = xgb.DMatrix(X, label=y, missing=np.nan), xgb.DMatrix(X_val, label=y_val, missing=np.nan)
        self.booster = xgb.train({**XGB_PARAMS, "nthread": _threads()}, dfit, num_boost_round=MAX_ROUNDS,
                                 evals=[(dval, "val")], early_stopping_rounds=EARLY_STOP, verbose_eval=False)
        return self

    def predict(self, X):
        return self.booster.predict(_xgb().DMatrix(X, missing=np.nan), iteration_range=(0, self.best_iteration + 1))

    def contributions(self, X):
        """Đóng góp SHAP vào log-odds của từng đặc trưng (bỏ cột hệ số chặn cuối)."""
        c = self.booster.predict(_xgb().DMatrix(X, missing=np.nan), pred_contribs=True,
                                 iteration_range=(0, self.best_iteration + 1))
        return c[:, :-1]

    def save(self, path):
        self.booster.save_model(path)

    @classmethod
    def load(cls, path):
        booster = _xgb().Booster()
        booster.load_model(path)
        return cls(booster)


KINDS = {"LR": LogReg, "XGB": XGB}


def _split_time(df):
    times = np.sort(df["at"].unique())
    cut = times[int(len(times) * (1 - VAL_SHARE))] if len(times) > 5 else times[-1]
    return df[df["at"] < cut], df[df["at"] >= cut]


def train(df, kind):
    X, y = matrix(df), df["label"].to_numpy(dtype=float)
    if kind == "LR":
        return LogReg().fit(X, y)
    fit, val = _split_time(df)
    if not len(fit) or not len(val) or fit["label"].nunique() < 2:
        fit, val = df, df
    return XGB().fit(matrix(fit), fit["label"].to_numpy(dtype=float), matrix(val), val["label"].to_numpy(dtype=float))


# ---------------------------------------------------------------- Mốc so sánh: chấm điểm luật hiện tại
def rule_scores(df, max_90d):
    from bloodbank.services import donor_match as dm

    out = np.empty(len(df))
    cols = df[["mode", "dist_km", "asked", "resp_rate", "show_rate", "n_donations", "verified", "recent_90d",
               "here"]].to_numpy(dtype=object)
    for i, (mode, dist, asked, resp, show, n, ver, recent, here) in enumerate(cols):
        dist = None if dist is None or dist != dist else float(dist)
        show = None if show is None or show != show else float(show)
        asked = int(asked or 0)
        came_back = round(float(resp) * asked) if asked and resp == resp and resp is not None else 0
        parts = dm.rule_parts(dm.MODES[dm.mode_of(mode)], dist, False, asked, came_back, show, int(n or 0),
                              bool(ver), int(recent or 0), max_90d, bool(here))
        out[i] = sum(p[1] for p in parts)
    return out


# ---------------------------------------------------------------- Chỉ số
def auc(y, s):
    y = np.asarray(y)
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    if not pos or not neg:
        return None
    ranks = pd.Series(s).rank(method="average").to_numpy()
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def top_k(df, col, k=TOP_K):
    """(p_at_k, hits_at_k): xếp từng lần kêu gọi theo `col` (cao trước), đếm người nhận lời trong k người đầu."""
    hits = slots = 0
    per = []
    for _, g in df.groupby("callout_id", sort=False):
        top = g.sort_values(col, ascending=False, kind="stable").head(k)
        hits += int(top["label"].sum())
        slots += len(top)
        per.append(int(top["label"].sum()))
    return (hits / slots if slots else None), (float(np.mean(per)) if per else None)


def _hits(df, col, k=TOP_K):
    """Số người nhận lời trong k người đầu của từng lần kêu gọi (Series theo callout_id)."""
    return (df.sort_values(col, ascending=False, kind="stable").groupby("callout_id", sort=True).head(k)
            .groupby("callout_id")["label"].sum())


def lift(df, col, base="RULE", n_boot=2000, seed=0):
    """(chênh lệch trung bình người nhận lời / lần trong 10 người đầu, cận dưới 95%, cận trên 95%)."""
    diff = (_hits(df, col) - _hits(df, base)).to_numpy(dtype=float)
    if not len(diff):
        return None, None, None
    rng = np.random.default_rng(seed)
    boots = diff[rng.integers(0, len(diff), (n_boot, len(diff)))].mean(axis=1)
    return float(diff.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def _clean(v):
    return None if isinstance(v, float) and v != v else v


def evaluate(df, col, prob=False):
    p_at, hits = top_k(df, col)
    out = {"p_at_10": p_at, "hits_at_10": hits, "auc": auc(df["label"].to_numpy(), df[col].to_numpy()),
           "calibration": None, "brier": None}
    if prob:
        p, y = df[col].to_numpy(), df["label"].to_numpy()
        out["calibration"] = float(p.mean() - y.mean())
        out["brier"] = float(np.mean((p - y) ** 2))
    return out


def backtest(df, window_days, max_90d, folds=4, log=None):
    """Chia các lần kêu gọi theo thời gian: nửa sau chia thành `folds` đoạn liên tiếp; mỗi đoạn được dự đoán bởi mô hình
    chỉ học từ lời mời ĐÃ BIẾT KẾT QUẢ trước đoạn đó (gửi trước mốc ≥ `window_days` ngày). Trả về (bảng tổng hợp,
    bảng từng đoạn, các dòng kiểm tra kèm điểm của 3 cách)."""
    df = df.sort_values(["at", "callout_id"]).reset_index(drop=True)
    calls = df.drop_duplicates("callout_id")[["callout_id", "at"]]
    test_calls = calls.iloc[len(calls) // 2:]
    chunks = [test_calls.iloc[ix] for ix in np.array_split(np.arange(len(test_calls)), folds) if len(ix)]
    win = pd.Timedelta(days=window_days)
    parts, per_fold = [], []
    for i, chunk in enumerate(chunks, 1):
        start = chunk["at"].iloc[0]
        train_df = df[df["at"] + win <= start]
        test = df[df["callout_id"].isin(chunk["callout_id"])].copy()
        if train_df["label"].nunique() < 2 or test.empty:
            continue
        test["RULE"] = rule_scores(test, max_90d)
        X = matrix(test)
        for kind in ("LR", "XGB"):
            test[kind] = train(train_df, kind).predict(X)
        parts.append(test)
        row = {"fold": i, "from": str(start)[:10], "train_rows": len(train_df), "test_callouts": len(chunk),
               **{f"{k}_p_at_10": top_k(test, k)[0] for k in MODELS}}
        per_fold.append(row)
        if log:
            log(f"  đoạn {i}/{len(chunks)} (từ {row['from']}, học {len(train_df):,} dòng, kiểm tra {len(chunk)} lần "
                f"kêu gọi): " + ", ".join(f"{k} {row[f'{k}_p_at_10']:.1%}" for k in MODELS))
    if not parts:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    allp = pd.concat(parts, ignore_index=True)
    summary = []
    for k, label in MODELS.items():
        gain = lift(allp, k) if k != "RULE" else (None, None, None)
        row = {"model": k, "label": label, **evaluate(allp, k, prob=k != "RULE"),
               "lift": gain[0], "lift_low": gain[1], "lift_high": gain[2],
               "test_callouts": int(allp["callout_id"].nunique()), "test_rows": len(allp),
               "base_rate": float(allp["label"].mean())}
        summary.append({key: _clean(v) for key, v in row.items()})
    return pd.DataFrame(summary), pd.DataFrame(per_fold), allp


# ---------------------------------------------------------------- Lưu / tải
def save(model, directory, meta):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model.save(directory / "model.json")
    meta = {**meta, "kind": model.kind, "features": FEATURES,
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (directory / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str),
                                             encoding="utf-8")
    return meta


def load(directory):
    """(mô hình, metadata) hoặc (None, None) nếu chưa có / hỏng / không khớp đặc trưng hiện tại."""
    directory = Path(directory)
    try:
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if meta.get("features") != FEATURES or meta.get("kind") not in KINDS:
            return None, None
        return KINDS[meta["kind"]].load(directory / "model.json"), meta
    except (OSError, ValueError, KeyError):
        return None, None
