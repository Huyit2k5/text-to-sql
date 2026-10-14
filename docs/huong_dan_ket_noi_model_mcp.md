# Kết nối model của bạn qua MCP để thử Text-to-SQL

Tài liệu này dành cho người có model (tự host hoặc qua API) muốn cho nhóm Text-to-SQL thử model đó mà **không đưa khóa API**.
Khóa vẫn nằm ở phía bạn: bạn dựng một MCP server nhỏ bọc model, rồi điền địa chỉ vào trang cấu hình. Hệ thống Text-to-SQL chỉ gọi một công cụ trên server đó.

## Bạn cần có

1. Một **MCP server** có ít nhất một công cụ nhận câu hỏi (chuỗi) và trả về văn bản do model sinh ra.
   Nên có thêm tham số nhận system prompt; nếu không có, hệ thống gộp system prompt vào đầu câu hỏi.
2. Địa chỉ truy cập được từ máy chạy ứng dụng Text-to-SQL (HTTPS nếu là địa chỉ công khai).
3. Một token riêng cho việc này, quyền tối thiểu, có thời hạn. Token bạn nhập sẽ được lưu trên máy chạy ứng dụng và người quản trị đọc được.

## Các bước

1. Nhận **link mời** từ người quản trị (hết hạn sau vài giờ, chỉ dùng một lần).
2. Mở link, điền địa chỉ MCP, kiểu kết nối (Streamable HTTP là mặc định), header xác thực và giá trị.
3. Bấm **Dò công cụ**, chọn công cụ gọi model. Trang tự đoán tham số prompt và system; sửa lại nếu sai.
4. Bấm **Gửi thử một câu**: phải nhận được câu trả lời mới lưu được.
5. Đặt tên hồ sơ và **Lưu**. Link mời hết hiệu lực.

Muốn thu hồi: bảo người quản trị xóa hồ sơ, và nên đổi hoặc hủy token ở phía bạn.

## Khung MCP server tối thiểu

Chỉ phần gọi model (`call_my_model`) là của bạn; phần MCP đã được thử với SDK `mcp` 2.x.

```python
from mcp.server.mcpserver import MCPServer      # SDK 1.x: from mcp.server.fastmcp import FastMCP

srv = MCPServer("my-llm")

def call_my_model(system: str, prompt: str) -> str:
    ...   # gọi API / model tự host của bạn bằng khóa của bạn, trả về văn bản

@srv.tool(description="Sinh văn bản từ prompt và system prompt.")
def generate(prompt: str, system: str = "") -> str:
    return call_my_model(system, prompt)

app = srv.streamable_http_app()                  # chạy: uvicorn module:app --host 0.0.0.0 --port 8000
```

Thêm xác thực (ví dụ kiểm tra header `Authorization: Bearer ...` bằng một middleware ASGI) trước khi mở ra ngoài; xem `BearerGate` trong
[tests/fake_mcp_llm_server.py](../tests/fake_mcp_llm_server.py).

## Điều cần biết khi đọc kết quả thử

- Hệ thống không điều khiển được temperature, giới hạn token hay mức suy nghĩ của model qua MCP; công cụ của bạn tự quyết định.
- Số token không được trả về nên báo cáo không có cột chi phí.
- Mỗi câu hỏi gọi model vài lần (sinh SQL, tự sửa lỗi, hỏi lại khi mơ hồ). Giới hạn tốc độ phía bạn ảnh hưởng thời gian chạy.
- Prompt gửi sang server của bạn gồm schema, quy tắc nghiệp vụ, ví dụ và câu hỏi (không có dòng dữ liệu hóa đơn thật trừ khi bật các bước giải thích hoặc kiểm tra ngữ nghĩa).
- Điểm thấp hơn model nội bộ không nhất thiết có nghĩa model của bạn kém: tài liệu nghiệp vụ và ví dụ đã được chỉnh theo model nội bộ.

## Dành cho người quản trị

- Đặt `T2SQL_ADMIN_PASSWORD`, mở thanh bên, nhập mật khẩu quản trị, mở mục **Model qua MCP**, bấm **Tạo link mời**. Đặt `T2SQL_PUBLIC_URL` để link đầy đủ địa chỉ.
- Link mời chỉ mở trang cấu hình, không thấy phần hỏi đáp hay dữ liệu. Chọn model đã cấu hình ở ô **Model** trong thanh bên (chỉ hiện sau khi nhập mật khẩu quản trị).
- Chạy bộ đánh giá: `python evaluate.py --configs production --llm-profile <tên hồ sơ>`; kết quả vào thư mục con `llm_<tên hồ sơ>`.
- Dùng cho CLI hoặc script: đặt `T2SQL_LLM_PROFILE=<tên hồ sơ>` trong `.env`.
- Địa chỉ do người ngoài nhập bị kiểm tra: chỉ http/https, chặn link-local (nơi đặt metadata đám mây) và loopback, địa chỉ công khai bắt buộc https.
  Đặt `T2SQL_MCP_ALLOWED_HOSTS` để chỉ chấp nhận đúng host của leader.
- File hồ sơ `.cache/llm_profiles.json` chứa token, đã nằm ngoài git; đừng sao chép đi.
