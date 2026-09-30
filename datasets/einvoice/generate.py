"""Sinh database hóa đơn điện tử giả lập trên ClickHouse (database `einvoice`).

Chạy (cần container ClickHouse của docker compose và CLICKHOUSE_PASSWORD trong .env):
  python datasets/einvoice/generate.py                 # quy mô 1.0: ~30 triệu hóa đơn, ~100 triệu dòng hàng
  python datasets/einvoice/generate.py --scale 0.02    # bản nhỏ để thử nhanh
  python datasets/einvoice/generate.py --access-only   # chỉ áp dụng lại user/role (access.sql)

Dữ liệu sinh hoàn toàn bên trong ClickHouse (INSERT ... SELECT FROM numbers()), giá trị "ngẫu nhiên" lấy từ
cityHash64(khóa, ...) nên chạy lại cho đúng cùng dữ liệu. Số DN (50.000) và người mua (2 triệu) cố định; --scale
chỉ đổi số hóa đơn / log. Khoảng thời gian 2023-01-01 .. 2025-06-30 ("hôm nay" của dự án).

Các bẫy cố ý giống ClickHouse thật (tài liệu nghiệp vụ ở schema_docs.json):
  - invoices là ReplacingMergeTree(version): hóa đơn đổi trạng thái có nhiều phiên bản -> phải dùng FINAL.
    Bảng tắt merge (max_bytes_to_merge_* = 1) để các bản ghi trùng giữ nguyên, kết quả đánh giá không đổi theo thời gian.
  - tax_messages.sent_at / api_requests.ts lưu UTC; invoices.issued_at theo giờ Việt Nam.
  - Hóa đơn ngoại tệ (USD/EUR): số tiền là nguyên tệ, phải nhân exchange_rate.
  - daily_seller_stats là AggregatingMergeTree: cột SimpleAggregateFunction phải sum(), cột buyers phải uniqExactMerge().
  - Thuế suất 10% giảm còn 8% từ 2023-07-01 cho nhóm hàng được giảm (Nghị quyết giảm thuế GTGT).
"""
import argparse
import os
import sys
import time
from datetime import date
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import t2sql  # noqa: E402,F401  (nạp .env)

DB = "einvoice"
N_SELLERS = 50_000
N_BUYERS = 2_000_000
TODAY = date(2025, 6, 30)
MONTHS = [(y, m) for y in (2023, 2024, 2025) for m in range(1, 13) if (y, m) <= (2025, 6)]
INVOICES_PER_MONTH = 1_000_000
API_REQUESTS_TOTAL = 40_000_000
SEASON = {1: 1.05, 2: 0.82, 3: 1.0, 4: 0.97, 5: 1.0, 6: 1.02, 7: 0.98, 8: 1.0, 9: 1.0, 10: 1.03, 11: 1.06, 12: 1.22}


# ----------------------------------------------------------------------------- tiện ích sinh SQL
def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def arr(values):
    return "[" + ", ".join(arr(v) if isinstance(v, list) else q(v) for v in values) + "]"


def H(key, *parts):
    return f"cityHash64({', '.join(parts)}, '{key}')"


def U(key, *parts):
    """Số giả ngẫu nhiên trong [0, 1)."""
    return f"({H(key, *parts)} % 1000000 / 1000000.0)"


def rnd(x):
    """Làm tròn theo loại tiền: VND tới đồng, ngoại tệ 2 chữ số (round() cần số chữ số là hằng)."""
    return f"if(dec = 0, round({x}), round({x}, 2))"


def pick(key, parts, weighted):
    """Chọn giá trị theo trọng số: weighted = [(giá trị, trọng số nguyên), ...]."""
    values = [v for v, w in weighted for _ in range(w)]
    return f"{arr(values)}[1 + {H(key, *parts)} % {len(values)}]"


# ----------------------------------------------------------------------------- dữ liệu tĩnh
PROVINCES = [
    ("01", "Hà Nội", "Miền Bắc"), ("02", "Hà Giang", "Miền Bắc"), ("04", "Cao Bằng", "Miền Bắc"),
    ("06", "Bắc Kạn", "Miền Bắc"), ("08", "Tuyên Quang", "Miền Bắc"), ("10", "Lào Cai", "Miền Bắc"),
    ("11", "Điện Biên", "Miền Bắc"), ("12", "Lai Châu", "Miền Bắc"), ("14", "Sơn La", "Miền Bắc"),
    ("15", "Yên Bái", "Miền Bắc"), ("17", "Hòa Bình", "Miền Bắc"), ("19", "Thái Nguyên", "Miền Bắc"),
    ("20", "Lạng Sơn", "Miền Bắc"), ("22", "Quảng Ninh", "Miền Bắc"), ("24", "Bắc Giang", "Miền Bắc"),
    ("25", "Phú Thọ", "Miền Bắc"), ("26", "Vĩnh Phúc", "Miền Bắc"), ("27", "Bắc Ninh", "Miền Bắc"),
    ("30", "Hải Dương", "Miền Bắc"), ("31", "Hải Phòng", "Miền Bắc"), ("33", "Hưng Yên", "Miền Bắc"),
    ("34", "Thái Bình", "Miền Bắc"), ("35", "Hà Nam", "Miền Bắc"), ("36", "Nam Định", "Miền Bắc"),
    ("37", "Ninh Bình", "Miền Bắc"), ("38", "Thanh Hóa", "Miền Trung"), ("40", "Nghệ An", "Miền Trung"),
    ("42", "Hà Tĩnh", "Miền Trung"), ("44", "Quảng Bình", "Miền Trung"), ("45", "Quảng Trị", "Miền Trung"),
    ("46", "Thừa Thiên Huế", "Miền Trung"), ("48", "Đà Nẵng", "Miền Trung"), ("49", "Quảng Nam", "Miền Trung"),
    ("51", "Quảng Ngãi", "Miền Trung"), ("52", "Bình Định", "Miền Trung"), ("54", "Phú Yên", "Miền Trung"),
    ("56", "Khánh Hòa", "Miền Trung"), ("58", "Ninh Thuận", "Miền Trung"), ("60", "Bình Thuận", "Miền Trung"),
    ("62", "Kon Tum", "Tây Nguyên"), ("64", "Gia Lai", "Tây Nguyên"), ("66", "Đắk Lắk", "Tây Nguyên"),
    ("67", "Đắk Nông", "Tây Nguyên"), ("68", "Lâm Đồng", "Tây Nguyên"), ("70", "Bình Phước", "Miền Nam"),
    ("72", "Tây Ninh", "Miền Nam"), ("74", "Bình Dương", "Miền Nam"), ("75", "Đồng Nai", "Miền Nam"),
    ("77", "Bà Rịa - Vũng Tàu", "Miền Nam"), ("79", "TP. Hồ Chí Minh", "Miền Nam"), ("80", "Long An", "Miền Nam"),
    ("82", "Tiền Giang", "Miền Nam"), ("83", "Bến Tre", "Miền Nam"), ("84", "Trà Vinh", "Miền Nam"),
    ("86", "Vĩnh Long", "Miền Nam"), ("87", "Đồng Tháp", "Miền Nam"), ("89", "An Giang", "Miền Nam"),
    ("91", "Kiên Giang", "Miền Nam"), ("92", "Cần Thơ", "Miền Nam"), ("93", "Hậu Giang", "Miền Nam"),
    ("94", "Sóc Trăng", "Miền Nam"), ("95", "Bạc Liêu", "Miền Nam"), ("96", "Cà Mau", "Miền Nam"),
]
BIG = {"01": 30, "79": 36, "48": 5, "31": 5, "74": 5, "75": 4, "27": 3, "92": 2, "22": 2, "56": 2}
PROVINCE_WEIGHTS = [(c, BIG.get(c, 1)) for c, _, _ in PROVINCES]
CHI_CUC = {"01": 8, "79": 10, "48": 3, "31": 3, "74": 3, "75": 3}

INDUSTRIES = [
    ("A", "Nông nghiệp, lâm nghiệp và thủy sản"), ("B", "Khai khoáng"),
    ("C", "Công nghiệp chế biến, chế tạo"), ("D", "Sản xuất và phân phối điện, khí đốt"),
    ("E", "Cung cấp nước, quản lý và xử lý rác thải"), ("F", "Xây dựng"),
    ("G", "Bán buôn và bán lẻ; sửa chữa ô tô, mô tô"), ("H", "Vận tải kho bãi"),
    ("I", "Dịch vụ lưu trú và ăn uống"), ("J", "Thông tin và truyền thông"),
    ("K", "Hoạt động tài chính, ngân hàng và bảo hiểm"), ("L", "Hoạt động kinh doanh bất động sản"),
    ("M", "Hoạt động chuyên môn, khoa học và công nghệ"), ("N", "Hoạt động hành chính và dịch vụ hỗ trợ"),
    ("O", "Quản lý nhà nước, an ninh quốc phòng"), ("P", "Giáo dục và đào tạo"),
    ("Q", "Y tế và hoạt động trợ giúp xã hội"), ("R", "Nghệ thuật, vui chơi và giải trí"),
    ("S", "Hoạt động dịch vụ khác"), ("T", "Hoạt động làm thuê trong hộ gia đình"),
    ("U", "Hoạt động của các tổ chức quốc tế"),
]
INDUSTRY_WEIGHTS = [("G", 34), ("C", 14), ("F", 10), ("H", 7), ("I", 8), ("J", 5), ("M", 5), ("N", 4), ("K", 2),
                    ("L", 3), ("P", 2), ("Q", 2), ("A", 2), ("S", 1), ("R", 1)]
DOMAIN_WORD = {"G": "Thương mại", "C": "Sản xuất", "F": "Xây dựng", "H": "Vận tải", "I": "Dịch vụ Ăn uống",
               "J": "Công nghệ", "M": "Tư vấn", "N": "Dịch vụ", "K": "Đầu tư Tài chính", "L": "Bất động sản",
               "P": "Giáo dục", "Q": "Y tế", "A": "Nông nghiệp"}

