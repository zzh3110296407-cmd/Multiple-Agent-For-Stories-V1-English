"""Deterministic source-specific term detection.

This is intentionally conservative. It finds terms that are likely to be
source assets and therefore must not appear in structure-only profiles.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


ENTITY_TYPE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("学院", "institution"),
    ("大学", "institution"),
    ("学校", "institution"),
    ("教会", "organization"),
    ("公司", "organization"),
    ("组织", "organization"),
    ("协会", "organization"),
    ("公会", "organization"),
    ("联邦", "organization"),
    ("帝国", "organization"),
    ("王国", "organization"),
    ("局", "organization"),
    ("署", "organization"),
    ("计划", "plan_or_project"),
    ("项目", "plan_or_project"),
    ("工程", "plan_or_project"),
    ("家族", "family_or_clan"),
    ("门", "family_or_clan"),
    ("派", "family_or_clan"),
    ("城", "location"),
    ("塔", "location"),
    ("星", "location"),
    ("舰", "artifact"),
    ("剑", "artifact"),
    ("刀", "artifact"),
    ("枪", "artifact"),
    ("石", "artifact"),
    ("戒", "artifact"),
    ("术", "ability_or_power"),
    ("阵", "ability_or_power"),
    ("法", "ability_or_power"),
    ("特殊能力", "ability_or_power"),
    ("神", "mythic_figure"),
    ("王", "mythic_figure"),
    ("族", "species_or_race"),
)

ASCII_ORG_SUFFIXES = (
    "Academy",
    "Bureau",
    "Institute",
    "Order",
    "Guild",
    "Church",
    "Council",
    "Federation",
    "Empire",
    "Project",
    "Plan",
    "Sword",
    "Gate",
    "City",
    "Engine",
)

COMMON_STOPWORDS = {
    "主角",
    "读者",
    "故事",
    "章节",
    "弧段",
    "冲突",
    "危机",
    "高潮",
    "身份",
    "选择",
    "阶段",
    "世界",
    "未来",
    "规则",
    "情绪",
    "结构",
    "机制",
    "关系",
    "人物",
    "伏笔",
    "线索",
    "真相",
    "代价",
}

LEADING_CJK_TRIM = (
    "进入",
    "来到",
    "前往",
    "来自",
    "神秘",
    "隐藏",
    "所谓",
    "名为",
    "代号",
    "使用",
    "获得",
    "启动",
    "发现",
    "揭示",
    "回收",
)

SOURCE_CONTEXT_PREFIXES = (
    "神秘",
    "专属",
    "名为",
    "代号",
    "组织",
    "学院",
    "计划",
    "武器",
    "道具",
    "能力",
    "术法",
    "仪式",
    "系统",
)


def iter_strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def normalize_surface(surface: str) -> str:
    text = re.sub(r"\s+", " ", str(surface or "").strip(" \t\r\n,.;:!?，。；：！？()[]{}<>《》“”\"'"))
    for prefix in LEADING_CJK_TRIM:
        if text.startswith(prefix) and len(text) > len(prefix) + 1:
            text = text[len(prefix) :]
    return text.strip(" \t\r\n,.;:!?，。；：！？()[]{}<>《》“”\"'")


def classify_surface(surface: str) -> str:
    text = normalize_surface(surface)
    for suffix, entity_type in ENTITY_TYPE_SUFFIXES:
        if text.endswith(suffix):
            return entity_type
    words = text.split()
    if len(words) >= 2:
        for suffix in ASCII_ORG_SUFFIXES:
            if words[-1] == suffix:
                if suffix in {"Sword", "Gate", "Engine"}:
                    return "artifact"
                if suffix in {"Project", "Plan"}:
                    return "plan_or_project"
                if suffix == "City":
                    return "location"
                return "organization"
    return "unknown_source_term"


def is_probable_source_term(surface: str) -> bool:
    text = normalize_surface(surface)
    if len(text) < 2 or text in COMMON_STOPWORDS:
        return False
    if text.isdigit():
        return False
    if classify_surface(text) != "unknown_source_term":
        return True
    if re.fullmatch(r"[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)+", text):
        return True
    return False


def is_context_source_term(surface: str, *, min_cjk_length: int = 2) -> bool:
    text = normalize_surface(surface)
    if len(text) < 2 or text in COMMON_STOPWORDS:
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return False
    if re.fullmatch(r"(?:第)?\d+(?:章|节|幕|卷|条|号|集)?", text):
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]+", text) and len(text) < min_cjk_length:
        return False
    return True


def detect_source_terms(text: str) -> dict[str, str]:
    source = str(text or "")
    found: dict[str, str] = {}

    for match in re.finditer(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)+\b", source):
        term = normalize_surface(match.group(0))
        if is_probable_source_term(term):
            found.setdefault(term, classify_surface(term))

    suffix_pattern = "|".join(re.escape(suffix) for suffix, _ in ENTITY_TYPE_SUFFIXES)
    for match in re.finditer(rf"[\u4e00-\u9fffA-Za-z0-9]{{2,18}}(?:{suffix_pattern})", source):
        term = normalize_surface(match.group(0))
        if is_probable_source_term(term):
            found.setdefault(term, classify_surface(term))
            for suffix, _ in ENTITY_TYPE_SUFFIXES:
                if not term.endswith(suffix):
                    continue
                root = normalize_surface(term[: -len(suffix)])
                if root and root != term and root in source and is_context_source_term(root, min_cjk_length=3):
                    found.setdefault(root, "unknown_source_term")
                break

    for match in re.finditer(r"[“\"']([^“”\"']{2,30})[”\"']", source):
        term = normalize_surface(match.group(1))
        if is_probable_source_term(term):
            found.setdefault(term, classify_surface(term))

    for prefix in SOURCE_CONTEXT_PREFIXES:
        for match in re.finditer(rf"{re.escape(prefix)}([\u4e00-\u9fffA-Za-z0-9]{{2,10}})", source):
            term = normalize_surface(match.group(1))
            if is_context_source_term(term):
                found.setdefault(term, classify_surface(term))

    repeated = Counter(re.findall(r"[\u4e00-\u9fff]{2,6}", source))
    for term, count in repeated.items():
        if count < 3:
            continue
        term = normalize_surface(term)
        if term in COMMON_STOPWORDS:
            continue
        if any(marker in source for marker in (f"神秘{term}", f"{term}启动", f"{term}计划", f"{term}规则")):
            found.setdefault(term, classify_surface(term))

    return found
