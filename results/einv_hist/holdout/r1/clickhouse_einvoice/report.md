# Kết quả đánh giá

- Bộ đánh giá: 44 câu (40 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| norules | **67.5%** | 100% | 79% | 38% | 100% | 8 | 67.5% | 44 | 160,360/3,482 | 15.0s |  |
| history | **82.5%** | 100% | 86% | 69% | 100% | 3 | 82.5% | 45 | 185,691/3,538 | 10.9s | +15.0 điểm so với dòng trên; 1 câu có sửa lại |
| + Danh mục, gợi ý lỗi | **82.5%** | 100% | 79% | 75% | 100% | 4 | 82.5% | 45 | 219,474/3,392 | 9.9s | +0.0 điểm so với dòng trên; 1 câu có sửa lại |

## Phân tích lỗi: norules (13 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 8 | x25, x26, x28, x29, x33, x34, x35, x36 |
| Chọn sai bảng | 3 | x11, x21, x31 |
| Khác | 1 | x16 |
| Sai điều kiện lọc | 1 | x39 |

### x11 (medium): Doanh thu quý trước là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(revenue_vnd) AS doanh_thu FROM daily_seller_stats WHERE day >= toDate('2025-06-30') - INTERVAL 2 MONTH AND day < toDate('2025-06-30') - INTERVAL 1 MONTH`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[95640373599370.9]]
- Kết quả chuẩn (5 dòng đầu): [[267457911791107.25]]

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) / count() AS trung_binh_gia_tri_hoa_don_vnd FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202503 AND 202505`
- SQL chuẩn: `SELECT avg(total_amount * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[92855696.47122812]]
- Kết quả chuẩn (5 dòng đầu): [[92708899.19605963]]

### x21 (medium): Doanh nghiệp có MST 7953529219 lập bao nhiêu hóa đơn hợp lệ mỗi tháng trong quý 2/2025 (tháng ghi 4-6)?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT formatDateTime(d.day, '%Y-%m') AS thang, sum(d.invoice_count) AS so_hoa_don_hop_le FROM daily_seller_stats AS d WHERE d.seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '7953529219') AND d.day BETWEEN toDate('2025-04-01') AND toDate('2025-06-30') GROUP BY formatDateTime(d.day, '%Y-%m') ORDER BY formatDateTime(d.day, '%Y-%m')`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, count() FROM invoices FINAL WHERE seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '7953529219') AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202504 AND 202506 GROUP BY thang`
- Kết quả dự đoán (5 dòng đầu): [['2025-04', 1791], ['2025-05', 1914], ['2025-06', 1934]]
- Kết quả chuẩn (5 dòng đầu): [[4, 1791], [5, 1914], [6, 1934]]

### x25 (hard): Doanh nghiệp nào có doanh thu quý 1/2025 tăng nhiều nhất (tính theo số tiền) so với quý 1/2024? Cho MST, tên và số tiền tăng thêm.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT s.tax_code AS mst, s.name AS ten_doanh_nghiep, (q1_2025.doanh_thu - q1_2024.doanh_thu) AS so_tien_tang_them
FROM (
    SELECT seller_id, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503
    GROUP BY seller_id
) AS q1_2025
JOIN (
    SELECT seller_id, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202401 AND 202403
    GROUP BY seller_id
) AS q1_2024 ON q1_2025.seller_id = q1_2024.seller_id
JOIN sellers AS s ON s.seller_id = q1_2025.seller_id
ORDER BY so_tien_tang_them DESC
LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(i.issued_at) = 2025) - sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(i.issued_at) = 2024) AS tang FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) IN (202401, 202402, 202403, 202501, 202502, 202503) GROUP BY s.seller_id, s.tax_code, s.name ORDER BY tang DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 338379530687.0]]

