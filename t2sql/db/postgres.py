"""Backend PostgreSQL.

Nhiều lớp bảo vệ, lớp sau không phụ thuộc lớp trước:
  1. Kiểm tra tĩnh (một câu lệnh, chỉ SELECT/WITH, cấm từ khóa ghi)           -> safety.static_check
  2. Phân tích cú pháp bằng sqlglot: cấm SELECT INTO, FOR UPDATE, hàm hệ thống (pg_*),
     bảng hệ thống, bảng/cột ngoài quyền của vai trò (để báo lỗi dễ hiểu)
  3. Trong Postgres: transaction READ ONLY, `SET LOCAL ROLE` sang role chỉ đọc của vai trò
     (quyền GRANT theo bảng/cột, xem docker/postgres/init/03_roles.sh), statement_timeout
  4. Server-side cursor: chỉ kéo về tối đa max_rows + 1 dòng
"""
import time

from ..safety import POLICIES, Policy, SafetyError, mask_value, static_check
from .base import Backend, ExecResult, normalize_value
from .guard import GuardRules, check_ast

# Hàm nguy hiểm / không cần cho truy vấn phân tích.
BLOCKED_FUNC_PREFIXES = ("pg_", "lo_", "dblink", "txid_")
BLOCKED_FUNCS = {"set_config", "current_setting", "query_to_xml", "query_to_xml_and_xmlschema",
                 "table_to_xml", "database_to_xml", "cursor_to_xml", "version", "inet_server_addr"}
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}


PG_RULES = GuardRules(BLOCKED_FUNC_PREFIXES, frozenset(BLOCKED_FUNCS), frozenset(SYSTEM_SCHEMAS), ("pg_",))


def ast_check(sql: str, policy: Policy, dialect: str = "postgres") -> set[str]:
    """Kiểm tra bằng cây cú pháp. Trả về tập bảng được đọc; raise SafetyError nếu vi phạm.
    Nếu sqlglot không phân tích được câu lệnh thì bỏ qua (Postgres vẫn thực thi quyền ở lớp 3)."""
    return check_ast(sql, policy, dialect, PG_RULES)


