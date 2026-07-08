#!/usr/bin/env python3
"""
全书拆解器 · 合并版（V1 + V2）
三层架构：章节层 → 弧段层 → 全书层（默认全部直接调用 DeepSeek，无 Dify 依赖）
支持断点续传、链条状态传递、V5.5 六扩展块、Dify 兼容模式

用法:
  模式A（章节文件夹）: python book_analyzer.py folder <文件夹路径> [输出目录] [--no-dify|--use-dify]
  模式B（整本书/docx）: python book_analyzer.py split  <文件路径>   [输出目录] [--no-dify|--use-dify]

章节文件夹命名规则（模式A）:
  001_第一章.txt / 002_第二章.txt ...（按文件名字母序读取）

运行模式（默认：直接 DeepSeek，无需 Dify）:
  --no-dify   三层全部直接调用 DeepSeek（默认）
  --use-dify  章节层和弧段层使用 Dify Workflow A/C（需配置 DIFY_API_KEY / DIFY_API_KEY_C）

环境变量:
  DEEPSEEK_API_KEY   DeepSeek API 密钥（优先读环境变量）
  DIFY_API_KEY       仅 --use-dify 模式需要（Workflow A）
  DIFY_API_KEY_C     仅 --use-dify 模式需要（Workflow C）
  NO_DIFY            "1"=直接调用（默认），"0"=Dify 模式
"""

import hashlib
import json
import os
import time
import re
import sys
import datetime
from pathlib import Path

import requests

from story_analyzer_utils import chapter_sort_key, clean_chapter_title

BACKEND_DIR = Path(__file__).resolve().parent
ANALYZER_CODE_DIR = BACKEND_DIR.parent
DATA_DIR = ANALYZER_CODE_DIR / "data"

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

# ── 词库集成（可选，缺失不影响主流程）────────────────────
try:
    _VOCAB_DIR = BACKEND_DIR
    sys.path.insert(0, str(_VOCAB_DIR))
    from vocabulary_manager import (
        load_vocabulary, save_vocabulary,
        get_vocabulary_context, process_chapter_components,
        show_pending_review,
    )
    _VOCAB_AVAILABLE = True
except ImportError:
    _VOCAB_AVAILABLE = False

# ── 配置区 ───────────────────────────────────────────────
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL    = "deepseek-chat"

# Dify 配置（仅 --use-dify 模式使用）
API_KEY   = os.environ.get("DIFY_API_KEY",   "")
API_KEY_C = os.environ.get("DIFY_API_KEY_C", "")
API_BASE  = "https://api.dify.ai/v1"

# 运行模式：True = 直接调用 DeepSeek（默认，推荐）
# 可在命令行使用 --no-dify 或 --use-dify 覆盖
NO_DIFY = os.environ.get("NO_DIFY", "1") == "1"

ARC_SIZE   = 15   # 每个弧段包含的章节数（可调）
API_DELAY  = 2    # 每次调用后等待秒数（避免限流）
MAX_RETRY  = 3    # 单次失败最大重试次数
RETRY_WAIT = 8    # 重试间隔秒数
TIMEOUT    = 300  # 单次请求超时秒数

# ── 宏观节点定义（5 个，供 _adapt_chapter_output 使用）──
_MACRO_DEFS = {
    "macro_opening":                {"label": "开端",         "order": 1},
    "macro_inciting_incident":      {"label": "触发事件",     "order": 2},
    "macro_development_escalation": {"label": "发展/升级",    "order": 3},
    "macro_crisis_local_climax":    {"label": "危机/局部高潮","order": 4},
    "macro_resolution_aftermath":   {"label": "结尾/余波",    "order": 5},
}


# ══════════════════════════════════════════════════════════
# 系统提示词
# ══════════════════════════════════════════════════════════

# ── 章节层（V2 格式：LLM 输出扁平内容 JSON，Python 负责结构映射）
_CHAPTER_SYSTEM_PROMPT = """\
你是一位专业的故事结构分析师，擅长中文小说深度拆解。
分析用户提供的章节，输出严格的 JSON 格式（不加任何 markdown 代码块包裹，不加任何额外文字）。

## 宏观组件（从以下 5 个中选，可多选）
- macro_opening：建立世界/主角/基调/初始缺口
- macro_inciting_incident：让故事进入运动，迫使角色回应核心问题
- macro_development_escalation：推进目标、扩大冲突
- macro_crisis_local_climax：角色面对关键选择，局部强度峰值
- macro_resolution_aftermath：呈现后果，形成阶段性落点

## 链条模式
如果用户提供了【上章摘要】【已知伏笔】【角色状态】，请在此基础上继续追踪，
累积更新伏笔列表（保留未回收的，标记已回收的）。

## 输出格式（纯 JSON，无任何包裹）

{
  "story_level": {
    "theme_proposition": "全书核心主题一句话",
    "causal_structure": "因果逻辑链",
    "protagonist_surface_goal": "主角表层目标",
    "protagonist_deep_desire": "主角深层欲望",
    "conflict_surface": "表层冲突（不能为空）",
    "conflict_deep": "深层冲突（不能为空）",
    "overall_emotion_curve": ["阶段1", "阶段2"]
  },
  "chapter": {
    "chapter_index": 1,
    "title": "章节标题",
    "summary": "本章摘要100-200字（不能为空）",
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

# ── 弧段层（V1+V2 合并：兼容 handoff_exporter 的 chapter_range 字段 + V2 扩展字段）
_ARC_SYSTEM_PROMPT = """\
你是一位专业文学结构分析师，专注弧段层分析。
收到若干章节分析结果，提炼弧段层规律。
输出纯 JSON（不加 markdown 代码块，不加额外文字）：

