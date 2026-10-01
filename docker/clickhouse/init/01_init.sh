#!/bin/bash
# Khởi tạo ClickHouse cho Text-to-SQL: profile, role và user chỉ đọc (t2sql_admin / t2sql_analyst / t2sql_sales).
# Chạy tự động khi container khởi tạo thư mục dữ liệu mới. Chạy lại được (CREATE ... OR REPLACE).
# Dữ liệu và quyền đọc bảng do từng bộ dữ liệu cấp: python datasets/einvoice/generate.py
set -eu

ch() { clickhouse client --user "${CLICKHOUSE_USER:-default}" --password "${CLICKHOUSE_PASSWORD:-}" "$@"; }

: "${T2SQL_CH_PASSWORD:?Đặt T2SQL_CH_PASSWORD trong .env}"
sed "s/__T2SQL_CH_PASSWORD__/${T2SQL_CH_PASSWORD}/g" /t2sql/sql/03_access.sql | ch --multiquery
echo "t2sql: ClickHouse đã sẵn sàng (đã tạo user t2sql_admin / t2sql_analyst / t2sql_sales)"
