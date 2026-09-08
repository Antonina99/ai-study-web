# -*- coding: utf-8 -*-
"""
core/data.py —— 数据与业务核心层

职责：
1. 静态配置：CAREER_DIRECTIONS（5 大求职方向）、COURSE_MODULES/MODULES（5 大核心模块课程大纲）、QUESTIONS（离线题库）。
2. 课程绑定索引 / 知识库加载 / 关键词加权。
3. 课程资产组装：get_clean_course_data（关键词/摘要/可折叠知识树/干货/考点，含 session 缓存与离线降级）。
4. 出题：AI 实战出题（focus 强约束注入）、逐单元自测、离线兜底（选项洗牌）。
5. 题目工具：选项标签/索引换算、AI 助教 Prompt 构造。
"""

import hashlib
import json
import random
import re

import streamlit as st

from core import kb, llm

COURSE_CLEAN_CHUNK_CHARS = 24000
LLM_COURSE_CONTEXT_CHARS = 12000
COURSE_CLEAN_VERSION = 2
NON_LEARNING_KEYWORDS = {
    "直播", "开班典礼", "课程安排", "课程服务", "就业服务", "班主任", "助教",
    "课表", "录播课", "直播课", "资源领取", "课程平台",
}

# ================================================================ 1. 求职方向
CAREER_DIRECTIONS = {
    "agent_fullstack": {
        "name": "AI 应用开发 / 全栈工程师",
        "desc": "专注于智能体构建、RAG 系统搭建与应用层落地",
        "focus": ["Agent", "RAG", "MCP", "OpenManus", "LangChain/LlamaIndex", "Function Calling"],
        "fallback_job": "agent_developer",
    },
    "llm_algorithm": {
        "name": "大模型算法 / 微调工程师",
        "desc": "专注于模型预训练、SFT 微调、RLHF/DPO 强化学习与多模态",
        "focus": ["LLM微调", "数据工程", "模型蒸馏", "多模态", "PEFT/LoRA", "DeepSpeed"],
        "fallback_job": "finetune_engineer",
    },
    "infra_devops": {
        "name": "AI 推理服务 / Infra / 运维工程师",
        "desc": "专注于高性能推理加速、集群调度与高并发部署",
        "focus": ["SGLang", "vLLM", "显卡调度", "高并发部署", "Quantization量化", "K8s/Triton"],
        "fallback_job": "infra_engineer",
    },
    "ai_pm_architect": {
        "name": "AI 产品经理 / 解决方案架构师",
        "desc": "专注于业务场景商业化落地、技术选型与 ROI/体验优化",
        "focus": ["业务场景落地", "技术选型", "成本与体验", "提示词策略", "竞品分析"],
        "fallback_job": "ai_pm",
    },
    "prompt_coding": {
        "name": "Prompt 与 AI 提效",
        "desc": "专注于提示词工程、AI 辅助编程（AI Coding）与个人/企业提效",
        "focus": ["Prompt工程", "AI Coding", "Cursor/Copilot", "Workflow自动化", "结构化输出"],
        "fallback_job": "prompt_engineer",
    },
}


def career_prompt_params(career_direction):
    """把求职方向键换算为 (方向名, 强约束关键词串)，供 Prompt 注入。"""
    cfg = CAREER_DIRECTIONS.get(career_direction)
    if cfg:
        return cfg["name"], "、".join(cfg["focus"])
    return career_direction or "", ""


# ================================================================ 2. 课程大纲
# 数据源：按核心技术模块划分（5 大模块），模块名自带序号与 emoji，课程以此为唯一权威。
COURSE_MODULES = {
    "🛠️ 1. LLM 基础与 AI 编程提效": [
        "开学典礼",
        "AI大模型基本原理及API使用",
        "从提示工程到RAG：构建大模型的知识与交互基础",
        "AI编程-从入门到精通",
        "大厂优秀工程师使用AI Coding 的最新方法与经验",
        "大型软件项目的AI开发与AI重构",
        "AI Coding 中的团队重新分工与新协作模式",
    ],
    "📚 2. RAG 企业级知识库与检索": [
        "Embeddings和向量数据库",
        "RAG技术与应用",
        "RAG多模态数据处理",
        "RAG调优",
        "LLM Wiki",
        "部分场景中可以取代RAG的技术",
        "LangChain：多任务应用开发",
        "AI框架设计与选型",
        "🔥 项目实战：企业知识库（企业RAG大赛冠军项目）",
        "💼 就业服务：RAG及开发框架相关简历+面试问题辅导",
    ],
    "🤖 3. Agent 自主体、MCP 协议与 Harness 架构": [
        "Agent：从可控性到自主反思",
        "🔥 Function Calling与MCP (上下文交互协议)",
        "Agent的自主规划与工具开发",
        "Agent的能力优化与效果评估",
        "🔥 Harness Engineering",
        "搭建Hermes Agent 中的长期记忆和自进化能力",
        "实现Hermes中的多Agent协作、主Agent调度",
        "🔥 项目实战：OpenManus开发实战",
        "💼 就业服务：Agent相关简历+面试问题辅导",
    ],
    "⚙️ 4. LLM 微调、CV与算力 Infra 部署": [
        "神经网络基础与Tensorflow实战",
        "Pytorch与视觉检测",
        "视觉与多模态模型",
        "多模态前沿：从Agent构建到视频AIGC",
        "LLM微调原理",
        "🔥 高质量微调数据工程与评估",
        "LLM模型蒸馏与微调实操",
        "HuggingFace生态实战：从模型应用到高效微调",
        "企业级AI部署：从硬件选型到框架选择",
        "AI服务核心：高并发原理与性能监控调优",
        "🔥 SGLang 深度优化：Radix 缓存与复杂任务的极致吞吐",
        "短剧视频逐帧换脸的显卡资源分配及排队系统",
        "🔥 在华为昇腾显卡上部署DeepSeek V4 模型 并连通本地Claude Code",
        "🔥 项目实战：AI质检",
        "💼 就业服务：模型训练与微调相关简历+面试问题辅导",
    ],
    "🎯 5. 毕业全栈实战与就业冲刺": [
        "综合实战项目复盘 (RAG + Agent + 微调 + 部署全链路集成)",
        "Agent / RAG / 开发框架 / 微调部署全套简历优化",
        "大模型高频面试真题精讲与模拟辅导",
    ],
}

# 课程学习路径使用完整课程名精确配置，不以标题关键词推断重要性。
CAREER_PATH_VARIANTS = {
    "ai_pm_architect": {"product": "AI 产品经理", "architect": "解决方案架构师"},
    "prompt_coding": {"coding": "AI 编程提效", "office": "办公提效"},
}
PATH_GAPS = {
    "llm_algorithm": "预训练、RLHF/DPO 的课程覆盖尚待原文确认。视觉检测与视频生成按岗位选学。",
    "infra_devops": "vLLM、量化、K8s/Triton 的课程覆盖尚待原文确认。",
    "product": "需求分析、业务指标和成本估算暂无明确专课，需补充学习。",
    "architect": "安全边界、容量规划和成本估算需结合项目补充验证。",
    "office": "办公工作流、信息整理和结果验证暂无充分的专课覆盖，编程课程按需选学。",
}


def _build_career_paths():
    """按完整课程标题生成各路径的等级、推荐理由与学习范围。"""
    paths = {key: {} for key in (
        "agent_fullstack", "llm_algorithm", "infra_devops", "product", "architect", "coding", "office"
    )}
    for course, level, reason, scope, targets in CAREER_COURSE_RULES:
        for target in targets.split():
            paths[target][course] = {"level": level, "reason": reason, "scope": scope}
    return paths


