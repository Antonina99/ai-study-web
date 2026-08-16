# -*- coding: utf-8 -*-
"""调试 _classify_courses 返回 99 的原因。"""
import sys, os, traceback
sys.path.insert(0, os.path.dirname(__file__))
from unittest.mock import patch
from core import data, llm, kb

fake_courses = {
    "3. Agent：从可控性到自主反思": {"original": None, "summary": None},
}
mock_json = ('[{"course": "3. Agent：从可控性到自主反思", "module_no": 3, '
             '"reason": "Agent 课程"}]')

print("=== 1) 检查 _json_scan 是否可解析 mock_json ===")
try:
    r = llm._json_scan(mock_json)
    print("_json_scan ->", r)
except Exception:
    traceback.print_exc()

print("\n=== 2) 手动执行 _classify_courses 关键步骤（不 mock，直接观察异常） ===")
try:
    # 构造 modules_desc
    modules_desc = "\n".join(
        f"{m['no']}. {m['name']}（主题：{', '.join(m.get('topics', []))}；"
        f"已有课程：{', '.join(m.get('courses', []))}）"
        for m in data.MODULES if m.get("no") != data.EXT_MODULE_NO
    )
    course_descs = []
    for name in ["3. Agent：从可控性到自主反思"]:
        course = fake_courses.get(name) or {}
        text = kb.kb_course_context(course, max_chars=1000)
        print(f"kb_course_context 返回: {text[:80]!r}")
        course_descs.append(f"课程名：{name}\n课程摘要：{text}\n---")
    system = (llm.CLASSIFY_MODULE_SYSTEM_PROMPT
              .replace("{modules}", modules_desc)
              .replace("{courses}", "\n".join(course_descs)))
    print(f"system prompt 前 200 字: {system[:200]!r}")
except Exception:
    traceback.print_exc()

print("\n=== 3) 带 patch 调用 _classify_courses ===")
try:
    with patch('core.data.llm.call_llm', return_value=mock_json):
        result = data._classify_courses(
            ["3. Agent：从可控性到自主反思"],
            fake_courses,
            api_key="k", model="m",
        )
    print("_classify_courses ->", result)
except Exception:
    traceback.print_exc()
