# -*- coding: utf-8 -*-
"""课程索引、AI 分类降级和选项显示的回归测试。"""

import unittest
from unittest import mock

from core import data
from views import tab2_quiz


class CourseIndexTests(unittest.TestCase):
    def test_numbered_kb_name_matches_outline_without_api(self):
        kb_name = "2. 从提示工程到RAG：构建大模型的知识与交互基础"
        index = data.build_course_index({kb_name: {}})
        matched = [item for item in index if item.get("kb_name") == kb_name]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["module_no"], 1)

    def test_unknown_course_uses_extra_module_without_api(self):
        index = data.build_course_index({"完全未匹配的新课程XYZ": {}})
        extra = [item for item in index if item.get("kb_name") == "完全未匹配的新课程XYZ"]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0]["module_no"], data.EXT_MODULE_NO)

    def test_mocked_ai_classifies_unknown_course(self):
        name = "自主智能体排障专题XYZ"
        response = (
            '[{"course":"自主智能体排障专题XYZ","module_no":3,'
            '"reason":"Agent 专题"}]'
        )
        with mock.patch.object(data.llm, "call_llm", return_value=response) as call:
            index = data.build_course_index({name: {}}, api_key="fake-key", model="fake-model")
        matched = [item for item in index if item.get("kb_name") == name]
        self.assertEqual(matched[0]["module_no"], 3)
        call.assert_called_once()

    def test_ai_parse_failure_falls_back_to_extra_module(self):
        name = "无法分类课程XYZ"
        with mock.patch.object(data.llm, "call_llm", return_value="不是 JSON"):
            index = data.build_course_index({name: {}}, api_key="fake-key", model="fake-model")
        matched = [item for item in index if item.get("kb_name") == name]
        self.assertEqual(matched[0]["module_no"], data.EXT_MODULE_NO)


class OptionTextTests(unittest.TestCase):
    def test_option_prefix_cleanup(self):
        samples = {
            "A. 微调7B模型": "微调7B模型",
            "B、基于LangChain的Agent": "基于LangChain的Agent",
            "C  纯RAG方案": "纯RAG方案",
            "D) 使用长上下文": "使用长上下文",
            "E. 额外选项": "E. 额外选项",
            "普通文本不带前缀": "普通文本不带前缀",
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(tab2_quiz._clean_option_text(source), expected)


if __name__ == "__main__":
    unittest.main()
