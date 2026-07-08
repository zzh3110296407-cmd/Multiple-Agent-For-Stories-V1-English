from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import json
import logging
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.agents.memory_curator_agent import MemoryCuratorAgent
from app.backend.agents.quality_check_agent import QualityCheckAgent
from app.backend.agents.scene_information_agent import SceneInformationAgent
from app.backend.agents.write_agent import WriteAgent
from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import Character, CharacterContextBuildRequest
from app.backend.models.decision import Decision
from app.backend.models.event import Event
from app.backend.models.framework_package import ChapterFramework, FrameworkPackage
from app.backend.models.memory_record import MEMORY_M2_VERSION_ID, MemoryRecord
from app.backend.models.relationship import Relationship
from app.backend.models.scene import Scene
from app.backend.models.scene_generation import (
    OrderedStoryInformationPackage,
    SceneCommitRequest,
    SceneDraftContent,
    SceneGenerateNextRequest,
    SceneGatePipelineSummary,
    SceneGenerationReadyStatus,
    SceneGenerationResponse,
    SceneGenerationTrace,
    SceneMemoryExtraction,
    SceneProgressionInspection,
    SceneProgressionStatement,
    SceneQualityReport,
    SceneWritingContext,
    StoryInformationItem,
)
from app.backend.models.scene_pattern_similarity import (
    SCENE_PATTERN_SIMILARITY_TOO_HIGH,
    SCENE_PATTERN_SIMILARITY_WARNING,
)
from app.backend.models.scene_snapshot import SceneSnapshotRef
from app.backend.models.state_change import StateChange
from app.backend.models.world_canvas import WorldCanvas
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.character_context_builder import CharacterContextBuilder
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.authorial_intent_service import AuthorialIntentService
from app.backend.services.abcd_runtime_gate_integration_service import (
    ABCDRuntimeGateIntegrationService,
)
from app.backend.services.continuity_gate_service import (
    ContinuityGateService,
    SceneConfirmationGuard,
)
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.services.generator_framework_context_service import (
    SCHEMA_VERSION as GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_VERSION,
)
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.objective_fact_write_guard import ObjectiveFactWriteGuard
from app.backend.services.provisional_dependency_service import ProvisionalDependencyService
from app.backend.services.project_story_premise_service import ProjectStoryPremiseService
from app.backend.services.character_prompt_fidelity_service import (
    premise_required_terms,
    require_project_story_premise_for_generation,
)
from app.backend.services.prompt_anchor_classification_service import classify_prompt_anchor_values
from app.backend.services.project_story_premise_service import FORBIDDEN_DEMO_DEFAULTS
from app.backend.services.quality_check_service import QualityCheckService
from app.backend.services.scene_progress_service import (
    NEXT_READY_SCENE_STATUSES,
    SceneProgressService,
)
from app.backend.services.scene_memory_service import SceneMemoryService
from app.backend.services.scene_pattern_similarity_gate_service import (
    ScenePatternSimilarityGateService,
)
from app.backend.models.scene_participation import SceneParticipationPrepareRequest
from app.backend.services.scene_participation_package_service import (
    SceneParticipationPackageService,
)
from app.backend.services.scene_runtime_refresh_state_service import (
    SceneRuntimeRefreshStateService,
)
from app.backend.services.scene_gate_readiness_service import SceneGateReadinessService
from app.backend.services.scene_version_snapshot_service import (
    SceneVersionSnapshotService,
)
from app.backend.services.subjective_fact_extraction_service import (
    SubjectiveFactExtractionService,
)
from app.backend.services.subjective_fact_write_service import SubjectiveFactWriteService
from app.backend.services.tiered_scene_memory_writeback_service import (
    TieredSceneMemoryWritebackService,
)
from app.backend.services.tracing_service import traceable_operation
from app.backend.storage.json_store import JsonStore, StorageError


logger = logging.getLogger(__name__)

