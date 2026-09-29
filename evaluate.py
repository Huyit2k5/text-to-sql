"""Chạy bộ đánh giá, chấm execution accuracy, ghi bảng ablation và phân tích lỗi.

Ví dụ:
  python evaluate.py --configs baseline                 # Mức 1: baseline
  python evaluate.py --configs all                      # Mức 2: toàn bộ ablation
  python evaluate.py --configs all --oracle             # tự kiểm tra harness, không gọi API
  python evaluate.py --configs selfcorrect --limit 10   # chạy thử 10 câu
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from t2sql import ROOT  # import t2sql cũng nạp .env
from t2sql.db import make_backend
from t2sql.dialect import example_sql
from t2sql.evaluation import ERROR_CATEGORIES, categorize, results_match
from t2sql.llm import LLMError, ScriptedLLM, default_llm
from t2sql.pipeline import ABLATION_ORDER, CONFIGS, TextToSQL

DATASET = os.path.join(ROOT, "eval", "dataset.json")
RESULTS = os.path.join(ROOT, "results")
LABELS = {"baseline": "Baseline (Mức 1)", "docs": "+ Mô tả cột", "fewshot": "+ Few-shot",
          "linking": "+ Schema linking", "selfcorrect": "+ Tự sửa lỗi", "production": "Production (Mức 3)",
          "shapecheck": "+ Kiểm tra hình dạng", "consistency": "+ Self-consistency", "robust": "+ Hình dạng + Self-consistency"}


def oracle_llm(items):
    """LLM giả: trả SQL chuẩn kèm markdown và lời giải thích thừa, để kiểm tra khâu tách SQL + chấm điểm."""
    by_q = {it["question"]: it for it in items}

    def fn(system, messages):
        m = re.findall(r"Câu hỏi: (.*?)\nSQL:", messages[0]["content"])
        it = by_q.get(m[-1].strip()) if m else None
        if not it or not it.get("sql"):
            return "CANNOT_ANSWER: Dữ liệu không có thông tin này."
        return f"Đây là câu truy vấn:\n```sql\n{it['sql']};\n```\nCâu này tính theo yêu cầu."
    return ScriptedLLM(fn)


def evaluate_config(name, items, llm, gold, workers, db_url=None, partial_path=None, resume=False):
    """Chạy một cấu hình. Mỗi câu xong được ghi ngay vào partial_path (JSONL), nên với model chậm
    có thể dừng giữa chừng rồi chạy lại với --resume: câu đã có kết quả (không lỗi LLM) được giữ nguyên."""
    pipe = TextToSQL(llm, CONFIGS[name], db=db_url)
    t0 = time.perf_counter()
    done = {}
    if resume and partial_path and os.path.exists(partial_path):
        with open(partial_path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("kind") != "error":
                    done[r["item_id"]] = r
        print(f"   --resume: giữ {len(done)} câu đã chạy, còn {len(items) - len(done)} câu", flush=True)
    todo = [it for it in items if it["id"] not in done]
    if partial_path:
        with open(partial_path, "w", encoding="utf-8") as f:   # ghi lại phần giữ, bỏ các câu lỗi LLM
            for r in done.values():
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    def run(it):
        ans = pipe.ask(it["question"], exclude_example=it["question"])
        rec = ans.to_log()
        rec.update(item_id=it["id"], difficulty=it["difficulty"], gold_sql=it.get("sql"),
                   n_attempts=len(ans.attempts))
        if it.get("expect") == "cannot":
            rec["correct"] = ans.kind in ("cannot", "refused")
            rec["correct_lenient"] = rec["correct"]
        else:
            g = gold[it["id"]]
            ok = ans.kind == "result" and ans.result is not None and ans.result.ok
            rows = ans.result.rows if ok else []
            rec["gold_ncols"] = len(g.columns)
            rec["pred_ncols"] = len(ans.result.columns) if ok else None
            rec["correct"] = ok and results_match(rows, g.rows, it.get("ordered", False))
            rec["correct_lenient"] = ok and results_match(rows, g.rows, it.get("ordered", False), True)
            rec["pred_preview"] = [list(r) for r in rows[:5]]
            rec["gold_preview"] = [list(r) for r in g.rows[:5]]
        if not rec["correct"]:
            rec["error_category"] = categorize(it, rec)
        return rec

    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(run, it): it for it in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            done[rec["item_id"]] = rec
            mark = "✓" if rec["correct"] else ("LỖI LLM" if rec["kind"] == "error" else "✗")
            print(f"   [{len(done)}/{len(items)}] {rec['item_id']} {mark} {rec['latency_ms'] / 1000:.0f}s", flush=True)
            if partial_path:
                with lock, open(partial_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    records = [done[it["id"]] for it in items]
    return records, time.perf_counter() - t0


def summarize(records):
    by = defaultdict(list)
    for r in records:
        by[r["difficulty"]].append(r["correct"])
    acc = lambda xs: sum(xs) / len(xs) if xs else 0.0
    answerable = [r for r in records if r["difficulty"] != "unanswerable"]
    return {
        "n": len(records),
        "ex": acc([r["correct"] for r in answerable]),
        "ex_lenient": acc([r["correct_lenient"] for r in answerable]),
        "by_difficulty": {d: acc(v) for d, v in by.items()},
        "refusal_acc": acc(by.get("unanswerable", [])),
        "exec_errors": sum(1 for r in answerable if not r["ok"] and r["kind"] == "result"),
        "retried": sum(1 for r in records if r["n_attempts"] > 1),
        "errors": Counter(r.get("error_category") for r in records if not r["correct"]),
        "avg_latency_ms": sum(r["latency_ms"] for r in records) / max(len(records), 1),
    }


def ablation_markdown(summaries, usage):
    lines = ["| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | "
             "EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    prev = None
    for name, s in summaries.items():
        d = s["by_difficulty"]
        u = usage[name]
        delta = "" if prev is None else f"{(s['ex'] - prev) * 100:+.1f} điểm so với dòng trên"
        if s["retried"]:
            delta += ("; " if delta else "") + f"{s['retried']} câu có sửa lại"
        lines.append(
            f"| {LABELS.get(name, name)} | **{s['ex']:.1%}** | {d.get('easy', 0):.0%} | {d.get('medium', 0):.0%} | "
            f"{d.get('hard', 0):.0%} | {s['refusal_acc']:.0%} | {s['exec_errors']} | {s['ex_lenient']:.1%} | "
            f"{u['calls']} | {u['input_tokens']:,}/{u['output_tokens']:,} | {s['avg_latency_ms'] / 1000:.1f}s | {delta} |")
        prev = s["ex"]
    return "\n".join(lines)


def error_markdown(name, records, items_by_id):
    wrong = [r for r in records if not r["correct"]]
    cnt = Counter(r["error_category"] for r in wrong)
    out = [f"## Phân tích lỗi: {LABELS.get(name, name)} ({len(wrong)} câu sai / {len(records)})", "",
           "| Nhóm lỗi | Số câu | Các câu |", "|---|---|---|"]
    for cat, n in cnt.most_common():
        ids = ", ".join(r["item_id"] for r in wrong if r["error_category"] == cat)
        out.append(f"| {ERROR_CATEGORIES.get(cat, cat)} | {n} | {ids} |")
    out.append("")
    for r in sorted(wrong, key=lambda r: r["item_id"]):
        it = items_by_id[r["item_id"]]
        out += [f"### {r['item_id']} ({r['difficulty']}): {it['question']}",
                f"- Nhóm: {ERROR_CATEGORIES.get(r['error_category'])}",
                f"- Kết quả hệ thống: `{r['kind']}`" + (f", {r['message']}" if r.get("message") else "")
                + (f", lỗi: {r['error']}" if r.get("error") else ""),
                f"- SQL dự đoán: `{r['sql']}`" if r.get("sql") else "- SQL dự đoán: (không có)",
                f"- SQL chuẩn: `{it.get('sql')}`",
                f"- Kết quả dự đoán (5 dòng đầu): {r.get('pred_preview')}",
                f"- Kết quả chuẩn (5 dòng đầu): {r.get('gold_preview')}", ""]
    return "\n".join(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=["baseline"],
                    help=f"tên cấu hình ({', '.join(CONFIGS)}) hoặc 'all' = {' '.join(ABLATION_ORDER)}")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("T2SQL_WORKERS") or 4))
    ap.add_argument("--oracle", action="store_true", help="dùng LLM giả trả về SQL chuẩn (kiểm tra harness)")
    ap.add_argument("--out", default=RESULTS)
    ap.add_argument("--db", default=None, help="URL database (mặc định lấy T2SQL_DATABASE_URL; trống = SQLite)")
    ap.add_argument("--resume", action="store_true",
                    help="giữ kết quả đã có trong results/.../<config>.jsonl, chỉ chạy các câu còn thiếu hoặc bị lỗi LLM")
    args = ap.parse_args()

    names = ABLATION_ORDER if args.configs == ["all"] else args.configs
    with open(DATASET, encoding="utf-8") as f:
        items = json.load(f)
    if args.limit:
        items = items[: args.limit]
    items_by_id = {it["id"]: it for it in items}

    ex = make_backend(args.db, max_rows=100_000, timeout_s=60)
    print(f"Database: {ex.describe()}", flush=True)
    gold = {}
    for it in items:
        if it.get("sql"):
            # SQL chuẩn viết cho SQLite -> chuyển sang dialect của DB đích (ưu tiên bản viết tay sql_pg...)
            it["sql_source"], it["sql"] = it["sql"], example_sql(it, ex.dialect)
            g = ex.run(it["sql"], safe=False)
            if not g.ok:
                sys.exit(f"SQL chuẩn của {it['id']} lỗi trên {ex.display_name}: {g.error}\n{it['sql']}")
            gold[it["id"]] = g

    out_dir = args.out
    if ex.dialect != "sqlite":
        out_dir = os.path.join(out_dir, ex.dialect)
    if args.oracle:
        out_dir = os.path.join(out_dir, "oracle")
    os.makedirs(out_dir, exist_ok=True)
    summaries, usage, all_records = {}, {}, {}
    for name in names:
        llm = oracle_llm(items) if args.oracle else default_llm()
        print(f"== {name}: {len(items)} câu ...", flush=True)
        try:
            records, secs = evaluate_config(name, items, llm, gold, args.workers, args.db,
                                            os.path.join(out_dir, f"{name}.jsonl"), args.resume)
        except LLMError as e:
            sys.exit(f"Lỗi LLM: {e}")
        fatal = [r for r in records if r["kind"] == "error"]
        if fatal and len(fatal) == len(records):
            sys.exit(f"Mọi câu đều lỗi LLM, ví dụ: {fatal[0]['message']}")
        s = summarize(records)
        summaries[name], all_records[name] = s, records
        usage[name] = vars(llm.usage)
        with open(os.path.join(out_dir, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        print(f"   EX = {s['ex']:.1%}  (dễ {s['by_difficulty'].get('easy', 0):.0%}, "
              f"TB {s['by_difficulty'].get('medium', 0):.0%}, khó {s['by_difficulty'].get('hard', 0):.0%}), "
              f"từ chối đúng {s['refusal_acc']:.0%}, {secs:.0f}s, {llm.usage.calls} lời gọi LLM"
              + (f", {len(fatal)} câu lỗi LLM (chạy lại với --resume)" if fatal else ""))

    table = ablation_markdown(summaries, usage)
    report = ["# Kết quả đánh giá" + (" (ORACLE, kiểm tra harness)" if args.oracle else ""), "",
              f"- Bộ đánh giá: {len(items)} câu ({sum(1 for i in items if i.get('sql'))} có đáp án, "
              f"{sum(1 for i in items if not i.get('sql'))} câu phải từ chối)",
              f"- Model: {getattr(llm, 'model', 'oracle')}, effort {getattr(llm, 'effort', None) or 'mặc định'}, reasoning {getattr(llm, 'reasoning', 'mặc định')}",
              f"- Database: {ex.describe()}",
              "- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa "
              "(trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.", "", table, ""]
    for name in (names[0], names[-1]) if len(names) > 1 else names:
        report.append(error_markdown(name, all_records[name], items_by_id))
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"model": getattr(llm, "model", "oracle"), "reasoning": getattr(llm, "reasoning", None),
                   "database": ex.describe(), "n_items": len(items),
                   "configs": {n: {**summaries[n], "errors": dict(summaries[n]["errors"]), "usage": usage[n]}
                               for n in summaries}}, f, ensure_ascii=False, indent=2, default=str)
    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("\n" + table + f"\n\nĐã ghi báo cáo: {path}")


if __name__ == "__main__":
    main()
