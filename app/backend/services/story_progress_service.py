import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.chapter_archive import ChapterArchiveRecord, ChapterOutcomeSummary
from app.backend.models.decision import Decision
from app.backend.models.framework_package import FrameworkPackage
from app.backend.models.story_progress import (
    ConfirmNextChapterRequest,
    ConfirmNextChapterResponse,
    ConfirmStoryDraftCompleteRequest,
    ConfirmStoryDraftCompleteResponse,
    ChapterTransitionRecord,
    NextChapterPreparationRecord,
    NextChapterPreviewResponse,
    PrepareNextChapterRequest,
    PrepareNextChapterResponse,
    StoryProgress,
    StoryProgressIssue,
)
from app.backend.services.chapter_archive_service import ChapterArchiveService
from app.backend.services.chapter_framework_builder_service import (
    ChapterFrameworkBuilderService,
)
from app.backend.services.chapter_memory_service import ChapterMemoryService
from app.backend.services.chapter_plan_service import ChapterPlanService, model_to_dict
from app.backend.services.scene_gate_readiness_service import SceneGateReadinessService
from app.backend.services.scene_memory_service import SceneMemoryService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
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


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class StoryProgressService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        chapter_archive_service: ChapterArchiveService | None = None,
        framework_builder: ChapterFrameworkBuilderService | None = None,
        chapter_plan_service: ChapterPlanService | None = None,
        chapter_memory_service: ChapterMemoryService | None = None,
        scene_memory_service: SceneMemoryService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.story_progress_file = self.data_dir / "story_progress.json"
        self.transitions_file = self.data_dir / "chapter_transitions.json"
        self.preparations_file = self.data_dir / "next_chapter_preparations.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.project_file = self.data_dir / "project.json"
        self.chapter_archive_service = chapter_archive_service or ChapterArchiveService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_builder = framework_builder or ChapterFrameworkBuilderService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapter_plan_service = chapter_plan_service or ChapterPlanService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapter_memory_service = chapter_memory_service or ChapterMemoryService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_memory_service = scene_memory_service or SceneMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            chapter_memory_service=self.chapter_memory_service,
        )

    def get_current_story_progress(self) -> StoryProgress:
        stored = self._try_read_story_progress()
        if stored is not None:
            if self._stored_progress_is_stale(stored):
                return self._derive_story_progress()
            return stored
        return self._derive_story_progress()

    def preview_next_chapter(self) -> NextChapterPreviewResponse:
        progress = self.get_current_story_progress()
        archive = self._archive_for_chapter(progress.current_chapter_index)
        if archive is None:
            issue = self._issue(
                "STORY_PROGRESS_CURRENT_ARCHIVE_REQUIRED",
                "Archive the current chapter before previewing the next chapter.",
                "blocking",
                "chapter",
                progress.current_chapter_id,
            )
            return NextChapterPreviewResponse(
                success=False,
                story_progress=progress,
                next_chapter_id="",
                next_chapter_index=0,
                blocking_issues=[issue],
            )

        if not progress.has_next_chapter:
            complete_progress = self._progress_from_archive(
                archive,
                status="current_chapter_archived",
                next_action="story_draft_complete",
            )
            return NextChapterPreviewResponse(
                success=True,
                can_prepare_next_chapter=False,
                can_complete_story_draft=True,
                story_progress=complete_progress,
                current_archive=archive,
                next_chapter_id="",
                next_chapter_index=0,
            )

        warnings = self._archive_warnings(archive)
        transition = self._build_transition(
            archive=archive,
            next_chapter_id=progress.next_chapter_id,
            next_chapter_index=progress.next_chapter_index,
            transition_status="previewed",
            warnings=warnings,
            source_decision_id="",
        )
        preview_progress = self._progress_from_archive(
            archive,
            status="next_chapter_previewed",
            next_action="prepare_next_chapter",
            transition_id=transition.transition_id,
            next_chapter_id=progress.next_chapter_id,
            next_chapter_index=progress.next_chapter_index,
            warnings=warnings,
        )
        return NextChapterPreviewResponse(
            success=True,
            can_prepare_next_chapter=True,
            can_complete_story_draft=False,
            story_progress=preview_progress,
            current_archive=archive,
            transition_preview=transition,
            next_chapter_id=progress.next_chapter_id,
            next_chapter_index=progress.next_chapter_index,
            warnings=warnings,
        )

    def prepare_next_chapter(
        self,
        request: PrepareNextChapterRequest,
    ) -> PrepareNextChapterResponse:
        preview = self.preview_next_chapter()
        if preview.blocking_issues or preview.current_archive is None:
            raise StorageError("STORY_PROGRESS_CURRENT_ARCHIVE_REQUIRED")
        if preview.can_complete_story_draft:
            raise StorageError(
                "STORY_PROGRESS_NO_NEXT_CHAPTER: Current archived chapter is the final chapter."
            )
        archive = preview.current_archive
        if archive.archive_status == "provisional" and not request.acknowledge_provisional_archive:
            raise StorageError(
                "STORY_PROGRESS_PROVISIONAL_ARCHIVE_ACK_REQUIRED: Provisional archive requires explicit acknowledgement before next chapter preparation."
            )
        self._assert_prepare_sources_safe(
            archive=archive,
            preview=preview,
            request=request,
        )

        existing = self._active_preparation_for_next(preview.next_chapter_index)
        if existing is not None and not request.force_rebuild:
            transition = self._transition_by_id(existing.transition_id)
            if transition is None:
                raise StorageError(
                    "STORY_PROGRESS_NEXT_CHAPTER_PREPARATION_INVALID: Existing preparation has no transition."
                )
            warning = self._issue(
                "existing_preparation_returned",
                "Existing next chapter preparation was returned without overwriting it.",
                "warning",
                "next_chapter_preparation",
                existing.preparation_id,
            )
            progress = self._progress_after_prepare(
                archive=archive,
                transition=transition,
                preparation=existing,
                warnings=[*transition.warnings, warning],
            )
            return PrepareNextChapterResponse(
                story_progress=progress,
                transition=transition,
                preparation=existing,
                warnings=[warning],
                returned_existing=True,
            )

        next_chapter_id = preview.next_chapter_id
        next_chapter_index = preview.next_chapter_index
        self._ensure_next_assignment(next_chapter_index)
        previous_summary = self._archive_outcome_summary(archive)
        clean_intent = self._safe_text(request.latest_user_intent_summary, 600)
        clean_story_goal = self._safe_text(
            request.story_goal
            or f"Prepare chapter {next_chapter_index} after archive {archive.archive_id}.",
            600,
        )
        framework_result = self.framework_builder.build_for_current_chapter(
            chapter_id=next_chapter_id,
            chapter_index=next_chapter_index,
            latest_user_intent_summary=clean_intent,
            previous_chapter_archive_id=archive.archive_id,
            previous_chapter_archive_status=archive.archive_status,
            previous_chapter_outcome_summary=previous_summary,
            force_rebuild=request.force_rebuild,
        )
        chapter_count = self._chapter_count()
        plan_response = self.chapter_plan_service.generate_chapter_plan(
            story_goal=clean_story_goal,
            chapter_count=chapter_count,
            current_chapter_index=next_chapter_index,
        )
        draft = plan_response.draft
        if draft is None:
            raise StorageError(
                "STORY_PROGRESS_NEXT_CHAPTER_PLAN_DRAFT_MISSING: Chapter plan draft was not generated."
            )
        if request.scene_count_proposal is not None:
            plan_response = self.chapter_plan_service.set_scene_count(
                chapter_index=next_chapter_index,
                scene_count=request.scene_count_proposal,
            )
            draft = plan_response.draft
            if draft is None:
                raise StorageError(
                    "STORY_PROGRESS_NEXT_CHAPTER_PLAN_DRAFT_MISSING: Chapter plan draft was not updated."
                )

        chapter_pack = self.chapter_memory_service.build_current_chapter_pack(
            next_chapter_id,
            force_refresh=True,
        )
        brief = draft.current_chapter_brief
        first_scene_pack = self.scene_memory_service.build_scene_pack(
            chapter_id=next_chapter_id,
            scene_index=1,
            scene_goal=brief.chapter_goal,
            active_character_ids=brief.participating_character_ids,
            include_provisional=archive.archive_status == "provisional",
            force_refresh=True,
        )

        transition_id = self._next_transition_id()
        preparation_id = self._next_preparation_id()
        decision = self._build_decision(
            decision_type="prepare",
            target_type="next_chapter_preparation",
            target_id=preparation_id,
            user_input=clean_intent
            or f"Prepare chapter {next_chapter_index} from archive {archive.archive_id}.",
        )
        warnings = [
            *preview.warnings,
            *[
                self._issue(
                    warning.code,
                    warning.message,
                    warning.severity,
                    "chapter_framework",
                    warning.ref_id,
                )
                for warning in framework_result.warnings
            ],
        ]
        transition = self._build_transition(
            archive=archive,
            next_chapter_id=next_chapter_id,
            next_chapter_index=next_chapter_index,
            transition_status="awaiting_confirmation",
            warnings=warnings,
            source_decision_id=decision.decision_id,
            transition_id=transition_id,
        )
        preparation = NextChapterPreparationRecord(
            preparation_id=preparation_id,
            project_id=self._project_id(),
            transition_id=transition.transition_id,
            next_chapter_id=next_chapter_id,
            next_chapter_index=next_chapter_index,
            previous_chapter_id=archive.chapter_id,
            previous_chapter_index=archive.chapter_index,
            previous_archive_id=archive.archive_id,
            previous_archive_status=archive.archive_status,
            previous_outcome_summary=previous_summary,
            chapter_framework_id=(
                framework_result.chapter_framework.chapter_framework_id
                if framework_result.chapter_framework
                else ""
            ),
            chapter_framework_build_context_id=(
                framework_result.build_context.build_context_id
                if framework_result.build_context
                else ""
            ),
            chapter_plan_draft_id=draft.draft_id,
            chapter_memory_pack_id=chapter_pack.chapter_memory_pack_id,
            first_scene_memory_pack_id=first_scene_pack.scene_memory_pack_id,
            scene_count_proposal=(
                request.scene_count_proposal
                or brief.user_selected_scene_count
                or brief.recommended_scene_count
                or 0
            ),
            scene_count_confirmed=False,
            preparation_status="awaiting_confirmation",
            warnings=warnings,
            requires_user_review=archive.archive_status == "provisional" or bool(warnings),
            source_decision_id=decision.decision_id,
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        progress = self._progress_after_prepare(
            archive=archive,
            transition=transition,
            preparation=preparation,
            warnings=warnings,
        )
        self._assert_m4_payloads_safe(
            story_progress=progress,
            transitions=[*self._read_transitions(), transition],
            preparations=[*self._read_preparations(), preparation],
            decision=decision,
        )
        self._write_transitions([*self._read_transitions(), transition])
        self._write_preparations([*self._read_preparations(), preparation])
        self._write_story_progress(progress)
        self._append_decision(decision)
        return PrepareNextChapterResponse(
            story_progress=progress,
            transition=transition,
            preparation=preparation,
            warnings=warnings,
        )

    def confirm_next_chapter(
        self,
        request: ConfirmNextChapterRequest,
    ) -> ConfirmNextChapterResponse:
        preparation = self._preparation_for_confirm(request.preparation_id)
        transition = self._transition_by_id(preparation.transition_id)
        if transition is None:
            raise StorageError(
                "STORY_PROGRESS_NEXT_CHAPTER_PREPARATION_REQUIRED: Transition is missing."
            )
        self._assert_confirm_sources_safe(
            preparation=preparation,
            transition=transition,
            request=request,
        )
        if not request.confirm_chapter_plan:
            raise StorageError(
                "STORY_PROGRESS_CHAPTER_PLAN_CONFIRMATION_REQUIRED: Next chapter plan and scene count must be confirmed before activation."
            )
        if request.scene_count is not None:
            self.chapter_plan_service.set_scene_count(
                chapter_index=preparation.next_chapter_index,
                scene_count=request.scene_count,
            )
            preparation.scene_count_proposal = request.scene_count
        plan_response = self.chapter_plan_service.confirm_chapter_plan(
            "Confirm next chapter plan and scene count for story progress transition."
        )
        if plan_response.draft is None or plan_response.draft.status != "confirmed":
            raise StorageError(
                "STORY_PROGRESS_CHAPTER_PLAN_CONFIRMATION_REQUIRED: Chapter plan confirmation did not produce a confirmed draft."
            )
        if plan_response.draft.current_chapter_index != preparation.next_chapter_index:
            raise StorageError(
                "STORY_PROGRESS_CHAPTER_PLAN_CONFIRMATION_REQUIRED: Confirmed draft must match the next chapter index."
            )
        decision = self._build_decision(
            decision_type="confirm",
            target_type="next_chapter_preparation",
            target_id=preparation.preparation_id,
            user_input=(
                f"Confirm chapter {preparation.next_chapter_index} as current active chapter."
            ),
        )
        timestamp = now_iso()
        transition.transition_status = "activated"
        transition.source_decision_id = decision.decision_id
        transition.updated_at = timestamp
        preparation.preparation_status = "activated"
        preparation.scene_count_confirmed = True
        preparation.source_decision_id = decision.decision_id
        preparation.updated_at = timestamp
        self._mark_chapters_after_activation(preparation)
        progress = self._progress_after_activation(
            preparation=preparation,
            transition=transition,
            decision_id=decision.decision_id,
        )
        transitions = self._replace_transition(transition)
        preparations = self._replace_preparation(preparation)
        self._assert_m4_payloads_safe(
            story_progress=progress,
            transitions=transitions,
            preparations=preparations,
            decision=decision,
        )
        self._write_transitions(transitions)
        self._write_preparations(preparations)
        self._write_story_progress(progress)
        self._append_decision(decision)
        return ConfirmNextChapterResponse(
            story_progress=progress,
            transition=transition,
            preparation=preparation,
            source_decision_id=decision.decision_id,
            warnings=preparation.warnings,
        )

    def confirm_story_draft_complete(
        self,
        request: ConfirmStoryDraftCompleteRequest,
    ) -> ConfirmStoryDraftCompleteResponse:
        if not request.acknowledge_completion:
            raise StorageError(
                "STORY_PROGRESS_COMPLETION_ACK_REQUIRED: Story draft completion requires acknowledgement."
            )
        progress = self.get_current_story_progress()
        archive = self._archive_for_chapter(progress.current_chapter_index)
        if archive is None:
            raise StorageError("STORY_PROGRESS_CURRENT_ARCHIVE_REQUIRED")
        if progress.has_next_chapter:
            raise StorageError(
                "STORY_PROGRESS_HAS_NEXT_CHAPTER: Prepare the next chapter instead of completing the story draft."
            )
        story_release_scene_ids = self._story_completion_scene_ids(current_archive=archive)
        SceneGateReadinessService(
            store=self.store,
            data_dir=self.data_dir,
        ).require_scenes_safe_to_release(
            story_release_scene_ids,
            boundary_code="STORY_PROGRESS_GATE_READINESS_BLOCKED",
            mode="story_draft_complete",
        )
        decision = self._build_decision(
            decision_type="confirm",
            target_type="story_progress",
            target_id="story_draft_complete",
            user_input="Confirm story draft complete after final chapter archive.",
        )
        complete = self._progress_from_archive(
            archive,
            status="story_draft_complete",
            next_action="story_draft_complete",
            source_decision_ids=[decision.decision_id],
        )
        self._assert_m4_payloads_safe(
            story_progress=complete,
            transitions=self._read_transitions(),
            preparations=self._read_preparations(),
            decision=decision,
        )
        self._write_story_progress(complete)
        self._append_decision(decision)
        self._update_project_step("story_draft_complete", "story_draft_complete")
        return ConfirmStoryDraftCompleteResponse(
            story_progress=complete,
            source_decision_id=decision.decision_id,
        )

    def _derive_story_progress(self) -> StoryProgress:
        chapters = self._read_chapters()
        archives = self._read_archives()
        chapter_count = self._chapter_count(chapters=chapters)
        current = self._select_current_chapter(chapters, archives)
        current_index = current.chapter_index if current else (archives[-1].chapter_index if archives else 1)
        if current_index < 1:
            current_index = 1
        current_id = (
            current.chapter_id
            if current and current.chapter_index >= 1
            else self._chapter_id(current_index)
        )
        archive = self._archive_for_chapter(current_index, archives)
        archived_indexes = sorted({archive.chapter_index for archive in archives})
        archived_ids = [archive.chapter_id for archive in sorted(archives, key=lambda item: item.chapter_index)]
        active_preparation = self._active_preparation_for_next(current_index + 1)
        has_next = bool(chapter_count and current_index < chapter_count)
        next_index = current_index + 1 if has_next else 0
        next_id = self._chapter_id(next_index) if has_next else ""
        status = "current_chapter_active"
        next_action = "continue_current_chapter"
        transition_id = ""
        preparation_id = ""
        warnings: list[StoryProgressIssue] = []
        if archive is None:
            completion_status = self._current_chapter_completion_status(current_id)
            if completion_status == "final_complete":
                next_action = "preview_chapter_archive"
            elif completion_status == "provisional_complete":
                next_action = "review_provisional_archive"
        if archive is not None:
            status = "current_chapter_archived"
            next_action = "preview_next_chapter" if has_next else "story_draft_complete"
            warnings = self._archive_warnings(archive)
        if active_preparation is not None:
            status = "next_chapter_ready_for_confirmation"
            next_action = "confirm_next_chapter"
            preparation_id = active_preparation.preparation_id
            transition_id = active_preparation.transition_id
            warnings = active_preparation.warnings
        timestamp = now_iso()
        return StoryProgress(
            project_id=self._project_id(),
            current_chapter_id=current_id,
            current_chapter_index=current_index,
            chapter_count=chapter_count,
            archived_chapter_ids=archived_ids,
            archived_chapter_indexes=archived_indexes,
            active_transition_id=transition_id,
            active_preparation_id=preparation_id,
            next_chapter_id=next_id,
            next_chapter_index=next_index,
            has_next_chapter=has_next,
            story_progress_status=status,
            next_recommended_action=next_action,
            warnings=warnings,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _progress_from_archive(
        self,
        archive: ChapterArchiveRecord,
        *,
        status: str,
        next_action: str,
        transition_id: str = "",
        preparation_id: str = "",
        next_chapter_id: str = "",
        next_chapter_index: int = 0,
        warnings: list[StoryProgressIssue] | None = None,
        source_decision_ids: list[str] | None = None,
    ) -> StoryProgress:
        chapter_count = self._chapter_count()
        has_next = bool(chapter_count and archive.chapter_index < chapter_count)
        resolved_next_index = next_chapter_index or (archive.chapter_index + 1 if has_next else 0)
        resolved_next_id = next_chapter_id or (self._chapter_id(resolved_next_index) if has_next else "")
        timestamp = now_iso()
        archives = self._read_archives()
        return StoryProgress(
            project_id=self._project_id(),
            story_progress_status=status,
            current_chapter_id=archive.chapter_id,
            current_chapter_index=archive.chapter_index,
            chapter_count=chapter_count,
            archived_chapter_ids=[
                item.chapter_id for item in sorted(archives, key=lambda value: value.chapter_index)
            ],
            archived_chapter_indexes=sorted({item.chapter_index for item in archives}),
            active_transition_id=transition_id,
            active_preparation_id=preparation_id,
            next_chapter_id=resolved_next_id,
            next_chapter_index=resolved_next_index if has_next else 0,
            has_next_chapter=has_next,
            next_recommended_action=next_action,
            warnings=warnings or [],
            source_decision_ids=source_decision_ids or [],
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _progress_after_prepare(
        self,
        *,
        archive: ChapterArchiveRecord,
        transition: ChapterTransitionRecord,
        preparation: NextChapterPreparationRecord,
        warnings: list[StoryProgressIssue],
    ) -> StoryProgress:
        return self._progress_from_archive(
            archive,
            status="next_chapter_ready_for_confirmation",
            next_action="confirm_next_chapter",
            transition_id=transition.transition_id,
            preparation_id=preparation.preparation_id,
            next_chapter_id=preparation.next_chapter_id,
            next_chapter_index=preparation.next_chapter_index,
            warnings=warnings,
            source_decision_ids=[preparation.source_decision_id] if preparation.source_decision_id else [],
        )

    def _progress_after_activation(
        self,
        *,
        preparation: NextChapterPreparationRecord,
        transition: ChapterTransitionRecord,
        decision_id: str,
    ) -> StoryProgress:
        archived_ids = sorted(
            {
                *[
                    archive.chapter_id
                    for archive in self._read_archives()
                ],
                preparation.previous_chapter_id,
            }
        )
        archived_indexes = sorted(
            {
                *[
                    archive.chapter_index
                    for archive in self._read_archives()
                ],
                preparation.previous_chapter_index,
            }
        )
        chapter_count = self._chapter_count()
        has_next = preparation.next_chapter_index < chapter_count
        timestamp = now_iso()
        return StoryProgress(
            project_id=self._project_id(),
            story_progress_status="next_chapter_active",
            current_chapter_id=preparation.next_chapter_id,
            current_chapter_index=preparation.next_chapter_index,
            chapter_count=chapter_count,
            archived_chapter_ids=archived_ids,
            archived_chapter_indexes=archived_indexes,
            active_transition_id=transition.transition_id,
            active_preparation_id=preparation.preparation_id,
            next_chapter_id=self._chapter_id(preparation.next_chapter_index + 1) if has_next else "",
            next_chapter_index=preparation.next_chapter_index + 1 if has_next else 0,
            has_next_chapter=has_next,
            next_recommended_action="generate_first_scene",
            warnings=preparation.warnings,
            source_decision_ids=[decision_id],
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _build_transition(
        self,
        *,
        archive: ChapterArchiveRecord,
        next_chapter_id: str,
        next_chapter_index: int,
        transition_status: str,
        warnings: list[StoryProgressIssue],
        source_decision_id: str,
        transition_id: str | None = None,
    ) -> ChapterTransitionRecord:
        timestamp = now_iso()
        assignment = self._assignment_for_index(next_chapter_index)
        return ChapterTransitionRecord(
            transition_id=transition_id
            or f"chapter_transition_preview_{archive.chapter_index:03d}_to_{next_chapter_index:03d}",
            project_id=self._project_id(),
            from_chapter_id=archive.chapter_id,
            from_chapter_index=archive.chapter_index,
            from_archive_id=archive.archive_id,
            from_archive_status=archive.archive_status,
            to_chapter_id=next_chapter_id,
            to_chapter_index=next_chapter_index,
            linked_macro_component_ids=(
                list(assignment.linked_macro_component_ids) if assignment else []
            ),
            transition_status=transition_status,
            warnings=warnings,
            requires_user_review=archive.archive_status == "provisional" or bool(warnings),
            source_decision_id=source_decision_id,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _archive_outcome_summary(self, archive: ChapterArchiveRecord) -> str:
        outcome: ChapterOutcomeSummary = archive.outcome_summary
        values = [
            archive.summary,
            outcome.user_visible_summary,
            outcome.chapter_goal_result,
            outcome.conflict_state,
            " / ".join(outcome.open_threads[:5]),
            " / ".join(outcome.next_chapter_seeds[:5]),
        ]
        return self._safe_text(" ".join(value for value in values if value), 900)

    def _archive_warnings(self, archive: ChapterArchiveRecord) -> list[StoryProgressIssue]:
        warnings: list[StoryProgressIssue] = []
        if archive.archive_status == "provisional":
            warnings.append(
                self._issue(
                    "provisional_archive_requires_review",
                    "Previous chapter archive is provisional; next chapter preparation requires explicit acknowledgement and keeps provisional dependency warnings visible.",
                    "warning",
                    "chapter_archive",
                    archive.archive_id,
                )
            )
        return warnings

    def _ensure_next_assignment(self, next_chapter_index: int) -> None:
        assignment = self._assignment_for_index(next_chapter_index)
        if assignment is None or assignment.status != "confirmed":
            raise StorageError(
                "STORY_PROGRESS_NEXT_CHAPTER_NOT_ASSIGNED: Confirmed framework mapping must cover the next chapter."
            )

    def _assignment_for_index(self, chapter_index: int):
        package = self._read_framework_package()
        for assignment in package.chapter_macro_assignments:
            if assignment.chapter_index == chapter_index:
                return assignment
        return None

    def _chapter_count(self, chapters: list[Chapter] | None = None) -> int:
        try:
            package = self._read_framework_package()
        except StorageError:
            package = None
        if package and package.chapter_macro_assignments:
            return max(assignment.chapter_index for assignment in package.chapter_macro_assignments)
        active_chapters = chapters if chapters is not None else self._read_chapters()
        return max((chapter.chapter_index for chapter in active_chapters), default=0)

    def _select_current_chapter(
        self,
        chapters: list[Chapter],
        archives: list[ChapterArchiveRecord],
    ) -> Chapter | None:
        active = (
            next((chapter for chapter in chapters if chapter.status == "active"), None)
            or next((chapter for chapter in chapters if chapter.detail_level == "current_chapter_brief"), None)
        )
        if active:
            return active
        if archives:
            archived_index = sorted(archives, key=lambda item: item.chapter_index)[-1].chapter_index
            return next((chapter for chapter in chapters if chapter.chapter_index == archived_index), None)
        return chapters[0] if chapters else None

    def _stored_progress_is_stale(self, progress: StoryProgress) -> bool:
        if progress.project_id != self._project_id():
            return True
        if progress.current_chapter_index < 1:
            return True
        if progress.story_progress_status in {
            "current_chapter_active",
            "next_chapter_active",
        }:
            if self._archive_for_chapter(progress.current_chapter_index) is not None:
                return True
            completion_status = self._current_chapter_completion_status(
                progress.current_chapter_id
            )
            if completion_status in {"final_complete", "provisional_complete"}:
                return True
        return False

    def _current_chapter_completion_status(self, chapter_id: str) -> str:
        if not chapter_id:
            return ""
        try:
            progress = self.chapter_archive_service.scene_progress_service.get_progress(
                chapter_id=chapter_id
            )
        except Exception:
            return ""
        return str(progress.completion_status or "")

    def _mark_chapters_after_activation(
        self,
        preparation: NextChapterPreparationRecord,
    ) -> None:
        chapters = self._read_chapters()
        timestamp = now_iso()
        scene_ids_by_chapter = self._official_scene_ids_by_chapter()
        updated: list[Chapter] = []
        for chapter in chapters:
            scene_ids = scene_ids_by_chapter.get(chapter.chapter_id, [])
            if scene_ids:
                chapter.scene_ids = scene_ids
                chapter.scene_count = max(int(chapter.scene_count or 0), len(scene_ids))
            if chapter.chapter_index == preparation.previous_chapter_index:
                chapter.status = "archived"
                chapter.detail_level = "archived"
                chapter.updated_at = timestamp
            elif chapter.chapter_index == preparation.next_chapter_index:
                chapter.status = "active"
                chapter.detail_level = "current_chapter_brief"
                chapter.chapter_framework_id = preparation.chapter_framework_id
                if preparation.scene_count_proposal:
                    chapter.scene_count = preparation.scene_count_proposal
                chapter.updated_at = timestamp
            elif chapter.chapter_index < preparation.next_chapter_index:
                chapter.status = "archived"
                chapter.detail_level = "archived"
                chapter.updated_at = timestamp
            else:
                chapter.status = "planned"
                chapter.detail_level = "light"
                chapter.updated_at = timestamp
            updated.append(chapter)
        self.store.write(self.chapters_file, [model_to_dict(chapter) for chapter in updated])

    def _official_scene_ids_by_chapter(self) -> dict[str, list[str]]:
        scene_ids_by_chapter: dict[str, list[tuple[int, str]]] = {}
        for archive in self._read_archives():
            ids = list(archive.scene_ids or archive.confirmed_scene_ids or [])
            if ids:
                scene_ids_by_chapter[archive.chapter_id] = [
                    (index + 1, scene_id) for index, scene_id in enumerate(ids)
                ]

        scenes_file = self.data_dir / "scenes.json"
        if self.store.exists(scenes_file):
            for item in self.store.read_list(scenes_file):
                if not isinstance(item, dict):
                    continue
                chapter_id = str(item.get("chapter_id") or "")
                scene_id = str(item.get("scene_id") or "")
                status = str(item.get("status") or "").lower()
                if not chapter_id or not scene_id:
                    continue
                if status not in {"confirmed", "committed", "revised", "temporary_confirmed"}:
                    continue
                try:
                    scene_index = int(item.get("scene_index") or 0)
                except (TypeError, ValueError):
                    scene_index = 0
                current = scene_ids_by_chapter.setdefault(chapter_id, [])
                if scene_id not in {existing_id for _, existing_id in current}:
                    current.append((scene_index, scene_id))

        return {
            chapter_id: [
                scene_id
                for _, scene_id in sorted(values, key=lambda pair: (pair[0] <= 0, pair[0], pair[1]))
            ]
            for chapter_id, values in scene_ids_by_chapter.items()
        }

    def _story_completion_scene_ids(
        self,
        *,
        current_archive: ChapterArchiveRecord,
    ) -> list[str]:
        values: list[str] = []
        archives = self._read_archives()
        for archive in archives:
            if archive.archive_status != "stable":
                continue
            values.extend(archive.confirmed_scene_ids or archive.scene_ids or [])
        values.extend(current_archive.confirmed_scene_ids or current_archive.scene_ids or [])

        scenes_file = self.data_dir / "scenes.json"
        if self.store.exists(scenes_file):
            for item in self.store.read_list(scenes_file):
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").strip().lower()
                if status not in {"confirmed", "committed", "revised"}:
                    continue
                scene_id = str(item.get("scene_id") or "").strip()
                if scene_id:
                    values.append(scene_id)
        return self._unique_strings(values)

    def _project_id(self) -> str:
        if not self.store.exists(self.project_file):
            return LOCAL_PROJECT_ID
        try:
            payload = self.store.read(self.project_file)
        except StorageError:
            return LOCAL_PROJECT_ID
        if not isinstance(payload, dict):
            return LOCAL_PROJECT_ID
        project_id = str(payload.get("project_id") or "").strip()
        return project_id or LOCAL_PROJECT_ID

    def _try_read_story_progress(self) -> StoryProgress | None:
        if not self.store.exists(self.story_progress_file):
            return None
        try:
            return StoryProgress(**self.store.read(self.story_progress_file))
        except ValidationError as exc:
            raise StorageError("StoryProgress JSON schema is invalid.") from exc

    def _read_chapters(self) -> list[Chapter]:
        if not self.store.exists(self.chapters_file):
            return []
        chapters: list[Chapter] = []
        for raw in self.store.read_list(self.chapters_file):
            if not isinstance(raw, dict):
                continue
            try:
                chapters.append(Chapter(**raw))
            except ValidationError as exc:
                raise StorageError("Chapters JSON schema is invalid.") from exc
        return sorted(chapters, key=lambda item: item.chapter_index)

    def _read_archives(self) -> list[ChapterArchiveRecord]:
        return self.chapter_archive_service.list_archives()

    def _archive_for_chapter(
        self,
        chapter_index: int,
        archives: list[ChapterArchiveRecord] | None = None,
    ) -> ChapterArchiveRecord | None:
        for archive in archives if archives is not None else self._read_archives():
            if archive.chapter_index == chapter_index:
                return archive
        return None

    def _read_framework_package(self) -> FrameworkPackage:
        if not self.store.exists(self.framework_package_file):
            raise StorageError("FRAMEWORK_PACKAGE_MISSING")
        try:
            return FrameworkPackage(**self.store.read(self.framework_package_file))
        except ValidationError as exc:
            raise StorageError("FrameworkPackage JSON schema is invalid.") from exc

    def _read_transitions(self) -> list[ChapterTransitionRecord]:
        if not self.store.exists(self.transitions_file):
            return []
        try:
            return [
                ChapterTransitionRecord(**item)
                for item in self.store.read_list(self.transitions_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("ChapterTransitionRecord JSON schema is invalid.") from exc

    def _read_preparations(self) -> list[NextChapterPreparationRecord]:
        if not self.store.exists(self.preparations_file):
            return []
        try:
            return [
                NextChapterPreparationRecord(**item)
                for item in self.store.read_list(self.preparations_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("NextChapterPreparationRecord JSON schema is invalid.") from exc

    def _write_story_progress(self, progress: StoryProgress) -> None:
        payload = model_to_dict(progress)
        self._assert_payload_safe(payload, "story_progress")
        self.store.write(self.story_progress_file, payload)

    def _write_transitions(self, transitions: list[ChapterTransitionRecord]) -> None:
        payload = [model_to_dict(transition) for transition in transitions]
        self._assert_payload_safe(payload, "chapter_transitions")
        self.store.write(self.transitions_file, payload)

    def _write_preparations(self, preparations: list[NextChapterPreparationRecord]) -> None:
        payload = [model_to_dict(preparation) for preparation in preparations]
        self._assert_payload_safe(payload, "next_chapter_preparations")
        self.store.write(self.preparations_file, payload)

    def _read_decision_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        return [
            item for item in self.store.read_list(self.decisions_file)
            if isinstance(item, dict)
        ]

    def _append_decision(self, decision: Decision) -> None:
        payload = model_to_dict(decision)
        self._assert_payload_safe(payload, "decision")
        decisions = self._read_decision_dicts()
        decisions.append(payload)
        self.store.write(self.decisions_file, decisions)

    def _build_decision(
        self,
        *,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        return Decision(
            decision_id=f"decision_story_progress_{len(self._read_decision_dicts()) + 1:03d}",
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            user_input=self._safe_text(user_input, 600),
            created_at=now_iso(),
        )

    def _active_preparation_for_next(
        self,
        next_chapter_index: int,
    ) -> NextChapterPreparationRecord | None:
        candidates = [
            preparation
            for preparation in self._read_preparations()
            if preparation.next_chapter_index == next_chapter_index
            and preparation.preparation_status in {"prepared", "awaiting_confirmation"}
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.updated_at, reverse=True)[0]

    def _preparation_for_confirm(
        self,
        preparation_id: str,
    ) -> NextChapterPreparationRecord:
        preparations = self._read_preparations()
        if preparation_id:
            for preparation in preparations:
                if preparation.preparation_id == preparation_id:
                    return preparation
        active = [
            preparation
            for preparation in preparations
            if preparation.preparation_status in {"prepared", "awaiting_confirmation"}
        ]
        if active:
            return sorted(active, key=lambda item: item.updated_at, reverse=True)[0]
        raise StorageError(
            "STORY_PROGRESS_NEXT_CHAPTER_PREPARATION_REQUIRED: Prepare the next chapter before confirmation."
        )

    def _transition_by_id(self, transition_id: str) -> ChapterTransitionRecord | None:
        for transition in self._read_transitions():
            if transition.transition_id == transition_id:
                return transition
        return None

    def _replace_transition(
        self,
        transition: ChapterTransitionRecord,
    ) -> list[ChapterTransitionRecord]:
        records = [
            item for item in self._read_transitions()
            if item.transition_id != transition.transition_id
        ]
        records.append(transition)
        return sorted(records, key=lambda item: item.created_at)

    def _replace_preparation(
        self,
        preparation: NextChapterPreparationRecord,
    ) -> list[NextChapterPreparationRecord]:
        records = [
            item for item in self._read_preparations()
            if item.preparation_id != preparation.preparation_id
        ]
        records.append(preparation)
        return sorted(records, key=lambda item: item.created_at)

    def _next_transition_id(self) -> str:
        return f"chapter_transition_{len(self._read_transitions()) + 1:03d}"

    def _next_preparation_id(self) -> str:
        return f"next_chapter_preparation_{len(self._read_preparations()) + 1:03d}"

    def _chapter_id(self, chapter_index: int) -> str:
        if chapter_index < 1:
            return ""
        for chapter in self._read_chapters():
            if chapter.chapter_index == chapter_index:
                return chapter.chapter_id
        return f"chapter_{chapter_index:03d}"

    def _update_project_step(self, current_step: str, status: str) -> None:
        if not self.store.exists(self.project_file):
            return
        project = self.store.read(self.project_file)
        project["current_step"] = current_step
        project["status"] = status
        project["updated_at"] = now_iso()
        self.store.write(self.project_file, project)

    def _assert_m4_payloads_safe(
        self,
        *,
        story_progress: StoryProgress,
        transitions: list[ChapterTransitionRecord],
        preparations: list[NextChapterPreparationRecord],
        decision: Decision,
    ) -> None:
        self._assert_payload_safe(model_to_dict(story_progress), "story_progress")
        self._assert_payload_safe(
            [model_to_dict(transition) for transition in transitions],
            "chapter_transitions",
        )
        self._assert_payload_safe(
            [model_to_dict(preparation) for preparation in preparations],
            "next_chapter_preparations",
        )
        self._assert_payload_safe(model_to_dict(decision), "decision")

    def _assert_prepare_sources_safe(
        self,
        *,
        archive: ChapterArchiveRecord,
        preview: NextChapterPreviewResponse,
        request: PrepareNextChapterRequest,
    ) -> None:
        self._assert_payload_safe(model_to_dict(archive), "current_chapter_archive")
        self._assert_payload_safe(
            {
                "next_chapter_id": preview.next_chapter_id,
                "next_chapter_index": preview.next_chapter_index,
                "story_progress": model_to_dict(preview.story_progress),
                "warnings": [model_to_dict(warning) for warning in preview.warnings],
            },
            "next_chapter_prepare_preflight",
        )
        if request.scene_count_proposal is not None:
            self._assert_payload_safe(
                {"scene_count_proposal": request.scene_count_proposal},
                "next_chapter_prepare_request",
            )

    def _assert_confirm_sources_safe(
        self,
        *,
        preparation: NextChapterPreparationRecord,
        transition: ChapterTransitionRecord,
        request: ConfirmNextChapterRequest,
    ) -> None:
        self._assert_payload_safe(
            {
                "preparation": model_to_dict(preparation),
                "transition": model_to_dict(transition),
                "scene_count": request.scene_count,
            },
            "next_chapter_confirm_preflight",
        )

    def _assert_payload_safe(self, payload: Any, label: str) -> None:
        unsafe_paths = self._unsafe_payload_paths(payload)
        if unsafe_paths:
            shown = ", ".join(unsafe_paths[:5])
            raise StorageError(
                "STORY_PROGRESS_UNSAFE_PAYLOAD_BLOCKED: "
                f"{label} contains unsafe raw, hidden reasoning, or secret-like content at {shown}."
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

    def _has_unsafe_text(self, text: str) -> bool:
        lowered = text.casefold()
        return any(marker in lowered for marker in UNSAFE_TEXT_MARKERS) or any(
            pattern.search(text) for pattern in UNSAFE_TEXT_PATTERNS
        )

    def _safe_text(self, value: Any, limit: int = 500) -> str:
        text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
        if not text:
            return ""
        if self._has_unsafe_text(text):
            return "[redacted]"
        if len(text) > limit:
            return text[: max(0, limit - 3)].rstrip() + "..."
        return text

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

    def _issue(
        self,
        code: str,
        message: str,
        severity: str = "warning",
        ref_type: str = "",
        ref_id: str = "",
    ) -> StoryProgressIssue:
        return StoryProgressIssue(
            code=code,
            message=self._safe_text(message, 360),
            severity=severity,
            ref_type=ref_type,
            ref_id=ref_id,
        )
