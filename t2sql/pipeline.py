"""Pipeline Text-to-SQL, bật/tắt từng cải tiến qua `Config` để làm ablation."""
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

from . import DEFAULT_DOCS, ROOT, TODAY, prompts
from .db import Backend, ExecResult, make_backend
from .checks import check_result, describe
from .dialect import example_sql
from .evaluation import results_match
from .llm import BaseLLM, LLMError
from .retrieval import FewShotRetriever, SchemaLinker, tables_in_sql
from .safety import POLICIES, Policy, is_write_request
from .sql_utils import parse_response


@dataclass
class Config:
    name: str = "baseline"
    use_docs: bool = False          # Mức 2.1: mô tả cột + giá trị mẫu + quy tắc nghiệp vụ
    use_fewshot: bool = False       # Mức 2.2: k ví dụ gần nhất
    use_linking: bool = False       # Mức 2.3: chỉ đưa bảng liên quan
    max_retries: int = 0            # Mức 2.4: tự sửa lỗi (0 = tắt)
    retry_on_empty: bool = True
    allow_clarify: bool = False     # Mức 3: hỏi lại khi mơ hồ
    rewrite_followups: bool = False  # Mức 3: hội thoại nhiều lượt
    explain: bool = False           # Mức 3: diễn giải SQL
    guard_write_intent: bool = False  # Mức 3: từ chối yêu cầu sửa/xóa trước khi gọi LLM
    fewshot_k: int = 4
    linking_top_k: int = 3
    linking_fewshot_hint: bool = False  # thêm bảng mà ví dụ few-shot dùng (tăng recall, prompt dài hơn)
    shape_check: bool = False       # kiểm tra hình dạng kết quả (t2sql/checks.py), nghi vấn -> cho model sửa
    n_candidates: int = 1           # self-consistency: số chuỗi sinh SQL (1 = tắt)
    sample_temperature: float = 0.7  # temperature cho các chuỗi lấy mẫu (chuỗi đầu luôn dùng mặc định)
    early_stop: bool = True         # 2 chuỗi đầu cùng kết quả thì bỏ các chuỗi còn lại


CONFIGS = {
    "baseline": Config("baseline"),
    "docs": Config("docs", use_docs=True),
    "fewshot": Config("fewshot", use_docs=True, use_fewshot=True),
    "linking": Config("linking", use_docs=True, use_fewshot=True, use_linking=True),
    "selfcorrect": Config("selfcorrect", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3),
    "shapecheck": Config("shapecheck", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                         shape_check=True),
    "consistency": Config("consistency", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                          n_candidates=3),
    "robust": Config("robust", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                     shape_check=True, n_candidates=3),
    "production": Config("production", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                         shape_check=True, allow_clarify=True, rewrite_followups=True, explain=True,
                         guard_write_intent=True),
}
ABLATION_ORDER = ["baseline", "docs", "fewshot", "linking", "selfcorrect"]


@dataclass
class Attempt:
    raw: str
    kind: str
    sql: str | None
    error: str | None = None
    rows: int | None = None
    llm_ms: float = 0.0             # thời gian model sinh câu trả lời
    db_ms: float = 0.0              # thời gian chạy SQL (kể cả kiểm tra an toàn)
    issues: list[str] = field(default_factory=list)   # quy tắc hình dạng bị vi phạm (R1..R7)


@dataclass
class Chain:
    """Một chuỗi sinh SQL -> chạy -> tự sửa. Self-consistency chạy nhiều chuỗi rồi bỏ phiếu."""
    temperature: float | None = None
    kind: str = "error"
    sql: str | None = None
    result: ExecResult | None = None
    message: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


def _usable(c: Chain) -> bool:
    return c.kind in ("cannot", "clarify") or (c.kind == "result" and c.result is not None and c.result.ok)


def _same_result(a: Chain, b: Chain) -> bool:
    """Hai chuỗi cho cùng kết quả: cùng từ chối, hoặc cùng tập dòng (bỏ qua thứ tự, cho phép thừa cột)."""
    if a.kind != b.kind or not (_usable(a) and _usable(b)):
        return False
    if a.kind != "result":
        return True
    ra, rb = a.result.rows, b.result.rows
    return results_match(ra, rb, allow_extra_columns=True) or results_match(rb, ra, allow_extra_columns=True)


@dataclass
class Answer:
    question: str
    kind: str                       # result | cannot | clarify | refused | error
    standalone_question: str | None = None
    sql: str | None = None
    result: ExecResult | None = None
    message: str | None = None      # lý do từ chối / câu hỏi lại / lỗi
    explanation: str | None = None
    attempts: list[Attempt] = field(default_factory=list)
    tables_in_prompt: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    agreement: str | None = None     # self-consistency: "3/3" = mọi chuỗi cho cùng kết quả
    candidates: list[dict] = field(default_factory=list)

    def to_log(self) -> dict:
        r = self.result
        return {
            "id": self.id, "started_at": self.started_at, "question": self.question, "standalone_question": self.standalone_question,
            "kind": self.kind, "sql": self.sql, "message": self.message, "explanation": self.explanation,
            "ok": bool(r and r.ok), "rows": len(r.rows) if r and r.ok else None,
            "error": r.error if r and not r.ok else None, "latency_ms": self.latency_ms,
            "attempts": [asdict(a) for a in self.attempts], "tables_in_prompt": self.tables_in_prompt,
            "agreement": self.agreement, "candidates": self.candidates,
        }


