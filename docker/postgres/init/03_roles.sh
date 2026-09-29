#!/bin/sh
# Tạo role cho Text-to-SQL. Chạy tự động một lần khi Postgres khởi tạo volume mới.
# Áp dụng cho database thật: xem docker/postgres/roles.sql.
#
#   t2sql_app          : LOGIN, NOINHERIT -> không có quyền gì cho tới khi SET ROLE sang một role dưới đây.
#   t2sql_admin_ro     : SELECT mọi bảng
#   t2sql_analyst_ro   : SELECT mọi bảng, riêng customers không có email/phone (GRANT theo cột)
#   t2sql_sales_ro     : SELECT orders, order_items, products, suppliers
# Mọi phiên của t2sql_app mặc định read-only và có statement_timeout.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_password="$T2SQL_APP_PASSWORD" -v dbname="$POSTGRES_DB" <<'EOSQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;

CREATE ROLE t2sql_admin_ro NOLOGIN;
CREATE ROLE t2sql_analyst_ro NOLOGIN;
CREATE ROLE t2sql_sales_ro NOLOGIN;

GRANT CONNECT ON DATABASE :"dbname" TO t2sql_admin_ro, t2sql_analyst_ro, t2sql_sales_ro;
GRANT USAGE ON SCHEMA public TO t2sql_admin_ro, t2sql_analyst_ro, t2sql_sales_ro;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO t2sql_admin_ro;

GRANT SELECT ON suppliers, products, orders, order_items, reviews TO t2sql_analyst_ro;
GRANT SELECT (customer_id, name, city, segment, created_at) ON customers TO t2sql_analyst_ro;

GRANT SELECT ON orders, order_items, products, suppliers TO t2sql_sales_ro;

CREATE ROLE t2sql_app LOGIN NOINHERIT PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"dbname" TO t2sql_app;
GRANT t2sql_admin_ro, t2sql_analyst_ro, t2sql_sales_ro TO t2sql_app;
ALTER ROLE t2sql_app SET default_transaction_read_only = on;
ALTER ROLE t2sql_app SET statement_timeout = '15s';
ALTER ROLE t2sql_app SET idle_in_transaction_session_timeout = '30s';
EOSQL
