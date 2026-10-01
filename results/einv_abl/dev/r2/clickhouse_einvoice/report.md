# Kết quả đánh giá

- Bộ đánh giá: 62 câu (58 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cold_conv | **82.8%** | 94% | 100% | 55% | 100% | 1 | 86.2% | 65 | 243,042/5,637 | 4.1s | 3 câu có sửa lại |
| cold_snip | **77.6%** | 88% | 91% | 55% | 100% | 1 | 81.0% | 66 | 238,297/5,162 | 4.2s | -5.2 điểm so với dòng trên; 4 câu có sửa lại |

## Phân tích lỗi: cold_conv (10 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai hàm / khoảng ngày tháng | 3 | h02, h09, h20 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 2 | h10, h12 |
| Sai cột kết quả / số cột | 1 | e04 |
| Sai điều kiện lọc | 1 | h15 |
| Chọn sai bảng | 1 | h17 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h18 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 1 | h19 |

### e04 (easy): Liệt kê các gói dịch vụ kèm số hóa đơn của gói và giá niêm yết.
- Nhóm: Sai cột kết quả / số cột
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT plan_id, name, invoice_quota, price_vnd FROM service_plans`
- SQL chuẩn: `SELECT name, invoice_quota, price_vnd FROM service_plans`
- Kết quả dự đoán (5 dòng đầu): [[1, 'Gói 300 hóa đơn', 300, 390000.0], [2, 'Gói 500 hóa đơn', 500, 550000.0], [3, 'Gói 1.000 hóa đơn', 1000, 890000.0], [4, 'Gói 2.000 hóa đơn', 2000, 1590000.0], [5, 'Gói 5.000 hóa đơn', 5000, 3290000.0]]
- Kết quả chuẩn (5 dòng đầu): [['Gói 300 hóa đơn', 300, 390000.0], ['Gói 500 hóa đơn', 500, 550000.0], ['Gói 1.000 hóa đơn', 1000, 890000.0], ['Gói 2.000 hóa đơn', 2000, 1590000.0], ['Gói 5.000 hóa đơn', 5000, 3290000.0]]

### h02 (hard): 5 nhóm hàng có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024 trên các hóa đơn hợp lệ.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    ii.product_group,
    sum((ii.line_amount - ii.discount_amount) * i.exchange_rate) AS doanh_thu_vnd
FROM invoice_items AS ii
JOIN invoices AS i
    ON ii.invoice_id = i.invoice_id
WHERE
    i.status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
    AND toYear(i.issued_at) = 2024
    AND toQuarter(i.issued_at) = 4
GROUP BY ii.product_group
ORDER BY doanh_thu_vnd DESC
LIMIT 5`
- SQL chuẩn: `SELECT it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY it.product_group ORDER BY doanh_thu DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['Vật liệu xây dựng', 70278413538554.0], ['Hàng xuất khẩu', 37967691152765.836], ['Dịch vụ tư vấn', 23730087160385.0], ['Dịch vụ ăn uống', 20506020105877.0], ['Nông sản và vật tư nông nghiệp', 18257173611258.0]]
- Kết quả chuẩn (5 dòng đầu): [['Vật liệu xây dựng', 66796102577154.0], ['Hàng xuất khẩu', 36158248955087.016], ['Dịch vụ tư vấn', 22530750068385.0], ['Dịch vụ ăn uống', 19433382638177.0], ['Nông sản và vật tư nông nghiệp', 17313756316558.0]]

### h09 (hard): Độ trễ p95 (ms) của từng endpoint API trong tháng 6/2025.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    endpoint,
    quantile(0.95)(latency_ms) AS p95_latency_ms
FROM api_requests
WHERE toTimeZone(ts, 'Asia/Ho_Chi_Minh') >= toDate('2025-06-01')
  AND toTimeZone(ts, 'Asia/Ho_Chi_Minh') < toDate('2025-07-01')
GROUP BY endpoint`
- SQL chuẩn: `SELECT endpoint, quantileExact(0.95)(latency_ms) FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202506 GROUP BY endpoint`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/cancel', 789.4499999999998], ['/api/invoice/search', 383.0], ['/api/invoice/create', 565.8999999999996], ['/api/auth/token', 186.44999999999982], ['/api/invoice/publish', 3797.8999999999996]]
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
    HAVING min(purchased_at) >= toDate('2023-01-01') AND min(purchased_at) <= toDate('2023-12-31')
),
subsequent_purchases AS (
    SELECT
        s.seller_id,
        min(s.purchased_at) AS next_date
    FROM subscriptions s
    INNER JOIN first_purchase fp ON s.seller_id = fp.seller_id
    WHERE s.purchased_at > fp.first_date
      AND s.purchased_at <= fp.first_date + INTERVAL 365 DAY
      AND s.payment_status = 'da_thanh_toan'
    GROUP BY s.seller_id
)
SELECT
    round(
        countIf(sp.seller_id IS NOT NULL) * 100.0 / count(fp.seller_id),
        2
    ) AS phan_tram_mua_them
