"""Pipeline Text-to-SQL, bật/tắt từng cải tiến qua `Config` để làm ablation."""
import re
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

from . import ROOT, TODAY, datasets, prompts
from .db import Backend, ExecResult, make_backend
from .checks import Issue, check_result, describe
from .dialect import example_sql
from .evaluation import results_match
from .llm import BaseLLM, LLMError
from .memory import ErrorMemory
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
    lookup_tables: bool = False     # đưa toàn bộ dòng của bảng danh mục nhỏ vào prompt + liên kết theo giá trị
    lookup_max_rows: int = 100
    lookup_max_chars: int = 4000    # bỏ qua bảng danh mục có nội dung dài hơn
    error_hints: bool = False       # gửi kèm gợi ý sửa theo mã lỗi của DB khi SQL lỗi
    cost_guard: bool = False        # EXPLAIN ESTIMATE trước khi chạy; đọc quá ngưỡng -> đề nghị model viết gọn hơn
    cost_guard_rows: int = 40_000_000   # ghi đè bằng T2SQL_MAX_ESTIMATED_ROWS
    semantic_check: bool = False    # thêm một lời gọi model soát lỗi logic của SQL + kết quả
    reasoning_hard: str | None = None   # bật reasoning (low/medium/high) cho câu hỏi có vẻ phức tạp
    use_history: bool = False       # thêm thói quen khai thác từ lịch sử truy vấn của analyst (t2sql/history.py)
    docs_variant: str | None = None  # dùng schema_docs.<variant>.json thay cho bản đầy đủ (ví dụ "norules")
    history_parts: str = "both"     # both | conventions | snippets: phần nào của tri thức lịch sử đưa vào prompt
    classify_first: bool = False    # một lời gọi model phân loại ANSWER / CLARIFY / CANNOT trước khi sinh SQL
    use_memory: bool = False        # bộ nhớ sửa lỗi (t2sql/memory.py): đưa bài học của câu tương tự đã từng sai vào prompt
    clarify_strong: bool = False    # quy tắc hỏi lại / từ chối chi tiết hơn ngay trong prompt sinh SQL (không thêm lời gọi)


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
    # Cải tiến cho ClickHouse / database lớn (cộng dồn lên shapecheck)
    "lookup": Config("lookup", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3, shape_check=True,
                     lookup_tables=True, error_hints=True),
    "costguard": Config("costguard", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3, shape_check=True,
                        lookup_tables=True, error_hints=True, cost_guard=True),
    "verify": Config("verify", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3, shape_check=True,
                     lookup_tables=True, error_hints=True, cost_guard=True, semantic_check=True),
    "reasoning": Config("reasoning", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3, shape_check=True,
                        lookup_tables=True, error_hints=True, cost_guard=True, semantic_check=True,
                        reasoning_hard="medium"),
    # Thí nghiệm tri thức từ lịch sử truy vấn: tài liệu KHÔNG có quy tắc nghiệp vụ, có / không có lịch sử
    "norules": Config("norules", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3, shape_check=True,
                      lookup_tables=True, error_hints=True, docs_variant="norules"),
    "history": Config("history", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3, shape_check=True,
                      lookup_tables=True, error_hints=True, docs_variant="norules", use_history=True),
    # Khởi đầu lạnh: database mới, chưa có quy tắc viết tay lẫn few-shot đã duyệt, chỉ có lịch sử truy vấn
    "cold": Config("cold", use_docs=True, use_linking=True, max_retries=3, shape_check=True,
                   lookup_tables=True, error_hints=True, docs_variant="norules"),
    "cold_history": Config("cold_history", use_docs=True, use_linking=True, max_retries=3, shape_check=True,
                           lookup_tables=True, error_hints=True, docs_variant="norules", use_history=True),
    "cold_conv": Config("cold_conv", use_docs=True, use_linking=True, max_retries=3, shape_check=True,
                        lookup_tables=True, error_hints=True, docs_variant="norules", use_history=True,
                        history_parts="conventions"),
    "cold_snip": Config("cold_snip", use_docs=True, use_linking=True, max_retries=3, shape_check=True,
                        lookup_tables=True, error_hints=True, docs_variant="norules", use_history=True,
                        history_parts="snippets"),
    "rules_history": Config("rules_history", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                            shape_check=True, lookup_tables=True, error_hints=True, use_history=True),
    # production trước khi bật gợi ý lỗi / bảng danh mục / chặn truy vấn nặng (giữ để so sánh)
    "production_plain": Config("production_plain", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                               shape_check=True, allow_clarify=True, rewrite_followups=True, explain=True,
                               guard_write_intent=True),
    # production không dùng few-shot: đo riêng tác dụng của ví dụ mẫu (bộ dữ liệu mới thường chưa có)
    "production_nofs": Config("production_nofs", use_docs=True, use_fewshot=False, use_linking=True, max_retries=3,
                              shape_check=True, allow_clarify=True, rewrite_followups=True, explain=True,
                              guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True),
    # production với tài liệu schema bản cũ (schema_docs.v1.json): đo tác dụng của lần bổ sung định nghĩa nghiệp vụ
    "production_docsv1": Config("production_docsv1", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                                shape_check=True, allow_clarify=True, rewrite_followups=True, explain=True,
                                guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True,
                                docs_variant="v1"),
    # production với tài liệu schema v3 (trước khi bổ sung nghĩa Status / Type suy ra từ ghi chú trên hóa đơn)
    "production_docsv3": Config("production_docsv3", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                                shape_check=True, allow_clarify=True, rewrite_followups=True, explain=True,
                                guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True,
                                docs_variant="v3"),
    # production + bộ nhớ sửa lỗi (thí nghiệm hướng 3)
    "production_memory": Config("production_memory", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                                shape_check=True, allow_clarify=True, rewrite_followups=True, explain=False,
                                guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True,
                                clarify_strong=True, use_memory=True),
    # production với tài liệu schema v4 (trước khi tự xác nhận thuế suất, Feature, đơn vị tính): so sánh với v5
    "production_docsv4": Config("production_docsv4", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                                shape_check=True, allow_clarify=True, rewrite_followups=True, explain=False,
                                guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True,
                                clarify_strong=True, docs_variant="v4"),
    # production với self-consistency (3 phương án)
    "production_sc": Config("production_sc", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                            shape_check=True, allow_clarify=True, rewrite_followups=True, explain=True,
                            guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True,
                            n_candidates=3),
    # explain=False: giải thích SQL là một lần gọi model thứ hai (đo trên hddt: 3,9 giây, 57% thời gian một câu hỏi).
    # Giao diện vẫn có nút bật; các cấu hình so sánh phía trên giữ explain=True để kết quả lịch sử không đổi.
    # clarify_strong: quy tắc hỏi lại / từ chối chi tiết trong prompt sinh SQL (không tốn lời gọi). Đo trên bộ 50 câu mơ hồ /
    # không trả lời được: từ chối đúng 32/32 (trước 30/32), không làm hỏng 94 câu thường. Các cấu hình so sánh phía trên giữ quy tắc cũ.
    "production": Config("production", use_docs=True, use_fewshot=True, use_linking=True, max_retries=3,
                         shape_check=True, allow_clarify=True, rewrite_followups=True, explain=False,
                         guard_write_intent=True, lookup_tables=True, error_hints=True, cost_guard=True,
                         clarify_strong=True),
    # production + bước phân loại câu hỏi trước khi sinh SQL (thí nghiệm câu mơ hồ / không trả lời được)
    "production_classify": Config("production_classify", use_docs=True, use_fewshot=True, use_linking=True,
                                  max_retries=3, shape_check=True, allow_clarify=True, rewrite_followups=True,
                                  explain=False, guard_write_intent=True, lookup_tables=True, error_hints=True,
                                  cost_guard=True, classify_first=True),
}
ABLATION_ORDER = ["baseline", "docs", "fewshot", "linking", "selfcorrect"]


