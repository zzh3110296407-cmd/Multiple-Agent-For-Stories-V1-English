import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.agents.role_generation_agent import RoleGenerationAgent
from app.backend.core.config import settings
from app.backend.models.character import (
    Character,
    CharacterArcState,
    CharacterContextBudget,
    CharacterCurrentState,
    CharacterHardLimit,
    CharacterMemorySummary,
    CharacterPersonalityBaseline,
    CharacterProfile,
)
from app.backend.models.character_workflow import CharacterValidationReport
from app.backend.models.decision import Decision
from app.backend.models.role_generation import (
    CurrentRoleDraft,
    RoleComplexityProfile,
    RoleGenerationResponse,
)
from app.backend.models.world_canvas import WorldCanvas
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.character_prompt_fidelity_service import (
    ROLE_GENERATION_PROJECT_STORY_PREMISE_MISSING,
    project_requires_story_premise,
    require_project_story_premise_for_generation,
    try_read_project_story_premise,
    validate_character_prompt_absorption,
)
from app.backend.services.character_service import LOCAL_PROJECT_ID, now_iso
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelConfigurationError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.role_tier_budget_service import RoleTierBudgetService
from app.backend.storage.json_store import JsonStore, StorageError


ROLE_GENERATION_VERSION_ID = "phase85_role_generation_v1"
ROLE_GENERATION_MODEL_CALL_FALLBACK_WARNING = (
    "role_generation_model_call_failed_used_deterministic_fallback"
)
ROLE_GENERATION_MODEL_JSON_FALLBACK_WARNING = (
    "role_generation_model_json_failed_used_deterministic_fallback"
)


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def copy_model(model: BaseModel, **updates: Any):
    if hasattr(model, "model_copy"):
        return model.model_copy(update=updates, deep=True)
    return model.copy(update=updates, deep=True)


