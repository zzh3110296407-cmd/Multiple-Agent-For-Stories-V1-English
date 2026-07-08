from __future__ import annotations

import re

from app.backend.models.scene_gate_repair import (
    SCENE_GATE_USER_ACTION_OPTION_ORDER,
    SCENE_GATE_USER_ACTION_OPTIONS,
    SceneGateRepairExpertRoundView,
    SceneGateRepairExpertView,
    SceneGateRepairLoopResult,
    SceneGateRepairOrdinaryView,
)


M7_SECRET_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"(?i)\blsv2_[A-Za-z0-9._-]+"),
)
M7_UNSAFE_VALUE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\braw[_ ]prompt\b",
        r"\braw[_ ]response\b",
        r"\bhidden[_ ]reasoning\b",
        r"\bhidden[_ ]prompt\b",
        r"\bchain[-_ ]of[-_ ]thought\b",
        r"\btraceback\b",
        r"\bprovider raw\b",
        r"\bgatefinding\b",
    )
)

APPROVED_STATUS = "approved_candidate_ready_for_user_acceptance"
USER_ACTION_STATUS = "stopped_requires_user_confirmation"
EXPERT_STATUS = "stopped_requires_expert_review"
BLOCKED_STATUS_TO_ACTION = {
    "blocked_provider_degraded": ("blocked", "retry_gate_repair", True, True),
    "blocked_upstream_refresh_required": ("blocked", "retry_gate_repair", True, True),
    "blocked_runtime_refresh_required": ("blocked", "retry_gate_repair", True, True),
    "blocked_max_rounds_reached": ("blocked", "open_expert_panel", True, False),
    "blocked_repeated_findings": ("blocked", "open_expert_panel", True, False),
    "blocked_no_effective_repair": ("blocked", "open_expert_panel", True, False),
    "blocked_no_safe_plan": ("blocked", "open_expert_panel", True, False),
    "blocked_m5_candidate_creation_failed": ("blocked", "open_expert_panel", True, True),
    "blocked_missing_explicit_continuity_evidence": ("blocked", "open_expert_panel", True, False),
    "blocked_runtime_confirm_not_allowed": ("blocked", "open_expert_panel", True, True),
}


