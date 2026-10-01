"""Giả lập lịch sử truy vấn của analyst trên ClickHouse `einvoice` (system.query_log).

Chạy:  python datasets/einvoice/make_query_log.py [--n 700]

Các bước:
  1. Tạo user `bi_analyst` (chỉ đọc, dùng profile t2sql_ro) - đại diện cho analyst của công ty.
  2. Sinh ~N câu SQL theo phong cách analyst rồi CHẠY THẬT bằng user đó, nên chúng nằm trong system.query_log
     giống lịch sử thật (kèm vài câu lỗi cú pháp, ghi exception).
  3. In thống kê. Bước khai thác tri thức nằm ở mine_query_log.py.

Thiết kế cho gần thực tế, để không "tự chấm bài mình":
  - Nhiều cách viết cho cùng một ý (alias khác nhau, thứ tự điều kiện, kiểu lọc thời gian, comment tiếng Việt).
  - ~12% câu "cẩu thả": quên FINAL, quên đổi múi giờ, quên nhân tỷ giá, hoặc lọc trạng thái khác chuẩn.
    Log thật luôn lẫn thói quen không nhất quán; khai thác phải chịu được nhiễu này.
  - Bỏ mọi câu trùng (sau khi chuẩn hóa) với SQL chuẩn của bộ dev, bộ held-out và pool few-shot.
Lưu ý trung thực: người viết bộ sinh này cũng là người viết bộ đánh giá, nên lịch sử phản ánh những quy ước mà
người viết đã biết. Thí nghiệm chứng minh cơ chế hoạt động, không chứng minh mức cải thiện trên dữ liệu thật.
"""
import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import t2sql  # noqa: E402,F401  (nạp .env)

USER = "bi_analyst"
TZ = "'Asia/Ho_Chi_Minh'"
VALID = ["'cqt_cap_ma'", "'da_gui_cqt'", "'bi_dieu_chinh'"]
MONTHS = [y * 100 + m for y in (2023, 2024, 2025) for m in range(1, 13) if y * 100 + m <= 202506]
REGIONS = ["Miền Bắc", "Miền Trung", "Miền Nam", "Tây Nguyên"]
ENDPOINTS = ["/api/invoice/create", "/api/invoice/sign", "/api/invoice/publish", "/api/invoice/search",
             "/api/invoice/download-pdf", "/api/auth/token"]
PROVINCES = [("01", "Hà Nội"), ("79", "TP. Hồ Chí Minh"), ("48", "Đà Nẵng"), ("31", "Hải Phòng"), ("92", "Cần Thơ")]


class Ctx:
    def __init__(self, rng, sloppy):
        self.r, self.sloppy = rng, sloppy

    def pick(self, xs):
        return self.r.choice(xs)

    def chance(self, p):
        return self.r.random() < p

    # --- các thói quen (mỗi thói quen có thể bị "quên" khi câu là loại cẩu thả)
    def final(self):
        return "" if "final" in self.sloppy else " FINAL"

    def valid(self, p=""):
        if "valid" in self.sloppy:
            return f"{p}status != 'da_huy'"
        vals = VALID[:]
        if self.chance(0.3):
            self.r.shuffle(vals)
        return f"{p}status IN ({', '.join(vals)})"

    def rev(self, p=""):
        fx = "" if "fx" in self.sloppy else f" * {p}exchange_rate"
        return f"({p}total_before_tax - {p}total_discount){fx}"

    def tz(self, col):
        return col if "tz" in self.sloppy else f"toTimeZone({col}, {TZ})"

    def month(self):
        return self.pick(MONTHS)

    def year(self):
        return self.pick([2023, 2024, 2025])

    def span(self, col, ym):
        """Lọc theo một tháng yyyymm cho cột giờ Việt Nam."""
        if self.chance(0.6):
            return f"toYYYYMM({col}) = {ym}"
        y, m = divmod(ym, 100)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        return (f"{col} >= toDateTime('{y}-{m:02d}-01 00:00:00', {TZ}) "
                f"AND {col} < toDateTime('{ny}-{nm:02d}-01 00:00:00', {TZ})")

    def comment(self, options, p=0.3):
        return f"-- {self.pick(options)}\n" if self.chance(p) else ""


