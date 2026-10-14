"""Chạy các bộ đánh giá QUA máy chủ MCP (công cụ ask_data) như một client thật, rồi chấm lại.

Mục đích: kiểm tra đóng gói MCP không làm giảm độ chính xác so với gọi trực tiếp pipeline `production`,
đo độ dài đầu ra (token ước lượng) và độ trễ từ phía client, và đo chất lượng câu nối tiếp khi `history` chỉ có câu hỏi.

Chấm: lấy SQL trong phần "SQL đã chạy:" của kết quả, chạy lại trên database và so với đáp án chuẩn như evaluate.py.
Câu 'clarify'/'cannot' chấm theo status trả về.

  set T2SQL_MCP_TOKEN=<token>      (token tạo bằng `token-create`; không in ra màn hình)
  python experiments/mcp/run_via_mcp.py --set dev holdout ambiguity followup
  python experiments/mcp/run_via_mcp.py --url https://<tên-máy>.<tailnet>.ts.net/mcp --set dev
"""
import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from t2sql import ROOT, datasets  # noqa: E402  (nạp .env)
from t2sql.db import make_backend  # noqa: E402
from t2sql.dialect import example_sql  # noqa: E402
from t2sql.evaluation import results_match  # noqa: E402

DS = os.path.join(ROOT, "datasets", "hddt")
SETS = {"dev": "eval.json", "holdout": "eval_holdout.json", "ambiguity": "eval_ambiguous.json"}

_C = "SELECT count() FROM VATInvoice FINAL WHERE is_deleted = 0 AND ArisingDate >= '{a}' AND ArisingDate < '{b}'"
_S = "SELECT sum(Total) FROM VATInvoice FINAL WHERE is_deleted = 0 AND ArisingDate >= '{a}' AND ArisingDate < '{b}'"
_CN = _C + " AND No > 0"
FOLLOWUP = [   # câu nối tiếp: history chỉ có câu hỏi trước, KHÔNG có SQL
    {"id": "f01", "history": ["Có bao nhiêu hóa đơn trong tháng 5 năm 2025?"], "question": "Còn tháng 4?",
     "sql": [_C.format(a="2025-04-01", b="2025-05-01"), _CN.format(a="2025-04-01", b="2025-05-01")]},
    {"id": "f02", "history": ["Tổng tiền hàng (Total) của các hóa đơn trong tháng 4/2025."], "question": "Còn tháng 5?",
     "sql": [_S.format(a="2025-05-01", b="2025-06-01")]},
    {"id": "f03", "history": ["Có bao nhiêu hóa đơn trong tháng 4/2025?"], "question": "Còn tháng 3?",
     "sql": [_C.format(a="2025-03-01", b="2025-04-01"), _CN.format(a="2025-03-01", b="2025-04-01")]},
    {"id": "f04", "history": ["Có bao nhiêu hóa đơn trong tháng 5 năm 2025?"], "question": "Tổng tiền hàng của chúng là bao nhiêu?",
     "sql": [_S.format(a="2025-05-01", b="2025-06-01")]},
    {"id": "f05", "history": ["Tổng tiền hàng (Total) của các hóa đơn trong tháng 4/2025."], "question": "Cũng tháng đó, có bao nhiêu hóa đơn?",
     "sql": [_C.format(a="2025-04-01", b="2025-05-01"), _CN.format(a="2025-04-01", b="2025-05-01")]},
    {"id": "f06", "history": ["Có bao nhiêu hóa đơn trong tháng 3/2025?", "Còn tháng 4?"], "question": "Và tháng 5?",
     "sql": [_C.format(a="2025-05-01", b="2025-06-01"), _CN.format(a="2025-05-01", b="2025-06-01")]},
]


def approx_tokens(text: str) -> int:
    """Ước lượng thận trọng (không có tokenizer của model): tiếng Việt + SQL + bảng ~ 1 token / 2,5 ký tự."""
    return int(len(text) / 2.5) + 1


def parse(text: str) -> dict:
    m = re.match(r"\[status: (\w+)\]", text or "")
    status = m.group(1) if m else "unknown"
    sql = None
    if "SQL đã chạy:\n" in (text or ""):
        sql = text.split("SQL đã chạy:\n", 1)[1].split("\n\n", 1)[0].strip() or None
    return {"status": status, "sql": sql}


