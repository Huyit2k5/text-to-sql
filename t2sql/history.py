"""Khai thác tri thức từ lịch sử truy vấn của analyst (system.query_log của ClickHouse).

Ý tưởng (BIRD-History, LinkedIn "Text-to-SQL for Enterprise Data Analytics"): câu SQL analyst đã chạy chứa những
thứ mà schema và câu hỏi không có: quy ước nghiệp vụ, thói quen viết truy vấn. Thay vì bắt người viết tay từng
quy tắc, ta THỐNG KÊ các quy ước từ lịch sử rồi đưa vào prompt, kèm vài truy vấn lịch sử liên quan.

Chỉ giữ quy ước mà đa số truy vấn tuân theo (min_support) và có đủ số mẫu (min_n): log thật lẫn nhiều thói quen
không nhất quán, và tri thức chưa lọc làm giảm chất lượng (theo LinkedIn).

Các quy ước khai thác được:
  - FINAL: bảng nào hầu như luôn đọc bằng `FROM bảng FINAL` (ReplacingMergeTree)
  - điều kiện lọc phổ biến trên một cột (ví dụ trạng thái hợp lệ)
  - cột giờ nào thường được bọc toTimeZone(...) trước khi lấy ngày / giờ
  - công thức đại lượng: alias `doanh_thu` thường tính bằng biểu thức nào
  - điều kiện JOIN hay dùng
"""
import json
import re
from collections import Counter, defaultdict

from .retrieval import TfidfIndex, tables_in_sql

_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_TIME_FUNCS = {"todate", "toyyyymm", "tohour", "toyear", "tomonth", "toquarter", "tostartofmonth", "tostartofday",
               "tostartofweek", "tostartofquarter", "formatdatetime", "todayofweek", "todatetime", "datediff",
               "toyyyymmdd", "tostartofhour"}
_STATEMENT_TABLES = 6
_MAX_STATEMENTS = 14


def strip_comments(sql: str) -> str:
    return re.sub(r"\s+", " ", _COMMENT.sub(" ", sql or "")).strip()


def comments_of(sql: str) -> str:
    return " ".join(m.lstrip("-/* ").rstrip("*/ ").strip() for m in _COMMENT.findall(sql or ""))


_FORMAT_TAIL = re.compile(r"\s*\bFORMAT\s+\w+\s*;?\s*$", re.I)


def strip_format(sql: str) -> str:
    """Thư viện Python (clickhouse-connect) tự thêm 'FORMAT Native' vào cuối câu; câu của người viết không có."""
    return _FORMAT_TAIL.sub("", sql or "").strip()


