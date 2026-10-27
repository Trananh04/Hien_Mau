"""Hằng số dùng chung của mô hình dự báo — module nhẹ (không nạp numpy/pandas/xgboost), để trang web chỉ ĐỌC kết quả
dự báo đã lưu mà không phải nạp thư viện huấn luyện vào từng worker."""
HORIZON = 14
HISTORY_DAYS = 28                      # cần tối thiểu 28 ngày lịch sử để có đủ đặc trưng
BLOOD_GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
FEATURES = ["h", "dow", "month", "tet", "blood_group",
            "last_1", "last_7", "last_14", "mean_7", "mean_28", "std_28", "nonzero_28", "same_weekday_4"]
