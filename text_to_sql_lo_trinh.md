# Lộ trình project Text-to-SQL (Mức 1 đến Mức 3)

**Mục tiêu:** người dùng hỏi bằng ngôn ngữ tự nhiên, hệ thống sinh câu SQL, chạy trên database và trả kết quả kèm giải thích.

**Nguyên tắc:** mỗi mức phải có một bản chạy được và một con số đo được (execution accuracy) trước khi sang mức tiếp theo.

---

## Bước 0: Chuẩn bị (làm một lần)

- **Database mẫu:** SQLite, dùng Chinook hoặc tự tạo 3-4 bảng (`customers`, `orders`, `order_items`, `products`).
- **Bộ đánh giá:** viết 50-100 cặp (câu hỏi, SQL chuẩn). Chia độ khó: dễ (1 bảng), trung bình (JOIN, GROUP BY), khó (subquery, nhiều JOIN, tính theo ngày tháng).
- **Ngôn ngữ và công cụ:** Python. `sqlite3`, `json`, `urllib` đều nằm trong thư viện chuẩn nên có thể giữ code thuần. Riêng phần gọi LLM cần gọi API qua HTTP (`urllib.request`) hoặc dùng SDK của nhà cung cấp.

---

## Mức 1: Bản chạy được (khoảng 1 tuần)

