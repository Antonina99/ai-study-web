"""读取由课程原文复核得到的学习资产；源内容变化后自动停止采用旧校订。"""

import copy
import hashlib
import json
from pathlib import Path


REVIEW_DIR = Path(__file__).resolve().parent.parent / "assets" / "course_reviews"


def source_fingerprint(course: dict) -> str:
    """以解析后的原文和导读计算指纹，兼容不同部署文件时间。"""
    source = {key: course.get(key) for key in ("original", "summary")}
    payload = json.dumps(source, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def apply_reviews(knowledge: dict, review_dir: Path = REVIEW_DIR) -> dict:
    """只在来源指纹完全匹配时应用校订；缓存和原始逐字稿不被改写。"""
    result = dict(knowledge)
    result["courses"] = dict(knowledge.get("courses", {}))
    for path in sorted(review_dir.glob("*.json")):
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
            course = result["courses"].get(review["course_key"])
            if not course or source_fingerprint(course) != review["source_sha256"]:
                continue
            if not _valid_review(review, course):
                continue
            projected = dict(course)
            projected["summary"] = dict(course.get("summary") or {})
            for key in ("keywords", "sections"):
                projected["summary"][key] = copy.deepcopy(review[key])
            projected["summary"]["summary"] = " ".join(review["summary_points"])
            projected["reviewed_assets"] = copy.deepcopy(review)
            result["courses"][review["course_key"]] = projected
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def _valid_review(review: dict, course: dict) -> bool:
    """验证校订必需字段与原文引用，损坏的资产安全回退到源课程。"""
    for key in ("keywords", "summary_points", "interview_points"):
        values = review.get(key)
        if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
            return False
    if not review["summary_points"] or not isinstance(review.get("sections"), list):
        return False
    count = len((course.get("original") or {}).get("segments", []))
    allowed = {f"original-{index + 1}" for index in range(count)}
    for section in review["sections"]:
        if not isinstance(section, dict) or not all(
            isinstance(section.get(key), str) and section[key]
            for key in ("ts", "title", "body")
        ):
            return False
        if not section.get("citation_ids") or any(
            marker not in allowed for marker in section["citation_ids"]
        ):
            return False
    return bool(review["sections"])