# ---------------------------------------------------------------------------------------------- các mẫu truy vấn
def rev_by_month(c):
    y, a = c.year(), c.pick(["", "i"])
    q = f"{a}." if a else ""
    m = c.pick([f"toStartOfMonth({q}issued_at) AS thang", f"formatDateTime({q}issued_at, '%Y-%m') AS thang"])
    return (c.comment(["doanh thu theo tháng", "doanh thu hợp lệ theo tháng, đã quy đổi VND"]) +
            f"SELECT {m}, sum({c.rev(q)}) AS doanh_thu FROM invoices{' AS ' + a if a else ''}{c.final()} "
            f"WHERE {c.valid(q)} AND toYear({q}issued_at) = {y} GROUP BY thang ORDER BY thang")


def count_valid_month(c):
    return (c.comment(["số hóa đơn hợp lệ trong tháng", "đếm hóa đơn đã được cấp mã"]) +
            f"SELECT count() AS so_hoa_don FROM invoices{c.final()} WHERE {c.valid()} AND {c.span('issued_at', c.month())}")


def top_sellers_revenue(c):
    ym, n = c.month(), c.pick([5, 10, 20])
    a, s = c.pick(["i", "inv"]), c.pick(["s", "dn"])
    on = c.pick([f"{s}.seller_id = {a}.seller_id", f"{a}.seller_id = {s}.seller_id"])
    return (c.comment(["top doanh nghiệp theo doanh thu", "top doanh nghiệp doanh thu cao nhất"]) +
            f"SELECT {s}.tax_code, {s}.name, sum({c.rev(a + '.')}) AS doanh_thu FROM invoices AS {a}{c.final()} "
            f"JOIN sellers AS {s} ON {on} WHERE {c.valid(a + '.')} AND {c.span(a + '.issued_at', ym)} "
            f"GROUP BY {s}.seller_id, {s}.tax_code, {s}.name ORDER BY doanh_thu DESC LIMIT {n}")


def rev_by_region(c):
    y = c.year()
    return (f"SELECT p.region, sum({c.rev('i.')}) AS doanh_thu FROM invoices AS i{c.final()} "
            f"JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code "
            f"WHERE {c.valid('i.')} AND toYear(i.issued_at) = {y} GROUP BY p.region ORDER BY doanh_thu DESC")


def vat_by_rate(c):
    ym = c.month()
    fx = "" if "fx" in c.sloppy else " * i.exchange_rate"
    return (c.comment(["tiền thuế theo thuế suất, quy đổi VND"]) +
            f"SELECT it.vat_rate, sum(it.vat_amount{fx}) AS tien_thue FROM invoice_items AS it "
            f"JOIN (SELECT invoice_id, exchange_rate FROM invoices{c.final()} WHERE {c.valid()} AND toYYYYMM(issued_at) = {ym}) AS i "
            f"ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = {ym} GROUP BY it.vat_rate ORDER BY tien_thue DESC")


def group_revenue(c):
    q0 = c.pick([(202401, 202403), (202404, 202406), (202407, 202409), (202410, 202412), (202501, 202503)])
    fx = "" if "fx" in c.sloppy else " * i.exchange_rate"
    return (f"SELECT it.product_group, sum((it.line_amount - it.discount_amount){fx}) AS doanh_thu FROM invoice_items AS it "
            f"JOIN (SELECT invoice_id, exchange_rate FROM invoices{c.final()} WHERE {c.valid()} "
            f"AND toYYYYMM(issued_at) BETWEEN {q0[0]} AND {q0[1]}) AS i ON i.invoice_id = it.invoice_id "
            f"WHERE toYYYYMM(it.issued_at) BETWEEN {q0[0]} AND {q0[1]} GROUP BY it.product_group ORDER BY doanh_thu DESC")


