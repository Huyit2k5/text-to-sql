"""Lớp an toàn (Mức 3): chỉ SELECT, một câu lệnh, phân quyền bảng/cột, che dữ liệu nhạy cảm."""
import re
import sqlite3
from dataclasses import dataclass, field

from .sql_utils import split_statements, strip_comments_and_strings

# Câu lệnh phải bắt đầu bằng SELECT/WITH, nên danh sách này chủ yếu bắt lệnh ghi lồng trong CTE
# (ví dụ WITH x AS (DELETE ... RETURNING *) SELECT ...). REPLACE chỉ cấm dạng "REPLACE INTO",
# vì replace() là hàm xử lý chuỗi hợp lệ.
FORBIDDEN = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", r"REPLACE\s+INTO", "TRUNCATE", "MERGE",
             "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "ANALYZE", "GRANT", "REVOKE", "REFRESH"]
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.I)
# Hàm có thể dùng để tấn công/gây tốn tài nguyên trong SQLite.
FORBIDDEN_FUNCS = {"load_extension", "randomblob", "zeroblob", "readfile", "writefile", "fts3_tokenizer"}

WRITE_INTENT = re.compile(
    r"\b(xóa|xoá|sửa|cập nhật|thêm mới|chèn|đổi tên|tạo bảng|delete|update|insert|drop|alter|truncate)\b", re.I)


class SafetyError(Exception):
    """SQL bị chặn trước hoặc trong lúc chạy. `reason` là thông báo hiển thị cho người dùng."""

    def __init__(self, reason: str, code: str = "blocked"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass
class Policy:
    """Phân quyền cho một vai trò. allowed_tables=None nghĩa là mọi bảng."""
    name: str = "admin"
    allowed_tables: set[str] | None = None
    denied_columns: set[tuple[str, str]] = field(default_factory=set)
    mask_pii: bool = False
    db_role: str | None = None      # role Postgres chỉ đọc tương ứng (GRANT khớp với policy này)

    def __post_init__(self):
        self.db_role = self.db_role or f"t2sql_{self.name}_ro"

    def describe(self) -> str:
        t = "mọi bảng" if self.allowed_tables is None else ", ".join(sorted(self.allowed_tables))
        d = ", ".join(f"{a}.{b}" for a, b in sorted(self.denied_columns)) or "không"
        return f"vai trò {self.name}: được đọc {t}; cột bị chặn: {d}"


PII_COLUMNS = {("customers", "email"), ("customers", "phone")}

POLICIES = {
    "admin": Policy("admin"),
    "analyst": Policy("analyst", denied_columns=set(PII_COLUMNS), mask_pii=True),
    "sales": Policy("sales", allowed_tables={"orders", "order_items", "products", "suppliers"},
                    mask_pii=True),
}


def static_check(sql: str) -> str:
    """Kiểm tra tĩnh. Trả về SQL đã chuẩn hóa hoặc raise SafetyError."""
    if not sql or not sql.strip():
        raise SafetyError("Không có câu SQL nào để chạy.", "empty")
    stmts = split_statements(sql)
    if len(stmts) != 1:
        raise SafetyError("Chỉ chấp nhận đúng một câu lệnh SQL.", "multi_statement")
    stmt = stmts[0]
    bare = strip_comments_and_strings(stmt)
    first = re.match(r"\s*\(*\s*(\w+)", bare)
    if not first or first.group(1).upper() not in ("SELECT", "WITH"):
        raise SafetyError("Chỉ cho phép câu lệnh SELECT (chỉ đọc).", "not_select")
    m = _FORBIDDEN_RE.search(bare)
    if m:
        raise SafetyError(f"Câu SQL chứa từ khóa bị cấm: {m.group(1).split()[0].upper()}.", "forbidden_keyword")
    return stmt


def make_authorizer(policy: Policy, seen_tables: set):
    """Authorizer của SQLite: được gọi lúc biên dịch câu lệnh, cho biết chính xác bảng/cột nào bị đọc."""
    allowed_actions = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                       getattr(sqlite3, "SQLITE_RECURSIVE", 33)}

    def auth(action, arg1, arg2, dbname, source):
        if action not in allowed_actions:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_DENY if (arg2 or "").lower() in FORBIDDEN_FUNCS else sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table, col = arg1, arg2
            if table and table.startswith("sqlite_"):
                return sqlite3.SQLITE_DENY
            if table:
                seen_tables.add(table)
                if policy.allowed_tables is not None and table not in policy.allowed_tables:
                    return sqlite3.SQLITE_DENY
                if (table, col) in policy.denied_columns:
                    return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return auth


_EMAIL = re.compile(r"^([^@\s]{1,2})[^@\s]*(@.+)$")
_PHONE = re.compile(r"^\+?\d[\d\s.-]{7,}\d$")


def mask_value(v):
    if isinstance(v, str):
        if _EMAIL.match(v):
            return _EMAIL.sub(r"\1***\2", v)
        if _PHONE.match(v):
            return v[:3] + "*" * (len(v) - 5) + v[-2:]
    return v


def is_write_request(question: str) -> bool:
    return bool(WRITE_INTENT.search(question or ""))
