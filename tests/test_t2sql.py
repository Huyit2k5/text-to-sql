"""Unit test (không gọi API).  Chạy:  python -m unittest -v

Các test cần database chạy trên ClickHouse `einvoice` (docker compose up -d clickhouse, rồi
python datasets/einvoice/generate.py); không có thì các test đó bị bỏ qua, còn lại vẫn chạy.
URL lấy từ T2SQL_TEST_CH_URL hoặc T2SQL_DATABASE_URL_EINVOICE trong .env.
Đặt T2SQL_TEST_SLOW=1 để chạy thêm các test quét toàn bộ SQL chuẩn (~1-2 phút).
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


EINVOICE_URL = os.environ.get("T2SQL_TEST_CH_URL") or _dotenv("T2SQL_DATABASE_URL_EINVOICE")
os.environ["T2SQL_DATABASE_URL"] = EINVOICE_URL     # các test pipeline mặc định dùng database einvoice

from t2sql import ROOT, datasets
from t2sql.db import make_backend
from t2sql.evaluation import categorize, results_match
from t2sql.llm import ScriptedLLM
from t2sql.logstore import QueryLogger
from t2sql.pipeline import CONFIGS, Config, TextToSQL
from t2sql.retrieval import FewShotRetriever, SchemaLinker, tables_in_sql
from t2sql.safety import POLICIES, SafetyError, static_check
from t2sql.schema import Schema
from t2sql.sql_utils import extract_sql, parse_response, split_statements
from t2sql.viz import choose_view

SLOW = unittest.skipUnless(os.environ.get("T2SQL_TEST_SLOW"), "đặt T2SQL_TEST_SLOW=1 để chạy (quét toàn bộ SQL chuẩn)")


def ev(max_rows=200, timeout_s=None):
    """Backend ClickHouse cho database einvoice."""
    return make_backend(EINVOICE_URL, max_rows=max_rows, timeout_s=timeout_s)


def _ev_available():
    if not EINVOICE_URL:
        return False
    try:
        return ev().run("SELECT count() FROM invoice_items").ok
    except Exception:
        return False


needs_ev = unittest.skipUnless(_ev_available(), "cần database einvoice (docker compose up -d clickhouse; python datasets/einvoice/generate.py)")
EV = datasets.for_database("einvoice")
POL = EV.policies      # admin / analyst / sales của bộ einvoice


def load_items(name="eval.json"):
    with open(os.path.join(ROOT, "datasets", "einvoice", name), encoding="utf-8") as f:
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


@needs_ev
class TestSafety(unittest.TestCase):
    def setUp(self):
        self.ex = ev(max_rows=50, timeout_s=0.5)

    def test_blocks_write_statements(self):
        for sql in ["DROP TABLE sellers", "DELETE FROM invoices", "UPDATE invoices SET status = 1",
                    "INSERT INTO provinces VALUES ('99', 'x', 'y')", "PRAGMA table_info(invoices)",
                    "ATTACH DATABASE 'x.db' AS x"]:
            with self.subTest(sql=sql):
                self.assertRaises(SafetyError, static_check, sql)
                self.assertFalse(self.ex.run(sql).ok)

    def test_blocks_multi_statement(self):
        res = self.ex.run("SELECT 1; DROP TABLE sellers")
        self.assertEqual(res.error_code, "multi_statement")

    def test_keyword_inside_string_is_allowed(self):
        res = self.ex.run("SELECT COUNT(*) FROM sellers WHERE name LIKE '%DROP TABLE%'")
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.rows[0][0], 0)

    def test_readonly_even_without_static_check(self):
        res = self.ex.run("DELETE FROM provinces", safe=False)
        self.assertFalse(res.ok)
        self.assertGreater(self.ex.run("SELECT COUNT(*) FROM provinces").rows[0][0], 0)

    def test_timeout_on_heavy_query(self):
        res = self.ex.run("SELECT COUNT(*) FROM api_requests a, api_requests b")
        self.assertEqual(res.error_code, "timeout")

    def test_row_limit(self):
        res = self.ex.run("SELECT * FROM sellers")
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.rows), 50)

    def test_table_permission(self):
        res = self.ex.run("SELECT COUNT(*) FROM invoices", policy=POL["sales"])
        self.assertEqual(res.error_code, "forbidden")
        # subquery / CTE cũng bị bắt vì kiểm tra cú pháp thấy mọi bảng được đọc
        res = self.ex.run("WITH x AS (SELECT status FROM invoices LIMIT 5) SELECT * FROM x", policy=POL["sales"])
        self.assertEqual(res.error_code, "forbidden")
        self.assertTrue(self.ex.run("SELECT COUNT(*) FROM sellers", policy=POL["sales"]).ok)

    def test_column_permission(self):
        analyst = POL["analyst"]
        self.assertEqual(self.ex.run("SELECT contact_email FROM sellers", policy=analyst).error_code, "forbidden")
        self.assertEqual(self.ex.run("SELECT * FROM sellers", policy=analyst).error_code, "forbidden")
        self.assertTrue(self.ex.run("SELECT name, tax_code FROM sellers LIMIT 3", policy=analyst).ok)

    def test_pii_masking(self):
        from t2sql.safety import Policy
        res = self.ex.run("SELECT contact_email, contact_phone FROM sellers LIMIT 1", policy=Policy("admin", mask_pii=True))
        email, phone = res.rows[0]
        self.assertIn("***@", email)
        self.assertIn("*", phone)

    def test_system_tables_blocked(self):
        self.assertFalse(self.ex.run("SELECT name FROM system.tables").ok)


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


@needs_ev
class TestDataset(unittest.TestCase):
    def test_eval_sets_are_well_formed(self):
        for name in ("eval.json", "eval_holdout.json"):
            items = load_items(name)
            self.assertEqual(len({i["id"] for i in items}), len(items))
            self.assertGreaterEqual(len([i for i in items if i["sql"]]), 40)
            for it in items:
                if it["sql"]:
                    static_check(it["sql"])
                else:
                    self.assertEqual(it["expect"], "cannot")

    def test_fewshot_pool_does_not_leak(self):
        with open(EV.fewshot_path, encoding="utf-8") as f:
            pool = json.load(f)
        eval_qs = {i["question"] for i in load_items()} | {i["question"] for i in load_items("eval_holdout.json")}
        self.assertGreaterEqual(len(pool), 20)
        for e in pool:
            with self.subTest(q=e["question"]):
                static_check(e["sql"])
                self.assertNotIn(e["question"], eval_qs)

    def test_schema_linking_recall(self):
        schema = ev().load_schema(EV.docs_path)
        schema.requires = {t: set(r) for t, r in EV.docs.get("requires", {}).items()}
        linker = SchemaLinker(schema)
        for name in ("eval.json", "eval_holdout.json"):
            for it in load_items(name):
                if it["sql"]:
                    with self.subTest(id=it["id"]):
                        self.assertTrue(tables_in_sql(it["sql"]) <= set(linker.link(it["question"])))


@needs_ev
class TestSchema(unittest.TestCase):
    def setUp(self):
        self.schema = ev().load_schema(EV.docs_path)

    def test_baseline_has_no_docs(self):
        text = self.schema.render(with_docs=False)
        self.assertIn("TABLE invoices", text)
        self.assertNotIn("FINAL", text)

    def test_docs_contain_business_rules_and_samples(self):
        text = self.schema.render(with_docs=True)
        self.assertIn("FINAL", text)
        self.assertIn("ví dụ:", text)

    def test_no_pii_or_free_text_in_samples(self):
        text = self.schema.render(with_docs=True)
        self.assertNotIn("ketoan.", text)          # email liên hệ của doanh nghiệp
        self.assertNotIn("@gmail.com", text)       # email người mua


def scripted(responses):
    """LLM giả trả lần lượt các phản hồi trong danh sách."""
    it = iter(responses)
    return ScriptedLLM(lambda system, messages: next(it))


@needs_ev
class TestPipeline(unittest.TestCase):
    def test_baseline_end_to_end(self):
        llm = scripted(["```sql\nSELECT COUNT(*) FROM sellers\n```"])
        ans = TextToSQL(llm, "baseline").ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual(ans.kind, "result")
        self.assertEqual(ans.result.rows, [(50000,)])

    def test_sql_error_without_retry_does_not_crash(self):
        ans = TextToSQL(scripted(["SELECT nope FROM sellers"]), "baseline").ask("x")
        self.assertEqual(ans.kind, "result")
        self.assertFalse(ans.result.ok)
        self.assertIn("nope", ans.result.error)

    def test_self_correction_fixes_error(self):
        llm = scripted(["SELECT nope FROM sellers", "SELECT COUNT(*) FROM sellers"])
        ans = TextToSQL(llm, "selfcorrect").ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual(len(ans.attempts), 2)
        self.assertTrue(ans.result.ok)
        # lượt sửa phải chứa thông báo lỗi và SQL cũ
        fix_turn = llm.calls[1][1]
        self.assertEqual(fix_turn[1]["content"], "SELECT nope FROM sellers")
        self.assertIn("nope", fix_turn[2]["content"])

    def test_self_correction_is_bounded(self):
        llm = ScriptedLLM(lambda s, m: "SELECT nope FROM sellers")
        ans = TextToSQL(llm, "selfcorrect").ask("x")
        self.assertEqual(len(ans.attempts), CONFIGS["selfcorrect"].max_retries + 1)

    def test_empty_result_retry_stops_when_sql_repeats(self):
        empty = "SELECT * FROM sellers WHERE company_type = 'Không tồn tại'"
        llm = ScriptedLLM(lambda s, m: empty)
        ans = TextToSQL(llm, "selfcorrect").ask("Doanh nghiệp loại không tồn tại")
        self.assertEqual(len(ans.attempts), 2)  # hỏi lại một lần, model giữ nguyên -> dừng
        self.assertTrue(ans.result.empty)

    def test_injected_second_statement_is_blocked_without_retry(self):
        llm = ScriptedLLM(lambda s, m: "SELECT 1; DROP TABLE sellers")
        ans = TextToSQL(llm, "selfcorrect").ask("x")
        self.assertEqual(ans.result.error_code, "multi_statement")
        self.assertEqual(len(ans.attempts), 1)

    def test_cannot_answer(self):
        ans = TextToSQL(scripted(["CANNOT_ANSWER: Không có dữ liệu thời tiết."]), "baseline").ask("Thời tiết?")
        self.assertEqual(ans.kind, "cannot")

    def test_write_request_refused_before_llm(self):
        llm = ScriptedLLM(lambda s, m: self.fail("không được gọi LLM"))
        ans = TextToSQL(llm, "production").ask("Xóa tất cả hóa đơn nháp")
        self.assertEqual(ans.kind, "refused")

    def test_denied_columns_hidden_from_prompt(self):
        llm = scripted(["SELECT COUNT(*) FROM sellers"])
        TextToSQL(llm, "baseline").ask("Có bao nhiêu doanh nghiệp?", policy="analyst")
        self.assertNotIn(" contact_email ", llm.calls[0][0])
        self.assertIn(" province_code ", llm.calls[0][0])

    def test_role_restricts_schema_in_prompt(self):
        llm = scripted(["SELECT COUNT(*) FROM sellers"])
        ans = TextToSQL(llm, "baseline").ask("Có bao nhiêu doanh nghiệp?", policy="sales")
        self.assertNotIn("TABLE invoices", llm.calls[0][0])
        self.assertTrue(ans.result.ok)

    def test_fewshot_excludes_eval_question(self):
        llm = scripted(["SELECT 1"])
        pool_q = "Có bao nhiêu doanh nghiệp đang dùng ký số HSM?"
        TextToSQL(llm, "fewshot").ask(pool_q, exclude_example=pool_q)
        user_msg = llm.calls[0][1][0]["content"]
        self.assertEqual(user_msg.count(pool_q), 1)  # chỉ xuất hiện ở câu hỏi, không ở ví dụ

    def test_linking_shrinks_prompt(self):
        llm = scripted(["SELECT quantileExact(0.5)(latency_ms) FROM api_requests"])
        ans = TextToSQL(llm, "linking").ask("Độ trễ trung vị của API tạo hóa đơn là bao nhiêu?")
        self.assertIn("api_requests", ans.tables_in_prompt)
        self.assertLess(len(ans.tables_in_prompt), 8)

    def test_multi_turn_rewrite_and_explanation(self):
        def fn(system, messages):
            if "câu hỏi độc lập" in system:
                self.assertIn("năm 2025", messages[0]["content"])
                return "Có bao nhiêu hóa đơn hợp lệ năm 2024?"
            if system.startswith("Bạn giải thích"):
                return "Đếm hóa đơn hợp lệ lập trong tháng 1/2024."
            self.assertIn("năm 2024", messages[0]["content"])
            return ("SELECT count() FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202401 "
                    "AND status IN ('cqt_cap_ma', 'da_gui_cqt', 'bi_dieu_chinh')")
        history = [{"question": "Có bao nhiêu hóa đơn hợp lệ năm 2025?", "sql": "SELECT ..."}]
        ans = TextToSQL(ScriptedLLM(fn), "production").ask("Còn năm 2024 thì sao?", history=history)
        self.assertEqual(ans.standalone_question, "Có bao nhiêu hóa đơn hợp lệ năm 2024?")
        self.assertTrue(ans.result.ok)
        self.assertTrue(ans.explanation)

    def test_clarify(self):
        ans = TextToSQL(scripted(["CLARIFY: Tốt nhất theo số hóa đơn, doanh thu hay số người mua?"]),
                        "production").ask("Doanh nghiệp nào tốt nhất?")
        self.assertEqual(ans.kind, "clarify")
        self.assertIn("doanh thu", ans.message)

    def test_logging_and_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            logger = QueryLogger(os.path.join(d, "q.jsonl"))
            pipe = TextToSQL(scripted(["SELECT COUNT(*) FROM sellers"]), "baseline", logger=logger)
            ans = pipe.ask("Có bao nhiêu doanh nghiệp?")
            logger.feedback(ans.id, True)
            self.assertEqual(logger.verified_examples(),
                             [{"question": "Có bao nhiêu doanh nghiệp?", "sql": "SELECT COUNT(*) FROM sellers"}])


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

    @needs_ev
    def test_end_to_end_with_think_block(self):
        from t2sql.llm import OpenAICompatLLM
        llm = OpenAICompatLLM(model="SDS-AI/softdream", base_url=self.url, api_key="k")
        ans = TextToSQL(llm, "baseline").ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual(ans.result.rows, [(50000,)])
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

    @needs_ev
    @SLOW
    def test_no_false_positive_on_gold(self):
        """Điều kiện bắt buộc: SQL chuẩn (bộ dev + held-out) không bị báo nghi vấn."""
        from t2sql.checks import check_result
        ex = ev(max_rows=10_000, timeout_s=60)
        for name in ("eval.json", "eval_holdout.json"):
            for it in load_items(name):
                if it["sql"]:
                    with self.subTest(id=it["id"]):
                        res = ex.run(it["sql"])
                        self.assertEqual(check_result(it["question"], res.columns, res.rows), [])


H06_Q = "Trong mỗi kênh bán, gói dịch vụ nào có doanh thu bán cao nhất? Cho biết kênh, tên gói và doanh thu."
H06_BAD = ("SELECT s.channel, p.name, sum(s.amount_vnd) AS dt FROM subscriptions AS s JOIN service_plans AS p ON p.plan_id = s.plan_id "
           "WHERE s.payment_status = 'da_thanh_toan' GROUP BY s.channel, p.name ORDER BY s.channel, dt DESC")
H06_GOOD = H06_BAD + " LIMIT 1 BY s.channel"


@needs_ev
class TestShapeCheckPipeline(unittest.TestCase):
    def test_suspicious_result_is_sent_back_and_fixed(self):
        llm = scripted([H06_BAD, H06_GOOD])
        ans = TextToSQL(llm, "shapecheck").ask(H06_Q)
        self.assertEqual(len(ans.attempts), 2)
        self.assertEqual(ans.attempts[0].issues, ["R2"])
        self.assertIn("lặp lại", llm.calls[1][1][-1]["content"])   # phản hồi gửi model có mô tả nghi vấn
        self.assertEqual(len(ans.result.rows), 3)     # 3 kênh bán, mỗi kênh một gói
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
        llm = scripted(["SELECT 1 AS trung_binh", "SELECT AVG(amount_vnd) FROM subscriptions"])
        ans = TextToSQL(llm, "shapecheck").ask("Trung bình mỗi đơn mua gói thu bao nhiêu tiền?")
        self.assertEqual(ans.attempts[0].issues, ["R0"])
        self.assertIn("FROM", llm.calls[1][1][-1]["content"])
        self.assertEqual(ans.sql, "SELECT AVG(amount_vnd) FROM subscriptions")


@needs_ev
class TestImprovements(unittest.TestCase):
    """Danh mục, chặn truy vấn nặng, tự soát logic, reasoning cho câu khó (cấu hình lookup / costguard / verify / reasoning)."""

    def cfg(self, **kw):
        base = dict(use_docs=True, use_linking=True, max_retries=3, shape_check=True)
        base.update(kw)
        return Config("test", **base)

    def test_lookup_tables_and_value_linking(self):
        llm = scripted(["SELECT count() FROM sellers WHERE province_code = '48'"])
        pipe = TextToSQL(llm, self.cfg(lookup_tables=True))
        self.assertIn("provinces", pipe.lookups)
        ans = pipe.ask("Có bao nhiêu doanh nghiệp ở Đà Nẵng?")
        self.assertIn("provinces", ans.tables_in_prompt)
        system = llm.calls[0][0]
        self.assertIn("DANH MỤC ĐẦY ĐỦ", system)
        self.assertIn("Đà Nẵng", system)

    def test_cost_guard_asks_for_cheaper_sql_before_running(self):
        from unittest import mock
        heavy, light = "SELECT SUM(amount_vnd) FROM subscriptions", "SELECT SUM(amount_vnd) FROM subscriptions WHERE subscription_id < 100"
        llm = scripted([heavy, light])
        pipe = TextToSQL(llm, self.cfg(cost_guard=True, cost_guard_rows=1000))
        est = lambda sql, policy=None: (5000, {"subscriptions": 5000}) if sql == heavy else (10, {"subscriptions": 10})
        with mock.patch.object(pipe.backend, "estimate_rows", side_effect=est), \
                mock.patch.object(pipe.backend, "run", wraps=pipe.backend.run) as run:
            ans = pipe.ask("Tổng tiền các đơn mua gói đầu tiên")
        self.assertEqual([a.estimated_rows for a in ans.attempts], [5000, None])
        self.assertEqual([c.args[0] for c in run.call_args_list], [light])   # SQL nặng không được chạy
        self.assertIn("dự kiến đọc khoảng 5,000 dòng", llm.calls[1][1][-1]["content"])

    def test_cost_guard_accepts_repeated_sql(self):
        from unittest import mock
        heavy = "SELECT SUM(amount_vnd) FROM subscriptions"
        pipe = TextToSQL(scripted([heavy, heavy]), self.cfg(cost_guard=True, cost_guard_rows=1000))
        with mock.patch.object(pipe.backend, "estimate_rows", return_value=(5000, {"subscriptions": 5000})):
            ans = pipe.ask("Tổng tiền các đơn mua gói")
        self.assertTrue(ans.result.ok)
        self.assertEqual(len(ans.attempts), 2)

    def test_semantic_check_sends_reason_back(self):
        bad = "SELECT seller_id, SUM(amount_vnd) FROM subscriptions GROUP BY seller_id ORDER BY 2 DESC LIMIT 1"
        good = "SELECT subscription_id, amount_vnd FROM subscriptions ORDER BY amount_vnd DESC LIMIT 1"
        llm = scripted([bad, "SAI: câu hỏi cần một đơn, không phải tổng theo doanh nghiệp", good])
        ans = TextToSQL(llm, self.cfg(semantic_check=True)).ask("Đơn mua gói có số tiền lớn nhất?")
        self.assertEqual(ans.sql, good)
        self.assertEqual(ans.attempts[0].verdict, "câu hỏi cần một đơn, không phải tổng theo doanh nghiệp")
        self.assertIn("QUY TẮC NGHIỆP VỤ", llm.calls[1][1][0]["content"])      # lời gọi soát lỗi
        self.assertIn("không phải tổng theo doanh nghiệp", llm.calls[2][1][-1]["content"])
        self.assertEqual(len(llm.calls), 3)          # chỉ soát một lần mỗi chuỗi

    def test_semantic_check_ok_keeps_sql(self):
        sql = "SELECT COUNT(*) FROM sellers"
        llm = scripted([sql, "OK"])
        ans = TextToSQL(llm, self.cfg(semantic_check=True)).ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual((ans.sql, len(llm.calls), ans.attempts[0].verdict), (sql, 2, None))

    def test_reasoning_only_for_hard_questions(self):
        from t2sql.pipeline import looks_hard
        self.assertTrue(looks_hard("Doanh thu tháng 6 tăng bao nhiêu phần trăm so với tháng 5?", 2))
        self.assertFalse(looks_hard("Có bao nhiêu doanh nghiệp ở Hà Nội?", 5))
        llm = scripted(["SELECT COUNT(*) FROM sellers", "SELECT 100.0 * countIf(status = 'closed') / count() FROM sellers"])
        pipe = TextToSQL(llm, self.cfg(reasoning_hard="medium"))
        self.assertIsNone(pipe.ask("Có bao nhiêu doanh nghiệp?").reasoning)
        self.assertEqual(pipe.ask("Tỷ lệ doanh nghiệp đã ngừng dịch vụ là bao nhiêu phần trăm?").reasoning, "medium")
        self.assertEqual(llm.reasoning_levels, [None, "medium"])


@needs_ev
class TestReviewFixes(unittest.TestCase):
    """Hồi quy cho các lỗi tìm thấy khi review."""

    def test_tables_in_sql_handles_quotes_and_schema_prefix(self):
        self.assertEqual(tables_in_sql('SELECT 1 FROM "orders"'), {"orders"})
        self.assertEqual(tables_in_sql("SELECT 1 FROM `invoices` FINAL"), {"invoices"})
        self.assertEqual(tables_in_sql('SELECT 1 FROM einvoice.invoices o JOIN "einvoice"."sellers" c ON 1'), {"invoices", "sellers"})
        self.assertEqual(tables_in_sql("SELECT 1"), set())

    def test_percent_with_a_space_after_a_number_is_still_a_filter_value(self):
        from t2sql.checks import _PERCENT
        for q in ("thuế suất 5%", "thuế suất 5 %", "giảm 10,5 %"):
            self.assertFalse(_PERCENT.search(q), q)
        for q in ("tỷ lệ % hóa đơn", "chiếm bao nhiêu %", "phần trăm hóa đơn"):
            self.assertTrue(_PERCENT.search(q), q)

    def test_rename_as_an_alias_is_allowed_but_rename_statement_is_not(self):
        self.assertEqual(static_check("SELECT 1 AS rename"), "SELECT 1 AS rename")
        for sql in ("RENAME TABLE a TO b", "SELECT 1; RENAME TABLE a TO b"):
            self.assertRaises(SafetyError, static_check, sql)

    def test_database_choices_keeps_two_servers_with_the_same_database_name(self):
        import importlib.util, os, sys
        from unittest import mock
        src = open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8").read()
        start = src.index("def database_choices")
        ns = {"os": os}
        exec(src[start:src.index("@st.cache_resource")], ns)
        env = {"T2SQL_DATABASE_URL": "clickhouse://u:p@a.local:8123/einvoice",
               "T2SQL_DATABASE_URL_B": "clickhouse://u:p@b.local:8123/einvoice"}
        with mock.patch.dict(os.environ, env, clear=True):
            out = ns["database_choices"]()
        self.assertEqual(len(out), 2)
        self.assertTrue(all("p@" not in k and ":p" not in k for k in out), list(out))

    @needs_ev
    def test_cost_limit_comes_from_dataset_docs_unless_env_overrides(self):
        from unittest import mock
        docs = dict(EV.docs, cost_guard_rows=123)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schema_docs.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(docs, f)
            env = {k: v for k, v in os.environ.items() if k != "T2SQL_MAX_ESTIMATED_ROWS"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(TextToSQL(scripted(["SELECT 1"]), "costguard", db=EINVOICE_URL, docs_path=path).cost_limit, 123)
                self.assertEqual(TextToSQL(scripted(["SELECT 1"]), "costguard", db=EINVOICE_URL).cost_limit, 40_000_000)
            with mock.patch.dict(os.environ, {"T2SQL_MAX_ESTIMATED_ROWS": "7"}):
                self.assertEqual(TextToSQL(scripted(["SELECT 1"]), "costguard", db=EINVOICE_URL, docs_path=path).cost_limit, 7)

    @needs_ev
    def test_missing_fewshot_pool_runs_without_examples(self):
        pipe = TextToSQL(scripted(["SELECT count() FROM sellers"]), "history", db=EINVOICE_URL,
                         fewshot_path="khong_ton_tai.json")
        self.assertIsNone(pipe.retriever)
        self.assertEqual(pipe.ask("Có bao nhiêu doanh nghiệp?").kind, "result")

    def test_quoted_table_is_not_flagged_as_missing_from(self):
        ans = TextToSQL(scripted(['SELECT COUNT(*) FROM "sellers"']), "shapecheck").ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual(ans.attempts[0].issues, [])
        self.assertEqual(len(ans.attempts), 1)

    def test_verifier_failure_keeps_good_result(self):
        from t2sql.llm import LLMError
        outs = iter(["SELECT COUNT(*) FROM sellers"])

        def fn(system, messages):
            if system.startswith("Bạn là người soát lỗi"):
                raise LLMError("hết thời gian chờ")
            return next(outs)
        ans = TextToSQL(ScriptedLLM(fn), Config("t", use_docs=True, max_retries=2, semantic_check=True)).ask("Có bao nhiêu doanh nghiệp?")
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
        res = TextToSQL(scripted(["SELECT 1 FROM orders"]), "docs").executor.run("SELECT COUNT(*) FROM sellers", policy=d.policies["locked"])
        self.assertEqual(res.error_code, "forbidden")


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


@needs_ev
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
        good = "SELECT COUNT(*) FROM sellers"
        llm = self.by_temperature("SELECT COUNT(*) FROM provinces", good, "SELECT COUNT(seller_id) FROM sellers")
        ans = TextToSQL(llm, self.cfg(early_stop=False)).ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual(ans.result.rows[0][0], 50000)
        self.assertEqual(ans.agreement, "2/3")
        self.assertEqual(sorted(t is None for t in llm.seen), [False, False, True])

    def test_early_stop_when_first_two_agree(self):
        llm = self.by_temperature("SELECT COUNT(*) FROM sellers", "SELECT COUNT(seller_id) FROM sellers", "SELECT 1")
        ans = TextToSQL(llm, self.cfg()).ask("Có bao nhiêu doanh nghiệp?")
        self.assertEqual(len(llm.seen), 2)
        self.assertEqual(ans.agreement, "2/2")

    def test_failed_candidates_do_not_vote(self):
        llm = self.by_temperature("SELECT nope FROM sellers", "SELECT COUNT(*) FROM sellers", "SELECT nope2 FROM x")
        cfg = self.cfg(early_stop=False, max_retries=0)
        ans = TextToSQL(llm, cfg).ask("Có bao nhiêu doanh nghiệp?")
        self.assertTrue(ans.result.ok)
        self.assertEqual(ans.agreement, "1/3")

    def test_flagged_candidate_loses_to_clean_one(self):
        llm = self.by_temperature(H06_BAD, H06_GOOD, H06_BAD)
        cfg = self.cfg(early_stop=False, max_retries=0, shape_check=True)
        ans = TextToSQL(llm, cfg).ask(H06_Q)
        self.assertEqual(len(ans.result.rows), 3)
        self.assertEqual([c["winner"] for c in ans.candidates], [False, True, False])

    def test_refusals_vote_together(self):
        llm = self.by_temperature("CANNOT_ANSWER: không có dữ liệu", "CANNOT_ANSWER: không có", "SELECT 1")
        ans = TextToSQL(llm, self.cfg()).ask("Thời tiết hôm nay?")
        self.assertEqual(ans.kind, "cannot")
        self.assertEqual(ans.agreement, "2/2")


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
        demo = ClickHouseBackend("clickhouse://t2sql:x@127.0.0.1:8123/einvoice")
        self.assertEqual(demo.username(POL["analyst"]), "t2sql_analyst")

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

    def test_ast_check_blocks_clickhouse_specific_risks(self):
        from t2sql.db.clickhouse import ast_check
        cases = {"SELECT * FROM url('http://x/a.csv', CSV)": "forbidden_function",
                 "SELECT * FROM file('/etc/passwd', LineAsString)": "forbidden_function",
                 "SELECT * FROM remote('h', einvoice, invoices)": "forbidden_function",
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
        self.assertEqual(ast_check("SELECT toYear(purchased_at) y, count() FROM subscriptions GROUP BY y ORDER BY y "
                                   "LIMIT 3 BY y", POL["sales"]), {"subscriptions"})
        with self.assertRaises(SafetyError):
            ast_check("SELECT contact_email FROM sellers", POL["analyst"])

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
        ev_ds = datasets.for_database("einvoice")
        self.assertEqual((ev_ds.name, ev_ds.sql_dialect), ("einvoice", "clickhouse"))
        self.assertTrue(ev_ds.eval_path.endswith("eval.json") and ev_ds.fewshot_path.endswith("fewshot_pool.json"))
        self.assertIn(("buyers", "email"), ev_ds.policies["analyst"].denied_columns)
        self.assertNotIn("invoices", ev_ds.policies["sales"].allowed_tables)
        self.assertIsNone(ev_ds.policies["admin"].allowed_tables)

    def test_default_policies_only_admin(self):
        self.assertEqual(set(POLICIES), {"admin"})

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


@needs_ev
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

    def test_schema_introspection(self):
        schema = ev().load_schema(EV.docs_path)
        self.assertEqual(len(schema.tables), 15)
        invoices = {c.name: c for c in schema.tables["invoices"].columns}
        self.assertTrue(invoices["invoice_id"].pk)
        self.assertFalse(invoices["issued_at"].pk)        # nằm trong khóa phân vùng / sắp xếp nhưng không phải khóa chính
        self.assertEqual(invoices["seller_id"].fk, "sellers.seller_id")       # từ "relations" trong docs
        self.assertEqual(invoices["issued_at"].type, "DateTime('Asia/Ho_Chi_Minh')")
        self.assertIn("FINAL", schema.render(with_docs=True))

    def test_left_join_returns_null(self):
        """join_use_nulls=1 (profile t2sql_ro): doanh nghiệp chưa mua gói phải ra NULL, không phải 0."""
        res = self.run_as("admin", "SELECT count() FROM sellers s LEFT JOIN subscriptions x ON x.seller_id = s.seller_id "
                                   "WHERE x.subscription_id IS NULL")
        self.assertEqual(res.rows, [(27,)])

    def test_timeout_and_row_limit(self):
        quick = make_backend(EINVOICE_URL, max_rows=50, timeout_s=1)
        res = quick.run("SELECT count() FROM api_requests a, api_requests b")
        self.assertEqual(res.error_code, "timeout")
        res = quick.run("SELECT * FROM sellers")
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.rows), 50)

    def test_database_rejects_writes_and_table_functions(self):
        for sql in ["INSERT INTO provinces (province_code) VALUES ('99')", "ALTER TABLE provinces DELETE WHERE 1", "DROP TABLE provinces"]:
            with self.subTest(sql=sql):
                self.assertFalse(self.ch.run(sql, safe=False).ok)
        from unittest import mock
        with mock.patch("t2sql.db.clickhouse.ast_check", return_value=set()):
            res = self.run_as("admin", "SELECT * FROM url('http://127.0.0.1:8123/ping', LineAsString)")
            self.assertEqual(res.error_code, "forbidden")
        self.assertEqual(self.run_as("admin", "SELECT count() FROM provinces").rows[0][0], 63)

    def test_pipeline_uses_einvoice_dataset(self):
        llm = scripted(["SELECT count() FROM invoices FINAL WHERE toYYYYMM(issued_at) = 202506"])
        pipe = TextToSQL(llm, "fewshot", db=EINVOICE_URL)
        self.assertEqual(pipe.dataset.name, "einvoice")
        ans = pipe.ask("Số hóa đơn lập trong tháng 6/2025", policy="analyst")
        self.assertTrue(ans.result.ok, ans.result.error)
        system, user_msg = llm.calls[0][0], llm.calls[0][1][0]["content"]
        self.assertIn("FINAL", system)
        self.assertIn("toTimeZone", system)
        self.assertIn("ClickHouse", system)
        self.assertIn("LIMIT N BY", system)
        self.assertNotIn("contact_email", system)          # cột analyst không được đọc bị ẩn khỏi prompt
        self.assertIn("FROM invoices", user_msg)            # few-shot của bộ einvoice
        self.assertNotIn("strftime", user_msg)

    @SLOW
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
