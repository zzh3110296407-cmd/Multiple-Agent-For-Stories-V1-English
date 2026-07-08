from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from ..analysis.canonical_builder import build_canonical_chapters
from ..arcs.arc_store import arc_candidates_path
from ..arcs.candidate_segmenter import propose_arc_candidates
from ..arcs.review_service import confirm_arc_candidates
from ..arcs.v2_hierarchy_import import import_v2_arc_hierarchy
from ..config import DEFAULT_ENCODING, ensure_dir
from ..handoff.exporter import export_handoff_package
from ..handoff.package_store import read_json, write_json
from ..ingestion.source_manifest_builder import build_source_manifest, write_source_manifest
from ..modules.arc_module_extractor import analyze_arc_modules
from ..modules.book_module_extractor import build_book_modules
from ..modules.chapter_module_extractor import analyze_chapter_modules
from ..quality.quality_gate import run_quality_gate
from ..trackers.candidate_extractor import extract_tracker_candidates
from ..trackers.foreshadowing_reconciler import reconcile_foreshadowing_tracker
from ..trackers.manual_override import apply_tracker_manual_override
from ..trackers.mystery_reconciler import reconcile_mystery_tracker


KNOWN_BAD_TITLE_PREFIXES = [
    "第一章的讲义",
    "第四节最后一秒钟",
    "第15章第4条",
]


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _ensure_empty_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _legacy_manifest(source_run: Path) -> dict[str, Any] | None:
    path = source_run / "output" / "run_manifest.json"
    if not path.exists():
        return None
    return _read_json(path)


def _legacy_generation_profiles(source_run: Path) -> dict[str, Any] | None:
    output_dir = source_run / "output"
    profiles_path = output_dir / "generation_profiles.json"
    if profiles_path.exists():
        return _read_json(profiles_path)
    bundle_path = output_dir / "full_book_bundle.json"
    if bundle_path.exists():
        bundle = _read_json(bundle_path)
        profiles = bundle.get("generation_profiles") if isinstance(bundle, dict) else None
        return profiles if isinstance(profiles, dict) else None
    return None


def _legacy_chapter_count(source_run: Path, manifest: dict[str, Any] | None) -> int | None:
    if manifest is not None and "total_chapters" in manifest:
        return int(manifest["total_chapters"])
    chapters_dir = source_run / "output" / "chapters"
    if chapters_dir.exists():
        return len(list(chapters_dir.glob("chapter_*_analysis.json")))
    return None


def _legacy_analysis_unit_count(source_run: Path, manifest: dict[str, Any] | None) -> int | None:
    if manifest is not None:
        for key in ("analysis_unit_count", "legacy_analysis_unit_total"):
            if key in manifest and manifest[key] is not None:
                return int(manifest[key])
        if manifest.get("chapters"):
            return len(manifest["chapters"])
    chapters_dir = source_run / "output" / "chapters"
    if chapters_dir.exists():
        return len(list(chapters_dir.glob("chapter_*_analysis.json")))
    return None


def _known_bad_legacy_titles(manifest: dict[str, Any] | None) -> list[str]:
    if manifest is None:
        return []
    titles: list[str] = []
    for chapter in manifest.get("chapters", []):
        title = str(chapter.get("input_title", "")).strip()
        if any(title.startswith(prefix) for prefix in KNOWN_BAD_TITLE_PREFIXES):
            titles.append(title)
    return titles


def _title_summary(manifest: Any, legacy_manifest: dict[str, Any] | None) -> dict[str, Any]:
    accepted_titles = [chapter.normalized_title for chapter in manifest.chapters]
    accepted_bad_titles = [
        title
        for title in accepted_titles
        if any(title.startswith(prefix) for prefix in KNOWN_BAD_TITLE_PREFIXES)
    ]
    known_bad_legacy_titles = _known_bad_legacy_titles(legacy_manifest)
    suspicious_titles = [
        {
            "chapter_id": chapter.chapter_id,
            "chapter_index": chapter.chapter_index,
            "normalized_title": chapter.normalized_title,
            "title_status": chapter.title_status,
            "boundary_status": chapter.boundary_status,
        }
        for chapter in manifest.chapters
        if chapter.title_status == "suspicious" or chapter.boundary_status != "ok"
    ]
    return {
        "legacy_chapter_count": None,
        "v1_chapter_count": len(manifest.chapters),
        "accepted_titles": accepted_titles,
        "known_bad_legacy_titles": known_bad_legacy_titles,
        "accepted_known_bad_titles": accepted_bad_titles,
        "known_bad_titles_rejected": not accepted_bad_titles,
        "legacy_analysis_unit_count": None,
        "suspicious_title_count": len(suspicious_titles),
        "suspicious_titles": suspicious_titles,
        "title_sources_traceable": all(
            bool(chapter.title_source and chapter.start_line is not None and chapter.end_line is not None)
            for chapter in manifest.chapters
        ),
    }


