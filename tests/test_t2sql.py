"""Unit test (không gọi API, không cần database).  Chạy:  python -m unittest -v
"""
import json
import os
import tempfile
import unittest


def _dotenv(key):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                if line.strip().startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    return ""



from t2sql import datasets
from t2sql.evaluation import categorize, results_match
from t2sql.llm import ScriptedLLM
from t2sql.logstore import QueryLogger
from t2sql.pipeline import CONFIGS, Config, TextToSQL
from t2sql.retrieval import FewShotRetriever, SchemaLinker, tables_in_sql
from t2sql.safety import POLICIES, SafetyError, static_check
from t2sql.schema import Schema
from t2sql.sql_utils import extract_sql, parse_response, split_statements
from t2sql.viz import choose_view

HDDT = datasets.for_database("hddt")
POL = HDDT.policies      # admin / analyst của bộ hddt


class TestExtractSQL(unittest.TestCase):
    def test_fenced_with_prose(self):
        raw = "Đây là câu truy vấn:\n```sql\nSELECT COUNT(*) FROM orders;\n```\nCâu này đếm đơn."
        self.assertEqual(extract_sql(raw), "SELECT COUNT(*) FROM orders")

    def test_prose_before_without_fence(self):
        self.assertEqual(extract_sql("Câu SQL là: SELECT 1"), "SELECT 1")

    def test_trailing_explanation_after_blank_line(self):
        raw = "SELECT name\nFROM products\n\nGiải thích: lấy tên sản phẩm."
        self.assertEqual(extract_sql(raw), "SELECT name\nFROM products")

    def test_keeps_second_statement_for_safety_layer(self):
        self.assertIn("DROP", extract_sql("SELECT 1; DROP TABLE sellers"))

    def test_cte_with_blank_lines_kept(self):
        raw = "WITH t AS (\n  SELECT 1 AS x\n)\n\nSELECT x FROM t"
        self.assertEqual(extract_sql(raw), raw)

    def test_markers(self):
        self.assertEqual(parse_response("CANNOT_ANSWER: không có dữ liệu thời tiết"),
                         ("cannot", "không có dữ liệu thời tiết"))
        self.assertEqual(parse_response("CLARIFY: theo doanh thu hay số lượng?")[0], "clarify")
        self.assertEqual(parse_response("```sql\nSELECT 1\n```")[0], "sql")

    def test_split_ignores_semicolon_in_string(self):
        self.assertEqual(len(split_statements("SELECT 'a;b' FROM t")), 1)
        self.assertEqual(len(split_statements("SELECT 1; SELECT 2;")), 2)




class TestEvaluation(unittest.TestCase):
    def test_lenient_mode_treats_month_spellings_as_the_same_answer(self):
        gold = [("2025-01-01", 5), ("2025-02-01", 6)]
        pred = [("2025-01", 5), ("2025-02", 6)]
        self.assertFalse(results_match(pred, gold))                       # chấm chính thức vẫn khắt khe
        self.assertTrue(results_match(pred, gold, allow_extra_columns=True))
        self.assertTrue(results_match([(3, 10)], [("2025-03-01", 10)], allow_extra_columns=True))
        self.assertTrue(results_match([("2025-03-01T00:00:00", 1)], [("2025-03-01", 1)], allow_extra_columns=True))
        self.assertFalse(results_match([(4, 10)], [("2025-03-01", 10)], allow_extra_columns=True))
        self.assertFalse(results_match([("2025-03-15", 1)], [("2025-03", 1)], allow_extra_columns=True))
        self.assertFalse(results_match([("2025-04", 5), ("2025-02", 6)], gold, allow_extra_columns=True))

    def test_order_and_column_permutation(self):
        gold = [("a", 1), ("b", 2)]
        self.assertTrue(results_match([(2, "b"), (1, "a")], gold))
        self.assertFalse(results_match([("b", 2), ("a", 1)], gold, ordered=True))
        self.assertTrue(results_match([("a", 1), ("b", 2)], gold, ordered=True))

    def test_float_tolerance(self):
        self.assertTrue(results_match([(32287690.05,)], [(32287690.049140047,)]))
        self.assertTrue(results_match([(5.0,)], [(5,)]))
        self.assertFalse(results_match([(0.116,)], [(11.6,)]))

    def test_extra_columns_only_lenient(self):
        gold = [("Dell XPS 13",)]
        pred = [(17, "Dell XPS 13")]
        self.assertFalse(results_match(pred, gold))
        self.assertTrue(results_match(pred, gold, allow_extra_columns=True))

    def test_categorize_business_logic(self):
        item = {"sql": "SELECT SUM(oi.quantity) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 4"}
        rec = {"kind": "result", "ok": True,
               "sql": "SELECT SUM(oi.quantity) FROM order_items oi JOIN orders o ON o.order_id = oi.order_id"}
        self.assertEqual(categorize(item, rec), "business_logic")






def scripted(responses):
    """LLM giả trả lần lượt các phản hồi trong danh sách."""
    it = iter(responses)
    return ScriptedLLM(lambda system, messages: next(it))




class TestRetrievalAndViz(unittest.TestCase):
    def test_fewshot_similarity(self):
        r = FewShotRetriever([{"question": "Doanh thu năm 2025 là bao nhiêu?", "sql": "A"},
                              {"question": "Có bao nhiêu khách hàng sỉ?", "sql": "B"}], k=1)
        self.assertEqual(r.top("Doanh thu năm 2024 là bao nhiêu?")[0]["sql"], "A")

    def test_choose_view(self):
        self.assertEqual(choose_view(["n"], [(5,)])["kind"], "metric")
        self.assertEqual(choose_view(["thang", "dt"], [("2025-01", 1.0), ("2025-02", 2.0)])["kind"], "line")
        self.assertEqual(choose_view(["cat", "dt"], [("A", 1.0), ("B", 2.0)])["kind"], "bar")
        self.assertEqual(choose_view(["a", "b"], [("x", "y"), ("z", "w")])["kind"], "table")
        self.assertEqual(choose_view(["a"], [])["kind"], "empty")


