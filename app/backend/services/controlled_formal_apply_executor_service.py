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
    FormalApplyApprovedNextStep,
    FormalApplyDecision,
    FormalApplyDecisionEvidenceSnapshot,
)
from ..models.formal_apply_dry_run import (
    FormalApplyDiffSummary,
    FormalApplyImpactPreview,
    FormalApplyPlan,
    FormalApplyPlanItem,
    FormalApplySafetyCheck,
)
from ..models.formal_apply_eligibility import (
    FormalApplyEligibilityReport,
    FormalApplySourceLineage,
    FormalApplyTarget,
)
from ..models.formal_apply_execution import (
    ChapterArchiveProposal,
    ChapterArchiveProposalListResponse,
    ControlledApplyWriteAudit,
    ControlledApplyWriteAuditListResponse,
    FormalApplyExecutionReadiness,
    FormalApplyExecutionRequest,
    FormalApplyExecutionResult,
    FormalApplyExecutionResultListResponse,
    FormalApplyExecutionStatus,
    FormalApplyExecutionStatusResponse,
    FormalApplyExecutionType,
    FormalApplyM6HandoffStatus,
    FormalApplyM7HandoffStatus,
    FormalApplyProposalListResponse,
    FormalApplyProposalStatusResponse,
    FormalApplyProposalType,
    FormalApplyRollbackRef,
    FormalApplyRollbackRefListResponse,
    FrameworkApplyProposal,
    FrameworkApplyProposalListResponse,
    NarrativeDebtProposal,
    NarrativeDebtProposalListResponse,
)
from ..services.analyze_stories_adapter_service import AnalyzeStoriesAdapterService
from ..services.formal_apply_decision_gate_service import FormalApplyDecisionGateService
from ..services.formal_apply_dry_run_service import FormalApplyDryRunService
from ..services.formal_apply_eligibility_service import FormalApplyEligibilityService
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m5_controlled_executors_v1"

EXECUTION_RESULTS_FILE = "phase6_formal_apply_execution_results.json"
ROLLBACK_REFS_FILE = "phase6_formal_apply_rollback_refs.json"
WRITE_AUDITS_FILE = "phase6_formal_apply_write_audits.json"
FRAMEWORK_PROPOSALS_FILE = "phase6_framework_apply_proposals.json"
CHAPTER_ARCHIVE_PROPOSALS_FILE = "phase6_chapter_archive_proposals.json"
NARRATIVE_DEBT_PROPOSALS_FILE = "phase6_narrative_debt_proposals.json"

ALLOWED_STORAGE_FILES = [
    EXECUTION_RESULTS_FILE,
    ROLLBACK_REFS_FILE,
    WRITE_AUDITS_FILE,
    FRAMEWORK_PROPOSALS_FILE,
    CHAPTER_ARCHIVE_PROPOSALS_FILE,
    NARRATIVE_DEBT_PROPOSALS_FILE,
]

