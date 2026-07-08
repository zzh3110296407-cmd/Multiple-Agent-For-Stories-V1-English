from typing import Any, Literal

from pydantic import BaseModel, Field


AnalyzerMaterialUserMode = Literal[
    "original_writing",
    "continuation_rewrite",
    "hybrid_adaptation",
]
AnalyzerMaterialSelectionStatus = Literal["ready", "blocked"]
AnalyzerMaterialSelectionIssueSeverity = Literal["warning", "blocking"]


class AnalyzerMaterialSelectionIssue(BaseModel):
    code: str
    severity: AnalyzerMaterialSelectionIssueSeverity = "warning"
    material_id: str | None = None
    field_path: str | None = None
    message: str
    safe_detail: str | None = None


class AnalyzerSelectedMaterial(BaseModel):
    material_id: str
    material: dict[str, Any]
    selection_score: int = 0
    selection_bucket: Literal["preferred", "compatible"] = "compatible"
    selection_reasons: list[str] = Field(default_factory=list)


class AnalyzerMaterialSelectionResult(BaseModel):
    selection_status: AnalyzerMaterialSelectionStatus
    user_mode: AnalyzerMaterialUserMode
    selected_materials: list[AnalyzerSelectedMaterial] = Field(default_factory=list)
    excluded_material_count: int = 0
    source_material_count: int = 0
    files_read: list[str] = Field(default_factory=list)
    issues: list[AnalyzerMaterialSelectionIssue] = Field(default_factory=list)
    import_status: str | None = None
    safe_summary: str = ""