SERVICE_PLANS = [  # plan_id, tên, loại, số HĐ (None = không giới hạn), giá (VND), số tháng hiệu lực (None = không hạn)
    (1, "Gói 300 hóa đơn", "theo_so_luong", 300, 390_000, None),
    (2, "Gói 500 hóa đơn", "theo_so_luong", 500, 550_000, None),
    (3, "Gói 1.000 hóa đơn", "theo_so_luong", 1000, 890_000, None),
    (4, "Gói 2.000 hóa đơn", "theo_so_luong", 2000, 1_590_000, None),
    (5, "Gói 5.000 hóa đơn", "theo_so_luong", 5000, 3_290_000, None),
    (6, "Gói 10.000 hóa đơn", "theo_so_luong", 10000, 5_490_000, None),
    (7, "Gói 50.000 hóa đơn", "theo_so_luong", 50000, 19_900_000, None),
    (8, "Gói không giới hạn 12 tháng", "theo_thoi_gian", None, 12_900_000, 12),
    (9, "Gói doanh nghiệp lớn (API) 12 tháng", "theo_thoi_gian", None, 32_000_000, 12),
]
TAX_ERRORS = [
    ("KTMST01", "Mã số thuế người bán không hợp lệ hoặc đã ngừng hoạt động", "nguoi_ban"),
    ("KTMST02", "Mã số thuế người mua sai định dạng", "nguoi_mua"),
    ("KTMST03", "Mã số thuế người mua không tồn tại", "nguoi_mua"),
    ("CKS01", "Chữ ký số không hợp lệ", "chu_ky_so"),
    ("CKS02", "Chứng thư số hết hiệu lực tại thời điểm ký", "chu_ky_so"),
    ("DD01", "Dữ liệu hóa đơn sai định dạng XML", "dinh_dang"),
    ("DD02", "Thiếu thông tin bắt buộc trên hóa đơn", "dinh_dang"),
    ("TT01", "Tổng tiền không khớp với chi tiết hàng hóa", "du_lieu"),
    ("TT02", "Thuế suất không phù hợp tại thời điểm lập hóa đơn", "du_lieu"),
    ("KH01", "Ký hiệu hóa đơn chưa được đăng ký sử dụng", "ky_hieu"),
    ("TRUNG01", "Trùng số hóa đơn", "du_lieu"),
    ("HT01", "Lỗi kết nối hệ thống của cơ quan thuế", "ky_thuat"),
    ("HT02", "Hết thời gian chờ phản hồi từ cơ quan thuế", "ky_thuat"),
]
REJECT_WEIGHTS = [("KTMST02", 25), ("KTMST03", 20), ("TT01", 15), ("TT02", 12), ("DD02", 10), ("CKS02", 6),
                  ("KH01", 5), ("DD01", 3), ("CKS01", 2), ("KTMST01", 1), ("TRUNG01", 1)]
CA_PROVIDERS = [("VietSign CA", 30), ("SafeCert", 22), ("TrustKey", 18), ("SignOne", 14), ("CertPlus", 10),
                ("eKey Việt", 6)]

BRANDS = ["An Phát", "Bảo Minh", "Bình An", "Đại Phát", "Đông Á", "Gia Huy", "Hà Thành", "Hải Long", "Hoàng Gia",
          "Hoàng Long", "Hồng Phúc", "Hưng Thịnh", "Kim Long", "Kim Ngân", "Lạc Hồng", "Long Hải", "Mai Linh",
          "Minh Anh", "Minh Châu", "Minh Khang", "Minh Phát", "Nam Á", "Nam Việt", "Ngọc Lan", "Nhật Minh",
          "Phú Hưng", "Phúc An", "Phúc Thịnh", "Phương Đông", "Quang Minh", "Sao Mai", "Sài Gòn Xanh", "Song Hà",
          "Tân Á", "Tân Phát", "Tân Tiến", "Thái Bình Dương", "Thành Công", "Thành Đạt", "Thiên Long",
          "Thịnh Vượng", "Toàn Cầu", "Trường An", "Trường Thành", "Trí Việt", "Vạn Lộc", "Vạn Xuân", "Việt Á",
          "Việt Hưng", "Việt Nhật", "Việt Tiến", "Vĩnh Phát", "Xuân Mai", "Á Châu", "Ánh Dương", "Đất Việt",
          "Hòa Bình", "Kiến Việt", "Tâm Đức", "Nhân Hòa"]
SUFFIXES = ["", " Miền Bắc", " Miền Nam", " Sài Gòn", " Hà Nội", " Đà Nẵng", " Việt Nam", " Group", " Plus", " Star",
            " Green", " Link", " Home", " Land", " Quốc Tế", " Hoàn Cầu", " 68", " 79", " 86", " 88", " 99",
            " Cửu Long", " Tây Nguyên", " Bắc Ninh", " Hải Phòng", " Mekong", " Sông Hồng", " Phương Nam",
            " Đông Dương", " Thủ Đô", " Hạ Long", " Thăng Long", " Gia Định", " Đồng Nai", " Tây Đô", " Kinh Bắc",
            " Trường Sơn", " Hùng Vương", " Bến Thành", " Phố Hiến"]
HO = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô",
      "Dương", "Lý"]
DEM = ["Văn", "Thị", "Minh", "Ngọc", "Quốc", "Thanh", "Hữu", "Đức", "Thu", "Hoài", "Gia", "Bảo"]
TEN = ["An", "Bình", "Châu", "Dũng", "Giang", "Hà", "Hải", "Hạnh", "Hiếu", "Hoa", "Hùng", "Hương", "Khánh", "Lan",
       "Linh", "Long", "Mai", "Minh", "Nam", "Nga", "Phong", "Phúc", "Quân", "Quang", "Sơn", "Tâm", "Thảo",
       "Thắng", "Trang", "Trung", "Tuấn", "Vân", "Vy", "Yến"]

# Nhóm hàng hóa: tên, thuế suất gốc (-1 = KCT), được giảm 10% -> 8% hay không, tên hàng, đơn vị, giá min/max (VND), SL min/max
GROUPS = [
    ("Thiết bị điện tử", 10, 1, ["Laptop văn phòng", "Màn hình 24 inch", "Máy in laser", "Bộ phát Wi-Fi",
                                 "Ổ cứng SSD 1TB", "Bàn phím không dây", "Máy chiếu"], ["cái", "bộ"], 300e3, 35e6, 1, 10),
    ("Thiết bị văn phòng", 10, 1, ["Giấy A4", "Bút bi", "Bìa hồ sơ", "Mực in", "Ghế xoay văn phòng",
                                   "Bàn làm việc", "Tủ tài liệu"], ["ram", "hộp", "cái", "chiếc"], 20e3, 6e6, 1, 100),
    ("Đồ uống và thực phẩm chế biến", 10, 1, ["Nước khoáng thùng 24 chai", "Bia lon thùng 24", "Cà phê rang xay",
                                              "Bánh quy hộp", "Mì ăn liền thùng", "Nước ngọt thùng 24",
                                              "Sữa tươi thùng"], ["thùng", "hộp", "kg"], 50e3, 900e3, 1, 200),
    ("Thực phẩm tươi sống", 5, 0, ["Gạo ST25", "Thịt heo", "Cá basa phi lê", "Rau củ tổng hợp", "Trứng gà",
                                   "Trái cây"], ["kg", "khay", "thùng"], 20e3, 400e3, 5, 200),
    ("Vật liệu xây dựng", 10, 1, ["Xi măng PCB40", "Gạch ốp lát", "Cát xây dựng", "Đá 1x2", "Sơn nước",
                                  "Ống nhựa PVC"], ["bao", "m2", "m3", "thùng", "cây"], 50e3, 3e6, 5, 500),
    ("Sắt thép", 10, 0, ["Thép cuộn D8", "Thép thanh vằn D16", "Thép hộp mạ kẽm", "Tôn lạnh"], ["kg"],
     14e3, 24e3, 100, 5000),
    ("Xăng dầu", 10, 0, ["Xăng RON 95-III", "Xăng E5 RON 92", "Dầu DO 0,05S"], ["lít"], 18e3, 26e3, 20, 2000),
    ("Dịch vụ vận tải", 10, 1, ["Cước vận chuyển nội địa", "Phí giao hàng chặng cuối", "Thuê xe tải 5 tấn",
                                "Phí lưu kho"], ["chuyến", "đơn", "ngày"], 30e3, 15e6, 1, 60),
    ("Dịch vụ ăn uống", 10, 1, ["Suất ăn công nghiệp", "Tiệc hội nghị", "Set menu", "Đồ uống tại chỗ",
                                "Buffet trưa"], ["suất", "bàn", "phần"], 30e3, 4e6, 1, 300),
    ("Phần mềm và dịch vụ CNTT", 10, 0, ["Bản quyền phần mềm kế toán", "Dịch vụ triển khai phần mềm",
                                         "Phí duy trì hệ thống", "Dịch vụ lưu trữ đám mây", "Gói hỗ trợ kỹ thuật",
                                         "Thiết kế website"], ["gói", "tháng", "năm"], 500e3, 60e6, 1, 12),
    ("Viễn thông", 10, 0, ["Cước Internet cáp quang", "Cước di động trả sau", "Thuê kênh truyền riêng",
                           "Dịch vụ tổng đài"], ["tháng", "thuê bao"], 150e3, 25e6, 1, 50),
    ("Dịch vụ tư vấn", 10, 1, ["Phí tư vấn thuế", "Phí dịch vụ kế toán", "Phí kiểm toán báo cáo tài chính",
                               "Tư vấn pháp lý", "Tư vấn quản trị"], ["gói", "tháng", "hợp đồng"], 2e6, 60e6, 1, 6),
    ("Cho thuê bất động sản", 10, 0, ["Tiền thuê văn phòng", "Phí quản lý tòa nhà", "Tiền thuê kho bãi",
                                      "Phí gửi xe"], ["tháng", "m2"], 1e6, 120e6, 1, 3),
    ("Giáo dục và đào tạo", -1, 0, ["Học phí khóa đào tạo kỹ năng", "Học phí tiếng Anh doanh nghiệp",
                                    "Phí đào tạo nội bộ", "Học phí lớp kế toán thực hành"], ["khóa", "học viên"],
     1e6, 30e6, 1, 40),
    ("Dịch vụ y tế", -1, 0, ["Khám sức khỏe định kỳ", "Xét nghiệm tổng quát", "Gói tiêm chủng",
                             "Khám chuyên khoa"], ["lượt", "gói"], 200e3, 5e6, 1, 300),
    ("Nông sản và vật tư nông nghiệp", 5, 0, ["Phân bón NPK", "Thức ăn chăn nuôi", "Giống lúa",
                                              "Thuốc bảo vệ thực vật"], ["bao", "kg", "chai"], 30e3, 1.5e6, 5, 1000),
    ("Hàng xuất khẩu", 0, 0, ["Hàng may mặc xuất khẩu", "Linh kiện điện tử xuất khẩu", "Cà phê nhân xuất khẩu",
                              "Hạt điều xuất khẩu", "Đồ gỗ nội thất xuất khẩu"], ["cái", "kg", "tấn"],
     100e3, 20e6, 1, 200),
]
G = {g[0]: i + 1 for i, g in enumerate(GROUPS)}
INDUSTRY_GROUPS = {
    "G": [("Thiết bị điện tử", 25), ("Thiết bị văn phòng", 20), ("Đồ uống và thực phẩm chế biến", 20),
          ("Thực phẩm tươi sống", 15), ("Vật liệu xây dựng", 10), ("Xăng dầu", 10)],
    "C": [("Vật liệu xây dựng", 25), ("Thiết bị điện tử", 20), ("Đồ uống và thực phẩm chế biến", 20),
          ("Nông sản và vật tư nông nghiệp", 15), ("Sắt thép", 20)],
    "F": [("Vật liệu xây dựng", 50), ("Sắt thép", 35), ("Dịch vụ tư vấn", 15)],
    "H": [("Dịch vụ vận tải", 80), ("Xăng dầu", 20)],
    "I": [("Dịch vụ ăn uống", 70), ("Đồ uống và thực phẩm chế biến", 30)],
    "J": [("Phần mềm và dịch vụ CNTT", 60), ("Viễn thông", 40)],
    "M": [("Dịch vụ tư vấn", 70), ("Phần mềm và dịch vụ CNTT", 30)],
    "N": [("Dịch vụ tư vấn", 40), ("Thiết bị văn phòng", 30), ("Dịch vụ vận tải", 30)],
    "K": [("Dịch vụ tư vấn", 100)],
    "L": [("Cho thuê bất động sản", 100)],
    "P": [("Giáo dục và đào tạo", 90), ("Thiết bị văn phòng", 10)],
    "Q": [("Dịch vụ y tế", 100)],
    "A": [("Thực phẩm tươi sống", 60), ("Nông sản và vật tư nông nghiệp", 40)],
}
DEFAULT_GROUPS = [("Thiết bị văn phòng", 50), ("Dịch vụ tư vấn", 50)]

