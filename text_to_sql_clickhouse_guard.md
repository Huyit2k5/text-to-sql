# Text-to-SQL cho ClickHouse: Query Guard (bản thử nghiệm)

> Nguồn ý tưởng: tài liệu *Introduction to Query Optimization* (AIVN eDA-2026, minh họa trên PostgreSQL). Các nguyên lý được chuyển sang ClickHouse (column store, sparse primary index).

## 1. Ý tưởng

Giữ nguyên bước LLM sinh SQL, chèn thêm một lớp **guard** giữa LLM và ClickHouse:

1. **Linter (rule-based):** bắt các lỗi "tốn tài nguyên mà không đổi kết quả" như `SELECT *`, thiếu điều kiện thời gian, hàm bọc quanh cột key, `DISTINCT` thừa, `HAVING` đặt sai chỗ.
2. **EXPLAIN gate:** hỏi ClickHouse ước lượng số dòng sẽ đọc (`EXPLAIN ESTIMATE`) trước khi chạy thật; vượt ngưỡng thì từ chối.
3. **Vòng lặp phản hồi:** lỗi từ linter/gate được đưa ngược lại cho LLM để viết lại (tối đa N lần).
4. **Đo lường:** ghi `read_rows`, `read_bytes`, `memory_usage`, thời gian từ `system.query_log` để so sánh có guard và không có guard.

Nguyên tắc rút ra từ tài liệu: mỗi thay đổi phải được kiểm chứng bằng execution plan, không suy luận chỉ từ câu SQL.

## 2. Pipeline

```
Câu hỏi
  -> [Prompt = schema context + câu hỏi]
  -> LLM -> SQL
  -> [Linter]            có lỗi? -> phản hồi cho LLM viết lại
  -> [EXPLAIN ESTIMATE]  vượt ngưỡng? -> phản hồi cho LLM viết lại
  -> Chạy trên ClickHouse (gắn log_comment để đo)
  -> Trả kết quả
```

## 3. Schema context đưa vào prompt (mẫu)

LLM cần biết `PARTITION BY` và `ORDER BY` thì mới viết được điều kiện lọc đúng tiền tố key.

```sql
-- Ví dụ minh họa, thay bằng bảng thật của bạn
CREATE TABLE orders
(
    order_id     UInt64,
    customer_id  UInt64,
    order_date   Date,
    status       LowCardinality(String),
    sales_channel LowCardinality(String),
    total_amount Decimal(18, 2)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(order_date)
ORDER BY (status, order_date);
```

Kèm các ghi chú cho LLM (dạng văn bản):

- Bảng `orders` lớn (~hàng chục triệu dòng), cột thời gian là `order_date`, luôn phải có điều kiện khoảng trên cột này.
- Không dùng `SELECT *`, chỉ chọn cột cần thiết.
- Không bọc hàm lên cột trong `ORDER BY` key, trừ `toDate`, `toYear`, `toYYYYMM`, `toStartOfMonth`.
- Khi JOIN, tổng hợp bảng chi tiết về đúng grain trước, bảng nhỏ đặt bên phải.
- Truy vấn không tổng hợp phải có `LIMIT`.

## 4. Bảng rule của linter

| Mã | Mức | Rule | Lý do (theo tài liệu và ClickHouse) |
|---|---|---|---|
| R0 | error | Chỉ cho phép một câu `SELECT`/`WITH`, cấm `INSERT`, `DROP`, `ALTER`... | An toàn cho công cụ hỏi đáp |
| R1 | error | Cấm `SELECT *`, `t.*` | Projection pushdown: column store chỉ nên đọc cột cần |
| R2 | error | Bảng lớn phải có điều kiện trên cột thời gian | Cắt partition và granule sớm |
| R3 | warn | Hàm không đơn điệu bọc cột key trong `WHERE` | Sargable predicate: mất khả năng bỏ qua granule |
| R4 | warn | `DISTINCT` cùng `GROUP BY` | Bước thừa, không đổi kết quả |
| R5 | warn | `HAVING` không chứa aggregate | Nên chuyển về `WHERE` |
| R6 | warn | Không aggregate, không `GROUP BY`, không `LIMIT` | Tránh kéo về tập kết quả khổng lồ |
| R7 | info | `ORDER BY` không có `LIMIT` | Sort toàn bộ có thể không cần thiết |
| R8 | info | Có `JOIN` | Nhắc pre-aggregation, bảng nhỏ đặt bên phải |
| R9 | error | `EXPLAIN ESTIMATE` vượt ngưỡng số dòng | Cổng chặn truy vấn quá nặng |

