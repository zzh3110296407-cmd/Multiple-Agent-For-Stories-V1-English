from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.continuity import (
    CONTINUITY_RESOLUTION_OPTION_TYPES,
    ContinuityIssue,
    ContinuityResolutionAuthorityGuardResult,
    ContinuityResolutionAuthorityPolicy,
    ContinuityResolutionOptionAvailability,
    ContinuityResolutionOptionAvailabilityReport,
    ContinuityResolutionOptionDefinition,
    ContinuityResolutionOptionExecutionRequest,
    ContinuityResolutionOptionExecutionResult,
)
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.continuity_gate_service import ContinuityGateService, now_iso
from app.backend.services.continuity_resolution_refresh_service import (
    ContinuityResolutionRefreshService,
)
from app.backend.services.continuity_resolution_service import IssueResolutionService
from app.backend.storage.json_store import JsonStore, StorageError


EXECUTABLE_OPTION_TYPES = {
    "complete_prior_story",
    "revise_current_scene",
    "mark_as_claim_or_misinformation",
    "keep_open_or_defer",
}

LEGACY_ACTION_BY_OPTION = {
    "complete_prior_story": "complete_prior_story",
    "revise_current_scene": "revise_current_scene",
    "mark_as_claim_or_misinformation": "mark_as_misinformation_or_lie",
}


def model_to_dict(model: BaseModel | dict[str, Any] | None) -> dict[str, Any]:
    if model is None:
        return {}
    if isinstance(model, dict):
        return dict(model)
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class ContinuityResolutionOptionMatrixService:
    def definitions(self) -> list[ContinuityResolutionOptionDefinition]:
        return [
            ContinuityResolutionOptionDefinition(
                option_type="complete_prior_story",
                label="Complete prior story",
                description="Create or reuse a prior-story completion candidate without immediately writing Event or MemoryRecord.",
                default_risk_level="medium",
                will_create_candidate=True,
                requires_user_input=True,
                requires_user_confirmation=True,
                expected_effect="Creates a governed prior-story completion candidate; confirmation is separate.",
                policy_notes=[
                    "candidate_first",
                    "does_not_immediately_write_event_or_memory",
                ],
            ),
            ContinuityResolutionOptionDefinition(
                option_type="revise_current_scene",
                label="Revise current scene",
                description="Create a scene revision candidate that can later be checked and confirmed.",
                default_risk_level="medium",
                will_create_revision_candidate=True,
                requires_user_input=True,
                requires_user_confirmation=True,
                expected_effect="Creates a SceneRevisionCandidate; confirmed prose is not overwritten now.",
                policy_notes=["revision_candidate_first"],
            ),
            ContinuityResolutionOptionDefinition(
                option_type="mark_as_claim_or_misinformation",
                label="Mark as claim or misinformation",
                description="Record the disputed statement as non-objective truth.",
                default_risk_level="medium",
                will_write_subjective_fact=True,
                requires_user_input=True,
                expected_effect="Writes subjective/non-objective memory state and resolves this issue.",
                policy_notes=["no_objective_event_write"],
            ),
            ContinuityResolutionOptionDefinition(
                option_type="mark_as_perception_or_hallucination",
                label="Mark as perception or hallucination",
                description="Represent the issue as subjective perception when a verified safe path exists.",
                default_risk_level="high",
                will_write_subjective_fact=True,
                requires_user_input=True,
                expected_effect="M6 exposes this path but keeps execution gated until a verified perception writer is selected.",
                policy_notes=["advanced_gated_in_m6"],
            ),
            ContinuityResolutionOptionDefinition(
                option_type="mark_as_apparent_contradiction",
                label="Mark as apparent contradiction",
                description="Route through apparent-contradiction semantics; never directly accepts hard conflicts.",
                default_risk_level="high",
                requires_user_input=True,
                requires_user_confirmation=True,
                expected_effect="M6 exposes this path as gated because apparent contradiction is not a direct resolver.",
                policy_notes=["must_not_directly_resolve_hard_conflicts"],
            ),
            ContinuityResolutionOptionDefinition(
                option_type="create_or_update_narrative_debt",
                label="Create or update narrative debt",
                description="Track a deferred explanation without automatically paying it off.",
                default_risk_level="high",
                will_create_narrative_debt=True,
                requires_user_input=True,
                expected_effect="M6 exposes this path as gated; debt cannot automatically clear blocking issues.",
                policy_notes=["does_not_auto_resolve_issue"],
            ),
            ContinuityResolutionOptionDefinition(
                option_type="keep_open_or_defer",
                label="Keep open or defer",
                description="Do not write facts and keep the issue visible for later decision.",
                default_risk_level="low",
                expected_effect="Returns a refresh payload with the issue still open.",
                policy_notes=["no_write"],
            ),
        ]


