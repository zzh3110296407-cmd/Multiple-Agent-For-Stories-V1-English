from typing import Optional

from pydantic import BaseModel, Field, validator

from app.backend.models.decision import Decision


class WorldRule(BaseModel):
    rule_id: str
    statement: str
    category: str = "other"
    firmness: str = "hard"
    source: str = "agent_generated"
    applies_to: list[str] = Field(default_factory=lambda: ["world"])
    rationale: str = ""
    risk_if_changed: str = ""
    version_id: str = "version_world_canvas_001"


class UnknownRule(BaseModel):
    unknown_rule_id: str
    summary: str
    gap_type: str = "other"
    why_it_matters: str = ""
    related_rule_ids: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    severity: str = "medium"
    status: str = "open"
    first_detected_at: str = ""
    last_checked_at: str = ""


class LogicConflict(BaseModel):
    conflict_id: str
    summary: str
    conflict_type: str = "contradiction"
    related_rule_ids: list[str] = Field(default_factory=list)
    severity: str = "medium"
    suggested_fix: str = ""
    requires_user_decision: bool = True


class WorldStructure(BaseModel):
    structure_id: str = "structure_root_001"
    name: str = ""
    structure_type: str = "other"
    summary: str = ""
    children: list[dict] = Field(default_factory=list)


class WorldCanvas(BaseModel):
    world_canvas_id: str
    project_id: str = "local_project"
    status: str = "draft"
    story_direction: str = ""
    scope: str
    tone: str
    world_structure: WorldStructure = Field(default_factory=WorldStructure)
    history_summary: str = ""
    geography_summary: str = ""
    culture_summary: str = ""
    special_rules_summary: str = ""
    hard_rules: list[WorldRule] = Field(default_factory=list)
    soft_rules: list[WorldRule] = Field(default_factory=list)
    unknown_rules: list[UnknownRule] = Field(default_factory=list)
    logic_conflicts: list[LogicConflict] = Field(default_factory=list)
    user_confirmation_needed: list[str] = Field(default_factory=list)
    locations: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    species: list[dict] = Field(default_factory=list)
    source_story_idea: str = ""
    latest_user_prompt: str = ""
    created_at: str = ""
    updated_at: str = ""
    version_id: str

    @validator("hard_rules", pre=True)
    def migrate_hard_rules(cls, value):
        return migrate_rule_list(value, firmness="hard")

    @validator("soft_rules", pre=True)
    def migrate_soft_rules(cls, value):
        return migrate_rule_list(value, firmness="soft")

    @validator("unknown_rules", pre=True)
    def migrate_unknown_rules(cls, value):
        if value is None:
            return []
        migrated = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, str):
                migrated.append(
                    {
                        "unknown_rule_id": f"unknown_legacy_{index:03d}",
                        "summary": item,
                        "gap_type": "other",
                        "why_it_matters": "Legacy unknown rule migrated from Milestone 2 string data.",
                        "related_rule_ids": [],
                        "suggested_questions": [],
                        "severity": "medium",
                        "status": "open",
                    }
                )
            else:
                migrated.append(item)
        return migrated


class WorldCanvasValidationResult(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    prompt_fidelity_status: str = "not_applicable"
    prompt_fidelity_issues: list[str] = Field(default_factory=list)
    prompt_fidelity_coverage: dict = Field(default_factory=dict)


class WorldCanvasGenerateRequest(BaseModel):
    story_idea: str = ""


class WorldCanvasReviseRequest(BaseModel):
    revision_prompt: str


class WorldCanvasConfirmRequest(BaseModel):
    user_input: Optional[str] = None


class WorldCanvasWorkflowResponse(BaseModel):
    world_canvas: WorldCanvas
    validation: WorldCanvasValidationResult
    decision: Optional[Decision] = None


def migrate_rule_list(value, firmness: str) -> list[dict]:
    if value is None:
        return []
    migrated = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            migrated.append(
                {
                    "rule_id": f"rule_legacy_{firmness}_{index:03d}",
                    "statement": item,
                    "category": "other",
                    "firmness": firmness,
                    "source": "seed",
                    "applies_to": ["world"],
                    "rationale": "Legacy world rule migrated from Milestone 2 string data.",
                    "risk_if_changed": "Changing this rule may affect existing story continuity.",
                    "version_id": "version_legacy_migrated",
                }
            )
        else:
            migrated.append(item)
    return migrated