def status_dist(c):
    return (f"SELECT status, count() AS so_hoa_don FROM invoices{c.final()} WHERE {c.span('issued_at', c.month())} "
            f"GROUP BY status ORDER BY so_hoa_don DESC")


def cancel_rate_channel(c):
    y = c.year()
    return (c.comment(["tỷ lệ hủy theo kênh lập"]) +
            f"SELECT channel, 100 * countIf(status = 'da_huy') / count() AS ty_le_huy FROM invoices{c.final()} "
            f"WHERE toYear(issued_at) = {y} GROUP BY channel ORDER BY ty_le_huy DESC")


def currency_share(c):
    y = c.year()
    return (f"SELECT currency, sum({c.rev()}) AS doanh_thu_vnd FROM invoices{c.final()} WHERE {c.valid()} "
            f"AND toYear(issued_at) = {y} GROUP BY currency")


def buyers_per_seller(c):
    ym = c.month()
    return (f"SELECT s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i{c.final()} "
            f"JOIN sellers AS s ON s.seller_id = i.seller_id WHERE {c.valid('i.')} AND {c.span('i.issued_at', ym)} "
            f"GROUP BY s.seller_id, s.name ORDER BY so_nguoi_mua DESC LIMIT {c.pick([5, 10])}")


def avg_invoice_value(c):
    fx = "" if "fx" in c.sloppy else " * exchange_rate"
    return (f"SELECT avg(total_amount{fx}) AS gia_tri_tb FROM invoices{c.final()} WHERE {c.valid()} "
            f"AND {c.span('issued_at', c.month())}")


def daily_stats_revenue(c):
    y = c.year()
    return (c.comment(["dùng bảng tổng hợp cho nhanh"], 0.5) +
            f"SELECT toStartOfMonth(day) AS thang, sum(revenue_vnd) AS doanh_thu, sum(invoice_count) AS so_hoa_don "
            f"FROM daily_seller_stats WHERE toYear(day) = {y} GROUP BY thang ORDER BY thang")


def daily_stats_buyers(c):
    ym = c.month()
    return (f"SELECT toStartOfMonth(day) AS thang, uniqExactMerge(buyers) AS so_nguoi_mua FROM daily_seller_stats "
            f"WHERE toYYYYMM(day) = {ym} GROUP BY thang")


def tax_accept_rate(c):
    y = c.year()
    return (c.comment(["tỷ lệ cơ quan thuế chấp nhận"]) +
            f"SELECT formatDateTime({c.tz('sent_at')}, '%Y-%m') AS thang, 100 * countIf(result = 'chap_nhan') / count() AS ty_le_chap_nhan "
            f"FROM tax_messages WHERE message_type = '200' AND toYear({c.tz('sent_at')}) = {y} GROUP BY thang ORDER BY thang")


def tax_response_time(c):
    ym = c.month()
    return (f"SELECT avg(dateDiff('second', sent_at, response_at)) AS giay_phan_hoi_tb FROM tax_messages "
            f"WHERE message_type = '200' AND result = 'chap_nhan' AND toYYYYMM({c.tz('sent_at')}) = {ym}")


def tax_reject_codes(c):
    y = c.year()
    return (f"SELECT e.error_code, e.description, count() AS so_lan FROM tax_messages AS t "
            f"JOIN tax_error_codes AS e ON e.error_code = t.error_code WHERE t.result = 'tu_choi' "
            f"AND toYear({c.tz('t.sent_at')}) = {y} GROUP BY e.error_code, e.description ORDER BY so_lan DESC LIMIT 10")


def tax_daily_messages(c):
    d = c.pick(["2025-06-24", "2025-05-12", "2024-12-20", "2025-03-03"])
    return (f"SELECT toDate({c.tz('sent_at')}) AS ngay, count() AS so_thong_diep FROM tax_messages "
            f"WHERE toDate({c.tz('sent_at')}) >= toDate('{d}') AND toDate({c.tz('sent_at')}) < toDate('{d}') + 7 GROUP BY ngay ORDER BY ngay")


