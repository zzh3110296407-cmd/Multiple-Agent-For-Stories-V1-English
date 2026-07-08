from __future__ import annotations

from pathlib import Path
from typing import Any
import shutil

from ..analysis.canonical_builder import CANONICAL_DIRNAME
from ..config import SOURCE_MANIFEST_FILENAME
from ..models.handoff import HandoffArtifacts, HandoffPackageManifest
from ..modules.conflict_report import build_module_conflict_report
from ..trackers.edit_report import build_tracker_edit_report
from .package_store import (
    GENERATOR_CONTRACT_VERSION,
    PACKAGE_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
    build_checksums,
    default_handoff_output_dir,
    now_iso,
    read_json,
    write_json,
)
from .validator import validate_handoff_package


def _copy_file(src: Path, dst: Path) -> Path:
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _copy_tree_files(src_dir: Path, dst_dir: Path, pattern: str = "*") -> list[Path]:
    if not src_dir.exists():
        raise FileNotFoundError(src_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for src in sorted(src_dir.glob(pattern)):
        if src.is_file():
            copied.append(_copy_file(src, dst_dir / src.name))
    return copied


def _copy_tracker_or_empty(
    *,
    src: Path,
    dst: Path,
    schema_version: str,
    tracker_type: str,
) -> Path:
    if src.exists():
        return _copy_file(src, dst)
    return write_json(
        dst,
        {
            "schema_version": schema_version,
            "tracker_type": tracker_type,
            "item_count": 0,
            "items": [],
        },
    )


def _copy_override_log_or_empty(*, src: Path, dst: Path) -> Path:
    if src.exists():
        return _copy_file(src, dst)
    return write_json(
        dst,
        {
            "schema_version": "story_analyzer.tracker_override_log.v1",
            "events": [],
        },
    )


def _ensure_fresh_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _manifest_artifacts() -> HandoffArtifacts:
    return HandoffArtifacts(
        source_input_manifest="source_input_manifest.json",
        canonical_chapters_root="canonical/chapters",
        full_book_bundle="full_book_bundle.v1.json",
        major_arcs="arcs/major_arcs.json",
        sub_arcs="arcs/sub_arcs.json",
        foreshadowing_tracker="trackers/foreshadowing_tracker.json",
        mystery_tracker="trackers/mystery_tracker.json",
        relationship_debt_tracker="trackers/relationship_debt_tracker.json",
        world_rule_reveal_tracker="trackers/world_rule_reveal_tracker.json",
        tracker_override_log="trackers/tracker_override_log.json",
        tracker_edit_report="trackers/tracker_edit_report.json",
        tracker_edit_report_markdown="trackers/tracker_edit_report.md",
        tracker_semantic_recommendation_report="trackers/tracker_semantic_recommendation_report.json",
        chapter_modules="modules/chapter_modules.json",
        arc_modules="modules/arc_modules.json",
        book_modules="modules/book_modules.json",
        module_catalog="modules/module_catalog.json",
        module_conflict_report="modules/module_conflict_report.json",
        book_framework_package="book_framework_package.v1.json",
        quality_report="quality_report.json",
        validation_summary="validation_summary.json",
        checksums="checksums.sha256",
    )


def _chapter_entries(package_dir: Path) -> list[dict[str, Any]]:
    source_manifest = read_json(package_dir / "source_input_manifest.json")
    entries: list[dict[str, Any]] = []
    for chapter in source_manifest.get("chapters", []):
        chapter_id = chapter["chapter_id"]
        entries.append(
            {
                "chapter_id": chapter_id,
                "chapter_index": chapter["chapter_index"],
                "normalized_title": chapter.get("normalized_title", ""),
                "canonical_ref": f"canonical/chapters/{chapter_id}.json",
            }
        )
    return entries


def _build_run_manifest(
    *,
    package_dir: Path,
    source_manifest: dict[str, Any],
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "story_analyzer.run_manifest.v1",
        "source": "analyze_stories",
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "run_id": run_id,
        "work_title": source_manifest.get("work_title", ""),
        "generated_at": generated_at,
        "chapter_count": len(source_manifest.get("chapters", [])),
        "package_root": ".",
        "artifacts": _manifest_artifacts().model_dump(mode="json"),
    }


def _build_full_book_bundle(
    *,
    source_manifest: dict[str, Any],
    run_id: str,
    generated_at: str,
    package_dir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "story_analyzer.full_book_bundle.v1",
        "source": "analyze_stories",
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "run_id": run_id,
        "work_title": source_manifest.get("work_title", ""),
        "generated_at": generated_at,
        "chapters": _chapter_entries(package_dir),
        "arcs": {
            "major_arcs_ref": "arcs/major_arcs.json",
            "sub_arcs_ref": "arcs/sub_arcs.json",
        },
        "trackers": {
            "foreshadowing_tracker_ref": "trackers/foreshadowing_tracker.json",
            "mystery_tracker_ref": "trackers/mystery_tracker.json",
            "relationship_debt_tracker_ref": "trackers/relationship_debt_tracker.json",
            "world_rule_reveal_tracker_ref": "trackers/world_rule_reveal_tracker.json",
            "tracker_override_log_ref": "trackers/tracker_override_log.json",
            "tracker_edit_report_ref": "trackers/tracker_edit_report.json",
            "tracker_edit_report_markdown_ref": "trackers/tracker_edit_report.md",
            "tracker_semantic_recommendation_report_ref": "trackers/tracker_semantic_recommendation_report.json",
        },
        "modules": {
            "chapter_modules_ref": "modules/chapter_modules.json",
            "arc_modules_ref": "modules/arc_modules.json",
            "book_modules_ref": "modules/book_modules.json",
            "module_catalog_ref": "modules/module_catalog.json",
            "module_conflict_report_ref": "modules/module_conflict_report.json",
        },
        "generator_import": {
            "requires_profile_compilation": True,
            "requires_user_confirmation_before_formal_write": True,
        },
    }


def _build_book_framework_package(
    *,
    source_manifest: dict[str, Any],
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "story_analyzer.book_framework_package.v1",
        "contract_version": GENERATOR_CONTRACT_VERSION,
        "source": "analyze_stories",
        "authority": "advisory_only",
        "can_write_formal_state": False,
        "run_id": run_id,
        "work_title": source_manifest.get("work_title", ""),
        "generated_at": generated_at,
        "module_catalog_ref": "modules/module_catalog.json",
        "chapter_modules_ref": "modules/chapter_modules.json",
        "arc_modules_ref": "modules/arc_modules.json",
        "book_modules_ref": "modules/book_modules.json",
        "module_conflict_report_ref": "modules/module_conflict_report.json",
        "import_policy": {
            "advisory_only": True,
            "requires_generator_profile_compiler": True,
            "requires_user_confirmation_before_formal_write": True,
            "does_not_include_final_generation_profile": True,
        },
    }


def _write_readme(
    package_dir: Path,
    source_manifest: dict[str, Any],
    generated_at: str,
    tracker_edit_report: dict[str, Any],
    module_conflict_report: dict[str, Any],
) -> None:
    readme = (
        "# Story Analyzer Handoff Package v1\n\n"
        f"Generated: {generated_at}\n"
        f"Work title: {source_manifest.get('work_title', '')}\n"
        f"Chapters: {len(source_manifest.get('chapters', []))}\n\n"
        "This package is advisory only. The story generator must import it for preview, compile a generation profile on its side, and require user confirmation before any formal write.\n"
        "\n"
        "## Tracker Edit Report\n\n"
        f"Status: {tracker_edit_report.get('status', 'unknown')}\n"
        f"Operations: {tracker_edit_report.get('operation_count', 0)}\n"
        f"Manual override items: {tracker_edit_report.get('manual_override_item_count', 0)}\n"
        f"Semantic risk: {tracker_edit_report.get('semantic_risk_level', 'unknown')}\n"
        "JSON: trackers/tracker_edit_report.json\n"
        "Markdown: trackers/tracker_edit_report.md\n"
        "Semantic recommendations: trackers/tracker_semantic_recommendation_report.json\n"
        "\n"
        "## Module Conflict Report\n\n"
        f"Status: {module_conflict_report.get('status', 'unknown')}\n"
        f"Conflicts: {module_conflict_report.get('conflict_count', 0)}\n"
        f"Max severity: {module_conflict_report.get('max_severity', 'info')}\n"
        "JSON: modules/module_conflict_report.json\n"
    )
    (package_dir / "README.md").write_text(readme, encoding="utf-8")


def export_handoff_package(
    run_dir: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    package_dir = Path(output_dir) if output_dir is not None else default_handoff_output_dir(run_path)
    _ensure_fresh_output_dir(package_dir)

    _copy_file(run_path / SOURCE_MANIFEST_FILENAME, package_dir / "source_input_manifest.json")
    _copy_tree_files(run_path / CANONICAL_DIRNAME, package_dir / "canonical" / "chapters", "chapter_*.json")
    _copy_file(run_path / "arcs" / "major_arcs.json", package_dir / "arcs" / "major_arcs.json")
    _copy_file(run_path / "arcs" / "sub_arcs.json", package_dir / "arcs" / "sub_arcs.json")
    _copy_file(run_path / "trackers" / "foreshadowing_tracker.json", package_dir / "trackers" / "foreshadowing_tracker.json")
    _copy_tracker_or_empty(
        src=run_path / "trackers" / "mystery_tracker.json",
        dst=package_dir / "trackers" / "mystery_tracker.json",
        schema_version="story_analyzer.mystery_tracker.v1",
        tracker_type="mystery",
    )
    _copy_tracker_or_empty(
        src=run_path / "trackers" / "relationship_debt_tracker.json",
        dst=package_dir / "trackers" / "relationship_debt_tracker.json",
        schema_version="story_analyzer.relationship_debt_tracker.v1",
        tracker_type="relationship_debt",
    )
    _copy_tracker_or_empty(
        src=run_path / "trackers" / "world_rule_reveal_tracker.json",
        dst=package_dir / "trackers" / "world_rule_reveal_tracker.json",
        schema_version="story_analyzer.world_rule_reveal_tracker.v1",
        tracker_type="world_rule_reveal",
    )
    _copy_override_log_or_empty(
        src=run_path / "trackers" / "tracker_override_log.json",
        dst=package_dir / "trackers" / "tracker_override_log.json",
    )
    tracker_edit_report = build_tracker_edit_report(package_dir)
    _copy_file(run_path / "modules" / "chapter_modules.json", package_dir / "modules" / "chapter_modules.json")
    _copy_file(run_path / "modules" / "arc_modules.json", package_dir / "modules" / "arc_modules.json")
    _copy_file(run_path / "modules" / "book_modules.json", package_dir / "modules" / "book_modules.json")
    _copy_file(run_path / "modules" / "module_catalog.json", package_dir / "modules" / "module_catalog.json")
    module_conflict_report = build_module_conflict_report(package_dir)
    _copy_file(run_path / "quality" / "quality_report.json", package_dir / "quality_report.json")

    source_manifest = read_json(package_dir / "source_input_manifest.json")
    run_id = f"handoff_{source_manifest.get('source_sha256', '')[:12] or package_dir.name}"
    generated_at = now_iso()
    manifest = HandoffPackageManifest(
        schema_version=PACKAGE_SCHEMA_VERSION,
        contract_version=GENERATOR_CONTRACT_VERSION,
        work_title=source_manifest.get("work_title", ""),
        run_id=run_id,
        artifacts=_manifest_artifacts(),
    )
    write_json(package_dir / "package_manifest.json", manifest.model_dump(mode="json"))
    write_json(
        package_dir / "run_manifest.json",
        _build_run_manifest(
            package_dir=package_dir,
            source_manifest=source_manifest,
            run_id=run_id,
            generated_at=generated_at,
        ),
    )
    write_json(
        package_dir / "full_book_bundle.v1.json",
        _build_full_book_bundle(
            source_manifest=source_manifest,
            run_id=run_id,
            generated_at=generated_at,
            package_dir=package_dir,
        ),
    )
    write_json(
        package_dir / "book_framework_package.v1.json",
        _build_book_framework_package(
            source_manifest=source_manifest,
            run_id=run_id,
            generated_at=generated_at,
        ),
    )
    write_json(
        package_dir / "validation_summary.json",
        {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "validation_status": "pending",
            "checked_at": generated_at,
            "blocking_issues": [],
            "warnings": [],
        },
    )
    _write_readme(package_dir, source_manifest, generated_at, tracker_edit_report, module_conflict_report)
    (package_dir / "checksums.sha256").write_text(build_checksums(package_dir), encoding="utf-8")

    validation_summary = validate_handoff_package(package_dir)
    write_json(package_dir / "validation_summary.json", validation_summary)
    return {
        "package_dir": str(package_dir),
        "package_manifest": manifest.model_dump(mode="json"),
        "validation_summary": validation_summary,
    }
