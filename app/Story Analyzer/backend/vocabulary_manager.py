"""
vocabulary_manager.py — 故事拆解器框架词库管理器
版本: 1.0
功能:
  1. 从 framework_package 提取本次分析使用的词条
  2. 对比词库，判断是"已有词"/"AI自审通过"/"需人工确认"
  3. 生成待审核报告，供用户确认后入库
  4. 提供词库查询接口（供 book_analyzer.py 分析前加载）
"""

import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
ANALYZER_CODE_DIR = BACKEND_DIR.parent
DATA_DIR = ANALYZER_CODE_DIR / "data"
VOCAB_FILE = DATA_DIR / "framework_vocabulary.json"

# 只管理这些模块里的词（chapter_function 里的系统固定词也纳入，但宽松处理）
MANAGED_MODULES = {
    "chapter_function",
    "reader_emotion",
    "character_desire",
    "conflict",
    "information_release",
    "style_pacing",
    "character_arc",
    "macro_framework_basic",
    "macro_framework_graph",
}

# 适合做词库标签匹配的模块（标签型）；其余模块是描述型，不做词库匹配
LABEL_MODULES = {
    "chapter_function",
    "reader_emotion",
    "style_pacing",
    "character_arc",
}

# 这些标签模式是动态生成的（伏笔回收F001等），不作为词库词条
DYNAMIC_LABEL_PATTERNS = [
    re.compile(r"^伏笔回收[A-Z]\d+$"),
    re.compile(r"^回收[A-Z]\d+$"),
]

# AI自审：相似度阈值，超过此比例视为"已有词的近似表达"，自动合并
SIMILARITY_THRESHOLD = 0.75


# ── 词库加载/保存 ──────────────────────────────────────────────────────────────