def api_error_by_hour(c):
    d = c.pick(["2025-03-18", "2025-06-10", "2024-11-05", "2025-01-20"])
    return (c.comment(["tỷ lệ lỗi API theo giờ (giờ VN)"]) +
            f"SELECT toHour({c.tz('ts')}) AS gio, 100 * countIf(http_status >= 400) / count() AS ty_le_loi FROM api_requests "
            f"WHERE toDate({c.tz('ts')}) = toDate('{d}') GROUP BY gio ORDER BY gio")


def api_p95(c):
    ym = c.month()
    return (f"SELECT endpoint, quantileExact(0.95)(latency_ms) AS p95_ms, count() AS so_request FROM api_requests "
            f"WHERE toYYYYMM({c.tz('ts')}) = {ym} GROUP BY endpoint ORDER BY p95_ms DESC")


def api_top_sellers(c):
    ym = c.month()
    return (f"SELECT s.name, count() AS so_request, 100 * countIf(a.http_status >= 400) / count() AS ty_le_loi "
            f"FROM api_requests AS a JOIN sellers AS s ON s.seller_id = a.seller_id WHERE toYYYYMM({c.tz('a.ts')}) = {ym} "
            f"GROUP BY s.seller_id, s.name ORDER BY so_request DESC LIMIT 5")


def sellers_by_province(c):
    return (f"SELECT p.name, count() AS so_dn FROM sellers AS s JOIN provinces AS p ON p.province_code = s.province_code "
            f"WHERE s.status = 'active' GROUP BY p.name ORDER BY so_dn DESC LIMIT {c.pick([5, 10])}")


def subs_revenue_plan(c):
    y = c.year()
    return (f"SELECT p.name, sum(s.amount_vnd) AS doanh_thu FROM subscriptions AS s JOIN service_plans AS p ON p.plan_id = s.plan_id "
            f"WHERE s.payment_status = 'da_thanh_toan' AND toYear(s.purchased_at) = {y} GROUP BY p.name ORDER BY doanh_thu DESC")


def certs_expiring(c):
    days = c.pick([15, 30, 60])
    return (f"SELECT provider, count() AS so_chung_thu FROM certificates WHERE revoked = 0 "
            f"AND valid_to >= toDate('2025-06-30') AND valid_to <= toDate('2025-06-30') + {days} GROUP BY provider")


def sellers_registered_quarter(c):
    y = c.pick([2023, 2024])
    return f"SELECT toQuarter(registered_at) AS quy, count() AS so_dn FROM sellers WHERE toYear(registered_at) = {y} GROUP BY quy ORDER BY quy"


def sellers_feature(c):
    f = c.pick(["api", "pos", "ky_hsm", "tich_hop_erp"])
    return (f"SELECT n.name, count() AS so_dn FROM sellers AS s JOIN industries AS n ON n.industry_code = s.industry_code "
            f"WHERE s.status = 'active' AND has(s.features, '{f}') GROUP BY n.name ORDER BY so_dn DESC LIMIT 5")


def invoices_by_channel(c):
    return (f"SELECT channel, count() AS so_hoa_don FROM invoices{c.final()} WHERE {c.valid()} "
            f"AND {c.span('issued_at', c.month())} GROUP BY channel ORDER BY so_hoa_don DESC")


def rev_by_payment(c):
    y = c.year()
    return (f"SELECT payment_method, sum({c.rev()}) AS doanh_thu FROM invoices{c.final()} WHERE {c.valid()} "
            f"AND toYear(issued_at) = {y} GROUP BY payment_method")


def seller_invoices_by_tax_code(c):
    code = c.pick(["7934474156", "0184171901", "5153431186", "4983799012"])
    y = c.year()
    return (c.comment(["hóa đơn hợp lệ của một doanh nghiệp theo MST"], 0.4) +
            f"SELECT toStartOfMonth(issued_at) AS thang, count() AS so_hoa_don, sum({c.rev()}) AS doanh_thu "
            f"FROM invoices{c.final()} WHERE seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '{code}') "
            f"AND {c.valid()} AND toYear(issued_at) = {y} GROUP BY thang ORDER BY thang")


