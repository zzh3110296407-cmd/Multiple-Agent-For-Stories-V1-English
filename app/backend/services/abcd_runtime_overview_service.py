from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.abcd_runtime_gate import (
    ABCDContinuityRuntimeIssue,
    ABCDQualityGateRuntimeReport,
    ABCDRuntimeGateIntegrationAudit,
    ABCDRuntimeGateIssueAcceptance,
)
from app.backend.models.abcd_runtime_overview import (
    ABCDRuntimeCharacterIntentOverview,
    ABCDRuntimeGateIssueOverview,
    ABCDRuntimeGateOverview,
    ABCDRuntimeOverviewResponse,
    ABCDRuntimeParticipantOverview,
    ABCDRuntimeRoleMemoryOverview,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.abcd_runtime_gate_context_builder import (
    ABCDRuntimeGateContextBuilder,
)
from app.backend.storage.json_store import JsonStore, StorageError


UNSAFE_VALUE_MARKERS = {
    "raw_prompt",
    "raw response",
    "raw_response",
    "hidden_reasoning",
    "internal_reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "api_key",
    "sk-",
    "lsv2_",
}


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ABCDRuntimeOverviewService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        context_builder: ABCDRuntimeGateContextBuilder | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.context_builder = context_builder or ABCDRuntimeGateContextBuilder(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.runtime_issues_file = self.data_dir / "abcd_continuity_runtime_issues.json"
        self.quality_reports_file = self.data_dir / "abcd_quality_runtime_reports.json"
        self.audits_file = self.data_dir / "abcd_runtime_gate_integration_audits.json"
        self.acceptances_file = self.data_dir / "abcd_runtime_gate_issue_acceptances.json"

    def get_scene_overview(self, scene_id: str) -> ABCDRuntimeOverviewResponse:
        clean_scene_id = str(scene_id or "").strip()
        if not clean_scene_id:
            raise StorageError("ABCD_RUNTIME_OVERVIEW_SCENE_ID_REQUIRED")
        bundle = self.context_builder.build_bundle(clean_scene_id, mode="draft_review")
        scene = bundle["scene"]
        participation = bundle.get("scene_participation")
        context_package = bundle.get("tiered_character_context")
        intent_package = bundle.get("tiered_character_intent")
        intent_candidates = list(bundle.get("intent_candidates") or [])
        risk_reports = list(bundle.get("risk_reports") or [])
        story_package = bundle.get("abcd_story_information")
        story_items = list(bundle.get("story_information_items") or [])
        write_plan = bundle.get("tiered_scene_memory_write_plan")
        role_entries = list(bundle.get("role_scene_memory_entries") or [])

        participants = self._participants(participation, context_package)
        gate_summary = self._gate_summary(clean_scene_id)
        warnings = _unique_strings(
            [
                *list(bundle.get("warnings") or []),
                *list(getattr(participation, "warnings", []) or []),
                *list(getattr(context_package, "warnings", []) or []),
                *list(getattr(intent_package, "warnings", []) or []),
                *list(getattr(story_package, "warnings", []) or []),
                *list(getattr(write_plan, "warnings", []) or []),
            ]
        )

        return ABCDRuntimeOverviewResponse(
            project_id=str(scene.project_id or ""),
            chapter_id=str(scene.chapter_id or ""),
            scene_id=str(scene.scene_id or ""),
            scene_index=int(scene.scene_index or 0),
            scene_status=str(scene.status or ""),
            participants=participants,
            context_summary=self._context_summary(
                participation=participation,
                context_package=context_package,
                participants=participants,
            ),
            intent_summary=self._intent_summary(
                intent_package=intent_package,
                story_package=story_package,
                story_items=story_items,
            ),
            character_intent_summaries=self._character_intent_summaries(
                participants=participants,
                intent_package=intent_package,
                intent_candidates=intent_candidates,
                risk_reports=risk_reports,
            ),
            memory_write_summary=self._memory_write_summary(write_plan),
            role_memory_summaries=self._role_memory_summaries(
                participants=participants,
                role_entries=role_entries,
                write_plan=write_plan,
            ),
            gate_summary=gate_summary,
            warnings=warnings,
            safe_summary=(
                f"ABCD runtime overview for scene {scene.scene_id}: "
                f"{len(participants)} participants, "
                f"{len(intent_candidates)} intent candidates, "
                f"{len(role_entries)} role-memory entries, "
                f"gate status {gate_summary.status}."
            ),
        )

    def _participants(
        self,
        participation: Any,
        context_package: Any,
    ) -> list[ABCDRuntimeParticipantOverview]:
        context_by_character = {
            str(item.character_id): item
            for item in list(getattr(context_package, "items", []) or [])
        }
        package_participants = list(getattr(participation, "participants", []) or [])
        if not package_participants and context_by_character:
            package_participants = [
                {
                    "character_id": character_id,
                    "name": getattr(item, "name", ""),
                    "tier": getattr(item, "tier", "D"),
                }
                for character_id, item in context_by_character.items()
            ]
        result: list[ABCDRuntimeParticipantOverview] = []
        for participant in package_participants:
            character_id = _get(participant, "character_id")
            context_item = context_by_character.get(character_id)
            result.append(
                ABCDRuntimeParticipantOverview(
                    character_id=character_id,
                    name=_safe_text(
                        _get(participant, "name")
                        or getattr(context_item, "name", "")
                    ),
                    tier=(_get(participant, "tier") or getattr(context_item, "tier", "D") or "D").upper(),
                    origin=_safe_text(_get(participant, "participation_source")),
                    selection_reason=_safe_text(_get(participant, "selection_reason")),
                    context_depth=_safe_text(_get(participant, "context_depth")),
                    context_summary=_safe_text(
                        getattr(context_item, "current_state_summary", "")
                        or getattr(context_item, "profile_summary", "")
                        or getattr(context_item, "memory_summary", "")
                    ),
                    source_memory_ids=list(getattr(context_item, "source_memory_ids", []) or []),
                )
            )
        return result

    def _context_summary(
        self,
        *,
        participation: Any,
        context_package: Any,
        participants: list[ABCDRuntimeParticipantOverview],
    ) -> dict[str, Any]:
        return {
            "scene_participation_package_id": str(
                getattr(participation, "scene_participation_package_id", "") or ""
            ),
            "tiered_character_context_package_id": str(
                getattr(context_package, "tiered_character_context_package_id", "") or ""
            ),
            "active_character_ids": [item.character_id for item in participants],
            "context_item_count": int(getattr(context_package, "item_count", 0) or 0),
            "tier_counts": _tier_counts([item.tier for item in participants]),
            "safe_summary": _safe_text(
                f"{len(participants)} selected participants are available for ABCD runtime context."
            ),
        }

    def _intent_summary(
        self,
        *,
        intent_package: Any,
        story_package: Any,
        story_items: list[Any],
    ) -> dict[str, Any]:
        return {
            "tiered_character_intent_package_id": str(
                getattr(intent_package, "tiered_character_intent_package_id", "") or ""
            ),
            "abcd_story_information_package_id": str(
                getattr(story_package, "abcd_story_information_package_id", "") or ""
            ),
            "writer_ready_candidate_count": len(
                list(getattr(intent_package, "writer_ready_candidate_ids", []) or [])
            ),
            "blocked_candidate_count": len(
                list(getattr(intent_package, "blocked_candidate_ids", []) or [])
            ),
            "needs_gate_candidate_count": len(
                list(getattr(intent_package, "needs_gate_candidate_ids", []) or [])
            ),
            "writer_ready_item_count": len(
                list(getattr(story_package, "writer_ready_item_ids", []) or [])
            ),
            "do_not_use_item_count": len(
                list(getattr(story_package, "do_not_use_item_ids", []) or [])
            ),
            "item_count": len(story_items),
            "safe_summary": _safe_text(
                getattr(intent_package, "safe_summary", "")
                or getattr(story_package, "safe_summary", "")
                or "No ABCD intent package has been prepared yet."
            ),
        }

    def _character_intent_summaries(
        self,
        *,
        participants: list[ABCDRuntimeParticipantOverview],
        intent_package: Any,
        intent_candidates: list[Any],
        risk_reports: list[Any],
    ) -> list[ABCDRuntimeCharacterIntentOverview]:
        writer_ready_ids = set(getattr(intent_package, "writer_ready_candidate_ids", []) or [])
        blocked_ids = set(getattr(intent_package, "blocked_candidate_ids", []) or [])
        needs_gate_ids = set(getattr(intent_package, "needs_gate_candidate_ids", []) or [])
        risk_by_candidate: dict[str, list[str]] = {}
        for report in risk_reports:
            risk_by_candidate.setdefault(
                str(getattr(report, "action_intention_candidate_id", "") or ""),
                [],
            ).append(str(getattr(report, "risk_report_id", "") or ""))
        result: list[ABCDRuntimeCharacterIntentOverview] = []
        for participant in participants:
            candidates = [
                candidate
                for candidate in intent_candidates
                if str(getattr(candidate, "character_id", "") or "") == participant.character_id
            ]
            candidate_ids = [
                str(getattr(candidate, "action_intention_candidate_id", "") or "")
                for candidate in candidates
            ]
            risk_ids: list[str] = []
            for candidate_id in candidate_ids:
                risk_ids.extend(risk_by_candidate.get(candidate_id, []))
            result.append(
                ABCDRuntimeCharacterIntentOverview(
                    character_id=participant.character_id,
                    tier=participant.tier,
                    candidate_count=len(candidates),
                    writer_ready_candidate_count=len(
                        [candidate_id for candidate_id in candidate_ids if candidate_id in writer_ready_ids]
                    ),
                    blocked_candidate_count=len(
                        [candidate_id for candidate_id in candidate_ids if candidate_id in blocked_ids]
                    ),
                    needs_gate_candidate_count=len(
                        [candidate_id for candidate_id in candidate_ids if candidate_id in needs_gate_ids]
                    ),
                    safe_summaries=[
                        _safe_text(getattr(candidate, "safe_summary", ""))
                        for candidate in candidates
                        if _safe_text(getattr(candidate, "safe_summary", ""))
                    ][:4],
                    source_candidate_ids=candidate_ids,
                    source_risk_report_ids=risk_ids,
                )
            )
        return result

    def _memory_write_summary(self, write_plan: Any) -> dict[str, Any]:
        if write_plan is None:
            return {
                "tiered_scene_memory_write_plan_id": "",
                "entry_count": 0,
                "written_memory_count": 0,
                "blocked_memory_count": 0,
                "safe_summary": "No tiered role-memory write plan is available yet.",
            }
        return {
            "tiered_scene_memory_write_plan_id": str(
                getattr(write_plan, "tiered_scene_memory_write_plan_id", "") or ""
            ),
            "target_memory_status": str(getattr(write_plan, "target_memory_status", "") or ""),
            "entry_count": len(list(getattr(write_plan, "role_memory_entry_ids", []) or [])),
            "written_memory_count": len(
                list(getattr(write_plan, "target_memory_record_ids", []) or [])
            ),
            "blocked_memory_count": int(getattr(write_plan, "blocked_memory_count", 0) or 0),
            "requires_user_confirmation_count": int(
                getattr(write_plan, "requires_user_confirmation_count", 0) or 0
            ),
            "safe_summary": _safe_text(getattr(write_plan, "safe_summary", "")),
        }

    def _role_memory_summaries(
        self,
        *,
        participants: list[ABCDRuntimeParticipantOverview],
        role_entries: list[Any],
        write_plan: Any,
    ) -> list[ABCDRuntimeRoleMemoryOverview]:
        result: list[ABCDRuntimeRoleMemoryOverview] = []
        for participant in participants:
            entries = [
                entry
                for entry in role_entries
                if str(getattr(entry, "character_id", "") or "") == participant.character_id
            ]
            result.append(
                ABCDRuntimeRoleMemoryOverview(
                    character_id=participant.character_id,
                    tier=participant.tier,
                    entry_count=len(entries),
                    written_count=len(
                        [entry for entry in entries if getattr(entry, "status", "") == "written"]
                    ),
                    blocked_count=len(
                        [entry for entry in entries if getattr(entry, "status", "") == "blocked"]
                    ),
                    truth_statuses=[
                        str(getattr(entry, "truth_status", "") or "")
                        for entry in entries
                    ],
                    safe_summaries=[
                        _safe_text(
                            getattr(entry, "safe_summary", "")
                            or getattr(entry, "memory_summary", "")
                        )
                        for entry in entries
                        if _safe_text(
                            getattr(entry, "safe_summary", "")
                            or getattr(entry, "memory_summary", "")
                        )
                    ][:4],
                    source_role_memory_entry_ids=[
                        str(getattr(entry, "role_scene_memory_entry_id", "") or "")
                        for entry in entries
                    ],
                    target_memory_record_ids=[
                        str(getattr(entry, "target_memory_record_id", "") or "")
                        for entry in entries
                        if str(getattr(entry, "target_memory_record_id", "") or "")
                    ],
                )
            )
        if not result and write_plan is not None:
            result.append(
                ABCDRuntimeRoleMemoryOverview(
                    character_id="",
                    entry_count=len(list(getattr(write_plan, "role_memory_entry_ids", []) or [])),
                    written_count=len(list(getattr(write_plan, "target_memory_record_ids", []) or [])),
                )
            )
        return result

    def _gate_summary(self, scene_id: str) -> ABCDRuntimeGateOverview:
        issues = self._dedupe_latest(
            [
                issue
                for issue in self._read_models(
                    self.runtime_issues_file,
                    ABCDContinuityRuntimeIssue,
                )
                if issue.scene_id == scene_id
            ],
            key_attr="runtime_issue_id",
        )
        latest_quality = _latest(
            [
                item
                for item in self._read_models(
                    self.quality_reports_file,
                    ABCDQualityGateRuntimeReport,
                )
                if item.scene_id == scene_id
            ]
        )
        latest_audit = _latest(
            [
                item
                for item in self._read_models(
                    self.audits_file,
                    ABCDRuntimeGateIntegrationAudit,
                )
                if item.scene_id == scene_id
            ]
        )
        accepted_ids = set(self._accepted_issue_ids(scene_id))
        if latest_quality is not None:
            accepted_ids.update(latest_quality.accepted_user_confirmation_issue_ids)
        if latest_audit is not None:
            accepted_ids.update(latest_audit.accepted_user_confirmation_issue_ids)
        blocking_ids = set(
            list(getattr(latest_quality, "blocking_issue_ids", []) or [])
            + list(getattr(latest_audit, "blocking_issue_ids", []) or [])
        )
        requires_ids = set(
            list(getattr(latest_quality, "requires_user_confirmation_issue_ids", []) or [])
            + list(getattr(latest_audit, "requires_user_confirmation_issue_ids", []) or [])
        )
        warning_ids = set(list(getattr(latest_quality, "warning_issue_ids", []) or []))
        overview_issues = [
            self._gate_issue_overview(
                issue,
                blocking_ids=blocking_ids,
                requires_ids=requires_ids,
                warning_ids=warning_ids,
                accepted_ids=accepted_ids,
            )
            for issue in issues
        ]
        unresolved_requires = [item.issue_id for item in overview_issues if item.status == "requires_user_confirmation"]
        unresolved_blocking = [item.issue_id for item in overview_issues if item.status == "blocking"]
        if latest_audit is None and latest_quality is None and not overview_issues:
            status = "not_run"
        elif unresolved_blocking:
            status = "blocked"
        elif unresolved_requires:
            status = "requires_user_confirmation"
        elif latest_audit is not None and latest_audit.passed:
            status = "passed"
        elif latest_quality is not None and latest_quality.passed:
            status = "passed"
        else:
            status = "warning"
        return ABCDRuntimeGateOverview(
            status=status,
            has_blockers=bool(unresolved_blocking),
            requires_user_confirmation=bool(unresolved_requires),
            unresolved_issue_count=len(unresolved_blocking) + len(unresolved_requires),
            accepted_issue_count=len(
                [item for item in overview_issues if item.status == "accepted"]
            ),
            blocking_issue_ids=sorted(unresolved_blocking),
            requires_user_confirmation_issue_ids=sorted(unresolved_requires),
            accepted_issue_ids=sorted(
                [item.issue_id for item in overview_issues if item.status == "accepted"]
            ),
            issues=overview_issues,
            safe_summary=_safe_text(
                getattr(latest_audit, "safe_summary", "")
                if latest_audit is not None
                else getattr(latest_quality, "safe_summary", "")
                if latest_quality is not None
                else "ABCD runtime gate has not been run for this scene."
            ),
        )

    def _gate_issue_overview(
        self,
        issue: ABCDContinuityRuntimeIssue,
        *,
        blocking_ids: set[str],
        requires_ids: set[str],
        warning_ids: set[str],
        accepted_ids: set[str],
    ) -> ABCDRuntimeGateIssueOverview:
        issue_id = issue.runtime_issue_id
        is_blocking = issue_id in blocking_ids or issue.severity == "blocking"
        is_requires_confirmation = (
            not is_blocking
            and (issue_id in requires_ids or issue.severity == "requires_user_confirmation")
        )
        if is_blocking:
            status = "blocking"
        elif issue_id in accepted_ids:
            status = "accepted"
        elif is_requires_confirmation:
            status = "requires_user_confirmation"
        elif issue_id in warning_ids or issue.severity == "warning":
            status = "warning"
        else:
            status = "open"
        evidence_refs = [
            f"{issue.source_artifact_type}:{issue.source_artifact_id}"
            if issue.source_artifact_type and issue.source_artifact_id
            else "",
            f"continuity:{issue.continuity_issue_id}" if issue.continuity_issue_id else "",
        ]
        return ABCDRuntimeGateIssueOverview(
            issue_id=issue_id,
            severity=issue.severity,
            issue_type=issue.issue_category,
            status=status,
            requires_user_confirmation=is_requires_confirmation,
            safe_summary=_safe_text(issue.safe_summary),
            evidence_refs=evidence_refs,
        )

    def _accepted_issue_ids(self, scene_id: str) -> list[str]:
        return [
            item.runtime_issue_id
            for item in self._read_models(
                self.acceptances_file,
                ABCDRuntimeGateIssueAcceptance,
            )
            if item.scene_id == scene_id
        ]

    def _dedupe_latest(self, models: list[Any], *, key_attr: str) -> list[Any]:
        result: dict[str, Any] = {}
        for model in models:
            key = str(getattr(model, key_attr, "") or "")
            if not key:
                continue
            existing = result.get(key)
            if existing is None or _sort_key(model) >= _sort_key(existing):
                result[key] = model
        return sorted(result.values(), key=lambda item: str(getattr(item, key_attr, "") or ""))

    def _read_models(self, path: Path, model_type: type[Any]) -> list[Any]:
        if not self.store.exists(path):
            return []
        rows = self.store.read_list(path)
        if not isinstance(rows, list):
            return []
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                result.append(model_type(**row))
            except ValidationError:
                continue
        return result


def _get(value: Any, key: str) -> str:
    if isinstance(value, dict):
        return str(value.get(key) or "")
    return str(getattr(value, key, "") or "")


def _tier_counts(tiers: list[str]) -> dict[str, int]:
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for tier in tiers:
        normalized = str(tier or "D").upper()
        counts[normalized if normalized in counts else "D"] += 1
    return counts


def _latest(models: list[Any]) -> Any | None:
    if not models:
        return None
    return sorted(models, key=_sort_key)[-1]


def _sort_key(model: Any) -> tuple[str, str]:
    return (
        str(getattr(model, "updated_at", "") or ""),
        str(getattr(model, "created_at", "") or ""),
    )


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.casefold()
    if any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
        return "[redacted unsafe runtime detail]"
    if len(text) > 500:
        return text[:497].rstrip() + "..."
    return text


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
