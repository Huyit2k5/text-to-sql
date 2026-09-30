# Kết quả đánh giá

- Bộ đánh giá: 62 câu (58 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Baseline (Mức 1) | **36.2%** | 56% | 41% | 15% | 100% | 7 | 37.9% | 62 | 128,743/4,680 | 3.7s |  |
| + Mô tả cột | **79.3%** | 94% | 86% | 60% | 100% | 3 | 82.8% | 62 | 484,127/5,433 | 5.8s | +43.1 điểm so với dòng trên |
| + Few-shot | **87.9%** | 100% | 100% | 65% | 100% | 3 | 87.9% | 62 | 508,222/4,409 | 5.3s | +8.6 điểm so với dòng trên |
| + Schema linking | **87.9%** | 100% | 100% | 65% | 100% | 3 | 89.7% | 62 | 288,917/4,307 | 5.8s | +0.0 điểm so với dòng trên |
| + Tự sửa lỗi | **89.7%** | 100% | 100% | 70% | 100% | 1 | 91.4% | 66 | 310,800/4,809 | 4.9s | +1.7 điểm so với dòng trên; 2 câu có sửa lại |
| + Kiểm tra hình dạng | **91.4%** | 100% | 100% | 75% | 100% | 1 | 91.4% | 67 | 315,781/4,933 | 9.8s | +1.7 điểm so với dòng trên; 3 câu có sửa lại |

## Phân tích lỗi: Baseline (Mức 1) (37 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai điều kiện lọc | 11 | e03, e11, m04, m14, m20, m21, m22, h06, h07, h09, h16 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 7 | e05, m15, m17, h01, h11, h13, h14 |
| Sai hàm / khoảng ngày tháng | 7 | e06, m02, m07, m12, m13, h02, h20 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 4 | m01, h08, h15, h19 |
| Khác | 3 | e12, e15, m10 |
| Từ chối / hỏi lại nhầm | 2 | h10, h17 |
| Sai cột kết quả / số cột | 1 | e04 |
| Chọn sai bảng | 1 | h04 |
| Sai JOIN | 1 | h18 |

### e03 (easy): Có bao nhiêu hộ kinh doanh đang dùng dịch vụ hóa đơn điện tử (mọi trạng thái)?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_ho_kinh_doanh_dang_dung_dich_vu
FROM sellers
WHERE company_type = 'ho_kinh_doanh'`
- SQL chuẩn: `SELECT count() FROM sellers WHERE company_type = 'Hộ kinh doanh'`
- Kết quả dự đoán (5 dòng đầu): [[0]]
- Kết quả chuẩn (5 dòng đầu): [[5613]]

### e04 (easy): Liệt kê các gói dịch vụ kèm số hóa đơn của gói và giá niêm yết.
- Nhóm: Sai cột kết quả / số cột
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT plan_id, name, invoice_quota, price_vnd FROM service_plans`
- SQL chuẩn: `SELECT name, invoice_quota, price_vnd FROM service_plans`
- Kết quả dự đoán (5 dòng đầu): [[1, 'Gói 300 hóa đơn', 300, 390000.0], [2, 'Gói 500 hóa đơn', 500, 550000.0], [3, 'Gói 1.000 hóa đơn', 1000, 890000.0], [4, 'Gói 2.000 hóa đơn', 2000, 1590000.0], [5, 'Gói 5.000 hóa đơn', 5000, 3290000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Gói 300 hóa đơn', 300, 390000.0], ['Gói 500 hóa đơn', 500, 550000.0], ['Gói 1.000 hóa đơn', 1000, 890000.0], ['Gói 2.000 hóa đơn', 2000, 1590000.0], ['Gói 5.000 hóa đơn', 5000, 3290000.0]]

### e05 (easy): Có bao nhiêu doanh nghiệp đang dùng tính năng tích hợp API?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Function 'in' is supported only if second argument is constant or table expression.
- SQL dự đoán: `SELECT count() AS so_doanh_nghiep_dung_api
FROM sellers
WHERE 'api_integration' IN features`
- SQL chuẩn: `SELECT count() FROM sellers WHERE has(features, 'api')`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[7784]]

### e06 (easy): Trong tháng 6/2025 có bao nhiêu hóa đơn hợp lệ được lập?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_hoa_don_hop_le
FROM invoices
WHERE toStartOfMonth(issued_at) = toDate('2025-06-01')
  AND status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202506`
- Kết quả dự đoán (5 dòng đầu): [[1359342]]
- Kết quả chuẩn (5 dòng đầu): [[1146292]]

### e11 (easy): Có bao nhiêu mã lỗi phản hồi của cơ quan thuế thuộc nhóm lỗi kỹ thuật?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_ma_loi_loi_ky_thuat
FROM tax_error_codes
WHERE category = 'loi_ky_thuat'`
- SQL chuẩn: `SELECT count() FROM tax_error_codes WHERE category = 'ky_thuat'`
- Kết quả dự đoán (5 dòng đầu): [[0]]
- Kết quả chuẩn (5 dòng đầu): [[2]]

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
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Identifier 'i.vat_rate' cannot be resolved from table with name i. In scope SELECT i.vat_rate AS thue_suat, sum(i.total_vat * i.exchange_rate) AS tong_thue_gtgt_vnd FROM invoices AS i WHERE (i.invoice_type = 'gtgt') AND (i.status IN ('nhap', 'da_ky', 'cho_cap_ma', 'cqt_cap_ma', 'da_gui_cqt')) AND (toStartOfMonth(i.issued_at) = toDate('2025-03-01')) GROUP BY i.vat_rate ORDER BY i.vat_rate ASC. Maybe you meant: ['i.nature'].
- SQL dự đoán: `SELECT
    i.vat_rate AS thue_suat,
    sum(i.total_vat * i.exchange_rate) AS tong_thue_gtgt_vnd
FROM invoices i
WHERE
    i.invoice_type = 'gtgt'
    AND i.status IN ('nhap', 'da_ky', 'cho_cap_ma', 'cqt_cap_ma', 'da_gui_cqt')
    AND toStartOfMonth(i.issued_at) = toDate('2025-03-01')
GROUP BY i.vat_rate
ORDER BY i.vat_rate`
- SQL chuẩn: `SELECT it.vat_rate, sum(it.vat_amount * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202503) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202503 GROUP BY it.vat_rate`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['KKKNT', 0.0], ['KCT', 0.0], ['8%', 3448261813099.0], ['0%', 0.0], ['10%', 1215067799255.0]]

### h02 (hard): 5 nhóm hàng có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024 trên các hóa đơn hợp lệ.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    ii.product_group,
    sum(ii.line_amount - ii.discount_amount) AS doanh_thu_chua_thue
FROM invoice_items ii
INNER JOIN invoices i ON ii.invoice_id = i.invoice_id
WHERE toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
  AND i.status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY ii.product_group
ORDER BY doanh_thu_chua_thue DESC
LIMIT 5`
- SQL chuẩn: `SELECT it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY it.product_group ORDER BY doanh_thu DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['Vật liệu xây dựng', 79597536146846.0], ['Dịch vụ tư vấn', 26863370089054.0], ['Dịch vụ ăn uống', 23268682910087.0], ['Nông sản và vật tư nông nghiệp', 20694351331238.0], ['Sắt thép', 18307608784623.0]]
- Kết quả chuẩn (5 dòng đầu): [['Vật liệu xây dựng', 66796102577154.0], ['Hàng xuất khẩu', 36158248955087.0], ['Dịch vụ tư vấn', 22530750068385.0], ['Dịch vụ ăn uống', 19433382638177.0], ['Nông sản và vật tư nông nghiệp', 17313756316558.0]]

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH monthly_revenue AS (
    SELECT
        formatDateTime(day, '%Y-%m') AS month,
        sum(revenue_vnd) AS revenue
    FROM daily_seller_stats
    WHERE day >= toDate('2024-12-01') AND day <= toDate('2025-06-30')
    GROUP BY month
)
SELECT
    month,
    revenue,
    round((revenue - lagInFrame(revenue, 1) OVER (ORDER BY month)) / lagInFrame(revenue, 1) OVER (ORDER BY month) * 100, 2) AS growth_pct
