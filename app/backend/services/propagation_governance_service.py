from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.formal_apply_execution import (
    ChapterArchiveProposal,
    ControlledApplyWriteAudit,
    FormalApplyExecutionResult,
    FormalApplyProposalType,
    FormalApplyRollbackRef,
    FrameworkApplyProposal,
    NarrativeDebtProposal,
)
from ..models.propagation_governance import (
    AffectedObjectReviewTask,
    AffectedObjectReviewTaskListResponse,
    CrossChapterRecheckPlan,
    CrossChapterRecheckPlanListResponse,
    FrameworkChangePropagationReport,
    FrameworkChangePropagationReportListResponse,
    PropagationGovernanceStatusResponse,
    PropagationImpactRecord,
    PropagationImpactRecordListResponse,
    PropagationReadinessResult,
    PropagationReviewRequest,
    PropagationReviewResult,
    PropagationTaskStatusRequest,
)
from ..services.controlled_formal_apply_executor_service import ControlledFormalApplyExecutorService
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m6_propagation_governance_v1"

IMPACT_RECORDS_FILE = "phase6_propagation_impact_records.json"
REVIEW_TASKS_FILE = "phase6_affected_object_review_tasks.json"
RECHECK_PLANS_FILE = "phase6_cross_chapter_recheck_plans.json"
FRAMEWORK_REPORTS_FILE = "phase6_framework_change_propagation_reports.json"

ALLOWED_STORAGE_FILES = [
    IMPACT_RECORDS_FILE,
    REVIEW_TASKS_FILE,
    RECHECK_PLANS_FILE,
    FRAMEWORK_REPORTS_FILE,
]

FORBIDDEN_STORAGE_FILES = [
    "decisions.json",
    "chapter_archives.json",
    "narrative_debts.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "scenes.json",
    "framework.json",
    "framework_package.json",
    "system_recommended_frameworks.json",
    "continuity_issues.json",
    "future_issues.json",
    "delayed_questions.json",
    "future_todos.json",
    "chapter_memory_packs.json",
    "scene_memory_packs.json",
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
]

