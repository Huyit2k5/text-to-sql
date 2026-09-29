"""Few-shot theo ngữ cảnh và schema linking (Mức 2), thuần Python.

Tiếng Việt là ngôn ngữ đơn lập: một "từ" thường gồm 2 âm tiết ("doanh thu", "khách hàng"),
nên ta dùng unigram + bigram âm tiết và TF-IDF để đo độ giống.
"""
import json
import math
import re
from collections import Counter

_TOKEN = re.compile(r"[0-9a-zà-ỹđ_]+", re.I)
STOP = {"của", "và", "là", "có", "các", "những", "cho", "trong", "theo", "với", "được", "bao", "nhiêu",
        "nào", "gì", "the", "a", "of", "hãy", "liệt", "kê", "cho", "tôi", "biết", "mỗi", "từng", "một"}


def tokens(text: str) -> list[str]:
    words = [w.lower() for w in _TOKEN.findall(text or "")]
    content = [w for w in words if w not in STOP]
    bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return content + bigrams


class TfidfIndex:
    def __init__(self, docs: list[str]):
        self.docs = [Counter(tokens(d)) for d in docs]
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs = [self._vec(d) for d in self.docs]

    def _vec(self, counts):
        v = {t: c * self.idf.get(t, math.log(1 + len(self.docs)) + 1) for t, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def scores(self, query: str) -> list[float]:
        q = self._vec(Counter(tokens(query)))
        return [sum(w * d.get(t, 0.0) for t, w in q.items()) for d in self.vecs]


class FewShotRetriever:
    """Chọn k cặp (câu hỏi, SQL) giống câu hỏi mới nhất; giới hạn tổng độ dài để prompt không phình."""

    def __init__(self, examples: list[dict], k: int = 4, max_chars: int = 3000):
        self.examples = examples
        self.k = k
        self.max_chars = max_chars
        self.index = TfidfIndex([e["question"] for e in examples])

    @classmethod
    def from_file(cls, path, **kw):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), **kw)

    def top(self, question: str, exclude_question: str | None = None) -> list[dict]:
        ranked = sorted(zip(self.index.scores(question), self.examples), key=lambda x: -x[0])
        out, used = [], 0
        for score, ex in ranked:
            if len(out) >= self.k or score <= 0:
                break
            if exclude_question and ex["question"].strip() == exclude_question.strip():
                continue  # tránh rò rỉ đáp án khi đánh giá
            size = len(ex["question"]) + len(ex["sql"])
            if used + size > self.max_chars:
                continue
            out.append(ex)
            used += size
        return out


_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_CTE_NAME = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.I)


def tables_in_sql(sql: str) -> set[str]:
    """Tên bảng sau FROM/JOIN, bỏ tên CTE."""
    ctes = {m.lower() for m in _CTE_NAME.findall(sql or "")}
    return {m.lower() for m in _TABLE_REF.findall(sql or "")} - ctes


class SchemaLinker:
    """Chấm điểm từng bảng theo mức trùng từ khóa giữa câu hỏi và (tên bảng, tên cột, mô tả, giá trị mẫu).

    Giữ các bảng có điểm cao nhất, cộng thêm bảng trung gian theo khóa ngoại để JOIN không bị đứt,
    và các bảng mà ví dụ few-shot đã dùng.
    """

    def __init__(self, schema, top_k: int = 3, min_ratio: float = 0.2):
        self.schema = schema
        self.top_k = top_k
        self.min_ratio = min_ratio
        self.names = list(schema.tables)
        docs = []
        for t in schema.tables.values():
            bits = [t.name.replace("_", " "), t.description, t.keywords]
            for c in t.columns:
                bits += [c.name.replace("_", " "), c.description] + [str(s) for s in c.samples]
            docs.append(" ".join(bits))
        self.index = TfidfIndex(docs)

    def link(self, question: str, hint_tables: set[str] | None = None) -> list[str]:
        scores = dict(zip(self.names, self.index.scores(question)))
        best = max(scores.values()) if scores else 0
        if best <= 0:
            return self.names  # không đoán được thì giữ toàn bộ schema
        ranked = sorted(self.names, key=lambda t: -scores[t])
        keep = {t for t in ranked[: self.top_k] if scores[t] >= best * self.min_ratio}
        keep |= {t for t in (hint_tables or set()) if t in self.schema.tables}
        q = question.lower()
        keep |= {t for concept, ts in self.schema.concepts.items() if concept in q
                 for t in ts if t in self.schema.tables}
        keep |= self._bridges(keep)
        keep |= self._required(keep)
        return [t for t in self.names if t in keep]

    # Bảng bắt buộc đi kèm theo quy tắc nghiệp vụ: doanh thu/số lượng bán cần orders.status.
    REQUIRES = {"order_items": {"orders"}}

    def _required(self, keep: set[str]) -> set[str]:
        return {r for t in keep for r in self.REQUIRES.get(t, set()) if r in self.schema.tables}

    def _bridges(self, keep: set[str]) -> set[str]:
        """Thêm bảng nằm giữa hai bảng đã chọn (ví dụ customers ↔ order_items cần orders)."""
        extra = set()
        for t in self.names:
            if t in keep:
                continue
            if len(self.schema.foreign_key_neighbors(t) & keep) >= 2:
                extra.add(t)
        return extra
