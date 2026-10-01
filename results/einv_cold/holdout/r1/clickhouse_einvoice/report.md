# Kết quả đánh giá

- Bộ đánh giá: 44 câu (40 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cold | **65.0%** | 90% | 71% | 44% | 100% | 3 | 65.0% | 47 | 154,059/3,675 | 8.7s | 3 câu có sửa lại |
| cold_history | **80.0%** | 100% | 86% | 62% | 100% | 2 | 80.0% | 44 | 161,993/3,653 | 10.0s | +15.0 điểm so với dòng trên |

## Phân tích lỗi: cold (14 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai điều kiện lọc | 5 | x09, x13, x26, x29, x39 |
| Sai hàm / khoảng ngày tháng | 3 | x18, x22, x23 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 3 | x25, x28, x34 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 2 | x32, x37 |
| Từ chối / hỏi lại nhầm | 1 | x31 |

### x09 (easy): Hôm nay có bao nhiêu request API bị từ chối vì gọi quá giới hạn (HTTP 429)?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_request_b429
FROM api_requests
WHERE toDate(ts) = toDate('2025-06-30')
  AND http_status = 429`
- SQL chuẩn: `SELECT count() FROM api_requests WHERE http_status = 429 AND toDate(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = toDate('2025-06-30')`
- Kết quả dự đoán (5 dòng đầu): [[171]]
- Kết quả chuẩn (5 dòng đầu): [[176]]

### x13 (medium): Năm ngoái mỗi hình thức thanh toán có bao nhiêu hóa đơn hợp lệ?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    i.payment_method AS payment_method,
    count() AS valid_invoice_count
FROM invoices i
WHERE toYear(i.issued_at) = 2024
  AND i.status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')
GROUP BY i.payment_method`
- SQL chuẩn: `SELECT payment_method, count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY payment_method`
- Kết quả dự đoán (5 dòng đầu): [['CK', 7025927], ['Khác', 366653], ['TM/CK', 2693541], ['TM', 3111915]]
- Kết quả chuẩn (5 dòng đầu): [['TM/CK', 2258699], ['TM', 2612557], ['Khác', 307497], ['CK', 5893944]]

### x18 (medium): Mỗi ngày trong tuần cuối tháng 5/2025 (25-31/5) có bao nhiêu thông điệp gửi cơ quan thuế bị lỗi kỹ thuật (ngày ghi dạng 2025-05-25)?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    formatDateTime(sent_at, '%Y-%m-%d') AS ngay,
    count() AS so_thong_diep_loi_ky_thuat
FROM tax_messages
WHERE sent_at >= toDateTime('2025-05-25 00:00:00')
  AND sent_at < toDateTime('2025-06-01 00:00:00')
  AND result = 'loi_ky_thuat'
GROUP BY ngay
ORDER BY ngay`
- SQL chuẩn: `SELECT toString(toDate(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh'))) AS ngay, count() FROM tax_messages WHERE result = 'loi_ky_thuat' AND toDate(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) BETWEEN toDate('2025-05-25') AND toDate('2025-05-31') GROUP BY ngay`
- Kết quả dự đoán (5 dòng đầu): [['2025-05-24', 9], ['2025-05-25', 360], ['2025-05-26', 1863], ['2025-05-27', 1098], ['2025-05-28', 1157]]
- Kết quả chuẩn (5 dòng đầu): [['2025-05-25', 346], ['2025-05-26', 1865], ['2025-05-27', 1096], ['2025-05-28', 1164], ['2025-05-29', 1064]]

### x22 (medium): Tháng trước, cơ quan thuế phản hồi trung bình mất bao nhiêu giây với dữ liệu hóa đơn không mã được chấp nhận?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    avg(dateDiff('second', sent_at, response_at)) AS thoi_gian_phan_hoi_tb_giay
FROM tax_messages
WHERE message_type = '203'
  AND result = 'chap_nhan'
  AND response_at IS NOT NULL
  AND toStartOfMonth(sent_at) = toStartOfMonth(toDate('2025-06-30') - INTERVAL 1 MONTH)`
- SQL chuẩn: `SELECT avg(dateDiff('second', sent_at, response_at)) FROM tax_messages WHERE message_type = '203' AND result = 'chap_nhan' AND toYYYYMM(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) = 202505`
- Kết quả dự đoán (5 dòng đầu): [[437.068853338596]]
- Kết quả chuẩn (5 dòng đầu): [[437.13577761609986]]

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
- Kết quả dự đoán (5 dòng đầu): [['/api/invoice/publish', 1201.5]]
- Kết quả chuẩn (5 dòng đầu): [['/api/invoice/publish', 1198]]

### x25 (hard): Doanh nghiệp nào có doanh thu quý 1/2025 tăng nhiều nhất (tính theo số tiền) so với quý 1/2024? Cho MST, tên và số tiền tăng thêm.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT
    s.tax_code AS mst,
    s.name AS ten_doanh_nghiep,
    (sumIf(i.total_amount * i.exchange_rate, toQuarter(i.issued_at) = 1 AND toYear(i.issued_at) = 2025)
     - sumIf(i.total_amount * i.exchange_rate, toQuarter(i.issued_at) = 1 AND toYear(i.issued_at) = 2024)) AS so_tien_tang_them
FROM invoices i
JOIN sellers s ON i.seller_id = s.seller_id
WHERE i.status NOT IN ('da_huy', 'bi_thay_the', 'bi_dieu_chinh')
  AND i.nature = 'goc'
  AND (
      (toQuarter(i.issued_at) = 1 AND toYear(i.issued_at) = 2025)
      OR
      (toQuarter(i.issued_at) = 1 AND toYear(i.issued_at) = 2024)
  )
GROUP BY s.tax_code, s.name
ORDER BY so_tien_tang_them DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(i.issued_at) = 2025) - sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(i.issued_at) = 2024) AS tang FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) IN (202401, 202402, 202403, 202501, 202502, 202503) GROUP BY s.seller_id, s.tax_code, s.name ORDER BY tang DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 338379530687.0]]

### x26 (hard): Người mua nào có tổng giá trị thanh toán (quy ra VND) lớn nhất năm ngoái trên hóa đơn hợp lệ? Cho tên người mua và số tiền.
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    b.name AS ten_nguoi_mua,
    sum(i.total_amount * i.exchange_rate) AS tong_gia_tri_thanh_toan_vnd
FROM invoices i
JOIN buyers b ON i.buyer_id = b.buyer_id
WHERE toYear(i.issued_at) = 2024
  AND i.status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')
GROUP BY b.name
ORDER BY tong_gia_tri_thanh_toan_vnd DESC
LIMIT 1`
- SQL chuẩn: `SELECT b.name, t.gia_tri FROM (SELECT buyer_id, sum(total_amount * exchange_rate) AS gia_tri FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id ORDER BY gia_tri DESC LIMIT 1) AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id`
- Kết quả dự đoán (5 dòng đầu): [['Pacific Industries Inc.', 267869345370.97]]
- Kết quả chuẩn (5 dòng đầu): [['Phan Minh Nam', 40321115610.64]]

### x28 (hard): Ở mỗi vùng miền, nhóm hàng nào có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024? Cho vùng, nhóm hàng và doanh thu.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `WITH q4_2024 AS (
    SELECT
        p.region AS vung_mien,
        ii.product_group AS nhom_hang,
        sum(ii.line_amount - ii.discount_amount) AS doanh_thu_vnd
    FROM invoice_items ii
    INNER JOIN invoices i ON ii.invoice_id = i.invoice_id
    INNER JOIN sellers s ON i.seller_id = s.seller_id
    INNER JOIN provinces p ON s.province_code = p.province_code
    WHERE i.issued_at >= '2024-10-01'
      AND i.issued_at < '2025-01-01'
    GROUP BY p.region, ii.product_group
)
SELECT
    vung_mien,
    nhom_hang,
    doanh_thu_vnd
FROM q4_2024
ORDER BY vung_mien, doanh_thu_vnd DESC
LIMIT 1 BY vung_mien`
- SQL chuẩn: `SELECT p.region, it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, seller_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY p.region, it.product_group ORDER BY p.region, doanh_thu DESC LIMIT 1 BY p.region`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 28414070999491.0], ['Miền Nam', 'Vật liệu xây dựng', 28266859467946.0], ['Miền Trung', 'Vật liệu xây dựng', 7818743821154.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2296428288563.0]]

### x29 (hard): Tháng nào năm ngoái có tỷ lệ hóa đơn bị hủy cao nhất (tháng ghi 1-12), tỷ lệ bao nhiêu phần trăm trên tổng số hóa đơn lập trong tháng?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    toMonth(issued_at) AS thang,
    round(100.0 * countIf(status = 'da_huy') / count(), 2) AS ty_le_huy_phan_tram
FROM invoices
WHERE toYear(issued_at) = 2024
GROUP BY toMonth(issued_at)
ORDER BY ty_le_huy_phan_tram DESC
LIMIT 1`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, 100 * countIf(status = 'da_huy') / count() AS ty_le FROM invoices FINAL WHERE toYear(issued_at) = 2024 GROUP BY thang ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [[6, 1.45]]
- Kết quả chuẩn (5 dòng đầu): [[5, 1.9530565866302663]]

### x31 (hard): Doanh nghiệp đăng ký dịch vụ trong năm 2025 chiếm bao nhiêu phần trăm doanh thu tháng 6/2025?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Bảng subscriptions không có cột doanh thu (revenue), chỉ có amount_vnd là số tiền thanh toán gói dịch vụ, không phải doanh thu từ hóa đơn
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT 100 * sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(s.registered_at) = 2025) / sum((i.total_before_tax - i.total_discount) * i.exchange_rate) FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202506`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[3.702471139201897]]

### x32 (hard): Trong ngày 18/03/2025, tỷ lệ lỗi API vượt 10% từ mấy giờ đến mấy giờ (giờ Việt Nam)? Cho giờ đầu tiên và giờ cuối cùng (0-23).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    min(toHour(ts + toIntervalHour(7))) AS gio_dau,
    max(toHour(ts + toIntervalHour(7))) AS gio_cuoi
FROM api_requests
WHERE toDate(ts + toIntervalHour(7)) = toDate('2025-03-18')
    AND http_status >= 400`
- SQL chuẩn: `SELECT min(gio), max(gio) FROM (SELECT toHour(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) AS gio, 100 * countIf(http_status >= 400) / count() AS ty_le FROM api_requests WHERE toDate(toTimeZone(ts, 'Asia/Ho_Chi_Minh')) = toDate('2025-03-18') GROUP BY gio) WHERE ty_le > 10`
- Kết quả dự đoán (5 dòng đầu): [[0, 23]]
- Kết quả chuẩn (5 dòng đầu): [[8, 10]]

### x34 (hard): Tổng tiền thuế GTGT (quy ra VND) trên các dòng hàng thuế suất 5% của hóa đơn hợp lệ năm ngoái là bao nhiêu?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT sum(vat_amount * i.exchange_rate) AS total_vat_5pct_vnd
FROM invoice_items ii
JOIN invoices i ON ii.invoice_id = i.invoice_id
WHERE ii.vat_rate = '5%'
  AND i.status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')
  AND toYear(i.issued_at) = 2024`
- SQL chuẩn: `SELECT sum(it.vat_amount * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) AS i ON i.invoice_id = it.invoice_id WHERE toYear(it.issued_at) = 2024 AND it.vat_rate = '5%'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[2766607651601.0]]

### x37 (hard): 5 doanh nghiệp gọi API nhiều nhất tháng trước, kèm tỷ lệ lỗi của từng doanh nghiệp (MST, tên, số request, tỷ lệ lỗi %).
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    s.tax_code AS mst,
    s.name AS ten_doanh_nghiep,
    count() AS so_request,
    round(100.0 * countIf(ar.http_status >= 400) / count(), 2) AS ty_le_loi_phan_tram
FROM api_requests AS ar
INNER JOIN sellers AS s ON ar.seller_id = s.seller_id
WHERE ar.ts >= toStartOfMonth(toDate('2025-06-30') - INTERVAL 1 MONTH)
  AND ar.ts < toStartOfMonth(toDate('2025-06-30'))
GROUP BY s.tax_code, s.name
ORDER BY so_request DESC
LIMIT 5`
- SQL chuẩn: `SELECT s.tax_code, s.name, count() AS so_request, 100 * countIf(a.http_status >= 400) / count() AS ty_le_loi FROM api_requests AS a JOIN sellers AS s ON s.seller_id = a.seller_id WHERE toYYYYMM(toTimeZone(a.ts, 'Asia/Ho_Chi_Minh')) = 202505 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_request DESC LIMIT 5`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 12486, 4.03], ['6082556967', 'Công ty Cổ phần Tư vấn Đại Phát', 5959, 3.69], ['4983799012', 'Công ty TNHH Thương mại Đông Á', 4716, 3.54], ['7955436514', 'Công ty TNHH Sản xuất Gia Huy', 4085, 3.77], ['0190074911', 'Công ty Cổ phần Xây dựng Hà Thành', 3609, 4.29]]
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 12487, 4.020180988227757], ['6082556967', 'Công ty Cổ phần Tư vấn Đại Phát', 5958, 3.6925142665323936], ['4983799012', 'Công ty TNHH Thương mại Đông Á', 4722, 3.536637018212622], ['7955436514', 'Công ty TNHH Sản xuất Gia Huy', 4088, 3.816046966731898], ['0190074911', 'Công ty Cổ phần Xây dựng Hà Thành', 3607, 4.297199889104519]]

### x39 (hard): Năm ngoái, bao nhiêu phần trăm người mua (có thông tin người mua) mua hàng của từ 2 doanh nghiệp trở lên trên hóa đơn hợp lệ?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    countIf(seller_count >= 2) * 100.0 / count() AS percent_buyers_2plus_sellers
FROM
(
    SELECT
        i.buyer_id,
        uniqExact(i.seller_id) AS seller_count
    FROM invoices i
    WHERE
        toYear(i.issued_at) = 2024
        AND i.buyer_id IS NOT NULL
        AND i.status IN ('cqt_cap_ma', 'da_ky', 'da_gui_cqt')
    GROUP BY i.buyer_id
)`
- SQL chuẩn: `SELECT 100 * countIf(so_dn >= 2) / count() FROM (SELECT buyer_id, uniqExact(seller_id) AS so_dn FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id)`
- Kết quả dự đoán (5 dòng đầu): [[79.80281593103456]]
- Kết quả chuẩn (5 dòng đầu): [[78.95717671082788]]

## Phân tích lỗi: cold_history (8 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai hàm / khoảng ngày tháng | 3 | x16, x23, x33 |
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 2 | x34, x36 |
| Khác | 1 | x26 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 1 | x28 |
| Sai điều kiện lọc | 1 | x29 |

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT avg(total_amount * exchange_rate) AS gia_tri_tb_hoa_don
FROM invoices FINAL
WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toQuarter(issued_at) = toQuarter(toDate('2025-06-30') - INTERVAL 1 QUARTER)`
- SQL chuẩn: `SELECT avg(total_amount * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[92868187.5460658]]
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

### x26 (hard): Người mua nào có tổng giá trị thanh toán (quy ra VND) lớn nhất năm ngoái trên hóa đơn hợp lệ? Cho tên người mua và số tiền.
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    b.name AS ten_nguoi_mua,
    sum(i.total_amount * i.exchange_rate) AS tong_gia_tri_thanh_toan_vnd
FROM invoices AS i FINAL
JOIN buyers AS b ON i.buyer_id = b.buyer_id
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toYear(i.issued_at) = 2024
GROUP BY b.name
ORDER BY tong_gia_tri_thanh_toan_vnd DESC
LIMIT 1`
- SQL chuẩn: `SELECT b.name, t.gia_tri FROM (SELECT buyer_id, sum(total_amount * exchange_rate) AS gia_tri FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id ORDER BY gia_tri DESC LIMIT 1) AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id`
- Kết quả dự đoán (5 dòng đầu): [['Pacific Industries Inc.', 226899867869.19]]
- Kết quả chuẩn (5 dòng đầu): [['Phan Minh Nam', 40321115610.64]]

### x28 (hard): Ở mỗi vùng miền, nhóm hàng nào có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024? Cho vùng, nhóm hàng và doanh thu.
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    p.region AS vung_mien,
    ii.product_group AS nhom_hang,
    sum(ii.line_amount * i.exchange_rate) AS doanh_thu
FROM invoice_items AS ii
JOIN invoices AS i FINAL ON i.invoice_id = ii.invoice_id
JOIN sellers AS s ON s.seller_id = ii.seller_id
JOIN provinces AS p ON p.province_code = s.province_code
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
GROUP BY p.region, ii.product_group
ORDER BY p.region, doanh_thu DESC
LIMIT 1 BY p.region`
- SQL chuẩn: `SELECT p.region, it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, seller_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY p.region, it.product_group ORDER BY p.region, doanh_thu DESC LIMIT 1 BY p.region`
- Kết quả dự đoán (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 28800600618441.0], ['Miền Nam', 'Vật liệu xây dựng', 28649147773946.0], ['Miền Trung', 'Vật liệu xây dựng', 7926557049854.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2326634305813.0]]
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
FROM invoices AS i FINAL
JOIN sellers AS s ON i.seller_id = s.seller_id
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

### x36 (hard): Với các hóa đơn thay thế lập năm ngoái, trung bình cách ngày lập hóa đơn gốc bao nhiêu ngày (tính theo ngày lịch)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT
    avg(dateDiff('day', related.issued_at, inv.issued_at)) AS trung_binh_cach_ngay
FROM invoices AS inv FINAL
INNER JOIN invoices AS related FINAL
    ON inv.related_invoice_id = related.invoice_id
WHERE
    inv.nature = 'thay_the'
    AND toYear(inv.issued_at) = 2024
    AND inv.status IN ('bi_dieu_chinh', 'cqt_cap_ma', 'da_gui_cqt')`
- SQL chuẩn: `SELECT avg(dateDiff('day', toDate(o.issued_at), toDate(r.issued_at))) FROM (SELECT related_invoice_id, issued_at FROM invoices FINAL WHERE nature = 'thay_the' AND toYear(issued_at) = 2024) AS r JOIN (SELECT invoice_id, issued_at FROM invoices FINAL WHERE status = 'bi_thay_the') AS o ON o.invoice_id = r.related_invoice_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5.645434282928188]]