## 5. Code (Python thuần, không import)

Lưu thành `query_guard.py`. Hai hàm `llm` và `run_query` do bạn truyền vào, nên file không cần import gì.

```python
# =====================================================================
# query_guard.py  -  Query Guard cho text-to-SQL ClickHouse
#
# Approach:
#   - Chuẩn hóa SQL (lowercase, gộp khoảng trắng) rồi kiểm tra bằng
#     thao tác chuỗi thuần, không dùng regex/parser (không import gì).
#   - check(sql): trả danh sách (mức, mã rule, thông điệp).
#   - explain_gate(): gọi EXPLAIN ESTIMATE qua hàm run_query do người
#     dùng truyền vào (run_query(sql) -> list các tuple), cộng cột rows.
#   - guarded_generate(): vòng lặp LLM -> linter -> gate -> phản hồi
#     lỗi cho LLM viết lại, tối đa max_retry lần.
#
# Edge cases:
#   - Chỉ phân tích được WHERE/HAVING đầu tiên; subquery/CTE lồng nhau
#     có thể bị bỏ sót hoặc báo nhầm (heuristic, không phải parser).
#   - Từ khóa nằm trong chuỗi ký tự hoặc comment có thể gây báo nhầm.
#   - Tên cột bị quote (`col`, "col") hoặc có alias bảng: chỉ khớp
#     nguyên từ, alias dạng t.col vẫn khớp, quote thì không.
#   - lower() làm đổi cả giá trị chuỗi, chỉ dùng để phân tích, không
#     dùng để chạy; câu SQL gốc luôn được giữ nguyên.
#   - EXPLAIN ESTIMATE chỉ có số liệu cho bảng MergeTree; nếu trả rỗng
#     thì est_rows = 0 và gate cho qua (cần xem lại thủ công).
#   - Nhiều câu lệnh (dấu ;) bị từ chối ngay ở R0.
# =====================================================================

# Cấu hình bảng lớn: cột thời gian và các cột trong ORDER BY key
TABLES = {
    "orders": {"time_col": "order_date", "key_cols": ["status", "order_date"]},
}

# Hàm đơn điệu trên cột key, vẫn tận dụng được primary key
MONOTONIC_OK = ("todate", "todate32", "todatetime", "toyear", "toyyyymm",
                "tostartofday", "tostartofmonth", "tostartofyear")

AGG = ("sum(", "count(", "avg(", "min(", "max(", "uniq(", "any(", "quantile(")

FORBIDDEN = ("insert", "drop", "alter", "truncate", "delete", "update",
             "attach", "detach", "rename", "grant", "optimize", "create")


def normalize(sql):
    s = sql.strip().rstrip(";")
    return " ".join(s.lower().split())


def is_word_char(c):
    return c.isalnum() or c == "_"


def find_word(text, w):
    """Vị trí các lần xuất hiện nguyên từ w trong text."""
    res = []
    i = text.find(w)
    while i >= 0:
        end = i + len(w)
        before_ok = i == 0 or not is_word_char(text[i - 1])
        after_ok = end >= len(text) or not is_word_char(text[end])
        if before_ok and after_ok:
            res.append(i)
        i = text.find(w, i + 1)
    return res


def get_clause(s, start_kw, end_kws):
    i = s.find(start_kw)
    if i < 0:
        return ""
    i += len(start_kw)
    j = len(s)
    for kw in end_kws:
        k = s.find(kw, i)
        if 0 <= k < j:
            j = k
    return s[i:j]


def func_before(clause, pos):
    """Tên hàm bọc trực tiếp cột tại pos. None: không bọc; "": chỉ là ngoặc."""
    if pos == 0 or clause[pos - 1] != "(":
        return None
    end = pos - 1
    k = end
    while k > 0 and is_word_char(clause[k - 1]):
        k -= 1
    return clause[k:end]


def check(sql):
    s = normalize(sql)
    issues = []

    # R0: chỉ một câu SELECT/WITH, không có lệnh ghi
    first = s.split(" ")[0] if s else ""
    if first not in ("select", "with"):
        issues.append(("error", "R0", "Chỉ cho phép câu SELECT/WITH"))
    if ";" in s:
        issues.append(("error", "R0", "Không cho phép nhiều câu lệnh"))
    for w in FORBIDDEN:
        if find_word(s, w):
            issues.append(("error", "R0", "Từ khóa bị cấm: " + w))
    if issues:
        return issues

    # R1: SELECT *
    t = s.replace("count(*)", "count(1)")
    if "select *" in t or "distinct *" in t or ".*" in t or ", *" in t:
        issues.append(("error", "R1", "Không dùng SELECT *, chỉ chọn cột cần thiết"))

    where = get_clause(s, " where ", [" group by ", " having ", " order by ", " limit "])
    tables_used = [name for name in TABLES if find_word(s, name)]

    for name in tables_used:
        cfg = TABLES[name]
        # R2: điều kiện thời gian trên bảng lớn
        if not find_word(where, cfg["time_col"]):
            issues.append(("error", "R2", "Bảng %s cần điều kiện trên cột %s" % (name, cfg["time_col"])))
        # R3: hàm không đơn điệu bọc cột key
        for col in cfg["key_cols"]:
            for pos in find_word(where, col):
                fn = func_before(where, pos)
                if fn and fn not in MONOTONIC_OK:
                    issues.append(("warn", "R3", "Hàm %s() bọc cột key %s, viết lại thành khoảng giá trị trực tiếp" % (fn, col)))

    has_group = " group by " in s
    has_agg = any(a in s for a in AGG)

    # R4: DISTINCT thừa khi đã GROUP BY
    if "distinct" in s and has_group:
        issues.append(("warn", "R4", "DISTINCT thừa khi đã có GROUP BY"))

    # R5: HAVING không chứa aggregate
    having = get_clause(s, " having ", [" order by ", " limit "])
    if having and not any(a in having for a in AGG):
        issues.append(("warn", "R5", "Điều kiện HAVING không dùng aggregate, chuyển về WHERE"))

    # R6, R7: LIMIT
    has_limit = " limit " in s
    if not has_group and not has_agg and not has_limit:
        issues.append(("warn", "R6", "Truy vấn không tổng hợp nên có LIMIT"))
    if " order by " in s and not has_limit and not has_group:
        issues.append(("info", "R7", "ORDER BY không có LIMIT, cân nhắc bỏ sort"))

    # R8: JOIN
    if " join " in s:
        issues.append(("info", "R8", "Có JOIN: tổng hợp trước về đúng grain, bảng nhỏ đặt bên phải"))

    return issues


def explain_gate(run_query, sql, max_rows):
    """run_query(sql) -> list các tuple. Cột EXPLAIN ESTIMATE:
    database, table, parts, rows, marks."""
    rows = run_query("EXPLAIN ESTIMATE " + sql.strip().rstrip(";"))
    total = 0
    for r in rows:
        total += int(r[3])
    return total <= max_rows, total


def guarded_generate(llm, run_query, question, schema_ctx, max_rows, max_retry=2):
    """llm(prompt) -> chuỗi SQL. Trả dict kết quả, ok=False nếu hết lượt sửa."""
    prompt = (schema_ctx + "\n\nCâu hỏi: " + question +
              "\nChỉ trả về đúng một câu SELECT cho ClickHouse.")
    result = None
    for attempt in range(max_retry + 1):
        sql = llm(prompt)
        issues = check(sql)
        errors = [i for i in issues if i[0] == "error"]
        est = None
        if not errors:
            ok, est = explain_gate(run_query, sql, max_rows)
            if not ok:
                errors.append(("error", "R9", "Ước lượng đọc %d dòng, vượt ngưỡng %d" % (est, max_rows)))
        result = {"sql": sql, "issues": issues + [e for e in errors if e[1] == "R9"],
                  "est_rows": est, "attempts": attempt + 1, "ok": not errors}
        if not errors:
            return result
        prompt = (prompt + "\n\nSQL trước:\n" + sql + "\nLỗi cần sửa:\n" +
                  "\n".join("- [%s] %s" % (e[1], e[2]) for e in errors) +
                  "\nHãy viết lại câu SQL.")
    return result


if __name__ == "__main__":
    demo = [
        "SELECT * FROM orders WHERE toYear(order_date) = 2026",
        "SELECT order_id FROM orders WHERE lower(status) = 'completed' AND order_date >= '2026-01-01'",
        "SELECT sales_channel, sum(total_amount) FROM orders "
        "WHERE status = 'Completed' AND order_date >= '2026-01-01' AND order_date < '2027-01-01' "
        "GROUP BY sales_channel",
        "DROP TABLE orders",
    ]
    for q in demo:
        print(q)
        for item in check(q):
            print("   ", item)
```

