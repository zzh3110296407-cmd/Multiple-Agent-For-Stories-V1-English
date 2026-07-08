from typing import Any, Literal

from pydantic import BaseModel, Field


AnalyzerHandoffImportStatus = Literal[
    "ready",
    "missing_validated_handoff",
    "blocked",
]
AnalyzerHandoffIssueSeverity = Literal["warning", "blocking"]


class AnalyzerHandoffImportIssue(BaseModel):
    code: str
    severity: AnalyzerHandoffIssueSeverity = "blocking"
    field_path: str | None = None
    message: str
    safe_detail: str | None = None


class AnalyzerHandoffImportRequest(BaseModel):
    output_dir: str


class AnalyzerHandoffImportResult(BaseModel):
    import_status: AnalyzerHandoffImportStatus
    output_dir: str
    handoff_path: str | None = None
    source_reference_index_path: str | None = None
    files_read: list[str] = Field(default_factory=list)
    quality_gate_summary: dict[str, Any] = Field(default_factory=dict)
    material_count: int = 0
    source_total_chapters: int | None = None
    analysis_unit_count: int | None = None
    arc_count: int | None = None
    expected_arc_count: int | None = None
    issues: list[AnalyzerHandoffImportIssue] = Field(default_factory=list)
    safe_summary: str = ""