FROM monthly_revenue
WHERE month >= '2025-01'
ORDER BY month`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 95998159808994.97, inf], ['2025-02', 76423585126203.75, -20.39], ['2025-03', 95036166855908.44, 24.35], ['2025-04', 94197039637282.66, -0.88], ['2025-05', 98998383826908.88, 5.1]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h06 (hard): Mỗi tháng của năm 2025 có bao nhiêu người mua khác nhau trên các hóa đơn hợp lệ (tháng ghi dạng 2025-01)?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    formatDateTime(issued_at, '%Y-%m') AS month,
    uniqExact(buyer_id) AS unique_buyers
FROM invoices
WHERE toYear(issued_at) = 2025
  AND buyer_id IS NOT NULL
  AND status != 'da_huy'
GROUP BY month
ORDER BY month`
- SQL chuẩn: `SELECT formatDateTime(issued_at, '%Y-%m') AS thang, uniqExact(buyer_id) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2025 GROUP BY thang`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 664591], ['2025-02', 558114], ['2025-03', 659024], ['2025-04', 654052], ['2025-05', 679553]]
- Kết quả chuẩn (5 dòng đầu): [['2025-05', 649179], ['2025-04', 624252], ['2025-01', 634250], ['2025-06', 660833], ['2025-02', 531185]]

### h07 (hard): Trong các doanh nghiệp lập ít nhất 1.000 hóa đơn năm 2024, doanh nghiệp nào có tỷ lệ hóa đơn bị hủy cao nhất? Cho biết mã số thuế, tên và tỷ lệ (%).
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    s.tax_code,
    s.name,
    (countIf(i.status = 'da_huy') * 100.0 / count()) AS huy_rate_pct
