from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.final_story_package import (
    AuthorityStatus,
    FinalStoryPackage,
    FinalStoryPackageManifest,
    FinalStoryPackageReadinessEvaluationResponse,
    FinalStoryPackageReadinessGate,
    FinalStoryPackageReadinessIssue,
    FinalStoryPackageReadinessIssueListResponse,
    FinalStoryPackageReadinessStatusResponse,
    FinalStoryPackageSection,
    FinalStoryPackageSourceRef,
    FinalStoryPackageValidationReport,
    PackageStatus,
    PackageType,
    ReadinessStatus,
    SectionValidationStatus,
    SectionType,
)
from ..models.scene import Scene
from .active_project_story_data import (
    active_project_story_data_dir,
    active_project_without_story_data,
    current_story_workspace_project_id,
)
from .scene_content_quality_signal_service import (
    DEMO_DEFAULT_LEAK,
    PROMPT_FIDELITY_MISSING,
    SCENE_OBJECTIVE_REPEATED,
    SCENE_PREVIOUS_SUMMARY_MISSING,
    SCENE_PROGRESSION_MISSING,
    SCENE_PROGRESSION_STATEMENT_MISSING,
    SCENE_REPETITION_TOO_HIGH,
    SceneContentQualitySignalReport,
    SceneContentQualitySignalService,
)
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase7_m1_final_story_package_readiness_v1"

READINESS_GATES_FILE = "final_story_package_readiness_gates.json"
READINESS_ISSUES_FILE = "final_story_package_readiness_issues.json"
VALIDATION_REPORTS_FILE = "final_story_package_validation_reports.json"
SOURCE_REFS_FILE = "final_story_package_source_refs.json"
SECTIONS_FILE = "final_story_package_sections.json"
MANIFESTS_FILE = "final_story_package_manifests.json"
PACKAGES_FILE = "final_story_packages.json"

ALLOWED_M1_STORAGE_FILES = [
    READINESS_GATES_FILE,
    READINESS_ISSUES_FILE,
    VALIDATION_REPORTS_FILE,
    SOURCE_REFS_FILE,
    SECTIONS_FILE,
    MANIFESTS_FILE,
    PACKAGES_FILE,
]

FORBIDDEN_STORY_FACT_FILES = [
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "story_bible.json",
    "decisions.json",
]

FORBIDDEN_PLUGIN_RUNTIME_FILES = [
    "plugin_runs.json",
    "plugin_run_steps.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
    "plugin_checkpoints.json",
    "plugin_checkpoint_decisions.json",
    "plugin_run_safety_reports.json",
    "script_forging_runs.json",
    "script_shape_packages.json",
    "screenplay_draft_artifacts.json",
    "storyboard_artifacts.json",
    "digital_asset_packages.json",
]

REQUIRED_SECTION_TYPES: list[SectionType] = [
    "complete_story_text",
    "chapter_scene_index",
    "character_table",
    "world_canvas_summary",
    "relationship_state_summary",
    "key_event_timeline",
    "user_locked_constraints",
    "style_and_tone",
]

UNSAFE_KEY_PARTS = (
    "prompt",
    "response",
    "reasoning",
    "secret",
    "password",
    "credential",
    "authorization",
    "apikey",
    "api_key",
    "providersecret",
)
UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "full prose",
    "full_prose",
    "prose_text",
    "revised_prose_text",
    "api_key",
    "authorization",
    "bearer ",
    "langsmith key",
    "provider secret",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
    return dict(model)


def resolve_final_package_story_data_dir(
    store: JsonStore,
    explicit_data_dir: Path | None,
) -> tuple[Path, str]:
    if explicit_data_dir is not None:
        return explicit_data_dir, ""
    active_data_dir = active_project_story_data_dir(store, settings.data_dir)
    if active_data_dir is not None:
        return active_data_dir, ""
    missing_project_id = active_project_without_story_data(store, settings.data_dir)
    if missing_project_id:
        return settings.data_dir, missing_project_id
    return settings.data_dir, ""


