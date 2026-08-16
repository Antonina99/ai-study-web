# -*- coding: utf-8 -*-
"""逐行跟踪 build_course_index -> _classify_courses 的执行路径。"""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(__file__))
from unittest.mock import patch
from core import data

fake_courses = {
    "2. 从提示工程到RAG：构建大模型的知识与交互基础": {"original": None, "summary": None},
    "3. Agent：从可控性到自主反思": {"original": None, "summary": None},
}

# 手动复刻 build_course_index 中 extra 计算逻辑
norm_map = {}
for k in fake_courses:
    nk = data.kb.normalize(k)
    if nk:
        norm_map.setdefault(nk, k)
print("norm_map:", norm_map)

bound_keys = set()
for mod in data.MODULES:
    for c in mod["courses"]:
        key = data.kb.normalize(c)
        hit = norm_map.get(key)
        if hit is None:
            for nk, ok in norm_map.items():
                if nk in key or key in nk:
                    hit = ok
                    break
        if hit:
            bound_keys.add(hit)
print("bound_keys:", bound_keys)
extra = [k for k in fake_courses if k not in bound_keys]
print("extra:", extra)

# 直接调用 _classify_courses 并捕获异常
mock_json = ('[{"course": "3. Agent：从可控性到自主反思", "module_no": 3, '
             '"reason": "Agent 课程"}]')
try:
    with patch('core.data.llm.call_llm', return_value=mock_json) as m:
        result = data._classify_courses(extra, fake_courses, api_key="k", model="m")
        print("call_count:", m.call_count, "| result:", result)
except Exception:
    traceback.print_exc()