class SceneGateRepairViewProjectionService:
    def build_ordinary_view(self, result: SceneGateRepairLoopResult) -> SceneGateRepairOrdinaryView:
        status_kind, primary_action, show_expert_entry, retry_allowed = self._ordinary_mapping(
            result.final_status
        )
        action_options = self._action_options(result)
        if result.final_status == USER_ACTION_STATUS and not action_options:
            action_options = ["modify", "confirm_keep"]
        if result.final_status == EXPERT_STATUS and "expert_review" not in action_options:
            action_options = [*action_options, "expert_review"]
        if primary_action == "retry_gate_repair" and "retry_gate_repair" not in action_options:
            action_options = [*action_options, "retry_gate_repair"]
        if retry_allowed and "retry_gate_repair" not in action_options:
            action_options = [*action_options, "retry_gate_repair"]
        if primary_action == "open_expert_panel" and "expert_review" not in action_options:
            action_options = [*action_options, "expert_review"]
        show_expert_entry = show_expert_entry or "expert_review" in action_options
        retry_allowed = retry_allowed or "retry_gate_repair" in action_options
        title = self._ordinary_title(result.final_status)
        return SceneGateRepairOrdinaryView(
            scene_id=result.scene_id,
            final_status=result.final_status,
            status_kind=status_kind,
            title=title,
            safe_user_summary=self._safe_summary(result),
            rounds_completed=result.rounds_completed,
            max_rounds=result.max_rounds,
            ready_for_user_final_acceptance=result.ready_for_user_final_acceptance,
            approved_candidate_id=self._safe_id(result.approved_candidate_id),
            approved_revision_id=self._safe_id(result.final_revision_id),
            user_visible_required=result.user_visible_required or result.final_status.startswith("stopped_"),
            user_action_required=result.user_action_required or result.final_status == USER_ACTION_STATUS,
            user_action_options=action_options,
            primary_action=primary_action,
            blocking_reasons=self._safe_list(result.blocked_reasons, limit=8, text_limit=220),
            show_expert_entry=show_expert_entry,
            retry_allowed=retry_allowed,
        )

    def build_expert_view(self, result: SceneGateRepairLoopResult) -> SceneGateRepairExpertView:
        round_views = [
            SceneGateRepairExpertRoundView(
                round_index=round_report.round_index,
                round_status=self._safe_id(round_report.round_status),
                target_type=self._safe_id(round_report.target_type),
                target_id=self._safe_id(round_report.target_id),
                revision_id=self._safe_id(round_report.revision_id),
                gate_run_id=self._safe_id(round_report.gate_run_id),
                quality_gate_run_id=self._safe_id(round_report.quality_gate_run_id),
                continuity_gate_run_id=self._safe_id(round_report.continuity_gate_run_id),
                analysis_id=self._safe_id(round_report.analysis_id),
                revision_plan_id=self._safe_id(round_report.revision_plan_id),
                revision_plan_signature=self._safe_id(round_report.revision_plan_signature),
                finding_signatures=self._safe_list(round_report.finding_signatures, limit=12, text_limit=160),
                repeated_finding_signatures=self._safe_list(
                    round_report.repeated_finding_signatures,
                    limit=12,
                    text_limit=160,
                ),
                user_action_required=round_report.user_action_required,
                user_action_options=self._action_options(round_report),
                m5_status=self._safe_id(round_report.m5_status),
                created_revision_id=self._safe_id(round_report.created_revision_id),
                stop_reason=self._safe_text(round_report.stop_reason, 260),
                safe_user_summary=self._safe_text(round_report.safe_user_summary, 360),
                internal_trace_refs=self._safe_list(round_report.internal_trace_refs, limit=16, text_limit=180),
            )
            for round_report in result.round_reports[: result.max_rounds]
        ]
        return SceneGateRepairExpertView(
            repair_run_id=self._safe_id(result.repair_run_id),
            repair_run_signature=self._safe_id(result.repair_run_signature),
            scene_id=result.scene_id,
            final_status=result.final_status,
            rounds_completed=result.rounds_completed,
            max_rounds=result.max_rounds,
            ready_for_user_final_acceptance=result.ready_for_user_final_acceptance,
            approved_candidate_id=self._safe_id(result.approved_candidate_id),
            approved_revision_id=self._safe_id(result.final_revision_id),
            blocked_reasons=self._safe_list(result.blocked_reasons, limit=12, text_limit=220),
            source_refs=self._safe_list(result.source_refs, limit=24, text_limit=180),
            round_views=round_views,
            no_write_authority_summary=self._safe_text(result.no_write_authority_summary, 900),
        )

    def _ordinary_mapping(self, final_status: str) -> tuple[str, str, bool, bool]:
        if final_status == APPROVED_STATUS:
            return "approved", "accept_candidate", False, False
        if final_status == USER_ACTION_STATUS:
            return "needs_user_action", "open_continuity_tools", False, False
        if final_status == EXPERT_STATUS:
            return "needs_expert", "open_expert_panel", True, False
        return BLOCKED_STATUS_TO_ACTION.get(
            final_status,
            ("failed", "open_expert_panel", True, False),
        )

    def _ordinary_title(self, final_status: str) -> str:
        if final_status == APPROVED_STATUS:
            return "后台检查已生成可确认候选"
        if final_status == USER_ACTION_STATUS:
            return "需要用户处理后才能继续"
        if final_status == EXPERT_STATUS:
            return "需要专家复核"
        if final_status == "blocked_provider_degraded":
            return "模型或运行时暂不可用"
        return "后台修复未能安全完成"

    def _safe_summary(self, result: SceneGateRepairLoopResult) -> str:
        summary = self._safe_text(result.safe_user_summary, 700)
        if summary:
            return summary
        if result.ready_for_user_final_acceptance:
            return "系统已创建或验证修订候选，但它尚未成为正式正文，需要用户最终确认。"
        if result.user_action_required:
            return "系统发现需要用户判断的问题，请先处理后再继续。"
        if result.blocked_reasons:
            return self._safe_text(result.blocked_reasons[0], 700)
        return "后台检查已结束，请查看当前状态并决定下一步。"

    def _action_options(self, value: object) -> list[str]:
        raw_options = getattr(value, "user_action_options", [])
        seen: set[str] = set()
        for option in raw_options or []:
            text = str(option or "").strip()
            if text in SCENE_GATE_USER_ACTION_OPTIONS:
                seen.add(text)
        return [option for option in SCENE_GATE_USER_ACTION_OPTION_ORDER if option in seen]

    def _safe_id(self, value: object, limit: int = 180) -> str:
        return self._safe_text(str(value or ""), limit)

    def _safe_list(self, values: list[str], *, limit: int, text_limit: int) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = self._safe_text(value, text_limit)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= limit:
                break
        return result

    def _safe_text(self, value: object, limit: int) -> str:
        text = str(value or "").strip()
        for pattern in M7_SECRET_PATTERNS:
            text = pattern.sub("[redacted]", text)
        for pattern in M7_UNSAFE_VALUE_PATTERNS:
            text = pattern.sub("[redacted]", text)
        return text[:limit]
