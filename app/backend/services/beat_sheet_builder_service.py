from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    Beat,
    BeatSheet,
    PsychologyVisibilityPlan,
    SceneProsePlan,
    WRITER_PLANNER_BEAT_TYPES,
)


class BeatSheetBuilderService:
    def build_beat_sheet(
        self,
        *,
        scene_prose_plan: SceneProsePlan,
        psychology_visibility_plan: PsychologyVisibilityPlan,
    ) -> BeatSheet:
        character_ids = [move.character_id for move in scene_prose_plan.character_moves if move.character_id]
        visibility_levels = [
            decision.visibility_level
            for decision in psychology_visibility_plan.decisions
            if decision.visibility_level
        ]
        beats = [
            Beat(
                beat_index=1,
                beat_type="opening_hook",
                purpose=scene_prose_plan.opening_hook,
                required_action="Open with the concrete situation implied by the hook.",
                allowed_psychology_visibility=visibility_levels,
                source_character_ids=character_ids,
                source_plan_field="opening_hook",
                source_refs=[f"scene_prose_plan:{scene_prose_plan.scene_prose_plan_id}:opening_hook"],
            ),
            Beat(
                beat_index=2,
                beat_type="character_move",
                purpose="Make a participant change the scene state through visible action.",
                required_action=scene_prose_plan.character_moves[0].visible_action
                if scene_prose_plan.character_moves
                else "",
                required_reveal_or_decision=scene_prose_plan.character_moves[0].scene_effect
                if scene_prose_plan.character_moves
                else "",
                allowed_psychology_visibility=visibility_levels,
                source_character_ids=character_ids,
                source_plan_field="character_moves",
                source_refs=[f"scene_prose_plan:{scene_prose_plan.scene_prose_plan_id}:character_moves"],
            ),
            Beat(
                beat_index=3,
                beat_type="conflict_turn",
                purpose=scene_prose_plan.conflict_turn.turn,
                required_action=scene_prose_plan.conflict_turn.pressure_source,
                required_reveal_or_decision=scene_prose_plan.conflict_turn.outcome,
                allowed_psychology_visibility=visibility_levels,
                source_character_ids=character_ids,
                source_plan_field="conflict_turn",
                source_refs=[f"scene_prose_plan:{scene_prose_plan.scene_prose_plan_id}:conflict_turn"],
            ),
            Beat(
                beat_index=4,
                beat_type="information_release",
                purpose="Control what the reader learns and what remains withheld.",
                required_reveal_or_decision=scene_prose_plan.new_information
                or scene_prose_plan.information_control.reveal,
                allowed_psychology_visibility=visibility_levels,
                source_character_ids=character_ids,
                source_plan_field="new_information",
                source_refs=[f"scene_prose_plan:{scene_prose_plan.scene_prose_plan_id}:new_information"],
            ),
            Beat(
                beat_index=5,
                beat_type="ending_pull",
                purpose=scene_prose_plan.ending_pull,
                required_reveal_or_decision="End by turning the reader toward the next scene.",
                allowed_psychology_visibility=visibility_levels,
                source_character_ids=character_ids,
                source_plan_field="ending_pull",
                source_refs=[f"scene_prose_plan:{scene_prose_plan.scene_prose_plan_id}:ending_pull"],
            ),
        ]
        return BeatSheet(
            beat_sheet_id=f"beat_sheet_{scene_prose_plan.scene_id}",
            project_id=scene_prose_plan.project_id,
            chapter_id=scene_prose_plan.chapter_id,
            scene_id=scene_prose_plan.scene_id,
            scene_index=scene_prose_plan.scene_index,
            source_scene_prose_plan_id=scene_prose_plan.scene_prose_plan_id,
            source_psychology_visibility_plan_id=psychology_visibility_plan.psychology_visibility_plan_id,
            beats=beats,
            required_beat_types=["opening_hook", "character_move", "conflict_turn", "ending_pull"],
        )

    def validate_beat_sheet(self, beat_sheet: BeatSheet) -> dict[str, object]:
        issue_codes: list[str] = []
        warnings: list[str] = []

        def add_issue(code: str) -> None:
            if code not in issue_codes:
                issue_codes.append(code)

        if not beat_sheet.beat_sheet_id.strip():
            add_issue("beat_sheet_id_missing")
        if not beat_sheet.source_scene_prose_plan_id.strip():
            add_issue("beat_sheet_plan_link_missing")
        if not beat_sheet.beats:
            add_issue("beat_sheet_required_beat_missing")

        indexes = [beat.beat_index for beat in beat_sheet.beats]
        expected_indexes = list(range(1, len(indexes) + 1))
        if indexes != expected_indexes:
            add_issue("beat_order_invalid")

        beat_types = {beat.beat_type for beat in beat_sheet.beats}
        required_present = set(beat_sheet.required_beat_types).issubset(beat_types)
        middle_present = bool({"obstacle", "character_move"} & beat_types)
        if not required_present or not middle_present:
            add_issue("beat_sheet_required_beat_missing")

        for beat in beat_sheet.beats:
            if beat.beat_type not in WRITER_PLANNER_BEAT_TYPES:
                add_issue("beat_type_invalid")
            if not beat.purpose.strip():
                add_issue("beat_purpose_missing")
            if not (
                beat.required_action.strip()
                or beat.required_reveal_or_decision.strip()
                or beat.source_plan_field.strip()
            ):
                add_issue("beat_not_actionable")

        candidate_only_boundary_enforced = (
            beat_sheet.candidate_only is True
            and beat_sheet.can_write_scene_prose_directly is False
            and beat_sheet.can_write_story_facts_directly is False
        )
        if not candidate_only_boundary_enforced:
            add_issue("direct_write_capability_forbidden")

        return {
            "passed": not issue_codes,
            "issue_codes": issue_codes,
            "warnings": warnings,
            "required_beat_types_present": "beat_sheet_required_beat_missing" not in issue_codes,
            "beat_indexes_contiguous": "beat_order_invalid" not in issue_codes,
            "beat_sheet_links_to_scene_prose_plan": "beat_sheet_plan_link_missing" not in issue_codes,
            "beats_are_actionable_or_reveal_bearing": "beat_not_actionable" not in issue_codes,
            "opening_hook_beat_present": "opening_hook" in beat_types,
            "conflict_turn_beat_present": "conflict_turn" in beat_types,
            "ending_pull_beat_present": "ending_pull" in beat_types,
            "candidate_only_boundary_enforced": candidate_only_boundary_enforced,
        }