async def call(session, question, history, detail, retries=6):
    """Gọi ask_data như WeKnora: gặp bận/quá hạn thì chờ rồi gửi lại (máy chủ nối vào việc đang chạy)."""
    args = {"question": question, "detail": detail}
    if history:
        args["history"] = history
    t0 = time.perf_counter()
    for attempt in range(retries):
        res = await session.call_tool("ask_data", args)
        text = res.content[0].text if res.content else ""
        if not res.is_error:
            return text, False, time.perf_counter() - t0, attempt
        m = re.search(r"khoảng (\d+) giây", text)
        if m or "quá" in text and "giây" in text:
            await asyncio.sleep(int(m.group(1)) if m else 2)
            continue
        return text, True, time.perf_counter() - t0, attempt
    return text, True, time.perf_counter() - t0, retries


def judge_sql(ex, sql, golds, ordered=False):
    if not sql:
        return False
    r = ex.run(sql, safe=False)
    if not r.ok:
        return False
    return any(results_match(r.rows, g.rows, ordered) for g in golds)


async def run(args):
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
    token = os.environ.get("T2SQL_MCP_TOKEN")
    if not token:
        sys.exit("Đặt biến môi trường T2SQL_MCP_TOKEN (token tạo bằng token-create).")
    ex = make_backend(None, max_rows=100_000, timeout_s=60)
    ds = datasets.for_backend(ex)
    out_dir = os.path.join(ROOT, "results", f"{ex.dialect}_{ds.name}_mcp")
    os.makedirs(out_dir, exist_ok=True)
    summary = {}
    async with create_mcp_http_client(headers={"X-API-Key": token}, timeout=120) as http, \
            streamable_http_client(args.url, http_client=http) as (rd, wr, *_):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            for name in args.set:
                if name == "followup":
                    items = FOLLOWUP
                else:
                    with open(os.path.join(DS, SETS[name]), encoding="utf-8") as f:
                        items = json.load(f)
                if args.limit:
                    items = items[: args.limit]
                print(f"== {name}: {len(items)} câu", flush=True)
                recs = []
                for it in items:
                    text, failed, secs, retried = await call(s, it["question"], it.get("history"), args.detail)
                    p = parse(text)
                    rec = {"id": it["id"], "question": it["question"], "status": "tool_error" if failed else p["status"],
                           "sql": p["sql"], "chars": len(text), "tokens": approx_tokens(text), "secs": round(secs, 1),
                           "retried": retried, "text": text}
                    exp = it.get("expect")
                    if name == "followup":
                        golds = [ex.run(q, safe=False) for q in it["sql"]]
                        rec["correct"] = rec["status"] == "answer" and judge_sql(ex, p["sql"], golds)
                    elif exp:                                  # bộ mơ hồ: chấm theo status
                        rec["correct"] = rec["status"] == exp
                        rec["expect"] = exp
                    else:
                        golds = [ex.run(example_sql({**it, "sql": q}), safe=False) for q in [it["sql"], *it.get("alt_sql", [])]]
                        rec["correct"] = rec["status"] == "answer" and judge_sql(ex, p["sql"], golds, it.get("ordered", False))
                    recs.append(rec)
                    print(f"   {it['id']} {'OK ' if rec['correct'] else 'SAI'} {rec['status']} {rec['secs']}s ~{rec['tokens']}tok", flush=True)
                with open(os.path.join(out_dir, f"{name}.jsonl"), "w", encoding="utf-8") as f:
                    for r in recs:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                toks = sorted(r["tokens"] for r in recs)
                secs = sorted(r["secs"] for r in recs)
                summary[name] = {
                    "n": len(recs), "correct": sum(r["correct"] for r in recs),
                    "tool_errors": sum(r["status"] == "tool_error" for r in recs),
                    "tokens_median": statistics.median(toks), "tokens_p90": toks[int(0.9 * (len(toks) - 1))], "tokens_max": toks[-1],
                    "secs_median": statistics.median(secs), "secs_p90": secs[int(0.9 * (len(secs) - 1))], "secs_max": secs[-1],
                    "retried_calls": sum(1 for r in recs if r["retried"]),
                }
                print("   ", json.dumps(summary[name], ensure_ascii=False), flush=True)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({"detail": args.detail, "sets": summary}, f, ensure_ascii=False, indent=2)
    print("Đã ghi", out_dir)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8780/mcp")
    ap.add_argument("--set", nargs="+", default=["dev"], choices=[*SETS, "followup"])
    ap.add_argument("--detail", default="concise", choices=["concise", "full"])
    ap.add_argument("--limit", type=int, default=None)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
