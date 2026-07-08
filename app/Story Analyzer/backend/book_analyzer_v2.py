#!/usr/bin/env python3
"""
全书拆解器 V2 · DeepSeek/Qwen 直调版
三层架构：章节层（模型直调）→ 弧段层（模型直调）→ 全书层（模型直调）
支持断点续传、链条状态传递、V5.5 六扩展块

用法:
  模式A（章节文件夹）: python book_analyzer_v2.py folder <文件夹路径> [输出目录]
  模式B（整本书文件）: python book_analyzer_v2.py split  <文件路径>   [输出目录]
  模式C（仅后处理旧输出）: python book_analyzer_v2.py postprocess <输出目录>
  可选模型: --model-provider deepseek|qwen
"""

import hashlib
import json
import os
import time
import re
import sys
import datetime
from difflib import SequenceMatcher
from pathlib import Path

import requests

from story_analyzer_utils import chapter_sort_key, clean_chapter_title, read_story_text_file
from story_analyzer_v1.abstraction import build_structure_only_profile
from story_analyzer_v1.audit import LlmCallLogger
from story_analyzer_v1.memory_semantics import (
    apply_foreshadowing_semantic_contract,
    apply_promotion_gate,
)

BACKEND_DIR = Path(__file__).resolve().parent
ANALYZER_CODE_DIR = BACKEND_DIR.parent
DATA_DIR = ANALYZER_CODE_DIR / "data"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 本地环境变量（可选）─────────────────────────────────
def _load_local_env() -> None:
    for env_path in (BACKEND_DIR / ".env", ANALYZER_CODE_DIR / ".env"):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_local_env()

# ── 词库集成（可选）─────────────────────────────────
try:
    _VOCAB_DIR = BACKEND_DIR
    sys.path.insert(0, str(_VOCAB_DIR))
    from vocabulary_manager import (
        load_vocabulary, save_vocabulary,
        get_vocabulary_context, process_chapter_components,
    )
    _VOCAB_AVAILABLE = True
except ImportError:
    _VOCAB_AVAILABLE = False