STATUS = {"nhap": 1, "da_ky": 2, "cho_cap_ma": 3, "cqt_cap_ma": 4, "cqt_tu_choi": 5, "da_gui_cqt": 6,
          "da_huy": 7, "bi_thay_the": 8, "bi_dieu_chinh": 9}
STATUS_ENUM = "Enum8(" + ", ".join(f"'{k}' = {v}" for k, v in STATUS.items()) + ")"


# ----------------------------------------------------------------------------- DDL
def ddl():
    t = f"DateTime('Asia/Ho_Chi_Minh')"
    return [
        f"CREATE DATABASE IF NOT EXISTS {DB} COMMENT 'Hóa đơn điện tử (dữ liệu giả lập)'",
        f"""CREATE TABLE {DB}.provinces (
    province_code LowCardinality(String) COMMENT 'Mã tỉnh/thành (2 chữ số)',
    name String COMMENT 'Tên tỉnh/thành phố',
    region LowCardinality(String) COMMENT 'Vùng: Miền Bắc, Miền Trung, Tây Nguyên, Miền Nam'
) ENGINE = MergeTree ORDER BY province_code COMMENT 'Danh mục 63 tỉnh/thành'""",
        f"""CREATE TABLE {DB}.tax_offices (
    tax_office_code LowCardinality(String) COMMENT 'Mã cơ quan thuế quản lý',
    name String COMMENT 'Tên cơ quan thuế',
    province_code LowCardinality(String) COMMENT 'Tỉnh/thành của cơ quan thuế',
    level Enum8('cuc_thue' = 1, 'chi_cuc_thue' = 2) COMMENT 'Cấp: Cục Thuế tỉnh hoặc Chi cục Thuế khu vực'
) ENGINE = MergeTree ORDER BY tax_office_code COMMENT 'Cơ quan thuế quản lý doanh nghiệp'""",
        f"""CREATE TABLE {DB}.industries (
    industry_code LowCardinality(String) COMMENT 'Mã ngành cấp 1 (VSIC, A-U)',
    name String COMMENT 'Tên ngành kinh tế'
) ENGINE = MergeTree ORDER BY industry_code COMMENT 'Ngành kinh tế cấp 1'""",
        f"""CREATE TABLE {DB}.service_plans (
    plan_id UInt8 COMMENT 'Mã gói dịch vụ',
    name String COMMENT 'Tên gói',
    plan_type LowCardinality(String) COMMENT 'theo_so_luong (mua theo số hóa đơn) | theo_thoi_gian (không giới hạn số HĐ trong thời hạn)',
    invoice_quota Nullable(UInt32) COMMENT 'Số hóa đơn của gói; NULL = không giới hạn',
    price_vnd Float64 COMMENT 'Giá niêm yết (VND, chưa VAT)',
    duration_months Nullable(UInt8) COMMENT 'Số tháng hiệu lực; NULL = không thời hạn'
) ENGINE = MergeTree ORDER BY plan_id COMMENT 'Gói dịch vụ hóa đơn điện tử'""",
        f"""CREATE TABLE {DB}.tax_error_codes (
    error_code LowCardinality(String) COMMENT 'Mã lỗi phản hồi của cơ quan thuế',
    description String COMMENT 'Mô tả lỗi',
    category LowCardinality(String) COMMENT 'Nhóm lỗi: nguoi_ban, nguoi_mua, chu_ky_so, dinh_dang, du_lieu, ky_hieu, ky_thuat'
) ENGINE = MergeTree ORDER BY error_code COMMENT 'Danh mục mã lỗi phản hồi từ cơ quan thuế'""",
        f"""CREATE TABLE {DB}.sellers (
    seller_id UInt32 COMMENT 'Mã doanh nghiệp (người bán) dùng dịch vụ',
    tax_code String COMMENT 'Mã số thuế người bán (10 số, chi nhánh có hậu tố -00x)',
    name String COMMENT 'Tên doanh nghiệp / hộ kinh doanh',
    company_type LowCardinality(String) COMMENT 'Loại hình: TNHH, Cổ phần, DNTN, Hộ kinh doanh, Chi nhánh, Hợp tác xã',
    industry_code LowCardinality(String) COMMENT 'Ngành kinh tế chính, tới industries.industry_code',
    province_code LowCardinality(String) COMMENT 'Tỉnh/thành trụ sở, tới provinces.province_code',
    tax_office_code LowCardinality(String) COMMENT 'Cơ quan thuế quản lý, tới tax_offices.tax_office_code',
    employee_size LowCardinality(String) COMMENT 'Quy mô lao động: <10, 10-49, 50-199, 200+',
    registered_at Date COMMENT 'Ngày đăng ký sử dụng dịch vụ',
    status Enum8('active' = 1, 'suspended' = 2, 'closed' = 3) COMMENT 'Trạng thái tài khoản dịch vụ',
    closed_at Nullable(Date) COMMENT 'Ngày ngừng sử dụng (status = closed)',
    features Array(LowCardinality(String)) COMMENT 'Tính năng đang dùng: api, excel_import, pos, ky_hsm, gui_email, sms, tich_hop_erp',
    sales_channel LowCardinality(String) COMMENT 'Kênh bán: truc_tiep, dai_ly, online',
    contact_email String COMMENT 'Email liên hệ (dữ liệu nhạy cảm)',
    contact_phone String COMMENT 'Số điện thoại liên hệ (dữ liệu nhạy cảm)'
) ENGINE = MergeTree ORDER BY seller_id COMMENT 'Doanh nghiệp / hộ kinh doanh dùng dịch vụ hóa đơn điện tử (người bán)'""",
        f"""CREATE TABLE {DB}.buyers (
    buyer_id UInt64 COMMENT 'Mã người mua',
    buyer_type Enum8('doanh_nghiep' = 1, 'ca_nhan' = 2, 'co_quan_nha_nuoc' = 3, 'to_chuc_nuoc_ngoai' = 4) COMMENT 'Loại người mua',
    tax_code Nullable(String) COMMENT 'Mã số thuế người mua; cá nhân thường để trống',
    name String COMMENT 'Tên người mua / đơn vị mua',
    province_code LowCardinality(String) COMMENT 'Tỉnh/thành của người mua',
    email Nullable(String) COMMENT 'Email nhận hóa đơn (dữ liệu nhạy cảm)',
    phone Nullable(String) COMMENT 'Số điện thoại (dữ liệu nhạy cảm)',
    created_at Date COMMENT 'Ngày người mua xuất hiện lần đầu trong hệ thống'
) ENGINE = MergeTree ORDER BY buyer_id COMMENT 'Người mua trên hóa đơn'""",
        f"""CREATE TABLE {DB}.subscriptions (
    subscription_id UInt64 COMMENT 'Mã đơn mua gói',
    seller_id UInt32 COMMENT 'Doanh nghiệp mua gói',
    plan_id UInt8 COMMENT 'Gói dịch vụ, tới service_plans.plan_id',
    purchased_at Date COMMENT 'Ngày mua',
    invoice_quota Nullable(UInt32) COMMENT 'Số hóa đơn được cấp theo đơn mua; NULL = không giới hạn',
    amount_vnd Float64 COMMENT 'Số tiền thanh toán (VND, chưa VAT, đã trừ chiết khấu)',
    discount_pct UInt8 COMMENT 'Chiết khấu (%)',
    payment_status Enum8('da_thanh_toan' = 1, 'chua_thanh_toan' = 2, 'hoan_tien' = 3) COMMENT 'Trạng thái thanh toán',
    channel LowCardinality(String) COMMENT 'Kênh bán: truc_tiep, dai_ly, online',
    expires_at Nullable(Date) COMMENT 'Ngày hết hạn (gói theo thời gian); NULL = không thời hạn'
) ENGINE = MergeTree ORDER BY (seller_id, purchased_at) COMMENT 'Lịch sử mua gói dịch vụ'""",
        f"""CREATE TABLE {DB}.certificates (
    certificate_id UInt64 COMMENT 'Mã chứng thư số',
    seller_id UInt32 COMMENT 'Doanh nghiệp sở hữu',
    provider LowCardinality(String) COMMENT 'Nhà cung cấp dịch vụ chứng thực chữ ký số',
    cert_type LowCardinality(String) COMMENT 'Loại: usb_token, hsm, ky_so_tu_xa',
    serial String COMMENT 'Số serial chứng thư',
    valid_from Date COMMENT 'Hiệu lực từ ngày',
    valid_to Date COMMENT 'Hiệu lực đến ngày',
    revoked UInt8 COMMENT '1 = đã thu hồi'
) ENGINE = MergeTree ORDER BY (seller_id, valid_from) COMMENT 'Chứng thư số dùng để ký hóa đơn'""",
        f"""CREATE TABLE {DB}.invoice_series (
    series_id UInt32 COMMENT 'Mã ký hiệu hóa đơn',
    seller_id UInt32 COMMENT 'Doanh nghiệp đăng ký ký hiệu',
    symbol LowCardinality(String) COMMENT 'Ký hiệu, ví dụ 1C25TAA: 1 = HĐ GTGT / 2 = HĐ bán hàng, C = có mã / K = không mã, 25 = năm',
    invoice_type Enum8('gtgt' = 1, 'ban_hang' = 2) COMMENT 'Loại hóa đơn',
    tax_code_type Enum8('co_ma' = 1, 'khong_ma' = 2) COMMENT 'Hóa đơn có mã / không có mã của cơ quan thuế',
    year UInt16 COMMENT 'Năm sử dụng ký hiệu',
    registered_at Date COMMENT 'Ngày đăng ký ký hiệu',
    status LowCardinality(String) COMMENT 'dang_su_dung | da_ket_thuc'
) ENGINE = MergeTree ORDER BY (seller_id, series_id) COMMENT 'Ký hiệu hóa đơn đã đăng ký'""",
        f"""CREATE TABLE {DB}.invoices (
    invoice_id UInt64 COMMENT 'Mã hóa đơn',
    seller_id UInt32 COMMENT 'Người bán, tới sellers.seller_id',
    series_id UInt32 COMMENT 'Ký hiệu hóa đơn, tới invoice_series.series_id',
    symbol LowCardinality(String) COMMENT 'Ký hiệu hóa đơn (1C25TAA...)',
    invoice_no UInt32 COMMENT 'Số hóa đơn',
    invoice_type Enum8('gtgt' = 1, 'ban_hang' = 2) COMMENT 'HĐ giá trị gia tăng / HĐ bán hàng',
    tax_code_type Enum8('co_ma' = 1, 'khong_ma' = 2) COMMENT 'Có mã / không có mã của cơ quan thuế',
    issued_at {t} COMMENT 'Thời điểm lập hóa đơn (giờ Việt Nam)',
    buyer_id Nullable(UInt64) COMMENT 'Người mua, tới buyers.buyer_id; NULL = khách lẻ không lấy thông tin',
    currency LowCardinality(String) COMMENT 'Loại tiền: VND, USD, EUR',
    exchange_rate Float64 COMMENT 'Tỷ giá quy đổi sang VND (VND = 1)',
    total_before_tax Float64 COMMENT 'Tổng tiền hàng chưa thuế (nguyên tệ)',
    total_discount Float64 COMMENT 'Tổng chiết khấu (nguyên tệ)',
    total_vat Float64 COMMENT 'Tổng tiền thuế GTGT (nguyên tệ)',
    total_amount Float64 COMMENT 'Tổng thanh toán = chưa thuế - chiết khấu + thuế (nguyên tệ)',
    payment_method LowCardinality(String) COMMENT 'Hình thức thanh toán: TM, CK, TM/CK, Khác',
    nature Enum8('goc' = 1, 'thay_the' = 2, 'dieu_chinh' = 3) COMMENT 'Tính chất: hóa đơn gốc / thay thế / điều chỉnh',
    related_invoice_id Nullable(UInt64) COMMENT 'Hóa đơn bị thay thế / bị điều chỉnh',
    status {STATUS_ENUM} COMMENT 'Trạng thái hiện tại',
    cqt_code Nullable(String) COMMENT 'Mã của cơ quan thuế (hóa đơn có mã đã được cấp)',
    item_count UInt16 COMMENT 'Số dòng hàng',
    channel LowCardinality(String) COMMENT 'Kênh lập: web, api, excel, pos, mobile',
    updated_at {t} COMMENT 'Thời điểm đổi trạng thái gần nhất',
    version UInt64 COMMENT 'Phiên bản bản ghi (lớn nhất = mới nhất)'
) ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(issued_at)
ORDER BY (seller_id, invoice_id)
COMMENT 'Hóa đơn điện tử. Mỗi lần đổi trạng thái ghi thêm một phiên bản: đọc trạng thái hiện tại phải dùng FINAL'""",
        f"""CREATE TABLE {DB}.invoice_items (
    invoice_id UInt64 COMMENT 'Hóa đơn, tới invoices.invoice_id',
    line_no UInt16 COMMENT 'Số thứ tự dòng',
    seller_id UInt32 COMMENT 'Người bán (lặp lại từ hóa đơn)',
    issued_at {t} COMMENT 'Thời điểm lập hóa đơn (lặp lại từ hóa đơn, giờ Việt Nam)',
    product_group LowCardinality(String) COMMENT 'Nhóm hàng hóa, dịch vụ',
    item_name String COMMENT 'Tên hàng hóa, dịch vụ',
    unit LowCardinality(String) COMMENT 'Đơn vị tính',
    quantity Float64 COMMENT 'Số lượng',
    unit_price Float64 COMMENT 'Đơn giá (nguyên tệ)',
    line_amount Float64 COMMENT 'Thành tiền chưa thuế = số lượng x đơn giá (nguyên tệ)',
    discount_amount Float64 COMMENT 'Chiết khấu của dòng (nguyên tệ)',
    vat_rate LowCardinality(String) COMMENT 'Thuế suất: 10%, 8%, 5%, 0%, KCT (không chịu thuế), KKKNT (HĐ bán hàng)',
    vat_amount Float64 COMMENT 'Tiền thuế GTGT của dòng (nguyên tệ)',
    item_nature Enum8('hang_hoa_dich_vu' = 1, 'khuyen_mai' = 2) COMMENT 'Tính chất dòng: hàng hóa dịch vụ / hàng khuyến mại'
) ENGINE = MergeTree
PARTITION BY toYYYYMM(issued_at)
ORDER BY (seller_id, invoice_id, line_no)
COMMENT 'Dòng hàng hóa, dịch vụ trên hóa đơn (không có trạng thái: lọc hóa đơn hợp lệ qua invoices)'""",
        f"""CREATE TABLE {DB}.tax_messages (
    message_id UInt64 COMMENT 'Mã thông điệp',
    invoice_id UInt64 COMMENT 'Hóa đơn liên quan',
    seller_id UInt32 COMMENT 'Người bán',
    message_type LowCardinality(String) COMMENT '200 = gửi HĐ đề nghị cấp mã, 203 = chuyển dữ liệu HĐ không mã, 300 = thông báo HĐ sai sót (hủy)',
    sent_at DateTime('UTC') COMMENT 'Thời điểm gửi tới cơ quan thuế (UTC)',
    response_at Nullable(DateTime('UTC')) COMMENT 'Thời điểm nhận phản hồi (UTC); NULL = chưa phản hồi',
    result Enum8('cho_phan_hoi' = 0, 'chap_nhan' = 1, 'tu_choi' = 2, 'loi_ky_thuat' = 3) COMMENT 'Kết quả phản hồi',
    error_code LowCardinality(Nullable(String)) COMMENT 'Mã lỗi, tới tax_error_codes.error_code',
    attempt UInt8 COMMENT 'Lần gửi thứ mấy'
) ENGINE = MergeTree
PARTITION BY toYYYYMM(sent_at)
ORDER BY (sent_at, message_id)
COMMENT 'Thông điệp trao đổi với cơ quan thuế'""",
        f"""CREATE TABLE {DB}.api_requests (
    ts DateTime64(3, 'UTC') COMMENT 'Thời điểm nhận request (UTC)',
    seller_id UInt32 COMMENT 'Doanh nghiệp gọi API',
    endpoint LowCardinality(String) COMMENT 'Đường dẫn API',
    method LowCardinality(String) COMMENT 'GET / POST',
    http_status UInt16 COMMENT 'Mã HTTP trả về',
    latency_ms UInt32 COMMENT 'Thời gian xử lý (ms)',
    client_type LowCardinality(String) COMMENT 'Loại client: erp, pos, web, mobile',
    error_code LowCardinality(Nullable(String)) COMMENT 'Mã lỗi ứng dụng khi http_status >= 400',
    request_bytes UInt32 COMMENT 'Kích thước request (byte)',
    response_bytes UInt32 COMMENT 'Kích thước response (byte)'
) ENGINE = MergeTree
PARTITION BY toYYYYMM(ts)
ORDER BY (seller_id, ts)
COMMENT 'Log gọi API tích hợp của doanh nghiệp'""",
        f"""CREATE TABLE {DB}.daily_seller_stats (
    day Date COMMENT 'Ngày lập hóa đơn (giờ Việt Nam)',
    seller_id UInt32 COMMENT 'Người bán',
    invoice_count SimpleAggregateFunction(sum, UInt64) COMMENT 'Số hóa đơn hợp lệ',
    revenue_vnd SimpleAggregateFunction(sum, Float64) COMMENT 'Doanh thu chưa thuế (VND, đã trừ chiết khấu, đã quy đổi)',
    vat_vnd SimpleAggregateFunction(sum, Float64) COMMENT 'Tiền thuế GTGT (VND)',
    buyers AggregateFunction(uniqExact, UInt64) COMMENT 'Tập người mua (trạng thái uniqExact)'
) ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(day)
ORDER BY (day, seller_id)
SETTINGS max_bytes_to_merge_at_max_space_in_pool = 1, max_bytes_to_merge_at_min_space_in_pool = 1
COMMENT 'Tổng hợp theo ngày từ hóa đơn hợp lệ. Một (day, seller_id) có thể có nhiều dòng: phải sum() / uniqExactMerge() và GROUP BY'""",
    ]


