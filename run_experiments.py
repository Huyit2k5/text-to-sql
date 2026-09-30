"""Chạy lặp nhiều lượt các cấu hình trên bộ dev và bộ held-out, rồi tổng hợp trung bình / khoảng dao động.

  python run_experiments.py --db "$T2SQL_DATABASE_URL_EINVOICE" --runs 3
  python run_experiments.py --summarize-only          # chỉ tổng hợp lại từ kết quả đã có

Kết quả: results/einv_exp/<bộ>/r<k>/clickhouse_einvoice/*.jsonl, results/einv_exp/summary.json, summary.md
"""
import argparse
import json
import os
import statistics
import subprocess
import sys

from t2sql import ROOT

SETS = {"dev": "datasets/einvoice/eval.json", "holdout": "datasets/einvoice/eval_holdout.json"}
# "reasoning" (bật reasoning cho câu khó) vẫn chạy được qua --variants, nhưng mặc định bỏ vì chậm ~10 lần.
VARIANTS = ["shapecheck", "lookup", "costguard", "verify"]
LABELS = {"shapecheck": "Trước cải tiến (kiểm tra hình dạng)", "lookup": "+ Danh mục, gợi ý lỗi",
          "costguard": "+ Chặn truy vấn nặng", "verify": "+ Tự soát logic", "reasoning": "+ Reasoning câu khó"}
OUT = os.path.join(ROOT, "results", "einv_exp")


def run_dir(set_name, k):
    return os.path.join(OUT, set_name, f"r{k}", "clickhouse_einvoice")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize(runs):
    out = {"variants": VARIANTS, "labels": LABELS, "sets": {}}
    for set_name in SETS:
        per_variant = {}
        for v in VARIANTS:
            rows = []
            for k in range(1, runs + 1):
                d = run_dir(set_name, k)
                sp = os.path.join(d, "summary.json")
                if not os.path.exists(sp):
                    continue
                with open(sp, encoding="utf-8") as f:
                    s = json.load(f)["configs"].get(v)
                recs = read_jsonl(os.path.join(d, f"{v}.jsonl"))
                if not s or not recs:
                    continue
                atts = [a for r in recs for a in r.get("attempts", [])]
                rows.append({
                    "run": k, "ex": s["ex"], "ex_lenient": s["ex_lenient"], "by_difficulty": s["by_difficulty"],
                    "refusal": s["refusal_acc"], "calls": s["usage"]["calls"], "tok_in": s["usage"]["input_tokens"],
                    "latency_ms": s["avg_latency_ms"],
                    "guard": sum(1 for a in atts if a.get("estimated_rows")),
                    "verdicts": sum(1 for a in atts if a.get("verdict")),
                    "reasoning": sum(1 for r in recs if r.get("reasoning")),
                    "wrong": sorted(r["item_id"] for r in recs if not r["correct"]),
                })
            if not rows:
                continue
            ex = [r["ex"] for r in rows]
            agg = lambda key: statistics.mean(r[key] for r in rows)
            per_variant[v] = {
                "n_runs": len(rows), "ex_mean": statistics.mean(ex), "ex_min": min(ex), "ex_max": max(ex),
                "ex_lenient_mean": agg("ex_lenient"),
                "by_difficulty": {d: statistics.mean(r["by_difficulty"].get(d, 0) for r in rows)
                                  for d in ("easy", "medium", "hard", "unanswerable")},
                "calls_mean": agg("calls"), "tok_in_mean": agg("tok_in"), "latency_ms_mean": agg("latency_ms"),
                "guard_mean": agg("guard"), "verdicts_mean": agg("verdicts"), "reasoning_mean": agg("reasoning"),
                "runs": rows,
            }
        out["sets"][set_name] = per_variant
    return out


def markdown(s):
    lines = []
    for set_name, per in s["sets"].items():
        lines += [f"### Bộ {set_name}", "",
                  "| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for v in s["variants"]:
            r = per.get(v)
            if not r:
                continue
            b = r["by_difficulty"]
            lines.append(f"| {s['labels'][v]} | **{100 * r['ex_mean']:.1f}%** | {100 * r['ex_min']:.1f} - {100 * r['ex_max']:.1f} "
                         f"| {100 * b['easy']:.0f}% | {100 * b['medium']:.0f}% | {100 * b['hard']:.0f}% "
                         f"| {r['calls_mean']:.0f} | {r['latency_ms_mean'] / 1000:.1f}s | {r['guard_mean']:.1f} "
                         f"| {r['verdicts_mean']:.1f} | {r['reasoning_mean']:.0f} |")
        lines.append("")
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL_EINVOICE"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--start", type=int, default=1, help="bắt đầu từ lượt số mấy (chạy tiếp khi bị dừng giữa chừng)")
    ap.add_argument("--variants", nargs="+", default=VARIANTS)
    ap.add_argument("--summarize-only", action="store_true")
    args = ap.parse_args()
    if not args.summarize_only:
        for k in range(args.start, args.runs + 1):
            for set_name, path in SETS.items():
                out = os.path.join(OUT, set_name, f"r{k}")
                print(f"=== lượt {k} · bộ {set_name}", flush=True)
                cmd = [sys.executable, "evaluate.py", "--db", args.db, "--dataset", path, "--out", out,
                       "--configs", *args.variants, "--resume"]
                subprocess.run(cmd, cwd=ROOT, check=True, env=dict(os.environ, PYTHONUTF8="1"))
    s = summarize(args.runs)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    md = markdown(s)
    with open(os.path.join(OUT, "summary.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    main()