# 每行显式列出课程、等级、理由、学习范围和适用路径。
CAREER_COURSE_RULES = [
    ('AI大模型基本原理及API使用', '基础必学', '建立模型能力边界与调用基础', '模型限制、API、输出检查', 'agent_fullstack llm_algorithm infra_devops product architect coding office'),
    ('从提示工程到RAG：构建大模型的知识与交互基础', '基础必学', '理解提示与外部知识如何影响结果', '提示设计、知识引用、结果验证', 'agent_fullstack product architect coding office'),
    ('Embeddings和向量数据库', '岗位核心', '为检索召回和RAG调优建立基础', '语义表示、索引与检索', 'agent_fullstack architect'),
    ('RAG技术与应用', '岗位核心', '建立知识检索与生成链路', '检索、生成与引用', 'agent_fullstack architect'),
    ('RAG调优', '岗位核心', '定位并改善知识问答效果', '召回、重排与评估', 'agent_fullstack architect'),
    ('AI框架设计与选型', '岗位核心', '根据交付约束选择技术方案', '框架边界与选型比较', 'agent_fullstack architect'),
    ('🔥 项目实战：企业知识库（企业RAG大赛冠军项目）', '岗位核心', '验证完整知识库的交付能力', '数据接入、检索、评估与集成', 'agent_fullstack architect'),
    ('🔥 Function Calling与MCP (上下文交互协议)', '岗位核心', '连接模型与外部工具', '工具接口、参数与执行边界', 'agent_fullstack architect'),
    ('Agent：从可控性到自主反思', '岗位核心', '理解智能体执行和控制机制', '任务循环、失败恢复与可控性', 'agent_fullstack architect'),
    ('Agent的能力优化与效果评估', '岗位核心', '建立可验证的任务质量标准', '成功率、工具调用与失败分析', 'agent_fullstack architect'),
    ('LangChain：多任务应用开发', '岗位核心', '实践应用编排与组件集成', '通过框架理解可迁移的工程模式', 'agent_fullstack'),
    ('Agent的自主规划与工具开发', '岗位核心', '实现可执行的任务链路', '规划、工具实现与错误处理', 'agent_fullstack'),
    ('🔥 Harness Engineering', '岗位核心', '完善智能体运行约束', '执行环境、反馈与控制', 'agent_fullstack'),
    ('🔥 项目实战：OpenManus开发实战', '岗位核心', '验证Agent工程实践能力', '关注工具集成与调试，而非记忆框架名', 'agent_fullstack'),
    ('搭建Hermes Agent 中的长期记忆和自进化能力', '专项选学', '在单Agent稳定后扩展复杂能力', '记忆或协作机制及适用边界', 'agent_fullstack architect'),
    ('实现Hermes中的多Agent协作、主Agent调度', '专项选学', '在单Agent稳定后扩展复杂能力', '记忆或协作机制及适用边界', 'agent_fullstack architect'),
    ('企业级AI部署：从硬件选型到框架选择', '岗位核心', '将模型应用可靠交付为服务', '硬件预算、部署与交付', 'agent_fullstack infra_devops architect'),
    ('AI服务核心：高并发原理与性能监控调优', '岗位核心', '将模型应用可靠交付为服务', '并发、延迟、吞吐与监控', 'agent_fullstack infra_devops architect'),
    ('神经网络基础与Tensorflow实战', '基础必学', '补齐训练所需基础', '神经网络与优化原理；框架实操按需', 'llm_algorithm'),
    ('Pytorch与视觉检测', '基础必学', '建立训练实现能力', 'PyTorch为基础；视觉检测按目标岗位选学', 'llm_algorithm'),
    ('LLM微调原理', '岗位核心', '完成数据、训练到评估的微调闭环', '结合验证集检查效果与泛化', 'llm_algorithm'),
    ('🔥 高质量微调数据工程与评估', '岗位核心', '完成数据、训练到评估的微调闭环', '结合验证集检查效果与泛化', 'llm_algorithm'),
    ('LLM模型蒸馏与微调实操', '岗位核心', '完成数据、训练到评估的微调闭环', '结合验证集检查效果与泛化', 'llm_algorithm'),
    ('HuggingFace生态实战：从模型应用到高效微调', '岗位核心', '完成数据、训练到评估的微调闭环', '结合验证集检查效果与泛化', 'llm_algorithm'),
    ('视觉与多模态模型', '专项选学', '面向多模态细分岗位拓展', '文本微调岗位可后置', 'llm_algorithm'),
    ('多模态前沿：从Agent构建到视频AIGC', '专项选学', '面向多模态细分岗位拓展', '文本微调岗位可后置', 'llm_algorithm'),
    ('🔥 SGLang 深度优化：Radix 缓存与复杂任务的极致吞吐', '岗位核心', '提升推理服务效率', '缓存、吞吐与性能测量', 'infra_devops'),
    ('短剧视频逐帧换脸的显卡资源分配及排队系统', '岗位核心', '学习共享算力的调度机制', '资源隔离、任务排队；业务案例为载体', 'infra_devops'),
    ('🔥 在华为昇腾显卡上部署DeepSeek V4 模型 并连通本地Claude Code', '专项选学', '满足国产算力适配需求', '目标岗位要求昇腾时优先', 'infra_devops'),
    ('Agent：从可控性到自主反思', '岗位核心', '支撑产品方案与效果判断', '理解能力边界与用户控制', 'product'),
    ('Agent的能力优化与效果评估', '岗位核心', '支撑产品方案与效果判断', '定义成功指标和效果验收', 'product'),
    ('AI框架设计与选型', '岗位核心', '支撑产品方案与效果判断', '了解方案约束，不要求深入框架实现', 'product'),
    ('🔥 项目实战：企业知识库（企业RAG大赛冠军项目）', '岗位核心', '支撑产品方案与效果判断', '关注场景、体验、验收与投入产出', 'product'),
    ('RAG多模态数据处理', '专项选学', '按实际业务场景选择案例', '产品看场景与验收；架构看集成边界', 'product architect'),
    ('🔥 项目实战：OpenManus开发实战', '专项选学', '按实际业务场景选择案例', '产品看场景与验收；架构看集成边界', 'product architect'),
    ('🔥 项目实战：AI质检', '专项选学', '按实际业务场景选择案例', '产品看场景与验收；架构看集成边界', 'product architect'),
    ('AI编程-从入门到精通', '岗位核心', '提升软件开发与验证效率', '任务拆解、代码审查、测试与重构', 'coding'),
    ('大厂优秀工程师使用AI Coding 的最新方法与经验', '岗位核心', '提升软件开发与验证效率', '任务拆解、代码审查、测试与重构', 'coding'),
    ('大型软件项目的AI开发与AI重构', '岗位核心', '提升软件开发与验证效率', '任务拆解、代码审查、测试与重构', 'coding'),
    ('AI Coding 中的团队重新分工与新协作模式', '专项选学', '适合团队负责人优化协作', '职责分工、审查与交付流程', 'coding office product'),
    ('LangChain：多任务应用开发', '专项选学', '需要编程自动化时扩展能力', '有编程基础后学习', 'coding office'),
    ('AI编程-从入门到精通', '专项选学', '仅在办公任务需要开发时学习', '非编程用户可跳过', 'office'),
    ('大型软件项目的AI开发与AI重构', '专项选学', '仅在办公任务需要开发时学习', '非编程用户可跳过', 'office'),
    ('综合实战项目复盘 (RAG + Agent + 微调 + 部署全链路集成)', '求职准备', '形成可展示的项目成果与复盘', '选取本方向负责的部分说明贡献', 'agent_fullstack llm_algorithm infra_devops product architect coding'),
    ('💼 就业服务：RAG及开发框架相关简历+面试问题辅导', '求职准备', '将学习成果转化为求职表达', '按目标岗位筛选题目与项目经历', 'agent_fullstack architect'),
    ('💼 就业服务：Agent相关简历+面试问题辅导', '求职准备', '将学习成果转化为求职表达', '按目标岗位筛选题目与项目经历', 'agent_fullstack'),
    ('💼 就业服务：模型训练与微调相关简历+面试问题辅导', '求职准备', '将学习成果转化为求职表达', '按目标岗位筛选题目与项目经历', 'llm_algorithm'),
    ('Agent / RAG / 开发框架 / 微调部署全套简历优化', '求职准备', '将学习成果转化为求职表达', '按目标岗位筛选题目与项目经历', 'agent_fullstack llm_algorithm infra_devops architect'),
    ('大模型高频面试真题精讲与模拟辅导', '求职准备', '将学习成果转化为求职表达', '按目标岗位筛选题目与项目经历', 'agent_fullstack llm_algorithm infra_devops product architect coding'),
]
CAREER_COURSE_PATHS = _build_career_paths()


