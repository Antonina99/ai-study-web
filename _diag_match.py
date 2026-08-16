# -*- coding: utf-8 -*-
"""验证课程名双向归一化匹配 + refresh_kb 的 AI 分类触发逻辑。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from unittest.mock import patch
from core import data, kb

# 模拟知识库解析结果：带序号的文件名
fake_courses = {
    "2. 从提示工程到RAG：构建大模型的知识与交互基础": {"original": None, "summary": None},
    "3. Agent：从可控性到自主反思": {"original": None, "summary": None},
}
# 构造一个包含这两个课程名的大纲模块，模拟 MODULES
data.MODULES = list(data.MODULES)
# 打印模块1课程，确认是否存在目标课程
print("模块1课程:", [c for c in data.MODULES if c.get("no") == 1][0]["courses"])
print("模块3课程:", [c for c in data.MODULES if c.get("no") == 3][0]["courses"])

# 1) 无 API Key：验证名称匹配
idx = data.build_course_index(fake_courses, api_key=None, model=None)
for it in idx:
    if it["name"] in ("2. 从提示工程到RAG：构建大模型的知识与交互基础",
                      "3. Agent：从可控性到自主反思"):
        print(f"\n[匹配结果] {it['name']} -> module_no={it['module_no']}")
    elif it.get("kb_name") == "2. 从提示工程到RAG：构建大模型的知识与交互基础":
        print(f"[大纲绑定] {it['name']} -> kb_name={it['kb_name']}")

# 2) 带 API Key：mock LLM 分类 "3. Agent" 应归入模块3
mock_json = ('[{"course": "3. Agent：从可控性到自主反思", "module_no": 3, '
             '"reason": "Agent 课程"}]')
with patch('core.data.llm.call_llm', return_value=mock_json):
    idx2 = data.build_course_index(fake_courses, api_key="k", model="m")
for it in idx2:
    if it["name"] == "3. Agent：从可控性到自主反思":
        print(f"\n[AI分类结果] {it['name']} -> module_no={it['module_no']}")

# 3) refresh_kb：文件未变化但有待分类课程+Key 时应触发；同一批不重复
import streamlit as st
# 注入 session
for key in ("_kb_classify_sig", "api_key", "llm_model"):
    st.session_state.pop(key, None)
st.session_state["api_key"] = "test-key"
st.session_state["llm_model"] = "qwen-max"

data.COURSE_INDEX = data.build_course_index(fake_courses, api_key="", model="m")
with patch('core.data.llm.call_llm', return_value=mock_json), \
     patch('core.data.kb.has_file_changes', return_value=False):
    r1 = data.refresh_kb()
    sig1 = st.session_state.get("_kb_classify_sig")
    print(f"\n[refresh_kb] 未变化但有待分类+Key: 触发分类 r1={r1}")
    # 再次调用：同一批课程不应重复触发
    r2 = data.refresh_kb()
    print(f"[refresh_kb] 同一批再次调用: r2={r2}, sig={'已记录' if sig1 else '无'}")
