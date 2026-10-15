"""Test máy chủ MCP ask_data: kho token, giới hạn tải, dựng văn bản, dịch vụ, và đường HTTP thật (cổng xác thực, 401, thu hồi tức thì).

LLM và pipeline là bản giả, không cần mạng. Riêng các test "live" chạy trên hddt thật (chỉ đọc, LLM giả), tự bỏ qua nếu không có database.
"""
import asyncio
import base64
import json
import os
import socket
import tempfile
import threading
import time
import unittest

try:
    import mcp  # noqa: F401
    import uvicorn
    import httpx
except ImportError:
    raise unittest.SkipTest("chưa cài gói mcp")

from t2sql import mcp_auth, mcp_server
from t2sql.db.base import ExecResult
from t2sql.mcp_llm import _Connection, probe_tools
from t2sql.llm import LLMError
from t2sql.pipeline import Answer, Attempt
from t2sql.safety import Policy


# ------------------------------------------------------------------ đồ giả
class FakeLogger:
    def __init__(self):
        self.events = []

    def event(self, kind, **fields):
        self.events.append({"type": kind, **fields})


class FakePipe:
    """Giống TextToSQL ở mức dịch vụ cần: policies, logger, ask()."""

    def __init__(self, answer=None, delay=0.0):
        self.policies = {"analyst": Policy("analyst", mask_pii=True), "admin": Policy("admin")}
        self.logger = FakeLogger()
        self.answer = answer
        self.delay = delay
        self.calls = []

    def ask(self, question, history=None, policy=None, exclude_example=None):
        self.calls.append({"question": question, "history": history, "policy": policy.name})
        if self.delay:
            time.sleep(self.delay)
        return self.answer or result_answer(question)


