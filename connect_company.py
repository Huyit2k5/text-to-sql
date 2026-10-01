"""Kiểm tra kết nối tới ClickHouse của công ty và tạo bộ dữ liệu khởi đầu.

Đặt URL trong .env (không dán mật khẩu vào chat hay commit):
  T2SQL_DATABASE_URL_CONGTY=clickhouses://tai_khoan:mat_khau@host:8443/ten_database?single_user=1

  python connect_company.py                       # kiểm tra T2SQL_DATABASE_URL_CONGTY
  python connect_company.py --env T2SQL_DATABASE_URL_KHAC
  python connect_company.py --url "clickhouse://..."
  python connect_company.py --init                # kiểm tra xong thì tạo datasets/<database>/schema_docs.json

Chỉ chạy các lệnh đọc (SELECT / SHOW / EXPLAIN). Mật khẩu không bao giờ được in ra.
"""
import argparse
import json
import os
import sys
from urllib.parse import unquote, urlsplit

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT
from t2sql.db import make_backend
from t2sql.safety import POLICIES

OK, WARN, BAD = "[OK]  ", "[LƯU Ý]", "[LỖI] "


def masked(url: str) -> str:
    u = urlsplit(url)
    host = f"{u.hostname}:{u.port}" if u.port else (u.hostname or "")
    return f"{u.scheme}://{unquote(u.username or '')}:***@{host}{u.path}"


def one(client, sql, default=None):
    try:
        rows = client.query(sql).result_rows
        return rows[0][0] if rows else default
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="URL ClickHouse (mặc định đọc từ biến môi trường --env)")
    ap.add_argument("--env", default="T2SQL_DATABASE_URL_CONGTY", help="tên biến môi trường chứa URL")
    ap.add_argument("--init", action="store_true", help="tạo datasets/<database>/schema_docs.json từ schema thật")
    a = ap.parse_args()

    url = (a.url or os.environ.get(a.env, "")).strip()
    if not url:
        sys.exit(f"Chưa có URL. Đặt {a.env}=clickhouses://user:mat_khau@host:8443/database?single_user=1 trong .env "
                 f"(xem .env.example), hoặc truyền --url.")
    print("Kết nối:", masked(url))
    be = make_backend(url)
    if "single_user" not in url:
        print(f"{WARN} URL chưa có ?single_user=1: backend sẽ đăng nhập bằng '{be.username(POLICIES['admin'])}' "
              "thay vì tài khoản của bạn. Thêm ?single_user=1 nếu dùng một tài khoản chung của công ty.")
    try:
        c = be._client(POLICIES["admin"])
        version = c.query("SELECT version()").result_rows[0][0]
    except Exception as e:
        sys.exit(f"{BAD} Không kết nối được: {str(e)[:300]}\n   Kiểm tra: host, cổng (8123 HTTP / 8443 HTTPS), "
                 "clickhouses:// nếu dùng HTTPS, tên tài khoản và mật khẩu, và mạng / VPN tới server.")
    me = one(c, "SELECT currentUser()")
    print(f"{OK} Đã kết nối ClickHouse {version}, tài khoản '{me}', database '{be.database}'")

    dbs = [r[0] for r in c.query("SELECT name FROM system.databases ORDER BY name").result_rows]
    if be.database not in dbs:
        print(f"{BAD} Không thấy database '{be.database}'. Các database tài khoản này thấy: {', '.join(dbs)}")
        sys.exit(1)

    tables = c.query("SELECT name, engine, coalesce(total_rows, 0) FROM system.tables WHERE database = {d:String} "
                     "AND NOT is_temporary ORDER BY name", parameters={"d": be.database}).result_rows
    print(f"{OK} Thấy {len(tables)} bảng trong '{be.database}'" + (":" if tables else " (tài khoản chưa có quyền SELECT?)"))
    for name, engine, n in tables[:40]:
        print(f"      {name:40s} {engine:28s} {int(n):>15,} dòng")
    if len(tables) > 40:
        print(f"      ... và {len(tables) - 40} bảng nữa")

    # Quyền ghi: tài khoản dùng cho Text-to-SQL chỉ nên có SELECT
    grants = [r[0] for r in c.query("SHOW GRANTS").result_rows] if one(c, "SELECT 1") else []
    risky = [g for g in grants if any(k in g.upper() for k in ("INSERT", "ALTER", "CREATE", "DROP", "TRUNCATE", "ALL ON", "GRANT OPTION"))]
    if risky:
        print(f"{WARN} Tài khoản có quyền ngoài đọc dữ liệu (nên xin tài khoản chỉ SELECT):")
        for g in risky[:5]:
            print("      ", g[:160])
    else:
        print(f"{OK} Tài khoản không có quyền ghi / thay đổi cấu trúc")

    # Có đổi được setting giới hạn từng truy vấn không?
    r = be.run("SELECT 1 AS x", POLICIES["admin"], safe=True)
    if not r.ok:
        print(f"{BAD} Chạy thử SELECT 1 lỗi: {r.error}")
    elif be.restricted:
        print(f"{WARN} Tài khoản không được đổi setting (readonly=1): không đặt được giới hạn thời gian / bộ nhớ "
              "cho từng truy vấn. Backend tự chuyển sang chế độ hạn chế (chỉ lấy tối đa số dòng cho phép). "
              "Nên nhờ DBA gắn profile giới hạn (max_execution_time, max_memory_usage, max_rows_to_read) cho tài khoản này.")
    else:
        print(f"{OK} Đặt được giới hạn thời gian / số dòng cho từng truy vấn")

    # EXPLAIN ESTIMATE (chặn truy vấn nặng) cần quyền đọc bảng
    if tables:
        est = be.estimate_rows(f"SELECT count() FROM `{be.database}`.`{tables[0][0]}`", POLICIES["admin"])
        print(f"{OK if est else WARN} EXPLAIN ESTIMATE " + ("chạy được (dùng cho chặn truy vấn nặng)" if est else
              "không chạy được: tính năng chặn truy vấn nặng sẽ bị bỏ qua"))

    # system.query_log cho phương pháp "tri thức từ lịch sử truy vấn"
    n = one(c, "SELECT count() FROM system.query_log WHERE type = 'QueryFinish' AND query_kind = 'Select' "
               "AND event_date >= today() - 30")
    if n is None:
        print(f"{WARN} Không đọc được system.query_log. Phương pháp lịch sử truy vấn cần DBA xuất giúp một file "
              f"datasets/{be.database}/query_history.jsonl (chỉ các SELECT thành công).")
    else:
        print(f"{OK} Đọc được system.query_log: {int(n):,} truy vấn SELECT trong 30 ngày gần nhất "
              f"(có thể khai thác bằng mine_query_log.py)")

    ds_dir = os.path.join(ROOT, "datasets", be.database)
    docs = os.path.join(ds_dir, "schema_docs.json")
    if os.path.exists(docs):
        print(f"{OK} Đã có bộ dữ liệu {os.path.relpath(docs, ROOT)}")
    elif a.init:
        init_dataset(c, be, ds_dir, docs)
    else:
        print(f"{WARN} Chưa có datasets/{be.database}/schema_docs.json (bắt buộc). Chạy lại với --init để tạo bản khởi đầu.")


