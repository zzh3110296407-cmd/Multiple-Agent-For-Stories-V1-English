from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from app.backend.models.scene_gate_repair import (
    GateFinding,
    GateRunReport,
    M6_CONTENT_SIGNAL_CODES,
    SCENE_GATE_REPAIR_SCHEMA_VERSION,
)
from app.backend.services.writer_gate_finding_bridge_service import (
    WRITER_GATE_REPAIRABLE_CATEGORIES,
    WriterGateFindingBridgeService,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))
UNSAFE_EXCERPT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]+"),
    re.compile(r"\b(raw_prompt|raw_response|hidden_reasoning|chain[-_ ]of[-_ ]thought)\b", re.I),
]
MACHINE_REPAIRABLE_CATEGORIES = {
    "demo_default_leak",
    "scene_repetition_too_high",
    "scene_progression_missing",
    "scene_progression_statement_missing",
    "scene_pattern_similarity_warning",
    "scene_pattern_similarity_too_high",
    "scene_objective_repeated",
    "scene_previous_summary_missing",
    "story_information_coverage",
    "do_not_include_violation",
    "prose_generation_failure",
    "prompt_fidelity_missing",
    "prompt_fidelity_weak",
    "chapter_goal_drift",
    "character_uniqueness_violation",
    "missing_source_fact",
    "no_source_fact",
    "unverified_old_event",
} | WRITER_GATE_REPAIRABLE_CATEGORIES
USER_CONFIRMATION_CATEGORIES = {
    "complete_prior_story",
    "world_hard_rule_direct_conflict",
    "forbidden_knowledge",
    "mark_as_subjective_claim",
    "subjective_claim_conversion",
    "canon_status_change",
    "abcd_runtime_requires_user_confirmation",
}
EXPERT_OR_RUNTIME_BLOCK_CATEGORIES = {
    "provider_degraded",
    "provider_fallback",
    "provider_http_error",
    "continuity_check_evidence_missing",
    "continuity_run_evidence_missing",
    "runtime_evidence_stale",
    "runtime_refresh_not_allowed",
    "runtime_confirm_not_allowed",
    "runtime_refresh_not_confirmable",
    "composite_current_scene_mismatch",
    "composite_runtime_scope_mismatch",
    "composite_runtime_blocked",
    "abcd_runtime_policy_violation",
    "abcd_runtime_blocking_issue",
    "abcd_runtime_failed",
}
USER_CONFIRMATION_FIELDS = {
    "story_idea",
    "premise",
    "world_canvas",
    "character_goal",
    "identity",
    "hard_rules",
    "canon_fact",
}
USER_CONFIRMATION_REPAIR_TYPES = {
    "complete_prior_story",
    "mark_as_subjective_claim",
    "request_user_confirmation",
}
AUTO_REPAIR_ALLOWED_RUNTIME_BLOCKING_REASONS = {
    "quality_requires_user_confirmation",
    "quality_blocking_issues",
    "continuity_blocking_issues",
    "quality_or_continuity_not_passed",
    "scene_gate_pipeline_blocked",
}


