"""Kiểm tải máy chủ MCP qua HTTP thật, dùng pipeline GIẢ chậm (không gọi LLM, không gọi ClickHouse).

Kịch bản (giới hạn như bản triển khai: 2 câu đồng thời toàn máy chủ, 1 câu mỗi người, 20 lệnh mỗi phút):
  S1  6 người cùng gửi một lúc
  S2  một người gửi 3 câu khác nhau cùng lúc
  S3  một người gửi 25 câu liên tiếp (giới hạn mỗi phút)
  S4  câu chạy quá hạn, rồi gửi lại như WeKnora thử lại
  S5  5 lần gửi cùng một câu hỏi đồng thời (client thử lại dồn)
  S6  pipeline ném lỗi giữa chừng: chỗ có được nhả không
  S7  thu hồi token khi đang có tải

  python experiments/heavy/mcp_load.py
"""
import asyncio
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from t2sql import mcp_auth, mcp_server  # noqa: E402
from tests.test_mcp_server import FakePipe, free_port, result_answer  # noqa: E402


class SlowPipe(FakePipe):
    def __init__(self, delay=1.0, fail=False):
        super().__init__()
        self.delay, self.fail, self.running, self.max_running = delay, fail, 0, 0
        self._lock = threading.Lock()

    def ask(self, question, history=None, policy=None, exclude_example=None):
        with self._lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.calls.append(question)
        try:
            time.sleep(self.delay)
            if self.fail:
                raise RuntimeError("lỗi giả lập")
            return result_answer(question)
        finally:
            with self._lock:
                self.running -= 1


def start(pipe, deadline_s):
    import uvicorn
    svc = mcp_server.AskService(lambda: pipe, limiter=mcp_auth.Limiter(2, 1, 20), deadline_s=deadline_s)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(mcp_server.build_app(svc), host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    import socket
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}/mcp", server


async def one_call(url, token, question):
    """Một client, một lệnh gọi. Trả (kết quả ngắn, giây)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    t0 = time.perf_counter()
    try:
        async with create_mcp_http_client(headers={"X-API-Key": token}, timeout=60) as http, \
                streamable_http_client(url, http_client=http) as (rd, wr, *_):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                res = await s.call_tool("ask_data", {"question": question})
                text = res.content[0].text if res.content else ""
                kind = "LỖI: " + text[:60].replace("\n", " ") if res.is_error else "ok"
    except BaseException as e:      # noqa: BLE001
        kind = f"{type(e).__name__}"
    return kind, round(time.perf_counter() - t0, 2)


def summarize(results):
    from collections import Counter
    return dict(Counter(k.split(" Hãy")[0] for k, _ in results))


async def main():
    tmp = tempfile.TemporaryDirectory()
    os.environ["T2SQL_MCP_TOKENS_FILE"] = os.path.join(tmp.name, "tokens.json")
    mcp_auth._cache.update(key=None, data=None)
    tok = {n: mcp_auth.create_token(n, days=1) for n in ("u1", "u2", "u3", "u4", "u5", "u6", "solo")}

    # S1
    pipe = SlowPipe(delay=1.0)
    url, srv = start(pipe, deadline_s=10)
    res = await asyncio.gather(*[one_call(url, tok[f"u{i}"], f"câu {i}") for i in range(1, 7)])
    print("S1  6 người cùng lúc, mỗi câu 1 giây:")
    print("    kết quả:", summarize(res), "| nhanh nhất bị từ chối:", min((s for k, s in res if k != "ok"), default=None), "giây")
    print("    số câu chạy song song tối đa trong pipeline:", pipe.max_running, "(giới hạn 2)")
    srv.should_exit = True

    # S2
    pipe = SlowPipe(delay=1.0)
    url, srv = start(pipe, deadline_s=10)
    res = await asyncio.gather(*[one_call(url, tok["solo"], f"câu khác {i}") for i in range(3)])
    print("S2  một người gửi 3 câu khác nhau cùng lúc:")
    print("    kết quả:", summarize(res), "| pipeline nhận", len(pipe.calls), "câu (giới hạn 1)")
    srv.should_exit = True

    # S3
    pipe = SlowPipe(delay=0.0)
    url, srv = start(pipe, deadline_s=10)
    res = []
    for i in range(25):
        res.append(await one_call(url, tok["u1"], f"nhanh {i}"))
    print("S3  một người gửi 25 câu liên tiếp trong vài giây:")
    print("    kết quả:", summarize(res), "| pipeline nhận", len(pipe.calls), "câu (giới hạn 20 mỗi phút)")
    srv.should_exit = True

    # S4
    pipe = SlowPipe(delay=4.0)
    url, srv = start(pipe, deadline_s=1.5)
    first = await one_call(url, tok["u2"], "câu rất chậm")
    other = await one_call(url, tok["u3"], "người khác trong lúc đó")      # còn chỗ toàn máy chủ (2)
    await asyncio.sleep(3.0)                                                 # đợi việc cũ xong
    retry = await one_call(url, tok["u2"], "câu rất chậm")                  # WeKnora thử lại sau khi quá hạn
    print("S4  câu quá hạn 1,5 giây (việc thật 4 giây), rồi thử lại:")
    print("    lần 1:", first, "| người khác trong lúc đó:", other, "| thử lại sau 4,5 giây:", retry)
    print("    pipeline nhận", pipe.calls.count("câu rất chậm"), "lần cho câu chậm (mong đợi 1: lần thử lại dùng kết quả vừa xong)")
    srv.should_exit = True

    # S5
    pipe = SlowPipe(delay=2.0)
    url, srv = start(pipe, deadline_s=10)
    res = await asyncio.gather(*[one_call(url, tok["u4"], "cùng một câu") for _ in range(5)])
    print("S5  5 lần gửi cùng một câu hỏi đồng thời:")
    print("    kết quả:", summarize(res), "| pipeline chạy", len(pipe.calls), "lần (mong đợi 1)")
    srv.should_exit = True

    # S6
    pipe = SlowPipe(delay=0.2, fail=True)
    url, srv = start(pipe, deadline_s=10)
    a = await one_call(url, tok["u5"], "gây lỗi 1")
    b = await one_call(url, tok["u5"], "gây lỗi 2")
    print("S6  pipeline ném lỗi:")
    print("    lần 1:", a, "| lần 2 (chỗ phải đã được nhả):", b)
    srv.should_exit = True

    # S7
    pipe = SlowPipe(delay=1.0)
    url, srv = start(pipe, deadline_s=10)
    ok1 = await one_call(url, tok["u6"], "trước khi thu hồi")
    mcp_auth.revoke_token("u6")
    after = await one_call(url, tok["u6"], "sau khi thu hồi")
    print("S7  thu hồi token khi máy chủ đang chạy:")
    print("    trước:", ok1, "| sau:", after)
    srv.should_exit = True
    tmp.cleanup()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