TABLES = ["provinces", "tax_offices", "industries", "service_plans", "tax_error_codes", "sellers", "buyers",
          "subscriptions", "certificates", "invoice_series", "invoices", "invoice_items", "tax_messages",
          "api_requests", "daily_seller_stats"]


# ----------------------------------------------------------------------------- sinh dữ liệu
def person(key, parts):
    return (f"concat({arr(HO)}[1 + {H(key + 'h', *parts)} % {len(HO)}], ' ', "
            f"{arr(DEM)}[1 + {H(key + 'd', *parts)} % {len(DEM)}], ' ', {arr(TEN)}[1 + {H(key + 't', *parts)} % {len(TEN)}])")


def static_inserts():
    out = [f"INSERT INTO {DB}.provinces VALUES " + ", ".join(f"({q(c)}, {q(n)}, {q(r)})" for c, n, r in PROVINCES),
           f"INSERT INTO {DB}.industries VALUES " + ", ".join(f"({q(c)}, {q(n)})" for c, n in INDUSTRIES),
           f"INSERT INTO {DB}.service_plans VALUES " + ", ".join(
               f"({p}, {q(n)}, {q(t)}, {q(k)}, {v}, {q(d)})" for p, n, t, k, v, d in SERVICE_PLANS),
           f"INSERT INTO {DB}.tax_error_codes VALUES " + ", ".join(f"({q(c)}, {q(d)}, {q(g)})" for c, d, g in TAX_ERRORS)]
    offices = []
    for code, name, _ in PROVINCES:
        offices.append(f"({q('CT' + code)}, {q('Cục Thuế ' + name)}, {q(code)}, 1)")
        for i in range(1, CHI_CUC.get(code, 0) + 1):
            offices.append(f"({q(f'CC{code}{i:02d}')}, {q(f'Chi cục Thuế khu vực {i} - {name}')}, {q(code)}, 2)")
    out.append(f"INSERT INTO {DB}.tax_offices VALUES " + ", ".join(offices))
    return out