# ── 配置 ─────────────────────────────────────────────
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_API_KEY  = os.environ.get(DEEPSEEK_API_KEY_ENV, "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL    = "deepseek-chat"

QWEN_API_KEY_ENV = "QWEN_API_KEY"
QWEN_DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
QWEN_BASE_URL = "https://your-openai-compatible-endpoint/v1"
QWEN_MODEL = "qwen3.6-35b-a3b-fp8"
QWEN_MAX_TOKENS = 12000

SUPPORTED_MODEL_PROVIDERS = {"deepseek", "qwen"}
DEFAULT_MODEL_PROVIDER = "deepseek"
MODEL_PROVIDER_ENV = "STORY_ANALYZER_MODEL_PROVIDER"
_ACTIVE_MODEL_PROVIDER: str | None = None
_ACTIVE_LLM_CALL_LOGGER: LlmCallLogger | None = None

ARC_SIZE   = 15
API_DELAY  = 2
MAX_RETRY  = 3
RETRY_WAIT = 8
TIMEOUT    = 300
CRITICAL_STAGE_EXTRA_RETRY_DELAYS = (30, 60)
CRITICAL_LLM_STAGES = {"arc_analysis", "book_analysis", "generation_profiles"}
ARC_TEXT_FIELD_LIMIT = 1200
ARC_LIST_FIELD_LIMIT = 8
ARC_PROMPT_CHAR_BUDGET = 90000

_RETRYABLE_LLM_ERROR_PATTERNS = (
    "proxyerror",
    "remotedisconnected",
    "connection reset",
    "connection aborted",
    "max retries exceeded",
    "temporarily unavailable",
    "bad gateway",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "read timed out",
    "connecttimeout",
    "sslerror",
)

_STRUCTURAL_ARC_TITLE_RE = re.compile(
    r"^(序幕|楔子|尾声|终章|第[一二三四五六七八九十百千万零〇两\d]+[幕卷部]|"
    r"prologue|epilogue|part\s+\d+|book\s+\d+)\b",
    re.IGNORECASE,
)

# ── 5 个宏观组件定义 ──────────────────────────────────
_MACRO_DEFS = {
    "macro_opening":                  {"label": "开端",       "order": 1},
    "macro_inciting_incident":        {"label": "触发事件",   "order": 2},
    "macro_development_escalation":   {"label": "发展/升级",  "order": 3},
    "macro_crisis_local_climax":      {"label": "危机/局部高潮", "order": 4},
    "macro_resolution_aftermath":     {"label": "结尾/余波",  "order": 5},
}


# ══════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════

_CHAPTER_SYSTEM_PROMPT = """\
你是一位专业的故事结构分析师，擅长中文小说深度拆解。
分析用户提供的章节，输出严格的 JSON 格式（不加任何 markdown 代码块包裹，不加任何额外文字）。

## 宏观组件（从以下5个中选，可多选）
- macro_opening：建立世界/主角/基调/初始缺口
- macro_inciting_incident：让故事进入运动，迫使角色回应核心问题
- macro_development_escalation：推进目标、扩大冲突
- macro_crisis_local_climax：角色面对关键选择，局部强度峰值
- macro_resolution_aftermath：呈现后果，形成阶段性落点

## 词库规则（必须遵守）
用户可能在【词库参考】中提供已有词条列表。你必须遵守以下规则：
1. **优先使用已有词条**：chapter_function、reader_emotion、character_desire、character_arc、conflict、information_release、style_pacing 这些字段的标签，必须优先从词库已有词条中选择。
2. **新词不得污染分析字段**：如果词库中确实没有合适的已有词条能描述当前分析内容，可以直接使用干净的新词；禁止在任何字段中输出内部新词标记（NEW_TERM）。
3. **不要用自由文本替代标签**：即使是 character_arc 的 arc_stage 字段，也应尽量匹配词库中已有的弧线模式（如"从服从到反抗"、"从天真到成熟"等），不匹配时才使用干净的新词。
4. **每个模块至少检查一次词库**：在填写每个模块的标签时，先检查词库中该模块的词条，确认没有合适的才创新。

## 链条模式
如果用户提供了【上章摘要】【已知伏笔】【角色状态】，请在此基础上继续追踪，
累积更新伏笔列表（保留未回收的，标记已回收的）。

## 伏笔 ID 规则
foreshadowing[].id 只作为本章临时引用编号；不要把 F001/F002 等编号当成全书稳定 ID。
最终稳定伏笔 ID 由本地分析器统一归一化分配。你只需要保证 content/status/planted_chapter/resolved_in_chapter 准确。

## 输出格式（纯 JSON，无任何包裹）

{
  "story_level": {
    "theme_proposition": "全书核心主题一句话",
    "causal_structure": "因果逻辑链",
    "protagonist_surface_goal": "主角表层目标",
    "protagonist_deep_desire": "主角深层欲望",
    "conflict_surface": "表层冲突",
    "conflict_deep": "深层冲突",
    "overall_emotion_curve": ["阶段1", "阶段2"]
  },
  "chapter": {
    "chapter_index": 1,
    "title": "章节标题",
    "summary": "本章摘要100-200字",
    "identified_macros": ["macro_opening"],
    "macro_assignment_reason": "选择原因",
    "plot_nodes": ["事件1", "事件2", "事件3"],
    "chapter_function": "本章结构功能",
    "reader_emotion": "读者情绪体验",
    "reader_emotion_intensity": 0.7,
    "character_desire": [
      {"character": "角色名", "surface_desire": "表层", "deep_desire": "深层", "desire_level": "strong"}
    ],
    "character_arc": [
      {"character": "角色名", "arc_stage": "当前状态", "change": "本章变化"}
    ],
    "conflict": [
      {"conflict_type": "外部/内部/人际", "surface": "表面冲突", "deep": "深层冲突"}
    ],
    "information_release": [
      {"info_type": "新信息/回收悬念/强化信息", "content": "内容", "reveal_method": "直接说明/暗示/行动展现"}
    ],
    "style_pacing": {
      "pacing": "急促/平缓/变速",
      "style_features": ["特点1", "特点2"],
      "tension_level": 0.7
    },
    "character_state_after": {
      "角色名": {"emotion": "情绪", "desire_level": "强度", "key_change": "变化"}
    }
  },
  "foreshadowing": [
    {"id": "F001", "content": "伏笔内容", "planted_chapter": 1, "status": "planted", "resolved_in_chapter": null}
  ],
  "ending_revelations": ["结尾揭示"],
  "recommendation_notes": ["创作建议"],
  "narrative_style": {
    "point_of_view": "叙述视角",
    "tense": "时态",
    "narrative_distance": "亲近/疏离/混合",
    "voice_characteristics": "声音特征"
  },
  "imagery_symbols": [
    {"symbol": "意象名", "meaning": "象征意义", "occurrences": 1}
  ],
  "genre_tags": ["现实主义"],
  "character_relationships": [
    {"character_a": "A", "character_b": "B", "relation_type": "关系类型", "dynamic": "动态"}
  ],
  "dialogue_motifs": [
    {"motif": "对话/句式", "context": "场景", "significance": "意义"}
  ],
  "key_objects_scenes": [
    {"name": "名称", "type": "object/scene", "symbolic_meaning": "象征意义"}
  ]
}
"""

_ARC_SYSTEM_PROMPT = """\
你是一位专业文学结构分析师，专注弧段层分析。
收到若干章节分析结果，提炼弧段层规律。
输出纯 JSON（不加 markdown 代码块，不加额外文字）：

{
  "arc_index": 1,
  "arc_chapter_range": "1-5",
  "arc_title": "弧段标题",
  "arc_theme": "弧段主题",
  "arc_summary": "弧段摘要200-400字",
  "arc_macros": ["macro_opening", "macro_inciting_incident"],
  "character_arcs_in_arc": {
    "角色名": {
      "arc_start_state": "开始状态",
      "arc_end_state": "结束状态",
      "key_changes": ["变化1", "变化2"]
    }
  },
  "foreshadowing_summary": {
    "planted_in_arc": [{"id": "F001", "content": "内容", "planted_chapter": 1}],
    "resolved_in_arc": [{"id": "F001", "content": "内容", "resolved_chapter": 3}],
    "still_open": ["F002"]
  },
  "arc_conflict_escalation": "冲突升级描述",
  "arc_pacing": "节奏描述",
  "arc_turning_point": "弧段转折点",
  "arc_emotion_curve": ["阶段1", "阶段2", "阶段3"]
}
"""

_BOOK_SYSTEM_PROMPT = """\
你是一位专业的文学结构分析师，专注全书宏观分析。
收到所有弧段分析结果，提炼全书规律。
输出纯 JSON（不加 markdown 代码块，不加额外文字）：

{
    "total_chapters": 9,
    "total_arcs": 1,
    "book_theme": "全书核心主题一句话",
    "theme_evolution": [
        {"arc": 1, "theme_phase": "主题阶段", "key_event": "关键事件"}
    ],
    "complete_character_arcs": {
        "角色名": {
            "introduction": "登场章节及初始状态",
            "turning_points": ["转折1", "转折2"],
            "conclusion": "最终命运",
            "full_arc_summary": "完整弧线一段话"
        }
    },
    "foreshadowing_map": {
        "F001": {
            "planted_arc": 1,
            "resolved_arc": null,
            "status": "resolved/unresolved/intentionally_open"
        }
    },
    "narrative_rhythm": "全书节奏描述3-4句话",
    "structural_pattern": "叙事结构类型及说明",
    "imagery_system": "核心意象及象征演变2-3句话",
    "book_summary": "200字以内全书叙事总结"
}
"""


# ══════════════════════════════════════════════════════
# 通用 LLM 调用
# ══════════════════════════════════════════════════════

def _extract_json(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*\n?|\n?```\s*$", "", text, flags=re.MULTILINE).strip()
    return text


def _strip_new_term_marker(value):
    if isinstance(value, str):
        cleaned = value.replace("[NEW_TERM]", "")
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([，。；：、,.!?])", r"\1", cleaned)
        return cleaned.strip()
    if isinstance(value, list):
        return [_strip_new_term_marker(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_new_term_marker(item) for key, item in value.items()}
    return value


def _legacy_arc_chunk_size(total_chapters: int) -> int:
    if total_chapters <= 8:
        return 2
    if total_chapters <= 20:
        return 4
    if total_chapters <= 60:
        return 6
    return 8


def _is_structural_arc_title(title: str) -> bool:
    return bool(_STRUCTURAL_ARC_TITLE_RE.match(title.strip()))


def _legacy_arc_ranges(chapters: list[dict]) -> list[tuple[int, int]]:
    total = len(chapters)
    if total == 0:
        return []

    structural_starts = [
        index
        for index, chapter in enumerate(chapters, start=1)
        if int(chapter.get("part_index") or 1) == 1 and _is_structural_arc_title(str(chapter.get("title", "")))
    ]
    if len(structural_starts) >= 3:
        ranges: list[tuple[int, int]] = []
        for position, start in enumerate(structural_starts):
            end = structural_starts[position + 1] - 1 if position + 1 < len(structural_starts) else total
            if start <= end:
                ranges.append((start, end))
        return ranges

    chunk_size = _legacy_arc_chunk_size(total)
    return [(start, min(start + chunk_size - 1, total)) for start in range(1, total + 1, chunk_size)]


def _normalized_source_title(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(title or "").lower(), flags=re.UNICODE)


def _normalized_source_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _chapter_texts_match_for_deduplication(first: str, second: str) -> bool:
    left = _normalized_source_text(first)
    right = _normalized_source_text(second)
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) / max(len(longer), 1) < 0.92:
        return False
    return longer.startswith(shorter) or SequenceMatcher(None, shorter[-5000:], longer[-5000:]).ratio() >= 0.98


def _find_repeated_chapter_block_size(chapters: list[dict]) -> tuple[int, dict] | None:
    total = len(chapters)
    if total < 6 or total % 2 != 0:
        return None
    block_size = total // 2
    first_block = chapters[:block_size]
    second_block = chapters[block_size:]
    title_matches = [
        _normalized_source_title(first.get("title", "")) == _normalized_source_title(second.get("title", ""))
        for first, second in zip(first_block, second_block)
    ]
    if not all(title_matches):
        return None

    exact_matches = 0
    compatible_matches = 0
    mismatches = []
    for index, (first, second) in enumerate(zip(first_block, second_block), start=1):
        first_text = str(first.get("text", ""))
        second_text = str(second.get("text", ""))
        if hashlib.sha256(first_text.encode("utf-8")).hexdigest() == hashlib.sha256(second_text.encode("utf-8")).hexdigest():
            exact_matches += 1
            compatible_matches += 1
        elif _chapter_texts_match_for_deduplication(first_text, second_text):
            compatible_matches += 1
        else:
            mismatches.append(index)

    minimum_exact = max(1, block_size - 1)
    if exact_matches >= minimum_exact and compatible_matches == block_size:
        return block_size, {
            "status": "deduplicated",
            "reason": "adjacent_repeated_source_chapter_sequence",
            "original_count": total,
            "deduped_count": block_size,
            "removed_count": total - block_size,
            "repeated_block_count": 2,
            "exact_duplicate_pairs": exact_matches,
            "compatible_duplicate_pairs": compatible_matches,
            "mismatched_pair_indices": mismatches,
        }
    return None


def _dedupe_repeated_source_chapter_sequence(chapters: list[dict]) -> tuple[list[dict], dict]:
    result = _find_repeated_chapter_block_size(chapters)
    if result is None:
        return list(chapters), {
            "status": "not_needed",
            "original_count": len(chapters),
            "deduped_count": len(chapters),
            "removed_count": 0,
        }
    block_size, report = result
    return list(chapters[:block_size]), report


def _empty_foreshadowing_registry() -> dict:
    return {
        "schema_version": "book_analyzer_v2.foreshadowing_registry.v1",
        "next_index": 1,
        "items": [],
        "source_model_id_map": {},
        "source_model_id_alias_collisions": [],
        "source_model_id_conflicts": [],
    }


def _append_unique(values: list, value) -> None:
    if value is not None and value not in values:
        values.append(value)


def _list_from_value(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


_FORESHADOWING_TRACKING_SCOPES = {"local", "arc", "book", "series"}
_FORESHADOWING_MEMORY_LANES = {
    "strict_foreshadowing",
    "plot_setup",
    "world_fact",
    "character_state",
    "quote_or_signal",
}

_FORESHADOWING_QUOTE_SIGNAL_TERMS = (
    "show me",
    "临时言灵",
    "口号",
    "台词",
    "slogan",
    "quote",
)

_FORESHADOWING_WORLD_FACT_TERMS = (
    "学院的存在",
    "卡塞尔学院",
    "卡塞尔",
    "世界观",
    "规则",
    "血统级别",
    "预科生",
    "龙族遗迹",
    "炼金术",
    "言灵",
    "龙骨",
    "龙王骨骸",
)

_FORESHADOWING_CHARACTER_STATE_TERMS = (
    "人性",
    "家庭温暖",
    "生父",
    "牺牲",
    "铭记",
    "特殊感情",
    "悲伤",
    "孤独",
    "渴望",
    "记忆",
    "创伤",
    "character",
    "emotion",
)

_FORESHADOWING_PLOT_SETUP_TERMS = (
    "被指定",
    "任务专员",
    "协助",
    "成为共犯",
    "派遣",
    "行动",
    "求婚",
    "悬赏",
    "承诺",
    "校董会",
    "共犯",
    "指定",
)


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chapter_distance(start, end) -> int | None:
    start_int = _int_or_none(start)
    end_int = _int_or_none(end)
    if start_int is None or end_int is None:
        return None
    return max(0, end_int - start_int)


def _infer_foreshadowing_tracking_scope(item: dict) -> str:
    status = _normalize_foreshadowing_status(item.get("status") or "planted")
    content = " ".join(
        str(item.get(key) or "")
        for key in ("canonical_content", "content", "resolved_aspect")
    )
    if (
        status == "partially_resolved"
        or item.get("resolution_scope") == "series"
        or item.get("open_questions")
        or _looks_like_long_horizon_reveal(content)
    ):
        return "series"
    if status == "resolved":
        distance = _chapter_distance(item.get("planted_chapter"), item.get("resolved_in_chapter"))
        if distance is None:
            return "local"
        if distance <= 1:
            return "local"
        if distance <= 5:
            return "arc"
        return "book"
    if item.get("state_updates"):
        return "book"
    return "book"


def _infer_foreshadowing_memory_lane(item: dict) -> str:
    status = _normalize_foreshadowing_status(item.get("status") or "planted")
    tracking_scope = item.get("tracking_scope") or _infer_foreshadowing_tracking_scope(item)
    content = " ".join(
        str(item.get(key) or "")
        for key in ("canonical_content", "content", "resolved_aspect")
    )
    if (
        tracking_scope == "series"
        or status == "partially_resolved"
        or item.get("open_questions")
        or _looks_like_long_horizon_reveal(content)
    ):
        return "strict_foreshadowing"
    if _contains_any(content, _FORESHADOWING_QUOTE_SIGNAL_TERMS):
        return "quote_or_signal"
    if _contains_any(content, _FORESHADOWING_CHARACTER_STATE_TERMS):
        return "character_state"
    if _contains_any(content, _FORESHADOWING_WORLD_FACT_TERMS):
        return "world_fact"
    if _contains_any(content, _FORESHADOWING_PLOT_SETUP_TERMS):
        return "plot_setup"
    if tracking_scope == "local":
        return "plot_setup"
    if tracking_scope in {"arc", "book"} and status == "resolved":
        return "plot_setup"
    return "strict_foreshadowing"


def _apply_foreshadowing_item_compat_fields(item: dict) -> dict:
    content = str(
        item.get("canonical_content")
        or item.get("content")
        or item.get("summary")
        or item.get("text")
        or item.get("resolved_aspect")
        or ""
    ).strip()
    if not content:
        return item
    item.setdefault("canonical_content", content)
    item.setdefault("content", content)
    item.setdefault("summary", content)
    item.setdefault("text", content)
    return item


def _normalize_foreshadowing_item_contract(item: dict) -> dict:
    _apply_foreshadowing_item_compat_fields(item)
    status = _normalize_foreshadowing_status(item.get("status") or "planted")
    content = " ".join(
        str(item.get(key) or "")
        for key in ("canonical_content", "content", "resolved_aspect")
    )
    has_series_open_question = item.get("resolution_scope") == "series" and bool(item.get("open_questions"))
    if (
        status == "resolved"
        and (
            has_series_open_question
            or (
                item.get("resolution_scope") == "series"
                and (
                    bool(item.get("partial_resolution_chapters"))
                    or bool(item.get("last_partial_resolution_chapter"))
                )
            )
        )
        and (
            _looks_like_long_horizon_reveal(content)
            or _open_questions_indicate_long_horizon(item)
            or bool(item.get("partial_resolution_chapters"))
            or bool(item.get("last_partial_resolution_chapter"))
        )
        and not _looks_like_final_closure(content)
    ):
        status = "partially_resolved"
    item["status"] = status

    if status == "partially_resolved":
        partial_chapters = []
        for chapter in item.get("partial_resolution_chapters") or []:
            _append_unique(partial_chapters, chapter)
        _append_unique(partial_chapters, item.get("last_partial_resolution_chapter"))
        _append_unique(partial_chapters, item.get("resolved_in_chapter"))
        item.pop("resolved_in_chapter", None)
        if partial_chapters:
            item["partial_resolution_chapters"] = partial_chapters
            item["last_partial_resolution_chapter"] = partial_chapters[-1]
        item["resolution_scope"] = item.get("resolution_scope") or "series"
        if _looks_like_long_horizon_reveal(content) and not item.get("open_questions"):
            item["open_questions"] = ["long_horizon_thread_requires_future_confirmation_or_consequence"]
        item["tracking_scope"] = _infer_foreshadowing_tracking_scope(item)
        item["memory_lane"] = _infer_foreshadowing_memory_lane(item)
        return item

    if status == "resolved":
        item.pop("open_questions", None)
        item.pop("partial_resolution_chapters", None)
        item.pop("last_partial_resolution_chapter", None)
        if item.get("resolution_scope") == "series":
            item["resolution_scope"] = "local"
        item["tracking_scope"] = _infer_foreshadowing_tracking_scope(item)
        item["memory_lane"] = _infer_foreshadowing_memory_lane(item)
        return item

    item.pop("partial_resolution_chapters", None)
    item.pop("last_partial_resolution_chapter", None)
    if status == "planted":
        item.pop("resolved_in_chapter", None)
    item["tracking_scope"] = _infer_foreshadowing_tracking_scope(item)
    item["memory_lane"] = _infer_foreshadowing_memory_lane(item)
    return item


def _normalize_foreshadowing_registry_contract(registry: dict) -> dict:
    normalized = registry if isinstance(registry, dict) else _empty_foreshadowing_registry()
    normalized.setdefault("schema_version", "book_analyzer_v2.foreshadowing_registry.v1")
    normalized.setdefault("next_index", 1)
    normalized.setdefault("items", [])
    for item in normalized["items"]:
        if isinstance(item, dict):
            _normalize_foreshadowing_item_contract(item)
    normalized.setdefault("source_model_id_map", {})
    normalized.setdefault("source_model_id_alias_collisions", [])
    scope_counts = {scope: 0 for scope in sorted(_FORESHADOWING_TRACKING_SCOPES)}
    lane_counts = {lane: 0 for lane in sorted(_FORESHADOWING_MEMORY_LANES)}
    for item in normalized["items"]:
        if not isinstance(item, dict):
            continue
        scope = item.get("tracking_scope")
        if scope in scope_counts:
            scope_counts[scope] += 1
        lane = item.get("memory_lane")
        if lane in lane_counts:
            lane_counts[lane] += 1
    normalized["counts_by_tracking_scope"] = scope_counts
    normalized["counts_by_memory_lane"] = lane_counts
    normalized["strict_foreshadowing_item_count"] = lane_counts.get("strict_foreshadowing", 0)
    # Model-emitted IDs are local hints. Stable IDs assigned by this registry are the only
    # authoritative IDs, so raw model ID reuse must never surface as a final conflict.
    normalized["source_model_id_conflicts"] = []
    normalized = apply_foreshadowing_semantic_contract(normalized)
    for item in normalized.get("items", []):
        if isinstance(item, dict):
            _normalize_foreshadowing_item_contract(item)
    normalized = apply_foreshadowing_semantic_contract(normalized)
    for item in normalized.get("items", []):
        if isinstance(item, dict):
            _apply_foreshadowing_item_compat_fields(item)
    return normalized


def _write_foreshadowing_registry(path: Path, registry: dict) -> dict:
    normalized = _normalize_foreshadowing_registry_contract(registry)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def _foreshadowing_registry_ref(registry: dict) -> dict:
    scope_counts = {scope: 0 for scope in sorted(_FORESHADOWING_TRACKING_SCOPES)}
    lane_counts = {lane: 0 for lane in sorted(_FORESHADOWING_MEMORY_LANES)}
    for item in registry.get("items", []):
        scope = item.get("tracking_scope")
        if scope in scope_counts:
            scope_counts[scope] += 1
        lane = item.get("memory_lane")
        if lane in lane_counts:
            lane_counts[lane] += 1
    return {
        "schema_version": registry.get("schema_version"),
        "item_count": len(registry.get("items", [])),
        "conflict_count": 0,
        "source_model_id_alias_collision_count": len(registry.get("source_model_id_alias_collisions", [])),
        "counts_by_tracking_scope": scope_counts,
        "counts_by_memory_lane": lane_counts,
    }


def _canonical_foreshadowing_key(content: str) -> str:
    text = str(content or "").lower()
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text


_FORESHADOWING_EXPLANATION_MARKERS = (
    "，暗示",
    "。暗示",
    "；暗示",
    ",暗示",
    ".暗示",
    "，预示",
    "。预示",
    "，成为",
    "。成为",
    "，证实",
    "。证实",
    "，呼应",
    "。呼应",
    "，本章",
    "。本章",
    "；本章",
    ", this",
    ". this",
    ", suggesting",
    ". suggesting",
    ", foreshadowing",
    ". foreshadowing",
)


def _foreshadowing_core_content(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    lower = text.lower()
    cut_positions = [lower.find(marker.lower()) for marker in _FORESHADOWING_EXPLANATION_MARKERS if marker.lower() in lower]
    if cut_positions:
        text = text[: min(cut_positions)].strip()
    return text.rstrip("。；;，, ")


_GENERIC_SUBJECT_REFS = ("主角", "主人公", "男主角", "女主角", "男主", "女主")
_LEADING_SUBJECT_CONNECTORS = (
    "在",
    "于",
    "因",
    "对",
    "与",
    "向",
    "从",
    "被",
    "把",
    "将",
    "收到",
    "发现",
    "意识到",
    "说出",
    "喊出",
    "使用",
    "进入",
    "遇见",
    "梦见",
    "拥有",
    "选择",
    "决定",
)


def _has_generic_subject_ref(content: str) -> bool:
    return any(ref in str(content or "") for ref in _GENERIC_SUBJECT_REFS)


def _normalize_leading_subject_for_key(content: str) -> str:
    text = str(content or "")
    connectors = "|".join(re.escape(connector) for connector in _LEADING_SUBJECT_CONNECTORS)
    generic_subjects = "|".join(re.escape(ref) for ref in _GENERIC_SUBJECT_REFS)
    text = re.sub(rf"^(?:{generic_subjects})(?=(?:{connectors}))", "角色", text)
    text = re.sub(rf"^[\u4e00-\u9fff]{{2,4}}(?=(?:{connectors}))", "角色", text)
    return text


def _foreshadowing_key_variants(content: str) -> set[str]:
    variants = {_canonical_foreshadowing_key(content)}
    normalized_subject_key = _canonical_foreshadowing_key(_normalize_leading_subject_for_key(content))
    if normalized_subject_key:
        variants.add(normalized_subject_key)
    core_content = _foreshadowing_core_content(content)
    core_key = _canonical_foreshadowing_key(core_content)
    if core_key:
        variants.add(core_key)
        variants.add(_canonical_foreshadowing_key(_normalize_leading_subject_for_key(core_content)))
    return {variant for variant in variants if variant}


def _foreshadowing_status_rank(status: str) -> int:
    return {
        "planted": 1,
        "open": 1,
        "unresolved": 1,
        "intentionally_open": 2,
        "partially_resolved": 2,
        "resolved": 3,
    }.get(_normalize_foreshadowing_status(status), 1)


def _normalize_foreshadowing_status(status: str) -> str:
    normalized = str(status or "planted").strip().lower()
    return {
        "active": "planted",
        "ongoing": "planted",
        "open": "planted",
        "unresolved": "planted",
        "intentionally_open": "partially_resolved",
        "partial": "partially_resolved",
        "partially_revealed": "partially_resolved",
        "partially resolved": "partially_resolved",
        "reinforced": "planted",
        "reiterated": "planted",
        "observed": "planted",
        "confirmed": "planted",
        "pending": "planted",
        "seeded": "planted",
        "hinted": "planted",
        "surfaced": "planted",
        "closed": "resolved",
        "complete": "resolved",
        "completed": "resolved",
        "revealed": "resolved",
        "paid_off": "resolved",
        "paid off": "resolved",
    }.get(normalized, normalized or "planted")


_LONG_HORIZON_REVEAL_TERMS = (
    "odin",
    "nibelungen",
    "nibelung",
    "bloodline",
    "father",
    "parents",
    "parentage",
    "identity mystery",
    "\u5965\u4e01",
    "\u5c3c\u4f2f\u9f99\u6839",
    "\u8840\u7edf",
    "\u7236\u4eb2",
    "\u7236\u6bcd",
    "\u8eab\u4efd\u8c1c",
    "\u957f\u671f\u60ac\u5ff5",
    "\u8de8\u5377",
)

_FINAL_CLOSURE_TERMS = (
    "fully resolved",
    "completely resolved",
    "closed permanently",
    "final answer",
    "\u5b8c\u5168\u63ed\u793a",
    "\u5f7b\u5e95\u89e3\u51b3",
    "\u5df2\u5b8c\u5168\u56de\u6536",
    "\u7ec8\u7ed3",
    "\u6700\u7ec8\u7b54\u6848",
)


def _looks_like_long_horizon_reveal(content: str) -> bool:
    return _contains_any(str(content or ""), _LONG_HORIZON_REVEAL_TERMS)


def _looks_like_final_closure(content: str) -> bool:
    return _contains_any(str(content or ""), _FINAL_CLOSURE_TERMS)


_LONG_HORIZON_OPEN_QUESTION_MARKERS = (
    "long_horizon",
    "future consequence",
    "future",
    "cross-book",
    "series",
    "\u957f\u671f",
    "\u8de8\u5377",
    "\u540e\u7eed",
    "\u672a\u6765",
)


def _open_questions_indicate_long_horizon(item: dict) -> bool:
    question_text = json.dumps(item.get("open_questions") or [], ensure_ascii=False).lower()
    return _contains_any(question_text, _LONG_HORIZON_OPEN_QUESTION_MARKERS)


def _resolution_status_for_release(item: dict, release_content: str) -> tuple[str, dict]:
    combined = " ".join(
        [
            str(item.get("canonical_content") or item.get("content") or ""),
            str(release_content or ""),
        ]
    )
    if _looks_like_long_horizon_reveal(combined) and not _looks_like_final_closure(combined):
        return (
            "partially_resolved",
            {
                "resolution_scope": "series",
                "resolved_aspect": str(release_content or item.get("canonical_content") or "").strip(),
                "open_question": "long_horizon_thread_requires_future_confirmation_or_consequence",
            },
        )
    return (
        "resolved",
        {
            "resolution_scope": "local",
            "resolved_aspect": str(release_content or item.get("canonical_content") or "").strip(),
            "open_question": "",
        },
    )


def _apply_partial_resolution_metadata(item: dict, chapter_number: int, metadata: dict) -> None:
    item["status"] = "partially_resolved"
    item["resolution_scope"] = metadata.get("resolution_scope") or item.get("resolution_scope") or "series"
    if metadata.get("resolved_aspect") and metadata["resolved_aspect"] not in item.setdefault("resolved_aspects", []):
        item["resolved_aspects"].append(metadata["resolved_aspect"])
    if metadata.get("open_question") and metadata["open_question"] not in item.setdefault("open_questions", []):
        item["open_questions"].append(metadata["open_question"])
    chapters = item.setdefault("partial_resolution_chapters", [])
    if chapter_number not in chapters:
        chapters.append(chapter_number)
    item["last_partial_resolution_chapter"] = chapter_number


def _merge_foreshadowing_status(old_status: str, new_status: str) -> str:
    old_status = _normalize_foreshadowing_status(old_status)
    new_status = _normalize_foreshadowing_status(new_status)
    return new_status if _foreshadowing_status_rank(new_status) >= _foreshadowing_status_rank(old_status) else old_status


def _next_foreshadowing_id(registry: dict) -> str:
    existing = {str(item.get("id")) for item in registry.get("items", [])}
    index = int(registry.get("next_index") or 1)
    while True:
        candidate = f"F{index:03d}"
        index += 1
        if candidate not in existing:
            registry["next_index"] = index
            return candidate


def _find_foreshadowing_item(
    registry: dict,
    content_key: str,
    content_key_variants: set[str] | None = None,
    has_generic_subject: bool = False,
) -> dict | None:
    if not content_key:
        return None
    incoming_variants = content_key_variants or {content_key}
    for item in registry.get("items", []):
        if item.get("content_key") == content_key:
            return item
        existing_variants = set(item.get("content_key_variants") or [])
        existing_variants.update(_foreshadowing_key_variants(item.get("canonical_content") or item.get("content") or ""))
        if content_key in existing_variants:
            return item
        safe_shared_variants = {
            variant
            for variant in (incoming_variants & existing_variants)
            if not variant.startswith("角色") or has_generic_subject or item.get("has_generic_subject_ref")
        }
        if safe_shared_variants:
            return item
        for incoming_key in incoming_variants:
            for existing_key in existing_variants:
                if min(len(incoming_key), len(existing_key)) < 8:
                    continue
                if (incoming_key.startswith("角色") or existing_key.startswith("角色")) and not (
                    has_generic_subject or item.get("has_generic_subject_ref")
                ):
                    continue
                if incoming_key in existing_key or existing_key in incoming_key:
                    return item
        if has_generic_subject or item.get("has_generic_subject_ref"):
            for incoming_key in incoming_variants:
                for existing_key in existing_variants:
                    if min(len(incoming_key), len(existing_key)) < 12:
                        continue
                    if SequenceMatcher(None, incoming_key, existing_key).ratio() >= 0.97:
                        return item
    for item in registry.get("items", []):
        existing_key = item.get("content_key") or ""
        if min(len(content_key), len(existing_key)) < 12:
            continue
        if SequenceMatcher(None, content_key, existing_key).ratio() >= 0.94:
            return item
    return None


_CONTRACT_TRACKER_ANCHORS = (
    "用生命换取",
    "用生命交换",
    "生命交换",
    "交换力量",
    "换取力量",
    "四次召唤",
    "召唤机会",
    "four summons",
    "summon chances",
    "summoning chances",
    "one quarter of life",
    "quarter of life",
)

_CONTRACT_TRACKER_TERMS = (
    "契约",
    "生命",
    "召唤",
    "机会",
    "代价",
    "力量",
    "交换",
    "contract",
    "life",
    "summon",
    "summons",
    "chance",
    "cost",
    "quarter",
)

_CONTRACT_STATE_UPDATE_TERMS = (
    "目前",
    "已经消耗",
    "已消耗",
    "消耗一次",
    "剩余",
    "还剩",
    "75%",
    "25%",
    "四分之一",
    "remaining",
    "remains",
    "already consumed",
    "consumed",
    "one quarter",
    "quarter",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def _looks_like_contract_tracker(content: str) -> bool:
    text = str(content or "")
    lowered = text.lower()
    if "契约" not in text and "contract" not in lowered:
        return False
    return _contains_any(text, _CONTRACT_TRACKER_ANCHORS) or (
        ("生命" in text or "life" in lowered)
        and _contains_any(text, ("召唤", "机会", "代价", "力量", "交换", "summon", "chance", "cost", "quarter"))
    )


def _looks_like_life_cost_progress_update(content: str) -> bool:
    text = str(content or "")
    lowered = text.lower()
    has_life = "生命" in text or "life" in lowered
    has_progress = _contains_any(text, _CONTRACT_STATE_UPDATE_TERMS)
    has_cost_marker = _contains_any(text, ("消耗", "剩余", "四分之一", "75%", "25%", "consumed", "remaining", "remains", "quarter"))
    return has_life and has_progress and has_cost_marker


def _looks_like_contract_state_update(content: str) -> bool:
    text = str(content or "")
    return (
        _looks_like_contract_tracker(text)
        and _contains_any(text, _CONTRACT_STATE_UPDATE_TERMS)
    ) or _looks_like_life_cost_progress_update(text)


def _contract_tracker_overlap(incoming_content: str, existing_content: str) -> bool:
    incoming = str(incoming_content or "")
    existing = str(existing_content or "")
    incoming_lower = incoming.lower()
    existing_lower = existing.lower()
    if not _looks_like_contract_tracker(existing):
        return False
    if _looks_like_life_cost_progress_update(incoming):
        return True
    if not _looks_like_contract_tracker(incoming):
        return False
    if any(anchor.lower() in incoming_lower and anchor.lower() in existing_lower for anchor in _CONTRACT_TRACKER_ANCHORS):
        return True
    shared_terms = [term for term in _CONTRACT_TRACKER_TERMS if term.lower() in incoming_lower and term.lower() in existing_lower]
    return len(shared_terms) >= 3


def _find_foreshadowing_state_update_parent(registry: dict, content: str) -> dict | None:
    if not _looks_like_contract_state_update(content):
        return None
    for item in registry.get("items", []):
        existing_content = item.get("canonical_content") or item.get("content") or ""
        if _contract_tracker_overlap(content, existing_content):
            return item
    return None


def _append_foreshadowing_state_update(item: dict, chapter_number: int, raw_id: str, content: str) -> dict:
    update = {
        "chapter_number": chapter_number,
        "source_model_id": raw_id,
        "source_model_ids": [raw_id] if raw_id else [],
        "content": content,
        "update_type": "contract_progress",
    }
    update_key = (
        int(chapter_number or 0),
        _canonical_foreshadowing_key(content),
    )
    updates = item.setdefault("state_updates", [])
    for existing in updates:
        existing_key = (
            int(existing.get("chapter_number") or 0),
            _canonical_foreshadowing_key(existing.get("content") or ""),
        )
        if existing_key == update_key:
            if raw_id:
                existing_ids = existing.setdefault("source_model_ids", [])
                if raw_id not in existing_ids:
                    existing_ids.append(raw_id)
                existing.setdefault("source_model_id", raw_id)
            return existing
    updates.append(update)
    return update


def _state_update_source_ids(raw_id: str, raw_state_update: dict | None) -> list[str]:
    ids = []
    for candidate in (
        raw_id,
        (raw_state_update or {}).get("source_model_id"),
        *((raw_state_update or {}).get("source_model_ids") or []),
    ):
        candidate_id = str(candidate or "").strip()
        if candidate_id and candidate_id not in ids:
            ids.append(candidate_id)
    return ids


def _source_model_id_key(raw_id: str, chapter_number: int | None = None) -> str:
    raw_id = str(raw_id or "").strip()
    if not raw_id:
        return ""
    try:
        chapter = int(chapter_number or 0)
    except (TypeError, ValueError):
        chapter = 0
    if chapter > 0:
        return f"chapter_{chapter:03d}:{raw_id}"
    return raw_id


def _source_model_id_candidates(raw_id: str, chapter_number: int | None = None) -> list[str]:
    raw_id = str(raw_id or "").strip()
    if not raw_id:
        return []
    candidates = []
    scoped = _source_model_id_key(raw_id, chapter_number)
    if scoped:
        candidates.append(scoped)
    if raw_id not in candidates:
        candidates.append(raw_id)
    return candidates


def _record_source_model_id(
    registry: dict,
    raw_id: str,
    stable_id: str,
    content: str,
    chapter_number: int | None = None,
) -> None:
    if not raw_id:
        return
    source_key = _source_model_id_key(raw_id, chapter_number)
    if not source_key:
        return
    model_map = registry.setdefault("source_model_id_map", {})
    mapped_ids = model_map.setdefault(source_key, [])
    if stable_id not in mapped_ids:
        mapped_ids.append(stable_id)
    if len(mapped_ids) <= 1:
        return
    collisions = registry.setdefault("source_model_id_alias_collisions", [])
    for collision in collisions:
        if collision.get("source_model_id_key") == source_key:
            collision["stable_ids"] = list(mapped_ids)
            collision["latest_content"] = content
            collision["observation_count"] = int(collision.get("observation_count") or 1) + 1
            break
    else:
        collisions.append(
            {
                "source_model_id": raw_id,
                "source_model_id_key": source_key,
                "chapter_number": int(chapter_number or 0) or None,
                "stable_ids": list(mapped_ids),
                "latest_content": content,
                "observation_count": 1,
                "diagnostic": "scoped_raw_model_id_reused_for_multiple_stable_items",
            }
        )
    registry["source_model_id_conflicts"] = []


def _resolve_foreshadowing_item(raw_item: dict, chapter_number: int, registry: dict) -> dict:
    explicit_raw_id = str(
        raw_item.get("source_model_id")
        or raw_item.get("foreshadowing_id")
        or ""
    ).strip()
    item_id = str(raw_item.get("id") or "").strip()
    stable_item_from_id = _registry_item_by_id(registry, item_id) if item_id else None
    if stable_item_from_id and explicit_raw_id == item_id:
        explicit_raw_id = ""
    raw_id = explicit_raw_id or ("" if stable_item_from_id else item_id)
    content = str(
        raw_item.get("content")
        or raw_item.get("description")
        or raw_item.get("canonical_content")
        or ""
    ).strip()
    raw_state_update = raw_item.get("state_update") if isinstance(raw_item.get("state_update"), dict) else None
    raw_state_update_content = str((raw_state_update or {}).get("content") or "").strip()
    content_key = _canonical_foreshadowing_key(content)
    content_key_variants = _foreshadowing_key_variants(content)
    has_generic_subject = _has_generic_subject_ref(content)
    status = _normalize_foreshadowing_status(raw_item.get("status") or "planted")
    resolved_chapter = raw_item.get("resolved_in_chapter") or raw_item.get("resolved_chapter")
    if resolved_chapter and status == "planted":
        status = "resolved"
    partial_resolution_metadata: dict = {}
    if status == "resolved":
        release_status, release_metadata = _resolution_status_for_release({"canonical_content": content}, content)
        if release_status == "partially_resolved":
            status = "partially_resolved"
            resolved_chapter = None
            partial_resolution_metadata = release_metadata

    state_update = None
    state_update_parent = _find_foreshadowing_state_update_parent(
        registry,
        raw_state_update_content or content,
    )
    item = state_update_parent or stable_item_from_id or _find_foreshadowing_item(
        registry,
        content_key,
        content_key_variants,
        has_generic_subject,
    )
    is_state_update = state_update_parent is not None or raw_state_update is not None
    if item is None:
        item = {
            "id": _next_foreshadowing_id(registry),
            "canonical_content": content,
            "content_key": content_key,
            "content_key_variants": sorted(content_key_variants),
            "has_generic_subject_ref": has_generic_subject,
                    "status": _normalize_foreshadowing_status(status),
            "planted_chapter": raw_item.get("planted_chapter") or chapter_number,
            "resolved_in_chapter": resolved_chapter,
            "source_model_ids": [],
            "history": [],
        }
        registry.setdefault("items", []).append(item)
    else:
        effective_status = "partially_resolved" if is_state_update and status in {"planted", "open", "unresolved"} else status
        item["status"] = _merge_foreshadowing_status(str(item.get("status") or "planted"), effective_status)
        merged_variants = set(item.get("content_key_variants") or [])
        merged_variants.update(content_key_variants)
        item["content_key_variants"] = sorted(merged_variants)
        item["has_generic_subject_ref"] = bool(item.get("has_generic_subject_ref") or has_generic_subject)
        if resolved_chapter and not item.get("resolved_in_chapter"):
            item["resolved_in_chapter"] = resolved_chapter

    if partial_resolution_metadata:
        _apply_partial_resolution_metadata(item, chapter_number, partial_resolution_metadata)

    if raw_item.get("resolution_scope"):
        item["resolution_scope"] = raw_item.get("resolution_scope")
    if raw_item.get("open_questions"):
        open_questions = item.setdefault("open_questions", [])
        for question in _list_from_value(raw_item.get("open_questions")):
            _append_unique(open_questions, question)
    if raw_item.get("resolved_aspects"):
        resolved_aspects = item.setdefault("resolved_aspects", [])
        for aspect in _list_from_value(raw_item.get("resolved_aspects")):
            _append_unique(resolved_aspects, aspect)
    raw_partial_chapters = []
    for field in ("partial_resolution_chapters", "partial_resolution_chapter", "last_partial_resolution_chapter"):
        for chapter_ref in _list_from_value(raw_item.get(field)):
            _append_unique(raw_partial_chapters, chapter_ref)
    if raw_partial_chapters:
        partial_chapters = item.setdefault("partial_resolution_chapters", [])
        for chapter_ref in raw_partial_chapters:
            _append_unique(partial_chapters, chapter_ref)
        item["last_partial_resolution_chapter"] = partial_chapters[-1]

    if is_state_update:
        update_content = raw_state_update_content or content
        update_chapter = (raw_state_update or {}).get("chapter_number") or chapter_number
        try:
            update_chapter = int(update_chapter)
        except (TypeError, ValueError):
            update_chapter = chapter_number
        update_source_ids = _state_update_source_ids(raw_id, raw_state_update)
        primary_update_source_id = update_source_ids[0] if update_source_ids else raw_id
        state_update = _append_foreshadowing_state_update(
            item,
            update_chapter,
            primary_update_source_id,
            update_content,
        )
        state_update_ids = state_update.setdefault("source_model_ids", [])
        for update_source_id in update_source_ids:
            if update_source_id not in state_update_ids:
                state_update_ids.append(update_source_id)
            if update_source_id not in item.setdefault("source_model_ids", []):
                item["source_model_ids"].append(update_source_id)
            _record_source_model_id(registry, update_source_id, item["id"], update_content, update_chapter)
        item["status"] = _merge_foreshadowing_status(str(item.get("status") or "planted"), "partially_resolved")

    if status == "resolved" and not item.get("resolved_in_chapter"):
        item["resolved_in_chapter"] = resolved_chapter or chapter_number

    if raw_id and raw_id not in item.setdefault("source_model_ids", []):
        item["source_model_ids"].append(raw_id)
    _record_source_model_id(registry, raw_id, item["id"], content, chapter_number)

    item.setdefault("history", []).append(
        {
            "chapter_number": chapter_number,
            "source_model_id": raw_id,
            "status": status,
            "content": content,
            "event_type": "state_update" if is_state_update else "observation",
        }
    )

    normalized = dict(raw_item)
    normalized["id"] = item["id"]
    normalized["content"] = item.get("canonical_content") or content
    normalized["status"] = item.get("status") or status
    normalized["planted_chapter"] = item.get("planted_chapter")
    normalized["resolved_in_chapter"] = item.get("resolved_in_chapter")
    if raw_id:
        normalized["source_model_id"] = raw_id
    if state_update:
        normalized["state_update"] = state_update
        normalized["delta_type_hint"] = "state_update"
    return normalized


def _registry_item_by_id(registry: dict, stable_id: str) -> dict | None:
    for item in registry.get("items", []):
        if str(item.get("id")) == str(stable_id):
            return item
    return None


def _information_release_entries(report: dict) -> list[dict]:
    analysis = (report.get("chapter_analysis") or {}) if isinstance(report, dict) else {}
    releases = list(analysis.get("information_release") or [])
    releases.extend(report.get("information_release") or [])
    return [release for release in releases if isinstance(release, dict)]


def _strip_foreshadowing_ref_prefix(content: str) -> str:
    return re.sub(r"^\s*F\d{3}\s*[:：\-]\s*", "", str(content or "").strip())


def _resolved_delta_from_registry_item(item: dict, source_model_id: str = "") -> dict:
    _normalize_foreshadowing_item_contract(item)
    status = _normalize_foreshadowing_status(item.get("status", "resolved"))
    resolved = {
        "id": item.get("id"),
        "content": item.get("canonical_content", ""),
        "status": status,
        "tracking_scope": item.get("tracking_scope", _infer_foreshadowing_tracking_scope(item)),
        "memory_lane": item.get("memory_lane", _infer_foreshadowing_memory_lane(item)),
        "planted_chapter": item.get("planted_chapter"),
    }
    if status == "resolved":
        resolved["resolved_in_chapter"] = item.get("resolved_in_chapter")
    if item.get("last_partial_resolution_chapter"):
        resolved["partial_resolution_chapter"] = item.get("last_partial_resolution_chapter")
    for key in ("resolution_scope", "resolved_aspects", "open_questions"):
        if item.get(key):
            resolved[key] = item.get(key)
    if source_model_id:
        resolved["source_model_id"] = str(source_model_id)
    if item.get("state_updates"):
        resolved["state_updates"] = item.get("state_updates")
    return resolved


def _mark_foreshadowing_item_resolved(
    item: dict,
    chapter_number: int,
    release_content: str = "",
    source_model_id: str = "",
    source: str = "information_release",
) -> dict:
    release_status, release_metadata = _resolution_status_for_release(item, release_content)
    item["status"] = _merge_foreshadowing_status(str(item.get("status") or "planted"), release_status)
    if release_status == "resolved":
        item["resolved_in_chapter"] = item.get("resolved_in_chapter") or chapter_number
        item.setdefault("resolved_aspects", [])
        if release_metadata.get("resolved_aspect") and release_metadata["resolved_aspect"] not in item["resolved_aspects"]:
            item["resolved_aspects"].append(release_metadata["resolved_aspect"])
        item["resolution_scope"] = item.get("resolution_scope") or release_metadata.get("resolution_scope") or "local"
    else:
        _apply_partial_resolution_metadata(item, chapter_number, release_metadata)
    item.setdefault("history", []).append(
        {
            "chapter_number": chapter_number,
            "source_model_id": str(source_model_id or ""),
            "status": release_status,
            "content": release_content or item.get("canonical_content", ""),
            "source": source,
        }
    )
    return _resolved_delta_from_registry_item(item, source_model_id)


def _mark_foreshadowing_resolved_from_ref(
    registry: dict,
    ref_id: str,
    chapter_number: int,
    release_content: str = "",
) -> dict | None:
    stable_id = _stable_foreshadowing_id_from_ref(registry, ref_id, chapter_number)
    if not stable_id:
        return None
    item = _registry_item_by_id(registry, stable_id)
    if not item:
        return None
    return _mark_foreshadowing_item_resolved(
        item,
        chapter_number,
        release_content,
        str(ref_id or ""),
        "information_release",
    )


def _information_release_resolution_items(report: dict, chapter_number: int, registry: dict) -> list[dict]:
    resolved_items = []
    seen_ids = set()
    for release in _information_release_entries(report):
        release_text = f"{release.get('info_type', '')} {release.get('content', '')}"
        if "伏笔" not in release_text and "回收" not in release_text:
            continue
        for ref_id in re.findall(r"\bF\d{3}\b", release_text):
            item = _mark_foreshadowing_resolved_from_ref(registry, ref_id, chapter_number, str(release.get("content", "")))
            if item and item["id"] not in seen_ids:
                resolved_items.append(item)
                seen_ids.add(item["id"])
    return resolved_items


def _information_release_content_resolution_items(report: dict, chapter_number: int, registry: dict) -> list[dict]:
    resolved_items = []
    seen_ids = set()
    for release in _information_release_entries(report):
        content = _strip_foreshadowing_ref_prefix(str(release.get("content", "")).strip())
        content_key = _canonical_foreshadowing_key(content)
        if len(content_key) < 12:
            continue
        item = _find_foreshadowing_item(
            registry,
            content_key,
            _foreshadowing_key_variants(content),
            _has_generic_subject_ref(content),
        )
        if not item:
            continue
        resolved_item = _mark_foreshadowing_item_resolved(
            item,
            chapter_number,
            content,
            "",
            "information_release_content_match",
        )
        if resolved_item and resolved_item["id"] not in seen_ids:
            resolved_items.append(resolved_item)
            seen_ids.add(resolved_item["id"])
    return resolved_items


def _information_release_state_update_items(report: dict, chapter_number: int, registry: dict) -> list[dict]:
    update_items = []
    seen_updates = set()
    for release in _information_release_entries(report):
        raw_content = str(release.get("content", "")).strip()
        content = _strip_foreshadowing_ref_prefix(raw_content)
        if not content or not _looks_like_contract_state_update(content):
            continue
        parent = _find_foreshadowing_state_update_parent(registry, content)
        if not parent:
            continue
        raw_ids = re.findall(r"\bF\d{3}\b", raw_content)
        raw_id = raw_ids[0] if raw_ids else ""
        state_update = _append_foreshadowing_state_update(parent, chapter_number, raw_id, content)
        for source_id in raw_ids:
            source_ids = state_update.setdefault("source_model_ids", [])
            if source_id not in source_ids:
                source_ids.append(source_id)
            if source_id not in parent.setdefault("source_model_ids", []):
                parent["source_model_ids"].append(source_id)
            _record_source_model_id(registry, source_id, parent["id"], content, chapter_number)
        parent["status"] = _merge_foreshadowing_status(str(parent.get("status") or "planted"), "partially_resolved")
        _normalize_foreshadowing_item_contract(parent)
        update_key = (parent.get("id"), int(chapter_number or 0), _canonical_foreshadowing_key(content))
        if update_key in seen_updates:
            continue
        seen_updates.add(update_key)
        update_items.append(
            {
                "id": parent.get("id"),
                "content": parent.get("canonical_content", ""),
                "status": _normalize_foreshadowing_status(parent.get("status", "partially_resolved")),
                "planted_chapter": parent.get("planted_chapter"),
                "partial_resolution_chapter": parent.get("last_partial_resolution_chapter"),
                "state_update": state_update,
                "delta_type_hint": "state_update",
            }
        )
    return update_items


def _apply_foreshadowing_registry_to_report(report: dict, chapter_number: int, registry: dict) -> dict:
    normalized_report = json.loads(json.dumps(report, ensure_ascii=False))
    normalized_items = []
    for raw_item in normalized_report.get("foreshadowing", []) or []:
        if isinstance(raw_item, dict):
            normalized_items.append(_resolve_foreshadowing_item(raw_item, chapter_number, registry))
    normalized_items.extend(_information_release_state_update_items(normalized_report, chapter_number, registry))
    normalized_items.extend(_information_release_resolution_items(normalized_report, chapter_number, registry))
    normalized_items.extend(_information_release_content_resolution_items(normalized_report, chapter_number, registry))
    _normalize_foreshadowing_registry_contract(registry)
    for item in normalized_items:
        if isinstance(item, dict):
            stable_item = _registry_item_by_id(registry, str(item.get("id") or ""))
            if stable_item:
                _normalize_foreshadowing_item_contract(stable_item)
                item.update(_resolved_delta_from_registry_item(stable_item, str(item.get("source_model_id") or "")))
            else:
                _normalize_foreshadowing_item_contract(item)
    delta_candidates = [
        _with_foreshadowing_delta_type(item, chapter_number)
        for item in normalized_items
        if _is_foreshadowing_delta_for_chapter(item, chapter_number)
    ]
    delta_items = _dedupe_foreshadowing_delta_items(delta_candidates)
    normalized_report["foreshadowing"] = delta_items
    normalized_report["foreshadowing_delta"] = delta_items
    normalized_report["known_foreshadowing_snapshot"] = _foreshadowing_snapshot_from_registry(registry)
    normalized_report["foreshadowing_scope"] = "chapter_delta"
    normalized_report["foreshadowing_registry_ref"] = _foreshadowing_registry_ref(registry)
    return normalized_report


def _chapter_ref_matches(value, chapter_number: int) -> bool:
    try:
        return int(value) == int(chapter_number)
    except (TypeError, ValueError):
        return False


def _is_foreshadowing_delta_for_chapter(item: dict, chapter_number: int) -> bool:
    state_update = item.get("state_update") if isinstance(item, dict) else None
    return _chapter_ref_matches(item.get("planted_chapter"), chapter_number) or _chapter_ref_matches(
        item.get("resolved_in_chapter"),
        chapter_number,
    ) or _chapter_ref_matches(item.get("partial_resolution_chapter"), chapter_number) or _chapter_ref_matches(
        (state_update or {}).get("chapter_number"),
        chapter_number,
    )


def _with_foreshadowing_delta_type(item: dict, chapter_number: int) -> dict:
    enriched = dict(item)
    status = _normalize_foreshadowing_status(enriched.get("status", "planted"))
    if status == "partially_resolved" and enriched.get("resolved_in_chapter"):
        enriched["partial_resolution_chapter"] = enriched.get("partial_resolution_chapter") or enriched.get("resolved_in_chapter")
        enriched.pop("resolved_in_chapter", None)
    planted = _chapter_ref_matches(item.get("planted_chapter"), chapter_number)
    resolved = status == "resolved" and _chapter_ref_matches(enriched.get("resolved_in_chapter"), chapter_number)
    partially_resolved = _chapter_ref_matches(enriched.get("partial_resolution_chapter"), chapter_number)
    state_update = _chapter_ref_matches((item.get("state_update") or {}).get("chapter_number"), chapter_number)
    if planted and resolved:
        delta_type = "planted_and_resolved"
    elif resolved:
        delta_type = "resolved"
    elif partially_resolved:
        delta_type = "partially_resolved"
    elif item.get("delta_type_hint") == "state_update" or state_update:
        delta_type = "state_update"
    else:
        delta_type = "planted"
    if resolved:
        enriched["status"] = "resolved"
    elif partially_resolved:
        enriched["status"] = "partially_resolved"
    else:
        enriched["status"] = _normalize_foreshadowing_status(enriched.get("status", "planted"))
    enriched["delta_type"] = delta_type
    enriched.pop("delta_type_hint", None)
    return enriched


def _foreshadowing_delta_rank(delta_type: str) -> int:
    return {
        "planted": 1,
        "state_update": 2,
        "partially_resolved": 3,
        "planted_and_resolved": 3,
        "resolved": 4,
    }.get(str(delta_type or ""), 1)


def _merge_foreshadowing_delta_entry(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for key in ("planted_chapter", "resolved_in_chapter", "partial_resolution_chapter", "source_model_id"):
        if not merged.get(key) and incoming.get(key):
            merged[key] = incoming.get(key)
    for key in ("resolution_scope", "resolved_aspects", "open_questions"):
        if incoming.get(key):
            merged[key] = incoming.get(key)
    if incoming.get("state_update"):
        merged["state_update"] = incoming.get("state_update")
    if incoming.get("state_updates"):
        merged["state_updates"] = incoming.get("state_updates")
    if incoming.get("source_model_ids"):
        source_ids = list(merged.get("source_model_ids") or [])
        for source_id in incoming.get("source_model_ids") or []:
            if source_id not in source_ids:
                source_ids.append(source_id)
        merged["source_model_ids"] = source_ids
    merged["status"] = _merge_foreshadowing_status(
        str(merged.get("status") or "planted"),
        str(incoming.get("status") or "planted"),
    )
    if _foreshadowing_delta_rank(str(incoming.get("delta_type"))) > _foreshadowing_delta_rank(str(merged.get("delta_type"))):
        merged["delta_type"] = incoming.get("delta_type")
    return merged


def _dedupe_foreshadowing_delta_items(delta_items: list[dict]) -> list[dict]:
    deduped = []
    by_id = {}
    for item in delta_items:
        stable_id = str(item.get("id") or "").strip()
        if not stable_id:
            deduped.append(item)
            continue
        if stable_id not in by_id:
            entry = dict(item)
            entry["status"] = _normalize_foreshadowing_status(entry.get("status", "planted"))
            by_id[stable_id] = entry
            deduped.append(entry)
            continue
        merged = _merge_foreshadowing_delta_entry(by_id[stable_id], item)
        by_id[stable_id].clear()
        by_id[stable_id].update(merged)
    return deduped


def _foreshadowing_snapshot_from_registry(registry: dict) -> list[dict]:
    snapshot = []
    for item in registry.get("items", []):
        _normalize_foreshadowing_item_contract(item)
        status = _normalize_foreshadowing_status(item.get("status", "planted"))
        entry = {
            "id": item.get("id"),
            "content": item.get("canonical_content", ""),
            "status": status,
            "tracking_scope": item.get("tracking_scope", _infer_foreshadowing_tracking_scope(item)),
            "memory_lane": item.get("memory_lane", _infer_foreshadowing_memory_lane(item)),
            "planted_chapter": item.get("planted_chapter"),
        }
        if status == "resolved":
            entry["resolved_in_chapter"] = item.get("resolved_in_chapter")
        if item.get("state_updates"):
            entry["state_updates"] = item.get("state_updates")
        if item.get("last_partial_resolution_chapter"):
            entry["partial_resolution_chapter"] = item.get("last_partial_resolution_chapter")
        for key in ("resolution_scope", "resolved_aspects", "open_questions"):
            if item.get(key):
                entry[key] = item.get(key)
        snapshot.append(entry)
    return snapshot


def _open_foreshadowing_items(registry: dict) -> list[dict]:
    return [
        item
        for item in registry.get("items", [])
        if _normalize_foreshadowing_status(item.get("status") or "planted") != "resolved"
    ]


def _build_next_pack_from_report(report: dict, registry: dict, chapter_number: int) -> dict:
    chapter = report.get("chapter_analysis", {}) or {}
    fw_lines = [
        f"{item.get('id')}: {item.get('canonical_content')} -- {item.get('status', 'planted')}"
        for item in _open_foreshadowing_items(registry)
    ]
    char_state = chapter.get("character_state_after", {}) or {}
    cs_lines = [
        f"{name}: emotion={state.get('emotion','-')}, desire={state.get('desire_level','-')}, change={state.get('key_change','-')}"
        for name, state in char_state.items()
        if isinstance(state, dict)
    ]
    return {
        "chapter_number": chapter_number + 1,
        "source_chapter_index": chapter_number,
        "known_foreshadowing": "\n".join(fw_lines),
        "known_character_state": "\n".join(cs_lines),
        "previous_summary": chapter.get("summary", ""),
        "foreshadowing_registry_ref": _foreshadowing_registry_ref(registry),
    }


def _source_chapter_count(chapters: list[dict]) -> int:
    source_indices = []
    for offset, chapter in enumerate(chapters, start=1):
        try:
            source_indices.append(int(chapter.get("original_chapter_index") or offset))
        except (TypeError, ValueError):
            source_indices.append(offset)
    return len(set(source_indices))


def _apply_book_source_metadata(book_framework: dict, chapters: list[dict]) -> dict:
    book = json.loads(json.dumps(book_framework or {}, ensure_ascii=False))
    analysis_unit_count = len(chapters)
    source_total_chapters = _source_chapter_count(chapters)
    book["total_chapters"] = source_total_chapters
    book["source_total_chapters"] = source_total_chapters
    book["analysis_unit_count"] = analysis_unit_count
    book["chapter_count_basis"] = "source_chapters"
    return book


def _apply_book_arc_metadata(book_framework: dict, arcs: list[dict]) -> dict:
    book = json.loads(json.dumps(book_framework or {}, ensure_ascii=False))
    source_arc_count = len(arcs or [])
    hierarchy = _compile_arc_hierarchy(arcs or [])
    major_arc_count = len(hierarchy.get("major_arcs", []))
    sub_arc_count = len(hierarchy.get("sub_arcs", []))
    if source_arc_count:
        book["total_arcs"] = source_arc_count
    book["source_arc_count"] = source_arc_count
    book["sub_arc_count"] = sub_arc_count
    book["major_arc_count"] = major_arc_count
    book["arc_count_basis"] = "source_sub_arcs"
    book["arc_hierarchy_ref"] = {
        "schema_version": hierarchy.get("schema_version", "book_analyzer_v2.arc_hierarchy.v1"),
        "major_arc_count": major_arc_count,
        "sub_arc_count": sub_arc_count,
        "recommended_profile_ref": "generation_profiles.arc_hierarchy",
    }
    return book


def _apply_manifest_source_metadata(manifest: dict, chapters: list[dict]) -> dict:
    normalized = json.loads(json.dumps(manifest or {}, ensure_ascii=False))
    analysis_unit_count = len(chapters)
    source_total_chapters = _source_chapter_count(chapters)
    normalized["total_chapters"] = source_total_chapters
    normalized["source_total_chapters"] = source_total_chapters
    normalized["analysis_unit_count"] = analysis_unit_count
    normalized["chapter_count_basis"] = "source_chapters"
    normalized["legacy_analysis_unit_total"] = analysis_unit_count
    return normalized


def _arc_source_metadata(chapters: list[dict], start_chapter: int, end_chapter: int) -> dict:
    selected = chapters[start_chapter - 1 : end_chapter]
    grouped: dict[int, dict] = {}
    for offset, chapter in enumerate(selected, start=start_chapter):
        original_index = int(chapter.get("original_chapter_index") or offset)
        original_title = chapter.get("original_title") or chapter.get("title", "")
        entry = grouped.setdefault(
            original_index,
            {
                "original_chapter_index": original_index,
                "original_title": original_title,
                "analysis_unit_start": offset,
                "analysis_unit_end": offset,
                "part_count": int(chapter.get("part_count") or 1),
                "parts": [],
            },
        )
        entry["analysis_unit_end"] = offset
        if chapter.get("part_index"):
            entry["parts"].append(
                {
                    "analysis_unit_index": offset,
                    "part_index": int(chapter.get("part_index") or 1),
                    "part_count": int(chapter.get("part_count") or 1),
                    "part_start_char": chapter.get("part_start_char"),
                    "part_end_char": chapter.get("part_end_char"),
                }
            )

    original_indices = sorted(grouped)
    source_range = ""
    if original_indices:
        source_range = f"{original_indices[0]}-{original_indices[-1]}"

    return {
        "analysis_unit_range": f"{start_chapter}-{end_chapter}",
        "source_chapter_range": source_range,
        "source_chapters": [grouped[index] for index in original_indices],
    }


def _load_arc_frameworks_from_dir(arc_dir: Path) -> list[dict]:
    arc_frameworks = []
    for path in sorted(arc_dir.glob("arc_*.json")):
        try:
            arc_frameworks.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return arc_frameworks


def _inject_arc_source_metadata(arc_framework: dict, metadata: dict) -> dict:
    arc = json.loads(json.dumps(arc_framework, ensure_ascii=False))
    arc["analysis_unit_range"] = metadata["analysis_unit_range"]
    arc["source_chapter_range"] = metadata["source_chapter_range"]
    arc["source_chapters"] = metadata["source_chapters"]
    if not arc.get("arc_chapter_range") or arc.get("arc_chapter_range") == metadata["analysis_unit_range"]:
        arc["arc_chapter_range"] = metadata["source_chapter_range"]
    return arc


def _stable_foreshadowing_id_from_ref(
    registry: dict,
    ref_id: str,
    chapter_number: int | None = None,
) -> str | None:
    ref_id = str(ref_id or "").strip()
    if not ref_id:
        return None
    stable_ids = {str(item.get("id")) for item in registry.get("items", [])}
    if ref_id in stable_ids:
        return ref_id
    model_map = registry.get("source_model_id_map", {})
    for candidate in _source_model_id_candidates(ref_id, chapter_number):
        mapped = model_map.get(candidate, [])
        if len(mapped) == 1:
            return mapped[0]
    suffix = f":{ref_id}"
    unambiguous = []
    for key, mapped_ids in model_map.items():
        if key == ref_id or key.endswith(suffix):
            for stable_id in mapped_ids or []:
                if stable_id not in unambiguous:
                    unambiguous.append(stable_id)
    if len(unambiguous) == 1:
        return unambiguous[0]
    return None


def _normalize_arc_foreshadowing_summary(arc_framework: dict, registry: dict) -> dict:
    arc = json.loads(json.dumps(arc_framework, ensure_ascii=False))
    summary = arc.get("foreshadowing_summary")
    if not isinstance(summary, dict):
        return arc

    for key in ("planted_in_arc", "resolved_in_arc"):
        normalized = []
        for raw_item in summary.get(key, []) or []:
            if isinstance(raw_item, dict):
                item_input = dict(raw_item)
                if key == "resolved_in_arc":
                    item_input.setdefault("status", "resolved")
                    if item_input.get("resolved_chapter") and not item_input.get("resolved_in_chapter"):
                        item_input["resolved_in_chapter"] = item_input.get("resolved_chapter")
                item = _resolve_foreshadowing_item(
                    item_input,
                    int(item_input.get("planted_chapter") or item_input.get("resolved_in_chapter") or item_input.get("resolved_chapter") or 0),
                    registry,
                )
                normalized.append(item)
        summary[key] = normalized

    stable_open = []
    for ref_id in summary.get("still_open", []) or []:
        stable_id = _stable_foreshadowing_id_from_ref(registry, ref_id)
        item = _registry_item_by_id(registry, stable_id) if stable_id else None
        if stable_id and item and item.get("status") != "resolved" and stable_id not in stable_open:
            stable_open.append(stable_id)
    planted_ids = []
    for item in summary.get("planted_in_arc", []) or []:
        stable_id = str((item or {}).get("id") or "").strip()
        if stable_id and stable_id not in planted_ids:
            planted_ids.append(stable_id)
    resolved_ids = {
        str((item or {}).get("id") or "").strip()
        for item in summary.get("resolved_in_arc", []) or []
        if str((item or {}).get("id") or "").strip()
    }
    local_open = [stable_id for stable_id in planted_ids if stable_id in stable_open and stable_id not in resolved_ids]
    summary["still_open"] = stable_open
    summary["still_open_scope"] = "known_open_after_arc"
    summary["known_open_after_arc"] = stable_open
    summary["local_open_in_arc"] = local_open
    arc["foreshadowing_summary"] = summary
    arc["foreshadowing_registry_ref"] = _foreshadowing_registry_ref(registry)
    return arc


def _arc_index_for_analysis_chapter(chapter_number: int | None, arc_ranges: list[tuple[int, int]]) -> int | None:
    if not chapter_number:
        return None
    for arc_index, (start, end) in enumerate(arc_ranges, start=1):
        if start <= chapter_number <= end:
            return arc_index
    return None


def _apply_book_foreshadowing_registry(book_framework: dict, registry: dict, arc_ranges: list[tuple[int, int]]) -> dict:
    book = json.loads(json.dumps(book_framework, ensure_ascii=False))
    book["foreshadowing_map"] = {
        item["id"]: {
            "content": item.get("canonical_content", ""),
            "planted_chapter": item.get("planted_chapter"),
            "resolved_in_chapter": item.get("resolved_in_chapter"),
            "planted_arc": _arc_index_for_analysis_chapter(item.get("planted_chapter"), arc_ranges),
            "resolved_arc": _arc_index_for_analysis_chapter(item.get("resolved_in_chapter"), arc_ranges),
            "status": item.get("status", "planted"),
            "tracking_scope": item.get("tracking_scope", _infer_foreshadowing_tracking_scope(item)),
            "memory_lane": item.get("memory_lane", _infer_foreshadowing_memory_lane(item)),
            "state_updates": item.get("state_updates", []),
            "resolution_scope": item.get("resolution_scope"),
            "open_questions": item.get("open_questions", []),
            "resolved_aspects": item.get("resolved_aspects", []),
        }
        for item in registry.get("items", [])
    }
    book["foreshadowing_registry_ref"] = _foreshadowing_registry_ref(registry)
    return book


_NARRATIVE_THREAD_TYPES = (
    "foreshadowing",
    "mystery",
    "relationship_debt",
    "character_arc_pattern",
    "world_rule_reveal",
    "motif_symbol",
)

_THREAD_WORLD_RULE_TERMS = (
    "world rule",
    "rule",
    "system",
    "academy",
    "bloodline",
    "nibelungen",
    "law",
    "\u89c4\u5219",
    "\u4e16\u754c\u89c2",
    "\u5b66\u9662",
    "\u8840\u7edf",
    "\u5c3c\u4f2f\u9f99\u6839",
)

_THREAD_MYSTERY_TERMS = (
    "mystery",
    "unknown",
    "identity",
    "secret",
    "odin",
    "\u8c1c",
    "\u5965\u4e01",
    "\u771f\u76f8",
    "\u672a\u77e5",
    "\u795e\u79d8",
)

_THREAD_RELATIONSHIP_TERMS = (
    "relationship",
    "father",
    "mother",
    "parents",
    "parent",
    "absence",
    "debt",
    "\u5173\u7cfb",
    "\u7236",
    "\u6bcd",
    "\u4e8f\u6b20",
    "\u7f3a\u5e2d",
)

_THREAD_MOTIF_TERMS = (
    "motif",
    "symbol",
    "recurring",
    "rain",
    "threshold",
    "\u6bcd\u9898",
    "\u610f\u8c61",
    "\u8c61\u5f81",
    "\u53cd\u590d",
    "\u96e8",
    "\u95e8\u69db",
)


def _empty_narrative_thread_registry() -> dict:
    return {
        "schema_version": "book_analyzer_v2.narrative_thread_registry.v1",
        "next_index": 1,
        "item_count": 0,
        "counts_by_type": {thread_type: 0 for thread_type in _NARRATIVE_THREAD_TYPES},
        "items": [],
        "promotion_candidate_count": 0,
        "already_tracked_candidate_count": 0,
        "promotion_group_count": 0,
        "foreshadowing_promotion_groups": [],
        "promotion_review_groups": [],
        "foreshadowing_candidate_promotions": [],
        "suppressed_promotion_candidates": [],
    }


def _next_narrative_thread_id(registry: dict) -> str:
    existing = {str(item.get("id")) for item in registry.get("items", [])}
    index = int(registry.get("next_index") or 1)
    while True:
        candidate = f"T{index:03d}"
        index += 1
        if candidate not in existing:
            registry["next_index"] = index
            return candidate


def _narrative_thread_registry_ref(registry: dict) -> dict:
    return {
        "schema_version": registry.get("schema_version"),
        "item_count": registry.get("item_count", len(registry.get("items", []))),
        "counts_by_type": registry.get("counts_by_type", {}),
        "promotion_candidate_count": registry.get("promotion_candidate_count", 0),
        "already_tracked_candidate_count": registry.get("already_tracked_candidate_count", 0),
        "promotion_group_count": registry.get("promotion_group_count", 0),
        "suppressed_promotion_candidate_count": len(registry.get("suppressed_promotion_candidates", [])),
    }


def _classify_narrative_thread(content: str, hint: str = "") -> str:
    hint_text = str(hint or "")
    if _contains_any(hint_text, _THREAD_MOTIF_TERMS):
        return "motif_symbol"
    if _contains_any(hint_text, _THREAD_WORLD_RULE_TERMS):
        return "world_rule_reveal"
    if _contains_any(hint_text, _THREAD_MYSTERY_TERMS):
        return "mystery"
    if _contains_any(hint_text, _THREAD_RELATIONSHIP_TERMS):
        return "relationship_debt"

    text = f"{hint} {content}"
    if _contains_any(text, _THREAD_MOTIF_TERMS):
        return "motif_symbol"
    if _contains_any(text, _THREAD_WORLD_RULE_TERMS):
        return "world_rule_reveal"
    if _contains_any(text, _THREAD_MYSTERY_TERMS):
        return "mystery"
    if _contains_any(text, _THREAD_RELATIONSHIP_TERMS):
        return "relationship_debt"
    return "mystery"


def _narrative_thread_status(content: str, base_status: str = "planted") -> str:
    status = _normalize_foreshadowing_status(base_status)
    if status == "resolved" and _looks_like_long_horizon_reveal(content):
        return "partially_resolved"
    if status in {"planted", "open", "unresolved"} and _looks_like_long_horizon_reveal(content):
        return "partially_resolved"
    return status


def _add_narrative_thread(
    registry: dict,
    *,
    thread_type: str,
    content: str,
    status: str = "planted",
    source: str,
    evidence: list[dict] | None = None,
    linked_foreshadowing_id: str = "",
) -> None:
    content = str(content or "").strip()
    if not content:
        return
    thread_type = thread_type if thread_type in _NARRATIVE_THREAD_TYPES else "mystery"
    content_key = _canonical_foreshadowing_key(content)
    if len(content_key) < 6:
        return
    dedupe_key = f"{thread_type}:{content_key}"
    incoming_status = _narrative_thread_status(content, status)
    for item in registry.get("items", []):
        if item.get("content_key") == dedupe_key:
            item["status"] = _merge_foreshadowing_status(item.get("status", "planted"), incoming_status)
            for evidence_item in evidence or []:
                if evidence_item not in item.setdefault("evidence", []):
                    item["evidence"].append(evidence_item)
            if linked_foreshadowing_id:
                item["linked_foreshadowing_id"] = linked_foreshadowing_id
            return
    item = {
        "id": _next_narrative_thread_id(registry),
        "thread_type": thread_type,
        "content": content,
        "content_key": dedupe_key,
        "status": incoming_status,
        "source": source,
        "evidence": list(evidence or []),
    }
    if linked_foreshadowing_id:
        item["linked_foreshadowing_id"] = linked_foreshadowing_id
    if incoming_status == "partially_resolved":
        item["resolution_scope"] = "series"
        item["open_questions"] = ["long_horizon_thread_requires_future_confirmation_or_consequence"]
    registry.setdefault("items", []).append(item)


def _refresh_narrative_thread_counts(registry: dict) -> dict:
    counts = {thread_type: 0 for thread_type in _NARRATIVE_THREAD_TYPES}
    for item in registry.get("items", []):
        thread_type = item.get("thread_type")
        if thread_type in counts:
            counts[thread_type] += 1
    registry["counts_by_type"] = counts
    registry["item_count"] = len(registry.get("items", []))
    return registry


_FORESHADOWING_PROMOTION_TERMS = (
    "future consequence",
    "future",
    "unknown",
    "identity",
    "mystery",
    "secret",
    "unresolved",
    "remains",
    "long horizon",
    "悬念",
    "谜",
    "未知",
    "真相",
    "秘密",
    "未解",
    "仍未",
    "后续",
    "未来",
    "伏笔",
    "暗示",
    "计划",
)


def _looks_like_abstract_theme_thread(content: str) -> bool:
    text = str(content or "").lower()
    theme_terms = ("主题", "宿命", "命运", "牺牲", "救赎", "觉醒", "成长", "自我", "悲剧性", "情感")
    concrete_terms = (
        "身份",
        "计划",
        "档案",
        "隐藏区域",
        "领域",
        "胚胎",
        "契约",
        "活灵",
        "武器",
        "药物",
        "纯度",
        "失控",
        "未知",
        "门",
        "悬念",
        "unknown",
        "hidden",
        "plan",
        "identity",
    )
    if not _contains_any(text, theme_terms):
        return False
    if re.search(r"个体通过.+(完成|实现).+(救赎|觉醒|成长)", text):
        return True
    return not _contains_any(text, concrete_terms)


def _thread_needs_foreshadowing_promotion_review(item: dict) -> bool:
    thread_type = str(item.get("thread_type") or "")
    if thread_type == "foreshadowing" or item.get("linked_foreshadowing_id"):
        return False
    content = str(item.get("content") or "")
    if _looks_like_abstract_theme_thread(content):
        return False
    status = _normalize_foreshadowing_status(item.get("status") or "planted")
    if thread_type in {"mystery", "world_rule_reveal"} and (
        status == "partially_resolved"
        or _looks_like_long_horizon_reveal(content)
        or _contains_any(content, _FORESHADOWING_PROMOTION_TERMS)
    ):
        return True
    if thread_type in {"relationship_debt", "character_arc_pattern"} and _contains_any(
        content,
        ("debt", "absence", "unresolved", "未解", "亏欠", "缺席", "悬念", "后续"),
    ):
        return True
    return False


def _semantic_content_tokens(content: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", str(content or "").lower())
        if len(token) >= 2
    }


def _looks_like_same_tracked_thread(candidate_content: str, tracked_content: str) -> bool:
    candidate_key = _canonical_foreshadowing_key(_strip_foreshadowing_ref_prefix(candidate_content))
    tracked_key = _canonical_foreshadowing_key(_strip_foreshadowing_ref_prefix(tracked_content))
    if len(candidate_key) < 8 or len(tracked_key) < 8:
        return False
    if candidate_key == tracked_key or candidate_key in tracked_key or tracked_key in candidate_key:
        return True

    similarity = SequenceMatcher(None, candidate_key, tracked_key).ratio()
    if similarity >= 0.62:
        return True

    candidate_group = _foreshadowing_promotion_group_key(candidate_content)
    tracked_group = _foreshadowing_promotion_group_key(tracked_content)
    if candidate_group != tracked_group or candidate_group.startswith("misc_"):
        return False

    candidate_tokens = _semantic_content_tokens(candidate_content)
    tracked_tokens = _semantic_content_tokens(tracked_content)
    shared_tokens = {
        token
        for token in candidate_tokens & tracked_tokens
        if len(token) >= 4 or any("\u4e00" <= char <= "\u9fff" for char in token)
    }
    return len(shared_tokens) >= 1 and similarity >= 0.35


def _explicit_foreshadowing_refs(content: str) -> list[str]:
    refs = []
    for match in re.findall(r"(?<![A-Za-z0-9])F\d{3,}(?![A-Za-z0-9])", str(content or ""), flags=re.IGNORECASE):
        ref = match.upper()
        if ref not in refs:
            refs.append(ref)
    return refs


def _tracked_foreshadowing_id_for_thread_content(registry: dict, content: str) -> str:
    explicit_refs = set(_explicit_foreshadowing_refs(content))
    if explicit_refs:
        tracked_refs = [
            str(item.get("linked_foreshadowing_id") or "")
            for item in registry.get("items", [])
            if item.get("thread_type") == "foreshadowing"
            and str(item.get("linked_foreshadowing_id") or "").upper() in explicit_refs
        ]
        if tracked_refs:
            return ",".join(sorted(set(tracked_refs)))
        return ",".join(sorted(explicit_refs))

    for item in registry.get("items", []):
        if item.get("thread_type") != "foreshadowing" or not item.get("linked_foreshadowing_id"):
            continue
        if _looks_like_same_tracked_thread(content, item.get("content", "")):
            return str(item.get("linked_foreshadowing_id") or "")
    return ""


def _compile_foreshadowing_candidate_promotions(registry: dict) -> list[dict]:
    promotions = []
    already_tracked_count = 0
    for item in registry.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("thread_type") == "foreshadowing" or item.get("linked_foreshadowing_id"):
            continue
        already_tracked_as = _tracked_foreshadowing_id_for_thread_content(registry, item.get("content", ""))
        if already_tracked_as:
            item["already_tracked_as"] = already_tracked_as
            item["promotion_review_status"] = "already_tracked"
            already_tracked_count += 1
            continue
        if not _thread_needs_foreshadowing_promotion_review(item):
            continue
        promotions.append(
            {
                "promotion_id": f"P{len(promotions) + 1:03d}",
                "source_thread_id": item.get("id"),
                "source_thread_type": item.get("thread_type"),
                "content": item.get("content", ""),
                "reason": "wide_narrative_thread_may_need_strict_foreshadowing_tracking",
                "review_status": "needs_review",
                "evidence": item.get("evidence", []),
            }
        )
    registry["already_tracked_candidate_count"] = already_tracked_count
    return promotions


def _foreshadowing_promotion_group_key(content: str) -> str:
    text = str(content or "").lower()
    if "尼伯龙根计划" in text or "nibelungen plan" in text:
        return "nibelungen_plan"
    if ("胚胎" in text or "embryo" in text) and (
        "领域" in text or "电子" in text or "干扰" in text or "domain" in text
    ):
        return "dragon_embryo_domain"
    if "猛鬼众" in text and ("蛇岐八家" in text or "影子" in text or "同胞" in text):
        return "organization_shadow_identity"
    if "白王" in text and ("契约" in text or "蛇岐八家" in text or "污染" in text):
        return "white_king_bloodline_origin"
    if ("活灵" in text or "暴怒" in text) and ("剑" in text or "武器" in text):
        return "living_weapon_rule"
    if ("风间琉璃" in text or "源稚生" in text) and ("血统" in text or "药物" in text or "纯度" in text):
        return "individual_bloodline_risk"
    if "爆血" in text or "血统" in text or "bloodline" in text:
        return "bloodline_risk"
    if "尼伯龙根" in text or "nibelungen" in text or "nibelung" in text:
        return "nibelungen_space"
    if "芬里厄" in text or "耶梦加得" in text or "龙王" in text or "dragon king" in text:
        return "dragon_king_identity"
    if "奥丁" in text or "odin" in text:
        return "odin_mystery"
    if "校董会" in text or "家族" in text or "board" in text or "family" in text:
        return "institutional_power"
    key = _canonical_foreshadowing_key(content)
    return f"misc_{key[:24] or 'unknown'}"


def _foreshadowing_promotion_group_label(group_key: str) -> str:
    return {
        "nibelungen_plan": "Nibelungen plan / bloodline program",
        "dragon_embryo_domain": "Dragon embryo domain / interference rule",
        "organization_shadow_identity": "Shadow organization identity",
        "white_king_bloodline_origin": "White king contract / bloodline origin",
        "living_weapon_rule": "Living weapon rule",
        "individual_bloodline_risk": "Individual bloodline escalation",
        "bloodline_risk": "Bloodline risk / unstable power",
        "nibelungen_space": "Nibelungen space / hidden dimension",
        "dragon_king_identity": "Dragon king identity / ancient being",
        "odin_mystery": "Odin mystery / mythic threat",
        "institutional_power": "Institutional or family power conflict",
    }.get(group_key, group_key)


def _compile_foreshadowing_promotion_groups(promotions: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    ordered_keys: list[str] = []
    for promotion in promotions:
        group_key = _foreshadowing_promotion_group_key(str(promotion.get("content") or ""))
        if group_key not in groups:
            ordered_keys.append(group_key)
            groups[group_key] = {
                "group_id": f"PG{len(ordered_keys):03d}",
                "group_key": group_key,
                "group_label": _foreshadowing_promotion_group_label(group_key),
                "review_status": "needs_review",
                "candidate_count": 0,
                "promotion_ids": [],
                "source_thread_ids": [],
                "source_thread_types": [],
                "representative_content": promotion.get("content", ""),
                "candidates": [],
            }
        group = groups[group_key]
        group["candidate_count"] += 1
        if promotion.get("promotion_id") not in group["promotion_ids"]:
            group["promotion_ids"].append(promotion.get("promotion_id"))
        if promotion.get("source_thread_id") not in group["source_thread_ids"]:
            group["source_thread_ids"].append(promotion.get("source_thread_id"))
        if promotion.get("source_thread_type") not in group["source_thread_types"]:
            group["source_thread_types"].append(promotion.get("source_thread_type"))
        group["candidates"].append(promotion)
    return [groups[key] for key in ordered_keys]


def _compile_narrative_thread_registry(
    book_framework: dict,
    arcs: list[dict],
    chapters: list[dict],
    foreshadowing_registry: dict | None,
) -> dict:
    registry = _empty_narrative_thread_registry()
    for item in (foreshadowing_registry or {}).get("items", []) if isinstance(foreshadowing_registry, dict) else []:
        _add_narrative_thread(
            registry,
            thread_type="foreshadowing",
            content=item.get("canonical_content") or item.get("content") or "",
            status=item.get("status", "planted"),
            source="foreshadowing_registry",
            linked_foreshadowing_id=str(item.get("id") or ""),
            evidence=[
                {
                    "chapter_number": item.get("planted_chapter"),
                    "role": "planted",
                }
            ],
        )

    for chapter in chapters or []:
        chapter_number = chapter.get("chapter_number")
        report = chapter.get("analysis_report") or {}
        for release in _information_release_entries(report):
            content = str(release.get("content") or "").strip()
            hint = str(release.get("info_type") or release.get("reveal_method") or "")
            _add_narrative_thread(
                registry,
                thread_type=_classify_narrative_thread(content, hint),
                content=content,
                status="partially_resolved" if _looks_like_long_horizon_reveal(content) else "planted",
                source="chapter_information_release",
                evidence=[{"chapter_number": chapter_number, "role": "information_release"}],
            )
        analysis = report.get("chapter_analysis") or {}
        for field_name, default_type in (
            ("character_arc", "character_arc_pattern"),
            ("relationship_changes", "relationship_debt"),
            ("world_facts_added", "world_rule_reveal"),
        ):
            for raw_item in analysis.get(field_name, []) or []:
                content = json.dumps(raw_item, ensure_ascii=False) if isinstance(raw_item, dict) else str(raw_item or "")
                _add_narrative_thread(
                    registry,
                    thread_type=default_type,
                    content=content,
                    status="planted",
                    source=f"chapter_{field_name}",
                    evidence=[{"chapter_number": chapter_number, "role": field_name}],
                )

    for source_name, value in (
        ("book_imagery_system", book_framework.get("imagery_system") if isinstance(book_framework, dict) else None),
        ("book_theme", book_framework.get("book_theme") if isinstance(book_framework, dict) else None),
    ):
        if not value:
            continue
        content = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        thread_type = _classify_narrative_thread(content, source_name)
        if thread_type in {"motif_symbol", "mystery", "world_rule_reveal"}:
            _add_narrative_thread(
                registry,
                thread_type=thread_type,
                content=content,
                status="planted",
                source=source_name,
                evidence=[],
            )

    registry = _refresh_narrative_thread_counts(registry)
    return apply_promotion_gate(registry)


_SOURCE_TERM_SEEDS = (
    "show me the flowers",
    "show me the money",
    "卡塞尔学院",
    "卡塞尔",
    "龙族",
    "青铜城",
    "龙王",
    "路鸣泽",
    "康斯坦丁",
    "black sheep wall",
    "EVA",
    "白帝城",
    "七宗罪",
    "诺顿",
    "老唐",
    "奥丁",
    "尼伯龙根计划",
    "尼伯龙根",
    "耶梦加得",
    "大地与山之王",
    "黑王",
    "白王",
)

_SOURCE_TERM_OBJECT_TERMS = (
    "七宗罪",
    "贤者之石",
    "龙骨",
)

_SOURCE_TERM_SLOGAN_PREFIXES = (
    "show me ",
)

_SOURCE_TERM_SUFFIXES = (
    "学院",
    "城市",
    "计划",
    "组织",
    "家族",
    "城",
    "族",
    "王",
    "罪",
)

_GENERIC_SOURCE_TERM_STOPWORDS = {
    "主角",
    "角色",
    "读者",
    "故事",
    "小说",
    "章节",
    "弧段",
    "危机",
    "任务",
    "事件",
    "地图",
}

_ASCII_SOURCE_TERM_EDGE_STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "but",
    "for",
    "from",
    "in",
    "into",
    "me",
    "my",
    "not",
    "of",
    "on",
    "our",
    "the",
    "their",
    "to",
    "with",
    "your",
}


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _is_partial_ascii_source_term(term: str, all_terms: set[str]) -> bool:
    if term in _SOURCE_TERM_SEEDS:
        return False
    if not _is_ascii_term(term):
        return False
    normalized = re.sub(r"\s+", " ", term.strip().lower())
    words = normalized.split()
    if len(words) < 2:
        return True
    if words[0] in _ASCII_SOURCE_TERM_EDGE_STOPWORDS or words[-1] in _ASCII_SOURCE_TERM_EDGE_STOPWORDS:
        return True
    for other in all_terms:
        other_normalized = re.sub(r"\s+", " ", str(other or "").strip().lower())
        if other_normalized == normalized or not _is_ascii_term(other_normalized):
            continue
        if len(other_normalized.split()) < 2:
            continue
        if (
            other_normalized.startswith(normalized + " ")
            or other_normalized.endswith(" " + normalized)
            or normalized.startswith(other_normalized + " ")
            or normalized.endswith(" " + other_normalized)
        ):
            return True
    return False


def _classify_source_term(term: str) -> str:
    normalized = re.sub(r"\s+", " ", str(term or "").strip().lower())
    if any(normalized.startswith(prefix) for prefix in _SOURCE_TERM_SLOGAN_PREFIXES):
        return "slogan_or_quote"
    if any(object_term in str(term or "") for object_term in _SOURCE_TERM_OBJECT_TERMS):
        return "object_term"
    return "world_term"


def _entity_aliases(name: str) -> list[str]:
    raw = str(name or "").strip()
    if not raw:
        return []
    aliases = [raw]
    for part in re.split(r"[/、,，|]", raw):
        part = part.strip()
        if part and part not in aliases:
            aliases.append(part)
    return aliases


def _collect_generation_entities(book_framework: dict, arcs: list[dict], chapters: list[dict]) -> dict[str, str]:
    names: list[str] = []

    def add(name: str) -> None:
        name = str(name or "").strip()
        if name and name not in names:
            names.append(name)

    for name in (book_framework.get("complete_character_arcs") or {}).keys():
        add(name)
    for arc in arcs:
        for name in (arc.get("character_arcs_in_arc") or {}).keys():
            add(name)
    for chapter in chapters:
        report = chapter.get("analysis_report") or {}
        analysis = report.get("chapter_analysis") or {}
        for field in ("character_desire", "character_arc"):
            for item in analysis.get(field, []) or []:
                if isinstance(item, dict):
                    add(item.get("character"))
        for name in (analysis.get("character_state_after") or {}).keys():
            add(name)

    entity_map: dict[str, str] = {}
    for index, name in enumerate(names, start=1):
        placeholder = f"CHARACTER_{index:02d}"
        for alias in _entity_aliases(name):
            entity_map.setdefault(alias, placeholder)
    return entity_map


def _all_profile_source_text(
    book_framework: dict,
    arcs: list[dict],
    chapters: list[dict],
    foreshadowing_registry: dict | None = None,
) -> str:
    return json.dumps(
        {
            "book_framework": book_framework,
            "arcs": arcs,
            "chapters": chapters,
            "foreshadowing_registry": foreshadowing_registry or {},
        },
        ensure_ascii=False,
    )


def _collect_source_terms(
    book_framework: dict,
    arcs: list[dict],
    chapters: list[dict],
    entity_map: dict[str, str],
    foreshadowing_registry: dict | None = None,
) -> dict[str, str]:
    text = _all_profile_source_text(book_framework, arcs, chapters, foreshadowing_registry)
    terms: set[str] = set()
    lowered_text = text.lower()

    for seed in _SOURCE_TERM_SEEDS:
        if seed and (seed in text or seed.lower() in lowered_text):
            terms.add(seed)

    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9]+(?:\s+[A-Za-z][A-Za-z0-9]+)+\b", text):
        phrase = match.group(0).strip()
        if len(phrase) >= 6 and phrase == phrase.lower():
            terms.add(phrase)

    for name in entity_map:
        terms.discard(name)
    filtered = sorted(
        (term for term in terms if term and not _is_partial_ascii_source_term(term, terms)),
        key=lambda term: (-len(term), term),
    )
    return {term: f"SOURCE_TERM_{index:02d}" for index, term in enumerate(filtered, start=1)}


def _is_ascii_term(term: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)*", term or ""))


def _replace_dename_term(text: str, term: str, placeholder: str) -> str:
    if not term:
        return text
    if _is_ascii_term(term):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        return re.sub(pattern, placeholder, text, flags=re.IGNORECASE)
    return text.replace(term, placeholder)


def _dename_value(value, entity_map: dict[str, str], source_term_map: dict[str, str] | None = None):
    if isinstance(value, str):
        output = value
        combined = {**(source_term_map or {}), **entity_map}
        for name, placeholder in sorted(combined.items(), key=lambda item: len(item[0]), reverse=True):
            output = _replace_dename_term(output, name, placeholder)
        return output
    if isinstance(value, list):
        return [_dename_value(item, entity_map, source_term_map) for item in value]
    if isinstance(value, dict):
        return {key: _dename_value(item, entity_map, source_term_map) for key, item in value.items()}
    return value


def _chapter_blueprint_from_bundle_chapter(
    chapter: dict,
    entity_map: dict[str, str],
    source_term_map: dict[str, str] | None = None,
) -> dict:
    framework = chapter.get("framework_package") or {}
    built = (framework.get("built_chapter_frameworks") or [{}])[0]
    modules = []
    for module in built.get("modules", []) or []:
        modules.append(
            {
                "module_id": module.get("module_id", ""),
                "content": _dename_value(module.get("content", ""), entity_map, source_term_map),
            }
        )
    return {
        "chapter_number": chapter.get("chapter_number"),
        "source_chapter_range": chapter.get("source_chapter_range") or chapter.get("original_chapter_index"),
        "macro_components": built.get("linked_macro_component_ids", []),
        "modules": modules,
    }


def _arc_macro_list(arc: dict) -> list[str]:
    macros = arc.get("arc_macros") or []
    if isinstance(macros, str):
        macros = [macros]
    return [str(macro) for macro in macros if macro]


def _macro_order_for_arc(arc: dict) -> int:
    macros = _arc_macro_list(arc)
    orders = [
        int((_MACRO_DEFS.get(macro) or {}).get("order") or 99)
        for macro in macros
    ]
    return min(orders) if orders else 99


def _major_stage_for_arc(arc: dict) -> str:
    order = _macro_order_for_arc(arc)
    if order <= 2:
        return "opening_and_inciting"
    if order == 3:
        return "development_and_escalation"
    if order == 4:
        return "crisis_and_climax"
    if order == 5:
        return "resolution_and_aftermath"
    return "structural_progression"


def _parse_range_endpoints(range_text: str) -> tuple[int | None, int | None]:
    numbers = [int(value) for value in re.findall(r"\d+", str(range_text or ""))]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return numbers[0], numbers[-1]


def _combine_range(range_values: list[str]) -> str:
    starts: list[int] = []
    ends: list[int] = []
    for value in range_values:
        start, end = _parse_range_endpoints(value)
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
    if not starts or not ends:
        return ""
    return f"{min(starts)}-{max(ends)}"


def _chunk_arc_groups(arcs: list[dict], target_group_count: int) -> list[list[dict]]:
    if not arcs:
        return []
    target = max(1, min(target_group_count, len(arcs)))
    groups: list[list[dict]] = []
    for index in range(target):
        start = round(index * len(arcs) / target)
        end = round((index + 1) * len(arcs) / target)
        if start < end:
            groups.append(arcs[start:end])
    return groups


def _phase_arc_groups(arcs: list[dict]) -> list[list[dict]]:
    sorted_arcs = sorted(arcs, key=lambda item: int(item.get("arc_index") or 0))
    total = len(sorted_arcs)
    if total >= 10:
        phase_end_ratios = (0.18, 0.42, 0.75, 0.92)
    elif total >= 6:
        phase_end_ratios = (0.25, 0.50, 0.83)
    else:
        return _chunk_arc_groups(sorted_arcs, min(3, total))

    ends: list[int] = []
    for ratio in phase_end_ratios:
        end = int(round(total * ratio))
        end = max(1, min(total - 1, end))
        if not ends or end > ends[-1]:
            ends.append(end)
    ends.append(total)

    groups: list[list[dict]] = []
    start = 0
    for end in ends:
        if start < end:
            groups.append(sorted_arcs[start:end])
        start = end
    return groups


def _major_arc_groups(arcs: list[dict]) -> list[list[dict]]:
    if not arcs:
        return []
    if len(arcs) >= 10:
        return _phase_arc_groups(arcs)
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_stage = ""
    for arc in sorted(arcs, key=lambda item: int(item.get("arc_index") or 0)):
        stage = _major_stage_for_arc(arc)
        if current and stage != current_stage:
            groups.append(current)
            current = []
        current.append(arc)
        current_stage = stage
    if current:
        groups.append(current)

    if 3 <= len(groups) <= 5:
        return groups
    if len(arcs) < 3:
        return groups
    target = min(4, len(arcs)) if len(groups) < 3 else 5
    return _chunk_arc_groups(sorted(arcs, key=lambda item: int(item.get("arc_index") or 0)), target)


def _dominant_stage_for_group(group: list[dict], group_index: int, total_groups: int) -> str:
    if total_groups > 1 and group_index == 1:
        return "opening_and_inciting"
    if total_groups > 1 and group_index == total_groups:
        return "resolution_and_aftermath"

    macro_set = {macro for arc in group for macro in _arc_macro_list(arc)}
    group_text = " ".join(
        str(arc.get(field) or "")
        for arc in group
        for field in ("arc_title", "arc_summary", "arc_turning_point")
    )
    group_text_lower = group_text.lower()
    climax_keywords = (
        "高潮",
        "觉醒",
        "复活",
        "契约",
        "七宗罪",
        "决战",
        "牺牲",
        "climax",
        "awakening",
        "contract",
        "sacrifice",
        "showdown",
    )
    if total_groups >= 5 and group_index == 2 and "macro_development_escalation" in macro_set:
        return "development_and_escalation"
    if "macro_crisis_local_climax" in macro_set and any(keyword.lower() in group_text_lower for keyword in climax_keywords):
        return "crisis_and_climax"
    if "macro_development_escalation" in macro_set:
        return "development_and_escalation"
    if "macro_crisis_local_climax" in macro_set:
        return "crisis_and_climax"
    if "macro_inciting_incident" in macro_set:
        return "opening_and_inciting"
    if "macro_resolution_aftermath" in macro_set:
        return "resolution_and_aftermath"
    return _major_stage_for_arc(group[0]) if group else "structural_progression"


def _compile_arc_hierarchy(arcs: list[dict]) -> dict:
    sorted_arcs = sorted(arcs or [], key=lambda item: int(item.get("arc_index") or 0))
    groups = _major_arc_groups(sorted_arcs)
    major_by_arc_index: dict[int, str] = {}
    major_arcs = []
    for major_index, group in enumerate(groups, start=1):
        major_id = f"major_arc_{major_index:03d}"
        for arc in group:
            try:
                major_by_arc_index[int(arc.get("arc_index") or 0)] = major_id
            except (TypeError, ValueError):
                continue
        titles = [str(arc.get("arc_title") or f"Arc {arc.get('arc_index')}") for arc in group]
        macros = []
        for arc in group:
            for macro in _arc_macro_list(arc):
                if macro not in macros:
                    macros.append(macro)
        source_ranges = [str(arc.get("source_chapter_range") or arc.get("arc_chapter_range") or "") for arc in group]
        analysis_ranges = [str(arc.get("analysis_unit_range") or arc.get("arc_chapter_range") or "") for arc in group]
        major_arcs.append(
            {
                "major_arc_id": major_id,
                "major_arc_index": major_index,
                "major_arc_title": titles[0] if len(titles) == 1 else f"{titles[0]} / {titles[-1]}",
                "dominant_stage": _dominant_stage_for_group(group, major_index, len(groups)),
                "source_chapter_range": _combine_range(source_ranges),
                "analysis_unit_range": _combine_range(analysis_ranges),
                "sub_arc_ids": [f"sub_arc_{int(arc.get('arc_index') or offset):03d}" for offset, arc in enumerate(group, start=1)],
                "macro_components": macros,
                "pacing_summary": " / ".join(str(arc.get("arc_pacing") or "") for arc in group if arc.get("arc_pacing")),
                "turning_points": [
                    {
                        "sub_arc_id": f"sub_arc_{int(arc.get('arc_index') or offset):03d}",
                        "turning_point": arc.get("arc_turning_point", ""),
                    }
                    for offset, arc in enumerate(group, start=1)
                ],
                "emotion_curve": [
                    emotion
                    for arc in group
                    for emotion in (arc.get("arc_emotion_curve") or [])
                ],
            }
        )

    sub_arcs = []
    for offset, arc in enumerate(sorted_arcs, start=1):
        try:
            arc_index = int(arc.get("arc_index") or offset)
        except (TypeError, ValueError):
            arc_index = offset
        sub_arcs.append(
            {
                "sub_arc_id": f"sub_arc_{arc_index:03d}",
                "sub_arc_index": arc_index,
                "major_arc_id": major_by_arc_index.get(arc_index, "major_arc_001"),
                "arc_title": arc.get("arc_title", ""),
                "source_chapter_range": arc.get("source_chapter_range") or arc.get("arc_chapter_range", ""),
                "analysis_unit_range": arc.get("analysis_unit_range") or arc.get("arc_chapter_range", ""),
                "macro_components": _arc_macro_list(arc),
                "pacing": arc.get("arc_pacing", ""),
                "turning_point": arc.get("arc_turning_point", ""),
                "emotion_curve": arc.get("arc_emotion_curve", []),
            }
        )

    return {
        "schema_version": "book_analyzer_v2.arc_hierarchy.v1",
        "major_arcs": major_arcs,
        "sub_arcs": sub_arcs,
    }


def _compile_hybrid_module_packs(
    book_framework: dict,
    arcs: list[dict],
    chapters: list[dict],
    foreshadowing_registry: dict | None,
    narrative_thread_registry: dict | None,
    source_term_map: dict[str, str],
) -> dict:
    character_arcs = book_framework.get("complete_character_arcs") or {}
    registry_items = (foreshadowing_registry or {}).get("items", []) if isinstance(foreshadowing_registry, dict) else []
    thread_items = (narrative_thread_registry or {}).get("items", []) if isinstance(narrative_thread_registry, dict) else []
    promotion_candidates = (
        (narrative_thread_registry or {}).get("foreshadowing_candidate_promotions", [])
        if isinstance(narrative_thread_registry, dict)
        else []
    )
    promotion_groups = (
        (narrative_thread_registry or {}).get("promotion_review_groups", [])
        or (narrative_thread_registry or {}).get("foreshadowing_promotion_groups", [])
        if isinstance(narrative_thread_registry, dict)
        else []
    )
    source_term_entries = [
        {
            "source_term": term,
            "placeholder": placeholder,
            "term_type": _classify_source_term(term),
        }
        for term, placeholder in sorted(source_term_map.items(), key=lambda item: item[1])
    ]
    candidate_mechanics_entries = [
        {
            "id": item.get("id"),
            "content": item.get("canonical_content", ""),
            "status": item.get("status", "planted"),
            "tracking_scope": item.get("tracking_scope", _infer_foreshadowing_tracking_scope(item)),
            "memory_lane": item.get("memory_lane", _infer_foreshadowing_memory_lane(item)),
        }
        for item in registry_items
    ]
    memory_lane_counts = {lane: 0 for lane in sorted(_FORESHADOWING_MEMORY_LANES)}
    for item in candidate_mechanics_entries:
        lane = item.get("memory_lane")
        if lane in memory_lane_counts:
            memory_lane_counts[lane] += 1
    return {
        "worldbuilding_module": {
            "purpose": "reuse selected source setting/world-rule materials while allowing substitution",
            "source_terms": source_term_entries,
            "world_terms": [item for item in source_term_entries if item["term_type"] == "world_term"],
            "object_terms": [item for item in source_term_entries if item["term_type"] == "object_term"],
            "slogan_or_quote_terms": [item for item in source_term_entries if item["term_type"] == "slogan_or_quote"],
            "imagery_system": book_framework.get("imagery_system", {}),
        },
        "relationship_network_module": {
            "purpose": "reuse relationship roles and character-position patterns",
            "character_arcs": character_arcs,
            "relationship_sources": [
                {
                    "chapter_number": chapter.get("chapter_number"),
                    "character_state_after": ((chapter.get("analysis_report") or {}).get("chapter_analysis") or {}).get(
                        "character_state_after",
                        {},
                    ),
                }
                for chapter in chapters
            ],
        },
        "core_conflict_module": {
            "purpose": "reuse source conflict shape without forcing full continuation",
            "book_theme": book_framework.get("book_theme") or book_framework.get("theme_proposition", ""),
            "structural_pattern": book_framework.get("structural_pattern", ""),
            "arc_turning_points": [
                {
                    "arc_index": arc.get("arc_index"),
                    "source_chapter_range": arc.get("source_chapter_range") or arc.get("arc_chapter_range"),
                    "turning_point": arc.get("arc_turning_point", ""),
                }
                for arc in arcs
            ],
        },
        "power_item_system_module": {
            "purpose": "reuse selected rules, tools, abilities, clues, and payoff objects",
            "foreshadowing_registry": foreshadowing_registry or {},
            "candidate_mechanics": candidate_mechanics_entries,
            "memory_lane_counts": memory_lane_counts,
            "strict_foreshadowing_items": [
                item for item in candidate_mechanics_entries if item.get("memory_lane") == "strict_foreshadowing"
            ],
        },
        "narrative_thread_module": {
            "purpose": "reuse or continue long-horizon mysteries, relationship debts, world rules, motifs, and strict foreshadowing items",
            "narrative_thread_registry_ref": _narrative_thread_registry_ref(narrative_thread_registry or {}),
            "foreshadowing_candidate_promotions": promotion_candidates,
            "foreshadowing_promotion_groups": promotion_groups,
            "promotion_review_groups": promotion_groups,
            "suppressed_promotion_candidates": (narrative_thread_registry or {}).get(
                "suppressed_promotion_candidates", []
            )
            if isinstance(narrative_thread_registry, dict)
            else [],
            "candidate_threads": [
                {
                    "id": item.get("id"),
                    "thread_type": item.get("thread_type"),
                    "content": item.get("content", ""),
                    "status": item.get("status", "planted"),
                    "linked_foreshadowing_id": item.get("linked_foreshadowing_id", ""),
                }
                for item in thread_items
            ],
        },
        "emotional_rhythm_module": {
            "purpose": "reuse affective pacing independently from concrete plot",
            "narrative_rhythm": book_framework.get("narrative_rhythm", ""),
            "arc_emotion_curves": [
                {
                    "arc_index": arc.get("arc_index"),
                    "source_chapter_range": arc.get("source_chapter_range") or arc.get("arc_chapter_range"),
                    "emotion_curve": arc.get("arc_emotion_curve", []),
                    "pacing": arc.get("arc_pacing", ""),
                }
                for arc in arcs
            ],
        },
    }


def _compile_generation_profiles(
    book_framework: dict,
    arcs: list[dict],
    chapters: list[dict],
    foreshadowing_registry: dict | None = None,
    narrative_thread_registry: dict | None = None,
) -> dict:
    entity_map = _collect_generation_entities(book_framework, arcs, chapters)
    source_term_map = _collect_source_terms(
        book_framework,
        arcs,
        chapters,
        entity_map,
        foreshadowing_registry,
    )
    arc_hierarchy = _compile_arc_hierarchy(arcs)
    structure_only = build_structure_only_profile(
        book_framework=book_framework,
        arcs=arcs,
        chapters=chapters,
        arc_hierarchy=arc_hierarchy,
        character_map=entity_map,
        foreshadowing_registry=foreshadowing_registry,
        narrative_thread_registry=narrative_thread_registry,
    )
    source_entity_inventory = structure_only.pop("_source_entity_inventory", {})
    hybrid_module_packs = _compile_hybrid_module_packs(
        book_framework,
        arcs,
        chapters,
        foreshadowing_registry,
        narrative_thread_registry,
        source_term_map,
    )
    return {
        "schema_version": "book_analyzer_v2.generation_profiles.v1",
        "arc_hierarchy": arc_hierarchy,
        "narrative_thread_registry_ref": _narrative_thread_registry_ref(narrative_thread_registry or {}),
        "source_entity_inventory": source_entity_inventory,
        "source_leak_report": structure_only.get("source_leak_report", {}),
        "abstract_mechanism_catalog": structure_only.get("abstract_mechanism_catalog", {}),
        "abstraction_quality_report": structure_only.get("abstraction_quality_report", {}),
        "usage_profiles": {
            "structure_only": structure_only,
            "source_story_continuation": {
                "profile_type": "source_story_continuation",
                "de_named": False,
                "book_framework": book_framework,
                "foreshadowing_registry": foreshadowing_registry or {},
                "narrative_thread_registry": narrative_thread_registry or {},
            },
            "hybrid_adaptation": {
                "profile_type": "hybrid_adaptation",
                "de_named": False,
                "structure_profile_ref": "structure_only",
                "selectable_modules": [
                    "rhythm_framework",
                    "arc_blueprint",
                    "arc_hierarchy.major_arcs",
                    "arc_hierarchy.sub_arcs",
                    "chapter_blueprint",
                    "character_arc_patterns",
                    "module_packs.worldbuilding_module",
                    "module_packs.relationship_network_module",
                    "module_packs.core_conflict_module",
                    "module_packs.power_item_system_module",
                    "module_packs.narrative_thread_module",
                    "module_packs.emotional_rhythm_module",
                ],
                "module_packs": hybrid_module_packs,
            },
        },
    }


def _expand_long_chapter_parts(chapters: list[dict]) -> list[dict]:
    from story_analyzer_v1.ingestion.source_manifest_builder import (
        MAX_ANALYSIS_UNIT_CHARS,
        split_text_part_spans,
    )

    expanded: list[dict] = []
    for original_index, chapter in enumerate(chapters, start=1):
        text = chapter["text"].strip()
        title = chapter["title"]
        spans = split_text_part_spans(text, max_chars=MAX_ANALYSIS_UNIT_CHARS)
        if len(spans) == 1:
            enriched = dict(chapter)
            enriched.setdefault("original_chapter_index", original_index)
            enriched.setdefault("original_title", title)
            expanded.append(enriched)
            continue

        for part_index, (part_text, part_start, part_end) in enumerate(spans, start=1):
            enriched = dict(chapter)
            enriched.update(
                {
                    "title": f"{title} part {part_index:02d}",
                    "text": part_text,
                    "original_chapter_index": original_index,
                    "original_title": title,
                    "part_index": part_index,
                    "part_count": len(spans),
                    "part_start_char": part_start,
                    "part_end_char": part_end,
                }
            )
            expanded.append(enriched)
    return expanded


def _call_llm_deepseek_legacy(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置。请复制 .env.example 为 .env，并在本地环境中设置真实密钥。")
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": temperature,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _normalize_model_provider(provider: str | None = None) -> str:
    selected = (
        provider
        or _ACTIVE_MODEL_PROVIDER
        or os.environ.get(MODEL_PROVIDER_ENV)
        or os.environ.get("ANALYZER_MODEL_PROVIDER")
        or DEFAULT_MODEL_PROVIDER
    )
    normalized = str(selected or "").strip().lower()
    if normalized not in SUPPORTED_MODEL_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_MODEL_PROVIDERS))
        raise ValueError(f"Unsupported story analyzer model provider: {selected!r}. Allowed: {allowed}")
    return normalized


def _select_qwen_api_key_env() -> str:
    explicit = os.environ.get("QWEN_API_KEY_ENV")
    if explicit:
        return explicit
    if os.environ.get(QWEN_API_KEY_ENV):
        return QWEN_API_KEY_ENV
    if os.environ.get(QWEN_DASHSCOPE_API_KEY_ENV):
        return QWEN_DASHSCOPE_API_KEY_ENV
    return QWEN_API_KEY_ENV


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def get_llm_runtime(provider: str | None = None) -> dict:
    provider_type = _normalize_model_provider(provider)
    if provider_type == "qwen":
        api_key_env = _select_qwen_api_key_env()
        return {
            "provider_type": "qwen",
            "model": os.environ.get("QWEN_MODEL_NAME", QWEN_MODEL),
            "base_url": os.environ.get("QWEN_BASE_URL", QWEN_BASE_URL).rstrip("/"),
            "api_key_env": api_key_env,
            "api_key_configured": bool(os.environ.get(api_key_env)),
            "max_tokens": int(os.environ.get("QWEN_MAX_TOKENS", QWEN_MAX_TOKENS)),
        }
    return {
        "provider_type": "deepseek",
        "model": DEEPSEEK_MODEL,
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL).rstrip("/"),
        "api_key_env": DEEPSEEK_API_KEY_ENV,
        "api_key_configured": bool(os.environ.get(DEEPSEEK_API_KEY_ENV)),
        "max_tokens": None,
    }


def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    provider: str | None = None,
    stage: str = "llm_call",
    target_id: str = "unknown",
    prompt_version: str = "legacy",
) -> str:
    runtime = get_llm_runtime(provider)
    if runtime["provider_type"] == "qwen":
        system_prompt = (
            system_prompt
            + "\n\n【Qwen JSON 输出约束】必须输出一个完整 JSON 对象；不要输出 markdown；"
            "不要省略尾部字段；如果内容很长，压缩文字长度而不是截断 JSON。"
        )
    api_key_env = runtime["api_key_env"]
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise RuntimeError(
            f"{api_key_env} is not configured. Copy .env.example to .env and set a real key, "
            "or enter a temporary key in the web UI."
        )
    url = _chat_completions_url(runtime["base_url"])
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": runtime["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": temperature,
    }
    if runtime.get("max_tokens"):
        payload["max_tokens"] = runtime["max_tokens"]
    started_at = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice["message"]["content"]
    except Exception as exc:
        if _ACTIVE_LLM_CALL_LOGGER is not None:
            _ACTIVE_LLM_CALL_LOGGER.record_call(
                stage=stage,
                target_id=target_id,
                provider=runtime["provider_type"],
                model=runtime["model"],
                base_url=runtime["base_url"],
                api_key_env=api_key_env,
                prompt_version=prompt_version,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                request=payload,
                response={"received": False, "finish_reason": "unknown", "raw_text": "", "json_parse_status": "failed"},
                error=str(exc),
                started_at=started_at,
                finished_at=time.time(),
            )
        raise
    if _ACTIVE_LLM_CALL_LOGGER is not None:
        _ACTIVE_LLM_CALL_LOGGER.record_call(
            stage=stage,
            target_id=target_id,
            provider=runtime["provider_type"],
            model=runtime["model"],
            base_url=runtime["base_url"],
            api_key_env=api_key_env,
            prompt_version=prompt_version,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            request=payload,
            response={
                "received": True,
                "finish_reason": finish_reason or "unknown",
                "raw_text": content,
                "json_parse_status": "unknown",
            },
            error=None,
            started_at=started_at,
            finished_at=time.time(),
        )
    if finish_reason in {"length", "max_tokens"}:
        raise RuntimeError(
            f"{runtime['provider_type']} output was truncated by max_tokens; "
            f"raise QWEN_MAX_TOKENS or reduce prompt size."
        )
    return content


def _call_llm_traced(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    provider: str | None = None,
    stage: str,
    target_id: str,
    prompt_version: str,
) -> str:
    try:
        return call_llm(
            system_prompt,
            user_prompt,
            temperature=temperature,
            provider=provider,
            stage=stage,
            target_id=target_id,
            prompt_version=prompt_version,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return call_llm(system_prompt, user_prompt, temperature=temperature, provider=provider)


_JSON_REPAIR_SYSTEM_PROMPT = (
    "You repair malformed JSON returned by a story analysis model. "
    "Return only one complete valid JSON object. Do not add markdown, comments, or explanations. "
    "Preserve all existing keys and values whenever possible. If a value is truncated, close the JSON "
    "with the smallest valid representation rather than inventing new story facts."
)


def _load_json_with_provider_repair(cleaned: str, label: str, provider: str | None = None) -> dict:
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as original_error:
        runtime = get_llm_runtime(provider)
        if runtime["provider_type"] != "qwen":
            raise RuntimeError(f"{label} JSON 解析失败: {original_error}\n内容片段: {cleaned[:400]}")

        repair_prompt = (
            f"The following {label} response should be valid JSON but failed to parse.\n"
            f"Parser error: {original_error}\n\n"
            "Repair it into a single complete JSON object. Output only JSON.\n\n"
            f"{cleaned}"
        )
        try:
            repaired_answer = _call_llm_traced(
                _JSON_REPAIR_SYSTEM_PROMPT,
                repair_prompt,
                temperature=0.0,
                provider=provider,
                stage="json_repair",
                target_id=label,
                prompt_version="json_repair_v1",
            )
            repaired = _extract_json(repaired_answer)
            if not repaired:
                raise RuntimeError("repair response did not contain JSON")
            return json.loads(repaired)
        except Exception as repair_error:
            raise RuntimeError(
                f"{label} JSON 解析失败，且 Qwen JSON 修复失败: {original_error}; "
                f"repair_error={repair_error}\n内容片段: {cleaned[:400]}"
            ) from repair_error


# ══════════════════════════════════════════════════════
# 章节层：调用 + 适配器
# ══════════════════════════════════════════════════════

def call_chapter_deepseek(
    text: str,
    chapter_number: int,
    chain: dict,
    provider: str | None = None,
) -> dict:
    """
    替代 call_workflow_a()，接口相同：
    返回 {"framework_package_json": ..., "analysis_report_json": ..., "next_chapter_pack": ...}
    """
    parts = [f"chapter_number: {chapter_number}"]
    if chain.get("previous_summary"):
        parts.append(f"\n【上章摘要】\n{chain['previous_summary']}")
    if chain.get("known_foreshadowing"):
        parts.append(f"\n【已知伏笔】\n{chain['known_foreshadowing']}")
    if chain.get("known_character_state"):
        parts.append(f"\n【角色状态】\n{chain['known_character_state']}")
    if chain.get("vocabulary_context"):
        parts.append(f"\n【词库参考】\n{chain['vocabulary_context']}")
    parts.append(f"\n\n【章节正文】\n{text}")

    answer  = _call_llm_traced(
        _CHAPTER_SYSTEM_PROMPT,
        "\n".join(parts),
        provider=provider,
        stage="chapter_analysis",
        target_id=f"chapter_{chapter_number:03d}",
        prompt_version="chapter_canonical_v1",
    )
    cleaned = _extract_json(answer)
    if not cleaned:
        raise RuntimeError(f"章节分析无 JSON 内容: {answer[:300]}")
    data = _load_json_with_provider_repair(cleaned, "章节", provider=provider)

    return _adapt_chapter_output(data, chapter_number)


def _adapt_chapter_output(data: dict, chapter_number: int) -> dict:
    """中间 JSON → framework_package_json + analysis_report_json + next_chapter_pack"""
    data = _strip_new_term_marker(data)
    ts  = datetime.datetime.now().isoformat()
    ch  = data.get("chapter", {})
    story = data.get("story_level", {})
    identified_macros = ch.get("identified_macros", ["macro_opening"])

    # ── framework_package ───────────────────────────
    macro_components = []
    for mid in identified_macros:
        defn = _MACRO_DEFS.get(mid, {})
        macro_components.append({
            "component_id":    mid,
            "component_label": defn.get("label", mid),
            "order":           defn.get("order", 0),
            "status":          "proposed",
        })

    modules = []
    for mod_id, mod_label, content in [
        ("chapter_function",   "篇章功能模块", ch.get("chapter_function", "")),
        ("reader_emotion",      "读者情绪模块", ch.get("reader_emotion", "")),
        ("character_desire",    "角色欲望模块", json.dumps(ch.get("character_desire", []), ensure_ascii=False)),
        ("character_arc",       "人物弧光模块", json.dumps(ch.get("character_arc", []), ensure_ascii=False)),
        ("conflict",            "冲突模块",     json.dumps(ch.get("conflict", []), ensure_ascii=False)),
        ("information_release", "信息释放模块", json.dumps(ch.get("information_release", []), ensure_ascii=False)),
        ("style_pacing",        "风格节奏模块", json.dumps(ch.get("style_pacing", {}), ensure_ascii=False)),
    ]:
        modules.append({
            "module_id":    mod_id,
            "module_label": mod_label,
            "content":      content,
            "build_status": "built",
        })

    framework_package = {
        "framework_package_id": f"fw_pkg_{chapter_number:03d}_{ts[:10].replace('-','')}",
        "project_id":           "local_project",
        "source":               "analyze_stories_v2",
        "language":             "zh",
        "constraint_strength":  "weak",
        "maturity":             "Analyzed",
        "macro_framework": {"components": macro_components},
        "component_vocabulary": {
            "macro_components": macro_components,
            "chapter_modules": [
                {"module_id": m["module_id"], "module_label": m["module_label"]}
                for m in modules
            ],
        },
        "chapter_macro_assignments": [{
            "chapter_index":              chapter_number,
            "linked_macro_component_ids": identified_macros,
            "assignment_type":            "analyze_stories_recommended",
            "status":                     "proposed",
            "reason":                     ch.get("macro_assignment_reason", ""),
        }],
        "built_chapter_frameworks": [{
            "chapter_framework_id":       f"chapter_fw_{chapter_number:03d}",
            "chapter_index":              chapter_number,
            "build_status":               "built",
            "user_intent_snapshot":       ch.get("summary", ""),
            "linked_macro_component_ids": identified_macros,
            "modules":                    modules,
            "created_at":                 ts,
            "updated_at":                 ts,
        }],
        "version_id": "v2",
    }

    # ── analysis_report ─────────────────────────────
    ext = {
        "叙事风格": {
            "视角":     data.get("narrative_style", {}).get("point_of_view", ""),
            "时态":     data.get("narrative_style", {}).get("tense", ""),
            "叙述距离": data.get("narrative_style", {}).get("narrative_distance", ""),
            "声音特征": data.get("narrative_style", {}).get("voice_characteristics", ""),
        },
        "意象与象征": [
            {"意象": s.get("symbol",""), "象征意义": s.get("meaning",""), "出现次数": s.get("occurrences",1)}
            for s in data.get("imagery_symbols", [])
        ],
        "类型标签": data.get("genre_tags", []),
        "角色关系网络": [
            {"角色A": r.get("character_a",""), "角色B": r.get("character_b",""),
             "关系类型": r.get("relation_type",""), "动态": r.get("dynamic","")}
            for r in data.get("character_relationships", [])
        ],
        "对话母题": [
            {"母题": m.get("motif",""), "场景": m.get("context",""), "意义": m.get("significance","")}
            for m in data.get("dialogue_motifs", [])
        ],
        "关键物件与场景": [
            {"名称": i.get("name",""), "类型": i.get("type",""), "象征意义": i.get("symbolic_meaning","")}
            for i in data.get("key_objects_scenes", [])
        ],
    }

    analysis_report = {
        "report_id":                   f"report_{chapter_number:03d}_{ts[:10].replace('-','')}",
        "analyzed_at":                 ts,
        "linked_framework_package_id": framework_package["framework_package_id"],
        "chapter_number":              chapter_number,
        "story_level":                 story,
        "chapter_analysis": {
            "chapter_index":      chapter_number,
            "title":              ch.get("title", f"第{chapter_number}章"),
            "summary":            ch.get("summary", ""),
            "identified_macros":  identified_macros,
            "macro_reason":       ch.get("macro_assignment_reason", ""),
            "plot_nodes":         ch.get("plot_nodes", []),
            "chapter_function":   ch.get("chapter_function", ""),
            "reader_emotion":     ch.get("reader_emotion", ""),
            "reader_emotion_intensity": ch.get("reader_emotion_intensity", 0.5),
            "character_desire":   ch.get("character_desire", []),
            "character_arc":      ch.get("character_arc", []),
            "conflict":           ch.get("conflict", []),
            "information_release": ch.get("information_release", []),
            "style_pacing":       ch.get("style_pacing", {}),
            "character_state_after": ch.get("character_state_after", {}),
        },
        "foreshadowing":        data.get("foreshadowing", []),
        "ending_revelations":   data.get("ending_revelations", []),
        "recommendation_notes": data.get("recommendation_notes", []),
        "扩展分析":             ext,
    }

    # ── next_chapter_pack ───────────────────────────
    open_fw = [f for f in data.get("foreshadowing", []) if f.get("status") != "resolved"]
    fw_lines = [f"{f['id']}：{f['content']} —— {f.get('status','planted')}" for f in open_fw]

    char_state = ch.get("character_state_after", {})
    cs_lines = [
        f"{name}：情绪={s.get('emotion','—')}，欲望强度={s.get('desire_level','—')}，关键变化={s.get('key_change','—')}"
        for name, s in char_state.items()
    ]

    next_chapter_pack = {
        "chapter_number":        chapter_number + 1,
        "known_foreshadowing":   "\n".join(fw_lines),
        "known_character_state": "\n".join(cs_lines),
        "previous_summary":      ch.get("summary", ""),
    }

    return {
        "framework_package_json": json.dumps(framework_package, ensure_ascii=False, indent=2),
        "analysis_report_json":   json.dumps(analysis_report,   ensure_ascii=False, indent=2),
        "next_chapter_pack":      json.dumps(next_chapter_pack,  ensure_ascii=False),
    }


# ══════════════════════════════════════════════════════
# 弧段层：DeepSeek 直调（替代 Workflow C）
# ══════════════════════════════════════════════════════

def _short_text(value, limit: int = ARC_TEXT_FIELD_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)].rstrip() + "...[truncated]"


def _short_list(value, limit: int = ARC_LIST_FIELD_LIMIT) -> list:
    items = value if isinstance(value, list) else []
    shortened = []
    for item in items[:limit]:
        if isinstance(item, dict):
            shortened.append(_compact_mapping(item, ARC_TEXT_FIELD_LIMIT // 2, 6))
        elif isinstance(item, list):
            shortened.append(_short_list(item, 5))
        else:
            shortened.append(_short_text(item, ARC_TEXT_FIELD_LIMIT // 2))
    if len(items) > limit:
        shortened.append(f"... {len(items) - limit} more")
    return shortened


def _compact_mapping(value, text_limit: int = ARC_TEXT_FIELD_LIMIT, item_limit: int = ARC_LIST_FIELD_LIMIT) -> dict:
    if not isinstance(value, dict):
        return {}
    compact = {}
    for key, item in value.items():
        if isinstance(item, str):
            compact[key] = _short_text(item, text_limit)
        elif isinstance(item, list):
            compact[key] = _short_list(item, item_limit)
        elif isinstance(item, dict):
            compact[key] = _compact_mapping(item, max(240, text_limit // 2), min(6, item_limit))
        else:
            compact[key] = item
    return compact


def _compact_chapter_package_for_arc(package: dict) -> dict:
    framework = package.get("framework_package") if isinstance(package, dict) else {}
    report = package.get("story_analysis_report") if isinstance(package, dict) else {}
    next_pack = package.get("next_chapter_pack") if isinstance(package, dict) else {}
    fw_chapter = (framework or {}).get("chapter_framework") or (framework or {}).get("chapter") or {}
    analysis = (report or {}).get("chapter_analysis") or (report or {}).get("chapter") or {}
    return {
        "chapter_number": package.get("chapter_number"),
        "analysis_unit_number": package.get("analysis_unit_number"),
        "source_chapter": package.get("source_chapter", {}),
        "title": analysis.get("title") or fw_chapter.get("title"),
        "summary": _short_text(analysis.get("summary") or fw_chapter.get("summary"), 1400),
        "chapter_function": _short_text(
            analysis.get("chapter_function") or fw_chapter.get("chapter_function"),
            600,
        ),
        "identified_macros": _short_list(
            analysis.get("identified_macros") or fw_chapter.get("identified_macros"),
            8,
        ),
        "plot_nodes": _short_list(analysis.get("plot_nodes") or fw_chapter.get("plot_nodes"), 10),
        "conflict": _short_list(analysis.get("conflict") or fw_chapter.get("conflict"), 8),
        "information_release": _short_list(
            analysis.get("information_release") or fw_chapter.get("information_release"),
            10,
        ),
        "character_arc": _short_list(analysis.get("character_arc") or fw_chapter.get("character_arc"), 10),
        "character_state_after": _compact_mapping(analysis.get("character_state_after") or {}, 420, 8),
        "foreshadowing_delta": _short_list((report or {}).get("foreshadowing") or [], 12),
        "style_pacing": _compact_mapping(analysis.get("style_pacing") or {}, 500, 6),
        "previous_summary": _short_text((next_pack or {}).get("previous_summary"), 800),
    }


def _compact_arc_chapter_packages(chapter_packages: list) -> list:
    compact = [_compact_chapter_package_for_arc(pkg) for pkg in chapter_packages]
    if len(json.dumps(compact, ensure_ascii=False)) <= ARC_PROMPT_CHAR_BUDGET:
        return compact
    for pkg in compact:
        pkg["summary"] = _short_text(pkg.get("summary"), 600)
        pkg["plot_nodes"] = _short_list(pkg.get("plot_nodes"), 5)
        pkg["conflict"] = _short_list(pkg.get("conflict"), 4)
        pkg["information_release"] = _short_list(pkg.get("information_release"), 5)
        pkg["character_arc"] = _short_list(pkg.get("character_arc"), 5)
        pkg["foreshadowing_delta"] = _short_list(pkg.get("foreshadowing_delta"), 6)
    return compact


def _fallback_arc_framework(
    chapter_packages: list,
    arc_index: int,
    arc_chapter_range: str,
    arc_metadata: dict,
    reason: str,
) -> dict:
    compact = _compact_arc_chapter_packages(chapter_packages)
    summaries = [pkg.get("summary", "") for pkg in compact if pkg.get("summary")]
    macros = []
    for pkg in compact:
        for macro in pkg.get("identified_macros") or []:
            if macro and macro not in macros:
                macros.append(macro)
    planted = []
    resolved = []
    still_open = []
    for pkg in compact:
        for item in pkg.get("foreshadowing_delta") or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").lower()
            entry = {
                "id": item.get("id", ""),
                "content": _short_text(item.get("content") or item.get("summary"), 500),
                "chapter": pkg.get("chapter_number"),
            }
            if "resolved" in status:
                resolved.append(entry)
            else:
                planted.append(entry)
                if entry["id"]:
                    still_open.append(entry["id"])
    start_title = compact[0].get("title") if compact else ""
    end_title = compact[-1].get("title") if compact else ""
    return {
        "arc_index": arc_index,
        "arc_chapter_range": arc_chapter_range,
        "arc_title": f"Arc {arc_index}: {start_title} -> {end_title}".strip(),
        "arc_theme": "fallback_from_chapter_frameworks",
        "arc_summary": _short_text(" / ".join(summaries), 1800),
        "arc_macros": macros[:12],
        "character_arcs_in_arc": {},
        "foreshadowing_summary": {
            "planted_in_arc": planted[:20],
            "resolved_in_arc": resolved[:20],
            "still_open": list(dict.fromkeys(still_open))[:40],
        },
        "arc_conflict_escalation": _short_text(
            " / ".join(
                str(item)
                for pkg in compact
                for item in (pkg.get("conflict") or [])[:2]
            ),
            1200,
        ),
        "arc_pacing": _short_text(
            " / ".join(
                str((pkg.get("style_pacing") or {}).get("pacing") or "")
                for pkg in compact
                if pkg.get("style_pacing")
            ),
            1000,
        ),
        "arc_turning_point": _short_text(
            (compact[-1].get("summary") if compact else "") or "fallback arc generated from chapter summaries",
            800,
        ),
        "arc_emotion_curve": [
            _short_text(pkg.get("chapter_function") or pkg.get("title"), 120)
            for pkg in compact[:8]
            if pkg.get("chapter_function") or pkg.get("title")
        ],
        "analysis_quality": "fallback",
        "fallback_reason": _short_text(reason, 1000),
        "fallback_source": "chapter_frameworks_after_arc_llm_failure",
        **{k: v for k, v in (arc_metadata or {}).items() if k not in {"start", "end"}},
    }


def call_arc_deepseek(
    chapter_packages: list,
    arc_index: int,
    arc_chapter_range: str,
    provider: str | None = None,
) -> dict:
    compact_packages = _compact_arc_chapter_packages(chapter_packages)
    user_prompt = (
        f"请分析以下弧段（第 {arc_index} 弧段，章节范围：{arc_chapter_range}）：\n\n"
        + json.dumps(compact_packages, ensure_ascii=False, indent=2)
        + "\n\n请按 JSON 格式输出弧段分析结果。"
    )
    answer  = _call_llm_traced(
        _ARC_SYSTEM_PROMPT,
        user_prompt,
        temperature=0.3,
        provider=provider,
        stage="arc_analysis",
        target_id=f"arc_{arc_index:03d}",
        prompt_version="arc_framework_v1",
    )
    cleaned = _extract_json(answer)
    if not cleaned:
        raise RuntimeError(f"弧段分析无 JSON: {answer[:300]}")
    return _load_json_with_provider_repair(cleaned, "弧段", provider=provider)


# ══════════════════════════════════════════════════════
# 全书层：DeepSeek 直调（原 Workflow D）
# ══════════════════════════════════════════════════════

def call_book_deepseek(
    arc_frameworks: list,
    total_chapters: int,
    provider: str | None = None,
) -> dict:
    user_prompt = (
        f"请分析以下小说全书结构（共 {total_chapters} 章，{len(arc_frameworks)} 个弧段）：\n\n"
        + json.dumps(arc_frameworks, ensure_ascii=False, indent=2)
        + "\n\n请按 JSON 格式输出全书分析结果。"
    )
    answer  = _call_llm_traced(
        _BOOK_SYSTEM_PROMPT,
        user_prompt,
        temperature=0.3,
        provider=provider,
        stage="book_analysis",
        target_id="book_framework",
        prompt_version="book_framework_v1",
    )
    cleaned = _extract_json(answer)
    if not cleaned:
        raise RuntimeError(f"全书分析无 JSON: {answer[:300]}")
    return _load_json_with_provider_repair(cleaned, "全书", provider=provider)


# ══════════════════════════════════════════════════════
# 章节加载
# ══════════════════════════════════════════════════════

def load_from_folder(folder: str) -> list:
    p = Path(folder)
    files = sorted(
        (f for f in p.iterdir() if f.suffix in (".txt", ".md") and f.is_file()),
        key=chapter_sort_key,
    )
    if not files:
        raise FileNotFoundError(f"文件夹 {folder} 中没有找到 .txt 或 .md 文件")
    chapters = [{"title": f.stem, "filename": f.name, "text": read_story_text_file(f)} for f in files]
    return _expand_long_chapter_parts(chapters)


def split_book(book_path: str, pattern: str = None) -> list:
    # 支持 .txt 和 .docx
    p = Path(book_path)
    if p.suffix.lower() == ".docx":
        try:
            from docx import Document
            doc = Document(str(p))
            text = "\n".join(para.text for para in doc.paragraphs)
        except ImportError:
            raise RuntimeError("读取 .docx 需要安装 python-docx：pip install python-docx")
    else:
        text = read_story_text_file(p)

    if pattern is None:
        from story_analyzer_v1.ingestion.chapter_boundary_detector import split_text_into_chapters

        chapters = []
        for chapter in split_text_into_chapters(text):
            part = chapter.text.strip()
            if len(part) < 50:
                continue
            title = chapter.source_title or chapter.normalized_title or clean_chapter_title(part, len(chapters) + 1)
            chapters.append({"title": title, "text": part})
        if not chapters:
            raise ValueError("未能切分出任何章节，请检查文件格式")
        chapters, _dedupe_report = _dedupe_repeated_source_chapter_sequence(chapters)
        return _expand_long_chapter_parts(chapters)

    parts = re.split(pattern, text)
    chapters = []
    for part in parts:
        part = part.strip()
        if len(part) < 50:
            continue
        title = clean_chapter_title(part, len(chapters) + 1)
        chapters.append({"title": title, "text": part})
    if not chapters:
        raise ValueError("未能切分出任何章节，请检查文件格式")
    chapters, _dedupe_report = _dedupe_repeated_source_chapter_sequence(chapters)
    return _expand_long_chapter_parts(chapters)


# ══════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════

def _manifest_entry(idx, chapter, sha256, status, output_files):
    entry = {
        "chapter_index":  idx,
        "input_filename": chapter.get("filename", ""),
        "input_title":    chapter["title"],
        "content_sha256": sha256,
        "text_length":    len(chapter["text"]),
        "output_files":   output_files,
        "status":         status,
    }
    for key in (
        "original_chapter_index",
        "original_title",
        "part_index",
        "part_count",
        "part_start_char",
        "part_end_char",
    ):
        if key in chapter:
            entry[key] = chapter[key]
    return entry


def _missing_required_outputs(out: Path) -> list[str]:
    required = ("book_framework.json", "generation_profiles.json", "full_book_bundle.json")
    return [name for name in required if not (out / name).exists()]


def _failed_stage_target(stage: str, target_id: str, reason: str, **extra) -> dict:
    entry = {
        "stage": stage,
        "target_id": target_id,
        "status": "failed_unrecovered",
        "reason": str(reason or ""),
    }
    entry.update({key: value for key, value in extra.items() if value not in (None, "")})
    return entry


def _arc_failure_entry(arc_index: int, arc_metadata: dict, reason: str) -> dict:
    arc_id = f"arc_{arc_index:03d}"
    return _failed_stage_target(
        "arc_analysis",
        arc_id,
        reason,
        arc_id=arc_id,
        arc_index=arc_index,
        source_chapter_range=arc_metadata.get("source_chapter_range"),
        analysis_unit_range=arc_metadata.get("analysis_unit_range"),
    )


def _missing_arc_failure_entries(
    arc_ranges: list[tuple[int, int]],
    chapters: list[dict],
    arc_dir: Path,
    known_failures: list[dict],
) -> list[dict]:
    known_ids = {entry.get("arc_id") for entry in known_failures}
    failures = list(known_failures)
    for arc_index, (start_chapter, end_chapter) in enumerate(arc_ranges, start=1):
        arc_id = f"arc_{arc_index:03d}"
        if arc_id in known_ids or (arc_dir / f"{arc_id}.json").exists():
            continue
        failures.append(
            _arc_failure_entry(
                arc_index,
                _arc_source_metadata(chapters, start_chapter, end_chapter),
                "missing_arc_output",
            )
        )
    return failures


def _apply_downstream_blocked_manifest_fields(
    manifest: dict,
    out: Path,
    *,
    failed_stage_targets: list[dict],
) -> dict:
    manifest["failed_stage_targets"] = failed_stage_targets
    manifest["missing_required_outputs"] = _missing_required_outputs(out)
    return manifest


def _call_with_provider_fallback(func, *args, provider: str):
    try:
        return func(*args, provider=provider)
    except TypeError as exc:
        if "provider" not in str(exc):
            raise
        return func(*args)


def _is_retryable_llm_error(error) -> bool:
    text = str(error or "").lower()
    return any(pattern in text for pattern in _RETRYABLE_LLM_ERROR_PATTERNS)


def _retry_delays_for_stage_error(stage: str, error) -> list[int]:
    base_delays = [RETRY_WAIT] * max(0, MAX_RETRY - 1)
    if MAX_RETRY >= 3 and stage in CRITICAL_LLM_STAGES and _is_retryable_llm_error(error):
        return base_delays + list(CRITICAL_STAGE_EXTRA_RETRY_DELAYS)
    return base_delays


def _run_with_stage_retries(stage: str, target_id: str, operation):
    retry_delays: list[int] | None = None
    attempt_index = 0
    while True:
        try:
            return operation(), ""
        except Exception as exc:
            final_error = str(exc)
            if retry_delays is None:
                retry_delays = _retry_delays_for_stage_error(stage, exc)
            if attempt_index >= len(retry_delays):
                return None, final_error
            delay = retry_delays[attempt_index]
            total_attempts = len(retry_delays) + 1
            kind = "外部连接/API 可恢复错误" if _is_retryable_llm_error(exc) else "常规错误"
            print(
                f"\n           ⚠ 重试 {attempt_index + 1}/{total_attempts - 1} "
                f"({kind}, {delay}s): {exc}"
            )
            time.sleep(delay)
            attempt_index += 1


def _model_signature(runtime: dict) -> str:
    return f"{runtime.get('provider_type')}:{runtime.get('model')}"


def _read_chapter_model_signature(model_path: Path) -> str:
    if not model_path.exists():
        return "deepseek:deepseek-chat"
    try:
        data = json.loads(model_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    return _model_signature(data)


def _attach_llm_ledger_summary(manifest: dict) -> dict:
    if _ACTIVE_LLM_CALL_LOGGER is None:
        manifest.setdefault("llm_call_ledger_ref", "llm_calls/index.json")
        manifest.setdefault("llm_call_count", 0)
        manifest.setdefault("llm_attempt_failed_call_count", 0)
        manifest.setdefault("llm_failed_call_count", 0)
        manifest.setdefault("llm_unrecovered_failed_target_count", 0)
        manifest.setdefault("llm_recovered_target_count", 0)
        manifest.setdefault("llm_repair_call_count", 0)
        manifest.setdefault("llm_truncated_call_count", 0)
        manifest.setdefault("provider_counts", {})
        manifest.setdefault("llm_target_status_counts", {"ok": 0, "recovered": 0, "failed": 0})
        manifest.setdefault("llm_recovered_targets", [])
        manifest.setdefault("llm_failed_targets", [])
        return manifest
    manifest.update(_ACTIVE_LLM_CALL_LOGGER.summary())
    return manifest


def _apply_arc_fallback_manifest_fields(manifest: dict, fallback_arcs: list[dict] | None) -> dict:
    fallback_arcs = fallback_arcs or []
    manifest["degraded_arc_count"] = len(fallback_arcs)
    manifest["fallback_arcs"] = fallback_arcs
    if not fallback_arcs:
        manifest.setdefault("llm_failed_targets_handled_by_fallback", [])
        manifest.setdefault("llm_fallback_recovered_target_count", 0)
        return manifest

    fallback_keys = {
        (str(item.get("stage") or "arc_analysis"), str(item.get("target_id") or item.get("arc_id") or ""))
        for item in fallback_arcs
    }
    failed_targets = manifest.get("llm_failed_targets") or []
    handled = [
        target
        for target in failed_targets
        if (str(target.get("stage") or ""), str(target.get("target_id") or "")) in fallback_keys
    ]
    remaining = [
        target
        for target in failed_targets
        if (str(target.get("stage") or ""), str(target.get("target_id") or "")) not in fallback_keys
    ]
    manifest["llm_failed_targets_raw"] = failed_targets
    manifest["llm_failed_targets_handled_by_fallback"] = handled
    manifest["llm_fallback_recovered_target_count"] = len(handled)
    if handled:
        manifest["llm_failed_targets"] = remaining
        manifest["llm_failed_call_count"] = len(remaining)
        manifest["llm_unrecovered_failed_target_count"] = len(remaining)
        counts = dict(manifest.get("llm_target_status_counts") or {})
        counts["failed"] = len(remaining)
        counts["fallback_recovered"] = len(handled)
        manifest["llm_target_status_counts"] = counts
    if handled and not remaining:
        manifest["llm_health_status"] = "recovered_with_fallback"
        manifest["llm_health_label"] = "已降级恢复"
        manifest["llm_health_severity"] = "warning"
        manifest["llm_health_message"] = (
            f"{len(handled)} 个 LLM target 最终未返回，但已用章节框架生成降级产物；"
            "输出可继续消费，但对应弧段质量需复核。"
        )
    return manifest


def run_book(
    chapters: list,
    output_dir: str,
    work_title: str = "",
    model_provider: str | None = None,
) -> dict:
    global _ACTIVE_LLM_CALL_LOGGER
    chapters, source_deduplication = _dedupe_repeated_source_chapter_sequence(chapters)
    out     = Path(output_dir)
    ch_dir  = out / "chapters"
    arc_dir = out / "arcs"
    ch_dir.mkdir(parents=True, exist_ok=True)
    arc_dir.mkdir(parents=True, exist_ok=True)
    _ACTIVE_LLM_CALL_LOGGER = LlmCallLogger(out / "llm_calls")
    log_path = out / "progress.log"
    total    = len(chapters)
    chain: dict = {}
    successful_chapters: set[int] = set()
    failed_chapters: list[dict] = []
    registry_path = out / "foreshadowing_registry.json"
    if registry_path.exists():
        try:
            foreshadowing_registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            foreshadowing_registry = _empty_foreshadowing_registry()
        foreshadowing_registry = _normalize_foreshadowing_registry_contract(foreshadowing_registry)
        rebuilding_registry = False
    else:
        foreshadowing_registry = _empty_foreshadowing_registry()
        rebuilding_registry = True

    # 词库
    vocab        = None
    vocab_context = ""
    if _VOCAB_AVAILABLE:
        try:
            vocab = load_vocabulary()
            vocab_context = get_vocabulary_context(vocab)
            print(f"📖 词库已加载：{vocab.get('stats',{}).get('total_terms',0)} 个词条")
        except Exception as e:
            print(f"⚠ 词库加载失败（不影响分析）: {e}")

    run_id   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    source_total = _source_chapter_count(chapters)
    llm_runtime = get_llm_runtime(model_provider)
    model_signature = _model_signature(llm_runtime)
    manifest = {
        "run_id":          run_id,
        "analyzer":        "book_analyzer_v2",
        "model_provider":  llm_runtime["provider_type"],
        "model":           llm_runtime["model"],
        "model_base_url":  llm_runtime["base_url"],
        "model_api_key_env": llm_runtime["api_key_env"],
        "model_api_key_configured": llm_runtime["api_key_configured"],
        "arc_strategy":    "structural_title_or_dynamic_chunk",
        "legacy_arc_size": ARC_SIZE,
        "total_chapters":  source_total,
        "analysis_unit_count": total,
        "source_total_chapters": source_total,
        "chapter_count_basis": "source_chapters",
        "legacy_analysis_unit_total": total,
        "run_started_at":  datetime.datetime.now().isoformat(),
        "run_finished_at": "",
        "run_status":     "running",
        "successful_chapter_count": 0,
        "failed_chapter_count": 0,
        "failed_chapters": [],
        "downstream_blocked_reason": "",
        "source_deduplication": source_deduplication,
        "chapters":        [],
    }
    manifest = _attach_llm_ledger_summary(manifest)

    arc_ranges = _legacy_arc_ranges(chapters)
    manifest["arc_ranges"] = [
        {"start": start, "end": end, **_arc_source_metadata(chapters, start, end)}
        for start, end in arc_ranges
    ]

    print(f"\n📚 共 {total} 章  |  弧段候选 {len(arc_ranges)} 个  |  输出目录: {output_dir}")
    print("═" * 60)

    # ── 第一层：章节层 ─────────────────────────────────
    provider_label = f"{llm_runtime['provider_type']} / {llm_runtime['model']}"
    print(f"▶ 第一层：章节拆解（{provider_label}）")
    for i, chapter in enumerate(chapters):
        idx        = i + 1
        cid        = f"chapter_{idx:03d}"
        fw_path    = ch_dir / f"{cid}_framework.json"
        an_path    = ch_dir / f"{cid}_analysis.json"
        pk_path    = ch_dir / f"{cid}_next_pack.json"
        hash_path  = ch_dir / f"{cid}_input.hash"
        model_path = ch_dir / f"{cid}_model.json"

        sha256 = hashlib.sha256(chapter["text"].encode()).hexdigest()
        if fw_path.exists():
            saved = hash_path.read_text().strip() if hash_path.exists() else ""
            saved_model_signature = _read_chapter_model_signature(model_path)
            if saved and saved != sha256:
                print(f"  [{idx:>3}/{total}] {chapter['title'][:30]}  ⚠ 内容变更，重新分析")
            elif saved_model_signature == model_signature:
                if rebuilding_registry and an_path.exists():
                    try:
                        existing_report = json.loads(an_path.read_text(encoding="utf-8"))
                        existing_report = _apply_foreshadowing_registry_to_report(
                            existing_report,
                            idx,
                            foreshadowing_registry,
                        )
                        an_path.write_text(json.dumps(existing_report, ensure_ascii=False, indent=2), encoding="utf-8")
                        foreshadowing_registry = _write_foreshadowing_registry(
                            registry_path,
                            foreshadowing_registry,
                        )
                    except json.JSONDecodeError:
                        pass
                chain = json.loads(pk_path.read_text(encoding="utf-8")) if pk_path.exists() else {}
                print(f"  [{idx:>3}/{total}] {chapter['title'][:30]}  ← 跳过（已完成）")
                manifest["chapters"].append(_manifest_entry(idx, chapter, sha256, "skipped",
                    [fw_path.name, an_path.name, pk_path.name]))
                successful_chapters.add(idx)
                continue

        print(f"  [{idx:>3}/{total}] {chapter['title'][:30]}  ...", end="", flush=True)
        t0 = time.time()
        outputs = None

        def _chapter_operation():
            call_chain = dict(chain)
            if vocab_context:
                call_chain["vocabulary_context"] = vocab_context
            return _call_with_provider_fallback(
                call_chapter_deepseek,
                chapter["text"],
                idx,
                call_chain,
                provider=llm_runtime["provider_type"],
            )

        outputs, final_error = _run_with_stage_retries("chapter_analysis", cid, _chapter_operation)
        if outputs is None:
            print(f"\n           ❌ 失败，跳过: {final_error}")
            _log(log_path, f"FAILED  {cid}  {final_error}")

        if outputs is None:
            failed_entry = _manifest_entry(idx, chapter, sha256, "failed", [])
            failed_entry["error"] = final_error
            manifest["chapters"].append(failed_entry)
            failed_chapters.append(failed_entry)
            continue

        fw_json  = outputs.get("framework_package_json", "")
        an_json  = outputs.get("analysis_report_json", "")
        pack_raw = outputs.get("next_chapter_pack", "{}")
        try:
            next_pack = json.loads(pack_raw) if isinstance(pack_raw, str) else pack_raw
        except json.JSONDecodeError:
            next_pack = {}

        try:
            an_data = json.loads(an_json) if isinstance(an_json, str) else an_json
            an_data = _apply_foreshadowing_registry_to_report(an_data, idx, foreshadowing_registry)
            next_pack = _build_next_pack_from_report(an_data, foreshadowing_registry, idx)
            an_json = json.dumps(an_data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass

        fw_path.write_text(fw_json, encoding="utf-8")
        an_path.write_text(an_json, encoding="utf-8")
        pk_path.write_text(json.dumps(next_pack, ensure_ascii=False, indent=2), encoding="utf-8")
        hash_path.write_text(sha256)
        model_path.write_text(json.dumps(llm_runtime, ensure_ascii=False, indent=2), encoding="utf-8")
        foreshadowing_registry = _write_foreshadowing_registry(registry_path, foreshadowing_registry)
        manifest["chapters"].append(_manifest_entry(idx, chapter, sha256, "ok",
            [fw_path.name, an_path.name, pk_path.name]))
        successful_chapters.add(idx)

        if vocab is not None and fw_json.strip():
            try:
                fw_data = json.loads(fw_json)
                _title  = work_title or Path(output_dir).parent.name
                vocab_report, vocab = process_chapter_components(fw_data, _title, idx, vocab, auto_approve_similar=True)
                new_cnt = len(vocab_report.get("new_terms_pending", []))
                if new_cnt:
                    print(f"\n     📖 词库：{new_cnt} 个新词待审核", end="")
            except Exception:
                pass

        chain = next_pack
        elapsed = time.time() - t0
        print(f"  ✓  {elapsed:.0f}s")
        _log(log_path, f"OK      {cid}  {chapter['title'][:40]}  {elapsed:.0f}s")

        if idx < total:
            time.sleep(API_DELAY)

    done = len(successful_chapters)
    print(f"\n  章节层完成 {done}/{total} 章")
    if done < total:
        print(f"  ⚠  {total - done} 章失败，重新运行可续跑")
        manifest["run_finished_at"] = datetime.datetime.now().isoformat()
        manifest["run_status"] = "partial"
        manifest["successful_chapter_count"] = done
        manifest["failed_chapter_count"] = len(failed_chapters) or (total - done)
        manifest["failed_chapters"] = failed_chapters
        manifest["downstream_status"] = "blocked"
        manifest["downstream_blocked_reason"] = "chapter_failures"
        manifest["failed_arc_count"] = 0
        manifest["failed_arcs"] = []
        failed_stage_targets = [
            _failed_stage_target(
                "chapter_analysis",
                f"chapter_{int(entry.get('chapter_index') or 0):03d}",
                entry.get("error", "chapter_analysis_failed"),
                chapter_index=entry.get("chapter_index"),
            )
            for entry in failed_chapters
        ]
        manifest = _apply_downstream_blocked_manifest_fields(
            manifest,
            out,
            failed_stage_targets=failed_stage_targets,
        )
        foreshadowing_registry = _write_foreshadowing_registry(registry_path, foreshadowing_registry)
        manifest = _apply_manifest_source_metadata(manifest, chapters)
        manifest = _attach_llm_ledger_summary(manifest)
        (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(ch_dir, arc_dir, out, total)
        _ACTIVE_LLM_CALL_LOGGER = None
        return {"status": "partial", "failed_chapter_count": manifest["failed_chapter_count"], "output_dir": str(out)}

    # ── 第二层：弧段层 ─────────────────────────────────
    print(f"\n▶ 第二层：弧段分析（{provider_label}）")
    arc_count = 0
    failed_arcs: list[dict] = []
    fallback_arcs: list[dict] = []
    for arc_index, (start_chapter, end_chapter) in enumerate(arc_ranges, start=1):
        arc_id    = f"arc_{arc_index:03d}"
        arc_path  = arc_dir / f"{arc_id}.json"
        arc_metadata = _arc_source_metadata(chapters, start_chapter, end_chapter)
        arc_range = arc_metadata["source_chapter_range"] or f"{start_chapter}-{end_chapter}"
        analysis_unit_range = arc_metadata["analysis_unit_range"]

        if arc_path.exists():
            try:
                existing_arc = json.loads(arc_path.read_text(encoding="utf-8"))
                existing_arc = _inject_arc_source_metadata(existing_arc, arc_metadata)
                existing_arc = _normalize_arc_foreshadowing_summary(existing_arc, foreshadowing_registry)
                arc_path.write_text(json.dumps(existing_arc, ensure_ascii=False, indent=2), encoding="utf-8")
            except json.JSONDecodeError:
                pass
            print(f"  [弧段 {arc_index}] 章{arc_range}  ← 跳过（已完成）")
            arc_count += 1
            continue

        chapter_packages = []
        for ch_idx in range(start_chapter, end_chapter + 1):
            fw_p = ch_dir / f"chapter_{ch_idx:03d}_framework.json"
            an_p = ch_dir / f"chapter_{ch_idx:03d}_analysis.json"
            pk_p = ch_dir / f"chapter_{ch_idx:03d}_next_pack.json"
            if fw_p.exists():
                try:
                    chapter_packages.append({
                        "chapter_number":        ch_idx,
                        "analysis_unit_number":  ch_idx,
                        "source_chapter":        _arc_source_metadata(chapters, ch_idx, ch_idx),
                        "framework_package":     json.loads(fw_p.read_text(encoding="utf-8")),
                        "story_analysis_report": json.loads(an_p.read_text(encoding="utf-8")) if an_p.exists() else {},
                        "next_chapter_pack":     json.loads(pk_p.read_text(encoding="utf-8")) if pk_p.exists() else {},
                    })
                except json.JSONDecodeError:
                    pass

        if not chapter_packages:
            print(f"  [弧段 {arc_index}] 章{arc_range}  ← 无数据，跳过")
            continue

        print(f"  [弧段 {arc_index}] 章{arc_range}（analysis units {analysis_unit_range}, {len(chapter_packages)} 个）  ...", end="", flush=True)
        t0     = time.time()
        arc_fw = None

        def _arc_operation():
            return _call_with_provider_fallback(
                call_arc_deepseek,
                chapter_packages,
                arc_index,
                arc_range,
                provider=llm_runtime["provider_type"],
            )

        arc_fw, final_error = _run_with_stage_retries("arc_analysis", arc_id, _arc_operation)

        if arc_fw is not None:
            arc_fw = _inject_arc_source_metadata(arc_fw, arc_metadata)
            arc_fw = _normalize_arc_foreshadowing_summary(arc_fw, foreshadowing_registry)
            arc_path.write_text(json.dumps(arc_fw, ensure_ascii=False, indent=2), encoding="utf-8")
            elapsed = time.time() - t0
            print(f"  ✓  {elapsed:.0f}s")
            _log(log_path, f"OK      {arc_id}  章{arc_range}  {elapsed:.0f}s")
            arc_count += 1
            time.sleep(API_DELAY)
        else:
            fallback_fw = _fallback_arc_framework(
                chapter_packages,
                arc_index,
                arc_range,
                arc_metadata,
                final_error,
            )
            fallback_fw = _inject_arc_source_metadata(fallback_fw, arc_metadata)
            fallback_fw = _normalize_arc_foreshadowing_summary(fallback_fw, foreshadowing_registry)
            arc_path.write_text(json.dumps(fallback_fw, ensure_ascii=False, indent=2), encoding="utf-8")
            elapsed = time.time() - t0
            print(f"\n           ⚠ 弧段模型失败，已用章节框架降级生成: {final_error}")
            _log(log_path, f"FALLBACK {arc_id}  章{arc_range}  {elapsed:.0f}s  {final_error}")
            fallback_arcs.append(
                {
                    **_arc_failure_entry(arc_index, arc_metadata, final_error),
                    "status": "fallback_generated",
                    "fallback_file": f"{arc_id}.json",
                }
            )
            arc_count += 1
            time.sleep(API_DELAY)
    print(f"\n  弧段层完成 {arc_count}/{len(arc_ranges)} 个弧段")
    foreshadowing_registry = _write_foreshadowing_registry(registry_path, foreshadowing_registry)
    if arc_count < len(arc_ranges):
        failed_arcs = _missing_arc_failure_entries(arc_ranges, chapters, arc_dir, failed_arcs)
        manifest["run_finished_at"] = datetime.datetime.now().isoformat()
        manifest["run_status"] = "partial"
        manifest["successful_chapter_count"] = done
        manifest["failed_chapter_count"] = 0
        manifest["failed_chapters"] = []
        manifest["downstream_status"] = "blocked"
        manifest["downstream_blocked_reason"] = "arc_failures"
        manifest["arc_count"] = arc_count
        manifest["expected_arc_count"] = len(arc_ranges)
        manifest["failed_arc_count"] = len(failed_arcs)
        manifest["failed_arcs"] = failed_arcs
        manifest = _apply_downstream_blocked_manifest_fields(
            manifest,
            out,
            failed_stage_targets=failed_arcs,
        )
        manifest = _apply_manifest_source_metadata(manifest, chapters)
        manifest = _attach_llm_ledger_summary(manifest)
        manifest = _apply_arc_fallback_manifest_fields(manifest, fallback_arcs)
        (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(ch_dir, arc_dir, out, total)
        _ACTIVE_LLM_CALL_LOGGER = None
        return {
            "status": "partial",
            "failed_chapter_count": 0,
            "failed_arc_count": len(failed_arcs),
            "output_dir": str(out),
        }

    # ── 第三层：全书层 ─────────────────────────────────
    print(f"\n▶ 第三层：全书分析（{provider_label}）")
    book_path = out / "book_framework.json"

    if book_path.exists():
        try:
            existing_book = json.loads(book_path.read_text(encoding="utf-8"))
            existing_book = _apply_book_foreshadowing_registry(existing_book, foreshadowing_registry, arc_ranges)
            existing_book = _apply_book_source_metadata(existing_book, chapters)
            existing_book = _apply_book_arc_metadata(existing_book, _load_arc_frameworks_from_dir(arc_dir))
            book_path.write_text(json.dumps(existing_book, ensure_ascii=False, indent=2), encoding="utf-8")
        except json.JSONDecodeError:
            pass
        print("  [全书层] ← 跳过（已完成）")
    else:
        arc_frameworks = _load_arc_frameworks_from_dir(arc_dir)

        if not arc_frameworks:
            print("  [全书层] 无弧段数据，跳过")
        else:
            print(f"  [全书层] {len(arc_frameworks)} 个弧段  ...", end="", flush=True)
            t0      = time.time()
            book_fw = None
            book_final_error = ""

            def _book_operation():
                book = _call_with_provider_fallback(
                    call_book_deepseek,
                    arc_frameworks,
                    source_total,
                    provider=llm_runtime["provider_type"],
                )
                book = _apply_book_foreshadowing_registry(book, foreshadowing_registry, arc_ranges)
                book = _apply_book_source_metadata(book, chapters)
                return _apply_book_arc_metadata(book, arc_frameworks)

            book_fw, book_final_error = _run_with_stage_retries("book_analysis", "book_framework", _book_operation)
            if book_fw is None:
                print(f"\n           ❌ 失败: {book_final_error}")
                _log(log_path, f"FAILED  book_framework  {book_final_error}")

            if book_fw is not None:
                book_path.write_text(json.dumps(book_fw, ensure_ascii=False, indent=2), encoding="utf-8")
                elapsed = time.time() - t0
                print(f"  ✓  {elapsed:.0f}s")
                _log(log_path, f"OK      book_framework  {elapsed:.0f}s")

    if vocab is not None:
        try:
            save_vocabulary(vocab)
            pending = vocab.get("stats", {}).get("total_pending", 0)
            total_t = vocab.get("stats", {}).get("total_terms", 0)
            if pending:
                print(f"\n📖 词库：{pending} 个新词待审核（python vocabulary_manager.py pending）")
            else:
                print(f"\n📖 词库：{total_t} 个词条，无新词待审核")
        except Exception as e:
            print(f"⚠ 词库保存失败: {e}")

    if not (out / "book_framework.json").exists():
        manifest["run_finished_at"] = datetime.datetime.now().isoformat()
        manifest["run_status"] = "partial"
        manifest["successful_chapter_count"] = done
        manifest["failed_chapter_count"] = 0
        manifest["failed_chapters"] = []
        manifest["downstream_status"] = "blocked"
        manifest["downstream_blocked_reason"] = "book_framework_failure"
        manifest["failed_arc_count"] = 0
        manifest["failed_arcs"] = []
        manifest = _apply_downstream_blocked_manifest_fields(
            manifest,
            out,
            failed_stage_targets=[
                _failed_stage_target(
                    "book_analysis",
                    "book_framework",
                    locals().get("book_final_error") or "book_framework_not_generated",
                )
            ],
        )
        foreshadowing_registry = _write_foreshadowing_registry(registry_path, foreshadowing_registry)
        manifest = _apply_manifest_source_metadata(manifest, chapters)
        manifest = _attach_llm_ledger_summary(manifest)
        manifest = _apply_arc_fallback_manifest_fields(manifest, fallback_arcs)
        (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(ch_dir, arc_dir, out, total)
        _ACTIVE_LLM_CALL_LOGGER = None
        return {"status": "partial", "failed_chapter_count": 0, "output_dir": str(out)}

    manifest["run_finished_at"] = datetime.datetime.now().isoformat()
    manifest["run_status"] = "completed"
    manifest["successful_chapter_count"] = done
    manifest["failed_chapter_count"] = 0
    manifest["failed_chapters"] = []
    manifest["downstream_status"] = "completed"
    manifest["downstream_blocked_reason"] = ""
    manifest["arc_count"] = arc_count
    manifest["expected_arc_count"] = len(arc_ranges)
    manifest["failed_arc_count"] = 0
    manifest["failed_arcs"] = []
    manifest["failed_stage_targets"] = []
    foreshadowing_registry = _write_foreshadowing_registry(registry_path, foreshadowing_registry)
    manifest = _apply_manifest_source_metadata(manifest, chapters)
    manifest = _attach_llm_ledger_summary(manifest)
    manifest = _apply_arc_fallback_manifest_fields(manifest, fallback_arcs)
    bundle_error = ""
    if (out / "book_framework.json").exists():
        try:
            _assemble_bundle(out, total, chapters)
        except Exception as exc:
            bundle_error = str(exc)
            print(f"\n           ❌ 打包失败: {bundle_error}")
            _log(log_path, f"FAILED  full_book_bundle  {bundle_error}")
    if bundle_error:
        manifest["run_status"] = "partial"
        manifest["downstream_status"] = "blocked"
        manifest["downstream_blocked_reason"] = "bundle_assembly_failure"
        manifest["failed_stage_targets"] = [
            _failed_stage_target("bundle_assembly", "full_book_bundle", bundle_error)
        ]
        manifest["missing_required_outputs"] = _missing_required_outputs(out)
        (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(ch_dir, arc_dir, out, total)
        _ACTIVE_LLM_CALL_LOGGER = None
        return {"status": "partial", "failed_chapter_count": 0, "output_dir": str(out)}
    manifest["missing_required_outputs"] = _missing_required_outputs(out)
    (out / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(ch_dir, arc_dir, out, total)
    _ACTIVE_LLM_CALL_LOGGER = None
    return {"status": "completed", "failed_chapter_count": 0, "output_dir": str(out)}


def _assemble_bundle(out: Path, total: int, chapters: list) -> None:
    ch_dir    = out / "chapters"
    arc_dir   = out / "arcs"
    book_path = out / "book_framework.json"
    registry_path = out / "foreshadowing_registry.json"
    source_total = _source_chapter_count(chapters)
    bundle    = {
        "meta": {
            "total_chapters": source_total,
            "source_total_chapters": source_total,
            "analysis_unit_count": total,
            "chapter_count_basis": "source_chapters",
            "processed_at": datetime.datetime.now().isoformat(),
            "schema_version": "2.0",
            "analyzer": "book_analyzer_v2",
        },
        "book_framework": {},
        "foreshadowing_registry": {},
        "narrative_thread_registry": {},
        "generation_profiles": {},
        "arc_hierarchy": {},
        "arcs":     [],
        "chapters": [],
    }
    if book_path.exists():
        try:
            bundle["book_framework"] = _apply_book_source_metadata(
                json.loads(book_path.read_text(encoding="utf-8")),
                chapters,
            )
        except json.JSONDecodeError: pass
    if registry_path.exists():
        try:
            bundle["foreshadowing_registry"] = _write_foreshadowing_registry(
                registry_path,
                json.loads(registry_path.read_text(encoding="utf-8"))
            )
            if bundle["foreshadowing_registry"].get("event_log"):
                (out / "foreshadowing_event_log.json").write_text(
                    json.dumps(bundle["foreshadowing_registry"]["event_log"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except json.JSONDecodeError: pass

    for f in sorted(arc_dir.glob("arc_*.json")):
        try: bundle["arcs"].append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError: pass

    bundle["book_framework"] = _apply_book_arc_metadata(bundle["book_framework"], bundle["arcs"])

    for i in range(1, total + 1):
        fw_p = ch_dir / f"chapter_{i:03d}_framework.json"
        an_p = ch_dir / f"chapter_{i:03d}_analysis.json"
        pk_p = ch_dir / f"chapter_{i:03d}_next_pack.json"
        hp   = ch_dir / f"chapter_{i:03d}_input.hash"
        if fw_p.exists():
            try:
                chapter_source = chapters[i-1] if i <= len(chapters) else {}
                bundle["chapters"].append({
                    "chapter_number":    i,
                    "title":             chapter_source.get("title", f"第{i}章"),
                    "input_filename":    chapter_source.get("filename",""),
                    "input_sha256":      hp.read_text().strip() if hp.exists() else "",
                    "original_chapter_index": chapter_source.get("original_chapter_index"),
                    "original_title": chapter_source.get("original_title"),
                    "part_index": chapter_source.get("part_index"),
                    "part_count": chapter_source.get("part_count"),
                    "part_start_char": chapter_source.get("part_start_char"),
                    "part_end_char": chapter_source.get("part_end_char"),
                    "framework_package": json.loads(fw_p.read_text(encoding="utf-8")),
                    "analysis_report":   json.loads(an_p.read_text(encoding="utf-8")) if an_p.exists() else {},
                    "next_chapter_pack": json.loads(pk_p.read_text(encoding="utf-8")) if pk_p.exists() else {},
                })
            except json.JSONDecodeError: pass

    bundle["narrative_thread_registry"] = _compile_narrative_thread_registry(
        bundle["book_framework"],
        bundle["arcs"],
        bundle["chapters"],
        bundle["foreshadowing_registry"],
    )
    (out / "narrative_thread_registry.json").write_text(
        json.dumps(bundle["narrative_thread_registry"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    bundle["generation_profiles"] = _compile_generation_profiles(
        bundle["book_framework"],
        bundle["arcs"],
        bundle["chapters"],
        bundle["foreshadowing_registry"],
        bundle["narrative_thread_registry"],
    )
    bundle["arc_hierarchy"] = bundle["generation_profiles"].get("arc_hierarchy", {})
    profiles_path = out / "generation_profiles.json"
    profiles_path.write_text(json.dumps(bundle["generation_profiles"], ensure_ascii=False, indent=2), encoding="utf-8")
    structure_only = (bundle["generation_profiles"].get("usage_profiles") or {}).get("structure_only", {})
    for file_name, key in (
        ("source_entity_inventory.json", "source_entity_inventory"),
        ("source_leak_report.json", "source_leak_report"),
        ("abstract_mechanism_catalog.json", "abstract_mechanism_catalog"),
        ("abstraction_quality_report.json", "abstraction_quality_report"),
    ):
        payload = bundle["generation_profiles"].get(key) or structure_only.get(key)
        if payload:
            (out / file_name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    bundle_path = out / "full_book_bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📦 打包完成 → {bundle_path}")


def _chapters_from_manifest(manifest: dict) -> list[dict]:
    chapters = []
    for entry in sorted(manifest.get("chapters", []), key=lambda item: int(item.get("chapter_index") or 0)):
        chapter = {
            "title": entry.get("input_title") or entry.get("title") or f"第{entry.get('chapter_index')}章",
            "filename": entry.get("input_filename", ""),
            "text": "",
        }
        for key in (
            "original_chapter_index",
            "original_title",
            "part_index",
            "part_count",
            "part_start_char",
            "part_end_char",
        ):
            if key in entry:
                chapter[key] = entry[key]
        chapters.append(chapter)
    return chapters


def _arc_ranges_from_manifest(manifest: dict, total: int) -> list[tuple[int, int]]:
    ranges = []
    for item in manifest.get("arc_ranges", []) or []:
        try:
            ranges.append((int(item["start"]), int(item["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    if ranges:
        return ranges
    return [(start, min(start + _legacy_arc_chunk_size(total) - 1, total)) for start in range(1, total + 1, _legacy_arc_chunk_size(total))]


def postprocess_existing_output(output_dir: str | Path) -> dict:
    out = Path(output_dir)
    manifest_path = out / "run_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"run_manifest.json not found: {out}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chapters = _chapters_from_manifest(manifest)
    total = len(chapters)
    manifest = _apply_manifest_source_metadata(manifest, chapters)
    ch_dir = out / "chapters"
    arc_dir = out / "arcs"
    registry = _empty_foreshadowing_registry()

    for idx in range(1, total + 1):
        an_path = ch_dir / f"chapter_{idx:03d}_analysis.json"
        pk_path = ch_dir / f"chapter_{idx:03d}_next_pack.json"
        if not an_path.exists():
            continue
        try:
            report = json.loads(an_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        report = _apply_foreshadowing_registry_to_report(report, idx, registry)
        an_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        next_pack = _build_next_pack_from_report(report, registry, idx)
        pk_path.write_text(json.dumps(next_pack, ensure_ascii=False, indent=2), encoding="utf-8")

    arc_ranges = _arc_ranges_from_manifest(manifest, total)
    for arc_index, (start_chapter, end_chapter) in enumerate(arc_ranges, start=1):
        arc_path = arc_dir / f"arc_{arc_index:03d}.json"
        if not arc_path.exists():
            continue
        try:
            arc = json.loads(arc_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        metadata = _arc_source_metadata(chapters, start_chapter, end_chapter)
        arc = _inject_arc_source_metadata(arc, metadata)
        arc = _normalize_arc_foreshadowing_summary(arc, registry)
        arc_path.write_text(json.dumps(arc, ensure_ascii=False, indent=2), encoding="utf-8")

    registry_path = out / "foreshadowing_registry.json"
    registry = _write_foreshadowing_registry(registry_path, registry)

    book_path = out / "book_framework.json"
    if book_path.exists():
        try:
            book = json.loads(book_path.read_text(encoding="utf-8"))
            book = _apply_book_foreshadowing_registry(book, registry, arc_ranges)
            book = _apply_book_source_metadata(book, chapters)
            book = _apply_book_arc_metadata(book, _load_arc_frameworks_from_dir(arc_dir))
            book_path.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
        except json.JSONDecodeError:
            pass

    _assemble_bundle(out, total, chapters)
    manifest = _attach_llm_ledger_summary(manifest)
    manifest = _apply_arc_fallback_manifest_fields(manifest, manifest.get("fallback_arcs") or [])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    source_total = _source_chapter_count(chapters)
    return {
        "output_dir": str(out),
        "chapters": total,
        "source_total_chapters": source_total,
        "analysis_unit_count": total,
        "foreshadowing_items": len(registry.get("items", [])),
        "source_model_id_conflicts": 0,
        "source_model_id_alias_collisions": len(registry.get("source_model_id_alias_collisions", [])),
        "generation_profiles": str(out / "generation_profiles.json"),
    }


def _print_summary(ch_dir: Path, arc_dir: Path, out: Path, total: int) -> None:
    print("\n" + "═" * 60)
    ch_done   = sum(1 for f in ch_dir.glob("*_framework.json"))
    arc_done  = sum(1 for f in arc_dir.glob("arc_*.json"))
    book_done = (out / "book_framework.json").exists()
    print(f"  章节层: {ch_done}/{total} 章  |  弧段层: {arc_done} 个弧段  |  全书层: {'✓' if book_done else '—'}")


def _log(path: Path, msg: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")


# ══════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════

def _extract_model_provider_arg(argv: list[str]) -> tuple[list[str], str | None]:
    cleaned = [argv[0]]
    model_provider: str | None = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--model-provider":
            if i + 1 >= len(argv):
                raise ValueError("--model-provider requires one value: deepseek or qwen")
            model_provider = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--model-provider="):
            model_provider = arg.split("=", 1)[1]
            i += 1
            continue
        cleaned.append(arg)
        i += 1
    if model_provider is not None:
        model_provider = _normalize_model_provider(model_provider)
    return cleaned, model_provider


def main() -> None:
    try:
        argv, model_provider = _extract_model_provider_arg(sys.argv)
    except ValueError as exc:
        print(str(exc))
        sys.exit(2)

    if len(argv) == 2 and argv[1] in {"-h", "--help"}:
        print(__doc__)
        return

    if len(argv) < 3:
        print(__doc__)
        sys.exit(1)

    mode       = argv[1]
    input_path = argv[2]
    output_dir = argv[3] if len(argv) > 3 else "output"
    if model_provider:
        os.environ[MODEL_PROVIDER_ENV] = model_provider

    if mode == "postprocess":
        summary = postprocess_existing_output(input_path)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if mode == "folder":
        chapters = load_from_folder(input_path)
    elif mode == "split":
        chapters = split_book(input_path)
    else:
        print(f"未知模式: {mode}（应为 folder 或 split）")
        sys.exit(1)

    work_title = Path(input_path).name
    print(f"✔ 加载完成：{len(chapters)} 章  |  作品标识: {work_title}")
    for i, ch in enumerate(chapters[:5]):
        print(f"  [{i+1}] {ch['title']}  ({len(ch['text'])} 字)")
    if len(chapters) > 5:
        print(f"  ... 共 {len(chapters)} 章")

    result = run_book(chapters, output_dir, work_title=work_title, model_provider=model_provider)
    if result.get("status") != "completed":
        sys.exit(2 if result.get("status") == "partial" else 1)


if __name__ == "__main__":
    main()
