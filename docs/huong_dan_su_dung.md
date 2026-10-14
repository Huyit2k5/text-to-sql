# Hướng dẫn sử dụng: hỏi dữ liệu hóa đơn bằng tiếng Việt

Hệ thống cho bạn hỏi dữ liệu hóa đơn điện tử (database `hddt`) bằng câu hỏi thường ngày, rồi trả về **con số hoặc bảng kết quả, biểu đồ và câu truy vấn đã chạy**.
Bạn không cần biết SQL. Đây là **bản dùng thử**: hãy đọc phần [Những điều cần biết về số liệu](#6-những-điều-cần-biết-về-số-liệu) trước khi dùng số liệu vào báo cáo.

## Mục lục
1. [Hệ thống làm được và không làm được gì](#1-hệ-thống-làm-được-và-không-làm-được-gì)
2. [Truy cập](#2-truy-cập)
3. [Làm quen với giao diện](#3-làm-quen-với-giao-diện)
4. [Cách đặt câu hỏi cho tốt](#4-cách-đặt-câu-hỏi-cho-tốt)
5. [Đọc kết quả](#5-đọc-kết-quả)
6. [Những điều cần biết về số liệu](#6-những-điều-cần-biết-về-số-liệu)
7. [Hệ thống hỏi lại hoặc từ chối](#7-hệ-thống-hỏi-lại-hoặc-từ-chối)
8. [Gửi phản hồi](#8-gửi-phản-hồi)
9. [Quyền và bảo mật](#9-quyền-và-bảo-mật)
10. [Xử lý sự cố](#10-xử-lý-sự-cố)
11. [Câu hỏi thường gặp](#11-câu-hỏi-thường-gặp)
12. [Phụ lục dành cho người quản trị](#12-phụ-lục-dành-cho-người-quản-trị)

---

## 1. Hệ thống làm được và không làm được gì

| Làm được | Không làm được |
|---|---|
| Đếm, cộng tổng, trung bình, tỷ lệ phần trăm | Thêm, sửa, xóa dữ liệu (hệ thống chỉ **đọc**) |
| Xếp hạng (top N), so sánh theo tháng, theo công ty, theo thuế suất | Dự báo tương lai, đưa ý kiến hay đánh giá chủ quan |
| Hiểu câu hỏi nối tiếp ("Còn tháng 4 thì sao?") | Xem dữ liệu cá nhân của người mua (tên, địa chỉ, số điện thoại, email, MST, số tài khoản) với vai trò `analyst` |
| Hỏi lại khi câu hỏi mơ hồ | Trả lời về dữ liệu không có trong hệ thống |
| Hiển thị câu SQL để bạn kiểm tra | Thay thế việc đối chiếu số liệu với báo cáo chính thức |

Dữ liệu gồm hai bảng: **hóa đơn** (khoảng 14 triệu dòng) và **dòng hàng hóa trên hóa đơn** (khoảng 16,5 triệu dòng). Dữ liệu tập trung vào **các tháng 3 đến 5 năm 2025**.

## 2. Truy cập

1. Mở địa chỉ do người quản trị gửi trong trình duyệt (Chrome, Edge, Firefox).
2. Nếu trình duyệt hiện hộp hỏi **tên đăng nhập và mật khẩu**, nhập thông tin người quản trị đã gửi riêng cho bạn. Đây là mật khẩu mở trang, dùng chung cho cả nhóm.
3. Lần đầu có thể mất vài chục giây để hệ thống nạp thông tin bảng. Các lần sau nhanh hơn.

Đừng chuyển tiếp địa chỉ hoặc mật khẩu cho người khác khi chưa hỏi người quản trị: trang cho phép xem số liệu hóa đơn thật của công ty.

## 3. Làm quen với giao diện

**Thanh bên trái** (bấm mũi tên `>` ở góc trên nếu đang thu gọn):

| Mục | Ý nghĩa | Bạn nên |
|---|---|---|
| Database | Nguồn dữ liệu (`ClickHouse · hddt`) | Giữ nguyên |
| Pipeline | Cách hệ thống xử lý câu hỏi | Giữ `production` |
| Giải thích SQL bằng lời | Thêm một đoạn giải thích câu truy vấn bằng tiếng Việt | Bật khi muốn hiểu hệ thống đã làm gì; tắt để nhanh hơn |
| Self-consistency | Sinh nhiều phương án rồi chọn kết quả được nhiều phương án đồng ý | Thường **không cần bật**, chậm hơn 2 đến 3 lần |
| Vai trò người dùng | Quyền xem dữ liệu | Mặc định `analyst` |
| Xóa hội thoại | Bắt đầu cuộc hỏi đáp mới | Bấm khi chuyển sang chủ đề khác |
| Thử hỏi | Danh sách câu hỏi mẫu | Dùng để làm quen |

**Khu vực chính:** ô nhập câu hỏi ở cuối trang ("Ví dụ: doanh thu tháng trước là bao nhiêu?"). Mỗi câu trả lời gồm các phần: câu hiểu lại (nếu có), phần kết quả, ô "Câu SQL đã chạy", và hai nút phản hồi.

## 4. Cách đặt câu hỏi cho tốt

Hệ thống đọc câu hỏi như một người làm báo cáo: câu càng rõ thì kết quả càng đúng ý.

### Nguyên tắc
1. **Nói rõ khoảng thời gian:** "tháng 5/2025", "quý 1 năm 2025". Nếu không nói, hệ thống tính trên toàn bộ dữ liệu.
2. **Nói rõ đại lượng:** "số hóa đơn", "tổng tiền hàng", "tổng thanh toán", "tiền thuế", "số lượng hàng hóa".
3. **Nói rõ đối tượng:** theo công ty, theo tháng, theo mức thuế suất, theo trạng thái.
4. **Nói rõ loại hóa đơn nếu quan trọng:** "đã phát hành", "đã hủy", "không hợp lệ theo cơ quan thuế".
5. **Một câu hỏi một ý.** Câu quá dài hoặc ghép nhiều ý dễ bị hiểu lệch; hãy tách thành nhiều câu rồi hỏi nối tiếp.
6. "Hôm nay" trong hệ thống là **30/06/2025**, nên "tháng này" nghĩa là tháng 6/2025 và "tháng trước" là tháng 5/2025.

### Ví dụ

| Câu hỏi | Nhận xét |
|---|---|
| Có bao nhiêu hóa đơn trong tháng 5 năm 2025? | Rõ |
| Số hóa đơn theo từng tháng trong quý 1 năm 2025. | Rõ, cho ra biểu đồ theo thời gian |
| 5 công ty phát hành nhiều hóa đơn nhất trong tháng 5/2025, kèm số hóa đơn. | Rõ |
| Có bao nhiêu hóa đơn không hợp lệ theo cơ quan thuế trong tháng 5/2025? | Rõ |
| Tỷ lệ phần trăm hóa đơn lập bằng USD trong tháng 5/2025. | Rõ |
| Tổng tiền thuế GTGT theo từng mức thuế suất trong tháng 5/2025. | Rõ |
| Có bao nhiêu hóa đơn đã hủy trong tháng 4/2025? | Rõ |
| Công ty nào lớn nhất? | **Mơ hồ** ("lớn nhất" theo gì?). Hệ thống sẽ hỏi lại |
| Cho tôi số liệu tháng này. | **Mơ hồ** (số liệu gì?). Hệ thống sẽ hỏi lại |
| Dự báo số hóa đơn tháng 7. | Ngoài dữ liệu, bị từ chối |

### Hỏi nối tiếp
Sau một câu trả lời, bạn có thể hỏi tiếp ngắn gọn: "Còn tháng 4 thì sao?", "Chỉ lấy hóa đơn đã phát hành", "Sắp xếp theo số hóa đơn giảm dần". Hệ thống ghi "Hiểu là: ..." để bạn xem nó đã bổ sung gì. Khi sang chủ đề khác, bấm **Xóa hội thoại** để tránh bị ảnh hưởng bởi câu trước.

## 5. Đọc kết quả

### Các phần của một câu trả lời

- **Hiểu là: ...**: hệ thống viết lại câu nối tiếp của bạn thành câu đầy đủ. Đọc để chắc nó hiểu đúng.
- **Một con số:** hiện thành thẻ số lớn.
- **Theo thời gian** (cột đầu là tháng hoặc ngày): hiện **biểu đồ đường** kèm bảng.
- **So sánh giữa các nhóm** (tối đa 30 nhóm): hiện **biểu đồ cột ngang** sắp giảm dần kèm bảng. Rê chuột lên cột để xem giá trị.
- **Bảng:** các trường hợp còn lại. Bạn có thể bấm tiêu đề cột để sắp xếp, tải về dạng CSV hoặc xem toàn màn hình bằng các nút trên bảng.
- **Câu SQL đã chạy:** bấm mở để xem câu truy vấn. Nếu ghi "(tự sửa N lần)" nghĩa là lần đầu hệ thống viết sai và đã tự sửa lại; kết quả cuối vẫn dùng được nhưng nên xem SQL nếu số liệu quan trọng.
- Dòng chữ nhỏ **"Bảng đưa vào prompt ... · 4.1s"**: bảng được dùng và thời gian xử lý.

### Các dòng chú thích bạn có thể gặp

| Dòng chú thích | Ý nghĩa | Bạn nên làm |
|---|---|---|
| "Số liệu tính cả hóa đơn nháp (chưa có số)..." | Câu trả lời không loại hóa đơn nháp | Hỏi lại với "chỉ hóa đơn đã phát hành" nếu cần |
| "🔎 Kết quả ban đầu có dấu hiệu không khớp câu hỏi, model đã sửa lại" | Hệ thống tự kiểm tra thấy hình dạng kết quả lạ (ví dụ hỏi một con số mà ra nhiều dòng) và đã sửa | Xem lại SQL |
| "🔎 ...model giữ nguyên câu SQL, hãy kiểm tra lại" | Hệ thống nghi ngờ nhưng giữ nguyên câu trả lời | **Kiểm tra kỹ** trước khi dùng |
| "Chỉ hiển thị 200 dòng đầu" | Kết quả dài hơn giới hạn hiển thị | Thu hẹp câu hỏi (thêm khoảng thời gian, hỏi top N) |
| "Không có dữ liệu thỏa điều kiện" | Câu truy vấn chạy được nhưng không có dòng nào | Kiểm tra khoảng thời gian và điều kiện lọc |

## 6. Những điều cần biết về số liệu

Đây là phần quan trọng nhất. Hệ thống trả lời đúng theo dữ liệu, nhưng **dữ liệu có đặc điểm có thể làm bạn hiểu nhầm**.

1. **Khoảng 91% bản ghi là hóa đơn nháp** (chưa có số hóa đơn). Nếu bạn chỉ hỏi "hóa đơn" mà không nói gì thêm, hệ thống đếm **cả nháp**. Muốn số liệu hóa đơn đã phát hành, hãy nói rõ "đã phát hành".
   Quy ước "hóa đơn" mặc định có tính nháp hay không **chưa được người nghiệp vụ xác nhận chính thức**.
2. **Có công ty thử nghiệm với số lượng lớn.** Ví dụ tháng 5/2025, một công ty thử chiếm khoảng 72% số hóa đơn, nên bảng xếp hạng công ty thường bị chi phối bởi dữ liệu thử (tên có thể giống "Công ty test..." hoặc là một chuỗi tên dài lặp lại). Hãy coi các dòng như vậy là dữ liệu thử, chưa có danh sách chính thức để loại.
3. **Hóa đơn bị hủy, bị thay thế, bị điều chỉnh** vẫn nằm trong dữ liệu. Hãy nêu rõ nếu bạn muốn loại hoặc chỉ lấy loại đó. Hóa đơn điều chỉnh giảm có số tiền âm nên khi cộng tổng sẽ tự trừ.
4. **Thuế suất:** mã âm có nghĩa riêng (-1 không chịu thuế, -2 không kê khai nộp thuế, -3 thuế suất khác). Thuế suất `0` **không chắc là thuế 0%**; thống kê theo từng mức thuế nên dựa vào dòng hàng hóa.
5. **"Dòng hàng hóa", "mặt hàng", "số lượng hàng hóa bán ra"** hiện chỉ tính các dòng là hàng hóa dịch vụ (không tính dòng chiết khấu, khuyến mại, ghi chú).
6. **"Doanh thu"** chưa có định nghĩa chính thức. Nếu bạn dùng chữ này, hệ thống dùng tổng tiền hàng chưa thuế và nêu rõ đã dùng cột nào. Nên dùng rõ "tiền hàng chưa thuế" hoặc "tổng thanh toán".
7. **Dữ liệu chủ yếu là tháng 3 đến 5/2025.** Các tháng khác có thể rất ít (tháng 1 và 2 chỉ vài nghìn hóa đơn), nên so sánh giữa các tháng phải thận trọng.
8. **Độ đúng của hệ thống đo trên bộ câu hỏi do nhóm kỹ thuật tự viết**, khoảng 95 đến 100% tùy bộ. Đó là cận trên, chưa phải độ đúng trên câu hỏi thật của bạn. Khi số liệu dùng cho quyết định hoặc báo cáo chính thức, **hãy đối chiếu với báo cáo hiện có của công ty**.

## 7. Hệ thống hỏi lại hoặc từ chối

| Bạn thấy | Nghĩa là | Bạn làm gì |
|---|---|---|
| Khung xanh **"Câu hỏi hơi mơ hồ: ..."** | Câu hỏi có nhiều cách hiểu cho kết quả khác nhau, hệ thống đưa 2 đến 3 lựa chọn | Trả lời ngắn, ví dụ "theo tổng tiền hàng trong tháng 5/2025" |
| Khung vàng **"Không thể trả lời từ dữ liệu này: ..."** | Dữ liệu không có thông tin đó, hoặc bạn yêu cầu sửa, xóa dữ liệu | Đổi câu hỏi hoặc hỏi người quản trị nếu bạn nghĩ dữ liệu có |
| Khung đỏ (lỗi) | Hệ thống gặp lỗi khi xử lý | Xem [Xử lý sự cố](#10-xử-lý-sự-cố) |

Hệ thống cố ý **hỏi lại hoặc từ chối thay vì đoán**, vì một con số sai mà trông hợp lý còn nguy hiểm hơn không có con số. Tuy vậy, một số câu mơ hồ vẫn có thể bị hệ thống tự đoán (khoảng 4 trên 17 câu mơ hồ trong bộ thử): luôn xem "Hiểu là ..." và câu SQL.

## 8. Gửi phản hồi

Dưới mỗi câu trả lời có hai nút:

- **👍 Đúng:** kết quả đúng ý bạn.
- **👎 Sai:** kết quả không đúng. Hãy bấm khi thấy sai, kể cả khi bạn không biết lỗi nằm ở đâu.

Phản hồi được lưu cùng câu hỏi và câu SQL để nhóm kỹ thuật xem lại và cải thiện hệ thống (ví dụ bổ sung định nghĩa nghiệp vụ). Nếu bạn biết đáp án đúng hoặc lý do, hãy nhắn thêm cho người quản trị kèm câu hỏi đã dùng.

## 9. Quyền và bảo mật

- Hệ thống **chỉ đọc**. Mọi yêu cầu thêm, sửa, xóa đều bị từ chối.
- Vai trò mặc định `analyst` **không xem được dữ liệu cá nhân của người mua**: tên, địa chỉ, số điện thoại, email, MST người mua, số tài khoản, người tạo, người phát hành, ghi chú. Câu hỏi cần các cột này sẽ bị từ chối, và email, số điện thoại nếu lọt vào kết quả sẽ bị che.
- Vai trò `admin` (xem đầy đủ) chỉ dành cho người quản trị, cần mật khẩu riêng.
- Câu hỏi và câu trả lời được **ghi log** để cải thiện hệ thống. Đừng nhập thông tin nhạy cảm không cần thiết vào ô hỏi.
- Trang hiện dùng một mật khẩu chung và **chưa đăng nhập theo từng người**, nên đừng chia sẻ địa chỉ hay mật khẩu ra ngoài nhóm.

## 10. Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Không mở được trang | Máy chủ chạy ứng dụng đang tắt, hoặc địa chỉ đã đổi (địa chỉ tạm thường đổi khi khởi động lại) | Hỏi người quản trị địa chỉ mới |
| Hỏi mật khẩu khi mở trang | Trang có lớp bảo vệ | Nhập thông tin người quản trị đã gửi |
| Trả lời rất chậm hoặc "đang suy nghĩ" lâu | Model đang bận (nhiều người hỏi cùng lúc) | Chờ thêm hoặc hỏi lại sau vài phút. Mỗi câu thường 4 đến 8 giây |
| Thông báo "Không kết nối được ClickHouse" | Máy chủ chưa kết nối được tới database | Báo người quản trị |
| Thông báo "Truy vấn vượt quá ... giây" hoặc vượt giới hạn tài nguyên | Câu hỏi đọc quá nhiều dữ liệu | Thu hẹp khoảng thời gian, hỏi top N thay vì toàn bộ danh sách |
| Thông báo lỗi liên quan đến model hoặc API | Model đang quá tải hoặc không kết nối được | Thử lại sau; nếu lặp lại thì báo người quản trị |
| Kết quả có vẻ sai | Hiểu sai định nghĩa, hoặc câu hỏi chưa đủ rõ | Mở "Câu SQL đã chạy", đọc "Hiểu là", hỏi lại rõ hơn, bấm 👎 |
| Số liệu khác báo cáo chính thức | Có thể do hóa đơn nháp, hóa đơn thử, hoặc định nghĩa khác nhau | Xem [mục 6](#6-những-điều-cần-biết-về-số-liệu), báo nhóm kỹ thuật kèm câu hỏi |
| Biểu đồ nhãn quá dài hoặc rối | Tên công ty trong dữ liệu rất dài (thường là dữ liệu thử) | Xem bảng bên dưới biểu đồ |

## 11. Câu hỏi thường gặp

**Hệ thống có tự bịa số liệu không?**
Mọi con số đều do database trả về, hệ thống không tự viết số. Rủi ro nằm ở chỗ **hiểu sai định nghĩa** (ví dụ tính cả hóa đơn nháp) chứ không phải bịa số. Vì vậy luôn có câu SQL để bạn kiểm tra.

**Làm sao biết kết quả đúng?**
Mở "Câu SQL đã chạy" và kiểm tra khoảng thời gian, điều kiện lọc, bảng được dùng. Với số liệu quan trọng, đối chiếu một vài con số với báo cáo hiện có.

**Vì sao cùng một câu hỏi, hai lần hỏi cho kết quả hơi khác nhau?**
Model có thể diễn đạt SQL theo cách khác nhau, và với các câu có định nghĩa chưa chốt (hóa đơn nháp, tính chất dòng hàng) kết quả có thể lệch nhẹ. Hãy nêu rõ định nghĩa trong câu hỏi.

**Tôi có thể hỏi bằng tiếng Việt không dấu hoặc viết tắt không?**
Có. Bộ thử diễn đạt lại (không dấu, khẩu ngữ, viết tắt) cho kết quả đúng 36/36, nhưng câu có dấu và đủ từ vẫn ổn định hơn.

**Tôi có thể xuất kết quả ra Excel không?**
Trong bảng kết quả có nút tải xuống ở góc trên bên phải bảng (định dạng CSV, mở được bằng Excel).

**Tôi muốn xem dữ liệu cá nhân của một khách hàng thì sao?**
Vai trò `analyst` không được. Nếu bạn có nhu cầu hợp lệ, hãy liên hệ người quản trị.

**Dữ liệu cập nhật đến khi nào?**
Dữ liệu trong hệ thống tập trung vào năm 2025 và "hôm nay" được cố định là 30/06/2025 để kết quả lặp lại được.

## 12. Phụ lục dành cho người quản trị

Mục này chỉ dành cho người vận hành, không cần với người dùng thông thường.

**Mở ứng dụng cho nhóm thử**
1. Chạy giao diện: `python -m streamlit run app.py --server.port 8501`.
2. Mở ngrok cho cổng 8501 **kèm xác thực bắt buộc**. Với bản ngrok hiện tại, dùng file Traffic Policy có `basic-auth` (cờ `--basic-auth` có thể bị bỏ qua, hãy kiểm tra bằng cách mở địa chỉ khi chưa nhập mật khẩu: phải trả về 401).
3. Gửi địa chỉ và mật khẩu cho nhóm qua kênh riêng. Tắt ngrok khi không dùng.

**Chế độ quản trị**
- Đặt `T2SQL_ADMIN_PASSWORD` trong `.env`, khởi động lại ứng dụng. Ở thanh bên, mở **Chế độ quản trị** và nhập mật khẩu để thấy vai trò `admin`, mục **Model qua MCP** và ô chọn **Model**.

**Cho người khác thử model của họ qua MCP**
- Trong **Model qua MCP**, bấm **Tạo link mời** (dùng một lần, hết hạn theo giờ bạn chọn) rồi gửi kèm [huong_dan_ket_noi_model_mcp.md](huong_dan_ket_noi_model_mcp.md). Sau khi họ lưu, chọn hồ sơ ở ô **Model**.
- Đặt `T2SQL_PUBLIC_URL` để link mời có đủ địa chỉ.

**Xem log và phản hồi**
- Log truy vấn và phản hồi 👍/👎 nằm ở `logs/queries.jsonl` (không đưa lên git).

**Khi nào nên khởi động lại ứng dụng**
- Sau khi sửa `.env` hoặc mã nguồn (Streamlit không nạp lại các module bên trong thư mục `t2sql/` khi chỉ lưu file).

**Giới hạn hiện tại cần biết trước khi mở cho nhiều người**
- Chưa có đăng nhập theo từng người, chưa giới hạn số câu chạy đồng thời, tài khoản ClickHouse chưa có giới hạn tài nguyên phía server. Xem [tai_lieu_ky_thuat.md](tai_lieu_ky_thuat.md) mục 11.

## Tài liệu liên quan
- [README](../README.md): tổng quan sản phẩm.
- [tai_lieu_ky_thuat.md](tai_lieu_ky_thuat.md): các kỹ thuật bên trong hệ thống.
- [huong_dan_ket_noi_model_mcp.md](huong_dan_ket_noi_model_mcp.md): kết nối model của người khác.
