# Kết quả đánh giá

- Bộ đánh giá: 64 câu (60 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/shop
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Baseline (Mức 1) | **51.7%** | 90% | 36% | 28% | 75% | 3 | 51.7% | 64 | 52,962/3,265 | 2.2s |  |
| + Mô tả cột | **90.0%** | 100% | 95% | 72% | 100% | 4 | 91.7% | 64 | 125,026/3,841 | 3.7s | +38.3 điểm so với dòng trên |
| + Few-shot | **91.7%** | 100% | 86% | 89% | 100% | 3 | 91.7% | 64 | 145,671/3,295 | 7.5s | +1.7 điểm so với dòng trên |
| + Schema linking | **95.0%** | 100% | 86% | 100% | 100% | 2 | 95.0% | 64 | 107,961/3,273 | 3.6s | +3.3 điểm so với dòng trên |
| + Tự sửa lỗi | **98.3%** | 100% | 95% | 100% | 100% | 0 | 98.3% | 64 | 107,961/3,276 | 3.7s | +3.3 điểm so với dòng trên |
| + Kiểm tra hình dạng | **98.3%** | 100% | 95% | 100% | 100% | 0 | 98.3% | 64 | 107,961/3,273 | 3.1s | +0.0 điểm so với dòng trên |
| + Hình dạng + Self-consistency | **98.3%** | 100% | 95% | 100% | 100% | 0 | 98.3% | 133 | 225,747/7,119 | 5.1s | +0.0 điểm so với dòng trên; 1 câu có sửa lại |

## Phân tích lỗi: Baseline (Mức 1) (30 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 11 | m06, m07, m13, m18, m20, h01, h02, h03, h10, h14, h15 |
| Chọn sai bảng | 7 | m01, m02, m03, m10, m12, m16, h16 |
| Khác | 4 | e14, m15, m19, h05 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 3 | m14, h04, h18 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 2 | h06, h11 |
| Sai điều kiện lọc | 1 | e10 |
| Sai JOIN | 1 | h07 |
| Lẽ ra phải từ chối | 1 | u02 |

### e10 (easy): Có bao nhiêu khách hàng VIP?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_khach_hang_vip FROM customers WHERE segment = 'VIP'`
- SQL chuẩn: `SELECT COUNT(*) FROM customers WHERE segment = 'vip'`
- Kết quả dự đoán (5 dòng đầu): [[0]]
- Kết quả chuẩn (5 dòng đầu): [[26]]

### e14 (easy): Tổng phí vận chuyển của các đơn hàng hoàn thành là bao nhiêu?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(shipping_fee) AS total_shipping_fee FROM orders WHERE status = 2`
- SQL chuẩn: `SELECT SUM(shipping_fee) FROM orders WHERE status = 4`
- Kết quả dự đoán (5 dòng đầu): [[870000.0]]
- Kết quả chuẩn (5 dòng đầu): [[28735000.0]]

### h01 (hard): Top 3 khách hàng chi tiêu nhiều nhất trong năm 2025, cho biết tên và tổng chi tiêu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT c.name AS ten_khach_hang, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS tong_chi_tieu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE toYear(o.order_date) = 2025
GROUP BY c.customer_id, c.name
ORDER BY tong_chi_tieu DESC
LIMIT 3`
- SQL chuẩn: `SELECT c.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS spent FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 AND toYear(o.order_date) = 2025 GROUP BY c.customer_id, c.name ORDER BY spent DESC LIMIT 3`
- Kết quả dự đoán (5 dòng đầu): [['Bùi Minh Sơn', 943613500.0], ['Ngô Hữu Giang', 882428400.0], ['Hoàng Đức Hùng', 858060500.0]]
- Kết quả chuẩn (5 dòng đầu): [['Hoàng Đức Hùng', 790100500.0], ['Ngô Hữu Giang', 773420400.0], ['Bùi Minh Sơn', 722803700.0]]

### h02 (hard): Tháng nào trong năm 2024 có doanh thu cao nhất? Cho biết tháng và doanh thu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toMonth(order_date) AS month,
    sum(quantity * unit_price * (1 - discount)) AS revenue
FROM order_items
JOIN orders ON order_items.order_id = orders.order_id
WHERE toYear(order_date) = 2024
GROUP BY month
ORDER BY revenue DESC
LIMIT 1`
- SQL chuẩn: `SELECT formatDateTime(o.order_date, '%Y-%m') AS month, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND toYear(o.order_date) = 2024 GROUP BY month ORDER BY revenue DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[9, 2410352250.0]]
- Kết quả chuẩn (5 dòng đầu): [['2024-09', 2280187350.0]]

### h03 (hard): Doanh thu tháng trước là bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu_thang_truoc
FROM order_items oi
INNER JOIN orders o ON oi.order_id = o.order_id
WHERE o.order_date >= toStartOfMonth(toDate('2025-06-30') - INTERVAL 1 MONTH)
  AND o.order_date < toStartOfMonth(toDate('2025-06-30'))`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND formatDateTime(o.order_date, '%Y-%m') = '2025-05'`
- Kết quả dự đoán (5 dòng đầu): [[5656774350.0]]
- Kết quả chuẩn (5 dòng đầu): [[5133815700.0]]

### h04 (hard): Doanh thu tháng 6/2025 tăng hay giảm bao nhiêu phần trăm so với tháng 5/2025?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Identifier 'oi.order_date' cannot be resolved from table with name oi. In scope SELECT ((sumIf(oi.quantity * oi.unit_price, (toMonth(oi.order_date) = 6) AND (toYear(oi.order_date) = 2025)) - sumIf(oi.quantity * oi.unit_price, (toMonth(oi.order_date) = 5) AND (toYear(oi.order_date) = 2025))) / sumIf(oi.quantity * oi.unit_price, (toMonth(oi.order_date) = 5) AND (toYear(oi.order_date) = 2025))) * 100 AS percent_change FROM order_items AS oi INNER JOIN orders AS o ON oi.order_id = o.order_id WHERE o.status = 1. Maybe you meant: ['oi.order_id'].
- SQL dự đoán: `SELECT
    (sumIf(oi.quantity * oi.unit_price, toMonth(oi.order_date) = 6 AND toYear(oi.order_date) = 2025) -
     sumIf(oi.quantity * oi.unit_price, toMonth(oi.order_date) = 5 AND toYear(oi.order_date) = 2025)) /
    sumIf(oi.quantity * oi.unit_price, toMonth(oi.order_date) = 5 AND toYear(oi.order_date) = 2025) * 100 AS percent_change
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
WHERE o.status = 1`
- SQL chuẩn: `WITH m AS (SELECT formatDateTime(o.order_date, '%Y-%m') AS month, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 GROUP BY month) SELECT 100.0 * (jun.rev - may.rev) / may.rev FROM m AS jun CROSS JOIN m AS may WHERE jun.month = '2025-06' AND may.month = '2025-05'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[-22.361848712255096]]

