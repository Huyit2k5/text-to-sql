# Kết quả đánh giá

- Bộ đánh giá: 64 câu (60 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: PostgreSQL t2sql_app@db:5432/shop
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| + Tự sửa lỗi | **96.7%** | 100% | 100% | 89% | 100% | 0 | 96.7% | 65 | 99,322/3,422 | 2.4s | 1 câu có sửa lại |
| + Kiểm tra hình dạng | **98.3%** | 100% | 100% | 94% | 100% | 0 | 98.3% | 66 | 101,096/3,542 | 2.4s | +1.7 điểm so với dòng trên; 2 câu có sửa lại |
| + Self-consistency | **96.7%** | 100% | 100% | 89% | 100% | 0 | 96.7% | 133 | 203,326/7,260 | 3.7s | -1.7 điểm so với dòng trên |
| + Hình dạng + Self-consistency | **98.3%** | 100% | 100% | 94% | 100% | 0 | 98.3% | 132 | 202,658/7,146 | 4.0s | +1.7 điểm so với dòng trên; 2 câu có sửa lại |

## Phân tích lỗi: + Tự sửa lỗi (2 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Khác | 1 | h06 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h11 |

### h06 (hard): Trong mỗi danh mục, sản phẩm nào có doanh thu cao nhất? Cho biết danh mục, tên sản phẩm và doanh thu.
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.category AS danh_muc, p.name AS ten_san_pham, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category, p.product_id, p.name ORDER BY p.category, doanh_thu DESC`
- SQL chuẩn: `WITH s AS (SELECT p.category, p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.product_id), r AS (SELECT *, RANK() OVER (PARTITION BY category ORDER BY rev DESC) AS rk FROM s) SELECT category, name, rev FROM r WHERE rk = 1`
- Kết quả dự đoán (5 dòng đầu): [['Laptop', 'Dell XPS 13', 4736689050.0], ['Laptop', 'Dell Latitude 5440', 3888292650.0], ['Laptop', 'MacBook Air M3', 3772123100.0], ['Laptop', 'Dell Inspiron 15', 2079863550.0], ['Máy tính bảng', 'iPad Air M2', 2822527700.0]]
- Kết quả chuẩn (5 dòng đầu): [['Laptop', 'Dell XPS 13', 4736689050.0], ['Máy tính bảng', 'iPad Air M2', 2822527700.0], ['Phụ kiện', 'AirPods Pro 2', 996440250.0], ['Điện thoại', 'iPhone 15 Pro Max', 4196466950.0], ['Đồng hồ thông minh', 'Apple Watch S9', 1344279350.0]]

### h11 (hard): Trung bình mất bao nhiêu ngày kể từ khi khách hàng đăng ký đến khi họ đặt đơn hàng đầu tiên?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT AVG(o.order_date - c.created_at) AS so_ngay_tb FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.order_date = (SELECT MIN(o2.order_date) FROM orders AS o2 WHERE o2.customer_id = c.customer_id)`
- SQL chuẩn: `SELECT AVG(f.first_order - c.created_at) FROM customers c JOIN (SELECT customer_id, MIN(order_date) AS first_order FROM orders GROUP BY customer_id) f ON f.customer_id = c.customer_id`
- Kết quả dự đoán (5 dòng đầu): [[69.41758241758242]]
- Kết quả chuẩn (5 dòng đầu): [[70.16666666666667]]

## Phân tích lỗi: + Hình dạng + Self-consistency (1 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h11 |

### h11 (hard): Trung bình mất bao nhiêu ngày kể từ khi khách hàng đăng ký đến khi họ đặt đơn hàng đầu tiên?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT AVG(o.order_date - c.created_at) AS so_ngay_tb FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.order_id = (SELECT MIN(o2.order_id) FROM orders AS o2 WHERE o2.customer_id = c.customer_id)`
- SQL chuẩn: `SELECT AVG(f.first_order - c.created_at) FROM customers c JOIN (SELECT customer_id, MIN(order_date) AS first_order FROM orders GROUP BY customer_id) f ON f.customer_id = c.customer_id`
- Kết quả dự đoán (5 dòng đầu): [[203.80555555555554]]
- Kết quả chuẩn (5 dòng đầu): [[70.16666666666667]]
