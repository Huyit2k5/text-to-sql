# Kết nối công cụ `ask_data` vào WeKnora (một trang)

Công cụ `ask_data` cho phép hỏi dữ liệu hóa đơn điện tử bằng tiếng Việt. Máy chủ chỉ đọc, che dữ liệu cá nhân, mỗi người một token.

## 1. Người vận hành (máy chạy máy chủ MCP)

1. Điền `.env` (xem `.env.example`: các biến `T2SQL_MCP_*`). Đặt `T2SQL_MCP_ALLOWED_HOSTS` bằng tên máy trên tailnet (không có `https://`).
2. Chạy: `docker compose up -d --build mcp` (hoặc `python -m t2sql.mcp_server serve`).
3. Tạo token cho từng người (hiện một lần, hạn mặc định 30 ngày):
   `docker compose exec mcp python -m t2sql.mcp_server token-create --label ten.nguoi.dung`
   Xem: `token-list`. Thu hồi (có hiệu lực ngay): `token-revoke --label ten.nguoi.dung`.
4. Đưa ra tailnet: `tailscale serve --bg 8780` (không dùng Funnel; cần bật HTTPS cho tailnet).
5. Gửi token qua kênh riêng tư, không gửi chung với URL.

## 2. Người quản trị WeKnora

Thêm máy chủ MCP với các giá trị:

| Mục | Giá trị |
|---|---|
| Transport | Streamable HTTP |
| URL | `https://<tên-máy>.<tailnet>.ts.net/mcp` |
| Xác thực | API key, header `X-API-Key` = token (hoặc `Authorization: Bearer <token>`; hoặc Basic: tên bất kỳ, mật khẩu = token) |
| Timeout | 30 giây (máy chủ tự trả lời trước 25 giây) |

Basic auth (nếu cần): header `Authorization: Basic base64(tên:token)`, tên chỉ để dễ đọc, **mật khẩu phải là token**. Thứ tự ưu tiên nếu gửi nhiều kiểu: Bearer, `X-API-Key`, Basic. Không nên đặt token trong URL kiểu `https://tên:token@...` vì sẽ lộ trong lịch sử, log và ảnh chụp màn hình; hãy dùng trường header của WeKnora.

Công cụ xuất hiện là `ask_data` (tham số: `question`, `history`, `detail`).

## 3. Cách dùng và kết quả

- Câu hỏi hợp lệ trả về bảng Markdown, dòng đầu có `[status: answer]`.
- Câu mơ hồ: `[status: clarify]` kèm câu hỏi lại. Hãy hỏi lại người dùng rồi gọi lại với câu rõ hơn.
- Yêu cầu ngoài phạm vi (ghi/xóa dữ liệu, thông tin cá nhân): `[status: cannot]`, đây là từ chối có chủ đích, không phải lỗi.
- Câu nối tiếp ("Còn tháng 4?"): truyền `history` là danh sách các **câu hỏi** trước đó (chỉ chuỗi, tối đa 4).
- Lỗi thật (quá thời gian, mất kết nối) trả về dạng lỗi công cụ kèm gợi ý thử lại.
- Gửi lại đúng câu hỏi đó trong 2 phút sẽ dùng kết quả đang chạy hoặc vừa xong, nên WeKnora tự thử lại không làm chạy trùng trên ClickHouse.

## 4. Giới hạn

Tối đa 2 câu chạy đồng thời toàn máy chủ, 1 câu mỗi người, 20 lệnh mỗi phút mỗi người. Hết chỗ thì báo bận ngay kèm số giây nên chờ.

## 5. Nếu không kết nối được

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| 401 | Token sai, hết hạn hoặc bị thu hồi |
| 421 | `Host` chưa nằm trong `T2SQL_MCP_ALLOWED_HOSTS` |
| Báo địa chỉ bị chặn | WeKnora chặn địa chỉ mạng nội bộ (SSRF): cần quản trị WeKnora cho phép địa chỉ `.ts.net`/`100.x` |
| Không tới được | Hai máy chưa cùng tailnet: chia sẻ máy (node sharing) sang tailnet của WeKnora |
