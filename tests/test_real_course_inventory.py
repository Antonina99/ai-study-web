# -*- coding: utf-8 -*-
"""现有真实课程资料的端到端验收；不调用模型 API。"""

import unittest
from unittest import mock

from core import data, kb


class RealCourseInventoryTests(unittest.TestCase):
    def test_every_bound_course_supports_read_qa_and_offline_quiz(self):
        bound = [item for item in data.COURSE_INDEX if item.get("kb_name")]
        self.assertGreaterEqual(len(bound), 3, "现有三门真实课程不应丢失绑定")
        career = next(iter(data.CAREER_DIRECTIONS))

        for item in bound:
            with self.subTest(course=item["name"]):
                course = data.KB["courses"].get(item["kb_name"])
                self.assertIsNotNone(course)
                self.assertTrue(kb.course_original_entries(course), "原文应可阅读")
                self.assertTrue(data.course_sections(course), "章节应可定位")
                self.assertTrue(kb.course_context_chunks(course, 24000), "整课应可分块")

                keywords = ((course.get("summary") or {}).get("keywords") or ["AI"])
                with mock.patch.object(data.st, "session_state", {
                    "llm_model": "offline-test", "chat_msgs": [], "cleaned_cache": {},
                }):
                    system, user, evidence = data.build_qa_request(item, keywords[0])
                self.assertTrue(system and user, "问答 Prompt 应可组装")
                self.assertTrue(evidence, "问答应能定位真实原文依据")
                self.assertTrue(all(entry["id"].startswith("original-") for entry in evidence))

                questions = data.generate_course_assessment(
                    item, None, data._rule_cleaned_doc(course), career,
                    "", "offline-test", num_q=3,
                )
                self.assertEqual(len(questions), 3)
                self.assertTrue(all(q["question_kind"] == "course_text" for q in questions))


if __name__ == "__main__":
    unittest.main()
