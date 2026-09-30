"""Unit test offline (không gọi API).  Chạy:  python -m unittest -v

Test PostgreSQL (TestPostgres) chạy khi kết nối được DB: lấy URL từ T2SQL_TEST_PG_URL, hoặc
T2SQL_DATABASE_URL trong .env (docker compose up -d db). Không kết nối được thì bỏ qua.
"""
import json
import os
import sqlite3
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


PG_URL = os.environ.get("T2SQL_TEST_PG_URL") or (
    _dotenv("T2SQL_DATABASE_URL") if _dotenv("T2SQL_DATABASE_URL").startswith("postgres") else "")
os.environ["T2SQL_DATABASE_URL"] = ""   # các test còn lại luôn chạy trên SQLite data/shop.db

from t2sql import DEFAULT_DB, DEFAULT_DOCS, ROOT
from t2sql.evaluation import categorize, results_match
from t2sql.executor import Executor
from t2sql.llm import ScriptedLLM
from t2sql.logstore import QueryLogger
from t2sql.pipeline import CONFIGS, Config, TextToSQL
from t2sql.retrieval import FewShotRetriever, SchemaLinker, tables_in_sql
from t2sql.safety import POLICIES, SafetyError, static_check
from t2sql.schema import Schema
from t2sql.sql_utils import extract_sql, parse_response, split_statements
from t2sql.viz import choose_view

DATASET = os.path.join(ROOT, "eval", "dataset.json")


def load_items():
    with open(DATASET, encoding="utf-8") as f:
        return json.load(f)


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
        self.assertIn("DROP", extract_sql("SELECT 1; DROP TABLE customers"))

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


class TestSafety(unittest.TestCase):
    def setUp(self):
        self.ex = Executor(DEFAULT_DB, max_rows=50, timeout_s=0.5)

    def test_blocks_write_statements(self):
        for sql in ["DROP TABLE customers", "DELETE FROM orders", "UPDATE orders SET status = 1",
                    "INSERT INTO suppliers VALUES (99, 'x', 'y')", "PRAGMA table_info(orders)",
                    "ATTACH DATABASE 'x.db' AS x"]:
            with self.subTest(sql=sql):
                self.assertRaises(SafetyError, static_check, sql)
                self.assertFalse(self.ex.run(sql).ok)

    def test_blocks_multi_statement(self):
        res = self.ex.run("SELECT 1; DROP TABLE customers")
        self.assertEqual(res.error_code, "multi_statement")

    def test_keyword_inside_string_is_allowed(self):
        res = self.ex.run("SELECT COUNT(*) FROM reviews WHERE comment LIKE '%DROP TABLE%'")
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.rows[0][0], 1)  # đúng một review chứa câu injection

    def test_readonly_even_without_static_check(self):
        res = self.ex.run("DELETE FROM orders", safe=False)
        self.assertFalse(res.ok)
        con = sqlite3.connect(DEFAULT_DB)
        self.assertGreater(con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
        con.close()

    def test_timeout_on_heavy_query(self):
        res = self.ex.run("SELECT COUNT(*) FROM order_items a, order_items b, order_items c")
        self.assertEqual(res.error_code, "timeout")

    def test_row_limit(self):
        res = self.ex.run("SELECT * FROM order_items")
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.rows), 50)

    def test_table_permission(self):
        res = self.ex.run("SELECT COUNT(*) FROM customers", policy=POLICIES["sales"])
        self.assertEqual(res.error_code, "forbidden")
        # subquery / CTE cũng bị bắt vì authorizer thấy mọi bảng được đọc
        res = self.ex.run("WITH x AS (SELECT city FROM customers) SELECT * FROM x", policy=POLICIES["sales"])
        self.assertEqual(res.error_code, "forbidden")
        self.assertTrue(self.ex.run("SELECT COUNT(*) FROM orders", policy=POLICIES["sales"]).ok)

    def test_column_permission(self):
        analyst = POLICIES["analyst"]
        self.assertEqual(self.ex.run("SELECT email FROM customers", policy=analyst).error_code, "forbidden")
        self.assertEqual(self.ex.run("SELECT * FROM customers", policy=analyst).error_code, "forbidden")
        self.assertTrue(self.ex.run("SELECT name, city FROM customers", policy=analyst).ok)

    def test_pii_masking(self):
        from t2sql.safety import Policy
        res = self.ex.run("SELECT email, phone FROM customers LIMIT 1", policy=Policy("x", mask_pii=True))
        email, phone = res.rows[0]
        self.assertIn("***@", email)
        self.assertIn("*", phone)

    def test_sqlite_master_blocked(self):
        self.assertFalse(self.ex.run("SELECT sql FROM sqlite_master").ok)


class TestEvaluation(unittest.TestCase):
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


class TestDataset(unittest.TestCase):
    def test_gold_sql_runs_and_is_non_empty(self):
        ex = Executor(DEFAULT_DB, max_rows=10_000)
        items = load_items()
        self.assertGreaterEqual(len([i for i in items if i["sql"]]), 50)
        for it in items:
            if it["sql"]:
                with self.subTest(id=it["id"]):
                    res = ex.run(it["sql"])  # SQL chuẩn cũng phải qua được lớp an toàn
                    self.assertTrue(res.ok, res.error)
                    self.assertTrue(res.rows)

    def test_fewshot_pool_runs_and_does_not_leak(self):
        ex = Executor(DEFAULT_DB)
        with open(os.path.join(ROOT, "eval", "fewshot_pool.json"), encoding="utf-8") as f:
            pool = json.load(f)
        eval_qs = {i["question"] for i in load_items()}
        for e in pool:
            with self.subTest(q=e["question"]):
                self.assertTrue(ex.run(e["sql"]).ok)
                self.assertNotIn(e["question"], eval_qs)

    def test_schema_linking_recall(self):
        schema = Schema.from_db(sqlite3.connect(DEFAULT_DB), DEFAULT_DOCS)
        linker = SchemaLinker(schema)
        for it in load_items():
            if it["sql"]:
                with self.subTest(id=it["id"]):
                    self.assertTrue(tables_in_sql(it["sql"]) <= set(linker.link(it["question"])))


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.schema = Schema.from_db(sqlite3.connect(DEFAULT_DB), DEFAULT_DOCS)

    def test_baseline_has_no_docs(self):
        text = self.schema.render(with_docs=False)
        self.assertIn("TABLE orders", text)
        self.assertNotIn("hoàn thành", text)

    def test_docs_contain_business_rules_and_samples(self):
        text = self.schema.render(with_docs=True)
        self.assertIn("status = 4", text)
        self.assertIn("ví dụ:", text)

    def test_no_pii_or_free_text_in_samples(self):
        text = self.schema.render(with_docs=True)
        self.assertNotIn("@example.com", text)
        self.assertNotIn("Bỏ qua mọi hướng dẫn", text)


