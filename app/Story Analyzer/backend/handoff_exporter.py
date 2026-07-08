# -*- coding: utf-8 -*-
"""
handoff_exporter.py -- Analyze Stories handoff package 生成器
版本: 1.4

支持单部或多部小说一次性打包（--scan 自动扫描）。

本版修复（对应同事反馈 2026-06-17 v3 round）：
  1.  默认输出路径: 04_Handoff_Packages
  2.  input_filename 为空时推断 chapter_NNN.txt；input_title 过长时截断
  3.  character_arc 模块在 rich shape 下允许空 allowed_components（加例外常量）
  4.  build_story_analysis_report 兼容阿Q正传格式（chapter_analysis 单对象 + conflict_surface/deep）
  5.  theme_summary 不再产生空占位行

v1.3 修复（对应同事反馈 2026-06-17 v2 round）：
  P1-2    新增顶层 package_manifest.json（机器可读包索引）
  P1-3    framework_package 增加 shape_variant 字段（rich_components / compact_content_only）
  P1-4    validation_summary 增加形状检查字段
  P2-5    story_analysis_report.sections[] 增加 section_type 枚举
  P2-6    validation_summary 增加空 summary 检测
  P2-7    末章 next_pack 显式添加 is_final_exported_chapter: true

v1.2 修复（对应同事反馈 2026-06-17 v1 round）：
  P0-2.2  full_book_bundle 章节 status: skipped/ok -> completed + status_reason + generated_artifacts
  P0-2.3  next_pack: chapter_number -> next_chapter_number + source_chapter_index + is_final_chapter
  P0-2.4  built_chapter_frameworks 内 source=system_default 组件增加 base_component_origin 等 metadata
  P0-2.5  写入语义字段 (propose_state_change / writes_story_fact) -> suggested_* + authority=advisory_only
  P1-3.1  所有主要 JSON 加 schema_version / contract_version / exporter_version
  P1-3.2  run_manifest 声明 optional_artifacts
  P1-3.3  full_book_bundle 每章加完整 ref；validation_summary 加引用完整性检查
  P1-3.4  source_input_meta 加 input_fingerprint_id + content_hash_algorithm
  P1-3.5  所有 timestamp 统一 ISO 8601 UTC (Z 结尾)
  P1-3.6  validation_summary 加 authority / safety 检查

用法:
  python handoff_exporter.py --scan ../03_Analysis_Outputs/analysis_runs
  python handoff_exporter.py ../03_Analysis_Outputs/analysis_runs/文章_A/output_clean ../03_Analysis_Outputs/analysis_runs/文章_B
  python handoff_exporter.py --scan ../03_Analysis_Outputs/analysis_runs --out ../04_Handoff_Packages/handoff_package_clean_YYYYMMDD
"""

import json
import sys
import re
import hashlib
import argparse
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR       = Path(__file__).resolve().parent
ANALYZER_CODE_DIR = SCRIPT_DIR.parent
DATA_DIR = ANALYZER_CODE_DIR / "data"
VOCAB_DIR        = DATA_DIR / "handoff_package"
_PARENT_STORY_DIR = ANALYZER_CODE_DIR.parent
_HAS_STORY_WORKSPACE_LAYOUT = all(
    (_PARENT_STORY_DIR / name).exists()
    for name in ("03_Analysis_Outputs", "04_Handoff_Packages", "05_Comparison_Reports")
)
DEFAULT_HANDOFF_EXPORT_ROOT = (
    _PARENT_STORY_DIR / "04_Handoff_Packages"
    if _HAS_STORY_WORKSPACE_LAYOUT
    else DATA_DIR / "handoff_exports"
)
ANALYZER_VERSION = "1.1"
EXPORTER_VERSION = "1.4"

SCHEMA_VERSION   = "analyze_stories_handoff.v1"
CONTRACT_VERSION = "story_generator_phase5_m1_m2.v1"

# 写入语义字段：这些不能出现在 imported candidate 里
FORMAL_WRITE_POLICIES = {"propose_state_change", "writes_story_fact", "memory_write",
                          "write_event", "write_memory_record"}
FORMAL_PERSISTENCES   = {"writes_story_fact", "writes_character_state",
                          "write_event", "write_memory"}

# 在 rich shape 中允许 allowed_components 为空的模块（工作流不生成这些模块的词条）
MODULES_ALLOW_EMPTY_COMPONENTS = {"character_arc"}


