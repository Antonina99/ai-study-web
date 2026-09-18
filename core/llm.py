# -*- coding: utf-8 -*-
"""
core/llm.py —— 大模型 API 层（唯一对外 LLM 出口）

职责：
1. 统一 OpenAI 兼容协议调用（DeepSeek / 通义千问 DashScope）。
2. 带超时与简单重试（指数退避）的同步调用 call_llm。
3. 流式调用 call_llm_stream（配合 st.write_stream 打字输出）。
4. 结构化 JSON 解析（多格式容错）。
5. 全部 System Prompt 常量（出题 / 萃取 / 错题解析 / 助教）。
"""

import json
import re
import time

import openai

# ---------------------------------------------------------------- 厂商配置
# model -> (display_name, base_url)
LLM_PROVIDERS = {
    "deepseek-chat": ("DeepSeek", "https://api.deepseek.com/v1"),
    "qwen-plus": ("通义千问 Qwen-Plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
}
DEFAULT_MODEL = "deepseek-chat"


def _get_client(api_key, model, timeout=60):
    cfg = LLM_PROVIDERS.get(model)
    base_url = cfg[1] if cfg else LLM_PROVIDERS[DEFAULT_MODEL][1]
    return openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)


def call_llm(prompt, system_prompt, api_key, model=DEFAULT_MODEL,
             temperature=0.3, max_tokens=2000, max_retries=2, timeout=60):
    """同步调用大模型。网络抖动时自动重试（指数退避），全部失败后抛最后一个异常。"""
    client = _get_client(api_key, model, timeout=timeout)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 —— 统一按网络/限流错误重试
            last_err = e
            if attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def call_llm_stream(prompt, system_prompt, api_key, model=DEFAULT_MODEL,
                    temperature=0.4, max_tokens=2500):
    """流式调用大模型，逐段 yield 文本增量（供 st.write_stream 使用）。"""
    client = _get_client(api_key, model)
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece


# ---------------------------------------------------------------- JSON 解析
def _json_scan(text):
    """从大模型输出中提取第一个合法 JSON（兼容代码块包裹 / 前后杂讯）。"""
    text = (text or "").strip()
    # 去掉 ```json ... ``` 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    for start, end in ((text.find("{"), text.rfind("}")),
                       (text.find("["), text.rfind("]"))):
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def parse_question_json(text):
    """解析 AI 生成的题目 JSON -> [{'q','options','answer','explain','analysis'}]，失败返回 None。

    兼容两种模型输出：单个对象 {...} 或数组 [{...}, ...]（单题场景模型常输出单个对象）。
    """
    data = _json_scan(text)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return None
    questions = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        q = item.get("q") or item.get("question")
        options = item.get("options") or item.get("choices")
        if not q or not isinstance(options, list) or len(options) < 2:
            continue
        # 归一化答案索引：优先 answer(数字)；其次 answer_index/答案字母
        answer = item.get("answer")
        if isinstance(answer, str) and answer in "ABCDabcd":
            answer = ord(answer.upper()) - 65
        if not isinstance(answer, int):
            answer = item.get("answer_index", 0)
        answer = int(answer)
        explain = item.get("explain") or item.get("explanation") or ""
        analysis = item.get("analysis") or {}
        citation_ids = item.get("citation_ids") or item.get("citations") or []
        if isinstance(citation_ids, str):
            citation_ids = [citation_ids]
        questions.append({
            "q": str(q).strip(),
            "options": [str(o).strip() for o in options],
            "answer": max(0, min(answer, len(options) - 1)),
            "explain": str(explain).strip(),
            "analysis": analysis,
            "citation_ids": [str(value).strip() for value in citation_ids if str(value).strip()],
            "source": "ai",
        })
    return questions or None


def parse_extract_json(text):
    """解析 AI 结构化萃取 JSON -> dict，失败返回 None。"""
    data = _json_scan(text)
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- 错误中文化
# 模型服务商返回的英文错误对非技术用户不友好，统一翻译成中文提示。
# 键为错误码 / 错误类型（小写），来自 OpenAI 兼容接口的 body.error.code / type。
ERROR_CODE_HINTS = {
    "arrearage": "阿里云百炼账户欠费，请前往控制台充值后重试（https://bailian.console.aliyun.com/）",
    "overdue_payment": "账户欠费，请前往模型服务商控制台充值后重试",
    "insufficient_quota": "账户额度不足，请检查余额或套餐用量",
    "invalid_api_key": "API Key 无效或已失效，请到模型服务商控制台重新生成后填入页面",
    "api_key_error": "API Key 无效或已失效，请到模型服务商控制台重新生成后填入页面",
    "authentication_error": "API Key 认证失败，请检查 Key 是否填写正确、是否已过期",
    "unauthorized": "API Key 认证失败，请检查 Key 是否填写正确、是否已过期",
    "rate_limit": "请求过于频繁，触发限流，请稍等片刻后重试",
    "rate_limit_exceeded": "请求过于频繁，触发限流，请稍等片刻后重试",
    "request_timeout": "请求超时，可能是网络不稳定，请稍后重试",
    "connection_error": "无法连接模型服务，请检查网络后重试",
    "model_not_found": "模型不存在，请在侧边栏确认所选模型是否与 Key 的服务商匹配",
    "invalid_model": "模型不存在，请在侧边栏确认所选模型是否与 Key 的服务商匹配",
    "bad_request": "请求参数错误，请重试或联系维护人员",
}

