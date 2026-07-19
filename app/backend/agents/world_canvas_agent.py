import json
from typing import Any

from pydantic import BaseModel

from app.backend.models.world_canvas import WorldCanvas
from app.backend.prompts.world_canvas_prompts import (
    WORLD_CANVAS_SCHEMA_INSTRUCTIONS,
    WORLD_CANVAS_SYSTEM_PROMPT,
    build_generate_prompt,
    build_revise_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class WorldCanvasAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def generate_from_idea(self, story_idea: str) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": WORLD_CANVAS_SYSTEM_PROMPT},
                {"role": "system", "content": WORLD_CANVAS_SCHEMA_INSTRUCTIONS},
                {"role": "user", "content": build_generate_prompt(story_idea)},
            ],
            options={
                "temperature": 0.35,
                "max_output_tokens": 3600,
            },
            schema_hint={
                "kind": "world_canvas",
                "operation": "generate",
                "story_idea": story_idea,
            },
        )
        return result.data

    def revise_canvas(
        self,
        current_canvas: WorldCanvas,
        revision_prompt: str,
    ) -> dict[str, Any]:
        current_canvas_json = json.dumps(
            model_to_dict(current_canvas),
            ensure_ascii=False,
            indent=2,
        )
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": WORLD_CANVAS_SYSTEM_PROMPT},
                {"role": "system", "content": WORLD_CANVAS_SCHEMA_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": build_revise_prompt(current_canvas_json, revision_prompt),
                },
            ],
            options={
                "temperature": 0.35,
                "max_output_tokens": 3200,
            },
            schema_hint={
                "kind": "world_canvas",
                "operation": "revise",
                "story_idea": current_canvas.source_story_idea,
                "revision_prompt": revision_prompt,
                "current_canvas": model_to_dict(current_canvas),
            },
        )
        return result.data