def result_answer(question="Q", columns=("so_hd",), rows=((98462,),), sql="SELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0 AND No > 0",
                  truncated=False, attempts=1, standalone=None):
    ans = Answer(question=question, kind="result", sql=sql, result=ExecResult(True, list(columns), list(rows), truncated),
                 standalone_question=standalone)
    ans.attempts = [Attempt(raw="", kind="sql", sql=sql) for _ in range(attempts)]
    return ans


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TempTokens(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("T2SQL_MCP_TOKENS_FILE")
        os.environ["T2SQL_MCP_TOKENS_FILE"] = os.path.join(self._tmp.name, "tokens.json")
        mcp_auth._cache.update(key=None, data=None)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("T2SQL_MCP_TOKENS_FILE", None)
        else:
            os.environ["T2SQL_MCP_TOKENS_FILE"] = self._old
        self._tmp.cleanup()


# ------------------------------------------------------------------ kho token
class TestTokens(TempTokens):
    def test_create_verify_and_plaintext_never_stored(self):
        tok = mcp_auth.create_token("an.nguyen", days=1)
        self.assertEqual(mcp_auth.verify_token(tok)["label"], "an.nguyen")
        self.assertIsNone(mcp_auth.verify_token(tok + "x"))
        self.assertIsNone(mcp_auth.verify_token(""))
        self.assertIsNone(mcp_auth.verify_token(None))
        with open(mcp_auth.tokens_path(), encoding="utf-8") as f:
            self.assertNotIn(tok, f.read())

    def test_revoke_takes_effect_immediately_without_restart(self):
        tok = mcp_auth.create_token("binh", days=1)
        self.assertIsNotNone(mcp_auth.verify_token(tok))
        self.assertTrue(mcp_auth.revoke_token("binh"))
        self.assertIsNone(mcp_auth.verify_token(tok))      # cùng tiến trình, không nạp lại thủ công
        self.assertFalse(mcp_auth.revoke_token("binh"))

    def test_revoke_from_another_process_is_seen(self):
        """CLI (tiến trình khác) ghi file; server phải thấy dù đã đệm: kiểm tra bằng cách sửa file trực tiếp."""
        tok = mcp_auth.create_token("chi", days=1)
        self.assertIsNotNone(mcp_auth.verify_token(tok))
        with open(mcp_auth.tokens_path(), "w", encoding="utf-8") as f:
            json.dump({"tokens": {}}, f)
        os.utime(mcp_auth.tokens_path(), ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
        self.assertIsNone(mcp_auth.verify_token(tok))

    def test_expired_token_rejected_and_listed_inactive(self):
        tok = mcp_auth.create_token("het.han", days=-1)
        self.assertIsNone(mcp_auth.verify_token(tok))
        self.assertFalse(mcp_auth.list_tokens()[0]["active"])

    def test_label_rules(self):
        for bad in ("", "  ", "x" * 61, "Nguyễn", "a/b", "a\nb"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                mcp_auth.create_token(bad)
        mcp_auth.create_token("dup")
        with self.assertRaises(ValueError):
            mcp_auth.create_token("dup")

    def test_list_never_exposes_token(self):
        tok = mcp_auth.create_token("u1")
        self.assertNotIn(tok, json.dumps(mcp_auth.list_tokens()))

    def test_token_from_headers(self):
        f = mcp_auth.token_from_headers
        self.assertEqual(f({"authorization": "Bearer abc"}), "abc")
        self.assertEqual(f({"authorization": "bearer abc"}), "abc")
        self.assertEqual(f({"x-api-key": "k1"}), "k1")
        self.assertEqual(f({"authorization": "Basic zzz", "x-api-key": "k2"}), "k2")      # X-API-Key ưu tiên hơn Basic
        self.assertIsNone(f({"authorization": "Basic zzz"}))                              # base64 hỏng
        enc = lambda t: "Basic " + base64.b64encode(t.encode()).decode()
        self.assertEqual(f({"authorization": enc("ban:tok123")}), "tok123")               # mật khẩu là token
        self.assertEqual(f({"authorization": enc("ban:tok:co:hai:cham")}), "tok:co:hai:cham")
        self.assertEqual(f({"authorization": enc("tok123")}), "tok123")                   # chỉ có tên: coi là token
        self.assertIsNone(f({"authorization": enc("ban:")}))
        self.assertEqual(f({"authorization": "Bearer b1", "x-api-key": "k"}), "b1")
        self.assertIsNone(f({}))
        self.assertIsNone(f(None))


# ------------------------------------------------------------------ giới hạn tải
class TestLimiter(unittest.TestCase):
    def test_global_and_per_user_limits_do_not_queue(self):
        lim = mcp_auth.Limiter(max_global=2, max_per_user=1, per_minute=100)
        self.assertTrue(lim.acquire("a")[0])
        ok, why, wait = lim.acquire("a")
        self.assertFalse(ok)
        self.assertIn("dở", why)
        self.assertTrue(lim.acquire("b")[0])
        ok, why, wait = lim.acquire("c")            # đủ 2 câu toàn server
        self.assertFalse(ok)
        self.assertIn("bận", why)
        self.assertGreater(wait, 0)
        lim.release("a")
        self.assertTrue(lim.acquire("c")[0])

    def test_per_minute_window(self):
        now = [1000.0]
        lim = mcp_auth.Limiter(max_global=10, max_per_user=10, per_minute=3, clock=lambda: now[0])
        for _ in range(3):
            self.assertTrue(lim.acquire("u")[0])
            lim.release("u")
        ok, why, wait = lim.acquire("u")
        self.assertFalse(ok)
        self.assertIn("3 lệnh", why)
        now[0] += 61
        self.assertTrue(lim.acquire("u")[0])

    def test_release_never_goes_negative(self):
        lim = mcp_auth.Limiter(max_global=1, max_per_user=1)
        lim.release("x")
        self.assertTrue(lim.acquire("x")[0])
        self.assertFalse(lim.acquire("y")[0])


# ------------------------------------------------------------------ dựng văn bản
class TestToolDescription(unittest.TestCase):
    def test_description_guides_clarify_cannot_followup_and_stays_short(self):
        d = mcp_server.DESCRIPTION
        for key in ("HỎI LẠI", "[status: clarify]", "[status: cannot]", "history", "detail=full", "DỮ LIỆU"):
            self.assertIn(key, d)
        self.assertLess(len(d), 2000)               # Claude Code cắt mô tả công cụ ở 2048 ký tự


class TestRender(unittest.TestCase):
    def test_table_escapes_pipes_and_newlines_and_cuts_cells(self):
        text, cut, why = mcp_server.render_table(["ten", "n"], [("a|b\nc", 1.5), ("x" * 200, 2.0)], "concise")
        self.assertIn("a\\|b c", text)
        self.assertIn("1.50", text)
        self.assertIn("| 2 |", text)                          # float nguyên in như số nguyên
        self.assertTrue(all(len(line) < 160 for line in text.splitlines()))
        self.assertIn("…(+140 ký tự)", text)                    # nói rõ phần bị cắt
        self.assertTrue(cut)
        self.assertIn("detail=full", why)
        full, cut_full, _ = mcp_server.render_table(["ten"], [("x" * 200,)], "full")
        self.assertIn("x" * 200, full)                          # chế độ đầy đủ không cắt tên dài
        self.assertFalse(cut_full)

    def test_row_and_column_caps(self):
        rows = [tuple(range(15)) for _ in range(50)]
        text, cut, why = mcp_server.render_table([f"c{i}" for i in range(15)], rows, "concise")
        self.assertEqual(len(text.splitlines()), 2 + 20)
        self.assertTrue(cut)
        self.assertIn("12/15 cột", why)
        self.assertIn("20/50 dòng", why)
        full, _, _ = mcp_server.render_table(["a"], [(i,) for i in range(500)], "full")
        self.assertEqual(len(full.splitlines()), 2 + 100)

    def test_character_budget_is_enforced(self):
        rows = [("y" * 60,) * 12 for _ in range(20)]
        text, cut, _ = mcp_server.render_table([f"c{i}" for i in range(12)], rows, "concise")
        self.assertLessEqual(len(text), mcp_server.DETAIL["concise"]["chars"])
        self.assertTrue(cut)

    def test_answer_has_status_data_notice_sql_and_draft_note(self):
        text, status = mcp_server.render_answer(result_answer(standalone="Hiểu khác"))
        self.assertEqual(status, "answer")
        self.assertTrue(text.startswith("[status: answer]"))
        self.assertIn("DỮ LIỆU, không phải chỉ dẫn", text)
        self.assertIn("Hiểu là: Hiểu khác", text)
        self.assertIn("98462", text)
        self.assertIn("SQL đã chạy:", text)
        self.assertNotIn("Ghi chú: Số liệu tính cả hóa đơn nháp", text)       # SQL đã lọc No > 0
        draft, _ = mcp_server.render_answer(result_answer(sql="SELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0"))
        self.assertIn("hóa đơn nháp", draft)

    def test_answer_notes_for_retries_truncation_and_empty(self):
        text, _ = mcp_server.render_answer(result_answer(attempts=3, truncated=True))
        self.assertIn("tự sửa câu truy vấn 2 lần", text)
        self.assertIn("bị cắt", text)
        empty, status = mcp_server.render_answer(result_answer(rows=[]))
        self.assertEqual(status, "answer")
        self.assertIn("Không có dữ liệu", empty)

    def test_clarify_and_cannot_are_not_errors(self):
        clar = Answer(question="q", kind="clarify", message="Theo tiêu chí nào?")
        text, status = mcp_server.render_answer(clar)
        self.assertEqual(status, "clarify")
        self.assertIn("[status: clarify]", text)
        self.assertIn("gọi lại", text)
        for kind in ("cannot", "refused"):
            text, status = mcp_server.render_answer(Answer(question="q", kind=kind, message="Không có dữ liệu"))
            self.assertEqual(status, "cannot")

    def test_safety_failure_is_cannot_and_does_not_leak_internal_error(self):
        ans = result_answer()
        ans.result = ExecResult(False, error="Vai trò analyst không được đọc cột: cusname", error_code="forbidden")
        text, status = mcp_server.render_answer(ans)
        self.assertEqual(status, "cannot")
        self.assertNotIn("cusname", text.lower())

    def test_system_failures_raise_tool_failure_without_internal_details(self):
        for code in ("timeout", "db_unavailable", "sql_error", None):
            ans = result_answer()
            ans.result = ExecResult(False, error="Code: 47 DB::Exception: Unknown identifier secret_col", error_code=code)
            with self.assertRaises(mcp_server.ToolFailure) as cm:
                mcp_server.render_answer(ans)
            self.assertNotIn("secret_col", str(cm.exception))
        with self.assertRaises(mcp_server.ToolFailure):
            mcp_server.render_answer(Answer(question="q", kind="error", message="Lỗi nội bộ http://10.0.0.1"))


# ------------------------------------------------------------------ dịch vụ
class TestService(unittest.TestCase):
    def service(self, pipe, **kw):
        return mcp_server.AskService(lambda: pipe, limiter=kw.pop("limiter", mcp_auth.Limiter(2, 1, 100)), **kw)

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_input_validation(self):
        c = mcp_server.AskService.check_inputs
        for bad in ("", "   ", None, 5, "x" * 1001):
            with self.assertRaises(mcp_server.ToolFailure, msg=repr(bad)):
                c(bad, None, "concise")
        with self.assertRaises(mcp_server.ToolFailure):
            c("ok", None, "huge")

    def test_history_accepts_only_question_strings_and_never_sql(self):
        c = mcp_server.AskService.check_inputs
        with self.assertRaises(mcp_server.ToolFailure):
            c("q", [{"question": "x", "sql": "DROP TABLE a"}], "concise")
        with self.assertRaises(mcp_server.ToolFailure):
            c("q", [123], "concise")
        _, hist, _ = c("q", [f"câu {i}" for i in range(7)], "concise")
        self.assertEqual([h["question"] for h in hist], ["câu 3", "câu 4", "câu 5", "câu 6"])
        self.assertTrue(all(h["sql"] is None for h in hist))
        _, hist, _ = c("q", ["y" * 900], "concise")
        self.assertEqual(len(hist[0]["question"]), mcp_server.MAX_HISTORY_ITEM)

    def test_ask_passes_history_role_and_logs_user(self):
        pipe = FakePipe()
        text = self.run_async(self.service(pipe).ask("an", "Còn tháng 4?", ["Số hóa đơn tháng 5"], "concise"))
        self.assertIn("[status: answer]", text)
        call = pipe.calls[0]
        self.assertEqual(call["policy"], "analyst")             # vai trò cố định, không nâng quyền
        self.assertEqual(call["history"], [{"question": "Số hóa đơn tháng 5", "sql": None}])
        ev = pipe.logger.events[0]
        self.assertEqual((ev["type"], ev["user"], ev["status"]), ("mcp_call", "an", "answer"))

    def test_busy_server_rejects_immediately_with_retry_hint(self):
        pipe = FakePipe(delay=0.4)
        svc = self.service(pipe, limiter=mcp_auth.Limiter(1, 1, 100))

        async def scenario():
            first = asyncio.ensure_future(svc.ask("a", "câu 1"))
            await asyncio.sleep(0.1)
            t0 = time.perf_counter()
            with self.assertRaises(mcp_server.ToolFailure) as cm:
                await svc.ask("b", "câu 2")
            self.assertLess(time.perf_counter() - t0, 0.2)       # không xếp hàng
            self.assertIn("thử lại sau", str(cm.exception))
            return await first
        self.assertIn("[status: answer]", self.run_async(scenario()))

    def test_deadline_returns_error_and_slot_is_held_until_work_ends(self):
        pipe = FakePipe(delay=0.5)
        lim = mcp_auth.Limiter(1, 1, 100)
        svc = self.service(pipe, limiter=lim, deadline_s=0.1)

        async def scenario():
            with self.assertRaises(mcp_server.ToolFailure) as cm:
                await svc.ask("a", "câu chậm")
            self.assertIn("quá 0.1 giây", str(cm.exception))
            self.assertFalse(lim.acquire("b")[0])                # luồng cũ còn chạy: chưa nhả chỗ
            await asyncio.sleep(0.7)
            self.assertTrue(lim.acquire("b")[0])                 # xong thì nhả
        self.run_async(scenario())

    def test_retry_of_same_question_joins_running_work_and_runs_once(self):
        """WeKnora tự thử lại khi quá hạn: không chạy lại trên ClickHouse, không tính vào giới hạn."""
        pipe = FakePipe(delay=0.4)
        lim = mcp_auth.Limiter(2, 1, 100)
        svc = self.service(pipe, limiter=lim, deadline_s=0.1)

        async def scenario():
            with self.assertRaises(mcp_server.ToolFailure):
                await svc.ask("a", "câu chậm")                   # quá hạn, việc vẫn chạy
            svc.deadline_s = 2
            return await svc.ask("a", "câu chậm")                # gửi lại: nối vào việc đang chạy
        self.assertIn("[status: answer]", self.run_async(scenario()))
        self.assertEqual(len(pipe.calls), 1)

    def test_recent_result_is_reused_but_other_users_and_questions_are_not(self):
        pipe = FakePipe()
        svc = self.service(pipe)

        async def scenario():
            await svc.ask("a", "câu 1")
            await svc.ask("a", "câu 1")                          # trùng: dùng lại
            await svc.ask("b", "câu 1")                          # người khác: chạy riêng
            await svc.ask("a", "câu 1", ["trước đó"])            # lịch sử khác: chạy riêng
            await svc.ask("a", "câu 2")
        self.run_async(scenario())
        self.assertEqual(len(pipe.calls), 4)

    def test_failed_work_is_not_cached(self):
        pipe = FakePipe(answer=Answer(question="q", kind="error", message="boom"))
        svc = self.service(pipe)

        async def scenario():
            for _ in range(2):
                with self.assertRaises(mcp_server.ToolFailure):
                    await svc.ask("a", "câu")
        self.run_async(scenario())
        self.assertEqual(len(pipe.calls), 2)

    def test_slot_released_after_failure(self):
        pipe = FakePipe(answer=Answer(question="q", kind="error", message="boom"))
        lim = mcp_auth.Limiter(1, 1, 100)
        svc = self.service(pipe, limiter=lim)
        with self.assertRaises(mcp_server.ToolFailure):
            self.run_async(svc.ask("a", "câu"))
        self.assertTrue(lim.acquire("a")[0])
        self.assertEqual(pipe.logger.events[0]["status"], "error")

    def test_missing_analyst_policy_is_refused(self):
        pipe = FakePipe()
        pipe.policies = {"admin": Policy("admin")}
        with self.assertRaises(mcp_server.ToolFailure):
            self.run_async(self.service(pipe).ask("a", "câu"))


# ------------------------------------------------------------------ đường HTTP thật
class TestHTTP(TempTokens):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._old = os.environ.get("T2SQL_MCP_TOKENS_FILE")
        os.environ["T2SQL_MCP_TOKENS_FILE"] = os.path.join(cls._tmp.name, "tokens.json")
        mcp_auth._cache.update(key=None, data=None)
        cls.pipe = FakePipe()
        service = mcp_server.AskService(lambda: cls.pipe, limiter=mcp_auth.Limiter(2, 2, 1000))
        cls.port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(mcp_server.build_app(service), host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.url = f"http://127.0.0.1:{cls.port}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        if cls._old is None:
            os.environ.pop("T2SQL_MCP_TOKENS_FILE", None)
        else:
            os.environ["T2SQL_MCP_TOKENS_FILE"] = cls._old
        cls._tmp.cleanup()

    def setUp(self):         # không dùng TempTokens.setUp: giữ kho token của lớp
        mcp_auth._cache.update(key=None, data=None)

    def tearDown(self):
        pass

    def call(self, args, headers, tool="ask_data"):
        async def go():
            async with _Connection(self.url, headers, "http", 30) as s:
                return await s.call_tool(tool, args)
        return asyncio.run(go())

    def test_no_token_or_bad_token_is_401(self):
        for headers in ({}, {"Authorization": "Bearer sai"}, {"X-API-Key": "sai"}, {"Authorization": "Basic Zm9vOmJhcg=="}):          # Basic foo:bar: sai token
            with self.assertRaises(LLMError, msg=str(headers)):
                probe_tools(self.url, headers)
        r = httpx.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("www-authenticate"), "Bearer, Basic realm=\"t2sql\"")

    def test_basic_auth_with_token_as_password_works_and_wrong_password_is_401(self):
        tok = mcp_auth.create_token("basic.test")
        enc = lambda pw: "Basic " + base64.b64encode(f"basic.test:{pw}".encode()).decode()
        self.assertEqual([t["name"] for t in probe_tools(self.url, {"Authorization": enc(tok)})], ["ask_data"])
        with self.assertRaises(LLMError):
            probe_tools(self.url, {"Authorization": enc("sai")})
        mcp_auth.revoke_token("basic.test")
        with self.assertRaises(LLMError):                       # thu hồi có hiệu lực ngay cả với Basic
            probe_tools(self.url, {"Authorization": enc(tok)})

    def test_both_header_styles_work_and_tool_definition(self):
        tok = mcp_auth.create_token("http.test")
        for headers in ({"Authorization": f"Bearer {tok}"}, {"X-API-Key": tok}):
            tools = probe_tools(self.url, headers)
            self.assertEqual([t["name"] for t in tools], ["ask_data"])
        t = tools[0]
        self.assertEqual(set(t["properties"]), {"question", "history", "detail"})      # ctx không lộ ra ngoài
        self.assertEqual(t["required"], ["question"])
        hist_schema = t["properties"]["history"]
        branches = hist_schema.get("anyOf") or [hist_schema]
        arrays = [b for b in branches if b.get("type") == "array"]
        self.assertEqual([a["items"] for a in arrays], [{"type": "string"}])         # chỉ mảng chuỗi: không có kênh nhận SQL hay đối tượng

        async def raw():
            async with _Connection(self.url, {"X-API-Key": tok}, "http", 30) as s:
                return (await s.list_tools()).tools[0]
        tool = asyncio.run(raw())
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertFalse(tool.annotations.destructive_hint)
        self.assertFalse(tool.annotations.open_world_hint)
        self.assertIsNone(getattr(tool, "output_schema", None) or getattr(tool, "outputSchema", None))    # giai đoạn 1: chỉ văn bản

    def test_call_returns_text_only_and_logs_authenticated_user(self):
        tok = mcp_auth.create_token("nguoi.goi")
        res = self.call({"question": "Có bao nhiêu hóa đơn?"}, {"Authorization": f"Bearer {tok}"})
        self.assertFalse(res.is_error)
        self.assertEqual(len(res.content), 1)
        self.assertIn("[status: answer]", res.content[0].text)
        self.assertIn("98462", res.content[0].text)
        self.assertIsNone(getattr(res, "structured_content", None) or getattr(res, "structuredContent", None))
        self.assertEqual(self.pipe.logger.events[-1]["user"], "nguoi.goi")

    def test_client_cannot_spoof_identity_header(self):
        tok = mcp_auth.create_token("that")
        self.call({"question": "q"}, {"Authorization": f"Bearer {tok}", mcp_server.USER_HEADER: "admin"})
        self.assertEqual(self.pipe.logger.events[-1]["user"], "that")

    def test_revoked_token_is_rejected_immediately_while_server_keeps_running(self):
        tok = mcp_auth.create_token("se.thu.hoi")
        self.assertFalse(self.call({"question": "q"}, {"X-API-Key": tok}).is_error)
        mcp_auth.revoke_token("se.thu.hoi")
        with self.assertRaises(Exception):
            self.call({"question": "q"}, {"X-API-Key": tok})
        self.assertEqual(httpx.post(self.url, headers={"X-API-Key": tok}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code, 401)

    def test_expired_token_is_401(self):
        tok = mcp_auth.create_token("cu", days=-1)
        self.assertEqual(httpx.post(self.url, headers={"Authorization": f"Bearer {tok}"},
                                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code, 401)

    def test_failures_are_tool_errors_with_actionable_text(self):
        tok = mcp_auth.create_token("loi")
        res = self.call({"question": "   "}, {"Authorization": f"Bearer {tok}"})
        self.assertTrue(res.is_error)
        self.assertIn("Thiếu câu hỏi", res.content[0].text)
        res = self.call({"question": "q", "history": ["ok", "SELECT 1"]}, {"Authorization": f"Bearer {tok}"})
        self.assertFalse(res.is_error)      # chuỗi nào cũng chỉ là câu hỏi; SQL không có kênh riêng

    def test_unknown_host_header_is_rejected(self):
        tok = mcp_auth.create_token("host")
        r = httpx.post(self.url, headers={"Authorization": f"Bearer {tok}", "Host": "evil.example.com",
                                          "Accept": "application/json, text/event-stream"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertNotEqual(r.status_code, 200)
        self.assertIn(r.status_code, (400, 403, 421))


# ------------------------------------------------------------------ live: hddt thật, LLM giả
def _live_url():
    url = os.environ.get("T2SQL_DATABASE_URL", "")
    return url if url.startswith(("clickhouse://", "clickhouses://")) and url.rstrip("/").endswith("hddt") or "/hddt" in url else ""


@unittest.skipUnless(_live_url(), "không có T2SQL_DATABASE_URL trỏ tới hddt")
class TestLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from t2sql.llm import ScriptedLLM
        from t2sql.pipeline import TextToSQL
        cls.sqls = {"count": "SELECT count() AS so_hd FROM VATInvoice FINAL WHERE is_deleted = 0 AND ArisingDate >= '2025-05-01' AND ArisingDate < '2025-06-01'",
                    "month": "SELECT toString(toStartOfMonth(ArisingDate)) AS thang, count() AS so_hd FROM VATInvoice FINAL "
                             "WHERE is_deleted = 0 AND ArisingDate >= '2025-01-01' AND ArisingDate < '2025-04-01' GROUP BY thang ORDER BY thang",
                    "pii": "SELECT CusName FROM VATInvoice FINAL WHERE is_deleted = 0 LIMIT 3"}

        def fn(system, messages):
            q = messages[-1]["content"]
            key = "month" if "tháng trong quý" in q else ("pii" if "tên khách" in q else "count")
            return cls.sqls[key]
        cls.pipe = TextToSQL(ScriptedLLM(fn), "production")

    def ask(self, q):
        svc = mcp_server.AskService(lambda: self.pipe, limiter=mcp_auth.Limiter(2, 2, 1000))
        return asyncio.run(svc.ask("live", q))

    def test_real_count_through_the_whole_stack(self):
        text = self.ask("Có bao nhiêu hóa đơn trong tháng 5/2025?")
        self.assertIn("[status: answer]", text)
        self.assertRegex(text, r"\|\s*\d{4,}\s*\|")
        self.assertIn("hóa đơn nháp", text)                     # SQL không lọc nháp nên phải có ghi chú

    def test_dates_are_not_masked_for_analyst(self):
        text = self.ask("Số hóa đơn theo từng tháng trong quý 1 năm 2025")
        self.assertIn("2025-01-01", text)
        self.assertNotIn("202*****", text)

    def test_personal_column_is_refused_for_analyst_role(self):
        try:
            text = self.ask("Cho tôi tên khách hàng")
        except mcp_server.ToolFailure:
            self.fail("cột cá nhân phải là cannot, không phải lỗi hệ thống")
        self.assertIn("[status: cannot]", text)
        self.assertNotIn("CusName", text)


if __name__ == "__main__":
    unittest.main()
