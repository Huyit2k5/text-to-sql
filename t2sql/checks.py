"""Kiểm tra hình dạng kết quả: bắt SQL "chạy được nhưng sai logic" mà không cần gọi thêm model.

Mỗi quy tắc đọc dấu hiệu trong câu hỏi tiếng Việt và so với hình dạng kết quả (số dòng, giá trị lặp,
khoảng giá trị). Khi có nghi vấn, pipeline gửi mô tả nghi vấn cho model để tự kiểm tra lại; model có thể
giữ nguyên SQL nếu nó đúng ý câu hỏi. Quy tắc được giữ bảo thủ: báo nhầm có thể khiến model "sửa" một câu đúng.

Quy tắc:
  R1  câu hỏi hỏi một con số ("bao nhiêu", "tổng", "trung bình"...) và không nhóm  -> đúng 1 dòng
  R2  "mỗi/từng X ... nhất" (đứng đầu trong mỗi nhóm)                              -> cột nhóm không lặp
  R3  "mỗi/từng/theo X" (gộp theo nhóm)                                             -> cột nhóm không lặp nhiều
  R4  "top N" / "N ... nhất"                                                         -> tối đa N dòng
  R5  "... nào ... nhất" không theo nhóm                                             -> 1 dòng (trừ khi bằng điểm)
  R6  "phần trăm" / "tỉ lệ" / "tỉ trọng"                                             -> đúng đơn vị %, tổng tỉ trọng ~100
  R7  mọi câu                                                                        -> không phải toàn NULL
"""
import re
from collections import Counter
from dataclasses import dataclass

_NUM = (int, float)


@dataclass
class Issue:
    rule: str
    message: str


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", (q or "").lower()).strip()


_EACH = re.compile(r"\b(mỗi|từng)\b")
_GROUP = re.compile(r"\b(mỗi|từng)\b|\btheo (?!số lượng|doanh thu|giá|số sao|điểm)")
_LIST = re.compile(r"\b(liệt kê|danh sách|những)\b")
_SCALAR = re.compile(r"\b(bao nhiêu|mấy|tổng|trung bình|tỉ lệ|phần trăm)\b")
_SUPER = re.compile(r"\bnhất\b")
_WHICH = re.compile(r"\bnào\b")
_TOPN = re.compile(r"\btop\s*(\d+)\b|\b(\d+)\s+[^\d,.?]{1,40}?\b(cao|nhiều|thấp|ít|lớn|nhỏ|đắt|rẻ) nhất\b")
# "%" chỉ tính là yêu cầu tỉ lệ khi không đứng sau một con số: "thuế suất 5%" là giá trị lọc, không phải câu hỏi về tỉ lệ
_PERCENT = re.compile(r"phần trăm|(?<![\d.,])\s*%|tỉ lệ phần trăm")
_SHARE = re.compile(r"\b(chiếm|tỉ trọng)\b")
_CHANGE = re.compile(r"\b(tăng|giảm|thay đổi|chênh lệch)\b")


def _text_col(columns, rows):
    """Chỉ số cột chữ đầu tiên (thường là cột nhóm / nhãn)."""
    for i in range(len(columns)):
        vals = [r[i] for r in rows if r[i] is not None]
        if vals and all(isinstance(v, str) for v in vals):
            return i
    return None


def _group_col(columns, rows):
    """Cột chữ có ít giá trị khác nhau nhất: cột nhóm trong kết quả "top N mỗi nhóm"."""
    text = [i for i in range(len(columns))
            if any(r[i] is not None for r in rows) and all(isinstance(r[i], str) for r in rows if r[i] is not None)]
    return min(text, key=lambda i: len({r[i] for r in rows}), default=None)


def _num_cols(columns, rows):
    return [i for i in range(len(columns))
            if rows and all((r[i] is None) or (isinstance(r[i], _NUM) and not isinstance(r[i], bool)) for r in rows)
            and any(r[i] is not None for r in rows)]


def _dupes(values):
    seen, dup = {}, []
    for v in values:
        seen[v] = seen.get(v, 0) + 1
    for v, n in seen.items():
        if n > 1:
            dup.append((v, n))
    return sorted(dup, key=lambda x: -x[1])


def _tied_on_last_numeric(columns, rows):
    """Nhiều dòng nhưng đều bằng điểm ở cột số cuối (hợp lệ cho câu 'nào ... nhất')."""
    nums = _num_cols(columns, rows)
    if not nums:
        return False
    vals = [r[nums[-1]] for r in rows]
    return len(set(round(v, 6) if isinstance(v, float) else v for v in vals)) == 1


