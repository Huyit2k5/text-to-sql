"""Bộ nhớ sửa lỗi: các cặp (câu hỏi, SQL sai, SQL đúng, bài học) rút ra từ lỗi đã được người nghiệp vụ sửa.

Khi câu hỏi mới giống một câu đã từng làm sai, đưa cặp đó vào prompt để model không lặp lại lỗi.
Theo hướng Memo-SQL (bộ nhớ lỗi - sửa) và các nghiên cứu học liên tục từ phản hồi: phiên bản nhẹ, chỉ truy hồi bằng TF-IDF
như few-shot, có ngưỡng tương đồng để không chèn bài học không liên quan.
"""
import json
import os

from .retrieval import TfidfIndex


class ErrorMemory:
    def __init__(self, entries: list[dict], k: int = 2, min_score: float = 0.2, max_chars: int = 3000):
        self.entries = entries
        self.k = k
        self.min_score = min_score
        self.max_chars = max_chars
        # tags: từ khóa khái niệm (ví dụ "đếm hóa đơn từ dòng hàng") giúp khớp các cách diễn đạt khác nhau của cùng một lỗi
        self.index = TfidfIndex([f"{e['question']} {e.get('tags', '')}" for e in entries]) if entries else None

    @classmethod
    def from_file(cls, path, **kw):
        if not path or not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), **kw)

    def top(self, question: str, exclude_question: str | None = None) -> list[dict]:
        """Các bài học liên quan nhất (đã loại mục có chính câu hỏi này khi đánh giá, tránh rò rỉ đáp án)."""
        if not self.index:
            return []
        ranked = sorted(zip(self.index.scores(question), self.entries), key=lambda x: -x[0])
        out, used = [], 0
        for score, e in ranked:
            if len(out) >= self.k or score < self.min_score:
                break
            if exclude_question and e["question"].strip() == exclude_question.strip():
                continue
            size = len(e["question"]) + len(e.get("wrong_sql", "")) + len(e["correct_sql"]) + len(e["lesson"])
            if used + size > self.max_chars:
                continue
            out.append(e)
            used += size
        return out
