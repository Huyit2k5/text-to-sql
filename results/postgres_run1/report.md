# Kết quả đánh giá

- Bộ đánh giá: 64 câu (60 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: PostgreSQL t2sql_app@db:5432/shop
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Baseline (Mức 1) | **50.0%** | 90% | 32% | 28% | 75% | 3 | 50.0% | 64 | 42,018/3,721 | 2.1s |  |
| + Mô tả cột | **88.3%** | 95% | 95% | 72% | 100% | 0 | 88.3% | 64 | 114,402/3,917 | 7.4s | +38.3 điểm so với dòng trên |
| + Few-shot | **96.7%** | 100% | 100% | 89% | 100% | 0 | 96.7% | 64 | 135,886/3,475 | 3.4s | +8.3 điểm so với dòng trên |
| + Schema linking | **95.0%** | 100% | 100% | 83% | 100% | 1 | 95.0% | 64 | 98,212/3,434 | 2.9s | -1.7 điểm so với dòng trên |
| + Tự sửa lỗi | **96.7%** | 100% | 100% | 89% | 100% | 0 | 96.7% | 64 | 98,212/3,481 | 3.5s | +1.7 điểm so với dòng trên |

## Phân tích lỗi: Baseline (Mức 1) (31 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 14 | m01, m06, m07, m13, m18, m20, h01, h02, h03, h04, h06, h07, h10, h14 |
| Chọn sai bảng | 7 | m02, m03, m10, m12, m16, h15, h16 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 3 | m14, m17, h18 |
| Khác | 2 | e14, m08 |
| Sai JOIN | 2 | m19, h05 |
| Sai điều kiện lọc | 1 | e10 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h11 |
| Lẽ ra phải từ chối | 1 | u02 |

### e10 (easy): Có bao nhiêu khách hàng VIP?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT COUNT(*) AS so_khach_hang_vip FROM customers WHERE segment = 'VIP'`
- SQL chuẩn: `SELECT COUNT(*) FROM customers WHERE segment = 'vip'`
- Kết quả dự đoán (5 dòng đầu): [[0]]
- Kết quả chuẩn (5 dòng đầu): [[26]]

### e14 (easy): Tổng phí vận chuyển của các đơn hàng hoàn thành là bao nhiêu?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT SUM(o.shipping_fee) AS tong_phi_van_chuyen
FROM orders o
WHERE o.status = 1`
- SQL chuẩn: `SELECT SUM(shipping_fee) FROM orders WHERE status = 4`
- Kết quả dự đoán (5 dòng đầu): [[365000.0]]
- Kết quả chuẩn (5 dòng đầu): [[28735000.0]]

### h01 (hard): Top 3 khách hàng chi tiêu nhiều nhất trong năm 2025, cho biết tên và tổng chi tiêu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT c.name AS ten_khach_hang, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS tong_chi_tieu
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2025
GROUP BY c.name
ORDER BY tong_chi_tieu DESC
LIMIT 3`
- SQL chuẩn: `SELECT c.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS spent FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2025' GROUP BY c.customer_id ORDER BY spent DESC NULLS LAST LIMIT 3`
- Kết quả dự đoán (5 dòng đầu): [['Ngô Hữu Giang', 1523526100.0], ['Bùi Minh Sơn', 943613500.0], ['Hoàng Đức Hùng', 858060500.0]]
- Kết quả chuẩn (5 dòng đầu): [['Hoàng Đức Hùng', 790100500.0], ['Ngô Hữu Giang', 773420400.0], ['Bùi Minh Sơn', 722803700.0]]

### h02 (hard): Tháng nào trong năm 2024 có doanh thu cao nhất? Cho biết tháng và doanh thu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT TO_CHAR(o.order_date, 'YYYY-MM') AS thang, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2024
GROUP BY TO_CHAR(o.order_date, 'YYYY-MM')
ORDER BY doanh_thu DESC
LIMIT 1`
- SQL chuẩn: `SELECT TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY-MM') AS month, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2024' GROUP BY month ORDER BY revenue DESC NULLS LAST LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['2024-09', 2410352250.0]]
- Kết quả chuẩn (5 dòng đầu): [['2024-09', 2280187350.0]]

