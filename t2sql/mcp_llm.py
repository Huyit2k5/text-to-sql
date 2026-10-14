"""LLM qua MCP: model (và khóa API) nằm ở phía người khác, ta chỉ gọi một công cụ trên MCP server của họ.

Hồ sơ (profile) mô tả cách nối: địa chỉ MCP server, header xác thực, tên công cụ và cách ghép tham số.
Hỗ trợ SDK `mcp` 1.x và 2.x. Mỗi lời gọi mở một phiên ngắn (initialize -> call_tool -> đóng), nên dùng được từ nhiều luồng.
"""
import asyncio
import re
import threading
import time

from .llm import BaseLLM, LLMError

_THINK = re.compile(r"<think>.*?</think>", re.S)
PING_PROMPT = "Trả lời đúng một từ: OK"

# Tên tham số hay gặp, dùng để gợi ý khi dò công cụ.
PROMPT_HINTS = ("prompt", "message", "query", "question", "input", "text", "content")
SYSTEM_HINTS = ("system", "system_prompt", "instructions", "instruction")


def _run(coro):
    """Chạy coroutine từ mã đồng bộ; nếu luồng hiện tại đã có event loop thì chạy ở luồng riêng."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box = {}

    def target():
        try:
            box["v"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e
    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


class _Connection:
    """Context manager bất đồng bộ trả về ClientSession đã initialize."""

    def __init__(self, url, headers, transport="http", timeout=60.0):
        self.url, self.headers, self.transport, self.timeout = url, dict(headers or {}), transport, timeout
        self._stack = None

    async def __aenter__(self):
        from contextlib import AsyncExitStack
        from mcp import ClientSession
        stack = AsyncExitStack()
        try:
            if self.transport == "sse":
                from mcp.client.sse import sse_client
                streams = await stack.enter_async_context(sse_client(self.url, headers=self.headers, timeout=self.timeout,
                                                                     sse_read_timeout=self.timeout))
            else:
                try:   # SDK 2.x: truyền header qua http client riêng
                    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
                    http = await stack.enter_async_context(create_mcp_http_client(headers=self.headers))
                    streams = await stack.enter_async_context(streamable_http_client(self.url, http_client=http))
                except ImportError:   # SDK 1.x
                    from mcp.client.streamable_http import streamablehttp_client
                    streams = await stack.enter_async_context(
                        streamablehttp_client(self.url, headers=self.headers, timeout=self.timeout,
                                              sse_read_timeout=self.timeout))
            session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        return session

    async def __aexit__(self, *exc):
        await self._stack.aclose()


def _describe_error(e: BaseException) -> str:
    """Gói lỗi (kể cả ExceptionGroup của anyio) thành một câu ngắn, không lộ nội dung phản hồi của server."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    msg = str(e).strip().splitlines()[0][:200] if str(e).strip() else ""
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


def probe_tools(url, headers=None, transport="http", timeout=30.0) -> list[dict]:
    """Liệt kê công cụ của MCP server: [{name, description, properties: {tên: {type, description}}, required: [...]}]."""
    async def go():
        async with _Connection(url, headers, transport, timeout) as s:
            res = await asyncio.wait_for(s.list_tools(), timeout)
            out = []
            for t in res.tools:
                schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
                out.append({"name": t.name, "description": t.description or "",
                            "properties": schema.get("properties", {}), "required": schema.get("required", [])})
            return out
    try:
        return _run(go())
    except BaseException as e:  # noqa: BLE001
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        raise LLMError(f"Không dò được công cụ của MCP server ({_describe_error(e)}).") from e


def guess_mapping(tool: dict) -> dict:
    """Đoán tên tham số prompt / system của một công cụ từ schema."""
    props = tool.get("properties", {})
    strs = [k for k, v in props.items() if (v or {}).get("type") in (None, "string")]
    low = {k.lower(): k for k in strs}
    system = next((low[h] for h in SYSTEM_HINTS if h in low), None)
    prompt = next((low[h] for h in PROMPT_HINTS if h in low), None)
    if not prompt:
        prompt = next((k for k in tool.get("required", []) if k in strs and k != system), None) \
            or next((k for k in strs if k != system), None)
    messages = next((k for k, v in props.items() if (v or {}).get("type") == "array" and "message" in k.lower()), None)
    return {"prompt_arg": prompt, "system_arg": system, "messages_arg": messages}


