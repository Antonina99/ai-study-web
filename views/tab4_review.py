# -*- coding: utf-8 -*-
"""
views/tab4_review.py —— Tab4 错题复习

- 错题统一记录到 st.session_state.error_notebook（Session State，不落盘 SQLite）；
- 提供错题列表复习（展开查看题目 / 你的答案 / 正确答案 / AI 解析）与 JSON 一键导出；
- 每条错题同时保留 question_data（完整题目快照），供侧边栏「重刷错题」原题重做。
"""

import json

import streamlit as st


def _option_text(idx, opts):
    """把答案下标转成「字母. 选项文本」；未作答 / 异常下标给出兜底文案。"""
    if idx is None:
        return "（未作答）"
    if isinstance(idx, int) and 0 <= idx < len(opts):
        return f"{chr(65 + idx)}. {opts[idx]}"
    return str(idx)


def record_wrong_question(q, user_ans):
    """记录错题到 st.session_state.error_notebook（按题目去重，避免重复记录同一题）。

    参数：
    - q        题目 dict（含 q / options / answer / explain / source / analysis 等字段）；
    - user_ans 用户所选答案下标（data.ans_index 的结果，可能为 None）。
    """
    opts = q.get("options") or []
    q_id = f"{q.get('source', 'quiz')}::{q.get('q', '')[:60]}"
    wrong_item = {
        "id": q_id,
        "chapter": q.get("source", ""),
        "question": q.get("q", ""),
        "user_answer": _option_text(user_ans, opts),
        "correct_answer": _option_text(q.get("answer"), opts),
        "analysis": (q.get("analysis") or {}).get("correct_reason") or q.get("explain", ""),
        # 完整题目快照：供侧边栏「重刷错题」原题重做（导出 JSON 时一并保留）
        "question_data": dict(q),
    }
    if not any(item["id"] == q_id for item in st.session_state.error_notebook):
        st.session_state.error_notebook.append(wrong_item)


def render_error_notebook_tab():
    """错题复习 Tab：展示错题列表，并提供 JSON 一键导出。"""
    if not st.session_state.error_notebook:
        st.info("🎉 当前暂无错题记录，继续保持！")
        return

    st.subheader("📚 错题复习与导出")
    st.caption("错题保存在本次会话中（不落盘）；点击下方按钮可导出 JSON 备份。")
    for idx, item in enumerate(st.session_state.error_notebook):
        with st.expander(f"❌ 错题 {idx + 1}：[{item['chapter']}] {item['question'][:20]}..."):
            st.write(f"**题目**：{item['question']}")
            st.write(f"**你的答案**：:red[{item['user_answer']}]")
            st.write(f"**正确答案**：:green[{item['correct_answer']}]")
            if item.get("analysis"):
                st.info(f"💡 **AI 解析**：{item['analysis']}")

    json_data = json.dumps(
        st.session_state.error_notebook, ensure_ascii=False, indent=2, default=str
    )
    st.download_button(
        label="📥 导出错题本 (JSON)",
        data=json_data,
        file_name="my_error_notebook.json",
        mime="application/json",
    )
