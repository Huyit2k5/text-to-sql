# Phiếu câu hỏi cần người hiểu dữ liệu `hddt` xác nhận

Mục đích: các điều dưới đây quyết định hệ thống Text-to-SQL trả lời đúng hay sai. Mỗi câu hỏi kèm **bằng chứng từ dữ liệu**
(số liệu tổng hợp, 6 tháng đầu 2025, bảng `VATInvoice` sau `FINAL`, `is_deleted = 0`, khoảng 629 nghìn hóa đơn) để người trả lời
đỡ phải tra lại. Điền vào chỗ **Trả lời**; sau đó cập nhật `schema_docs.json` (mục `business_rules` và mô tả cột).

**Cập nhật lần 2 (01/10):** suy luận được nhiều nghĩa hơn từ ghi chú trên hóa đơn, xem mục E. Các mục A1, A2, A5, B3 bên dưới giữ nguyên để đối chiếu nhưng đã được thu hẹp.

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
- Ở bộ giả lập cũ (đã xóa) quy tắc là "đã được cấp mã, đã gửi hoặc bị điều chỉnh". Ở đây chưa biết.
- Câu hỏi: lọc theo `Status`, `TCTCheckStatus` hay cả hai? Có loại `Type = 3` (điều chỉnh giảm), `Type = 1` (thay thế) không?
**Trả lời:** ________________________________________________

### A4. "Doanh thu" là cột nào?
- **Đã tự xác nhận bằng số học (xem mục D):** `Total` là tiền hàng chưa thuế, `VATAmount` là tiền thuế, `Amount = Total + VATAmount` là tổng thanh toán
  (khớp 100% với hóa đơn gốc thuế 10%). Tổng thuế tháng 5/2025 âm là do các hóa đơn điều chỉnh giảm (số âm) và dữ liệu thử nghiệm cộng gộp lại.
- Còn cần chốt: "doanh thu" là `Total` hay `Amount`; hóa đơn nào không tính (điều chỉnh, thay thế, bị hủy, thử nghiệm); có quy đổi theo `ExchangeRate` cho hóa đơn ngoại tệ (USD, THB, AUD...) không?
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
(tháng 4 có khoảng 320 nghìn).
**Đã thu hẹp (xem mục D):** gần như toàn bộ nằm ở **một công ty** (10.106 trong 10.116 hóa đơn `-1`, 1.088 trong 1.183 hóa đơn `5`), đều là hóa đơn gốc; nên không phải do thay đổi quy định ngày 01/06/2025.
Câu hỏi còn lại: đó là đợt nhập / thử nghiệm hàng loạt, hay công ty đó gặp sự cố khi phát hành? Có loại khỏi báo cáo không?
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
**Đã tự xác nhận (xem mục D):** -1 là không chịu thuế (KCT), -2 là không kê khai nộp thuế (KKKNT), -3 là thuế suất khác. **Mới phát hiện:** `VATRate = 0` ở bảng hóa đơn KHÔNG phải thuế suất 0%.
- Còn cần xác nhận: mã `-5` (109 dòng) là gì; `VATRate = 0` ở cấp hóa đơn nghĩa là "nhiều mức thuế" hay "chưa điền"; khi tính "hóa đơn có thuế" có loại các mã âm không?
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

---

## D. Đã tự xác nhận bằng quy định và dữ liệu (cần người nghiệp vụ xem lại)

Phương pháp: đối chiếu khái niệm trong quy định về hóa đơn điện tử (Nghị định 123/2020/NĐ-CP, Thông tư 78/2021/TT-BTC, Nghị định 70/2025/NĐ-CP có hiệu lực từ 01/06/2025)
với số liệu tổng hợp trong dữ liệu. Quy định cho biết khái niệm; **mã số nội bộ của phần mềm (ví dụ `Status = 5`) quy định không nói**, nên phần đó chỉ là suy luận từ dữ liệu.
Nguồn tham khảo là bài viết của nhà cung cấp phần mềm hóa đơn và trang pháp luật, chưa đối chiếu với văn bản gốc.

