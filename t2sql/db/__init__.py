"""Chọn backend database theo T2SQL_DATABASE_URL.

  (trống)                         -> SQLite data/shop.db
  sqlite:///duong/dan/file.db     -> SQLite
  postgresql://user:pass@host/db  -> PostgreSQL
  clickhouse://user:pass@host:8123/db  (clickhouses:// cho HTTPS) -> ClickHouse
"""
import os

from .base import Backend, ExecResult, format_table, normalize_value


def make_backend(url: str | None = None, max_rows: int = 200, timeout_s: float | None = None) -> Backend:
    from .. import DEFAULT_DB
    url = (url if url is not None else os.environ.get("T2SQL_DATABASE_URL", "")).strip()
    timeout = timeout_s if timeout_s is not None else float(os.environ.get("T2SQL_QUERY_TIMEOUT") or 5)
    if url.startswith(("postgres://", "postgresql://")):
        from .postgres import PostgresBackend
        return PostgresBackend(url, max_rows=max_rows, timeout_s=timeout,
                               schema=os.environ.get("T2SQL_DB_SCHEMA") or "public")
    if url.startswith(("clickhouse://", "clickhouses://", "clickhouse+https://")):
        from .clickhouse import ClickHouseBackend
        return ClickHouseBackend(url, max_rows=max_rows, timeout_s=timeout)
    from .sqlite import SQLiteBackend
    path = url.removeprefix("sqlite:///") if url else DEFAULT_DB
    return SQLiteBackend(path, max_rows=max_rows, timeout_s=timeout)


__all__ = ["Backend", "ExecResult", "format_table", "make_backend", "normalize_value"]
