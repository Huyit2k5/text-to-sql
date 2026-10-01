# Kết quả đánh giá

- Bộ đánh giá: 62 câu (58 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cold | **56.9%** | 81% | 64% | 30% | 100% | 1 | 58.6% | 68 | 234,480/5,161 | 7.8s | 5 câu có sửa lại |
| cold_history | **84.5%** | 94% | 95% | 65% | 100% | 2 | 87.9% | 68 | 269,216/7,104 | 9.3s | +27.6 điểm so với dòng trên; 4 câu có sửa lại |

## Phân tích lỗi: cold (25 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai điều kiện lọc | 6 | m14, m17, m20, h07, h09, h19 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 4 | m12, h08, h10, h15 |
| Sai hàm / khoảng ngày tháng | 4 | m13, m15, h01, h12 |
| Khác | 3 | e12, e15, m10 |
| Từ chối / hỏi lại nhầm | 3 | m21, h06, h17 |
| Chọn sai bảng | 2 | h04, h14 |
| Sai cột kết quả / số cột | 1 | e04 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 1 | h02 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h18 |

### e04 (easy): Liệt kê các gói dịch vụ kèm số hóa đơn của gói và giá niêm yết.
- Nhóm: Sai cột kết quả / số cột
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT plan_id, name, invoice_quota, price_vnd FROM service_plans`
- SQL chuẩn: `SELECT name, invoice_quota, price_vnd FROM service_plans`
- Kết quả dự đoán (5 dòng đầu): [[1, 'Gói 300 hóa đơn', 300, 390000.0], [2, 'Gói 500 hóa đơn', 500, 550000.0], [3, 'Gói 1.000 hóa đơn', 1000, 890000.0], [4, 'Gói 2.000 hóa đơn', 2000, 1590000.0], [5, 'Gói 5.000 hóa đơn', 5000, 3290000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Gói 300 hóa đơn', 300, 390000.0], ['Gói 500 hóa đơn', 500, 550000.0], ['Gói 1.000 hóa đơn', 1000, 890000.0], ['Gói 2.000 hóa đơn', 2000, 1590000.0], ['Gói 5.000 hóa đơn', 5000, 3290000.0]]

### e12 (easy): Có bao nhiêu hóa đơn được lập bằng ngoại tệ (không phải VND)?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_hoa_don_ngoai_te
FROM invoices
WHERE currency != 'VND'`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE currency != 'VND'`
- Kết quả dự đoán (5 dòng đầu): [[1248483]]
- Kết quả chuẩn (5 dòng đầu): [[926722]]

### e15 (easy): Hiện có bao nhiêu hóa đơn đang chờ cơ quan thuế cấp mã?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_hoa_don_cho_cap_ma FROM invoices WHERE status = 'cho_cap_ma'`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE status = 'cho_cap_ma'`
- Kết quả dự đoán (5 dòng đầu): [[4570278]]
- Kết quả chuẩn (5 dòng đầu): [[20235]]

### h01 (hard): Tiền thuế GTGT (quy ra VND) theo từng thuế suất của các hóa đơn hợp lệ trong tháng 3/2025.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    ii.vat_rate AS thue_suat,
    sum(ii.vat_amount * i.exchange_rate) AS thue_gtgt_vnd
FROM invoice_items ii
JOIN invoices i ON ii.invoice_id = i.invoice_id
WHERE toYear(i.issued_at) = 2025
  AND toMonth(i.issued_at) = 3
  AND i.status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')
GROUP BY ii.vat_rate
ORDER BY ii.vat_rate`
- SQL chuẩn: `SELECT it.vat_rate, sum(it.vat_amount * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202503) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202503 GROUP BY it.vat_rate`
- Kết quả dự đoán (5 dòng đầu): [['0%', 0.0], ['10%', 1451724942886.0], ['5%', 322908595344.0], ['8%', 4118504822043.0], ['KCT', 0.0]]
- Kết quả chuẩn (5 dòng đầu): [['KKKNT', 0.0], ['KCT', 0.0], ['8%', 3448261813099.0], ['0%', 0.0], ['10%', 1215067799255.0]]

### h02 (hard): 5 nhóm hàng có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024 trên các hóa đơn hợp lệ.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT
    ii.product_group AS nhom_hang,
    sum(ii.line_amount - ii.discount_amount) * any(i.exchange_rate) AS doanh_thu_vnd
FROM invoice_items ii
JOIN invoices i ON ii.invoice_id = i.invoice_id
WHERE toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
  AND i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'da_ky')