def sellers_by_type(c):
    return "SELECT company_type, count() AS so_dn FROM sellers WHERE status = 'active' GROUP BY company_type ORDER BY so_dn DESC"


def revenue_growth(c):
    y = c.pick([2024, 2025])
    return (f"SELECT thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY thang ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong "
            f"FROM (SELECT toStartOfMonth(issued_at) AS thang, sum({c.rev()}) AS doanh_thu FROM invoices{c.final()} "
            f"WHERE {c.valid()} AND toYear(issued_at) = {y} GROUP BY thang) ORDER BY thang")


def daily_invoices_recent(c):
    return (f"SELECT toDate(issued_at) AS ngay, count() AS so_hoa_don FROM invoices{c.final()} WHERE {c.valid()} "
            f"AND issued_at >= toDateTime('2025-06-01 00:00:00', {TZ}) GROUP BY ngay ORDER BY ngay")


def buyer_type_share(c):
    y = c.year()
    return (f"SELECT b.buyer_type, sum({c.rev('i.')}) AS doanh_thu FROM invoices AS i{c.final()} "
            f"JOIN buyers AS b ON b.buyer_id = i.buyer_id WHERE {c.valid('i.')} AND toYear(i.issued_at) = {y} GROUP BY b.buyer_type")


def replaced_invoices(c):
    y = c.pick([2024, 2025])
    return (f"SELECT nature, count() AS so_hoa_don FROM invoices{c.final()} WHERE nature != 'goc' AND toYear(issued_at) = {y} GROUP BY nature")


def sales_by_region_group(c):
    ym = c.month()
    return (f"SELECT p.region, sum(d.revenue_vnd) AS doanh_thu, sum(d.vat_vnd) AS tien_thue FROM daily_seller_stats AS d "
            f"JOIN sellers AS s ON s.seller_id = d.seller_id JOIN provinces AS p ON p.province_code = s.province_code "
            f"WHERE toYYYYMM(d.day) = {ym} GROUP BY p.region")


TEMPLATES = [
    (rev_by_month, 5), (count_valid_month, 4), (top_sellers_revenue, 4), (rev_by_region, 3), (vat_by_rate, 3),
    (group_revenue, 3), (status_dist, 3), (cancel_rate_channel, 2), (currency_share, 2), (buyers_per_seller, 2),
    (avg_invoice_value, 2), (daily_stats_revenue, 3), (daily_stats_buyers, 2), (tax_accept_rate, 3),
    (tax_response_time, 3), (tax_reject_codes, 3), (tax_daily_messages, 2), (api_error_by_hour, 3), (api_p95, 3),
    (api_top_sellers, 2), (sellers_by_province, 2), (subs_revenue_plan, 2), (certs_expiring, 2),
    (sellers_registered_quarter, 1), (sellers_feature, 2), (invoices_by_channel, 2), (rev_by_payment, 2),
    (seller_invoices_by_tax_code, 2), (sellers_by_type, 1), (revenue_growth, 2), (daily_invoices_recent, 1),
    (buyer_type_share, 2), (replaced_invoices, 1), (sales_by_region_group, 2),
]
BROKEN = [  # câu lỗi thường gặp (gõ sai tên hàm, thiếu GROUP BY, sai tên cột...): ghi exception trong query_log
    "SELECT toyear(issued_at), count() FROM invoices FINAL GROUP BY 1",
    "SELECT seller_id, name, count() FROM sellers GROUP BY seller_id",
    "SELECT sum(total_amout) FROM invoices FINAL",
    "SELECT count() FROM invoice WHERE toYear(issued_at) = 2024",
    "SELECT status, count( FROM invoices FINAL GROUP BY status",
    "SELECT dateDiff('day', sent_at) FROM tax_messages",
]
SLOPPY_FLAGS = ["final", "final", "fx", "tz", "valid"]     # FINAL hay bị quên nhất


def normalize(sql):
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").lower()