def scripted(responses):
    """LLM giả trả lần lượt các phản hồi trong danh sách."""
    it = iter(responses)
    return ScriptedLLM(lambda system, messages: next(it))


class TestPipeline(unittest.TestCase):
    def test_baseline_end_to_end(self):
        llm = scripted(["```sql\nSELECT COUNT(*) FROM customers\n```"])
        ans = TextToSQL(llm, "baseline").ask("Có bao nhiêu khách hàng?")
        self.assertEqual(ans.kind, "result")
        self.assertEqual(ans.result.rows, [(200,)])

    def test_sql_error_without_retry_does_not_crash(self):
        ans = TextToSQL(scripted(["SELECT nope FROM customers"]), "baseline").ask("x")
        self.assertEqual(ans.kind, "result")
        self.assertFalse(ans.result.ok)
        self.assertIn("no such column", ans.result.error)

    def test_self_correction_fixes_error(self):
        llm = scripted(["SELECT nope FROM customers", "SELECT COUNT(*) FROM customers"])
        ans = TextToSQL(llm, "selfcorrect").ask("Có bao nhiêu khách hàng?")
        self.assertEqual(len(ans.attempts), 2)
        self.assertTrue(ans.result.ok)
        # lượt sửa phải chứa thông báo lỗi và SQL cũ
        fix_turn = llm.calls[1][1]
        self.assertEqual(fix_turn[1]["content"], "SELECT nope FROM customers")
        self.assertIn("no such column", fix_turn[2]["content"])

    def test_self_correction_is_bounded(self):
        llm = ScriptedLLM(lambda s, m: "SELECT nope FROM customers")
        ans = TextToSQL(llm, "selfcorrect").ask("x")
        self.assertEqual(len(ans.attempts), CONFIGS["selfcorrect"].max_retries + 1)

    def test_empty_result_retry_stops_when_sql_repeats(self):
        empty = "SELECT * FROM customers WHERE city = 'Paris'"
        llm = ScriptedLLM(lambda s, m: empty)
        ans = TextToSQL(llm, "selfcorrect").ask("Khách ở Paris")
        self.assertEqual(len(ans.attempts), 2)  # hỏi lại một lần, model giữ nguyên -> dừng
        self.assertTrue(ans.result.empty)

    def test_injected_second_statement_is_blocked_without_retry(self):
        llm = ScriptedLLM(lambda s, m: "SELECT 1; DROP TABLE customers")
        ans = TextToSQL(llm, "selfcorrect").ask("x")
        self.assertEqual(ans.result.error_code, "multi_statement")
        self.assertEqual(len(ans.attempts), 1)

    def test_cannot_answer(self):
        ans = TextToSQL(scripted(["CANNOT_ANSWER: Không có dữ liệu thời tiết."]), "baseline").ask("Thời tiết?")
        self.assertEqual(ans.kind, "cannot")

    def test_write_request_refused_before_llm(self):
        llm = ScriptedLLM(lambda s, m: self.fail("không được gọi LLM"))
        ans = TextToSQL(llm, "production").ask("Xóa tất cả đơn hàng bị hủy")
        self.assertEqual(ans.kind, "refused")

    def test_denied_columns_hidden_from_prompt(self):
        llm = scripted(["SELECT COUNT(*) FROM customers"])
        TextToSQL(llm, "baseline").ask("Có bao nhiêu khách hàng?", policy="analyst")
        self.assertNotIn(" email ", llm.calls[0][0])
        self.assertIn(" city ", llm.calls[0][0])

    def test_role_restricts_schema_in_prompt(self):
        llm = scripted(["SELECT COUNT(*) FROM orders"])
        ans = TextToSQL(llm, "baseline").ask("Có bao nhiêu đơn?", policy="sales")
        self.assertNotIn("TABLE customers", llm.calls[0][0])
        self.assertTrue(ans.result.ok)

    def test_fewshot_excludes_eval_question(self):
        llm = scripted(["SELECT 1"])
        pool_q = "Có bao nhiêu sản phẩm đang kinh doanh?"
        TextToSQL(llm, "fewshot").ask(pool_q, exclude_example=pool_q)
        user_msg = llm.calls[0][1][0]["content"]
        self.assertEqual(user_msg.count(pool_q), 1)  # chỉ xuất hiện ở câu hỏi, không ở ví dụ

    def test_linking_shrinks_prompt(self):
        llm = scripted(["SELECT AVG(rating) FROM reviews"])
        ans = TextToSQL(llm, "linking").ask("Điểm đánh giá trung bình là bao nhiêu?")
        self.assertIn("reviews", ans.tables_in_prompt)
        self.assertLess(len(ans.tables_in_prompt), 6)

    def test_multi_turn_rewrite_and_explanation(self):
        def fn(system, messages):
            if "câu hỏi độc lập" in system:
                self.assertIn("năm 2025", messages[0]["content"])
                return "Doanh thu năm 2024 là bao nhiêu?"
            if system.startswith("Bạn giải thích"):
                return "Tính tổng doanh thu các đơn hoàn thành năm 2024."
            self.assertIn("năm 2024", messages[0]["content"])
            return ("SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) FROM order_items oi "
                    "JOIN orders o ON o.order_id = oi.order_id WHERE o.status = 4 "
                    "AND strftime('%Y', o.order_date) = '2024'")
        history = [{"question": "Doanh thu năm 2025 là bao nhiêu?", "sql": "SELECT ..."}]
        ans = TextToSQL(ScriptedLLM(fn), "production").ask("Còn năm 2024 thì sao?", history=history)
        self.assertEqual(ans.standalone_question, "Doanh thu năm 2024 là bao nhiêu?")
        self.assertTrue(ans.result.ok)
        self.assertTrue(ans.explanation)

    def test_clarify(self):
        ans = TextToSQL(scripted(["CLARIFY: Tốt nhất theo doanh thu, số lượng bán hay điểm đánh giá?"]),
                        "production").ask("Sản phẩm nào tốt nhất?")
        self.assertEqual(ans.kind, "clarify")
        self.assertIn("doanh thu", ans.message)

    def test_logging_and_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            logger = QueryLogger(os.path.join(d, "q.jsonl"))
            pipe = TextToSQL(scripted(["SELECT COUNT(*) FROM customers"]), "baseline", logger=logger)
            ans = pipe.ask("Có bao nhiêu khách hàng?")
            logger.feedback(ans.id, True)
            self.assertEqual(logger.verified_examples(),
                             [{"question": "Có bao nhiêu khách hàng?", "sql": "SELECT COUNT(*) FROM customers"}])


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

        answer = "<think>Cần đếm khách hàng.</think>\n```sql\nSELECT COUNT(*) FROM customers\n```"

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

    def test_end_to_end_with_think_block(self):
        from t2sql.llm import OpenAICompatLLM
        llm = OpenAICompatLLM(model="SDS-AI/softdream", base_url=self.url, api_key="k")
        ans = TextToSQL(llm, "baseline").ask("Có bao nhiêu khách hàng?")
        self.assertEqual(ans.result.rows, [(200,)])
        path, auth, body = self.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")   # tự thêm /v1
        self.assertEqual(auth, "Bearer k")
        self.assertEqual(body["model"], "SDS-AI/softdream")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertTrue(body["stream"])
        self.assertEqual(llm.usage.input_tokens, 11)
        self.assertEqual(llm.usage.output_tokens, 20)

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
                         "SELECT COUNT(*) FROM customers")
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

    def test_r7_all_null(self):
        self.assertEqual(self.rules("Doanh thu năm 2030?", ["x"], [(None,)]), ["R7"])

    def test_no_false_positive_on_gold(self):
        """Điều kiện bắt buộc: 60 SQL chuẩn không bị báo nghi vấn."""
        from t2sql.checks import check_result
        ex = Executor(DEFAULT_DB, max_rows=10_000)
        for it in load_items():
            if it["sql"]:
                with self.subTest(id=it["id"]):
                    res = ex.run(it["sql"])
                    self.assertEqual(check_result(it["question"], res.columns, res.rows), [])