### h05 (hard): Có bao nhiêu khách hàng đã mua cả điện thoại lẫn laptop (tính các đơn hoàn thành)?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count(DISTINCT o.customer_id) AS so_khach_hang
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.status = 1
  AND p.category IN ('Điện thoại', 'Laptop')
GROUP BY o.customer_id
HAVING count(DISTINCT p.category) = 2`
- SQL chuẩn: `SELECT COUNT(*) FROM (SELECT o.customer_id FROM orders AS o JOIN order_items AS oi ON oi.order_id = o.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 AND p.category IN ('Điện thoại', 'Laptop') GROUP BY o.customer_id HAVING COUNT(DISTINCT p.category) = 2)`
- Kết quả dự đoán (5 dòng đầu): [[1], [1], [1]]
- Kết quả chuẩn (5 dòng đầu): [[135]]

### h06 (hard): Trong mỗi danh mục, sản phẩm nào có doanh thu cao nhất? Cho biết danh mục, tên sản phẩm và doanh thu.
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.category AS danh_muc,
    p.name AS ten_san_pham,
    sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.status = 1
GROUP BY p.category, p.product_id, p.name
ORDER BY p.category, doanh_thu DESC
LIMIT 1 BY p.category`
- SQL chuẩn: `WITH s AS (SELECT p.category, p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.product_id, p.category, p.name), r AS (SELECT *, RANK() OVER (PARTITION BY category ORDER BY rev DESC) AS rk FROM s) SELECT category, name, rev FROM r WHERE rk = 1`
- Kết quả dự đoán (5 dòng đầu): [['Laptop', 'MacBook Air M3', 136869500.0], ['Máy tính bảng', 'iPad Air M2', 266743000.0], ['Phụ kiện', 'AirPods Pro 2', 20679500.0], ['Điện thoại', 'Xiaomi 14', 59970000.0], ['Đồng hồ thông minh', 'Galaxy Watch 6', 29530000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Laptop', 'Dell XPS 13', 4736689050.0], ['Đồng hồ thông minh', 'Apple Watch S9', 1344279350.0], ['Phụ kiện', 'AirPods Pro 2', 996440250.0], ['Máy tính bảng', 'iPad Air M2', 2822527700.0], ['Điện thoại', 'iPhone 15 Pro Max', 4196466950.0]]

### h07 (hard): Có bao nhiêu khách hàng có tổng chi tiêu cao hơn mức chi tiêu trung bình của các khách hàng đã mua hàng?
- Nhóm: Sai JOIN
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_khach_hang_chi_tieu_cao_hon_tb
FROM (
    SELECT o.customer_id, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS total_spent
    FROM orders o
    INNER JOIN order_items oi ON o.order_id = oi.order_id
    WHERE o.status = 1
    GROUP BY o.customer_id
)
WHERE total_spent > (
    SELECT avg(total_spent)
    FROM (
        SELECT o.customer_id, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS total_spent
        FROM orders o
        INNER JOIN order_items oi ON o.order_id = oi.order_id
        WHERE o.status = 1
        GROUP BY o.customer_id
    )
)`
- SQL chuẩn: `WITH t AS (SELECT o.customer_id, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS spent FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 GROUP BY o.customer_id) SELECT COUNT(*) FROM t WHERE spent > (SELECT AVG(spent) FROM t)`
- Kết quả dự đoán (5 dòng đầu): [[4]]
- Kết quả chuẩn (5 dòng đầu): [[69]]

### h10 (hard): Doanh thu từng quý của năm 2024 (số thứ tự quý 1-4 và doanh thu).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toQuarter(order_date) AS quarter_number,
    sum(quantity * unit_price * (1 - discount)) AS revenue
FROM order_items
JOIN orders ON order_items.order_id = orders.order_id
WHERE toYear(order_date) = 2024
GROUP BY quarter_number
ORDER BY quarter_number`
- SQL chuẩn: `SELECT toQuarter(o.order_date) AS quarter, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 4 AND toYear(o.order_date) = 2024 GROUP BY quarter`
- Kết quả dự đoán (5 dòng đầu): [[1, 3315728450.0], [2, 3912441700.0], [3, 5331685050.0], [4, 6078390750.0]]
- Kết quả chuẩn (5 dòng đầu): [[1, 2982690700.0], [2, 3645414900.0], [3, 4783356850.0], [4, 5568275150.0]]

### h11 (hard): Trung bình mất bao nhiêu ngày kể từ khi khách hàng đăng ký đến khi họ đặt đơn hàng đầu tiên?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT avg(dateDiff('day', c.created_at, o.order_date)) AS trung_binh_so_ngay
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.order_date = (
    SELECT min(order_date)
    FROM orders
    WHERE customer_id = c.customer_id
)`
- SQL chuẩn: `SELECT AVG(dateDiff('day', c.created_at, f.first_order)) FROM customers c JOIN (SELECT customer_id, MIN(order_date) AS first_order FROM orders GROUP BY customer_id) f ON f.customer_id = c.customer_id`
- Kết quả dự đoán (5 dòng đầu): [[69.41758241758242]]
- Kết quả chuẩn (5 dòng đầu): [[70.16666666666667]]

### h14 (hard): Top 3 sản phẩm có doanh thu cao nhất từ khách hàng ở TP.HCM trong năm 2025 (tên sản phẩm và doanh thu).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.name AS ten_san_pham, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
JOIN products p ON oi.product_id = p.product_id
WHERE c.city = 'TP.HCM' AND toYear(o.order_date) = 2025
GROUP BY p.product_id, p.name
ORDER BY doanh_thu DESC
LIMIT 3`
- SQL chuẩn: `SELECT p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 AND c.city = 'TP.HCM' AND toYear(o.order_date) = 2025 GROUP BY p.product_id, p.name ORDER BY revenue DESC LIMIT 3`
- Kết quả dự đoán (5 dòng đầu): [['MacBook Air M3', 1298310000.0], ['Dell XPS 13', 1170316950.0], ['iPhone 15', 995593300.0]]
- Kết quả chuẩn (5 dòng đầu): [['MacBook Air M3', 1101403000.0], ['Dell XPS 13', 968172150.0], ['iPhone 15', 912911400.0]]

### h15 (hard): Nhà cung cấp nào mang lại doanh thu cao nhất trong danh mục Phụ kiện? Cho biết tên nhà cung cấp và doanh thu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    s.name AS supplier_name,
    sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN products p ON oi.product_id = p.product_id
JOIN suppliers s ON p.supplier_id = s.supplier_id
WHERE p.category = 'Phụ kiện'
GROUP BY s.supplier_id, s.name
ORDER BY revenue DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id JOIN suppliers AS s ON s.supplier_id = p.supplier_id WHERE o.status = 4 AND p.category = 'Phụ kiện' GROUP BY s.supplier_id, s.name ORDER BY revenue DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['Apple Distribution', 1115097250.0]]
- Kết quả chuẩn (5 dòng đầu): [['Apple Distribution', 996440250.0]]

### h16 (hard): Mỗi danh mục chiếm bao nhiêu phần trăm tổng doanh thu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.category AS danh_muc,
    round(100.0 * sum(oi.quantity * oi.unit_price * (1 - oi.discount)) / (SELECT sum(oi2.quantity * oi2.unit_price * (1 - oi2.discount)) FROM order_items oi2), 2) AS phan_tram_doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.category`
- SQL chuẩn: `WITH t AS (SELECT p.category, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category) SELECT category, 100.0 * rev / (SELECT SUM(rev) FROM t) FROM t`
- Kết quả dự đoán (5 dòng đầu): [['Điện thoại', 35.52], ['Máy tính bảng', 16.34], ['Đồng hồ thông minh', 6.05], ['Laptop', 36.56], ['Phụ kiện', 5.52]]
- Kết quả chuẩn (5 dòng đầu): [['Điện thoại', 35.51235719362094], ['Máy tính bảng', 15.98254145818304], ['Đồng hồ thông minh', 6.066029345858758], ['Laptop', 36.72188663002458], ['Phụ kiện', 5.717185372312683]]

### h18 (hard): Đơn hàng hoàn thành nào có giá trị lớn nhất? Cho biết mã đơn, tên khách hàng và giá trị đơn.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Column 'oi.quantity' is not under aggregate function and not in GROUP BY keys. In query SELECT o.order_id, c.name AS customer_name, ((oi.quantity * oi.unit_price) * (1 - oi.discount)) + o.shipping_fee AS order_value FROM orders AS o INNER JOIN customers AS c ON o.customer_id = c.customer_id INNER JOIN order_items AS oi ON o.order_id = oi.order_id WHERE o.status = 1 GROUP BY o.order_id, c.name, o.shipping_fee ORDER BY order_value DESC LIMIT 1.
- SQL dự đoán: `SELECT o.order_id, c.name AS customer_name, (oi.quantity * oi.unit_price * (1 - oi.discount)) + o.shipping_fee AS order_value
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.status = 1
GROUP BY o.order_id, c.name, o.shipping_fee
ORDER BY order_value DESC
LIMIT 1`
- SQL chuẩn: `SELECT o.order_id, c.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS value FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 GROUP BY o.order_id, c.name ORDER BY value DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[1438, 'Ngô Minh Lan', 703720000.0]]

