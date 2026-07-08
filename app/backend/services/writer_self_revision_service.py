from __future__ import annotations

import re

from app.backend.models.writer_prose_engine import (
    RenderedProseBeat,
    WriterPlannerLayerOutput,
    WriterProseDraftPackage,
    WriterProseDraftingValidationReport,
    WriterSelfRevisionAction,
    WriterSelfRevisionReport,
    WriterSelfRevisionResult,
)
from app.backend.services.writer_prose_drafting_service import WriterProseDraftingService
from app.backend.services.writer_quality_inspection_service import (
    WriterQualityInspectionService,
)
from app.backend.services.writer_quality_shared import (
    ABSTRACT_MARKERS,
    EMPTY_MYSTERY_MARKERS,
    ISSUE_TO_ACTION,
    PLACEHOLDER_OR_INSTRUCTION_MARKERS,
    blocking_markers,
    contains_any,
    language_for_text,
    safe_excerpt,
    unique_strings,
)


class WriterSelfRevisionService:
    def __init__(
        self,
        *,
        writer_quality_inspection_service: WriterQualityInspectionService | None = None,
        writer_prose_drafting_service: WriterProseDraftingService | None = None,
    ) -> None:
        self.inspection_service = writer_quality_inspection_service or WriterQualityInspectionService()
        self.drafting_service = writer_prose_drafting_service or WriterProseDraftingService()

    def revise(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
        *,
        max_passes: int = 2,
    ) -> WriterSelfRevisionResult:
        initial_bundle = self.inspection_service.inspect(package, planner_output)
        if initial_bundle.blocking_issue_codes:
            validation = self.drafting_service.validate_draft_package(
                package,
                source_planner_output=planner_output,
            )
            report = WriterSelfRevisionReport(
                writer_self_revision_report_id=f"writer_self_revision_report_{package.draft_package_id}",
                source_draft_package_id=package.draft_package_id,
                original_issue_codes=initial_bundle.issue_codes,
                revision_actions=[],
                final_issue_codes=initial_bundle.issue_codes,
                blocking_issue_codes=initial_bundle.blocking_issue_codes,
                repair_passes_run=0,
                ready_for_downstream_gates=False,
                blocking_issue_remains=True,
                candidate_only=True,
                no_story_write=True,
            )
            return WriterSelfRevisionResult(
                source_draft_package_id=package.draft_package_id,
                revised_draft_package=package,
                initial_inspection_bundle=initial_bundle,
                final_inspection_bundle=initial_bundle,
                revision_report=report,
                m4_validation_report=validation,
                writer_self_revision_applied=False,
                ready_for_downstream_gates=False,
                candidate_only=True,
                can_write_scene_prose_directly=False,
                can_write_story_facts_directly=False,
                requires_post_draft_gate_review=True,
            )

        current = package
        actions: list[WriterSelfRevisionAction] = []
        passes_run = 0
        for pass_index in range(1, max(1, max_passes) + 1):
            bundle = self.inspection_service.inspect(current, planner_output)
            if bundle.passed:
                break
            if bundle.blocking_issue_codes or not bundle.repairable_issue_codes:
                break
            passes_run = pass_index
            current, pass_actions = self._apply_repair_pass(
                package=current,
                planner_output=planner_output,
                issue_codes=bundle.repairable_issue_codes,
                pass_index=pass_index,
            )
            actions.extend(pass_actions)

        final_bundle = self.inspection_service.inspect(current, planner_output)
        validation = self.drafting_service.validate_draft_package(
            current,
            source_planner_output=planner_output,
        )
        ready = validation.passed and final_bundle.passed and not final_bundle.blocking_issue_codes
        report = WriterSelfRevisionReport(
            writer_self_revision_report_id=f"writer_self_revision_report_{package.draft_package_id}",
            source_draft_package_id=package.draft_package_id,
            original_issue_codes=initial_bundle.issue_codes,
            revision_actions=actions,
            final_issue_codes=final_bundle.issue_codes,
            blocking_issue_codes=final_bundle.blocking_issue_codes,
            repair_passes_run=passes_run,
            ready_for_downstream_gates=ready,
            blocking_issue_remains=bool(final_bundle.blocking_issue_codes),
            candidate_only=True,
            no_story_write=True,
        )
        return WriterSelfRevisionResult(
            source_draft_package_id=package.draft_package_id,
            revised_draft_package=current,
            initial_inspection_bundle=initial_bundle,
            final_inspection_bundle=final_bundle,
            revision_report=report,
            m4_validation_report=validation,
            writer_self_revision_applied=bool(actions),
            ready_for_downstream_gates=ready,
            candidate_only=True,
            can_write_scene_prose_directly=False,
            can_write_story_facts_directly=False,
            requires_post_draft_gate_review=True,
        )

    def _apply_repair_pass(
        self,
        *,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
        issue_codes: list[str],
        pass_index: int,
    ) -> tuple[WriterProseDraftPackage, list[WriterSelfRevisionAction]]:
        actions = [
            WriterSelfRevisionAction(
                action_id=f"writer_self_revision_action_{package.draft_package_id}_{pass_index}_{index}",
                action_type=ISSUE_TO_ACTION.get(code, "tighten_reader_experience"),
                source_issue_codes=[code],
                safe_summary=f"Candidate-only repair for {code}.",
                applied=True,
                candidate_only=True,
            )
            for index, code in enumerate(unique_strings(issue_codes), start=1)
        ]
        prose = self._repair_prose(package.candidate_prose, planner_output, issue_codes)
        synopsis = self._repair_synopsis(package.candidate_synopsis, planner_output)
        package = self._package_with_revised_text(package, planner_output, synopsis, prose)
        return package, actions

    def _repair_prose(
        self,
        prose: str,
        planner_output: WriterPlannerLayerOutput,
        issue_codes: list[str],
    ) -> str:
        language = language_for_text(prose + " " + planner_output.scene_prose_plan.opening_hook)
        text = self._redact_blocking_markers(prose)
        text = self._remove_overexposed_psychology(text)
        if self._should_replace_original_with_plan_sentences(text, issue_codes):
            text = ""
        else:
            text = self._remove_empty_or_abstract_markers(text)
        required_sentences = self._required_sentences(planner_output, language)
        additions: list[str] = []
        if any(
            code in issue_codes
            for code in (
                "empty_mystery_too_high",
                "abstract_language_too_high",
                "abstract_language_density_high",
                "opening_hook_too_abstract",
                "hook_payoff_missing",
                "placeholder_or_instruction_text_leak",
            )
        ):
            additions.append(required_sentences["hook"])
        if any(
            code in issue_codes
            for code in (
                "empty_mystery_too_high",
                "abstract_language_too_high",
                "abstract_language_density_high",
                "plot_turn_missing",
                "scene_reader_value_missing",
                "hook_payoff_missing",
            )
        ):
            additions.append(required_sentences["turn"])
        if any(
            code in issue_codes
            for code in (
                "empty_mystery_too_high",
                "abstract_language_too_high",
                "abstract_language_density_high",
                "visible_action_missing",
                "dialogue_or_decision_missing",
            )
        ):
            additions.append(required_sentences["action"])
        if any(
            code in issue_codes
            for code in (
                "empty_mystery_too_high",
                "abstract_language_too_high",
                "abstract_language_density_high",
                "ending_pull_missing",
                "ending_pull_too_abstract",
                "reader_question_not_advanced",
            )
        ):
            additions.append(required_sentences["ending"])
        if any(
            code in issue_codes
            for code in (
                "psychology_overexposed",
                "interior_monologue_not_earned",
                "action_replaced_by_explanation",
                "subtext_should_be_behavior",
                "minor_role_over_interiorized",
                "subtext_balance_failed",
                "negative_space_leaked",
            )
        ):
            additions.append(required_sentences["subtext"])
        if any(code in issue_codes for code in ("abstract_language_too_high", "adjective_density_high", "over_poetic_metaphor")):
            text = self._plain_language(text, language)
        if not text.strip() and not additions:
            additions = list(required_sentences.values())[:4]
        joined = "\n\n".join(part for part in [text.strip(), *additions] if part.strip())
        if contains_any(joined, PLACEHOLDER_OR_INSTRUCTION_MARKERS):
            joined = "\n\n".join(part for part in additions if part.strip())
        return joined.strip()

    def _repair_synopsis(
        self,
        synopsis: str,
        planner_output: WriterPlannerLayerOutput,
    ) -> str:
        plan = planner_output.scene_prose_plan
        seed = synopsis.strip() or plan.scene_goal or plan.reader_value
        return safe_excerpt(seed, limit=240)

    def _package_with_revised_text(
        self,
        package: WriterProseDraftPackage,
        planner_output: WriterPlannerLayerOutput,
        synopsis: str,
        prose: str,
    ) -> WriterProseDraftPackage:
        density = self.drafting_service.metrics_service.density_report(prose)
        rendered_beats = self._revised_rendered_beats(package, prose)
        return package.copy(
            update={
                "candidate_synopsis": synopsis,
                "candidate_prose": prose,
                "rendered_beats": rendered_beats,
                "required_progression_delta_reflected": self.drafting_service._progression_reflected(
                    planner_output,
                    prose,
                ),
                "opening_hook_reflected": self.drafting_service._text_reflected(
                    planner_output.scene_prose_plan.opening_hook,
                    prose,
                ),
                "conflict_turn_reflected": self.drafting_service._text_reflected(
                    planner_output.scene_prose_plan.conflict_turn,
                    prose,
                ),
                "ending_pull_reflected": self.drafting_service._text_reflected(
                    planner_output.scene_prose_plan.ending_pull,
                    prose,
                ),
                "visible_action_present": self.drafting_service._visible_action_present(prose),
                "dialogue_or_decision_present": self.drafting_service._dialogue_or_decision_present(prose),
                "raw_psychology_chain_forbidden": not bool(blocking_markers(prose)),
                "internal_json_forbidden": not self.drafting_service._contains_internal_json(prose),
                "empty_mystery_density": float(density.get("empty_mystery_density", 0.0)),
                "abstract_language_density": float(density.get("abstract_language_density", 0.0)),
                "adjective_density": float(density.get("adjective_density", 0.0)),
                "candidate_only": True,
                "can_write_scene_prose_directly": False,
                "can_write_story_facts_directly": False,
                "requires_post_draft_gate_review": True,
            },
        )

    def _revised_rendered_beats(
        self,
        package: WriterProseDraftPackage,
        prose: str,
    ) -> list[RenderedProseBeat]:
        return [beat.copy(update={"prose_segment": prose}) for beat in package.rendered_beats]

    def _redact_blocking_markers(self, text: str) -> str:
        value = str(text or "")
        markers = [
            "raw_psychology_chain",
            "raw psychology chain",
            "hidden_reasoning",
            "hidden reasoning",
            "internal_reasoning",
            "chain-of-thought",
            "provider raw",
            "raw_prompt",
            "raw response",
            "raw_response",
            "traceback",
            "diagnostic",
        ]
        for marker in markers:
            value = re.sub(re.escape(marker), "[removed]", value, flags=re.IGNORECASE)
        return value

    def _should_replace_original_with_plan_sentences(self, text: str, issue_codes: list[str]) -> bool:
        if contains_any(text, PLACEHOLDER_OR_INSTRUCTION_MARKERS):
            return True
        replacement_codes = {
            "empty_mystery_too_high",
            "abstract_language_too_high",
            "abstract_language_density_high",
            "opening_hook_too_abstract",
            "hook_payoff_missing",
            "placeholder_or_instruction_text_leak",
        }
        return bool(replacement_codes.intersection(set(issue_codes)))

    def _remove_empty_or_abstract_markers(self, text: str) -> str:
        value = str(text or "")
        for marker in sorted(EMPTY_MYSTERY_MARKERS | ABSTRACT_MARKERS, key=len, reverse=True):
            value = re.sub(re.escape(marker), "", value, flags=re.IGNORECASE)
        return value

    def _remove_overexposed_psychology(self, text: str) -> str:
        value = str(text or "")
        patterns = [
            r"\b(she|he|they)\s+thought\b[^.!?\n]*[.!?]?",
            r"\bbecause\s+(her|his|their)\b[^.!?\n]*[.!?]?",
            r"\beveryone understands\b[^.!?\n]*[.!?]?",
        ]
        for pattern in patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE)
        return value

    def _plain_language(self, text: str, language: str) -> str:
        if language == "zh":
            replacements = {
                "\u547d\u8fd0": "\u9009\u62e9",
                "\u771f\u76f8": "\u4e8b\u5b9e",
                "\u795e\u79d8": "\u672a\u89e3\u7684\u7ec6\u8282",
                "\u610f\u4e49": "\u76ee\u6807",
            }
        else:
            replacements = {
                "like a sea of": "with",
                "as if": "while",
                "ocean of": "",
                "destiny": "choice",
                "truth": "fact",
                "mystery": "unanswered detail",
            }
        value = str(text or "")
        for old, new in replacements.items():
            value = re.sub(re.escape(old), new, value, flags=re.IGNORECASE)
        return value

    def _required_sentences(
        self,
        planner_output: WriterPlannerLayerOutput,
        language: str,
    ) -> dict[str, str]:
        plan = planner_output.scene_prose_plan
        if language == "zh":
            hook_text = self._localized_plan_text(
                plan.opening_hook or plan.scene_goal,
                "\u773c\u524d\u7684\u5371\u9669",
                language,
            )
            hook_text = self._sentence_fragment(hook_text)
            turn_text = self._localized_plan_text(
                plan.new_information or plan.must_change_by_end,
                "\u65b0\u7684\u53d1\u73b0",
                language,
            )
            turn_text = self._sentence_fragment(turn_text)
            ending_text = self._localized_plan_text(
                plan.ending_pull or plan.reader_value,
                "\u6700\u540e\u7684\u9009\u62e9",
                language,
            )
            ending_text = self._sentence_fragment(ending_text)
            hook = f"\u5f00\u573a\u52a8\u4f5c\u628a\u95ee\u9898\u843d\u5230\u773c\u524d\uff1a{hook_text}\u3002"
            turn = (
                f"\u8f6c\u6298\u6539\u53d8\u4e86\u773c\u524d\u95ee\u9898\uff1a{turn_text}\u3002"
                "\u53c2\u4e0e\u8005\u5fc5\u987b\u7acb\u523b\u56de\u5e94\u3002"
            )
            action = "\u4e00\u540d\u53c2\u4e0e\u8005\u4f38\u624b\u6253\u5f00\u4e0b\u4e00\u9053\u73b0\u5b9e\u95e8\u69db\uff0c\u8bf4\uff1a\u201c\u73b0\u5728\u5c31\u505a\u9009\u62e9\u3002\u201d"
            ending = (
                f"\u7ed3\u5c3e\u7559\u4e0b\u4e00\u4e2a\u53ef\u8ffd\u95ee\u7684\u98ce\u9669\uff1a{ending_text}\u3002"
                "\u4e0b\u4e00\u6b65\u5df2\u7ecf\u88ab\u770b\u89c1\u3002"
            )
            subtext = "\u5fc3\u7406\u538b\u529b\u6539\u7531\u52a8\u4f5c\u548c\u505c\u987f\u5448\u73b0\uff0c\u800c\u4e0d\u76f4\u63a5\u89e3\u91ca\u3002"
        else:
            hook_text = self._localized_plan_text(
                plan.opening_hook or plan.scene_goal,
                "A visible pressure",
                language,
            )
            hook_text = self._sentence_fragment(hook_text)
            turn_text = self._localized_plan_text(
                plan.new_information or plan.must_change_by_end,
                "The new information",
                language,
            )
            turn_text = self._sentence_fragment(turn_text)
            ending_text = self._localized_plan_text(
                plan.ending_pull or plan.reader_value,
                "The final choice",
                language,
            )
            ending_text = self._sentence_fragment(ending_text)
            hook = f"The opening action makes the problem visible: {hook_text}."
            turn = (
                f"The turn changes the immediate problem: {turn_text}. "
                "The participants must answer it now."
            )
            action = 'A participant opens the next concrete step and says, "We choose the risk now."'
            ending = (
                f"The ending leaves a specific risk in motion: {ending_text}, "
                "and the next step is visible."
            )
            subtext = "The pressure moves through gesture, pause, and choice instead of direct explanation."
        return {"hook": hook, "turn": turn, "action": action, "ending": ending, "subtext": subtext}

    def _localized_plan_text(self, value: str, fallback: str, language: str) -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        text = self.drafting_service._safe_story_text(text)
        text = self._remove_story_instruction_clauses(text)
        text = self._deimperativize_story_text(text)
        if language == "zh":
            narrative = self._zh_story_text_from_mixed_instruction(text)
            if narrative:
                return narrative
        if ":" in text and self._looks_like_instruction_prefix(text.split(":", 1)[0]):
            suffix = text.split(":", 1)[1].strip()
            if suffix:
                text = suffix
                text = self._remove_story_instruction_clauses(text)
                text = self._deimperativize_story_text(text)
                if language == "zh":
                    narrative = self._zh_story_text_from_mixed_instruction(text)
                    if narrative:
                        return narrative
        if language == "zh":
            if ":" in text:
                suffix = text.split(":", 1)[1].strip()
                if suffix and any("\u4e00" <= char <= "\u9fff" for char in suffix):
                    text = suffix
            if not any("\u4e00" <= char <= "\u9fff" for char in text):
                return fallback
            if re.search(r"[A-Za-z][A-Za-z'-]*", text):
                return fallback
            return text
        if self._looks_like_instruction_prefix(text):
            return fallback
        if language != "zh" and any("\u4e00" <= char <= "\u9fff" for char in text):
            return fallback
        return text

    def _zh_story_text_from_mixed_instruction(self, text: str) -> str:
        value = str(text or "").strip()
        if not any("\u4e00" <= char <= "\u9fff" for char in value):
            return ""
        value = self._rewrite_common_writer_safe_clauses_zh(value)
        value = re.sub(
            r"\bConstraint\s+for\s+([^:：]+)[:：]\s*",
            r"\1，",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bEnd\s+by\s+making\s+the\s+next\s+step\s+concrete[:：]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\bAct\s+on\s+", "处理", value, flags=re.IGNORECASE)
        value = re.sub(
            r"\bMoves?\s+the\s+scene\s+toward\s+",
            "推动现场转向",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bThe\s+group\s+can\s+no\s+longer\s+avoid\s+",
            "众人不能再回避",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bThe\s+approved\s+context\s+makes\s+delay\s+costly[:：]?\s*",
            "拖延带来代价：",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bA\s+participant\s+must\s+choose\s+how\s+to\s+act\s+on\s+",
            "参与者必须选择如何处理",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bThe\s+scene\s+ends\s+with\s+the\s+situation\s+changed\s+by\s+",
            "场景以局势改变收束：",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bShow\s+concrete\s+movement\s+around\s+this\s+change[:：]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"use\s+as\s+a\s+tentative\s+behavior\s+hint\s+only;?\s*keep\s+it\s+consistent\s+with\s+quality_gate\.?\s*",
            "作为暂定动作线索，",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"use\s+as\s+a\s+tentative\s+behavior\s+hint\s+only;?\s*",
            "作为暂定动作线索，",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"keep\s+it\s+consistent\s+with\s+quality_gate\.?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bsteps\s+forward\s+and\s+asks\s+a\s+precise\s+question\b",
            "上前提出一个具体问题",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bForce\s+the\s+choice\s+to\s+become\s+explicit\b",
            "迫使选择变得明确",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bBlocks\s+the\s+easy\s+route\s+long\s+enough\s+to\s+demand\s+a\s+decision\b",
            "挡住简单退路，逼出决定",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bThe\s+conflict\s+turn\s+becomes\s+a\s+visible\s+choice\b",
            "冲突转折变成可见选择",
            value,
            flags=re.IGNORECASE,
        )
        value = self._remove_story_instruction_clauses(value)
        value = re.sub(r"\bM7\s+writer-safe\s+ABCD\s+StoryInformation\s+package\s+adapted\s+from\s+candidate-only\s+character\s+intent\s+outputs\.?", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" ：:，,。.;；")
        if not any("\u4e00" <= char <= "\u9fff" for char in value):
            return ""
        return value

    def _rewrite_common_writer_safe_clauses_zh(self, text: str) -> str:
        value = str(text or "")
        patterns = [
            (
                r"(?P<name>[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff][\w_\-\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]*)\s+may\s+express\s+this\s+only\s+as\s+subjective\s+claim:\s*states\s+a\s+cautious\s+interpretation\s+rather\s+than\s+a\s+fact\.?\s*Do\s+not\s+present\s+it\s+as\s+objective\s+fact\.?",
                r"\g<name>提出谨慎解释而不宣称事实",
            ),
            (
                r"(?P<name>[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff][\w_\-\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]*)\s+may\s+express\s+this\s+only\s+as\s+unknown:\s*pauses\s+before\s+answering\.?\s*Do\s+not\s+present\s+it\s+as\s+objective\s+fact\.?",
                r"\g<name>回答前停顿，暂不定论",
            ),
            (
                r"(?P<name>[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff][\w_\-\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]*)\s+may\s+express\s+this\s+only\s+as\s+perception:\s*points\s+to\s+the\s+local\s+hazard\.?\s*Do\s+not\s+present\s+it\s+as\s+objective\s+fact\.?",
                r"\g<name>指向现场危险，呈现为感知",
            ),
        ]
        for pattern, replacement in patterns:
            value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
        value = re.sub(
            r"\bDo\s+not\s+present\s+it\s+as\s+objective\s+fact\.?",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\bmay\s+express\s+this\s+only\s+as\s+(?:subjective\s+claim|unknown|perception)[:：]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return value

    def _sentence_fragment(self, text: str) -> str:
        return re.sub(r"[\s\u3002.!?]+$", "", str(text or "").strip())

    def _deimperativize_story_text(self, text: str) -> str:
        value = str(text or "").strip()
        value = re.sub(r"^use\s+the\s+", "The ", value, flags=re.IGNORECASE)
        value = re.sub(r"^use\s+", "The ", value, flags=re.IGNORECASE)
        return value

    def _remove_story_instruction_clauses(self, text: str) -> str:
        value = str(text or "")
        patterns = [
            r";?\s*present this as belief,?\s*not objective fact\.?",
            r";?\s*present this as belief\.?",
            r",?\s*not objective fact\.?",
            r"\s+as (?:a\s+)?concise [A-Z]-tier continuity hint\.?",
            r"\s+as (?:a\s+)?[A-Z]-tier continuity hint\.?",
        ]
        for pattern in patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE)
        return " ".join(value.split())

    def _looks_like_instruction_prefix(self, text: str) -> bool:
        lowered = str(text or "").casefold()
        markers = {
            "end by",
            "chapter focus",
            "move at least",
            "name the first",
            "distinctive procedure",
            "scene-specific evidence movement",
            "cannot solve the beat alone",
        }
        return any(marker in lowered for marker in markers)