def init_dataset(c, be, ds_dir, docs):
    cols = c.query("SELECT table, name, comment FROM system.columns WHERE database = {d:String} ORDER BY table, position",
                   parameters={"d": be.database}).result_rows
    tcomment = dict(c.query("SELECT name, comment FROM system.tables WHERE database = {d:String}",
                            parameters={"d": be.database}).result_rows)
    tables = {}
    for t, name, comment in cols:
        e = tables.setdefault(t, {"description": tcomment.get(t, ""), "keywords": "", "columns": {}})
        if comment:
            e["columns"][name] = comment
    doc = {
        "title": f"Database {be.database}",
        "sql_dialect": "clickhouse",
        "business_rules": ["TODO: quy tắc nghiệp vụ bắt buộc áp dụng (ví dụ: bảng ReplacingMergeTree phải dùng FINAL, "
                           "múi giờ, đơn vị tiền, trạng thái nào được tính là hợp lệ)"],
        "tables": tables,
        "concepts": {},
        "relations": {},
        "requires": {},
        "no_sample_columns": [],
        "policies": {"admin": {}},
        "example_questions": [],
    }
    os.makedirs(ds_dir, exist_ok=True)
    with open(docs, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"{OK} Đã tạo {os.path.relpath(docs, ROOT)} ({len(tables)} bảng). Việc cần làm tiếp, theo thứ tự quan trọng:")
    print("      1. Điền description + mô tả cột cho các bảng / cột chính (ảnh hưởng độ chính xác nhiều nhất)")
    print("      2. Điền business_rules, relations (khóa ngoại dạng \"bang.cot\": \"bang_khac.cot\"), no_sample_columns "
          "cho cột nhạy cảm (số điện thoại, email, CCCD...)")
    print("      3. Viết eval.json: 20-30 câu hỏi thật kèm SQL chuẩn, rồi chạy evaluate.py để đo")


if __name__ == "__main__":
    main()