FROM first_purchase fp
LEFT JOIN subsequent_purchases sp ON fp.seller_id = sp.seller_id`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): [[36.57]]
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h12 (hard): Hóa đơn hợp lệ có giá trị thanh toán (quy ra VND) lớn nhất trong tháng 5/2025 là của doanh nghiệp nào? Cho biết mã số thuế, tên doanh nghiệp và số tiền.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    s.tax_code AS ma_so_thue,
    s.name AS ten_doanh_nghiep,
    sum((i.total_before_tax - i.total_discount) * i.exchange_rate) AS gia_tri_thanh_toan_vnd
FROM invoices AS i FINAL
JOIN sellers AS s ON i.seller_id = s.seller_id
WHERE i.status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
  AND toYear(i.issued_at) = 2025
  AND toMonth(i.issued_at) = 5
GROUP BY s.tax_code, s.name
ORDER BY gia_tri_thanh_toan_vnd DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, i.total_amount * i.exchange_rate AS gia_tri FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 ORDER BY gia_tri DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 872268825413.0]]
- Kết quả chuẩn (5 dòng đầu): [['7966472767', 'Công ty TNHH Thương mại Mai Linh Miền Bắc', 6428990761.440001]]

### h15 (hard): Tỷ trọng (%) doanh thu theo từng loại tiền (VND, USD, EUR) trong tổng doanh thu năm 2024, tính sau khi quy đổi ra VND.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    currency,
    sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu_vnd,
    round(100.0 * sum((total_before_tax - total_discount) * exchange_rate) / sum(sum((total_before_tax - total_discount) * exchange_rate)) OVER (), 2) AS ty_trong_phan_tram
FROM invoices FINAL
WHERE toYear(issued_at) = 2024
  AND status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY currency
ORDER BY doanh_thu_vnd DESC`
- SQL chuẩn: `SELECT currency, 100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency`
- Kết quả dự đoán (5 dòng đầu): [['VND', 855385263863095.0, 87.62], ['USD', 96677915997293.69, 9.9], ['EUR', 24166040283787.42, 2.48]]
- Kết quả chuẩn (5 dòng đầu): [['EUR', 2.47544734219474], ['USD', 9.903198347516758], ['VND', 87.62135431028862]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    sum(vat_vnd) - sumIf(vat_vnd, toYear(day) = 2024 AND toMonth(day) = 12) AS tang_them_thue_gtgt_vnd
FROM daily_seller_stats
WHERE toYear(day) = 2024
  AND toMonth(day) = 12`
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): [[0.0]]
- Kết quả chuẩn (5 dòng đầu): [[994295801179.5398]]

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
    i.channel AS "Kênh lập hóa đơn",
    countIf(tm.result = 'tu_choi') AS "Số hóa đơn bị từ chối",
    count() AS "Tổng số hóa đơn có mã",
    round(countIf(tm.result = 'tu_choi') * 100.0 / count(), 2) AS "Tỷ lệ bị từ chối (%)"
FROM invoices AS i FINAL
INNER JOIN tax_messages AS tm ON i.invoice_id = tm.invoice_id
WHERE
    i.tax_code_type = 'co_ma'
    AND toYear(i.issued_at) = 2024
    AND i.status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
    AND tm.message_type = '200'
GROUP BY i.channel
ORDER BY i.channel`
- SQL chuẩn: `SELECT channel, 100 * countIf(status = 'cqt_tu_choi') / count() FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND status NOT IN ('nhap', 'da_ky') AND toYear(issued_at) = 2024 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['web', 1.4971074916687104], ['api', 1.486270820381018], ['pos', 1.4948555536419363], ['excel', 1.5009573404408165], ['mobile', 1.4632595061549485]]

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
- Kết quả dự đoán (5 dòng đầu): [['Y tế và hoạt động trợ giúp xã hội', 4961940896144.0], ['Xây dựng', 14456186494121.0], ['Vận tải kho bãi', 6348842003316.016], ['Thông tin và truyền thông', 5046754754134.0], ['Nông nghiệp, lâm nghiệp và thủy sản', 2006688954684.0]]
- Kết quả chuẩn (5 dòng đầu): [['Bán buôn và bán lẻ; sửa chữa ô tô, mô tô', 24557555592537.56], ['Công nghiệp chế biến, chế tạo', 17992054933995.47], ['Xây dựng', 14456186494121.0], ['Dịch vụ lưu trú và ăn uống', 7387790023048.0], ['Vận tải kho bãi', 6348842003316.018]]

## Phân tích lỗi: cold_snip (13 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai hàm / khoảng ngày tháng | 5 | m07, m15, h02, h04, h20 |
| Khác | 2 | e12, h01 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 2 | h08, h10 |
| Sai cột kết quả / số cột | 1 | e04 |
| Sai điều kiện lọc | 1 | h15 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h18 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 1 | h19 |

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
- SQL dự đoán: `SELECT count() AS so_hoa_don_ngoai_te FROM invoices WHERE currency != 'VND'`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE currency != 'VND'`
- Kết quả dự đoán (5 dòng đầu): [[1248483]]
- Kết quả chuẩn (5 dòng đầu): [[926722]]

### h01 (hard): Tiền thuế GTGT (quy ra VND) theo từng thuế suất của các hóa đơn hợp lệ trong tháng 3/2025.
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    ii.vat_rate AS thue_suat,
    sum(ii.vat_amount * i.exchange_rate) AS tien_thue_gtgt_vnd
FROM invoice_items ii
INNER JOIN invoices i
    ON ii.invoice_id = i.invoice_id
WHERE
    i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
    AND toYYYYMM(i.issued_at) = 202503
GROUP BY ii.vat_rate`
- SQL chuẩn: `SELECT it.vat_rate, sum(it.vat_amount * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202503) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202503 GROUP BY it.vat_rate`
- Kết quả dự đoán (5 dòng đầu): [['KKKNT', 0.0], ['KCT', 0.0], ['8%', 3630513499111.0], ['0%', 0.0], ['10%', 1280765527370.0]]
- Kết quả chuẩn (5 dòng đầu): [['KKKNT', 0.0], ['KCT', 0.0], ['8%', 3448261813099.0], ['0%', 0.0], ['10%', 1215067799255.0]]

### h02 (hard): 5 nhóm hàng có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024 trên các hóa đơn hợp lệ.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    ii.product_group AS nhom_hang,
    sum(ii.line_amount - ii.discount_amount) * any(i.exchange_rate) AS doanh_thu_vnd
FROM invoice_items ii
JOIN invoices i ON ii.invoice_id = i.invoice_id
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
GROUP BY ii.product_group
ORDER BY doanh_thu_vnd DESC
LIMIT 5`
- SQL chuẩn: `SELECT it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY it.product_group ORDER BY doanh_thu DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['Vật liệu xây dựng', 70278413538554.0], ['Hàng xuất khẩu', 40307437786216.72], ['Dịch vụ tư vấn', 23730087160385.0], ['Dịch vụ ăn uống', 20506020105877.0], ['Nông sản và vật tư nông nghiệp', 18257173611258.0]]
- Kết quả chuẩn (5 dòng đầu): [['Vật liệu xây dựng', 66796102577154.0], ['Hàng xuất khẩu', 36158248955087.016], ['Dịch vụ tư vấn', 22530750068385.0], ['Dịch vụ ăn uống', 19433382638177.0], ['Nông sản và vật tư nông nghiệp', 17313756316558.0]]

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH monthly_revenue AS (
    SELECT
        formatDateTime(issued_at, '%Y-%m') AS thang,
        sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
      AND issued_at >= toDate('2024-12-01')
      AND issued_at < toDate('2025-07-01')
    GROUP BY thang
)
SELECT
    thang,
    doanh_thu,
    round((doanh_thu - lagInFrame(doanh_thu, 1) OVER (ORDER BY thang)) / lagInFrame(doanh_thu, 1) OVER (ORDER BY thang) * 100, 2) AS tang_truong_phan_tram
FROM monthly_revenue
WHERE thang >= '2025-01'
ORDER BY thang`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 95998159808994.73, inf], ['2025-02', 76423585126203.92, -20.39], ['2025-03', 95036166855908.55, 24.35], ['2025-04', 94197039637282.92, -0.88], ['2025-05', 98998383826909.31, 5.1]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h08 (hard): Trong ngày 18/03/2025, khung giờ nào có tỷ lệ lỗi API cao nhất? Cho biết giờ (0-23) và tỷ lệ lỗi (%).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT toHour(ts) AS gio, 100 * countIf(http_status >= 400) / count() AS ty_le_loi FROM api_requests WHERE toDate(ts) = toDate('2025-03-18') GROUP BY gio ORDER BY ty_le_loi DESC LIMIT 1`
- SQL chuẩn: `SELECT toHour(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) AS gio, 100 * countIf(http_status >= 400) / count() AS ty_le FROM api_requests WHERE toDate(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = toDate('2025-03-18') GROUP BY gio ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[2, 38.870588235294115]]
- Kết quả chuẩn (5 dòng đầu): [[9, 38.870588235294115]]

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
        ON s.seller_id = f.seller_id
    GROUP BY f.seller_id
)
SELECT
    round(100.0 * countIf(repurchase_count > 0) / count(), 2) AS phan_tram_mua_them