{
  "arc_index": 1,
  "chapter_range": "1-5",
  "arc_title": "弧段标题（5-15字）",
  "arc_theme": "弧段核心主题（5-15字）",
  "arc_theme_evolution": "主题在弧段内如何演进（2-3句话）",
  "arc_summary": "弧段核心叙事总结（100-200字）",
  "arc_macros": ["macro_opening", "macro_inciting_incident"],
  "arc_character_states": {
    "角色名": {
      "start_state": "弧段开始时的状态",
      "end_state": "弧段结束时的状态",
      "key_change": "关键变化，一句话"
    }
  },
  "arc_conflict_peak": "弧段内冲突最高点（2-3句话）",
  "arc_conflict_escalation": "冲突升级过程描述",
  "arc_emotional_rhythm": "弧段整体情绪节奏（2-3句话）",
  "arc_emotion_curve": ["情绪阶段1", "情绪阶段2", "情绪阶段3"],
  "arc_turning_point": "弧段关键转折点",
  "arc_pacing": "节奏描述",
  "arc_foreshadowing_planted": ["F001", "F002"],
  "arc_foreshadowing_resolved": ["F003"],
  "arc_foreshadowing_status": {
    "F001": "planted",
    "F003": "resolved"
  },
  "foreshadowing_summary": {
    "planted_in_arc": [{"id": "F001", "content": "内容", "planted_chapter": 1}],
    "resolved_in_arc": [{"id": "F003", "content": "内容", "resolved_chapter": 4}],
    "still_open": ["F001", "F002"]
  }
}
"""

# ── 全书层
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
    "narrative_rhythm": "全书节奏描述（3-4句话）",
    "structural_pattern": "叙事结构类型及说明",
    "imagery_system": "核心意象及象征演变（2-3句话）",
    "book_summary": "200字以内全书叙事总结"
}
"""


# ══════════════════════════════════════════════════════════
# 1. API 调用
# ══════════════════════════════════════════════════════════

