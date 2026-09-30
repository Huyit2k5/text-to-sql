"""Xuất database mẫu (data/shop.db) thành script khởi tạo ClickHouse.

Chạy:  python data/export_clickhouse.py
Sinh:  docker/clickhouse/sql/01_schema.sql  (database, bảng MergeTree, COMMENT nghiệp vụ)
       docker/clickhouse/sql/02_data.sql    (dữ liệu)
User / role / phân quyền nằm ở docker/clickhouse/sql/03_access.sql (viết tay, không sinh).

ClickHouse không có khóa ngoại: quan hệ giữa các bảng khai báo ở mục "relations" của data/schema_docs.json.
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "shop.db")
DOCS = os.path.join(HERE, "schema_docs.json")
OUT = os.path.join(ROOT, "docker", "clickhouse", "sql")
DATABASE = "shop"

TABLES = ["suppliers", "customers", "products", "orders", "order_items", "reviews"]

# Kiểu ClickHouse. Tiền dùng Float64 (không dùng Decimal): ClickHouse báo lỗi khi trộn Decimal với số thực
# (ví dụ `unit_price * 1.1`), model sẽ vấp liên tục. Chuỗi ít giá trị khác nhau dùng LowCardinality.
CH_TYPES = {
    ("customers", "created_at"): "Date",
    ("orders", "order_date"): "Date",
    ("reviews", "created_at"): "Date",
    ("products", "is_active"): "UInt8",
    ("orders", "status"): "UInt8",
    ("reviews", "rating"): "UInt8",
    ("suppliers", "country"): "LowCardinality(String)",
    ("customers", "city"): "LowCardinality(String)",
    ("customers", "segment"): "LowCardinality(String)",
    ("products", "category"): "LowCardinality(String)",
    ("orders", "payment_method"): "LowCardinality(String)",
}
# Khóa sắp xếp (ORDER BY của MergeTree): chọn theo cách truy vấn hay lọc nhất.
ORDER_BY = {"orders": "(order_date, order_id)", "order_items": "(order_id, order_item_id)",
            "reviews": "(product_id, review_id)"}


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    con = sqlite3.connect(DB)
    with open(DOCS, encoding="utf-8") as f:
        docs = json.load(f)["tables"]
    os.makedirs(OUT, exist_ok=True)
    header = "-- Sinh tự động bởi data/export_clickhouse.py. Không sửa tay."

    ddl = [header, f"CREATE DATABASE IF NOT EXISTS {DATABASE};"]
    for t in TABLES:
        cols = con.execute(f"PRAGMA table_info({t})").fetchall()
        tdoc = docs.get(t, {})
        lines, pk = [], None
        for _, name, ctype, _, _, is_pk in cols:
            nullable = con.execute(f"SELECT 1 FROM {t} WHERE {name} IS NULL LIMIT 1").fetchone()
            ch = CH_TYPES.get((t, name), "Int32" if ctype.upper() == "INTEGER" else
                              "Float64" if ctype.upper() == "REAL" else "String")
            if nullable:
                ch = f"Nullable({ch})"
            line = f"    {name} {ch}"
            if tdoc.get("columns", {}).get(name):
                line += f" COMMENT {q(tdoc['columns'][name])}"
            lines.append(line)
            if is_pk:
                pk = name
        ddl.append(f"CREATE TABLE IF NOT EXISTS {DATABASE}.{t} (\n" + ",\n".join(lines) + "\n)\n"
                   f"ENGINE = MergeTree\nORDER BY {ORDER_BY.get(t, pk)}\n"
                   + (f"COMMENT {q(tdoc['description'])}" if tdoc.get("description") else "") + ";")
    with open(os.path.join(OUT, "01_schema.sql"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n\n".join(ddl) + "\n")

    data = [header]
    counts = {}
    for t in TABLES:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        rows = con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
        counts[t] = len(rows)
        for i in range(0, len(rows), 1000):
            values = ",\n".join("(" + ", ".join(q(v) for v in r) + ")" for r in rows[i:i + 1000])
            data.append(f"INSERT INTO {DATABASE}.{t} ({', '.join(cols)}) VALUES\n{values};")
    with open(os.path.join(OUT, "02_data.sql"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(data) + "\n")
    print("Đã ghi", OUT, counts)


if __name__ == "__main__":
    main()
