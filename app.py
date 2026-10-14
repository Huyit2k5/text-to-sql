"""Demo Streamlit (Mức 3).  Chạy:  streamlit run app.py"""
import os
from dataclasses import replace

import pandas as pd
import streamlit as st

from t2sql import access, charts, config_page, llm_profiles
from t2sql.llm import default_llm
from t2sql.logstore import QueryLogger
from t2sql.pipeline import CONFIGS, TextToSQL
from t2sql.viz import choose_view

st.set_page_config(page_title="Text-to-SQL", page_icon="🗄️", layout="wide")

# Link mời (?invite=...): chỉ hiện trang cấu hình model, không có phần hỏi đáp hay dữ liệu.
if st.query_params.get("invite"):
    config_page.invite_page(st.query_params["invite"])
    st.stop()

EXAMPLES = ["Có bao nhiêu bản ghi trong bảng lớn nhất?", "Còn năm ngoái thì sao?", "Xóa toàn bộ dữ liệu"]   # khi bộ dữ liệu không khai báo example_questions


def database_choices():
    """T2SQL_DATABASE_URL (mặc định) + các T2SQL_DATABASE_URL_<TÊN> khác, ví dụ _CLICKHOUSE."""
    def label(url, with_host=False):
        db = url.rsplit("/", 1)[-1].split("?", 1)[0]
        text = f"ClickHouse · {db}" if db else "ClickHouse"
        if with_host:      # hai server cùng tên database: thêm host để phân biệt (không in tài khoản / mật khẩu)
            text += " @ " + url.split("@")[-1].split("/")[0]
        return text

    urls = [os.environ.get("T2SQL_DATABASE_URL", "").strip()]
    urls += [v.strip() for k, v in sorted(os.environ.items()) if k.startswith("T2SQL_DATABASE_URL_") and v.strip()]
    out = {}
    for u in urls:
        if u and u not in out.values():
            out[label(u) if label(u) not in out else label(u, with_host=True)] = u
    return out or {"(chưa cấu hình T2SQL_DATABASE_URL)": ""}


@st.cache_resource
def get_pipeline(config_name, explain, consistency, db_url, llm_profile=None, llm_version=0):
    cfg = replace(CONFIGS[config_name], explain=explain)
    if consistency:
        cfg = replace(cfg, n_candidates=3)
    return TextToSQL(default_llm(llm_profile), cfg, db=db_url, logger=QueryLogger())   # llm_version: đổi hồ sơ thì tạo lại


with st.sidebar:
    st.header("Cấu hình")
    dbs = database_choices()
    db_label = st.selectbox("Database", list(dbs), disabled=len(dbs) == 1)
    config_name = st.selectbox("Pipeline", list(CONFIGS), index=list(CONFIGS).index("production"))
    explain = st.toggle("Giải thích SQL bằng lời", value=CONFIGS[config_name].explain,
                        help="Thêm một lần gọi model cho mỗi câu hỏi. Tắt đi nếu model chậm.")
    consistency = st.toggle("Self-consistency (3 phương án)", value=CONFIGS[config_name].n_candidates > 1,
                            help="Sinh nhiều câu SQL, chạy cả hai/ba và chọn kết quả được nhiều phương án đồng ý. "
                                 "Tốn 2-3 lần gọi model; cho biết độ tin cậy của câu trả lời.")
    # Vai trò và câu hỏi gợi ý theo bộ dữ liệu của database đang chọn
    # Vai trò đặc quyền (admin: thấy cả dữ liệu cá nhân) bị ẩn, trừ khi nhập đúng T2SQL_ADMIN_PASSWORD hoặc chạy cục bộ
    # với T2SQL_ALLOW_ADMIN=1 (xem t2sql/access.py). Chưa có đăng nhập theo người dùng.
    if access.admin_password() and not access.admin_always_allowed():
        with st.expander("Chế độ quản trị"):
            attempt = st.text_input("Mật khẩu quản trị", type="password", key="admin_pw")
            if attempt:
                st.session_state.admin_unlocked = access.password_matches(attempt)
                if not st.session_state.admin_unlocked:
                    st.error("Sai mật khẩu.")
    privileged = access.admin_always_allowed() or st.session_state.get("admin_unlocked", False)
    llm_profile, llm_version = None, 0
    if privileged:   # chọn model và tạo link mời chỉ dành cho chủ hệ thống: người dùng ngrok không được tiêu khóa API của người khác
        config_page.owner_panel()
        profiles = {p["name"]: p for p in llm_profiles.list_profiles()}
        if profiles:
            choice = st.selectbox("Model", ["Mặc định (.env)"] + list(profiles))
            if choice in profiles:
                llm_profile, llm_version = choice, profiles[choice]["updated_at"]
    try:
        pipe = get_pipeline(config_name, explain, consistency, dbs[db_label] or None, llm_profile, llm_version)
    except Exception as e:  # thiếu SDK / credentials / không kết nối được DB
        st.error(f"Không khởi tạo được pipeline: {e}")
        st.stop()
    roles = access.selectable_roles(pipe.policies, st.session_state.get("admin_unlocked", False))
    if not roles:
        st.error("Bộ dữ liệu này không có vai trò hạn chế nào để hiển thị. Đặt T2SQL_ALLOW_ADMIN=1 nếu chạy cục bộ.")
        st.stop()
    role = st.selectbox("Vai trò người dùng", roles, index=roles.index("analyst") if "analyst" in roles else 0)
    st.caption(pipe.policies[role].describe())
    if st.button("Xóa hội thoại") or st.session_state.get("db_label") != db_label:
        st.session_state.turns = []
        st.session_state.history = []
    st.session_state.db_label = db_label
    st.markdown("**Thử hỏi:**\n" + "\n".join(f"- {e}" for e in (pipe.dataset.example_questions or EXAMPLES)))