| Điều đã xác nhận | Căn cứ quy định | Căn cứ dữ liệu | Độ chắc |
|---|---|---|---|
| `Total` = tiền hàng chưa thuế, `VATAmount` = tiền thuế, `Amount` = `Total + VATAmount` | Cấu trúc tiêu thức hóa đơn | `Amount = Total + VATAmount` khớp 100% (hóa đơn gốc, thuế 10%) | Cao |
| `Type = 3` là hóa đơn điều chỉnh giảm | Điều chỉnh giảm ghi số âm, điều chỉnh tăng ghi số dương | 91 – 100% số tiền âm | Cao |
| `Type = 1` là hóa đơn thay thế | Hóa đơn thay thế phải ghi "Thay thế cho hóa đơn…" | 99% ghi chú nhắc "thay thế" | Cao |
| `Type = 2` có thể là điều chỉnh tăng | Như trên | Số tiền dương, có ghi chú xử lý | Trung bình |
| `VATRate = -1` là không chịu thuế (KCT) | Thuế suất gồm 0, 5, 8, 10, KCT, KKKNT, khác; hóa đơn KCT ghi tiền thuế 0 | 100% tiền thuế bằng 0; `AmountNoVAT` khớp tổng thanh toán (1,002) | Cao |
| `VATRate = -2` là không kê khai, tính nộp thuế (KKKNT) | Như trên | 85% có `AmountNDeclared > 0` | Trung bình – cao |
| `VATRate = -3` là thuế suất khác | Như trên | 98% có `AmountOther > 0`; mức lẻ như 15,15 hay 12,34 cũng vào `AmountOther` | Trung bình – cao |
| `VATRate = 0` ở hóa đơn **không** phải là thuế suất 0% | – | Tháng 5/2025, dòng hàng của các hóa đơn này: 8% (44.434), 5% (20.151), 10% (3.721), chỉ 0% là 364 | Cao (với dữ liệu này) |
| `ProductInv.Feature = 1` là hàng hóa, dịch vụ; `3` là chiết khấu thương mại; `4` là ghi chú, diễn giải | Tính chất dòng hàng gồm hàng hóa dịch vụ, khuyến mại, chiết khấu thương mại, ghi chú | 3: 95% thành tiền âm; 4: đơn giá và thành tiền hầu hết bằng 0; 1: 99,8% số dòng | Cao cho 1, 3, 4; `2` (khuyến mại) và `5` chưa kiểm chứng |
| `ApprovalStatus`, `StatusExtra`, `Hidden`, `Certified` không dùng | – | Luôn NULL hoặc 0 trong dữ liệu 2025 | Cao |
| `Serial` (ký hiệu) rỗng ở 99,6% hóa đơn | – | Đếm trực tiếp | Cao |
| Tháng 6/2025 bất thường do một công ty | Không phải thay đổi quy định | 10.106 trong 10.116 hóa đơn `Status = -1` là của một công ty | Cao |

Các điều này đã được ghi vào `schema_docs.json` kèm nguồn gốc (quy định / dữ liệu / suy luận).

Nguồn tham khảo (bài viết thứ cấp):
- Điều 19 Nghị định 123/2020/NĐ-CP (xử lý hóa đơn sai sót): https://hethongphapluat.com/nghi-dinh-123-2020-nd-cp-quy-dinh-ve-hoa-don-chung-tu/dieu-19
- Phân biệt hóa đơn điều chỉnh và thay thế: https://easyinvoice.vn/phan-biet-hoa-don-dieu-chinh-va-hoa-don-thay-the/
- KCT và KKKNT: https://www.meinvoice.vn/tin-tuc/40559/kct-va-kkknt/
- Tính chất hàng hóa, dịch vụ: https://helpv4.meinvoice.vn/kb/chon-tinh-chat-cua-hang-hoa-dich-vu/
- Điểm mới Nghị định 70/2025/NĐ-CP: https://einvoice.vn/tin-tuc/8-diem-moi-tai-nghi-dinh-70-2025-nd-cp-sua-doi-nghi-dinh-123-2020-nd-cp-quy-dinh-ve-hoa-don-chung-tu

