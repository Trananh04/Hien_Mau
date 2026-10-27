"""Phiên bản mô hình dự báo: mỗi lần huấn luyện lưu một thư mục riêng, chỉ bản qua chốt chặn mới được dùng.

    FORECAST_MODEL_DIR/
        model.json, metadata.json      ← bản ĐANG DÙNG (predict.py chỉ đọc 2 file này)
        versions/<phiên bản>/          ← mọi bản đã huấn luyện, kể cả bản bị chốt chặn loại
        last_run.json                  ← lần huấn luyện gần nhất (thời điểm, kết quả, lý do)
        last_check.json                ← lần kiểm tra mỗi đêm gần nhất (monitor.nightly_check)
        train.request                  ← Quản trị bấm "Huấn luyện lại ngay"; tác vụ định kỳ nhận và xóa

Chốt chặn (khi không ép): bản mới chỉ được dùng nếu trong backtest
  1. sai số (WAPE) thấp hơn CẢ HAI cách đơn giản (TB 28 ngày, TB cùng thứ);
  2. không dự báo thiếu quá MAX_UNDER_BIAS (dự báo thiếu nguy hiểm hơn dự báo thừa: thiếu máu thật mà trang báo đủ);
  3. không thay một bản học từ dữ liệu THẬT bằng bản học từ dữ liệu MÔ PHỎNG.
"""
import json
import re
import shutil
from datetime import datetime, timedelta, timezone

from django.conf import settings

from . import model as M

MAX_UNDER_BIAS = -0.05


def root():
    return settings.FORECAST_MODEL_DIR


def versions_dir():
    return root() / "versions"


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def active_meta():
    return _read(root() / "metadata.json")


def versions():
    """Mọi bản đã lưu, mới nhất trước; mỗi bản là metadata + "active"."""
    current = (active_meta() or {}).get("version")
    out = []
    if versions_dir().is_dir():
        for d in versions_dir().iterdir():
            meta = _read(d / "metadata.json")
            if meta and (d / "model.json").exists():
                out.append({**meta, "version": d.name, "active": d.name == current})
    return sorted(out, key=lambda m: m["version"], reverse=True)


def new_version():
    at = datetime.now(timezone.utc)
    while (versions_dir() / at.strftime("%Y%m%d-%H%M%S")).exists():      # 2 lần huấn luyện trong cùng 1 giây
        at += timedelta(seconds=1)
    return at.strftime("%Y%m%d-%H%M%S")


def save_version(trained, meta):
    version = meta.get("version") or new_version()
    meta = M.save(trained, versions_dir() / version, {**meta, "version": version})
    return version, meta


def guard(meta, current=None):
    """(đạt?, [lý do không đạt]) theo 3 điều kiện ở đầu file."""
    reasons = []
    scores = {r["model"]: r for r in meta.get("backtest") or []}
    if "XGB" not in scores:
        reasons.append("chưa có kết quả backtest")
    else:
        xgb, base = scores["XGB"], min(scores["B0"]["wape"], scores["B1"]["wape"])
        if xgb["wape"] >= base:
            reasons.append(f"sai số {xgb['wape']:.1%} không thấp hơn cách đơn giản ({base:.1%})")
        if xgb["bias"] < MAX_UNDER_BIAS:
            reasons.append(f"dự báo thiếu {-xgb['bias']:.1%} (cho phép tối đa {-MAX_UNDER_BIAS:.0%})")
    if current and not current.get("synthetic") and meta.get("synthetic"):
        reasons.append("bản đang dùng học từ dữ liệu thật, bản mới chỉ học từ dữ liệu mô phỏng")
    return not reasons, reasons


def activate(version):
    """Dùng bản `version` (cũng là cách quay lại bản cũ). Ghi metadata trước, model.json sau — predict.py tải lại
    khi model.json đổi, lúc đó metadata đã khớp."""
    if not re.fullmatch(r"\d{8}-\d{6}", version or ""):
        raise FileNotFoundError(version)
    src = versions_dir() / version
    meta = _read(src / "metadata.json")
    if not meta or not (src / "model.json").exists() or M.load(src)[0] is None:
        raise FileNotFoundError(version)
    meta = {**meta, "version": version, "activated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(root() / "metadata.json", meta)
    tmp = root() / "model.json.tmp"
    shutil.copyfile(src / "model.json", tmp)          # copyfile (không copy2) → mtime mới, các tiến trình tải lại
    tmp.replace(root() / "model.json")
    return meta


def last_run():
    return _read(root() / "last_run.json")


def record_run(result):
    _write(root() / "last_run.json", {**result, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def state(name):
    return _read(root() / f"{name}.json")


def set_state(name, data):
    _write(root() / f"{name}.json", data)


def request_training():
    root().mkdir(parents=True, exist_ok=True)
    (root() / "train.request").write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def training_requested():
    return (root() / "train.request").exists()


def clear_request():
    (root() / "train.request").unlink(missing_ok=True)
