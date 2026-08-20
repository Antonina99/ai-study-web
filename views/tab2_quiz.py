# -*- coding: utf-8 -*-
"""
views/tab2_quiz.py —— Tab2 智能自测与刷题

- 出题范围：全部课程 / 按模块（多选课程）/ 按章节（三级精准限定）。
- AI 实战出题优先（基于清洗干货 + 求职方向 focus 强约束），失败/无 Key 回退离线题库（选项已洗牌）。
- 作答使用「无默认选中」；提交后展示三段式结构化解析 + AI 错题深度解析（流式输出）。
- 答错的题目写入 Session State 错题本（不落盘 SQLite），可在「错题复习」Tab 导出 JSON。
"""

import random
import re

import streamlit as st

from core import data, llm
from views import tab4_review


def _clean_option_text(text):
    """去掉选项文本自带的 A./A、等字母前缀，避免与 format_func 叠加显示。"""
    text = str(text).strip()
    return re.sub(r"^[A-Da-d][\.、,，\s\)\）:：]\s*", "", text)


def generate_quiz(units, num_q, selected_job):
    """按「出题单元」出题：AI 实战出题优先 → 内置实战题库离线兜底。"""
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    questions = []
    ai_units = [u for u in units if u.get("kb_name")]
    job = data.CAREER_DIRECTIONS.get(selected_job, {})
    job_name = job.get("name", selected_job)

    if api_key and ai_units:
        with st.spinner("🤖 AI 正在基于清洗干货与求职方向生成实战面试题…"):
            questions = data.ai_gen_questions(ai_units, num_q, api_key, model, selected_job)
        if questions:
            st.success(f"✅ 本次题目由 AI 结合课程干货与【{job_name}】方向生成（实战 / 面试取向）。")

    if not questions:
        questions = data.fallback_questions(job.get("fallback_job", "agent_developer"), num_q)
        st.caption("🔌 离线兜底：未配置 Key 或 AI 出题失败，已使用【内置实战题库】（非课程索引题；建议配置 API Key 体验 AI 实战出题）。")

    st.session_state.quiz = questions
    st.session_state.quiz_direction = selected_job
    st.session_state.submitted = False
    clear_answers()


def submit_quiz(quiz):
    """提交答卷：把错题记录到 Session State 错题本（不落盘 SQLite）。"""
    for i, q in enumerate(quiz):
        if data.ans_index(q, st.session_state.get(f"ans_{i}")) is None:
            st.warning("还有题目未作答，请完成所有题目后再提交。")
            return
    for i, q in enumerate(quiz):
        user_ans = data.ans_index(q, st.session_state.get(f"ans_{i}"))
        if user_ans != q["answer"]:
            tab4_review.record_wrong_question(q, user_ans)
    st.session_state.submitted = True
    st.rerun()


def clear_answers():
    """清空 Tab2 作答状态键（ans_*）。"""
    for k in [k for k in st.session_state.keys() if k.startswith("ans_")]:
        del st.session_state[k]


def _render_ai_explain(q, user_ans, api_key, model, i):
    """AI 错题深度解析：流式打字输出（st.write_stream），结果缓存到 session。"""
    ai_key = f"ai_explain_{i}"
    if ai_key in st.session_state:
        st.info(st.session_state[ai_key])
        return
    if st.button(f"🤖 AI 解析：为什么选 {chr(65 + q['answer'])} 不选我选的", key=f"btn_ai_{i}"):
        try:
            system, user = llm.build_explain_prompt(q, user_ans)
            st.session_state[ai_key] = st.write_stream(llm.call_llm_stream(user, system, api_key, model))
        except Exception as e:
            st.session_state[ai_key] = f"❌ AI 解析调用失败：{llm.humanize_error(e)}"
        st.rerun()