---

## E. Suy luận bổ sung từ ghi chú trên hóa đơn (lần 2)

Hệ thống ghi vào cột `Note` / `ProcessInvNote` các câu cố định: "Thay thế cho hóa đơn…", "Điều chỉnh cho hóa đơn…", "Hóa đơn bị thay thế bởi…", "Hóa đơn bị điều chỉnh bởi…", "Thực hiện hủy Hóa đơn (Không thay thế)…".
Đối chiếu các câu này, số hóa đơn (`No`) và số tiền với `Status`, `Type` cho bằng chứng mạnh hơn so với chỉ nhìn tỉ lệ.

| Điều suy luận | Bằng chứng (tháng 1 – 6/2025) | Độ chắc |
|---|---|---|
| **`Status = 0` là hóa đơn CHƯA PHÁT HÀNH (nháp)** | 574.619 / 574.630 dòng có số hóa đơn `No = 0`; hóa đơn có số chỉ khoảng 5 – 9 nghìn mỗi tháng (tháng 5/2025: **1.733** so với 98.462 dòng); khớp giao diện CAdmin ("chưa gửi CQT" chỉ tính Status ∈ {1,3,4,5}) | Cao |
| `Status = 1` đang trong quá trình phát hành / gửi cơ quan thuế | 82% có số; riêng tháng 5/2025 chỉ 1.558 / 4.710 có số | Trung bình |
| `Status = 3` hóa đơn BỊ THAY THẾ | 118 / 187 ghi chú "Hóa đơn bị thay thế bởi…", gần như không có ở trạng thái khác | Cao |
| `Status = 4` hóa đơn BỊ ĐIỀU CHỈNH | Ghi chú "Hóa đơn bị điều chỉnh bởi…" ở ít nhất 68% | Cao |
| `Status = 5` hóa đơn ĐÃ HỦY | 223 / 257 (87%) hóa đơn có ghi chú "Thực hiện hủy Hóa đơn…" nằm ở trạng thái này; 98% có số | Trung bình – cao |
| `Status = -1`: nghĩa chưa rõ | Có số (100%), giá trị bằng 0 (99%), không mã cơ quan thuế; tháng 6/2025 do một công ty tạo hơn 10 nghìn | Thấp |
| `Status = 6`: nghĩa chưa rõ | 57 dòng, 2 công ty, 98% chưa có số | Thấp |
| `Type = 2` điều chỉnh TĂNG; `3` điều chỉnh GIẢM; `4` điều chỉnh THÔNG TIN | 2: 633 / 642 số tiền dương; 3: 212 / 234 số tiền âm; 4: 67 / 74 số tiền bằng 0; cả ba ghi "Điều chỉnh cho hóa đơn…" | Cao |
| Hóa đơn đã hủy được ghi bằng `Status = 5` | Xem trên; `DestructionStatus` luôn bằng 0 nên không dùng | Trung bình – cao |

**Câu hỏi quan trọng nhất cho người nghiệp vụ:** khoảng 91% dòng trong bảng là hóa đơn nháp chưa có số. Khi người dùng hỏi "có bao nhiêu hóa đơn", họ muốn đếm
**hóa đơn đã phát hành** hay **mọi dòng**? Hiện hệ thống đếm mọi dòng trừ khi câu hỏi nói "đã phát hành", và được dặn nêu rõ trong câu trả lời rằng kết quả gồm cả hóa đơn nháp.
**Trả lời:** ________________________________________________

Các nghĩa trên đã được ghi vào `schema_docs.json` kèm mức độ chắc chắn (tài liệu v4).