H06_Q = "Trong mỗi danh mục, sản phẩm nào có doanh thu cao nhất? Cho biết danh mục, tên sản phẩm và doanh thu."
H06_BAD = ("SELECT p.category, p.name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount)) AS dt FROM order_items oi "
           "JOIN orders o ON o.order_id = oi.order_id JOIN products p ON p.product_id = oi.product_id "
           "WHERE o.status = 4 GROUP BY p.product_id ORDER BY p.category, dt DESC")
H06_GOOD = next(i["sql"] for i in load_items() if i["id"] == "h06")


class TestShapeCheckPipeline(unittest.TestCase):
    def test_suspicious_result_is_sent_back_and_fixed(self):
        llm = scripted([H06_BAD, H06_GOOD])
        ans = TextToSQL(llm, "shapecheck").ask(H06_Q)
        self.assertEqual(len(ans.attempts), 2)
        self.assertEqual(ans.attempts[0].issues, ["R2"])
        self.assertIn("lặp lại", llm.calls[1][1][-1]["content"])   # phản hồi gửi model có mô tả nghi vấn
        self.assertEqual(len(ans.result.rows), 5)
        self.assertEqual(ans.attempts[1].issues, [])

    def test_model_keeping_sql_is_accepted(self):
        llm = ScriptedLLM(lambda s, m: H06_BAD)
        ans = TextToSQL(llm, "shapecheck").ask(H06_Q)
        self.assertEqual(len(ans.attempts), 2)   # hỏi lại một lần, model giữ nguyên -> dừng, không ép tiếp
        self.assertEqual(ans.sql, H06_BAD)

    def test_disabled_in_selfcorrect(self):
        ans = TextToSQL(scripted([H06_BAD]), "selfcorrect").ask(H06_Q)
        self.assertEqual(len(ans.attempts), 1)

    def test_sql_without_table_is_sent_back(self):
        """R0: "SELECT count()" không có FROM vẫn chạy (ClickHouse trả 1) nhưng không lấy từ dữ liệu."""
        llm = scripted(["SELECT 1 AS trung_binh", "SELECT AVG(quantity) FROM order_items"])
        ans = TextToSQL(llm, "shapecheck").ask("Trung bình mỗi dòng hàng mua bao nhiêu sản phẩm?")
        self.assertEqual(ans.attempts[0].issues, ["R0"])
        self.assertIn("FROM", llm.calls[1][1][-1]["content"])
        self.assertEqual(ans.sql, "SELECT AVG(quantity) FROM order_items")


