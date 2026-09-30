"""Dialect SQL: chuyển SQL mẫu (viết cho SQLite) sang DB đích và gợi ý cú pháp cho prompt."""
import re
from functools import lru_cache

SOURCE_DIALECT = "sqlite"   # dialect mà eval/dataset.json và eval/fewshot_pool.json được viết

# Khóa ghi đè thủ công trong dataset / few-shot khi chuyển tự động không đúng.
OVERRIDE_KEYS = {"postgres": "sql_pg", "clickhouse": "sql_ch"}

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

NAMES = {"sqlite": "SQLite", "postgres": "PostgreSQL", "clickhouse": "ClickHouse"}


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
    if target == "clickhouse":
        _complete_group_by(tree)
    out = tree.sql(dialect=target)
    if target == "postgres":
        out = _CAST_TS.sub(r"\1", out)               # TO_CHAR(CAST(col AS TIMESTAMP), ...) -> TO_CHAR(col, ...)
    if target == "clickhouse":
        out = _CH_YEAR.sub(r"toYear(\1) = \2", out)  # formatDateTime(col, '%Y') = '2024' -> toYear(col) = 2024
    return out


_CH_YEAR = re.compile(r"formatDateTime\(([A-Za-z_][\w.]*), '%Y'\) = '(\d{4})'")


def _complete_group_by(tree):
    """SQLite/Postgres cho phép GROUP BY khóa chính rồi SELECT cột khác của bảng đó; ClickHouse thì không.
    Thêm vào GROUP BY các cột trần (không nằm trong hàm gộp) ở SELECT và HAVING."""
    from sqlglot import exp
    for sel in tree.find_all(exp.Select):
        group = sel.args.get("group")
        if not group:
            continue
        have = {e.sql() for e in group.expressions}
        aliases = {e.alias for e in sel.expressions if isinstance(e, exp.Alias)}
        cands = [e.this if isinstance(e, exp.Alias) else e for e in sel.expressions]
        having = sel.args.get("having")
        if having:
            cands += [c for c in having.find_all(exp.Column)
                      if not c.find_ancestor(exp.AggFunc, exp.Window) and c.find_ancestor(exp.Select) is sel]
        for c in cands:
            if not isinstance(c, exp.Column) or isinstance(c.this, exp.Star) or c.sql() in have:
                continue
            if not c.table and c.name in aliases:
                continue
            group.append("expressions", c.copy())
            have.add(c.sql())


def to_dialect(sql: str, target: str) -> str:
    if not sql or target == SOURCE_DIALECT:
        return sql
    return _transpile(sql, target)


def example_sql(item: dict, target: str, source: str = SOURCE_DIALECT) -> str | None:
    """SQL của một mục dataset/few-shot cho dialect đích (ưu tiên bản viết tay nếu có).
    source: dialect mà trường "sql" được viết (bộ shop: SQLite; datasets/<tên>/ khai báo sql_dialect)."""
    override = OVERRIDE_KEYS.get(target)
    if override and item.get(override):
        return item[override]
    if source == target:
        return item.get("sql")
    if source != SOURCE_DIALECT:
        raise ValueError(f"Chưa hỗ trợ chuyển SQL {source} -> {target}")
    return to_dialect(item.get("sql"), target)
