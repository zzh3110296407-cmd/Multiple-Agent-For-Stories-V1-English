import json
from typing import Any

from pydantic import BaseModel

from app.backend.models.character import Character
from app.backend.models.character_workflow import CurrentCharacterDraft
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.models.relationship import Relationship
from app.backend.models.world_canvas import WorldCanvas
from app.backend.prompts.character_prompts import (
    CHARACTER_SCHEMA_INSTRUCTIONS,
    CHARACTER_SYSTEM_PROMPT,
    build_generate_prompt,
    build_revise_prompt,
)
from app.backend.agents.role_generation_agent import (
    compact_characters_json,
    compact_project_story_premise_json,
    compact_world_canvas_json,
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


class CharacterAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def generate_character(
        self,
        world_canvas: WorldCanvas,
        existing_characters: list[Character],
        existing_relationships: list[Relationship],
        user_prompt: str,
        role_hint: str = "",
        story_function_hint: str = "",
        project_story_premise: ProjectStoryPremise | None = None,
        same_tier_characters: list[Character] | None = None,
    ) -> dict[str, Any]:
        same_tier = list(same_tier_characters or [])
        user_content = build_generate_prompt(
            world_canvas_json=compact_world_canvas_json(world_canvas),
            project_story_premise_json=compact_project_story_premise_json(project_story_premise),
            existing_characters_json=compact_characters_json(existing_characters),
            same_tier_characters_json=compact_characters_json(same_tier),
            existing_relationships_json=models_to_json(existing_relationships),
            user_prompt=user_prompt,
            role_hint=role_hint,
            story_function_hint=story_function_hint,
        )
        messages = [
            {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
            {"role": "system", "content": CHARACTER_SCHEMA_INSTRUCTIONS},
            {"role": "user", "content": user_content},
        ]
        result = self.model_gateway.generate_json(
            messages=messages,
            options={
                "temperature": 0.35,
                "max_output_tokens": 1600,
            },
            schema_hint={
                "kind": "character",
                "operation": "generate",
                "user_prompt": user_prompt,
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
                "existing_relationships": [
                    model_to_dict(relationship)
                    for relationship in existing_relationships
                ],
            },
        )
        data = normalize_character_payload(result.data)
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
                        "shape: {\"character\": {...}, \"relationship_drafts\": []}. "
                        "Do not explain. Do not use markdown."
                    ),
                },
            ],
            options={
                "temperature": 0.2,
                "max_output_tokens": 1800,
            },
            schema_hint={
                "kind": "character",
                "operation": "generate_strict_schema_retry",
                "user_prompt": user_prompt,
            },
        )
        return normalize_character_payload(retry.data)

    def revise_character(
        self,
        current_draft: CurrentCharacterDraft,
        world_canvas: WorldCanvas,
        existing_characters: list[Character],
        existing_relationships: list[Relationship],
        revision_prompt: str,
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
                {"role": "system", "content": CHARACTER_SCHEMA_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": build_revise_prompt(
                        current_draft_json=json.dumps(
                            model_to_dict(current_draft),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        world_canvas_json=json.dumps(
                            model_to_dict(world_canvas),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        existing_characters_json=models_to_json(existing_characters),
                        existing_relationships_json=models_to_json(existing_relationships),
                        revision_prompt=revision_prompt,
                    ),
                },
            ],
            schema_hint={
                "kind": "character",
                "operation": "revise",
                "revision_prompt": revision_prompt,
                "current_draft": model_to_dict(current_draft),
                "world_canvas": model_to_dict(world_canvas),
                "existing_characters": [
                    model_to_dict(character) for character in existing_characters
                ],
                "existing_relationships": [
                    model_to_dict(relationship)
                    for relationship in existing_relationships
                ],
            },
        )
        return result.data


def normalize_character_payload(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    if isinstance(data.get("character"), dict):
        return data
    for key in ("role", "draft", "data", "result"):
        candidate = data.get(key)
        if isinstance(candidate, dict) and _looks_like_character(candidate):
            return {
                "character": candidate,
                "relationship_drafts": data.get("relationship_drafts") or [],
            }
    if _looks_like_character(data):
        return {
            "character": data,
            "relationship_drafts": data.get("relationship_drafts") or [],
        }
    return data


def _looks_like_character(value: dict[str, Any]) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("name")
        and (isinstance(value.get("profile"), dict) or isinstance(value.get("current_state"), dict))
    )