def load_vocabulary() -> dict:
    """加载词库文件，不存在时返回空结构。"""
    if not VOCAB_FILE.exists():
        return _empty_vocabulary()
    with open(VOCAB_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_vocabulary(vocab: dict) -> None:
    """保存词库，更新 last_updated 时间戳和 stats。"""
    vocab["last_updated"] = _now()
    _recount_stats(vocab)
    with open(VOCAB_FILE, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)
    print(f"[词库] 已保存至 {VOCAB_FILE}")


def _empty_vocabulary() -> dict:
    return {
        "schema_version": "1.0",
        "created_at": _now(),
        "last_updated": _now(),
        "managed_modules": list(MANAGED_MODULES),
        "stats": {"total_terms": 0, "total_pending": 0, "works_analyzed": 0, "by_module": {}},
        "terms": {m: {} for m in MANAGED_MODULES},
        "pending_review": [],
    }


# ── 词库查询（供 book_analyzer.py 调用）────────────────────────────────────────

def get_vocabulary_context(vocab: Optional[dict] = None) -> str:
    """
    返回词库摘要字符串，用于在 LLM prompt 中提示现有词条。
    格式：每个模块一段，列出标签和简短定义，LLM 分析时优先使用已有词。
    """
    if vocab is None:
        vocab = load_vocabulary()

    lines = ["=== 框架词库（分析时优先使用以下已有词条，如需创建新词请在输出中标注 [NEW_TERM]）===\n"]
    for module_id, terms in vocab.get("terms", {}).items():
        active_terms = {k: v for k, v in terms.items() if v.get("status") == "active"}
        if not active_terms:
            continue
        lines.append(f"【{module_id}】")
        for t in active_terms.values():
            lines.append(f"  • {t['label']}：{t['abstract_definition'][:60]}…")
        lines.append("")
    return "\n".join(lines)


def find_term(label: str, module_id: str, vocab: Optional[dict] = None) -> Optional[dict]:
    """精确查找：在指定模块中找到 label 完全匹配的词条，返回词条 dict 或 None。"""
    if vocab is None:
        vocab = load_vocabulary()
    terms = vocab.get("terms", {}).get(module_id, {})
    for term in terms.values():
        if term.get("label") == label:
            return term
    return None


# ── 提取分析结果中的词条 ────────────────────────────────────────────────────────

def _parse_labels_from_content(content: str) -> list[str]:
    """
    从 v2 格式的 content 字符串中解析出标签列表。
    支持格式：
    - 顿号/逗号分隔："世界铺垫、触发推进、高潮执行"
    - JSON 列表中的 arc_stage 字段
    - style_pacing 的 style_features 列表
    """
    if not content or not content.strip():
        return []

    content = content.strip()

    # 尝试 JSON 解析
    if content.startswith(("{", "[")):
        try:
            data = json.loads(content)
            labels = []
            if isinstance(data, dict):
                # style_pacing: {"pacing": "...", "style_features": ["高信息密度", ...]}
                for feat in data.get("style_features", []):
                    if isinstance(feat, str):
                        labels.append(feat.strip())
            elif isinstance(data, list):
                # character_arc: [{"arc_stage": "从麻木到觉醒", ...}]
                for item in data:
                    if isinstance(item, dict):
                        stage = item.get("arc_stage", "")
                        if stage:
                            labels.append(stage.strip())
            return [l for l in labels if l]
        except (json.JSONDecodeError, TypeError):
            pass

    # 顿号/逗号分隔的标签字符串
    labels = re.split(r"[、，,]", content)
    return [l.strip().replace(" [NEW_TERM]", "").replace("[NEW_TERM]", "") for l in labels if l.strip()]


def extract_components_from_framework(framework_package: dict) -> dict:
    """
    从 framework_package 提取每个模块使用的组件标签。
    兼容 v1（components 列表）和 v2（content 字符串）两种格式。
    只对 LABEL_MODULES 中的标签型模块做提取，描述型模块跳过。
    返回: {module_id: [{label, normalized_hint}, ...]}
    """
    result = {}
    bcf = framework_package.get("built_chapter_frameworks", [])
    if not bcf:
        return result

    ch_fw = bcf[0] if isinstance(bcf, list) else next(iter(bcf.values()), {})
    for module in ch_fw.get("modules", []):
        module_id = module.get("module_id", module.get("name", ""))
        if module_id not in LABEL_MODULES:
            continue
        comps = []

        # v1 格式：components 列表
        for comp in module.get("components", []):
            label = comp.get("label", "").strip()
            hint  = comp.get("normalized_hint", "").strip()
            if not label:
                continue
            if any(p.match(label) for p in DYNAMIC_LABEL_PATTERNS):
                continue
            comps.append({"label": label, "normalized_hint": hint})

        # v2 格式：content 字符串（仅当 components 为空时回退）
        if not comps and module.get("content"):
            for label in _parse_labels_from_content(module["content"]):
                label_clean = label.replace(" [NEW_TERM]", "").replace("[NEW_TERM]", "").strip()
                if not label_clean:
                    continue
                if any(p.match(label_clean) for p in DYNAMIC_LABEL_PATTERNS):
                    continue
                is_new = "[NEW_TERM]" in label
                comps.append({
                    "label": label_clean,
                    "normalized_hint": f"[NEW_TERM] {label_clean}" if is_new else "",
                })

        if comps:
            result[module_id] = comps
    return result


# ── AI 自审：相似度比对 ──────────────────────────────────────────────────────────

def _char_similarity(a: str, b: str) -> float:
    """简单字符重叠相似度（Jaccard），用于快速过滤明显不同的词。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_similar_term(label: str, module_id: str, vocab: dict) -> Optional[dict]:
    """
    在指定模块中查找与 label 相似度超过阈值的词条。
    返回最相似的词条 dict，或 None。
    """
    terms = vocab.get("terms", {}).get(module_id, {})
    best_score, best_term = 0.0, None
    for term in terms.values():
        if term.get("status") != "active":
            continue
        score = _char_similarity(label, term["label"])
        if score > best_score:
            best_score, best_term = score, term
    if best_score >= SIMILARITY_THRESHOLD:
        return best_term
    return None


# ── 核心：分析后处理（主流程）───────────────────────────────────────────────────

def process_chapter_components(
    framework_package: dict,
    work_title: str,
    chapter_number: int,
    vocab: Optional[dict] = None,
    auto_approve_similar: bool = True,
) -> dict:
    """
    处理一章分析结果：
    1. 提取所有组件词条
    2. 精确匹配已有词 → 更新 usage_count
    3. AI相似度匹配 → 记录为近似词（可选自动合并）
    4. 无匹配的新词 → 加入 pending_review
    返回处理报告 dict。
    """
    if vocab is None:
        vocab = load_vocabulary()

    components = extract_components_from_framework(framework_package)
    report = {
        "work": work_title,
        "chapter": chapter_number,
        "processed_at": _now(),
        "exact_matches": [],
        "similar_matches": [],
        "new_terms_pending": [],
        "summary": "",
    }

    for module_id, comps in components.items():
        for comp in comps:
            label = comp["label"]
            hint  = comp["normalized_hint"]

            # 1. 精确匹配
            existing = find_term(label, module_id, vocab)
            if existing:
                _increment_usage(existing, work_title, chapter_number, hint, vocab, module_id)
                report["exact_matches"].append({"module": module_id, "label": label,
                                                 "term_id": existing["term_id"]})
                continue

            # 2. AI 相似度匹配
            similar = find_similar_term(label, module_id, vocab)
            if similar and auto_approve_similar:
                report["similar_matches"].append({
                    "module": module_id,
                    "new_label": label,
                    "matched_to": similar["label"],
                    "term_id": similar["term_id"],
                    "action": "auto_merged",
                })
                # 把这个 hint 作为该词条的一个新示例（不改变标签）
                _add_example_to_term(similar, work_title, chapter_number, hint, vocab, module_id)
                continue
            elif similar:
                report["similar_matches"].append({
                    "module": module_id,
                    "new_label": label,
                    "matched_to": similar["label"],
                    "term_id": similar["term_id"],
                    "action": "needs_confirmation",
                })

            # 3. 真正的新词 → pending
            pending_entry = {
                "pending_id": _gen_pending_id(module_id, label),
                "module": module_id,
                "label": label,
                "normalized_hint_example": hint,
                "work": work_title,
                "chapter": chapter_number,
                "proposed_at": _now(),
                "ai_note": (
                    f"与库中词条「{similar['label']}」相似度 "
                    f"{_char_similarity(label, similar['label']):.0%}，但未达自动合并阈值。"
                    if similar else "库中无相似词条，为全新词。"
                ),
                "status": "pending",
            }
            # 避免重复加入
            already = [p for p in vocab["pending_review"] if p["label"] == label and p["module"] == module_id]
            if not already:
                vocab["pending_review"].append(pending_entry)
            report["new_terms_pending"].append({"module": module_id, "label": label})

    # 更新 works_analyzed
    all_works = set()
    for module_terms in vocab.get("terms", {}).values():
        for t in module_terms.values():
            all_works.update(t.get("works_used_in", []))
    all_works.add(work_title)
    vocab["stats"]["works_analyzed"] = len(all_works)

    report["summary"] = (
        f"精确匹配 {len(report['exact_matches'])} 个，"
        f"相似合并 {len(report['similar_matches'])} 个，"
        f"新词待审 {len(report['new_terms_pending'])} 个。"
    )
    return report, vocab


# ── 待审核词条管理 ────────────────────────────────────────────────────────────

def show_pending_review(vocab: Optional[dict] = None) -> None:
    """打印所有待审核的新词条，供用户查看。"""
    if vocab is None:
        vocab = load_vocabulary()
    pending = [p for p in vocab.get("pending_review", []) if p.get("status") == "pending"]
    if not pending:
        print("[词库] 没有待审核的新词条。")
        return

    print(f"\n{'='*60}")
    print(f"【待审核新词条】共 {len(pending)} 个")
    print(f"{'='*60}")
    for i, p in enumerate(pending, 1):
        print(f"\n#{i}  pending_id: {p['pending_id']}")
        print(f"  模块: {p['module']}")
        print(f"  新词: 「{p['label']}」")
        print(f"  示例: {p['normalized_hint_example'][:100]}")
        print(f"  来源: {p['work']} 第{p['chapter']}章")
        print(f"  AI备注: {p['ai_note']}")
    print(f"\n{'='*60}")
    print("使用 approve_pending(pending_id, abstract_definition) 确认入库")
    print("使用 reject_pending(pending_id) 拒绝词条")


def approve_pending(
    pending_id: str,
    abstract_definition: str,
    vocab: Optional[dict] = None,
    save: bool = True,
) -> None:
    """
    人工确认：将 pending 词条正式入库。
    abstract_definition: 你对这个新词的跨故事抽象定义（必须提供）。
    """
    if vocab is None:
        vocab = load_vocabulary()

    found = None
    for p in vocab["pending_review"]:
        if p["pending_id"] == pending_id and p["status"] == "pending":
            found = p
            break

    if not found:
        print(f"[词库] 未找到 pending_id={pending_id}，或已处理。")
        return

    module_id = found["module"]
    label     = found["label"]

    # 生成新 term_id
    existing_ids = list(vocab["terms"].get(module_id, {}).keys())
    prefix = module_id[:2]  # cf / re / cd / co / ir / sp
    existing_nums = [int(k.split("_")[1]) for k in existing_ids if "_" in k and k.split("_")[1].isdigit()]
    next_num = (max(existing_nums) + 1) if existing_nums else 1
    term_id = f"{prefix}_{next_num:03d}"

    new_term = {
        "term_id": term_id,
        "label": label,
        "abstract_definition": abstract_definition,
        "module": module_id,
        "usage_count": 1,
        "works_used_in": [found["work"]],
        "chapter_examples": [
            {
                "work": found["work"],
                "chapter": found["chapter"],
                "hint": found["normalized_hint_example"],
            }
        ],
        "status": "active",
        "added_by": "human_confirmed",
        "created_at": _now(),
    }

    vocab["terms"].setdefault(module_id, {})[term_id] = new_term
    found["status"] = "approved"

    print(f"[词库] ✓ 已入库：[{module_id}] 「{label}」→ {term_id}")
    if save:
        save_vocabulary(vocab)


def reject_pending(pending_id: str, vocab: Optional[dict] = None, save: bool = True) -> None:
    """拒绝一个待审核词条（标记为 rejected，不入库）。"""
    if vocab is None:
        vocab = load_vocabulary()
    for p in vocab["pending_review"]:
        if p["pending_id"] == pending_id and p["status"] == "pending":
            p["status"] = "rejected"
            print(f"[词库] ✗ 已拒绝：「{p['label']}」（{pending_id}）")
            if save:
                save_vocabulary(vocab)
            return
    print(f"[词库] 未找到 pending_id={pending_id}")


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _increment_usage(term: dict, work: str, chapter: int, hint: str, vocab: dict, module_id: str) -> None:
    term["usage_count"] = term.get("usage_count", 0) + 1
    if work not in term.get("works_used_in", []):
        term.setdefault("works_used_in", []).append(work)
    term.setdefault("chapter_examples", []).append(
        {"work": work, "chapter": chapter, "hint": hint}
    )


def _add_example_to_term(term: dict, work: str, chapter: int, hint: str, vocab: dict, module_id: str) -> None:
    """为近似词条追加一个新示例，但不改变标签。"""
    term["usage_count"] = term.get("usage_count", 0) + 1
    if work not in term.get("works_used_in", []):
        term.setdefault("works_used_in", []).append(work)
    term.setdefault("chapter_examples", []).append(
        {"work": work, "chapter": chapter, "hint": hint, "original_label": hint}
    )


def _gen_pending_id(module_id: str, label: str) -> str:
    raw = f"{module_id}::{label}::{_now()}"
    return "pnd_" + hashlib.md5(raw.encode()).hexdigest()[:8]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _recount_stats(vocab: dict) -> None:
    by_module = {}
    total = 0
    for mod, terms in vocab.get("terms", {}).items():
        active = sum(1 for t in terms.values() if t.get("status") == "active")
        by_module[mod] = active
        total += active
    vocab["stats"]["total_terms"] = total
    vocab["stats"]["total_pending"] = sum(
        1 for p in vocab.get("pending_review", []) if p.get("status") == "pending"
    )
    vocab["stats"]["by_module"] = by_module


# ── CLI 入口（直接运行此脚本时可用）────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if not args or args[0] == "show":
        # 显示词库统计
        vocab = load_vocabulary()
        stats = vocab.get("stats", {})
        print(f"\n{'='*50}")
        print("【框架词库统计】")
        print(f"  总词条数: {stats.get('total_terms', 0)}")
        print(f"  待审核:   {stats.get('total_pending', 0)}")
        print(f"  已分析作品: {stats.get('works_analyzed', 0)}")
        print(f"  各模块:")
        for mod, cnt in stats.get("by_module", {}).items():
            print(f"    {mod}: {cnt} 个词条")
        print(f"{'='*50}\n")
        show_pending_review(vocab)

    elif args[0] == "pending":
        show_pending_review()

    elif args[0] == "approve" and len(args) >= 3:
        pending_id = args[1]
        definition = " ".join(args[2:])
        approve_pending(pending_id, definition)

    elif args[0] == "reject" and len(args) >= 2:
        reject_pending(args[1])

    elif args[0] == "context":
        print(get_vocabulary_context())

    else:
        print("用法:")
        print("  python vocabulary_manager.py show           # 显示词库统计和待审核")
        print("  python vocabulary_manager.py pending        # 显示待审核词条")
        print("  python vocabulary_manager.py context        # 显示 LLM prompt 上下文摘要")
        print("  python vocabulary_manager.py approve <id> <定义>  # 确认入库")
        print("  python vocabulary_manager.py reject <id>   # 拒绝词条")
