# -*- coding: utf-8 -*-
"""端到端验证：模拟模块99已存在 + 两门课应被正确分配。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from unittest.mock import patch
from core import data

# 1) 模拟真实场景：MODULES 已包含「新增课程」模块（99），含之前被误分进去的课
extra_mod = {"no": data.EXT_MODULE_NO, "name": "新增课程（自动发现）",
             "courses": ["2. 从提示工程到RAG：构建大模型的知识与交互基础",
                          "3. Agent：从可控性到自主反思"]}
if not any(m.get("no") == data.EXT_MODULE_NO for m in data.MODULES):
    data.MODULES = list(data.MODULES) + [extra_mod]
print("MODULES 是否含模块99:", any(m.get("no") == data.EXT_MODULE_NO for m in data.MODULES))

# 2) 模拟知识库解析的课程
fake_courses = {
    "2. 从提示工程到RAG：构建大模型的知识与交互基础": {"original": None, "summary": None},
    "3. Agent：从可控性到自主反思": {"original": None, "summary": None},
}

# 3) 带 API Key 构建索引，mock AI 把 Agent 课程分到模块3
mock_json = ('[{"course": "3. Agent：从可控性到自主反思", "module_no": 3, '
             '"reason": "Agent 课程"}]')
with patch('core.data.llm.call_llm', return_value=mock_json) as m:
    idx = data.build_course_index(fake_courses, api_key="k", model="m")

print("\n索引项：")
for it in idx:
    print(f"  module_no={it['module_no']:>2} | name={it['name']} | kb_name={it.get('kb_name')}")

print("\ncall_llm 调用次数:", m.call_count)

# 断言
def find(module_no, name):
    return [it for it in idx if it["module_no"] == module_no and it["name"] == name]

assert find(1, "从提示工程到RAG：构建大模型的知识与交互基础")[0]["kb_name"] == "2. 从提示工程到RAG：构建大模型的知识与交互基础", "课2 应绑定到模块1"
assert find(3, "3. Agent：从可控性到自主反思"), "Agent 课应被 AI 分到模块3"
assert not [it for it in idx if it["module_no"] == data.EXT_MODULE_NO], "不应再残留新增模块项"
print("\nALL_ASSERT_OK")
