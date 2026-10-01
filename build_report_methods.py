"""Dựng báo cáo HTML so sánh các phương pháp đã thử trên ClickHouse `einvoice`.

  python build_report_methods.py     ->  report/bao_cao_so_sanh_phuong_phap.html

Đọc summary.json của các thư mục kết quả:
  results/clickhouse_einvoice_run1, results/clickhouse_einvoice   chuỗi cải tiến ban đầu (chỉ bộ dev)
  results/einv_exp     cải tiến thêm (danh mục, chặn truy vấn nặng, tự soát logic)
  results/einv_hist    không quy tắc nghiệp vụ: có / không lịch sử truy vấn
  results/einv_cold    khởi đầu lạnh (không quy tắc, không few-shot): có / không lịch sử
  results/einv_abl     tách phần thống kê quy ước và phần truy vấn minh họa của lịch sử
Chạy rejudge_timeouts.py trên các thư mục thí nghiệm trước khi dựng báo cáo.
"""
import glob
import json
import os
import sys
from datetime import datetime

import t2sql  # noqa: F401  (nạp .env)
from t2sql import ROOT

R = lambda *p: os.path.join(ROOT, "results", *p)

# id, nhãn, họ phương pháp, đầu vào cần chuẩn bị, mô tả
METHODS = [
    ("baseline", "Chỉ có tên bảng và cột", "chain", [], "Schema trần: tên bảng, cột, kiểu, khóa."),
    ("docs", "+ Mô tả cột và quy tắc nghiệp vụ", "chain", ["desc", "rules"],
     "Thêm mô tả bảng / cột, giá trị mẫu và 16 quy tắc nghiệp vụ viết tay (FINAL, hóa đơn hợp lệ, tỷ giá, múi giờ...)."),
    ("fewshot", "+ Few-shot", "chain", ["desc", "rules", "fewshot"], "Thêm 4 ví dụ câu hỏi - SQL gần nhất từ pool 26 câu đã duyệt."),
    ("linking", "+ Chọn bảng liên quan", "chain", ["desc", "rules", "fewshot"], "Chỉ đưa vào prompt các bảng liên quan (TF-IDF + khái niệm + khóa ngoại)."),
    ("selfcorrect", "+ Tự sửa lỗi", "chain", ["desc", "rules", "fewshot"], "SQL lỗi hoặc rỗng thì gửi lại cho model sửa (tối đa 3 lần)."),
    ("shapecheck", "+ Kiểm tra hình dạng kết quả", "chain", ["desc", "rules", "fewshot"], "Bắt lỗi chạy được nhưng sai: thiếu FROM, top N trả thừa dòng, cột nhóm lặp..."),
    ("lookup", "+ Bảng danh mục, gợi ý sửa theo mã lỗi", "extra", ["desc", "rules", "fewshot"],
     "Đưa toàn bộ bảng danh mục nhỏ vào prompt (không tự đoán mã tỉnh, mã ngành...) và gợi ý sửa theo mã lỗi ClickHouse."),
    ("costguard", "+ Chặn truy vấn nặng", "extra", ["desc", "rules", "fewshot"], "EXPLAIN ESTIMATE trước khi chạy; đọc quá 40 triệu dòng thì đề nghị model viết gọn hơn."),
    ("verify", "+ Model tự soát logic", "extra", ["desc", "rules", "fewshot"], "Thêm một lời gọi model soát lỗi logic của SQL + kết quả rồi sửa."),
    ("cold", "Khởi đầu lạnh (mô tả bảng ngắn, không quy tắc, không few-shot)", "history", ["desc"],
     "Database mới: chỉ có mô tả bảng ngắn và COMMENT sẵn có trong ClickHouse."),
    ("cold_snip", "Khởi đầu lạnh + chỉ truy vấn lịch sử minh họa", "history", ["desc", "log"], "Thêm 2 câu SQL lịch sử liên quan, chỉ lấy câu tuân theo quy ước đa số."),
    ("cold_conv", "Khởi đầu lạnh + chỉ thống kê quy ước", "history", ["desc", "log"],
     "Thêm quy ước thống kê từ 700 truy vấn lịch sử: FINAL, điều kiện lọc, toTimeZone, công thức, JOIN."),
    ("cold_history", "Khởi đầu lạnh + cả hai phần của lịch sử", "history", ["desc", "log"], "Thống kê quy ước và truy vấn minh họa."),
    ("norules", "Có few-shot, không quy tắc, không lịch sử", "history", ["desc", "fewshot"], "Có few-shot đã duyệt nhưng không có quy tắc nghiệp vụ viết tay."),
    ("history", "Có few-shot, không quy tắc, + lịch sử", "history", ["desc", "fewshot", "log"], "Như dòng trên, thêm tri thức từ lịch sử truy vấn."),
    ("rules_history", "Đủ quy tắc viết tay + lịch sử", "history", ["desc", "rules", "fewshot", "log"], "Chưa chạy thí nghiệm này."),
]
TAGS = {"desc": "Mô tả bảng", "rules": "Quy tắc viết tay", "fewshot": "Few-shot", "log": "Lịch sử truy vấn"}
FAMILIES = {"chain": "Chuỗi cải tiến ban đầu", "extra": "Cải tiến thêm (cộng dồn lên dòng kiểm tra hình dạng)",
            "history": "Tri thức từ lịch sử truy vấn"}


