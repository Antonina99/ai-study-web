# -*- coding: utf-8 -*-
"""
大模型实战课程 · 智能学习与知识看板（入口文件）

架构分层：
- core/llm.py      —— LLM API 调用（超时/重试/流式）、Prompt 常量、JSON 解析
- core/kb.py       —— docx 解析（时间戳分段、口语去噪、归一化）与缓存
- core/data.py     —— 求职方向/课程大纲/离线题库、知识库加载、课程资产组装、出题逻辑
- views/tab1_course.py / tab2_quiz.py / tab3_assistant.py / tab4_review.py —— 四个 Tab 的 UI 渲染层
- app.py           —— 应用入口：初始化 / 侧边栏 / Tab 调度

说明：
- 求职方向 5 选 1，贯穿课程知识图谱、实战出题与错题解析（focus 强约束注入）。
- 课程整理和测评提供离线规则兜底；AI 助教需要有效 API Key。
- 学习进度（章节打卡）与错题本保存在 Session State（本次会话内有效，不落盘 SQLite），
  错题本可在「错题复习」Tab 一键导出 JSON。
"""

import streamlit as st

from core import data, llm
from views import tab1_course, tab2_quiz, tab3_assistant, tab4_review, workspace_ui

st.set_page_config(page_title="AI 大模型实战求职助手", layout="wide")


