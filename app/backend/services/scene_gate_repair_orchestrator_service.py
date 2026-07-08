from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.scene_gate_repair import (
    GateRunReport,
    SceneGateAnalysisReport,
    SceneGateRepairLoopResult,
    SceneGateRepairRoundReport,
    SceneRevisionPlan,
)
from app.backend.models.scene_revision import SceneWritingRepairEntryResponse
from app.backend.services.continuity_gate_service import ContinuityGateService
from app.backend.services.quality_check_service import QualityCheckService
from app.backend.services.scene_gate_analysis_agent_service import (
    SceneGateAnalysisAgentService,
    WRITER_CATEGORIES,
)
from app.backend.services.writer_gate_finding_bridge_service import (
    WRITER_GATE_HARD_LEAK_CATEGORIES,
)
from app.backend.services.scene_gate_repair_adapter_service import (
    SceneGateRepairAdapterService,
)
from app.backend.services.scene_revision_plan_service import SceneRevisionPlanService
from app.backend.services.scene_revision_service import SceneRevisionService
from app.backend.services.scene_runtime_refresh_state_service import (
    SceneRuntimeRefreshStateService,
)
from app.backend.storage.json_store import JsonStore, StorageError


SHANGHAI_TZ = timezone(timedelta(hours=8))
M6_ALLOWED_WRITER_ACTION = "rewrite_scene_prose"
M6_UPSTREAM_ACTIONS = {
    "refresh_scene_information",
    "refresh_story_information_package",
    "refresh_memory_retrieval",
    "regenerate_memory_extraction_candidates",
    "refresh_scene_participation",
    "refresh_runtime_evidence",
    "rerun_quality_gate",
    "rerun_continuity_gate",
}
M6_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9._-]*"),
    re.compile(r"(?i)\blsv2_[A-Za-z0-9._-]*"),
)
M6_UNSAFE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\braw[_ ]prompt\b",
        r"\braw[_ ]response\b",
        r"\bhidden[_ ]reasoning\b",
        r"\bhidden[_ ]prompt\b",
        r"\bchain[-_ ]of[-_ ]thought\b",
        r"\btraceback\b",
        r"\bprovider raw\b",
    )
)


