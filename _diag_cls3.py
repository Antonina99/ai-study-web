# -*- coding: utf-8 -*-
"""在 build_course_index 完整链路中验证 AI 分类。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from unittest.mock import patch
from core import data

fake_courses = {
    "2. 从提示工程到RAG：构建大模型的知识与交互基础": {"original": None, "summary": None},
    "3. Agent：从可控性到自主反思": {"original": None, "summary": None},
}
mock_json = ('[{"course": "3. Agent：从可控性到自主反思", "module_no": 3, '
             '"reason": "Agent 课程"}]')

with patch('core.data.llm.call_llm', return_value=mock_json) as m:
    idx2 = data.build_course_index(fake_courses, api_key="k", model="m")
    print("call_llm 被调用次数:", m.call_count)

print("\n完整索引（带 key）：")
for it in idx2:
    print(f"  module_no={it['module_no']} | name={it['name']} | kb_name={it.get('kb_name')}")
