"""Kết nối vào endpoint MCP do WeKnora công bố (Settings > MCP Server) và liệt kê hoặc gọi công cụ.

Đọc WEKNORA_MCP_URL và WEKNORA_MCP_TOKEN từ .env (không in token). Mặc định chỉ LIỆT KÊ công cụ.

  python experiments/mcp/weknora_endpoint.py                       # liệt kê công cụ
  python experiments/mcp/weknora_endpoint.py --ask "câu hỏi"       # gọi công cụ ask một lần
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from t2sql import ROOT  # noqa: E402,F401  (nạp .env)


def mask(text: str, secret: str) -> str:
    return text.replace(secret, "<token>") if secret else text


async def connect(url, token, style):
    from contextlib import AsyncExitStack
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    headers = {"Authorization": f"Bearer {token}"} if style == "bearer" else {"X-API-Key": token}
    stack = AsyncExitStack()
    try:
        http = await stack.enter_async_context(create_mcp_http_client(headers=headers, timeout=420))
        rd, wr, *_ = await stack.enter_async_context(streamable_http_client(url, http_client=http))
        session = await stack.enter_async_context(ClientSession(rd, wr))
        await session.initialize()
        return stack, session
    except BaseException:
        await stack.aclose()
        raise


async def run(args):
    url, token = os.environ.get("WEKNORA_MCP_URL"), os.environ.get("WEKNORA_MCP_TOKEN")
    if not url or not token:
        sys.exit("Thiếu WEKNORA_MCP_URL hoặc WEKNORA_MCP_TOKEN trong .env")
    last = None
    for style in ("bearer", "x-api-key"):
        try:
            stack, session = await connect(url, token, style)
            print(f"Kết nối được (xác thực: {style})")
            break
        except BaseException as e:      # noqa: BLE001
            last = f"{style}: {type(e).__name__}: {mask(str(e), token)[:300]}"
            print("Không kết nối được bằng", last)
    else:
        sys.exit("Thất bại với cả hai kiểu xác thực.")
    try:
        tools = (await session.list_tools()).tools
        print(f"{len(tools)} công cụ:")
        for t in tools:
            props = list((getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}).get("properties", {}))
            print(f"- {t.name}  tham số: {props}")
            print("    ", " ".join((t.description or "").split())[:220])
        if args.call:
            res = await session.call_tool(args.call, {})
            print(f"Gọi {args.call}: is_error={res.is_error}")
            for c in res.content:
                print(mask(getattr(c, "text", str(c)), token)[:3000])
        if args.ask:
            name = args.tool or next((t.name for t in tools if t.name == "ask"), None)
            if not name:
                sys.exit("Không có công cụ 'ask'; dùng --tool để chọn tên công cụ.")
            print(f"\nGọi {name}: {args.ask}")
            res = await session.call_tool(name, {args.arg: args.ask})
            print("is_error:", res.is_error)
            for c in res.content:
                print(mask(getattr(c, "text", str(c)), token)[:6000])
    finally:
        await stack.aclose()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", default=None, help="câu hỏi gửi cho công cụ ask")
    ap.add_argument("--tool", default=None, help="tên công cụ (mặc định: ask)")
    ap.add_argument("--arg", default="question", help="tên tham số của công cụ")
    ap.add_argument("--call", default=None, help="gọi một công cụ không cần tham số (ví dụ list_knowledge_bases)")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