def _evidence(chapter_index: int, note: str) -> list[dict[str, Any]]:
    return [
        {
            "ref_type": "canonical_chapter",
            "chapter_index": chapter_index,
            "note": note,
        }
    ]


def _seed_longzu_semantics(run_dir: Path) -> None:
    canonical_dir = run_dir / "canonical_chapter_analysis"
    boundary_seed = {
        2: ["dominant_conflict_changed", "new_question_launched"],
        3: ["reader_experience_shifted", "dominant_conflict_changed"],
        5: ["reader_experience_shifted", "dominant_conflict_changed"],
        7: ["reader_experience_shifted"],
        8: ["new_question_launched", "dominant_conflict_changed"],
        10: ["dominant_conflict_changed", "new_question_launched"],
        11: ["major_question_answered", "dominant_conflict_changed"],
        12: ["reader_experience_shifted"],
    }
    tracker_seed = {
        2: [
            {
                "candidate_id": "longzu_bloodline_plant_002",
                "candidate_type": "foreshadowing",
                "content": "血统异常线索：普通身份下出现与隐藏世界规则不匹配的潜能。",
                "candidate_action": "plant",
                "possible_existing_item_refs": ["BLOODLINE_THREAD"],
                "evidence_refs": _evidence(2, "bloodline clue planted"),
                "confidence_score": 0.78,
            }
        ],
        3: [
            {
                "candidate_id": "longzu_bloodline_reinforce_003",
                "candidate_type": "foreshadowing",
                "content": "血统异常线索被测试结果强化，但真实解释仍未完全释放。",
                "candidate_action": "reinforce",
                "possible_existing_item_refs": ["BLOODLINE_THREAD"],
                "evidence_refs": _evidence(3, "bloodline clue reinforced"),
                "confidence_score": 0.75,
            }
        ],
        5: [
            {
                "candidate_id": "longzu_dragon_king_plant_005",
                "candidate_type": "foreshadowing",
                "content": "龙王身份谜题：青铜城探索把敌人身份从传说推向现实威胁。",
                "candidate_action": "plant",
                "possible_existing_item_refs": ["DRAGON_KING_THREAD"],
                "evidence_refs": _evidence(5, "dragon king identity clue planted"),
                "confidence_score": 0.8,
            }
        ],
        8: [
            {
                "candidate_id": "longzu_contract_plant_008",
                "candidate_type": "foreshadowing",
                "content": "契约线索：路鸣泽提出可召唤四次，每次消耗四分之一生命。",
                "candidate_action": "plant",
                "possible_existing_item_refs": ["CONTRACT_THREAD"],
                "evidence_refs": _evidence(8, "contract planted"),
                "confidence_score": 0.86,
            }
        ],
        9: [
            {
                "candidate_id": "longzu_contract_reinforce_009",
                "candidate_type": "foreshadowing",
                "content": "契约线索被强化：召唤规则与兄弟关系绑定，代价尚未完全兑现。",
                "candidate_action": "reinforce",
                "possible_existing_item_refs": ["CONTRACT_THREAD"],
                "evidence_refs": _evidence(9, "contract reinforced"),
                "confidence_score": 0.82,
            }
        ],
        10: [
            {
                "candidate_id": "longzu_dragon_king_surface_010",
                "candidate_type": "foreshadowing",
                "content": "龙王身份谜题表面化：复苏问题成为主线冲突。",
                "candidate_action": "surface",
                "possible_existing_item_refs": ["DRAGON_KING_THREAD"],
                "evidence_refs": _evidence(10, "dragon king identity surfaced"),
                "confidence_score": 0.82,
            }
        ],
        11: [
            {
                "candidate_id": "longzu_contract_surface_011",
                "candidate_type": "foreshadowing",
                "content": "契约线索表面化：一次召唤已消耗生命份额，剩余次数发生变化。",
                "candidate_action": "surface",
                "possible_existing_item_refs": ["CONTRACT_THREAD"],
                "evidence_refs": _evidence(11, "contract surfaced"),
                "confidence_score": 0.84,
            },
            {
                "candidate_id": "longzu_bloodline_surface_011",
                "candidate_type": "foreshadowing",
                "content": "血统异常线索表面化：潜能与最终高潮中的行动能力产生因果关系。",
                "candidate_action": "surface",
                "possible_existing_item_refs": ["BLOODLINE_THREAD"],
                "evidence_refs": _evidence(11, "bloodline clue surfaced"),
                "confidence_score": 0.8,
            },
        ],
    }

    for path in sorted(canonical_dir.glob("chapter_*.json")):
        data = _read_json(path)
        chapter_index = int(data["chapter_index"])
        data["story_facts"]["chapter_summary"] = (
            f"semantic regression seed: chapter {chapter_index} has canonical story facts and structure."
        )
        data["story_facts"]["events"].append(
            {
                "event_id": f"longzu_event_{chapter_index:03d}",
                "summary": f"回归语义种子：第{chapter_index}单元的核心叙事事件已归入 canonical。",
                "evidence_refs": _evidence(chapter_index, "canonical event seed"),
            }
        )
        data["story_facts"]["character_state_changes"].append(
            {
                "character": "protagonist",
                "character_ref": "protagonist",
                "state_change": f"第{chapter_index}单元后，主角状态随隐藏世界压力发生阶段性变化。",
                "evidence_refs": _evidence(chapter_index, "character state seed"),
            }
        )
        data["structural_analysis"]["chapter_function"] = {
            "function": "semantic regression seed",
            "requires_llm_semantic_pass": True,
        }
        data["structural_analysis"]["dominant_reader_experience"] = {
            "label": "regression_seed_reader_experience",
            "evidence_refs": _evidence(chapter_index, "reader experience seed"),
        }
        for signal_name in boundary_seed.get(chapter_index, []):
            data["boundary_signals"][signal_name] = True
        data["tracker_candidates"].extend(tracker_seed.get(chapter_index, []))
        _write_json(path, data)