# 模块补充元信息（展示说明 / 求职方向匹配主题 / 推荐理由）
_MODULE_META = {
    "🛠️ 1. LLM 基础与 AI 编程提效": {
        "desc": "从大模型原理与 API 调用，到 AI Coding 与大型软件项目重构，理解 AI 如何重塑个人开发效率与团队协作。",
        "topics": ["基础", "Prompt", "AI Coding", "RAG"],
        "why": "所有方向的必修地基：模型原理 + Prompt + AI Coding 全链路一次打透。"},
    "📚 2. RAG 企业级知识库与检索": {
        "desc": "从 Embeddings/向量数据库到 RAG 调优与多模态检索，再通过 LangChain 与框架选型落地企业级知识库实战。",
        "topics": ["RAG", "知识库", "向量数据库", "LangChain", "落地"],
        "why": "最广泛落地的 AI 场景：RAG 全链路 + 框架选型 + 冠军项目实战，应用开发与架构必学。"},
    "🤖 3. Agent 自主体、MCP 协议与 Harness 架构": {
        "desc": "从 Agent 可控性与 Function Calling，到 MCP 协议、Harness 架构与多 Agent 协作，掌握智能体全栈实战。",
        "topics": ["Agent", "MCP", "Harness", "Function Calling", "多Agent"],
        "why": "应用开发/全栈工程师的核心主场：Agent 原理 + MCP + Harness + OpenManus 实战全链路。"},
    "⚙️ 4. LLM 微调、CV与算力 Infra 部署": {
        "desc": "从神经网络/视觉基础到 LLM 微调与高质量数据工程，再到企业级部署、SGLang 优化与华为昇腾国产化实战。",
        "topics": ["微调", "CV", "多模态", "数据工程", "SGLang", "昇腾", "部署"],
        "why": "算法/微调/Infra 工程师的必选核心：微调 + 视觉多模态 + 高并发部署与国产化一条龙。"},
    "🎯 5. 毕业全栈实战与就业冲刺": {
        "desc": "综合 RAG + Agent + 微调 + 部署全链路项目复盘，配套全套简历优化与高频面试真题精讲。",
        "topics": ["就业", "面试", "项目复盘", "简历"],
        "why": "临门一脚：全链路实战复盘 + 简历优化 + 面试冲刺，直击 offer。"},
}

# 由 COURSE_MODULES 生成 MODULES（no 取自模块名自带编号，兼容既有字段结构）
MODULES = []
for _i, (_mname, _mcourses) in enumerate(COURSE_MODULES.items(), start=1):
    _mno = re.search(r"\d+", _mname)
    MODULES.append({
        "no": int(_mno.group()) if _mno else _i,
        "name": _mname,
        "courses": _mcourses,
        **_MODULE_META.get(_mname, {}),
    })


