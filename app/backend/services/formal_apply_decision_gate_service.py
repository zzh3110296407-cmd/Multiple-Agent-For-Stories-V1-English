from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.formal_apply_decision import (
    FormalApplyApprovalRecord,
    FormalApplyApprovalRecordListResponse,
    FormalApplyApprovedNextStep,
    FormalApplyDecision,
    FormalApplyDecisionEvidenceSnapshot,
    FormalApplyDecisionGateResult,
    FormalApplyDecisionListResponse,
    FormalApplyDecisionReadinessResult,
    FormalApplyDecisionScope,
    FormalApplyDecisionStatusResponse,
    FormalApplyDecisionSubmitRequest,
    FormalApplyQuestion,
    FormalApplyQuestionAnswerRequest,
    FormalApplyQuestionListResponse,
    FormalApplyRejectionRecord,
    FormalApplyRejectionRecordListResponse,
    FormalApplyUserOverride,
    FormalApplyUserOverrideListResponse,
)
from ..models.formal_apply_dry_run import (
    FormalApplyDiffSummary,
    FormalApplyImpactPreview,
    FormalApplyPlan,
    FormalApplyPlanItem,
    FormalApplySafetyCheck,
)
from ..models.formal_apply_eligibility import (
    FormalApplyBlockReason,
    FormalApplyEligibilityReport,
    FormalApplySourceLineage,
    FormalApplyTarget,
)
from ..services.formal_apply_dry_run_service import FormalApplyDryRunService
from ..services.formal_apply_eligibility_service import FormalApplyEligibilityService
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m4_formal_apply_decision_gate_v1"

DECISIONS_FILE = "phase6_formal_apply_decisions.json"
APPROVALS_FILE = "phase6_formal_apply_approval_records.json"
REJECTIONS_FILE = "phase6_formal_apply_rejection_records.json"
OVERRIDES_FILE = "phase6_formal_apply_user_overrides.json"
QUESTIONS_FILE = "phase6_formal_apply_questions.json"
EVIDENCE_SNAPSHOTS_FILE = "phase6_formal_apply_decision_evidence_snapshots.json"
ALLOWED_STORAGE_FILES = [
    DECISIONS_FILE,
    APPROVALS_FILE,
    REJECTIONS_FILE,
    OVERRIDES_FILE,
    QUESTIONS_FILE,
    EVIDENCE_SNAPSHOTS_FILE,
]

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
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "full_user_modification_text",
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
class FormalApplyDecisionContext:
    plan: FormalApplyPlan
    plan_items: list[FormalApplyPlanItem]
    target: FormalApplyTarget | None
    lineage: FormalApplySourceLineage | None
    report: FormalApplyEligibilityReport | None
    block_reasons: list[FormalApplyBlockReason]
    diff_summary: FormalApplyDiffSummary | None
    impact_preview: FormalApplyImpactPreview | None
    safety_check: FormalApplySafetyCheck | None
    missing_artifact_ids: list[str]
    mismatch_ids: list[str]
    hard_blocker_ids: list[str]
    warning_codes: list[str]
    expected_next_step: FormalApplyApprovedNextStep
    decision_scope: FormalApplyDecisionScope


