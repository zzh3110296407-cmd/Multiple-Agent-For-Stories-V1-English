from __future__ import annotations

import re
from typing import Any

from app.backend.models.writer_prose_engine import (
    CharacterMovePlan,
    ConflictTurnPlan,
    InformationControlPlan,
    PacingPlan,
    SceneProsePlan,
    WRITER_PLANNER_SUB_AGENT_ORDER,
    WriterPlannerInputSnapshot,
    WriterPlannerLayerOutput,
    WriterPlannerLayerValidationReport,
    WriterPlannerSubAgentTrace,
)
from app.backend.services.beat_sheet_builder_service import BeatSheetBuilderService
from app.backend.services.psychology_visibility_planner_service import (
    PsychologyVisibilityPlannerService,
)
from app.backend.services.prompt_anchor_classification_service import extract_positive_prompt_terms
from app.backend.services.scene_prose_plan_service import SceneProsePlanService


class WriterPlannerLayerService:
    def __init__(
        self,
        *,
        scene_plan_service: SceneProsePlanService | None = None,
        psychology_service: PsychologyVisibilityPlannerService | None = None,
        beat_sheet_service: BeatSheetBuilderService | None = None,
    ) -> None:
        self.scene_plan_service = scene_plan_service or SceneProsePlanService()
        self.psychology_service = psychology_service or PsychologyVisibilityPlannerService()
        self.beat_sheet_service = beat_sheet_service or BeatSheetBuilderService()

    def build_fixture_input_snapshot(self) -> WriterPlannerInputSnapshot:
        return WriterPlannerInputSnapshot(
            project_id="project_m3",
            chapter_id="chapter_001",
            scene_id="scene_002",
            scene_index=2,
            style_profile_id="web_serial_clear_plot",
            scene_writing_context_summary="The team has proved the first clue works but has not paid the full cost.",
            scene_progression_statement="Turn the usable clue into a contested choice.",
            chapter_scene_beat_id="chapter_001_scene_002_beat",
            required_progression_delta="The lead becomes tied to an ally's risk.",
            previous_scene_summary="Scene 1 proved the first clue was useful but costly.",
            previous_scene_pattern="test clue under deadline",
            previous_ending_pull="End with the lead pointing to a harder second location.",
            active_character_ids=["char_a", "char_b", "char_c", "char_d"],
            active_character_tiers={
                "char_a": "A",
                "char_b": "B",
                "char_c": "C",
                "char_d": "D",
            },
            writer_abcd_context_view_id="writer_view_m3",
            abcd_story_information_package_id="abcd_package_m3",
            memory_context_refs=["memory_scene_001_clue_cost"],
            character_intent_refs=["intent_char_a_test", "intent_char_b_warn"],
            prompt_terms=["clue", "ally", "risk"],
            source_refs=[
                "chapter_scene_beat:chapter_001_scene_002_beat",
                "scene_summary:scene_001",
            ],
        )

    def build_input_snapshot_from_writer_inputs(
        self,
        *,
        request: Any,
        package: Any,
        writer_view: Any,
        items: list[Any],
    ) -> WriterPlannerInputSnapshot:
        text_pool = [
            *getattr(writer_view, "opening_context", []),
            *getattr(writer_view, "scene_progression", []),
            *getattr(writer_view, "required_reveals", []),
            *getattr(writer_view, "character_turns", []),
            *getattr(writer_view, "ending_beat", []),
            getattr(writer_view, "safe_summary", ""),
            getattr(package, "safe_summary", ""),
            *[
                getattr(item, "writer_instruction", "")
                or getattr(getattr(item, "base_story_information_item", None), "content", "")
                for item in items
            ],
        ]
        progression = _first_non_empty(
            [
                *getattr(writer_view, "scene_progression", []),
                *getattr(writer_view, "required_reveals", []),
                getattr(package, "safe_summary", ""),
            ],
            "Advance the approved scene progression through visible action.",
        )
        writer_ready_texts = [
            getattr(item, "writer_instruction", "")
            or getattr(getattr(item, "base_story_information_item", None), "content", "")
            for item in items
            if getattr(item, "writer_bucket", "") in {"scene_progression", "character_turns"}
        ]
        combined_writer_ready_text = " ".join(
            str(text or "").strip() for text in writer_ready_texts[:4] if str(text or "").strip()
        )
        required_delta = _first_non_empty(
            [
                combined_writer_ready_text,
                *getattr(writer_view, "required_reveals", []),
                *getattr(writer_view, "scene_progression", []),
            ],
            progression,
        )
        active_character_ids = list(getattr(package, "active_character_ids", []) or [])
        tiers: dict[str, str] = {}
        for item in items:
            character_id = str(getattr(item, "character_id", "") or "").strip()
            tier = str(getattr(item, "tier", "") or "").strip().upper()
            if character_id and tier:
                tiers[character_id] = tier
        for character_id in active_character_ids:
            tiers.setdefault(character_id, "D")
        return WriterPlannerInputSnapshot(
            project_id=getattr(request, "project_id", "") or getattr(package, "project_id", ""),
            chapter_id=getattr(request, "chapter_id", "") or getattr(package, "chapter_id", ""),
            scene_id=getattr(request, "scene_id", "") or getattr(package, "scene_id", ""),
            scene_index=int(getattr(request, "scene_index", 0) or getattr(package, "scene_index", 1) or 1),
            style_profile_id="web_serial_clear_plot",
            scene_writing_context_summary=_first_non_empty(
                [*getattr(writer_view, "opening_context", []), getattr(writer_view, "safe_summary", "")],
                "The approved participants enter the scene with a concrete problem.",
            ),
            scene_progression_statement=progression,
            chapter_scene_beat_id=f"live_writer_beat_{getattr(package, 'abcd_story_information_package_id', 'package')}",
            required_progression_delta=required_delta,
            previous_scene_summary=_first_non_empty(
                getattr(writer_view, "opening_context", []),
                "Previous scene context is carried only as approved writer context.",
            ),
            previous_scene_pattern=_first_non_empty(
                getattr(writer_view, "guardrails", []),
                "avoid repeating the prior scene pattern",
            ),
            previous_ending_pull="Previous scene ended before this live writer request.",
            active_character_ids=active_character_ids,
            active_character_tiers=tiers,
            writer_abcd_context_view_id=getattr(writer_view, "writer_view_id", ""),
            abcd_story_information_package_id=getattr(package, "abcd_story_information_package_id", ""),
            memory_context_refs=[
                ref
                for ref in [
                    getattr(package, "source_scene_memory_pack_id", ""),
                    getattr(package, "source_tiered_character_context_package_id", ""),
                ]
                if ref
            ],
            character_intent_refs=[
                ref
                for ref in [
                    getattr(item, "source_action_intention_candidate_id", "") or getattr(item, "item_id", "")
                    for item in items
                ]
                if ref
            ],
            prompt_terms=_extract_prompt_terms(" ".join(str(text or "") for text in text_pool)),
            source_refs=[
                getattr(package, "abcd_story_information_package_id", ""),
                getattr(writer_view, "writer_view_id", ""),
                *[getattr(item, "item_id", "") for item in items],
            ],
        )

    def build_scene_prose_plan(self, snapshot: WriterPlannerInputSnapshot) -> SceneProsePlan:
        progression = _first_non_empty(
            [snapshot.scene_progression_statement, snapshot.required_progression_delta],
            "Advance the scene through a visible choice.",
        )
        delta = _first_non_empty(
            [snapshot.required_progression_delta, snapshot.scene_progression_statement],
            "The scene changes through the approved action.",
        )
        opening_hook = _first_non_empty(
            [snapshot.scene_writing_context_summary, progression],
            "A concrete problem is already in motion.",
        )
        ending_pull = f"End by making the next step concrete: {delta}"
        if " ".join(ending_pull.casefold().split()) == " ".join(snapshot.previous_ending_pull.casefold().split()):
            ending_pull = f"End by forcing a different next choice around {delta}"
        active_ids = snapshot.active_character_ids or ["active_participant"]
        primary_id = active_ids[0]
        secondary_id = active_ids[1] if len(active_ids) > 1 else active_ids[0]
        return SceneProsePlan(
            scene_prose_plan_id=f"scene_prose_plan_{snapshot.scene_id}",
            project_id=snapshot.project_id,
            chapter_id=snapshot.chapter_id,
            scene_id=snapshot.scene_id,
            scene_index=snapshot.scene_index,
            style_profile_id=snapshot.style_profile_id,
            source_chapter_scene_beat_id=snapshot.chapter_scene_beat_id,
            previous_scene_summary=snapshot.previous_scene_summary,
            previous_scene_pattern=snapshot.previous_scene_pattern,
            scene_purpose=f"Move the scene through this approved progression: {progression}",
            reader_value=f"Show concrete movement around this change: {delta}",
            must_change_by_end=snapshot.required_progression_delta,
            difference_from_previous_scene=f"This scene changes the prior pattern by acting on: {delta}",
            opening_hook=opening_hook,
            ending_pull=ending_pull,
            conflict_turn=ConflictTurnPlan(
                turn_trigger=progression,
                pressure_source=f"The approved context makes delay costly: {delta}",
                turn=f"A participant must choose how to act on {delta}",
                outcome=f"The scene ends with the situation changed by {delta}",
            ),
            new_information=snapshot.required_progression_delta,
            character_state_delta=f"{primary_id} moves from intention to visible action.",
            relationship_delta=f"{secondary_id} has to respond to the changed pressure.",
            cost_or_risk_delta=f"The next action now carries a concrete cost: {delta}",
            character_moves=[
                CharacterMovePlan(
                    character_id=primary_id,
                    intended_move=f"Act on {delta}",
                    visible_action=f"Moves the scene toward {delta}",
                    scene_effect=f"The group can no longer avoid {delta}",
                ),
                CharacterMovePlan(
                    character_id=secondary_id,
                    intended_move="Force the choice to become explicit.",
                    visible_action="Blocks the easy route long enough to demand a decision.",
                    scene_effect="The conflict turn becomes a visible choice.",
                ),
            ],
            information_control=InformationControlPlan(
                reveal=snapshot.required_progression_delta,
                withhold="The full consequence of the choice.",
                reader_question=f"What will {delta} cost next?",
                source_refs=["chapter_scene_beat:chapter_001_scene_002_beat:required_progression_delta"],
            ),
            pacing=PacingPlan(
                opening_pressure=opening_hook,
                escalation=f"Escalate through {delta}",
                release_or_turn=ending_pull,
            ),
            forbidden_repetition_patterns=[snapshot.previous_scene_pattern],
            required_prompt_terms=snapshot.prompt_terms,
            required_memory_refs=snapshot.memory_context_refs,
            source_refs=[
                *snapshot.source_refs,
                f"chapter_scene_beat:{snapshot.chapter_scene_beat_id}:required_progression_delta",
            ],
        )

    def build_logical_sub_agent_traces(
        self,
        snapshot: WriterPlannerInputSnapshot,
    ) -> list[WriterPlannerSubAgentTrace]:
        contributions = {
            "ScenePurposePlanner": ["scene_purpose", "must_change_by_end"],
            "ReaderHookPlanner": ["opening_hook", "ending_pull"],
            "ConflictTurnPlanner": ["conflict_turn", "cost_or_risk_delta"],
            "CharacterMovePlanner": ["character_moves", "character_state_delta"],
            "InformationReleasePlanner": ["new_information", "information_control"],
            "PsychologyVisibilityPlanner": ["psychology_visibility_plan"],
            "PacingPlanner": ["pacing", "difference_from_previous_scene"],
            "BeatSheetBuilder": ["beat_sheet"],
        }
        return [
            WriterPlannerSubAgentTrace(
                step_index=index,
                sub_agent_name=name,
                contributed_fields=contributions[name],
                source_refs=[f"writer_planner_input:{snapshot.scene_id}:{name}"],
                safe_summary=f"{name} contributed {', '.join(contributions[name])}.",
            )
            for index, name in enumerate(WRITER_PLANNER_SUB_AGENT_ORDER, start=1)
        ]

    def build_planner_output(
        self,
        snapshot: WriterPlannerInputSnapshot | None = None,
    ) -> WriterPlannerLayerOutput:
        input_snapshot = snapshot or self.build_fixture_input_snapshot()
        scene_prose_plan = self.build_scene_prose_plan(input_snapshot)
        psychology_plan, _negative_spaces = self.psychology_service.build_fixture_plan()
        psychology_plan = psychology_plan.model_copy(
            update={
                "psychology_visibility_plan_id": f"psych_visibility_plan_{input_snapshot.scene_id}",
                "project_id": input_snapshot.project_id,
                "chapter_id": input_snapshot.chapter_id,
                "scene_id": input_snapshot.scene_id,
                "scene_index": input_snapshot.scene_index,
                "source_scene_prose_plan_id": scene_prose_plan.scene_prose_plan_id,
                "source_context_refs": input_snapshot.source_refs,
            }
        )
        updated_decisions = []
        for decision in psychology_plan.decisions:
            updated_decisions.append(
                decision.model_copy(
                    update={
                        "project_id": input_snapshot.project_id,
                        "chapter_id": input_snapshot.chapter_id,
                        "scene_id": input_snapshot.scene_id,
                        "scene_index": input_snapshot.scene_index,
                    }
                )
            )
        psychology_plan = psychology_plan.model_copy(update={"decisions": updated_decisions})
        beat_sheet = self.beat_sheet_service.build_beat_sheet(
            scene_prose_plan=scene_prose_plan,
            psychology_visibility_plan=psychology_plan,
        )
        traces = self.build_logical_sub_agent_traces(input_snapshot)
        return WriterPlannerLayerOutput(
            planner_output_id=f"writer_planner_output_{input_snapshot.scene_id}",
            project_id=input_snapshot.project_id,
            chapter_id=input_snapshot.chapter_id,
            scene_id=input_snapshot.scene_id,
            scene_index=input_snapshot.scene_index,
            input_snapshot=input_snapshot,
            scene_prose_plan=scene_prose_plan,
            psychology_visibility_plan=psychology_plan,
            beat_sheet=beat_sheet,
            logical_sub_agent_traces=traces,
            required_progression_delta_mapped=self.required_progression_delta_mapped(
                input_snapshot, scene_prose_plan
            ),
            ending_pull_differs_from_previous=self.ending_pull_differs_from_previous(
                input_snapshot, scene_prose_plan
            ),
        )

    def validate_planner_output(
        self,
        output: WriterPlannerLayerOutput,
    ) -> WriterPlannerLayerValidationReport:
        issue_codes: list[str] = []
        warning_codes: list[str] = []
        issues: list[str] = []
        warnings: list[str] = []

        def add_issue(code: str, message: str) -> None:
            if code not in issue_codes:
                issue_codes.append(code)
                issues.append(message)

        scene_report = self.scene_plan_service.validate_plan(output.scene_prose_plan)
        if not scene_report.passed:
            issue_codes.extend(scene_report.issue_codes)
            issues.extend(scene_report.issues)
        psychology_report = self.psychology_service.validate_plan(output.psychology_visibility_plan)
        if not psychology_report.passed:
            issue_codes.extend(psychology_report.issue_codes)
            issues.extend(psychology_report.issues)
        beat_report = self.beat_sheet_service.validate_beat_sheet(output.beat_sheet)
        if not beat_report["passed"]:
            issue_codes.extend(str(code) for code in beat_report["issue_codes"])

        if output.scene_index >= 2:
            if not (output.scene_prose_plan.previous_scene_summary or output.scene_prose_plan.previous_scene_pattern):
                add_issue("previous_scene_context_missing", "Scene 2+ requires previous scene context.")
            if not output.scene_prose_plan.difference_from_previous_scene:
                add_issue("difference_from_previous_scene_missing", "Scene 2+ requires a difference from previous scene.")
            if not output.ending_pull_differs_from_previous:
                add_issue("ending_pull_repeated", "Ending pull must differ from previous scene.")
        if not any(move.is_meaningful() for move in output.scene_prose_plan.character_moves):
            add_issue("character_move_missing", "Planner output requires at least one meaningful character move.")
        if not output.scene_prose_plan.opening_hook:
            add_issue("opening_hook_missing", "Opening hook is required.")
        if not output.scene_prose_plan.conflict_turn or not output.scene_prose_plan.conflict_turn.is_valid():
            add_issue("conflict_turn_missing", "Conflict turn is required.")
        if not output.scene_prose_plan.ending_pull:
            add_issue("ending_pull_missing", "Ending pull is required.")
        if not output.required_progression_delta_mapped:
            add_issue("required_progression_delta_unmapped", "Required progression delta was not mapped.")

        trace_order_valid = self.logical_trace_order_valid(output.logical_sub_agent_traces)
        if not trace_order_valid:
            names = [trace.sub_agent_name for trace in output.logical_sub_agent_traces]
            if len(names) != len(WRITER_PLANNER_SUB_AGENT_ORDER):
                add_issue("logical_sub_agent_trace_missing", "Every logical sub-agent trace is required.")
            else:
                add_issue("logical_sub_agent_trace_order_invalid", "Logical sub-agent trace order is invalid.")

        candidate_only_boundary_enforced = (
            output.candidate_only is True
            and output.can_write_scene_prose_directly is False
            and output.can_write_story_facts_directly is False
            and output.beat_sheet.candidate_only is True
            and output.scene_prose_plan.candidate_only is True
            and output.psychology_visibility_plan.candidate_only is True
        )
        if not candidate_only_boundary_enforced:
            add_issue("direct_write_capability_forbidden", "Planner output cannot write prose or facts directly.")

        no_direct_story_write_fields = candidate_only_boundary_enforced
        issue_codes = sorted(set(issue_codes))
        return WriterPlannerLayerValidationReport(
            planner_output_id=output.planner_output_id,
            passed=not issue_codes,
            issue_codes=issue_codes,
            warning_codes=sorted(set(warning_codes)),
            issues=issues,
            warnings=warnings,
            beat_sheet_passed=bool(beat_report["passed"]),
            logical_sub_agent_trace_order_valid=trace_order_valid,
            candidate_only_boundary_enforced=candidate_only_boundary_enforced,
            no_direct_story_write_fields=no_direct_story_write_fields,
        )

    def required_progression_delta_mapped(
        self,
        snapshot: WriterPlannerInputSnapshot,
        scene_prose_plan: SceneProsePlan,
    ) -> bool:
        delta = snapshot.required_progression_delta.strip()
        if not delta:
            return False
        text = " ".join(
            [
                scene_prose_plan.must_change_by_end,
                scene_prose_plan.new_information,
                scene_prose_plan.character_state_delta,
                scene_prose_plan.relationship_delta,
                scene_prose_plan.cost_or_risk_delta,
                " ".join(scene_prose_plan.source_refs),
            ]
        )
        return delta in text and f"chapter_scene_beat:{snapshot.chapter_scene_beat_id}:required_progression_delta" in scene_prose_plan.source_refs

    def ending_pull_differs_from_previous(
        self,
        snapshot: WriterPlannerInputSnapshot,
        scene_prose_plan: SceneProsePlan,
    ) -> bool:
        previous = " ".join(snapshot.previous_ending_pull.casefold().split())
        current = " ".join(scene_prose_plan.ending_pull.casefold().split())
        return bool(current and current != previous)

    def logical_trace_order_valid(self, traces: list[WriterPlannerSubAgentTrace]) -> bool:
        names = [trace.sub_agent_name for trace in sorted(traces, key=lambda item: item.step_index)]
        return names == WRITER_PLANNER_SUB_AGENT_ORDER


def _first_non_empty(values: list[Any], fallback: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return " ".join(text.split())
    return fallback


def _extract_prompt_terms(text: str) -> list[str]:
    terms = extract_positive_prompt_terms(text, limit=4)
    if terms:
        return terms
    internal_terms = {
        "candidate",
        "constraint",
        "context",
        "diagnostic",
        "evidence",
        "consistent",
        "quality",
        "tentative",
        "behavior",
        "cautious",
        "claim",
        "directly",
        "rather",
        "subjective",
        "interpretation",
        "present",
        "objective",
        "source",
        "internal",
        "prompt",
        "writer",
        "memory",
        "package",
        "fiction",
        "hint",
        "keep",
        "only",
    }
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z'-]*", str(text or ""))
        if len(word) >= 4 and not word.casefold().startswith(("char", "scene", "chapter", "project"))
        and word.casefold() not in internal_terms
    ]
    result: list[str] = []
    seen: set[str] = set()
    for word in words:
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(word)
        if len(result) >= 4:
            break
    return result or ["choice", "pressure"]
