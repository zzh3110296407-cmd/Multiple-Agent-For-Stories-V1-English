import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.agents.scene_revision_agent import SceneRevisionAgent
from app.backend.core.config import settings
from app.backend.models.chapter import Chapter
from app.backend.models.character import Character
from app.backend.models.decision import Decision
from app.backend.models.framework_package import ChapterFramework, FrameworkPackage
from app.backend.models.relationship import Relationship
from app.backend.models.scene import Scene
from app.backend.models.quality import QualityReport, to_embedded_scene_quality_report
from app.backend.models.scene_generation import SceneDraftContent, SceneQualityReport
from app.backend.models.scene_revision import (
    SCENE_WRITING_REPAIR_ENTRY_SCHEMA_VERSION,
    SceneRevisionCandidate,
    SceneRevisionResponse,
    SceneWritingRepairEntryResponse,
)
from app.backend.models.scene_gate_repair import (
    SceneRevisionPlan,
    SceneRevisionPlanAction,
)
from app.backend.models.world_canvas import WorldCanvas
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.abcd_runtime_gate_integration_service import (
    ABCDRuntimeGateIntegrationService,
)
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.services.continuity_gate_service import (
    ContinuityGateService,
    SceneConfirmationGuard,
)
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.quality_check_service import QualityCheckService
from app.backend.services.scene_character_visibility import text_mentions_character
from app.backend.services.scene_generation_service import SceneGenerationService
from app.backend.services.world_rule_timing import (
    has_period_bound_exchange_rule,
    premature_period_exchange_claim,
)
from app.backend.services.tracing_service import traceable_operation
from app.backend.storage.json_store import JsonStore, StorageError


LOGGER = logging.getLogger(__name__)