FROM repurchase`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): [[37.34]]
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h15 (hard): Tỷ trọng (%) doanh thu theo từng loại tiền (VND, USD, EUR) trong tổng doanh thu năm 2024, tính sau khi quy đổi ra VND.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    currency AS loai_tien,
    sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu_vnd,
    round(100.0 * sum((total_before_tax - total_discount) * exchange_rate) / sum(sum((total_before_tax - total_discount) * exchange_rate)) OVER (), 2) AS ty_trong_phan_tram
FROM invoices FINAL
WHERE toYear(issued_at) = 2024
  AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
GROUP BY currency
ORDER BY doanh_thu_vnd DESC`
- SQL chuẩn: `SELECT currency, 100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency`
- Kết quả dự đoán (5 dòng đầu): [['VND', 855385263863095.0, 87.62], ['USD', 96677915997293.69, 9.9], ['EUR', 24166040283787.42, 2.48]]
- Kết quả chuẩn (5 dòng đầu): [['EUR', 2.47544734219474], ['USD', 9.903198347516758], ['VND', 87.62135431028862]]

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
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt giới hạn tài nguyên (đọc quá nhiều dòng / bộ nhớ): Query memory limit exceeded: would use 1.86 GiB (attempt to allocate chunk of 8.00 MiB bytes), maximum: 1.86 GiB: While executing FillingRightJoinSide.
- SQL dự đoán: `SELECT
    i.channel AS kenh_lap,
    100 * countIf(tm.result = 'tu_choi') / count() AS ty_le_tu_choi
FROM invoices i
INNER JOIN tax_messages tm ON i.invoice_id = tm.invoice_id
WHERE i.tax_code_type = 'co_ma'
  AND toYear(i.issued_at) = 2024
  AND tm.message_type = '200'
GROUP BY i.channel
ORDER BY ty_le_tu_choi DESC`
- SQL chuẩn: `SELECT channel, 100 * countIf(status = 'cqt_tu_choi') / count() FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND status NOT IN ('nhap', 'da_ky') AND toYear(issued_at) = 2024 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['web', 1.4971074916687104], ['api', 1.486270820381018], ['pos', 1.4948555536419363], ['excel', 1.5009573404408165], ['mobile', 1.4632595061549485]]

### h20 (hard): Doanh thu tháng 5/2025 theo ngành kinh tế của người bán, sắp xếp giảm dần (tên ngành và doanh thu).
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.name AS ten_nganh,
    sum(d.revenue_vnd) AS doanh_thu
FROM daily_seller_stats AS d
INNER JOIN sellers AS s ON d.seller_id = s.seller_id
INNER JOIN industries AS i ON s.industry_code = i.industry_code
WHERE d.day >= toDate('2025-05-01') AND d.day <= toDate('2025-05-31')
GROUP BY i.name
ORDER BY i.name DESC, doanh_thu DESC`
- SQL chuẩn: `SELECT n.name, sum(d.revenue_vnd) AS doanh_thu FROM daily_seller_stats AS d JOIN sellers AS s ON s.seller_id = d.seller_id JOIN industries AS n ON n.industry_code = s.industry_code WHERE toYYYYMM(d.day) = 202505 GROUP BY n.name ORDER BY doanh_thu DESC`
- Kết quả dự đoán (5 dòng đầu): [['Y tế và hoạt động trợ giúp xã hội', 4961940896144.0], ['Xây dựng', 14456186494121.0], ['Vận tải kho bãi', 6348842003316.018], ['Thông tin và truyền thông', 5046754754134.0], ['Nông nghiệp, lâm nghiệp và thủy sản', 2006688954684.0]]
- Kết quả chuẩn (5 dòng đầu): [['Bán buôn và bán lẻ; sửa chữa ô tô, mô tô', 24557555592537.56], ['Công nghiệp chế biến, chế tạo', 17992054933995.47], ['Xây dựng', 14456186494121.0], ['Dịch vụ lưu trú và ăn uống', 7387790023048.0], ['Vận tải kho bãi', 6348842003316.018]]

### m07 (medium): Số request API theo từng endpoint trong tháng 5/2025.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT endpoint, count() AS so_request
FROM api_requests
WHERE ts >= toDate('2025-05-01') AND ts < toDate('2025-06-01')
GROUP BY endpoint`
- SQL chuẩn: `SELECT endpoint, count() FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202505 GROUP BY endpoint`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/cancel', 18106], ['/api/invoice/search', 365025], ['/api/invoice/create', 550679], ['/api/auth/token', 163858], ['/api/invoice/publish', 274256]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/cancel', 18102], ['/api/invoice/search', 365023], ['/api/invoice/create', 550666], ['/api/auth/token', 163825], ['/api/invoice/publish', 274219]]

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
