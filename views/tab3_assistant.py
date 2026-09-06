# -*- coding: utf-8 -*-
"""
views/tab3_assistant.py —— Tab3 课程 AI 助教

- 基于当前课程/章节上下文问答（带最近 6 轮对话历史，切换课程自动清空）。
- 回答完成后校验引用标识，再与本地原文依据一起展示。
"""

import streamlit as st

from core import data, llm
from views import workspace_ui


QUICK_QUESTIONS = [
    "总结当前范围的核心知识点",
    "这些内容在面试中会怎么考？",
    "给我一个结合实际项目的例子",
]


def _render_evidence(evidence):
    """展示由本地知识库核对过的课程原文引用。"""
    if not evidence:
        st.warning("当前课程原文中未找到可核对的直接依据；回答中的补充内容来自模型知识。")
        return
    with st.expander(f"📎 课程原文依据（{len(evidence)}）"):
        for entry in evidence:
            st.markdown(
                f"**《{entry['course']}》 · {entry['section']} · "
                f"{entry['marker']} · `{entry['id']}`**"
            )
            st.write(entry["text"])
            st.divider()


def render_tab3():
    """Tab3 入口：工作台式上下文、聊天与快捷提问面板。"""
    workspace_ui.render_section_heading("课程 AI 助教", "基于当前课程或章节文字进行问答")
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)

    current_course = st.session_state.get("current_course")
    if not current_course or not current_course.get("kb_name"):
        st.info("请先在「📖 课程大纲与导读」页选择一门已绑定 docx 的课程，即可针对该课程提问。")
        return

    section = st.session_state.get("current_section")
    scope_desc = f"章节「{section['title']}」" if section else "整门课程"

    # 切换课程后自动清空历史
    if st.session_state.get("chat_course_id") != current_course["id"]:
        st.session_state.chat_msgs = []
        st.session_state.chat_course_id = current_course["id"]

    course = data.KB["courses"].get(current_course["kb_name"]) or {}
    original = course.get("original") or {}
    sections = data.course_sections(course)
    prompt = None

    col_context, col_chat, col_tools = st.columns([.85, 2.05, .9], gap="medium")
    with col_context:
        with st.container(border=True):
            workspace_ui.render_section_heading("当前上下文", "助教只读取此范围")
            st.markdown(f"**{current_course['name']}**")
            st.caption(scope_desc)
            workspace_ui.render_badges(
                ["AI 模式" if api_key else "离线模式", model if api_key else "等待 API Key"],
                key=f"assistant_status_{current_course['id']}",
            )
            st.divider()
            workspace_ui.render_metric(
                "课程章节", len(sections), "可定位学习单元",
                key=f"assistant_sections_{current_course['id']}",
            )
            workspace_ui.render_metric(
                "转写片段", len(original.get("segments") or []), "原文上下文来源",
                key=f"assistant_segments_{current_course['id']}",
            )

    with col_chat:
        with st.container(border=True):
            workspace_ui.render_section_heading("知识对话", "回答将结合课程文字和最近对话")
            if not st.session_state.chat_msgs:
                st.info("可以让助教总结章节、解释概念，或把课程内容转换成面试回答。")
            for msg in st.session_state.chat_msgs:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    if msg["role"] == "assistant":
                        _render_evidence(msg.get("evidence") or [])
            prompt = st.chat_input(
                f"向助教提问《{current_course['name']}》…",
                disabled=not api_key,
                key="assistant_chat_input",
            )

    with col_tools:
        with st.container(border=True):
            workspace_ui.render_section_heading("快捷提问", "从常用学习任务开始")
            for index, question in enumerate(QUICK_QUESTIONS):
                if st.button(
                    question,
                    key=f"assistant_quick_{index}",
                    use_container_width=True,
                    disabled=not api_key,
                ):
                    prompt = question
            st.divider()
            if api_key:
                st.success("AI 助教已就绪")
            else:
                st.warning("请先在侧边栏填写 API Key")

    if prompt:
        st.session_state.chat_msgs.append({"role": "user", "content": prompt})
        try:
            system, user, evidence = data.build_qa_request(current_course, prompt, section)
            with col_chat:
                with st.chat_message("assistant"):
                    answer = llm.call_llm(user, system, api_key, model, max_tokens=1800)
                    answer = data.sanitize_answer_citations(answer, evidence)
                    st.markdown(answer)
                    _render_evidence(evidence)
        except Exception as e:
            answer = f"❌ AI 调用失败：{llm.humanize_error(e)}"
            evidence = []
        st.session_state.chat_msgs.append({
            "role": "assistant", "content": answer, "evidence": evidence,
        })
        st.rerun()
