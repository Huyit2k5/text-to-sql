"""Dialect SQL: gợi ý cú pháp ClickHouse cho prompt và chọn SQL mẫu."""

HINTS = {
    "clickhouse": """Cú pháp ClickHouse:
- Cột ngày có kiểu Date. Lấy năm/tháng/quý: toYear(col), toMonth(col), toQuarter(col), toStartOfMonth(col),
  formatDateTime(col, '%Y-%m'). Hôm nay là toDate('2025-06-30') (KHÔNG dùng today()).
- Khoảng ngày: toDate('2025-06-30') - INTERVAL 1 MONTH, subtractDays(toDate('2025-06-30'), 7);
  số ngày giữa hai ngày: dateDiff('day', a, b) (= b - a).
- Phép chia `/` luôn ra số thực; chia lấy phần nguyên dùng intDiv(a, b).
- Top N trong mỗi nhóm: ORDER BY nhom, gia_tri DESC LIMIT N BY nhom (hoặc hàm cửa sổ RANK() OVER (PARTITION BY ...)).
- Mọi cột không gộp trong SELECT phải nằm trong GROUP BY (kể cả khi đã GROUP BY khóa chính), ví dụ
  GROUP BY p.product_id, p.name. Được dùng alias của SELECT trong GROUP BY / HAVING / ORDER BY.
- Tên hàm phân biệt hoa thường (toYear, dateDiff, countIf, sumIf...). count() đếm dòng; uniqExact(col) đếm giá trị khác nhau.
- Không dùng table function (numbers(), url()...), bảng system.*, mệnh đề SETTINGS hay FORMAT.""",
}

NAMES = {"clickhouse": "ClickHouse"}


def example_sql(item: dict) -> str | None:
    """SQL của một mục dataset / few-shot. Mọi bộ dữ liệu viết thẳng bằng ClickHouse (trường "sql")."""
    return item.get("sql")
