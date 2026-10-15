"""Test chạy trên ClickHouse thật của công ty (database hddt). Chỉ đọc; LLM là bản giả (ScriptedLLM), không gọi API.

  python -m unittest -v tests.test_hddt_live

Cần T2SQL_DATABASE_URL (môi trường hoặc .env) trỏ tới database hddt; không có thì cả file bị bỏ qua.
Mọi truy vấn đều có lọc ngày hẹp hoặc LIMIT để nhẹ với server dùng chung. Đặt T2SQL_TEST_SLOW=1 để chạy thêm
test chạy toàn bộ SQL chuẩn và SQL few-shot (~1-2 phút). Thông báo lỗi không in dữ liệu thật.
"""
import json
import os
import tempfile
import unittest
from unittest import mock


def _dotenv(key):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                if line.strip().startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    return ""


URL = os.environ.get("T2SQL_DATABASE_URL") or _dotenv("T2SQL_DATABASE_URL")
if URL:
    os.environ["T2SQL_DATABASE_URL"] = URL

from t2sql import datasets  # noqa: E402
from t2sql.db import make_backend  # noqa: E402
from t2sql.llm import ScriptedLLM  # noqa: E402
from t2sql.logstore import QueryLogger  # noqa: E402
from t2sql.pipeline import CONFIGS, Config, TextToSQL  # noqa: E402
from t2sql.retrieval import SchemaLinker, tables_in_sql  # noqa: E402
from t2sql.safety import Policy, SafetyError, static_check  # noqa: E402

SLOW = unittest.skipUnless(os.environ.get("T2SQL_TEST_SLOW"), "đặt T2SQL_TEST_SLOW=1 để chạy (chạy toàn bộ SQL chuẩn)")


def _available():
    if not URL or "/hddt" not in URL:
        return False
    try:
        return make_backend(URL).run("SELECT 1").ok
    except Exception:
        return False


needs_hddt = unittest.skipUnless(_available(), "cần T2SQL_DATABASE_URL trỏ tới ClickHouse hddt")
DS = datasets.for_database("hddt")
POL = DS.policies

# Một tháng, một ngày: đủ nhỏ để chạy nhanh mà vẫn có dữ liệu.
MONTH = "ArisingDate >= '2025-03-01' AND ArisingDate < '2025-04-01'"
ONE_DAY = "ArisingDate >= '2025-03-03' AND ArisingDate < '2025-03-04'"
COUNT_MONTH = f"SELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0 AND {MONTH}"


def load_items(name="eval.json"):
    with open(os.path.join(os.path.dirname(DS.eval_path), name), encoding="utf-8") as f:
        return json.load(f)


def scripted(responses):
    """LLM giả trả lần lượt các phản hồi trong danh sách."""
    it = iter(responses)
    return ScriptedLLM(lambda system, messages: next(it))


