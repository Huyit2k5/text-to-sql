"""Đếm token THẬT của đầu ra `ask_data` đã lưu bởi run_via_mcp.py (results/<dialect>_<db>_mcp/*.jsonl).

Dùng tokenizer của chính model đang cấu hình qua điểm cuối /tokenize của vLLM (cùng máy chủ với LLM_BASE_URL).
Nếu điểm cuối không có thì dùng tiktoken cl100k_base làm xấp xỉ (ghi rõ trong kết quả).
Cũng đếm mô tả công cụ ask_data, vì nó nằm trong mỗi yêu cầu của client.

  python experiments/mcp/count_tokens.py
"""
import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from t2sql import ROOT  # noqa: E402  (nạp .env)


def make_counter():
    import httpx
    base = (os.environ.get("LLM_BASE_URL") or "").rstrip("/")
    key = os.environ.get("LLM_API_KEY") or ""
    model = os.environ.get("LLM_MODEL") or ""
    if not model:
        from t2sql.llm import default_llm
        model = getattr(default_llm(), "model", "")
    roots = [base[:-3] if base.endswith("/v1") else base, base]
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    for root in roots:
        try:
            r = httpx.post(root + "/tokenize", json={"model": model, "prompt": "xin chào"}, headers=headers, timeout=30)
            if r.status_code == 200 and "count" in r.json():
                def count(text, root=root):
                    rr = httpx.post(root + "/tokenize", json={"model": model, "prompt": text, "add_special_tokens": False},
                                    headers=headers, timeout=60)
                    rr.raise_for_status()
                    return rr.json()["count"]
                return count, f"tokenizer của model {model} (vLLM /tokenize)"
        except Exception:
            continue
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda text: len(enc.encode(text))), "tiktoken cl100k_base (xấp xỉ, không phải tokenizer của model)"
    except Exception as e:
        sys.exit(f"Không có tokenizer nào dùng được ({e}). Cài tiktoken hoặc mở /tokenize của vLLM.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    count, how = make_counter()
    print("Tokenizer:", how)
    from t2sql import mcp_server
    print("Mô tả công cụ ask_data:", count(mcp_server.DESCRIPTION), "token")
    base = os.path.join(ROOT, "results")
    dirs = glob.glob(os.path.join(base, "*_mcp"))
    if not dirs:
        sys.exit("Chưa có kết quả: chạy experiments/mcp/run_via_mcp.py trước.")
    allc = []
    for path in sorted(glob.glob(os.path.join(dirs[0], "*.jsonl"))):
        name = os.path.basename(path)[:-6]
        recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        toks = [count(r["text"]) for r in recs if r.get("text")]
        est = [r["tokens"] for r in recs if r.get("text")]
        toks_s = sorted(toks)
        allc += toks
        print(f"{name:10s} n={len(toks):3d}  trung vị={statistics.median(toks):6.0f}  p90={toks_s[int(0.9 * (len(toks_s) - 1))]:5d}"
              f"  lớn nhất={toks_s[-1]:5d}   (ước lượng theo ký tự: lớn nhất={max(est)})")
    allc.sort()
    print(f"TẤT CẢ     n={len(allc)}  lớn nhất={allc[-1]}  -> {'ĐẠT' if allc[-1] < 10000 else 'KHÔNG ĐẠT'} tiêu chí dưới 10.000 token")


if __name__ == "__main__":
    main()
