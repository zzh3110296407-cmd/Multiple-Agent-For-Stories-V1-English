from typing import Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.character import Character
from app.backend.models.character_workflow import CharacterValidationReport
from app.backend.models.decision import Decision


class RoleComplexityProfile(BaseModel):
    tier: str
    profile_depth: str = "medium"
    relationship_depth: str = "limited"
    arc_depth: str = "light"


class CurrentRoleDraft(BaseModel):
    draft_id: str
    project_id: str = "local_project"
    source_world_canvas_id: str = ""
    role: Character
    complexity_profile: RoleComplexityProfile
    validation_report: CharacterValidationReport = Field(
        default_factory=lambda: CharacterValidationReport(passed=True)
    )
    latest_user_prompt: str = ""
    status: str = "draft"
    created_at: str = ""
    updated_at: str = ""


class RoleGenerateRequest(BaseModel):
    user_prompt: str
    target_tier: str = "B"
    role_hint: Optional[str] = None
    story_function_hint: Optional[str] = None

    @validator("target_tier")
    def normalize_target_tier(cls, value: str) -> str:
        return str(value or "").upper()


class RoleDraftDecisionRequest(BaseModel):
    user_input: str = ""


class RoleGenerationResponse(BaseModel):
    draft: Optional[CurrentRoleDraft] = None
    roles: list[Character] = Field(default_factory=list)
    validation: Optional[CharacterValidationReport] = None
    decision: Optional[Decision] = None
    cleared: bool = False
