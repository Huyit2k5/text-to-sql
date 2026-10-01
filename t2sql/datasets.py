"""Bộ dữ liệu của một database: tài liệu schema, pool few-shot, bộ đánh giá, phân quyền theo vai trò.

Mỗi database có một thư mục datasets/<tên database>/ với schema_docs.json (bắt buộc), fewshot_pool.json, eval.json.
  Trong schema_docs.json có thể khai báo thêm:
    "sql_dialect": "clickhouse"                       dialect của SQL trong few-shot / bộ đánh giá
    "policies": {"analyst": {"denied_columns": [["buyers", "email"]], "mask_pii": true},
                 "sales": {"allowed_tables": ["sellers", ...]}}
    "requires": {"invoice_items": ["invoices"]}      bảng luôn đi kèm khi schema linking chọn bảng này
    "no_sample_columns": [["buyers", "name"]]        cột không đưa giá trị mẫu vào prompt
    "example_questions": [...]                       câu hỏi gợi ý trên app
"""
import json
import os
from dataclasses import dataclass, field

from . import ROOT
from .safety import POLICIES, Policy

DATASETS_DIR = os.path.join(ROOT, "datasets")


@dataclass
class Dataset:
    name: str
    docs_path: str
    fewshot_path: str | None
    eval_path: str | None
    sql_dialect: str = "clickhouse"
    docs: dict = field(default_factory=dict)
    history_path: str | None = None     # query_history.jsonl (mine_query_log.py): lịch sử truy vấn của analyst

    def docs_path_for(self, variant: str | None) -> str:
        """schema_docs.<variant>.json cạnh file docs chính (dùng để đo ảnh hưởng của phần quy tắc nghiệp vụ)."""
        if not variant:
            return self.docs_path
        path = self.docs_path[:-len(".json")] + f".{variant}.json"
        if not os.path.exists(path):
            raise FileNotFoundError(f"Không có tài liệu biến thể '{variant}': {path}")
        return path

    @property
    def policies(self) -> dict[str, Policy]:
        spec = self.docs.get("policies")
        if not spec:
            return dict(POLICIES)
        out = {}
        for name, p in spec.items():
            out[name] = Policy(name, allowed_tables=set(p["allowed_tables"]) if p.get("allowed_tables") is not None else None,
                               denied_columns={tuple(c) for c in p.get("denied_columns", [])},
                               mask_pii=bool(p.get("mask_pii", False)))
        out.setdefault("admin", Policy("admin"))
        return out

    @property
    def example_questions(self) -> list[str]:
        return list(self.docs.get("example_questions", []))


def _existing(path):
    return path if path and os.path.exists(path) else None


def from_docs(docs_path: str, name: str | None = None) -> Dataset:
    with open(docs_path, encoding="utf-8") as f:
        docs = json.load(f)
    folder = os.path.dirname(os.path.abspath(docs_path))
    return Dataset(name or os.path.basename(folder), docs_path, _existing(os.path.join(folder, "fewshot_pool.json")),
                   _existing(os.path.join(folder, "eval.json")), docs.get("sql_dialect", "clickhouse"), docs,
                   _existing(os.path.join(folder, "query_history.jsonl")))


def for_database(db_name: str | None) -> Dataset:
    """Bộ dữ liệu của database: datasets/<db_name>/schema_docs.json (bắt buộc)."""
    path = os.path.join(DATASETS_DIR, db_name or "", "schema_docs.json")
    if not db_name or not os.path.exists(path):
        raise FileNotFoundError(f"Chưa có bộ dữ liệu cho database '{db_name}': tạo {os.path.join(DATASETS_DIR, str(db_name), 'schema_docs.json')} "
                                "(mô tả bảng / cột, quan hệ, quy tắc nghiệp vụ, phân quyền theo vai trò).")
    return from_docs(path, db_name)


def for_backend(backend) -> Dataset:
    return for_database(getattr(backend, "database_name", None))
