# Phiếu câu hỏi cần người hiểu dữ liệu `hddt` xác nhận

Mục đích: các điều dưới đây quyết định hệ thống Text-to-SQL trả lời đúng hay sai. Mỗi câu hỏi kèm **bằng chứng từ dữ liệu**
(số liệu tổng hợp, 6 tháng đầu 2025, bảng `VATInvoice` sau `FINAL`, `is_deleted = 0`, khoảng 629 nghìn hóa đơn) để người trả lời
đỡ phải tra lại. Điền vào chỗ **Trả lời**; sau đó cập nhật `schema_docs.json` (mục `business_rules` và mô tả cột).

Đã xác nhận chính thức (lấy từ giao diện CAdmin) và đã ghi vào `schema_docs.json`:
`TCTCheckStatus`: 1 = Hợp lệ, -2 = Không hợp lệ, -1 = Đang kiểm tra, NULL và `Status IN (1,3,4,5)` = Chưa gửi CQT.

---

## A. Ưu tiên cao: quyết định các câu hỏi thường gặp

### A1. Ý nghĩa `Status`
| Giá trị | Số dòng | Dấu hiệu trong dữ liệu | Giả thuyết hiện tại |
|---|---|---|---|
| 0 | 574.630 (91%) | Chưa có phản hồi từ CQT; 100% có `PublishDate` | Trước khi tương tác với CQT (chưa phát hành chính thức?) |
| 1 | 42.290 | 71% có kết quả của CQT; nhiều thông báo lỗi | Đã tương tác với CQT |
| 3 | 187 | 75% ghi chú nhắc "thay thế" | Bị thay thế |
| 4 | 98 | 81% ghi chú nhắc "điều chỉnh" | Bị điều chỉnh |
| 5 | 1.475 | 75% có `TCTCheckStatus = -2`; 15% ghi chú nhắc "hủy" | Bị CQT từ chối, chờ hủy / thay thế |
| -1 | 10.537 | Không có dấu hiệu; 96% nằm ở tháng 6/2025 | Trạng thái tạm? |
| 6 | 57 | Không có dấu hiệu | Không rõ |

Cần biết: tên gọi chính thức của từng giá trị (đặc biệt **0**, **-1**, **5**, **6**). Nếu có enum / hằng số trong mã nguồn CAdmin thì gửi phần đó.
**Trả lời:** ________________________________________________

### A2. Thế nào là "hóa đơn đã hủy"?
- `DestructionStatus` luôn bằng 0 trong toàn bộ dữ liệu đã xem, nên chưa dùng được.
- Câu hỏi: hóa đơn hủy được ghi bằng cột nào / giá trị nào? Có phải `Status = 5`?
**Trả lời:** ________________________________________________

### A3. Thế nào là hóa đơn "có hiệu lực" dùng để tính doanh thu, số hóa đơn phát hành, tiền thuế?
- Ví dụ trên `einvoice` (dữ liệu giả lập) quy tắc là "đã được cấp mã, đã gửi hoặc bị điều chỉnh". Ở đây chưa biết.
- Câu hỏi: lọc theo `Status`, `TCTCheckStatus` hay cả hai? Có loại `Type = 3` (điều chỉnh giảm), `Type = 1` (thay thế) không?
**Trả lời:** ________________________________________________

### A4. "Doanh thu" là cột nào?
- Có ba cột tiền: `Total` (tiền hàng?), `VATAmount` (tiền thuế), `Amount` (tổng thanh toán?). Trong tháng 5/2025:
  tổng `Total` ≈ 14,1 tỷ, tổng `VATAmount` ≈ **-11,3 tỷ** (âm), tổng `Amount` ≈ 2,6 tỷ; `Total + VATAmount` không bằng `Amount`.
- Câu hỏi: ý nghĩa đúng của ba cột; vì sao tổng thuế lại âm; doanh thu = `Total` hay `Amount`? Có phải quy đổi theo `ExchangeRate` cho hóa đơn ngoại tệ (USD, THB, AUD...)?
**Trả lời:** ________________________________________________

### A5. Loại hóa đơn `Type`
| Giá trị | Số dòng | Dấu hiệu | Giả thuyết |
|---|---|---|---|
| 0 | 627.109 | Gần như không có ghi chú xử lý | Hóa đơn gốc |
| 1 | 1.212 | 99% ghi chú nhắc "thay thế" | Thay thế |
| 2 | 642 | Số tiền dương; có ghi chú xử lý | Điều chỉnh (tăng?) |
| 3 | 234 | 91% số tiền âm | Điều chỉnh giảm / trả hàng |
| 4 | 74 | Số tiền dương nhỏ; có ghi chú xử lý | Điều chỉnh khác (thông tin?) |
| 5, 6 | 1 và 2 | Quá ít | Không rõ |

