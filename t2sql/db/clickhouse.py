"""Backend ClickHouse (qua HTTP interface, driver clickhouse-connect).

ClickHouse không có transaction/ROLLBACK, nên an toàn dựa vào quyền của user và các setting giới hạn:
  1. Kiểm tra tĩnh (một câu lệnh, chỉ SELECT/WITH, cấm từ khóa ghi)                 -> safety.static_check
  2. Phân tích cú pháp bằng sqlglot: cấm table function (url, file, s3, remote, mysql...), bảng system.*,
     mệnh đề SETTINGS / FORMAT, hàm sleep/dictGet..., bảng/cột ngoài quyền của vai trò
  3. Trong ClickHouse: mỗi vai trò là một user riêng (t2sql_admin / t2sql_analyst / t2sql_sales) với profile
     readonly=2, join_use_nulls=1, giới hạn thời gian/bộ nhớ/số dòng (xem docker/clickhouse/sql/03_access.sql)
  4. Mỗi truy vấn gửi kèm max_execution_time và max_result_rows (result_overflow_mode=break)

URL: clickhouse://<tiền tố user>:<mật khẩu>@host:8123/<database>   (clickhouses:// cho HTTPS)
User thực tế = T2SQL_CH_USER_TEMPLATE (mặc định "{user}_{role}"), ví dụ t2sql -> t2sql_analyst.
Dùng một user chung cho mọi vai trò: đặt T2SQL_CH_USER_TEMPLATE="{user}".
"""
import os
import re
import threading
import time
from urllib.parse import unquote, urlsplit

from ..safety import POLICIES, Policy, SafetyError, mask_value, static_check
from .base import Backend, ExecResult, normalize_value
from .guard import GuardRules, check_ast

CH_RULES = GuardRules(
    blocked_func_prefixes=("dictget", "sleep"),
    blocked_funcs=frozenset({"joinget", "file", "url", "input", "executable", "getsetting", "getmacro",
                             "currentprofiles", "currentroles", "enabledprofiles", "enabledroles"}),
    system_schemas=frozenset({"system", "information_schema"}),
    allow_table_functions=False,
    blocked_clauses={"settings": "Không được tự đặt SETTINGS trong câu truy vấn.",
                     "format": "Không được dùng mệnh đề FORMAT (kết quả do ứng dụng định dạng)."},
)
# sqlglot không phân tích được các cú pháp này, nên chặn bằng regex.
_CH_FORBIDDEN = re.compile(r"\bINTO\s+OUTFILE\b|\bSYSTEM\s+\w|\bKILL\s+QUERY\b|\bOPTIMIZE\s+TABLE\b", re.I)

# Mã lỗi ClickHouse -> error_code của ExecResult.
_LIMIT_CODES = {159: "timeout", 394: "timeout", 158: "limit", 307: "limit", 241: "limit", 396: "limit"}
_FORBIDDEN_CODES = {497, 516}           # ACCESS_DENIED, AUTHENTICATION_FAILED
_READONLY_CODES = {164, 452}            # READONLY, SETTING_CONSTRAINT_VIOLATION
# Gợi ý sửa theo mã lỗi (gửi kèm lỗi cho model khi bật Config.error_hints).
ERROR_HINTS = {
    184: "Không được lồng hàm gộp trong hàm gộp (ví dụ countIf(x > min(x))). Tính giá trị gộp bên trong (min, max, "
         "count, groupArray...) ở một subquery / CTE có GROUP BY trước, rồi gộp tiếp ở truy vấn ngoài.",
    215: "Mọi cột không nằm trong hàm gộp phải có trong GROUP BY (ClickHouse không tự suy ra từ khóa chính): "
         "thêm cột đó vào GROUP BY hoặc bọc bằng any(col).",
    47: "Tên cột / alias không tồn tại ở tầng truy vấn này. Kiểm tra tên cột trong schema, alias bảng, và alias của "
        "subquery (cột của subquery chỉ gọi được qua tên đã đặt trong SELECT của subquery).",
    60: "Bảng không tồn tại: chỉ dùng các bảng có trong schema.",
    46: "Tên hàm ClickHouse phân biệt hoa thường: toYear, toMonth, toStartOfMonth, dateDiff, countIf, sumIf, "
        "uniqExact, quantileExact, formatDateTime, toTimeZone...",
    62: "Lỗi cú pháp. Lưu ý: FINAL đứng SAU alias (FROM invoices AS i FINAL); không dùng dấu chấm phẩy giữa câu.",
    386: "Các nhánh if / multiIf / CASE hoặc các giá trị trong mảng phải cùng kiểu: ép kiểu rõ ràng (toString, toFloat64, "
         "toNullable).",
    43: "Kiểu tham số không hợp lệ: ép kiểu rõ ràng (toDate, toDateTime, toFloat64, toString); dateDiff cần hai giá trị "
        "Date/DateTime; cột Nullable dùng assumeNotNull hoặc coalesce.",
    53: "Kiểu dữ liệu không khớp: ép kiểu rõ ràng; so sánh cột Enum bằng tên giá trị dạng chuỗi.",
}
_CODE_RE = re.compile(r"Code: (\d+)")
_MSG_RE = re.compile(r"DB::Exception: (.*?)(?:\s*\(version [\d.]+.*|\s*$)", re.S)