@needs_hddt
class TestSafetyLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ex = make_backend(URL, max_rows=50, timeout_s=10)

    def test_blocks_write_statements(self):
        for sql in ["DROP TABLE VATInvoice", "DELETE FROM VATInvoice WHERE 1", "UPDATE VATInvoice SET Amount = 0",
                    "INSERT INTO ProductInv VALUES (1)", "ALTER TABLE VATInvoice DELETE WHERE 1",
                    "ATTACH TABLE x", "TRUNCATE TABLE ProductInv", "CREATE TABLE t (a Int8) ENGINE = Memory"]:
            with self.subTest(sql=sql):
                self.assertRaises(SafetyError, static_check, sql)
                self.assertFalse(self.ex.run(sql).ok)

    def test_blocks_multi_statement(self):
        self.assertEqual(self.ex.run("SELECT 1; DROP TABLE VATInvoice").error_code, "multi_statement")

    def test_keyword_inside_string_is_allowed(self):
        res = self.ex.run(f"SELECT count() FROM VATInvoice FINAL WHERE ComName LIKE '%DROP TABLE%' AND {ONE_DAY}")
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.rows[0][0], 0)

    def test_account_cannot_write_even_without_app_checks(self):
        """Lớp cuối: tài khoản chỉ có SELECT. Bỏ qua kiểm tra của app (safe=False) thì database vẫn từ chối."""
        before = self.ex.run(COUNT_MONTH).rows[0][0]
        for sql in ["DELETE FROM VATInvoice_local WHERE 1", "ALTER TABLE VATInvoice_local DELETE WHERE 1",
                    "DROP TABLE ProductInv", "INSERT INTO ProductInv SELECT * FROM ProductInv LIMIT 0",
                    "CREATE TABLE t_t2sql_test (a Int8) ENGINE = Memory"]:
            with self.subTest(sql=sql):
                self.assertFalse(self.ex.run(sql, safe=False).ok)
        self.assertEqual(self.ex.run(COUNT_MONTH).rows[0][0], before)

    def test_row_limit(self):
        res = self.ex.run(f"SELECT id FROM VATInvoice WHERE {MONTH}")
        self.assertTrue(res.ok, res.error)
        self.assertTrue(res.truncated)
        self.assertEqual(len(res.rows), 50)

    def test_table_functions_and_system_tables_blocked(self):
        for sql in ["SELECT name FROM system.tables", "SELECT * FROM url('http://127.0.0.1:8123/ping', LineAsString)",
                    "SELECT * FROM file('/etc/passwd', LineAsString)", "SELECT count() FROM numbers(1000000000)",
                    "SELECT * FROM remote('127.0.0.1', hddt, VATInvoice)"]:
            with self.subTest(sql=sql):
                self.assertFalse(self.ex.run(sql).ok)

    def test_cannot_set_own_settings_or_format(self):
        for sql in [f"{COUNT_MONTH} SETTINGS max_execution_time = 1000", f"{COUNT_MONTH} FORMAT JSON"]:
            with self.subTest(sql=sql):
                self.assertEqual(self.ex.run(sql).error_code, "forbidden_keyword")

    def test_table_permission(self):
        only_products = Policy("only_products", allowed_tables={"ProductInv"})
        for sql in ["SELECT count() FROM VATInvoice", "SELECT count() FROM VATInvoice_local",
                    "WITH x AS (SELECT id FROM VATInvoice LIMIT 5) SELECT * FROM x"]:        # CTE cũng bị bắt
            with self.subTest(sql=sql):
                self.assertEqual(self.ex.run(sql, policy=only_products).error_code, "forbidden")
        self.assertTrue(self.ex.run("SELECT count() FROM ProductInv WHERE InvArisingDate >= '2025-03-03' "
                                    "AND InvArisingDate < '2025-03-04'", policy=only_products).ok)
        self.assertEqual(self.ex.run("SELECT 1 FROM ProductInv", policy=Policy("none", allowed_tables=set())).error_code,
                         "forbidden")

    def test_column_permission(self):
        analyst = POL["analyst"]
        for sql in ["SELECT CusPhone FROM VATInvoice", "SELECT cusphone FROM vatinvoice", "SELECT * FROM VATInvoice",
                    "SELECT count() FROM VATInvoice WHERE CusEmails != ''",
                    "WITH x AS (SELECT CusAddress FROM VATInvoice LIMIT 1) SELECT * FROM x"]:
            with self.subTest(sql=sql):
                self.assertEqual(self.ex.run(sql, policy=analyst).error_code, "forbidden")
        ok = self.ex.run(f"SELECT ComName, Amount FROM VATInvoice WHERE {ONE_DAY} LIMIT 3", policy=analyst)
        self.assertTrue(ok.ok, ok.error)
        # admin (không che PII) đọc được cột bị chặn của analyst
        self.assertTrue(self.ex.run(f"SELECT CusPhone FROM VATInvoice WHERE {ONE_DAY} LIMIT 1", policy=POL["admin"]).ok)

    def test_database_enforces_column_permission_when_app_check_is_bypassed(self):
        """Phân quyền cột do app thực hiện (tài khoản dùng chung): bỏ lớp app thì vai trò analyst không còn bị chặn.
        Test này ghi lại đúng thực tế đó để không ai tưởng database tự chặn; muốn chặn thật cần GRANT theo cột."""
        with mock.patch("t2sql.db.clickhouse.ast_check", return_value=set()):
            res = self.ex.run(f"SELECT CusPhone FROM VATInvoice WHERE {ONE_DAY} LIMIT 1", policy=POL["analyst"])
        self.assertTrue(res.ok, res.error)

    def test_pii_masking(self):
        res = self.ex.run(f"SELECT CusEmails FROM VATInvoice WHERE CusEmails LIKE '%@%' AND {MONTH} LIMIT 5",
                          policy=Policy("admin", mask_pii=True))
        self.assertTrue(res.ok, res.error)
        if not res.rows:
            self.skipTest("không có hóa đơn nào có email trong tháng thử")
        for (email,) in res.rows:
            self.assertIn("***@", email)