# ================================================================ 3. 离线题库
# 为 5 个求职方向各配置 5 道高频面试题，answer 分散（不再全为 A）。
# 运行时会再洗牌一次，保证顺序随机。
QUESTIONS = {
    "agent_developer": [
        {"q": "MCP（Model Context Protocol）协议的核心作用是什么？",
         "options": ["替代向量数据库存储上下文", "为模型提供标准化方式连接外部工具与数据源", "一种新的模型量化格式", "专门用于模型预训练的数据格式"],
         "answer": 1, "explain": "MCP 是连接大模型与外部工具/数据源的标准化接口协议，解决工具生态碎片化问题，而非替代向量库或用于训练。", "source": "offline"},
        {"q": "搭建 RAG 系统时，最影响检索质量的第一步通常是？",
         "options": ["选最大的向量模型", "把召回 Top-K 调到最大", "文档切分（chunking）策略", "直接用全文搜索代替向量检索"],
         "answer": 2, "explain": "切分策略直接决定片段语义完整性，是 RAG 召回质量的基石；模型大小与 Top-K 更多是调优环节。", "source": "offline"},
        {"q": "Agent 与普通「单次 LLM 调用」最本质的区别是？",
         "options": ["Agent 具备循环推理 + 工具调用 + 自我纠错的能力", "Agent 一定使用更大的模型", "Agent 不需要系统提示词", "Agent 只能处理文本"],
         "answer": 0, "explain": "Agent 核心是「感知-决策-行动-反思」循环，能自主调用工具并纠正错误；单次调用是一次性的输入输出映射。", "source": "offline"},
        {"q": "Function Calling（函数调用）在智能体中的典型用途是？",
         "options": ["压缩上下文", "给模型添加记忆", "提升推理速度", "让模型按 JSON Schema 输出参数并触发外部动作"],
         "answer": 3, "explain": "Function Calling 让模型根据意图生成结构化的函数参数，应用层据此执行外部 API/工具，是 Agent 落地 Tool Use 的基础。", "source": "offline"},
        {"q": "LangChain 与 LlamaIndex 在应用开发中的定位差异是？",
         "options": ["两者完全相同", "LlamaIndex 只能做聊天", "LangChain 侧重编排与 Agent 生态，LlamaIndex 侧重数据索引与检索", "LangChain 不提供 LCEL"],
         "answer": 2, "explain": "LangChain 强在 Chain/Agent 编排，LlamaIndex 强在文档索引/检索/RAG 数据层，常配合使用。", "source": "offline"},
    ],
    "finetune_engineer": [
        {"q": "SFT（监督微调）的主要目的是？",
         "options": ["压缩模型体积", "让基座模型学会遵循指令与特定输出格式", "加速推理", "替代全部 RLHF"],
         "answer": 1, "explain": "SFT 用（指令, 期望输出）对训练，将基座模型对齐到指令跟随与任务格式，是 RLHF 之前的关键步骤。", "source": "offline"},
        {"q": "LoRA 相比全参微调（Full Fine-tuning）最突出的优势是？",
         "options": ["效果一定更好", "只需要低秩适配矩阵，显存占用与参数量大幅降低", "只能用于文本模型", "不需要数据"],
         "answer": 1, "explain": "LoRA 冻结原权重、只训练低秩适配矩阵，可插拔、显存友好，适合多任务/多用户场景。", "source": "offline"},
        {"q": "RLHF 的标准三步流程是？",
         "options": ["SFT → 奖励模型训练 → PPO 强化学习", "直接强化学习 → 蒸馏 → 量化", "预训练 → 裁剪 → 蒸馏", "数据增强 → 蒸馏 → 评测"],
         "answer": 0, "explain": "RLHF 先做指令微调，再训练奖励模型（人类偏好标注），最后用 PPO 等算法优化策略模型。", "source": "offline"},
        {"q": "模型蒸馏（Distillation）的核心思想是？",
         "options": ["用更小的模型指导大模型", "把模型切分到多卡", "只保留注意力头", "用大模型的软标签/输出分布训练小模型，让模型逼近大模型能力"],
         "answer": 3, "explain": "蒸馏用教师模型输出的软标签（概率分布）训练学生模型，是模型轻量化、成本优化的重要手段。", "source": "offline"},
        {"q": "微调数据工程中最关键的质量指标通常是什么？",
         "options": ["样本条数越多越好", "全部用模型生成的数据", "文本越长越好", "指令-答案对齐度、覆盖度与去重去噪"],
         "answer": 3, "explain": "微调效果上限由数据质量决定：对齐、覆盖、去重、噪声控制比盲目堆量更重要。", "source": "offline"},
    ],
    "infra_engineer": [
        {"q": "SGLang 的核心定位是？",
         "options": ["一种向量数据库", "面向大模型的高性能推理与服务框架（RadixAttention 等）", "一个前端框架", "模型训练调度器"],
         "answer": 1, "explain": "SGLang 专注推理吞吐与结构化生成优化，RadixAttention 缓存前缀，与 vLLM 同属高性能推理框架。", "source": "offline"},
        {"q": "vLLM 中 PagedAttention 主要解决的问题是？",
         "options": ["KV Cache 显存碎片化与浪费", "模型过拟合", "数据标注成本", "网络带宽"],
         "answer": 0, "explain": "PagedAttention 借鉴操作系统分页思想管理 KV Cache，显著提升显存利用率和吞吐。", "source": "offline"},
        {"q": "昇腾 NPU 上部署模型，从 CUDA 迁移的核心依赖是？",
         "options": ["只改模型权重", "CANN（异构计算架构）与配套算子/推理引擎", "更换训练数据", "必须重写全部业务代码"],
         "answer": 1, "explain": "昇腾生态依赖 CANN，模型迁移涉及算子适配、推理引擎（如 MindIE）与 API 兼容层，业务侧尽量透明。", "source": "offline"},
        {"q": "多卡推理时「张量并行（TP）」的含义是？",
         "options": ["按 batch 切分数据", "只复制模型权重不计算", "把单个 Transformer 层的参数按维度切分到多卡协同计算", "多副本各自推理后投票"],
         "answer": 2, "explain": "张量并行将单层权重按维度拆分到多卡并行计算，适合单卡放不下的大模型；数据并行/流水线并行是另一种切法。", "source": "offline"},
        {"q": "长上下文场景下显存与延迟压力主要来自？",
         "options": ["KV Cache 随序列长度线性增长", "词表大小", "Batch 数太少", "输出温度"],
         "answer": 0, "explain": "KV Cache 与序列长度成正比，长上下文是显存瓶颈主因，常见对策有 KV 量化、滑动窗口、前缀缓存等。", "source": "offline"},
    ],
    "ai_pm": [
        {"q": "评估一个「用大模型改造业务」的需求时，最先应该确认的是？",
         "options": ["直接用最贵的模型", "业务目标与成功指标（ROI 可量化）", "用哪个向量库", "微调还是 RAG"],
         "answer": 1, "explain": "先定义业务价值与量化指标，再做技术选型；技术细节（RAG/微调/向量库）是后续手段。", "source": "offline"},
        {"q": "RAG 项目落地效果差，最常见的根因排序通常是？",
         "options": ["先排查检索召回质量，再看生成幻觉", "直接怀疑模型能力", "先换更大的模型", "先加更多 GPU"],
         "answer": 0, "explain": "RAG 效果 80% 以上取决于「检索」环节（切分、召回、重排），生成侧问题是第二位的。", "source": "offline"},
        {"q": "在满足效果前提下降低 LLM 调用成本，最推荐的路径是？",
         "options": ["无限增加缓存", "分级模型策略：简单任务用小模型、复杂任务用大模型 + Prompt 压缩与缓存", "永远只用最贵模型", "禁止流式输出"],
         "answer": 1, "explain": "按任务难度分级路由、prompt 压缩、结果缓存是 ROI 最高的成本优化组合。", "source": "offline"},
        {"q": "客户要求私有化部署大模型应用，方案评审的首要关注点是？",
         "options": ["界面好看", "是否用了最新框架", "团队成员数量", "数据安全边界、算力评估与模型合规授权"],
         "answer": 3, "explain": "私有化核心是数据不出域、算力与模型规格匹配、License 合规；技术选型服务于此。", "source": "offline"},
        {"q": "给客户写技术方案时，最应该体现的部分是？",
         "options": ["业务痛点 → 架构设计 → 选型对比 → 成本与风险 → 里程碑", "罗列全部 AI 术语", "只写代码示例", "只写市场分析"],
         "answer": 0, "explain": "方案要形成「问题-方案-依据-成本-风险-计划」闭环，让客户能据此决策与验收。", "source": "offline"},
    ],
    "prompt_engineer": [
        {"q": "Few-shot（少样本）提示的核心做法是？",
         "options": ["在提示中给出若干输入输出示例，引导模型模仿", "让模型随机发挥", "只给一个关键词", "关闭流式输出"],
         "answer": 0, "explain": "Few-shot 通过在上下文中展示示例，让模型理解任务模式，是提升输出质量的低成本手段。", "source": "offline"},
        {"q": "思维链（Chain-of-Thought）提示适用于什么场景？",
         "options": ["只适用于翻译", "需要多步推理的复杂任务（数学、逻辑、决策）", "只适用于画图", "任何简单问答都强制要求"],
         "answer": 1, "explain": "CoT 引导模型逐步推理，显著提升复杂推理任务的准确率，是推理类提示的标准技巧。", "source": "offline"},
        {"q": "给模型设定「角色」（System 角色描述）的主要作用是？",
         "options": ["限制模型长度", "减少显存", "提升模型运行速度", "提供回复的风格、立场与边界约束"],
         "answer": 3, "explain": "角色设定是一种强先验约束，让模型以指定专家身份、语气和规则作答，提升一致性。", "source": "offline"},
        {"q": "用 AI Coding 工具写一段功能代码前，最有效的描述方式是？",
         "options": ["描述清晰的输入输出、边界条件与验收标准", "只说一句“写个登录”，让 AI 猜", "随便贴一段报错", "让 AI 直接改生产库"],
         "answer": 0, "explain": "AI Coding 的关键是「任务拆解 + 明确验收标准」，描述越具体，生成代码质量越高。", "source": "offline"},
        {"q": "要求模型输出「结构化 JSON」时，最稳妥的做法是？",
         "options": ["让模型自由发挥格式", "禁止模型输出引号", "在提示中给出 JSON Schema/示例，并声明只输出 JSON", "用正则从任意文本里硬解析"],
         "answer": 2, "explain": "给 Schema 示例 + 输出约束，配合解析兜底（错误重试），是生产级结构化输出的最佳实践。", "source": "offline"},
    ],
}


def shuffle_question(q):
    """复制并打乱一道题的选项顺序（修正『正确答案恒为 A』的 Bug），返回新题。"""
    opts = list(q["options"])
    ans = q["answer"]
    z = list(zip(opts, range(len(opts))))
    random.shuffle(z)
    q2 = dict(q)
    q2["options"] = [o for o, _ in z]
    q2["answer"] = next(i for i, (_, idx) in enumerate(z) if idx == ans)
    return q2


def fallback_questions(job_key, num_q):
    """离线兜底出题：优先本方向题库，不足时从其他方向补足，选项已洗牌。"""
    pool = [shuffle_question(q) for q in QUESTIONS.get(job_key, [])]
    if len(pool) >= num_q:
        return random.sample(pool, num_q)
    extra = []
    for k, qs in QUESTIONS.items():
        if k == job_key:
            continue
        for q in qs:
            extra.append(shuffle_question(q))
            if len(pool) + len(extra) >= num_q:
                break
        if len(pool) + len(extra) >= num_q:
            break
    return (pool + extra)[:num_q]


