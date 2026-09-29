"""Chọn cách hiển thị phù hợp với hình dạng kết quả."""
import re

_DATE = re.compile(r"^\d{4}(-\d{2}){0,2}$")


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def choose_view(columns: list[str], rows: list[tuple]) -> dict:
    """Trả về {"kind": "empty"|"metric"|"line"|"bar"|"table", "x": idx, "y": [idx...]}.

    - 1 dòng x 1 cột            -> metric (một con số)
    - cột đầu là ngày/tháng + cột số -> line (xu hướng theo thời gian)
    - cột đầu là nhãn + cột số, <= 30 dòng -> bar (so sánh giữa nhóm)
    - còn lại                   -> table
    """
    if not rows:
        return {"kind": "empty"}
    if len(rows) == 1 and len(columns) == 1:
        return {"kind": "metric"}
    if len(columns) < 2:
        return {"kind": "table"}
    num_cols = [i for i in range(1, len(columns)) if all(_is_num(r[i]) or r[i] is None for r in rows)]
    if not num_cols or len(rows) < 2:
        return {"kind": "table"}
    first = [r[0] for r in rows]
    if all(isinstance(v, str) and _DATE.match(v) for v in first) or \
            (all(isinstance(v, int) for v in first) and columns[0].lower() in ("month", "thang", "quarter", "quy", "year", "nam")):
        return {"kind": "line", "x": 0, "y": num_cols}
    if len(rows) <= 30 and all(isinstance(v, str) for v in first):
        return {"kind": "bar", "x": 0, "y": num_cols[:1]}
    return {"kind": "table"}
