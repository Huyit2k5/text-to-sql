"""Tạo schema_docs.norules.json từ schema_docs.json: bản tài liệu KHÔNG có quy tắc nghiệp vụ.

Dùng cho thí nghiệm "tri thức từ lịch sử truy vấn có thay được việc viết tay quy tắc không?". Bản này giữ nguyên
những gì một database thật thường đã có (mô tả bảng ngắn, quan hệ, từ khóa liên kết, phân quyền, danh mục) và bỏ:
  - toàn bộ business_rules
  - các câu mô tả bảng / cột có chứa quy tắc (FINAL, tỷ giá, hóa đơn hợp lệ, múi giờ...): mô tả bảng được thay bằng
    câu trung tính; mô tả cột ghi đè bị bỏ (khi đó pipeline dùng COMMENT gốc của cột trong ClickHouse).
Kiểu dữ liệu vẫn hiện trong schema (ví dụ DateTime('UTC'), Enum8 với tên giá trị).

  python datasets/einvoice/derive_norules_docs.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NEUTRAL = {
    "invoices": "Hóa đơn điện tử",
    "invoice_items": "Dòng hàng hóa, dịch vụ trên hóa đơn",
    "tax_messages": "Thông điệp trao đổi với cơ quan thuế",
    "api_requests": "Log gọi API tích hợp của doanh nghiệp",
    "daily_seller_stats": "Bảng tổng hợp theo ngày và người bán",
}


def main():
    with open(os.path.join(HERE, "schema_docs.json"), encoding="utf-8") as f:
        docs = json.load(f)
    docs["business_rules"] = []
    for name, t in docs["tables"].items():
        if name in NEUTRAL:
            t["description"] = NEUTRAL[name]
        t.pop("columns", None)
    out = os.path.join(HERE, "schema_docs.norules.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Đã ghi", out)


if __name__ == "__main__":
    main()
