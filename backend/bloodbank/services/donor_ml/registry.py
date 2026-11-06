"""Phiên bản mô hình gợi ý người hiến: mỗi lần huấn luyện lưu một thư mục riêng, chỉ bản qua chốt chặn mới được dùng.

    DONOR_AI_MODEL_DIR/
        model.json, metadata.json      ← bản ĐANG DÙNG (predict.py chỉ đọc 2 file này)
        versions/<phiên bản>/          ← mọi bản đã huấn luyện, kể cả bản bị chốt chặn loại
        sim/invites.csv                ← dữ liệu mô phỏng (sinh một lần)
        last_run.json, last_check.json, last_accuracy.json, train.request

Chốt chặn (khi không ép): trong backtest, mô hình tốt nhất (LR hoặc XGB, theo p@10) chỉ được dùng nếu
  1. số người nhận lời trong 10 người đầu mỗi lần kêu gọi NHIỀU HƠN chấm điểm luật một cách chắc chắn: cận dưới khoảng
     tin cậy 95% của phần hơn (so cặp trên cùng lần kêu gọi, bootstrap) phải > 0 — không đặt ngưỡng tùy ý;
  2. AUC cao hơn chấm điểm luật (xếp hạng tốt hơn trên toàn danh sách, không chỉ ở đầu);
  3. xác suất dự đoán lệch tỷ lệ thực tế không quá MAX_CALIBRATION (vì xác suất dùng để tính số người cần mời);
  4. có đủ MIN_TEST_CALLOUTS lần kêu gọi để kiểm tra;
  5. không thay một bản học từ dữ liệu THẬT bằng bản học từ dữ liệu MÔ PHỎNG.
"""
import re
import shutil
from datetime import datetime, timedelta, timezone

from django.conf import settings

from bloodbank.services.forecast_ml.registry import _read, _write

MAX_CALIBRATION = 0.05
MIN_TEST_CALLOUTS = 20


def root():
    return settings.DONOR_AI_MODEL_DIR


def versions_dir():
    return root() / "versions"


def active_meta():
    return _read(root() / "metadata.json")


def versions():
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
    while (versions_dir() / at.strftime("%Y%m%d-%H%M%S")).exists():
        at += timedelta(seconds=1)
    return at.strftime("%Y%m%d-%H%M%S")


def scores(meta):
    return {r["model"]: r for r in (meta or {}).get("backtest") or []}


def best_kind(meta):
    """LR hoặc XGB — bản có p@10 cao hơn (bằng nhau thì chọn LR, đơn giản hơn)."""
    s = scores(meta)
    cands = [k for k in ("LR", "XGB") if (s.get(k) or {}).get("p_at_10") is not None]
    if not cands:
        return None
    return max(cands, key=lambda k: (round(s[k]["p_at_10"], 4), round(s[k].get("auc") or 0, 4), k == "LR"))


def guard(meta, current=None):
    """(đạt?, [lý do không đạt]) theo các điều kiện ở đầu file."""
    reasons = []
    s = scores(meta)
    kind = meta.get("chosen")
    if not kind or "RULE" not in s:
        return False, ["chưa có kết quả backtest"]
    m, rule = s[kind], s["RULE"]
    if (m.get("test_callouts") or 0) < MIN_TEST_CALLOUTS:
        reasons.append(f"mới có {m.get('test_callouts') or 0} lần kêu gọi để kiểm tra (cần ≥ {MIN_TEST_CALLOUTS})")
    if m.get("lift_low") is None or m["lift_low"] <= 0:
        reasons.append(f"10 người đầu: {_pct(m['p_at_10'])} nhận lời so với {_pct(rule['p_at_10'])} của chấm điểm luật — "
                       f"phần hơn chưa chắc chắn (khoảng tin cậy 95%: {_num(m.get('lift_low'))} → "
                       f"{_num(m.get('lift_high'))} người / lần)")
    if m.get("auc") is None or rule.get("auc") is None or m["auc"] <= rule["auc"]:
        reasons.append(f"AUC {m.get('auc') or 0:.3f} không cao hơn chấm điểm luật ({rule.get('auc') or 0:.3f})")
    if m.get("calibration") is None or abs(m["calibration"]) > MAX_CALIBRATION:
        reasons.append(f"xác suất lệch thực tế {_pct(m.get('calibration'), signed=True)} "
                       f"(cho phép ±{MAX_CALIBRATION:.0%})")
    if current and not current.get("synthetic") and meta.get("synthetic"):
        reasons.append("bản đang dùng học từ dữ liệu thật, bản mới chỉ học từ dữ liệu mô phỏng")
    return not reasons, reasons


def _pct(v, signed=False):
    if v is None:
        return "—"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def _num(v):
    return "—" if v is None else f"{v:+.2f}".replace(".", ",")


def save_version(trained, meta):
    from . import model as M

    version = meta.get("version") or new_version()
    meta = M.save(trained, versions_dir() / version, {**meta, "version": version})
    return version, meta


def activate(version):
    if not re.fullmatch(r"\d{8}-\d{6}", version or ""):
        raise FileNotFoundError(version)
    from . import model as M

    src = versions_dir() / version
    meta = _read(src / "metadata.json")
    if not meta or M.load(src)[0] is None:
        raise FileNotFoundError(version)
    meta = {**meta, "version": version, "activated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write(root() / "metadata.json", meta)
    tmp = root() / "model.json.tmp"
    shutil.copyfile(src / "model.json", tmp)          # mtime mới → các tiến trình web tải lại
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