FROM invoices i
JOIN sellers s ON i.seller_id = s.seller_id
WHERE toYear(i.issued_at) = 2024
GROUP BY s.seller_id, s.tax_code, s.name
HAVING count() >= 1000
ORDER BY huy_rate_pct DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, 100 * countIf(i.status = 'da_huy') / count() AS ty_le FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE toYear(i.issued_at) = 2024 GROUP BY s.seller_id, s.tax_code, s.name HAVING count() >= 1000 ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['7978850259', 'Công ty Cổ phần Dịch vụ Ăn uống An Phát Cửu Long', 2.588996763754045]]
- Kết quả chuẩn (5 dòng đầu): [['7460498778', 'Công ty TNHH Tư vấn Long Hải 86', 3.0592734225621414]]

### h08 (hard): Trong ngày 18/03/2025, khung giờ nào có tỷ lệ lỗi API cao nhất? Cho biết giờ (0-23) và tỷ lệ lỗi (%).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toHour(ts) AS gio,
    round(100.0 * countIf(http_status >= 400) / count(), 2) AS ty_le_loi_pct
FROM api_requests
WHERE ts >= toDateTime('2025-03-18 00:00:00')
  AND ts < toDateTime('2025-03-19 00:00:00')
GROUP BY gio
ORDER BY ty_le_loi_pct DESC
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
WHERE ts >= toDateTime('2025-06-01 00:00:00', 'UTC')
  AND ts < toDateTime('2025-07-01 00:00:00', 'UTC')
GROUP BY endpoint`
- SQL chuẩn: `SELECT endpoint, quantileExact(0.95)(latency_ms) FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202506 GROUP BY endpoint`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/cancel', 786.4499999999998], ['/api/invoice/search', 379.0], ['/api/invoice/create', 558.4499999999998], ['/api/auth/token', 190.0], ['/api/invoice/publish', 3787.0]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/cancel', 803], ['/api/invoice/search', 377], ['/api/invoice/create', 567], ['/api/auth/token', 188], ['/api/invoice/publish', 3773]]

### h10 (hard): Trong các doanh nghiệp mua gói lần đầu trong năm 2023, bao nhiêu phần trăm mua thêm gói trong vòng 365 ngày sau lần mua đầu tiên?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Dữ liệu không có thông tin về "mua lần đầu" hay "mua thêm" gói dịch vụ, chỉ có bảng subscriptions ghi lại các lần mua nhưng không có cột chỉ định đây là lần đầu hay lần mua sau
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h11 (hard): Với các doanh nghiệp đăng ký dịch vụ từ năm 2023 trở đi, trung bình mất bao nhiêu ngày từ lúc đăng ký đến khi lập hóa đơn đầu tiên (hóa đơn ở bất kỳ trạng thái nào, kể cả nháp)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Aggregate function min(i.issued_at) is found inside another aggregate function in query.
- SQL dự đoán: `SELECT
    avg(dateDiff('day', s.registered_at, min(i.issued_at))) AS avg_days_to_first_invoice
FROM
    sellers s
JOIN
    invoices i ON s.seller_id = i.seller_id
WHERE
    s.registered_at >= toDate('2023-01-01')
GROUP BY
    s.seller_id
HAVING
    count() > 0`
- SQL chuẩn: `SELECT avg(dateDiff('day', s.registered_at, f.dau_tien)) FROM sellers AS s JOIN (SELECT seller_id, toDate(min(issued_at)) AS dau_tien FROM invoices GROUP BY seller_id) AS f ON f.seller_id = s.seller_id WHERE s.registered_at >= toDate('2023-01-01')`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[2.088904694167852]]

### h13 (hard): Trong ngày 02/01/2025, có bao nhiêu hóa đơn phải gửi đề nghị cấp mã tới cơ quan thuế nhiều hơn một lần?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Syntax error: failed at position 232 (() (line 8, col 23): () > 1
)
 FORMAT Native. Expected one of: token, DoubleColon, OR, AND, IS NOT DISTINCT FROM, IS NULL, IS NOT NULL, BETWEEN, NOT BETWEEN, LIKE, ILIKE, NOT LIKE, NOT ILIKE, REGEXP, IN, NOT IN, GLOBAL IN, GLOBAL NOT IN, MOD, DIV, alias, AS, WINDOW, QUALIFY, ORDER BY, LIMIT, OFFSET, FETCH, SETTINGS, UNION, EXCEPT, INTERSECT.
- SQL dự đoán: `SELECT count() AS so_hoa_don_gui_nhieu_hon_mot_lan
FROM (
    SELECT invoice_id
    FROM tax_messages
    WHERE message_type = 'cap_ma'
      AND toDate(sent_at) = toDate('2025-01-02')
    GROUP BY invoice_id
    HAVING count() > 1() > 1
)`
- SQL chuẩn: `SELECT count() FROM (SELECT invoice_id FROM tax_messages WHERE message_type = '200' AND toDate(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) = toDate('2025-01-02') GROUP BY invoice_id HAVING count() > 1)`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[3778]]

### h14 (hard): Năm 2024, doanh nghiệp có mã số thuế 0184171901 đạt doanh thu bao nhiêu và có bao nhiêu người mua khác nhau?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Illegal type AggregateFunction(uniqExact, UInt64) of argument for aggregate function with Merge suffix. because it corresponds to different aggregate function: uniqExact instead of uniqState.
- SQL dự đoán: `SELECT
    sum(dss.revenue_vnd) AS doanh_thu,
    uniqStateMerge(dss.buyers) AS so_nguoi_mua_khac_nhau