class ContinuityResolutionAuthorityGuard:
    def policy_for(
        self,
        issue: ContinuityIssue,
        definition: ContinuityResolutionOptionDefinition,
    ) -> ContinuityResolutionAuthorityPolicy:
        option_type = definition.option_type
        violates_hard_rule = (
            issue.category == "world_hard_rule_direct_conflict"
            and option_type not in {"revise_current_scene", "keep_open_or_defer"}
        )
        return ContinuityResolutionAuthorityPolicy(
            option_type=option_type,
            may_write_objective_fact=False,
            must_create_candidate=option_type in {"complete_prior_story", "revise_current_scene"},
            requires_user_confirmation=definition.requires_user_confirmation,
            may_resolve_source_issue_now=option_type == "mark_as_claim_or_misinformation",
            affects_source_story_data=False,
            violates_hard_rule_policy=violates_hard_rule,
            subjective_only=option_type in {
                "mark_as_claim_or_misinformation",
                "mark_as_perception_or_hallucination",
            },
            may_convert_blocking_to_accepted=False,
            notes=list(definition.policy_notes),
        )

    def check(
        self,
        issue: ContinuityIssue,
        option: ContinuityResolutionOptionAvailability,
    ) -> ContinuityResolutionAuthorityGuardResult:
        policy = ContinuityResolutionAuthorityPolicy(
            option_type=option.option_type,
            may_write_objective_fact=False,
            must_create_candidate=option.option_type in {"complete_prior_story", "revise_current_scene"},
            requires_user_confirmation=option.requires_user_confirmation,
            may_resolve_source_issue_now=option.option_type == "mark_as_claim_or_misinformation",
            affects_source_story_data=False,
            violates_hard_rule_policy=(
                issue.category == "world_hard_rule_direct_conflict"
                and option.option_type not in {"revise_current_scene", "keep_open_or_defer"}
            ),
            subjective_only=option.option_type in {
                "mark_as_claim_or_misinformation",
                "mark_as_perception_or_hallucination",
            },
            may_convert_blocking_to_accepted=False,
            notes=list(option.policy_notes),
        )
        blocked: list[str] = []
        if not option.enabled:
            blocked.append(option.disabled_reason or "option_not_enabled")
        if option.option_type not in EXECUTABLE_OPTION_TYPES:
            blocked.append("option_is_gated_in_m6_mvp")
        if policy.violates_hard_rule_policy:
            blocked.append("hard_rule_policy_blocks_this_option")
        return ContinuityResolutionAuthorityGuardResult(
            allowed=not blocked,
            option_type=option.option_type,
            issue_id=issue.issue_id,
            policy=policy,
            warnings=[option.authority_warning] if option.authority_warning else [],
            blocked_reasons=_unique_strings(blocked),
        )


