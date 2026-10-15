"""Backend ClickHouse (qua HTTP interface, driver clickhouse-connect).

ClickHouse không có transaction/ROLLBACK, nên an toàn dựa vào quyền của user và các setting giới hạn:
  1. Kiểm tra tĩnh (một câu lệnh, chỉ SELECT/WITH, cấm từ khóa ghi)                 -> safety.static_check
  2. Phân tích cú pháp bằng sqlglot: cấm table function (url, file, s3, remote, mysql...), bảng system.*,
     mệnh đề SETTINGS / FORMAT, hàm sleep/dictGet..., bảng/cột ngoài quyền của vai trò
  3. Trong ClickHouse: mỗi vai trò là một user riêng (t2sql_admin / t2sql_analyst / t2sql_sales) với profile
     readonly=2, join_use_nulls=1, giới hạn thời gian/bộ nhớ/số dòng
  4. Mỗi truy vấn gửi kèm max_execution_time và max_result_rows (result_overflow_mode=break)

URL: clickhouse://<tiền tố user>:<mật khẩu>@host:8123/<database>   (clickhouses:// cho HTTPS)
User thực tế = T2SQL_CH_USER_TEMPLATE (mặc định "{user}_{role}"), ví dụ t2sql -> t2sql_analyst.
Dùng một user chung cho mọi vai trò (ClickHouse có sẵn của công ty): thêm ?single_user=1 vào URL
(hoặc đặt T2SQL_CH_USER_TEMPLATE="{user}" cho mọi URL).

User chỉ có quyền đọc và không được đổi setting (readonly=1): ClickHouse từ chối max_execution_time /
max_result_rows gửi kèm truy vấn. Khi gặp lỗi đó backend chuyển sang "chế độ hạn chế": không gửi setting nữa,
đọc kết quả dạng luồng và dừng sau max_rows dòng. Giới hạn thời gian khi đó chỉ là phía client (truy vấn vẫn có thể
chạy tiếp trên server), nên cần nhờ DBA gắn profile giới hạn cho user này.
"""
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from itertools import islice
from urllib.parse import parse_qs, unquote, urlsplit

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
_READONLY_CODES = {164}                 # READONLY: ghi dữ liệu hoặc đổi setting bằng user chỉ đọc
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
def _is_readonly_setting_error(e: Exception) -> bool:
    """User readonly=1 không được đổi setting: server báo "Cannot modify '...' setting in readonly mode", còn
    clickhouse-connect tự chặn phía client với thông báo "Setting ... is readonly". Nhận diện theo nội dung, không theo
    mã lỗi: mã 164 còn xuất hiện khi user chỉ đọc cố ghi dữ liệu, mã 452 là mọi vi phạm ràng buộc setting; hai trường hợp
    đó không được bật chế độ hạn chế (bật là tắt vĩnh viễn giới hạn thời gian / số dòng của cả tiến trình)."""
    return bool(re.search(r"setting .{0,60} is readonly|cannot modify .{0,60} setting in readonly mode", str(e), re.I))


class _Restricted(Exception):
    """Dấu hiệu nội bộ: chuyển sang chế độ hạn chế."""


_CODE_RE = re.compile(r"Code: (\d+)")
_MSG_RE = re.compile(r"DB::Exception: (.*?)(?:\s*\(version [\d.]+.*|\s*$)", re.S)


def ast_check(sql: str, policy: Policy, dialect: str = "clickhouse") -> set[str]:
    if _CH_FORBIDDEN.search(sql):
        raise SafetyError("Câu SQL chứa lệnh quản trị / ghi file bị cấm.", "forbidden_keyword")
    return check_ast(sql, policy, dialect, CH_RULES)


