from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.framework_module_library import (
    CopyrightSourceRecord,
    FrameworkMaturityRecord,
    FrameworkModuleLibraryItem,
    FrameworkPatternRecord,
    ModuleCompositionRule,
    UserPrivateFramework,
)
from ..models.phase6_replay_gate import KnownGapCarryForwardRecord
from ..models.propagation_governance import AffectedObjectReviewTask, PropagationImpactRecord
from ..models.recommendation_governance import (
    LibraryPromotionDecision,
    LibraryPromotionDecisionListResponse,
    RecommendationEligibilityReport,
    RecommendationEligibilityReportListResponse,
    RecommendationEvaluateRequest,
    RecommendationEvaluationResult,
    RecommendationGovernanceStatusResponse,
    RecommendationOpenReviewRequest,
    RecommendationRequiredNextStep,
    RecommendationReviewActionRequest,
    RecommendationReviewActionResult,
    RecommendationReviewStatus,
    RecommendationRiskCategory,
    RecommendationRiskLevel,
    RecommendationRiskProfile,
    RecommendationRiskProfileListResponse,
    RecommendationSourceObjectType,
    SystemRecommendationCandidateReview,
    SystemRecommendationCandidateReviewListResponse,
)
from ..services.framework_module_library_service import (
    COMPOSITION_RULES_FILE,
    COPYRIGHT_FILE,
    ITEMS_FILE,
    MATURITY_FILE,
    PATTERNS_FILE,
    PRIVATE_FRAMEWORKS_FILE,
    SYSTEM_RECOMMENDATIONS_FILE,
)
from ..services.phase6_replay_gate_service import KNOWN_GAPS_FILE
from ..services.propagation_governance_service import IMPACT_RECORDS_FILE, REVIEW_TASKS_FILE
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m7_recommendation_governance_v1"

ELIGIBILITY_REPORTS_FILE = "phase6_recommendation_eligibility_reports.json"
RISK_PROFILES_FILE = "phase6_recommendation_risk_profiles.json"
CANDIDATE_REVIEWS_FILE = "phase6_system_recommendation_candidate_reviews.json"
PROMOTION_DECISIONS_FILE = "phase6_library_promotion_decisions.json"

ALLOWED_STORAGE_FILES = [
    ELIGIBILITY_REPORTS_FILE,
    RISK_PROFILES_FILE,
    CANDIDATE_REVIEWS_FILE,
    PROMOTION_DECISIONS_FILE,
]

FORBIDDEN_STORAGE_FILES = [
    ITEMS_FILE,
    PATTERNS_FILE,
    COMPOSITION_RULES_FILE,
    MATURITY_FILE,
    COPYRIGHT_FILE,
    PRIVATE_FRAMEWORKS_FILE,
    SYSTEM_RECOMMENDATIONS_FILE,
    "framework_library_collections.json",
    "framework_library_build_reports.json",
    "decisions.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "scenes.json",
    "framework.json",
    "framework_package.json",
    "continuity_issues.json",
    "future_issues.json",
    "delayed_questions.json",
    "future_todos.json",
    "phase6_stable_clean_replay_reports.json",
    "phase6_analyze_stories_replay_runs.json",
    "phase6_known_gap_carry_forward_records.json",
    "phase6_replay_compatibility_matrices.json",
    "phase6_replay_evidence_indexes.json",
    "phase6_formal_apply_targets.json",
    "phase6_formal_apply_source_lineages.json",
    "phase6_formal_apply_eligibility_reports.json",
    "phase6_formal_apply_block_reasons.json",
    "phase6_formal_apply_plans.json",
    "phase6_formal_apply_plan_items.json",
    "phase6_formal_apply_diff_summaries.json",
    "phase6_formal_apply_impact_previews.json",
    "phase6_formal_apply_safety_checks.json",
    "phase6_formal_apply_decisions.json",
    "phase6_formal_apply_approval_records.json",
    "phase6_formal_apply_rejection_records.json",
    "phase6_formal_apply_user_overrides.json",
    "phase6_formal_apply_questions.json",
    "phase6_formal_apply_decision_evidence_snapshots.json",
    "phase6_formal_apply_execution_results.json",
    "phase6_formal_apply_rollback_refs.json",
    "phase6_formal_apply_write_audits.json",
    "phase6_framework_apply_proposals.json",
    "phase6_chapter_archive_proposals.json",
    "phase6_narrative_debt_proposals.json",
    IMPACT_RECORDS_FILE,
    REVIEW_TASKS_FILE,
    "phase6_cross_chapter_recheck_plans.json",
    "phase6_framework_change_propagation_reports.json",
]
TERMINAL_REVIEW_STATUSES = {
    "approved_as_candidate",
    "rejected",
    "private_only",
    "project_local_only",
    "superseded",
}

UNSAFE_KEY_PARTS = (
    "prompt",
    "response",
    "reasoning",
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
)
UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "full prose",
    "full_prose",
    "prose text",
    "prose_text",
    "revised prose text",
    "revised_prose_text",
    "full user modification text",
    "full_user_modification_text",
    "provider secret",
    "provider_secret",
    "authorization:",
    "bearer ",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")
FILESYSTEM_PATH_RE = re.compile(r"(?i)(^[\\/]|[a-z]:[\\/]|(^|[\\/])\.\.([\\/]|$))")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if isinstance(model, BaseModel):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json")
        return model.dict()
    if isinstance(model, dict):
        return dict(model)
    raise TypeError(f"Unsupported model type: {type(model)!r}")


