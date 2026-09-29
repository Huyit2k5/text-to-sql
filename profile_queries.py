"""Đo chi phí thực thi từng câu SQL trên PostgreSQL (giống bảng "Query Latency & Memory" của dashboard).

Với mỗi câu SQL do model sinh (và SQL chuẩn của cùng câu hỏi, để so sánh):
  - Duration   : thời gian chạy phía client (gửi câu lệnh -> nhận hết kết quả), trung vị của N lần đo
  - Exec time  : "Execution Time" + "Planning Time" từ EXPLAIN ANALYZE (phía server)
  - CPU time   : thời gian CPU của tiến trình Postgres phục vụ kết nối, đọc từ /proc/<pid>/schedstat (ns)
  - CPU core   : CPU time / Duration (số core dùng trung bình)
  - Read rows  : tổng số dòng đọc từ bảng (các node scan: actual rows + rows removed by filter, nhân số loop)
  - Read bytes : shared buffers hit + read (x 8 KiB)
  - Memory     : tổng bộ nhớ đỉnh của các node Sort / Hash / HashAggregate / Memoize (work_mem thực dùng)
  - Result     : số dòng kết quả
  - Score      : Exec time của SQL model / Exec time của SQL chuẩn (1.0 = ngang SQL chuẩn)
  - Status     : Normal | Chậm | Sai kết quả | Lỗi

Chạy trên máy host (cần quyền `docker exec` vào container Postgres để đọc /proc):
  python profile_queries.py                       # đọc results/postgres/*.jsonl, ghi results/postgres/query_metrics.jsonl
  python profile_queries.py --repeat 5 --container text-to-sql-db-1
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time

import psycopg
from psycopg import sql as psql

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT
from t2sql.dialect import example_sql
from t2sql.pipeline import ABLATION_ORDER

SLOW_SCORE = 2.0        # chậm hơn SQL chuẩn quá 2 lần ...
SLOW_MIN_MS = 20.0      # ... và mất trên 20 ms thì đánh dấu "Chậm"
SLOW_ABS_MS = 1000.0    # hoặc trên 1 giây


class ProcReader:
    """Một tiến trình `docker exec -i <container> sh` chạy suốt, để đọc /proc nhanh (không tạo process mới mỗi lần)."""

    def __init__(self, container):
        env = dict(os.environ, MSYS_NO_PATHCONV="1")
        # Pipe nhị phân: ở chế độ text, Windows đổi "\n" thành "\r\n" và shell trong container đọc sai đường dẫn.
        self.p = subprocess.Popen(["docker", "exec", "-i", container, "sh"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, bufsize=0, env=env)

    def cpu_ns(self, pid):
        self.p.stdin.write(f"cut -d' ' -f1 /proc/{pid}/schedstat\n".encode())
        line = self.p.stdout.readline().decode().strip()
        if not line:
            raise RuntimeError(f"Không đọc được /proc/{pid}/schedstat trong container")
        return int(line)

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


def plan_stats(plan):
    """Tổng hợp từ cây EXPLAIN (FORMAT JSON)."""
    read_rows, mem_kb, disk_kb, nodes = 0, 0, 0, []

    def walk(n):
        nonlocal read_rows, mem_kb, disk_kb
        nodes.append(n["Node Type"])
        loops = n.get("Actual Loops", 1) or 1
        if "Relation Name" in n:
            read_rows += (n.get("Actual Rows", 0) + n.get("Rows Removed by Filter", 0)
                          + n.get("Rows Removed by Index Recheck", 0)) * loops
        mem_kb += n.get("Peak Memory Usage", 0)
        if n.get("Sort Space Type") == "Memory":
            mem_kb += n.get("Sort Space Used", 0)
        elif n.get("Sort Space Type") == "Disk":
            disk_kb += n.get("Sort Space Used", 0)
        disk_kb += n.get("Disk Usage", 0)
        for c in n.get("Plans", []):
            walk(c)

    root = plan["Plan"]
    walk(root)
    blocks = root.get("Shared Hit Blocks", 0) + root.get("Shared Read Blocks", 0)
    return {"read_rows": int(read_rows), "read_bytes": blocks * 8192, "memory_bytes": int(mem_kb * 1024),
            "disk_bytes": int(disk_kb * 1024), "exec_ms": plan.get("Execution Time", 0.0),
            "plan_ms": plan.get("Planning Time", 0.0), "nodes": nodes}


class Profiler:
    def __init__(self, url, container, repeat=3, role="t2sql_admin_ro", timeout_ms=30000):
        self.conn = psycopg.connect(url, autocommit=True, connect_timeout=10, application_name="t2sql-profiler")
        self.conn.execute(psql.SQL("SET ROLE {}").format(psql.Identifier(role)))
        self.conn.execute("SET default_transaction_read_only = on")
        self.conn.execute(f"SET statement_timeout = {int(timeout_ms)}")
        self.pid = self.conn.execute("SELECT pg_backend_pid()").fetchone()[0]
        self.host = self.conn.info.host
        self.server = self.conn.execute("SHOW server_version").fetchone()[0]
        self.proc = ProcReader(container)
        self.repeat = repeat
        self.cache = {}

    def profile(self, sql_text):
        if sql_text in self.cache:
            return self.cache[sql_text]
        out = {"ok": True, "error": None}
        try:
            self.conn.execute(sql_text).fetchall()                      # khởi động (cache, plan)
            durations, cpus = [], []
            for _ in range(self.repeat):
                c0 = self.proc.cpu_ns(self.pid)
                t0 = time.perf_counter()
                rows = self.conn.execute(sql_text).fetchall()
                durations.append((time.perf_counter() - t0) * 1000)
                cpus.append((self.proc.cpu_ns(self.pid) - c0) / 1e6)
            plans = [self.conn.execute(psql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ") + psql.SQL(sql_text))
                     .fetchone()[0][0] for _ in range(self.repeat)]
            stats = [plan_stats(p) for p in plans]
            dur = statistics.median(durations)
            cpu = statistics.median(cpus)
            out.update(duration_ms=round(dur, 3), cpu_ms=round(cpu, 3), cpu_cores=round(cpu / dur, 3) if dur else 0,
                       result_rows=len(rows),
                       exec_ms=round(statistics.median(s["exec_ms"] + s["plan_ms"] for s in stats), 3),
                       **{k: stats[0][k] for k in ("read_rows", "read_bytes", "memory_bytes", "disk_bytes", "nodes")})
        except psycopg.Error as e:
            out.update(ok=False, error=(e.diag.message_primary or str(e)).splitlines()[0])
        self.cache[sql_text] = out
        return out

    def close(self):
        self.proc.close()
        self.conn.close()


def status_of(rec, m, gold_m):
    if not m or not m["ok"]:
        return "Lỗi"
    if not rec["correct"]:
        return "Sai kết quả"
    score = m.get("score")
    if m["duration_ms"] > SLOW_ABS_MS or (score and score > SLOW_SCORE and m["exec_ms"] > SLOW_MIN_MS):
        return "Chậm"
    return "Normal"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(ROOT, "results", "postgres"))
    ap.add_argument("--db", default=os.environ.get("T2SQL_DATABASE_URL"))
    ap.add_argument("--container", default="text-to-sql-db-1")
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    if not (args.db or "").startswith("postgres"):
        sys.exit("Cần T2SQL_DATABASE_URL trỏ tới PostgreSQL (hoặc --db).")

    with open(os.path.join(ROOT, "eval", "dataset.json"), encoding="utf-8") as f:
        items = {it["id"]: it for it in json.load(f)}
    prof = Profiler(args.db, args.container, args.repeat)
    print(f"PostgreSQL {prof.server} tại {prof.host}, backend pid {prof.pid}, đo {args.repeat} lần/câu", flush=True)

    gold = {}
    for iid, it in items.items():
        if it.get("sql"):
            gold[iid] = prof.profile(example_sql(it, "postgres"))
    print(f"Đã đo {len(gold)} câu SQL chuẩn", flush=True)

    out_path = os.path.join(args.results, "query_metrics.jsonl")
    n = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for cfg in ABLATION_ORDER:
            path = os.path.join(args.results, f"{cfg}.jsonl")
            if not os.path.exists(path):
                continue
            for line in open(path, encoding="utf-8"):
                rec = json.loads(line)
                m = prof.profile(rec["sql"]) if rec.get("sql") else None
                g = gold.get(rec["item_id"])
                if m and m["ok"] and g and g["ok"] and g["exec_ms"]:
                    m = dict(m, score=round(m["exec_ms"] / g["exec_ms"], 2))
                llm_ms = sum(a.get("llm_ms", 0) for a in rec.get("attempts", []))
                row = {"config": cfg, "item_id": rec["item_id"], "difficulty": rec["difficulty"],
                       "question": rec["question"], "time": rec.get("started_at"), "sql": rec.get("sql"),
                       "kind": rec["kind"], "correct": rec["correct"], "error_category": rec.get("error_category"),
                       "eval_error": rec.get("error"), "message": rec.get("message"), "n_attempts": rec["n_attempts"],
                       "latency_ms": rec["latency_ms"], "llm_ms": round(llm_ms, 1),
                       "host": f"{prof.host} (PostgreSQL {prof.server})",
                       "metrics": m, "gold_metrics": g, "status": status_of(rec, m, g) if rec.get("sql") else
                       ("Normal" if rec["correct"] else "Sai kết quả")}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
            print(f"  {cfg}: xong", flush=True)
    prof.close()
    print(f"Đã ghi {n} dòng: {out_path}")


if __name__ == "__main__":
    main()
