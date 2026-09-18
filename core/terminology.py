"""有依据的课程术语校订；只处理派生学习文本，不改写原始引用。"""

import re


TERMINOLOGY_VERSION = 1
# 规则限定已确认的误写；RAG 全称另由原论文及课程 22:19 交叉核对。
TERM_RULES = (
    (r"(?<![A-Za-z])Retrieve\s+as\s+you\s+Go(?![A-Za-z])",
     "Retrieval-Augmented Generation", None),
    (r"Model\s+Scope\s+Platform", "Model Context Protocol", r"\bMCP\b"),
    (r"方程call|风声call|风声扣", "Function Calling", None),
    (r"(?<![A-Za-z])Long\s+(?:Graf|Graph)(?![A-Za-z])", "LangGraph", None),
    (r"(?<![A-Za-z])Lama\s+Index(?![A-Za-z])", "LlamaIndex", None),
    (r"(?<![A-Za-z])(?:evening|inventing|invention|in\s+pending|infinity)"
     r"(?=\s*模型)", "Embedding", r"向量|切片|检索|\bRAG\b"),
    (r"(?<![A-Za-z])in\s+contest\s+learning(?![A-Za-z])",
     "In-Context Learning", r"提示词|上下文|参考资料|样例"),
    (r"(?<![A-Za-z])Agented\s+RAG(?![A-Za-z])", "Agentic RAG", None),
)


def correct_terms(text: str) -> str:
    """按完整 token 与句内技术语境校订已确认术语，不猜测人名和模型版本。"""
    value = str(text or "")
    for pattern, replacement, cue in TERM_RULES:
        if cue is None or re.search(cue, value, flags=re.I):
            value = re.sub(pattern, replacement, value, flags=re.I)
    return value


def terminology_prompt() -> str:
    """为结构化整理提供术语约束，与离线纠错共用已确认定义。"""
    return (
        "术语核对：RAG = Retrieval-Augmented Generation（检索增强生成）；"
        "MCP = Model Context Protocol；Embedding 为嵌入/向量表征；"
        "Agentic RAG 为智能体参与检索的流程。只在对应技术语境使用。"
        "不得照抄导读中的错误英文展开，不确定的人名、型号、数字保留疑问，"
        "不要自行猜测补全。区分讲师的个案经验与通用事实，保留条件和否定。"
    )
