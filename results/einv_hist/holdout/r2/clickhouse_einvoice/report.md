# Kết quả đánh giá

- Bộ đánh giá: 44 câu (40 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| norules | **72.5%** | 100% | 79% | 50% | 100% | 5 | 72.5% | 44 | 160,366/3,297 | 14.0s |  |
| history | **75.0%** | 100% | 86% | 50% | 100% | 6 | 75.0% | 45 | 185,691/3,480 | 13.0s | +2.5 điểm so với dòng trên; 1 câu có sửa lại |
| + Danh mục, gợi ý lỗi | **90.0%** | 100% | 79% | 94% | 100% | 0 | 90.0% | 46 | 224,789/3,437 | 7.1s | +15.0 điểm so với dòng trên; 2 câu có sửa lại |

## Phân tích lỗi: norules (11 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Lỗi thực thi (SQL sai cú pháp / sai tên cột) | 5 | x26, x28, x34, x35, x36 |
| Chọn sai bảng | 2 | x11, x21 |
| Sai hàm / khoảng ngày tháng | 2 | x16, x33 |
| Từ chối / hỏi lại nhầm | 1 | x31 |
| Sai điều kiện lọc | 1 | x39 |

### x11 (medium): Doanh thu quý trước là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(revenue_vnd) AS doanh_thu FROM daily_seller_stats WHERE day >= toDate('2025-06-30') - INTERVAL 2 MONTH AND day < toDate('2025-06-30') - INTERVAL 1 MONTH`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[95640373599370.9]]
- Kết quả chuẩn (5 dòng đầu): [[267457911791107.25]]

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) / count() AS trung_binh_gia_tri_hoa_don_vnd FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toQuarter(issued_at) = toQuarter(toDate('2025-06-30') - INTERVAL 1 MONTH)`
- SQL chuẩn: `SELECT avg(total_amount * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[93113242.18846428]]
- Kết quả chuẩn (5 dòng đầu): [[92708899.19605963]]

### x21 (medium): Doanh nghiệp có MST 7953529219 lập bao nhiêu hóa đơn hợp lệ mỗi tháng trong quý 2/2025 (tháng ghi 4-6)?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT formatDateTime(d.day, '%Y-%m') AS thang, sum(d.invoice_count) AS so_hoa_don_hop_le FROM daily_seller_stats AS d WHERE d.seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '7953529219') AND d.day BETWEEN toDate('2025-04-01') AND toDate('2025-06-30') GROUP BY formatDateTime(d.day, '%Y-%m') ORDER BY formatDateTime(d.day, '%Y-%m')`
- SQL chuẩn: `SELECT toMonth(issued_at) AS thang, count() FROM invoices FINAL WHERE seller_id = (SELECT seller_id FROM sellers WHERE tax_code = '7953529219') AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202504 AND 202506 GROUP BY thang`
- Kết quả dự đoán (5 dòng đầu): [['2025-04', 1791], ['2025-05', 1914], ['2025-06', 1934]]
- Kết quả chuẩn (5 dòng đầu): [[4, 1791], [5, 1914], [6, 1934]]

