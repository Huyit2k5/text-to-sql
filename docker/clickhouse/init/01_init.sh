#!/bin/bash
# Khởi tạo ClickHouse cho Text-to-SQL: bảng + dữ liệu mẫu + user/role chỉ đọc.
# Chạy tự động khi container khởi tạo thư mục dữ liệu mới. Chạy lại được (idempotent):
# bảng tạo IF NOT EXISTS, dữ liệu chỉ nạp khi bảng orders còn trống, user/role OR REPLACE.
set -eu

ch() { clickhouse client --user "${CLICKHOUSE_USER:-default}" --password "${CLICKHOUSE_PASSWORD:-}" "$@"; }

ch --multiquery < /t2sql/sql/01_schema.sql
if [ "$(ch --query 'SELECT count() FROM shop.orders')" = "0" ]; then
    ch --multiquery < /t2sql/sql/02_data.sql
fi
: "${T2SQL_CH_PASSWORD:?Đặt T2SQL_CH_PASSWORD trong .env}"
sed "s/__T2SQL_CH_PASSWORD__/${T2SQL_CH_PASSWORD}/g" /t2sql/sql/03_access.sql | ch --multiquery
echo "t2sql: ClickHouse đã sẵn sàng ($(ch --query 'SELECT count() FROM shop.orders') đơn hàng)"
