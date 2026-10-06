"""Biểu đồ cho giao diện web (Altair, có sẵn cùng Streamlit).

Cột ngang, sắp xếp theo giá trị giảm dần, nhãn dài đọc được đủ, có tiêu đề trục và số trên đầu cột.
Đổi tên cột sang tên an toàn trước khi vẽ: tên cột của kết quả có thể chứa dấu chấm, ngoặc hay dấu hai chấm
làm hỏng cú pháp rút gọn của Altair; tên thật chỉ dùng làm tiêu đề.
"""
import re

import altair as alt
import pandas as pd

BAR_HEIGHT = 30          # chiều cao mỗi cột (px)
LABEL_LIMIT = 300        # độ dài tối đa của nhãn (px) trước khi bị cắt; tooltip luôn hiện đủ


def _number_format(values) -> str:
    return ",.0f" if all(float(v).is_integer() for v in values if pd.notna(v)) else ",.2f"


def bar_chart(df: pd.DataFrame, label_col: str, value_col: str, color: str = "#0068C9") -> alt.Chart:
    """Biểu đồ cột ngang: mỗi dòng một cột, dài nhất ở trên."""
    data = pd.DataFrame({"nhan": df[label_col].astype(str), "gia_tri": pd.to_numeric(df[value_col])})
    fmt = _number_format(data["gia_tri"])
    base = alt.Chart(data).encode(
        y=alt.Y("nhan:N", sort=alt.EncodingSortField(field="gia_tri", order="descending"),
                title=label_col, axis=alt.Axis(labelLimit=LABEL_LIMIT)),
        x=alt.X("gia_tri:Q", title=value_col, axis=alt.Axis(format=fmt)),
        tooltip=[alt.Tooltip("nhan:N", title=label_col), alt.Tooltip("gia_tri:Q", title=value_col, format=fmt)])
    bars = base.mark_bar(color=color, cornerRadiusEnd=3)
    labels = base.mark_text(align="left", dx=4, color="#555").encode(text=alt.Text("gia_tri:Q", format=fmt))
    return (bars + labels).properties(height=max(BAR_HEIGHT * len(data), 90)).configure_axis(grid=True)


_ISSUED = re.compile(r"\bNo\s*(>|!=|<>)\s*0\b|\bStatus\b|\bTCTCheckStatus\b", re.I)


def draft_note(sql: str | None) -> str | None:
    """Ghi chú giả định khi câu trả lời đọc hóa đơn mà không lọc trạng thái: bảng gồm cả hóa đơn nháp (chưa có số),
    khoảng 91% số dòng. Quy ước 'hóa đơn' mặc định chưa được người nghiệp vụ xác nhận nên cần nói rõ với người dùng."""
    if not sql or not re.search(r"\bVATInvoice\b", sql, re.I) or _ISSUED.search(sql):
        return None
    return ("Số liệu tính cả hóa đơn nháp (chưa có số): khoảng 91% bản ghi trong dữ liệu là nháp. "
            "Hỏi lại với \"chỉ hóa đơn đã phát hành\" nếu bạn cần loại chúng.")