_READ_TIMEOUT_RE = re.compile(r"read timed out|read timeout|ReadTimeout", re.I)    # không gồm "connect timeout"


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
        single = parse_qs(u.query).get("single_user", ["0"])[0].lower() in ("1", "true", "yes")
        self.user_template = "{user}" if single else (os.environ.get("T2SQL_CH_USER_TEMPLATE") or "{user}_{role}")
        self.restricted = False      # True: user không được đổi setting (readonly=1), xem docstring
        self._clients = {}
        self._lock = threading.Lock()

    def describe(self):
        return f"ClickHouse {self.user_prefix}@{self.host}:{self.port}/{self.database}"

    def username(self, policy: Policy) -> str:
        return self.user_template.format(user=self.user_prefix, role=policy.name)

    def _client_restricted(self, policy: Policy):
        """Client riêng cho chế độ hạn chế: không gửi được max_execution_time nên ép thời gian chờ phía client
        (chờ dữ liệu quá timeout_s thì ngắt kết nối, server hủy truy vấn khi không ghi được kết quả)."""
        user = self.username(policy)
        with self._lock:
            key = (user, "restricted")
            if key not in self._clients:
                import clickhouse_connect
                self._clients[key] = clickhouse_connect.get_client(
                    host=self.host, port=self.port, username=user, password=self.password,
                    database=self.database, secure=self.secure, connect_timeout=10,
                    send_receive_timeout=max(1, int(self.timeout_s)), autogenerate_session_id=False)
            return self._clients[key]

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
    def _schema_signature(self) -> str:
        """Băm (bảng, cột, kiểu) hiện có: thêm / xóa / đổi kiểu cột thì khóa đệm đổi, không phải chờ hết hạn."""
        import hashlib
        rows = self._client(POLICIES["admin"]).query(
            "SELECT table, name, type FROM system.columns WHERE database = {db:String} ORDER BY table, position",
            parameters={"db": self.database}).result_rows
        return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()[:16]

    def load_schema(self, docs_path=None, n_samples: int = 3):
        """Như _load_schema nhưng lưu đệm vào .cache/ (mặc định 24 giờ, T2SQL_SCHEMA_CACHE_HOURS=0 để tắt):
        database lớn có hàng trăm cột nên lấy giá trị mẫu mất cả chục giây mỗi lần khởi động.
        Khóa đệm có chữ ký cấu trúc bảng; giá trị mẫu (lấy từ dữ liệu thật) nằm dạng văn bản thường trong .cache/."""
        import hashlib
        import json

        from ..schema import Column, Schema, Table
        hours = float(os.environ.get("T2SQL_SCHEMA_CACHE_HOURS", "24") or 0)
        if hours <= 0:
            return self._load_schema(docs_path, n_samples)
        docs_text = ""
        if docs_path:
            with open(docs_path, encoding="utf-8") as f:
                docs_text = f.read()
        try:
            signature = self._schema_signature()
        except Exception:
            return self._load_schema(docs_path, n_samples)          # không đọc được cấu trúc bảng: không dùng đệm
        key = hashlib.sha256(f"{self.host}:{self.port}/{self.database}|{n_samples}|{signature}|{docs_text}".encode()).hexdigest()[:20]
        path = os.path.join(os.environ.get("T2SQL_CACHE_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", ".cache"),
                            f"schema_{self.database}_{key}.json")
        try:
            if time.time() - os.path.getmtime(path) < hours * 3600:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                tables = {n: Table(n, [Column(**c) for c in t["columns"]], t["description"], t["row_count"], t["keywords"])
                          for n, t in data["tables"].items()}
                return Schema(tables, data["business_rules"], data["concepts"])
        except (OSError, ValueError, KeyError, TypeError):
            pass                                  # chưa có đệm / đệm hỏng: nạp lại từ database
        schema = self._load_schema(docs_path, n_samples)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = {"tables": {n: {"description": t.description, "row_count": t.row_count, "keywords": t.keywords,
                                   "columns": [vars(c) for c in t.columns]} for n, t in schema.tables.items()},
                    "business_rules": schema.business_rules, "concepts": schema.concepts}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            os.replace(tmp, path)
        except OSError:
            pass
        return schema

    def _load_schema(self, docs_path=None, n_samples: int = 3):
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
        skip = set(docs.get("exclude_tables", []))       # ví dụ bảng *_local của bảng Distributed
        client = self._client(POLICIES["admin"])
        p = {"db": self.database}
        meta = {r[0]: r[1:] for r in client.query(
            "SELECT name, comment, coalesce(total_rows, 0) FROM system.tables "
            "WHERE database = {db:String} AND NOT is_temporary", parameters=p).result_rows}
        cols = client.query(
            "SELECT table, name, type, comment, is_in_primary_key FROM system.columns "
            "WHERE database = {db:String} ORDER BY table, position", parameters=p).result_rows
        tables, to_sample = {}, []
        for tname, cname, ctype, ccomment, in_pk in cols:
            if tname in skip:
                continue
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
                to_sample.append((tname, col))
            tables[tname].columns.append(col)
        def sample(item):
            tname, col = item
            q = (f"SELECT DISTINCT `{col.name}` FROM (SELECT `{col.name}` FROM `{self.database}`.`{tname}` "
                 f"WHERE `{col.name}` IS NOT NULL LIMIT 5000) LIMIT 50")
            vals = [normalize_value(r[0]) for r in client.query(q).result_rows]
            col.samples = [v for v in vals if not (isinstance(v, str) and len(v) > MAX_SAMPLE_LEN)][:n_samples]

        with ThreadPoolExecutor(max_workers=8) as pool:          # nhiều cột: lấy mẫu song song
            list(pool.map(sample, to_sample))
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
                                              settings={} if self.restricted else {"max_execution_time": 10}).result_rows
        except Exception:
            return None
        per_table = {}
        for r in rows:            # database, table, parts, rows, marks
            per_table[r[1]] = per_table.get(r[1], 0) + int(r[3])
        return sum(per_table.values()), per_table

    def _run_streaming(self, client, sql_text: str):
        """Chạy không kèm setting và chỉ lấy tối đa max_rows + 1 dòng đầu."""
        with client.query_rows_stream(sql_text) as stream:
            cols = list(stream.source.column_names)
            return cols, list(islice(stream, self.max_rows + 1))

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
            who = policy if safe else POLICIES["admin"]
            client = self._client(who)
            sql_text = sql_text.rstrip("; "+chr(10))
            try:
                if self.restricted:
                    raise _Restricted()
                res = client.query(sql_text, settings=settings)
                cols, rows = list(res.column_names), res.result_rows
            except _Restricted:
                cols, rows = self._run_streaming(self._client_restricted(who), sql_text)
            except Exception as e:
                if not _is_readonly_setting_error(e):
                    raise
                self.restricted = True
                cols, rows = self._run_streaming(self._client_restricted(who), sql_text)
        except Exception as e:  # clickhouse_connect.driver.exceptions.*
            from clickhouse_connect.driver.exceptions import OperationalError
            code, msg = _error_parts(e)
            if self.restricted and code is None and re.search(r"timed? ?out", str(e), re.I):
                return ExecResult(False, error=f"Truy vấn vượt quá {self.timeout_s:g}s và đã bị dừng.",
                                  error_code="timeout", elapsed_ms=_ms(t0))
            if code is None and _READ_TIMEOUT_RE.search(str(e)):
                # Chờ kết quả quá lâu (không phải lỗi kết nối): ứng dụng ngừng chờ, nhưng server có thể còn chạy
                # truy vấn thêm một lúc nếu tài khoản không có giới hạn thời gian phía server.
                return ExecResult(False, error=f"Truy vấn quá lâu (chờ hơn {self.timeout_s:g}s) nên ứng dụng đã ngừng chờ.",
                                  error_code="timeout", elapsed_ms=_ms(t0))
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
