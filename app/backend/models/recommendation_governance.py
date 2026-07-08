from typing import Literal

from pydantic import BaseModel, Field


RecommendationSourceObjectType = Literal[
    "framework_module_library_item",
    "framework_pattern_record",
    "module_composition_rule",
    "user_private_framework",
]
RecommendationEligibilityStatus = Literal[
    "eligible_for_review",
    "eligible_with_warnings",
    "private_only",
    "project_local_only",
    "blocked",
    "needs_more_evidence",
]
RecommendationRequiredNextStep = Literal[
    "system_recommendation_review",
    "keep_private",
    "keep_project_local",
    "request_more_evidence",
    "reject",
]
RecommendationRiskLevel = Literal["low", "medium", "high", "blocked"]
RecommendationRiskCategory = Literal[
    "weak_external_evidence",
    "missing_source_lineage",
    "character_arc_empty_by_design",
    "copyright_risk",
    "maturity_too_low",
    "reference_only_source",
    "private_framework_dangling_ref",
    "unreviewed_propagation_impact",
    "unsafe_raw_content",
    "unknown",
]
RecommendationReviewStatus = Literal[
    "pending",
    "approved_as_candidate",
    "rejected",
    "needs_more_evidence",
    "private_only",
    "project_local_only",
    "superseded",
]
RecommendationApprovedVisibility = Literal[
    "private",
    "project_local",
    "system_recommendation_candidate",
    "blocked",
]
LibraryPromotionDecisionType = Literal[
    "promote_to_system_recommendation_candidate",
    "keep_project_local",
    "keep_private",
    "reject_promotion",
    "request_more_evidence",
]
LibraryPromotionDecisionStatus = Literal["recorded", "blocked", "superseded"]


class RecommendationEvaluateRequest(BaseModel):
    source_object_type: RecommendationSourceObjectType
    source_object_id: str
    safe_user_note: str = ""


class RecommendationOpenReviewRequest(BaseModel):
    eligibility_report_id: str
    safe_user_note: str = ""


class RecommendationReviewActionRequest(BaseModel):
    safe_user_note: str = ""
    reviewer_note: str = ""
    acknowledged_warning_codes: list[str] = Field(default_factory=list)


class RecommendationEligibilityReport(BaseModel):
    recommendation_eligibility_report_id: str
    project_id: str = "local_project"
    source_object_type: RecommendationSourceObjectType
    source_object_id: str
    source_object_label: str = ""
    source_lineage_ids: list[str] = Field(default_factory=list)
    source_ref_ids: list[str] = Field(default_factory=list)
    copyright_source_record_id: str | None = None
    maturity_record_id: str | None = None
    known_gap_record_ids: list[str] = Field(default_factory=list)
    linked_m5_execution_result_ids: list[str] = Field(default_factory=list)
    linked_m6_impact_record_ids: list[str] = Field(default_factory=list)
    eligibility_status: RecommendationEligibilityStatus
    can_create_system_recommendation_candidate: bool = False
    can_be_private_reusable: bool = True
    can_be_project_local_reusable: bool = True
    blocking_reason_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    required_next_step: RecommendationRequiredNextStep
    does_not_create_active_recommendation: bool = True
    does_not_mutate_active_framework: bool = True
    does_not_write_story_fact: bool = True
    safe_user_note: str = ""
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class RecommendationRiskProfile(BaseModel):
    recommendation_risk_profile_id: str
    project_id: str = "local_project"
    source_object_type: RecommendationSourceObjectType
    source_object_id: str
    eligibility_report_id: str | None = None
    risk_level: RecommendationRiskLevel
    risk_categories: list[RecommendationRiskCategory] = Field(default_factory=list)
    copyright_risk_level: str = "unknown"
    source_confidence: str = "medium"
    maturity_confidence: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    safe_summary: str
    created_at: str
    updated_at: str
    version_id: str


class SystemRecommendationCandidateReview(BaseModel):
    recommendation_review_id: str
    project_id: str = "local_project"
    source_object_type: RecommendationSourceObjectType
    source_object_id: str
    eligibility_report_id: str
    risk_profile_id: str
    review_status: RecommendationReviewStatus = "pending"
    reviewer_type: str = "user"
    reviewer_note: str = ""
    acknowledged_warning_codes: list[str] = Field(default_factory=list)
    approved_visibility: RecommendationApprovedVisibility = "private"
    decision_ids: list[str] = Field(default_factory=list)
    does_not_create_active_recommendation: bool = True
    does_not_activate_framework: bool = True
    does_not_write_story_fact: bool = True
    created_at: str
    updated_at: str
    version_id: str


class LibraryPromotionDecision(BaseModel):
    library_promotion_decision_id: str
    project_id: str = "local_project"
    source_object_type: RecommendationSourceObjectType
    source_object_id: str
    eligibility_report_id: str
    risk_profile_id: str
    recommendation_review_id: str
    decision_type: LibraryPromotionDecisionType
    decision_status: LibraryPromotionDecisionStatus = "recorded"
    user_note: str = ""
    acknowledged_warning_codes: list[str] = Field(default_factory=list)
    resulting_visibility: RecommendationApprovedVisibility
    does_not_mutate_existing_library_record: bool = True
    does_not_create_active_recommendation: bool = True
    does_not_mutate_active_framework: bool = True
    does_not_create_formal_story_fact: bool = True
    created_at: str
    updated_at: str
    version_id: str


class RecommendationEvaluationResult(BaseModel):
    success: bool
    eligibility_report: RecommendationEligibilityReport
    risk_profile: RecommendationRiskProfile
    safe_summary: str


class RecommendationGovernanceStatusResponse(BaseModel):
    eligibility_report_count: int = 0
    risk_profile_count: int = 0
    review_count: int = 0
    pending_review_count: int = 0
    promotion_decision_count: int = 0
    active_system_recommendation_count: int = 0
    latest_eligibility_report_id: str | None = None
    governance_only: bool = True
    active_recommendation_creation_disabled: bool = True
    active_framework_mutation_disabled: bool = True
    formal_story_write_disabled: bool = True
    allowed_storage_files: list[str] = Field(default_factory=list)
    forbidden_storage_files: list[str] = Field(default_factory=list)
    safe_summary: str


class RecommendationEligibilityReportListResponse(BaseModel):
    eligibility_reports: list[RecommendationEligibilityReport] = Field(default_factory=list)
    total_count: int = 0


class RecommendationRiskProfileListResponse(BaseModel):
    risk_profiles: list[RecommendationRiskProfile] = Field(default_factory=list)
    total_count: int = 0


class SystemRecommendationCandidateReviewListResponse(BaseModel):
    reviews: list[SystemRecommendationCandidateReview] = Field(default_factory=list)
    total_count: int = 0


class LibraryPromotionDecisionListResponse(BaseModel):
    promotion_decisions: list[LibraryPromotionDecision] = Field(default_factory=list)
    total_count: int = 0


class RecommendationReviewActionResult(BaseModel):
    success: bool
    review: SystemRecommendationCandidateReview
    promotion_decision: LibraryPromotionDecision
    safe_summary: str
