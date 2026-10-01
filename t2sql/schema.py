"""Mô hình schema (bảng, cột, khóa) và dựng chuỗi mô tả để đưa vào prompt."""
import json
from dataclasses import dataclass, field

# Cột văn bản tự do hoặc nhạy cảm: không đưa giá trị mẫu vào prompt
# (tránh lộ PII và tránh prompt injection nằm trong dữ liệu).
NO_SAMPLE_COLUMNS = {("customers", "email"), ("customers", "phone"), ("customers", "name"),
                     ("reviews", "comment")}
MAX_SAMPLE_LEN = 40


@dataclass
class Column:
    name: str
    type: str
    pk: bool = False
    fk: str | None = None          # "table.column"
    description: str = ""
    samples: list = field(default_factory=list)


@dataclass
class Table:
    name: str
    columns: list[Column]
    description: str = ""
    row_count: int = 0
    keywords: str = ""              # từ khóa nghiệp vụ, chỉ dùng cho schema linking

    def column_names(self):
        return [c.name for c in self.columns]


class Schema:
    def __init__(self, tables: dict[str, Table], business_rules: list[str] | None = None,
                 concepts: dict[str, list[str]] | None = None):
        self.tables = tables
        self.business_rules = business_rules or []
        self.concepts = concepts or {}   # khái niệm nghiệp vụ -> bảng cần dùng (cho schema linking)
        self.requires: dict[str, set[str]] = {}   # bảng -> bảng luôn phải đi kèm (từ docs "requires")

    def subset(self, table_names):
        keep = {t: self.tables[t] for t in self.tables if t in set(table_names)}
        return Schema(keep, self.business_rules, self.concepts)

    def without_columns(self, denied: set[tuple[str, str]]):
        """Bản sao schema bỏ các cột mà vai trò không được đọc (để model không sinh SQL dùng chúng)."""
        tables = {name: Table(t.name, [c for c in t.columns if (name, c.name) not in denied],
                              t.description, t.row_count, t.keywords)
                  for name, t in self.tables.items()}
        return Schema(tables, self.business_rules, self.concepts)

    # ---------- hiển thị ----------
    def render(self, with_docs: bool = False, rules: bool = True) -> str:
        """with_docs=False: chỉ tên bảng/cột/kiểu/khóa (baseline).
        with_docs=True: thêm mô tả nghiệp vụ, giá trị mẫu, quy tắc nghiệp vụ."""
        parts = []
        for t in self.tables.values():
            head = f"TABLE {t.name}"
            if with_docs and t.description:
                head += f"  -- {t.description} ({t.row_count} dòng)"
            lines = [head]
            for c in t.columns:
                line = f"  {c.name} {c.type}"
                if c.pk:
                    line += " PRIMARY KEY"
                if c.fk:
                    line += f" REFERENCES {c.fk}"
                if with_docs:
                    extra = []
                    if c.description:
                        extra.append(c.description)
                    if c.samples:
                        extra.append("ví dụ: " + ", ".join(repr(v) for v in c.samples))
                    if extra:
                        line += "  -- " + "; ".join(extra)
                lines.append(line)
            parts.append("\n".join(lines))
        text = "\n\n".join(parts)
        if with_docs and rules and self.business_rules:
            text += "\n\nQUY TẮC NGHIỆP VỤ:\n" + "\n".join(f"- {r}" for r in self.business_rules)
        return text

    def foreign_key_neighbors(self, table: str) -> set[str]:
        out = set()
        for c in self.tables[table].columns:
            if c.fk:
                out.add(c.fk.split(".")[0])
        for t in self.tables.values():
            for c in t.columns:
                if c.fk and c.fk.split(".")[0] == table:
                    out.add(t.name)
        return out
