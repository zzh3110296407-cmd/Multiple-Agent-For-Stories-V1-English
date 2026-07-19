from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.agents.character_agent import CharacterAgent
from app.backend.core.config import settings
from app.backend.models.character import Character
from app.backend.models.character_workflow import (
    CharacterValidationReport,
    CharacterWorkflowResponse,
    CurrentCharacterDraft,
)
from app.backend.models.decision import Decision
from app.backend.models.relationship import Relationship
from app.backend.models.world_canvas import WorldCanvas
from app.backend.repositories import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.character_prompt_fidelity_service import (
    CHARACTER_PROJECT_STORY_PREMISE_MISSING,
    project_requires_story_premise,
    require_project_story_premise_for_generation,
    try_read_project_story_premise,
    validate_character_prompt_absorption,
)
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.tracing_service import traceable_operation
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
CHARACTER_VERSION_ID = "version_character_m5_001"
RELATIONSHIP_VERSION_ID = "version_relationship_m5_001"
CHARACTER_MODEL_CALL_FALLBACK_WARNING = (
    "character_model_call_failed_used_deterministic_fallback"
)
CHARACTER_MODEL_JSON_FALLBACK_WARNING = (
    "character_model_json_failed_used_deterministic_fallback"
)
SHANGHAI_TZ = timezone(timedelta(hours=8))
POST_MAIN_CAST_STEPS = {
    "characters_confirmed",
    "chapter_plan_draft",
    "chapter_plan_confirmed",
    "chapter_in_progress",
    "chapter_archived",
    "next_chapter_preparation",
    "next_chapter_active",
}
POST_MAIN_CAST_SCENE_STEP_RE = re.compile(
    r"^scene_\d+_(confirmed|revised|temporary_confirmed|continuity_recheck)$"
)


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