GROUP BY ii.product_group
ORDER BY doanh_thu_vnd DESC
LIMIT 5`
- SQL chuẩn: `SELECT it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY it.product_group ORDER BY doanh_thu DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Vật liệu xây dựng', 66796102577154.0], ['Hàng xuất khẩu', 36158248955086.97], ['Dịch vụ tư vấn', 22530750068385.0], ['Dịch vụ ăn uống', 19433382638177.0], ['Nông sản và vật tư nông nghiệp', 17313756316558.0]]

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH monthly_revenue AS (
    SELECT
        formatDateTime(day, '%Y-%m') AS month,
        sum(revenue_vnd) AS total_revenue
    FROM daily_seller_stats
    WHERE day >= toDate('2024-12-01') AND day <= toDate('2025-06-30')
    GROUP BY month
)
SELECT
    month,
    total_revenue,
    CASE
        WHEN lagInFrame(total_revenue, 1) OVER (ORDER BY month) IS NULL OR lagInFrame(total_revenue, 1) OVER (ORDER BY month) = 0 THEN NULL
        ELSE (total_revenue - lagInFrame(total_revenue, 1) OVER (ORDER BY month)) / lagInFrame(total_revenue, 1) OVER (ORDER BY month) * 100
    END AS growth_rate_percent
FROM monthly_revenue
WHERE month >= '2025-01'
ORDER BY month`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 95998159808994.94, None], ['2025-02', 76423585126204.34, -20.390572821122426], ['2025-03', 95036166855908.52, 24.354499594552827], ['2025-04', 94197039637282.72, -0.882955664550382], ['2025-05', 98998383826909.05, 5.097128538343131]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h06 (hard): Mỗi tháng của năm 2025 có bao nhiêu người mua khác nhau trên các hóa đơn hợp lệ (tháng ghi dạng 2025-01)?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Cột buyers trong daily_seller_stats có kiểu AggregateFunction(uniqExact, UInt64), không phải Array, nên không thể dùng ARRAY JOIN để lấy danh sách buyer_id
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT formatDateTime(issued_at, '%Y-%m') AS thang, uniqExact(buyer_id) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2025 GROUP BY thang`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['2025-04', 624252], ['2025-01', 634250], ['2025-06', 660833], ['2025-05', 649179], ['2025-02', 531185]]

### h07 (hard): Trong các doanh nghiệp lập ít nhất 1.000 hóa đơn năm 2024, doanh nghiệp nào có tỷ lệ hóa đơn bị hủy cao nhất? Cho biết mã số thuế, tên và tỷ lệ (%).
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    s.tax_code AS ma_so_thue,
    s.name AS ten_doanh_nghiep,
    round(100.0 * countIf(i.status = 'da_huy') / count(), 2) AS ty_le_huy
FROM invoices i
JOIN sellers s ON i.seller_id = s.seller_id
WHERE toYear(i.issued_at) = 2024
GROUP BY s.tax_code, s.name
HAVING count() >= 1000
ORDER BY ty_le_huy DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, 100 * countIf(i.status = 'da_huy') / count() AS ty_le FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE toYear(i.issued_at) = 2024 GROUP BY s.seller_id, s.tax_code, s.name HAVING count() >= 1000 ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['7978850259', 'Công ty Cổ phần Dịch vụ Ăn uống An Phát Cửu Long', 2.59]]
- Kết quả chuẩn (5 dòng đầu): [['7460498778', 'Công ty TNHH Tư vấn Long Hải 86', 3.0592734225621414]]

### h08 (hard): Trong ngày 18/03/2025, khung giờ nào có tỷ lệ lỗi API cao nhất? Cho biết giờ (0-23) và tỷ lệ lỗi (%).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toHour(ts) AS gio,
    round(100.0 * countIf(http_status >= 400) / count(), 2) AS ty_le_loi_phan_tram
FROM api_requests
WHERE toDate(ts) = toDate('2025-03-18')
GROUP BY gio
ORDER BY ty_le_loi_phan_tram DESC
LIMIT 1`
- SQL chuẩn: `SELECT toHour(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) AS gio, 100 * countIf(http_status >= 400) / count() AS ty_le FROM api_requests WHERE toDate(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = toDate('2025-03-18') GROUP BY gio ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[2, 38.87]]
- Kết quả chuẩn (5 dòng đầu): [[9, 38.870588235294115]]

### h09 (hard): Độ trễ p95 (ms) của từng endpoint API trong tháng 6/2025.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    endpoint,
    quantile(0.95)(latency_ms) AS p95_latency_ms
FROM api_requests
WHERE ts >= toDateTime('2025-06-01 00:00:00')
  AND ts < toDateTime('2025-07-01 00:00:00')