### x26 (hard): Người mua nào có tổng giá trị thanh toán (quy ra VND) lớn nhất năm ngoái trên hóa đơn hợp lệ? Cho tên người mua và số tiền.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT b.name AS ten_nguoi_mua, sum(i.total_amount * i.exchange_rate) AS tong_gia_tri_vnd
FROM invoices AS i FINAL
JOIN buyers AS b ON b.buyer_id = i.buyer_id
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toYear(i.issued_at) = 2024
GROUP BY b.buyer_id, b.name
ORDER BY tong_gia_tri_vnd DESC
LIMIT 1`
- SQL chuẩn: `SELECT b.name, t.gia_tri FROM (SELECT buyer_id, sum(total_amount * exchange_rate) AS gia_tri FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id ORDER BY gia_tri DESC LIMIT 1) AS t JOIN buyers AS b ON b.buyer_id = t.buyer_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Phan Minh Nam', 40321115610.64]]

### x28 (hard): Ở mỗi vùng miền, nhóm hàng nào có doanh thu (quy ra VND, chưa thuế, đã trừ chiết khấu) cao nhất trong quý 4/2024? Cho vùng, nhóm hàng và doanh thu.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT p.region AS vung_mien, it.product_group AS nhom_hang, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu
FROM invoice_items AS it
JOIN invoices AS i FINAL ON i.invoice_id = it.invoice_id
JOIN sellers AS s ON s.seller_id = i.seller_id
JOIN provinces AS p ON p.province_code = s.province_code
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND toQuarter(i.issued_at) = 4
  AND toYear(i.issued_at) = 2024
GROUP BY p.region, it.product_group
ORDER BY p.region, doanh_thu DESC
LIMIT 1 BY p.region`
- SQL chuẩn: `SELECT p.region, it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, seller_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY p.region, it.product_group ORDER BY p.region, doanh_thu DESC LIMIT 1 BY p.region`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 28414070999491.0], ['Miền Nam', 'Vật liệu xây dựng', 28266859467946.0], ['Miền Trung', 'Vật liệu xây dựng', 7818743821154.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2296428288563.0]]

### x29 (hard): Tháng nào năm ngoái có tỷ lệ hóa đơn bị hủy cao nhất (tháng ghi 1-12), tỷ lệ bao nhiêu phần trăm trên tổng số hóa đơn lập trong tháng?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT toMonth(issued_at) AS thang, 100 * countIf(status = 'da_huy') / count() AS ty_le_huy FROM invoices FINAL WHERE toYear(issued_at) = 2024 GROUP BY toMonth(issued_at) ORDER BY ty_le_huy DESC LIMIT 1`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, 100 * countIf(status = 'da_huy') / count() AS ty_le FROM invoices FINAL WHERE toYear(issued_at) = 2024 GROUP BY thang ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5, 1.9530565866302663]]

### x31 (hard): Doanh nghiệp đăng ký dịch vụ trong năm 2025 chiếm bao nhiêu phần trăm doanh thu tháng 6/2025?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    round(
        100.0 * sumIf(s.amount_vnd, toYear(s.purchased_at) = 2025 AND toMonth(s.purchased_at) = 6 AND s.payment_status = 'da_thanh_toan')
        /
        sumIf(s.amount_vnd, toMonth(s.purchased_at) = 6 AND s.payment_status = 'da_thanh_toan')
    , 2) AS phan_tram_doanh_thu