def sellers_insert():
    sid = "seller_id"
    types = ("multiIf(seller_id <= 2500, " + pick("ct1", [sid], [("TNHH", 55), ("Cổ phần", 45)]) + ", "
             + pick("ct", [sid], [("TNHH", 55), ("Cổ phần", 20), ("DNTN", 5), ("Hộ kinh doanh", 12),
                                  ("Chi nhánh", 6), ("Hợp tác xã", 2)]) + ")")
    domain = "transform(industry_code, " + arr(list(DOMAIN_WORD)) + ", " + arr(list(DOMAIN_WORD.values())) + ", 'Thương mại Dịch vụ')"
    brand = f"concat({arr(BRANDS)}[1 + (seller_id - 1) % {len(BRANDS)}], {arr(SUFFIXES)}[1 + intDiv(seller_id - 1, {len(BRANDS)}) % {len(SUFFIXES)}])"
    name = (f"multiIf(company_type = 'Hộ kinh doanh', concat('Hộ kinh doanh ', {person('sp', [sid])}), "
            f"company_type = 'Chi nhánh', concat('Chi nhánh Công ty TNHH ', {domain}, ' ', {brand}), "
            f"company_type = 'TNHH', concat('Công ty TNHH ', {domain}, ' ', {brand}), "
            f"company_type = 'Cổ phần', concat('Công ty Cổ phần ', {domain}, ' ', {brand}), "
            f"company_type = 'DNTN', concat('Doanh nghiệp tư nhân ', {brand}), concat('Hợp tác xã ', {domain}, ' ', {brand}))")
    big_codes, big_n = list(CHI_CUC), list(CHI_CUC.values())
    tax_office = (f"if(seller_id > 3000 AND transform(province_code, {arr(big_codes)}, {arr(big_n)}, 0) > 0, "
                  f"concat('CC', province_code, leftPad(toString(1 + {H('to', sid)} % transform(province_code, {arr(big_codes)}, {arr(big_n)}, 1)), 2, '0')), "
                  f"concat('CT', province_code))")
    reg = (f"if(seller_id <= 2500 OR {U('r1', sid)} < 0.7, toDate('2019-01-01') + toUInt32({H('r2', sid)} % 1461), "
           f"toDate('2023-01-01') + toUInt32({H('r3', sid)} % 900))")
    feats = ("arrayFilter(f -> " + H("ft", "f", sid) + " % 100 < multiIf("
             "f = 'api', if(seller_id <= 3000, 70, 12), f = 'excel_import', 40, "
             "f = 'pos', if(industry_code IN ('G', 'I'), 25, 3), f = 'ky_hsm', if(seller_id <= 3000, 45, 6), "
             "f = 'gui_email', 85, f = 'sms', 8, f = 'tich_hop_erp', if(seller_id <= 3000, 40, 3), 0), "
             "['api', 'excel_import', 'pos', 'ky_hsm', 'gui_email', 'sms', 'tich_hop_erp'])")
    return f"""INSERT INTO {DB}.sellers
SELECT seller_id,
       concat(province_code, leftPad(toString({H('mst', sid)} % 100000000), 8, '0'),
              if(company_type = 'Chi nhánh', concat('-00', toString(1 + {H('cn', sid)} % 3)), '')) AS tax_code,
       {name} AS name, company_type, industry_code, province_code, {tax_office} AS tax_office_code,
       multiIf(seller_id <= 500, '200+', seller_id <= 3000, '50-199', company_type = 'Hộ kinh doanh', '<10',
               {U('sz', sid)} < 0.3, '10-49', '<10') AS employee_size,
       registered_at,
       if(st < 0.06 AND seller_id > 500, 3, if(st < 0.10 AND seller_id > 500, 2, 1)) AS status,
       if(status = 3, toNullable(least(toDate('2025-06-20'), greatest(registered_at + 120, toDate('2023-06-01')) + toUInt32({H('cl', sid)} % 700))), NULL) AS closed_at,
       {feats} AS features,
       {pick('ch', [sid], [('truc_tiep', 35), ('dai_ly', 45), ('online', 20)])} AS sales_channel,
       concat('ketoan.', toString(seller_id), '@', {pick('em', [sid], [('gmail.com', 50), ('yahoo.com', 10), ('outlook.com', 10), ('congty.vn', 30)])}) AS contact_email,
       concat('09', leftPad(toString({H('ph', sid)} % 100000000), 8, '0')) AS contact_phone
FROM (SELECT toUInt32(number + 1) AS seller_id,
             {pick('ind', ['seller_id'], INDUSTRY_WEIGHTS)} AS industry_code,
             {pick('prov', ['seller_id'], PROVINCE_WEIGHTS)} AS province_code,
             {types} AS company_type,
             {reg} AS registered_at,
             {U('st', 'seller_id')} AS st
      FROM numbers({N_SELLERS}))"""


def buyers_insert():
    b = "buyer_id"
    foreign = (f"concat({arr(['Sunrise', 'Pacific', 'Global', 'Asia Link', 'Blue Ocean', 'Golden Gate', 'Nippon', 'Hanwa', 'Mekong Star'])}"
               f"[1 + {H('fn1', b)} % 9], ' ', {arr(['Trading Co., Ltd', 'Logistics Pte. Ltd', 'Industries Inc.', 'GmbH', 'Co., Ltd'])}[1 + {H('fn2', b)} % 5])")
    org = (f"concat({arr(['Ủy ban nhân dân quận ', 'Sở Tài chính ', 'Trường THPT ', 'Bệnh viện đa khoa ', 'Trung tâm Y tế '])}"
           f"[1 + {H('og1', b)} % 5], {arr([n for _, n, _ in PROVINCES])}[1 + {H('og2', b)} % {len(PROVINCES)}])")
    company = (f"concat({arr(['Công ty TNHH ', 'Công ty Cổ phần ', 'Công ty TNHH MTV '])}[1 + {H('bc1', b)} % 3], "
               f"{arr(BRANDS)}[1 + {H('bc2', b)} % {len(BRANDS)}], {arr(SUFFIXES)}[1 + {H('bc3', b)} % {len(SUFFIXES)}])")
    return f"""INSERT INTO {DB}.buyers
SELECT buyer_id, buyer_type,
       multiIf(buyer_type IN ('doanh_nghiep', 'co_quan_nha_nuoc'),
               toNullable(concat(leftPad(toString(1 + {H('bt1', b)} % 96), 2, '0'), leftPad(toString({H('bt2', b)} % 100000000), 8, '0'))),
               buyer_type = 'ca_nhan' AND {U('bt3', b)} < 0.25, toNullable(leftPad(toString({H('bt4', b)} % 1000000000000), 12, '0')),
               NULL) AS tax_code,
       multiIf(buyer_type = 'doanh_nghiep', {company}, buyer_type = 'ca_nhan', {person('bp', [b])},
               buyer_type = 'co_quan_nha_nuoc', {org}, {foreign}) AS name,
       {pick('bprov', [b], PROVINCE_WEIGHTS)} AS province_code,
       if({U('be', b)} < 0.7, toNullable(concat('kh', toString(buyer_id), '@', {pick('bem', [b], [('gmail.com', 60), ('yahoo.com', 10), ('outlook.com', 10), ('company.vn', 20)])})), NULL) AS email,
       if({U('bph', b)} < 0.6, toNullable(concat('0', {pick('bpp', [b], [('3', 25), ('5', 5), ('7', 15), ('8', 25), ('9', 30)])}, leftPad(toString({H('bph2', b)} % 100000000), 8, '0'))), NULL) AS phone,
       toDate('2019-01-01') + toUInt32({H('bcr', b)} % 2370) AS created_at
FROM (SELECT toUInt64(number + 1) AS buyer_id,
             CAST({pick('btype', ['buyer_id'], [(1, 55), (2, 40), (3, 4), (4, 1)])} AS Enum8('doanh_nghiep' = 1, 'ca_nhan' = 2, 'co_quan_nha_nuoc' = 3, 'to_chuc_nuoc_ngoai' = 4)) AS buyer_type
      FROM numbers({N_BUYERS}))"""