# ================================================================ 初始化
def init_session_state():
    """初始化全部会话状态（学习进度/错题本基于 Session State）。"""
    # 运行期检测知识库：放入新 docx 后刷新页面即可自动发现新课程（内部有文件签名缓存，开销极小）
    data.refresh_kb()
    defaults = {
        "api_key": "",
        "path_variant_ai_pm_architect": "product",
        "path_variant_prompt_coding": "coding",
        "llm_model": llm.DEFAULT_MODEL,
        "current_course": data.COURSE_INDEX[0],
        "current_section": None,
        "tab1_detail": "✨ 课程精华",
        "tab1_module": data.MODULES[0]["name"],
        "tab1_course": f"{data.COURSE_INDEX[0]['id']}｜{data.COURSE_INDEX[0]['name']}",
        "tab1_section": "整门课程",
        "quiz": None,
        "submitted": False,
        "quiz_direction": None,
        "chat_msgs": [],
        "chat_course_id": None,
        "cleaned_cache": {},
        # 课程内测评
        "current_quiz": None,
        "current_submitted": False,
        "current_quiz_course": None,
        # 学习进度（本会话内有效，不落盘）
        "completed_chapters": set(),
        # 错题本（本会话内有效，可在「错题复习」Tab 导出 JSON）
        "error_notebook": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ================================================================ 学习进度看板
def _total_chapters():
    """全部知识库课程的章节总数（学习进度看板的进度分母）。"""
    total = 0
    for c in data.COURSE_INDEX:
        kb_name = c.get("kb_name")
        if kb_name:
            sections = data.course_sections(data.KB["courses"][kb_name])
            total += len(sections)
    return total


def render_progress_bar(total_chapters_count):
    """学习进度看板：基于 Session State 的完成章节数动态计算进度条。"""
    completed_count = len(st.session_state.completed_chapters)
    progress = completed_count / total_chapters_count if total_chapters_count > 0 else 0.0
    workspace_ui.render_progress(
        progress,
        f"已完成 {completed_count}/{total_chapters_count} 章",
        key="sidebar_learning_progress",
    )


# ================================================================ 侧边栏
def render_sidebar():
    with st.sidebar:
        st.header("🎯 学习与评估配置")
        selected_job = st.radio(
            "选择目标求职方向：",
            options=list(data.CAREER_DIRECTIONS.keys()),
            format_func=lambda k: data.CAREER_DIRECTIONS[k]["name"],
        )
        job = data.CAREER_DIRECTIONS[selected_job]
        st.caption(job["desc"])
        st.caption("重点能力")
        workspace_ui.render_badges(job["focus"], key=f"sidebar_focus_{selected_job}")

        st.divider()
        st.subheader("🔑 API 设置")
        st.session_state.api_key = st.text_input(
            "API Key", type="password",
            value=st.session_state.get("api_key", ""),
            placeholder="sk-…（DeepSeek / 通义千问）",
        )
        model_labels = [f"{llm.LLM_PROVIDERS[m][0]}（{m}）" for m in llm.LLM_PROVIDERS]
        sel_label = st.selectbox("模型", options=model_labels, index=list(llm.LLM_PROVIDERS).index(st.session_state.llm_model))
        st.session_state.llm_model = sel_label.split("（")[1][:-1]
        if st.session_state.api_key:
            st.caption("✅ 已配置，AI 实战出题 / 错题解析 / 助教均已启用。")
        else:
            st.caption("🔌 离线模式：内置题库与规则降级可完整演示。")

        st.divider()
        with st.expander("📖 使用说明"):
            st.markdown(
                "**Tab 1** 课程学习：模块 → 课程 → 章节级联；课程精华、可折叠岗位课程路径与当前课程知识树、考点测评、章节速览和原文查找。\n\n"
                "**Tab 2** 智能自测与刷题：AI 实战出题优先，失败时使用内置题库；提交后查看结构化解析与可选的 AI 错题深度解析。\n\n"
                "**Tab 3** 课程 AI 助教：结合当前课程/章节文字提问，回答附带可核对的原文依据。\n\n"
                "**Tab 4** 错题复习：本会话内答错的题目集中展示，支持一键导出 JSON。\n\n"
                "📈 学习进度与错题本保存在本次会话中（不落盘），刷新页面会清空；可在「Tab 4」导出错题本备份。"
            )

        st.divider()
        st.subheader("📈 学习进度")
        bound_courses = sum(1 for c in data.COURSE_INDEX if c["kb_name"])
        workspace_ui.render_metric(
            "知识库覆盖",
            f"{bound_courses} / {len(data.COURSE_INDEX)}",
            "已绑定转写文字的课程",
            key="sidebar_kb_metric",
        )
        if data.newly_added:
            st.info(f"🆕 检测到新入库课程：**{data.newly_added}**")
        render_progress_bar(_total_chapters())
        st.caption(f"错题本：{len(st.session_state.error_notebook)} 道（本会话内有效，可在「错题复习」导出）")
        if st.session_state.error_notebook:
            if st.button("📌 重刷错题"):
                st.session_state.quiz = [
                    data.shuffle_question(dict(it["question_data"]))
                    for it in st.session_state.error_notebook
                ]
                st.session_state.submitted = False
                st.session_state.quiz_direction = selected_job
                for k in [k for k in st.session_state.keys() if k.startswith("ans_")]:
                    del st.session_state[k]
                st.toast("已加载错题，请到「Tab 2」作答。")

    return selected_job


# ================================================================ 主区
def main():
    init_session_state()
    workspace_ui.apply_workspace_theme()
    selected_job = render_sidebar()

    workspace_ui.render_workspace_header(
        "AI 大模型实战学习工作台",
        "围绕课程转写文字完成阅读、知识整理、智能自测与问答。",
    )
    pages = ["课程学习", "智能自测", "AI 助教", "错题复习"]
    selected_page = workspace_ui.render_navigation(pages, key="main_workspace_navigation")
    if selected_page == "课程学习":
        tab1_course.render_tab1(selected_job)
    elif selected_page == "智能自测":
        tab2_quiz.render_tab2(selected_job)
    elif selected_page == "AI 助教":
        tab3_assistant.render_tab3()
    else:
        tab4_review.render_error_notebook_tab()

    st.divider()
    st.caption("数据源：`课程原文及导读/` 目录下的 docx 课程原文与导读；AI 输出请以实际为准。")


if __name__ == "__main__":
    main()
