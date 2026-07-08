from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.apparent_contradiction import (
    ApparentContradictionClassificationResult,
    ApparentContradictionGateDecision,
    ApparentContradictionGateResult,
)
from app.backend.models.continuity import ContinuityIssue
from app.backend.models.narrative_layer import (
    ApparentContradictionRecord,
    NarrativeDebt,
    NarrativeObjectReference,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.apparent_contradiction_classifier import (
    HARD_BLOCK_CATEGORIES,
    ApparentContradictionClassifier,
)
from app.backend.services.apparent_contradiction_context_builder import (
    ApparentContradictionContextBuilder,
)
from app.backend.services.narrative_layer_service import NarrativeLayerService
from app.backend.storage.json_store import JsonStore


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
TRACKABLE_DEVICE_TYPES = {
    "misdirection",
    "hallucination",
    "psychological_contradiction",
    "delayed_explanation",
    "delayed_reveal",
    "foreshadowing",
    "open_ambiguity",
    "symbolic_unresolved",
    "unreliable_claim",
    "unreliable_perception",
}


class ApparentContradictionGateService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        context_builder: ApparentContradictionContextBuilder | None = None,
        classifier: ApparentContradictionClassifier | None = None,
        narrative_layer_service: NarrativeLayerService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.narrative_layer_service = narrative_layer_service or NarrativeLayerService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.context_builder = context_builder or ApparentContradictionContextBuilder(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            narrative_layer_service=self.narrative_layer_service,
        )
        self.classifier = classifier or ApparentContradictionClassifier()

    def evaluate_issues(
        self,
        *,
        continuity_context: dict[str, Any],
        issues: list[ContinuityIssue],
        mode: str,
    ) -> ApparentContradictionGateResult:
        if not issues:
            return ApparentContradictionGateResult(
                safe_summary="没有新的连续性问题需要表面矛盾门处理。"
            )
        context = self.context_builder.build(
            continuity_context=continuity_context,
            issues=issues,
        )
        classifications = self.classifier.classify(context)
        classification_by_id = {
            item.issue_id: item
            for item in classifications
        }
        apparent_records: list[ApparentContradictionRecord] = []
        gated_issues: list[ContinuityIssue] = []
        decisions: list[ApparentContradictionGateDecision] = []
        created_debt_ids: list[str] = []

        for issue in issues:
            classification = classification_by_id.get(issue.issue_id)
            if classification is None:
                classification = ApparentContradictionClassificationResult(
                    issue_id=issue.issue_id,
                    classification="needs_user_confirmation",
                    quality_gate_action="require_user_confirmation",
                    safe_user_summary="表面矛盾门未能分类该问题，需要用户确认。",
                )
            record = self._upsert_apparent_record(
                context=context,
                issue=issue,
                classification=classification,
            )
            debt = self._ensure_narrative_debt(
                context=context,
                issue=issue,
                classification=classification,
                record=record,
            )
            if debt is not None:
                created_debt_ids.append(debt.narrative_debt_id)
                if debt.narrative_debt_id not in classification.matched_narrative_debt_ids:
                    classification.matched_narrative_debt_ids.append(
                        debt.narrative_debt_id
                    )
                record = self._upsert_apparent_record(
                    context=context,
                    issue=issue,
                    classification=classification,
                )
            apparent_records.append(record)
            gated_issue = self._apply_gate_decision(
                issue=issue,
                classification=classification,
                apparent_record=record,
                mode=mode,
            )
            gated_issues.append(gated_issue)
            decisions.append(self._decision_for_issue(gated_issue))

        return ApparentContradictionGateResult(
            apparent_records=apparent_records,
            issues_to_block=[
                issue.issue_id
                for issue in gated_issues
                if issue.apparent_gate_action == "block"
            ],
            issues_to_warn=[
                issue.issue_id
                for issue in gated_issues
                if issue.apparent_gate_action == "warn"
            ],
            issues_requiring_user_confirmation=[
                issue.issue_id
                for issue in gated_issues
                if issue.apparent_gate_action == "require_user_confirmation"
            ],
            issues_not_blocking=[
                issue.issue_id
                for issue in gated_issues
                if issue.apparent_gate_action in {"do_not_block", "warn"}
            ],
            created_narrative_debt_ids=created_debt_ids,
            safe_summary=self._result_summary(gated_issues),
            classifications=classifications,
            decisions=decisions,
            gated_issues=gated_issues,
        )

    def _upsert_apparent_record(
        self,
        *,
        context: Any,
        issue: ContinuityIssue,
        classification: ApparentContradictionClassificationResult,
    ) -> ApparentContradictionRecord:
        record_id = _record_id_for_issue(issue.issue_id)
        project_id = _project_id_for_context(context, issue)
        record = ApparentContradictionRecord(
            apparent_contradiction_id=record_id,
            project_id=project_id,
            chapter_id=issue.chapter_id or context.chapter_id,
            scene_id=issue.scene_id or context.scene_id,
            status="active",
            source_issue_id=issue.issue_id,
            surface_contradiction=_short_text(
                issue.user_visible_message
                or issue.technical_summary
                or issue.evidence_text,
                260,
            ),
            classification=classification.classification,
            device_type=classification.device_type,
            matched_claim_ids=classification.matched_claim_ids,
            matched_narrative_intent_ids=classification.matched_narrative_intent_ids,
            matched_psychology_trace_ids=classification.matched_psychology_trace_ids,
            matched_expression_record_ids=classification.matched_expression_record_ids,
            matched_perception_state_ids=classification.matched_perception_state_ids,
            matched_narrative_debt_ids=classification.matched_narrative_debt_ids,
            matched_refs=classification.matched_refs,
            quality_gate_action=classification.quality_gate_action,
            tracking_action=classification.tracking_action,
        )
        return self.narrative_layer_service.create_apparent_contradiction(record)

    def _ensure_narrative_debt(
        self,
        *,
        context: Any,
        issue: ContinuityIssue,
        classification: ApparentContradictionClassificationResult,
        record: ApparentContradictionRecord,
    ) -> NarrativeDebt | None:
        if classification.tracking_action != "create_narrative_debt":
            return None
        if classification.device_type not in TRACKABLE_DEVICE_TYPES:
            return None
        existing = [
            debt
            for debt in self.narrative_layer_service.list_debts(
                scene_id=context.scene_id,
            )
            if debt.source_apparent_contradiction_id == record.apparent_contradiction_id
            and debt.status in {"active", "intentionally_open"}
        ]
        if existing:
            return existing[0]
        project_id = _project_id_for_context(context, issue)
        debt = NarrativeDebt(
            narrative_debt_id=f"debt_{record.apparent_contradiction_id}",
            project_id=project_id,
            chapter_id=issue.chapter_id or context.chapter_id,
            scene_id=issue.scene_id or context.scene_id,
            source_scene_id=issue.scene_id or context.scene_id,
            source_apparent_contradiction_id=record.apparent_contradiction_id,
            source_narrative_intent_id=(
                classification.matched_narrative_intent_ids[0]
                if classification.matched_narrative_intent_ids
                else ""
            ),
            debt_type=_debt_type_for_device(classification.device_type),
            summary=_short_text(classification.safe_user_summary, 260)
            or "表面矛盾需要后续解释或保持有意歧义。",
            payoff_required=classification.device_type
            not in {"open_ambiguity", "symbolic_unresolved"},
            open_ambiguity_allowed=classification.device_type == "open_ambiguity",
            symbolic_unresolved=classification.device_type == "symbolic_unresolved",
            source_refs=[
                NarrativeObjectReference(
                    object_type="continuity_issue",
                    object_id=issue.issue_id,
                    relation="source issue",
                ),
                NarrativeObjectReference(
                    object_type="apparent_contradiction",
                    object_id=record.apparent_contradiction_id,
                    relation="source apparent contradiction",
                ),
            ],
        )
        return self.narrative_layer_service.create_narrative_debt(debt)

    def _apply_gate_decision(
        self,
        *,
        issue: ContinuityIssue,
        classification: ApparentContradictionClassificationResult,
        apparent_record: ApparentContradictionRecord,
        mode: str,
    ) -> ContinuityIssue:
        action = classification.quality_gate_action
        if issue.category in HARD_BLOCK_CATEGORIES:
            action = "block"
        if action == "do_not_block" and not _has_matched_records(classification):
            action = "require_user_confirmation"
        severity, blocks_final, blocks_revision, requires_acceptance, policy = (
            self._decision_fields(issue, action)
        )
        if (
            mode == "revision_confirmation"
            and issue.blocks_state_changing_revision_confirmation
            and action != "block"
        ):
            blocks_revision = True
            requires_acceptance = True
            if severity == "info":
                severity = "requires_user_confirmation"
            if policy == "allowed":
                policy = "requires_strong_confirmation"
        data = model_to_dict(issue)
        data.update(
            {
                "severity": severity,
                "blocks_final_confirmation": blocks_final,
                "blocks_state_changing_revision_confirmation": blocks_revision,
                "requires_explicit_acceptance": requires_acceptance,
                "acceptance_policy": policy,
                "apparent_contradiction_ids": _unique_strings(
                    [
                        *issue.apparent_contradiction_ids,
                        apparent_record.apparent_contradiction_id,
                    ]
                ),
                "apparent_gate_action": action,
                "apparent_classification": classification.classification,
                "apparent_device_type": classification.device_type,
                "apparent_evidence_summary": _short_text(
                    classification.safe_user_summary,
                    260,
                ),
                "apparent_matched_record_ids": _matched_record_ids(classification),
                "updated_at": now_iso(),
            }
        )
        if action != "block":
            data["technical_summary"] = _append_gate_note(
                issue.technical_summary,
                action,
                apparent_record.apparent_contradiction_id,
            )
        return ContinuityIssue(**data)

    def _decision_fields(
        self,
        issue: ContinuityIssue,
        action: str,
    ) -> tuple[str, bool, bool, bool, str]:
        if issue.category in HARD_BLOCK_CATEGORIES:
            return "blocking", True, True, True, "forbidden"
        if action == "block":
            return (
                "blocking",
                True,
                True,
                True,
                issue.acceptance_policy
                if issue.acceptance_policy != "forbidden"
                else "requires_strong_confirmation",
            )
        if action == "require_user_confirmation":
            return (
                "requires_user_confirmation",
                False,
                False,
                True,
                "requires_strong_confirmation",
            )
        if action == "warn":
            return "warning", False, False, False, issue.acceptance_policy or "allowed"
        return "info", False, False, False, "allowed"

    def _decision_for_issue(
        self,
        issue: ContinuityIssue,
    ) -> ApparentContradictionGateDecision:
        return ApparentContradictionGateDecision(
            issue_id=issue.issue_id,
            quality_gate_action=issue.apparent_gate_action or "block",
            severity=issue.severity,
            blocks_final_confirmation=issue.blocks_final_confirmation,
            blocks_state_changing_revision_confirmation=(
                issue.blocks_state_changing_revision_confirmation
            ),
            requires_explicit_acceptance=issue.requires_explicit_acceptance,
            acceptance_policy=issue.acceptance_policy,
        )

    def _result_summary(self, issues: list[ContinuityIssue]) -> str:
        blocking = sum(1 for issue in issues if issue.apparent_gate_action == "block")
        require = sum(
            1
            for issue in issues
            if issue.apparent_gate_action == "require_user_confirmation"
        )
        warnings = sum(1 for issue in issues if issue.apparent_gate_action == "warn")
        informational = sum(
            1 for issue in issues if issue.apparent_gate_action == "do_not_block"
        )
        return (
            f"表面矛盾门完成：阻断 {blocking}，需确认 {require}，"
            f"提醒 {warnings}，放行 {informational}。"
        )


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


def _record_id_for_issue(issue_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", issue_id or "unknown").strip("_")
    return f"apparent_{safe or 'unknown'}"


def _project_id_for_context(context: Any, issue: ContinuityIssue) -> str:
    return (
        str(getattr(issue, "project_id", "") or "").strip()
        or str(getattr(context, "project_id", "") or "").strip()
        or LOCAL_PROJECT_ID
    )


def _debt_type_for_device(device_type: str) -> str:
    if device_type == "delayed_reveal":
        return "delayed_explanation"
    if device_type == "unreliable_perception":
        return "hallucination"
    if device_type in {
        "foreshadowing",
        "misdirection",
        "hallucination",
        "delayed_explanation",
        "psychological_contradiction",
        "unreliable_claim",
        "open_ambiguity",
        "symbolic_unresolved",
    }:
        return device_type
    return "other"


def _has_matched_records(
    classification: ApparentContradictionClassificationResult,
) -> bool:
    return bool(_matched_record_ids(classification))


def _matched_record_ids(
    classification: ApparentContradictionClassificationResult,
) -> list[str]:
    return _unique_strings(
        [
            *classification.matched_claim_ids,
            *classification.matched_narrative_intent_ids,
            *classification.matched_psychology_trace_ids,
            *classification.matched_expression_record_ids,
            *classification.matched_perception_state_ids,
            *classification.matched_narrative_debt_ids,
            *[
                ref.object_id
                for ref in classification.matched_refs
                if ref.object_id
            ],
        ]
    )


def _append_gate_note(summary: str, action: str, record_id: str) -> str:
    note = f"M4 apparent_contradiction_gate={action}; record={record_id}."
    text = str(summary or "").strip()
    if note in text:
        return text
    if not text:
        return note
    return _short_text(f"{text} {note}", 500)


def _short_text(value: Any, limit: int = 260) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."


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
