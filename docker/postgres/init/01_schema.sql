-- Sinh tự động bởi data/export_postgres.py. Không sửa tay.
BEGIN;
CREATE TABLE suppliers (
    supplier_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL
);
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    city TEXT NOT NULL,
    segment TEXT NOT NULL,
    created_at DATE NOT NULL
);
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    unit_price NUMERIC(14,2) NOT NULL,
    is_active SMALLINT NOT NULL
);
CREATE INDEX ON products (supplier_id);
CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date DATE NOT NULL,
    status SMALLINT NOT NULL,
    payment_method TEXT NOT NULL,
    shipping_fee NUMERIC(14,2) NOT NULL
);
CREATE INDEX ON orders (customer_id);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(14,2) NOT NULL,
    discount NUMERIC(4,2) NOT NULL
);
CREATE INDEX ON order_items (product_id);
CREATE INDEX ON order_items (order_id);
CREATE TABLE reviews (
    review_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    rating SMALLINT NOT NULL,
    comment TEXT,
    created_at DATE NOT NULL
);
CREATE INDEX ON reviews (customer_id);
CREATE INDEX ON reviews (product_id);
CREATE INDEX ON orders (order_date);
COMMENT ON TABLE suppliers IS 'Nhà cung cấp / hãng phân phối sản phẩm';
COMMENT ON COLUMN suppliers.supplier_id IS 'Mã nhà cung cấp';
COMMENT ON COLUMN suppliers.name IS 'Tên nhà cung cấp';
COMMENT ON COLUMN suppliers.country IS 'Quốc gia của nhà cung cấp';
COMMENT ON TABLE customers IS 'Khách hàng (người mua, khách, client)';
COMMENT ON COLUMN customers.customer_id IS 'Mã khách hàng';
COMMENT ON COLUMN customers.name IS 'Họ tên khách hàng';
COMMENT ON COLUMN customers.email IS 'Email khách hàng (dữ liệu nhạy cảm)';
COMMENT ON COLUMN customers.phone IS 'Số điện thoại (dữ liệu nhạy cảm)';
COMMENT ON COLUMN customers.city IS 'Thành phố / tỉnh của khách hàng';
COMMENT ON COLUMN customers.segment IS 'Phân khúc: ''retail'' = khách lẻ, ''wholesale'' = khách sỉ/đại lý, ''vip'' = khách VIP';
COMMENT ON COLUMN customers.created_at IS 'Ngày khách đăng ký tài khoản';
COMMENT ON TABLE products IS 'Sản phẩm (mặt hàng) đang hoặc đã từng bán';
COMMENT ON COLUMN products.product_id IS 'Mã sản phẩm';
COMMENT ON COLUMN products.name IS 'Tên sản phẩm';
COMMENT ON COLUMN products.category IS 'Danh mục / loại sản phẩm';
COMMENT ON COLUMN products.supplier_id IS 'Nhà cung cấp, khóa ngoại tới suppliers.supplier_id';
COMMENT ON COLUMN products.unit_price IS 'Giá niêm yết hiện tại (VND)';
COMMENT ON COLUMN products.is_active IS '1 = đang kinh doanh, 0 = đã ngừng bán';
COMMENT ON TABLE orders IS 'Đơn hàng (đơn đặt hàng, giao dịch mua)';
COMMENT ON COLUMN orders.order_id IS 'Mã đơn hàng';
COMMENT ON COLUMN orders.customer_id IS 'Khách đặt đơn, khóa ngoại tới customers.customer_id';
COMMENT ON COLUMN orders.order_date IS 'Ngày đặt hàng (YYYY-MM-DD)';
COMMENT ON COLUMN orders.status IS 'Trạng thái: 1 = chờ xử lý, 2 = đang giao, 3 = đã hủy, 4 = hoàn thành';
COMMENT ON COLUMN orders.payment_method IS 'Hình thức thanh toán: ''cod'' = thanh toán khi nhận hàng, ''card'' = thẻ, ''bank_transfer'' = chuyển khoản';
COMMENT ON COLUMN orders.shipping_fee IS 'Phí vận chuyển (VND), không tính vào doanh thu';
COMMENT ON TABLE order_items IS 'Chi tiết đơn hàng: từng sản phẩm trong một đơn';
COMMENT ON COLUMN order_items.order_item_id IS 'Mã dòng chi tiết';
COMMENT ON COLUMN order_items.order_id IS 'Khóa ngoại tới orders.order_id';
COMMENT ON COLUMN order_items.product_id IS 'Khóa ngoại tới products.product_id';
COMMENT ON COLUMN order_items.quantity IS 'Số lượng mua';
COMMENT ON COLUMN order_items.unit_price IS 'Đơn giá lúc bán (VND), trước chiết khấu';
COMMENT ON COLUMN order_items.discount IS 'Tỉ lệ chiết khấu (0.1 = giảm 10%)';
COMMENT ON TABLE reviews IS 'Đánh giá / nhận xét sản phẩm của khách hàng';
COMMENT ON COLUMN reviews.review_id IS 'Mã đánh giá';
COMMENT ON COLUMN reviews.product_id IS 'Sản phẩm được đánh giá, khóa ngoại tới products.product_id';
COMMENT ON COLUMN reviews.customer_id IS 'Người đánh giá, khóa ngoại tới customers.customer_id';
COMMENT ON COLUMN reviews.rating IS 'Số sao 1..5';
COMMENT ON COLUMN reviews.comment IS 'Nội dung nhận xét (văn bản tự do do người dùng nhập)';
COMMENT ON COLUMN reviews.created_at IS 'Ngày viết đánh giá';
COMMIT;
