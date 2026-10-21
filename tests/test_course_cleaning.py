"""验证术语纠错、长文边界、事实保护及有来源校订资产的应用。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import data, kb
from core.course_review import apply_reviews, source_fingerprint
from core.terminology import correct_terms


class CourseCleaningTests(unittest.TestCase):
    def test_rag_and_contextual_terms(self):
        self.assertEqual(correct_terms("RAG（Retrieve as you Go）"),
                         "RAG（Retrieval-Augmented Generation）")
        self.assertEqual(correct_terms("evening模型将切片变成向量。"),
                         "Embedding模型将切片变成向量。")
        for text in ("Good evening，今天讨论模型。", "Model Scope Platform 产品介绍", "TRAG模型"):
            self.assertEqual(correct_terms(text), text)
        self.assertEqual(correct_terms("向量由 Embedding 模型生成。"),
                         "向量由 Embedding 模型生成。")

    def test_deduplication_preserves_numbers_negation_and_comparisons(self):
        sentences = [
            "向量检索的相似度阈值可以设置为 0.5。",
            "向量检索的相似度阈值可以设置为 0.8。",
            "模型会在每次回答后更新自身的参数。",
            "模型不会在每次回答后更新自身的参数。",
            "查询过滤要求 x > 10。", "查询过滤要求 x < 10。",
            "商品价格为 1.5 元。", "商品价格为 15 元。",
        ]
        cleaned = kb.clean_course_text("\n".join(sentences + sentences[:1]))
        for sentence in sentences:
            self.assertIn(sentence, cleaned)
        self.assertEqual(cleaned.count(sentences[0]), 1)
        self.assertIn("额度", kb.clean_text("嗯，额度不足，需要限制并发。"))

    def test_guide_stops_before_recap_and_repeated_ppt(self):
        guide = kb.parse_summary([
            "测试_导读", "2026年09月19日", "全文摘要", "技术摘要。", "章节速览",
            "00:00 第一章", "知识一。", "01:00 第二章", "知识二。",
            "要点回顾", "错误的问答不能附着末章。", "提取PPT",
            "00:00 第一章", "重复知识。", "01:00 第二章", "重复知识。",
        ])
        self.assertEqual(len(guide["sections"]), 2)
        self.assertEqual(guide["sections"][-1]["body"], "知识二。")

    def test_guide_stops_before_question_answer_recap(self):
        """问答回顾不应附着到最后一章的学习正文。"""
        guide = kb.parse_summary([
            "测试_导读", "日期", "章节速览", "00:00 第一章", "课程知识。",
            "问答回顾", "发言人 问：课程安排是什么？",
            "发言人 答：后续还有直播。",
        ])
        self.assertEqual(len(guide["sections"]), 1)
        self.assertEqual(guide["sections"][0]["body"], "课程知识。")

    def test_repeated_section_without_recap_marker_is_not_imported_twice(self):
        guide = kb.parse_summary([
            "测试_导读", "日期", "章节速览", "00:00 第一章", "完整知识。",
            "01:00 第二章", "下一主题。", "00:00 第一章", "重复知识。",
        ])
        self.assertEqual(len(guide["sections"]), 2)
        self.assertNotIn("重复", str(guide))

    def test_review_requires_matching_source_and_preserves_raw(self):
        source = {
            "original": {"title": "测试课", "segments": [{"ts": "00:01", "text": "转写原貌"}]},
            "summary": {"title": "测试导读", "summary": "旧摘要", "sections": []},
        }
        review = {
            "course_key": "测试课", "source_sha256": source_fingerprint(source),
            "keywords": ["RAG"], "summary_points": ["已核对的摘要"],
            "interview_points": [], "sections": [{
                "ts": "00:00", "title": "知识点", "body": "学习版",
                "citation_ids": ["original-1"],
            }],
        }
        knowledge = {"courses": {"测试课": source}}
        before = copy.deepcopy(knowledge)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            path.write_text(json.dumps(review), encoding="utf-8")
            projected = apply_reviews(knowledge, Path(folder))["courses"]["测试课"]
            self.assertEqual(projected["summary"]["summary"], "已核对的摘要")
            self.assertEqual(projected["original"], source["original"])
            self.assertEqual(knowledge, before)
            changed = copy.deepcopy(knowledge)
            changed["courses"]["测试课"]["original"]["segments"][0]["text"] = "新版原文"
            self.assertNotIn("reviewed_assets", apply_reviews(changed, Path(folder))["courses"]["测试课"])
            review["sections"][0]["citation_ids"] = ["original-999"]
            path.write_text(json.dumps(review), encoding="utf-8")
            self.assertNotIn("reviewed_assets", apply_reviews(knowledge, Path(folder))["courses"]["测试课"])

    def test_ai_output_receives_same_correction(self):
        result = data._parse_extract(json.dumps({
            "summary_points": ["RAG（Retrieve as you Go）先检索。"],
            "cleaned_text": "RAG（Retrieve as you Go）先检索。",
            "keywords": ["RAG"], "interview_points": [],
        }))
        self.assertNotIn("Retrieve as you Go", str(result))
        self.assertIn("Retrieval-Augmented Generation", result["cleaned_text"])

    def test_real_rag_review_is_used_without_api_and_keeps_evidence(self):
        item = next(item for item in data.COURSE_INDEX if item["id"] == "1-2")
        course = data.KB["courses"][item["kb_name"]]
        self.assertIn("reviewed_assets", course)
        self.assertEqual(len(course["summary"]["sections"]), 26)
        with mock.patch.object(data.st, "session_state", {}), \
                mock.patch.object(data.llm, "call_llm") as api:
            result = data.get_clean_course_data(item, "agent_fullstack", "fake", "test")
        api.assert_not_called()
        self.assertIn("Retrieval-Augmented Generation", result["summary"])
        self.assertNotIn("Retrieve as you Go", result["summary"])
        self.assertNotIn("航天发动机", result["summary"])
        self.assertNotIn("拜拜", result["clean_text"])
        self.assertIn("retrieval augmented generation", course["original"]["segments"][32]["text"])
        self.assertTrue(all(kb.section_original_segments(course, section)
                            for section in course["summary"]["sections"]))

    def test_all_bound_courses_use_source_matched_reviews_without_api(self):
        """所有已入库课程的校订应实际生效，且不会触发模型重新覆盖。"""
        bound = [item for item in data.COURSE_INDEX if item.get("kb_name")]
        self.assertEqual(len(bound), 15)
        for item in bound:
            with self.subTest(course=item["id"]):
                course = data.KB["courses"][item["kb_name"]]
                review = course.get("reviewed_assets")
                self.assertIsNotNone(review, "来源变化或资产失效时必须重新复核")
                sections = review["sections"]
                starts = [kb.timestamp_seconds(section["ts"]) for section in sections]
                self.assertTrue(all(value is not None for value in starts))
                self.assertEqual(starts, sorted(set(starts)))
                evidence_ids = {entry["id"] for entry in kb.course_original_entries(course)}
                for section in sections:
                    self.assertTrue(set(section["citation_ids"]) <= evidence_ids)
                    self.assertTrue(kb.section_original_segments(course, section))
                with mock.patch.object(data.st, "session_state", {}), \
                        mock.patch.object(data.llm, "call_llm") as api:
                    pack = data.get_clean_course_data(item, "agent_fullstack", "fake", "test")
                api.assert_not_called()
                self.assertEqual(pack["summary_points"], review["summary_points"])
                self.assertEqual(pack["review_notes"], review["notes"])
                for section in sections:
                    self.assertIn(section["body"], pack["clean_text"])

    def test_qa_receives_review_notes_without_treating_them_as_raw_evidence(self):
        """外部校订与未决项随问答传入，但不能冒充原文引用。"""
        item = next(item for item in data.COURSE_INDEX if item["id"] == "1-2")
        course = data.KB["courses"][item["kb_name"]]
        with mock.patch.object(data.st, "session_state", {"chat_msgs": []}):
            _, prompt, evidence = data.build_qa_request(item, "RAG")
        self.assertIn("不是讲师原话", prompt)
        self.assertIn("待核实体不可推断为确定事实", prompt)
        for note in course["reviewed_assets"]["notes"]:
            self.assertIn(note, prompt)
        originals = {entry["id"]: entry["text"] for entry in kb.course_original_entries(course)}
        self.assertTrue(all(entry["text"] == originals[entry["id"]] for entry in evidence))


if __name__ == "__main__":
    unittest.main()