_CLASSIFY_RE = re.compile(r"^\W*(ANSWER|CLARIFY|CANNOT)\b[\s:：-]*(.*)", re.I | re.S)


def parse_classification(raw: str):
    """(kind, payload): 'sql' = tiếp tục sinh SQL; 'clarify' / 'cannot' kèm câu hỏi lại / lý do. Không đọc được -> tiếp tục."""
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    m = _CLASSIFY_RE.match(text)
    if not m:
        return "sql", None
    word, rest = m.group(1).upper(), m.group(2).strip().splitlines()[0].strip() if m.group(2).strip() else ""
    if word == "CLARIFY":
        return "clarify", rest or "Bạn có thể nói rõ hơn câu hỏi không?"
    if word == "CANNOT":
        return "cannot", rest or "Dữ liệu không có thông tin này."
    return "sql", None


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
    estimated_rows: int | None = None   # cost_guard: số dòng dự kiến đọc (khi vượt ngưỡng, SQL không được chạy)
    verdict: str | None = None      # semantic_check: lý do người soát cho là sai (None = OK / không soát)


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


_HARD_CUES = [
    ("so với", "cùng kỳ", "tăng", "giảm", "chênh"),                          # so sánh giữa hai kỳ / nhóm
    ("tỷ lệ", "tỷ trọng", "phần trăm", "%"),                                   # tỷ lệ
    ("nếu ", "giả sử", "không có chính sách"),                                 # giả định
    ("lần đầu", "đầu tiên", "mua thêm", "trở lên", "trong vòng", "đến khi", "từ lúc", "cách ngày"),  # chuỗi sự kiện
    ("ở mỗi", "mỗi vùng", "mỗi nơi", "mỗi ngành", "mỗi tỉnh", "từng vùng"),   # xếp hạng trong nhóm
]


