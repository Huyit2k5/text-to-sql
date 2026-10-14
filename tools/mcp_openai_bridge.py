"""MCP server bọc một model chuẩn OpenAI (vLLM, Bifrost...): cầu nối để thử luồng "model qua MCP" với chính model trong .env.

  python tools/mcp_openai_bridge.py --port 8770 [--token <token>]

Đọc LLM_BASE_URL, LLM_API_KEY, T2SQL_MODEL... từ .env như phần còn lại của dự án (khóa API không rời máy này).
Công cụ `generate(prompt, system="")` trả về văn bản model sinh ra. Chỉ nghe ở 127.0.0.1; mọi request phải có header
`Authorization: Bearer <token>`. Không đặt --token thì sinh token ngẫu nhiên và in ra một lần.

Đây cũng là khung mẫu cho người có model riêng: thay phần gọi model (hàm `call_model`) bằng API của bạn.
"""
import argparse
import asyncio
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

import t2sql  # noqa: E402,F401  (nạp .env)
from t2sql.llm import OpenAICompatLLM  # noqa: E402

srv = MCPServer("openai-bridge")
_llm = None


def call_model(system: str, prompt: str) -> str:
    global _llm
    if _llm is None:
        _llm = OpenAICompatLLM()
    return _llm.complete(system or "Bạn là trợ lý hữu ích.", [{"role": "user", "content": prompt}])


@srv.tool(description="Sinh văn bản từ prompt và system prompt (tùy chọn) bằng model của bridge.")
async def generate(prompt: str, system: str = "") -> str:
    return await asyncio.to_thread(call_model, system, prompt)


class BearerGate:
    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope["headers"]).get(b"authorization", b"").decode()
            if not secrets.compare_digest(auth, f"Bearer {self.token}"):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--token", default=os.environ.get("T2SQL_BRIDGE_TOKEN", ""))
    args = ap.parse_args()
    token = args.token or secrets.token_urlsafe(18)
    if not args.token:
        print(f"Token (chỉ in một lần): {token}", flush=True)
    print(f"MCP server: http://127.0.0.1:{args.port}/mcp  (header Authorization: Bearer <token>)", flush=True)
    uvicorn.run(BearerGate(srv.streamable_http_app(), token), host="127.0.0.1", port=args.port, log_level="warning")
