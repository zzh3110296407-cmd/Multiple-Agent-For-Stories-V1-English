"""
framework_synthesizer.py — 跨作品 Framework 合成与交付工具
版本: 1.0

功能:
  读取 framework_vocabulary.json（积累自多部小说分析），合成一套
  基于实证的 framework 推荐方案，并打包成下游系统可审查使用的交付包。

输出文件（handoff_package/）:
  ├── recommended_framework.json   ← 下游可审查的 component_vocabulary 候选
  ├── vocabulary_export.json       ← 完整词库（含使用统计与可靠性分级）
  ├── cross_novel_patterns.md      ← 跨作品规律报告（人读）
  └── integration_notes.md        ← 接入说明

用法:
  python framework_synthesizer.py
  python framework_synthesizer.py --min-usage 2 --output-dir ./handoff
  python framework_synthesizer.py --comparator 测试与输出/comparison_data_20260617.json
"""

import json
import sys
import argparse
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Optional

# ── 路径 ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
ANALYZER_CODE_DIR = SCRIPT_DIR.parent
DATA_DIR = ANALYZER_CODE_DIR / "data"
VOCAB_FILE = DATA_DIR / "framework_vocabulary.json"

# ── 模块元数据（与历史生成器 schema 对齐）────────────────────────────────────
MODULE_META = {
    "chapter_function": {
        "label": "篇章功能模块",
        "order": 1,
        "persistence": "chapter_local",
        "write_policy": "no_memory_write",
    },
    "reader_emotion": {
        "label": "读者情绪模块",
        "order": 2,
        "persistence": "ephemeral",
        "write_policy": "no_memory_write",
    },
    "character_desire": {
        "label": "角色欲望模块",
        "order": 3,
        "persistence": "cross_chapter",
        "write_policy": "memory_write",
    },
    "character_arc": {
        "label": "人物弧光模块",
        "order": 4,
        "persistence": "cross_chapter",
        "write_policy": "memory_write",
    },
    "conflict": {
        "label": "冲突模块",
        "order": 5,
        "persistence": "chapter_local",
        "write_policy": "no_memory_write",
    },
    "information_release": {
        "label": "信息释放模块",
        "order": 6,
        "persistence": "cross_chapter",
        "write_policy": "memory_write",
    },
    "style_pacing": {
        "label": "风格节奏模块",
        "order": 7,
        "persistence": "chapter_local",
        "write_policy": "no_memory_write",
    },
}

CHAPTER_MODULES = list(MODULE_META.keys())
MACRO_MODULES   = ["macro_framework_basic", "macro_framework_graph"]


# ── 数据加载 ─────────────────────────────────────────────────────────────────

def load_vocabulary(path: Path = VOCAB_FILE) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"词库文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_comparator_data(path: Optional[Path]) -> Optional[dict]:
    if path and path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


# ── 可靠性分级 ────────────────────────────────────────────────────────────────

def reliability_tier(term: dict, n_works: int) -> str:
    """
    根据跨作品出现次数给词条定可靠性等级：
      verified   — 在 ≥2 部作品中出现（跨作品验证）
      tentative  — 仅在 1 部作品中出现（待验证）
      defined    — 系统预定义，尚未被任何分析使用
    """
    cnt = term.get("usage_count", 0)
    if cnt >= 2:
        return "verified"
    if cnt == 1:
        return "tentative"
    return "defined"


def tier_label(tier: str) -> str:
    return {"verified": "✅ 跨作品验证", "tentative": "⚠️ 单作品", "defined": "📋 预定义"}.get(tier, tier)


# ── 组件 ID 生成 ──────────────────────────────────────────────────────────────

def _to_component_id(term_id: str, module_id: str) -> str:
    """将词库 term_id 转为历史生成器 schema 的 component_id 格式。"""
    prefix_map = {
        "chapter_function":    "cf",
        "reader_emotion":      "re",
        "character_desire":    "cd",
        "character_arc":       "ca",
        "conflict":            "co",
        "information_release": "ir",
        "style_pacing":        "sp",
        "macro_framework_basic":  "mfb",
        "macro_framework_graph":  "mfg",
    }
    prefix = prefix_map.get(module_id, module_id[:3])
    return f"vocab_{prefix}_{term_id}"


# ── 推荐 Framework 合成 ───────────────────────────────────────────────────────

