"""Huấn luyện mô hình XGBoost dự báo nhu cầu 14 ngày; tùy chọn backtest trượt so với 2 baseline.

    python manage.py train_forecast --backtest              # dữ liệu mô phỏng (FORECAST_MODEL_DIR/sim/demand.csv)
    python manage.py train_forecast --data duong/dan.csv     # CSV khác: cột date, series, blood_group, demand

Ghi ra FORECAST_MODEL_DIR: model.json, metadata.json (nguồn dữ liệu, chỉ số), evaluation.csv, evaluation_by_h.csv.
Mô hình chỉ được dùng trên trang Dự báo thiếu hụt khi Quản trị bật cấu hình `forecast_ai_enabled`.
"""
import time
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bloodbank.services.forecast_ml import features, model
from bloodbank.services.forecast_ml.simulate import tet_flags


class Command(BaseCommand):
    help = "Huấn luyện XGBoost dự báo nhu cầu máu 14 ngày (+ backtest so với baseline)"

    def add_arguments(self, parser):
        parser.add_argument("--data", default=None, help="CSV nhu cầu theo ngày (mặc định: dữ liệu mô phỏng)")
        parser.add_argument("--backtest", action="store_true", help="Đánh giá trượt trước khi huấn luyện bản cuối")
        parser.add_argument("--folds", type=int, default=12)

    def handle(self, data, backtest, folds, **_):
        out = settings.FORECAST_MODEL_DIR
        path = Path(data) if data else out / "sim" / "demand.csv"
        if not path.exists():
            raise CommandError(f"Không thấy {path}. Chạy trước: python manage.py simulate_demand")
        raw = pd.read_csv(path, parse_dates=["date"])
        synthetic = bool(raw.get("is_synthetic", pd.Series([0])).max())
        if "series" not in raw:
            raw["series"] = raw["hospital"]
        daily = features.fill_days(raw[["date", "series", "blood_group", "demand"]])
        t0 = time.time()
        examples = features.build_all(daily, tet_flags)
        self.stdout.write(f"Dữ liệu: {path.name} · {daily['series'].nunique()} bệnh viện × "
                          f"{daily['blood_group'].nunique()} nhóm máu · {daily['date'].nunique()} ngày · "
                          f"{len(examples):,} dòng huấn luyện ({time.time() - t0:.1f}s)"
                          + (" · DỮ LIỆU MÔ PHỎNG" if synthetic else ""))
        meta = {"data_file": str(path.name), "synthetic": synthetic, "rows": len(examples),
                "date_from": str(daily["date"].min().date()), "date_to": str(daily["date"].max().date())}
        if backtest:
            self.stdout.write(f"Backtest trượt {folds} mốc, mỗi mốc 14 ngày:")
            summary, by_h, per_fold = model.backtest(examples, folds=folds, log=self.stdout.write)
            summary.to_csv(out / "evaluation.csv", index=False)
            by_h.to_csv(out / "evaluation_by_h.csv", index=False)
            per_fold.to_csv(out / "evaluation_folds.csv", index=False)
            self.stdout.write("\nKết quả (càng thấp càng tốt; Bias âm = dự báo thiếu):")
            self.stdout.write(f"  {'Mô hình':<14}{'MAE/ngày':>10}{'WAPE':>8}{'Bias':>8}{'WAPE tổng 14 ngày':>20}")
            for r in summary.itertuples():
                self.stdout.write(f"  {r.label:<14}{r.mae:>10.3f}{r.wape:>8.1%}{r.bias:>+8.1%}{r.wape_14d_total:>20.1%}")
            best = summary.set_index("model")
            meta["backtest"] = summary.to_dict(orient="records")
            meta["beats_baseline"] = bool(best.loc["XGB", "wape"] < min(best.loc["B0", "wape"], best.loc["B1", "wape"]))
            self.stdout.write("XGBoost " + ("THẮNG" if meta["beats_baseline"] else "KHÔNG thắng")
                              + " cả hai baseline về WAPE.")
        t0 = time.time()
        final = model.train(examples)
        meta["trees"] = int(final.best_iteration + 1)
        model.save(final, out, meta)
        self.stdout.write(f"Đã lưu mô hình ({meta['trees']} cây, {time.time() - t0:.1f}s) vào {out}")
        if synthetic:
            self.stdout.write("Lưu ý: mô hình học trên dữ liệu MÔ PHỎNG — chỉ chứng minh hệ thống chạy đúng.")
