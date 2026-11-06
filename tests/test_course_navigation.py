"""知识图谱到课程精华的页面交互回归。"""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class CourseNavigationTests(unittest.TestCase):
    def test_graph_jump_syncs_directory_and_resets_detail(self):
        """跨模块、同课点击均打开整课精华，未入库课程不可跳转。"""
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=60)
        app.radio(key="knowledge_view").set_value("岗位路线").run(timeout=60)
        for course_id in ("3-1", "3-1", "1-1", "1-2"):
            app.session_state["tab1_detail"] = "🧠 知识图谱"
            app.run(timeout=60)
            app.button(key=f"open_graph_course_{course_id}").click().run(timeout=60)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["current_course"]["id"], course_id)
            self.assertTrue(app.selectbox(key="tab1_course").value.startswith(course_id + "｜"))
            self.assertEqual(app.selectbox(key="tab1_section").value, "整门课程")
            self.assertEqual(app.session_state["tab1_detail"], "✨ 课程精华")
        summaries = "\n".join(str(info.value) for info in app.info)
        self.assertIn("Retrieval-Augmented Generation", summaries)
        self.assertNotIn("Retrieve as you Go", summaries)
        self.assertTrue(any(expander.label == "术语校订与依据" for expander in app.expander))
        app.selectbox(key="tab1_section").select_index(1).run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(any("原文依据：" in str(caption.value) for caption in app.caption))
        app.selectbox(key="tab1_section").select_index(0).run(timeout=60)
        app.radio(key="knowledge_view").set_value("岗位路线").run(timeout=60)
        self.assertTrue(app.button(key="open_graph_course_2-0").disabled)

    def test_graph_filters_and_empty_state(self):
        """默认本课视图、课程筛选与搜索空态可用。"""
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=60)
        self.assertEqual(app.radio(key="knowledge_view").value, "本课知识")
        app.radio(key="knowledge_view").set_value("岗位路线").run(timeout=60)
        app.radio(key="graph_scope").set_value("已有文字").run(timeout=60)
        buttons = [b for b in app.button if (b.key or "").startswith("open_graph_course_")]
        self.assertTrue(buttons)
        self.assertTrue(all(not b.disabled for b in buttons))
        app.text_input(key="graph_search").set_value("rAg").run(timeout=60)
        buttons = [b for b in app.button if (b.key or "").startswith("open_graph_course_")]
        self.assertTrue(buttons)
        self.assertTrue(all("rag" in b.label.lower() for b in buttons))
        app.text_input(key="graph_search").set_value("不存在的课程xyz").run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(any("没有符合条件" in str(i.value) for i in app.info))