def synthesize_macro_framework(vocab: dict, min_usage: int) -> list[dict]:
    """合成大 framework 宏观节点列表（按 order 排序）。"""
    components = []
    order = 1

    for mod_id in MACRO_MODULES:
        terms = vocab.get("terms", {}).get(mod_id, {})
        for term_id, term in sorted(terms.items()):
            if term.get("status") != "active":
                continue
            tier = reliability_tier(term, vocab.get("stats", {}).get("works_analyzed", 1))
            components.append({
                "component_id":  _to_component_id(term_id, mod_id),
                "label":         term["label"],
                "order":         order,
                "instruction":   term.get("abstract_definition", ""),
                "source":        "vocabulary_library",
                "scope":         "macro",
                "reliability":   tier,
                "usage_count":   term.get("usage_count", 0),
                "works_used_in": term.get("works_used_in", []),
                "node_type":     "graph" if mod_id == "macro_framework_graph" else "basic",
            })
            order += 1

    return components


def synthesize_chapter_modules(vocab: dict, min_usage: int) -> list[dict]:
    """合成章节模块列表，每个模块含推荐词条（按可靠性排序）。"""
    n_works = vocab.get("stats", {}).get("works_analyzed", 1)
    modules = []

    for mod_id in CHAPTER_MODULES:
        meta = MODULE_META[mod_id]
        terms = vocab.get("terms", {}).get(mod_id, {})
        if not terms:
            continue

        # 按 usage_count 降序排列词条，相同时按 term_id 排
        sorted_terms = sorted(
            terms.values(),
            key=lambda t: (-t.get("usage_count", 0), t.get("term_id", ""))
        )

        allowed = []
        for i, term in enumerate(sorted_terms):
            if term.get("status") != "active":
                continue
            tier = reliability_tier(term, n_works)
            comp = {
                "component_id":  _to_component_id(term["term_id"], mod_id),
                "label":         term["label"],
                "source":        "vocabulary_library",
                "scope":         "chapter",
                "persistence":   meta["persistence"],
                "owner":         "chapter_framework",
                "write_policy":  meta["write_policy"],
                "normalized_hint": term.get("abstract_definition", ""),
                "order":         i,
                "reliability":   tier,
                "usage_count":   term.get("usage_count", 0),
                "works_used_in": term.get("works_used_in", []),
            }
            # reader_emotion 额外带 valence/arousal
            if mod_id == "reader_emotion":
                if "valence" in term:
                    comp["valence"] = term["valence"]
                if "arousal" in term:
                    comp["arousal"] = term["arousal"]
            allowed.append(comp)

        modules.append({
            "module_id":   mod_id,
            "label":       meta["label"],
            "scope":       "chapter",
            "persistence": meta["persistence"],
            "owner":       "chapter_framework",
            "write_policy": meta["write_policy"],
            "order":       meta["order"],
            "allowed_components": allowed,
            # 推荐默认值：usage_count >= min_usage 的词条
            "recommended_defaults": [
                c["label"] for c in allowed if c["usage_count"] >= min_usage
            ],
        })

    return modules


def build_recommended_framework(vocab: dict, min_usage: int) -> dict:
    """组合完整的 recommended_framework.json。"""
    macro = synthesize_macro_framework(vocab, min_usage)
    chapter_mods = synthesize_chapter_modules(vocab, min_usage)
    n_works = vocab.get("stats", {}).get("works_analyzed", 1)

    return {
        "_meta": {
            "generated_at":   datetime.now().isoformat(),
            "source":         "framework_vocabulary.json",
            "works_analyzed": n_works,
            "min_usage_threshold": min_usage,
            "description": (
                "由 framework_synthesizer.py 从多部小说分析中提炼的推荐 framework。"
                "reliability=verified 的词条已在多部作品中验证，可作为生成器强默认值；"
                "tentative 词条建议作为候选池；defined 词条为预定义但尚未在分析中出现。"
            ),
        },
        "component_vocabulary": {
            "macro_components":  macro,
            "chapter_modules":   chapter_mods,
            "module_components": [],  # 保持与历史生成器 schema 兼容
        },
        # 按可靠性分层的快查表
        "reliability_summary": _build_reliability_summary(vocab, chapter_mods, macro, n_works),
    }


