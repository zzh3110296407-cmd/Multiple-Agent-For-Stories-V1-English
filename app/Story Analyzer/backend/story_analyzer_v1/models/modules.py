from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import AdvisoryAuthority, GenerationMode, SourceSpecificity, validate_evidence_refs


class ModuleEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    module_instance_id: str
    scope: Literal["book", "major_arc", "sub_arc", "chapter", "tracker"]
    module_type: Literal[
        "rhythm",
        "plot",
        "theme",
        "character",
        "relationship",
        "world",
        "style",
        "information",
        "adaptation",
    ]
    source_specificity: SourceSpecificity
    recommended_modes: list[GenerationMode] = Field(default_factory=list)
    user_selectable: bool = True
    authority: AdvisoryAuthority = AdvisoryAuthority.ADVISORY_ONLY
    can_write_formal_state: bool = False
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    missing_dependency_behavior: Literal["warn", "auto_include", "ask_user"] = "warn"
    content: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validate_evidence_refs(value)