LOCAL_PROJECT_ID = "local_project"
SCENE_GENERATION_VERSION_ID = "version_scene_m7_001"
GENERATOR_FRAMEWORK_CONTEXT_FILE = "generator_framework_context.json"
SCENE_WRITER_PROJECT_STORY_PREMISE_MISSING = "scene_writer_project_story_premise_missing"
SCENE_PROGRESSION_STATEMENT_MISSING = "scene_progression_statement_missing"
SCENE_PROGRESSION_STATEMENT_REPEATED = "scene_progression_statement_repeated"
SCENE_PREVIOUS_SUMMARY_MISSING = "scene_previous_summary_missing"
SCENE_STATE_DELTA_MISSING = "scene_state_delta_missing"
SCENE_REPETITION_TOO_HIGH = "scene_repetition_too_high"
SCENE_PATTERN_HIDDEN_CODES = {
    SCENE_PATTERN_SIMILARITY_WARNING,
    SCENE_PATTERN_SIMILARITY_TOO_HIGH,
}
SCENE_PROGRESSION_MISSING = "scene_progression_missing"
SCENE_OBJECTIVE_REPEATED = "scene_objective_repeated"
SCENE_PROMPT_FIDELITY_WEAK = "scene_prompt_fidelity_weak"
SCENE_PROMPT_FIDELITY_MISSING = "scene_prompt_fidelity_missing"
SCENE_DEMO_DEFAULT_LEAK = "scene_demo_default_leak"
GENERIC_SCENE_PROGRESSION_OBJECTIVE = (
    "Advance this scene with a new clue, action, and character pressure."
)
SCENE_ADJACENT_SIMILARITY_BLOCK_THRESHOLD = 0.72
SCENE_LAST_THREE_SIMILARITY_BLOCK_THRESHOLD = 0.78
SCENE_NEAR_COPY_SIMILARITY_BLOCK_THRESHOLD = 0.96
SCENE_EXACT_COPY_SIMILARITY_BLOCK_THRESHOLD = 0.995
INTERNAL_PROSE_MARKERS = (
    "Provider",
    "provider_failure",
    "HTTP error",
    "Model provider",
    "SceneInformationFallback",
    "Context JSON",
    "Current chapter",
    "Chapter goal",
    "Memory ",
    "Keywords:",
    "Ordered story information",
    "scene_information",
    "memory_extraction",
    "narrative_intent",
    "prose_text",
    "role_memory",
    "MODEL_FALLBACK_PLACEHOLDER",
    "diagnostic placeholder",
    "error=",
    "error status=",
    "围绕本幕目标",
    "不得越过已确认世界规则",
    "外部模型",
    "错误摘要",
    "系统内部",
)
NON_STORY_PROSE_FAILURE_MARKERS = (
    "MODEL_FALLBACK_PLACEHOLDER",
    "External model output was not valid story prose",
    "diagnostic placeholder",
    "Failure summary:",
    "外部模型未能生成正式修订散文",
)
NON_STORY_PROSE_ERROR_MARKERS = (
    "Provider HTTP error",
    "ModelCallError",
    "model service call failed",
    "失败阶段摘要：",
)
SCENE_GATE_PROVIDER_DEGRADED_RECHECK_ATTEMPTS = 2
COMPOSITE_RUNTIME_RUNS_FILE = "composite_runtime_graph_runs.json"
ALLOWED_MAIN_CAST_STEPS = {
    "characters_confirmed",
    "chapter_plan_draft",
    "chapter_plan_confirmed",
    "scene_1_draft",
    "scene_1_confirmed",
}
ALLOWED_CHAPTER_PLAN_STEPS = {
    "chapter_plan_confirmed",
    "scene_1_draft",
    "scene_1_confirmed",
}
ALLOWED_SCENE_COMMIT_TYPES = {"confirmed", "revised", "temporary_confirmed"}
SHANGHAI_TZ = timezone(timedelta(hours=8))


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class SceneGenerationService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        model_gateway: ModelGatewayService | None = None,
        framework_service: FrameworkPackageService | None = None,
        scene_information_agent: SceneInformationAgent | None = None,
        write_agent: WriteAgent | None = None,
        memory_curator_agent: MemoryCuratorAgent | None = None,
        quality_check_agent: QualityCheckAgent | None = None,
        quality_check_service: QualityCheckService | None = None,
        scene_memory_service: SceneMemoryService | None = None,
        scene_participation_service: SceneParticipationPackageService | None = None,
        character_context_builder: CharacterContextBuilder | None = None,
        scene_progress_service: SceneProgressService | None = None,
        dependency_service: ProvisionalDependencyService | None = None,
        continuity_gate_service: ContinuityGateService | None = None,
        authorial_intent_service: AuthorialIntentService | None = None,
        subjective_fact_extraction_service: SubjectiveFactExtractionService | None = None,
        subjective_fact_write_service: SubjectiveFactWriteService | None = None,
        objective_fact_write_guard: ObjectiveFactWriteGuard | None = None,
        role_memory_writeback_service: TieredSceneMemoryWritebackService | None = None,
        abcd_runtime_gate_service: ABCDRuntimeGateIntegrationService | None = None,
        scene_runtime_refresh_state_service: SceneRuntimeRefreshStateService | None = None,
        scene_gate_readiness_service: SceneGateReadinessService | None = None,
        scene_gate_repair_orchestrator: Any | None = None,
        project_story_premise_service: ProjectStoryPremiseService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.project_file = self.data_dir / "project.json"
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.scenes_file = self.data_dir / "scenes.json"
        self.events_file = self.data_dir / "events.json"
        self.state_changes_file = self.data_dir / "state_changes.json"
        self.memory_records_file = self.data_dir / "memory_records.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.chapter_plan_draft_file = self.data_dir / "chapter_plan_draft.json"
        self.generator_framework_context_file = (
            self.data_dir / GENERATOR_FRAMEWORK_CONTEXT_FILE
        )
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_service = framework_service or FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_information_agent = scene_information_agent or SceneInformationAgent(
            model_gateway=self.model_gateway,
        )
        self.write_agent = write_agent or WriteAgent(model_gateway=self.model_gateway)
        self.memory_curator_agent = memory_curator_agent or MemoryCuratorAgent(
            model_gateway=self.model_gateway,
        )
        self.quality_check_agent = quality_check_agent or QualityCheckAgent(
            model_gateway=self.model_gateway,
        )
        self.quality_check_service = quality_check_service or QualityCheckService(
            store=self.store,
            data_dir=self.data_dir,
            model_gateway=self.model_gateway,
            framework_service=self.framework_service,
        )
        self.scene_memory_service = scene_memory_service or SceneMemoryService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scene_snapshot_service = SceneVersionSnapshotService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.role_memory_writeback_service = role_memory_writeback_service or (
            TieredSceneMemoryWritebackService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.abcd_runtime_gate_service = abcd_runtime_gate_service or (
            ABCDRuntimeGateIntegrationService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.character_context_builder = character_context_builder or CharacterContextBuilder(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scene_participation_service = (
            scene_participation_service
            or SceneParticipationPackageService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
                scene_memory_service=self.scene_memory_service,
                character_context_builder=self.character_context_builder,
            )
        )
        self.scene_progress_service = scene_progress_service or SceneProgressService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.dependency_service = dependency_service or ProvisionalDependencyService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.continuity_gate_service = continuity_gate_service or ContinuityGateService(
            store=self.store,
            data_dir=self.data_dir,
            model_gateway=self.model_gateway,
            repositories=self.repositories,
        )
        self.authorial_intent_service = (
            authorial_intent_service
            or AuthorialIntentService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
                model_gateway=self.model_gateway,
            )
        )
        self.subjective_fact_extraction_service = (
            subjective_fact_extraction_service
            or SubjectiveFactExtractionService()
        )
        self.subjective_fact_write_service = (
            subjective_fact_write_service
            or SubjectiveFactWriteService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.objective_fact_write_guard = (
            objective_fact_write_guard or ObjectiveFactWriteGuard()
        )
        self.project_story_premise_service = (
            project_story_premise_service
            or ProjectStoryPremiseService(store=self.store, data_dir=self.data_dir)
        )
        self.scene_confirmation_guard = SceneConfirmationGuard(
            self.continuity_gate_service
        )
        self.scene_runtime_refresh_state_service = scene_runtime_refresh_state_service or (
            SceneRuntimeRefreshStateService(
                store=self.store,
                data_dir=self.data_dir,
                abcd_runtime_gate_service=self.abcd_runtime_gate_service,
                scene_participation_service=self.scene_participation_service,
            )
        )
        self.scene_gate_readiness_service = scene_gate_readiness_service or (
            SceneGateReadinessService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.scene_gate_repair_orchestrator = scene_gate_repair_orchestrator

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_scene(self) -> SceneGenerationResponse:
        scene = self._find_current_scene()
        chapter_id = scene.chapter_id if scene else None
        return SceneGenerationResponse(
            success=scene is not None,
            scene=model_to_dict(scene) if scene else None,
            story_information_summary=self._story_information_summary(scene),
            quality_report=scene.quality_report if scene else None,
            readiness=self.check_scene_generation_ready(),
            progress=self.get_scene_progress(chapter_id),
            scene_gate_pipeline=self._scene_gate_pipeline_from_scene(scene)
            if scene
            else None,
        )

    def get_scene_progress(
        self,
        chapter_id: str | None = None,
    ):
        return self.scene_progress_service.get_progress(chapter_id)

    @traceable_operation("SceneGenerationService.generate_first_scene", tags=["scene"])
    def generate_first_scene(
        self,
        chapter_id: str | None = None,
        scene_index: int = 1,
    ) -> SceneGenerationResponse:
        if scene_index != 1:
            raise StorageError(
                "SCENE_INDEX_INVALID: generate-first only supports scene_index=1; use generate-next for sequential scenes."
            )
        return self._generate_scene_draft(
            chapter_id=chapter_id,
            scene_index=scene_index,
            regeneration_hint="",
        )

    @traceable_operation("SceneGenerationService.generate_next_scene", tags=["scene"])
    def generate_next_scene(
        self,
        request: SceneGenerateNextRequest | None = None,
    ) -> SceneGenerationResponse:
        request = request or SceneGenerateNextRequest()
        progress = self.get_scene_progress(request.chapter_id)
        if progress.scene_count < 1:
            raise StorageError(
                "SCENE_NEXT_NOT_READY: 当前章还没有设置 scene_count。"
            )
        if progress.next_scene_index > progress.scene_count:
            raise StorageError(
                "SCENE_COUNT_REACHED: 当前章已经达到 scene_count，不能继续生成下一幕。"
            )
        if not progress.can_generate_next:
            reason_codes = set(progress.blocking_reason_codes)
            code = (
                "SCENE_PREVIOUS_NOT_COMMITTED"
                if "previous_scene_not_committed" in reason_codes
                else "SCENE_PREVIOUS_SCENE_MISSING"
                if "previous_scene_missing" in reason_codes
                else "SCENE_CURRENT_DRAFT_EXISTS"
                if "current_scene_draft_exists" in reason_codes
                else "SCENE_NEXT_NOT_READY"
            )
            raise StorageError(
                f"{code}: "
                + ("；".join(progress.blocking_reasons) or "下一幕暂不可生成。")
            )
        include_provisional = self._should_include_provisional_for_next(
            request.include_provisional,
            progress,
        )
        response = self._generate_scene_draft(
            chapter_id=progress.chapter_id,
            scene_index=progress.next_scene_index,
            regeneration_hint="",
            write_prose=True,
            force_refresh_packs=request.force_refresh_packs,
            include_provisional=include_provisional,
            progress_before=progress,
        )
        return response

    @traceable_operation("SceneGenerationService.regenerate_first_scene", tags=["scene"])
    def regenerate_first_scene(
        self,
        regeneration_hint: str = "",
    ) -> SceneGenerationResponse:
        current_scene = self._find_current_scene()
        if current_scene and current_scene.status in {"confirmed", "committed"}:
            raise StorageError(
                "SCENE_ALREADY_CONFIRMED: Current scene is confirmed and cannot be regenerated in Milestone 7."
            )
        chapter_id = current_scene.chapter_id if current_scene else None
        return self._generate_scene_draft(
            chapter_id=chapter_id,
            scene_index=1,
            regeneration_hint=regeneration_hint.strip(),
        )

    @traceable_operation("SceneGenerationService.confirm_scene_draft", tags=["scene"])
    def confirm_scene_draft(
        self,
        user_input: str | None = None,
    ) -> SceneGenerationResponse:
        scene = self._find_current_scene()
        if scene is None:
            raise StorageError("SCENE_DRAFT_MISSING: Current scene draft does not exist.")
        return self.commit_scene(
            scene_id=scene.scene_id,
            request=SceneCommitRequest(
                commit_type="confirmed",
                user_input=user_input,
            ),
        )

    @traceable_operation("SceneGenerationService.commit_scene", tags=["scene"])
    def commit_scene(
        self,
        scene_id: str,
        request: SceneCommitRequest,
    ) -> SceneGenerationResponse:
        commit_type = str(request.commit_type or "").strip()
        if commit_type not in ALLOWED_SCENE_COMMIT_TYPES:
            raise StorageError(
                "SCENE_COMMIT_TYPE_INVALID: commit_type must be confirmed, revised, or temporary_confirmed."
            )
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_DRAFT_MISSING: Scene draft does not exist.")
        if commit_type == "temporary_confirmed":
            return self._temporary_confirm_scene(
                scene=scene,
                user_input=request.user_input,
            )
        if commit_type == "revised":
            return self._commit_revised_scene(
                scene=scene,
                revision_id=request.revision_id,
                user_input=request.user_input,
                accepted_abcd_runtime_issue_ids=request.accepted_abcd_runtime_issue_ids,
            )
        return self._confirm_scene(
            scene=scene,
            user_input=request.user_input,
            accepted_abcd_runtime_issue_ids=request.accepted_abcd_runtime_issue_ids,
        )

    def temporary_confirm_scene(
        self,
        scene_id: str,
        user_input: str | None = None,
    ) -> SceneGenerationResponse:
        return self.commit_scene(
            scene_id=scene_id,
            request=SceneCommitRequest(
                commit_type="temporary_confirmed",
                user_input=user_input,
            ),
        )

    def _confirm_scene(
        self,
        scene: Scene,
        user_input: str | None = None,
        accepted_abcd_runtime_issue_ids: list[str] | None = None,
    ) -> SceneGenerationResponse:
        if scene.status in {"confirmed", "committed"} and not scene.is_provisional:
            raise StorageError(
                "SCENE_ALREADY_CONFIRMED: Current scene has already been confirmed."
            )
        clean_user_input = (user_input or "").strip()
        source_was_provisional = scene.status == "temporary_confirmed" or scene.is_provisional
        prepared_scene = self._ensure_scene_has_prose(scene)
        if self._is_non_story_failure_prose(prepared_scene.prose_text):
            raise StorageError(
                "SCENE_NON_STORY_FALLBACK_PROSE: Cannot confirm diagnostic fallback/provider failure text as story prose."
            )
        quality_response = None
        try:
            quality_response = self.quality_check_service.check_scene_object(
                prepared_scene,
                context=self._approved_context_for_scene(prepared_scene),
                persist_scene=False,
            )
            quality_report = quality_response.embedded_report
            quality_report_id = quality_response.report.quality_report_id
        except (ModelCallError, ModelJsonParseError) as exc:
            raise StorageError(
                "SCENE_QUALITY_CHECK_UNAVAILABLE: Final quality check failed; retry before confirming this scene."
            ) from exc
        prepared_scene = Scene(
            **{
                **model_to_dict(prepared_scene),
                "quality_report": model_to_dict(quality_report),
                "quality_report_id": quality_report_id,
                "updated_at": now_iso(),
            }
        )
        self.save_scene_draft(prepared_scene)
        self.continuity_gate_service.check_scene(
            prepared_scene.scene_id,
            mode="final_confirmation",
        )
        reloaded_scene = self._find_scene_by_id(prepared_scene.scene_id)
        if reloaded_scene is not None:
            prepared_scene = reloaded_scene
        self._require_abcd_runtime_gate_final(
            prepared_scene.scene_id,
            user_confirmation_text=clean_user_input,
            accepted_issue_ids=accepted_abcd_runtime_issue_ids,
        )
        self.scene_runtime_refresh_state_service.require_confirm_allowed(
            prepared_scene.scene_id,
            user_confirmation_text=clean_user_input,
        )
        self.scene_gate_readiness_service.require_safe_to_confirm(
            prepared_scene.scene_id,
            boundary_code="SCENE_GATE_READINESS_BLOCKED",
        )
        self._record_composite_runtime_commit_boundary_preview(
            prepared_scene,
            (
                f"scene_final_confirmation_receipt_{prepared_scene.scene_id}_"
                f"{now_iso().replace(':', '').replace('.', '')}"
            ),
        )

        memory_ready_scene = self._ensure_scene_memory_extraction(prepared_scene)
        memory_ready_scene = self._apply_subjective_fact_write_rules(
            memory_ready_scene,
            status="active",
        )
        events = self.write_confirmed_events(memory_ready_scene, status="confirmed")
        state_changes = self.write_confirmed_state_changes(
            memory_ready_scene,
            events,
            default_status="confirmed",
        )
        memory_records = self.write_memory_records(
            memory_ready_scene,
            events,
            status_override="active",
            source_type="scene_confirmed",
        )
        event_ids = [event.event_id for event in events]
        state_change_ids = [change.state_change_id for change in state_changes]
        timestamp = now_iso()
        confirmed_scene = Scene(
            **{
                **model_to_dict(memory_ready_scene),
                "status": "confirmed",
                "prose_status": "generated",
                "is_provisional": False,
                "event_ids": event_ids,
                "state_change_ids": state_change_ids,
                "quality_report": model_to_dict(quality_report),
                "quality_report_id": quality_report_id,
                "needs_review_reason": "",
                "updated_at": timestamp,
            }
        )
        self.save_confirmed_scene(confirmed_scene)
        self._attach_scene_to_chapter(confirmed_scene)
        self._write_tiered_role_memory(
            scene=confirmed_scene,
            commit_type="confirmed",
            events=events,
            state_changes=state_changes,
            memory_records=memory_records,
        )
        self._run_abcd_runtime_gate_audit(
            confirmed_scene.scene_id,
            mode="post_commit_audit",
        )
        if source_was_provisional:
            self.dependency_service.mark_dependents_for_recheck(
                source_scene_id=confirmed_scene.scene_id,
                source_memory_ids=[memory.memory_id for memory in memory_records],
                reason=f"第 {confirmed_scene.scene_index} 幕临时事实已转为正式版本，需要复核依赖场景。",
            )
        decision = self.write_decision(
            target_id=confirmed_scene.scene_id,
            user_input=clean_user_input
            or f"正式确认第 {confirmed_scene.scene_index} 幕。",
        )
        scene_snapshot = self._create_confirmed_scene_snapshot(
            confirmed_scene,
            decision,
        )
        self.update_project_step(
            f"scene_{confirmed_scene.scene_index}_confirmed",
            f"scene_{confirmed_scene.scene_index}_confirmed",
        )
        return SceneGenerationResponse(
            success=True,
            scene=model_to_dict(confirmed_scene),
            story_information_summary=self._story_information_summary(confirmed_scene),
            quality_report=confirmed_scene.quality_report,
            readiness=self.check_scene_generation_ready(
                chapter_id=confirmed_scene.chapter_id,
                scene_index=confirmed_scene.scene_index,
            ),
            decision=decision,
            scene_snapshot=scene_snapshot,
            progress=self.get_scene_progress(confirmed_scene.chapter_id),
        )

    def _create_confirmed_scene_snapshot(
        self,
        scene: Scene,
        decision: Decision,
    ) -> dict[str, Any]:
        decision_ref = SceneSnapshotRef(
            ref_type="decision",
            ref_id=decision.decision_id,
            ref_status=decision.decision_type,
            role="audit_ref",
            safe_label="Scene confirmation decision",
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
        )
        snapshot = self.scene_snapshot_service.create_snapshot_for_scene(
            scene_id=scene.scene_id,
            snapshot_type="confirmed_scene",
            target_scene_id=scene.scene_id,
            extra_refs=[decision_ref],
        )
        return {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "snapshot_type": snapshot.snapshot_type,
            "status": snapshot.status,
            "ref_count": len(snapshot.source_refs),
        }

    def _temporary_confirm_scene(
        self,
        scene: Scene,
        user_input: str | None = None,
    ) -> SceneGenerationResponse:
        if scene.status in {"confirmed", "committed"} and not scene.is_provisional:
            raise StorageError(
                "SCENE_ALREADY_CONFIRMED: Current scene has already been confirmed."
            )
        self.scene_confirmation_guard.require_scene_confirmation_allowed(
            scene.scene_id,
            mode="temporary_confirmation",
        )
        reloaded_scene = self._find_scene_by_id(scene.scene_id)
        if reloaded_scene is not None:
            scene = reloaded_scene
        self._run_abcd_runtime_gate_audit(
            scene.scene_id,
            mode="temporary_confirmation",
        )
        memory_ready_scene = self._ensure_scene_memory_extraction(scene)
        memory_ready_scene = self._apply_subjective_fact_write_rules(
            memory_ready_scene,
            status="provisional",
        )
        events = self.write_confirmed_events(memory_ready_scene, status="provisional")
        state_changes = self.write_confirmed_state_changes(
            memory_ready_scene,
            events,
            default_status="provisional",
        )
        memory_records = self.write_memory_records(
            memory_ready_scene,
            events,
            status_override="provisional",
            source_type="scene_temporary_confirmed",
        )
        timestamp = now_iso()
        temporary_scene = Scene(
            **{
                **model_to_dict(memory_ready_scene),
                "status": "temporary_confirmed",
                "prose_status": "skipped",
                "is_provisional": True,
                "event_ids": [event.event_id for event in events],
                "state_change_ids": [
                    change.state_change_id for change in state_changes
                ],
                "updated_at": timestamp,
            }
        )
        self.save_confirmed_scene(temporary_scene)
        self._attach_scene_to_chapter(temporary_scene)
        self._write_tiered_role_memory(
            scene=temporary_scene,
            commit_type="temporary_confirmed",
            events=events,
            state_changes=state_changes,
            memory_records=memory_records,
        )
        self._run_abcd_runtime_gate_audit(
            temporary_scene.scene_id,
            mode="post_commit_audit",
        )
        decision = self.write_decision(
            target_id=temporary_scene.scene_id,
            user_input=(user_input or "").strip()
            or f"临时确认第 {temporary_scene.scene_index} 幕，先保留结构信息继续推进。",
            decision_type="temporary_confirm",
        )
        self.update_project_step(
            f"scene_{temporary_scene.scene_index}_temporary_confirmed",
            f"scene_{temporary_scene.scene_index}_temporary_confirmed",
        )
        return SceneGenerationResponse(
            success=True,
            scene=model_to_dict(temporary_scene),
            story_information_summary=self._story_information_summary(temporary_scene),
            quality_report=temporary_scene.quality_report,
            readiness=self.check_scene_generation_ready(
                chapter_id=temporary_scene.chapter_id,
                scene_index=temporary_scene.scene_index,
            ),
            decision=decision,
            progress=self.get_scene_progress(temporary_scene.chapter_id),
        )

    def _commit_revised_scene(
        self,
        scene: Scene,
        revision_id: str | None,
        user_input: str | None = None,
        accepted_abcd_runtime_issue_ids: list[str] | None = None,
    ) -> SceneGenerationResponse:
        revision_id = str(revision_id or scene.active_revision_id or "").strip()
        if not revision_id:
            raise StorageError(
                "SCENE_REVISION_CANDIDATE_MISSING: revision_id is required."
            )
        candidate = next(
            (
                item
                for item in scene.revision_history
                if item.revision_id == revision_id
            ),
            None,
        )
        if candidate is None:
            raise StorageError(
                "SCENE_REVISION_CANDIDATE_MISSING: Revision candidate does not exist."
            )
        if candidate.status != "confirmed":
            raise StorageError(
                "SCENE_REVISION_CANDIDATE_NOT_ACTIVE: Revision must be confirmed by the revision flow before commit."
            )
        self.continuity_gate_service.check_scene(
            scene.scene_id,
            mode="final_confirmation",
        )
        reloaded_scene = self._find_scene_by_id(scene.scene_id)
        if reloaded_scene is not None:
            scene = reloaded_scene
        self._require_abcd_runtime_gate_final(
            scene.scene_id,
            user_confirmation_text=(user_input or "").strip(),
            accepted_issue_ids=accepted_abcd_runtime_issue_ids,
        )
        self.scene_runtime_refresh_state_service.require_confirm_allowed(
            scene.scene_id,
            user_confirmation_text=(user_input or "").strip(),
        )
        self.scene_gate_readiness_service.require_safe_to_confirm(
            scene.scene_id,
            boundary_code="SCENE_GATE_READINESS_BLOCKED",
        )
        revised_scene = Scene(
            **{
                **model_to_dict(scene),
                "status": "revised",
                "prose_status": "generated" if scene.prose_text else scene.prose_status,
                "is_provisional": False,
                "active_revision_id": "",
                "updated_at": now_iso(),
            }
        )
        self.save_confirmed_scene(revised_scene)
        self._attach_scene_to_chapter(revised_scene)
        self._rebuild_tiered_role_memory(revised_scene)
        self._run_abcd_runtime_gate_audit(
            revised_scene.scene_id,
            mode="post_commit_audit",
        )
        decision = self.write_decision(
            target_id=revised_scene.scene_id,
            user_input=(user_input or "").strip()
            or f"确认第 {revised_scene.scene_index} 幕修订版本进入顺序推进。",
            decision_type="confirm_revision",
        )
        self.update_project_step(
            f"scene_{revised_scene.scene_index}_revised",
            f"scene_{revised_scene.scene_index}_revised",
        )
        return SceneGenerationResponse(
            success=True,
            scene=model_to_dict(revised_scene),
            story_information_summary=self._story_information_summary(revised_scene),
            quality_report=revised_scene.quality_report,
            readiness=self.check_scene_generation_ready(
                chapter_id=revised_scene.chapter_id,
                scene_index=revised_scene.scene_index,
            ),
            decision=decision,
            progress=self.get_scene_progress(revised_scene.chapter_id),
        )

    def _write_tiered_role_memory(
        self,
        *,
        scene: Scene,
        commit_type: str,
        events: list[Event],
        state_changes: list[StateChange],
        memory_records: list[MemoryRecord],
    ) -> None:
        try:
            self.role_memory_writeback_service.build_plan_for_committed_scene(
                scene=scene,
                commit_type=commit_type,
                events=events,
                state_changes=state_changes,
                extraction=scene.memory_extraction,
                generic_memory_records=memory_records,
                force_rebuild=True,
            )
        except Exception as exc:
            self._record_tiered_role_memory_failure(
                scene=scene,
                commit_type=commit_type,
                exc=exc,
            )

    def _require_abcd_runtime_gate_final(
        self,
        scene_id: str,
        *,
        user_confirmation_text: str | None = None,
        accepted_issue_ids: list[str] | None = None,
    ) -> None:
        self.abcd_runtime_gate_service.require_final_confirmation_allowed(
            scene_id,
            user_confirmation_text=user_confirmation_text,
            accepted_issue_ids=accepted_issue_ids,
        )

    def _run_abcd_runtime_gate_audit(self, scene_id: str, *, mode: str) -> None:
        try:
            self.abcd_runtime_gate_service.review_scene(
                scene_id,
                mode=mode,
                force_refresh=True,
            )
        except Exception as exc:
            # M9 post/temporary audit is evidence-only here. Final confirmation uses
            # _require_abcd_runtime_gate_final and remains blocking. Audit failures
            # are still persisted as M9 evidence so they cannot disappear silently.
            recorder = getattr(self.abcd_runtime_gate_service, "record_audit_failure", None)
            if callable(recorder):
                try:
                    recorder(scene_id, mode=mode, exc=exc)
                except Exception:
                    logger.exception(
                        "Failed to persist ABCD runtime audit failure for scene %s.",
                        scene_id,
                    )
                    return

    def _rebuild_tiered_role_memory(self, scene: Scene) -> None:
        try:
            self.role_memory_writeback_service.rebuild_write_plan_for_scene(
                scene.scene_id,
                force_rebuild=True,
            )
        except Exception as exc:
            self._record_tiered_role_memory_failure(
                scene=scene,
                commit_type=scene.status,
                exc=exc,
            )

    def _record_tiered_role_memory_failure(
        self,
        *,
        scene: Scene,
        commit_type: str,
        exc: Exception,
    ) -> None:
        recorder = getattr(
            self.role_memory_writeback_service,
            "record_writeback_failure",
            None,
        )
        if not callable(recorder):
            return
        try:
            recorder(
                scene=scene,
                commit_type=commit_type,
                error_message=f"{exc.__class__.__name__}: {str(exc)[:240]}",
            )
        except Exception:
            logger.exception(
                "Failed to persist tiered role memory failure for scene %s.",
                scene.scene_id,
            )
            return

    def check_scene_generation_ready(
        self,
        chapter_id: str | None = None,
        scene_index: int = 1,
    ) -> SceneGenerationReadyStatus:
        issues: list[str] = []
        model_status = self.model_gateway.validate_model_config()
        active_model_configured = model_status.configured
        if not active_model_configured:
            issues.append("Active model is not configured.")

        world_canvas = self._try_read_world_canvas()
        world_canvas_confirmed = world_canvas is not None and world_canvas.status == "confirmed"
        if not world_canvas_confirmed:
            issues.append("WorldCanvas.status must be confirmed.")

        confirmed_characters = self._read_confirmed_a_characters_if_present()
        confirmed_a_character_count = len(confirmed_characters)
        if confirmed_a_character_count < 1:
            issues.append("At least one confirmed A-tier character is required.")

        project = self._read_project_if_present()
        project_step = str((project or {}).get("current_step") or "")
        project_status = str((project or {}).get("status") or "")
        main_cast_step_ready = (
            project_step in ALLOWED_MAIN_CAST_STEPS
            or project_status in ALLOWED_MAIN_CAST_STEPS
            or project_step.startswith("scene_")
            or project_status.startswith("scene_")
        )
        if not main_cast_step_ready:
            issues.append("Project.current_step/status must show main cast is finished.")

        decisions = self._read_decision_dicts()
        main_cast_decision_exists = self._has_confirm_decision(decisions, "main_cast")
        if not main_cast_decision_exists:
            issues.append("Decision(target_type=main_cast) is required.")
        main_cast_finished = (
            confirmed_a_character_count >= 1
            and main_cast_step_ready
            and main_cast_decision_exists
        )

        chapter_plan_step_ready = (
            project_step in ALLOWED_CHAPTER_PLAN_STEPS
            or project_status in ALLOWED_CHAPTER_PLAN_STEPS
            or project_step.startswith("scene_")
            or project_status.startswith("scene_")
        )
        if not chapter_plan_step_ready:
            issues.append("Project.current_step/status must show chapter plan is confirmed.")

        chapter_plan_decision_exists = self._has_confirm_decision(
            decisions,
            "chapter_plan",
        )
        if not chapter_plan_decision_exists:
            issues.append("Decision(target_type=chapter_plan) is required.")

        chapters = self._read_chapters_if_present()
        current_chapter = self._select_current_chapter(chapters, chapter_id)
        current_chapter_exists = current_chapter is not None
        if not current_chapter_exists:
            issues.append("Current Chapter is missing.")

        current_chapter_has_scene_count = (
            current_chapter is not None and current_chapter.scene_count >= scene_index
        )
        if not current_chapter_has_scene_count:
            issues.append("Current Chapter.scene_count must be at least 1.")

        current_chapter_framework_exists = (
            current_chapter is not None and bool(current_chapter.chapter_framework_id)
        )
        if not current_chapter_framework_exists:
            issues.append("Current Chapter.chapter_framework_id is missing.")

        framework_package_ready = False
        current_chapter_framework_built = False
        if self.store.exists(self.framework_package_file):
            validation = self.framework_service.validate_framework_package()
            framework_package_ready = validation.valid
            issues.extend(validation.issues)
            if validation.valid and current_chapter is not None:
                try:
                    package = self.framework_service.get_framework_package()
                    current_chapter_framework_built = (
                        self._find_built_chapter_framework(package, current_chapter)
                        is not None
                    )
                except StorageError as exc:
                    issues.append(str(exc))
        else:
            issues.append("Framework package is missing.")
        if not current_chapter_framework_built:
            issues.append(
                "Current chapter framework must exist in FrameworkPackage.built_chapter_frameworks."
            )

        chapter_plan_confirmed = (
            chapter_plan_step_ready
            and chapter_plan_decision_exists
            and current_chapter_exists
            and current_chapter_has_scene_count
            and current_chapter_framework_exists
            and current_chapter_framework_built
        )

        return SceneGenerationReadyStatus(
            ready=len(issues) == 0,
            active_model_configured=active_model_configured,
            world_canvas_confirmed=world_canvas_confirmed,
            confirmed_a_character_count=confirmed_a_character_count,
            main_cast_step_ready=main_cast_step_ready,
            main_cast_decision_exists=main_cast_decision_exists,
            main_cast_finished=main_cast_finished,
            chapter_plan_step_ready=chapter_plan_step_ready,
            chapter_plan_decision_exists=chapter_plan_decision_exists,
            chapter_plan_confirmed=chapter_plan_confirmed,
            current_chapter_exists=current_chapter_exists,
            current_chapter_has_scene_count=current_chapter_has_scene_count,
            current_chapter_framework_exists=current_chapter_framework_exists,
            current_chapter_framework_built=current_chapter_framework_built,
            framework_package_ready=framework_package_ready,
            issues=self._unique_strings(issues),
        )

    def load_scene_inputs(
        self,
        chapter_id: str | None = None,
        scene_index: int = 1,
        force_refresh_packs: bool = False,
        include_provisional: bool = False,
        scene_id: str | None = None,
        scene_goal: str = "",
        scene_location: str = "",
    ) -> dict[str, Any]:
        readiness = self.check_scene_generation_ready(chapter_id, scene_index)
        if not readiness.ready:
            self._raise_scene_generation_not_ready(readiness)

        world_canvas = self._read_world_canvas()
        relationships = self._read_confirmed_relationships()
        chapters = self._read_chapters()
        chapter = self._select_current_chapter(chapters, chapter_id)
        if chapter is None:
            self._raise_scene_generation_not_ready(readiness)
        package = self.framework_service.get_framework_package()
        current_framework = self._find_built_chapter_framework(package, chapter)
        if current_framework is None:
            self._raise_scene_generation_not_ready(readiness)
        current_chapter_brief_summary = self._current_chapter_brief_summary(chapter)
        chapter_scene_beat = self._chapter_scene_beat_for_scene(chapter, scene_index)
        chapter_scene_beat_history = self._chapter_scene_beat_history(
            chapter,
            scene_index,
        )
        resolved_scene_goal = self._resolve_current_scene_goal(
            chapter,
            scene_index,
            explicit_scene_goal=scene_goal,
            brief_summary=current_chapter_brief_summary,
            chapter_scene_beat=chapter_scene_beat,
        )
        project_intent_summary = self._project_intent_summary(
            world_canvas=world_canvas,
            chapter=chapter,
        )
        beat_anchors = (
            chapter_scene_beat.get("continuity_anchors")
            if isinstance(chapter_scene_beat, dict)
            else {}
        )
        if not isinstance(beat_anchors, dict):
            beat_anchors = {}
        required_memory_refs = self._unique_strings(
            [
                str(value or "")
                for value in safe_list(beat_anchors.get("required_memory_refs"))
            ]
        )

        participation_response = self.scene_participation_service.prepare_package(
            SceneParticipationPrepareRequest(
                chapter_id=chapter.chapter_id,
                scene_index=scene_index,
                scene_id=scene_id,
                scene_goal=resolved_scene_goal,
                scene_location=scene_location,
                required_memory_refs=required_memory_refs,
                include_provisional=include_provisional,
                force_refresh=force_refresh_packs,
            )
        )
        participation_package = participation_response.package
        participation_readiness = participation_response.readiness
        if (
            participation_readiness is not None
            and not participation_readiness.ready
        ):
            self._raise_scene_participation_confirmation_required(
                participation_readiness
            )
        active_character_ids = (
            participation_package.active_character_ids
            if participation_package is not None
            else []
        )
        characters = self._read_confirmed_characters_by_ids(active_character_ids)
        scene_pack = participation_response.scene_memory_pack
        scene_pack_data = model_to_dict(scene_pack) if scene_pack is not None else None
        memory_context = self._memory_context_from_scene_pack(scene_pack_data)
        character_context = (
            model_to_dict(participation_response.tiered_character_context_package)
            if participation_response.tiered_character_context_package is not None
            else {"items": [], "warnings": ["tiered_character_context_package_missing"]}
        )
        generator_framework_context = self._read_generator_framework_context()
        current_chapter_framework = self._chapter_framework_payload_with_generator_context(
            current_framework,
            generator_framework_context,
        )

        return {
            "project_id": self._current_project_id(),
            "scene_index": scene_index,
            "scene_count": chapter.scene_count,
            "world_canvas": model_to_dict(world_canvas),
            "project_intent_summary": project_intent_summary,
            "characters": [model_to_dict(character) for character in characters],
            "relationships": [
                model_to_dict(relationship) for relationship in relationships
            ],
            "chapter": model_to_dict(chapter),
            "chapter_scene_beat": chapter_scene_beat,
            "chapter_scene_beat_history": chapter_scene_beat_history,
            "resolved_scene_goal": resolved_scene_goal,
            "current_chapter_brief_summary": current_chapter_brief_summary,
            "current_chapter_framework": current_chapter_framework,
            "generator_framework_context": self._compact_generator_framework_context(
                generator_framework_context
            ),
            "framework_package": model_to_dict(package),
            "recent_events": self._read_list_if_present(self.events_file),
            "character_context": character_context,
            "scene_participation_package": (
                model_to_dict(participation_package)
                if participation_package is not None
                else None
            ),
            "scene_participation_readiness": (
                model_to_dict(participation_readiness)
                if participation_readiness is not None
                else None
            ),
            "tiered_character_context_package": character_context,
            **memory_context,
        }

    def _project_intent_summary(
        self,
        *,
        world_canvas: WorldCanvas,
        chapter: Chapter,
    ) -> str:
        project_id = self._current_project_id()
        try:
            premise = self.project_story_premise_service.read_for_project(project_id)
        except Exception:
            premise = None
            logger.exception(
                "Failed to read project story premise for scene generation context."
            )
        if premise is not None:
            summary = (
                premise.safe_user_story_summary
                or premise.user_story_premise[:360]
            ).strip()
            if summary:
                return summary
        fallback_parts = [
            world_canvas.story_direction,
            world_canvas.scope,
            world_canvas.tone,
            chapter.chapter_goal,
            chapter.summary,
        ]
        summary = " / ".join(
            str(part).strip() for part in fallback_parts if str(part or "").strip()
        )
        return summary[:720] or "Project intent is unavailable; follow the confirmed world canvas and current chapter goal only."

    def _project_story_premise_for_scene_writer(self, project_id: str):
        return require_project_story_premise_for_generation(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            missing_code=SCENE_WRITER_PROJECT_STORY_PREMISE_MISSING,
            project_file=self.project_file,
        )

    def _build_scene_writing_context(
        self,
        *,
        context: dict[str, Any],
        chapter: Chapter,
        scene_id: str,
        scene_index: int,
    ) -> SceneWritingContext:
        project_id = str(context.get("project_id") or self._current_project_id())
        premise = self._project_story_premise_for_scene_writer(project_id)
        premise_payload = model_to_dict(premise) if premise is not None else {}
        required_terms = premise_required_terms(premise, limit=32)
        confirmed_summaries = self._confirmed_scene_summaries(
            chapter_id=chapter.chapter_id,
            before_scene_index=scene_index,
        )
        story_summaries = self._confirmed_story_summaries_before(
            chapter=chapter,
            before_scene_index=scene_index,
        )
        repetition_history = story_summaries or confirmed_summaries
        previous_summary = (
            repetition_history[-1].get("safe_summary", "")
            if repetition_history
            else ""
        )
        chapter_state = self._chapter_state_so_far(
            confirmed_summaries,
            story_summaries=story_summaries,
        )
        forbidden_patterns = self._forbidden_repetition_patterns(
            repetition_history,
            context=context,
        )
        scene_pack = context.get("scene_memory_pack") or {}
        participation = context.get("scene_participation_package") or {}
        selected_ids = self._unique_strings(
            [
                *[
                    str(character.get("character_id") or "")
                    for character in context.get("characters", [])
                    if isinstance(character, dict)
                ],
                *(
                    participation.get("active_character_ids", [])
                    if isinstance(participation, dict)
                    else []
                ),
            ]
        )
        source_refs = [
            f"project:{project_id}",
            f"chapter:{chapter.chapter_id}",
            f"scene:{scene_id}",
        ]
        if premise is not None:
            source_refs.append(f"project_story_premise:{premise.project_id}")
        if isinstance(scene_pack, dict) and scene_pack.get("scene_memory_pack_id"):
            source_refs.append(f"scene_memory_pack:{scene_pack['scene_memory_pack_id']}")
        if isinstance(participation, dict) and participation.get("scene_participation_package_id"):
            source_refs.append(
                f"scene_participation_package:{participation['scene_participation_package_id']}"
            )
        chapter_scene_beat = dict(context.get("chapter_scene_beat") or {})
        chapter_scene_beat_history = [
            dict(item)
            for item in safe_list(context.get("chapter_scene_beat_history"))
            if isinstance(item, dict)
        ][:8]
        beat_id = str(chapter_scene_beat.get("beat_id") or "").strip()
        beat_chapter_id = str(
            chapter_scene_beat.get("chapter_id") or chapter.chapter_id
        ).strip()
        if beat_id:
            source_refs.append(f"chapter_scene_beat:{beat_id}")
        if beat_chapter_id and chapter_scene_beat_history:
            source_refs.append(f"chapter_scene_beats:chapter:{beat_chapter_id}")
        generator_framework_context = self._compact_generator_framework_context(
            context.get("generator_framework_context") or {}
        )
        framework_composition_id = self._framework_composition_id(
            generator_framework_context
        )
        framework_context_source_refs = self._framework_context_source_refs(
            generator_framework_context
        )
        if framework_composition_id:
            source_refs.append(f"framework_composition:{framework_composition_id}")
        source_refs.extend(framework_context_source_refs)

        return SceneWritingContext(
            project_id=project_id,
            chapter_id=chapter.chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
            scene_count=chapter.scene_count,
            project_story_premise=premise_payload,
            prompt_fidelity_contract={
                **(
                    model_to_dict(premise.prompt_fidelity_contract)
                    if premise is not None
                    else {}
                ),
                "required_terms": required_terms,
            },
            chapter_goal=chapter.chapter_goal or chapter.summary,
            current_chapter_brief_summary=str(
                context.get("current_chapter_brief_summary") or ""
            ),
            chapter_scene_beat=chapter_scene_beat,
            chapter_scene_beat_history=chapter_scene_beat_history,
            current_chapter_framework=dict(
                context.get("current_chapter_framework") or {}
            ),
            framework_composition_id=framework_composition_id,
            framework_context_source_refs=framework_context_source_refs,
            generator_framework_context=generator_framework_context,
            resolved_scene_goal=str(context.get("resolved_scene_goal") or ""),
            previous_scene_summary=previous_summary,
            confirmed_scene_summaries=confirmed_summaries,
            chapter_state_so_far=chapter_state,
            selected_abcd_participants=selected_ids,
            scene_participation_package=participation if isinstance(participation, dict) else {},
            tiered_character_context_package=dict(
                context.get("tiered_character_context_package") or {}
            ),
            tiered_character_intent_package=self._latest_tiered_character_intent_package(
                chapter_id=chapter.chapter_id,
                scene_index=scene_index,
            ),
            scene_memory_pack=scene_pack if isinstance(scene_pack, dict) else {},
            authorial_intent=dict(context.get("authorial_intent") or {}),
            forbidden_repetition_patterns=forbidden_patterns,
            source_refs=self._unique_strings(source_refs),
        )

    def _build_scene_progression_statement(
        self,
        *,
        writing_context: SceneWritingContext,
        scene_information: dict[str, Any],
        ordered_package: OrderedStoryInformationPackage,
    ) -> SceneProgressionStatement:
        prompt_terms = self._scene_required_prompt_terms(writing_context)[:16]
        chapter_scene_beat = dict(writing_context.chapter_scene_beat or {})
        beat_progression = chapter_scene_beat.get("required_progression_delta") or {}
        if not isinstance(beat_progression, dict):
            beat_progression = {}
        beat_anchors = chapter_scene_beat.get("continuity_anchors") or {}
        if not isinstance(beat_anchors, dict):
            beat_anchors = {}
        scene_goal = scene_information.get("scene_goal") or {}
        scene_objective = self._short_context_text(
            str(
                chapter_scene_beat.get("scene_function")
                or scene_goal.get("summary")
                or writing_context.resolved_scene_goal
                or (ordered_package.scene_progression[0] if ordered_package.scene_progression else "")
            ),
            max_len=700,
        )
        scene_objective = self._story_facing_text(scene_objective)
        if (
            not scene_objective
            or self._is_generic_scene_objective(scene_objective)
            or self._progression_objective_seen(scene_objective, writing_context)
        ):
            scene_objective = self._fallback_scene_objective(
                writing_context,
                prompt_terms=prompt_terms,
            )
        first_character_id = (
            writing_context.selected_abcd_participants[0]
            if writing_context.selected_abcd_participants
            else ""
        )
        new_information = self._short_context_text(
            (
                beat_progression.get("new_information")
                or (
                    ordered_package.required_reveals[0]
                    if ordered_package.required_reveals
                    else ""
                )
                if ordered_package.required_reveals
                else beat_progression.get("new_information")
                or (
                    f"Scene {writing_context.scene_index} adds a new actionable clue tied to "
                    f"{prompt_terms[0] if prompt_terms else 'the active premise'}."
                )
            ),
            max_len=500,
        )
        new_information = self._story_facing_text(new_information) or (
            f"Scene {writing_context.scene_index} adds one new actionable clue."
        )
        character_state_delta = self._short_context_text(
            str(beat_progression.get("character_state_delta") or "")
            or self._character_state_delta_hint(
                writing_context=writing_context,
                first_character_id=first_character_id,
            ),
            max_len=500,
        )
        character_state_delta = self._story_facing_text(character_state_delta) or (
            "An active participant leaves the scene with a changed pressure or choice."
        )
        conflict_turn = self._short_context_text(
            (
                beat_progression.get("conflict_turn")
                or ordered_package.scene_progression[0]
                if ordered_package.scene_progression
                else beat_progression.get("conflict_turn")
                or writing_context.resolved_scene_goal
            ),
            max_len=500,
        )
        conflict_turn = self._story_facing_text(conflict_turn) or scene_objective
        difference = self._short_context_text(
            self._difference_from_previous_scene(writing_context, scene_objective),
            max_len=500,
        )
        difference = self._story_facing_text(difference) or (
            "This scene must not replay the previous confirmed scene."
        )
        required_memory_refs = self._unique_strings(
            [
                str(value or "")
                for value in safe_list(beat_anchors.get("required_memory_refs"))
            ]
        )
        source_refs = self._unique_strings(
            [
                *writing_context.source_refs,
                *[
                    str(value or "")
                    for value in safe_list(chapter_scene_beat.get("source_refs"))
                ],
                (
                    f"chapter_scene_beat:{chapter_scene_beat.get('beat_id')}"
                    if chapter_scene_beat.get("beat_id")
                    else ""
                ),
            ]
        )
        return SceneProgressionStatement(
            scene_objective=scene_objective,
            new_information=new_information,
            character_state_delta=character_state_delta,
            conflict_turn=conflict_turn,
            difference_from_previous_scene=difference,
            required_prompt_terms=prompt_terms,
            required_character_ids=writing_context.selected_abcd_participants,
            required_memory_refs=required_memory_refs,
            source_refs=source_refs,
        )

    def _scene_required_prompt_terms(
        self,
        writing_context: SceneWritingContext,
    ) -> list[str]:
        contract = writing_context.prompt_fidelity_contract or {}
        premise_payload = writing_context.project_story_premise or {}
        forbidden_markers = contract.get("forbidden_markers") or []
        prompt_terms = classify_prompt_anchor_values(
            [
                premise_payload.get("user_story_premise"),
                premise_payload.get("safe_user_story_summary"),
                contract.get("required_markers") or [],
            ],
            limit=16,
            forbidden_values=forbidden_markers,
        ).positive_required_anchors
        if prompt_terms:
            return prompt_terms
        return classify_prompt_anchor_values(
            [
                *safe_list(
                    writing_context.project_story_premise.get(
                        "prompt_markers_detected"
                    )
                ),
                *safe_list(writing_context.project_story_premise.get("core_terms")),
                *safe_list(writing_context.project_story_premise.get("setting_terms")),
                *safe_list(writing_context.project_story_premise.get("conflict_terms")),
                *safe_list(writing_context.project_story_premise.get("role_terms")),
            ],
            limit=16,
            forbidden_values=forbidden_markers,
        ).positive_required_anchors

    def _fallback_scene_objective(
        self,
        writing_context: SceneWritingContext,
        *,
        prompt_terms: list[str],
    ) -> str:
        term = prompt_terms[0] if prompt_terms else "the active project premise"
        phase_templates = [
            "Scene 1 opens the active premise by locating a first concrete clue tied to {term}.",
            "Scene 2 tests the first clue through a different participant choice tied to {term}.",
            "Scene 3 turns the investigation by exposing a cost or contradiction around {term}.",
            "Scene 4 escalates the conflict through a consequence that changes participant pressure around {term}.",
            "Scene 5 forces a chapter-level decision that carries {term} into the next story beat.",
        ]
        index = max(1, int(writing_context.scene_index or 1))
        if index <= len(phase_templates):
            return phase_templates[index - 1].format(term=term)
        return (
            f"Scene {index} advances a distinct consequence tied to {term} "
            "without replaying earlier scene objectives."
        )

    def _is_generic_scene_objective(self, value: str) -> bool:
        return (
            self._normalize_progression_text(value)
            == self._normalize_progression_text(GENERIC_SCENE_PROGRESSION_OBJECTIVE)
        )

    def _progression_objective_seen(
        self,
        objective: str,
        writing_context: SceneWritingContext,
    ) -> bool:
        objective_norm = self._normalize_progression_text(objective)
        if not objective_norm:
            return False
        for previous in self._previous_progression_objectives(writing_context):
            previous_norm = self._normalize_progression_text(previous)
            if previous_norm and objective_norm == previous_norm:
                return True
        return False

    def _previous_progression_objectives(
        self,
        writing_context: SceneWritingContext,
    ) -> list[str]:
        state = writing_context.chapter_state_so_far or {}
        return self._unique_strings(
            [
                *[
                    str(value or "")
                    for value in state.get("recent_scene_progression_objectives", [])
                ],
                *[str(value or "") for value in state.get("recent_scene_goals", [])],
            ]
        )

    def _attach_progression_to_ordered_package(
        self,
        ordered_package: OrderedStoryInformationPackage,
        progression: SceneProgressionStatement,
        writing_context: SceneWritingContext,
    ) -> OrderedStoryInformationPackage:
        updated = OrderedStoryInformationPackage(**model_to_dict(ordered_package))
        progression_lines = [
            progression.scene_objective,
            progression.new_information,
            progression.character_state_delta,
            progression.conflict_turn,
            progression.difference_from_previous_scene,
        ]
        updated.scene_progression = self._unique_strings(
            [line for line in progression_lines if line]
            + list(updated.scene_progression)
        )
        beat = writing_context.chapter_scene_beat or {}
        ending_hook = self._short_context_text(
            str(beat.get("ending_hook_requirement") or ""),
            max_len=400,
        )
        if ending_hook:
            updated.ending_beat = self._unique_strings(
                [ending_hook] + list(updated.ending_beat)
            )
        avoid_axes = [
            str(value or "").strip()
            for value in safe_list(beat.get("avoid_repetition_axes"))
            if str(value or "").strip()
        ]
        updated.do_not_include = self._unique_strings(
            list(updated.do_not_include)
            + avoid_axes
            + list(writing_context.forbidden_repetition_patterns)
        )
        return updated

    def _confirmed_scene_summaries(
        self,
        *,
        chapter_id: str,
        before_scene_index: int,
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for item in self._read_list_if_present(self.scenes_file):
            if not isinstance(item, dict):
                continue
            if item.get("chapter_id") != chapter_id:
                continue
            try:
                scene_index = int(item.get("scene_index") or 0)
            except (TypeError, ValueError):
                continue
            if scene_index >= before_scene_index:
                continue
            if str(item.get("status") or "") not in NEXT_READY_SCENE_STATUSES:
                continue
            content = item.get("content") or {}
            synopsis = str(content.get("synopsis") or item.get("synopsis") or "").strip()
            prose_text = str(
                content.get("prose_text") or item.get("prose_text") or ""
            ).strip()
            extraction = item.get("memory_extraction") or {}
            events = extraction.get("event_summary") or []
            state_changes = extraction.get("proposed_state_changes") or []
            event_summary = " ".join(
                str(event.get("summary") or event.get("event_summary") or "")
                for event in events
                if isinstance(event, dict)
            )
            state_summary = " ".join(
                str(change.get("summary") or change.get("change_summary") or "")
                for change in state_changes
                if isinstance(change, dict)
            )
            goal = str(item.get("goal") or "").strip()
            trace = item.get("generation_trace") or {}
            progression_statement = (
                trace.get("scene_progression_statement")
                if isinstance(trace, dict)
                else {}
            ) or {}
            progression_objective = str(
                progression_statement.get("scene_objective") or ""
            ).strip()
            safe_summary = self._short_context_text(
                " ".join(
                    part
                    for part in [
                        f"Scene {scene_index}",
                        goal,
                        synopsis,
                        event_summary,
                        state_summary,
                    ]
                    if part
                ),
                max_len=1000,
            )
            summaries.append(
                {
                    "scene_id": str(item.get("scene_id") or ""),
                    "chapter_id": str(item.get("chapter_id") or ""),
                    "scene_index": scene_index,
                    "status": str(item.get("status") or ""),
                    "goal": goal,
                    "progression_objective": self._short_context_text(
                        progression_objective,
                        max_len=700,
                    ),
                    "synopsis": self._short_context_text(synopsis, max_len=500),
                    "safe_summary": safe_summary,
                    "event_summary": self._short_context_text(event_summary, max_len=500),
                    "state_change_summary": self._short_context_text(
                        state_summary,
                        max_len=500,
                    ),
                    "prose_fragment": self._short_context_text(
                        prose_text,
                        max_len=1800,
                    ),
                }
            )
        return sorted(summaries, key=lambda summary: summary["scene_index"])

    def _confirmed_story_summaries_before(
        self,
        *,
        chapter: Chapter,
        before_scene_index: int,
    ) -> list[dict[str, Any]]:
        chapter_orders: dict[str, int] = {}
        for item in self._read_list_if_present(self.chapters_file):
            if not isinstance(item, dict) or not str(item.get("chapter_id") or "").strip():
                continue
            try:
                chapter_orders[str(item.get("chapter_id") or "")] = int(
                    item.get("chapter_index") or 0
                )
            except (TypeError, ValueError):
                continue
        current_order = chapter_orders.get(chapter.chapter_id)
        if not current_order:
            try:
                current_order = max(1, int(getattr(chapter, "chapter_index", 1) or 1))
            except (TypeError, ValueError):
                current_order = 1
        summaries: list[dict[str, Any]] = []
        for item in self._read_list_if_present(self.scenes_file):
            if not isinstance(item, dict):
                continue
            item_chapter_id = str(item.get("chapter_id") or "")
            item_order = chapter_orders.get(item_chapter_id)
            if not item_order:
                item_order = current_order if item_chapter_id == chapter.chapter_id else 0
            try:
                scene_index = int(item.get("scene_index") or 0)
            except (TypeError, ValueError):
                continue
            if item_order > current_order:
                continue
            if item_order == current_order and scene_index >= before_scene_index:
                continue
            if str(item.get("status") or "") not in NEXT_READY_SCENE_STATUSES:
                continue
            content = item.get("content") or {}
            synopsis = str(content.get("synopsis") or item.get("synopsis") or "").strip()
            prose_text = str(
                content.get("prose_text") or item.get("prose_text") or ""
            ).strip()
            extraction = item.get("memory_extraction") or {}
            events = extraction.get("event_summary") or []
            state_changes = extraction.get("proposed_state_changes") or []
            event_summary = " ".join(
                str(event.get("summary") or event.get("event_summary") or "")
                for event in events
                if isinstance(event, dict)
            )
            state_summary = " ".join(
                str(change.get("summary") or change.get("change_summary") or "")
                for change in state_changes
                if isinstance(change, dict)
            )
            goal = str(item.get("goal") or "").strip()
            trace = item.get("generation_trace") or {}
            progression_statement = (
                trace.get("scene_progression_statement")
                if isinstance(trace, dict)
                else {}
            ) or {}
            progression_objective = str(
                progression_statement.get("scene_objective") or ""
            ).strip()
            safe_summary = self._short_context_text(
                " ".join(
                    part
                    for part in [
                        f"Chapter {item_order}",
                        f"Scene {scene_index}",
                        goal,
                        synopsis,
                        event_summary,
                        state_summary,
                    ]
                    if part
                ),
                max_len=1000,
            )
            summaries.append(
                {
                    "scene_id": str(item.get("scene_id") or ""),
                    "chapter_id": item_chapter_id,
                    "chapter_index": item_order,
                    "scene_index": scene_index,
                    "status": str(item.get("status") or ""),
                    "goal": goal,
                    "progression_objective": self._short_context_text(
                        progression_objective,
                        max_len=700,
                    ),
                    "synopsis": self._short_context_text(synopsis, max_len=500),
                    "safe_summary": safe_summary,
                    "event_summary": self._short_context_text(event_summary, max_len=500),
                    "state_change_summary": self._short_context_text(
                        state_summary,
                        max_len=500,
                    ),
                    "prose_fragment": self._short_context_text(
                        prose_text,
                        max_len=1800,
                    ),
                }
            )
        return sorted(
            summaries,
            key=lambda summary: (
                int(summary.get("chapter_index") or 0),
                int(summary.get("scene_index") or 0),
            ),
        )

    def _chapter_state_so_far(
        self,
        confirmed_summaries: list[dict[str, Any]],
        *,
        story_summaries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        story_history = story_summaries or confirmed_summaries
        recent = story_history[-3:]
        return {
            "confirmed_scene_count": len(confirmed_summaries),
            "latest_scene_index": (
                confirmed_summaries[-1]["scene_index"] if confirmed_summaries else 0
            ),
            "recent_scene_ids": [
                str(summary.get("scene_id") or "") for summary in recent
            ],
            "recent_scene_summaries": [
                str(summary.get("safe_summary") or "") for summary in recent
            ],
            "recent_scene_goals": [
                str(summary.get("goal") or "") for summary in recent
            ],
            "recent_scene_progression_objectives": [
                str(summary.get("progression_objective") or "")
                for summary in recent
                if summary.get("progression_objective")
            ],
            "recent_scene_prose_fragments": [
                str(summary.get("prose_fragment") or "") for summary in recent
            ],
            "accumulated_reveals": [
                str(summary.get("event_summary") or "")
                for summary in story_history
                if summary.get("event_summary")
            ][-8:],
            "changed_character_states": [
                str(summary.get("state_change_summary") or "")
                for summary in story_history
                if summary.get("state_change_summary")
            ][-8:],
        }

    def _forbidden_repetition_patterns(
        self,
        confirmed_summaries: list[dict[str, Any]],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        patterns: list[str] = []
        for summary in confirmed_summaries[-3:]:
            patterns.extend(
                [
                    str(summary.get("goal") or ""),
                    str(summary.get("synopsis") or ""),
                    str(summary.get("event_summary") or ""),
                    str(summary.get("state_change_summary") or ""),
                ]
            )
            prose = str(summary.get("prose_fragment") or "")
            if prose:
                patterns.append(prose[:180])
                patterns.append(prose[-180:])
        patterns.append(str(context.get("resolved_scene_goal") or ""))
        return [
            self._short_context_text(pattern, max_len=240)
            for pattern in self._unique_strings(patterns)
            if len(str(pattern or "").strip()) >= 12
        ][:16]

    def _latest_tiered_character_intent_package(
        self,
        *,
        chapter_id: str,
        scene_index: int,
    ) -> dict[str, Any]:
        path = self.data_dir / "tiered_character_intent_packages.json"
        packages: list[dict[str, Any]] = []
        for item in self._read_list_if_present(path):
            if not isinstance(item, dict) or item.get("chapter_id") != chapter_id:
                continue
            try:
                item_scene_index = int(item.get("scene_index") or 0)
            except (TypeError, ValueError):
                continue
            if item_scene_index == scene_index:
                packages.append(item)
        if not packages:
            return {"status": "not_available"}
        packages.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
        latest = dict(packages[-1])
        return {
            "status": latest.get("status") or "unknown",
            "tiered_character_intent_package_id": latest.get(
                "tiered_character_intent_package_id",
                "",
            ),
            "active_character_ids": latest.get("active_character_ids", []),
            "writer_ready_candidate_ids": latest.get("writer_ready_candidate_ids", []),
            "blocked_candidate_ids": latest.get("blocked_candidate_ids", []),
            "needs_gate_candidate_ids": latest.get("needs_gate_candidate_ids", []),
            "safe_summary": latest.get("safe_summary", ""),
        }

    def _character_state_delta_hint(
        self,
        *,
        writing_context: SceneWritingContext,
        first_character_id: str,
    ) -> str:
        context_items = safe_list(
            (writing_context.tiered_character_context_package or {}).get("items")
        )
        for item in context_items:
            if not isinstance(item, dict):
                continue
            if first_character_id and item.get("character_id") != first_character_id:
                continue
            summary = str(
                item.get("safe_summary")
                or item.get("context_summary")
                or item.get("memory_summary")
                or ""
            ).strip()
            if summary:
                return (
                    f"{first_character_id or 'active_character'} changes stance from "
                    f"the prior context instead of repeating it: {summary}"
                )
        if first_character_id:
            return (
                f"{first_character_id} must leave this scene with a new pressure, "
                "choice, or knowledge boundary compared with the previous scene."
            )
        return "At least one active participant must leave this scene with a changed pressure or choice."

    def _difference_from_previous_scene(
        self,
        writing_context: SceneWritingContext,
        scene_objective: str,
    ) -> str:
        previous = writing_context.previous_scene_summary.strip()
        if not previous:
            return (
                "This is the first active scene in the chapter; establish a new "
                "entry point without importing demo defaults or prior chapter endings."
            )
        return (
            "Do not replay the previous confirmed scene. Previous scene summary: "
            f"{previous[:360]} Current scene must advance: {scene_objective[:360]}"
        )

    def _inspect_scene_progression(
        self,
        *,
        content: SceneDraftContent,
        writing_context: SceneWritingContext,
        progression: SceneProgressionStatement | None,
    ) -> SceneProgressionInspection:
        warnings: list[str] = []
        blocking: list[str] = []
        if progression is None:
            blocking.append(SCENE_PROGRESSION_STATEMENT_MISSING)
            progression = SceneProgressionStatement()
        if not progression.scene_objective.strip():
            blocking.append(SCENE_PROGRESSION_MISSING)
        if not progression.new_information.strip() or not progression.conflict_turn.strip():
            blocking.append(SCENE_PROGRESSION_MISSING)
        if not progression.character_state_delta.strip():
            blocking.append(SCENE_STATE_DELTA_MISSING)
        if writing_context.scene_index > 1 and not writing_context.previous_scene_summary.strip():
            blocking.append(SCENE_PREVIOUS_SUMMARY_MISSING)

        previous_goals = self._previous_progression_objectives(writing_context)
        objective_norm = self._normalize_progression_text(progression.scene_objective)
        if objective_norm and any(
            objective_norm == self._normalize_progression_text(goal)
            for goal in previous_goals
        ):
            blocking.append(SCENE_OBJECTIVE_REPEATED)
            blocking.append(SCENE_PROGRESSION_STATEMENT_REPEATED)

        story_text = f"{content.synopsis}\n{content.prose_text}"
        recent_fragments = [
            str(fragment or "")
            for fragment in (writing_context.chapter_state_so_far or {}).get(
                "recent_scene_prose_fragments",
                [],
            )
            if str(fragment or "").strip()
        ]
        adjacent_similarity = (
            self._text_similarity(story_text, recent_fragments[-1])
            if recent_fragments
            else 0.0
        )
        last_three_similarity = max(
            [self._text_similarity(story_text, fragment) for fragment in recent_fragments],
            default=0.0,
        )

        pattern_report = ScenePatternSimilarityGateService().inspect_draft(
            content=content,
            writing_context=writing_context,
            progression=progression,
        )
        pattern_codes = [
            finding.code
            for finding in pattern_report.findings
            if finding.code
        ]
        text_similarity_high = (
            adjacent_similarity > SCENE_ADJACENT_SIMILARITY_BLOCK_THRESHOLD
            or last_three_similarity > SCENE_LAST_THREE_SIMILARITY_BLOCK_THRESHOLD
        )
        text_near_copy = (
            max(adjacent_similarity, last_three_similarity)
            >= SCENE_NEAR_COPY_SIMILARITY_BLOCK_THRESHOLD
        )
        text_exact_copy = (
            max(adjacent_similarity, last_three_similarity)
            >= SCENE_EXACT_COPY_SIMILARITY_BLOCK_THRESHOLD
        )
        no_comparison_repetition_risk = (
            not self._pattern_report_has_comparisons(pattern_report)
            and not self._pattern_report_has_strong_progression(pattern_report)
        )
        if text_similarity_high and (
            no_comparison_repetition_risk
            or pattern_report.verdict == "block_auto_repair"
            or text_exact_copy
            or (
                text_near_copy
                and not self._pattern_report_has_meaningful_progression(pattern_report)
            )
        ):
            blocking.append(SCENE_REPETITION_TOO_HIGH)

        prompt_terms = self._unique_strings(progression.required_prompt_terms)
        prompt_terms_seen = [
            term
            for term in prompt_terms
            if self._contains_term(story_text, term)
        ]
        if prompt_terms and not prompt_terms_seen:
            blocking.append(SCENE_PROMPT_FIDELITY_MISSING)
        elif prompt_terms and len(prompt_terms_seen) < min(2, len(prompt_terms)):
            warnings.append(SCENE_PROMPT_FIDELITY_WEAK)

        demo_default_count = sum(
            story_text.count(default)
            for default in FORBIDDEN_DEMO_DEFAULTS
            if default
        )
        if demo_default_count:
            blocking.append(SCENE_DEMO_DEFAULT_LEAK)

        if pattern_report.verdict == "block_auto_repair":
            blocking.extend(pattern_codes)
        elif pattern_report.verdict == "warn_auto_repair":
            warnings.extend(pattern_codes)

        blocking = self._unique_strings(blocking)
        warnings = self._unique_strings(
            [warning for warning in warnings if warning not in blocking]
        )
        return SceneProgressionInspection(
            passed=not blocking,
            warnings=warnings,
            blocking_issues=blocking,
            adjacent_similarity=round(adjacent_similarity, 4),
            last_three_similarity=round(last_three_similarity, 4),
            prompt_terms_seen=prompt_terms_seen,
            demo_default_count=demo_default_count,
            scene_pattern_signature=model_to_dict(pattern_report.current_signature),
            scene_pattern_similarity_report=model_to_dict(pattern_report),
            pattern_verdict=pattern_report.verdict,
            pattern_finding_codes=self._unique_strings(pattern_codes),
        )

    def _pattern_report_has_comparisons(self, pattern_report: Any) -> bool:
        return bool(getattr(pattern_report, "compared_signature_ids", None))

    def _pattern_report_has_strong_progression(self, pattern_report: Any) -> bool:
        signature = getattr(pattern_report, "current_signature", None)
        if signature is None:
            return False
        has_story_turn = all(
            bool(getattr(signature, field, False))
            for field in (
                "has_new_information",
                "has_character_state_delta",
                "has_conflict_turn",
            )
        )
        has_cost_or_hook = bool(
            getattr(signature, "has_cost_or_risk_delta", False)
            or getattr(signature, "has_distinct_ending_hook", False)
        )
        return has_story_turn and has_cost_or_hook

    def _pattern_report_has_meaningful_progression(self, pattern_report: Any) -> bool:
        signature = getattr(pattern_report, "current_signature", None)
        if signature is None:
            return False
        return any(
            bool(getattr(signature, field, False))
            for field in (
                "has_new_information",
                "has_character_state_delta",
                "has_conflict_turn",
                "has_cost_or_risk_delta",
            )
        )

    def _merge_progression_inspection_quality(
        self,
        report: SceneQualityReport,
        inspection: SceneProgressionInspection | None,
    ) -> SceneQualityReport:
        if inspection is None:
            return report
        visible_inspection_warnings = [
            warning
            for warning in inspection.warnings
            if warning not in SCENE_PATTERN_HIDDEN_CODES
        ]
        visible_inspection_blocking = [
            issue
            for issue in inspection.blocking_issues
            if issue not in SCENE_PATTERN_HIDDEN_CODES
        ]
        hidden_pattern_blocking = any(
            issue in SCENE_PATTERN_HIDDEN_CODES for issue in inspection.blocking_issues
        )
        warnings = self._unique_strings(list(report.warnings) + visible_inspection_warnings)
        blocking = self._unique_strings(
            list(report.blocking_issues) + visible_inspection_blocking
        )
        summary = report.summary
        if inspection.blocking_issues:
            summary = summary or "Scene progression/repetition gate blocked this draft."
        elif inspection.warnings:
            summary = summary or "Scene progression/repetition gate produced warnings."
        return SceneQualityReport(
            quality_report_id=report.quality_report_id,
            passed=len(blocking) == 0 and not hidden_pattern_blocking and report.passed,
            warnings=warnings,
            blocking_issues=blocking,
            requires_user_confirmation=report.requires_user_confirmation,
            continuity_checked=report.continuity_checked,
            continuity_gate_run_id=report.continuity_gate_run_id,
            continuity_checked_at=report.continuity_checked_at,
            continuity_passed=report.continuity_passed,
            continuity_issue_ids=list(report.continuity_issue_ids),
            blocking_continuity_issue_ids=list(
                report.blocking_continuity_issue_ids
            ),
            accepted_continuity_issue_ids=list(
                report.accepted_continuity_issue_ids
            ),
            semantic_check_status=report.semantic_check_status,
            summary=summary,
            quality_degraded=report.quality_degraded,
            confirmation_block_reason=(
                report.confirmation_block_reason
                or (
                    "scene_progression_or_repetition_gate_blocked"
                    if blocking
                    else ""
                )
            ),
        )

    def _normalize_progression_text(self, value: str) -> str:
        return re.sub(
            r"[\s\u3000,.;:!?，。；：！？\"'`（）()\[\]{}<>《》]+",
            "",
            str(value or "").casefold(),
        )

    def _text_similarity(self, left: str, right: str) -> float:
        left_norm = self._normalize_progression_text(left)[:2400]
        right_norm = self._normalize_progression_text(right)[:2400]
        if not left_norm or not right_norm:
            return 0.0
        return SequenceMatcher(None, left_norm, right_norm).ratio()

    def _contains_term(self, text: str, term: str) -> bool:
        clean = str(term or "").strip()
        if not clean:
            return False
        return clean.casefold() in str(text or "").casefold()

    def generate_scene_information(
        self,
        context: dict[str, Any],
        regeneration_hint: str = "",
    ) -> dict[str, Any]:
        scene_information = self.scene_information_agent.generate_scene_information(
            context=context,
            regeneration_hint=regeneration_hint,
        )
        return self._apply_resolved_scene_goal(
            self._normalize_scene_information(scene_information),
            context,
        )

    def _fallback_scene_information(
        self,
        *,
        context: dict[str, Any],
        scene_index: int,
        exc: Exception,
    ) -> dict[str, Any]:
        chapter = context.get("chapter") or {}
        framework = context.get("current_chapter_framework") or {}
        scene_pack = context.get("scene_memory_pack") or {}
        scene_goal = str(
            context.get("resolved_scene_goal")
            or chapter.get("chapter_goal")
            or chapter.get("summary")
            or f"Scene {scene_index} requires regeneration before it can become story prose."
        ).strip()
        location = str(
            context.get("scene_location")
            or framework.get("primary_location")
            or (scene_pack.get("location") if isinstance(scene_pack, dict) else "")
            or "当前章节核心地点"
        )
        characters = [
            item
            for item in context.get("characters", [])
            if isinstance(item, dict) and item.get("character_id")
        ]
        role_beats = []
        for index, character in enumerate(characters[:4]):
            name = str(character.get("name") or character.get("character_id") or "").strip()
            if not name:
                continue
            if index == 0:
                content = f"{name}围绕本幕目标做出选择，推动当前冲突进入下一步。"
            elif index == 1:
                content = f"{name}从自身立场回应本幕变化，形成阻力或支持。"
            else:
                content = f"{name}补充局部行动或情绪反应，不引入未经确认的新设定。"
            role_beats.append(
                {
                    "character_id": str(character.get("character_id") or ""),
                    "content": content,
                }
            )
        safe_error = self._safe_composite_runtime_error(exc)
        return self._apply_resolved_scene_goal(
            self._normalize_scene_information(
                {
                    "scene_goal": {
                        "summary": scene_goal,
                        "source": "provider_failure_fallback",
                    },
                    "environment": {
                        "location": location,
                        "time_label": f"第 {scene_index} 幕",
                    },
                    "role_beats": role_beats,
                    "story_information_list": [
                        {
                            "item_id": "provider_fallback_scene_goal",
                            "type": "scene_goal",
                            "content": scene_goal,
                            "source_node": "SceneInformationFallback",
                            "priority": "must_use",
                            "order_hint": 10,
                        },
                        {
                            "item_id": "provider_fallback_warning",
                            "type": "diagnostic",
                            "content": (
                                "外部模型 Provider 在场景信息阶段失败，"
                                f"本幕使用可恢复结构草稿。错误摘要：{safe_error}"
                            ),
                            "source_node": "SceneInformationFallback",
                            "priority": "do_not_use",
                            "order_hint": 20,
                        },
                    ],
                }
            ),
            context,
        )

    def assemble_story_information(
        self,
        scene_information: dict[str, Any],
        context: dict[str, Any],
    ) -> list[StoryInformationItem]:
        raw_items = scene_information.get("story_information_list") or []
        items: list[StoryInformationItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            try:
                items.append(StoryInformationItem(**raw_item))
            except ValidationError:
                continue
        if not items:
            items = self._fallback_story_information(scene_information, context)
        items = [
            *self._current_scene_goal_story_information(context),
            *items,
        ]
        items.extend(self._story_information_from_memory_pack(context))
        return self._dedupe_story_information(items)

    def _normalize_scene_information(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data or {})
        scene_goal = normalized.get("scene_goal")
        if isinstance(scene_goal, str):
            normalized["scene_goal"] = {"summary": scene_goal}
        elif not isinstance(scene_goal, dict):
            normalized["scene_goal"] = {}

        environment = normalized.get("environment")
        if isinstance(environment, str):
            normalized["environment"] = {"location": environment}
        elif not isinstance(environment, dict):
            normalized["environment"] = {}

        role_beats = normalized.get("role_beats")
        if isinstance(role_beats, dict):
            normalized["role_beats"] = [role_beats]
        elif isinstance(role_beats, list):
            normalized["role_beats"] = [
                item if isinstance(item, dict) else {"content": str(item)}
                for item in role_beats
                if item
            ]
        else:
            normalized["role_beats"] = []

        raw_items = normalized.get("story_information_list")
        if isinstance(raw_items, list):
            normalized["story_information_list"] = [
                self._normalize_story_information_item(item, index)
                for index, item in enumerate(raw_items, start=1)
                if item
            ]
        else:
            normalized["story_information_list"] = []
        return normalized

    def _normalize_story_information_item(self, item: Any, index: int) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {
                "item_id": f"story_info_{index:03d}",
                "type": "scene_goal",
                "content": str(item),
                "source_node": "SceneInformationAgent",
                "priority": "should_use",
                "order_hint": index * 10,
            }
        normalized = dict(item)
        normalized.setdefault(
            "item_id",
            str(normalized.get("id") or normalized.get("key") or f"story_info_{index:03d}"),
        )
        normalized.setdefault(
            "content",
            str(
                normalized.get("summary")
                or normalized.get("description")
                or normalized.get("text")
                or normalized.get("beat")
                or ""
            ),
        )
        normalized.setdefault("type", str(normalized.get("category") or "scene_goal"))
        normalized.setdefault("source_node", "SceneInformationAgent")
        normalized.setdefault("priority", "should_use")
        normalized.setdefault("order_hint", index * 10)
        return normalized

    def order_story_information(
        self,
        items: list[StoryInformationItem],
    ) -> OrderedStoryInformationPackage:
        priority_order = {
            "must_use": 0,
            "should_use": 1,
            "optional": 2,
            "do_not_use": 3,
        }

        def sort_key(item: StoryInformationItem) -> tuple[int, int, str]:
            return (
                priority_order.get(item.priority, 9),
                item.order_hint if item.order_hint is not None else 999,
                item.item_id,
            )

        sorted_items = sorted(items, key=sort_key)
        package = OrderedStoryInformationPackage()
        for item in sorted_items:
            if item.priority == "do_not_use":
                package.do_not_include.append(item.content)
                continue
            if item.type == "anti_repeat_guidance":
                package.anti_repeat_guidance.append(item.content)
                continue
            if item.type in {"environment", "world_rule"}:
                package.opening_context.append(item.content)
            elif item.type in {"scene_goal", "conflict", "framework_component"}:
                package.scene_progression.append(item.content)
            elif item.type == "character_turn":
                package.character_turns.append(item.content)
            elif item.type == "reveal":
                package.required_reveals.append(item.content)
            elif item.type == "emotion":
                package.emotional_beats.append(item.content)
            elif item.type == "ending":
                package.ending_beat.append(item.content)
            else:
                package.scene_progression.append(item.content)
        return package

    def write_scene(
        self,
        ordered_package: OrderedStoryInformationPackage,
        approved_context: dict[str, Any],
    ) -> SceneDraftContent:
        data = self.write_agent.write_scene(
            ordered_story_information_package=model_to_dict(ordered_package),
            approved_context=approved_context,
        )
        try:
            return SceneDraftContent(**data)
        except ValidationError as exc:
            raise StorageError("SCENE_MODEL_SCHEMA_INVALID: Write Agent output is invalid.") from exc

    def extract_memory(
        self,
        scene_draft: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> SceneMemoryExtraction:
        data = self.memory_curator_agent.extract_memory(
            scene=scene_draft,
            approved_context=approved_context,
        )
        normalized = self._normalize_memory_extraction_data(
            data,
            scene_draft=scene_draft,
            approved_context=approved_context,
        )
        try:
            return SceneMemoryExtraction(**normalized)
        except ValidationError as exc:
            raise StorageError("SCENE_MODEL_SCHEMA_INVALID: Memory Curator output is invalid.") from exc

    def quality_check(
        self,
        scene_draft: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> SceneQualityReport:
        try:
            data = self.quality_check_agent.check_scene(
                scene=scene_draft,
                approved_context=approved_context,
            )
            report = SceneQualityReport(**data)
        except ValidationError as exc:
            raise StorageError("SCENE_MODEL_SCHEMA_INVALID: Quality Check output is invalid.") from exc

        rule_report = self._rule_quality_check(scene_draft, approved_context)
        warnings = self._unique_strings(report.warnings + rule_report.warnings)
        blocking_issues = self._unique_strings(
            report.blocking_issues + rule_report.blocking_issues
        )
        return SceneQualityReport(
            passed=len(blocking_issues) == 0,
            warnings=warnings,
            blocking_issues=blocking_issues,
            requires_user_confirmation=(
                report.requires_user_confirmation
                or rule_report.requires_user_confirmation
            ),
        )

    def _provider_failure_quality_report(
        self,
        *,
        stage: str,
        exc: Exception,
        existing_report: SceneQualityReport | None = None,
    ) -> SceneQualityReport:
        existing = existing_report or SceneQualityReport(passed=True)
        safe_error = self._safe_composite_runtime_error(exc)
        warning = (
            f"Model provider failed during {stage}; a recoverable local draft was "
            f"kept for user review. error={safe_error}"
        )
        return SceneQualityReport(
            quality_report_id=existing.quality_report_id,
            passed=not existing.blocking_issues,
            warnings=self._unique_strings([*existing.warnings, warning]),
            blocking_issues=list(existing.blocking_issues),
            requires_user_confirmation=True,
            continuity_checked=existing.continuity_checked,
            continuity_gate_run_id=existing.continuity_gate_run_id,
            continuity_checked_at=existing.continuity_checked_at,
            continuity_passed=existing.continuity_passed,
            continuity_issue_ids=list(existing.continuity_issue_ids),
            blocking_continuity_issue_ids=list(
                existing.blocking_continuity_issue_ids
            ),
            accepted_continuity_issue_ids=list(
                existing.accepted_continuity_issue_ids
            ),
            semantic_check_status=existing.semantic_check_status
            if existing.semantic_check_status != "not_run"
            else "degraded_fallback",
            summary=existing.summary
            or "Provider failure fallback draft requires user review.",
            quality_degraded=True,
            confirmation_block_reason=existing.confirmation_block_reason
            or "provider_failure_fallback_requires_review",
        )

    def save_scene_draft(self, scene: Scene) -> None:
        self._upsert_scene(scene)

    def save_confirmed_scene(self, scene: Scene) -> None:
        self._upsert_scene(scene)

    def _apply_subjective_fact_write_rules(
        self,
        scene: Scene,
        *,
        status: str,
    ) -> Scene:
        extraction = self.subjective_fact_extraction_service.extract_from_scene(scene)
        write_result = self.subjective_fact_write_service.write_from_extraction(
            extraction,
            status=status,
            project_id=scene.project_id,
        )
        filtered_scene, guard_decision = self.objective_fact_write_guard.filter_scene(
            scene,
            extraction,
        )
        trace_data = model_to_dict(filtered_scene.generation_trace)
        subjective_record_ids = self._unique_strings(
            [
                *trace_data.get("subjective_record_ids", []),
                *write_result.subjective_record_ids,
            ]
        )
        trace_data["subjective_record_ids"] = subjective_record_ids
        trace_data["subjective_fact_summary"] = (
            "M3 subjective records: "
            f"claims={len(write_result.claim_record_ids)}, "
            f"perceptions={len(write_result.perception_state_record_ids)}, "
            f"psychology={len(write_result.psychology_trace_ids)}, "
            f"expressions={len(write_result.expression_record_ids)}, "
            f"blocked_objective={len(guard_decision.blocked_objective_candidates)}."
        )
        trace_data["objective_guard_blocked_count"] = len(
            guard_decision.blocked_objective_candidates
        )
        trace_data["objective_guard_warnings"] = self._unique_strings(
            [
                *trace_data.get("objective_guard_warnings", []),
                *guard_decision.warnings,
            ]
        )
        return Scene(
            **{
                **model_to_dict(filtered_scene),
                "generation_trace": trace_data,
                "updated_at": now_iso(),
            }
        )

    def write_confirmed_events(
        self,
        scene: Scene,
        status: str = "confirmed",
    ) -> list[Event]:
        timestamp = now_iso()
        existing = self._read_list_if_present(self.events_file)
        event_by_id = {
            event.get("event_id"): dict(event)
            for event in existing
            if isinstance(event, dict) and event.get("event_id")
        }
        guarded_extraction, _decision = (
            self.objective_fact_write_guard.filter_scene_memory_extraction(scene)
        )
        events: list[Event] = []
        for index, event_data in enumerate(guarded_extraction.event_summary, start=1):
            if not isinstance(event_data, dict):
                continue
            event_id = event_data.get("event_id") or f"event_{scene.scene_id}_{index:03d}"
            event = Event(
                event_id=event_id,
                scene_id=scene.scene_id,
                summary=str(event_data.get("summary") or scene.synopsis),
                participants=[
                    str(participant)
                    for participant in event_data.get("participants", [])
                    if participant
                ],
                location_id=str(event_data.get("location_id") or scene.location),
                cause=str(event_data.get("cause") or "Scene draft was confirmed."),
                result=str(event_data.get("result") or scene.synopsis),
                tags=[
                    str(tag) for tag in event_data.get("tags", []) if tag
                ],
                status=status,
                created_at=event_by_id.get(event_id, {}).get("created_at") or timestamp,
                updated_at=timestamp,
            )
            event_by_id[event_id] = model_to_dict(event)
            events.append(event)
        self.repositories.events.write_all(list(event_by_id.values()))
        return events

    def write_confirmed_state_changes(
        self,
        scene: Scene,
        events: list[Event],
        default_status: str = "confirmed",
    ) -> list[StateChange]:
        timestamp = now_iso()
        existing = self._read_list_if_present(self.state_changes_file)
        change_by_id = {
            change.get("state_change_id"): dict(change)
            for change in existing
            if isinstance(change, dict) and change.get("state_change_id")
        }
        reason_event_id = events[0].event_id if events else ""
        guarded_extraction, _decision = (
            self.objective_fact_write_guard.filter_scene_memory_extraction(scene)
        )
        state_changes: list[StateChange] = []
        for index, change_data in enumerate(
            guarded_extraction.proposed_state_changes,
            start=1,
        ):
            if not isinstance(change_data, dict):
                continue
            change_id = (
                change_data.get("state_change_id")
                or f"change_{scene.scene_id}_{index:03d}"
            )
            requires_confirmation = bool(
                change_data.get("requires_user_confirmation")
            )
            if default_status == "provisional":
                status = "provisional"
            else:
                status = "proposed" if requires_confirmation else str(
                    change_data.get("status") or default_status
                )
            change = StateChange(
                state_change_id=change_id,
                target_type=str(change_data.get("target_type") or "scene"),
                target_id=str(change_data.get("target_id") or scene.scene_id),
                before=dict(change_data.get("before") or {}),
                after=dict(
                    change_data.get("after")
                    or {"summary": change_data.get("summary") or scene.synopsis}
                ),
                reason_event_id=str(
                    change_data.get("reason_event_id") or reason_event_id
                ),
                requires_user_confirmation=requires_confirmation,
                status=status,
            )
            data = model_to_dict(change)
            data["created_at"] = change_by_id.get(change_id, {}).get("created_at") or timestamp
            data["updated_at"] = timestamp
            change_by_id[change_id] = data
            state_changes.append(change)
        self.repositories.state_changes.write_all(list(change_by_id.values()))
        return state_changes

    def write_memory_records(
        self,
        scene: Scene,
        events: list[Event] | None = None,
        status_override: str | None = None,
        source_type: str = "scene_confirmed",
    ) -> list[MemoryRecord]:
        existing = self._read_list_if_present(self.memory_records_file)
        memory_by_id = {
            memory.get("memory_id"): dict(memory)
            for memory in existing
            if isinstance(memory, dict) and memory.get("memory_id")
        }
        event_ids = [event.event_id for event in events or []] or list(scene.event_ids)
        event_tags = [
            tag
            for event in events or []
            for tag in event.tags
            if tag
        ]
        memory_records: list[MemoryRecord] = []
        guarded_extraction, _decision = (
            self.objective_fact_write_guard.filter_scene_memory_extraction(scene)
        )
        for index, memory_data in enumerate(guarded_extraction.memory_records, start=1):
            if not isinstance(memory_data, dict):
                continue
            memory_id = (
                memory_data.get("memory_id")
                or f"memory_{scene.scene_id}_{index:03d}"
            )
            source_object_type = str(
                memory_data.get("source_object_type")
                or memory_data.get("object_type")
                or "scene"
            )
            source_object_id = str(
                memory_data.get("source_object_id")
                or memory_data.get("object_id")
                or scene.scene_id
            )
            keywords = self._unique_strings(
                [
                    *[
                        str(keyword)
                        for keyword in memory_data.get("keywords", [])
                        if keyword
                    ],
                    *[
                        str(tag)
                        for tag in memory_data.get("tags", [])
                        if tag
                    ],
                    *event_tags,
                    source_object_type,
                    str(memory_data.get("memory_type") or "event"),
                    scene.location,
                ]
            )
            character_ids = self._unique_strings(
                [
                    *[
                        str(character_id)
                        for character_id in memory_data.get("character_ids", [])
                        if character_id
                    ],
                    *scene.linked_character_ids,
                ]
            )
            relationship_ids = self._unique_strings(
                [
                    *[
                        str(relationship_id)
                        for relationship_id in memory_data.get("relationship_ids", [])
                        if relationship_id
                    ],
                    *scene.linked_relationship_ids,
                ]
            )
            record_event_ids = self._unique_strings(
                [
                    *[
                        str(event_id)
                        for event_id in memory_data.get("event_ids", [])
                        if event_id
                    ],
                    *event_ids,
                ]
            )
            timestamp = now_iso()
            memory = MemoryRecord(
                memory_id=memory_id,
                project_id=scene.project_id,
                source_object_type=source_object_type,
                source_object_id=source_object_id,
                chapter_id=scene.chapter_id,
                scene_id=scene.scene_id,
                memory_type=str(memory_data.get("memory_type") or "event"),
                summary=str(memory_data.get("summary") or scene.synopsis),
                keywords=keywords,
                character_ids=character_ids,
                relationship_ids=relationship_ids,
                location=str(memory_data.get("location") or scene.location or "") or None,
                event_ids=record_event_ids,
                importance=str(memory_data.get("importance") or "medium"),
                status=str(status_override or memory_data.get("status") or "active"),
                superseded_by=memory_data.get("superseded_by") or None,
                truth_status=str(memory_data.get("truth_status") or "objective_fact"),
                objective_truth=bool(memory_data.get("objective_truth", True)),
                source_issue_id=str(memory_data.get("source_issue_id") or ""),
                speaker_character_id=str(memory_data.get("speaker_character_id") or ""),
                believed_by_character_ids=[
                    str(character_id)
                    for character_id in memory_data.get("believed_by_character_ids", [])
                    if character_id
                ],
                known_false_by_character_ids=[
                    str(character_id)
                    for character_id in memory_data.get("known_false_by_character_ids", [])
                    if character_id
                ],
                version_id=str(memory_data.get("version_id") or MEMORY_M2_VERSION_ID),
                created_at=memory_by_id.get(memory_id, {}).get("created_at") or timestamp,
                updated_at=timestamp,
                source_type=str(
                    source_type if status_override else memory_data.get("source_type") or source_type
                ),
                object_type=source_object_type,
                object_id=source_object_id,
                tags=keywords,
                embedding_ref=str(memory_data.get("embedding_ref") or ""),
            )
            memory_by_id[memory_id] = model_to_dict(memory)
            memory_records.append(memory)
        self.repositories.memory.write_all(list(memory_by_id.values()))
        return memory_records

    def write_decision(
        self,
        target_id: str,
        user_input: str,
        decision_type: str = "confirm",
    ) -> Decision:
        decisions = self._read_decision_dicts()
        decision = Decision(
            decision_id=f"decision_scene_{decision_type}_{len(decisions) + 1:03d}",
            decision_type=decision_type,
            target_type="scene",
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.repositories.decisions.write_all(decisions)
        return decision

    def update_project_step(self, current_step: str, status: str) -> None:
        if not self.store.exists(self.project_file):
            return
        project = self.store.read(self.project_file)
        updated = dict(project)
        updated["project_id"] = self._current_project_id()
        updated["current_step"] = current_step
        updated["status"] = status
        updated["updated_at"] = now_iso()
        if updated != project:
            self.store.write(self.project_file, updated)

    def _generate_scene_draft(
        self,
        chapter_id: str | None,
        scene_index: int,
        regeneration_hint: str,
        write_prose: bool = True,
        force_refresh_packs: bool = False,
        include_provisional: bool = False,
        progress_before: Any | None = None,
    ) -> SceneGenerationResponse:
        readiness = self.check_scene_generation_ready(chapter_id, scene_index)
        if not readiness.ready:
            self._raise_scene_generation_not_ready(readiness)

        context = self.load_scene_inputs(
            chapter_id=chapter_id,
            scene_index=scene_index,
            force_refresh_packs=force_refresh_packs,
            include_provisional=include_provisional,
        )
        chapter = Chapter(**context["chapter"])
        current_scene = self._find_scene(chapter.chapter_id, scene_index)
        if current_scene and current_scene.status in NEXT_READY_SCENE_STATUSES:
            raise StorageError(
                "SCENE_ALREADY_CONFIRMED: Current scene is already committed and cannot be overwritten."
            )
        if current_scene and scene_index != 1 and current_scene.status == "draft":
            raise StorageError(
                "SCENE_NEXT_NOT_READY: 下一幕草稿已存在，请先确认或处理该草稿。"
            )

        scene_id = current_scene.scene_id if current_scene else self._scene_id(
            chapter,
            scene_index,
        )
        generation_trace_id = self.authorial_intent_service.create_generation_trace_id(
            chapter_id=chapter.chapter_id,
            scene_index=scene_index,
        )
        context["scene_id"] = scene_id
        context["generation_trace_id"] = generation_trace_id
        authorial_intent_result = (
            self.authorial_intent_service.create_or_skip_for_scene_generation(
                context,
                chapter_id=chapter.chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                generation_trace_id=generation_trace_id,
                regeneration_hint=regeneration_hint,
            )
        )
        context["authorial_intent"] = self._safe_authorial_intent_context(
            authorial_intent_result
        )
        writing_context = self._build_scene_writing_context(
            context=context,
            chapter=chapter,
            scene_id=scene_id,
            scene_index=scene_index,
        )
        context["scene_writing_context"] = model_to_dict(writing_context)
        context["project_story_premise"] = writing_context.project_story_premise
        context["prompt_fidelity_contract"] = writing_context.prompt_fidelity_contract

        provider_fallback_reasons: list[str] = []
        used_content_fallback = False
        try:
            scene_information = self.generate_scene_information(
                context=context,
                regeneration_hint=regeneration_hint,
            )
        except (ModelCallError, ModelJsonParseError) as exc:
            provider_fallback_reasons.append(
                f"scene_information:{self._safe_composite_runtime_error(exc)}"
            )
            scene_information = self._fallback_scene_information(
                context=context,
                scene_index=scene_index,
                exc=exc,
            )
        story_items = self.assemble_story_information(scene_information, context)
        ordered_package = self.order_story_information(story_items)
        progression_statement = self._build_scene_progression_statement(
            writing_context=writing_context,
            scene_information=scene_information,
            ordered_package=ordered_package,
        )
        ordered_package = self._attach_progression_to_ordered_package(
            ordered_package,
            progression_statement,
            writing_context,
        )
        context["scene_progression_statement"] = model_to_dict(progression_statement)
        trace = SceneGenerationTrace(
            generation_trace_id=generation_trace_id,
            narrative_intent_ids=[
                authorial_intent_result.narrative_intent_id
            ]
            if authorial_intent_result.narrative_intent_id
            else [],
            narrative_intent_summary=authorial_intent_result.narrative_intent_summary,
            authorial_intent_status=authorial_intent_result.status,
            authorial_intent_skip_reason=authorial_intent_result.skip_reason,
            authorial_intent_failure_reason=authorial_intent_result.failure_reason,
            scene_goal=scene_information.get("scene_goal") or {},
            environment=scene_information.get("environment") or {},
            role_beats=list(scene_information.get("role_beats") or []),
            story_information_list=story_items,
            ordered_story_information_package=ordered_package,
            scene_writing_context=writing_context,
            scene_progression_statement=progression_statement,
        )
        approved_context = {
            **context,
            "scene_information": {
                "scene_goal": trace.scene_goal,
                "environment": trace.environment,
                "role_beats": trace.role_beats,
            },
        }
        if write_prose:
            try:
                content = self.write_scene(ordered_package, approved_context)
                if self._scene_content_has_internal_diagnostics(content):
                    provider_fallback_reasons.append("write_scene:internal_diagnostic_leak")
                    used_content_fallback = True
                    content = self._fallback_scene_content(
                        chapter=chapter,
                        scene_index=scene_index,
                        scene_information=scene_information,
                        ordered_package=ordered_package,
                        context=context,
                        exc=ModelCallError("Write Agent output leaked internal diagnostics."),
                    )
            except (ModelCallError, ModelJsonParseError) as exc:
                provider_fallback_reasons.append(
                    f"write_scene:{self._safe_composite_runtime_error(exc)}"
                )
                used_content_fallback = True
                content = self._fallback_scene_content(
                    chapter=chapter,
                    scene_index=scene_index,
                    scene_information=scene_information,
                    ordered_package=ordered_package,
                    context=context,
                    exc=exc,
                )
            prose_status = "fallback_generated" if used_content_fallback else "generated"
        else:
            synopsis = self._synopsis_from_scene_information(
                scene_information,
                ordered_package,
                scene_index,
            )
            content = SceneDraftContent(synopsis=synopsis, prose_text="")
            prose_status = "not_generated"
        progression_inspection = self._inspect_scene_progression(
            content=content,
            writing_context=writing_context,
            progression=progression_statement,
        )
        trace.progression_inspection = progression_inspection
        draft_for_memory = {
            "scene_id": scene_id,
            "chapter_id": chapter.chapter_id,
            "scene_index": scene_index,
            "content": model_to_dict(content),
            "synopsis": content.synopsis,
            "prose_text": content.prose_text,
        }
        if write_prose and not used_content_fallback:
            try:
                memory_extraction = self.extract_memory(
                    draft_for_memory,
                    approved_context,
                )
            except (ModelCallError, ModelJsonParseError) as exc:
                provider_fallback_reasons.append(
                    f"extract_memory:{self._safe_composite_runtime_error(exc)}"
                )
                memory_extraction = self._fallback_memory_extraction(
                    scene_id=scene_id,
                    chapter=chapter,
                    scene_index=scene_index,
                    content=content,
                    context=context,
                )
        else:
            if used_content_fallback:
                memory_extraction = SceneMemoryExtraction(
                    no_event_reason="Scene prose fallback is diagnostic-only; memory extraction skipped."
                )
            else:
                memory_extraction = self._fallback_memory_extraction(
                    scene_id=scene_id,
                    chapter=chapter,
                    scene_index=scene_index,
                    content=content,
                    context=context,
                )
        timestamp = now_iso()
        scene_goal = trace.scene_goal or {}
        environment = trace.environment or {}
        dependency_fields = self.dependency_service.dependencies_from_scene_pack(
            context.get("scene_memory_pack")
        )
        scene_memory_pack = context.get("scene_memory_pack") or {}
        character_context = context.get("character_context") or {}
        framework_composition_id = self._framework_composition_id(
            context.get("generator_framework_context") or {}
        )
        scene_source_refs = self._scene_source_refs_from_trace(trace, context)
        scene = Scene(
            scene_id=scene_id,
            project_id=self._current_project_id(),
            chapter_id=chapter.chapter_id,
            scene_index=scene_index,
            goal=str(scene_goal.get("summary") or content.synopsis),
            synopsis=content.synopsis,
            prose_text=content.prose_text,
            input_memory_ids=self._memory_ids_from_context(context),
            event_ids=current_scene.event_ids if current_scene else [],
            state_change_ids=current_scene.state_change_ids if current_scene else [],
            status="draft",
            prose_status=prose_status,
            is_provisional=False,
            depends_on_provisional_scene_ids=dependency_fields[
                "depends_on_provisional_scene_ids"
            ],
            depends_on_provisional_memory_ids=dependency_fields[
                "depends_on_provisional_memory_ids"
            ],
            chapter_memory_pack_id=str(
                scene_memory_pack.get("chapter_memory_pack_id") or ""
            ),
            scene_memory_pack_id=str(
                scene_memory_pack.get("scene_memory_pack_id") or ""
            ),
            character_context_ids=[
                str(item.get("character_id") or "")
                for item in character_context.get("items", [])
                if isinstance(item, dict) and item.get("character_id")
            ],
            narrative_intent_ids=trace.narrative_intent_ids,
            scene_goal=scene_goal,
            time_label=str(environment.get("time_label") or ""),
            location=str(
                environment.get("location_id")
                or environment.get("location")
                or ""
            ),
            generation_trace=trace,
            content=content,
            memory_extraction=memory_extraction,
            quality_report=SceneQualityReport(),
            linked_world_canvas_id=str(context["world_canvas"].get("world_canvas_id") or ""),
            linked_character_ids=[
                character["character_id"]
                for character in context["characters"]
                if character.get("character_id")
            ],
            linked_relationship_ids=[
                relationship["relationship_id"]
                for relationship in context["relationships"]
                if relationship.get("relationship_id")
            ],
            linked_framework_package_id=str(
                context["framework_package"].get("framework_package_id") or ""
            ),
            linked_chapter_framework_id=str(
                context["current_chapter_framework"].get("chapter_framework_id") or ""
            ),
            linked_framework_composition_id=framework_composition_id,
            source_refs=scene_source_refs,
            version_id=SCENE_GENERATION_VERSION_ID,
            created_at=current_scene.created_at if current_scene else timestamp,
            updated_at=timestamp,
        )
        if write_prose:
            try:
                quality_response = self.quality_check_service.check_scene_object(
                    scene,
                    context=approved_context,
                    persist_scene=False,
                )
                quality_report = quality_response.embedded_report
                if provider_fallback_reasons:
                    quality_report = self._provider_failure_quality_report(
                        stage="scene_generation",
                        exc=ModelCallError("; ".join(provider_fallback_reasons)),
                        existing_report=quality_report,
                    )
                scene = Scene(
                    **{
                        **model_to_dict(scene),
                        "quality_report": model_to_dict(quality_report),
                        "quality_report_id": quality_response.report.quality_report_id,
                    }
                )
            except (ModelCallError, ModelJsonParseError) as exc:
                provider_fallback_reasons.append(
                    f"quality_check:{self._safe_composite_runtime_error(exc)}"
                )
                scene = Scene(
                    **{
                        **model_to_dict(scene),
                        "quality_report": model_to_dict(
                            self._provider_failure_quality_report(
                                stage="scene_generation_quality_check",
                                exc=ModelCallError(
                                    "; ".join(provider_fallback_reasons)
                                ),
                                existing_report=scene.quality_report,
                            )
                        ),
                    }
                )
        if trace.progression_inspection is not None:
            scene = Scene(
                **{
                    **model_to_dict(scene),
                    "quality_report": model_to_dict(
                        self._merge_progression_inspection_quality(
                            scene.quality_report,
                            trace.progression_inspection,
                        )
                    ),
                }
            )
        self.save_scene_draft(scene)
        scene, scene_gate_pipeline = self._run_generation_gate_pipeline(scene)
        self._record_composite_runtime_candidate_preview(scene)
        self.update_project_step(
            f"scene_{scene_index}_draft",
            f"scene_{scene_index}_draft",
        )
        return SceneGenerationResponse(
            success=scene_gate_pipeline.visible_to_user,
            scene=model_to_dict(scene),
            story_information_summary=self._story_information_summary(scene),
            quality_report=scene.quality_report,
            readiness=self.check_scene_generation_ready(
                chapter_id=chapter.chapter_id,
                scene_index=scene_index,
            ),
            progress=self.get_scene_progress(chapter.chapter_id),
            scene_gate_pipeline=scene_gate_pipeline,
        )

    def _run_generation_gate_pipeline(
        self,
        scene: Scene,
        *,
        max_rounds: int = 3,
    ) -> tuple[Scene, SceneGatePipelineSummary]:
        scene = self._run_generation_gate_checks(scene)
        if self._scene_gate_provider_degraded(scene):
            scene = self._retry_scene_gate_provider_degraded(scene)
        if self._scene_gate_passed(scene):
            return scene, self._scene_gate_pipeline_from_scene(
                scene,
                status="passed_without_repair",
                safe_user_summary="Scene passed quality and continuity checks.",
            )
        if self._scene_gate_provider_degraded(scene):
            return self._mark_scene_gate_blocked(
                scene,
                self._scene_gate_pipeline_from_scene(
                    scene,
                    status="blocked_provider_degraded",
                    visible_to_user=False,
                    user_action_required=True,
                    user_action_options=["modify", "retry"],
                    safe_user_summary=(
                        "The model or gate provider was degraded. Please retry or modify the scene request."
                    ),
                ),
            )
        try:
            repair_result = self._get_scene_gate_repair_orchestrator().run_scene_gate_repair_loop(
                scene.scene_id,
                project_id=scene.project_id,
                chapter_id=scene.chapter_id,
                max_rounds=max_rounds,
                force_runtime_refresh=True,
            )
        except Exception as exc:
            logger.exception("Scene generation gate repair failed for scene %s.", scene.scene_id)
            return self._mark_scene_gate_blocked(
                scene,
                self._scene_gate_pipeline_from_scene(
                    scene,
                    status="blocked_requires_expert_review",
                    visible_to_user=False,
                    user_action_required=True,
                    user_action_options=["expert_review", "modify", "delete"],
                    safe_user_summary=(
                        "The automatic gate repair pipeline stopped and needs expert review."
                    ),
                    blocking_issue_codes=[self._safe_composite_runtime_error(exc)],
                ),
            )

        if (
            repair_result.final_status == "approved_candidate_ready_for_user_acceptance"
            and repair_result.approved_candidate_id
        ):
            try:
                repaired_scene = self._auto_apply_generation_repair_candidate(
                    scene.scene_id,
                    repair_result.approved_candidate_id,
                )
            except StorageError as exc:
                return self._mark_scene_gate_blocked(
                    scene,
                    self._scene_gate_pipeline_from_scene(
                        scene,
                        status="blocked_provider_degraded",
                        rounds_completed=repair_result.rounds_completed,
                        visible_to_user=False,
                        user_action_required=True,
                        user_action_options=["retry", "modify"],
                        safe_user_summary=(
                            "The automatic repair candidate was diagnostic fallback text and cannot be released."
                        ),
                        approved_revision_id=repair_result.approved_candidate_id,
                        blocking_issue_codes=[self._safe_composite_runtime_error(exc)],
                    ),
                )
            repaired_scene = self._run_generation_gate_checks(repaired_scene)
            if self._scene_gate_passed(repaired_scene):
                return repaired_scene, self._scene_gate_pipeline_from_scene(
                    repaired_scene,
                    status="passed_after_auto_repair",
                    rounds_completed=repair_result.rounds_completed,
                    auto_repair_applied=True,
                    approved_revision_id=repair_result.approved_candidate_id,
                    safe_user_summary=(
                        repair_result.safe_user_summary
                        or "Scene passed after automatic gate repair."
                    ),
                )
            scene = repaired_scene

        if (
            repair_result.final_status == "approved_candidate_ready_for_user_acceptance"
            and not repair_result.approved_candidate_id
        ):
            reloaded_scene = self._find_scene_by_id(scene.scene_id) or scene
            reloaded_scene = self._run_generation_gate_checks(reloaded_scene)
            if self._scene_gate_passed(reloaded_scene):
                return reloaded_scene, self._scene_gate_pipeline_from_scene(
                    reloaded_scene,
                    status="passed_without_repair",
                    rounds_completed=repair_result.rounds_completed,
                    safe_user_summary="Scene passed after mandatory gate recheck.",
                )
            scene = reloaded_scene

        status = self._scene_gate_pipeline_status_from_repair_result(repair_result)
        return self._mark_scene_gate_blocked(
            scene,
            self._scene_gate_pipeline_from_scene(
                scene,
                status=status,
                rounds_completed=repair_result.rounds_completed,
                visible_to_user=False,
                user_action_required=True,
                user_action_options=repair_result.user_action_options
                or self._default_scene_gate_user_options(status),
                safe_user_summary=repair_result.safe_user_summary
                or "The automatic gate repair pipeline stopped before the scene could be released.",
                approved_revision_id=repair_result.approved_candidate_id,
                blocking_issue_codes=repair_result.blocked_reasons,
            ),
        )

    def _run_generation_gate_checks(self, scene: Scene) -> Scene:
        try:
            quality_response = self.quality_check_service.check_scene_object(
                scene,
                context=self._approved_context_for_scene(scene),
                persist_scene=False,
            )
            scene = Scene(
                **{
                    **model_to_dict(scene),
                    "quality_report": model_to_dict(quality_response.embedded_report),
                    "quality_report_id": quality_response.report.quality_report_id,
                    "updated_at": now_iso(),
                }
            )
            self.save_scene_draft(scene)
        except (ModelCallError, ModelJsonParseError, StorageError) as exc:
            safe_error = self._safe_composite_runtime_error(exc)
            scene = Scene(
                **{
                    **model_to_dict(scene),
                    "quality_report": model_to_dict(
                        self._provider_failure_quality_report(
                            stage="scene_generation_quality_gate_pipeline",
                            exc=ModelCallError(safe_error),
                            existing_report=scene.quality_report,
                        )
                    ),
                    "updated_at": now_iso(),
                }
            )
            self.save_scene_draft(scene)
            return scene

        try:
            self.continuity_gate_service.check_scene(
                scene.scene_id,
                mode="scene_generation_gate_pipeline",
            )
        except Exception as exc:
            logger.exception("Scene generation continuity gate failed for %s.", scene.scene_id)
            safe_error = self._safe_composite_runtime_error(exc)
            degraded = self._provider_failure_quality_report(
                stage="scene_generation_continuity_gate_pipeline",
                exc=ModelCallError(safe_error),
                existing_report=scene.quality_report,
            )
            scene = Scene(
                **{
                    **model_to_dict(scene),
                    "quality_report": model_to_dict(degraded),
                    "updated_at": now_iso(),
                }
            )
            self.save_scene_draft(scene)
            return scene
        return self._find_scene_by_id(scene.scene_id) or scene

    def _retry_scene_gate_provider_degraded(self, scene: Scene) -> Scene:
        current = scene
        for attempt_index in range(SCENE_GATE_PROVIDER_DEGRADED_RECHECK_ATTEMPTS):
            if not self._scene_gate_provider_degraded(current):
                return current
            logger.info(
                "Scene generation gate provider degraded for %s; rechecking gate attempt %s/%s.",
                current.scene_id,
                attempt_index + 1,
                SCENE_GATE_PROVIDER_DEGRADED_RECHECK_ATTEMPTS,
            )
            latest = self._find_scene_by_id(current.scene_id) or current
            current = self._run_generation_gate_checks(latest)
            if self._scene_gate_passed(current):
                return current
        return current

    def _scene_gate_pipeline_from_scene(
        self,
        scene: Scene | None,
        *,
        status: str = "passed_without_repair",
        rounds_completed: int = 0,
        auto_repair_applied: bool = False,
        visible_to_user: bool | None = None,
        user_action_required: bool = False,
        user_action_options: list[str] | None = None,
        safe_user_summary: str = "",
        approved_revision_id: str = "",
        blocking_issue_codes: list[str] | None = None,
    ) -> SceneGatePipelineSummary:
        quality = scene.quality_report if scene else SceneQualityReport()
        if (
            scene
            and status == "passed_without_repair"
            and not self._scene_gate_passed(scene)
        ):
            status = "blocked_requires_user_action"
            visible_to_user = False if visible_to_user is None else visible_to_user
            user_action_required = True if not user_action_required else user_action_required
            user_action_options = user_action_options or ["modify", "complete", "delete"]
            safe_user_summary = safe_user_summary or (
                "This scene has not passed mandatory quality and continuity gates yet."
            )
        quality_passed = self._scene_quality_passed(quality)
        continuity_passed = self._scene_continuity_passed(quality)
        if visible_to_user is None:
            visible_to_user = status in {"passed_without_repair", "passed_after_auto_repair"}
        return SceneGatePipelineSummary(
            pipeline_run_id=self._scene_gate_pipeline_id(scene, status),
            status=status,
            rounds_completed=rounds_completed,
            quality_checked=bool(quality.quality_report_id),
            continuity_checked=bool(
                quality.continuity_checked and quality.continuity_gate_run_id
            ),
            quality_passed=quality_passed,
            continuity_passed=continuity_passed,
            auto_repair_applied=auto_repair_applied,
            visible_to_user=bool(visible_to_user),
            user_action_required=user_action_required,
            user_action_options=user_action_options or [],
            safe_user_summary=safe_user_summary
            or quality.summary
            or self._default_scene_gate_summary(status),
            approved_revision_id=approved_revision_id,
            continuity_gate_run_id=quality.continuity_gate_run_id,
            blocking_issue_codes=self._unique_strings(
                [
                    *(blocking_issue_codes or []),
                    *quality.blocking_issues,
                    *quality.blocking_continuity_issue_ids,
                    quality.confirmation_block_reason,
                ]
            ),
        )

    def _scene_gate_pipeline_id(self, scene: Scene | None, status: str) -> str:
        if scene is None:
            return f"scene_gate_pipeline_missing_{status}"
        return (
            f"scene_gate_pipeline_{scene.scene_id}_{status}_"
            f"{now_iso().replace(':', '').replace('.', '')}"
        )

    def _scene_gate_passed(self, scene: Scene) -> bool:
        if self._is_non_story_failure_prose(scene.prose_text):
            return False
        quality = scene.quality_report
        return self._scene_quality_passed(quality) and self._scene_continuity_passed(quality)

    def _scene_quality_passed(self, quality: SceneQualityReport) -> bool:
        return bool(
            quality.quality_report_id
            and quality.passed
            and not quality.blocking_issues
            and not quality.requires_user_confirmation
            and not quality.quality_degraded
        )

    def _scene_continuity_passed(self, quality: SceneQualityReport) -> bool:
        return bool(
            quality.continuity_checked
            and quality.continuity_gate_run_id
            and quality.continuity_passed
            and not quality.blocking_continuity_issue_ids
        )

    def _scene_gate_provider_degraded(self, scene: Scene) -> bool:
        quality = scene.quality_report
        return bool(
            quality.quality_degraded
            or "provider" in (quality.confirmation_block_reason or "").casefold()
            or "provider" in (quality.summary or "").casefold()
        )

    def _mark_scene_gate_blocked(
        self,
        scene: Scene,
        pipeline: SceneGatePipelineSummary,
    ) -> tuple[Scene, SceneGatePipelineSummary]:
        scene = self._find_scene_by_id(scene.scene_id) or scene
        updated = Scene(
            **{
                **model_to_dict(scene),
                "status": "needs_review",
                "needs_review_reason": (
                    f"scene_gate_pipeline:{pipeline.status}:{pipeline.safe_user_summary}"
                )[:1000],
                "updated_at": now_iso(),
            }
        )
        self.save_scene_draft(updated)
        return updated, pipeline

    def _scene_gate_pipeline_status_from_repair_result(self, repair_result: Any) -> str:
        final_status = str(getattr(repair_result, "final_status", "") or "")
        if final_status == "blocked_provider_degraded":
            return "blocked_provider_degraded"
        if final_status in {
            "blocked_no_effective_repair",
            "blocked_m5_candidate_creation_failed",
        }:
            return "blocked_provider_degraded"
        blocked_reasons = [
            str(reason or "").casefold()
            for reason in (getattr(repair_result, "blocked_reasons", []) or [])
        ]
        if any(
            "revision_candidate_content_signature_unchanged" in reason
            or "prose_generation_failure" in reason
            or "diagnostic fallback" in reason
            or "provider" in reason
            for reason in blocked_reasons
        ):
            return "blocked_provider_degraded"
        if "max_round" in final_status:
            return "blocked_max_rounds"
        if "expert" in final_status:
            return "blocked_requires_expert_review"
        return "blocked_requires_user_action"

    def _default_scene_gate_user_options(self, status: str) -> list[str]:
        if status == "blocked_requires_expert_review":
            return ["expert_review", "modify", "delete"]
        if status == "blocked_provider_degraded":
            return ["retry", "modify"]
        if status == "blocked_max_rounds":
            return ["modify", "complete", "delete"]
        return ["modify", "complete", "delete", "confirm_keep"]

    def _default_scene_gate_summary(self, status: str) -> str:
        if status == "passed_after_auto_repair":
            return "Scene passed after automatic gate repair."
        if status == "blocked_requires_expert_review":
            return "The scene gate pipeline stopped for expert review."
        if status == "blocked_provider_degraded":
            return "The scene gate pipeline stopped because provider evidence is degraded."
        if status == "blocked_max_rounds":
            return "The scene gate pipeline reached the maximum repair rounds."
        if status == "blocked_requires_user_action":
            return "The scene needs user action before it can be shown as a normal draft."
        return "Scene passed quality and continuity checks."

    def _get_scene_gate_repair_orchestrator(self) -> Any:
        if self.scene_gate_repair_orchestrator is not None:
            return self.scene_gate_repair_orchestrator
        from app.backend.services.scene_gate_repair_orchestrator_service import (
            SceneGateRepairOrchestratorService,
        )
        from app.backend.services.scene_revision_service import SceneRevisionService

        scene_revision_service = SceneRevisionService(
            store=self.store,
            data_dir=self.data_dir,
            model_gateway=self.model_gateway,
            framework_service=self.framework_service,
            scene_generation_service=self,
            quality_check_service=self.quality_check_service,
            continuity_gate_service=self.continuity_gate_service,
            abcd_runtime_gate_service=self.abcd_runtime_gate_service,
        )
        self.scene_gate_repair_orchestrator = SceneGateRepairOrchestratorService(
            store=self.store,
            data_dir=self.data_dir,
            quality_service=self.quality_check_service,
            continuity_service=self.continuity_gate_service,
            runtime_refresh_service=self.scene_runtime_refresh_state_service,
            scene_revision_service=scene_revision_service,
        )
        return self.scene_gate_repair_orchestrator

    def _auto_apply_generation_repair_candidate(
        self,
        scene_id: str,
        revision_id: str,
    ) -> Scene:
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_GATE_REPAIR_SCENE_MISSING: Scene does not exist.")
        candidate = next(
            (
                item
                for item in scene.revision_history
                if item.revision_id == revision_id
            ),
            None,
        )
        if candidate is None:
            raise StorageError(
                "SCENE_GATE_REPAIR_CANDIDATE_MISSING: Repair candidate does not exist."
            )
        if self._is_non_story_failure_prose(candidate.revised_prose_text):
            raise StorageError(
                "SCENE_GATE_REPAIR_NON_STORY_CANDIDATE: Repair candidate contains diagnostic fallback/provider failure text."
            )
        content = SceneDraftContent(
            synopsis=candidate.revised_synopsis,
            prose_text=candidate.revised_prose_text,
        )
        updated_history = []
        for item in scene.revision_history:
            if item.revision_id == candidate.revision_id:
                updated_history.append(
                    {
                        **model_to_dict(item),
                        "status": "confirmed",
                        "updated_at": now_iso(),
                    }
                )
            else:
                updated_history.append(model_to_dict(item))
        updated_scene = Scene(
            **{
                **model_to_dict(scene),
                "goal": candidate.revised_synopsis or scene.goal,
                "synopsis": candidate.revised_synopsis,
                "prose_text": candidate.revised_prose_text,
                "content": model_to_dict(content),
                "memory_extraction": model_to_dict(candidate.memory_extraction),
                "quality_report": model_to_dict(candidate.quality_report),
                "quality_report_id": candidate.quality_report_id,
                "status": "draft",
                "needs_review_reason": "",
                "revision_history": updated_history,
                "active_revision_id": "",
                "prose_status": "generated",
                "updated_at": now_iso(),
            }
        )
        self.save_scene_draft(updated_scene)
        return updated_scene

    def _record_composite_runtime_candidate_preview(self, scene: Scene) -> None:
        try:
            payload = self._build_composite_runtime_candidate_preview(scene)
        except Exception as exc:
            payload = self._blocked_composite_runtime_candidate_preview(scene, exc)
        try:
            self._append_composite_runtime_run(payload)
        except StorageError:
            logger.exception(
                "Failed to append composite runtime candidate preview for scene %s.",
                scene.scene_id,
            )
            return

    def _record_composite_runtime_commit_boundary_preview(
        self,
        scene: Scene,
        user_confirmation_receipt_id: str,
    ) -> None:
        try:
            payload = self._build_composite_runtime_candidate_preview(
                scene,
                mode="commit_boundary_preview",
                user_confirmation_receipt_id=user_confirmation_receipt_id,
            )
        except Exception as exc:
            payload = self._blocked_composite_runtime_candidate_preview(
                scene,
                exc,
                mode="commit_boundary_preview",
            )
        try:
            self._append_composite_runtime_run(payload)
        except StorageError:
            logger.exception(
                "Failed to append composite runtime commit boundary preview for scene %s.",
                scene.scene_id,
            )
            return

    def _build_composite_runtime_candidate_preview(
        self,
        scene: Scene,
        *,
        mode: str = "candidate_preview",
        user_confirmation_receipt_id: str = "",
    ) -> dict[str, Any]:
        from app.backend.models.composite_runtime_graph import (
            CompositeRuntimeGraphInputRefs,
            CompositeRuntimeGraphRunRequest,
        )
        from app.backend.services.composite_runtime_orchestration_service import (
            CompositeRuntimeOrchestrationService,
        )

        request = CompositeRuntimeGraphRunRequest(
            project_id=scene.project_id or self._current_project_id(),
            chapter_id=scene.chapter_id,
            scene_id=scene.scene_id,
            scene_index=scene.scene_index,
            scene_goal=scene.goal or scene.synopsis,
            scene_location=scene.location,
            mode=mode,
            input_refs=CompositeRuntimeGraphInputRefs(
                mock_user_confirmation_receipt_id=user_confirmation_receipt_id,
            ),
            dry_run=True,
        )
        result = CompositeRuntimeOrchestrationService(
            store=self.store,
            data_dir=self.data_dir,
        ).run(request)
        data = model_to_dict(result)
        check = self._composite_runtime_check_from_result(data)
        if not check.get("candidate_scene_output"):
            check["candidate_scene_output"] = self._composite_runtime_scene_ref(
                scene,
                graph_run_id=str(check.get("graph_run_id") or request.graph_run_id),
            )
        return check

    def _blocked_composite_runtime_candidate_preview(
        self,
        scene: Scene,
        exc: Exception,
        *,
        mode: str = "candidate_preview",
    ) -> dict[str, Any]:
        graph_run_id = (
            f"composite_runtime_{scene.chapter_id}_{scene.scene_index:03d}_{mode}_"
            f"{now_iso().replace(':', '').replace('.', '')}"
        )
        safe_error = self._safe_composite_runtime_error(exc)
        return {
            "graph_run_id": graph_run_id,
            "graph_id": "scene_generation_candidate_graph_v1",
            "mode": mode,
            "status": "blocked",
            "final_decision": "blocked",
            "node_receipts": [],
            "node_order": [],
            "agent_run_ids": [],
            "gate_receipt_ids": [],
            "candidate_scene_output": {
                **self._composite_runtime_scene_ref(scene, graph_run_id=graph_run_id),
                "safe_summary": "Composite Runtime live preview was attempted for the current scene but blocked.",
            },
            "commit_boundary_preview_receipt": None,
            "writeback_plan_preview_ref": None,
            "sequence_report": {
                "graph_run_id": graph_run_id,
                "sequence_valid": False,
                "node_order": [],
                "violations": [safe_error],
                "safe_summary": "Composite Runtime sequence did not run.",
            },
            "authority_audit": {
                "graph_run_id": graph_run_id,
                "authority_audit_passed": False,
                "candidate_gate_commit_writeback_order_preserved": False,
                "story_fact_delta_empty": True,
                "no_write_audit_passed": True,
                "all_node_story_fact_delta_empty": True,
                "no_node_claims_committed_authority": True,
                "candidate_output_candidate_only": True,
                "no_frontend_or_api_mutation": True,
                "checked_node_receipt_ids": [],
                "blocking_findings": [safe_error],
                "warnings": [],
                "safe_summary": "Composite Runtime remained no-write after blocked live preview.",
            },
            "trace": {
                "graph_trace_id": f"trace_{graph_run_id}",
                "graph_run_id": graph_run_id,
                "graph_id": "scene_generation_candidate_graph_v1",
                "mode": mode,
                "node_receipt_ids": [],
                "agent_run_ids": [],
                "gate_receipt_ids": [],
                "candidate_scene_output_ref": f"candidate_scene_output_{graph_run_id}",
                "safe_summary": "Current-scene Composite Runtime preview was blocked safely.",
                "created_at": now_iso(),
            },
            "warnings": [],
            "blocking_findings": [safe_error],
            "safe_summary": "Composite Runtime live preview was blocked before downstream use.",
            "source_kind": "live_project_runtime",
            "read_only": True,
            "generated_at": now_iso(),
        }

    def _composite_runtime_check_from_result(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "graph_run_id": data.get("graph_run_id", ""),
            "graph_id": data.get("graph_id", "scene_generation_candidate_graph_v1"),
            "mode": data.get("mode", "candidate_preview"),
            "status": data.get("status", ""),
            "final_decision": data.get("final_decision", ""),
            "node_receipts": data.get("node_receipts", []),
            "node_order": data.get("node_order", []),
            "agent_run_ids": data.get("agent_run_ids", []),
            "gate_receipt_ids": data.get("gate_receipt_ids", []),
            "candidate_scene_output": data.get("candidate_scene_output") or {},
            "commit_boundary_preview_receipt": data.get("commit_boundary_preview_receipt"),
            "writeback_plan_preview_ref": data.get("writeback_plan_preview_ref"),
            "sequence_report": data.get("sequence_report", {}),
            "authority_audit": data.get("authority_audit", {}),
            "trace": data.get("trace", {}),
            "warnings": data.get("warnings", []),
            "blocking_findings": data.get("blocking_findings", []),
            "safe_summary": data.get("safe_summary", ""),
            "source_kind": "live_project_runtime",
            "read_only": True,
            "generated_at": data.get("generated_at") or now_iso(),
        }

    def _composite_runtime_scene_ref(
        self,
        scene: Scene,
        *,
        graph_run_id: str,
    ) -> dict[str, Any]:
        return {
            "candidate_scene_output_id": f"candidate_scene_output_{graph_run_id}",
            "graph_run_id": graph_run_id,
            "project_id": scene.project_id or self._current_project_id(),
            "chapter_id": scene.chapter_id,
            "scene_id": scene.scene_id,
            "scene_index": scene.scene_index,
            "candidate_only": True,
            "can_write_scene_directly": False,
            "can_write_story_facts_directly": False,
            "story_fact_delta_empty": True,
        }

    def _append_composite_runtime_run(self, payload: dict[str, Any]) -> None:
        path = self.data_dir / COMPOSITE_RUNTIME_RUNS_FILE
        rows: list[Any] = []
        if self.store.exists(path):
            try:
                existing = self.store.read_any(path)
            except StorageError:
                existing = []
            if isinstance(existing, list):
                rows = existing
            elif isinstance(existing, dict):
                rows = existing.get("runs", []) if isinstance(existing.get("runs"), list) else []
        graph_run_id = str(payload.get("graph_run_id") or "")
        rows = [
            item
            for item in rows
            if not isinstance(item, dict) or str(item.get("graph_run_id") or "") != graph_run_id
        ]
        rows.append(payload)
        self.store.write(path, rows[-50:])

    def _safe_composite_runtime_error(self, exc: Exception) -> str:
        text = str(exc or "").strip() or exc.__class__.__name__
        code = text.split(":", 1)[0].strip() or exc.__class__.__name__
        return code[:120]

    def _safe_authorial_intent_context(self, result) -> dict[str, Any]:
        return {
            "status": str(result.status or ""),
            "narrative_intent_ids": [result.narrative_intent_id]
            if result.narrative_intent_id
            else [],
            "summary": str(result.narrative_intent_summary or ""),
            "skip_reason": str(result.skip_reason or ""),
            "failure_reason": str(result.failure_reason or ""),
        }

    def _safe_authorial_intent_context_from_scene(self, scene: Scene) -> dict[str, Any]:
        trace = scene.generation_trace
        return {
            "status": trace.authorial_intent_status,
            "narrative_intent_ids": trace.narrative_intent_ids,
            "summary": trace.narrative_intent_summary,
            "skip_reason": trace.authorial_intent_skip_reason,
            "failure_reason": trace.authorial_intent_failure_reason,
            "generation_trace_id": trace.generation_trace_id,
        }

    def _approved_context_for_scene(self, scene: Scene) -> dict[str, Any]:
        context = self.load_scene_inputs(
            chapter_id=scene.chapter_id,
            scene_index=scene.scene_index,
            include_provisional=bool(
                scene.is_provisional
                or scene.depends_on_provisional_scene_ids
                or scene.depends_on_provisional_memory_ids
            ),
            scene_id=scene.scene_id,
            scene_goal=scene.goal,
            scene_location=scene.location,
        )
        return {
            **context,
            "scene_information": {
                "scene_goal": scene.scene_goal or {},
                "environment": scene.generation_trace.environment or {},
                "role_beats": scene.generation_trace.role_beats,
            },
            "authorial_intent": self._safe_authorial_intent_context_from_scene(scene),
        }

    def _ensure_scene_has_prose(self, scene: Scene) -> Scene:
        content = scene.content or SceneDraftContent(
            synopsis=scene.synopsis,
            prose_text=scene.prose_text,
        )
        if (content.prose_text or scene.prose_text).strip():
            return Scene(
                **{
                    **model_to_dict(scene),
                    "content": model_to_dict(content),
                    "synopsis": content.synopsis or scene.synopsis,
                    "prose_text": content.prose_text or scene.prose_text,
                    "prose_status": "generated",
                }
            )
        ordered_package = (
            scene.generation_trace.ordered_story_information_package
            or self.order_story_information(scene.generation_trace.story_information_list)
        )
        approved_context = self._approved_context_for_scene(scene)
        generated_content = self.write_scene(ordered_package, approved_context)
        if not generated_content.synopsis:
            generated_content.synopsis = scene.synopsis
        return Scene(
            **{
                **model_to_dict(scene),
                "content": model_to_dict(generated_content),
                "synopsis": generated_content.synopsis,
                "prose_text": generated_content.prose_text,
                "prose_status": "generated",
                "updated_at": now_iso(),
            }
        )

    def _ensure_scene_memory_extraction(self, scene: Scene) -> Scene:
        extraction = scene.memory_extraction
        if (
            extraction.event_summary
            or extraction.proposed_state_changes
            or extraction.relationship_changes
            or extraction.memory_records
            or extraction.no_event_reason
        ):
            normalized = self._normalize_memory_extraction_data(
                model_to_dict(extraction),
                scene_draft=self._scene_draft_for_memory(scene),
                approved_context=self._memory_context_from_scene(scene),
            )
            if normalized == model_to_dict(extraction):
                return scene
            return Scene(
                **{
                    **model_to_dict(scene),
                    "memory_extraction": normalized,
                    "updated_at": now_iso(),
                }
            )
        approved_context = self._approved_context_for_scene(scene)
        content = scene.content or SceneDraftContent(
            synopsis=scene.synopsis,
            prose_text=scene.prose_text,
        )
        try:
            extraction = self.extract_memory(
                {
                    "scene_id": scene.scene_id,
                    "chapter_id": scene.chapter_id,
                    "scene_index": scene.scene_index,
                    "content": model_to_dict(content),
                    "synopsis": scene.synopsis,
                    "prose_text": scene.prose_text,
                },
                approved_context,
            )
        except (StorageError, ValidationError):
            chapter = Chapter(**approved_context["chapter"])
            extraction = self._fallback_memory_extraction(
                scene_id=scene.scene_id,
                chapter=chapter,
                scene_index=scene.scene_index,
                content=content,
                context=approved_context,
            )
        return Scene(
            **{
                **model_to_dict(scene),
                "memory_extraction": model_to_dict(extraction),
                "updated_at": now_iso(),
            }
        )

    def _scene_draft_for_memory(self, scene: Scene) -> dict[str, Any]:
        content = scene.content or SceneDraftContent(
            synopsis=scene.synopsis,
            prose_text=scene.prose_text,
        )
        return {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "scene_index": scene.scene_index,
            "content": model_to_dict(content),
            "synopsis": scene.synopsis,
            "prose_text": scene.prose_text,
            "location": scene.location,
            "linked_character_ids": scene.linked_character_ids,
            "linked_relationship_ids": scene.linked_relationship_ids,
        }

    def _memory_context_from_scene(self, scene: Scene) -> dict[str, Any]:
        return {
            "characters": [
                {"character_id": character_id}
                for character_id in scene.linked_character_ids
                if character_id
            ],
            "relationships": [
                {"relationship_id": relationship_id}
                for relationship_id in scene.linked_relationship_ids
                if relationship_id
            ],
            "scene_information": {
                "environment": {
                    "location_id": scene.location,
                    "location": scene.location,
                }
            },
        }

    def _normalize_memory_extraction_data(
        self,
        data: dict[str, Any],
        *,
        scene_draft: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> dict[str, Any]:
        raw = dict(data or {}) if isinstance(data, dict) else {}
        scene_id = str(scene_draft.get("scene_id") or "scene")
        scene_index = scene_draft.get("scene_index") or 1
        content = scene_draft.get("content") or {}
        summary = str(
            raw.get("summary")
            or content.get("synopsis")
            or scene_draft.get("synopsis")
            or "Scene memory extraction summary."
        ).strip()
        location = self._scene_memory_location(scene_draft, approved_context)
        context_character_ids = self._context_ids(
            approved_context,
            "characters",
            "character_id",
        )
        visible_character_ids = self._visible_character_ids_from_scene_text(
            scene_draft,
            context_character_ids,
        )
        context_relationship_ids = self._context_ids(
            approved_context,
            "relationships",
            "relationship_id",
        )

        raw_event_summary = self._coerce_memory_extraction_items(
            raw.get("event_summary"),
            string_field="summary",
        )
        event_summary = [
            self._normalize_event_summary_item(
                item,
                index=index,
                scene_id=scene_id,
                scene_index=scene_index,
                summary=summary,
                location=location,
                context_character_ids=visible_character_ids or context_character_ids,
            )
            for index, item in enumerate(raw_event_summary, start=1)
            if isinstance(item, (dict, str))
        ]
        if visible_character_ids:
            event_summary = [
                {
                    **event,
                    "participants": self._filter_visible_participants(
                        event.get("participants") or [],
                        visible_character_ids,
                    ),
                }
                for event in event_summary
            ]
        proposed_state_changes = [
            self._normalize_state_change_item(
                item,
                index=index,
                scene_id=scene_id,
                summary=summary,
            )
            for index, item in enumerate(
                self._coerce_memory_extraction_items(
                    raw.get("proposed_state_changes"),
                    string_field="summary",
                    allow_string=False,
                ),
                start=1,
            )
            if isinstance(item, dict)
        ]
        relationship_changes = [
            self._normalize_relationship_change_item(item, index, scene_id)
            for index, item in enumerate(
                self._coerce_memory_extraction_items(
                    raw.get("relationship_changes"),
                    string_field="summary",
                    allow_string=False,
                ),
                start=1,
            )
            if isinstance(item, dict)
        ]
        memory_records = [
            self._normalize_memory_record_item(
                item,
                index=index,
                scene_id=scene_id,
                scene_index=scene_index,
                summary=summary,
                context_character_ids=visible_character_ids or context_character_ids,
                context_relationship_ids=context_relationship_ids,
                location=location,
            )
            for index, item in enumerate(
                self._coerce_memory_extraction_items(
                    raw.get("memory_records"),
                    string_field="content",
                    allow_string=False,
                ),
                start=1,
            )
            if isinstance(item, dict)
        ]
        no_event_reason = str(raw.get("no_event_reason") or "").strip()
        if not event_summary and not no_event_reason:
            if proposed_state_changes or relationship_changes or memory_records:
                event_summary = [
                    self._normalize_event_summary_item(
                        {"summary": summary},
                        index=1,
                        scene_id=scene_id,
                        scene_index=scene_index,
                        summary=summary,
                        location=location,
                        context_character_ids=context_character_ids,
                    )
                ]
            else:
                no_event_reason = "No durable event was extracted from this scene."

        return {
            "event_summary": event_summary,
            "proposed_state_changes": proposed_state_changes,
            "relationship_changes": relationship_changes,
            "memory_records": memory_records,
            "no_event_reason": no_event_reason,
        }

    def _coerce_memory_extraction_items(
        self,
        value: Any,
        *,
        string_field: str,
        allow_string: bool = True,
    ) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        if allow_string and isinstance(value, str):
            clean = value.strip()
            return [{string_field: clean}] if clean else []
        return []

    def _visible_character_ids_from_scene_text(
        self,
        scene_draft: dict[str, Any],
        candidate_character_ids: list[str],
    ) -> list[str]:
        candidate_ids = self._unique_strings(candidate_character_ids)
        if not candidate_ids:
            return []
        content = scene_draft.get("content") or {}
        text = " ".join(
            str(value or "")
            for value in [
                content.get("synopsis"),
                content.get("prose_text"),
                scene_draft.get("synopsis"),
                scene_draft.get("prose_text"),
                scene_draft.get("scene_goal"),
            ]
        )
        if not text.strip():
            return []
        characters_by_id = {
            character.character_id: character
            for character in self._read_confirmed_characters_by_ids(candidate_ids)
        }
        visible: list[str] = []
        for character_id in candidate_ids:
            character = characters_by_id.get(character_id)
            names = [
                character_id,
                character.name if character else "",
                character.profile.identity if character else "",
            ]
            if any(name and str(name) in text for name in names):
                visible.append(character_id)
        return self._unique_strings(visible)

    def _filter_visible_participants(
        self,
        participants: list[Any],
        visible_character_ids: list[str],
    ) -> list[str]:
        visible = set(self._unique_strings(visible_character_ids))
        if not visible:
            return self._unique_strings([str(item) for item in participants if item])
        return [
            character_id
            for character_id in self._unique_strings(
                [str(item) for item in participants if item]
            )
            if character_id in visible
        ]

    def _normalize_event_summary_item(
        self,
        item: dict[str, Any] | str,
        *,
        index: int,
        scene_id: str,
        scene_index: int,
        summary: str,
        location: str,
        context_character_ids: list[str],
    ) -> dict[str, Any]:
        event = dict(item) if isinstance(item, dict) else {"summary": str(item)}
        event_summary = str(
            event.get("summary")
            or event.get("content")
            or event.get("description")
            or event.get("text")
            or summary
        ).strip()
        participants = self._unique_strings(
            [
                *[str(value) for value in event.get("participants") or [] if value],
                *[str(value) for value in event.get("character_ids") or [] if value],
                str(event.get("character_id") or ""),
            ]
        ) or context_character_ids
        tags = self._unique_strings(
            [
                *[str(value) for value in event.get("tags") or [] if value],
                f"scene_{scene_index}",
            ]
        )
        return {
            **event,
            "event_id": str(event.get("event_id") or event.get("id") or f"event_{scene_id}_{index:03d}"),
            "summary": event_summary,
            "participants": participants,
            "location_id": str(event.get("location_id") or event.get("location") or location),
            "cause": str(event.get("cause") or "Scene memory extraction recorded this event."),
            "result": str(event.get("result") or event.get("outcome") or event_summary),
            "tags": tags,
        }

    def _normalize_state_change_item(
        self,
        item: dict[str, Any],
        *,
        index: int,
        scene_id: str,
        summary: str,
    ) -> dict[str, Any]:
        change = dict(item)
        character_id = str(change.get("character_id") or "").strip()
        relationship_id = str(change.get("relationship_id") or "").strip()
        target_type = str(change.get("target_type") or "").strip()
        target_id = str(change.get("target_id") or "").strip()
        if not target_id and character_id:
            target_type = target_type or "character"
            target_id = character_id
        elif not target_id and relationship_id:
            target_type = target_type or "relationship"
            target_id = relationship_id
        elif not target_id:
            target_type = target_type or "scene"
            target_id = str(change.get("scene_id") or scene_id)
        target_type = target_type or "scene"

        field = str(change.get("field") or change.get("path") or "").strip()
        before = dict(change.get("before") or {})
        after = dict(change.get("after") or {})
        if field and "old_value" in change and not before:
            before = {field: change.get("old_value")}
        if field and "new_value" in change and not after:
            after = {field: change.get("new_value")}
        if not after:
            after = {"summary": change.get("summary") or summary}
        return {
            **change,
            "state_change_id": str(
                change.get("state_change_id")
                or change.get("change_id")
                or change.get("id")
                or f"change_{scene_id}_{index:03d}"
            ),
            "target_type": target_type,
            "target_id": target_id,
            "before": before,
            "after": after,
            "summary": str(
                change.get("summary")
                or change.get("description")
                or (f"{target_type} {target_id} changes {field}." if field else summary)
            ),
            "requires_user_confirmation": bool(
                change.get("requires_user_confirmation")
            ),
            "status": str(
                change.get("status")
                or ("proposed" if change.get("requires_user_confirmation") else "confirmed")
            ),
        }

    def _normalize_relationship_change_item(
        self,
        item: dict[str, Any],
        index: int,
        scene_id: str,
    ) -> dict[str, Any]:
        change = dict(item)
        return {
            **change,
            "relationship_change_id": str(
                change.get("relationship_change_id")
                or change.get("change_id")
                or change.get("id")
                or f"relationship_change_{scene_id}_{index:03d}"
            ),
        }

    def _normalize_memory_record_item(
        self,
        item: dict[str, Any],
        *,
        index: int,
        scene_id: str,
        scene_index: int,
        summary: str,
        context_character_ids: list[str],
        context_relationship_ids: list[str],
        location: str,
    ) -> dict[str, Any]:
        record = dict(item)
        character_id = str(record.get("character_id") or "").strip()
        relationship_id = str(record.get("relationship_id") or "").strip()
        event_id = str(record.get("event_id") or "").strip()
        object_type = str(
            record.get("object_type")
            or record.get("source_object_type")
            or record.get("related_object_type")
            or ""
        ).strip()
        object_id = str(
            record.get("object_id")
            or record.get("source_object_id")
            or record.get("related_object_id")
            or ""
        ).strip()
        if not object_id and character_id:
            object_type = object_type or "character"
            object_id = character_id
        elif not object_id and relationship_id:
            object_type = object_type or "relationship"
            object_id = relationship_id
        elif not object_id and event_id:
            object_type = object_type or "event"
            object_id = event_id
        elif not object_id:
            object_type = object_type or "scene"
            object_id = scene_id
        object_type = object_type or "scene"

        record_summary = str(
            record.get("summary")
            or record.get("content")
            or record.get("description")
            or record.get("text")
            or summary
        ).strip()
        character_ids = self._unique_strings(
            [
                *[str(value) for value in record.get("character_ids") or [] if value],
                character_id,
                *(context_character_ids if object_type == "scene" else []),
                object_id if object_type == "character" else "",
            ]
        )
        relationship_ids = self._unique_strings(
            [
                *[str(value) for value in record.get("relationship_ids") or [] if value],
                relationship_id,
                *(context_relationship_ids if object_type == "scene" else []),
                object_id if object_type == "relationship" else "",
            ]
        )
        event_ids = self._unique_strings(
            [
                *[str(value) for value in record.get("event_ids") or [] if value],
                event_id,
            ]
        )
        keywords = self._unique_strings(
            [
                *[str(value) for value in record.get("keywords") or [] if value],
                f"scene_{scene_index}",
                *character_ids[:3],
                *relationship_ids[:3],
            ]
        )
        return {
            **record,
            "memory_id": str(
                record.get("memory_id")
                or record.get("id")
                or f"memory_{scene_id}_{index:03d}"
            ),
            "source_type": str(record.get("source_type") or "scene_draft"),
            "object_type": object_type,
            "object_id": object_id,
            "source_object_type": str(record.get("source_object_type") or object_type),
            "source_object_id": str(record.get("source_object_id") or object_id),
            "summary": record_summary,
            "keywords": keywords,
            "character_ids": character_ids,
            "relationship_ids": relationship_ids,
            "event_ids": event_ids,
            "location": record.get("location") or location or None,
            "memory_type": str(record.get("memory_type") or "event"),
        }

    def _scene_memory_location(
        self,
        scene_draft: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> str:
        environment = (
            (approved_context.get("scene_information") or {}).get("environment")
            or {}
        )
        if not isinstance(environment, dict):
            environment = {}
        return str(
            scene_draft.get("location")
            or environment.get("location_id")
            or environment.get("location")
            or ""
        )

    def _context_ids(
        self,
        approved_context: dict[str, Any],
        collection_key: str,
        id_key: str,
    ) -> list[str]:
        return self._unique_strings(
            [
                str(item.get(id_key) or "")
                for item in approved_context.get(collection_key, [])
                if isinstance(item, dict) and item.get(id_key)
            ]
        )

    def _fallback_memory_extraction(
        self,
        *,
        scene_id: str,
        chapter: Chapter,
        scene_index: int,
        content: SceneDraftContent,
        context: dict[str, Any],
    ) -> SceneMemoryExtraction:
        character_ids = [
            str(character.get("character_id") or "")
            for character in context.get("characters", [])
            if isinstance(character, dict) and character.get("character_id")
        ]
        relationship_ids = [
            str(relationship.get("relationship_id") or "")
            for relationship in context.get("relationships", [])
            if isinstance(relationship, dict) and relationship.get("relationship_id")
        ]
        location = str(
            ((context.get("scene_information") or {}).get("environment") or {}).get(
                "location_id"
            )
            or ""
        )
        summary = content.synopsis or chapter.chapter_goal or chapter.summary
        return SceneMemoryExtraction(
            event_summary=[
                {
                    "event_id": f"event_{scene_id}_001",
                    "summary": summary,
                    "participants": character_ids,
                    "location_id": location,
                    "cause": chapter.main_conflict or "当前章顺序推进需要记录本幕事实。",
                    "result": summary,
                    "tags": [f"scene_{scene_index}", "sequential_next_scene"],
                }
            ],
            proposed_state_changes=[
                {
                    "state_change_id": f"change_{scene_id}_001",
                    "target_type": "scene",
                    "target_id": scene_id,
                    "before": {},
                    "after": {"summary": summary},
                    "summary": summary,
                    "requires_user_confirmation": False,
                    "status": "confirmed",
                }
            ],
            relationship_changes=[],
            memory_records=[
                {
                    "memory_id": f"memory_{scene_id}_001",
                    "source_type": "scene_draft",
                    "object_type": "scene",
                    "object_id": scene_id,
                    "source_object_type": "scene",
                    "source_object_id": scene_id,
                    "summary": summary,
                    "keywords": [
                        f"scene_{scene_index}",
                        "sequential_next_scene",
                        *(character_ids[:3]),
                        *(relationship_ids[:3]),
                    ],
                    "character_ids": character_ids,
                    "relationship_ids": relationship_ids,
                    "location": location or None,
                    "memory_type": "event",
                }
            ],
        )

    def _strip_internal_scene_prefix(self, value: str) -> str:
        return re.sub(
            r"^\s*Current chapter\s+\d+\s+scene\s+\d+\s*:\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

    def _story_facing_text(self, value: Any) -> str:
        text = self._strip_internal_scene_prefix(str(value or "").strip())
        if not text:
            return ""
        folded = text.casefold()
        for marker in INTERNAL_PROSE_MARKERS:
            if marker.casefold() in folded:
                return ""
        return text

    def _scene_content_has_internal_diagnostics(
        self,
        content: SceneDraftContent,
    ) -> bool:
        text = f"{content.synopsis}\n{content.prose_text}"
        if re.search(
            r"\bCurrent chapter\s+\d+\s+scene\s+\d+\s*:",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        return not self._story_facing_text(text)

    def _fallback_scene_content(
        self,
        *,
        chapter: Chapter,
        scene_index: int,
        scene_information: dict[str, Any],
        ordered_package: OrderedStoryInformationPackage,
        context: dict[str, Any],
        exc: Exception,
    ) -> SceneDraftContent:
        raw_synopsis = self._synopsis_from_scene_information(
            scene_information,
            ordered_package,
            scene_index,
        )
        chapter_goal = self._story_facing_text(chapter.chapter_goal or chapter.summary)
        synopsis = (
            self._story_facing_text(raw_synopsis)
            or chapter_goal
            or f"Scene {scene_index} requires regeneration before it can become story prose."
        )
        environment = scene_information.get("environment") or {}
        location = str(
            environment.get("location")
            or environment.get("location_id")
            or context.get("scene_location")
            or "current scene location"
        )
        chapter_goal = chapter_goal or "current chapter goal"
        character_names = [
            str(character.get("name") or character.get("character_id") or "").strip()
            for character in context.get("characters", [])
            if isinstance(character, dict)
            and (character.get("name") or character.get("character_id"))
        ]
        cast_line = ", ".join(character_names[:4]) or "scene characters"
        safe_error = self._safe_composite_runtime_error(exc)
        paragraphs = [
            "MODEL_FALLBACK_PLACEHOLDER: External model output was not valid story prose; this diagnostic placeholder must not be exported as story text.",
            f"Structural synopsis: {synopsis}",
            f"Chapter goal: {chapter_goal}",
            f"Scene location: {location}; characters: {cast_line}.",
            f"Failure summary: {safe_error}",
        ]
        return SceneDraftContent(
            synopsis=synopsis,
            prose_text="\n\n".join(paragraphs),
        )

    def _synopsis_from_scene_information(
        self,
        scene_information: dict[str, Any],
        ordered_package: OrderedStoryInformationPackage,
        scene_index: int,
    ) -> str:
        scene_goal = scene_information.get("scene_goal") or {}
        summary = str(scene_goal.get("summary") or "").strip()
        if summary:
            return summary
        for group in [
            ordered_package.scene_progression,
            ordered_package.required_reveals,
            ordered_package.ending_beat,
            ordered_package.opening_context,
        ]:
            if group:
                return str(group[0])
        return f"Scene {scene_index} structural draft is diagnostic only and requires regeneration."

    def _should_include_provisional_for_next(
        self,
        explicit: bool | None,
        progress: Any,
    ) -> bool:
        if explicit is True:
            return True
        if explicit is False:
            return False
        for scene in progress.scenes:
            if not isinstance(scene, dict):
                continue
            if (
                scene.get("status") == "temporary_confirmed"
                or scene.get("is_provisional")
                or scene.get("depends_on_provisional_scene_ids")
                or scene.get("depends_on_provisional_memory_ids")
            ):
                return True
        return any(
            memory.get("status") == "provisional"
            and memory.get("chapter_id") == progress.chapter_id
            for memory in self._read_list_if_present(self.memory_records_file)
            if isinstance(memory, dict)
        )

    def _rule_quality_check(
        self,
        scene_draft: dict[str, Any],
        approved_context: dict[str, Any],
    ) -> SceneQualityReport:
        warnings: list[str] = []
        blocking_issues: list[str] = []
        content = scene_draft.get("content") or {}
        synopsis = str(content.get("synopsis") or scene_draft.get("synopsis") or "")
        prose_text = str(content.get("prose_text") or scene_draft.get("prose_text") or "")
        if not synopsis.strip():
            blocking_issues.append("Scene synopsis is empty.")
        if not prose_text.strip():
            blocking_issues.append("Scene prose_text is empty.")
        if self._is_non_story_failure_prose(prose_text):
            blocking_issues.append(
                "Scene prose_text contains diagnostic fallback/provider failure text."
            )
        trace = scene_draft.get("generation_trace") or {}
        if not trace.get("story_information_list"):
            blocking_issues.append("Scene story_information_list is missing.")
        if not trace.get("ordered_story_information_package"):
            blocking_issues.append("Scene ordered_story_information_package is missing.")
        self._validate_scene_hard_rules(
            prose_text=prose_text,
            world_canvas=approved_context.get("world_canvas") or {},
            blocking_issues=blocking_issues,
        )
        do_not_include = (
            (trace.get("ordered_story_information_package") or {}).get("do_not_include")
            or []
        )
        for item in do_not_include:
            text = str(item).strip()
            if text and text in prose_text:
                blocking_issues.append("Scene prose includes do_not_use story information.")
                break
        memory_extraction = scene_draft.get("memory_extraction") or {}
        if not memory_extraction.get("event_summary") and not memory_extraction.get("no_event_reason"):
            warnings.append("Memory extraction has no event summary or no_event_reason.")
        return SceneQualityReport(
            passed=len(blocking_issues) == 0,
            warnings=self._unique_strings(warnings),
            blocking_issues=self._unique_strings(blocking_issues),
            requires_user_confirmation=False,
        )

    def _is_non_story_failure_prose(self, prose_text: str) -> bool:
        text = str(prose_text or "")
        if not text.strip():
            return False
        if any(marker in text for marker in NON_STORY_PROSE_FAILURE_MARKERS):
            return True
        return "Failure summary:" in text and any(
            marker in text for marker in NON_STORY_PROSE_ERROR_MARKERS
        )

    def _validate_scene_hard_rules(
        self,
        prose_text: str,
        world_canvas: dict[str, Any],
        blocking_issues: list[str],
    ) -> None:
        hard_rule_texts = [
            f"{rule.get('rule_id', '')} {rule.get('statement', '')}"
            if isinstance(rule, dict)
            else str(rule)
            for rule in world_canvas.get("hard_rules", [])
        ]
        if self._has_midnight_only_rule(hard_rule_texts) and self._claims_non_midnight_trigger(prose_text):
            blocking_issues.append("Scene appears to violate a World Canvas hard trigger rule.")
        if self._has_no_free_memory_creation_rule(hard_rule_texts) and self._claims_free_memory_creation(prose_text):
            blocking_issues.append("Scene appears to violate a World Canvas hard memory-creation rule.")
        if self._has_no_free_memory_reversal_rule(hard_rule_texts) and self._claims_free_memory_reversal(prose_text):
            blocking_issues.append("Scene appears to violate a World Canvas hard memory-reversal rule.")

    def _fallback_story_information(
        self,
        scene_information: dict[str, Any],
        context: dict[str, Any],
    ) -> list[StoryInformationItem]:
        chapter = context.get("chapter") or {}
        environment = scene_information.get("environment") or {}
        resolved_scene_goal = str(
            context.get("resolved_scene_goal")
            or chapter.get("chapter_goal")
            or ""
        ).strip()
        return [
            StoryInformationItem(
                item_id="fallback_scene_goal",
                type="scene_goal",
                content=resolved_scene_goal or "生成当前章当前场景。",
                source_node="ScenePlanner",
                priority="must_use",
                order_hint=10,
            ),
            StoryInformationItem(
                item_id="fallback_environment",
                type="environment",
                content=environment.get("location") or "使用已确认世界画布中的当前地点。",
                source_node="SceneEnvironment",
                priority="should_use",
                order_hint=20,
            ),
        ]

    def _upsert_scene(self, scene: Scene) -> None:
        scenes = self._read_list_if_present(self.scenes_file)
        scene_data = model_to_dict(scene)
        replaced = False
        updated: list[dict[str, Any]] = []
        for item in scenes:
            if not isinstance(item, dict):
                continue
            if item.get("scene_id") == scene.scene_id:
                updated.append(scene_data)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(scene_data)
        self.repositories.scenes.write_all(updated)

    def _attach_scene_to_chapter(self, scene: Scene) -> None:
        chapters = self._read_list_if_present(self.chapters_file)
        changed = False
        updated = []
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter = dict(item)
            if chapter.get("chapter_id") == scene.chapter_id:
                scene_ids = [
                    str(scene_id)
                    for scene_id in chapter.get("scene_ids", [])
                    if scene_id
                ]
                if scene.scene_id not in scene_ids:
                    scene_ids.append(scene.scene_id)
                chapter["scene_ids"] = scene_ids
                chapter["updated_at"] = now_iso()
                changed = True
            updated.append(chapter)
        if changed:
            self.repositories.chapters.write_all(updated)

    def _find_current_scene(self) -> Scene | None:
        chapters = self._read_chapters_if_present()
        chapter = self._select_current_chapter(chapters)
        if chapter is None:
            return None
        scenes = [
            scene
            for scene in (
                self._safe_scene(item)
                for item in self._read_list_if_present(self.scenes_file)
            )
            if scene is not None and scene.chapter_id == chapter.chapter_id
        ]
        if not scenes:
            return None
        return sorted(
            scenes,
            key=lambda scene: (scene.scene_index, scene.updated_at or scene.created_at),
            reverse=True,
        )[0]

    def _safe_scene(self, item: dict[str, Any]) -> Scene | None:
        if not isinstance(item, dict):
            return None
        try:
            return Scene(**item)
        except ValidationError as exc:
            raise StorageError("Scene JSON schema is invalid.") from exc

    def _find_scene(self, chapter_id: str, scene_index: int) -> Scene | None:
        for item in self._read_list_if_present(self.scenes_file):
            if not isinstance(item, dict):
                continue
            if item.get("chapter_id") != chapter_id or item.get("scene_index") != scene_index:
                continue
            try:
                return Scene(**item)
            except ValidationError as exc:
                raise StorageError("Scene JSON schema is invalid.") from exc
        return None

    def _find_scene_by_id(self, scene_id: str) -> Scene | None:
        for item in self._read_list_if_present(self.scenes_file):
            if not isinstance(item, dict):
                continue
            if item.get("scene_id") != scene_id:
                continue
            try:
                return Scene(**item)
            except ValidationError as exc:
                raise StorageError("Scene JSON schema is invalid.") from exc
        return None

    def _read_world_canvas(self) -> WorldCanvas:
        data = self.store.read(self.world_canvas_file)
        try:
            return WorldCanvas(**data)
        except ValidationError as exc:
            raise StorageError("WorldCanvas JSON schema is invalid.") from exc

    def _try_read_world_canvas(self) -> WorldCanvas | None:
        try:
            return self._read_world_canvas()
        except StorageError:
            return None

    def _read_characters(self) -> list[Character]:
        data = self.repositories.characters.list_all()
        try:
            return [Character(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Characters JSON schema is invalid.") from exc

    def _read_confirmed_a_characters_if_present(self) -> list[Character]:
        return [
            character
            for character in self._read_characters()
            if character.tier == "A" and character.status == "confirmed"
        ]

    def _read_confirmed_characters_by_ids(
        self,
        character_ids: list[str],
    ) -> list[Character]:
        requested = self._unique_strings(character_ids)
        if not requested:
            return []
        by_id = {
            character.character_id: character
            for character in self._read_characters()
            if character.status == "confirmed" and not character.archived_at
        }
        return [
            by_id[character_id]
            for character_id in requested
            if character_id in by_id
        ]

    def _read_relationships(self) -> list[Relationship]:
        data = self.repositories.relationships.list_all()
        try:
            return [Relationship(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Relationships JSON schema is invalid.") from exc

    def _read_confirmed_relationships(self) -> list[Relationship]:
        return [
            relationship
            for relationship in self._read_relationships()
            if relationship.status == "confirmed"
        ]

    def _read_chapters(self) -> list[Chapter]:
        data = self.repositories.chapters.list_all()
        try:
            return [Chapter(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Chapters JSON schema is invalid.") from exc

    def _read_chapters_if_present(self) -> list[Chapter]:
        if not self.repositories.chapters.list_all():
            return []
        return self._read_chapters()

    def _read_project_if_present(self) -> dict[str, Any] | None:
        if not self.store.exists(self.project_file):
            return None
        return self.store.read(self.project_file)

    def _read_decision_dicts(self) -> list[dict[str, Any]]:
        return self._read_list_if_present(self.decisions_file)

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        repository_by_path = {
            self.scenes_file: self.repositories.scenes,
            self.events_file: self.repositories.events,
            self.state_changes_file: self.repositories.state_changes,
            self.memory_records_file: self.repositories.memory,
            self.characters_file: self.repositories.characters,
            self.relationships_file: self.repositories.relationships,
            self.chapters_file: self.repositories.chapters,
            self.decisions_file: self.repositories.decisions,
        }
        repository = repository_by_path.get(path)
        if repository is not None:
            return repository.list_all()
        if not self.store.exists(path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]

    def _read_generator_framework_context(self) -> dict[str, Any]:
        if not self.store.exists(self.generator_framework_context_file):
            return {}
        data = self.store.read_any(self.generator_framework_context_file)
        if not isinstance(data, dict):
            raise StorageError("GENERATOR_FRAMEWORK_CONTEXT_INVALID: expected object")
        if data.get("schema_version") != GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_VERSION:
            raise StorageError("GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_MISMATCH")
        return data

    def _compact_generator_framework_context(
        self,
        generator_framework_context: Any,
    ) -> dict[str, Any]:
        if not isinstance(generator_framework_context, dict):
            return {}
        if not generator_framework_context:
            return {}
        return {
            "schema_version": generator_framework_context.get("schema_version", ""),
            "composition_ref": generator_framework_context.get("composition_ref") or {},
            "global_framework_context": generator_framework_context.get("global_framework_context")
            or {"items": []},
            "chapter_framework_context": generator_framework_context.get("chapter_framework_context")
            or {"items": []},
            "source_fidelity_context": generator_framework_context.get("source_fidelity_context")
            or {"enabled": False, "items": []},
            "evidence_refs": self._framework_context_source_refs(generator_framework_context),
            "policy_issues": generator_framework_context.get("policy_issues") or [],
        }

    def _chapter_framework_payload_with_generator_context(
        self,
        framework: ChapterFramework,
        generator_framework_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = model_to_dict(framework)
        context = self._compact_generator_framework_context(generator_framework_context or {})
        composition_id = self._framework_composition_id(context)
        if not composition_id:
            return payload
        payload["framework_composition_id"] = composition_id
        payload["generator_framework_context"] = context
        payload["generator_context_source_refs"] = self._framework_context_source_refs(context)
        return payload

    def _framework_composition_id(self, generator_framework_context: Any) -> str:
        if not isinstance(generator_framework_context, dict):
            return ""
        composition_ref = generator_framework_context.get("composition_ref") or {}
        if not isinstance(composition_ref, dict):
            return ""
        return str(composition_ref.get("composition_id") or "").strip()

    def _framework_context_source_refs(
        self,
        generator_framework_context: Any,
    ) -> list[str]:
        if not isinstance(generator_framework_context, dict):
            return []
        return self._unique_strings(
            [
                str(ref or "").strip()
                for ref in generator_framework_context.get("evidence_refs", [])
                if str(ref or "").strip()
            ]
        )

    def _scene_source_refs_from_trace(
        self,
        trace: SceneGenerationTrace,
        context: dict[str, Any],
    ) -> list[str]:
        refs: list[str] = []
        writing_context = trace.scene_writing_context
        if writing_context is not None:
            refs.extend(list(writing_context.source_refs))
        progression = trace.scene_progression_statement
        if progression is not None:
            refs.extend(list(progression.source_refs))
        refs.extend(
            self._framework_context_source_refs(
                context.get("generator_framework_context") or {}
            )
        )
        composition_id = self._framework_composition_id(
            context.get("generator_framework_context") or {}
        )
        if composition_id:
            refs.insert(0, f"framework_composition:{composition_id}")
        return self._unique_strings(refs)

    def _select_current_chapter(
        self,
        chapters: list[Chapter],
        chapter_id: str | None = None,
    ) -> Chapter | None:
        if chapter_id:
            for chapter in chapters:
                if chapter.chapter_id == chapter_id:
                    return chapter
            return None
        story_progress_chapter = self._select_story_progress_chapter(chapters)
        if story_progress_chapter is not None:
            return story_progress_chapter
        for chapter in chapters:
            if chapter.detail_level == "current_chapter_brief":
                return chapter
        for chapter in chapters:
            if chapter.status == "active":
                return chapter
        for chapter in chapters:
            if chapter.chapter_framework_id and chapter.scene_count >= 1:
                return chapter
        return None

    def _select_story_progress_chapter(self, chapters: list[Chapter]) -> Chapter | None:
        progress_path = self.data_dir / "story_progress.json"
        if not self.store.exists(progress_path):
            return None
        try:
            progress = self.store.read(progress_path)
        except Exception:
            return None
        if not isinstance(progress, dict):
            return None
        status = str(progress.get("story_progress_status") or "").strip()
        if status not in {"current_chapter_active", "next_chapter_active"}:
            return None
        progress_chapter_id = str(progress.get("current_chapter_id") or "").strip()
        progress_chapter_index = int(progress.get("current_chapter_index") or 0)
        for chapter in chapters:
            if progress_chapter_id and chapter.chapter_id == progress_chapter_id:
                return chapter
        if progress_chapter_index:
            for chapter in chapters:
                if chapter.chapter_index == progress_chapter_index:
                    return chapter
        return None

    def _find_built_chapter_framework(
        self,
        package: FrameworkPackage,
        chapter: Chapter,
    ) -> ChapterFramework | None:
        for framework in package.built_chapter_frameworks:
            if framework.chapter_framework_id != chapter.chapter_framework_id:
                continue
            return framework
        return None

    def _has_confirm_decision(
        self,
        decisions: list[dict[str, Any]],
        target_type: str,
    ) -> bool:
        return any(
            decision.get("decision_type") == "confirm"
            and decision.get("target_type") == target_type
            for decision in decisions
        )

    def _scene_id(self, chapter: Chapter, scene_index: int) -> str:
        return f"scene_m7_{chapter.chapter_id}_{scene_index:03d}"

    def _current_chapter_brief_summary(self, chapter: Chapter) -> str:
        brief = self._current_chapter_brief_dict(chapter)
        return self._short_context_text(
            str(brief.get("summary_for_scene_generation") or ""),
            max_len=1200,
        )

    def _current_chapter_scene_beats(self, chapter: Chapter) -> list[dict[str, Any]]:
        chapter_payload = model_to_dict(chapter)
        raw_beats = safe_list(chapter_payload.get("chapter_scene_beats"))
        if not raw_beats:
            embedded_brief = chapter_payload.get("current_chapter_brief")
            if isinstance(embedded_brief, dict):
                raw_beats = safe_list(embedded_brief.get("chapter_scene_beats"))
        brief = self._current_chapter_brief_dict(chapter)
        if not raw_beats:
            raw_beats = safe_list(brief.get("chapter_scene_beats"))
        beats: list[dict[str, Any]] = []
        for item in raw_beats:
            if hasattr(item, "model_dump"):
                data = item.model_dump(mode="json")
            elif hasattr(item, "dict"):
                data = item.dict()
            elif isinstance(item, dict):
                data = dict(item)
            else:
                continue
            try:
                beat_chapter_id = str(data.get("chapter_id") or chapter.chapter_id)
                scene_index = int(data.get("scene_index") or 0)
            except (TypeError, ValueError):
                continue
            if beat_chapter_id != chapter.chapter_id:
                continue
            if scene_index < 1:
                continue
            data["chapter_id"] = beat_chapter_id
            data["scene_index"] = scene_index
            data["scene_count"] = int(data.get("scene_count") or chapter.scene_count or 0)
            for nested_key in [
                "required_progression_delta",
                "continuity_anchors",
                "stage_strategy",
                "autonomy_space",
            ]:
                nested = data.get(nested_key)
                data[nested_key] = dict(nested) if isinstance(nested, dict) else {}
            data["avoid_repetition_axes"] = [
                str(value or "").strip()
                for value in safe_list(data.get("avoid_repetition_axes"))
                if str(value or "").strip()
            ]
            data["source_refs"] = [
                str(value or "").strip()
                for value in safe_list(data.get("source_refs"))
                if str(value or "").strip()
            ]
            beats.append(data)
        return sorted(beats, key=lambda beat: int(beat.get("scene_index") or 0))

    def _chapter_scene_beat_for_scene(
        self,
        chapter: Chapter,
        scene_index: int,
    ) -> dict[str, Any]:
        for beat in self._current_chapter_scene_beats(chapter):
            try:
                if int(beat.get("scene_index") or 0) == int(scene_index):
                    return dict(beat)
            except (TypeError, ValueError):
                continue
        return {}

    def _chapter_scene_beat_history(
        self,
        chapter: Chapter,
        scene_index: int,
    ) -> list[dict[str, Any]]:
        beats = self._current_chapter_scene_beats(chapter)
        if not beats:
            return []
        if len(beats) <= 5:
            return beats
        lower = max(1, int(scene_index or 1) - 2)
        upper = int(scene_index or 1) + 2
        bounded = [
            beat
            for beat in beats
            if lower <= int(beat.get("scene_index") or 0) <= upper
        ]
        return bounded[:5]

    def _scene_goal_from_chapter_scene_beat(
        self,
        chapter_scene_beat: dict[str, Any],
        chapter: Chapter,
        scene_index: int,
    ) -> str:
        if not isinstance(chapter_scene_beat, dict) or not chapter_scene_beat:
            return ""
        scene_function = self._short_context_text(
            str(chapter_scene_beat.get("scene_function") or ""),
            max_len=320,
        )
        progression = chapter_scene_beat.get("required_progression_delta") or {}
        if not isinstance(progression, dict):
            progression = {}
        new_information = self._short_context_text(
            str(progression.get("new_information") or ""),
            max_len=240,
        )
        conflict_turn = self._short_context_text(
            str(progression.get("conflict_turn") or ""),
            max_len=240,
        )
        character_state_delta = self._short_context_text(
            str(progression.get("character_state_delta") or ""),
            max_len=220,
        )
        chapter_goal = self._short_context_text(
            chapter.chapter_goal or chapter.summary or "",
            max_len=260,
        )
        parts = [
            f"Current chapter {chapter.chapter_index} scene {scene_index}: {scene_function}"
            if scene_function
            else f"Current chapter {chapter.chapter_index} scene {scene_index}",
        ]
        if new_information:
            parts.append(f"Must add: {new_information}")
        if character_state_delta:
            parts.append(f"Must shift character state by: {character_state_delta}")
        if conflict_turn:
            parts.append(f"Must turn conflict by: {conflict_turn}")
        if chapter_goal:
            parts.append(f"Chapter goal: {chapter_goal}")
        return self._short_context_text(". ".join(parts), max_len=900)

    def _resolve_current_scene_goal(
        self,
        chapter: Chapter,
        scene_index: int,
        *,
        explicit_scene_goal: str = "",
        brief_summary: str = "",
        chapter_scene_beat: dict[str, Any] | None = None,
    ) -> str:
        explicit = self._short_context_text(explicit_scene_goal, max_len=900)
        if explicit:
            return explicit
        beat_goal = self._scene_goal_from_chapter_scene_beat(
            chapter_scene_beat or {},
            chapter,
            scene_index,
        )
        if beat_goal:
            return beat_goal
        brief = self._current_chapter_brief_dict(chapter)
        summary = brief_summary or str(brief.get("summary_for_scene_generation") or "")
        chapter_goal = str(
            brief.get("chapter_goal")
            or chapter.chapter_goal
            or chapter.summary
            or ""
        ).strip()
        scene_fragment = self._extract_scene_goal_fragment(summary, scene_index)
        if scene_fragment:
            return self._short_context_text(
                (
                    f"Current chapter {chapter.chapter_index} scene {scene_index}: "
                    f"{scene_fragment} Chapter goal: {chapter_goal}"
                ),
                max_len=900,
            )
        if summary:
            return self._short_context_text(
                (
                    f"Current chapter {chapter.chapter_index} scene {scene_index}: "
                    f"{summary} Chapter goal: {chapter_goal}"
                ),
                max_len=900,
            )
        if chapter_goal:
            return self._short_context_text(
                (
                    f"Current chapter {chapter.chapter_index} scene {scene_index}: "
                    f"{chapter_goal}"
                ),
                max_len=900,
            )
        return f"Current chapter {chapter.chapter_index} scene {scene_index}: advance the current chapter goal."

    def _current_chapter_brief_dict(self, chapter: Chapter) -> dict[str, Any]:
        if not self.store.exists(self.chapter_plan_draft_file):
            return {}
        try:
            draft = self.store.read(self.chapter_plan_draft_file)
        except StorageError:
            return {}
        if not isinstance(draft, dict):
            return {}
        if int(draft.get("current_chapter_index") or 0) != int(chapter.chapter_index):
            return {}
        brief = draft.get("current_chapter_brief")
        return dict(brief) if isinstance(brief, dict) else {}

    def _extract_scene_goal_fragment(self, summary: str, scene_index: int) -> str:
        text = self._collapse_text(summary)
        if not text:
            return ""
        marker = (
            rf"(?:场景\s*{scene_index}|第\s*{scene_index}\s*[场幕]|"
            rf"scene\s*{scene_index})"
        )
        next_marker = r"(?:场景\s*\d+|第\s*\d+\s*[场幕]|scene\s*\d+)"
        match = re.search(
            rf"{marker}\s*[：:、,\-]?\s*(.*?)(?={next_marker}\s*[：:、,\-]?|$)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._short_context_text(match.group(1), max_len=520)
        return ""

    def _apply_resolved_scene_goal(
        self,
        scene_information: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        resolved_scene_goal = self._short_context_text(
            str(context.get("resolved_scene_goal") or ""),
            max_len=900,
        )
        if not resolved_scene_goal:
            return scene_information
        normalized = dict(scene_information)
        goal = dict(normalized.get("scene_goal") or {})
        original_summary = str(goal.get("summary") or "").strip()
        if original_summary and original_summary != resolved_scene_goal:
            goal["model_summary"] = original_summary
        goal["summary"] = resolved_scene_goal
        goal["source"] = "current_chapter_brief"
        normalized["scene_goal"] = goal
        return normalized

    def _current_scene_goal_story_information(
        self,
        context: dict[str, Any],
    ) -> list[StoryInformationItem]:
        resolved_scene_goal = self._short_context_text(
            str(context.get("resolved_scene_goal") or ""),
            max_len=900,
        )
        if not resolved_scene_goal:
            return []
        try:
            return [
                StoryInformationItem(
                    item_id="current_chapter_resolved_scene_goal",
                    type="scene_goal",
                    content=(
                        "Current chapter scene goal, higher priority than previous "
                        f"chapter memory: {resolved_scene_goal}"
                    ),
                    source_node="SceneGenerationService",
                    priority="must_use",
                    order_hint=0,
                )
            ]
        except ValidationError:
            return []

    def _collapse_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _short_context_text(self, text: str, *, max_len: int = 240) -> str:
        collapsed = self._collapse_text(text)
        if len(collapsed) <= max_len:
            return collapsed
        return collapsed[: max_len - 1].rstrip() + "..."

    def _scene_memory_pack_context(
        self,
        chapter: Chapter,
        scene_index: int,
        scene_id: str | None,
        scene_goal: str,
        scene_location: str,
        characters: list[Character],
        include_provisional: bool,
        force_refresh: bool,
    ) -> dict[str, Any]:
        try:
            pack = self.scene_memory_service.build_scene_pack(
                chapter_id=chapter.chapter_id,
                scene_index=scene_index,
                scene_id=scene_id,
                scene_goal=scene_goal or chapter.chapter_goal or chapter.summary,
                scene_location=scene_location,
                active_character_ids=[
                    character.character_id for character in characters
                ],
                include_provisional=include_provisional,
                force_refresh=force_refresh,
            )
            pack_data = model_to_dict(pack)
            return {
                "scene_memory_pack": pack_data,
                "memory_pack_context": {
                    "must_use_context": pack_data.get("must_use_context", []),
                    "should_use_context": pack_data.get("should_use_context", []),
                    "optional_context": pack_data.get("optional_context", []),
                    "continuity_anchor_context": pack_data.get(
                        "continuity_anchor_context",
                        [],
                    ),
                    "do_not_repeat_context": pack_data.get(
                        "do_not_repeat_context",
                        [],
                    ),
                    "forbidden_or_conflict_context": pack_data.get(
                        "forbidden_or_conflict_context",
                        [],
                    ),
                    "retrieval_gaps": pack_data.get("retrieval_gaps", [])[:10],
                },
                "memory_records": [],
                "memory_pack_warning": "",
            }
        except StorageError as exc:
            return {
                "scene_memory_pack": None,
                "memory_pack_context": {
                    "must_use_context": [],
                    "should_use_context": [],
                    "optional_context": [],
                    "continuity_anchor_context": [],
                    "do_not_repeat_context": [],
                    "forbidden_or_conflict_context": [],
                    "retrieval_gaps": [
                        {
                            "gap_type": "memory_pack_build_fallback",
                            "severity": "warning",
                            "message": str(exc),
                        }
                    ],
                },
                "memory_records": self._read_list_if_present(self.memory_records_file),
                "memory_pack_warning": str(exc),
            }

    def _memory_context_from_scene_pack(
        self,
        scene_pack: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not scene_pack:
            return {
                "scene_memory_pack": None,
                "memory_pack_context": {
                    "must_use_context": [],
                    "should_use_context": [],
                    "optional_context": [],
                    "continuity_anchor_context": [],
                    "do_not_repeat_context": [],
                    "forbidden_or_conflict_context": [],
                    "retrieval_gaps": [
                        {
                            "gap_type": "scene_participation_memory_pack_missing",
                            "severity": "warning",
                            "message": "SceneParticipationPackage did not build a SceneMemoryPack.",
                        }
                    ],
                },
                "memory_records": self._read_list_if_present(self.memory_records_file),
                "memory_pack_warning": "scene_participation_memory_pack_missing",
            }
        return {
            "scene_memory_pack": scene_pack,
            "memory_pack_context": {
                "must_use_context": scene_pack.get("must_use_context", []),
                "should_use_context": scene_pack.get("should_use_context", []),
                "optional_context": scene_pack.get("optional_context", []),
                "continuity_anchor_context": scene_pack.get(
                    "continuity_anchor_context",
                    [],
                ),
                "do_not_repeat_context": scene_pack.get(
                    "do_not_repeat_context",
                    [],
                ),
                "forbidden_or_conflict_context": scene_pack.get(
                    "forbidden_or_conflict_context",
                    [],
                ),
                "retrieval_gaps": scene_pack.get("retrieval_gaps", [])[:10],
            },
            "memory_records": [],
            "memory_pack_warning": "",
        }

    def _character_context_for_scene(
        self,
        *,
        chapter: Chapter,
        scene_index: int,
        scene_id: str,
        characters: list[Character],
        scene_memory_pack: dict[str, Any] | None,
        include_provisional: bool,
    ) -> dict[str, Any]:
        pack_id = ""
        if isinstance(scene_memory_pack, dict):
            pack_id = str(scene_memory_pack.get("scene_memory_pack_id") or "")
        response = self.character_context_builder.build_context(
            CharacterContextBuildRequest(
                character_ids=[character.character_id for character in characters],
                chapter_id=chapter.chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
                scene_memory_pack_id=pack_id,
                include_provisional=include_provisional,
            )
        )
        return model_to_dict(response)

    def _memory_ids_from_context(self, context: dict[str, Any]) -> list[str]:
        scene_pack = context.get("scene_memory_pack") or {}
        pack_ids = self._unique_strings(
            [
                *scene_pack.get("must_use_memory_ids", []),
                *scene_pack.get("should_use_memory_ids", []),
                *scene_pack.get("optional_memory_ids", []),
                *scene_pack.get("continuity_anchor_memory_ids", []),
            ]
        )
        if pack_ids:
            return pack_ids[:25]
        return [
            memory["memory_id"]
            for memory in context.get("memory_records", [])
            if memory.get("memory_id")
        ][:5]

    def _story_information_from_memory_pack(
        self,
        context: dict[str, Any],
    ) -> list[StoryInformationItem]:
        pack_context = context.get("memory_pack_context") or {}
        specs = [
            ("must_use_context", "must_use", 100),
            ("should_use_context", "should_use", 200),
            ("continuity_anchor_context", "should_use", 260),
            ("optional_context", "optional", 300),
            ("do_not_repeat_context", "should_use", 360),
            ("forbidden_or_conflict_context", "do_not_use", 400),
        ]
        items: list[StoryInformationItem] = []
        for group_name, priority, order_base in specs:
            refs = pack_context.get(group_name) or []
            for index, ref in enumerate(refs, start=1):
                if not isinstance(ref, dict):
                    continue
                memory_id = str(ref.get("memory_id") or "")
                summary = str(ref.get("summary") or "").strip()
                if not memory_id or not summary:
                    continue
                keywords = ", ".join(
                    [
                        str(keyword)
                        for keyword in (ref.get("keywords") or [])[:6]
                        if keyword
                    ]
                )
                role = str(ref.get("injection_role") or priority)
                content = f"Memory {memory_id} ({role}): {summary}"
                if keywords:
                    content += f" Keywords: {keywords}."
                downrank_reason = str(ref.get("downrank_reason") or "").strip()
                if downrank_reason:
                    content += f" Context note: {downrank_reason}."
                try:
                    item_type = (
                        "anti_repeat_guidance"
                        if group_name == "do_not_repeat_context"
                        else "memory_context"
                    )
                    items.append(
                        StoryInformationItem(
                            item_id=f"memory_pack_{group_name}_{memory_id}",
                            type=item_type,
                            content=content,
                            source_node="SceneMemoryPack",
                            priority=priority,
                            order_hint=order_base + index,
                        )
                    )
                except ValidationError:
                    continue
        return items

    def _story_information_summary(self, scene: Scene | None) -> list[str]:
        if scene is None:
            return []
        return [
            item.content
            for item in scene.generation_trace.story_information_list
            if item.priority in {"must_use", "should_use"}
        ][:8]

    def _dedupe_story_information(
        self,
        items: list[StoryInformationItem],
    ) -> list[StoryInformationItem]:
        seen: set[str] = set()
        deduped: list[StoryInformationItem] = []
        for item in items:
            key = item.item_id or item.content
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _raise_scene_generation_not_ready(
        self,
        readiness: SceneGenerationReadyStatus,
    ) -> None:
        raise StorageError(
            "SCENE_GENERATION_NOT_READY: Please confirm World Canvas, main cast, chapter route, current chapter brief, and scene count before generating the first scene. "
            + "; ".join(readiness.issues)
        )

    def _raise_scene_participation_confirmation_required(
        self,
        readiness: Any,
    ) -> None:
        payload = {
            "message": "Scene participation needs user confirmation before scene generation.",
            "recommended_action": "review_scene_participant_candidates",
            "pending_creation_candidate_ids": list(
                getattr(readiness, "pending_creation_candidate_ids", []) or []
            ),
            "unresolved_required_need_ids": list(
                getattr(readiness, "unresolved_required_need_ids", []) or []
            ),
            "blocking_issues": list(getattr(readiness, "blocking_issues", []) or []),
            "readiness": model_to_dict(readiness)
            if isinstance(readiness, BaseModel)
            else {},
        }
        raise StorageError(
            "SCENE_PARTICIPATION_CONFIRMATION_REQUIRED: "
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )

    def _has_midnight_only_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "midnight" in text.lower()
            or "零点" in text
            or "午 夜".replace(" ", "") in text
            for text in hard_rule_texts
        )

    def _claims_non_midnight_trigger(self, text: str) -> bool:
        trigger_markers = ["触发", "鸣响", "钟声", "异常", "trigger", "ring"]
        non_midnight_markers = [
            "随机触发",
            "随时触发",
            "任意时间触发",
            "白天触发",
            "非零点触发",
            "不受时间限制",
            "不需要零点",
            "雨夜触发",
            "daytime",
            "randomly trigger",
        ]
        return any(marker in text for marker in trigger_markers) and any(
            marker in text for marker in non_midnight_markers
        )

    def _has_no_free_memory_creation_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "memory_cost" in text
            or (
                "新记忆" in text
                and any(marker in text for marker in ["不会", "不能", "不允许"])
            )
            for text in hard_rule_texts
        )

    def _claims_free_memory_creation(self, text: str) -> bool:
        return self._contains_unnegated_marker(
            text,
            [
                "凭空获得新记忆",
                "凭空创造新记忆",
                "创造新记忆",
                "植入新记忆",
                "生成新记忆",
            ],
        )

    def _has_no_free_memory_reversal_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "no_free_reversal" in text
            or (
                "无代价" in text
                and any(marker in text for marker in ["撤销", "恢复", "找回", "记忆"])
            )
            for text in hard_rule_texts
        )

    def _claims_free_memory_reversal(self, text: str) -> bool:
        return self._contains_unnegated_marker(
            text,
            [
                "无代价恢复",
                "无代价撤销",
                "直接恢复全部记忆",
                "立刻恢复全部记忆",
                "完全找回记忆且没有代价",
                "不付代价恢复",
            ],
        )

    def _contains_unnegated_marker(self, text: str, markers: list[str]) -> bool:
        lower_text = text.lower()
        for marker in markers:
            lower_marker = marker.lower()
            start = 0
            while True:
                index = lower_text.find(lower_marker, start)
                if index < 0:
                    break
                sentence = self._claim_sentence_window(text, index, index + len(marker))
                marker_offset = index - self._sentence_start_index(text, index)
                if not self._is_negated_claim_sentence(sentence, marker_offset):
                    return True
                start = index + len(marker)
        return False

    def _claim_sentence_window(self, text: str, start: int, end: int) -> str:
        sentence_start = self._sentence_start_index(text, start)
        sentence_end = len(text)
        for separator in ["\n", "。", "！", "？", ".", "!", "?", ";", "；"]:
            index = text.find(separator, end)
            if index >= 0:
                sentence_end = min(sentence_end, index)
        return text[sentence_start:sentence_end]

    def _sentence_start_index(self, text: str, start: int) -> int:
        sentence_start = 0
        for separator in ["\n", "。", "！", "？", ".", "!", "?", ";", "；"]:
            index = text.rfind(separator, 0, start)
            if index >= 0:
                sentence_start = max(sentence_start, index + len(separator))
        return sentence_start

    def _is_negated_claim_sentence(self, sentence: str, marker_offset: int) -> bool:
        prefix = sentence[: max(marker_offset, 0)].lower()
        full_sentence = sentence.lower()
        negation_markers = [
            "不要",
            "不得",
            "不能",
            "不会",
            "不应",
            "不许",
            "禁止",
            "避免",
            "不允许",
            "并非",
            "不是",
            "不可",
            "不再",
            "不该",
            "无需",
            "do not",
            "does not",
            "must not",
            "should not",
            "cannot",
            "can't",
            "forbid",
            "forbidden",
            "prohibit",
            "prohibited",
            "avoid",
        ]
        if any(marker in prefix[-24:] for marker in negation_markers):
            return True
        constraint_markers = ["rule", "constraint", "forbidden", "avoid", "禁止", "不得", "不要"]
        if any(marker in full_sentence for marker in ["without", "free of"]):
            return any(marker in full_sentence for marker in constraint_markers)
        return False

    def _unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