### x26 (hard): Người mua nào có tổng giá trị thanh toán (quy ra VND) lớn nhất năm ngoái trên hóa đơn hợp lệ? Cho tên người mua và số tiền.
- Nhóm: Lỗi thực thi (SQL sai cú pháp / sai tên cột)
- Kết quả hệ thống: `result`, lỗi: Truy vấn vượt quá 30s và đã bị dừng.
- SQL dự đoán: `SELECT b.name AS ten_nguoi_mua, sum(i.total_amount * i.exchange_rate) AS tong_gia_tri_vnd FROM invoices AS i FINAL JOIN buyers AS b ON b.buyer_id = i.buyer_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(i.issued_at) = 2024 GROUP BY b.buyer_id, b.name ORDER BY tong_gia_tri_vnd DESC LIMIT 1`
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
ORDER BY vung_mien, doanh_thu DESC
LIMIT 1 BY vung_mien`
- SQL chuẩn: `SELECT p.region, it.product_group, sum((it.line_amount - it.discount_amount) * i.exchange_rate) AS doanh_thu FROM invoice_items AS it JOIN (SELECT invoice_id, seller_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202410 AND 202412) AS i ON i.invoice_id = it.invoice_id JOIN sellers AS s ON s.seller_id = i.seller_id JOIN provinces AS p ON p.province_code = s.province_code WHERE toYYYYMM(it.issued_at) BETWEEN 202410 AND 202412 GROUP BY p.region, it.product_group ORDER BY p.region, doanh_thu DESC LIMIT 1 BY p.region`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [['Miền Bắc', 'Vật liệu xây dựng', 28414070999491.0], ['Miền Nam', 'Vật liệu xây dựng', 28266859467946.0], ['Miền Trung', 'Vật liệu xây dựng', 7818743821154.0], ['Tây Nguyên', 'Vật liệu xây dựng', 2296428288563.0]]

### x31 (hard): Doanh nghiệp đăng ký dịch vụ trong năm 2025 chiếm bao nhiêu phần trăm doanh thu tháng 6/2025?
- Nhóm: Từ chối / hỏi lại nhầm
- Kết quả hệ thống: `cannot`, Không có bảng doanh thu (revenue) trong schema để tính doanh thu tháng 6/2025
- SQL dự đoán: (không có)
- SQL chuẩn: `SELECT 100 * sumIf((i.total_before_tax - i.total_discount) * i.exchange_rate, toYear(s.registered_at) = 2025) / sum((i.total_before_tax - i.total_discount) * i.exchange_rate) FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202506`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[3.702471139201897]]

### x33 (hard): Quý trước, doanh nghiệp nào có nhiều người mua khác nhau nhất trên hóa đơn hợp lệ? Cho MST, tên và số người mua.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toQuarter(i.issued_at) = 2 AND toYear(i.issued_at) = 2025 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) BETWEEN 202501 AND 202503 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 2980]]
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
- SQL dự đoán: `SELECT avg(dateDiff('day', toDate(orig.issued_at), toDate(repl.issued_at))) AS trung_binh_so_ngay FROM invoices AS repl FINAL INNER JOIN invoices AS orig FINAL ON repl.related_invoice_id = orig.invoice_id WHERE repl.nature = 'thay_the' AND toYear(repl.issued_at) = 2024`
- SQL chuẩn: `SELECT avg(dateDiff('day', toDate(o.issued_at), toDate(r.issued_at))) FROM (SELECT related_invoice_id, issued_at FROM invoices FINAL WHERE nature = 'thay_the' AND toYear(issued_at) = 2024) AS r JOIN (SELECT invoice_id, issued_at FROM invoices FINAL WHERE status = 'bi_thay_the') AS o ON o.invoice_id = r.related_invoice_id`
- Kết quả dự đoán (5 dòng đầu): []
- Kết quả chuẩn (5 dòng đầu): [[5.645434282928188]]

### x39 (hard): Năm ngoái, bao nhiêu phần trăm người mua (có thông tin người mua) mua hàng của từ 2 doanh nghiệp trở lên trên hóa đơn hợp lệ?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    countIf(seller_count >= 2) * 100.0 / count() AS phan_tram
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

## Phân tích lỗi: + Danh mục, gợi ý lỗi (4 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Chọn sai bảng | 2 | x11, x21 |
| Khác | 1 | x16 |
| Sai hàm / khoảng ngày tháng | 1 | x33 |

### x11 (medium): Doanh thu quý trước là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(revenue_vnd) AS doanh_thu FROM daily_seller_stats WHERE day >= toDate('2025-06-30') - INTERVAL 3 MONTH AND day < toDate('2025-06-30') - INTERVAL 2 MONTH`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[97252266948458.22]]
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

### x33 (hard): Quý trước, doanh nghiệp nào có nhiều người mua khác nhau nhất trên hóa đơn hợp lệ? Cho MST, tên và số người mua.
- Nhóm: Sai hàm / khoảng ngày tháng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toQuarter(i.issued_at) = 2 AND toYear(i.issued_at) = 2025 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, uniqExact(i.buyer_id) AS so_nguoi_mua FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) BETWEEN 202501 AND 202503 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY so_nguoi_mua DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 2980]]
- Kết quả chuẩn (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 2958]]