GROUP BY endpoint`
- SQL chuẩn: `SELECT endpoint, quantileExact(0.95)(latency_ms) FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202506 GROUP BY endpoint`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/cancel', 797.0], ['/api/invoice/search', 373.0], ['/api/invoice/create', 572.0], ['/api/auth/token', 190.0], ['/api/invoice/publish', 3883.45]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/cancel', 803], ['/api/invoice/search', 377], ['/api/invoice/create', 567], ['/api/auth/token', 188], ['/api/invoice/publish', 3773]]

### h10 (hard): Trong các doanh nghiệp mua gói lần đầu trong năm 2023, bao nhiêu phần trăm mua thêm gói trong vòng 365 ngày sau lần mua đầu tiên?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH first_purchase AS (
    SELECT
        seller_id,
        min(purchased_at) AS first_date
    FROM subscriptions
    WHERE payment_status = 'da_thanh_toan'
    GROUP BY seller_id
    HAVING toYear(first_date) = 2023
),
repurchase AS (
    SELECT
        f.seller_id,
        countIf(s.purchased_at > f.first_date AND s.purchased_at <= f.first_date + INTERVAL 365 DAY) AS repurchase_count
    FROM first_purchase f
    LEFT JOIN subscriptions s
        ON f.seller_id = s.seller_id
        AND s.payment_status = 'da_thanh_toan'
    GROUP BY f.seller_id
)
SELECT
    round(100.0 * countIf(repurchase_count > 0) / count(), 2) AS percent_repurchase
FROM repurchase`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): [[36.57]]
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h12 (hard): Hóa đơn hợp lệ có giá trị thanh toán (quy ra VND) lớn nhất trong tháng 5/2025 là của doanh nghiệp nào? Cho biết mã số thuế, tên doanh nghiệp và số tiền.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    s.tax_code AS ma_so_thue,
    s.name AS ten_doanh_nghiep,
    sum(i.total_amount * i.exchange_rate) AS tong_tien_thanh_toan_vnd
FROM invoices i
JOIN sellers s ON i.seller_id = s.seller_id
WHERE toYear(i.issued_at) = 2025
  AND toMonth(i.issued_at) = 5
  AND i.status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')
GROUP BY s.tax_code, s.name
ORDER BY tong_tien_thanh_toan_vnd DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, i.total_amount * i.exchange_rate AS gia_tri FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 ORDER BY gia_tri DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 1131063594916.0]]
- Kết quả chuẩn (5 dòng đầu): [['7966472767', 'Công ty TNHH Thương mại Mai Linh Miền Bắc', 6428990761.440001]]

### h14 (hard): Năm 2024, doanh nghiệp có mã số thuế 0184171901 đạt doanh thu bao nhiêu và có bao nhiêu người mua khác nhau?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    sum(dss.revenue_vnd) AS doanh_thu_vnd,
    uniqExact(dss.buyers) AS so_nguoi_mua_khac_nhau
FROM daily_seller_stats dss
JOIN sellers s ON dss.seller_id = s.seller_id
WHERE s.tax_code = '0184171901'
  AND toYear(dss.day) = 2024`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate), uniqExact(buyer_id) FROM invoices FINAL WHERE seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '0184171901') AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[9160037938443.0, 732]]
- Kết quả chuẩn (5 dòng đầu): [[9160037938443.0, 3051]]

### h15 (hard): Tỷ trọng (%) doanh thu theo từng loại tiền (VND, USD, EUR) trong tổng doanh thu năm 2024, tính sau khi quy đổi ra VND.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    currency,
    sum(total_before_tax * exchange_rate) AS revenue_vnd,
    round(100.0 * sum(total_before_tax * exchange_rate) / sum(sum(total_before_tax * exchange_rate)) OVER (), 2) AS percent_of_total
FROM invoices
WHERE toYear(issued_at) = 2024
GROUP BY currency
ORDER BY revenue_vnd DESC`
- SQL chuẩn: `SELECT currency, 100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency`
- Kết quả dự đoán (5 dòng đầu): [['VND', 1257025824042898.0, 87.61], ['USD', 142175233604064.38, 9.91], ['EUR', 35566957848988.8, 2.48]]
- Kết quả chuẩn (5 dòng đầu): [['EUR', 2.47544734219474], ['VND', 87.62135431028862], ['USD', 9.903198347516758]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Dữ liệu không có thông tin về hóa đơn hợp lệ (chỉ có trạng thái hóa đơn) và không có dữ liệu doanh thu/thuế theo từng mức thuế suất cụ thể để tính toán giả định thay đổi thuế suất từ 8% lên 10%.
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[994295801179.54]]

