"""Kiểm tra truy vấn nặng CHỈ BẰNG KẾ HOẠCH: không chạy truy vấn, không đọc dữ liệu.

Với mỗi câu SQL mẫu (kiểu model hay sinh khi hỏi "toàn thời gian", nối bảng lớn, GROUP BY nhiều giá trị...):
  - EXPLAIN ESTIMATE: số dòng dự kiến đọc theo bảng (qua backend.estimate_rows, có cả kiểm tra an toàn);
  - EXPLAIN indexes = 1: số phần (part) và granule được chọn sau khi cắt theo khóa/phân vùng;
  - đối chiếu với ngưỡng mềm của bộ dữ liệu và trần cứng đề xuất 40 triệu dòng.

  python experiments/heavy/estimate_only.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from t2sql import datasets  # noqa: E402  (nạp .env)
from t2sql.db import make_backend  # noqa: E402
from t2sql.safety import POLICIES  # noqa: E402

V = "VATInvoice FINAL"
P = "ProductInv FINAL"
M5 = "ArisingDate >= '2025-05-01' AND ArisingDate < '2025-06-01'"
CASES = [
    ("n01", "đếm hóa đơn một tháng (bình thường)", f"SELECT count() FROM {V} WHERE is_deleted = 0 AND {M5}"),
    ("n02", "hóa đơn theo tháng trong 1 năm (bình thường)",
     f"SELECT toStartOfMonth(ArisingDate), count() FROM {V} WHERE is_deleted = 0 AND ArisingDate >= '2025-01-01' AND ArisingDate < '2026-01-01' GROUP BY 1"),
    ("n03", "dòng hàng một tháng (bình thường)",
     f"SELECT count() FROM {P} WHERE is_deleted = 0 AND InvArisingDate >= '2025-05-01' AND InvArisingDate < '2025-06-01'"),
    ("h01", "đếm hóa đơn toàn thời gian", f"SELECT count() FROM {V} WHERE is_deleted = 0"),
    ("h02", "tổng tiền toàn thời gian", f"SELECT sum(Total), sum(Amount) FROM {V} WHERE is_deleted = 0"),
    ("h03", "GROUP BY tên công ty, toàn thời gian",
     f"SELECT ComName, count() c FROM {V} WHERE is_deleted = 0 GROUP BY ComName ORDER BY c DESC LIMIT 5"),
    ("h04", "GROUP BY công ty và tháng, toàn thời gian",
     f"SELECT ComID, toStartOfMonth(ArisingDate) m, sum(Total) FROM {V} WHERE is_deleted = 0 GROUP BY ComID, m"),
    ("h05", "uniqExact tên công ty, toàn thời gian", f"SELECT uniqExact(ComName) FROM {V} WHERE is_deleted = 0"),
    ("h06", "mặt hàng bán chạy nhất, mọi năm",
     f"SELECT Name, sum(Quantity) q FROM {P} WHERE is_deleted = 0 GROUP BY Name ORDER BY q DESC LIMIT 10"),
    ("h07", "đếm dòng hàng toàn thời gian", f"SELECT count(), uniqExact(InvID) FROM {P} WHERE is_deleted = 0"),
    ("h08", "nối hóa đơn với dòng hàng, không lọc ngày",
     f"SELECT v.ComName, sum(p.Total) FROM VATInvoice AS v FINAL INNER JOIN ProductInv AS p FINAL ON v.ComID = p.ComID AND v.id = p.InvID "
     f"WHERE v.is_deleted = 0 AND p.is_deleted = 0 GROUP BY v.ComName ORDER BY 2 DESC LIMIT 5"),
    ("h09", "nối hóa đơn với dòng hàng, một tháng",
     f"SELECT v.ComName, sum(p.Total) FROM VATInvoice AS v FINAL INNER JOIN ProductInv AS p FINAL ON v.ComID = p.ComID AND v.id = p.InvID "
     f"WHERE v.is_deleted = 0 AND p.is_deleted = 0 AND v.{M5} GROUP BY v.ComName ORDER BY 2 DESC LIMIT 5"),
    ("h10", "ORDER BY không lọc ngày (quét toàn bảng)",
     f"SELECT id, ComName, Amount FROM {V} WHERE is_deleted = 0 ORDER BY Amount DESC LIMIT 20"),
    ("h11", "LIKE '%test%' trên tên công ty", f"SELECT count() FROM {V} WHERE is_deleted = 0 AND ComName LIKE '%test%'"),
    ("h12", "hàm cửa sổ theo công ty, toàn thời gian",
     f"SELECT ComID, ArisingDate, Total, row_number() OVER (PARTITION BY ComID ORDER BY ArisingDate) rn FROM {V} WHERE is_deleted = 0"),
    ("h13", "thông tin đầy đủ quanh một công ty không lọc ngày",
     f"SELECT * FROM {V} WHERE is_deleted = 0 AND ComName LIKE '%ABC%' LIMIT 100"),
]

HARD = 40_000_000


def indexes_summary(ex, sql):
    """Tóm tắt EXPLAIN indexes = 1: số phần và granule được chọn / tổng, theo từng chỉ mục."""
    rows = ex._client(POLICIES["admin"]).query("EXPLAIN indexes = 1 " + sql.rstrip("; \n")).result_rows
    text = "\n".join(r[0] for r in rows)
    parts = re.findall(r"Parts:\s*(\d+)/(\d+)", text)
    gran = re.findall(r"Granules:\s*(\d+)/(\d+)", text)
    return (f"{parts[-1][0]}/{parts[-1][1]} phần" if parts else "?") + ", " + (f"{gran[-1][0]}/{gran[-1][1]} granule" if gran else "?")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ex = make_backend(None, max_rows=100, timeout_s=60)
    ds = datasets.for_backend(ex)
    import json
    soft = json.load(open(ds.schema_docs_path, encoding="utf-8")).get("cost_guard_rows", 40_000_000) if getattr(ds, "schema_docs_path", None) else 5_000_000
    print(f"Ngưỡng mềm của bộ dữ liệu: {soft:,} dòng; trần cứng đề xuất: {HARD:,} dòng\n")
    print(f"{'mã':4s} {'ước lượng đọc':>16s}  {'so với ngưỡng':14s} {'cắt theo chỉ mục':32s} mô tả")
    over_hard = []
    for cid, desc, sql in CASES:
        est = ex.estimate_rows(sql)
        if est is None:
            print(f"{cid:4s} {'(không ước lượng được)':>16s}  {'':14s} {'':32s} {desc}")
            continue
        total, per = est
        flag = "trên trần cứng" if total > HARD else ("trên ngưỡng mềm" if total > soft else "dưới ngưỡng")
        try:
            idx = indexes_summary(ex, sql)
        except Exception as e:      # noqa: BLE001
            idx = f"lỗi: {str(e)[:25]}"
        print(f"{cid:4s} {total:16,d}  {flag:14s} {idx:32s} {desc}")
        if total > HARD:
            over_hard.append(cid)
    print("\nCâu vượt trần cứng 40 triệu dòng:", over_hard or "không có")


if __name__ == "__main__":
    main()
