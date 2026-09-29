-- Phân quyền cho Text-to-SQL trên một PostgreSQL có sẵn (không phải DB mẫu trong docker compose).
--
-- Chạy bằng tài khoản quản trị (owner của schema):
--   psql "postgresql://admin@host:5432/ten_db" -v app_password='mat-khau-manh' -v dbname=ten_db -f roles.sql
--
-- Sau đó đặt trong .env:
--   T2SQL_DATABASE_URL=postgresql://t2sql_app:mat-khau-manh@host:5432/ten_db
--   T2SQL_DB_SCHEMA=public            (schema chứa bảng nghiệp vụ)
--
-- QUAN TRỌNG: các GRANT dưới đây phải khớp với POLICIES trong t2sql/safety.py
-- (allowed_tables / denied_columns của từng vai trò). App kiểm tra trước để báo lỗi dễ hiểu;
-- Postgres là lớp thực thi cuối cùng. Sửa bảng/cột theo schema thật của bạn.

\set ON_ERROR_STOP on

-- 1. Role theo vai trò (không đăng nhập được, chỉ để SET ROLE)
CREATE ROLE t2sql_admin_ro NOLOGIN;
CREATE ROLE t2sql_analyst_ro NOLOGIN;
CREATE ROLE t2sql_sales_ro NOLOGIN;
GRANT CONNECT ON DATABASE :"dbname" TO t2sql_admin_ro, t2sql_analyst_ro, t2sql_sales_ro;
GRANT USAGE ON SCHEMA public TO t2sql_admin_ro, t2sql_analyst_ro, t2sql_sales_ro;

-- admin: đọc mọi bảng (bảng tạo sau này cũng tự được cấp)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO t2sql_admin_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO t2sql_admin_ro;

-- analyst: mọi bảng, trừ cột nhạy cảm (GRANT theo cột)
GRANT SELECT ON suppliers, products, orders, order_items, reviews TO t2sql_analyst_ro;
GRANT SELECT (customer_id, name, city, segment, created_at) ON customers TO t2sql_analyst_ro;

-- sales: chỉ bảng bán hàng
GRANT SELECT ON orders, order_items, products, suppliers TO t2sql_sales_ro;

-- 2. Tài khoản app đăng nhập. NOINHERIT: không có quyền gì cho tới khi SET ROLE.
CREATE ROLE t2sql_app LOGIN NOINHERIT PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"dbname" TO t2sql_app;
GRANT t2sql_admin_ro, t2sql_analyst_ro, t2sql_sales_ro TO t2sql_app;
ALTER ROLE t2sql_app SET default_transaction_read_only = on;
ALTER ROLE t2sql_app SET statement_timeout = '15s';
ALTER ROLE t2sql_app SET idle_in_transaction_session_timeout = '30s';

-- Khuyến nghị: trỏ app vào read replica thay vì primary để truy vấn nặng không ảnh hưởng hệ thống chính.
