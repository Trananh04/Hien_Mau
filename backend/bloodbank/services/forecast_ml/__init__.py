"""AI dự báo nhu cầu khối hồng cầu 14 ngày (XGBoost) — xem docs/huong-dan-ai-du-bao-thieu-mau.md.

params    — tham số mô phỏng, mỗi số kèm nguồn hoặc ghi "GIẢ ĐỊNH"
simulate  — sinh lịch sử nhu cầu mô phỏng (CSV riêng, không ghi vào sổ kho)
features  — đặc trưng dự báo trực tiếp 14 bước, không dùng dữ liệu tương lai
model     — huấn luyện XGBoost, 2 baseline, backtest trượt, lưu / tải
predict   — dự báo cho dòng tồn kho thật từ sổ kho (trang Dự báo thiếu hụt)
"""
