# -*- coding: utf-8 -*-
"""
大模型实战课程 · 智能学习与知识看板（入口文件）

架构分层：
- core/llm.py      —— LLM API 调用（超时/重试/流式）、Prompt 常量、JSON 解析
- core/kb.py       —— docx 解析（时间戳分段、口语去噪、归一化）与缓存
- core/data.py     —— 求职方向/课程大纲/离线题库、知识库加载、课程资产组装、出题逻辑
- core/tracker.py  —— SQLite 轻量持久化（错题本 + 学习统计）
- core/share.py    —— 对外分享链接（短码生成 / 有效期 / 撤销，SQLite 落盘）
- views/tab1_course.py / tab2_quiz.py / tab3_assistant.py —— 三个 Tab 的 UI 渲染层
- views/share_panel.py —— 分享链接 UI（生成 / 复制 / 管理 / 有效期）
- app.py           —— 应用入口：初始化 / 侧边栏 / Tab 调度 / 分享链接访问

说明：
- 求职方向 5 选 1，贯穿思维导图定制、实战出题与错题解析（focus 强约束注入）。
- 所有 AI 能力均有离线规则兜底，未配置 API Key 也可完整体验。
- 错题本与学习统计落盘 learning_tracker.db，刷新页面不丢失。
- 对外分享：生成带唯一短码的链接（?share=<短码>），他人无需登录即可访问。
"""

import streamlit as st

from core import data, llm, share, tracker
from views import share_panel, tab1_course, tab2_quiz, tab3_assistant

st.set_page_config(page_title="AI 大模型实战求职助手", layout="wide")


# ================================================================ 初始化
def init_session_state():
    """初始化全部会话状态（错题本/统计从 SQLite 恢复；分享链接表初始化并清理过期）。"""
    tracker.init_db()
    share.init_db()
    share.purge_expired()
    # 运行期检测知识库：放入新 docx 后刷新页面即可自动发现新课程（内部有文件签名缓存，开销极小）
    data.refresh_kb()
    defaults = {
        "api_key": "",
        "llm_model": llm.DEFAULT_MODEL,
        "current_course": data.COURSE_INDEX[0],
        "current_section": None,
        "quiz": None,
        "submitted": False,
        "quiz_direction": None,
        "chat_msgs": [],
        "chat_course_id": None,
        "cleaned_cache": {},
        "mindmap_cache": {},
        # 课程内测评
        "current_quiz": None,
        "current_submitted": False,
        "current_quiz_course": None,
        # 对外分享
        "share_base_url": share.get_default_base_url(),
        "_is_shared_view": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if "wrongs" not in st.session_state:
        st.session_state.wrongs = tracker.load_wrongs()
    if "stats" not in st.session_state:
        st.session_state.stats = tracker.load_stats()


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
        st.markdown("**重点方向**：" + "　".join(f"`{x}`" for x in job["focus"]))

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

        # 对外分享：访客通过分享链接访问时隐藏（避免被访客管理/撤销主人的链接）
        if not st.session_state.get("_is_shared_view"):
            share_panel.render_sidebar_share_panel()

        st.divider()
        with st.expander("📖 使用说明"):
            st.markdown(
                "**Tab 1** 课程大纲与导读：模块 → 课程 → 章节级联；关键词/摘要/定制思维导图/干货/考点/章节速览；课程内求职实战测评。\n\n"
                "**Tab 2** 智能自测与刷题：AI 实战出题（强依赖 API）+ 内置题库离线兜底；提交后查看结构化解析与 AI 错题深度解析。\n\n"
                "**Tab 3** 课程 AI 助教：结合当前课程/章节上下文提问，流式回答。\n\n"
                "📈 学习进度与错题本会自动落盘本地 `learning_tracker.db`。"
            )

        st.divider()
        st.subheader("📈 学习进度")
        st.markdown("**知识库覆盖**："
                    f"{sum(1 for c in data.COURSE_INDEX if c['kb_name'])} / {len(data.COURSE_INDEX)} 门课")
        if data.newly_added:
            st.info(f"🆕 检测到新入库课程：**{data.newly_added}**")
        answered = st.session_state.stats["answered"]
        correct = st.session_state.stats["correct"]
        acc = correct / answered if answered else 0
        st.progress(acc, text=f"答题正确率：{acc:.0%}（{correct}/{answered}）")
        st.caption(f"错题本：{len(st.session_state.wrongs)} 道")
        if st.session_state.wrongs:
            if st.button("📌 重刷错题"):
                st.session_state.quiz = [data.shuffle_question(dict(w)) for w in st.session_state.wrongs]
                st.session_state.submitted = False
                st.session_state.quiz_direction = selected_job
                for k in [k for k in st.session_state.keys() if k.startswith("ans_")]:
                    del st.session_state[k]
                st.toast("已加载错题，请到「Tab 2」作答。")

    return selected_job


# ================================================================ 分享链接访问
def render_shared_view(token):
    """分享链接访问入口：校验短码后直接渲染被分享内容（无需登录）。

    - 课程级：只渲染该课程的详情看板（复用原有组件，样式/交互与本站一致）；
    - 平台级：渲染完整应用（隐藏分享管理面板，访客可自行配置自己的 API Key）。
    """
    rec = share.get_share(token)
    if not rec or not share.is_valid(rec):
        st.markdown("## 🔒 分享链接不可用")
        st.error("该分享链接不存在或已过期。")
        st.caption("请联系分享者重新生成链接。")
        return
    st.markdown("### 🎓 AI 大模型应用开发 · 实战求职学习平台")
    st.caption(
        f"🕐 分享创建于 {rec['created_at']}　·　"
        + ("有效期：永久" if not rec.get("expires_at") else f"有效期至：{rec['expires_at']}")
        + "　·　访客模式（无需登录）"
    )
    if rec.get("target_type") == "course":
        item = next((c for c in data.COURSE_INDEX if c["id"] == rec.get("target_id")), None)
        if not item:
            st.warning("被分享的课程已不存在（可能已被移除或重命名）。")
            return
        career = rec.get("career_direction") or next(iter(data.CAREER_DIRECTIONS))
        tab1_course.render_course_detail(item, section=None, career_direction=career)
        st.divider()
        st.caption("本页面由分享者生成的对外链接提供 · 访客模式（无需登录）")
    else:
        # 平台级：完整渲染（隐藏侧边栏分享管理面板）
        st.session_state["_is_shared_view"] = True
        main(is_shared=True)


# ================================================================ 主区
def main(is_shared=False):
    init_session_state()
    # 分享链接模式：?share=<短码>
    if not is_shared:
        token = st.query_params.get("share")
        if isinstance(token, list):
            token = token[0] if token else None
        if token:
            render_shared_view(token)
            st.stop()
    selected_job = render_sidebar()

    st.title("🎓 AI 大模型应用开发 · 实战求职学习平台")

    tab1, tab2, tab3 = st.tabs(["📖 课程大纲与导读", "📝 智能自测与刷题", "💬 课程 AI 助教"])
    with tab1:
        tab1_course.render_tab1(selected_job)
    with tab2:
        tab2_quiz.render_tab2(selected_job)
    with tab3:
        tab3_assistant.render_tab3()

    st.divider()
    st.caption("数据源：`课程原文及导读/` 目录下的 docx 课程原文与导读；AI 输出请以实际为准。")


if __name__ == "__main__":
    main()
