# Kết quả đánh giá

- Bộ đánh giá: 62 câu (58 có đáp án, 4 câu phải từ chối)
- Model: SDS-AI/softdream, effort mặc định, reasoning none
- Database: ClickHouse t2sql@127.0.0.1:8123/einvoice
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| norules | **89.7%** | 100% | 100% | 70% | 100% | 0 | 91.4% | 65 | 249,119/4,817 | 6.4s | 2 câu có sửa lại |
| history | **89.7%** | 100% | 100% | 70% | 100% | 0 | 91.4% | 64 | 272,107/4,798 | 7.6s | +0.0 điểm so với dòng trên; 2 câu có sửa lại |
| + Danh mục, gợi ý lỗi | **91.4%** | 100% | 100% | 75% | 100% | 0 | 91.4% | 66 | 335,517/4,887 | 7.2s | +1.7 điểm so với dòng trên; 2 câu có sửa lại |

## Phân tích lỗi: norules (6 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Sai điều kiện lọc | 3 | h10, h17, h19 |
| Chọn sai bảng | 1 | h04 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h12 |
| Sai cột kết quả / số cột | 1 | h15 |

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT formatDateTime(day, '%Y-%m') AS thang, sum(revenue_vnd) AS doanh_thu, (sum(revenue_vnd) - lagInFrame(sum(revenue_vnd), 1, 0) OVER (ORDER BY day)) / lagInFrame(sum(revenue_vnd), 1, 0) OVER (ORDER BY day) * 100 AS tang_truong_pct FROM daily_seller_stats WHERE (toYear(day) = 2025 AND toMonth(day) = 1) OR toYear(day) = 2025 GROUP BY day ORDER BY day`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 3054180711958.0977, inf], ['2025-01', 3108968856215.8906, 1.7938736906850272], ['2025-01', 3118072745150.729, 0.29282663660771624], ['2025-01', 3053122514320.6924, -2.0830248726893283], ['2025-01', 961757743867.4899, -68.49920894571514]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h10 (hard): Trong các doanh nghiệp mua gói lần đầu trong năm 2023, bao nhiêu phần trăm mua thêm gói trong vòng 365 ngày sau lần mua đầu tiên?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT
    round(100.0 * countIf(repeat_count > 0) / count(), 2) AS phan_tram_mua_them
FROM
(
    SELECT
        seller_id,
        countIf(purchased_at > first_purchase AND purchased_at <= first_purchase + INTERVAL 365 DAY) AS repeat_count
    FROM
    (
        SELECT
            seller_id,
            purchased_at,
            min(purchased_at) OVER (PARTITION BY seller_id) AS first_purchase
        FROM subscriptions
        WHERE toYear(purchased_at) = 2023
    )
    GROUP BY seller_id, first_purchase
)`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): [[5.16]]
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h12 (hard): Hóa đơn hợp lệ có giá trị thanh toán (quy ra VND) lớn nhất trong tháng 5/2025 là của doanh nghiệp nào? Cho biết mã số thuế, tên doanh nghiệp và số tiền.
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code, s.name, sum(i.total_amount * i.exchange_rate) AS gia_tri_vnd FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY gia_tri_vnd DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, i.total_amount * i.exchange_rate AS gia_tri FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 ORDER BY gia_tri DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 874190960147.0]]
- Kết quả chuẩn (5 dòng đầu): [['7966472767', 'Công ty TNHH Thương mại Mai Linh Miền Bắc', 6428990761.440001]]

### h15 (hard): Tỷ trọng (%) doanh thu theo từng loại tiền (VND, USD, EUR) trong tổng doanh thu năm 2024, tính sau khi quy đổi ra VND.
- Nhóm: Sai cột kết quả / số cột
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT currency, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu_vnd, round(100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024), 2) AS ty_trong_phan_tram FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency ORDER BY doanh_thu_vnd DESC`
- SQL chuẩn: `SELECT currency, 100 * sum((total_before_tax - total_discount) * exchange_rate) / (SELECT sum((total_before_tax - total_discount) * exchange_rate) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024) FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYear(issued_at) = 2024 GROUP BY currency`
- Kết quả dự đoán (5 dòng đầu): [['VND', 855385263863095.0, 87.62], ['USD', 96677915997293.69, 9.9], ['EUR', 24166040283787.42, 2.48]]
- Kết quả chuẩn (5 dòng đầu): [['EUR', 2.47544734219474], ['USD', 9.903198347516758], ['VND', 87.62135431028862]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(vat_amount * exchange_rate) - sumIf(vat_amount * exchange_rate, vat_rate = '8%') + sumIf((line_amount - discount_amount) * exchange_rate * 0.10, vat_rate = '8%') AS tang_them_thue FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412`
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): [[6678360938964.699]]
- Kết quả chuẩn (5 dòng đầu): [[994295801179.5399]]

