from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.agents.chapter_agent import ChapterAgent
from app.backend.core.config import settings
from app.backend.core.story_capacity import (
    CHAPTER_COUNT_MAX,
    CHAPTER_COUNT_MIN,
    DEFAULT_SCENE_COUNT,
    SCENE_COUNT_MAX,
    SCENE_COUNT_MIN,
    chapter_count_range_label,
    clamp_scene_count,
    scene_count_range_label,
)
from app.backend.models.chapter import Chapter
from app.backend.models.chapter_plan import (
    CDRoleFunctionNeed,
    ChapterPlanDraft,
    ChapterPlanFoundationStatus,
    ChapterPlanRemovedSupportingRoleReference,
    ChapterPlanRepairSupportingRoleReferencesResponse,
    ChapterPlanValidationReport,
    ChapterPlanWorkflowResponse,
    ChapterRouteItem,
    ChapterSceneBeat,
    CurrentChapterBrief,
)
from app.backend.models.character import Character
from app.backend.models.decision import Decision
from app.backend.models.framework_package import (
    ChapterFramework,
    ChapterMacroAssignment,
    FrameworkPackage,
)
from app.backend.models.relationship import Relationship
from app.backend.models.world_canvas import WorldCanvas
from app.backend.repositories import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.framework_package_service import FrameworkPackageService
from app.backend.services.generator_framework_context_service import (
    GeneratorFrameworkContextService,
    SCHEMA_VERSION as GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_VERSION,
)
from app.backend.services.model_gateway_service import ModelGatewayService, ModelJsonParseError
from app.backend.services.chapter_role_input_builder_service import (
    ChapterRoleInputBuilderService,
)
from app.backend.services.character_prompt_fidelity_service import (
    compact_json_text,
    premise_required_terms,
    project_requires_story_premise,
    require_project_story_premise_for_generation,
    try_read_project_story_premise,
)
from app.backend.services.project_story_premise_service import FORBIDDEN_DEMO_DEFAULTS
from app.backend.services.tracing_service import traceable_operation
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
CHAPTER_PLAN_VERSION_ID = "version_chapter_plan_m6_001"
ALLOWED_MAIN_CAST_STEPS = {
    "characters_confirmed",
    "chapter_plan_draft",
    "chapter_plan_confirmed",
    "scene_generation",
    "scene_1_confirmed",
    "scene_1_revised",
    "scene_2_confirmed",
    "scene_2_revised",
    "scene_3_confirmed",
    "scene_3_revised",
    "scene_4_confirmed",
    "scene_4_revised",
    "scene_5_confirmed",
    "scene_5_revised",
    "chapter_in_progress",
    "chapter_archived",
    "next_chapter_preparation",
    "next_chapter_active",
}
SCENE_PROGRESS_STEP_RE = re.compile(
    r"^scene_\d+_(confirmed|revised|temporary_confirmed|continuity_recheck)$"
)
SHANGHAI_TZ = timezone(timedelta(hours=8))
CHAPTER_PLAN_PROJECT_STORY_PREMISE_MISSING = "chapter_plan_project_story_premise_missing"
CHAPTER_PLAN_PROMPT_FIDELITY_MISSING = "chapter_plan_prompt_fidelity_missing"
CHAPTER_PLAN_PROMPT_FIDELITY_WEAK = "chapter_plan_prompt_fidelity_weak"
GENERATOR_FRAMEWORK_CONTEXT_FILE = "generator_framework_context.json"
CHAPTER_PLAN_DEMO_DEFAULT_LEAK = "chapter_plan_demo_default_leak"
CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR = "chapter_plan_framework_contract_error"
CHAPTER_PLAN_FRAMEWORK_FALLBACK_UNACKNOWLEDGED = "chapter_plan_framework_fallback_unacknowledged"
CHAPTER_MEMORY_PACK_MISSING = "chapter_memory_pack_missing"
CHAPTER_MEMORY_PACK_CREATED_MINIMAL = "chapter_memory_pack_created_minimal"
MODEL_FALLBACK_USED = "model_fallback_used"

SCENE_BEAT_PHASES_BY_COUNT: dict[int, list[str]] = {
    1: ["single_scene_turn"],
    2: ["chapter_entry", "chapter_exit_hook"],
    3: ["chapter_entry", "investigation_or_test", "chapter_exit_hook"],
    4: ["chapter_entry", "first_pressure", "midpoint_turn", "chapter_exit_hook"],
    5: [
        "chapter_entry",
        "first_pressure",
        "midpoint_turn",
        "consequence_or_cost",
        "chapter_exit_hook",
    ],
}

SCENE_BEAT_LONG_PHASE_SEQUENCE = [
    "chapter_entry",
    "orientation_reframe",
    "first_pressure",
    "evidence_gain",
    "constraint_discovery",
    "relationship_or_choice_turn",
    "false_lead",
    "tactical_attempt",
    "external_pressure",
    "setback",
    "midpoint_turn",
    "reversal_setup",
    "cost_visibility",
    "countermove",
    "relationship_pressure",
    "consequence_or_cost",
    "integration",
    "last_complication",
    "exit_decision",
    "chapter_exit_hook",
]

SCENE_BEAT_PHASE_LIBRARY: dict[str, dict[str, Any]] = {
    "chapter_entry": {
        "scene_function": "Establish the current chapter direction and first actionable pressure.",
        "new_information": "Name the first practical question or evidence gap the chapter must pursue.",
        "character_state_delta": "Move at least one A/B participant from intention into committed involvement.",
        "conflict_turn": "Introduce the chapter pressure without resolving the central chapter problem.",
        "cost_or_risk_delta": "Clarify what may become harder if the opening pressure is ignored.",
        "ending_hook_requirement": "End with a concrete next pressure, question, or decision point.",
    },
    "first_pressure": {
        "scene_function": "Apply the first clear test against the chapter direction.",
        "new_information": "Add a new constraint, contradiction, or operational limit to the chapter question.",
        "character_state_delta": "Shift at least one A/B participant's confidence, leverage, or obligation.",
        "conflict_turn": "Turn the opening intention into active resistance or complication.",
        "cost_or_risk_delta": "Show the first visible cost of pursuing the chapter problem.",
        "ending_hook_requirement": "End by making the next test more specific than the current one.",
    },
    "orientation_reframe": {
        "scene_function": "Reframe the chapter direction through a concrete local condition.",
        "new_information": "Add context that changes how the opening pressure should be interpreted.",
        "character_state_delta": "Make one participant adjust expectation, suspicion, or tactical posture.",
        "conflict_turn": "Shift the chapter problem from general pressure into a clearer local shape.",
        "cost_or_risk_delta": "Clarify a risk created by misunderstanding the local condition.",
        "ending_hook_requirement": "End with the reframed condition forcing a new practical move.",
    },
    "evidence_gain": {
        "scene_function": "Gain one usable piece of evidence without solving the chapter problem.",
        "new_information": "Provide evidence that narrows the question while opening another uncertainty.",
        "character_state_delta": "Change how at least one participant weighs trust, urgency, or risk.",
        "conflict_turn": "Turn passive investigation into an evidence-driven complication.",
        "cost_or_risk_delta": "Attach a cost to using or revealing the gained evidence.",
        "ending_hook_requirement": "End with the evidence pointing toward a harder verification step.",
    },
    "constraint_discovery": {
        "scene_function": "Discover a rule, resource, time, or social constraint that limits progress.",
        "new_information": "Add a constraint that was not visible in prior scenes.",
        "character_state_delta": "Force a participant to abandon, narrow, or defend a tactic.",
        "conflict_turn": "Convert the chapter pressure into a constrained choice space.",
        "cost_or_risk_delta": "Make the constraint create a specific tradeoff for future action.",
        "ending_hook_requirement": "End with the constraint requiring a new route rather than repetition.",
    },
    "false_lead": {
        "scene_function": "Follow a plausible lead that changes direction without becoming filler.",
        "new_information": "Reveal why the lead is incomplete, misleading, or only partially useful.",
        "character_state_delta": "Expose a participant's bias, impatience, doubt, or hidden priority.",
        "conflict_turn": "Turn apparent progress into a sharper interpretive problem.",
        "cost_or_risk_delta": "Show what is spent, risked, or exposed by chasing the lead.",
        "ending_hook_requirement": "End with a corrected question or a more dangerous lead.",
    },
    "tactical_attempt": {
        "scene_function": "Let characters attempt a concrete tactic under current constraints.",
        "new_information": "Show what the tactic proves, fails to prove, or accidentally reveals.",
        "character_state_delta": "Make success or failure alter confidence, alliance, or obligation.",
        "conflict_turn": "Transform planning into action with a visible partial result.",
        "cost_or_risk_delta": "Create a consequence that follows from the tactic itself.",
        "ending_hook_requirement": "End with the tactic causing a changed operational problem.",
    },
    "external_pressure": {
        "scene_function": "Introduce pressure from an outside force, institution, crowd, rival, or deadline.",
        "new_information": "Add external context that changes the cost of the chapter goal.",
        "character_state_delta": "Force a participant to respond to pressure they do not fully control.",
        "conflict_turn": "Move the conflict from internal pursuit to contested external pressure.",
        "cost_or_risk_delta": "Make delay, exposure, or resistance more costly than before.",
        "ending_hook_requirement": "End with external pressure narrowing the next available action.",
    },
    "setback": {
        "scene_function": "Deliver a setback that invalidates an assumption without resetting progress.",
        "new_information": "Reveal which prior assumption, method, or alliance is unreliable.",
        "character_state_delta": "Leave a participant with doubt, guilt, anger, or a revised priority.",
        "conflict_turn": "Convert progress into a problem that must be reworked, not repeated.",
        "cost_or_risk_delta": "Make the setback impose a new debt, loss, exposure, or deadline.",
        "ending_hook_requirement": "End with the setback demanding a different response.",
    },
    "reversal_setup": {
        "scene_function": "Prepare a reversal by aligning evidence, pressure, and character stakes.",
        "new_information": "Add a clue or pressure that can later turn the chapter interpretation.",
        "character_state_delta": "Position a participant near a decision, realization, or moral strain.",
        "conflict_turn": "Tighten the conflict so the current approach is about to become insufficient.",
        "cost_or_risk_delta": "Signal what may break if the coming turn is mishandled.",
        "ending_hook_requirement": "End with the setup pointing to a possible reversal.",
    },
    "cost_visibility": {
        "scene_function": "Make the emotional, social, material, or knowledge cost visible.",
        "new_information": "Show what the chapter pursuit is costing beyond the immediate objective.",
        "character_state_delta": "Force a participant to acknowledge, deny, or redistribute the cost.",
        "conflict_turn": "Turn cost into a pressure that affects the next choice.",
        "cost_or_risk_delta": "Add a distinct cost that must carry into later scenes.",
        "ending_hook_requirement": "End with the cost creating a new obligation or hesitation.",
    },
    "countermove": {
        "scene_function": "Let an opposing force, environment, or hidden agenda make a countermove.",
        "new_information": "Reveal how resistance adapts to the characters' recent progress.",
        "character_state_delta": "Make at least one participant reassess leverage, safety, or trust.",
        "conflict_turn": "Turn the chapter conflict from pursuit into active contest.",
        "cost_or_risk_delta": "Raise the cost of continuing with the same plan.",
        "ending_hook_requirement": "End with the countermove forcing adaptation.",
    },
    "relationship_pressure": {
        "scene_function": "Put relationship pressure in direct contact with the chapter objective.",
        "new_information": "Reveal motive, trust, resentment, dependency, or conflicting loyalty.",
        "character_state_delta": "Change a participant's relational stance or emotional commitment.",
        "conflict_turn": "Make relationship pressure alter the route through the chapter problem.",
        "cost_or_risk_delta": "Create a personal cost attached to pursuing the objective.",
        "ending_hook_requirement": "End with relationship pressure complicating the next move.",
    },
    "integration": {
        "scene_function": "Integrate prior evidence, cost, and character pressure into a new working view.",
        "new_information": "Combine earlier information into a clearer but still incomplete interpretation.",
        "character_state_delta": "Make a participant commit to a revised understanding or tactic.",
        "conflict_turn": "Turn scattered progress into a focused next-stage problem.",
        "cost_or_risk_delta": "Clarify which unresolved risk now matters most.",
        "ending_hook_requirement": "End with the integrated view requiring a decisive test.",
    },
    "last_complication": {
        "scene_function": "Add the last major complication before the chapter exit movement.",
        "new_information": "Introduce a late complication that changes timing, leverage, or certainty.",
        "character_state_delta": "Force a participant to act under less certainty than they want.",
        "conflict_turn": "Prevent the chapter from resolving too cleanly before the exit hook.",
        "cost_or_risk_delta": "Make the final push carry a distinct risk.",
        "ending_hook_requirement": "End with the complication requiring an exit decision.",
    },
    "exit_decision": {
        "scene_function": "Make a decision that converts chapter consequences into forward momentum.",
        "new_information": "Clarify what the characters now believe, know, or choose to risk.",
        "character_state_delta": "Lock in a changed intention, burden, or relational stance for later retrieval.",
        "conflict_turn": "Move from chapter problem handling into next movement commitment.",
        "cost_or_risk_delta": "Name the cost or risk that follows the decision forward.",
        "ending_hook_requirement": "End with the decision pointing to the chapter exit hook.",
    },
    "investigation_or_test": {
        "scene_function": "Test the chapter question through a focused inquiry, attempt, or encounter.",
        "new_information": "Add a different piece of usable information than the previous beat.",
        "character_state_delta": "Force at least one A/B participant to revise a tactic, trust boundary, or priority.",
        "conflict_turn": "Convert uncertainty into a narrower problem that still cannot be solved yet.",
        "cost_or_risk_delta": "Expose a new risk attached to the information gained in this scene.",
        "ending_hook_requirement": "End with a result that changes what the following scene must handle.",
    },
    "midpoint_turn": {
        "scene_function": "Turn the chapter problem so the prior approach is no longer sufficient.",
        "new_information": "Reveal a structural change in the chapter problem, not a final answer.",
        "character_state_delta": "Make at least one A/B participant accept, resist, or reinterpret the turn.",
        "conflict_turn": "Escalate or redirect the chapter conflict into a new tactical shape.",
        "cost_or_risk_delta": "Attach a sharper consequence to continuing after the turn.",
        "ending_hook_requirement": "End with the changed problem pointing to a harder next move.",
    },
    "consequence_or_cost": {
        "scene_function": "Make the cost of the chapter's progress visible and actionable.",
        "new_information": "Add consequence information that changes the meaning of earlier progress.",
        "character_state_delta": "Leave at least one A/B participant with a changed burden, doubt, or responsibility.",
        "conflict_turn": "Translate prior progress into a new obstacle, debt, or exposure.",
        "cost_or_risk_delta": "State a distinct cost or risk that was not present in the previous beat.",
        "ending_hook_requirement": "End with an unresolved cost, pressure, or tradeoff that must be carried forward.",
    },
    "relationship_or_choice_turn": {
        "scene_function": "Force a relationship, trust, or choice turn inside the chapter pressure.",
        "new_information": "Add information about alignment, motive, trust, or consequence.",
        "character_state_delta": "Change a participant's relationship stance, choice pressure, or self-understanding.",
        "conflict_turn": "Move the conflict through a decision point rather than a factual discovery.",
        "cost_or_risk_delta": "Create a personal or relational risk attached to the choice.",
        "ending_hook_requirement": "End with the choice creating a next-scene obligation or uncertainty.",
    },
    "chapter_exit_hook": {
        "scene_function": "Convert chapter progress into an exit hook for the next story movement.",
        "new_information": "Add final chapter-level orientation without locking a future chapter solution.",
        "character_state_delta": "Leave at least one A/B participant changed enough to alter the next chapter approach.",
        "conflict_turn": "Close the current chapter movement while opening the next pressure.",
        "cost_or_risk_delta": "Carry forward a cost, risk, or unresolved implication from the chapter.",
        "ending_hook_requirement": "End with a forward hook that does not prescribe exact future prose or action order.",
    },
    "single_scene_turn": {
        "scene_function": "Compress chapter entry, turn, consequence, and hook into one scene responsibility.",
        "new_information": "Add one decisive chapter-level information movement without over-specifying its content.",
        "character_state_delta": "Move at least one A/B participant through intention, pressure, and response.",
        "conflict_turn": "Give the single scene a clear turn rather than a static summary.",
        "cost_or_risk_delta": "Clarify one cost or risk that follows from the scene's turn.",
        "ending_hook_requirement": "End with a forward pressure, question, or consequence.",
    },
}

