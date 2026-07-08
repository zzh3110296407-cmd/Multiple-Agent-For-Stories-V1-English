from __future__ import annotations

from app.backend.models.writer_prose_engine import (
    CharacterMovePlan,
    ConflictTurnPlan,
    InformationControlPlan,
    PacingPlan,
    SceneProsePlan,
    SceneProsePlanValidationReport,
)


class SceneProsePlanService:
    def validate_plan(self, plan: SceneProsePlan) -> SceneProsePlanValidationReport:
        issue_codes: list[str] = []
        warning_codes: list[str] = []
        issues: list[str] = []
        warnings: list[str] = []

        def add_issue(code: str, message: str) -> None:
            if code not in issue_codes:
                issue_codes.append(code)
                issues.append(message)

        def add_warning(code: str, message: str) -> None:
            if code not in warning_codes:
                warning_codes.append(code)
                warnings.append(message)

        if not plan.scene_purpose.strip():
            add_issue("scene_purpose_missing", "SceneProsePlan.scene_purpose is required.")
        if not plan.reader_value.strip():
            add_issue("reader_value_missing", "SceneProsePlan.reader_value is required.")
        if not plan.conflict_turn or not plan.conflict_turn.is_valid():
            add_issue("conflict_turn_missing", "SceneProsePlan.conflict_turn must include trigger, pressure, turn, and outcome.")
        if not plan.opening_hook.strip():
            add_issue("opening_hook_missing", "SceneProsePlan.opening_hook is required.")
        if not plan.ending_pull.strip():
            add_issue("ending_pull_missing", "SceneProsePlan.ending_pull is required.")

        deltas = [
            plan.new_information,
            plan.character_state_delta,
            plan.relationship_delta,
            plan.cost_or_risk_delta,
        ]
        if not any(str(delta or "").strip() for delta in deltas):
            add_issue("scene_delta_missing", "SceneProsePlan requires at least one scene delta.")

        if plan.scene_index >= 2:
            if not (plan.previous_scene_summary.strip() or plan.previous_scene_pattern.strip()):
                add_issue("previous_scene_context_missing", "Scene 2+ plans require previous scene context.")
            if not plan.difference_from_previous_scene.strip():
                add_issue("difference_from_previous_scene_missing", "Scene 2+ plans require difference_from_previous_scene.")

        if not plan.character_moves or not any(move.is_meaningful() for move in plan.character_moves):
            add_warning("character_moves_missing", "M1 allows empty character moves as a warning; M3 will enforce concrete moves.")

        if not plan.source_chapter_scene_beat_id.strip():
            if not plan.source_chapter_scene_beat_fallback:
                add_issue("chapter_scene_beat_fallback_unmarked", "Missing chapter scene beat requires explicit fallback.")
            elif not plan.source_chapter_scene_beat_fallback_reason.strip():
                add_issue("chapter_scene_beat_fallback_unmarked", "Chapter scene beat fallback requires a reason.")
            else:
                add_warning("chapter_scene_beat_fallback_used", "Old-project chapter scene beat fallback is explicit.")

        candidate_only_boundary_enforced = (
            plan.candidate_only is True
            and plan.can_write_scene_prose_directly is False
            and plan.can_write_story_facts_directly is False
        )
        if not candidate_only_boundary_enforced:
            add_issue("direct_write_capability_forbidden", "SceneProsePlan cannot write prose or story facts directly.")

        return SceneProsePlanValidationReport(
            scene_prose_plan_id=plan.scene_prose_plan_id,
            passed=not issue_codes,
            issue_codes=issue_codes,
            warning_codes=warning_codes,
            issues=issues,
            warnings=warnings,
            candidate_only_boundary_enforced=candidate_only_boundary_enforced,
            no_direct_story_write_fields=candidate_only_boundary_enforced,
            source_chapter_scene_beat_fallback_used=plan.source_chapter_scene_beat_fallback,
        )

    def build_valid_scene_one_plan(self) -> SceneProsePlan:
        return SceneProsePlan(
            scene_prose_plan_id="scene_prose_plan_scene_001",
            project_id="project_m1",
            chapter_id="chapter_001",
            scene_id="scene_001",
            scene_index=1,
            source_chapter_scene_beat_id="chapter_001_scene_001_beat",
            scene_purpose="Open the chapter problem through a visible test of the premise.",
            reader_value="Give the reader a concrete question and a practical first clue.",
            must_change_by_end="The team moves from curiosity to an actionable lead.",
            opening_hook="The first clue arrives in a form the protagonist cannot ignore.",
            ending_pull="End with the lead pointing to a harder second location.",
            conflict_turn=ConflictTurnPlan(
                turn_trigger="The first clue contradicts the expected route.",
                pressure_source="A public deadline forces immediate action.",
                turn="The protagonist must test the clue instead of discussing it.",
                outcome="The scene ends with proof that the clue is useful but costly.",
            ),
            new_information="The clue identifies a hidden constraint in the chapter problem.",
            character_state_delta="The protagonist becomes willing to act before complete certainty.",
            character_moves=[
                CharacterMovePlan(
                    character_id="char_a",
                    intended_move="Test the clue.",
                    visible_action="Opens the sealed case and compares the mark.",
                    scene_effect="The practical lead becomes usable.",
                )
            ],
            information_control=InformationControlPlan(
                reveal="The clue is real.",
                withhold="Who planted it.",
                reader_question="Why was this clue left now?",
            ),
            pacing=PacingPlan(
                opening_pressure="Immediate practical interruption.",
                escalation="Contradictory evidence forces a test.",
                release_or_turn="The test works but raises cost.",
            ),
            forbidden_repetition_patterns=["static discussion opening"],
            required_prompt_terms=["clue", "deadline"],
            required_memory_refs=["memory_chapter_context"],
            source_refs=["chapter_scene_beat:chapter_001_scene_001_beat"],
        )

    def build_valid_scene_two_plan(self) -> SceneProsePlan:
        plan = self.build_valid_scene_one_plan().model_copy(
            update={
                "scene_prose_plan_id": "scene_prose_plan_scene_002",
                "scene_id": "scene_002",
                "scene_index": 2,
                "source_chapter_scene_beat_id": "chapter_001_scene_002_beat",
                "previous_scene_summary": "Scene 1 proved the first clue was useful but costly.",
                "previous_scene_pattern": "test clue under deadline",
                "scene_purpose": "Escalate the practical lead into a contested choice.",
                "reader_value": "Show a new pressure that makes the earlier clue less simple.",
                "must_change_by_end": "The lead becomes tied to a relationship risk.",
                "difference_from_previous_scene": "This scene shifts from testing a clue to choosing who must pay the cost.",
                "opening_hook": "The second location is already being searched by someone else.",
                "ending_pull": "End with the protagonist choosing a riskier route.",
                "new_information": "The second location links the clue to a known ally.",
                "relationship_delta": "Trust between the protagonist and ally becomes conditional.",
                "source_refs": ["chapter_scene_beat:chapter_001_scene_002_beat"],
            }
        )
        return plan

    def build_old_project_fallback_plan(self) -> SceneProsePlan:
        plan = self.build_valid_scene_one_plan().model_copy(
            update={
                "scene_prose_plan_id": "scene_prose_plan_fallback_old_project",
                "source_chapter_scene_beat_id": "",
                "source_chapter_scene_beat_fallback": True,
                "source_chapter_scene_beat_fallback_reason": "Legacy project predates chapter scene beat records.",
                "source_refs": ["legacy_project_without_chapter_scene_beats"],
            }
        )
        return plan
