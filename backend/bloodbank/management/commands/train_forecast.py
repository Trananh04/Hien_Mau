"""Huấn luyện mô hình XGBoost dự báo nhu cầu 14 ngày: backtest so với 2 baseline → lưu phiên bản → chốt chặn.

    python manage.py train_forecast                     # tự chọn: sổ kho nếu đủ dữ liệu, chưa đủ thì dữ liệu mô phỏng
    python manage.py train_forecast --source db         # bắt buộc dữ liệu thật (báo lỗi nếu chưa đủ)
    python manage.py train_forecast --data duong/dan.csv # CSV: cột date, series, blood_group, demand
    python manage.py train_forecast --force              # dùng bản mới dù không qua chốt chặn
    python manage.py train_forecast --list               # các phiên bản đã lưu
    python manage.py train_forecast --activate 20261027-031500   # quay lại một bản cũ

Mỗi lần chạy lưu FORECAST_MODEL_DIR/versions/<phiên bản>/ (mô hình, metadata, kết quả backtest). Bản mới chỉ thay bản
đang dùng khi qua chốt chặn (xem registry.py). Trang Dự báo thiếu hụt chỉ dùng AI khi Quản trị bật `forecast_ai_enabled`.
"""
from django.core.management.base import BaseCommand, CommandError

from bloodbank.services.forecast_ml import registry, training


class Command(BaseCommand):
    help = "Huấn luyện XGBoost dự báo nhu cầu máu 14 ngày (backtest, phiên bản, chốt chặn)"

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=["auto", "db", "csv"], default="auto")
        parser.add_argument("--data", default=None, help="CSV nhu cầu theo ngày (ngầm định --source csv)")
        parser.add_argument("--folds", type=int, default=12)
        parser.add_argument("--force", action="store_true", help="Dùng bản mới dù không qua chốt chặn")
        parser.add_argument("--no-promote", action="store_true", help="Chỉ huấn luyện + lưu phiên bản")
        parser.add_argument("--backtest", action="store_true", help="(giữ cho tương thích — backtest luôn chạy)")
        parser.add_argument("--list", action="store_true")
        parser.add_argument("--activate", default=None, metavar="PHIEN_BAN")

    def handle(self, source, data, folds, force, no_promote, list, activate, **_):
        if list:
            for v in registry.versions():
                xgb = {r["model"]: r for r in v.get("backtest") or []}.get("XGB", {})
                self.stdout.write(f"{'*' if v['active'] else ' '} {v['version']}  {v.get('source', '?'):<4} "
                                  f"WAPE {xgb.get('wape', 0):.1%}  bias {xgb.get('bias', 0):+.1%}  "
                                  + ("qua chốt chặn" if (v.get("guard") or {}).get("passed") else "không qua"))
            return
        if activate:
            try:
                registry.activate(activate)
            except FileNotFoundError:
                raise CommandError(f"Không có phiên bản hợp lệ {activate}")
            self.stdout.write(f"Đang dùng phiên bản {activate}.")
            return
        try:
            meta = training.run("csv" if data else source, data, folds, promote=not no_promote, force=force,
                                log=self.stdout.write)
        except training.NotEnoughData as exc:
            raise CommandError(str(exc))
        self.stdout.write("\nKết quả backtest (càng thấp càng tốt; Bias âm = dự báo thiếu):")
        self.stdout.write(f"  {'Mô hình':<14}{'MAE/ngày':>10}{'WAPE':>8}{'Bias':>8}{'WAPE tổng 14 ngày':>20}")
        for r in meta["backtest"]:
            self.stdout.write(f"  {r['label']:<14}{r['mae']:>10.3f}{r['wape']:>8.1%}{r['bias']:>+8.1%}"
                              f"{r['wape_14d_total']:>20.1%}")
        guard = meta["guard"]
        self.stdout.write(f"Phiên bản {meta['version']}: " + ("QUA chốt chặn" if guard["passed"] else
                          "KHÔNG qua chốt chặn — " + "; ".join(guard["reasons"])))
        self.stdout.write("→ Đang dùng bản này." if meta["promoted"] else "→ Giữ bản đang dùng.")
        if meta["synthetic"]:
            self.stdout.write("Lưu ý: học trên dữ liệu MÔ PHỎNG — chỉ chứng minh hệ thống chạy đúng.")