### h18 (hard): Có bao nhiêu doanh nghiệp đang hoạt động mà chứng thư số còn hiệu lực cuối cùng sẽ hết hạn trong 15 ngày tới (tính từ hôm nay) và chưa có chứng thư nào mới hơn?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count(DISTINCT s.seller_id) AS so_doanh_nghiep
FROM sellers s
INNER JOIN certificates c ON s.seller_id = c.seller_id
WHERE s.status = 'active'
  AND c.valid_to >= toDate('2025-06-30')
  AND c.valid_to <= toDate('2025-06-30') + INTERVAL 15 DAY
  AND NOT EXISTS (
    SELECT 1
    FROM certificates c2
    WHERE c2.seller_id = s.seller_id
      AND c2.valid_from > c.valid_from
  )`
- SQL chuẩn: `SELECT count() FROM (SELECT seller_id, max(valid_to) AS het_han FROM certificates WHERE revoked = 0 GROUP BY seller_id) AS c JOIN sellers AS s ON s.seller_id = c.seller_id WHERE s.status = 'active' AND c.het_han >= toDate('2025-06-30') AND c.het_han <= toDate('2025-06-30') + 15`
- Kết quả dự đoán (5 dòng đầu): [[1189]]
- Kết quả chuẩn (5 dòng đầu): [[1158]]

### h19 (hard): Với hóa đơn có mã lập năm 2024, tỷ lệ (%) bị cơ quan thuế từ chối theo từng kênh lập hóa đơn là bao nhiêu?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.channel AS "Kênh lập hóa đơn",
    countIf(i.status = 'cqt_tu_choi') AS "Số hóa đơn bị từ chối",
    count() AS "Tổng số hóa đơn",
    round(countIf(i.status = 'cqt_tu_choi') * 100.0 / count(), 2) AS "Tỷ lệ bị từ chối (%)"
FROM invoices i
WHERE toYear(i.issued_at) = 2024
  AND i.tax_code_type = 'co_ma'
GROUP BY i.channel
ORDER BY i.channel`
- SQL chuẩn: `SELECT channel, 100 * countIf(status = 'cqt_tu_choi') / count() FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND status NOT IN ('nhap', 'da_ky') AND toYear(issued_at) = 2024 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): [['api', 31580, 2989963, 1.06], ['excel', 10238, 960298, 1.07], ['mobile', 3635, 349580, 1.04], ['pos', 9374, 882028, 1.06], ['web', 70567, 6630613, 1.06]]
- Kết quả chuẩn (5 dòng đầu): [['web', 1.4971074916687104], ['excel', 1.5009573404408165], ['pos', 1.4948555536419363], ['mobile', 1.4632595061549485], ['api', 1.486270820381018]]

### m10 (medium): Năm 2024 có bao nhiêu hóa đơn thay thế được lập?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_hoa_don_thay_the
FROM invoices
WHERE toYear(issued_at) = 2024
  AND nature = 'thay_the'`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE nature = 'thay_the' AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[227839]]
- Kết quả chuẩn (5 dòng đầu): [[172284]]

### m12 (medium): Số hóa đơn hợp lệ theo kênh lập hóa đơn trong tháng 6/2025.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.channel AS "Kênh lập hóa đơn",
    sum(dss.invoice_count) AS "Số hóa đơn hợp lệ"
FROM daily_seller_stats dss
JOIN invoices i
    ON dss.seller_id = i.seller_id
WHERE
    dss.day >= toDate('2025-06-01')
    AND dss.day <= toDate('2025-06-30')
GROUP BY
    i.channel`
- SQL chuẩn: `SELECT channel, count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202506 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): [['mobile', 210438426], ['pos', 6356420832], ['web', 4045370906], ['api', 3274305290], ['excel', 1029615689]]
- Kết quả chuẩn (5 dòng đầu): [['mobile', 34628], ['pos', 83456], ['web', 651644], ['api', 282104], ['excel', 94460]]

### m13 (medium): Thời gian phản hồi trung bình (giây) của cơ quan thuế với các thông điệp đề nghị cấp mã được chấp nhận trong tháng 6/2025.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    avg(dateDiff('second', sent_at, response_at)) AS thoi_gian_phan_hoi_trung_binh_giay
FROM tax_messages
WHERE message_type = '200'
  AND result = 'chap_nhan'
  AND response_at IS NOT NULL
  AND toStartOfMonth(sent_at) = toDate('2025-06-01')`
- SQL chuẩn: `SELECT avg(dateDiff('second', sent_at, response_at)) FROM tax_messages WHERE message_type = '200' AND result = 'chap_nhan' AND toYYYYMM(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) = 202506`
- Kết quả dự đoán (5 dòng đầu): [[148.81478705821624]]
- Kết quả chuẩn (5 dòng đầu): [[148.79127469593172]]

### m14 (medium): 10 mã lỗi khiến cơ quan thuế từ chối nhiều nhất năm 2024, kèm mô tả lỗi và số lần.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    tec.error_code AS ma_loi,
    tec.description AS mo_ta_loi,
    count() AS so_lan_tu_choi
FROM tax_messages tm
INNER JOIN tax_error_codes tec ON tm.error_code = tec.error_code
WHERE tm.result = 'tu_choi'
  AND toYear(tm.sent_at) = 2024
GROUP BY tec.error_code, tec.description
ORDER BY so_lan_tu_choi DESC
LIMIT 10`
- SQL chuẩn: `SELECT e.error_code, e.description, count() AS so_lan FROM tax_messages AS t JOIN tax_error_codes AS e ON e.error_code = t.error_code WHERE t.result = 'tu_choi' AND toYear(toTimeZone(t.sent_at, 'Asia/Ho_Chi_Minh')) = 2024 GROUP BY e.error_code, e.description ORDER BY so_lan DESC LIMIT 10`
- Kết quả dự đoán (5 dòng đầu): [['KTMST02', 'Mã số thuế người mua sai định dạng', 31455], ['KTMST03', 'Mã số thuế người mua không tồn tại', 25062], ['DD02', 'Thiếu thông tin bắt buộc trên hóa đơn', 23917], ['TT01', 'Tổng tiền không khớp với chi tiết hàng hóa', 18976], ['TT02', 'Thuế suất không phù hợp tại thời điểm lập hóa đơn', 15145]]
- Kết quả chuẩn (5 dòng đầu): [['KTMST02', 'Mã số thuế người mua sai định dạng', 31454], ['KTMST03', 'Mã số thuế người mua không tồn tại', 25062], ['DD02', 'Thiếu thông tin bắt buộc trên hóa đơn', 23912], ['TT01', 'Tổng tiền không khớp với chi tiết hàng hóa', 18978], ['TT02', 'Thuế suất không phù hợp tại thời điểm lập hóa đơn', 15141]]