class ContinuityResolutionOptionAvailabilityService:
    def __init__(
        self,
        *,
        matrix_service: ContinuityResolutionOptionMatrixService | None = None,
        authority_guard: ContinuityResolutionAuthorityGuard | None = None,
    ) -> None:
        self.matrix_service = matrix_service or ContinuityResolutionOptionMatrixService()
        self.authority_guard = authority_guard or ContinuityResolutionAuthorityGuard()

    def matrix(self) -> dict[str, Any]:
        definitions = self.matrix_service.definitions()
        return {
            "success": True,
            "option_types": [item.option_type for item in definitions],
            "options": [model_to_dict(item) for item in definitions],
            "generated_at": now_iso(),
        }

    def report_for_issue(self, issue: ContinuityIssue) -> ContinuityResolutionOptionAvailabilityReport:
        options = [self._availability_for(issue, definition) for definition in self.matrix_service.definitions()]
        return ContinuityResolutionOptionAvailabilityReport(
            issue_id=issue.issue_id,
            issue=issue,
            options=options,
            recommended_options=[item for item in options if item.availability_status == "recommended"],
            available_options=[item for item in options if item.availability_status == "available"],
            advanced_gated_options=[item for item in options if item.availability_status == "advanced_gated"],
            blocked_options=[item for item in options if item.availability_status == "blocked"],
            generated_at=now_iso(),
        )

    def _availability_for(
        self,
        issue: ContinuityIssue,
        definition: ContinuityResolutionOptionDefinition,
    ) -> ContinuityResolutionOptionAvailability:
        if issue.status != "open":
            status, rank, reason, warning, notes = (
                "blocked",
                0,
                "continuity_issue_not_open",
                "Resolution options can only execute for open continuity issues.",
                ["issue_status_not_open"],
            )
        else:
            status, rank, reason, warning, notes = self._category_status(issue, definition.option_type)
        enabled = status in {"recommended", "available"}
        option = ContinuityResolutionOptionAvailability(
            option_type=definition.option_type,
            label=definition.label,
            description=definition.description,
            enabled=enabled,
            disabled_reason="" if enabled else reason,
            availability_status=status,
            recommended=status == "recommended",
            recommended_rank=rank if status == "recommended" else 0,
            risk_level=definition.default_risk_level,
            requires_user_input=definition.requires_user_input,
            requires_user_confirmation=definition.requires_user_confirmation,
            required_input_fields=self._required_fields(definition.option_type),
            will_write_objective_fact=False,
            will_write_subjective_fact=definition.will_write_subjective_fact,
            will_create_candidate=definition.will_create_candidate,
            will_create_revision_candidate=definition.will_create_revision_candidate,
            will_create_narrative_debt=definition.will_create_narrative_debt,
            expected_effect=definition.expected_effect,
            authority_warning=warning,
            policy_notes=_unique_strings([*definition.policy_notes, *notes]),
        )
        policy = self.authority_guard.policy_for(issue, definition)
        if policy.violates_hard_rule_policy and option.enabled:
            option.enabled = False
            option.availability_status = "blocked"
            option.recommended = False
            option.recommended_rank = 0
            option.disabled_reason = "hard_rule_policy_blocks_this_option"
            option.authority_warning = "Hard-rule conflicts can only be revised or kept open in M6."
        return option

    def _category_status(
        self,
        issue: ContinuityIssue,
        option_type: str,
    ) -> tuple[str, int, str, str, list[str]]:
        category = issue.category
        hard_rule_warning = "Hard-rule conflicts cannot be reframed into subjective/debt paths by M6."
        missing_source = _mentions_missing_source(issue)
        if category in {"no_source_fact", "unverified_old_event"}:
            rules = {
                "complete_prior_story": ("recommended", 1, "", "", ["missing_source_default"]),
                "mark_as_claim_or_misinformation": ("available", 0, "", "", []),
                "revise_current_scene": ("available", 0, "", "", []),
                "keep_open_or_defer": ("available", 0, "", "", ["no_write"]),
                "mark_as_perception_or_hallucination": (
                    "advanced_gated",
                    0,
                    "No verified perception writer is enabled for M6 MVP.",
                    "Subjective perception requires a verified writer path.",
                    [],
                ),
                "create_or_update_narrative_debt": (
                    "advanced_gated",
                    0,
                    "Narrative debt tracking cannot automatically resolve this issue in M6.",
                    "Debt is tracking only; it does not prove source facts.",
                    [],
                ),
            }
            return rules.get(option_type, _blocked("This option is not a default missing-source resolver."))
        if category == "world_hard_rule_direct_conflict":
            if option_type == "revise_current_scene":
                return ("recommended", 1, "", "", ["hard_rule_safe_path"])
            if option_type == "keep_open_or_defer":
                return ("available", 0, "", "", ["no_write"])
            return ("blocked", 0, "Hard-rule conflicts must be revised or kept open.", hard_rule_warning, [])
        if category == "forbidden_knowledge":
            if option_type == "revise_current_scene":
                return ("recommended", 1, "", "", [])
            if option_type == "mark_as_claim_or_misinformation":
                return ("available", 0, "", "", ["subjective_only"])
            if option_type == "mark_as_perception_or_hallucination":
                return (
                    "advanced_gated",
                    0,
                    "No verified perception writer is enabled for M6 MVP.",
                    "Perception handling is exposed but gated.",
                    ["subjective_only"],
                )
            if option_type == "keep_open_or_defer":
                return ("available", 0, "", "", ["no_write"])
            if option_type == "complete_prior_story" and missing_source:
                return ("available", 0, "", "", ["conditional_missing_source"])
            return _blocked("Forbidden knowledge cannot be solved by this option by default.")
        if category == "location_scene_state_contradiction":
            if option_type == "revise_current_scene":
                return ("recommended", 1, "", "", [])
            if option_type == "keep_open_or_defer":
                return ("available", 0, "", "", ["no_write"])
            if option_type in {
                "mark_as_perception_or_hallucination",
                "mark_as_apparent_contradiction",
                "create_or_update_narrative_debt",
            }:
                return (
                    "advanced_gated",
                    0,
                    "This option needs a verified non-objective/debt policy path before execution.",
                    "Gated to avoid mutating objective location state.",
                    [],
                )
            return _blocked("M6 cannot directly rewrite objective location or scene state.")
        if category == "relationship_contradiction":
            if option_type == "revise_current_scene":
                return ("recommended", 1, "", "", [])
            if option_type in {"complete_prior_story", "mark_as_claim_or_misinformation", "keep_open_or_defer"}:
                return ("available", 0, "", "", ["no_direct_relationship_write"])
            return _blocked("M6 cannot directly write relationship state from this option.")
        if option_type == "revise_current_scene":
            return ("recommended", 1, "", "", [])
        if option_type in {"mark_as_claim_or_misinformation", "keep_open_or_defer"}:
            return ("available", 0, "", "", [])
        if option_type == "complete_prior_story" and missing_source:
            return ("available", 0, "", "", ["conditional_missing_source"])
        return (
            "advanced_gated",
            0,
            "This option is visible for governance but not executable for this issue in M6.",
            "Advanced option requires a verified safe path.",
            [],
        )

    def _required_fields(self, option_type: str) -> list[str]:
        if option_type == "revise_current_scene":
            return ["revision_prompt"]
        if option_type in {
            "complete_prior_story",
            "mark_as_claim_or_misinformation",
            "mark_as_perception_or_hallucination",
            "mark_as_apparent_contradiction",
            "create_or_update_narrative_debt",
        }:
            return ["user_input"]
        return []