class SceneGateRepairOrchestratorService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        quality_service: QualityCheckService | None = None,
        continuity_service: ContinuityGateService | None = None,
        runtime_refresh_service: SceneRuntimeRefreshStateService | None = None,
        adapter_service: SceneGateRepairAdapterService | None = None,
        analysis_service: SceneGateAnalysisAgentService | None = None,
        revision_plan_service: SceneRevisionPlanService | None = None,
        scene_revision_service: SceneRevisionService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.scenes_file = self.data_dir / "scenes.json"
        self.quality_service = quality_service or QualityCheckService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.continuity_service = continuity_service or ContinuityGateService(
            data_dir=self.data_dir,
        )
        self.runtime_refresh_service = runtime_refresh_service or SceneRuntimeRefreshStateService(
            data_dir=self.data_dir,
        )
        self.adapter_service = adapter_service or SceneGateRepairAdapterService()
        self.analysis_service = analysis_service or SceneGateAnalysisAgentService()
        self.revision_plan_service = revision_plan_service or SceneRevisionPlanService()
        self.scene_revision_service = scene_revision_service or SceneRevisionService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def run_scene_gate_repair_loop(
        self,
        scene_id: str,
        *,
        project_id: str = "",
        chapter_id: str = "",
        initial_revision_id: str = "",
        max_rounds: int = 3,
        force_runtime_refresh: bool = True,
    ) -> SceneGateRepairLoopResult:
        max_rounds = min(5, max(1, int(max_rounds or 3)))
        scene = self._find_scene(scene_id)
        resolved_project_id = project_id or str(scene.get("project_id") or "")
        resolved_chapter_id = chapter_id or str(scene.get("chapter_id") or "")
        initial_target_type = "scene_revision" if initial_revision_id else "scene"
        initial_target_id = initial_revision_id or scene_id
        repair_run_id = self._stable_hash(
            "scene_gate_repair_run",
            {
                "scene_id": scene_id,
                "project_id": resolved_project_id,
                "chapter_id": resolved_chapter_id,
                "initial_revision_id": initial_revision_id,
                "max_rounds": max_rounds,
            },
        )

        current_target_type = initial_target_type
        current_revision_id = initial_revision_id
        previous_analysis_reports: list[SceneGateAnalysisReport] = []
        previous_blocking_signatures: set[str] = set()
        previous_plan_signatures: set[str] = set()
        repair_attempted = False
        round_reports: list[SceneGateRepairRoundReport] = []

        for round_index in range(max_rounds):
            target_signature = self._target_content_signature(scene_id, current_revision_id)
            quality_response = self._run_quality(
                scene_id=scene_id,
                revision_id=current_revision_id,
            )
            continuity_response = self._run_continuity(
                scene_id=scene_id,
                revision_id=current_revision_id,
            )
            runtime_state = self.runtime_refresh_service.refresh(
                scene_id,
                revision_id=current_revision_id,
                force_refresh=force_runtime_refresh,
            )
            gate_run = self.adapter_service.build_gate_run_report(
                project_id=resolved_project_id,
                chapter_id=resolved_chapter_id,
                scene_id=scene_id,
                candidate_id=current_revision_id,
                revision_id=current_revision_id,
                round_index=round_index,
                quality_report=self._model_to_dict(quality_response.report),
                continuity_report=self._model_to_dict(continuity_response),
                runtime_refresh_state=runtime_state,
            )
            analysis = self.analysis_service.analyze_gate_run_report(
                gate_run,
                previous_analysis_reports=previous_analysis_reports,
            )
            plan = self.revision_plan_service.build_revision_plan(analysis)
            blocking_signatures = self._blocking_finding_signatures(gate_run)
            repeated_signatures = sorted(blocking_signatures & previous_blocking_signatures)
            stop_repeated_signatures = self._repeated_signatures_requiring_stop(
                gate_run,
                repeated_signatures,
            )
            round_report = self._round_report(
                repair_run_id=repair_run_id,
                round_index=round_index,
                scene_id=scene_id,
                project_id=resolved_project_id,
                chapter_id=resolved_chapter_id,
                target_type=current_target_type,
                revision_id=current_revision_id,
                gate_run=gate_run,
                analysis=analysis,
                plan=plan,
                repeated_signatures=repeated_signatures,
            )
            round_reports.append(round_report)

            if self._is_approved_gate_state(gate_run, analysis):
                round_reports[-1] = round_report.copy(
                    update={
                        "round_status": "approved_candidate_ready_for_user_acceptance",
                        "safe_user_summary": self._safe_text(
                            "Candidate passed explicit quality, explicit continuity, and runtime refresh checks."
                        ),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    approved_candidate_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status="approved_candidate_ready_for_user_acceptance",
                    ready=True,
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            immediate_stop = self._immediate_stop_status(gate_run, analysis, plan)
            if immediate_stop:
                round_reports[-1] = round_report.copy(
                    update={
                        "round_status": immediate_stop,
                        "stop_reason": self._stop_reason(gate_run, analysis, plan),
                        "safe_user_summary": self._stop_summary(analysis, plan),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status=immediate_stop,
                    blocked_reasons=[round_reports[-1].stop_reason],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            if repair_attempted and stop_repeated_signatures:
                round_reports[-1] = round_report.copy(
                    update={
                        "round_status": "blocked_repeated_findings",
                        "stop_reason": "blocking_finding_signature_repeated_after_repair",
                        "safe_user_summary": self._safe_text(
                            "The same blocking gate issue persisted after a repair attempt."
                        ),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status="blocked_repeated_findings",
                    blocked_reasons=["blocking_finding_signature_repeated_after_repair"],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            if (
                repair_attempted
                and plan.revision_plan_signature in previous_plan_signatures
                and not self._is_writer_only_plan(plan)
            ):
                round_reports[-1] = round_report.copy(
                    update={
                        "round_status": "blocked_repeated_findings",
                        "stop_reason": "revision_plan_signature_repeated_after_repair",
                        "safe_user_summary": self._safe_text(
                            "The same repair plan repeated after a repair attempt."
                        ),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status="blocked_repeated_findings",
                    blocked_reasons=["revision_plan_signature_repeated_after_repair"],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            execution_plan = self._writer_execution_plan(plan)
            if execution_plan is None:
                status = self._non_writer_plan_status(gate_run, plan)
                round_reports[-1] = round_report.copy(
                    update={
                        "round_status": status,
                        "stop_reason": self._stop_reason(gate_run, analysis, plan),
                        "safe_user_summary": self._stop_summary(analysis, plan),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status=status,
                    blocked_reasons=[round_reports[-1].stop_reason],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            if round_index >= max_rounds - 1:
                round_reports[-1] = round_report.copy(
                    update={
                        "round_status": "blocked_max_rounds_reached",
                        "stop_reason": "max_rounds_reached_before_verified_approval",
                        "safe_user_summary": self._safe_text(
                            "The bounded repair loop reached its maximum round count before approval."
                        ),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status="blocked_max_rounds_reached",
                    blocked_reasons=["max_rounds_reached_before_verified_approval"],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            previous_analysis_reports.append(analysis)
            previous_blocking_signatures.update(blocking_signatures)
            previous_plan_signatures.add(execution_plan.revision_plan_signature)
            m5_response = self.scene_revision_service.revise_scene_from_plan(
                scene_id,
                execution_plan,
                source_gate_run_id=gate_run.gate_run_id,
                source_analysis_id=analysis.analysis_id,
            )
            round_reports[-1] = round_reports[-1].copy(
                update={
                    "m5_status": m5_response.status,
                    "created_revision_id": m5_response.revision_id if m5_response.success else "",
                    "round_status": (
                        "repair_candidate_created"
                        if m5_response.status == "candidate_created"
                        else self._m5_blocked_status(m5_response.status)
                    ),
                    "stop_reason": "" if m5_response.success else ",".join(m5_response.blocked_reasons),
                    "safe_user_summary": self._safe_text(m5_response.safe_user_summary),
                    "internal_trace_refs": self._unique(
                        [
                            *round_reports[-1].internal_trace_refs,
                            *m5_response.internal_trace_refs,
                        ]
                    ),
                }
            )
            if m5_response.status != "candidate_created" or not m5_response.revision_id:
                final_status = self._m5_blocked_status(m5_response.status)
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type=current_target_type,
                    final_revision_id=current_revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status=final_status,
                    blocked_reasons=m5_response.blocked_reasons or [m5_response.status],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            new_signature = self._target_content_signature(scene_id, m5_response.revision_id)
            if new_signature == target_signature:
                round_reports[-1] = round_reports[-1].copy(
                    update={
                        "round_status": "blocked_no_effective_repair",
                        "stop_reason": "revision_candidate_content_signature_unchanged",
                        "safe_user_summary": self._safe_text(
                            "The repair candidate did not change the scene synopsis or prose."
                        ),
                    }
                )
                return self._result(
                    repair_run_id=repair_run_id,
                    scene_id=scene_id,
                    project_id=resolved_project_id,
                    chapter_id=resolved_chapter_id,
                    initial_target_type=initial_target_type,
                    initial_revision_id=initial_revision_id,
                    final_target_type="scene_revision",
                    final_revision_id=m5_response.revision_id,
                    max_rounds=max_rounds,
                    round_reports=round_reports,
                    final_status="blocked_no_effective_repair",
                    blocked_reasons=["revision_candidate_content_signature_unchanged"],
                    safe_user_summary=round_reports[-1].safe_user_summary,
                )

            repair_attempted = True
            current_target_type = "scene_revision"
            current_revision_id = m5_response.revision_id

        return self._result(
            repair_run_id=repair_run_id,
            scene_id=scene_id,
            project_id=resolved_project_id,
            chapter_id=resolved_chapter_id,
            initial_target_type=initial_target_type,
            initial_revision_id=initial_revision_id,
            final_target_type=current_target_type,
            final_revision_id=current_revision_id,
            max_rounds=max_rounds,
            round_reports=round_reports,
            final_status="blocked_max_rounds_reached",
            blocked_reasons=["max_rounds_reached"],
            safe_user_summary="The bounded repair loop reached its maximum round count.",
        )

    def _run_quality(self, *, scene_id: str, revision_id: str) -> Any:
        if revision_id:
            return self.quality_service.check_scene_revision(scene_id, revision_id)
        return self.quality_service.check_scene_draft(scene_id)

    def _run_continuity(self, *, scene_id: str, revision_id: str) -> Any:
        if revision_id:
            return self.continuity_service.check_scene_revision(
                scene_id,
                revision_id,
                mode="scene_gate_repair_loop",
            )
        return self.continuity_service.check_scene(
            scene_id,
            mode="scene_gate_repair_loop",
        )

    def _round_report(
        self,
        *,
        repair_run_id: str,
        round_index: int,
        scene_id: str,
        project_id: str,
        chapter_id: str,
        target_type: str,
        revision_id: str,
        gate_run: GateRunReport,
        analysis: SceneGateAnalysisReport,
        plan: SceneRevisionPlan,
        repeated_signatures: list[str],
    ) -> SceneGateRepairRoundReport:
        return SceneGateRepairRoundReport(
            repair_run_id=repair_run_id,
            round_index=round_index,
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            target_type=target_type,
            target_id=revision_id or scene_id,
            revision_id=revision_id,
            quality_checked=gate_run.quality_checked,
            quality_gate_run_id=gate_run.quality_gate_run_id,
            quality_passed=gate_run.quality_passed,
            continuity_checked=gate_run.continuity_checked,
            continuity_gate_run_id=gate_run.continuity_gate_run_id,
            continuity_passed=gate_run.continuity_passed,
            runtime_refresh_checked=gate_run.runtime_refresh_checked,
            runtime_confirm_allowed=gate_run.runtime_confirm_allowed,
            runtime_blocking_reasons=gate_run.runtime_blocking_reasons,
            gate_run_id=gate_run.gate_run_id,
            analysis_id=analysis.analysis_id,
            revision_plan_id=plan.revision_plan_id,
            revision_plan_signature=plan.revision_plan_signature,
            finding_signatures=[finding.finding_signature for finding in gate_run.findings],
            repeated_finding_signatures=repeated_signatures,
            blocking_finding_ids=gate_run.blocking_finding_ids,
            user_action_required=analysis.user_action_required or analysis.requires_user_confirmation,
            user_action_options=analysis.user_action_options,
            plan_status=plan.plan_status,
            recommended_next_step=plan.recommended_next_step,
            round_status="blocked_no_safe_plan",
            safe_user_summary=self._safe_text(analysis.user_facing_status_summary or plan.safe_user_summary),
            internal_trace_refs=self._unique(
                [
                    f"gate_run:{gate_run.gate_run_id}",
                    f"scene_gate_analysis:{analysis.analysis_id}",
                    f"scene_revision_plan:{plan.revision_plan_id}",
                    *gate_run.source_refs,
                    *analysis.source_refs,
                    *plan.source_refs,
                ]
            ),
        )

    def _result(
        self,
        *,
        repair_run_id: str,
        scene_id: str,
        project_id: str,
        chapter_id: str,
        initial_target_type: str,
        initial_revision_id: str,
        final_target_type: str,
        final_revision_id: str,
        max_rounds: int,
        round_reports: list[SceneGateRepairRoundReport],
        final_status: str,
        ready: bool = False,
        approved_candidate_id: str = "",
        blocked_reasons: list[str] | None = None,
        safe_user_summary: str = "",
    ) -> SceneGateRepairLoopResult:
        final_target_id = final_revision_id or scene_id
        refs = self._unique(
            [
                f"scene:{scene_id}",
                *[
                    ref
                    for report in round_reports
                    for ref in report.internal_trace_refs
                ],
            ]
        )
        signature = self._stable_hash(
            "scene_gate_repair_run_signature",
            {
                "repair_run_id": repair_run_id,
                "scene_id": scene_id,
                "initial_revision_id": initial_revision_id,
                "final_status": final_status,
                "rounds": [
                    {
                        "round_index": report.round_index,
                        "round_status": report.round_status,
                        "gate_run_id": report.gate_run_id,
                        "analysis_id": report.analysis_id,
                        "revision_plan_signature": report.revision_plan_signature,
                        "created_revision_id": report.created_revision_id,
                    }
                    for report in round_reports
                ],
            },
        )
        user_action_options = self._unique_user_options(
            [
                option
                for report in round_reports
                for option in report.user_action_options
            ]
        )
        if final_status == "stopped_requires_expert_review" and "expert_review" not in user_action_options:
            user_action_options.append("expert_review")
        return SceneGateRepairLoopResult(
            repair_run_id=repair_run_id,
            repair_run_signature=signature,
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            initial_target_type=initial_target_type,
            initial_target_id=initial_revision_id or scene_id,
            initial_revision_id=initial_revision_id,
            final_target_type=final_target_type,
            final_target_id=final_target_id,
            final_revision_id=final_revision_id,
            approved_candidate_id=approved_candidate_id if ready else "",
            max_rounds=max_rounds,
            rounds_completed=len(round_reports),
            final_status=final_status,
            ready_for_user_final_acceptance=ready,
            user_visible_required=final_status.startswith("stopped_"),
            user_action_required=final_status.startswith("stopped_"),
            user_action_options=user_action_options,
            safe_user_summary=self._safe_text(safe_user_summary),
            blocked_reasons=blocked_reasons or [],
            round_reports=round_reports,
            source_refs=refs,
            no_write_authority_summary=(
                "M6 orchestrates gate checks, runtime evidence, analysis, planning, "
                "and M5 revision candidate creation only. It does not confirm or apply "
                "revisions, resolve continuity issues, write memory/canon, or export final output."
            ),
        )

    def _is_approved_gate_state(
        self,
        gate_run: GateRunReport,
        analysis: SceneGateAnalysisReport,
    ) -> bool:
        return (
            gate_run.quality_checked
            and gate_run.quality_passed is True
            and gate_run.continuity_checked
            and gate_run.continuity_passed is True
            and gate_run.runtime_refresh_checked
            and gate_run.runtime_confirm_allowed is True
            and not gate_run.provider_degraded
            and not gate_run.blocking_finding_ids
            and not gate_run.confirmation_required_finding_ids
            and not analysis.requires_user_confirmation
            and not analysis.user_action_required
            and analysis.recommended_next_action != "stop_for_expert_review"
        )

    def _immediate_stop_status(
        self,
        gate_run: GateRunReport,
        analysis: SceneGateAnalysisReport,
        plan: SceneRevisionPlan,
    ) -> str:
        if gate_run.provider_degraded or analysis.degraded_finding_ids:
            return "blocked_provider_degraded"
        if not gate_run.continuity_checked:
            return "blocked_missing_explicit_continuity_evidence"
        if plan.requires_expert_review or plan.recommended_next_step == "stop_for_expert_review":
            return "stopped_requires_expert_review"
        if analysis.recommended_next_action == "stop_for_expert_review":
            return "stopped_requires_expert_review"
        if (
            plan.requires_user_confirmation
            or plan.may_touch_user_requested_content
            or plan.recommended_next_step == "stop_for_user_confirmation"
            or analysis.requires_user_confirmation
            or analysis.user_action_required
            or analysis.recommended_next_action == "stop_for_user_confirmation"
        ):
            return "stopped_requires_user_confirmation"
        if plan.plan_status == "refresh_required" or plan.recommended_next_step == "refresh_runtime_or_gate_evidence_later":
            return "blocked_upstream_refresh_required"
        return ""

    def _non_writer_plan_status(self, gate_run: GateRunReport, plan: SceneRevisionPlan) -> str:
        action_types = {action.action_type for action in plan.repair_actions}
        if action_types & M6_UPSTREAM_ACTIONS:
            return "blocked_upstream_refresh_required"
        if gate_run.runtime_confirm_allowed is False:
            return "blocked_runtime_confirm_not_allowed"
        if gate_run.runtime_refresh_checked is False:
            return "blocked_runtime_refresh_required"
        return "blocked_no_safe_plan"

    def _is_writer_only_plan(self, plan: SceneRevisionPlan) -> bool:
        if plan.plan_status != "ready_for_repair":
            return False
        if plan.recommended_next_step != "execute_repair_plan_later":
            return False
        if not plan.auto_repair_plan_allowed:
            return False
        if plan.requires_user_confirmation or plan.requires_expert_review:
            return False
        if plan.may_touch_user_requested_content:
            return False
        if not plan.repair_actions:
            return False
        return all(
            action.action_type == M6_ALLOWED_WRITER_ACTION
            and action.target_repair_system == "writer"
            and not action.requires_user_confirmation
            and not action.requires_expert_review
            and not action.may_touch_user_requested_content
            for action in plan.repair_actions
        )

    def _writer_execution_plan(self, plan: SceneRevisionPlan) -> SceneRevisionPlan | None:
        if self._is_writer_only_plan(plan):
            return plan
        if plan.plan_status != "ready_for_repair":
            return None
        if plan.recommended_next_step != "execute_repair_plan_later":
            return None
        if not plan.auto_repair_plan_allowed:
            return None
        if (
            plan.requires_user_confirmation
            or plan.requires_expert_review
            or plan.may_touch_user_requested_content
        ):
            return None

        writer_actions = [
            action
            for action in plan.repair_actions
            if action.action_type == M6_ALLOWED_WRITER_ACTION
            and action.target_repair_system == "writer"
            and not action.requires_user_confirmation
            and not action.requires_expert_review
            and not action.may_touch_user_requested_content
        ]
        if not writer_actions:
            return None

        blocked_group_ids = set(plan.blocked_group_ids or [])
        if blocked_group_ids:
            writer_actions = [
                action
                for action in writer_actions
                if set(action.source_group_ids) & blocked_group_ids
            ]
            if not writer_actions:
                return None

        executable_action_ids = {action.action_id for action in writer_actions}
        for action in plan.repair_actions:
            if action.action_id in executable_action_ids:
                continue
            if (
                action.requires_user_confirmation
                or action.requires_expert_review
                or action.may_touch_user_requested_content
            ):
                return None
            if blocked_group_ids and set(action.source_group_ids) & blocked_group_ids:
                return None
            if action.action_type not in M6_UPSTREAM_ACTIONS:
                return None

        signature = self._stable_hash(
            "scene_revision_plan_writer_execution_signature",
            {
                "source_plan_signature": plan.revision_plan_signature,
                "writer_action_signatures": [
                    action.action_signature for action in writer_actions
                ],
            },
        )
        writer_group_ids = self._unique(
            [
                group_id
                for action in writer_actions
                for group_id in action.source_group_ids
            ]
        )
        writer_finding_ids = self._unique(
            [
                finding_id
                for action in writer_actions
                for finding_id in action.source_finding_ids
            ]
        )
        writer_finding_signatures = self._unique(
            [
                finding_signature
                for action in writer_actions
                for finding_signature in action.source_finding_signatures
            ]
        )
        forbidden_changes = self._unique(
            [
                forbidden
                for action in writer_actions
                for forbidden in action.forbidden_changes
            ]
        )
        deferred_action_types = self._unique(
            [
                action.action_type
                for action in plan.repair_actions
                if action.action_id not in executable_action_ids
            ]
        )
        summary_suffix = ""
        if deferred_action_types:
            summary_suffix = (
                " Deferred nonblocking advisory action(s) for later evidence refresh: "
                + ", ".join(deferred_action_types)
                + "."
            )
        return plan.copy(
            update={
                "revision_plan_id": f"{plan.revision_plan_id}_writer_execution",
                "revision_plan_signature": signature,
                "root_cause_group_ids": writer_group_ids,
                "finding_ids": writer_finding_ids,
                "finding_signatures": writer_finding_signatures,
                "repair_actions": writer_actions,
                "blocked_group_ids": [
                    group_id
                    for group_id in plan.blocked_group_ids
                    if group_id in set(writer_group_ids)
                ],
                "user_visible_group_ids": [
                    group_id
                    for group_id in plan.user_visible_group_ids
                    if group_id in set(writer_group_ids)
                ],
                "user_action_required_group_ids": [],
                "requires_user_confirmation": False,
                "requires_expert_review": False,
                "auto_repair_plan_allowed": True,
                "may_touch_user_requested_content": False,
                "requires_fresh_story_information": any(
                    action.requires_fresh_story_information for action in writer_actions
                ),
                "requires_fresh_memory_retrieval": any(
                    action.requires_fresh_memory_retrieval for action in writer_actions
                ),
                "requires_fresh_memory_extraction": any(
                    action.requires_fresh_memory_extraction for action in writer_actions
                ),
                "requires_fresh_quality_check": any(
                    action.requires_fresh_quality_check for action in writer_actions
                ),
                "requires_fresh_continuity_check": any(
                    action.requires_fresh_continuity_check for action in writer_actions
                ),
                "requires_runtime_refresh_after_repair": any(
                    action.requires_runtime_refresh_after_repair for action in writer_actions
                ),
                "forbidden_changes": forbidden_changes,
                "plan_summary": (
                    "M6 writer execution subset derived from mixed repair plan."
                    + summary_suffix
                )[:1000],
                "safe_user_summary": (
                    plan.safe_user_summary
                    + " M6 will execute only the safe writer prose repair subset now."
                    + summary_suffix
                )[:1000],
                "stop_reason": "",
                "source_refs": self._unique(
                    [
                        *plan.source_refs,
                        f"source_scene_revision_plan:{plan.revision_plan_id}",
                    ]
                ),
            }
        )

    def _m5_blocked_status(self, m5_status: str) -> str:
        mapping = {
            "blocked_requires_user_confirmation": "stopped_requires_user_confirmation",
            "blocked_requires_expert_review": "stopped_requires_expert_review",
            "blocked_requires_upstream_refresh": "blocked_upstream_refresh_required",
            "blocked_plan_not_auto_repairable": "blocked_no_safe_plan",
            "blocked_unsupported_action_type": "blocked_no_safe_plan",
            "blocked_invalid_plan": "blocked_no_safe_plan",
            "blocked_scene_mismatch": "blocked_m5_candidate_creation_failed",
        }
        return mapping.get(m5_status, "blocked_m5_candidate_creation_failed")

    def _stop_reason(
        self,
        gate_run: GateRunReport,
        analysis: SceneGateAnalysisReport,
        plan: SceneRevisionPlan,
    ) -> str:
        reasons = [
            *gate_run.runtime_blocking_reasons,
            *analysis.auto_repair_blocking_reasons,
            analysis.recommended_stop_reason,
            plan.stop_reason,
        ]
        if gate_run.provider_degraded:
            reasons.append("provider_degraded")
        if not gate_run.continuity_checked:
            reasons.append("explicit_continuity_evidence_missing")
        if plan.recommended_next_step:
            reasons.append(plan.recommended_next_step)
        return self._safe_text(", ".join([reason for reason in reasons if reason]), 600)

    def _stop_summary(self, analysis: SceneGateAnalysisReport, plan: SceneRevisionPlan) -> str:
        return self._safe_text(
            analysis.user_facing_status_summary
            or analysis.analysis_summary
            or plan.safe_user_summary
            or plan.plan_summary
            or "The repair loop stopped before creating a safe revision candidate.",
            1000,
        )

    def _blocking_finding_signatures(self, gate_run: GateRunReport) -> set[str]:
        keys: set[str] = set()
        for finding in gate_run.findings:
            if not (
                finding.finding_id in gate_run.blocking_finding_ids
                or finding.finding_id in gate_run.confirmation_required_finding_ids
                or finding.blocks_final_output
                or finding.severity in {"blocking", "requires_user_confirmation"}
            ):
                continue
            keys.add(finding.finding_signature)
            keys.add(self._finding_repeat_key(finding))
        return keys

    def _finding_repeat_key(self, finding: Any) -> str:
        return self._stable_hash(
            "finding_repeat_key",
            {
                "gate_type": getattr(finding, "gate_type", ""),
                "category": getattr(finding, "category", ""),
                "severity": getattr(finding, "severity", ""),
                "affected_fields": getattr(finding, "affected_fields", []),
                "requires_user_confirmation": getattr(finding, "requires_user_confirmation", False),
                "blocks_final_output": getattr(finding, "blocks_final_output", False),
            },
        )

    def _repeated_signatures_requiring_stop(
        self,
        gate_run: GateRunReport,
        repeated_signatures: list[str],
    ) -> list[str]:
        repeated = set(repeated_signatures)
        if not repeated:
            return []
        stop_signatures: set[str] = set()
        for finding in gate_run.findings:
            finding_keys = {
                str(getattr(finding, "finding_signature", "") or ""),
                self._finding_repeat_key(finding),
            }
            matched = {key for key in finding_keys if key and key in repeated}
            if not matched:
                continue
            if self._repeated_finding_can_continue_auto_repair(finding):
                continue
            stop_signatures.update(matched)
        return sorted(stop_signatures)

    def _repeated_finding_can_continue_auto_repair(self, finding: Any) -> bool:
        category = str(getattr(finding, "category", "") or "")
        severity = str(getattr(finding, "severity", "") or "")
        if category not in WRITER_CATEGORIES:
            return False
        if category in WRITER_GATE_HARD_LEAK_CATEGORIES:
            return False
        if bool(getattr(finding, "requires_user_confirmation", False)):
            return False
        if severity == "requires_user_confirmation":
            return False
        if bool(getattr(finding, "blocks_auto_repair", False)):
            return False
        return True

    def _target_content_signature(self, scene_id: str, revision_id: str) -> str:
        scene = self._find_scene(scene_id)
        if revision_id:
            candidate = self._find_revision_candidate(scene, revision_id)
            text = "\n".join(
                [
                    str(candidate.get("revised_synopsis") or ""),
                    str(candidate.get("revised_prose_text") or ""),
                ]
            )
        else:
            content = scene.get("content") if isinstance(scene.get("content"), dict) else {}
            text = "\n".join(
                [
                    str(scene.get("synopsis") or content.get("synopsis") or ""),
                    str(scene.get("prose_text") or content.get("prose_text") or ""),
                ]
            )
        normalized = " ".join(text.casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _find_scene(self, scene_id: str) -> dict[str, Any]:
        clean = str(scene_id or "").strip()
        for scene in self.store.read_list(self.scenes_file):
            if isinstance(scene, dict) and str(scene.get("scene_id") or "") == clean:
                return scene
        raise StorageError(f"SCENE_GATE_REPAIR_SCENE_NOT_FOUND: {scene_id}")

    def _find_revision_candidate(self, scene: dict[str, Any], revision_id: str) -> dict[str, Any]:
        for candidate in scene.get("revision_history") or []:
            if isinstance(candidate, dict) and str(candidate.get("revision_id") or "") == revision_id:
                return candidate
        raise StorageError(f"SCENE_GATE_REPAIR_REVISION_NOT_FOUND: {revision_id}")

    def _stable_hash(self, prefix: str, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:24]}"

    def _model_to_dict(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, BaseModel):
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json")
            return value.dict()
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "dict"):
            return value.dict()
        return {}

    def _safe_text(self, value: str, limit: int = 1200) -> str:
        text = str(value or "").strip()
        for pattern in M6_SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        for pattern in M6_UNSAFE_PATTERNS:
            text = pattern.sub("[redacted]", text)
        return text[:limit]

    def _unique(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result[:80]

    def _unique_user_options(self, values: list[str]) -> list[str]:
        allowed = ["modify", "complete", "delete", "confirm_keep", "expert_review"]
        present = {str(value or "").strip() for value in values}
        return [option for option in allowed if option in present]