class CharacterService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        agent: CharacterAgent | None = None,
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
        self.current_draft_file = self.data_dir / "current_character_draft.json"
        self.agent = agent or CharacterAgent(
            model_gateway=ModelGatewayService(store=self.store, data_dir=self.data_dir)
        )

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_characters(self) -> CharacterWorkflowResponse:
        return CharacterWorkflowResponse(
            draft=self._try_read_current_draft(),
            characters=self._read_characters(),
            relationships=self._read_relationships(),
            main_cast_finished=self._is_main_cast_finished(),
        )

    def get_current_draft(self) -> CharacterWorkflowResponse:
        draft = self._try_read_current_draft()
        return CharacterWorkflowResponse(
            draft=draft,
            characters=self._read_characters(),
            relationships=self._read_relationships(),
            validation=draft.validation_report if draft else None,
            main_cast_finished=self._is_main_cast_finished(),
        )

    @traceable_operation("CharacterService.generate_character", tags=["characters"])
    def generate_character(
        self,
        user_prompt: str,
        role_hint: str | None = None,
        story_function_hint: str | None = None,
    ) -> CharacterWorkflowResponse:
        clean_prompt = user_prompt.strip()
        if not clean_prompt:
            raise StorageError("user_prompt must not be empty.")
        world_canvas = self.load_confirmed_world_canvas()
        existing_characters = self._read_confirmed_characters()
        project_story_premise = require_project_story_premise_for_generation(
            store=self.store,
            data_dir=self.data_dir,
            project_id=self._current_project_id(),
            missing_code=CHARACTER_PROJECT_STORY_PREMISE_MISSING,
            project_file=self.project_file,
        )
        same_tier_characters = [
            character for character in existing_characters if character.tier == "A"
        ]

        existing_relationships = self._read_confirmed_relationships()
        fallback_warning = ""
        try:
            agent_data = self.agent.generate_character(
                world_canvas=world_canvas,
                existing_characters=existing_characters,
                existing_relationships=existing_relationships,
                user_prompt=clean_prompt,
                role_hint=role_hint or "",
                story_function_hint=story_function_hint or "",
                project_story_premise=project_story_premise,
                same_tier_characters=same_tier_characters,
            )
        except (ModelConfigurationError, ModelCallError, ModelJsonParseError) as exc:
            fallback_warning = CHARACTER_MODEL_CALL_FALLBACK_WARNING
            if isinstance(exc, ModelJsonParseError):
                fallback_warning = CHARACTER_MODEL_JSON_FALLBACK_WARNING
            agent_data = {
                "character": self._fallback_character_payload(
                    user_prompt=clean_prompt,
                    role_hint=role_hint or "",
                    story_function_hint=story_function_hint or "",
                    world_canvas=world_canvas,
                    project_story_premise=project_story_premise,
                ),
                "relationship_drafts": [],
            }
        draft = self._build_draft_from_agent_data(
            data=agent_data,
            world_canvas=world_canvas,
            existing_characters=existing_characters,
            existing_relationships=existing_relationships,
            latest_user_prompt=clean_prompt,
            existing_draft=None,
        )
        draft = self._draft_with_fallback_warning(draft, fallback_warning)
        self.save_current_draft(draft)
        self._update_project_step("character_draft", "drafting_character")
        return CharacterWorkflowResponse(
            draft=draft,
            characters=self._read_characters(),
            relationships=self._read_relationships(),
            validation=draft.validation_report,
        )

    @traceable_operation("CharacterService.revise_character", tags=["characters"])
    def revise_character(self, revision_prompt: str) -> CharacterWorkflowResponse:
        clean_prompt = revision_prompt.strip()
        if not clean_prompt:
            raise StorageError("revision_prompt must not be empty.")
        world_canvas = self.load_confirmed_world_canvas()
        current_draft = self._read_current_draft()
        existing_characters = self._read_confirmed_characters(
            exclude_character_id=current_draft.character.character_id
        )
        existing_relationships = self._read_confirmed_relationships()
        fallback_warning = ""
        try:
            agent_data = self.agent.revise_character(
                current_draft=current_draft,
                world_canvas=world_canvas,
                existing_characters=existing_characters,
                existing_relationships=existing_relationships,
                revision_prompt=clean_prompt,
            )
        except (ModelConfigurationError, ModelCallError, ModelJsonParseError) as exc:
            fallback_warning = CHARACTER_MODEL_CALL_FALLBACK_WARNING
            if isinstance(exc, ModelJsonParseError):
                fallback_warning = CHARACTER_MODEL_JSON_FALLBACK_WARNING
            agent_data = {
                "character": self._fallback_revised_character_payload(
                    current_draft=current_draft,
                    revision_prompt=clean_prompt,
                ),
                "relationship_drafts": [
                    model_to_dict(relationship)
                    for relationship in current_draft.relationship_drafts
                ],
            }
        draft = self._build_draft_from_agent_data(
            data=agent_data,
            world_canvas=world_canvas,
            existing_characters=existing_characters,
            existing_relationships=existing_relationships,
            latest_user_prompt=clean_prompt,
            existing_draft=current_draft,
        )
        draft = self._draft_with_fallback_warning(draft, fallback_warning)
        self.save_current_draft(draft)
        self._update_project_step("character_draft", "drafting_character")
        return CharacterWorkflowResponse(
            draft=draft,
            characters=self._read_characters(),
            relationships=self._read_relationships(),
            validation=draft.validation_report,
        )

    @traceable_operation("CharacterService.confirm_character", tags=["characters"])
    def confirm_character(self, user_input: str | None = None) -> CharacterWorkflowResponse:
        draft = self._read_current_draft()
        if draft.status == "confirmed" or draft.character.status == "confirmed":
            raise StorageError(
                "CHARACTER_DRAFT_ALREADY_CONFIRMED: Current character draft has already been confirmed."
            )
        validation = self.validate_character_draft(draft)
        if validation.blocking_issues:
            raise StorageError(
                "Cannot confirm Character while blocking validation issues exist."
            )

        character, relationships = self.append_confirmed_character_and_relationships(draft)
        self.update_story_bible_refs(
            character_ids=[character.character_id],
            relationship_ids=[relationship.relationship_id for relationship in relationships],
        )
        decision = self._append_decision(
            decision_type="confirm",
            target_type="character",
            target_id=character.character_id,
            user_input=user_input
            or "用户确认当前角色作为后续章节规划与场景模拟的主角输入。",
        )
        confirmed_draft = copy_model(
            draft,
            character=character,
            relationship_drafts=relationships,
            validation_report=validation,
            status="confirmed",
            updated_at=now_iso(),
        )
        self.save_current_draft(confirmed_draft)
        if not self._is_main_cast_finished():
            self._update_project_step("character_confirmed", "character_confirmed")
        return CharacterWorkflowResponse(
            draft=confirmed_draft,
            characters=self._read_characters(),
            relationships=self._read_relationships(),
            validation=validation,
            decision=decision,
        )

    @traceable_operation("CharacterService.finish_main_cast", tags=["characters"])
    def finish_main_cast(self, user_input: str | None = None) -> CharacterWorkflowResponse:
        confirmed_characters = self._read_confirmed_characters()
        if self._confirmed_a_tier_count(confirmed_characters) < 1:
            raise StorageError(
                "MAIN_CAST_REQUIRES_CHARACTER: Confirm at least one A-tier character before finishing main cast setup."
            )
        decision = self._append_decision(
            decision_type="confirm",
            target_type="main_cast",
            target_id=self._current_project_id(),
            user_input=user_input or "用户确认主角团初始化完成。",
        )
        self._update_project_step("characters_confirmed", "characters_confirmed")
        return CharacterWorkflowResponse(
            draft=self._try_read_current_draft(),
            characters=self._read_characters(),
            relationships=self._read_relationships(),
            decision=decision,
            main_cast_finished=True,
        )

    def load_confirmed_world_canvas(self) -> WorldCanvas:
        try:
            data = self.store.read(self.world_canvas_file)
            world_canvas = WorldCanvas(**data)
        except (StorageError, ValidationError) as exc:
            raise StorageError(
                "WORLD_CANVAS_NOT_CONFIRMED: 请先确认世界画布，再创建主角。"
            ) from exc
        if world_canvas.status != "confirmed":
            raise StorageError(
                "WORLD_CANVAS_NOT_CONFIRMED: 请先确认世界画布，再创建主角。"
            )
        return world_canvas

    def validate_character_draft(
        self,
        draft: CurrentCharacterDraft,
    ) -> CharacterValidationReport:
        warnings: list[str] = []
        blocking_issues: list[str] = []
        user_confirmation_needed: list[str] = []

        world_canvas = self._try_load_confirmed_world_canvas_for_validation(
            blocking_issues
        )
        character = draft.character
        profile = character.profile
        state = character.current_state
        arc = character.arc_state

        current_project_id = self._current_project_id()
        if draft.project_id != current_project_id or character.project_id != current_project_id:
            blocking_issues.append("Character draft project_id must match current project.")
        if draft.status not in {"draft", "confirmed"}:
            blocking_issues.append("CurrentCharacterDraft.status must be draft or confirmed.")
        if character.tier != "A":
            blocking_issues.append("Character.tier must be A for Milestone 5 main cast setup.")
        if not character.name:
            blocking_issues.append("Character.name must not be empty.")
        if not profile.identity:
            blocking_issues.append("Character.profile.identity must not be empty.")
        if not profile.background_summary:
            blocking_issues.append("Character.profile.background_summary must not be empty.")
        if not state.current_desire:
            blocking_issues.append("Character.current_state.current_desire must not be empty.")
        if not state.current_fear:
            blocking_issues.append("Character.current_state.current_fear must not be empty.")
        if not profile.personality_baseline.traits:
            blocking_issues.append("Character.profile.personality_baseline.traits must not be empty.")
        if not profile.personality_baseline.values:
            blocking_issues.append("Character.profile.personality_baseline.values must not be empty.")
        if not profile.personality_baseline.bottom_line:
            blocking_issues.append("Character.profile.personality_baseline.bottom_line must not be empty.")
        if not profile.hard_limits:
            blocking_issues.append("Character.profile.hard_limits must contain at least one limit.")
        elif any(not limit.statement for limit in profile.hard_limits):
            blocking_issues.append("Character.profile.hard_limits statements must not be empty.")

        self._validate_location_faction_species_refs(character, world_canvas, warnings)
        self._validate_knowledge_boundaries(character, world_canvas, blocking_issues, warnings)
        self._validate_world_hard_rules(
            character,
            world_canvas,
            blocking_issues,
            user_confirmation_needed,
        )
        self._validate_duplicate_story_function(character, warnings, user_confirmation_needed)
        self._validate_relationship_drafts(draft, blocking_issues)
        self._validate_future_locking(character, blocking_issues, user_confirmation_needed)
        premise = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=current_project_id,
        )
        if premise or project_requires_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=current_project_id,
            project_file=self.project_file,
        ):
            m3_blocking, m3_warnings, _coverage = validate_character_prompt_absorption(
                character=character,
                requested_tier="A",
                existing_characters=self._read_confirmed_characters(
                    exclude_character_id=character.character_id
                ),
                premise=premise,
                latest_user_prompt=draft.latest_user_prompt,
                issue_prefix="character",
            )
            blocking_issues.extend(m3_blocking)
            warnings.extend(m3_warnings)

        if warnings and not user_confirmation_needed:
            user_confirmation_needed.append("请确认这些 warning 不会破坏后续章节规划。")

        return CharacterValidationReport(
            passed=len(blocking_issues) == 0,
            warnings=warnings,
            blocking_issues=blocking_issues,
            user_confirmation_needed=user_confirmation_needed,
        )

    def build_relationship_drafts(
        self,
        character: Character,
        existing_characters: list[Character],
        existing_relationships: list[Relationship],
        agent_relationships: list[Relationship],
    ) -> list[Relationship]:
        relationship_drafts = list(agent_relationships)
        if not existing_characters:
            return relationship_drafts

        existing_ids = {character.character_id for character in existing_characters}
        has_new_character_relationship = any(
            self._relationship_touches_new_and_existing(
                relationship=relationship,
                new_character_id=character.character_id,
                existing_ids=existing_ids,
            )
            for relationship in relationship_drafts
        )
        if has_new_character_relationship:
            return self._dedupe_relationships(relationship_drafts)

        target = existing_characters[0]
        relationship_id = self._relationship_id(character.character_id, target.character_id)
        if self._relationship_pair_exists(
            character.character_id,
            target.character_id,
            existing_relationships + relationship_drafts,
        ):
            return self._dedupe_relationships(relationship_drafts)
        relationship_drafts.append(
            Relationship(
                relationship_id=relationship_id,
                project_id=self._current_project_id(),
                source_id=character.character_id,
                target_id=target.character_id,
                type="alliance",
                state="新角色愿意交换线索，但双方都保留与世界核心规则有关的隐瞒。",
                strength=0.5,
                evidence_event_ids=[],
                evidence_note="这是主角初始化阶段的必要关系草案，不来自已生成事件。",
                status="draft",
                source="relationship_builder",
                version_id=RELATIONSHIP_VERSION_ID,
                created_at=now_iso(),
                updated_at=now_iso(),
            )
        )
        return self._dedupe_relationships(relationship_drafts)

    def _fallback_character_payload(
        self,
        *,
        user_prompt: str,
        role_hint: str,
        story_function_hint: str,
        world_canvas: WorldCanvas,
        project_story_premise: Any,
    ) -> dict[str, Any]:
        name = (
            self._name_from_prompt(user_prompt)
            or self._clean_text(role_hint)
            or "未命名主角"
        )
        prompt_evidence = self._limit_text(user_prompt, 420)
        premise_evidence = self._premise_evidence(project_story_premise)
        world_evidence = self._world_evidence(world_canvas)
        story_anchor = self._join_non_empty(
            [prompt_evidence, premise_evidence, world_evidence],
            separator="；",
        )
        identity = self._join_non_empty(
            [
                self._clean_text(role_hint),
                self._identity_from_prompt(user_prompt),
                "A 级主角",
            ],
            separator=" / ",
        )
        story_function = self._join_non_empty(
            [
                self._clean_text(story_function_hint),
                self._story_function_from_prompt(user_prompt),
                "推动核心谜团、世界规则验证与人物选择",
            ],
            separator="；",
        )
        core_goal = self._goal_from_prompt(user_prompt)
        core_fear = self._fear_from_prompt(user_prompt)
        return {
            "name": name,
            "tier": "A",
            "role": "protagonist",
            "profile": {
                "description": self._join_non_empty(
                    [
                        f"{name} 是从当前项目提示词生成的 A 级主角。",
                        prompt_evidence,
                    ],
                    separator=" ",
                ),
                "identity": identity,
                "story_function": story_function,
                "background_summary": story_anchor,
                "species_or_group": self._species_or_group_from_prompt(user_prompt),
                "faction_or_origin": self._faction_from_prompt(user_prompt),
                "appearance_summary": "",
                "traits": self._prompt_traits(user_prompt),
                "goals": [core_goal],
                "fears": [core_fear],
                "secrets": self._secrets_from_prompt(user_prompt),
                "personality_baseline": {
                    "traits": self._prompt_traits(user_prompt),
                    "values": self._prompt_values(user_prompt),
                    "bottom_line": self._bottom_line_from_prompt(user_prompt),
                    "speech_style_hint": "审慎、重视证据，避免越过已确认事实。",
                },
                "hard_limits": [
                    {
                        "limit_id": "limit_prompt_and_world_rules_001",
                        "statement": self._bottom_line_from_prompt(user_prompt),
                        "reason": "主角草案必须受当前世界画布和用户提示词约束。",
                        "source": "deterministic_fallback",
                    }
                ],
                "knowledge_scope": [
                    self._join_non_empty(
                        [
                            "只知道当前世界画布、已确认设定和自己可合理接触的线索",
                            self._limit_text(prompt_evidence, 140),
                        ],
                        separator="：",
                    )
                ],
                "forbidden_knowledge": [
                    "不能提前知道未生成章节的真相、幕后安排或最终结局。"
                ],
            },
            "current_state": {
                "location_id": "",
                "faction_id": "",
                "species_id": "",
                "emotional_state": self._emotional_state_from_prompt(user_prompt),
                "knowledge": [self._limit_text(prompt_evidence, 180)],
                "active_goal": core_goal,
                "current_desire": core_goal,
                "current_fear": core_fear,
                "resources": self._resources_from_prompt(user_prompt),
                "secrets": self._secrets_from_prompt(user_prompt),
            },
            "arc_state": {
                "current_arc": "从依赖既有证据到主动质疑权力结构与自我身份边界。",
                "starting_point": self._limit_text(prompt_evidence, 160),
                "pressure": self._pressure_from_prompt(user_prompt),
                "inner_conflict": self._inner_conflict_from_prompt(user_prompt),
                "next_possible_change": "在下一轮篇章规划中根据用户确认的角色选择继续更新。",
                "possible_direction": "沿用户设定的核心冲突推进，不提前锁死未来结局。",
                "locked_future_events": [],
            },
            "memory_summary": {
                "summary": self._limit_text(story_anchor, 260),
                "key_memory_ids": [],
                "open_threads": self._open_threads_from_prompt(user_prompt),
                "last_updated_event_id": "",
            },
            "context_budget": {
                "max_character_tokens": 1800,
                "include_recent_events": 4,
                "include_relationships": True,
                "include_memory_summary": True,
                "include_arc_state": True,
                "include_forbidden_knowledge": True,
                "include_full_profile": True,
            },
            "relationship_refs": [],
            "event_refs": [],
        }

    def _fallback_revised_character_payload(
        self,
        *,
        current_draft: CurrentCharacterDraft,
        revision_prompt: str,
    ) -> dict[str, Any]:
        raw = model_to_dict(current_draft.character)
        profile = dict(raw.get("profile") or {})
        state = dict(raw.get("current_state") or {})
        arc = dict(raw.get("arc_state") or {})
        memory = dict(raw.get("memory_summary") or {})
        revision_note = self._limit_text(revision_prompt, 260)
        profile["background_summary"] = self._join_non_empty(
            [profile.get("background_summary"), f"用户修订要求：{revision_note}"],
            separator="；",
        )
        profile["description"] = self._join_non_empty(
            [profile.get("description"), revision_note],
            separator=" ",
        )
        state["active_goal"] = self._join_non_empty(
            [state.get("active_goal"), revision_note],
            separator="；",
        )
        state["current_desire"] = state.get("current_desire") or state.get("active_goal") or revision_note
        arc["next_possible_change"] = self._join_non_empty(
            [arc.get("next_possible_change"), revision_note],
            separator="；",
        )
        memory["summary"] = self._join_non_empty(
            [memory.get("summary"), f"修订记录：{revision_note}"],
            separator="；",
        )
        raw["profile"] = profile
        raw["current_state"] = state
        raw["arc_state"] = arc
        raw["memory_summary"] = memory
        return raw

    def _draft_with_fallback_warning(
        self,
        draft: CurrentCharacterDraft,
        warning_code: str,
    ) -> CurrentCharacterDraft:
        if not warning_code:
            return draft
        validation = draft.validation_report
        warnings = list(validation.warnings)
        if warning_code not in warnings:
            warnings.append(warning_code)
        return copy_model(
            draft,
            validation_report=copy_model(validation, warnings=warnings),
        )

    def _name_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        patterns = [
            r"(?:[A-D]\s*级\s*)?(?:主角|角色|姓名)[:：]\s*([A-Za-z0-9_\-\u4e00-\u9fff]{2,16})",
            r"(?:名叫|叫作|叫做)[:：\s]*([A-Za-z0-9_\-\u4e00-\u9fff]{2,16})",
            r"([A-Za-z0-9_\-\u4e00-\u9fff]{2,16})[，,]\s*(?:[^。；;]{0,24})?(?:主角|审计员|侦探|记者|飞行员|科学家|工程师)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = self._clean_text(match.group(1)).strip("，,。；;：:")
                if self._valid_name_candidate(candidate):
                    return candidate
        return ""

    def _valid_name_candidate(self, candidate: str) -> bool:
        text = self._clean_text(candidate)
        if not text or len(text) > 16:
            return False
        if re.search(r"^(?:是|是一|是一名|一名|一个|核心|重要|年轻|长期)$", text):
            return False
        if any(marker in text for marker in ("主角", "角色", "级", "功能", "方向", "身份")):
            return False
        return True

    def _identity_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        identity_markers = [
            "记忆审计员",
            "AI副本",
            "AI 副本",
            "科学家",
            "工程师",
            "飞行员",
            "调查员",
            "侦探",
            "记者",
            "士兵",
            "学生",
        ]
        hits = [marker for marker in identity_markers if marker in text]
        return "、".join(hits[:3])

    def _story_function_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if any(marker in text for marker in ["追查", "调查", "审计", "被删", "失踪"]):
            return "追查核心事故与被隐藏的证据"
        if any(marker in text for marker in ["反抗", "逃离", "权力", "殖民"]):
            return "把个人选择推向制度冲突"
        return "承担主线视角与核心冲突推进"

    def _species_or_group_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if "AI" in text or "人工智能" in text:
            return "人类 / AI 相关群体"
        return "人类"

    def _faction_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if "企业殖民地" in text:
            return "企业殖民地体系相关"
        if "轨道城市" in text:
            return "轨道城市居民体系"
        return ""

    def _goal_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if any(marker in text for marker in ["追查", "调查", "审计", "航行记录"]):
            return "追查事故真相并核验被删除或受损的关键记录。"
        if "失踪" in text:
            return "找出失踪事件背后的真实原因。"
        return "推动当前提示词中的核心冲突进入可验证的故事行动。"

    def _fear_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if any(marker in text for marker in ["AI", "身份边界", "副本"]):
            return "无法判断记忆、人格与证据中哪一部分仍然可信。"
        if any(marker in text for marker in ["权力", "殖民", "企业"]):
            return "真相被权力结构再次掩盖。"
        return "自己的选择破坏已确认世界规则或误导后续剧情。"

    def _prompt_traits(self, prompt: str) -> list[str]:
        text = self._clean_text(prompt)
        traits = ["审慎", "证据导向"]
        if any(marker in text for marker in ["科幻", "技术", "量子", "AI"]):
            traits.append("技术敏感")
        if any(marker in text for marker in ["悬疑", "追查", "事故", "被删"]):
            traits.append("疑点追踪")
        return self._unique_strings(traits)

    def _prompt_values(self, prompt: str) -> list[str]:
        values = ["事实可核验", "不牺牲世界规则一致性"]
        if any(marker in prompt for marker in ["AI", "身份"]):
            values.append("尊重人格边界")
        return self._unique_strings(values)

    def _bottom_line_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if "不能主动伪造物理证据" in text:
            return "不能主动伪造物理证据，也不能绕过已确认技术代价。"
        return "不能违反已确认世界硬规则，不能提前得知未生成剧情真相。"

    def _secrets_from_prompt(self, prompt: str) -> list[str]:
        text = self._clean_text(prompt)
        secrets: list[str] = []
        if "秘密是" in text:
            secret = text.split("秘密是", 1)[1].split("；", 1)[0].split("。", 1)[0]
            secrets.append(self._limit_text(secret, 120))
        if "AI副本" in text or "AI 副本" in text:
            secrets.append("与 AI 副本的真实关系仍需在后续剧情中验证。")
        return self._unique_strings(secrets)

    def _emotional_state_from_prompt(self, prompt: str) -> str:
        if any(marker in prompt for marker in ["事故", "失踪", "被删", "悬疑"]):
            return "警觉且压抑，正在寻找可核验证据"
        return "准备进入主线行动"

    def _resources_from_prompt(self, prompt: str) -> list[str]:
        resources: list[str] = []
        if "航行记录" in prompt:
            resources.append("残缺航行记录线索")
        if "量子通信" in prompt:
            resources.append("受损记忆片段")
        if "AI" in prompt:
            resources.append("AI 副本对话入口")
        return self._unique_strings(resources)

    def _pressure_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if any(marker in text for marker in ["企业", "殖民地", "权力"]):
            return "企业殖民地权力结构持续压缩调查空间。"
        if "事故" in text:
            return "事故后果正在扩大，证据随时间继续流失。"
        return "核心冲突需要在后续章节中被具体化。"

    def _inner_conflict_from_prompt(self, prompt: str) -> str:
        text = self._clean_text(prompt)
        if any(marker in text for marker in ["AI", "身份边界", "副本"]):
            return "必须判断 AI 副本是可信主体、工具，还是被篡改过的证据容器。"
        return "必须在个人愿望和世界硬规则之间做出选择。"

    def _open_threads_from_prompt(self, prompt: str) -> list[str]:
        candidates = []
        text = self._clean_text(prompt)
        for marker in ["事故", "被删除的航行记录", "失踪飞船", "AI副本", "企业殖民地", "身份边界"]:
            if marker in text:
                candidates.append(marker)
        return self._unique_strings(candidates[:5])

    def _world_evidence(self, world_canvas: WorldCanvas) -> str:
        return self._limit_text(
            self._join_non_empty(
                [
                    world_canvas.story_direction,
                    world_canvas.scope,
                    world_canvas.tone,
                    world_canvas.world_structure.summary,
                    world_canvas.special_rules_summary,
                ],
                separator="；",
            ),
            320,
        )

    def _premise_evidence(self, premise: Any) -> str:
        if not premise:
            return ""
        data = model_to_dict(premise)
        pieces: list[str] = []
        for key in (
            "safe_user_story_summary",
            "required_story_elements",
            "core_terms",
            "setting_terms",
            "conflict_terms",
            "role_terms",
        ):
            value = data.get(key)
            if isinstance(value, list):
                pieces.extend(str(item) for item in value[:8])
            elif value:
                pieces.append(str(value))
        return self._limit_text(" ".join(pieces), 420)

    def _clean_text(self, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    def _limit_text(self, value: Any, limit: int) -> str:
        clean = self._clean_text(value)
        if len(clean) <= limit:
            return clean
        return clean[: max(0, limit - 1)].rstrip() + "…"

    def _join_non_empty(self, values: list[Any], separator: str) -> str:
        return separator.join(
            self._clean_text(value) for value in values if self._clean_text(value)
        )

    def save_current_draft(self, draft: CurrentCharacterDraft) -> None:
        self.store.write(self.current_draft_file, model_to_dict(draft))

    def append_confirmed_character_and_relationships(
        self,
        draft: CurrentCharacterDraft,
    ) -> tuple[Character, list[Relationship]]:
        timestamp = now_iso()
        relationship_ids = [relationship.relationship_id for relationship in draft.relationship_drafts]
        confirmed_character = copy_model(
            draft.character,
            relationship_refs=self._unique_strings(
                draft.character.relationship_refs + relationship_ids
            ),
            status="confirmed",
            source=draft.character.source or "agent_generated",
            updated_at=timestamp,
            created_at=draft.character.created_at or draft.created_at or timestamp,
        )
        confirmed_relationships = [
            copy_model(
                relationship,
                status="confirmed",
                source=relationship.source or "agent_generated",
                updated_at=timestamp,
                created_at=relationship.created_at or timestamp,
            )
            for relationship in draft.relationship_drafts
        ]

        characters = self._read_characters()
        characters = self._upsert_character(characters, confirmed_character)
        characters = self._attach_relationship_refs(characters, confirmed_relationships)
        self.repositories.characters.write_all(
            [model_to_dict(character) for character in characters]
        )

        relationships = self._read_relationships()
        for relationship in confirmed_relationships:
            relationships = self._upsert_relationship(relationships, relationship)
        self.repositories.relationships.write_all(
            [model_to_dict(relationship) for relationship in relationships]
        )
        return confirmed_character, confirmed_relationships

    def update_story_bible_refs(
        self,
        character_ids: list[str],
        relationship_ids: list[str],
    ) -> None:
        if not self.store.exists(self.story_bible_file):
            raise StorageError("StoryBible file is missing.")
        story_bible = self.store.read(self.story_bible_file)
        updated = dict(story_bible)
        updated["project_id"] = self._current_project_id()
        updated["main_character_ids"] = self._unique_strings(
            list(updated.get("main_character_ids") or []) + character_ids
        )
        updated["relationship_ids"] = self._unique_strings(
            list(updated.get("relationship_ids") or []) + relationship_ids
        )
        if updated != story_bible:
            self.store.write(self.story_bible_file, updated)

    def _build_draft_from_agent_data(
        self,
        data: dict[str, Any],
        world_canvas: WorldCanvas,
        existing_characters: list[Character],
        existing_relationships: list[Relationship],
        latest_user_prompt: str,
        existing_draft: CurrentCharacterDraft | None,
    ) -> CurrentCharacterDraft:
        timestamp = now_iso()
        character_data = dict(data.get("character") or {})
        if not character_data:
            raise StorageError("Character model output must include a character object.")
        existing_ids = {character.character_id for character in existing_characters}
        preserved_id = (
            existing_draft.character.character_id
            if existing_draft
            else ""
        )
        character_data["character_id"] = self._resolve_character_id(
            candidate_id=str(character_data.get("character_id") or ""),
            existing_ids=existing_ids,
            preserved_id=preserved_id,
        )
        current_project_id = self._current_project_id()
        character_data["project_id"] = current_project_id
        character_data["tier"] = "A"
        character_data["status"] = "draft"
        character_data["source"] = character_data.get("source") or "agent_generated"
        character_data["version_id"] = (
            character_data.get("version_id") or CHARACTER_VERSION_ID
        )
        character_data["created_at"] = (
            existing_draft.character.created_at
            if existing_draft and existing_draft.character.created_at
            else timestamp
        )
        character_data["updated_at"] = timestamp
        if existing_draft:
            original_name = self._clean_text(existing_draft.character.name)
            requested_name = self._revision_name_from_prompt(
                latest_user_prompt,
                current_name=original_name,
            )
            target_name = requested_name or original_name
            model_name = self._clean_text(str(character_data.get("name") or ""))
            if model_name and model_name != target_name:
                replaced = self._replace_text_value(
                    character_data,
                    model_name,
                    target_name,
                )
                if isinstance(replaced, dict):
                    character_data = replaced
            character_data["name"] = target_name
        else:
            character_data = self._apply_explicit_prompt_name(
                character_data=character_data,
                latest_user_prompt=latest_user_prompt,
            )
        try:
            character = Character(**character_data)
        except ValidationError as exc:
            raise StorageError("Character model output failed schema validation.") from exc

        agent_relationships = self._parse_relationship_drafts(
            data=data,
            new_character_id=character.character_id,
            existing_draft=existing_draft,
            timestamp=timestamp,
        )
        relationship_drafts = self.build_relationship_drafts(
            character=character,
            existing_characters=existing_characters,
            existing_relationships=existing_relationships,
            agent_relationships=agent_relationships,
        )
        character = copy_model(
            character,
            relationship_refs=self._unique_strings(
                [relationship.relationship_id for relationship in relationship_drafts]
            ),
        )
        draft = CurrentCharacterDraft(
            draft_id=existing_draft.draft_id if existing_draft else self._next_draft_id(),
            project_id=current_project_id,
            source_world_canvas_id=world_canvas.world_canvas_id,
            character=character,
            relationship_drafts=relationship_drafts,
            latest_user_prompt=latest_user_prompt,
            status="draft",
            created_at=existing_draft.created_at if existing_draft else timestamp,
            updated_at=timestamp,
        )
        validation = self.validate_character_draft(draft)
        return copy_model(draft, validation_report=validation)

    def _apply_explicit_prompt_name(
        self,
        *,
        character_data: dict[str, Any],
        latest_user_prompt: str,
    ) -> dict[str, Any]:
        explicit_name = self._name_from_prompt(latest_user_prompt)
        if not explicit_name:
            return character_data
        current_name = self._clean_text(str(character_data.get("name") or ""))
        if current_name == explicit_name:
            return character_data
        updated = self._replace_text_value(character_data, current_name, explicit_name)
        if isinstance(updated, dict):
            updated["name"] = explicit_name
            profile = dict(updated.get("profile") or {})
            profile["description"] = self._join_non_empty(
                [
                    f"{explicit_name} 是从用户角色构想中明确提取的角色姓名。",
                    profile.get("description"),
                ],
                separator=" ",
            )
            updated["profile"] = profile
            return updated
        character_data["name"] = explicit_name
        return character_data

    def _revision_name_from_prompt(
        self,
        prompt: str,
        *,
        current_name: str,
    ) -> str:
        text = self._clean_text(prompt)
        escaped_current_name = re.escape(self._clean_text(current_name))
        patterns = [
            r"(?:将|把)?(?:角色的?)?(?:姓名|名字)\s*(?:从\s*[^，,。；;]{1,16}\s*)?(?:改为|修改为|更改为|设为|重命名为)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{2,16})",
        ]
        if escaped_current_name:
            patterns.append(
                rf"(?:将|把)?{escaped_current_name}\s*(?:改名为|重命名为)\s*([A-Za-z0-9_\-\u4e00-\u9fff]{{2,16}})"
            )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            candidate = self._clean_text(match.group(1)).strip("，,。；;：:")
            if self._valid_name_candidate(candidate):
                return candidate
        return ""

    def _replace_text_value(self, value: Any, old_text: str, new_text: str) -> Any:
        if isinstance(value, str):
            return value.replace(old_text, new_text) if old_text else value
        if isinstance(value, list):
            return [self._replace_text_value(item, old_text, new_text) for item in value]
        if isinstance(value, dict):
            return {
                key: self._replace_text_value(item, old_text, new_text)
                for key, item in value.items()
            }
        return value

    def _parse_relationship_drafts(
        self,
        data: dict[str, Any],
        new_character_id: str,
        existing_draft: CurrentCharacterDraft | None,
        timestamp: str,
    ) -> list[Relationship]:
        raw_relationships = data.get("relationship_drafts") or []
        if not isinstance(raw_relationships, list):
            raise StorageError("relationship_drafts must be a list.")
        relationships: list[Relationship] = []
        for index, raw_relationship in enumerate(raw_relationships, start=1):
            if not isinstance(raw_relationship, dict):
                raise StorageError("relationship_drafts items must be objects.")
            relationship_data = dict(raw_relationship)
            relationship_data["project_id"] = self._current_project_id()
            relationship_data["relationship_id"] = (
                relationship_data.get("relationship_id")
                or f"rel_{new_character_id}_{index:03d}"
            )
            relationship_data["status"] = "draft"
            relationship_data["source"] = (
                relationship_data.get("source") or "agent_generated"
            )
            relationship_data["version_id"] = (
                relationship_data.get("version_id") or RELATIONSHIP_VERSION_ID
            )
            relationship_data["created_at"] = relationship_data.get("created_at") or (
                existing_draft.created_at if existing_draft else timestamp
            )
            relationship_data["updated_at"] = timestamp
            try:
                relationships.append(Relationship(**relationship_data))
            except ValidationError as exc:
                raise StorageError("Relationship draft failed schema validation.") from exc
        return relationships

    def _read_current_draft(self) -> CurrentCharacterDraft:
        data = self.store.read(self.current_draft_file)
        try:
            return CurrentCharacterDraft(**data)
        except ValidationError as exc:
            raise StorageError(
                f"JSON schema is invalid: {self.current_draft_file}"
            ) from exc

    def _try_read_current_draft(self) -> CurrentCharacterDraft | None:
        if not self.store.exists(self.current_draft_file):
            return None
        return self._read_current_draft()

    def _read_characters(self) -> list[Character]:
        data = self.repositories.characters.list_all()
        try:
            return [Character(**item) for item in data]
        except (TypeError, ValidationError) as exc:
            raise StorageError("Character repository schema is invalid.") from exc

    def _read_relationships(self) -> list[Relationship]:
        data = self.repositories.relationships.list_all()
        try:
            return [Relationship(**item) for item in data]
        except (TypeError, ValidationError) as exc:
            raise StorageError("Relationship repository schema is invalid.") from exc

    def _read_confirmed_characters(
        self,
        exclude_character_id: str = "",
    ) -> list[Character]:
        return [
            character
            for character in self._read_characters()
            if character.status == "confirmed"
            and character.character_id != exclude_character_id
        ]

    def _read_confirmed_relationships(self) -> list[Relationship]:
        return [
            relationship
            for relationship in self._read_relationships()
            if relationship.status == "confirmed"
        ]

    def _try_load_confirmed_world_canvas_for_validation(
        self,
        blocking_issues: list[str],
    ) -> WorldCanvas | None:
        try:
            return self.load_confirmed_world_canvas()
        except StorageError:
            blocking_issues.append("WorldCanvas.status must be confirmed before Character generation.")
            return None

    def _validate_location_faction_species_refs(
        self,
        character: Character,
        world_canvas: WorldCanvas | None,
        warnings: list[str],
    ) -> None:
        if world_canvas is None:
            return
        location_ids = {
            item.get("location_id")
            for item in world_canvas.locations
            if isinstance(item, dict)
        }
        faction_ids = {
            item.get("faction_id")
            for item in world_canvas.factions
            if isinstance(item, dict)
        }
        species_ids = {
            item.get("species_id")
            for item in world_canvas.species
            if isinstance(item, dict)
        }
        state = character.current_state
        if state.location_id and state.location_id not in location_ids and not self._is_candidate_ref(state.location_id):
            warnings.append("Character.current_state.location_id is not in WorldCanvas.locations.")
        if state.faction_id and state.faction_id not in faction_ids and not self._is_candidate_ref(state.faction_id):
            warnings.append("Character.current_state.faction_id is not in WorldCanvas.factions.")
        if state.species_id and state.species_id not in species_ids and not self._is_candidate_ref(state.species_id):
            warnings.append("Character.current_state.species_id is not in WorldCanvas.species.")

    def _validate_knowledge_boundaries(
        self,
        character: Character,
        world_canvas: WorldCanvas | None,
        blocking_issues: list[str],
        warnings: list[str],
    ) -> None:
        profile = character.profile
        knowledge_text = "\n".join(
            profile.knowledge_scope
            + character.current_state.knowledge
            + [character.current_state.active_goal]
        )
        for forbidden in profile.forbidden_knowledge:
            if not forbidden:
                continue
            forbidden_positive = forbidden.replace("不知道", "知道")
            if forbidden in knowledge_text or forbidden_positive in knowledge_text:
                blocking_issues.append("Character knowledge includes forbidden knowledge.")
                break
        if world_canvas and any(rule.gap_type == "missing_origin" for rule in world_canvas.unknown_rules):
            if "真正来源" in knowledge_text or "真实来源" in knowledge_text:
                warnings.append("Character may know a world-origin fact that is still an unknown rule gap.")
        combined_text = "\n".join(
            [
                profile.background_summary,
                *profile.goals,
                *profile.secrets,
                character.current_state.current_desire,
                character.current_state.active_goal,
            ]
        )
        if world_canvas and "无代价" in combined_text:
            hard_rule_text = "\n".join(rule.statement for rule in world_canvas.hard_rules)
            if "代价" in hard_rule_text:
                blocking_issues.append("Character draft appears to violate a World Canvas hard cost rule.")

    def _validate_world_hard_rules(
        self,
        character: Character,
        world_canvas: WorldCanvas | None,
        blocking_issues: list[str],
        user_confirmation_needed: list[str],
    ) -> None:
        if world_canvas is None:
            return

        character_text = self._collect_character_text(character)
        hard_rule_texts = [rule.statement for rule in world_canvas.hard_rules]
        if not hard_rule_texts:
            return

        issue_count_before = len(blocking_issues)
        if self._has_midnight_only_rule(hard_rule_texts) and self._claims_non_midnight_trigger(character_text):
            blocking_issues.append(
                "Character draft appears to violate a World Canvas hard trigger rule."
            )
        if self._has_no_free_memory_creation_rule(hard_rule_texts) and self._claims_free_memory_creation(character_text):
            blocking_issues.append(
                "Character draft appears to violate a World Canvas hard memory-creation rule."
            )
        if self._has_no_free_memory_reversal_rule(hard_rule_texts) and self._claims_free_memory_reversal(character_text):
            blocking_issues.append(
                "Character draft appears to violate a World Canvas hard memory-reversal rule."
            )
        if self._claims_explicit_hard_rule_override(character_text):
            blocking_issues.append(
                "Character draft explicitly overrides or ignores World Canvas hard rules."
            )

        if len(blocking_issues) > issue_count_before and not user_confirmation_needed:
            user_confirmation_needed.append(
                "请修订角色草案，使其遵守已确认的世界硬规则。"
            )

    def _collect_character_text(self, character: Character) -> str:
        profile = character.profile
        state = character.current_state
        arc = character.arc_state
        baseline = profile.personality_baseline
        parts = [
            character.name,
            character.role,
            profile.description,
            profile.identity,
            profile.story_function,
            profile.background_summary,
            profile.species_or_group,
            profile.faction_or_origin,
            profile.appearance_summary,
            baseline.bottom_line,
            baseline.speech_style_hint,
            state.emotional_state,
            state.active_goal,
            state.current_desire,
            state.current_fear,
            arc.current_arc,
            arc.starting_point,
            arc.pressure,
            arc.inner_conflict,
            arc.next_possible_change,
            arc.possible_direction,
        ]
        list_fields = [
            profile.traits,
            profile.goals,
            profile.fears,
            profile.secrets,
            baseline.traits,
            baseline.values,
            profile.knowledge_scope,
            profile.forbidden_knowledge,
            state.knowledge,
            state.resources,
            state.secrets,
            arc.locked_future_events,
        ]
        for field in list_fields:
            parts.extend(field)
        for limit in profile.hard_limits:
            parts.extend([limit.statement, limit.reason, limit.source])
        return "\n".join(part for part in parts if part)

    def _has_midnight_only_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            any(time_marker in text for time_marker in ["午夜", "零点"])
            and any(limit_marker in text for limit_marker in ["只", "仅", "固定", "每晚"])
            for text in hard_rule_texts
        )

    def _claims_non_midnight_trigger(self, character_text: str) -> bool:
        trigger_markers = ["触发", "鸣响", "钟声", "异常"]
        non_midnight_markers = [
            "随机触发",
            "随时触发",
            "任意时间触发",
            "白天触发",
            "非零点触发",
            "不受时间限制",
            "不需要零点",
            "雨夜触发",
        ]
        return (
            any(marker in character_text for marker in trigger_markers)
            and any(marker in character_text for marker in non_midnight_markers)
        )

    def _has_no_free_memory_creation_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "新记忆" in text
            and any(marker in text for marker in ["不会", "不能", "不允许"])
            for text in hard_rule_texts
        )

    def _claims_free_memory_creation(self, character_text: str) -> bool:
        return any(
            marker in character_text
            for marker in [
                "凭空获得新记忆",
                "凭空创造新记忆",
                "创造新记忆",
                "植入新记忆",
                "生成新记忆",
                "制造新记忆",
            ]
        )

    def _has_no_free_memory_reversal_rule(self, hard_rule_texts: list[str]) -> bool:
        return any(
            "无代价" in text
            and any(marker in text for marker in ["撤销", "恢复", "找回", "记忆"])
            for text in hard_rule_texts
        )

    def _claims_free_memory_reversal(self, character_text: str) -> bool:
        return any(
            marker in character_text
            for marker in [
                "无代价恢复",
                "无代价撤销",
                "直接恢复全部记忆",
                "立刻恢复全部记忆",
                "完全找回记忆且没有代价",
                "不付代价恢复",
            ]
        )

    def _claims_explicit_hard_rule_override(self, character_text: str) -> bool:
        return any(
            marker in character_text
            for marker in [
                "无视世界硬规则",
                "无视硬规则",
                "违反硬规则",
                "不受世界规则限制",
                "不受任何已确认规则限制",
            ]
        )

    def _validate_duplicate_story_function(
        self,
        character: Character,
        warnings: list[str],
        user_confirmation_needed: list[str],
    ) -> None:
        story_function = character.profile.story_function.strip().lower()
        if not story_function:
            return
        duplicates = [
            existing
            for existing in self._read_confirmed_characters(
                exclude_character_id=character.character_id
            )
            if existing.profile.story_function.strip().lower() == story_function
        ]
        if duplicates:
            warnings.append("Character.profile.story_function duplicates an existing confirmed character.")
            user_confirmation_needed.append(
                "请确认这个角色功能重复是有意设计，而不是主角团功能重叠。"
            )

    def _validate_relationship_drafts(
        self,
        draft: CurrentCharacterDraft,
        blocking_issues: list[str],
    ) -> None:
        existing_characters = self._read_confirmed_characters(
            exclude_character_id=draft.character.character_id
        )
        if existing_characters and not draft.relationship_drafts:
            blocking_issues.append(
                "Second and later characters must include at least one relationship draft."
            )
            return

        valid_ids = {draft.character.character_id} | {
            character.character_id for character in existing_characters
        }
        for relationship in draft.relationship_drafts:
            if relationship.source_id not in valid_ids or relationship.target_id not in valid_ids:
                blocking_issues.append("Relationship source_id/target_id must point to the new or confirmed characters.")
            if draft.character.character_id not in {relationship.source_id, relationship.target_id}:
                blocking_issues.append("Relationship draft must involve the current new character.")
            if relationship.source_id == relationship.target_id:
                blocking_issues.append("Relationship source_id and target_id must be different.")

    def _validate_future_locking(
        self,
        character: Character,
        blocking_issues: list[str],
        user_confirmation_needed: list[str],
    ) -> None:
        arc = character.arc_state
        future_text = "\n".join(
            [
                arc.current_arc,
                arc.next_possible_change,
                arc.possible_direction,
                *arc.locked_future_events,
            ]
        )
        lock_markers = [
            "必定死亡",
            "必然死亡",
            "固定死亡",
            "必定背叛",
            "固定背叛",
            "结局必定",
            "锁定结局",
            "must die",
            "fixed ending",
            "locked ending",
        ]
        if any(marker in future_text for marker in lock_markers) or arc.locked_future_events:
            blocking_issues.append("Character arc must not lock deaths, betrayals, endings, or fixed future events.")
            user_confirmation_needed.append("请改为可能方向，不要把未来章节事件写成既定事实。")

    def _relationship_touches_new_and_existing(
        self,
        relationship: Relationship,
        new_character_id: str,
        existing_ids: set[str],
    ) -> bool:
        endpoints = {relationship.source_id, relationship.target_id}
        return new_character_id in endpoints and bool(endpoints & existing_ids)

    def _relationship_pair_exists(
        self,
        source_id: str,
        target_id: str,
        relationships: list[Relationship],
    ) -> bool:
        desired_pair = {source_id, target_id}
        return any(
            {relationship.source_id, relationship.target_id} == desired_pair
            for relationship in relationships
        )

    def _dedupe_relationships(
        self,
        relationships: list[Relationship],
    ) -> list[Relationship]:
        seen: set[str] = set()
        deduped: list[Relationship] = []
        for relationship in relationships:
            if relationship.relationship_id in seen:
                continue
            seen.add(relationship.relationship_id)
            deduped.append(relationship)
        return deduped

    def _upsert_character(
        self,
        characters: list[Character],
        character: Character,
    ) -> list[Character]:
        updated = []
        replaced = False
        for existing in characters:
            if existing.character_id == character.character_id:
                updated.append(character)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(character)
        return updated

    def _upsert_relationship(
        self,
        relationships: list[Relationship],
        relationship: Relationship,
    ) -> list[Relationship]:
        updated = []
        replaced = False
        for existing in relationships:
            if existing.relationship_id == relationship.relationship_id:
                updated.append(relationship)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(relationship)
        return updated

    def _attach_relationship_refs(
        self,
        characters: list[Character],
        relationships: list[Relationship],
    ) -> list[Character]:
        relationship_refs_by_character: dict[str, list[str]] = {}
        for relationship in relationships:
            relationship_refs_by_character.setdefault(
                relationship.source_id,
                [],
            ).append(relationship.relationship_id)
            relationship_refs_by_character.setdefault(
                relationship.target_id,
                [],
            ).append(relationship.relationship_id)
        updated: list[Character] = []
        for character in characters:
            extra_refs = relationship_refs_by_character.get(character.character_id, [])
            if not extra_refs:
                updated.append(character)
                continue
            updated.append(
                copy_model(
                    character,
                    relationship_refs=self._unique_strings(
                        character.relationship_refs + extra_refs
                    ),
                    updated_at=character.updated_at or now_iso(),
                )
            )
        return updated

    def _append_decision(
        self,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self._read_decisions()
        prefix = (
            "decision_character_confirm"
            if target_type == "character"
            else "decision_main_cast_finish"
        )
        decision = Decision(
            decision_id=f"{prefix}_{len(decisions) + 1:03d}",
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.store.write(self.decisions_file, decisions)
        return decision

    def _read_decisions(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        decisions = self.store.read_list(self.decisions_file)
        return [dict(item) for item in decisions if isinstance(item, dict)]

    def _is_main_cast_finished(self) -> bool:
        if self.store.exists(self.project_file):
            project = self.store.read(self.project_file)
            for value in (
                str(project.get("current_step") or ""),
                str(project.get("status") or ""),
            ):
                if self._is_post_main_cast_step(value):
                    return True
        return any(
            decision.get("decision_type") == "confirm"
            and decision.get("target_type") == "main_cast"
            for decision in self._read_decisions()
        )

    def _is_post_main_cast_step(self, step: str) -> bool:
        return step in POST_MAIN_CAST_STEPS or bool(
            POST_MAIN_CAST_SCENE_STEP_RE.match(step or "")
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

    def _confirmed_a_tier_count(self, characters: list[Character]) -> int:
        return len(
            [
                character
                for character in characters
                if character.tier == "A" and character.status == "confirmed"
            ]
        )

    def _resolve_character_id(
        self,
        candidate_id: str,
        existing_ids: set[str],
        preserved_id: str = "",
    ) -> str:
        if preserved_id:
            return preserved_id
        base_id = candidate_id or f"char_m5_{len(existing_ids) + 1:03d}"
        if base_id not in existing_ids:
            return base_id
        index = 2
        while f"{base_id}_{index:03d}" in existing_ids:
            index += 1
        return f"{base_id}_{index:03d}"

    def _next_draft_id(self) -> str:
        if not self.store.exists(self.current_draft_file):
            return "character_draft_001"
        try:
            existing = self._read_current_draft()
        except StorageError:
            return "character_draft_001"
        digits = "".join(ch for ch in existing.draft_id if ch.isdigit())
        next_number = int(digits or "0") + 1
        return f"character_draft_{next_number:03d}"

    def _relationship_id(self, source_id: str, target_id: str) -> str:
        return f"rel_{source_id}_{target_id}"

    def _is_candidate_ref(self, value: str) -> bool:
        return value.startswith(("new_", "candidate_", "draft_"))

    def _unique_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