### m15 (medium): Có bao nhiêu doanh nghiệp đang hoạt động lập ít hơn 10 hóa đơn (mọi trạng thái) trong tháng 6/2025, kể cả doanh nghiệp không lập hóa đơn nào?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_doanh_nghiep
FROM (
    SELECT s.seller_id
    FROM sellers s
    LEFT JOIN invoices i ON s.seller_id = i.seller_id
    WHERE s.status = 'active'
    GROUP BY s.seller_id
    HAVING countIf(i.issued_at >= toDate('2025-06-01') AND i.issued_at < toDate('2025-07-01')) < 10
)`
- SQL chuẩn: `SELECT count() FROM sellers AS s LEFT JOIN (SELECT seller_id, count() AS n FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202506 GROUP BY seller_id) AS c ON c.seller_id = s.seller_id WHERE s.status = 'active' AND (c.n IS NULL OR c.n < 10)`
- Kết quả dự đoán (5 dòng đầu): [[1940]]
- Kết quả chuẩn (5 dòng đầu): [[5204]]

### m17 (medium): Tỷ lệ (%) hóa đơn hợp lệ năm 2024 không có thông tin người mua (khách lẻ).
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    round(
        countIf(buyer_id IS NULL) * 100.0 / count(),
        2
    ) AS ty_le_khach_le_phan_tram
FROM invoices
WHERE toYear(issued_at) = 2024
  AND status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')`
- SQL chuẩn: `SELECT 100 * countIf(buyer_id IS NULL) / count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[22.75]]
- Kết quả chuẩn (5 dòng đầu): [[22.79076181710743]]

### m20 (medium): Tổng giá trị thanh toán (quy ra VND) của các hóa đơn hợp lệ lập bằng USD trong năm 2024.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) AS total_payment_vnd
FROM invoices
WHERE currency = 'USD'
  AND toYear(issued_at) = 2024
  AND status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')`
- SQL chuẩn: `SELECT sum(total_amount * exchange_rate) FROM invoices FINAL WHERE currency = 'USD' AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[115103156282261.16]]
- Kết quả chuẩn (5 dòng đầu): [[96677915997293.22]]

### m21 (medium): Số hóa đơn hợp lệ năm 2024 theo loại hóa đơn (GTGT / bán hàng) và theo có mã / không mã.
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Bảng daily_seller_stats không có cột invoice_type và tax_code_type
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT invoice_type, tax_code_type, count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY invoice_type, tax_code_type`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['gtgt', 'co_ma', 6419826], ['ban_hang', 'co_ma', 1558691], ['gtgt', 'khong_ma', 2559916], ['ban_hang', 'khong_ma', 534264]]

## Phân tích lỗi: cold_history (9 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 2 | h04, h19 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 2 | h10, h17 |
| Sai cột kết quả / số cột | 1 | e04 |
| Từ chối / hỏi lại nhầm | 1 | m15 |
| Sai điều kiện lọc | 1 | h15 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h18 |
| Sai hàm / khoảng ngày tháng | 1 | h20 |

