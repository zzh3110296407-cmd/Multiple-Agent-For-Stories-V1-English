from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import uuid

from ..analysis.canonical_builder import build_canonical_chapters
from ..arcs.candidate_segmenter import propose_arc_candidates
from ..config import DEFAULT_ENCODING, ensure_dir
from ..handoff.exporter import export_handoff_package
from ..modules.arc_module_extractor import analyze_arc_modules
from ..modules.book_module_extractor import build_book_modules
from ..modules.chapter_module_extractor import analyze_chapter_modules
from ..quality.quality_gate import run_quality_gate
from ..state.pipeline_state import load_pipeline_state, record_pipeline_step
from ..trackers.candidate_extractor import extract_tracker_candidates
from ..trackers.edit_report import build_tracker_edit_report
from ..trackers.foreshadowing_reconciler import reconcile_foreshadowing_tracker
from ..trackers.mystery_reconciler import reconcile_mystery_tracker
from ..trackers.relationship_debt_reconciler import reconcile_relationship_debt_tracker
from ..trackers.tracker_store import (
    foreshadowing_tracker_path,
    mystery_tracker_path,
    relationship_debt_tracker_path,
    world_rule_reveal_tracker_path,
)
from ..trackers.world_rule_reveal_reconciler import reconcile_world_rule_reveal_tracker