@needs_hddt
class TestHddtDataLive(unittest.TestCase):
    """Những điều kiện dữ liệu mà quy tắc trong schema_docs.json dựa vào."""

    @classmethod
    def setUpClass(cls):
        cls.ex = make_backend(URL, max_rows=50, timeout_s=30)

    def test_final_is_needed(self):
        """Bảng giữ nhiều phiên bản: bỏ FINAL thì đếm nhiều hơn hoặc bằng (đúng khi có bản ghi chưa gộp)."""
        raw = self.ex.run(f"SELECT count() FROM VATInvoice WHERE {MONTH}").rows[0][0]
        final = self.ex.run(f"SELECT count() FROM VATInvoice FINAL WHERE {MONTH}").rows[0][0]
        self.assertGreaterEqual(raw, final)
        self.assertGreater(final, 0)

    def test_amount_equals_total_plus_vat(self):
        res = self.ex.run(f"SELECT countIf(abs(Amount - (Total + VATAmount)) > 0.01), count() FROM VATInvoice FINAL "
                          f"WHERE is_deleted = 0 AND {ONE_DAY}")
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.rows[0][0], 0)

    def test_join_invoice_to_lines(self):
        res = self.ex.run("SELECT count() FROM VATInvoice AS i FINAL JOIN ProductInv AS p FINAL "
                          "ON i.ComID = p.ComID AND i.id = p.InvID "
                          "WHERE i.is_deleted = 0 AND p.is_deleted = 0 AND i.ArisingDate >= '2025-03-03' "
                          "AND i.ArisingDate < '2025-03-04' AND p.InvArisingDate >= '2025-03-03' "
                          "AND p.InvArisingDate < '2025-03-04'")
        self.assertTrue(res.ok, res.error)
        self.assertGreater(res.rows[0][0], 0)

    def test_schema_introspection(self):
        schema = make_backend(URL).load_schema(DS.docs_path)
        self.assertEqual(set(schema.tables), {"VATInvoice", "ProductInv"})      # bảng *_local bị loại (exclude_tables)
        cols = {c.name: c for c in schema.tables["VATInvoice"].columns}
        self.assertIn("ArisingDate", cols)
        self.assertIn("Decimal", cols["Amount"].type)
        text = schema.render(with_docs=True)
        self.assertIn("FINAL", text)
        self.assertIn("is_deleted", text)

    def test_samples_skip_personal_columns(self):
        schema = make_backend(URL).load_schema(DS.docs_path)
        personal = {c for t, c in POL["analyst"].denied_columns}
        for c in schema.tables["VATInvoice"].columns:
            if c.name in personal:
                with self.subTest(column=c.name):
                    self.assertFalse(c.samples, "cột cá nhân không được lấy giá trị mẫu")

    def test_left_join_returns_null(self):
        """Hóa đơn không có dòng hàng phải ra NULL (không phải 0) khi LEFT JOIN."""
        res = self.ex.run("SELECT countIf(p.InvID IS NULL), count() FROM VATInvoice AS i FINAL "
                          "LEFT JOIN (SELECT ComID, InvID FROM ProductInv FINAL WHERE is_deleted = 0 "
                          "AND InvArisingDate >= '2025-03-03' AND InvArisingDate < '2025-03-04') AS p "
                          "ON i.ComID = p.ComID AND i.id = p.InvID "
                          "WHERE i.is_deleted = 0 AND i.ArisingDate >= '2025-03-03' AND i.ArisingDate < '2025-03-04'")
        self.assertTrue(res.ok, res.error)
        self.assertGreater(res.rows[0][0], 0)         # có hóa đơn không có dòng hàng, và đếm ra số dương (không bị 0 thay NULL)

    @SLOW
    def test_all_gold_and_fewshot_sql_run(self):
        ch = make_backend(URL, max_rows=100_000, timeout_s=60)
        items = load_items() + load_items("eval_holdout.json") + load_items("eval_paraphrase.json")
        with open(DS.fewshot_path, encoding="utf-8") as f:
            items += json.load(f)
        for it in items:
            if it.get("sql"):
                with self.subTest(id=it.get("id", it["question"][:40])):
                    res = ch.run(it["sql"], safe=False)
                    self.assertTrue(res.ok, res.error)


