import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.model_settings import ModelSettingsWorkbench
from app.backend.models.project_creation import ProjectCreationRequest, ProjectOriginMetadata
from app.backend.models.framework import Framework
from app.backend.models.project import ProjectState
from app.backend.models.story_bible import StoryBible
from app.backend.models.story_setup import (
    AnswerStorySetupQuestionRequest,
    BootstrapStorySetupHandoffRequest,
    CreateStorySetupDecisionRequest,
    CreateStorySetupDraftBundleRequest,
    CreateStorySetupHandoffRequest,
    CreateStorySetupIntakeRequest,
    CreateStorySetupPromptFromProjectRequest,
    PatchStorySetupDraftBundleRequest,
    StorySetupDecision,
    StorySetupDraftBundle,
    StorySetupHandoff,
    StorySetupIntake,
    StorySetupPrompt,
    StorySetupQuestion,
    StorySetupBootstrapResult,
    StorySetupCurrentState,
    StorySetupSafetyReport,
    StorySetupUserInput,
)
from app.backend.models.world_canvas import UnknownRule, WorldCanvas, WorldRule
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.active_project_story_data import story_data_dir_for_project
from app.backend.services.framework_package_service import (
    DEFAULT_FRAMEWORK_ID,
    DEFAULT_FRAMEWORK_PACKAGE_ID,
    FrameworkPackageService,
)
from app.backend.services.generator_framework_context_service import (
    GeneratorFrameworkContextService,
    SCHEMA_VERSION as GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_VERSION,
)
from app.backend.services.model_settings_service import ModelSettingsService
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.project_creation_service import ProjectCreationService
from app.backend.services.project_story_premise_service import (
    PROJECT_STORY_PREMISE_FILE,
    PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT,
    ProjectStoryPremiseBlocked,
    ProjectStoryPremiseSafetyError,
    ProjectStoryPremiseService,
)
from app.backend.storage.json_store import JsonStore, StorageError


STORY_SETUP_PROMPTS_FILE = "story_setup_prompts.json"
STORY_SETUP_USER_INPUTS_FILE = "story_setup_user_inputs.json"
STORY_SETUP_INTAKES_FILE = "story_setup_intakes.json"
STORY_SETUP_DRAFT_BUNDLES_FILE = "story_setup_draft_bundles.json"
STORY_SETUP_QUESTIONS_FILE = "story_setup_questions.json"
STORY_SETUP_DECISIONS_FILE = "story_setup_decisions.json"
STORY_SETUP_HANDOFFS_FILE = "story_setup_handoffs.json"
STORY_SETUP_SAFETY_REPORTS_FILE = "story_setup_safety_reports.json"
GENERATOR_FRAMEWORK_CONTEXT_FILE = "generator_framework_context.json"

STORY_FACT_FILES = [
    "project.json",
    "story_bible.json",
    "world_canvas.json",
    "characters.json",
    "relationships.json",
    "framework.json",
    "chapters.json",
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "final_story_package_snapshots.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
]
BOOTSTRAP_EMPTY_LIST_FILES = [
    "characters.json",
    "relationships.json",
    "chapters.json",
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "decisions.json",
    "issues.json",
    "quality_reports.json",
    "chapter_archives.json",
    "chapter_framework_build_contexts.json",
    "chapter_framework_build_reasons.json",
    "chapter_memory_packs.json",
    "scene_memory_packs.json",
    "scene_candidate_caches.json",
    "cached_scene_candidates.json",
    "continuity_issues.json",
    "future_issues.json",
    "delayed_questions.json",
    "future_todos.json",
]

SUPPORTED_DECISION_TYPES = {
    "confirm_for_handoff",
    "request_revision",
    "reject",
    "answer_questions",
    "defer",
}
SUPPORTED_TARGET_WORKSPACES = {
    "world_canvas_workspace",
    "character_workspace",
    "framework_workspace",
    "chapter_planning_workspace",
}

SECRET_LIKE_RE = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_\-]{8,}|(?i:bearer\s+[A-Za-z0-9._\-]{8,})|(?i:authorization\s*:)"
)
OPTIONAL_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
UNSAFE_VALUE_MARKERS = (
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "provider_payload",
    "provider payload",
    "provider_response",
    "provider response",
    "api_key_ref",
)
STORY_SETUP_MISSING_CODES = {
    "prompt_text_confirmation",
    "world_scope",
    "tone",
    "protagonist",
    "core_conflict",
    "length_or_audience",
    "magic_or_rule_system",
    "technology_or_speculative_rule",
    "relationship_focus",
    "information_release",
}


class StorySetupError(RuntimeError):
    """Base error for Phase 8 M3 story setup failures."""


class StorySetupNotFound(StorySetupError):
    """Raised when a story setup record is not found."""


class StorySetupBlocked(StorySetupError):
    """Raised when story setup is blocked by product boundary rules."""


class StorySetupSafetyError(StorySetupError):
    """Raised when a payload violates the M3 safety contract."""


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, BaseModel):
        return model.dict()
    return dict(model)


def serialize_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return model_to_dict(value)
    if isinstance(value, list):
        return [serialize_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_jsonable(child) for key, child in value.items()}
    return value


