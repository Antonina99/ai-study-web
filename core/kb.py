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
from difflib import SequenceMatcher

# 知识库目录（项目根目录下的「课程原文及导读」文件夹；本模块位于 core/ 子目录，故向上两级）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(_PROJECT_ROOT, "课程原文及导读")
# 解析缓存文件
CACHE_FILE = os.path.join(_PROJECT_ROOT, "_knowledge_cache.json")
# 解析规则版本；升级后自动忽略旧文件指纹并重新解析全部源文件。
CACHE_VERSION = 3

# 时间戳匹配，如 "00:05" / "01:09:23"
TS_RE = re.compile(r"^\s*(\d{1,2})[:：](\d{2})(?:[:：](\d{2}))?\s*(.*)$")
# 常见音视频转写前缀，如「发言人 00:01」「说话人 1 00:01」。
SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(?:发言人|说话人|讲师)(?:\s+[^\s:：]+)?\s+(?=\d{1,2}[:：]\d{2})"
)
# 转写文件第二行常见的日期，用于区分元数据与无时间戳正文。
DATE_LINE_RE = re.compile(r"^\s*\d{4}(?:年|[-/.])\d{1,2}(?:月|[-/.])\d{1,2}")

# 中文句子切分（用于原文长句提取）
SENT_SPLIT_RE = re.compile(r"[。！？!?；;]")

# 题库生成时的选项数
N_OPTIONS = 4


# ============================================================
# 一、docx 解析
# ============================================================

def _match_timestamp(line: str):
    """匹配普通或带说话人前缀的时间戳行，返回正则匹配结果。"""
    text = SPEAKER_PREFIX_RE.sub("", str(line or ""), count=1)
    return TS_RE.match(text)


def _timestamp_text(match: re.Match) -> str:
    """将时间戳匹配结果规范为 MM:SS 或 HH:MM:SS，保留秒级精度。"""
    value = match.group(1) + ":" + match.group(2)
    if match.group(3):
        value += ":" + match.group(3)
    return value


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
        m = _match_timestamp(p)
        if m:
            if buf:
                segs.append((cur_ts or "", "".join(buf)))
            cur_ts = _timestamp_text(m)
            buf = [m.group(4)] if m.group(4) else []
        else:
            buf.append(p)
    if buf:
        segs.append((cur_ts or "", "".join(buf)))
    return segs


def parse_original(paras):
    """解析原文；无时间戳时保留正文段落，并将 ts 留空。"""
    title = paras[0] if paras else ""
    body_start = 2 if len(paras) > 1 and DATE_LINE_RE.match(paras[1]) else 1
    body_paras = paras[body_start:]
    if any(_match_timestamp(text) for text in body_paras):
        segs = split_ts_text(body_paras)
    else:
        segs = [("", text) for text in body_paras if str(text).strip()]
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
            m = _match_timestamp(p)
            if m:
                # 新章节：时间戳 + 标题
                if cur_section is not None:
                    sections.append(cur_section)
                cur_section = {
                    "ts": _timestamp_text(m),
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

# 仅用于学习视图派生文本；原始转写片段始终原样保存在知识库中。
NON_LEARNING_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"^(?:大家|同学们)?(?:早上|上午|中午|下午|晚上)?好[啊呀嘛]?$",
        r"^(?:大家)?(?:能|可以)(?:听|看)(?:到|见|清楚)(?:我|声音|屏幕)?吗?$",
        r"^(?:感谢|谢谢)(?:大家|各位|同学们)?(?:的参与|的支持|收看)?[啊呀]?$",
        r"^(?:好[的，, ]*)?(?:今天|这节课|本节课|咱们)?(?:就)?(?:先)?(?:讲|聊)?到这(?:里|儿)?(?:吧)?$",
        r"^(?:下课|散会|拜拜|再见|回头见|下次见|下周[一二三四五六日天]?见)[了啊呀，, ]*$",
        r"^(?:大家)?(?:点个赞|点点赞|关注一下|刷一波|扣个?\d|公屏上扣\d)[吧啊呀]?$",
        r"^(?:好的?|行|可以|没问题|收到|ok|okay)[了啊呀吧嘛，, ]*$",
    )
]
NON_LEARNING_PHRASES = (
    "下课，拜拜", "下课拜拜", "拜拜，下周", "拜拜下周", "下周二见",
    "大家唠唠嗑", "聊会儿天", "聊会儿天儿", "我这个头发", "头发有点自来卷",
    "开班典礼", "直播课与录播课", "直播课和录播课", "资源领取", "班主任通知",
    "课程平台", "课程初期无作业", "更新课表", "讲师、助教和班主任",
    "价格优惠", "锁定优惠", "直播课回放", "优惠的方法",
)