class PostgresBackend(Backend):
    dialect = "postgres"
    display_name = "PostgreSQL"

    def __init__(self, url: str, max_rows: int = 200, timeout_s: float = 5.0, schema: str = "public"):
        super().__init__(max_rows, timeout_s)
        import psycopg  # noqa: F401  (báo lỗi sớm nếu chưa cài)
        self.url = url
        import psycopg
        self.database_name = psycopg.conninfo.conninfo_to_dict(url).get("dbname")
        self.schema_name = schema

    def describe(self):
        import psycopg
        info = psycopg.conninfo.conninfo_to_dict(self.url)
        return f"PostgreSQL {info.get('user', '')}@{info.get('host', '')}:{info.get('port', 5432)}/{info.get('dbname', '')}"

    def _connect(self):
        import psycopg
        conn = psycopg.connect(self.url, connect_timeout=10, application_name="text-to-sql")
        conn.read_only = True
        return conn

    @staticmethod
    def _set_role(conn, policy: Policy):
        from psycopg import sql
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(policy.db_role)))

    # ------------------------------------------------------------------ schema
    def load_schema(self, docs_path=None, n_samples: int = 3):
        """Đọc schema qua pg_catalog dưới role admin chỉ đọc. Mô tả lấy từ docs JSON, thiếu thì lấy COMMENT ON."""
        import json

        from psycopg import sql

        from ..schema import MAX_SAMPLE_LEN, NO_SAMPLE_COLUMNS, Column, Schema, Table
        docs = {}
        if docs_path:
            with open(docs_path, encoding="utf-8") as f:
                docs = json.load(f)
        tdocs = docs.get("tables", {})
        with self._connect() as conn:
            self._set_role(conn, POLICIES["admin"])
            cols = conn.execute("""
                SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
                       col_description(c.oid, a.attnum), obj_description(c.oid, 'pg_class'),
                       GREATEST(c.reltuples, 0)::bigint
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'm', 'p')
                ORDER BY c.relname, a.attnum""", (self.schema_name,)).fetchall()
            cons = conn.execute("""
                SELECT c.contype, rel.relname, a.attname, frel.relname, fa.attname
                FROM pg_constraint c
                JOIN pg_class rel ON rel.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = rel.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                LEFT JOIN pg_class frel ON frel.oid = c.confrelid
                LEFT JOIN pg_attribute fa ON fa.attrelid = c.confrelid AND fa.attnum = c.confkey[1]
                WHERE n.nspname = %s AND c.contype IN ('p', 'f') AND cardinality(c.conkey) = 1""",
                                 (self.schema_name,)).fetchall()
            pks = {(t, c) for k, t, c, _, _ in cons if k == "p"}
            fks = {(t, c): f"{ft}.{fc}" for k, t, c, ft, fc in cons if k == "f"}

            tables = {}
            for tname, cname, ctype, ccomment, tcomment, reltuples in cols:
                tdoc = tdocs.get(tname, {})
                if tname not in tables:
                    tables[tname] = Table(tname, [], tdoc.get("description") or tcomment or "", int(reltuples),
                                          tdoc.get("keywords", ""))
                col = Column(cname, ctype, (tname, cname) in pks, fks.get((tname, cname)),
                             tdoc.get("columns", {}).get(cname) or ccomment or "")
                if (tname, cname) not in NO_SAMPLE_COLUMNS and not col.pk and not col.fk:
                    q = sql.SQL("SELECT DISTINCT {c} FROM (SELECT {c} FROM {s}.{t} WHERE {c} IS NOT NULL LIMIT 5000) x "
                                "LIMIT 50").format(c=sql.Identifier(cname), s=sql.Identifier(self.schema_name),
                                                   t=sql.Identifier(tname))
                    vals = [normalize_value(r[0]) for r in conn.execute(q).fetchall()]
                    col.samples = [v for v in vals if not (isinstance(v, str) and len(v) > MAX_SAMPLE_LEN)][:n_samples]
                tables[tname].columns.append(col)
            conn.rollback()
        return Schema(tables, docs.get("business_rules", []), docs.get("concepts", {}))

    # ------------------------------------------------------------------ run
    def run(self, sql_text: str, policy: Policy | None = None, safe: bool = True) -> ExecResult:
        import psycopg
        from psycopg import errors
        policy = policy or POLICIES["admin"]
        t0 = time.perf_counter()
        tables = set()
        try:
            if safe:
                sql_text = static_check(sql_text)
                tables = ast_check(sql_text, policy, self.dialect)
        except SafetyError as e:
            return ExecResult(False, error=e.reason, error_code=e.code, elapsed_ms=_ms(t0))

        try:
            with self._connect() as conn:
                self._set_role(conn, policy if safe else POLICIES["admin"])
                conn.execute("SELECT set_config('statement_timeout', %s, true)", (str(int(self.timeout_s * 1000)),))
                with conn.cursor(name="t2sql_query") as cur:   # server-side cursor
                    cur.execute(sql_text)
                    rows = cur.fetchmany(self.max_rows + 1)
                    cols = [d.name for d in (cur.description or [])]
                conn.rollback()
        except errors.QueryCanceled:
            return ExecResult(False, error=f"Truy vấn vượt quá {self.timeout_s:g}s và đã bị dừng.",
                              error_code="timeout", elapsed_ms=_ms(t0))
        except errors.InsufficientPrivilege as e:
            return ExecResult(False, error=f"Không có quyền truy cập dữ liệu này ({policy.describe()}): "
                              f"{e.diag.message_primary}", error_code="forbidden", elapsed_ms=_ms(t0), tables=tables)
        except errors.ReadOnlySqlTransaction:
            return ExecResult(False, error="Chỉ cho phép truy vấn đọc dữ liệu.", error_code="blocked", elapsed_ms=_ms(t0))
        except psycopg.OperationalError as e:
            return ExecResult(False, error=f"Không kết nối được database: {str(e).splitlines()[0]}",
                              error_code="db_unavailable", elapsed_ms=_ms(t0))
        except psycopg.Error as e:
            msg = e.diag.message_primary or str(e)
            if e.diag.message_hint:
                msg += f" (gợi ý: {e.diag.message_hint})"
            return ExecResult(False, error=msg, error_code="sql_error", elapsed_ms=_ms(t0))

        truncated = len(rows) > self.max_rows
        rows = [tuple(normalize_value(v) for v in r) for r in rows[: self.max_rows]]
        if safe and policy.mask_pii:
            rows = [tuple(mask_value(v) for v in r) for r in rows]
        return ExecResult(True, cols, rows, truncated, elapsed_ms=_ms(t0), tables=tables)


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 1)