def load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


def stat(ex_list, by_diff, calls, latency, extra=None):
    ex = [x for x in ex_list if x is not None]
    if not ex:
        return None
    d = {"n_runs": len(ex), "mean": sum(ex) / len(ex), "min": min(ex), "max": max(ex), "runs": ex,
         "by_diff": by_diff, "calls": calls, "latency_ms": latency}
    d.update(extra or {})
    return d


def from_experiment(summary, variant):
    """Kết quả của run_experiments.py: sets.{dev,holdout}.{variant}."""
    out = {}
    for set_name in ("dev", "holdout"):
        v = ((summary or {}).get("sets", {}).get(set_name, {})).get(variant)
        if v:
            out[set_name] = {"n_runs": v["n_runs"], "mean": v["ex_mean"], "min": v["ex_min"], "max": v["ex_max"],
                             "runs": [r["ex"] for r in v["runs"]], "by_diff": v["by_difficulty"],
                             "calls": v["calls_mean"], "latency_ms": v["latency_ms_mean"],
                             "guard": v.get("guard_mean"), "verdicts": v.get("verdicts_mean")}
    return out


def from_chain(variant):
    """Chuỗi cải tiến ban đầu: 2 lượt, chỉ có bộ dev."""
    exs, diffs, calls, lat = [], [], [], []
    for folder in ("clickhouse_einvoice_run1", "clickhouse_einvoice"):
        s = load(R(folder, "summary.json"))
        c = ((s or {}).get("configs") or {}).get(variant)
        if c:
            exs.append(c["ex"])
            diffs.append(c["by_difficulty"])
            calls.append(c["usage"]["calls"])
            lat.append(c["avg_latency_ms"])
    if not exs:
        return {}
    by = {k: sum(d.get(k, 0) for d in diffs) / len(diffs) for k in ("easy", "medium", "hard", "unanswerable")}
    return {"dev": stat(exs, by, sum(calls) / len(calls), sum(lat) / len(lat))}


def rejudge_stats():
    total = fixed = 0
    for path in glob.glob(R("einv_*", "*", "r*", "*", "*.jsonl")):
        for line in open(path, encoding="utf-8"):
            if '"rejudged"' not in line:
                continue
            r = json.loads(line)
            total += 1
            fixed += int(r.get("rejudged") == "đã chạy lại" and r.get("correct"))
    return total, fixed


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    exp, hist = load(R("einv_exp", "summary.json")), load(R("einv_hist", "summary.json"))
    cold, abl = load(R("einv_cold", "summary.json")), load(R("einv_abl", "summary.json"))
    sources = {"lookup": hist, "norules": hist, "history": hist, "cold": cold, "cold_history": cold,
               "cold_conv": abl, "cold_snip": abl, "costguard": exp, "verify": exp}
    methods = []
    for mid, label, fam, needs, desc in METHODS:
        if mid == "shapecheck":
            data = from_experiment(exp, "shapecheck")           # code hiện tại, có cả bộ held-out
            older = from_chain("shapecheck").get("dev")
        elif fam == "chain":
            data, older = from_chain(mid), None
        else:
            data, older = from_experiment(sources.get(mid), mid), None
        methods.append({"id": mid, "label": label, "family": fam, "needs": needs, "desc": desc,
                        "dev": data.get("dev"), "holdout": data.get("holdout"), "older_dev": older})
    total, fixed = rejudge_stats()
    data = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "methods": methods, "tags": TAGS,
            "families": FAMILIES, "rejudge": {"total": total, "fixed": fixed}}
    tpl = os.path.join(ROOT, "report", "template_methods.html")
    html = open(tpl, encoding="utf-8").read()
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    assert "/*__DATA__*/null" in html
    html = html.replace("/*__DATA__*/null", blob)
    out = os.path.join(ROOT, "report", "bao_cao_so_sanh_phuong_phap.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    missing = [m["id"] for m in methods if not m["dev"] and not m["holdout"]]
    print(f"Đã ghi {out} ({len(html) // 1024} KiB). Đã chấm lại {total} câu quá hạn, {fixed} câu thực ra đúng. "
          f"Phương pháp chưa có số liệu: {missing}")


if __name__ == "__main__":
    main()