FROM daily_seller_stats dss
JOIN sellers s ON dss.seller_id = s.seller_id
WHERE s.tax_code = '0184171901'
  AND toYear(dss.day) = 2024`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate), uniqExact(buyer_id) FROM invoices FINAL WHERE seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '0184171901') AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[9160037938443.0, 3051]]

### h15 (hard): Tỷ trọng (%) doanh thu theo từng loại tiền (VND, USD, EUR) trong tổng doanh thu năm 2024, tính sau khi quy đổi ra VND.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    currency,
    sum(total_amount * exchange_rate) AS revenue_vnd,
    round(100 * sum(total_amount * exchange_rate) / sum(sum(total_amount * exchange_rate)) OVER (), 2) AS percentage
FROM invoices
WHERE toYear(issued_at) = 2024
GROUP BY currency
ORDER BY revenue_vnd DESC`
- SQL chuẩn: `SELECT currency, 100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency`
- Kết quả dự đoán (5 dòng đầu): [['VND', 1313712355826918.0, 88.22], ['USD', 140275247836129.19, 9.42], ['EUR', 35081637925024.824, 2.36]]
- Kết quả chuẩn (5 dòng đầu): [['EUR', 2.47544734219474], ['USD', 9.903198347516758], ['VND', 87.62135431028862]]

### h16 (hard): Ở Hà Nội, TP. Hồ Chí Minh và Đà Nẵng, mỗi nơi doanh nghiệp nào có nhiều hóa đơn hợp lệ nhất năm 2024? Cho biết tỉnh/thành, mã số thuế, tên và số hóa đơn.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH valid_invoices AS (
    SELECT
        s.province_code,
        s.tax_code,
        s.name,
        count() AS invoice_count
    FROM invoices i
    INNER JOIN sellers s ON i.seller_id = s.seller_id
    WHERE toYear(i.issued_at) = 2024
      AND i.status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')
      AND s.province_code IN (
          SELECT province_code FROM provinces WHERE name IN ('Hà Nội', 'TP. Hồ Chí Minh', 'Đà Nẵng')
      )
    GROUP BY s.province_code, s.tax_code, s.name
),
ranked AS (
    SELECT
        p.name AS tinh_thanh,
        vi.tax_code,
        vi.name AS ten_doanh_nghiep,
        vi.invoice_count,
        RANK() OVER (PARTITION BY vi.province_code ORDER BY vi.invoice_count DESC) AS rnk
    FROM valid_invoices vi
    INNER JOIN provinces p ON vi.province_code = p.province_code
)
SELECT
    tinh_thanh,
    tax_code,
    ten_doanh_nghiep,
    invoice_count
FROM ranked
WHERE rnk = 1
ORDER BY tinh_thanh`
- SQL chuẩn: `SELECT p.name, s.tax_code, s.name, count() AS so_hd FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(i.issued_at) = 2024 AND s.province_code IN ('01', '79', '48') GROUP BY p.name, s.seller_id, s.tax_code, s.name ORDER BY p.name, so_hd DESC LIMIT 1 BY p.name`
- Kết quả dự đoán (5 dòng đầu): [['Hà Nội', '0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 68076], ['TP. Hồ Chí Minh', '7934474156', 'Công ty TNHH Thương mại An Phát', 186822], ['Đà Nẵng', '4897360640', 'Công ty TNHH Vận tải Hoàng Gia', 20780]]
- Kết quả chuẩn (5 dòng đầu): [['Hà Nội', '0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 52414], ['TP. Hồ Chí Minh', '7934474156', 'Công ty TNHH Thương mại An Phát', 162123], ['Đà Nẵng', '4897360640', 'Công ty TNHH Vận tải Hoàng Gia', 17998]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Dữ liệu không có thông tin về chính sách giảm thuế hay thuế suất gốc (10%) để tính toán mức tăng thêm
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[994295801179.54]]

### h18 (hard): Có bao nhiêu doanh nghiệp đang hoạt động mà chứng thư số còn hiệu lực cuối cùng sẽ hết hạn trong 15 ngày tới (tính từ hôm nay) và chưa có chứng thư nào mới hơn?
- Nhóm: Sai JOIN
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_doanh_nghiep
FROM (
    SELECT s.seller_id
    FROM sellers s
    WHERE s.status = 'active'
    AND s.company_type = 'doanh_nghiep'
    AND s.seller_id IN (
        SELECT seller_id
        FROM certificates
        WHERE valid_to >= toDate('2025-06-30')
        AND valid_to <= toDate('2025-06-30') + INTERVAL 15 DAY
        AND revoked = 0
        AND certificate_id = (
            SELECT max(c2.certificate_id)
            FROM certificates c2
            WHERE c2.seller_id = certificates.seller_id
        )
    )
)`
- SQL chuẩn: `SELECT count() FROM (SELECT seller_id, max(valid_to) AS het_han FROM certificates WHERE revoked = 0 GROUP BY seller_id) AS c JOIN sellers AS s ON s.seller_id = c.seller_id WHERE s.status = 'active' AND c.het_han >= toDate('2025-06-30') AND c.het_han <= toDate('2025-06-30') + 15`
- Kết quả dự đoán (5 dòng đầu): [[0]]
- Kết quả chuẩn (5 dòng đầu): [[1158]]

