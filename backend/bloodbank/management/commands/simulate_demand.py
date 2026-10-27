"""Sinh lịch sử nhu cầu khối hồng cầu MÔ PHỎNG ra file CSV (không ghi vào sổ kho), kèm file tham số + nguồn.

    python manage.py simulate_demand                      # 540 ngày, kết thúc hôm nay, seed 42
    python manage.py simulate_demand --days 720 --seed 7
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from bloodbank.services.forecast_ml import params, simulate


class Command(BaseCommand):
    help = "Sinh dữ liệu nhu cầu máu mô phỏng (CSV) để huấn luyện thử mô hình dự báo"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=540)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--out", default=None, help="Thư mục ghi (mặc định FORECAST_MODEL_DIR/sim)")

    def handle(self, days, seed, out, **_):
        out = Path(out) if out else settings.FORECAST_MODEL_DIR / "sim"
        out.mkdir(parents=True, exist_ok=True)
        df = simulate.simulate(days=days, seed=seed)
        df.to_csv(out / "demand.csv", index=False)
        (out / "params.json").write_text(json.dumps({"seed": seed, "days": days, "params": params.SIM_PARAMS},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
        per_day = df.groupby(["hospital", "tier"])["demand"].sum() / days
        self.stdout.write(f"Đã ghi {len(df):,} dòng ({df['date'].min():%d/%m/%Y} → {df['date'].max():%d/%m/%Y}) "
                          f"vào {out / 'demand.csv'}")
        self.stdout.write("Nhu cầu khối hồng cầu trung bình/ngày (mọi nhóm máu):")
        for (hospital, tier), v in per_day.items():
            self.stdout.write(f"  {hospital:<10} hạng {tier:<4} {v:5.1f}")
        self.stdout.write(f"Tỷ lệ chưa đáp ứng: {df['unmet'].sum() / max(df['demand'].sum(), 1):.1%} · "
                          f"ngày-chuỗi bằng 0: {(df['demand'] == 0).mean():.0%}")
