"""Đo offline độ chính xác của các quy tắc kiểm tra hình dạng (t2sql/checks.py), không gọi model.

  1. Chạy 60 SQL chuẩn: quy tắc KHÔNG được báo câu nào (báo nhầm trên đáp án đúng = hỏng).
  2. Chạy lại SQL model đã sinh trong các lượt đánh giá có sẵn, so nghi vấn với nhãn đúng/sai:
       báo đúng  = có nghi vấn và câu đó sai      (quy tắc có ích)
       báo nhầm  = có nghi vấn nhưng câu đó đúng   (quy tắc có hại: có thể làm model sửa hỏng)
       bỏ sót    = câu sai nhưng không có nghi vấn

  python analyze_shape_checks.py                        # dùng results/clickhouse_einvoice và results/clickhouse_einvoice_run1
  python analyze_shape_checks.py --runs results/clickhouse_einvoice
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT, datasets
from t2sql.checks import check_result
from t2sql.db import make_backend
from t2sql.dialect import example_sql
from t2sql.pipeline import ABLATION_ORDER


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", default=[os.path.join(ROOT, "results", "clickhouse_einvoice"),
                                                  os.path.join(ROOT, "results", "clickhouse_einvoice_run1")])
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL"), help="ClickHouse chứa bộ dữ liệu cần phân tích")
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "clickhouse_einvoice", "shape_checks_offline.json"))
    args = ap.parse_args()
    db = make_backend(args.db, max_rows=100_000, timeout_s=30)
    with open(datasets.for_backend(db).eval_path, encoding="utf-8") as f:
        items = {it["id"]: it for it in json.load(f)}
    cache = {}

    def run(sql):
        if sql not in cache:
            cache[sql] = db.run(sql, safe=False)
        return cache[sql]

    # 1) SQL chuẩn
    gold_flags = []
    for iid, it in items.items():
        if not it.get("sql"):
            continue
        res = run(example_sql(it))
        issues = check_result(it["question"], res.columns, res.rows)
        if issues:
            gold_flags.append((iid, [i.rule for i in issues], issues[0].message))
    print(f"SQL chuẩn: {len(gold_flags)} / {sum(1 for it in items.values() if it.get('sql'))} câu bị báo nghi vấn (yêu cầu 0)")
    for g in gold_flags:
        print("   BÁO NHẦM", g)

    # 2) SQL model đã sinh
    stats = defaultdict(Counter)
    examples = defaultdict(list)
    for run_dir in args.runs:
        for cfg in ABLATION_ORDER:
            path = os.path.join(run_dir, f"{cfg}.jsonl")
            if not os.path.exists(path):
                continue
            for line in open(path, encoding="utf-8"):
                r = json.loads(line)
                if not r.get("sql") or r["difficulty"] == "unanswerable":
                    continue
                res = run(r["sql"])
                if not res.ok or not res.rows:
                    continue   # lỗi / rỗng: vòng tự sửa hiện có đã xử lý
                issues = check_result(r["question"], res.columns, res.rows)
                rules = sorted({i.rule for i in issues}) or ["-"]
                for rule in rules:
                    key = "báo đúng" if (issues and not r["correct"]) else "báo nhầm" if issues else \
                        "bỏ sót" if not r["correct"] else "đúng, không báo"
                    stats[rule][key] += 1
                    if issues and len(examples[(rule, key)]) < 4:
                        examples[(rule, key)].append(f"{os.path.basename(run_dir)}/{cfg}/{r['item_id']}")
                stats["TỔNG"]["báo đúng" if (issues and not r["correct"]) else "báo nhầm" if issues else
                              "bỏ sót" if not r["correct"] else "đúng, không báo"] += 1

    print("\nSQL model sinh (chạy được, có kết quả):")
    for rule in sorted(stats):
        c = stats[rule]
        print(f"  {rule:5} báo đúng {c['báo đúng']:3}  báo nhầm {c['báo nhầm']:3}  "
              f"bỏ sót {c['bỏ sót']:3}  đúng-không-báo {c['đúng, không báo']:3}")
    for (rule, key), ex in sorted(examples.items()):
        print(f"    {rule} {key}: {', '.join(ex)}")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"gold_false_positives": gold_flags, "stats": {k: dict(v) for k, v in stats.items()},
                   "examples": {f"{k[0]} {k[1]}": v for k, v in examples.items()}}, f, ensure_ascii=False, indent=2)
    print(f"\nĐã ghi {args.out}")


if __name__ == "__main__":
    main()