def looks_hard(question: str, n_tables: int) -> bool:
    """Heuristic chọn câu hỏi nên bật reasoning: có ít nhất một dấu hiệu phức tạp (so sánh kỳ, tỷ lệ, giả định,
    chuỗi sự kiện, xếp hạng trong nhóm). Số bảng sau schema linking không phân biệt được câu khó nên không dùng.
    Trên bộ dev: bắt 13/20 câu khó, 3/22 câu trung bình, 0/16 câu dễ."""
    q = (question or "").lower()
    return any(any(c in q for c in group) for group in _HARD_CUES)


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
    memory_ids: list[str] = field(default_factory=list)   # bài học từ bộ nhớ sửa lỗi đã đưa vào prompt
    agreement: str | None = None     # self-consistency: "3/3" = mọi chuỗi cho cùng kết quả
    candidates: list[dict] = field(default_factory=list)
    reasoning: str | None = None     # mức reasoning đã dùng cho câu này (reasoning_hard)

    def to_log(self) -> dict:
        r = self.result
        return {
            "id": self.id, "started_at": self.started_at, "question": self.question, "standalone_question": self.standalone_question,
            "kind": self.kind, "sql": self.sql, "message": self.message, "explanation": self.explanation,
            "ok": bool(r and r.ok), "rows": len(r.rows) if r and r.ok else None,
            "error": r.error if r and not r.ok else None, "latency_ms": self.latency_ms,
            "attempts": [asdict(a) for a in self.attempts], "tables_in_prompt": self.tables_in_prompt,
            "agreement": self.agreement, "candidates": self.candidates, "reasoning": self.reasoning,
            "memory_ids": self.memory_ids,
        }


