"""Chấm execution accuracy và phân nhóm lỗi."""
import itertools
import math
import re

from .retrieval import tables_in_sql
from .sql_utils import strip_comments_and_strings


# ---------------------------------------------------------------- so khớp kết quả
def _canon(v):
    from .db.base import normalize_value
    v = normalize_value(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if v.is_integer():
            return int(v)
        return float(f"{v:.10g}")
    if isinstance(v, str):
        return v.strip()
    return v


def _key(v):
    """Khóa sắp xếp ổn định khi cột có kiểu lẫn lộn."""
    return (0, v) if isinstance(v, (int, float)) else (1, str(v))


# Chế độ nới lỏng: tháng viết "2025-03", ngày đầu tháng "2025-03-01" hoặc số tháng 3 là cùng một đáp án.
_MONTH = re.compile(r"^(\d{4})-(\d{2})(?:-01(?:[T ]00:00:00(?:\.0+)?)?)?$")


def _month_of(v):
    m = _MONTH.match(v) if isinstance(v, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def _close(a, b, lenient=False):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-4, abs_tol=1e-2)
    if lenient:
        ma, mb = _month_of(a), _month_of(b)
        if ma and mb:
            return ma == mb
        for x, y in ((a, mb), (b, ma)):
            if y and isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 12:
                return x == y[1]
    return a == b


def _rows_equal(pred, gold, ordered, lenient=False):
    if len(pred) != len(gold):
        return False
    if not ordered:
        pred = sorted(pred, key=lambda r: tuple(_key(v) for v in r))
        gold = sorted(gold, key=lambda r: tuple(_key(v) for v in r))
    return all(len(p) == len(g) and all(_close(a, b, lenient) for a, b in zip(p, g)) for p, g in zip(pred, gold))


def results_match(pred_rows, gold_rows, ordered=False, allow_extra_columns=False) -> bool:
    """So kết quả thực thi.

    - Không quan tâm tên cột; cho phép hoán vị cột.
    - Không quan tâm thứ tự dòng, trừ khi câu hỏi yêu cầu thứ tự (ordered=True).
    - Số thực so với sai số tương đối 1e-4 (bỏ qua khác biệt do ROUND, thứ tự cộng).
    - allow_extra_columns=True ("lenient"): chấp nhận khi kết quả dự đoán có thêm cột (chỉ số phụ), và coi
      "2025-03", "2025-03-01", số tháng 3 là cùng một tháng.
    """
    pred = [tuple(_canon(v) for v in r) for r in pred_rows]
    gold = [tuple(_canon(v) for v in r) for r in gold_rows]
    if len(pred) != len(gold):
        return False
    if not gold:
        return True
    pc, gc = len(pred[0]), len(gold[0])
    if pc < gc or (pc > gc and not allow_extra_columns):
        return False
    if pc > 8:  # tránh bùng nổ tổ hợp
        return pc == gc and _rows_equal(pred, gold, ordered, allow_extra_columns)
    for perm in itertools.permutations(range(pc), gc):
        proj = [tuple(r[i] for i in perm) for r in pred]
        if _rows_equal(proj, gold, ordered, allow_extra_columns):
            return True
    return False


# ---------------------------------------------------------------- phân nhóm lỗi
ERROR_CATEGORIES = {
    "execution_error": "Lỗi thực thi (SQL sai cú pháp / sai tên cột)",
    "wrong_refusal": "Từ chối / hỏi lại nhầm",
    "should_refuse": "Lẽ ra phải từ chối",
    "wrong_table": "Chọn sai bảng",
    "business_logic": "Hiểu sai nghiệp vụ (trạng thái đơn, công thức doanh thu)",
    "date_function": "Sai hàm / khoảng ngày tháng",
    "wrong_join": "Sai JOIN",
    "wrong_filter": "Sai điều kiện lọc",
    "wrong_columns": "Sai cột kết quả / số cột",
    "wrong_aggregation": "Sai phép gộp / GROUP BY / ORDER-LIMIT",
    "other": "Khác",
}

_LITERAL = re.compile(r"'([^']*)'|\b(\d+(?:\.\d+)?)\b")
_DATE_FUNCS = re.compile(r"\b(strftime|julianday|date|datetime|extract|date_trunc|to_char|date_part"
                         r"|todate|toyear|tomonth|toquarter|tostartof\w+|formatdatetime|datediff|subtract\w+|add\w+s"
                         r")\s*\(|\binterval\b", re.I)


def _literals(sql):
    return {a or b for a, b in _LITERAL.findall(sql or "")}


def _norm(sql):
    return re.sub(r"\s+", " ", strip_comments_and_strings(sql or "")).upper()


def categorize(item: dict, rec: dict) -> str:
    """Phân loại heuristic dựa trên so sánh SQL dự đoán với SQL chuẩn. Dùng để định hướng, không tuyệt đối."""
    gold, pred = item.get("sql"), rec.get("sql")
    if item.get("expect") == "cannot":
        return "should_refuse"
    if rec.get("kind") in ("cannot", "clarify", "refused"):
        return "wrong_refusal"
    if rec.get("kind") == "error" or not rec.get("ok"):
        return "execution_error"
    gt, pt = tables_in_sql(gold), tables_in_sql(pred)
    if gt != pt and not gt <= pt:
        return "wrong_table"
    g_status = re.search(r"STATUS\s*(=|IN)", _norm(gold)) is not None
    p_status = re.search(r"STATUS\s*(=|IN|<>|!=|>|<)", _norm(pred)) is not None
    if g_status != p_status or ("DISCOUNT" in _norm(gold)) != ("DISCOUNT" in _norm(pred)):
        return "business_logic"
    gl, pl = _literals(gold), _literals(pred)
    date_lit = lambda s: {x for x in s if re.match(r"\d{4}(-\d{2})?(-\d{2})?$", x)}
    if bool(_DATE_FUNCS.search(gold)) != bool(_DATE_FUNCS.search(pred)) or date_lit(gl) != date_lit(pl):
        return "date_function"
    if gt != pt or _norm(gold).count(" JOIN ") != _norm(pred).count(" JOIN "):
        return "wrong_join"
    if {x for x in gl if not x.isdigit()} != {x for x in pl if not x.isdigit()}:
        return "wrong_filter"
    if rec.get("pred_ncols") is not None and rec.get("gold_ncols") is not None \
            and rec["pred_ncols"] != rec["gold_ncols"]:
        return "wrong_columns"
    for kw in ("GROUP BY", "ORDER BY", "LIMIT", "DISTINCT", "HAVING"):
        if (kw in _norm(gold)) != (kw in _norm(pred)):
            return "wrong_aggregation"
    return "other"