### h19 (hard): Với hóa đơn có mã lập năm 2024, tỷ lệ (%) bị cơ quan thuế từ chối theo từng kênh lập hóa đơn là bao nhiêu?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.channel AS channel,
    count() AS total_invoices,
    countIf(t.result = 'tu_choi') AS rejected_count,
    (countIf(t.result = 'tu_choi') / count()) * 100 AS rejection_rate_pct
FROM invoices i
INNER JOIN tax_messages t ON i.invoice_id = t.invoice_id
WHERE toYear(i.issued_at) = 2024
GROUP BY i.channel
ORDER BY i.channel`
- SQL chuẩn: `SELECT channel, 100 * countIf(status = 'cqt_tu_choi') / count() FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND status NOT IN ('nhap', 'da_ky') AND toYear(issued_at) = 2024 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): [['api', 4264847, 37593, 0.8814618672135248], ['excel', 1360029, 12240, 0.8999808092327443], ['mobile', 493435, 4360, 0.8836016901922239], ['pos', 1204040, 11006, 0.91408923291585], ['web', 9362566, 84192, 0.8992406568882931]]
- Kết quả chuẩn (5 dòng đầu): [['web', 1.4971074916687104], ['api', 1.486270820381018], ['pos', 1.4948555536419363], ['excel', 1.5009573404408165], ['mobile', 1.4632595061549485]]

### h20 (hard): Doanh thu tháng 5/2025 theo ngành kinh tế của người bán, sắp xếp giảm dần (tên ngành và doanh thu).
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.name AS ten_nganh,
    sum(dss.revenue_vnd) AS doanh_thu
FROM daily_seller_stats dss
INNER JOIN sellers s ON dss.seller_id = s.seller_id
INNER JOIN industries i ON s.industry_code = i.industry_code
WHERE dss.day >= toDate('2025-05-01')
  AND dss.day < toDate('2025-06-01')
GROUP BY i.name
ORDER BY i.name DESC, doanh_thu DESC`
- SQL chuẩn: `SELECT n.name, sum(d.revenue_vnd) AS doanh_thu FROM daily_seller_stats AS d JOIN sellers AS s ON s.seller_id = d.seller_id JOIN industries AS n ON n.industry_code = s.industry_code WHERE toYYYYMM(d.day) = 202505 GROUP BY n.name ORDER BY doanh_thu DESC`
- Kết quả dự đoán (5 dòng đầu): [['Y tế và hoạt động trợ giúp xã hội', 4961940896144.0], ['Xây dựng', 14456186494121.0], ['Vận tải kho bãi', 6348842003316.0205], ['Thông tin và truyền thông', 5046754754134.0], ['Nông nghiệp, lâm nghiệp và thủy sản', 2006688954684.0]]
- Kết quả chuẩn (5 dòng đầu): [['Bán buôn và bán lẻ; sửa chữa ô tô, mô tô', 24557555592537.56], ['Công nghiệp chế biến, chế tạo', 17992054933995.47], ['Xây dựng', 14456186494121.0], ['Dịch vụ lưu trú và ăn uống', 7387790023048.0], ['Vận tải kho bãi', 6348842003316.018]]

### m01 (medium): Doanh thu chưa thuế theo từng tháng năm 2024 (tháng ghi dạng 2024-01).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    formatDateTime(issued_at, '%Y-%m') AS thang,
    sum(total_before_tax) AS doanh_thu_chua_thue
FROM invoices
WHERE toYear(issued_at) = 2024
GROUP BY thang
ORDER BY thang`
- SQL chuẩn: `SELECT formatDateTime(issued_at, '%Y-%m') AS thang, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY thang`
- Kết quả dự đoán (5 dòng đầu): [['2024-01', 97328772168484.2], ['2024-02', 75949430064139.12], ['2024-03', 92575572732434.53], ['2024-04', 96381706182482.44], ['2024-05', 99637528841595.9]]
- Kết quả chuẩn (5 dòng đầu): [['2024-07', 80923783673919.88], ['2024-06', 78684075505558.81], ['2024-05', 77411517024593.34], ['2024-04', 74836199206639.08], ['2024-03', 72072680618109.94]]

### m02 (medium): 5 tỉnh/thành có nhiều hóa đơn hợp lệ nhất trong quý 1/2025 (theo trụ sở người bán), kèm số hóa đơn.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.name AS tinh_thanh,
    count() AS so_hoa_don
FROM invoices i
JOIN sellers s ON i.seller_id = s.seller_id
JOIN provinces p ON s.province_code = p.province_code
WHERE toQuarter(i.issued_at) = 1
  AND toYear(i.issued_at) = 2025
  AND i.status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY p.name
