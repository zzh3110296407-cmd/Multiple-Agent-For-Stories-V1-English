import json

from app.backend.models.authorial_intent import (
    AuthorialIntentAgentOutput,
    AuthorialIntentContext,
)
from app.backend.prompts.authorial_intent_prompts import (
    AUTHORIAL_INTENT_SYSTEM_PROMPT,
    build_authorial_intent_prompt,
)
from app.backend.services.model_gateway_service import ModelGatewayService


class AuthorialIntentAgent:
    def __init__(self, model_gateway: ModelGatewayService | None = None) -> None:
        self.model_gateway = model_gateway or ModelGatewayService()

    def generate(self, context: AuthorialIntentContext) -> AuthorialIntentAgentOutput:
        context_payload = model_to_dict(context)
        result = self.model_gateway.generate_json(
            messages=[
                {"role": "system", "content": AUTHORIAL_INTENT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_authorial_intent_prompt(
                        context_json=json.dumps(
                            context_payload,
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                },
            ],
            schema_hint={
                "kind": "authorial_intent",
                "context": context_payload,
            },
            options={"temperature": 0.3, "max_output_tokens": 1200},
            agent_role="authorial_intent_agent",
            service_name="AuthorialIntentAgent",
            operation_name="generate_authorial_intent",
        )
        return AuthorialIntentAgentOutput(**result.data)


def model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()