@needs_hddt
class TestDatasetLive(unittest.TestCase):
    def test_gold_sql_passes_static_check_and_ids_are_unique(self):
        for name in ("eval.json", "eval_holdout.json"):
            items = load_items(name)
            self.assertEqual(len({i["id"] for i in items}), len(items))
            for it in items:
                if it["sql"]:
                    static_check(it["sql"])
                else:
                    self.assertEqual(it["expect"], "cannot")

    def test_schema_linking_recall(self):
        schema = make_backend(URL).load_schema(DS.docs_path)
        schema.requires = {t: set(r) for t, r in DS.docs.get("requires", {}).items()}
        linker = SchemaLinker(schema)
        for name in ("eval.json", "eval_holdout.json"):
            for it in load_items(name):
                if it["sql"]:
                    with self.subTest(id=it["id"]):
                        linked = {t.lower() for t in linker.link(it["question"])}      # tables_in_sql trả tên chữ thường
                        self.assertTrue(tables_in_sql(it["sql"]) <= linked)


@needs_hddt
class TestPipelineLive(unittest.TestCase):
    def test_baseline_end_to_end(self):
        ans = TextToSQL(scripted([f"```sql\n{COUNT_MONTH}\n```"]), "baseline", db=URL).ask("Có bao nhiêu hóa đơn tháng 3/2025?")
        self.assertEqual(ans.kind, "result")
        self.assertTrue(ans.result.ok, ans.result.error)
        self.assertGreater(ans.result.rows[0][0], 0)

    def test_pipeline_uses_hddt_dataset(self):
        llm = scripted([COUNT_MONTH])
        pipe = TextToSQL(llm, "fewshot", db=URL)
        self.assertEqual(pipe.dataset.name, "hddt")
        ans = pipe.ask("Số hóa đơn lập trong tháng 3/2025", policy="analyst")
        self.assertTrue(ans.result.ok, ans.result.error)
        system, user_msg = llm.calls[0][0], llm.calls[0][1][0]["content"]
        self.assertIn("FINAL", system)
        self.assertIn("ClickHouse", system)
        self.assertNotIn(" CusPhone ", system)           # cột analyst không được đọc bị ẩn khỏi prompt
        self.assertIn("VATInvoice", user_msg)             # few-shot của bộ hddt

    def test_sql_error_without_retry_does_not_crash(self):
        ans = TextToSQL(scripted(["SELECT nope FROM VATInvoice"]), "baseline", db=URL).ask("x")
        self.assertEqual(ans.kind, "result")
        self.assertFalse(ans.result.ok)
        self.assertIn("nope", ans.result.error)

    def test_self_correction_fixes_error(self):
        llm = scripted(["SELECT nope FROM VATInvoice", COUNT_MONTH])
        ans = TextToSQL(llm, "selfcorrect", db=URL).ask("Có bao nhiêu hóa đơn tháng 3/2025?")
        self.assertEqual(len(ans.attempts), 2)
        self.assertTrue(ans.result.ok)
        fix_turn = llm.calls[1][1]
        self.assertEqual(fix_turn[1]["content"], "SELECT nope FROM VATInvoice")
        self.assertIn("nope", fix_turn[2]["content"])

    def test_self_correction_is_bounded(self):
        llm = ScriptedLLM(lambda s, m: "SELECT nope FROM VATInvoice")
        ans = TextToSQL(llm, "selfcorrect", db=URL).ask("x")
        self.assertEqual(len(ans.attempts), CONFIGS["selfcorrect"].max_retries + 1)

    def test_empty_result_retry_stops_when_sql_repeats(self):
        empty = f"SELECT id FROM VATInvoice FINAL WHERE ComName = 'Không tồn tại' AND {ONE_DAY}"
        ans = TextToSQL(ScriptedLLM(lambda s, m: empty), "selfcorrect", db=URL).ask("Công ty không tồn tại")
        self.assertEqual(len(ans.attempts), 2)       # hỏi lại một lần, model giữ nguyên -> dừng
        self.assertTrue(ans.result.empty)

    def test_injected_second_statement_is_blocked_without_retry(self):
        ans = TextToSQL(ScriptedLLM(lambda s, m: "SELECT 1; DROP TABLE VATInvoice"), "selfcorrect", db=URL).ask("x")
        self.assertEqual(ans.result.error_code, "multi_statement")
        self.assertEqual(len(ans.attempts), 1)

    def test_cannot_answer(self):
        ans = TextToSQL(scripted(["CANNOT_ANSWER: Không có dữ liệu thời tiết."]), "baseline", db=URL).ask("Thời tiết?")
        self.assertEqual(ans.kind, "cannot")

    def test_write_request_refused_before_llm(self):
        llm = ScriptedLLM(lambda s, m: self.fail("không được gọi LLM"))
        ans = TextToSQL(llm, "production", db=URL).ask("Xóa tất cả hóa đơn nháp")
        self.assertEqual(ans.kind, "refused")

    def test_analyst_cannot_get_personal_column_even_if_model_writes_it(self):
        llm = scripted(["SELECT CusPhone FROM VATInvoice"])
        ans = TextToSQL(llm, "baseline", db=URL).ask("Số điện thoại khách hàng?", policy="analyst")
        self.assertEqual(ans.result.error_code, "forbidden")
        self.assertNotIn(" CusPhone ", llm.calls[0][0])

    def test_analyst_prompt_says_personal_info_is_restricted_not_missing(self):
        """Vai trò analyst không thấy cột cá nhân; prompt phải nói rõ là bị hạn chế quyền (không phải không có dữ liệu)
        và cấm thay cột khác rồi đặt tên như thứ được hỏi. Vai trò admin không có đoạn này."""
        llm = scripted(["SELECT 1", "SELECT 1"])
        pipe = TextToSQL(llm, "baseline", db=URL)
        pipe.ask("Cho tôi số điện thoại khách hàng", policy="analyst")
        pipe.ask("Cho tôi số điện thoại khách hàng", policy="admin")
        analyst_system, admin_system = llm.calls[0][0], llm.calls[1][0]
        self.assertIn("hạn chế quyền truy cập", analyst_system)
        self.assertIn("Không được thay bằng một cột khác", analyst_system)
        self.assertNotIn("hạn chế quyền truy cập", admin_system)

    def test_fewshot_excludes_eval_question(self):
        with open(DS.fewshot_path, encoding="utf-8") as f:
            pool_q = json.load(f)[0]["question"]
        llm = scripted(["SELECT 1"])
        TextToSQL(llm, "fewshot", db=URL).ask(pool_q, exclude_example=pool_q)
        self.assertEqual(llm.calls[0][1][0]["content"].count(pool_q), 1)    # chỉ ở câu hỏi, không ở ví dụ

    def test_linking_shrinks_prompt(self):
        llm = scripted(["SELECT 1"])
        ans = TextToSQL(llm, "linking", db=URL).ask("Tổng tiền hóa đơn tháng 3 năm 2025?")
        self.assertIn("VATInvoice", ans.tables_in_prompt)
        self.assertLessEqual(len(ans.tables_in_prompt), 2)

    def test_multi_turn_rewrite(self):
        def fn(system, messages):
            if "câu hỏi độc lập" in system:
                self.assertIn("tháng 3", messages[0]["content"])
                return "Có bao nhiêu hóa đơn trong tháng 4 năm 2025?"
            return ("SELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0 "
                    "AND ArisingDate >= '2025-04-01' AND ArisingDate < '2025-05-01'")
        history = [{"question": "Có bao nhiêu hóa đơn trong tháng 3 năm 2025?", "sql": COUNT_MONTH}]
        cfg = Config("multi_turn", use_docs=True, use_linking=True, max_retries=2, rewrite_followup=True) \
            if "rewrite_followup" in Config.__dataclass_fields__ else "production"
        ans = TextToSQL(ScriptedLLM(fn), cfg, db=URL).ask("Còn tháng 4 thì sao?", history=history)
        self.assertEqual(ans.standalone_question, "Có bao nhiêu hóa đơn trong tháng 4 năm 2025?")
        self.assertTrue(ans.result.ok, ans.result.error)

    def test_clarify(self):
        ans = TextToSQL(scripted(["CLARIFY: Doanh thu tính theo tổng tiền có hay không có thuế?"]),
                        "production", db=URL).ask("Doanh thu tháng 3?")
        self.assertEqual(ans.kind, "clarify")
        self.assertIn("thuế", ans.message)

    def test_logging_and_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            logger = QueryLogger(os.path.join(d, "q.jsonl"))
            ans = TextToSQL(scripted([COUNT_MONTH]), "baseline", logger=logger, db=URL).ask("Có bao nhiêu hóa đơn tháng 3/2025?")
            logger.feedback(ans.id, True)
            self.assertEqual(logger.verified_examples(),
                             [{"question": "Có bao nhiêu hóa đơn tháng 3/2025?", "sql": COUNT_MONTH}])


