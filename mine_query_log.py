"""Lấy lịch sử truy vấn của analyst từ system.query_log của ClickHouse và xem tri thức khai thác được.

  python mine_query_log.py                        # db mặc định: T2SQL_DATABASE_URL_EINVOICE
  python mine_query_log.py --db "$T2SQL_DATABASE_URL_XYZ" --database xyz

Ghi datasets/<database>/query_history.jsonl (ảnh chụp: lúc chạy pipeline không cần quyền đọc system.query_log).
Cần quyền đọc system.query_log: dùng user quản trị (CLICKHOUSE_USER / CLICKHOUSE_PASSWORD trong .env).
"""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT, datasets
from t2sql.db import make_backend
from t2sql.history import HistoryKnowledge, fetch_query_log


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL"))
    ap.add_argument("--database", default=None, help="tên database trong ClickHouse (mặc định lấy từ URL)")
    ap.add_argument("--exclude-user-prefix", nargs="*", default=["t2sql", "default"],
                    help="bỏ user của ứng dụng và user quản trị (không phải analyst)")
    ap.add_argument("--limit", type=int, default=50_000)
    ap.add_argument("--min-support", type=float, default=0.6)
    ap.add_argument("--min-n", type=int, default=8)
    args = ap.parse_args()

    import clickhouse_connect
    u = urlsplit(args.db)
    database = args.database or u.path.strip("/")
    client = clickhouse_connect.get_client(host=u.hostname, port=u.port or 8123, secure=u.scheme == "clickhouses",
                                           username=os.environ.get("CLICKHOUSE_USER") or "default",
                                           password=os.environ.get("CLICKHOUSE_PASSWORD", ""))
    client.command("SYSTEM FLUSH LOGS")
    rows = fetch_query_log(client, database, tuple(args.exclude_user_prefix), args.limit)
    users = {}
    for r in rows:
        users[r["user"]] = users.get(r["user"], 0) + 1
    print(f"Đọc được {len(rows)} truy vấn khác nhau của {len(users)} user: {users}")

    ds = datasets.for_database(database)
    folder = os.path.dirname(ds.docs_path)
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "query_history.jsonl")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("Đã ghi", out)

    backend = make_backend(args.db)
    schema = backend.load_schema(ds.docs_path)
    cols = {t: set(tb.column_names()) for t, tb in schema.tables.items()}
    hk = HistoryKnowledge([r["sql"] for r in rows], cols, min_support=args.min_support, min_n=args.min_n)
    print(f"\nTri thức khai thác được (min_support={args.min_support}, min_n={args.min_n}), theo từng bảng:")
    print("  FINAL:", {t: f"{h}/{n}" for t, (h, n) in hk.final_support.items()})
    print("  cột giờ bọc toTimeZone:", {f"{t}.{c}": f"{w}/{n}" for (t, c), (w, n, _) in hk.tz_cols.items()})
    for (t, c), (top, n) in hk.pred_top.items():
        print(f"  lọc {t}.{c} (n={n}):", top)
    for alias, tabs, expr, c, total in hk.formulas:
        print(f"  {alias} {sorted(tabs)}: {c}/{total} {expr}")
    print("  JOIN:", hk.joins[:12])
    print(f"  {sum(q.conforms for q in hk.queries)}/{hk.n} truy vấn tuân theo mọi quy ước (dùng làm ví dụ minh họa)")


if __name__ == "__main__":
    main()