class RoleGenerationService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        agent: RoleGenerationAgent | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.project_file = self.data_dir / "project.json"
        self.current_role_draft_file = self.data_dir / "current_role_draft.json"
        self.agent = agent or RoleGenerationAgent(
            model_gateway=ModelGatewayService(store=self.store, data_dir=self.data_dir)
        )
        self.budget_service = RoleTierBudgetService()

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_draft(self) -> RoleGenerationResponse:
        draft = self._try_read_current_draft()
        return RoleGenerationResponse(
            draft=draft,
            roles=self._read_characters(),
            validation=draft.validation_report if draft else None,
        )

    def generate_role_draft(
        self,
        *,
        user_prompt: str,
        target_tier: str,
        role_hint: str | None = None,
        story_function_hint: str | None = None,
    ) -> RoleGenerationResponse:
        clean_prompt = user_prompt.strip()
        if not clean_prompt:
            raise StorageError("ROLE_GENERATION_PROMPT_REQUIRED")
        tier = str(target_tier or "").upper()
        if tier == "A":
            raise StorageError("USE_CHARACTER_MAIN_CAST_GENERATOR_FOR_A_TIER")
        if tier not in {"B", "C", "D"}:
            raise StorageError("ROLE_GENERATION_INVALID_TARGET_TIER")

        world_canvas = self._read_confirmed_world_canvas()
        existing_characters = [
            character
            for character in self._read_characters()
            if character.status == "confirmed"
        ]
        project_story_premise = require_project_story_premise_for_generation(
            store=self.store,
            data_dir=self.data_dir,
            project_id=self._current_project_id(),
            missing_code=ROLE_GENERATION_PROJECT_STORY_PREMISE_MISSING,
            project_file=self.project_file,
        )
        same_tier_characters = [
            character for character in existing_characters if character.tier == tier
        ]
        complexity_profile = self._complexity_profile(tier)
        fallback_warning = ""
        try:
            agent_data = self.agent.generate_role(
                world_canvas=world_canvas,
                existing_characters=existing_characters,
                user_prompt=clean_prompt,
                target_tier=tier,
                complexity_profile=complexity_profile,
                role_hint=role_hint or "",
                story_function_hint=story_function_hint or "",
                project_story_premise=project_story_premise,
                same_tier_characters=same_tier_characters,
            )
        except (ModelConfigurationError, ModelCallError, ModelJsonParseError) as exc:
            fallback_warning = ROLE_GENERATION_MODEL_CALL_FALLBACK_WARNING
            if isinstance(exc, ModelJsonParseError):
                fallback_warning = ROLE_GENERATION_MODEL_JSON_FALLBACK_WARNING
            agent_data = {
                "character": self._fallback_role_payload(
                    target_tier=tier,
                    user_prompt=clean_prompt,
                    role_hint=role_hint or "",
                    story_function_hint=story_function_hint or "",
                )
            }
        role = self._build_role(
            agent_data=agent_data,
            target_tier=tier,
            user_prompt=clean_prompt,
            role_hint=role_hint or "",
            story_function_hint=story_function_hint or "",
        )
        validation = self._validate_role_draft(role, latest_user_prompt=clean_prompt)
        validation = self._validation_with_fallback_warning(
            validation,
            fallback_warning,
        )
        timestamp = now_iso()
        draft = CurrentRoleDraft(
            draft_id=self._next_draft_id(),
            project_id=self._current_project_id(),
            source_world_canvas_id=world_canvas.world_canvas_id,
            role=role,
            complexity_profile=complexity_profile,
            validation_report=validation,
            latest_user_prompt=clean_prompt,
            status="draft",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._write_current_draft(draft)
        return RoleGenerationResponse(
            draft=draft,
            roles=self._read_characters(),
            validation=validation,
        )

    def confirm_current_draft(self, user_input: str = "") -> RoleGenerationResponse:
        draft = self._read_current_draft()
        if draft.status != "draft" or draft.role.status != "draft":
            raise StorageError("ROLE_GENERATION_DRAFT_NOT_CONFIRMABLE")
        validation = self._validate_role_draft(
            draft.role,
            latest_user_prompt=draft.latest_user_prompt,
        )
        if validation.blocking_issues:
            raise StorageError("ROLE_GENERATION_DRAFT_HAS_BLOCKING_ISSUES")
        timestamp = now_iso()
        role = copy_model(
            draft.role,
            status="confirmed",
            source="role_generation",
            updated_at=timestamp,
        )
        characters = self._read_characters()
        characters.append(role)
        self._write_characters(characters)
        decision = self._append_decision(
            decision_type="confirm_generated_role",
            target_type="role",
            target_id=role.character_id,
            user_input=user_input or f"确认生成的 {role.tier}-tier 角色：{role.name}",
        )
        self._clear_current_draft()
        return RoleGenerationResponse(
            draft=None,
            roles=self._read_characters(),
            validation=validation,
            decision=decision,
            cleared=True,
        )

    def clear_current_draft(self) -> RoleGenerationResponse:
        self._clear_current_draft()
        return RoleGenerationResponse(
            draft=None,
            roles=self._read_characters(),
            cleared=True,
        )

    def _build_role(
        self,
        *,
        agent_data: dict[str, Any],
        target_tier: str,
        user_prompt: str,
        role_hint: str,
        story_function_hint: str,
    ) -> Character:
        raw = self._normalize_agent_role_payload(
            agent_data=agent_data,
            target_tier=target_tier,
            user_prompt=user_prompt,
            role_hint=role_hint,
            story_function_hint=story_function_hint,
        )
        try:
            role = Character(**raw)
        except ValidationError:
            raw = self._fallback_role_payload(
                target_tier=target_tier,
                user_prompt=user_prompt,
                role_hint=role_hint,
                story_function_hint=story_function_hint,
            )
            try:
                role = Character(**raw)
            except ValidationError as exc:
                raise StorageError("ROLE_GENERATION_AGENT_OUTPUT_INVALID") from exc
        return self._normalize_complexity(role, target_tier)

    def _normalize_agent_role_payload(
        self,
        *,
        agent_data: dict[str, Any],
        target_tier: str,
        user_prompt: str,
        role_hint: str,
        story_function_hint: str,
    ) -> dict[str, Any]:
        raw = self._extract_character_payload(agent_data)
        raw["project_id"] = self._current_project_id()
        raw["character_id"] = self._resolve_character_id(
            str(raw.get("character_id") or ""),
            target_tier,
        )
        raw["tier"] = target_tier
        raw["role"] = str(raw.get("role") or role_hint or "supporting_npc")
        raw["name"] = self._clean_text(
            raw.get("name")
            or self._name_from_prompt(user_prompt)
            or self._fallback_name(target_tier)
        )
        raw["status"] = "draft"
        raw["source"] = "role_generation"
        raw["version_id"] = ROLE_GENERATION_VERSION_ID
        raw["profile"] = self._normalize_profile_payload(
            raw=raw,
            target_tier=target_tier,
            user_prompt=user_prompt,
            story_function_hint=story_function_hint,
        )
        raw["current_state"] = self._normalize_current_state_payload(
            raw=raw,
            target_tier=target_tier,
        )
        raw["arc_state"] = self._normalize_arc_state_payload(raw, target_tier)
        raw["memory_summary"] = self._normalize_memory_summary_payload(
            raw=raw,
            target_tier=target_tier,
        )
        raw["context_budget"] = model_to_dict(
            self.budget_service.default_budgets()[target_tier]
        )
        raw["relationship_refs"] = self._coerce_ref_list(raw.get("relationship_refs"))
        raw["event_refs"] = self._coerce_ref_list(raw.get("event_refs"))
        raw["created_at"] = self._clean_text(raw.get("created_at"))
        raw["updated_at"] = self._clean_text(raw.get("updated_at"))
        raw["archived_at"] = ""
        return raw

    def _extract_character_payload(self, agent_data: dict[str, Any]) -> dict[str, Any]:
        character = agent_data.get("character") if isinstance(agent_data, dict) else None
        if isinstance(character, Mapping):
            return dict(character)
        if isinstance(agent_data, Mapping):
            character_keys = {
                "character_id",
                "name",
                "tier",
                "role",
                "profile",
                "identity",
                "description",
                "current_state",
                "arc_state",
            }
            if any(key in agent_data for key in character_keys):
                return dict(agent_data)
        return {}

    def _fallback_role_payload(
        self,
        *,
        target_tier: str,
        user_prompt: str,
        role_hint: str,
        story_function_hint: str,
    ) -> dict[str, Any]:
        name = (
            self._name_from_prompt(user_prompt)
            or self._clean_text(role_hint)
            or self._fallback_name(target_tier)
        )
        description = self._fallback_description(target_tier, user_prompt)
        profile = {
            "description": description,
            "identity": self._fallback_identity(target_tier, role_hint),
            "story_function": story_function_hint or role_hint or "有限辅助功能",
            "background_summary": self._limit_text(user_prompt, 160),
            "species_or_group": "",
            "faction_or_origin": "",
            "appearance_summary": "",
            "traits": self._fallback_traits(target_tier),
            "goals": [self._fallback_goal(target_tier, story_function_hint)],
            "fears": ["被迫承担超过当前层级的信息量"] if target_tier != "D" else [],
            "secrets": [],
            "personality_baseline": {
                "traits": self._fallback_traits(target_tier),
                "values": ["保留可核验证据"] if target_tier in {"B", "C"} else [],
                "bottom_line": "不主动伪造关键线索。" if target_tier != "D" else "",
                "speech_style_hint": "简短、贴近现场事实。",
            },
            "hard_limits": [],
            "knowledge_scope": [self._fallback_knowledge_scope(target_tier)],
            "forbidden_knowledge": [],
        }
        return {
            "character_id": self._resolve_character_id("", target_tier),
            "project_id": self._current_project_id(),
            "name": name,
            "tier": target_tier,
            "role": role_hint or "supporting_npc",
            "profile": profile,
            "current_state": {
                "location_id": "",
                "faction_id": "",
                "species_id": "",
                "emotional_state": "等待进入当前场景",
                "knowledge": profile["knowledge_scope"][:1],
                "active_goal": self._fallback_goal(target_tier, story_function_hint),
                "current_desire": "" if target_tier == "D" else "完成有限叙事功能",
                "current_fear": "",
                "resources": [],
                "secrets": [],
            },
            "arc_state": {
                "current_arc": "" if target_tier in {"C", "D"} else "支线角色的轻量变化",
                "starting_point": "",
                "pressure": "只承受当前章节压力" if target_tier == "C" else "",
                "inner_conflict": "",
                "next_possible_change": "",
                "possible_direction": "",
                "locked_future_events": [],
            },
            "relationship_refs": [],
            "event_refs": [],
            "memory_summary": {
                "summary": f"{name}由角色生成器根据用户输入创建，后续按{target_tier}级记忆预算记录。",
                "key_memory_ids": [],
                "open_threads": [],
                "last_updated_event_id": "",
            },
            "context_budget": model_to_dict(
                self.budget_service.default_budgets()[target_tier]
            ),
            "status": "draft",
            "source": "role_generation",
            "version_id": ROLE_GENERATION_VERSION_ID,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "archived_at": "",
        }

    def _normalize_profile_payload(
        self,
        *,
        raw: dict[str, Any],
        target_tier: str,
        user_prompt: str,
        story_function_hint: str,
    ) -> dict[str, Any]:
        profile = self._coerce_dict(raw.get("profile"))
        if story_function_hint and not profile.get("story_function"):
            profile["story_function"] = story_function_hint
        traits = self._coerce_string_list(
            profile.get("traits") or raw.get("traits"),
            fallback=self._fallback_traits(target_tier),
        )
        personality = self._coerce_dict(profile.get("personality_baseline"))
        return {
            "description": self._clean_text(
                profile.get("description")
                or raw.get("description")
                or self._fallback_description(target_tier, user_prompt)
            ),
            "identity": self._clean_text(
                profile.get("identity")
                or raw.get("identity")
                or self._fallback_identity(target_tier, raw.get("role"))
            ),
            "story_function": self._clean_text(
                profile.get("story_function")
                or raw.get("story_function")
                or story_function_hint
                or raw.get("role")
                or "有限辅助功能"
            ),
            "background_summary": self._clean_text(
                profile.get("background_summary")
                or raw.get("background")
                or raw.get("background_summary")
                or self._limit_text(user_prompt, 180)
            ),
            "species_or_group": self._clean_text(profile.get("species_or_group")),
            "faction_or_origin": self._clean_text(
                profile.get("faction_or_origin")
                or raw.get("faction_or_origin")
                or raw.get("origin")
            ),
            "appearance_summary": self._clean_text(profile.get("appearance_summary")),
            "traits": traits,
            "goals": self._coerce_string_list(
                profile.get("goals") or raw.get("goals") or raw.get("goal"),
                fallback=[self._fallback_goal(target_tier, raw.get("story_function"))],
            ),
            "fears": self._coerce_string_list(profile.get("fears") or raw.get("fears")),
            "secrets": self._coerce_string_list(
                profile.get("secrets") or raw.get("secrets")
            ),
            "personality_baseline": {
                "traits": self._coerce_string_list(
                    personality.get("traits"),
                    fallback=traits,
                ),
                "values": self._coerce_string_list(personality.get("values")),
                "bottom_line": self._clean_text(personality.get("bottom_line")),
                "speech_style_hint": self._clean_text(
                    personality.get("speech_style_hint")
                    or raw.get("speech_style_hint")
                ),
            },
            "hard_limits": self._coerce_hard_limits(
                profile.get("hard_limits") or raw.get("hard_limits")
            ),
            "knowledge_scope": self._coerce_string_list(
                profile.get("knowledge_scope") or raw.get("knowledge_scope"),
                fallback=[self._fallback_knowledge_scope(target_tier)],
            ),
            "forbidden_knowledge": self._coerce_string_list(
                profile.get("forbidden_knowledge") or raw.get("forbidden_knowledge")
            ),
        }

    def _normalize_current_state_payload(
        self,
        *,
        raw: dict[str, Any],
        target_tier: str,
    ) -> dict[str, Any]:
        state = self._coerce_dict(raw.get("current_state"))
        return {
            "location_id": self._clean_text(state.get("location_id")),
            "faction_id": self._clean_text(state.get("faction_id")),
            "species_id": self._clean_text(state.get("species_id")),
            "emotional_state": self._clean_text(
                state.get("emotional_state")
                or raw.get("emotional_state")
                or "等待进入当前场景"
            ),
            "knowledge": self._coerce_string_list(
                state.get("knowledge") or raw.get("knowledge")
            ),
            "active_goal": self._clean_text(
                state.get("active_goal")
                or state.get("current_goal")
                or raw.get("active_goal")
                or raw.get("current_goal")
                or raw.get("goal")
                or self._fallback_goal(target_tier, raw.get("story_function"))
            ),
            "current_desire": self._clean_text(
                state.get("current_desire") or raw.get("current_desire")
            ),
            "current_fear": self._clean_text(
                state.get("current_fear") or raw.get("current_fear")
            ),
            "resources": self._coerce_string_list(
                state.get("resources") or raw.get("resources")
            ),
            "secrets": self._coerce_string_list(
                state.get("secrets") or raw.get("state_secrets")
            ),
        }

    def _normalize_arc_state_payload(
        self,
        raw: dict[str, Any],
        target_tier: str,
    ) -> dict[str, Any]:
        arc = self._coerce_dict(raw.get("arc_state"))
        return {
            "current_arc": self._clean_text(
                arc.get("current_arc")
                or raw.get("arc")
                or ("" if target_tier in {"C", "D"} else "轻量支线变化")
            ),
            "starting_point": self._clean_text(arc.get("starting_point")),
            "pressure": self._clean_text(
                arc.get("pressure")
                or raw.get("pressure")
                or ("只承受当前章节压力" if target_tier == "C" else "")
            ),
            "inner_conflict": self._clean_text(
                arc.get("inner_conflict") or raw.get("inner_conflict")
            ),
            "next_possible_change": self._clean_text(arc.get("next_possible_change")),
            "possible_direction": self._clean_text(arc.get("possible_direction")),
            "locked_future_events": self._coerce_string_list(
                arc.get("locked_future_events")
            ),
        }

    def _normalize_memory_summary_payload(
        self,
        *,
        raw: dict[str, Any],
        target_tier: str,
    ) -> dict[str, Any]:
        memory = self._coerce_dict(raw.get("memory_summary"))
        name = self._clean_text(raw.get("name")) or self._fallback_name(target_tier)
        return {
            "summary": self._clean_text(
                memory.get("summary")
                or raw.get("memory_summary")
                or f"{name}按{target_tier}级记忆预算持久记录。"
            ),
            "key_memory_ids": self._coerce_ref_list(memory.get("key_memory_ids")),
            "open_threads": self._coerce_string_list(memory.get("open_threads")),
            "last_updated_event_id": self._clean_text(
                memory.get("last_updated_event_id")
            ),
        }

    def _coerce_dict(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def _coerce_string_list(
        self,
        value: Any,
        *,
        fallback: list[str] | None = None,
    ) -> list[str]:
        if value is None or value == "":
            return list(fallback or [])
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            values = [value]
        result: list[str] = []
        for item in values:
            if isinstance(item, Mapping):
                item = (
                    item.get("summary")
                    or item.get("statement")
                    or item.get("description")
                    or item.get("name")
                    or item.get("value")
                    or item.get("text")
                    or ""
                )
            clean = self._clean_text(item)
            if clean:
                result.append(clean)
        return result or list(fallback or [])

    def _coerce_ref_list(self, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        values = value if isinstance(value, list) else [value]
        refs: list[str] = []
        for item in values:
            if isinstance(item, Mapping):
                item = (
                    item.get("relationship_id")
                    or item.get("event_id")
                    or item.get("memory_id")
                    or item.get("character_id")
                    or item.get("id")
                    or ""
                )
            clean = self._clean_text(item)
            if clean:
                refs.append(clean)
        return refs

    def _coerce_hard_limits(self, value: Any) -> list[dict[str, Any]]:
        limits: list[dict[str, Any]] = []
        for index, item in enumerate(
            self._coerce_list(value),
            start=1,
        ):
            if isinstance(item, Mapping):
                statement = self._clean_text(
                    item.get("statement")
                    or item.get("limit")
                    or item.get("description")
                    or item.get("text")
                    or item.get("summary")
                )
                reason = self._clean_text(item.get("reason"))
                source = self._clean_text(item.get("source")) or "agent_generated"
                limit_id = self._clean_text(item.get("limit_id"))
            else:
                statement = self._clean_text(item)
                reason = ""
                source = "agent_generated"
                limit_id = ""
            if statement:
                limits.append(
                    {
                        "limit_id": limit_id or f"limit_role_generated_{index:03d}",
                        "statement": statement,
                        "reason": reason,
                        "source": source,
                    }
                )
        return limits

    def _coerce_list(self, value: Any) -> list[Any]:
        if value is None or value == "":
            return []
        return value if isinstance(value, list) else [value]

    def _clean_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            return "；".join(
                self._clean_text(item)
                for item in value
                if self._clean_text(item)
            )
        if isinstance(value, Mapping):
            for key in ("summary", "statement", "description", "name", "value", "text"):
                if key in value:
                    return self._clean_text(value.get(key))
            return ""
        return str(value).strip()

    def _name_from_prompt(self, user_prompt: str) -> str:
        prompt = user_prompt.strip()
        patterns = [
            r"(?:角色|名叫|叫|名称|名字)[:：\s]*([A-Za-z0-9_\-\u4e00-\u9fff]{2,12})",
            r"([A-Za-z0-9_\-\u4e00-\u9fff]{2,8})[:：]",
        ]
        stop_words = {"生成", "创建", "一个", "一位", "角色", "章节角色", "场景角色"}
        for pattern in patterns:
            match = re.search(pattern, prompt)
            if not match:
                continue
            candidate = match.group(1).strip("_- ")
            if candidate and candidate not in stop_words:
                return candidate
        return ""

    def _limit_text(self, value: str, limit: int) -> str:
        clean = str(value or "").strip()
        return clean[:limit]

    def _fallback_description(self, tier: str, user_prompt: str) -> str:
        prompt = self._limit_text(user_prompt, 120)
        if tier == "B":
            return f"围绕主线提供阶段性推动的 B 级角色。{prompt}"
        if tier == "C":
            return f"服务当前章节线索和场景判断的 C 级角色。{prompt}"
        return f"服务单幕现场功能的 D 级角色。{prompt}"

    def _fallback_identity(self, tier: str, role_hint: Any) -> str:
        hint = self._clean_text(role_hint)
        if hint:
            return hint
        return {
            "B": "支线辅助角色",
            "C": "章节局部角色",
            "D": "场景局部角色",
        }.get(tier, "辅助角色")

    def _fallback_traits(self, tier: str) -> list[str]:
        if tier == "B":
            return ["可靠", "保留判断", "掌握局部资源"]
        if tier == "C":
            return ["熟悉现场", "信息有限"]
        return ["现场反应明确"]

    def _fallback_goal(self, tier: str, story_function_hint: Any) -> str:
        hint = self._clean_text(story_function_hint)
        if hint:
            return hint
        return {
            "B": "推动一条支线线索进入主线判断",
            "C": "在当前章节提供可核验的局部信息",
            "D": "在当前场景完成一个明确现场功能",
        }.get(tier, "完成辅助叙事功能")

    def _fallback_knowledge_scope(self, tier: str) -> str:
        return {
            "B": "知道与自身支线功能有关的有限事实",
            "C": "只知道当前章节所需的局部事实",
            "D": "只知道当前场景可观察到的事实",
        }.get(tier, "知道有限事实")

    def _normalize_complexity(self, role: Character, tier: str) -> Character:
        profile = role.profile
        state = role.current_state
        arc = role.arc_state
        budget = self.budget_service.default_budgets()[tier]
        if tier == "B":
            profile = copy_model(
                profile,
                traits=self._limit_strings(profile.traits, 5),
                goals=self._limit_strings(profile.goals, 3),
                fears=self._limit_strings(profile.fears, 3),
                secrets=self._limit_strings(profile.secrets, 3),
                hard_limits=self._limit_hard_limits(profile.hard_limits, 2),
                forbidden_knowledge=self._limit_strings(profile.forbidden_knowledge, 2),
                knowledge_scope=self._limit_strings(profile.knowledge_scope, 4),
            )
            arc = copy_model(arc, locked_future_events=[])
        elif tier == "C":
            profile = copy_model(
                profile,
                traits=self._limit_strings(profile.traits, 3),
                goals=self._limit_strings(profile.goals, 1),
                fears=self._limit_strings(profile.fears, 1),
                secrets=[],
                hard_limits=self._limit_hard_limits(profile.hard_limits, 1),
                forbidden_knowledge=self._limit_strings(profile.forbidden_knowledge, 1),
                knowledge_scope=self._limit_strings(profile.knowledge_scope, 2),
            )
            state = copy_model(
                state,
                knowledge=self._limit_strings(state.knowledge, 2),
                resources=self._limit_strings(state.resources, 1),
                secrets=[],
            )
            arc = CharacterArcState(pressure=arc.pressure)
        else:
            profile = copy_model(
                profile,
                traits=self._limit_strings(profile.traits, 2),
                goals=self._limit_strings(profile.goals, 1),
                fears=[],
                secrets=[],
                personality_baseline=CharacterPersonalityBaseline(
                    traits=self._limit_strings(
                        profile.personality_baseline.traits or profile.traits,
                        2,
                    ),
                    speech_style_hint=profile.personality_baseline.speech_style_hint,
                ),
                hard_limits=[],
                forbidden_knowledge=[],
                knowledge_scope=self._limit_strings(profile.knowledge_scope, 1),
            )
            state = copy_model(
                state,
                knowledge=self._limit_strings(state.knowledge, 1),
                current_desire="",
                current_fear="",
                resources=[],
                secrets=[],
            )
            arc = CharacterArcState()

        return copy_model(
            role,
            tier=tier,
            profile=profile,
            current_state=state,
            arc_state=arc,
            relationship_refs=[],
            context_budget=CharacterContextBudget(**model_to_dict(budget)),
            status="draft",
            source="role_generation",
            version_id=ROLE_GENERATION_VERSION_ID,
            created_at=role.created_at or now_iso(),
            updated_at=now_iso(),
        )

    def _validate_role_draft(
        self,
        role: Character,
        latest_user_prompt: str = "",
    ) -> CharacterValidationReport:
        blocking_issues: list[str] = []
        warnings: list[str] = []
        if role.project_id != self._current_project_id():
            blocking_issues.append("Generated role project_id must match active project.")
        if role.tier not in {"B", "C", "D"}:
            blocking_issues.append("Generated role tier must be B, C, or D.")
        if role.status != "draft":
            blocking_issues.append("Generated role draft status must be draft.")
        if not role.name.strip():
            blocking_issues.append("Generated role name is required.")
        if role.tier == "D":
            if role.arc_state.current_arc or role.arc_state.inner_conflict:
                warnings.append("D-tier role arc fields were minimized by backend policy.")
            if role.relationship_refs:
                blocking_issues.append("D-tier generated role must not carry relationship refs.")
        project_id = self._current_project_id()
        premise = try_read_project_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
        )
        if premise or project_requires_story_premise(
            store=self.store,
            data_dir=self.data_dir,
            project_id=project_id,
            project_file=self.project_file,
        ):
            m3_blocking, m3_warnings, _coverage = validate_character_prompt_absorption(
                character=role,
                requested_tier=role.tier,
                existing_characters=[
                    character
                    for character in self._read_characters()
                    if character.status == "confirmed"
                    and character.character_id != role.character_id
                ],
                premise=premise,
                latest_user_prompt=latest_user_prompt,
                issue_prefix="role_generation",
            )
            blocking_issues.extend(m3_blocking)
            warnings.extend(m3_warnings)
        return CharacterValidationReport(
            passed=not blocking_issues,
            warnings=warnings,
            blocking_issues=blocking_issues,
            user_confirmation_needed=[],
        )

    def _validation_with_fallback_warning(
        self,
        validation: CharacterValidationReport,
        warning_code: str,
    ) -> CharacterValidationReport:
        if not warning_code:
            return validation
        warnings = list(validation.warnings)
        if warning_code not in warnings:
            warnings.append(warning_code)
        return copy_model(validation, warnings=warnings)

    def _read_confirmed_world_canvas(self) -> WorldCanvas:
        if not self.store.exists(self.world_canvas_file):
            raise StorageError("WORLD_CANVAS_NOT_CONFIRMED")
        world_canvas = WorldCanvas(**self.store.read(self.world_canvas_file))
        if world_canvas.status != "confirmed":
            raise StorageError("WORLD_CANVAS_NOT_CONFIRMED")
        if world_canvas.project_id != self._current_project_id():
            raise StorageError("WORLD_CANVAS_PROJECT_MISMATCH")
        return world_canvas

    def _read_characters(self) -> list[Character]:
        try:
            return [
                Character(**item)
                for item in self.repositories.characters.list_all()
                if isinstance(item, dict)
            ]
        except (TypeError, ValidationError) as exc:
            raise StorageError("ROLE_GENERATION_CHARACTERS_INVALID") from exc

    def _write_characters(self, characters: list[Character]) -> None:
        self.repositories.characters.write_all(
            [model_to_dict(character) for character in characters],
        )

    def _read_current_draft(self) -> CurrentRoleDraft:
        return CurrentRoleDraft(**self.store.read(self.current_role_draft_file))

    def _try_read_current_draft(self) -> CurrentRoleDraft | None:
        if not self.store.exists(self.current_role_draft_file):
            return None
        return self._read_current_draft()

    def _write_current_draft(self, draft: CurrentRoleDraft) -> None:
        self.store.write(self.current_role_draft_file, model_to_dict(draft))

    def _clear_current_draft(self) -> None:
        if self.current_role_draft_file.exists():
            self.current_role_draft_file.unlink()

    def _append_decision(
        self,
        *,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> Decision:
        decisions = self.repositories.decisions.list_all()
        decision = Decision(
            decision_id=f"decision_{target_type}_{target_id}_{uuid4().hex[:8]}",
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            user_input=user_input,
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.repositories.decisions.write_all(decisions)
        return decision

    def _resolve_character_id(self, candidate_id: str, tier: str) -> str:
        existing_ids = {character.character_id for character in self._read_characters()}
        clean = "".join(
            character if character.isalnum() or character in {"_", "-"} else "_"
            for character in candidate_id.strip()
        ).strip("_")
        if not clean or clean in existing_ids:
            clean = f"char_{tier.lower()}_{uuid4().hex[:8]}"
        return clean

    def _next_draft_id(self) -> str:
        existing = self._try_read_current_draft()
        if not existing:
            return "role_draft_001"
        digits = "".join(ch for ch in existing.draft_id if ch.isdigit())
        return f"role_draft_{int(digits or '0') + 1:03d}"

    def _complexity_profile(self, tier: str) -> RoleComplexityProfile:
        if tier == "B":
            return RoleComplexityProfile(
                tier=tier,
                profile_depth="medium",
                relationship_depth="limited",
                arc_depth="light",
            )
        if tier == "C":
            return RoleComplexityProfile(
                tier=tier,
                profile_depth="short",
                relationship_depth="optional",
                arc_depth="minimal",
            )
        return RoleComplexityProfile(
            tier=tier,
            profile_depth="minimal",
            relationship_depth="none",
            arc_depth="none",
        )

    def _fallback_name(self, tier: str) -> str:
        return {
            "B": "支线角色",
            "C": "章节角色",
            "D": "场景角色",
        }.get(tier, "角色")

    def _limit_strings(self, values: list[str], limit: int) -> list[str]:
        result: list[str] = []
        for value in values:
            clean = str(value or "").strip()
            if clean:
                result.append(clean)
            if len(result) >= limit:
                break
        return result

    def _limit_hard_limits(
        self,
        values: list[CharacterHardLimit],
        limit: int,
    ) -> list[CharacterHardLimit]:
        return [
            value
            for value in values
            if value.statement.strip()
        ][:limit]
