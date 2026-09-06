# -*- coding: utf-8 -*-
"""
views/tab1_course.py —— Tab1 课程大纲与导读

- 左侧：模块 → 课程 → 章节 三级级联目录（重点模块高亮）。
- 右侧：课程详情看板，采用「二级 Tab」减负：
  关键词/摘要置顶 → （✨ 课程精华 | 🧠 知识图谱 | 🎯 考点与测评 | 📚 章节速览）。
- 课程内「求职实战模拟测评」：独立状态键（cans_ / current_submitted / current_quiz），与 Tab2 互不干扰。
"""

from html import escape

import streamlit as st

from core import data, llm
from views import tab4_review, workspace_ui

# 无默认选择的占位选项（用户未主动选择前，提交会被拦截）
PLACEHOLDER = "（请选择答案）"


def _render_question_evidence(q, index):
    """在课程测评解析中展示已核对的本地原文。"""
    citations = q.get("citations") or []
    if citations:
        with st.expander(f"📎 查看课程原文依据（{len(citations)}）", key=f"course_evidence_{index}"):
            for entry in citations:
                st.markdown(
                    f"**《{entry['course']}》 · {entry['section']} · "
                    f"{entry['marker']} · `{entry['id']}`**"
                )
                st.write(entry["text"])
                st.divider()
    else:
        st.warning(q.get("citation_status") or "当前课程原文中未找到可核对依据。")


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


def _render_tree_node(label, tags=None, priority=False, detail=""):
    """渲染知识树中的课程或知识节点。"""
    tag_html = "".join(
        f'<span class="knowledge-tree-tag {escape(kind)}">{escape(text)}</span>'
        for text, kind in (tags or [])
    )
    priority_class = " is-priority" if priority else ""
    detail_html = f'<small>{escape(detail)}</small>' if detail else ""
    st.markdown(
        f'<div class="knowledge-tree-node{priority_class}">'
        f'<i></i><span class="knowledge-tree-label">{escape(label)}{detail_html}</span>'
        f'<span class="knowledge-tree-tags">{tag_html}</span></div>',
        unsafe_allow_html=True,
    )


def _render_career_course_tree(current_item, career_direction):
    """按模块展示可折叠课程路径，并标记当前岗位重点课程。"""
    career = data.CAREER_DIRECTIONS.get(career_direction, {})
    current_name = current_item.get("name") or ""
    current_key = data.kb.normalize(current_name)
    bound_keys = {
        data.kb.normalize(course.get("name"))
        for course in data.COURSE_INDEX if course.get("kb_name")
    }
    priorities = {
        course_name: data.course_priority_reasons(course_name, career_direction)
        for module in data.MODULES
        for course_name in module.get("courses", [])
    }
    priority_total = sum(bool(reasons) for reasons in priorities.values())
    st.markdown(
        f'<div class="knowledge-tree-root"><span>目标岗位</span>'
        f'<strong>{escape(career.get("name", career_direction))}</strong>'
        f'<small>{escape(career.get("desc", ""))} · {priority_total} 门重点课程</small></div>',
        unsafe_allow_html=True,
    )
    for module in data.MODULES:
        if module.get("no") == data.EXT_MODULE_NO:
            continue
        courses = module.get("courses", [])
        priority_count = sum(bool(priorities.get(name)) for name in courses)
        contains_current = any(data.kb.normalize(name) == current_key for name in courses)
        label = f"{module['name']}　·　⭐ {priority_count} 门岗位重点"
        with st.expander(label, expanded=contains_current):
            for course_name in courses:
                reasons = priorities.get(course_name) or []
                normalized = data.kb.normalize(course_name)
                tags = []
                if reasons:
                    tags.append(("岗位重点", "priority"))
                if normalized == current_key:
                    tags.append(("当前课程", "current"))
                if normalized in bound_keys:
                    tags.append(("已有文字", "ready"))
                detail = f"重点关联：{' / '.join(reasons)}" if reasons else ""
                _render_tree_node(course_name, tags, bool(reasons), detail)


