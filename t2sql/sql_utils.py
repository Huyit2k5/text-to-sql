"""Tách SQL khỏi phản hồi LLM và các tiện ích xử lý chuỗi SQL."""
import re

CANNOT = "CANNOT_ANSWER"
CLARIFY = "CLARIFY"

_FENCE = re.compile(r"```(?:sql|clickhouse)?\s*(.*?)```", re.S | re.I)
_SQL_START = re.compile(r"\b(WITH|SELECT)\b", re.I)


def parse_response(text: str) -> tuple[str, str]:
    """Trả về (kind, payload) với kind ∈ {'sql', 'cannot', 'clarify'}."""
    t = re.sub(r"<think>.*?</think>|^.*?</think>", "", text or "", flags=re.S).strip()
    for marker, kind in ((CANNOT, "cannot"), (CLARIFY, "clarify")):
        m = re.search(rf"{marker}\s*:?\s*(.*)", t, re.S)
        if m and not _FENCE.search(t[: m.start()]):
            return kind, m.group(1).strip() or marker
    return "sql", extract_sql(t)


def extract_sql(text: str) -> str:
    """Bỏ markdown fence, chữ giải thích thừa; giữ một câu SQL."""
    t = (text or "").strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    else:
        t = t.replace("```", "")
        m = _SQL_START.search(t)
        if m:
            t = t[m.start():]
    # Cắt phần giải thích sau câu lệnh: dừng ở một đoạn (sau dòng trống) trông như
    # văn xuôi. Không tách theo ';' ở đây, để lớp an toàn còn thấy được câu lệnh thứ hai.
    paragraphs = re.split(r"\n\s*\n", t)
    kept = [paragraphs[0]]
    for p in paragraphs[1:]:
        if _looks_like_prose(p):
            break
        kept.append(p)
    return "\n\n".join(kept).strip().rstrip(";").strip()


_SQL_WORDS = {"SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "ON",
              "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "EXCEPT", "INTERSECT", "WITH",
              "AND", "OR", "CASE", "WHEN", "THEN", "ELSE", "END", "AS", "(", ")", "--", ","}


def _looks_like_prose(paragraph: str) -> bool:
    first = paragraph.strip().split("\n")[0].strip()
    if not first:
        return False
    word = re.split(r"[\s(]", first, maxsplit=1)[0].upper()
    if word in _SQL_WORDS or first[0] in "(),":
        return False
    return bool(re.search(r"[^\x00-\x7f]", first)) or first.endswith((".", ":")) or len(first.split()) > 6


def strip_comments_and_strings(sql: str) -> str:
    """Thay nội dung chuỗi/comment bằng khoảng trắng để quét từ khóa an toàn."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        elif ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # '' escape
                        j += 2
                        continue
                    break
                j += 1
            out.append(ch + " " + ch if ch == "'" else sql[i:j + 1])  # giữ tên định danh "..."
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Tách theo ';' nằm ngoài chuỗi/comment. Bỏ câu rỗng."""
    parts, buf, i, n = [], [], 0, len(sql)
    quote = None
    while i < n:
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            buf.append(sql[i:j])
            i = j
            continue
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j == -1 else j + 2
            buf.append(sql[i:j])
            i = j
            continue
        elif ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
        elif ch == ";":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if strip_comments_and_strings(p).strip()]
