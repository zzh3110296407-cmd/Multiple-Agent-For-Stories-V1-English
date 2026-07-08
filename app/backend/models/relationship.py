from pydantic import BaseModel, Field, validator


class Relationship(BaseModel):
    relationship_id: str
    project_id: str = "local_project"
    source_id: str
    target_id: str
    type: str
    state: str
    strength: float
    evidence_event_ids: list[str] = Field(default_factory=list)
    evidence_note: str = ""
    status: str = "confirmed"
    source: str = "seed"
    version_id: str = "version_relationship_legacy"
    created_at: str = ""
    updated_at: str = ""

    @validator("strength")
    def strength_must_be_normalized(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("Relationship.strength must be between 0 and 1.")
        return value