@needs_hddt
class TestCostGuardLive(unittest.TestCase):
    """Chặn truy vấn nặng bằng EXPLAIN ESTIMATE thật trên hddt (ngưỡng 5 triệu dòng trong schema_docs.json)."""

    def cfg(self, **kw):
        base = dict(use_docs=True, use_linking=True, max_retries=3, shape_check=True, cost_guard=True)
        base.update(kw)
        return Config("test", **base)

    def test_heavy_sql_is_not_run_and_light_sql_is(self):
        heavy = "SELECT sum(Amount) FROM VATInvoice"
        llm = scripted([heavy, COUNT_MONTH])
        pipe = TextToSQL(llm, self.cfg(), db=URL)
        self.assertEqual(pipe.cost_limit, DS.docs["cost_guard_rows"])
        with mock.patch.object(pipe.backend, "run", wraps=pipe.backend.run) as run:
            ans = pipe.ask("Tổng tiền tất cả hóa đơn?")
        self.assertGreater(ans.attempts[0].estimated_rows, pipe.cost_limit)
        self.assertEqual([c.args[0] for c in run.call_args_list], [COUNT_MONTH])      # SQL nặng không được chạy
        self.assertIn("dự kiến đọc khoảng", llm.calls[1][1][-1]["content"])
        self.assertTrue(ans.result.ok, ans.result.error)

    def test_model_may_keep_heavy_sql_after_one_warning(self):
        heavy = "SELECT sum(Amount) FROM VATInvoice WHERE ArisingDate >= '2020-01-01'"
        pipe = TextToSQL(scripted([heavy, heavy]), self.cfg(), db=URL)
        with mock.patch.object(pipe.backend, "estimate_rows", return_value=(50_000_000, {"VATInvoice": 50_000_000})), \
                mock.patch.object(pipe.backend, "run", return_value=mock.Mock(ok=True, empty=False, rows=[(1,)],
                                                                              error=None, truncated=False)):
            ans = pipe.ask("Tổng tiền từ 2020?")
        self.assertEqual(len(ans.attempts), 2)       # chặn mềm: nhắc một lần rồi chấp nhận SQL lặp lại


if __name__ == "__main__":
    unittest.main()
