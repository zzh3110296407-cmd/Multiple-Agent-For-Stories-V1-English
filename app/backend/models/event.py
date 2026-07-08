from pydantic import BaseModel, Field


class Event(BaseModel):
    event_id: str
    scene_id: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    location_id: str
    cause: str
    result: str
    tags: list[str] = Field(default_factory=list)
    status: str = "confirmed"
    created_at: str = ""
    updated_at: str = ""