### m01 (medium): Tổng doanh thu từ trước đến nay là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS tong_doanh_thu
FROM order_items oi`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4`
- Kết quả dự đoán (5 dòng đầu): [[45584674900.0]]
- Kết quả chuẩn (5 dòng đầu): [[39423269550.0]]

### m02 (medium): Doanh thu theo từng danh mục sản phẩm.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.category AS danh_muc, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu FROM order_items oi INNER JOIN products p ON oi.product_id = p.product_id GROUP BY p.category ORDER BY doanh_thu DESC`
- SQL chuẩn: `SELECT p.category, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category`
- Kết quả dự đoán (5 dòng đầu): [['Laptop', 16666609900.0], ['Điện thoại', 16193637900.0], ['Máy tính bảng', 7448301550.0], ['Đồng hồ thông minh', 2758693300.0], ['Phụ kiện', 2517432250.0]]
- Kết quả chuẩn (5 dòng đầu): [['Điện thoại', 14000132300.0], ['Máy tính bảng', 6300840400.0], ['Đồng hồ thông minh', 2391427100.0], ['Laptop', 14476968350.0], ['Phụ kiện', 2253901400.0]]

### m03 (medium): Top 5 sản phẩm có doanh thu cao nhất, cho biết tên sản phẩm và doanh thu.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.name AS ten_san_pham, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.product_id, p.name
ORDER BY doanh_thu DESC
LIMIT 5`
- SQL chuẩn: `SELECT p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.product_id, p.name ORDER BY revenue DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['Dell XPS 13', 5644732750.0], ['iPhone 15 Pro Max', 4750333500.0], ['MacBook Air M3', 4424566900.0], ['Dell Latitude 5440', 4213162150.0], ['iPhone 15', 3952573650.0]]
- Kết quả chuẩn (5 dòng đầu): [['Dell XPS 13', 4736689050.0], ['iPhone 15 Pro Max', 4196466950.0], ['Dell Latitude 5440', 3888292650.0], ['MacBook Air M3', 3772123100.0], ['iPhone 15', 3672422850.0]]