def check_result(question: str, columns: list[str], rows: list[tuple]) -> list[Issue]:
    """Trả về danh sách nghi vấn (rỗng = không thấy gì bất thường). Chỉ gọi khi truy vấn chạy thành công."""
    q = _norm(question)
    issues: list[Issue] = []
    if not rows or not columns:
        return issues
    n = len(rows)
    grouped = bool(_GROUP.search(q))
    listing = bool(_LIST.search(q))

    # R7: toàn NULL
    if all(v is None for r in rows for v in r):
        issues.append(Issue("R7", "Kết quả chỉ có giá trị NULL. Có thể điều kiện lọc, JOIN hoặc phép gộp chưa đúng."))
        return issues

    # R4: top N (toàn bộ), hoặc top N trong mỗi nhóm ("top 3 sản phẩm trong từng danh mục")
    m = _TOPN.search(q)
    top_n = int(m.group(1) or m.group(2)) if m else None
    gi = _group_col(columns, rows) if top_n and _EACH.search(q) else None
    if gi is not None and len({r[gi] for r in rows}) * 2 > n:
        gi = None      # cột chữ ít giá trị nhất vẫn gần như duy nhất: đó là cột xếp hạng, không phải cột nhóm
    if gi is not None:
        counts = Counter(r[gi] for r in rows)
        worst, k = counts.most_common(1)[0]
        if k > top_n:
            issues.append(Issue("R4", f"Câu hỏi yêu cầu {top_n} kết quả đứng đầu trong mỗi nhóm nhưng nhóm "
                                      f"'{worst}' có {k} dòng. Có thể thiếu bước giới hạn {top_n} dòng mỗi nhóm."))
        grouped = False            # đã kiểm tra theo nhóm, không áp R2/R3
    elif top_n and n > top_n:
        issues.append(Issue("R4", f"Câu hỏi yêu cầu {top_n} kết quả đứng đầu nhưng kết quả có {n} dòng. "
                                  f"Có thể thiếu ORDER BY ... LIMIT {top_n}."))

    # R2: đứng đầu trong mỗi nhóm
    if grouped and _SUPER.search(q) and not top_n:
        gi = _text_col(columns, rows)
        if gi is not None:
            d = _dupes([r[gi] for r in rows])
            if d:
                ex = ", ".join(f"'{v}' ×{k}" for v, k in d[:3])
                issues.append(Issue("R2", f"Câu hỏi yêu cầu một kết quả đứng đầu cho mỗi nhóm, nhưng cột "
                                          f"`{columns[gi]}` lặp lại ({ex}); kết quả có {n} dòng cho "
                                          f"{len(set(r[gi] for r in rows))} nhóm. Có thể thiếu bước chọn dòng đứng "
                                          f"đầu mỗi nhóm (RANK/ROW_NUMBER hoặc DISTINCT ON)."))

    # R3: gộp theo nhóm mà cột nhóm lặp nhiều (tên trùng lặp lẻ tẻ thì bỏ qua, ví dụ hai khách cùng tên)
    elif grouped and not listing and n >= 4:
        gi = _text_col(columns, rows)
        # nhóm theo nhiều cột chữ (ví dụ loại hóa đơn × có mã/không mã): xét tổ hợp của các cột đó
        text_cols = [i for i in range(len(columns)) if any(r[i] is not None for r in rows)
                     and all(isinstance(r[i], str) for r in rows if r[i] is not None)]
        if gi is not None and len({tuple(r[i] for i in text_cols) for r in rows}) * 2 > n:
            gi = None
        if gi is not None:
            distinct = len(set(r[gi] for r in rows))
            if distinct * 2 <= n:
                issues.append(Issue("R3", f"Kết quả gộp theo nhóm nhưng cột `{columns[gi]}` chỉ có {distinct} giá trị "
                                          f"khác nhau trên {n} dòng. Có thể GROUP BY thừa cột hoặc JOIN làm nhân dòng."))

    # R1: một con số
    if not grouped and not listing and not top_n and _SCALAR.search(q) and not _WHICH.search(q) and n > 1:
        issues.append(Issue("R1", f"Câu hỏi hỏi một con số nhưng kết quả có {n} dòng. "
                                  f"Có thể thiếu phép gộp (SUM/COUNT/AVG) hoặc GROUP BY thừa."))

    # R5: "... nào ... nhất" không theo nhóm
    if (not grouped and not listing and not top_n and _WHICH.search(q) and _SUPER.search(q) and n > 1
            and not _tied_on_last_numeric(columns, rows)):
        issues.append(Issue("R5", f"Câu hỏi hỏi một đối tượng đứng đầu nhưng kết quả có {n} dòng (không bằng điểm). "
                                  f"Có thể thiếu ORDER BY ... LIMIT 1."))

    # R6: phần trăm
    if _PERCENT.search(q) or _SHARE.search(q):
        nums = _num_cols(columns, rows)
        if nums:
            vals = [r[nums[-1]] for r in rows if r[nums[-1]] is not None]
            if vals and _PERCENT.search(q) and all(abs(v) <= 1 for v in vals) and any(v != 0 for v in vals):
                issues.append(Issue("R6", "Câu hỏi hỏi phần trăm nhưng mọi giá trị đều trong khoảng -1..1, có thể đang là "
                                          "tỉ lệ thập phân. Nhân với 100 nếu câu hỏi cần phần trăm."))
            elif vals and not _CHANGE.search(q) and any(v < 0 or v > 100.0001 for v in vals):
                issues.append(Issue("R6", "Tỉ lệ phần trăm nằm ngoài khoảng 0..100. Kiểm tra lại tử số / mẫu số."))
            elif vals and grouped and _SHARE.search(q) and len(vals) > 1 and abs(sum(vals) - 100) > 0.5:
                issues.append(Issue("R6", f"Tỉ trọng các nhóm cộng lại bằng {sum(vals):.2f}%, không phải 100%. "
                                          f"Kiểm tra mẫu số (tổng) có tính trên cùng điều kiện lọc không."))
    return issues


def describe(issues: list[Issue]) -> str:
    return "\n".join(f"- {i.message}" for i in issues)
