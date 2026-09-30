# Kết quả đánh giá

- Bộ đánh giá: 44 câu (40 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| + Kiểm tra hình dạng | **85.0%** | 80% | 79% | 94% | 100% | 0 | 85.0% | 47 | 213,952/3,482 | 5.5s | 3 câu có sửa lại |
| + Danh mục, gợi ý lỗi | **90.0%** | 100% | 79% | 94% | 100% | 0 | 90.0% | 47 | 230,191/3,661 | 11.0s | +5.0 điểm so với dòng trên; 3 câu có sửa lại |
| + Chặn truy vấn nặng | **87.5%** | 100% | 79% | 88% | 100% | 0 | 87.5% | 47 | 229,793/3,527 | 9.6s | -2.5 điểm so với dòng trên; 3 câu có sửa lại |
| + Tự soát logic | **90.0%** | 100% | 79% | 94% | 100% | 0 | 90.0% | 90 | 315,379/4,999 | 9.9s | +2.5 điểm so với dòng trên; 8 câu có sửa lại |

## Phân tích lỗi: + Kiểm tra hình dạng (6 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Khác | 2 | x02, x16 |
| Chọn sai bảng | 2 | x11, x21 |
| Sai điều kiện lọc | 1 | x05 |
| Sai hàm / khoảng ngày tháng | 1 | x33 |

### x02 (easy): Có bao nhiêu công ty cổ phần ở Đà Nẵng dùng dịch vụ?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() AS so_cong_ty_co_phan_da_nang FROM sellers WHERE company_type = 'Cổ phần' AND province_code = '78'`
- SQL chuẩn: `SELECT count() FROM sellers WHERE company_type = 'Cổ phần' AND province_code = '48'`
- Kết quả dự đoán (5 dòng đầu): [[0]]
- Kết quả chuẩn (5 dòng đầu): [[370]]

### x05 (easy): Gói không giới hạn 12 tháng giá bao nhiêu?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT price_vnd FROM service_plans WHERE plan_type = 'theo_thoi_gian' AND duration_months = 12`
- SQL chuẩn: `SELECT price_vnd FROM service_plans WHERE name = 'Gói không giới hạn 12 tháng'`
- Kết quả dự đoán (5 dòng đầu): [[12900000.0], [32000000.0]]
- Kết quả chuẩn (5 dòng đầu): [[12900000.0]]

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

## Phân tích lỗi: + Tự soát logic (4 câu sai / 44)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Chọn sai bảng | 2 | x11, x21 |
| Khác | 1 | x16 |
| Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu) | 1 | x30 |

### x11 (medium): Doanh thu quý trước là bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(revenue_vnd) AS doanh_thu FROM daily_seller_stats WHERE day >= toDate('2025-06-30') - INTERVAL 3 MONTH AND day < toDate('2025-06-30') - INTERVAL 2 MONTH`
- SQL chuẩn: `SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202501 AND 202503`
- Kết quả dự đoán (5 dòng đầu): [[97252266948458.2]]
- Kết quả chuẩn (5 dòng đầu): [[267457911791107.25]]

### x16 (medium): Trong quý trước, trung bình mỗi hóa đơn hợp lệ trị giá bao nhiêu (quy ra VND, đã gồm thuế)?
- Nhóm: Khác
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_amount * exchange_rate) / count() AS gia_tri_tb_hoa_don_vnd FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) BETWEEN 202503 AND 202505`
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

### x30 (hard): Có bao nhiêu doanh nghiệp đã mua gói ít nhất 3 lần nhưng không dùng tính năng API?
- Nhóm: Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT count() FROM sellers WHERE seller_id IN (SELECT seller_id FROM subscriptions WHERE payment_status = 'da_thanh_toan' GROUP BY seller_id HAVING count() >= 3) AND NOT has(features, 'api')`
- SQL chuẩn: `SELECT count() FROM (SELECT seller_id FROM subscriptions GROUP BY seller_id HAVING count() >= 3) AS m JOIN sellers AS s ON s.seller_id = m.seller_id WHERE NOT has(s.features, 'api')`
- Kết quả dự đoán (5 dòng đầu): [[10731]]
- Kết quả chuẩn (5 dòng đầu): [[11370]]
