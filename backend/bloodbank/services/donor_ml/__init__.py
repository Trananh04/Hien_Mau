"""AI gợi ý người hiến: dự đoán KHẢ NĂNG NHẬN LỜI của từng người được mời, dùng để xếp hạng danh sách gợi ý.

Kiến trúc 2 tầng — AI không bao giờ quyết định ai được mời:
  1. Luật (donor_match.suggest): lọc cứng nhóm máu, tuổi, thời gian nghỉ, giới hạn số lời mời → TẬP ứng viên an toàn;
  2. Mô hình (module này): ước lượng P(nhận lời trong N ngày) cho từng ứng viên → XẾP LẠI thứ tự + giải thích.

  features  — đặc trưng tại thời điểm mời (một nguồn cho cả lúc học và lúc dùng)
  history   — dữ liệu học từ lịch sử kêu gọi thật (mỗi lời mời = một dòng, nhãn = có nhận lời không)
  simulate  — dữ liệu mô phỏng khi chưa đủ dữ liệu thật (ghi rõ là mô phỏng)
  model     — hồi quy logistic + XGBoost, so với mốc "chấm điểm luật", backtest theo thời gian
  registry  — phiên bản mô hình + chốt chặn
  training  — một lần huấn luyện: dữ liệu → backtest → chốt chặn → lưu / dùng bản mới
  predict   — xếp hạng lúc gợi ý: xác suất, yếu tố chính, dành chỗ cho người mới
  monitor   — theo dõi tỷ lệ nhận lời thực tế, tự học lại khi có lý do, tự tắt khi AI lệch nhiều
"""
