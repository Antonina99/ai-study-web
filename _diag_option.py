# -*- coding: utf-8 -*-
"""验证选项清洗函数与课程索引构建。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from views import tab2_quiz

samples = [
    "A. 微调7B模型",
    "B、基于LangChain的Agent",
    "C  纯RAG方案",
    "D) 使用长上下文",
    "A)  选项内容",
    "E. 额外选项",
    "A. A. 双重前缀",
    "普通文本不带前缀",
]
print("选项清洗结果：")
for s in samples:
    print(f"  {s!r} -> {tab2_quiz._clean_option_text(s)!r}")

# 验证 build_course_index 对未匹配课程的兜底行为
from core import data
# 构造一个假课程字典，其中包含一个未匹配课程
fake_courses = {
    "开学典礼": {"original": {"segments": []}, "summary": {"summary": "开学典礼内容"}},
    "完全未匹配的新课": {"original": {"segments": []}, "summary": {"summary": "Agent开发"}},
}
idx = data.build_course_index(fake_courses, api_key=None, model=None)
extra_items = [it for it in idx if it["name"] == "完全未匹配的新课"]
print("\n无 API Key 时未匹配课程分配：")
print(f"  模块号: {extra_items[0]['module_no'] if extra_items else '未找到'}")
print(f"  新增模块编号: {data.EXT_MODULE_NO}")