class TestImprovements(unittest.TestCase):
    """Danh mục, chặn truy vấn nặng, tự soát logic, reasoning cho câu khó (cấu hình lookup / costguard / verify / reasoning)."""

    def cfg(self, **kw):
        base = dict(use_docs=True, use_linking=True, max_retries=3, shape_check=True)
        base.update(kw)
        return Config("test", **base)

    def test_lookup_tables_and_value_linking(self):
        llm = scripted(["SELECT COUNT(*) FROM products p JOIN suppliers s ON s.supplier_id = p.supplier_id WHERE s.name = 'Samsung Vina'"])
        pipe = TextToSQL(llm, self.cfg(lookup_tables=True))
        self.assertIn("suppliers", pipe.lookups)
        ans = pipe.ask("Samsung Vina cung cấp bao nhiêu mặt hàng?")
        self.assertIn("suppliers", ans.tables_in_prompt)
        system = llm.calls[0][0]
        self.assertIn("DANH MỤC ĐẦY ĐỦ", system)
        self.assertIn("Samsung Vina", system)
        self.assertNotIn("DANH MỤC ĐẦY ĐỦ", TextToSQL(scripted(["SELECT 1"]), self.cfg()).schema.render(True))

    def test_cost_guard_asks_for_cheaper_sql_before_running(self):
        from unittest import mock
        heavy, light = "SELECT SUM(quantity) FROM order_items", "SELECT SUM(quantity) FROM order_items WHERE order_id < 10"
        llm = scripted([heavy, light])
        pipe = TextToSQL(llm, self.cfg(cost_guard=True, cost_guard_rows=1000))
        est = lambda sql, policy=None: (5000, {"order_items": 5000}) if sql == heavy else (10, {"order_items": 10})
        with mock.patch.object(pipe.backend, "estimate_rows", side_effect=est), \
                mock.patch.object(pipe.backend, "run", wraps=pipe.backend.run) as run:
            ans = pipe.ask("Tổng số lượng bán ra của vài đơn đầu")
        self.assertEqual([a.estimated_rows for a in ans.attempts], [5000, None])
        self.assertEqual([c.args[0] for c in run.call_args_list], [light])   # SQL nặng không được chạy
        self.assertIn("dự kiến đọc khoảng 5,000 dòng", llm.calls[1][1][-1]["content"])

    def test_cost_guard_accepts_repeated_sql(self):
        from unittest import mock
        heavy = "SELECT SUM(quantity) FROM order_items"
        pipe = TextToSQL(scripted([heavy, heavy]), self.cfg(cost_guard=True, cost_guard_rows=1000))
        with mock.patch.object(pipe.backend, "estimate_rows", return_value=(5000, {"order_items": 5000})):
            ans = pipe.ask("Tổng số lượng bán ra")
        self.assertTrue(ans.result.ok)
        self.assertEqual(len(ans.attempts), 2)

    def test_semantic_check_sends_reason_back(self):
        bad = "SELECT customer_id, SUM(shipping_fee) FROM orders GROUP BY customer_id ORDER BY 2 DESC LIMIT 1"
        good = "SELECT order_id, shipping_fee FROM orders ORDER BY shipping_fee DESC LIMIT 1"
        llm = scripted([bad, "SAI: câu hỏi cần một đơn, không phải tổng theo khách", good])
        ans = TextToSQL(llm, self.cfg(semantic_check=True)).ask("Đơn hàng có phí vận chuyển cao nhất?")
        self.assertEqual(ans.sql, good)
        self.assertEqual(ans.attempts[0].verdict, "câu hỏi cần một đơn, không phải tổng theo khách")
        self.assertIn("QUY TẮC NGHIỆP VỤ", llm.calls[1][1][0]["content"])      # lời gọi soát lỗi
        self.assertIn("không phải tổng theo khách", llm.calls[2][1][-1]["content"])
        self.assertEqual(len(llm.calls), 3)          # chỉ soát một lần mỗi chuỗi

    def test_semantic_check_ok_keeps_sql(self):
        sql = "SELECT COUNT(*) FROM customers"
        llm = scripted([sql, "OK"])
        ans = TextToSQL(llm, self.cfg(semantic_check=True)).ask("Có bao nhiêu khách hàng?")
        self.assertEqual((ans.sql, len(llm.calls), ans.attempts[0].verdict), (sql, 2, None))

    def test_reasoning_only_for_hard_questions(self):
        from t2sql.pipeline import looks_hard
        self.assertTrue(looks_hard("Doanh thu tháng 6 tăng bao nhiêu phần trăm so với tháng 5?", 2))
        self.assertFalse(looks_hard("Có bao nhiêu khách hàng ở Hà Nội?", 5))
        llm = scripted(["SELECT COUNT(*) FROM customers", "SELECT 100.0 * SUM(status = 3) / COUNT(*) FROM orders"])
        pipe = TextToSQL(llm, self.cfg(reasoning_hard="medium"))
        self.assertIsNone(pipe.ask("Có bao nhiêu khách hàng?").reasoning)
        self.assertEqual(pipe.ask("Tỷ lệ đơn bị hủy là bao nhiêu phần trăm?").reasoning, "medium")
        self.assertEqual(llm.reasoning_levels, [None, "medium"])


