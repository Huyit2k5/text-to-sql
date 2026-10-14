# Query Guard cho ClickHouse: kế hoạch và kết quả thực nghiệm

Đánh giá việc áp dụng ý tưởng trong [text_to_sql_clickhouse_guard.md](../text_to_sql_clickhouse_guard.md) (linter + cổng `EXPLAIN ESTIMATE` + vòng phản hồi)
lên database `hddt`. Ngày chạy: 2026-10-05. Script: [experiments/query_guard/](../experiments/query_guard/).

## Kết luận ngắn

**Không nên xây linter theo tài liệu.** Trên bộ câu hiện có, các luật không bắt được lỗi nào đáng kể, và luật duy nhất báo được nhiều (R3) không tiết kiệm tài nguyên.
Cổng `EXPLAIN ESTIMATE` đã có sẵn (`cost_guard`) và nên giữ nguyên. Việc còn lại là ghi nhận cảnh báo ở dạng thụ động trong thí điểm để biết câu hỏi thật có khác không.

## Đối chiếu tài liệu với dự án

| Ý trong tài liệu | Dự án hiện có | Kết luận |
|---|---|---|
| R0 một câu `SELECT`, cấm lệnh ghi | [safety.py](../t2sql/safety.py), [guard.py](../t2sql/db/guard.py) (sqlglot) | Đã có, tốt hơn bản dùng chuỗi |
| R9 cổng `EXPLAIN ESTIMATE` | `cost_guard`, ngưỡng 5 triệu dòng, chặn mềm | Đã có |
| Phản hồi lỗi cho model, tối đa N lần | Đã có | Đã có |
| Đo bằng `log_comment` và `system.query_log` | [profile_clickhouse.py](../profile_clickhouse.py) | Đã có |
| R1 cấm `SELECT *` | `analyst` bị chặn vì có cột cá nhân | Gần như đã có |
| R2 bắt buộc điều kiện thời gian | chưa có | Không chặn cứng: câu "từ trước đến nay" là hợp lệ |
| R3 hàm bọc cột khóa | chưa có | **Đã thử, không có lợi** (E1) |
| R4–R8 | chưa có | Giá trị thấp, R6 báo nhầm (E0) |
| Khóa phân vùng / sắp xếp trong prompt | có trong `schema_docs.json` | Đã có |

Khóa thật của `hddt` (từ `system.tables`): `VATInvoice_local` phân vùng `toYYYYMM(ArisingDate)`, sắp xếp `(ComID, id)`;
`ProductInv_local` phân vùng `toYYYYMM(InvArisingDate)`, sắp xếp `(ComID, id)`. Cả hai là `ReplicatedReplacingMergeTree`; bảng chính là `Distributed`.

## Thí nghiệm và kết quả

### E0. Chạy linter của tài liệu offline (không cần server)

Hàm `check()` của tài liệu, chỉnh bảng cấu hình sang `VATInvoice` / `ProductInv`, trên SQL model đã sinh (46 câu trong file dev đang có + 30 held-out) và SQL chuẩn.

| Rule | Số lần báo | Nhận xét |
|---|---|---|
| R2 thiếu điều kiện thời gian | 0 | Model luôn lọc thời gian |
| R3 hàm bọc cột khóa | 14 | `toYear(...) = 2025 AND toMonth(...) = 5`, `toQuarter(...)`; 11/14 nằm trên câu đúng |
| R6 thiếu `LIMIT` | 5 | Cả 5 là báo nhầm (`uniqExact` không có trong danh sách hàm gộp); SQL chuẩn cũng bị báo |
| R8 có `JOIN` | 1 | Chỉ nhắc nhở |

E0b: luật "thiếu `FINAL`" hoặc "thiếu `is_deleted = 0`" viết riêng cho `hddt`: **0 lần báo** trên toàn bộ SQL model (tức là model đã tuân thủ).

### E1. R3: bản gốc và bản viết lại thành khoảng (cần server)

14 câu bị R3 báo, mỗi câu chạy bản gốc và bản viết lại `ArisingDate >= 'Y-M-01' AND ArisingDate < ...` (1 lần khởi động + 3 lần đo, trung vị).

