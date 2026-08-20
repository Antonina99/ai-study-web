# -*- coding: utf-8 -*-
"""
views/tab1_course.py —— Tab1 课程大纲与导读

- 左侧：模块 → 课程 → 章节 三级级联目录（重点模块高亮）。
- 右侧：课程详情看板，采用「二级 Tab」减负：
  关键词/摘要置顶 → （🧠 思维导图 | 🎯 考点与测评 | 📚 章节速览）。
- 课程内「求职实战模拟测评」：独立状态键（cans_ / current_submitted / current_quiz），与 Tab2 互不干扰。
"""

import streamlit as st

from core import data, llm
from views import tab4_review

# 无默认选择的占位选项（用户未主动选择前，提交会被拦截）
PLACEHOLDER = "（请选择答案）"


def _render_keywords(keywords):
    """稳定渲染关键词标签：优先 st.tags（Streamlit 1.45+），旧版本/异常时回退 Markdown 胶囊。"""
    if not keywords:
        st.caption("（暂无关键词，配置 API Key 后可由 AI 自动提取）")
        return
    if hasattr(st, "tags"):
        try:
            st.tags(list(keywords))
            return
        except Exception:
            pass
    st.markdown("　".join(f"`{k}`" for k in keywords))


def _submit_course_quiz(quiz):
    """提交课程内测评：校验完整性，并把错题记录到 Session State 错题本（不落盘 SQLite）。"""
    for i, q in enumerate(quiz):
        if data.ans_index(q, st.session_state.get(f"cans_{i}")) is None:
            st.warning("还有题目未作答，请完成所有题目后再提交。")
            return
    for i, q in enumerate(quiz):
        user_ans = data.ans_index(q, st.session_state.get(f"cans_{i}"))
        if user_ans != q["answer"]:
            tab4_review.record_wrong_question(q, user_ans)
    st.session_state.current_submitted = True
    st.rerun()


def render_chapter_completion_toggle(chapter_id):
    """章节学习打卡：勾选后计入 Session State 学习进度（侧边栏进度条实时更新）。"""
    is_completed = chapter_id in st.session_state.completed_chapters
    if st.checkbox("✅ 标记本节为已完成", value=is_completed, key=f"chk_{chapter_id}"):
        st.session_state.completed_chapters.add(chapter_id)
    else:
        st.session_state.completed_chapters.discard(chapter_id)


def render_course_quiz():
    """课程详情页「求职实战测评」渲染器：读取 st.session_state.current_quiz。

    - 独立作答状态（cans_ / current_submitted），与 Tab2 的 ans_ / submitted 互不干扰；
    - 复用 opt_labels / ans_index 与结构化解析（为什么对 / 其他选项错在哪 / 面试加分点）。
    """
    quiz = st.session_state.get("current_quiz") or []
    if not quiz:
        return
    submitted = st.session_state.get("current_submitted", False)

    st.markdown(f"**已生成 {len(quiz)} 道求职实战题**" + ("（已提交，可查看解析）" if submitted else ""))
    for i, q in enumerate(quiz):
        col_l, col_r = st.columns([3, 2])
        with col_l:
            st.markdown(f"**第 {i + 1} 题**")
            st.write(q["q"])
            st.radio(
                "你的答案",
                options=[PLACEHOLDER, *data.opt_labels(q)],
                key=f"cans_{i}",
                disabled=submitted,
            )
        with col_r:
            if submitted:
                user_ans = data.ans_index(q, st.session_state.get(f"cans_{i}"))
                is_right = user_ans == q["answer"]
                correct_letter = chr(65 + q["answer"])
                if is_right:
                    st.success("✅ 回答正确")
                else:
                    st.error("❌ 回答错误")
                    st.markdown(f"正确答案：**{correct_letter}**")
                analysis = q.get("analysis") or {}
                if analysis.get("correct_reason"):
                    st.success(f"**为什么选 {correct_letter}**：{analysis['correct_reason']}")
                if analysis.get("wrong_reasons"):
                    st.warning(f"**其他选项错在哪**：{analysis['wrong_reasons']}")
                if analysis.get("interview_tips"):
                    st.info(analysis["interview_tips"])
                elif q.get("explain"):
                    st.markdown(f"**解析**：{q['explain']}")
        st.divider()

    if not submitted:
        if st.button("提交答案并查看解析", type="primary", key="btn_submit_course_quiz"):
            _submit_course_quiz(quiz)
    else:
        correct = sum(
            1 for i, q in enumerate(quiz)
            if data.ans_index(q, st.session_state.get(f"cans_{i}")) == q["answer"]
        )
        st.success(f"🎉 得分：**{correct} / {len(quiz)}**")
        if st.button("🔄 重新作答", key="btn_reset_course_quiz"):
            st.session_state.current_submitted = False
            for k in [k for k in st.session_state.keys() if k.startswith("cans_")]:
                del st.session_state[k]
            st.rerun()