# ================================================================ 4. 课程索引
def module_hits(module, focus):
    """模块与求职方向的匹配度：子串包含匹配（如 focus『LLM微调』命中 topics『微调』）。"""
    topics = module.get("topics", [])
    if not topics or not focus:
        return 0
    return sum(1 for f in focus if any(t in f or f in t for t in topics))


def module_weight(module, focus):
    """模块权重 = 基础得分(0.15) + 求职方向匹配加成，用于推荐排序。"""
    hits = module_hits(module, focus)
    return 0.15 + 0.85 * min(1.0, hits / 2)


def course_learning_profile(course_name, career_direction, variant=None):
    """精确查询课程学习定位；未知课程返回空配置，不自动猜测。"""
    options = CAREER_PATH_VARIANTS.get(career_direction, {})
    path = variant if variant in options else next(iter(options), career_direction)
    return dict(CAREER_COURSE_PATHS.get(path, {}).get(course_name, {}))


def course_priority_reasons(course_name, career_direction):
    """兼容旧调用，返回基础或核心课程的具体推荐理由。"""
    profile = course_learning_profile(course_name, career_direction)
    return [profile["reason"]] if profile.get("level") in {"基础必学", "岗位核心"} else []


EXT_MODULE_NO = 99  # 「新增课程（自动发现）」模块编号


def _classify_courses(course_names, courses, api_key, model):
    """调用 LLM，把未按名称匹配的课程分配到已有模块。

    返回 {course_name: module_no}，无法判断的取 EXT_MODULE_NO。
    """
    if not course_names or not api_key:
        return {}
    modules_desc = "\n".join(
        f"{m['no']}. {m['name']}（主题：{', '.join(m.get('topics', []))}；"
        f"已有课程：{', '.join(m.get('courses', []))}）"
        for m in MODULES if m.get("no") != EXT_MODULE_NO
    )
    course_descs = []
    for name in course_names:
        course = courses.get(name) or {}
        text = kb.kb_course_context(course, max_chars=1000)
        course_descs.append(f"课程名：{name}\n课程摘要：{text}\n---")
    system = (llm.CLASSIFY_MODULE_SYSTEM_PROMPT
              .replace("{modules}", modules_desc)
              .replace("{courses}", "\n".join(course_descs)))
    try:
        text = llm.call_llm("请分类", system, api_key, model,
                            temperature=0.2, max_tokens=1200)
        data = llm._json_scan(text)
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, list):
            mapping = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                cname = item.get("course") or item.get("name") or item.get("course_name")
                if cname:
                    mapping[cname] = int(item.get("module_no", EXT_MODULE_NO))
            return mapping
    except Exception:
        pass
    return {}


def build_course_index(courses, api_key=None, model=None):
    """大纲课程 -> 知识库课程 绑定索引（归一化精确匹配，失败回退子串包含匹配）。

    注：courses 为 {课程名: {"original":..., "summary":...}}，课程名即键，无 name 字段。
    知识库课程名可能带序号/全角标点，这里对两侧都做归一化后再匹配（双向）。
    知识库中不在硬编码大纲里的课程：先按名称匹配，再调用 AI 判断应归入哪个模块；
    无 API Key 或 AI 判断失败时，才归入「新增课程」模块（EXT_MODULE_NO）。
    """
    index = []
    bound_keys = set()
    # 归一化映射：归一化课程名 -> 原始课程名（同一门课去重，保留第一个原始名）
    norm_map = {}
    for k in courses:
        nk = kb.normalize(k)
        if nk:
            norm_map.setdefault(nk, k)
    for mod in MODULES:
        # 「新增课程」模块（EXT_MODULE_NO）只是兜底展示，不参与大纲名称匹配，
        # 否则其中的课程会被精确绑定回 99，AI 分类永不触发
        if mod.get("no") == EXT_MODULE_NO:
            continue
        for i, c in enumerate(mod["courses"]):
            key = kb.normalize(c)
            hit_key = norm_map.get(key)
            if hit_key is None:
                # 精确匹配失败时退化为双向子串包含匹配
                for nk, ok in norm_map.items():
                    if nk in key or key in nk:
                        hit_key = ok
                        break
            if hit_key:
                bound_keys.add(hit_key)
            index.append({
                "id": f"{mod['no']}-{i}",
                "module_no": mod["no"],
                "name": c,
                "kb_name": hit_key,
            })
    # 追加知识库中存在、但未被任何大纲课程绑定/覆盖的课程（新增 docx 自动发现）
    extra = [k for k in courses if k not in bound_keys]
    extra_module_map = _classify_courses(extra, courses, api_key, model) if extra else {}
    for i, k in enumerate(extra):
        module_no = extra_module_map.get(k, EXT_MODULE_NO)
        index.append({
            "id": f"x-{i}",
            "module_no": module_no,
            "name": k,
            "kb_name": k,
        })
    return index


def _sync_extra_module():
    """把索引中「新增课程」模块的课程同步到 MODULES（幂等，不重复追加）。"""
    global MODULES
    extra = [it["name"] for it in COURSE_INDEX if it["module_no"] == EXT_MODULE_NO]
    for m in MODULES:
        if m.get("no") == EXT_MODULE_NO:
            m["courses"] = extra
            return
    if extra:
        MODULES = list(MODULES) + [{
            "no": EXT_MODULE_NO,
            "name": "新增课程（自动发现）",
            "desc": "自动从「课程原文及导读」文件夹发现的新课程，可正常查看与出题。",
            "courses": extra,
            "topics": [],
            "why": "将课程 docx 放入「课程原文及导读」文件夹后，本模块会自动出现对应课程。",
        }]


def refresh_kb():
    """轻量检测知识库变化：文件有新增/修改时重建 KB 与课程索引。

    Streamlit 每次交互都会 rerun，但 kb.build_kb() 只在模块加载时执行过一次；
    本函数让运行期间新增的 docx 也能被自动发现。若用户已配置 API Key，还会用 AI
    把「新增课程」模块中的未匹配课程智能分配到已有模块（文件未变化时也会尝试，
    但同一批课程只尝试一次，避免每次 rerun 重复调 LLM）。返回 True 表示发生了刷新。
    """
    global KB, COURSE_INDEX, newly_added
    changed = kb.has_file_changes()
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    # 待 AI 分类的课程（当前仍停留在「新增课程」模块中的）
    pending = sorted(it["name"] for it in COURSE_INDEX if it.get("module_no") == EXT_MODULE_NO)
    # 同一批课程已尝试过分类则跳过，避免每次 rerun 都调 LLM
    last_sig = st.session_state.get("_kb_classify_sig")
    need_classify = bool(api_key and pending and pending != last_sig)
    if not changed and not need_classify:
        return False
    kb_data, added = kb.build_kb() if changed else (KB, [])
    kb_data["index"] = build_course_index(kb_data.get("courses", {}), api_key, model)
    KB = kb_data
    COURSE_INDEX = KB.get("index", [])
    newly_added = added
    if need_classify:
        st.session_state["_kb_classify_sig"] = pending
    _sync_extra_module()
    return changed


# ================================================================ 5. 知识库加载
def build_kb():
    """加载知识库（含新增文件检测），并注入课程绑定索引。

    程序启动时调用，此时用户尚未填写 API Key，只按课程名匹配；
    未匹配的进入「新增课程」模块，待 refresh_kb 获取到 Key 后再做 AI 分配。
    """
    kb_data, newly_added = kb.build_kb()
    kb_data["index"] = build_course_index(kb_data.get("courses", {}))
    return kb_data, newly_added