def subscriptions_insert():
    s, k = "seller_id", "k"
    plan = (f"multiIf(seller_id <= 500, {pick('pl1', [s, k], [(7, 40), (9, 40), (8, 20)])}, "
            f"seller_id <= 3000, {pick('pl2', [s, k], [(5, 40), (6, 35), (8, 25)])}, "
            f"{pick('pl3', [s, k], [(1, 35), (2, 30), (3, 25), (4, 10)])})")
    prices = arr([p[4] for p in SERVICE_PLANS])
    quotas = "[" + ", ".join("NULL" if p[3] is None else str(p[3]) for p in SERVICE_PLANS) + "]"
    return f"""INSERT INTO {DB}.subscriptions
SELECT toUInt64(seller_id) * 10 + k AS subscription_id, seller_id, plan_id, purchased_at,
       {quotas}[plan_id] AS invoice_quota,
       round({prices}[plan_id] * (100 - discount_pct) / 100) AS amount_vnd, discount_pct,
       multiIf(purchased_at >= toDate('2025-06-01') AND {U('pay', s, k)} < 0.3, 2, {U('pay2', s, k)} < 0.02, 3, 1) AS payment_status,
       sales_channel AS channel,
       if(plan_id IN (8, 9), toNullable(addMonths(purchased_at, 12)), NULL) AS expires_at
FROM (SELECT s.seller_id AS seller_id, s.sales_channel AS sales_channel, n.k AS k,
             toUInt8({plan}) AS plan_id,
             s.registered_at + toUInt32(n.k * (300 + {H('gap', s, k)} % 120) + {H('off', s, k)} % 20) AS purchased_at,
             toUInt8({pick('dc', [s, k], [(0, 70), (10, 20), (20, 10)])}) AS discount_pct,
             toUInt8(1 + {H('np', s)} % 3 + if(seller_id <= 3000, 3, 0)) AS n_purchases
      FROM {DB}.sellers AS s CROSS JOIN (SELECT toUInt8(number) AS k FROM numbers(7)) AS n)
WHERE k < n_purchases AND purchased_at <= toDate('{TODAY}')"""


def certificates_insert():
    s, k = "seller_id", "k"
    return f"""INSERT INTO {DB}.certificates
SELECT toUInt64(seller_id) * 10 + k AS certificate_id, seller_id,
       {pick('ca', [s], CA_PROVIDERS)} AS provider,
       if(seller_id <= 3000 AND {U('hsm', s)} < 0.4, 'hsm', {pick('ctp', [s, k], [('usb_token', 60), ('ky_so_tu_xa', 40)])}) AS cert_type,
       lower(hex({H('ser', s, k)})) AS serial,
       valid_from, valid_from + period - 1 AS valid_to,
       toUInt8({U('rv', s, k)} < 0.02) AS revoked
FROM (SELECT seller_id, k, toUInt32(365 * (1 + {H('per', s)} % 3)) AS period,
             registered_at - 10 + k * period AS valid_from
      FROM {DB}.sellers CROSS JOIN (SELECT toUInt32(number) AS k FROM numbers(7)) AS n)
WHERE valid_from <= toDate('{TODAY}')"""


def skeleton_insert(y, m, n):
    """Khung hóa đơn của một tháng (chưa có tổng tiền): người bán, thời điểm, trạng thái, người mua..."""
    ym = y * 100 + m
    i = "invoice_id"
    start = date(y, m, 1)
    days = (date(y + (m == 12), m % 12 + 1, 1) - start).days
    today = f"toDateTime('{TODAY} 23:59:59', 'Asia/Ho_Chi_Minh')"
    status_co = (f"multiIf(issued_at >= {today} - 86400 * 2 AND r < 0.35, 3, r < 0.015, 1, r < 0.025, 2, r < 0.040, 5, "
                 f"r < 0.060, 7, r < 0.075 AND issued_at < {today} - 86400 * 12, 8, "
                 f"r < 0.090 AND issued_at < {today} - 86400 * 12, 9, 4)")
    status_k = (f"multiIf(r < 0.015, 1, r < 0.030, 2, r < 0.050, 7, r < 0.065 AND issued_at < {today} - 86400 * 12, 8, "
                f"r < 0.080 AND issued_at < {today} - 86400 * 12, 9, 6)")
    pool = f"(10 + toUInt32(3000 * pow(1 - seller_id / {N_SELLERS}, 8)) + {H('pool', 'seller_id')} % 50)"
    letters = arr(["AA", "AB", "BA", "BB", "HN", "SG", "DN", "KT", "MT", "XK"])
    return f"""INSERT INTO {DB}._skel
SELECT invoice_id, seller_id, industry_code,
       toUInt32(seller_id * 100 + (toYear(issued_at) - 2020) * 10 + s_idx) AS series_id,
       concat(toString(inv_type), if(tax_code_type = 1, 'C', 'K'), right(toString(toYear(issued_at)), 2), 'T',
              {letters}[1 + ({H('ltr', 'seller_id')} + s_idx) % 10]) AS symbol,
       toUInt32(1 + {H('no', i)} % 9000000) AS invoice_no, inv_type, tax_code_type, issued_at,
       multiIf((inv_type = 2 AND {U('bn1', i)} < 0.6) OR (channel = 'pos' AND {U('bn2', i)} < 0.8) OR {U('bn3', i)} < 0.08,
               NULL, toNullable(1 + cityHash64(seller_id, toUInt32(pow({U('bp', i)}, 1.5) * {pool})) % {N_BUYERS})) AS buyer_id,
       currency,
       multiIf(currency = 'USD', toFloat64(round(23300 + dateDiff('month', toDate('2023-01-01'), toDate(issued_at)) * 62 + toInt64({H('fx', i)} % 300) - 150)),
               currency = 'EUR', toFloat64(round((23300 + dateDiff('month', toDate('2023-01-01'), toDate(issued_at)) * 62) * 1.08 + toInt64({H('fx2', i)} % 400) - 200)),
               1.0) AS exchange_rate,
       if(channel = 'pos', {pick('pm1', [i], [('TM', 70), ('CK', 30)])},
          {pick('pm2', [i], [('CK', 55), ('TM', 20), ('TM/CK', 22), ('Khác', 3)])}) AS payment_method,
       toUInt8(1) AS nature, CAST(NULL AS Nullable(UInt64)) AS related_invoice_id,
       toUInt8(if(tax_code_type = 1, {status_co}, {status_k})) AS status,
       if(tax_code_type = 1 AND status IN (4, 7, 8, 9),
          toNullable(concat('M1-', right(toString(toYear(issued_at)), 2), '-', substring(hex({H('cq1', i)}), 1, 5), '-',
                            leftPad(toString({H('cq2', i)} % 100000000000), 11, '0'))), NULL) AS cqt_code,
       toUInt16(if(channel = 'pos', 1 + {H('ic', i)} % 3, 1 + floor(9 * pow({U('ic2', i)}, 2)))) AS item_count,
       channel,
       least({today}, issued_at + multiIf(status = 4, 2 + {H('up1', i)} % 118, status = 6, 60 + {H('up2', i)} % 7140,
                                           status IN (7, 8, 9), 86400 * (1 + {H('up3', i)} % 10) + {H('up4', i)} % 36000,
                                           status IN (3, 5), 5 + {H('up5', i)} % 60, 0)) AS updated_at
FROM (
    SELECT g.invoice_id AS invoice_id, g.seller_id AS seller_id, s.industry_code AS industry_code,
           toUInt8(if(s.company_type = 'Hộ kinh doanh' OR {U('it', 'g.seller_id')} < 0.1, 2, 1)) AS inv_type,
           toUInt8(if({U('tc', 'g.seller_id')} < 0.72, 1, 2)) AS tax_code_type,
           toUInt8(if(g.seller_id <= 2000 AND {U('si', 'g.invoice_id')} < 0.3, 2, 1)) AS s_idx,
           toDateTime(g.d, 'Asia/Ho_Chi_Minh') + g.secs AS issued_at,
           multiIf(has(s.features, 'api') AND {U('chn1', 'g.invoice_id')} < 0.8, 'api',
                   has(s.features, 'pos') AND {U('chn2', 'g.invoice_id')} < 0.7, 'pos',
                   has(s.features, 'excel_import') AND {U('chn3', 'g.invoice_id')} < 0.3, 'excel',
                   {U('chn4', 'g.invoice_id')} < 0.05, 'mobile', 'web') AS channel,
           if(s.industry_code IN ('C', 'G', 'H') AND {U('cur', 'g.invoice_id')} < 0.06,
              if({U('cur2', 'g.invoice_id')} < 0.8, 'USD', 'EUR'), 'VND') AS currency,
           {U('st', 'g.invoice_id')} AS r
    FROM (
        SELECT toUInt64({ym}) * 10000000 + number AS invoice_id,
               toUInt32(least({N_SELLERS}, 1 + floor({N_SELLERS} * pow({U('sel', 'number', str(ym))}, 2.5)))) AS seller_id,
               toDate('{start}') + toUInt32({H('day', 'number', str(ym))} % {days}) AS d0,
               if(toDayOfWeek(d0) = 7 AND {U('sun', 'number', str(ym))} < 0.7, d0 + 1, d0) AS d1,
               least(d1, toDate('{TODAY}')) AS d,
               toUInt32(if({U('hr', 'number', str(ym))} < 0.95, 25200 + {H('sec', 'number', str(ym))} % 46800,
                           {H('sec2', 'number', str(ym))} % 86400)) AS secs
        FROM numbers({n})
    ) AS g
    INNER JOIN {DB}.sellers AS s ON s.seller_id = g.seller_id
    WHERE g.d >= s.registered_at AND (s.closed_at IS NULL OR g.d < s.closed_at) AND g.d <= toDate('{TODAY}')
)"""


def derived_insert():
    """Hóa đơn thay thế / điều chỉnh cho các hóa đơn gốc bị thay thế (8) / bị điều chỉnh (9) trong khung."""
    i = "invoice_id"
    today = f"toDateTime('{TODAY} 23:59:59', 'Asia/Ho_Chi_Minh')"
    return f"""INSERT INTO {DB}._skel
SELECT invoice_id + 5000000, seller_id, industry_code, series_id, symbol, toUInt32(1 + {H('dno', i)} % 9000000),
       inv_type, tax_code_type, new_issued, buyer_id, currency, exchange_rate, payment_method,
       toUInt8(if(status = 8, 2, 3)) AS new_nature, toNullable(invoice_id), toUInt8(if(tax_code_type = 1, 4, 6)),
       if(tax_code_type = 1, toNullable(concat('M1-', right(toString(toYear(new_issued)), 2), '-',
                                              substring(hex({H('dcq1', i)}), 1, 5), '-',
                                              leftPad(toString({H('dcq2', i)} % 100000000000), 11, '0'))), NULL),
       toUInt16(if(new_nature = 3, 1, item_count)), channel,
       least({today}, new_issued + if(tax_code_type = 1, 2 + {H('dup', i)} % 118, 60 + {H('dup2', i)} % 7140))
FROM (SELECT *, least(updated_at, {today} - 3600) AS new_issued FROM {DB}._skel WHERE nature = 1 AND status IN (8, 9))"""