### h19 (hard): Với hóa đơn có mã lập năm 2024, tỷ lệ (%) bị cơ quan thuế từ chối theo từng kênh lập hóa đơn là bao nhiêu?
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT channel AS kenh_lap, 100 * countIf(status = 'cqt_tu_choi') / count() AS ty_le_tu_choi FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND toYear(issued_at) = 2024 GROUP BY channel ORDER BY ty_le_tu_choi DESC`
- SQL chuẩn: `SELECT channel, 100 * countIf(status = 'cqt_tu_choi') / count() FROM invoices FINAL WHERE tax_code_type = 'co_ma' AND status NOT IN ('nhap', 'da_ky') AND toYear(issued_at) = 2024 GROUP BY channel`
- Kết quả dự đoán (5 dòng đầu): [['excel', 1.464781155571834], ['web', 1.4607689142115239], ['pos', 1.4580692326237936], ['api', 1.4500579472175235], ['mobile', 1.4280158240653076]]
- Kết quả chuẩn (5 dòng đầu): [['web', 1.4971074916687104], ['pos', 1.4948555536419363], ['excel', 1.5009573404408165], ['mobile', 1.4632595061549485], ['api', 1.486270820381018]]

## Phân tích lỗi: + Danh mục, gợi ý lỗi (5 câu sai / 62)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
| Chọn sai bảng | 2 | h04, h17 |
| Sai điều kiện lọc | 1 | h07 |
| Sai JOIN | 1 | h10 |
| Sai phép gộp / GROUP BY / ORDER-LIMIT | 1 | h12 |

### h04 (hard): Doanh thu từng tháng năm 2025 và mức tăng trưởng (%) so với tháng liền trước (tháng ghi dạng 2025-01; tháng 1 so với tháng 12/2024).
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT formatDateTime(day, '%Y-%m') AS thang, sum(revenue_vnd) AS doanh_thu, round(100 * (sum(revenue_vnd) - lagInFrame(sum(revenue_vnd), 1, 0) OVER (ORDER BY day)) / lagInFrame(sum(revenue_vnd), 1, 0) OVER (ORDER BY day), 2) AS tang_truong_pct FROM daily_seller_stats WHERE toYear(day) = 2025 GROUP BY day ORDER BY day`
- SQL chuẩn: `SELECT thang, doanh_thu, tang_truong FROM (SELECT formatDateTime(m, '%Y-%m') AS thang, doanh_thu, 100 * (doanh_thu / lagInFrame(doanh_thu) OVER (ORDER BY m ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) - 1) AS tang_truong FROM (SELECT toStartOfMonth(issued_at) AS m, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND issued_at >= toDateTime('2024-12-01 00:00:00', 'Asia/Ho_Chi_Minh') GROUP BY m)) WHERE thang >= '2025-01'`
- Kết quả dự đoán (5 dòng đầu): [['2025-01', 3054180711958.096, inf], ['2025-01', 3108968856215.888, 1.79], ['2025-01', 3118072745150.728, 0.29], ['2025-01', 3053122514320.6895, -2.08], ['2025-01', 961757743867.49, -68.5]]
- Kết quả chuẩn (5 dòng đầu): [['2025-01', 95998159808994.73, -12.307673752589398], ['2025-02', 76423585126203.92, -20.3905728211227], ['2025-03', 95036166855908.55, 24.35449959455356], ['2025-04', 94197039637282.92, -0.8829556645502001], ['2025-05', 98998383826909.31, 5.0971285383431875]]

