"""MCP server giả đóng vai "model của leader", dùng cho test và chạy thử cục bộ (không gọi LLM thật).

  python tests/fake_mcp_llm_server.py --port 8765 [--token abc]

Công cụ `generate(prompt, system="")` trả về một câu SQL cố định cho câu hỏi chứa "bao nhiêu", còn lại trả lại nguyên prompt rút gọn.
Có token thì mọi request phải gửi header `Authorization: Bearer <token>`.
"""
import argparse

import uvicorn
from mcp.server.mcpserver import MCPServer


def build(split_system: bool = True) -> MCPServer:
    srv = MCPServer("fake-llm")

    if split_system:
        @srv.tool(description="Sinh văn bản từ prompt (và system prompt tùy chọn).")
        def generate(prompt: str, system: str = "") -> str:
            return _answer(prompt, system)
    else:
        @srv.tool(description="Hỏi con AI một câu.")
        def ask(question: str) -> str:
            return _answer(question, "")
    return srv


def _answer(prompt: str, system: str) -> str:
    if "OK" in prompt and "một từ" in prompt:
        return "OK"
    if "bao nhiêu" in prompt.lower():
        return "```sql\nSELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0\n```"
    return f"[system={len(system)} ký tự] {prompt[:80]}"


class BearerGate:
    """ASGI middleware: từ chối request không có đúng token."""

    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.token:
            headers = dict(scope["headers"])
            if headers.get(b"authorization", b"").decode() != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="")
    ap.add_argument("--single-arg", action="store_true", help="công cụ chỉ nhận một chuỗi, không có system prompt")
    args = ap.parse_args()
    app = BearerGate(build(split_system=not args.single_arg).streamable_http_app(), args.token)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