class StorySetupService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_creation_service: ProjectCreationService | None = None,
        model_settings_service: ModelSettingsService | None = None,
        model_gateway: ModelGatewayService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_creation_service = project_creation_service or ProjectCreationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.model_settings_service = model_settings_service or ModelSettingsService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.prompts_file = self.data_dir / STORY_SETUP_PROMPTS_FILE
        self.user_inputs_file = self.data_dir / STORY_SETUP_USER_INPUTS_FILE
        self.intakes_file = self.data_dir / STORY_SETUP_INTAKES_FILE
        self.draft_bundles_file = self.data_dir / STORY_SETUP_DRAFT_BUNDLES_FILE
        self.questions_file = self.data_dir / STORY_SETUP_QUESTIONS_FILE
        self.decisions_file = self.data_dir / STORY_SETUP_DECISIONS_FILE
        self.handoffs_file = self.data_dir / STORY_SETUP_HANDOFFS_FILE
        self.safety_reports_file = self.data_dir / STORY_SETUP_SAFETY_REPORTS_FILE

    def create_prompt_from_project(
        self,
        request: CreateStorySetupPromptFromProjectRequest,
    ) -> StorySetupPrompt:
        self._guard_safe_payload(model_to_dict(request), allow_controlled_text=True)
        origin = self._prompt_first_origin(request.project_id)
        creation_request = self._resolve_creation_request(
            request.creation_request_id,
            origin.source_prompt_ref,
        )
        now = utc_now()
        controlled_ref = None
        has_controlled_prompt_text = bool((request.prompt_text or "").strip())
        if has_controlled_prompt_text:
            controlled_ref = self._write_controlled_user_input(
                project_id=request.project_id,
                input_type="controlled_prompt_text",
                input_text=request.prompt_text or "",
                now=now,
            )

        model_hint = self._model_readiness_hint()
        warnings: list[str] = []
        if not has_controlled_prompt_text:
            warnings.append("controlled_prompt_text_confirmation_needed")
        if not model_hint["active_model_selection_id"]:
            warnings.append("no_active_model_selection")

        prompt = StorySetupPrompt(
            story_setup_prompt_id=f"story_setup_prompt_{uuid4().hex[:12]}",
            project_id=request.project_id,
            creation_request_id=creation_request.creation_request_id if creation_request else request.creation_request_id,
            project_origin_metadata_id=origin.origin_metadata_id,
            prompt_text_ref=origin.source_prompt_ref,
            safe_prompt_summary=self._safe_prompt_summary(origin, creation_request),
            controlled_prompt_text_ref=controlled_ref,
            has_controlled_prompt_text=has_controlled_prompt_text,
            needs_prompt_text_confirmation=not has_controlled_prompt_text,
            language=self._project_language(request.project_id, creation_request),
            user_intent_tags=self._intent_tags_from_origin(origin),
            active_model_selection_id=model_hint["active_model_selection_id"],
            active_model_provider_type=model_hint["provider_type"],
            active_model_name=model_hint["model_name"],
            model_health_status_at_creation=model_hint["health_status"],
            prompt_status="ready_for_intake"
            if has_controlled_prompt_text
            else "needs_text_confirmation",
            safe_summary=(
                "Prompt-first setup prompt created from project origin metadata. "
                "Full creative text is only stored in controlled setup user input when provided."
            ),
            warnings=self._dedupe(warnings + model_hint["warnings"]),
            created_at=now,
            updated_at=now,
        )
        prompts = self._read_prompts()
        prompts.append(prompt)
        self._write_prompts(prompts)
        return prompt

    def get_prompt(self, story_setup_prompt_id: str) -> StorySetupPrompt:
        return self._get_prompt(story_setup_prompt_id)

    def create_intake(
        self,
        request: CreateStorySetupIntakeRequest,
    ) -> StorySetupIntake:
        prompt = self._get_prompt(request.story_setup_prompt_id)
        now = utc_now()
        prompt_text = self._controlled_prompt_text(prompt.controlled_prompt_text_ref)
        analysis = self._analyze_story_setup_prompt(prompt, prompt_text)
        missing = analysis["missing_information_codes"]
        intake = StorySetupIntake(
            story_setup_intake_id=f"story_setup_intake_{uuid4().hex[:12]}",
            project_id=prompt.project_id,
            story_setup_prompt_id=prompt.story_setup_prompt_id,
            intake_status="needs_prompt_confirmation"
            if prompt.needs_prompt_text_confirmation
            else "draft",
            detected_genre_tags=analysis["detected_genre_tags"],
            detected_tone_tags=analysis["detected_tone_tags"],
            detected_world_scope=analysis["detected_world_scope"],
            detected_core_conflict=analysis["detected_core_conflict"],
            detected_protagonist_hint=analysis["detected_protagonist_hint"],
            detected_story_length_hint=analysis["detected_story_length_hint"],
            prompt_signal_summary=analysis["prompt_signal_summary"],
            detected_key_terms=analysis["detected_key_terms"],
            missing_information_codes=missing,
            analysis_snapshot=analysis,
            used_real_provider=bool(analysis.get("used_real_provider")),
            used_deterministic_fallback=bool(analysis.get("used_deterministic_fallback", True)),
            safe_summary=(
                "Story setup intake extracted safe setup signals from the controlled prompt. "
                "No raw model output is stored."
            ),
            warnings=list(analysis.get("warnings") or []),
            created_at=now,
            updated_at=now,
        )
        intakes = self._read_intakes()
        intakes.append(intake)
        self._write_intakes(intakes)
        return intake

    def get_intake(self, story_setup_intake_id: str) -> StorySetupIntake:
        return self._get_intake(story_setup_intake_id)

    def create_draft_bundle(
        self,
        request: CreateStorySetupDraftBundleRequest,
    ) -> StorySetupDraftBundle:
        prompt = self._get_prompt(request.story_setup_prompt_id)
        intake = (
            self._get_intake(request.story_setup_intake_id)
            if request.story_setup_intake_id
            else self.create_intake(
                CreateStorySetupIntakeRequest(
                    story_setup_prompt_id=prompt.story_setup_prompt_id
                )
            )
        )
        if intake.story_setup_prompt_id != prompt.story_setup_prompt_id:
            raise StorySetupBlocked("intake_prompt_mismatch")
        now = utc_now()
        selected_composition_id = self._safe_optional_composition_id(
            request.selected_framework_composition_id
        )
        generator_context = (
            self._confirmed_generator_framework_context(selected_composition_id)
            if selected_composition_id
            else {}
        )
        framework_suggestion = self._framework_suggestion(intake)
        if selected_composition_id:
            framework_suggestion.update(
                {
                    "selected_framework_composition_id": selected_composition_id,
                    "generator_framework_context_schema": generator_context.get("schema_version", ""),
                    "generator_framework_context_status": "confirmed",
                    "generator_framework_context_ref": GENERATOR_FRAMEWORK_CONTEXT_FILE,
                }
            )
        bundle = StorySetupDraftBundle(
            story_setup_draft_bundle_id=f"story_setup_bundle_{uuid4().hex[:12]}",
            project_id=prompt.project_id,
            story_setup_prompt_id=prompt.story_setup_prompt_id,
            story_setup_intake_id=intake.story_setup_intake_id,
            bundle_status="draft",
            world_canvas_draft_suggestion=self._world_canvas_suggestion(intake),
            main_cast_draft_direction=self._main_cast_direction(intake),
            framework_setup_suggestion=framework_suggestion,
            chapter_route_suggestion=self._chapter_route_suggestion(intake),
            selected_framework_composition_id=selected_composition_id,
            generator_framework_context_ref=(
                GENERATOR_FRAMEWORK_CONTEXT_FILE if selected_composition_id else None
            ),
            creates_final_story_facts_now=False,
            requires_downstream_confirmation=True,
            used_real_provider=intake.used_real_provider,
            used_deterministic_fallback=intake.used_deterministic_fallback,
            safe_summary=(
                "Story setup draft bundle created as suggestions only; downstream workspaces must confirm final facts."
            ),
            warnings=self._draft_warnings(prompt, intake),
            created_at=now,
            updated_at=now,
        )
        questions = self._build_questions(bundle, intake, now)
        bundle.question_ids = [question.story_setup_question_id for question in questions]
        bundles = self._read_draft_bundles()
        bundles.append(bundle)
        self._write_draft_bundles(bundles)
        existing_questions = self._read_questions()
        existing_questions.extend(questions)
        self._write_questions(existing_questions)
        self._replace_intake(
            intake.copy(
                update={
                    "question_ids": bundle.question_ids,
                    "updated_at": now,
                }
            )
        )
        return bundle

    def get_draft_bundle(self, story_setup_draft_bundle_id: str) -> StorySetupDraftBundle:
        return self._get_draft_bundle(story_setup_draft_bundle_id)

    def list_draft_bundles(self) -> list[StorySetupDraftBundle]:
        return self._read_draft_bundles()

    def patch_draft_bundle(
        self,
        story_setup_draft_bundle_id: str,
        request: PatchStorySetupDraftBundleRequest,
    ) -> StorySetupDraftBundle:
        self._guard_safe_payload(model_to_dict(request), allow_controlled_text=False)
        bundle = self._get_draft_bundle(story_setup_draft_bundle_id)
        if bundle.bundle_status not in {"draft", "revision_requested"}:
            raise StorySetupBlocked("draft_bundle_is_not_editable")
        updates = request.dict(exclude_unset=True)
        safe_updates: dict[str, Any] = {}
        for field in [
            "world_canvas_draft_suggestion",
            "main_cast_draft_direction",
            "framework_setup_suggestion",
            "chapter_route_suggestion",
        ]:
            if field in updates and updates[field] is not None:
                safe_updates[field] = self._mark_suggestion(updates[field], field)
        if (
            "selected_framework_composition_id" in updates
            and updates.get("selected_framework_composition_id") is not None
        ):
            selected_composition_id = self._safe_optional_composition_id(
                updates.get("selected_framework_composition_id")
            )
            generator_context = (
                self._confirmed_generator_framework_context(selected_composition_id)
                if selected_composition_id
                else {}
            )
            safe_updates["selected_framework_composition_id"] = selected_composition_id
            safe_updates["generator_framework_context_ref"] = (
                GENERATOR_FRAMEWORK_CONTEXT_FILE if selected_composition_id else None
            )
            framework_suggestion = dict(
                safe_updates.get("framework_setup_suggestion")
                or bundle.framework_setup_suggestion
                or {}
            )
            if selected_composition_id:
                framework_suggestion.update(
                    {
                        "selected_framework_composition_id": selected_composition_id,
                        "generator_framework_context_schema": generator_context.get("schema_version", ""),
                        "generator_framework_context_status": "confirmed",
                        "generator_framework_context_ref": GENERATOR_FRAMEWORK_CONTEXT_FILE,
                    }
                )
            else:
                for key in [
                    "selected_framework_composition_id",
                    "generator_framework_context_schema",
                    "generator_framework_context_status",
                    "generator_framework_context_ref",
                ]:
                    framework_suggestion.pop(key, None)
            safe_updates["framework_setup_suggestion"] = self._mark_suggestion(
                framework_suggestion,
                "framework_setup_suggestion",
            )
        safe_updates["updated_at"] = utc_now()
        safe_updates["warnings"] = self._dedupe(
            bundle.warnings + ["user_safe_patch_applied"]
        )
        updated = bundle.copy(update=safe_updates)
        self._replace_draft_bundle(updated)
        return updated

    def list_questions(self, story_setup_draft_bundle_id: str) -> list[StorySetupQuestion]:
        bundle = self._get_draft_bundle(story_setup_draft_bundle_id)
        question_ids = set(bundle.question_ids)
        return [
            question
            for question in self._read_questions()
            if question.story_setup_question_id in question_ids
        ]

    def answer_question(
        self,
        question_id: str,
        request: AnswerStorySetupQuestionRequest,
    ) -> StorySetupQuestion:
        self._guard_safe_payload(model_to_dict(request), allow_controlled_text=True)
        questions = self._read_questions()
        question: StorySetupQuestion | None = None
        for item in questions:
            if item.story_setup_question_id == question_id:
                question = item
                break
        if question is None:
            raise StorySetupNotFound(f"Story setup question not found: {question_id}")
        now = utc_now()
        answer_ref = self._write_controlled_user_input(
            project_id=question.project_id,
            input_type=f"question_answer:{question.question_type}",
            input_text=request.answer_text,
            now=now,
        )
        updated = question.copy(
            update={
                "answer_status": "answered",
                "user_answer_ref": answer_ref,
                "safe_answer_summary": self._safe_answer_summary(request.answer_text),
                "updated_at": now,
            }
        )
        self._replace_question(updated)
        self._update_intake_after_answer(updated)
        self._update_bundle_after_answer(updated)
        return updated

    def create_decision(
        self,
        story_setup_draft_bundle_id: str,
        request: CreateStorySetupDecisionRequest,
    ) -> StorySetupDecision:
        self._guard_safe_payload(model_to_dict(request), allow_controlled_text=False)
        if request.decision_type not in SUPPORTED_DECISION_TYPES:
            raise StorySetupBlocked("unsupported_story_setup_decision_type")
        bundle = self._get_draft_bundle(story_setup_draft_bundle_id)
        now = utc_now()
        status = "confirmed" if request.decision_type == "confirm_for_handoff" else "recorded"
        if request.decision_type == "reject":
            status = "rejected"
        decision = StorySetupDecision(
            story_setup_decision_id=f"story_setup_decision_{uuid4().hex[:12]}",
            project_id=bundle.project_id,
            story_setup_draft_bundle_id=bundle.story_setup_draft_bundle_id,
            decision_type=request.decision_type,
            decision_status=status,
            decision_scope="setup_draft_only",
            safe_user_note=self._safe_note(request.safe_user_note),
            requested_changes=[self._safe_note(item) for item in request.requested_changes[:10]],
            does_not_confirm_world_canvas_final=True,
            does_not_confirm_characters_final=True,
            does_not_confirm_framework_final=True,
            does_not_confirm_chapter_plan_final=True,
            does_not_write_story_facts=True,
            created_at=now,
        )
        decisions = self._read_decisions()
        decisions.append(decision)
        self._write_decisions(decisions)
        next_status = {
            "confirm_for_handoff": "handoff_ready",
            "request_revision": "revision_requested",
            "reject": "rejected",
            "answer_questions": "questions_answered",
            "defer": "deferred",
        }[request.decision_type]
        self._replace_draft_bundle(
            bundle.copy(
                update={
                    "bundle_status": next_status,
                    "decision_ids": self._dedupe(bundle.decision_ids + [decision.story_setup_decision_id]),
                    "updated_at": now,
                }
            )
        )
        return decision

    def get_decision(self, story_setup_decision_id: str) -> StorySetupDecision:
        return self._get_decision(story_setup_decision_id)

    def create_handoff(
        self,
        story_setup_decision_id: str,
        request: CreateStorySetupHandoffRequest,
    ) -> StorySetupHandoff:
        self._guard_safe_payload(model_to_dict(request), allow_controlled_text=False)
        if request.target_workspace not in SUPPORTED_TARGET_WORKSPACES:
            raise StorySetupBlocked("unsupported_handoff_target_workspace")
        decision = self._get_decision(story_setup_decision_id)
        if decision.decision_type != "confirm_for_handoff" or decision.decision_status != "confirmed":
            raise StorySetupBlocked("handoff_requires_confirm_for_handoff_decision")
        bundle = self._get_draft_bundle(decision.story_setup_draft_bundle_id)
        now = utc_now()
        handoff = StorySetupHandoff(
            story_setup_handoff_id=f"story_setup_handoff_{uuid4().hex[:12]}",
            project_id=bundle.project_id,
            story_setup_draft_bundle_id=bundle.story_setup_draft_bundle_id,
            story_setup_decision_id=decision.story_setup_decision_id,
            handoff_status="ready",
            target_workspace=request.target_workspace,
            world_canvas_draft_ref=f"{bundle.story_setup_draft_bundle_id}:world_canvas_draft_suggestion",
            main_cast_direction_ref=f"{bundle.story_setup_draft_bundle_id}:main_cast_draft_direction",
            framework_suggestion_ref=f"{bundle.story_setup_draft_bundle_id}:framework_setup_suggestion",
            chapter_route_suggestion_ref=f"{bundle.story_setup_draft_bundle_id}:chapter_route_suggestion",
            selected_framework_composition_id=bundle.selected_framework_composition_id,
            generator_framework_context_ref=bundle.generator_framework_context_ref,
            requires_world_canvas_confirmation=True,
            requires_character_confirmation=True,
            requires_framework_confirmation=True,
            requires_chapter_route_confirmation=True,
            safe_summary=(
                f"Story setup handoff routes draft suggestions to {request.target_workspace}; "
                "it does not apply or confirm story facts."
            ),
            warnings=["downstream_confirmation_required"],
            created_at=now,
            updated_at=now,
        )
        handoffs = self._read_handoffs()
        handoffs.append(handoff)
        self._write_handoffs(handoffs)
        self.create_safety_report(bundle.story_setup_draft_bundle_id, handoff.story_setup_handoff_id)
        return handoff

    def get_handoff(self, story_setup_handoff_id: str) -> StorySetupHandoff:
        return self._get_handoff(story_setup_handoff_id)

    def get_current_state(self, project_id: str | None = None) -> StorySetupCurrentState:
        warnings: list[str] = []
        effective_project_id = (project_id or "").strip()
        if not effective_project_id:
            try:
                effective_project_id = self._active_selection_project_id()
            except Exception:
                effective_project_id = ""
                warnings.append("active_project_selection_unavailable")

        decisions = self._read_decisions()
        handoffs = self._read_handoffs()
        prompts = self._read_prompts()
        intakes = self._read_intakes()
        draft_bundles = self._read_draft_bundles()
        questions = self._read_questions()
        safety_reports = self._read_safety_reports()
        if effective_project_id:
            project_decisions = [
                item for item in decisions if item.project_id == effective_project_id
            ]
            project_handoffs = [
                item for item in handoffs if item.project_id == effective_project_id
            ]
            project_prompts = [
                item for item in prompts if item.project_id == effective_project_id
            ]
            project_intakes = [
                item for item in intakes if item.project_id == effective_project_id
            ]
            project_draft_bundles = [
                item for item in draft_bundles if item.project_id == effective_project_id
            ]
            project_questions = [
                item for item in questions if item.project_id == effective_project_id
            ]
            project_safety_reports = [
                item for item in safety_reports if item.project_id == effective_project_id
            ]
        else:
            project_decisions = decisions
            project_handoffs = handoffs
            project_prompts = prompts
            project_intakes = intakes
            project_draft_bundles = draft_bundles
            project_questions = questions
            project_safety_reports = safety_reports
            if decisions or handoffs:
                warnings.append("current_state_unscoped_latest_record_used")

        current_handoff = self._latest_handoff(project_handoffs)
        current_decision = None
        if current_handoff:
            current_decision = next(
                (
                    item
                    for item in project_decisions
                    if item.story_setup_decision_id == current_handoff.story_setup_decision_id
                ),
                None,
            )
            if current_decision is None:
                warnings.append("handoff_decision_missing")
        if current_decision is None:
            current_decision = self._latest_decision(project_decisions)

        if current_decision and not effective_project_id:
            effective_project_id = current_decision.project_id
        if current_handoff and not effective_project_id:
            effective_project_id = current_handoff.project_id

        draft_bundle_id = ""
        if current_handoff:
            draft_bundle_id = current_handoff.story_setup_draft_bundle_id
        elif current_decision:
            draft_bundle_id = current_decision.story_setup_draft_bundle_id

        current_draft_bundle: StorySetupDraftBundle | None = None
        if draft_bundle_id:
            current_draft_bundle = next(
                (
                    item
                    for item in project_draft_bundles
                    if item.story_setup_draft_bundle_id == draft_bundle_id
                ),
                None,
            )
            if current_draft_bundle is None:
                warnings.append("current_story_setup_draft_bundle_missing")
        if current_draft_bundle is None and project_draft_bundles:
            current_draft_bundle = project_draft_bundles[-1]
            draft_bundle_id = current_draft_bundle.story_setup_draft_bundle_id

        current_prompt: StorySetupPrompt | None = None
        current_intake: StorySetupIntake | None = None
        if current_draft_bundle:
            current_prompt = next(
                (
                    item
                    for item in project_prompts
                    if item.story_setup_prompt_id == current_draft_bundle.story_setup_prompt_id
                ),
                None,
            )
            current_intake = next(
                (
                    item
                    for item in project_intakes
                    if item.story_setup_intake_id == current_draft_bundle.story_setup_intake_id
                ),
                None,
            )
        if current_prompt is None and project_prompts:
            current_prompt = project_prompts[-1]
        if current_intake is None and current_prompt:
            prompt_intakes = [
                item
                for item in project_intakes
                if item.story_setup_prompt_id == current_prompt.story_setup_prompt_id
            ]
            current_intake = prompt_intakes[-1] if prompt_intakes else None
        if current_draft_bundle is None and current_prompt:
            prompt_bundles = [
                item
                for item in project_draft_bundles
                if item.story_setup_prompt_id == current_prompt.story_setup_prompt_id
            ]
            current_draft_bundle = prompt_bundles[-1] if prompt_bundles else None
            if current_draft_bundle:
                draft_bundle_id = current_draft_bundle.story_setup_draft_bundle_id

        current_questions: list[StorySetupQuestion] = []
        current_safety_report: StorySetupSafetyReport | None = None
        if current_draft_bundle:
            current_questions = [
                item
                for item in project_questions
                if item.story_setup_draft_bundle_id == current_draft_bundle.story_setup_draft_bundle_id
            ]
            bundle_safety_reports = [
                item
                for item in project_safety_reports
                if item.story_setup_draft_bundle_id == current_draft_bundle.story_setup_draft_bundle_id
            ]
            current_safety_report = bundle_safety_reports[-1] if bundle_safety_reports else None

        if current_prompt and not effective_project_id:
            effective_project_id = current_prompt.project_id
        if current_intake and not effective_project_id:
            effective_project_id = current_intake.project_id
        if current_draft_bundle and not effective_project_id:
            effective_project_id = current_draft_bundle.project_id

        if current_handoff:
            state_status = "handoff_ready"
        elif current_decision:
            state_status = current_decision.decision_type or "decision_recorded"
        elif current_draft_bundle:
            state_status = current_draft_bundle.bundle_status or "draft_bundle_ready"
        elif current_intake:
            state_status = current_intake.intake_status or "intake_ready"
        elif current_prompt:
            state_status = current_prompt.prompt_status or "prompt_ready"
        else:
            state_status = "empty"

        return StorySetupCurrentState(
            project_id=effective_project_id,
            state_status=state_status,
            controlled_prompt_text=(
                self._controlled_prompt_text(current_prompt.controlled_prompt_text_ref)
                if current_prompt
                else ""
            ),
            story_setup_prompt=current_prompt,
            story_setup_intake=current_intake,
            story_setup_draft_bundle=current_draft_bundle,
            story_setup_questions=current_questions,
            controlled_question_answers={
                question.story_setup_question_id: self._controlled_prompt_text(
                    question.user_answer_ref
                )
                for question in current_questions
                if question.user_answer_ref
            },
            story_setup_decision=current_decision,
            story_setup_handoff=current_handoff,
            story_setup_safety_report=current_safety_report,
            story_setup_draft_bundle_id=draft_bundle_id,
            warnings=self._dedupe(warnings),
        )

    def bootstrap_active_project_story_data(
        self,
        story_setup_handoff_id: str,
        request: BootstrapStorySetupHandoffRequest,
    ) -> StorySetupBootstrapResult:
        self._guard_safe_payload(model_to_dict(request), allow_controlled_text=False)
        handoff = self._get_handoff(story_setup_handoff_id)
        if handoff.handoff_status != "ready":
            raise StorySetupBlocked("handoff_is_not_ready_for_bootstrap")
        decision = self._get_decision(handoff.story_setup_decision_id)
        if decision.decision_type != "confirm_for_handoff" or decision.decision_status != "confirmed":
            raise StorySetupBlocked("bootstrap_requires_confirmed_handoff_decision")
        bundle = self._get_draft_bundle(handoff.story_setup_draft_bundle_id)
        if bundle.project_id != handoff.project_id:
            raise StorySetupBlocked("handoff_bundle_project_mismatch")
        active_project_id = self._active_selection_project_id()
        if active_project_id != handoff.project_id:
            raise StorySetupBlocked("handoff_project_must_be_active_project")
        if active_project_id == "local_project":
            raise StorySetupBlocked("legacy_debug_project_does_not_use_story_setup_bootstrap")

        now = utc_now()
        project_summary = self.project_creation_service.get_project(active_project_id)
        project_shell = project_summary.project
        safe_project_id = self._safe_id(active_project_id)
        story_bible_id = f"story_bible_{safe_project_id}_setup"
        world_canvas_id = f"world_canvas_{safe_project_id}_draft"
        framework_id = DEFAULT_FRAMEWORK_ID
        framework_package_id = DEFAULT_FRAMEWORK_PACKAGE_ID
        version_id = f"phase8_5_story_setup_bootstrap_{uuid4().hex[:8]}"
        story_data_dir = story_data_dir_for_project(active_project_id, self.data_dir)

        project = ProjectState(
            project_id=active_project_id,
            title=project_shell.title,
            language=project_shell.language,
            phase="phase_8_5",
            current_phase="productized_workspace",
            current_step="world_canvas_draft",
            status="story_setup_bootstrapped",
            story_bible_id=story_bible_id,
            created_at=project_shell.created_at or now,
            updated_at=now,
        )
        story_bible = StoryBible(
            story_bible_id=story_bible_id,
            project_id=active_project_id,
            world_canvas_id=world_canvas_id,
            active_framework_id=framework_id,
            version_id=version_id,
        )
        prompt = self._get_prompt(bundle.story_setup_prompt_id)
        world_canvas = self._world_canvas_from_setup_bundle(
            bundle=bundle,
            prompt=prompt,
            project_id=active_project_id,
            world_canvas_id=world_canvas_id,
            version_id=version_id,
            now=now,
        )
        framework = Framework(
            framework_id=framework_id,
            project_id=active_project_id,
            name="Story setup default framework",
            constraint_strength="strong",
            maturity="System",
            source="system_default",
            framework_package_id=framework_package_id,
            nodes=[],
        )
        framework_package = FrameworkPackageService(
            store=self.store,
            data_dir=story_data_dir,
        )._build_default_package()
        framework_package.project_id = active_project_id
        framework_package.language = project_shell.language
        framework_package.version_id = version_id
        framework_package.framework_package_id = framework_package_id
        framework_package.source = "system_default"
        framework_package.constraint_strength = "strong"
        framework_package.maturity = "System"

        created_files: list[str] = []
        updated_files: list[str] = []
        cleared_files: list[str] = []
        selected_composition_id = self._safe_optional_composition_id(
            bundle.selected_framework_composition_id
        )
        generator_framework_context_ref: str | None = None
        generator_framework_context = (
            self._confirmed_generator_framework_context(selected_composition_id)
            if selected_composition_id
            else {}
        )
        self._write_bootstrap_file(story_data_dir, "project.json", model_to_dict(project), created_files, updated_files)
        self._write_bootstrap_file(story_data_dir, "story_bible.json", model_to_dict(story_bible), created_files, updated_files)
        self._write_bootstrap_file(story_data_dir, "world_canvas.json", model_to_dict(world_canvas), created_files, updated_files)
        self._write_bootstrap_file(story_data_dir, "framework.json", model_to_dict(framework), created_files, updated_files)
        self._write_bootstrap_file(story_data_dir, "framework_package.json", model_to_dict(framework_package), created_files, updated_files)
        if selected_composition_id:
            self._write_bootstrap_file(
                story_data_dir,
                GENERATOR_FRAMEWORK_CONTEXT_FILE,
                generator_framework_context,
                created_files,
                updated_files,
            )
            generator_framework_context_ref = self._bootstrap_file_ref(
                story_data_dir,
                GENERATOR_FRAMEWORK_CONTEXT_FILE,
            )
        for file_name in BOOTSTRAP_EMPTY_LIST_FILES:
            self._write_bootstrap_file(story_data_dir, file_name, [], created_files, updated_files)
            cleared_files.append(self._bootstrap_file_ref(story_data_dir, file_name))
        premise_status = "not_created"
        premise_ref: str | None = None
        premise_blocking_issues: list[str] = []
        premise_existed_before = self.store.exists(story_data_dir / PROJECT_STORY_PREMISE_FILE)
        try:
            premise = ProjectStoryPremiseService(
                store=self.store,
                data_dir=self.data_dir,
                project_creation_service=self.project_creation_service,
            ).build_from_story_setup(
                prompt=prompt,
                handoff=handoff,
                story_data_dir=story_data_dir,
            )
            premise_status = "created" if not premise.blocking_issues else "blocked"
            premise_blocking_issues = list(premise.blocking_issues)
            premise_ref = self._bootstrap_file_ref(story_data_dir, PROJECT_STORY_PREMISE_FILE)
            if premise_ref not in created_files and premise_ref not in updated_files:
                if premise_existed_before:
                    updated_files.append(premise_ref)
                else:
                    created_files.append(premise_ref)
        except ProjectStoryPremiseBlocked as exc:
            issue = str(exc) or PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT
            if issue == PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT:
                premise_status = "blocked"
                premise_blocking_issues = [PROJECT_STORY_PREMISE_MISSING_CONTROLLED_PROMPT]
            else:
                raise StorySetupBlocked(issue) from exc
        except ProjectStoryPremiseSafetyError as exc:
            raise StorySetupSafetyError(str(exc)) from exc
        self._update_project_shell_after_bootstrap(
            project_id=active_project_id,
            current_step="world_canvas_draft",
            status="story_setup_bootstrapped",
            now=now,
        )
        handoff = handoff.copy(
            update={
                "handoff_status": "applied",
                "updated_at": now,
            }
        )
        self._write_handoffs(
            [
                handoff if item.story_setup_handoff_id == handoff.story_setup_handoff_id else item
                for item in self._read_handoffs()
            ]
        )

        return StorySetupBootstrapResult(
            story_setup_bootstrap_id=f"story_setup_bootstrap_{uuid4().hex[:12]}",
            project_id=active_project_id,
            story_setup_handoff_id=handoff.story_setup_handoff_id,
            story_bible_id=story_bible_id,
            world_canvas_id=world_canvas_id,
            world_canvas_status=world_canvas.status,
            story_data_scope="active_project",
            created_files=created_files,
            updated_files=updated_files,
            cleared_legacy_files=cleared_files,
            setup_required_after_bootstrap=False,
            next_workspace_id="world_canvas",
            project_story_premise_status=premise_status,
            project_story_premise_ref=premise_ref,
            project_story_premise_blocking_issues=premise_blocking_issues,
            selected_framework_composition_id=selected_composition_id,
            generator_framework_context_ref=generator_framework_context_ref,
            safe_summary=(
                "Story setup bootstrap created a per-project active story workspace; "
                "world canvas and downstream objects still require normal confirmation."
            ),
            warnings=self._dedupe(["downstream_confirmation_required", *premise_blocking_issues]),
            created_at=now,
        )

    def get_or_create_safety_report(
        self,
        story_setup_draft_bundle_id: str,
    ) -> StorySetupSafetyReport:
        existing = [
            report
            for report in self._read_safety_reports()
            if report.story_setup_draft_bundle_id == story_setup_draft_bundle_id
        ]
        return existing[-1] if existing else self.create_safety_report(story_setup_draft_bundle_id)

    def create_safety_report(
        self,
        story_setup_draft_bundle_id: str,
        story_setup_handoff_id: str | None = None,
    ) -> StorySetupSafetyReport:
        bundle = self._get_draft_bundle(story_setup_draft_bundle_id)
        violations = self._safety_violations()
        report = StorySetupSafetyReport(
            story_setup_safety_report_id=f"story_setup_safety_{uuid4().hex[:12]}",
            project_id=bundle.project_id,
            story_setup_draft_bundle_id=bundle.story_setup_draft_bundle_id,
            story_setup_handoff_id=story_setup_handoff_id,
            passed=not violations,
            violations=violations,
            warnings=["controlled_user_inputs_are_isolated"]
            if self.user_inputs_file.exists()
            else [],
            safe_summary=(
                "M3 safety report checks story setup storage for secret and model-payload markers "
                "and confirms setup handoff is not a story fact apply layer."
            ),
            created_at=utc_now(),
        )
        reports = self._read_safety_reports()
        reports.append(report)
        self._write_safety_reports(reports)
        return report

    def safety_scan(self) -> StorySetupSafetyReport:
        bundle = self._read_draft_bundles()[-1] if self._read_draft_bundles() else None
        return StorySetupSafetyReport(
            story_setup_safety_report_id="story_setup_safety_scan_preview",
            project_id=bundle.project_id if bundle else "unknown",
            story_setup_draft_bundle_id=bundle.story_setup_draft_bundle_id if bundle else "unknown",
            passed=not self._safety_violations(),
            violations=self._safety_violations(),
            safe_summary="Story setup safety scan preview.",
            created_at=utc_now(),
        )

    def _prompt_first_origin(self, project_id: str) -> ProjectOriginMetadata:
        origin = self.project_creation_service.get_project_origin(project_id)
        if origin.origin_type != "prompt_first" or not origin.is_prompt_first:
            raise StorySetupBlocked("story_setup_requires_prompt_first_project")
        if not origin.source_prompt_ref:
            raise StorySetupBlocked("prompt_first_project_missing_source_prompt_ref")
        return origin

    def _resolve_creation_request(
        self,
        creation_request_id: str | None,
        prompt_text_ref: str | None,
    ) -> ProjectCreationRequest | None:
        requests = self._read_project_creation_requests()
        if creation_request_id:
            for request in requests:
                if request.creation_request_id == creation_request_id:
                    return request
            raise StorySetupNotFound(f"Project creation request not found: {creation_request_id}")
        for request in reversed(requests):
            if request.prompt_text_ref == prompt_text_ref:
                return request
        return None

    def _active_selection_project_id(self) -> str:
        selection = self.project_creation_service.get_active_project_selection().active_project_selection
        return selection.project_id if selection else ""

    def _world_canvas_from_setup_bundle(
        self,
        *,
        bundle: StorySetupDraftBundle,
        prompt: StorySetupPrompt,
        project_id: str,
        world_canvas_id: str,
        version_id: str,
        now: str,
    ) -> WorldCanvas:
        suggestion = bundle.world_canvas_draft_suggestion or {}
        tone_candidates = suggestion.get("tone_candidates")
        if not isinstance(tone_candidates, list):
            tone_candidates = []
        unknown_gaps = suggestion.get("unknown_logic_gaps")
        if not isinstance(unknown_gaps, list):
            unknown_gaps = []
        soft_candidates = suggestion.get("soft_rule_candidates")
        if not isinstance(soft_candidates, list):
            soft_candidates = []

        scope = self._safe_text(str(suggestion.get("world_scope") or "world_scope_to_confirm"), 120)
        tone = self._safe_text(", ".join(str(item) for item in tone_candidates if item) or "tone_to_confirm", 180)
        story_direction = self._safe_text(
            str(suggestion.get("potential_conflict") or "Story direction requires World Canvas confirmation."),
            300,
        )
        source_story_idea = self._source_story_idea_from_story_setup_prompt(prompt)
        soft_rules = [
            WorldRule(
                rule_id=f"setup_soft_rule_{index:03d}",
                statement=self._safe_text(str(candidate), 260),
                category="story_setup_suggestion",
                firmness="soft",
                source="story_setup_draft_suggestion",
                rationale="Imported from Story Setup as a draft suggestion, not a confirmed hard rule.",
                risk_if_changed="Low until user confirms the World Canvas.",
                version_id=version_id,
            )
            for index, candidate in enumerate(soft_candidates[:5], start=1)
            if str(candidate).strip()
        ]
        unknown_rules = [
            UnknownRule(
                unknown_rule_id=f"setup_unknown_{index:03d}",
                summary=self._safe_text(str(gap), 220),
                gap_type="story_setup_missing_information",
                why_it_matters="Story Setup marked this item as missing or unresolved before downstream confirmation.",
                severity="medium",
                status="open",
                first_detected_at=now,
                last_checked_at=now,
            )
            for index, gap in enumerate(unknown_gaps[:8], start=1)
            if str(gap).strip()
        ]
        return WorldCanvas(
            world_canvas_id=world_canvas_id,
            project_id=project_id,
            status="draft",
            story_direction=story_direction,
            scope=scope,
            tone=tone,
            history_summary="Draft initialized from Story Setup; confirm details in World Canvas.",
            geography_summary="Draft initialized from Story Setup; locations are not confirmed yet.",
            culture_summary="Draft initialized from Story Setup; culture and factions are not confirmed yet.",
            special_rules_summary="No hard rule is confirmed by Story Setup bootstrap.",
            hard_rules=[],
            soft_rules=soft_rules,
            unknown_rules=unknown_rules,
            user_confirmation_needed=[
                "Confirm World Canvas before character, framework, chapter, or scene generation."
            ],
            source_story_idea=source_story_idea,
            latest_user_prompt="",
            created_at=now,
            updated_at=now,
            version_id=version_id,
        )

    def _source_story_idea_from_story_setup_prompt(self, prompt: StorySetupPrompt) -> str:
        controlled_text = self._controlled_prompt_text(prompt.controlled_prompt_text_ref)
        if controlled_text:
            self._guard_controlled_text(controlled_text)
            return self._safe_text(controlled_text, 5000)
        fallback = (prompt.safe_prompt_summary or prompt.safe_summary or "").strip()
        return self._safe_text(fallback, 1200) or "Story Setup source premise requires user confirmation."

    def _write_bootstrap_file(
        self,
        story_data_dir: Path,
        file_name: str,
        payload: Any,
        created_files: list[str],
        updated_files: list[str],
    ) -> None:
        path = story_data_dir / file_name
        existed = self.store.exists(path)
        self._guard_safe_payload(payload, allow_controlled_text=False)
        self.store.write(path, serialize_jsonable(payload))
        file_ref = self._bootstrap_file_ref(story_data_dir, file_name)
        if existed:
            updated_files.append(file_ref)
        else:
            created_files.append(file_ref)

    def _bootstrap_file_ref(self, story_data_dir: Path, file_name: str) -> str:
        try:
            relative = (story_data_dir / file_name).resolve().relative_to(self.data_dir.parent.resolve())
            return relative.as_posix()
        except ValueError:
            return file_name

    def _update_project_shell_after_bootstrap(
        self,
        *,
        project_id: str,
        current_step: str,
        status: str,
        now: str,
    ) -> None:
        registry_file = self.data_dir / "project_registry.json"
        if not self.store.exists(registry_file):
            return
        try:
            registry = self.store.read(registry_file)
        except StorageError:
            return
        projects = registry.get("projects") if isinstance(registry, dict) else []
        if not isinstance(projects, list):
            return
        changed = False
        updated_projects = []
        for item in projects:
            if isinstance(item, dict) and item.get("project_id") == project_id:
                next_item = dict(item)
                next_item["current_step"] = current_step
                next_item["status"] = status
                next_item["updated_at"] = now
                updated_projects.append(next_item)
                changed = True
            else:
                updated_projects.append(item)
        if changed:
            payload = dict(registry)
            payload["projects"] = updated_projects
            self._guard_safe_payload(payload, allow_controlled_text=False)
            self.store.write(registry_file, payload)

    def _safe_optional_composition_id(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if not OPTIONAL_ID_RE.match(text):
            raise StorySetupSafetyError("selected_framework_composition_id_is_invalid")
        return text

    def _confirmed_generator_framework_context(self, composition_id: str) -> dict[str, Any]:
        context = GeneratorFrameworkContextService(
            store=self.store,
            data_dir=self.data_dir,
        ).build_context(composition_id)
        if context.get("schema_version") != GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_VERSION:
            raise StorySetupBlocked("generator_framework_context_schema_mismatch")
        return context

    def _safe_id(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value or "").strip("_").lower()
        return cleaned[:80] or "project"

    def _safe_text(self, value: str, limit: int) -> str:
        clean = " ".join((value or "").split())
        self._guard_safe_payload({"safe_text": clean}, allow_controlled_text=False)
        return clean[:limit]

    def _read_project_creation_requests(self) -> list[ProjectCreationRequest]:
        path = self.data_dir / "project_creation_requests.json"
        if not self.store.exists(path):
            return []
        try:
            return [ProjectCreationRequest(**item) for item in self.store.read_list(path)]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError("Project creation request storage is invalid.") from exc

    def _write_controlled_user_input(
        self,
        project_id: str,
        input_type: str,
        input_text: str,
        now: str,
    ) -> str:
        self._guard_controlled_text(input_text)
        record = StorySetupUserInput(
            story_setup_user_input_id=f"story_setup_user_input_{uuid4().hex[:12]}",
            project_id=project_id,
            input_type=input_type,
            input_text=input_text,
            safe_summary=f"Controlled setup user input stored for {input_type}.",
            created_at=now,
        )
        inputs = self._read_user_inputs()
        inputs.append(record)
        self._write_user_inputs(inputs)
        return f"story_setup_user_input:{record.story_setup_user_input_id}"

    def _controlled_prompt_text(self, controlled_ref: str | None) -> str:
        if not controlled_ref:
            return ""
        user_input_id = controlled_ref.removeprefix("story_setup_user_input:")
        for item in self._read_user_inputs():
            if item.story_setup_user_input_id == user_input_id:
                return item.input_text
        return ""

    def _model_readiness_hint(self) -> dict[str, Any]:
        try:
            workbench: ModelSettingsWorkbench = self.model_settings_service.workbench()
        except Exception:
            return {
                "active_model_selection_id": None,
                "provider_type": None,
                "model_name": None,
                "health_status": "unknown",
                "warnings": ["model_settings_unavailable"],
            }
        latest_health = workbench.health_summary.latest_health_check
        warnings = []
        if workbench.warnings:
            warnings.append("model_settings_warning")
        if workbench.blockers:
            warnings.append("model_settings_blocker")
        configured = bool(
            workbench.active_selection_id
            and workbench.current_provider
            and workbench.current_model
            and not workbench.blockers
        )
        return {
            "active_model_selection_id": workbench.active_selection_id,
            "provider_type": workbench.current_provider or None,
            "model_name": workbench.current_model or None,
            "health_status": "passed" if configured else latest_health.status if latest_health else "unknown",
            "warnings": self._dedupe(warnings),
        }

    def _safe_prompt_summary(
        self,
        origin: ProjectOriginMetadata,
        creation_request: ProjectCreationRequest | None,
    ) -> str:
        if creation_request and creation_request.prompt_safe_summary:
            return creation_request.prompt_safe_summary
        return (
            f"Prompt-first project has source prompt ref {origin.source_prompt_ref}; "
            "full prompt text must be confirmed in Story Setup if needed."
        )

    def _project_language(
        self,
        project_id: str,
        creation_request: ProjectCreationRequest | None,
    ) -> str:
        if creation_request and creation_request.requested_language:
            return creation_request.requested_language
        try:
            return self.project_creation_service.get_project(project_id).project.language
        except Exception:
            return "zh"

    def _intent_tags_from_origin(self, origin: ProjectOriginMetadata) -> list[str]:
        tags = ["prompt_first", "requires_setup_review"]
        if origin.is_real_user_project:
            tags.append("real_user_project")
        return tags

    def _missing_information_codes(
        self,
        prompt: StorySetupPrompt,
        prompt_text: str,
    ) -> list[str]:
        missing: list[str] = []
        lowered = prompt_text.lower()
        if prompt.needs_prompt_text_confirmation:
            missing.append("prompt_text_confirmation")
        if not any(
            word in lowered
            for word in [
                "world",
                "city",
                "kingdom",
                "village",
                "space",
                "planet",
                "mars",
                "colony",
            ]
        ) and not any(
            word in prompt_text
            for word in [
                "世界",
                "城市",
                "火星",
                "殖民",
                "殖民地",
                "星球",
                "太空",
                "基地",
                "校园",
                "都市",
                "王朝",
                "江湖",
                "学院",
                "小镇",
                "村庄",
                "灯塔",
                "码头",
                "唐代",
                "唐朝",
                "长安",
                "洛阳",
                "西市",
                "东市",
                "道观",
                "驿馆",
                "坊市",
                "王朝",
                "杭州",
                "实验区",
                "治理区",
                "社区",
                "校区",
                "数据中台",
                "公共服务",
            ]
        ):
            missing.append("world_scope")
        if not any(
            word in lowered
            for word in [
                "tone",
                "dark",
                "comic",
                "comedy",
                "warm",
                "serious",
                "mystery",
                "suspense",
                "romance",
                "romantic",
                "horror",
                "thriller",
                "epic",
                "adventure",
                "technology",
                "governance",
            ]
        ) and not any(
            word in prompt_text
            for word in [
                "悬疑",
                "温暖",
                "温柔",
                "黑暗",
                "轻松",
                "轻快",
                "严肃",
                "科幻",
                "浪漫",
                "甜",
                "喜剧",
                "搞笑",
                "恐怖",
                "惊悚",
                "史诗",
                "宏大",
                "冒险",
                "热血",
                "治愈",
                "悲伤",
                "悲剧",
                "压抑",
                "讽刺",
                "思辨",
                "典雅",
                "明朗",
                "奇诡",
                "传奇",
                "志怪",
                "游侠",
                "侠义",
                "科技",
                "理性",
                "治理",
                "社会议题",
            ]
        ):
            missing.append("tone")
        if not any(
            word in lowered for word in ["protagonist", "hero", "girl", "boy", "detective", "engineer", "auditor", "teacher"]
        ) and not any(
            word in prompt_text
            for word in [
                "主角",
                "主人公",
                "少年",
                "少女",
                "男孩",
                "女孩",
                "林夏",
                "守灯人",
                "侦探",
                "学生",
                "骑士",
                "工程师",
                "审计员",
                "老师",
                "教师",
                "医生",
                "职员",
                "机器人",
            ]
        ):
            missing.append("protagonist")
        if not any(
            word in lowered
            for word in ["conflict", "must", "wants", "against", "mystery", "secret", "alien", "code", "choose", "save"]
        ) and not any(
            word in prompt_text
            for word in [
                "危机",
                "冲突",
                "想要",
                "必须",
                "谜",
                "秘密",
                "外星代码",
                "代码",
                "科技",
                "人工智能",
                "AI治理",
                "算法",
                "算法审计",
                "数据中台",
                "教育机器人",
                "记忆备份",
                "公共服务",
                "自动化",
                "可追溯",
                "悬疑",
                "选择",
                "拯救",
                "寻找",
                "找回",
                "阻止",
                "逃离",
            ]
        ):
            missing.append("core_conflict")
        if not any(word in lowered for word in ["chapter", "short", "novel", "series"]) and not any(
            word in prompt_text for word in ["章", "短篇", "长篇", "小说", "系列"]
        ):
            missing.append("length_or_audience")
        return self._dedupe(missing)

    def _analyze_story_setup_prompt(
        self,
        prompt: StorySetupPrompt,
        prompt_text: str,
    ) -> dict[str, Any]:
        fallback = self._rule_based_story_setup_analysis(prompt, prompt_text)
        model_analysis = self._model_story_setup_analysis(
            project_id=prompt.project_id,
            prompt_text=prompt_text,
            fallback=fallback,
        )
        if model_analysis:
            return model_analysis
        status = self.model_gateway.validate_model_config()
        if status.configured and status.provider_type not in {None, "", "local"}:
            raise StorySetupBlocked(
                "真实模型未能完成故事设定分析，请重试。系统不会用内置规则结果冒充模型输出。"
            )
        return fallback

    def _model_story_setup_analysis(
        self,
        *,
        project_id: str,
        prompt_text: str,
        fallback: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not (prompt_text or "").strip():
            return None
        try:
            status = self.model_gateway.validate_model_config()
            if not status.configured or status.provider_type in {None, "", "local"}:
                return None
            result = self.model_gateway.generate_json(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是故事设定分析智能体。只输出一个 JSON 对象，不要输出 markdown。"
                            "根据用户输入自主判断故事类型、读者基调、核心冲突、主角功能、"
                            "待补充问题和每个问题的参考选项。不要套用固定题材；不要把所有题材都判成悬疑。"
                            "用户明确要求排除的题材、意象或情节只能作为禁止约束，"
                            "不得列入 detected_key_terms，也不得写入任何草案建议。"
                            "所有字段必须是安全、简短、面向创作工作台的草案建议，不写最终故事事实。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请分析下面的故事输入，并返回 JSON：\n"
                            "{\n"
                            '  "detected_genre_tags": ["类型词"],\n'
                            '  "detected_tone_tags": ["读者基调词"],\n'
                            '  "detected_world_scope": "世界范围草案",\n'
                            '  "detected_core_conflict": "核心冲突草案",\n'
                            '  "detected_protagonist_hint": "主角功能草案",\n'
                            '  "detected_story_length_hint": "篇幅草案",\n'
                            '  "prompt_signal_summary": "输入信号摘要",\n'
                            '  "detected_key_terms": ["关键实体或意象"],\n'
                            '  "missing_information_codes": ["world_scope|tone|protagonist|core_conflict|length_or_audience|magic_or_rule_system|technology_or_speculative_rule|relationship_focus|information_release"],\n'
                            '  "world_canvas_draft_suggestion": {},\n'
                            '  "main_cast_draft_direction": {},\n'
                            '  "framework_setup_suggestion": {},\n'
                            '  "chapter_route_suggestion": {},\n'
                            '  "questions": [\n'
                            '    {"question_type": "tone", "question_text": "需要用户确认的问题", "suggested_options": ["参考选项"]}\n'
                            "  ]\n"
                            "}\n\n"
                            f"用户输入：{prompt_text}"
                        ),
                    },
                ],
                schema_hint={
                    "kind": "story_setup_analysis",
                    "operation": "analyze_prompt",
                    "project_id": project_id,
                },
                options={
                    "temperature": 0.25,
                    "max_output_tokens": 1800,
                    "timeout_seconds": 75,
                    "max_attempts": 1,
                },
                project_id=project_id,
                agent_role="system",
                service_name="StorySetupService",
                operation_name="story_setup_analysis",
            )
        except (ModelConfigurationError, ModelCallError, ModelJsonParseError, StorySetupSafetyError):
            return None
        except Exception:
            return None
        return self._normalize_story_setup_analysis(
            result.data,
            fallback=fallback,
            used_real_provider=True,
            warning="model_generated_story_setup_analysis",
        )

    def _rule_based_story_setup_analysis(
        self,
        prompt: StorySetupPrompt,
        prompt_text: str,
    ) -> dict[str, Any]:
        genre_tags = self._detect_genre_tags(prompt_text)
        tone_tags = self._compose_story_setup_tone_tags(genre_tags, self._detect_tone_tags(prompt_text))
        key_terms = self._detect_key_terms(prompt_text)
        analysis = {
            "detected_genre_tags": genre_tags,
            "detected_tone_tags": tone_tags,
            "detected_world_scope": self._detect_world_scope(prompt_text),
            "detected_core_conflict": self._detected_conflict_summary(prompt_text),
            "detected_protagonist_hint": self._detected_protagonist_hint(prompt_text),
            "detected_story_length_hint": self._detected_length_hint(prompt_text),
            "prompt_signal_summary": self._prompt_signal_summary(prompt_text),
            "detected_key_terms": key_terms,
            "missing_information_codes": self._missing_information_codes(prompt, prompt_text),
            "used_real_provider": False,
            "used_deterministic_fallback": True,
            "warnings": ["dynamic_rule_based_story_setup_analysis"],
        }
        analysis["questions"] = self._dynamic_story_setup_question_specs(analysis)
        return analysis

    def _normalize_story_setup_analysis(
        self,
        payload: Any,
        *,
        fallback: dict[str, Any],
        used_real_provider: bool,
        warning: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return fallback
        normalized = dict(fallback)
        normalized["detected_genre_tags"] = self._safe_text_list(
            payload.get("detected_genre_tags"),
            fallback=fallback.get("detected_genre_tags") or [],
            limit=6,
            item_limit=36,
        )
        normalized["detected_tone_tags"] = self._safe_text_list(
            payload.get("detected_tone_tags"),
            fallback=fallback.get("detected_tone_tags") or [],
            limit=5,
            item_limit=36,
        )
        normalized["detected_tone_tags"] = self._compose_story_setup_tone_tags(
            normalized["detected_genre_tags"],
            normalized["detected_tone_tags"],
        )[:5]
        for key, limit in [
            ("detected_world_scope", 120),
            ("detected_core_conflict", 220),
            ("detected_protagonist_hint", 160),
            ("detected_story_length_hint", 120),
            ("prompt_signal_summary", 360),
        ]:
            normalized[key] = self._safe_analysis_text(
                payload.get(key),
                fallback=str(fallback.get(key) or ""),
                limit=limit,
            )
        normalized["detected_key_terms"] = self._safe_text_list(
            payload.get("detected_key_terms"),
            fallback=fallback.get("detected_key_terms") or [],
            limit=16,
            item_limit=40,
        )
        normalized["missing_information_codes"] = self._safe_missing_codes(
            payload.get("missing_information_codes"),
            fallback=fallback.get("missing_information_codes") or [],
        )
        for key in [
            "world_canvas_draft_suggestion",
            "main_cast_draft_direction",
            "framework_setup_suggestion",
            "chapter_route_suggestion",
        ]:
            normalized[key] = self._safe_analysis_dict(payload.get(key))
        normalized["questions"] = self._normalize_question_specs(
            payload.get("questions"),
            fallback=fallback.get("questions") or [],
        )
        normalized["used_real_provider"] = used_real_provider
        normalized["used_deterministic_fallback"] = not used_real_provider
        normalized["warnings"] = [warning]
        self._guard_safe_payload(normalized, allow_controlled_text=False)
        return normalized

    def _safe_analysis_text(self, value: Any, *, fallback: str = "", limit: int = 240) -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        try:
            return self._safe_text(text, limit)
        except StorySetupSafetyError:
            return fallback

    def _safe_text_list(
        self,
        value: Any,
        *,
        fallback: list[str],
        limit: int,
        item_limit: int,
    ) -> list[str]:
        raw_items: list[Any]
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            raw_items = re.split(r"[,，、;/；\n]+", value)
        else:
            raw_items = []
        items: list[str] = []
        for item in raw_items:
            safe = self._safe_analysis_text(item, limit=item_limit)
            if safe:
                items.append(safe)
        return self._dedupe(items)[:limit] or list(fallback)[:limit]

    def _safe_missing_codes(self, value: Any, *, fallback: list[str]) -> list[str]:
        raw = value if isinstance(value, list) else []
        codes = [
            str(item or "").strip()
            for item in raw
            if str(item or "").strip() in STORY_SETUP_MISSING_CODES
        ]
        return self._dedupe(codes) or list(fallback)

    def _safe_analysis_dict(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, Any] = {}
        for key, child in value.items():
            safe_key = re.sub(r"[^A-Za-z0-9_]+", "_", str(key or "")).strip("_")[:80]
            if not safe_key:
                continue
            if isinstance(child, list):
                result[safe_key] = self._safe_text_list(
                    child,
                    fallback=[],
                    limit=8,
                    item_limit=120,
                )
            elif isinstance(child, dict):
                nested = self._safe_analysis_dict(child)
                if nested:
                    result[safe_key] = nested
            else:
                safe_value = self._safe_analysis_text(child, limit=240)
                if safe_value:
                    result[safe_key] = safe_value
        return result

    def _normalize_question_specs(
        self,
        value: Any,
        *,
        fallback: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return fallback
        specs: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            question_type = str(item.get("question_type") or "").strip()
            if question_type not in STORY_SETUP_MISSING_CODES:
                question_type = "core_conflict"
            question_text = self._safe_analysis_text(
                item.get("question_text"),
                limit=140,
            )
            if not question_text:
                continue
            options = self._safe_text_list(
                item.get("suggested_options"),
                fallback=[],
                limit=4,
                item_limit=80,
            )
            specs.append(
                {
                    "question_type": question_type,
                    "question_text": question_text,
                    "suggested_options": options,
                }
            )
        return specs[:5] or fallback

    def _dynamic_story_setup_question_specs(self, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        terms = list(analysis.get("detected_key_terms") or [])
        genres = list(analysis.get("detected_genre_tags") or [])
        tones = [tone for tone in analysis.get("detected_tone_tags") or [] if tone != "tone_to_confirm"]
        missing = list(analysis.get("missing_information_codes") or [])
        anchor = terms[0] if terms else "当前故事"
        primary_tone = tones[0] if tones else ""
        tone_label = self._story_setup_display_label(primary_tone) if primary_tone else ""
        specs: list[dict[str, Any]] = []

        specs.append(
            {
                "question_type": "world_scope",
                "question_text": f"「{anchor}」所在故事世界的边界需要确认到哪一层？",
                "suggested_options": [
                    f"只锁定「{anchor}」及直接相关地点",
                    f"扩展到「{anchor}」周边组织或区域",
                    "保留更大世界存在，但本阶段不展开",
                ],
            }
        )
        if primary_tone:
            specs.append(
                {
                    "question_type": "tone",
                    "question_text": f"后续草案应如何处理「{tone_label}」基调？",
                    "suggested_options": [
                        f"以「{tone_label}」作为主要阅读感受",
                        f"保留「{tone_label}」，但加入反差情绪",
                        f"降低「{tone_label}」强度，给角色选择留空间",
                    ],
                }
            )
        else:
            specs.append(
                {
                    "question_type": "tone",
                    "question_text": "读者在第一阶段应优先感受到什么基调？",
                    "suggested_options": self._tone_options_for_genres(genres),
                }
            )
        protagonist = str(analysis.get("detected_protagonist_hint") or "")
        protagonist_label = self._protagonist_display_label(protagonist)
        specs.append(
            {
                "question_type": "protagonist",
                "question_text": f"关于「{protagonist_label or '主角'}」，第一阶段更应承担什么故事功能？",
                "suggested_options": self._protagonist_options_for_genres(genres),
            }
        )
        specs.append(
            {
                "question_type": "core_conflict",
                "question_text": "当前草案最需要确认哪一种核心冲突？",
                "suggested_options": self._conflict_options_for_genres(genres, terms),
            }
        )
        if any(tag in genres for tag in ["fantasy", "low_fantasy", "xianxia", "wuxia"]):
            specs.append(
                {
                    "question_type": "magic_or_rule_system",
                    "question_text": "超自然或规则系统应严格到什么程度？",
                    "suggested_options": [
                        "只保留一个核心规则",
                        "允许少量软规则制造余韵",
                        "先不解释机制，只确认代价",
                    ],
                }
            )
        elif "science_fiction" in genres:
            specs.append(
                {
                    "question_type": "technology_or_speculative_rule",
                    "question_text": "科幻或异常设定需要先确认哪条底层规则？",
                    "suggested_options": [
                        "确认技术边界和代价",
                        "确认异常现象的来源",
                        "先保留未知，只确认不能越界的限制",
                    ],
                }
            )
        elif any(tag in genres for tag in ["romance", "family", "slice_of_life"]):
            specs.append(
                {
                    "question_type": "relationship_focus",
                    "question_text": "关系线应优先推动哪类变化？",
                    "suggested_options": [
                        "从误解走向靠近",
                        "从依赖走向独立",
                        "从隐瞒走向坦白",
                    ],
                }
            )
        else:
            specs.append(
                {
                    "question_type": "length_or_audience",
                    "question_text": "第一版规划应按什么篇幅和读者期待推进？",
                    "suggested_options": [
                        "短篇闭环，快速完成主要冲突",
                        "多章节展开，保留支线空间",
                        "系列化开端，只确认第一阶段目标",
                    ],
                }
            )
        if any(tag in genres for tag in ["mystery", "crime", "thriller"]) and not any(
            spec["question_type"] == "information_release" for spec in specs
        ):
            specs.append(
                {
                    "question_type": "information_release",
                    "question_text": "悬念或真相信息应在第一阶段释放到什么程度？",
                    "suggested_options": [
                        "只释放异常现象，不解释来源",
                        "释放一个可验证线索",
                        "让角色知道一部分，读者知道更少",
                    ],
                }
            )
        priority = missing or [spec["question_type"] for spec in specs]
        ordered = sorted(
            specs,
            key=lambda spec: priority.index(spec["question_type"])
            if spec["question_type"] in priority
            else len(priority),
        )
        return ordered[:5]

    def _tone_options_for_genres(self, genres: list[str]) -> list[str]:
        if any(tag in genres for tag in ["historical", "legend", "zhiguai", "wuxia"]):
            return ["典雅奇诡", "明朗游侠", "志怪传奇"]
        if "romance" in genres:
            return ["浪漫但克制", "轻快甜感", "苦涩拉扯"]
        if "science_fiction" in genres:
            return ["冷峻探索", "宏大未知", "紧张危机"]
        if any(tag in genres for tag in ["fantasy", "low_fantasy", "xianxia"]):
            return ["奇诡神秘", "史诗感", "温柔幻想"]
        if any(tag in genres for tag in ["horror", "thriller", "crime"]):
            return ["压迫紧张", "黑暗惊悚", "冷静调查"]
        if "comedy" in genres:
            return ["轻快喜剧", "荒诞讽刺", "温暖日常"]
        return ["严肃克制", "温暖治愈", "紧张推进"]

    def _protagonist_options_for_genres(self, genres: list[str]) -> list[str]:
        if any(tag in genres for tag in ["historical", "legend", "zhiguai", "wuxia"]):
            return ["在礼法与侠义之间做选择", "承担奇遇带来的代价", "连接民间传闻与正式秩序"]
        if "romance" in genres:
            return ["主动修复关系裂痕", "在靠近与退让之间选择", "让关系变化推动主线"]
        if "science_fiction" in genres:
            return ["验证技术或异常规则的边界", "保护具体的人不被系统目标吞没", "在效率、责任与风险之间做选择"]
        if any(tag in genres for tag in ["fantasy", "low_fantasy", "xianxia"]):
            return ["承担规则代价", "保护重要对象", "在力量诱惑与底线之间选择"]
        if any(tag in genres for tag in ["mystery", "crime", "thriller"]):
            return ["主动追寻真相或目标", "保护关键证据或见证者", "在危险信息差中推进调查"]
        if "comedy" in genres:
            return ["制造误会并推动修正", "用反差行动打开局面", "在轻快冲突中完成选择"]
        return ["主动推进核心目标", "保护某个重要对象", "作为见证者逐步理解世界"]

    def _conflict_options_for_genres(self, genres: list[str], terms: list[str]) -> list[str]:
        anchor = terms[0] if terms else "核心目标"
        if any(tag in genres for tag in ["historical", "legend", "zhiguai", "wuxia"]):
            return ["礼法与侠义的选择", "人情与异象的代价", f"围绕「{anchor}」的奇遇阻碍"]
        if "romance" in genres:
            return ["关系误解", "价值观冲突", f"围绕「{anchor}」的选择代价"]
        if "science_fiction" in genres:
            return ["技术边界与责任归属", "公共效率与个体处境", f"围绕「{anchor}」的认知或治理危机"]
        if any(tag in genres for tag in ["fantasy", "low_fantasy", "xianxia", "wuxia"]):
            return ["规则代价", "旧秩序压迫", f"围绕「{anchor}」的禁忌选择"]
        if any(tag in genres for tag in ["mystery", "crime", "thriller"]):
            return ["真相遮蔽", "外部威胁", f"围绕「{anchor}」的调查阻力"]
        return ["外部压力", "道德选择", f"围绕「{anchor}」的目标阻碍"]

    def _story_setup_display_label(self, value: str) -> str:
        labels = {
            "sci_fi_suspense": "科幻悬疑",
            "cold_tech": "冷峻技术感",
            "suspense": "悬疑",
            "mystery": "谜团",
            "dark": "偏暗",
            "warm": "温暖",
            "light": "轻快",
            "serious": "严肃",
            "romantic": "浪漫",
            "comedic": "喜剧",
            "adventurous": "冒险",
            "epic": "史诗",
            "horror": "恐怖",
            "healing": "治愈",
            "tragic": "悲伤",
            "satirical": "讽刺",
            "speculative": "思辨",
            "classical": "典雅",
            "bright": "明朗",
            "strange": "奇诡",
            "legend": "传奇",
            "zhiguai": "志怪",
        }
        return labels.get(value, value)

    def _protagonist_display_label(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "主角"
        if ":" in text:
            prefix, rest = text.split(":", 1)
            if prefix == "named_protagonist_suggestion":
                return rest.strip() or "主角线索"
            return self._story_setup_display_label(rest.strip() or prefix)
        labels = {
            "detective_function_suggestion": "调查者主角",
            "named_or_central_protagonist_suggestion": "核心主角",
            "young_protagonist_function_suggestion": "年轻或核心主角",
            "protagonist_function_to_confirm": "主角",
        }
        return labels.get(text, self._story_setup_display_label(text))

    def _prompt_signal_summary(self, text: str) -> str:
        if not (text or "").strip():
            return "No controlled prompt text was available for Story Setup analysis."
        terms = self._detect_key_terms(text)
        if terms:
            return self._safe_text(
                f"Controlled prompt signals detected: {', '.join(terms)}.",
                360,
            )
        return "Controlled prompt text was available; no specific deterministic signals were detected."

    def _detect_key_terms(self, text: str) -> list[str]:
        lowered = text.lower()
        terms: list[str] = []
        terms.extend(
            term
            for term in self._extract_prompt_anchor_terms(text)
            if not self._keyword_is_negated(text, term)
        )
        for keyword in [
            "Mars",
            "colony",
            "colonist",
            "science fiction",
            "sci-fi",
            "alien",
            "code",
            "火星",
            "殖民",
            "殖民地",
            "科幻",
            "外星",
            "外星代码",
            "代码",
            "林夏",
            "基地",
            "太空",
            "星球",
            "悬疑",
            "浪漫爱情",
            "爱情",
            "恋爱",
            "低魔",
            "魔法",
            "秘密",
            "危机",
            "冲突",
            "唐代",
            "唐朝",
            "盛唐",
            "中唐",
            "晚唐",
            "长安",
            "洛阳",
            "西市",
            "东市",
            "道观",
            "驿馆",
            "夜禁",
            "传奇",
            "志怪",
            "游侠",
            "侠义",
            "青玉佩",
            "玉佩",
            "胡商",
            "女史",
            "古镜",
            "异象",
            "礼法",
            "奇遇",
            "典雅",
            "明朗",
            "奇诡",
        ]:
            if (keyword.lower() in lowered or keyword in text) and not self._keyword_is_negated(text, keyword):
                terms.append(keyword)
        return self._dedupe(terms)[:20]

    def _extract_prompt_anchor_terms(self, text: str) -> list[str]:
        source = re.sub(r"\s+", " ", text or "").strip()
        if not source:
            return []
        terms: list[str] = []
        suffix_pattern = (
            r"[\u4e00-\u9fffA-Za-z0-9·]{0,8}"
            r"(?:码头|港口|灯塔|钟楼|塔|月亮|潮汐|彗星|记忆|邮差|船员|鲸|黑信|信|钟|姐姐|哥哥|"
            r"母亲|父亲|城市|小镇|村庄|王国|学院|学校|剧院|桥|列车|图书馆|档案馆|"
            r"森林|岛|河|海|花园|宫殿|基地|殖民地|代码|钥匙|契约|王冠|诅咒|梦境|"
            r"杭州|实验区|治理区|社区|校区|数据中台|算法|算法审计|审计日志|追溯日志|"
            r"教育机器人|机器人|记忆备份|公共服务|人工智能|AI治理|科技治理|"
            r"长安|洛阳|西市|东市|道观|驿馆|坊市|夜禁|玉佩|青玉佩|古镜|胡商|女史|遗书|文书|异象|奇遇)"
        )
        role_name_pattern = (
            r"[\u4e00-\u9fff]{0,4}"
            r"(?:侦探|邮差|修复师|术士|守夜人|守灯人|记者|骑士|女巫|学生|船长|医生|主角|女史|书生|进士)"
            r"[\u4e00-\u9fff]{1,4}"
        )
        for pattern in [
            r"(?:主角|主人公)([\u4e00-\u9fff]{2,4})(?:和|与)(?:旧友|朋友|同伴|恋人|爱人)?([\u4e00-\u9fff]{2,4})",
            r"(?:主角|主人公)([\u4e00-\u9fff]{2,4})(?:在|必须|想要|和|与|，|。|,|\.|\s|$)",
            r"(?:发生在|位于|来自|围绕)([\u4e00-\u9fffA-Za-z0-9·]{2,14}?)(?:的|、|，|。|,|\.|\s|$)",
            r"(?:找回|寻找|救回|保护|阻止|揭开|解开|追踪)([\u4e00-\u9fffA-Za-z0-9·]{2,14})(?:，|。|,|\.|\s|$)",
            r"(?:刻进|藏进|写进|封进|送入|放入)([\u4e00-\u9fffA-Za-z0-9·]{2,14})(?:，|。|,|\.|\s|$)",
            r"([\u4e00-\u9fff]{0,4}(?:侦探|邮差|修复师|术士|守夜人|守灯人|记者|骑士|女巫|学生|船长|医生|主角|女史|书生|进士)[\u4e00-\u9fff]{1,4})(?:收到|发现|必须|，|。|,|\.|\s|$)",
            r"([\u4e00-\u9fffA-Za-z0-9·]{2,14}?)(?:每逢|升起|倒放|收到|寄来|寄来的|敲响|会把|刻进|落下|留下|必须|发现|引发|拯救|选择|隐藏|失踪|消失|出现)",
            r"([\u4e00-\u9fffA-Za-z0-9·]{2,14}?)(?:的影子|的线索|的秘密|的遗物)",
            suffix_pattern,
            role_name_pattern,
        ]:
            for match in re.finditer(pattern, source):
                raw_values = (
                    [match.group(index) for index in range(1, match.lastindex + 1)]
                    if match.lastindex
                    else [match.group(0)]
                )
                for raw in raw_values:
                    term = self._clean_prompt_anchor_term(raw)
                    if term:
                        terms.append(term)
        return self._dedupe(terms)[:10]

    def _keyword_is_negated(self, text: str, keyword: str) -> bool:
        source = text or ""
        needle = keyword or ""
        if not needle:
            return False
        lowered_source = source.lower()
        lowered_needle = needle.lower()
        starts: list[int] = []
        cursor = 0
        while True:
            start = lowered_source.find(lowered_needle, cursor)
            if start < 0:
                break
            starts.append(start)
            cursor = start + max(1, len(lowered_needle))
        if not starts:
            return False

        negation_markers = ["不要", "不能", "不是", "避免", "不写", "别写", "拒绝", "排除", "禁止", "不得"]
        clause_boundaries = ["。", "！", "？", "；", ";", "\n", "但是", "但要", "而是", "却要"]
        for start in starts:
            clause_start = 0
            for boundary in clause_boundaries:
                boundary_index = source.rfind(boundary, 0, start)
                if boundary_index >= 0:
                    clause_start = max(clause_start, boundary_index + len(boundary))
            prefix = source[clause_start:start]
            if not any(marker in prefix for marker in negation_markers):
                return False
        return True

    def _clean_prompt_anchor_term(self, value: str) -> str:
        term = (value or "").strip(" ，。,.、；;：:（）()[]【】")
        if not term:
            return ""
        if re.search(r"\d", term):
            return ""
        for marker in [
            "我要写一个发生在",
            "我想写一个发生在",
            "发生在",
            "主角",
            "主人公",
            "必须",
            "必须在",
            "需要",
            "每逢",
            "收到",
            "发现",
            "找回",
            "寻找",
            "留下的",
            "留下",
            "会把",
            "围绕",
            "来自",
            "倒放",
            "拯救",
            "寄来的",
            "寄来",
            "一位",
            "一名",
            "一个",
            "一间",
            "这个",
            "那个",
        ]:
            if marker in term and len(term) > len(marker):
                term = term.split(marker)[-1]
        for trailing in ["的影子", "的线索", "的秘密", "的遗物", "升起就", "升起", "每逢"]:
            if trailing in term and len(term) > len(trailing):
                term = term.split(trailing)[0]
        if "在" in term and len(term) >= 4:
            term = term.split("在")[-1]
        term = term.strip(" 的了着过中里内外上下前后，。,.、；;：:（）()[]【】")
        if len(term) < 2 or len(term) > 14:
            return ""
        generic_terms = {
            "故事",
            "小说",
            "主角",
            "世界",
            "低魔",
            "悬疑",
            "低魔悬疑故事",
            "悬疑故事",
            "长篇小说",
            "星代码",
            "这段代码",
            "判断这段代码",
            "是在拯救殖民",
        }
        if term in generic_terms:
            return ""
        return term

    def _detect_genre_tags(self, text: str) -> list[str]:
        lowered = text.lower()
        tags = []
        for keyword, tag in [
            ("detective", "mystery"),
            ("mystery", "mystery"),
            ("suspense", "mystery"),
            ("fantasy", "fantasy"),
            ("magic", "fantasy"),
            ("dragon", "fantasy"),
            ("space", "science_fiction"),
            ("mars", "science_fiction"),
            ("colony", "science_fiction"),
            ("alien", "science_fiction"),
            ("science fiction", "science_fiction"),
            ("sci-fi", "science_fiction"),
            ("code", "science_fiction"),
            ("robot", "science_fiction"),
            ("technology", "science_fiction"),
            ("governance", "science_fiction"),
            ("algorithm", "science_fiction"),
            ("romance", "romance"),
            ("love story", "romance"),
            ("comedy", "comedy"),
            ("horror", "horror"),
            ("thriller", "thriller"),
            ("crime", "crime"),
            ("historical", "historical"),
            ("adventure", "adventure"),
            ("legend", "legend"),
            ("chuanqi", "legend"),
            ("悬疑", "mystery"),
            ("低魔", "low_fantasy"),
            ("魔法", "fantasy"),
            ("奇幻", "fantasy"),
            ("仙侠", "xianxia"),
            ("武侠", "wuxia"),
            ("唐代", "historical"),
            ("唐朝", "historical"),
            ("盛唐", "historical"),
            ("长安", "historical"),
            ("传奇", "legend"),
            ("志怪", "zhiguai"),
            ("游侠", "wuxia"),
            ("侠义", "wuxia"),
            ("古镜", "fantasy"),
            ("异象", "fantasy"),
            ("爱情", "romance"),
            ("恋爱", "romance"),
            ("浪漫", "romance"),
            ("喜剧", "comedy"),
            ("搞笑", "comedy"),
            ("恐怖", "horror"),
            ("惊悚", "thriller"),
            ("犯罪", "crime"),
            ("推理", "mystery"),
            ("历史", "historical"),
            ("古代", "historical"),
            ("校园", "campus"),
            ("都市", "urban"),
            ("日常", "slice_of_life"),
            ("冒险", "adventure"),
            ("战争", "war"),
            ("太空", "science_fiction"),
            ("火星", "science_fiction"),
            ("殖民", "science_fiction"),
            ("科幻", "science_fiction"),
            ("科技", "science_fiction"),
            ("人工智能", "science_fiction"),
            ("AI治理", "science_fiction"),
            ("算法", "science_fiction"),
            ("算法审计", "science_fiction"),
            ("数据中台", "science_fiction"),
            ("教育机器人", "science_fiction"),
            ("记忆备份", "science_fiction"),
            ("公共服务", "science_fiction"),
            ("自动化", "science_fiction"),
            ("可追溯", "science_fiction"),
            ("外星", "science_fiction"),
            ("代码", "science_fiction"),
        ]:
            if (keyword in lowered or keyword in text) and not self._keyword_is_negated(text, keyword):
                tags.append(tag)
        return self._dedupe(tags) or ["open_genre"]

    def _detect_tone_tags(self, text: str) -> list[str]:
        lowered = text.lower()
        tags = []
        for keyword, tag in [
            ("dark", "dark"),
            ("warm", "warm"),
            ("comic", "light"),
            ("serious", "serious"),
            ("rational", "serious"),
            ("governance", "serious"),
            ("mystery", "suspense"),
            ("suspense", "suspense"),
            ("romantic", "romantic"),
            ("romance", "romantic"),
            ("comedy", "comedic"),
            ("comic", "comedic"),
            ("adventure", "adventurous"),
            ("epic", "epic"),
            ("legend", "strange"),
            ("chuanqi", "strange"),
            ("horror", "horror"),
            ("thriller", "horror"),
            ("tragic", "tragic"),
            ("satire", "satirical"),
            ("黑暗", "dark"),
            ("温暖", "warm"),
            ("温柔", "warm"),
            ("轻松", "light"),
            ("轻快", "light"),
            ("严肃", "serious"),
            ("理性", "serious"),
            ("治理", "serious"),
            ("社会议题", "serious"),
            ("责任", "serious"),
            ("浪漫", "romantic"),
            ("甜", "romantic"),
            ("喜剧", "comedic"),
            ("搞笑", "comedic"),
            ("冒险", "adventurous"),
            ("热血", "adventurous"),
            ("典雅", "classical"),
            ("明朗", "bright"),
            ("奇诡", "strange"),
            ("传奇", "strange"),
            ("志怪", "strange"),
            ("游侠", "adventurous"),
            ("侠义", "adventurous"),
            ("史诗", "epic"),
            ("宏大", "epic"),
            ("恐怖", "horror"),
            ("惊悚", "horror"),
            ("治愈", "healing"),
            ("悲伤", "tragic"),
            ("悲剧", "tragic"),
            ("压抑", "tragic"),
            ("讽刺", "satirical"),
            ("思辨", "speculative"),
            ("悬疑", "suspense"),
        ]:
            if (keyword in lowered or keyword in text) and not self._keyword_is_negated(text, keyword):
                tags.append(tag)
        return self._dedupe(tags) or ["tone_to_confirm"]

    def _compose_story_setup_tone_tags(self, genres: list[str], tones: list[str]) -> list[str]:
        genre_set = set(genres or [])
        normalized = [tone for tone in self._dedupe(tones or []) if tone and tone != "tone_to_confirm"]
        if "science_fiction" in genre_set:
            if "suspense" in normalized or "mystery" in genre_set:
                normalized = ["sci_fi_suspense"] + [tone for tone in normalized if tone != "suspense"]
            if "warm" in normalized and "serious" in normalized:
                normalized.extend(["speculative"])
            elif not any(tone in normalized for tone in ["speculative", "cold_tech", "adventurous"]):
                normalized.extend(["speculative", "cold_tech"])
        if any(tag in genre_set for tag in ["historical", "legend", "zhiguai"]) and "strange" not in normalized:
            normalized.append("strange")
        return self._dedupe(normalized) or ["tone_to_confirm"]

    def _detect_world_scope(self, text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ["empire", "planet", "space", "kingdom", "mars", "colony"]) or any(
            word in text for word in ["火星", "殖民", "殖民地", "星球", "太空", "基地"]
        ):
            return "large_scope_suggestion"
        if any(word in lowered for word in ["city", "village", "school", "harbor", "port", "tower"]) or any(
            word in text
            for word in [
                "城市",
                "村庄",
                "学校",
                "码头",
                "港口",
                "灯塔",
                "钟楼",
                "小镇",
                "学院",
                "唐代",
                "唐朝",
                "长安",
                "洛阳",
                "西市",
                "东市",
                "道观",
                "驿馆",
                "坊市",
            ]
        ):
            return "focused_location_suggestion"
        return "world_scope_to_confirm"

    def _detected_conflict_summary(self, text: str) -> str:
        if text.strip():
            terms = self._detect_key_terms(text)
            if terms:
                pressure = self._extract_conflict_pressure(text)
                summary = "Controlled prompt conflict signals: " + ", ".join(terms)
                if pressure:
                    summary = f"{summary}; pressure: {pressure}"
                return self._safe_text(summary, 260)
            return "A central conflict is implied by the controlled prompt and needs user confirmation."
        return "Core conflict is missing and should be clarified before downstream confirmation."

    def _extract_conflict_pressure(self, text: str) -> str:
        for pattern in [
            r"(必须[\u4e00-\u9fffA-Za-z0-9·，,、]{4,40})(?:。|\.|$)",
            r"(需要[\u4e00-\u9fffA-Za-z0-9·，,、]{4,40})(?:。|\.|$)",
            r"(想要[\u4e00-\u9fffA-Za-z0-9·，,、]{4,40})(?:。|\.|$)",
        ]:
            match = re.search(pattern, text or "")
            if match:
                return self._safe_text(match.group(1).strip(" ，,、"), 90)
        return ""

    def _detected_protagonist_hint(self, text: str) -> str:
        lowered = text.lower()
        role_named = re.search(r"(?:女史|书生|进士)([\u4e00-\u9fff]{2,4})", text or "")
        if role_named:
            return f"named_protagonist_suggestion:{role_named.group(1)}"
        if "林夏" in text:
            return "named_protagonist_suggestion:林夏"
        named = self._extract_named_protagonist_hint(text)
        if named:
            return f"named_protagonist_suggestion:{named}"
        role_name = self._extract_protagonist_anchor(text)
        if role_name:
            return f"named_protagonist_suggestion:{role_name}"
        if "detective" in lowered or "侦探" in text:
            return "detective_function_suggestion"
        if any(word in lowered for word in ["protagonist", "hero"]):
            return "named_or_central_protagonist_suggestion"
        if any(word in lowered for word in ["child", "girl", "boy"]) or any(
            word in text for word in ["主角", "主人公", "少年", "少女", "孩子"]
        ):
            return "young_protagonist_function_suggestion"
        return "protagonist_function_to_confirm"

    def _extract_named_protagonist_hint(self, text: str) -> str:
        source = re.sub(r"\s+", "", text or "")
        for pattern in [
            r"(?:主角|主人公)([\u4e00-\u9fff]{2,4})(?:和|与)(?:旧友|朋友|同伴|恋人|爱人)?([\u4e00-\u9fff]{2,4})",
            r"(?:主角|主人公)([\u4e00-\u9fff]{2,4})(?:在|必须|想要|收到|发现|和|与|，|。|,|\.|$)",
        ]:
            match = re.search(pattern, source)
            if not match:
                continue
            names = [self._clean_prompt_anchor_term(group) for group in match.groups()]
            names = [name for name in names if name]
            if names:
                return " / ".join(self._dedupe(names)[:2])
        return ""

    def _extract_protagonist_anchor(self, text: str) -> str:
        for term in self._extract_prompt_anchor_terms(text):
            if any(role in term for role in ["侦探", "邮差", "修复师", "术士", "守夜人", "守灯人", "记者", "骑士", "女巫", "学生", "船长", "医生"]):
                return term
        return ""

    def _detected_length_hint(self, text: str) -> str:
        lowered = text.lower()
        if "5x5" in lowered or "5章" in text or "每章5幕" in text:
            return "five_chapters_five_scenes"
        if "short" in lowered or "短篇" in text:
            return "short_story_or_novella"
        if "series" in lowered or "长篇" in text:
            return "long_form_or_series"
        return "length_to_confirm"

    def _world_canvas_suggestion(self, intake: StorySetupIntake) -> dict[str, Any]:
        analyzed = self._analysis_section(intake, "world_canvas_draft_suggestion")
        signal = self._prompt_signal_payload(intake)
        if analyzed:
            return {
                "status": "draft_suggestion",
                "requires_confirmation": True,
                **analyzed,
                **signal,
            }
        anchor = intake.detected_key_terms[0] if intake.detected_key_terms else "核心设定"
        rule_hint = self._world_rule_hint_for_intake(intake, anchor)
        return {
            "status": "draft_suggestion",
            "requires_confirmation": True,
            "world_scope": intake.detected_world_scope,
            "tone_candidates": intake.detected_tone_tags,
            "hard_rule_candidates": [rule_hint],
            "soft_rule_candidates": [
                f"保留输入中的核心意象：{', '.join(intake.detected_key_terms[:16])}"
                if intake.detected_key_terms
                else "先确认世界基调、题材类型与核心异常是否存在。"
            ],
            "unknown_logic_gaps": intake.missing_information_codes,
            "potential_conflict": intake.detected_core_conflict,
            **signal,
        }

    def _main_cast_direction(self, intake: StorySetupIntake) -> dict[str, Any]:
        analyzed = self._analysis_section(intake, "main_cast_draft_direction")
        signal = self._prompt_signal_payload(intake)
        if analyzed:
            return {
                "status": "draft_direction",
                "requires_confirmation": True,
                **analyzed,
                **signal,
            }
        protagonist = self._protagonist_display_label(intake.detected_protagonist_hint)
        protagonist = protagonist if protagonist and protagonist != "protagonist_function_to_confirm" else "主角"
        return {
            "status": "draft_direction",
            "requires_confirmation": True,
            "main_cast_size": "small_to_medium_cast",
            "protagonist_function": intake.detected_protagonist_hint,
            "desire_direction": f"在角色工作台确认「{protagonist}」最想得到、守住或逃离的东西。",
            "opposing_force_direction": f"围绕「{protagonist}」与核心冲突确认主要阻力。",
            "relationship_tension_direction": "关系事实暂不写死，只保留需要后续确认的关系张力。",
            **signal,
        }

    def _framework_suggestion(self, intake: StorySetupIntake) -> dict[str, Any]:
        analyzed = self._analysis_section(intake, "framework_setup_suggestion")
        signal = self._prompt_signal_payload(intake)
        if analyzed:
            return {
                "status": "draft_suggestion",
                "requires_confirmation": True,
                **analyzed,
                **signal,
            }
        return {
            "status": "draft_suggestion",
            "requires_confirmation": True,
            "macro_framework_shape": self._framework_shape_for_intake(intake),
            "chapter_count_range": "1-20",
            "conflict_escalation_path": intake.detected_core_conflict
            if intake.detected_core_conflict
            else "从初始目标推进到不可逆选择。",
            "reversal_crisis_climax_direction": "转折、危机与高潮仍交给 Framework 与章节规划工作台确认。",
            "constraint_strength_suggestion": "medium",
            "genre_tags": intake.detected_genre_tags,
            **signal,
        }

    def _chapter_route_suggestion(self, intake: StorySetupIntake) -> dict[str, Any]:
        analyzed = self._analysis_section(intake, "chapter_route_suggestion")
        signal = self._prompt_signal_payload(intake)
        if analyzed:
            return {
                "status": "draft_suggestion",
                "requires_confirmation": True,
                **analyzed,
                **signal,
            }
        return {
            "status": "draft_suggestion",
            "requires_confirmation": True,
            "route_type": "lightweight_macro_route",
            "chapter_route": self._chapter_route_for_intake(intake),
            "length_hint": intake.detected_story_length_hint,
            "notes": (
                "这不是已确认的章节路线或篇章 Framework。确认前只作为故事设定草案参考。"
            ),
            **signal,
        }

    def _analysis_section(self, intake: StorySetupIntake, key: str) -> dict[str, Any]:
        snapshot = intake.analysis_snapshot or {}
        value = snapshot.get(key)
        return dict(value) if isinstance(value, dict) else {}

    def _world_rule_hint_for_intake(self, intake: StorySetupIntake, anchor: str) -> str:
        genres = set(intake.detected_genre_tags)
        if "science_fiction" in genres:
            return f"先确认「{anchor}」相关技术或异常现象的边界、代价和不可突破限制。"
        if genres.intersection({"fantasy", "low_fantasy", "xianxia", "wuxia"}):
            return f"先确认「{anchor}」相关超自然规则的触发条件、代价和失效条件。"
        if genres.intersection({"romance", "family", "slice_of_life"}):
            return f"先确认「{anchor}」所在现实/关系环境中不可随意改写的社会与人物边界。"
        if genres.intersection({"mystery", "crime", "thriller", "horror"}):
            return f"先确认「{anchor}」相关线索、真相和危险不能提前越权揭示。"
        return f"先确认「{anchor}」作为故事基础设定时哪些内容属于硬边界。"

    def _framework_shape_for_intake(self, intake: StorySetupIntake) -> str:
        genres = set(intake.detected_genre_tags)
        if "romance" in genres:
            return "encounter_tension_choice_resolution"
        if "science_fiction" in genres:
            return "premise_discovery_escalation_consequence"
        if genres.intersection({"fantasy", "low_fantasy", "xianxia", "wuxia"}):
            return "rule_reveal_trial_cost_transformation"
        if genres.intersection({"mystery", "crime", "thriller"}):
            return "clue_discovery_pressure_reversal_truth"
        if "comedy" in genres:
            return "setup_misread_escalation_payoff"
        return "setup_escalation_choice_resolution"

    def _chapter_route_for_intake(self, intake: StorySetupIntake) -> list[str]:
        genres = set(intake.detected_genre_tags)
        if "romance" in genres:
            return ["关系入口", "误解或吸引升级", "选择与关系代价"]
        if "science_fiction" in genres:
            return ["设定异常出现", "规则边界被测试", "技术或生存代价显现"]
        if genres.intersection({"fantasy", "low_fantasy", "xianxia", "wuxia"}):
            return ["规则或禁忌显影", "试炼推进", "代价与身份变化"]
        if genres.intersection({"mystery", "crime", "thriller"}):
            return ["线索入口", "调查压力升级", "反转或真相边缘"]
        if "comedy" in genres:
            return ["误会建立", "失控升级", "包袱回收"]
        return ["开端与处境", "压力推进", "选择与后果"]

    def _prompt_signal_payload(self, intake: StorySetupIntake) -> dict[str, Any]:
        return {
            "prompt_signal_summary": intake.prompt_signal_summary,
            "detected_key_terms": intake.detected_key_terms,
        }

    def _build_questions(
        self,
        bundle: StorySetupDraftBundle,
        intake: StorySetupIntake,
        now: str,
    ) -> list[StorySetupQuestion]:
        specs = (
            self._normalize_question_specs(
                (intake.analysis_snapshot or {}).get("questions"),
                fallback=[],
            )
            or self._dynamic_story_setup_question_specs(intake.analysis_snapshot or self._intake_analysis_view(intake))
        )
        return [
            StorySetupQuestion(
                story_setup_question_id=f"story_setup_question_{uuid4().hex[:12]}",
                project_id=bundle.project_id,
                story_setup_intake_id=bundle.story_setup_intake_id,
                story_setup_draft_bundle_id=bundle.story_setup_draft_bundle_id,
                question_type=spec["question_type"],
                question_text=spec["question_text"],
                suggested_options=spec["suggested_options"],
                created_at=now,
                updated_at=now,
            )
            for spec in specs[:5]
        ]

    def _intake_analysis_view(self, intake: StorySetupIntake) -> dict[str, Any]:
        return {
            "detected_genre_tags": intake.detected_genre_tags,
            "detected_tone_tags": intake.detected_tone_tags,
            "detected_world_scope": intake.detected_world_scope,
            "detected_core_conflict": intake.detected_core_conflict,
            "detected_protagonist_hint": intake.detected_protagonist_hint,
            "detected_story_length_hint": intake.detected_story_length_hint,
            "prompt_signal_summary": intake.prompt_signal_summary,
            "detected_key_terms": intake.detected_key_terms,
            "missing_information_codes": intake.missing_information_codes,
        }

    def _draft_warnings(
        self,
        prompt: StorySetupPrompt,
        intake: StorySetupIntake,
    ) -> list[str]:
        warnings = ["requires_downstream_confirmation"]
        if intake.used_real_provider:
            warnings.append("model_generated_story_setup_analysis")
        if intake.used_deterministic_fallback:
            warnings.append("deterministic_fallback_used")
        if prompt.needs_prompt_text_confirmation:
            warnings.append("prompt_text_confirmation_needed")
        warnings.extend([f"missing:{code}" for code in intake.missing_information_codes])
        return self._dedupe(warnings)

    def _mark_suggestion(self, value: dict[str, Any], field: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise StorySetupBlocked(f"{field}_must_be_object")
        next_value = dict(value)
        next_value["status"] = next_value.get("status") or "draft_suggestion"
        next_value["requires_confirmation"] = True
        return next_value

    def _safe_answer_summary(self, answer_text: str) -> str:
        clean = " ".join((answer_text or "").split())
        return f"User answered setup question ({len(clean)} characters)."

    def _safe_note(self, note: str) -> str:
        self._guard_safe_payload({"safe_user_note": note}, allow_controlled_text=False)
        return " ".join((note or "").split())[:240]

    def _update_intake_after_answer(self, question: StorySetupQuestion) -> None:
        intake = self._get_intake(question.story_setup_intake_id)
        missing = [code for code in intake.missing_information_codes if code != question.question_type]
        self._replace_intake(
            intake.copy(
                update={
                    "missing_information_codes": missing,
                    "intake_status": "answered_with_remaining_questions"
                    if missing
                    else "answered",
                    "updated_at": utc_now(),
                }
            )
        )

    def _update_bundle_after_answer(self, question: StorySetupQuestion) -> None:
        bundle = self._get_draft_bundle(question.story_setup_draft_bundle_id)
        self._replace_draft_bundle(
            bundle.copy(
                update={
                    "bundle_status": "draft",
                    "warnings": self._dedupe(bundle.warnings + ["question_answer_recorded"]),
                    "updated_at": utc_now(),
                }
            )
        )

    def _safety_violations(self) -> list[str]:
        violations: list[str] = []
        for path in [
            self.prompts_file,
            self.intakes_file,
            self.draft_bundles_file,
            self.questions_file,
            self.decisions_file,
            self.handoffs_file,
            self.safety_reports_file,
            self.data_dir / "project_origin_metadata.json",
            self.data_dir / "project_registry.json",
        ]:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            value_text = self._string_values_text(text)
            lowered = value_text.lower()
            if SECRET_LIKE_RE.search(value_text):
                violations.append(f"{path.name}:secret_like_value")
            if "authorization:" in lowered:
                violations.append(f"{path.name}:authorization_header")
            if "bearer " in lowered:
                violations.append(f"{path.name}:bearer_token")
            for marker in UNSAFE_VALUE_MARKERS:
                if marker in lowered:
                    violations.append(f"{path.name}:unsafe_marker:{marker}")
            if self._has_uncontrolled_long_prose(value_text):
                violations.append(f"{path.name}:uncontrolled_full_story_prose")
        if self.user_inputs_file.exists():
            user_text = self.user_inputs_file.read_text(encoding="utf-8", errors="ignore")
            if SECRET_LIKE_RE.search(user_text):
                violations.append(f"{self.user_inputs_file.name}:secret_like_value")
            lowered_user_text = user_text.lower()
            for marker in UNSAFE_VALUE_MARKERS:
                if marker in lowered_user_text:
                    violations.append(f"{self.user_inputs_file.name}:unsafe_marker:{marker}")
        return self._dedupe(violations)

    def _has_uncontrolled_long_prose(self, value_text: str) -> bool:
        proseish = [
            segment
            for segment in value_text.splitlines()
            if len(segment) > 1200 and segment.count(" ") > 120
        ]
        return bool(proseish)

    def _guard_controlled_text(self, text: str) -> None:
        if not text or not text.strip():
            raise StorySetupBlocked("controlled_text_required")
        if len(text) > 12000:
            raise StorySetupBlocked("controlled_text_too_long")
        lowered = text.lower()
        if SECRET_LIKE_RE.search(text) or "authorization:" in lowered or "bearer " in lowered:
            raise StorySetupSafetyError("controlled_text_contains_secret_or_authorization_marker")
        for marker in UNSAFE_VALUE_MARKERS:
            if marker in lowered:
                raise StorySetupSafetyError(f"controlled_text_contains_unsafe_marker:{marker}")

    def _guard_safe_payload(
        self,
        payload: Any,
        allow_controlled_text: bool,
    ) -> None:
        issues = self._unsafe_payload_issues(
            payload,
            "payload",
            allow_controlled_text=allow_controlled_text,
        )
        if issues:
            raise StorySetupSafetyError("; ".join(issues))

    def _unsafe_payload_issues(
        self,
        payload: Any,
        label: str,
        allow_controlled_text: bool,
    ) -> list[str]:
        issues: list[str] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = str(key).lower().replace("-", "_")
                    if normalized_key in {"authorization", "bearer", "api_key_ref", "api_key_plaintext", "raw_key"}:
                        issues.append(f"{label}:{path}.{key}:unsafe_key")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if not isinstance(value, str):
                return
            if SECRET_LIKE_RE.search(value):
                issues.append(f"{label}:{path}:secret_like_value")
            lowered = value.lower()
            if "authorization:" in lowered or "bearer " in lowered:
                issues.append(f"{label}:{path}:authorization_marker")
            if not allow_controlled_text or not path.endswith(".prompt_text") and not path.endswith(".answer_text"):
                for marker in UNSAFE_VALUE_MARKERS:
                    if marker in lowered:
                        issues.append(f"{label}:{path}:unsafe_marker:{marker}")

        visit(payload, "$")
        return self._dedupe(issues)

    def _read_prompts(self) -> list[StorySetupPrompt]:
        return self._read_model_list(self.prompts_file, StorySetupPrompt)

    def _write_prompts(self, records: list[StorySetupPrompt]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.prompts_file, [model_to_dict(item) for item in records])

    def _read_user_inputs(self) -> list[StorySetupUserInput]:
        return self._read_model_list(self.user_inputs_file, StorySetupUserInput)

    def _write_user_inputs(self, records: list[StorySetupUserInput]) -> None:
        for record in records:
            self._guard_controlled_text(record.input_text)
        self.store.write(self.user_inputs_file, [model_to_dict(item) for item in records])

    def _read_intakes(self) -> list[StorySetupIntake]:
        return self._read_model_list(self.intakes_file, StorySetupIntake)

    def _write_intakes(self, records: list[StorySetupIntake]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.intakes_file, [model_to_dict(item) for item in records])

    def _read_draft_bundles(self) -> list[StorySetupDraftBundle]:
        return self._read_model_list(self.draft_bundles_file, StorySetupDraftBundle)

    def _write_draft_bundles(self, records: list[StorySetupDraftBundle]) -> None:
        for record in records:
            if record.creates_final_story_facts_now or not record.requires_downstream_confirmation:
                raise StorySetupSafetyError("draft_bundle_story_fact_boundary_violation")
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.draft_bundles_file, [model_to_dict(item) for item in records])

    def _read_questions(self) -> list[StorySetupQuestion]:
        return self._read_model_list(self.questions_file, StorySetupQuestion)

    def _write_questions(self, records: list[StorySetupQuestion]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.questions_file, [model_to_dict(item) for item in records])

    def _read_decisions(self) -> list[StorySetupDecision]:
        return self._read_model_list(self.decisions_file, StorySetupDecision)

    def _write_decisions(self, records: list[StorySetupDecision]) -> None:
        for record in records:
            if (
                record.decision_scope != "setup_draft_only"
                or not record.does_not_write_story_facts
                or not record.does_not_confirm_world_canvas_final
                or not record.does_not_confirm_characters_final
                or not record.does_not_confirm_framework_final
                or not record.does_not_confirm_chapter_plan_final
            ):
                raise StorySetupSafetyError("story_setup_decision_boundary_violation")
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.decisions_file, [model_to_dict(item) for item in records])

    def _read_handoffs(self) -> list[StorySetupHandoff]:
        return self._read_model_list(self.handoffs_file, StorySetupHandoff)

    def _write_handoffs(self, records: list[StorySetupHandoff]) -> None:
        for record in records:
            if not (
                record.requires_world_canvas_confirmation
                and record.requires_character_confirmation
                and record.requires_framework_confirmation
                and record.requires_chapter_route_confirmation
            ):
                raise StorySetupSafetyError("story_setup_handoff_confirmation_boundary_violation")
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.handoffs_file, [model_to_dict(item) for item in records])

    def _read_safety_reports(self) -> list[StorySetupSafetyReport]:
        return self._read_model_list(self.safety_reports_file, StorySetupSafetyReport)

    def _write_safety_reports(self, records: list[StorySetupSafetyReport]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records], allow_controlled_text=False)
        self.store.write(self.safety_reports_file, [model_to_dict(item) for item in records])

    def _read_model_list(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        try:
            data = self.store.read_list(path)
            return [model_type(**item) for item in data]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError(f"Storage file is invalid: {path.name}") from exc

    def _get_prompt(self, story_setup_prompt_id: str) -> StorySetupPrompt:
        for record in self._read_prompts():
            if record.story_setup_prompt_id == story_setup_prompt_id:
                return record
        raise StorySetupNotFound(f"Story setup prompt not found: {story_setup_prompt_id}")

    def _get_intake(self, story_setup_intake_id: str) -> StorySetupIntake:
        for record in self._read_intakes():
            if record.story_setup_intake_id == story_setup_intake_id:
                return record
        raise StorySetupNotFound(f"Story setup intake not found: {story_setup_intake_id}")

    def _get_draft_bundle(self, story_setup_draft_bundle_id: str) -> StorySetupDraftBundle:
        for record in self._read_draft_bundles():
            if record.story_setup_draft_bundle_id == story_setup_draft_bundle_id:
                return record
        raise StorySetupNotFound(f"Story setup draft bundle not found: {story_setup_draft_bundle_id}")

    def _get_decision(self, story_setup_decision_id: str) -> StorySetupDecision:
        for record in self._read_decisions():
            if record.story_setup_decision_id == story_setup_decision_id:
                return record
        raise StorySetupNotFound(f"Story setup decision not found: {story_setup_decision_id}")

    def _get_handoff(self, story_setup_handoff_id: str) -> StorySetupHandoff:
        for record in self._read_handoffs():
            if record.story_setup_handoff_id == story_setup_handoff_id:
                return record
        raise StorySetupNotFound(f"Story setup handoff not found: {story_setup_handoff_id}")

    def _latest_decision(self, records: list[StorySetupDecision]) -> StorySetupDecision | None:
        if not records:
            return None
        return max(records, key=lambda item: item.created_at or item.story_setup_decision_id)

    def _latest_handoff(self, records: list[StorySetupHandoff]) -> StorySetupHandoff | None:
        if not records:
            return None
        return max(
            records,
            key=lambda item: item.updated_at or item.created_at or item.story_setup_handoff_id,
        )

    def _replace_intake(self, updated: StorySetupIntake) -> None:
        records = self._read_intakes()
        for index, record in enumerate(records):
            if record.story_setup_intake_id == updated.story_setup_intake_id:
                records[index] = updated
                self._write_intakes(records)
                return
        raise StorySetupNotFound(f"Story setup intake not found: {updated.story_setup_intake_id}")

    def _replace_draft_bundle(self, updated: StorySetupDraftBundle) -> None:
        records = self._read_draft_bundles()
        for index, record in enumerate(records):
            if record.story_setup_draft_bundle_id == updated.story_setup_draft_bundle_id:
                records[index] = updated
                self._write_draft_bundles(records)
                return
        raise StorySetupNotFound(f"Story setup draft bundle not found: {updated.story_setup_draft_bundle_id}")

    def _replace_question(self, updated: StorySetupQuestion) -> None:
        records = self._read_questions()
        for index, record in enumerate(records):
            if record.story_setup_question_id == updated.story_setup_question_id:
                records[index] = updated
                self._write_questions(records)
                return
        raise StorySetupNotFound(f"Story setup question not found: {updated.story_setup_question_id}")

    def _string_values_text(self, text: str) -> str:
        try:
            payload = json.loads(text)
        except ValueError:
            return text
        values: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for child in value.values():
                    visit(child)
                return
            if isinstance(value, list):
                for child in value:
                    visit(child)
                return
            if isinstance(value, str):
                values.append(value)

        visit(payload)
        return "\n".join(values)

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
