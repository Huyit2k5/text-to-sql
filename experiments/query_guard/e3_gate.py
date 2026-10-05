"""E3: phân bố EXPLAIN ESTIMATE của SQL chuẩn và SQL model; E0b: luật FINAL / is_deleted offline."""
import json
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from t2sql.db import make_backend  # noqa: E402
from t2sql.safety import POLICIES  # noqa: E402

url = [l.split("=", 1)[1].strip() for l in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig") if l.startswith("T2SQL_DATABASE_URL=")][0]
be = make_backend(url, max_rows=100000, timeout_s=60)

files = {"dev": os.path.join(ROOT, "results", "clickhouse_hddt", "production.jsonl"),
         "holdout": os.path.join(ROOT, "results", "hddt_hold_noexp", "clickhouse_hddt", "production.jsonl")}
rows = []
for name, p in files.items():
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        r["set"] = name
        rows.append(r)

est = {"gold": [], "model": []}
for r in rows:
    for who, key in (("gold", "gold_sql"), ("model", "sql")):
        q = r.get(key)
        if not q:
            continue
        e = be.estimate_rows(q)
        if e is not None:
            est[who].append((e[0], r["item_id"], r["set"], bool(r.get("correct"))))

for who, v in est.items():
    xs = sorted(x[0] for x in v)
    q = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]  # noqa: E731
    print(f"{who}: {len(xs)} câu | p50 {q(.5):,} | p90 {q(.9):,} | p99 {q(.99):,} | max {xs[-1]:,}")
    for th in (1_000_000, 2_000_000, 5_000_000, 10_000_000):
        over = [x for x in v if x[0] > th]
        print(f"   ngưỡng {th:>10,}: vượt {len(over):>2} câu", [(x[1], x[3]) for x in over][:8])
    top = sorted(v, reverse=True)[:5]
    print("   5 câu ước lượng lớn nhất:", [(f"{x[0]:,}", x[1], 'đúng' if x[3] else 'sai') for x in top])

# E0b: luật FINAL / is_deleted (offline)
print("\nE0b: luật FINAL và is_deleted trên SQL model")
bad = []
for r in rows:
    q = (r.get("sql") or "")
    if not q:
        continue
    for t in re.findall(r"\b(?:FROM|JOIN)\s+(VATInvoice|ProductInv)\b(?!_local)([^,]*?)(?=\bWHERE\b|\bJOIN\b|\bON\b|\bGROUP\b|\bORDER\b|\)|$)", q, re.I | re.S):
        if "FINAL" not in t[1].upper():
            bad.append((r["item_id"], "thiếu FINAL", bool(r.get("correct"))))
    if re.search(r"\b(VATInvoice|ProductInv)\b", q, re.I) and "is_deleted" not in q.lower():
        bad.append((r["item_id"], "thiếu is_deleted", bool(r.get("correct"))))
print("  số lần báo:", len(bad), bad[:10])
