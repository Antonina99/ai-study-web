# -*- coding: utf-8 -*-
"""
kb.py —— 课程知识库模块（纯标准库实现，不依赖 python-docx）

功能：
1. 扫描「课程原文及导读」文件夹下的 docx（命名规则：课程名_原文 / 课程名_导读）。
2. 用 zipfile + 正则解析 docx 段落文本（无需额外依赖）。
3. 解析导读：提取关键词、全文摘要、章节速览（时间戳+标题+正文）。
4. 解析原文：提取时间戳分段文本。
5. 增量检测：按「文件名 + 大小 + 修改时间」识别新增/变化文件，只解析新增内容。
6. 解析结果缓存在 _knowledge_cache.json，供出题与页面展示使用。
7. 基于知识库离线生成单选题（内容全部来自课程原文与导读，不调用大模型）。
"""

import os
import re
import json
import glob
import random
import zipfile

# 知识库目录（项目根目录下的「课程原文及导读」文件夹；本模块位于 core/ 子目录，故向上两级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(_PROJECT_ROOT, "课程原文及导读")
# 解析缓存文件
CACHE_FILE = os.path.join(_PROJECT_ROOT, "_knowledge_cache.json")

# 时间戳匹配，如 "00:05" / "01:09:23"
TS_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(.*)$")

# 中文句子切分（用于原文长句提取）
SENT_SPLIT_RE = re.compile(r"[。！？!?；;]")

# 题库生成时的选项数
N_OPTIONS = 4


# ============================================================
# 一、docx 解析
# ============================================================

def parse_docx(path):
    """用 zipfile + 正则解析 docx 的段落文本，返回非空段落列表。"""
    paras = []
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.S)
        line = "".join(texts).strip()
        if line:
            paras.append(line)
    return paras


def split_ts_text(paras):
    """把「时间戳 + 文本」交替的段落合并为 [(时间戳, 文本), ...]。

    原文 docx 结构示例：
        ["1、开学典礼_原文", "2026年08月15日 17:10", "00:05", "嘿。", "00:15", "okay. ...", ...]
    返回：[(("00:05"), "嘿。"), (("00:15"), "okay. ..."), ...]
    前两行（标题、日期）由调用方跳过。
    """
    segs = []
    cur_ts = None
    buf = []
    for p in paras:
        m = TS_RE.match(p)
        if m:
            if cur_ts is not None and buf:
                segs.append((cur_ts, "".join(buf)))
            cur_ts = m.group(1) + ":" + m.group(2) + ((":" + m.group(3)) if m.group(3) else "")
            buf = [m.group(4)] if m.group(4) else []
        else:
            buf.append(p)
    if cur_ts is not None and buf:
        segs.append((cur_ts, "".join(buf)))
    return segs


def parse_original(paras):
    """解析原文：返回 {title, segments:[{ts, text}]}。"""
    title = paras[0] if paras else ""
    segs = split_ts_text(paras[2:])  # 跳过标题行与日期行
    return {
        "title": title,
        "segments": [{"ts": ts, "text": text} for ts, text in segs],
    }


def parse_summary(paras):
    """解析导读：返回 {title, keywords:[], summary:str, sections:[{ts,title,body}]}。

    导读 docx 结构示例：
        ["1、开学典礼_导读", "2026年08月15日 17:10",
         "关键词", "直播 开班典礼 ...",
         "全文摘要", "在这次讨论中，……",
         "章节速览",
         "00:00 AI课程开班典礼：技能、课程安排与行业解读", "本次直播活动是……",
         "06:59 AI技术与商业化融合的行业洞察", "本次分享聚焦于……", ...]
    """
    title = paras[0] if paras else ""
    keywords = []
    summary = ""
    sections = []          # [{ts, title, body}]
    mode = None            # "keywords" | "summary" | "sections"
    cur_section = None     # 当前正在拼接的章节
    for p in paras[2:]:    # 跳过标题行与日期行
        if p == "关键词":
            mode = "keywords"
            continue
        if p == "全文摘要":
            mode = "summary"
            continue
        if p == "章节速览":
            mode = "sections"
            continue

        if mode == "keywords":
            # 关键词通常以空格/顿号分隔，也可能带序号
            keywords = [k for k in re.split(r"[\s、,，;；]+", p) if k]
        elif mode == "summary":
            summary += p
        elif mode == "sections":
            m = TS_RE.match(p)
            if m:
                # 新章节：时间戳 + 标题
                if cur_section is not None:
                    sections.append(cur_section)
                cur_section = {
                    "ts": m.group(1) + ":" + m.group(2),
                    "title": m.group(4).strip(),
                    "body": "",
                }
            elif cur_section is not None:
                # 章节正文（可能跨多段）
                cur_section["body"] += p
    if cur_section is not None:
        sections.append(cur_section)

    return {
        "title": title,
        "keywords": keywords,
        "summary": summary,
        "sections": sections,
    }