### h03 (hard): Doanh thu tháng trước là bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount / 100.0)) AS doanh_thu_thang_truoc
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
WHERE o.order_date >= DATE '2025-06-30' - INTERVAL '2 months'
  AND o.order_date < DATE '2025-06-30' - INTERVAL '1 month'`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY-MM') = '2025-05'`
- Kết quả dự đoán (5 dòng đầu): [[5863040877.5]]
- Kết quả chuẩn (5 dòng đầu): [[5133815700.0]]

### h04 (hard): Doanh thu tháng 6/2025 tăng hay giảm bao nhiêu phần trăm so với tháng 5/2025?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
  ROUND(
    (
      (
        SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount))
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE TO_CHAR(o.order_date, 'YYYY-MM') = '2025-06'
      ) - (
        SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount))
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE TO_CHAR(o.order_date, 'YYYY-MM') = '2025-05'
      )
    ) * 100.0 / (
      SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount))
      FROM order_items oi
      JOIN orders o ON oi.order_id = o.order_id
      WHERE TO_CHAR(o.order_date, 'YYYY-MM') = '2025-05'
    ),
    2
  ) AS percent_change
WHERE (
  SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount))
  FROM order_items oi
  JOIN orders o ON oi.order_id = o.order_id
  WHERE TO_CHAR(o.order_date, 'YYYY-MM') = '2025-05'
) IS NOT NULL
  AND (
    SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount))
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.order_id
    WHERE TO_CHAR(o.order_date, 'YYYY-MM') = '2025-05'
  ) != 0`
- SQL chuẩn: `WITH m AS (SELECT TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY-MM') AS month, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 GROUP BY month) SELECT 100.0 * (jun.rev - may.rev) / NULLIF(may.rev, 0) FROM m AS jun CROSS JOIN m AS may WHERE jun.month = '2025-06' AND may.month = '2025-05'`
- Kết quả dự đoán (5 dòng đầu): [[17.86]]
- Kết quả chuẩn (5 dòng đầu): [[-22.361848712255096]]

### h05 (hard): Có bao nhiêu khách hàng đã mua cả điện thoại lẫn laptop (tính các đơn hoàn thành)?
- Nhóm: Sai JOIN
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT COUNT(DISTINCT c.customer_id) AS so_khach_hang
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
WHERE o.status = 1
  AND p.category IN ('Điện thoại', 'Laptop')
GROUP BY c.customer_id
HAVING COUNT(DISTINCT p.category) = 2`
- SQL chuẩn: `SELECT COUNT(*) FROM (SELECT o.customer_id FROM orders AS o JOIN order_items AS oi ON oi.order_id = o.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 AND p.category IN ('Điện thoại', 'Laptop') GROUP BY o.customer_id HAVING COUNT(DISTINCT p.category) = 2)`
- Kết quả dự đoán (5 dòng đầu): [[1], [1], [1]]
- Kết quả chuẩn (5 dòng đầu): [[135]]

### h06 (hard): Trong mỗi danh mục, sản phẩm nào có doanh thu cao nhất? Cho biết danh mục, tên sản phẩm và doanh thu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.category AS danh_muc,
    p.name AS ten_san_pham,
    SUM(oi.quantity * oi.unit_price) AS doanh_thu
FROM
    order_items oi
JOIN
    orders o ON oi.order_id = o.order_id
JOIN
    products p ON oi.product_id = p.product_id
WHERE
    o.status = 1
GROUP BY
    p.category,
    p.name
ORDER BY
    p.category,
    doanh_thu DESC`
- SQL chuẩn: `WITH s AS (SELECT p.category, p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.product_id), r AS (SELECT *, RANK() OVER (PARTITION BY category ORDER BY rev DESC NULLS LAST) AS rk FROM s) SELECT category, name, rev FROM r WHERE rk = 1`
- Kết quả dự đoán (5 dòng đầu): [['Laptop', 'MacBook Air M3', 159541000.0], ['Laptop', 'Dell XPS 13', 94020000.0], ['Laptop', 'Dell Latitude 5440', 47481000.0], ['Máy tính bảng', 'iPad Air M2', 266743000.0], ['Máy tính bảng', 'Galaxy Tab S9', 50848000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Laptop', 'Dell XPS 13', 4736689050.0], ['Máy tính bảng', 'iPad Air M2', 2822527700.0], ['Phụ kiện', 'AirPods Pro 2', 996440250.0], ['Điện thoại', 'iPhone 15 Pro Max', 4196466950.0], ['Đồng hồ thông minh', 'Apple Watch S9', 1344279350.0]]

### h07 (hard): Có bao nhiêu khách hàng có tổng chi tiêu cao hơn mức chi tiêu trung bình của các khách hàng đã mua hàng?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT COUNT(*) AS so_khach_hang_chi_tieu_cao_hon_tb
FROM (
    SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total_spent
    FROM orders o
    JOIN order_items oi ON o.order_id = oi.order_id
    GROUP BY o.customer_id
) AS customer_spending
WHERE total_spent > (
    SELECT AVG(total_spent)
    FROM (
        SELECT o.customer_id, SUM(oi.quantity * oi.unit_price) AS total_spent
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        GROUP BY o.customer_id
    ) AS all_customer_spending
)`
- SQL chuẩn: `WITH t AS (SELECT o.customer_id, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS spent FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 GROUP BY o.customer_id) SELECT COUNT(*) FROM t WHERE spent > (SELECT AVG(spent) FROM t)`
- Kết quả dự đoán (5 dòng đầu): [[73]]
- Kết quả chuẩn (5 dòng đầu): [[69]]

### h10 (hard): Doanh thu từng quý của năm 2024 (số thứ tự quý 1-4 và doanh thu).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
  EXTRACT(QUARTER FROM o.order_date) AS quarter_number,
  SUM(oi.quantity * oi.unit_price * (1 - COALESCE(oi.discount, 0))) AS revenue
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2024
GROUP BY EXTRACT(QUARTER FROM o.order_date)
ORDER BY quarter_number`
- SQL chuẩn: `SELECT (CAST(TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'MM') AS INT) + 2) / NULLIF(3, 0) AS quarter, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2024' GROUP BY quarter`
- Kết quả dự đoán (5 dòng đầu): [[1, 3315728450.0], [2, 3912441700.0], [3, 5331685050.0], [4, 6078390750.0]]
- Kết quả chuẩn (5 dòng đầu): [[1, 2982690700.0], [2, 3645414900.0], [3, 4783356850.0], [4, 5568275150.0]]

### h11 (hard): Trung bình mất bao nhiêu ngày kể từ khi khách hàng đăng ký đến khi họ đặt đơn hàng đầu tiên?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT AVG(o.order_date - c.created_at) AS trung_binh_so_ngay
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_date = (
    SELECT MIN(o2.order_date)
    FROM orders o2
    WHERE o2.customer_id = o.customer_id
)`
- SQL chuẩn: `SELECT AVG(f.first_order - c.created_at) FROM customers c JOIN (SELECT customer_id, MIN(order_date) AS first_order FROM orders GROUP BY customer_id) f ON f.customer_id = c.customer_id`
- Kết quả dự đoán (5 dòng đầu): [[69.41758241758242]]
- Kết quả chuẩn (5 dòng đầu): [[70.16666666666667]]

### h14 (hard): Top 3 sản phẩm có doanh thu cao nhất từ khách hàng ở TP.HCM trong năm 2025 (tên sản phẩm và doanh thu).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.name AS ten_san_pham, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
JOIN products p ON oi.product_id = p.product_id
WHERE c.city = 'TP.HCM'
  AND EXTRACT(YEAR FROM o.order_date) = 2025
GROUP BY p.name
ORDER BY doanh_thu DESC
LIMIT 3`
- SQL chuẩn: `SELECT p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 AND c.city = 'TP.HCM' AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2025' GROUP BY p.product_id ORDER BY revenue DESC NULLS LAST LIMIT 3`
- Kết quả dự đoán (5 dòng đầu): [['MacBook Air M3', 1298310000.0], ['Dell XPS 13', 1170316950.0], ['iPhone 15', 995593300.0]]
- Kết quả chuẩn (5 dòng đầu): [['MacBook Air M3', 1101403000.0], ['Dell XPS 13', 968172150.0], ['iPhone 15', 912911400.0]]

### h15 (hard): Nhà cung cấp nào mang lại doanh thu cao nhất trong danh mục Phụ kiện? Cho biết tên nhà cung cấp và doanh thu.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.name AS supplier_name, SUM(oi.quantity * oi.unit_price) AS revenue
FROM suppliers s
JOIN products p ON s.supplier_id = p.supplier_id
JOIN order_items oi ON p.product_id = oi.product_id
WHERE p.category = 'Phụ kiện'
GROUP BY s.name
ORDER BY revenue DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id JOIN suppliers AS s ON s.supplier_id = p.supplier_id WHERE o.status = 4 AND p.category = 'Phụ kiện' GROUP BY s.supplier_id ORDER BY revenue DESC NULLS LAST LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['Apple Distribution', 1183591000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Apple Distribution', 996440250.0]]

### h16 (hard): Mỗi danh mục chiếm bao nhiêu phần trăm tổng doanh thu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT 
    p.category AS danh_muc,
    ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) * 100.0 / SUM(SUM(oi.quantity * oi.unit_price * (1 - oi.discount))) OVER (), 2) AS phan_tram_doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.category`
- SQL chuẩn: `WITH t AS (SELECT p.category, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category) SELECT category, 100.0 * rev / NULLIF((SELECT SUM(rev) FROM t), 0) FROM t`
- Kết quả dự đoán (5 dòng đầu): [['Đồng hồ thông minh', 6.05], ['Điện thoại', 35.52], ['Laptop', 36.56], ['Máy tính bảng', 16.34], ['Phụ kiện', 5.52]]
- Kết quả chuẩn (5 dòng đầu): [['Đồng hồ thông minh', 6.066029345858758], ['Điện thoại', 35.51235719362094], ['Laptop', 36.72188663002458], ['Máy tính bảng', 15.98254145818304], ['Phụ kiện', 5.717185372312683]]

### h18 (hard): Đơn hàng hoàn thành nào có giá trị lớn nhất? Cho biết mã đơn, tên khách hàng và giá trị đơn.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: column "oi.quantity" must appear in the GROUP BY clause or be used in an aggregate function
- SQL dự đoán: `SELECT o.order_id, c.name AS customer_name, (oi.quantity * oi.unit_price * (1 - oi.discount)) + o.shipping_fee AS order_value
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.status = 1
GROUP BY o.order_id, c.name, o.shipping_fee
ORDER BY order_value DESC
LIMIT 1`
- SQL chuẩn: `SELECT o.order_id, c.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS value FROM order_items oi JOIN orders o ON o.order_id = oi.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE o.status = 4 GROUP BY o.order_id, c.name ORDER BY value DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[1438, 'Ngô Minh Lan', 703720000.0]]

### m01 (medium): Tổng doanh thu từ trước đến nay là bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount / 100.0)) AS tong_doanh_thu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4`
- Kết quả dự đoán (5 dòng đầu): [[47731489999.0]]
- Kết quả chuẩn (5 dòng đầu): [[39423269550.0]]

### m02 (medium): Doanh thu theo từng danh mục sản phẩm.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT 
    p.category AS danh_muc_san_pham,
    SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.category`
- SQL chuẩn: `SELECT p.category, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category`
- Kết quả dự đoán (5 dòng đầu): [['Đồng hồ thông minh', 2758693300.0], ['Điện thoại', 16193637900.0], ['Laptop', 16666609900.0], ['Máy tính bảng', 7448301550.0], ['Phụ kiện', 2517432250.0]]
- Kết quả chuẩn (5 dòng đầu): [['Đồng hồ thông minh', 2391427100.0], ['Điện thoại', 14000132300.0], ['Laptop', 14476968350.0], ['Máy tính bảng', 6300840400.0], ['Phụ kiện', 2253901400.0]]

### m03 (medium): Top 5 sản phẩm có doanh thu cao nhất, cho biết tên sản phẩm và doanh thu.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.name AS ten_san_pham, SUM(oi.quantity * oi.unit_price) AS doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.name
ORDER BY doanh_thu DESC
LIMIT 5`
- SQL chuẩn: `SELECT p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS revenue FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.product_id ORDER BY revenue DESC NULLS LAST LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['Dell XPS 13', 5972817000.0], ['iPhone 15 Pro Max', 4952318000.0], ['MacBook Air M3', 4611329000.0], ['Dell Latitude 5440', 4494422000.0], ['iPhone 15', 4120906000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Dell XPS 13', 4736689050.0], ['iPhone 15 Pro Max', 4196466950.0], ['Dell Latitude 5440', 3888292650.0], ['MacBook Air M3', 3772123100.0], ['iPhone 15', 3672422850.0]]

### m06 (medium): Doanh thu năm 2024 là bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu_2024
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2024`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2024'`
- Kết quả dự đoán (5 dòng đầu): [[18638245950.0]]
- Kết quả chuẩn (5 dòng đầu): [[16979737600.0]]

### m07 (medium): Doanh thu theo từng tháng trong năm 2025.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT 
    TO_CHAR(o.order_date, 'YYYY-MM') AS thang,
    SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2025
GROUP BY TO_CHAR(o.order_date, 'YYYY-MM')
ORDER BY thang`
- SQL chuẩn: `SELECT TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY-MM'), SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4 AND TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2025' GROUP BY 1`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 3159446300.0], ['2025-02', 3264129650.0], ['2025-03', 4509316950.0], ['2025-04', 3689943050.0], ['2025-05', 5656774350.0]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 3047761350.0], ['2025-02', 2653912750.0], ['2025-03', 4164242050.0], ['2025-04', 3458000500.0], ['2025-05', 5133815700.0]]

### m08 (medium): Khách hàng nào đặt nhiều đơn hàng nhất? Cho biết tên và số đơn.
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT c.name AS ten_khach_hang, COUNT(o.order_id) AS so_don
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
GROUP BY c.name
ORDER BY so_don DESC
LIMIT 1`
- SQL chuẩn: `SELECT c.name, COUNT(*) AS n FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id GROUP BY c.customer_id ORDER BY n DESC NULLS LAST LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['Hoàng Hữu Tâm', 24]]
- Kết quả chuẩn (5 dòng đầu): [['Đặng Ngọc Phúc', 18]]

### m10 (medium): Tổng số lượng sản phẩm bán ra của từng danh mục.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.category, SUM(oi.quantity) AS total_quantity_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
GROUP BY p.category`
- SQL chuẩn: `SELECT p.category, SUM(oi.quantity) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category`
- Kết quả dự đoán (5 dòng đầu): [['Đồng hồ thông minh', 535], ['Điện thoại', 928], ['Laptop', 702], ['Máy tính bảng', 553], ['Phụ kiện', 1650]]
- Kết quả chuẩn (5 dòng đầu): [['Đồng hồ thông minh', 459], ['Điện thoại', 792], ['Laptop', 610], ['Máy tính bảng', 466], ['Phụ kiện', 1455]]

### m12 (medium): Đã bán được bao nhiêu chiếc iPhone 15?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT SUM(oi.quantity) AS total_iphone_15_sold
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
WHERE p.name ILIKE '%iPhone 15%'`
- SQL chuẩn: `SELECT SUM(oi.quantity) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 AND p.name = 'iPhone 15'`
- Kết quả dự đoán (5 dòng đầu): [[345]]
- Kết quả chuẩn (5 dòng đầu): [[179]]

### m13 (medium): Doanh thu theo từng phân khúc khách hàng.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT 
    c.segment AS phan_khuc_khach_hang,
    SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN orders o ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
GROUP BY c.segment`
- SQL chuẩn: `SELECT c.segment, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 GROUP BY c.segment`
- Kết quả dự đoán (5 dòng đầu): [['wholesale', 12323598300.0], ['vip', 5919483100.0], ['retail', 27341593500.0]]
- Kết quả chuẩn (5 dòng đầu): [['wholesale', 10888624300.0], ['vip', 4965102300.0], ['retail', 23569542950.0]]

### m14 (medium): Giá trị trung bình của một đơn hàng hoàn thành là bao nhiêu (không tính phí vận chuyển)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: aggregate function calls cannot be nested
- SQL dự đoán: `SELECT AVG(SUM(oi.quantity * oi.unit_price * (1 - oi.discount / 100.0))) AS average_order_value
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
WHERE o.status = 1
GROUP BY o.order_id`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) / NULLIF(COUNT(DISTINCT o.order_id), 0) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE o.status = 4`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[32287690.049140047]]

### m16 (medium): Doanh thu từ các sản phẩm của nhà cung cấp Apple Distribution là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
JOIN suppliers s ON p.supplier_id = s.supplier_id
WHERE s.name = 'Apple Distribution'`
- SQL chuẩn: `SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id JOIN suppliers AS s ON s.supplier_id = p.supplier_id WHERE o.status = 4 AND s.name = 'Apple Distribution'`
- Kết quả dự đoán (5 dòng đầu): [[18932325550.0]]
- Kết quả chuẩn (5 dòng đầu): [[16804260200.0]]