### m06 (medium): Doanh thu năm 2024 là bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu_2024_2024
FROM order_items oi
INNER JOIN orders o ON oi.order_id = o.order_id
WHERE toYear(o.order_date) = 2024`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND toYear(o.order_date) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[18638245950.0]]
- Kết quả chuẩn (5 dòng đầu): [[16979737600.0]]

### m07 (medium): Doanh thu theo từng tháng trong năm 2025.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    formatDateTime(o.order_date, '%Y-%m') AS thang,
    sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
WHERE toYear(o.order_date) = 2025
GROUP BY thang
ORDER BY thang`
- SQL chuẩn: `SELECT formatDateTime(o.order_date, '%Y-%m'), SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND toYear(o.order_date) = 2025 GROUP BY 1`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 3159446300.0], ['2025-02', 3264129650.0], ['2025-03', 4509316950.0], ['2025-04', 3689943050.0], ['2025-05', 5656774350.0]]
- Kết quả chuẩn (5 dòng đầu): [['2025-04', 3458000500.0], ['2025-02', 2653912750.0], ['2025-03', 4164242050.0], ['2025-05', 5133815700.0], ['2025-01', 3047761350.0]]

### m10 (medium): Tổng số lượng sản phẩm bán ra của từng danh mục.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.category, sum(oi.quantity) AS total_quantity_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.category`
- SQL chuẩn: `SELECT p.category, SUM(oi.quantity) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category`
- Kết quả dự đoán (5 dòng đầu): [['Điện thoại', 928], ['Máy tính bảng', 553], ['Đồng hồ thông minh', 535], ['Laptop', 702], ['Phụ kiện', 1650]]
- Kết quả chuẩn (5 dòng đầu): [['Điện thoại', 792], ['Máy tính bảng', 466], ['Đồng hồ thông minh', 459], ['Laptop', 610], ['Phụ kiện', 1455]]

