# Kết quả đánh giá

- Bộ đánh giá: 44 câu (40 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cold_conv | **87.5%** | 100% | 86% | 81% | 100% | 1 | 87.5% | 50 | 188,517/4,530 | 5.6s | 4 câu có sửa lại |
| cold_snip | **72.5%** | 90% | 86% | 50% | 100% | 4 | 72.5% | 47 | 169,160/4,071 | 7.4s | -15.0 điểm so với dòng trên; 2 câu có sửa lại |

## Phân tích lỗi: cold_conv (5 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai hàm / khoảng ngày tháng | 2 | x16, x23 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 1 | x28 |
| Sai điều kiện lọc | 1 | x29 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 1 | x33 |

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    sum(total_amount * exchange_rate) / count() AS gia_tri_tb_hoa_don
FROM invoices FINAL
WHERE status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
  AND toQuarter(issued_at) = toQuarter(toDate('2025-06-30') - INTERVAL 1 QUARTER)`
- SQL chuẩn: `SELECT avg(total_amount * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[92868187.54606575]]
- Kết quả chuẩn (5 dòng đầu): [[92708899.19605963]]

### x23 (medium): Tháng trước, endpoint API nào có độ trễ trung vị cao nhất và độ trễ đó là bao nhiêu ms?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT endpoint, quantile(0.5)(latency_ms) AS median_latency_ms
FROM api_requests
WHERE toStartOfMonth(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = toStartOfMonth(toDate('2025-06-30') - INTERVAL 1 MONTH)
GROUP BY endpoint
ORDER BY median_latency_ms DESC
LIMIT 1`
- SQL chuẩn: `SELECT endpoint, quantileExact(0.5)(latency_ms) AS p50 FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202505 GROUP BY endpoint ORDER BY p50 DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/publish', 1192.0]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/publish', 1198]]

### x28 (hard): Ở mỗi vùng miền, nhóm hàng nào có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024? Cho vùng, nhóm hàng và doanh thu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.region AS vung_mien,
    ii.product_group AS nhom_hang,
    sum(ii.line_amount * i.exchange_rate) AS doanh_thu_vnd
FROM invoice_items AS ii
JOIN invoices AS i ON ii.invoice_id = i.invoice_id
JOIN sellers AS s ON ii.seller_id = s.seller_id
JOIN provinces AS p ON s.province_code = p.province_code
WHERE toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
  AND i.status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')
GROUP BY p.region, ii.product_group
ORDER BY p.region, doanh_thu_vnd DESC
LIMIT 1 BY p.region`
- SQL chuẩn: `SELECT p.region, it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, seller_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY p.region, it.product_group ORDER BY p.region, doanh_thu DESC LIMIT 1 BY p.region`
- Kết quả dự đoán (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 30314456791441.0], ['Miền Nam', 'Vật liệu xây dựng', 30148103207946.0], ['Miền Trung', 'Vật liệu xây dựng', 8323596354854.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2447446554813.0]]
- Kết quả chuẩn (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 28414070999491.0], ['Miền Nam', 'Vật liệu xây dựng', 28266859467946.0], ['Miền Trung', 'Vật liệu xây dựng', 7818743821154.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2296428288563.0]]

### x29 (hard): Tháng nào năm ngoái có tỷ lệ hóa đơn bị hủy cao nhất (tháng ghi 1-12), tỷ lệ bao nhiêu phần trăm trên tổng số hóa đơn lập trong tháng?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toMonth(issued_at) AS thang,
    round(100.0 * countIf(status = 'da_huy') / count(), 2) AS ty_le_huy_phan_tram
FROM invoices FINAL
WHERE toYear(issued_at) = 2024
GROUP BY toMonth(issued_at)
ORDER BY ty_le_huy_phan_tram DESC
LIMIT 1`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, 100 * countIf(status = 'da_huy') / count() AS ty_le FROM invoices FINAL WHERE toYear(issued_at) = 2024 GROUP BY thang ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[6, 1.95]]
- Kết quả chuẩn (5 dòng đầu): [[5, 1.9530565866302663]]

### x33 (hard): Quý trước, doanh nghiệp nào có nhiều người mua khác nhau nhất trên hóa đơn hợp lệ? Cho MST, tên và số người mua.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Data type AggregateFunction(uniqExact, UInt64) is not allowed in ORDER BY keys, because its values are not comparable. Set setting allow_not_comparable_types_in_order_by = 1 in order to allow it.
- SQL dự đoán: `SELECT
    s.tax_code AS mst,
    s.name AS ten_doanh_nghiep,
    uniqExactStateMerge(d.buyers) AS so_nguoi_mua
FROM daily_seller_stats AS d
JOIN sellers AS s ON d.seller_id = s.seller_id
WHERE toQuarter(d.day) = toQuarter(toDate('2025-06-30') - INTERVAL 1 QUARTER)
GROUP BY s.tax_code, s.name
ORDER BY so_nguoi_mua DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) BETWEEN 202501 AND 202503 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 2958]]

## Phân tích lỗi: cold_snip (11 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 4 | x28, x34, x35, x36 |
| Sai hàm / khoảng ngày tháng | 3 | x16, x23, x33 |
| Sai điều kiện lọc | 2 | x09, x29 |
| Khác | 1 | x26 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 1 | x37 |

### x09 (easy): Hôm nay có bao nhiêu request API bị từ chối vì gọi quá giới hạn (HTTP 429)?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_request_bui_tu_choi
FROM api_requests
WHERE http_status = 429
  AND toDate(ts) = toDate('2025-06-30')`
