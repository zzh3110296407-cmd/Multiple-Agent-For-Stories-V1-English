from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from ..analysis.canonical_builder import build_canonical_chapters
from ..arcs.candidate_segmenter import propose_arc_candidates
from ..arcs.review_service import confirm_arc_candidates
from ..config import DEFAULT_ENCODING, ensure_dir
from ..handoff.exporter import export_handoff_package
from ..ingestion.source_manifest_builder import build_source_manifest, write_source_manifest
from ..modules.arc_module_extractor import analyze_arc_modules
from ..modules.book_module_extractor import build_book_modules
from ..modules.chapter_module_extractor import analyze_chapter_modules
from ..quality.quality_gate import run_quality_gate
from ..state.pipeline_state import record_pipeline_step
from ..trackers.candidate_extractor import extract_tracker_candidates
from ..trackers.foreshadowing_reconciler import reconcile_foreshadowing_tracker
from ..trackers.mystery_reconciler import reconcile_mystery_tracker
from ..trackers.relationship_debt_reconciler import reconcile_relationship_debt_tracker
from ..trackers.world_rule_reveal_reconciler import reconcile_world_rule_reveal_tracker


PIPELINE_DIRNAME = "pipeline"
SUMMARY_SCHEMA_VERSION = "story_analyzer.pipeline_run_summary.v1"


def pipeline_summary_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / PIPELINE_DIRNAME / "run_summary.json"