# ============================================================
# 二、课程名归一化与知识库构建（含增量检测）
# ============================================================

def normalize(name):
    """规范化课程名，用于「大纲课程名」与「docx 文件名课程名」的 1:1 绑定。

    规则：去掉开头序号（如 "1、" / "01、" / "1."）、去掉所有空白、统一括号/冒号为半角、转小写。
    例：normalize("1、开学典礼") == normalize("开学典礼") == "开学典礼"
    """
    if not name:
        return ""
    s = re.sub(r"^\s*\d+\s*[、.．:：\-—]\s*", "", str(name))
    s = re.sub(r"[\s\u3000\u00a0]+", "", s)
    s = s.replace("（", "(").replace("）", ")").replace("：", ":").replace("，", ",")
    return s.lower()


# 口语噪声词表（规则版去噪用；有 API Key 时优先使用 LLM 结构化萃取）
NOISE_WORDS = [
    "那个那个", "那个那个那个", "然后呢", "然后", "就是说呢", "就是说", "也就是说",
    "对吧对", "对吧", "对不对呀", "对不对", "是吧", "是不是啊", "是不是",
    "呃呃", "呃", "嗯嗯", "嗯", "额额", "额", "好吧", "好的好的", "行吧",
    "是吧对吧", "对不对对", "这个这个", "那然后", "我们就是说",
]


def clean_text(text):
    """规则版口语去噪：剔除语气词/口头禅、压缩重复字与标点。

    用于「未配置 API Key」或「LLM 萃取失败」时的离线降级清洗；
    配置 Key 后优先使用 app.py 中的 AI 结构化萃取（extract_structured_knowledge）。
    """
    if not text:
        return ""
    t = str(text)
    for w in NOISE_WORDS:
        t = t.replace(w, "")
    # 连续重复中文单字压缩（如 对对对 → 对），不影响英文/数字 token
    t = re.sub(r"([\u4e00-\u9fff])\1{2,}", r"\1", t)
    # 连续重复标点压缩
    t = re.sub(r"([，。！？；：])\1+", r"\1", t)
    # 空白压成单个空格（保留英文 token 间的空格，如 "Function Calling"）
    t = re.sub(r"\s+", " ", t)
    # 中文标点两侧去掉空格
    t = re.sub(r"\s*([，。！？；：、])\s*", r"\1", t)
    t = re.sub(r"[，。]{2,}", "。", t)
    t = re.sub(r"^[，。；：、,;: ]+", "", t)
    return t.strip()


def _course_key(fname):
    """从文件名解析课程名与类型。

    规则：文件名形如「1、开学典礼_原文.docx」→ (课程名="1、开学典礼", 类型="原文")。
    兼容不以下划线分隔、文件名带 .docx 后缀等情况。
    """
    base = fname[:-5] if fname.lower().endswith(".docx") else fname
    for suffix, kind in (("_原文", "原文"), ("_导读", "导读"),
                         ("原文", "原文"), ("导读", "导读")):
        if base.endswith(suffix):
            return base[: -len(suffix)].strip(), kind
    return None, None


def _file_signature(path):
    """文件指纹：大小 + 修改时间，用于增量检测。"""
    st = os.stat(path)
    return "%d_%d" % (st.st_size, int(st.st_mtime))