### m17 (medium): Liệt kê tên các sản phẩm không xuất hiện trong bất kỳ đơn hàng nào của năm 2025.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: syntax error at or near "="
- SQL dự đoán: `SELECT p.name AS product_name
FROM products p
WHERE p.product_id NOT IN (
    SELECT DISTINCT oi.product_id
    FROM order_items oi
    JOIN orders o ON oi.order_id = o.order_id
    WHERE EXTRACT(YEAR FROM o.order_date) = 20 = 2025
)`
- SQL chuẩn: `SELECT name FROM products WHERE NOT product_id IN (SELECT oi.product_id FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id WHERE TO_CHAR(CAST(o.order_date AS TIMESTAMP), 'YYYY') = '2025')`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Galaxy Buds 2'], ['Xiaomi Band 8'], ['Tai nghe Logitech G435']]

### m18 (medium): Doanh thu theo thành phố của khách hàng.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT c.city, SUM(oi.quantity * oi.unit_price) AS doanh_thu FROM order_items oi JOIN orders o ON oi.order_id = o.order_id JOIN customers c ON o.customer_id = c.customer_id GROUP BY c.city`
- SQL chuẩn: `SELECT c.city, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 GROUP BY c.city`
- Kết quả dự đoán (5 dòng đầu): [['Huế', 1331637000.0], ['Hải Phòng', 5196183000.0], ['Cần Thơ', 2320326000.0], ['Hà Nội', 13257505000.0], ['Đà Nẵng', 7613236000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Huế', 1137874500.0], ['Hải Phòng', 4386062200.0], ['Cần Thơ', 1734733100.0], ['Hà Nội', 10821316850.0], ['Đà Nẵng', 6375210950.0]]

### m19 (medium): Trong năm 2025, mỗi hình thức thanh toán có bao nhiêu đơn hàng hoàn thành?
- Nhóm: Sai JOIN
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT 
    o.payment_method,
    COUNT(o.order_id) AS so_don_hang_hoan_thanh
FROM orders o
WHERE EXTRACT(YEAR FROM o.order_date) = 2025
  AND o.status = 1
GROUP BY o.payment_method`
- SQL chuẩn: `SELECT payment_method, COUNT(*) FROM orders WHERE status = 4 AND TO_CHAR(CAST(order_date AS TIMESTAMP), 'YYYY') = '2025' GROUP BY payment_method`
- Kết quả dự đoán (5 dòng đầu): [['bank_transfer', 3], ['card', 9], ['cod', 9]]
- Kết quả chuẩn (5 dòng đầu): [['bank_transfer', 166], ['card', 218], ['cod', 312]]

### m20 (medium): Mỗi khách hàng VIP có mua hàng đã chi tiêu tổng cộng bao nhiêu? Cho biết tên khách hàng và tổng chi tiêu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT c.name AS ten_khach_hang, SUM(oi.quantity * oi.unit_price * (1 - oi.discount / 100.0)) AS tong_chi_tieu
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE c.segment = 'VIP'
GROUP BY c.name`
- SQL chuẩn: `SELECT c.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.status = 4 AND c.segment = 'vip' GROUP BY c.customer_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Lê Đức Giang', 60795800.0], ['Đỗ Thanh Châu', 163511000.0], ['Hoàng Hữu An', 238636400.0], ['Nguyễn Gia Mai', 213241700.0], ['Trần Đức Nam', 174064400.0]]

### u02 (unanswerable): Lợi nhuận sau khi trừ giá vốn của từng sản phẩm là bao nhiêu?
- Nhóm: Lẽ ra phải từ chối
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT 
    p.product_id,
    p.name AS product_name,
    SUM(oi.quantity * oi.unit_price) AS total_revenue,
    SUM(oi.quantity * p.unit_price) AS total_cost,
    SUM(oi.quantity * oi.unit_price) - SUM(oi.quantity * p.unit_price) AS profit
FROM products p
JOIN order_items oi ON p.product_id = oi.product_id
GROUP BY p.product_id, p.name`
- SQL chuẩn: `None`
- Kết quả dự đoán (5 dòng đầu): None
- Kết quả chuẩn (5 dòng đầu): None

## Phân tích lỗi: + Tự sửa lỗi (2 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Khác | 1 | h06 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h11 |

### h06 (hard): Trong mỗi danh mục, sản phẩm nào có doanh thu cao nhất? Cho biết danh mục, tên sản phẩm và doanh thu.
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.category AS danh_muc, p.name AS ten_san_pham, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS doanh_thu FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.category, p.product_id, p.name ORDER BY p.category, doanh_thu DESC NULLS LAST`
- SQL chuẩn: `WITH s AS (SELECT p.category, p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS rev FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id JOIN products AS p ON p.product_id = oi.product_id WHERE o.status = 4 GROUP BY p.product_id), r AS (SELECT *, RANK() OVER (PARTITION BY category ORDER BY rev DESC NULLS LAST) AS rk FROM s) SELECT category, name, rev FROM r WHERE rk = 1`
- Kết quả dự đoán (5 dòng đầu): [['Laptop', 'Dell XPS 13', 4736689050.0], ['Laptop', 'Dell Latitude 5440', 3888292650.0], ['Laptop', 'MacBook Air M3', 3772123100.0], ['Laptop', 'Dell Inspiron 15', 2079863550.0], ['Máy tính bảng', 'iPad Air M2', 2822527700.0]]
- Kết quả chuẩn (5 dòng đầu): [['Laptop', 'Dell XPS 13', 4736689050.0], ['Máy tính bảng', 'iPad Air M2', 2822527700.0], ['Phụ kiện', 'AirPods Pro 2', 996440250.0], ['Điện thoại', 'iPhone 15 Pro Max', 4196466950.0], ['Đồng hồ thông minh', 'Apple Watch S9', 1344279350.0]]

### h11 (hard): Trung bình mất bao nhiêu ngày kể từ khi khách hàng đăng ký đến khi họ đặt đơn hàng đầu tiên?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT AVG(o.order_date - c.created_at) AS so_ngay_tb FROM orders AS o JOIN customers AS c ON c.customer_id = o.customer_id WHERE o.order_id = (SELECT MIN(o2.order_id) FROM orders AS o2 WHERE o2.customer_id = c.customer_id)`
- SQL chuẩn: `SELECT AVG(f.first_order - c.created_at) FROM customers c JOIN (SELECT customer_id, MIN(order_date) AS first_order FROM orders GROUP BY customer_id) f ON f.customer_id = c.customer_id`
- Kết quả dự đoán (5 dòng đầu): [[203.80555555555554]]
- Kết quả chuẩn (5 dòng đầu): [[70.16666666666667]]