KB, newly_added = build_kb()
COURSE_INDEX = KB.get("index", [])
_sync_extra_module()


# ================================================================ 6. 课程资产组装
def _parse_extract(content):
    """解析 AI 结构化萃取结果 -> 含 ok 标志的结构化 dict；失败返回 None。"""
    data = llm.parse_extract_json(content)
    if not data:
        return None

    def _lst(v, n):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()][:n]
        return []

    cleaned = kb.clean_course_text(data.get("cleaned_text") or data.get("clean_text") or "")
    summary = [kb.clean_text(x) for x in _lst(data.get("summary_points"), 5)]
    interview = [kb.clean_text(x) for x in _lst(data.get("interview_points"), 5)]
    summary = [x for x in summary if x]
    interview = [x for x in interview if x]
    keywords = _lst(data.get("keywords"), 8)
    return {
        "keywords": keywords,
        "summary_points": summary,
        "interview_points": interview,
        "cleaned_text": cleaned,
        "ok": bool(cleaned or summary or interview),
    }


def _course_clean_cache_key(item, course, model):
    """生成包含课程、源内容与模型的整理缓存键。"""
    source = json.dumps(course, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]
    return f"course-v{COURSE_CLEAN_VERSION}::{item.get('kb_name') or item.get('id')}::{model}::{digest}"


def _unique_values(values, limit):
    """去重并限制聚合字段长度。"""
    result = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _learning_keywords(values, limit=12):
    """清理关键词中的课程事务和直播运营标签。"""
    cleaned = []
    for value in values or []:
        text = kb.clean_text(value)
        if text and text not in NON_LEARNING_KEYWORDS:
            cleaned.append(text)
    return _unique_values(cleaned, limit)


def _balanced_chunk_values(processed, field, limit):
    """轮询各文本块聚合字段，避免整课摘要只来自前几个块。"""
    groups = [result.get(field) or [] for _, result in processed]
    values = []
    depth = 0
    while len(values) < limit and any(depth < len(group) for group in groups):
        for group in groups:
            if depth < len(group):
                values.append(group[depth])
        depth += 1
    return _unique_values(values, limit)


def cleaned_course_context(cleaned, max_chars=LLM_COURSE_CONTEXT_CHARS):
    """从分块整理正文中均衡抽取上下文，供整课问答和出题使用。"""
    text = (cleaned or {}).get("cleaned_text") or ""
    blocks = [block.strip() for block in re.split(r"(?=^## )", text, flags=re.MULTILINE)
              if block.strip()]
    if not blocks or len(text) <= max_chars:
        return text[:max_chars]
    quota = max(1, (max_chars - len(blocks) * 2) // len(blocks))
    excerpts = []
    for block in blocks:
        if len(block) > quota:
            head = quota * 2 // 3
            block = block[:head] + "…" + block[-max(1, quota - head - 1):]
        excerpts.append(block)
    return "\n\n".join(excerpts)[:max_chars]


def _merge_chunk_extracts(processed, total_chunks):
    """把分章节文本块的萃取结果合并为整课资产。"""
    summary_points = _balanced_chunk_values(processed, "summary_points", 12)
    interview_points = _balanced_chunk_values(processed, "interview_points", 10)
    cleaned_parts = []
    for chunk, result in processed:
        if result.get("cleaned_text"):
            cleaned_parts.append(f"## {chunk['title']}\n{result['cleaned_text']}")
    cleaned_text = kb.clean_course_text("\n\n".join(cleaned_parts))
    return {
        "keywords": _learning_keywords(_balanced_chunk_values(processed, "keywords", 20)),
        "summary_points": summary_points,
        "interview_points": interview_points,
        "cleaned_text": cleaned_text,
        "processed_chunks": len(processed),
        "total_chunks": total_chunks,
        "ok": bool(cleaned_text or summary_points or interview_points),
    }


def get_cleaned(item, api_key, model):
    """按章节块进行 AI 萃取并合并整课结果；失败时返回可用的部分结果。"""
    cache = st.session_state.setdefault("cleaned_cache", {})
    course = KB["courses"].get(item.get("kb_name"))
    if not api_key or not course:
        return None
    cache_key = _course_clean_cache_key(item, course, model)
    if cache.get(cache_key):
        return cache[cache_key]
    chunks = kb.course_context_chunks(course, max_chars=COURSE_CLEAN_CHUNK_CHARS)
    processed = []
    for chunk in chunks:
        chunk_key = f"{cache_key}::{chunk['id']}"
        cleaned = cache.get(chunk_key)
        if not cleaned:
            try:
                response = llm.call_llm(
                    chunk["text"], llm.EXTRACT_SYSTEM_PROMPT, api_key, model,
                    temperature=0.2, max_tokens=2200,
                )
                cleaned = _parse_extract(response)
                if cleaned:
                    cache[chunk_key] = cleaned
            except Exception:
                cleaned = None
        if cleaned:
            processed.append((chunk, cleaned))
    merged = _merge_chunk_extracts(processed, len(chunks))
    if not merged["ok"]:
        return None
    if len(processed) == len(chunks):
        cache[cache_key] = merged
    return merged


def get_cached_cleaned(item, model=None):
    """读取当前课程、源内容和模型对应的整课整理缓存。"""
    course = KB["courses"].get(item.get("kb_name"))
    if not course:
        return None
    selected_model = model or st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    cache_key = _course_clean_cache_key(item, course, selected_model)
    return st.session_state.get("cleaned_cache", {}).get(cache_key)


def _rule_cleaned_doc(course, max_chars=2800):
    """离线规则版干货正文；无导读时回退到清洗后的转写原文。"""
    parts = []
    sm = course.get("summary") or {}
    summary_text = (sm.get("summary") or "").strip()
    if summary_text:
        parts.append(f"## 核心概览\n{kb.clean_text(summary_text)}")
    sections = sm.get("sections", [])
    if len(sections) > 6:
        indexes = [round(index * (len(sections) - 1) / 5) for index in range(6)]
        sections = [sections[index] for index in indexes]
    for sec in sections:
        body = (sec.get("body") or "").strip()
        if body:
            title = kb.clean_text(sec.get("title") or "课程知识点")
            parts.append(f"## {title}\n{kb.clean_text(body)}")
    if not parts:
        org = course.get("original") or {}
        for segment in org.get("segments", []):
            body = kb.clean_text(segment.get("text") or "")
            if body:
                parts.append(body)
    if parts:
        overview = kb.clean_course_text("\n\n".join(parts))
        return overview[:max_chars]
    return kb.clean_course_text(kb.kb_course_context(course, max_chars=max_chars))


def course_sections(course):
    """返回统一章节列表；缺少导读时用转写原文的时间段或段落兜底。"""
    sm = (course or {}).get("summary") or {}
    if sm.get("sections"):
        return sm["sections"]

    org = (course or {}).get("original") or {}
    sections = []
    for index, segment in enumerate(org.get("segments", [])):
        body = kb.clean_text(segment.get("text") or "")
        if not body:
            continue
        preview = re.sub(r"\s+", " ", body).strip()
        if len(preview) > 26:
            preview = preview[:26] + "…"
        sections.append({
            "id": f"original-{index + 1}",
            "ts": segment.get("ts") or "",
            "title": preview or f"转写段落 {index + 1}",
            "body": body,
            "source": "original",
        })
    return sections


def section_label(section):
    """生成章节选择标签；无时间戳段落只显示稳定段落编号与内容摘要。"""
    timestamp = (section or {}).get("ts") or ""
    title = (section or {}).get("title") or "未命名章节"
    marker = timestamp or (section or {}).get("id") or "转写段落"
    return f"{marker}｜{title}"


def _balanced_items(values, limit):
    """从长列表头尾均衡选取条目，保留课程前后知识脉络。"""
    items = _unique_values([kb.clean_text(value) for value in values], 100)
    if len(items) <= limit:
        return items
    indexes = [round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)]
    return [items[index] for index in indexes]