def ast_check(sql: str, policy: Policy, dialect: str = "clickhouse") -> set[str]:
    if _CH_FORBIDDEN.search(sql):
        raise SafetyError("Câu SQL chứa lệnh quản trị / ghi file bị cấm.", "forbidden_keyword")
    return check_ast(sql, policy, dialect, CH_RULES)


def _error_parts(e: Exception) -> tuple[int | None, str]:
    text = str(e)
    code = _CODE_RE.search(text)
    msg = _MSG_RE.search(text)
    message = (msg.group(1) if msg else text.strip().splitlines()[-1]).strip()
    message = re.sub(r"\s*\(([A-Z_]+)\)$", "", message)          # bỏ "(UNKNOWN_IDENTIFIER)" ở cuối
    return (int(code.group(1)) if code else None), message[:600]


class ClickHouseBackend(Backend):
    dialect = "clickhouse"
    display_name = "ClickHouse"

    def __init__(self, url: str, max_rows: int = 200, timeout_s: float = 5.0):
        super().__init__(max_rows, timeout_s)
        import clickhouse_connect  # noqa: F401  (báo lỗi sớm nếu chưa cài)
        u = urlsplit(url)
        self.secure = u.scheme in ("clickhouses", "clickhouse+https")
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or (8443 if self.secure else 8123)
        self.user_prefix = unquote(u.username or "default")
        self.password = unquote(u.password or "")
        self.database = (u.path or "/").strip("/") or "default"
        self.database_name = self.database
        self.user_template = os.environ.get("T2SQL_CH_USER_TEMPLATE") or "{user}_{role}"
        self._clients = {}
        self._lock = threading.Lock()

    def describe(self):
        return f"ClickHouse {self.user_prefix}@{self.host}:{self.port}/{self.database}"

    def username(self, policy: Policy) -> str:
        return self.user_template.format(user=self.user_prefix, role=policy.name)

    def _client(self, policy: Policy):
        user = self.username(policy)
        with self._lock:
            if user not in self._clients:
                import clickhouse_connect
                self._clients[user] = clickhouse_connect.get_client(
                    host=self.host, port=self.port, username=user, password=self.password,
                    database=self.database, secure=self.secure, connect_timeout=10,
                    send_receive_timeout=max(30, int(self.timeout_s) + 15),
                    autogenerate_session_id=False)      # không dùng session: cho phép chạy song song
            return self._clients[user]

    # ------------------------------------------------------------------ schema
    def load_schema(self, docs_path=None, n_samples: int = 3):
        """Đọc schema qua system.columns / system.tables (chỉ thấy bảng user admin được GRANT).
        Mô tả lấy từ docs JSON, thiếu thì lấy COMMENT. Khóa ngoại lấy từ mục "relations" của docs."""
        import json

        from ..schema import MAX_SAMPLE_LEN, NO_SAMPLE_COLUMNS, Column, Schema, Table
        docs = {}
        if docs_path:
            with open(docs_path, encoding="utf-8") as f:
                docs = json.load(f)
        tdocs, rel = docs.get("tables", {}), docs.get("relations", {})
        no_sample = NO_SAMPLE_COLUMNS | {tuple(c) for c in docs.get("no_sample_columns", [])}
        client = self._client(POLICIES["admin"])
        p = {"db": self.database}
        meta = {r[0]: r[1:] for r in client.query(
            "SELECT name, comment, coalesce(total_rows, 0) FROM system.tables "
            "WHERE database = {db:String} AND NOT is_temporary", parameters=p).result_rows}
        cols = client.query(
            "SELECT table, name, type, comment, is_in_primary_key FROM system.columns "
            "WHERE database = {db:String} ORDER BY table, position", parameters=p).result_rows
        tables = {}
        for tname, cname, ctype, ccomment, in_pk in cols:
            tdoc = tdocs.get(tname, {})
            if tname not in tables:
                tcomment, nrows = meta.get(tname, ("", 0))
                tables[tname] = Table(tname, [], tdoc.get("description") or tcomment or "", int(nrows),
                                      tdoc.get("keywords", ""))
            fk = rel.get(f"{tname}.{cname}")
            # Khóa sắp xếp của MergeTree không bảo đảm duy nhất; chỉ coi cột *_id (không phải khóa ngoại) là khóa chính.
            pk = bool(in_pk) and cname.endswith("_id") and not fk
            col = Column(cname, ctype, pk, fk, tdoc.get("columns", {}).get(cname) or ccomment or "")
            if (tname, cname) not in no_sample and not pk and not fk and not ctype.startswith("AggregateFunction"):
                q = (f"SELECT DISTINCT `{cname}` FROM (SELECT `{cname}` FROM `{self.database}`.`{tname}` "
                     f"WHERE `{cname}` IS NOT NULL LIMIT 5000) LIMIT 50")
                vals = [normalize_value(r[0]) for r in client.query(q).result_rows]
                col.samples = [v for v in vals if not (isinstance(v, str) and len(v) > MAX_SAMPLE_LEN)][:n_samples]
            tables[tname].columns.append(col)
        return Schema(tables, docs.get("business_rules", []), docs.get("concepts", {}))

    # ------------------------------------------------------------------ ước lượng chi phí
    def estimate_rows(self, sql_text: str, policy: Policy | None = None):
        """EXPLAIN ESTIMATE: số dòng dự kiến đọc theo bảng (từ số granule), không chạy truy vấn.
        None khi SQL không qua được kiểm tra an toàn hoặc EXPLAIN lỗi (để bước chạy thật báo lỗi như bình thường)."""
        policy = policy or POLICIES["admin"]
        try:
            sql_text = static_check(sql_text)
            ast_check(sql_text, policy, self.dialect)
            rows = self._client(policy).query("EXPLAIN ESTIMATE " + sql_text.rstrip("; \n"),
                                              settings={"max_execution_time": 10}).result_rows
        except Exception:
            return None
        per_table = {}
        for r in rows:            # database, table, parts, rows, marks
            per_table[r[1]] = per_table.get(r[1], 0) + int(r[3])
        return sum(per_table.values()), per_table

    # ------------------------------------------------------------------ run
    def run(self, sql_text: str, policy: Policy | None = None, safe: bool = True,
            log_comment: str = "t2sql") -> ExecResult:
        policy = policy or POLICIES["admin"]
        t0 = time.perf_counter()
        tables = set()
        try:
            if safe:
                sql_text = static_check(sql_text)
                tables = ast_check(sql_text, policy, self.dialect)
        except SafetyError as e:
            return ExecResult(False, error=e.reason, error_code=e.code, elapsed_ms=_ms(t0))

        settings = {"max_execution_time": int(max(1, self.timeout_s)),
                    "max_result_rows": self.max_rows + 1, "result_overflow_mode": "break",
                    "log_comment": log_comment[:200]}
        try:
            res = self._client(policy if safe else POLICIES["admin"]).query(sql_text.rstrip("; \n"),
                                                                           settings=settings)
            cols, rows = list(res.column_names), res.result_rows
        except Exception as e:  # clickhouse_connect.driver.exceptions.*
            from clickhouse_connect.driver.exceptions import OperationalError
            code, msg = _error_parts(e)
            if isinstance(e, OperationalError) and code is None:
                return ExecResult(False, error=f"Không kết nối được ClickHouse: {msg}",
                                  error_code="db_unavailable", elapsed_ms=_ms(t0))
            if code in _LIMIT_CODES:
                kind = _LIMIT_CODES[code]
                text = (f"Truy vấn vượt quá {self.timeout_s:g}s và đã bị dừng." if kind == "timeout"
                        else f"Truy vấn vượt giới hạn tài nguyên (đọc quá nhiều dòng / bộ nhớ): {msg}")
                return ExecResult(False, error=text, error_code="timeout", elapsed_ms=_ms(t0))
            if code in _FORBIDDEN_CODES:
                return ExecResult(False, error=f"Không có quyền truy cập dữ liệu này ({policy.describe()}): {msg}",
                                  error_code="forbidden", elapsed_ms=_ms(t0), tables=tables)
            if code in _READONLY_CODES:
                return ExecResult(False, error="Chỉ cho phép truy vấn đọc dữ liệu.", error_code="blocked",
                                  elapsed_ms=_ms(t0))
            return ExecResult(False, error=msg, error_code="sql_error", elapsed_ms=_ms(t0), hint=ERROR_HINTS.get(code))

        truncated = len(rows) > self.max_rows
        rows = [tuple(normalize_value(v) for v in r) for r in rows[: self.max_rows]]
        if safe and policy.mask_pii:
            rows = [tuple(mask_value(v) for v in r) for r in rows]
        return ExecResult(True, cols, rows, truncated, elapsed_ms=_ms(t0), tables=tables)


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 1)