def item_group_expr():
    """Chỉ số nhóm hàng (1-based) cho dòng hàng, theo ngành của người bán."""
    parts = []
    for ind, weights in INDUSTRY_GROUPS.items():
        parts.append(f"industry_code = '{ind}', {pick('grp', ['invoice_id', 'i'], [(G[g], w) for g, w in weights])}")
    default = pick("grp", ["invoice_id", "i"], [(G[g], w) for g, w in DEFAULT_GROUPS])
    return f"multiIf(currency != 'VND', {G['Hàng xuất khẩu']}, {', '.join(parts)}, {default})"


def items_insert():
    names = arr([g[3] for g in GROUPS])
    units = arr([g[4] for g in GROUPS])
    pmin, pmax = arr([g[5] for g in GROUPS]), arr([g[6] for g in GROUPS])
    qmin, qmax = arr([g[7] for g in GROUPS]), arr([g[8] for g in GROUPS])
    base_rate, reducible = arr([g[1] for g in GROUPS]), arr([g[2] for g in GROUPS])
    ii = ["invoice_id", "i"]
    return f"""INSERT INTO {DB}._items
SELECT invoice_id, toUInt16(i + 1) AS line_no, seller_id, issued_at,
       {arr([g[0] for g in GROUPS])}[gidx] AS product_group,
       if(nature = 3, concat('Điều chỉnh ', nm), nm) AS item_name,
       arrayElement({units}[gidx], 1 + {H('un', *ii)} % length({units}[gidx])) AS unit,
       toFloat64(if(nature = 3, 1, {qmin}[gidx] + floor(pow({U('qty', *ii)}, 3) * ({qmax}[gidx] - {qmin}[gidx] + 1)))) AS quantity,
       if(promo, 0, {rnd(f"if(nature = 3, if({U('sgn', *ii)} < 0.65, -1, 1) * price_vnd * (0.05 + 0.3 * {U('adj', *ii)}), price_vnd) / exchange_rate")}) AS unit_price,
       {rnd('quantity * unit_price')} AS line_amount,
       if(nature = 3 OR promo, 0, {rnd('line_amount * multiIf(disc_r < 0.8, 0, disc_r < 0.93, 0.05, 0.1)')}) AS discount_amount,
       multiIf(inv_type = 2, 'KKKNT', rate < 0, 'KCT', concat(toString(rate), '%')) AS vat_rate,
       if(inv_type = 2, 0, {rnd('(line_amount - discount_amount) * greatest(rate, 0) / 100')}) AS vat_amount,
       toUInt8(if(promo, 2, 1)) AS item_nature
FROM (
    SELECT invoice_id, seller_id, issued_at, nature, inv_type, exchange_rate, i,
           {item_group_expr()} AS gidx,
           arrayElement({names}[gidx], 1 + {H('nm', *ii)} % length({names}[gidx])) AS nm,
           round(exp(log({pmin}[gidx]) + pow({U('pr', *ii)}, 2.2) * (log({pmax}[gidx]) - log({pmin}[gidx]))) / 1000) * 1000 AS price_vnd,
           if(currency = 'VND', 0, 2) AS dec,
           nature = 1 AND {U('km', *ii)} < 0.02 AND gidx NOT IN (10, 11, 12, 13, 14, 15) AS promo,
           {U('dsc', *ii)} AS disc_r,
           if({base_rate}[gidx] = 10 AND {reducible}[gidx] = 1 AND toDate(issued_at) >= toDate('2023-07-01'), 8,
              {base_rate}[gidx]) AS rate
    FROM {DB}._skel ARRAY JOIN range(item_count) AS i
)"""


def invoices_insert():
    return f"""INSERT INTO {DB}.invoices
SELECT k.invoice_id, k.seller_id, k.series_id, k.symbol, k.invoice_no, k.inv_type, k.tax_code_type, k.issued_at,
       k.buyer_id, k.currency, k.exchange_rate, t.before, t.disc, t.vat, if(k.currency = 'VND', round(t.before - t.disc + t.vat), round(t.before - t.disc + t.vat, 2)),
       k.payment_method, k.nature, k.related_invoice_id, k.status, k.cqt_code, k.item_count, k.channel, k.updated_at,
       toUInt64(toUnixTimestamp(k.updated_at)) * 10 + 9
FROM {DB}._skel AS k
INNER JOIN (SELECT invoice_id, sum(line_amount) AS before, sum(discount_amount) AS disc, sum(vat_amount) AS vat
            FROM {DB}._items GROUP BY invoice_id) AS t ON t.invoice_id = k.invoice_id"""


def old_versions_insert(ym):
    """Phiên bản cũ của hóa đơn (trạng thái trước khi đổi): bắt buộc cho HĐ bị hủy / thay thế / điều chỉnh,
    25% cho HĐ hợp lệ; 10% HĐ được cấp mã có thêm phiên bản 'da_ky'."""
    i = "invoice_id"
    base = f"FROM {DB}.invoices WHERE toYYYYMM(issued_at) = {ym}"
    prev = "if(tax_code_type = 'co_ma', 'cqt_cap_ma', 'da_gui_cqt')"
    return [
        f"""INSERT INTO {DB}.invoices
SELECT * REPLACE (CAST(multiIf(status IN ('da_huy', 'bi_thay_the', 'bi_dieu_chinh'), {prev},
                               status = 'cqt_cap_ma', 'cho_cap_ma', 'da_ky') AS {STATUS_ENUM}) AS status,
                  if(status IN ('cqt_cap_ma', 'da_gui_cqt'), NULL, cqt_code) AS cqt_code,
                  if(status IN ('da_huy', 'bi_thay_the', 'bi_dieu_chinh'), issued_at + 60, issued_at) AS updated_at,
                  version - 5 AS version)
{base} AND (status IN ('da_huy', 'bi_thay_the', 'bi_dieu_chinh') OR (status IN ('cqt_cap_ma', 'da_gui_cqt') AND {U('ov', i)} < 0.25))""",
        f"""INSERT INTO {DB}.invoices
SELECT * REPLACE (CAST('da_ky' AS {STATUS_ENUM}) AS status, CAST(NULL AS Nullable(String)) AS cqt_code,
                  issued_at AS updated_at, version - 8 AS version)
{base} AND status = 'cqt_cap_ma' AND {U('ov2', i)} < 0.10""",
    ]


def tax_messages_inserts(ym):
    i = "invoice_id"
    base = f"FROM {DB}.invoices WHERE toYYYYMM(issued_at) = {ym} AND status NOT IN ('nhap', 'da_ky')"
    outage = ("(toDate(issued_at) = toDate('2025-01-02') AND toHour(issued_at) BETWEEN 8 AND 11) "
              "OR (toDate(issued_at) = toDate('2024-06-28') AND toHour(issued_at) BETWEEN 14 AND 16)")
    main_sent = f"issued_at + if(tax_code_type = 'co_ma', 1 + {H('ms', i)} % 20, 30 + {H('ms2', i)} % 1800)"
    retry = f"({U('rt', i)} < 0.03 OR (({outage}) AND {U('rt2', i)} < 0.4))"
    return [
        # thông điệp chính (200 / 203)
        f"""INSERT INTO {DB}.tax_messages
SELECT invoice_id * 10 + 1, invoice_id, seller_id, if(tax_code_type = 'co_ma', '200', '203'),
       sent, if(result = 'cho_phan_hoi', NULL, toNullable(sent + resp)), result,
       if(result = 'tu_choi', toNullable({pick('rej', [i], REJECT_WEIGHTS)}), NULL), toUInt8(if({retry}, 2, 1))
FROM (SELECT *, toTimeZone({main_sent} + if({retry}, 300 + {H('rw', i)} % 900, 0), 'UTC') AS sent,
             CAST(multiIf(status = 'cho_cap_ma', 'cho_phan_hoi', status = 'cqt_tu_choi', 'tu_choi', 'chap_nhan')
                  AS Enum8('cho_phan_hoi' = 0, 'chap_nhan' = 1, 'tu_choi' = 2, 'loi_ky_thuat' = 3)) AS result,
             toUInt32(if({U('slow', i)} < 0.03, 600 + {H('rs1', i)} % 7200,
                         if(tax_code_type = 'co_ma', 2 + {H('rs2', i)} % 45, 20 + {H('rs3', i)} % 600))) AS resp
      {base})""",
        # lần gửi lỗi kỹ thuật trước đó
        f"""INSERT INTO {DB}.tax_messages
SELECT invoice_id * 10, invoice_id, seller_id, if(tax_code_type = 'co_ma', '200', '203'),
       toTimeZone({main_sent}, 'UTC'), toNullable(toTimeZone({main_sent}, 'UTC') + 30 + {H('er', i)} % 90), 'loi_ky_thuat',
       toNullable({pick('ht', [i], [('HT01', 60), ('HT02', 40)])}), toUInt8(1)
{base} AND {retry}""",
        # thông báo hủy hóa đơn (mẫu 04/SS)
        f"""INSERT INTO {DB}.tax_messages
SELECT invoice_id * 10 + 2, invoice_id, seller_id, '300', toTimeZone(updated_at, 'UTC'),
       toNullable(toTimeZone(updated_at, 'UTC') + 10 + {H('cx', i)} % 600),
       if({U('cxr', i)} < 0.95, 'chap_nhan', 'tu_choi'), if({U('cxr', i)} < 0.95, NULL, toNullable('DD02')), toUInt8(1)
{base} AND status = 'da_huy'""",
    ]


def daily_stats_inserts():
    sel = f"""INSERT INTO {DB}.daily_seller_stats
SELECT toDate(issued_at) AS day, seller_id, count(), sum((total_before_tax - total_discount) * exchange_rate),
       sum(total_vat * exchange_rate), uniqExactStateIf(assumeNotNull(buyer_id), buyer_id IS NOT NULL)
FROM {DB}.invoices WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND invoice_id % 2 = {{half}}
GROUP BY day, seller_id"""
    return [sel.format(half=0), sel.format(half=1)]


def series_insert():
    return f"""INSERT INTO {DB}.invoice_series
SELECT series_id, any(seller_id), any(symbol), any(invoice_type), any(tax_code_type), toUInt16(any(toYear(issued_at))),
       toDate(min(issued_at)) - (5 + series_id % 40), if(any(toYear(issued_at)) < 2025, 'da_ket_thuc', 'dang_su_dung')
FROM {DB}.invoices GROUP BY series_id"""