def _relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _write_summary(run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    path = pipeline_summary_path(run_dir)
    ensure_dir(path.parent)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return summary


def _record_source_manifest(run_dir: Path, manifest: Any, manifest_path: Path) -> None:
    record_pipeline_step(
        run_dir,
        step_id="source_manifest",
        step_type="source_manifest",
        status="completed",
        input_fingerprints=[manifest.source_sha256],
        output_refs=[_relative_to_run(run_dir, manifest_path)],
    )


def _record_canonical(run_dir: Path, paths: list[Path]) -> None:
    for path in paths:
        chapter = json.loads(path.read_text(encoding="utf-8-sig"))
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


def _record_trackers(
    run_dir: Path,
    candidate_paths: list[Path],
    *,
    foreshadowing_tracker: dict[str, Any],
    mystery_tracker: dict[str, Any],
    relationship_debt_tracker: dict[str, Any],
    world_rule_reveal_tracker: dict[str, Any],
) -> None:
    for path in candidate_paths:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
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
    record_pipeline_step(
        run_dir,
        step_id="foreshadowing_tracker",
        step_type="foreshadowing_tracker",
        status="completed",
        schema_version=foreshadowing_tracker.get("schema_version", ""),
        output_refs=["trackers/foreshadowing_tracker.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="mystery_tracker",
        step_type="mystery_tracker",
        status="completed",
        schema_version=mystery_tracker.get("schema_version", ""),
        output_refs=["trackers/mystery_tracker.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="relationship_debt_tracker",
        step_type="relationship_debt_tracker",
        status="completed",
        schema_version=relationship_debt_tracker.get("schema_version", ""),
        output_refs=["trackers/relationship_debt_tracker.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="world_rule_reveal_tracker",
        step_type="world_rule_reveal_tracker",
        status="completed",
        schema_version=world_rule_reveal_tracker.get("schema_version", ""),
        output_refs=["trackers/world_rule_reveal_tracker.json"],
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


def _record_arc_confirmation(run_dir: Path, review: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="arc_confirmation",
        step_type="arc_confirmation",
        status="completed",
        schema_version=review.get("schema_version", ""),
        output_refs=["arcs/major_arcs.json", "arcs/sub_arcs.json", "arcs/arc_review.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="major_arcs",
        step_type="major_arcs",
        status="completed",
        output_refs=["arcs/major_arcs.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="sub_arcs",
        step_type="sub_arcs",
        status="completed",
        output_refs=["arcs/sub_arcs.json"],
    )


def _record_arc_modules(run_dir: Path, payload: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="arc_modules",
        step_type="arc_modules",
        status="completed",
        schema_version=payload.get("schema_version", ""),
        output_refs=["modules/arc_modules.json", "modules/module_catalog.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="module_catalog",
        step_type="module_catalog",
        status="completed",
        output_refs=["modules/module_catalog.json"],
    )


def _record_chapter_modules(run_dir: Path, payload: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="chapter_modules",
        step_type="chapter_modules",
        status="completed",
        schema_version=payload.get("schema_version", ""),
        output_refs=["modules/chapter_modules.json", "modules/module_catalog.json"],
    )
    record_pipeline_step(
        run_dir,
        step_id="module_catalog",
        step_type="module_catalog",
        status="completed",
        output_refs=["modules/module_catalog.json"],
    )


def _record_book_modules(run_dir: Path, payload: dict[str, Any]) -> None:
    record_pipeline_step(
        run_dir,
        step_id="book_modules",
        step_type="book_modules",
        status="completed",
        schema_version=payload.get("schema_version", ""),
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
    record_pipeline_step(
        run_dir,
        step_id="handoff_package",
        step_type="handoff_package",
        status="completed" if summary["validation_status"] == "passed" else "blocked",
        output_refs=[str(Path(result["package_dir"]))],
        errors=[issue["message"] for issue in summary.get("blocking_issues", [])],
        warnings=[issue["message"] for issue in summary.get("warnings", [])],
    )


def _blocked_quality_summary(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    return _write_summary(
        run_dir,
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "status": "blocked_quality",
            "current_stage": "quality_gate",
            "next_action": "repair_or_rerun_quality",
            "run_dir": str(run_dir),
            "quality": {
                "status": report["status"],
                "blocking_issue_count": report["blocking_issue_count"],
                "warning_count": report["warning_count"],
            },
            "artifacts": {
                "quality_report": "quality/quality_report.json",
            },
        },
    )


def prepare_run(
    input_path: str | Path,
    run_dir: str | Path,
    *,
    work_title: str | None = None,
) -> dict[str, Any]:
    """Run the analyzer pipeline through arc proposal and stop for user review."""

    run_path = Path(run_dir)
    manifest = build_source_manifest(input_path, work_title=work_title)
    manifest_path = write_source_manifest(manifest, run_path)
    _record_source_manifest(run_path, manifest, manifest_path)

    canonical_paths = build_canonical_chapters(run_path)
    _record_canonical(run_path, canonical_paths)

    quality_report = run_quality_gate(run_path)
    _record_quality(run_path, quality_report)
    if quality_report["status"] == "blocked":
        return _blocked_quality_summary(run_path, quality_report)

    candidate_paths = extract_tracker_candidates(run_path)
    foreshadowing_tracker = reconcile_foreshadowing_tracker(run_path)
    mystery_tracker = reconcile_mystery_tracker(run_path)
    relationship_debt_tracker = reconcile_relationship_debt_tracker(run_path)
    world_rule_reveal_tracker = reconcile_world_rule_reveal_tracker(run_path)
    _record_trackers(
        run_path,
        candidate_paths,
        foreshadowing_tracker=foreshadowing_tracker,
        mystery_tracker=mystery_tracker,
        relationship_debt_tracker=relationship_debt_tracker,
        world_rule_reveal_tracker=world_rule_reveal_tracker,
    )

    proposal = propose_arc_candidates(run_path)
    _record_arc_candidates(run_path, proposal)

    return _write_summary(
        run_path,
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "status": "awaiting_arc_review",
            "current_stage": "arc_review",
            "next_action": "review_and_confirm_arcs",
            "run_dir": str(run_path),
            "quality": {
                "status": quality_report["status"],
                "blocking_issue_count": quality_report["blocking_issue_count"],
                "warning_count": quality_report["warning_count"],
            },
            "arcs": {
                "status": proposal["status"],
                "candidate_version": proposal["candidate_version"],
                "major_arc_count": len(proposal["major_arcs"]),
                "sub_arc_count": len(proposal["sub_arcs"]),
            },
            "artifacts": {
                "source_input_manifest": "source_input_manifest.json",
                "canonical_chapters_root": "canonical_chapter_analysis",
                "quality_report": "quality/quality_report.json",
                "foreshadowing_tracker": "trackers/foreshadowing_tracker.json",
                "mystery_tracker": "trackers/mystery_tracker.json",
                "relationship_debt_tracker": "trackers/relationship_debt_tracker.json",
                "world_rule_reveal_tracker": "trackers/world_rule_reveal_tracker.json",
                "arc_candidates": "arcs/arc_candidates.json",
                "arc_review": "arcs/arc_review.json",
                "arc_review_markdown": "arcs/arc_review.md",
            },
        },
    )


def continue_run(
    run_dir: str | Path,
    *,
    review_file: str | Path | None = None,
    package_out: str | Path | None = None,
) -> dict[str, Any]:
    """Continue a prepared run after the user has reviewed arc boundaries."""

    run_path = Path(run_dir)
    quality_report = run_quality_gate(run_path)
    _record_quality(run_path, quality_report)
    if quality_report["status"] == "blocked":
        return _blocked_quality_summary(run_path, quality_report)

    review = confirm_arc_candidates(run_path, review_file=review_file)
    _record_arc_confirmation(run_path, review)

    chapter_modules = analyze_chapter_modules(run_path)
    _record_chapter_modules(run_path, chapter_modules)

    arc_modules = analyze_arc_modules(run_path)
    _record_arc_modules(run_path, arc_modules)

    book_modules = build_book_modules(run_path)
    _record_book_modules(run_path, book_modules)

    handoff = export_handoff_package(run_path, output_dir=package_out)
    _record_handoff(run_path, handoff)
    validation = handoff["validation_summary"]

    return _write_summary(
        run_path,
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "status": "completed" if validation["validation_status"] == "passed" else "blocked_handoff",
            "current_stage": "handoff_exported",
            "next_action": "import_package_in_generator" if validation["validation_status"] == "passed" else "fix_handoff_validation",
            "run_dir": str(run_path),
            "quality": {
                "status": quality_report["status"],
                "blocking_issue_count": quality_report["blocking_issue_count"],
                "warning_count": quality_report["warning_count"],
            },
            "arcs": {
                "status": review["status"],
                "confirmed_version": review["confirmed_version"],
            },
            "modules": {
                "chapter_module_count": chapter_modules["module_count"],
                "arc_module_count": arc_modules["module_count"],
                "book_module_count": book_modules["module_count"],
            },
            "handoff": {
                "package_dir": handoff["package_dir"],
                "validation_status": validation["validation_status"],
                "blocking_issue_count": validation["blocking_issue_count"],
                "warning_count": validation["warning_count"],
            },
            "artifacts": {
                "major_arcs": "arcs/major_arcs.json",
                "sub_arcs": "arcs/sub_arcs.json",
                "chapter_modules": "modules/chapter_modules.json",
                "arc_modules": "modules/arc_modules.json",
                "book_modules": "modules/book_modules.json",
                "module_catalog": "modules/module_catalog.json",
                "module_conflict_report": "modules/module_conflict_report.json",
                "run_summary": "pipeline/run_summary.json",
            },
        },
    )