def _text_of(result) -> str:
    if getattr(result, "is_error", None) or getattr(result, "isError", False):
        parts = [getattr(c, "text", "") for c in (result.content or [])]
        raise LLMError("Công cụ MCP báo lỗi: " + " ".join(parts)[:300])
    texts = [c.text for c in (result.content or []) if getattr(c, "type", "") == "text" and getattr(c, "text", None)]
    return "\n".join(texts).strip()


class McpLLM(BaseLLM):
    """Gọi một công cụ MCP như một LLM. `profile`:

      url, transport ("http" | "sse"), auth_header + auth_value (tùy chọn), tool,
      prompt_arg, system_arg (None = gộp system vào prompt), messages_arg (None = gộp hội thoại vào prompt),
      fixed_args (dict tham số cố định, ví dụ model), response_key (tùy chọn: lấy trường này nếu công cụ trả JSON),
      timeout_s, name.
    """
    effort = None
    reasoning = "mcp"

    def __init__(self, profile: dict):
        super().__init__()
        for k in ("url", "tool", "prompt_arg"):
            if not profile.get(k):
                raise LLMError(f"Hồ sơ model thiếu '{k}'.")
        self.profile = profile
        self.name = profile.get("name") or "mcp"
        self.model = f"mcp:{self.name}"
        self.timeout = float(profile.get("timeout_s") or 300)
        self.retries = int(profile.get("retries", 1))
        self.headers = {}
        if profile.get("auth_value"):
            self.headers[profile.get("auth_header") or "Authorization"] = profile["auth_value"]

    # --- ghép tham số ---
    def build_args(self, system: str, messages: list[dict]) -> dict:
        p = self.profile
        args = dict(p.get("fixed_args") or {})
        if p.get("messages_arg"):
            args[p["messages_arg"]] = messages
            if p.get("system_arg"):
                args[p["system_arg"]] = system
            else:   # công cụ nhận messages nhưng không có chỗ cho system: đặt thành tin nhắn đầu
                args[p["messages_arg"]] = [{"role": "system", "content": system}] + messages
            return args
        if p.get("system_arg"):
            args[p["system_arg"]] = system
            args[p["prompt_arg"]] = self._conversation(messages, with_system=None)
        else:
            args[p["prompt_arg"]] = self._conversation(messages, with_system=system)
        return args

    @staticmethod
    def _conversation(messages, with_system):
        if len(messages) == 1 and messages[0]["role"] == "user":
            body = messages[0]["content"]
        else:
            names = {"user": "Người dùng", "assistant": "Trợ lý"}
            body = "\n\n".join(f"[{names.get(m['role'], m['role'])}]\n{m['content']}" for m in messages)
            body += "\n\nHãy viết lượt trả lời tiếp theo của Trợ lý."
        return f"{with_system}\n\n---\n{body}" if with_system else body

    def _extract(self, text: str) -> str:
        key = self.profile.get("response_key")
        if key:
            import json
            try:
                data = json.loads(text)
                for part in key.split("."):
                    data = data[part]
                text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            except (ValueError, KeyError, TypeError):
                pass   # không phải JSON như mô tả: dùng nguyên văn
        return _THINK.sub("", text).strip()

    async def _call_async(self, args):
        async with _Connection(self.profile["url"], self.headers, self.profile.get("transport") or "http",
                               self.timeout) as s:
            return await asyncio.wait_for(s.call_tool(self.profile["tool"], args), self.timeout)

    def call_raw(self, args: dict) -> str:
        last = None
        for attempt in range(self.retries + 1):
            try:
                return _text_of(_run(self._call_async(args)))
            except LLMError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as e:  # noqa: BLE001
                last = LLMError(f"Gọi MCP server thất bại ({_describe_error(e)}).")
                last.__cause__ = e
                if attempt < self.retries:
                    time.sleep(2 * (attempt + 1))
        raise last

    def complete(self, system, messages, max_tokens=16000, temperature=None, reasoning=None):
        # max_tokens / temperature / reasoning không truyền được: công cụ MCP của họ tự quyết định.
        t0 = time.perf_counter()
        text = self._extract(self.call_raw(self.build_args(system, messages)))
        self._record(0, 0, time.perf_counter() - t0)
        if not text:
            raise LLMError("Công cụ MCP trả về câu trả lời rỗng.")
        return text

    def ping(self) -> tuple[str, float]:
        """Gọi thử một prompt ngắn; trả (câu trả lời, giây)."""
        t0 = time.perf_counter()
        text = self._extract(self.call_raw(self.build_args("", [{"role": "user", "content": PING_PROMPT}])))
        return text, time.perf_counter() - t0
