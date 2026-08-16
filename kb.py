# -*- coding: utf-8 -*-
"""
kb.py —— 兼容转发层

历史脚本（_test_kb.py / _inspect_docx.py 等）仍可通过 `import kb` 使用原有解析能力。
真实实现已迁移至 core/kb.py（docx 解析、口语去噪、课程名归一化、离线出题、上下文拼接）。
"""

from core.kb import *  # noqa: F401,F403
