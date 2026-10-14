# Phiếu kiểm toán bộ đánh giá hddt (dành cho người hiểu nghiệp vụ)

Hệ thống Text-to-SQL được chấm bằng cách so kết quả với "SQL chuẩn" do nhóm kỹ thuật tự viết. Một LLM đã soát 91 câu và gắn cờ 24 câu cần người nghiệp vụ quyết định;
các cờ xoay quanh 4 vấn đề. Nhóm kỹ thuật **đã tự suy luận** từ quy định, dữ liệu và đối soát số liệu để chọn một cách hiểu cho từng vấn đề (bên dưới).
**Những lựa chọn đó chưa được chuyên gia xác nhận.** Nhờ bạn đánh dấu `[x]` đồng ý hoặc sửa lại. Phiếu không chứa dữ liệu thật.

| # | Vấn đề | Kỹ thuật đã chọn tạm | Độ chắc | Việc cần ở bạn |
|---|---|---|---|---|
| 1 | "Hóa đơn" mặc định có tính hóa đơn nháp không? | **Chưa chốt**: giữ mặc định hiện tại (tính cả nháp), chấp nhận cả hai cách trong bộ chấm, báo rõ trên giao diện | Thấp | Chọn mặc định |
| 2 | "Dòng hàng hóa", "mặt hàng" có chỉ tính `Feature = 1` không? | **Có**, chỉ `Feature = 1` | Cao | Xác nhận |
| 3 | Thống kê theo thuế suất dùng cột nào? | **Cấp dòng hàng** (`ProductInv.VATRate`) | Cao | Xác nhận |
| 4 | Các câu lẻ | Giữ nguyên, ghi chú | Trung bình | Xem lại |

## Câu 1. "Hóa đơn" mặc định là gì? (13 câu bị ảnh hưởng)

**Bằng chứng thu được:**
- Quy định: hóa đơn điện tử chỉ có hiệu lực khi đã lập, ký và có số; bản nháp không phải hóa đơn theo nghĩa pháp lý. Nghiêng về "chỉ tính đã phát hành". (Các nguồn tra được chỉ nêu chung; chưa tìm được điều khoản nêu chính xác thời điểm cấp số.)
- Dữ liệu: khoảng 91% dòng trong bảng hóa đơn là nháp (chưa có số). Riêng tháng 3/2025: 148.713 bản ghi, 8.463 có số; tháng 5/2025: 98.462 bản ghi, 1,8% có số. Bảng xếp hạng công ty bị chi phối bởi dữ liệu thử (một mã công ty chiếm 72% bản ghi tháng 5, 0% có số).
- Thói quen truy vấn thật: **không có thông tin.** 15 truy vấn thật trên bảng hóa đơn trong lịch sử đều là kiểm tra đồng bộ dữ liệu (đếm, `uniqExact(id)`, `_version`), không phải câu hỏi nghiệp vụ.

**Vì sao chưa chốt:** đổi mặc định sang "đã phát hành" sẽ đổi kết quả và SQL chuẩn của gần như mọi câu về hóa đơn, và cần quyết định riêng cho câu hỏi theo dòng hàng. Quyết định này thuộc về người nghiệp vụ.

Khi người dùng hỏi "bao nhiêu hóa đơn", "công ty có nhiều hóa đơn nhất"... mà không nói gì thêm:

- [ ] (a) tính **mọi** hóa đơn, kể cả nháp (hiện tại)
- [ ] (b) chỉ tính hóa đơn **đã phát hành** (`No > 0`)
- [ ] (c) tùy câu hỏi (ghi rõ):

Thêm: có **danh sách mã công ty (ComID) thuộc môi trường thử** cần loại khỏi mọi số liệu không? Nếu có, ghi danh sách hoặc cách nhận biết:

Hiện tại giao diện hiện ghi chú "số liệu tính cả hóa đơn nháp" dưới câu trả lời khi SQL không lọc trạng thái. Bộ chấm chấp nhận cả hai cách (SQL chuẩn là (a), `alt_sql` là (b)).

Câu bị ảnh hưởng: h01, h07, h10, h11, h14, h16, h22, h23, h24, h27, o07, o09, o19.

## Câu 2. "Dòng hàng hóa", "mặt hàng" chỉ tính `Feature = 1`? (5 câu) Đã tự xác nhận

