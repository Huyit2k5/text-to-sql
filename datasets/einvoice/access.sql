-- Phân quyền cho database einvoice. Chạy bởi generate.py (hoặc: python datasets/einvoice/generate.py --access-only).
-- Dùng lại profile t2sql_ro và 3 user t2sql_admin / t2sql_analyst / t2sql_sales tạo bởi docker/clickhouse/sql/03_access.sql.
--   admin   : đọc mọi bảng
--   analyst : đọc mọi bảng, trừ thông tin liên hệ (email / điện thoại) của người bán và người mua
--   sales   : phòng kinh doanh - chỉ khách hàng dịch vụ (sellers), gói, chứng thư số, danh mục và bảng tổng hợp ngày;
--             không xem chi tiết hóa đơn, người mua, log

CREATE ROLE IF NOT EXISTS t2sql_admin_ro;
CREATE ROLE IF NOT EXISTS t2sql_analyst_ro;
CREATE ROLE IF NOT EXISTS t2sql_sales_ro;

GRANT SELECT ON einvoice.* TO t2sql_admin_ro;

GRANT SELECT ON einvoice.provinces TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.tax_offices TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.industries TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.service_plans TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.tax_error_codes TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.subscriptions TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.certificates TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.invoice_series TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.invoices TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.invoice_items TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.tax_messages TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.api_requests TO t2sql_analyst_ro;
GRANT SELECT ON einvoice.daily_seller_stats TO t2sql_analyst_ro;
GRANT SELECT(seller_id, tax_code, name, company_type, industry_code, province_code, tax_office_code, employee_size,
             registered_at, status, closed_at, features, sales_channel) ON einvoice.sellers TO t2sql_analyst_ro;
GRANT SELECT(buyer_id, buyer_type, tax_code, name, province_code, created_at) ON einvoice.buyers TO t2sql_analyst_ro;

GRANT SELECT ON einvoice.sellers TO t2sql_sales_ro;
GRANT SELECT ON einvoice.subscriptions TO t2sql_sales_ro;
GRANT SELECT ON einvoice.service_plans TO t2sql_sales_ro;
GRANT SELECT ON einvoice.certificates TO t2sql_sales_ro;
GRANT SELECT ON einvoice.provinces TO t2sql_sales_ro;
GRANT SELECT ON einvoice.industries TO t2sql_sales_ro;
GRANT SELECT ON einvoice.tax_offices TO t2sql_sales_ro;
GRANT SELECT ON einvoice.daily_seller_stats TO t2sql_sales_ro