def _arc_labels(chapters: list[int]) -> tuple[str, str, str, str]:
    start = chapters[0]
    end = chapters[-1]
    if start <= 1 and end <= 1:
        return (
            "普通世界与召唤入口",
            "主角是否会被隐藏世界选中",
            "日常身份与隐藏世界邀请的冲突",
            "从熟悉日常进入异常召唤",
        )
    if start <= 3 and end <= 4:
        return (
            "入学与身份测试",
            "主角如何理解新世界规则",
            "自我认知与学院评价体系的冲突",
            "新奇、压迫与身份不确定",
        )
    if start <= 5 and end <= 6:
        return (
            "青铜城探索",
            "隐藏世界的真实危险如何显形",
            "任务探索与龙族威胁的冲突",
            "悬疑、危险和世界观扩张",
        )
    if start <= 7 and end <= 7:
        return (
            "关系缓冲",
            "高压主线后人物关系如何重新摆放",
            "情感关系与主线压力的缓冲冲突",
            "放缓、亲近和不安并存",
        )
    if start <= 8 and end <= 9:
        return (
            "兄弟契约与长期代价",
            "契约能解决什么，又会夺走什么",
            "短期救援与长期代价的冲突",
            "诱惑、亲密和危险承诺",
        )
    if start <= 10 and end <= 10:
        return (
            "龙王复苏与真相逼近",
            "敌人身份是否已经进入现实",
            "世界真相与角色行动能力的冲突",
            "危机升级和真相压迫",
        )
    if start <= 11 and end <= 11:
        return (
            "七宗罪高潮与契约兑现",
            "主角是否愿意支付代价完成跃迁",
            "生存、选择与代价的冲突",
            "高强度高潮和代价落地",
        )
    return (
        "余波解释与未来钩子",
        "事件之后还有哪些未偿问题",
        "日常恢复与未完成契约的冲突",
        "释然、回望和下一部期待",
    )