### m12 (medium): Đã bán được bao nhiêu chiếc iPhone 15?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(oi.quantity) AS total_iphone_15_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
WHERE p.name = 'iPhone 15'`
- SQL chuẩn: `SELECT SUM(oi.quantity) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 AND p.name = 'iPhone 15'`
- Kết quả dự đoán (5 dòng đầu): [[193]]
- Kết quả chuẩn (5 dòng đầu): [[179]]

### m13 (medium): Doanh thu theo từng phân khúc khách hàng.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    c.segment AS phan_khuc_khach_hang,
    sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
GROUP BY c.segment`
- SQL chuẩn: `SELECT c.segment, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 GROUP BY c.segment`
- Kết quả dự đoán (5 dòng đầu): [['wholesale', 12323598300.0], ['retail', 27341593500.0], ['vip', 5919483100.0]]
- Kết quả chuẩn (5 dòng đầu): [['wholesale', 10888624300.0], ['retail', 23569542950.0], ['vip', 4965102300.0]]

### m14 (medium): Giá trị trung bình của một đơn hàng hoàn thành là bao nhiêu (không tính phí vận chuyển)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Aggregate function sum((quantity * unit_price) * (1 - discount)) is found inside another aggregate function in query.
- SQL dự đoán: `SELECT avg(sum(quantity * unit_price * (1 - discount))) AS avg_order_value
FROM order_items
WHERE order_id IN (
    SELECT order_id
    FROM orders
    WHERE status = 2
)
GROUP BY order_id`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) / COUNT(DISTINCT o.order_id) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[32287690.049140047]]

