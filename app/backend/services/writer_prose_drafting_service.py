from __future__ import annotations

import re
from typing import Any

from app.backend.models.writer_prose_engine import (
    Beat,
    PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION,
    ProseStyleProfile,
    RenderedProseBeat,
    SubtextRenderingReport,
    WRITER_PROSE_DRAFTING_MODULE_ORDER,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
    WriterProseDraftingInput,
    WriterProseDraftingTrace,
    WriterProseDraftingValidationReport,
)
from app.backend.services.subtext_renderer_service import SubtextRendererService
from app.backend.services.writer_prose_metrics_service import WriterProseMetricsService


FORBIDDEN_PROSE_MARKERS = {
    "raw_psychology_chain",
    "hidden_reasoning",
    "internal reasoning",
    "provider raw",
    "traceback",
    "raw_prompt",
    "raw response",
    "diagnostic",
    "source_refs",
    "scene_prose_plan",
    "psychology_visibility_plan",
    "beat_sheet",
    "writer_planner_output",
}
JSON_MARKERS = {"{", "}", "\"beat_type\"", "\"source_refs\"", "\"candidate_prose\""}
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
DIALOGUE_MARKERS = {
    '"',
    " says",
    " asks",
    " answers",
    "decides",
    "chooses",
    "choice",
    "“",
    "”",
    "说",
    "问",
    "回答",
    "决定",
    "选择",
}
VISIBLE_ACTION_MARKERS = {
    "moves",
    "marks",
    "opens",
    "closes",
    "blocks",
    "reaches",
    "turns",
    "steps",
    "points",
    "holds",
    "answers",
    "chooses",
    "acts",
    "伸手",
    "行动",
    "移动",
    "走",
    "打开",
    "挡住",
    "指向",
    "握住",
    "回答",
    "选择",
    "决定",
    "处理",
    "跟进",
}