Cần xác nhận **2** và **4**, và nghĩa của 5, 6. Cũng hỏi: làm thế nào biết hóa đơn gốc của một hóa đơn thay thế / điều chỉnh
(không có cột liên kết; `RelatedInvType` luôn bằng 0, `AdjustReplaceReasonCode` luôn rỗng).
**Trả lời:** ________________________________________________

---

## B. Chất lượng dữ liệu: cần quyết định loại hay giữ

### B1. Hóa đơn thử nghiệm
Dữ liệu có công ty thử (tên bắt đầu bằng "test"), một công ty chiếm tổng tiền rất lớn trong một tháng, và hàng hóa có tên kiểu "Tester".
Tổng thuế tháng 4/2025 khoảng 524 nghìn tỷ, tháng 1 và 2 chỉ vài trăm tỷ; số lượng một mặt hàng lên tới cỡ 10^17.
- Câu hỏi: có danh sách công ty (`ComID`) thử cần loại khỏi mọi báo cáo không? Quy tắc nhận biết?
**Trả lời:** ________________________________________________

### B2. Ngày `ArisingDate` sai
Giá trị lớn nhất là năm **2522**, nhỏ nhất 2024-04-29.
- Câu hỏi: các hóa đơn ngày tương lai là dữ liệu lỗi cần loại không? Dữ liệu chính thức bắt đầu và kết thúc khi nào?
**Trả lời:** ________________________________________________

### B3. Tháng 6/2025 bất thường
`Status = -1` nhảy từ 10 – 240 hóa đơn mỗi tháng lên **10.116**; `Status = 5` từ 8 – 131 lên **1.183**; `Status = 0` giảm mạnh còn khoảng 10 nghìn
(tháng 4 có khoảng 320 nghìn). Đây là dữ liệu chưa đồng bộ xong hay một sự kiện nghiệp vụ?
**Trả lời:** ________________________________________________

### B4. Cột `ProvinceName` rỗng
Trong tháng 5/2025, 100% hóa đơn không có tên tỉnh / thành. Hiện không trả lời được câu hỏi "theo địa phương".
- Câu hỏi: tỉnh thành lấy từ đâu (`ProvinceCode`, địa chỉ, bảng khác)? Có bảng danh mục tỉnh không?
**Trả lời:** ________________________________________________

### B5. `PaymentMethod` lẫn mã giao diện
Khoảng 6.800 hóa đơn trong tháng 5/2025 có giá trị `{ maxlength = 50, class = form-control, placeholder = ... }` (lỗi giao diện ghi nhầm vào dữ liệu);
các giá trị khác viết khác nhau cho cùng ý ("Tiền mặt/Chuyển khoản", "TM/CK", "Chuyển khoản").
- Câu hỏi: có bảng chuẩn hóa hình thức thanh toán không? Cách nhóm đúng là gì?
**Trả lời:** ________________________________________________

### B6. Thuế suất `VATRate` có giá trị âm
Tháng 5/2025: 10 (75.037), 0 (21.148), **-1 (1.793)**, 8 (406), **-3 (39)**, 5 (21), ngoài ra có -2 và -5.
- Câu hỏi: ý nghĩa của các mã âm (không chịu thuế, không kê khai thuế...)? Khi tính "hóa đơn có thuế" có loại chúng không?
**Trả lời:** ________________________________________________

---

## C. Cấu trúc và truy cập

### C1. Nối bảng hóa đơn với hàng hóa
Đang dùng `ProductInv.InvID = VATInvoice.id` và `ProductInv.ComID = VATInvoice.ComID`. Xác nhận cách nối này đúng,
và `id` chỉ duy nhất trong phạm vi một `ComID`?
**Trả lời:** ________________________________________________

### C2. Phạm vi một người dùng được xem
Dữ liệu của nhiều công ty (`ComID`). Một người dùng Text-to-SQL được xem tất cả hay chỉ công ty của họ? Nếu chỉ một công ty thì cần thêm bộ lọc `ComID` bắt buộc cho từng người.
**Trả lời:** ________________________________________________

### C3. Giới hạn tài nguyên
Tài khoản hiện chưa có profile giới hạn thời gian / bộ nhớ trên server. Xin DBA một tài khoản chỉ đọc có profile giới hạn riêng
(ví dụ `max_execution_time` 30 giây, `max_memory_usage`, `max_rows_to_read`).
**Trả lời:** ________________________________________________

### C4. Cột nhạy cảm
17 cột hiện không đưa giá trị mẫu cho model: `ComPhone`, `ComAddress`, `ComBankNo`, `ComTaxCode`, `CusName`, `Buyer`, `CusAddress`, `CusPhone`,
`CusBankNo`, `CusTaxCode`, `CusEmails`, `CusIdentification`, `PassportNo`, `CreateBy`, `PublishBy`, `ApproveBy`, `Note`.
Còn cột nào cần thêm? Có cột nào người dùng không được phép đọc kết quả (ví dụ số điện thoại, email)?
**Trả lời:** ________________________________________________