class TestReviewFixes(unittest.TestCase):
    """Hồi quy cho các lỗi tìm thấy khi review."""

    def test_tables_in_sql_handles_quotes_and_schema_prefix(self):
        self.assertEqual(tables_in_sql('SELECT 1 FROM "orders"'), {"orders"})
        self.assertEqual(tables_in_sql("SELECT 1 FROM `invoices` FINAL"), {"invoices"})
        self.assertEqual(tables_in_sql('SELECT 1 FROM shop.orders o JOIN "shop"."customers" c ON 1'), {"orders", "customers"})
        self.assertEqual(tables_in_sql("SELECT 1"), set())

    def test_quoted_table_is_not_flagged_as_missing_from(self):
        ans = TextToSQL(scripted(['SELECT COUNT(*) FROM "customers"']), "shapecheck").ask("Có bao nhiêu khách hàng?")
        self.assertEqual(ans.attempts[0].issues, [])
        self.assertEqual(len(ans.attempts), 1)

    def test_verifier_failure_keeps_good_result(self):
        from t2sql.llm import LLMError
        outs = iter(["SELECT COUNT(*) FROM customers"])

        def fn(system, messages):
            if system.startswith("Bạn là người soát lỗi"):
                raise LLMError("hết thời gian chờ")
            return next(outs)
        ans = TextToSQL(ScriptedLLM(fn), Config("t", use_docs=True, max_retries=2, semantic_check=True)).ask("Có bao nhiêu khách hàng?")
        self.assertEqual(ans.kind, "result")
        self.assertTrue(ans.result.ok)

    def test_topn_with_each_word_but_ranking_column_still_checked(self):
        from t2sql.checks import check_result
        rows = [(f"sp{i}", 100 - i) for i in range(50)]
        rules = [i.rule for i in check_result("Top 5 sản phẩm bán chạy nhất, doanh thu từng sản phẩm", ["name", "rev"], rows)]
        self.assertEqual(rules, ["R4"])

    def test_empty_allowed_tables_means_no_access(self):
        from t2sql.datasets import Dataset
        d = Dataset("x", "", None, None, docs={"policies": {"locked": {"allowed_tables": []}, "open": {}}})
        self.assertEqual(d.policies["locked"].allowed_tables, set())
        self.assertIsNone(d.policies["open"].allowed_tables)
        res = TextToSQL(scripted(["SELECT 1 FROM orders"]), "docs").executor.run("SELECT COUNT(*) FROM orders", policy=d.policies["locked"])
        self.assertEqual(res.error_code, "forbidden")


class TestSelfConsistency(unittest.TestCase):
    def cfg(self, **kw):
        from dataclasses import replace
        return replace(CONFIGS["consistency"], **kw)

    def by_temperature(self, greedy, *samples):
        """LLM giả: temperature None -> SQL greedy; các lần lấy mẫu lần lượt nhận samples."""
        it = iter(samples)
        seen = []

        def fn(system, messages):
            return None
        llm = ScriptedLLM(fn)

        def complete(system, messages, max_tokens=16000, temperature=None, reasoning=None):
            seen.append(temperature)
            with llm._lock:
                return greedy if temperature is None else next(it)
        llm.complete = complete
        llm.seen = seen
        return llm

    def test_majority_vote_overrides_greedy(self):
        good = "SELECT COUNT(*) FROM customers"
        llm = self.by_temperature("SELECT COUNT(*) FROM orders", good, "SELECT COUNT(customer_id) FROM customers")
        ans = TextToSQL(llm, self.cfg(early_stop=False)).ask("Có bao nhiêu khách hàng?")
        self.assertEqual(ans.result.rows[0][0], 200)
        self.assertEqual(ans.agreement, "2/3")
        self.assertEqual(sorted(t is None for t in llm.seen), [False, False, True])

    def test_early_stop_when_first_two_agree(self):
        llm = self.by_temperature("SELECT COUNT(*) FROM customers", "SELECT COUNT(customer_id) FROM customers",
                                  "SELECT 1")
        ans = TextToSQL(llm, self.cfg()).ask("Có bao nhiêu khách hàng?")
        self.assertEqual(len(llm.seen), 2)
        self.assertEqual(ans.agreement, "2/2")

    def test_failed_candidates_do_not_vote(self):
        llm = self.by_temperature("SELECT nope FROM customers", "SELECT COUNT(*) FROM customers", "SELECT nope2 FROM x")
        cfg = self.cfg(early_stop=False, max_retries=0)
        ans = TextToSQL(llm, cfg).ask("Có bao nhiêu khách hàng?")
        self.assertTrue(ans.result.ok)
        self.assertEqual(ans.agreement, "1/3")

    def test_flagged_candidate_loses_to_clean_one(self):
        llm = self.by_temperature(H06_BAD, H06_GOOD, H06_BAD)
        cfg = self.cfg(early_stop=False, max_retries=0, shape_check=True)
        ans = TextToSQL(llm, cfg).ask(H06_Q)
        self.assertEqual(len(ans.result.rows), 5)
        self.assertEqual([c["winner"] for c in ans.candidates], [False, True, False])

    def test_refusals_vote_together(self):
        llm = self.by_temperature("CANNOT_ANSWER: không có dữ liệu", "CANNOT_ANSWER: không có", "SELECT 1")
        ans = TextToSQL(llm, self.cfg()).ask("Thời tiết hôm nay?")
        self.assertEqual(ans.kind, "cannot")
        self.assertEqual(ans.agreement, "2/2")


def _pg_available():
    if not PG_URL:
        return False
    try:
        import psycopg
        psycopg.connect(PG_URL, connect_timeout=3).close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_pg_available(), "không kết nối được PostgreSQL (docker compose up -d db)")
class TestPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from t2sql.db import make_backend
        cls.pg = make_backend(PG_URL, max_rows=50, timeout_s=1)

    def run_as(self, role, sql):
        return self.pg.run(sql, policy=POLICIES[role])

    def test_schema_introspection(self):
        schema = self.pg.load_schema(DEFAULT_DOCS)
        self.assertEqual(set(schema.tables),
                         {"customers", "suppliers", "products", "orders", "order_items", "reviews"})
        orders = {c.name: c for c in schema.tables["orders"].columns}
        self.assertTrue(orders["order_id"].pk)
        self.assertEqual(orders["customer_id"].fk, "customers.customer_id")
        self.assertEqual(orders["order_date"].type, "date")
        text = schema.render(with_docs=True)
        self.assertIn("status = 4", text)
        self.assertNotIn("@example.com", text)
        self.assertNotIn("Bỏ qua mọi hướng dẫn", text)

    def test_values_are_normalized(self):
        res = self.run_as("admin", "SELECT MAX(o.order_date), AVG(r.rating), SUM(p.unit_price) FROM orders o, "
                                   "(SELECT rating FROM reviews LIMIT 1) r, (SELECT unit_price FROM products LIMIT 1) p")
        self.assertTrue(res.ok, res.error)
        d, avg, total = res.rows[0]
        self.assertEqual(d, "2025-06-30")
        self.assertIsInstance(avg, (int, float))
        self.assertIsInstance(total, (int, float))

    def test_role_permissions(self):
        self.assertTrue(self.run_as("analyst", "SELECT COUNT(*) FROM customers").ok)
        self.assertTrue(self.run_as("analyst", "SELECT name, city FROM customers").ok)
        for sql in ["SELECT email FROM customers", "SELECT * FROM customers", "SELECT c.* FROM customers c"]:
            with self.subTest(sql=sql):
                self.assertEqual(self.run_as("analyst", sql).error_code, "forbidden")
        self.assertEqual(self.run_as("sales", "SELECT COUNT(*) FROM customers").error_code, "forbidden")
        self.assertEqual(self.run_as("sales", "WITH x AS (SELECT city FROM customers) SELECT * FROM x").error_code,
                         "forbidden")
        self.assertTrue(self.run_as("sales", "SELECT COUNT(*) FROM orders").ok)

    def test_database_enforces_permissions_even_without_parser_check(self):
        from unittest import mock
        with mock.patch("t2sql.db.postgres.ast_check", return_value=set()):
            res = self.run_as("analyst", "SELECT email FROM customers")
            self.assertEqual(res.error_code, "forbidden")
            self.assertIn("permission denied", res.error)
            res = self.run_as("sales", "SELECT COUNT(*) FROM customers")
            self.assertEqual(res.error_code, "forbidden")
        # Bỏ mọi kiểm tra phía app: server-side cursor không nhận lệnh ghi...
        self.assertFalse(self.pg.run("DELETE FROM orders", safe=False).ok)
        # ...và kể cả chạy thẳng trên kết nối của app, transaction READ ONLY vẫn chặn.
        import psycopg
        with self.pg._connect() as conn:
            self.pg._set_role(conn, POLICIES["admin"])
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute("DELETE FROM orders")
        self.assertEqual(self.run_as("admin", "SELECT COUNT(*) FROM orders").rows[0][0], 1446)

    def test_blocks_dangerous_sql(self):
        cases = {"SELECT pg_sleep(5)": "forbidden_function",
                 "SELECT set_config('statement_timeout', '0', false)": "forbidden_function",
                 "SELECT * INTO new_table FROM orders": "forbidden_keyword",
                 "SELECT * FROM orders FOR UPDATE": "forbidden_keyword",
                 "SELECT * FROM pg_catalog.pg_roles": "forbidden",
                 "SELECT * FROM information_schema.tables": "forbidden",
                 "WITH x AS (DELETE FROM orders RETURNING 1) SELECT * FROM x": "forbidden_keyword",
                 "SELECT 1; DROP TABLE orders": "multi_statement"}
        for sql, code in cases.items():
            with self.subTest(sql=sql):
                self.assertEqual(self.run_as("admin", sql).error_code, code)

    def test_timeout_and_row_limit(self):
        res = self.run_as("admin", "SELECT COUNT(*) FROM order_items a, order_items b, order_items c")
        self.assertEqual(res.error_code, "timeout")
        res = self.run_as("admin", "SELECT * FROM order_items")
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.rows), 50)

    def test_gold_and_fewshot_match_sqlite(self):
        """SQL viết cho SQLite, sau khi chuyển sang Postgres, phải cho cùng kết quả trên hai DB."""
        from t2sql.db import make_backend
        from t2sql.dialect import example_sql
        lite = Executor(DEFAULT_DB, max_rows=10_000)
        pg = make_backend(PG_URL, max_rows=10_000, timeout_s=30)
        with open(os.path.join(ROOT, "eval", "fewshot_pool.json"), encoding="utf-8") as f:
            pool = json.load(f)
        for it in [i for i in load_items() if i["sql"]] + pool:
            with self.subTest(q=it["question"]):
                pg_sql = example_sql(it, "postgres")
                a, b = lite.run(it["sql"]), pg.run(pg_sql)
                self.assertTrue(b.ok, f"{b.error}: {pg_sql}")
                self.assertTrue(results_match(b.rows, a.rows, it.get("ordered", False)), pg_sql)

    def test_pipeline_end_to_end_and_prompt(self):
        llm = scripted(["SELECT TO_CHAR(order_date, 'YYYY') AS nam, COUNT(*) FROM orders GROUP BY 1"])
        ans = TextToSQL(llm, "docs", db=PG_URL).ask("Số đơn theo năm", policy="analyst")
        self.assertTrue(ans.result.ok, ans.result.error)
        self.assertEqual(sum(n for _, n in ans.result.rows), 1446)
        system = llm.calls[0][0]
        self.assertIn("PostgreSQL", system)
        self.assertIn("TO_CHAR", system)
        self.assertNotIn(" email ", system)   # cột analyst không được đọc bị ẩn khỏi prompt

    def test_fewshot_examples_are_transpiled(self):
        llm = scripted(["SELECT 1"])
        TextToSQL(llm, "fewshot", db=PG_URL).ask("Doanh thu tháng 1 năm 2025.")
        user_msg = llm.calls[0][1][0]["content"]
        self.assertNotIn("strftime", user_msg)
        self.assertIn("TO_CHAR", user_msg)