def _build_reliability_summary(vocab, chapter_mods, macro, n_works) -> dict:
    summary = {"verified": {}, "tentative": {}, "defined": {}}
    for mod in chapter_mods:
        mod_id = mod["module_id"]
        for comp in mod["allowed_components"]:
            tier = comp["reliability"]
            summary[tier].setdefault(mod_id, []).append(comp["label"])
    # 宏观节点
    for comp in macro:
        tier = comp["reliability"]
        summary[tier].setdefault("macro", []).append(comp["label"])
    return summary


# ── 词库导出 ──────────────────────────────────────────────────────────────────

def build_vocabulary_export(vocab: dict) -> dict:
    """完整词库导出，含统计、分级与示例。"""
    n_works = vocab.get("stats", {}).get("works_analyzed", 1)
    export = {
        "_meta": {
            "generated_at":   datetime.now().isoformat(),
            "works_analyzed": n_works,
            "total_terms":    vocab.get("stats", {}).get("total_terms", 0),
        },
        "modules": {},
    }

    all_modules = CHAPTER_MODULES + MACRO_MODULES
    for mod_id in all_modules:
        terms = vocab.get("terms", {}).get(mod_id, {})
        if not terms:
            continue
        sorted_terms = sorted(terms.values(), key=lambda t: -t.get("usage_count", 0))
        export["modules"][mod_id] = {
            "label": MODULE_META.get(mod_id, {}).get("label", mod_id),
            "term_count": len(sorted_terms),
            "terms": [
                {
                    "term_id":    t["term_id"],
                    "label":      t["label"],
                    "definition": t.get("abstract_definition", ""),
                    "reliability": reliability_tier(t, n_works),
                    "usage_count": t.get("usage_count", 0),
                    "works_used_in": t.get("works_used_in", []),
                    "examples": [
                        f"{ex['work']} 第{ex['chapter']}章：{ex['hint']}"
                        for ex in t.get("chapter_examples", [])[:2]
                    ],
                }
                for t in sorted_terms
                if t.get("status") == "active"
            ],
        }

    return export


# ── 跨作品规律报告 ────────────────────────────────────────────────────────────