### m15 (medium): Tỉ lệ phần trăm đơn hàng bị hủy trên tổng số đơn là bao nhiêu?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    countIf(status = 4) * 100.0 / count() AS percent_cancelled_orders
FROM orders`
- SQL chuẩn: `SELECT 100.0 * SUM(CASE WHEN status = 3 THEN 1 ELSE 0 END) / COUNT(*) FROM orders`
- Kết quả dự đoán (5 dòng đầu): [[84.43983402489627]]
- Kết quả chuẩn (5 dòng đầu): [[11.618257261410788]]

### m16 (medium): Doanh thu từ các sản phẩm của nhà cung cấp Apple Distribution là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
JOIN suppliers s ON p.supplier_id = s.supplier_id
WHERE s.name = 'Apple Distribution'`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id JOIN suppliers AS s ON s.supplier_id = p.supplier_id WHERE o.status = 4 AND s.name = 'Apple Distribution'`
- Kết quả dự đoán (5 dòng đầu): [[18932325550.0]]
- Kết quả chuẩn (5 dòng đầu): [[16804260200.0]]

### m18 (medium): Doanh thu theo thành phố của khách hàng.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    c.city AS city,
    sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
GROUP BY c.city`
- SQL chuẩn: `SELECT c.city, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 GROUP BY c.city`
- Kết quả dự đoán (5 dòng đầu): [['Đà Nẵng', 7292249800.0], ['Hải Phòng', 4958307800.0], ['Huế', 1275939400.0], ['TP.HCM', 17254203250.0], ['Cần Thơ', 2194218250.0]]
- Kết quả chuẩn (5 dòng đầu): [['Đà Nẵng', 6375210950.0], ['Hải Phòng', 4386062200.0], ['Huế', 1137874500.0], ['TP.HCM', 14968071950.0], ['Cần Thơ', 1734733100.0]]

### m19 (medium): Trong năm 2025, mỗi hình thức thanh toán có bao nhiêu đơn hàng hoàn thành?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    o.payment_method,
    count() AS so_don_hang_hoan_thanh
FROM orders o
WHERE toYear(o.order_date) = 2025
  AND o.status = 2
GROUP BY o.payment_method`
- SQL chuẩn: `SELECT payment_method, COUNT(*) FROM orders WHERE status = 4 AND toYear(order_date) = 2025 GROUP BY payment_method`
- Kết quả dự đoán (5 dòng đầu): [['cod', 19], ['bank_transfer', 7], ['card', 10]]
- Kết quả chuẩn (5 dòng đầu): [['cod', 312], ['bank_transfer', 166], ['card', 218]]

### m20 (medium): Mỗi khách hàng VIP có mua hàng đã chi tiêu tổng cộng bao nhiêu? Cho biết tên khách hàng và tổng chi tiêu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT c.name AS customer_name, sum(oi.quantity * oi.unit_price * (1 - oi.discount)) AS total_spent
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE c.segment = 'VIP'
GROUP BY c.customer_id, c.name`
- SQL chuẩn: `SELECT c.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 AND c.segment = 'vip' GROUP BY c.customer_id, c.name`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Phạm Thanh Lan', 179128100.0], ['Bùi Hữu Phúc', 31738300.0], ['Bùi Ngọc Mai', 162880500.0], ['Ngô Thu Tuấn', 69141400.0], ['Phạm Văn Phúc', 285792250.0]]

### u02 (unanswerable): Lợi nhuận sau khi trừ giá vốn của từng sản phẩm là bao nhiêu?
- Nhóm: Lẽ ra phải từ chối
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.product_id,
    p.name,
    sum((oi.unit_price - p.unit_price) * oi.quantity) AS profit_after_cost
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.product_id, p.name`
- SQL chuẩn: `None`
- Kết quả dự đoán (5 dòng đầu): None
- Kết quả chuẩn (5 dòng đầu): None

## Phân tích lỗi: + Hình dạng + Self-consistency (1 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai điều kiện lọc | 1 | m07 |

### m07 (medium): Doanh thu theo từng tháng trong năm 2025.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT toStartOfMonth(o.order_date) AS thang, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND toYear(o.order_date) = 2025 GROUP BY thang ORDER BY thang`
- SQL chuẩn: `SELECT formatDateTime(o.order_date, '%Y-%m'), SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND toYear(o.order_date) = 2025 GROUP BY 1`
- Kết quả dự đoán (5 dòng đầu): [['2025-01-01', 3047761350.0], ['2025-02-01', 2653912750.0], ['2025-03-01', 4164242050.0], ['2025-04-01', 3458000500.0], ['2025-05-01', 5133815700.0]]
- Kết quả chuẩn (5 dòng đầu): [['2025-04', 3458000500.0], ['2025-02', 2653912750.0], ['2025-03', 4164242050.0], ['2025-05', 5133815700.0], ['2025-01', 3047761350.0]]
