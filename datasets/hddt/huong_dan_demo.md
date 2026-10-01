# Hướng dẫn demo Text-to-SQL trên dữ liệu hóa đơn `hddt`

## 1. Chạy giao diện
```
streamlit run app.py
```
Mở http://localhost:8501. Cần `.env` có `T2SQL_DATABASE_URL_CONGTY` (xem `.env.example`) và máy chạy được kết nối tới ClickHouse công ty
(đúng mạng nội bộ / VPN). Kiểm tra trước bằng `python connect_company.py`.

Thanh bên trái:
- **Database:** chọn `ClickHouse · hddt`. Lần đầu mất khoảng 30 giây để nạp cấu trúc bảng; các lần sau trong cùng phiên thì nhanh.
- **Pipeline:** để `production`.
- **Vai trò người dùng:** mặc định `analyst` (không đọc được thông tin cá nhân của khách: tên, số điện thoại, email, số tài khoản, MST người mua...).
  Chỉ chọn `admin` khi người dùng được phép xem các cột đó.
- **Giải thích SQL bằng lời:** tắt đi nếu thấy chậm (mỗi câu thêm một lần gọi model).
- **Self-consistency:** sinh 3 phương án rồi chọn kết quả được nhiều phương án đồng ý. Chậm hơn 2–3 lần, nên chỉ bật khi muốn chứng minh độ tin cậy.
- Dưới mỗi câu trả lời: mở "Câu SQL đã chạy" để xem SQL, và bấm **👍 Đúng / 👎 Sai** (phản hồi được lưu trong thư mục `logs/`).

## 2. Kịch bản demo gợi ý (khoảng 10 phút)
Các câu dưới đây đã chạy đúng trong lần đánh giá gần nhất (tháng 5/2025 có khoảng 98 nghìn hóa đơn). Mỗi câu thường mất 4–10 giây.

| Bước | Câu hỏi | Điều muốn cho khách thấy |
|---|---|---|
| 1 | Có bao nhiêu hóa đơn trong tháng 5 năm 2025? | Hỏi bằng tiếng Việt thường, ra con số. Mở SQL để thấy hệ thống tự thêm `FINAL` và `is_deleted = 0`. |
| 2 | Còn tháng 4 thì sao? | Hiểu câu hỏi nối tiếp (hội thoại nhiều lượt). |
| 3 | Số hóa đơn theo từng tháng trong quý 1 năm 2025. | Nhóm theo thời gian. |
| 4 | 5 công ty phát hành nhiều hóa đơn nhất trong tháng 5/2025, kèm số hóa đơn. | Top N. |
| 5 | Có bao nhiêu hóa đơn không hợp lệ theo cơ quan thuế trong tháng 5/2025? | Dùng đúng định nghĩa nghiệp vụ (`TCTCheckStatus = -2`). |
| 6 | Tỷ lệ phần trăm hóa đơn lập bằng USD trong tháng 5/2025. | Tính phần trăm. |
| 7 | Tổng số lượng hàng hóa trên các hóa đơn hợp lệ theo cơ quan thuế trong tháng 5/2025. | Nối hai bảng; câu nặng (khoảng 15 giây), hệ thống tự viết lại cho gọn. |
| 8 | Cho tôi số điện thoại khách hàng của 3 hóa đơn mới nhất. | **Bảo mật:** vai trò `analyst` bị từ chối vì schema không có cột này. |
| 9 | Xóa toàn bộ hóa đơn tháng 5. | **An toàn:** bị từ chối, hệ thống chỉ đọc dữ liệu. |
| 10 | Dự báo số hóa đơn tháng 7/2025. | Biết từ chối câu hỏi nằm ngoài dữ liệu thay vì bịa. |

## 3. Những điều nên nói trước với người xem
- **Kết quả chỉ đáng tin sau khi có người nghiệp vụ đối chiếu.** Trên bộ câu hỏi nội bộ 46 câu, hệ thống đúng khoảng 83 – 100% tùy cách chấm (chấm khắt khe 83 – 90%, chấm nới lỏng cách viết tháng và cột phụ 98 – 100%)
  (xem `results/` và báo cáo), nhưng các câu hỏi đó do nhóm kỹ thuật viết. Chưa đo bằng câu hỏi thật của người dùng.
- **Dữ liệu có hóa đơn thử nghiệm** (công ty "test…", số lượng và tiền cực lớn): một số kết quả "lớn bất thường" là do dữ liệu, không phải do hệ thống.
- **Chưa trả lời được (hoặc trả lời "chưa có định nghĩa"):**
  - hóa đơn đã hủy (chưa biết cột nào ghi hủy);
  - hóa đơn "có hiệu lực" / doanh thu chính thức (chưa chốt định nghĩa);
  - thống kê theo tỉnh thành (cột tên tỉnh trống);
  - ý nghĩa của các mã `Status` ngoài `TCTCheckStatus`, `Type`.
- **Câu hỏi nặng** (cả năm, nối bảng lớn) có thể mất 20 – 30 giây; hệ thống tự cắt nếu quá 30 giây.
- **Ghi log:** câu hỏi và SQL được lưu trong `logs/` (không có dữ liệu trả về nhưng có nội dung câu hỏi); đừng gửi log ra ngoài.
- **Thanh bên hiển thị tên tài khoản và địa chỉ máy chủ ClickHouse** (dòng "Database: ..."). Không chiếu màn hình này cho người ngoài.

## 4. Xử lý sự cố nhanh
| Hiện tượng | Cách xử lý |
|---|---|
| "Không kết nối được ClickHouse" | Kiểm tra VPN / mạng nội bộ; chạy `python connect_company.py`. |
| "Không khởi tạo được pipeline" | Kiểm tra `.env` (`LLM_*`, `T2SQL_DATABASE_URL_CONGTY`); model tự host có đang chạy không. |
| Câu trả lời lỗi "LLM" lặp lại | Model tự host quá tải; chờ ít phút rồi hỏi lại (đã gặp khi chạy đánh giá liên tục). |
| "Truy vấn vượt quá 30s" | Hỏi hẹp hơn (một tháng thay vì cả năm), hoặc nhờ DBA nâng giới hạn. |
| Kết quả "lạ" | Mở "Câu SQL đã chạy", bấm 👎, ghi lại câu hỏi để bổ sung vào bộ đánh giá. |