class WriterProseDraftingService:
    def __init__(
        self,
        *,
        subtext_renderer: SubtextRendererService | None = None,
        metrics_service: WriterProseMetricsService | None = None,
    ) -> None:
        self.subtext_renderer = subtext_renderer or SubtextRendererService()
        self.metrics_service = metrics_service or WriterProseMetricsService()

    def draft_from_planner_output(
        self,
        planner_output: WriterPlannerLayerOutput,
        *,
        do_not_use_texts: list[str] | None = None,
        used_story_information_item_ids: list[str] | None = None,
        ignored_do_not_use_item_ids: list[str] | None = None,
    ) -> WriterProseDraftPackage:
        drafting_input = self._build_input(planner_output, do_not_use_texts or [])
        language = self._language_for_output(planner_output)
        subtext_report = self.subtext_renderer.render(
            planner_output.psychology_visibility_plan,
            language=language,
        )
        rendered_beats = [
            self._render_beat(
                beat=beat,
                planner_output=planner_output,
                subtext_report=subtext_report,
                do_not_use_texts=do_not_use_texts or [],
                language=language,
            )
            for beat in sorted(planner_output.beat_sheet.beats, key=lambda item: item.beat_index)
        ]
        candidate_prose = "\n\n".join(
            beat.prose_segment for beat in rendered_beats if beat.prose_segment.strip()
        ).strip()
        candidate_synopsis = self._candidate_synopsis(planner_output)
        density = self.metrics_service.density_report(candidate_prose)
        used_prompt_terms = [
            term
            for term in planner_output.scene_prose_plan.required_prompt_terms
            if term and term.casefold() in candidate_prose.casefold()
        ]
        return WriterProseDraftPackage(
            draft_package_id=f"writer_prose_draft_package_{planner_output.scene_id}",
            project_id=planner_output.project_id,
            chapter_id=planner_output.chapter_id,
            scene_id=planner_output.scene_id,
            scene_index=planner_output.scene_index,
            source_planner_output_id=planner_output.planner_output_id,
            source_scene_prose_plan_id=planner_output.scene_prose_plan.scene_prose_plan_id,
            source_psychology_visibility_plan_id=(
                planner_output.psychology_visibility_plan.psychology_visibility_plan_id
            ),
            source_beat_sheet_id=planner_output.beat_sheet.beat_sheet_id,
            style_profile_id=planner_output.scene_prose_plan.style_profile_id,
            candidate_synopsis=candidate_synopsis,
            candidate_prose=candidate_prose,
            rendered_beats=rendered_beats,
            drafting_traces=self._drafting_traces(drafting_input),
            subtext_rendering_report=subtext_report,
            character_ids_present=self._character_ids_present(planner_output),
            required_prompt_terms_used=used_prompt_terms,
            used_story_information_item_ids=used_story_information_item_ids or [],
            ignored_do_not_use_item_ids=ignored_do_not_use_item_ids or [],
            required_progression_delta_reflected=self._progression_reflected(
                planner_output, candidate_prose
            ),
            opening_hook_reflected=self._text_reflected(
                planner_output.scene_prose_plan.opening_hook, candidate_prose
            ),
            conflict_turn_reflected=self._conflict_turn_reflected(
                planner_output,
                candidate_prose,
            ),
            ending_pull_reflected=self._text_reflected(
                planner_output.scene_prose_plan.ending_pull, candidate_prose
            ),
            visible_action_present=self._visible_action_present(candidate_prose),
            dialogue_or_decision_present=self._dialogue_or_decision_present(candidate_prose),
            psychology_visibility_applied=subtext_report.status == "passed"
            and bool(subtext_report.decisions),
            raw_psychology_chain_forbidden=not self._contains_forbidden_marker(candidate_prose),
            internal_json_forbidden=not self._contains_internal_json(candidate_prose),
            empty_mystery_density=density["empty_mystery_density"],
            abstract_language_density=density["abstract_language_density"],
            adjective_density=density["adjective_density"],
            candidate_only=True,
            can_write_scene_prose_directly=False,
            can_write_story_facts_directly=False,
            requires_post_draft_gate_review=True,
            version_id=PHASE85E_M4_WRITER_PROSE_DRAFTING_VERSION,
        )

    def validate_draft_package(
        self,
        package: WriterProseDraftPackage,
        *,
        source_planner_output: WriterPlannerLayerOutput | None = None,
    ) -> WriterProseDraftingValidationReport:
        issue_codes: list[str] = []
        warning_codes: list[str] = []
        issues: list[str] = []
        warnings: list[str] = []

        def add_issue(code: str, message: str) -> None:
            if code not in issue_codes:
                issue_codes.append(code)
                issues.append(message)

        if not package.candidate_prose.strip():
            add_issue("candidate_prose_missing", "Candidate prose is required.")
        if not package.rendered_beats:
            add_issue("rendered_beat_missing", "At least one rendered beat is required.")
        if not self._beat_order_reflected(package):
            add_issue("beat_order_not_reflected", "Rendered beats must follow source beat order.")
        if not package.opening_hook_reflected:
            add_issue("opening_hook_not_reflected", "Opening hook was not reflected.")
        if not package.conflict_turn_reflected:
            add_issue("conflict_turn_not_reflected", "Conflict turn was not reflected.")
        character_move_reflected = self._rendered_beat_type_present(package, "character_move")
        if not character_move_reflected:
            add_issue("character_move_not_reflected", "Character move beat was not reflected.")
        if not package.required_progression_delta_reflected:
            add_issue("required_progression_delta_not_reflected", "Required progression delta was not reflected.")
        if not package.ending_pull_reflected:
            add_issue("ending_pull_not_reflected", "Ending pull was not reflected.")
        if not package.visible_action_present:
            add_issue("visible_action_missing", "Candidate prose requires visible action.")
        if not package.dialogue_or_decision_present:
            add_issue("dialogue_or_decision_missing", "Candidate prose requires dialogue or a concrete decision.")
        if not package.psychology_visibility_applied or package.subtext_rendering_report.status != "passed":
            add_issue("psychology_visibility_violation", "Psychology visibility was not safely applied.")
        if self._contains_forbidden_marker(package.candidate_prose) or not package.raw_psychology_chain_forbidden:
            add_issue("raw_psychology_chain_leaked", "Raw psychology or provider markers leaked.")
        if self._contains_internal_json(package.candidate_prose) or not package.internal_json_forbidden:
            add_issue("internal_json_leaked", "Internal JSON or diagnostic fields leaked.")
        if "diagnostic" in package.candidate_prose.casefold() or "traceback" in package.candidate_prose.casefold():
            add_issue("diagnostic_text_leaked", "Diagnostic text leaked into prose.")

        profile = ProseStyleProfile(style_profile_id=package.style_profile_id)
        empty_ok = package.empty_mystery_density <= profile.suspense_style.empty_mystery_budget
        abstract_ok = package.abstract_language_density <= profile.scene_style.abstract_language_budget
        adjective_ok = package.adjective_density <= profile.adjective_budget
        if not empty_ok:
            add_issue("empty_mystery_density_high", "Empty mystery density is too high.")
        if not abstract_ok:
            add_issue("abstract_language_density_high", "Abstract language density is too high.")
        if not adjective_ok:
            add_issue("adjective_density_high", "Adjective density is too high.")

        candidate_only_boundary_enforced = (
            package.candidate_only is True
            and package.can_write_scene_prose_directly is False
            and package.can_write_story_facts_directly is False
        )
        if not candidate_only_boundary_enforced:
            add_issue("direct_write_capability_forbidden", "Draft package cannot write prose or facts directly.")
        if not package.requires_post_draft_gate_review:
            add_issue("post_draft_gate_requirement_missing", "Draft package requires post-draft gate review.")

        if source_planner_output is not None:
            if package.source_planner_output_id != source_planner_output.planner_output_id:
                add_issue("source_planner_output_mismatch", "Draft package source planner output mismatch.")
            if not self._all_source_beats_rendered(package, source_planner_output):
                add_issue("rendered_beat_missing", "A source beat was not rendered.")

        return WriterProseDraftingValidationReport(
            draft_package_id=package.draft_package_id,
            passed=not issue_codes,
            issue_codes=sorted(set(issue_codes)),
            warning_codes=sorted(set(warning_codes)),
            issues=issues,
            warnings=warnings,
            beat_order_reflected="beat_order_not_reflected" not in issue_codes,
            opening_hook_reflected=package.opening_hook_reflected,
            conflict_turn_reflected=package.conflict_turn_reflected,
            character_move_reflected=character_move_reflected,
            required_progression_delta_reflected=package.required_progression_delta_reflected,
            ending_pull_reflected=package.ending_pull_reflected,
            visible_action_present=package.visible_action_present,
            dialogue_or_decision_present=package.dialogue_or_decision_present,
            psychology_visibility_applied=package.psychology_visibility_applied,
            raw_psychology_chain_forbidden="raw_psychology_chain_leaked" not in issue_codes,
            internal_json_forbidden="internal_json_leaked" not in issue_codes,
            empty_mystery_density_within_threshold=empty_ok,
            abstract_language_density_within_threshold=abstract_ok,
            adjective_density_within_threshold=adjective_ok,
            candidate_only_boundary_enforced=candidate_only_boundary_enforced,
            post_draft_gate_requirement_preserved=package.requires_post_draft_gate_review,
        )

    def _build_input(
        self,
        planner_output: WriterPlannerLayerOutput,
        do_not_use_texts: list[str],
    ) -> WriterProseDraftingInput:
        return WriterProseDraftingInput(
            input_id=f"writer_prose_drafting_input_{planner_output.scene_id}",
            planner_output_id=planner_output.planner_output_id,
            project_id=planner_output.project_id,
            chapter_id=planner_output.chapter_id,
            scene_id=planner_output.scene_id,
            scene_index=planner_output.scene_index,
            style_profile_id=planner_output.scene_prose_plan.style_profile_id,
            source_scene_prose_plan_id=planner_output.scene_prose_plan.scene_prose_plan_id,
            source_psychology_visibility_plan_id=(
                planner_output.psychology_visibility_plan.psychology_visibility_plan_id
            ),
            source_beat_sheet_id=planner_output.beat_sheet.beat_sheet_id,
            do_not_use_texts=do_not_use_texts,
            source_refs=[
                planner_output.planner_output_id,
                planner_output.scene_prose_plan.scene_prose_plan_id,
                planner_output.psychology_visibility_plan.psychology_visibility_plan_id,
                planner_output.beat_sheet.beat_sheet_id,
            ],
        )

    def _render_beat(
        self,
        *,
        beat: Beat,
        planner_output: WriterPlannerLayerOutput,
        subtext_report: SubtextRenderingReport,
        do_not_use_texts: list[str],
        language: str,
    ) -> RenderedProseBeat:
        plan = planner_output.scene_prose_plan
        subtext = self._subtext_for_beat(beat, subtext_report)
        segment = self._segment_for_beat(beat, planner_output, subtext, language=language)
        segment = self._sanitize_prose(segment, do_not_use_texts)
        return RenderedProseBeat(
            beat_index=beat.beat_index,
            beat_type=beat.beat_type,
            source_beat_type=beat.beat_type,
            source_beat_refs=beat.source_refs,
            prose_segment=segment,
            used_character_ids=beat.source_character_ids,
            visible_action_present=self._visible_action_present(segment),
            dialogue_or_decision_present=self._dialogue_or_decision_present(segment),
            concrete_information_reveal_present=self._text_reflected(
                plan.new_information or plan.information_control.reveal,
                segment,
            ),
            psychology_channels_used=[
                decision.rendered_channel
                for decision in subtext_report.decisions
                if decision.rendered_subtext and decision.rendered_subtext in segment
            ],
            interior_line_word_count=sum(
                decision.interior_line_word_count
                for decision in subtext_report.decisions
                if decision.rendered_subtext and decision.rendered_subtext in segment
            ),
            source_refs=[*beat.source_refs, plan.scene_prose_plan_id],
        )

    def _segment_for_beat(
        self,
        beat: Beat,
        planner_output: WriterPlannerLayerOutput,
        subtext: str,
        *,
        language: str = "en",
    ) -> str:
        plan = planner_output.scene_prose_plan
        if language == "zh":
            return self._segment_for_beat_zh(beat, planner_output, subtext)
        term_text = ""
        term_terms = [
            self._safe_story_text(term)
            for term in plan.required_prompt_terms
            if self._safe_story_text(term)
        ]
        if term_terms:
            term_text = " The concrete terms stay visible: " + ", ".join(
                term_terms[:4]
            ) + "."
        if beat.beat_type == "opening_hook":
            return (
                f"A participant reaches for the immediate problem: {self._safe_story_text(plan.opening_hook)}. "
                f"{subtext} \"We act on what is in front of us,\" someone says."
            )
        if beat.beat_type == "character_move":
            move = plan.character_moves[0] if plan.character_moves else None
            action = move.visible_action if move else beat.required_action
            effect = move.scene_effect if move else beat.required_reveal_or_decision
            return (
                f"The next move is visible: {self._safe_story_text(action)}. "
                f"The choice changes the room: {self._safe_story_text(effect)}. {subtext}"
            )
        if beat.beat_type == "conflict_turn":
            return (
                f"Pressure tightens around {self._safe_story_text(plan.conflict_turn.pressure_source)}. "
                f"The turn comes when {self._safe_story_text(plan.conflict_turn.turn)}. "
                f"\"Then we choose the risk,\" someone says."
            )
        if beat.beat_type == "information_release":
            reveal = plan.new_information or plan.information_control.reveal
            withheld = plan.information_control.withhold or "the next answer"
            return (
                f"The new information lands plainly: {self._safe_story_text(reveal)}. "
                f"The scene keeps back {self._safe_story_text(withheld)}.{term_text}"
            )
        if beat.beat_type == "ending_pull":
            return (
                f"The final choice points forward: {self._safe_story_text(plan.ending_pull)}. "
                f"Someone decides to follow that risk before the chance closes."
            )
        return (
            f"The beat moves through a visible action: {self._safe_story_text(beat.required_action)}. "
            f"The result is concrete: {self._safe_story_text(beat.required_reveal_or_decision)}."
        )

    def _segment_for_beat_zh(
        self,
        beat: Beat,
        planner_output: WriterPlannerLayerOutput,
        subtext: str,
    ) -> str:
        plan = planner_output.scene_prose_plan
        delta = self._preferred_language_text(
            [
                plan.must_change_by_end,
                plan.new_information,
                plan.information_control.reveal,
                plan.opening_hook,
            ],
            "zh",
        )
        term_text = ""
        zh_terms = [
            self._safe_story_text(term)
            for term in plan.required_prompt_terms
            if CJK_RE.search(str(term or ""))
        ]
        if zh_terms:
            term_text = " 具体词仍然留在正文里：" + "、".join(
                zh_terms[:4]
            ) + "。"
        if beat.beat_type == "opening_hook":
            hook = self._preferred_language_text([plan.opening_hook, delta], "zh")
            return (
                f"一名参与者伸手处理眼前的问题：{hook}。"
                f"{subtext}“我们先处理看得见的事。”有人说。"
            )
        if beat.beat_type == "character_move":
            move = plan.character_moves[0] if plan.character_moves else None
            action = self._preferred_language_text(
                [getattr(move, "visible_action", ""), beat.required_action, delta],
                "zh",
            )
            effect = self._preferred_language_text(
                [getattr(move, "scene_effect", ""), beat.required_reveal_or_decision, delta],
                "zh",
            )
            return f"下一步必须看得见：{action}。这个选择改变了现场：{effect}。{subtext}"
        if beat.beat_type == "conflict_turn":
            pressure = self._preferred_language_text(
                [plan.conflict_turn.pressure_source, plan.conflict_turn.turn_trigger, delta],
                "zh",
            )
            turn = self._preferred_language_text(
                [plan.conflict_turn.turn, plan.conflict_turn.outcome, delta],
                "zh",
            )
            return f"压力压向{pressure}。转折发生在{turn}。“那就选择这个风险。”有人说。"
        if beat.beat_type == "information_release":
            reveal = self._preferred_language_text(
                [plan.new_information, plan.information_control.reveal, delta],
                "zh",
            )
            withheld = self._preferred_language_text(
                [plan.information_control.withhold, "下一步答案"],
                "zh",
            )
            return f"新的信息被清楚摆出来：{reveal}。场景仍然扣住{withheld}。{term_text}"
        if beat.beat_type == "ending_pull":
            ending = self._preferred_language_text([plan.ending_pull, delta], "zh")
            return f"最后的选择把下一步推到眼前：{ending}。有人决定在机会关闭前跟进这个风险。"
        action = self._preferred_language_text([beat.required_action, delta], "zh")
        result = self._preferred_language_text([beat.required_reveal_or_decision, delta], "zh")
        return f"这一拍通过可见动作推进：{action}。结果变得具体：{result}。"

    def _subtext_for_beat(
        self,
        beat: Beat,
        subtext_report: SubtextRenderingReport,
    ) -> str:
        wanted = set(beat.source_character_ids)
        for decision in subtext_report.decisions:
            if decision.character_id in wanted and decision.rendered_subtext:
                return decision.rendered_subtext
        for decision in subtext_report.decisions:
            if decision.rendered_subtext:
                return decision.rendered_subtext
        return ""

    def _candidate_synopsis(self, planner_output: WriterPlannerLayerOutput) -> str:
        plan = planner_output.scene_prose_plan
        return self._sanitize_prose(
            " ".join(
                [
                    self._safe_story_text(plan.scene_purpose),
                    self._safe_story_text(plan.must_change_by_end),
                    self._safe_story_text(plan.ending_pull),
                ]
            ),
            [],
        )[:480]

    def _drafting_traces(self, drafting_input: WriterProseDraftingInput) -> list[WriterProseDraftingTrace]:
        contributions = {
            "DialogueActionWriter": ["visible_action_present", "dialogue_or_decision_present"],
            "SubtextRenderer": ["psychology_visibility_applied"],
            "PlainProseStylist": ["abstract_language_density", "adjective_density"],
            "HookAndPayoffEditor": ["opening_hook_reflected", "ending_pull_reflected"],
            "RepetitionBreaker": ["empty_mystery_density"],
            "InteriorLineLimiter": ["interior_line_word_count"],
        }
        return [
            WriterProseDraftingTrace(
                step_index=index,
                module_name=name,
                contributed_fields=contributions[name],
                source_refs=[drafting_input.input_id],
                safe_summary=f"{name} contributed {', '.join(contributions[name])}.",
            )
            for index, name in enumerate(WRITER_PROSE_DRAFTING_MODULE_ORDER, start=1)
        ]

    def _character_ids_present(self, planner_output: WriterPlannerLayerOutput) -> list[str]:
        ids: list[str] = []
        for move in planner_output.scene_prose_plan.character_moves:
            ids.append(move.character_id)
        for decision in planner_output.psychology_visibility_plan.decisions:
            ids.append(decision.character_id)
        return _unique_strings(ids)

    def _beat_order_reflected(self, package: WriterProseDraftPackage) -> bool:
        indexes = [beat.beat_index for beat in package.rendered_beats]
        return indexes == list(range(1, len(indexes) + 1))

    def _all_source_beats_rendered(
        self,
        package: WriterProseDraftPackage,
        source: WriterPlannerLayerOutput,
    ) -> bool:
        source_keys = {(beat.beat_index, beat.beat_type) for beat in source.beat_sheet.beats}
        rendered_keys = {(beat.beat_index, beat.source_beat_type) for beat in package.rendered_beats}
        return source_keys.issubset(rendered_keys)

    def _rendered_beat_type_present(self, package: WriterProseDraftPackage, beat_type: str) -> bool:
        return any(beat.source_beat_type == beat_type and beat.prose_segment for beat in package.rendered_beats)

    def _progression_reflected(
        self,
        planner_output: WriterPlannerLayerOutput,
        text: str,
    ) -> bool:
        plan = planner_output.scene_prose_plan
        return self._text_reflected(plan.must_change_by_end, text) or self._text_reflected(
            plan.new_information, text
        )

    def _conflict_turn_reflected(
        self,
        planner_output: WriterPlannerLayerOutput,
        text: str,
    ) -> bool:
        turn = planner_output.scene_prose_plan.conflict_turn
        fields = [
            turn.pressure_source,
            turn.turn_trigger,
            turn.turn,
            turn.outcome,
        ]
        meaningful = [field for field in fields if str(field or "").strip()]
        if not meaningful:
            return False
        reflected_count = sum(
            1
            for field in meaningful
            if self._text_reflected(field, text)
        )
        return reflected_count >= min(2, len(meaningful))

    def _text_reflected(self, source: str, target: str) -> bool:
        source_norm = self._normalized_reflection_text(source)
        target_norm = self._normalized_reflection_text(target)
        if source_norm and target_norm and source_norm in target_norm:
            return True
        source_cjk = "".join(CJK_RE.findall(str(source or "")))
        target_cjk = "".join(CJK_RE.findall(str(target or "")))
        if source_cjk:
            if source_cjk in target_cjk:
                return True
            source_ngrams = self._cjk_ngrams(source_cjk)
            target_ngrams = self._cjk_ngrams(target_cjk)
            if source_ngrams:
                return len(source_ngrams & target_ngrams) >= min(2, len(source_ngrams))
        source_words = {
            word
            for word in re.findall(r"[A-Za-z][A-Za-z'-]*", str(source or "").casefold())
            if len(word) >= 4
        }
        if not source_words:
            return False
        target_words = set(re.findall(r"[A-Za-z][A-Za-z'-]*", str(target or "").casefold()))
        return len(source_words & target_words) >= min(2, len(source_words))

    def _normalized_reflection_text(self, value: str) -> str:
        return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)

    def _cjk_ngrams(self, value: str) -> set[str]:
        text = "".join(CJK_RE.findall(str(value or "")))
        if not text:
            return set()
        if len(text) <= 2:
            return {text}
        return {text[index : index + 2] for index in range(0, len(text) - 1)}

    def _visible_action_present(self, text: str) -> bool:
        lowered = str(text or "").casefold()
        return any(marker in lowered for marker in VISIBLE_ACTION_MARKERS)

    def _dialogue_or_decision_present(self, text: str) -> bool:
        lowered = str(text or "").casefold()
        return any(marker in lowered for marker in DIALOGUE_MARKERS)

    def _contains_forbidden_marker(self, text: str) -> bool:
        lowered = str(text or "").casefold()
        return any(marker.casefold() in lowered for marker in FORBIDDEN_PROSE_MARKERS)

    def _contains_internal_json(self, text: str) -> bool:
        if self.metrics_service.contains_source_id(text):
            return True
        lowered = str(text or "").casefold()
        return any(marker.casefold() in lowered for marker in JSON_MARKERS)

    def _sanitize_prose(self, value: str, do_not_use_texts: list[str]) -> str:
        text = self._safe_story_text(value)
        for blocked in do_not_use_texts:
            blocked_text = str(blocked or "").strip()
            if blocked_text and blocked_text.casefold() in text.casefold():
                text = re.sub(re.escape(blocked_text), "[withheld]", text, flags=re.IGNORECASE)
        return text

    def _safe_story_text(self, value: Any) -> str:
        text = " ".join(str(value or "").split())
        for marker in FORBIDDEN_PROSE_MARKERS:
            text = re.sub(re.escape(marker), "[redacted-marker]", text, flags=re.IGNORECASE)
        text = re.sub(
            r"\b(?:project|chapter|scene|char|memory|event|state|writer|beat_sheet|"
            r"scene_prose_plan|psych_visibility_plan|writer_planner_output)_[A-Za-z0-9_]+\b",
            "a participant",
            text,
        )
        text = self._remove_story_instruction_text(text)
        return text.strip()

    def _remove_story_instruction_text(self, text: str) -> str:
        value = str(text or "").strip()
        if ":" in value:
            prefix, suffix = value.split(":", 1)
            if self._looks_like_instruction_prefix(prefix):
                value = suffix.strip()
        value = re.sub(r"^use\s+the\s+", "The ", value, flags=re.IGNORECASE)
        value = re.sub(r"^use\s+", "The ", value, flags=re.IGNORECASE)
        value = re.sub(r"^moves?\s+the\s+scene\s+toward\s+", "The scene turns toward ", value, flags=re.IGNORECASE)
        patterns = [
            r";?\s*use as a tentative behavior hint only;?\s*",
            r";?\s*keep it consistent with quality_gate\.?",
            r"\s*may express this only as subjective claim:\s*",
            r"\s*states a cautious interpretation rather than a fact\.?",
            r"\s*do not present it as objective fact\.?",
            r"\s*steps forward and asks a precise question\.?",
            r";?\s*present this as belief,?\s*not objective fact\.?",
            r";?\s*present this as belief\.?",
            r",?\s*not objective fact\.?",
            r"\s+as (?:a\s+)?concise [A-Z]-tier continuity hint\.?",
            r"\s+as (?:a\s+)?[A-Z]-tier continuity hint\.?",
        ]
        for pattern in patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE)
        value = re.sub(r"^([^:：]{1,30})\s*[:：]\s*", r"\1 ", value)
        return " ".join(value.split())

    def _looks_like_instruction_prefix(self, text: str) -> bool:
        lowered = str(text or "").casefold()
        markers = {
            "end by",
            "chapter focus",
            "move the scene",
            "move at least",
            "name the first",
            "distinctive procedure",
            "scene-specific evidence movement",
            "cannot solve the beat alone",
        }
        return any(marker in lowered for marker in markers)

    def _language_for_output(self, planner_output: WriterPlannerLayerOutput) -> str:
        plan = planner_output.scene_prose_plan
        snapshot = planner_output.input_snapshot
        texts = [
            plan.scene_purpose,
            plan.reader_value,
            plan.must_change_by_end,
            plan.opening_hook,
            plan.ending_pull,
            plan.new_information,
            plan.conflict_turn.turn_trigger,
            plan.conflict_turn.pressure_source,
            plan.conflict_turn.turn,
            plan.conflict_turn.outcome,
            snapshot.scene_writing_context_summary,
            snapshot.scene_progression_statement,
            snapshot.required_progression_delta,
            *plan.required_prompt_terms,
            *snapshot.prompt_terms,
        ]
        return "zh" if any(CJK_RE.search(str(text or "")) for text in texts) else "en"

    def _preferred_language_text(self, values: list[Any], language: str) -> str:
        fallback = ""
        for value in values:
            text = self._language_story_text(value, language)
            if not text:
                continue
            fallback = fallback or text
            if language == "zh" and CJK_RE.search(text):
                return text
            if language != "zh":
                return text
        return fallback

    def _language_story_text(self, value: Any, language: str) -> str:
        text = self._safe_story_text(value)
        if language != "zh" or not CJK_RE.search(text):
            return text
        first_cjk = CJK_RE.search(text)
        if first_cjk:
            text = text[first_cjk.start() :]
        text = re.sub(r"^[：:，,。.\s]+", "", text)
        text = re.sub(r"[：:，,。.!?；;\s]+$", "", text)
        return text.strip()


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
