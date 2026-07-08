from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.config import settings
from ..models.formal_apply_eligibility import (
    FormalApplyBlockReason,
    FormalApplyBlockReasonListResponse,
    FormalApplyEligibilityReport,
    FormalApplyEligibilityReportListResponse,
    FormalApplyEligibilityResult,
    FormalApplyEligibilityStatus,
    FormalApplyEligibilityStatusResponse,
    FormalApplyInspectRequest,
    FormalApplySourceLineage,
    FormalApplyTarget,
    FormalApplyTargetListResponse,
    FormalApplyTargetStatus,
    FormalApplyTargetType,
)
from ..services.analyze_stories_adapter_service import AnalyzeStoriesAdapterService
from ..services.framework_package_candidate_service import FrameworkPackageCandidateService
from ..services.phase6_replay_gate_service import (
    CHARACTER_ARC_GAP_ID,
    Phase6ReplayGateService,
)
from ..storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SCHEMA_VERSION = "phase6_m2_formal_apply_eligibility_v1"

TARGETS_FILE = "phase6_formal_apply_targets.json"
SOURCE_LINEAGES_FILE = "phase6_formal_apply_source_lineages.json"
ELIGIBILITY_REPORTS_FILE = "phase6_formal_apply_eligibility_reports.json"
BLOCK_REASONS_FILE = "phase6_formal_apply_block_reasons.json"
ALLOWED_STORAGE_FILES = [
    TARGETS_FILE,
    SOURCE_LINEAGES_FILE,
    ELIGIBILITY_REPORTS_FILE,
    BLOCK_REASONS_FILE,
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


class FormalApplyEligibilityService:
    """Phase 6 M2 target eligibility gate.

    M2 only classifies whether a safe candidate may enter a future M3 dry-run.
    It never writes formal facts, proposal records, decisions, apply plans, or
    active story state.
    """

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        replay_gate_service: Phase6ReplayGateService | None = None,
        framework_candidate_service: FrameworkPackageCandidateService | None = None,
        analyze_stories_adapter_service: AnalyzeStoriesAdapterService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.targets_file = self.data_dir / TARGETS_FILE
        self.source_lineages_file = self.data_dir / SOURCE_LINEAGES_FILE
        self.eligibility_reports_file = self.data_dir / ELIGIBILITY_REPORTS_FILE
        self.block_reasons_file = self.data_dir / BLOCK_REASONS_FILE
        self.replay_gate_service = replay_gate_service or Phase6ReplayGateService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_candidate_service = (
            framework_candidate_service
            or FrameworkPackageCandidateService(store=self.store, data_dir=self.data_dir)
        )
        self.analyze_stories_adapter_service = (
            analyze_stories_adapter_service
            or AnalyzeStoriesAdapterService(store=self.store, data_dir=self.data_dir)
        )

    def get_status(self) -> FormalApplyEligibilityStatusResponse:
        targets = self._read_models_if_exists(self.targets_file, FormalApplyTarget)
        reports = self._read_models_if_exists(
            self.eligibility_reports_file,
            FormalApplyEligibilityReport,
        )
        block_reasons = self._read_models_if_exists(
            self.block_reasons_file,
            FormalApplyBlockReason,
        )
        lineages = self._read_models_if_exists(
            self.source_lineages_file,
            FormalApplySourceLineage,
        )
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyEligibilityStatusResponse(
            target_count=len(targets),
            eligibility_report_count=len(reports),
            block_reason_count=len(block_reasons),
            source_lineage_count=len(lineages),
            latest_eligibility_report_id=reports[0].eligibility_report_id if reports else None,
            formal_write_guard_active=True,
            known_gap_guard_active=True,
            allowed_storage_files=list(ALLOWED_STORAGE_FILES),
            safe_summary=(
                "Phase 6 M2 formal-apply eligibility is audit-only. "
                "Candidates can only be routed toward future M3 dry-run review."
            ),
        )

    def inspect_target(self, request: FormalApplyInspectRequest) -> FormalApplyEligibilityResult:
        request_dict = model_to_dict(request)
        self._guard_safe_payload(request_dict)
        self._ensure_storage_files()

        timestamp = now_iso()
        target_id = self._next_id("formal_apply_target", self.targets_file, "target_id")
        lineage_id = f"{target_id}_lineage"
        report_id = f"{target_id}_eligibility_report"

        source_detail = self._load_source_detail(request)
        source_refs = self._collect_source_refs(request, source_detail)
        user_supplement_refs = [ref for ref in source_refs if self._is_user_supplement_ref(ref)]
        m1_status = self.replay_gate_service.get_status()
        m1_reports = self.replay_gate_service.list_reports().reports
        m1_known_gaps = self.replay_gate_service.list_known_gaps().known_gaps
        active_m1_gap_ids = [
            gap.known_gap_record_id
            for gap in m1_known_gaps
            if gap.gap_id == CHARACTER_ARC_GAP_ID
            and gap.gap_status in {"carried_forward", "downgraded", "blocked"}
        ]
        known_gaps = self._dedupe(
            list(m1_status.active_known_gaps)
            + list(source_detail.get("known_gaps", []))
        )

        block_reasons: list[FormalApplyBlockReason] = []

        def add_reason(
            code: str,
            *,
            severity: str = "blocking",
            source_ref: str | None = None,
            safe_summary: str | None = None,
            requires_user_supplement: bool = False,
            can_be_resolved_in_m2: bool = False,
        ) -> None:
            block_reasons.append(
                FormalApplyBlockReason(
                    reason_id=f"{target_id}_reason_{len(block_reasons) + 1:03d}",
                    target_id=target_id,
                    reason_code=code,
                    severity=severity,  # type: ignore[arg-type]
                    source_ref=source_ref,
                    safe_summary=safe_summary or self._reason_summary(code),
                    requires_user_supplement=requires_user_supplement,
                    can_be_resolved_in_m2=can_be_resolved_in_m2,
                    created_at=timestamp,
                )
            )

        eligibility_status, target_status, can_enter_m3, allowed_next_step = self._classify_target(
            request,
            source_detail,
            source_refs,
            add_reason,
        )

        if block_reasons:
            blocking_codes = {reason.reason_code for reason in block_reasons if reason.severity == "blocking"}
            if eligibility_status in {"eligible_for_m3_dry_run", "eligible_with_warnings_for_m3_dry_run"}:
                if blocking_codes:
                    eligibility_status = "blocked"
                    target_status = "blocked"
                    can_enter_m3 = False
                    allowed_next_step = "blocked"

        target = FormalApplyTarget(
            target_id=target_id,
            project_id=request.project_id or LOCAL_PROJECT_ID,
            target_type=request.target_type,
            source_type=self._short(request.source_type or source_detail.get("source_type") or "unknown", 80),
            source_id=self._short(request.source_id or source_detail.get("source_id") or request.candidate_id or "", 120),
            source_family=self._short(request.source_family or source_detail.get("source_family") or "", 80),
            candidate_id=request.candidate_id,
            target_label=self._target_label(request, source_detail),
            target_status=target_status,
            allowed_next_step=allowed_next_step,
            requires_user_decision_before_apply=True,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        lineage = FormalApplySourceLineage(
            lineage_id=lineage_id,
            target_id=target_id,
            source_system=self._source_system(request, source_refs, source_detail),
            source_record_type=self._short(
                request.source_family
                or source_detail.get("source_family")
                or request.target_type,
                120,
            ),
            source_record_id=self._short(
                request.candidate_id
                or request.source_id
                or source_detail.get("source_id")
                or target_id,
                160,
            ),
            source_refs=source_refs,
            m1_replay_report_id=m1_reports[0].replay_report_id if m1_reports else None,
            m1_known_gap_record_ids=active_m1_gap_ids,
            m1_compatibility_matrix_id=m1_reports[0].compatibility_matrix_id if m1_reports else None,
            m1_evidence_index_id=m1_reports[0].evidence_index_id if m1_reports else None,
            source_package_status=self._short(
                source_detail.get("source_package_status")
                or m1_status.external_contract_confidence
                or "unknown",
                80,
            ),
            external_contract_confidence=m1_status.external_contract_confidence,
            known_gaps=known_gaps,
            user_supplement_refs=user_supplement_refs,
            safe_summary=self._lineage_summary(request, source_refs, known_gaps),
            created_at=timestamp,
            updated_at=timestamp,
        )
        report = FormalApplyEligibilityReport(
            eligibility_report_id=report_id,
            target_id=target_id,
            target_type=request.target_type,
            eligibility_status=eligibility_status,
            can_enter_m3_dry_run=can_enter_m3,
            can_write_formal_record_now=False,
            creates_formal_record_now=False,
            writes_formal_story_fact_now=False,
            no_formal_write_performed=True,
            requires_user_decision_before_apply=True,
            allowed_next_step=allowed_next_step,
            block_reason_ids=[reason.reason_id for reason in block_reasons],
            lineage_id=lineage_id,
            safe_summary=self._report_summary(eligibility_status, request.target_type),
            warnings=[
                reason.reason_code
                for reason in block_reasons
                if reason.severity == "warning"
            ],
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        result = FormalApplyEligibilityResult(
            success=True,
            target=target,
            lineage=lineage,
            eligibility_report=report,
            block_reasons=block_reasons,
        )
        self._guard_safe_payload(model_to_dict(target))
        self._guard_safe_payload(model_to_dict(lineage))
        self._guard_safe_payload(model_to_dict(report))
        for reason in block_reasons:
            self._guard_safe_payload(model_to_dict(reason))
        self._guard_safe_payload(model_to_dict(result))
        self._append(self.targets_file, model_to_dict(target))
        self._append(self.source_lineages_file, model_to_dict(lineage))
        self._append(self.eligibility_reports_file, model_to_dict(report))
        for reason in block_reasons:
            self._append(self.block_reasons_file, model_to_dict(reason))
        return result

    def list_targets(self) -> FormalApplyTargetListResponse:
        targets = self._read_models_if_exists(self.targets_file, FormalApplyTarget)
        targets.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyTargetListResponse(targets=targets, total_count=len(targets))

    def get_target(self, target_id: str) -> FormalApplyTarget:
        for target in self._read_models_if_exists(self.targets_file, FormalApplyTarget):
            if target.target_id == target_id:
                return target
        raise StorageError(f"FORMAL_APPLY_TARGET_NOT_FOUND: {target_id}")

    def list_eligibility_reports(self) -> FormalApplyEligibilityReportListResponse:
        reports = self._read_models_if_exists(
            self.eligibility_reports_file,
            FormalApplyEligibilityReport,
        )
        reports.sort(key=lambda item: item.updated_at, reverse=True)
        return FormalApplyEligibilityReportListResponse(
            eligibility_reports=reports,
            total_count=len(reports),
        )

    def get_eligibility_report(self, eligibility_report_id: str) -> FormalApplyEligibilityReport:
        for report in self._read_models_if_exists(
            self.eligibility_reports_file,
            FormalApplyEligibilityReport,
        ):
            if report.eligibility_report_id == eligibility_report_id:
                return report
        raise StorageError(f"FORMAL_APPLY_ELIGIBILITY_REPORT_NOT_FOUND: {eligibility_report_id}")

    def list_block_reasons(self) -> FormalApplyBlockReasonListResponse:
        reasons = self._read_models_if_exists(self.block_reasons_file, FormalApplyBlockReason)
        reasons.sort(key=lambda item: item.created_at, reverse=True)
        return FormalApplyBlockReasonListResponse(block_reasons=reasons, total_count=len(reasons))

    def get_source_lineage(self, lineage_id: str) -> FormalApplySourceLineage:
        for lineage in self._read_models_if_exists(
            self.source_lineages_file,
            FormalApplySourceLineage,
        ):
            if lineage.lineage_id == lineage_id:
                return lineage
        raise StorageError(f"FORMAL_APPLY_SOURCE_LINEAGE_NOT_FOUND: {lineage_id}")

    def _classify_target(
        self,
        request: FormalApplyInspectRequest,
        source_detail: dict[str, Any],
        source_refs: list[str],
        add_reason: Any,
    ) -> tuple[FormalApplyEligibilityStatus, FormalApplyTargetStatus, bool, str]:
        if request.target_type == "imported_framework_merge_target":
            if not source_detail.get("source_found"):
                add_reason("framework_candidate_not_found")
                return "blocked", "blocked", False, "blocked"
            if not source_detail.get("source_ready"):
                add_reason("framework_candidate_not_ready")
                return "blocked", "blocked", False, "blocked"
            if source_detail.get("warning_count", 0):
                add_reason(
                    "framework_candidate_has_warnings",
                    severity="warning",
                    safe_summary="Framework candidate is normalized but carries warnings for user review.",
                )
                return "eligible_with_warnings_for_m3_dry_run", "eligible", True, "m3_dry_run"
            return "eligible_for_m3_dry_run", "eligible", True, "m3_dry_run"

        if request.target_type == "imported_framework_set_active_target":
            add_reason("set_active_not_supported_in_m2_v1")
            return "blocked", "blocked", False, "blocked"

        if request.target_type == "imported_framework_reference_only_target":
            add_reason(
                "reference_only_evidence_cannot_mutate",
                severity="info",
                safe_summary="Reference-only evidence may inform review but cannot mutate active framework state.",
            )
            return "reference_only", "reference_only", False, "reference_only_review"

        if request.target_type == "chapter_archive_candidate_target":
            if not source_detail.get("source_found"):
                add_reason("chapter_archive_candidate_not_found")
                return "blocked", "blocked", False, "blocked"
            if not source_detail.get("source_ready"):
                add_reason("chapter_archive_candidate_not_ready")
                return "blocked", "blocked", False, "blocked"
            return (
                "eligible_for_m3_dry_run",
                "eligible",
                True,
                "m3_dry_run_for_future_chapter_archive_proposal",
            )

        if request.target_type == "narrative_debt_candidate_target":
            if source_detail.get("source_requested") and not source_detail.get("source_found"):
                add_reason("narrative_debt_candidate_not_found")
                return "blocked", "blocked", False, "blocked"
            if source_detail.get("source_found") and not source_detail.get("source_ready"):
                add_reason("narrative_debt_candidate_not_ready")
                return "blocked", "blocked", False, "blocked"
            if self.replay_gate_service.should_block_character_arc_apply(source_refs):
                add_reason(
                    "character_arc_empty_by_design_source_not_apply_eligible",
                    source_ref=self._first_non_user_source(source_refs),
                    requires_user_supplement=True,
                    safe_summary=(
                        "Analyze Stories character-arc source is carried forward as a known gap. "
                        "User supplement evidence is required before future apply review."
                    ),
                )
                return "requires_user_supplement", "blocked", False, "user_supplement_required"
            return (
                "eligible_for_m3_dry_run",
                "eligible",
                True,
                "m3_dry_run_for_future_narrative_debt_proposal",
            )

        if request.target_type == "recommendation_promotion_target":
            add_reason("recommendation_promotion_requires_m7_governance")
            return "future_governance_required", "future_governance_required", False, "future_governance_required"

        if request.target_type in {
            "framework_library_item_target",
            "framework_pattern_target",
            "module_composition_rule_target",
        }:
            add_reason("target_type_requires_future_governance")
            return "future_governance_required", "future_governance_required", False, "future_governance_required"

        add_reason("unsupported_target_type")
        return "unsupported", "unsupported", False, "unsupported"

    def _load_source_detail(self, request: FormalApplyInspectRequest) -> dict[str, Any]:
        source_id = request.candidate_id or request.source_id
        detail: dict[str, Any] = {
            "source_requested": bool(source_id),
            "source_found": not bool(source_id),
            "source_ready": True,
            "source_type": request.source_type,
            "source_id": source_id or request.source_id,
            "source_family": request.source_family,
            "source_refs": [],
            "known_gaps": [],
            "warning_count": 0,
            "source_package_status": "unknown",
        }
        if request.target_type.startswith("imported_framework_"):
            if not source_id:
                detail["source_found"] = False
                detail["source_ready"] = False
                return detail
            try:
                framework_detail = self.framework_candidate_service.get_detail(source_id)
            except StorageError:
                detail["source_found"] = False
                detail["source_ready"] = False
                return detail
            candidate = framework_detail.candidate
            report = framework_detail.normalization_report
            source_refs = [
                f"analyze_stories:framework_candidate:{candidate.candidate_id}",
                f"analyze_stories:import:{candidate.import_id}",
            ]
            source_refs.extend([f"input_fingerprint:{item}" for item in candidate.input_fingerprint_ids])
            if candidate.source_ref:
                source_refs.append(f"artifact:{candidate.source_ref.artifact_id}")
                if candidate.source_ref.source_manifest_id:
                    source_refs.append(f"source_manifest:{candidate.source_ref.source_manifest_id}")
            warnings = report.warnings if report else []
            blocking = report.blocking_issues if report else []
            detail.update(
                {
                    "source_found": True,
                    "source_ready": bool(candidate.can_proceed_to_m4_workbench) and not blocking,
                    "source_type": "analyze_stories_framework_candidate",
                    "source_id": candidate.candidate_id,
                    "source_family": "framework_package",
                    "source_refs": source_refs,
                    "warning_count": len(warnings),
                    "source_package_status": self._source_package_status(candidate.normalized_framework_package),
                }
            )
            return detail

        if request.target_type in {"chapter_archive_candidate_target", "narrative_debt_candidate_target"}:
            if not source_id:
                detail["source_found"] = False
                detail["source_ready"] = False
                return detail
            if request.target_type == "narrative_debt_candidate_target" and (
                self._is_user_supplement_ref(str(source_id))
                or request.source_type.lower().replace("-", "_") == "user_supplement"
            ):
                detail.update(
                    {
                        "source_found": True,
                        "source_ready": True,
                        "source_type": "user_supplement",
                        "source_id": str(source_id),
                        "source_family": request.source_family or "narrative_debt",
                        "source_refs": [
                            str(source_id)
                            if self._is_user_supplement_ref(str(source_id))
                            else f"user_supplement:{source_id}"
                        ],
                        "known_gaps": [],
                        "warning_count": 0,
                        "source_package_status": "user_supplement",
                    }
                )
                return detail
            try:
                adapter_detail = self.analyze_stories_adapter_service.get_candidate(source_id)
            except StorageError:
                detail["source_found"] = False
                detail["source_ready"] = False
                return detail
            candidate = adapter_detail.candidate
            source_refs = self._candidate_source_refs(candidate)
            detail.update(
                {
                    "source_found": True,
                    "source_ready": candidate.get("candidate_status") in {"candidate", "reviewed"}
                    and not candidate.get("blocking_issues", []),
                    "source_type": "analyze_stories_adapter_candidate",
                    "source_id": candidate.get("candidate_id", source_id),
                    "source_family": candidate.get("candidate_family", request.source_family),
                    "source_refs": source_refs,
                    "known_gaps": self._safe_string_list(candidate.get("known_package_gaps_carried", [])),
                    "warning_count": len(candidate.get("warnings", []) or []),
                    "source_package_status": "stable_with_known_gaps"
                    if candidate.get("known_package_gaps_carried")
                    else "unknown",
                }
            )
            return detail

        return detail

    def _collect_source_refs(
        self,
        request: FormalApplyInspectRequest,
        source_detail: dict[str, Any],
    ) -> list[str]:
        refs: list[str] = []
        refs.extend(self._safe_string_list(source_detail.get("source_refs", [])))
        detail_refs = self._safe_string_list(source_detail.get("source_refs", []))
        source_detail_is_user_only = bool(detail_refs) and all(
            self._is_user_supplement_ref(ref) for ref in detail_refs
        ) and not source_detail.get("known_gaps")
        request_ref_is_user = self._is_user_supplement_ref(str(request.source_id)) or (
            request.source_type.lower().replace("-", "_") == "user_supplement"
        )
        if source_detail_is_user_only and not request_ref_is_user:
            pass
        elif request.source_type and request.source_id:
            refs.append(f"{request.source_type}:{request.source_id}")
        elif request.source_id:
            refs.append(request.source_id)
        if request.candidate_id:
            refs.append(f"candidate:{request.candidate_id}")
        refs.extend(self._safe_string_list(source_detail.get("known_gaps", [])))
        return self._dedupe([self._short(ref, 180) for ref in refs if ref])

    def _candidate_source_refs(self, candidate: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        raw_refs: list[str] = []
        for ref in candidate.get("source_refs", []) or []:
            if not isinstance(ref, dict):
                raw_refs.append(str(ref))
                continue
            source_type = str(ref.get("source_type") or "source")
            source_id = str(ref.get("source_id") or "")
            if source_id:
                raw_refs.append(f"{source_type}:{source_id}")
            safe_summary = str(ref.get("safe_summary") or "")
            if CHARACTER_ARC_GAP_ID in safe_summary:
                raw_refs.append(CHARACTER_ARC_GAP_ID)
        known_gaps = self._safe_string_list(candidate.get("known_package_gaps_carried", []))
        has_user_supplement_refs = any(self._is_user_supplement_ref(ref) for ref in raw_refs)
        has_non_user_refs = any(not self._is_user_supplement_ref(ref) for ref in raw_refs)
        if not (has_user_supplement_refs and not has_non_user_refs and not known_gaps):
            refs.extend(
                [
                    f"analyze_stories:{candidate.get('candidate_family', 'candidate')}:{candidate.get('candidate_id', '')}",
                    f"analyze_stories:import:{candidate.get('import_id', '')}",
                ]
            )
        refs.extend(raw_refs)
        refs.extend(known_gaps)
        return self._dedupe([ref for ref in refs if ref and not ref.endswith(":")])

    def _source_package_status(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key in ("source_package_status", "external_contract_confidence"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return self._short(value, 80)
            manifest = payload.get("run_manifest")
            if isinstance(manifest, dict):
                value = manifest.get("source_package_status")
                if isinstance(value, str) and value:
                    return self._short(value, 80)
        return "unknown"

    def _target_label(self, request: FormalApplyInspectRequest, source_detail: dict[str, Any]) -> str:
        label = request.safe_note or source_detail.get("source_id") or request.target_type
        return self._short(str(label), 140)

    def _source_system(
        self,
        request: FormalApplyInspectRequest,
        source_refs: list[str],
        source_detail: dict[str, Any],
    ) -> str:
        if any(self._is_user_supplement_ref(ref) for ref in source_refs):
            return "user_supplement"
        if "analyze_stories" in " ".join(source_refs).lower():
            return "analyze_stories"
        if str(source_detail.get("source_type", "")).startswith("analyze_stories"):
            return "analyze_stories"
        return self._short(request.source_type or "unknown", 80)

    def _lineage_summary(
        self,
        request: FormalApplyInspectRequest,
        source_refs: list[str],
        known_gaps: list[str],
    ) -> str:
        gap_note = f" Known gaps: {', '.join(known_gaps[:3])}." if known_gaps else ""
        return self._short(
            f"Target {request.target_type} inspected from {len(source_refs)} safe source refs.{gap_note}",
            260,
        )

    def _report_summary(
        self,
        status: FormalApplyEligibilityStatus,
        target_type: FormalApplyTargetType,
    ) -> str:
        return (
            f"{target_type} classified as {status}. "
            "M2 performed eligibility classification only and did not write formal story facts."
        )

    def _reason_summary(self, code: str) -> str:
        summaries = {
            "framework_candidate_not_found": "Framework candidate was not found in local safe candidate storage.",
            "framework_candidate_not_ready": "Framework candidate is not normalized and ready for workbench review.",
            "set_active_not_supported_in_m2_v1": "Setting an imported framework active is outside M2 v1.",
            "reference_only_evidence_cannot_mutate": "Reference-only evidence cannot mutate active framework state.",
            "chapter_archive_candidate_not_found": "Chapter archive candidate was not found.",
            "chapter_archive_candidate_not_ready": "Chapter archive candidate is blocked or unavailable.",
            "narrative_debt_candidate_not_found": "Narrative debt candidate was not found.",
            "narrative_debt_candidate_not_ready": "Narrative debt candidate is blocked or unavailable.",
            "character_arc_empty_by_design_source_not_apply_eligible": "Known character-arc gap blocks Analyze Stories sourced apply eligibility.",
            "recommendation_promotion_requires_m7_governance": "Recommendation promotion requires later governance.",
            "target_type_requires_future_governance": "This target type requires a future governance milestone.",
            "unsupported_target_type": "Unsupported target type for Phase 6 M2.",
        }
        return summaries.get(code, code.replace("_", " "))

    def _first_non_user_source(self, refs: list[str]) -> str | None:
        for ref in refs:
            if not self._is_user_supplement_ref(ref):
                return ref
        return refs[0] if refs else None

    def _is_user_supplement_ref(self, ref: str) -> bool:
        lowered = ref.lower()
        return lowered.startswith("user_supplement:") or lowered.startswith("user-supplement:")

    def _ensure_storage_files(self) -> None:
        for path in (
            self.targets_file,
            self.source_lineages_file,
            self.eligibility_reports_file,
            self.block_reasons_file,
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
                    if any(part in normalized_key for part in UNSAFE_KEY_PARTS):
                        raise StorageError(f"FORMAL_APPLY_ELIGIBILITY_UNSAFE_PAYLOAD_BLOCKED: {path}.{key}")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if isinstance(value, str):
                lowered = value.lower()
                if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
                    raise StorageError(f"FORMAL_APPLY_ELIGIBILITY_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if SECRET_LIKE_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_ELIGIBILITY_UNSAFE_PAYLOAD_BLOCKED: {path}")
                if FILESYSTEM_PATH_RE.search(value):
                    raise StorageError(f"FORMAL_APPLY_ELIGIBILITY_UNSAFE_PAYLOAD_BLOCKED: {path}")

        visit(payload, "$")

    def _safe_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        output: list[str] = []
        for item in value:
            if isinstance(item, str):
                output.append(item)
        return output

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
