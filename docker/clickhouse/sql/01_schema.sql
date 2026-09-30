-- Sinh tự động bởi data/export_clickhouse.py. Không sửa tay.

CREATE DATABASE IF NOT EXISTS shop;

CREATE TABLE IF NOT EXISTS shop.suppliers (
    supplier_id Int32 COMMENT 'Mã nhà cung cấp',
    name String COMMENT 'Tên nhà cung cấp',
    country LowCardinality(String) COMMENT 'Quốc gia của nhà cung cấp'
)
ENGINE = MergeTree
ORDER BY supplier_id
COMMENT 'Nhà cung cấp / hãng phân phối sản phẩm';

CREATE TABLE IF NOT EXISTS shop.customers (
    customer_id Int32 COMMENT 'Mã khách hàng',
    name String COMMENT 'Họ tên khách hàng',
    email String COMMENT 'Email khách hàng (dữ liệu nhạy cảm)',
    phone String COMMENT 'Số điện thoại (dữ liệu nhạy cảm)',
    city LowCardinality(String) COMMENT 'Thành phố / tỉnh của khách hàng',
    segment LowCardinality(String) COMMENT 'Phân khúc: \'retail\' = khách lẻ, \'wholesale\' = khách sỉ/đại lý, \'vip\' = khách VIP',
    created_at Date COMMENT 'Ngày khách đăng ký tài khoản'
)
ENGINE = MergeTree
ORDER BY customer_id
COMMENT 'Khách hàng (người mua, khách, client)';

CREATE TABLE IF NOT EXISTS shop.products (
    product_id Int32 COMMENT 'Mã sản phẩm',
    name String COMMENT 'Tên sản phẩm',
    category LowCardinality(String) COMMENT 'Danh mục / loại sản phẩm',
    supplier_id Int32 COMMENT 'Nhà cung cấp, khóa ngoại tới suppliers.supplier_id',
    unit_price Float64 COMMENT 'Giá niêm yết hiện tại (VND)',
    is_active UInt8 COMMENT '1 = đang kinh doanh, 0 = đã ngừng bán'
)
ENGINE = MergeTree
ORDER BY product_id
COMMENT 'Sản phẩm (mặt hàng) đang hoặc đã từng bán';

CREATE TABLE IF NOT EXISTS shop.orders (
    order_id Int32 COMMENT 'Mã đơn hàng',
    customer_id Int32 COMMENT 'Khách đặt đơn, khóa ngoại tới customers.customer_id',
    order_date Date COMMENT 'Ngày đặt hàng (YYYY-MM-DD)',
    status UInt8 COMMENT 'Trạng thái: 1 = chờ xử lý, 2 = đang giao, 3 = đã hủy, 4 = hoàn thành',
    payment_method LowCardinality(String) COMMENT 'Hình thức thanh toán: \'cod\' = thanh toán khi nhận hàng, \'card\' = thẻ, \'bank_transfer\' = chuyển khoản',
    shipping_fee Float64 COMMENT 'Phí vận chuyển (VND), không tính vào doanh thu'
)
ENGINE = MergeTree
ORDER BY (order_date, order_id)
COMMENT 'Đơn hàng (đơn đặt hàng, giao dịch mua)';

CREATE TABLE IF NOT EXISTS shop.order_items (
    order_item_id Int32 COMMENT 'Mã dòng chi tiết',
    order_id Int32 COMMENT 'Khóa ngoại tới orders.order_id',
    product_id Int32 COMMENT 'Khóa ngoại tới products.product_id',
    quantity Int32 COMMENT 'Số lượng mua',
    unit_price Float64 COMMENT 'Đơn giá lúc bán (VND), trước chiết khấu',
    discount Float64 COMMENT 'Tỉ lệ chiết khấu (0.1 = giảm 10%)'
)
ENGINE = MergeTree
ORDER BY (order_id, order_item_id)
COMMENT 'Chi tiết đơn hàng: từng sản phẩm trong một đơn';

CREATE TABLE IF NOT EXISTS shop.reviews (
    review_id Int32 COMMENT 'Mã đánh giá',
    product_id Int32 COMMENT 'Sản phẩm được đánh giá, khóa ngoại tới products.product_id',
    customer_id Int32 COMMENT 'Người đánh giá, khóa ngoại tới customers.customer_id',
    rating UInt8 COMMENT 'Số sao 1..5',
    comment Nullable(String) COMMENT 'Nội dung nhận xét (văn bản tự do do người dùng nhập)',
    created_at Date COMMENT 'Ngày viết đánh giá'
)
ENGINE = MergeTree
ORDER BY (product_id, review_id)
COMMENT 'Đánh giá / nhận xét sản phẩm của khách hàng';
