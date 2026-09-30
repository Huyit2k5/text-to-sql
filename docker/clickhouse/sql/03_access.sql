-- User / role cho Text-to-SQL trên ClickHouse. Chạy bởi docker/clickhouse/init/01_init.sh,
-- __T2SQL_CH_PASSWORD__ được thay bằng biến môi trường T2SQL_CH_PASSWORD.
-- Áp dụng cho ClickHouse thật: đổi tên database `shop`, danh sách bảng/cột và mật khẩu rồi chạy bằng user quản trị.
--
-- Mỗi vai trò của app là một user riêng (t2sql_admin / t2sql_analyst / t2sql_sales), backend chọn user
-- theo vai trò đang dùng. Cả ba dùng chung profile t2sql_ro:
--   readonly = 2   : chỉ đọc; vẫn cho client đặt setting (timeout, giới hạn dòng) nhưng trong khung ràng buộc
--   join_use_nulls : LEFT JOIN không khớp trả NULL như SQL chuẩn (mặc định ClickHouse trả 0 / '')
--   giới hạn thời gian, bộ nhớ, số dòng đọc / trả về (có MAX: client không vượt được)
-- Không cấp CREATE TEMPORARY TABLE / SOURCES => không dùng được url(), file(), s3(), remote(), mysql()...

CREATE SETTINGS PROFILE OR REPLACE t2sql_ro SETTINGS
    readonly = 2,
    join_use_nulls = 1 CONST,
    allow_ddl = 0 CONST,
    allow_introspection_functions = 0 CONST,
    max_execution_time = 15 MAX 60,
    max_memory_usage = 2000000000 MAX 4000000000,
    max_rows_to_read = 500000000 MAX 500000000,
    max_result_rows = 100000 MAX 1000001,
    max_threads = 4 MAX 8;

CREATE ROLE OR REPLACE t2sql_admin_ro;
CREATE ROLE OR REPLACE t2sql_analyst_ro;
CREATE ROLE OR REPLACE t2sql_sales_ro;

GRANT SELECT ON shop.* TO t2sql_admin_ro;

GRANT SELECT ON shop.suppliers TO t2sql_analyst_ro;
GRANT SELECT ON shop.products TO t2sql_analyst_ro;
GRANT SELECT ON shop.orders TO t2sql_analyst_ro;
GRANT SELECT ON shop.order_items TO t2sql_analyst_ro;
GRANT SELECT ON shop.reviews TO t2sql_analyst_ro;
GRANT SELECT(customer_id, name, city, segment, created_at) ON shop.customers TO t2sql_analyst_ro;

GRANT SELECT ON shop.orders TO t2sql_sales_ro;
GRANT SELECT ON shop.order_items TO t2sql_sales_ro;
GRANT SELECT ON shop.products TO t2sql_sales_ro;
GRANT SELECT ON shop.suppliers TO t2sql_sales_ro;

CREATE USER OR REPLACE t2sql_admin IDENTIFIED WITH sha256_password BY '__T2SQL_CH_PASSWORD__'
    DEFAULT DATABASE shop SETTINGS PROFILE 't2sql_ro';
CREATE USER OR REPLACE t2sql_analyst IDENTIFIED WITH sha256_password BY '__T2SQL_CH_PASSWORD__'
    DEFAULT DATABASE shop SETTINGS PROFILE 't2sql_ro';
CREATE USER OR REPLACE t2sql_sales IDENTIFIED WITH sha256_password BY '__T2SQL_CH_PASSWORD__'
    DEFAULT DATABASE shop SETTINGS PROFILE 't2sql_ro';

GRANT t2sql_admin_ro TO t2sql_admin;
GRANT t2sql_analyst_ro TO t2sql_analyst;
GRANT t2sql_sales_ro TO t2sql_sales;
SET DEFAULT ROLE t2sql_admin_ro TO t2sql_admin;
SET DEFAULT ROLE t2sql_analyst_ro TO t2sql_analyst;
SET DEFAULT ROLE t2sql_sales_ro TO t2sql_sales;