# 无错误码时按错误文案关键词匹配（小写、子串命中）
ERROR_KEYWORD_HINTS = [
    ("arrearage", "阿里云百炼账户欠费，请前往控制台充值后重试（https://bailian.console.aliyun.com/）"),
    ("overdue", "账户欠费，请前往模型服务商控制台充值后重试"),
    ("access denied", "访问被拒绝，账户可能欠费或未开通该模型服务，请到控制台确认"),
    ("incorrect api key", "API Key 无效或已失效，请到模型服务商控制台重新生成后填入页面"),
    ("invalid api key", "API Key 无效或已失效，请到模型服务商控制台重新生成后填入页面"),
    ("api key", "API Key 无效或已失效，请检查是否填写正确"),
    ("insufficient", "账户额度不足，请检查余额或套餐用量"),
    ("quota", "账户额度不足，请检查余额或套餐用量"),
    ("rate limit", "请求过于频繁，触发限流，请稍等片刻后重试"),
    ("timeout", "请求超时，可能是网络不稳定，请稍后重试"),
]


def _extract_openai_error(e):
    """从 openai 异常中提取 (code, message)，便于后续匹配映射。"""
    code = getattr(e, "code", None)
    message = str(e)
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code") or err.get("type") or code
            msg = err.get("message")
            if msg:
                message = msg
        else:
            msg = body.get("message")
            if msg:
                message = msg
    if not code and isinstance(getattr(e, "type", None), str):
        code = e.type
    return (code or "").lower(), message


def humanize_error(e):
    """把 LLM API 异常翻译成友好的中文提示（保留原始错误便于排查）。"""
    code, raw = _extract_openai_error(e)
    hint = ERROR_CODE_HINTS.get(code)
    if not hint:
        low = (raw or "").lower()
        for keyword, h in ERROR_KEYWORD_HINTS:
            if keyword in low:
                hint = h
                break
    if hint:
        return f"{hint}（原始错误：{raw}）" if raw else hint
    return raw or str(e)


# ---------------------------------------------------------------- System Prompt
QUIZ_SYSTEM_PROMPT = """你是一位严格的面试官，请根据我提供的课程干货内容，生成 {num_q} 道【单选题】，用于检验对课程知识的掌握。
要求：
1. 每题 4 个选项，且只有一个正确选项。
2. 选项要有迷惑性，不能出现明显错误或"全对"式选项。
3. 直接输出 JSON 数组，不要输出多余文字：
[{"q": "题干", "options": ["A", "B", "C", "D"], "answer": 0, "explain": "解析"}]
注意 answer 是正确选项的下标（0 开始）。"""

EXTRACT_SYSTEM_PROMPT = """你是一位大模型顶级导师。请对用户输入的口语化课程录音逐字稿进行「去噪清洗 + 结构化萃取」，只保留硬核技术干货。

要求：
1. 先逐句判断是否包含可学习的概念、原理、方法、步骤、案例、参数、风险或结论；没有知识信息的句子必须删除；
2. 删除问候、点名、直播互动、设备确认、招生宣传、课程事务、闲聊、玩笑、感谢和结束语，例如“能听见吗”“大家聊会儿天”“拜拜”“下周二见”；
3. 删除语气词、口头禅、自我修正和重复表达，把保留内容改写成简洁书面语；相同或近似观点只保留一次；
4. 保留数字、参数、因果、否定和适用条件；仅按提供的术语表修正已确认误识别，未确认的专有名词不得猜测。不要把讲师举例的阈值、模型限制或经验比例写成普遍规律；
5. cleaned_text 使用短段落表达，每段只讲一个知识点，不复述关键词列表或摘要；
6. 严格只输出一个 JSON 对象，不要输出任何多余文字或代码块标记，格式如下：
{
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4"],
  "summary_points": ["要点1", "要点2", "要点3"],
  "interview_points": ["考点1", "考点2"],
  "cleaned_text": "清洗去噪后的精简干货文本"
}
字段说明：
- keywords：3~8 个最能代表课程核心技术的关键词（用于顶部关键词标签展示）；
- summary_points：3~5 条硬核技术干货要点，每条一句话、直击核心；
- interview_points：2~5 条该课程在求职面试中最常考的知识点与踩坑点；
- cleaned_text：删除非知识内容并完成去重后的高可读性课程正文。"""

