from __future__ import annotations

from typing import Any

from app.backend.models.writer_prose_engine import (
    DEFAULT_PROSE_STYLE_PROFILE_ID,
    ProseStyleProfile,
    PsychologyStylePolicy,
    SceneStylePolicy,
    SentenceStylePolicy,
    SuspenseStylePolicy,
)


class ProseStyleProfileService:
    def get_default_profile(self) -> ProseStyleProfile:
        return ProseStyleProfile(
            style_profile_id=DEFAULT_PROSE_STYLE_PROFILE_ID,
            label="clear plot-driven web-serial prose",
            language_density=0.48,
            adjective_budget=0.18,
            metaphor_budget=0.20,
            scene_drive=["action", "dialogue", "decision"],
            reader_hook_required=True,
            sentence_style=SentenceStylePolicy(
                plain_language_required=True,
                max_sentence_length_hint=28,
                sentence_variety_required=True,
                avoid_overloaded_clauses=True,
            ),
            scene_style=SceneStylePolicy(
                show_dont_explain=True,
                concrete_action_required=True,
                dialogue_or_decision_required=True,
                abstract_language_budget=0.24,
            ),
            suspense_style=SuspenseStylePolicy(
                concrete_evidence_required=True,
                reveal_or_question_required=True,
                empty_mystery_budget=0.18,
            ),
            psychology_policy=PsychologyStylePolicy(
                mode="subtext_first",
                behavior_first=True,
                direct_explanation_budget=0.22,
                interiority_requires_visible_trigger=True,
            ),
            limited_patterns=[
                "stacked abstract nouns",
                "empty mystery language",
                "adjective clusters",
                "metaphor chains",
                "static introspection",
            ],
            limited_patterns_are_density_hints=True,
        )

    def build_non_default_profile(self) -> ProseStyleProfile:
        profile = self.get_default_profile()
        return profile.model_copy(
            update={
                "style_profile_id": "lean_noir_test_profile",
                "label": "lean noir test profile",
                "language_density": 0.42,
                "adjective_budget": 0.14,
                "metaphor_budget": 0.16,
                "limited_patterns": [
                    "ornate weather openings",
                    "static interior explanation",
                ],
            }
        )

    def validate_profile(self, profile: ProseStyleProfile) -> dict[str, Any]:
        issues: list[str] = []
        warnings: list[str] = []

        if not profile.style_profile_id.strip():
            issues.append("style_profile_id_missing")
        if not profile.label.strip():
            issues.append("label_missing")

        density_fields = {
            "language_density": profile.language_density,
            "adjective_budget": profile.adjective_budget,
            "metaphor_budget": profile.metaphor_budget,
            "abstract_language_budget": profile.scene_style.abstract_language_budget,
            "empty_mystery_budget": profile.suspense_style.empty_mystery_budget,
            "direct_explanation_budget": profile.psychology_policy.direct_explanation_budget,
        }
        invalid_density_fields = [
            name for name, value in density_fields.items() if float(value) < 0 or float(value) > 1
        ]
        if invalid_density_fields:
            issues.append("density_threshold_out_of_range")

        if not profile.sentence_style.plain_language_required:
            issues.append("plain_language_policy_missing")
        if not {"action", "dialogue", "decision"}.issubset(set(profile.scene_drive)):
            issues.append("scene_drive_action_dialogue_decision_missing")
        if not profile.reader_hook_required:
            issues.append("reader_hook_not_required")
        if not profile.suspense_style.concrete_evidence_required:
            issues.append("concrete_suspense_policy_missing")
        if profile.psychology_policy.mode != "subtext_first":
            issues.append("psychology_subtext_first_missing")
        if not profile.limited_patterns_are_density_hints:
            issues.append("limited_patterns_must_be_density_hints")
        if not profile.limited_patterns:
            warnings.append("limited_patterns_empty")
        if len(profile.limited_patterns) != len({" ".join(item.casefold().split()) for item in profile.limited_patterns}):
            issues.append("limited_patterns_not_unique")

        return {
            "passed": not issues,
            "issues": issues,
            "warnings": warnings,
            "default_style_profile_id": profile.style_profile_id,
            "plain_language_constraints_present": profile.sentence_style.plain_language_required,
            "scene_drive_action_dialogue_decision": {"action", "dialogue", "decision"}.issubset(set(profile.scene_drive)),
            "reader_hook_required": profile.reader_hook_required,
            "density_thresholds_valid": not invalid_density_fields,
            "limited_patterns_are_density_hints": profile.limited_patterns_are_density_hints,
            "psychology_policy_subtext_first": profile.psychology_policy.mode == "subtext_first",
            "limited_patterns": profile.limited_patterns,
        }