def _enrich_arc_candidates(run_dir: Path) -> None:
    payload = read_json(arc_candidates_path(run_dir))
    for arc in [*payload.get("major_arcs", []), *payload.get("sub_arcs", [])]:
        chapters = arc["chapters_included"]
        goal, question, conflict, reader_experience = _arc_labels(chapters)
        if arc["arc_level"] == "major_arc" and chapters[-1] <= 10:
            goal = "进入隐藏世界并完成第一次身份跃迁"
            question = "普通主角如何被推入龙族世界并获得行动位置"
            conflict = "日常身份、学院秩序与龙族威胁之间的递进冲突"
            reader_experience = "从召唤、入学、探索到危机升级的连续吸引"
        elif arc["arc_level"] == "major_arc":
            goal = "事件余波、契约代价与未来钩子"
            question = "高潮后哪些代价和问题仍会牵引续作"
            conflict = "阶段胜利与未偿契约之间的冲突"
            reader_experience = "高潮释放后的解释、余波和持续期待"
        arc["stage_goal"] = goal
        arc["stage_question"] = question
        arc["dominant_conflict"] = conflict
        arc["dominant_reader_experience"] = reader_experience
        arc["entry_state"] = {"chapter_index": chapters[0], "state": f"{goal}开始"}
        arc["exit_state"] = {"chapter_index": chapters[-1], "state": f"{goal}结束"}
        arc["turning_points"] = [
            {
                "chapter_index": chapters[-1],
                "description": question,
                "evidence_refs": _evidence(chapters[-1], "arc turning point seed"),
            }
        ]
    write_json(arc_candidates_path(run_dir), payload)


def _contract_tracker_summary(tracker: dict[str, Any]) -> dict[str, Any]:
    contract_items = [
        item
        for item in tracker.get("items", [])
        if "契约" in item.get("canonical_content", "")
        or any("契约" in update.get("content", "") for update in item.get("updates", []))
    ]
    update_types = sorted(
        {
            update["update_type"]
            for item in contract_items
            for update in item.get("updates", [])
        }
    )
    planted_chapters = [item.get("planted", {}).get("chapter_index") for item in contract_items]
    return {
        "item_count": len(contract_items),
        "tracker_item_ids": [item["tracker_item_id"] for item in contract_items],
        "planted_chapters": planted_chapters,
        "update_types": update_types,
        "planted_not_overwritten": all(chapter is not None for chapter in planted_chapters),
    }


def _arc_summary(run_dir: Path) -> dict[str, Any]:
    major = read_json(run_dir / "arcs" / "major_arcs.json")
    sub = read_json(run_dir / "arcs" / "sub_arcs.json")
    sub_ranges = [arc["chapters_included"] for arc in sub.get("arcs", [])]
    fixed_legacy_split = sub_ranges == [list(range(1, 16)), [16, 17]]
    return {
        "major_arc_count": len(major.get("arcs", [])),
        "sub_arc_count": len(sub.get("arcs", [])),
        "sub_arc_ranges": sub_ranges,
        "not_legacy_fixed_split": not fixed_legacy_split,
        "review_status": major.get("status"),
    }


def _module_summary(run_dir: Path) -> dict[str, Any]:
    arc_modules = read_json(run_dir / "modules" / "arc_modules.json")
    book_modules = read_json(run_dir / "modules" / "book_modules.json")
    catalog = read_json(run_dir / "modules" / "module_catalog.json")
    conflict_path = run_dir / "modules" / "module_conflict_report.json"
    conflict_report = read_json(conflict_path) if conflict_path.exists() else {}
    specificity = sorted(
        {
            module["source_specificity"]
            for module in [*arc_modules.get("modules", []), *book_modules.get("modules", [])]
        }
    )
    return {
        "arc_module_count": arc_modules.get("module_count", 0),
        "book_module_count": book_modules.get("module_count", 0),
        "catalog_module_count": catalog.get("module_count", 0),
        "source_specificity_values": specificity,
        "has_transferable": "transferable" in specificity,
        "has_hybrid": "hybrid" in specificity,
        "conflict_report_exists": conflict_path.exists(),
        "conflict_report_status": conflict_report.get("status", "missing"),
        "conflict_count": conflict_report.get("conflict_count", 0),
    }


