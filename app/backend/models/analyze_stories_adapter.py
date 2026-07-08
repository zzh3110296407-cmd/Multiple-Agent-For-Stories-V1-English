from typing import Literal

from pydantic import BaseModel, Field


AdapterCandidateFamily = Literal[
    "chapter_archive",
    "narrative_debt",
    "open_thread",
    "closed_thread",
    "payoff",
    "apparent_contradiction_template",
]
AdapterCandidateStatus = Literal["candidate", "reviewed", "deferred", "rejected", "blocked"]
AdapterDerivationStatus = Literal[
    "completed",
    "completed_with_warnings",
    "blocked",
    "no_candidates",
]
AdapterReliabilityLevel = Literal[
    "stable",
    "validated_with_warnings",
    "provisional",
    "blocked",
]
AdapterConfidence = Literal["explicit", "inferred_from_section", "weak", "blocked"]
AdapterEvidenceStrength = Literal[
    "explicit_section",
    "explicit_ref",
    "weak_label_match",
    "unavailable",
]
AdapterIssueSeverity = Literal["info", "warning", "blocking"]
AdapterActionType = Literal["mark_reviewed", "defer", "reject"]


class AnalyzeStoriesAdapterIssue(BaseModel):
    code: str
    severity: AdapterIssueSeverity = "warning"
    candidate_family: AdapterCandidateFamily | None = None
    field_path: str | None = None
    source_id: str | None = None
    chapter_index: int | None = None
    safe_detail: str = ""


class AnalyzeStoriesAdapterSourceRef(BaseModel):
    source_type: str
    source_id: str
    relationship: str = "supports"
    field_path: str | None = None
    section_type: str | None = None
    chapter_index: int | None = None
    safe_summary: str = ""


class AnalyzeStoriesAdapterDerivationReport(BaseModel):
    derivation_report_id: str
    project_id: str = "local_project"
    bundle_manifest_id: str
    bundle_validation_report_id: str | None = None
    import_id: str
    artifact_id: str
    source: Literal["analyze_stories"] = "analyze_stories"
    derivation_status: AdapterDerivationStatus
    reliability_level: AdapterReliabilityLevel = "blocked"
    can_be_used_as_reference: bool = False
    can_proceed_to_m6_adapter: bool = False
    known_package_gaps_carried: list[str] = Field(default_factory=list)
    viewer_state_ids: list[str] = Field(default_factory=list)
    section_view_ids: list[str] = Field(default_factory=list)
    imported_framework_decision_ids: list[str] = Field(default_factory=list)
    candidate_ids_by_family: dict[str, list[str]] = Field(default_factory=dict)
    candidate_count_by_family: dict[str, int] = Field(default_factory=dict)
    unsupported_section_count_by_type: dict[str, int] = Field(default_factory=dict)
    unhandled_sections: list[AnalyzeStoriesAdapterSourceRef] = Field(default_factory=list)
    warnings: list[AnalyzeStoriesAdapterIssue] = Field(default_factory=list)
    blocking_issues: list[AnalyzeStoriesAdapterIssue] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class AnalyzeStoriesAdapterCandidateBase(BaseModel):
    candidate_id: str
    candidate_family: AdapterCandidateFamily
    candidate_status: AdapterCandidateStatus = "candidate"
    project_id: str = "local_project"
    source: Literal["analyze_stories"] = "analyze_stories"
    derivation_report_id: str
    bundle_manifest_id: str
    import_id: str
    artifact_id: str
    viewer_state_id: str | None = None
    section_view_ids: list[str] = Field(default_factory=list)
    chapter_index: int | None = None
    reliability_level: AdapterReliabilityLevel = "blocked"
    derivation_confidence: AdapterConfidence = "explicit"
    evidence_strength: AdapterEvidenceStrength = "explicit_section"
    source_refs: list[AnalyzeStoriesAdapterSourceRef] = Field(default_factory=list)
    known_package_gaps_carried: list[str] = Field(default_factory=list)
    warnings: list[AnalyzeStoriesAdapterIssue] = Field(default_factory=list)
    blocking_issues: list[AnalyzeStoriesAdapterIssue] = Field(default_factory=list)
    safe_summary: str = ""
    created_at: str
    updated_at: str
    version_id: str