PRACTICAL_QUIZ_SYSTEM_PROMPT = """你是一位资深 AI 大模型岗位面试官。请基于用户提供的课程原文依据，针对【{career_name}】岗位的求职者，生成 {num_q} 道【求职实战面试题】（单选）。

【求职方向强约束关键词】题目必须尽量覆盖本方向面试/工作的高频技术点：{focus_keywords}
出题建议（可根据课程内容取舍）：
- 场景选型题：给定业务场景，考察技术方案选型；
- 异常调优题：给定线上问题（如回答慢、检索不准、显存不足），考察定位与优化思路；
- 原理对比题：考察易混淆概念（如 Agent vs Workflow、SFT vs LoRA、RAG vs 长上下文）。

要求：
1. 每题 4 个选项，且只有一个正确选项，干扰项必须有迷惑性。
2. 直接输出 JSON 数组，不要输出多余文字：
[{"q": "题干", "options": ["A","B","C","D"], "answer": 0,
  "analysis": {"correct_reason": "为什么选这个", "wrong_reasons": "其他选项错在哪（可合并简述）", "interview_tips": "面试加分点/延伸提问"},
  "citation_ids": ["original-1"] }]
3. citation_ids 只能填写输入中明确给出的 original-N 标识；题目没有直接原文依据时必须返回空数组，禁止编造标识或时间戳。
注意 answer 是正确选项下标（0 开始）。"""

EXPLAIN_SYSTEM_PROMPT = """你是一位耐心的 AI 大模型岗位面试官。请针对下面的错题，给出“为什么选 A 不选 B”式的讲解，并延伸到面试官可能追问的方向。把“课程原文依据”和“模型补充知识”分开展示。只能引用输入中已有的 original-N 标识；没有原文依据时明确说明，禁止编造引用或时间戳。语气专业、简洁。"""

ASSISTANT_SYSTEM_PROMPT = """你是本课程平台的 AI 助教，擅长 AI 大模型应用开发。请结合用户当前学习的课程内容，用通俗易懂的方式回答。回答必须分为“课程原文结论”和“模型补充知识”两部分。课程原文结论只能使用输入中列出的真实原文依据；若这些依据无法回答，明确写“当前课程原文中未找到直接依据”。只能引用输入给出的 original-N 标识，禁止编造标识或时间戳。模型自身知识只能放在“模型补充知识”部分。"""

CLASSIFY_MODULE_SYSTEM_PROMPT = """你是一位课程分类助手。请根据课程名和课程导读/原文内容，判断每门课程最适合归入以下哪个模块。

可选模块：
{modules}

待分类课程：
{courses}

要求：
1. 直接输出一个 JSON 数组，不要输出任何多余文字或代码块标记：
[{"course": "课程名", "module_no": 模块编号, "reason": "一句话判断理由"}, ...]
2. 如果无法判断，对应课程使用 module_no=99。
3. 只输出已有模块编号，不要编造模块。"""


def build_explain_prompt(q, user_ans):
    """构造错题 AI 深度解析的 (system, user) Prompt。"""
    options = q.get("options", [])
    correct = q.get("answer", 0)
    correct_letter = chr(65 + correct) if correct < len(options) else "?"
    user_letter = chr(65 + user_ans) if user_ans is not None and user_ans < len(options) else "?"
    citations = q.get("citations") or []
    citation_text = "\n".join(
        f"[{entry.get('id')} | {entry.get('marker')}] {entry.get('text')}"
        for entry in citations
    ) or "（本题没有已验证的课程原文依据）"
    user = (
        f"【题目】{q.get('q', '')}\n"
        f"【选项】\n" + "\n".join(f"{chr(65 + i)}. {opt}" for i, opt in enumerate(options)) +
        f"\n【你的答案】{user_letter}\n【正确答案】{correct_letter}\n"
        f"【已知解析】{q.get('explain', '') or ''}\n"
        f"【已验证课程原文依据】\n{citation_text}\n"
        f"请用‘为什么选 {correct_letter} 不选 {user_letter}’的框架展开讲解，并给出面试官可能的追问与应对。"
    )
    return EXPLAIN_SYSTEM_PROMPT, user