FROM subscriptions s
WHERE toYear(s.purchased_at) = 2025`
- SQL chuẩn: `SELECT 100 * sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(s.registered_at) = 2025) / sum((i.total_before_tax - i.total_discount) * i.exchange_rate) FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202506`
- Kết quả dự đoán (5 dòng đầu): [[100.0]]
- Kết quả chuẩn (5 dòng đầu): [[3.702471139201897]]

### x33 (hard): Quý trước, doanh nghiệp nào có nhiều người mua khác nhau nhất trên hóa đơn hợp lệ? Cho MST, tên và số người mua.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT s.tax_code AS mst, s.name AS ten_doanh_nghiep, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toQuarter(i.issued_at) = toQuarter(toDate('2025-06-30') - INTERVAL 1 QUARTER) AND toYear(i.issued_at) = toYear(toDate('2025-06-30') - INTERVAL 1 QUARTER) GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) BETWEEN 202501 AND 202503 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 2958]]

### x34 (hard): Tổng tiền thuế GTGT (quy ra VND) trên các dòng hàng thuế suất 5% của hóa đơn hợp lệ năm ngoái là bao nhiêu?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT sum(it.vat_amount * i.exchange_rate) AS tong_tien_thue_5phut FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) AS i ON i.invoice_id = it.invoice_id WHERE it.vat_rate = '5%' AND toYear(it.issued_at) = 2024`
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
WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
  AND s.status = 'closed'
  AND toYear(s.closed_at) = 2024`
- SQL chuẩn: `SELECT count() FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND seller_id IN (SELECT seller_id FROM sellers WHERE status = 'closed' AND toYear(closed_at) = 2024)`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[350648]]

### x36 (hard): Với các hóa đơn thay thế lập năm ngoái, trung bình cách ngày lập hóa đơn gốc bao nhiêu ngày (tính theo ngày lịch)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT avg(dateDiff('day', toDate(orig.issued_at), toDate(repl.issued_at))) AS trung_binh_ngay_lap_thay_the FROM invoices AS repl FINAL INNER JOIN invoices AS orig FINAL ON repl.related_invoice_id = orig.invoice_id WHERE repl.nature = 'thay_the' AND toYear(repl.issued_at) = 2024`
- SQL chuẩn: `SELECT avg(dateDiff('day', toDate(o.issued_at), toDate(r.issued_at))) FROM (SELECT related_invoice_id, issued_at FROM invoices FINAL WHERE nature = 'thay_the' AND toYear(issued_at) = 2024) AS r JOIN (SELECT invoice_id, issued_at FROM invoices FINAL WHERE status = 'bi_thay_the') AS o ON o.invoice_id = r.related_invoice_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5.645434282928188]]

### x39 (hard): Năm ngoái, bao nhiêu phần trăm người mua (có thông tin người mua) mua hàng của từ 2 doanh nghiệp trở lên trên hóa đơn hợp lệ?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    countIf(seller_count >= 2) * 100.0 / count() AS phan_tram_nguoi_mua
FROM
(
    SELECT
        i.buyer_id,
        uniqExact(i.seller_id) AS seller_count
    FROM invoices AS i
    WHERE
        i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
        AND toYear(i.issued_at) = 2024
        AND i.buyer_id IS NOT NULL
    GROUP BY i.buyer_id
)`
- SQL chuẩn: `SELECT 100 * countIf(so_dn >= 2) / count() FROM (SELECT buyer_id, uniqExact(seller_id) AS so_dn FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id)`
- Kết quả dự đoán (5 dòng đầu): [[79.50409614000469]]
- Kết quả chuẩn (5 dòng đầu): [[78.95717671082788]]

## Phân tích lỗi: + Danh mục, gợi ý lỗi (7 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 4 | x34, x36, x39, x40 |
| Chọn sai bảng | 2 | x11, x21 |
| Khác | 1 | x16 |

### x11 (medium): Doanh thu quý trước là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(revenue_vnd) AS doanh_thu FROM daily_seller_stats WHERE toQuarter(day) = 2 AND toYear(day) = 2025`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[294657428601740.56]]
- Kết quả chuẩn (5 dòng đầu): [[267457911791107.25]]

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) / count() AS trung_binh_gia_tri_hoa_don_vnd FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202503 AND 202505`
- SQL chuẩn: `SELECT avg(total_amount * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[92855696.47122812]]
- Kết quả chuẩn (5 dòng đầu): [[92708899.19605963]]