def _render_course_knowledge_tree(item, groups):
    """渲染当前课程内部的可折叠知识分支。"""
    st.markdown(
        f'<div class="knowledge-tree-root course"><span>当前课程</span>'
        f'<strong>{escape(item.get("name") or "当前课程")}</strong>'
        f'<small>{len(groups)} 个知识分支，可逐层展开查看</small></div>',
        unsafe_allow_html=True,
    )
    for index, group in enumerate(groups):
        items = group.get("items") or []
        with st.expander(f"{group['name']}　·　{len(items)} 个节点", expanded=index == 0):
            for value in items:
                _render_tree_node(str(value))


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
            st.markdown(
                f"**第 {i + 1} 题**　`{q.get('source', '课程测评题')}`"
            )
            st.write(q["q"])
            options = q.get("options") or []
            st.radio(
                "你的答案",
                options=[PLACEHOLDER, *options],
                format_func=lambda value: value if value == PLACEHOLDER else (
                    f"{chr(65 + options.index(value))}. {value}"
                ),
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
                _render_question_evidence(q, i)
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


def _render_original_browser(course, item):
    """渲染课程原文关键词检索和分页浏览。"""
    query = st.text_input(
        "搜索课程原文",
        placeholder="输入一个或多个关键词，例如：多模态 注意力",
        key=f"original_search_{item['id']}",
    )
    matches = data.kb.search_course_segments(course, query)
    all_entries = data.kb.course_original_entries(course)
    if query:
        st.caption(f"找到 {len(matches)} 个片段；多个关键词需同时出现在同一片段中。")
    else:
        st.caption(f"共 {len(all_entries)} 个原文片段，可按页连续浏览。")
    if not matches:
        st.info("没有找到匹配片段，请缩短关键词或检查原文内容。")
        return

    page_size = 12
    page_count = (len(matches) + page_size - 1) // page_size
    page = st.selectbox(
        "浏览页",
        options=list(range(page_count)),
        format_func=lambda value: f"第 {value + 1} / {page_count} 页",
        key=f"original_page_{item['id']}_{query}",
    )
    start = page * page_size
    for entry in matches[start:start + page_size]:
        preview = entry["text"].replace("\n", " ")[:48]
        with st.expander(f"{entry['marker']} · {preview}{'…' if len(entry['text']) > 48 else ''}"):
            st.caption(f"片段标识：{entry['id']}")
            st.markdown(entry["text"])


def render_course_detail(item, section=None, career_direction=None):
    """渲染一门课程的详情看板（P2 减负：二级 Tab 拆解长页面）。

    - section 非 None：章节聚焦视图，直接展示该章节清洗后的干货正文；
    - 整门课程视图：
      A. 关键资产置顶：核心关键词 + 全文摘要；
      B. 二级 Tab：✨ 课程精华 | 🧠 知识图谱 | 🎯 考点与测评 | 📚 章节速览。
    """
    kb_name = item.get("kb_name")
    workspace_ui.render_section_heading(
        item["name"],
        "课程知识与转写文字工作区",
    )
    if section:
        st.caption(f"课程 ID：`{item['id']}`　·　当前章节：**{data.section_label(section)}**")
    else:
        st.caption(f"课程 ID：`{item['id']}`　·　整门课程")
    if not kb_name:
        st.warning("该课程暂未在「课程原文及导读」文件夹中找到对应 docx（`课程名_原文` / `课程名_导读`）。放入文件后刷新页面即可自动解析并绑定。")
        return
    course = data.KB["courses"][kb_name]
    sm = course.get("summary") or {}
    original = course.get("original")
    org = original or {}
    original_segments = org.get("segments") or []
    tag_parts = ["导读 ✓"] if sm else []
    if original_segments:
        tag_parts.append("原文 ✓")
    elif original is not None:
        tag_parts.append("原文为空")
    else:
        tag_parts.append("未提供原文")
    tag = "　".join(tag_parts)
    st.caption(f"已绑定知识库：`{kb_name}`　{tag}")
    workspace_ui.render_badges(tag_parts, key=f"course_assets_{item['id']}")

    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", data.llm.DEFAULT_MODEL)

    # ---------- 章节聚焦视图 ----------
    if section:
        body = data.kb.clean_text(section.get("body") or "")
        heading = "章节原文" if section.get("source") == "original" else "章节干货正文"
        st.markdown(f"**📄 {heading}（已去噪清洗）**")
        if body:
            st.markdown(body)
        else:
            st.info("该章节暂无可阅读文字。")
        chapter_segments = data.kb.section_original_segments(course, section)
        if chapter_segments and section.get("source") != "original":
            with st.expander(f"查看本章原文（{len(chapter_segments)} 个片段）"):
                for segment in chapter_segments:
                    marker = segment.get("ts") or "无时间戳"
                    st.markdown(f"**{marker}**　{data.kb.clean_text(segment.get('text') or '')}")
        st.divider()
        # 学习打卡：勾选后计入本次会话学习进度（不落盘）
        section_id = section.get("id") or section.get("ts") or section.get("title")
        render_chapter_completion_toggle(f"{item['id']}::{section_id}")
        st.caption("💡 提示：完整的关键词、摘要、课程精华与可折叠知识图谱请在「整门课程」视图查看。")
        return

    # ---------- 整门课程视图 ----------
    data_pack = data.get_clean_course_data(item, career_direction, api_key, model)
    career_name = data.CAREER_DIRECTIONS.get(career_direction, {}).get("name", career_direction)
    if data_pack["total_chunks"]:
        workspace_ui.render_badges(
            [f"章节整理 {data_pack['processed_chunks']}/{data_pack['total_chunks']} 块"],
            key=f"course_clean_progress_{item['id']}",
        )

    metric_cols = st.columns(3)
    with metric_cols[0]:
        workspace_ui.render_metric(
            "课程章节", len(data.course_sections(course)), "可定位的学习单元",
            key=f"course_sections_{item['id']}",
        )
    with metric_cols[1]:
        workspace_ui.render_metric(
            "转写片段", len(original_segments), "已解析原文段落",
            key=f"course_segments_{item['id']}",
        )
    with metric_cols[2]:
        workspace_ui.render_metric(
            "当前方向", career_name, "内容与考点偏好",
            key=f"course_career_{item['id']}",
        )

    # A. 关键资产置顶：核心关键词 + 全文摘要
    st.markdown("### 🔑 核心关键词")
    _render_keywords(data_pack["keywords"])

    st.markdown("### 📌 全文摘要")
    if data_pack["summary"]:
        st.info(data_pack["summary"])
    else:
        st.caption("（暂无摘要，配置 API Key 后可由 AI 自动萃取）")

    # B. 二级 Tab 拆解长页面（P2 减负）
    t_essence, t_mind, t_quiz, t_sec, t_original = st.tabs(
        ["✨ 课程精华", "🧠 知识图谱", "🎯 考点与测评", "📚 章节速览", "🔎 原文查找"]
    )

    with t_essence:
        st.markdown("### ✨ 课程精华")
        st.caption("已过滤寒暄、直播互动、课程事务、结束语和重复表达，并保留课程知识内容。")
        if data_pack["summary_points"]:
            st.markdown("**本课核心结论**")
            for index, point in enumerate(data_pack["summary_points"], 1):
                st.markdown(f"{index}. {point}")
        if data_pack["summary_points"] and data_pack["clean_text"]:
            st.divider()
        if data_pack["clean_text"]:
            st.markdown("**结构化课程干货**")
            with st.container(border=True):
                st.markdown(data_pack["clean_text"])
        else:
            st.info("该课程暂无可整理的知识内容。")

    with t_mind:
        st.markdown("### 🧭 岗位课程路径")
        st.caption("展开模块查看课程；重点标记会随左侧求职方向切换。")
        _render_career_course_tree(item, career_direction)
        st.divider()
        st.markdown("### 🧠 当前课程知识结构")
        st.caption("课程内部知识按主题、脉络、考点和求职关联分组，可分别展开或收起。")
        if data_pack["knowledge_groups"]:
            _render_course_knowledge_tree(item, data_pack["knowledge_groups"])
        else:
            st.caption("（当前课程暂无可整理的知识节点）")

    with t_quiz:
        # 实战/面试考点
        if data_pack["interview_points"]:
            st.markdown("**🎯 实战 / 面试考点**")
            for x in data_pack["interview_points"]:
                st.markdown(f"- {x}")
            st.divider()

        # 求职实战模拟测评：AI 优先，失败或无 Key 时按课程文字离线生成。
        st.markdown("### 📝 求职实战模拟测评")
        quiz_scope_key = "|".join(filter(None, [
            item["id"],
            str((section or {}).get("id") or ""),
            str((section or {}).get("ts") or ""),
            str((section or {}).get("title") or ""),
        ]))
        # 切换课程或章节后清掉上一范围的题目，避免串用。
        if st.session_state.get("current_quiz_course") != quiz_scope_key:
            st.session_state.pop("current_quiz", None)
            st.session_state["current_quiz_course"] = quiz_scope_key
            st.session_state["current_submitted"] = False

        if not api_key:
            st.caption("🔌 离线模式：将优先使用当前课程文字出题，不足时以通用内置题补齐。")
        else:
            st.caption("🤖 AI 优先：调用失败或返回空题时会自动降级为课程文字题。")
        if st.button("🎯 生成本课程测评", key=f"btn_gen_course_quiz_{quiz_scope_key}"):
            with st.spinner("正在根据当前课程范围生成测评题..."):
                quiz_list = data.generate_course_assessment(
                    item, section, data_pack["clean_text"], career_direction,
                    api_key, st.session_state.get("llm_model", llm.DEFAULT_MODEL),
                    num_q=3,
                )
            if quiz_list:
                st.session_state["current_quiz"] = quiz_list
                st.session_state["current_submitted"] = False
                for k in [k for k in st.session_state.keys() if k.startswith("cans_")]:
                    del st.session_state[k]
                kinds = {question.get("question_kind") for question in quiz_list}
                labels = []
                if "course_ai" in kinds:
                    labels.append("AI 课程原文题")
                if "course_text" in kinds:
                    labels.append("离线课程文字题")
                if "general_offline" in kinds:
                    labels.append("通用内置题")
                st.success(f"✅ 已生成本课程测评：{' + '.join(labels)}。")
            else:
                st.warning("当前课程和内置题库均未能生成可用题目。")
        render_course_quiz()

    with t_sec:
        sections = data.course_sections(course)
        if sections:
            section_type = "章节" if sm.get("sections") else "转写片段"
            unit = "章" if sm.get("sections") else "段"
            st.markdown(f"**📚 {section_type}速览**（{len(sections)} {unit}）")
            for s in sections:
                with st.expander(data.section_label(s)):
                    st.write(s.get("body", "") or "（无正文）")
        else:
            st.info("该课程暂无可阅读文字。请检查原文 docx 是否为空或格式是否正确。")

    with t_original:
        _render_original_browser(course, item)


def _render_course_directory(selected_job):
    """渲染三级课程目录，返回当前课程与章节。"""
    workspace_ui.render_section_heading("课程目录", "模块 → 课程 → 章节")
    module_labels = [m["name"] for m in data.MODULES]
    sel_module = st.radio("选择模块", options=module_labels, key="tab1_module")
    module_no = next(mm["no"] for mm in data.MODULES if mm["name"] == sel_module)
    module = next((mm for mm in data.MODULES if mm["no"] == module_no), data.MODULES[0])

    courses = [c for c in data.COURSE_INDEX if c["module_no"] == module_no]
    course_labels = [f"{c['id']}｜{c['name']}" for c in courses]
    sel_course = st.selectbox("选择课程", options=course_labels, key="tab1_course")
    course_id = sel_course.split("｜")[0]
    current_course = next(c for c in data.COURSE_INDEX if c["id"] == course_id)

    section_labels = ["整门课程"]
    sections = []
    if current_course.get("kb_name"):
        sections = data.course_sections(data.KB["courses"][current_course["kb_name"]])
        section_labels += [data.section_label(section) for section in sections]
    selected_label = st.selectbox("选择章节（可选）", section_labels, key="tab1_section")
    current_section = None
    if current_course.get("kb_name") and selected_label != "整门课程":
        current_section = sections[section_labels.index(selected_label) - 1]

    st.divider()
    st.markdown(f"**模块说明**　{module['desc']}")
    focus = data.CAREER_DIRECTIONS[selected_job]["focus"]
    if data.module_hits(module, focus):
        workspace_ui.render_badges(["重点模块"], key=f"module_hot_{module_no}_{selected_job}")
    st.caption(module["why"])
    bound_status = "课程文字已入库" if current_course["kb_name"] else "等待课程文字"
    workspace_ui.render_badges([f"{len(courses)} 门课", bound_status], key=f"module_meta_{module_no}")
    return current_course, current_section


def render_tab1(selected_job):
    """Tab1 入口：工作台式三级目录 + 课程详情。"""
    col_dir, col_detail = st.columns([0.82, 2.18], gap="medium")

    with col_dir:
        with st.container(border=True):
            current_course, current_section = _render_course_directory(selected_job)
            st.session_state.current_course = current_course
            st.session_state.current_section = current_section

    with col_detail:
        with st.container(border=True):
            render_course_detail(st.session_state.current_course, st.session_state.current_section, selected_job)
