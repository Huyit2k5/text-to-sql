"""Dựng báo cáo HTML riêng cho Text-to-SQL trên ClickHouse, bộ dữ liệu hóa đơn điện tử (einvoice).

  python build_report_clickhouse.py
  -> results/clickhouse_einvoice/bao_cao_clickhouse.html và bao_cao_clickhouse_einvoice.html (thư mục gốc)

Đọc: results/clickhouse_einvoice_run1/ (lượt 1), results/clickhouse_einvoice/ (lượt 2 + query_metrics.jsonl
của profile_clickhouse.py), datasets/einvoice/eval.json; thông tin bảng lấy trực tiếp từ system.tables / system.parts.
"""
import argparse
import json
import os
import re
import shutil
import statistics
import sys
from datetime import datetime
from urllib.parse import urlsplit

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT, datasets
from t2sql.pipeline import CONFIGS

CONFIG_ORDER = ["baseline", "docs", "fewshot", "linking", "selfcorrect", "shapecheck"]
LABELS = {"baseline": "Baseline", "docs": "+ Mô tả cột, quy tắc", "fewshot": "+ Few-shot",
          "linking": "+ Schema linking", "selfcorrect": "+ Tự sửa lỗi", "shapecheck": "+ Kiểm tra hình dạng"}
EXPLAIN = {
    "baseline": "Chỉ tên bảng, cột, kiểu, khóa. Không có mô tả hay quy tắc nghiệp vụ.",
    "docs": "Thêm mô tả bảng/cột, giá trị mẫu và 16 quy tắc nghiệp vụ (FINAL, hóa đơn hợp lệ, tỷ giá, múi giờ...).",
    "fewshot": "Thêm 4 ví dụ câu hỏi - SQL gần nhất lấy từ pool 26 câu (không trùng bộ đánh giá).",
    "linking": "Chỉ đưa vào prompt các bảng liên quan (TF-IDF + khái niệm nghiệp vụ + khóa ngoại khai báo).",
    "selfcorrect": "SQL lỗi hoặc ra rỗng thì gửi lỗi lại cho model sửa (tối đa 2 lần).",
    "shapecheck": "Thêm kiểm tra hình dạng kết quả R0-R7 (ví dụ SQL không có FROM, top N trả thừa dòng).",
}
# Nhận xét viết tay cho các câu còn sai ở cấu hình cuối
NOTES = {
    "h04": "Dùng bảng tổng hợp ngày nhưng nhóm theo ngày thay vì tháng (181 dòng thay vì 6). Kiểm tra hình dạng bắt được (R3) nhưng model sửa lại vẫn sai.",
    "h10": "Lồng hàm gộp min() bên trong countIf(); ClickHouse báo lỗi, vòng tự sửa không gỡ được.",
    "h12": "Câu hỏi cần một hóa đơn lớn nhất, model lại cộng tổng giá trị theo doanh nghiệp.",
    "h16": "Model tự đoán mã tỉnh Đà Nẵng là '78' (đúng là '48') thay vì JOIN bảng provinces theo tên.",
    "h17": "Ước lượng phần thuế được giảm bằng 25% tổng thuế cả tháng, thay vì chỉ tính 2% trên các dòng 8%.",
    "h15": "Đúng số liệu nhưng thêm cột doanh thu (EX nới lỏng tính đúng).",
    "h11": "Lượt 1: câu hỏi chưa nói rõ tính hóa đơn ở trạng thái nào, model chỉ tính hóa đơn hợp lệ. Câu hỏi đã được làm rõ (mọi trạng thái) trước lượt 2 và model trả lời đúng.",
    "m11": "Lượt 1 có lần trả SELECT count() không có FROM: ClickHouse vẫn chạy (đọc system.one) và trả 1. Đã thêm quy tắc R0.",
}
MONEY = re.compile(r"\b(total_before_tax|total_amount|total_vat|total_discount|line_amount|vat_amount|discount_amount)\b")
LOGS = re.compile(r"\b(tax_messages|api_requests)\b")
TIME_ON_LOG = re.compile(r"\b(sent_at|response_at|ts)\b")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def needs(sql):
    """Các bẫy mà một câu SQL (chuẩn) cần xử lý."""
    s = sql or ""
    return {
        "final": bool(re.search(r"\binvoices\b", s)) and "FINAL" in s.upper(),
        "timezone": bool(LOGS.search(s) and TIME_ON_LOG.search(s)),
        "fx": bool(MONEY.search(s)),
    }


