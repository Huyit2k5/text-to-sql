"""Dựng báo cáo HTML từ kết quả evaluate.py + profile_queries.py.

  python build_report.py                     # -> results/postgres/bao_cao.html
  python build_report.py --run results/postgres --prev results/postgres_run1

Đọc:  <run>/<config>.jsonl, <run>/report.md (hoặc summary.json), <run>/query_metrics.jsonl,
      và (tùy chọn) lần chạy trước <prev>/ để so sánh.
Mẫu giao diện: report/template.html (dữ liệu được nhúng vào chỗ /*__DATA__*/).
"""
import argparse
import json
import os
import re
import statistics
import sys
import time

from t2sql import ROOT
from t2sql.evaluation import ERROR_CATEGORIES
from t2sql.pipeline import ABLATION_ORDER

LABELS = {"baseline": "Baseline", "docs": "+ Mô tả cột", "fewshot": "+ Few-shot",
          "linking": "+ Schema linking", "selfcorrect": "+ Tự sửa lỗi",
          "shapecheck": "+ Kiểm tra hình dạng", "consistency": "+ Self-consistency", "robust": "+ Hình dạng + Self-consistency"}


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def usage_from_report(run_dir):
    """Token / số lời gọi LLM theo cấu hình. Ưu tiên summary.json; lần chạy cũ thì đọc bảng trong report.md."""
    path = os.path.join(run_dir, "summary.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        return {c: v["usage"] for c, v in s["configs"].items()}
    out = {}
    rp = os.path.join(run_dir, "report.md")
    if not os.path.exists(rp):
        return out
    by_label = {"Baseline (Mức 1)": "baseline", "+ Mô tả cột": "docs", "+ Few-shot": "fewshot",
                "+ Schema linking": "linking", "+ Tự sửa lỗi": "selfcorrect"}
    for line in open(rp, encoding="utf-8"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 10 and cells[0] in by_label:
            tin, tout = (int(x.replace(",", "")) for x in cells[9].split("/"))
            out[by_label[cells[0]]] = {"calls": int(cells[8]), "input_tokens": tin, "output_tokens": tout}
    return out


def summarize_run(run_dir):
    res = {}
    usage = usage_from_report(run_dir)
    for cfg in ABLATION_ORDER:
        recs = load_jsonl(os.path.join(run_dir, f"{cfg}.jsonl"))
        if not recs:
            continue
        ans = [r for r in recs if r["difficulty"] != "unanswerable"]
        acc = lambda rs: round(100 * sum(r["correct"] for r in rs) / len(rs), 1) if rs else None
        by_diff = {d: acc([r for r in recs if r["difficulty"] == d]) for d in ("easy", "medium", "hard", "unanswerable")}
        llm = [sum(a.get("llm_ms", 0) for a in r.get("attempts", [])) for r in recs]
        db = [sum(a.get("db_ms", 0) for a in r.get("attempts", [])) for r in recs]
        errs = {}
        for r in recs:
            if not r["correct"]:
                errs[r.get("error_category") or "other"] = errs.get(r.get("error_category") or "other", 0) + 1
        res[cfg] = {
            "label": LABELS[cfg], "n": len(recs), "ex": acc(ans), "by_difficulty": by_diff,
            "wrong": len(recs) - sum(r["correct"] for r in recs),
            "exec_errors": sum(1 for r in ans if r["kind"] == "result" and not r["ok"]),
            "llm_errors": sum(1 for r in recs if r["kind"] == "error"),
            "retried": sum(1 for r in recs if r["n_attempts"] > 1),
            "latency_avg_ms": round(statistics.mean(r["latency_ms"] for r in recs), 1),
            "latency_p95_ms": round(sorted(r["latency_ms"] for r in recs)[int(0.95 * (len(recs) - 1))], 1),
            "llm_avg_ms": round(statistics.mean(llm), 1) if any(llm) else None,
            "db_avg_ms": round(statistics.mean(db), 2) if any(db) else None,
            "errors": {ERROR_CATEGORIES.get(k, k): v for k, v in sorted(errs.items(), key=lambda x: -x[1])},
            "usage": usage.get(cfg),
        }
    return res


ROBUST_ORDER = ["selfcorrect", "shapecheck", "consistency", "robust"]


def summarize_robust(run_dirs, offline_path):
    """So sánh kiểm tra hình dạng / self-consistency qua nhiều lượt chạy (results/robust_r*/postgres)."""
    runs = [d for d in run_dirs if os.path.isdir(d)]
    if not runs:
        return None
    per_cfg = {}
    for cfg in ROBUST_ORDER:
        recs_by_run = [load_jsonl(os.path.join(d, f"{cfg}.jsonl")) for d in runs]
        recs_by_run = [r for r in recs_by_run if r]
        if not recs_by_run:
            continue
        exs, lat_p50, lat_p95, calls, flips = [], [], [], [], None
        flagged = fixed = kept = 0
        agree = {}
        for recs in recs_by_run:
            ans = [r for r in recs if r["difficulty"] != "unanswerable"]
            exs.append(round(100 * sum(r["correct"] for r in ans) / len(ans), 3))
            lats = sorted(r["latency_ms"] for r in recs)
            lat_p50.append(lats[(len(lats) - 1) // 2])
            lat_p95.append(lats[int(0.95 * (len(lats) - 1))])
            for r in recs:
                att = r.get("attempts") or []
                if any(a.get("issues") for a in att):
                    flagged += 1
                    if att and not att[-1].get("issues"):
                        fixed += 1
                    else:
                        kept += 1
                if r.get("agreement"):
                    a = agree.setdefault(r["agreement"], [0, 0])
                    a[0] += 1
                    a[1] += int(r["correct"])
        calls = [usage_from_report(d).get(cfg, {}).get("calls") for d in runs]
        tokens = [usage_from_report(d).get(cfg, {}).get("input_tokens") for d in runs]
        if len(recs_by_run) >= 2:
            a = {r["item_id"]: r["correct"] for r in recs_by_run[0]}
            b = {r["item_id"]: r["correct"] for r in recs_by_run[1]}
            flips = sorted(k for k in a if k in b and a[k] != b[k])
        wrong = sorted({r["item_id"] for recs in recs_by_run for r in recs if not r["correct"]})
        per_cfg[cfg] = {"label": LABELS[cfg], "ex": exs, "calls": calls, "input_tokens": tokens,
                        "lat_p50": lat_p50, "lat_p95": lat_p95, "flips": flips, "wrong": wrong,
                        "shape_flagged": flagged, "shape_fixed": fixed, "shape_kept": kept,
                        "agreement": {k: {"n": v[0], "correct": v[1]} for k, v in
                                      sorted(agree.items(), key=lambda kv: (-int(kv[0].split("/")[0]) / int(kv[0].split("/")[1]),
                                                                            -int(kv[0].split("/")[1])))}}
    offline = None
    if offline_path and os.path.exists(offline_path):
        with open(offline_path, encoding="utf-8") as f:
            offline = json.load(f)
    return {"n_runs": len(runs), "configs": per_cfg, "offline": offline}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=os.path.join(ROOT, "results", "postgres"))
    ap.add_argument("--prev", default=os.path.join(ROOT, "results", "postgres_run1"))
    ap.add_argument("--template", default=os.path.join(ROOT, "report", "template.html"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--host-label", default="db", help="tên host hiển thị (container Postgres)")
    ap.add_argument("--robust", nargs="*", default=[os.path.join(ROOT, "results", f"robust_r{i}", "postgres") for i in (1, 2)],
                    help="các lượt chạy cấu hình kiểm tra hình dạng / self-consistency")
    args = ap.parse_args()

    metrics = load_jsonl(os.path.join(args.run, "query_metrics.jsonl"))
    if not metrics:
        sys.exit("Chưa có query_metrics.jsonl: chạy python profile_queries.py trước.")
    summary_path = os.path.join(args.run, "summary.json")
    meta = {}
    if os.path.exists(summary_path):
        with open(summary_path, encoding="utf-8") as f:
            s = json.load(f)
        meta = {k: s.get(k) for k in ("model", "reasoning", "database", "n_items")}
    # Lượt chạy cũ chưa có summary.json: lấy từ cấu hình hiện tại (.env)
    meta.setdefault("model", os.environ.get("T2SQL_MODEL"))
    if not meta.get("reasoning"):
        r = (os.environ.get("T2SQL_REASONING") or "").lower()
        meta["reasoning"] = "none" if r in ("off", "0", "false", "none", "no") else (r or None)
    meta.setdefault("n_items", None)

    # Giờ trong kết quả là giờ của container (thường UTC). Nếu lệch so với giờ ghi file trên máy này thì đổi sang giờ máy.
    shift = 0
    times = [m["time"] for m in metrics if m.get("time")]
    if times:
        import datetime as dt
        last = max(dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S") for t in times)
        mtime = dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(args.run, "selfcorrect.jsonl")))
        shift = round((mtime - last).total_seconds() / 3600)
        if abs(shift) >= 1:
            for m in metrics:
                if m.get("time"):
                    m["time"] = (dt.datetime.strptime(m["time"], "%Y-%m-%d %H:%M:%S") + dt.timedelta(hours=shift)).strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(ROOT, "eval", "dataset.json"), encoding="utf-8") as f:
        dataset = json.load(f)

    queries = []
    for m in metrics:
        mm, gm = m.get("metrics") or {}, m.get("gold_metrics") or {}
        queries.append({
            "config": m["config"], "id": m["item_id"], "difficulty": m["difficulty"], "time": m["time"],
            "question": m["question"], "sql": m["sql"], "host": args.host_label, "status": m["status"],
            "correct": m["correct"], "kind": m["kind"], "message": m.get("message"),
            "error": mm.get("error") or m.get("eval_error"), "error_category": ERROR_CATEGORIES.get(m.get("error_category"), m.get("error_category")),
            "attempts": m["n_attempts"], "latency_ms": m["latency_ms"], "llm_ms": m["llm_ms"],
            "duration_ms": mm.get("duration_ms"), "exec_ms": mm.get("exec_ms"), "read_rows": mm.get("read_rows"),
            "read_bytes": mm.get("read_bytes"), "result_rows": mm.get("result_rows"),
            "memory_bytes": mm.get("memory_bytes"), "cpu_ms": mm.get("cpu_ms"), "cpu_cores": mm.get("cpu_cores"),
            "score": mm.get("score"),
            "gold": {k: gm.get(k) for k in ("duration_ms", "exec_ms", "read_rows", "memory_bytes", "cpu_ms", "result_rows")},
        })
    from t2sql.dialect import example_sql
    gold_sql = {it["id"]: example_sql(it, "postgres") for it in dataset if it.get("sql")}

    data = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "meta": meta,
        "host": (metrics[0]["host"].replace("127.0.0.1", f"container {args.host_label}") if metrics else ""),
        "runs": {"run2": summarize_run(args.run), "run1": summarize_run(args.prev) if os.path.isdir(args.prev) else {}},
        "queries": queries,
        "gold_sql": gold_sql,
        "labels": LABELS,
        "robust": summarize_robust(args.robust, os.path.join(args.run, "shape_checks_offline.json")),
    }
    with open(args.template, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload)
    out = args.out or os.path.join(args.run, "bao_cao.html")
    # Bản mở trực tiếp bằng trình duyệt: thêm khung tài liệu đầy đủ (bản đăng Artifact thì nền tảng tự bọc).
    split = html.index('<div class="wrap">')   # title/meta/font/CSS của mẫu -> <head>, phần còn lại -> <body>
    full = ('<!doctype html>\n<html lang="vi">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n'
            + html[:split] + "</head>\n<body>\n" + html[split:] + "\n</body>\n</html>\n")
    with open(out, "w", encoding="utf-8") as f:
        f.write(full)
    with open(out.replace(".html", ".fragment.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Đã ghi {out} ({len(full) / 1024:.0f} KB, {len(queries)} truy vấn)")


if __name__ == "__main__":
    main()