- SQL chuẩn: `SELECT count() FROM api_requests WHERE http_status = 429 AND toDate(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = toDate('2025-06-30')`
- Kết quả dự đoán (5 dòng đầu): [[171]]
- Kết quả chuẩn (5 dòng đầu): [[176]]

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) / count() AS trung_binh_gia_hoa_don_vnd
FROM invoices FINAL
WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toQuarter(issued_at) = toQuarter(toDate('2025-06-30') - INTERVAL 1 QUARTER)`
- SQL chuẩn: `SELECT avg(total_amount * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[92868187.54606575]]
- Kết quả chuẩn (5 dòng đầu): [[92708899.19605963]]

### x23 (medium): Tháng trước, endpoint API nào có độ trễ trung vị cao nhất và độ trễ đó là bao nhiêu ms?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT endpoint, quantile(0.5)(latency_ms) AS median_latency_ms
FROM api_requests
WHERE ts >= toDate('2025-05-01') AND ts < toDate('2025-06-01')
GROUP BY endpoint
ORDER BY median_latency_ms DESC
LIMIT 1`
- SQL chuẩn: `SELECT endpoint, quantileExact(0.5)(latency_ms) AS p50 FROM api_requests WHERE toYYYYMM(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = 202505 GROUP BY endpoint ORDER BY p50 DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/publish', 1195.0]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/publish', 1198]]

### x26 (hard): Người mua nào có tổng giá trị thanh toán (quy ra VND) lớn nhất năm ngoái trên hóa đơn hợp lệ? Cho tên người mua và số tiền.
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    b.name AS ten_nguoi_mua,
    sum(i.total_amount * i.exchange_rate) AS tong_gia_tri_thanh_toan_vnd
FROM invoices i FINAL
JOIN buyers b ON i.buyer_id = b.buyer_id
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toYear(i.issued_at) = 2024
GROUP BY b.name
ORDER BY tong_gia_tri_thanh_toan_vnd DESC
LIMIT 1`
- SQL chuẩn: `SELECT b.name, t.gia_tri FROM (SELECT buyer_id, sum(total_amount * exchange_rate) AS gia_tri FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id ORDER BY gia_tri DESC LIMIT 1) AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id`
- Kết quả dự đoán (5 dòng đầu): [['Pacific Industries Inc.', 226899867869.19]]
- Kết quả chuẩn (5 dòng đầu): [['Phan Minh Nam', 40321115610.64]]

### x28 (hard): Ở mỗi vùng miền, nhóm hàng nào có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024? Cho vùng, nhóm hàng và doanh thu.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT
    p.region AS vung_mien,
    ii.product_group AS nhom_hang,
    sum((ii.line_amount - ii.discount_amount) * i.exchange_rate) AS doanh_thu_vnd
FROM invoice_items AS ii
JOIN invoices AS i FINAL ON i.invoice_id = ii.invoice_id
JOIN sellers AS s ON s.seller_id = ii.seller_id
JOIN provinces AS p ON p.province_code = s.province_code
WHERE toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
  AND i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
GROUP BY p.region, ii.product_group
ORDER BY p.region, doanh_thu_vnd DESC
LIMIT 1 BY p.region`
- SQL chuẩn: `SELECT p.region, it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, seller_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY p.region, it.product_group ORDER BY p.region, doanh_thu DESC LIMIT 1 BY p.region`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 28414070999491.0], ['Miền Nam', 'Vật liệu xây dựng', 28266859467946.0], ['Miền Trung', 'Vật liệu xây dựng', 7818743821154.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2296428288563.0]]

### x29 (hard): Tháng nào năm ngoái có tỷ lệ hóa đơn bị hủy cao nhất (tháng ghi 1-12), tỷ lệ bao nhiêu phần trăm trên tổng số hóa đơn lập trong tháng?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toMonth(issued_at) AS thang,
    round(100.0 * countIf(status = 'da_huy') / count(), 2) AS ty_le_huy_phan_tram