def trap_hits(pred, need):
    p = pred or ""
    return {
        "final": need["final"] and (bool(re.search(r"\binvoices\b", p)) and "FINAL" not in p.upper()),
        "timezone": need["timezone"] and bool(LOGS.search(p)) and "toTimeZone" not in p,
        "fx": need["fx"] and bool(MONEY.search(p)) and "exchange_rate" not in p and "revenue_vnd" not in p
              and "vat_vnd" not in p,
    }


def run_data(folder, items):
    out = {}
    summary = {}
    if os.path.exists(os.path.join(folder, "summary.json")):
        with open(os.path.join(folder, "summary.json"), encoding="utf-8") as f:
            summary = json.load(f)
    for cfg in CONFIG_ORDER:
        recs = read_jsonl(os.path.join(folder, f"{cfg}.jsonl"))
        if not recs:
            continue
        s = summary.get("configs", {}).get(cfg, {})
        u = s.get("usage", {})
        traps = {k: [0, 0] for k in ("final", "timezone", "fx")}
        no_from = 0
        per_item = {}
        for r in recs:
            it = items.get(r["item_id"], {})
            per_item[r["item_id"]] = {"ok": bool(r["correct"]), "lenient": bool(r.get("correct_lenient")),
                                      "kind": r["kind"], "cat": r.get("error_category")}
            if not it.get("sql"):
                continue
            need = needs(it["sql"])
            hits = trap_hits(r.get("sql"), need) if r.get("sql") else {k: False for k in need}
            for k in traps:
                if need[k]:
                    traps[k][1] += 1
                    traps[k][0] += int(hits[k])
            for a in r.get("attempts", []):
                sql = a.get("sql") or ""
                if sql and not re.search(r"\bFROM\b", sql, re.I):
                    no_from += 1
        out[cfg] = {
            "ex": s.get("ex"), "ex_lenient": s.get("ex_lenient"), "by_difficulty": s.get("by_difficulty", {}),
            "refusal": s.get("refusal_acc"), "exec_errors": s.get("exec_errors"), "retried": s.get("retried"),
            "calls": u.get("calls"), "tok_in": u.get("input_tokens"), "tok_out": u.get("output_tokens"),
            "latency_ms": s.get("avg_latency_ms"), "traps": traps, "no_from": no_from, "items": per_item,
        }
    return out, summary


def status_of(r):
    m, g = r.get("metrics"), r.get("gold_metrics")
    if not r.get("sql"):
        return "Normal" if r["correct"] else "Sai kết quả"
    if not m or not m.get("ok"):
        return "Lỗi"
    if not r["correct"]:
        return "Sai kết quả"
    if m.get("score") and m["score"] >= 2 and m["duration_ms"] > 50:
        return "Nặng hơn chuẩn"
    if m["duration_ms"] > 1000:
        return "Chậm (ngang chuẩn)"
    return "Normal"


