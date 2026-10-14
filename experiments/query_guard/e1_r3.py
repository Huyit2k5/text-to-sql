"""E1: các câu bị luật R3 báo (hàm bọc cột khóa phân vùng) so với bản viết lại thành khoảng. Chỉ đọc."""
import json
import os
import re
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from t2sql.db import make_backend  # noqa: E402
from t2sql.safety import POLICIES  # noqa: E402

url = [l.split("=", 1)[1].strip() for l in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig") if l.startswith("T2SQL_DATABASE_URL=")][0]
be = make_backend(url, max_rows=100000, timeout_s=60)
c = be._client(POLICIES["admin"])

rows = []
for p in (os.path.join(ROOT, "results", "clickhouse_hddt", "production.jsonl"), os.path.join(ROOT, "results", "hddt_hold_noexp", "clickhouse_hddt", "production.jsonl")):
    rows += [json.loads(l) for l in open(p, encoding="utf-8")]

COL = r"(ArisingDate|InvArisingDate)"
YM = re.compile(r"toYear\(" + COL + r"\)\s*=\s*(\d{4})\s+AND\s+toMonth\(\1\)\s*=\s*(\d{1,2})", re.I)
YQ = re.compile(r"toYear\(" + COL + r"\)\s*=\s*(\d{4})\s+AND\s+toQuarter\(\1\)\s*=\s*([1-4])", re.I)


def ym_range(m):
    col, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
    ny, nm = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return f"{col} >= '{y}-{mo:02d}-01' AND {col} < '{ny}-{nm:02d}-01'"


def yq_range(m):
    col, y, q = m.group(1), int(m.group(2)), int(m.group(3))
    s, e = (q - 1) * 3 + 1, q * 3 + 1
    ny, ne = (y + 1, 1) if e > 12 else (y, e)
    return f"{col} >= '{y}-{s:02d}-01' AND {col} < '{ny}-{ne:02d}-01'"


def rewrite(sql):
    return YQ.sub(yq_range, YM.sub(ym_range, sql))


def measure(sql, n=3):
    c.query(sql)                                   # khởi động
    times, rr, rb = [], 0, 0
    for _ in range(n):
        t = time.perf_counter()
        res = c.query(sql)
        times.append((time.perf_counter() - t) * 1000)
        s = res.summary or {}
        rr, rb = int(s.get("read_rows", 0)), int(s.get("read_bytes", 0))
    return round(statistics.median(times), 1), rr, rb, [tuple(r) for r in res.result_rows]


def granules(sql):
    out = c.query("EXPLAIN indexes = 1 " + sql.replace("VATInvoice", "VATInvoice_local").replace("ProductInv", "ProductInv_local")).result_rows
    txt = "\n".join(r[0] for r in out)
    # dòng Granules đầu tiên (MinMax) và dòng cuối của khối Partition
    g = re.findall(r"Granules: (\d+)/(\d+)", txt)
    return g[0] if g else None


seen, results = set(), []
for r in rows:
    q = r.get("sql") or ""
    new = rewrite(q)
    if new == q or r["item_id"] in seen:
        continue
    seen.add(r["item_id"])
    try:
        a = measure(q)
        b = measure(new)
    except Exception as e:  # noqa: BLE001
        print(r["item_id"], "lỗi:", str(e)[:100])
        continue
    same = a[3] == b[3]
    results.append({"id": r["item_id"], "same_result": same, "ms_orig": a[0], "ms_range": b[0], "rows_orig": a[1], "rows_range": b[1],
                    "bytes_orig": a[2], "bytes_range": b[2], "gran_orig": granules(q), "gran_range": granules(new)})
    x = results[-1]
    print(f"{x['id']:>4} kết quả {'GIỐNG' if same else 'KHÁC'} | ms {x['ms_orig']:>7} -> {x['ms_range']:>7} | dòng đọc {x['rows_orig']:>10,} -> {x['rows_range']:>10,} | granule {x['gran_orig']} -> {x['gran_range']}", flush=True)

os.makedirs(os.path.join(ROOT, "results", "hddt_lint"), exist_ok=True)
json.dump(results, open(os.path.join(ROOT, "results", "hddt_lint", "e1_r3.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
if results:
    print("\nSố câu:", len(results), "| kết quả khác:", sum(not x["same_result"] for x in results))
    print("ms trung vị:", statistics.median(x["ms_orig"] for x in results), "->", statistics.median(x["ms_range"] for x in results))
    print("dòng đọc tổng:", f"{sum(x['rows_orig'] for x in results):,}", "->", f"{sum(x['rows_range'] for x in results):,}")
    print("câu đọc ít hơn:", sum(x["rows_range"] < x["rows_orig"] for x in results), "| nhiều hơn:", sum(x["rows_range"] > x["rows_orig"] for x in results))
