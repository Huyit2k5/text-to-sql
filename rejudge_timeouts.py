"""Chấm lại các câu bị chấm sai vì truy vấn QUÁ HẠN / QUÁ TẢI khi database đang bận (không phải vì model viết sai).

Khi chạy nhiều thí nghiệm song song, ClickHouse có thể quá tải và các câu SQL đúng bị dừng ở 30 giây. Script này chạy lại
ĐÚNG câu SQL model đã sinh (không gọi lại model) lúc database rảnh, rồi chấm lại so với SQL chuẩn. Câu nào vẫn quá hạn khi
chạy một mình thì vẫn bị tính sai (đó là lỗi thật: truy vấn quá nặng). Ghi lại jsonl và summary.json.

  python rejudge_timeouts.py results/einv_hist results/einv_cold        # quét mọi lượt / bộ / cấu hình trong các thư mục
  python rejudge_timeouts.py results/einv_hist --dry-run
Chỉ chạy khi không có thí nghiệm nào khác đang chạy.
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

from t2sql import ROOT, datasets
from t2sql.db import make_backend
from t2sql.evaluation import categorize, results_match

MARKERS = ("vượt quá", "giới hạn tài nguyên")
EVAL = {"dev": "eval.json", "holdout": "eval_holdout.json"}


def needs_rejudge(rec):
    err = rec.get("error") or ""
    return rec.get("kind") == "result" and not rec.get("ok") and any(m in err for m in MARKERS) and rec.get("sql")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL_EINVOICE"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from evaluate import summarize

    pipe_backend = make_backend(args.db, max_rows=200, timeout_s=30)          # như pipeline khi trả lời
    gold_backend = make_backend(args.db, max_rows=100_000, timeout_s=60)      # như evaluate.py khi tính SQL chuẩn
    ds = datasets.for_backend(pipe_backend)
    folder = os.path.dirname(ds.docs_path)
    items = {name: {it["id"]: it for it in json.load(open(os.path.join(folder, fn), encoding="utf-8"))}
             for name, fn in EVAL.items()}
    gold_cache = {}
    total = fixed = 0
    for root in args.roots:
        for path in sorted(glob.glob(os.path.join(root, "*", "r*", "*", "*.jsonl"))):
            set_name = path.replace("\\", "/").split("/")[-4]
            if set_name not in items or os.path.basename(path).startswith("query_metrics"):
                continue
            recs = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
            todo = [r for r in recs if needs_rejudge(r)]
            if not todo:
                continue
            changed = 0
            for r in todo:
                total += 1
                it = items[set_name][r["item_id"]]
                if args.dry_run:
                    continue
                res = pipe_backend.run(r["sql"])
                if not res.ok and any(m in (res.error or "") for m in MARKERS):
                    r["rejudged"] = "vẫn quá hạn khi chạy một mình"
                    continue
                key = (set_name, it["id"])
                if key not in gold_cache:
                    gold_cache[key] = gold_backend.run(it["sql"], safe=False)
                g = gold_cache[key]
                ok = res.ok
                rows = res.rows if ok else []
                was = r["correct"]
                r.update(ok=ok, rows=len(rows) if ok else None, error=None if ok else res.error, rejudged="đã chạy lại")
                r["pred_ncols"] = len(res.columns) if ok else None
                r["pred_preview"] = [list(x) for x in rows[:5]]
                r["correct"] = ok and results_match(rows, g.rows, it.get("ordered", False))
                r["correct_lenient"] = ok and results_match(rows, g.rows, it.get("ordered", False), True)
                if r["correct"]:
                    r.pop("error_category", None)
                else:
                    r["error_category"] = categorize(it, r)
                changed += int(r["correct"] and not was)
                fixed += int(r["correct"] and not was)
            print(f"{path.replace(ROOT + os.sep, '')}: {len(todo)} câu quá hạn, {changed} câu đúng khi chạy lại", flush=True)
            if args.dry_run:
                continue
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            sp = os.path.join(os.path.dirname(path), "summary.json")
            cfg = os.path.basename(path)[:-len(".jsonl")]
            if os.path.exists(sp):
                summary = json.load(open(sp, encoding="utf-8"))
                if cfg in summary.get("configs", {}):
                    s = summarize(recs)
                    summary["configs"][cfg].update({**s, "errors": dict(s["errors"])})
                    with open(sp, "w", encoding="utf-8", newline="\n") as f:
                        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"Tổng: {total} câu bị chấm sai vì quá hạn; {fixed} câu thực ra đúng.")


if __name__ == "__main__":
    main()