def build_kb():
    """扫描知识库目录，增量解析 docx。

    返回: (kb, newly_added)
      kb: {"courses": {课程名: {"original": {...}, "summary": {...}}}, "file_signs": {...}}
      newly_added: 本次新增/变化的课程名列表
    """
    kb = {"courses": {}, "file_signs": {}}
    newly_added = []

    # 读取已有缓存
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                old = json.load(f)
            kb["courses"] = old.get("courses", {})
            kb["file_signs"] = old.get("file_signs", {})
        except Exception:
            pass

    paths = sorted(glob.glob(os.path.join(KB_DIR, "*.docx")))
    for path in paths:
        fname = os.path.basename(path)
        name, kind = _course_key(fname)
        if not name or not kind:
            continue
        sig = _file_signature(path)
        if kb["file_signs"].get(fname) == sig:
            continue  # 未变化，跳过

        paras = parse_docx(path)
        if not paras:
            continue
        course = kb["courses"].setdefault(name, {"original": None, "summary": None})
        if kind == "原文":
            course["original"] = parse_original(paras)
        else:
            course["summary"] = parse_summary(paras)
        kb["file_signs"][fname] = sig
        if name not in newly_added:
            newly_added.append(name)

    # 课程名排序
    kb["courses"] = {k: kb["courses"][k] for k in sorted(kb["courses"])}

    # 写回缓存（解析失败/目录不存在时不写，保留旧缓存）
    if os.path.isdir(KB_DIR):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"courses": kb["courses"], "file_signs": kb["file_signs"]},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return kb, newly_added


def has_file_changes():
    """轻量检测：目录下 docx 是否有新增/修改（不解析、不写缓存），供运行时自动刷新用。"""
    if not os.path.isdir(KB_DIR):
        return False
    old_signs = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                old_signs = json.load(f).get("file_signs", {}) or {}
        except Exception:
            pass
    current_signs = {}
    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.docx"))):
        fname = os.path.basename(path)
        name, kind = _course_key(fname)
        if not name or not kind:
            continue
        try:
            current_signs[fname] = _file_signature(path)
        except OSError:
            continue
    return current_signs != old_signs


def get_kb():
    """读取缓存中的知识库（不重新扫描）。页面加载时用 build_kb 即可。"""
    if not os.path.exists(CACHE_FILE):
        return {"courses": {}, "file_signs": {}}
    with open(CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 三、基于知识库出题（离线规则生成，不调用大模型）
# ============================================================

def _extract_key_terms(text):
    """从文本中提取「值得挖空」的关键词：英文/数字 token、含冒号的术语、书名号内容。"""
    terms = []
    terms += re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{1,30}", text)          # 英文/数字
    terms += re.findall(r"[^\s，。；、,.;:：（）()]{2,12}：", text)          # xx：
    terms += re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,10}（[^）]{1,12}）", text)  # 中文（英文）
    terms = [t.rstrip("：") for t in terms]
    # 去重、去太短的
    seen, out = set(), []
    for t in terms:
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _make_question(kind, q, correct, wrongs, explain, source):
    """构造单道选择题。correct 为正确选项文本，wrongs 为干扰项列表。"""
    options = [correct] + list(wrongs)[: N_OPTIONS - 1]
    random.shuffle(options)
    return {
        "q": q,
        "options": options,
        "answer": options.index(correct),
        "explain": explain,
        "source": source,
    }


def _all_terms(courses):
    """收集知识库中所有可用于出题的关键词池（来自导读关键词 + 章节标题）。"""
    pool = []
    for name, c in courses.items():
        sm = c.get("summary") or {}
        pool += sm.get("keywords", [])
        for s in sm.get("sections", []):
            t = s.get("title", "")
            # 标题拆词：去掉时间戳，按冒号/空格/顿号拆
            for seg in re.split(r"[:：\s、,，。；;]+", t):
                if len(seg) >= 2 and seg not in pool:
                    pool.append(seg)
    return [x for x in pool if x.strip()]


