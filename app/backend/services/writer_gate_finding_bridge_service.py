from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel

from app.backend.models.scene_gate_repair import GateFinding


WRITER_GATE_REPAIRABLE_CATEGORIES = {
    "plot_turn_missing",
    "visible_action_missing",
    "dialogue_or_decision_missing",
    "ending_pull_missing",
    "empty_mystery_too_high",
    "abstract_language_too_high",
    "abstract_language_density_high",
    "adjective_density_too_high",
    "adjective_density_high",
    "prose_too_literary_for_profile",
    "plain_language_profile_failed",
    "scene_reader_value_missing",
    "opening_hook_too_abstract",
    "ending_pull_too_abstract",
    "reader_question_not_advanced",
    "hook_payoff_missing",
    "psychology_overexposed",
    "interior_monologue_not_earned",
    "action_replaced_by_explanation",
    "subtext_should_be_behavior",
    "suspense_overexplained",
    "minor_role_over_interiorized",
    "character_depth_flattened_by_exposition",
    "subtext_balance_failed",
    "negative_space_leaked",
    "forbidden_psychology_channel_used",
    "placeholder_or_instruction_text_leak",
}
WRITER_GATE_HARD_LEAK_CATEGORIES = {
    "raw_psychology_chain_leak",
    "hidden_reasoning_leak",
    "provider_raw_leak",
    "internal_json_leak",
    "diagnostic_text_leak",
}
WRITER_GATE_ISSUE_CATEGORIES = (
    WRITER_GATE_REPAIRABLE_CATEGORIES | WRITER_GATE_HARD_LEAK_CATEGORIES
)

SAFE_EXCERPT_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{3,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]+"),
    re.compile(
        r"\b(raw[_ -]?prompt|raw[_ -]?response|provider[_ -]?raw|hidden[_ -]?reasoning|"
        r"chain[-_ ]of[-_ ]thought|raw[_ -]?psychology[_ -]?chain|traceback)\b",
        re.I,
    ),
]


