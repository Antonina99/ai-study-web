# -*- coding: utf-8 -*-
"""用 mock 验证 AI 课程分类解析逻辑。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch
from core import data

# 模拟两门未匹配课程
fake_courses = {
    "未匹配课A": {"original": None, "summary": None},
    "未匹配课B": {"original": None, "summary": None},
}

mock_json = '[{"course": "未匹配课A", "module_no": 3, "reason": "讲Agent"}, {"course": "未匹配课B", "module_no": 99, "reason": "无法判断"}]'

with patch('core.data.llm.call_llm', return_value=mock_json):
    result = data._classify_courses(
        ["未匹配课A", "未匹配课B"],
        fake_courses,
        api_key="fake-key",
        model="fake-model",
    )

print("AI 分类解析结果：")
for k, v in result.items():
    print(f"  {k} -> 模块 {v}")

assert result.get("未匹配课A") == 3, "课A 应分配到模块 3"
assert result.get("未匹配课B") == data.EXT_MODULE_NO, "课B 应分配到新增模块"
print("\nMOCK_TEST_OK")