def gen_questions(kb, num=3, focus=None, course_names=None, section_filter=None):
    """基于知识库生成 num 道单选题。

    题型1（章节理解）：给出导读章节正文（已口语去噪），选择对应的章节标题。
    题型2（关键词记忆）：给出课程导读关键词，选属于该课的关键词。
    题型3（原文填空）：从原文中抽取含关键词的长句（已口语去噪），将关键词挖空，选项来自术语池。

    focus: 岗位重点关键词列表，命中关键词的课程优先出题。
    course_names: 可选，限定出题范围。可传大纲课程名或知识库课程名，内部按 normalize 自动匹配绑定。
    section_filter: 可选 dict，{知识库课程名: [ts, ...]}，仅从指定章节（分钟级时间戳匹配）出题。
    题目内容全部来自课程原文与导读；不足 num 时返回实际可生成的题数。
    """
    courses = kb.get("courses", {})
    if not courses:
        return []

    # 按出题范围过滤课程（course_names 中的大纲课程名自动绑定到知识库课程名）
    if course_names:
        names = []
        for n in course_names:
            if not n:
                continue
            norm = normalize(n)
            hit = None
            for real in courses:
                if norm and normalize(real) == norm:
                    hit = real
                    break
            if hit is None:
                for real in courses:
                    rn = normalize(real)
                    if rn and (rn in norm or norm in rn):
                        hit = real
                        break
            if hit and hit not in names:
                names.append(hit)
    else:
        names = list(courses.keys())

    # 预筛：优先选中与 focus 相关的课程
    if focus:
        def _score(name):
            text = json.dumps(courses[name], ensure_ascii=False)
            return sum(1 for k in focus if k and k.lower() in text.lower())
        names = sorted(names, key=_score, reverse=True)

    questions = []
    term_pool = [t for t in _all_terms(courses) if len(t) >= 2]

    # ---- 题型 1：章节标题匹配（支持按章节精准过滤 + 口语清洗）----
    sec_list = []
    for name in names:
        sm = courses[name].get("summary") or {}
        for s in sm.get("sections", []):
            if not (s.get("title") and s.get("body")):
                continue
            # 章节级出题范围过滤：命中指定时间戳（分钟级匹配）
            if section_filter and name in section_filter:
                if not any(s.get("ts", "")[:5] == ts[:5] for ts in section_filter[name]):
                    continue
            sec_list.append((name, s))
    if len(sec_list) >= N_OPTIONS and len(questions) < num:
        random.shuffle(sec_list)
        for name, s in sec_list:
            if len(questions) >= num:
                break
            body = clean_text(s["body"])
            if len(body) < 15:
                continue
            correct = s["title"]
            wrongs = [x[1]["title"] for x in sec_list if x[1]["title"] != correct]
            wrongs = list(dict.fromkeys(wrongs))  # 去重保持顺序
            if len(wrongs) < N_OPTIONS - 1:
                # 干扰项不足时，用其他课程的关键词补位
                extra = [t for t in term_pool if t != correct and t not in wrongs]
                wrongs += extra
            if len(wrongs) < N_OPTIONS - 1:
                continue
            random.shuffle(wrongs)
            preview = body if len(body) <= 100 else body[:100] + "…"
            questions.append(_make_question(
                "章节理解",
                f"（{name}）下面这段导读内容，对应的是哪个章节？\n\n“{preview}”",
                correct, wrongs[:N_OPTIONS - 1],
                f"这段内容出自课程《{name}》的章节「{correct}」（{s['ts']}）。完整导读：{body}",
                f"{name} · 导读",
            ))

    # ---- 题型 2：关键词匹配 ----
    kw_list = []
    for name in names:
        sm = courses[name].get("summary") or {}
        if len(sm.get("keywords", [])) >= 2:
            kw_list.append((name, sm["keywords"]))
    if len(questions) < num and kw_list:
        random.shuffle(kw_list)
        for name, kws in kw_list:
            if len(questions) >= num:
                break
            # 至少需要 1 正确 + 3 干扰
            others = [t for t in term_pool if t not in kws]
            if len(others) < N_OPTIONS - 1:
                continue
            correct = random.choice(kws)
            random.shuffle(others)
            questions.append(_make_question(
                "关键词记忆",
                f"（{name}）以下哪个是这份课程导读中提炼的关键词？",
                correct, others[:N_OPTIONS - 1],
                f"《{name}》导读的关键词包括：{'、'.join(kws)}。",
                f"{name} · 导读",
            ))

    # ---- 题型 3：原文挖空 ----
    if len(questions) < num and term_pool:
        candidates = []
        for name in names:
            org = courses[name].get("original")
            if not org:
                continue
            for seg in org.get("segments", []):
                text = clean_text(seg.get("text", ""))
                if section_filter and name in section_filter:
                    if not any(seg.get("ts", "")[:5] == ts[:5] for ts in section_filter[name]):
                        continue
                for sent in SENT_SPLIT_RE.split(text):
                    sent = sent.strip()
                    if len(sent) < 20 or len(sent) > 120:
                        continue
                    for term in _extract_key_terms(sent):
                        if term in sent:
                            candidates.append((name, seg["ts"], sent, term))
                            break
        random.shuffle(candidates)
        used = set()
        for name, ts, sent, term in candidates:
            if len(questions) >= num:
                break
            if (sent, term) in used:
                continue
            used.add((sent, term))
            qtext = sent.replace(term, "____", 1)
            if qtext == sent or "____" not in qtext:
                continue
            wrongs = []
            for t in term_pool:
                if len(wrongs) >= N_OPTIONS - 1:
                    break
                if t != term and t != qtext and t not in wrongs:
                    wrongs.append(t)
            if len(wrongs) < N_OPTIONS - 1:
                continue
            questions.append(_make_question(
                "原文填空",
                f"（{name}）根据课程原文，补全这句话：\n\n“{qtext}”",
                term, wrongs,
                f"这句话出自《{name}》原文 {ts} 处，完整原句为：{sent}",
                f"{name} · 原文",
            ))

    return questions[:num]


