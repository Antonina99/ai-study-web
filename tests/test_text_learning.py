# -*- coding: utf-8 -*-
"""文字学习主链路回归测试；仅使用临时数据，不访问真实模型 API。"""

import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock
from xml.sax.saxutils import escape

from core import data, kb


def _write_docx(path, paragraphs):
    """写入足够供 core.kb.parse_docx 解析的最小 docx。"""
    body = "".join(
        f"<w:p><w:r><w:t>{escape(str(text))}</w:t></w:r></w:p>"
        for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


class TranscriptParsingTests(unittest.TestCase):
    def test_speaker_prefix_and_hour_timestamp(self):
        parsed = kb.parse_original([
            "测试课_原文",
            "2026年09月06日",
            "发言人 1 00:05 第一段内容",
            "说话人 A 01:02:03 第二段内容",
        ])
        self.assertEqual(
            parsed["segments"],
            [
                {"ts": "00:05", "text": "第一段内容"},
                {"ts": "01:02:03", "text": "第二段内容"},
            ],
        )
        self.assertEqual(kb.timestamp_seconds("01:02:03"), 3723)

    def test_no_timestamp_keeps_stable_paragraphs(self):
        parsed = kb.parse_original([
            "无时间戳课程_原文", "2026-09-06", "第一段", "第二段",
        ])
        self.assertEqual(
            parsed["segments"],
            [{"ts": "", "text": "第一段"}, {"ts": "", "text": "第二段"}],
        )
        entries = kb.course_original_entries({"original": parsed})
        self.assertEqual([entry["id"] for entry in entries], ["original-1", "original-2"])
        self.assertEqual([entry["marker"] for entry in entries], ["段落 1", "段落 2"])

    def test_empty_input_is_safe(self):
        self.assertEqual(kb.parse_original([]), {"title": "", "segments": []})
        self.assertEqual(kb.clean_text(""), "")
        self.assertEqual(kb.kb_course_context({}), "")

    def test_learning_cleanup_removes_chatter_and_keeps_technical_facts(self):
        source = (
            "嗯嗯，大家好。Transformer 使用 8 个注意力头，学习率为 1e-4。"
            "我们慢慢来，我们慢慢来。下课，拜拜，下周二见，拜拜。"
        )
        cleaned = kb.clean_course_text(source)
        self.assertIn("Transformer", cleaned)
        self.assertIn("8 个注意力头", cleaned)
        self.assertIn("1e-4", cleaned)
        self.assertEqual(cleaned.count("我们慢慢来"), 1)
        self.assertNotIn("大家好", cleaned)
        self.assertNotIn("拜拜", cleaned)
        self.assertNotIn("下周二见", cleaned)

    def test_summary_boilerplate_and_sales_content_are_removed(self):
        cleaned = kb.clean_course_text(
            "在这次讨论中，焦点放在了Agent检查点与恢复机制。"
            "课程章节介绍检查点如何恢复执行。"
            "此外还介绍价格优惠和直播课回放。"
        )
        self.assertIn("Agent检查点与恢复机制", cleaned)
        self.assertIn("课程章节", cleaned)
        self.assertNotIn("焦点放在了", cleaned)
        self.assertNotIn("价格优惠", cleaned)

    def test_course_cleanup_deduplicates_repeated_sentences(self):
        cleaned = kb.clean_course_text(
            "RAG 通过检索补充模型上下文。\nRAG 通过检索补充模型上下文。\n"
            "向量数据库负责保存和检索嵌入。"
        )
        self.assertEqual(cleaned.count("RAG 通过检索补充模型上下文"), 1)
        self.assertIn("向量数据库", cleaned)


class CourseAssetTests(unittest.TestCase):
    def test_offline_essence_cleans_summary_sections_and_deduplicates(self):
        course = {
            "summary": {
                "summary": "RAG 通过检索补充上下文。拜拜，下周二见。",
                "sections": [
                    {"body": "RAG 通过检索补充上下文。大家唠唠嗑，聊会儿天儿。"},
                    {"body": "向量数据库保存 Embedding。"},
                ],
            },
            "original": {"segments": []},
        }
        essence = data._rule_cleaned_doc(course)
        self.assertEqual(essence.count("RAG 通过检索补充上下文"), 1)
        self.assertIn("向量数据库", essence)
        self.assertNotIn("拜拜", essence)
        self.assertNotIn("唠唠嗑", essence)

    def test_course_knowledge_is_grouped_for_collapsible_tree(self):
        course = {
            "summary": {
                "keywords": ["RAG", "Embedding", "向量数据库", "召回率"],
                "sections": [
                    {"title": f"课程章节 {index}"} for index in range(1, 9)
                ],
            },
            "original": {"title": "企业 RAG 实战_原文", "segments": []},
        }
        career = next(iter(data.CAREER_DIRECTIONS))
        groups = data.course_knowledge_groups(
            "RAG 与 Agent 项目实践。", career, course,
            keywords=course["summary"]["keywords"], summary_points=["检索质量决定回答质量"],
        )
        by_name = {group["name"]: group["items"] for group in groups}
        self.assertIn("核心主题", by_name)
        self.assertIn("课程脉络", by_name)
        self.assertIn("求职关联", by_name)
        self.assertIn("课程章节 1", by_name["课程脉络"])
        self.assertLessEqual(len(by_name["课程脉络"]), 12)

    def test_every_career_marks_explicit_priority_courses(self):
        examples = {
            "agent_fullstack": "🔥 Function Calling与MCP (上下文交互协议)",
            "llm_algorithm": "🔥 高质量微调数据工程与评估",
            "infra_devops": "🔥 SGLang 深度优化：Radix 缓存与复杂任务的极致吞吐",
            "ai_pm_architect": "AI框架设计与选型",
            "prompt_coding": "大厂优秀工程师使用AI Coding 的最新方法与经验",
        }
        for career, course_name in examples.items():
            with self.subTest(career=career):
                self.assertTrue(data.course_priority_reasons(course_name, career))
        self.assertFalse(data.course_priority_reasons("LLM微调原理", "agent_fullstack"))

    def test_path_profiles_are_exact_and_role_specific(self):
        courses = {name for names in data.COURSE_MODULES.values() for name in names}
        for path in data.CAREER_COURSE_PATHS.values():
            self.assertTrue(set(path).issubset(courses))
            self.assertTrue(all(p["reason"] and p["scope"] for p in path.values()))
        profile = data.course_learning_profile
        self.assertEqual(profile("Embeddings和向量数据库", "agent_fullstack")["level"], "岗位核心")
        self.assertFalse(profile("新增项目实战", "ai_pm_architect"))
        self.assertFalse(profile("🔥 项目实战：AI质检", "infra_devops"))
        name = "大型软件项目的AI开发与AI重构"
        self.assertEqual(profile(name, "prompt_coding", "coding")["level"], "岗位核心")
        self.assertEqual(profile(name, "prompt_coding", "office")["level"], "专项选学")
        name = "企业级AI部署：从硬件选型到框架选择"
        self.assertFalse(profile(name, "ai_pm_architect", "product"))
        self.assertEqual(profile(name, "ai_pm_architect", "architect")["level"], "岗位核心")

    def test_chunk_merge_cleans_and_deduplicates_ai_results(self):
        processed = [
            ({"title": "第一章"}, {
                "cleaned_text": "向量检索负责召回候选文档。拜拜。",
                "summary_points": ["向量检索负责召回"],
                "interview_points": ["解释召回率"],
                "keywords": ["RAG"],
            }),
            ({"title": "第二章"}, {
                "cleaned_text": "向量检索负责召回候选文档。重排模型优化候选顺序。",
                "summary_points": ["重排优化顺序"],
                "interview_points": ["解释重排"],
                "keywords": ["Rerank"],
            }),
        ]
        merged = data._merge_chunk_extracts(processed, 2)
        self.assertTrue(merged["ok"])
        self.assertEqual(merged["cleaned_text"].count("向量检索负责召回候选文档"), 1)
        self.assertNotIn("拜拜", merged["cleaned_text"])


class KnowledgeCacheTests(unittest.TestCase):
    def test_original_only_course_and_cache_rebuild(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "cache.json")
            docx_path = os.path.join(temp_dir, "1、测试课程_原文.docx")
            _write_docx(docx_path, [
                "1、测试课程_原文", "2026年09月06日", "00:01", "初始文字",
            ])
            with mock.patch.object(kb, "KB_DIR", temp_dir), mock.patch.object(
                kb, "CACHE_FILE", cache_path
            ):
                first, first_changed = kb.build_kb()
                self.assertEqual(first_changed, ["1、测试课程"])
                self.assertIsNone(first["courses"]["1、测试课程"]["summary"])
                self.assertEqual(
                    first["courses"]["1、测试课程"]["original"]["segments"][0]["text"],
                    "初始文字",
                )

                second, second_changed = kb.build_kb()
                self.assertEqual(second_changed, [])
                self.assertEqual(second["courses"], first["courses"])

                _write_docx(docx_path, [
                    "1、测试课程_原文", "2026年09月06日", "00:01", "更新后的更长文字",
                ])
                stat = os.stat(docx_path)
                os.utime(docx_path, (stat.st_atime, stat.st_mtime + 2))
                rebuilt, rebuilt_changed = kb.build_kb()
                self.assertEqual(rebuilt_changed, ["1、测试课程"])
                self.assertEqual(
                    rebuilt["courses"]["1、测试课程"]["original"]["segments"][0]["text"],
                    "更新后的更长文字",
                )
                with open(cache_path, encoding="utf-8") as cache_file:
                    saved = json.load(cache_file)
                self.assertEqual(saved["cache_version"], kb.CACHE_VERSION)


class ChapterRangeTests(unittest.TestCase):
    def test_chapter_boundaries_include_middle_and_last_ranges(self):
        course = {
            "summary": {"sections": [
                {"ts": "00:00", "title": "开头", "body": "开头导读"},
                {"ts": "01:00:00", "title": "一小时后", "body": "后段导读"},
            ]},
            "original": {"segments": [
                {"ts": "00:10", "text": "开头原文"},
                {"ts": "59:59", "text": "中段原文"},
                {"ts": "01:00:00", "text": "小时边界"},
                {"ts": "01:30:00", "text": "末段原文"},
            ]},
        }
        first, last = course["summary"]["sections"]
        self.assertEqual(
            [segment["text"] for segment in kb.section_original_segments(course, first)],
            ["开头原文", "中段原文"],
        )
        self.assertEqual(
            [segment["text"] for segment in kb.section_original_segments(course, last)],
            ["小时边界", "末段原文"],
        )
        self.assertNotIn("末段原文", kb.kb_course_context(course, section=first))
        self.assertIn("末段原文", kb.kb_course_context(course, section=last))

    def test_qa_request_returns_prompt_and_verified_evidence(self):
        course = {
            "summary": {"sections": []},
            "original": {"segments": [
                {"ts": "00:20", "text": "多模态模型可以联合处理图片和文字。"},
            ]},
        }
        item = {"name": "多模态测试课", "kb_name": "多模态测试课"}
        with mock.patch.object(data, "KB", {"courses": {"多模态测试课": course}}), \
                mock.patch.object(data.st, "session_state", {
                    "llm_model": "offline-test", "chat_msgs": [], "cleaned_cache": {},
                }):
            system, user, evidence = data.build_qa_request(item, "如何处理图片和文字？")
        self.assertIn("课程原文结论", system)
        self.assertIn("original-1", user)
        self.assertEqual([entry["id"] for entry in evidence], ["original-1"])


class QuizFallbackTests(unittest.TestCase):
    def setUp(self):
        self.course = {
            "summary": {
                "keywords": ["Agent", "RAG", "MCP", "部署"],
                "sections": [
                    {"ts": f"0{index}:00", "title": f"章节{index}",
                     "body": f"这是章节{index}的完整技术说明，包含足够长度用于离线题目生成。"}
                    for index in range(4)
                ],
            },
            "original": {"segments": [
                {"ts": f"0{index}:10", "text": f"章节{index}原文包含 Agent 技术实践和项目说明。"}
                for index in range(4)
            ]},
        }
        self.item = {"name": "测试课程", "kb_name": "测试课程"}
        self.career = next(iter(data.CAREER_DIRECTIONS))

    def test_answer_mapping_survives_shuffle(self):
        question = {"q": "测试", "options": ["甲", "乙", "丙", "丁"], "answer": 2}
        for _ in range(10):
            shuffled = data.shuffle_question(question)
            self.assertEqual(shuffled["options"][shuffled["answer"]], "丙")
            self.assertEqual(data.ans_index(shuffled, "丙"), shuffled["answer"])
            self.assertIsNone(data.ans_index(shuffled, None))

    def test_ai_empty_result_falls_back_to_course_text(self):
        synthetic_kb = {"courses": {"测试课程": self.course}}
        with mock.patch.object(data, "KB", synthetic_kb), mock.patch.object(
            data, "generate_practical_quiz_api", return_value=[]
        ) as ai_call:
            questions = data.generate_course_assessment(
                self.item, None, "课程文字", self.career, "fake-key", "fake-model", 3,
            )
        ai_call.assert_called_once()
        self.assertEqual(len(questions), 3)
        self.assertTrue(all(q["question_kind"] == "course_text" for q in questions))
        self.assertTrue(all(q["source"] in {"课程原文题", "课程导读题"} for q in questions))

    def test_empty_course_falls_back_to_general_questions(self):
        synthetic_kb = {"courses": {"空课程": {"summary": {}, "original": {"segments": []}}}}
        empty_item = {"name": "空课程", "kb_name": "空课程"}
        with mock.patch.object(data, "KB", synthetic_kb):
            questions = data.generate_course_assessment(
                empty_item, None, "", self.career, "", "fake-model", 3,
            )
        self.assertEqual(len(questions), 3)
        self.assertTrue(all(q["question_kind"] == "general_offline" for q in questions))
        self.assertTrue(all(q["source"] == "通用内置题" for q in questions))


if __name__ == "__main__":
    unittest.main()