def table_info(url):
    import clickhouse_connect
    u = urlsplit(url)
    c = clickhouse_connect.get_client(host=u.hostname, port=u.port or 8123, secure=u.scheme == "clickhouses",
                                      username=os.environ.get("CLICKHOUSE_USER") or "default",
                                      password=os.environ.get("CLICKHOUSE_PASSWORD", ""))
    db = (u.path or "/").strip("/")
    rows = c.query("""
        SELECT t.name, t.engine, t.comment, t.partition_key, t.sorting_key,
               sum(p.rows), sum(p.bytes_on_disk), sum(p.data_uncompressed_bytes), count(p.name)
        FROM system.tables AS t LEFT JOIN (SELECT * FROM system.parts WHERE active) AS p
             ON p.database = t.database AND p.table = t.name
        WHERE t.database = {db:String} GROUP BY t.name, t.engine, t.comment, t.partition_key, t.sorting_key
        ORDER BY sum(p.rows) DESC""", parameters={"db": db}).result_rows
    final_rows = c.query(f"SELECT count() FROM `{db}`.invoices FINAL").result_rows[0][0]
    return c.server_version, final_rows, [
        {"name": r[0], "engine": r[1], "comment": r[2], "partition": r[3], "order_by": r[4], "rows": int(r[5] or 0),
         "bytes": int(r[6] or 0), "raw_bytes": int(r[7] or 0), "parts": int(r[8] or 0)} for r in rows]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run1", default=os.path.join(ROOT, "results", "clickhouse_einvoice_run1"))
    ap.add_argument("--run2", default=os.path.join(ROOT, "results", "clickhouse_einvoice"))
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL_EINVOICE"))
    ap.add_argument("--template", default=os.path.join(ROOT, "report", "template_clickhouse.html"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    ds = datasets.for_database("einvoice")
    with open(ds.eval_path, encoding="utf-8") as f:
        items = {it["id"]: it for it in json.load(f)}
    run1, _ = run_data(args.run1, items)
    run2, summary2 = run_data(args.run2, items)
    last = CONFIG_ORDER[-1]

    # Câu sai ở cấu hình cuối, lượt 2 (+ lượt 1 để so)
    recs2 = {r["item_id"]: r for r in read_jsonl(os.path.join(args.run2, f"{last}.jsonl"))}
    recs1 = {r["item_id"]: r for r in read_jsonl(os.path.join(args.run1, f"{last}.jsonl"))}
    failures = []
    for iid in sorted(set(k for k, r in recs2.items() if not r["correct"]) | set(k for k, r in recs1.items() if not r["correct"])):
        r2, r1, it = recs2.get(iid, {}), recs1.get(iid, {}), items[iid]
        failures.append({"id": iid, "difficulty": it["difficulty"], "question": it["question"],
                         "wrong_run1": not r1.get("correct", True), "wrong_run2": not r2.get("correct", True),
                         "lenient2": bool(r2.get("correct_lenient")), "category": r2.get("error_category") or r1.get("error_category"),
                         "pred_sql": r2.get("sql") if not r2.get("correct", True) else r1.get("sql"),
                         "error": r2.get("error") if not r2.get("correct", True) else r1.get("error"),
                         "gold_sql": it["sql"], "note": NOTES.get(iid, ""),
                         "pred_preview": (r2 if not r2.get("correct", True) else r1).get("pred_preview"),
                         "gold_preview": (r2 if not r2.get("correct", True) else r1).get("gold_preview")})

    # Hiệu năng (lượt 2)
    perf = []
    for r in read_jsonl(os.path.join(args.run2, "query_metrics.jsonl")):
        m, g = r.get("metrics") or {}, r.get("gold_metrics") or {}
        perf.append({"config": r["config"], "id": r["item_id"], "difficulty": r["difficulty"], "question": r["question"],
                     "time": r.get("time"), "sql": r.get("sql"), "gold_sql": items[r["item_id"]].get("sql"),
                     "correct": r["correct"], "status": status_of(r),
                     "m": {k: m.get(k) for k in ("duration_ms", "cpu_ms", "cpu_cores", "read_rows", "read_bytes",
                                                 "memory_bytes", "result_rows", "score", "error")} if m else None,
                     "g": {k: g.get(k) for k in ("duration_ms", "cpu_ms", "read_rows", "memory_bytes", "result_rows")} if g else None,
                     "llm_ms": r.get("llm_ms"), "latency_ms": r.get("latency_ms")})
    gold_perf = {}
    for p in perf:
        if p["g"] and p["id"] not in gold_perf:
            gold_perf[p["id"]] = p["g"]
    gd = [g["duration_ms"] for g in gold_perf.values() if g.get("duration_ms") is not None]

    server, final_rows, tables = table_info(args.db) if args.db else ("?", None, [])
    counts = {"easy": 0, "medium": 0, "hard": 0, "unanswerable": 0}
    for it in items.values():
        counts[it["difficulty"]] += 1
    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": summary2.get("model"), "reasoning": summary2.get("reasoning"),
        "database": summary2.get("database"), "server": server, "final_rows": final_rows,
        "n_items": len(items), "counts": counts, "configs": CONFIG_ORDER, "labels": LABELS, "explain": EXPLAIN,
        "runs": {"Lượt 1": run1, "Lượt 2": run2}, "failures": failures, "perf": perf, "tables": tables,
        "gold": {"n": len(gd), "median_ms": statistics.median(gd) if gd else None, "max_ms": max(gd) if gd else None,
                 "max_rows": max((g.get("read_rows") or 0) for g in gold_perf.values()) if gold_perf else None},
        "items": {iid: {"q": it["question"], "d": it["difficulty"]} for iid, it in items.items()},
        "fewshot_n": len(json.load(open(ds.fewshot_path, encoding="utf-8"))),
        "rules_n": len(ds.docs.get("business_rules", [])),
        "linking_top_k": CONFIGS["linking"].linking_top_k,
    }
    with open(args.template, encoding="utf-8") as f:
        html = f.read()
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", blob)
    out = args.out or os.path.join(args.run2, "bao_cao_clickhouse.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    shutil.copyfile(out, os.path.join(ROOT, "bao_cao_clickhouse_einvoice.html"))
    print(f"Đã ghi {out} ({len(html) // 1024} KiB) và bao_cao_clickhouse_einvoice.html")


if __name__ == "__main__":
    main()