### e04 (easy): Liệt kê các gói dịch vụ kèm số hóa đơn của gói và giá niêm yết.
- Nhóm: Sai cột kết quả / số cột
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT plan_id, name, invoice_quota, price_vnd FROM service_plans`
- SQL chuẩn: `SELECT name, invoice_quota, price_vnd FROM service_plans`
- Kết quả dự đoán (5 dòng đầu): [[1, 'Gói 300 hóa đơn', 300, 390000.0], [2, 'Gói 500 hóa đơn', 500, 550000.0], [3, 'Gói 1.000 hóa đơn', 1000, 890000.0], [4, 'Gói 2.000 hóa đơn', 2000, 1590000.0], [5, 'Gói 5.000 hóa đơn', 5000, 3290000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Gói 300 hóa đơn', 300, 390000.0], ['Gói 500 hóa đơn', 500, 550000.0], ['Gói 1.000 hóa đơn', 1000, 890000.0], ['Gói 2.000 hóa đơn', 2000, 1590000.0], ['Gói 5.000 hóa đơn', 5000, 3290000.0]]

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Illegal type String of argument of function toYear. Should be Date, Date32, DateTime or DateTime64: In scope SELECT formatDateTime(thang, '%Y-%m') AS thang, doanh_thu, round(((doanh_thu - doanh_thu_thang_truoc) / doanh_thu_thang_truoc) * 100, 2) AS tang_truong_phan_tram FROM (SELECT toStartOfMonth(issued_at) AS thang, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu, lagInFrame(sum((total_before_tax - total_discount) * exchange_rate), 1) OVER (ORDER BY toStartOfMonth(issued_at) ASC) AS doanh_thu_thang_truoc FROM invoices FINAL WHERE (status IN ('cqt_cap_ma', 'da_gui_cqt', 
- SQL dự đoán: `SELECT
    formatDateTime(thang, '%Y-%m') AS thang,
    doanh_thu,
    round((doanh_thu - doanh_thu_thang_truoc) / doanh_thu_thang_truoc * 100, 2) AS tang_truong_phan_tram
FROM
(
    SELECT
        toStartOfMonth(issued_at) AS thang,
        sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu,
        lagInFrame(sum((total_before_tax - total_discount) * exchange_rate), 1) OVER (ORDER BY toStartOfMonth(issued_at)) AS doanh_thu_thang_truoc
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
      AND (
          (toYear(issued_at) = 2025)
          OR (toYear(issued_at) = 2024 AND toMonth(issued_at) = 12)
      )
    GROUP BY thang
    ORDER BY thang
)
WHERE toYear(thang) = 2025
ORDER BY thang`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h10 (hard): Trong các doanh nghiệp mua gói lần đầu trong năm 2023, bao nhiêu phần trăm mua thêm gói trong vòng 365 ngày sau lần mua đầu tiên?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH first_purchase AS (
    SELECT
        seller_id,
        min(purchased_at) AS first_date
    FROM subscriptions
    WHERE payment_status = 'da_thanh_toan'
    GROUP BY seller_id
    HAVING toYear(first_date) = 2023
),
repurchase AS (
    SELECT
        f.seller_id,
        countIf(s.purchased_at > f.first_date AND s.purchased_at <= f.first_date + INTERVAL 365 DAY) AS repurchase_count
    FROM first_purchase AS f
    LEFT JOIN subscriptions AS s
        ON f.seller_id = s.seller_id
        AND s.payment_status = 'da_thanh_toan'
    GROUP BY f.seller_id
)
SELECT
    countIf(repurchase_count > 0) * 100.0 / count() AS phan_tram_mua_them
FROM repurchase`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): [[36.574770258980784]]
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h15 (hard): Tỷ trọng (%) doanh thu theo từng loại tiền (VND, USD, EUR) trong tổng doanh thu năm 2024, tính sau khi quy đổi ra VND.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    currency AS loai_tien,
    sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu_vnd,
    round(100.0 * sum((total_before_tax - total_discount) * exchange_rate) / sum(sum((total_before_tax - total_discount) * exchange_rate)) OVER (), 2) AS ty_trong_phan_tram
FROM invoices FINAL
WHERE status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
  AND toYear(issued_at) = 2024
GROUP BY currency
ORDER BY doanh_thu_vnd DESC`
- SQL chuẩn: `SELECT currency, 100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency`
- Kết quả dự đoán (5 dòng đầu): [['VND', 855385263863095.0, 87.62], ['USD', 96677915997293.69, 9.9], ['EUR', 24166040283787.42, 2.48]]
- Kết quả chuẩn (5 dòng đầu): [['EUR', 2.47544734219474], ['VND', 87.62135431028862], ['USD', 9.903198347516758]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    sum(vat_amount * exchange_rate) AS tong_tien_thue_goc,
    sumIf(vat_amount * exchange_rate, vat_rate = '8%') * 0.2 AS tang_them
FROM invoice_items AS it
JOIN (
    SELECT invoice_id, exchange_rate
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
      AND toYYYYMM(issued_at) = 202412
) AS i ON i.invoice_id = it.invoice_id
WHERE toYYYYMM(it.issued_at) = 202412`
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): [[5684065137803.0, 795436640947.2001]]
- Kết quả chuẩn (5 dòng đầu): [[994295801179.54]]