@dataclass
class SourceContext:
    source_object_type: RecommendationSourceObjectType
    source_object_id: str
    source_object_label: str
    record: dict[str, Any]
    source_refs: list[dict[str, Any]]
    maturity_records: list[FrameworkMaturityRecord]
    copyright_records: list[CopyrightSourceRecord]
    known_gap_records: list[KnownGapCarryForwardRecord]
    linked_m6_impacts: list[PropagationImpactRecord]
    linked_m6_tasks: list[AffectedObjectReviewTask]
    dangling_ref_codes: list[str]


class RecommendationGovernanceService:
    """Phase 6 M7 recommendation-governance evidence service.

    M7 evaluates and records governance decisions for possible recommendation
    candidate review. It never creates active system recommendations and never
    mutates framework library records.
    """

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.eligibility_reports_file = self.data_dir / ELIGIBILITY_REPORTS_FILE
        self.risk_profiles_file = self.data_dir / RISK_PROFILES_FILE
        self.candidate_reviews_file = self.data_dir / CANDIDATE_REVIEWS_FILE
        self.promotion_decisions_file = self.data_dir / PROMOTION_DECISIONS_FILE

    def get_status(self) -> RecommendationGovernanceStatusResponse:
        reports = self._read_models_if_exists(self.eligibility_reports_file, RecommendationEligibilityReport)
        risks = self._read_models_if_exists(self.risk_profiles_file, RecommendationRiskProfile)
        reviews = self._read_models_if_exists(self.candidate_reviews_file, SystemRecommendationCandidateReview)
        decisions = self._read_models_if_exists(self.promotion_decisions_file, LibraryPromotionDecision)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        active_recommendations = [
            item
            for item in self._read_list(self.data_dir / SYSTEM_RECOMMENDATIONS_FILE)
            if item.get("status") == "candidate"
        ]
        return RecommendationGovernanceStatusResponse(
            eligibility_report_count=len(reports),
            risk_profile_count=len(risks),
            review_count=len(reviews),
            pending_review_count=len([review for review in reviews if review.review_status == "pending"]),
            promotion_decision_count=len(decisions),
            active_system_recommendation_count=len(active_recommendations),
            latest_eligibility_report_id=reports[0].recommendation_eligibility_report_id if reports else None,
            governance_only=True,
            active_recommendation_creation_disabled=True,
            active_framework_mutation_disabled=True,
            formal_story_write_disabled=True,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            forbidden_storage_files=list(FORBIDDEN_STORAGE_FILES),
            safe_summary=(
                "Phase 6 M7 records recommendation governance evidence only. "
                "It creates no active recommendations and mutates no framework library or story records."
            ),
        )

    def evaluate(
        self,
        request: RecommendationEvaluateRequest | dict[str, Any],
    ) -> RecommendationEvaluationResult:
        normalized = request if isinstance(request, RecommendationEvaluateRequest) else RecommendationEvaluateRequest(**request)
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500:
            raise StorageError("RECOMMENDATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: safe_user_note_too_long")
        context = self._load_source_context(normalized.source_object_type, normalized.source_object_id)
        before = self._storage_fingerprints()
        timestamp = now_iso()
        report_id = self._next_id("recommendation_eligibility_report", self.eligibility_reports_file, "recommendation_eligibility_report_id")
        risk_id = f"{report_id}_risk_profile"
        risk_categories, warnings, blockers = self._policy_findings(context)
        risk_level = self._risk_level(context, risk_categories, blockers)
        status, required_next_step, can_create = self._eligibility_status(context, risk_categories, blockers, risk_level)
        copyright_record = context.copyright_records[0] if context.copyright_records else None
        maturity_record = context.maturity_records[0] if context.maturity_records else None
        report = RecommendationEligibilityReport(
            recommendation_eligibility_report_id=report_id,
            project_id=LOCAL_PROJECT_ID,
            source_object_type=context.source_object_type,
            source_object_id=context.source_object_id,
            source_object_label=self._short(context.source_object_label, 160),
            source_lineage_ids=self._lineage_ids(context.source_refs),
            source_ref_ids=self._source_ref_ids(context.source_refs),
            copyright_source_record_id=copyright_record.copyright_source_record_id if copyright_record else None,
            maturity_record_id=maturity_record.maturity_record_id if maturity_record else None,
            known_gap_record_ids=[gap.known_gap_record_id for gap in context.known_gap_records],
            linked_m5_execution_result_ids=[],
            linked_m6_impact_record_ids=[impact.impact_record_id for impact in context.linked_m6_impacts],
            eligibility_status=status,
            can_create_system_recommendation_candidate=can_create,
            can_be_private_reusable=status != "blocked",
            can_be_project_local_reusable=status not in {"blocked", "private_only"},
            blocking_reason_codes=self._dedupe(blockers),
            warning_codes=self._dedupe(warnings),
            required_next_step=required_next_step,
            does_not_create_active_recommendation=True,
            does_not_mutate_active_framework=True,
            does_not_write_story_fact=True,
            safe_user_note=self._short(normalized.safe_user_note, 500),
            safe_summary=(
                f"M7 evaluated {context.source_object_type}:{context.source_object_id} for recommendation governance only. "
                f"Status: {status}."
            ),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        risk_profile = RecommendationRiskProfile(
            recommendation_risk_profile_id=risk_id,
            project_id=LOCAL_PROJECT_ID,
            source_object_type=context.source_object_type,
            source_object_id=context.source_object_id,
            eligibility_report_id=report_id,
            risk_level=risk_level,
            risk_categories=self._dedupe(risk_categories),
            copyright_risk_level=self._copyright_risk(context),
            source_confidence="high" if context.source_refs else "low",
            maturity_confidence=self._maturity_confidence(context),
            warnings=self._dedupe(warnings),
            blocking_issues=self._dedupe(blockers),
            safe_summary=f"M7 risk profile is {risk_level}; no active recommendation was created.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._guard_safe_payload(model_to_dict(report))
        self._guard_safe_payload(model_to_dict(risk_profile))
        self._append(self.eligibility_reports_file, model_to_dict(report))
        self._append(self.risk_profiles_file, model_to_dict(risk_profile))
        self._assert_only_allowed_changed(before)
        return RecommendationEvaluationResult(
            success=True,
            eligibility_report=report,
            risk_profile=risk_profile,
            safe_summary="M7 recommendation eligibility and risk evidence were recorded without recommendation activation.",
        )

    def open_review(
        self,
        request: RecommendationOpenReviewRequest | dict[str, Any],
    ) -> SystemRecommendationCandidateReview:
        normalized = request if isinstance(request, RecommendationOpenReviewRequest) else RecommendationOpenReviewRequest(**request)
        self._guard_safe_payload(model_to_dict(normalized))
        report = self.get_eligibility_report(normalized.eligibility_report_id)
        if report.eligibility_status == "blocked":
            raise StorageError("RECOMMENDATION_GOVERNANCE_REVIEW_BLOCKED: eligibility_blocked")
        active = self._active_review_for_report_or_source(report)
        if active:
            raise StorageError(f"RECOMMENDATION_GOVERNANCE_DUPLICATE_ACTIVE_REVIEW: {active.recommendation_review_id}")
        risk = self._risk_for_report(report.recommendation_eligibility_report_id)
        if risk is None:
            raise StorageError("RECOMMENDATION_RISK_PROFILE_NOT_FOUND")
        before = self._storage_fingerprints()
        timestamp = now_iso()
        review = SystemRecommendationCandidateReview(
            recommendation_review_id=self._next_id("recommendation_review", self.candidate_reviews_file, "recommendation_review_id"),
            project_id=LOCAL_PROJECT_ID,
            source_object_type=report.source_object_type,
            source_object_id=report.source_object_id,
            eligibility_report_id=report.recommendation_eligibility_report_id,
            risk_profile_id=risk.recommendation_risk_profile_id,
            review_status="pending",
            reviewer_type="user",
            reviewer_note=self._short(normalized.safe_user_note, 500),
            acknowledged_warning_codes=[],
            approved_visibility="private",
            decision_ids=[],
            does_not_create_active_recommendation=True,
            does_not_activate_framework=True,
            does_not_write_story_fact=True,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._guard_safe_payload(model_to_dict(review))
        self._append(self.candidate_reviews_file, model_to_dict(review))
        self._assert_only_allowed_changed(before)
        return review

    def approve_candidate(
        self,
        review_id: str,
        request: RecommendationReviewActionRequest | dict[str, Any] | None = None,
    ) -> RecommendationReviewActionResult:
        normalized = self._normalize_action_request(request)
        review = self.get_review(review_id)
        self._assert_review_mutable(review)
        report = self.get_eligibility_report(review.eligibility_report_id)
        risk = self.get_risk_profile(review.risk_profile_id)
        blockers = []
        if report.can_create_system_recommendation_candidate is not True:
            blockers.append("report_not_candidate_eligible")
        if risk.risk_level in {"high", "blocked"}:
            blockers.append(f"risk_level_{risk.risk_level}")
        blockers.extend(risk.blocking_issues)
        missing_warnings = [
            warning
            for warning in self._dedupe(report.warning_codes + risk.warnings)
            if warning not in normalized.acknowledged_warning_codes
        ]
        if missing_warnings:
            blockers.append("required_warnings_not_acknowledged")
        if self._unresolved_m6_task_exists(report):
            blockers.append("unresolved_m6_propagation_task")
        if blockers:
            raise StorageError("RECOMMENDATION_GOVERNANCE_APPROVAL_BLOCKED: " + ",".join(self._dedupe(blockers)))
        return self._record_review_action(
            review,
            normalized,
            review_status="approved_as_candidate",
            decision_type="promote_to_system_recommendation_candidate",
            resulting_visibility="system_recommendation_candidate",
        )

    def reject_review(
        self,
        review_id: str,
        request: RecommendationReviewActionRequest | dict[str, Any] | None = None,
    ) -> RecommendationReviewActionResult:
        return self._record_review_action(
            self.get_review(review_id),
            self._normalize_action_request(request),
            review_status="rejected",
            decision_type="reject_promotion",
            resulting_visibility="blocked",
        )

    def request_more_evidence(
        self,
        review_id: str,
        request: RecommendationReviewActionRequest | dict[str, Any] | None = None,
    ) -> RecommendationReviewActionResult:
        return self._record_review_action(
            self.get_review(review_id),
            self._normalize_action_request(request),
            review_status="needs_more_evidence",
            decision_type="request_more_evidence",
            resulting_visibility="private",
        )

    def keep_private(
        self,
        review_id: str,
        request: RecommendationReviewActionRequest | dict[str, Any] | None = None,
    ) -> RecommendationReviewActionResult:
        return self._record_review_action(
            self.get_review(review_id),
            self._normalize_action_request(request),
            review_status="private_only",
            decision_type="keep_private",
            resulting_visibility="private",
        )

    def keep_project_local(
        self,
        review_id: str,
        request: RecommendationReviewActionRequest | dict[str, Any] | None = None,
    ) -> RecommendationReviewActionResult:
        return self._record_review_action(
            self.get_review(review_id),
            self._normalize_action_request(request),
            review_status="project_local_only",
            decision_type="keep_project_local",
            resulting_visibility="project_local",
        )

    def list_eligibility_reports(self) -> RecommendationEligibilityReportListResponse:
        reports = self._read_models_if_exists(self.eligibility_reports_file, RecommendationEligibilityReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return RecommendationEligibilityReportListResponse(eligibility_reports=reports, total_count=len(reports))

    def get_eligibility_report(self, report_id: str) -> RecommendationEligibilityReport:
        self._guard_safe_id(report_id, "report_id")
        for report in self._read_models_if_exists(self.eligibility_reports_file, RecommendationEligibilityReport):
            if report.recommendation_eligibility_report_id == report_id:
                return report
        raise StorageError(f"RECOMMENDATION_ELIGIBILITY_REPORT_NOT_FOUND: {report_id}")

    def list_reviews(self) -> SystemRecommendationCandidateReviewListResponse:
        reviews = self._read_models_if_exists(self.candidate_reviews_file, SystemRecommendationCandidateReview)
        reviews.sort(key=lambda item: item.created_at, reverse=True)
        return SystemRecommendationCandidateReviewListResponse(reviews=reviews, total_count=len(reviews))

    def get_review(self, review_id: str) -> SystemRecommendationCandidateReview:
        self._guard_safe_id(review_id, "review_id")
        for review in self._read_models_if_exists(self.candidate_reviews_file, SystemRecommendationCandidateReview):
            if review.recommendation_review_id == review_id:
                return review
        raise StorageError(f"RECOMMENDATION_REVIEW_NOT_FOUND: {review_id}")

    def list_risk_profiles(self) -> RecommendationRiskProfileListResponse:
        profiles = self._read_models_if_exists(self.risk_profiles_file, RecommendationRiskProfile)
        profiles.sort(key=lambda item: item.created_at, reverse=True)
        return RecommendationRiskProfileListResponse(risk_profiles=profiles, total_count=len(profiles))

    def get_risk_profile(self, risk_profile_id: str) -> RecommendationRiskProfile:
        self._guard_safe_id(risk_profile_id, "risk_profile_id")
        for profile in self._read_models_if_exists(self.risk_profiles_file, RecommendationRiskProfile):
            if profile.recommendation_risk_profile_id == risk_profile_id:
                return profile
        raise StorageError(f"RECOMMENDATION_RISK_PROFILE_NOT_FOUND: {risk_profile_id}")

    def list_promotion_decisions(self) -> LibraryPromotionDecisionListResponse:
        decisions = self._read_models_if_exists(self.promotion_decisions_file, LibraryPromotionDecision)
        decisions.sort(key=lambda item: item.created_at, reverse=True)
        return LibraryPromotionDecisionListResponse(promotion_decisions=decisions, total_count=len(decisions))

    def get_promotion_decision(self, decision_id: str) -> LibraryPromotionDecision:
        self._guard_safe_id(decision_id, "decision_id")
        for decision in self._read_models_if_exists(self.promotion_decisions_file, LibraryPromotionDecision):
            if decision.library_promotion_decision_id == decision_id:
                return decision
        raise StorageError(f"RECOMMENDATION_PROMOTION_DECISION_NOT_FOUND: {decision_id}")

    def _record_review_action(
        self,
        review: SystemRecommendationCandidateReview,
        request: RecommendationReviewActionRequest,
        *,
        review_status: RecommendationReviewStatus,
        decision_type: str,
        resulting_visibility: str,
    ) -> RecommendationReviewActionResult:
        self._guard_safe_payload(model_to_dict(request))
        self._assert_review_mutable(review)
        before = self._storage_fingerprints()
        timestamp = now_iso()
        decision_id = self._next_id("library_promotion_decision", self.promotion_decisions_file, "library_promotion_decision_id")
        updated_review = SystemRecommendationCandidateReview(
            **{
                **model_to_dict(review),
                "review_status": review_status,
                "reviewer_note": self._short(request.reviewer_note or request.safe_user_note, 500),
                "acknowledged_warning_codes": self._dedupe(request.acknowledged_warning_codes),
                "approved_visibility": resulting_visibility,
                "decision_ids": self._dedupe(list(review.decision_ids) + [decision_id]),
                "does_not_create_active_recommendation": True,
                "does_not_activate_framework": True,
                "does_not_write_story_fact": True,
                "updated_at": timestamp,
            }
        )
        decision = LibraryPromotionDecision(
            library_promotion_decision_id=decision_id,
            project_id=LOCAL_PROJECT_ID,
            source_object_type=review.source_object_type,
            source_object_id=review.source_object_id,
            eligibility_report_id=review.eligibility_report_id,
            risk_profile_id=review.risk_profile_id,
            recommendation_review_id=review.recommendation_review_id,
            decision_type=decision_type,
            decision_status="recorded",
            user_note=self._short(request.reviewer_note or request.safe_user_note, 500),
            acknowledged_warning_codes=self._dedupe(request.acknowledged_warning_codes),
            resulting_visibility=resulting_visibility,
            does_not_mutate_existing_library_record=True,
            does_not_create_active_recommendation=True,
            does_not_mutate_active_framework=True,
            does_not_create_formal_story_fact=True,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._guard_safe_payload(model_to_dict(updated_review))
        self._guard_safe_payload(model_to_dict(decision))
        self._replace(self.candidate_reviews_file, "recommendation_review_id", review.recommendation_review_id, model_to_dict(updated_review))
        self._append(self.promotion_decisions_file, model_to_dict(decision))
        self._assert_only_allowed_changed(before)
        return RecommendationReviewActionResult(
            success=True,
            review=updated_review,
            promotion_decision=decision,
            safe_summary="M7 review action recorded governance evidence only; no active recommendation or framework mutation occurred.",
        )

    def _assert_review_mutable(self, review: SystemRecommendationCandidateReview) -> None:
        if review.review_status in TERMINAL_REVIEW_STATUSES:
            raise StorageError(
                "RECOMMENDATION_GOVERNANCE_REVIEW_ACTION_BLOCKED: "
                f"terminal_review_status:{review.review_status}"
            )

    def _load_source_context(self, source_object_type: RecommendationSourceObjectType, source_object_id: str) -> SourceContext:
        self._guard_safe_id(source_object_id, "source_object_id")
        if source_object_type == "framework_module_library_item":
            record = self._find_by_id(self.data_dir / ITEMS_FILE, "library_item_id", source_object_id, "RECOMMENDATION_SOURCE_OBJECT_NOT_FOUND")
            item = FrameworkModuleLibraryItem(**record)
            source_refs = [model_to_dict(ref) for ref in item.source_refs]
            maturity = self._optional_model(self.data_dir / MATURITY_FILE, "maturity_record_id", item.maturity_record_id, FrameworkMaturityRecord)
            copyright_record = self._optional_model(self.data_dir / COPYRIGHT_FILE, "copyright_source_record_id", item.copyright_source_record_id, CopyrightSourceRecord)
            label = item.label
            dangling: list[str] = []
            maturities = [maturity] if maturity else []
            copyrights = [copyright_record] if copyright_record else []
        elif source_object_type == "framework_pattern_record":
            record = self._find_by_id(self.data_dir / PATTERNS_FILE, "pattern_id", source_object_id, "RECOMMENDATION_SOURCE_OBJECT_NOT_FOUND")
            pattern = FrameworkPatternRecord(**record)
            source_refs = [model_to_dict(ref) for ref in pattern.source_refs]
            maturity = self._optional_model(self.data_dir / MATURITY_FILE, "maturity_record_id", pattern.maturity_record_id, FrameworkMaturityRecord)
            copyright_record = self._optional_model(self.data_dir / COPYRIGHT_FILE, "copyright_source_record_id", pattern.copyright_source_record_id, CopyrightSourceRecord)
            label = pattern.label
            dangling = []
            maturities = [maturity] if maturity else []
            copyrights = [copyright_record] if copyright_record else []
        elif source_object_type == "module_composition_rule":
            record = self._find_by_id(self.data_dir / COMPOSITION_RULES_FILE, "rule_id", source_object_id, "RECOMMENDATION_SOURCE_OBJECT_NOT_FOUND")
            rule = ModuleCompositionRule(**record)
            source_refs = [model_to_dict(ref) for ref in rule.source_refs]
            child_items, child_patterns, dangling = self._linked_rule_objects(rule)
            label = rule.relation_type
            maturities = self._maturities_for_objects(child_items, child_patterns)
            copyrights = self._copyrights_for_objects(child_items, child_patterns)
        else:
            record = self._find_by_id(self.data_dir / PRIVATE_FRAMEWORKS_FILE, "private_framework_id", source_object_id, "RECOMMENDATION_SOURCE_OBJECT_NOT_FOUND")
            private = UserPrivateFramework(**record)
            child_items, child_patterns, child_rules, dangling = self._linked_private_framework_objects(private)
            source_refs = []
            for item in child_items:
                source_refs.extend([model_to_dict(ref) for ref in item.source_refs])
            for pattern in child_patterns:
                source_refs.extend([model_to_dict(ref) for ref in pattern.source_refs])
            for rule in child_rules:
                source_refs.extend([model_to_dict(ref) for ref in rule.source_refs])
            label = private.title
            maturities = self._maturities_for_objects(child_items, child_patterns)
            copyrights = self._copyrights_for_objects(child_items, child_patterns)

        known_gaps = self._linked_known_gaps(record, source_refs)
        impacts = self._linked_m6_impacts(source_object_id, record, source_refs)
        impact_ids = {impact.impact_record_id for impact in impacts}
        tasks = [
            task
            for task in self._read_models_if_exists(self.data_dir / REVIEW_TASKS_FILE, AffectedObjectReviewTask)
            if task.impact_record_id in impact_ids
        ]
        return SourceContext(
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            source_object_label=label,
            record=record,
            source_refs=source_refs,
            maturity_records=[item for item in maturities if item],
            copyright_records=[item for item in copyrights if item],
            known_gap_records=known_gaps,
            linked_m6_impacts=impacts,
            linked_m6_tasks=tasks,
            dangling_ref_codes=dangling,
        )

    def _policy_findings(
        self,
        context: SourceContext,
    ) -> tuple[list[RecommendationRiskCategory], list[str], list[str]]:
        categories: list[RecommendationRiskCategory] = []
        warnings: list[str] = []
        blockers: list[str] = []
        record = context.record
        source_type = str(record.get("source_type") or "").lower()
        constraint = str(record.get("constraint_strength") or "").lower()
        text = self._search_text(context)

        if not context.source_refs:
            categories.append("missing_source_lineage")
            blockers.append("missing_source_lineage")
        if source_type == "analyze_stories_vocabulary" and constraint in {"reference", "suggestion", ""}:
            categories.append("weak_external_evidence")
            warnings.append("weak_external_evidence")
        if source_type == "m4_reference_only" or constraint == "reference":
            categories.append("reference_only_source")
            warnings.append("reference_only_source")
        if "character_arc_empty_by_design" in text and "character_arc" in text:
            categories.append("character_arc_empty_by_design")
            blockers.append("character_arc_empty_by_design")
        for gap in context.known_gap_records:
            if gap.gap_id == "character_arc_empty_by_design" and gap.gap_status != "closed":
                categories.append("character_arc_empty_by_design")
                blockers.append("character_arc_empty_by_design")
        if context.dangling_ref_codes:
            categories.append("private_framework_dangling_ref")
            blockers.extend(context.dangling_ref_codes)

        copyright_risk = self._copyright_risk(context)
        if copyright_risk == "missing":
            categories.append("copyright_risk")
            blockers.append("missing_copyright_source")
        elif copyright_risk in {"high", "blocked"}:
            categories.append("copyright_risk")
            blockers.append(f"copyright_risk_{copyright_risk}")
        elif copyright_risk == "medium":
            categories.append("copyright_risk")
            warnings.append("copyright_risk_medium")

        maturity = self._maturity_level(context)
        if maturity == "missing":
            categories.append("maturity_too_low")
            blockers.append("missing_maturity_record")
        elif maturity in {"raw_import", "blocked", "deprecated"}:
            categories.append("maturity_too_low")
            if maturity in {"blocked", "deprecated"}:
                blockers.append(f"maturity_{maturity}")
            else:
                warnings.append("maturity_raw_import_private_only")
        elif maturity in {"validated", "validated_with_warnings", "user_reviewed"}:
            if maturity != "user_reviewed":
                categories.append("maturity_too_low")
            warnings.append(f"maturity_{maturity}")

        unresolved_tasks = [task for task in context.linked_m6_tasks if task.task_status in {"pending", "deferred", "blocked"}]
        if unresolved_tasks:
            categories.append("unreviewed_propagation_impact")
            blockers.append("unresolved_m6_propagation_task")
        dismissed_tasks = [task for task in context.linked_m6_tasks if task.task_status == "dismissed"]
        if dismissed_tasks:
            warnings.append("dismissed_m6_task_is_governance_closure_only")
        return self._dedupe(categories), self._dedupe(warnings), self._dedupe(blockers)

    def _risk_level(
        self,
        context: SourceContext,
        categories: list[RecommendationRiskCategory],
        blockers: list[str],
    ) -> RecommendationRiskLevel:
        if blockers:
            return "blocked" if any("character_arc" in item or "dangling" in item or "blocked" in item for item in blockers) else "high"
        if "copyright_risk" in categories and self._copyright_risk(context) == "medium":
            return "medium"
        if categories:
            return "medium"
        return "low"

    def _eligibility_status(
        self,
        context: SourceContext,
        categories: list[RecommendationRiskCategory],
        blockers: list[str],
        risk_level: RecommendationRiskLevel,
    ) -> tuple[str, RecommendationRequiredNextStep, bool]:
        maturity = self._maturity_level(context)
        copyright_risk = self._copyright_risk(context)
        if "character_arc_empty_by_design" in categories or "private_framework_dangling_ref" in categories or maturity in {"blocked", "deprecated"} or copyright_risk in {"high", "blocked"}:
            return "blocked", "reject", False
        if blockers:
            return "needs_more_evidence", "request_more_evidence", False
        if "weak_external_evidence" in categories:
            return "project_local_only", "keep_project_local", False
        if "reference_only_source" in categories:
            return "project_local_only", "keep_project_local", False
        if maturity == "raw_import":
            return "private_only", "keep_private", False
        if maturity == "validated":
            return "project_local_only", "keep_project_local", False
        if maturity in {"validated_with_warnings", "user_reviewed"} or risk_level == "medium":
            return "eligible_with_warnings", "system_recommendation_review", True
        return "eligible_for_review", "system_recommendation_review", True

    def _normalize_action_request(
        self,
        request: RecommendationReviewActionRequest | dict[str, Any] | None,
    ) -> RecommendationReviewActionRequest:
        normalized = request if isinstance(request, RecommendationReviewActionRequest) else RecommendationReviewActionRequest(**(request or {}))
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500 or len(normalized.reviewer_note) > 500:
            raise StorageError("RECOMMENDATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: action_note_too_long")
        return normalized

    def _active_review_for_report_or_source(self, report: RecommendationEligibilityReport) -> SystemRecommendationCandidateReview | None:
        for review in self._read_models_if_exists(self.candidate_reviews_file, SystemRecommendationCandidateReview):
            if review.review_status not in {"pending", "needs_more_evidence"}:
                continue
            if review.eligibility_report_id == report.recommendation_eligibility_report_id:
                return review
            if review.source_object_type == report.source_object_type and review.source_object_id == report.source_object_id:
                return review
        return None

    def _risk_for_report(self, report_id: str) -> RecommendationRiskProfile | None:
        for profile in self._read_models_if_exists(self.risk_profiles_file, RecommendationRiskProfile):
            if profile.eligibility_report_id == report_id:
                return profile
        return None

    def _unresolved_m6_task_exists(self, report: RecommendationEligibilityReport) -> bool:
        impact_ids = set(report.linked_m6_impact_record_ids)
        if not impact_ids:
            return False
        for task in self._read_models_if_exists(self.data_dir / REVIEW_TASKS_FILE, AffectedObjectReviewTask):
            if task.impact_record_id in impact_ids and task.task_status in {"pending", "deferred", "blocked"}:
                return True
        return False

    def _linked_rule_objects(self, rule: ModuleCompositionRule) -> tuple[list[FrameworkModuleLibraryItem], list[FrameworkPatternRecord], list[str]]:
        item_ids = self._dedupe(rule.source_library_item_ids + rule.target_library_item_ids)
        pattern_ids = self._dedupe(rule.source_pattern_ids + rule.target_pattern_ids)
        items, patterns, dangling = [], [], []
        for item_id in item_ids:
            item = self._optional_model(self.data_dir / ITEMS_FILE, "library_item_id", item_id, FrameworkModuleLibraryItem)
            if item:
                items.append(item)
            else:
                dangling.append(f"dangling_library_item_ref:{item_id}")
        for pattern_id in pattern_ids:
            pattern = self._optional_model(self.data_dir / PATTERNS_FILE, "pattern_id", pattern_id, FrameworkPatternRecord)
            if pattern:
                patterns.append(pattern)
            else:
                dangling.append(f"dangling_pattern_ref:{pattern_id}")
        return items, patterns, dangling

    def _linked_private_framework_objects(
        self,
        private: UserPrivateFramework,
    ) -> tuple[list[FrameworkModuleLibraryItem], list[FrameworkPatternRecord], list[ModuleCompositionRule], list[str]]:
        items, patterns, rules, dangling = [], [], [], []
        for item_id in private.item_ids:
            item = self._optional_model(self.data_dir / ITEMS_FILE, "library_item_id", item_id, FrameworkModuleLibraryItem)
            if item:
                items.append(item)
            else:
                dangling.append(f"dangling_library_item_ref:{item_id}")
        for pattern_id in private.pattern_ids:
            pattern = self._optional_model(self.data_dir / PATTERNS_FILE, "pattern_id", pattern_id, FrameworkPatternRecord)
            if pattern:
                patterns.append(pattern)
            else:
                dangling.append(f"dangling_pattern_ref:{pattern_id}")
        for rule_id in private.composition_rule_ids:
            rule = self._optional_model(self.data_dir / COMPOSITION_RULES_FILE, "rule_id", rule_id, ModuleCompositionRule)
            if rule:
                rules.append(rule)
            else:
                dangling.append(f"dangling_composition_rule_ref:{rule_id}")
        return items, patterns, rules, dangling

    def _maturities_for_objects(
        self,
        items: list[FrameworkModuleLibraryItem],
        patterns: list[FrameworkPatternRecord],
    ) -> list[FrameworkMaturityRecord]:
        records = []
        for item in items:
            record = self._optional_model(self.data_dir / MATURITY_FILE, "maturity_record_id", item.maturity_record_id, FrameworkMaturityRecord)
            if record:
                records.append(record)
        for pattern in patterns:
            record = self._optional_model(self.data_dir / MATURITY_FILE, "maturity_record_id", pattern.maturity_record_id, FrameworkMaturityRecord)
            if record:
                records.append(record)
        return records

    def _copyrights_for_objects(
        self,
        items: list[FrameworkModuleLibraryItem],
        patterns: list[FrameworkPatternRecord],
    ) -> list[CopyrightSourceRecord]:
        records = []
        for item in items:
            record = self._optional_model(self.data_dir / COPYRIGHT_FILE, "copyright_source_record_id", item.copyright_source_record_id, CopyrightSourceRecord)
            if record:
                records.append(record)
        for pattern in patterns:
            record = self._optional_model(self.data_dir / COPYRIGHT_FILE, "copyright_source_record_id", pattern.copyright_source_record_id, CopyrightSourceRecord)
            if record:
                records.append(record)
        return records

    def _linked_known_gaps(
        self,
        record: dict[str, Any],
        source_refs: list[dict[str, Any]],
    ) -> list[KnownGapCarryForwardRecord]:
        text = self._safe_json_text({"record": record, "source_refs": source_refs}).lower()
        gaps = []
        for gap in self._read_models_if_exists(self.data_dir / KNOWN_GAPS_FILE, KnownGapCarryForwardRecord):
            if gap.known_gap_record_id.lower() in text or gap.gap_id.lower() in text:
                gaps.append(gap)
        return gaps

    def _linked_m6_impacts(
        self,
        source_object_id: str,
        record: dict[str, Any],
        source_refs: list[dict[str, Any]],
    ) -> list[PropagationImpactRecord]:
        text = self._safe_json_text({"source_object_id": source_object_id, "record": record, "source_refs": source_refs}).lower()
        output = []
        for impact in self._read_models_if_exists(self.data_dir / IMPACT_RECORDS_FILE, PropagationImpactRecord):
            candidates = [
                impact.impact_record_id,
                impact.execution_result_id,
                impact.proposal_id,
                impact.target_id,
                impact.source_lineage_id,
                impact.eligibility_report_id,
            ]
            if any(value and value.lower() in text for value in candidates):
                output.append(impact)
        return output

    def _search_text(self, context: SourceContext) -> str:
        return self._safe_json_text(
            {
                "record": context.record,
                "source_refs": context.source_refs,
                "known_gap_ids": [gap.gap_id for gap in context.known_gap_records],
            }
        ).lower()

    def _source_ref_ids(self, refs: list[dict[str, Any]]) -> list[str]:
        return self._dedupe([self._safe_ref(ref.get("source_ref_id") or ref.get("source_id")) for ref in refs if ref])

    def _lineage_ids(self, refs: list[dict[str, Any]]) -> list[str]:
        values = []
        for ref in refs:
            for key in (
                "source_derivation_report_id",
                "source_imported_framework_decision_id",
                "source_import_id",
                "source_artifact_id",
                "source_candidate_id",
                "source_id",
            ):
                if ref.get(key):
                    values.append(self._safe_ref(ref.get(key)))
        return self._dedupe(values)

    def _maturity_level(self, context: SourceContext) -> str:
        if not context.maturity_records:
            return "missing"
        order = {
            "blocked": 0,
            "deprecated": 1,
            "raw_import": 2,
            "validated": 3,
            "validated_with_warnings": 4,
            "user_reviewed": 5,
            "user_confirmed": 6,
            "system_recommended_candidate": 7,
        }
        return min((record.maturity_level for record in context.maturity_records), key=lambda value: order.get(value, 99))

    def _maturity_confidence(self, context: SourceContext) -> str:
        level = self._maturity_level(context)
        if level in {"user_confirmed", "system_recommended_candidate"}:
            return "high"
        if level in {"user_reviewed", "validated_with_warnings", "validated"}:
            return "medium"
        return "low" if level != "missing" else "unknown"

    def _copyright_risk(self, context: SourceContext) -> str:
        if not context.copyright_records:
            return "missing"
        order = {"low": 0, "medium": 1, "high": 2, "blocked": 3}
        return max((record.risk_level for record in context.copyright_records), key=lambda value: order.get(value, -1))

    def _read_models_if_exists(self, path: Path, model: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        return [model(**item) for item in self.store.read_list(path)]

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        return [item for item in self.store.read_list(path) if isinstance(item, dict)]

    def _find_by_id(self, path: Path, key: str, value: str, error_code: str) -> dict[str, Any]:
        for item in self._read_list(path):
            if item.get(key) == value:
                return item
        raise StorageError(f"{error_code}: {value}")

    def _optional_model(self, path: Path, key: str, value: str, model: type[BaseModel]) -> Any | None:
        if not value:
            return None
        for item in self._read_list(path):
            if item.get(key) == value:
                return model(**item)
        return None

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        values = self._read_list(path)
        values.append(item)
        self.store.write(path, values)

    def _replace(self, path: Path, key: str, value: str, item: dict[str, Any]) -> None:
        values = self._read_list(path)
        for index, existing in enumerate(values):
            if existing.get(key) == value:
                values[index] = item
                self.store.write(path, values)
                return
        raise StorageError(f"RECOMMENDATION_RECORD_NOT_FOUND: {value}")

    def _next_id(self, prefix: str, path: Path, id_key: str) -> str:
        max_index = 0
        for item in self._read_list(path):
            raw = str(item.get(id_key, ""))
            if raw.startswith(prefix):
                suffix = raw.removeprefix(prefix).strip("_")
                try:
                    max_index = max(max_index, int(suffix.split("_")[0]))
                except ValueError:
                    continue
        return f"{prefix}_{max_index + 1:03d}"

    def _storage_fingerprints(self) -> dict[str, str]:
        fingerprints: dict[str, str] = {}
        if not self.data_dir.exists():
            return fingerprints
        for path in sorted(self.data_dir.glob("*.json")):
            try:
                fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise StorageError(f"RECOMMENDATION_GOVERNANCE_STORAGE_SCAN_FAILED: {path.name}") from exc
        return fingerprints

    def _assert_only_allowed_changed(self, before: dict[str, str]) -> None:
        after = self._storage_fingerprints()
        changed = {name for name, value in after.items() if before.get(name) != value}
        changed.update(set(before) - set(after))
        unexpected = sorted(changed - set(ALLOWED_STORAGE_FILES))
        if unexpected:
            raise StorageError(f"RECOMMENDATION_GOVERNANCE_FORBIDDEN_STORAGE_MUTATION: {unexpected}")

    def _guard_safe_id(self, value: str, label: str) -> None:
        self._guard_safe_payload({label: value})

    def _guard_safe_payload(self, payload: Any) -> None:
        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    safe_negative_assertion = normalized_key.startswith("doesnot") and isinstance(child, bool)
                    if not safe_negative_assertion and any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"RECOMMENDATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"RECOMMENDATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"RECOMMENDATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"RECOMMENDATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _safe_json_text(self, payload: Any) -> str:
        return str(payload)

    def _safe_ref(self, value: Any) -> str:
        text = self._short(value or "unknown", 180)
        text = re.sub(r"[^a-zA-Z0-9_:\-.]", "_", text)
        return text or "unknown"

    def _short(self, value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    def _dedupe(self, values: list[Any]) -> list[Any]:
        seen: set[Any] = set()
        output = []
        for value in values:
            if value in {None, ""}:
                continue
            key = str(value)
            if key in seen:
                continue
            seen.add(key)
            output.append(value)
        return output