def _handoff_summary(export_result: dict[str, Any]) -> dict[str, Any]:
    package_dir = Path(export_result["package_dir"])
    package_manifest = read_json(package_dir / "package_manifest.json")
    return {
        "package_dir": str(package_dir),
        "validation_status": export_result["validation_summary"]["validation_status"],
        "blocking_issue_count": export_result["validation_summary"]["blocking_issue_count"],
        "warning_count": export_result["validation_summary"]["warning_count"],
        "advisory_only": package_manifest.get("authority") == "advisory_only"
        and package_manifest.get("can_write_formal_state") is False,
        "generator_import_preview_ready": (package_dir / "book_framework_package.v1.json").exists()
        and (package_dir / "modules" / "module_catalog.json").exists()
        and package_manifest.get("generator_capabilities", {}).get(
            "requires_user_confirmation_before_formal_write"
        )
        is True,
    }


def _tracker_edit_report_summary(package_dir: Path) -> dict[str, Any]:
    report_path = package_dir / "trackers" / "tracker_edit_report.json"
    markdown_path = package_dir / "trackers" / "tracker_edit_report.md"
    semantic_path = package_dir / "trackers" / "tracker_semantic_recommendation_report.json"
    if not report_path.exists():
        return {
            "status": "missing",
            "operation_count": 0,
            "manual_override_item_count": 0,
            "json_ref": "trackers/tracker_edit_report.json",
            "markdown_ref": "trackers/tracker_edit_report.md",
            "semantic_risk_level": "missing",
            "semantic_review": {},
            "semantic_recommendation_report_ref": "trackers/tracker_semantic_recommendation_report.json",
            "json_exists": False,
            "markdown_exists": markdown_path.exists(),
            "semantic_recommendation_report_exists": semantic_path.exists(),
        }
    report = read_json(report_path)
    return {
        "status": report.get("status", "unknown"),
        "operation_count": report.get("operation_count", 0),
        "manual_override_item_count": report.get("manual_override_item_count", 0),
        "operations_by_type": report.get("operations_by_type", {}),
        "operations_by_tracker_type": report.get("operations_by_tracker_type", {}),
        "semantic_risk_level": report.get("semantic_risk_level", "unknown"),
        "semantic_review": report.get("semantic_review", {}),
        "semantic_recommendation_report_ref": "trackers/tracker_semantic_recommendation_report.json",
        "json_ref": "trackers/tracker_edit_report.json",
        "markdown_ref": "trackers/tracker_edit_report.md",
        "json_exists": True,
        "markdown_exists": markdown_path.exists(),
        "semantic_recommendation_report_exists": semantic_path.exists(),
    }