class FormalApplyDecisionGateService:
    """Phase 6 M4 user decision gate.

    M4 records user decision audit only. It never writes the global
    decisions ledger, proposals, apply results, active framework state, or
    formal story records.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        dry_run_service: FormalApplyDryRunService | None = None,
        eligibility_service: FormalApplyEligibilityService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.decisions_file = self.data_dir / DECISIONS_FILE
        self.approvals_file = self.data_dir / APPROVALS_FILE
        self.rejections_file = self.data_dir / REJECTIONS_FILE
        self.overrides_file = self.data_dir / OVERRIDES_FILE
        self.questions_file = self.data_dir / QUESTIONS_FILE
        self.evidence_snapshots_file = self.data_dir / EVIDENCE_SNAPSHOTS_FILE
        self.eligibility_service = eligibility_service or FormalApplyEligibilityService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.dry_run_service = dry_run_service or FormalApplyDryRunService(
            store=self.store,
            data_dir=self.data_dir,
            eligibility_service=self.eligibility_service,
        )

    def get_status(self) -> FormalApplyDecisionStatusResponse:
        decisions = self._read_models_if_exists(self.decisions_file, FormalApplyDecision)
        decisions.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyDecisionStatusResponse(
            decision_count=len(decisions),
            approval_count=len(self._read_models_if_exists(self.approvals_file, FormalApplyApprovalRecord)),
            rejection_count=len(self._read_models_if_exists(self.rejections_file, FormalApplyRejectionRecord)),
            override_count=len(self._read_models_if_exists(self.overrides_file, FormalApplyUserOverride)),
            question_count=len(self._read_models_if_exists(self.questions_file, FormalApplyQuestion)),
            evidence_snapshot_count=len(
                self._read_models_if_exists(self.evidence_snapshots_file, FormalApplyDecisionEvidenceSnapshot)
            ),
            latest_decision_record_id=decisions[0].decision_record_id if decisions else None,
            global_decision_write_disabled=True,
            apply_execution_disabled=True,
            proposal_creation_disabled=True,
            formal_story_write_disabled=True,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            safe_summary=(
                "Phase 6 M4 records user decision audit only. It creates no global decisions, "
                "proposals, apply results, active framework mutations, or formal story writes."
            ),
        )

    def get_plan_readiness(self, plan_id: str) -> FormalApplyDecisionReadinessResult:
        self._guard_safe_id(plan_id, "plan_id")
        context = self._load_context(plan_id)
        return self._readiness_from_context(context)

    def submit_decision(
        self,
        plan_id: str,
        request: FormalApplyDecisionSubmitRequest | dict[str, Any],
    ) -> FormalApplyDecisionGateResult:
        self._guard_safe_id(plan_id, "plan_id")
        normalized = request if isinstance(request, FormalApplyDecisionSubmitRequest) else FormalApplyDecisionSubmitRequest(**request)
        self._guard_request(normalized)
        self._ensure_storage_files()
        context = self._load_context(plan_id)
        readiness = self._readiness_from_context(context)
        timestamp = now_iso()
        decision_id = self._next_id("formal_apply_decision", self.decisions_file, "decision_record_id")
        snapshot_id = f"{decision_id}_evidence_snapshot"
        requested_next_step = normalized.approved_next_step or readiness.expected_approved_next_step
        approval_like = normalized.decision_type in {"approve_for_next_step", "override_warning_and_approve"}
        approval_allowed = False
        approval_blockers: list[str] = []
        if approval_like:
            approval_allowed, approval_blockers = self._approval_allowed(normalized, readiness, requested_next_step)
        decision_status = "recorded"
        gate_status = "recorded_no_approval"
        if approval_like:
            decision_status = "recorded" if approval_allowed else "blocked"
            gate_status = "allowed" if approval_allowed else "blocked"

        blocked_reason_ids = self._dedupe(readiness.blocked_reason_ids + approval_blockers)
        decision = FormalApplyDecision(
            decision_record_id=decision_id,
            project_id=context.plan.project_id or LOCAL_PROJECT_ID,
            target_id=context.plan.target_id,
            source_lineage_id=context.plan.source_lineage_id,
            eligibility_report_id=context.plan.eligibility_report_id,
            plan_id=context.plan.plan_id,
            impact_preview_id=context.impact_preview.impact_preview_id if context.impact_preview else "",
            diff_summary_id=context.diff_summary.diff_summary_id if context.diff_summary else "",
            safety_check_id=context.safety_check.safety_check_id if context.safety_check else "",
            evidence_snapshot_id=snapshot_id,
            global_decision_id=None,
            decision_type=normalized.decision_type,
            decision_status=decision_status,  # type: ignore[arg-type]
            decision_scope=readiness.decision_scope,
            approved_next_step=requested_next_step if approval_allowed else "none",
            requires_m5_execution=bool(approval_allowed and requested_next_step.startswith("m5_")),
            authorizes_formal_record_write=False,
            authorizes_apply_execution_now=False,
            authorizes_proposal_creation_now=False,
            creates_formal_record_now=False,
            writes_formal_story_fact_now=False,
            no_formal_write_performed=True,
            user_note=self._short(normalized.user_note, 500),
            blocked_reason_ids=blocked_reason_ids,
            warning_codes=readiness.warning_codes,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        evidence_snapshot = self._build_evidence_snapshot(context, decision, timestamp)
        approval_record: FormalApplyApprovalRecord | None = None
        override_record: FormalApplyUserOverride | None = None
        rejection_record: FormalApplyRejectionRecord | None = None
        question: FormalApplyQuestion | None = None

        if approval_allowed:
            if normalized.decision_type == "override_warning_and_approve":
                override_record = FormalApplyUserOverride(
                    override_id=f"{decision_id}_override",
                    decision_record_id=decision_id,
                    target_id=context.plan.target_id,
                    plan_id=context.plan.plan_id,
                    override_type="warning_override",
                    override_reason=self._short(normalized.override_reason, 500),
                    acknowledged_warning_codes=self._dedupe(normalized.acknowledged_warning_codes),
                    non_overridable_block_reason_ids=[],
                    created_at=timestamp,
                    version_id=SCHEMA_VERSION,
                )
            approval_record = FormalApplyApprovalRecord(
                approval_id=f"{decision_id}_approval",
                decision_record_id=decision_id,
                target_id=context.plan.target_id,
                plan_id=context.plan.plan_id,
                approval_type=normalized.decision_type,
                approved_next_step=requested_next_step,
                acknowledged_warning_codes=self._dedupe(normalized.acknowledged_warning_codes),
                override_record_ids=[override_record.override_id] if override_record else [],
                user_confirmation_text=self._short(normalized.user_note or normalized.override_reason, 500),
                authorizes_apply_execution_now=False,
                authorizes_proposal_creation_now=False,
                creates_formal_record_now=False,
                no_formal_write_performed=True,
                created_at=timestamp,
                version_id=SCHEMA_VERSION,
            )
        elif normalized.decision_type == "reject":
            rejection_record = FormalApplyRejectionRecord(
                rejection_id=f"{decision_id}_rejection",
                decision_record_id=decision_id,
                target_id=context.plan.target_id,
                plan_id=context.plan.plan_id,
                rejection_reason=self._short(normalized.rejection_reason or normalized.user_note, 500),
                safe_summary="User rejected the M3 plan. M4 recorded audit only.",
                created_at=timestamp,
                version_id=SCHEMA_VERSION,
            )
        elif normalized.decision_type == "request_more_evidence":
            question_text = normalized.question_text or normalized.user_note or "More evidence requested before M5."
            question = FormalApplyQuestion(
                question_id=f"{decision_id}_question",
                decision_record_id=decision_id,
                target_id=context.plan.target_id,
                plan_id=context.plan.plan_id,
                question_type="more_evidence",
                question_text=self._short(question_text, 600),
                question_status="open",
                answer_text="",
                answered_at=None,
                safe_summary="User requested more evidence. M4 created a question only.",
                created_at=timestamp,
                updated_at=timestamp,
                version_id=SCHEMA_VERSION,
            )

        self._guard_safe_payload(model_to_dict(decision))
        self._guard_safe_payload(model_to_dict(evidence_snapshot))
        if approval_record:
            self._guard_safe_payload(model_to_dict(approval_record))
        if override_record:
            self._guard_safe_payload(model_to_dict(override_record))
        if rejection_record:
            self._guard_safe_payload(model_to_dict(rejection_record))
        if question:
            self._guard_safe_payload(model_to_dict(question))

        self._append(self.decisions_file, model_to_dict(decision))
        self._append(self.evidence_snapshots_file, model_to_dict(evidence_snapshot))
        if override_record:
            self._append(self.overrides_file, model_to_dict(override_record))
        if approval_record:
            self._append(self.approvals_file, model_to_dict(approval_record))
        if rejection_record:
            self._append(self.rejections_file, model_to_dict(rejection_record))
        if question:
            self._append(self.questions_file, model_to_dict(question))

        return FormalApplyDecisionGateResult(
            success=approval_allowed or not approval_like,
            gate_status=gate_status,  # type: ignore[arg-type]
            plan_id=context.plan.plan_id,
            target_id=context.plan.target_id,
            decision=decision,
            approval_record=approval_record,
            rejection_record=rejection_record,
            override_record=override_record,
            question=question,
            evidence_snapshot=evidence_snapshot,
            allowed_next_step=requested_next_step if approval_allowed else "none",
            can_enter_m5=bool(approval_record and requested_next_step.startswith("m5_")),
            blocked_reason_ids=blocked_reason_ids,
            warning_codes=readiness.warning_codes,
            safe_summary=self._result_summary(normalized.decision_type, approval_allowed, approval_like),
        )

    def list_decisions(self) -> FormalApplyDecisionListResponse:
        decisions = self._read_models_if_exists(self.decisions_file, FormalApplyDecision)
        decisions.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyDecisionListResponse(decisions=decisions, total_count=len(decisions))

    def get_decision(self, decision_record_id: str) -> FormalApplyDecision:
        self._guard_safe_id(decision_record_id, "decision_record_id")
        for decision in self._read_models_if_exists(self.decisions_file, FormalApplyDecision):
            if decision.decision_record_id == decision_record_id:
                return decision
        raise StorageError(f"FORMAL_APPLY_DECISION_NOT_FOUND: {decision_record_id}")

    def get_evidence_snapshot(self, decision_record_id: str) -> FormalApplyDecisionEvidenceSnapshot:
        decision = self.get_decision(decision_record_id)
        for snapshot in self._read_models_if_exists(self.evidence_snapshots_file, FormalApplyDecisionEvidenceSnapshot):
            if snapshot.evidence_snapshot_id == decision.evidence_snapshot_id:
                return snapshot
        raise StorageError(f"FORMAL_APPLY_DECISION_EVIDENCE_SNAPSHOT_NOT_FOUND: {decision_record_id}")

    def list_approvals(self) -> FormalApplyApprovalRecordListResponse:
        approvals = self._read_models_if_exists(self.approvals_file, FormalApplyApprovalRecord)
        approvals.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyApprovalRecordListResponse(approval_records=approvals, total_count=len(approvals))

    def list_rejections(self) -> FormalApplyRejectionRecordListResponse:
        rejections = self._read_models_if_exists(self.rejections_file, FormalApplyRejectionRecord)
        rejections.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyRejectionRecordListResponse(rejection_records=rejections, total_count=len(rejections))

    def list_overrides(self) -> FormalApplyUserOverrideListResponse:
        overrides = self._read_models_if_exists(self.overrides_file, FormalApplyUserOverride)
        overrides.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyUserOverrideListResponse(override_records=overrides, total_count=len(overrides))

    def list_questions(self) -> FormalApplyQuestionListResponse:
        questions = self._read_models_if_exists(self.questions_file, FormalApplyQuestion)
        questions.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyQuestionListResponse(questions=questions, total_count=len(questions))

    def get_question(self, question_id: str) -> FormalApplyQuestion:
        self._guard_safe_id(question_id, "question_id")
        for question in self._read_models_if_exists(self.questions_file, FormalApplyQuestion):
            if question.question_id == question_id:
                return question
        raise StorageError(f"FORMAL_APPLY_QUESTION_NOT_FOUND: {question_id}")

    def answer_question(
        self,
        question_id: str,
        request: FormalApplyQuestionAnswerRequest | dict[str, Any],
    ) -> FormalApplyQuestion:
        self._guard_safe_id(question_id, "question_id")
        normalized = request if isinstance(request, FormalApplyQuestionAnswerRequest) else FormalApplyQuestionAnswerRequest(**request)
        self._guard_safe_payload(model_to_dict(normalized))
        questions = self._read_models_if_exists(self.questions_file, FormalApplyQuestion)
        timestamp = now_iso()
        updated: list[FormalApplyQuestion] = []
        result: FormalApplyQuestion | None = None
        for question in questions:
            if question.question_id != question_id:
                updated.append(question)
                continue
            result = FormalApplyQuestion(
                **{
                    **model_to_dict(question),
                    "question_status": "answered",
                    "answer_text": self._short(normalized.answer_text, 600),
                    "answered_at": timestamp,
                    "updated_at": timestamp,
                    "safe_summary": "User answered the M4 evidence question. No approval or write was created.",
                }
            )
            updated.append(result)
        if result is None:
            raise StorageError(f"FORMAL_APPLY_QUESTION_NOT_FOUND: {question_id}")
        self._guard_safe_payload(model_to_dict(result))
        self.store.write(self.questions_file, [model_to_dict(item) for item in updated])
        return result

    def _load_context(self, plan_id: str) -> FormalApplyDecisionContext:
        plan = self.dry_run_service.get_plan(plan_id)
        plan_items = self.dry_run_service.list_plan_items(plan_id).plan_items
        diff_summary = self._first_by_plan(self.dry_run_service.list_diff_summaries().diff_summaries, plan_id)
        impact_preview = self._first_by_plan(self.dry_run_service.list_impact_previews().impact_previews, plan_id)
        safety_check = self._first_by_plan(self.dry_run_service.list_safety_checks().safety_checks, plan_id)

        missing: list[str] = []
        mismatches: list[str] = []
        target: FormalApplyTarget | None = None
        lineage: FormalApplySourceLineage | None = None
        report: FormalApplyEligibilityReport | None = None
        try:
            target = self.eligibility_service.get_target(plan.target_id)
        except StorageError:
            missing.append("m2_target_missing")
        try:
            lineage = self.eligibility_service.get_source_lineage(plan.source_lineage_id)
        except StorageError:
            missing.append("m2_source_lineage_missing")
        try:
            report = self.eligibility_service.get_eligibility_report(plan.eligibility_report_id)
        except StorageError:
            missing.append("m2_eligibility_report_missing")
        if not plan_items:
            missing.append("m3_plan_items_missing")
        if diff_summary is None:
            missing.append("m3_diff_summary_missing")
        if impact_preview is None:
            missing.append("m3_impact_preview_missing")
        if safety_check is None:
            missing.append("m3_safety_check_missing")
        if report and report.target_id != plan.target_id:
            mismatches.append("m2_report_target_mismatch")
        if report and report.lineage_id != plan.source_lineage_id:
            mismatches.append("m2_report_lineage_mismatch")
        if target and target.target_id != plan.target_id:
            mismatches.append("m2_target_id_mismatch")
        if lineage and lineage.target_id != plan.target_id:
            mismatches.append("m2_lineage_target_mismatch")
        if diff_summary and diff_summary.target_id != plan.target_id:
            mismatches.append("m3_diff_target_mismatch")
        if impact_preview and impact_preview.target_id != plan.target_id:
            mismatches.append("m3_impact_target_mismatch")
        if safety_check and safety_check.target_id != plan.target_id:
            mismatches.append("m3_safety_target_mismatch")

        block_reasons = []
        if report:
            block_reasons = [
                reason
                for reason in self.eligibility_service.list_block_reasons().block_reasons
                if reason.reason_id in set(report.block_reason_ids)
            ]
        warning_codes = self._collect_warning_codes(plan, report, safety_check)
        hard_blockers = self._collect_hard_blockers(
            plan=plan,
            plan_items=plan_items,
            report=report,
            block_reasons=block_reasons,
            diff_summary=diff_summary,
            impact_preview=impact_preview,
            safety_check=safety_check,
            missing=missing,
            mismatches=mismatches,
        )
        return FormalApplyDecisionContext(
            plan=plan,
            plan_items=plan_items,
            target=target,
            lineage=lineage,
            report=report,
            block_reasons=block_reasons,
            diff_summary=diff_summary,
            impact_preview=impact_preview,
            safety_check=safety_check,
            missing_artifact_ids=missing,
            mismatch_ids=mismatches,
            hard_blocker_ids=hard_blockers,
            warning_codes=warning_codes,
            expected_next_step=self._expected_next_step(plan.target_type),
            decision_scope=self._decision_scope(plan.target_type),
        )

    def _readiness_from_context(self, context: FormalApplyDecisionContext) -> FormalApplyDecisionReadinessResult:
        plan = context.plan
        safety_status = context.safety_check.safety_status if context.safety_check else "missing"
        no_write_guarantees = {
            "m2_no_formal_write_performed": bool(context.report and context.report.no_formal_write_performed),
            "m3_plan_no_formal_write_performed": plan.no_formal_write_performed,
            "m3_plan_preview_record_only": plan.preview_record_only,
            "m3_diff_no_formal_write_performed": bool(context.diff_summary and context.diff_summary.no_formal_write_performed),
            "m3_impact_no_formal_story_write": bool(
                context.impact_preview and not context.impact_preview.formal_story_fact_write_attempted
            ),
            "m3_safety_no_apply_result": bool(context.safety_check and context.safety_check.no_apply_result_created),
            "m4_no_global_decision_write": True,
        }
        approval_ready = (
            plan.plan_status == "ready_for_m4_decision"
            and plan.can_enter_m4_decision
            and plan.requires_user_decision_before_apply
            and safety_status in {"pass", "warn"}
            and not context.hard_blocker_ids
            and context.expected_next_step != "none"
        )
        return FormalApplyDecisionReadinessResult(
            success=True,
            gate_status="allowed" if approval_ready and safety_status == "pass" else "blocked",
            plan_id=plan.plan_id,
            target_id=plan.target_id,
            target_type=plan.target_type,
            source_lineage_id=plan.source_lineage_id,
            eligibility_report_id=plan.eligibility_report_id,
            diff_summary_id=context.diff_summary.diff_summary_id if context.diff_summary else "",
            impact_preview_id=context.impact_preview.impact_preview_id if context.impact_preview else "",
            safety_check_id=context.safety_check.safety_check_id if context.safety_check else "",
            plan_status=plan.plan_status,
            safety_status=safety_status,
            can_enter_m4_decision=plan.can_enter_m4_decision,
            can_record_approval=approval_ready,
            can_request_more_evidence=True,
            can_reject_defer_cancel=True,
            allowed_next_step=plan.allowed_next_step,
            expected_approved_next_step=context.expected_next_step,
            decision_scope=context.decision_scope,
            requires_m5_execution=context.expected_next_step.startswith("m5_"),
            hard_blocker_ids=context.hard_blocker_ids,
            blocked_reason_ids=self._dedupe(
                plan.block_reason_ids
                + (context.safety_check.block_reason_ids if context.safety_check else [])
                + context.missing_artifact_ids
                + context.mismatch_ids
                + context.hard_blocker_ids
            ),
            warning_codes=context.warning_codes,
            non_authorized_actions=[
                "apply_execution_now",
                "proposal_creation_now",
                "global_decision_write",
                "formal_story_fact_write",
                "active_framework_mutation",
                "event_memory_state_scene_write",
                "automatic_recommendation_promotion",
            ],
            artifact_ids={
                "target_id": plan.target_id,
                "source_lineage_id": plan.source_lineage_id,
                "eligibility_report_id": plan.eligibility_report_id,
                "plan_id": plan.plan_id,
                "diff_summary_id": context.diff_summary.diff_summary_id if context.diff_summary else "",
                "impact_preview_id": context.impact_preview.impact_preview_id if context.impact_preview else "",
                "safety_check_id": context.safety_check.safety_check_id if context.safety_check else "",
            },
            no_write_guarantees=no_write_guarantees,
            safe_summary=(
                f"M4 readiness for {plan.plan_id}: plan={plan.plan_status}, safety={safety_status}. "
                "Approval can only authorize a later next step; M4 performs no write."
            ),
        )

    def _approval_allowed(
        self,
        request: FormalApplyDecisionSubmitRequest,
        readiness: FormalApplyDecisionReadinessResult,
        requested_next_step: str,
    ) -> tuple[bool, list[str]]:
        blockers: list[str] = []
        if not readiness.can_record_approval:
            blockers.append("m4_readiness_not_approvable")
        if requested_next_step != readiness.expected_approved_next_step or requested_next_step == "none":
            blockers.append("approved_next_step_mismatch")
        if request.decision_type == "approve_for_next_step" and readiness.warning_codes:
            blockers.append("warning_override_required")
        if request.decision_type == "override_warning_and_approve":
            if not readiness.warning_codes:
                blockers.append("warning_override_without_warning")
            if not request.override_reason.strip():
                blockers.append("override_reason_required")
            missing_ack = sorted(set(readiness.warning_codes) - set(request.acknowledged_warning_codes))
            if missing_ack:
                blockers.append("all_warning_codes_must_be_acknowledged")
        if readiness.safety_status == "block":
            blockers.append("safety_block_not_overridable")
        if readiness.hard_blocker_ids:
            blockers.append("hard_blocker_not_overridable")
        return not blockers, self._dedupe(blockers)

    def _build_evidence_snapshot(
        self,
        context: FormalApplyDecisionContext,
        decision: FormalApplyDecision,
        timestamp: str,
    ) -> FormalApplyDecisionEvidenceSnapshot:
        plan = context.plan
        evidence_payloads: dict[str, Any] = {
            "target": context.target,
            "source_lineage": context.lineage,
            "eligibility_report": context.report,
            "plan": context.plan,
            "plan_items": context.plan_items,
            "diff_summary": context.diff_summary,
            "impact_preview": context.impact_preview,
            "safety_check": context.safety_check,
        }
        hashes: dict[str, str] = {}
        summaries: list[str] = []
        for key, value in evidence_payloads.items():
            safe_value = self._safe_evidence_value(value)
            hashes[key] = self._fingerprint(safe_value)
            summaries.append(f"{key}: {self._safe_summary_for(value)}")
        snapshot = FormalApplyDecisionEvidenceSnapshot(
            evidence_snapshot_id=decision.evidence_snapshot_id,
            decision_record_id=decision.decision_record_id,
            target_id=plan.target_id,
            source_lineage_id=plan.source_lineage_id,
            eligibility_report_id=plan.eligibility_report_id,
            plan_id=plan.plan_id,
            impact_preview_id=context.impact_preview.impact_preview_id if context.impact_preview else "",
            diff_summary_id=context.diff_summary.diff_summary_id if context.diff_summary else "",
            safety_check_id=context.safety_check.safety_check_id if context.safety_check else "",
            plan_status=plan.plan_status,
            safety_status=context.safety_check.safety_status if context.safety_check else "missing",
            allowed_next_step=plan.allowed_next_step,
            block_reason_ids=decision.blocked_reason_ids,
            warning_codes=decision.warning_codes,
            before_fingerprints=dict(plan.before_fingerprints),
            after_fingerprint_previews=dict(plan.after_fingerprint_previews),
            evidence_hashes=hashes,
            safe_summaries=summaries,
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return snapshot

    def _collect_hard_blockers(
        self,
        *,
        plan: FormalApplyPlan,
        plan_items: list[FormalApplyPlanItem],
        report: FormalApplyEligibilityReport | None,
        block_reasons: list[FormalApplyBlockReason],
        diff_summary: FormalApplyDiffSummary | None,
        impact_preview: FormalApplyImpactPreview | None,
        safety_check: FormalApplySafetyCheck | None,
        missing: list[str],
        mismatches: list[str],
    ) -> list[str]:
        blockers = list(missing) + list(mismatches)
        if plan.plan_status != "ready_for_m4_decision":
            blockers.append(f"plan_status_{plan.plan_status}")
        if not plan.can_enter_m4_decision:
            blockers.append("plan_cannot_enter_m4_decision")
        if not plan.requires_user_decision_before_apply:
            blockers.append("plan_missing_required_user_decision")
        if plan.can_write_formal_record_now or plan.creates_formal_record_now or plan.writes_formal_story_fact_now:
            blockers.append("m3_plan_write_flag_inconsistent")
        if not plan.no_formal_write_performed or not plan.preview_record_only:
            blockers.append("m3_plan_no_write_guarantee_failed")
        if report:
            if report.can_write_formal_record_now or report.creates_formal_record_now or report.writes_formal_story_fact_now:
                blockers.append("m2_report_write_flag_inconsistent")
            if not report.no_formal_write_performed:
                blockers.append("m2_report_no_write_guarantee_failed")
        for reason in block_reasons:
            if reason.severity == "blocking":
                blockers.append(reason.reason_id)
            if reason.reason_code == "reference_only_evidence_cannot_mutate":
                blockers.append("reference_only_evidence_cannot_mutate")
            if reason.reason_code == "set_active_not_supported_in_m2_v1":
                blockers.append("imported_framework_set_active_target_blocked")
            if reason.reason_code == "character_arc_empty_by_design_source_not_apply_eligible":
                blockers.append("character_arc_empty_by_design_requires_user_supplement")
        for item in plan_items:
            if not item.no_write_guarantee:
                blockers.append(f"{item.item_id}_no_write_guarantee_failed")
            if item.write_intent not in {"future_user_confirmed_merge", "future_proposal_creation", "future_governance_review", "none"}:
                blockers.append(f"{item.item_id}_unsupported_write_intent")
        blockers.extend(self._plan_preview_next_step_mismatches(plan, plan_items))
        if diff_summary:
            if not diff_summary.no_formal_write_performed:
                blockers.append("m3_diff_no_write_guarantee_failed")
            if not diff_summary.no_prose_diff or not diff_summary.no_full_chapter_rewrite:
                blockers.append("m3_diff_prose_or_full_rewrite_not_allowed")
        if impact_preview:
            if impact_preview.formal_story_fact_write_attempted:
                blockers.append("formal_story_fact_write_attempted")
            if impact_preview.event_memory_state_scene_write_attempted:
                blockers.append("event_memory_state_scene_write_attempted")
            if impact_preview.active_framework_mutation_attempted:
                blockers.append("active_framework_mutation_attempted")
            if impact_preview.full_chapter_framework_prebuild_attempted:
                blockers.append("full_chapter_framework_prebuild_attempted")
        if safety_check:
            if safety_check.safety_status == "block":
                blockers.append("safety_status_block")
            for item in safety_check.check_items:
                if isinstance(item, dict) and item.get("status") == "block":
                    blockers.append(str(item.get("check_id") or "safety_item_block"))
            for flag in (
                "no_decision_created",
                "no_proposal_created",
                "no_apply_result_created",
                "no_formal_record_created",
                "no_active_framework_mutation",
                "no_raw_prompt",
                "no_raw_response",
                "no_hidden_reasoning",
                "no_secret_like_material",
                "no_full_prose",
            ):
                if getattr(safety_check, flag) is not True:
                    blockers.append(f"m3_safety_{flag}_failed")
        return self._dedupe(blockers)

    def _plan_preview_next_step_mismatches(
        self,
        plan: FormalApplyPlan,
        plan_items: list[FormalApplyPlanItem],
    ) -> list[str]:
        if plan.plan_status != "ready_for_m4_decision":
            return []
        expected_step = self._expected_next_step(plan.target_type)
        contracts = {
            "m5_create_framework_apply_proposal": {
                "item_type": "framework_merge_preview",
                "action_preview": "preview_framework_merge_for_later_user_decision",
                "write_intent": "future_user_confirmed_merge",
            },
            "m5_create_chapter_archive_proposal": {
                "item_type": "chapter_archive_proposal_preview",
                "action_preview": "create_chapter_archive_proposal_later",
                "write_intent": "future_proposal_creation",
            },
            "m5_create_narrative_debt_proposal": {
                "item_type": "narrative_debt_proposal_preview",
                "action_preview": "create_narrative_debt_proposal_later",
                "write_intent": "future_proposal_creation",
            },
        }
        contract = contracts.get(expected_step)
        if contract is None:
            return []
        if not plan_items:
            return ["m3_plan_preview_next_step_mismatch"]
        mismatches: list[str] = []
        for item in plan_items:
            for field_name, expected_value in contract.items():
                if getattr(item, field_name) != expected_value:
                    mismatches.append(f"m3_plan_preview_next_step_mismatch_{field_name}")
        return self._dedupe(mismatches)

    def _collect_warning_codes(
        self,
        plan: FormalApplyPlan,
        report: FormalApplyEligibilityReport | None,
        safety_check: FormalApplySafetyCheck | None,
    ) -> list[str]:
        warnings = list(plan.warnings)
        if report:
            warnings.extend(report.warnings)
        if safety_check:
            for item in safety_check.check_items:
                if isinstance(item, dict) and item.get("status") == "warn":
                    warnings.append(str(item.get("check_id") or item.get("safe_summary") or "safety_warning"))
        return self._dedupe([self._short(value, 160) for value in warnings if value])

    def _expected_next_step(self, target_type: str) -> FormalApplyApprovedNextStep:
        mapping: dict[str, FormalApplyApprovedNextStep] = {
            "imported_framework_merge_target": "m5_create_framework_apply_proposal",
            "chapter_archive_candidate_target": "m5_create_chapter_archive_proposal",
            "narrative_debt_candidate_target": "m5_create_narrative_debt_proposal",
            "recommendation_promotion_target": "m7_recommendation_governance_review",
        }
        return mapping.get(target_type, "none")

    def _decision_scope(self, target_type: str) -> FormalApplyDecisionScope:
        mapping: dict[str, FormalApplyDecisionScope] = {
            "imported_framework_merge_target": "framework_apply",
            "chapter_archive_candidate_target": "chapter_archive_proposal",
            "narrative_debt_candidate_target": "narrative_debt_proposal",
            "recommendation_promotion_target": "recommendation_governance",
        }
        return mapping.get(target_type, "view_only")

    def _first_by_plan(self, values: list[Any], plan_id: str) -> Any | None:
        for value in values:
            if getattr(value, "plan_id", None) == plan_id:
                return value
        return None

    def _ensure_storage_files(self) -> None:
        for path in (
            self.decisions_file,
            self.approvals_file,
            self.rejections_file,
            self.overrides_file,
            self.questions_file,
            self.evidence_snapshots_file,
        ):
            self.store.write_if_missing(path, [])

    def _read_models_if_exists(self, path: Path, model: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        return [model(**item) for item in self.store.read_list(path)]

    def _read_list(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        return self.store.read_list(path)

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        data = self._read_list(path)
        data.append(item)
        self.store.write(path, data)

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

    def _safe_evidence_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, list):
            return [self._safe_evidence_value(item) for item in value]
        if isinstance(value, BaseModel):
            return model_to_dict(value)
        if isinstance(value, dict):
            return dict(value)
        return value

    def _safe_summary_for(self, value: Any) -> str:
        if value is None:
            return "missing"
        if isinstance(value, list):
            return f"{len(value)} records"
        payload = model_to_dict(value) if isinstance(value, BaseModel) else value
        if isinstance(payload, dict):
            return self._short(
                payload.get("safe_summary")
                or payload.get("target_label")
                or payload.get("reason_code")
                or payload.get("plan_status")
                or "safe artifact present",
                260,
            )
        return self._short(str(value), 260)

    def _guard_safe_id(self, value: str, label: str) -> None:
        self._guard_safe_payload({label: value})

    def _guard_request(self, request: FormalApplyDecisionSubmitRequest) -> None:
        self._guard_safe_payload(model_to_dict(request))
        for field in ("user_note", "override_reason", "question_text", "rejection_reason"):
            value = getattr(request, field)
            if len(value) > 1000:
                raise StorageError(f"FORMAL_APPLY_DECISION_UNSAFE_PAYLOAD_BLOCKED: {field}_too_long")

    def _guard_safe_payload(self, payload: Any) -> None:
        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    safe_negative_assertion = normalized_key.startswith("no") and isinstance(child, bool)
                    if not safe_negative_assertion and any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"FORMAL_APPLY_DECISION_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"FORMAL_APPLY_DECISION_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_DECISION_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_DECISION_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _fingerprint(self, payload: Any) -> str:
        self._guard_safe_payload(payload)
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _result_summary(self, decision_type: str, approval_allowed: bool, approval_like: bool) -> str:
        if approval_like and approval_allowed:
            return "M4 recorded a user approval for a later next step. No M5 execution or proposal was created."
        if approval_like:
            return "M4 blocked the approval attempt and created no approval record."
        return f"M4 recorded {decision_type}. No approval, proposal, apply result, or formal write was created."

    def _short(self, text: Any, limit: int) -> str:
        value = " ".join(str(text or "").split())
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 3)] + "..."

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output
