"""Giao diện chung cho các backend database."""
import datetime
import decimal
from dataclasses import dataclass, field


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None
    error_code: str | None = None   # sql_error | timeout | forbidden | blocked | db_unavailable | ...
    elapsed_ms: float = 0.0
    tables: set[str] = field(default_factory=set)

    @property
    def empty(self):
        return self.ok and not self.rows


def normalize_value(v):
    """Đưa giá trị về kiểu Python cơ bản để chấm điểm, hiển thị và vẽ biểu đồ giống nhau giữa các DB."""
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() and v.as_tuple().exponent >= 0 else float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, datetime.timedelta):
        return v.total_seconds() / 86400
    if isinstance(v, (bytes, memoryview)):
        return bytes(v).hex()
    return v


class Backend:
    dialect = "sqlite"            # tên dialect theo sqlglot
    display_name = "SQLite"

    def __init__(self, max_rows: int = 200, timeout_s: float = 5.0):
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def run(self, sql: str, policy=None, safe: bool = True) -> ExecResult:
        raise NotImplementedError

    def load_schema(self, docs_path: str | None = None):
        raise NotImplementedError

    def describe(self) -> str:
        return self.display_name


def format_table(res: ExecResult, max_rows: int = 20, max_width: int = 40) -> str:
    """In kết quả dạng bảng văn bản cho terminal."""
    if not res.ok:
        return f"[Lỗi] {res.error}"
    if not res.rows:
        return "Không có dữ liệu thỏa điều kiện."
    rows = res.rows[:max_rows]

    def cell(v):
        s = "NULL" if v is None else (f"{v:,.2f}" if isinstance(v, float) else str(v))
        return s if len(s) <= max_width else s[: max_width - 1] + "…"

    table = [[cell(c) for c in res.columns]] + [[cell(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(res.columns))]
    fmt = lambda r: " | ".join(v.ljust(w) for v, w in zip(r, widths))
    lines = [fmt(table[0]), "-+-".join("-" * w for w in widths)] + [fmt(r) for r in table[1:]]
    shown = len(rows)
    total_note = f"{len(res.rows)}+" if res.truncated else str(len(res.rows))
    if shown < len(res.rows) or res.truncated:
        lines.append(f"... hiển thị {shown}/{total_note} dòng")
    return "\n".join(lines)
