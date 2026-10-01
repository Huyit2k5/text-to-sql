"""Đo chi phí thực thi từng câu SQL trên ClickHouse, lấy số liệu từ system.query_log
(cùng nguồn với dashboard "Query Latency & Memory" của ClickHouse).

Mỗi câu SQL (của model và SQL chuẩn cùng câu hỏi) chạy 1 lần khởi động + N lần đo, mỗi lần gắn một log_comment
riêng; sau đó đọc system.query_log (type = 'QueryFinish') và lấy trung vị:
  - Duration   : event_time_microseconds - query_start_time_microseconds (phía server, micro giây)
  - CPU time   : ProfileEvents UserTimeMicroseconds + SystemTimeMicroseconds (mọi thread của truy vấn)
  - CPU core   : CPU time / Duration
  - Read rows / Read bytes / Memory (memory_usage đỉnh) / Result (result_rows)
  - Score      : Duration của SQL model / Duration của SQL chuẩn
Truy vấn chạy bằng user chỉ đọc t2sql_admin; đọc query_log bằng user quản trị (CLICKHOUSE_USER / CLICKHOUSE_PASSWORD).

  python profile_clickhouse.py              # đọc results/clickhouse_<bộ dữ liệu>/*.jsonl, ghi query_metrics.jsonl
  python profile_clickhouse.py --db "$T2SQL_DATABASE_URL_EINVOICE"   # chọn database khác
"""
import argparse
import json
import os
import statistics
import sys
import uuid

import clickhouse_connect

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT, datasets
from t2sql.db.clickhouse import ClickHouseBackend
from t2sql.dialect import example_sql
from t2sql.safety import POLICIES

SLOW_SCORE = 2.0        # chậm hơn SQL chuẩn quá 2 lần ...
SLOW_MIN_MS = 20.0      # ... và mất trên 20 ms thì đánh dấu "Chậm"
SLOW_ABS_MS = 1000.0    # hoặc trên 1 giây


def status_of(rec, m, gold_m):
    if not m or not m["ok"]:
        return "Lỗi"
    if not rec["correct"]:
        return "Sai kết quả"
    score = m.get("score")
    if m["duration_ms"] > SLOW_ABS_MS or (score and score > SLOW_SCORE and m["exec_ms"] > SLOW_MIN_MS):
        return "Chậm"
    return "Normal"


CONFIG_ORDER = ["baseline", "docs", "fewshot", "linking", "selfcorrect", "shapecheck", "consistency", "robust"]


