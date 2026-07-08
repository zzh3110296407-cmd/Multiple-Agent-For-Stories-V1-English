from typing import Any

from pydantic import BaseModel, Field


class StateChange(BaseModel):
    state_change_id: str
    target_type: str
    target_id: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    reason_event_id: str
    requires_user_confirmation: bool
    status: str