### h18 (hard): Có bao nhiêu doanh nghiệp đang hoạt động mà chứng thư số còn hiệu lực cuối cùng sẽ hết hạn trong 15 ngày tới (tính từ hôm nay) và chưa có chứng thư nào mới hơn?
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count(DISTINCT s.seller_id) AS so_doanh_nghiep
FROM sellers s
INNER JOIN certificates c ON s.seller_id = c.seller_id
WHERE s.status = 'active'
  AND c.valid_to >= toDate('2025-06-30')
  AND c.valid_to <= toDate('2025-06-30') + INTERVAL 15 DAY
  AND NOT EXISTS (
    SELECT 1
    FROM certificates c2
    WHERE c2.seller_id = s.seller_id
      AND c2.valid_from > c.valid_from
  )`
- SQL chuẩn: `SELECT count() FROM (SELECT seller_id, max(valid_to) AS het_han FROM certificates WHERE revoked = 0 GROUP BY seller_id) AS c JOIN sellers AS s ON s.seller_id = c.seller_id WHERE s.status = 'active' AND c.het_han >= toDate('2025-06-30') AND c.het_han <= toDate('2025-06-30') + 15`
- Kết quả dự đoán (5 dòng đầu): [[1189]]
- Kết quả chuẩn (5 dòng đầu): [[1158]]

### h19 (hard): Với hóa đơn có mã lập năm 2024, tỷ lệ (%) bị cơ quan thuế từ chối theo từng kênh lập hóa đơn là bao nhiêu?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt giới hạn tài nguyên (đọc quá nhiều dòng / bộ nhớ): Query memory limit exceeded: would use 1.87 GiB (attempt to allocate chunk of 8.00 MiB bytes), maximum: 1.86 GiB: While executing FillingRightJoinSide.
- SQL dự đoán: `SELECT
    i.channel AS kenh_lap,
    100 * countIf(tm.result = 'tu_choi') / count() AS ty_le_tu_choi
FROM invoices AS i FINAL
INNER JOIN tax_messages AS tm
    ON i.invoice_id = tm.invoice_id
WHERE
    i.tax_code_type = 'co_ma'
    AND toYear(i.issued_at) = 2024
    AND tm.message_type = '200'
GROUP BY kenh_lap
ORDER BY ty_le_tu_choi DESC`
- SQL chuẩn: `SELECT channel, 100 * countIf(status = 'cqt_tu_choi') / count() FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND status NOT IN ('nhap', 'da_ky') AND toYear(issued_at) = 2024 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['web', 1.4971074916687104], ['excel', 1.5009573404408165], ['pos', 1.4948555536419363], ['mobile', 1.4632595061549485], ['api', 1.486270820381018]]

### h20 (hard): Doanh thu tháng 5/2025 theo ngành kinh tế của người bán, sắp xếp giảm dần (tên ngành và doanh thu).
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.name AS ten_nganh,
    sum(dss.revenue_vnd) AS doanh_thu