FORBIDDEN_STORAGE_FILES = [
    "decisions.json",
    "formal_apply_execution_results.json",
    "framework_apply_proposals.json",
    "chapter_archive_proposals.json",
    "narrative_debt_proposals.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "scenes.json",
    "framework_package.json",
    "system_recommended_frameworks.json",
    "phase6_formal_apply_decisions.json",
    "phase6_formal_apply_approval_records.json",
    "phase6_formal_apply_rejection_records.json",
    "phase6_formal_apply_user_overrides.json",
    "phase6_formal_apply_questions.json",
    "phase6_formal_apply_decision_evidence_snapshots.json",
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
    "prose text",
    "revised_prose_text",
    "full_prose",
    "full prose",
    "full_user_modification_text",
    "authorization:",
    "bearer ",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")
FILESYSTEM_PATH_RE = re.compile(r"(?i)(^[\\/]|[a-z]:[\\/]|(^|[\\/])\.\.([\\/]|$))")

STEP_TO_EXECUTION: dict[str, tuple[FormalApplyExecutionType, FormalApplyProposalType]] = {
    "m5_create_framework_apply_proposal": ("create_framework_apply_proposal", "framework_apply"),
    "m5_create_chapter_archive_proposal": ("create_chapter_archive_proposal", "chapter_archive"),
    "m5_create_narrative_debt_proposal": ("create_narrative_debt_proposal", "narrative_debt"),
}


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
class CurrentEvidenceContext:
    target: FormalApplyTarget | None
    lineage: FormalApplySourceLineage | None
    report: FormalApplyEligibilityReport | None
    plan: FormalApplyPlan | None
    plan_items: list[FormalApplyPlanItem]
    diff_summary: FormalApplyDiffSummary | None
    impact_preview: FormalApplyImpactPreview | None
    safety_check: FormalApplySafetyCheck | None
    missing_artifact_ids: list[str]
    mismatch_ids: list[str]
    hard_blocker_ids: list[str]
    warning_codes: list[str]
    current_hashes: dict[str, str]


class ControlledFormalApplyExecutorService:
    """Phase 6 M5 controlled proposal creation.

    M5 consumes an M4 approval and creates Phase 6 proposal records plus
    execution evidence only. It never calls formal archive/debt/framework
    write services and never mutates story truth.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        decision_service: FormalApplyDecisionGateService | None = None,
        dry_run_service: FormalApplyDryRunService | None = None,
        eligibility_service: FormalApplyEligibilityService | None = None,
        analyze_stories_adapter_service: AnalyzeStoriesAdapterService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.execution_results_file = self.data_dir / EXECUTION_RESULTS_FILE
        self.rollback_refs_file = self.data_dir / ROLLBACK_REFS_FILE
        self.write_audits_file = self.data_dir / WRITE_AUDITS_FILE
        self.framework_proposals_file = self.data_dir / FRAMEWORK_PROPOSALS_FILE
        self.chapter_archive_proposals_file = self.data_dir / CHAPTER_ARCHIVE_PROPOSALS_FILE
        self.narrative_debt_proposals_file = self.data_dir / NARRATIVE_DEBT_PROPOSALS_FILE
        self.eligibility_service = eligibility_service or FormalApplyEligibilityService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.dry_run_service = dry_run_service or FormalApplyDryRunService(
            store=self.store,
            data_dir=self.data_dir,
            eligibility_service=self.eligibility_service,
        )
        self.decision_service = decision_service or FormalApplyDecisionGateService(
            store=self.store,
            data_dir=self.data_dir,
            dry_run_service=self.dry_run_service,
            eligibility_service=self.eligibility_service,
        )
        self.analyze_stories_adapter_service = analyze_stories_adapter_service or AnalyzeStoriesAdapterService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def get_status(self) -> FormalApplyExecutionStatusResponse:
        execution_results = self._read_models_if_exists(self.execution_results_file, FormalApplyExecutionResult)
        execution_results.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyExecutionStatusResponse(
            execution_result_count=len(execution_results),
            rollback_ref_count=len(self._read_models_if_exists(self.rollback_refs_file, FormalApplyRollbackRef)),
            write_audit_count=len(self._read_models_if_exists(self.write_audits_file, ControlledApplyWriteAudit)),
            latest_execution_result_id=execution_results[0].execution_result_id if execution_results else None,
            proposal_only=True,
            formal_story_write_disabled=True,
            active_framework_mutation_disabled=True,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            forbidden_storage_files=list(FORBIDDEN_STORAGE_FILES),
            safe_summary=(
                "Phase 6 M5 creates proposal records and execution evidence only. "
                "It writes no formal story facts, active framework state, recommendations, propagation output, or global decisions."
            ),
        )

    def get_approval_readiness(self, approval_id: str) -> FormalApplyExecutionReadiness:
        self._guard_safe_id(approval_id, "approval_id")
        blockers: list[str] = []
        warnings: list[str] = []
        approval = self._find_approval(approval_id)
        if approval is None:
            return self._readiness(
                approval_id=approval_id,
                blocked_reason_ids=["m4_approval_missing"],
                safe_summary="M5 readiness blocked because the M4 approval does not exist.",
            )

        execution_type, proposal_type = self._execution_mapping(approval.approved_next_step)
        if execution_type == "route_to_m7":
            blockers.append("route_to_m7_not_m5")
        elif execution_type == "none":
            blockers.append("unsupported_approved_next_step")

        if approval.authorizes_apply_execution_now is not False:
            blockers.append("approval_authorizes_apply_execution_now")
        if approval.authorizes_proposal_creation_now is not False:
            blockers.append("approval_authorizes_proposal_creation_now")
        if approval.creates_formal_record_now is not False:
            blockers.append("approval_creates_formal_record_now")
        if approval.no_formal_write_performed is not True:
            blockers.append("approval_no_formal_write_guarantee_failed")

        decision: FormalApplyDecision | None = None
        snapshot: FormalApplyDecisionEvidenceSnapshot | None = None
        try:
            decision = self.decision_service.get_decision(approval.decision_record_id)
        except StorageError:
            blockers.append("m4_decision_missing")
        if decision:
            if decision.decision_status != "recorded":
                blockers.append(f"m4_decision_status_{decision.decision_status}")
            if decision.approved_next_step != approval.approved_next_step:
                blockers.append("m4_decision_approval_next_step_mismatch")
            if decision.requires_m5_execution is not True:
                blockers.append("m4_decision_does_not_require_m5")
            if decision.authorizes_formal_record_write or decision.authorizes_apply_execution_now:
                blockers.append("m4_decision_write_authorization_inconsistent")
            if decision.authorizes_proposal_creation_now or decision.creates_formal_record_now:
                blockers.append("m4_decision_creation_authorization_inconsistent")
            if decision.writes_formal_story_fact_now or not decision.no_formal_write_performed:
                blockers.append("m4_decision_no_write_guarantee_failed")
            try:
                snapshot = self.decision_service.get_evidence_snapshot(decision.decision_record_id)
            except StorageError:
                blockers.append("m4_evidence_snapshot_missing")
        if decision and snapshot and decision.evidence_snapshot_id != snapshot.evidence_snapshot_id:
            blockers.append("m4_decision_snapshot_id_mismatch")
        if snapshot and approval.plan_id != snapshot.plan_id:
            blockers.append("m4_approval_snapshot_plan_mismatch")

        context = self._load_current_context(snapshot.plan_id if snapshot else approval.plan_id)
        blockers.extend(context.missing_artifact_ids)
        blockers.extend(context.mismatch_ids)
        blockers.extend(context.hard_blocker_ids)
        warnings.extend(context.warning_codes)

        if context.plan:
            if context.plan.plan_status != "ready_for_m4_decision":
                blockers.append(f"m3_plan_status_{context.plan.plan_status}")
            if not context.plan.can_enter_m4_decision:
                blockers.append("m3_plan_cannot_enter_m4_decision")
        if context.safety_check:
            if context.safety_check.safety_status not in {"pass", "warn"}:
                blockers.append(f"m3_safety_status_{context.safety_check.safety_status}")
            if any(isinstance(item, dict) and item.get("status") == "block" for item in context.safety_check.check_items):
                blockers.append("m3_safety_item_block")

        snapshot_hashes = dict(snapshot.evidence_hashes) if snapshot else {}
        stale_evidence = False
        if snapshot:
            stale_evidence = self._hashes_stale(context.current_hashes, snapshot_hashes)
            if stale_evidence:
                blockers.append("stale_m4_evidence_snapshot")
            blockers.extend(self._snapshot_id_mismatches(snapshot, context))

        already_executed = any(
            result.approval_id == approval_id and result.execution_status == "executed"
            for result in self._read_models_if_exists(self.execution_results_file, FormalApplyExecutionResult)
        )
        if already_executed:
            blockers.append("approval_already_executed")

        if not blockers:
            blockers.extend(self._candidate_blockers(context, proposal_type))

        can_execute = not blockers and execution_type in {
            "create_framework_apply_proposal",
            "create_chapter_archive_proposal",
            "create_narrative_debt_proposal",
        }
        return self._readiness(
            approval_id=approval.approval_id,
            decision_record_id=approval.decision_record_id,
            evidence_snapshot_id=snapshot.evidence_snapshot_id if snapshot else "",
            plan_id=approval.plan_id,
            target_id=approval.target_id,
            target_type=context.plan.target_type if context.plan else "",
            source_lineage_id=context.plan.source_lineage_id if context.plan else "",
            eligibility_report_id=context.plan.eligibility_report_id if context.plan else "",
            approved_next_step=approval.approved_next_step,
            execution_type=execution_type,
            expected_proposal_type=proposal_type,
            can_execute=can_execute,
            already_executed=already_executed,
            stale_evidence=stale_evidence,
            current_evidence_hashes=context.current_hashes,
            snapshot_evidence_hashes=snapshot_hashes,
            blocked_reason_ids=self._dedupe(blockers),
            warning_codes=self._dedupe(warnings),
            safe_summary=(
                "M5 approval readiness is executable."
                if can_execute
                else "M5 approval readiness is blocked; no proposal or execution evidence was written."
            ),
        )

    def execute_approval(
        self,
        approval_id: str,
        request: FormalApplyExecutionRequest | dict[str, Any] | None = None,
    ) -> FormalApplyExecutionResult:
        normalized = request if isinstance(request, FormalApplyExecutionRequest) else FormalApplyExecutionRequest(**(request or {}))
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500:
            raise StorageError("FORMAL_APPLY_EXECUTION_UNSAFE_PAYLOAD_BLOCKED: safe_user_note_too_long")
        readiness = self.get_approval_readiness(approval_id)
        if not readiness.can_execute:
            return self._transient_blocked_result(readiness, normalized)

        context = self._load_current_context(readiness.plan_id)
        if not context.plan or not context.target or not context.lineage or not context.report:
            return self._transient_blocked_result(
                FormalApplyExecutionReadiness(
                    **{
                        **model_to_dict(readiness),
                        "can_execute": False,
                        "blocked_reason_ids": self._dedupe(readiness.blocked_reason_ids + ["current_artifact_missing"]),
                        "safe_summary": "M5 execution blocked because current artifacts disappeared before proposal creation.",
                    }
                ),
                normalized,
            )

        before_fingerprints = self._storage_fingerprints()
        self._ensure_storage_files()
        timestamp = now_iso()
        execution_id = self._next_id("formal_apply_execution", self.execution_results_file, "execution_result_id")
        proposal_id = self._next_proposal_id(readiness.expected_proposal_type)
        rollback_ref_id = f"{execution_id}_rollback_ref"
        write_audit_id = f"{execution_id}_write_audit"

        proposal = self._build_proposal(
            proposal_id=proposal_id,
            readiness=readiness,
            context=context,
            timestamp=timestamp,
        )
        result = FormalApplyExecutionResult(
            execution_result_id=execution_id,
            project_id=context.plan.project_id or LOCAL_PROJECT_ID,
            approval_id=readiness.approval_id,
            decision_record_id=readiness.decision_record_id,
            evidence_snapshot_id=readiness.evidence_snapshot_id,
            target_id=readiness.target_id,
            target_type=readiness.target_type,
            source_lineage_id=readiness.source_lineage_id,
            eligibility_report_id=readiness.eligibility_report_id,
            plan_id=readiness.plan_id,
            approved_next_step=readiness.approved_next_step,
            execution_type=readiness.execution_type,
            execution_status="executed",
            created_proposal_id=proposal_id,
            created_proposal_type=readiness.expected_proposal_type,
            rollback_ref_id=rollback_ref_id,
            write_audit_id=write_audit_id,
            propagation_review_required=True,
            m6_handoff_status="required",
            m7_handoff_status="not_applicable",
            authorizes_formal_record_write=False,
            authorizes_apply_execution_now=False,
            creates_formal_record_now=False,
            writes_formal_story_fact_now=False,
            no_formal_write_performed=True,
            no_active_framework_mutation=True,
            no_event_memory_state_scene_write=True,
            no_chapter_archive_record_created=True,
            no_narrative_debt_record_created=True,
            no_recommendation_created=True,
            no_propagation_rewrite=True,
            full_automatic_undo_supported=False,
            blocked_reason_ids=[],
            warning_codes=readiness.warning_codes,
            safe_user_note=self._short(normalized.safe_user_note, 500),
            safe_summary=(
                f"M5 created a {readiness.expected_proposal_type} proposal and execution evidence only. "
                "No formal story write or active framework mutation was performed."
            ),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        rollback_ref = FormalApplyRollbackRef(
            rollback_ref_id=rollback_ref_id,
            execution_result_id=execution_id,
            proposal_id=proposal_id,
            proposal_type=readiness.expected_proposal_type,
            target_id=readiness.target_id,
            plan_id=readiness.plan_id,
            approval_id=readiness.approval_id,
            before_fingerprints=dict(context.plan.before_fingerprints),
            after_fingerprint_previews=dict(context.plan.after_fingerprint_previews),
            inverse_plan_hints=list(context.plan.inverse_plan_hints),
            rollback_scope=self._rollback_scope(context),
            full_automatic_undo_supported=False,
            safe_summary="Rollback reference is evidence-only. Full automatic undo is not supported.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

        self._guard_safe_payload(model_to_dict(proposal))
        self._guard_safe_payload(model_to_dict(result))
        self._guard_safe_payload(model_to_dict(rollback_ref))
        self._append(self._proposal_file(readiness.expected_proposal_type), model_to_dict(proposal))
        self._append(self.execution_results_file, model_to_dict(result))
        self._append(self.rollback_refs_file, model_to_dict(rollback_ref))

        mid_fingerprints = self._storage_fingerprints()
        created, mutated = self._storage_delta(before_fingerprints, mid_fingerprints)
        if WRITE_AUDITS_FILE in before_fingerprints:
            mutated = self._dedupe(mutated + [WRITE_AUDITS_FILE])
        else:
            created = self._dedupe(created + [WRITE_AUDITS_FILE])
        changed_files = set(created) | set(mutated)
        unchanged_forbidden = [
            file_name
            for file_name in FORBIDDEN_STORAGE_FILES
            if file_name not in changed_files
        ]
        only_allowed = all(file_name in set(ALLOWED_STORAGE_FILES) for file_name in changed_files)
        audit = ControlledApplyWriteAudit(
            write_audit_id=write_audit_id,
            execution_result_id=execution_id,
            approval_id=readiness.approval_id,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            forbidden_storage_files=list(FORBIDDEN_STORAGE_FILES),
            created_storage_files=sorted(created),
            mutated_storage_files=sorted(mutated),
            unchanged_forbidden_files=unchanged_forbidden,
            only_allowed_storage_changed=only_allowed,
            no_global_decision_write="decisions.json" not in changed_files,
            no_active_framework_mutation="framework_package.json" not in changed_files,
            no_formal_story_fact_write=not ({"chapter_archives.json", "narrative_debts.json"} & changed_files),
            no_event_memory_state_scene_write=not ({"events.json", "memory_records.json", "state_changes.json", "scenes.json"} & changed_files),
            no_chapter_archive_record_created="chapter_archives.json" not in changed_files,
            no_narrative_debt_record_created="narrative_debts.json" not in changed_files,
            no_recommendation_created="system_recommended_frameworks.json" not in changed_files,
            no_propagation_rewrite=True,
            safe_summary="M5 write audit observed only Phase 6 M5 storage deltas.",
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._guard_safe_payload(model_to_dict(audit))
        if not audit.only_allowed_storage_changed:
            raise StorageError("FORMAL_APPLY_EXECUTION_FORBIDDEN_STORAGE_MUTATION")
        self._append(self.write_audits_file, model_to_dict(audit))
        return result

    def list_execution_results(self) -> FormalApplyExecutionResultListResponse:
        values = self._read_models_if_exists(self.execution_results_file, FormalApplyExecutionResult)
        values.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyExecutionResultListResponse(execution_results=values, total_count=len(values))

    def get_execution_result(self, execution_result_id: str) -> FormalApplyExecutionResult:
        self._guard_safe_id(execution_result_id, "execution_result_id")
        for item in self._read_models_if_exists(self.execution_results_file, FormalApplyExecutionResult):
            if item.execution_result_id == execution_result_id:
                return item
        raise StorageError(f"FORMAL_APPLY_EXECUTION_RESULT_NOT_FOUND: {execution_result_id}")

    def list_rollback_refs(self) -> FormalApplyRollbackRefListResponse:
        values = self._read_models_if_exists(self.rollback_refs_file, FormalApplyRollbackRef)
        values.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyRollbackRefListResponse(rollback_refs=values, total_count=len(values))

    def list_write_audits(self) -> ControlledApplyWriteAuditListResponse:
        values = self._read_models_if_exists(self.write_audits_file, ControlledApplyWriteAudit)
        values.sort(key=lambda item: item.created_at, reverse=True)
        return ControlledApplyWriteAuditListResponse(write_audits=values, total_count=len(values))

    def get_proposal_status(self) -> FormalApplyProposalStatusResponse:
        framework = self._read_models_if_exists(self.framework_proposals_file, FrameworkApplyProposal)
        archives = self._read_models_if_exists(self.chapter_archive_proposals_file, ChapterArchiveProposal)
        debts = self._read_models_if_exists(self.narrative_debt_proposals_file, NarrativeDebtProposal)
        total = len(framework) + len(archives) + len(debts)
        return FormalApplyProposalStatusResponse(
            framework_proposal_count=len(framework),
            chapter_archive_proposal_count=len(archives),
            narrative_debt_proposal_count=len(debts),
            total_count=total,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            proposal_only=True,
            no_formal_write_performed=True,
            safe_summary="M5 proposals are proposal-only records; no formal archive, debt, framework apply, or propagation write is performed.",
        )

    def list_all_proposals(self) -> FormalApplyProposalListResponse:
        proposals = [
            *self._read_models_if_exists(self.framework_proposals_file, FrameworkApplyProposal),
            *self._read_models_if_exists(self.chapter_archive_proposals_file, ChapterArchiveProposal),
            *self._read_models_if_exists(self.narrative_debt_proposals_file, NarrativeDebtProposal),
        ]
        proposals.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyProposalListResponse(proposals=proposals, total_count=len(proposals))

    def list_framework_proposals(self) -> FrameworkApplyProposalListResponse:
        values = self._read_models_if_exists(self.framework_proposals_file, FrameworkApplyProposal)
        values.sort(key=lambda item: item.updated_at, reverse=True)
        return FrameworkApplyProposalListResponse(framework_proposals=values, total_count=len(values))

    def list_chapter_archive_proposals(self) -> ChapterArchiveProposalListResponse:
        values = self._read_models_if_exists(self.chapter_archive_proposals_file, ChapterArchiveProposal)
        values.sort(key=lambda item: item.updated_at, reverse=True)
        return ChapterArchiveProposalListResponse(chapter_archive_proposals=values, total_count=len(values))

    def list_narrative_debt_proposals(self) -> NarrativeDebtProposalListResponse:
        values = self._read_models_if_exists(self.narrative_debt_proposals_file, NarrativeDebtProposal)
        values.sort(key=lambda item: item.updated_at, reverse=True)
        return NarrativeDebtProposalListResponse(narrative_debt_proposals=values, total_count=len(values))

    def get_proposal(self, proposal_id: str) -> FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal:
        self._guard_safe_id(proposal_id, "proposal_id")
        for proposal in self.list_all_proposals().proposals:
            if proposal.proposal_id == proposal_id:
                return proposal
        raise StorageError(f"FORMAL_APPLY_PROPOSAL_NOT_FOUND: {proposal_id}")

    def _find_approval(self, approval_id: str) -> FormalApplyApprovalRecord | None:
        for approval in self.decision_service.list_approvals().approval_records:
            if approval.approval_id == approval_id:
                return approval
        return None

    def _execution_mapping(
        self,
        approved_next_step: str,
    ) -> tuple[FormalApplyExecutionType, FormalApplyProposalType | None]:
        if approved_next_step == "m7_recommendation_governance_review":
            return "route_to_m7", None
        if approved_next_step in STEP_TO_EXECUTION:
            return STEP_TO_EXECUTION[approved_next_step]
        return "none", None

    def _load_current_context(self, plan_id: str) -> CurrentEvidenceContext:
        missing: list[str] = []
        mismatches: list[str] = []
        hard_blockers: list[str] = []
        warnings: list[str] = []
        target = None
        lineage = None
        report = None
        plan = None
        plan_items: list[FormalApplyPlanItem] = []
        diff_summary = None
        impact_preview = None
        safety_check = None
        try:
            plan = self.dry_run_service.get_plan(plan_id)
        except StorageError:
            missing.append("m3_plan_missing")
        if plan:
            plan_items = self.dry_run_service.list_plan_items(plan.plan_id).plan_items
            diff_summary = self._first_by_plan(self.dry_run_service.list_diff_summaries().diff_summaries, plan.plan_id)
            impact_preview = self._first_by_plan(self.dry_run_service.list_impact_previews().impact_previews, plan.plan_id)
            safety_check = self._first_by_plan(self.dry_run_service.list_safety_checks().safety_checks, plan.plan_id)
            if not plan_items:
                missing.append("m3_plan_items_missing")
            if diff_summary is None:
                missing.append("m3_diff_summary_missing")
            if impact_preview is None:
                missing.append("m3_impact_preview_missing")
            if safety_check is None:
                missing.append("m3_safety_check_missing")
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
            if target and target.target_id != plan.target_id:
                mismatches.append("m2_target_id_mismatch")
            if lineage and lineage.target_id != plan.target_id:
                mismatches.append("m2_lineage_target_mismatch")
            if report and report.target_id != plan.target_id:
                mismatches.append("m2_report_target_mismatch")
            if report and report.lineage_id != plan.source_lineage_id:
                mismatches.append("m2_report_lineage_mismatch")
            if diff_summary and diff_summary.target_id != plan.target_id:
                mismatches.append("m3_diff_target_mismatch")
            if impact_preview and impact_preview.target_id != plan.target_id:
                mismatches.append("m3_impact_target_mismatch")
            if safety_check and safety_check.target_id != plan.target_id:
                mismatches.append("m3_safety_target_mismatch")
            hard_blockers = self._collect_current_hard_blockers(plan, plan_items, report, diff_summary, impact_preview, safety_check)
            warnings = self._dedupe(
                list(plan.warnings)
                + (list(report.warnings) if report else [])
                + self._safety_warning_codes(safety_check)
            )
        current_hashes = self._evidence_hashes(
            {
                "target": target,
                "source_lineage": lineage,
                "eligibility_report": report,
                "plan": plan,
                "plan_items": plan_items,
                "diff_summary": diff_summary,
                "impact_preview": impact_preview,
                "safety_check": safety_check,
            }
        )
        return CurrentEvidenceContext(
            target=target,
            lineage=lineage,
            report=report,
            plan=plan,
            plan_items=plan_items,
            diff_summary=diff_summary,
            impact_preview=impact_preview,
            safety_check=safety_check,
            missing_artifact_ids=self._dedupe(missing),
            mismatch_ids=self._dedupe(mismatches),
            hard_blocker_ids=self._dedupe(hard_blockers),
            warning_codes=self._dedupe(warnings),
            current_hashes=current_hashes,
        )

    def _collect_current_hard_blockers(
        self,
        plan: FormalApplyPlan,
        plan_items: list[FormalApplyPlanItem],
        report: FormalApplyEligibilityReport | None,
        diff_summary: FormalApplyDiffSummary | None,
        impact_preview: FormalApplyImpactPreview | None,
        safety_check: FormalApplySafetyCheck | None,
    ) -> list[str]:
        blockers: list[str] = []
        if plan.plan_status != "ready_for_m4_decision":
            blockers.append(f"m3_plan_status_{plan.plan_status}")
        if not plan.can_enter_m4_decision:
            blockers.append("m3_plan_cannot_enter_m4_decision")
        if plan.can_write_formal_record_now or plan.creates_formal_record_now or plan.writes_formal_story_fact_now:
            blockers.append("m3_plan_write_flag_inconsistent")
        if not plan.no_formal_write_performed or not plan.preview_record_only:
            blockers.append("m3_plan_no_write_guarantee_failed")
        if report:
            if report.can_write_formal_record_now or report.creates_formal_record_now or report.writes_formal_story_fact_now:
                blockers.append("m2_report_write_flag_inconsistent")
            if not report.no_formal_write_performed:
                blockers.append("m2_report_no_write_guarantee_failed")
        blockers.extend(self._plan_preview_next_step_mismatches(plan, plan_items))
        for item in plan_items:
            if not item.no_write_guarantee:
                blockers.append(f"{item.item_id}_no_write_guarantee_failed")
        if diff_summary and not diff_summary.no_formal_write_performed:
            blockers.append("m3_diff_no_write_guarantee_failed")
        if impact_preview:
            if impact_preview.formal_story_fact_write_attempted:
                blockers.append("formal_story_fact_write_attempted")
            if impact_preview.event_memory_state_scene_write_attempted:
                blockers.append("event_memory_state_scene_write_attempted")
            if impact_preview.active_framework_mutation_attempted:
                blockers.append("active_framework_mutation_attempted")
        if safety_check:
            if safety_check.safety_status == "block":
                blockers.append("safety_status_block")
            blockers.extend(safety_check.block_reason_ids)
            for item in safety_check.check_items:
                if isinstance(item, dict) and item.get("status") == "block":
                    blockers.append(str(item.get("check_id") or "safety_item_block"))
        return self._dedupe(blockers)

    def _plan_preview_next_step_mismatches(
        self,
        plan: FormalApplyPlan,
        plan_items: list[FormalApplyPlanItem],
    ) -> list[str]:
        contracts = {
            "imported_framework_merge_target": {
                "item_type": "framework_merge_preview",
                "action_preview": "preview_framework_merge_for_later_user_decision",
                "write_intent": "future_user_confirmed_merge",
            },
            "chapter_archive_candidate_target": {
                "item_type": "chapter_archive_proposal_preview",
                "action_preview": "create_chapter_archive_proposal_later",
                "write_intent": "future_proposal_creation",
            },
            "narrative_debt_candidate_target": {
                "item_type": "narrative_debt_proposal_preview",
                "action_preview": "create_narrative_debt_proposal_later",
                "write_intent": "future_proposal_creation",
            },
        }
        contract = contracts.get(plan.target_type)
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

    def _snapshot_id_mismatches(
        self,
        snapshot: FormalApplyDecisionEvidenceSnapshot,
        context: CurrentEvidenceContext,
    ) -> list[str]:
        mismatches: list[str] = []
        if not context.plan:
            return mismatches
        checks = {
            "target_id": (snapshot.target_id, context.plan.target_id),
            "source_lineage_id": (snapshot.source_lineage_id, context.plan.source_lineage_id),
            "eligibility_report_id": (snapshot.eligibility_report_id, context.plan.eligibility_report_id),
            "plan_id": (snapshot.plan_id, context.plan.plan_id),
            "diff_summary_id": (snapshot.diff_summary_id, context.diff_summary.diff_summary_id if context.diff_summary else ""),
            "impact_preview_id": (snapshot.impact_preview_id, context.impact_preview.impact_preview_id if context.impact_preview else ""),
            "safety_check_id": (snapshot.safety_check_id, context.safety_check.safety_check_id if context.safety_check else ""),
        }
        for label, (snapshot_value, current_value) in checks.items():
            if snapshot_value != current_value:
                mismatches.append(f"m4_snapshot_{label}_mismatch")
        return mismatches

    def _hashes_stale(self, current_hashes: dict[str, str], snapshot_hashes: dict[str, str]) -> bool:
        required = (
            "target",
            "source_lineage",
            "eligibility_report",
            "plan",
            "plan_items",
            "diff_summary",
            "impact_preview",
            "safety_check",
        )
        for key in required:
            if not current_hashes.get(key) or not snapshot_hashes.get(key):
                return True
            if current_hashes[key] != snapshot_hashes[key]:
                return True
        return False

    def _candidate_blockers(
        self,
        context: CurrentEvidenceContext,
        proposal_type: FormalApplyProposalType | None,
    ) -> list[str]:
        if proposal_type is None:
            return ["proposal_type_missing"]
        if not context.target or not context.lineage:
            return ["candidate_context_missing"]
        candidate_id = self._source_candidate_id(context)
        if proposal_type == "framework_apply":
            return []
        if not candidate_id:
            return ["source_candidate_id_missing"]
        try:
            candidate = self.analyze_stories_adapter_service.get_candidate(candidate_id).candidate
        except StorageError:
            return ["source_candidate_missing"]
        blockers: list[str] = []
        expected_family = "chapter_archive" if proposal_type == "chapter_archive" else "narrative_debt"
        if candidate.get("candidate_family") != expected_family:
            blockers.append("source_candidate_wrong_family")
        if candidate.get("candidate_status") in {"rejected", "blocked"}:
            blockers.append(f"source_candidate_status_{candidate.get('candidate_status')}")
        if "character_arc_empty_by_design" in self._safe_string_list(candidate.get("known_package_gaps_carried")):
            if not self._has_user_supplement(candidate, context.lineage):
                blockers.append("character_arc_empty_by_design_requires_user_supplement")
        try:
            self._guard_safe_payload(candidate)
        except StorageError:
            blockers.append("source_candidate_unsafe_payload")
        return self._dedupe(blockers)

    def _build_proposal(
        self,
        *,
        proposal_id: str,
        readiness: FormalApplyExecutionReadiness,
        context: CurrentEvidenceContext,
        timestamp: str,
    ) -> FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal:
        if not context.plan or not context.target or not context.lineage:
            raise StorageError("FORMAL_APPLY_EXECUTION_CONTEXT_MISSING")
        source_refs = self._source_refs(context)
        base_kwargs = {
            "proposal_id": proposal_id,
            "proposal_status": "proposed",
            "project_id": context.plan.project_id or LOCAL_PROJECT_ID,
            "approval_id": readiness.approval_id,
            "decision_record_id": readiness.decision_record_id,
            "evidence_snapshot_id": readiness.evidence_snapshot_id,
            "target_id": readiness.target_id,
            "target_type": readiness.target_type,
            "source_lineage_id": readiness.source_lineage_id,
            "eligibility_report_id": readiness.eligibility_report_id,
            "plan_id": readiness.plan_id,
            "source_candidate_id": self._source_candidate_id(context),
            "source_refs": source_refs,
            "warning_codes": readiness.warning_codes,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version_id": SCHEMA_VERSION,
        }
        if readiness.expected_proposal_type == "framework_apply":
            candidate_ref = self._source_candidate_id(context) or context.target.source_id
            return FrameworkApplyProposal(
                **base_kwargs,
                proposal_type="framework_apply",
                merge_strategy="merge_into_user_confirmed_framework_version",
                candidate_framework_ref=self._short(candidate_ref, 180),
                active_framework_mutation_performed=False,
                set_active_requested=False,
                proposed_change_summary=self._short(context.target.target_label or context.lineage.safe_summary, 500),
                safe_component_refs=source_refs[:8],
                safe_summary=self._short(
                    "Framework apply proposal created for later user-confirmed merge. Active framework was not mutated.",
                    700,
                ),
            )
        if readiness.expected_proposal_type == "chapter_archive":
            candidate = self._adapter_candidate_or_error(context, "chapter_archive")
            return ChapterArchiveProposal(
                **base_kwargs,
                proposal_type="chapter_archive",
                chapter_index=self._safe_int(candidate.get("chapter_index")),
                archive_summary_candidate=self._short(candidate.get("archive_summary_candidate"), 500),
                chapter_goal_result_candidate=self._short(candidate.get("chapter_goal_result_candidate"), 500),
                reader_emotion_result_candidate=self._short(candidate.get("reader_emotion_result_candidate"), 500),
                conflict_state_candidate=self._short(candidate.get("conflict_state_candidate"), 500),
                candidate_status_at_creation=self._short(candidate.get("candidate_status"), 80),
                creates_chapter_archive_record_now=False,
                safe_summary=self._short(
                    candidate.get("safe_summary")
                    or "Chapter archive proposal created for later review. No ChapterArchiveRecord was created.",
                    700,
                ),
            )
        if readiness.expected_proposal_type == "narrative_debt":
            candidate = self._adapter_candidate_or_error(context, "narrative_debt")
            return NarrativeDebtProposal(
                **base_kwargs,
                proposal_type="narrative_debt",
                debt_type=self._short(candidate.get("debt_type") or "unknown", 120),
                payoff_required=bool(candidate.get("payoff_required", False)),
                open_ambiguity_allowed=bool(candidate.get("open_ambiguity_allowed", False)),
                symbolic_unresolved=bool(candidate.get("symbolic_unresolved", False)),
                payoff_deadline_hint=self._short(candidate.get("payoff_deadline_hint"), 300),
                candidate_status_at_creation=self._short(candidate.get("candidate_status"), 80),
                creates_narrative_debt_record_now=False,
                safe_summary=self._short(
                    candidate.get("safe_summary")
                    or "Narrative debt proposal created for later review. No formal NarrativeDebt was created.",
                    700,
                ),
            )
        raise StorageError("FORMAL_APPLY_EXECUTION_UNSUPPORTED_PROPOSAL_TYPE")

    def _adapter_candidate_or_error(
        self,
        context: CurrentEvidenceContext,
        expected_family: str,
    ) -> dict[str, Any]:
        candidate_id = self._source_candidate_id(context)
        if not candidate_id:
            raise StorageError("FORMAL_APPLY_EXECUTION_SOURCE_CANDIDATE_ID_MISSING")
        candidate = self.analyze_stories_adapter_service.get_candidate(candidate_id).candidate
        if candidate.get("candidate_family") != expected_family:
            raise StorageError("FORMAL_APPLY_EXECUTION_SOURCE_CANDIDATE_WRONG_FAMILY")
        if candidate.get("candidate_status") in {"rejected", "blocked"}:
            raise StorageError("FORMAL_APPLY_EXECUTION_SOURCE_CANDIDATE_BLOCKED")
        self._guard_safe_payload(candidate)
        return candidate

    def _source_candidate_id(self, context: CurrentEvidenceContext) -> str | None:
        if context.target and context.target.candidate_id:
            return context.target.candidate_id
        if context.lineage and context.lineage.source_record_id:
            return context.lineage.source_record_id
        if context.target and context.target.source_id:
            return context.target.source_id
        return None

    def _source_refs(self, context: CurrentEvidenceContext) -> list[str]:
        refs = list(context.lineage.source_refs if context.lineage else [])
        if context.target:
            refs.append(f"m2_target:{context.target.target_id}")
            if context.target.candidate_id:
                refs.append(f"candidate:{context.target.candidate_id}")
        if context.report:
            refs.append(f"m2_report:{context.report.eligibility_report_id}")
        return self._dedupe([self._short(ref, 180) for ref in refs if ref])

    def _has_user_supplement(self, candidate: dict[str, Any], lineage: FormalApplySourceLineage) -> bool:
        if lineage.user_supplement_refs:
            return True
        for ref in candidate.get("source_refs", []):
            if isinstance(ref, dict):
                source_type = str(ref.get("source_type", "")).lower().replace("-", "_")
                source_id = str(ref.get("source_id", "")).lower()
                if source_type == "user_supplement" or source_id.startswith("user_supplement:"):
                    return True
            elif str(ref).lower().startswith(("user_supplement:", "user-supplement:")):
                return True
        return False

    def _readiness(
        self,
        *,
        approval_id: str,
        decision_record_id: str = "",
        evidence_snapshot_id: str = "",
        plan_id: str = "",
        target_id: str = "",
        target_type: str = "",
        source_lineage_id: str = "",
        eligibility_report_id: str = "",
        approved_next_step: FormalApplyApprovedNextStep = "none",
        execution_type: FormalApplyExecutionType = "none",
        expected_proposal_type: FormalApplyProposalType | None = None,
        can_execute: bool = False,
        already_executed: bool = False,
        stale_evidence: bool = False,
        current_evidence_hashes: dict[str, str] | None = None,
        snapshot_evidence_hashes: dict[str, str] | None = None,
        blocked_reason_ids: list[str] | None = None,
        warning_codes: list[str] | None = None,
        safe_summary: str = "",
    ) -> FormalApplyExecutionReadiness:
        blockers = self._dedupe(blocked_reason_ids or [])
        return FormalApplyExecutionReadiness(
            success=True,
            approval_id=approval_id,
            decision_record_id=decision_record_id,
            evidence_snapshot_id=evidence_snapshot_id,
            plan_id=plan_id,
            target_id=target_id,
            target_type=target_type,
            source_lineage_id=source_lineage_id,
            eligibility_report_id=eligibility_report_id,
            approved_next_step=approved_next_step,
            execution_type=execution_type,
            expected_proposal_type=expected_proposal_type,
            can_execute=can_execute,
            already_executed=already_executed,
            stale_evidence=stale_evidence,
            current_evidence_hashes=current_evidence_hashes or {},
            snapshot_evidence_hashes=snapshot_evidence_hashes or {},
            blocked_reason_ids=blockers,
            warning_codes=self._dedupe(warning_codes or []),
            non_authorized_actions=[
                "formal_record_write",
                "apply_execution_now",
                "active_framework_mutation",
                "chapter_archive_record_creation",
                "narrative_debt_record_creation",
                "event_memory_state_scene_write",
                "recommendation_creation",
                "propagation_rewrite",
                "full_automatic_undo",
            ],
            safe_summary=safe_summary or ("M5 readiness blocked." if blockers else "M5 readiness is executable."),
        )

    def _transient_blocked_result(
        self,
        readiness: FormalApplyExecutionReadiness,
        request: FormalApplyExecutionRequest,
    ) -> FormalApplyExecutionResult:
        if readiness.stale_evidence:
            status: FormalApplyExecutionStatus = "stale"
        elif readiness.execution_type == "route_to_m7" or "unsupported_approved_next_step" in readiness.blocked_reason_ids:
            status = "unsupported"
        else:
            status = "blocked"
        m6_status: FormalApplyM6HandoffStatus = "blocked" if status != "unsupported" else "not_required"
        m7_status: FormalApplyM7HandoffStatus = "required" if readiness.execution_type == "route_to_m7" else "blocked"
        return FormalApplyExecutionResult(
            execution_result_id="",
            project_id=LOCAL_PROJECT_ID,
            approval_id=readiness.approval_id,
            decision_record_id=readiness.decision_record_id,
            evidence_snapshot_id=readiness.evidence_snapshot_id,
            target_id=readiness.target_id,
            target_type=readiness.target_type,
            source_lineage_id=readiness.source_lineage_id,
            eligibility_report_id=readiness.eligibility_report_id,
            plan_id=readiness.plan_id,
            approved_next_step=readiness.approved_next_step,
            execution_type=readiness.execution_type,
            execution_status=status,
            created_proposal_id=None,
            created_proposal_type=None,
            rollback_ref_id=None,
            write_audit_id="",
            propagation_review_required=False,
            m6_handoff_status=m6_status,
            m7_handoff_status=m7_status,
            authorizes_formal_record_write=False,
            authorizes_apply_execution_now=False,
            creates_formal_record_now=False,
            writes_formal_story_fact_now=False,
            no_formal_write_performed=True,
            no_active_framework_mutation=True,
            no_event_memory_state_scene_write=True,
            no_chapter_archive_record_created=True,
            no_narrative_debt_record_created=True,
            no_recommendation_created=True,
            no_propagation_rewrite=True,
            full_automatic_undo_supported=False,
            blocked_reason_ids=readiness.blocked_reason_ids,
            warning_codes=readiness.warning_codes,
            safe_user_note=self._short(request.safe_user_note, 500),
            safe_summary="M5 execution request was blocked; no proposal, execution record, rollback ref, or write audit was persisted.",
            created_at=now_iso(),
            version_id=SCHEMA_VERSION,
        )

    def _rollback_scope(self, context: CurrentEvidenceContext) -> list[str]:
        scope = ["m5_proposal_record", "m5_execution_evidence", "m5_rollback_ref", "m5_write_audit"]
        if context.impact_preview:
            scope.extend(context.impact_preview.rollback_scope)
        return self._dedupe([self._short(item, 160) for item in scope])

    def _ensure_storage_files(self) -> None:
        for path in (
            self.execution_results_file,
            self.rollback_refs_file,
            self.write_audits_file,
            self.framework_proposals_file,
            self.chapter_archive_proposals_file,
            self.narrative_debt_proposals_file,
        ):
            self.store.write_if_missing(path, [])

    def _proposal_file(self, proposal_type: FormalApplyProposalType | None) -> Path:
        if proposal_type == "framework_apply":
            return self.framework_proposals_file
        if proposal_type == "chapter_archive":
            return self.chapter_archive_proposals_file
        if proposal_type == "narrative_debt":
            return self.narrative_debt_proposals_file
        raise StorageError("FORMAL_APPLY_EXECUTION_UNSUPPORTED_PROPOSAL_TYPE")

    def _next_proposal_id(self, proposal_type: FormalApplyProposalType | None) -> str:
        prefix_by_type = {
            "framework_apply": ("framework_apply_proposal", self.framework_proposals_file),
            "chapter_archive": ("chapter_archive_proposal", self.chapter_archive_proposals_file),
            "narrative_debt": ("narrative_debt_proposal", self.narrative_debt_proposals_file),
        }
        if proposal_type not in prefix_by_type:
            raise StorageError("FORMAL_APPLY_EXECUTION_UNSUPPORTED_PROPOSAL_TYPE")
        prefix, path = prefix_by_type[proposal_type]
        return self._next_id(prefix, path, "proposal_id")

    def _evidence_hashes(self, payloads: dict[str, Any]) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for key, value in payloads.items():
            hashes[key] = self._fingerprint(self._safe_evidence_value(value))
        return hashes

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

    def _fingerprint(self, payload: Any) -> str:
        self._guard_safe_payload(payload)
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _storage_fingerprints(self) -> dict[str, str]:
        fingerprints: dict[str, str] = {}
        if not self.data_dir.exists():
            return fingerprints
        for path in sorted(self.data_dir.glob("*.json")):
            try:
                fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise StorageError(f"FORMAL_APPLY_EXECUTION_STORAGE_SCAN_FAILED: {path.name}") from exc
        return fingerprints

    def _storage_delta(self, before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str]]:
        created = sorted([name for name in after if name not in before])
        mutated = sorted([name for name in after if name in before and before[name] != after[name]])
        return created, mutated

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

    def _first_by_plan(self, values: list[Any], plan_id: str) -> Any | None:
        for value in values:
            if getattr(value, "plan_id", None) == plan_id:
                return value
        return None

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
                    safe_negative_assertion = normalized_key.startswith("no") and isinstance(child, bool)
                    if not safe_negative_assertion and any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"FORMAL_APPLY_EXECUTION_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"FORMAL_APPLY_EXECUTION_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_EXECUTION_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_EXECUTION_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _safety_warning_codes(self, safety_check: FormalApplySafetyCheck | None) -> list[str]:
        if not safety_check:
            return []
        return [
            str(item.get("check_id") or item.get("safe_summary") or "safety_warning")
            for item in safety_check.check_items
            if isinstance(item, dict) and item.get("status") == "warn"
        ]

    def _safe_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [self._short(item, 200) for item in value if item]

    def _safe_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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
