"""Backend SQLite: chế độ chỉ đọc, timeout, giới hạn số dòng, kiểm tra quyền bằng authorizer."""
import sqlite3
import time

from ..safety import POLICIES, Policy, SafetyError, make_authorizer, mask_value, static_check
from .base import Backend, ExecResult


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Mở SQLite ở chế độ chỉ đọc (mode=ro) + PRAGMA query_only làm lớp bảo vệ thứ hai."""
    uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    return con


class SQLiteBackend(Backend):
    dialect = "sqlite"
    display_name = "SQLite"

    def __init__(self, db_path: str, max_rows: int = 200, timeout_s: float = 5.0):
        super().__init__(max_rows, timeout_s)
        self.db_path = db_path

    def describe(self):
        return f"SQLite ({self.db_path})"

    def load_schema(self, docs_path=None):
        from ..schema import Schema
        con = sqlite3.connect(self.db_path)
        try:
            return Schema.from_db(con, docs_path)
        finally:
            con.close()

    def run(self, sql: str, policy: Policy | None = None, safe: bool = True) -> ExecResult:
        """safe=False chỉ dùng khi chấm điểm SQL chuẩn (tin cậy); vẫn chạy ở chế độ chỉ đọc."""
        policy = policy or POLICIES["admin"]
        t0 = time.perf_counter()
        seen = set()
        try:
            if safe:
                sql = static_check(sql)
        except SafetyError as e:
            return ExecResult(False, error=e.reason, error_code=e.code)

        con = connect_readonly(self.db_path)
        try:
            deadline = time.perf_counter() + self.timeout_s
            con.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10_000)
            if safe:
                con.set_authorizer(make_authorizer(policy, seen))
            try:
                cur = con.execute(sql)
                cols = [d[0] for d in (cur.description or [])]
                rows = cur.fetchmany(self.max_rows + 1)
            except sqlite3.DatabaseError as e:
                msg = str(e)
                if "interrupted" in msg:
                    return ExecResult(False, error=f"Truy vấn vượt quá {self.timeout_s:g}s và đã bị dừng.",
                                      error_code="timeout", elapsed_ms=_ms(t0))
                if "not authorized" in msg or "prohibited" in msg:
                    return ExecResult(False, error=f"Không có quyền truy cập dữ liệu này ({policy.describe()}).",
                                      error_code="forbidden", elapsed_ms=_ms(t0), tables=seen)
                return ExecResult(False, error=msg, error_code="sql_error", elapsed_ms=_ms(t0))
            truncated = len(rows) > self.max_rows
            rows = rows[: self.max_rows]
            if safe and policy.mask_pii:
                rows = [tuple(mask_value(v) for v in r) for r in rows]
            return ExecResult(True, cols, rows, truncated, elapsed_ms=_ms(t0), tables=seen)
        finally:
            con.close()


def _ms(t0):
    return round((time.perf_counter() - t0) * 1000, 1)
