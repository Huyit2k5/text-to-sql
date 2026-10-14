"""Thí nghiệm: câu mơ hồ / không trả lời được, có và không có bước phân loại trước khi sinh SQL.

  python experiments/ambiguity/run_ambiguity.py --configs production production_classify --runs 2

Mỗi câu trong datasets/hddt/eval_ambiguous.json có "expect": clarify | cannot | answer.
  clarify -> đúng khi hệ thống hỏi lại; cannot -> đúng khi từ chối / nói không có dữ liệu;
  answer  -> đúng khi trả lời được (SQL chạy ra kết quả, kể cả rỗng).
Chỉ đọc trên ClickHouse. Kết quả ghi vào results/hddt_ambiguity/ (không đưa lên git).
"""
import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from t2sql import datasets  # noqa: E402
from t2sql.llm import default_llm  # noqa: E402
from t2sql.pipeline import CONFIGS, TextToSQL  # noqa: E402


def load_env_url():
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8-sig"):
        if line.startswith("T2SQL_DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    sys.exit("Thiếu T2SQL_DATABASE_URL trong .env")


def action_of(ans):
    if ans.kind == "clarify":
        return "clarify"
    if ans.kind in ("cannot", "refused"):
        return "cannot"
    if ans.kind == "result" and ans.result is not None and ans.result.ok:
        return "answer"
    return "error"


def run_config(name, items, url, workers):
    llm = default_llm()
    pipe = TextToSQL(llm, CONFIGS[name], db=url)

    def one(it):
        ans = pipe.ask(it["question"])
        act = action_of(ans)
        return {"id": it["id"], "expect": it["expect"], "question": it["question"], "action": act,
                "correct": act == it["expect"], "kind": ans.kind, "message": ans.message, "sql": ans.sql,
                "latency_ms": ans.latency_ms, "attempts": len(ans.attempts)}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        recs = list(ex.map(one, items))
    return recs, time.perf_counter() - t0, vars(llm.usage)


def report(name, recs):
    out = {}
    for cls in ("clarify", "cannot", "answer"):
        rs = [r for r in recs if r["expect"] == cls]
        out[cls] = (sum(r["correct"] for r in rs), len(rs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=["production", "production_classify"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "hddt_ambiguity"))
    args = ap.parse_args()
    url = load_env_url()
    ds = datasets.for_database("hddt")
    with open(os.path.join(os.path.dirname(ds.eval_path), "eval_ambiguous.json"), encoding="utf-8") as f:
        items = json.load(f)
    os.makedirs(args.out, exist_ok=True)
    summary = {}
    for run in range(1, args.runs + 1):
        for name in args.configs:                       # tuần tự: không chạy thí nghiệm song song trên server chung
            recs, secs, usage = run_config(name, items, url, args.workers)
            with open(os.path.join(args.out, f"{name}_run{run}.jsonl"), "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            rep = report(name, recs)
            lat = statistics.median(r["latency_ms"] for r in recs) / 1000
            summary[(name, run)] = rep
            print(f"[run {run}] {name:20s} hỏi lại đúng {rep['clarify'][0]}/{rep['clarify'][1]} | "
                  f"từ chối đúng {rep['cannot'][0]}/{rep['cannot'][1]} | trả lời đúng (đối chứng) {rep['answer'][0]}/{rep['answer'][1]} "
                  f"| trung vị {lat:.1f}s | {usage['calls']} lời gọi | {secs:.0f}s", flush=True)
            for r in recs:
                if not r["correct"]:
                    print(f"      ✗ {r['id']} cần {r['expect']} -> {r['action']}: {r['question'][:60]}", flush=True)


if __name__ == "__main__":
    main()