GENERIC_SCENE_BEAT_MARKERS = {
    "advance chapter goal through scene",
    "this scene must add one new actionable information delta beyond prior confirmed scenes",
    "at least one active participant must leave with changed pressure choice relationship or knowledge boundary",
    "the conflict must advance turn test or increase pressure instead of restating the previous scene",
    "this scene should clarify a new cost risk constraint or tradeoff created by progress",
    "end with a new question choice danger evidence or consequence for the next scene",
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def copy_model(model: BaseModel, **updates: Any):
    if hasattr(model, "model_copy"):
        return model.model_copy(update=updates, deep=True)
    return model.copy(update=updates, deep=True)


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def is_allowed_foundation_step(step: str) -> bool:
    return step in ALLOWED_MAIN_CAST_STEPS or bool(
        SCENE_PROGRESS_STEP_RE.match(step or "")
    )


class ChapterPlanService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        agent: ChapterAgent | None = None,
        model_gateway: ModelGatewayService | None = None,
        framework_service: FrameworkPackageService | None = None,
        chapter_role_input_builder: ChapterRoleInputBuilderService | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.project_file = self.data_dir / "project.json"
        self.story_bible_file = self.data_dir / "story_bible.json"
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.characters_file = self.data_dir / "characters.json"
        self.relationships_file = self.data_dir / "relationships.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.chapters_file = self.data_dir / "chapters.json"
        self.framework_package_file = self.data_dir / "framework_package.json"
        self.chapter_plan_draft_file = self.data_dir / "chapter_plan_draft.json"
        self.generator_framework_context_file = (
            self.data_dir / GENERATOR_FRAMEWORK_CONTEXT_FILE
        )
        self.chapter_framework_build_contexts_file = (
            self.data_dir / "chapter_framework_build_contexts.json"
        )
        self.chapter_framework_build_reasons_file = (
            self.data_dir / "chapter_framework_build_reasons.json"
        )
        self.model_gateway = model_gateway or ModelGatewayService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_service = framework_service or FrameworkPackageService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.chapter_role_input_builder = (
            chapter_role_input_builder
            or ChapterRoleInputBuilderService(
                store=self.store,
                data_dir=self.data_dir,
                repositories=self.repositories,
            )
        )
        self.agent = agent or ChapterAgent(model_gateway=self.model_gateway)

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_plan(self) -> ChapterPlanWorkflowResponse:
        draft = self._try_read_chapter_plan_draft()
        if draft:
            validation = self.validate_chapter_plan_draft(draft)
            draft = copy_model(draft, validation_report=validation)
        else:
            validation = None
        framework = draft.current_chapter_framework if draft else None
        return ChapterPlanWorkflowResponse(
            draft=draft,
            chapters=self._read_chapters_if_present(),
            current_chapter_framework=framework,
            validation=validation,
            foundation=self.check_foundation_ready(),
        )

    @traceable_operation("ChapterPlanService.generate_chapter_plan", tags=["chapter_plan"])
    def generate_chapter_plan(
        self,
        story_goal: str,
        chapter_count: int,
        current_chapter_index: int = 1,
        framework_composition_id: str = "",
    ) -> ChapterPlanWorkflowResponse:
        clean_goal = story_goal.strip()
        if not clean_goal:
            raise StorageError("story_goal must not be empty.")
        self._validate_chapter_count(chapter_count)
        active_progress_chapter_index = self._active_story_progress_chapter_index()
        if 1 <= active_progress_chapter_index <= chapter_count:
            current_chapter_index = active_progress_chapter_index
        if current_chapter_index < 1 or current_chapter_index > chapter_count:
            raise StorageError(
                "CURRENT_CHAPTER_INDEX_INVALID: current_chapter_index must be within chapter_count."
            )
        foundation = self.check_foundation_ready()
        self._raise_if_foundation_not_ready(foundation)

        world_canvas = self.load_confirmed_world_canvas()
        role_inputs = self.chapter_role_input_builder.build_chapter_role_inputs(
            project_id=self._current_project_id(),
        )
        if not role_inputs.main_cast:
            raise StorageError(
                "FOUNDATION_NOT_READY: At least one confirmed A-tier character is required."
            )
        characters = [*role_inputs.main_cast, *role_inputs.supporting_roles]
        relationships = self.load_confirmed_relationships()
        framework_package = self.load_and_validate_framework_package()
        macro_assignments = self._assignments_for_count(
            framework_package,
            chapter_count,
        )
        current_chapter_framework = self.read_current_chapter_framework(
            current_chapter_index=current_chapter_index,
        )
        generator_framework_context = self.load_generator_framework_context(
            framework_composition_id
        )
        project_id = self._current_project_id()
        project_story_premise = require_project_story_premise_for_generation(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            missing_code=CHAPTER_PLAN_PROJECT_STORY_PREMISE_MISSING,
            project_file=self.project_file,
        )

        cd_role_function_policy = self._cd_role_function_policy(role_inputs)
        try:
            agent_data = self.agent.generate_chapter_plan(
                world_canvas=world_canvas,
                confirmed_main_cast=role_inputs.main_cast,
                confirmed_supporting_roles=role_inputs.supporting_roles,
                cd_role_function_policy=cd_role_function_policy,
                confirmed_relationships=relationships,
                framework_package=framework_package,
                macro_assignments=macro_assignments,
                current_chapter_framework=current_chapter_framework,
                generator_framework_context=generator_framework_context,
                project_story_premise=project_story_premise,
                story_goal=clean_goal,
                chapter_count=chapter_count,
                current_chapter_index=current_chapter_index,
            )
        except ModelJsonParseError:
            agent_data = self._fallback_agent_data_after_json_failure(
                story_goal=clean_goal,
                chapter_count=chapter_count,
                current_chapter_index=current_chapter_index,
                main_cast=role_inputs.main_cast,
                supporting_roles=role_inputs.supporting_roles,
                cd_role_function_policy=cd_role_function_policy,
                macro_assignments=macro_assignments,
                framework_package=framework_package,
                current_chapter_framework=current_chapter_framework,
                project_story_premise=project_story_premise,
            )
        draft = self._build_draft_from_agent_data(
            data=agent_data,
            story_goal=clean_goal,
            chapter_count=chapter_count,
            current_chapter_index=current_chapter_index,
            world_canvas=world_canvas,
            characters=characters,
            relationships=relationships,
            framework_package=framework_package,
            macro_assignments=macro_assignments,
            current_chapter_framework=current_chapter_framework,
            generator_framework_context=generator_framework_context,
            latest_user_prompt=clean_goal,
            existing_draft=None,
        )
        self.save_chapter_plan_draft(draft)
        self._update_project_step("chapter_plan_draft", "chapter_plan_draft")
        return ChapterPlanWorkflowResponse(
            draft=draft,
            chapters=self._read_chapters_if_present(),
            current_chapter_framework=draft.current_chapter_framework,
            validation=draft.validation_report,
            foundation=self.check_foundation_ready(),
        )

    @traceable_operation("ChapterPlanService.revise_chapter_plan", tags=["chapter_plan"])
    def revise_chapter_plan(self, revision_prompt: str) -> ChapterPlanWorkflowResponse:
        clean_prompt = revision_prompt.strip()
        if not clean_prompt:
            raise StorageError("revision_prompt must not be empty.")
        current_draft = self._read_chapter_plan_draft()
        foundation = self.check_foundation_ready()
        self._raise_if_foundation_not_ready(foundation)

        world_canvas = self.load_confirmed_world_canvas()
        role_inputs = self.chapter_role_input_builder.build_chapter_role_inputs(
            project_id=self._current_project_id(),
        )
        if not role_inputs.main_cast:
            raise StorageError(
                "FOUNDATION_NOT_READY: At least one confirmed A-tier character is required."
            )
        characters = [*role_inputs.main_cast, *role_inputs.supporting_roles]
        relationships = self.load_confirmed_relationships()
        framework_package = self.load_and_validate_framework_package()
        current_chapter_framework = self._chapter_framework_from_draft(current_draft)
        generator_framework_context = self.load_generator_framework_context(
            current_draft.framework_composition_id
        )
        project_id = self._current_project_id()
        project_story_premise = require_project_story_premise_for_generation(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            missing_code=CHAPTER_PLAN_PROJECT_STORY_PREMISE_MISSING,
            project_file=self.project_file,
        )

        cd_role_function_policy = self._cd_role_function_policy(role_inputs)
        try:
            agent_data = self.agent.revise_chapter_plan(
                current_draft=current_draft,
                world_canvas=world_canvas,
                confirmed_main_cast=role_inputs.main_cast,
                confirmed_supporting_roles=role_inputs.supporting_roles,
                cd_role_function_policy=cd_role_function_policy,
                confirmed_relationships=relationships,
                framework_package=framework_package,
                current_chapter_framework=current_chapter_framework,
                generator_framework_context=generator_framework_context,
                project_story_premise=project_story_premise,
                revision_prompt=clean_prompt,
            )
        except ModelJsonParseError:
            agent_data = self._fallback_agent_data_after_json_failure(
                story_goal=current_draft.story_goal,
                chapter_count=current_draft.chapter_count,
                current_chapter_index=current_draft.current_chapter_index,
                main_cast=role_inputs.main_cast,
                supporting_roles=role_inputs.supporting_roles,
                cd_role_function_policy=cd_role_function_policy,
                macro_assignments=self._assignments_for_count(
                    framework_package,
                    current_draft.chapter_count,
                ),
                framework_package=framework_package,
                current_chapter_framework=current_chapter_framework,
                project_story_premise=project_story_premise,
            )
        macro_assignments = self._assignments_for_count(
            framework_package,
            current_draft.chapter_count,
        )
        draft = self._build_draft_from_agent_data(
            data=agent_data,
            story_goal=current_draft.story_goal,
            chapter_count=current_draft.chapter_count,
            current_chapter_index=current_draft.current_chapter_index,
            world_canvas=world_canvas,
            characters=characters,
            relationships=relationships,
            framework_package=framework_package,
            macro_assignments=macro_assignments,
            current_chapter_framework=current_chapter_framework,
            generator_framework_context=generator_framework_context,
            latest_user_prompt=clean_prompt,
            existing_draft=current_draft,
        )
        self.save_chapter_plan_draft(draft)
        self._update_project_step("chapter_plan_draft", "chapter_plan_draft")
        return ChapterPlanWorkflowResponse(
            draft=draft,
            chapters=self._read_chapters_if_present(),
            current_chapter_framework=draft.current_chapter_framework,
            validation=draft.validation_report,
            foundation=self.check_foundation_ready(),
        )

    def set_scene_count(
        self,
        chapter_index: int,
        scene_count: int,
    ) -> ChapterPlanWorkflowResponse:
        if scene_count < SCENE_COUNT_MIN or scene_count > SCENE_COUNT_MAX:
            raise StorageError(
                f"SCENE_COUNT_INVALID: scene_count must be between {scene_count_range_label()}."
            )
        draft = self._read_chapter_plan_draft()
        if chapter_index < 1 or chapter_index > draft.chapter_count:
            raise StorageError(
                "SCENE_COUNT_INVALID: chapter_index must be within chapter_count."
            )
        if chapter_index != draft.current_chapter_index:
            route_found = False
            updated_routes: list[ChapterRouteItem] = []
            for route in draft.chapter_routes:
                if route.chapter_index == chapter_index:
                    route_found = True
                    updated_routes.append(
                        copy_model(route, planned_scene_count=scene_count)
                    )
                else:
                    updated_routes.append(route)
            if not route_found:
                raise StorageError(
                    "SCENE_COUNT_INVALID: chapter_index must match an existing chapter route."
                )
            updated_draft = copy_model(
                draft,
                chapter_routes=updated_routes,
                updated_at=now_iso(),
            )
            validation = self.validate_chapter_plan_draft(updated_draft)
            updated_draft = copy_model(updated_draft, validation_report=validation)
            self.save_chapter_plan_draft(updated_draft)
            return ChapterPlanWorkflowResponse(
                draft=updated_draft,
                chapters=self._read_chapters_if_present(),
                current_chapter_framework=updated_draft.current_chapter_framework,
                validation=validation,
                foundation=self.check_foundation_ready(),
            )
        resized_beats = self.resize_chapter_scene_beats(
            draft.current_chapter_brief.chapter_scene_beats,
            chapter_id=self._chapter_id(chapter_index),
            scene_count=scene_count,
            chapter_goal=draft.current_chapter_brief.chapter_goal,
            summary_for_scene_generation=draft.current_chapter_brief.summary_for_scene_generation,
        )
        brief = copy_model(
            draft.current_chapter_brief,
            user_selected_scene_count=scene_count,
            chapter_scene_beats=resized_beats,
        )
        updated_draft = copy_model(
            draft,
            current_chapter_brief=brief,
            updated_at=now_iso(),
        )
        validation = self.validate_chapter_plan_draft(updated_draft)
        updated_draft = copy_model(updated_draft, validation_report=validation)
        self.save_chapter_plan_draft(updated_draft)
        return ChapterPlanWorkflowResponse(
            draft=updated_draft,
            chapters=self._read_chapters_if_present(),
            current_chapter_framework=updated_draft.current_chapter_framework,
            validation=validation,
            foundation=self.check_foundation_ready(),
        )

    def repair_supporting_role_references(
        self,
    ) -> ChapterPlanRepairSupportingRoleReferencesResponse:
        draft = self._read_chapter_plan_draft()
        if draft.status == "confirmed":
            raise StorageError(
                "CHAPTER_PLAN_ALREADY_CONFIRMED: Current chapter plan draft has already been confirmed."
            )
        stale_before = self._chapter_plan_character_refs_stale(draft)
        repaired_draft, removed = self._normalize_chapter_plan_role_references(
            draft,
            update_source_refs=True,
        )
        validation = self.validate_chapter_plan_draft(repaired_draft)
        repaired_draft = copy_model(
            repaired_draft,
            validation_report=validation,
            updated_at=now_iso(),
        )
        self.save_chapter_plan_draft(repaired_draft)
        return ChapterPlanRepairSupportingRoleReferencesResponse(
            success=True,
            draft=repaired_draft,
            validation_report=validation,
            removed_references=removed,
            remaining_valid_supporting_role_ids=self._valid_supporting_role_ids(),
            stale_reason_cleared=stale_before
            and not self._chapter_plan_character_refs_stale(repaired_draft),
            foundation=self.check_foundation_ready(),
        )

    @traceable_operation("ChapterPlanService.confirm_chapter_plan", tags=["chapter_plan"])
    def confirm_chapter_plan(
        self,
        user_input: str | None = None,
    ) -> ChapterPlanWorkflowResponse:
        draft = self._read_chapter_plan_draft()
        if draft.status == "confirmed":
            raise StorageError(
                "CHAPTER_PLAN_ALREADY_CONFIRMED: Current chapter plan draft has already been confirmed."
            )
        validation = self.validate_chapter_plan_draft(draft)
        if validation.blocking_issues:
            raise StorageError(
                "CHAPTER_PLAN_BLOCKING_ISSUES: Cannot confirm chapter plan while blocking validation issues exist."
            )
        chapters = self.save_confirmed_chapters(draft)
        current_framework = self.save_confirmed_current_chapter_framework(
            draft=draft,
            current_chapter_id=chapters[draft.current_chapter_index - 1].chapter_id,
        )
        decision = self.write_decision(
            target_id=draft.draft_id,
            user_input=user_input
            or "User confirmed lightweight chapter route, current chapter brief, and current chapter scene count.",
        )
        self.update_project_step("chapter_plan_confirmed", "chapter_plan_confirmed")

        confirmed_draft = copy_model(
            draft,
            status="confirmed",
            current_chapter_framework=self._chapter_framework_payload_with_generator_context(
                current_framework,
                self.load_generator_framework_context(draft.framework_composition_id),
            ),
            validation_report=validation,
            updated_at=now_iso(),
        )
        self.save_chapter_plan_draft(confirmed_draft)
        return ChapterPlanWorkflowResponse(
            draft=confirmed_draft,
            chapters=chapters,
            current_chapter_framework=confirmed_draft.current_chapter_framework,
            validation=validation,
            foundation=self.check_foundation_ready(),
            decision=decision,
        )

    def check_foundation_ready(self) -> ChapterPlanFoundationStatus:
        issues: list[str] = []
        model_status = self.model_gateway.validate_model_config()
        active_model_configured = model_status.configured
        if not active_model_configured:
            issues.append("Active model is not configured.")

        world_canvas_confirmed = False
        try:
            world_canvas = self._read_world_canvas()
            world_canvas_confirmed = world_canvas.status == "confirmed"
        except StorageError:
            world_canvas = None
        if not world_canvas_confirmed:
            issues.append("WorldCanvas.status must be confirmed.")

        confirmed_characters = self._read_confirmed_a_characters_if_present()
        confirmed_a_character_count = len(confirmed_characters)
        if confirmed_a_character_count < 1:
            issues.append("At least one confirmed A-tier character is required.")

        project_step_ready = False
        if self.store.exists(self.project_file):
            project = self.store.read(self.project_file)
            project_step = str(project.get("current_step") or "")
            project_status = str(project.get("status") or "")
            project_step_ready = (
                is_allowed_foundation_step(project_step)
                or is_allowed_foundation_step(project_status)
            )
        if not project_step_ready:
            issues.append(
                "Project.current_step/status must be characters_confirmed or a chapter plan state."
            )

        main_cast_decision_exists = any(
            decision.get("decision_type") == "confirm"
            and decision.get("target_type") == "main_cast"
            for decision in self._read_decision_dicts()
        )
        if not main_cast_decision_exists:
            issues.append("Decision(target_type=main_cast) is required.")
        main_cast_finished = project_step_ready and main_cast_decision_exists

        framework_package_ready = False
        if self.store.exists(self.framework_package_file):
            validation = self.framework_service.validate_framework_package()
            framework_package_ready = validation.valid
            issues.extend(validation.issues)
        else:
            issues.append("Framework package is missing.")

        return ChapterPlanFoundationStatus(
            ready=len(issues) == 0,
            active_model_configured=active_model_configured,
            world_canvas_confirmed=world_canvas_confirmed,
            confirmed_a_character_count=confirmed_a_character_count,
            project_step_ready=project_step_ready,
            main_cast_decision_exists=main_cast_decision_exists,
            main_cast_finished=main_cast_finished,
            framework_package_ready=framework_package_ready,
            issues=issues,
        )

    def load_confirmed_world_canvas(self) -> WorldCanvas:
        world_canvas = self._read_world_canvas()
        if world_canvas.status != "confirmed":
            raise StorageError(
                "FOUNDATION_NOT_READY: WorldCanvas.status must be confirmed."
            )
        return world_canvas

    def load_confirmed_main_cast(self) -> list[Character]:
        characters = self._read_confirmed_a_characters_if_present()
        if not characters:
            raise StorageError(
                "FOUNDATION_NOT_READY: At least one confirmed A-tier character is required."
            )
        return characters

    def _cd_role_function_policy(self, role_inputs) -> dict[str, Any]:
        return {
            "scene_only_role_counts": dict(role_inputs.scene_only_role_counts),
            "cd_function_need_seed_hints": list(role_inputs.cd_function_need_seed_hints),
            "rules": [
                "C/D roles are chapter function needs only.",
                "Do not output concrete C/D character ids in chapter-level participants.",
                "Do not include C/D profile, memory, psychology, or relationship graph details.",
                "SceneAgent resolves these function needs later.",
            ],
            "allowed_function_types": [
                "local_witness",
                "guard_or_gatekeeper",
                "crowd_reaction",
                "temporary_guide",
                "minor_opponent",
                "messenger",
                "shopkeeper",
                "driver",
                "servant",
                "patrol",
                "background_resident",
                "case_informant",
                "other",
            ],
        }

    def load_confirmed_relationships(self) -> list[Relationship]:
        return [
            relationship
            for relationship in self._read_relationships()
            if relationship.status == "confirmed"
        ]

    def load_and_validate_framework_package(self) -> FrameworkPackage:
        if not self.store.exists(self.framework_package_file):
            raise StorageError("FOUNDATION_NOT_READY: Framework package is missing.")
        validation = self.framework_service.validate_framework_package()
        if not validation.valid:
            raise StorageError(
                "FOUNDATION_NOT_READY: Framework package validation failed: "
                + "; ".join(validation.issues)
            )
        return self.framework_service.get_framework_package()

    def assign_macro_components(
        self,
        chapter_count: int,
    ) -> list[ChapterMacroAssignment]:
        response = self.framework_service.assign_macro_components(chapter_count)
        return response.assignments

    def build_current_chapter_framework_draft(
        self,
        current_chapter_index: int,
        story_goal: str,
    ) -> ChapterFramework:
        return self.read_current_chapter_framework(current_chapter_index)

    def read_current_chapter_framework(
        self,
        current_chapter_index: int,
    ) -> ChapterFramework:
        framework_package = self.load_and_validate_framework_package()
        for framework in framework_package.built_chapter_frameworks:
            if framework.chapter_index == current_chapter_index:
                self._ensure_framework_has_build_audit(framework)
                return framework
        raise StorageError(
            "CURRENT_CHAPTER_FRAMEWORK_REQUIRED: Build current chapter framework before generating a chapter plan."
        )

    def validate_chapter_plan_draft(
        self,
        draft: ChapterPlanDraft,
    ) -> ChapterPlanValidationReport:
        warnings: list[str] = []
        blocking_issues: list[str] = []
        user_confirmation_needed = list(draft.user_confirmation_needed)

        if draft.project_id != self._current_project_id():
            blocking_issues.append("ChapterPlanDraft.project_id must match current project.")
        if draft.status not in {"draft", "confirmed"}:
            blocking_issues.append("ChapterPlanDraft.status must be draft or confirmed.")
        if draft.chapter_count < CHAPTER_COUNT_MIN or draft.chapter_count > CHAPTER_COUNT_MAX:
            blocking_issues.append(
                f"chapter_count must be between {chapter_count_range_label()}."
            )
        if len(draft.chapter_routes) != draft.chapter_count:
            blocking_issues.append("chapter_routes length must match chapter_count.")

        world_canvas = self._try_read_world_canvas_for_validation(blocking_issues)
        characters_by_tier = self._read_confirmed_characters_by_tier()
        main_cast_characters = characters_by_tier["A"]
        supporting_role_characters = characters_by_tier["B"]
        characters = [*main_cast_characters, *supporting_role_characters]
        relationships = self.load_confirmed_relationships()
        framework_package = self._try_read_framework_package_for_validation(
            blocking_issues
        )
        valid_main_cast_ids = {character.character_id for character in main_cast_characters}
        valid_supporting_role_ids = {
            character.character_id for character in supporting_role_characters
        }
        valid_character_ids = valid_main_cast_ids | valid_supporting_role_ids
        characters_by_id = {
            character.character_id: character for character in self._read_characters()
        }
        scene_only_ids = {
            character.character_id
            for character in [*characters_by_tier["C"], *characters_by_tier["D"]]
        }
        valid_relationship_ids = {
            relationship.relationship_id for relationship in relationships
        }

        if draft.source_character_ids and set(draft.source_character_ids) != valid_character_ids:
            warnings.append("characters_changed_after_chapter_plan_generation")
            blocking_issues.append(
                "characters_changed_after_chapter_plan_generation: confirmed A/B character set changed after chapter plan generation; run Auto-fix supporting role references or regenerate before confirmation."
            )
        if draft.source_relationship_ids and not set(draft.source_relationship_ids) <= valid_relationship_ids:
            blocking_issues.append("source_relationship_ids must point to confirmed relationships.")

        macro_ids: set[str] = set()
        assignment_map: dict[int, ChapterMacroAssignment] = {}
        if framework_package:
            macro_ids = {
                component.component_id
                for component in framework_package.macro_framework.components
            }
            assignment_map = {
                assignment.chapter_index: assignment
                for assignment in framework_package.chapter_macro_assignments
            }
            if len(assignment_map) != draft.chapter_count:
                blocking_issues.append(
                    "chapter_macro_assignments must align with chapter_count."
                )

        route_indexes = [route.chapter_index for route in draft.chapter_routes]
        if sorted(route_indexes) != list(range(1, draft.chapter_count + 1)):
            blocking_issues.append("chapter_routes must cover chapter indexes 1..chapter_count.")

        for route_index, route in enumerate(draft.chapter_routes):
            if not route.temporary_title:
                blocking_issues.append("Each chapter route must have a temporary title.")
            if not route.linked_macro_component_ids:
                blocking_issues.append("Each chapter route must have a macro component.")
            if not route.macro_component_label:
                blocking_issues.append("Each chapter route must have a macro component label.")
            if not route.light_route_summary:
                blocking_issues.append("Each chapter route must have a light route summary.")
            if not route.narrative_function:
                blocking_issues.append("Each chapter route must have a narrative function.")
            if macro_ids and not set(route.linked_macro_component_ids) <= macro_ids:
                blocking_issues.append("Chapter route macro components must come from framework package.")
            assignment = assignment_map.get(route.chapter_index)
            if assignment and route.linked_macro_component_ids != assignment.linked_macro_component_ids:
                warnings.append("Chapter route macro components differ from assigned macro components.")
            if route.chapter_index != draft.current_chapter_index and route.detail_level != "light":
                blocking_issues.append("Future chapter routes must stay light.")
            if route.expected_focus_character_ids and not set(route.expected_focus_character_ids) <= valid_main_cast_ids:
                blocking_issues.append("Chapter route expected_focus_character_ids must point to confirmed A-tier main cast characters.")
            for character_id in route.expected_supporting_role_ids:
                if character_id not in valid_supporting_role_ids:
                    blocking_issues.append(
                        self._invalid_supporting_role_message(
                            field_path=f"chapter_routes[{route_index}].expected_supporting_role_ids",
                            character_id=character_id,
                            characters_by_id=characters_by_id,
                            valid_supporting_role_ids=valid_supporting_role_ids,
                        )
                    )
            for need in route.cd_role_function_need_hints:
                self._validate_cd_role_function_need(
                    need=need,
                    scene_only_ids=scene_only_ids,
                    recommended_scene_count=None,
                    blocking_issues=blocking_issues,
                    field_name="ChapterRouteItem.cd_role_function_need_hints",
                )
            if route.planned_scene_count is not None and (
                route.planned_scene_count < SCENE_COUNT_MIN
                or route.planned_scene_count > SCENE_COUNT_MAX
            ):
                blocking_issues.append(
                    f"ChapterRouteItem.planned_scene_count must be between {scene_count_range_label()}."
                )

        brief = draft.current_chapter_brief
        if brief.chapter_index != draft.current_chapter_index:
            blocking_issues.append("CurrentChapterBrief.chapter_index must match current_chapter_index.")
        if not brief.title:
            blocking_issues.append("CurrentChapterBrief.title must not be empty.")
        if not brief.chapter_goal:
            blocking_issues.append("CurrentChapterBrief.chapter_goal must not be empty.")
        if not brief.reader_emotion_goal:
            blocking_issues.append("CurrentChapterBrief.reader_emotion_goal must not be empty.")
        if not brief.participating_character_ids:
            blocking_issues.append("CurrentChapterBrief.participating_character_ids must not be empty.")
        else:
            participating_set = set(brief.participating_character_ids)
            if participating_set & scene_only_ids:
                blocking_issues.append("C/D concrete character ids are not allowed in chapter-level participating_character_ids; use cd_role_function_needs instead.")
            if not participating_set <= valid_character_ids:
                blocking_issues.append("CurrentChapterBrief.participating_character_ids must point to confirmed A/B chapter-level explicit characters.")
            if not participating_set & valid_main_cast_ids:
                blocking_issues.append("CurrentChapterBrief.participating_character_ids must include at least one confirmed A-tier main cast character.")
        if not brief.main_cast_character_ids:
            blocking_issues.append("CurrentChapterBrief.main_cast_character_ids must not be empty.")
        elif not set(brief.main_cast_character_ids) <= valid_main_cast_ids:
            blocking_issues.append("CurrentChapterBrief.main_cast_character_ids must point to confirmed A-tier main cast characters.")
        for character_id in brief.supporting_role_ids:
            if character_id not in valid_supporting_role_ids:
                blocking_issues.append(
                    self._invalid_supporting_role_message(
                        field_path="current_chapter_brief.supporting_role_ids",
                        character_id=character_id,
                        characters_by_id=characters_by_id,
                        valid_supporting_role_ids=valid_supporting_role_ids,
                    )
                )
        if not brief.main_conflict:
            blocking_issues.append("CurrentChapterBrief.main_conflict must not be empty.")
        if not brief.character_desire_or_arc_focus:
            blocking_issues.append("CurrentChapterBrief.character_desire_or_arc_focus must not be empty.")
        if not brief.summary_for_scene_generation:
            blocking_issues.append("CurrentChapterBrief.summary_for_scene_generation must not be empty.")
        if not draft.current_chapter_framework:
            blocking_issues.append("Current chapter framework draft is required.")
        if not draft.current_chapter_framework_id:
            blocking_issues.append("current_chapter_framework_id must not be empty.")
        if brief.chapter_framework_id != draft.current_chapter_framework_id:
            blocking_issues.append("CurrentChapterBrief.chapter_framework_id must match current_chapter_framework_id.")

        for focus in brief.character_desire_or_arc_focus:
            character_id = str(focus.get("character_id") or "")
            if character_id and character_id not in valid_main_cast_ids:
                blocking_issues.append("character_desire_or_arc_focus character_id must point to confirmed A-tier characters.")
            if not focus.get("desire") and not focus.get("arc_focus"):
                blocking_issues.append("Each character desire or arc focus must include desire or arc_focus.")

        recommended_scene_count = self._effective_scene_count(brief)
        self._validate_chapter_scene_beats(
            brief=brief,
            effective_scene_count=recommended_scene_count,
            valid_character_ids=valid_character_ids,
            scene_only_ids=scene_only_ids,
            blocking_issues=blocking_issues,
        )
        for role_ref_index, role_ref in enumerate(brief.supporting_role_refs):
            role_ref_data = self._supporting_role_ref_data(role_ref)
            role_ref_character_id = str(role_ref_data.get("character_id") or "").strip()
            if role_ref_character_id not in valid_supporting_role_ids:
                blocking_issues.append(
                    self._invalid_supporting_role_message(
                        field_path=f"current_chapter_brief.supporting_role_refs[{role_ref_index}].character_id",
                        character_id=role_ref_character_id,
                        characters_by_id=characters_by_id,
                        valid_supporting_role_ids=valid_supporting_role_ids,
                    )
                )
            if str(role_ref_data.get("tier") or "") != "B":
                blocking_issues.append("supporting_role_refs tier must be B.")
            related_main_cast_ids = self._string_list(
                role_ref_data.get("related_main_cast_ids")
            )
            if related_main_cast_ids and not set(related_main_cast_ids) <= valid_main_cast_ids:
                blocking_issues.append("supporting_role_refs related_main_cast_ids must point to confirmed A-tier main cast characters.")
            for scene_index in self._integer_list(role_ref_data.get("expected_scene_indices")):
                if scene_index < 1 or scene_index > recommended_scene_count:
                    blocking_issues.append("supporting_role_refs expected_scene_indices must be within current chapter scene count.")

        for focus_index, focus in enumerate(brief.supporting_role_function_focus):
            character_id = str(focus.get("character_id") or "")
            if character_id and character_id not in valid_supporting_role_ids:
                blocking_issues.append(
                    self._invalid_supporting_role_message(
                        field_path=f"current_chapter_brief.supporting_role_function_focus[{focus_index}].character_id",
                        character_id=character_id,
                        characters_by_id=characters_by_id,
                        valid_supporting_role_ids=valid_supporting_role_ids,
                    )
                )
            if not focus.get("function_focus") and not focus.get("expected_chapter_effect"):
                blocking_issues.append("Each supporting_role_function_focus entry must include function_focus or expected_chapter_effect.")

        for need in brief.cd_role_function_needs:
            self._validate_cd_role_function_need(
                need=need,
                scene_only_ids=scene_only_ids,
                recommended_scene_count=recommended_scene_count,
                blocking_issues=blocking_issues,
                field_name="CurrentChapterBrief.cd_role_function_needs",
            )

        self._validate_current_chapter_framework(
            draft=draft,
            assignment_map=assignment_map,
            blocking_issues=blocking_issues,
        )
        self._validate_framework_build_contract(
            draft=draft,
            framework_package=framework_package,
            blocking_issues=blocking_issues,
            warnings=warnings,
        )
        self._validate_chapter_plan_prompt_fidelity(
            draft=draft,
            blocking_issues=blocking_issues,
            warnings=warnings,
        )
        self._validate_forbidden_knowledge(
            draft=draft,
            characters=characters,
            blocking_issues=blocking_issues,
        )
        self._validate_world_hard_rules(
            draft=draft,
            world_canvas=world_canvas,
            blocking_issues=blocking_issues,
            user_confirmation_needed=user_confirmation_needed,
        )
        self._validate_future_locking(
            draft=draft,
            warnings=warnings,
            user_confirmation_needed=user_confirmation_needed,
        )

        return ChapterPlanValidationReport(
            passed=len(blocking_issues) == 0,
            warnings=self._unique_strings(warnings),
            blocking_issues=self._unique_strings(blocking_issues),
            user_confirmation_needed=self._unique_strings(user_confirmation_needed),
        )

    def save_chapter_plan_draft(self, draft: ChapterPlanDraft) -> None:
        self.store.write(self.chapter_plan_draft_file, model_to_dict(draft))

    def save_confirmed_chapters(self, draft: ChapterPlanDraft) -> list[Chapter]:
        timestamp = now_iso()
        scene_count = (
            draft.current_chapter_brief.user_selected_scene_count
            or draft.current_chapter_brief.recommended_scene_count
            or DEFAULT_SCENE_COUNT
        )
        chapters: list[Chapter] = []
        for route in draft.chapter_routes:
            is_current = route.chapter_index == draft.current_chapter_index
            brief = draft.current_chapter_brief if is_current else None
            route_scene_count = (
                scene_count if brief else route.planned_scene_count or DEFAULT_SCENE_COUNT
            )
            main_cast_ids = brief.main_cast_character_ids if brief else route.expected_focus_character_ids
            supporting_role_ids = (
                brief.supporting_role_ids if brief else route.expected_supporting_role_ids
            )
            participating_ids = self._unique_strings([*main_cast_ids, *supporting_role_ids])
            supporting_role_refs = (
                [model_to_dict(item) for item in brief.supporting_role_refs]
                if brief
                else []
            )
            cd_role_function_needs = (
                [model_to_dict(item) for item in brief.cd_role_function_needs]
                if brief
                else [model_to_dict(item) for item in route.cd_role_function_need_hints]
            )
            chapters.append(
                Chapter(
                    chapter_id=self._chapter_id(route.chapter_index),
                    project_id=self._current_project_id(),
                    chapter_index=route.chapter_index,
                    title=brief.title if brief else route.temporary_title,
                    summary=(
                        brief.summary_for_scene_generation
                        if brief
                        else route.light_route_summary
                    ),
                    goals=[brief.chapter_goal] if brief else [route.narrative_function],
                    participant_character_ids=participating_ids,
                    participating_character_ids=participating_ids,
                    main_cast_character_ids=list(main_cast_ids),
                    supporting_role_ids=list(supporting_role_ids),
                    supporting_role_refs=supporting_role_refs,
                    cd_role_function_needs=cd_role_function_needs,
                    linked_macro_component_ids=route.linked_macro_component_ids,
                    light_route_summary=route.light_route_summary,
                    narrative_function=route.narrative_function,
                    chapter_goal=brief.chapter_goal if brief else "",
                    main_conflict=brief.main_conflict if brief else route.expected_conflict_hint,
                    chapter_framework_id=(
                        draft.current_chapter_framework_id if brief else ""
                    ),
                    scene_count=route_scene_count,
                    scene_ids=[],
                    detail_level="current_chapter_brief" if brief else "light",
                    version_id=CHAPTER_PLAN_VERSION_ID,
                    created_at=timestamp,
                    updated_at=timestamp,
                    status="active" if brief else "planned",
                )
            )
        self.repositories.chapters.write_all(
            [model_to_dict(chapter) for chapter in chapters]
        )
        return chapters

    def save_confirmed_current_chapter_framework(
        self,
        draft: ChapterPlanDraft,
        current_chapter_id: str,
    ) -> ChapterFramework:
        framework_package = self.load_and_validate_framework_package()
        current_framework = self._chapter_framework_from_draft(draft)
        for existing in framework_package.built_chapter_frameworks:
            if existing.chapter_index == current_framework.chapter_index:
                self._ensure_framework_has_build_audit(existing)
                return existing
        raise StorageError(
            "CURRENT_CHAPTER_FRAMEWORK_REQUIRED: Build current chapter framework before confirming a chapter plan."
        )

    def write_decision(self, target_id: str, user_input: str) -> Decision:
        decisions = self._read_decision_dicts()
        decision = Decision(
            decision_id=f"decision_chapter_plan_confirm_{len(decisions) + 1:03d}",
            decision_type="confirm",
            target_type="chapter_plan",
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.store.write(self.decisions_file, decisions)
        return decision

    def update_project_step(self, current_step: str, status: str) -> None:
        self._update_project_step(current_step, status)

    def _fallback_agent_data_after_json_failure(
        self,
        *,
        story_goal: str,
        chapter_count: int,
        current_chapter_index: int,
        main_cast: list[Character],
        supporting_roles: list[Character],
        cd_role_function_policy: dict[str, Any],
        macro_assignments: list[ChapterMacroAssignment],
        framework_package: FrameworkPackage,
        current_chapter_framework: ChapterFramework,
        project_story_premise: Any,
    ) -> dict[str, Any]:
        macro_label_map = {
            component.component_id: component.label
            for component in framework_package.macro_framework.components
        }
        main_cast_ids = [character.character_id for character in main_cast]
        supporting_role_ids = [character.character_id for character in supporting_roles]
        participating_ids = self._unique_strings([*main_cast_ids, *supporting_role_ids])
        premise_evidence = self._premise_evidence_text(project_story_premise)
        current_assignment = next(
            (
                assignment
                for assignment in macro_assignments
                if assignment.chapter_index == current_chapter_index
            ),
            None,
        )
        route_items: list[dict[str, Any]] = []
        for assignment in macro_assignments:
            linked_ids = list(assignment.linked_macro_component_ids)
            macro_label = " / ".join(
                macro_label_map.get(component_id, component_id)
                for component_id in linked_ids
            )
            route_items.append(
                {
                    "chapter_index": assignment.chapter_index,
                    "temporary_title": f"Chapter {assignment.chapter_index}: {macro_label or 'Story phase'}",
                    "linked_macro_component_ids": linked_ids,
                    "macro_component_label": macro_label,
                    "light_route_summary": (
                        f"Controlled fallback route for chapter {assignment.chapter_index}. "
                        f"Preserve ProjectStoryPremise evidence: {premise_evidence}."
                    ),
                    "narrative_function": (
                        f"Establish the chapter function around {premise_evidence}."
                        if assignment.chapter_index == 1
                        else f"Advance {premise_evidence} without locking future scenes."
                    ),
                    "expected_focus_character_ids": main_cast_ids[:2] or main_cast_ids,
                    "expected_supporting_role_ids": supporting_role_ids[:2],
                    "cd_role_function_need_hints": [
                        self._fallback_cd_function_need(
                            need_id=f"fallback_route_{assignment.chapter_index:03d}_cd_need_001",
                            scene_index=None,
                            tier_preference="C_or_D",
                            function_type="case_informant",
                            function_summary="SceneAgent may select a local witness, crowd voice, or gatekeeper if the scene needs grounded evidence.",
                            reason="The chapter route should reserve local texture without binding a concrete C/D character at chapter level.",
                        )
                    ],
                    "expected_conflict_hint": "The cast must pursue evidence while uncertainty and institutional pressure increase.",
                    "detail_level": "light",
                    "future_lock_level": "low",
                }
            )

        linked_current_ids = (
            list(current_assignment.linked_macro_component_ids)
            if current_assignment
            else list(current_chapter_framework.linked_macro_component_ids)
        )
        current_macro_label = " / ".join(
            macro_label_map.get(component_id, component_id)
            for component_id in linked_current_ids
        )
        cd_counts = cd_role_function_policy.get("scene_only_role_counts") or {}
        c_count = int(cd_counts.get("C") or 0)
        d_count = int(cd_counts.get("D") or 0)
        current_cd_needs = [
            self._fallback_cd_function_need(
                need_id=f"fallback_chapter_{current_chapter_index:03d}_cd_need_001",
                scene_index=1,
                tier_preference="C" if c_count else "C_or_D",
                function_type="local_witness",
                function_summary="SceneAgent should select or reuse a local witness when the opening scene needs a concrete clue.",
                reason="C-tier roles belong in scene selection, but the chapter can request a witness function.",
            )
        ]
        if d_count:
            current_cd_needs.append(
                self._fallback_cd_function_need(
                    need_id=f"fallback_chapter_{current_chapter_index:03d}_cd_need_002",
                    scene_index=2,
                    tier_preference="D",
                    function_type="crowd_reaction",
                    function_summary="SceneAgent may reuse a minimal persistent D-tier crowd or dock presence if the location returns.",
                    reason="D-tier roles can persist through memory, but concrete binding is deferred to scene runtime.",
                )
            )

        return {
            "story_goal": story_goal,
            "chapter_routes": route_items[:chapter_count],
            "current_chapter_brief": {
                "chapter_index": current_chapter_index,
                "title": f"Chapter {current_chapter_index}: {current_macro_label or 'Current pressure'}",
                "linked_macro_component_ids": linked_current_ids,
                "chapter_framework_id": current_chapter_framework.chapter_framework_id,
                "chapter_goal": (
                    "Recover from invalid model JSON by producing a conservative, user-confirmable chapter brief "
                    f"that preserves ProjectStoryPremise: {premise_evidence}."
                ),
                "reader_emotion_goal": ["curiosity", "unease"],
                "participating_character_ids": participating_ids,
                "main_cast_character_ids": main_cast_ids,
                "supporting_role_ids": supporting_role_ids,
                "supporting_role_refs": [
                    {
                        "character_id": character_id,
                        "tier": "B",
                        "role_in_chapter": "supporting pressure",
                        "participation_reason": "B-tier role participates at chapter level without becoming main cast.",
                        "related_main_cast_ids": main_cast_ids[:1],
                        "expected_scene_indices": [1],
                        "context_depth": "medium",
                    }
                    for character_id in supporting_role_ids
                ],
                "supporting_role_function_focus": [
                    {
                        "character_id": character_id,
                        "function_focus": "Apply supporting pressure or provide chapter-level leverage.",
                        "expected_chapter_effect": "Helps the scene system decide when this B-tier role should appear.",
                    }
                    for character_id in supporting_role_ids
                ],
                "cd_role_function_needs": current_cd_needs,
                "main_conflict": f"The main cast needs evidence for {premise_evidence} while world boundaries constrain direct action.",
                "character_desire_or_arc_focus": [
                    {
                        "character_id": character.character_id,
                        "desire": character.current_state.active_goal,
                        "arc_focus": character.arc_state.current_arc,
                    }
                    for character in main_cast
                ],
                "world_rules_to_respect": [
                    "Respect confirmed WorldCanvas hard rules.",
                    "Do not resolve the central unknown before the scene system earns it.",
                ],
                "forbidden_moves": [
                    "Do not bind concrete C/D character ids in chapter-level planning.",
                    "Do not overwrite confirmed memory or world facts.",
                    "Do not skip user confirmation for the fallback chapter plan.",
                ],
                "recommended_scene_count": DEFAULT_SCENE_COUNT,
                "summary_for_scene_generation": (
                    f"Use this conservative chapter brief around {premise_evidence} as a recoverable fallback after invalid model JSON. "
                    "Scene writing should create concrete events only after the user confirms the plan."
                ),
            },
            "user_confirmation_needed": [
                "Controlled fallback chapter plan was created because the model returned invalid JSON; user confirmation is required before scene writing."
            ],
        }

    def _fallback_cd_function_need(
        self,
        *,
        need_id: str,
        scene_index: int | None,
        tier_preference: str,
        function_type: str,
        function_summary: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "need_id": need_id,
            "scene_index": scene_index,
            "tier_preference": tier_preference,
            "function_type": function_type,
            "function_summary": function_summary,
            "reason": reason,
            "location_hint": "",
            "relationship_hint": "",
            "knowledge_need": "Only scene-local knowledge required by the confirmed chapter brief.",
            "reuse_existing_preferred": True,
            "must_not_bind_specific_character_id": True,
            "resolved_by_scene_agent": True,
        }

    def _build_draft_from_agent_data(
        self,
        data: dict[str, Any],
        story_goal: str,
        chapter_count: int,
        current_chapter_index: int,
        world_canvas: WorldCanvas,
        characters: list[Character],
        relationships: list[Relationship],
        framework_package: FrameworkPackage,
        macro_assignments: list[ChapterMacroAssignment],
        current_chapter_framework: ChapterFramework,
        generator_framework_context: dict[str, Any] | None,
        latest_user_prompt: str,
        existing_draft: ChapterPlanDraft | None,
    ) -> ChapterPlanDraft:
        timestamp = now_iso()
        plan_data = data.get("draft") or data.get("chapter_plan") or data
        if not isinstance(plan_data, dict):
            raise StorageError("Chapter model output must be a JSON object.")

        assignment_map = {
            assignment.chapter_index: assignment for assignment in macro_assignments
        }
        macro_label_map = {
            component.component_id: component.label
            for component in framework_package.macro_framework.components
        }
        main_cast_characters = [
            character for character in characters if character.tier == "A"
        ]
        supporting_role_characters = [
            character for character in characters if character.tier == "B"
        ]
        valid_main_cast_ids = [
            character.character_id for character in main_cast_characters
        ]
        valid_supporting_role_ids = [
            character.character_id for character in supporting_role_characters
        ]
        valid_character_ids = [*valid_main_cast_ids, *valid_supporting_role_ids]
        default_character_id = valid_main_cast_ids[0] if valid_main_cast_ids else ""
        route_data_list = plan_data.get("chapter_routes") or []
        if not isinstance(route_data_list, list):
            raise StorageError("Chapter model output chapter_routes must be a list.")

        existing_routes_by_index = (
            {route.chapter_index: route for route in existing_draft.chapter_routes}
            if existing_draft
            else {}
        )
        routes: list[ChapterRouteItem] = []
        for chapter_index in range(1, chapter_count + 1):
            raw_route = self._find_route_data(route_data_list, chapter_index)
            existing_route = existing_routes_by_index.get(chapter_index)
            assignment = assignment_map.get(chapter_index)
            linked_ids = (
                list(raw_route.get("linked_macro_component_ids") or [])
                if raw_route
                else []
            )
            if not linked_ids and assignment:
                linked_ids = assignment.linked_macro_component_ids
            macro_label = (
                str(raw_route.get("macro_component_label") or "")
                if raw_route
                else ""
            )
            if not macro_label:
                macro_label = " / ".join(
                    macro_label_map.get(component_id, component_id)
                    for component_id in linked_ids
                )
            focus_ids = self._string_list(
                raw_route.get("expected_focus_character_ids") if raw_route else []
            )
            if not focus_ids and default_character_id:
                focus_ids = [default_character_id]
            expected_supporting_role_ids = self._string_list(
                raw_route.get("expected_supporting_role_ids") if raw_route else []
            )
            expected_supporting_role_ids = self._filter_supporting_role_ids(
                expected_supporting_role_ids,
                set(valid_supporting_role_ids),
            )
            planned_scene_count = self._coerce_optional_scene_count(
                (raw_route or {}).get("planned_scene_count")
            )
            if planned_scene_count is None and existing_route:
                planned_scene_count = existing_route.planned_scene_count
            routes.append(
                ChapterRouteItem(
                    chapter_index=chapter_index,
                    temporary_title=str(
                        (raw_route or {}).get("temporary_title")
                        or f"第 {chapter_index} 章"
                    ),
                    linked_macro_component_ids=linked_ids,
                    macro_component_label=macro_label,
                    light_route_summary=str(
                        (raw_route or {}).get("light_route_summary")
                        or self._fallback_route_summary(chapter_index, macro_label)
                    ),
                    narrative_function=str(
                        (raw_route or {}).get("narrative_function")
                        or self._fallback_narrative_function(chapter_index)
                    ),
                    expected_focus_character_ids=focus_ids,
                    expected_supporting_role_ids=expected_supporting_role_ids,
                    cd_role_function_need_hints=self._normalize_cd_role_function_needs(
                        (raw_route or {}).get("cd_role_function_need_hints"),
                        context=f"chapter_route_{chapter_index}",
                    ),
                    expected_conflict_hint=str(
                        (raw_route or {}).get("expected_conflict_hint") or ""
                    ),
                    planned_scene_count=planned_scene_count,
                    detail_level="light",
                    future_lock_level=str(
                        (raw_route or {}).get("future_lock_level") or "low"
                    ),
                )
            )

        raw_brief = plan_data.get("current_chapter_brief") or {}
        if not isinstance(raw_brief, dict):
            raise StorageError("Chapter model output current_chapter_brief must be an object.")
        current_assignment = assignment_map.get(current_chapter_index)
        current_linked_ids = list(raw_brief.get("linked_macro_component_ids") or [])
        if not current_linked_ids and current_assignment:
            current_linked_ids = current_assignment.linked_macro_component_ids
        valid_main_cast_id_set = set(valid_main_cast_ids)
        valid_supporting_role_id_set = set(valid_supporting_role_ids)
        raw_participating_ids = self._string_list(raw_brief.get("participating_character_ids"))
        main_cast_ids = self._string_list(raw_brief.get("main_cast_character_ids"))
        main_cast_ids = [
            character_id for character_id in main_cast_ids
            if character_id in valid_main_cast_id_set
        ]
        if not main_cast_ids:
            main_cast_ids = [
                character_id
                for character_id in raw_participating_ids
                if character_id in valid_main_cast_id_set
            ]
        if not main_cast_ids and default_character_id:
            main_cast_ids = [default_character_id]
        supporting_role_ids = self._string_list(raw_brief.get("supporting_role_ids"))
        supporting_role_ids = self._filter_supporting_role_ids(
            supporting_role_ids,
            valid_supporting_role_id_set,
        )
        if not supporting_role_ids:
            supporting_role_ids = [
                character_id
                for character_id in raw_participating_ids
                if character_id in valid_supporting_role_id_set
            ]
        participating_ids = self._normalize_chapter_participating_ids(
            raw_participating_ids,
            main_cast_ids=main_cast_ids,
            supporting_role_ids=supporting_role_ids,
            default_main_cast_id=default_character_id,
            valid_main_cast_ids=valid_main_cast_id_set,
            valid_supporting_role_ids=valid_supporting_role_id_set,
        )
        route_for_current = routes[current_chapter_index - 1]
        chapter_goal = str(
            raw_brief.get("chapter_goal")
            or "Build the current chapter's investigation goal, character pressure, and rule boundary."
        )
        summary_for_scene_generation = str(
            raw_brief.get("summary_for_scene_generation")
            or route_for_current.light_route_summary
        )
        recommended_scene_count = self._coerce_scene_count(
            raw_brief.get("recommended_scene_count"),
            default=DEFAULT_SCENE_COUNT,
        )
        raw_user_selected_scene_count = self._coerce_optional_scene_count(
            raw_brief.get("user_selected_scene_count")
        )
        existing_scene_count = (
            existing_draft.current_chapter_brief.user_selected_scene_count
            if existing_draft
            else None
        )
        effective_scene_count = (
            existing_scene_count
            or raw_user_selected_scene_count
            or recommended_scene_count
            or DEFAULT_SCENE_COUNT
        )
        existing_beats = (
            existing_draft.current_chapter_brief.chapter_scene_beats
            if existing_draft
            else None
        )
        chapter_scene_beats = self.normalize_chapter_scene_beats(
            raw_brief.get("chapter_scene_beats"),
            chapter_id=self._chapter_id(current_chapter_index),
            scene_count=effective_scene_count,
            chapter_goal=chapter_goal,
            summary_for_scene_generation=summary_for_scene_generation,
            existing_beats=existing_beats,
        )
        brief = CurrentChapterBrief(
            chapter_index=current_chapter_index,
            title=str(raw_brief.get("title") or route_for_current.temporary_title),
            linked_macro_component_ids=current_linked_ids,
            chapter_framework_id=current_chapter_framework.chapter_framework_id,
            chapter_goal=str(
                raw_brief.get("chapter_goal")
                or "建立当前章节的调查目标、人物压力和世界规则边界。"
            ),
            reader_emotion_goal=list(
                raw_brief.get("reader_emotion_goal") or ["好奇", "不安"]
            ),
            participating_character_ids=participating_ids,
            main_cast_character_ids=main_cast_ids,
            supporting_role_ids=supporting_role_ids,
            supporting_role_refs=self._normalize_supporting_role_refs(
                raw_brief.get("supporting_role_refs"),
                supporting_role_ids=supporting_role_ids,
                main_cast_ids=main_cast_ids,
                valid_supporting_role_ids=valid_supporting_role_id_set,
            ),
            supporting_role_function_focus=self._normalize_supporting_role_function_focus(
                raw_brief.get("supporting_role_function_focus"),
                supporting_role_ids=supporting_role_ids,
                valid_supporting_role_ids=valid_supporting_role_id_set,
            ),
            cd_role_function_needs=self._normalize_cd_role_function_needs(
                raw_brief.get("cd_role_function_needs"),
                context="current_chapter_brief",
            ),
            main_conflict=str(
                raw_brief.get("main_conflict")
                or route_for_current.expected_conflict_hint
                or "主角想接近真相，但世界规则和现有权力结构同时制造阻力。"
            ),
            character_desire_or_arc_focus=self._normalize_character_focus(
                raw_brief.get("character_desire_or_arc_focus"),
                main_cast_characters,
                main_cast_ids,
            ),
            world_rules_to_respect=list(
                raw_brief.get("world_rules_to_respect")
                or [rule.statement for rule in world_canvas.hard_rules[:3]]
            ),
            forbidden_moves=list(
                raw_brief.get("forbidden_moves")
                or [
                    "不要让角色提前知道世界核心未知来源。",
                    "不要无代价逆转已经发生的记忆代价。",
                    "不要锁死未来章节的死亡、背叛、结局或精确揭示。",
                ]
            ),
            recommended_scene_count=recommended_scene_count,
            user_selected_scene_count=raw_user_selected_scene_count,
            chapter_scene_beats=chapter_scene_beats,
            summary_for_scene_generation=summary_for_scene_generation,
        )
        if existing_draft and existing_draft.current_chapter_brief.user_selected_scene_count:
            brief = copy_model(
                brief,
                user_selected_scene_count=existing_draft.current_chapter_brief.user_selected_scene_count,
            )

        framework_context_payload = self._chapter_framework_payload_with_generator_context(
            current_chapter_framework,
            generator_framework_context,
        )
        framework_composition_id = self._framework_composition_id(
            generator_framework_context
        )
        framework_source_refs = self._framework_context_source_refs(
            generator_framework_context
        )
        if framework_composition_id:
            framework_source_refs.insert(
                0,
                f"framework_composition:{framework_composition_id}",
            )

        draft = ChapterPlanDraft(
            draft_id=existing_draft.draft_id if existing_draft else self._next_draft_id(),
            project_id=self._current_project_id(),
            status="draft",
            story_goal=str(plan_data.get("story_goal") or story_goal),
            chapter_count=chapter_count,
            current_chapter_index=current_chapter_index,
            source_world_canvas_id=world_canvas.world_canvas_id,
            source_character_ids=valid_character_ids,
            source_relationship_ids=[
                relationship.relationship_id for relationship in relationships
            ],
            framework_package_id=framework_package.framework_package_id,
            framework_composition_id=framework_composition_id,
            source_refs=self._unique_strings(framework_source_refs),
            chapter_routes=routes,
            current_chapter_brief=brief,
            current_chapter_framework=framework_context_payload,
            current_chapter_framework_id=current_chapter_framework.chapter_framework_id,
            validation_report=ChapterPlanValidationReport(passed=False),
            user_confirmation_needed=list(
                plan_data.get("user_confirmation_needed") or []
            ),
            latest_user_prompt=latest_user_prompt,
            created_at=existing_draft.created_at if existing_draft else timestamp,
            updated_at=timestamp,
        )
        validation = self.validate_chapter_plan_draft(draft)
        return copy_model(draft, validation_report=validation)

    def _normalize_chapter_plan_role_references(
        self,
        draft: ChapterPlanDraft,
        *,
        update_source_refs: bool,
    ) -> tuple[ChapterPlanDraft, list[ChapterPlanRemovedSupportingRoleReference]]:
        valid_main_cast_ids = set(self._valid_main_cast_ids())
        valid_supporting_role_ids = set(self._valid_supporting_role_ids())
        characters_by_id = self._character_map()
        removed: list[ChapterPlanRemovedSupportingRoleReference] = []

        def filter_ids(character_ids: list[str], field_path: str) -> list[str]:
            filtered: list[str] = []
            for character_id in self._unique_strings(character_ids):
                if character_id in valid_supporting_role_ids:
                    filtered.append(character_id)
                    continue
                removed.append(
                    self._removed_supporting_role_ref(
                        field_path=field_path,
                        character_id=character_id,
                        characters_by_id=characters_by_id,
                    )
                )
            return filtered

        routes: list[ChapterRouteItem] = []
        for route_index, route in enumerate(draft.chapter_routes):
            routes.append(
                copy_model(
                    route,
                    expected_supporting_role_ids=filter_ids(
                        list(route.expected_supporting_role_ids),
                        f"chapter_routes[{route_index}].expected_supporting_role_ids",
                    ),
                )
            )

        brief = draft.current_chapter_brief
        supporting_role_ids = filter_ids(
            list(brief.supporting_role_ids),
            "current_chapter_brief.supporting_role_ids",
        )
        participating_ids: list[str] = []
        for character_id in self._unique_strings(list(brief.participating_character_ids)):
            is_valid_main = character_id in valid_main_cast_ids
            is_valid_support = (
                character_id in valid_supporting_role_ids
                and character_id in set(supporting_role_ids)
            )
            if is_valid_main or is_valid_support:
                participating_ids.append(character_id)
                continue
            removed.append(
                self._removed_supporting_role_ref(
                    field_path="current_chapter_brief.participating_character_ids",
                    character_id=character_id,
                    characters_by_id=characters_by_id,
                    reason=(
                        "chapter-level participating_character_ids require confirmed "
                        "A/B explicit characters; concrete C/D characters must stay "
                        "in cd_role_function_needs for SceneAgent resolution"
                    ),
                )
            )
        if not any(character_id in valid_main_cast_ids for character_id in participating_ids):
            fallback_main = next(iter(sorted(valid_main_cast_ids)), "")
            if fallback_main:
                participating_ids.insert(0, fallback_main)

        supporting_role_refs: list[dict[str, Any]] = []
        for role_ref_index, role_ref in enumerate(brief.supporting_role_refs):
            role_ref_data = self._supporting_role_ref_data(role_ref)
            character_id = str(role_ref_data.get("character_id") or "").strip()
            if character_id in valid_supporting_role_ids:
                role_ref_data["character_id"] = character_id
                role_ref_data["tier"] = "B"
                supporting_role_refs.append(role_ref_data)
                continue
            removed.append(
                self._removed_supporting_role_ref(
                    field_path=f"current_chapter_brief.supporting_role_refs[{role_ref_index}].character_id",
                    character_id=character_id,
                    characters_by_id=characters_by_id,
                )
            )

        supporting_role_function_focus: list[dict[str, Any]] = []
        for focus_index, focus in enumerate(brief.supporting_role_function_focus):
            if not isinstance(focus, dict):
                continue
            character_id = str(focus.get("character_id") or "").strip()
            if character_id in valid_supporting_role_ids:
                supporting_role_function_focus.append(dict(focus))
                continue
            removed.append(
                self._removed_supporting_role_ref(
                    field_path=f"current_chapter_brief.supporting_role_function_focus[{focus_index}].character_id",
                    character_id=character_id,
                    characters_by_id=characters_by_id,
                )
            )

        brief_data = self._shallow_model_data(brief)
        brief_data["participating_character_ids"] = self._unique_strings(participating_ids)
        brief_data["supporting_role_ids"] = supporting_role_ids
        brief_data["supporting_role_refs"] = supporting_role_refs
        brief_data["supporting_role_function_focus"] = supporting_role_function_focus
        updated_brief = CurrentChapterBrief(**brief_data)
        draft_data = self._shallow_model_data(draft)
        draft_data["chapter_routes"] = [model_to_dict(route) for route in routes]
        draft_data["current_chapter_brief"] = model_to_dict(updated_brief)
        if update_source_refs:
            draft_data["source_character_ids"] = self._current_chapter_explicit_character_ids()
        return ChapterPlanDraft(**draft_data), removed

    def _removed_supporting_role_ref(
        self,
        *,
        field_path: str,
        character_id: str,
        characters_by_id: dict[str, Character],
        reason: str = "supporting role fields require confirmed B-tier roles",
    ) -> ChapterPlanRemovedSupportingRoleReference:
        character = characters_by_id.get(character_id)
        return ChapterPlanRemovedSupportingRoleReference(
            field_path=field_path,
            character_id=character_id,
            name=character.name if character else "",
            tier=character.tier if character else "missing",
            status=character.status if character else "missing",
            reason=reason,
        )

    def _invalid_supporting_role_message(
        self,
        *,
        field_path: str,
        character_id: str,
        characters_by_id: dict[str, Character],
        valid_supporting_role_ids: set[str],
    ) -> str:
        character = characters_by_id.get(character_id)
        name = character.name if character else "unknown"
        tier = character.tier if character else "missing"
        status = character.status if character else "missing"
        valid_ids = ", ".join(sorted(valid_supporting_role_ids)) or "none"
        return (
            f"Invalid supporting role id at {field_path}: {character_id} "
            f"({name}, tier={tier}, status={status}). "
            "Supporting role fields require confirmed B-tier roles. "
            f"Valid B-tier ids: {valid_ids}."
        )

    def _character_map(self) -> dict[str, Character]:
        return {character.character_id: character for character in self._read_characters()}

    def _valid_supporting_role_ids(self) -> list[str]:
        return [
            character.character_id
            for character in self._read_characters()
            if character.tier == "B" and character.status == "confirmed"
        ]

    def _valid_main_cast_ids(self) -> list[str]:
        return [
            character.character_id
            for character in self._read_characters()
            if character.tier == "A" and character.status == "confirmed"
        ]

    def _normalize_chapter_participating_ids(
        self,
        raw_participating_ids: list[str],
        *,
        main_cast_ids: list[str],
        supporting_role_ids: list[str],
        default_main_cast_id: str,
        valid_main_cast_ids: set[str],
        valid_supporting_role_ids: set[str],
    ) -> list[str]:
        normalized: list[str] = []
        valid_supporting_for_brief = set(supporting_role_ids) & valid_supporting_role_ids
        for character_id in self._unique_strings(raw_participating_ids):
            if character_id in valid_main_cast_ids:
                normalized.append(character_id)
            elif character_id in valid_supporting_for_brief:
                normalized.append(character_id)
        normalized.extend(
            character_id for character_id in main_cast_ids
            if character_id in valid_main_cast_ids
        )
        normalized.extend(
            character_id for character_id in supporting_role_ids
            if character_id in valid_supporting_for_brief
        )
        if not any(character_id in valid_main_cast_ids for character_id in normalized):
            if default_main_cast_id:
                normalized.insert(0, default_main_cast_id)
        return self._unique_strings(normalized)

    def _current_chapter_explicit_character_ids(self) -> list[str]:
        characters_by_tier = self._read_confirmed_characters_by_tier()
        return [
            *[character.character_id for character in characters_by_tier["A"]],
            *[character.character_id for character in characters_by_tier["B"]],
        ]

    def normalize_chapter_scene_beats(
        self,
        raw_beats: Any,
        *,
        chapter_id: str,
        scene_count: int,
        chapter_goal: str,
        summary_for_scene_generation: str,
        existing_beats: Any | None = None,
    ) -> list[ChapterSceneBeat]:
        source_beats = raw_beats if isinstance(raw_beats, list) and raw_beats else existing_beats
        by_index: dict[int, ChapterSceneBeat] = {}
        for item in source_beats or []:
            data = self._scene_beat_data(item)
            if not data:
                continue
            try:
                scene_index = int(data.get("scene_index") or 0)
            except (TypeError, ValueError):
                continue
            if scene_index < 1 or scene_index > scene_count:
                continue
            merged = model_to_dict(
                self.fallback_chapter_scene_beat(
                    scene_index,
                    chapter_id=chapter_id,
                    scene_count=scene_count,
                    chapter_goal=chapter_goal,
                    summary_for_scene_generation=summary_for_scene_generation,
                )
            )
            merged.update(data)
            merged["chapter_id"] = chapter_id
            merged["scene_index"] = scene_index
            merged["scene_count"] = scene_count
            try:
                beat = ChapterSceneBeat(**merged)
            except ValidationError:
                beat = self.fallback_chapter_scene_beat(
                    scene_index,
                    chapter_id=chapter_id,
                    scene_count=scene_count,
                    chapter_goal=chapter_goal,
                    summary_for_scene_generation=summary_for_scene_generation,
                )
            by_index[scene_index] = beat
        normalized = [
            by_index.get(scene_index)
            or self.fallback_chapter_scene_beat(
                scene_index,
                chapter_id=chapter_id,
                scene_count=scene_count,
                chapter_goal=chapter_goal,
                summary_for_scene_generation=summary_for_scene_generation,
            )
            for scene_index in range(1, scene_count + 1)
        ]
        return self.differentiate_chapter_scene_beats(
            normalized,
            brief_context={
                "chapter_id": chapter_id,
                "chapter_goal": chapter_goal,
                "summary_for_scene_generation": summary_for_scene_generation,
            },
            scene_count=scene_count,
        )

    def resize_chapter_scene_beats(
        self,
        existing_beats: Any,
        *,
        chapter_id: str,
        scene_count: int,
        chapter_goal: str,
        summary_for_scene_generation: str,
    ) -> list[ChapterSceneBeat]:
        return self.normalize_chapter_scene_beats(
            existing_beats,
            chapter_id=chapter_id,
            scene_count=scene_count,
            chapter_goal=chapter_goal,
            summary_for_scene_generation=summary_for_scene_generation,
            existing_beats=existing_beats,
        )

    def fallback_chapter_scene_beat(
        self,
        scene_index: int,
        *,
        chapter_id: str,
        scene_count: int,
        chapter_goal: str,
        summary_for_scene_generation: str,
    ) -> ChapterSceneBeat:
        return self.fallback_differentiated_chapter_scene_beat(
            scene_index,
            chapter_id=chapter_id,
            scene_count=scene_count,
            chapter_goal=chapter_goal,
            summary_for_scene_generation=summary_for_scene_generation,
        )

    def fallback_differentiated_chapter_scene_beat(
        self,
        scene_index: int,
        *,
        chapter_id: str,
        scene_count: int,
        chapter_goal: str,
        summary_for_scene_generation: str,
        phase_key: str | None = None,
    ) -> ChapterSceneBeat:
        phase_key = phase_key or self._expected_scene_beat_phase(scene_index, scene_count)
        if phase_key not in SCENE_BEAT_PHASE_LIBRARY:
            phase_key = self._expected_scene_beat_phase(scene_index, scene_count)
        phase = SCENE_BEAT_PHASE_LIBRARY[phase_key]
        return ChapterSceneBeat(
            beat_id=f"{chapter_id}_scene_beat_{scene_index:03d}",
            chapter_id=chapter_id,
            scene_index=scene_index,
            scene_count=scene_count,
            scene_function=str(phase["scene_function"]),
            function_family=phase_key,
            required_progression_delta={
                "new_information": str(phase["new_information"]),
                "character_state_delta": str(phase["character_state_delta"]),
                "conflict_turn": str(phase["conflict_turn"]),
                "cost_or_risk_delta": str(phase["cost_or_risk_delta"]),
            },
            continuity_anchors={
                "carry_forward_threads": self._bounded_structural_threads(
                    chapter_goal,
                    summary_for_scene_generation,
                ),
                "allowed_returning_characters": [],
                "allowed_returning_locations": [],
                "required_memory_refs": [],
            },
            stage_strategy={
                "location_strategy": "open",
                "time_delta": "must_make_time_relation_clear",
                "action_mode": "open",
                "atmosphere_delta": "optional",
            },
            autonomy_space={
                "character_action_freedom": "high",
                "optional_detours_allowed": True,
                "cd_role_slots_open": True,
            },
            avoid_repetition_axes=[
                "scene_function",
                "new_information",
                "conflict_turn",
                "ending_hook",
            ],
            ending_hook_requirement=str(phase["ending_hook_requirement"]),
            source_refs=["chapter_scene_beats_m1_differentiated_fallback"],
        )

    def _fallback_chapter_scene_beat_avoiding_seen(
        self,
        scene_index: int,
        *,
        chapter_id: str,
        scene_count: int,
        chapter_goal: str,
        summary_for_scene_generation: str,
        seen_scene_functions: set[str],
    ) -> ChapterSceneBeat:
        expected_phase = self._expected_scene_beat_phase(scene_index, scene_count)
        phase_candidates = [
            expected_phase,
            *[
                phase_key
                for phase_key in SCENE_BEAT_PHASE_LIBRARY
                if phase_key != expected_phase
            ],
        ]
        for phase_key in phase_candidates:
            beat = self.fallback_differentiated_chapter_scene_beat(
                scene_index,
                chapter_id=chapter_id,
                scene_count=scene_count,
                chapter_goal=chapter_goal,
                summary_for_scene_generation=summary_for_scene_generation,
                phase_key=phase_key,
            )
            if self._normalized_scene_beat_text(beat.scene_function) not in seen_scene_functions:
                return beat
        base = self.fallback_differentiated_chapter_scene_beat(
            scene_index,
            chapter_id=chapter_id,
            scene_count=scene_count,
            chapter_goal=chapter_goal,
            summary_for_scene_generation=summary_for_scene_generation,
            phase_key=expected_phase,
        )
        return copy_model(
            base,
            scene_function=(
                f"{base.scene_function} Scene {scene_index} structural responsibility."
            ),
            source_refs=[
                *self._string_list(base.source_refs),
                "chapter_scene_beats_m1_unique_collision_suffix",
            ],
        )

    def differentiate_chapter_scene_beats(
        self,
        beats: Any,
        *,
        brief_context: dict[str, Any],
        scene_count: int,
    ) -> list[ChapterSceneBeat]:
        chapter_id = str(brief_context.get("chapter_id") or self._chapter_id(1))
        chapter_goal = str(brief_context.get("chapter_goal") or "")
        summary_for_scene_generation = str(
            brief_context.get("summary_for_scene_generation") or ""
        )
        repaired: list[ChapterSceneBeat] = []
        seen_fingerprints: set[str] = set()
        seen_scene_functions: set[str] = set()
        source_by_index: dict[int, ChapterSceneBeat] = {}
        for item in beats or []:
            data = self._scene_beat_data(item)
            if not data:
                continue
            try:
                scene_index = int(data.get("scene_index") or 0)
            except (TypeError, ValueError):
                continue
            if scene_index < 1 or scene_index > scene_count:
                continue
            try:
                source_by_index[scene_index] = ChapterSceneBeat(**data)
            except ValidationError:
                continue

        for scene_index in range(1, scene_count + 1):
            beat = source_by_index.get(scene_index) or self.fallback_differentiated_chapter_scene_beat(
                scene_index,
                chapter_id=chapter_id,
                scene_count=scene_count,
                chapter_goal=chapter_goal,
                summary_for_scene_generation=summary_for_scene_generation,
            )
            beat = copy_model(
                beat,
                beat_id=beat.beat_id or f"{chapter_id}_scene_beat_{scene_index:03d}",
                chapter_id=chapter_id,
                scene_index=scene_index,
                scene_count=scene_count,
            )
            fingerprint = self._scene_beat_fingerprint(beat)
            scene_function_key = self._normalized_scene_beat_text(beat.scene_function)
            previous = repaired[-1] if repaired else None
            if (
                self._fallback_beat_phase_stale(beat, scene_index, scene_count)
                or
                self.is_generic_or_duplicate_scene_beat(beat, previous_beat=previous)
                or scene_function_key in seen_scene_functions
                or fingerprint in seen_fingerprints
            ):
                beat = self._fallback_chapter_scene_beat_avoiding_seen(
                    scene_index,
                    chapter_id=chapter_id,
                    scene_count=scene_count,
                    chapter_goal=chapter_goal,
                    summary_for_scene_generation=summary_for_scene_generation,
                    seen_scene_functions=seen_scene_functions,
                )
                fingerprint = self._scene_beat_fingerprint(beat)
                scene_function_key = self._normalized_scene_beat_text(beat.scene_function)
            repaired.append(beat)
            seen_fingerprints.add(fingerprint)
            if scene_function_key:
                seen_scene_functions.add(scene_function_key)
        return repaired

    def chapter_scene_beat_distinctness_report(
        self,
        beats: Any,
        *,
        scene_count: int,
    ) -> dict[str, Any]:
        normalized: list[ChapterSceneBeat] = []
        for beat in beats or []:
            data = self._scene_beat_data(beat)
            if not data:
                continue
            try:
                normalized.append(ChapterSceneBeat(**data))
            except ValidationError:
                continue
        adjacent_duplicates: list[dict[str, int]] = []
        adjacent_without_delta: list[dict[str, int]] = []
        adjacent_same_hook_without_delta: list[dict[str, int]] = []
        for index in range(1, len(normalized)):
            previous = normalized[index - 1]
            current = normalized[index]
            pair = {"left": index, "right": index + 1}
            if self._normalized_scene_beat_text(previous.scene_function) == self._normalized_scene_beat_text(current.scene_function):
                adjacent_duplicates.append(pair)
            if not self._scene_beats_have_meaningful_delta(previous, current):
                adjacent_without_delta.append(pair)
            if (
                self._normalized_scene_beat_text(previous.ending_hook_requirement)
                == self._normalized_scene_beat_text(current.ending_hook_requirement)
                and not self._scene_beats_have_meaningful_delta(previous, current)
            ):
                adjacent_same_hook_without_delta.append(pair)
        function_values = [
            self._normalized_scene_beat_text(beat.scene_function)
            for beat in normalized
            if self._normalized_scene_beat_text(beat.scene_function)
        ]
        function_positions: dict[str, list[int]] = {}
        for index, value in enumerate(function_values, start=1):
            function_positions.setdefault(value, []).append(index)
        duplicate_scene_functions = [
            {"scene_function": value, "indices": indices}
            for value, indices in function_positions.items()
            if value and len(indices) > 1
        ]
        progression_values = [
            self._progression_fingerprint(beat)
            for beat in normalized
            if self._progression_fingerprint(beat)
        ]
        all_same_function = bool(function_values) and len(set(function_values)) == 1 and len(function_values) == scene_count
        all_same_progression = bool(progression_values) and len(set(progression_values)) == 1 and len(progression_values) == scene_count
        return {
            "passed": not any(
                [
                    adjacent_duplicates,
                    duplicate_scene_functions,
                    adjacent_without_delta,
                    adjacent_same_hook_without_delta,
                    all_same_function,
                    all_same_progression,
                ]
            ),
            "adjacent_duplicate_scene_functions": adjacent_duplicates,
            "duplicate_scene_functions": duplicate_scene_functions,
            "adjacent_without_meaningful_delta": adjacent_without_delta,
            "adjacent_same_hook_without_delta": adjacent_same_hook_without_delta,
            "all_same_scene_function": all_same_function,
            "all_same_progression_delta": all_same_progression,
        }

    def is_generic_or_duplicate_scene_beat(
        self,
        beat: ChapterSceneBeat,
        previous_beat: ChapterSceneBeat | None = None,
    ) -> bool:
        source_refs = set(self._string_list(beat.source_refs))
        if "chapter_scene_beats_m0_fallback" in source_refs:
            return True
        function_text = self._normalized_scene_beat_text(beat.scene_function)
        hook_text = self._normalized_scene_beat_text(beat.ending_hook_requirement)
        progression = self._progression_values(beat)
        progression_values = [
            self._normalized_scene_beat_text(value) for value in progression.values()
        ]
        all_progression_generic = bool(progression_values) and all(
            self._is_generic_scene_beat_text(value) for value in progression_values
        )
        if beat.function_family == "open" and (
            self._is_generic_scene_beat_text(function_text)
            or self._is_generic_scene_beat_text(hook_text)
            or all_progression_generic
        ):
            return True
        if not any(progression_values):
            return True
        if previous_beat and self._scene_beat_fingerprint(beat) == self._scene_beat_fingerprint(previous_beat):
            return True
        if previous_beat and not self._scene_beats_have_meaningful_delta(previous_beat, beat):
            return True
        return False

    def _expected_scene_beat_phase(self, scene_index: int, scene_count: int) -> str:
        phases = self._scene_beat_phases_for_count(scene_count)
        return phases[max(0, min(scene_index - 1, len(phases) - 1))]

    def _scene_beat_phases_for_count(self, scene_count: int) -> list[str]:
        count = self._coerce_scene_count(scene_count, default=DEFAULT_SCENE_COUNT)
        if count in SCENE_BEAT_PHASES_BY_COUNT:
            return list(SCENE_BEAT_PHASES_BY_COUNT[count])
        if count >= len(SCENE_BEAT_LONG_PHASE_SEQUENCE):
            return list(SCENE_BEAT_LONG_PHASE_SEQUENCE[:count])
        if count <= 1:
            return [SCENE_BEAT_LONG_PHASE_SEQUENCE[0]]
        max_source_index = len(SCENE_BEAT_LONG_PHASE_SEQUENCE) - 1
        source_indexes: list[int] = []
        for target_index in range(count):
            raw_index = round(target_index * max_source_index / (count - 1))
            if source_indexes and raw_index <= source_indexes[-1]:
                raw_index = min(max_source_index, source_indexes[-1] + 1)
            source_indexes.append(raw_index)
        if source_indexes[-1] != max_source_index:
            source_indexes[-1] = max_source_index
        return [SCENE_BEAT_LONG_PHASE_SEQUENCE[index] for index in source_indexes]

    def _fallback_beat_phase_stale(
        self,
        beat: ChapterSceneBeat,
        scene_index: int,
        scene_count: int,
    ) -> bool:
        if "chapter_scene_beats_m1_differentiated_fallback" not in set(
            self._string_list(beat.source_refs)
        ):
            return False
        return beat.function_family != self._expected_scene_beat_phase(
            scene_index,
            scene_count,
        )

    def _normalize_chapter_scene_beats_for_draft(
        self,
        draft: ChapterPlanDraft,
    ) -> ChapterPlanDraft:
        brief = draft.current_chapter_brief
        scene_count = self._effective_scene_count(brief)
        beats = self.normalize_chapter_scene_beats(
            brief.chapter_scene_beats,
            chapter_id=self._chapter_id(brief.chapter_index),
            scene_count=scene_count,
            chapter_goal=brief.chapter_goal,
            summary_for_scene_generation=brief.summary_for_scene_generation,
            existing_beats=brief.chapter_scene_beats,
        )
        if [model_to_dict(beat) for beat in beats] == [
            model_to_dict(beat) for beat in brief.chapter_scene_beats
        ]:
            return draft
        return copy_model(
            draft,
            current_chapter_brief=copy_model(
                brief,
                chapter_scene_beats=beats,
            ),
        )

    def _effective_scene_count(self, brief: CurrentChapterBrief) -> int:
        return self._coerce_scene_count(
            brief.user_selected_scene_count or brief.recommended_scene_count or DEFAULT_SCENE_COUNT,
            default=DEFAULT_SCENE_COUNT,
        )

    def _coerce_optional_scene_count(self, raw_value: Any) -> int | None:
        if raw_value is None or raw_value == "":
            return None
        return self._coerce_scene_count(raw_value, default=DEFAULT_SCENE_COUNT)

    def _coerce_scene_count(self, raw_value: Any, *, default: int) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
        return clamp_scene_count(value, default=default)

    def _scene_beat_data(self, beat: Any) -> dict[str, Any]:
        if isinstance(beat, dict):
            return dict(beat)
        if isinstance(beat, BaseModel):
            return model_to_dict(beat)
        return {}

    def _bounded_structural_threads(
        self,
        chapter_goal: str,
        summary_for_scene_generation: str,
    ) -> list[str]:
        refs: list[str] = []
        if str(chapter_goal or "").strip():
            refs.append("chapter_goal")
        if str(summary_for_scene_generation or "").strip():
            refs.append("summary_for_scene_generation")
        return refs

    def _normalized_scene_beat_text(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[_\-]+", " ", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _is_generic_scene_beat_text(self, value: Any) -> bool:
        normalized = self._normalized_scene_beat_text(value)
        if not normalized:
            return True
        return any(marker in normalized for marker in GENERIC_SCENE_BEAT_MARKERS)

    def _progression_values(self, beat: ChapterSceneBeat) -> dict[str, str]:
        data = self._scene_beat_nested_data(beat.required_progression_delta)
        return {
            "new_information": str(data.get("new_information") or ""),
            "character_state_delta": str(data.get("character_state_delta") or ""),
            "conflict_turn": str(data.get("conflict_turn") or ""),
            "cost_or_risk_delta": str(data.get("cost_or_risk_delta") or ""),
        }

    def _progression_fingerprint(self, beat: ChapterSceneBeat) -> str:
        values = self._progression_values(beat)
        return "|".join(
            self._normalized_scene_beat_text(values[field_name])
            for field_name in [
                "new_information",
                "character_state_delta",
                "conflict_turn",
                "cost_or_risk_delta",
            ]
        )

    def _scene_beat_fingerprint(self, beat: ChapterSceneBeat) -> str:
        return "|".join(
            [
                self._normalized_scene_beat_text(beat.scene_function),
                self._normalized_scene_beat_text(beat.function_family),
                self._progression_fingerprint(beat),
                self._normalized_scene_beat_text(beat.ending_hook_requirement),
            ]
        )

    def _scene_beats_have_meaningful_delta(
        self,
        left: ChapterSceneBeat,
        right: ChapterSceneBeat,
    ) -> bool:
        if self._normalized_scene_beat_text(left.function_family) != self._normalized_scene_beat_text(right.function_family):
            return True
        if self._normalized_scene_beat_text(left.ending_hook_requirement) != self._normalized_scene_beat_text(right.ending_hook_requirement):
            return True
        left_values = self._progression_values(left)
        right_values = self._progression_values(right)
        for field_name in [
            "new_information",
            "character_state_delta",
            "conflict_turn",
            "cost_or_risk_delta",
        ]:
            if self._normalized_scene_beat_text(left_values[field_name]) != self._normalized_scene_beat_text(right_values[field_name]):
                return True
        return False

    def _chapter_plan_character_refs_stale(
        self,
        draft: ChapterPlanDraft,
    ) -> bool:
        if not draft.source_character_ids:
            return False
        return set(draft.source_character_ids) != set(
            self._current_chapter_explicit_character_ids()
        )

    def _supporting_role_ref_data(self, role_ref: Any) -> dict[str, Any]:
        if isinstance(role_ref, dict):
            return dict(role_ref)
        if isinstance(role_ref, BaseModel):
            return model_to_dict(role_ref)
        return {}

    def _validate_chapter_scene_beats(
        self,
        *,
        brief: CurrentChapterBrief,
        effective_scene_count: int,
        valid_character_ids: set[str],
        scene_only_ids: set[str],
        blocking_issues: list[str],
    ) -> None:
        beats = list(brief.chapter_scene_beats)
        if len(beats) != effective_scene_count:
            blocking_issues.append(
                "CurrentChapterBrief.chapter_scene_beats length must match current chapter scene count."
            )
        expected_indices = list(range(1, effective_scene_count + 1))
        seen_indices: list[int] = []
        valid_chapter_participant_ids = set(brief.participating_character_ids) & valid_character_ids
        for beat_index, beat in enumerate(beats):
            beat_data = self._scene_beat_data(beat)
            try:
                scene_index = int(beat_data.get("scene_index") or 0)
            except (TypeError, ValueError):
                scene_index = 0
            seen_indices.append(scene_index)
            if scene_index < 1 or scene_index > effective_scene_count:
                blocking_issues.append("chapter_scene_beats scene_index must be within current chapter scene count.")
            if int(beat_data.get("scene_count") or 0) != effective_scene_count:
                blocking_issues.append("chapter_scene_beats scene_count must match current chapter scene count.")
            if not str(beat_data.get("scene_function") or "").strip():
                blocking_issues.append("Each chapter_scene_beat must include non-empty scene_function.")
            if not str(beat_data.get("ending_hook_requirement") or "").strip():
                blocking_issues.append("Each chapter_scene_beat must include non-empty ending_hook_requirement.")
            progression = self._scene_beat_nested_data(
                beat_data.get("required_progression_delta")
            )
            if not any(str(value or "").strip() for value in progression.values()):
                blocking_issues.append("Each chapter_scene_beat must include at least one required_progression_delta field.")
            anchors = self._scene_beat_nested_data(beat_data.get("continuity_anchors"))
            for character_id in self._string_list(anchors.get("allowed_returning_characters")):
                if character_id in scene_only_ids:
                    blocking_issues.append(
                        "chapter_scene_beats continuity_anchors.allowed_returning_characters cannot contain concrete C/D character ids."
                    )
                if character_id not in valid_chapter_participant_ids:
                    blocking_issues.append(
                        "chapter_scene_beats continuity_anchors.allowed_returning_characters must be current chapter A/B participants only."
                    )
            if beat_index >= effective_scene_count:
                blocking_issues.append("chapter_scene_beats has more entries than current chapter scene count.")
        if sorted(seen_indices) != expected_indices:
            blocking_issues.append("chapter_scene_beats scene_index values must be contiguous and 1-based.")
        distinctness = self.chapter_scene_beat_distinctness_report(
            beats,
            scene_count=effective_scene_count,
        )
        if distinctness["adjacent_duplicate_scene_functions"]:
            blocking_issues.append(
                "Adjacent chapter_scene_beats must not repeat the same scene_function."
            )
        if distinctness["duplicate_scene_functions"]:
            blocking_issues.append(
                "chapter_scene_beats scene_function must be unique within the current chapter."
            )
        if distinctness["adjacent_same_hook_without_delta"]:
            blocking_issues.append(
                "Adjacent chapter_scene_beats must not repeat the same ending hook without a different progression delta."
            )
        if distinctness["adjacent_without_meaningful_delta"]:
            blocking_issues.append(
                "Adjacent chapter_scene_beats must differ in at least one progression delta, ending hook, or function_family."
            )
        if distinctness["all_same_scene_function"]:
            blocking_issues.append(
                "All chapter_scene_beats cannot share the same scene_function."
            )
        if distinctness["all_same_progression_delta"]:
            blocking_issues.append(
                "All chapter_scene_beats cannot share the same progression delta."
            )
        for beat in beats:
            beat_data = self._scene_beat_data(beat)
            try:
                beat_model = ChapterSceneBeat(**beat_data)
            except ValidationError:
                continue
            if (
                beat_model.function_family == "open"
                and self.is_generic_or_duplicate_scene_beat(beat_model)
            ):
                blocking_issues.append(
                    "chapter_scene_beats cannot keep generic open fallback beats after generation or revision."
                )

    def _scene_beat_nested_data(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, BaseModel):
            return model_to_dict(value)
        return {}

    def _shallow_model_data(self, model: Any) -> dict[str, Any]:
        if not isinstance(model, BaseModel):
            return dict(model) if isinstance(model, dict) else {}
        field_names = getattr(model, "model_fields", None)
        if field_names is None:
            field_names = getattr(model, "__fields__", {})
        return {field_name: getattr(model, field_name) for field_name in field_names}

    def _string_list(self, raw_value: Any) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        return self._unique_strings(
            [str(item).strip() for item in raw_value if str(item or "").strip()]
        )

    def _integer_list(self, raw_value: Any) -> list[int]:
        if not isinstance(raw_value, list):
            return []
        result: list[int] = []
        for item in raw_value:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result

    def _filter_supporting_role_ids(
        self,
        character_ids: list[str],
        valid_supporting_role_ids: set[str],
    ) -> list[str]:
        return [
            character_id
            for character_id in self._unique_strings(character_ids)
            if character_id in valid_supporting_role_ids
        ]

    def _filter_character_ids(
        self,
        character_ids: list[str],
        valid_character_ids: set[str],
    ) -> list[str]:
        return [
            character_id
            for character_id in self._unique_strings(character_ids)
            if character_id in valid_character_ids
        ]

    def _normalize_supporting_role_refs(
        self,
        raw_refs: Any,
        supporting_role_ids: list[str],
        main_cast_ids: list[str],
        valid_supporting_role_ids: set[str],
    ) -> list[dict[str, Any]]:
        if isinstance(raw_refs, list) and raw_refs:
            normalized: list[dict[str, Any]] = []
            valid_main_cast_ids = set(main_cast_ids)
            for item in raw_refs:
                if not isinstance(item, dict):
                    continue
                character_id = str(item.get("character_id") or "").strip()
                if character_id not in valid_supporting_role_ids:
                    continue
                entry = dict(item)
                entry["character_id"] = character_id
                entry["tier"] = "B"
                entry["related_main_cast_ids"] = self._filter_character_ids(
                    self._string_list(entry.get("related_main_cast_ids")),
                    valid_main_cast_ids,
                )
                normalized.append(entry)
            return normalized
        related_main_cast_ids = main_cast_ids[:1]
        return [
            {
                "character_id": character_id,
                "tier": "B",
                "role_in_chapter": "supporting role",
                "participation_reason": "Supports chapter pressure without becoming main cast.",
                "related_main_cast_ids": related_main_cast_ids,
                "expected_scene_indices": [1],
                "context_depth": "medium",
            }
            for character_id in supporting_role_ids
        ]

    def _normalize_supporting_role_function_focus(
        self,
        raw_focus: Any,
        supporting_role_ids: list[str],
        valid_supporting_role_ids: set[str],
    ) -> list[dict[str, Any]]:
        if isinstance(raw_focus, list) and raw_focus:
            normalized: list[dict[str, Any]] = []
            for item in raw_focus:
                if not isinstance(item, dict):
                    continue
                character_id = str(item.get("character_id") or "").strip()
                if character_id not in valid_supporting_role_ids:
                    continue
                entry = dict(item)
                entry["character_id"] = character_id
                normalized.append(entry)
            return normalized
        return [
            {
                "character_id": character_id,
                "function_focus": "support the chapter conflict",
                "expected_chapter_effect": "adds relationship pressure or concrete evidence pressure",
            }
            for character_id in supporting_role_ids
        ]

    def _normalize_cd_role_function_needs(
        self,
        raw_needs: Any,
        *,
        context: str,
    ) -> list[CDRoleFunctionNeed]:
        if raw_needs in (None, "", []):
            return []
        if not isinstance(raw_needs, list):
            raise StorageError(f"{context}.cd_role_function_needs must be a list.")
        needs: list[CDRoleFunctionNeed] = []
        for index, item in enumerate(raw_needs, start=1):
            if not isinstance(item, dict):
                raise StorageError(f"{context}.cd_role_function_needs[{index}] must be an object.")
            if self._contains_forbidden_cd_binding_key(item):
                raise StorageError(
                    f"{context}.cd_role_function_needs[{index}] must not include concrete character_id, selected_character_id, role_id, or role binding fields."
                )
            try:
                needs.append(CDRoleFunctionNeed(**item))
            except ValidationError as exc:
                raise StorageError(
                    f"{context}.cd_role_function_needs[{index}] schema is invalid."
                ) from exc
        return needs

    def _contains_forbidden_cd_binding_key(self, value: Any) -> bool:
        forbidden_keys = {
            "character_id",
            "selected_character_id",
            "role_id",
            "selected_role_id",
            "concrete_character_id",
        }
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key) in forbidden_keys:
                    return True
                if self._contains_forbidden_cd_binding_key(nested):
                    return True
        if isinstance(value, list):
            return any(self._contains_forbidden_cd_binding_key(item) for item in value)
        return False

    def _normalize_character_focus(
        self,
        raw_focus: Any,
        characters: list[Character],
        participating_ids: list[str],
    ) -> list[dict[str, Any]]:
        if isinstance(raw_focus, list) and raw_focus:
            normalized = []
            valid_ids = {character.character_id for character in characters}
            for item in raw_focus:
                if not isinstance(item, dict):
                    continue
                character_id = str(item.get("character_id") or "")
                if character_id and character_id not in valid_ids:
                    continue
                normalized.append(dict(item))
            if normalized:
                return normalized

        character_map = {character.character_id: character for character in characters}
        result: list[dict[str, Any]] = []
        for character_id in participating_ids:
            character = character_map.get(character_id)
            if character is None:
                continue
            result.append(
                {
                    "character_id": character.character_id,
                    "desire": character.current_state.current_desire
                    or character.current_state.active_goal,
                    "arc_focus": character.arc_state.current_arc
                    or character.arc_state.next_possible_change,
                }
            )
        return result

    def _validate_cd_role_function_need(
        self,
        need: CDRoleFunctionNeed,
        scene_only_ids: set[str],
        recommended_scene_count: int | None,
        blocking_issues: list[str],
        field_name: str,
    ) -> None:
        payload = model_to_dict(need)
        if not need.need_id:
            blocking_issues.append(f"{field_name} need_id is required.")
        if not need.function_type:
            blocking_issues.append(f"{field_name} function_type is required.")
        if not need.function_summary:
            blocking_issues.append(f"{field_name} function_summary is required.")
        if not need.reason:
            blocking_issues.append(f"{field_name} reason is required.")
        if need.scene_index is not None:
            if need.scene_index < 1:
                blocking_issues.append(f"{field_name} scene_index must be positive.")
            if recommended_scene_count is not None and need.scene_index > recommended_scene_count:
                blocking_issues.append(f"{field_name} scene_index must be within current chapter scene count.")
        if need.must_not_bind_specific_character_id is not True:
            blocking_issues.append(f"{field_name} must_not_bind_specific_character_id must be true.")
        if need.resolved_by_scene_agent is not True:
            blocking_issues.append(f"{field_name} resolved_by_scene_agent must be true.")
        if self._contains_forbidden_cd_binding_key(payload):
            blocking_issues.append(f"{field_name} must not contain concrete C/D binding fields.")
        if self._contains_scene_only_character_id(payload, scene_only_ids):
            blocking_issues.append(f"{field_name} must not contain concrete C/D character ids.")

    def _contains_scene_only_character_id(
        self,
        value: Any,
        scene_only_ids: set[str],
    ) -> bool:
        if not scene_only_ids:
            return False
        if isinstance(value, str):
            return any(character_id and character_id in value for character_id in scene_only_ids)
        if isinstance(value, dict):
            return any(
                self._contains_scene_only_character_id(item, scene_only_ids)
                for item in value.values()
            )
        if isinstance(value, list):
            return any(
                self._contains_scene_only_character_id(item, scene_only_ids)
                for item in value
            )
        return False

    def _validate_current_chapter_framework(
        self,
        draft: ChapterPlanDraft,
        assignment_map: dict[int, ChapterMacroAssignment],
        blocking_issues: list[str],
    ) -> None:
        framework_data = draft.current_chapter_framework or {}
        if not isinstance(framework_data, dict):
            blocking_issues.append("current_chapter_framework must be an object.")
            return
        if framework_data.get("chapter_index") != draft.current_chapter_index:
            blocking_issues.append("current_chapter_framework must be built only for the current chapter.")
        if framework_data.get("chapter_framework_id") != draft.current_chapter_framework_id:
            blocking_issues.append("current_chapter_framework_id must match framework draft.")
        assignment = assignment_map.get(draft.current_chapter_index)
        if assignment and framework_data.get("linked_macro_component_ids") != assignment.linked_macro_component_ids:
            blocking_issues.append("current_chapter_framework macro ids must match current assignment.")
        if "future_chapters" in framework_data or "chapter_frameworks" in framework_data:
            blocking_issues.append("current_chapter_framework must not include future chapter frameworks.")

    def _validate_framework_build_contract(
        self,
        draft: ChapterPlanDraft,
        framework_package: FrameworkPackage | None,
        blocking_issues: list[str],
        warnings: list[str],
    ) -> None:
        framework_data = draft.current_chapter_framework or {}
        if not isinstance(framework_data, dict):
            blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR)
            return
        modules = framework_data.get("modules") or []
        if not modules:
            blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR)
        if framework_package:
            module_by_id = {
                module.module_id: module
                for module in framework_package.component_vocabulary.chapter_modules
            }
            for module in modules:
                if not isinstance(module, dict):
                    blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR)
                    continue
                module_id = str(module.get("module_id") or "").strip()
                vocabulary_module = module_by_id.get(module_id)
                if not vocabulary_module:
                    blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR)
                    continue
                allowed_component_ids = {
                    component.component_id
                    for component in vocabulary_module.allowed_components
                }
                component_ids = [
                    str(component.get("component_id") or "").strip()
                    for component in (module.get("components") or [])
                    if isinstance(component, dict)
                ]
                if not component_ids or not set(component_ids) <= allowed_component_ids:
                    blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR)

        context = self._latest_framework_build_context(draft)
        if not context:
            blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_CONTRACT_ERROR)
            return
        build_mode = str(context.get("build_mode") or "")
        issue_codes = [
            str(code or "")
            for code in (context.get("memory_pack_issue_codes") or [])
            if str(code or "")
        ]
        memory_status = str(context.get("memory_pack_status") or "")
        if memory_status not in {"ready", "created_minimal"}:
            blocking_issues.append(CHAPTER_MEMORY_PACK_MISSING)
        project_id = self._current_project_id()
        premise_exists = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
        ) is not None
        if premise_exists or project_requires_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            project_file=self.project_file,
        ):
            premise_status = str(context.get("project_story_premise_status") or "")
            premise_ref = str(context.get("project_story_premise_ref") or "")
            premise_terms = context.get("project_story_premise_terms") or []
            if premise_status != "ready" or not premise_ref or not premise_terms:
                blocking_issues.append(CHAPTER_PLAN_PROJECT_STORY_PREMISE_MISSING)
        if build_mode == "fallback":
            warnings.append(MODEL_FALLBACK_USED)
            blocking_issues.append(CHAPTER_PLAN_FRAMEWORK_FALLBACK_UNACKNOWLEDGED)
        if context.get("memory_pack_status") == "missing_degraded" or CHAPTER_MEMORY_PACK_MISSING in issue_codes:
            blocking_issues.append(CHAPTER_MEMORY_PACK_MISSING)
        if CHAPTER_MEMORY_PACK_CREATED_MINIMAL in issue_codes:
            warnings.append(CHAPTER_MEMORY_PACK_CREATED_MINIMAL)
        if context.get("project_story_premise_status") == "missing":
            blocking_issues.append(CHAPTER_PLAN_PROJECT_STORY_PREMISE_MISSING)

    def _validate_chapter_plan_prompt_fidelity(
        self,
        draft: ChapterPlanDraft,
        blocking_issues: list[str],
        warnings: list[str],
    ) -> None:
        project_id = self._current_project_id()
        premise = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
        )
        if not premise:
            if project_requires_story_premise(
                store=self.store,
                data_dir=self.data_dir,
                project_id=project_id,
                project_file=self.project_file,
            ):
                blocking_issues.append(CHAPTER_PLAN_PROJECT_STORY_PREMISE_MISSING)
            return
        story_text = self._collect_draft_text(draft)
        compact_story_text = compact_json_text(
            {
                "chapter_routes": [model_to_dict(route) for route in draft.chapter_routes],
                "current_chapter_brief": model_to_dict(draft.current_chapter_brief),
            }
        )
        fidelity_text = f"{story_text}\n{compact_story_text}"
        required_terms = premise_required_terms(premise)
        hits = [
            term
            for term in required_terms
            if term and term in fidelity_text
        ]
        if required_terms and not hits:
            blocking_issues.append(CHAPTER_PLAN_PROMPT_FIDELITY_MISSING)
        elif required_terms and len(hits) < min(2, len(required_terms)):
            warnings.append(CHAPTER_PLAN_PROMPT_FIDELITY_WEAK)
        route_texts = [
            "\n".join(
                [
                    route.temporary_title,
                    route.light_route_summary,
                    route.narrative_function,
                    route.expected_conflict_hint,
                ]
            )
            for route in draft.chapter_routes
        ]
        brief = draft.current_chapter_brief
        brief_text = "\n".join(
            [
                str(brief.title or ""),
                str(brief.chapter_goal or ""),
                str(brief.reader_emotion_goal or ""),
                str(brief.main_conflict or ""),
                str(brief.summary_for_scene_generation or ""),
            ]
        )
        scoped_texts = [*route_texts, brief_text]
        if required_terms and scoped_texts:
            scoped_hits = [
                any(term and term in text for term in required_terms)
                for text in scoped_texts
            ]
            if not any(scoped_hits):
                blocking_issues.append(CHAPTER_PLAN_PROMPT_FIDELITY_MISSING)
            elif not all(scoped_hits):
                warnings.append(CHAPTER_PLAN_PROMPT_FIDELITY_WEAK)
        if sum(fidelity_text.count(default) for default in FORBIDDEN_DEMO_DEFAULTS) > 0:
            blocking_issues.append(CHAPTER_PLAN_DEMO_DEFAULT_LEAK)

    def _premise_evidence_text(self, premise: Any) -> str:
        terms = premise_required_terms(premise) if premise else []
        summary = str(getattr(premise, "safe_user_story_summary", "") or "")
        evidence = " / ".join([*terms[:6], summary][:7]).strip()
        return evidence[:420] or "confirmed project premise"

    def _latest_framework_build_context(
        self,
        draft: ChapterPlanDraft,
    ) -> dict[str, Any] | None:
        framework_id = str(draft.current_chapter_framework_id or "")
        contexts = self._read_list_if_present(self.chapter_framework_build_contexts_file)
        candidates = [
            context
            for context in contexts
            if isinstance(context, dict)
            and (
                context.get("chapter_framework_id") == framework_id
                or (
                    int(context.get("chapter_index") or 0) == draft.current_chapter_index
                    and framework_id == f"chapter_fw_{draft.current_chapter_index:03d}"
                )
            )
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )[0]

    def _validate_forbidden_knowledge(
        self,
        draft: ChapterPlanDraft,
        characters: list[Character],
        blocking_issues: list[str],
    ) -> None:
        text = self._collect_story_content_text(draft)
        for character in characters:
            for forbidden in character.profile.forbidden_knowledge:
                if not forbidden:
                    continue
                forbidden_positive = forbidden.replace("不知道", "知道")
                if forbidden in text or forbidden_positive in text:
                    blocking_issues.append("Chapter plan gives a character forbidden knowledge.")
                    return

    def _validate_world_hard_rules(
        self,
        draft: ChapterPlanDraft,
        world_canvas: WorldCanvas | None,
        blocking_issues: list[str],
        user_confirmation_needed: list[str],
    ) -> None:
        if world_canvas is None:
            return
        draft_text = self._collect_draft_text(draft)
        hard_rule_texts = [
            f"{rule.rule_id} {rule.statement}" for rule in world_canvas.hard_rules
        ]
        issue_count_before = len(blocking_issues)
        if self._has_midnight_only_rule(hard_rule_texts) and self._claims_non_midnight_trigger(draft_text):
            blocking_issues.append("Chapter plan appears to violate a World Canvas hard trigger rule.")
        if self._has_no_free_memory_creation_rule(hard_rule_texts) and self._claims_free_memory_creation(draft_text):
            blocking_issues.append("Chapter plan appears to violate a World Canvas hard memory-creation rule.")
        if self._has_no_free_memory_reversal_rule(hard_rule_texts) and self._claims_free_memory_reversal(draft_text):
            blocking_issues.append("Chapter plan appears to violate a World Canvas hard memory-reversal rule.")
        if self._claims_explicit_hard_rule_override(draft_text):
            blocking_issues.append("Chapter plan explicitly overrides or ignores World Canvas hard rules.")
        if len(blocking_issues) > issue_count_before:
            user_confirmation_needed.append(
                "请修订章节规划，使当前章遵守已经确认的世界硬规则。"
            )

    def _validate_future_locking(
        self,
        draft: ChapterPlanDraft,
        warnings: list[str],
        user_confirmation_needed: list[str],
    ) -> None:
        future_routes = [
            route for route in draft.chapter_routes if route.chapter_index != draft.current_chapter_index
        ]
        future_text = "\n".join(
            [
                route.temporary_title
                + "\n"
                + route.light_route_summary
                + "\n"
                + route.narrative_function
                + "\n"
                + route.expected_conflict_hint
                for route in future_routes
            ]
            + [draft.latest_user_prompt]
        )
        lock_markers = [
            "必死",
            "必然死亡",
            "固定死亡",
            "必背叛",
            "固定背叛",
            "必觉醒",
            "固定觉醒",
            "锁定结局",
            "结局必定",
            "精确揭示",
            "must die",
            "fixed ending",
            "locked ending",
            "exact reveal",
            "guaranteed betrayal",
        ]
        if any(marker in future_text for marker in lock_markers):
            warnings.append(
                "Future chapter route appears to lock a death, betrayal, ending, awakening, or exact reveal."
            )
            user_confirmation_needed.append(
                "请把未来章节改成轻量意图，不要锁死未来命运或精确揭示。"
            )

    def _collect_draft_text(self, draft: ChapterPlanDraft) -> str:
        brief = draft.current_chapter_brief
        parts = [
            brief.title,
            brief.chapter_goal,
            brief.main_conflict,
            brief.summary_for_scene_generation,
        ]
        for focus in brief.character_desire_or_arc_focus:
            parts.extend(str(value) for value in focus.values())
        for focus in brief.supporting_role_function_focus:
            parts.extend(str(value) for value in focus.values())
        for need in brief.cd_role_function_needs:
            parts.extend(str(value) for value in model_to_dict(need).values())
        for route in draft.chapter_routes:
            parts.extend(
                [
                    route.temporary_title,
                    route.macro_component_label,
                    route.light_route_summary,
                    route.narrative_function,
                    route.expected_conflict_hint,
                ]
            )
            for need in route.cd_role_function_need_hints:
                parts.extend(str(value) for value in model_to_dict(need).values())
        return "\n".join(part for part in parts if part)

    def _collect_story_content_text(self, draft: ChapterPlanDraft) -> str:
        brief = draft.current_chapter_brief
        parts = [
            draft.story_goal,
            brief.title,
            brief.chapter_goal,
            brief.main_conflict,
            brief.summary_for_scene_generation,
        ]
        parts.extend(brief.reader_emotion_goal)
        for focus in brief.character_desire_or_arc_focus:
            parts.extend(str(value) for value in focus.values())
        for focus in brief.supporting_role_function_focus:
            parts.extend(str(value) for value in focus.values())
        for need in brief.cd_role_function_needs:
            parts.extend(str(value) for value in model_to_dict(need).values())
        for route in draft.chapter_routes:
            parts.extend(
                [
                    route.temporary_title,
                    route.light_route_summary,
                    route.narrative_function,
                    route.expected_conflict_hint,
                ]
            )
            for need in route.cd_role_function_need_hints:
                parts.extend(str(value) for value in model_to_dict(need).values())
        return "\n".join(part for part in parts if part)

    def _has_midnight_only_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "midnight" in text.lower()
            or "零点" in text
            or "午夜" in text
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
                if not self._is_negated_claim_sentence(sentence, index - self._sentence_start_index(text, index)):
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

    def _claims_explicit_hard_rule_override(self, text: str) -> bool:
        return any(
            marker in text
            for marker in [
                "无视世界硬规则",
                "无视硬规则",
                "违反硬规则",
                "不受世界规则限制",
                "不受任何已确认规则限制",
                "ignore hard rules",
                "override hard rules",
            ]
        )

    def _read_world_canvas(self) -> WorldCanvas:
        data = self.store.read(self.world_canvas_file)
        try:
            return WorldCanvas(**data)
        except ValidationError as exc:
            raise StorageError("WorldCanvas JSON schema is invalid.") from exc

    def _read_characters(self) -> list[Character]:
        data = self.repositories.characters.list_all()
        try:
            return [Character(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Character repository schema is invalid.") from exc

    def _read_confirmed_a_characters_if_present(self) -> list[Character]:
        return [
            character
            for character in self._read_characters()
            if character.tier == "A" and character.status == "confirmed"
        ]

    def _read_confirmed_characters_by_tier(self) -> dict[str, list[Character]]:
        result: dict[str, list[Character]] = {tier: [] for tier in ["A", "B", "C", "D"]}
        for character in self._read_characters():
            tier = str(character.tier or "").upper()
            if tier in result and character.status == "confirmed":
                result[tier].append(character)
        return result

    def _read_relationships(self) -> list[Relationship]:
        data = self.repositories.relationships.list_all()
        try:
            return [Relationship(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Relationship repository schema is invalid.") from exc

    def _read_decision_dicts(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        return [
            dict(item)
            for item in self.store.read_list(self.decisions_file)
            if isinstance(item, dict)
        ]

    def _read_chapter_plan_draft(self) -> ChapterPlanDraft:
        if not self.store.exists(self.chapter_plan_draft_file):
            raise StorageError("CHAPTER_PLAN_DRAFT_MISSING: Current chapter plan draft does not exist.")
        data = self.store.read(self.chapter_plan_draft_file)
        try:
            return self._normalize_chapter_scene_beats_for_draft(ChapterPlanDraft(**data))
        except ValidationError as exc:
            raise StorageError("ChapterPlanDraft JSON schema is invalid.") from exc

    def _active_story_progress_chapter_index(self) -> int:
        story_progress_file = self.data_dir / "story_progress.json"
        if not self.store.exists(story_progress_file):
            return 0
        try:
            payload = self.store.read(story_progress_file)
        except StorageError:
            return 0
        if not isinstance(payload, dict):
            return 0
        status = str(payload.get("story_progress_status") or "").strip()
        if status not in {"current_chapter_active", "next_chapter_active"}:
            return 0
        try:
            chapter_index = int(payload.get("current_chapter_index") or 0)
        except (TypeError, ValueError):
            return 0
        if self._chapter_has_archive(chapter_index):
            return 0
        return chapter_index

    def _chapter_has_archive(self, chapter_index: int) -> bool:
        if chapter_index < 1:
            return False
        archive_file = self.data_dir / "chapter_archives.json"
        if not self.store.exists(archive_file):
            return False
        try:
            archives = self.store.read_list(archive_file)
        except StorageError:
            return False
        return any(
            isinstance(item, dict)
            and int(item.get("chapter_index") or 0) == chapter_index
            for item in archives
        )

    def _try_read_chapter_plan_draft(self) -> ChapterPlanDraft | None:
        try:
            return self._read_chapter_plan_draft()
        except StorageError:
            return None

    def _read_chapters_if_present(self) -> list[Chapter]:
        data = self.repositories.chapters.list_all()
        try:
            return [Chapter(**item) for item in data if isinstance(item, dict)]
        except ValidationError as exc:
            raise StorageError("Chapter repository schema is invalid.") from exc

    def _try_read_world_canvas_for_validation(
        self,
        blocking_issues: list[str],
    ) -> WorldCanvas | None:
        try:
            world_canvas = self.load_confirmed_world_canvas()
        except StorageError:
            blocking_issues.append("WorldCanvas.status must be confirmed.")
            return None
        return world_canvas

    def _try_read_framework_package_for_validation(
        self,
        blocking_issues: list[str],
    ) -> FrameworkPackage | None:
        try:
            return self.load_and_validate_framework_package()
        except StorageError as exc:
            blocking_issues.append(str(exc))
            return None

    def _chapter_framework_from_draft(
        self,
        draft: ChapterPlanDraft,
    ) -> ChapterFramework:
        if not draft.current_chapter_framework:
            raise StorageError("Current chapter framework draft is missing.")
        try:
            return ChapterFramework(**draft.current_chapter_framework)
        except ValidationError as exc:
            raise StorageError("Current chapter framework draft schema is invalid.") from exc

    def _ensure_framework_has_build_audit(
        self,
        framework: ChapterFramework,
    ) -> None:
        contexts = self._read_list_if_present(self.chapter_framework_build_contexts_file)
        reasons = self._read_list_if_present(self.chapter_framework_build_reasons_file)
        expected_context_framework_id = f"chapter_fw_{framework.chapter_index:03d}"
        has_context = any(
            isinstance(context, dict)
            and (
                context.get("chapter_framework_id") == framework.chapter_framework_id
                or (
                    context.get("chapter_index") == framework.chapter_index
                    and expected_context_framework_id == framework.chapter_framework_id
                )
            )
            for context in contexts
        )
        has_reason = any(
            isinstance(reason, dict)
            and reason.get("chapter_framework_id") == framework.chapter_framework_id
            for reason in reasons
        )
        if not has_context or not has_reason:
            raise StorageError(
                "CHAPTER_FRAMEWORK_AUDIT_MISSING: Current chapter framework must have Phase 3 M2 build context and reasons."
            )

    def _assignments_for_count(
        self,
        package: FrameworkPackage,
        chapter_count: int,
    ) -> list[ChapterMacroAssignment]:
        assignments = [
            assignment
            for assignment in package.chapter_macro_assignments
            if 1 <= assignment.chapter_index <= chapter_count
        ]
        if len(assignments) != chapter_count:
            raise StorageError(
                "CURRENT_CHAPTER_ASSIGNMENT_MISSING: Confirmed framework mapping must cover the requested chapter_count."
            )
        return sorted(assignments, key=lambda assignment: assignment.chapter_index)

    def _read_list_if_present(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [
            item
            for item in self.store.read_list(path)
            if isinstance(item, dict)
        ]

    def load_generator_framework_context(
        self,
        framework_composition_id: str | None = "",
    ) -> dict[str, Any]:
        requested_id = str(framework_composition_id or "").strip()
        stored_context = self._read_generator_framework_context()
        stored_id = self._framework_composition_id(stored_context)
        if stored_context:
            if requested_id and stored_id and stored_id != requested_id:
                raise StorageError(
                    "GENERATOR_FRAMEWORK_CONTEXT_ID_MISMATCH:"
                    f"requested={requested_id}:stored={stored_id}"
                )
            return stored_context
        if not requested_id:
            return {}
        context = self._build_generator_framework_context_for_requested_id(
            requested_id
        )
        self.store.write(self.generator_framework_context_file, context)
        return context

    def _build_generator_framework_context_for_requested_id(
        self,
        requested_id: str,
    ) -> dict[str, Any]:
        try:
            return GeneratorFrameworkContextService(
                store=self.store,
                data_dir=self.data_dir,
            ).build_context(requested_id)
        except StorageError as active_exc:
            if self.data_dir.resolve() == settings.data_dir.resolve():
                raise
            try:
                return GeneratorFrameworkContextService(
                    store=self.store,
                    data_dir=settings.data_dir,
                ).build_context(requested_id)
            except StorageError:
                raise active_exc

    def _read_generator_framework_context(self) -> dict[str, Any]:
        if not self.store.exists(self.generator_framework_context_file):
            return {}
        data = self.store.read_any(self.generator_framework_context_file)
        if not isinstance(data, dict):
            raise StorageError("GENERATOR_FRAMEWORK_CONTEXT_INVALID: expected object")
        if data.get("schema_version") != GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_VERSION:
            raise StorageError("GENERATOR_FRAMEWORK_CONTEXT_SCHEMA_MISMATCH")
        return data

    def _chapter_framework_payload_with_generator_context(
        self,
        framework: ChapterFramework,
        generator_framework_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = model_to_dict(framework)
        context = dict(generator_framework_context or {})
        composition_id = self._framework_composition_id(context)
        if not composition_id:
            return payload
        payload["framework_composition_id"] = composition_id
        payload["generator_framework_context"] = {
            "schema_version": context.get("schema_version", ""),
            "composition_ref": context.get("composition_ref") or {},
            "chapter_framework_context": context.get("chapter_framework_context") or {"items": []},
            "evidence_refs": self._framework_context_source_refs(context),
            "policy_issues": context.get("policy_issues") or [],
        }
        payload["generator_context_source_refs"] = self._framework_context_source_refs(context)
        return payload

    def _framework_composition_id(
        self,
        generator_framework_context: dict[str, Any] | None,
    ) -> str:
        if not isinstance(generator_framework_context, dict):
            return ""
        composition_ref = generator_framework_context.get("composition_ref") or {}
        if not isinstance(composition_ref, dict):
            return ""
        return str(composition_ref.get("composition_id") or "").strip()

    def _framework_context_source_refs(
        self,
        generator_framework_context: dict[str, Any] | None,
    ) -> list[str]:
        if not isinstance(generator_framework_context, dict):
            return []
        refs = [
            str(ref or "").strip()
            for ref in generator_framework_context.get("evidence_refs", [])
            if str(ref or "").strip()
        ]
        return self._unique_strings(refs)

    def _find_route_data(
        self,
        route_data_list: list[Any],
        chapter_index: int,
    ) -> dict[str, Any]:
        for item in route_data_list:
            if not isinstance(item, dict):
                continue
            if item.get("chapter_index") == chapter_index:
                return dict(item)
        if 0 <= chapter_index - 1 < len(route_data_list):
            item = route_data_list[chapter_index - 1]
            if isinstance(item, dict):
                return dict(item)
        return {}

    def _fallback_route_summary(self, chapter_index: int, macro_label: str) -> str:
        return f"第 {chapter_index} 章承担{macro_label or '阶段'}功能，只保留轻量路线意图。"

    def _fallback_narrative_function(self, chapter_index: int) -> str:
        if chapter_index == 1:
            return "建立世界规则、主角压力和最初调查入口。"
        return "推进阶段性压力，但不锁死未来具体事件。"

    def _validate_chapter_count(self, chapter_count: int) -> None:
        if chapter_count < CHAPTER_COUNT_MIN or chapter_count > CHAPTER_COUNT_MAX:
            raise StorageError(
                f"CHAPTER_COUNT_INVALID: chapter_count must be between {chapter_count_range_label()}."
            )

    def _raise_if_foundation_not_ready(
        self,
        foundation: ChapterPlanFoundationStatus,
    ) -> None:
        if foundation.ready:
            return
        raise StorageError(
            "FOUNDATION_NOT_READY: 请先确认世界画布并完成主角团初始化，再生成章节路线。 "
            + "; ".join(foundation.issues)
        )

    def _update_project_step(self, current_step: str, status: str) -> None:
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

    def _chapter_id(self, chapter_index: int) -> str:
        return f"chapter_m6_{chapter_index:03d}"

    def _next_draft_id(self) -> str:
        if not self.store.exists(self.chapter_plan_draft_file):
            return "chapter_plan_draft_001"
        try:
            existing = self._read_chapter_plan_draft()
        except StorageError:
            return "chapter_plan_draft_001"
        digits = "".join(ch for ch in existing.draft_id if ch.isdigit())
        next_number = int(digits or "0") + 1
        return f"chapter_plan_draft_{next_number:03d}"

    def _unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