ORDER BY so_hoa_don DESC
LIMIT 5`
- SQL chuẩn: `SELECT p.name, count() AS so_hd FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND i.issued_at >= toDateTime('2025-01-01 00:00:00', 'Asia/Ho_Chi_Minh') AND i.issued_at < toDateTime('2025-04-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY p.name ORDER BY so_hd DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['TP. Hồ Chí Minh', 909308], ['Hà Nội', 729449], ['Hải Phòng', 119465], ['Đà Nẵng', 117980], ['Bình Dương', 111472]]
- Kết quả chuẩn (5 dòng đầu): [['TP. Hồ Chí Minh', 763414], ['Hà Nội', 610113], ['Hải Phòng', 100282], ['Đà Nẵng', 99553], ['Bình Dương', 93500]]

### m04 (medium): Trong năm 2024, bao nhiêu phần trăm thông điệp gửi hóa đơn đề nghị cấp mã bị cơ quan thuế từ chối?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    round(
        countIf(result = 'tu_choi') * 100.0 / count(),
        2
    ) AS percent_rejected
FROM tax_messages
WHERE message_type = 'gui_hoa_don_de_nghi_cap_ma'
  AND toYear(sent_at) = 2024`
- SQL chuẩn: `SELECT 100 * countIf(result = 'tu_choi') / count() FROM tax_messages WHERE message_type = '200' AND toYear(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[nan]]
- Kết quả chuẩn (5 dòng đầu): [[1.4496327363543322]]

### m07 (medium): Số request API theo từng endpoint trong tháng 5/2025.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT endpoint, count() AS request_count FROM api_requests WHERE ts >= toDate('2025-05-01') AND ts < toDate('2025-06-01') GROUP BY endpoint`
- SQL chuẩn: `SELECT endpoint, count() FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202505 GROUP BY endpoint`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/cancel', 18106], ['/api/invoice/search', 365025], ['/api/invoice/create', 550679], ['/api/auth/token', 163858], ['/api/invoice/publish', 274256]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/cancel', 18102], ['/api/invoice/search', 365023], ['/api/invoice/create', 550666], ['/api/auth/token', 163825], ['/api/invoice/publish', 274219]]

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
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.channel AS "Kênh lập hóa đơn",
    count() AS "Số hóa đơn hợp lệ"
FROM invoices i
WHERE toYear(i.issued_at) = 2025
  AND toMonth(i.issued_at) = 6
  AND i.status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY i.channel`
- SQL chuẩn: `SELECT channel, count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202506 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): [['mobile', 40977], ['pos', 98659], ['web', 772562], ['api', 334839], ['excel', 112305]]
- Kết quả chuẩn (5 dòng đầu): [['mobile', 34628], ['pos', 83456], ['web', 651644], ['api', 282104], ['excel', 94460]]

### m13 (medium): Thời gian phản hồi trung bình (giây) của cơ quan thuế với các thông điệp đề nghị cấp mã được chấp nhận trong tháng 6/2025.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    avg(dateDiff('second', sent_at, response_at) / 1000.0) AS avg_response_time_seconds
FROM
    tax_messages
WHERE
    message_type = 'de_xin_cap_ma'
    AND result = 'chap_nhan'
    AND toStartOfMonth(sent_at) = toDate('2025-06-01')`
- SQL chuẩn: `SELECT avg(dateDiff('second', sent_at, response_at)) FROM tax_messages WHERE message_type = '200' AND result = 'chap_nhan' AND toYYYYMM(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) = 202506`
- Kết quả dự đoán (5 dòng đầu): [[None]]
- Kết quả chuẩn (5 dòng đầu): [[148.79127469593172]]

### m14 (medium): 10 mã lỗi khiến cơ quan thuế từ chối nhiều nhất năm 2024, kèm mô tả lỗi và số lần.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    tme.error_code,
    tme.description,
    count() AS so_lan_tu_choi
FROM tax_messages tm
INNER JOIN tax_error_codes tme ON tm.error_code = tme.error_code
WHERE tm.result = 'tu_choi'
  AND toYear(tm.sent_at) = 2024
GROUP BY tme.error_code, tme.description
ORDER BY so_lan_tu_choi DESC
LIMIT 10`
- SQL chuẩn: `SELECT e.error_code, e.description, count() AS so_lan FROM tax_messages AS t JOIN tax_error_codes AS e ON e.error_code = t.error_code WHERE t.result = 'tu_choi' AND toYear(toTimeZone(t.sent_at, 'Asia/Ho_Chi_Minh')) = 2024 GROUP BY e.error_code, e.description ORDER BY so_lan DESC LIMIT 10`
- Kết quả dự đoán (5 dòng đầu): [['KTMST02', 'Mã số thuế người mua sai định dạng', 31455], ['KTMST03', 'Mã số thuế người mua không tồn tại', 25062], ['DD02', 'Thiếu thông tin bắt buộc trên hóa đơn', 23917], ['TT01', 'Tổng tiền không khớp với chi tiết hàng hóa', 18976], ['TT02', 'Thuế suất không phù hợp tại thời điểm lập hóa đơn', 15145]]
- Kết quả chuẩn (5 dòng đầu): [['KTMST02', 'Mã số thuế người mua sai định dạng', 31454], ['KTMST03', 'Mã số thuế người mua không tồn tại', 25062], ['DD02', 'Thiếu thông tin bắt buộc trên hóa đơn', 23912], ['TT01', 'Tổng tiền không khớp với chi tiết hàng hóa', 18978], ['TT02', 'Thuế suất không phù hợp tại thời điểm lập hóa đơn', 15141]]

