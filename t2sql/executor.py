"""Giữ tương thích: `Executor` là backend SQLite. Mã mới dùng `t2sql.db.make_backend`."""
from .db.base import ExecResult, format_table
from .db.sqlite import SQLiteBackend as Executor, connect_readonly

__all__ = ["ExecResult", "Executor", "connect_readonly", "format_table"]