def _extract_json(raw: str) -> str:
    """清理 LLM 输出中的 <think> 推理块和 ```json 代码块包裹，提取纯 JSON 文本。"""
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*\n?|\n?```\s*$", "", text, flags=re.MULTILINE).strip()
    return text


def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
    """直接调用 DeepSeek API（OpenAI 兼容格式）。"""
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


# ── Dify 兼容层（--use-dify 模式使用）────────────────────

def parse_answer(answer: str) -> dict:
    """
    解析 Dify advanced-chat 返回的 answer 文本：
    提取两个 ```json 块 → framework_package_json / analysis_report_json
    提取【字段名】格式 → next_chapter_pack
    """
    json_blocks = re.findall(r"```json\s*\n(.*?)\n```", answer, re.DOTALL)
    framework_json = json_blocks[0].strip() if len(json_blocks) > 0 else ""
    analysis_json  = json_blocks[1].strip() if len(json_blocks) > 1 else ""

    next_pack = {}
    for m in re.finditer(r"【(\w+)】\s*\n(.*?)(?=\n【|\Z)", answer, re.DOTALL):
        key, val = m.group(1), m.group(2).strip()
        next_pack[key] = val

    return {
        "framework_package_json": framework_json,
        "analysis_report_json":   analysis_json,
        "next_chapter_pack":      json.dumps(next_pack, ensure_ascii=False),
    }


def call_workflow_a(text: str, chapter_number: int, chain: dict) -> dict:
    """调用 Dify advanced-chat 应用分析单章（--use-dify 模式）。"""
    url = f"{API_BASE}/chat-messages"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "inputs": {
            "chapter_number":        chapter_number,
            "known_foreshadowing":   chain.get("known_foreshadowing", ""),
            "known_character_state": chain.get("known_character_state", ""),
            "previous_summary":      chain.get("previous_summary", ""),
            "vocabulary_context":    chain.get("vocabulary_context", ""),
        },
        "query": text,
        "response_mode": "blocking",
        "user": "book_analyzer",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("event") == "error" or "answer" not in data:
        raise RuntimeError(f"Dify 返回错误: {data.get('message', data)}")
    answer = data.get("answer", "")
    if not answer.strip():
        raise RuntimeError("Dify 返回内容为空")
    return parse_answer(answer)


def call_workflow_c(chapter_packages: list[dict], arc_index: int, arc_chapter_range: str) -> dict:
    """调用 Dify Workflow C（弧段分析器，--use-dify 模式）。"""
    url = f"{API_BASE}/workflows/run"
    headers = {"Authorization": f"Bearer {API_KEY_C}", "Content-Type": "application/json"}
    payload = {
        "inputs": {
            "chapters_json":     json.dumps(chapter_packages, ensure_ascii=False),
            "arc_index":         arc_index,
            "arc_chapter_range": arc_chapter_range,
        },
        "response_mode": "blocking",
        "user": "book_analyzer",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    arc_json = data.get("data", {}).get("outputs", {}).get("arc_framework_json", "")
    if not arc_json:
        raise RuntimeError(f"Workflow C 返回内容为空: {data}")
    arc_json = _extract_json(arc_json)
    if not arc_json:
        raise RuntimeError("Workflow C 返回内容仅含推理过程，无 JSON")
    try:
        return json.loads(arc_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Workflow C JSON 解析失败: {e}\n{arc_json[:300]}")


# ── 直接调用模式（NO_DIFY=True，默认）────────────────────

def _adapt_chapter_output(data: dict, chapter_number: int) -> dict:
    """
    将 LLM 输出的扁平内容 JSON 映射为标准三件套：
    framework_package_json / analysis_report_json / next_chapter_pack
    同时提取六扩展块（叙事风格/意象/类型标签/角色关系/对话母题/关键物件）。
    """
    ts    = datetime.datetime.now().isoformat()
    ch    = data.get("chapter", {})
    story = data.get("story_level", {})
    identified_macros = ch.get("identified_macros", ["macro_opening"])

    # ── framework_package ─────────────────────────────
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
        ("reader_emotion",     "读者情绪模块", ch.get("reader_emotion", "")),
        ("character_desire",   "角色欲望模块",
         json.dumps(ch.get("character_desire", []), ensure_ascii=False)),
        ("character_arc",      "人物弧光模块",
         json.dumps(ch.get("character_arc", []), ensure_ascii=False)),
        ("conflict",           "冲突模块",
         json.dumps(ch.get("conflict", []), ensure_ascii=False)),
        ("information_release","信息释放模块",
         json.dumps(ch.get("information_release", []), ensure_ascii=False)),
        ("style_pacing",       "风格节奏模块",
         json.dumps(ch.get("style_pacing", {}), ensure_ascii=False)),
    ]:
        modules.append({
            "module_id":    mod_id,
            "module_label": mod_label,
            "content":      content,
            "build_status": "built",
        })

    framework_package = {
        "framework_package_id": f"fw_pkg_{chapter_number:03d}_{ts[:10].replace('-', '')}",
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

    # ── 六扩展块 ─────────────────────────────────────
    ext = {
        "叙事风格": {
            "视角":     data.get("narrative_style", {}).get("point_of_view", ""),
            "时态":     data.get("narrative_style", {}).get("tense", ""),
            "叙述距离": data.get("narrative_style", {}).get("narrative_distance", ""),
            "声音特征": data.get("narrative_style", {}).get("voice_characteristics", ""),
        },
        "意象与象征": [
            {"意象": s.get("symbol", ""), "象征意义": s.get("meaning", ""),
             "出现次数": s.get("occurrences", 1)}
            for s in data.get("imagery_symbols", [])
        ],
        "类型标签": data.get("genre_tags", []),
        "角色关系网络": [
            {"角色A": r.get("character_a", ""), "角色B": r.get("character_b", ""),
             "关系类型": r.get("relation_type", ""), "动态": r.get("dynamic", "")}
            for r in data.get("character_relationships", [])
        ],
        "对话母题": [
            {"母题": m.get("motif", ""), "场景": m.get("context", ""),
             "意义": m.get("significance", "")}
            for m in data.get("dialogue_motifs", [])
        ],
        "关键物件与场景": [
            {"名称": i.get("name", ""), "类型": i.get("type", ""),
             "象征意义": i.get("symbolic_meaning", "")}
            for i in data.get("key_objects_scenes", [])
        ],
    }

    # ── analysis_report ──────────────────────────────
    analysis_report = {
        "report_id":                   f"report_{chapter_number:03d}_{ts[:10].replace('-', '')}",
        "analyzed_at":                 ts,
        "linked_framework_package_id": framework_package["framework_package_id"],
        "chapter_number":              chapter_number,
        "story_level":                 story,
        "chapter_analysis": {
            "chapter_index":           chapter_number,
            "title":                   ch.get("title", f"第{chapter_number}章"),
            "summary":                 ch.get("summary", ""),
            "identified_macros":       identified_macros,
            "macro_reason":            ch.get("macro_assignment_reason", ""),
            "plot_nodes":              ch.get("plot_nodes", []),
            "chapter_function":        ch.get("chapter_function", ""),
            "reader_emotion":          ch.get("reader_emotion", ""),
            "reader_emotion_intensity":ch.get("reader_emotion_intensity", 0.5),
            "character_desire":        ch.get("character_desire", []),
            "character_arc":           ch.get("character_arc", []),
            "conflict":                ch.get("conflict", []),
            "information_release":     ch.get("information_release", []),
            "style_pacing":            ch.get("style_pacing", {}),
            "character_state_after":   ch.get("character_state_after", {}),
        },
        "foreshadowing":        data.get("foreshadowing", []),
        "ending_revelations":   data.get("ending_revelations", []),
        "recommendation_notes": data.get("recommendation_notes", []),
        "扩展分析":             ext,
    }

    # ── next_chapter_pack ────────────────────────────
    open_fw  = [f for f in data.get("foreshadowing", []) if f.get("status") != "resolved"]
    fw_lines = [f"{f['id']}：{f['content']} —— {f.get('status', 'planted')}"
                for f in open_fw]

    char_state = ch.get("character_state_after", {})
    cs_lines   = [
        f"{name}：情绪={s.get('emotion','—')}，欲望强度={s.get('desire_level','—')}，"
        f"关键变化={s.get('key_change','—')}"
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


def call_chapter_direct(text: str, chapter_number: int,
                        chain: dict, vocab_context: str = "") -> dict:
    """
    直接调用 DeepSeek API 分析单章（不依赖 Dify）。
    返回格式与 call_workflow_a 一致：
      framework_package_json / analysis_report_json / next_chapter_pack
    输出包含六扩展块（叙事风格/意象/类型标签/角色关系/对话母题/关键物件）。
    """
    parts = [f"chapter_number: {chapter_number}"]
    if chain.get("previous_summary"):
        parts.append(f"\n【上章摘要】\n{chain['previous_summary']}")
    if chain.get("known_foreshadowing"):
        parts.append(f"\n【已知伏笔】\n{chain['known_foreshadowing']}")
    if chain.get("known_character_state"):
        parts.append(f"\n【角色状态】\n{chain['known_character_state']}")
    if vocab_context:
        parts.append(f"\n【词库参考（优先复用以下词条）】\n{vocab_context}")
    parts.append(f"\n\n【章节正文】\n{text}")

    user_prompt = "\n".join(parts)
    raw         = call_llm(_CHAPTER_SYSTEM_PROMPT, user_prompt)
    cleaned     = _extract_json(raw)
    if not cleaned:
        raise RuntimeError(f"章节分析返回无 JSON（章节 {chapter_number}）: {raw[:200]}")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"章节 {chapter_number} JSON 解析失败: {e}\n内容: {cleaned[:400]}"
        )
    return _adapt_chapter_output(data, chapter_number)


def call_arc_direct(chapter_packages: list[dict],
                    arc_index: int, arc_chapter_range: str) -> dict:
    """
    直接调用 DeepSeek API 进行弧段分析（不依赖 Dify）。
    发送各章摘要（而非完整数据）以节省 Token，返回弧段框架字典。
    """
    summaries = []
    for pkg in chapter_packages:
        ch_num = pkg.get("chapter_number", "?")
        fw     = pkg.get("framework_package", {})
        an     = pkg.get("story_analysis_report", {})

        # 提取模块摘要
        bcf_list = fw.get("built_chapter_frameworks", [])
        bcf      = bcf_list[0] if bcf_list else {}
        modules_summary: dict = {}
        for mod in bcf.get("modules", []):
            mid     = mod.get("module_id", "")
            content = (mod.get("content") or
                       "、".join(c.get("label", "") for c in mod.get("components", [])))
            if content:
                modules_summary[mid] = content

        # 兼容 analysis_report 两种格式
        chap_ana = an.get("chapter_analysis") if an else None
        if not chap_ana and an:
            chapters_list = an.get("chapters", [])
            chap_ana = chapters_list[0] if chapters_list else {}
        summary = (chap_ana or {}).get("summary", "")

        macro_ids     = bcf.get("linked_macro_component_ids", [])
        foreshadowing = an.get("foreshadowing", []) if an else []

        summaries.append({
            "chapter_number":        ch_num,
            "macro_nodes":           macro_ids,
            "modules":               modules_summary,
            "chapter_summary":       summary,
            "foreshadowing_planted": [f.get("id") or f.get("foreshadowing_id", "")
                                       for f in foreshadowing],
        })

    user_prompt = (
        f"请分析弧段 {arc_index}（章节范围 {arc_chapter_range}）。\n\n"
        "以下是本弧段各章的结构框架摘要：\n\n"
        + json.dumps(summaries, ensure_ascii=False, indent=2)
        + f"\n\n请按照系统提示的 JSON 格式输出弧段分析结果。"
          f"arc_index 填 {arc_index}，chapter_range 填 \"{arc_chapter_range}\"。"
    )
    raw     = call_llm(_ARC_SYSTEM_PROMPT, user_prompt, temperature=0.3)
    cleaned = _extract_json(raw)
    if not cleaned:
        raise RuntimeError(f"弧段 {arc_index} 分析返回无 JSON: {raw[:200]}")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"弧段 {arc_index} JSON 解析失败: {e}\n内容: {cleaned[:300]}"
        )


def call_workflow_d(arc_frameworks: list[dict], total_chapters: int) -> dict:
    """全书分析：直接调用 DeepSeek（三种模式均走此接口）。"""
    user_prompt = (
        f"请分析以下小说全书结构（共 {total_chapters} 章，"
        f"{len(arc_frameworks)} 个弧段）：\n\n"
        + json.dumps(arc_frameworks, ensure_ascii=False, indent=2)
        + "\n\n请按 JSON 格式输出全书分析结果。"
    )
    raw     = call_llm(_BOOK_SYSTEM_PROMPT, user_prompt, temperature=0.3)
    cleaned = _extract_json(raw)
    if not cleaned:
        raise RuntimeError(f"全书分析返回无 JSON: {raw[:200]}")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"全书分析 JSON 解析失败: {e}\n内容: {cleaned[:300]}")


# ══════════════════════════════════════════════════════════
# 2. 章节加载
# ══════════════════════════════════════════════════════════

def load_from_folder(folder: str) -> list[dict]:
    """模式A：从文件夹读取章节，按文件名排序。"""
    p     = Path(folder)
    files = sorted(
        (f for f in p.iterdir() if f.suffix in (".txt", ".md") and f.is_file()),
        key=chapter_sort_key,
    )
    if not files:
        raise FileNotFoundError(f"文件夹 {folder} 中没有找到 .txt 或 .md 文件")
    return [{"title": f.stem, "filename": f.name, "text": f.read_text(encoding="utf-8")}
            for f in files]


def split_book(book_path: str, pattern: str | None = None) -> list[dict]:
    """
    模式B：从整本书文件按章节标记切分。
    支持 .txt / .md / .docx（需 pip install python-docx）。
    """
    p = Path(book_path)
    if p.suffix.lower() == ".docx":
        try:
            from docx import Document
            doc  = Document(str(p))
            text = "\n".join(para.text for para in doc.paragraphs)
        except ImportError:
            raise RuntimeError("读取 .docx 需要安装 python-docx：pip install python-docx")
    else:
        text = p.read_text(encoding="utf-8")

    if pattern is None:
        pattern = r"(?=(?:第[零一二三四五六七八九十百千万\d]+[章节回]|Chapter\s+\d+))"
    parts    = re.split(pattern, text)
    chapters = []
    for part in parts:
        part = part.strip()
        if len(part) < 50:
            continue
        title = clean_chapter_title(part, len(chapters) + 1)
        chapters.append({"title": title, "text": part})
    if not chapters:
        raise ValueError("未能切分出任何章节，请检查文件格式或手动指定分割符")
    return chapters


# ══════════════════════════════════════════════════════════
# 3. 主流程
# ══════════════════════════════════════════════════════════

def _manifest_entry(idx: int, chapter: dict, sha256: str,
                    status: str, output_files: list[str]) -> dict:
    return {
        "chapter_index":  idx,
        "input_filename": chapter.get("filename", ""),
        "input_title":    chapter["title"],
        "content_sha256": sha256,
        "text_length":    len(chapter["text"]),
        "output_files":   output_files,
        "status":         status,
    }


def run_book(chapters: list[dict], output_dir: str, work_title: str = "") -> None:
    out     = Path(output_dir)
    ch_dir  = out / "chapters"
    arc_dir = out / "arcs"
    ch_dir.mkdir(parents=True, exist_ok=True)
    arc_dir.mkdir(parents=True, exist_ok=True)
    log_path = out / "progress.log"
    total    = len(chapters)
    chain: dict = {}

    # ── 词库：启动时加载 ─────────────────────────────────
    vocab         = None
    vocab_context = ""
    if _VOCAB_AVAILABLE:
        try:
            vocab         = load_vocabulary()
            vocab_context = get_vocabulary_context(vocab)
            total_terms   = vocab.get("stats", {}).get("total_terms", 0)
            print(f"📖 词库已加载：{total_terms} 个词条")
        except Exception as _e:
            print(f"⚠ 词库加载失败（不影响分析）: {_e}")

    # ── run manifest ─────────────────────────────────────
    run_id   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest: dict = {
        "run_id":          run_id,
        "analyzer":        "book_analyzer_v1v2_merged",
        "analyzer_version":"2.0",
        "mode":            ("direct_deepseek" if NO_DIFY else "dify+deepseek"),
        "model":           DEEPSEEK_MODEL,
        "workflow_a_app_id": ("direct_deepseek" if NO_DIFY
                              else (API_KEY[:12] + "...") if API_KEY else "unconfigured"),
        "workflow_c_app_id": ("direct_deepseek" if NO_DIFY
                              else (API_KEY_C[:12] + "...") if API_KEY_C else "unconfigured"),
        "arc_size":        ARC_SIZE,
        "total_chapters":  total,
        "run_started_at":  datetime.datetime.now().isoformat(),
        "run_finished_at": "",
        "chapters":        [],
    }

    mode_label = "直接DeepSeek（无Dify）" if NO_DIFY else "Dify+DeepSeek"
    print(f"\n📚 共 {total} 章  |  弧段大小 {ARC_SIZE}  |  模式: {mode_label}  |  输出: {output_dir}")
    print("═" * 60)

    # ══════════════════════════════════════════════════════
    # 第一层：章节层
    # ══════════════════════════════════════════════════════
    print("▶ 第一层：章节拆解")
    for i, chapter in enumerate(chapters):
        idx        = i + 1
        cid        = f"chapter_{idx:03d}"
        fw_path    = ch_dir / f"{cid}_framework.json"
        an_path    = ch_dir / f"{cid}_analysis.json"
        pk_path    = ch_dir / f"{cid}_next_pack.json"
        hash_path  = ch_dir / f"{cid}_input.hash"

        # ── 断点续传（含输入 SHA256 校验）───────────────
        sha256 = hashlib.sha256(chapter["text"].encode()).hexdigest()
        if fw_path.exists():
            saved_hash = hash_path.read_text().strip() if hash_path.exists() else ""
            if saved_hash and saved_hash != sha256:
                print(f"  [{idx:>3}/{total}] {chapter['title'][:30]}  ⚠ 输入已变更，重新分析")
            else:
                chain = json.loads(pk_path.read_text(encoding="utf-8")) if pk_path.exists() else {}
                print(f"  [{idx:>3}/{total}] {chapter['title'][:30]}  ← 跳过（已完成）")
                manifest["chapters"].append(_manifest_entry(
                    idx, chapter, sha256, "skipped",
                    [fw_path.name, an_path.name, pk_path.name]
                ))
                continue

        # ── 调用 API（含重试）────────────────────────────
        print(f"  [{idx:>3}/{total}] {chapter['title'][:30]}  ...", end="", flush=True)
        t0      = time.time()
        outputs = None

        for attempt in range(MAX_RETRY):
            try:
                if NO_DIFY:
                    # 传入临时副本，避免 vocab_context 污染持久链条
                    call_chain = dict(chain)
                    if vocab_context:
                        call_chain["vocabulary_context"] = vocab_context
                    outputs = call_chapter_direct(
                        text=chapter["text"],
                        chapter_number=idx,
                        chain=call_chain,
                        vocab_context=vocab_context,
                    )
                else:
                    call_chain = dict(chain)
                    if vocab_context:
                        call_chain["vocabulary_context"] = vocab_context
                    outputs = call_workflow_a(
                        text=chapter["text"],
                        chapter_number=idx,
                        chain=call_chain,
                    )
                break
            except Exception as exc:
                if attempt < MAX_RETRY - 1:
                    print(f"\n           ⚠ 重试 {attempt+1}/{MAX_RETRY}: {exc}")
                    time.sleep(RETRY_WAIT)
                else:
                    print(f"\n           ❌ 失败，跳过: {exc}")
                    _log(log_path, f"FAILED  {cid}  {exc}")

        if outputs is None:
            continue

        # ── 解析输出 ─────────────────────────────────────
        fw_json  = outputs.get("framework_package_json", "")
        an_json  = outputs.get("analysis_report_json", "")
        pack_raw = outputs.get("next_chapter_pack", "{}")
        try:
            next_pack = json.loads(pack_raw) if isinstance(pack_raw, str) else pack_raw
        except json.JSONDecodeError:
            next_pack = {}

        # ── 写磁盘 ───────────────────────────────────────
        fw_path.write_text(fw_json, encoding="utf-8")
        an_path.write_text(an_json, encoding="utf-8")
        pk_path.write_text(json.dumps(next_pack, ensure_ascii=False, indent=2), encoding="utf-8")
        hash_path.write_text(sha256)
        manifest["chapters"].append(_manifest_entry(
            idx, chapter, sha256, "ok",
            [fw_path.name, an_path.name, pk_path.name]
        ))

        # ── 词库：对比本章 framework_package，记录新词 ────
        if vocab is not None and fw_json.strip():
            try:
                fw_data = json.loads(fw_json)
                _title  = work_title or Path(output_dir).parent.name
                vocab_report, vocab = process_chapter_components(
                    fw_data, _title, idx, vocab, auto_approve_similar=True
                )
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

    # 章节层汇总
    done = sum(1 for f in ch_dir.glob("*_framework.json"))
    print(f"\n  章节层完成 {done}/{total} 章")
    if done < total:
        print(f"  ⚠  {total - done} 章失败，重新运行脚本可续跑")
        manifest["run_finished_at"] = datetime.datetime.now().isoformat()
        (out / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _print_summary(ch_dir, arc_dir, out, total)
        return

    # ══════════════════════════════════════════════════════
    # 第二层：弧段层
    # ══════════════════════════════════════════════════════
    if not NO_DIFY and not API_KEY_C:
        print("\n⚠  Dify 模式：DIFY_API_KEY_C 未配置，跳过弧段层和全书层")
        print("   → 配置 DIFY_API_KEY_C 环境变量，或改用 --no-dify 模式（默认）")
        _print_summary(ch_dir, arc_dir, out, total)
        return

    print("\n▶ 第二层：弧段分析")
    arc_count = 0
    arc_index = 1
    for start in range(0, total, ARC_SIZE):
        end       = min(start + ARC_SIZE, total)
        arc_id    = f"arc_{arc_index:03d}"
        arc_path  = arc_dir / f"{arc_id}.json"
        arc_range = f"{start + 1}-{end}"

        if arc_path.exists():
            print(f"  [弧段 {arc_index}] 章{arc_range}  ← 跳过（已完成）")
            arc_index += 1
            arc_count += 1
            continue

        # 读取本弧段各章数据
        chapter_packages = []
        for ch_idx in range(start + 1, end + 1):
            fw_p = ch_dir / f"chapter_{ch_idx:03d}_framework.json"
            an_p = ch_dir / f"chapter_{ch_idx:03d}_analysis.json"
            pk_p = ch_dir / f"chapter_{ch_idx:03d}_next_pack.json"
            if fw_p.exists():
                try:
                    chapter_packages.append({
                        "chapter_number":        ch_idx,
                        "framework_package":     json.loads(fw_p.read_text(encoding="utf-8")),
                        "story_analysis_report": json.loads(an_p.read_text(encoding="utf-8")) if an_p.exists() else {},
                        "next_chapter_pack":     json.loads(pk_p.read_text(encoding="utf-8")) if pk_p.exists() else {},
                    })
                except json.JSONDecodeError:
                    pass

        if not chapter_packages:
            print(f"  [弧段 {arc_index}] 章{arc_range}  ← 无数据，跳过")
            arc_index += 1
            continue

        print(f"  [弧段 {arc_index}] 章{arc_range}（{len(chapter_packages)} 章）  ...", end="", flush=True)
        t0     = time.time()
        arc_fw = None

        for attempt in range(MAX_RETRY):
            try:
                if NO_DIFY:
                    arc_fw = call_arc_direct(chapter_packages, arc_index, arc_range)
                else:
                    arc_fw = call_workflow_c(chapter_packages, arc_index, arc_range)
                break
            except Exception as exc:
                if attempt < MAX_RETRY - 1:
                    print(f"\n           ⚠ 重试 {attempt+1}/{MAX_RETRY}: {exc}")
                    time.sleep(RETRY_WAIT)
                else:
                    print(f"\n           ❌ 失败: {exc}")
                    _log(log_path, f"FAILED  {arc_id}  {exc}")

        if arc_fw is not None:
            arc_path.write_text(json.dumps(arc_fw, ensure_ascii=False, indent=2), encoding="utf-8")
            elapsed = time.time() - t0
            print(f"  ✓  {elapsed:.0f}s")
            _log(log_path, f"OK      {arc_id}  章{arc_range}  {elapsed:.0f}s")
            arc_count += 1
            time.sleep(API_DELAY)

        arc_index += 1

    print(f"\n  弧段层完成 {arc_count}/{arc_index - 1} 个弧段")

    # ══════════════════════════════════════════════════════
    # 第三层：全书层（三种模式均直接调用 DeepSeek）
    # ══════════════════════════════════════════════════════
    if not DEEPSEEK_API_KEY:
        print("\n⚠  DEEPSEEK_API_KEY 未配置，跳过全书层")
        _print_summary(ch_dir, arc_dir, out, total)
        return

    print("\n▶ 第三层：全书分析")
    book_path = out / "book_framework.json"

    if book_path.exists():
        print("  [全书层] ← 跳过（已完成）")
    else:
        arc_frameworks = []
        for f in sorted(arc_dir.glob("arc_*.json")):
            try:
                arc_frameworks.append(json.loads(f.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

        if not arc_frameworks:
            print("  [全书层] 无弧段数据，跳过")
        else:
            print(f"  [全书层] {len(arc_frameworks)} 个弧段  ...", end="", flush=True)
            t0      = time.time()
            book_fw = None

            for attempt in range(MAX_RETRY):
                try:
                    book_fw = call_workflow_d(arc_frameworks, total)
                    break
                except Exception as exc:
                    if attempt < MAX_RETRY - 1:
                        print(f"\n           ⚠ 重试 {attempt+1}/{MAX_RETRY}: {exc}")
                        time.sleep(RETRY_WAIT)
                    else:
                        print(f"\n           ❌ 失败: {exc}")
                        _log(log_path, f"FAILED  book_framework  {exc}")

            if book_fw is not None:
                book_path.write_text(
                    json.dumps(book_fw, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                elapsed = time.time() - t0
                print(f"  ✓  {elapsed:.0f}s")
                _log(log_path, f"OK      book_framework  {elapsed:.0f}s")
                _assemble_bundle(out, total, chapters)

    # ── 词库：保存更新，打印待审核报告 ──────────────────
    if vocab is not None:
        try:
            save_vocabulary(vocab)
            pending_cnt = vocab.get("stats", {}).get("total_pending", 0)
            total_terms = vocab.get("stats", {}).get("total_terms", 0)
            if pending_cnt:
                print(f"\n📖 词库：{pending_cnt} 个词条待人工审核")
                print(f"   运行 python vocabulary_manager.py pending 查看详情")
                print(f"   运行 python vocabulary_manager.py approve <id> <定义> 审核")
            else:
                print(f"\n📖 词库：{total_terms} 个词条，无新词待审核")
        except Exception as _ve:
            print(f"⚠ 词库保存失败: {_ve}")

    manifest["run_finished_at"] = datetime.datetime.now().isoformat()
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_summary(ch_dir, arc_dir, out, total)


def _assemble_bundle(out: Path, total: int, chapters: list[dict]) -> None:
    """组装最终产物 full_book_bundle.json。"""
    ch_dir    = out / "chapters"
    arc_dir   = out / "arcs"
    book_path = out / "book_framework.json"

    bundle: dict = {
        "meta": {
            "total_chapters": total,
            "processed_at":   datetime.datetime.now().isoformat(),
            "schema_version": "2.0",
            "analyzer":       "book_analyzer_v1v2_merged",
        },
        "book_framework": {},
        "arcs":           [],
        "chapters":       [],
    }

    if book_path.exists():
        try:
            bundle["book_framework"] = json.loads(book_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    for f in sorted(arc_dir.glob("arc_*.json")):
        try:
            bundle["arcs"].append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    for i in range(1, total + 1):
        fw_p = ch_dir / f"chapter_{i:03d}_framework.json"
        an_p = ch_dir / f"chapter_{i:03d}_analysis.json"
        pk_p = ch_dir / f"chapter_{i:03d}_next_pack.json"
        hp   = ch_dir / f"chapter_{i:03d}_input.hash"
        if fw_p.exists():
            try:
                bundle["chapters"].append({
                    "chapter_number":    i,
                    "title":             chapters[i-1]["title"] if i <= len(chapters) else f"第{i}章",
                    "input_filename":    chapters[i-1].get("filename", "") if i <= len(chapters) else "",
                    "input_sha256":      hp.read_text().strip() if hp.exists() else "",
                    "framework_package": json.loads(fw_p.read_text(encoding="utf-8")),
                    "analysis_report":   json.loads(an_p.read_text(encoding="utf-8")) if an_p.exists() else {},
                    "next_chapter_pack": json.loads(pk_p.read_text(encoding="utf-8")) if pk_p.exists() else {},
                })
            except json.JSONDecodeError:
                pass

    bundle_path = out / "full_book_bundle.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📦 打包完成 → {bundle_path}")


def _print_summary(ch_dir: Path, arc_dir: Path, out: Path, total: int) -> None:
    print("\n" + "═" * 60)
    ch_done   = sum(1 for f in ch_dir.glob("*_framework.json"))
    arc_done  = sum(1 for f in arc_dir.glob("arc_*.json"))
    book_done = (out / "book_framework.json").exists()
    print(f"  章节层: {ch_done}/{total} 章  |  弧段层: {arc_done} 个弧段  |  全书层: {'✓' if book_done else '—'}")


def _log(path: Path, msg: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")


# ══════════════════════════════════════════════════════════
# 4. 入口
# ══════════════════════════════════════════════════════════

def main() -> None:
    # 解析可选模式标志（在参数列表任意位置均可）
    global NO_DIFY
    if "--no-dify" in sys.argv:
        sys.argv.remove("--no-dify")
        NO_DIFY = True
    elif "--use-dify" in sys.argv:
        sys.argv.remove("--use-dify")
        NO_DIFY = False

    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    mode       = sys.argv[1]
    input_path = sys.argv[2]
    output_dir = sys.argv[3] if len(sys.argv) > 3 else "output"

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

    run_book(chapters, output_dir, work_title=work_title)


if __name__ == "__main__":
    main()
