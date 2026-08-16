# -*- coding: utf-8 -*-
"""
views/tab3_assistant.py —— Tab3 课程 AI 助教

- 基于当前课程/章节上下文问答（带最近 6 轮对话历史，切换课程自动清空）。
- 回答采用流式打字输出（st.write_stream），降低等待焦虑。
"""

import streamlit as st

from core import data, llm


def render_tab3():
    """Tab3 入口：聊天界面 + 流式 AI 助教回答。"""
    st.subheader("💬 课程 AI 助教")
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)

    current_course = st.session_state.get("current_course")
    if not current_course or not current_course.get("kb_name"):
        st.info("请先在「📖 课程大纲与导读」页选择一门已绑定 docx 的课程，即可针对该课程提问。")
        return

    section = st.session_state.get("current_section")
    scope_desc = f"章节「{section['title']}」" if section else "整门课程"
    st.caption(f"当前上下文：**《{current_course['name']}》** · {scope_desc}")

    # 切换课程后自动清空历史
    if st.session_state.get("chat_course_id") != current_course["id"]:
        st.session_state.chat_msgs = []
        st.session_state.chat_course_id = current_course["id"]

    for msg in st.session_state.chat_msgs:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if not api_key:
        st.info("🔌 未配置 API Key：当前为离线模式，无法使用 AI 助教。请在左侧「API 设置」填入 Key 后重试。")
        return

    prompt = st.chat_input(f"向助教提问《{current_course['name']}》…")
    if prompt:
        st.session_state.chat_msgs.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            try:
                system, user = data.build_qa_prompt(current_course, prompt, section)
                answer = st.write_stream(llm.call_llm_stream(user, system, api_key, model))
            except Exception as e:
                answer = f"❌ AI 调用失败：{llm.humanize_error(e)}"
                st.markdown(answer)
        st.session_state.chat_msgs.append({"role": "assistant", "content": answer})
        st.rerun()
