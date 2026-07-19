import json
from typing import Any

from app.backend.prompts.scene_generation_prompts import (
    SCENE_INFORMATION_SYSTEM_PROMPT,
    build_scene_information_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


SCENE_INFORMATION_MAX_OUTPUT_TOKENS = 1200
SCENE_INFORMATION_TIMEOUT_SECONDS = 45
SCENE_INFORMATION_MAX_ATTEMPTS = 1


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
            options={
                "max_output_tokens": SCENE_INFORMATION_MAX_OUTPUT_TOKENS,
                "timeout_seconds": SCENE_INFORMATION_TIMEOUT_SECONDS,
                "max_attempts": SCENE_INFORMATION_MAX_ATTEMPTS,
                "temperature": 0.3,
            },
            agent_role="scene",
            service_name="SceneInformationAgent",
            operation_name="generate_scene_information",
        )
        return result.data