### h07 (hard): Trong các doanh nghiệp lập ít nhất 1.000 hóa đơn năm 2024, doanh nghiệp nào có tỷ lệ hóa đơn bị hủy cao nhất? Cho biết mã số thuế, tên và tỷ lệ (%).
- Nhóm: Sai điều kiện lọc
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code, s.name, 100 * countIf(i.status = 'da_huy') / count() AS ty_le_huy FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE toYear(i.issued_at) = 2024 GROUP BY s.seller_id, s.tax_code, s.name HAVING countIf(i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')) >= 1000 ORDER BY ty_le_huy DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, 100 * countIf(i.status = 'da_huy') / count() AS ty_le FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE toYear(i.issued_at) = 2024 GROUP BY s.seller_id, s.tax_code, s.name HAVING count() >= 1000 ORDER BY ty_le DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['3180571336', 'Công ty Cổ phần Vận tải Tân Á Green', 3.0470914127423825]]
- Kết quả chuẩn (5 dòng đầu): [['7460498778', 'Công ty TNHH Tư vấn Long Hải 86', 3.0592734225621414]]

### h10 (hard): Trong các doanh nghiệp mua gói lần đầu trong năm 2023, bao nhiêu phần trăm mua thêm gói trong vòng 365 ngày sau lần mua đầu tiên?
- Nhóm: Sai JOIN
- Kết quả hệ thống: `result`
- SQL dự đoán: `WITH first_purchases AS (
    SELECT
        seller_id,
        min(purchased_at) AS first_date
    FROM subscriptions
    WHERE toYear(purchased_at) = 2023
    GROUP BY seller_id
)
SELECT
    100.0 * countIf(repeat_count > 0) / count() AS ty_le_mua_them
FROM
(
    SELECT
        fp.seller_id,
        countIf(s.purchased_at > fp.first_date AND s.purchased_at <= fp.first_date + INTERVAL 365 DAY) AS repeat_count
    FROM first_purchases AS fp
    LEFT JOIN subscriptions AS s ON fp.seller_id = s.seller_id
    GROUP BY fp.seller_id
)`
- SQL chuẩn: `SELECT 100 * countIf(lan_sau IS NOT NULL AND dateDiff('day', lan_dau, lan_sau) <= 365) / count() FROM (SELECT seller_id, min(purchased_at) AS lan_dau, if(count() > 1, arraySort(groupArray(purchased_at))[2], NULL) AS lan_sau FROM subscriptions GROUP BY seller_id) WHERE toYear(lan_dau) = 2023`
- Kết quả dự đoán (5 dòng đầu): [[29.176086410449635]]
- Kết quả chuẩn (5 dòng đầu): [[37.38926959719205]]

### h12 (hard): Hóa đơn hợp lệ có giá trị thanh toán (quy ra VND) lớn nhất trong tháng 5/2025 là của doanh nghiệp nào? Cho biết mã số thuế, tên doanh nghiệp và số tiền.
- Nhóm: Sai phép gộp / GROUP BY / ORDER-LIMIT
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT s.tax_code, s.name, sum(i.total_amount * i.exchange_rate) AS gia_tri_thanh_toan_vnd FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 GROUP BY s.seller_id, s.tax_code, s.name ORDER BY gia_tri_thanh_toan_vnd DESC LIMIT 1`
- SQL chuẩn: `SELECT s.tax_code, s.name, i.total_amount * i.exchange_rate AS gia_tri FROM invoices AS i FINAL JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(i.issued_at) = 202505 ORDER BY gia_tri DESC LIMIT 1`
- Kết quả dự đoán (5 dòng đầu): [['0184171901', 'Công ty TNHH Giáo dục Bảo Minh', 874190960147.0]]
- Kết quả chuẩn (5 dòng đầu): [['7966472767', 'Công ty TNHH Thương mại Mai Linh Miền Bắc', 6428990761.440001]]

### h17 (hard): Nếu không có chính sách giảm thuế (thuế suất 8% vẫn là 10%), tổng tiền thuế GTGT (VND) của các hóa đơn hợp lệ trong tháng 12/2024 sẽ tăng thêm bao nhiêu?
- Nhóm: Chọn sai bảng
- Kết quả hệ thống: `result`
- SQL dự đoán: `SELECT sum(total_vat * exchange_rate) * 0.25 AS tang_them_thue FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412`
- SQL chuẩn: `SELECT sum((it.line_amount - it.discount_amount) * 0.02 * i.exchange_rate) FROM invoice_items AS it JOIN (SELECT invoice_id, exchange_rate FROM invoices FINAL WHERE status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh') AND toYYYYMM(issued_at) = 202412) AS i ON i.invoice_id = it.invoice_id WHERE toYYYYMM(it.issued_at) = 202412 AND it.vat_rate = '8%'`
- Kết quả dự đoán (5 dòng đầu): [[1421016284450.75]]
- Kết quả chuẩn (5 dòng đầu): [[994295801179.5399]]
