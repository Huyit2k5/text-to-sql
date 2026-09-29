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
        for line in open(path, encoding="utf-8-sig"):
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

        def complete(system, messages, max_tokens=16000, temperature=None):
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


if __name__ == "__main__":
    unittest.main()