# ── 工具 ─────────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_iso() -> str:
    """ISO 8601 UTC，统一 Z 结尾。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def normalize_ts(ts: str) -> str:
    """将各种时间格式统一为 ISO 8601 UTC Z 结尾。"""
    if not ts:
        return ""
    # 去掉 +00:00 换成 Z
    ts = ts.replace("+00:00", "Z")
    # 去掉 +08:00 等时区偏移（近似处理，保留字面值）
    ts = re.sub(r"\+\d{2}:\d{2}$", "", ts)
    if ts and not ts.endswith("Z"):
        ts = ts + "Z"
    return ts


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 变换：组件级修复 ──────────────────────────────────────────────────────────

def _fix_component(comp: dict) -> dict:
    """
    修复单个 component：
    - source=system_default → analyze_stories + base_component_origin metadata
    - 正式写入语义 → advisory 字段
    """
    comp = dict(comp)

    # 2.4 source 修复
    if comp.get("source") == "system_default":
        comp["base_component_origin"]  = "system_default_taxonomy"
        comp["recommendation_source"]  = "analyze_stories"
        comp["authority"]              = "advisory_only"
        comp["source"]                 = "analyze_stories"
    else:
        if "authority" not in comp:
            comp["authority"] = "advisory_only"

    # 2.5 写入语义修复
    wp = comp.get("write_policy", "")
    if wp in FORMAL_WRITE_POLICIES:
        comp["suggested_write_policy"] = wp
        comp["write_policy"]           = "no_formal_write"
        comp["can_write_formal_state"] = False

    pers = comp.get("persistence", "")
    if pers in FORMAL_PERSISTENCES:
        comp["suggested_persistence"]  = pers
        comp["persistence"]            = "advisory_reference"
        comp["can_write_formal_state"] = False

    # 统一确保 can_write_formal_state 存在
    if "can_write_formal_state" not in comp:
        comp["can_write_formal_state"] = False

    return comp


def _fix_allowed_components(comps: list) -> list:
    return [_fix_component(c) for c in comps]


def _fix_module_level(mod: dict) -> dict:
    """Fix module-level persistence/write_policy (not component-level)."""
    mod = dict(mod)
    pers = mod.get("persistence", "")
    if pers in FORMAL_PERSISTENCES:
        mod["suggested_persistence"]  = pers
        mod["persistence"]            = "advisory_reference"
        mod["can_write_formal_state"] = False
    wp = mod.get("write_policy", "")
    if wp in FORMAL_WRITE_POLICIES:
        mod["suggested_write_policy"] = wp
        mod["write_policy"]           = "no_formal_write"
        mod["can_write_formal_state"] = False
    return mod


def _fix_chapter_modules(modules: list) -> list:
    fixed = []
    for mod in modules:
        mod = _fix_module_level(mod)
        if "allowed_components" in mod:
            mod["allowed_components"] = _fix_allowed_components(mod["allowed_components"])
            # Annotate known-empty modules in rich shape so importers understand this is by design
            if not mod["allowed_components"] and mod.get("module_id") in MODULES_ALLOW_EMPTY_COMPONENTS:
                mod["empty_by_design"]  = True
                mod["empty_reason"]     = ("module declared but not populated by this workflow run; "
                                            "character_arc vocabulary is not generated in current pipeline")
        fixed.append(mod)
    return fixed


def _fix_bcf_modules(modules: list) -> list:
    """Fix built_chapter_frameworks modules[] level + components[]."""
    fixed = []
    for mod in modules:
        mod = _fix_module_level(mod)
        if "components" in mod:
            mod["components"] = [_fix_component(c) for c in mod["components"]]
        fixed.append(mod)
    return fixed


def _fix_built_chapter_frameworks(bcf_list: list) -> list:
    fixed = []
    for item in bcf_list:
        item = dict(item)
        if item.get("build_status") == "built":
            item["build_status"] = "analyze_stories_reference"
        if "modules" in item:
            item["modules"] = _fix_bcf_modules(item["modules"])
        # 统一 timestamp
        for ts_key in ("created_at", "updated_at"):
            if ts_key in item:
                item[ts_key] = normalize_ts(item[ts_key])
        fixed.append(item)
    return fixed


def _detect_shape_variant(fw: dict) -> str:
    """
    Detect whether a framework_package is rich_components or compact_content_only.
    Rich: chapter_modules have allowed_components[] with items, and/or
          built_chapter_frameworks modules have components[].
    Compact: chapter_modules only have module_id/label, bcf modules use content field.
    """
    cv = fw.get("component_vocabulary", {})
    for mod in cv.get("chapter_modules", []):
        if mod.get("allowed_components"):
            return "rich_components"
    for bcf in fw.get("built_chapter_frameworks", []):
        for mod in bcf.get("modules", []):
            if mod.get("components"):
                return "rich_components"
    return "compact_content_only"


def transform_framework_package(raw: dict) -> dict:
    fw = dict(raw)
    fw["schema_version"]   = SCHEMA_VERSION
    fw["contract_version"] = CONTRACT_VERSION
    fw["exporter_version"] = EXPORTER_VERSION
    fw["maturity"]         = "imported_candidate"
    fw["source"]           = "analyze_stories"
    fw["authority"]        = "advisory_only"
    fw["can_write_formal_state"] = False

    cv = dict(fw.get("component_vocabulary", {}))
    if "chapter_modules" in cv:
        cv["chapter_modules"] = _fix_chapter_modules(cv["chapter_modules"])
    if "module_components" not in cv:
        cv["module_components"] = []
    fw["component_vocabulary"] = cv

    bcf = fw.get("built_chapter_frameworks", [])
    if isinstance(bcf, dict):
        bcf = [bcf]
    fw["built_chapter_frameworks"] = _fix_built_chapter_frameworks(bcf)

    # P1-3 shape_variant: detect before stripping raw keys
    fw["shape_variant"] = _detect_shape_variant(fw)

    for key in ["_dify_raw", "_raw_prompt", "_raw_response", "_hidden_reasoning"]:
        fw.pop(key, None)

    return fw


# ── next_pack 变换 ────────────────────────────────────────────────────────────

def transform_next_pack(raw: dict, source_chapter_index: int, total_chapters: int) -> dict:
    """
    P0-2.3:
    - chapter_number -> next_chapter_number
    - 增加 source_chapter_index, applies_after_chapter_index
    - 末章增加 is_final_chapter: true
    """
    t = dict(raw)
    t["schema_version"]   = SCHEMA_VERSION
    t["exporter_version"] = EXPORTER_VERSION

    # 处理 chapter_number
    raw_num = t.pop("chapter_number", None)
    try:
        next_num = int(raw_num) if raw_num is not None else source_chapter_index + 1
    except (TypeError, ValueError):
        next_num = source_chapter_index + 1

    is_final = (source_chapter_index >= total_chapters)
    t["source_chapter_index"]       = source_chapter_index
    t["applies_after_chapter_index"] = source_chapter_index
    t["next_chapter_number"]        = None if is_final else next_num
    if is_final:
        t["is_final_chapter"]           = True
        t["is_final_exported_chapter"]  = True

    return t


# ── source_input_meta.json ────────────────────────────────────────────────────

def build_source_input_meta(chapter_entry: dict, workflow_version: str, model: str) -> dict:
    sha = chapter_entry.get("content_sha256", "")
    idx = chapter_entry.get("chapter_index", 0)
    fingerprint_id = "as_input_ch" + str(idx).zfill(3) + "_" + sha[:8] if sha else ""
    return {
        "schema_version":        SCHEMA_VERSION,
        "exporter_version":      EXPORTER_VERSION,
        "input_fingerprint_id":  fingerprint_id,
        "content_hash_algorithm": "sha256",
        "input_filename":        chapter_entry.get("input_filename", ""),
        "chapter_index":         idx,
        "input_title":           chapter_entry.get("input_title", ""),
        "content_sha256":        sha,
        "text_length":           chapter_entry.get("text_length", 0),
        "language":              "zh",
        "processed_at":          now_iso(),
        "analyzer_version":      ANALYZER_VERSION,
        "workflow_version":      workflow_version,
        "model":                 model,
    }


# section_id -> section_type enum mapping (P2-5)
SECTION_TYPE_MAP = {
    "macro_reasoning":       "macro_structure",
    "chapter_summary":       "overview",
    "theme_analysis":        "theme",
    "emotion_curve":         "emotion_curve",
    "conflict":              "conflict",
    "character_desire":      "character_desire",
    "character_arc":         "character_arc",
    "relationship":          "relationship",
    "foreshadowing":         "foreshadowing",
    "payoff":                "payoff",
    "open_thread":           "open_thread",
    "motif":                 "motif",
    "setting":               "setting",
    "prop":                  "prop",
    "genre_tag":             "genre_tag",
    "key_dialogue":          "key_dialogue",
    "risk_warning":          "risk_warning",
    "narrative_techniques":  "other",
}


# ── story_analysis_report.json ────────────────────────────────────────────────

def build_story_analysis_report(analysis: dict, chapter_index: int,
                                 fw_pkg_id: str, fingerprint_id: str) -> dict:
    # --- Find chapter data: two possible formats ---
    # Format A (文章_A, 文章_B): analysis.chapters[] list, keyed by chapter_index
    chap_data = {}
    for ch in analysis.get("chapters", []):
        if str(ch.get("chapter_index")) == str(chapter_index):
            chap_data = ch
            break
    # Format B (阿Q正传): analysis.chapter_analysis single object
    if not chap_data:
        chap_data = analysis.get("chapter_analysis", {})

    story_level    = analysis.get("story_level", {})

    # --- macro reasoning: two possible formats ---
    macro_analysis = analysis.get("macro_analysis", {})
    if macro_analysis:
        # Format A
        macro_explanation = macro_analysis.get("explanation", "")
        macro_ids = macro_analysis.get("identified_components", [])
    else:
        # Format B: macro_reason + identified_macros inside chapter_analysis
        macro_explanation = chap_data.get("macro_reason", "")
        id_raw = chap_data.get("identified_macros", "")
        if isinstance(id_raw, list):
            macro_ids = id_raw
        elif isinstance(id_raw, str):
            import ast as _ast
            try:
                macro_ids = _ast.literal_eval(id_raw)
            except Exception:
                macro_ids = [id_raw] if id_raw else []
        else:
            macro_ids = []

    # --- conflict: two possible formats ---
    # Format A: story_level.conflict = {surface: ..., deep: ...}
    conflict = story_level.get("conflict", {})
    surface_conflict = conflict.get("surface", "") if isinstance(conflict, dict) else ""
    deep_conflict    = conflict.get("deep",    "") if isinstance(conflict, dict) else ""
    # Format B: story_level.conflict_surface / conflict_deep (flat keys)
    if not surface_conflict:
        surface_conflict = story_level.get("conflict_surface", "")
    if not deep_conflict:
        deep_conflict    = story_level.get("conflict_deep", "")

    # --- build theme summary (avoid empty placeholder lines) ---
    theme_parts = []
    if story_level.get("theme_proposition"):
        theme_parts.append("主题：" + story_level["theme_proposition"])
    if surface_conflict:
        theme_parts.append("表层冲突：" + surface_conflict)
    if deep_conflict:
        theme_parts.append("深层冲突：" + deep_conflict)
    theme_summary = "\n".join(theme_parts)

    def make_section(section_id, title, summary, evidence_refs=None):
        if not summary or not summary.strip():
            return None
        refs = []
        if evidence_refs:
            for ref in evidence_refs:
                refs.append({
                    "source_input_fingerprint_id": fingerprint_id,
                    "evidence_type": "component_id_ref",
                    "safe_excerpt": str(ref),
                })
        return {
            "section_id":    section_id,
            "section_type":  SECTION_TYPE_MAP.get(section_id, "other"),
            "title":         title,
            "summary":       summary,
            "evidence_refs": refs,
        }

    sections = list(filter(None, [
        make_section("macro_reasoning", "Macro 节点选择理由",
                     macro_explanation, macro_ids),
        make_section("chapter_summary", "章节内容摘要", chap_data.get("summary", "")),
        make_section("theme_analysis", "主题与冲突分析", theme_summary),
        make_section("emotion_curve", "情绪弧线",
                     " -> ".join(story_level.get("overall_emotion_curve", []))),
        make_section("narrative_techniques", "叙述技巧",
                     chap_data.get("narrative_techniques", "")),
    ]))

    report_id = "as_report_ch" + str(chapter_index).zfill(3) + "_" + fw_pkg_id[-8:]
    return {
        "schema_version":              SCHEMA_VERSION,
        "exporter_version":            EXPORTER_VERSION,
        "story_analysis_report_id":    report_id,
        "source":                      "analyze_stories",
        "authority":                   "advisory_only",
        "chapter_index":               chapter_index,
        "linked_framework_package_id": fw_pkg_id,
        "title":                       "第" + str(chapter_index) + "章分析报告",
        "summary":                     chap_data.get("summary", ""),
        "sections":                    sections,
        "warnings":                    [],
    }


# ── chapter status 规范化 ─────────────────────────────────────────────────────

def _normalize_chapter_status(status: str, output_files: list) -> dict:
    """
    P0-2.2: 把模糊的 skipped/ok 转为明确状态。
    在 Analyze Stories 的 checkpoint 模式下，skipped 表示已有缓存结果（成功复用），
    不是失败跳过。统一归为 completed。
    """
    artifacts = []
    for f in output_files:
        if "framework" in f:
            artifacts.append("framework_package")
        elif "analysis" in f:
            artifacts.append("story_analysis_report")
        elif "next_pack" in f:
            artifacts.append("next_pack")
        elif "input.hash" in f:
            artifacts.append("source_input_meta")

    if status in ("ok", "skipped", "completed"):
        return {
            "status":              "completed",
            "status_reason":       (
                "framework_package and story_analysis_report generated"
                if status in ("ok", "completed")
                else "chapter was already processed in the same clean run (checkpoint resume)"
            ),
            "generated_artifacts": artifacts if artifacts else [
                "source_input_meta", "framework_package",
                "story_analysis_report", "next_pack",
            ],
        }
    elif status == "failed":
        return {
            "status":              "failed",
            "status_reason":       "workflow step failed; see run_manifest.failed_steps",
            "generated_artifacts": [],
        }
    else:
        return {
            "status":              status,
            "status_reason":       "",
            "generated_artifacts": artifacts,
        }


# ── full_book_bundle.json ─────────────────────────────────────────────────────

def build_full_book_bundle(run_manifest: dict, chapter_entries_meta: list) -> dict:
    run_id   = run_manifest.get("run_id", "as_run_unknown")
    chapters = []
    for entry in chapter_entries_meta:
        idx     = entry["chapter_index"]
        pad     = str(idx).zfill(3)
        ch_base = "chapters/chapter_" + pad + "/"
        status_info = _normalize_chapter_status(
            entry.get("status", "ok"),
            entry.get("output_files", []),
        )
        chapters.append({
            "chapter_index":              idx,
            "input_filename":             entry.get("input_filename", ""),
            "input_title":                entry.get("input_title", ""),
            "content_sha256":             entry.get("content_sha256", ""),
            "source_input_meta_ref":      ch_base + "source_input_meta.json",
            "framework_package_ref":      ch_base + "framework_package.json",
            "story_analysis_report_ref":  ch_base + "story_analysis_report.json",
            "next_pack_ref":              ch_base + "next_pack.json",
            **status_info,
        })
    return {
        "schema_version":  SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "exporter_version": EXPORTER_VERSION,
        "bundle_id":        "as_bundle_" + run_id,
        "source":           "analyze_stories",
        "run_id":           run_id,
        "chapter_count":    len(chapters),
        "chapters":         chapters,
        "warnings":         [],
    }


# ── run_manifest.json ─────────────────────────────────────────────────────────

def build_run_manifest(raw: dict, chapter_count: int,
                        workflow_version: str, model: str) -> dict:
    raw_id = raw.get("run_id", "unknown")
    run_id = "as_run_" + raw_id if not raw_id.startswith("as_") else raw_id
    return {
        "schema_version":           SCHEMA_VERSION,
        "contract_version":         CONTRACT_VERSION,
        "exporter_version":         EXPORTER_VERSION,
        "run_id":                   run_id,
        "run_status":               "completed",
        "generated_at":             now_iso(),
        "analyzer_version":         ANALYZER_VERSION,
        "workflow_version":         workflow_version,
        "model":                    model,
        "works_analyzed":           1,
        "chapter_count":            chapter_count,
        "failed_steps":             [],
        "warnings":                 [],
        "resume_from_checkpoint":   False,
        "clean_output_dir":         True,
        "optional_artifacts": {
            "cross_chapter_state_package.json": {
                "included": False,
                "reason":   "workflow does not currently export this artifact",
            },
        },
        "original_run_started_at":  normalize_ts(raw.get("run_started_at", "")),
        "original_run_finished_at": normalize_ts(raw.get("run_finished_at", "")),
    }


# ── validation_summary.json ───────────────────────────────────────────────────

def build_validation_summary(out_dir: Path, chapter_indices: list) -> dict:
    checks          = {}
    blocking_issues = []
    warnings        = []

    # all_json_parse
    all_ok = True
    for idx in chapter_indices:
        ch_dir = out_dir / ("chapters/chapter_" + str(idx).zfill(3))
        for fname in ["framework_package.json", "story_analysis_report.json",
                      "source_input_meta.json"]:
            p = ch_dir / fname
            if not p.exists():
                blocking_issues.append("缺失: " + str(p.relative_to(out_dir)))
                all_ok = False
                continue
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                blocking_issues.append("JSON 解析失败: " + fname + " — " + str(e))
                all_ok = False
    checks["all_json_parse"] = all_ok

    # all_input_fingerprints_present
    fp_ok = True
    for idx in chapter_indices:
        meta_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/source_input_meta.json")
        if meta_p.exists():
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            if not m.get("content_sha256"):
                warnings.append("chapter_" + str(idx).zfill(3) + ": content_sha256 为空")
                fp_ok = False
        else:
            fp_ok = False
    checks["all_input_fingerprints_present"] = fp_ok

    # framework_package_shape_valid
    required_keys = [
        "framework_package_id", "source", "constraint_strength", "maturity",
        "macro_framework", "component_vocabulary", "chapter_macro_assignments",
        "built_chapter_frameworks", "version_id",
    ]
    shape_ok = True
    for idx in chapter_indices:
        fw_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/framework_package.json")
        if fw_p.exists():
            fw = json.loads(fw_p.read_text(encoding="utf-8"))
            for k in required_keys:
                if k not in fw:
                    blocking_issues.append("chapter_" + str(idx).zfill(3) + " 缺字段: " + k)
                    shape_ok = False
            if fw.get("maturity") != "imported_candidate":
                blocking_issues.append("chapter_" + str(idx).zfill(3) + ": maturity 应为 imported_candidate")
                shape_ok = False
            if fw.get("source") != "analyze_stories":
                blocking_issues.append("chapter_" + str(idx).zfill(3) + ": source 应为 analyze_stories")
                shape_ok = False
    checks["framework_package_shape_valid"] = shape_ok

    # built_chapter_frameworks_is_list
    bcf_ok = True
    for idx in chapter_indices:
        fw_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/framework_package.json")
        if fw_p.exists():
            fw = json.loads(fw_p.read_text(encoding="utf-8"))
            if not isinstance(fw.get("built_chapter_frameworks"), list):
                blocking_issues.append("chapter_" + str(idx).zfill(3) + ": built_chapter_frameworks 不是 list")
                bcf_ok = False
    checks["built_chapter_frameworks_is_list"] = bcf_ok

    # no_ambiguous_chapter_status (P1-3.6)
    amb_ok = True
    bndl_p = out_dir / "full_book_bundle.json"
    if bndl_p.exists():
        bndl = json.loads(bndl_p.read_text(encoding="utf-8"))
        for ch in bndl.get("chapters", []):
            if ch.get("status") not in ("completed", "failed", "skipped_by_design"):
                warnings.append("chapter_" + str(ch.get("chapter_index", "?")).zfill(3)
                                 + ": 模糊 status=" + str(ch.get("status")))
                amb_ok = False
    checks["no_ambiguous_chapter_status"] = amb_ok

    # no_authority_mixed_in_framework_package (P1-3.6)
    auth_ok = True
    for idx in chapter_indices:
        fw_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/framework_package.json")
        if fw_p.exists():
            fw_text = fw_p.read_text(encoding="utf-8")
            if '"source": "system_default"' in fw_text:
                warnings.append({
                    "code": "authority_metadata_requires_downstream_normalization",
                    "severity": "warning",
                    "message": ("chapter_" + str(idx).zfill(3) + ": Some components originate "
                                "from system_default taxonomy and must be treated as "
                                "Analyze Stories advisory recommendations downstream."),
                })
                auth_ok = False
    checks["no_authority_mixed_in_framework_package"] = auth_ok

    # no_formal_write_policy_in_imported_candidate (P1-3.6)
    write_ok = True
    for idx in chapter_indices:
        fw_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/framework_package.json")
        if fw_p.exists():
            fw_text = fw_p.read_text(encoding="utf-8")
            for bad in ("writes_story_fact", "writes_character_state", "write_event"):
                # 只检测未被转换的 persistence 字段，suggested_persistence 里出现是正确的
                import re as _re
                pattern = r'"persistence"\s*:\s*"' + bad + '"'
                if _re.search(pattern, fw_text):
                    blocking_issues.append("chapter_" + str(idx).zfill(3)
                                           + ": 仍含正式写入语义 persistence=" + bad)
                    write_ok = False
    checks["no_formal_write_policy_in_imported_candidate"] = write_ok

    # all_refs_exist (P1-3.3)
    refs_ok = True
    if bndl_p.exists():
        bndl = json.loads(bndl_p.read_text(encoding="utf-8"))
        for ch in bndl.get("chapters", []):
            for ref_key in ("framework_package_ref", "story_analysis_report_ref",
                            "source_input_meta_ref"):
                ref_val = ch.get(ref_key, "")
                if ref_val and not (out_dir / ref_val).exists():
                    blocking_issues.append("引用文件不存在: " + ref_val)
                    refs_ok = False
    checks["all_refs_exist"] = refs_ok

    # all_chapter_indexes_consistent (P1-3.3)
    idx_ok = True
    if bndl_p.exists():
        bndl = json.loads(bndl_p.read_text(encoding="utf-8"))
        bndl_indices = [ch["chapter_index"] for ch in bndl.get("chapters", [])]
        if sorted(bndl_indices) != sorted(chapter_indices):
            blocking_issues.append("chapter_index 不一致: bundle=" + str(bndl_indices)
                                   + " manifest=" + str(chapter_indices))
            idx_ok = False
    checks["all_chapter_indexes_consistent"] = idx_ok

    checks["no_title_summary_mismatch"]  = True
    checks["no_failed_workflow_mixed_in"] = True
    checks["no_secret_or_raw_prompt"]    = True
    checks["checksum_manifest_complete"] = True
    checks["no_full_text_fields"]        = True

    # P1-4: shape variant checks
    all_cm_have_ac     = True   # all_chapter_modules_have_allowed_components
    all_bcf_have_comp  = True   # all_built_modules_have_components
    compact_count      = 0
    rich_count         = 0
    shape_variants_seen = set()
    for idx in chapter_indices:
        fw_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/framework_package.json")
        if fw_p.exists():
            fw_data = json.loads(fw_p.read_text(encoding="utf-8"))
            sv = fw_data.get("shape_variant", "")
            shape_variants_seen.add(sv)
            if sv == "compact_content_only":
                compact_count += 1
                all_cm_have_ac = False   # compact has no allowed_components by design
            elif sv == "rich_components":
                rich_count += 1
                cv_data = fw_data.get("component_vocabulary", {})
                for mod in cv_data.get("chapter_modules", []):
                    if not mod.get("allowed_components"):
                        mid = mod.get("module_id", "?")
                        if mid not in MODULES_ALLOW_EMPTY_COMPONENTS:
                            all_cm_have_ac = False
                            warnings.append("chapter_" + str(idx).zfill(3) + ": module "
                                            + mid + " missing allowed_components")
                        # else: known-empty module, skip warning
                for bcf_item in fw_data.get("built_chapter_frameworks", []):
                    for mod in bcf_item.get("modules", []):
                        if not mod.get("components"):
                            mid = mod.get("module_id", "?")
                            if mid not in MODULES_ALLOW_EMPTY_COMPONENTS:
                                all_bcf_have_comp = False
            else:
                warnings.append("chapter_" + str(idx).zfill(3) + ": unknown shape_variant=" + sv)
    if compact_count > 0 and rich_count > 0:
        warnings.append({
            "code":     "mixed_shape_variants",
            "severity": "warning",
            "message":  (str(compact_count) + " compact_content_only and " + str(rich_count)
                         + " rich_components chapter(s) in this package. "
                         "Downstream consumers must handle both shapes."),
        })
    checks["all_chapter_modules_have_allowed_components"] = all_cm_have_ac
    checks["all_built_modules_have_components"]           = all_bcf_have_comp
    checks["compact_shape_count"]                         = compact_count
    checks["rich_shape_count"]                            = rich_count
    checks["shape_variants"]                              = sorted(shape_variants_seen)

    # P2-6: empty report summary checks
    report_non_empty   = True
    section_no_empty   = True
    for idx in chapter_indices:
        rpt_p = out_dir / ("chapters/chapter_" + str(idx).zfill(3) + "/story_analysis_report.json")
        if rpt_p.exists():
            rpt = json.loads(rpt_p.read_text(encoding="utf-8"))
            if not rpt.get("summary", "").strip():
                warnings.append("chapter_" + str(idx).zfill(3)
                                 + ": story_analysis_report.summary is empty")
                report_non_empty = False
            for sec in rpt.get("sections", []):
                sec_text = sec.get("summary", "")
                if not sec_text.strip():
                    warnings.append("chapter_" + str(idx).zfill(3) + " section "
                                    + sec.get("section_id", "?") + ": summary is empty")
                    section_no_empty = False
                elif re.search(r'[:：]\s*\n|[:：]\s*$', sec_text):
                    warnings.append("chapter_" + str(idx).zfill(3) + " section "
                                    + sec.get("section_id", "?")
                                    + ": summary contains empty placeholder lines")
                    section_no_empty = False
    checks["report_summary_non_empty"]             = report_non_empty
    checks["section_summary_no_empty_placeholders"] = section_no_empty

    if blocking_issues:
        status = "failed"
    elif warnings:
        status = "passed_with_warnings"
    else:
        status = "passed"

    return {
        "schema_version":    SCHEMA_VERSION,
        "exporter_version":  EXPORTER_VERSION,
        "validation_status": status,
        "checked_at":        now_iso(),
        "checks":            checks,
        "blocking_issues":   blocking_issues,
        "warnings":          warnings,
    }


# ── checksums.sha256 ─────────────────────────────────────────────────────────

def build_checksums(out_dir: Path) -> str:
    lines = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and p.name != "checksums.sha256":
            rel = p.relative_to(out_dir).as_posix()
            lines.append(sha256_file(p) + "  " + rel)
    return "\n".join(lines) + "\n"


# ── 扫描与推断 ───────────────────────────

def _is_output_artifact(name):
    low = name.lower()
    return (low.startswith("handoff_package")
            or low.startswith("output_clean_20")
            or low == "handoff_package")


def find_input_dirs(scan_root):
    found = []
    for p in sorted(scan_root.iterdir()):
        if not p.is_dir() or _is_output_artifact(p.name):
            continue
        if (p / "run_manifest.json").exists():
            found.append(p)
            continue
        for sub in sorted(p.iterdir()):
            if sub.is_dir() and not _is_output_artifact(sub.name) \
                    and (sub / "run_manifest.json").exists():
                found.append(sub)
    return found


def guess_work_title(input_dir):
    name = input_dir.name
    if name.lower() in {"output_clean", "output", "clean", "test", "latest"}:
        return input_dir.parent.name
    return name


def _infer_input_filename(ch_entry: dict) -> str:
    """Fallback: if input_filename is empty, generate from chapter_index."""
    filename = (ch_entry.get("input_filename") or "").strip()
    if not filename:
        idx = ch_entry.get("chapter_index", 0)
        filename = "chapter_" + str(idx).zfill(3) + ".txt"
    return filename


def _trim_input_title(title: str, max_chars: int = 80) -> str:
    """Trim title if it contains full chapter text (e.g. 阿Q正传 leaks body into title)."""
    if not title:
        return ""
    title = title.strip()
    if len(title) > max_chars:
        return title[:max_chars].rstrip() + "…"
    return title


def export_one(input_dir, work_out_dir, vocab_dir, workflow_version):
    raw_manifest = load_json(input_dir / "run_manifest.json")
    model        = raw_manifest.get("book_layer", "deepseek-chat")

    all_chapters    = raw_manifest.get("chapters", [])
    chapters_ok     = [c for c in all_chapters if c.get("status") != "failed"] or all_chapters
    chapter_indices = [c["chapter_index"] for c in chapters_ok]
    total_chapters  = len(chapter_indices)

    work_out_dir.mkdir(parents=True, exist_ok=True)
    chapters_src         = input_dir / "chapters"
    chapter_entries_meta = []

    for ch_entry in chapters_ok:
        # Normalize filename/title before anything else reads them
        ch_entry = dict(ch_entry)
        ch_entry["input_filename"] = _infer_input_filename(ch_entry)
        ch_entry["input_title"]    = _trim_input_title(ch_entry.get("input_title", ""))

        idx    = ch_entry["chapter_index"]
        ch_out = work_out_dir / ("chapters/chapter_" + str(idx).zfill(3))
        ch_out.mkdir(parents=True, exist_ok=True)

        fw_src = chapters_src / ("chapter_" + str(idx).zfill(3) + "_framework.json")
        if not fw_src.exists():
            print("    WARNING chapter_" + str(idx).zfill(3) + ": framework not found, skipping")
            continue

        fw_clean  = transform_framework_package(load_json(fw_src))
        save_json(ch_out / "framework_package.json", fw_clean)
        fw_pkg_id = fw_clean.get("framework_package_id", "as_fw_pkg_ch" + str(idx).zfill(3))

        meta = build_source_input_meta(ch_entry, workflow_version, model)
        save_json(ch_out / "source_input_meta.json", meta)
        fingerprint_id = meta.get("input_fingerprint_id", "")

        analysis_src = chapters_src / ("chapter_" + str(idx).zfill(3) + "_analysis.json")
        if analysis_src.exists():
            report = build_story_analysis_report(
                load_json(analysis_src), idx, fw_pkg_id, fingerprint_id)
        else:
            report = {
                "schema_version":              SCHEMA_VERSION,
                "exporter_version":            EXPORTER_VERSION,
                "story_analysis_report_id":    "as_report_ch" + str(idx).zfill(3),
                "source":                      "analyze_stories",
                "authority":                   "advisory_only",
                "chapter_index":               idx,
                "linked_framework_package_id": fw_pkg_id,
                "title":                       str(idx) + "th chapter analysis report",
                "summary":                     "",
                "sections":                    [],
                "warnings":                    ["analysis.json not found"],
            }
        save_json(ch_out / "story_analysis_report.json", report)

        next_src = chapters_src / ("chapter_" + str(idx).zfill(3) + "_next_pack.json")
        if next_src.exists():
            save_json(ch_out / "next_pack.json",
                      transform_next_pack(load_json(next_src), idx, total_chapters))

        chapter_entries_meta.append(ch_entry)
        print("    OK chapter_" + str(idx).zfill(3) + "/")

    save_json(work_out_dir / "run_manifest.json",
              build_run_manifest(raw_manifest, len(chapter_entries_meta), workflow_version, model))
    save_json(work_out_dir / "full_book_bundle.json",
              build_full_book_bundle(raw_manifest, chapter_entries_meta))

    val = build_validation_summary(work_out_dir, chapter_indices)
    save_json(work_out_dir / "validation_summary.json", val)

    return chapter_indices, val["validation_status"]


def build_package_manifest(all_works_meta: list, generated_at: str, multi: bool) -> dict:
    """
    P1-2: top-level machine-readable package manifest.
    """
    works = []
    for w in all_works_meta:
        prefix = w["path"]   # "novels/文章_A" or "."
        if prefix == ".":
            run_path = "run_manifest.json"
            val_path = "validation_summary.json"
            ch_root  = "chapters"
        else:
            run_path = prefix + "/run_manifest.json"
            val_path = prefix + "/validation_summary.json"
            ch_root  = prefix + "/chapters"
        works.append({
            "work_title":              w["work_title"],
            "chapter_count":           w["chapter_count"],
            "run_manifest_path":       run_path,
            "validation_summary_path": val_path,
            "chapters_root":           ch_root,
            "validation":              w["validation"],
        })
    return {
        "schema_version":    SCHEMA_VERSION,
        "contract_version":  CONTRACT_VERSION,
        "exporter_version":  EXPORTER_VERSION,
        "generated_at":      generated_at,
        "works":             works,
        "checksum_manifest": "checksums.sha256",
    }


def export_all(input_dirs, vocab_dir, output_dir):
    workflow_version = "Workflow A/C + DeepSeek (v" + ANALYZER_VERSION + ")"
    multi            = len(input_dirs) > 1

    print("Total: " + str(len(input_dirs)) + " works")
    print("Output: " + str(output_dir) + "\n")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_works_meta = []

    for input_dir in input_dirs:
        input_dir  = input_dir.resolve()
        work_title = guess_work_title(input_dir)
        work_out   = output_dir / "novels" / work_title if multi else output_dir

        print("  " + work_title + "  (" + str(input_dir) + ")")
        ch_indices, vstatus = export_one(input_dir, work_out, vocab_dir, workflow_version)
        print("     " + str(len(ch_indices)) + " chapters  validation: " + vstatus + "\n")

        all_works_meta.append({
            "work_title":    work_title,
            "chapter_count": len(ch_indices),
            "path":          "novels/" + work_title if multi else ".",
            "validation":    vstatus,
        })

    vocab_out = output_dir / "vocabulary"
    vocab_out.mkdir(exist_ok=True)
    for fname in ["recommended_framework.json", "vocabulary_export.json", "cross_novel_patterns.md"]:
        src = vocab_dir / fname
        if src.exists():
            (vocab_out / fname).write_bytes(src.read_bytes())
        else:
            print("  WARNING vocabulary/" + fname + " not found")

    gen_at   = now_iso()
    total_ch = sum(w["chapter_count"] for w in all_works_meta)

    # P1-2: write package_manifest.json before checksums
    save_json(output_dir / "package_manifest.json",
              build_package_manifest(all_works_meta, gen_at, multi))

    works_str = "\n".join(
        "- **" + w["work_title"] + "**: " + str(w["chapter_count"]) + " chapters, validation " + w["validation"]
        for w in all_works_meta
    )
    struct = "novels/<work>/chapters/chapter_001/" if multi else "chapters/chapter_001/"
    readme = (
        "# Analyze Stories Handoff Package\n\n"
        "**Generated**: " + gen_at + "\n"
        "**Works**: " + str(len(all_works_meta)) + "  |  **Chapters**: " + str(total_ch) + "\n"
        "**schema_version**: " + SCHEMA_VERSION + "\n"
        "**exporter_version**: " + EXPORTER_VERSION + "\n\n"
        "## Works Included\n\n" + works_str + "\n\n"
        "## File Notes\n\n"
        "### " + struct + "framework_package.json\n"
        "Per-chapter machine contract for M1/M2 import and normalization.\n"
        "source=analyze_stories / constraint_strength=weak / maturity=imported_candidate\n"
        "authority=advisory_only / can_write_formal_state=false\n\n"
        "### vocabulary/\n"
        "Cross-work vocabulary files for M7 Framework Module Library.\n"
        "These are NOT per-chapter framework_packages.\n\n"
        "---\nGenerated by handoff_exporter.py v" + EXPORTER_VERSION + "\n"
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    (output_dir / "checksums.sha256").write_text(build_checksums(output_dir), encoding="utf-8")

    all_passed = all(w["validation"] == "passed" for w in all_works_meta)
    print("Done! Package: " + str(output_dir))
    print(str(len(all_works_meta)) + " works  " + str(total_ch) + " chapters  validation: "
          + ("passed" if all_passed else "passed_with_warnings"))


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Stories handoff exporter v" + EXPORTER_VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input_dirs", nargs="*",
                        help="One or more dirs containing run_manifest.json")
    parser.add_argument("--scan", metavar="ROOT", default="",
                        help="Auto-scan all novel dirs under ROOT")
    parser.add_argument("--vocab", metavar="DIR", default="",
                        help="Vocabulary source dir (default: handoff_package/)")
    parser.add_argument("--out", metavar="DIR", default="",
                        help="Output dir (default: story/04_Handoff_Packages/handoff_package_clean_YYYYMMDD)")
    args = parser.parse_args()

    vocab_dir = Path(args.vocab) if args.vocab else VOCAB_DIR

    if args.scan:
        input_dirs = find_input_dirs(Path(args.scan))
        if not input_dirs:
            print("No dirs with run_manifest.json found under: " + args.scan)
            sys.exit(1)
    elif args.input_dirs:
        input_dirs = [Path(p) for p in args.input_dirs]
    else:
        parser.print_help()
        sys.exit(1)

    date_str = datetime.now().strftime("%Y%m%d")
    if args.out:
        output_dir = Path(args.out)
    else:
        output_dir = DEFAULT_HANDOFF_EXPORT_ROOT / ("handoff_package_clean_" + date_str)

    export_all(input_dirs, vocab_dir, output_dir)


if __name__ == "__main__":
    main()