def api_insert(y, m, n):
    ym = y * 100 + m
    start = date(y, m, 1)
    days = (date(y + (m == 12), m % 12 + 1, 1) - start).days
    num = ["number", str(ym)]
    endpoints = [("/api/invoice/create", 30), ("/api/invoice/sign", 15), ("/api/invoice/publish", 15),
                 ("/api/invoice/search", 20), ("/api/invoice/download-pdf", 10), ("/api/invoice/cancel", 1),
                 ("/api/auth/token", 9)]
    base_ms = "transform(endpoint, ['/api/invoice/create', '/api/invoice/sign', '/api/invoice/publish', '/api/invoice/search', '/api/invoice/download-pdf', '/api/invoice/cancel', '/api/auth/token'], [180, 650, 1200, 120, 350, 250, 60], 200)"
    normal = pick("hs", num, [(200, 9600), (400, 150), (401, 50), (409, 40), (422, 100), (429, 30), (500, 20), (503, 5), (504, 5)])
    incident = pick("hsi", num, [(200, 60), (503, 25), (504, 15)])
    hsm = pick("hsh", num, [(200, 55), (500, 45)])
    in1 = "(ts_local >= toDateTime('2025-03-18 08:30:00', 'Asia/Ho_Chi_Minh') AND ts_local < toDateTime('2025-03-18 10:45:00', 'Asia/Ho_Chi_Minh'))"
    in2 = "(ts_local >= toDateTime('2024-11-05 14:00:00', 'Asia/Ho_Chi_Minh') AND ts_local < toDateTime('2024-11-05 14:40:00', 'Asia/Ho_Chi_Minh') AND endpoint = '/api/invoice/sign')"
    gauss = f"({U('g1', *num)} + {U('g2', *num)} + {U('g3', *num)} + {U('g4', *num)} - 2)"
    return f"""INSERT INTO {DB}.api_requests
WITH (SELECT groupArray(seller_id) FROM (SELECT seller_id FROM {DB}.sellers WHERE has(features, 'api') ORDER BY seller_id)) AS api_ids
SELECT toTimeZone(toDateTime64(ts_local, 3), 'UTC') + toIntervalMillisecond({H('ms', *num)} % 1000) AS ts,
       seller_id, endpoint,
       if(endpoint IN ('/api/invoice/search', '/api/invoice/download-pdf'), 'GET', 'POST') AS method,
       toUInt16(multiIf({in1}, {incident}, {in2}, {hsm}, {normal})) AS http_status,
       toUInt32(multiIf(http_status = 429, 5 + {H('l0', *num)} % 15, http_status = 504, 30000,
                        greatest(5, {base_ms} * exp(1.2 * {gauss}) * if({in1}, 6, 1)))) AS latency_ms,
       {pick('cli', num, [('erp', 50), ('pos', 15), ('web', 25), ('mobile', 10)])} AS client_type,
       multiIf(http_status = 400, 'INVALID_PAYLOAD', http_status = 401, 'UNAUTHORIZED', http_status = 409, 'DUPLICATE_INVOICE',
               http_status = 422, 'VALIDATION_ERROR', http_status = 429, 'RATE_LIMITED', http_status = 500, 'INTERNAL_ERROR',
               http_status = 503, 'SERVICE_UNAVAILABLE', http_status = 504, 'GATEWAY_TIMEOUT', NULL) AS error_code,
       toUInt32(if(method = 'POST', 1500 + {H('rq', *num)} % 18000, 200 + {H('rq2', *num)} % 600)) AS request_bytes,
       toUInt32(if(endpoint = '/api/invoice/download-pdf', 80000 + {H('rp', *num)} % 320000, 300 + {H('rp2', *num)} % 8000)) AS response_bytes
FROM (
    SELECT api_ids[1 + toUInt32(floor(length(api_ids) * pow({U('as', *num)}, 1.8)))] AS seller_id,
           {pick('ep', num, endpoints)} AS endpoint,
           toDateTime(toDate('{start}') + toUInt32({H('ad', *num)} % {days}), 'Asia/Ho_Chi_Minh')
             + toUInt32(if({U('ah', *num)} < 0.9, 25200 + {H('as1', *num)} % 46800, {H('as2', *num)} % 86400)) AS ts_local,
           number
    FROM numbers({n})
) AS r
WHERE toDate(ts_local) <= toDate('{TODAY}')"""


# ----------------------------------------------------------------------------- chạy
def month_count(idx, m, scale):
    growth = 0.75 + 0.5 * idx / (len(MONTHS) - 1)
    return max(1000, int(INVOICES_PER_MONTH * scale * growth * SEASON[m]))


def admin_client():
    import clickhouse_connect
    url = os.environ.get("T2SQL_DATABASE_URL_CLICKHOUSE") or "clickhouse://x@127.0.0.1:8123/shop"
    u = urlsplit(url)
    return clickhouse_connect.get_client(
        host=u.hostname or "127.0.0.1", port=u.port or 8123, secure=u.scheme == "clickhouses",
        username=os.environ.get("CLICKHOUSE_USER") or "default", password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        send_receive_timeout=3600, settings={"max_memory_usage": 5_000_000_000, "max_threads": 8,
                                             "max_insert_threads": 4, "join_use_nulls": 0})


def apply_access(c):
    pw = os.environ.get("T2SQL_CH_PASSWORD")
    if not pw:
        sys.exit("Thiếu T2SQL_CH_PASSWORD trong .env")
    with open(os.path.join(HERE, "access.sql"), encoding="utf-8") as f:
        text = f.read()
    stmts = [s.strip() for s in text.split(";") if s.strip() and not all(
        ln.strip().startswith("--") or not ln.strip() for ln in s.splitlines())]
    for s in stmts:
        c.command(s)
    print(f"Đã áp dụng {len(stmts)} lệnh phân quyền (access.sql)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="hệ số số hóa đơn / log (1.0 = ~30 triệu hóa đơn)")
    ap.add_argument("--access-only", action="store_true")
    args = ap.parse_args()
    c = admin_client()
    if args.access_only:
        apply_access(c)
        return

    t_all = time.perf_counter()

    def run(sql, label=None):
        t0 = time.perf_counter()
        c.command(sql)
        if label:
            print(f"  {label}: {time.perf_counter() - t0:.1f}s", flush=True)

    print(f"ClickHouse {c.server_version}, database {DB}, scale {args.scale}", flush=True)
    c.command(f"DROP DATABASE IF EXISTS {DB} SYNC")
    for s in ddl():
        c.command(s)
    skel_cols = """invoice_id UInt64, seller_id UInt32, industry_code String, series_id UInt32, symbol String,
        invoice_no UInt32, inv_type UInt8, tax_code_type UInt8, issued_at DateTime('Asia/Ho_Chi_Minh'),
        buyer_id Nullable(UInt64), currency String, exchange_rate Float64, payment_method String, nature UInt8,
        related_invoice_id Nullable(UInt64), status UInt8, cqt_code Nullable(String), item_count UInt16,
        channel String, updated_at DateTime('Asia/Ho_Chi_Minh')"""
    c.command(f"CREATE TABLE {DB}._skel ({skel_cols}) ENGINE = MergeTree ORDER BY invoice_id")
    c.command(f"CREATE TABLE {DB}._items AS {DB}.invoice_items ENGINE = MergeTree ORDER BY (invoice_id, line_no)")

    print("Danh mục, người bán, người mua, gói dịch vụ, chứng thư số...", flush=True)
    for s in static_inserts():
        run(s)
    run(sellers_insert(), "sellers")
    run(buyers_insert(), "buyers")
    run(subscriptions_insert(), "subscriptions")
    run(certificates_insert(), "certificates")

    print("Hóa đơn + dòng hàng theo tháng...", flush=True)
    for idx, (y, m) in enumerate(MONTHS):
        t0 = time.perf_counter()
        c.command(f"TRUNCATE TABLE {DB}._skel")
        c.command(f"TRUNCATE TABLE {DB}._items")
        c.command(skeleton_insert(y, m, month_count(idx, m, args.scale)))
        c.command(derived_insert())
        c.command(items_insert())
        c.command(invoices_insert())
        c.command(f"INSERT INTO {DB}.invoice_items SELECT * FROM {DB}._items")
        print(f"  {y}-{m:02d}: {time.perf_counter() - t0:.1f}s", flush=True)
    c.command(f"DROP TABLE {DB}._skel")
    c.command(f"DROP TABLE {DB}._items")
    run(f"OPTIMIZE TABLE {DB}.invoices FINAL", "gộp invoices (1 part / tháng)")

    print("Ký hiệu, thông điệp cơ quan thuế, bảng tổng hợp ngày...", flush=True)
    run(series_insert(), "invoice_series")
    for y, m in MONTHS:
        for s in tax_messages_inserts(y * 100 + m):
            c.command(s)
    print("  tax_messages: xong", flush=True)
    for s in daily_stats_inserts():
        run(s)
    print("  daily_seller_stats: xong", flush=True)

    # Từ đây tắt merge của invoices: phiên bản cũ nằm ở part riêng và giữ nguyên (cần FINAL để bỏ).
    c.command(f"ALTER TABLE {DB}.invoices MODIFY SETTING max_bytes_to_merge_at_max_space_in_pool = 1, "
              f"max_bytes_to_merge_at_min_space_in_pool = 1")
    for y, m in MONTHS:
        for s in old_versions_insert(y * 100 + m):
            c.command(s)
    print("  invoices: đã thêm phiên bản cũ", flush=True)

    print("Log API...", flush=True)
    per_month = API_REQUESTS_TOTAL * args.scale / len(MONTHS)
    for idx, (y, m) in enumerate(MONTHS):
        c.command(api_insert(y, m, max(1000, int(per_month * (0.6 + 0.8 * idx / (len(MONTHS) - 1))))))
    print("  api_requests: xong", flush=True)

    apply_access(c)
    print("\nSố dòng:")
    for t in TABLES:
        n = c.query(f"SELECT count() FROM {DB}.{t}").result_rows[0][0]
        print(f"  {t:20s} {n:>14,}")
    size = c.query(f"SELECT formatReadableSize(sum(bytes_on_disk)) FROM system.parts WHERE database = '{DB}' AND active").result_rows[0][0]
    print(f"Dung lượng trên đĩa: {size}; tổng thời gian {time.perf_counter() - t_all:.0f}s")


if __name__ == "__main__":
    main()