class ContinuityResolutionOptionExecutionService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        continuity_gate_service: ContinuityGateService | None = None,
        issue_resolution_service: IssueResolutionService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.continuity_gate_service = continuity_gate_service or ContinuityGateService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.issue_resolution_service = issue_resolution_service or IssueResolutionService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
            continuity_gate_service=self.continuity_gate_service,
        )
        self.refresh_service = ContinuityResolutionRefreshService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.availability_service = ContinuityResolutionOptionAvailabilityService()
        self.authority_guard = ContinuityResolutionAuthorityGuard()

    def matrix(self) -> dict[str, Any]:
        return self.availability_service.matrix()

    def report_for_issue_id(self, issue_id: str) -> ContinuityResolutionOptionAvailabilityReport:
        return self.availability_service.report_for_issue(self.continuity_gate_service.get_issue(issue_id))

    def execute(
        self,
        issue_id: str,
        request: ContinuityResolutionOptionExecutionRequest,
    ) -> ContinuityResolutionOptionExecutionResult:
        if request.option_type not in CONTINUITY_RESOLUTION_OPTION_TYPES:
            raise StorageError("CONTINUITY_RESOLUTION_OPTION_UNKNOWN: Unknown continuity resolution option.")
        issue = self.continuity_gate_service.get_issue(issue_id)
        if issue.status != "open":
            raise StorageError(
                "CONTINUITY_RESOLUTION_ISSUE_NOT_OPEN: Resolution options can only execute for open issues."
            )
        report = self.availability_service.report_for_issue(issue)
        option = _find_option(report.options, request.option_type)
        guard = self.authority_guard.check(issue, option)
        if not guard.allowed:
            raise StorageError(
                "CONTINUITY_RESOLUTION_OPTION_DISABLED: "
                + "; ".join(guard.blocked_reasons or ["option_not_executable"])
            )
        if request.option_type == "keep_open_or_defer":
            refresh = self.refresh_service.build_refresh_after_issue_action(
                action_type="keep_open_or_defer",
                action_status="kept_open",
                issue_id=issue.issue_id,
                affected_issue_ids=[issue.issue_id],
                recompute_quality_report=False,
            )
            return ContinuityResolutionOptionExecutionResult(
                option_type=request.option_type,
                issue_id=issue.issue_id,
                refresh=refresh,
                safe_summary="Issue kept open without fact writes.",
            )
        if request.option_type == "mark_as_claim_or_misinformation":
            return self._execute_claim_or_misinformation(issue, request)
        legacy_action = LEGACY_ACTION_BY_OPTION.get(request.option_type)
        if not legacy_action:
            raise StorageError("CONTINUITY_RESOLUTION_OPTION_DISABLED: Option is gated in M6 MVP.")
        return self._execute_legacy(issue, request, legacy_action)

    def _execute_legacy(
        self,
        issue: ContinuityIssue,
        request: ContinuityResolutionOptionExecutionRequest,
        legacy_action: str,
    ) -> ContinuityResolutionOptionExecutionResult:
        before = self._storage_counts()
        response = self.issue_resolution_service.resolve_issue(
            issue.issue_id,
            action_type=legacy_action,
            user_input=request.user_input,
            revision_prompt=request.revision_prompt,
            truth_status=request.truth_status,
        )
        after = self._storage_counts()
        if request.option_type == "complete_prior_story":
            self._assert_no_event_or_memory_write(before, after)
        candidate = response.get("candidate") or {}
        revision = response.get("scene_revision_response") or {}
        revision_candidate = revision.get("candidate") or revision.get("current_candidate") or {}
        return ContinuityResolutionOptionExecutionResult(
            option_type=request.option_type,
            issue_id=issue.issue_id,
            created_candidate_id=str(candidate.get("candidate_id") or ""),
            created_revision_id=str(revision_candidate.get("revision_id") or ""),
            decision_id=str((response.get("decision") or {}).get("decision_id") or ""),
            refresh=response.get("refresh"),
            safe_summary=self._summary_for(response, request.option_type),
            warnings=[],
            issue=response.get("issue"),
            candidate=candidate or None,
            decision=response.get("decision"),
            candidate_decision=response.get("candidate_decision"),
            write_plan=response.get("write_plan"),
            lineage=response.get("lineage"),
            scene_revision_response=revision or None,
        )

    def _execute_claim_or_misinformation(
        self,
        issue: ContinuityIssue,
        request: ContinuityResolutionOptionExecutionRequest,
    ) -> ContinuityResolutionOptionExecutionResult:
        before = self._storage_counts()
        response = self.issue_resolution_service.resolve_issue(
            issue.issue_id,
            action_type="mark_as_misinformation_or_lie",
            user_input=request.user_input,
            truth_status=request.truth_status or "misinformation",
        )
        after = self._storage_counts()
        if after["events"] != before["events"]:
            raise StorageError("CONTINUITY_RESOLUTION_OBJECTIVE_WRITE_BLOCKED: Claim path wrote objective Event.")
        memory = response.get("memory_record") or {}
        return ContinuityResolutionOptionExecutionResult(
            option_type=request.option_type,
            issue_id=issue.issue_id,
            created_claim_id=str(memory.get("memory_id") or ""),
            decision_id=str((response.get("decision") or {}).get("decision_id") or ""),
            refresh=response.get("refresh"),
            safe_summary="Recorded issue as non-objective claim/misinformation.",
            issue=response.get("issue"),
            decision=response.get("decision"),
            memory_record=memory or None,
        )

    def _storage_counts(self) -> dict[str, int]:
        return {
            "events": len(self.repositories.events.list_all()),
            "memory": len(self.repositories.memory.list_all()),
            "scenes": len(self.repositories.scenes.list_all()),
            "relationships": len(self.repositories.relationships.list_all()),
        }

    def _assert_no_event_or_memory_write(
        self,
        before: dict[str, int],
        after: dict[str, int],
    ) -> None:
        if after["events"] != before["events"] or after["memory"] != before["memory"]:
            raise StorageError(
                "CONTINUITY_RESOLUTION_OBJECTIVE_WRITE_BLOCKED: Candidate creation wrote Event or MemoryRecord."
            )

    def _summary_for(self, response: dict[str, Any], option_type: str) -> str:
        refresh = response.get("refresh") or {}
        if isinstance(refresh, dict) and refresh.get("safe_summary"):
            return str(refresh.get("safe_summary") or "")
        if option_type == "complete_prior_story":
            return "Created governed prior-story completion candidate."
        if option_type == "revise_current_scene":
            return "Created scene revision candidate."
        return "Continuity resolution option executed."


def _blocked(reason: str) -> tuple[str, int, str, str, list[str]]:
    return ("blocked", 0, reason, reason, [])


def _find_option(
    options: list[ContinuityResolutionOptionAvailability],
    option_type: str,
) -> ContinuityResolutionOptionAvailability:
    for option in options:
        if option.option_type == option_type:
            return option
    raise StorageError("CONTINUITY_RESOLUTION_OPTION_UNKNOWN: Unknown continuity resolution option.")


def _mentions_missing_source(issue: ContinuityIssue) -> bool:
    text = " ".join(
        [
            issue.category,
            issue.user_visible_message,
            issue.technical_summary,
            issue.evidence_text,
        ]
    ).casefold()
    markers = [
        "missing source",
        "no source",
        "source fact",
        "prior story",
        "prior source",
        "prior fact",
        "unverified prior",
    ]
    return any(marker in text for marker in markers)


def _unique_strings(values: list[str]) -> list[str]:
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