class TestToday(unittest.TestCase):
    """Ngày 'hôm nay' trong prompt: cố định cho đánh giá, ngày thật cho máy chủ MCP."""

    def setUp(self):
        self._old = os.environ.pop("T2SQL_TODAY", None)

    def tearDown(self):
        os.environ.pop("T2SQL_TODAY", None)
        if self._old is not None:
            os.environ["T2SQL_TODAY"] = self._old

    def test_default_is_fixed_for_reproducible_evaluation(self):
        from t2sql import TODAY, today
        self.assertEqual(today(), TODAY)
        os.environ["T2SQL_TODAY"] = ""
        self.assertEqual(today(), TODAY)                # biến rỗng (env_file của Docker) vẫn là ngày cố định

    def test_real_and_pinned(self):
        import datetime
        from t2sql import today
        os.environ["T2SQL_TODAY"] = "real"
        self.assertEqual(today(), datetime.date.today().isoformat())
        os.environ["T2SQL_TODAY"] = "2026-01-15"
        self.assertEqual(today(), "2026-01-15")

    def test_prompts_use_current_value_everywhere(self):
        from t2sql import prompts
        os.environ["T2SQL_TODAY"] = "2026-10-15"
        for text in (prompts.sql_system("schema", True), prompts.classify_system("schema")):
            self.assertIn("2026-10-15", text)
            self.assertNotIn("2025-06-30", text)
            self.assertNotIn("@TODAY@", text)
        del os.environ["T2SQL_TODAY"]
        self.assertIn("2025-06-30", prompts.sql_system("schema", True))


class TestConfigEnv(unittest.TestCase):
    ENV_KEYS = ["T2SQL_TEST_A", "T2SQL_TEST_B", "T2SQL_TEST_C", "T2SQL_TEST_EMPTY",
                "T2SQL_MODEL", "T2SQL_EFFORT", "T2SQL_FALLBACKS", "T2SQL_MAX_TOKENS", "ANTHROPIC_API_KEY"]

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in self.ENV_KEYS}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_load_dotenv(self):
        from t2sql import load_dotenv
        os.environ["T2SQL_TEST_C"] = "from-shell"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write('# comment\nT2SQL_TEST_A="quoted value"\nexport T2SQL_TEST_B=plain  # note\n'
                        "T2SQL_TEST_C=from-file\nT2SQL_TEST_EMPTY=\n")
            load_dotenv(path)
        self.assertEqual(os.environ["T2SQL_TEST_A"], "quoted value")
        self.assertEqual(os.environ["T2SQL_TEST_B"], "plain")
        self.assertEqual(os.environ["T2SQL_TEST_C"], "from-shell")  # không ghi đè biến có sẵn
        self.assertNotIn("T2SQL_TEST_EMPTY", os.environ)            # giá trị rỗng = dùng mặc định

    def _llm(self, model, effort="medium", fallbacks="1", cap=""):
        from t2sql.llm import ClaudeLLM
        os.environ.update(T2SQL_MODEL=model, T2SQL_EFFORT=effort, T2SQL_FALLBACKS=fallbacks,
                          T2SQL_MAX_TOKENS=cap, ANTHROPIC_API_KEY="test-key")
        return ClaudeLLM()

    def test_params_follow_model(self):
        k = self._llm("claude-opus-5-5")._kwargs("s", [], 16000)
        self.assertEqual(k["output_config"], {"effort": "medium"})
        self.assertEqual(k["fallbacks"], "default")

        k = self._llm("claude-haiku-4-5")._kwargs("s", [], 16000)
        self.assertNotIn("output_config", k)   # Haiku 4.5 không nhận effort
        self.assertNotIn("fallbacks", k)       # fallback chỉ có trên model mới

        k = self._llm("claude-sonnet-4-6", effort="xhigh")._kwargs("s", [], 16000)
        self.assertEqual(k["output_config"], {"effort": "high"})

        k = self._llm("claude-sonnet-5-5", effort="", fallbacks="0", cap="4000")._kwargs("s", [], 16000)
        self.assertNotIn("output_config", k)
        self.assertNotIn("fallbacks", k)
        self.assertEqual(k["max_tokens"], 4000)