FROM invoices FINAL
WHERE toYear(issued_at) = 2024
GROUP BY toMonth(issued_at)
ORDER BY ty_le_huy_phan_tram DESC
LIMIT 1`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, 100 * countIf(status = 'da_huy') / count() AS ty_le FROM invoices FINAL WHERE toYear(issued_at) = 2024 GROUP BY thang ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[6, 1.95]]
- Kết quả chuẩn (5 dòng đầu): [[5, 1.9530565866302663]]

### x33 (hard): Quý trước, doanh nghiệp nào có nhiều người mua khác nhau nhất trên hóa đơn hợp lệ? Cho MST, tên và số người mua.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code AS mst, s.name AS ten_doanh_nghiep, uniqExact(i.buyer_id) AS so_nguoi_mua
FROM invoices i
JOIN sellers s ON i.seller_id = s.seller_id
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND i.buyer_id IS NOT NULL
  AND toQuarter(i.issued_at) = toQuarter(toDate('2025-06-30') - INTERVAL 1 QUARTER)
GROUP BY s.tax_code, s.name
ORDER BY so_nguoi_mua DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) BETWEEN 202501 AND 202503 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 3049]]
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 2958]]

### x34 (hard): Tổng tiền thuế GTGT (quy ra VND) trên các dòng hàng thuế suất 5% của hóa đơn hợp lệ năm ngoái là bao nhiêu?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT sum(it.vat_amount * i.exchange_rate) AS tong_tien_thue_gtgt_vnd
FROM invoice_items AS it
JOIN (
    SELECT invoice_id, exchange_rate
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
      AND toYear(issued_at) = 2024
) AS i ON i.invoice_id = it.invoice_id
WHERE it.vat_rate = '5%'
  AND toYear(it.issued_at) = 2024`
- SQL chuẩn: `SELECT sum(it.vat_amount * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) AS i ON i.invoice_id = it.invoice_id WHERE toYear(it.issued_at) = 2024 AND it.vat_rate = '5%'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[2766607651601.0]]

### x35 (hard): Các doanh nghiệp ngừng dịch vụ trong năm ngoái đã lập tổng cộng bao nhiêu hóa đơn hợp lệ?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT count() AS tong_so_hoa_don_hop_le
FROM invoices i
FINAL
JOIN sellers s ON i.seller_id = s.seller_id
WHERE s.status = 'closed'
  AND toYear(s.closed_at) = 2024
  AND i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND seller_id IN (SELECT seller_id FROM sellers WHERE status = 'closed' AND toYear(closed_at) = 2024)`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[350648]]

### x36 (hard): Với các hóa đơn thay thế lập năm ngoái, trung bình cách ngày lập hóa đơn gốc bao nhiêu ngày (tính theo ngày lịch)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT
    avg(dateDiff('day', i2.issued_at, i.issued_at)) AS trung_binh_cach_ngay
FROM invoices i
FINAL
INNER JOIN invoices i2 FINAL
    ON i.related_invoice_id = i2.invoice_id
WHERE
    i.nature = 'thay_the'
    AND toYear(i.issued_at) = 2024`
- SQL chuẩn: `SELECT avg(dateDiff('day', toDate(o.issued_at), toDate(r.issued_at))) FROM (SELECT related_invoice_id, issued_at FROM invoices FINAL WHERE nature = 'thay_the' AND toYear(issued_at) = 2024) AS r JOIN (SELECT invoice_id, issued_at FROM invoices FINAL WHERE status = 'bi_thay_the') AS o ON o.invoice_id = r.related_invoice_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5.645434282928188]]

### x37 (hard): 5 doanh nghiệp gọi API nhiều nhất tháng trước, kèm tỷ lệ lỗi của từng doanh nghiệp (MST, tên, số request, tỷ lệ lỗi %).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code AS mst, s.name AS ten_doanh_nghiep, count() AS so_request, 100 * countIf(r.http_status >= 400) / count() AS ty_le_loi FROM api_requests r JOIN sellers s ON r.seller_id = s.seller_id WHERE r.ts >= toStartOfMonth(toDate('2025-06-30') - INTERVAL 1 MONTH) AND r.ts < toStartOfMonth(toDate('2025-06-30')) GROUP BY s.tax_code, s.name ORDER BY so_request DESC LIMIT 5`
- SQL chuẩn: `SELECT s.tax_code, s.name, count() AS so_request, 100 * countIf(a.http_status >= 400) / count() AS ty_le_loi FROM api_requests AS a JOIN sellers AS s ON s.seller_id = a.seller_id WHERE toYYYYMM(toTimeZone(a.ts, 'Asia/Ho_Chi_Minh')) = 202505 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_request DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 12486, 4.028511933365369], ['6082556967', 'Công ty Cổ phần Tư vấn Đại Phát', 5959, 3.6918946131901325], ['4983799012', 'Công ty TNHH Thương mại Đông Á', 4716, 3.541136556403732], ['7955436514', 'Công ty TNHH Sản xuất Gia Huy', 4085, 3.769889840881273], ['0190074911', 'Công ty Cổ phần Xây dựng Hà Thành', 3609, 4.29481850928235]]
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 12487, 4.020180988227757], ['6082556967', 'Công ty Cổ phần Tư vấn Đại Phát', 5958, 3.6925142665323936], ['4983799012', 'Công ty TNHH Thương mại Đông Á', 4722, 3.536637018212622], ['7955436514', 'Công ty TNHH Sản xuất Gia Huy', 4088, 3.816046966731898], ['0190074911', 'Công ty Cổ phần Xây dựng Hà Thành', 3607, 4.297199889104519]]
