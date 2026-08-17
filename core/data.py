# -*- coding: utf-8 -*-
"""
core/data.py —— 数据与业务核心层

职责：
1. 静态配置：CAREER_DIRECTIONS（5 大求职方向）、COURSE_MODULES/MODULES（5 大核心模块课程大纲）、QUESTIONS（离线题库）。
2. 课程绑定索引 / 知识库加载 / 关键词加权。
3. 课程资产组装：get_clean_course_data（关键词/摘要/思维导图/干货/考点，含 session 缓存与离线降级）。
4. 出题：AI 实战出题（focus 强约束注入）、逐单元自测、离线兜底（选项洗牌）。
5. 题目工具：选项标签/索引换算、AI 助教 Prompt 构造。
"""

import random
import re

import streamlit as st

from core import kb, llm

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
        "name": "AI 架构 / Infra / 运维工程师",
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
        "name": "Prompt 工程师 / AI 提效泛职场",
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

    cleaned = str(data.get("cleaned_text") or data.get("clean_text") or "").strip()
    summary = _lst(data.get("summary_points"), 5)
    interview = _lst(data.get("interview_points"), 5)
    keywords = _lst(data.get("keywords"), 8)
    return {
        "keywords": keywords,
        "summary_points": summary,
        "mindmap": str(data.get("mindmap") or "").strip(),
        "interview_points": interview,
        "cleaned_text": cleaned,
        "ok": bool(cleaned or summary or interview),
    }


def get_cleaned(item, api_key, model):
    """AI 结构化萃取（带 session 缓存）：返回含 ok 标志的 dict；无 Key/无课程/失败时返回 None。"""
    cache = st.session_state.setdefault("cleaned_cache", {})
    # 优先用 id；出题链路传入的单元没有 id，退化用 kb_name 做缓存 key，避免跨课程串用同一份缓存
    cid = item.get("id") or item.get("kb_name")
    if cache.get(cid):
        return cache[cid]
    course = KB["courses"].get(item.get("kb_name"))
    if not api_key or not course:
        return None
    prompt = kb.kb_course_context(course, max_chars=8000)
    try:
        text = llm.call_llm(prompt, llm.EXTRACT_SYSTEM_PROMPT, api_key, model,
                            temperature=0.2, max_tokens=2000)
        cleaned = _parse_extract(text)
        if not cleaned:
            return None
        cache[cid] = cleaned
        return cleaned
    except Exception:
        return None


def _rule_cleaned_doc(course, max_chars=1600):
    """离线规则版干货正文：导读摘要 + 各章节正文拼接（无 Key 时兜底）。"""
    parts = []
    sm = course.get("summary") or {}
    summary_text = (sm.get("summary") or "").strip()
    if summary_text:
        parts.append(summary_text)
    for sec in sm.get("sections", []):
        body = (sec.get("body") or "").strip()
        if body:
            parts.append(body)
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text


def _rule_mindmap(course, career_direction):
    """离线规则版思维导图：关键词/章节/求职方向重点骨架。"""
    sm = course.get("summary") or {}
    career_name = CAREER_DIRECTIONS.get(career_direction, {}).get("name", career_direction)
    lines = ["mindmap", f"root(({career_name}))"]
    seen = set()
    for kw in sm.get("keywords", [])[:6]:
        if kw not in seen:
            lines.append(f"    {kw}")
            seen.add(kw)
    for kw in CAREER_DIRECTIONS.get(career_direction, {}).get("focus", [])[:4]:
        if kw not in seen:
            lines.append(f"    {kw}")
            seen.add(kw)
    for sec in sm.get("sections", [])[:8]:
        title = (sec.get("title") or "").strip()
        if title and title not in seen:
            lines.append(f"    {title}")
            seen.add(title)
    return "\n".join(lines)


def generate_learning_mindmap(clean_text, career_direction, course=None, api_key=None, model=None):
    """求职方向定制思维导图：LLM 优先（focus 强约束注入），失败回退离线规则版。"""
    api_key = api_key or st.session_state.get("api_key", "").strip()
    model = model or st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    career_name, focus = career_prompt_params(career_direction)

    if api_key and clean_text:
        try:
            system = (llm.MINDMAP_SYSTEM_PROMPT
                      .replace("{career_name}", career_name)
                      .replace("{focus_keywords}", focus))
            code = llm.call_llm(clean_text, system, api_key, model, temperature=0.3, max_tokens=1600)
            code = llm.sanitize_mermaid(code)
            if code.startswith("mindmap"):
                return code
        except Exception:
            pass
    return _rule_mindmap(course or {}, career_direction)