def render_course_detail(item, section=None, career_direction=None):
    """渲染一门课程的详情看板（P2 减负：二级 Tab 拆解长页面）。

    - section 非 None：章节聚焦视图，直接展示该章节清洗后的干货正文；
    - 整门课程视图：
      A. 关键资产置顶：核心关键词 + 全文摘要；
      B. 二级 Tab：🧠 思维导图 | 🎯 考点与测评 | 📚 章节速览。
    """
    kb_name = item.get("kb_name")
    st.subheader(f"📖 {item['name']}")
    if section:
        st.caption(f"课程 ID：`{item['id']}`　·　当前章节：**`{section.get('ts')}` {section.get('title')}**")
    else:
        st.caption(f"课程 ID：`{item['id']}`　·　整门课程")
    if not kb_name:
        st.warning("该课程暂未在「课程原文及导读」文件夹中找到对应 docx（`课程名_原文` / `课程名_导读`）。放入文件后刷新页面即可自动解析并绑定。")
        return
    course = data.KB["courses"][kb_name]
    sm = course.get("summary") or {}
    org = course.get("original")
    tag = ("导读 ✓" if sm else "") + ("原文 ✓" if org else "")
    st.caption(f"已绑定知识库：`{kb_name}`　{tag}")

    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", data.llm.DEFAULT_MODEL)

    # ---------- 章节聚焦视图 ----------
    if section:
        body = data.kb.clean_text(section.get("body") or "")
        st.markdown("**📄 章节干货正文（已去噪清洗）**")
        if body:
            st.markdown(body)
        else:
            st.info("该章节暂无导读正文。")
        st.divider()
        # 学习打卡：勾选后计入本次会话学习进度（不落盘）
        render_chapter_completion_toggle(f"{item['id']}::{section.get('ts')}")
        st.caption("💡 提示：完整的关键词 / 摘要 / 定制思维导图请在「整门课程」视图查看。")
        return

    # ---------- 整门课程视图 ----------
    data_pack = data.get_clean_course_data(item, career_direction, api_key, model)
    career_name = data.CAREER_DIRECTIONS.get(career_direction, {}).get("name", career_direction)

    # A. 关键资产置顶：核心关键词 + 全文摘要
    st.markdown("### 🔑 核心关键词")
    _render_keywords(data_pack["keywords"])

    st.markdown("### 📌 全文摘要")
    if data_pack["summary"]:
        st.info(data_pack["summary"])
    else:
        st.caption("（暂无摘要，配置 API Key 后可由 AI 自动萃取）")

    # B. 二级 Tab 拆解长页面（P2 减负）
    t_mind, t_quiz, t_sec = st.tabs(["🧠 思维导图", "🎯 考点与测评", "📚 章节速览"])

    with t_mind:
        st.markdown(f"### 🧠 思维导图 · 已为【{career_name}】强化重点")
        if data_pack["mermaid_code"]:
            try:
                st.mermaid(data_pack["mermaid_code"])
            except Exception:
                st.markdown(f"```mermaid\n{data_pack['mermaid_code']}\n```")
        else:
            st.caption("（暂时无法生成思维导图）")

        st.caption("结构说明：根节点为求职方向 → 二级主题分组（核心概念 / 技术栈 / 应用场景 / 面试重点）→ 三级具体知识点，层次 ≤ 3 级。")
        with st.expander("📋 查看 / 复制 Mermaid 源码", expanded=False):
            st.code(data_pack["mermaid_code"], language="mermaid")

        with st.expander("📖 查看清洗后的精炼课程干货", expanded=False):
            if data_pack["interview_points"]:
                st.markdown("**🎯 实战 / 面试考点**")
                for x in data_pack["interview_points"]:
                    st.markdown(f"- {x}")
            if data_pack["interview_points"] and data_pack["clean_text"]:
                st.divider()
            if data_pack["clean_text"]:
                st.markdown(data_pack["clean_text"])
            else:
                st.info("该课程暂无清洗后的干货正文。")

    with t_quiz:
        # 实战/面试考点
        if data_pack["interview_points"]:
            st.markdown("**🎯 实战 / 面试考点**")
            for x in data_pack["interview_points"]:
                st.markdown(f"- {x}")
            st.divider()

        # 求职实战模拟测评：基于本课程干货 + 求职方向实时生成（强依赖 LLM API）
        st.markdown("### 📝 求职实战模拟测评")
        # 切换课程后自动清掉上一门课生成的题目，避免串课
        if st.session_state.get("current_quiz_course") != item["id"]:
            st.session_state.pop("current_quiz", None)
            st.session_state["current_quiz_course"] = item["id"]

        if not api_key:
            st.caption("🔌 未配置 API Key：当前为离线模式。在左侧「API 设置」填入 Key 后，AI 面试官即可基于本课程干货实时出实战题。")
        if st.button("🚀 调用大模型 API 实时生成求职实战题", key=f"btn_gen_course_quiz_{item['id']}", disabled=not api_key):
            with st.spinner("AI 面试官正在根据选定方向与干货内容出题中..."):
                try:
                    quiz_list = data.generate_practical_quiz_api(data_pack["clean_text"], career_direction, num_q=3)
                except Exception as e:
                    st.error(f"❌ AI 调用失败：{llm.humanize_error(e)}")
                    quiz_list = []
            if quiz_list:
                st.session_state["current_quiz"] = quiz_list
                st.session_state["current_submitted"] = False
                for k in [k for k in st.session_state.keys() if k.startswith("cans_")]:
                    del st.session_state[k]
                st.success(f"✅ 已根据【{career_name}】方向生成本课程实战测评题。")
            else:
                st.warning("未生成题目：请确认已配置 API Key，且本课程已有清洗干货内容。")
        render_course_quiz()

    with t_sec:
        sections = sm.get("sections", [])
        if sections:
            st.markdown(f"**📚 章节速览**（{len(sections)} 章）")
            for s in sections:
                with st.expander(f"`{s['ts']}` {s['title']}"):
                    st.write(s.get("body", "") or "（无正文）")
        else:
            st.info("该课程暂无章节速览。")