class TextToSQL:
    def __init__(self, llm: BaseLLM, config: Config | str = "baseline", db: Backend | str | None = None,
                 docs_path: str | None = None, fewshot_path: str | None = None,
                 max_rows: int = 200, timeout_s: float | None = None, logger=None):
        """db: một Backend, một URL clickhouse://..., hoặc None để lấy từ T2SQL_DATABASE_URL.
        docs_path=None: dùng bộ dữ liệu theo tên database (datasets/<tên>/, bắt buộc phải có)."""
        self.llm = llm
        self.config = CONFIGS[config] if isinstance(config, str) else config
        if isinstance(db, Backend):
            self.backend = db
        else:
            self.backend = make_backend(db, max_rows=max_rows, timeout_s=timeout_s)
        self.executor = self.backend   # tên cũ
        self.dialect = self.backend.dialect
        self.dataset = datasets.for_backend(self.backend) if docs_path is None else datasets.from_docs(docs_path)
        self.policies = self.dataset.policies
        self.schema = self.backend.load_schema(self.dataset.docs_path_for(self.config.docs_variant))
        self.schema.requires = {t: set(r) for t, r in self.dataset.docs.get("requires", {}).items()}
        self.retriever = None
        if self.config.use_fewshot:
            path = fewshot_path or self.dataset.fewshot_path
            if path and os.path.exists(path):      # bộ dữ liệu mới chưa có few-shot: chạy không kèm ví dụ
                self.retriever = FewShotRetriever.from_file(path, k=self.config.fewshot_k)
                for ex in self.retriever.examples:
                    ex["sql"] = example_sql(ex)
        self.memory = ErrorMemory.from_file(os.path.join(os.path.dirname(self.dataset.docs_path), "error_memory.json"),
                                            min_score=float(os.environ.get("T2SQL_MEMORY_MIN_SCORE") or 0.2)) \
            if self.config.use_memory and self.dataset.docs_path else None
        self.linker = SchemaLinker(self.schema, top_k=self.config.linking_top_k) if self.config.use_linking else None
        self.lookups = self._load_lookups() if self.config.lookup_tables else {}
        self.history = self._load_history() if self.config.use_history else None
        # ngưỡng của bộ dữ liệu (docs "cost_guard_rows") theo cỡ server thật; biến môi trường ghi đè
        self.cost_limit = int(os.environ.get("T2SQL_MAX_ESTIMATED_ROWS") or self.dataset.docs.get("cost_guard_rows")
                              or self.config.cost_guard_rows)
        self.logger = logger

    def _load_history(self):
        from .history import HistoryKnowledge, load_history
        if not self.dataset.history_path:
            raise FileNotFoundError("Chưa có query_history.jsonl: chạy `python mine_query_log.py` trước.")
        cols = {t: set(tb.column_names()) for t, tb in self.schema.tables.items()}
        return HistoryKnowledge([r["sql"] for r in load_history(self.dataset.history_path)], cols, self.dialect)

    def _load_lookups(self) -> dict:
        """Bảng danh mục nhỏ (ít dòng): {bảng: (cột, dòng, tập giá trị chữ viết thường để liên kết theo giá trị)}."""
        from .schema import NO_SAMPLE_COLUMNS
        cfg, out = self.config, {}
        no_sample = NO_SAMPLE_COLUMNS | {tuple(c) for c in self.dataset.docs.get("no_sample_columns", [])}
        for name, t in self.schema.tables.items():
            if not 0 < t.row_count <= cfg.lookup_max_rows:
                continue
            cols = [c.name for c in t.columns
                    if (name, c.name) not in no_sample and not c.type.startswith("AggregateFunction")]
            res = self.backend.run("SELECT " + ", ".join(cols) + f" FROM {name}", safe=False)
            if not res.ok or not res.rows:
                continue
            text = prompts.lookup_text({name: (res.columns, res.rows)})
            if len(text) > cfg.lookup_max_chars:
                continue
            values = {str(v).lower() for r in res.rows for v in r
                      if isinstance(v, str) and len(v) >= 3 and not v.isdigit()}
            out[name] = (res.columns, res.rows, values)
        return out

    # ------------------------------------------------------------------
    def ask(self, question: str, history: list[dict] | None = None, policy: Policy | str | None = None,
            exclude_example: str | None = None) -> Answer:
        policy = self.policies[policy] if isinstance(policy, str) else (policy or self.policies["admin"])
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
            linked = set(self.linker.link(q, hint))
            if self.lookups:   # liên kết theo giá trị: câu hỏi nhắc "Đà Nẵng", "Xây dựng"... -> kèm bảng danh mục đó
                ql = q.lower()
                linked |= {t for t, (_, _, vals) in self.lookups.items() if any(v in ql for v in vals)}
            schema = schema.subset([t for t in linked if t in schema.tables])
        ans.tables_in_prompt = list(schema.tables)

        schema_text = schema.render(with_docs=cfg.use_docs)
        shown = {t: self.lookups[t] for t in schema.tables if t in self.lookups}
        if shown:
            parts = {}
            for t, (cols, rows, _) in shown.items():
                keep = [i for i, c in enumerate(cols) if c in schema.tables[t].column_names()]
                parts[t] = ([cols[i] for i in keep], [tuple(r[i] for i in keep) for r in rows])
            schema_text += "\n\n" + prompts.lookup_text(parts)
        if self.history:
            denied = {c for t, c in policy.denied_columns}
            hist = self.history.render(set(schema.tables), q, exclude_columns=denied, parts=cfg.history_parts)
            if hist:
                schema_text += "\n\n" + hist
        if cfg.classify_first:
            t_cls = time.perf_counter()
            raw = self.llm.complete(prompts.classify_system(schema_text), [{"role": "user", "content": q}],
                                    max_tokens=1000)
            kind, payload = parse_classification(raw)
            if kind != "sql":
                ans.attempts.append(Attempt(raw=raw, kind=kind, sql=None,
                                            llm_ms=round((time.perf_counter() - t_cls) * 1000, 1)))
                ans.kind, ans.message = kind, payload
                return
        system = prompts.sql_system(schema_text, cfg.allow_clarify, self.dialect, cfg.clarify_strong)
        reasoning = cfg.reasoning_hard if cfg.reasoning_hard and looks_hard(q, len(schema.tables)) else None
        ans.reasoning = reasoning
        lessons = self.memory.top(q, exclude_question=exclude_example) if self.memory else []
        ans.memory_ids = [e["id"] for e in lessons]
        messages = [{"role": "user", "content": prompts.user_message(q, examples, lessons)}]

        if cfg.n_candidates <= 1:
            chain = self._chain(system, messages, policy, q, temperature=None, reasoning=reasoning)
        else:
            chain = self._self_consistency(system, messages, policy, q, ans, reasoning=reasoning)
        ans.kind, ans.sql, ans.result, ans.attempts = chain.kind, chain.sql, chain.result, chain.attempts
        if chain.kind in ("cannot", "clarify"):
            ans.message = chain.message

    # ------------------------------------------------------------------ một chuỗi: sinh -> chạy -> tự sửa
    def _chain(self, system, base_messages, policy, question, temperature=None, reasoning=None) -> "Chain":
        """Sinh SQL, chạy, và tự sửa khi SQL lỗi / rỗng / kết quả có hình dạng đáng ngờ (tối đa max_retries lần).
        Tùy Config: chặn truy vấn đọc quá nhiều (cost_guard), soát lỗi logic bằng một lời gọi model (semantic_check)."""
        cfg = self.config
        messages = list(base_messages)
        chain = Chain(temperature=temperature)
        last_sql = None
        guarded = verified = False
        for attempt_no in range(cfg.max_retries + 1):
            t_llm = time.perf_counter()
            raw = self.llm.complete(system, messages, max_tokens=16000, temperature=temperature, reasoning=reasoning)
            kind, payload = parse_response(raw)
            att = Attempt(raw=raw, kind=kind, sql=payload if kind == "sql" else None,
                          llm_ms=round((time.perf_counter() - t_llm) * 1000, 1))
            chain.attempts.append(att)
            if kind in ("cannot", "clarify"):
                chain.kind, chain.message, chain.sql, chain.result = kind, payload, None, None
                return chain
            repeated = payload == last_sql   # model giữ nguyên SQL sau phản hồi: chấp nhận, không ép sửa tiếp
            can_retry = attempt_no < cfg.max_retries
            if cfg.cost_guard and not guarded and not repeated and can_retry:
                est = self.backend.estimate_rows(payload, policy)
                if est and est[0] > self.cost_limit:
                    guarded = True
                    att.estimated_rows = est[0]
                    detail = ", ".join(f"{t}: {n:,}" for t, n in sorted(est[1].items(), key=lambda x: -x[1]))
                    last_sql = payload
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user",
                                     "content": prompts.FIX_COST.format(rows=f"{est[0]:,}", detail=detail)})
                    continue
            res = self.executor.run(payload, policy=policy)
            att.db_ms = res.elapsed_ms
            chain.kind, chain.sql, chain.result = "result", payload, res
            att.error, att.rows = (None, len(res.rows)) if res.ok else (res.error, None)
            if res.error_code in ("forbidden", "blocked", "multi_statement", "not_select",
                                  "forbidden_keyword", "forbidden_function", "timeout", "db_unavailable"):
                return chain  # vi phạm an toàn / quá tải: không cho model "thử lại cho qua"
            issues = check_result(question, res.columns, res.rows) if (cfg.shape_check and res.ok) else []
            if cfg.shape_check and res.ok and not tables_in_sql(payload):
                # ClickHouse chạy được "SELECT count()" không có FROM (đọc system.one) và trả 1: sai mà không báo lỗi
                issues.insert(0, Issue("R0", "Câu SQL không đọc từ bảng nào (thiếu FROM), nên kết quả không lấy từ dữ liệu."))
            att.issues = [i.rule for i in issues]
            chain.issues = att.issues
            if not res.ok:
                hint = f"\nGợi ý: {res.hint}" if cfg.error_hints and res.hint else ""
                fix = prompts.fix_error(res.error + hint, self.dialect)
            elif res.empty and cfg.retry_on_empty and not repeated:
                fix = prompts.FIX_EMPTY
            elif issues and not repeated:
                fix = prompts.FIX_SHAPE.format(issues=describe(issues))
            elif cfg.semantic_check and not verified and not repeated and can_retry:
                verified = True
                try:
                    reason = prompts.parse_verdict(self.llm.complete(
                        prompts.VERIFY_SYSTEM,
                        prompts.verify_messages(question, payload, res.columns, res.rows, len(res.rows),
                                                self.schema.business_rules),
                        max_tokens=2000, temperature=0))
                except LLMError:
                    return chain    # bước soát chỉ là phụ: lỗi mạng / quá tải thì giữ kết quả đã chạy tốt
                if not reason:
                    return chain
                att.verdict = reason
                fix = prompts.FIX_SEMANTIC.format(reason=reason)
            else:
                return chain
            if attempt_no == cfg.max_retries:
                return chain
            last_sql = payload
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": fix})
        return chain

    # ------------------------------------------------------------------ self-consistency
    def _self_consistency(self, system, messages, policy, question, ans, reasoning=None) -> "Chain":
        """Chạy nhiều chuỗi (1 chuỗi temperature 0 + các chuỗi lấy mẫu), gom theo KẾT QUẢ thực thi và chọn nhóm
        đông nhất. Chuỗi lỗi bị loại; chuỗi có nghi vấn hình dạng chỉ được tính khi không còn chuỗi sạch.
        early_stop: chạy 2 chuỗi trước, nếu cùng kết quả thì bỏ chuỗi thứ 3."""
        from concurrent.futures import ThreadPoolExecutor
        cfg = self.config
        temps = [None] + [cfg.sample_temperature] * (cfg.n_candidates - 1)
        run = lambda t: self._chain(system, messages, policy, question, temperature=t, reasoning=reasoning)
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