FROM daily_seller_stats AS dss
INNER JOIN sellers AS s ON dss.seller_id = s.seller_id
INNER JOIN industries AS i ON s.industry_code = i.industry_code
WHERE dss.day >= toDate('2025-05-01') AND dss.day < toDate('2025-06-01')
GROUP BY i.name
ORDER BY i.name DESC, doanh_thu DESC`
- SQL chuẩn: `SELECT n.name, sum(d.revenue_vnd) AS doanh_thu FROM daily_seller_stats AS d JOIN sellers AS s ON s.seller_id = d.seller_id JOIN industries AS n ON n.industry_code = s.industry_code WHERE toYYYYMM(d.day) = 202505 GROUP BY n.name ORDER BY doanh_thu DESC`
- Kết quả dự đoán (5 dòng đầu): [['Y tế và hoạt động trợ giúp xã hội', 4961940896144.0], ['Xây dựng', 14456186494121.0], ['Vận tải kho bãi', 6348842003316.019], ['Thông tin và truyền thông', 5046754754134.0], ['Nông nghiệp, lâm nghiệp và thủy sản', 2006688954684.0]]
- Kết quả chuẩn (5 dòng đầu): [['Bán buôn và bán lẻ; sửa chữa ô tô, mô tô', 24557555592537.56], ['Công nghiệp chế biến, chế tạo', 17992054933995.473], ['Xây dựng', 14456186494121.0], ['Dịch vụ lưu trú và ăn uống', 7387790023048.0], ['Vận tải kho bãi', 6348842003316.018]]

### m15 (medium): Có bao nhiêu doanh nghiệp đang hoạt động lập ít hơn 10 hóa đơn (mọi trạng thái) trong tháng 6/2025, kể cả doanh nghiệp không lập hóa đơn nào?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Câu hỏi yêu cầu đếm cả những doanh nghiệp không lập hóa đơn nào, điều này đòi hỏi phải truy vấn bảng sellers và kết hợp với dữ liệu hóa đơn (LEFT JOIN hoặc subquery), nhưng không có bảng nào chứa thông tin "doanh nghiệp đã lập hóa đơn" một cách trực tiếp để loại trừ những doanh nghiệp không có hóa đơn. Hơn nữa, việc xác định "doanh nghiệp không lập hóa đơn nào" trong tháng 6/2025 cần phải kiểm tra sự vắng mặt của dữ liệu trong bảng invoices, điều này phức tạp và không thể thực hiện đơn giản bằng một truy vấn SELECT duy nhất mà không có các hàm đặc biệt hoặc logic phức tạp hơn (như NOT IN với subquery, nhưng điều này có thể gây lỗi nếu subquery trả về NULL hoặc rỗng). Tuy nhiên, lý do chính xác hơn là: Câu hỏi yêu cầu đếm "doanh nghiệp đang hoạt động" (sellers.status = 'active') và "lập ít hơn 10 hóa đơn" (bao gồm 0 hóa đơn). Để đếm những doanh nghiệp có 0 hóa đơn, ta cần lấy tất cả sellers active và LEFT JOIN với invoices, sau đó đếm những nhóm có count(invoices) < 10. Đây là một truy vấn hợp lệ. Hãy xem xét lại.

Truy vấn cần:
1. Lấy tất cả sellers có status = 'active'.
2. LEFT JOIN với invoices (FINAL) cho tháng 6/2025 (issued_at trong tháng 6/2025).
3. Nhóm theo seller_id.
4. Đếm số hóa đơn (count(invoices.invoice_id)).
5. Lọc những nhóm có count < 10.
6. Đếm số seller_id thỏa mãn.

Tuy nhiên, bảng invoices có 37 triệu dòng, việc LEFT JOIN toàn bộ sellers (50k) với invoices (37M) có thể rất nặng, nhưng về mặt cú pháp ClickHouse là khả thi.

Câu hỏi: "Có bao nhiêu doanh nghiệp đang hoạt động lập ít hơn 10 hóa đơn (mọi trạng thái) trong tháng 6/2025, kể cả doanh nghiệp không lập hóa đơn nào?"

"mọi trạng thái" nghĩa là không lọc status của hóa đơn.
"tháng 6/2025" nghĩa là issued_at trong khoảng từ 2025-06-01 đến 2025-06-30.

Truy vấn:
SELECT count() AS so_doanh_nghiep
FROM (
    SELECT s.seller_id
    FROM sellers s
    LEFT JOIN invoices i FINAL
        ON s.seller_id = i.seller_id
        AND toYear(i.issued_at) = 2025
        AND toMonth(i.issued_at) = 6
    WHERE s.status = 'active'
    GROUP BY s.seller_id
    HAVING count(i.invoice_id) < 10
)

Tuy nhiên, trong ClickHouse, LEFT JOIN với điều kiện trong ON clause là được hỗ trợ. Nhưng cần cẩn thận với FINAL.
Một cách khác hiệu quả hơn:
SELECT count() AS so_doanh_nghiep
FROM sellers s
WHERE s.status = 'active'
AND (
    SELECT count() FROM invoices i FINAL
    WHERE i.seller_id = s.seller_id
    AND toYear(i.issued_at) = 2025
    AND toMonth(i.issued_at) = 6
) < 10

Cách này dùng subquery tương quan, có thể chậm nhưng đúng nghĩa.
Hoặc dùng LEFT JOIN:
SELECT count() AS so_doanh_nghiep
FROM (
    SELECT s.seller_id, count(i.invoice_id) AS so_hoa_don
    FROM sellers s
    LEFT JOIN invoices i FINAL
    ON s.seller_id = i.seller_id
    AND toYear(i.issued_at) = 2025
    AND toMonth(i.issued_at) = 6
    WHERE s.status = 'active'
    GROUP BY s.seller_id
    HAVING so_hoa_don < 10
)

Tôi sẽ chọn cách LEFT JOIN vì nó chuẩn hơn cho việc đếm cả những người không có hóa đơn.

Lưu ý: "mọi trạng thái" nghĩa là không cần lọc status của invoice.

SELECT count() AS so_doanh_nghiep
FROM (
    SELECT s.seller_id
    FROM sellers s
    LEFT JOIN invoices i FINAL
    ON s.seller_id = i.seller_id
    AND toYear(i.issued_at) = 2025
    AND toMonth(i.issued_at) = 6
    WHERE s.status = 'active'
    GROUP BY s.seller_id
    HAVING count(i.invoice_id) < 10
)
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT count() FROM sellers AS s LEFT JOIN (SELECT seller_id, count() AS n FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202506 GROUP BY seller_id) AS c ON c.seller_id = s.seller_id WHERE s.status = 'active' AND (c.n IS NULL OR c.n < 10)`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5204]]