st.title(pipe.dataset.docs.get("title") or "Hỏi dữ liệu bằng tiếng Việt")
st.session_state.setdefault("turns", [])
st.session_state.setdefault("history", [])
st.sidebar.caption(f"Database: {pipe.backend.describe()} · Model: {getattr(pipe.llm, 'model', '?')}")


def render(ans, idx):
    if ans.standalone_question and ans.standalone_question != ans.question:
        st.caption(f"Hiểu là: {ans.standalone_question}")
    if ans.kind == "clarify":
        st.info(f"Câu hỏi hơi mơ hồ: {ans.message}")
        return
    if ans.kind in ("cannot", "refused"):
        st.warning(f"Không thể trả lời từ dữ liệu này: {ans.message}")
        return
    if ans.kind == "error":
        st.error(ans.message)
        return
    if ans.agreement:
        votes, total = (int(x) for x in ans.agreement.split("/"))
        if votes == total:
            st.caption(f"✅ {ans.agreement} phương án SQL cho cùng kết quả")
        else:
            st.warning(f"Chỉ {ans.agreement} phương án SQL cho cùng kết quả. Hãy kiểm tra lại câu SQL trước khi dùng số liệu.")
    if any(a.issues for a in ans.attempts):
        fixed = not ans.attempts[-1].issues
        st.caption("🔎 Kết quả ban đầu có dấu hiệu không khớp câu hỏi" + (", model đã sửa lại." if fixed else
                   "; model giữ nguyên câu SQL, hãy kiểm tra lại."))
    if ans.explanation:
        st.write(ans.explanation)
    with st.expander("Câu SQL đã chạy" + (f" (tự sửa {len(ans.attempts) - 1} lần)" if len(ans.attempts) > 1 else ""),
                     expanded=False):
        st.code(ans.sql, language="sql")
        st.caption(f"Bảng đưa vào prompt: {', '.join(ans.tables_in_prompt)} · {ans.latency_ms / 1000:.1f}s")
    res = ans.result
    if not res.ok:
        st.error(res.error)
        return
    if not res.rows:
        st.info("Không có dữ liệu thỏa điều kiện.")
        return
    note = charts.draft_note(ans.sql)
    if note:
        st.caption(note)
    df = pd.DataFrame(res.rows, columns=res.columns)
    view = choose_view(res.columns, res.rows)
    if view["kind"] == "metric":
        v = res.rows[0][0]
        st.metric(res.columns[0], f"{v:,.2f}" if isinstance(v, float) else v)
    elif view["kind"] in ("line", "bar"):
        x = res.columns[view["x"]]
        ys = [res.columns[i] for i in view["y"]]
        if view["kind"] == "bar":
            st.altair_chart(charts.bar_chart(df, x, ys[0]), width="stretch")
        else:
            st.line_chart(df, x=x, y=ys, x_label=x, y_label=", ".join(ys))
        st.dataframe(df, hide_index=True)
    else:
        st.dataframe(df, hide_index=True)
    if res.truncated:
        st.caption(f"Chỉ hiển thị {len(res.rows)} dòng đầu.")
    c1, c2, _ = st.columns([1, 1, 8])
    if c1.button("👍 Đúng", key=f"good{idx}"):
        pipe.logger.feedback(ans.id, True)
        st.toast("Đã ghi nhận")
    if c2.button("👎 Sai", key=f"bad{idx}"):
        pipe.logger.feedback(ans.id, False)
        st.toast("Đã ghi nhận, cảm ơn!")


for i, (q, ans) in enumerate(st.session_state.turns):
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        render(ans, i)

q = st.chat_input("Ví dụ: doanh thu tháng trước là bao nhiêu?")
if q:
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        status = st.empty()

        def on_progress(phase, n, secs):
            label = "Model đang suy nghĩ" if phase == "thinking" else "Model đang viết câu trả lời"
            status.caption(f"⏳ {label}… {n} token · {secs:.0f}s")

        if hasattr(pipe.llm, "set_progress"):
            pipe.llm.set_progress(on_progress)
        with st.spinner("Đang sinh và chạy SQL... (model tự host có thể mất vài phút)"):
            ans = pipe.ask(q, history=st.session_state.history, policy=role)
        status.empty()
        render(ans, len(st.session_state.turns))
    st.session_state.turns.append((q, ans))
    if ans.kind == "result" and ans.result and ans.result.ok:
        st.session_state.history.append({"question": ans.standalone_question or q, "sql": ans.sql})
    elif ans.kind == "clarify":
        st.session_state.history.append({"question": q, "sql": None, "clarify": ans.message})
