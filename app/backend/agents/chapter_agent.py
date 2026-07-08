import json
from typing import Any

from pydantic import BaseModel

from app.backend.models.character import Character
from app.backend.models.chapter_plan import ChapterPlanDraft
from app.backend.models.framework_package import ChapterFramework, ChapterMacroAssignment, FrameworkPackage
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.models.relationship import Relationship
from app.backend.models.world_canvas import WorldCanvas
from app.backend.prompts.chapter_prompts import (
    CHAPTER_SCHEMA_INSTRUCTIONS,
    CHAPTER_SYSTEM_PROMPT,
    build_generate_prompt,
    build_revise_prompt,
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


def model_to_json(model: BaseModel | dict[str, Any]) -> str:
    data = model_to_dict(model) if isinstance(model, BaseModel) else model
    return json.dumps(data, ensure_ascii=False, indent=2)


class ChapterAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def generate_chapter_plan(
        self,
        world_canvas: WorldCanvas,
        confirmed_main_cast: list[Character],
        confirmed_supporting_roles: list[Character],
        cd_role_function_policy: dict[str, Any],
        confirmed_relationships: list[Relationship],
        framework_package: FrameworkPackage,
        macro_assignments: list[ChapterMacroAssignment],
        current_chapter_framework: ChapterFramework,
        generator_framework_context: dict[str, Any] | None,
        project_story_premise: ProjectStoryPremise | None,
        story_goal: str,
        chapter_count: int,
        current_chapter_index: int,
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": CHAPTER_SYSTEM_PROMPT},
                {"role": "system", "content": CHAPTER_SCHEMA_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": build_generate_prompt(
                        world_canvas_json=model_to_json(world_canvas),
                        confirmed_main_cast_json=models_to_json(confirmed_main_cast),
                        confirmed_supporting_roles_json=models_to_json(confirmed_supporting_roles),
                        cd_role_function_policy_json=model_to_json(cd_role_function_policy),
                        confirmed_relationships_json=models_to_json(confirmed_relationships),
                        framework_package_json=model_to_json(framework_package),
                        macro_assignments_json=models_to_json(macro_assignments),
                        current_chapter_framework_json=model_to_json(current_chapter_framework),
                        generator_framework_context_json=model_to_json(
                            generator_framework_context or {}
                        ),
                        project_story_premise_json=(
                            model_to_json(project_story_premise)
                            if project_story_premise
                            else "{}"
                        ),
                        story_goal=story_goal,
                        chapter_count=chapter_count,
                        current_chapter_index=current_chapter_index,
                    ),
                },
            ],
            schema_hint={
                "kind": "chapter_plan",
                "operation": "generate",
                "story_goal": story_goal,
                "chapter_count": chapter_count,
                "current_chapter_index": current_chapter_index,
                "world_canvas": model_to_dict(world_canvas),
                "confirmed_main_cast": [
                    model_to_dict(character) for character in confirmed_main_cast
                ],
                "confirmed_supporting_roles": [
                    model_to_dict(character) for character in confirmed_supporting_roles
                ],
                "cd_role_function_policy": cd_role_function_policy,
                "confirmed_characters": [
                    model_to_dict(character)
                    for character in [*confirmed_main_cast, *confirmed_supporting_roles]
                ],
                "confirmed_relationships": [
                    model_to_dict(relationship)
                    for relationship in confirmed_relationships
                ],
                "framework_package": model_to_dict(framework_package),
                "macro_assignments": [
                    model_to_dict(assignment) for assignment in macro_assignments
                ],
                "current_chapter_framework": model_to_dict(current_chapter_framework),
                "generator_framework_context": generator_framework_context or {},
                "project_story_premise": (
                    model_to_dict(project_story_premise)
                    if project_story_premise
                    else None
                ),
            },
        )
        return result.data

    def revise_chapter_plan(
        self,
        current_draft: ChapterPlanDraft,
        world_canvas: WorldCanvas,
        confirmed_main_cast: list[Character],
        confirmed_supporting_roles: list[Character],
        cd_role_function_policy: dict[str, Any],
        confirmed_relationships: list[Relationship],
        framework_package: FrameworkPackage,
        current_chapter_framework: ChapterFramework,
        generator_framework_context: dict[str, Any] | None,
        project_story_premise: ProjectStoryPremise | None,
        revision_prompt: str,
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": CHAPTER_SYSTEM_PROMPT},
                {"role": "system", "content": CHAPTER_SCHEMA_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": build_revise_prompt(
                        current_draft_json=model_to_json(current_draft),
                        world_canvas_json=model_to_json(world_canvas),
                        confirmed_main_cast_json=models_to_json(confirmed_main_cast),
                        confirmed_supporting_roles_json=models_to_json(confirmed_supporting_roles),
                        cd_role_function_policy_json=model_to_json(cd_role_function_policy),
                        confirmed_relationships_json=models_to_json(confirmed_relationships),
                        framework_package_json=model_to_json(framework_package),
                        current_chapter_framework_json=model_to_json(current_chapter_framework),
                        generator_framework_context_json=model_to_json(
                            generator_framework_context or {}
                        ),
                        project_story_premise_json=(
                            model_to_json(project_story_premise)
                            if project_story_premise
                            else "{}"
                        ),
                        revision_prompt=revision_prompt,
                    ),
                },
            ],
            schema_hint={
                "kind": "chapter_plan",
                "operation": "revise",
                "revision_prompt": revision_prompt,
                "current_draft": model_to_dict(current_draft),
                "world_canvas": model_to_dict(world_canvas),
                "confirmed_main_cast": [
                    model_to_dict(character) for character in confirmed_main_cast
                ],
                "confirmed_supporting_roles": [
                    model_to_dict(character) for character in confirmed_supporting_roles
                ],
                "cd_role_function_policy": cd_role_function_policy,
                "confirmed_characters": [
                    model_to_dict(character)
                    for character in [*confirmed_main_cast, *confirmed_supporting_roles]
                ],
                "confirmed_relationships": [
                    model_to_dict(relationship)
                    for relationship in confirmed_relationships
                ],
                "framework_package": model_to_dict(framework_package),
                "current_chapter_framework": model_to_dict(current_chapter_framework),
                "generator_framework_context": generator_framework_context or {},
                "project_story_premise": (
                    model_to_dict(project_story_premise)
                    if project_story_premise
                    else None
                ),
            },
        )
        return result.data