### m15 (medium): Có bao nhiêu doanh nghiệp đang hoạt động lập ít hơn 10 hóa đơn (mọi trạng thái) trong tháng 6/2025, kể cả doanh nghiệp không lập hóa đơn nào?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Syntax error: failed at position 158 (LEFT) (line 7, col 5): LEFT JOIN invoices i
    ON s.seller_id = i.seller_id
    AND toYear(i.issued_at) = 2025
    AND toMonth(i.issued_at) = 6
    GROUP BY s.seller_id
    HAVING count(i... Expected one of: OR, AND, IS NOT DISTINCT FROM, IS NULL, IS NOT NULL, BETWEEN, NOT BETWEEN, LIKE, ILIKE, NOT LIKE, NOT ILIKE, REGEXP, IN, NOT IN, GLOBAL IN, GLOBAL NOT IN, MOD, DIV, alias, AS, GROUP BY, WITH, HAVING, WINDOW, QUALIFY, ORDER BY, LIMIT, OFFSET, FETCH, SETTINGS, UNION, EXCEPT, INTERSECT.
- SQL dự đoán: `SELECT count() AS so_doanh_nghiep
FROM (
    SELECT s.seller_id
    FROM sellers s
    WHERE s.status = 'active'
    AND s.company_type = 'doanh_nghiep'
    LEFT JOIN invoices i
    ON s.seller_id = i.seller_id
    AND toYear(i.issued_at) = 2025
    AND toMonth(i.issued_at) = 6
    GROUP BY s.seller_id
    HAVING count(i.invoice_id) < 10
)`
- SQL chuẩn: `SELECT count() FROM sellers AS s LEFT JOIN (SELECT seller_id, count() AS n FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202506 GROUP BY seller_id) AS c ON c.seller_id = s.seller_id WHERE s.status = 'active' AND (c.n IS NULL OR c.n < 10)`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5204]]

### m17 (medium): Tỷ lệ (%) hóa đơn hợp lệ năm 2024 không có thông tin người mua (khách lẻ).
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Syntax error: failed at position 152 (4) (line 8, col 2): 4
 FORMAT Native. Expected one of: token, DoubleColon, OR, AND, IS NOT DISTINCT FROM, IS NULL, IS NOT NULL, BETWEEN, NOT BETWEEN, LIKE, ILIKE, NOT LIKE, NOT ILIKE, REGEXP, IN, NOT IN, GLOBAL IN, GLOBAL NOT IN, MOD, DIV, alias, AS, GROUP BY, WITH, HAVING, WINDOW, QUALIFY, ORDER BY, LIMIT, OFFSET, FETCH, SETTINGS, UNION, EXCEPT, INTERSECT, INTO OUTFILE, FORMAT, ParallelWithClause, PARALLEL WITH, end of query.
- SQL dự đoán: `SELECT
    round(
        countIf(buyer_id IS NULL) * 100.0 / count(),
        2
    ) AS ty_le_khach_le
FROM invoices
WHERE toYear(issued_at) = 2024
 4`
- SQL chuẩn: `SELECT 100 * countIf(buyer_id IS NULL) / count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[22.79076181710743]]

### m20 (medium): Tổng giá trị thanh toán (quy ra VND) của các hóa đơn hợp lệ lập bằng USD trong năm 2024.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) AS tong_gia_tri_vnd
FROM invoices
WHERE currency = 'USD'
  AND toYear(issued_at) = 2024
  AND status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')`
- SQL chuẩn: `SELECT sum(total_amount * exchange_rate) FROM invoices FINAL WHERE currency = 'USD' AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): [[115103156282261.16]]
- Kết quả chuẩn (5 dòng đầu): [[96677915997293.22]]

### m21 (medium): Số hóa đơn hợp lệ năm 2024 theo loại hóa đơn (GTGT / bán hàng) và theo có mã / không mã.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    invoice_type,
    tax_code_type,
    count() AS so_hoa_don_hop_le
FROM invoices
WHERE toYear(issued_at) = 2024
  AND status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY invoice_type, tax_code_type`
- SQL chuẩn: `SELECT invoice_type, tax_code_type, count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY invoice_type, tax_code_type`
- Kết quả dự đoán (5 dòng đầu): [['gtgt', 'co_ma', 7388598], ['ban_hang', 'co_ma', 1793890], ['gtgt', 'khong_ma', 3322783], ['ban_hang', 'khong_ma', 692765]]
- Kết quả chuẩn (5 dòng đầu): [['gtgt', 'co_ma', 6419826], ['ban_hang', 'co_ma', 1558691], ['gtgt', 'khong_ma', 2559916], ['ban_hang', 'khong_ma', 534264]]