**Bằng chứng:**
- Quy định (quyết định về thành phần dữ liệu hóa đơn): tính chất dòng hàng gồm hàng hóa dịch vụ, khuyến mại, chiết khấu thương mại, ghi chú. Mã `Feature` trong dữ liệu khớp: 1 hàng hóa dịch vụ (99,8% số dòng tháng 3/2025), 2 khuyến mại (11 dòng), 3 chiết khấu thương mại (112/133 dòng có thành tiền âm), 4 ghi chú (thành tiền bằng 0).
- Kết luận: "dòng hàng hóa", "mặt hàng" = `Feature = 1`. SQL chuẩn cũ thiếu lọc này và đã được sửa (h08, h19, h20, o13).

**Hai chi tiết nhỏ cũng đã chọn:**
- Đơn vị tính rỗng: **loại khỏi thống kê** (khoảng 77% dòng hàng không ghi đơn vị tính, nên "đơn vị dùng nhiều nhất" sẽ là ô trống nếu không loại). Dữ liệu tháng 5/2025.
- Tiền chiết khấu: chiết khấu thương mại nằm ở hai chỗ, `DiscountAmount` của dòng hàng hóa và `DiscountAmount` của dòng `Feature = 3` (tháng 4/2025: 7,4 triệu và 7,8 triệu; tháng 3/2025 toàn bộ ở dòng hàng hóa). "Tổng tiền chiết khấu" chung thì cộng mọi dòng; "trên các dòng hàng hóa" thì chỉ `Feature = 1`. Câu o14 chấp nhận cả hai.

- [ ] Đồng ý
- [ ] Sửa lại (ghi rõ):

## Câu 3. Thống kê theo mức thuế suất dùng cột nào? (7 câu: o12, h03, h13, h26, h43, h44, o02) Đã tự xác nhận bằng đối soát số liệu

**Bằng chứng (tháng 3/2025, tổng tiền thuế GTGT theo từng mức):**

| Mức | Theo dòng hàng (`ProductInv.VATRate`) | Cột tổng hợp theo mức của chính hóa đơn | Theo `VATInvoice.VATRate` |
|---|---|---|---|
| 0% | 5,2 triệu | 5,0 triệu | **7.153 triệu** |
| 5% | 1.864 triệu | 1.804 triệu | 2.886 triệu |
| 8% | 362 triệu | 356 triệu | 351 triệu |
| 10% | 24.457 tỷ | 24.460 tỷ | 24.452 tỷ |

Theo dòng hàng khớp cột tổng hợp của chính hóa đơn (lệch 0,02% ở mức 10%); theo cấp hóa đơn thì mức "0" chứa 7,2 tỷ tiền thuế trong khi thuế thật của mức 0% chỉ khoảng 5 triệu, vì `VATRate = 0` ở cấp hóa đơn gồm cả hóa đơn nhiều mức thuế hoặc chưa điền.

Hệ quả: câu "tổng thuế theo mức" dùng cấp dòng hàng (o12 đã sửa SQL chuẩn). Câu "số hóa đơn có thuế suất 8%": cấp hóa đơn chỉ thấy 406 hóa đơn, còn hóa đơn có ít nhất một dòng 8% là 17.263 (tháng 5/2025); SQL chuẩn nay tính theo dòng hàng và vẫn chấp nhận cách cũ (h03, h13, h26, h43, h44, o02; o12 đã sửa SQL chuẩn).

- [ ] Đồng ý
- [ ] Sửa lại (ghi rõ):

## Câu 4. Các câu còn lại

| Mã | Câu hỏi | Kỹ thuật đã làm | Quyết định của bạn |
|---|---|---|---|
| h21 | Có bao nhiêu hóa đơn có tiền chiết khấu lớn hơn 0 trong tháng 5/2025? | Giữ: dùng `DiscountAmount` cấp hóa đơn | |
| h24 | Công ty nào có số hóa đơn nhiều hơn mức trung bình? | Giữ, chấp nhận cả cách tính nháp / đã phát hành (như câu 1) | |
| h56 | Có bao nhiêu hóa đơn đã bị điều chỉnh trong tháng 5/2025? | Giữ: `Status = 4` (hóa đơn gốc bị điều chỉnh); hóa đơn điều chỉnh là `Type` 2/3/4 | |
| o24 | 5 mặt hàng bán ra có tổng số lượng lớn nhất tháng 4/2025 | Giữ; top-N có hòa ở vị trí cuối và có giá trị bất thường do hàng thử | |

## Việc kỹ thuật sau khi có phản hồi

1. Nếu bạn chọn (b) ở câu 1: đổi mặc định, sửa SQL chuẩn và ví dụ few-shot, chạy lại bộ đánh giá.
2. Cập nhật tài liệu `schema_docs.json` theo các câu trả lời khác.

Chi tiết thực nghiệm: `report/bao_cao_kiem_toan_bo_danh_gia.html`.