def build_patterns_report(vocab: dict, comparator: Optional[dict], min_usage: int) -> str:
    n_works    = vocab.get("stats", {}).get("works_analyzed", 1)
    works_list = []
    # 从词库 works_used_in 字段收集作品列表
    for mod_terms in vocab.get("terms", {}).values():
        for term in mod_terms.values():
            works_list.extend(term.get("works_used_in", []))
    works_set = sorted(set(works_list))

    lines = []
    lines.append("# 跨作品 Framework 规律报告")
    lines.append(f"\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"\n**分析基础**：{n_works} 部作品" +
                 (f"（{' / '.join(works_set)}）" if works_set else "") +
                 f"，词库共 {vocab.get('stats', {}).get('total_terms', 0)} 个词条\n")

    # ── 1. 可靠性分布 ────────────────────────────────────────────────────────
    lines.append("---\n## 一、词条可靠性分布\n")
    lines.append("| 模块 | 总词条 | ✅ 跨作品验证 | ⚠️ 单作品 | 📋 预定义 |")
    lines.append("|------|--------|-------------|----------|---------|")

    for mod_id in CHAPTER_MODULES:
        terms = vocab.get("terms", {}).get(mod_id, {})
        if not terms: continue
        v = sum(1 for t in terms.values() if reliability_tier(t, n_works) == "verified")
        ten = sum(1 for t in terms.values() if reliability_tier(t, n_works) == "tentative")
        d = sum(1 for t in terms.values() if reliability_tier(t, n_works) == "defined")
        label = MODULE_META[mod_id]["label"]
        lines.append(f"| {label} | {len(terms)} | {v} | {ten} | {d} |")

    # ── 2. 跨作品共有词条（核心规律）────────────────────────────────────────
    lines.append("\n---\n## 二、跨作品共有词条（✅ 已验证）\n")
    lines.append("> 这些词条在多部作品中均出现，是叙事的普遍构件，建议作为生成器的强默认值。\n")

    has_verified = False
    for mod_id in CHAPTER_MODULES:
        terms = vocab.get("terms", {}).get(mod_id, {})
        verified = [t for t in terms.values()
                    if reliability_tier(t, n_works) == "verified"]
        if verified:
            has_verified = True
            label = MODULE_META[mod_id]["label"]
            lines.append(f"**{label}**")
            lines.append("")
            lines.append("| 词条 | 出现作品数 | 作品列表 |")
            lines.append("|------|-----------|---------|")
            for t in sorted(verified, key=lambda x: -x.get("usage_count", 0)):
                works_str = "、".join(t.get("works_used_in", []))
                lines.append(f"| {t['label']} | {t.get('usage_count', 0)}/{n_works} | {works_str} |")
            lines.append("")

    if not has_verified:
        lines.append("_（目前作品数量不足，需分析更多作品后才能找出跨作品共有词条）_\n")

    # ── 3. 各作品特有词条（风格差异）────────────────────────────────────────
    if n_works >= 2:
        lines.append("\n---\n## 三、各作品特有词条（⚠️ 风格差异）\n")
        lines.append("> 只出现在单一作品中，反映该作品独特的叙事选择，不建议作为通用默认值。\n")

        # 按作品分组展示单一出现词条
        work_unique: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for mod_id in CHAPTER_MODULES:
            terms = vocab.get("terms", {}).get(mod_id, {})
            for t in terms.values():
                if reliability_tier(t, n_works) == "tentative":
                    for w in t.get("works_used_in", []):
                        work_unique[w][mod_id].append(t["label"])

        for work, mods in sorted(work_unique.items()):
            lines.append(f"### {work}\n")
            for mod_id, labels in mods.items():
                label = MODULE_META.get(mod_id, {}).get("label", mod_id)
                lines.append(f"- **{label}**：{'、'.join(labels)}")
            lines.append("")

    # ── 4. 大 framework 节点规律 ─────────────────────────────────────────────
    lines.append("\n---\n## 四、大 Framework 节点规律\n")

    # 从 comparator 数据获取（若有）
    if comparator and "macro_sequences" in comparator:
        seqs = comparator["macro_sequences"]
        node_counts = comparator.get("macro_node_work_count", {})
        n_c = comparator.get("meta", {}).get("works_analyzed", n_works)

        lines.append("**各作品大 framework 结构序列**\n")
        for work_title, seq in seqs.items():
            lines.append(f"*{work_title}*")
            for i, nodes in enumerate(seq, 1):
                lines.append(f"- 第 {i} 章：{'→'.join(nodes) if nodes else '（无）'}")
            lines.append("")

        if node_counts:
            lines.append("**跨作品共有宏观节点**\n")
            lines.append("| 节点 | 出现作品数 |")
            lines.append("|------|-----------|")
            for node, cnt in sorted(node_counts.items(), key=lambda x: -x[1]):
                lines.append(f"| {node} | {cnt}/{n_c} |")
            lines.append("")
    else:
        # 从词库的 macro_framework_basic 模块读取
        macro_terms = vocab.get("terms", {}).get("macro_framework_basic", {})
        lines.append("**词库中定义的宏观节点（基础节点）**\n")
        lines.append("| 节点 | 定义 |")
        lines.append("|------|------|")
        for t in sorted(macro_terms.values(), key=lambda x: x.get("term_id", "")):
            lines.append(f"| {t['label']} | {t.get('abstract_definition', '')[:50]}… |")
        lines.append("\n_（运行 framework_comparator.py 后可展示跨作品节点序列对比）_\n")

    # ── 5. 词条共现规律 ──────────────────────────────────────────────────────
    if comparator and comparator.get("top_cooccurrence"):
        lines.append("\n---\n## 五、高频词条共现（叙事组合规律）\n")
        lines.append("> 以下词条对频繁在同一章节中共同出现，揭示叙事策略的组合模式。\n")
        lines.append("| 词条 A | 词条 B | 共现次数 |")
        lines.append("|--------|--------|---------|")
        for item in comparator["top_cooccurrence"][:12]:
            a, b = item["pair"]
            a_l = a.split(":", 1)[1] if ":" in a else a
            b_l = b.split(":", 1)[1] if ":" in b else b
            lines.append(f"| {a_l} | {b_l} | {item['count']} |")

    # ── 6. 对下游的接入建议 ──────────────────────────────────────────────────
    lines.append("\n---\n## 六、接入建议\n")
    verified_counts = {}
    for mod_id in CHAPTER_MODULES:
        terms = vocab.get("terms", {}).get(mod_id, {})
        v = sum(1 for t in terms.values() if reliability_tier(t, n_works) == "verified")
        if v > 0:
            verified_counts[MODULE_META[mod_id]["label"]] = v

    if verified_counts:
        lines.append("**推荐作为生成器强默认值的模块**（已跨作品验证）：\n")
        for label, cnt in sorted(verified_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {label}：{cnt} 个验证词条")
        lines.append("")

    lines.append("**可靠性使用建议**：\n")
    lines.append("- `reliability: verified` → 作为生成器的 `system_default` 强约束")
    lines.append("- `reliability: tentative` → 作为候选池，由生成器按场景挑选")
    lines.append("- `reliability: defined` → 作为扩展备选，LLM 可自由使用")
    lines.append("")
    lines.append("**与 analyze_stories 接口对齐**：")
    lines.append("- `recommended_framework.json` 的结构与 Workflow A 输出的 `component_vocabulary` 完全兼容")
    lines.append("- 词条的 `normalized_hint` 字段填入了词库中的 `abstract_definition`，可直接用于生成提示")

    lines.append("\n---\n_报告由 framework_synthesizer.py 自动生成_")
    return "\n".join(lines)


# ── 接入说明 ──────────────────────────────────────────────────────────────────

def build_integration_notes(vocab: dict, min_usage: int) -> str:
    n_works = vocab.get("stats", {}).get("works_analyzed", 1)
    lines = []
    lines.append("# 接入说明 — Framework 词库交付包\n")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"\n分析基础：{n_works} 部小说 · {vocab.get('stats', {}).get('total_terms', 0)} 个词条\n")

    lines.append("## 文件说明\n")
    lines.append("| 文件 | 用途 |")
    lines.append("|------|------|")
    lines.append("| `recommended_framework.json` | 核心交付：直接可用的 component_vocabulary，格式与现有 framework_package schema 完全兼容 |")
    lines.append("| `vocabulary_export.json` | 完整词库，含每个词条的可靠性分级、使用统计和示例 |")
    lines.append("| `cross_novel_patterns.md` | 跨作品规律报告，适合 review 和讨论 |")
    lines.append("| `integration_notes.md` | 本文件 |\n")

    lines.append("## 如何使用 recommended_framework.json\n")
    lines.append("```python")
    lines.append("import json")
    lines.append("")
    lines.append("with open('recommended_framework.json') as f:")
    lines.append("    fw = json.load(f)")
    lines.append("")
    lines.append("# 获取章节模块（直接替换/补充你的 component_vocabulary.chapter_modules）")
    lines.append("chapter_modules = fw['component_vocabulary']['chapter_modules']")
    lines.append("")
    lines.append("# 获取宏观节点")
    lines.append("macro_components = fw['component_vocabulary']['macro_components']")
    lines.append("")
    lines.append("# 只取跨作品验证的词条作为强默认值")
    lines.append("for module in chapter_modules:")
    lines.append("    verified = [c for c in module['allowed_components']")
    lines.append("                if c['reliability'] == 'verified']")
    lines.append("    tentative = [c for c in module['allowed_components']")
    lines.append("                 if c['reliability'] == 'tentative']")
    lines.append("```\n")

    lines.append("## reliability 字段说明\n")
    lines.append("| 值 | 含义 | 建议处理 |")
    lines.append("|-----|------|---------|")
    lines.append(f"| `verified` | 已在 ≥{min_usage} 部小说中出现，跨作品验证 | 作为 `system_default` 强约束 |")
    lines.append("| `tentative` | 仅在 1 部小说中出现，待验证 | 作为候选池 |")
    lines.append("| `defined` | 系统预定义，暂无分析数据 | 作为扩展备选 |\n")

    lines.append("## reader_emotion 模块特别说明\n")
    lines.append("该模块的词条附带 `valence`（情绪效价）和 `arousal`（唤起强度）字段：\n")
    lines.append("```json")
    lines.append("{")
    lines.append('  "label": "紧张",')
    lines.append('  "valence": "negative",')
    lines.append('  "arousal": "high",')
    lines.append('  "normalized_hint": "..."')
    lines.append("}")
    lines.append("```")
    lines.append("\n生成器可利用这两个维度做情绪路径规划，而不只是依赖标签名。\n")

    lines.append("## 词库持续更新说明\n")
    lines.append("每分析一部新小说，运行：")
    lines.append("```bash")
    lines.append("python book_analyzer.py folder <章节目录>")
    lines.append("python vocabulary_manager.py pending   # 审核新词条")
    lines.append("python framework_synthesizer.py        # 重新生成交付包")
    lines.append("```")
    lines.append("\n词库会自动积累 `usage_count`，随着分析作品增多，`verified` 词条会越来越多。")

    return "\n".join(lines)