### m22 (medium): Tháng nào của năm 2024 có nhiều hóa đơn hợp lệ nhất (tháng ghi 1-12), bao nhiêu hóa đơn?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT toMonth(issued_at) AS thang, count() AS so_hoa_don
FROM invoices
WHERE toYear(issued_at) = 2024
  AND status IN ('da_ky', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY toMonth(issued_at)
ORDER BY so_hoa_don DESC
LIMIT 1`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, count() AS so_hd FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY thang ORDER BY so_hd DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[12, 1476457]]
- Kết quả chuẩn (5 dòng đầu): [[12, 1238479]]

## Phân tích lỗi: + Kiểm tra hình dạng (5 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Chọn sai bảng | 3 | h04, h16, h17 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 1 | h10 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h12 |

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT formatDateTime(day, '%Y-%m') AS thang, sum(revenue_vnd) AS doanh_thu, round(100 * (sum(revenue_vnd) - lagInFrame(sum(revenue_vnd), 1, 0) OVER (ORDER BY day)) / lagInFrame(sum(revenue_vnd), 1, 0) OVER (ORDER BY day), 2) AS tang_truong_pct FROM daily_seller_stats WHERE toYYYYMM(day) BETWEEN 202412 AND 202512 GROUP BY day ORDER BY day`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): [['2024-12', 1116063711944.91, inf], ['2024-12', 5914641043426.585, 429.96], ['2024-12', 3477185328796.3906, -41.21], ['2024-12', 3514037245780.8794, 1.06], ['2024-12', 3555285621056.0234, 1.17]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h10 (hard): Trong các doanh nghiệp mua gói lần đầu trong năm 2023, bao nhiêu phần trăm mua thêm gói trong vòng 365 ngày sau lần mua đầu tiên?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Aggregate function min(s.purchased_at) is found inside another aggregate function in query.
- SQL dự đoán: `SELECT 100.0 * countIf(repeat_count > 0) / count() AS ty_le_mua_them FROM (SELECT s.seller_id, min(s.purchased_at) AS first_purchase, countIf(s.purchased_at > min(s.purchased_at) AND s.purchased_at <= min(s.purchased_at) + INTERVAL 365 DAY) AS repeat_count FROM subscriptions AS s WHERE toYear(s.purchased_at) = 2023 GROUP BY s.seller_id HAVING first_purchase >= toDate('2023-01-01') AND first_purchase <= toDate('2023-12-31'))`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h12 (hard): Hóa đơn hợp lệ có giá trị thanh toán (quy ra VND) lớn nhất trong tháng 5/2025 là của doanh nghiệp nào? Cho biết mã số thuế, tên doanh nghiệp và số tiền.
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code, s.name, sum(i.total_amount * i.exchange_rate) AS gia_tri_thanh_toan_vnd FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY gia_tri_thanh_toan_vnd DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, i.total_amount * i.exchange_rate AS gia_tri FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 ORDER BY gia_tri DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 874190960147.0]]
- Kết quả chuẩn (5 dòng đầu): [['7966472767', 'Công ty TNHH Thương mại Mai Linh Miền Bắc', 6428990761.440001]]

### h16 (hard): Ở Hà Nội, TP. Hồ Chí Minh và Đà Nẵng, mỗi nơi doanh nghiệp nào có nhiều hóa đơn hợp lệ nhất năm 2024? Cho biết tỉnh/thành, mã số thuế, tên và số hóa đơn.
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT p.name AS tinh_thanh, s.tax_code, s.name AS ten_doanh_nghiep, sum(d.invoice_count) AS so_hoa_don
FROM daily_seller_stats AS d
JOIN sellers AS s ON s.seller_id = d.seller_id
JOIN provinces AS p ON p.province_code = s.province_code
WHERE p.province_code IN ('01', '79', '78')
  AND toYear(d.day) = 2024
GROUP BY p.province_code, p.name, s.seller_id, s.tax_code, s.name
ORDER BY p.province_code, so_hoa_don DESC
LIMIT 1 BY p.province_code`
- SQL chuẩn: `SELECT p.name, s.tax_code, s.name, count() AS so_hd FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(i.issued_at) = 2024 AND s.province_code IN ('01', '79', '48') GROUP BY p.name, s.seller_id, s.tax_code, s.name ORDER BY p.name, so_hd DESC LIMIT 1 BY p.name`
- Kết quả dự đoán (5 dòng đầu): [['Hà Nội', '0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 52414], ['TP. Hồ Chí Minh', '7934474156', 'Công ty TNHH Thương mại An Phát', 162123]]
- Kết quả chuẩn (5 dòng đầu): [['Hà Nội', '0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 52414], ['TP. Hồ Chí Minh', '7934474156', 'Công ty TNHH Thương mại An Phát', 162123], ['Đà Nẵng', '4897360640', 'Công ty TNHH Vận tải Hoàng Gia', 17998]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_vat * exchange_rate) * 0.25 AS tang_them_thue FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412`
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): [[1421016284450.75]]
- Kết quả chuẩn (5 dòng đầu): [[994295801179.54]]