def generate(n, seed=7):
    rng = random.Random(seed)
    forbidden = set()
    for name in ("eval.json", "eval_holdout.json", "fewshot_pool.json"):
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            forbidden |= {normalize(it["sql"]) for it in json.load(f) if it.get("sql")}
    funcs = [f for f, w in TEMPLATES for _ in range(w)]
    out, seen, dropped, tries = [], set(), 0, 0
    per_template, cap = {}, max(20, int(n * 0.07))     # không để vài mẫu có nhiều tham số chiếm hết lịch sử
    while len(out) < n and tries < n * 60:
        tries += 1
        f = rng.choice(funcs)
        if per_template.get(f.__name__, 0) >= cap:
            continue
        sloppy = {rng.choice(SLOPPY_FLAGS)} if rng.random() < 0.12 else set()
        sql = f(Ctx(rng, sloppy))
        key = normalize(sql)
        if key in forbidden:
            dropped += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        per_template[f.__name__] = per_template.get(f.__name__, 0) + 1
        out.append({"sql": sql, "template": f.__name__, "sloppy": sorted(sloppy)})
    return out, dropped


def admin_client():
    import clickhouse_connect
    from urllib.parse import urlsplit
    u = urlsplit(os.environ.get("T2SQL_DATABASE_URL_EINVOICE") or "clickhouse://x@127.0.0.1:8123/einvoice")
    return u, dict(host=u.hostname or "127.0.0.1", port=u.port or 8123, secure=u.scheme == "clickhouses"), clickhouse_connect


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=700)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--save", default=os.path.join(HERE, "query_log_generated.jsonl"),
                    help="ghi thêm danh sách câu đã sinh (kèm nhãn cẩu thả) để đối chiếu; KHÔNG dùng lúc chạy pipeline")
    args = ap.parse_args()
    pw = os.environ.get("T2SQL_CH_PASSWORD")
    if not pw:
        sys.exit("Thiếu T2SQL_CH_PASSWORD trong .env")
    _, conn, ch = admin_client()
    admin = ch.get_client(**conn, username=os.environ.get("CLICKHOUSE_USER") or "default",
                          password=os.environ.get("CLICKHOUSE_PASSWORD", ""))
    admin.command(f"CREATE USER IF NOT EXISTS {USER} IDENTIFIED WITH sha256_password BY '{pw}' SETTINGS PROFILE 't2sql_ro'")
    admin.command(f"GRANT SELECT ON einvoice.* TO {USER}")

    items, dropped = generate(args.n, args.seed)
    print(f"Đã sinh {len(items)} câu (bỏ {dropped} câu trùng SQL chuẩn của bộ dev / held-out / few-shot)", flush=True)
    with open(args.save, "w", encoding="utf-8", newline="\n") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    def run(sql):
        c = ch.get_client(**conn, username=USER, password=pw, database="einvoice", autogenerate_session_id=False,
                          send_receive_timeout=120)
        try:
            c.query(sql, settings={"max_execution_time": 60})
            return "ok"
        except Exception as e:
            return "error:" + str(e)[:80]

    sqls = [it["sql"] for it in items] + BROKEN * 4
    rng = random.Random(args.seed)
    rng.shuffle(sqls)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, sqls))
    ok, err = sum(r == "ok" for r in results), [r for r in results if r != "ok"]
    print(f"Đã chạy {len(sqls)} câu bằng user {USER}: {ok} thành công, {len(err)} lỗi "
          f"(kỳ vọng {len(BROKEN) * 4} câu lỗi có chủ đích)", flush=True)
    unexpected = [r for r in err if not any(k in r for k in ("Syntax", "Unknown", "Missing", "NOT_AN", "doesn't exist", "table"))]
    for r in unexpected[:5]:
        print("  lỗi ngoài dự kiến:", r)
    admin.command("SYSTEM FLUSH LOGS")
    n = admin.query("SELECT count() FROM system.query_log WHERE user = {u:String} AND type != 'QueryStart'",
                    parameters={"u": USER}).result_rows[0][0]
    print(f"system.query_log hiện có {n} bản ghi của {USER}")


if __name__ == "__main__":
    main()