REBUILD_REPORT_SCHEMA_VERSION = "story_analyzer.downstream_rebuild_report.v1"
TRACKER_STEP_TYPES = {
    "foreshadowing_tracker",
    "mystery_tracker",
    "relationship_debt_tracker",
    "world_rule_reveal_tracker",
}
MODULE_STEP_TYPES = {
    "chapter_modules",
    "arc_modules",
    "book_modules",
    "module_catalog",
}
ARC_REVIEW_STEP_TYPES = {
    "arc_confirmation",
    "major_arcs",
    "sub_arcs",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _report_dir(run_dir: Path) -> Path:
    return run_dir / "pipeline" / "downstream_rebuilds"


def _latest_report_path(run_dir: Path) -> Path:
    return run_dir / "pipeline" / "downstream_rebuild_report.json"


def _write_report(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    ensure_dir(_report_dir(run_dir))
    latest_path = _latest_report_path(run_dir)
    history_path = _report_dir(run_dir) / f"{report['rebuild_id']}.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    latest_path.write_text(payload, encoding=DEFAULT_ENCODING)
    history_path.write_text(payload, encoding=DEFAULT_ENCODING)
    return report


def _unique_handoff_output_dir(run_dir: Path) -> Path:
    root = ensure_dir(run_dir / "rebuilds")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for _ in range(10):
        candidate = root / f"handoff_package_{stamp}_{uuid.uuid4().hex[:8]}"
        if not candidate.exists():
            return candidate
    return root / f"handoff_package_{stamp}_{uuid.uuid4().hex}"


def _invalidated_steps(run_dir: Path) -> list[dict[str, Any]]:
    state = load_pipeline_state(run_dir)
    return [step for step in state.get("steps", []) if step.get("status") == "invalidated"]


def _invalidated_by(step: dict[str, Any], change_type: str) -> bool:
    marker = f"invalidated_by:{change_type}"
    return marker in step.get("warnings", [])


def _step_types(steps: list[dict[str, Any]]) -> set[str]:
    return {str(step.get("step_type", "")) for step in steps}


def _tracker_invalidated_only_by_manual_edit(step: dict[str, Any]) -> bool:
    if step.get("step_type") not in TRACKER_STEP_TYPES:
        return False
    return _invalidated_by(step, "tracker_manual_override")


def plan_downstream_rebuild(run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir)
    invalidated = _invalidated_steps(run_path)
    invalidated_step_types = _step_types(invalidated)
    invalidated_step_ids = [step["step_id"] for step in invalidated]

    needs_canonical = "chapter_canonical_analysis" in invalidated_step_types
    needs_quality = needs_canonical or "quality_gate" in invalidated_step_types
    tracker_steps_invalidated = any(step_type in TRACKER_STEP_TYPES for step_type in invalidated_step_types)
    tracker_steps_need_regeneration = any(
        step.get("step_type") in TRACKER_STEP_TYPES and not _tracker_invalidated_only_by_manual_edit(step)
        for step in invalidated
    )
    manual_tracker_edit = any(_invalidated_by(step, "tracker_manual_override") for step in invalidated)
    needs_trackers = (
        needs_canonical
        or "tracker_candidate_extraction" in invalidated_step_types
        or tracker_steps_need_regeneration
    )
    needs_existing_tracker_record = tracker_steps_invalidated and not needs_trackers
    needs_tracker_edit_report = (
        manual_tracker_edit
        or "tracker_edit_report" in invalidated_step_types
        or needs_existing_tracker_record
    )
    needs_arc_candidates = needs_canonical or "arc_candidates" in invalidated_step_types
    needs_arc_review = needs_arc_candidates or bool(invalidated_step_types.intersection(ARC_REVIEW_STEP_TYPES))
    needs_modules = (
        not needs_arc_review
        and (
            needs_trackers
            or needs_tracker_edit_report
            or bool(invalidated_step_types.intersection(MODULE_STEP_TYPES))
        )
    )
    needs_handoff = (
        not needs_arc_review
        and (
            needs_modules
            or "handoff_package" in invalidated_step_types
            or "handoff_validation" in invalidated_step_types
        )
    )

    planned_stages = []
    if needs_canonical:
        planned_stages.append("canonical")
    if needs_quality:
        planned_stages.append("quality_gate")
    if needs_trackers:
        planned_stages.append("trackers")
    if needs_existing_tracker_record:
        planned_stages.append("existing_trackers")
    if needs_tracker_edit_report:
        planned_stages.append("tracker_edit_report")
    if needs_arc_candidates:
        planned_stages.append("arc_candidates")
    if needs_arc_review and not needs_arc_candidates:
        planned_stages.append("arc_review_required")
    if needs_modules:
        planned_stages.append("modules")
    if needs_handoff:
        planned_stages.append("handoff_package")

    if not invalidated:
        status = "noop"
        next_action = "none"
    elif needs_arc_review:
        status = "awaiting_arc_review"
        next_action = "review_and_confirm_arcs"
    else:
        status = "ready"
        next_action = "resume_from_invalidation"

    return {
        "schema_version": REBUILD_REPORT_SCHEMA_VERSION,
        "status": status,
        "next_action": next_action,
        "run_dir": str(run_path),
        "invalidated_step_ids": invalidated_step_ids,
        "invalidated_step_types": sorted(invalidated_step_types),
        "planned_stages": planned_stages,
    }


def _record_canonical(run_dir: Path, paths: list[Path]) -> None:
    for path in paths:
        chapter = _read_json(path)
        chapter_index = chapter["chapter_index"]
        record_pipeline_step(
            run_dir,
            step_id=f"canonical_chapter_{chapter_index:03d}",
            step_type="chapter_canonical_analysis",
            status="completed",
            input_fingerprints=[chapter["source"]["text_sha256"]],
            schema_version=chapter.get("schema_version", ""),
            output_refs=[_relative_to_run(run_dir, path)],
            scope={"chapter_index": chapter_index, "chapter_id": chapter["chapter_id"]},
        )


def _record_quality(run_dir: Path, report: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="quality_gate",
        step_type="quality_gate",
        status="blocked" if report["status"] == "blocked" else "completed",
        schema_version=report.get("schema_version", ""),
        output_refs=["quality/quality_report.json"],
        warnings=[issue["message"] for issue in report.get("issues", []) if issue.get("severity") == "warning"],
        errors=[issue["message"] for issue in report.get("issues", []) if issue.get("severity") == "blocking"],
    )


def _record_tracker_candidates(run_dir: Path, candidate_paths: list[Path]) -> None:
    for path in candidate_paths:
        payload = _read_json(path)
        chapter_index = payload["chapter_index"]
        record_pipeline_step(
            run_dir,
            step_id=f"tracker_candidates_chapter_{chapter_index:03d}",
            step_type="tracker_candidate_extraction",
            status="completed",
            schema_version=payload.get("schema_version", ""),
            output_refs=[_relative_to_run(run_dir, path)],
            scope={"chapter_index": chapter_index, "chapter_id": payload["chapter_id"]},
        )


def _record_tracker_file(run_dir: Path, *, step_id: str, path: Path) -> None:
    payload = _read_json(path)
    record_pipeline_step(
        run_dir,
        step_id=step_id,
        step_type=step_id,
        status="completed",
        schema_version=payload.get("schema_version", ""),
        output_refs=[_relative_to_run(run_dir, path)],
    )


def _record_trackers(
    run_dir: Path,
    *,
    foreshadowing_tracker: dict[str, Any],
    mystery_tracker: dict[str, Any],
    relationship_debt_tracker: dict[str, Any],
    world_rule_reveal_tracker: dict[str, Any],
) -> None:
    for step_id, payload, output_ref in [
        ("foreshadowing_tracker", foreshadowing_tracker, "trackers/foreshadowing_tracker.json"),
        ("mystery_tracker", mystery_tracker, "trackers/mystery_tracker.json"),
        ("relationship_debt_tracker", relationship_debt_tracker, "trackers/relationship_debt_tracker.json"),
        ("world_rule_reveal_tracker", world_rule_reveal_tracker, "trackers/world_rule_reveal_tracker.json"),
    ]:
        record_pipeline_step(
            run_dir,
            step_id=step_id,
            step_type=step_id,
            status="completed",
            schema_version=payload.get("schema_version", ""),
            output_refs=[output_ref],
        )


def _record_existing_tracker_files(run_dir: Path) -> None:
    for step_id, path in [
        ("foreshadowing_tracker", foreshadowing_tracker_path(run_dir)),
        ("mystery_tracker", mystery_tracker_path(run_dir)),
        ("relationship_debt_tracker", relationship_debt_tracker_path(run_dir)),
        ("world_rule_reveal_tracker", world_rule_reveal_tracker_path(run_dir)),
    ]:
        if path.exists():
            _record_tracker_file(run_dir, step_id=step_id, path=path)


def _record_tracker_edit_report(run_dir: Path, report: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="tracker_edit_report",
        step_type="tracker_edit_report",
        status="completed",
        schema_version=report.get("schema_version", ""),
        output_refs=[
            "trackers/tracker_edit_report.json",
            "trackers/tracker_edit_report.md",
            "trackers/tracker_semantic_recommendation_report.json",
        ],
    )


def _record_arc_candidates(run_dir: Path, proposal: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="arc_candidates",
        step_type="arc_candidates",
        status="completed",
        schema_version=proposal.get("schema_version", ""),
        output_refs=["arcs/arc_candidates.json", "arcs/arc_review.json", "arcs/arc_review.md"],
    )


def _record_modules(
    run_dir: Path,
    *,
    chapter_modules: dict[str, Any],
    arc_modules: dict[str, Any],
    book_modules: dict[str, Any],
) -> None:
    record_pipeline_step(
        run_dir,
        step_id="chapter_modules",
        step_type="chapter_modules",
        status="completed",
        schema_version=chapter_modules.get("schema_version", ""),
        output_refs=["modules/chapter_modules.json", "modules/module_catalog.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="arc_modules",
        step_type="arc_modules",
        status="completed",
        schema_version=arc_modules.get("schema_version", ""),
        output_refs=["modules/arc_modules.json", "modules/module_catalog.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="book_modules",
        step_type="book_modules",
        status="completed",
        schema_version=book_modules.get("schema_version", ""),
        output_refs=["modules/book_modules.json", "modules/module_catalog.json", "modules/module_conflict_report.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="module_catalog",
        step_type="module_catalog",
        status="completed",
        output_refs=["modules/module_catalog.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="module_conflict_report",
        step_type="module_conflict_report",
        status="completed",
        output_refs=["modules/module_conflict_report.json"],
    )


def _record_handoff(run_dir: Path, result: dict[str, Any]) -> None:
    summary = result["validation_summary"]
    package_dir = str(Path(result["package_dir"]))
    status = "completed" if summary["validation_status"] == "passed" else "blocked"
    record_pipeline_step(
        run_dir,
        step_id="handoff_package",
        step_type="handoff_package",
        status=status,
        output_refs=[package_dir],
        errors=[issue["message"] for issue in summary.get("blocking_issues", [])],
        warnings=[issue["message"] for issue in summary.get("warnings", [])],
    )
    record_pipeline_step(
        run_dir,
        step_id="handoff_validation",
        step_type="handoff_validation",
        status=status,
        schema_version=summary.get("schema_version", ""),
        output_refs=[f"{package_dir}/validation_summary.json"],
        errors=[issue["message"] for issue in summary.get("blocking_issues", [])],
        warnings=[issue["message"] for issue in summary.get("warnings", [])],
    )


def _finalize_report(
    run_dir: Path,
    *,
    rebuild_id: str,
    status: str,
    next_action: str,
    invalidated_step_ids: list[str],
    planned_stages: list[str],
    rebuilt_stages: list[str],
    started_at: str,
    handoff: dict[str, Any] | None = None,
    quality: dict[str, Any] | None = None,
    arcs: dict[str, Any] | None = None,
    modules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "schema_version": REBUILD_REPORT_SCHEMA_VERSION,
        "rebuild_id": rebuild_id,
        "status": status,
        "next_action": next_action,
        "run_dir": str(run_dir),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "invalidated_step_ids": invalidated_step_ids,
        "planned_stages": planned_stages,
        "rebuilt_stages": rebuilt_stages,
        "quality": quality or {},
        "arcs": arcs or {},
        "modules": modules or {},
        "handoff": handoff or {"package_dir": None},
    }
    _write_report(run_dir, report)
    record_pipeline_step(
        run_dir,
        step_id=f"downstream_rebuild_{rebuild_id}",
        step_type="downstream_rebuild",
        status="completed" if status in {"completed", "noop", "awaiting_arc_review"} else "blocked",
        schema_version=REBUILD_REPORT_SCHEMA_VERSION,
        output_refs=[
            "pipeline/downstream_rebuild_report.json",
            f"pipeline/downstream_rebuilds/{rebuild_id}.json",
        ],
        warnings=[] if status == "completed" else [status],
    )
    return report


def resume_from_invalidation(
    run_dir: str | Path,
    *,
    package_out: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    plan = plan_downstream_rebuild(run_path)
    rebuild_id = f"rebuild_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    started_at = _utc_now()

    if dry_run:
        return {
            **plan,
            "rebuild_id": rebuild_id,
            "dry_run": True,
            "rebuilt_stages": [],
            "handoff": {"package_dir": None},
        }

    if plan["status"] == "noop":
        return _finalize_report(
            run_path,
            rebuild_id=rebuild_id,
            status="noop",
            next_action="none",
            invalidated_step_ids=plan["invalidated_step_ids"],
            planned_stages=plan["planned_stages"],
            rebuilt_stages=[],
            started_at=started_at,
        )

    rebuilt_stages: list[str] = []
    quality_summary: dict[str, Any] = {}
    arcs_summary: dict[str, Any] = {}
    modules_summary: dict[str, Any] = {}
    handoff_summary: dict[str, Any] | None = None
    planned_stages = plan["planned_stages"]

    if "canonical" in planned_stages:
        canonical_paths = build_canonical_chapters(run_path)
        _record_canonical(run_path, canonical_paths)
        rebuilt_stages.append("canonical")

    if "quality_gate" in planned_stages:
        quality_report = run_quality_gate(run_path)
        _record_quality(run_path, quality_report)
        quality_summary = {
            "status": quality_report["status"],
            "blocking_issue_count": quality_report["blocking_issue_count"],
            "warning_count": quality_report["warning_count"],
        }
        rebuilt_stages.append("quality_gate")
        if quality_report["status"] == "blocked":
            return _finalize_report(
                run_path,
                rebuild_id=rebuild_id,
                status="blocked_quality",
                next_action="repair_or_rerun_quality",
                invalidated_step_ids=plan["invalidated_step_ids"],
                planned_stages=planned_stages,
                rebuilt_stages=rebuilt_stages,
                started_at=started_at,
                quality=quality_summary,
            )

    if "trackers" in planned_stages:
        candidate_paths = extract_tracker_candidates(run_path)
        _record_tracker_candidates(run_path, candidate_paths)
        foreshadowing_tracker = reconcile_foreshadowing_tracker(run_path)
        mystery_tracker = reconcile_mystery_tracker(run_path)
        relationship_debt_tracker = reconcile_relationship_debt_tracker(run_path)
        world_rule_reveal_tracker = reconcile_world_rule_reveal_tracker(run_path)
        _record_trackers(
            run_path,
            foreshadowing_tracker=foreshadowing_tracker,
            mystery_tracker=mystery_tracker,
            relationship_debt_tracker=relationship_debt_tracker,
            world_rule_reveal_tracker=world_rule_reveal_tracker,
        )
        rebuilt_stages.append("trackers")

    if "existing_trackers" in planned_stages:
        _record_existing_tracker_files(run_path)
        rebuilt_stages.append("existing_trackers")

    if "tracker_edit_report" in planned_stages:
        tracker_edit_report = build_tracker_edit_report(run_path)
        _record_tracker_edit_report(run_path, tracker_edit_report)
        rebuilt_stages.append("tracker_edit_report")

    if "arc_candidates" in planned_stages:
        proposal = propose_arc_candidates(run_path)
        _record_arc_candidates(run_path, proposal)
        arcs_summary = {
            "status": proposal["status"],
            "candidate_version": proposal["candidate_version"],
            "major_arc_count": len(proposal["major_arcs"]),
            "sub_arc_count": len(proposal["sub_arcs"]),
        }
        rebuilt_stages.append("arc_candidates")
        return _finalize_report(
            run_path,
            rebuild_id=rebuild_id,
            status="awaiting_arc_review",
            next_action="review_and_confirm_arcs",
            invalidated_step_ids=plan["invalidated_step_ids"],
            planned_stages=planned_stages,
            rebuilt_stages=rebuilt_stages,
            started_at=started_at,
            quality=quality_summary,
            arcs=arcs_summary,
        )

    if "arc_review_required" in planned_stages:
        return _finalize_report(
            run_path,
            rebuild_id=rebuild_id,
            status="awaiting_arc_review",
            next_action="confirm-arcs",
            invalidated_step_ids=plan["invalidated_step_ids"],
            planned_stages=planned_stages,
            rebuilt_stages=rebuilt_stages,
            started_at=started_at,
            quality=quality_summary,
        )

    if "modules" in planned_stages:
        chapter_modules = analyze_chapter_modules(run_path)
        arc_modules = analyze_arc_modules(run_path)
        book_modules = build_book_modules(run_path)
        _record_modules(
            run_path,
            chapter_modules=chapter_modules,
            arc_modules=arc_modules,
            book_modules=book_modules,
        )
        modules_summary = {
            "chapter_module_count": chapter_modules["module_count"],
            "arc_module_count": arc_modules["module_count"],
            "book_module_count": book_modules["module_count"],
        }
        rebuilt_stages.append("modules")

    if "handoff_package" in planned_stages:
        output_dir = Path(package_out) if package_out is not None else _unique_handoff_output_dir(run_path)
        handoff = export_handoff_package(run_path, output_dir=output_dir)
        _record_handoff(run_path, handoff)
        validation = handoff["validation_summary"]
        handoff_summary = {
            "package_dir": handoff["package_dir"],
            "validation_status": validation["validation_status"],
            "blocking_issue_count": validation["blocking_issue_count"],
            "warning_count": validation["warning_count"],
        }
        rebuilt_stages.append("handoff_package")
        if validation["validation_status"] != "passed":
            return _finalize_report(
                run_path,
                rebuild_id=rebuild_id,
                status="blocked_handoff",
                next_action="fix_handoff_validation",
                invalidated_step_ids=plan["invalidated_step_ids"],
                planned_stages=planned_stages,
                rebuilt_stages=rebuilt_stages,
                started_at=started_at,
                quality=quality_summary,
                modules=modules_summary,
                handoff=handoff_summary,
            )

    return _finalize_report(
        run_path,
        rebuild_id=rebuild_id,
        status="completed",
        next_action="import_package_in_generator",
        invalidated_step_ids=plan["invalidated_step_ids"],
        planned_stages=planned_stages,
        rebuilt_stages=rebuilt_stages,
        started_at=started_at,
        quality=quality_summary,
        modules=modules_summary,
        handoff=handoff_summary,
    )
