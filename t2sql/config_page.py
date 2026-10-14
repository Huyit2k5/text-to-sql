"""Giao diện Streamlit cho hồ sơ model qua MCP: trang của người được mời và bảng điều khiển của chủ hệ thống."""
import json
import os

import streamlit as st

from . import llm_profiles as lp
from .llm import LLMError
from .mcp_llm import McpLLM, guess_mapping, probe_tools

NONE = "(không có, gộp vào prompt)"
TRANSPORTS = {"Streamable HTTP (khuyến nghị)": "http", "SSE (cũ)": "sse"}


def invite_page(token: str):
    """Trang chỉ có phần cấu hình: người cầm link mời không thấy phần hỏi đáp hay dữ liệu."""
    st.title("Kết nối model của bạn")
    if not lp.check_invite(token):
        st.error("Link mời không hợp lệ, đã hết hạn hoặc đã được dùng. Hãy xin link mới.")
        st.stop()
    st.write("Điền địa chỉ MCP server của model bạn muốn dùng. Hệ thống sẽ gọi một công cụ trên server đó để sinh SQL; "
             "khóa API của bạn vẫn nằm ở phía bạn.")
    st.info("Token bạn nhập ở đây sẽ được lưu trên máy chạy ứng dụng và người quản trị hệ thống có thể đọc được. "
            "Hãy dùng token riêng, quyền tối thiểu và có thời hạn.")
    ss = st.session_state

    st.subheader("1. Kết nối")
    url = st.text_input("Địa chỉ MCP server", placeholder="https://.../mcp", key="cfg_url")
    transport_label = st.selectbox("Kiểu kết nối", list(TRANSPORTS), key="cfg_transport")
    c1, c2 = st.columns(2)
    auth_header = c1.text_input("Tên header xác thực (bỏ trống nếu không cần)", value="Authorization", key="cfg_hdr")
    auth_value = c2.text_input("Giá trị header", type="password", placeholder="Bearer ...", key="cfg_hval")
    transport = TRANSPORTS[transport_label]
    headers = {auth_header: auth_value} if auth_header and auth_value else {}

    if st.button("Dò công cụ"):
        ss.pop("cfg_tested", None)
        reason = lp.validate_url(url)
        if reason:
            st.error(reason)
        else:
            with st.spinner("Đang kết nối..."):
                try:
                    ss.cfg_tools = probe_tools(url, headers, transport, timeout=30)
                except LLMError as e:
                    ss.pop("cfg_tools", None)
                    st.error(str(e))
    tools = ss.get("cfg_tools")
    if tools is None:
        return
    if not tools:
        st.warning("Server không có công cụ nào.")
        return

    st.subheader("2. Chọn công cụ gọi model")
    names = [t["name"] for t in tools]
    tool_name = st.selectbox("Công cụ", names, key="cfg_tool")
    tool = next(t for t in tools if t["name"] == tool_name)
    if tool["description"]:
        st.caption(tool["description"])
    props = list(tool["properties"])
    guess = guess_mapping(tool)
    if not props:
        st.error("Công cụ này không có tham số, không dùng được để gửi prompt.")
        return
    prompt_arg = st.selectbox("Tham số nhận câu hỏi (prompt)", props,
                              index=props.index(guess["prompt_arg"]) if guess["prompt_arg"] in props else 0,
                              key=f"cfg_prompt_{tool_name}")
    sys_opts = [NONE] + [p for p in props if p != prompt_arg]
    system_arg = st.selectbox("Tham số nhận system prompt", sys_opts,
                              index=sys_opts.index(guess["system_arg"]) if guess["system_arg"] in sys_opts else 0,
                              key=f"cfg_system_{tool_name}",
                              help="Nếu công cụ không có tham số này, system prompt được gộp vào đầu prompt.")
    fixed_txt = st.text_area("Tham số cố định (JSON, ví dụ tên model). Bỏ trống nếu không cần", value="", key=f"cfg_fixed_{tool_name}", height=70)
    response_key = st.text_input("Nếu công cụ trả JSON, lấy trường (ví dụ result.text). Bỏ trống = lấy nguyên văn", key=f"cfg_rkey_{tool_name}")
    try:
        fixed = json.loads(fixed_txt) if fixed_txt.strip() else {}
        if not isinstance(fixed, dict):
            raise ValueError
    except ValueError:
        st.error("Tham số cố định phải là một JSON object.")
        return

    profile = {"url": url.strip(), "transport": transport, "tool": tool_name, "prompt_arg": prompt_arg,
               "system_arg": None if system_arg == NONE else system_arg, "fixed_args": fixed,
               "response_key": response_key.strip() or None, "timeout_s": 300}
    if headers:
        profile["auth_header"], profile["auth_value"] = auth_header, auth_value
    signature = json.dumps(profile, sort_keys=True)

    st.subheader("3. Kiểm tra")
    if st.button("Gửi thử một câu"):
        with st.spinner("Đang gọi model..."):
            try:
                reply, secs = McpLLM(dict(profile, name="thu", retries=0)).ping()
                ss.cfg_tested = signature
                st.success(f"Model trả lời sau {secs:.1f} giây: {reply[:200]}")
            except LLMError as e:
                ss.pop("cfg_tested", None)
                st.error(str(e))
    if ss.get("cfg_tested") != signature:
        st.caption("Cần gửi thử thành công với đúng cấu hình hiện tại trước khi lưu.")
        return

    st.subheader("4. Lưu")
    name = st.text_input("Tên hồ sơ", value="leader-llm", key="cfg_name")
    if st.button("Lưu cấu hình", type="primary"):
        try:
            lp.save_profile(name, profile)
        except ValueError as e:
            st.error(str(e))
            return
        lp.consume_invite(token)
        for k in [k for k in ss if k.startswith("cfg_")]:
            del ss[k]
        st.success("Đã lưu. Link mời này không dùng lại được nữa. Bạn có thể đóng trang.")
        st.stop()


def owner_panel():
    """Dành cho chủ hệ thống (sau khi đã qua cổng quản trị): tạo link mời, xem và xóa hồ sơ."""
    with st.expander("Model qua MCP (cấu hình bởi người khác)"):
        c1, c2 = st.columns([1, 2])
        hours = c1.number_input("Hạn (giờ)", min_value=1, max_value=168, value=24, step=1)
        if c2.button("Tạo link mời"):
            tok = lp.create_invite(hours=hours)
            base = os.environ.get("T2SQL_PUBLIC_URL", "").rstrip("/") or "<địa chỉ ứng dụng>"
            st.session_state.last_invite = f"{base}/?invite={tok}"
        if st.session_state.get("last_invite"):
            st.code(st.session_state.last_invite, language=None)
            st.caption("Chỉ hiện một lần. Đặt T2SQL_PUBLIC_URL để link đầy đủ địa chỉ ngrok.")
        profs = lp.list_profiles()
        if not profs:
            st.caption("Chưa có hồ sơ model nào.")
        for p in profs:
            a, b = st.columns([4, 1])
            a.write(f"**{p['name']}** · {p['url']} · công cụ `{p['tool']}`")
            if b.button("Xóa", key=f"del_{p['name']}"):
                lp.delete_profile(p["name"])
                st.rerun()
