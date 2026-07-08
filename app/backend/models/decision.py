from pydantic import BaseModel


class Decision(BaseModel):
    decision_id: str
    decision_type: str
    target_type: str
    target_id: str
    user_input: str
    created_at: str