def course_knowledge_groups(clean_text, career_direction, course=None, keywords=None,
                            summary_points=None, interview_points=None):
    """返回当前课程的可折叠知识分组。"""
    course = course or {}
    summary = course.get("summary") or {}
    topic_items = _balanced_items(keywords or summary.get("keywords") or [], 8)
    section_items = _balanced_items(
        [section.get("title") for section in summary.get("sections", []) if section.get("title")],
        12,
    )
    takeaway_source = interview_points or summary_points or []
    if not takeaway_source:
        takeaway_source = re.findall(r"[^。！？!?；;]+", clean_text or "")
    takeaway_items = _balanced_items(takeaway_source, 8)

    focus = CAREER_DIRECTIONS.get(career_direction, {}).get("focus", []) or []
    searchable = " ".join(topic_items + section_items + takeaway_items + [clean_text or ""]).casefold()
    career_items = []
    for value in focus:
        tokens = [token for token in re.split(r"[/、]", value) if token]
        if any(token.casefold() in searchable for token in tokens):
            career_items.append(value)
    groups = [
        {"name": "核心主题", "items": topic_items},
        {"name": "课程脉络", "items": section_items},
        {"name": "实践与考点", "items": takeaway_items},
        {"name": "求职关联", "items": _balanced_items(career_items, 5)},
    ]
    return [group for group in groups if group["items"]]


def get_clean_course_data(item, career_direction, api_key=None, model=None):
    """组装一门课程的关键词、摘要、干货、考点与可折叠知识分组。

    - api_key / model 可省略：省略时自动从会话读取；
    - AI 优先，未配置 Key 或萃取失败时降级为离线规则版。
    """
    api_key = api_key or st.session_state.get("api_key", "").strip()
    model = model or st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    course = KB["courses"].get(item.get("kb_name")) or {}
    sm = course.get("summary") or {}
    cleaned = get_cleaned(item, api_key, model)
    ok = bool(cleaned and cleaned.get("ok"))

    summary_points = cleaned["summary_points"] if ok and cleaned["summary_points"] else [
        kb.clean_text(value)
        for value in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", sm.get("summary") or "")
        if kb.clean_text(value)
    ][:5]
    summary = " ".join(summary_points) if summary_points else "（暂无摘要）"
    keywords = _learning_keywords(
        cleaned["keywords"] if ok and cleaned["keywords"] else (sm.get("keywords") or [])
    )
    interview_points = cleaned["interview_points"] if ok else []
    clean_text = cleaned["cleaned_text"] if ok and cleaned["cleaned_text"] else _rule_cleaned_doc(course)

    knowledge_groups = course_knowledge_groups(
        clean_text,
        career_direction,
        course,
        keywords=keywords,
        summary_points=summary_points,
        interview_points=interview_points,
    )

    return {
        "keywords": keywords,
        "summary": summary,
        "summary_points": summary_points,
        "knowledge_groups": knowledge_groups,
        "clean_text": clean_text,
        "interview_points": interview_points,
        "processed_chunks": cleaned.get("processed_chunks", 0) if cleaned else 0,
        "total_chunks": cleaned.get("total_chunks", 0) if cleaned else 0,
    }


# ================================================================ 7. 出题
def _query_terms(text):
    """提取中英文检索词；中文长句补充 2~4 字片段以适配口语转写。"""
    raw = str(text or "").casefold()
    terms = re.findall(r"[a-z][a-z0-9_.+-]{1,30}|[\u4e00-\u9fff]{2,}", raw)
    expanded = []
    for term in terms:
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 4:
            expanded.extend(term[index:index + size]
                            for size in (4, 3, 2)
                            for index in range(len(term) - size + 1))
        else:
            expanded.append(term)
    stop = {"什么", "怎么", "为什么", "这个", "这些", "课程", "当前", "内容", "总结", "一下"}
    return [term for term in dict.fromkeys(expanded) if term not in stop]


def course_evidence(item, query="", section=None, limit=4):
    """从指定课程/章节返回真实原文依据，标识和时间戳均由知识库生成。"""
    course = KB["courses"].get((item or {}).get("kb_name")) or {}
    entries = kb.course_original_entries(course)
    if section:
        allowed = {id(segment) for segment in kb.section_original_segments(course, section)}
        original_segments = ((course.get("original") or {}).get("segments") or [])
        allowed_indexes = {index for index, segment in enumerate(original_segments, 1)
                           if id(segment) in allowed}
        entries = [entry for entry in entries if entry["index"] in allowed_indexes]
    if not entries:
        return []

    terms = _query_terms(query)
    scored = []
    for entry in entries:
        lowered = entry["text"].casefold()
        score = sum((len(term) ** 2) * lowered.count(term) for term in terms)
        if score:
            scored.append((score, entry))
    if scored:
        selected = [entry for _, entry in sorted(scored, key=lambda pair: (-pair[0], pair[1]["index"]))[:limit]]
    elif terms:
        return []
    else:
        count = min(limit, len(entries))
        indexes = [round(index * (len(entries) - 1) / max(1, count - 1)) for index in range(count)]
        selected = [entries[index] for index in dict.fromkeys(indexes)]

    section_name = (section or {}).get("title") if isinstance(section, dict) else ""
    return [{**entry, "course": item.get("name") or item.get("kb_name") or "",
             "section": section_name or "整门课程"} for entry in selected]


def evidence_text(evidence):
    """把已验证引用格式化为 Prompt 上下文。"""
    return "\n\n".join(
        f"[{entry['id']} | {entry['marker']}] {entry['text']}" for entry in evidence
    )


def verified_citations(citation_ids, evidence):
    """仅保留当前候选集合中的引用，并返回本地原文而非模型复述。"""
    allowed = {entry["id"]: entry for entry in evidence}
    result = []
    for citation_id in citation_ids or []:
        value = citation_id.get("id") if isinstance(citation_id, dict) else citation_id
        if value in allowed and value not in {entry["id"] for entry in result}:
            result.append(allowed[value])
    return result


def sanitize_answer_citations(answer, evidence):
    """移除回答中不在白名单内的 original-N，防止展示虚构引用。"""
    allowed = {entry["id"] for entry in evidence}
    return re.sub(r"original-\d+",
                  lambda match: match.group(0) if match.group(0) in allowed else "无效引用已移除",
                  str(answer or ""))


def generate_practical_quiz(clean_text, career_direction, api_key, model, num_q=3, label="", evidence=None):
    """基于课程干货 + 求职方向生成实战题（强依赖 LLM）。

    返回洗牌后的题目列表（含结构化 analysis）；未配置 Key / 无干货 / 解析失败时返回 []。
    """
    if not api_key or not clean_text:
        return []
    clean_text = evidence_text(evidence) if evidence else cleaned_course_context({"cleaned_text": clean_text})
    career_name, focus = career_prompt_params(career_direction)
    system = (llm.PRACTICAL_QUIZ_SYSTEM_PROMPT
              .replace("{career_name}", career_name)
              .replace("{focus_keywords}", focus)
              .replace("{num_q}", str(num_q)))
    user = (f"请基于以下课程干货内容，为【{career_name}】方向生成 {num_q} 道求职实战单选题：\n\n{clean_text}"
            if not label else
            f"【范围】{label}\n请基于以下课程干货内容，为【{career_name}】方向生成 {num_q} 道求职实战单选题：\n\n{clean_text}")
    try:
        # 生成题数越多输出越长，按题目数动态放宽 token 上限（单题约 900 token 预算）
        max_tokens = max(2500, min(900 * num_q, 6000))
        text = llm.call_llm(user, system, api_key, model, temperature=0.4, max_tokens=max_tokens)
        questions = llm.parse_question_json(text)
        if not questions:
            return []
        out = []
        for q in questions[:num_q]:
            q["source"] = f"{label} · AI 实战题" if label else "AI 实战题"
            q["citations"] = verified_citations(q.pop("citation_ids", []), evidence or [])
            q["citation_status"] = ("已核对课程原文" if q["citations"]
                                      else "当前课程原文中未找到可核对依据")
            out.append(shuffle_question(q))
        return out
    except Exception:
        return []


