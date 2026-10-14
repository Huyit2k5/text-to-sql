"""Chấm lại một số câu trong kết quả đã lưu (không gọi lại model) sau khi SQL chuẩn / đáp án thay thế của chúng thay đổi.

  python experiments/audit/rejudge_items.py --items h18 h45 o12 o20 --runs results/a/clickhouse_hddt/production.jsonl ...

Chạy lại ĐÚNG câu SQL model đã sinh trên ClickHouse rồi so với SQL chuẩn mới và mọi alt_sql. Ghi kết quả vào <file>.rejudged.jsonl.
Dùng khi phát hiện bộ chấm thiếu một cách hiểu hợp lệ: áp cùng quy tắc cho mọi cấu hình đang so sánh (kể cả cấu hình không có bộ nhớ).
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from t2sql import datasets  # noqa: E402
from t2sql.db import make_backend  # noqa: E402
from t2sql.evaluation import results_match  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", nargs="+", required=True)
    ap.add_argument("--runs", nargs="+", required=True)
    args = ap.parse_args()
    url = next(line.split("=", 1)[1].strip() for line in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig")
               if line.startswith("T2SQL_DATABASE_URL="))
    ex = make_backend(url, max_rows=100000, timeout_s=120)
    base = os.path.dirname(datasets.for_database("hddt").eval_path)
    gold = {}
    for f in ("eval.json", "eval_holdout.json"):
        for it in json.load(open(os.path.join(base, f), encoding="utf-8")):
            if it["id"] in args.items:
                gold[it["id"]] = (it, [ex.run(s, safe=False) for s in [it["sql"]] + it.get("alt_sql", [])])
    for path in args.runs:
        out, changes = [], []
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r["item_id"] in gold and r.get("sql") and r.get("kind") == "result":
                it, golds = gold[r["item_id"]]
                res = ex.run(r["sql"], safe=False)
                new = bool(res.ok and any(g.ok and results_match(res.rows, g.rows, it.get("ordered", False)) for g in golds))
                if new != bool(r["correct"]):
                    changes.append((r["item_id"], r["correct"], new))
                r["correct"] = new
            out.append(r)
        with open(path + ".rejudged.jsonl", "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        print(os.path.relpath(path, ROOT), "đổi:", changes)


if __name__ == "__main__":
    main()