class AnalyzeStoriesChapterArchiveCandidate(AnalyzeStoriesAdapterCandidateBase):
    candidate_family: Literal["chapter_archive"] = "chapter_archive"
    archive_summary_candidate: str = ""
    chapter_goal_result_candidate: str = ""
    reader_emotion_result_candidate: str = ""
    conflict_state_candidate: str = ""
    open_thread_candidate_ids: list[str] = Field(default_factory=list)
    closed_thread_candidate_ids: list[str] = Field(default_factory=list)
    payoff_candidate_ids: list[str] = Field(default_factory=list)


class AnalyzeStoriesNarrativeDebtCandidate(AnalyzeStoriesAdapterCandidateBase):
    candidate_family: Literal["narrative_debt"] = "narrative_debt"
    debt_type: str = "unknown"
    payoff_required: bool = False
    open_ambiguity_allowed: bool = False
    symbolic_unresolved: bool = False
    payoff_deadline_hint: str = ""
    related_open_thread_candidate_ids: list[str] = Field(default_factory=list)
    related_payoff_candidate_ids: list[str] = Field(default_factory=list)


class AnalyzeStoriesOpenThreadCandidate(AnalyzeStoriesAdapterCandidateBase):
    candidate_family: Literal["open_thread"] = "open_thread"
    thread_type: str = "unknown"
    setup_summary_candidate: str = ""
    expected_payoff_hint: str = ""


class AnalyzeStoriesClosedThreadCandidate(AnalyzeStoriesAdapterCandidateBase):
    candidate_family: Literal["closed_thread"] = "closed_thread"
    thread_type: str = "unknown"
    closure_summary_candidate: str = ""
    related_open_thread_candidate_ids: list[str] = Field(default_factory=list)


class AnalyzeStoriesPayoffCandidate(AnalyzeStoriesAdapterCandidateBase):
    candidate_family: Literal["payoff"] = "payoff"
    payoff_type: str = "unknown"
    payoff_summary_candidate: str = ""
    related_open_thread_candidate_ids: list[str] = Field(default_factory=list)
    related_narrative_debt_candidate_ids: list[str] = Field(default_factory=list)


class AnalyzeStoriesApparentContradictionTemplateCandidate(AnalyzeStoriesAdapterCandidateBase):
    candidate_family: Literal["apparent_contradiction_template"] = "apparent_contradiction_template"
    contradiction_type: str = "unknown"
    surface_contradiction_candidate: str = ""
    expected_gate_action: str = "review_quality"
    requires_narrative_debt: bool = False
    related_narrative_debt_candidate_ids: list[str] = Field(default_factory=list)


class AnalyzeStoriesAdapterCandidateAction(BaseModel):
    action_id: str
    candidate_id: str
    candidate_family: AdapterCandidateFamily
    action_type: AdapterActionType
    before_status: AdapterCandidateStatus
    after_status: AdapterCandidateStatus
    safe_user_note: str = ""
    created_at: str
    version_id: str


class AnalyzeStoriesAdapterDerivationRequest(BaseModel):
    viewer_state_ids: list[str] = Field(default_factory=list)
    include_candidate_families: list[AdapterCandidateFamily] = Field(default_factory=list)
    safe_user_note: str = ""


class AnalyzeStoriesAdapterCandidateActionRequest(BaseModel):
    safe_user_note: str = ""


class AnalyzeStoriesAdapterDerivationResult(BaseModel):
    success: bool
    derivation_report: AnalyzeStoriesAdapterDerivationReport
    chapter_archive_candidates: list[AnalyzeStoriesChapterArchiveCandidate] = Field(default_factory=list)
    narrative_debt_candidates: list[AnalyzeStoriesNarrativeDebtCandidate] = Field(default_factory=list)
    open_thread_candidates: list[AnalyzeStoriesOpenThreadCandidate] = Field(default_factory=list)
    closed_thread_candidates: list[AnalyzeStoriesClosedThreadCandidate] = Field(default_factory=list)
    payoff_candidates: list[AnalyzeStoriesPayoffCandidate] = Field(default_factory=list)
    apparent_contradiction_template_candidates: list[AnalyzeStoriesApparentContradictionTemplateCandidate] = Field(default_factory=list)


class AnalyzeStoriesAdapterDerivationListResponse(BaseModel):
    derivation_reports: list[AnalyzeStoriesAdapterDerivationReport] = Field(default_factory=list)


class AnalyzeStoriesAdapterCandidateListResponse(BaseModel):
    candidates: list[dict] = Field(default_factory=list)


class AnalyzeStoriesAdapterCandidateDetail(BaseModel):
    candidate: dict


class AnalyzeStoriesAdapterCandidateActionResult(BaseModel):
    success: bool
    candidate: dict
    action: AnalyzeStoriesAdapterCandidateAction