| Chỉ số | Bản gốc | Viết lại |
|---|---|---|
| Kết quả | | **giống nhau ở 14/14 câu** |
| Tổng dòng đọc | 2.485.309 | 2.485.309 (không câu nào đọc ít hơn hay nhiều hơn) |
| Số granule được chọn | như nhau ở mọi câu (ví dụ 13/2033) | như nhau |
| Thời gian trung vị | 138 ms | 126 ms (khác biệt nằm trong nhiễu đo) |

`EXPLAIN indexes = 1` cho thấy ClickHouse suy ra khoảng từ `toYear(...)` rồi cắt phân vùng (chỉ chọn 2 trên 330 phần dữ liệu), nên `toMonth(...)` đi kèm không làm mất việc cắt.
**R3 không tiết kiệm tài nguyên ở `hddt`**; thêm vào chỉ làm tăng báo động và có nguy cơ làm model sửa hỏng câu đang đúng.

### E3. Phân bố chi phí ước lượng (`EXPLAIN ESTIMATE`) để hiệu chỉnh cổng chặn

70 câu SQL chuẩn và 70 câu SQL model (dev + held-out):

| | p50 | p90 | p99 / lớn nhất |
|---|---|---|---|
| SQL chuẩn | 148.715 | 468.829 | 13.216.820 |
| SQL model | 148.715 | 478.767 | 13.216.820 |

| Ngưỡng | Số câu vượt | Câu |
|---|---|---|
| 1 triệu | 5 (chuẩn) / 6 (model) | h10, h34, o08, o13, o18 (+ o12, câu sai) |
| 2, 5, 10 triệu | 2 | h10, h34, đều **đúng**: là câu hỏi toàn bộ thời gian, đọc toàn bảng hợp lệ |

- SQL model tốn chi phí **ngang SQL chuẩn**: model không viết truy vấn nặng hơn mức cần thiết.
- Ngưỡng 5 triệu hiện tại chỉ chạm hai câu hợp lệ toàn bảng; chặn mềm (nhắc một lần rồi chấp nhận SQL lặp lại) đúng là cách xử lý phù hợp.
  Hạ ngưỡng xuống 1 triệu sẽ nhắc thêm các câu đúng, không có lợi.

## Quyết định

1. **Không** thêm linter R1–R8 theo tài liệu. Không có lỗi nào để bắt trên dữ liệu đã đo; R3 vô ích, R6 báo nhầm.
2. **Giữ** `cost_guard` với ngưỡng 5 triệu dòng như hiện tại.
3. **Chưa chạy A/B `production` và `production_lint`** (E2): không có luật nào đủ giá trị để đưa vào, nên A/B sẽ cho hai kết quả giống nhau.

## Việc tiếp theo có thể làm

- **Ghi cảnh báo thụ động trong thí điểm:** chạy các luật (R2, `FINAL`, `is_deleted`) trên câu của người dùng thật, chỉ ghi log, không gửi lại cho model.
  Câu hỏi thật có thể khác bộ tự viết (ví dụ không lọc thời gian, đọc nhiều tháng). Nếu một luật báo nhiều, khi đó mới đo lại như E1.
- **Đo thêm trên bộ câu thật của chuyên gia** (khi có): lặp lại E0, E1, E3 trên đó.
- **Đề xuất DBA (ngoài phạm vi ứng dụng):** khóa sắp xếp `(ComID, id)` không có `ArisingDate`; truy vấn lọc theo thời gian trên mọi công ty đọc nhiều granule hơn mức cần
  (ví dụ 13 đến 47 granule cho một tháng). Nếu cần nhanh hơn nữa, đây là chỗ để xem xét, nhưng đó là thay đổi schema.

## Hạn chế của các kết quả này

- Số mẫu nhỏ (14 câu bị R3 báo, 70 câu cho E3) và đều do nhóm viết, lọc chủ yếu theo tháng.
- Thời gian đo trên server dùng chung, chịu tải thay đổi; chênh vài chục mili giây là nhiễu. Chỉ số đáng tin là số dòng đọc và số granule.
- File dev đang dùng có 46 câu (không phải cả 66); held-out 30 câu.
- Chưa đo bộ nhớ từng truy vấn (cần `system.query_log`, tài khoản không có quyền `SYSTEM FLUSH LOGS`); số dòng và granule đã đủ để kết luận về cắt phân vùng.