class TextToSQL:
    def __init__(self, llm: BaseLLM, config: Config | str = "baseline", db: Backend | str | None = None,
                 docs_path: str = DEFAULT_DOCS, fewshot_path: str | None = None,
                 max_rows: int = 200, timeout_s: float | None = None, logger=None):
        """db: một Backend, một URL (postgresql://... / sqlite:///...), đường dẫn file SQLite,
        hoặc None để lấy từ T2SQL_DATABASE_URL (trống = SQLite data/shop.db)."""
        self.llm = llm
        self.config = CONFIGS[config] if isinstance(config, str) else config
        if isinstance(db, Backend):
            self.backend = db
        else:
            url = db if db is None or "://" in db else f"sqlite:///{db}"
            self.backend = make_backend(url, max_rows=max_rows, timeout_s=timeout_s)
        self.executor = self.backend   # tên cũ
        self.dialect = self.backend.dialect
        self.schema = self.backend.load_schema(docs_path)
        self.retriever = None
        if self.config.use_fewshot:
            path = fewshot_path or os.path.join(ROOT, "eval", "fewshot_pool.json")
            self.retriever = FewShotRetriever.from_file(path, k=self.config.fewshot_k)
            # Ví dụ viết cho SQLite: chuyển sang dialect của DB đích (ưu tiên bản viết tay nếu có).
            for ex in self.retriever.examples:
                ex["sql"] = example_sql(ex, self.dialect)
        self.linker = SchemaLinker(self.schema, top_k=self.config.linking_top_k) if self.config.use_linking else None
        self.logger = logger

    # ------------------------------------------------------------------
    def ask(self, question: str, history: list[dict] | None = None, policy: Policy | str | None = None,
            exclude_example: str | None = None) -> Answer:
        policy = POLICIES[policy] if isinstance(policy, str) else (policy or POLICIES["admin"])
        t0 = time.perf_counter()
        ans = Answer(question=question, kind="error")
        try:
            self._ask(ans, question, history or [], policy, exclude_example)
            if self.config.explain:
                self.explain(ans)
        except LLMError as e:
            ans.kind, ans.message = "error", str(e)
        ans.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if self.logger:
            self.logger.log(ans, policy=policy.name, config=self.config.name)
        return ans

    def _ask(self, ans: Answer, question: str, history, policy, exclude_example):
        cfg = self.config
        if not question or not question.strip():
            ans.kind, ans.message = "cannot", "Câu hỏi trống."
            return
        if cfg.guard_write_intent and is_write_request(question):
            ans.kind = "refused"
            ans.message = "Xin lỗi, hệ thống chỉ hỗ trợ tra cứu dữ liệu, không thể thêm, sửa hay xóa dữ liệu."
            return

        q = question
        if cfg.rewrite_followups and history:
            q = self.llm.complete(prompts.REWRITE_SYSTEM.format(today=TODAY),
                                  prompts.rewrite_messages(history, question), max_tokens=2000).strip() or question
        ans.standalone_question = q

        examples = self.retriever.top(q, exclude_question=exclude_example) if self.retriever else []
        schema = self.schema
        if policy.allowed_tables is not None:
            schema = schema.subset(policy.allowed_tables)  # không cho model thấy bảng ngoài quyền
        if policy.denied_columns:
            schema = schema.without_columns(policy.denied_columns)
        if self.linker:
            use_hint = examples and cfg.linking_fewshot_hint
            hint = set().union(*(tables_in_sql(e["sql"]) for e in examples)) if use_hint else set()
            linked = self.linker.link(q, hint)
            schema = schema.subset([t for t in linked if t in schema.tables])
        ans.tables_in_prompt = list(schema.tables)

        system = prompts.sql_system(schema.render(with_docs=cfg.use_docs), cfg.allow_clarify, self.dialect)
        messages = [{"role": "user", "content": prompts.user_message(q, examples)}]

        if cfg.n_candidates <= 1:
            chain = self._chain(system, messages, policy, q, temperature=None)
        else:
            chain = self._self_consistency(system, messages, policy, q, ans)
        ans.kind, ans.sql, ans.result, ans.attempts = chain.kind, chain.sql, chain.result, chain.attempts
        if chain.kind in ("cannot", "clarify"):
            ans.message = chain.message

    # ------------------------------------------------------------------ một chuỗi: sinh -> chạy -> tự sửa
    def _chain(self, system, base_messages, policy, question, temperature=None) -> "Chain":
        """Sinh SQL, chạy, và tự sửa khi SQL lỗi / rỗng / kết quả có hình dạng đáng ngờ (tối đa max_retries lần)."""
        cfg = self.config
        messages = list(base_messages)
        chain = Chain(temperature=temperature)
        last_sql = None
        for attempt_no in range(cfg.max_retries + 1):
            t_llm = time.perf_counter()
            raw = self.llm.complete(system, messages, max_tokens=16000, temperature=temperature)
            kind, payload = parse_response(raw)
            att = Attempt(raw=raw, kind=kind, sql=payload if kind == "sql" else None,
                          llm_ms=round((time.perf_counter() - t_llm) * 1000, 1))
            chain.attempts.append(att)
            if kind in ("cannot", "clarify"):
                chain.kind, chain.message, chain.sql, chain.result = kind, payload, None, None
                return chain
            res = self.executor.run(payload, policy=policy)
            att.db_ms = res.elapsed_ms
            chain.kind, chain.sql, chain.result = "result", payload, res
            att.error, att.rows = (None, len(res.rows)) if res.ok else (res.error, None)
            if res.error_code in ("forbidden", "blocked", "multi_statement", "not_select",
                                  "forbidden_keyword", "forbidden_function", "timeout", "db_unavailable"):
                return chain  # vi phạm an toàn / quá tải: không cho model "thử lại cho qua"
            issues = check_result(question, res.columns, res.rows) if (cfg.shape_check and res.ok) else []
            att.issues = [i.rule for i in issues]
            chain.issues = att.issues
            repeated = payload == last_sql   # model giữ nguyên SQL sau phản hồi: chấp nhận, không ép sửa tiếp
            if not res.ok:
                fix = prompts.fix_error(res.error, self.dialect)
            elif res.empty and cfg.retry_on_empty and not repeated:
                fix = prompts.FIX_EMPTY
            elif issues and not repeated:
                fix = prompts.FIX_SHAPE.format(issues=describe(issues))
            else:
                return chain
            if attempt_no == cfg.max_retries:
                return chain
            last_sql = payload
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": fix})
        return chain

    # ------------------------------------------------------------------ self-consistency
    def _self_consistency(self, system, messages, policy, question, ans) -> "Chain":
        """Chạy nhiều chuỗi (1 chuỗi temperature 0 + các chuỗi lấy mẫu), gom theo KẾT QUẢ thực thi và chọn nhóm
        đông nhất. Chuỗi lỗi bị loại; chuỗi có nghi vấn hình dạng chỉ được tính khi không còn chuỗi sạch.
        early_stop: chạy 2 chuỗi trước, nếu cùng kết quả thì bỏ chuỗi thứ 3."""
        from concurrent.futures import ThreadPoolExecutor
        cfg = self.config
        temps = [None] + [cfg.sample_temperature] * (cfg.n_candidates - 1)
        run = lambda t: self._chain(system, messages, policy, question, temperature=t)
        first = min(2, len(temps)) if cfg.early_stop else len(temps)
        with ThreadPoolExecutor(max_workers=len(temps)) as pool:
            chains = list(pool.map(run, temps[:first]))
            if len(temps) > first and not (_same_result(chains[0], chains[1]) and _usable(chains[0])):
                chains += list(pool.map(run, temps[first:]))

        valid = [c for c in chains if _usable(c)]
        clean = [c for c in valid if not c.issues] or valid
        clusters: list[list[Chain]] = []
        for c in clean:
            for cl in clusters:
                if _same_result(cl[0], c):
                    cl.append(c)
                    break
            else:
                clusters.append([c])
        if clusters:
            # đông nhất thắng; hòa thì ưu tiên nhóm chứa chuỗi temperature 0 (chuỗi đầu tiên)
            best = max(clusters, key=lambda cl: (len(cl), any(c is chains[0] for c in cl)))
            winner = next((c for c in best if c is chains[0]), best[0])
            votes = len(best)
        else:
            winner, votes = chains[0], 0    # mọi chuỗi đều lỗi: giữ chuỗi temperature 0
        ans.agreement = f"{votes}/{len(chains)}"
        ans.candidates = [{"temperature": c.temperature, "kind": c.kind, "sql": c.sql, "issues": c.issues,
                           "ok": bool(c.result and c.result.ok), "rows": len(c.result.rows) if c.result and c.result.ok else None,
                           "attempts": len(c.attempts), "winner": c is winner} for c in chains]
        return winner

    def explain(self, ans: Answer) -> str | None:
        if ans.kind != "result" or not ans.sql:
            return None
        ans.explanation = self.llm.complete(prompts.EXPLAIN_SYSTEM,
                                            prompts.explain_messages(ans.standalone_question or ans.question, ans.sql),
                                            max_tokens=4000).strip()
        return ans.explanation