Cách nối vào hệ thống thật: `llm` là hàm gọi mô hình của bạn, `run_query` là hàm chạy SQL trên ClickHouse và trả về danh sách tuple.

## 6. Truy vấn kiểm tra thủ công và đo lường

Xem index có được dùng không (kiểm tra theo phiên bản ClickHouse đang chạy):

```sql
EXPLAIN indexes = 1
SELECT order_id, total_amount
FROM orders
WHERE status = 'Completed'
  AND order_date >= '2026-01-01' AND order_date < '2027-01-01';
```

Chạy thật có gắn nhãn để gom số liệu:

```sql
SELECT ...
SETTINGS log_comment = 'tts_trial_guard';
```

Lấy số liệu đo:

```sql
SYSTEM FLUSH LOGS;

SELECT
    query_id,
    query_duration_ms,
    read_rows,
    read_bytes,
    memory_usage
FROM system.query_log
WHERE type = 'QueryFinish'
  AND log_comment = 'tts_trial_guard'
ORDER BY event_time DESC
LIMIT 100;
```

Với nhóm đối chứng không có guard, dùng nhãn `tts_trial_baseline`.

## 7. Kế hoạch thử nghiệm

1. **Chuẩn bị bộ câu hỏi:** 20 đến 30 câu tiếng Việt đại diện (lọc theo thời gian, tổng hợp theo nhóm, có join, top-N), kèm SQL chuẩn do người viết để so kết quả.
2. **Baseline:** chạy toàn bộ câu hỏi qua LLM, không guard. Ghi kết quả đúng/sai, `read_rows`, `read_bytes`, `memory_usage`, thời gian.
3. **Bật linter:** chạy lại, ghi số lần bị rule bắt, số lần LLM sửa đúng sau phản hồi.
4. **Bật thêm EXPLAIN gate:** đặt ngưỡng `max_rows` sau khi đã có số liệu baseline (không đoán trước ngưỡng).
5. **So sánh:** kết quả đúng không được thấp hơn baseline; kỳ vọng `read_rows` và `memory_usage` giảm; ghi thêm số lần retry trung bình.

Ghi chú theo dõi:

- Rule nào báo nhầm nhiều thì sửa hoặc hạ mức.
- Câu hỏi nào vẫn nặng dù qua guard thì xem lại thiết kế `ORDER BY` key của bảng (đây là việc ở mức schema, không sửa được bằng linter).

## 8. Giới hạn đã biết

- Linter dùng thao tác chuỗi nên chỉ là heuristic, chưa phải parser SQL. Khi lên môi trường thật nên thay bằng parser.
- Tài liệu gốc minh họa trên PostgreSQL; hành vi optimizer của ClickHouse khác và thay đổi theo phiên bản, mọi kết luận cần được kiểm chứng bằng `EXPLAIN` trên bản đang dùng.
- `EXPLAIN ESTIMATE` chỉ ước lượng theo marks của bảng MergeTree, không thay thế việc đo số liệu thật trong `system.query_log`.
- Các khái niệm statistics/ANALYZE của PostgreSQL không có tương đương trực tiếp, nên bản thử này không đề cập.