LOCAL_PROJECT_ID = "local_project"
SCENE_REVISION_VERSION_ID = "version_scene_m8_001"
REVISION_ALLOWED_SCENE_STATUSES = {"draft", "revised"}
REVISION_LOCKED_SCENE_STATUSES = {"confirmed", "committed"}
SHANGHAI_TZ = timezone(timedelta(hours=8))
REVISION_INTERNAL_PROSE_MARKERS = (
    "Context JSON",
    "Revision beat",
    "Revision:",
    "revision_prompt",
    "revised_prose_text",
    "Provider",
    "HTTP error",
    "外部模型",
    "错误摘要",
    "修订目标是",
    "修改当前幕",
    "不要自动确认修订",
)
SCENE_WRITING_REPAIR_ALLOWED_ACTION = "rewrite_scene_prose"
SCENE_WRITING_REPAIR_UPSTREAM_ACTIONS = {
    "refresh_story_information_package",
    "refresh_scene_information",
    "refresh_memory_retrieval",
    "regenerate_memory_extraction_candidates",
    "refresh_scene_participation",
    "refresh_runtime_evidence",
    "rerun_quality_gate",
    "rerun_continuity_gate",
}
SCENE_WRITING_REPAIR_STOP_ACTIONS = {
    "stop_for_user_confirmation",
    "stop_for_expert_review",
}
SCENE_WRITING_REPAIR_UNSAFE_PROMPT_MARKERS = (
    "raw_prompt",
    "raw response",
    "raw_response",
    "hidden_reasoning",
    "hidden prompt",
    "hidden_prompt",
    "chain-of-thought",
    "chain_of_thought",
    "traceback",
    "provider raw",
    "sk-",
    "lsv2_",
)
SCENE_WRITING_REPAIR_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9._-]*"),
    re.compile(r"(?i)\blsv2_[A-Za-z0-9._-]*"),
)
SCENE_WRITING_REPAIR_UNSAFE_PROMPT_PATTERNS = tuple(
    re.compile(re.escape(marker), re.IGNORECASE)
    for marker in SCENE_WRITING_REPAIR_UNSAFE_PROMPT_MARKERS
    if marker not in {"sk-", "lsv2_"}
)


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class SceneRevisionService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        model_gateway: ModelGatewayService | None = None,
        framework_service: FrameworkPackageService | None = None,
        scene_generation_service: SceneGenerationService | None = None,
        scene_revision_agent: SceneRevisionAgent | None = None,
        quality_check_service: QualityCheckService | None = None,
        continuity_gate_service: ContinuityGateService | None = None,
        abcd_runtime_gate_service: ABCDRuntimeGateIntegrationService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_file = self.data_dir / "project.json"
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.scenes_file = self.data_dir / "scenes.json"
        self.continuity_issues_file = self.data_dir / "continuity_issues.json"
        self.quality_reports_file = self.data_dir / "quality_reports.json"
        self.events_file = self.data_dir / "events.json"
        self.state_changes_file = self.data_dir / "state_changes.json"
        self.memory_records_file = self.data_dir / "memory_records.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_service = framework_service or FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.scene_generation_service = scene_generation_service or SceneGenerationService(
            store=self.store,
            data_dir=self.data_dir,
            model_gateway=self.model_gateway,
            framework_service=self.framework_service,
        )
        self.scene_revision_agent = scene_revision_agent or SceneRevisionAgent(
            model_gateway=self.model_gateway,
        )
        self.quality_check_service = quality_check_service or QualityCheckService(
            store=self.store,
            data_dir=self.data_dir,
            model_gateway=self.model_gateway,
            framework_service=self.framework_service,
        )
        self.continuity_gate_service = continuity_gate_service or ContinuityGateService(
            store=self.store,
            data_dir=self.data_dir,
            model_gateway=self.model_gateway,
        )
        self.scene_confirmation_guard = SceneConfirmationGuard(
            self.continuity_gate_service
        )
        self.abcd_runtime_gate_service = abcd_runtime_gate_service or (
            ABCDRuntimeGateIntegrationService(
                store=self.store,
                data_dir=self.data_dir,
            )
        )

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_revision_candidate(self, scene_id: str) -> SceneRevisionResponse:
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_REVISION_SCENE_MISSING: Scene does not exist.")
        candidate = self._active_candidate(scene)
        return SceneRevisionResponse(
            success=True,
            scene=model_to_dict(scene),
            candidate=model_to_dict(candidate) if candidate else None,
            current_candidate=model_to_dict(candidate) if candidate else None,
            revision_intent=candidate.revision_intent if candidate else "",
            quality_report=candidate.quality_report if candidate else None,
        )

    @traceable_operation("SceneRevisionService.revise_scene", tags=["scene_revision"])
    def revise_scene(
        self,
        scene_id: str,
        revision_prompt: str,
        force_hard_rule_override: bool = False,
        source_continuity_issue_id: str = "",
        allow_confirmed_scene: bool = False,
    ) -> SceneRevisionResponse:
        clean_prompt = revision_prompt.strip()
        if not clean_prompt:
            raise StorageError("SCENE_REVISION_PROMPT_REQUIRED: Revision prompt is empty.")

        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_REVISION_SCENE_MISSING: Scene does not exist.")
        self._ensure_scene_revision_open(
            scene,
            allow_confirmed_scene=allow_confirmed_scene,
        )

        context = self.load_revision_context(
            scene=scene,
            revision_prompt=clean_prompt,
            force_hard_rule_override=force_hard_rule_override,
        )
        revision_intent = self.classify_revision_intent(clean_prompt, context)
        context["revision_intent"] = revision_intent
        hard_rule_warnings = self.detect_hard_rule_warnings(
            revision_prompt=clean_prompt,
            revision_intent=revision_intent,
            revised_text="",
            world_canvas=context.get("world_canvas") or {},
        )
        if hard_rule_warnings and not force_hard_rule_override:
            raise StorageError(
                "HARD_RULE_CONFLICT: Revision prompt appears to conflict with World Canvas hard rules."
            )

        candidate = self.generate_revision_candidate(
            scene=scene,
            context=context,
            revision_prompt=clean_prompt,
            revision_intent=revision_intent,
            force_hard_rule_override=force_hard_rule_override,
            prompt_hard_rule_warnings=hard_rule_warnings,
            source_continuity_issue_id=source_continuity_issue_id,
        )
        updated_scene = self.save_revision_candidate(scene, candidate)
        return SceneRevisionResponse(
            success=True,
            scene=model_to_dict(updated_scene),
            candidate=model_to_dict(candidate),
            current_candidate=model_to_dict(candidate),
            revision_intent=revision_intent,
            quality_report=candidate.quality_report,
        )

    @traceable_operation(
        "SceneRevisionService.revise_scene_from_plan",
        tags=["scene_revision", "scene_gate_repair", "phase85d_m5"],
    )
    def revise_scene_from_plan(
        self,
        scene_id: str,
        revision_plan: SceneRevisionPlan | dict[str, Any],
        *,
        source_gate_run_id: str = "",
        source_analysis_id: str = "",
        force_hard_rule_override: bool = False,
    ) -> SceneWritingRepairEntryResponse:
        try:
            plan = self._coerce_revision_plan(revision_plan)
        except ValidationError:
            return self._scene_writing_repair_blocked_response(
                status="blocked_invalid_plan",
                scene_id=scene_id,
                blocked_reasons=["invalid_scene_revision_plan"],
            )

        response_gate_run_id = (source_gate_run_id or plan.gate_run_id).strip()
        response_analysis_id = (source_analysis_id or plan.analysis_id).strip()
        if plan.scene_id != scene_id:
            return self._scene_writing_repair_blocked_response(
                status="blocked_scene_mismatch",
                scene_id=scene_id,
                plan=plan,
                source_gate_run_id=response_gate_run_id,
                source_analysis_id=response_analysis_id,
                blocked_reasons=["revision_plan_scene_id_does_not_match_request"],
            )

        blocked = self._scene_writing_repair_executability_stop(
            plan,
            source_gate_run_id=response_gate_run_id,
            source_analysis_id=response_analysis_id,
        )
        if blocked is not None:
            return blocked

        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_REVISION_SCENE_MISSING: Scene does not exist.")
        self._ensure_scene_revision_open(scene)

        prompt_bundle = self._compile_scene_writing_repair_prompt(
            plan=plan,
            scene=scene,
            source_gate_run_id=response_gate_run_id,
            source_analysis_id=response_analysis_id,
        )
        revision_prompt = prompt_bundle["revision_prompt"]
        revision_intent = prompt_bundle["revision_intent"]
        context = self.load_revision_context(
            scene=scene,
            revision_prompt=revision_prompt,
            force_hard_rule_override=force_hard_rule_override,
        )
        context["revision_intent"] = revision_intent
        context["structured_repair_entry"] = prompt_bundle["structured_context_patch"]

        hard_rule_warnings = self.detect_hard_rule_warnings(
            revision_prompt=revision_prompt,
            revision_intent=revision_intent,
            revised_text="",
            world_canvas=context.get("world_canvas") or {},
        )
        if hard_rule_warnings and not force_hard_rule_override:
            raise StorageError(
                "HARD_RULE_CONFLICT: Structured repair prompt appears to conflict with World Canvas hard rules."
            )

        candidate = self.generate_revision_candidate(
            scene=scene,
            context=context,
            revision_prompt=revision_prompt,
            revision_intent=revision_intent,
            force_hard_rule_override=force_hard_rule_override,
            prompt_hard_rule_warnings=hard_rule_warnings,
        )
        candidate = self._attach_scene_writing_repair_trace(
            candidate=candidate,
            plan=plan,
            source_gate_run_id=response_gate_run_id,
            source_analysis_id=response_analysis_id,
            structured_repair_entry_id=prompt_bundle["structured_repair_entry_id"],
            structured_repair_prompt_signature=prompt_bundle["prompt_signature"],
        )
        updated_scene = self.save_revision_candidate(scene, candidate)
        return SceneWritingRepairEntryResponse(
            success=True,
            status="candidate_created",
            scene_id=scene_id,
            revision_id=candidate.revision_id,
            revision_plan_id=plan.revision_plan_id,
            revision_plan_signature=plan.revision_plan_signature,
            source_gate_run_id=response_gate_run_id,
            source_analysis_id=response_analysis_id,
            round_index=plan.round_index,
            executed_action_ids=[
                action.action_id for action in plan.repair_actions
                if action.action_type == SCENE_WRITING_REPAIR_ALLOWED_ACTION
            ],
            skipped_action_ids=[],
            blocked_reasons=[],
            candidate=model_to_dict(candidate),
            scene=model_to_dict(updated_scene),
            safe_user_summary=prompt_bundle["safe_user_summary"],
            internal_trace_refs=[
                f"scene_revision_plan:{plan.revision_plan_id}",
                f"gate_run:{response_gate_run_id}",
                f"scene_gate_analysis:{response_analysis_id}",
                f"structured_repair_entry:{prompt_bundle['structured_repair_entry_id']}",
            ],
            no_write_authority_summary=(
                "M5 created one scene revision candidate only; no scene confirmation, "
                "canon writeback, memory writeback, continuity lifecycle mutation, API, "
                "or UI exposure is authorized."
            ),
        )

    def _coerce_revision_plan(
        self,
        revision_plan: SceneRevisionPlan | dict[str, Any],
    ) -> SceneRevisionPlan:
        if isinstance(revision_plan, SceneRevisionPlan):
            return revision_plan
        return SceneRevisionPlan(**model_to_dict(revision_plan))

    def _scene_writing_repair_executability_stop(
        self,
        plan: SceneRevisionPlan,
        *,
        source_gate_run_id: str,
        source_analysis_id: str,
    ) -> SceneWritingRepairEntryResponse | None:
        action_types = [action.action_type for action in plan.repair_actions]
        action_type_set = set(action_types)
        skipped_action_ids = [action.action_id for action in plan.repair_actions]

        if plan.plan_status == "no_repair_needed" or plan.recommended_next_step == "no_repair_needed":
            return self._scene_writing_repair_blocked_response(
                status="no_repair_needed",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_has_no_repair_needed"],
            )
        if plan.requires_expert_review or "stop_for_expert_review" in action_type_set:
            return self._scene_writing_repair_blocked_response(
                status="blocked_requires_expert_review",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_requires_expert_review"],
            )
        if plan.requires_user_confirmation or "stop_for_user_confirmation" in action_type_set:
            return self._scene_writing_repair_blocked_response(
                status="blocked_requires_user_confirmation",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_requires_user_confirmation"],
            )
        if plan.may_touch_user_requested_content:
            return self._scene_writing_repair_blocked_response(
                status="blocked_requires_user_confirmation",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_may_touch_user_requested_content"],
            )
        if not plan.auto_repair_plan_allowed:
            return self._scene_writing_repair_blocked_response(
                status="blocked_plan_not_auto_repairable",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_auto_repair_not_allowed"],
            )
        if plan.plan_status != "ready_for_repair" or plan.recommended_next_step != "execute_repair_plan_later":
            if plan.plan_status == "refresh_required":
                return self._scene_writing_repair_blocked_response(
                    status="blocked_requires_upstream_refresh",
                    scene_id=plan.scene_id,
                    plan=plan,
                    source_gate_run_id=source_gate_run_id,
                    source_analysis_id=source_analysis_id,
                    skipped_action_ids=skipped_action_ids,
                    blocked_reasons=["revision_plan_requires_upstream_refresh"],
                )
            return self._scene_writing_repair_blocked_response(
                status="blocked_invalid_plan",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_status_or_next_step_not_executable"],
            )
        if not action_types:
            return self._scene_writing_repair_blocked_response(
                status="blocked_unsupported_action_type",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                blocked_reasons=["revision_plan_has_no_repair_actions"],
            )
        if action_type_set & SCENE_WRITING_REPAIR_UPSTREAM_ACTIONS:
            return self._scene_writing_repair_blocked_response(
                status="blocked_requires_upstream_refresh",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_contains_upstream_refresh_action"],
            )
        if action_type_set & SCENE_WRITING_REPAIR_STOP_ACTIONS:
            return self._scene_writing_repair_blocked_response(
                status="blocked_unsupported_action_type",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=skipped_action_ids,
                blocked_reasons=["revision_plan_contains_stop_action"],
            )
        unsupported_actions = [
            action
            for action in plan.repair_actions
            if action.action_type != SCENE_WRITING_REPAIR_ALLOWED_ACTION
            or action.target_repair_system != "writer"
        ]
        if unsupported_actions:
            return self._scene_writing_repair_blocked_response(
                status="blocked_unsupported_action_type",
                scene_id=plan.scene_id,
                plan=plan,
                source_gate_run_id=source_gate_run_id,
                source_analysis_id=source_analysis_id,
                skipped_action_ids=[action.action_id for action in unsupported_actions],
                blocked_reasons=["revision_plan_contains_non_writer_action"],
            )
        return None

    def _compile_scene_writing_repair_prompt(
        self,
        *,
        plan: SceneRevisionPlan,
        scene: Scene,
        source_gate_run_id: str,
        source_analysis_id: str,
    ) -> dict[str, Any]:
        writer_actions = [
            action
            for action in plan.repair_actions
            if action.action_type == SCENE_WRITING_REPAIR_ALLOWED_ACTION
        ]
        action_payloads = [
            self._scene_writing_repair_action_payload(action)
            for action in writer_actions
        ]
        context_patch = {
            "schema_version": SCENE_WRITING_REPAIR_ENTRY_SCHEMA_VERSION,
            "revision_plan_id": plan.revision_plan_id,
            "revision_plan_signature": plan.revision_plan_signature,
            "source_gate_run_id": source_gate_run_id,
            "source_analysis_id": source_analysis_id,
            "round_index": plan.round_index,
            "source_finding_ids": plan.finding_ids,
            "source_finding_signatures": plan.finding_signatures,
            "action_types": [action.action_type for action in writer_actions],
            "repair_action_ids": [action.action_id for action in writer_actions],
            "repair_action_signatures": [
                action.action_signature for action in writer_actions
            ],
            "forbidden_changes": plan.forbidden_changes,
            "safe_user_summary": self._safe_repair_text(plan.safe_user_summary, 800),
        }
        prompt_payload = {
            "schema_version": SCENE_WRITING_REPAIR_ENTRY_SCHEMA_VERSION,
            "instruction": (
                "Create a new revision candidate only. Rewrite only the current "
                "scene prose/synopsis needed by the listed writer repair actions."
            ),
            "revision_plan_id": plan.revision_plan_id,
            "revision_plan_signature": plan.revision_plan_signature,
            "source_gate_run_id": source_gate_run_id,
            "source_analysis_id": source_analysis_id,
            "source_finding_ids": plan.finding_ids,
            "source_finding_signatures": plan.finding_signatures,
            "source_categories": self._unique_strings(
                [
                    category
                    for action in writer_actions
                    for category in action.source_categories
                ]
            ),
            "actions": action_payloads,
            "forbidden_changes": plan.forbidden_changes,
            "user_intent_preservation_notes": [
                self._safe_repair_text(note, 400)
                for note in plan.user_intent_preservation_notes
            ],
            "safe_user_summary": self._safe_repair_text(plan.safe_user_summary, 800),
            "mandatory_boundaries": [
                "Create a new revision candidate only.",
                "Rewrite only the current scene prose/synopsis needed by the listed writer repair actions.",
                "Preserve ProjectStoryPremise.",
                "Preserve confirmed world hard rules.",
                "Preserve character identity, goals, knowledge limits, and active scene participants.",
                "Do not create or confirm characters.",
                "Do not resolve continuity issues.",
                "Do not write memory.",
                "Do not confirm the scene.",
                "Do not commit canon facts.",
                "Do not replace prompt-first content with demo or fallback content.",
            ],
            "current_scene_ref": {
                "scene_id": scene.scene_id,
                "chapter_id": scene.chapter_id,
                "scene_index": scene.scene_index,
                "version_id": scene.version_id,
            },
        }
        revision_prompt = (
            "Structured Scene Gate Repair Entry\n"
            + json.dumps(prompt_payload, ensure_ascii=False, indent=2, sort_keys=True)
        )
        prompt_signature = self._stable_hash(
            "scene_writing_repair_prompt_signature",
            {
                "revision_prompt": revision_prompt,
                "scene_id": scene.scene_id,
                "scene_version_id": scene.version_id,
                "synopsis": scene.synopsis or (scene.content.synopsis if scene.content else ""),
                "prose_text": scene.prose_text or (scene.content.prose_text if scene.content else ""),
            },
        )
        entry_id = self._stable_hash(
            "scene_writing_repair_entry",
            {
                "scene_id": scene.scene_id,
                "revision_plan_id": plan.revision_plan_id,
                "revision_plan_signature": plan.revision_plan_signature,
                "prompt_signature": prompt_signature,
            },
        )
        return {
            "revision_prompt": revision_prompt,
            "revision_intent": "structured_gate_repair",
            "structured_context_patch": context_patch,
            "prompt_signature": prompt_signature,
            "structured_repair_entry_id": entry_id,
            "safe_user_summary": self._safe_repair_text(plan.safe_user_summary, 800),
        }

    def _scene_writing_repair_action_payload(
        self,
        action: SceneRevisionPlanAction,
    ) -> dict[str, Any]:
        return {
            "action_id": action.action_id,
            "action_signature": action.action_signature,
            "action_type": action.action_type,
            "target_repair_system": action.target_repair_system,
            "root_cause_layer": action.root_cause_layer,
            "source_finding_ids": action.source_finding_ids,
            "source_finding_signatures": action.source_finding_signatures,
            "source_categories": action.source_categories,
            "action_summary": self._safe_repair_text(action.action_summary, 500),
            "repair_instruction": self._safe_repair_text(action.repair_instruction, 700),
            "allowed_change_scope": action.allowed_change_scope,
            "forbidden_changes": action.forbidden_changes,
        }

    def _attach_scene_writing_repair_trace(
        self,
        *,
        candidate: SceneRevisionCandidate,
        plan: SceneRevisionPlan,
        source_gate_run_id: str,
        source_analysis_id: str,
        structured_repair_entry_id: str,
        structured_repair_prompt_signature: str,
    ) -> SceneRevisionCandidate:
        writer_actions = [
            action
            for action in plan.repair_actions
            if action.action_type == SCENE_WRITING_REPAIR_ALLOWED_ACTION
        ]
        return SceneRevisionCandidate(
            **{
                **model_to_dict(candidate),
                "source_revision_plan_id": plan.revision_plan_id,
                "source_revision_plan_signature": plan.revision_plan_signature,
                "source_gate_run_id": source_gate_run_id,
                "source_analysis_id": source_analysis_id,
                "source_repair_action_ids": [
                    action.action_id for action in writer_actions
                ],
                "source_repair_action_signatures": [
                    action.action_signature for action in writer_actions
                ],
                "source_finding_ids": plan.finding_ids,
                "source_finding_signatures": plan.finding_signatures,
                "structured_repair_entry_id": structured_repair_entry_id,
                "structured_repair_prompt_signature": structured_repair_prompt_signature,
                "repair_round_index": plan.round_index,
                "structured_repair_status": "candidate_created",
                "safe_repair_summary": self._safe_repair_text(
                    plan.safe_user_summary or plan.plan_summary,
                    800,
                ),
            }
        )

    def _scene_writing_repair_blocked_response(
        self,
        *,
        status: str,
        scene_id: str,
        plan: SceneRevisionPlan | None = None,
        source_gate_run_id: str = "",
        source_analysis_id: str = "",
        skipped_action_ids: list[str] | None = None,
        blocked_reasons: list[str] | None = None,
    ) -> SceneWritingRepairEntryResponse:
        return SceneWritingRepairEntryResponse(
            success=False,
            status=status,
            scene_id=scene_id,
            revision_plan_id=plan.revision_plan_id if plan else "",
            revision_plan_signature=plan.revision_plan_signature if plan else "",
            source_gate_run_id=source_gate_run_id or (plan.gate_run_id if plan else ""),
            source_analysis_id=source_analysis_id or (plan.analysis_id if plan else ""),
            round_index=plan.round_index if plan else 0,
            skipped_action_ids=skipped_action_ids or [],
            blocked_reasons=blocked_reasons or [status],
            safe_user_summary=(
                self._safe_repair_text(plan.safe_user_summary, 800)
                if plan
                else "Structured scene repair plan could not be executed."
            ),
            internal_trace_refs=(
                [
                    f"scene_revision_plan:{plan.revision_plan_id}",
                    f"gate_run:{source_gate_run_id or plan.gate_run_id}",
                    f"scene_gate_analysis:{source_analysis_id or plan.analysis_id}",
                ]
                if plan
                else []
            ),
            no_write_authority_summary=(
                "M5 returned a structured stop response and did not create a "
                "revision candidate or mutate story authority files."
            ),
        )

    def _safe_repair_text(self, value: str, limit: int) -> str:
        text = str(value or "").strip()
        for pattern in SCENE_WRITING_REPAIR_SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        for pattern in SCENE_WRITING_REPAIR_UNSAFE_PROMPT_PATTERNS:
            text = pattern.sub("[redacted]", text)
        return text[:limit]

    def _stable_hash(self, prefix: str, payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:24]}"

    @traceable_operation("SceneRevisionService.confirm_revision", tags=["scene_revision"])
    def confirm_revision(
        self,
        scene_id: str,
        revision_id: str,
        user_input: str | None = None,
        accepted_abcd_runtime_issue_ids: list[str] | None = None,
    ) -> SceneRevisionResponse:
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_REVISION_SCENE_MISSING: Scene does not exist.")
        candidate = self._find_revision_candidate(scene, revision_id)
        if candidate is None:
            raise StorageError("SCENE_REVISION_CANDIDATE_MISSING: Revision candidate does not exist.")
        self._ensure_scene_revision_open(
            scene,
            allow_confirmed_scene=(
                candidate.source_scene_status in REVISION_LOCKED_SCENE_STATUSES
            ),
        )
        if candidate.status != "candidate":
            raise StorageError("SCENE_REVISION_CANDIDATE_NOT_ACTIVE: Revision candidate is not active.")
        if scene.active_revision_id != candidate.revision_id:
            raise StorageError("SCENE_REVISION_CANDIDATE_NOT_ACTIVE: Revision candidate is not the active candidate.")
        candidate = self._sync_revision_candidate_quality_report(scene, candidate)
        if candidate.quality_report.blocking_issues:
            raise StorageError(
                "SCENE_REVISION_QUALITY_BLOCKING_ISSUES: Cannot confirm revision while blocking quality issues exist."
            )
        clean_user_input = (user_input or "").strip()
        self._validate_revision_confirmation_gate(
            scene=scene,
            candidate=candidate,
            user_input=clean_user_input,
        )
        if candidate.requires_user_confirmation and not clean_user_input:
            raise StorageError(
                "SCENE_REVISION_CONFIRMATION_INPUT_REQUIRED: Revision requires explicit user confirmation input."
            )
        self.scene_confirmation_guard.require_revision_confirmation_allowed(
            scene.scene_id,
            candidate.revision_id,
        )
        reloaded_scene = self._find_scene_by_id(scene_id)
        if reloaded_scene is not None:
            scene = reloaded_scene
            candidate = self._find_revision_candidate(scene, revision_id) or candidate
        self.abcd_runtime_gate_service.require_final_confirmation_allowed(
            scene.scene_id,
            user_confirmation_text=clean_user_input,
            accepted_issue_ids=accepted_abcd_runtime_issue_ids,
        )

        revised_scene = self.apply_revision_candidate(scene, candidate)
        self._sync_linked_continuity_issue_after_confirmation(
            candidate=candidate,
            user_input=clean_user_input,
        )
        decision = self.write_revision_decision(
            decision_type="confirm",
            target_id=candidate.revision_id,
            user_input=clean_user_input
            or "User confirmed current scene revision candidate.",
        )
        revised_step = f"scene_{revised_scene.scene_index}_revised"
        self.update_project_step(revised_step, revised_step)
        return SceneRevisionResponse(
            success=True,
            scene=model_to_dict(revised_scene),
            candidate=model_to_dict(
                self._find_revision_candidate(revised_scene, candidate.revision_id)
                or candidate
            ),
            current_candidate=model_to_dict(
                self._find_revision_candidate(revised_scene, candidate.revision_id)
                or candidate
            ),
            revision_intent=candidate.revision_intent,
            quality_report=revised_scene.quality_report,
            decision=decision,
        )

    @traceable_operation("SceneRevisionService.reject_revision", tags=["scene_revision"])
    def reject_revision(
        self,
        scene_id: str,
        revision_id: str,
        user_input: str | None = None,
    ) -> SceneRevisionResponse:
        scene = self._find_scene_by_id(scene_id)
        if scene is None:
            raise StorageError("SCENE_REVISION_SCENE_MISSING: Scene does not exist.")
        candidate = self._find_revision_candidate(scene, revision_id)
        if candidate is None:
            raise StorageError("SCENE_REVISION_CANDIDATE_MISSING: Revision candidate does not exist.")
        if candidate.status != "candidate":
            raise StorageError("SCENE_REVISION_CANDIDATE_NOT_ACTIVE: Revision candidate is not active.")
        if scene.active_revision_id != candidate.revision_id:
            raise StorageError("SCENE_REVISION_CANDIDATE_NOT_ACTIVE: Revision candidate is not the active candidate.")

        timestamp = now_iso()
        updated_history = []
        rejected_candidate = candidate
        for item in scene.revision_history:
            if item.revision_id == revision_id:
                rejected_candidate = SceneRevisionCandidate(
                    **{
                        **model_to_dict(item),
                        "status": "rejected",
                        "updated_at": timestamp,
                    }
                )
                updated_history.append(rejected_candidate)
            else:
                updated_history.append(item)
        updated_scene = Scene(
            **{
                **model_to_dict(scene),
                "revision_history": [model_to_dict(item) for item in updated_history],
                "active_revision_id": ""
                if scene.active_revision_id == revision_id
                else scene.active_revision_id,
                "updated_at": timestamp,
            }
        )
        self._upsert_scene(updated_scene)
        self._sync_linked_continuity_issue_after_rejection(rejected_candidate)
        decision = self.write_revision_decision(
            decision_type="reject",
            target_id=revision_id,
            user_input=(user_input or "").strip()
            or "User rejected current scene revision candidate.",
        )
        return SceneRevisionResponse(
            success=True,
            scene=model_to_dict(updated_scene),
            candidate=model_to_dict(rejected_candidate),
            current_candidate=None,
            revision_intent=rejected_candidate.revision_intent,
            quality_report=rejected_candidate.quality_report,
            decision=decision,
        )

    def load_revision_context(
        self,
        scene: Scene,
        revision_prompt: str,
        force_hard_rule_override: bool,
    ) -> dict[str, Any]:
        model_status = self.model_gateway.validate_model_config()
        if not model_status.configured:
            raise ModelConfigurationError("; ".join(model_status.issues))
        self._ensure_scene_revision_ready(scene)

        world_canvas = self._read_world_canvas()
        characters = self._read_revision_context_characters(scene)
        if not characters:
            raise StorageError("SCENE_REVISION_NOT_READY: Confirmed revision context characters are missing.")
        relationships = self._read_confirmed_relationships()
        chapters = self._read_chapters()
        chapter = self._find_chapter(scene.chapter_id, chapters)
        if chapter is None:
            raise StorageError("SCENE_REVISION_NOT_READY: Current chapter is missing.")
        package = self.framework_service.get_framework_package()
        current_framework = self._find_built_chapter_framework(package, chapter)
        if current_framework is None:
            raise StorageError("SCENE_REVISION_NOT_READY: Current chapter framework is missing.")

        trace = scene.generation_trace
        allowed_character_ids = self._revision_context_character_ids(scene)
        approved_context = {
            "project_id": self._current_project_id(),
            "output_language": self.scene_generation_service._project_output_language(),
            "scene_index": scene.scene_index,
            "scene_count": chapter.scene_count,
            "world_canvas": model_to_dict(world_canvas),
            "characters": [model_to_dict(character) for character in characters],
            "allowed_revision_character_ids": allowed_character_ids,
            "allowed_revision_characters": [
                model_to_dict(character)
                for character in characters
                if character.character_id in set(allowed_character_ids)
            ],
            "relationships": [
                model_to_dict(relationship) for relationship in relationships
            ],
            "chapter": model_to_dict(chapter),
            "current_chapter_framework": model_to_dict(current_framework),
            "framework_package": model_to_dict(package),
            "recent_events": self._read_list_if_present(self.events_file),
            "memory_records": self._read_list_if_present(self.memory_records_file),
            "scene_information": {
                "scene_goal": trace.scene_goal or {},
                "environment": trace.environment or {},
                "role_beats": trace.role_beats,
            },
        }
        return {
            **approved_context,
            "current_scene": model_to_dict(scene),
            "revision_prompt": revision_prompt,
            "force_hard_rule_override": force_hard_rule_override,
        }

    def classify_revision_intent(
        self,
        revision_prompt: str,
        context: dict[str, Any],
    ) -> str:
        text = revision_prompt.lower()
        rule_preservation_markers = [
            "preserve the hard rules",
            "preserve all hard rules",
            "keep the hard rules",
            "keep all hard rules",
            "follow the hard rules",
            "respect the hard rules",
            "do not change the rules",
            "without changing the rules",
            "do not violate",
            "without violating",
            "保持硬规则",
            "保持全部硬规则",
            "保持世界规则",
            "保持全部已确认世界规则",
            "遵守硬规则",
            "遵守世界规则",
            "不改变规则",
            "不修改规则",
            "不违反规则",
            "不违背规则",
            "不得违反规则",
            "不得违背规则",
        ]
        preserves_rules = self._contains_any(text, rule_preservation_markers)
        explicit_rule_conflict_markers = [
            "break rule",
            "ignore rule",
            "bypass rule",
            "violate rule",
            "sun rises",
            "daytime trigger",
            "free memory",
            "without cost",
            "restore memory without",
            "打破规则",
            "忽略规则",
            "绕过规则",
            "违反规则",
            "违背规则",
            "太阳升起",
            "白天触发",
            "无代价",
            "没有代价",
            "免费恢复",
        ]
        if (
            self._contains_any(text, explicit_rule_conflict_markers)
            and not preserves_rules
        ):
            return "hard_rule_conflict"
        explicit_rule_change_markers = [
            "change rule",
            "change the rule",
            "change world setting",
            "rewrite the rule",
            "修改规则",
            "改变规则",
            "更改规则",
            "重写规则",
            "更改设定",
            "修改设定",
        ]
        if (
            self._contains_any(text, explicit_rule_change_markers)
            and not preserves_rules
        ):
            return "world_rule_change"
        outcome_markers = [
            "outcome",
            "result",
            "kill",
            "die",
            "death",
            "release",
            "spare",
            "survive",
            "放走",
            "释放",
            "不杀",
            "不要杀",
            "活下来",
            "结局",
            "结果",
        ]
        outcome_preserve_markers = [
            "outcome unchanged",
            "result unchanged",
            "keep every event outcome",
            "preserve every event outcome",
            "without changing the outcome",
            "do not change the outcome",
            "不改变结果",
            "不改变结局",
            "保持结果",
            "保持结局",
        ]
        if self._contains_any(text, outcome_markers) and not self._contains_any(
            text,
            outcome_preserve_markers,
        ):
            return "event_outcome_change"
        if self._contains_any(
            text,
            ["action", "move", "choice", "动作", "行动", "选择"],
        ):
            return "character_action_change"
        if self._contains_any(
            text,
            ["sad", "grief", "tragic", "tone", "emotion", "更悲伤", "情绪", "语气", "氛围"],
        ):
            return "emotion_tone"
        if self._contains_any(
            text,
            ["detail", "suspense", "pressure", "add", "增加", "细节", "悬疑", "压迫"],
        ):
            return "detail_addition"
        if self._contains_any(
            text,
            ["style", "polish", "rewrite", "文风", "风格", "润色"],
        ):
            return "style_only"
        return "detail_addition"

    def detect_hard_rule_warnings(
        self,
        revision_prompt: str,
        revision_intent: str,
        revised_text: str,
        world_canvas: dict[str, Any],
    ) -> list[dict[str, Any]]:
        combined_text = f"{revision_prompt}\n{revised_text}".lower()
        warnings: list[dict[str, Any]] = []
        hard_rules = [
            rule
            for rule in world_canvas.get("hard_rules", [])
            if isinstance(rule, dict)
        ]

        if revision_intent in {"hard_rule_conflict", "world_rule_change"}:
            warnings.append(
                self._hard_rule_warning(
                    hard_rules,
                    "Revision request appears to alter or bypass World Canvas hard rules.",
                )
            )
        if self._contains_any(
            combined_text,
            ["sun rises", "daytime trigger", "noon trigger", "白天触发", "太阳升起"],
        ):
            warnings.append(
                self._hard_rule_warning(
                    hard_rules,
                    "Revision candidate may violate time/trigger restrictions.",
                )
            )
        if self._contains_any(
            combined_text,
            [
                "free memory",
                "without cost",
                "no cost",
                "restore memory without",
                "无代价",
                "没有代价",
                "免费恢复",
            ],
        ):
            warnings.append(
                self._hard_rule_warning(
                    hard_rules,
                    "Revision candidate may violate memory cost restrictions.",
                )
            )
        hard_rule_texts = [
            f"{rule.get('rule_id', '')} {rule.get('statement', '')}"
            for rule in hard_rules
        ]
        premature_claim = (
            premature_period_exchange_claim(revised_text)
            if has_period_bound_exchange_rule(hard_rule_texts) and revised_text
            else ""
        )
        if premature_claim:
            warning = self._hard_rule_warning(
                    hard_rules,
                    "Revision candidate appears to trigger a period-bound exchange before its confirmed event window.",
                )
            warning["evidence_excerpt"] = premature_claim[:240]
            warnings.append(warning)
        return self._dedupe_warning_dicts(warnings)

    def _safe_provider_error(self, exc: Exception) -> str:
        text = str(exc or "").strip() or exc.__class__.__name__
        return text.split(":", 1)[0].strip()[:120] or exc.__class__.__name__

    def _disallowed_revision_character_mentions(
        self,
        context: dict[str, Any],
        revised_synopsis: str,
        revised_prose_text: str,
    ) -> list[str]:
        allowed_ids = {
            str(character_id)
            for character_id in context.get("allowed_revision_character_ids", [])
            if character_id
        }
        if not allowed_ids:
            return []
        text = f"{revised_synopsis}\n{revised_prose_text}"
        disallowed: list[str] = []
        for character in context.get("characters", []):
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("character_id") or "").strip()
            name = str(character.get("name") or "").strip()
            if not character_id or character_id in allowed_ids or not name:
                continue
            if name in text:
                disallowed.append(name)
        return self._unique_strings(disallowed)

    def _revision_internal_prose_markers(
        self,
        revised_synopsis: str,
        revised_prose_text: str,
        revision_prompt: str,
    ) -> list[str]:
        text = f"{revised_synopsis}\n{revised_prose_text}"
        markers = [
            marker
            for marker in REVISION_INTERNAL_PROSE_MARKERS
            if marker and marker in text
        ]
        clean_prompt = revision_prompt.strip()
        if clean_prompt and clean_prompt in text:
            markers.append("revision_prompt")
        return self._unique_strings(markers)

    def _fallback_revision_output(
        self,
        *,
        scene: Scene,
        context: dict[str, Any],
        revision_prompt: str,
        revision_intent: str,
        exc: Exception,
    ) -> dict[str, Any]:
        scene_info = context.get("scene_information") or {}
        scene_goal = scene_info.get("scene_goal") or {}
        environment = scene_info.get("environment") or {}
        location = str(
            environment.get("location")
            or environment.get("location_id")
            or scene.location
            or "当前场景地点"
        )
        characters = [
            item
            for item in context.get("characters", [])
            if isinstance(item, dict)
        ]
        allowed_ids = {
            str(character_id)
            for character_id in context.get("allowed_revision_character_ids", [])
            if character_id
        }
        if allowed_ids:
            scoped_characters = [
                character
                for character in characters
                if str(character.get("character_id") or "") in allowed_ids
            ]
            if scoped_characters:
                characters = scoped_characters
        names = [
            str(character.get("name") or character.get("character_id") or "").strip()
            for character in characters
            if character.get("name") or character.get("character_id")
        ]
        cast_line = "、".join(names[:4]) or "本幕角色"
        goal_summary = str(
            scene_goal.get("summary") or scene.goal or scene.synopsis or revision_prompt
        ).strip()
        revised_synopsis = goal_summary
        revised_prose_text = "\n\n".join(
            [
                "外部模型未能生成正式修订散文，本次结果仅保留结构占位，不应写入故事正文。",
                f"修订目标：{revised_synopsis}",
                f"场景位置：{location}；涉及角色：{cast_line}。",
                f"修订意图：{revision_intent}",
                f"失败阶段摘要：{self._safe_provider_error(exc)}",
            ]
        )
        return {
            "revised_synopsis": revised_synopsis,
            "revised_prose_text": revised_prose_text,
            "change_summary": [
                f"Applied local fallback revision after provider failure: {self._safe_provider_error(exc)}",
                f"Revision intent: {revision_intent}",
            ],
            "possible_impacts": [
                {
                    "target_type": "scene",
                    "target_id": scene.scene_id,
                    "risk": "quality_degraded",
                    "summary": "Local revision fallback requires user review before confirmation.",
                }
            ],
            "updated_story_information_notes": [
                "Provider failure fallback kept the revision within existing scene and chapter facts."
            ],
            "requires_user_confirmation": True,
        }

    def generate_revision_candidate(
        self,
        scene: Scene,
        context: dict[str, Any],
        revision_prompt: str,
        revision_intent: str,
        force_hard_rule_override: bool,
        prompt_hard_rule_warnings: list[dict[str, Any]],
        source_continuity_issue_id: str = "",
    ) -> SceneRevisionCandidate:
        provider_fallback_reasons: list[str] = []
        try:
            output = self.scene_revision_agent.revise_scene(context)
        except (ModelCallError, ModelJsonParseError) as exc:
            provider_fallback_reasons.append(
                f"revise_scene:{self._safe_provider_error(exc)}"
            )
            output = self._fallback_revision_output(
                scene=scene,
                context=context,
                revision_prompt=revision_prompt,
                revision_intent=revision_intent,
                exc=exc,
            )
        revised_synopsis = str(output.get("revised_synopsis") or "").strip()
        revised_prose_text = str(output.get("revised_prose_text") or "").strip()
        if not revised_synopsis or not revised_prose_text:
            raise StorageError(
                "SCENE_REVISION_MODEL_SCHEMA_INVALID: Revision Agent output must include revised_synopsis and revised_prose_text."
            )
        internal_markers = self._revision_internal_prose_markers(
            revised_synopsis,
            revised_prose_text,
            revision_prompt,
        )
        disallowed_mentions = self._disallowed_revision_character_mentions(
            context,
            revised_synopsis,
            revised_prose_text,
        )
        if internal_markers or disallowed_mentions:
            if internal_markers:
                provider_fallback_reasons.append(
                    "revise_scene:internal_prompt_markers:"
                    + ",".join(internal_markers)
                )
            if disallowed_mentions:
                provider_fallback_reasons.append(
                    "revise_scene:disallowed_character_mentions:"
                    + ",".join(disallowed_mentions)
                )
            safety_repair_context = dict(context)
            safety_repair_scene = dict(safety_repair_context.get("current_scene") or {})
            safety_repair_scene["prose_text"] = ""
            safety_repair_scene["revision_history"] = []
            safety_repair_scene["active_revision_id"] = ""
            safety_repair_context["current_scene"] = safety_repair_scene
            safety_repair_context["revision_prompt"] = (
                revision_prompt
                + "\n\n上一版候选未通过正文安全检查。请只输出故事内叙事，"
                "不要复述修订指令、上下文、技术字段或错误信息；只使用允许角色。"
            )
            safety_repair_context["output_safety_repair"] = {
                "internal_markers_to_remove": internal_markers,
                "disallowed_character_names_to_remove": disallowed_mentions,
                "allowed_revision_characters": context.get("allowed_revision_characters") or [],
            }
            try:
                output = self.scene_revision_agent.revise_scene(safety_repair_context)
            except (ModelCallError, ModelJsonParseError) as exc:
                raise StorageError(
                    "SCENE_REVISION_UNSAFE_OUTPUT: Automatic story-prose safety repair failed."
                ) from exc
            revised_synopsis = str(output.get("revised_synopsis") or "").strip()
            revised_prose_text = str(output.get("revised_prose_text") or "").strip()
            repaired_markers = self._revision_internal_prose_markers(
                revised_synopsis,
                revised_prose_text,
                revision_prompt,
            )
            repaired_disallowed = self._disallowed_revision_character_mentions(
                context,
                revised_synopsis,
                revised_prose_text,
            )
            if not revised_synopsis or not revised_prose_text or repaired_markers or repaired_disallowed:
                raise StorageError(
                    "SCENE_REVISION_UNSAFE_OUTPUT: Revision candidate still contains meta text or disallowed characters after automatic repair."
                )

        first_pass_detected_warnings = self.detect_hard_rule_warnings(
                revision_prompt="",
                revision_intent=revision_intent,
                revised_text=f"{revised_synopsis}\n{revised_prose_text}",
                world_canvas=context.get("world_canvas") or {},
            )
        first_pass_agent_warnings = self._agent_hard_rule_warnings(output)
        first_pass_warnings = self._dedupe_warning_dicts(
            first_pass_detected_warnings + first_pass_agent_warnings
        )
        if first_pass_warnings and not force_hard_rule_override:
            LOGGER.warning(
                "scene_revision_hard_rule_repair scene_id=%s deterministic=%s agent=%s",
                scene.scene_id,
                [
                    {
                        "summary": item.get("summary"),
                        "evidence": item.get("evidence_excerpt"),
                    }
                    for item in first_pass_detected_warnings
                ],
                [item.get("summary") for item in first_pass_agent_warnings],
            )
            repair_context = dict(context)
            repair_scene = dict(repair_context.get("current_scene") or {})
            repair_scene["prose_text"] = ""
            repair_scene["revision_history"] = []
            repair_scene["active_revision_id"] = ""
            repair_context["current_scene"] = repair_scene
            repair_context["revision_prompt"] = (
                revision_prompt
                + "\n\n上一版候选未通过世界硬规则检查。请完整重写并修复下列冲突；"
                "不得沿用冲突句，返回的 hard_rule_warnings 必须为空。"
            )
            repair_context["hard_rule_repair"] = {
                "warnings": first_pass_warnings,
                "confirmed_hard_rules": (context.get("world_canvas") or {}).get("hard_rules") or [],
                "safe_scene_synopsis": str(repair_scene.get("synopsis") or ""),
                "required_result": "A complete replacement candidate that satisfies every confirmed hard rule.",
            }
            try:
                repaired_output = self.scene_revision_agent.revise_scene(repair_context)
            except (ModelCallError, ModelJsonParseError) as exc:
                raise StorageError(
                    "HARD_RULE_CONFLICT: Revision candidate conflicts with World Canvas hard rules and automatic repair failed."
                ) from exc
            repaired_synopsis = str(repaired_output.get("revised_synopsis") or "").strip()
            repaired_prose = str(repaired_output.get("revised_prose_text") or "").strip()
            if not repaired_synopsis or not repaired_prose:
                raise StorageError(
                    "SCENE_REVISION_MODEL_SCHEMA_INVALID: Hard-rule repair output must include revised_synopsis and revised_prose_text."
                )
            repaired_internal_markers = self._revision_internal_prose_markers(
                repaired_synopsis,
                repaired_prose,
                revision_prompt,
            )
            repaired_disallowed_mentions = self._disallowed_revision_character_mentions(
                context,
                repaired_synopsis,
                repaired_prose,
            )
            if repaired_internal_markers or repaired_disallowed_mentions:
                raise StorageError(
                    "HARD_RULE_CONFLICT: Automatic hard-rule repair produced an unsafe scene candidate."
                )
            output = repaired_output
            revised_synopsis = repaired_synopsis
            revised_prose_text = repaired_prose

        candidate_scene = self._candidate_scene_dict(
            scene=scene,
            revised_synopsis=revised_synopsis,
            revised_prose_text=revised_prose_text,
        )
        try:
            memory_extraction = self.scene_generation_service.extract_memory(
                candidate_scene,
                context,
            )
        except (ModelCallError, ModelJsonParseError) as exc:
            provider_fallback_reasons.append(
                f"extract_memory:{self._safe_provider_error(exc)}"
            )
            chapter = Chapter(**context["chapter"])
            memory_extraction = self.scene_generation_service._fallback_memory_extraction(
                scene_id=scene.scene_id,
                chapter=chapter,
                scene_index=scene.scene_index,
                content=SceneDraftContent(
                    synopsis=revised_synopsis,
                    prose_text=revised_prose_text,
                ),
                context=context,
            )
        memory_extraction = self._filter_revision_memory_participants(
            memory_extraction=memory_extraction,
            revised_synopsis=revised_synopsis,
            revised_prose_text=revised_prose_text,
            agent_output=output,
        )
        candidate_scene["memory_extraction"] = model_to_dict(memory_extraction)

        revised_warnings = self.detect_hard_rule_warnings(
            revision_prompt=revision_prompt,
            revision_intent=revision_intent,
            revised_text=f"{revised_synopsis}\n{revised_prose_text}",
            world_canvas=context.get("world_canvas") or {},
        )
        hard_rule_warnings = self._dedupe_warning_dicts(
            prompt_hard_rule_warnings
            + revised_warnings
            + self._agent_hard_rule_warnings(output)
        )
        if hard_rule_warnings and not force_hard_rule_override:
            LOGGER.warning(
                "scene_revision_hard_rule_rejected scene_id=%s warnings=%s",
                scene.scene_id,
                [
                    {
                        "summary": item.get("summary"),
                        "evidence": item.get("evidence_excerpt"),
                    }
                    for item in hard_rule_warnings
                ],
            )
            raise StorageError(
                "HARD_RULE_CONFLICT: Revision candidate conflicts with World Canvas hard rules."
            )

        timestamp = now_iso()
        candidate = SceneRevisionCandidate(
            revision_id=self._next_revision_id(scene),
            scene_id=scene.scene_id,
            revision_prompt=revision_prompt,
            revision_intent=revision_intent,
            base_scene_version_id=scene.version_id or "",
            source_scene_status=scene.status,
            revised_synopsis=revised_synopsis,
            revised_prose_text=revised_prose_text,
            change_summary=[
                str(item)
                for item in output.get("change_summary", [])
                if item
            ]
            or [f"Applied {revision_intent} revision request."],
            possible_impacts=[
                dict(item)
                for item in output.get("possible_impacts", [])
                if isinstance(item, dict)
            ],
            updated_story_information_notes=[
                str(item)
                for item in output.get("updated_story_information_notes", [])
                if item
            ],
            hard_rule_warnings=hard_rule_warnings,
            requires_user_confirmation=bool(hard_rule_warnings)
            or bool(output.get("requires_user_confirmation")),
            source_continuity_issue_id=source_continuity_issue_id,
            resolution_lifecycle_status=(
                "pending_revision_candidate" if source_continuity_issue_id else ""
            ),
            memory_extraction=memory_extraction,
            quality_report=SceneQualityReport(),
            force_hard_rule_override=force_hard_rule_override,
            status="candidate",
            created_at=timestamp,
            updated_at=timestamp,
        )
        quality_response = None
        try:
            quality_response = self.quality_check_service.check_revision_candidate_object(
                scene=scene,
                candidate=candidate,
                context=context,
                persist_scene=False,
            )
            embedded_report = quality_response.embedded_report
            if provider_fallback_reasons:
                embedded_report = self.scene_generation_service._provider_failure_quality_report(
                    stage="scene_revision",
                    exc=ModelCallError("; ".join(provider_fallback_reasons)),
                    existing_report=embedded_report,
                )
            quality_report_id = quality_response.report.quality_report_id
        except (ModelCallError, ModelJsonParseError) as exc:
            provider_fallback_reasons.append(
                f"quality_check:{self._safe_provider_error(exc)}"
            )
            embedded_report = self.scene_generation_service._provider_failure_quality_report(
                stage="scene_revision_quality_check",
                exc=ModelCallError("; ".join(provider_fallback_reasons)),
                existing_report=candidate.quality_report,
            )
            quality_report_id = ""
        candidate = SceneRevisionCandidate(
            **{
                **model_to_dict(candidate),
                "quality_report": model_to_dict(embedded_report),
                "quality_report_id": quality_report_id,
                "requires_user_confirmation": (
                    candidate.requires_user_confirmation
                    or embedded_report.requires_user_confirmation
                    or embedded_report.quality_degraded
                    or embedded_report.semantic_check_status == "failed"
                ),
                "confirmation_gate": self._candidate_confirmation_gate(
                    quality_report=embedded_report,
                    base_requires_confirmation=candidate.requires_user_confirmation,
                ),
            }
        )
        return candidate

    def save_revision_candidate(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate,
    ) -> Scene:
        timestamp = now_iso()
        updated_scene = Scene(
            **{
                **model_to_dict(scene),
                "revision_history": [
                    *[model_to_dict(item) for item in scene.revision_history],
                    model_to_dict(candidate),
                ],
                "active_revision_id": candidate.revision_id,
                "updated_at": timestamp,
            }
        )
        self._upsert_scene(updated_scene)
        return updated_scene

    def apply_revision_candidate(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate,
    ) -> Scene:
        timestamp = now_iso()
        content = SceneDraftContent(
            synopsis=candidate.revised_synopsis,
            prose_text=candidate.revised_prose_text,
        )
        updated_history = []
        for item in scene.revision_history:
            if item.revision_id == candidate.revision_id:
                updated_history.append(
                    SceneRevisionCandidate(
                        **{
                            **model_to_dict(item),
                            "status": "confirmed",
                            "updated_at": timestamp,
                        }
                    )
                )
            else:
                updated_history.append(item)
        revised_scene = Scene(
            **{
                **model_to_dict(scene),
                "synopsis": candidate.revised_synopsis,
                "prose_text": candidate.revised_prose_text,
                "content": model_to_dict(content),
                "memory_extraction": model_to_dict(candidate.memory_extraction),
                "quality_report": model_to_dict(candidate.quality_report),
                "quality_report_id": candidate.quality_report_id,
                "status": "revised",
                "revision_history": [
                    model_to_dict(item) for item in updated_history
                ],
                "active_revision_id": candidate.revision_id,
                "version_id": SCENE_REVISION_VERSION_ID,
                "updated_at": timestamp,
            }
        )
        self._upsert_scene(revised_scene)
        return revised_scene

    def write_revision_decision(
        self,
        decision_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self._read_decision_dicts()
        decision = Decision(
            decision_id=f"decision_scene_revision_{len(decisions) + 1:03d}",
            decision_type=decision_type,
            target_type="scene_revision",
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.store.write(self.decisions_file, decisions)
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

    def mark_current_scene_draft_memory_superseded(
        self,
        scene_id: str,
        revision_id: str,
    ) -> None:
        self._mark_superseded(
            self.events_file,
            lambda item: item.get("scene_id") == scene_id
            and str(item.get("status") or "") in {"draft", "scene_draft"},
            revision_id,
        )
        self._mark_superseded(
            self.state_changes_file,
            lambda item: (
                item.get("scene_id") == scene_id
                or item.get("source_scene_id") == scene_id
            )
            and str(item.get("status") or "") in {"draft", "scene_draft"},
            revision_id,
        )
        self._mark_superseded(
            self.memory_records_file,
            lambda item: item.get("object_id") == scene_id
            and str(item.get("source_type") or "") in {"scene_draft", "draft"},
            revision_id,
        )

    def _ensure_scene_revision_open(
        self,
        scene: Scene,
        *,
        allow_confirmed_scene: bool = False,
    ) -> None:
        if scene.status in REVISION_LOCKED_SCENE_STATUSES and not allow_confirmed_scene:
            raise StorageError(
                "SCENE_REVISION_CONFIRMED_SCENE_LOCKED: Confirmed or committed scenes cannot be revised by the Milestone 8 draft revision flow."
            )
        if scene.status in REVISION_LOCKED_SCENE_STATUSES and allow_confirmed_scene:
            return
        if self._is_scene_gate_pipeline_needs_review(scene):
            return
        if scene.status not in REVISION_ALLOWED_SCENE_STATUSES:
            raise StorageError(
                "SCENE_REVISION_NOT_READY: Scene status must be draft or revised."
            )

    def _is_scene_gate_pipeline_needs_review(self, scene: Scene) -> bool:
        return bool(
            scene.status == "needs_review"
            and str(scene.needs_review_reason or "").startswith("scene_gate_pipeline:")
        )

    def _ensure_scene_revision_ready(self, scene: Scene) -> None:
        content = scene.content
        synopsis = (
            content.synopsis if content else scene.synopsis
        ) or scene.synopsis
        prose_text = (
            content.prose_text if content else scene.prose_text
        ) or scene.prose_text
        issues: list[str] = []
        if not synopsis.strip():
            issues.append("Scene synopsis is missing.")
        if not prose_text.strip():
            issues.append("Scene prose_text is missing.")
        if not scene.generation_trace.story_information_list:
            issues.append("Scene generation_trace.story_information_list is missing.")
        if not scene.generation_trace.ordered_story_information_package:
            issues.append("Scene generation_trace.ordered_story_information_package is missing.")
        has_memory_extraction = any(
            [
                scene.memory_extraction.event_summary,
                scene.memory_extraction.proposed_state_changes,
                scene.memory_extraction.relationship_changes,
                scene.memory_extraction.memory_records,
                scene.memory_extraction.no_event_reason,
            ]
        )
        if not has_memory_extraction:
            issues.append("Scene memory_extraction is missing.")
        if scene.quality_report is None:
            issues.append("Scene quality_report is missing.")
        if issues:
            raise StorageError("SCENE_REVISION_NOT_READY: " + "; ".join(issues))

    def _candidate_scene_dict(
        self,
        scene: Scene,
        revised_synopsis: str,
        revised_prose_text: str,
    ) -> dict[str, Any]:
        content = {
            "synopsis": revised_synopsis,
            "prose_text": revised_prose_text,
        }
        return {
            **model_to_dict(scene),
            "content": content,
            "synopsis": revised_synopsis,
            "prose_text": revised_prose_text,
            "memory_extraction": {},
        }

    def _candidate_confirmation_gate(
        self,
        *,
        quality_report: SceneQualityReport,
        base_requires_confirmation: bool,
    ) -> dict[str, Any]:
        semantic_failed = quality_report.semantic_check_status == "failed"
        requires_confirmation = bool(
            base_requires_confirmation
            or quality_report.requires_user_confirmation
            or quality_report.quality_degraded
            or semantic_failed
        )
        reasons = []
        if base_requires_confirmation:
            reasons.append("candidate_requires_user_confirmation")
        if quality_report.requires_user_confirmation:
            reasons.append("quality_requires_user_confirmation")
        if quality_report.quality_degraded or semantic_failed:
            reasons.append("semantic_quality_unavailable")
        return {
            "requires_user_confirmation": requires_confirmation,
            "reasons": self._unique_strings(reasons),
            "quality_report_id": quality_report.quality_report_id,
            "semantic_check_status": quality_report.semantic_check_status,
            "quality_degraded": quality_report.quality_degraded,
        }

    def _validate_revision_confirmation_gate(
        self,
        *,
        scene: Scene,
        candidate: SceneRevisionCandidate,
        user_input: str,
    ) -> None:
        report = candidate.quality_report
        if not candidate.quality_report_id or not report.quality_report_id:
            raise StorageError(
                "SCENE_REVISION_QUALITY_REPORT_INCOMPLETE: Revision candidate quality report is missing its id."
            )
        if candidate.quality_report_id != report.quality_report_id:
            raise StorageError(
                "SCENE_REVISION_QUALITY_REPORT_MISMATCH: Candidate quality_report_id disagrees with embedded quality report."
            )
        self._validate_full_embedded_quality_sync(candidate)
        if report.blocking_issues:
            raise StorageError(
                "SCENE_REVISION_QUALITY_BLOCKING_ISSUES: Cannot confirm revision while blocking quality issues exist."
            )
        if report.semantic_check_status == "failed" and not user_input:
            raise StorageError(
                "SCENE_REVISION_SEMANTIC_QUALITY_DEGRADED_CONFIRMATION_REQUIRED: Semantic quality check failed; explicit user confirmation is required."
            )
        if (report.requires_user_confirmation or report.quality_degraded) and not user_input:
            raise StorageError(
                "SCENE_REVISION_CONFIRMATION_INPUT_REQUIRED: Quality gate requires explicit user confirmation input."
            )
        polluted = self._unjustified_memory_participants(candidate)
        if polluted:
            raise StorageError(
                "SCENE_REVISION_MEMORY_PARTICIPANTS_UNJUSTIFIED: "
                + ", ".join(polluted)
            )
        linked_issue = self._linked_continuity_issue(candidate.source_continuity_issue_id)
        if linked_issue and linked_issue.get("requires_explicit_acceptance") and not user_input:
            raise StorageError(
                "SCENE_REVISION_LINKED_CONTINUITY_ACCEPTANCE_REQUIRED: Linked continuity issue requires explicit acceptance."
            )

    def _sync_revision_candidate_quality_report(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate,
    ) -> SceneRevisionCandidate:
        report = candidate.quality_report
        report_id = (
            candidate.quality_report_id
            or report.quality_report_id
            or str(candidate.confirmation_gate.get("quality_report_id") or "").strip()
        )
        if not report_id:
            return candidate

        stored_report = self._stored_quality_report(report_id)
        if stored_report is not None:
            try:
                embedded_report = to_embedded_scene_quality_report(
                    QualityReport(**stored_report)
                )
            except ValidationError as exc:
                raise StorageError(
                    "SCENE_REVISION_QUALITY_REPORT_INCOMPLETE: Stored revision quality report is invalid."
                ) from exc
        else:
            embedded_report = SceneQualityReport(
                **{
                    **model_to_dict(report),
                    "quality_report_id": report_id,
                }
            )

        requires_confirmation = bool(
            candidate.requires_user_confirmation
            or embedded_report.requires_user_confirmation
            or embedded_report.quality_degraded
            or embedded_report.semantic_check_status == "failed"
        )
        confirmation_gate = {
            **candidate.confirmation_gate,
            "requires_user_confirmation": requires_confirmation,
            "quality_report_id": report_id,
            "semantic_check_status": embedded_report.semantic_check_status,
            "quality_degraded": embedded_report.quality_degraded,
        }
        updated_candidate = SceneRevisionCandidate(
            **{
                **model_to_dict(candidate),
                "quality_report": model_to_dict(embedded_report),
                "quality_report_id": report_id,
                "requires_user_confirmation": requires_confirmation,
                "confirmation_gate": confirmation_gate,
                "updated_at": now_iso(),
            }
        )
        if model_to_dict(updated_candidate) != model_to_dict(candidate):
            self._persist_synced_revision_candidate(scene, updated_candidate)
        return updated_candidate

    def _persist_synced_revision_candidate(
        self,
        scene: Scene,
        candidate: SceneRevisionCandidate,
    ) -> None:
        updated_history = []
        changed = False
        for item in scene.revision_history:
            if item.revision_id == candidate.revision_id:
                updated_history.append(candidate)
                changed = True
            else:
                updated_history.append(item)
        if not changed:
            return
        self._upsert_scene(
            Scene(
                **{
                    **model_to_dict(scene),
                    "revision_history": [
                        model_to_dict(item) for item in updated_history
                    ],
                    "updated_at": now_iso(),
                }
            )
        )

    def _filter_revision_memory_participants(
        self,
        *,
        memory_extraction,
        revised_synopsis: str,
        revised_prose_text: str,
        agent_output: dict[str, Any],
    ):
        visible_ids = self._visible_revision_character_ids(
            revised_synopsis=revised_synopsis,
            revised_prose_text=revised_prose_text,
            agent_output=agent_output,
        )
        if not visible_ids:
            return memory_extraction
        character_ids = {character.character_id for character in self._read_characters()}
        data = model_to_dict(memory_extraction)
        for event in data.get("event_summary") or []:
            if not isinstance(event, dict):
                continue
            participants = []
            for participant in event.get("participants") or []:
                text = str(participant or "").strip()
                if not text:
                    continue
                if text in character_ids and text not in visible_ids:
                    continue
                participants.append(text)
            event["participants"] = self._unique_strings(participants)
        for memory in data.get("memory_records") or []:
            if not isinstance(memory, dict):
                continue
            character_refs = []
            for character_id in memory.get("character_ids") or []:
                text = str(character_id or "").strip()
                if not text:
                    continue
                if text in character_ids and text not in visible_ids:
                    continue
                character_refs.append(text)
            if "character_ids" in memory:
                memory["character_ids"] = self._unique_strings(character_refs)
        return type(memory_extraction)(**data)

    def _validate_full_embedded_quality_sync(
        self,
        candidate: SceneRevisionCandidate,
    ) -> None:
        full_report = self._stored_quality_report(candidate.quality_report_id)
        if full_report is None:
            raise StorageError(
                "SCENE_REVISION_QUALITY_REPORT_INCOMPLETE: Full revision quality report is missing."
            )
        embedded = candidate.quality_report
        mismatches: list[str] = []
        scalar_fields = [
            "passed",
            "requires_user_confirmation",
            "continuity_passed",
            "semantic_check_status",
            "quality_degraded",
            "confirmation_block_reason",
        ]
        embedded_data = model_to_dict(embedded)
        for field in scalar_fields:
            if full_report.get(field) != embedded_data.get(field):
                mismatches.append(field)
        list_fields = [
            "continuity_issue_ids",
            "blocking_continuity_issue_ids",
            "accepted_continuity_issue_ids",
        ]
        for field in list_fields:
            if list(full_report.get(field) or []) != list(embedded_data.get(field) or []):
                mismatches.append(field)
        if mismatches:
            raise StorageError(
                "SCENE_REVISION_QUALITY_REPORT_MISMATCH: "
                + ", ".join(self._unique_strings(mismatches))
            )

    def _stored_quality_report(self, quality_report_id: str) -> dict[str, Any] | None:
        if not quality_report_id or not self.store.exists(self.quality_reports_file):
            return None
        for item in self._read_list_if_present(self.quality_reports_file):
            if item.get("quality_report_id") == quality_report_id:
                return dict(item)
        return None

    def _unjustified_memory_participants(
        self,
        candidate: SceneRevisionCandidate,
    ) -> list[str]:
        visible_ids = self._visible_revision_character_ids(
            revised_synopsis=candidate.revised_synopsis,
            revised_prose_text=candidate.revised_prose_text,
            agent_output={},
        )
        if not visible_ids:
            return []
        character_ids = {character.character_id for character in self._read_characters()}
        unjustified: list[str] = []
        for event in candidate.memory_extraction.event_summary:
            if not isinstance(event, dict):
                continue
            for participant in event.get("participants") or []:
                participant_id = str(participant or "").strip()
                if participant_id in character_ids and participant_id not in visible_ids:
                    unjustified.append(participant_id)
        return self._unique_strings(unjustified)

    def _visible_revision_character_ids(
        self,
        *,
        revised_synopsis: str,
        revised_prose_text: str,
        agent_output: dict[str, Any],
    ) -> set[str]:
        text = f"{revised_synopsis}\n{revised_prose_text}".casefold()
        visible_ids: set[str] = set()
        for character in self._read_characters():
            character_id = character.character_id
            if text_mentions_character(text, character):
                visible_ids.add(character_id)
        for key in ("visible_character_ids", "participant_character_ids", "linked_character_ids"):
            for value in agent_output.get(key) or []:
                if value:
                    visible_ids.add(str(value))
        for beat in agent_output.get("role_beats") or []:
            if isinstance(beat, dict) and beat.get("character_id"):
                visible_ids.add(str(beat["character_id"]))
        return visible_ids

    def _linked_continuity_issue(self, issue_id: str) -> dict[str, Any] | None:
        if not issue_id or not self.store.exists(self.continuity_issues_file):
            return None
        for item in self._read_list_if_present(self.continuity_issues_file):
            if item.get("issue_id") == issue_id:
                return dict(item)
        return None

    def _sync_linked_continuity_issue_after_confirmation(
        self,
        *,
        candidate: SceneRevisionCandidate,
        user_input: str,
    ) -> None:
        issue = self._linked_continuity_issue(candidate.source_continuity_issue_id)
        if not issue:
            return
        status = "accepted" if issue.get("requires_explicit_acceptance") else "resolved"
        self._upsert_linked_continuity_issue(
            issue,
            status=status,
            linked_revision_candidate_status="confirmed",
            lifecycle_status=status,
            lifecycle_message=(
                user_input
                or "Linked scene revision candidate was confirmed and addressed the source continuity issue."
            ),
        )

    def _sync_linked_continuity_issue_after_rejection(
        self,
        candidate: SceneRevisionCandidate,
    ) -> None:
        issue = self._linked_continuity_issue(candidate.source_continuity_issue_id)
        if not issue:
            return
        self._upsert_linked_continuity_issue(
            issue,
            status="open",
            linked_revision_candidate_status="rejected",
            lifecycle_status="rejected_candidate_keeps_open",
            lifecycle_message="Linked scene revision candidate was rejected; source issue remains open.",
        )

    def _upsert_linked_continuity_issue(
        self,
        issue: dict[str, Any],
        *,
        status: str,
        linked_revision_candidate_status: str,
        lifecycle_status: str,
        lifecycle_message: str,
    ) -> None:
        issues = self._read_list_if_present(self.continuity_issues_file)
        updated = []
        for item in issues:
            if item.get("issue_id") != issue.get("issue_id"):
                updated.append(item)
                continue
            copy = dict(item)
            copy["status"] = status
            copy["linked_revision_candidate_status"] = linked_revision_candidate_status
            copy["resolution_lifecycle_status"] = lifecycle_status
            copy["resolution_lifecycle_message"] = lifecycle_message
            copy["updated_at"] = now_iso()
            updated.append(copy)
        self.store.write(self.continuity_issues_file, updated)

    def _allow_hard_rule_override(
        self,
        quality_report: SceneQualityReport,
        hard_rule_warnings: list[dict[str, Any]],
    ) -> SceneQualityReport:
        warning_texts = [
            str(warning.get("summary") or warning.get("rule_id") or "Hard rule conflict warning.")
            for warning in hard_rule_warnings
        ]
        retained_blocking = [
            issue
            for issue in quality_report.blocking_issues
            if not self._is_hard_rule_quality_issue(issue)
        ]
        converted_blocking = [
            issue
            for issue in quality_report.blocking_issues
            if self._is_hard_rule_quality_issue(issue)
        ]
        warnings = self._unique_strings(
            quality_report.warnings + warning_texts + converted_blocking
        )
        return SceneQualityReport(
            passed=len(retained_blocking) == 0,
            warnings=warnings,
            blocking_issues=retained_blocking,
            requires_user_confirmation=True,
        )

    def _is_hard_rule_quality_issue(self, issue: str) -> bool:
        lowered = issue.lower()
        return "hard" in lowered or "world canvas" in lowered or "rule" in lowered

    def _find_scene_by_id(self, scene_id: str) -> Scene | None:
        for item in self._read_list_if_present(self.scenes_file):
            if item.get("scene_id") != scene_id:
                continue
            try:
                return Scene(**item)
            except ValidationError as exc:
                raise StorageError("Scene JSON schema is invalid.") from exc
        return None

    def _find_revision_candidate(
        self,
        scene: Scene,
        revision_id: str,
    ) -> SceneRevisionCandidate | None:
        for candidate in scene.revision_history:
            if candidate.revision_id == revision_id:
                return candidate
        return None

    def _active_candidate(self, scene: Scene) -> SceneRevisionCandidate | None:
        if not scene.active_revision_id:
            return None
        candidate = self._find_revision_candidate(scene, scene.active_revision_id)
        if candidate and candidate.status == "candidate":
            return candidate
        return None

    def _next_revision_id(self, scene: Scene) -> str:
        return f"revision_{scene.scene_id}_{len(scene.revision_history) + 1:03d}"

    def _read_world_canvas(self) -> WorldCanvas:
        data = self.store.read(self.world_canvas_file)
        try:
            return WorldCanvas(**data)
        except ValidationError as exc:
            raise StorageError("WorldCanvas JSON schema is invalid.") from exc

    def _read_characters(self) -> list[Character]:
        if not self.store.exists(self.characters_file):
            return []
        try:
            return [
                Character(**item)
                for item in self.store.read_list(self.characters_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Characters JSON schema is invalid.") from exc

    def _read_confirmed_a_characters_if_present(self) -> list[Character]:
        return [
            character
            for character in self._read_characters()
            if character.tier == "A" and character.status == "confirmed"
        ]

    def _read_revision_context_characters(self, scene: Scene) -> list[Character]:
        confirmed = [
            character
            for character in self._read_characters()
            if character.status == "confirmed" and not character.archived_at
        ]
        selected_ids = self._revision_context_character_ids(scene)

        characters: list[Character] = []
        for character in confirmed:
            if character.tier == "A" or character.character_id in selected_ids:
                characters.append(character)
        return characters

    def _revision_context_character_ids(self, scene: Scene) -> list[str]:
        ids: list[str] = []
        ids.extend(scene.linked_character_ids)
        ids.extend(scene.character_context_ids)
        for event in scene.memory_extraction.event_summary:
            if isinstance(event, dict):
                ids.extend(str(value) for value in event.get("participants") or [])
        for memory in scene.memory_extraction.memory_records:
            if isinstance(memory, dict):
                ids.extend(str(value) for value in memory.get("character_ids") or [])

        trace = scene.generation_trace
        for beat in trace.role_beats:
            if isinstance(beat, dict) and beat.get("character_id"):
                ids.append(str(beat["character_id"]))
        for item in trace.story_information_list:
            ids.extend(item.related_character_ids)
        return self._unique_strings(ids)

    def _read_relationships(self) -> list[Relationship]:
        if not self.store.exists(self.relationships_file):
            return []
        try:
            return [
                Relationship(**item)
                for item in self.store.read_list(self.relationships_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Relationships JSON schema is invalid.") from exc

    def _read_confirmed_relationships(self) -> list[Relationship]:
        return [
            relationship
            for relationship in self._read_relationships()
            if relationship.status == "confirmed"
        ]

    def _read_chapters(self) -> list[Chapter]:
        try:
            return [
                Chapter(**item)
                for item in self.store.read_list(self.chapters_file)
                if isinstance(item, dict)
            ]
        except ValidationError as exc:
            raise StorageError("Chapters JSON schema is invalid.") from exc

    def _find_chapter(
        self,
        chapter_id: str,
        chapters: list[Chapter],
    ) -> Chapter | None:
        for chapter in chapters:
            if chapter.chapter_id == chapter_id:
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

    def _upsert_scene(self, scene: Scene) -> None:
        scenes = self._read_list_if_present(self.scenes_file)
        scene_data = model_to_dict(scene)
        replaced = False
        updated = []
        for item in scenes:
            if item.get("scene_id") == scene.scene_id:
                updated.append(scene_data)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(scene_data)
        self.store.write(self.scenes_file, updated)

    def _read_decision_dicts(self) -> list[dict[str, Any]]:
        return self._read_list_if_present(self.decisions_file)

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [
            dict(item)
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]

    def _mark_superseded(
        self,
        path: Path,
        should_mark,
        revision_id: str,
    ) -> None:
        if not self.store.exists(path):
            return
        changed = False
        updated = []
        timestamp = now_iso()
        for item in self._read_list_if_present(path):
            if should_mark(item):
                copy = dict(item)
                copy["status"] = "superseded"
                copy["superseded_by"] = revision_id
                copy["superseded_reason"] = "Scene revision candidate generated before formal scene confirmation."
                copy["updated_at"] = timestamp
                updated.append(copy)
                changed = True
            else:
                updated.append(item)
        if changed:
            self.store.write(path, updated)

    def _hard_rule_warning(
        self,
        hard_rules: list[dict[str, Any]],
        summary: str,
    ) -> dict[str, Any]:
        rule = hard_rules[0] if hard_rules else {}
        return {
            "rule_id": str(rule.get("rule_id") or "world_canvas_hard_rule"),
            "summary": summary,
            "statement": str(rule.get("statement") or ""),
            "requires_user_confirmation": True,
        }

    def _agent_hard_rule_warnings(
        self,
        output: dict[str, Any],
    ) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for index, item in enumerate(output.get("hard_rule_warnings") or [], start=1):
            if isinstance(item, dict):
                warning = dict(item)
                warning["rule_id"] = str(
                    warning.get("rule_id") or f"agent_hard_rule_warning_{index:03d}"
                )
                warning["summary"] = str(
                    warning.get("summary")
                    or warning.get("message")
                    or warning.get("rule_id")
                    or "Revision Agent reported a hard-rule warning."
                )
                warning["statement"] = str(warning.get("statement") or "")
                warning["requires_user_confirmation"] = bool(
                    warning.get("requires_user_confirmation", True)
                )
                warnings.append(warning)
            elif item:
                warnings.append(
                    {
                        "rule_id": f"agent_hard_rule_warning_{index:03d}",
                        "summary": str(item),
                        "statement": "",
                        "requires_user_confirmation": True,
                    }
                )
        return warnings

    def _contains_any(self, text: str, markers: list[str]) -> bool:
        return any(marker.lower() in text for marker in markers)

    def _dedupe_warning_dicts(
        self,
        warnings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, Any]] = []
        for warning in warnings:
            rule_id = str(warning.get("rule_id") or "")
            summary = str(warning.get("summary") or "")
            key = (rule_id, summary)
            if key in seen:
                continue
            seen.add(key)
            result.append(warning)
        return result

    def _unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