def get_clean_course_data(item, career_direction, api_key=None, model=None):
    """组装一门课程的「关键资产」数据包：keywords / summary / mermaid_code / clean_text / interview_points。

    - api_key / model 可省略：省略时自动从会话读取；
    - AI 优先，未配置 Key 或萃取失败时降级为离线规则版；思维导图带 session 缓存。
    """
    api_key = api_key or st.session_state.get("api_key", "").strip()
    model = model or st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    course = KB["courses"].get(item.get("kb_name")) or {}
    sm = course.get("summary") or {}
    cleaned = get_cleaned(item, api_key, model)
    ok = bool(cleaned and cleaned.get("ok"))

    summary = "、".join(cleaned["summary_points"]) if ok and cleaned["summary_points"] else (sm.get("summary") or "（暂无摘要）")
    keywords = cleaned["keywords"] if ok and cleaned["keywords"] else (sm.get("keywords") or [])
    interview_points = cleaned["interview_points"] if ok else []
    clean_text = cleaned["cleaned_text"] if ok and cleaned["cleaned_text"] else _rule_cleaned_doc(course)

    mkey = f"{item['id']}|{career_direction}"
    mermaid_code = st.session_state.mindmap_cache.get(mkey)
    if not mermaid_code:
        mermaid_code = generate_learning_mindmap(clean_text, career_direction, course, api_key, model)
        st.session_state.mindmap_cache[mkey] = mermaid_code

    return {
        "keywords": keywords,
        "summary": summary,
        "mermaid_code": mermaid_code,
        "clean_text": clean_text,
        "interview_points": interview_points,
    }


# ================================================================ 7. 出题
def generate_practical_quiz(clean_text, career_direction, api_key, model, num_q=3, label=""):
    """基于课程干货 + 求职方向生成实战题（强依赖 LLM）。

    返回洗牌后的题目列表（含结构化 analysis）；未配置 Key / 无干货 / 解析失败时返回 []。
    """
    if not api_key or not clean_text:
        return []
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
            out.append(shuffle_question(q))
        return out
    except Exception:
        return []


def generate_practical_quiz_api(clean_text, career_direction, num_q=3):
    """页面直接调用的实战出题入口：自动读取会话中的 API Key / 模型。"""
    api_key = st.session_state.get("api_key", "").strip()
    model = st.session_state.get("llm_model", llm.DEFAULT_MODEL)
    return generate_practical_quiz(
        clean_text, career_direction, api_key, model,
        num_q=num_q, label="求职实战测评",
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
        section_ts = unit.get("section_ts")
        cleaned = get_cleaned({**unit, "kb_name": kb_name}, api_key, model)
        if cleaned and cleaned.get("ok") and cleaned.get("cleaned_text"):
            ctx = cleaned["cleaned_text"]
        else:
            ctx = kb.kb_course_context(course, max_chars=4000, section_ts=section_ts)
        if not ctx:
            continue
        scope_desc = unit.get("module_name", "") + " / " + unit.get("name", "")
        if unit.get("title"):
            scope_desc += " / " + unit["title"]
        label = f"自测 · {scope_desc}" if scope_desc else "自测"
        try:
            qs = generate_practical_quiz(ctx, career_direction, api_key, model, num_q=num_q, label=label)
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


def build_qa_prompt(item, question, section=None):
    """构造 AI 助教的 (system, user) Prompt（含最近对话历史与章节/整课上下文）。

    section 支持两种形态：章节 dict（含 ts/title/body）或标题字符串。
    """
    course = KB["courses"].get(item.get("kb_name")) or {}
    scope_desc = "整门课程"

    if section and isinstance(section, dict):
        body = section.get("body") or ""
        title = section.get("title") or ""
        if len(body) > 1200:
            body = body[:1200] + "…"
        ctx = body or ""
        if ctx:
            scope_desc = f"章节「{title}」"
    elif section and isinstance(section, str):
        ctx = ""
        sm = course.get("summary") or {}
        for s in sm.get("sections", []):
            if s.get("title") == section:
                body = s.get("body") or ""
                if len(body) > 1200:
                    body = body[:1200] + "…"
                ctx = body
                scope_desc = f"章节「{section}」"
                break
    else:
        ctx = ""

    if not ctx:
        cleaned = st.session_state.get("cleaned_cache", {}).get(item.get("id"))
        if cleaned and cleaned.get("cleaned_text"):
            ctx = cleaned["cleaned_text"]
            scope_desc = "整门课程（AI 清洗后的干货）"
        else:
            ctx = kb.kb_course_context(course, max_chars=6000)
            scope_desc = "整门课程"

    history = st.session_state.get("chat_msgs", [])[-6:]
    hist_txt = "\n".join(f"{m['role']}: {m['content']}" for m in history)

    user = (
        f"当前课程：《{item.get('name', '')}》\n"
        f"【当前学习范围】{scope_desc}\n\n"
        f"【课程内容参考】\n{ctx}\n\n"
        f"【最近对话】\n{hist_txt}\n\n"
        f"用户问题：{question}"
    )
    return llm.ASSISTANT_SYSTEM_PROMPT, user