### x21 (medium): Doanh nghiệp có MST 7953529219 lập bao nhiêu hóa đơn hợp lệ mỗi tháng trong quý 2/2025 (tháng ghi 4-6)?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT formatDateTime(d.day, '%Y-%m') AS thang, sum(d.invoice_count) AS so_hoa_don FROM daily_seller_stats AS d WHERE d.seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '7953529219') AND d.day BETWEEN toDate('2025-04-01') AND toDate('2025-06-30') GROUP BY formatDateTime(d.day, '%Y-%m') ORDER BY formatDateTime(d.day, '%Y-%m')`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, count() FROM invoices FINAL WHERE seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '7953529219') AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202504 AND 202506 GROUP BY thang`
- Kết quả dự đoán (5 dòng đầu): [['2025-04', 1791], ['2025-05', 1914], ['2025-06', 1934]]
- Kết quả chuẩn (5 dòng đầu): [[4, 1791], [5, 1914], [6, 1934]]

### x34 (hard): Tổng tiền thuế GTGT (quy ra VND) trên các dòng hàng thuế suất 5% của hóa đơn hợp lệ năm ngoái là bao nhiêu?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT sum(it.vat_amount * i.exchange_rate) AS tong_tien_thue_5phut
FROM invoice_items AS it
JOIN (
    SELECT invoice_id, exchange_rate
    FROM invoices FINAL
    WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
      AND toYear(issued_at) = 2024
) AS i ON i.invoice_id = it.invoice_id
WHERE toYear(it.issued_at) = 2024
  AND it.vat_rate = '5%'`
- SQL chuẩn: `SELECT sum(it.vat_amount * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) AS i ON i.invoice_id = it.invoice_id WHERE toYear(it.issued_at) = 2024 AND it.vat_rate = '5%'`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[2766607651601.0]]

### x36 (hard): Với các hóa đơn thay thế lập năm ngoái, trung bình cách ngày lập hóa đơn gốc bao nhiêu ngày (tính theo ngày lịch)?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT avg(dateDiff('day', toDate(orig.issued_at), toDate(repl.issued_at))) AS trung_binh_so_ngay FROM invoices AS repl FINAL INNER JOIN invoices AS orig FINAL ON repl.related_invoice_id = orig.invoice_id WHERE repl.nature = 'thay_the' AND toYear(repl.issued_at) = 2024`
- SQL chuẩn: `SELECT avg(dateDiff('day', toDate(o.issued_at), toDate(r.issued_at))) FROM (SELECT related_invoice_id, issued_at FROM invoices FINAL WHERE nature = 'thay_the' AND toYear(issued_at) = 2024) AS r JOIN (SELECT invoice_id, issued_at FROM invoices FINAL WHERE status = 'bi_thay_the') AS o ON o.invoice_id = r.related_invoice_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5.645434282928188]]

### x39 (hard): Năm ngoái, bao nhiêu phần trăm người mua (có thông tin người mua) mua hàng của từ 2 doanh nghiệp trở lên trên hóa đơn hợp lệ?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT
    100.0 * countIf(seller_cnt >= 2) / count() AS ty_le_nguoi_mua_tu_2_doanh_nghiep
FROM
(
    SELECT
        i.buyer_id,
        uniqExact(i.seller_id) AS seller_cnt
    FROM invoices AS i FINAL
    WHERE
        i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')
        AND toYear(i.issued_at) = 2024
        AND i.buyer_id IS NOT NULL
    GROUP BY i.buyer_id
)`
- SQL chuẩn: `SELECT 100 * countIf(so_dn >= 2) / count() FROM (SELECT buyer_id, uniqExact(seller_id) AS so_dn FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 AND buyer_id IS NOT NULL GROUP BY buyer_id)`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[78.95717671082788]]

### x40 (hard): Hộ kinh doanh chiếm bao nhiêu phần trăm doanh thu năm ngoái?
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT 100 * sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, s.company_type = 'Hộ kinh doanh') / sum((i.total_before_tax - i.total_discount) * i.exchange_rate) AS phan_tram_doanh_thu FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(i.issued_at) = 2024`
- SQL chuẩn: `SELECT 100 * sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, s.company_type = 'Hộ kinh doanh') / sum((i.total_before_tax - i.total_discount) * i.exchange_rate) FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(i.issued_at) = 2024`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[7.963497790408956]]
