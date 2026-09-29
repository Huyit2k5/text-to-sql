"""Xuất database mẫu (data/shop.db) thành script khởi tạo PostgreSQL.

Chạy:  python data/export_postgres.py
Sinh:  docker/postgres/init/01_schema.sql  (bảng, khóa, index, COMMENT nghiệp vụ)
       docker/postgres/init/02_data.sql    (dữ liệu)
Role / phân quyền nằm ở docker/postgres/init/03_roles.sh (viết tay, không sinh).
"""
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(HERE, "shop.db")
DOCS = os.path.join(HERE, "schema_docs.json")
OUT = os.path.join(ROOT, "docker", "postgres", "init")

# Thứ tự tạo bảng theo khóa ngoại.
TABLES = ["suppliers", "customers", "products", "orders", "order_items", "reviews"]

# Kiểu PostgreSQL cho từng cột (SQLite chỉ có INTEGER/TEXT/REAL/DATE lỏng lẻo).
PG_TYPES = {
    ("customers", "created_at"): "DATE",
    ("orders", "order_date"): "DATE",
    ("reviews", "created_at"): "DATE",
    ("products", "unit_price"): "NUMERIC(14,2)",
    ("order_items", "unit_price"): "NUMERIC(14,2)",
    ("order_items", "discount"): "NUMERIC(4,2)",
    ("orders", "shipping_fee"): "NUMERIC(14,2)",
    ("products", "is_active"): "SMALLINT",
    ("orders", "status"): "SMALLINT",
    ("reviews", "rating"): "SMALLINT",
}


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    con = sqlite3.connect(DB)
    with open(DOCS, encoding="utf-8") as f:
        docs = json.load(f)["tables"]
    os.makedirs(OUT, exist_ok=True)

    ddl = ["-- Sinh tự động bởi data/export_postgres.py. Không sửa tay.", "BEGIN;"]
    comments = []
    for t in TABLES:
        cols = con.execute(f"PRAGMA table_info({t})").fetchall()
        fks = {r[3]: (r[2], r[4]) for r in con.execute(f"PRAGMA foreign_key_list({t})")}
        lines = []
        for _, name, ctype, notnull, _, pk in cols:
            pg = PG_TYPES.get((t, name), "INTEGER" if ctype.upper() == "INTEGER" else
                              "DOUBLE PRECISION" if ctype.upper() == "REAL" else "TEXT")
            line = f"    {name} {pg}"
            if pk:
                line += " PRIMARY KEY"
            elif notnull:
                line += " NOT NULL"
            if name in fks:
                line += f" REFERENCES {fks[name][0]}({fks[name][1]})"
            lines.append(line)
        ddl.append(f"CREATE TABLE {t} (\n" + ",\n".join(lines) + "\n);")
        for name in fks:
            ddl.append(f"CREATE INDEX ON {t} ({name});")
        tdoc = docs.get(t, {})
        if tdoc.get("description"):
            comments.append(f"COMMENT ON TABLE {t} IS {q(tdoc['description'])};")
        for c, d in tdoc.get("columns", {}).items():
            comments.append(f"COMMENT ON COLUMN {t}.{c} IS {q(d)};")
    ddl.append("CREATE INDEX ON orders (order_date);")
    ddl += comments + ["COMMIT;", ""]
    with open(os.path.join(OUT, "01_schema.sql"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(ddl))

    data = ["-- Sinh tự động bởi data/export_postgres.py. Không sửa tay.", "BEGIN;"]
    counts = {}
    for t in TABLES:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        rows = con.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
        counts[t] = len(rows)
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            values = ",\n".join("(" + ", ".join(q(v) for v in r) + ")" for r in chunk)
            data.append(f"INSERT INTO {t} ({', '.join(cols)}) VALUES\n{values};")
    data += ["ANALYZE;", "COMMIT;", ""]
    with open(os.path.join(OUT, "02_data.sql"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(data))
    print("Đã ghi", OUT, counts)


if __name__ == "__main__":
    main()