def _sentence_key(text):
    """生成去重用句子键，忽略空白、标点和常见口语连接词。"""
    value = str(text or "").casefold()
    value = re.sub(r"^(?:那么|然后|所以|就是|这个|其实)+", "", value)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def _is_non_learning_sentence(text):
    """判断句子是否仅包含寒暄、直播互动、结束语等非课程内容。"""
    value = re.sub(r"[。！？!?；;…\s]+$", "", str(text or "").strip())
    compact = re.sub(r"\s+", "", value).casefold()
    if not compact:
        return True
    if any(phrase in compact for phrase in NON_LEARNING_PHRASES):
        return True
    return any(pattern.fullmatch(value) for pattern in NON_LEARNING_PATTERNS)


def _dedupe_adjacent_clauses(text):
    """压缩相邻的重复短语或分句，如“我们慢慢来，我们慢慢来”。"""
    value = str(text or "")
    repeated = re.compile(r"([\u4e00-\u9fffA-Za-z0-9 ]{2,16})[，,、 ]+\1")
    while repeated.search(value):
        value = repeated.sub(r"\1", value)
    return value


def clean_text(text):
    """清洗单段学习文字，过滤口头语、重复表达与非课程聊天。

    用于「未配置 API Key」或「LLM 萃取失败」时的离线降级清洗；
    配置 Key 后优先使用 app.py 中的 AI 结构化萃取（extract_structured_knowledge）。
    """
    if not text:
        return ""
    sentences = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", str(text))
    kept = []
    for sentence in sentences:
        if _is_non_learning_sentence(sentence):
            continue
        cleaned = _dedupe_adjacent_clauses(sentence)
        for word in NOISE_WORDS:
            cleaned = cleaned.replace(word, "")
        cleaned = re.sub(
            r"^(?:在)?(?:本次|这次)?(?:课程|分享|讨论|对话|演讲)(?:中)?[，, ]*"
            r"(?:老师与学生|参与者)?(?:主要|重点|深入|详细|集中|还)?"
            r"(?:介绍了|讨论了|探讨了|围绕|聚焦于|焦点放在了|强调了|涵盖了|分享了)[，, ]*",
            "",
            cleaned,
        )
        cleaned = re.sub(r"^(?:整体上|总体而言|总的来说)[，, ]*", "", cleaned)
        cleaned = re.sub(r"([\u4e00-\u9fff])\1{2,}", r"\1", cleaned)
        cleaned = re.sub(r"([，。！？；：])\1+", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s*([，。！？；：、])\s*", r"\1", cleaned)
        cleaned = re.sub(r"[，。]{2,}", "。", cleaned)
        cleaned = re.sub(r"^[，。；：、,;: ]+", "", cleaned).strip()
        if cleaned and not _is_non_learning_sentence(cleaned):
            kept.append(cleaned)
    return "".join(kept).strip()


def clean_course_text(text, similarity=0.92):
    """清洗整课派生文本，并删除完全相同或高度相似的重复句。"""
    if not text:
        return ""
    output = []
    seen_keys = []
    exact_keys = set()
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            if output and output[-1] != "":
                output.append("")
            continue
        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line)
            heading = clean_text(heading)
            if heading:
                output.append(f"## {heading}")
            continue
        for sentence in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", line):
            cleaned = clean_text(sentence)
            key = _sentence_key(cleaned)
            if not key:
                continue
            duplicate = key in exact_keys
            if not duplicate and len(key) >= 12:
                duplicate = any(
                    SequenceMatcher(None, key, old).ratio() >= similarity
                    for old in seen_keys
                    if len(old) >= 12
                    and abs(len(key) - len(old)) <= max(3, len(key) // 10)
                    and (key[:6] == old[:6] or key[-6:] == old[-6:])
                )
            if duplicate:
                continue
            seen_keys.append(key)
            exact_keys.add(key)
            output.append(cleaned)
    while output and output[-1] == "":
        output.pop()
    return "\n".join(output)


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
    kb = {"cache_version": CACHE_VERSION, "courses": {}, "file_signs": {}}
    newly_added = []

    # 读取已有缓存
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("cache_version") == CACHE_VERSION:
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
                json.dump({"cache_version": CACHE_VERSION,
                           "courses": kb["courses"], "file_signs": kb["file_signs"]},
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
                cached = json.load(f)
            if cached.get("cache_version") != CACHE_VERSION:
                return True
            old_signs = cached.get("file_signs", {}) or {}
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
        return {"cache_version": CACHE_VERSION, "courses": {}, "file_signs": {}}
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


def timestamp_seconds(timestamp):
    """将 MM:SS / HH:MM:SS 转为秒；格式无效时返回 None。"""
    if not isinstance(timestamp, str):
        return None
    value = timestamp.strip().replace("：", ":")
    if not re.fullmatch(r"\d+:\d{2}(?::\d{2})?", value):
        return None
    parts = [int(part) for part in value.split(":")]
    if parts[-1] >= 60 or (len(parts) == 3 and parts[1] >= 60):
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _section_reference(value):
    """把时间戳字符串或章节字典规范为章节引用。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        if value.startswith("original-"):
            return {"id": value}
        return {"ts": value}
    return {}


def _summary_section_index(course, reference):
    """按精确时间戳或标题查找导读章节下标。"""
    sections = ((course or {}).get("summary") or {}).get("sections", [])
    target_seconds = timestamp_seconds(reference.get("ts"))
    for index, section in enumerate(sections):
        section_seconds = timestamp_seconds(section.get("ts"))
        if target_seconds is not None and section_seconds == target_seconds:
            return index
        if reference.get("title") and section.get("title") == reference["title"]:
            return index
    return None


def _original_section_index(section_id, segment_count):
    """解析 original-N 标识并返回零基下标。"""
    match = re.fullmatch(r"original-(\d+)", str(section_id or ""))
    if not match:
        return None
    index = int(match.group(1)) - 1
    return index if 0 <= index < segment_count else None


def section_original_segments(course, section):
    """按章节引用提取原文；导读章节使用本章起点到下一章起点的区间。"""
    reference = _section_reference(section)
    segments = ((course or {}).get("original") or {}).get("segments", [])
    original_index = _original_section_index(reference.get("id"), len(segments))
    if original_index is not None:
        return [segments[original_index]]

    summary_sections = ((course or {}).get("summary") or {}).get("sections", [])
    summary_index = _summary_section_index(course, reference)
    if summary_index is not None:
        start = timestamp_seconds(summary_sections[summary_index].get("ts"))
        end = None
        for next_section in summary_sections[summary_index + 1:]:
            end = timestamp_seconds(next_section.get("ts"))
            if end is not None:
                break
    else:
        start = timestamp_seconds(reference.get("ts"))
        end = None
        if start is not None:
            later = []
            for segment in segments:
                segment_seconds = timestamp_seconds(segment.get("ts"))
                if segment_seconds is not None and segment_seconds > start:
                    later.append(segment_seconds)
            end = min(later) if later else None
    if start is None:
        return []
    matched = []
    for segment in segments:
        segment_seconds = timestamp_seconds(segment.get("ts"))
        if segment_seconds is None or segment_seconds < start:
            continue
        if end is None or segment_seconds < end:
            matched.append(segment)
    return matched


def course_original_entries(course):
    """返回带稳定段落标识的原文条目，供浏览和关键词定位复用。"""
    segments = ((course or {}).get("original") or {}).get("segments", [])
    entries = []
    for index, segment in enumerate(segments):
        text = clean_text(segment.get("text") or "")
        if not text:
            continue
        marker = segment.get("ts") or f"段落 {index + 1}"
        entries.append({
            "id": f"original-{index + 1}",
            "index": index + 1,
            "ts": segment.get("ts") or "",
            "marker": marker,
            "text": text,
        })
    return entries


def search_course_segments(course, query="", limit=None):
    """在课程原文中按全部关键词检索；空查询返回可分页的完整原文。"""
    entries = course_original_entries(course)
    terms = [term.casefold() for term in re.split(r"\s+", str(query).strip()) if term]
    if terms:
        entries = [
            entry for entry in entries
            if all(term in entry["text"].casefold() for term in terms)
        ]
    return entries[:limit] if isinstance(limit, int) and limit >= 0 else entries


def _section_context_unit(course, section, index):
    """构造一个完整章节的导读与原文单元。"""
    title = section.get("title") or f"章节 {index + 1}"
    marker = section.get("ts") or section.get("id") or str(index + 1)
    lines = [f"【章节 {marker}】{title}"]
    body = clean_text(section.get("body") or "")
    if body:
        lines.append("【导读】" + body)
    segments = section_original_segments(course, section)
    for segment in segments:
        segment_marker = segment.get("ts") or "无时间戳"
        lines.append(f"[{segment_marker}] {clean_text(segment.get('text') or '')}")
    return {"id": f"section-{index + 1}", "title": title, "text": "\n".join(lines)}, segments


def course_context_units(course):
    """按章节构造整课上下文单元，并补入未被导读区间覆盖的原文。"""
    summary = (course or {}).get("summary") or {}
    original = (course or {}).get("original") or {}
    units = []
    covered = set()
    for index, section in enumerate(summary.get("sections", [])):
        unit, segments = _section_context_unit(course, section, index)
        if unit["text"].strip():
            units.append(unit)
        covered.update(id(segment) for segment in segments)
    entries_by_index = {entry["index"]: entry for entry in course_original_entries(course)}
    for index, segment in enumerate(original.get("segments", []), 1):
        if id(segment) not in covered:
            entry = entries_by_index.get(index)
            if not entry:
                continue
            units.append({"id": entry["id"], "title": entry["marker"],
                          "text": f"【原文 {entry['marker']}】\n{entry['text']}"})
    if not units and summary.get("summary"):
        units.append({"id": "summary", "title": "全文摘要",
                      "text": "【全文摘要】" + summary["summary"]})
    return units


def _split_context_unit(unit, max_chars):
    """把超长章节切为连续文本块，并保留章节标题。"""
    text = unit["text"]
    if len(text) <= max_chars:
        return [unit]
    prefix = f"【{unit['title']} · 分段】\n"
    size = max(1, max_chars - len(prefix))
    pieces = []
    for index, start in enumerate(range(0, len(text), size), 1):
        pieces.append({"id": f"{unit['id']}-{index}", "title": unit["title"],
                       "text": prefix + text[start:start + size]})
    return pieces


def course_context_chunks(course, max_chars=8000):
    """按章节边界打包整课上下文，确保头、中、尾内容均进入某个文本块。"""
    units = []
    for unit in course_context_units(course):
        units.extend(_split_context_unit(unit, max_chars))
    chunks, current, current_size = [], [], 0
    for unit in units:
        extra = len(unit["text"]) + (2 if current else 0)
        if current and current_size + extra > max_chars:
            chunks.append(current)
            current, current_size = [], 0
        current.append(unit)
        current_size += len(unit["text"]) + (2 if len(current) > 1 else 0)
    if current:
        chunks.append(current)
    return [{"id": f"chunk-{index + 1}",
             "title": " / ".join(unit["title"] for unit in group),
             "text": "\n\n".join(unit["text"] for unit in group)}
            for index, group in enumerate(chunks)]


def _balanced_unit_excerpt(units, max_chars):
    """在字符预算内均衡保留每个章节的开头与结尾。"""
    if not units:
        return ""
    joined = "\n\n".join(unit["text"] for unit in units)
    if len(joined) <= max_chars:
        return joined
    quota = max(12, (max_chars - len(units) * 2) // len(units))
    excerpts = []
    for unit in units:
        text = unit["text"]
        if len(text) > quota:
            head = max(1, quota * 2 // 3)
            text = text[:head] + "…" + text[-max(1, quota - head - 1):]
        excerpts.append(text)
    result = "\n\n".join(excerpts)
    return result[:max_chars]


def _section_filter_references(section_filter, course_name):
    """读取一门课的章节过滤条件，兼容旧时间戳字符串列表。"""
    if not section_filter or course_name not in section_filter:
        return []
    return [_section_reference(value) for value in section_filter[course_name]]


def gen_questions(kb, num=3, focus=None, course_names=None, section_filter=None):
    """基于知识库生成 num 道单选题。

    题型1（章节理解）：给出导读章节正文（已口语去噪），选择对应的章节标题。
    题型2（关键词记忆）：给出课程导读关键词，选属于该课的关键词。
    题型3（原文填空）：从原文中抽取含关键词的长句（已口语去噪），将关键词挖空，选项来自术语池。

    focus: 岗位重点关键词列表，命中关键词的课程优先出题。
    course_names: 可选，限定出题范围。可传大纲课程名或知识库课程名，内部按 normalize 自动匹配绑定。
    section_filter: 可选 dict，{知识库课程名: [章节引用, ...]}，按章节区间或 original-N 精确出题。
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
        references = _section_filter_references(section_filter, name)
        for index, s in enumerate(sm.get("sections", [])):
            if not (s.get("title") and s.get("body")):
                continue
            if references:
                if not any(_summary_section_index(courses[name], ref) == index
                           for ref in references):
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
        if _section_filter_references(section_filter, name):
            continue
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
            references = _section_filter_references(section_filter, name)
            allowed_segments = {
                id(segment)
                for reference in references
                for segment in section_original_segments(courses[name], reference)
            }
            for seg in org.get("segments", []):
                text = clean_text(seg.get("text", ""))
                if references and id(seg) not in allowed_segments:
                    continue
                for sent in SENT_SPLIT_RE.split(text):
                    sent = sent.strip()
                    if len(sent) < 20 or len(sent) > 120:
                        continue
                    for term in _extract_key_terms(sent):
                        if term in sent:
                            marker = seg.get("ts") or "无时间戳段落"
                            candidates.append((name, marker, sent, term))
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

def kb_course_context(course, max_chars=4000, section_ts=None, section=None):
    """把一门课的知识库内容拼成适合送入 LLM 的上下文文本。

    优先导读（关键词 / 全文摘要 / 章节速览），再附原文摘录；整体按 max_chars 裁剪。

    section_ts 保留用于兼容历史调用；section 可传统一章节字典。指定章节后，导读章节
    按当前起点到下一章起点提取原文，无时间戳原文按 original-N 精确定位。
    """
    sm = course.get("summary") or {}
    org = course.get("original") or {}

    reference = _section_reference(section or section_ts)
    if reference:
        section_units = []
        summary_index = _summary_section_index(course, reference)
        if summary_index is not None:
            selected = sm["sections"][summary_index]
            section_units.append({
                "id": "guide", "title": selected.get("title", "章节导读"),
                "text": "【章节 %s】%s\n%s" % (
                    selected.get("ts", ""), selected.get("title", ""),
                    clean_text(selected.get("body", "") or ""),
                ),
            })
        matched = section_original_segments(course, reference)
        if matched:
            positions = {id(item): index + 1 for index, item in enumerate(org.get("segments", []))}
            for segment in matched:
                marker = segment.get("ts") or f"段落 {positions.get(id(segment), '?')}"
                section_units.append({
                    "id": f"original-{positions.get(id(segment), '?')}", "title": marker,
                    "text": "[%s] %s" % (marker, clean_text(segment.get("text", ""))),
                })
        return _balanced_unit_excerpt(section_units, max_chars)

    metadata = []
    if sm.get("keywords"):
        metadata.append("【关键词】" + "、".join(sm["keywords"]))
    if sm.get("summary"):
        metadata.append("【全文摘要】" + sm["summary"])
    units = course_context_units(course)
    if metadata:
        units.insert(0, {"id": "metadata", "title": "课程概览",
                         "text": "\n\n".join(metadata)})
    return _balanced_unit_excerpt(units, max_chars)