class TestOpenAICompat(unittest.TestCase):
    """Provider cho model tự host, chạy với một server giả định dạng OpenAI."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        cls.requests = []

        answer = "<think>Cần đếm doanh nghiệp.</think>\n```sql\nSELECT COUNT(*) FROM sellers\n```"

        class H(BaseHTTPRequestHandler):
            def _send(self, code, data, ctype="application/json"):
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                cls.requests.append((self.path, self.headers.get("Authorization"), body))
                if body["max_tokens"] > cls.context_limit:   # giả lập vLLM: prompt + max_tokens vượt context
                    return self._send(400, json.dumps({"error": {"message":
                                      "This model's maximum context length is 4096 tokens"}}).encode())
                if not body.get("stream"):
                    out = {"choices": [{"message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 11, "completion_tokens": 7}}
                    return self._send(200, json.dumps(out).encode())
                # SSE như vLLM có reasoning parser: suy nghĩ nằm ở reasoning_content, câu trả lời ở content
                events = [{"choices": [{"delta": {"reasoning_content": w}}]} for w in ["Cần ", "đếm ", "khách."]]
                events += [{"choices": [{"delta": {"content": answer[i:i + 10]}}]} for i in range(0, len(answer), 10)]
                events += [{"choices": [{"delta": {}, "finish_reason": "stop"}]},
                           {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 20}}]
                data = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
                self._send(200, data.encode(), "text/event-stream")

            def log_message(self, *a):
                pass

        cls.context_limit = 100_000
        cls.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()


    def test_progress_callback_sees_thinking_then_answer(self):
        from t2sql.llm import OpenAICompatLLM
        llm = OpenAICompatLLM(model="m", base_url=self.url)
        phases = []
        llm.set_progress(lambda phase, n, secs: phases.append(phase))
        self.assertIn("SELECT COUNT(*)", llm.complete("s", [{"role": "user", "content": "q"}]))
        self.assertEqual(phases[:3], ["thinking"] * 3)
        self.assertEqual(phases[-1], "answer")

    def test_extra_body_is_merged(self):
        from t2sql.llm import OpenAICompatLLM
        os.environ["T2SQL_EXTRA_BODY"] = '{"chat_template_kwargs": {"enable_thinking": false}}'
        try:
            llm = OpenAICompatLLM(model="m", base_url=self.url)
        finally:
            del os.environ["T2SQL_EXTRA_BODY"]
        llm.complete("s", [{"role": "user", "content": "q"}])
        self.assertEqual(self.requests[-1][2]["chat_template_kwargs"], {"enable_thinking": False})

    def test_reasoning_switch(self):
        from t2sql.llm import OpenAICompatLLM
        for value, expected in [("off", "none"), ("high", "high"), ("", None)]:
            os.environ["T2SQL_REASONING"] = value
            try:
                llm = OpenAICompatLLM(model="m", base_url=self.url)
            finally:
                del os.environ["T2SQL_REASONING"]
            llm.complete("s", [{"role": "user", "content": "q"}])
            self.assertEqual(self.requests[-1][2].get("reasoning_effort"), expected)

    def test_non_stream_mode(self):
        from t2sql.llm import OpenAICompatLLM
        llm = OpenAICompatLLM(model="m", base_url=self.url)
        llm.stream = False
        self.assertEqual(parse_response(llm.complete("s", [{"role": "user", "content": "q"}]))[1],
                         "SELECT COUNT(*) FROM sellers")
        self.assertFalse(self.requests[-1][2]["stream"])

    def test_context_length_backoff(self):
        from t2sql.llm import OpenAICompatLLM
        type(self).context_limit = 2048
        try:
            llm = OpenAICompatLLM(model="m", base_url=self.url)
            llm.max_tokens_cap = 8192
            llm.complete("s", [{"role": "user", "content": "q"}])
            self.assertEqual([r[2]["max_tokens"] for r in self.requests[-3:]], [8192, 4096, 2048])
            self.assertEqual(llm.max_tokens_cap, 2048)   # lần sau dùng luôn mức đã giảm
        finally:
            type(self).context_limit = 100_000

    def test_provider_selection(self):
        from t2sql.llm import ClaudeLLM, OpenAICompatLLM, default_llm
        saved = {k: os.environ.get(k) for k in ("T2SQL_PROVIDER", "T2SQL_MODEL", "ANTHROPIC_API_KEY")}
        try:
            os.environ.update(T2SQL_PROVIDER="", T2SQL_MODEL="SDS-AI/softdream")
            self.assertIsInstance(default_llm(), OpenAICompatLLM)
            os.environ.update(T2SQL_MODEL="claude-sonnet-5-5", ANTHROPIC_API_KEY="x")
            self.assertIsInstance(default_llm(), ClaudeLLM)
            os.environ.update(T2SQL_PROVIDER="openai")
            self.assertIsInstance(default_llm(), OpenAICompatLLM)
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_think_only_prefix_is_stripped(self):
        self.assertEqual(parse_response("lý do...</think>SELECT 1"), ("sql", "SELECT 1"))


class TestShapeChecks(unittest.TestCase):
    def rules(self, q, cols, rows):
        from t2sql.checks import check_result
        return [i.rule for i in check_result(q, cols, rows)]

    def test_r1_scalar_question(self):
        self.assertEqual(self.rules("Có bao nhiêu khách hàng đã mua cả điện thoại lẫn laptop?", ["n"], [(1,), (2,)]), ["R1"])
        self.assertEqual(self.rules("Có bao nhiêu khách hàng?", ["n"], [(200,)]), [])
        self.assertEqual(self.rules("Mỗi thành phố có bao nhiêu khách hàng?", ["city", "n"], [("A", 1), ("B", 2)]), [])

    def test_r2_top_per_group(self):
        q = "Trong mỗi danh mục, sản phẩm nào có doanh thu cao nhất?"
        bad = [("Laptop", "A", 5.0), ("Laptop", "B", 4.0), ("Phone", "C", 3.0)]
        good = [("Laptop", "A", 5.0), ("Phone", "C", 3.0)]
        self.assertEqual(self.rules(q, ["danh_muc", "ten", "dt"], bad), ["R2"])
        self.assertEqual(self.rules(q, ["danh_muc", "ten", "dt"], good), [])

    def test_r3_grouping_multiplied(self):
        q = "Doanh thu theo từng thành phố."
        rows = [("HN", 1.0), ("HN", 2.0), ("HN", 3.0), ("HCM", 4.0)]
        self.assertEqual(self.rules(q, ["city", "dt"], rows), ["R3"])
        # vài tên trùng lẻ tẻ (hai khách cùng tên) không bị báo
        names = [("An", 1.0), ("Bình", 2.0), ("An", 3.0), ("Chi", 4.0), ("Dũng", 5.0)]
        self.assertEqual(self.rules("Mỗi khách hàng VIP đã chi tiêu bao nhiêu?", ["name", "x"], names), [])

    def test_r4_top_n(self):
        self.assertEqual(self.rules("Top 3 khách hàng chi tiêu nhiều nhất", ["n", "x"],
                                    [("a", 3.0), ("b", 2.0), ("c", 1.0), ("d", 0.5)]), ["R4"])
        self.assertEqual(self.rules("Top 3 khách hàng chi tiêu nhiều nhất", ["n", "x"], [("a", 3.0), ("b", 2.0)]), [])

    def test_r5_single_superlative_allows_ties(self):
        q = "Khách hàng nào đặt nhiều đơn hàng nhất?"
        self.assertEqual(self.rules(q, ["name", "n"], [("a", 18), ("b", 17)]), ["R5"])
        self.assertEqual(self.rules(q, ["name", "n"], [("a", 18), ("b", 18)]), [])

    def test_r6_percent(self):
        self.assertEqual(self.rules("Tỉ lệ phần trăm đơn bị hủy là bao nhiêu?", ["x"], [(0.116,)]), ["R6"])
        self.assertEqual(self.rules("Tỉ lệ phần trăm đơn bị hủy là bao nhiêu?", ["x"], [(11.6,)]), [])
        self.assertEqual(self.rules("Doanh thu tháng 6 tăng hay giảm bao nhiêu phần trăm?", ["x"], [(-22.4,)]), [])
        self.assertEqual(self.rules("Mỗi danh mục chiếm bao nhiêu phần trăm tổng doanh thu?", ["c", "p"],
                                    [("a", 30.0), ("b", 30.0)]), ["R6"])
        self.assertEqual(self.rules("Mỗi danh mục chiếm bao nhiêu phần trăm tổng doanh thu?", ["c", "p"],
                                    [("a", 60.0), ("b", 40.0)]), [])

    def test_percent_sign_after_a_number_is_a_filter_value_not_a_ratio(self):
        q = "Tổng tiền thuế trên các dòng hàng thuế suất 5% của hóa đơn hợp lệ năm ngoái là bao nhiêu?"
        self.assertEqual(self.rules(q, ["thue"], [(2766607651601.0,)]), [])
        self.assertEqual(self.rules("Doanh thu tăng bao nhiêu %?", ["x"], [(0.4,)]), ["R6"])     # hỏi tỉ lệ: vẫn kiểm tra

    def test_r7_all_null(self):
        self.assertEqual(self.rules("Doanh thu năm 2030?", ["x"], [(None,)]), ["R7"])



H06_Q = "Trong mỗi kênh bán, gói dịch vụ nào có doanh thu bán cao nhất? Cho biết kênh, tên gói và doanh thu."
H06_BAD = ("SELECT s.channel, p.name, sum(s.amount_vnd) AS dt FROM subscriptions AS s JOIN service_plans AS p ON p.plan_id = s.plan_id "
           "WHERE s.payment_status = 'da_thanh_toan' GROUP BY s.channel, p.name ORDER BY s.channel, dt DESC")
H06_GOOD = H06_BAD + " LIMIT 1 BY s.channel"








class TestHistoryKnowledge(unittest.TestCase):
    """Khai thác quy ước từ lịch sử truy vấn (t2sql/history.py)."""

    COLS = {"invoices": {"invoice_id", "seller_id", "status", "issued_at", "total_before_tax", "total_discount",
                         "exchange_rate", "channel"},
            "sellers": {"seller_id", "name", "tax_code"},
            "tax_messages": {"message_id", "invoice_id", "sent_at", "result", "message_type"}}

    def history(self):
        good = [
            "-- doanh thu hợp lệ theo tháng\nSELECT toStartOfMonth(issued_at) AS thang, sum((total_before_tax - total_discount) * exchange_rate) AS doanh_thu "
            f"FROM invoices FINAL WHERE status IN ('da_gui_cqt', 'cqt_cap_ma') AND toYear(issued_at) = {2020 + i % 5} GROUP BY thang"
            for i in range(20)]
        good += [f"SELECT s.name, sum((i.total_before_tax - i.total_discount) * i.exchange_rate) AS doanh_thu FROM invoices AS i FINAL "
                 f"JOIN sellers AS s ON s.seller_id = i.seller_id WHERE i.status IN ('cqt_cap_ma', 'da_gui_cqt') AND i.channel = 'c{i}' GROUP BY s.name"
                 for i in range(10)]
        good += [f"SELECT toHour(toTimeZone(sent_at, 'Asia/Ho_Chi_Minh')) AS gio, count() FROM tax_messages WHERE message_type = '200' AND result = 'r{i}' GROUP BY gio"
                 for i in range(12)]
        sloppy = ["SELECT count() FROM invoices WHERE status != 'da_huy'",                                   # quên FINAL
                  "SELECT toHour(sent_at) AS gio, count() FROM tax_messages GROUP BY gio",                  # quên đổi múi giờ
                  "SELECT sum(total_before_tax - total_discount) AS doanh_thu FROM invoices FINAL"]         # quên tỷ giá
        return good + sloppy

    def test_mines_majority_conventions_and_ignores_noise(self):
        from t2sql.history import HistoryKnowledge
        hk = HistoryKnowledge(self.history(), self.COLS, min_n=8)
        self.assertIn("invoices", hk.final_tables)
        self.assertNotIn("sellers", hk.final_tables)
        self.assertEqual(hk.final_support["invoices"], (31, 32))      # 32 câu đọc invoices, 1 câu quên FINAL
        self.assertIn(("tax_messages", "sent_at"), hk.tz_cols)
        (top, n) = hk.pred_top[("invoices", "status")]
        self.assertEqual(top[0][0], "status IN ('cqt_cap_ma', 'da_gui_cqt')")
        alias, tabs, expr, c, total = hk.formulas[0]
        self.assertEqual((alias, expr), ("doanh_thu", "sum((total_before_tax - total_discount) * exchange_rate)"))
        self.assertIn("invoices.seller_id = sellers.seller_id", [j for j, _ in hk.joins])

    def test_statements_only_for_tables_in_prompt(self):
        from t2sql.history import HistoryKnowledge
        hk = HistoryKnowledge(self.history(), self.COLS, min_n=8)
        text = "\n".join(hk.statements({"tax_messages"}))
        self.assertIn("toTimeZone(sent_at", text)
        self.assertNotIn("FINAL", text)
        self.assertIn("FROM invoices FINAL", "\n".join(hk.statements({"invoices", "sellers"})))

    def test_snippets_prefer_conforming_queries_with_matching_words(self):
        from t2sql.history import HistoryKnowledge
        hk = HistoryKnowledge(self.history(), self.COLS, min_n=8)
        snips = hk.snippets("Doanh thu hợp lệ theo tháng", {"invoices", "sellers"})
        self.assertTrue(snips)
        self.assertTrue(all("FINAL" in s for s in snips))            # câu quên FINAL không được làm ví dụ
        self.assertEqual(hk.snippets("Doanh thu", {"invoices"}, exclude_columns={"total_discount"}), [])

    def test_prompt_contains_history_and_role_columns_are_excluded(self):
        import tempfile
        from t2sql.datasets import Dataset
        from t2sql.history import HistoryKnowledge
        hk = HistoryKnowledge(self.history(), self.COLS, min_n=8)
        text = hk.render({"invoices", "sellers"}, "Doanh thu hợp lệ theo tháng")
        self.assertIn("TRUY VẤN LỊCH SỬ", text)
        self.assertIn("doanh_thu", text)
        self.assertNotIn("nhap", text)




class TestClickHouseOffline(unittest.TestCase):
    """Phần không cần server: kiểm tra AST, đọc lỗi."""

    def test_schema_is_cached_on_disk_and_invalidated_when_docs_change(self):
        from unittest import mock
        from t2sql.db.clickhouse import ClickHouseBackend
        from t2sql.schema import Column, Schema, Table
        def fake():
            return Schema({"VATInvoice": Table("VATInvoice", [Column("Amount", "Decimal(21, 6)", False, None, "Tiền", [1, "a"])],
                                               "Hóa đơn", 5, "hóa đơn")}, ["rule"], {"c": ["VATInvoice"]})
        with tempfile.TemporaryDirectory() as tmp:
            docs = os.path.join(tmp, "docs.json")
            with open(docs, "w", encoding="utf-8") as f:
                f.write('{"a": 1}')
            be = ClickHouseBackend("clickhouse://u:p@ch.local:8123/hddt?single_user=1")
            sig = ["v1"]
            sig_patch = mock.patch.object(ClickHouseBackend, "_schema_signature", side_effect=lambda: sig[0])
            sig_patch.start()
            self.addCleanup(sig_patch.stop)
            with mock.patch.dict(os.environ, {"T2SQL_CACHE_DIR": os.path.join(tmp, "cache"), "T2SQL_SCHEMA_CACHE_HOURS": "24"}):
                with mock.patch.object(ClickHouseBackend, "_load_schema", side_effect=lambda *a, **k: fake()) as loader:
                    first = be.load_schema(docs)
                    second = be.load_schema(docs)
                    self.assertEqual(loader.call_count, 1)                    # lần hai đọc từ đệm
                    col = second.tables["VATInvoice"].columns[0]
                    self.assertEqual((col.name, col.type, col.samples, second.business_rules, second.concepts),
                                     ("Amount", "Decimal(21, 6)", [1, "a"], ["rule"], {"c": ["VATInvoice"]}))
                    self.assertEqual(second.tables["VATInvoice"].row_count, 5)
                    with open(docs, "w", encoding="utf-8") as f:
                        f.write('{"a": 2}')
                    be.load_schema(docs)
                    self.assertEqual(loader.call_count, 2)                    # đổi tài liệu thì nạp lại
                    be.load_schema(docs)
                    self.assertEqual(loader.call_count, 2)
                    sig[0] = "v2"                                             # database thêm / xóa cột
                    be.load_schema(docs)
                    self.assertEqual(loader.call_count, 3)                    # đổi cấu trúc bảng thì nạp lại
            with mock.patch.dict(os.environ, {"T2SQL_CACHE_DIR": os.path.join(tmp, "cache"), "T2SQL_SCHEMA_CACHE_HOURS": "0"}):
                with mock.patch.object(ClickHouseBackend, "_load_schema", side_effect=lambda *a, **k: fake()) as loader:
                    be.load_schema(docs)
                    be.load_schema(docs)
                    self.assertEqual(loader.call_count, 2)                    # tắt đệm

    def test_single_user_url_uses_the_account_for_every_role(self):
        from t2sql.db.clickhouse import ClickHouseBackend
        shared = ClickHouseBackend("clickhouses://huy:p%40ss@ch.congty.vn/sales?single_user=1")
        self.assertEqual(shared.username(POL["admin"]), "huy")
        self.assertEqual(shared.username(POL["analyst"]), "huy")
        self.assertEqual((shared.secure, shared.port, shared.password, shared.database), (True, 8443, "p@ss", "sales"))
        per_role = ClickHouseBackend("clickhouse://t2sql:x@127.0.0.1:8123/hddt")
        self.assertEqual(per_role.username(POL["analyst"]), "t2sql_analyst")

    def test_policy_table_and_column_names_are_case_insensitive(self):
        from t2sql.db.clickhouse import ast_check
        from t2sql.safety import Policy
        pol = Policy("admin", allowed_tables={"VATInvoice", "ProductInv"}, denied_columns={("VATInvoice", "CusPhone")})
        self.assertEqual(ast_check("SELECT count() FROM VATInvoice FINAL", pol), {"vatinvoice"})
        for sql in ("SELECT CusPhone FROM VATInvoice", "SELECT * FROM VATInvoice"):
            with self.assertRaises(SafetyError):
                ast_check(sql, pol)
        with self.assertRaises(SafetyError):
            ast_check("SELECT 1 FROM VATInvoice_local", pol)

    def test_readonly_setting_errors_switch_to_restricted_mode(self):
        from t2sql.db.clickhouse import _is_readonly_setting_error
        self.assertTrue(_is_readonly_setting_error(Exception("Setting max_execution_time is readonly")))
        self.assertTrue(_is_readonly_setting_error(Exception("Code: 164. DB::Exception: Cannot modify 'x' setting in readonly mode")))
        self.assertFalse(_is_readonly_setting_error(Exception("Code: 60. DB::Exception: Table x doesn't exist")))
        # ghi dữ liệu bằng user chỉ đọc (cũng mã 164) và vi phạm ràng buộc setting (452) KHÔNG phải lỗi đổi setting
        self.assertFalse(_is_readonly_setting_error(Exception("Code: 164. DB::Exception: Cannot execute query in readonly mode")))
        self.assertFalse(_is_readonly_setting_error(Exception("Code: 452. DB::Exception: Setting max_memory_usage should not be changed")))

    def test_write_attempt_keeps_limits_and_timeout_is_enforced_when_restricted(self):
        from unittest import mock
        from t2sql.db.clickhouse import ClickHouseBackend
        be = ClickHouseBackend("clickhouse://u:p@ch.local:8123/hddt?single_user=1", timeout_s=7)
        client = mock.Mock()
        client.query.side_effect = Exception("Code: 164. DB::Exception: Cannot execute query in readonly mode")
        with mock.patch.object(ClickHouseBackend, "_client", return_value=client):
            r = be.run("SELECT 1")
        self.assertFalse(r.ok)
        self.assertFalse(be.restricted)                                   # lỗi ghi không làm mất giới hạn của cả tiến trình
        slow = mock.Mock()
        slow.query_rows_stream.side_effect = Exception("HTTPConnectionPool(host='ch.local', port=8123): Read timed out.")
        be.restricted = True
        with mock.patch.object(ClickHouseBackend, "_client", return_value=mock.Mock()), \
             mock.patch.object(ClickHouseBackend, "_client_restricted", return_value=slow) as rc:
            r = be.run("SELECT 1")
        self.assertEqual(r.error_code, "timeout")
        self.assertIn("7s", r.error)
        rc.assert_called()

    def test_ast_check_blocks_clickhouse_specific_risks(self):
        from t2sql.db.clickhouse import ast_check
        cases = {"SELECT * FROM url('http://x/a.csv', CSV)": "forbidden_function",
                 "SELECT * FROM file('/etc/passwd', LineAsString)": "forbidden_function",
                 "SELECT * FROM remote('h', hddt, VATInvoice)": "forbidden_function",
                 "SELECT count() FROM numbers(1000000000)": "forbidden_function",
                 "SELECT sleepEachRow(1) FROM orders": "forbidden_function",
                 "SELECT dictGet('d', 'a', 1)": "forbidden_function",
                 "SELECT name FROM system.tables": "forbidden",
                 "SELECT 1 FROM orders SETTINGS max_execution_time = 1000": "forbidden_keyword",
                 "SELECT 1 FROM orders FORMAT JSON": "forbidden_keyword",
                 "SELECT * FROM orders INTO OUTFILE 'x.csv'": "forbidden_keyword"}
        for sql, code in cases.items():
            with self.subTest(sql=sql):
                with self.assertRaises(SafetyError) as cm:
                    ast_check(sql, POLICIES["admin"])
                self.assertEqual(cm.exception.code, code)
        self.assertEqual(ast_check("SELECT toYear(ArisingDate) y, count() FROM VATInvoice FINAL GROUP BY y ORDER BY y "
                                   "LIMIT 3 BY y", POL["analyst"]), {"vatinvoice"})
        with self.assertRaises(SafetyError):
            ast_check("SELECT CusPhone FROM VATInvoice", POL["analyst"])

    def test_error_message_is_cleaned(self):
        from t2sql.db.clickhouse import _error_parts
        e = Exception("HTTPDriver for http://127.0.0.1:8123 received ClickHouse error code 47\n Code: 47. "
                      "DB::Exception: Unknown expression identifier `foo` in scope SELECT foo FROM orders. "
                      "Maybe you meant: ['o']. (UNKNOWN_IDENTIFIER) (version 25.8.33.6 (official build))")
        code, msg = _error_parts(e)
        self.assertEqual(code, 47)
        self.assertTrue(msg.startswith("Unknown expression identifier `foo`"))
        self.assertNotIn("version", msg)

    def test_topn_per_group_shape_check(self):
        from t2sql.checks import check_result
        q = "Top 3 sản phẩm có doanh thu cao nhất trong từng danh mục"
        good = [(c, f"{c}{i}", 100 - i) for c in "ABCDE" for i in range(3)]
        bad = [(f"{c}{i}", c, 100 - i) for c in "ABCDE" for i in range(5)]
        self.assertEqual(check_result(q, ["cat", "name", "rev"], good), [])
        self.assertEqual([i.rule for i in check_result(q, ["name", "cat", "rev"], bad)], ["R4"])


class TestDatasets(unittest.TestCase):
    def test_hddt_fewshot_pool_is_separate_from_both_eval_sets(self):
        ds = datasets.for_database("hddt")
        def questions(path):
            with open(path, encoding="utf-8") as f:
                return {i["question"] for i in json.load(f)}
        pool = questions(ds.fewshot_path)
        for name in ("eval.json", "eval_holdout.json"):
            self.assertFalse(pool & questions(os.path.join(os.path.dirname(ds.fewshot_path), name)), name)
        self.assertFalse(questions(os.path.join(os.path.dirname(ds.fewshot_path), "eval.json"))
                         & questions(os.path.join(os.path.dirname(ds.fewshot_path), "eval_holdout.json")))

    def test_hddt_analyst_cannot_read_personal_columns_but_admin_can(self):
        from t2sql.db.clickhouse import ast_check
        ds = datasets.for_database("hddt")
        analyst, admin = ds.policies["analyst"], ds.policies["admin"]
        self.assertTrue(analyst.mask_pii and not admin.mask_pii)
        for sql in ("SELECT CusPhone FROM VATInvoice", "SELECT cusemails FROM VATInvoice",
                    "SELECT * FROM VATInvoice", "SELECT v.Buyer FROM VATInvoice AS v FINAL",
                    "SELECT count() FROM VATInvoice_local"):
            with self.assertRaises(SafetyError, msg=sql):
                ast_check(sql, analyst)
        ok = "SELECT ComName, sum(Amount) FROM VATInvoice FINAL WHERE is_deleted = 0 GROUP BY ComName"
        self.assertEqual(ast_check(ok, analyst), {"vatinvoice"})
        self.assertEqual(ast_check("SELECT CusPhone FROM VATInvoice", admin), {"vatinvoice"})
        # model không được thấy cột bị chặn trong schema của vai trò analyst
        from t2sql.schema import Schema, Table, Column
        schema = Schema({"VATInvoice": Table("VATInvoice", [Column("ComName", "String", False, None, ""),
                                                           Column("CusPhone", "String", False, None, "")], "", 0, "")}, [], {})
        shown = schema.without_columns(analyst.denied_columns).render()
        self.assertIn("ComName", shown)
        self.assertNotIn("CusPhone", shown)

    """Bộ dữ liệu theo tên database: datasets/<tên>/schema_docs.json (bắt buộc)."""

    def test_lookup_by_database_name(self):
        with self.assertRaises(FileNotFoundError):
            datasets.for_database("khong_co_bo_du_lieu_nay")
        with self.assertRaises(FileNotFoundError):
            datasets.for_database(None)
        ds = datasets.for_database("hddt")
        self.assertEqual((ds.name, ds.sql_dialect), ("hddt", "clickhouse"))
        self.assertTrue(ds.eval_path.endswith("eval.json") and ds.fewshot_path.endswith("fewshot_pool.json"))
        self.assertIn(("VATInvoice", "CusPhone"), ds.policies["analyst"].denied_columns)
        self.assertEqual(ds.policies["admin"].allowed_tables, {"VATInvoice", "ProductInv"})

    def test_default_policies_only_admin(self):
        self.assertEqual(set(POLICIES), {"admin"})

    def test_hddt_files_are_consistent(self):
        ev = datasets.for_database("hddt")
        with open(ev.eval_path, encoding="utf-8") as f:
            items = json.load(f)
        with open(ev.fewshot_path, encoding="utf-8") as f:
            pool = json.load(f)
        self.assertEqual(len({i["id"] for i in items}), len(items))
        self.assertFalse({i["question"] for i in items} & {p["question"] for p in pool})
        tables = set(ev.docs["tables"])
        for rel in ev.docs["relations"].items():
            for side in rel:
                self.assertIn(side.split(".")[0], tables)


class TestClarifyRules(unittest.TestCase):
    def test_production_uses_the_detailed_clarify_rule_and_older_configs_keep_the_short_one(self):
        from t2sql import prompts
        self.assertTrue(CONFIGS["production"].clarify_strong)
        self.assertFalse(CONFIGS["production_plain"].clarify_strong)
        strong = prompts.sql_system("SCHEMA", True, "clickhouse", strong=True)
        short = prompts.sql_system("SCHEMA", True, "clickhouse", strong=False)
        off = prompts.sql_system("SCHEMA", False, "clickhouse", strong=True)
        self.assertIn("đoán tên cột không có trong schema", strong)
        self.assertIn("CLARIFY:", strong)
        self.assertIn("CLARIFY:", short)
        self.assertNotIn("đoán tên cột không có trong schema", short)
        self.assertNotIn("CLARIFY", off)                   # allow_clarify=False tắt cả hai

    def test_classification_step_parses_the_three_answers_and_fails_open(self):
        from t2sql import prompts
        from t2sql.pipeline import parse_classification
        self.assertEqual(parse_classification("ANSWER"), ("sql", None))
        self.assertEqual(parse_classification("CLARIFY: Theo tiêu chí nào?"), ("clarify", "Theo tiêu chí nào?"))
        self.assertEqual(parse_classification("<think>x</think>\nCANNOT: Không có dữ liệu."), ("cannot", "Không có dữ liệu."))
        self.assertEqual(parse_classification("không rõ"), ("sql", None))          # không đọc được: cứ sinh SQL
        self.assertFalse(CONFIGS["production"].classify_first)
        self.assertTrue(CONFIGS["production_classify"].classify_first)
        self.assertIn("bộ phân loại", prompts.classify_system("SCHEMA"))


class TestRoleVisibility(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.pols = datasets.for_database("hddt").policies          # admin (đặc quyền) + analyst (che PII)

    def test_privileged_role_is_hidden_by_default(self):
        from t2sql import access
        with self.mock.patch.dict(os.environ, {"T2SQL_ALLOW_ADMIN": "", "T2SQL_ADMIN_PASSWORD": ""}):
            self.assertTrue(access.is_privileged(self.pols["admin"]))
            self.assertFalse(access.is_privileged(self.pols["analyst"]))
            self.assertEqual(access.selectable_roles(self.pols), ["analyst"])

    def test_unlock_and_local_override_show_every_role(self):
        from t2sql import access
        with self.mock.patch.dict(os.environ, {"T2SQL_ALLOW_ADMIN": "", "T2SQL_ADMIN_PASSWORD": ""}):
            self.assertEqual(set(access.selectable_roles(self.pols, unlocked=True)), {"admin", "analyst"})
        with self.mock.patch.dict(os.environ, {"T2SQL_ALLOW_ADMIN": "1"}):
            self.assertEqual(set(access.selectable_roles(self.pols)), {"admin", "analyst"})

    def test_password_check(self):
        from t2sql import access
        with self.mock.patch.dict(os.environ, {"T2SQL_ADMIN_PASSWORD": "mat-khau-thu"}):
            self.assertTrue(access.password_matches("mat-khau-thu"))
            self.assertFalse(access.password_matches("sai"))
            self.assertFalse(access.password_matches(""))
        with self.mock.patch.dict(os.environ, {"T2SQL_ADMIN_PASSWORD": ""}):
            self.assertFalse(access.password_matches(""))                   # chưa đặt mật khẩu: không bao giờ mở khóa


class TestCharts(unittest.TestCase):
    def test_bar_chart_is_horizontal_sorted_by_value_with_axis_titles_and_safe_field_names(self):
        import pandas as pd
        from t2sql import charts
        df = pd.DataFrame({"Tên công ty (ComName).": ["CÔNG TY A", "P", "Phạm Văn Tùng"], "số: hóa đơn": [3, 77, 5]})
        spec = charts.bar_chart(df, "Tên công ty (ComName).", "số: hóa đơn").to_dict()
        bar, text = spec["layer"]
        self.assertEqual(bar["encoding"]["y"]["field"], "nhan")                     # tên cột lạ không làm hỏng đặc tả
        self.assertEqual(bar["encoding"]["y"]["sort"], {"field": "gia_tri", "order": "descending"})
        self.assertEqual(bar["encoding"]["y"]["title"], "Tên công ty (ComName).")
        self.assertEqual(bar["encoding"]["x"]["title"], "số: hóa đơn")
        self.assertEqual(bar["encoding"]["x"]["axis"]["format"], ",.0f")           # số nguyên: không có phần thập phân
        self.assertEqual(text["encoding"]["text"]["field"], "gia_tri")             # số trên đầu cột
        self.assertGreaterEqual(spec["height"], 90)

    def test_bar_chart_uses_decimals_for_non_integer_values(self):
        import pandas as pd
        from t2sql import charts
        df = pd.DataFrame({"nhom": ["a", "b"], "ty_le": [12.5, 3.25]})
        self.assertEqual(charts.bar_chart(df, "nhom", "ty_le").to_dict()["layer"][0]["encoding"]["x"]["axis"]["format"], ",.2f")


class TestDraftNote(unittest.TestCase):
    def test_note_only_when_invoices_are_read_without_a_status_filter(self):
        from t2sql import charts
        base = "SELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0"
        self.assertIsNotNone(charts.draft_note(base))
        self.assertIsNone(charts.draft_note(base + " AND No > 0"))                        # đã nói rõ đã phát hành
        self.assertIsNone(charts.draft_note(base + " AND TCTCheckStatus = -2"))
        self.assertIsNone(charts.draft_note(base + " AND Status = 5"))
        self.assertIsNone(charts.draft_note("SELECT count() FROM ProductInv FINAL WHERE is_deleted = 0"))   # chỉ bảng dòng hàng
        self.assertIsNone(charts.draft_note(None))


class TestErrorMemory(unittest.TestCase):
    ENTRIES = [
        {"id": "x1", "question": "Tỷ lệ phần trăm số hóa đơn của mỗi mức thuế suất", "tags": "đếm hóa đơn từ dòng hàng uniqExact",
         "wrong_sql": "SELECT count() FROM ProductInv", "correct_sql": "SELECT uniqExact((ComID, InvID)) FROM ProductInv", "lesson": "đếm hóa đơn bằng uniqExact"},
        {"id": "x2", "question": "Đơn vị tính nào dùng nhiều nhất", "tags": "đơn vị tính rỗng",
         "wrong_sql": "SELECT Unit", "correct_sql": "SELECT Unit WHERE Unit != ''", "lesson": "loại đơn vị tính rỗng"},
    ]

    def test_retrieves_similar_lessons_and_skips_unrelated_questions(self):
        from t2sql.memory import ErrorMemory
        mem = ErrorMemory(self.ENTRIES, k=2, min_score=0.2)
        self.assertEqual([e["id"] for e in mem.top("Mỗi mức thuế suất chiếm bao nhiêu phần trăm số hóa đơn?")], ["x1"])
        self.assertEqual(mem.top("Thời tiết ngày mai thế nào?"), [])

    def test_the_question_being_evaluated_is_excluded_to_avoid_answer_leakage(self):
        from t2sql.memory import ErrorMemory
        mem = ErrorMemory(self.ENTRIES, k=2, min_score=0.1)
        q = self.ENTRIES[0]["question"]
        self.assertEqual(mem.top(q, exclude_question=q), [])

    def test_missing_memory_file_means_no_memory_and_prompt_has_lessons_only_when_found(self):
        from t2sql import prompts
        from t2sql.memory import ErrorMemory
        self.assertIsNone(ErrorMemory.from_file(os.path.join(tempfile.gettempdir(), "khong_co_file.json")))
        plain = prompts.user_message("Câu hỏi mới")
        with_lessons = prompts.user_message("Câu hỏi mới", None, self.ENTRIES[:1])
        self.assertNotIn("Bài học", plain)
        self.assertIn("Bài học: đếm hóa đơn bằng uniqExact", with_lessons)
        self.assertTrue(with_lessons.rstrip().endswith("SQL:"))               # câu hỏi vẫn ở cuối prompt

    def test_memory_is_off_by_default_and_on_in_the_experiment_config(self):
        self.assertFalse(CONFIGS["production"].use_memory)
        self.assertTrue(CONFIGS["production_memory"].use_memory)


class TestMaskValue(unittest.TestCase):
    def test_dates_are_not_masked_as_phone_numbers(self):
        from t2sql.safety import mask_value
        for d in ("2025-01-01", "2025-12-31", "2025-03", "2025-03-01T00:00:00", "2025-03-01 00:00:00"):
            self.assertEqual(mask_value(d), d, d)

    def test_phone_and_email_still_masked(self):
        from t2sql.safety import mask_value
        self.assertEqual(mask_value("0901234567"), "090*****67")
        self.assertEqual(mask_value("+84 901 234 567"), "+84**********67")
        self.assertEqual(mask_value("nguyenvan@congty.vn"), "ng***@congty.vn")

    def test_other_values_unchanged(self):
        from t2sql.safety import mask_value
        self.assertEqual(mask_value("Công ty ABC"), "Công ty ABC")
        self.assertEqual(mask_value(12345), 12345)
        self.assertIsNone(mask_value(None))


if __name__ == "__main__":
    unittest.main()
