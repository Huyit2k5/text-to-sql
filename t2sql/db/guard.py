"""Kiểm tra SQL bằng cây cú pháp (sqlglot), dùng chung cho các backend client-server.

Lớp này chạy trước khi gửi SQL tới database, để chặn sớm và báo lỗi dễ hiểu. Database vẫn là lớp bảo vệ
cuối cùng (quyền GRANT, chế độ chỉ đọc), nên nếu sqlglot không phân tích được câu lệnh thì bỏ qua.
"""
from dataclasses import dataclass, field

from ..safety import Policy, SafetyError


@dataclass(frozen=True)
class GuardRules:
    blocked_func_prefixes: tuple[str, ...] = ()
    blocked_funcs: frozenset[str] = frozenset()
    system_schemas: frozenset[str] = frozenset()
    system_table_prefixes: tuple[str, ...] = ()
    allow_table_functions: bool = True       # FROM url(...), FROM generate_series(...)
    blocked_clauses: dict = field(default_factory=dict)   # tên arg của exp.Select -> thông báo


def check_ast(sql: str, policy: Policy, dialect: str, rules: GuardRules) -> set[str]:
    """Trả về tập bảng được đọc; raise SafetyError nếu vi phạm."""
    import sqlglot
    from sqlglot import exp
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return set()
    if not isinstance(tree, exp.Query):
        raise SafetyError("Chỉ cho phép câu lệnh SELECT (chỉ đọc).", "not_select")
    if tree.find(exp.Into):
        raise SafetyError("Không được dùng SELECT ... INTO (tạo bảng mới).", "forbidden_keyword")
    if tree.find(exp.Lock):
        raise SafetyError("Không được khóa dòng (FOR UPDATE / FOR SHARE).", "forbidden_keyword")
    for sel in tree.find_all(exp.Select):
        for arg, msg in rules.blocked_clauses.items():
            if sel.args.get(arg):
                raise SafetyError(msg, "forbidden_keyword")

    if not rules.allow_table_functions:
        for t in tree.find_all(exp.Table):
            if isinstance(t.this, exp.Func):
                fname = (t.this.name if isinstance(t.this, exp.Anonymous) else t.this.sql_name()).lower()
                raise SafetyError(f"Không được dùng table function {fname}() (đọc file / URL / DB khác).",
                                  "forbidden_function")
    for fn in tree.find_all(exp.Func):
        name = (fn.sql_name() if not isinstance(fn, exp.Anonymous) else fn.name).lower()
        if name.startswith(rules.blocked_func_prefixes) or name in rules.blocked_funcs:
            raise SafetyError(f"Không được gọi hàm hệ thống {name}().", "forbidden_function")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = set()
    for t in tree.find_all(exp.Table):
        name, schema = t.name.lower(), (t.db or "").lower()
        if not name or (name in ctes and not schema):
            continue
        if schema in rules.system_schemas or name.startswith(rules.system_table_prefixes):
            raise SafetyError("Không được truy vấn bảng hệ thống.", "forbidden")
        tables.add(name)
    if policy.allowed_tables is not None:
        bad = tables - policy.allowed_tables
        if bad:
            raise SafetyError(f"Vai trò {policy.name} không được đọc bảng: {', '.join(sorted(bad))}.", "forbidden")
    denied = {c for t, c in policy.denied_columns if t in tables}
    if denied:
        used = {c.name.lower() for c in tree.find_all(exp.Column)}
        # chỉ tính `*` / `c.*` trong danh sách cột của SELECT, không tính COUNT(*)
        star = any(isinstance(p, exp.Star) or (isinstance(p, exp.Column) and isinstance(p.this, exp.Star))
                   for sel in tree.find_all(exp.Select) for p in sel.expressions)
        hit = used & denied
        if hit or star:
            cols = ", ".join(sorted(hit)) if hit else "* (bao gồm " + ", ".join(sorted(denied)) + ")"
            raise SafetyError(f"Vai trò {policy.name} không được đọc cột: {cols}.", "forbidden")
    return tables