def generate_practical_quiz_api(clean_text, career_direction, num_q=3, item=None, section=None):
    """页面直接调用的实战出题入口：自动读取会话中的 API Key / 模型。"""
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    evidence = course_evidence(item, "", section, limit=8) if item else []
    return generate_practical_quiz(
        clean_text, career_direction, api_key, model,
        num_q=num_q, label="求职实战测评", evidence=evidence,
    )


def ai_gen_questions(units, num_q, api_key, model, career_direction):
    """Tab2 出题：取 1 个课程上下文，一次让 AI 生成 num_q 道题（仅 1~2 次 LLM 调用），
    失败时换下一个单元兜底；全部失败返回空列表（由调用方回退离线题库）。"""
    tried = 0
    for unit in units:
        if tried >= 2:
            break
        kb_name = unit.get("kb_name")
        if not kb_name:
            continue
        tried += 1
        course = KB["courses"].get(kb_name)
        if not course:
            continue
        section = None
        if unit.get("section_id") or unit.get("section_ts") or unit.get("section_title"):
            section = {
                "id": unit.get("section_id"),
                "ts": unit.get("section_ts"),
                "title": unit.get("section_title"),
            }
        cleaned = get_cleaned({**unit, "kb_name": kb_name}, api_key, model)
        if not section and cleaned and cleaned.get("ok") and cleaned.get("cleaned_text"):
            ctx = cleaned_course_context(cleaned)
        else:
            ctx = kb.kb_course_context(course, max_chars=4000, section=section)
        if not ctx:
            continue
        scope_desc = unit.get("module_name", "") + " / " + unit.get("name", "")
        if unit.get("section_title"):
            scope_desc += " / " + unit["section_title"]
        label = f"自测 · {scope_desc}" if scope_desc else "自测"
        try:
            evidence = course_evidence(
                {"name": unit.get("name"), "kb_name": kb_name},
                unit.get("section_title") or unit.get("name") or "",
                section, limit=8,
            )
            qs = generate_practical_quiz(
                ctx, career_direction, api_key, model, num_q=num_q,
                label=label, evidence=evidence,
            )
            if qs:
                return qs
        except Exception:
            pass
    return []


# ================================================================ 8. 题目工具
def opt_labels(q):
    """生成选项字母标签列表（与 options 一一对应）。"""
    return [chr(65 + i) for i in range(len(q.get("options", [])))]


def ans_index(q, label):
    """把用户选中的选项换算为下标；支持选项文本或字母标签，未选/越界返回 None。"""
    if not label:
        return None
    opts = q.get("options", [])
    if label in opts:
        return opts.index(label)
    try:
        return opt_labels(q).index(label)
    except ValueError:
        return None


def build_qa_request(item, question, section=None):
    """构造助教 Prompt 与本地验证过的原文依据。

    section 支持两种形态：章节 dict（含 ts/title/body）或标题字符串。
    """
    course = KB["courses"].get(item.get("kb_name")) or {}
    scope_desc = "整门课程"

    if section and isinstance(section, dict):
        title = section.get("title") or ""
        ctx = kb.kb_course_context(course, max_chars=6000, section=section)
        if ctx:
            scope_desc = f"章节「{title}」"
    elif section and isinstance(section, str):
        ctx = kb.kb_course_context(
            course, max_chars=6000, section={"title": section}
        )
        if ctx:
            scope_desc = f"章节「{section}」"
    else:
        ctx = ""

    if not ctx:
        cleaned = get_cached_cleaned(item, st.session_state.get("llm_model"))
        if cleaned and cleaned.get("cleaned_text"):
            ctx = cleaned_course_context(cleaned, max_chars=6000)
            scope_desc = "整门课程（AI 清洗后的干货）"
        else:
            ctx = kb.kb_course_context(course, max_chars=6000)
            scope_desc = "整门课程"

    history = st.session_state.get("chat_msgs", [])[-6:]
    hist_txt = "\n".join(f"{m['role']}: {m['content']}" for m in history)

    evidence = course_evidence(item, question, section if isinstance(section, dict) else None, limit=4)
    evidence_block = evidence_text(evidence) or "（当前范围没有可用的课程原文依据）"
    user = (
        f"当前课程：《{item.get('name', '')}》\n"
        f"【当前学习范围】{scope_desc}\n\n"
        f"【已验证课程原文依据】\n{evidence_block}\n\n"
        f"【课程导读/整理内容（只能辅助理解，不能作为原文引用）】\n{ctx}\n\n"
        f"【最近对话】\n{hist_txt}\n\n"
        f"用户问题：{question}"
    )
    return llm.ASSISTANT_SYSTEM_PROMPT, user, evidence


def _offline_question_evidence(item, question, section=None):
    """为离线原文题按真实时间戳回填引用；导读题不伪装成原文引用。"""
    if "· 原文" not in str(question.get("source_detail") or question.get("source", "")):
        return []
    match = re.search(r"原文\s+([^\s]+)\s+处", question.get("explain", ""))
    if not match:
        return []
    marker = match.group(1)
    course = KB["courses"].get(item.get("kb_name")) or {}
    for entry in kb.course_original_entries(course):
        if entry["marker"] == marker:
            return [{**entry, "course": item.get("name") or item.get("kb_name") or "",
                     "section": (section or {}).get("title") or "整门课程"}]
    return []


def generate_course_assessment(item, section, clean_text, career_direction,
                               api_key, model, num_q=3):
    """课程页测评的 AI → 课程文字 → 通用题库三级降级链。"""
    questions = []
    if api_key:
        questions = generate_practical_quiz_api(
            clean_text, career_direction, num_q=num_q, item=item, section=section,
        )
        for question in questions:
            question["question_kind"] = "course_ai"
            question["source"] = "AI 课程原文题"

    if not questions and item.get("kb_name"):
        section_filter = None
        if section:
            section_filter = {item["kb_name"]: [section]}
        questions = kb.gen_questions(
            KB, num=num_q, course_names=[item["kb_name"]],
            section_filter=section_filter,
        )
        for question in questions:
            question["question_kind"] = "course_text"
            question["source_detail"] = question.get("source", "")
            question["source"] = ("课程原文题" if "· 原文" in question["source_detail"]
                                  else "课程导读题")
            question["citations"] = _offline_question_evidence(item, question, section)
            question["citation_status"] = (
                "已核对课程原文" if question["citations"]
                else "本题依据课程导读生成，没有对应的原文片段引用"
            )

    if len(questions) < num_q:
        job = CAREER_DIRECTIONS.get(career_direction, {})
        fallback = fallback_questions(job.get("fallback_job", "agent_developer"), num_q - len(questions))
        for question in fallback:
            question["question_kind"] = "general_offline"
            question["source"] = "通用内置题"
            question["citations"] = []
            question["citation_status"] = "本题来自内置通用题库，没有课程原文引用"
        questions.extend(fallback)
    return questions[:num_q]


def build_qa_prompt(item, question, section=None):
    """兼容旧调用：只返回助教 system/user Prompt。"""
    system, user, _ = build_qa_request(item, question, section)
    return system, user
