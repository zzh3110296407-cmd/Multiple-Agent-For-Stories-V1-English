from typing import Optional

from pydantic import BaseModel, Field

from app.backend.models.character import Character
from app.backend.models.decision import Decision
from app.backend.models.relationship import Relationship


class CharacterValidationReport(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    user_confirmation_needed: list[str] = Field(default_factory=list)


class CurrentCharacterDraft(BaseModel):
    draft_id: str
    project_id: str = "local_project"
    source_world_canvas_id: str
    character: Character
    relationship_drafts: list[Relationship] = Field(default_factory=list)
    validation_report: CharacterValidationReport = Field(
        default_factory=lambda: CharacterValidationReport(passed=True)
    )
    latest_user_prompt: str = ""
    status: str = "draft"
    created_at: str = ""
    updated_at: str = ""


class CharacterGenerateRequest(BaseModel):
    user_prompt: str
    role_hint: Optional[str] = None
    story_function_hint: Optional[str] = None


class CharacterReviseRequest(BaseModel):
    revision_prompt: str


class CharacterConfirmRequest(BaseModel):
    user_input: Optional[str] = None


class FinishMainCastRequest(BaseModel):
    user_input: Optional[str] = None


class CharacterWorkflowResponse(BaseModel):
    draft: Optional[CurrentCharacterDraft] = None
    characters: list[Character] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    validation: Optional[CharacterValidationReport] = None
    decision: Optional[Decision] = None
    main_cast_finished: bool = False