def render_tab1(selected_job):
    """Tab1 入口：左侧三级级联目录 + 右侧课程详情看板。"""
    col_dir, col_detail = st.columns([1, 2], gap="large")

    with col_dir:
        st.subheader("📚 课程目录")
        st.caption("模块 → 课程 → 章节 两级联动")
        # 第一级：模块
        module_labels = [m["name"] for m in data.MODULES]
        sel_module = st.radio("选择模块", options=module_labels, key="tab1_module")
        module_no = next(mm["no"] for mm in data.MODULES if mm["name"] == sel_module)
        m = next((mm for mm in data.MODULES if mm["no"] == module_no), data.MODULES[0])

        # 第二级：课程
        sub = [c for c in data.COURSE_INDEX if c["module_no"] == module_no]
        course_labels = [f"{c['id']}｜{c['name']}" for c in sub]
        sel_course = st.selectbox("选择课程", options=course_labels, key="tab1_course")
        cid = sel_course.split("｜")[0]
        current_course = next(c for c in data.COURSE_INDEX if c["id"] == cid)

        # 第三级：章节（来自知识库导读，可「整门课程」）
        section_labels = ["整门课程"]
        sections = []
        if current_course.get("kb_name"):
            sections = (data.KB["courses"][current_course["kb_name"]].get("summary") or {}).get("sections", [])
            section_labels += [f"{s['ts']}｜{s['title']}" for s in sections]
        sel_section = st.selectbox("选择章节（可选）", options=section_labels, key="tab1_section")
        current_section = None
        if current_course.get("kb_name") and sel_section != "整门课程":
            idx = section_labels.index(sel_section) - 1
            current_section = sections[idx]

        st.session_state.current_course = current_course
        st.session_state.current_section = current_section

        st.divider()
        st.markdown(f"**模块说明**：{m['desc']}")
        hits = data.module_hits(m, data.CAREER_DIRECTIONS[selected_job]["focus"])
        if hits:
            st.success(f"⭐ 本模块是 **{data.CAREER_DIRECTIONS[selected_job]['name']}** 的重点模块")
        st.write(f"💡 {m['why']}")
        st.caption(f"该模块共 {len(sub)} 门课；选中的课程已入库：" + ("✅" if current_course["kb_name"] else "❌ 未绑定"))

    with col_detail:
        render_course_detail(st.session_state.current_course, st.session_state.current_section, selected_job)
