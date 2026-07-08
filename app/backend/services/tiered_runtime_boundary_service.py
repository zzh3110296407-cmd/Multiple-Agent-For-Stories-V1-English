import json
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.runtime_participation import TieredRuntimeBoundaryReport
from app.backend.services.abcd_runtime_participation_policy_service import now_utc


DEFAULT_INHERITED_CONTRACTS = [
    "ContinuityIssue lifecycle remains authoritative.",
    "Continuity resolution options remain backend-governed.",
    "QualityReport continuity fields must refresh after relevant actions.",
    "ProductProgressSummary remains a view model, not an authority source.",
    "Plugin outputs must not write back into source story facts.",
]


class TieredRuntimeBoundaryService:
    """Documents Phase 8.5-B M1 runtime authority boundaries."""

    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = docs_dir or settings.app_root / "docs"

    def build_report(self) -> TieredRuntimeBoundaryReport:
        return TieredRuntimeBoundaryReport(
            chapter_layer_allowed={
                "explicit_role_tiers": ["A", "B"],
                "c_d_allowed_only_as_function_needs": True,
                "c_d_detailed_context_forbidden": True,
                "may_write_story_facts": False,
            },
            scene_layer_allowed={
                "selectable_role_tiers": ["A", "B", "C", "D"],
                "scene_agent_must_explain_c_d_selection": True,
                "unselected_c_d_excluded_from_context": True,
                "must_pass_continuity_and_quality_gates": True,
            },
            memory_write_boundary={
                "future_boundary": "scene_commit_after_quality_and_continuity_gates",
                "d_tier_memory": "minimal_but_persistent",
                "claim_perception_auto_objective_event": False,
                "m1_writeback_enabled": False,
            },
            candidate_only_objects=[
                "character_psychology_trace",
                "character_action_intent",
                "character_behavior_expression",
                "scene_participation_package",
                "pre_commit_memory_write_plan",
            ],
            authority_objects=[
                "confirmed_scene",
                "confirmed_event",
                "confirmed_memory_record",
                "confirmed_character_state_change",
                "continuity_gate_decision",
                "user_confirmation_decision",
            ],
            view_model_objects=[
                "ProductProgressSummary",
                "NextRecommendedAction",
                "UserDecisionSurface",
                "BlockingIssueSurface",
                "PluginOutputArtifact",
            ],
            prohibited_runtime_shortcuts=[
                "psychology_or_action_intent_output_cannot_write_story_fact_directly",
                "character_behavior_expression_cannot_bypass_story_information_package",
                "claim_or_perception_cannot_auto_write_objective_event",
                "scene_agent_cannot_bypass_continuity_gate",
                "authorial_intent_agent_cannot_release_hard_rules",
                "major_state_changes_require_gate_or_user_confirmation",
                "product_progress_summary_is_not_authority_source",
                "plugin_output_artifact_has_no_source_story_writeback",
            ],
            inherited_phase85a_contracts=self._inherited_contracts(),
            safe_summary=(
                "M1 records candidate, authority, and view-model boundaries for later ABCD runtime work."
            ),
            created_at=now_utc(),
        )

    def _inherited_contracts(self) -> list[str]:
        path = self.docs_dir / "phase85b_m0_intake_report.json"
        if not path.exists():
            return list(DEFAULT_INHERITED_CONTRACTS)
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return list(DEFAULT_INHERITED_CONTRACTS)
        contracts = report.get("inherited_contracts")
        if not isinstance(contracts, list):
            return list(DEFAULT_INHERITED_CONTRACTS)
        return [str(item) for item in contracts if str(item).strip()] or list(
            DEFAULT_INHERITED_CONTRACTS
        )
