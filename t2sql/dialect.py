"""Dialect SQL: chuyển SQL mẫu (viết cho SQLite) sang DB đích và gợi ý cú pháp cho prompt."""
import re
from functools import lru_cache

SOURCE_DIALECT = "sqlite"   # dialect mà eval/dataset.json và eval/fewshot_pool.json được viết

# Khóa ghi đè thủ công trong dataset / few-shot khi chuyển tự động không đúng.
OVERRIDE_KEYS = {"postgres": "sql_pg"}

HINTS = {
    "sqlite": """Cú pháp SQLite:
- Cột ngày lưu dạng chuỗi 'YYYY-MM-DD'. Lấy năm/tháng: strftime('%Y', col), strftime('%Y-%m', col).
- Khoảng ngày: date('2025-06-30', '-1 month'); số ngày giữa hai ngày: julianday(a) - julianday(b).""",
    "postgres": """Cú pháp PostgreSQL:
- Cột ngày có kiểu DATE. Lấy năm/tháng: EXTRACT(YEAR FROM col), TO_CHAR(col, 'YYYY-MM'), DATE_TRUNC('month', col).
- Khoảng ngày: DATE '2025-06-30' - INTERVAL '1 month'; số ngày giữa hai ngày: a - b (kết quả là số nguyên).
- Hai số nguyên chia nhau ra số nguyên: nhân với 100.0 hoặc ép kiểu ::numeric khi cần tỉ lệ / phần trăm.
- Mọi cột không gộp trong SELECT phải có trong GROUP BY (trừ khi đã GROUP BY khóa chính của bảng chứa cột đó).
- Chuỗi dùng nháy đơn; so sánh chuỗi phân biệt hoa thường (dùng ILIKE nếu cần không phân biệt).""",
}

NAMES = {"sqlite": "SQLite", "postgres": "PostgreSQL"}


_CAST_TS = re.compile(r"CAST\(([A-Za-z_][\w.]*) AS TIMESTAMP\)")


@lru_cache(maxsize=4096)
def _transpile(sql: str, target: str) -> str:
    """Chuyển dialect bằng sqlglot rồi làm sạch để ví dụ few-shot trông như người viết.
    Model bắt chước ví dụ, nên cú pháp rườm rà (NULLIF chống chia 0, NULLS LAST, CAST thừa) dễ bị chép sai."""
    import sqlglot
    from sqlglot import exp
    tree = sqlglot.parse_one(sql, read=SOURCE_DIALECT)
    for node in tree.find_all(exp.Div):
        node.set("safe", None)                       # bỏ "/ NULLIF(x, 0)"
    for node in tree.find_all(exp.Ordered):          # bỏ "NULLS LAST/FIRST" (dữ liệu không có NULL ở cột sắp xếp)
        node.set("nulls_first", bool(node.args.get("desc")) if target == "postgres" else node.args.get("nulls_first"))
    out = tree.sql(dialect=target)
    if target == "postgres":
        out = _CAST_TS.sub(r"\1", out)               # TO_CHAR(CAST(col AS TIMESTAMP), ...) -> TO_CHAR(col, ...)
    return out


def to_dialect(sql: str, target: str) -> str:
    if not sql or target == SOURCE_DIALECT:
        return sql
    return _transpile(sql, target)


def example_sql(item: dict, target: str) -> str | None:
    """SQL của một mục dataset/few-shot cho dialect đích (ưu tiên bản viết tay nếu có)."""
    override = OVERRIDE_KEYS.get(target)
    if override and item.get(override):
        return item[override]
    return to_dialect(item.get("sql"), target)