# ============================================================
# 四、LLM 上下文生成（供 app.py 的 AI 出题 / AI 助教使用）
# ============================================================

def kb_course_context(course, max_chars=4000, section_ts=None):
    """把一门课的知识库内容拼成适合送入 LLM 的上下文文本。

    优先导读（关键词 / 全文摘要 / 章节速览），再附原文摘录；整体按 max_chars 裁剪。

    section_ts: 可选，指定只提取该章节（分钟级时间戳匹配）的导读正文与对应时段原文，
    用于「按章节精准定向出题」。
    """
    parts = []
    sm = course.get("summary") or {}
    org = course.get("original") or {}

    if section_ts:
        for s in sm.get("sections", []):
            if s.get("ts", "")[:5] == section_ts[:5]:
                parts.append("【章节 %s】%s\n%s" % (s.get("ts", ""), s.get("title", ""), clean_text(s.get("body", "") or "")))
        if org.get("segments"):
            matched = [seg for seg in org["segments"] if seg.get("ts", "")[:5] == section_ts[:5]]
            if matched:
                parts.append("【原文摘录】\n" + "\n".join(
                    "[%s] %s" % (seg.get("ts", ""), clean_text(seg.get("text", ""))) for seg in matched))
        text = "\n\n".join(p for p in parts if p)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…（内容过长已截断）"
        return text

    if sm.get("keywords"):
        parts.append("【关键词】" + "、".join(sm["keywords"]))
    if sm.get("summary"):
        parts.append("【全文摘要】" + sm["summary"])
    if sm.get("sections"):
        secs = []
        for s in sm["sections"]:
            secs.append("【章节 %s】%s\n%s" % (s.get("ts", ""), s.get("title", ""), clean_text(s.get("body", "") or "")))
        parts.append("【章节速览】\n" + "\n\n".join(secs))

    if org.get("segments"):
        joined = "\n".join("[%s] %s" % (s.get("ts", ""), clean_text(s.get("text", ""))) for s in org["segments"])
        parts.append("【原文摘录】\n" + joined)

    text = "\n\n".join(p for p in parts if p)
    if len(text) > max_chars:
        head = max_chars * 3 // 4
        tail = max_chars - head - 1
        text = text[:head] + "\n…（内容过长已截断）\n" + text[-tail:]
    return text