def render_quiz():
    """左右分栏渲染题目：左栏作答（无默认选中），提交后右栏展示解析与 AI 深度解析。"""
    quiz = st.session_state.get("quiz") or []
    if not quiz:
        st.info("暂无题目，请点击「🎯 生成题目」。")
        return
    submitted = st.session_state.get("submitted", False)
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)

    st.markdown(f"**共 {len(quiz)} 题**" + ("（已提交，可查看解析）" if submitted else ""))

    for i, q in enumerate(quiz):
        col_l, col_r = st.columns([3, 2])
        with col_l:
            st.markdown(f"**第 {i + 1} 题**" + (f"　`{q['source']}`" if q.get("source") else ""))
            st.write(q["q"])
            opts = q.get("options") or []
            labels = data.opt_labels(q)
            if opts:
                st.radio(
                    "你的答案",
                    options=opts,
                    format_func=lambda x: f"{labels[opts.index(x)]}. {_clean_option_text(x)}",
                    index=None,
                    key=f"ans_{i}",
                    disabled=submitted,
                )
            else:
                st.warning("该题暂缺选项，请忽略。")

            # 「查看答案」展开开关：未提交也可展开查看正确答案与解析
            with st.expander("📖 查看答案与解析", expanded=False, key=f"exp_ans_{i}"):
                correct_letter = chr(65 + q["answer"])
                st.markdown(f"**正确答案：{correct_letter}**")
                analysis = q.get("analysis") or {}
                if analysis.get("correct_reason"):
                    st.write(f"**解析**：{analysis['correct_reason']}")
                elif q.get("explain"):
                    st.write(q["explain"])
                else:
                    st.caption("该题暂无文字解析。")
        with col_r:
            if submitted:
                user_ans = data.ans_index(q, st.session_state.get(f"ans_{i}"))
                is_right = user_ans == q["answer"]
                correct_letter = chr(65 + q["answer"])
                if is_right:
                    st.success("✅ 回答正确")
                else:
                    st.error("❌ 回答错误")
                    st.markdown(f"正确答案：**{correct_letter}**")

                # 结构化解析：正确原因 / 干扰项误区 / 面试加分点
                analysis = q.get("analysis") or {}
                if analysis.get("correct_reason") or analysis.get("wrong_reasons"):
                    if analysis.get("correct_reason"):
                        st.success(f"**为什么选 {correct_letter}**：{analysis['correct_reason']}")
                    if analysis.get("wrong_reasons"):
                        st.warning(f"**其他选项错在哪**：{analysis['wrong_reasons']}")
                    if analysis.get("interview_tips"):
                        st.info(analysis["interview_tips"])
                elif q.get("explain"):
                    st.markdown(f"**解析**：{q['explain']}")
                else:
                    st.caption("该题暂无文字解析。" + ("可点击下方「AI 解析」让助教讲解。" if (not is_right and api_key) else ""))

                # AI 错题深度解析（仅做错且已配置 Key 时提供，流式输出）
                if not is_right and api_key and user_ans is not None:
                    _render_ai_explain(q, user_ans, api_key, model, i)
        st.divider()

    if not submitted:
        if st.button("提交答案并查看解析", type="primary"):
            submit_quiz(quiz)
    else:
        correct = sum(
            1 for i, q in enumerate(quiz)
            if data.ans_index(q, st.session_state.get(f"ans_{i}")) == q["answer"]
        )
        st.success(f"🎉 得分：**{correct} / {len(quiz)}**")
        if st.button("🔄 重新作答"):
            st.session_state.submitted = False
            clear_answers()
            st.rerun()