# ── 打包输出 ──────────────────────────────────────────────────────────────────

def export_package(
    vocab: dict,
    comparator: Optional[dict],
    output_dir: Path,
    min_usage: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. recommended_framework.json
    fw = build_recommended_framework(vocab, min_usage)
    fw_path = output_dir / "recommended_framework.json"
    with open(fw_path, "w", encoding="utf-8") as f:
        json.dump(fw, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {fw_path.name}")

    # 2. vocabulary_export.json
    ve = build_vocabulary_export(vocab)
    ve_path = output_dir / "vocabulary_export.json"
    with open(ve_path, "w", encoding="utf-8") as f:
        json.dump(ve, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {ve_path.name}")

    # 3. cross_novel_patterns.md
    report = build_patterns_report(vocab, comparator, min_usage)
    rp_path = output_dir / "cross_novel_patterns.md"
    rp_path.write_text(report, encoding="utf-8")
    print(f"  ✅ {rp_path.name}")

    # 4. integration_notes.md
    notes = build_integration_notes(vocab, min_usage)
    no_path = output_dir / "integration_notes.md"
    no_path.write_text(notes, encoding="utf-8")
    print(f"  ✅ {no_path.name}")


# ── 控制台摘要 ────────────────────────────────────────────────────────────────

def print_summary(vocab: dict, min_usage: int) -> None:
    n_works  = vocab.get("stats", {}).get("works_analyzed", 1)
    total    = vocab.get("stats", {}).get("total_terms", 0)
    verified = sum(
        1 for mod in CHAPTER_MODULES + MACRO_MODULES
        for t in vocab.get("terms", {}).get(mod, {}).values()
        if reliability_tier(t, n_works) == "verified"
    )
    tentative = sum(
        1 for mod in CHAPTER_MODULES + MACRO_MODULES
        for t in vocab.get("terms", {}).get(mod, {}).values()
        if reliability_tier(t, n_works) == "tentative"
    )

    print(f"\n{'='*55}")
    print(f"  Framework Synthesizer  |  {n_works} 部作品  {total} 词条")
    print(f"{'='*55}")
    print(f"  ✅ 跨作品验证  : {verified} 个 → 建议作强默认值")
    print(f"  ⚠️  单作品      : {tentative} 个 → 建议作候选池")
    print(f"  📋 预定义      : {total - verified - tentative} 个 → 备选扩展")
    print()
    print(f"  min_usage 阈值 : {min_usage}（出现在 ≥{min_usage} 部作品 = verified）")
    print(f"{'='*55}\n")


# ── 主入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="跨作品 Framework 合成与交付工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--vocab", metavar="PATH",
        default=str(VOCAB_FILE),
        help=f"词库路径（默认: {VOCAB_FILE.name}）",
    )
    parser.add_argument(
        "--comparator", metavar="PATH", default="",
        help="framework_comparator.py 输出的 JSON 数据路径（可选，用于共现分析）",
    )
    parser.add_argument(
        "--min-usage", metavar="N", type=int, default=2,
        help="跨作品验证阈值：词条出现在 ≥N 部作品中视为 verified（默认 2）",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR", default="",
        help="交付包输出目录（默认: 词库同级的 handoff_package/）",
    )
    args = parser.parse_args()

    # 加载词库
    vocab_path = Path(args.vocab)
    print(f"📖 加载词库：{vocab_path}")
    vocab = load_vocabulary(vocab_path)
    n_works = vocab.get("stats", {}).get("works_analyzed", 1)
    total   = vocab.get("stats", {}).get("total_terms", 0)
    print(f"   {n_works} 部作品 · {total} 个词条")

    # 加载比较器数据（可选）
    comp_path = Path(args.comparator) if args.comparator else None
    comparator = load_comparator_data(comp_path)
    if comparator:
        print(f"📊 加载比较数据：{comp_path.name}")

    # 输出目录
    output_dir = Path(args.output_dir) if args.output_dir else vocab_path.parent / "handoff_package"

    # 控制台摘要
    print_summary(vocab, args.min_usage)

    # 生成交付包
    print(f"📦 生成交付包 → {output_dir}/")
    export_package(vocab, comparator, output_dir, args.min_usage)

    print(f"\n✅ 完成！交付包已保存到：{output_dir}")
    print("   需要交付时，将整个输出文件夹作为词库候选包审查使用。\n")


if __name__ == "__main__":
    main()
