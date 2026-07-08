from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.backend.core.config import settings
from app.backend.models.app_progress import (
    AppProgressActiveModel,
    AppProgressChapterArchive,
    AppProgressChapterPlan,
    AppProgressFramework,
    AppProgressMainCast,
    AppProgressNextChapterPreparation,
    AppProgressProject,
    AppProgressResponse,
    AppProgressScene,
    AppProgressStep,
    AppProgressWorldCanvas,
)
from app.backend.models.chapter_plan import ChapterPlanDraft
from app.backend.models.scene import Scene
from app.backend.models.story_progress import StoryProgress
from app.backend.services.chapter_archive_service import ChapterArchiveService
from app.backend.services.active_project_story_data import active_project_story_data_dir
from app.backend.services.model_gateway_service import ModelGatewayService
from app.backend.services.project_data_service import ProjectDataService
from app.backend.services.scene_gate_readiness_service import SceneGateReadinessService
from app.backend.services.scene_progress_service import SceneProgressService
from app.backend.services.story_progress_service import StoryProgressService
from app.backend.services.tracing_service import TracingService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class AppProgressService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_file: Path | None = None,
        model_gateway: ModelGatewayService | None = None,
        project_data_service: ProjectDataService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_file = project_file or settings.project_file
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.project_data_service = project_data_service or ProjectDataService(
            store=self.store,
            data_dir=self.data_dir,
            project_file=self.project_file,
            respect_active_project_selection=True,
        )
        self.scene_progress_service = SceneProgressService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapter_archive_service = ChapterArchiveService(
            store=self.store,
            data_dir=self.data_dir,
            scene_progress_service=self.scene_progress_service,
        )
        self.story_progress_service = StoryProgressService(
            store=self.store,
            data_dir=self.data_dir,
            chapter_archive_service=self.chapter_archive_service,
        )
        self.scene_gate_readiness_service = SceneGateReadinessService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.tracing = TracingService()
        self.chapter_plan_draft_file = self.data_dir / "chapter_plan_draft.json"

    def get_progress(self) -> AppProgressResponse:
        data = self.project_data_service.get_project_data()
        active_model = self._active_model_progress()
        if data.setup_required:
            return self._setup_required_progress(data=data, active_model=active_model)
        project = AppProgressProject(
            initialized=data.project is not None,
            project_id=data.project.project_id if data.project else LOCAL_PROJECT_ID,
            title=data.project.title if data.project else "",
            current_step=data.project.current_step if data.project else "",
            status=data.project.status if data.project else "",
        )
        world_canvas = AppProgressWorldCanvas(
            exists=data.world_canvas is not None,
            status=data.world_canvas.status if data.world_canvas else "",
        )
        decisions = data.decisions
        main_cast_decision_exists = any(
            decision.decision_type == "confirm"
            and decision.target_type == "main_cast"
            for decision in decisions
        )
        confirmed_characters = [
            character
            for character in data.characters
            if character.status == "confirmed" and character.tier == "A"
        ]
        main_cast = AppProgressMainCast(
            confirmed_character_count=len(confirmed_characters),
            finished=main_cast_decision_exists,
            main_cast_decision_exists=main_cast_decision_exists,
        )
        story_progress = self._story_progress_service().get_current_story_progress()
        framework = self._framework_progress(
            framework_package=data.framework_package,
            decisions=decisions,
            current_chapter_index=story_progress.current_chapter_index,
        )
        chapter_plan = self._chapter_plan_progress(
            chapters=data.chapters,
            decisions=decisions,
        )
        scene = self._scene_progress(data.scenes, story_progress.current_chapter_id)
        chapter_archive = self._chapter_archive_progress(story_progress.current_chapter_index)
        next_chapter_preparation = self._next_chapter_preparation_progress(
            story_progress.active_preparation_id,
            story_progress.next_chapter_index,
            story_progress.next_chapter_id,
        )
        locked_reasons = self._locked_reasons(
            project=project,
            active_model=active_model,
            world_canvas=world_canvas,
            main_cast=main_cast,
            framework=framework,
            chapter_plan=chapter_plan,
            scene=scene,
        )
        return AppProgressResponse(
            project=project,
            active_model=active_model,
            world_canvas=world_canvas,
            main_cast=main_cast,
            framework=framework,
            chapter_plan=chapter_plan,
            scene=scene,
            chapter_archive=chapter_archive,
            story_progress=story_progress,
            next_chapter_preparation=next_chapter_preparation,
            tracing=self.tracing.get_status(),
            steps=self._steps(
                world_canvas=world_canvas,
                main_cast=main_cast,
                framework=framework,
                chapter_plan=chapter_plan,
                scene=scene,
                locked_reasons=locked_reasons,
            ),
            next_recommended_action=self._next_recommended_action(
                project=project,
                active_model=active_model,
                world_canvas=world_canvas,
                main_cast=main_cast,
                framework=framework,
                chapter_plan=chapter_plan,
                scene=scene,
                chapter_archive=chapter_archive,
                story_progress=story_progress,
            ),
            locked_reasons=locked_reasons,
        )

    def _setup_required_progress(
        self,
        data: Any,
        active_model: AppProgressActiveModel,
    ) -> AppProgressResponse:
        project_state = data.project
        project = AppProgressProject(
            initialized=project_state is not None,
            project_id=project_state.project_id if project_state else LOCAL_PROJECT_ID,
            title=project_state.title if project_state else "",
            current_step=project_state.current_step if project_state else "story_setup_required",
            status=project_state.status if project_state else "setup_required",
        )
        locked_reasons = {
            "world_canvas": ["Story data setup is required for the active project."],
            "characters": ["Story data setup is required for the active project."],
            "framework": ["Story data setup is required for the active project."],
            "chapter_plan": ["Story data setup is required for the active project."],
            "scene": ["Story data setup is required for the active project."],
        }
        active_model = active_model.copy(
            update={"issues": self._safe_setup_issue_codes(active_model.issues)}
        )
        return AppProgressResponse(
            project=project,
            active_model=active_model,
            world_canvas=AppProgressWorldCanvas(exists=False, status="setup_required"),
            main_cast=AppProgressMainCast(),
            framework=AppProgressFramework(),
            chapter_plan=AppProgressChapterPlan(),
            scene=AppProgressScene(completion_status="setup_required"),
            story_progress=StoryProgress(
                project_id=project.project_id,
                story_progress_status="setup_required",
                next_recommended_action=project.current_step or "story_setup_required",
            ),
            tracing=self.tracing.get_status(),
            steps=[
                AppProgressStep(key="project", label="Project", state="done"),
                AppProgressStep(
                    key="world_canvas",
                    label="World Canvas",
                    state="available",
                    locked_reasons=locked_reasons["world_canvas"],
                ),
                AppProgressStep(
                    key="characters",
                    label="Characters",
                    state="locked",
                    locked_reasons=locked_reasons["characters"],
                ),
                AppProgressStep(
                    key="framework",
                    label="Framework",
                    state="locked",
                    locked_reasons=locked_reasons["framework"],
                ),
                AppProgressStep(
                    key="chapter_plan",
                    label="Chapter Plan",
                    state="locked",
                    locked_reasons=locked_reasons["chapter_plan"],
                ),
                AppProgressStep(
                    key="scene",
                    label="Scene",
                    state="locked",
                    locked_reasons=locked_reasons["scene"],
                ),
            ],
            next_recommended_action=project.current_step or "story_setup_required",
            locked_reasons=locked_reasons,
        )

    def _safe_setup_issue_codes(self, issues: list[str]) -> list[str]:
        safe: list[str] = []
        for issue in issues:
            lowered = str(issue or "").lower()
            if (
                "json file" in lowered
                or "storage" in lowered
                or ":\\" in lowered
                or "/local_project/" in lowered
                or "\\local_project\\" in lowered
            ):
                code = "model_config_missing"
            else:
                code = str(issue or "model_warning").strip()[:80] or "model_warning"
            if code not in safe:
                safe.append(code)
        return safe

    def _chapter_archive_progress(self, current_chapter_index: int | None = None) -> AppProgressChapterArchive:
        try:
            preview = self._chapter_archive_service().preview_archive(
                chapter_index=current_chapter_index,
            )
        except StorageError:
            return AppProgressChapterArchive()
        existing = preview.existing_archive
        if existing:
            return AppProgressChapterArchive(
                exists=True,
                archive_id=existing.archive_id,
                archive_status=existing.archive_status,
                chapter_id=existing.chapter_id,
                chapter_index=existing.chapter_index,
                ready_for_archive=False,
                recommended_archive_mode=existing.archive_status,
                blocking_issue_count=0,
                warning_count=len(existing.validation_report.warnings),
            )
        report = preview.validation_report
        return AppProgressChapterArchive(
            exists=False,
            chapter_id=preview.chapter_id,
            chapter_index=preview.chapter_index,
            ready_for_archive=report.passed,
            recommended_archive_mode=preview.recommended_archive_mode,
            blocking_issue_count=len(report.blocking_issues),
            warning_count=len(report.warnings),
        )

    def _next_chapter_preparation_progress(
        self,
        preparation_id: str,
        next_chapter_index: int,
        next_chapter_id: str = "",
    ) -> AppProgressNextChapterPreparation:
        try:
            preparations = self._story_progress_service()._read_preparations()
        except StorageError:
            return AppProgressNextChapterPreparation()
        confirmable_statuses = {"prepared", "awaiting_confirmation"}
        candidates = [
            preparation
            for preparation in preparations
            if preparation.preparation_status in confirmable_statuses
            and next_chapter_index
            and preparation.next_chapter_index == next_chapter_index
            and (not next_chapter_id or preparation.next_chapter_id == next_chapter_id)
            and (not preparation_id or preparation.preparation_id == preparation_id)
        ]
        if not candidates:
            return AppProgressNextChapterPreparation()
        preparation = sorted(candidates, key=lambda item: item.updated_at, reverse=True)[0]
        return AppProgressNextChapterPreparation(
            exists=True,
            preparation_id=preparation.preparation_id,
            transition_id=preparation.transition_id,
            next_chapter_id=preparation.next_chapter_id,
            next_chapter_index=preparation.next_chapter_index,
            previous_archive_id=preparation.previous_archive_id,
            preparation_status=preparation.preparation_status,
            chapter_framework_id=preparation.chapter_framework_id,
            chapter_plan_draft_id=preparation.chapter_plan_draft_id,
            chapter_memory_pack_id=preparation.chapter_memory_pack_id,
            first_scene_memory_pack_id=preparation.first_scene_memory_pack_id,
            requires_user_review=preparation.requires_user_review,
            warning_count=len(preparation.warnings),
        )

    def _active_model_progress(self) -> AppProgressActiveModel:
        status = self.model_gateway.validate_model_config()
        return AppProgressActiveModel(
            configured=status.configured,
            provider_type=status.provider_type or "",
            model_name=status.model_name or "",
            issues=status.issues,
        )

    def _chapter_plan_progress(
        self,
        chapters: list[Any],
        decisions: list[Any],
    ) -> AppProgressChapterPlan:
        draft = self._try_read_chapter_plan_draft()
        current_chapter = self._current_chapter(chapters)
        chapter_plan_decision_exists = any(
            decision.decision_type == "confirm"
            and decision.target_type == "chapter_plan"
            for decision in decisions
        )
        scene_count = 0
        current_chapter_index = 1
        status = ""
        if draft:
            current_chapter_index = draft.current_chapter_index
            status = draft.status
            brief = draft.current_chapter_brief
            scene_count = brief.user_selected_scene_count or 0
        if current_chapter and chapter_plan_decision_exists:
            current_chapter_index = current_chapter.chapter_index or current_chapter_index
            scene_count = current_chapter.scene_count or scene_count
            status = current_chapter.status or status
        if chapter_plan_decision_exists and status != "draft":
            status = "confirmed"
        return AppProgressChapterPlan(
            exists=bool(draft or chapters),
            status=status,
            current_chapter_index=current_chapter_index,
            scene_count=scene_count,
            chapter_plan_decision_exists=chapter_plan_decision_exists,
        )

    def _framework_progress(
        self,
        framework_package: Any | None,
        decisions: list[Any],
        current_chapter_index: int = 1,
    ) -> AppProgressFramework:
        if not framework_package:
            return AppProgressFramework()
        assignments = framework_package.chapter_macro_assignments
        last_decision_id = self._last_framework_mapping_decision_id(decisions)
        requires_reconfirm = any(
            assignment.status == "requires_reconfirm"
            for assignment in assignments
        )
        mapping_confirmed = bool(assignments) and bool(last_decision_id) and all(
            assignment.status == "confirmed"
            for assignment in assignments
        )
        if not assignments:
            mapping_status = "missing"
        elif mapping_confirmed:
            mapping_status = "confirmed"
        elif requires_reconfirm:
            mapping_status = "requires_reconfirm"
        else:
            mapping_status = "draft"
        chapter_count = (
            max(assignment.chapter_index for assignment in assignments)
            if assignments
            else 0
        )
        current_framework = next(
            (
                framework
                for framework in framework_package.built_chapter_frameworks
                if framework.chapter_index == current_chapter_index
            ),
            None,
        )
        return AppProgressFramework(
            package_exists=True,
            mapping_exists=bool(assignments),
            chapter_count=chapter_count,
            assignment_count=len(assignments),
            mapping_status=mapping_status,
            mapping_confirmed=mapping_confirmed,
            requires_reconfirm=requires_reconfirm,
            last_decision_id=last_decision_id,
            current_chapter_framework_built=current_framework is not None,
            current_chapter_framework_id=(
                current_framework.chapter_framework_id if current_framework else ""
            ),
            current_chapter_framework_index=(
                current_framework.chapter_index if current_framework else 0
            ),
        )

    def _scene_progress(
        self,
        scenes: list[Scene],
        current_chapter_id: str = "",
    ) -> AppProgressScene:
        progress = self._scene_progress_service().get_progress()
        current_scene = self._current_scene(scenes, current_chapter_id)
        if not current_scene:
            return AppProgressScene(
                scene_count=progress.scene_count,
                next_scene_index=progress.next_scene_index,
                can_generate_next=progress.can_generate_next,
                completion_status=progress.completion_status,
                dependency_warning_count=len(progress.dependency_warnings),
                has_temporary_scene=any(
                    scene.get("status") == "temporary_confirmed"
                    or scene.get("is_provisional")
                    for scene in progress.scenes
                ),
            )
        readiness = self._scene_gate_readiness(current_scene.scene_id)
        quality_target_type = "scene"
        quality_target_id = current_scene.scene_id
        active_candidate = None
        if current_scene.active_revision_id:
            active_candidate = next(
                (
                    candidate
                    for candidate in current_scene.revision_history
                    if candidate.revision_id == current_scene.active_revision_id
                    and candidate.status == "candidate"
                ),
                None,
            )
        if active_candidate:
            quality_target_type = "scene_revision_candidate"
            quality_target_id = active_candidate.revision_id
        open_blocking_issue_count = int(readiness.get("open_blocking_issue_count") or 0)
        open_user_action_issue_count = int(
            readiness.get("open_user_action_issue_count") or 0
        )
        return AppProgressScene(
            current_scene_exists=True,
            status=current_scene.status,
            scene_id=current_scene.scene_id,
            scene_index=current_scene.scene_index,
            prose_status=current_scene.prose_status,
            has_generated_prose=self._has_generated_scene_prose(current_scene),
            scene_count=progress.scene_count,
            next_scene_index=progress.next_scene_index,
            can_generate_next=progress.can_generate_next,
            completion_status=progress.completion_status,
            dependency_warning_count=len(progress.dependency_warnings),
            has_temporary_scene=any(
                scene.get("status") == "temporary_confirmed"
                or scene.get("is_provisional")
                for scene in progress.scenes
            ),
            has_revision_candidate=active_candidate is not None,
            active_revision_id=active_candidate.revision_id if active_candidate else "",
            quality_target_type=quality_target_type,
            quality_target_id=quality_target_id,
            quality_passed=bool(readiness.get("quality_passed")),
            blocking_issue_count=open_blocking_issue_count,
            requires_user_confirmation=bool(open_user_action_issue_count),
            gate_readiness_current=True,
            gate_safe_to_confirm=bool(readiness.get("safe_to_confirm")),
            gate_safe_to_release=bool(readiness.get("safe_to_release")),
            gate_requires_user_action=bool(readiness.get("requires_user_action")),
            gate_reason_codes=safe_list(readiness.get("reason_codes")),
        )

    def _scene_gate_readiness(self, scene_id: str) -> dict[str, Any]:
        try:
            return self._scene_gate_readiness_service().evaluate(
                scene_id,
                mode="final_confirmation",
            )
        except StorageError as exc:
            return {
                "safe_to_confirm": False,
                "safe_to_release": False,
                "quality_passed": False,
                "requires_user_action": True,
                "open_blocking_issue_count": 1,
                "open_user_action_issue_count": 0,
                "reason_codes": [
                    str(exc).split(":", 1)[0] or "scene_gate_readiness_error"
                ],
            }

    def _locked_reasons(
        self,
        project: AppProgressProject,
        active_model: AppProgressActiveModel,
        world_canvas: AppProgressWorldCanvas,
        main_cast: AppProgressMainCast,
        framework: AppProgressFramework,
        chapter_plan: AppProgressChapterPlan,
        scene: AppProgressScene,
    ) -> dict[str, list[str]]:
        reasons: dict[str, list[str]] = {
            "project": [],
            "world_canvas": [],
            "characters": [],
            "framework": [],
            "chapter_plan": [],
            "scene": [],
            "scene_revision": [],
            "scene_confirm": [],
        }
        if not project.initialized:
            reasons["world_canvas"].append("Initialize the local project first.")
        if not active_model.configured:
            reasons["world_canvas"].append("Configure an active model before generation.")
        if not world_canvas.exists or world_canvas.status != "confirmed":
            reasons["characters"].append("Confirm World Canvas before generating characters.")
            reasons["chapter_plan"].append("Confirm World Canvas before chapter planning.")
            reasons["scene"].append("Confirm World Canvas before scene generation.")
        if main_cast.confirmed_character_count < 1:
            reasons["chapter_plan"].append("Confirm at least one A-tier character.")
            reasons["scene"].append("Confirm at least one A-tier character.")
        if not main_cast.finished:
            reasons["framework"].append("Finish Main Cast before confirming framework mapping.")
            reasons["chapter_plan"].append("Finish Main Cast before chapter planning.")
            reasons["scene"].append("Finish Main Cast before scene generation.")
        if not framework.package_exists:
            reasons["framework"].append("Initialize Framework Package before framework mapping.")
            reasons["chapter_plan"].append("Initialize Framework Package before chapter planning.")
            reasons["scene"].append("Initialize Framework Package before scene generation.")
        elif (
            not framework.mapping_confirmed
            and not chapter_plan.chapter_plan_decision_exists
        ):
            reasons["chapter_plan"].append("Confirm lightweight framework mapping before chapter planning.")
        elif framework.mapping_confirmed and not framework.current_chapter_framework_built:
            reasons["chapter_plan"].append("Build current chapter framework before chapter planning.")
        if not chapter_plan.chapter_plan_decision_exists or chapter_plan.status != "confirmed":
            reasons["scene"].append("Confirm Chapter Plan before generating the first scene.")
        if chapter_plan.scene_count < 1:
            reasons["scene"].append("Set scene_count for the current chapter.")
        if not framework.current_chapter_framework_built:
            reasons["scene"].append("Build current chapter framework before scene generation.")
        if not scene.current_scene_exists:
            reasons["scene_revision"].append("Generate a Scene draft before prompt revision.")
            reasons["scene_confirm"].append("Generate a Scene draft before confirmation.")
        elif scene.status in {
            "draft",
            "revised",
            "needs_review",
            "needs_regeneration",
            "continuity_recheck",
        } and not scene.has_generated_prose:
            reasons["scene_confirm"].append("Generate Scene prose before confirming Scene draft.")
        if scene.current_scene_exists and scene.has_generated_prose and not scene.gate_safe_to_confirm:
            reason_codes = ", ".join(scene.gate_reason_codes) or "scene_gate_not_ready"
            reasons["scene_confirm"].append(
                f"Resolve scene gate readiness before confirming Scene draft: {reason_codes}."
            )
        return {key: value for key, value in reasons.items() if value}

    def _steps(
        self,
        world_canvas: AppProgressWorldCanvas,
        main_cast: AppProgressMainCast,
        framework: AppProgressFramework,
        chapter_plan: AppProgressChapterPlan,
        scene: AppProgressScene,
        locked_reasons: dict[str, list[str]],
    ) -> list[AppProgressStep]:
        return [
            AppProgressStep(
                key="project",
                label="Project",
                state="done",
                locked_reasons=locked_reasons.get("project", []),
            ),
            AppProgressStep(
                key="world_canvas",
                label="World Canvas",
                state=self._world_step_state(world_canvas),
                locked_reasons=locked_reasons.get("world_canvas", []),
            ),
            AppProgressStep(
                key="characters",
                label="Characters",
                state="done" if main_cast.finished else "available",
                locked_reasons=locked_reasons.get("characters", []),
            ),
            AppProgressStep(
                key="framework",
                label="Framework",
                state=self._framework_step_state(framework, locked_reasons),
                locked_reasons=locked_reasons.get("framework", []),
            ),
            AppProgressStep(
                key="chapter_plan",
                label="Chapter Plan",
                state=self._chapter_step_state(chapter_plan, locked_reasons),
                locked_reasons=locked_reasons.get("chapter_plan", []),
            ),
            AppProgressStep(
                key="scene",
                label="Scene",
                state=self._scene_step_state(scene, locked_reasons),
                locked_reasons=locked_reasons.get("scene", []),
            ),
        ]

    def _next_recommended_action(
        self,
        project: AppProgressProject,
        active_model: AppProgressActiveModel,
        world_canvas: AppProgressWorldCanvas,
        main_cast: AppProgressMainCast,
        framework: AppProgressFramework,
        chapter_plan: AppProgressChapterPlan,
        scene: AppProgressScene,
        chapter_archive: AppProgressChapterArchive,
        story_progress: Any,
    ) -> str:
        if not project.initialized:
            return "initialize_project"
        if not active_model.configured:
            return "configure_active_model"
        if not world_canvas.exists:
            return "generate_world_canvas"
        if world_canvas.status != "confirmed":
            return "confirm_world_canvas"
        if main_cast.confirmed_character_count < 1:
            return "generate_character"
        if not main_cast.finished:
            return "finish_main_cast"
        if not framework.package_exists:
            return "setup_framework"
        if (
            not framework.mapping_confirmed
            and not chapter_plan.chapter_plan_decision_exists
        ):
            return "confirm_framework_mapping"
        if framework.mapping_confirmed and not framework.current_chapter_framework_built:
            return "build_current_chapter_framework"
        if not chapter_plan.exists:
            return "generate_chapter_plan"
        if chapter_plan.scene_count < 1:
            return "set_scene_count"
        if not chapter_plan.chapter_plan_decision_exists or chapter_plan.status != "confirmed":
            return "confirm_chapter_plan"
        if not scene.current_scene_exists:
            return "generate_first_scene"
        if scene.status in {
            "draft",
            "revised",
            "needs_review",
            "needs_regeneration",
            "continuity_recheck",
        }:
            if not scene.has_generated_prose:
                return "regenerate_scene"
            if not scene.gate_safe_to_confirm:
                return "review_scene_gate"
            return "confirm_scene"
        if scene.can_generate_next:
            return "generate_next_scene"
        if story_progress.next_recommended_action == "story_draft_complete":
            return "story_draft_complete"
        if scene.completion_status == "provisional_complete":
            return "review_provisional_archive"
        if scene.completion_status == "final_complete":
            return "preview_chapter_archive"
        if story_progress.next_recommended_action in {
            "preview_next_chapter",
            "prepare_next_chapter",
            "confirm_next_chapter",
            "story_draft_complete",
        }:
            return story_progress.next_recommended_action
        if chapter_archive.exists:
            return "preview_next_chapter"
        return "review_scene_gate"

    def _has_generated_scene_prose(self, scene: Scene) -> bool:
        prose_text = scene.prose_text or ""
        if scene.content and scene.content.prose_text:
            prose_text = scene.content.prose_text
        return bool(prose_text.strip()) and scene.prose_status not in {
            "not_generated",
            "fallback_generated",
        }

    def _world_step_state(self, world_canvas: AppProgressWorldCanvas) -> str:
        if not world_canvas.exists:
            return "available"
        if world_canvas.status == "confirmed":
            return "done"
        if world_canvas.status == "draft":
            return "draft"
        return "warning"

    def _chapter_step_state(
        self,
        chapter_plan: AppProgressChapterPlan,
        locked_reasons: dict[str, list[str]],
    ) -> str:
        if locked_reasons.get("chapter_plan"):
            return "locked"
        if chapter_plan.status == "confirmed":
            return "done"
        if chapter_plan.exists:
            return "draft"
        return "available"

    def _framework_step_state(
        self,
        framework: AppProgressFramework,
        locked_reasons: dict[str, list[str]],
    ) -> str:
        if locked_reasons.get("framework"):
            return "locked"
        if framework.mapping_confirmed:
            return "done"
        if framework.requires_reconfirm:
            return "warning"
        if framework.mapping_exists:
            return "draft"
        if framework.package_exists:
            return "available"
        return "locked"

    def _scene_step_state(
        self,
        scene: AppProgressScene,
        locked_reasons: dict[str, list[str]],
    ) -> str:
        if locked_reasons.get("scene"):
            return "locked"
        if scene.completion_status == "final_complete":
            return "done"
        if scene.completion_status == "provisional_complete":
            return "warning"
        if scene.current_scene_exists and scene.has_generated_prose and not scene.gate_safe_to_confirm:
            return "warning"
        if scene.can_generate_next:
            return "available"
        if scene.current_scene_exists:
            return "draft"
        return "available"

    def _current_chapter(self, chapters: list[Any]) -> Any | None:
        return (
            next((chapter for chapter in chapters if chapter.detail_level == "current_chapter_brief"), None)
            or next((chapter for chapter in chapters if chapter.status == "active"), None)
            or next((chapter for chapter in chapters if chapter.chapter_framework_id), None)
        )

    def _current_scene(
        self,
        scenes: list[Scene],
        current_chapter_id: str = "",
    ) -> Scene | None:
        if current_chapter_id:
            scenes = [
                scene for scene in scenes
                if scene.chapter_id == current_chapter_id
            ]
        if not scenes:
            return None
        return sorted(
            scenes,
            key=lambda scene: (scene.scene_index, scene.updated_at or scene.created_at),
            reverse=True,
        )[0]

    def _try_read_chapter_plan_draft(self) -> ChapterPlanDraft | None:
        chapter_plan_draft_file = self._story_data_dir() / "chapter_plan_draft.json"
        if not self.store.exists(chapter_plan_draft_file):
            return None
        try:
            return ChapterPlanDraft(**self.store.read(chapter_plan_draft_file))
        except ValidationError as exc:
            raise StorageError("ChapterPlanDraft JSON schema is invalid.") from exc

    def _story_data_dir(self) -> Path:
        return active_project_story_data_dir(self.store, self.data_dir) or self.data_dir

    def _scene_progress_service(self) -> SceneProgressService:
        story_data_dir = self._story_data_dir()
        if story_data_dir == self.data_dir:
            return self.scene_progress_service
        return SceneProgressService(store=self.store, data_dir=story_data_dir)

    def _scene_gate_readiness_service(self) -> SceneGateReadinessService:
        story_data_dir = self._story_data_dir()
        if story_data_dir == self.data_dir:
            return self.scene_gate_readiness_service
        return SceneGateReadinessService(store=self.store, data_dir=story_data_dir)

    def _chapter_archive_service(self) -> ChapterArchiveService:
        story_data_dir = self._story_data_dir()
        if story_data_dir == self.data_dir:
            return self.chapter_archive_service
        scene_progress_service = SceneProgressService(store=self.store, data_dir=story_data_dir)
        return ChapterArchiveService(
            store=self.store,
            data_dir=story_data_dir,
            scene_progress_service=scene_progress_service,
        )

    def _story_progress_service(self) -> StoryProgressService:
        story_data_dir = self._story_data_dir()
        if story_data_dir == self.data_dir:
            return self.story_progress_service
        chapter_archive_service = self._chapter_archive_service()
        return StoryProgressService(
            store=self.store,
            data_dir=story_data_dir,
            chapter_archive_service=chapter_archive_service,
        )

    def _last_framework_mapping_decision_id(self, decisions: list[Any]) -> str:
        matching = [
            decision
            for decision in decisions
            if decision.target_type == "framework_macro_mapping"
        ]
        if not matching:
            return ""
        matching.sort(key=lambda decision: decision.created_at or "")
        return matching[-1].decision_id
