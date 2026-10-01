"""Chọn backend database theo T2SQL_DATABASE_URL. Chỉ hỗ trợ ClickHouse.

  clickhouse://user:pass@host:8123/database   (clickhouses:// cho HTTPS)
"""
import os

from .base import Backend, ExecResult, format_table, normalize_value

CLICKHOUSE_SCHEMES = ("clickhouse://", "clickhouses://", "clickhouse+https://")


def make_backend(url: str | None = None, max_rows: int = 200, timeout_s: float | None = None) -> Backend:
    url = (url if url is not None else os.environ.get("T2SQL_DATABASE_URL", "")).strip()
    if not url:
        raise ValueError("Chưa cấu hình database: đặt T2SQL_DATABASE_URL=clickhouse://user:pass@host:8123/database trong .env")
    if not url.startswith(CLICKHOUSE_SCHEMES):
        raise ValueError(f"Chỉ hỗ trợ ClickHouse (clickhouse://...), nhận được: {url.split('://', 1)[0]}://")
    timeout = timeout_s if timeout_s is not None else float(os.environ.get("T2SQL_QUERY_TIMEOUT") or 30)
    from .clickhouse import ClickHouseBackend
    return ClickHouseBackend(url, max_rows=max_rows, timeout_s=timeout)


__all__ = ["Backend", "ExecResult", "format_table", "make_backend", "normalize_value"]