def _write_markdown_report(output_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Story Analyzer v1 M8 Longzu Regression Report",
        "",
        f"status: {report['status']}",
        f"source_run: {report['source_run']}",
        f"run_dir: {report['run_dir']}",
        "",
        "## Input",
        "",
        f"- legacy_chapter_count: {report['source_input']['legacy_chapter_count']}",
        f"- legacy_analysis_unit_count: {report['source_input'].get('legacy_analysis_unit_count')}",
        f"- v1_chapter_count: {report['source_input']['v1_chapter_count']}",
        f"- known_bad_titles_rejected: {report['source_input']['known_bad_titles_rejected']}",
        f"- suspicious_title_count: {report['source_input']['suspicious_title_count']}",
        "",
        "## Tracker",
        "",
        f"- total_items: {report['trackers']['item_count']}",
        f"- contract_item_count: {report['trackers']['contract_tracker']['item_count']}",
        f"- contract_update_types: {', '.join(report['trackers']['contract_tracker']['update_types'])}",
        f"- manual_override_smoke_passed: {report['trackers']['manual_override_smoke_passed']}",
        f"- edit_report_status: {report['trackers']['edit_report']['status']}",
        f"- edit_report_operation_count: {report['trackers']['edit_report']['operation_count']}",
        f"- edit_report_semantic_risk: {report['trackers']['edit_report']['semantic_risk_level']}",
        "- semantic_recommendation_report_exists: "
        f"{report['trackers']['edit_report']['semantic_recommendation_report_exists']}",
        "",
        "## Arcs",
        "",
        f"- major_arc_count: {report['arcs']['major_arc_count']}",
        f"- sub_arc_count: {report['arcs']['sub_arc_count']}",
        f"- sub_arc_ranges: {report['arcs']['sub_arc_ranges']}",
        f"- not_legacy_fixed_split: {report['arcs']['not_legacy_fixed_split']}",
        "",
        "## Modules",
        "",
        f"- conflict_report_exists: {report['modules']['conflict_report_exists']}",
        f"- conflict_report_status: {report['modules']['conflict_report_status']}",
        f"- conflict_count: {report['modules']['conflict_count']}",
        "",
        "## Handoff",
        "",
        f"- validation_status: {report['handoff']['validation_status']}",
        f"- generator_import_preview_ready: {report['handoff']['generator_import_preview_ready']}",
        "",
        "## Issues",
        "",
    ]
    issues = report.get("blocking_issues", []) + report.get("warnings", [])
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- none")
    (output_dir / "longzu_regression_report.md").write_text("\n".join(lines) + "\n", encoding=DEFAULT_ENCODING)


def _evaluate_report(report: dict[str, Any]) -> None:
    blockers: list[str] = []
    warnings: list[str] = []

    if report["source_input"].get("accepted_known_bad_titles"):
        blockers.append("known bad legacy titles were accepted by v1 source manifest")
    if not report["source_input"]["title_sources_traceable"]:
        blockers.append("chapter title sources are not fully traceable")
    if report["quality"]["status"] != "passed":
        blockers.append("quality gate did not pass")
    if report["trackers"]["contract_tracker"]["item_count"] != 1:
        blockers.append("contract foreshadowing did not reconcile into exactly one tracker item")
    for update_type in ["reinforced", "surfaced"]:
        if update_type not in report["trackers"]["contract_tracker"]["update_types"]:
            blockers.append(f"contract tracker is missing {update_type} update")
    if not report["trackers"]["contract_tracker"]["planted_not_overwritten"]:
        blockers.append("contract tracker planted state was not preserved")
    if report["trackers"]["edit_report"]["status"] != "manual_edits_present":
        blockers.append("tracker edit report did not record manual edits")
    if report["trackers"]["edit_report"]["operation_count"] < 1:
        blockers.append("tracker edit report did not include the manual override operation")
    if report["trackers"]["edit_report"]["manual_override_item_count"] < 1:
        blockers.append("tracker edit report did not include manual override items")
    if not report["trackers"]["edit_report"]["json_exists"] or not report["trackers"]["edit_report"]["markdown_exists"]:
        blockers.append("tracker edit report package artifacts are missing")
    if not report["trackers"]["edit_report"]["semantic_recommendation_report_exists"]:
        blockers.append("tracker semantic recommendation report package artifact is missing")
    if report["arcs"]["major_arc_count"] < 2:
        blockers.append("arc proposal did not create at least two major arcs")
    if report["arcs"]["sub_arc_count"] < 6:
        blockers.append("arc proposal is still too coarse")
    if not report["arcs"]["not_legacy_fixed_split"]:
        blockers.append("arc proposal repeated the rejected 1-15 / 16-17 split")
    if not report["modules"]["has_transferable"] or not report["modules"]["has_hybrid"]:
        blockers.append("module package lacks required transferable/hybrid coverage")
    if not report["modules"]["conflict_report_exists"]:
        blockers.append("module conflict report artifact is missing")
    if report["handoff"]["validation_status"] != "passed":
        blockers.append("handoff validation did not pass")
    if report["handoff"]["blocking_issue_count"]:
        blockers.append("handoff package contains blocking issues")
    if not report["handoff"]["generator_import_preview_ready"]:
        blockers.append("generator import preview artifacts are missing or unsafe")
    legacy_comparison_count = (
        report["source_input"].get("legacy_analysis_unit_count")
        or report["source_input"].get("legacy_chapter_count")
    )
    if legacy_comparison_count is not None and legacy_comparison_count != report["source_input"]["v1_chapter_count"]:
        warnings.append(
            "legacy run used a different chapter segmentation count; v1 source manifest uses traceable source headings"
        )

    report["blocking_issues"] = blockers
    report["warnings"] = warnings
    report["status"] = "failed" if blockers else "passed"


