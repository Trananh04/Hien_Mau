"""Huấn luyện AI gợi ý người hiến: backtest 3 cách (chấm điểm luật / hồi quy logistic / XGBoost) → chọn → chốt chặn.

    python manage.py train_donor_model                  # tự chọn: lịch sử thật nếu đủ, chưa đủ thì dữ liệu mô phỏng
    python manage.py train_donor_model --source db      # bắt buộc dữ liệu thật (báo lỗi nếu chưa đủ)
    python manage.py train_donor_model --source sim     # dữ liệu mô phỏng
    python manage.py train_donor_model --resimulate     # sinh lại dữ liệu mô phỏng trước khi học
    python manage.py train_donor_model --force          # dùng bản mới dù không qua chốt chặn
    python manage.py train_donor_model --list           # các phiên bản đã lưu
    python manage.py train_donor_model --activate 20261104-031500   # quay lại một bản cũ

Mỗi lần chạy lưu DONOR_AI_MODEL_DIR/versions/<phiên bản>/. Bản mới chỉ thay bản đang dùng khi qua chốt chặn (registry.py).
Màn Gợi ý người hiến chỉ xếp theo AI khi Quản trị bật `donor_ai_enabled`.
"""
from django.core.management.base import BaseCommand, CommandError

from bloodbank.services.donor_ml import model, registry, training


class Command(BaseCommand):
    help = "Huấn luyện AI gợi ý người hiến (dự đoán khả năng nhận lời; backtest, phiên bản, chốt chặn)"

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=["auto", "db", "sim"], default="auto")
        parser.add_argument("--folds", type=int, default=4)
        parser.add_argument("--force", action="store_true", help="Dùng bản mới dù không qua chốt chặn")
        parser.add_argument("--no-promote", action="store_true", help="Chỉ huấn luyện + lưu phiên bản")
        parser.add_argument("--resimulate", action="store_true", help="Sinh lại dữ liệu mô phỏng")
        parser.add_argument("--list", action="store_true")
        parser.add_argument("--activate", default=None, metavar="PHIEN_BAN")

    def handle(self, source, folds, force, no_promote, resimulate, list, activate, **_):
        if list:
            for v in registry.versions():
                s = registry.scores(v)
                chosen = s.get(v.get("chosen")) or {}
                self.stdout.write(f"{'*' if v['active'] else ' '} {v['version']}  {v.get('source', '?'):<3} "
                                  f"{v.get('chosen') or '?':<3} p@10 {chosen.get('p_at_10') or 0:.1%} "
                                  f"(luật {(s.get('RULE') or {}).get('p_at_10') or 0:.1%})  "
                                  + ("qua chốt chặn" if (v.get("guard") or {}).get("passed") else "không qua"))
            return
        if activate:
            try:
                registry.activate(activate)
            except FileNotFoundError:
                raise CommandError(f"Không có phiên bản hợp lệ {activate}")
            self.stdout.write(f"Đang dùng phiên bản {activate}.")
            return
        if resimulate:
            training.sim_path().unlink(missing_ok=True)
        try:
            meta = training.run(source, folds, promote=not no_promote, force=force, log=self.stdout.write)
        except training.NotEnoughData as exc:
            raise CommandError(str(exc))
        self.stdout.write("\nKết quả kiểm tra (trên các lần kêu gọi mô hình chưa thấy):")
        self.stdout.write(f"  {'Cách xếp hạng':<20}{'Nhận lời/10 đầu':>17}{'Người/lần':>11}{'Hơn luật (95%)':>26}"
                          f"{'AUC':>8}{'Lệch xác suất':>15}")
        for r in meta["backtest"]:
            cal = "—" if r.get("calibration") is None else f"{r['calibration']:+.1%}"
            gain = ("—" if r.get("lift") is None else
                    f"{r['lift']:+.2f} ({r['lift_low']:+.2f} → {r['lift_high']:+.2f})")
            self.stdout.write(f"  {r['label']:<20}{r['p_at_10']:>17.1%}{r['hits_at_10']:>11.2f}{gain:>26}"
                              f"{r['auc']:>8.3f}{cal:>15}")
        guard = meta["guard"]
        self.stdout.write(f"Phiên bản {meta['version']} ({model.MODELS[meta['chosen']]}): " +
                          ("QUA chốt chặn" if guard["passed"] else "KHÔNG qua chốt chặn — " + "; ".join(guard["reasons"])))
        if meta["promoted"]:
            self.stdout.write(self.style.SUCCESS("Đang dùng bản này. Bật ở Quản trị → AI gợi ý người hiến "
                                                 "(hoặc cấu hình donor_ai_enabled)."))
        else:
            self.stdout.write("Giữ bản đang dùng.")
