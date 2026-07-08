import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.chapter_archive import (
    CHAPTER_ARCHIVE_VERSION_ID,
    ChapterArchivePreview,
    ChapterArchiveRecord,
    ChapterArchiveRequest,
    ChapterArchiveResponse,
    ChapterArchiveValidationIssue,
    ChapterArchiveValidationReport,
    ChapterOutcomeSummary,
)
from app.backend.models.decision import Decision
from app.backend.models.framework_package import ChapterFrameworkBuildResult
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import SceneProgressResponse
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.chapter_framework_builder_service import (
    ChapterFrameworkBuilderService,
)
from app.backend.services.scene_gate_readiness_service import SceneGateReadinessService
from app.backend.services.scene_progress_service import SceneProgressService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
FINAL_SCENE_STATUSES = {"confirmed", "committed", "revised"}
UNSAFE_TEXT_MARKERS = [
    "raw_prompt",
    "raw_response",
    "api_key",
    "hidden_reasoning",
    "internal_reasoning",
    "prose_text",
    "sk-",
    "lsv2_",
]
UNSAFE_TEXT_PATTERNS = [
    re.compile(r"raw[\s_-]*prompt", re.IGNORECASE),
    re.compile(r"raw[\s_-]*response", re.IGNORECASE),
    re.compile(r"api[\s_-]*key", re.IGNORECASE),
    re.compile(r"hidden[\s_-]*reasoning", re.IGNORECASE),
    re.compile(r"internal[\s_-]*reasoning", re.IGNORECASE),
    re.compile(r"prose[\s_-]*text", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"lsv2_[A-Za-z0-9_]+", re.IGNORECASE),
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class ChapterArchiveService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        framework_builder: ChapterFrameworkBuilderService | None = None,
        scene_progress_service: SceneProgressService | None = None,
        scene_gate_readiness_service: SceneGateReadinessService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_builder = framework_builder or ChapterFrameworkBuilderService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_progress_service = scene_progress_service or SceneProgressService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scene_gate_readiness_service = (
            scene_gate_readiness_service
            or SceneGateReadinessService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.archive_file = self.data_dir / "chapter_archives.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.chapter_plan_draft_file = self.data_dir / "chapter_plan_draft.json"

    def preview_archive(
        self,
        chapter_id: str | None = None,
        chapter_index: int | None = None,
    ) -> ChapterArchivePreview:
        chapter, resolve_issues = self._resolve_chapter(
            chapter_id=chapter_id,
            chapter_index=chapter_index,
        )
        if chapter is None:
            report = ChapterArchiveValidationReport(
                passed=False,
                archive_mode="blocked",
                blocking_issues=resolve_issues
                or [
                    self._issue(
                        "CHAPTER_ARCHIVE_NOT_READY",
                        "No current chapter is available for archive preview.",
                        "blocking",
                    )
                ],
            )
            return ChapterArchivePreview(
                chapter_id=chapter_id or "",
                chapter_index=chapter_index or 0,
                recommended_archive_mode="blocked",
                validation_report=report,
                user_visible_summary="Chapter archive is not ready.",
            )

        existing = self._find_archive(chapter.chapter_id, chapter.chapter_index)
        validation_context = self._validate_archive_candidate(chapter, resolve_issues)
        report = validation_context["report"]
        candidate = None
        if existing is None and report.passed and report.archive_mode in {"stable", "provisional"}:
            candidate = self._build_archive_record(
                chapter=chapter,
                archive_status=report.archive_mode,
                validation_context=validation_context,
                source_decision_id="",
            )

        summary = self._preview_summary(
            chapter=chapter,
            existing=existing,
            candidate=candidate,
            report=report,
        )
        return ChapterArchivePreview(
            chapter_id=chapter.chapter_id,
            chapter_index=chapter.chapter_index,
            recommended_archive_mode=report.archive_mode,
            existing_archive=existing,
            archive_candidate=candidate,
            validation_report=report,
            scene_progress=validation_context.get("progress"),
            user_visible_summary=summary,
        )

    def archive_chapter(self, request: ChapterArchiveRequest) -> ChapterArchiveResponse:
        preview = self.preview_archive(
            chapter_id=request.chapter_id,
            chapter_index=request.chapter_index,
        )
        if preview.existing_archive is not None:
            self._require_archive_scenes_ready(
                list(
                    preview.existing_archive.confirmed_scene_ids
                    or preview.existing_archive.scene_ids
                    or []
                ),
                boundary_code="CHAPTER_ARCHIVE_EXISTING_GATE_READINESS_BLOCKED",
            )
            self._sync_chapter_metadata_after_archive(preview.existing_archive)
            return ChapterArchiveResponse(
                archive=preview.existing_archive,
                preview=preview,
                returned_existing=True,
            )
        report = preview.validation_report
        if not report.passed or preview.archive_candidate is None:
            raise StorageError(
                "CHAPTER_ARCHIVE_NOT_READY: Chapter archive validation has blocking issues."
            )
        if request.archive_mode == "stable" and report.archive_mode != "stable":
            raise StorageError(
                "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE: Stable archive requires final_complete progress and no provisional dependencies."
            )
        if request.archive_mode == "provisional":
            if report.archive_mode != "provisional":
                raise StorageError(
                    "CHAPTER_ARCHIVE_NOT_READY: Provisional archive is only available for provisional_complete chapters."
                )
            if not request.accept_warnings:
                raise StorageError(
                    "CHAPTER_ARCHIVE_PROVISIONAL_ACCEPTANCE_REQUIRED: Provisional archive requires accept_warnings=true."
                )
        if report.archive_mode == "provisional" and request.archive_mode == "stable":
            raise StorageError(
                "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE: Validation recommends provisional archive."
            )

        decision_type = "confirm" if request.archive_mode == "stable" else "accept_warning"
        decision = self._build_decision(
            decision_type=decision_type,
            target_id=preview.archive_candidate.archive_id,
            user_input=request.user_input,
        )
        archive = preview.archive_candidate.copy(deep=True)
        archive.archive_status = request.archive_mode
        archive.source_decision_id = decision.decision_id
        archive.updated_at = now_iso()
        self._require_archive_scenes_ready(
            list(archive.confirmed_scene_ids or archive.scene_ids or []),
            boundary_code="CHAPTER_ARCHIVE_GATE_READINESS_BLOCKED",
        )

        archives = self._read_archives()
        if self._find_archive(archive.chapter_id, archive.chapter_index, archives):
            raise StorageError(
                "CHAPTER_ARCHIVE_ALREADY_EXISTS: Chapter archive already exists."
            )
        archives.append(archive)
        archives.sort(key=lambda item: item.chapter_index)
        self._write_archives(archives)
        self._sync_chapter_metadata_after_archive(archive)
        self._append_decision(decision)
        return ChapterArchiveResponse(
            archive=archive,
            preview=preview,
            decision=decision,
        )

    def get_archive_by_chapter(self, chapter_id: str) -> ChapterArchiveResponse:
        archive = self._find_archive(chapter_id, None)
        if archive is None:
            raise StorageError("CHAPTER_ARCHIVE_NOT_FOUND: No archive exists for this chapter.")
        return ChapterArchiveResponse(archive=archive)

    def list_archives(self) -> list[ChapterArchiveRecord]:
        return sorted(self._read_archives(), key=lambda item: item.chapter_index)

    def _validate_archive_candidate(
        self,
        chapter: Chapter,
        initial_issues: list[ChapterArchiveValidationIssue],
    ) -> dict[str, Any]:
        blocking: list[ChapterArchiveValidationIssue] = list(initial_issues)
        warnings: list[ChapterArchiveValidationIssue] = []
        progress = self.scene_progress_service.get_progress(chapter.chapter_id)
        scenes = self._required_scenes(chapter)
        scene_by_index = {scene.scene_index: scene for scene in scenes}
        required_indexes = list(range(1, max(0, chapter.scene_count or 0) + 1))
        missing_indexes = [
            index for index in required_indexes if index not in scene_by_index
        ]

        if chapter.scene_count < 1:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_NOT_READY",
                    "Current chapter has no scene_count.",
                    "blocking",
                    "chapter",
                    chapter.chapter_id,
                )
            )
        for index in missing_indexes:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_NOT_READY",
                    f"Required scene {index} is missing.",
                    "blocking",
                    "scene_index",
                    str(index),
                )
            )

        archive_mode = self._mode_from_progress(progress.completion_status)
        if archive_mode == "blocked":
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_NOT_READY",
                    f"Chapter progress is {progress.completion_status}; archive is only available after final or provisional completion.",
                    "blocking",
                    "chapter",
                    chapter.chapter_id,
                )
            )

        if archive_mode == "stable":
            for scene in scene_by_index.values():
                if scene.status not in FINAL_SCENE_STATUSES:
                    blocking.append(
                        self._issue(
                            "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE",
                            f"Scene {scene.scene_index} status is {scene.status}; stable archive requires confirmed, committed, or revised.",
                            "blocking",
                            "scene",
                            scene.scene_id,
                        )
                    )
                self._append_stable_dependency_issues(scene, blocking)
        elif archive_mode == "provisional":
            for scene in scene_by_index.values():
                self._append_provisional_warnings(scene, warnings)
            if warnings:
                warnings.append(
                    self._issue(
                        "CHAPTER_ARCHIVE_PROVISIONAL_ACCEPTANCE_REQUIRED",
                        "Provisional archive preserves temporary/provisional dependencies and requires explicit acceptance.",
                        "warning",
                        "chapter",
                        chapter.chapter_id,
                    )
                )

        framework_result = self._audited_framework_result(chapter, blocking)
        if scene_by_index:
            try:
                self._require_archive_scenes_ready(
                    [
                        scene.scene_id
                        for scene in scene_by_index.values()
                        if scene.status in FINAL_SCENE_STATUSES
                    ],
                    boundary_code="CHAPTER_ARCHIVE_GATE_READINESS_BLOCKED",
                )
            except StorageError as exc:
                blocking.append(
                    self._issue(
                        "CHAPTER_ARCHIVE_GATE_READINESS_BLOCKED",
                        str(exc),
                        "blocking",
                        "chapter",
                        chapter.chapter_id,
                    )
                )
        continuity_issues = self._continuity_issues_for_chapter(chapter, scenes)
        for issue in continuity_issues:
            if self._is_blocking_continuity_issue(issue):
                blocking.append(
                    self._issue(
                        "CHAPTER_ARCHIVE_NOT_READY",
                        self._safe_text(
                            issue.get("user_visible_message")
                            or issue.get("technical_summary")
                            or "Open blocking continuity issue prevents archive.",
                            260,
                        ),
                        "blocking",
                        "continuity_issue",
                        str(issue.get("issue_id") or ""),
                    )
                )
            elif str(issue.get("status") or "") == "open":
                warnings.append(
                    self._issue(
                        "open_continuity_issue_listed",
                        self._safe_text(
                            issue.get("user_visible_message")
                            or issue.get("technical_summary")
                            or "Open continuity issue is listed in the archive.",
                            260,
                        ),
                        "warning",
                        "continuity_issue",
                        str(issue.get("issue_id") or ""),
                    )
                )

        if blocking:
            archive_mode = "blocked"
        report = ChapterArchiveValidationReport(
            passed=not blocking and archive_mode in {"stable", "provisional"},
            archive_mode=archive_mode,
            blocking_issues=self._dedupe_issues(blocking),
            warnings=self._dedupe_issues(warnings),
            user_confirmation_needed=(
                ["accept_provisional_archive"]
                if archive_mode == "provisional" and not blocking
                else []
            ),
        )
        return {
            "report": report,
            "progress": progress,
            "scenes": [scene_by_index[index] for index in required_indexes if index in scene_by_index],
            "framework_result": framework_result,
            "continuity_issues": continuity_issues,
            "narrative_debts": self._narrative_debts_for_chapter(chapter, scenes),
        }

    def _require_archive_scenes_ready(
        self,
        scene_ids: list[Any],
        *,
        boundary_code: str,
    ) -> list[dict[str, Any]]:
        clean_scene_ids = self._unique_strings(scene_ids)
        if not clean_scene_ids:
            raise StorageError(f"{boundary_code}: chapter_archive_scene_ids_missing")
        return self.scene_gate_readiness_service.require_scenes_safe_to_release(
            clean_scene_ids,
            boundary_code=boundary_code,
            mode="chapter_archive",
        )

    def _build_archive_record(
        self,
        *,
        chapter: Chapter,
        archive_status: str,
        validation_context: dict[str, Any],
        source_decision_id: str,
    ) -> ChapterArchiveRecord:
        timestamp = now_iso()
        scenes: list[Scene] = validation_context["scenes"]
        progress: SceneProgressResponse = validation_context["progress"]
        framework_result: ChapterFrameworkBuildResult | None = validation_context.get(
            "framework_result"
        )
        framework = framework_result.chapter_framework if framework_result else None
        build_context = framework_result.build_context if framework_result else None
        continuity_issues = validation_context.get("continuity_issues") or []
        narrative_debts = validation_context.get("narrative_debts") or []
        event_ids = self._scene_event_ids(scenes)
        memory_ids = self._scene_memory_ids(scenes)
        state_change_ids = self._scene_state_change_ids(scenes)
        events = self._events_by_ids(event_ids)
        memories = self._memories_for_archive(chapter, scenes, memory_ids)
        state_changes = self._state_changes_by_ids(state_change_ids)
        summary = self._archive_summary(chapter, scenes, progress.completion_status)
        validation_report: ChapterArchiveValidationReport = validation_context["report"]

        return ChapterArchiveRecord(
            archive_id=self._next_archive_id(),
            project_id=LOCAL_PROJECT_ID,
            chapter_id=chapter.chapter_id,
            chapter_index=chapter.chapter_index,
            chapter_framework_id=(framework.chapter_framework_id if framework else chapter.chapter_framework_id),
            chapter_framework_build_context_id=(
                build_context.build_context_id if build_context else ""
            ),
            archive_status=archive_status,
            chapter_completion_status=progress.completion_status,
            scene_ids=[scene.scene_id for scene in scenes],
            confirmed_scene_ids=[
                scene.scene_id for scene in scenes if scene.status in FINAL_SCENE_STATUSES
            ],
            temporary_scene_ids=[
                scene.scene_id for scene in scenes if scene.status == "temporary_confirmed"
            ],
            provisional_scene_ids=[
                scene.scene_id for scene in scenes if scene.is_provisional
            ],
            provisional_memory_ids=self._provisional_memory_ids(scenes, memories),
            dependent_scene_ids=self._dependent_scene_ids(scenes),
            summary=summary,
            outcome_summary=ChapterOutcomeSummary(
                chapter_goal_result=self._chapter_goal_result(chapter),
                reader_emotion_result=self._reader_emotion_result(),
                character_arc_progress=self._change_refs(
                    state_changes,
                    target_type="character",
                ),
                relationship_progress=self._change_refs(
                    state_changes,
                    target_type="relationship",
                ),
                conflict_state=self._safe_text(chapter.main_conflict, 360),
                open_threads=self._open_thread_summaries(continuity_issues, narrative_debts),
                closed_threads=[
                    self._safe_text(event.get("summary"), 240)
                    for event in events[:8]
                    if event.get("summary")
                ],
                next_chapter_seeds=self._next_seed_summaries(narrative_debts),
                world_state_notes=[
                    self._safe_text(memory.get("summary"), 240)
                    for memory in memories[:8]
                    if memory.get("summary")
                ],
                unresolved_risks=[
                    issue.message
                    for issue in [
                        *validation_report.blocking_issues,
                        *validation_report.warnings,
                    ][:10]
                ],
                user_visible_summary=summary,
            ),
            key_event_ids=[event.get("event_id", "") for event in events if event.get("event_id")],
            key_events=[
                self._safe_text(event.get("summary"), 260)
                for event in events[:10]
                if event.get("summary")
            ],
            character_change_refs=[
                change.get("state_change_id", "")
                for change in state_changes
                if str(change.get("target_type") or "") == "character"
            ],
            relationship_change_refs=[
                change.get("state_change_id", "")
                for change in state_changes
                if str(change.get("target_type") or "") == "relationship"
            ],
            memory_refs=[memory.get("memory_id", "") for memory in memories if memory.get("memory_id")],
            unresolved_issue_ids=[
                issue.get("issue_id", "")
                for issue in continuity_issues
                if str(issue.get("status") or "") == "open"
            ],
            unresolved_issue_summary=[
                self._safe_text(
                    issue.get("user_visible_message")
                    or issue.get("technical_summary")
                    or issue.get("issue_id"),
                    260,
                )
                for issue in continuity_issues
                if str(issue.get("status") or "") == "open"
            ][:10],
            narrative_debt_ids=[
                debt.get("narrative_debt_id", "")
                for debt in narrative_debts
                if debt.get("narrative_debt_id")
            ],
            narrative_debt_summary=[
                self._safe_text(debt.get("summary") or debt.get("narrative_debt_id"), 260)
                for debt in narrative_debts[:10]
            ],
            validation_report=validation_report,
            source_decision_id=source_decision_id,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=CHAPTER_ARCHIVE_VERSION_ID,
        )

    def _resolve_chapter(
        self,
        *,
        chapter_id: str | None,
        chapter_index: int | None,
    ) -> tuple[Chapter | None, list[ChapterArchiveValidationIssue]]:
        chapters = self._read_chapters()
        issues: list[ChapterArchiveValidationIssue] = []
        clean_id = str(chapter_id or "").strip()
        if chapter_index is not None and chapter_index < 1:
            issues.append(
                self._issue(
                    "CHAPTER_ARCHIVE_ID_INDEX_MISMATCH",
                    "chapter_index must be greater than 0.",
                    "blocking",
                    "chapter_index",
                    str(chapter_index),
                )
            )
            return None, issues
        if clean_id and chapter_index is not None:
            matched = next(
                (chapter for chapter in chapters if chapter.chapter_id == clean_id),
                None,
            )
            inferred = self._chapter_index_from_id(clean_id)
            if matched and matched.chapter_index != chapter_index:
                issues.append(
                    self._issue(
                        "CHAPTER_ARCHIVE_ID_INDEX_MISMATCH",
                        "chapter_id points to a different chapter_index.",
                        "blocking",
                        "chapter",
                        clean_id,
                    )
                )
            if inferred is not None and inferred != chapter_index:
                issues.append(
                    self._issue(
                        "CHAPTER_ARCHIVE_ID_INDEX_MISMATCH",
                        "chapter_id suffix does not match chapter_index.",
                        "blocking",
                        "chapter",
                        clean_id,
                    )
                )
            return matched, issues if issues else ([] if matched else [
                self._issue(
                    "CHAPTER_ARCHIVE_NOT_READY",
                    "Requested chapter_id does not exist.",
                    "blocking",
                    "chapter",
                    clean_id,
                )
            ])
        if clean_id:
            matched = next(
                (chapter for chapter in chapters if chapter.chapter_id == clean_id),
                None,
            )
            if matched:
                return matched, []
            return None, [
                self._issue(
                    "CHAPTER_ARCHIVE_NOT_READY",
                    "Requested chapter_id does not exist.",
                    "blocking",
                    "chapter",
                    clean_id,
                )
            ]
        if chapter_index is not None:
            matched = next(
                (chapter for chapter in chapters if chapter.chapter_index == chapter_index),
                None,
            )
            if matched:
                return matched, []
            return None, [
                self._issue(
                    "CHAPTER_ARCHIVE_NOT_READY",
                    "Requested chapter_index does not exist.",
                    "blocking",
                    "chapter_index",
                    str(chapter_index),
                )
            ]
        current = (
            next((chapter for chapter in chapters if chapter.detail_level == "current_chapter_brief"), None)
            or next((chapter for chapter in chapters if chapter.status == "active"), None)
            or next((chapter for chapter in chapters if chapter.chapter_framework_id), None)
            or (chapters[0] if chapters else None)
        )
        return current, []

    def _audited_framework_result(
        self,
        chapter: Chapter,
        blocking: list[ChapterArchiveValidationIssue],
    ) -> ChapterFrameworkBuildResult | None:
        try:
            result = self.framework_builder.get_current_chapter_framework(
                chapter_id=chapter.chapter_id,
                chapter_index=chapter.chapter_index,
            )
        except StorageError as exc:
            message = str(exc)
            code = (
                "CHAPTER_ARCHIVE_ID_INDEX_MISMATCH"
                if "CURRENT_CHAPTER_ID_INDEX_MISMATCH" in message
                else "CHAPTER_ARCHIVE_FRAMEWORK_AUDIT_MISSING"
            )
            blocking.append(
                self._issue(
                    code,
                    message,
                    "blocking",
                    "chapter_framework",
                    chapter.chapter_framework_id,
                )
            )
            return None
        framework = result.chapter_framework
        if framework is None or result.build_context is None or not result.build_reasons:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_FRAMEWORK_AUDIT_MISSING",
                    "Current chapter framework is missing M2 audit context or reasons.",
                    "blocking",
                    "chapter_framework",
                    chapter.chapter_framework_id,
                )
            )
            return result
        if chapter.chapter_framework_id and framework.chapter_framework_id != chapter.chapter_framework_id:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_FRAMEWORK_AUDIT_MISSING",
                    "Chapter.chapter_framework_id does not match the M2 current chapter framework.",
                    "blocking",
                    "chapter_framework",
                    chapter.chapter_framework_id,
                )
            )
        return result

    def _append_stable_dependency_issues(
        self,
        scene: Scene,
        blocking: list[ChapterArchiveValidationIssue],
    ) -> None:
        if scene.status == "temporary_confirmed":
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE",
                    f"Scene {scene.scene_index} is temporary_confirmed.",
                    "blocking",
                    "scene",
                    scene.scene_id,
                )
            )
        if scene.is_provisional:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE",
                    f"Scene {scene.scene_index} is provisional.",
                    "blocking",
                    "scene",
                    scene.scene_id,
                )
            )
        for memory_id in scene.depends_on_provisional_memory_ids:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE",
                    f"Scene {scene.scene_index} depends on provisional memory {memory_id}.",
                    "blocking",
                    "memory",
                    memory_id,
                )
            )
        for scene_id in scene.depends_on_provisional_scene_ids:
            blocking.append(
                self._issue(
                    "CHAPTER_ARCHIVE_STABLE_REQUIRES_FINAL_COMPLETE",
                    f"Scene {scene.scene_index} depends on provisional scene {scene_id}.",
                    "blocking",
                    "scene",
                    scene_id,
                )
            )

    def _append_provisional_warnings(
        self,
        scene: Scene,
        warnings: list[ChapterArchiveValidationIssue],
    ) -> None:
        if scene.status == "temporary_confirmed":
            warnings.append(
                self._issue(
                    "temporary_scene_preserved",
                    f"Scene {scene.scene_index} is temporary_confirmed and will remain visible as provisional.",
                    "warning",
                    "scene",
                    scene.scene_id,
                )
            )
        if scene.is_provisional:
            warnings.append(
                self._issue(
                    "provisional_scene_preserved",
                    f"Scene {scene.scene_index} is provisional and will remain visible as provisional.",
                    "warning",
                    "scene",
                    scene.scene_id,
                )
            )
        for memory_id in scene.depends_on_provisional_memory_ids:
            warnings.append(
                self._issue(
                    "provisional_memory_preserved",
                    f"Scene {scene.scene_index} depends on provisional memory {memory_id}.",
                    "warning",
                    "memory",
                    memory_id,
                )
            )
        for scene_id in scene.depends_on_provisional_scene_ids:
            warnings.append(
                self._issue(
                    "provisional_scene_dependency_preserved",
                    f"Scene {scene.scene_index} depends on provisional scene {scene_id}.",
                    "warning",
                    "scene",
                    scene_id,
                )
            )

    def _required_scenes(self, chapter: Chapter) -> list[Scene]:
        scenes: list[Scene] = []
        for item in self.repositories.scenes.list_all():
            if item.get("chapter_id") != chapter.chapter_id:
                continue
            try:
                scene = Scene(**item)
            except ValidationError as exc:
                raise StorageError("Scene JSON schema is invalid.") from exc
            if 1 <= scene.scene_index <= max(0, chapter.scene_count or 0):
                scenes.append(scene)
        return sorted(scenes, key=lambda item: item.scene_index)

    def _read_chapters(self) -> list[Chapter]:
        chapters: list[Chapter] = []
        try:
            for item in self.repositories.chapters.list_all():
                chapters.append(Chapter(**item))
        except ValidationError as exc:
            raise StorageError("Chapters JSON schema is invalid.") from exc
        return sorted(chapters, key=lambda item: item.chapter_index or 0)

    def _read_archives(self) -> list[ChapterArchiveRecord]:
        if not self.store.exists(self.archive_file):
            return []
        data = self.store.read_list(self.archive_file)
        try:
            return [
                ChapterArchiveRecord(**item)
                for item in data
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("ChapterArchive JSON schema is invalid.") from exc

    def _write_archives(self, archives: list[ChapterArchiveRecord]) -> None:
        payload = [model_to_dict(archive) for archive in archives]
        self._assert_archive_payload_safe(payload)
        self.store.write(self.archive_file, payload)

    def _sync_chapter_metadata_after_archive(self, archive: ChapterArchiveRecord) -> None:
        chapters = self.repositories.chapters.list_all()
        scene_ids = list(archive.scene_ids or archive.confirmed_scene_ids or [])
        scene_count = max(len(scene_ids), len(archive.confirmed_scene_ids or []))
        updated: list[dict[str, Any]] = []
        changed = False
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter = dict(item)
            chapter_id = str(chapter.get("chapter_id") or "")
            chapter_index = int(chapter.get("chapter_index") or 0)
            if chapter_id == archive.chapter_id or chapter_index == archive.chapter_index:
                if scene_ids and chapter.get("scene_ids") != scene_ids:
                    chapter["scene_ids"] = scene_ids
                    changed = True
                if scene_count:
                    existing_scene_count = int(chapter.get("scene_count") or 0)
                    next_scene_count = max(existing_scene_count, scene_count)
                    if chapter.get("scene_count") != next_scene_count:
                        chapter["scene_count"] = next_scene_count
                        changed = True
                if archive.chapter_framework_id and chapter.get("chapter_framework_id") != archive.chapter_framework_id:
                    chapter["chapter_framework_id"] = archive.chapter_framework_id
                    changed = True
                if chapter.get("status") != "archived":
                    chapter["status"] = "archived"
                    changed = True
                if chapter.get("detail_level") != "archived":
                    chapter["detail_level"] = "archived"
                    changed = True
                chapter["updated_at"] = now_iso()
            updated.append(chapter)
        if changed:
            self.repositories.chapters.write_all(updated)

    def _find_archive(
        self,
        chapter_id: str,
        chapter_index: int | None,
        archives: list[ChapterArchiveRecord] | None = None,
    ) -> ChapterArchiveRecord | None:
        for archive in archives if archives is not None else self._read_archives():
            if archive.chapter_id == chapter_id:
                return archive
            if chapter_index is not None and archive.chapter_index == chapter_index:
                return archive
        return None

    def _build_decision(
        self,
        *,
        decision_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        return Decision(
            decision_id=f"decision_chapter_archive_{len(self._read_decision_dicts()) + 1:03d}",
            decision_type=decision_type,
            target_type="chapter_archive",
            target_id=target_id,
            user_input=self._safe_text(user_input, 500),
            created_at=now_iso(),
        )

    def _append_decision(self, decision: Decision) -> None:
        records = self._read_decision_dicts()
        records.append(model_to_dict(decision))
        self.store.write(self.decisions_file, records)

    def _read_decision_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        return [
            item
            for item in self.store.read_list(self.decisions_file)
            if isinstance(item, dict)
        ]

    def _next_archive_id(self) -> str:
        return f"chapter_archive_{len(self._read_archives()) + 1:03d}"

    def _mode_from_progress(self, completion_status: str) -> str:
        if completion_status == "final_complete":
            return "stable"
        if completion_status == "provisional_complete":
            return "provisional"
        return "blocked"

    def _preview_summary(
        self,
        *,
        chapter: Chapter,
        existing: ChapterArchiveRecord | None,
        candidate: ChapterArchiveRecord | None,
        report: ChapterArchiveValidationReport,
    ) -> str:
        if existing:
            return (
                f"Chapter {chapter.chapter_index} already has a "
                f"{existing.archive_status} archive: {existing.archive_id}."
            )
        if candidate:
            return candidate.summary
        if report.blocking_issues:
            return self._safe_text(report.blocking_issues[0].message, 300)
        return "Chapter archive preview is blocked."

    def _archive_summary(
        self,
        chapter: Chapter,
        scenes: list[Scene],
        completion_status: str,
    ) -> str:
        title = chapter.title or chapter.chapter_id
        statuses = ", ".join(
            f"{scene.scene_index}:{scene.status}" for scene in scenes[:8]
        )
        base = (
            f"Chapter {chapter.chapter_index} ({title}) reached "
            f"{completion_status} with scenes {statuses}."
        )
        if chapter.summary:
            base += f" Outcome anchor: {chapter.summary}"
        return self._safe_text(base, 700)

    def _chapter_goal_result(self, chapter: Chapter) -> str:
        values = [
            chapter.chapter_goal,
            *chapter.goals,
            self._current_chapter_brief_field("chapter_goal"),
        ]
        return self._safe_text(" / ".join(value for value in values if value), 600)

    def _reader_emotion_result(self) -> str:
        value = self._current_chapter_brief_field("reader_emotion_goal")
        if isinstance(value, list):
            return self._safe_text(" / ".join(str(item) for item in value), 300)
        return self._safe_text(value, 300)

    def _current_chapter_brief_field(self, field_name: str) -> Any:
        if not self.store.exists(self.chapter_plan_draft_file):
            return ""
        try:
            draft = self.store.read(self.chapter_plan_draft_file)
        except StorageError:
            return ""
        brief = draft.get("current_chapter_brief") if isinstance(draft, dict) else {}
        if not isinstance(brief, dict):
            return ""
        return brief.get(field_name) or ""

    def _scene_event_ids(self, scenes: list[Scene]) -> list[str]:
        values: list[Any] = []
        for scene in scenes:
            values.extend(scene.event_ids)
            for item in scene.memory_extraction.event_summary:
                if isinstance(item, dict):
                    values.append(item.get("event_id"))
        return self._unique_strings(values)

    def _scene_state_change_ids(self, scenes: list[Scene]) -> list[str]:
        values: list[Any] = []
        for scene in scenes:
            values.extend(scene.state_change_ids)
            for item in scene.memory_extraction.proposed_state_changes:
                if isinstance(item, dict):
                    values.append(item.get("state_change_id") or item.get("change_id"))
            for item in scene.memory_extraction.relationship_changes:
                if isinstance(item, dict):
                    values.append(item.get("state_change_id") or item.get("change_id"))
        return self._unique_strings(values)

    def _scene_memory_ids(self, scenes: list[Scene]) -> list[str]:
        values: list[Any] = []
        for scene in scenes:
            values.extend(scene.input_memory_ids)
            values.extend(scene.depends_on_provisional_memory_ids)
            for item in scene.memory_extraction.memory_records:
                if isinstance(item, dict):
                    values.append(item.get("memory_id"))
        return self._unique_strings(values)

    def _events_by_ids(self, event_ids: list[str]) -> list[dict[str, Any]]:
        wanted = set(event_ids)
        return [
            self._safe_event(event)
            for event in self.repositories.events.list_all()
            if event.get("event_id") in wanted
        ][:12]

    def _state_changes_by_ids(self, state_change_ids: list[str]) -> list[dict[str, Any]]:
        wanted = set(state_change_ids)
        return [
            change
            for change in self.repositories.state_changes.list_all()
            if change.get("state_change_id") in wanted
        ][:12]

    def _memories_for_archive(
        self,
        chapter: Chapter,
        scenes: list[Scene],
        memory_ids: list[str],
    ) -> list[dict[str, Any]]:
        scene_ids = {scene.scene_id for scene in scenes}
        wanted = set(memory_ids)
        memories = []
        for memory in self.repositories.memory.list_all():
            if (
                memory.get("memory_id") in wanted
                or memory.get("chapter_id") == chapter.chapter_id
                or memory.get("scene_id") in scene_ids
            ):
                memories.append(self._safe_memory(memory))
        return memories[:14]

    def _continuity_issues_for_chapter(
        self,
        chapter: Chapter,
        scenes: list[Scene],
    ) -> list[dict[str, Any]]:
        scene_ids = {scene.scene_id for scene in scenes}
        return [
            issue
            for issue in self.repositories.continuity_issues.list_all()
            if issue.get("chapter_id") == chapter.chapter_id
            or issue.get("scene_id") in scene_ids
        ]

    def _narrative_debts_for_chapter(
        self,
        chapter: Chapter,
        scenes: list[Scene],
    ) -> list[dict[str, Any]]:
        scene_ids = {scene.scene_id for scene in scenes}
        return [
            debt
            for debt in self.repositories.narrative_debts.list_all()
            if debt.get("chapter_id") == chapter.chapter_id
            or debt.get("scene_id") in scene_ids
            or debt.get("source_scene_id") in scene_ids
        ][:12]

    def _safe_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event.get("event_id", ""),
            "summary": self._safe_text(event.get("summary"), 260),
            "result": self._safe_text(event.get("result"), 220),
            "status": event.get("status", ""),
        }

    def _safe_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        return {
            "memory_id": memory.get("memory_id", ""),
            "summary": self._safe_text(memory.get("summary"), 260),
            "status": memory.get("status", ""),
            "truth_status": memory.get("truth_status", ""),
            "chapter_id": memory.get("chapter_id", ""),
            "scene_id": memory.get("scene_id", ""),
        }

    def _change_refs(self, state_changes: list[dict[str, Any]], *, target_type: str) -> list[str]:
        result = []
        for change in state_changes:
            if str(change.get("target_type") or "") != target_type:
                continue
            result.append(
                self._safe_text(
                    f"{change.get('state_change_id', '')}: {change.get('target_id', '')}",
                    220,
                )
            )
        return result[:8]

    def _open_thread_summaries(
        self,
        continuity_issues: list[dict[str, Any]],
        narrative_debts: list[dict[str, Any]],
    ) -> list[str]:
        values = [
            issue.get("user_visible_message")
            or issue.get("technical_summary")
            or issue.get("issue_id")
            for issue in continuity_issues
            if issue.get("status") == "open"
        ]
        values.extend(
            debt.get("summary") or debt.get("narrative_debt_id")
            for debt in narrative_debts
            if debt.get("status") in {"active", "expired", "intentionally_open"}
        )
        return [self._safe_text(value, 240) for value in values if value][:10]

    def _next_seed_summaries(self, narrative_debts: list[dict[str, Any]]) -> list[str]:
        return [
            self._safe_text(debt.get("summary") or debt.get("narrative_debt_id"), 240)
            for debt in narrative_debts
            if debt.get("status") in {"active", "intentionally_open"}
        ][:8]

    def _provisional_memory_ids(
        self,
        scenes: list[Scene],
        memories: list[dict[str, Any]],
    ) -> list[str]:
        values: list[Any] = []
        for scene in scenes:
            values.extend(scene.depends_on_provisional_memory_ids)
        values.extend(
            memory.get("memory_id")
            for memory in memories
            if memory.get("status") == "provisional"
        )
        return self._unique_strings(values)

    def _dependent_scene_ids(self, scenes: list[Scene]) -> list[str]:
        values: list[Any] = []
        for scene in scenes:
            values.extend(scene.depends_on_provisional_scene_ids)
        return self._unique_strings(values)

    def _is_blocking_continuity_issue(self, issue: dict[str, Any]) -> bool:
        return (
            str(issue.get("status") or "") == "open"
            and (
                str(issue.get("severity") or "") == "blocking"
                or str(issue.get("severity") or "") == "requires_user_confirmation"
                or bool(issue.get("blocks_final_confirmation"))
                or bool(issue.get("requires_explicit_acceptance"))
            )
        )

    def _issue(
        self,
        code: str,
        message: str,
        severity: str,
        ref_type: str = "",
        ref_id: str = "",
    ) -> ChapterArchiveValidationIssue:
        return ChapterArchiveValidationIssue(
            code=code,
            message=self._safe_text(message, 360),
            severity=severity,
            ref_type=ref_type,
            ref_id=ref_id,
        )

    def _dedupe_issues(
        self,
        issues: list[ChapterArchiveValidationIssue],
    ) -> list[ChapterArchiveValidationIssue]:
        result: list[ChapterArchiveValidationIssue] = []
        seen: set[tuple[str, str, str]] = set()
        for issue in issues:
            key = (issue.code, issue.ref_type, issue.ref_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(issue)
        return result

    def _chapter_index_from_id(self, chapter_id: str) -> int | None:
        suffix = chapter_id.rsplit("_", 1)[-1]
        if suffix.isdigit():
            value = int(suffix)
            return value if value > 0 else None
        return None

    def _unique_strings(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def _has_unsafe_text(self, text: str) -> bool:
        lowered = text.casefold()
        return any(marker in lowered for marker in UNSAFE_TEXT_MARKERS) or any(
            pattern.search(text) for pattern in UNSAFE_TEXT_PATTERNS
        )

    def _assert_archive_payload_safe(self, payload: Any) -> None:
        unsafe_paths = self._unsafe_payload_paths(payload)
        if unsafe_paths:
            shown = ", ".join(unsafe_paths[:5])
            raise StorageError(
                "CHAPTER_ARCHIVE_UNSAFE_PAYLOAD_BLOCKED: Archive payload contains unsafe raw, hidden reasoning, or secret-like content at "
                f"{shown}."
            )

    def _unsafe_payload_paths(self, value: Any, path: str = "$") -> list[str]:
        if isinstance(value, str):
            return [path] if self._has_unsafe_text(value) else []
        if isinstance(value, dict):
            paths: list[str] = []
            for key, item in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}"
                if self._has_unsafe_text(key_text):
                    paths.append(child_path)
                paths.extend(self._unsafe_payload_paths(item, child_path))
            return paths
        if isinstance(value, list):
            paths: list[str] = []
            for index, item in enumerate(value):
                paths.extend(self._unsafe_payload_paths(item, f"{path}[{index}]"))
            return paths
        return []

    def _safe_text(self, value: Any, limit: int = 500) -> str:
        text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
        if not text:
            return ""
        if self._has_unsafe_text(text):
            return "[redacted]"
        if len(text) > limit:
            return text[: max(0, limit - 3)].rstrip() + "..."
        return text