def render_tab2(selected_job):
    """Tab2 入口：出题面板 + 题目渲染。"""
    st.subheader("📝 智能自测与刷题")
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    if api_key:
        st.caption(f"🤖 AI 模式已开启（`{model}`）：AI 实战出题（基于清洗干货 + 求职方向）+ AI 错题深度解析。")
    else:
        st.caption("🔌 离线模式：未配置 API Key，使用【内置实战题库】兜底。建议在左侧「API 设置」填入 Key，开启 AI 实战出题与错题解析。")

    job = data.CAREER_DIRECTIONS.get(selected_job, {})

    col_panel, col_opt = st.columns([2, 1], gap="large")

    with col_panel:
        scope = st.radio("出题范围", ["全部课程", "按模块", "按章节"], horizontal=True, key="quiz_scope")
        units = []

        if scope == "全部课程":
            units = [{"name": c["name"], "kb_name": c["kb_name"]} for c in data.COURSE_INDEX]

        elif scope == "按模块":
            module_labels = [m["name"] for m in data.MODULES]
            sel_m = st.selectbox("选择模块", options=module_labels, key="quiz_module")
            module_no = next(mm["no"] for mm in data.MODULES if mm["name"] == sel_m)
            sub = [c for c in data.COURSE_INDEX if c["module_no"] == module_no]
            course_labels = [f"{c['id']}｜{c['name']}" for c in sub]
            sel_cs = st.multiselect("选择课程（可多选）", options=course_labels, key="quiz_courses", default=course_labels)
            for c in sub:
                if f"{c['id']}｜{c['name']}" in sel_cs:
                    units.append({"name": c["name"], "kb_name": c["kb_name"]})

        else:  # 按章节：模块 → 课程 → 章节 三级精准限定
            module_labels = [m["name"] for m in data.MODULES]
            sel_m = st.selectbox("选择模块", options=module_labels, key="quiz_ch_module")
            module_no = next(mm["no"] for mm in data.MODULES if mm["name"] == sel_m)
            sub = [c for c in data.COURSE_INDEX if c["module_no"] == module_no]
            course_labels = [f"{c['id']}｜{c['name']}" for c in sub]
            sel_c = st.selectbox("选择课程", options=course_labels, key="quiz_ch_course")
            cid = sel_c.split("｜")[0]
            course_item = next(c for c in sub if c["id"] == cid)

            sec_labels, sec_map = [], {}
            if course_item["kb_name"]:
                sections = (data.KB["courses"][course_item["kb_name"]].get("summary") or {}).get("sections", [])
                sec_labels = [f"{s['ts']}｜{s['title']}" for s in sections]
                sec_map = {f"{s['ts']}｜{s['title']}": s for s in sections}
            if not sec_labels:
                st.info("该课程暂无章节级导读，将按整门课程出题。")
            sel_secs = st.multiselect(
                "选择章节（可多选，留空=整门课程）", options=sec_labels, key="quiz_ch_sections",
                help="选中具体章节后，AI 将只提取该章节文本精准定向出题。",
            )
            if sel_secs:
                for lab in sel_secs:
                    s = sec_map[lab]
                    units.append({
                        "name": course_item["name"],
                        "kb_name": course_item["kb_name"],
                        "section_ts": s["ts"],
                        "section_title": s["title"],
                    })
            else:
                units.append({"name": course_item["name"], "kb_name": course_item["kb_name"]})

        bound = sum(1 for u in units if u.get("kb_name"))
        st.caption(f"当前出题范围：**{len(units)}** 个出题单元" + (f"（其中 {bound} 个已入库）" if len(units) > 1 else ""))

    with col_opt:
        num_q = st.slider("题目数量", min_value=1, max_value=8, value=3)
        st.write("")
        if st.button("🎯 生成题目", type="primary", use_container_width=True):
            generate_quiz(units, num_q, selected_job)

    # 首次进入或切换求职方向后，自动加载一组离线示例题（不调用 AI，避免首屏等待）
    if (st.session_state.get("quiz") is None
            or st.session_state.get("quiz_direction") != selected_job):
        with st.spinner("正在加载示例题目…"):
            st.session_state.quiz = data.fallback_questions(job.get("fallback_job", "agent_developer"), num_q)
            st.session_state.submitted = False
            st.session_state.quiz_direction = selected_job
            clear_answers()
        if not api_key:
            st.caption("🔌 当前为【内置实战题库】离线示例；配置 API Key 后点击「🎯 生成题目」可获得 AI 实时实战出题。")

    render_quiz()