### Approach
1. Đọc schema từ SQLite (`sqlite_master` hoặc `PRAGMA table_info`), ghép thành chuỗi mô tả.
2. Prompt gồm: schema + câu hỏi + yêu cầu "chỉ trả về một câu SQL".
3. Gọi LLM, làm sạch kết quả (bỏ dấu ``` và chữ thừa).
4. Chạy SQL bằng `sqlite3`, in kết quả.
5. Giao diện tối giản: vòng lặp `input()` trên terminal, hoặc Streamlit/Gradio nếu muốn demo.

### Edge cases
- LLM trả kèm giải thích hoặc markdown quanh câu SQL: cần bước tách SQL.
- SQL sai cú pháp: bắt lỗi, hiển thị thông báo, không để chương trình dừng.
- Kết quả rỗng: báo rõ "không có dữ liệu", không im lặng.
- Kết quả quá lớn: giới hạn số dòng in ra.
- Câu hỏi không liên quan đến database: trả lời "không thể trả lời từ dữ liệu này".

### Đầu ra cần có
- Script chạy end-to-end.
- Kết quả **execution accuracy lần đầu** trên bộ 50 câu (đây là baseline).

---

## Mức 2: Làm cho đáng tin (khoảng 2-3 tuần, chỗ có chiều sâu)

### Approach
Thêm từng cải tiến một, mỗi lần chạy lại bộ đánh giá và ghi số vào bảng ablation.

1. **Mô tả cột và giá trị mẫu:** thêm chú thích nghiệp vụ (ví dụ `status = 3` nghĩa là đã hủy), kèm 2-3 giá trị mẫu cho mỗi cột.
2. **Few-shot theo ngữ cảnh:** lưu các cặp (câu hỏi, SQL đúng), tính độ giống với câu hỏi mới và đưa k ví dụ gần nhất vào prompt.
3. **Schema linking:** khi database lớn, chỉ đưa các bảng/cột liên quan vào prompt (dùng embedding hoặc chấm điểm từ khóa đơn giản).
4. **Tự sửa lỗi:** nếu SQL lỗi hoặc trả rỗng, gửi lại câu hỏi + SQL cũ + thông báo lỗi cho LLM để sinh lại, tối đa N lần (ví dụ N = 3).
5. **Phân tích lỗi:** gom các câu sai theo nhóm: chọn sai bảng, sai JOIN, sai điều kiện lọc, hiểu sai nghiệp vụ, sai hàm ngày tháng.

### Edge cases
- Vòng lặp tự sửa không kết thúc: luôn đặt giới hạn số lần thử.
- Few-shot làm prompt quá dài: giới hạn số ví dụ và độ dài.
- Hai SQL khác nhau nhưng kết quả giống nhau: chấm theo **kết quả thực thi**, không so khớp chuỗi.
- Thứ tự dòng khác nhau khi so kết quả: chuẩn hóa bằng cách sắp xếp trước khi so (trừ khi câu hỏi yêu cầu thứ tự).
- Cột đặt tên gây nhầm (ví dụ `date`, `name` có ở nhiều bảng): dùng alias rõ ràng, nêu trong prompt.

### Bảng ablation cần có

| Cấu hình | Execution accuracy | Ghi chú |
|---|---|---|
| Baseline (Mức 1) | ? | |
| + Mô tả cột | ? | |
| + Few-shot | ? | |
| + Schema linking | ? | |
| + Tự sửa lỗi | ? | |

---

## Mức 3: Chuẩn production (khoảng 2-3 tuần)

### Approach
1. **An toàn thực thi:**
   - Chỉ cho phép `SELECT`; chặn `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`.
   - Kết nối database ở chế độ chỉ đọc (SQLite: `file:...?mode=ro`).
   - Giới hạn số dòng (`LIMIT`) và thời gian chạy.
2. **Phân quyền:** mỗi user chỉ được truy vấn một số bảng/cột nhất định; kiểm tra danh sách bảng trong SQL sinh ra trước khi chạy.
3. **Hội thoại nhiều lượt:** lưu lịch sử, viết lại câu hỏi nối tiếp thành câu hỏi độc lập ("còn tháng trước thì sao?").
4. **Xử lý câu hỏi mơ hồ:** khi có nhiều cách hiểu, hỏi lại người dùng thay vì đoán.
5. **Giải thích và kiểm chứng:** hiển thị câu SQL và diễn giải bằng lời để người dùng tự kiểm tra.
6. **Trực quan hóa:** tự chọn bảng hoặc biểu đồ phù hợp với kiểu kết quả.
7. **Ghi log:** lưu câu hỏi, SQL, kết quả, độ trễ, phản hồi đúng/sai của người dùng để cải thiện tiếp.

### Edge cases
- SQL đúng cú pháp nhưng **sai ngữ nghĩa** (nguy hiểm nhất vì người dùng không biết): luôn hiển thị SQL, cho phép phản hồi.
- Prompt injection nằm trong dữ liệu (ví dụ ô mô tả chứa lệnh "bỏ qua hướng dẫn trước"): không đưa dữ liệu thô vào prompt như chỉ dẫn.
- Nhiều câu lệnh trong một chuỗi (`SELECT ...; DROP ...`): chỉ chấp nhận đúng một câu lệnh.
- Truy vấn nặng (JOIN không điều kiện) làm treo database: đặt timeout.
- Lộ dữ liệu nhạy cảm (email, số điện thoại): che hoặc chặn cột nhạy cảm.
- Câu hỏi ngoài phạm vi hoặc yêu cầu sửa/xóa dữ liệu: từ chối lịch sự.

---

## Hướng mở rộng (tùy chọn)

- **Fine-tune model nhỏ (LoRA)** chuyên sinh SQL, so sánh chi phí và chất lượng với model lớn.
- **Benchmark chuẩn:** thử trên Spider hoặc BIRD để có số liệu so sánh được với cộng đồng.
- **Đa ngôn ngữ:** câu hỏi tiếng Việt, tên cột tiếng Anh (điểm khác biệt vì phần lớn benchmark chỉ có tiếng Anh).
- **Trade-off:** vẽ đồ thị accuracy vs chi phí vs độ trễ theo số lần retry, kích thước model, độ dài prompt.

---

## Checklist hoàn thành

- [ ] Mức 1 chạy end-to-end, có baseline accuracy
- [ ] Bộ đánh giá 50-100 câu, chấm bằng execution accuracy
- [ ] Mức 2: bảng ablation đầy đủ và phân tích lỗi
- [ ] Mức 3: lớp an toàn, phân quyền, hội thoại nhiều lượt
- [ ] Demo (Streamlit/Gradio) và README giải thích kiến trúc, kết quả, hạn chế
