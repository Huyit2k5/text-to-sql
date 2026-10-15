"""Chạy THẬT một số truy vấn nặng trên ClickHouse dùng chung, từng câu một, rồi đọc tài nguyên thật từ system.query_log.

An toàn:
  - tuần tự (không song song), nghỉ giữa các câu;
  - mỗi câu bị giới hạn thời gian (T2SQL_QUERY_TIMEOUT hoặc --timeout) và số dòng trả về (100);
  - kiểm tra tải trước khi chạy (số truy vấn đang chạy trên server) và dừng nếu server đang bận;
  - dừng ngay khi một câu chạm giới hạn thời gian hoặc bộ nhớ, không chạy tiếp các câu còn lại;
  - chỉ SELECT qua đường chạy của hệ thống (có kiểm tra an toàn), gắn log_comment để tra lại trong query_log.

  python experiments/heavy/run_heavy.py [--timeout 30] [--max-busy 3] [--pause 8]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from t2sql import datasets  # noqa: E402,F401  (nạp .env)
from t2sql.db import make_backend  # noqa: E402
from t2sql.safety import POLICIES  # noqa: E402

COMMENT = "t2sql_heavy_test"
V = "VATInvoice FINAL"
# từ nhẹ đến nặng; mã khớp estimate_only.py
CASES = [
    ("h01", "đếm hóa đơn toàn thời gian", f"SELECT count() FROM {V} WHERE is_deleted = 0"),
    ("h02", "tổng tiền toàn thời gian", f"SELECT sum(Total), sum(Amount) FROM {V} WHERE is_deleted = 0"),
    ("h03", "GROUP BY tên công ty, toàn thời gian",
     f"SELECT ComName, count() c FROM {V} WHERE is_deleted = 0 GROUP BY ComName ORDER BY c DESC LIMIT 5"),
    ("h05", "uniqExact tên công ty", f"SELECT uniqExact(ComName) FROM {V} WHERE is_deleted = 0"),
    ("h04", "GROUP BY công ty và tháng",
     f"SELECT ComID, toStartOfMonth(ArisingDate) m, sum(Total) FROM {V} WHERE is_deleted = 0 GROUP BY ComID, m LIMIT 100"),
    ("h06", "mặt hàng bán chạy nhất mọi năm (dòng hàng)",
     "SELECT Name, sum(Quantity) q FROM ProductInv FINAL WHERE is_deleted = 0 GROUP BY Name ORDER BY q DESC LIMIT 10"),
    ("h10", "ORDER BY Amount toàn bảng",
     f"SELECT id, ComName, Amount FROM {V} WHERE is_deleted = 0 ORDER BY Amount DESC LIMIT 20"),
    ("h08", "nối hóa đơn với dòng hàng, không lọc ngày",
     "SELECT v.ComName, sum(p.Total) FROM VATInvoice AS v FINAL INNER JOIN ProductInv AS p FINAL "
     "ON v.ComID = p.ComID AND v.id = p.InvID WHERE v.is_deleted = 0 AND p.is_deleted = 0 "
     "GROUP BY v.ComName ORDER BY 2 DESC LIMIT 5"),
    ("h12", "hàm cửa sổ theo công ty, toàn thời gian",
     f"SELECT ComID, ArisingDate, Total, row_number() OVER (PARTITION BY ComID ORDER BY ArisingDate) rn FROM {V} WHERE is_deleted = 0"),
]


def server_busy(ex):
    """Đo tải gián tiếp (tài khoản không đọc được system.processes): số truy vấn đã kết thúc trong 60 giây gần nhất."""
    r = ex.run("SELECT count() FROM system.query_log WHERE event_time >= now() - 60 AND type = 'QueryFinish'", safe=False)
    return int(r.rows[0][0]) if r.ok and r.rows else -1


def usage(ex, comments):
    """Tài nguyên thật từ query_log cho các truy vấn đã gắn log_comment."""
    q = ("SELECT query_start_time, query_duration_ms, read_rows, formatReadableSize(read_bytes), "
         "formatReadableSize(memory_usage), type, exception_code, substring(query, 1, 60) "
         f"FROM clusterAllReplicas(default, system.query_log) WHERE log_comment = '{comment_filter(comments)}' "
         "AND type != 'QueryStart' ORDER BY query_start_time")
    r = ex.run(q, safe=False)
    if r.ok:
        return r.rows
    r2 = ex.run(q.replace("clusterAllReplicas(default, system.query_log)", "system.query_log"), safe=False)
    return r2.rows if r2.ok else []


def comment_filter(_):
    return COMMENT


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--max-busy", type=int, default=100, help="không chạy nếu trong 60 giây gần nhất server đã xử lý nhiều hơn số truy vấn này")
    ap.add_argument("--pause", type=int, default=8)
    args = ap.parse_args()
    ex = make_backend(None, max_rows=100, timeout_s=args.timeout)
    busy = server_busy(ex)
    print(f"Truy vấn server đã xử lý trong 60 giây gần nhất: {busy} (ngưỡng cho phép: {args.max_busy})")
    if busy < 0 or busy > args.max_busy:
        sys.exit("Server đang bận hoặc không đọc được tải: không chạy.")
    stopped = None
    for cid, desc, sql in CASES:
        busy = server_busy(ex)
        if busy > args.max_busy:
            stopped = f"server bận ({busy} truy vấn) trước khi chạy {cid}"
            break
        t0 = time.perf_counter()
        res = ex.run(sql, policy=POLICIES["admin"], log_comment=COMMENT)
        secs = time.perf_counter() - t0
        status = "ok" if res.ok else f"LỖI {res.error_code}"
        print(f"{cid} {status:18s} {secs:6.1f}s  {len(res.rows) if res.ok else '-':>4} dòng  {desc}", flush=True)
        if not res.ok:
            print("     ", (res.error or "")[:160].replace("\n", " "))
            stopped = f"{cid} lỗi ({res.error_code}): dừng các câu còn lại"
            break
        if secs > 0.8 * args.timeout:
            stopped = f"{cid} mất {secs:.0f}s, gần giới hạn: dừng các câu còn lại"
            break
        time.sleep(args.pause)
    print("\nDừng sớm:" if stopped else "\nChạy hết các câu.", stopped or "")
    print("\nTài nguyên thật từ system.query_log:")
    rows = usage(ex, COMMENT)
    print(f"{'thời gian':>9s} {'dòng đọc':>12s} {'byte đọc':>10s} {'bộ nhớ':>10s}  trạng thái / câu")
    for st, ms, rr, rb, mem, typ, exc, q in rows:
        print(f"{ms / 1000:8.1f}s {rr:12,d} {rb:>10s} {mem:>10s}  {typ} {exc or ''} {q}")


if __name__ == "__main__":
    main()