class TestClickHouseOffline(unittest.TestCase):
    """Phần không cần server: kiểm tra AST, chuyển dialect, đọc lỗi."""

    def test_ast_check_blocks_clickhouse_specific_risks(self):
        from t2sql.db.clickhouse import ast_check
        cases = {"SELECT * FROM url('http://x/a.csv', CSV)": "forbidden_function",
                 "SELECT * FROM file('/etc/passwd', LineAsString)": "forbidden_function",
                 "SELECT * FROM remote('h', shop, orders)": "forbidden_function",
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
        self.assertEqual(ast_check("SELECT toYear(order_date) y, count() FROM orders GROUP BY y ORDER BY y "
                                   "LIMIT 3 BY y", POLICIES["sales"]), {"orders"})
        with self.assertRaises(SafetyError):
            ast_check("SELECT email FROM customers", POLICIES["analyst"])

    def test_transpile_completes_group_by(self):
        from t2sql.dialect import to_dialect
        out = to_dialect("SELECT p.name, SUM(oi.quantity) FROM order_items oi JOIN products p "
                         "ON p.product_id = oi.product_id GROUP BY p.product_id HAVING p.unit_price > 1", "clickhouse")
        self.assertIn("GROUP BY p.product_id, p.name, p.unit_price", out)
        out = to_dialect("SELECT strftime('%Y', order_date) AS y, COUNT(*) FROM orders GROUP BY y", "clickhouse")
        self.assertIn("GROUP BY y", out)
        self.assertNotIn("order_date HAVING", out)
        self.assertIn("toYear(order_date) = 2024",
                      to_dialect("SELECT COUNT(*) FROM orders WHERE strftime('%Y', order_date) = '2024'", "clickhouse"))

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


def _ch_url():
    return os.environ.get("T2SQL_TEST_CH_URL") or _dotenv("T2SQL_DATABASE_URL_CLICKHOUSE")


def _ch_available():
    url = _ch_url()
    if not url:
        return False
    try:
        from t2sql.db import make_backend
        return make_backend(url).run("SELECT 1").ok
    except Exception:
        return False


@unittest.skipUnless(_ch_available(), "không kết nối được ClickHouse (docker compose up -d clickhouse)")
class TestClickHouse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from t2sql.db import make_backend
        cls.ch = make_backend(_ch_url(), max_rows=50, timeout_s=1)

    def run_as(self, role, sql):
        return self.ch.run(sql, policy=POLICIES[role])

    def test_schema_introspection(self):
        schema = self.ch.load_schema(DEFAULT_DOCS)
        self.assertEqual(set(schema.tables),
                         {"customers", "suppliers", "products", "orders", "order_items", "reviews"})
        orders = {c.name: c for c in schema.tables["orders"].columns}
        self.assertTrue(orders["order_id"].pk)
        self.assertFalse(orders["order_date"].pk)            # nằm trong ORDER BY của MergeTree nhưng không phải khóa
        self.assertEqual(orders["customer_id"].fk, "customers.customer_id")   # từ "relations" trong docs
        self.assertEqual(orders["order_date"].type, "Date")
        text = schema.render(with_docs=True)
        self.assertIn("status = 4", text)
        self.assertNotIn("@example.com", text)

    def test_role_permissions(self):
        self.assertTrue(self.run_as("analyst", "SELECT name, city FROM customers").ok)
        for sql in ["SELECT email FROM customers", "SELECT * FROM customers"]:
            with self.subTest(sql=sql):
                self.assertEqual(self.run_as("analyst", sql).error_code, "forbidden")
        self.assertEqual(self.run_as("sales", "SELECT count() FROM customers").error_code, "forbidden")
        self.assertEqual(self.run_as("sales", "SELECT count() FROM orders").rows, [(1446,)])

    def test_database_enforces_permissions_even_without_parser_check(self):
        from unittest import mock
        with mock.patch("t2sql.db.clickhouse.ast_check", return_value=set()):
            res = self.run_as("analyst", "SELECT email FROM customers")
            self.assertEqual(res.error_code, "forbidden")
            self.assertIn("Not enough privileges", res.error)
            self.assertEqual(self.run_as("sales", "SELECT count() FROM customers").error_code, "forbidden")
            self.assertEqual(self.run_as("admin", "SELECT * FROM url('http://127.0.0.1:8123/ping', LineAsString)")
                             .error_code, "forbidden")
        for sql in ["INSERT INTO orders (order_id) VALUES (99999)", "ALTER TABLE orders DELETE WHERE 1",
                    "DROP TABLE orders"]:
            with self.subTest(sql=sql):
                self.assertFalse(self.ch.run(sql, safe=False).ok)
        self.assertEqual(self.run_as("admin", "SELECT count() FROM orders").rows[0][0], 1446)

    def test_left_join_returns_null(self):
        """join_use_nulls=1 (profile t2sql_ro): khách chưa có đơn phải ra NULL, không phải 0."""
        res = self.run_as("admin", "SELECT count() FROM customers c LEFT JOIN orders o "
                                   "ON o.customer_id = c.customer_id WHERE o.order_id IS NULL")
        lite = Executor(DEFAULT_DB).run("SELECT COUNT(*) FROM customers c LEFT JOIN orders o "
                                        "ON o.customer_id = c.customer_id WHERE o.order_id IS NULL")
        self.assertEqual(res.rows, lite.rows)

    def test_timeout_and_row_limit(self):
        res = self.run_as("admin", "SELECT count() FROM order_items a, order_items b, order_items c")
        self.assertEqual(res.error_code, "timeout")
        res = self.run_as("admin", "SELECT * FROM order_items")
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.rows), 50)

    def test_gold_and_fewshot_match_sqlite(self):
        from t2sql.db import make_backend
        from t2sql.dialect import example_sql
        lite = Executor(DEFAULT_DB, max_rows=10_000)
        ch = make_backend(_ch_url(), max_rows=10_000, timeout_s=30)
        with open(os.path.join(ROOT, "eval", "fewshot_pool.json"), encoding="utf-8") as f:
            pool = json.load(f)
        for it in [i for i in load_items() if i["sql"]] + pool:
            with self.subTest(q=it["question"]):
                ch_sql = example_sql(it, "clickhouse")
                a, b = lite.run(it["sql"]), ch.run(ch_sql)
                self.assertTrue(b.ok, f"{b.error}: {ch_sql}")
                self.assertTrue(results_match(b.rows, a.rows, it.get("ordered", False)), ch_sql)

    def test_pipeline_end_to_end_and_prompt(self):
        llm = scripted(["SELECT toYear(order_date) AS nam, count() FROM orders GROUP BY nam"])
        ans = TextToSQL(llm, "fewshot", db=_ch_url()).ask("Số đơn theo năm", policy="analyst")
        self.assertTrue(ans.result.ok, ans.result.error)
        self.assertEqual(sum(n for _, n in ans.result.rows), 1446)
        system, user_msg = llm.calls[0][0], llm.calls[0][1][0]["content"]
        self.assertIn("ClickHouse", system)
        self.assertIn("LIMIT N BY", system)
        self.assertNotIn(" email ", system)
        self.assertNotIn("strftime", user_msg)