def run_longzu_regression(
    source_run: str | Path,
    output_dir: str | Path,
    *,
    work_title: str = "龙族1·火之晨曦",
) -> dict[str, Any]:
    source_run_path = Path(source_run)
    output_path = Path(output_dir)
    _ensure_empty_output_dir(output_path)

    source_text = source_run_path / "input" / "book.txt"
    if not source_text.exists():
        raise FileNotFoundError(source_text)

    legacy = _legacy_manifest(source_run_path)
    run_dir = ensure_dir(output_path / "run")
    manifest = build_source_manifest(source_text, work_title=work_title)
    write_source_manifest(manifest, run_dir)
    title_summary = _title_summary(manifest, legacy)
    title_summary["legacy_chapter_count"] = _legacy_chapter_count(source_run_path, legacy)
    title_summary["legacy_analysis_unit_count"] = _legacy_analysis_unit_count(source_run_path, legacy)

    build_canonical_chapters(run_dir)
    _seed_longzu_semantics(run_dir)
    imported_arc_hierarchy = {"status": "missing", "reason": "generation_profiles_not_found"}
    profiles = _legacy_generation_profiles(source_run_path)
    if profiles is not None:
        imported_arc_hierarchy = import_v2_arc_hierarchy(run_dir, profiles)
    quality = run_quality_gate(run_dir)
    extract_tracker_candidates(run_dir)
    tracker = reconcile_foreshadowing_tracker(run_dir)
    reconcile_mystery_tracker(run_dir)
    contract_summary = _contract_tracker_summary(tracker)
    manual_override_passed = False
    if contract_summary["tracker_item_ids"]:
        apply_tracker_manual_override(
            run_dir,
            tracker_item_id=contract_summary["tracker_item_ids"][0],
            status="partially_resolved",
            reason="M8 regression manual override smoke test",
        )
        updated_tracker = read_json(run_dir / "trackers" / "foreshadowing_tracker.json")
        manual_override_passed = any(
            item.get("manual_override", {}).get("active") is True
            for item in updated_tracker.get("items", [])
            if item["tracker_item_id"] in contract_summary["tracker_item_ids"]
        )
        tracker = updated_tracker

    propose_arc_candidates(run_dir)
    _enrich_arc_candidates(run_dir)
    confirm_arc_candidates(run_dir)
    analyze_chapter_modules(run_dir)
    analyze_arc_modules(run_dir)
    build_book_modules(run_dir)
    package_dir = output_path / "handoff_package_v1"
    export_result = export_handoff_package(run_dir, output_dir=package_dir)
    tracker_edit_report = _tracker_edit_report_summary(package_dir)

    report: dict[str, Any] = {
        "schema_version": "story_analyzer.longzu_regression.v1",
        "status": "pending",
        "source_run": str(source_run_path),
        "run_dir": str(run_dir),
        "source_input": title_summary,
        "quality": {
            "status": quality["status"],
            "blocking_issue_count": quality["blocking_issue_count"],
            "warning_count": quality["warning_count"],
        },
        "trackers": {
            "item_count": tracker.get("item_count", len(tracker.get("items", []))),
            "contract_tracker": contract_summary,
            "manual_override_smoke_passed": manual_override_passed,
            "edit_report": tracker_edit_report,
        },
        "arcs": _arc_summary(run_dir),
        "modules": _module_summary(run_dir),
        "handoff": _handoff_summary(export_result),
    }
    report["arcs"]["imported_arc_hierarchy"] = imported_arc_hierarchy
    _evaluate_report(report)
    _write_json(output_path / "longzu_regression_report.json", report)
    _write_markdown_report(output_path, report)
    return report