NON_AUTHORIZED_ACTIONS = [
    "formal_record_write",
    "active_framework_mutation",
    "chapter_archive_record_creation",
    "narrative_debt_record_creation",
    "event_memory_state_scene_write",
    "continuity_issue_resolution",
    "narrative_debt_payoff",
    "future_issue_mutation",
    "recommendation_creation",
    "propagation_rewrite",
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
    "full prose",
    "full_prose",
    "prose text",
    "prose_text",
    "revised prose text",
    "revised_prose_text",
    "full user modification text",
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


class PropagationGovernanceService:
    """Phase 6 M6 governance records for downstream propagation review.

    M6 consumes accepted M5 execution/proposal evidence and writes only M6
    governance records. It does not apply, resolve, regenerate, recommend, or
    mutate formal story/framework state.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        execution_service: ControlledFormalApplyExecutorService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.impact_records_file = self.data_dir / IMPACT_RECORDS_FILE
        self.review_tasks_file = self.data_dir / REVIEW_TASKS_FILE
        self.recheck_plans_file = self.data_dir / RECHECK_PLANS_FILE
        self.framework_reports_file = self.data_dir / FRAMEWORK_REPORTS_FILE
        self.execution_service = execution_service or ControlledFormalApplyExecutorService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def get_status(self) -> PropagationGovernanceStatusResponse:
        impacts = self._read_models_if_exists(self.impact_records_file, PropagationImpactRecord)
        tasks = self._read_models_if_exists(self.review_tasks_file, AffectedObjectReviewTask)
        plans = self._read_models_if_exists(self.recheck_plans_file, CrossChapterRecheckPlan)
        reports = self._read_models_if_exists(self.framework_reports_file, FrameworkChangePropagationReport)
        impacts.sort(key=lambda item: item.created_at, reverse=True)
        return PropagationGovernanceStatusResponse(
            impact_record_count=len(impacts),
            review_task_count=len(tasks),
            pending_review_task_count=len([task for task in tasks if task.task_status == "pending"]),
            recheck_plan_count=len(plans),
            framework_report_count=len(reports),
            latest_impact_record_id=impacts[0].impact_record_id if impacts else None,
            governance_only=True,
            formal_story_write_disabled=True,
            propagation_rewrite_disabled=True,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            forbidden_storage_files=list(FORBIDDEN_STORAGE_FILES),
            safe_summary=(
                "Phase 6 M6 records propagation governance review evidence only. "
                "It writes no formal story facts, active framework state, decisions, recommendations, or propagation rewrites."
            ),
        )

    def get_execution_readiness(self, execution_result_id: str) -> PropagationReadinessResult:
        self._guard_safe_id(execution_result_id, "execution_result_id")
        blockers: list[str] = []
        warnings: list[str] = []
        artifact_ids: dict[str, str] = {}
        result = self._find_execution_result(execution_result_id)
        if result is None:
            return self._readiness(
                execution_result_id=execution_result_id,
                execution_status="missing",
                blocked_reason_ids=["m5_execution_result_missing"],
                safe_summary="M6 propagation readiness is blocked because the M5 execution result does not exist.",
            )

        artifact_ids.update(
            {
                "execution_result_id": result.execution_result_id,
                "approval_id": result.approval_id,
                "decision_record_id": result.decision_record_id,
                "evidence_snapshot_id": result.evidence_snapshot_id,
                "target_id": result.target_id,
                "source_lineage_id": result.source_lineage_id,
                "eligibility_report_id": result.eligibility_report_id,
                "plan_id": result.plan_id,
            }
        )
        warnings.extend(result.warning_codes)
        if result.execution_status != "executed":
            blockers.append(f"m5_execution_status_{result.execution_status}")
        if not result.created_proposal_id:
            blockers.append("m5_created_proposal_id_missing")
        if result.created_proposal_type not in {"framework_apply", "chapter_archive", "narrative_debt"}:
            blockers.append("m5_created_proposal_type_unsupported")
        if result.propagation_review_required is not True:
            blockers.append("m5_propagation_review_not_required")
        if result.m6_handoff_status != "required":
            blockers.append(f"m5_m6_handoff_status_{result.m6_handoff_status or 'missing'}")
        blockers.extend(self._result_no_write_blockers(result))
        blockers.extend(self._required_linkage_blockers(result))

        proposal_status = "missing"
        proposal = None
        if result.created_proposal_id:
            proposal = self._find_proposal(result.created_proposal_id)
            if proposal is None:
                blockers.append("linked_proposal_missing")
            else:
                proposal_status = proposal.proposal_status
                artifact_ids["proposal_id"] = proposal.proposal_id
                warnings.extend(proposal.warning_codes)
                if proposal.proposal_status != "proposed":
                    blockers.append(f"proposal_status_{proposal.proposal_status}")
                if proposal.proposal_type != result.created_proposal_type:
                    blockers.append("proposal_type_mismatch")

        rollback = self._find_rollback_ref(result.rollback_ref_id or "")
        if rollback is None:
            blockers.append("rollback_ref_missing")
        else:
            artifact_ids["rollback_ref_id"] = rollback.rollback_ref_id
            if rollback.execution_result_id != result.execution_result_id:
                blockers.append("rollback_ref_execution_mismatch")

        audit = self._find_write_audit(result.write_audit_id)
        if audit is None:
            blockers.append("write_audit_missing")
        else:
            artifact_ids["write_audit_id"] = audit.write_audit_id
            if audit.execution_result_id != result.execution_result_id:
                blockers.append("write_audit_execution_mismatch")
            blockers.extend(self._audit_no_write_blockers(audit))

        existing = self._active_impact_for_execution(result.execution_result_id)
        if existing:
            blockers.append("m6_governance_review_already_exists")
            artifact_ids["impact_record_id"] = existing.impact_record_id

        can_review = not blockers
        return self._readiness(
            execution_result_id=result.execution_result_id,
            execution_status=result.execution_status,
            created_proposal_id=result.created_proposal_id,
            created_proposal_type=result.created_proposal_type,
            proposal_status=proposal_status,
            rollback_ref_id=result.rollback_ref_id,
            write_audit_id=result.write_audit_id,
            propagation_review_required=result.propagation_review_required,
            m6_handoff_status=result.m6_handoff_status,
            blocked_reason_ids=self._dedupe(blockers),
            warning_codes=self._dedupe(warnings),
            artifact_ids=artifact_ids,
            can_review=can_review,
            safe_summary=(
                "M6 propagation governance review can be created."
                if can_review
                else "M6 propagation governance readiness is blocked; no governance records were written."
            ),
        )

    def review_execution(
        self,
        execution_result_id: str,
        request: PropagationReviewRequest | dict[str, Any] | None = None,
    ) -> PropagationReviewResult:
        normalized = request if isinstance(request, PropagationReviewRequest) else PropagationReviewRequest(**(request or {}))
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500:
            raise StorageError("PROPAGATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: safe_user_note_too_long")
        readiness = self.get_execution_readiness(execution_result_id)
        if "m5_execution_result_missing" in readiness.blocked_reason_ids:
            raise StorageError(f"PROPAGATION_EXECUTION_RESULT_NOT_FOUND: {execution_result_id}")
        if "m6_governance_review_already_exists" in readiness.blocked_reason_ids:
            raise StorageError(
                "PROPAGATION_GOVERNANCE_DUPLICATE_REVIEW: "
                f"{readiness.artifact_ids.get('impact_record_id', '')}"
            )
        if not readiness.can_review:
            raise StorageError(
                "PROPAGATION_GOVERNANCE_NOT_READY: "
                + ",".join(readiness.blocked_reason_ids)
            )

        result = self._find_execution_result(execution_result_id)
        if result is None or not result.created_proposal_id or not result.created_proposal_type:
            raise StorageError(f"PROPAGATION_EXECUTION_RESULT_NOT_FOUND: {execution_result_id}")
        proposal = self._find_proposal(result.created_proposal_id)
        rollback = self._find_rollback_ref(result.rollback_ref_id or "")
        audit = self._find_write_audit(result.write_audit_id)
        if proposal is None or rollback is None or audit is None:
            raise StorageError("PROPAGATION_GOVERNANCE_NOT_READY: linked_artifact_missing")

        before = self._storage_fingerprints()
        timestamp = now_iso()
        impact_id = self._next_id("propagation_impact", self.impact_records_file, "impact_record_id")
        task_specs = self._task_specs(result, proposal)
        review_tasks = [
            self._build_review_task(
                task_id=f"{impact_id}_task_{index:03d}",
                impact_record_id=impact_id,
                result=result,
                proposal=proposal,
                spec=spec,
                timestamp=timestamp,
            )
            for index, spec in enumerate(task_specs, start=1)
        ]
        recheck_plan = self._build_recheck_plan(
            impact_record_id=impact_id,
            result=result,
            proposal=proposal,
            review_tasks=review_tasks,
            timestamp=timestamp,
        )
        framework_report = None
        if proposal.proposal_type == "framework_apply":
            framework_report = self._build_framework_report(
                impact_record_id=impact_id,
                result=result,
                proposal=proposal,
                timestamp=timestamp,
            )

        impact = PropagationImpactRecord(
            impact_record_id=impact_id,
            project_id=result.project_id or LOCAL_PROJECT_ID,
            execution_result_id=result.execution_result_id,
            proposal_id=proposal.proposal_id,
            proposal_type=proposal.proposal_type,
            approval_id=result.approval_id,
            decision_record_id=result.decision_record_id,
            evidence_snapshot_id=result.evidence_snapshot_id,
            target_id=result.target_id,
            target_type=result.target_type,
            source_lineage_id=result.source_lineage_id,
            eligibility_report_id=result.eligibility_report_id,
            plan_id=result.plan_id,
            rollback_ref_id=rollback.rollback_ref_id,
            write_audit_id=audit.write_audit_id,
            impact_status="review_tasks_created",
            affected_domains=self._affected_domains(proposal.proposal_type),
            affected_object_refs=[
                {"object_type": task.object_type, "object_ref": task.object_ref, "reason": task.review_reason}
                for task in review_tasks
            ],
            review_task_ids=[task.task_id for task in review_tasks],
            recheck_plan_ids=[recheck_plan.recheck_plan_id],
            framework_report_id=framework_report.framework_report_id if framework_report else None,
            blocked_reason_ids=[],
            warning_codes=self._dedupe(readiness.warning_codes),
            review_task_state_is_confirmation=False,
            user_confirmation_recorded=False,
            formal_resolution_performed=False,
            propagation_rewrite_performed=False,
            safe_user_note=self._short(normalized.safe_user_note, 500),
            safe_summary=(
                f"M6 created propagation governance review tasks for {proposal.proposal_type}. "
                "No formal write, confirmation, resolution, recommendation, or rewrite was performed."
            ),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

        payloads = [
            model_to_dict(impact),
            *[model_to_dict(task) for task in review_tasks],
            model_to_dict(recheck_plan),
        ]
        if framework_report:
            payloads.append(model_to_dict(framework_report))
        for payload in payloads:
            self._guard_safe_payload(payload)

        self._append(self.impact_records_file, model_to_dict(impact))
        for task in review_tasks:
            self._append(self.review_tasks_file, model_to_dict(task))
        self._append(self.recheck_plans_file, model_to_dict(recheck_plan))
        if framework_report:
            self._append(self.framework_reports_file, model_to_dict(framework_report))
        self._assert_only_allowed_changed(before)
        return PropagationReviewResult(
            success=True,
            readiness=readiness,
            impact_record=impact,
            review_tasks=review_tasks,
            recheck_plan=recheck_plan,
            framework_report=framework_report,
            safe_summary="M6 propagation governance records were created without formal writes.",
        )

    def list_impact_records(self) -> PropagationImpactRecordListResponse:
        records = self._read_models_if_exists(self.impact_records_file, PropagationImpactRecord)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return PropagationImpactRecordListResponse(impact_records=records, total_count=len(records))

    def get_impact_record(self, impact_record_id: str) -> PropagationImpactRecord:
        self._guard_safe_id(impact_record_id, "impact_record_id")
        for record in self._read_models_if_exists(self.impact_records_file, PropagationImpactRecord):
            if record.impact_record_id == impact_record_id:
                return record
        raise StorageError(f"PROPAGATION_IMPACT_RECORD_NOT_FOUND: {impact_record_id}")

    def list_review_tasks(self, status: str | None = None) -> AffectedObjectReviewTaskListResponse:
        if status:
            self._guard_safe_id(status, "status")
        tasks = self._read_models_if_exists(self.review_tasks_file, AffectedObjectReviewTask)
        if status:
            tasks = [task for task in tasks if task.task_status == status]
        tasks.sort(key=lambda item: item.created_at, reverse=True)
        return AffectedObjectReviewTaskListResponse(review_tasks=tasks, total_count=len(tasks))

    def mark_task_reviewed(
        self,
        task_id: str,
        request: PropagationTaskStatusRequest | dict[str, Any] | None = None,
    ) -> AffectedObjectReviewTask:
        return self._set_task_status(task_id, "reviewed", request)

    def defer_task(
        self,
        task_id: str,
        request: PropagationTaskStatusRequest | dict[str, Any] | None = None,
    ) -> AffectedObjectReviewTask:
        return self._set_task_status(task_id, "deferred", request)

    def dismiss_task(
        self,
        task_id: str,
        request: PropagationTaskStatusRequest | dict[str, Any] | None = None,
    ) -> AffectedObjectReviewTask:
        return self._set_task_status(task_id, "dismissed", request)

    def list_recheck_plans(self) -> CrossChapterRecheckPlanListResponse:
        plans = self._read_models_if_exists(self.recheck_plans_file, CrossChapterRecheckPlan)
        plans.sort(key=lambda item: item.created_at, reverse=True)
        return CrossChapterRecheckPlanListResponse(recheck_plans=plans, total_count=len(plans))

    def list_framework_reports(self) -> FrameworkChangePropagationReportListResponse:
        reports = self._read_models_if_exists(self.framework_reports_file, FrameworkChangePropagationReport)
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return FrameworkChangePropagationReportListResponse(framework_reports=reports, total_count=len(reports))

    def _set_task_status(
        self,
        task_id: str,
        status: str,
        request: PropagationTaskStatusRequest | dict[str, Any] | None = None,
    ) -> AffectedObjectReviewTask:
        self._guard_safe_id(task_id, "task_id")
        normalized = request if isinstance(request, PropagationTaskStatusRequest) else PropagationTaskStatusRequest(**(request or {}))
        self._guard_safe_payload(model_to_dict(normalized))
        if len(normalized.safe_user_note) > 500 or len(normalized.status_note) > 500:
            raise StorageError("PROPAGATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: task_note_too_long")
        before = self._storage_fingerprints()
        payload = self._read_list(self.review_tasks_file)
        timestamp = now_iso()
        updated_task = None
        for index, item in enumerate(payload):
            if item.get("task_id") == task_id:
                item = dict(item)
                item["task_status"] = status
                item["status_note"] = self._short(normalized.status_note or normalized.safe_user_note, 500)
                item["updated_at"] = timestamp
                item["reviewed_at"] = timestamp if status == "reviewed" else item.get("reviewed_at")
                updated_task = AffectedObjectReviewTask(**item)
                self._guard_safe_payload(model_to_dict(updated_task))
                payload[index] = model_to_dict(updated_task)
                break
        if updated_task is None:
            raise StorageError(f"PROPAGATION_REVIEW_TASK_NOT_FOUND: {task_id}")
        self.store.write(self.review_tasks_file, payload)
        self._sync_impact_status(updated_task.impact_record_id, timestamp)
        self._assert_only_allowed_changed(before)
        return updated_task

    def _sync_impact_status(self, impact_record_id: str, timestamp: str) -> None:
        records = self._read_list(self.impact_records_file)
        tasks = self._read_models_if_exists(self.review_tasks_file, AffectedObjectReviewTask)
        matching_tasks = [task for task in tasks if task.impact_record_id == impact_record_id]
        if not matching_tasks:
            return
        task_statuses = {task.task_status for task in matching_tasks}
        if "blocked" in task_statuses:
            new_status = "blocked"
        elif task_statuses <= {"reviewed", "dismissed"}:
            new_status = "reviewed"
        elif task_statuses == {"pending"}:
            new_status = "review_tasks_created"
        else:
            new_status = "review_in_progress"
        changed = False
        for index, item in enumerate(records):
            if item.get("impact_record_id") == impact_record_id:
                item = dict(item)
                item["impact_status"] = new_status
                item["updated_at"] = timestamp
                item["user_confirmation_recorded"] = False
                item["formal_resolution_performed"] = False
                item["propagation_rewrite_performed"] = False
                self._guard_safe_payload(item)
                records[index] = item
                changed = True
                break
        if changed:
            self.store.write(self.impact_records_file, records)

    def _find_execution_result(self, execution_result_id: str) -> FormalApplyExecutionResult | None:
        for item in self.execution_service.list_execution_results().execution_results:
            if item.execution_result_id == execution_result_id:
                return item
        return None

    def _find_proposal(self, proposal_id: str) -> FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal | None:
        if not proposal_id:
            return None
        try:
            return self.execution_service.get_proposal(proposal_id)
        except StorageError:
            return None

    def _find_rollback_ref(self, rollback_ref_id: str) -> FormalApplyRollbackRef | None:
        if not rollback_ref_id:
            return None
        for item in self.execution_service.list_rollback_refs().rollback_refs:
            if item.rollback_ref_id == rollback_ref_id:
                return item
        return None

    def _find_write_audit(self, write_audit_id: str) -> ControlledApplyWriteAudit | None:
        if not write_audit_id:
            return None
        for item in self.execution_service.list_write_audits().write_audits:
            if item.write_audit_id == write_audit_id:
                return item
        return None

    def _active_impact_for_execution(self, execution_result_id: str) -> PropagationImpactRecord | None:
        for item in self._read_models_if_exists(self.impact_records_file, PropagationImpactRecord):
            if item.execution_result_id == execution_result_id and item.impact_status != "superseded":
                return item
        return None

    def _result_no_write_blockers(self, result: FormalApplyExecutionResult) -> list[str]:
        checks = {
            "m5_authorizes_formal_record_write": result.authorizes_formal_record_write is False,
            "m5_authorizes_apply_execution_now": result.authorizes_apply_execution_now is False,
            "m5_creates_formal_record_now": result.creates_formal_record_now is False,
            "m5_writes_formal_story_fact_now": result.writes_formal_story_fact_now is False,
            "m5_no_formal_write_failed": result.no_formal_write_performed is True,
            "m5_active_framework_mutation_failed": result.no_active_framework_mutation is True,
            "m5_event_memory_state_scene_write_failed": result.no_event_memory_state_scene_write is True,
            "m5_chapter_archive_created": result.no_chapter_archive_record_created is True,
            "m5_narrative_debt_created": result.no_narrative_debt_record_created is True,
            "m5_recommendation_created": result.no_recommendation_created is True,
            "m5_propagation_rewrite_performed": result.no_propagation_rewrite is True,
        }
        return [key for key, ok in checks.items() if not ok]

    def _audit_no_write_blockers(self, audit: ControlledApplyWriteAudit) -> list[str]:
        checks = {
            "write_audit_allowed_storage_failed": audit.only_allowed_storage_changed is True,
            "write_audit_global_decision_changed": audit.no_global_decision_write is True,
            "write_audit_active_framework_changed": audit.no_active_framework_mutation is True,
            "write_audit_formal_story_fact_written": audit.no_formal_story_fact_write is True,
            "write_audit_event_memory_state_scene_written": audit.no_event_memory_state_scene_write is True,
            "write_audit_chapter_archive_created": audit.no_chapter_archive_record_created is True,
            "write_audit_narrative_debt_created": audit.no_narrative_debt_record_created is True,
            "write_audit_recommendation_created": audit.no_recommendation_created is True,
            "write_audit_propagation_rewrite_performed": audit.no_propagation_rewrite is True,
        }
        return [key for key, ok in checks.items() if not ok]

    def _required_linkage_blockers(self, result: FormalApplyExecutionResult) -> list[str]:
        required = {
            "approval_id": result.approval_id,
            "decision_record_id": result.decision_record_id,
            "evidence_snapshot_id": result.evidence_snapshot_id,
            "target_id": result.target_id,
            "target_type": result.target_type,
            "source_lineage_id": result.source_lineage_id,
            "eligibility_report_id": result.eligibility_report_id,
            "plan_id": result.plan_id,
        }
        return [f"m5_linkage_{key}_missing" for key, value in required.items() if not value]

    def _task_specs(
        self,
        result: FormalApplyExecutionResult,
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
    ) -> list[dict[str, Any]]:
        if proposal.proposal_type == "framework_apply":
            specs = [
                ("active_framework", "active_framework:current", "Active framework review", "active framework must be manually reviewed before any later merge"),
                ("framework_package", "framework_package:current", "Framework package impact", "framework package/version impact requires review"),
                ("chapter_framework", "chapter_framework:current_jit", "Current chapter JIT framework impact", "current chapter JIT framework may become stale"),
                ("built_chapter_framework", "built_chapter_frameworks:existing", "Built chapter framework staleness", "previously built chapter frameworks require staleness review"),
                ("future_assignment", "future_chapter_assignments:pending", "Future assignment recheck", "future chapter assignment mapping requires recheck"),
                ("framework_library", "framework_library:references", "Framework module/library/reference impact", "library and reference usage require manual governance review"),
            ]
            return self._with_unknown_ref_if_needed([self._spec(*spec) for spec in specs], proposal)
        if proposal.proposal_type == "chapter_archive":
            chapter_ref = f"chapter:{proposal.chapter_index}" if proposal.chapter_index else f"unknown:{proposal.proposal_id}"
            return self._with_unknown_ref_if_needed([
                self._spec("chapter_archive", f"chapter_archive_candidate:{proposal.proposal_id}", "Archive consistency", "archive proposal consistency requires review"),
                self._spec("chapter", chapter_ref, "Chapter outcome interpretation", "chapter outcome interpretation can affect later summary and memory relevance"),
                self._spec("thread", f"thread_review:{proposal.proposal_id}", "Open or closed thread impact", "open and closed thread interpretation requires downstream review"),
                self._spec("memory", f"memory_relevance:{chapter_ref}", "Later chapter memory relevance", "later chapter summary and memory relevance require recheck"),
                self._spec("continuity", f"continuity_review:{proposal.proposal_id}", "Continuity downstream review", "continuity-related downstream review is required"),
            ], proposal)
        specs = [
            self._spec("narrative_debt", f"narrative_debt_proposal:{proposal.proposal_id}", "Payoff relevance", "debt payoff relevance requires governance review"),
            self._spec("open_thread", f"open_thread:{proposal.proposal_id}", "Open-thread relevance", "open-thread relevance requires downstream review"),
            self._spec("future_issue", f"future_issue_review:{proposal.proposal_id}", "Future issue relevance", "future issue relevance requires review without mutation"),
            self._spec("delayed_question", f"delayed_question_review:{proposal.proposal_id}", "Delayed question relevance", "delayed question relevance requires review without mutation"),
            self._spec("continuity", f"continuity_review:{proposal.proposal_id}", "Continuity review", "continuity review is required without resolving issues"),
        ]
        if self._needs_character_arc_guard(result, proposal):
            specs.append(
                self._spec(
                    "character_arc_guard",
                    "known_gap:character_arc_empty_by_design",
                    "character_arc_empty_by_design guard",
                    "known character arc gap must be carried forward and cannot be closed by M6",
                )
            )
        return self._with_unknown_ref_if_needed(specs, proposal)

    def _with_unknown_ref_if_needed(
        self,
        specs: list[dict[str, str]],
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
    ) -> list[dict[str, str]]:
        if proposal.source_refs:
            return specs
        return [
            *specs,
            self._spec(
                "unknown",
                f"unknown:{proposal.proposal_id}",
                "Unknown affected object",
                "source refs are unavailable, so an unknown-safe review task is preserved",
            ),
        ]

    def _spec(self, object_type: str, object_ref: str, label: str, reason: str) -> dict[str, str]:
        return {
            "object_type": self._short(object_type, 80),
            "object_ref": self._safe_ref(object_ref),
            "object_label": self._short(label, 160),
            "review_reason": self._short(reason, 300),
            "review_scope": "governance_review_only_no_formal_confirmation",
        }

    def _build_review_task(
        self,
        *,
        task_id: str,
        impact_record_id: str,
        result: FormalApplyExecutionResult,
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
        spec: dict[str, str],
        timestamp: str,
    ) -> AffectedObjectReviewTask:
        return AffectedObjectReviewTask(
            task_id=task_id,
            impact_record_id=impact_record_id,
            execution_result_id=result.execution_result_id,
            proposal_id=proposal.proposal_id,
            proposal_type=proposal.proposal_type,
            object_type=spec["object_type"],
            object_ref=spec["object_ref"],
            object_label=spec["object_label"],
            review_reason=spec["review_reason"],
            review_scope=spec["review_scope"],
            task_status="pending",
            status_note="",
            source_refs=self._safe_string_list(proposal.source_refs),
            blocks_formal_confirmation=True,
            reviewed_at=None,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_recheck_plan(
        self,
        *,
        impact_record_id: str,
        result: FormalApplyExecutionResult,
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
        review_tasks: list[AffectedObjectReviewTask],
        timestamp: str,
    ) -> CrossChapterRecheckPlan:
        chapter_refs = self._chapter_refs(proposal, review_tasks)
        object_refs = [task.object_ref for task in review_tasks]
        return CrossChapterRecheckPlan(
            recheck_plan_id=f"{impact_record_id}_recheck_plan",
            impact_record_id=impact_record_id,
            execution_result_id=result.execution_result_id,
            proposal_id=proposal.proposal_id,
            proposal_type=proposal.proposal_type,
            recheck_status="ready_for_review",
            chapter_refs=chapter_refs,
            object_refs=object_refs,
            task_ids=[task.task_id for task in review_tasks],
            required_before_formal_confirmation=True,
            no_regeneration_planned=True,
            safe_summary="Cross-chapter recheck plan is governance-only; no regeneration is planned.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _build_framework_report(
        self,
        *,
        impact_record_id: str,
        result: FormalApplyExecutionResult,
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
        timestamp: str,
    ) -> FrameworkChangePropagationReport:
        if not isinstance(proposal, FrameworkApplyProposal):
            raise StorageError("PROPAGATION_GOVERNANCE_FRAMEWORK_REPORT_TYPE_MISMATCH")
        candidate_ref = self._safe_ref(proposal.candidate_framework_ref or f"framework_candidate:{proposal.proposal_id}")
        component_refs = self._safe_string_list(proposal.safe_component_refs)
        return FrameworkChangePropagationReport(
            framework_report_id=f"{impact_record_id}_framework_report",
            impact_record_id=impact_record_id,
            execution_result_id=result.execution_result_id,
            proposal_id=proposal.proposal_id,
            candidate_framework_ref=candidate_ref,
            safe_component_refs=component_refs,
            active_framework_review_required=True,
            framework_package_review_required=True,
            current_chapter_jit_review_required=True,
            built_chapter_framework_staleness_review_required=True,
            future_assignment_recheck_required=True,
            framework_library_reference_review_required=True,
            affected_chapter_refs=["chapter:current", "chapter:future", "chapter:built"],
            affected_framework_refs=["active_framework:current", "framework_package:current", candidate_ref],
            no_active_framework_mutation=True,
            no_framework_package_write=True,
            no_chapter_framework_prebuild=True,
            safe_summary="Framework propagation report requires review only; active framework and framework package were not mutated.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _affected_domains(self, proposal_type: FormalApplyProposalType) -> list[str]:
        if proposal_type == "framework_apply":
            return ["framework", "framework_package", "chapter_framework", "cross_chapter"]
        if proposal_type == "chapter_archive":
            return ["chapter_archive", "chapter_summary", "memory", "continuity", "cross_chapter"]
        return ["narrative_debt", "future_review", "continuity", "character_arc", "cross_chapter"]

    def _chapter_refs(
        self,
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
        tasks: list[AffectedObjectReviewTask],
    ) -> list[str]:
        refs: list[str] = []
        if proposal.proposal_type == "framework_apply":
            refs.extend(["chapter:current", "chapter:future", "chapter:built"])
        elif isinstance(proposal, ChapterArchiveProposal) and proposal.chapter_index:
            refs.extend([f"chapter:{proposal.chapter_index}", f"chapter:after_{proposal.chapter_index}"])
        else:
            refs.append("chapter:future")
        if any(task.object_type == "unknown" for task in tasks):
            refs.append("unknown:chapter_scope")
        return self._dedupe([self._safe_ref(ref) for ref in refs])

    def _needs_character_arc_guard(
        self,
        result: FormalApplyExecutionResult,
        proposal: FrameworkApplyProposal | ChapterArchiveProposal | NarrativeDebtProposal,
    ) -> bool:
        if proposal.proposal_type != "narrative_debt":
            return False
        searchable = " ".join(
            [
                " ".join(result.warning_codes),
                " ".join(proposal.warning_codes),
                " ".join(proposal.source_refs),
                getattr(proposal, "candidate_status_at_creation", ""),
                proposal.safe_summary,
            ]
        ).lower()
        return "character_arc_empty_by_design" in searchable or "character arc" in searchable

    def _readiness(
        self,
        *,
        execution_result_id: str,
        can_review: bool = False,
        execution_status: str = "",
        created_proposal_id: str | None = None,
        created_proposal_type: FormalApplyProposalType | None = None,
        proposal_status: str = "",
        rollback_ref_id: str | None = None,
        write_audit_id: str = "",
        propagation_review_required: bool = False,
        m6_handoff_status: str = "",
        blocked_reason_ids: list[str] | None = None,
        warning_codes: list[str] | None = None,
        artifact_ids: dict[str, str] | None = None,
        safe_summary: str = "",
    ) -> PropagationReadinessResult:
        return PropagationReadinessResult(
            success=True,
            execution_result_id=execution_result_id,
            can_review=can_review,
            execution_status=execution_status,
            created_proposal_id=created_proposal_id,
            created_proposal_type=created_proposal_type,
            proposal_status=proposal_status,
            rollback_ref_id=rollback_ref_id,
            write_audit_id=write_audit_id,
            propagation_review_required=propagation_review_required,
            m6_handoff_status=m6_handoff_status,
            blocked_reason_ids=self._dedupe(blocked_reason_ids or []),
            warning_codes=self._dedupe(warning_codes or []),
            artifact_ids=artifact_ids or {},
            non_authorized_actions=list(NON_AUTHORIZED_ACTIONS),
            safe_summary=safe_summary or "M6 readiness checked.",
        )

    def _read_models_if_exists(self, path: Path, model: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        return [model(**item) for item in self.store.read_list(path)]

    def _read_list(self, path: Path) -> list[Any]:
        if not self.store.exists(path):
            return []
        return self.store.read_list(path)

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        values = self._read_list(path)
        values.append(item)
        self.store.write(path, values)

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
                raise StorageError(f"PROPAGATION_GOVERNANCE_STORAGE_SCAN_FAILED: {path.name}") from exc
        return fingerprints

    def _assert_only_allowed_changed(self, before: dict[str, str]) -> None:
        after = self._storage_fingerprints()
        changed = {name for name, value in after.items() if before.get(name) != value}
        changed.update(set(before) - set(after))
        unexpected = sorted(changed - set(ALLOWED_STORAGE_FILES))
        if unexpected:
            raise StorageError(f"PROPAGATION_GOVERNANCE_FORBIDDEN_STORAGE_MUTATION: {unexpected}")

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
                        raise StorageError(f"PROPAGATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"PROPAGATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"PROPAGATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"PROPAGATION_GOVERNANCE_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _safe_ref(self, value: Any) -> str:
        text = self._short(value or "unknown", 180)
        text = re.sub(r"[^a-zA-Z0-9_:\-.]", "_", text)
        if not text:
            text = "unknown:ref"
        return text

    def _safe_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return self._dedupe([self._safe_ref(item) for item in value if item])

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
