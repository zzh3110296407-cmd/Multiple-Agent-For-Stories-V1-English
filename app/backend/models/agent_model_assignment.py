from typing import Optional

from pydantic import BaseModel


class AgentModelAssignment(BaseModel):
    assignment_id: str
    agent_role: str = "all"
    primary_model_profile_id: str
    fallback_model_profile_id: Optional[str] = None
    routing_policy: str = "single_model"
    temperature: float = 0.7
    max_output_tokens: int = 2000
    structured_output_required: bool = True