def load_history(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def fetch_query_log(client, database: str, exclude_user_prefixes=("t2sql",), limit: int = 50_000) -> list[dict]:
    """Đọc các SELECT thành công của người dùng thật từ system.query_log (cần quyền đọc bảng này).
    Loại: câu lỗi, câu của chính ứng dụng (user t2sql*), câu đo hiệu năng, câu đọc bảng hệ thống."""
    cond = " AND ".join(f"user NOT LIKE '{p}%'" for p in exclude_user_prefixes) or "1"
    rows = client.query(f"""
        SELECT query, user, event_time, query_duration_ms, read_rows FROM system.query_log
        WHERE type = 'QueryFinish' AND query_kind = 'Select' AND has(databases, {{db:String}}) AND {cond}
          AND log_comment NOT LIKE 't2sql-prof%' AND positionCaseInsensitive(query, 'system.') = 0
        ORDER BY event_time DESC LIMIT {int(limit)}""", parameters={"db": database}).result_rows
    seen, out = set(), []
    for q, user, ts, ms, read in rows:
        q = strip_format(q)
        key = strip_comments(q).lower().rstrip(";")
        if key in seen:
            continue
        seen.add(key)
        out.append({"sql": q.strip(), "user": user, "time": str(ts), "duration_ms": ms, "read_rows": int(read)})
    return out


class _Q:
    """Đặc trưng của một truy vấn lịch sử."""
    __slots__ = ("sql", "clean", "tables", "final", "tz_unwrapped", "doc", "conforms", "cols", "formulas")

    def __init__(self, sql):
        sql = strip_format(sql)
        self.sql, self.clean = sql, strip_comments(sql)
        self.tables, self.final, self.tz_unwrapped, self.cols = set(), set(), set(), set()
        self.formulas = {}
        self.conforms = True
        aliases = " ".join(re.findall(r"\bAS\s+([a-z_][a-z0-9_]*)", self.clean, re.I))
        literals = " ".join(re.findall(r"'([^']{2,40})'", self.clean))
        self.doc = f"{comments_of(sql)} {aliases.replace('_', ' ')} {literals}"


class HistoryKnowledge:
    def __init__(self, sqls: list[str], columns: dict[str, set[str]], dialect: str = "clickhouse",
                 min_support: float = 0.6, min_n: int = 8):
        import sqlglot
        self.columns, self.dialect = columns, dialect
        self.min_support, self.min_n = min_support, min_n
        self.queries = [_Q(s) for s in sqls if s and s.strip()]
        final_used, final_hit = Counter(), Counter()
        preds = defaultdict(Counter)          # (bảng, cột) -> Counter(vị từ)
        pred_queries = Counter()              # (bảng, cột) -> số truy vấn có lọc cột đó
        tz_ctx, tz_wrapped, tz_name = Counter(), Counter(), {}
        exprs = defaultdict(Counter)          # (alias, frozenset bảng) -> Counter(biểu thức)
        joins = Counter()
        for q in self.queries:
            q.tables = {t for t in tables_in_sql(q.clean) if t in columns}
            for t in q.tables:
                final_used[t] += 1
                if re.search(rf"\b(?:FROM|JOIN)\s+(?:\w+\.)?{t}(?:\s+(?:AS\s+)?\w+)?\s+FINAL\b", q.clean, re.I):
                    q.final.add(t)
                    final_hit[t] += 1
            try:
                tree = sqlglot.parse_one(q.clean, read=dialect)
            except Exception:
                continue
            self._mine_ast(q, tree, preds, pred_queries, tz_ctx, tz_wrapped, tz_name, exprs, joins)
        self.n = len(self.queries)
        self.final_tables = {t for t in final_used if final_used[t] >= min_n and final_hit[t] / final_used[t] >= min_support}
        self.final_support = {t: (final_hit[t], final_used[t]) for t in self.final_tables}
        self.pred_top = self._top_predicates(preds, pred_queries)
        self.tz_cols = {k: (tz_wrapped[k], tz_ctx[k], tz_name.get(k, "Asia/Ho_Chi_Minh")) for k in tz_ctx
                        if tz_ctx[k] >= min_n and tz_wrapped[k] / tz_ctx[k] >= min_support}
        self.formulas = self._top_formulas(exprs)
        self.joins = [(j, n) for j, n in joins.most_common() if n >= min_n]
        top = {(alias, tabs): expr for alias, tabs, expr, _, _ in self.formulas}
        for q in self.queries:      # câu vi phạm quy ước đa số không được làm ví dụ minh họa
            q.conforms = (all(t in q.final for t in q.tables & self.final_tables)
                          and not (q.tz_unwrapped & set(self.tz_cols))
                          and all(q.formulas.get(k, e) == e for k, e in top.items()))
        self.index = TfidfIndex([q.doc for q in self.queries]) if self.queries else None

    # ------------------------------------------------------------------ khai thác từ cây cú pháp
    def _mine_ast(self, q, tree, preds, pred_queries, tz_ctx, tz_wrapped, tz_name, exprs, joins):
        from sqlglot import exp
        alias_map = {}
        for tb in tree.find_all(exp.Table):
            if tb.name in self.columns:
                alias_map[tb.alias_or_name] = tb.name
                alias_map[tb.name] = tb.name

        def resolve(col):
            if col.table:
                return alias_map.get(col.table)
            cands = [t for t in q.tables if col.name in self.columns.get(t, ())]
            return cands[0] if len(cands) == 1 else None

        seen_pred, seen_ctx, seen_wrapped = set(), set(), set()
        for node in tree.find_all(exp.EQ, exp.NEQ, exp.In):
            left = node.this
            if not isinstance(left, exp.Column) or left.name.endswith("_id"):
                continue
            t = resolve(left)
            if not t:
                continue
            if isinstance(node, exp.In):
                vals = [e for e in node.expressions]
                op = "IN"
            else:
                vals, op = [node.expression], "=" if isinstance(node, exp.EQ) else "!="
            if not vals or not all(isinstance(v, exp.Literal) for v in vals):
                continue
            lits = sorted(("'" + v.name + "'") if v.is_string else v.name for v in vals)
            text = f"{left.name} IN ({', '.join(lits)})" if op == "IN" else f"{left.name} {op} {lits[0]}"
            key = (t, left.name)
            preds[key][text] += 1
            if key not in seen_pred:
                seen_pred.add(key)
                pred_queries[key] += 1
        for col in tree.find_all(exp.Column):
            t = resolve(col)
            if not t:
                continue
            q.cols.add(col.name)
            func, wrapped, in_time = col.parent, False, False
            while func is not None and not isinstance(func, exp.Select):
                if isinstance(func, exp.Anonymous):
                    name = func.name.lower()
                    if name == "totimezone":
                        wrapped = True
                        if len(func.expressions) > 1 and isinstance(func.expressions[1], exp.Literal):
                            tz_name[(t, col.name)] = func.expressions[1].name
                    elif name in _TIME_FUNCS:
                        in_time = True
                elif type(func).__name__.lower() in ("year", "month", "day", "quarter", "cast", "datediff", "timetostr"):
                    in_time = in_time or type(func).__name__.lower() != "cast"
                func = func.parent
            if in_time or wrapped:
                key = (t, col.name)
                if key not in seen_ctx:
                    seen_ctx.add(key)
                    tz_ctx[key] += 1
                if wrapped and key not in seen_wrapped:
                    seen_wrapped.add(key)
                    tz_wrapped[key] += 1
                elif not wrapped:
                    q.tz_unwrapped.add(key)
        for agg in tree.find_all(exp.Sum, exp.Avg, exp.Anonymous):
            if isinstance(agg, exp.Anonymous) and agg.name not in ("uniqExactMerge", "uniqMerge"):
                continue
            cols = list(agg.find_all(exp.Column))
            if not cols:
                continue
            tabs = {resolve(c) for c in cols}
            if None in tabs:
                continue
            clone = agg.copy()
            for c in clone.find_all(exp.Column):
                c.set("table", None)
            parent = agg.parent
            while parent is not None and not isinstance(parent, (exp.Alias, exp.Select)):
                parent = parent.parent
            if isinstance(parent, exp.Alias):
                key = (parent.alias, frozenset(tabs))
                text = clone.sql(dialect=self.dialect)
                exprs[key][text] += 1
                q.formulas[key] = text
        pairs = set()
        for j in tree.find_all(exp.Join):
            on = j.args.get("on")
            if isinstance(on, exp.EQ) and isinstance(on.this, exp.Column) and isinstance(on.expression, exp.Column):
                a, b = resolve(on.this), resolve(on.expression)
                if a and b and a != b:
                    pairs.add(" = ".join(sorted([f"{a}.{on.this.name}", f"{b}.{on.expression.name}"])))
        for p in pairs:
            joins[p] += 1

    def _top_predicates(self, preds, pred_queries):
        out = {}
        for key, counter in preds.items():
            n_q = pred_queries[key]
            if n_q < self.min_n:
                continue
            top = [(t, c) for t, c in counter.most_common(2) if c >= self.min_n and c / n_q >= 0.25]
            if top and top[0][1] / n_q >= 0.5:
                out[key] = (top, n_q)
        return out

    def _top_formulas(self, exprs):
        out = []
        for (alias, tabs), counter in exprs.items():
            total = sum(counter.values())
            expr, c = counter.most_common(1)[0]
            if re.search(r"\b[A-Z][A-Z_]{2,}\(", expr):
                continue        # sqlglot viết lại hàm (DATE_DIFF...): không còn là cách viết ClickHouse gốc
            if total >= self.min_n and c / total >= self.min_support and alias:
                out.append((alias, tabs, expr, c, total))
        return sorted(out, key=lambda x: -x[4])

    # ------------------------------------------------------------------ đưa vào prompt
    def statements(self, tables: set[str]) -> list[str]:
        out = []
        for t in sorted(self.final_tables & tables):
            hit, used = self.final_support[t]
            out.append(f"Bảng `{t}`: {hit}/{used} truy vấn đọc bằng `FROM {t} FINAL` (có alias thì `FROM {t} AS x FINAL`).")
        for (t, c), (top, n_q) in sorted(self.pred_top.items(), key=lambda kv: -kv[1][1]):
            if t in tables:
                shown = "; ".join(f"`{p}` ({100 * k / n_q:.0f}%)" for p, k in top)
                out.append(f"Điều kiện lọc `{c}` trên `{t}` (trong {n_q} truy vấn có lọc cột này): {shown}.")
        for (t, c), (wrapped, ctx, tz) in sorted(self.tz_cols.items()):
            if t in tables:
                out.append(f"Cột `{c}` của `{t}`: {wrapped}/{ctx} truy vấn bọc `toTimeZone({c}, '{tz}')` trước khi lấy ngày / giờ.")
        for alias, tabs, expr, c, total in self.formulas:
            if tabs <= tables:
                out.append(f"Đại lượng đặt tên `{alias}`: {100 * c / total:.0f}% ({total} truy vấn) tính bằng `{expr}`.")
        joins = [f"`{j}`" for j, n in self.joins if all(p.split(".")[0] in tables for p in j.split(" = "))]
        if joins:
            out.append("Điều kiện JOIN hay dùng: " + ", ".join(joins[:_STATEMENT_TABLES]) + ".")
        return out[:_MAX_STATEMENTS]

    def snippets(self, question: str, tables: set[str], k: int = 2, exclude_columns: set[str] = frozenset(),
                 max_chars: int = 700) -> list[str]:
        if not self.index:
            return []
        scored = sorted(zip(self.index.scores(question), self.queries), key=lambda x: -x[0])
        out, seen = [], set()
        for score, q in scored:
            if score < 0.05 or len(out) >= k:
                break
            if not q.conforms or not q.tables or not q.tables <= tables or q.cols & exclude_columns:
                continue
            shape = re.sub(r"\d+|'[^']*'", "?", q.clean)
            if shape in seen or len(q.sql) > max_chars:
                continue
            seen.add(shape)
            out.append(q.sql)
        return out

    def render(self, tables: set[str], question: str, exclude_columns: set[str] = frozenset(),
               parts: str = "both") -> str:
        """parts: "both" | "conventions" (chỉ thống kê quy ước) | "snippets" (chỉ truy vấn lịch sử liên quan)."""
        lines = self.statements(tables) if parts in ("both", "conventions") else []
        snips = self.snippets(question, tables, exclude_columns=exclude_columns) if parts in ("both", "snippets") else []
        if not lines and not snips:
            return ""
        text = (f"THÓI QUEN RÚT RA TỪ {self.n} TRUY VẤN LỊCH SỬ CỦA ANALYST (đã chạy thành công). Đây là thống kê thói quen "
                f"đa số, không phải chân lý; khi phù hợp với câu hỏi thì làm theo thói quen đa số:")
        if lines:
            text += "\n" + "\n".join(f"- {s}" for s in lines)
        if snips:
            text += "\nMột số truy vấn lịch sử liên quan (chỉ để tham khảo cách viết, không phải đáp án):\n" + "\n---\n".join(snips)
        return text
