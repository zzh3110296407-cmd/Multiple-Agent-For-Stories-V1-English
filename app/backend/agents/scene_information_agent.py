import json
from typing import Any

from app.backend.prompts.scene_generation_prompts import (
    SCENE_INFORMATION_SYSTEM_PROMPT,
    build_scene_information_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


class SceneInformationAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def generate_scene_information(
        self,
        context: dict[str, Any],
        regeneration_hint: str = "",
    ) -> dict[str, Any]:
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": SCENE_INFORMATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_scene_information_prompt(
                        context_json=json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                        ),
                        regeneration_hint=regeneration_hint,
                    ),
                },
            ],
            schema_hint={
                "kind": "scene_information",
                "operation": "regenerate" if regeneration_hint else "generate",
                "context": context,
                "regeneration_hint": regeneration_hint,
            },
        )
        return result.data