class WriterGateFindingBridgeService:
    """Map Phase 8.5-E writer quality evidence into sanitized GateFinding objects."""

    def build_findings(
        self,
        *,
        scene_id: str = "",
        round_index: int = 0,
        writer_quality_bundle: Any | None = None,
        writer_self_revision_report: Any | None = None,
        writer_self_revision_result: Any | None = None,
        writer_candidate_draft: Any | None = None,
    ) -> list[GateFinding]:
        evidence_items = self._collect_evidence_items(
            writer_quality_bundle=writer_quality_bundle,
            writer_self_revision_report=writer_self_revision_report,
            writer_self_revision_result=writer_self_revision_result,
            writer_candidate_draft=writer_candidate_draft,
        )
        findings: list[GateFinding] = []
        seen: set[str] = set()
        for item in evidence_items:
            for category in item["issue_codes"]:
                if category not in WRITER_GATE_ISSUE_CATEGORIES:
                    continue
                finding = self._finding_for_issue(
                    category=category,
                    source_check_id=item["source_check_id"],
                    source_issue_id=f"{item['source_kind']}:{category}",
                    source_refs=item["source_refs"],
                    scene_id=scene_id or item.get("scene_id", ""),
                    ready_for_downstream_gates=item["ready_for_downstream_gates"],
                    eligible_for_commit=item["eligible_for_commit"],
                    explicitly_blocking=category in item["blocking_issue_codes"],
                    round_index=round_index,
                )
                if finding.finding_signature in seen:
                    continue
                seen.add(finding.finding_signature)
                findings.append(finding)
        return findings

    def source_refs(
        self,
        *,
        writer_quality_bundle: Any | None = None,
        writer_self_revision_report: Any | None = None,
        writer_self_revision_result: Any | None = None,
        writer_candidate_draft: Any | None = None,
    ) -> list[str]:
        refs: list[str] = []
        for item in self._collect_evidence_items(
            writer_quality_bundle=writer_quality_bundle,
            writer_self_revision_report=writer_self_revision_report,
            writer_self_revision_result=writer_self_revision_result,
            writer_candidate_draft=writer_candidate_draft,
        ):
            refs.extend(item["source_refs"])
        return _unique_strings(refs)

    def _collect_evidence_items(
        self,
        *,
        writer_quality_bundle: Any | None,
        writer_self_revision_report: Any | None,
        writer_self_revision_result: Any | None,
        writer_candidate_draft: Any | None,
    ) -> list[dict[str, Any]]:
        result_payload = _as_dict(writer_self_revision_result)
        explicit_bundle = _as_dict(writer_quality_bundle)
        explicit_report = _as_dict(writer_self_revision_report)
        explicit_candidate = _as_dict(writer_candidate_draft)

        bundles = [
            explicit_bundle,
            _as_dict(result_payload.get("initial_inspection_bundle")),
            _as_dict(result_payload.get("final_inspection_bundle")),
        ]
        reports = [
            explicit_report,
            _as_dict(result_payload.get("revision_report")),
        ]
        candidates = [
            explicit_candidate,
            _as_dict(result_payload.get("revised_draft_package")),
        ]

        items: list[dict[str, Any]] = []
        for bundle in bundles:
            if bundle:
                items.append(self._bundle_item(bundle))
        for report in reports:
            if report:
                items.append(self._revision_report_item(report))
        for candidate in candidates:
            if candidate:
                items.append(self._candidate_item(candidate))
        return [item for item in items if item["issue_codes"]]

    def _bundle_item(self, bundle: dict[str, Any]) -> dict[str, Any]:
        source_id = _first_text(
            bundle,
            "inspection_bundle_id",
            "writer_quality_inspection_bundle_id",
            "source_draft_package_id",
        )
        issue_codes = _unique_strings(
            [
                *_as_list(bundle.get("issue_codes")),
                *_as_list(bundle.get("repairable_issue_codes")),
                *_as_list(bundle.get("blocking_issue_codes")),
            ]
        )
        blocking_codes = set(_unique_strings(_as_list(bundle.get("blocking_issue_codes"))))
        return {
            "source_kind": "writer_quality",
            "source_check_id": source_id,
            "source_refs": [f"writer_quality:{source_id}"] if source_id else [],
            "scene_id": _first_text(bundle, "scene_id", "target_scene_id"),
            "issue_codes": issue_codes,
            "blocking_issue_codes": blocking_codes,
            "ready_for_downstream_gates": _bool_value(bundle, "ready_for_downstream_gates"),
            "eligible_for_commit": None,
        }

    def _revision_report_item(self, report: dict[str, Any]) -> dict[str, Any]:
        source_id = _first_text(
            report,
            "writer_self_revision_report_id",
            "revision_report_id",
            "source_draft_package_id",
        )
        final_codes = _as_list(report.get("final_issue_codes"))
        blocking_codes = set(_unique_strings(_as_list(report.get("blocking_issue_codes"))))
        ready = _bool_value(report, "ready_for_downstream_gates")
        if ready is None and bool(report.get("blocking_issue_remains")):
            ready = False
        issue_codes = _unique_strings(
            [
                *(final_codes or []),
                *_as_list(report.get("blocking_issue_codes")),
            ]
        )
        if not issue_codes and ready is not True:
            issue_codes = _unique_strings(_as_list(report.get("original_issue_codes")))
        return {
            "source_kind": "writer_self_revision",
            "source_check_id": source_id,
            "source_refs": [f"writer_self_revision:{source_id}"] if source_id else [],
            "scene_id": _first_text(report, "scene_id", "target_scene_id"),
            "issue_codes": issue_codes,
            "blocking_issue_codes": blocking_codes,
            "ready_for_downstream_gates": ready,
            "eligible_for_commit": None,
        }

    def _candidate_item(self, candidate: dict[str, Any]) -> dict[str, Any]:
        source_id = _first_text(
            candidate,
            "writer_candidate_draft_id",
            "candidate_id",
            "source_writer_self_revision_report_id",
        )
        issue_codes = _unique_strings(_as_list(candidate.get("writer_quality_issue_codes")))
        eligible = _bool_value(candidate, "eligible_for_commit_service_review")
        ready = True if eligible is True and not issue_codes else False if eligible is False else None
        return {
            "source_kind": "writer_candidate",
            "source_check_id": source_id,
            "source_refs": [f"writer_candidate:{source_id}"] if source_id else [],
            "scene_id": _first_text(candidate, "scene_id", "target_scene_id"),
            "issue_codes": issue_codes,
            "blocking_issue_codes": set(),
            "ready_for_downstream_gates": ready,
            "eligible_for_commit": eligible,
        }

    def _finding_for_issue(
        self,
        *,
        category: str,
        source_check_id: str,
        source_issue_id: str,
        source_refs: list[str],
        scene_id: str,
        ready_for_downstream_gates: bool | None,
        eligible_for_commit: bool | None,
        explicitly_blocking: bool,
        round_index: int,
    ) -> GateFinding:
        hard_leak = category in WRITER_GATE_HARD_LEAK_CATEGORIES
        ordinary_blocking = (
            ready_for_downstream_gates is False
            or eligible_for_commit is False
            or explicitly_blocking
        )
        severity = "blocking" if hard_leak or ordinary_blocking else "warning"
        suggested = (
            ["stop_for_expert_review", "rewrite_scene_prose_blocked_unsafe"]
            if hard_leak
            else ["rewrite_scene_prose"]
        )
        evidence_refs = _unique_strings(
            [*source_refs, f"writer_issue:{category}", f"writer_gate_category:{category}"]
        )
        excerpt = (
            "Writer candidate contains a redacted unsafe internal/provider leak."
            if hard_leak
            else f"Writer candidate still has writer-quality issue {category}."
        )
        return _gate_finding(
            gate_type="quality",
            category=category,
            severity=severity,
            target_type="scene",
            target_id=scene_id,
            root_cause_layer="writer_prose_output",
            source_check_id=source_check_id,
            source_issue_id=source_issue_id,
            affected_fields=["writer_candidate_draft.candidate_prose"],
            evidence_refs=evidence_refs,
            safe_source_excerpt=excerpt,
            suggested_repair_types=suggested,
            blocks_auto_repair=hard_leak,
            blocks_final_output=severity == "blocking",
            requires_user_confirmation=False,
            round_index=round_index,
        )


def _gate_finding(
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
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return [value]


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _bool_value(payload: dict[str, Any], key: str) -> bool | None:
    if key not in payload:
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes", "1", "passed", "ready"}:
            return True
        if lowered in {"false", "no", "0", "failed", "blocked"}:
            return False
    return bool(value)


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _short_hash(payload: Any, *, length: int = 16) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _safe_excerpt(text: str) -> str:
    value = " ".join(str(text or "").split())
    for pattern in SAFE_EXCERPT_PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value[:400]


__all__ = [
    "WRITER_GATE_HARD_LEAK_CATEGORIES",
    "WRITER_GATE_ISSUE_CATEGORIES",
    "WRITER_GATE_REPAIRABLE_CATEGORIES",
    "WriterGateFindingBridgeService",
]