class TestDatasets(unittest.TestCase):
    """Bộ dữ liệu theo tên database: datasets/<tên>/ hoặc bộ shop mặc định."""

    def test_default_and_einvoice(self):
        from t2sql import datasets
        shop = datasets.for_database("shop")
        self.assertEqual((shop.name, shop.sql_dialect), ("shop", "sqlite"))
        self.assertEqual(set(shop.policies), set(POLICIES))
        self.assertEqual(datasets.for_database(None).name, "shop")
        ev = datasets.for_database("einvoice")
        self.assertEqual((ev.name, ev.sql_dialect), ("einvoice", "clickhouse"))
        self.assertTrue(ev.eval_path.endswith("eval.json") and ev.fewshot_path.endswith("fewshot_pool.json"))
        self.assertIn(("buyers", "email"), ev.policies["analyst"].denied_columns)
        self.assertNotIn("invoices", ev.policies["sales"].allowed_tables)
        self.assertIsNone(ev.policies["admin"].allowed_tables)

    def test_example_sql_keeps_same_dialect(self):
        from t2sql.dialect import example_sql
        sql = "SELECT count() FROM invoices FINAL"
        self.assertEqual(example_sql({"sql": sql}, "clickhouse", source="clickhouse"), sql)
        with self.assertRaises(ValueError):
            example_sql({"sql": sql}, "postgres", source="clickhouse")

    def test_einvoice_files_are_consistent(self):
        from t2sql import datasets
        ev = datasets.for_database("einvoice")
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


def _einvoice_url():
    url = os.environ.get("T2SQL_TEST_EINVOICE_URL") or _dotenv("T2SQL_DATABASE_URL_EINVOICE")
    if not url:
        return ""
    try:
        from t2sql.db import make_backend
        return url if make_backend(url).run("SELECT count() FROM invoice_items").ok else ""
    except Exception:
        return ""


EINVOICE_URL = _einvoice_url()


@unittest.skipUnless(EINVOICE_URL, "chưa có database einvoice (python datasets/einvoice/generate.py)")
class TestEInvoice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from t2sql.db import make_backend
        cls.ch = make_backend(EINVOICE_URL, max_rows=50, timeout_s=30)

    def run_as(self, role, sql):
        from t2sql import datasets
        return self.ch.run(sql, policy=datasets.for_database("einvoice").policies[role])

    def test_final_trap_exists(self):
        """invoices giữ phiên bản cũ: không FINAL thì đếm nhiều hơn (bẫy cố ý của bộ dữ liệu)."""
        raw = self.run_as("admin", "SELECT count() FROM invoices WHERE toYYYYMM(issued_at) = 202401").rows[0][0]
        final = self.run_as("admin", "SELECT count() FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202401").rows[0][0]
        self.assertGreater(raw, final * 1.1)

    def test_role_permissions_app_and_database(self):
        from unittest import mock
        self.assertEqual(self.run_as("analyst", "SELECT email FROM buyers").error_code, "forbidden")
        self.assertTrue(self.run_as("analyst", "SELECT name FROM buyers LIMIT 1").ok)
        self.assertEqual(self.run_as("sales", "SELECT count() FROM invoices").error_code, "forbidden")
        self.assertTrue(self.run_as("sales", "SELECT sum(revenue_vnd) FROM daily_seller_stats WHERE day = toDate('2025-06-02')").ok)
        with mock.patch("t2sql.db.clickhouse.ast_check", return_value=set()):
            self.assertEqual(self.run_as("analyst", "SELECT phone FROM buyers").error_code, "forbidden")
            self.assertEqual(self.run_as("sales", "SELECT count() FROM invoice_items").error_code, "forbidden")

    def test_pipeline_uses_einvoice_dataset(self):
        llm = scripted(["SELECT count() FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202506"])
        pipe = TextToSQL(llm, "fewshot", db=EINVOICE_URL)
        self.assertEqual(pipe.dataset.name, "einvoice")
        ans = pipe.ask("Số hóa đơn lập trong tháng 6/2025", policy="analyst")
        self.assertTrue(ans.result.ok, ans.result.error)
        system, user_msg = llm.calls[0][0], llm.calls[0][1][0]["content"]
        self.assertIn("FINAL", system)
        self.assertIn("toTimeZone", system)
        self.assertNotIn("contact_email", system)          # cột analyst không được đọc bị ẩn khỏi prompt
        self.assertIn("FROM invoices", user_msg)            # few-shot của bộ einvoice, không phải bộ shop
        self.assertNotIn("order_items", user_msg)

    @unittest.skipUnless(os.environ.get("T2SQL_TEST_SLOW"), "đặt T2SQL_TEST_SLOW=1 để chạy toàn bộ SQL chuẩn (~40s)")
    def test_all_gold_and_fewshot_sql_run(self):
        from t2sql import datasets
        from t2sql.db import make_backend
        ev = datasets.for_database("einvoice")
        ch = make_backend(EINVOICE_URL, max_rows=100_000, timeout_s=60)
        with open(ev.eval_path, encoding="utf-8") as f:
            items = json.load(f)
        with open(ev.fewshot_path, encoding="utf-8") as f:
            items += json.load(f)
        for it in items:
            if it.get("sql"):
                with self.subTest(q=it["question"]):
                    res = ch.run(it["sql"], safe=False)
                    self.assertTrue(res.ok, res.error)
                    self.assertTrue(res.rows)


if __name__ == "__main__":
    unittest.main()
