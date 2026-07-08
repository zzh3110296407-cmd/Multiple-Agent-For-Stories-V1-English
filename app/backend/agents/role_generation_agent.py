import json
from typing import Any

from pydantic import BaseModel

from app.backend.models.character import Character
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.models.role_generation import RoleComplexityProfile
from app.backend.models.world_canvas import WorldCanvas
from app.backend.prompts.character_prompts import (
    ROLE_GENERATION_SCHEMA_INSTRUCTIONS,
    ROLE_GENERATION_SYSTEM_PROMPT,
    build_role_generate_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def models_to_json(models: list[BaseModel]) -> str:
    return json.dumps(
        [model_to_dict(model) for model in models],
        ensure_ascii=False,
        indent=2,
    )


def optional_model_to_json(model: BaseModel | None) -> str:
    if model is None:
        return "null"
    return json.dumps(model_to_dict(model), ensure_ascii=False, indent=2)


def bounded_text(value: Any, limit: int = 500) -> str:
    clean = " ".join(str(value or "").split())
    return clean[:limit]


def compact_world_canvas_json(world_canvas: WorldCanvas) -> str:
    data = model_to_dict(world_canvas)
    compact = {
        "world_canvas_id": data.get("world_canvas_id", ""),
        "project_id": data.get("project_id", ""),
        "story_direction": bounded_text(data.get("story_direction"), 600),
        "scope": bounded_text(data.get("scope"), 240),
        "tone": bounded_text(data.get("tone"), 240),
        "world_structure": bounded_text(data.get("world_structure"), 500),
        "history_summary": bounded_text(data.get("history_summary"), 500),
        "geography_summary": bounded_text(data.get("geography_summary"), 360),
        "culture_summary": bounded_text(data.get("culture_summary"), 360),
        "special_rules_summary": bounded_text(data.get("special_rules_summary"), 360),
        "hard_rules": compact_rule_list(data.get("hard_rules"), limit=8),
        "soft_rules": compact_rule_list(data.get("soft_rules"), limit=8),
        "locations": compact_named_items(data.get("locations"), limit=8),
        "factions": compact_named_items(data.get("factions"), limit=8),
        "species": compact_named_items(data.get("species"), limit=6),
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def compact_project_story_premise_json(premise: ProjectStoryPremise | None) -> str:
    if premise is None:
        return "null"
    data = model_to_dict(premise)
    compact = {
        "project_id": data.get("project_id", ""),
        "source_status": data.get("source_status", ""),
        "safe_user_story_summary": bounded_text(data.get("safe_user_story_summary"), 420),
        "required_story_elements": list(data.get("required_story_elements") or [])[:18],
        "core_terms": list(data.get("core_terms") or [])[:18],
        "setting_terms": list(data.get("setting_terms") or [])[:10],
        "conflict_terms": list(data.get("conflict_terms") or [])[:10],
        "role_terms": list(data.get("role_terms") or [])[:36],
        "prompt_markers_detected": list(data.get("prompt_markers_detected") or [])[:10],
        "required_markers": list(
            ((data.get("prompt_fidelity_contract") or {}).get("required_markers") or [])
        )[:10],
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def compact_characters_json(characters: list[Character]) -> str:
    return json.dumps(
        [compact_character(character) for character in characters],
        ensure_ascii=False,
        indent=2,
    )


def compact_character(character: Character) -> dict[str, Any]:
    data = model_to_dict(character)
    profile = data.get("profile") or {}
    state = data.get("current_state") or {}
    return {
        "character_id": data.get("character_id", ""),
        "name": data.get("name", ""),
        "tier": data.get("tier", ""),
        "role": data.get("role", ""),
        "description": bounded_text(profile.get("description"), 240),
        "identity": bounded_text(profile.get("identity"), 160),
        "story_function": bounded_text(profile.get("story_function"), 180),
        "active_goal": bounded_text(state.get("active_goal"), 220),
        "current_desire": bounded_text(state.get("current_desire"), 160),
        "current_fear": bounded_text(state.get("current_fear"), 160),
    }


def compact_rule_list(items: Any, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(items or [])[:limit]:
        if isinstance(item, BaseModel):
            item = model_to_dict(item)
        if not isinstance(item, dict):
            result.append({"statement": bounded_text(item, 240)})
            continue
        result.append(
            {
                "rule_id": item.get("rule_id", ""),
                "statement": bounded_text(item.get("statement"), 260),
                "scope": item.get("scope", ""),
                "source": item.get("source", ""),
            }
        )
    return result


def compact_named_items(items: Any, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list(items or [])[:limit]:
        if isinstance(item, BaseModel):
            item = model_to_dict(item)
        if not isinstance(item, dict):
            result.append({"name": bounded_text(item, 120)})
            continue
        result.append(
            {
                "id": item.get("location_id")
                or item.get("faction_id")
                or item.get("species_id")
                or item.get("id")
                or "",
                "name": item.get("name", ""),
                "description": bounded_text(
                    item.get("description") or item.get("summary") or item.get("role"),
                    220,
                ),
            }
        )
    return result


class RoleGenerationAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def generate_role(
        self,
        *,
        world_canvas: WorldCanvas,
        existing_characters: list[Character],
        user_prompt: str,
        target_tier: str,
        complexity_profile: RoleComplexityProfile,
        role_hint: str = "",
        story_function_hint: str = "",
        project_story_premise: ProjectStoryPremise | None = None,
        same_tier_characters: list[Character] | None = None,
    ) -> dict[str, Any]:
        same_tier = list(same_tier_characters or [])
        max_output_tokens = self._max_output_tokens_for_tier(target_tier)
        user_content = build_role_generate_prompt(
            world_canvas_json=compact_world_canvas_json(world_canvas),
            project_story_premise_json=compact_project_story_premise_json(project_story_premise),
            existing_characters_json=compact_characters_json(existing_characters),
            same_tier_characters_json=compact_characters_json(same_tier),
            user_prompt=user_prompt,
            target_tier=target_tier,
            complexity_profile_json=json.dumps(
                model_to_dict(complexity_profile),
                ensure_ascii=False,
                indent=2,
            ),
            role_hint=role_hint,
            story_function_hint=story_function_hint,
        )
        messages = [
            {"role": "system", "content": ROLE_GENERATION_SYSTEM_PROMPT},
            {"role": "system", "content": ROLE_GENERATION_SCHEMA_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ]
        result = self.model_gateway.generate_json(
            messages=messages,
            options={
                "temperature": 0.35,
                "max_output_tokens": max_output_tokens,
            },
            schema_hint={
                "kind": "character",
                "operation": "generate_role",
                "user_prompt": user_prompt,
                "target_tier": target_tier,
                "complexity_profile": model_to_dict(complexity_profile),
                "role_hint": role_hint,
                "story_function_hint": story_function_hint,
                "project_story_premise": (
                    model_to_dict(project_story_premise)
                    if project_story_premise
                    else None
                ),
                "world_canvas": model_to_dict(world_canvas),
                "existing_characters": [
                    model_to_dict(character) for character in existing_characters
                ],
                "same_tier_characters": [
                    model_to_dict(character) for character in same_tier
                ],
            },
        )
        data = normalize_role_payload(result.data)
        if "character" in data:
            return data
        retry = self.model_gateway.generate_json(
            messages=[
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Your previous JSON did not include the required top-level key "
                        "'character'. Return only valid JSON with exactly this top-level "
                        "shape: {\"character\": {...}}. The character.tier must be "
                        f"{target_tier}. Do not explain. Do not use markdown."
                    ),
                },
            ],
            options={
                "temperature": 0.2,
                "max_output_tokens": max(max_output_tokens, 1200),
            },
            schema_hint={
                "kind": "character",
                "operation": "generate_role_strict_schema_retry",
                "user_prompt": user_prompt,
                "target_tier": target_tier,
            },
        )
        return normalize_role_payload(retry.data)

    def _max_output_tokens_for_tier(self, target_tier: str) -> int:
        tier = str(target_tier or "").upper()
        if tier == "B":
            return 1100
        if tier == "C":
            return 850
        if tier == "D":
            return 650
        return 900


def normalize_role_payload(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    if isinstance(data.get("character"), dict):
        return data
    for key in ("role", "draft", "data", "result"):
        candidate = data.get(key)
        if isinstance(candidate, dict) and _looks_like_role(candidate):
            return {"character": candidate}
    if _looks_like_role(data):
        return {"character": data}
    return data


def _looks_like_role(value: dict[str, Any]) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("name")
        and (isinstance(value.get("profile"), dict) or isinstance(value.get("current_state"), dict))
    )