class SceneGateRepairAdapterService:
    """Read-only adapter from existing gate outputs to Phase 8.5-D M1 reports."""

    def build_gate_run_report(
        self,
        *,
        project_id: str,
        chapter_id: str = "",
        scene_id: str = "",
        candidate_id: str = "",
        revision_id: str = "",
        round_index: int = 0,
        quality_report: Any | None = None,
        continuity_report: Any | None = None,
        runtime_refresh_state: Any | None = None,
        abcd_runtime_report: Any | None = None,
        composite_runtime_report: Any | None = None,
        provider_status: Any | None = None,
        writer_quality_bundle: Any | None = None,
        writer_self_revision_report: Any | None = None,
        writer_self_revision_result: Any | None = None,
        writer_candidate_draft: Any | None = None,
    ) -> GateRunReport:
        quality = _as_dict(quality_report)
        continuity = _as_dict(continuity_report)
        runtime = _as_dict(runtime_refresh_state)
        abcd = _as_dict(abcd_runtime_report)
        composite = _as_dict(composite_runtime_report)
        provider = _as_dict(provider_status)

        findings: list[GateFinding] = []
        source_refs: list[str] = []

        quality_checked = bool(quality)
        quality_gate_run_id = _first_text(
            quality,
            "quality_report_id",
            "quality_gate_run_id",
            "check_id",
        )
        quality_checked_at = _first_text(quality, "created_at", "checked_at", "updated_at")
        quality_passed = bool(quality.get("passed")) if quality_checked else None
        if quality_gate_run_id:
            source_refs.append(f"quality:{quality_gate_run_id}")
        if quality_checked:
            findings.extend(
                self._quality_findings(
                    quality,
                    scene_id=scene_id,
                    round_index=round_index,
                )
            )

        explicit_continuity = self._has_explicit_continuity_evidence(continuity)
        continuity_checked = explicit_continuity
        continuity_gate_run_id = _first_text(
            continuity,
            "continuity_gate_run_id",
        )
        continuity_checked_at = _first_text(
            continuity,
            "continuity_checked_at",
        )
        continuity_passed = (
            bool(continuity.get("continuity_passed", continuity.get("passed", True)))
            if continuity_checked
            else None
        )
        if continuity_gate_run_id:
            source_refs.append(f"continuity:{continuity_gate_run_id}")
        if not continuity_checked:
            findings.append(
                self._finding(
                    gate_type="continuity",
                    category="continuity_check_evidence_missing",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="runtime_evidence",
                    source_check_id="",
                    source_issue_id="",
                    affected_fields=["continuity_passed"],
                    evidence_refs=["quality_report.continuity_passed_default_true"],
                    safe_source_excerpt=(
                        "No explicit continuity gate run evidence was provided; "
                        "default continuity_passed=true is not trusted."
                    ),
                    suggested_repair_types=["run_continuity_gate"],
                    blocks_auto_repair=True,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        else:
            findings.extend(
                self._continuity_findings(
                    continuity,
                    scene_id=scene_id,
                    round_index=round_index,
                )
            )

        provider_findings = self._provider_findings(
            quality=quality,
            provider=provider,
            scene_id=scene_id,
            round_index=round_index,
        )
        findings.extend(provider_findings)
        degraded_check_ids = _unique_strings(
            [
                finding.source_check_id or finding.finding_id
                for finding in provider_findings
            ]
        )
        provider_degraded = bool(provider_findings)
        has_quality_or_continuity_release_blocker = any(
            finding.gate_type in {"quality", "continuity"} and finding.blocks_final_output
            for finding in findings
        )

        runtime_checked = bool(runtime)
        runtime_state = _first_text(runtime, "runtime_refresh_state", "state", "status")
        runtime_confirm_allowed = self._runtime_confirm_allowed(runtime) if runtime_checked else None
        runtime_blocking_reasons = _unique_strings(
            [
                *_as_list(runtime.get("blocking_reasons")),
                *_as_list(runtime.get("blockingReasons")),
                *_as_list(runtime.get("confirm_blocking_reasons")),
            ]
        )
        runtime_source_refs = _unique_strings(_as_list(runtime.get("source_refs")))
        if runtime_checked:
            source_refs.append(
                f"runtime_refresh:{_first_text(runtime, 'state_id', 'runtime_state_id', 'report_id') or runtime_state or 'inline'}"
            )
            source_refs.extend(runtime_source_refs)
            findings.extend(
                self._runtime_findings(
                    runtime,
                    scene_id=scene_id,
                    confirm_allowed=runtime_confirm_allowed,
                    blocking_reasons=runtime_blocking_reasons,
                    round_index=round_index,
                    suppress_quality_continuity_runtime_blocker=has_quality_or_continuity_release_blocker,
                )
            )

        abcd_checked = bool(abcd)
        abcd_passed = self._bool_from(abcd, "passed") if abcd_checked else None
        if abcd_checked:
            source_refs.append(
                f"abcd_runtime:{_first_text(abcd, 'quality_runtime_report_id', 'audit_id', 'report_id') or 'inline'}"
            )
            findings.extend(
                self._abcd_findings(
                    abcd,
                    scene_id=scene_id,
                    round_index=round_index,
                    defer_draft_runtime_confirmation=has_quality_or_continuity_release_blocker,
                )
            )

        composite_checked = bool(composite)
        composite_current_scene_match = (
            self._composite_current_scene_match(composite, scene_id=scene_id)
            if composite_checked
            else None
        )
        if composite_checked:
            source_refs.append(
                f"composite_runtime:{_first_text(composite, 'run_id', 'graph_run_id', 'report_id') or 'inline'}"
            )
            findings.extend(
                self._composite_findings(
                    composite,
                    scene_id=scene_id,
                    current_scene_match=composite_current_scene_match,
                    round_index=round_index,
                    defer_draft_runtime_blockers=has_quality_or_continuity_release_blocker,
                )
            )

        writer_bridge = WriterGateFindingBridgeService()
        findings.extend(
            writer_bridge.build_findings(
                scene_id=scene_id,
                round_index=round_index,
                writer_quality_bundle=writer_quality_bundle,
                writer_self_revision_report=writer_self_revision_report,
                writer_self_revision_result=writer_self_revision_result,
                writer_candidate_draft=writer_candidate_draft,
            )
        )
        source_refs.extend(
            writer_bridge.source_refs(
                writer_quality_bundle=writer_quality_bundle,
                writer_self_revision_report=writer_self_revision_report,
                writer_self_revision_result=writer_self_revision_result,
                writer_candidate_draft=writer_candidate_draft,
            )
        )

        findings = self._dedupe_findings(findings)
        blocking_finding_ids = [
            finding.finding_id
            for finding in findings
            if finding.blocks_final_output or finding.severity == "blocking"
        ]
        confirmation_required_finding_ids = [
            finding.finding_id
            for finding in findings
            if finding.requires_user_confirmation
            or finding.severity == "requires_user_confirmation"
        ]
        has_degraded_finding = any(finding.severity == "degraded" for finding in findings)
        has_blocking_finding = any(
            finding.blocks_final_output or finding.severity == "blocking"
            for finding in findings
        )
        safe_to_show_user = not (
            provider_degraded
            or has_degraded_finding
            or bool(blocking_finding_ids)
            or bool(confirmation_required_finding_ids)
            or not continuity_checked
            or runtime_confirm_allowed is False
            or bool(runtime_blocking_reasons)
            or abcd_passed is False
            or composite_current_scene_match is False
            or has_blocking_finding
        )
        runtime_blocks_auto_repair = self._runtime_blocks_auto_repair(
            runtime_confirm_allowed=runtime_confirm_allowed,
            runtime_blocking_reasons=runtime_blocking_reasons,
            suppress_quality_continuity_runtime_blocker=has_quality_or_continuity_release_blocker,
        )
        safe_for_auto_repair_loop = (
            not provider_degraded
            and continuity_checked
            and runtime_checked
            and not runtime_blocks_auto_repair
            and not any(finding.blocks_auto_repair for finding in findings)
            and not confirmation_required_finding_ids
            and composite_current_scene_match is not False
        )

        gate_run_id = self._gate_run_id(
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            candidate_id=candidate_id,
            revision_id=revision_id,
            round_index=round_index,
            findings=findings,
        )
        return GateRunReport(
            schema_version=SCENE_GATE_REPAIR_SCHEMA_VERSION,
            gate_run_id=gate_run_id,
            project_id=project_id,
            chapter_id=chapter_id,
            scene_id=scene_id,
            candidate_id=candidate_id,
            revision_id=revision_id,
            round_index=round_index,
            generated_at=_now_iso(),
            quality_checked=quality_checked,
            quality_gate_run_id=quality_gate_run_id,
            quality_checked_at=quality_checked_at,
            quality_passed=quality_passed,
            continuity_checked=continuity_checked,
            continuity_gate_run_id=continuity_gate_run_id,
            continuity_checked_at=continuity_checked_at,
            continuity_passed=continuity_passed,
            runtime_refresh_checked=runtime_checked,
            runtime_refresh_state=runtime_state,
            runtime_confirm_allowed=runtime_confirm_allowed,
            runtime_blocking_reasons=runtime_blocking_reasons,
            abcd_runtime_checked=abcd_checked,
            abcd_runtime_passed=abcd_passed,
            composite_runtime_checked=composite_checked,
            composite_current_scene_match=composite_current_scene_match,
            provider_degraded=provider_degraded,
            degraded_check_ids=degraded_check_ids,
            findings=findings,
            blocking_finding_ids=blocking_finding_ids,
            confirmation_required_finding_ids=confirmation_required_finding_ids,
            safe_for_auto_repair_loop=safe_for_auto_repair_loop,
            safe_to_show_user=safe_to_show_user,
            source_refs=source_refs,
        )

    def _quality_findings(
        self,
        quality: dict[str, Any],
        *,
        scene_id: str,
        round_index: int,
    ) -> list[GateFinding]:
        findings: list[GateFinding] = []
        source_check_id = _first_text(quality, "quality_report_id", "quality_gate_run_id", "check_id")
        for issue in _as_list(quality.get("blocking_issues")):
            issue_data = _as_dict(issue)
            category = _first_text(issue_data, "category") or str(issue or "").strip() or "quality_blocking_issue"
            findings.append(
                self._finding_from_issue(
                    issue_data,
                    gate_type="quality",
                    category=category,
                    severity="blocking",
                    source_check_id=source_check_id,
                    scene_id=scene_id,
                    root_cause_layer="quality",
                    blocks_final_output=True,
                    round_index=round_index,
                )
            )
        for issue in _as_list(quality.get("warnings")):
            issue_data = _as_dict(issue)
            severity = _first_text(issue_data, "severity") or "warning"
            category = _first_text(issue_data, "category") or str(issue or "").strip() or "quality_warning"
            findings.append(
                self._finding_from_issue(
                    issue_data,
                    gate_type="quality",
                    category=category,
                    severity=severity if severity != "blocking" else "warning",
                    source_check_id=source_check_id,
                    scene_id=scene_id,
                    root_cause_layer="quality",
                    blocks_final_output=False,
                    round_index=round_index,
                )
            )
        if bool(quality.get("requires_user_confirmation")) and self._quality_requires_user_confirmation_finding_needed(
            quality
        ):
            findings.append(
                self._finding(
                    gate_type="quality",
                    category="quality_requires_user_confirmation",
                    severity="requires_user_confirmation",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="quality",
                    source_check_id=source_check_id,
                    source_issue_id="quality_requires_user_confirmation",
                    affected_fields=["quality_report.requires_user_confirmation"],
                    evidence_refs=[f"quality:{source_check_id}"] if source_check_id else [],
                    safe_source_excerpt=_first_text(quality, "confirmation_block_reason", "summary")
                    or "Quality report requires user confirmation.",
                    suggested_repair_types=["request_user_confirmation"],
                    blocks_auto_repair=True,
                    blocks_final_output=False,
                    requires_user_confirmation=True,
                    round_index=round_index,
                )
            )
        return findings

    def _continuity_findings(
        self,
        continuity: dict[str, Any],
        *,
        scene_id: str,
        round_index: int,
    ) -> list[GateFinding]:
        findings: list[GateFinding] = []
        source_check_id = _first_text(
            continuity,
            "continuity_gate_run_id",
            "gate_run_id",
            "check_id",
            "continuity_check_id",
        )
        for issue in _as_list(continuity.get("issues")):
            issue_data = _as_dict(issue)
            raw_category = _first_text(issue_data, "category") or "continuity_issue"
            category = self._normalized_continuity_category(raw_category, issue_data)
            raw_severity = _first_text(issue_data, "severity") or "warning"
            machine_repairable = str(category or "").casefold() in MACHINE_REPAIRABLE_CATEGORIES
            severity = raw_severity
            if machine_repairable and raw_severity == "requires_user_confirmation":
                severity = "blocking" if bool(issue_data.get("blocks_final_confirmation")) else "warning"
            blocks_final = bool(issue_data.get("blocks_final_confirmation")) or severity == "blocking"
            findings.append(
                self._finding_from_issue(
                    issue_data,
                    gate_type="continuity",
                    category=category,
                    severity=severity,
                    source_check_id=source_check_id,
                    scene_id=scene_id,
                    root_cause_layer="continuity",
                    blocks_final_output=blocks_final,
                    round_index=round_index,
                    requires_user_confirmation=False
                    if machine_repairable
                    else (
                        bool(issue_data.get("requires_explicit_acceptance"))
                        or severity == "requires_user_confirmation"
                    ),
                )
            )
        known_issue_ids = {finding.source_issue_id for finding in findings if finding.source_issue_id}
        for issue_id in _as_list(continuity.get("blocking_issue_ids")):
            text = str(issue_id or "").strip()
            if not text or text in known_issue_ids:
                continue
            findings.append(
                self._finding(
                    gate_type="continuity",
                    category="continuity_blocking_issue",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="continuity",
                    source_check_id=source_check_id,
                    source_issue_id=text,
                    affected_fields=["continuity.blocking_issue_ids"],
                    evidence_refs=[f"continuity_issue:{text}"],
                    safe_source_excerpt=f"Continuity gate reports blocking issue {text}.",
                    suggested_repair_types=["review_continuity_issue"],
                    blocks_auto_repair=True,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        for issue_id in _as_list(continuity.get("warning_issue_ids")):
            text = str(issue_id or "").strip()
            if not text or text in known_issue_ids:
                continue
            findings.append(
                self._finding(
                    gate_type="continuity",
                    category="continuity_warning_issue",
                    severity="warning",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="continuity",
                    source_check_id=source_check_id,
                    source_issue_id=text,
                    affected_fields=["continuity.warning_issue_ids"],
                    evidence_refs=[f"continuity_issue:{text}"],
                    safe_source_excerpt=f"Continuity gate reports warning issue {text}.",
                    suggested_repair_types=["review_continuity_issue"],
                    blocks_auto_repair=False,
                    blocks_final_output=False,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        return findings

    def _normalized_continuity_category(
        self,
        category: str,
        issue_data: dict[str, Any],
    ) -> str:
        normalized = str(category or "").strip()
        technical_summary = _first_text(issue_data, "technical_summary", "technical")
        if (
            normalized.casefold() == "forbidden_knowledge"
            and "ordered_story_information_package.do_not_include"
            in technical_summary
        ):
            return "do_not_include_violation"
        return normalized

    def _provider_findings(
        self,
        *,
        quality: dict[str, Any],
        provider: dict[str, Any],
        scene_id: str,
        round_index: int,
    ) -> list[GateFinding]:
        degraded = bool(quality.get("quality_degraded"))
        status = _first_text(provider, "status", "health", "last_call_status")
        safe_error_code = _first_text(provider, "safe_error_code", "last_safe_error_code")
        if status and status not in {"passed", "healthy", "ok", "success"}:
            degraded = True
        if int(provider.get("recent_failures") or 0) > 0:
            degraded = True
        if safe_error_code:
            degraded = True
        if not degraded:
            return []
        source_check_id = (
            _first_text(provider, "check_id", "runtime_call_id", "call_id")
            or _first_text(quality, "quality_report_id")
            or "provider_status"
        )
        return [
            self._finding(
                gate_type="provider",
                category="provider_degraded",
                severity="degraded",
                target_type="scene",
                target_id=scene_id,
                root_cause_layer="provider",
                source_check_id=source_check_id,
                source_issue_id=safe_error_code or "provider_degraded",
                affected_fields=["model_provider", "quality_report.quality_degraded"],
                evidence_refs=[f"provider:{source_check_id}"],
                safe_source_excerpt=(
                    _first_text(quality, "confirmation_block_reason", "summary")
                    or safe_error_code
                    or "Provider/runtime health is degraded."
                ),
                suggested_repair_types=["retry_after_provider_recovers"],
                blocks_auto_repair=True,
                blocks_final_output=True,
                requires_user_confirmation=False,
                round_index=round_index,
            )
        ]

    def _runtime_findings(
        self,
        runtime: dict[str, Any],
        *,
        scene_id: str,
        confirm_allowed: bool | None,
        blocking_reasons: list[str],
        round_index: int,
        suppress_quality_continuity_runtime_blocker: bool = False,
    ) -> list[GateFinding]:
        state = _first_text(runtime, "runtime_refresh_state", "state", "status")
        if confirm_allowed is True and not blocking_reasons and state not in {"blocked", "degraded", "stale"}:
            return []
        reasons = blocking_reasons or ([state] if state else ["runtime_refresh_not_confirmable"])
        if suppress_quality_continuity_runtime_blocker:
            return []
        findings: list[GateFinding] = []
        for index, reason in enumerate(reasons, start=1):
            category = _normalize_category(reason) or "runtime_refresh_not_confirmable"
            findings.append(
                self._finding(
                    gate_type="runtime_refresh",
                    category=category,
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="runtime_refresh",
                    source_check_id=_first_text(runtime, "state_id", "runtime_state_id", "report_id"),
                    source_issue_id=f"runtime_refresh_{index}",
                    affected_fields=["runtime_confirm_allowed"],
                    evidence_refs=[f"runtime_refresh:{state or 'unknown'}"],
                    safe_source_excerpt=reason,
                    suggested_repair_types=["refresh_runtime_state"],
                    blocks_auto_repair=True,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        return findings

    def _abcd_findings(
        self,
        abcd: dict[str, Any],
        *,
        scene_id: str,
        round_index: int,
        defer_draft_runtime_confirmation: bool = False,
    ) -> list[GateFinding]:
        findings: list[GateFinding] = []
        source_check_id = _first_text(abcd, "quality_runtime_report_id", "audit_id", "report_id")
        for issue_id in _as_list(abcd.get("blocking_issue_ids")):
            text = str(issue_id or "").strip()
            if not text:
                continue
            findings.append(
                self._finding(
                    gate_type="abcd_runtime",
                    category="abcd_runtime_blocking_issue",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="abcd_runtime",
                    source_check_id=source_check_id,
                    source_issue_id=text,
                    affected_fields=["abcd_runtime.blocking_issue_ids"],
                    evidence_refs=[f"abcd_runtime_issue:{text}"],
                    safe_source_excerpt=f"ABCD runtime gate reports blocking issue {text}.",
                    suggested_repair_types=["review_abcd_runtime_issue"],
                    blocks_auto_repair=not defer_draft_runtime_confirmation,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        for violation in _as_list(abcd.get("violations")):
            text = str(violation or "").strip()
            if not text:
                continue
            findings.append(
                self._finding(
                    gate_type="abcd_runtime",
                    category="abcd_runtime_policy_violation",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="abcd_runtime",
                    source_check_id=source_check_id,
                    source_issue_id=_short_hash(text),
                    affected_fields=["abcd_runtime.violations"],
                    evidence_refs=[f"abcd_runtime_violation:{_short_hash(text)}"],
                    safe_source_excerpt=text,
                    suggested_repair_types=["review_abcd_runtime_issue"],
                    blocks_auto_repair=True,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        for issue_id in _as_list(abcd.get("requires_user_confirmation_issue_ids")):
            text = str(issue_id or "").strip()
            if not text:
                continue
            findings.append(
                self._finding(
                    gate_type="abcd_runtime",
                    category="abcd_runtime_requires_user_confirmation",
                    severity=(
                        "warning"
                        if defer_draft_runtime_confirmation
                        else "requires_user_confirmation"
                    ),
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="abcd_runtime",
                    source_check_id=source_check_id,
                    source_issue_id=text,
                    affected_fields=["abcd_runtime.requires_user_confirmation_issue_ids"],
                    evidence_refs=[f"abcd_runtime_issue:{text}"],
                    safe_source_excerpt=f"ABCD runtime issue {text} requires user confirmation.",
                    suggested_repair_types=[
                        "revise_current_scene"
                        if defer_draft_runtime_confirmation
                        else "request_user_confirmation"
                    ],
                    blocks_auto_repair=False if defer_draft_runtime_confirmation else True,
                    blocks_final_output=bool(defer_draft_runtime_confirmation),
                    requires_user_confirmation=False if defer_draft_runtime_confirmation else True,
                    round_index=round_index,
                )
            )
        if self._bool_from(abcd, "passed") is False and not findings:
            findings.append(
                self._finding(
                    gate_type="abcd_runtime",
                    category="abcd_runtime_failed",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="abcd_runtime",
                    source_check_id=source_check_id,
                    source_issue_id="abcd_runtime_failed",
                    affected_fields=["abcd_runtime.passed"],
                    evidence_refs=[f"abcd_runtime:{source_check_id or 'inline'}"],
                    safe_source_excerpt=_first_text(abcd, "safe_summary") or "ABCD runtime gate failed.",
                    suggested_repair_types=["revise_current_scene"],
                    blocks_auto_repair=not defer_draft_runtime_confirmation,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        return findings

    def _composite_findings(
        self,
        composite: dict[str, Any],
        *,
        scene_id: str,
        current_scene_match: bool | None,
        round_index: int,
        defer_draft_runtime_blockers: bool = False,
    ) -> list[GateFinding]:
        findings: list[GateFinding] = []
        source_check_id = _first_text(composite, "run_id", "graph_run_id", "report_id")
        final_decision = _first_text(composite, "final_decision", "overall_decision", "status")
        if current_scene_match is False:
            findings.append(
                self._finding(
                    gate_type="composite_runtime",
                    category="composite_current_scene_mismatch",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="composite_runtime",
                    source_check_id=source_check_id,
                    source_issue_id="composite_current_scene_mismatch",
                    affected_fields=["composite_current_scene_match"],
                    evidence_refs=[f"composite_runtime:{source_check_id or 'inline'}"],
                    safe_source_excerpt="Composite runtime evidence does not match the current scene.",
                    suggested_repair_types=["refresh_composite_runtime"],
                    blocks_auto_repair=True,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        if final_decision in {"blocked", "failed", "fail"}:
            findings.append(
                self._finding(
                    gate_type="composite_runtime",
                    category="composite_runtime_blocked",
                    severity="blocking",
                    target_type="scene",
                    target_id=scene_id,
                    root_cause_layer="composite_runtime",
                    source_check_id=source_check_id,
                    source_issue_id="composite_runtime_blocked",
                    affected_fields=["composite_runtime.final_decision"],
                    evidence_refs=[f"composite_runtime:{source_check_id or 'inline'}"],
                    safe_source_excerpt=f"Composite runtime final decision is {final_decision}.",
                    suggested_repair_types=[
                        "revise_current_scene"
                        if defer_draft_runtime_blockers
                        else "review_composite_runtime"
                    ],
                    blocks_auto_repair=not defer_draft_runtime_blockers,
                    blocks_final_output=True,
                    requires_user_confirmation=False,
                    round_index=round_index,
                )
            )
        for finding in _as_list(composite.get("blocking_findings")):
            finding_data = _as_dict(finding)
            category = _first_text(finding_data, "category", "finding_code") or "composite_runtime_blocking_finding"
            findings.append(
                self._finding_from_issue(
                    finding_data,
                    gate_type="composite_runtime",
                    category=category,
                    severity="blocking",
                    source_check_id=source_check_id,
                    scene_id=scene_id,
                    root_cause_layer="composite_runtime",
                    blocks_final_output=True,
                    round_index=round_index,
                    blocks_auto_repair_override=not defer_draft_runtime_blockers,
                )
            )
        return findings

    def _finding_from_issue(
        self,
        issue_data: dict[str, Any],
        *,
        gate_type: str,
        category: str,
        severity: str,
        source_check_id: str,
        scene_id: str,
        root_cause_layer: str,
        blocks_final_output: bool,
        round_index: int,
        requires_user_confirmation: bool | None = None,
        blocks_auto_repair_override: bool | None = None,
    ) -> GateFinding:
        source_issue_id = _first_text(
            issue_data,
            "issue_id",
            "runtime_issue_id",
            "finding_id",
            "finding_code",
            "id",
        )
        target_type = _first_text(issue_data, "related_object_type", "target_type") or "scene"
        target_id = (
            _first_text(issue_data, "related_object_id", "target_id", "scene_id")
            or scene_id
        )
        evidence_refs = [
            *_as_list(issue_data.get("source_memory_ids")),
            *_as_list(issue_data.get("source_event_ids")),
            *_as_list(issue_data.get("source_scene_ids")),
            *_as_list(issue_data.get("source_character_ids")),
            *_as_list(issue_data.get("source_relationship_ids")),
            *_as_list(issue_data.get("source_refs")),
        ]
        technical_metadata = _as_dict(issue_data.get("technical_metadata"))
        pattern_report_id = _first_text(
            technical_metadata,
            "scene_pattern_similarity_report_id",
            "report_id",
        )
        current_signature_id = _first_text(
            technical_metadata,
            "current_signature_id",
            "scene_pattern_signature_id",
        )
        if pattern_report_id:
            evidence_refs.append(f"scene_pattern_report:{pattern_report_id}")
        if current_signature_id:
            evidence_refs.append(f"scene_pattern_signature:{current_signature_id}")
        evidence_refs.extend(
            f"scene_pattern_compared_signature:{signature_id}"
            for signature_id in _as_list(technical_metadata.get("compared_signature_ids"))
            if str(signature_id or "").strip()
        )
        evidence_refs.extend(
            f"scene_pattern_source_scene:{scene_id_value}"
            for scene_id_value in _as_list(technical_metadata.get("source_scene_ids"))
            if str(scene_id_value or "").strip()
        )
        for score_key in ("structural_similarity_score", "text_similarity_score"):
            if score_key in technical_metadata:
                evidence_refs.append(f"{score_key}:{technical_metadata.get(score_key)}")
        if source_issue_id:
            evidence_refs.append(f"{gate_type}_issue:{source_issue_id}")
        user_confirmation = (
            bool(requires_user_confirmation)
            if requires_user_confirmation is not None
            else severity == "requires_user_confirmation"
        )
        return self._finding(
            gate_type=gate_type,
            category=category,
            severity=severity,
            target_type=target_type,
            target_id=target_id,
            root_cause_layer=root_cause_layer,
            source_check_id=source_check_id,
            source_issue_id=source_issue_id,
            affected_fields=_as_list(issue_data.get("affected_fields"))
            or [_first_text(issue_data, "category") or category],
            evidence_refs=evidence_refs,
            safe_source_excerpt=_first_text(
                issue_data,
                "technical_summary",
                "message",
                "user_visible_message",
                "evidence_text",
                "evidence",
                "safe_summary",
            ),
            suggested_repair_types=_as_list(issue_data.get("suggested_repair_types"))
            or _as_list(issue_data.get("suggested_repair_focus"))
            or _as_list(issue_data.get("suggested_options"))
            or _as_list(technical_metadata.get("suggested_repair_focus"))
            or ["review_gate_finding"],
            blocks_auto_repair=(
                bool(blocks_auto_repair_override)
                if blocks_auto_repair_override is not None
                else self._issue_blocks_auto_repair(
                    gate_type=gate_type,
                    category=category,
                    severity=severity,
                    affected_fields=_as_list(issue_data.get("affected_fields"))
                    or [_first_text(issue_data, "category") or category],
                    suggested_repair_types=_as_list(issue_data.get("suggested_repair_types"))
                    or _as_list(issue_data.get("suggested_repair_focus"))
                    or _as_list(issue_data.get("suggested_options"))
                    or _as_list(technical_metadata.get("suggested_repair_focus"))
                    or ["review_gate_finding"],
                    requires_user_confirmation=user_confirmation,
                )
            ),
            blocks_final_output=blocks_final_output,
            requires_user_confirmation=user_confirmation,
            round_index=round_index,
        )

    def _issue_blocks_auto_repair(
        self,
        *,
        gate_type: str,
        category: str,
        severity: str,
        affected_fields: list[str],
        suggested_repair_types: list[str],
        requires_user_confirmation: bool,
    ) -> bool:
        normalized_category = str(category or "").casefold()
        normalized_gate_type = str(gate_type or "").casefold()
        normalized_fields = {str(field or "").casefold() for field in affected_fields}
        normalized_suggested = {str(item or "").casefold() for item in suggested_repair_types}
        if requires_user_confirmation or severity == "requires_user_confirmation":
            return True
        if normalized_category in USER_CONFIRMATION_CATEGORIES:
            return True
        if normalized_category in EXPERT_OR_RUNTIME_BLOCK_CATEGORIES:
            return True
        if normalized_fields & USER_CONFIRMATION_FIELDS:
            return True
        if normalized_suggested & USER_CONFIRMATION_REPAIR_TYPES:
            return True
        if normalized_gate_type in {"provider", "runtime_refresh", "composite_runtime", "abcd_runtime"}:
            return True
        if normalized_category in MACHINE_REPAIRABLE_CATEGORIES:
            return False
        return severity == "blocking"

    def _quality_requires_user_confirmation_finding_needed(
        self,
        quality: dict[str, Any],
    ) -> bool:
        issues = [
            _as_dict(issue)
            for issue in [
                *_as_list(quality.get("blocking_issues")),
                *_as_list(quality.get("warnings")),
            ]
        ]
        if not issues:
            return True
        for issue in issues:
            category = _first_text(issue, "category").casefold()
            severity = _first_text(issue, "severity").casefold()
            affected_fields = {
                str(field or "").casefold()
                for field in _as_list(issue.get("affected_fields"))
            }
            suggested_repair_types = {
                str(item or "").casefold()
                for item in _as_list(issue.get("suggested_repair_types"))
                or _as_list(issue.get("suggested_repair_focus"))
                or _as_list(issue.get("suggested_options"))
            }
            if category in USER_CONFIRMATION_CATEGORIES:
                return True
            if category in EXPERT_OR_RUNTIME_BLOCK_CATEGORIES:
                return True
            if affected_fields & USER_CONFIRMATION_FIELDS:
                return True
            if category not in MACHINE_REPAIRABLE_CATEGORIES and severity in {
                "blocking",
                "requires_user_confirmation",
            }:
                return True
            if suggested_repair_types and not (
                suggested_repair_types & USER_CONFIRMATION_REPAIR_TYPES
            ):
                continue
        return False

    def _runtime_blocks_auto_repair(
        self,
        *,
        runtime_confirm_allowed: bool | None,
        runtime_blocking_reasons: list[str],
        suppress_quality_continuity_runtime_blocker: bool = False,
    ) -> bool:
        if runtime_confirm_allowed is True:
            return False
        if suppress_quality_continuity_runtime_blocker:
            return False
        normalized = {
            str(reason or "").strip().casefold()
            for reason in runtime_blocking_reasons
            if str(reason or "").strip()
        }
        if not normalized:
            return runtime_confirm_allowed is False
        return not normalized.issubset(AUTO_REPAIR_ALLOWED_RUNTIME_BLOCKING_REASONS)

    def _finding(
        self,
        *,
        gate_type: str,
        category: str,
        severity: str,
        target_type: str,
        target_id: str,
        root_cause_layer: str,
        source_check_id: str,
        source_issue_id: str,
        affected_fields: list[str],
        evidence_refs: list[str],
        safe_source_excerpt: str,
        suggested_repair_types: list[str],
        blocks_auto_repair: bool,
        blocks_final_output: bool,
        requires_user_confirmation: bool,
        round_index: int,
    ) -> GateFinding:
        signature_payload = {
            "gate_type": gate_type,
            "source_check_id": source_check_id,
            "source_issue_id": source_issue_id,
            "category": category,
            "severity": severity,
            "target_type": target_type,
            "target_id": target_id,
            "affected_fields": _unique_strings(affected_fields),
            "evidence_refs": _unique_strings(evidence_refs),
        }
        signature = _short_hash(signature_payload, length=24)
        return GateFinding(
            finding_id=f"gate_finding_{signature[:16]}",
            finding_signature=signature,
            gate_type=gate_type,
            source_check_id=source_check_id,
            source_issue_id=source_issue_id,
            category=category,
            severity=severity,
            status="open",
            target_type=target_type or "scene",
            target_id=target_id,
            root_cause_layer=root_cause_layer,
            affected_fields=affected_fields,
            evidence_refs=evidence_refs,
            safe_source_excerpt=_safe_excerpt(safe_source_excerpt),
            suggested_repair_types=suggested_repair_types,
            blocks_auto_repair=blocks_auto_repair,
            blocks_final_output=blocks_final_output,
            requires_user_confirmation=requires_user_confirmation,
            first_seen_round=round_index,
            last_seen_round=round_index,
            repair_attempt_count=0,
        )

    def _dedupe_findings(self, findings: list[GateFinding]) -> list[GateFinding]:
        result: list[GateFinding] = []
        seen: set[str] = set()
        for finding in findings:
            if finding.finding_signature in seen:
                continue
            seen.add(finding.finding_signature)
            result.append(finding)
        return result

    def _gate_run_id(
        self,
        *,
        project_id: str,
        chapter_id: str,
        scene_id: str,
        candidate_id: str,
        revision_id: str,
        round_index: int,
        findings: list[GateFinding],
    ) -> str:
        digest = _short_hash(
            {
                "project_id": project_id,
                "chapter_id": chapter_id,
                "scene_id": scene_id,
                "candidate_id": candidate_id,
                "revision_id": revision_id,
                "round_index": round_index,
                "finding_signatures": [finding.finding_signature for finding in findings],
            },
            length=16,
        )
        return f"gate_run_{scene_id or 'scene'}_{round_index}_{digest}"

    def _has_explicit_continuity_evidence(self, continuity: dict[str, Any]) -> bool:
        if not continuity:
            return False
        return (
            continuity.get("continuity_checked") is True
            and _has_non_empty_value(continuity.get("continuity_gate_run_id"))
            and _has_non_empty_value(continuity.get("continuity_checked_at"))
        )

    def _runtime_confirm_allowed(self, runtime: dict[str, Any]) -> bool | None:
        for key in ["runtime_confirm_allowed", "confirm_allowed", "can_confirm", "confirm_enabled"]:
            if key in runtime:
                return bool(runtime.get(key))
        return None

    def _composite_current_scene_match(
        self,
        composite: dict[str, Any],
        *,
        scene_id: str,
    ) -> bool | None:
        for key in ["composite_current_scene_match", "current_scene_match"]:
            if key in composite:
                return bool(composite.get(key))
        summary = _as_dict(composite.get("composite_runtime_summary"))
        for key in ["composite_current_scene_match", "current_scene_match"]:
            if key in summary:
                return bool(summary.get(key))
        source_scene_id = _first_text(composite, "scene_id", "target_scene_id")
        candidate_output = _as_dict(composite.get("candidate_scene_output"))
        source_scene_id = source_scene_id or _first_text(candidate_output, "scene_id", "target_scene_id")
        if source_scene_id and scene_id:
            return source_scene_id == scene_id
        return None

    def _bool_from(self, payload: dict[str, Any], key: str) -> bool | None:
        if key not in payload:
            return None
        return bool(payload.get(key))


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()
    if isinstance(value, BaseModel):
        return value.dict()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _unique_strings(values: list[Any]) -> list[str]:
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
    return result


def _has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _normalize_category(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80]


def _safe_excerpt(value: str) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    for pattern in UNSAFE_EXCERPT_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:400]


def _short_hash(value: Any, *, length: int = 16) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()
