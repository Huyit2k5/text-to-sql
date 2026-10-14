"""Test LLM qua MCP: lớp McpLLM, hồ sơ, link mời, kiểm tra địa chỉ, trang cấu hình. Dùng MCP server giả chạy cục bộ, không cần mạng.

Cần gói `mcp`; thiếu thì bỏ qua cả file.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import mcp  # noqa: F401
except ImportError:
    raise unittest.SkipTest("chưa cài gói mcp")

from t2sql import llm_profiles as lp
from t2sql.llm import LLMError, default_llm
from t2sql.mcp_llm import McpLLM, guess_mapping, probe_tools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "tok-test"
_procs = {}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(*extra):
    port = _free_port()
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "fake_mcp_llm_server.py"), "--port", str(port),
                          "--token", TOKEN, *extra], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p, f"http://127.0.0.1:{port}/mcp"
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("MCP server giả không khởi động được")


def setUpModule():
    _procs["split"] = _start()
    _procs["single"] = _start("--single-arg")


def tearDownModule():
    for p, _ in _procs.values():
        p.kill()


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def profile(kind="split", **kw):
    url = _procs[kind][1]
    base = {"name": "t", "url": url, "tool": "generate" if kind == "split" else "ask",
            "prompt_arg": "prompt" if kind == "split" else "question",
            "system_arg": "system" if kind == "split" else None,
            "auth_header": "Authorization", "auth_value": f"Bearer {TOKEN}", "timeout_s": 30, "retries": 0}
    base.update(kw)
    return base


class TestMcpLLM(unittest.TestCase):
    def test_probe_and_guess(self):
        tools = probe_tools(_procs["split"][1], AUTH)
        self.assertEqual([t["name"] for t in tools], ["generate"])
        self.assertEqual(guess_mapping(tools[0]), {"prompt_arg": "prompt", "system_arg": "system", "messages_arg": None})
        single = probe_tools(_procs["single"][1], AUTH)
        self.assertEqual(guess_mapping(single[0])["prompt_arg"], "question")
        self.assertIsNone(guess_mapping(single[0])["system_arg"])

    def test_complete_split_system(self):
        llm = McpLLM(profile())
        text = llm.complete("Bạn là trợ lý SQL.", [{"role": "user", "content": "Có bao nhiêu hóa đơn?"}])
        self.assertIn("SELECT count()", text)
        self.assertEqual(llm.usage.calls, 1)

    def test_complete_merges_system_when_tool_has_none(self):
        llm = McpLLM(profile("single"))
        text = llm.complete("QUY TẮC: dùng FINAL.", [{"role": "user", "content": "xin chào"}])
        self.assertIn("QUY TẮC", text)          # server giả trả lại phần đầu prompt: system đã được gộp vào
        self.assertIn("[system=0 ký tự]", text)

    def test_ping(self):
        reply, secs = McpLLM(profile()).ping()
        self.assertEqual(reply, "OK")
        self.assertGreaterEqual(secs, 0)

    def test_wrong_token_raises_llmerror(self):
        with self.assertRaises(LLMError) as cm:
            McpLLM(profile(auth_value="Bearer sai")).ping()
        self.assertNotIn("sai", str(cm.exception))   # không lộ token trong thông báo lỗi

    def test_unreachable_server(self):
        with self.assertRaises(LLMError):
            McpLLM(profile(url=f"http://127.0.0.1:{_free_port()}/mcp")).ping()

    def test_unknown_tool(self):
        with self.assertRaises(LLMError):
            McpLLM(profile(tool="khong_co")).ping()

    def test_build_args_multi_turn_and_messages_arg(self):
        llm = McpLLM(profile("single"))
        msgs = [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "SQL1"},
                {"role": "user", "content": "lỗi: x"}]
        body = llm.build_args("SYS", msgs)["question"]
        self.assertIn("[Người dùng]\nQ1", body)
        self.assertIn("[Trợ lý]\nSQL1", body)
        self.assertTrue(body.startswith("SYS"))
        with_msgs = McpLLM(profile(messages_arg="messages", system_arg=None)).build_args("SYS", msgs)
        self.assertEqual(with_msgs["messages"][0], {"role": "system", "content": "SYS"})

    def test_response_key_and_think_stripped(self):
        llm = McpLLM(profile(response_key="out.text"))
        self.assertEqual(llm._extract('{"out": {"text": "<think>x</think> SELECT 1"}}'), "SELECT 1")
        self.assertEqual(llm._extract("không phải json"), "không phải json")

    def test_missing_fields(self):
        with self.assertRaises(LLMError):
            McpLLM({"url": "http://x", "tool": "t"})


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["T2SQL_PROFILES_FILE"] = os.path.join(self.tmp.name, "p.json")
        self.addCleanup(lambda: (os.environ.pop("T2SQL_PROFILES_FILE", None), self.tmp.cleanup()))

    def test_save_list_delete_hides_secrets(self):
        lp.save_profile("leader", {"url": "http://h/mcp", "tool": "gen", "prompt_arg": "p", "auth_value": "Bearer BI-MAT"})
        listed = lp.list_profiles()
        self.assertEqual([p["name"] for p in listed], ["leader"])
        self.assertNotIn("BI-MAT", str(listed))
        self.assertEqual(lp.get_profile("leader")["auth_value"], "Bearer BI-MAT")
        self.assertTrue(lp.delete_profile("leader"))
        self.assertIsNone(lp.get_profile("leader"))

    def test_bad_name(self):
        with self.assertRaises(ValueError):
            lp.save_profile("../x", {})

    def test_invite_lifecycle(self):
        tok = lp.create_invite(hours=1)
        self.assertTrue(lp.check_invite(tok))
        self.assertFalse(lp.check_invite(tok + "x"))
        self.assertFalse(lp.check_invite(""))
        with open(os.environ["T2SQL_PROFILES_FILE"], encoding="utf-8") as f:
            self.assertNotIn(tok, f.read())   # chỉ lưu bản băm
        lp.consume_invite(tok)
        self.assertFalse(lp.check_invite(tok))

    def test_invite_expires(self):
        tok = lp.create_invite(hours=0.0000001)
        time.sleep(0.05)
        self.assertFalse(lp.check_invite(tok))

    def test_default_llm_uses_profile(self):
        lp.save_profile("leader", profile())
        llm = default_llm("leader")
        self.assertIsInstance(llm, McpLLM)
        self.assertEqual(llm.model, "mcp:leader")
        with self.assertRaises(LLMError):
            default_llm("khong-co")


class TestValidateUrl(unittest.TestCase):
    def setUp(self):
        for k in ("T2SQL_MCP_ALLOW_LOCAL", "T2SQL_MCP_ALLOWED_HOSTS"):
            os.environ.pop(k, None)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("T2SQL_MCP_ALLOW_LOCAL", "T2SQL_MCP_ALLOWED_HOSTS")])

    def test_rejects(self):
        for bad in ("", "ftp://x/mcp", "file:///etc/passwd", "http://169.254.169.254/latest", "http://127.0.0.1:9/mcp",
                    "http://localhost/mcp"):
            self.assertIsNotNone(lp.validate_url(bad), bad)

    def test_allow_local_flag_and_private(self):
        os.environ["T2SQL_MCP_ALLOW_LOCAL"] = "1"
        self.assertIsNone(lp.validate_url("http://127.0.0.1:9/mcp"))
        self.assertIsNone(lp.validate_url("http://10.1.2.3:8000/mcp"))
        self.assertIsNotNone(lp.validate_url("http://169.254.169.254/x"))   # link-local luôn bị chặn

    def test_public_http_rejected(self):
        self.assertIsNotNone(lp.validate_url("http://8.8.8.8/mcp"))
        self.assertIsNone(lp.validate_url("https://8.8.8.8/mcp"))

    def test_allowed_hosts(self):
        os.environ["T2SQL_MCP_ALLOWED_HOSTS"] = "8.8.8.8"
        self.assertIsNone(lp.validate_url("https://8.8.8.8/mcp"))
        self.assertIsNotNone(lp.validate_url("https://1.1.1.1/mcp"))


class TestInvitePage(unittest.TestCase):
    def test_invalid_invite_shows_error_and_no_chat(self):
        from streamlit.testing.v1 import AppTest
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["T2SQL_PROFILES_FILE"] = os.path.join(tmp.name, "p.json")
        self.addCleanup(lambda: os.environ.pop("T2SQL_PROFILES_FILE", None))
        at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30)
        at.query_params["invite"] = "khong-hop-le"
        at.run()
        self.assertEqual(len(at.error), 1)
        self.assertIn("không hợp lệ", at.error[0].value)
        self.assertEqual(len(at.chat_input), 0)   # không có ô hỏi đáp
        self.assertEqual(len(at.sidebar.selectbox), 0)   # và không có cấu hình database

    def test_valid_invite_shows_connection_form_only(self):
        from streamlit.testing.v1 import AppTest
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["T2SQL_PROFILES_FILE"] = os.path.join(tmp.name, "p.json")
        self.addCleanup(lambda: os.environ.pop("T2SQL_PROFILES_FILE", None))
        tok = lp.create_invite(hours=1)
        at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30)
        at.query_params["invite"] = tok
        at.run()
        self.assertEqual(len(at.error), 0)
        self.assertEqual(len(at.chat_input), 0)
        self.assertEqual(at.title[0].value, "Kết nối model của bạn")
        self.assertEqual(len(at.text_input), 3)   # địa chỉ, tên header, giá trị header

    def test_full_flow_probe_test_save(self):
        """Người được mời: dò công cụ -> gửi thử -> lưu; link mời hết hiệu lực sau khi lưu."""
        from streamlit.testing.v1 import AppTest
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ["T2SQL_PROFILES_FILE"] = os.path.join(tmp.name, "p.json")
        os.environ["T2SQL_MCP_ALLOW_LOCAL"] = "1"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("T2SQL_PROFILES_FILE", "T2SQL_MCP_ALLOW_LOCAL")])
        tok = lp.create_invite(hours=1)
        at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
        at.query_params["invite"] = tok
        at.run()
        at.text_input(key="cfg_url").set_value(_procs["split"][1])
        at.text_input(key="cfg_hval").set_value(f"Bearer {TOKEN}")
        next(b for b in at.button if b.label == "Dò công cụ").click()
        at.run()
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])
        self.assertEqual(at.selectbox(key="cfg_tool").value, "generate")
        self.assertEqual(at.selectbox(key="cfg_system_generate").value, "system")   # tự đoán đúng tham số
        next(b for b in at.button if b.label == "Gửi thử một câu").click()
        at.run()
        self.assertEqual(len(at.error), 0, [e.value for e in at.error])
        next(b for b in at.button if b.label == "Lưu cấu hình").click()
        at.run()
        saved = lp.get_profile("leader-llm")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["tool"], "generate")
        self.assertEqual(saved["auth_value"], f"Bearer {TOKEN}")
        self.assertFalse(lp.check_invite(tok))
        self.assertNotIn(TOKEN, " ".join(str(e.value) for e in at.markdown))   # token không hiện lại trên trang


if __name__ == "__main__":
    unittest.main()