class Profiler:
    def __init__(self, url, repeat=3):
        self.backend = ClickHouseBackend(url)
        self.client = self.backend._client(POLICIES["admin"])
        self.admin = clickhouse_connect.get_client(
            host=self.backend.host, port=self.backend.port, secure=self.backend.secure,
            username=os.environ.get("CLICKHOUSE_USER") or "default", password=os.environ.get("CLICKHOUSE_PASSWORD", ""))
        self.server = self.client.server_version
        self.repeat = repeat
        self.run_id = uuid.uuid4().hex[:8]
        self.pending = {}       # sql -> (tags, result_rows) | error
        self.cache = {}

    def submit(self, sql_text):
        """Chạy câu SQL (khởi động + N lần), ghi nhớ tag để đọc query_log sau."""
        if sql_text in self.pending:
            return
        tags = []
        try:
            for i in range(self.repeat + 1):
                tag = f"t2sql-prof:{self.run_id}:{len(self.pending)}:{i}"
                res = self.client.query(sql_text, settings={"log_comment": tag, "max_execution_time": 60})
                if i:                   # lần 0 là khởi động
                    tags.append(tag)
            self.pending[sql_text] = (tags, len(res.result_rows))
        except Exception as e:
            from t2sql.db.clickhouse import _error_parts
            self.pending[sql_text] = _error_parts(e)[1]

    def collect(self):
        self.admin.command("SYSTEM FLUSH LOGS")
        rows = self.admin.query("""
            SELECT log_comment,
                   dateDiff('microsecond', query_start_time_microseconds, event_time_microseconds) AS dur_us,
                   ProfileEvents['UserTimeMicroseconds'] + ProfileEvents['SystemTimeMicroseconds'] AS cpu_us,
                   read_rows, read_bytes, memory_usage, result_rows
            FROM system.query_log
            WHERE type = 'QueryFinish' AND log_comment LIKE {p:String}""",
                                parameters={"p": f"t2sql-prof:{self.run_id}:%"}).result_rows
        by_tag = {r[0]: r[1:] for r in rows}
        for sql_text, v in self.pending.items():
            if isinstance(v, str):
                self.cache[sql_text] = {"ok": False, "error": v}
                continue
            tags, n_result = v
            got = [by_tag[t] for t in tags if t in by_tag]
            if not got:
                self.cache[sql_text] = {"ok": False, "error": "không thấy trong system.query_log"}
                continue
            med = lambda k: statistics.median(g[k] for g in got)
            dur, cpu = med(0) / 1000, med(1) / 1000
            self.cache[sql_text] = {
                "ok": True, "error": None, "duration_ms": round(dur, 3), "exec_ms": round(dur, 3),
                "cpu_ms": round(cpu, 3), "cpu_cores": round(cpu / dur, 3) if dur else 0,
                "read_rows": int(med(2)), "read_bytes": int(med(3)), "memory_bytes": int(med(4)),
                "disk_bytes": 0, "result_rows": n_result, "nodes": []}

    def get(self, sql_text):
        return self.cache.get(sql_text)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=None, help="mặc định results/clickhouse_<tên bộ dữ liệu>")
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL"))
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    if not (args.db or "").startswith("clickhouse"):
        sys.exit("Cần T2SQL_DATABASE_URL (hoặc --db clickhouse://...).")

    prof = Profiler(args.db, args.repeat)
    ds = datasets.for_backend(prof.backend)
    args.results = args.results or os.path.join(ROOT, "results", f"clickhouse_{ds.name}")
    with open(ds.eval_path, encoding="utf-8") as f:
        items = {it["id"]: it for it in json.load(f)}
    print(f"ClickHouse {prof.server} tại {prof.backend.host}:{prof.backend.port}, bộ dữ liệu {ds.name}, "
          f"đo {args.repeat} lần/câu", flush=True)

    gold_sql = {iid: example_sql(it) for iid, it in items.items() if it.get("sql")}
    records = []
    for cfg in CONFIG_ORDER:
        path = os.path.join(args.results, f"{cfg}.jsonl")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                records += [(cfg, json.loads(line)) for line in f if line.strip()]
    for s in list(gold_sql.values()) + [r["sql"] for _, r in records if r.get("sql")]:
        prof.submit(s)
    print(f"Đã chạy {len(prof.pending)} câu SQL khác nhau, đọc system.query_log...", flush=True)
    prof.collect()

    out_path = os.path.join(args.results, "query_metrics.jsonl")
    host = f"{prof.backend.host} (ClickHouse {prof.server})"
    with open(out_path, "w", encoding="utf-8") as out:
        for cfg, rec in records:
            m = prof.get(rec["sql"]) if rec.get("sql") else None
            g = prof.get(gold_sql.get(rec["item_id"])) if rec["item_id"] in gold_sql else None
            if m and m["ok"] and g and g["ok"] and g["exec_ms"]:
                m = dict(m, score=round(m["exec_ms"] / g["exec_ms"], 2))
            llm_ms = sum(a.get("llm_ms", 0) for a in rec.get("attempts", []))
            row = {"config": cfg, "item_id": rec["item_id"], "difficulty": rec["difficulty"],
                   "question": rec["question"], "time": rec.get("started_at"), "sql": rec.get("sql"),
                   "kind": rec["kind"], "correct": rec["correct"], "error_category": rec.get("error_category"),
                   "eval_error": rec.get("error"), "message": rec.get("message"), "n_attempts": rec["n_attempts"],
                   "latency_ms": rec["latency_ms"], "llm_ms": round(llm_ms, 1), "host": host,
                   "metrics": m, "gold_metrics": g,
                   "status": status_of(rec, m, g) if rec.get("sql") else ("Normal" if rec["correct"] else "Sai kết quả")}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    ok = [prof.cache[s] for s in prof.cache if prof.cache[s]["ok"]]
    if ok:
        q = lambda k: statistics.median(m[k] for m in ok)
        print(f"Trung vị: {q('duration_ms'):.2f} ms, CPU {q('cpu_ms'):.2f} ms, đọc {q('read_rows'):.0f} dòng, "
              f"bộ nhớ {q('memory_bytes') / 1024:.0f} KiB; chậm nhất {max(m['duration_ms'] for m in ok):.1f} ms")
    print(f"Đã ghi {len(records)} dòng: {out_path}")


if __name__ == "__main__":
    main()
