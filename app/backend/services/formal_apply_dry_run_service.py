from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.formal_apply_dry_run import (
    FormalApplyDiffSummary,
    FormalApplyDiffSummaryListResponse,
    FormalApplyDryRunPlanRequest,
    FormalApplyDryRunResult,
    FormalApplyDryRunStatusResponse,
    FormalApplyImpactPreview,
    FormalApplyImpactPreviewListResponse,
    FormalApplyPlan,
    FormalApplyPlanItem,
    FormalApplyPlanItemListResponse,
    FormalApplyPlanListResponse,
    FormalApplySafetyCheck,
    FormalApplySafetyCheckListResponse,
    FormalApplyWriteIntent,
)
from ..models.formal_apply_eligibility import (
    FormalApplyBlockReason,
    FormalApplyEligibilityReport,
    FormalApplySourceLineage,
    FormalApplyTarget,
)
from ..services.formal_apply_eligibility_service import FormalApplyEligibilityService
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m3_formal_apply_dry_run_v1"

PLANS_FILE = "phase6_formal_apply_plans.json"
PLAN_ITEMS_FILE = "phase6_formal_apply_plan_items.json"
DIFF_SUMMARIES_FILE = "phase6_formal_apply_diff_summaries.json"
IMPACT_PREVIEWS_FILE = "phase6_formal_apply_impact_previews.json"
SAFETY_CHECKS_FILE = "phase6_formal_apply_safety_checks.json"
ALLOWED_STORAGE_FILES = [
    PLANS_FILE,
    PLAN_ITEMS_FILE,
    DIFF_SUMMARIES_FILE,
    IMPACT_PREVIEWS_FILE,
    SAFETY_CHECKS_FILE,
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


class FormalApplyDryRunService:
    """Phase 6 M3 dry-run and impact preview service.

    M3 consumes existing M2 eligibility artifacts and writes only preview
    records. It does not create decisions, proposals, execution results,
    formal facts, active framework mutations, or story state writes.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        eligibility_service: FormalApplyEligibilityService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.plans_file = self.data_dir / PLANS_FILE
        self.plan_items_file = self.data_dir / PLAN_ITEMS_FILE
        self.diff_summaries_file = self.data_dir / DIFF_SUMMARIES_FILE
        self.impact_previews_file = self.data_dir / IMPACT_PREVIEWS_FILE
        self.safety_checks_file = self.data_dir / SAFETY_CHECKS_FILE
        self.eligibility_service = eligibility_service or FormalApplyEligibilityService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def get_status(self) -> FormalApplyDryRunStatusResponse:
        plans = self._read_models_if_exists(self.plans_file, FormalApplyPlan)
        plans.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyDryRunStatusResponse(
            plan_count=len(plans),
            plan_item_count=len(self._read_models_if_exists(self.plan_items_file, FormalApplyPlanItem)),
            diff_summary_count=len(self._read_models_if_exists(self.diff_summaries_file, FormalApplyDiffSummary)),
            impact_preview_count=len(self._read_models_if_exists(self.impact_previews_file, FormalApplyImpactPreview)),
            safety_check_count=len(self._read_models_if_exists(self.safety_checks_file, FormalApplySafetyCheck)),
            latest_plan_id=plans[0].plan_id if plans else None,
            preview_record_only=True,
            no_formal_write_performed=True,
            m4_decision_required_before_write=True,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            safe_summary=(
                "Phase 6 M3 dry-run is preview-only. It consumes M2 eligibility "
                "reports and produces no decisions, proposals, apply results, or formal story writes."
            ),
        )

    def create_plan(self, request: FormalApplyDryRunPlanRequest) -> FormalApplyDryRunResult:
        self._guard_safe_payload(model_to_dict(request))
        self._ensure_storage_files()
        timestamp = now_iso()
        report = self.eligibility_service.get_eligibility_report(request.eligibility_report_id)
        target, lineage, block_reasons, consistency_warnings = self._load_m2_context(report, request)

        plan_id = self._next_id("formal_apply_plan", self.plans_file, "plan_id")
        block_reason_ids = self._dedupe(
            list(report.block_reason_ids)
            + [reason.reason_id for reason in block_reasons]
        )
        plan_status, can_enter_m4, allowed_next_step, write_intent, action_preview = self._classify_plan(
            report,
            target,
            lineage,
            consistency_warnings,
        )
        if plan_status != "ready_for_m4_decision" and not block_reason_ids:
            block_reason_ids = [f"{plan_id}_blocked_without_m2_reason"]
        warnings = self._dedupe(list(report.warnings) + consistency_warnings)
        if lineage and "character_arc_empty_by_design" in lineage.known_gaps:
            warnings.append("known_gap_character_arc_empty_by_design")
        target_id = report.target_id
        source_lineage_id = report.lineage_id
        affected_refs = self._affected_refs(target, lineage, report)
        before_refs = self._before_refs(target, lineage, report)
        after_refs = self._after_preview_refs(report, plan_id)
        before_fingerprints = {
            ref: self._fingerprint({"before": ref, "eligibility_report_id": report.eligibility_report_id})
            for ref in before_refs
        }
        after_fingerprint_previews = {
            ref: self._fingerprint({"after_preview": ref, "plan_id": plan_id, "target_type": report.target_type})
            for ref in after_refs
        }
        plan = FormalApplyPlan(
            plan_id=plan_id,
            project_id=request.project_id or LOCAL_PROJECT_ID,
            target_id=target_id,
            eligibility_report_id=report.eligibility_report_id,
            target_type=report.target_type,
            source_lineage_id=source_lineage_id,
            plan_status=plan_status,
            allowed_next_step=allowed_next_step,
            can_enter_m4_decision=can_enter_m4,
            requires_user_decision_before_apply=True,
            can_write_formal_record_now=False,
            creates_formal_record_now=False,
            writes_formal_story_fact_now=False,
            no_formal_write_performed=True,
            preview_record_only=True,
            block_reason_ids=block_reason_ids,
            rollback_ref_preview=[
                f"rollback_preview:{plan_id}:restore_before_fingerprints",
                "full_automatic_undo:false",
            ],
            before_fingerprints=before_fingerprints,
            after_fingerprint_previews=after_fingerprint_previews,
            inverse_plan_hints=[
                "Review before/after fingerprints before any M4 approval.",
                "Future rollback remains scope-limited and user-confirmed.",
                "No full automatic undo is prepared in M3.",
            ],
            warnings=warnings,
            safe_summary=self._plan_summary(plan_status, report.target_type, request.safe_note),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        plan_items = [
            FormalApplyPlanItem(
                item_id=f"{plan_id}_item_001",
                plan_id=plan_id,
                target_id=target_id,
                item_type=self._item_type(report.target_type, plan_status),
                target_object_ref=self._target_object_ref(target, lineage, report),
                action_preview=action_preview,
                write_intent=write_intent,
                no_write_guarantee=True,
                requires_m4_decision=True,
                blocked_by_reason_ids=block_reason_ids if plan_status != "ready_for_m4_decision" else [],
                affected_object_refs=affected_refs,
                rollback_hint="Rollback is preview-only in M3; no formal undo action exists yet.",
                safe_summary=self._item_summary(report.target_type, plan_status),
                sort_order=1,
                created_at=timestamp,
            )
        ]
        diff_summary = FormalApplyDiffSummary(
            diff_summary_id=f"{plan_id}_diff_summary",
            plan_id=plan_id,
            target_id=target_id,
            diff_kind=self._diff_kind(report.target_type, plan_status),
            before_refs=before_refs,
            after_preview_refs=after_refs,
            changed_fields_preview=self._changed_fields_preview(report.target_type, plan_status),
            no_prose_diff=True,
            no_full_chapter_rewrite=True,
            no_formal_write_performed=True,
            safe_summary=self._diff_summary(report.target_type, plan_status),
            created_at=timestamp,
        )
        impact_preview = FormalApplyImpactPreview(
            impact_preview_id=f"{plan_id}_impact_preview",
            plan_id=plan_id,
            target_id=target_id,
            affected_domains=self._affected_domains(report.target_type, plan_status),
            affected_object_refs=affected_refs,
            downstream_review_tasks=self._downstream_tasks(report.target_type, plan_status),
            formal_story_fact_write_attempted=False,
            event_memory_state_scene_write_attempted=False,
            active_framework_mutation_attempted=False,
            full_chapter_framework_prebuild_attempted=False,
            rollback_scope=[
                "preview_before_after_fingerprints",
                "preview_inverse_plan_hints",
                "no_full_automatic_undo",
            ],
            warnings=warnings,
            safe_summary=self._impact_summary(report.target_type, plan_status),
            created_at=timestamp,
        )
        safety_check = FormalApplySafetyCheck(
            safety_check_id=f"{plan_id}_safety_check",
            plan_id=plan_id,
            target_id=target_id,
            safety_status=self._safety_status(plan_status, warnings),
            check_items=self._safety_items(report, plan_status, lineage, warnings),
            block_reason_ids=block_reason_ids,
            no_decision_created=True,
            no_proposal_created=True,
            no_apply_result_created=True,
            no_formal_record_created=True,
            no_active_framework_mutation=True,
            no_raw_prompt=True,
            no_raw_response=True,
            no_hidden_reasoning=True,
            no_secret_like_material=True,
            no_full_prose=True,
            safe_summary=self._safety_summary(plan_status, report.target_type),
            created_at=timestamp,
        )
        result = FormalApplyDryRunResult(
            success=True,
            plan=plan,
            plan_items=plan_items,
            diff_summary=diff_summary,
            impact_preview=impact_preview,
            safety_check=safety_check,
        )
        self._guard_safe_payload(model_to_dict(result))
        self._append(self.plans_file, model_to_dict(plan))
        for item in plan_items:
            self._append(self.plan_items_file, model_to_dict(item))
        self._append(self.diff_summaries_file, model_to_dict(diff_summary))
        self._append(self.impact_previews_file, model_to_dict(impact_preview))
        self._append(self.safety_checks_file, model_to_dict(safety_check))
        return result

    def list_plans(self) -> FormalApplyPlanListResponse:
        plans = self._read_models_if_exists(self.plans_file, FormalApplyPlan)
        plans.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyPlanListResponse(plans=plans, total_count=len(plans))

    def get_plan(self, plan_id: str) -> FormalApplyPlan:
        for plan in self._read_models_if_exists(self.plans_file, FormalApplyPlan):
            if plan.plan_id == plan_id:
                return plan
        raise StorageError(f"FORMAL_APPLY_DRY_RUN_PLAN_NOT_FOUND: {plan_id}")

    def list_plan_items(self, plan_id: str | None = None) -> FormalApplyPlanItemListResponse:
        items = self._read_models_if_exists(self.plan_items_file, FormalApplyPlanItem)
        if plan_id is not None:
            items = [item for item in items if item.plan_id == plan_id]
        items.sort(key=lambda item: (item.plan_id, item.sort_order))
        return FormalApplyPlanItemListResponse(plan_items=items, total_count=len(items))

    def list_diff_summaries(self) -> FormalApplyDiffSummaryListResponse:
        summaries = self._read_models_if_exists(self.diff_summaries_file, FormalApplyDiffSummary)
        summaries.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyDiffSummaryListResponse(diff_summaries=summaries, total_count=len(summaries))

    def list_impact_previews(self) -> FormalApplyImpactPreviewListResponse:
        previews = self._read_models_if_exists(self.impact_previews_file, FormalApplyImpactPreview)
        previews.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyImpactPreviewListResponse(impact_previews=previews, total_count=len(previews))

    def list_safety_checks(self) -> FormalApplySafetyCheckListResponse:
        checks = self._read_models_if_exists(self.safety_checks_file, FormalApplySafetyCheck)
        checks.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplySafetyCheckListResponse(safety_checks=checks, total_count=len(checks))

    def _load_m2_context(
        self,
        report: FormalApplyEligibilityReport,
        request: FormalApplyDryRunPlanRequest,
    ) -> tuple[FormalApplyTarget | None, FormalApplySourceLineage | None, list[FormalApplyBlockReason], list[str]]:
        warnings: list[str] = []
        target: FormalApplyTarget | None = None
        lineage: FormalApplySourceLineage | None = None
        if request.target_id and request.target_id != report.target_id:
            warnings.append("request_target_id_does_not_match_eligibility_report")
        try:
            target = self.eligibility_service.get_target(report.target_id)
        except StorageError:
            warnings.append("m2_target_missing")
        try:
            lineage = self.eligibility_service.get_source_lineage(report.lineage_id)
        except StorageError:
            warnings.append("m2_source_lineage_missing")
        if target and target.target_id != report.target_id:
            warnings.append("m2_target_id_mismatch")
        if lineage and lineage.target_id != report.target_id:
            warnings.append("m2_lineage_target_mismatch")
        if report.can_write_formal_record_now or report.creates_formal_record_now or report.writes_formal_story_fact_now:
            warnings.append("m2_formal_write_flag_inconsistent")
        if not report.no_formal_write_performed:
            warnings.append("m2_no_write_flag_inconsistent")
        reasons = [
            reason
            for reason in self.eligibility_service.list_block_reasons().block_reasons
            if reason.reason_id in report.block_reason_ids
        ]
        missing_reasons = sorted(set(report.block_reason_ids) - {reason.reason_id for reason in reasons})
        if missing_reasons:
            warnings.append("m2_block_reason_missing")
        return target, lineage, reasons, self._dedupe(warnings)

    def _classify_plan(
        self,
        report: FormalApplyEligibilityReport,
        target: FormalApplyTarget | None,
        lineage: FormalApplySourceLineage | None,
        warnings: list[str],
    ) -> tuple[str, bool, str, FormalApplyWriteIntent, str]:
        if warnings or target is None or lineage is None:
            return "failed_closed", False, "failed_closed_review", "none", "failed_closed_explanation_only"
        if not report.can_enter_m3_dry_run:
            if report.target_type == "recommendation_promotion_target":
                return "blocked", False, "m7_recommendation_governance", "future_governance_review", "m7_governance_required_later"
            return "blocked", False, report.allowed_next_step or "blocked", "none", "blocked_explanation_only"
        if report.target_type == "imported_framework_merge_target":
            return "ready_for_m4_decision", True, "m4_user_decision", "future_user_confirmed_merge", "preview_framework_merge_for_later_user_decision"
        if report.target_type == "chapter_archive_candidate_target":
            return "ready_for_m4_decision", True, "m4_user_decision", "future_proposal_creation", "create_chapter_archive_proposal_later"
        if report.target_type == "narrative_debt_candidate_target":
            return "ready_for_m4_decision", True, "m4_user_decision", "future_proposal_creation", "create_narrative_debt_proposal_later"
        return "failed_closed", False, "failed_closed_review", "none", "unexpected_m2_eligible_target_failed_closed"

    def _target_object_ref(
        self,
        target: FormalApplyTarget | None,
        lineage: FormalApplySourceLineage | None,
        report: FormalApplyEligibilityReport,
    ) -> str:
        if target and target.candidate_id:
            return f"candidate:{target.candidate_id}"
        if lineage:
            return f"{lineage.source_record_type}:{lineage.source_record_id}"
        return f"target:{report.target_id}"

    def _affected_refs(
        self,
        target: FormalApplyTarget | None,
        lineage: FormalApplySourceLineage | None,
        report: FormalApplyEligibilityReport,
    ) -> list[str]:
        refs = [f"target:{report.target_id}", f"eligibility_report:{report.eligibility_report_id}"]
        if target:
            refs.append(f"target_type:{target.target_type}")
            if target.candidate_id:
                refs.append(f"candidate:{target.candidate_id}")
        if lineage:
            refs.append(f"source_lineage:{lineage.lineage_id}")
            refs.extend(lineage.source_refs[:8])
        return self._dedupe([self._short(ref, 180) for ref in refs if ref])

    def _before_refs(
        self,
        target: FormalApplyTarget | None,
        lineage: FormalApplySourceLineage | None,
        report: FormalApplyEligibilityReport,
    ) -> list[str]:
        refs = [f"m2_report:{report.eligibility_report_id}"]
        if target:
            refs.append(f"m2_target:{target.target_id}")
        if lineage:
            refs.append(f"m2_lineage:{lineage.lineage_id}")
            refs.extend(lineage.source_refs[:5])
        return self._dedupe(refs)

    def _after_preview_refs(self, report: FormalApplyEligibilityReport, plan_id: str) -> list[str]:
        if report.target_type == "imported_framework_merge_target":
            return [f"future_user_confirmed_framework_version_preview:{plan_id}"]
        if report.target_type == "chapter_archive_candidate_target":
            return [f"future_chapter_archive_proposal_preview:{plan_id}"]
        if report.target_type == "narrative_debt_candidate_target":
            return [f"future_narrative_debt_proposal_preview:{plan_id}"]
        return [f"blocked_preview_record:{plan_id}"]

    def _item_type(self, target_type: str, plan_status: str) -> str:
        if plan_status != "ready_for_m4_decision":
            return "blocked_explanation_preview"
        return {
            "imported_framework_merge_target": "framework_merge_preview",
            "chapter_archive_candidate_target": "chapter_archive_proposal_preview",
            "narrative_debt_candidate_target": "narrative_debt_proposal_preview",
        }.get(target_type, "unsupported_preview")

    def _diff_kind(self, target_type: str, plan_status: str) -> str:
        if plan_status != "ready_for_m4_decision":
            return "blocked_no_diff"
        return {
            "imported_framework_merge_target": "framework_merge_preview",
            "chapter_archive_candidate_target": "chapter_archive_proposal_preview",
            "narrative_debt_candidate_target": "narrative_debt_proposal_preview",
        }.get(target_type, "unsupported_no_diff")

    def _changed_fields_preview(self, target_type: str, plan_status: str) -> list[str]:
        if plan_status != "ready_for_m4_decision":
            return []
        return {
            "imported_framework_merge_target": [
                "macro_framework_preview",
                "component_vocabulary_preview",
                "chapter_macro_assignment_preview",
            ],
            "chapter_archive_candidate_target": [
                "chapter_archive_proposal_preview",
                "archive_summary_candidate_ref",
            ],
            "narrative_debt_candidate_target": [
                "narrative_debt_proposal_preview",
                "debt_type_candidate_ref",
            ],
        }.get(target_type, [])

    def _affected_domains(self, target_type: str, plan_status: str) -> list[str]:
        if plan_status != "ready_for_m4_decision":
            return ["formal_apply_preview", "safety_review"]
        return {
            "imported_framework_merge_target": ["framework_workbench", "formal_apply_preview"],
            "chapter_archive_candidate_target": ["chapter_archive_proposal_preview", "formal_apply_preview"],
            "narrative_debt_candidate_target": ["narrative_debt_proposal_preview", "formal_apply_preview"],
        }.get(target_type, ["formal_apply_preview"])

    def _downstream_tasks(self, target_type: str, plan_status: str) -> list[str]:
        if plan_status != "ready_for_m4_decision":
            return ["review_blocked_reason_before_m4"]
        tasks = ["m4_user_decision_required_before_any_write"]
        if target_type == "imported_framework_merge_target":
            tasks.append("future_merge_review_without_active_framework_mutation")
        if target_type == "chapter_archive_candidate_target":
            tasks.append("future_chapter_archive_proposal_review")
        if target_type == "narrative_debt_candidate_target":
            tasks.append("future_narrative_debt_proposal_review")
        return tasks

    def _safety_status(self, plan_status: str, warnings: list[str]) -> str:
        if plan_status != "ready_for_m4_decision":
            return "block"
        return "warn" if warnings else "pass"

    def _safety_items(
        self,
        report: FormalApplyEligibilityReport,
        plan_status: str,
        lineage: FormalApplySourceLineage | None,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        items = [
            self._check_item("m2_report_consumed", "pass", "M3 consumes an existing M2 eligibility report."),
            self._check_item("no_decision_created", "pass", "M3 creates no FormalApplyDecision."),
            self._check_item("no_proposal_created", "pass", "M3 creates no framework, archive, or debt proposal."),
            self._check_item("no_apply_result_created", "pass", "M3 creates no apply execution result."),
            self._check_item("no_formal_record_created", "pass", "M3 creates no formal story record."),
            self._check_item("no_active_framework_mutation", "pass", "M3 does not mutate active framework state."),
            self._check_item("no_event_memory_state_scene_write", "pass", "M3 writes no Event, MemoryRecord, StateChange, or Scene prose."),
            self._check_item("no_full_chapter_framework_prebuild", "pass", "M3 does not prebuild a full future ChapterFramework."),
            self._check_item("no_raw_or_secret_material", "pass", "M3 output safety scan blocks raw/secret material."),
        ]
        if lineage and lineage.user_supplement_refs:
            items.append(
                self._check_item(
                    "user_supplement_separate_evidence",
                    "pass",
                    "User supplement source refs remain separate from imported Analyze Stories gap refs.",
                )
            )
        if plan_status != "ready_for_m4_decision":
            items.append(
                self._check_item(
                    "m4_decision_not_ready",
                    "block",
                    f"M2 report status {report.eligibility_status} does not permit normal M3 dry-run.",
                )
            )
        for warning in warnings:
            items.append(self._check_item(f"warning_{warning}", "warn", warning))
        return items

    def _check_item(self, check_id: str, status: str, safe_summary: str) -> dict[str, Any]:
        return {"check_id": check_id, "status": status, "safe_summary": self._short(safe_summary, 220)}

    def _plan_summary(self, plan_status: str, target_type: str, safe_note: str) -> str:
        note = f" Note: {self._short(safe_note, 90)}" if safe_note else ""
        return (
            f"{target_type} dry-run plan is {plan_status}. "
            "M3 produced preview records only and performed no formal writes."
            f"{note}"
        )

    def _item_summary(self, target_type: str, plan_status: str) -> str:
        return f"{target_type} item preview recorded with no-write guarantee; plan_status={plan_status}."

    def _diff_summary(self, target_type: str, plan_status: str) -> str:
        if plan_status == "ready_for_m4_decision":
            return f"{target_type} preview diff summarizes object refs only; no prose diff or rewrite is produced."
        return f"{target_type} has no mutation diff because the M3 plan is blocked or failed closed."

    def _impact_summary(self, target_type: str, plan_status: str) -> str:
        return f"{target_type} impact preview records downstream review tasks only; no write-capable path was called."

    def _safety_summary(self, plan_status: str, target_type: str) -> str:
        return f"{target_type} safety check status follows plan_status={plan_status}; all M3 no-write guarantees remain true."

    def _ensure_storage_files(self) -> None:
        for path in (
            self.plans_file,
            self.plan_items_file,
            self.diff_summaries_file,
            self.impact_previews_file,
            self.safety_checks_file,
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

    def _guard_safe_payload(self, payload: Any) -> None:
        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                    safe_negative_assertion = normalized_key.startswith("no") and isinstance(child, bool)
                    if not safe_negative_assertion and any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"FORMAL_APPLY_DRY_RUN_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"FORMAL_APPLY_DRY_RUN_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_DRY_RUN_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_DRY_RUN_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _fingerprint(self, payload: Any) -> str:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def _short(self, text: Any, limit: int) -> str:
        value = " ".join(str(text or "").split())
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 3)] + "..."

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        output: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output