class FinalStoryPackageReadinessService:
    """Phase 7 M1 final-story-package boundary service.

    M1 defines package readiness metadata only. It never exports full prose,
    never runs plugins, and never mutates original story fact files.
    """

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir, self._missing_active_project_id = resolve_final_package_story_data_dir(
            self.store,
            data_dir,
        )
        self.project_id = current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )
        self.readiness_gates_file = self.data_dir / READINESS_GATES_FILE
        self.readiness_issues_file = self.data_dir / READINESS_ISSUES_FILE
        self.validation_reports_file = self.data_dir / VALIDATION_REPORTS_FILE
        self.source_refs_file = self.data_dir / SOURCE_REFS_FILE
        self.sections_file = self.data_dir / SECTIONS_FILE
        self.manifests_file = self.data_dir / MANIFESTS_FILE
        self.packages_file = self.data_dir / PACKAGES_FILE

    def get_status(self) -> FinalStoryPackageReadinessStatusResponse:
        self._assert_active_story_data_available()
        gates = self._read_models_if_exists(self.readiness_gates_file, FinalStoryPackageReadinessGate)
        packages = self._read_models_if_exists(self.packages_file, FinalStoryPackage)
        reports = self._read_models_if_exists(self.validation_reports_file, FinalStoryPackageValidationReport)
        gates.sort(key=lambda item: item.created_at, reverse=True)
        packages.sort(key=lambda item: item.created_at, reverse=True)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        latest_gate = gates[0] if gates else None
        latest_package = packages[0] if packages else None
        latest_report = reports[0] if reports else None
        return FinalStoryPackageReadinessStatusResponse(
            gate_count=len(gates),
            package_count=len(packages),
            latest_readiness_gate_id=latest_gate.readiness_gate_id if latest_gate else None,
            latest_final_story_package_id=latest_package.final_story_package_id if latest_package else None,
            latest_validation_report_id=latest_report.validation_report_id if latest_report else None,
            latest_readiness_status=latest_gate.readiness_status if latest_gate else None,
            latest_package_type=latest_package.package_type if latest_package else None,
            latest_not_real_project_final_package=(
                latest_package.not_real_project_final_package if latest_package else False
            ),
            latest_blocking_issue_count=len(latest_gate.blocking_issue_ids) if latest_gate else 0,
            latest_warning_issue_count=len(latest_gate.warning_issue_ids) if latest_gate else 0,
            allowed_storage_files=list(ALLOWED_M1_STORAGE_FILES),
            forbidden_story_fact_files=list(FORBIDDEN_STORY_FACT_FILES),
            forbidden_plugin_runtime_files=list(FORBIDDEN_PLUGIN_RUNTIME_FILES),
            safe_summary=(
                "Final Story Package readiness is a boundary check. The package is the only "
                "future plugin input; drafts and Phase 6 proposals are not formal plugin truth."
            ),
        )

    def evaluate_readiness(
        self,
        request: Any | None = None,
        *,
        allow_fixture: bool = False,
        persist: bool = True,
        safe_user_note: str = "",
    ) -> FinalStoryPackageReadinessEvaluationResponse:
        if request is not None:
            allow_fixture = bool(getattr(request, "allow_fixture", allow_fixture))
            persist = bool(getattr(request, "persist", persist))
            safe_user_note = str(getattr(request, "safe_user_note", safe_user_note) or "")
        self._assert_active_story_data_available()
        self._assert_safe_payload({"safe_user_note": safe_user_note}, context="safe_user_note")

        created_at = now_iso()
        suffix = self._id_suffix(created_at)
        package_id = f"final_story_package_{suffix}"
        gate_id = f"final_story_package_readiness_gate_{suffix}"
        manifest_id = f"final_story_package_manifest_{suffix}"
        report_id = f"final_story_package_validation_report_{suffix}"
        version_id = f"{SCHEMA_VERSION}_{suffix}"

        data = self._load_story_data()
        issues: list[FinalStoryPackageReadinessIssue] = []
        source_refs: list[FinalStoryPackageSourceRef] = []
        source_ref_keys: set[tuple[str, str]] = set()

        def add_issue(
            severity: str,
            code: str,
            message: str,
            resolution: str,
            refs: list[str] | None = None,
        ) -> None:
            issue = FinalStoryPackageReadinessIssue(
                issue_id=f"final_story_package_issue_{code}_{len(issues) + 1:03d}_{suffix}",
                readiness_gate_id=gate_id,
                severity=severity,  # type: ignore[arg-type]
                code=code,
                user_visible_message=self._safe_text(message, limit=220),
                recommended_resolution=self._safe_text(resolution, limit=220),
                source_refs=refs or [],
                created_at=created_at,
            )
            issues.append(issue)

        def add_ref(
            source_object_type: str,
            source_object_id: str,
            authority_status: AuthorityStatus,
            reason: str,
            *,
            source_version_id: str = "",
            warnings: list[str] | None = None,
        ) -> str:
            source_object_id = self._safe_identifier(source_object_id or "unknown")
            key = (source_object_type, source_object_id)
            if key in source_ref_keys:
                for existing in source_refs:
                    if (
                        existing.source_object_type == source_object_type
                        and existing.source_object_id == source_object_id
                    ):
                        return existing.source_ref_id
            source_ref_keys.add(key)
            can_be_truth = authority_status in {"formal_story_fact", "user_confirmed"}
            if authority_status == "fixture" and allow_fixture:
                can_be_truth = True
            ref = FinalStoryPackageSourceRef(
                source_ref_id=f"final_story_package_source_ref_{len(source_refs) + 1:03d}_{suffix}",
                final_story_package_id=package_id,
                source_object_type=source_object_type,
                source_object_id=source_object_id,
                source_version_id=self._safe_identifier(source_version_id) if source_version_id else "",
                authority_status=authority_status,
                can_be_plugin_input_truth=can_be_truth,
                reason=self._safe_text(reason, limit=180),
                warnings=warnings or [],
                created_at=created_at,
            )
            source_refs.append(ref)
            return ref.source_ref_id

        final_confirmation_decision_id = self._final_confirmation_decision_id(data["decisions"])
        story_draft_complete_exists = self._story_draft_complete_exists(data["story_progress"], data["decisions"])
        final_confirmation_exists = story_draft_complete_exists
        if not story_draft_complete_exists:
            add_issue(
                "blocking",
                "no_final_confirmation",
                "Final story draft completion is not formally signaled.",
                "Set StoryProgress.story_progress_status to story_draft_complete or add the corresponding story_progress Decision before creating a real final package.",
                ["story_progress", "decisions"],
            )

        continuity_blockers = self._blocking_continuity_issues(data["continuity_issues"])
        if continuity_blockers:
            add_issue(
                "blocking",
                "unresolved_blocking_continuity_issue",
                "Open blocking continuity issues still block final package readiness.",
                "Resolve or formally accept blocking continuity issues before final package creation.",
                [self._safe_identifier(str(item.get("issue_id") or "")) for item in continuity_blockers],
            )

        proposed_formal_apply = self._proposed_formal_apply_records(data)
        if proposed_formal_apply:
            add_issue(
                "blocking",
                "pending_formal_apply_proposal",
                "Proposed formal-apply records are still pending.",
                "Approve, reject, or resolve pending formal-apply proposals before final package creation.",
                proposed_formal_apply[:8],
            )

        blocking_tasks = self._blocking_propagation_tasks(data["phase6_affected_object_review_tasks"])
        if blocking_tasks:
            add_issue(
                "blocking",
                "pending_propagation_review_blocks_final_confirmation",
                "Propagation review tasks that block final confirmation are still pending, deferred, or blocked.",
                "Complete or dismiss blocking propagation review tasks before final package creation.",
                [self._safe_identifier(str(item.get("task_id") or "")) for item in blocking_tasks[:8]],
            )

        provisional_archives = [
            archive
            for archive in data["chapter_archives"]
            if str(archive.get("archive_status") or "").lower() == "provisional"
        ]
        if provisional_archives:
            add_issue(
                "blocking",
                "provisional_chapter_archive",
                "A provisional chapter archive is present.",
                "Convert provisional chapter archives to stable archives or remove them from final package scope.",
                [self._safe_identifier(str(item.get("archive_id") or "")) for item in provisional_archives],
            )

        known_gap_refs = self._known_gap_character_arc_refs(data)
        if known_gap_refs:
            add_issue(
                "warning",
                "known_gap_character_arc_empty_by_design",
                "Character arc evidence includes a known carried-forward gap.",
                "Keep the gap visible in final package residuals or add user-confirmed evidence later.",
                known_gap_refs[:8],
            )

        stable_archives = [
            archive
            for archive in data["chapter_archives"]
            if str(archive.get("archive_status") or "").lower() == "stable"
        ]
        confirmed_scenes_by_id = {
            str(scene.get("scene_id") or ""): scene
            for scene in data["scenes"]
            if str(scene.get("status") or "").lower() == "confirmed"
            and not bool(scene.get("is_provisional"))
        }
        all_scenes_by_id = {
            str(scene.get("scene_id") or ""): scene
            for scene in data["scenes"]
            if isinstance(scene, dict) and str(scene.get("scene_id") or "")
        }
        stable_scene_ids: list[str] = []
        for archive in stable_archives:
            for scene_id in archive.get("confirmed_scene_ids") or archive.get("scene_ids") or []:
                if isinstance(scene_id, str) and scene_id not in stable_scene_ids:
                    stable_scene_ids.append(scene_id)
        confirmed_stable_scene_ids = [scene_id for scene_id in stable_scene_ids if scene_id in confirmed_scenes_by_id]
        incomplete_stable_scene_ids = [scene_id for scene_id in stable_scene_ids if scene_id not in confirmed_scenes_by_id]
        proposal_stable_scene_ids = [
            scene_id
            for scene_id in incomplete_stable_scene_ids
            if str(all_scenes_by_id.get(scene_id, {}).get("status") or "").lower() in {"proposal", "proposed"}
        ]
        candidate_stable_scene_ids = [
            scene_id for scene_id in incomplete_stable_scene_ids if scene_id not in proposal_stable_scene_ids
        ]
        if candidate_stable_scene_ids:
            add_issue(
                "blocking",
                "depends_on_unconfirmed_draft",
                "Stable archive scope references scenes that are not confirmed.",
                "Confirm or remove those scenes before using them as final package truth.",
                [self._safe_identifier(scene_id) for scene_id in candidate_stable_scene_ids[:8]],
            )
        if proposal_stable_scene_ids:
            add_issue(
                "blocking",
                "depends_on_candidate_or_proposal_as_truth",
                "Stable archive scope references proposal scenes as final package truth.",
                "Convert proposal records to formal records before final package creation.",
                [self._safe_identifier(scene_id) for scene_id in proposal_stable_scene_ids[:8]],
            )

        content_health = self._evaluate_m6_content_health(
            confirmed_stable_scene_ids=confirmed_stable_scene_ids,
            confirmed_scenes_by_id=confirmed_scenes_by_id,
        )
        for signal_issue in content_health.issues:
            if signal_issue.code not in {
                PROMPT_FIDELITY_MISSING,
                DEMO_DEFAULT_LEAK,
                SCENE_REPETITION_TOO_HIGH,
                SCENE_PROGRESSION_MISSING,
                SCENE_PROGRESSION_STATEMENT_MISSING,
            }:
                continue
            signal_severity = str(getattr(signal_issue, "severity", "") or "").lower()
            if signal_severity != "blocking":
                continue
            add_issue(
                "blocking",
                signal_issue.code,
                signal_issue.user_visible_message or signal_issue.code,
                "Revise/regenerate affected scenes and rerun Quality/Continuity checks before creating a final package.",
                [self._safe_identifier(ref) for ref in signal_issue.source_refs[:8]],
            )

        sections: list[FinalStoryPackageSection] = []

        def add_section(
            section_type: SectionType,
            content_ref: str,
            validation_status: SectionValidationStatus,
            item_count: int = 0,
            preview: str = "",
            refs: list[str] | None = None,
            warnings: list[str] | None = None,
        ) -> FinalStoryPackageSection:
            section = FinalStoryPackageSection(
                section_id=f"final_story_package_section_{section_type}_{len(sections) + 1:03d}_{suffix}",
                final_story_package_id=package_id,
                section_type=section_type,
                content_ref=self._safe_text(content_ref, limit=180),
                safe_preview=self._safe_text(preview, limit=220),
                item_count=item_count,
                source_ref_ids=refs or [],
                validation_status=validation_status,
                warnings=warnings or [],
                created_at=created_at,
            )
            sections.append(section)
            return section

        archive_ref_ids: list[str] = []
        for archive in stable_archives:
            archive_ref_ids.append(
                add_ref(
                    "chapter_archive",
                    str(archive.get("archive_id") or ""),
                    "formal_story_fact",
                    "Stable chapter archive used as final package sequence metadata.",
                    source_version_id=str(archive.get("version_id") or ""),
                )
            )
        scene_ref_ids: list[str] = []
        for scene_id in confirmed_stable_scene_ids:
            scene = confirmed_scenes_by_id[scene_id]
            scene_ref_ids.append(
                add_ref(
                    "scene",
                    scene_id,
                    "formal_story_fact",
                    "Confirmed scene referenced by stable archive metadata.",
                    source_version_id=str(scene.get("version_id") or ""),
                )
            )
        complete_story_text_ref = ""
        if stable_archives and confirmed_stable_scene_ids:
            sequence_hash = self._hash_text("|".join([*confirmed_stable_scene_ids, *[str(a.get("archive_id")) for a in stable_archives]]))
            complete_story_text_ref = f"confirmed_scene_sequence:{sequence_hash}"
            add_section(
                "complete_story_text",
                complete_story_text_ref,
                "present",
                len(confirmed_stable_scene_ids),
                "Complete story text is represented by confirmed scene sequence metadata only.",
                [*archive_ref_ids, *scene_ref_ids],
            )
        else:
            add_issue(
                "blocking",
                "missing_complete_story_text",
                "Confirmed scene sequence or stable archive metadata is missing.",
                "Create stable chapter archive metadata backed by confirmed scenes before final package creation.",
                ["chapter_archives", "scenes"],
            )
            add_section(
                "complete_story_text",
                "missing:confirmed_scene_sequence",
                "missing",
                0,
                "Missing confirmed scene sequence metadata.",
                [],
            )

        chapter_ids = self._chapter_ids(data["chapters"], stable_archives)
        if chapter_ids and confirmed_stable_scene_ids:
            add_section(
                "chapter_scene_index",
                f"chapter_scene_index:{self._hash_text('|'.join(chapter_ids + confirmed_stable_scene_ids))}",
                "present",
                len(confirmed_stable_scene_ids),
                "Chapter and scene index is derived from stable archive and confirmed scene ids.",
                [*archive_ref_ids, *scene_ref_ids],
            )
        else:
            add_issue(
                "blocking",
                "missing_chapter_scene_index",
                "Chapter-scene index metadata is missing.",
                "Confirm scenes and chapter archive metadata before final package creation.",
                ["chapters", "chapter_archives", "scenes"],
            )
            add_section("chapter_scene_index", "missing:chapter_scene_index", "missing", 0)

        character_ref_ids: list[str] = []
        truth_character_ref_ids: list[str] = []
        for character in data["characters"]:
            if not isinstance(character, dict):
                continue
            character_authority = self._authority_for_status(str(character.get("status") or ""))
            character_ref_id = (
                add_ref(
                    "character",
                    str(character.get("character_id") or character.get("id") or ""),
                    character_authority,
                    "Character table source for final package metadata.",
                    source_version_id=str(character.get("version_id") or ""),
                )
            )
            character_ref_ids.append(character_ref_id)
            if self._is_truth_authority(character_authority):
                truth_character_ref_ids.append(character_ref_id)
        if truth_character_ref_ids:
            add_section(
                "character_table",
                f"character_table:{self._hash_text('|'.join(truth_character_ref_ids))}",
                "present",
                len(truth_character_ref_ids),
                "Character table is represented by confirmed character records.",
                truth_character_ref_ids,
            )
        else:
            add_issue(
                "blocking",
                "missing_character_table",
                "Confirmed character table records are missing.",
                "Confirm character records before final package creation.",
                ["characters"],
            )
            add_section("character_table", "missing:character_table", "missing", 0)

        world_canvas = data["world_canvas"]
        world_canvas_ref_ids: list[str] = []
        world_canvas_truth_ref_ids: list[str] = []
        if world_canvas:
            world_canvas_authority = self._authority_for_status(str(world_canvas.get("status") or ""))
            world_canvas_ref_id = (
                add_ref(
                    "world_canvas",
                    str(world_canvas.get("world_canvas_id") or "world_canvas"),
                    world_canvas_authority,
                    "World canvas summary source for final package metadata.",
                    source_version_id=str(world_canvas.get("version_id") or ""),
                )
            )
            world_canvas_ref_ids.append(world_canvas_ref_id)
            if self._is_truth_authority(world_canvas_authority):
                world_canvas_truth_ref_ids.append(world_canvas_ref_id)
        if world_canvas_truth_ref_ids:
            add_section(
                "world_canvas_summary",
                f"world_canvas_summary:{self._safe_identifier(str(world_canvas.get('world_canvas_id') or 'world_canvas'))}",
                "present",
                1,
                "World canvas summary is represented by confirmed canvas metadata.",
                world_canvas_truth_ref_ids,
            )
        elif world_canvas:
            add_issue(
                "blocking",
                "missing_world_canvas_summary",
                "Confirmed world canvas summary is missing.",
                "Confirm the world canvas before final package creation.",
                world_canvas_ref_ids,
            )
            add_section(
                "world_canvas_summary",
                f"blocked:world_canvas_summary:{self._safe_identifier(str(world_canvas.get('world_canvas_id') or 'world_canvas'))}",
                "blocked",
                0,
                "World canvas summary cannot be satisfied by non-confirmed canvas metadata.",
                world_canvas_ref_ids,
                ["world_canvas_not_confirmed"],
            )
        else:
            add_issue(
                "blocking",
                "missing_world_canvas_summary",
                "World canvas summary is missing.",
                "Confirm a world canvas before final package creation.",
                ["world_canvas"],
            )
            add_section("world_canvas_summary", "missing:world_canvas_summary", "missing", 0)

        relationship_ref_ids: list[str] = []
        truth_relationship_ref_ids: list[str] = []
        for relationship in data["relationships"]:
            if not isinstance(relationship, dict):
                continue
            relationship_status = str(
                relationship.get("status") or relationship.get("relationship_status") or ""
            )
            relationship_authority = self._authority_for_status(relationship_status)
            relationship_ref_id = (
                add_ref(
                    "relationship",
                    str(relationship.get("relationship_id") or relationship.get("id") or ""),
                    relationship_authority,
                    "Relationship-state summary source for final package metadata.",
                    source_version_id=str(relationship.get("version_id") or ""),
                )
            )
            relationship_ref_ids.append(relationship_ref_id)
            if self._is_truth_authority(relationship_authority):
                truth_relationship_ref_ids.append(relationship_ref_id)
        if truth_relationship_ref_ids:
            relationship_status: SectionValidationStatus = "present"
            relationship_section_ref_ids = truth_relationship_ref_ids
            relationship_count = len(truth_relationship_ref_ids)
            relationship_warnings: list[str] = []
        elif relationship_ref_ids:
            relationship_status = "blocked"
            relationship_section_ref_ids = relationship_ref_ids
            relationship_count = 0
            relationship_warnings = ["relationship_sources_not_confirmed"]
        else:
            relationship_status = "warning"
            relationship_section_ref_ids = []
            relationship_count = 0
            relationship_warnings = ["no_relationship_records_found"]
        add_section(
            "relationship_state_summary",
            f"relationship_state_summary:{self._hash_text('|'.join(relationship_section_ref_ids) or 'none')}",
            relationship_status,
            relationship_count,
            "Relationship state summary is explicitly represented.",
            relationship_section_ref_ids,
            relationship_warnings,
        )

        event_ref_ids: list[str] = []
        truth_event_ref_ids: list[str] = []
        for event in data["events"]:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("event_id") or event.get("id") or "")
            if event_id:
                event_status = str(event.get("status") or event.get("event_status") or "")
                event_authority = self._formal_story_fact_authority_for_status(event_status)
                event_ref_id = (
                    add_ref(
                        "event",
                        event_id,
                        event_authority,
                        "Key event timeline source for final package metadata.",
                        source_version_id=str(event.get("version_id") or ""),
                    )
                )
                event_ref_ids.append(event_ref_id)
                if self._is_truth_authority(event_authority):
                    truth_event_ref_ids.append(event_ref_id)
        if truth_event_ref_ids:
            add_section(
                "key_event_timeline",
                f"key_event_timeline:{self._hash_text('|'.join(truth_event_ref_ids))}",
                "present",
                len(truth_event_ref_ids),
                "Key event timeline is represented by event ids only.",
                truth_event_ref_ids,
            )
        elif event_ref_ids:
            add_issue(
                "blocking",
                "missing_key_event_timeline",
                "Confirmed key event timeline records are missing.",
                "Confirm key event records before final package creation.",
                event_ref_ids,
            )
            add_section(
                "key_event_timeline",
                f"blocked:key_event_timeline:{self._hash_text('|'.join(event_ref_ids))}",
                "blocked",
                0,
                "Key event timeline cannot be satisfied by non-confirmed event records.",
                event_ref_ids,
                ["event_sources_not_confirmed"],
            )
        elif confirmed_stable_scene_ids:
            add_section(
                "key_event_timeline",
                f"key_event_timeline_from_confirmed_scenes:{self._hash_text('|'.join(confirmed_stable_scene_ids))}",
                "present",
                len(confirmed_stable_scene_ids),
                "Key event timeline is derived from confirmed scenes in stable archive order.",
                [*archive_ref_ids, *scene_ref_ids],
                ["derived_from_confirmed_scene_sequence"],
            )
        else:
            add_issue(
                "blocking",
                "missing_key_event_timeline",
                "Key event timeline records are missing.",
                "Confirm key event records before final package creation.",
                ["events"],
            )
            add_section("key_event_timeline", "missing:key_event_timeline", "missing", 0)

        locked_refs, locked_count = self._locked_constraint_refs(data, add_ref)
        if locked_count > 0:
            locked_status: SectionValidationStatus = "present"
            locked_warnings: list[str] = []
        elif locked_refs:
            locked_status = "blocked"
            locked_warnings = ["locked_constraint_sources_not_confirmed"]
        else:
            locked_status = "warning"
            locked_warnings = ["no_explicit_locked_constraints_found"]
        add_section(
            "user_locked_constraints",
            f"user_locked_constraints:{self._hash_text('|'.join(locked_refs) or 'none')}",
            locked_status,
            locked_count,
            "User locked constraints are represented by hard rules and hard-limit metadata.",
            locked_refs,
            locked_warnings,
        )

        tone = str(world_canvas.get("tone") or "") if world_canvas else ""
        if tone and world_canvas_truth_ref_ids:
            add_section(
                "style_and_tone",
                f"style_and_tone:{self._safe_identifier(str(world_canvas.get('world_canvas_id') or 'world_canvas'))}",
                "present",
                1,
                "Style and tone are represented by confirmed world-canvas tone metadata.",
                world_canvas_ref_ids,
            )
        elif tone and world_canvas:
            add_section(
                "style_and_tone",
                f"blocked:style_and_tone:{self._safe_identifier(str(world_canvas.get('world_canvas_id') or 'world_canvas'))}",
                "blocked",
                0,
                "Style and tone cannot be satisfied by non-confirmed world-canvas metadata.",
                world_canvas_ref_ids,
                ["world_canvas_not_confirmed"],
            )
        else:
            add_issue(
                "warning",
                "missing_style_and_tone",
                "Style and tone metadata is sparse or missing.",
                "Add or confirm world-canvas tone metadata before export if style fidelity matters.",
                ["world_canvas"],
            )
            add_section("style_and_tone", "missing:style_and_tone", "warning", 0, warnings=["style_and_tone_missing"])

        add_section(
            "source_lineage",
            f"source_lineage:{self._hash_text('|'.join(ref.source_ref_id for ref in source_refs))}",
            "present",
            len(source_refs),
            "Source lineage records authority status for plugin boundary checks.",
            [ref.source_ref_id for ref in source_refs],
        )
        if known_gap_refs:
            add_section(
                "known_residuals",
                f"known_residuals:{self._hash_text('|'.join(known_gap_refs))}",
                "warning",
                len(known_gap_refs),
                "Known residuals are explicitly carried forward as non-clean evidence.",
                [],
                ["known_gap_character_arc_empty_by_design"],
            )

        blocked_truth_refs = [
            ref
            for ref in source_refs
            if ref.authority_status in {"candidate", "proposal", "unconfirmed_draft", "unknown", "reference_only"}
        ]
        if blocked_truth_refs:
            candidate_refs = [
                ref.source_ref_id
                for ref in blocked_truth_refs
                if ref.authority_status in {"candidate", "unconfirmed_draft", "unknown", "reference_only"}
            ]
            proposal_refs = [ref.source_ref_id for ref in blocked_truth_refs if ref.authority_status == "proposal"]
            if candidate_refs:
                add_issue(
                    "blocking",
                    "depends_on_unconfirmed_draft",
                    "Final package metadata depends on unconfirmed draft or candidate truth.",
                    "Confirm or remove all candidate and unconfirmed draft sources before final package creation.",
                    candidate_refs,
                )
            if proposal_refs:
                add_issue(
                    "blocking",
                    "depends_on_candidate_or_proposal_as_truth",
                    "Final package metadata depends on proposal truth.",
                    "Convert proposal records to formal records before final package creation.",
                    proposal_refs,
                )

        missing_required_sections = [
            section.section_type
            for section in sections
            if section.section_type in REQUIRED_SECTION_TYPES and section.validation_status in {"missing", "blocked"}
        ]
        if any(section.section_type == "user_locked_constraints" for section in sections) is False:
            missing_required_sections.append("user_locked_constraints")
        if any(section.section_type == "style_and_tone" for section in sections) is False:
            missing_required_sections.append("style_and_tone")
        if any(section.section_type == "relationship_state_summary" for section in sections) is False:
            missing_required_sections.append("relationship_state_summary")

        warning_issue_ids = [issue.issue_id for issue in issues if issue.severity == "warning"]
        blocking_issue_ids = [issue.issue_id for issue in issues if issue.severity == "blocking"]
        if allow_fixture and blocking_issue_ids:
            readiness_status: ReadinessStatus = "fixture_only"
            package_type: PackageType = "fixture_final_story_package"
            package_status: PackageStatus = "fixture"
            not_real = True
            add_issue(
                "info",
                "fixture_package_only",
                "Fixture package readiness is explicitly non-real and cannot be treated as a final project package.",
                "Use fixture packages only for development verification; create a real package after blockers are resolved.",
                ["fixture"],
            )
        elif blocking_issue_ids:
            readiness_status = "blocked"
            package_type = "real_project_final_package"
            package_status = "blocked"
            not_real = False
        elif warning_issue_ids or any(section.validation_status == "warning" for section in sections):
            readiness_status = "ready_with_warnings"
            package_type = "real_project_final_package"
            package_status = "ready_with_warnings"
            not_real = False
        else:
            readiness_status = "ready"
            package_type = "real_project_final_package"
            package_status = "ready"
            not_real = False

        warning_issue_ids = [issue.issue_id for issue in issues if issue.severity == "warning"]
        blocking_issue_ids = [issue.issue_id for issue in issues if issue.severity == "blocking"]
        package_ready = readiness_status in {"ready", "ready_with_warnings"}
        source_version_ids = sorted({ref.source_version_id for ref in source_refs if ref.source_version_id})

        section_by_type = {section.section_type: section for section in sections}
        final_package = FinalStoryPackage(
            final_story_package_id=package_id,
            project_id=self.project_id,
            package_status=package_status,
            package_type=package_type,
            readiness_status=readiness_status,
            real_final_confirmation_exists=final_confirmation_exists,
            not_real_project_final_package=not_real,
            complete_story_text_ref=section_by_type.get("complete_story_text").content_ref if section_by_type.get("complete_story_text") else "",
            chapter_scene_index_ref=section_by_type.get("chapter_scene_index").content_ref if section_by_type.get("chapter_scene_index") else "",
            character_table_ref=section_by_type.get("character_table").content_ref if section_by_type.get("character_table") else "",
            world_canvas_summary_ref=section_by_type.get("world_canvas_summary").content_ref if section_by_type.get("world_canvas_summary") else "",
            relationship_state_summary_ref=section_by_type.get("relationship_state_summary").content_ref if section_by_type.get("relationship_state_summary") else "",
            key_event_timeline_ref=section_by_type.get("key_event_timeline").content_ref if section_by_type.get("key_event_timeline") else "",
            user_locked_constraints_ref=section_by_type.get("user_locked_constraints").content_ref if section_by_type.get("user_locked_constraints") else "",
            style_and_tone_ref=section_by_type.get("style_and_tone").content_ref if section_by_type.get("style_and_tone") else "",
            manifest_id=manifest_id,
            validation_report_id=report_id,
            readiness_gate_id=gate_id,
            source_ref_ids=[ref.source_ref_id for ref in source_refs],
            version_id=version_id,
            created_at=created_at,
            updated_at=created_at,
            safe_summary=self._summary_for_status(readiness_status),
            warnings=[issue.code for issue in issues if issue.severity in {"warning", "info"}],
        )
        manifest = FinalStoryPackageManifest(
            manifest_id=manifest_id,
            final_story_package_id=package_id,
            project_id=self.project_id,
            package_type=package_type,
            readiness_status=readiness_status,
            content_sections=[section.section_id for section in sections],
            declared_chapter_count=len(chapter_ids),
            declared_scene_count=len(stable_scene_ids),
            detected_chapter_count=len(chapter_ids),
            detected_scene_count=len(confirmed_stable_scene_ids),
            source_version_ids=source_version_ids,
            source_ref_ids=[ref.source_ref_id for ref in source_refs],
            final_confirmation_decision_id=final_confirmation_decision_id,
            fixture_reason="allow_fixture requested while real package readiness is blocked." if package_type == "fixture_final_story_package" else "",
            not_real_project_final_package=not_real,
            created_at=created_at,
            updated_at=created_at,
            safe_summary="Manifest lists final package metadata sections without storing full story prose.",
        )
        validation_report = FinalStoryPackageValidationReport(
            validation_report_id=report_id,
            final_story_package_id=package_id,
            project_id=self.project_id,
            passed=package_ready,
            package_ready=package_ready,
            validation_status=readiness_status,
            missing_required_sections=missing_required_sections,
            blocking_issue_ids=blocking_issue_ids,
            warning_issue_ids=warning_issue_ids,
            has_complete_story_text=self._section_present(section_by_type, "complete_story_text"),
            has_chapter_scene_index=self._section_present(section_by_type, "chapter_scene_index"),
            has_character_table=self._section_present(section_by_type, "character_table"),
            has_world_canvas_summary=self._section_present(section_by_type, "world_canvas_summary"),
            has_relationship_state_summary=self._section_present_or_warning(section_by_type, "relationship_state_summary"),
            has_key_event_timeline=self._section_present(section_by_type, "key_event_timeline"),
            has_user_locked_constraints=self._section_present_or_warning(section_by_type, "user_locked_constraints"),
            has_style_and_tone=self._section_present_or_warning(section_by_type, "style_and_tone"),
            has_final_confirmation_status=final_confirmation_exists,
            has_version_id=bool(version_id),
            has_source_refs=bool(source_refs),
            safe_summary="Validation report records readiness booleans and issue ids only.",
            created_at=created_at,
        )
        gate = FinalStoryPackageReadinessGate(
            readiness_gate_id=gate_id,
            project_id=self.project_id,
            final_story_package_id=package_id,
            readiness_status=readiness_status,
            can_create_real_final_story_package=package_ready,
            can_create_fixture_package=allow_fixture,
            final_confirmation_exists=final_confirmation_exists,
            story_draft_complete_exists=story_draft_complete_exists,
            unresolved_blocking_continuity_issue_exists=bool(continuity_blockers),
            pending_formal_apply_proposal_exists=bool(proposed_formal_apply),
            pending_propagation_review_that_blocks_final_confirmation_exists=bool(blocking_tasks),
            depends_on_unconfirmed_draft_or_candidate=any(
                ref.authority_status in {"candidate", "unconfirmed_draft", "unknown"} for ref in source_refs
            )
            or bool(incomplete_stable_scene_ids),
            depends_on_proposal_as_truth=any(ref.authority_status == "proposal" for ref in source_refs)
            or bool(proposal_stable_scene_ids),
            uses_fixture=package_type == "fixture_final_story_package",
            not_real_project_final_package=not_real,
            blocking_issue_ids=blocking_issue_ids,
            warning_issue_ids=warning_issue_ids,
            recommended_next_step=self._recommended_next_step(
                readiness_status=readiness_status,
                story_draft_complete_exists=story_draft_complete_exists,
                final_confirmation_exists=final_confirmation_exists,
                proposed_formal_apply=bool(proposed_formal_apply),
                blocking_tasks=bool(blocking_tasks),
            ),
            safe_summary=self._summary_for_status(readiness_status),
            created_at=created_at,
            updated_at=created_at,
        )
        response = FinalStoryPackageReadinessEvaluationResponse(
            success=True,
            readiness_gate=gate,
            final_story_package=final_package,
            manifest=manifest,
            validation_report=validation_report,
            sections=sections,
            source_refs=source_refs,
            issues=issues,
            safe_summary=(
                "Final Story Package readiness evaluated. Future plugins may read only a real final package; "
                "fixture packages are marked non-real."
            ),
        )
        self._assert_safe_payload(model_to_dict(response), context="final_story_package_readiness_response")
        if persist:
            self._persist_evaluation(response)
        return response

    def get_readiness_gate(self, readiness_gate_id: str) -> FinalStoryPackageReadinessGate:
        self._assert_active_story_data_available()
        gates = self._read_models_if_exists(self.readiness_gates_file, FinalStoryPackageReadinessGate)
        for gate in gates:
            if gate.readiness_gate_id == readiness_gate_id:
                return gate
        raise StorageError("FINAL_STORY_PACKAGE_READINESS_GATE_NOT_FOUND")

    def list_readiness_issues(self, readiness_gate_id: str) -> FinalStoryPackageReadinessIssueListResponse:
        self._assert_active_story_data_available()
        self.get_readiness_gate(readiness_gate_id)
        issues = [
            issue
            for issue in self._read_models_if_exists(self.readiness_issues_file, FinalStoryPackageReadinessIssue)
            if issue.readiness_gate_id == readiness_gate_id
        ]
        return FinalStoryPackageReadinessIssueListResponse(
            readiness_gate_id=readiness_gate_id,
            issues=issues,
            total_count=len(issues),
        )

    def _assert_active_story_data_available(self) -> None:
        if self._missing_active_project_id:
            raise StorageError(
                "ACTIVE_PROJECT_STORY_DATA_NOT_FOUND:"
                + self._safe_identifier(self._missing_active_project_id)
            )

    def _persist_evaluation(self, response: FinalStoryPackageReadinessEvaluationResponse) -> None:
        writes = {
            self.readiness_gates_file: [response.readiness_gate],
            self.readiness_issues_file: response.issues,
            self.validation_reports_file: [response.validation_report],
            self.source_refs_file: response.source_refs,
            self.sections_file: response.sections,
            self.manifests_file: [response.manifest],
            self.packages_file: [response.final_story_package],
        }
        for path, models in writes.items():
            if path.name not in ALLOWED_M1_STORAGE_FILES:
                raise StorageError(f"FINAL_STORY_PACKAGE_FORBIDDEN_STORAGE_WRITE: {path.name}")
            self._append_models(path, models)

    def _append_models(self, path: Path, models: list[BaseModel]) -> None:
        existing = self._read_list_if_exists(path)
        existing.extend(model_to_dict(model) for model in models)
        self._assert_safe_payload(existing, context=path.name)
        self.store.write(path, existing)

    def _load_story_data(self) -> dict[str, Any]:
        return {
            "story_progress": self._read_dict_if_exists("story_progress.json"),
            "decisions": self._read_list_if_exists(self.data_dir / "decisions.json"),
            "chapter_archives": self._read_list_if_exists(self.data_dir / "chapter_archives.json"),
            "scenes": self._read_list_if_exists(self.data_dir / "scenes.json"),
            "chapters": self._read_list_or_dict_items_if_exists("chapters.json"),
            "events": self._read_list_if_exists(self.data_dir / "events.json"),
            "memory_records": self._read_list_if_exists(self.data_dir / "memory_records.json"),
            "state_changes": self._read_list_if_exists(self.data_dir / "state_changes.json"),
            "characters": self._read_list_if_exists(self.data_dir / "characters.json"),
            "relationships": self._read_list_if_exists(self.data_dir / "relationships.json"),
            "world_canvas": self._read_dict_if_exists("world_canvas.json"),
            "story_bible": self._read_dict_if_exists("story_bible.json"),
            "continuity_issues": self._read_list_if_exists(self.data_dir / "continuity_issues.json"),
            "phase6_formal_apply_proposals": self._read_list_if_exists(self.data_dir / "phase6_formal_apply_proposals.json"),
            "phase6_framework_apply_proposals": self._read_list_if_exists(self.data_dir / "phase6_framework_apply_proposals.json"),
            "phase6_chapter_archive_proposals": self._read_list_if_exists(self.data_dir / "phase6_chapter_archive_proposals.json"),
            "phase6_narrative_debt_proposals": self._read_list_if_exists(self.data_dir / "phase6_narrative_debt_proposals.json"),
            "phase6_propagation_impact_records": self._read_list_if_exists(self.data_dir / "phase6_propagation_impact_records.json"),
            "phase6_affected_object_review_tasks": self._read_list_if_exists(self.data_dir / "phase6_affected_object_review_tasks.json"),
            "phase6_known_gap_carry_forward_records": self._read_list_if_exists(self.data_dir / "phase6_known_gap_carry_forward_records.json"),
            "phase6_known_residuals_carry_forward_reports": self._read_list_if_exists(self.data_dir / "phase6_known_residuals_carry_forward_reports.json"),
            "phase6_release_gate_reports": self._read_list_if_exists(self.data_dir / "phase6_release_gate_reports.json"),
            "phase6_closeout_readiness_reports": self._read_list_if_exists(self.data_dir / "phase6_closeout_readiness_reports.json"),
        }

    def _read_dict_if_exists(self, file_name: str) -> dict[str, Any]:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return {}
        data = self.store.read_any(path)
        if isinstance(data, dict):
            return data
        return {}

    def _read_list_or_dict_items_if_exists(self, file_name: str) -> list[dict[str, Any]]:
        path = self.data_dir / file_name
        if not self.store.exists(path):
            return []
        data = self.store.read_any(path)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("chapters", "items", "records"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [data]
        return []

    def _read_list_if_exists(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        data = self.store.read_any(path)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in (
                "items",
                "records",
                "issues",
                "scenes",
                "events",
                "characters",
                "relationships",
                "reports",
                "known_residuals_reports",
                "release_gate_reports",
                "closeout_readiness_reports",
            ):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _read_models_if_exists(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        items = self._read_list_if_exists(path)
        models = []
        for item in items:
            if isinstance(item, dict):
                models.append(model_type(**item))
        return models

    def _evaluate_m6_content_health(
        self,
        *,
        confirmed_stable_scene_ids: list[str],
        confirmed_scenes_by_id: dict[str, dict[str, Any]],
    ) -> SceneContentQualitySignalReport:
        scenes: list[Scene] = []
        for scene_id in confirmed_stable_scene_ids:
            raw = confirmed_scenes_by_id.get(scene_id)
            if not raw:
                continue
            try:
                scenes.append(Scene(**raw))
            except Exception:
                continue
        if not scenes:
            return SceneContentQualitySignalReport(
                target_type="final_story_package",
                target_id="confirmed_scene_sequence",
                prompt_fidelity_status="not_applicable",
                progression_status="not_applicable",
                generated_at=now_iso(),
            )
        return SceneContentQualitySignalService(
            store=self.store,
            data_dir=self.data_dir,
        ).evaluate_final_sequence(
            scenes=scenes,
            project_id=self.project_id,
        )

    def _story_draft_complete_exists(self, story_progress: dict[str, Any], decisions: list[Any]) -> bool:
        if str(story_progress.get("story_progress_status") or "") == "story_draft_complete":
            return True
        return bool(self._final_confirmation_decision_id(decisions))

    def _final_confirmation_decision_id(self, decisions: list[Any]) -> str:
        for decision in reversed([item for item in decisions if isinstance(item, dict)]):
            if (
                str(decision.get("target_type") or "") == "story_progress"
                and str(decision.get("target_id") or "") == "story_draft_complete"
                and str(decision.get("decision_type") or "") in {"confirm", "approve", "complete"}
            ):
                return self._safe_identifier(str(decision.get("decision_id") or ""))
        return ""

    def _blocking_continuity_issues(self, issues: list[Any]) -> list[dict[str, Any]]:
        blockers = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if str(issue.get("status") or "").lower() != "open":
                continue
            severity = str(issue.get("severity") or "").lower()
            if (
                severity in {"blocking", "requires_user_confirmation"}
                or bool(issue.get("blocks_final_confirmation"))
                or bool(issue.get("requires_explicit_acceptance"))
            ):
                blockers.append(issue)
        return blockers

    def _proposed_formal_apply_records(self, data: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for file_key in (
            "phase6_formal_apply_proposals",
            "phase6_framework_apply_proposals",
            "phase6_chapter_archive_proposals",
            "phase6_narrative_debt_proposals",
        ):
            for item in data[file_key]:
                if not isinstance(item, dict):
                    continue
                if str(item.get("proposal_status") or item.get("status") or "").lower() == "proposed":
                    refs.append(
                        self._safe_identifier(
                            str(
                                item.get("proposal_id")
                                or item.get("framework_proposal_id")
                                or item.get("chapter_archive_proposal_id")
                                or item.get("narrative_debt_proposal_id")
                                or item.get("id")
                                or file_key
                            )
                        )
                    )
        return refs

    def _blocking_propagation_tasks(self, tasks: list[Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in tasks
            if isinstance(item, dict)
            and str(item.get("task_status") or "").lower() in {"pending", "deferred", "blocked"}
            and bool(item.get("blocks_formal_confirmation"))
        ]

    def _known_gap_character_arc_refs(self, data: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        sources = [
            ("phase6_known_gap_carry_forward_record", data["phase6_known_gap_carry_forward_records"]),
            ("phase6_known_residuals_carry_forward_report", data["phase6_known_residuals_carry_forward_reports"]),
            ("phase6_release_gate_report", data["phase6_release_gate_reports"]),
            ("phase6_closeout_readiness_report", data["phase6_closeout_readiness_reports"]),
        ]
        for source_type, items in sources:
            for item in items:
                if not isinstance(item, dict):
                    continue
                blob = json.dumps(item, ensure_ascii=False).lower()
                if "character_arc_empty_by_design" not in blob:
                    continue
                refs.append(
                    self._safe_identifier(
                        str(
                            item.get("gap_id")
                            or item.get("known_residuals_report_id")
                            or item.get("release_gate_report_id")
                            or item.get("closeout_readiness_report_id")
                            or item.get("record_id")
                            or source_type
                        )
                    )
                )
        return refs

    def _chapter_ids(self, chapters: list[dict[str, Any]], stable_archives: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for chapter in chapters:
            chapter_id = str(chapter.get("chapter_id") or chapter.get("id") or "")
            if chapter_id and chapter_id not in ids:
                ids.append(chapter_id)
        for archive in stable_archives:
            chapter_id = str(archive.get("chapter_id") or "")
            if chapter_id and chapter_id not in ids:
                ids.append(chapter_id)
        return ids

    def _locked_constraint_refs(self, data: dict[str, Any], add_ref: Any) -> tuple[list[str], int]:
        refs: list[str] = []
        truth_count = 0
        world_canvas = data["world_canvas"]
        world_canvas_authority = (
            self._authority_for_status(str(world_canvas.get("status") or ""))
            if isinstance(world_canvas, dict)
            else "unknown"
        )
        for rule in world_canvas.get("hard_rules") or [] if isinstance(world_canvas, dict) else []:
            if isinstance(rule, dict):
                rule_status = str(rule.get("status") or rule.get("rule_status") or "")
                rule_authority = self._authority_for_status(rule_status) if rule_status else world_canvas_authority
                refs.append(
                    add_ref(
                        "world_canvas_hard_rule",
                        str(rule.get("rule_id") or ""),
                        rule_authority,
                        "World hard rule included as locked final-package constraint metadata.",
                        source_version_id=str(rule.get("version_id") or world_canvas.get("version_id") or ""),
                    )
                )
                if self._is_truth_authority(rule_authority):
                    truth_count += 1
        for character in data["characters"]:
            if not isinstance(character, dict):
                continue
            profile = character.get("profile") if isinstance(character.get("profile"), dict) else {}
            hard_limits = profile.get("hard_limits") or character.get("hard_limits")
            if hard_limits:
                character_authority = self._authority_for_status(str(character.get("status") or ""))
                refs.append(
                    add_ref(
                        "character_hard_limits",
                        str(character.get("character_id") or character.get("id") or ""),
                        character_authority,
                        "Character hard limits included as locked final-package constraint metadata.",
                        source_version_id=str(character.get("version_id") or ""),
                    )
                )
                if self._is_truth_authority(character_authority):
                    truth_count += 1
        for event in data["events"]:
            if not isinstance(event, dict):
                continue
            if event.get("locked") or event.get("is_locked") or event.get("future_event_locked"):
                event_authority = self._formal_story_fact_authority_for_status(
                    str(event.get("status") or event.get("event_status") or "")
                )
                refs.append(
                    add_ref(
                        "locked_event_constraint",
                        str(event.get("event_id") or event.get("id") or ""),
                        event_authority,
                        "Locked event metadata included as user constraint source.",
                        source_version_id=str(event.get("version_id") or ""),
                    )
                )
                if self._is_truth_authority(event_authority):
                    truth_count += 1
        return refs, truth_count

    def _authority_for_status(self, status: str) -> AuthorityStatus:
        normalized = status.lower().strip()
        if normalized in {"confirmed", "stable", "final_complete", "active", "applied"}:
            return "user_confirmed"
        if normalized in {"candidate"}:
            return "candidate"
        if normalized in {"proposal", "proposed"}:
            return "proposal"
        if normalized in {"draft", "unconfirmed", "unconfirmed_draft", "outputs", "provisional"}:
            return "unconfirmed_draft"
        if not normalized:
            return "unknown"
        return "reference_only"

    def _is_truth_authority(self, authority_status: AuthorityStatus) -> bool:
        return authority_status in {"formal_story_fact", "user_confirmed"}

    def _formal_story_fact_authority_for_status(self, status: str) -> AuthorityStatus:
        normalized = status.lower().strip()
        if normalized in {"confirmed", "stable", "final_complete", "active", "applied"}:
            return "formal_story_fact"
        if normalized == "candidate":
            return "candidate"
        if normalized in {"proposal", "proposed"}:
            return "proposal"
        if normalized in {"draft", "unconfirmed", "unconfirmed_draft", "outputs", "provisional"}:
            return "unconfirmed_draft"
        if not normalized:
            return "unknown"
        return "reference_only"

    def _recommended_next_step(
        self,
        *,
        readiness_status: ReadinessStatus,
        story_draft_complete_exists: bool,
        final_confirmation_exists: bool,
        proposed_formal_apply: bool,
        blocking_tasks: bool,
    ) -> str:
        if readiness_status == "fixture_only":
            return "use_fixture_only"
        if readiness_status in {"ready", "ready_with_warnings"}:
            return "export_final_story_package_in_m2"
        if not story_draft_complete_exists or not final_confirmation_exists:
            return "complete_story_draft_confirmation"
        if proposed_formal_apply:
            return "resolve_pending_proposals"
        if blocking_tasks:
            return "review_propagation_tasks"
        if readiness_status == "blocked":
            return "resolve_blocking_issues"
        return "not_ready"

    def _section_present(self, sections: dict[str, FinalStoryPackageSection], section_type: SectionType) -> bool:
        section = sections.get(section_type)
        return bool(section and section.validation_status == "present")

    def _section_present_or_warning(
        self,
        sections: dict[str, FinalStoryPackageSection],
        section_type: SectionType,
    ) -> bool:
        section = sections.get(section_type)
        return bool(section and section.validation_status in {"present", "warning"})

    def _summary_for_status(self, readiness_status: ReadinessStatus) -> str:
        if readiness_status == "fixture_only":
            return "Fixture-only readiness is non-real and cannot be used as a real final project package."
        if readiness_status == "blocked":
            return "Final Story Package readiness is blocked by unresolved formal boundary issues."
        if readiness_status == "ready_with_warnings":
            return "Final Story Package can be created for future plugin input with visible warnings."
        return "Final Story Package can be created as the only future plugin input."

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def _id_suffix(self, created_at: str) -> str:
        return self._hash_text(created_at)[:10]

    def _safe_identifier(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-:.]", "_", value.strip())
        return cleaned[:120] or "unknown"

    def _safe_text(self, value: str, *, limit: int = 180) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        for marker in UNSAFE_VALUE_MARKERS:
            text = re.sub(re.escape(marker), "[redacted]", text, flags=re.IGNORECASE)
        text = SECRET_LIKE_RE.sub("[redacted-secret]", text)
        if len(text) > limit:
            text = text[: max(0, limit - 3)].rstrip() + "..."
        return text

    def _assert_safe_payload(self, payload: Any, *, context: str) -> None:
        unsafe_paths: list[str] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    key_text = str(key)
                    key_lower = key_text.lower()
                    if any(part in key_lower for part in UNSAFE_KEY_PARTS):
                        unsafe_paths.append(f"{path}.{key_text}")
                    walk(nested, f"{path}.{key_text}")
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    walk(nested, f"{path}[{index}]")
            elif isinstance(value, str):
                lowered = value.lower()
                if SECRET_LIKE_RE.search(value) or any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    unsafe_paths.append(path)

        walk(payload, context)
        if unsafe_paths:
            raise StorageError(
                "FINAL_STORY_PACKAGE_UNSAFE_PAYLOAD_BLOCKED: "
                + ", ".join(sorted(set(unsafe_paths))[:8])
            )
