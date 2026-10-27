"""Tham số mô phỏng nhu cầu khối hồng cầu — mỗi tham số có `value` và `source` (in thẳng vào báo cáo).

Tham số ghi "GIẢ ĐỊNH" là chưa có số liệu công bố, cần đối chiếu khi có dữ liệu thật.
"""

SIM_PARAMS = {
    "abo_share": {
        "value": {"O": 0.435, "B": 0.303, "A": 0.206, "AB": 0.056},
        "source": "Tỷ lệ nhóm máu ABO ở 71.695 người bệnh, BV Hữu nghị Việt Đức 2024 (Tạp chí Y học Cộng đồng)",
    },
    "rh_negative_share": {
        "value": 0.0019,
        "source": "Cùng nghiên cứu BV Hữu nghị Việt Đức 2024: Rh(D) âm 0,188%",
    },
    # Bộ Hugging Face: trung vị units_requested_month của khối hồng cầu, mỗi dòng = 1 cơ sở × 1 chế phẩm × 1 nhóm
    # máu × 1 tháng (national 250, district 50, rural 8 đơn vị/tháng). Coi đó là nhu cầu nhóm O (nhóm phổ biến
    # nhất) của cơ sở cùng hạng → tổng mọi nhóm = giá trị / 30 ngày / tỷ lệ nhóm O.
    "hospital_rbc_per_day": {
        "value": {"lon": round(250 / 30 / 0.435, 1), "vua": round(50 / 30 / 0.435, 1), "nho": round(8 / 30 / 0.435, 1)},
        "source": "electricsheepafrica/blood-bank-supply-management (CC BY 4.0, dữ liệu mô phỏng): trung vị "
                  "units_requested_month khối hồng cầu theo hạng cơ sở ÷ 30 ÷ tỷ lệ nhóm O",
    },
    "monthly_cv": {
        "value": 0.08,
        "source": "Cùng bộ Hugging Face: khoảng p10–p90 ≈ ±8% quanh trung vị theo tháng (cơ sở hạng lớn)",
    },
    "fill_rate": {
        "value": 0.956,
        "source": "BV Nguyễn Tri Phương 2021–2023: đơn vị cung ứng đáp ứng ≥ 95,6% nhu cầu (vnras.com)",
    },
    "weekday_factor": {
        "value": [1.15, 1.10, 1.05, 1.05, 1.00, 0.85, 0.80],     # thứ 2 … chủ nhật
        "source": "GIẢ ĐỊNH — ca mổ phiên dồn ngày thường, cuối tuần chủ yếu cấp cứu",
    },
    "tet_factor": {
        "value": 0.80,
        "source": "GIẢ ĐỊNH — giảm mổ phiên quanh Tết (2 ngày trước đến 4 ngày sau mùng 1)",
    },
    "yearly_trend": {
        "value": 0.03,
        "source": "GIẢ ĐỊNH — nhu cầu tăng nhẹ 3%/năm",
    },
    "trauma_spike": {
        "value": {"daily_prob": 0.01, "extra_mean": 4},
        "source": "GIẢ ĐỊNH — khoảng 1%/ngày có ca đa chấn thương cần thêm trung bình 4 đơn vị (chia theo nhóm máu)",
    },
    "hospitals": {
        "value": [("SIM-LON-1", "lon"), ("SIM-VUA-1", "vua"), ("SIM-VUA-2", "vua"), ("SIM-VUA-3", "vua"),
                  ("SIM-NHO-1", "nho"), ("SIM-NHO-2", "nho")],
        "source": "GIẢ ĐỊNH — 6 bệnh viện mô phỏng: 1 hạng lớn, 3 hạng vừa, 2 hạng nhỏ",
    },
}

# Mùng 1 Tết Nguyên đán (dương lịch)
TET_DATES = {2023: "2023-01-22", 2024: "2024-02-10", 2025: "2025-01-29", 2026: "2026-02-17", 2027: "2027-02-06",
             2028: "2028-01-26"}
TET_WINDOW = (-2, 4)          # 2 ngày trước → 4 ngày sau mùng 1


def value(key):
    return SIM_PARAMS[key]["value"]
