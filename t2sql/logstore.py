"""Ghi log truy vấn và phản hồi người dùng (JSON Lines) để phân tích và cải thiện sau này."""
import json
import os
import threading
import time

from . import ROOT

DEFAULT_LOG = os.path.join(ROOT, "logs", "queries.jsonl")


class QueryLogger:
    def __init__(self, path: str = DEFAULT_LOG):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()

    def _write(self, rec: dict):
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def log(self, answer, **extra):
        self._write({"type": "query", **answer.to_log(), **extra})

    def feedback(self, answer_id: str, correct: bool, note: str = ""):
        """Người dùng đánh dấu câu trả lời đúng/sai. Câu đúng có thể đưa vào pool few-shot."""
        self._write({"type": "feedback", "id": answer_id, "correct": correct, "note": note})

    def read(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def verified_examples(self):
        """Các cặp (câu hỏi, SQL) được người dùng xác nhận đúng: nguồn bổ sung cho few-shot."""
        recs = self.read()
        good = {r["id"] for r in recs if r["type"] == "feedback" and r["correct"]}
        return [{"question": r.get("standalone_question") or r["question"], "sql": r["sql"]}
                for r in recs if r["type"] == "query" and r["id"] in good and r.get("sql")]
