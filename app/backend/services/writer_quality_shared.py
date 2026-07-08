from __future__ import annotations

import re
from typing import Any


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

REPAIRABLE_ISSUE_CODES = {
    "empty_mystery_too_high",
    "abstract_language_too_high",
    "abstract_language_density_high",
    "adjective_density_high",
    "adjective_density_too_high",
    "scene_reader_value_missing",
    "plot_turn_missing",
    "visible_action_missing",
    "dialogue_or_decision_missing",
    "ending_pull_missing",
    "opening_hook_too_abstract",
    "ending_pull_too_abstract",
    "reader_question_not_advanced",
    "hook_payoff_missing",
    "psychology_overexposed",
    "interior_monologue_not_earned",
    "action_replaced_by_explanation",
    "subtext_should_be_behavior",
    "minor_role_over_interiorized",
    "subtext_balance_failed",
    "negative_space_leaked",
    "forbidden_psychology_channel_used",
    "over_poetic_metaphor",
    "plain_language_profile_failed",
    "suspense_overexplained",
    "character_depth_flattened_by_exposition",
    "placeholder_or_instruction_text_leak",
}

BLOCKING_ISSUE_CODES = {
    "raw_psychology_chain_leak",
    "internal_json_leak",
    "diagnostic_text_leak",
    "provider_raw_leak",
    "hidden_reasoning_leak",
    "candidate_no_write_boundary_broken",
    "canon_write_detected",
}

ISSUE_TO_ACTION = {
    "empty_mystery_too_high": "replace_empty_mystery_with_concrete_hook",
    "scene_reader_value_missing": "restore_scene_reader_value",
    "adjective_density_high": "reduce_adjective_density",
    "adjective_density_too_high": "reduce_adjective_density",
    "abstract_language_too_high": "simplify_over_poetic_language",
    "abstract_language_density_high": "simplify_over_poetic_language",
    "psychology_overexposed": "rewrite_psychology_as_visible_action",
    "interior_monologue_not_earned": "convert_inner_monologue_to_dialogue_subtext",
    "action_replaced_by_explanation": "rewrite_psychology_as_visible_action",
    "subtext_should_be_behavior": "restore_subtext",
    "minor_role_over_interiorized": "rewrite_psychology_as_visible_action",
    "visible_action_missing": "add_visible_action_or_decision",
    "dialogue_or_decision_missing": "add_visible_action_or_decision",
    "ending_pull_missing": "break_repeated_opening_or_ending",
    "ending_pull_too_abstract": "break_repeated_opening_or_ending",
    "opening_hook_too_abstract": "replace_empty_mystery_with_concrete_hook",
    "plot_turn_missing": "add_missing_conflict_turn",
    "reader_question_not_advanced": "restore_scene_reader_value",
    "hook_payoff_missing": "restore_scene_reader_value",
    "subtext_balance_failed": "restore_subtext",
    "negative_space_leaked": "restore_subtext",
    "forbidden_psychology_channel_used": "restore_subtext",
    "over_poetic_metaphor": "simplify_over_poetic_language",
    "plain_language_profile_failed": "simplify_over_poetic_language",
    "placeholder_or_instruction_text_leak": "replace_instruction_text_with_scene_plan_prose",
}

RAW_BLOCKING_MARKERS = {
    "raw_psychology_chain": "raw_psychology_chain_leak",
    "raw psychology chain": "raw_psychology_chain_leak",
    "hidden_reasoning": "hidden_reasoning_leak",
    "hidden reasoning": "hidden_reasoning_leak",
    "internal_reasoning": "hidden_reasoning_leak",
    "internal reasoning": "hidden_reasoning_leak",
    "chain-of-thought": "hidden_reasoning_leak",
    "chain of thought": "hidden_reasoning_leak",
    "chain_of_thought": "hidden_reasoning_leak",
    "provider raw": "provider_raw_leak",
    "provider_raw": "provider_raw_leak",
    "raw_prompt": "provider_raw_leak",
    "raw prompt": "provider_raw_leak",
    "raw_response": "provider_raw_leak",
    "raw response": "provider_raw_leak",
    "traceback": "diagnostic_text_leak",
    "diagnostic": "diagnostic_text_leak",
    '"source_refs"': "internal_json_leak",
    '"candidate_prose"': "internal_json_leak",
    '"beat_type"': "internal_json_leak",
}

ABSTRACT_MARKERS = {
    "truth",
    "destiny",
    "fate",
    "meaning",
    "darkness",
    "silence",
    "fear",
    "hope",
    "shadow",
    "uncertain",
    "mystery",
    "\u672a\u77e5",
    "\u547d\u8fd0",
    "\u610f\u4e49",
    "\u9ed1\u6697",
    "\u6c89\u9ed8",
    "\u6050\u60e7",
    "\u5e0c\u671b",
}

EMPTY_MYSTERY_MARKERS = {
    "something",
    "somehow",
    "mysterious",
    "unknown",
    "hidden truth",
    "no one knew",
    "only time would tell",
    "\u67d0\u79cd",
    "\u4e0d\u77e5\u4e3a\u4f55",
    "\u795e\u79d8",
    "\u65e0\u4eba\u77e5\u6653",
    "\u9690\u85cf\u771f\u76f8",
}

VISIBLE_ACTION_MARKERS = {
    "opens",
    "moves",
    "reaches",
    "turns",
    "steps",
    "blocks",
    "chooses",
    "decides",
    "acts",
    "\u6253\u5f00",
    "\u4f38\u624b",
    "\u884c\u52a8",
    "\u8d70",
    "\u6321\u4f4f",
    "\u9009\u62e9",
    "\u51b3\u5b9a",
    "\u8ddf\u8fdb",
}

DIALOGUE_OR_DECISION_MARKERS = {
    '"',
    "\u201c",
    "\u201d",
    " says",
    " asks",
    "answers",
    "decides",
    "chooses",
    "\u8bf4",
    "\u95ee",
    "\u56de\u7b54",
    "\u51b3\u5b9a",
    "\u9009\u62e9",
}

CONCRETE_ENDING_MARKERS = {
    "next",
    "risk",
    "choice",
    "decides",
    "follow",
    "question",
    "\u4e0b\u4e00\u6b65",
    "\u98ce\u9669",
    "\u9009\u62e9",
    "\u51b3\u5b9a",
    "\u95ee\u9898",
    "\u8ddf\u8fdb",
}

INNER_MONOLOGUE_MARKERS = {
    "she thought",
    "he thought",
    "they thought",
    "i think",
    "inner thought",
    "inner life",
    "inner monologue",
    "wanted validation",
    "attachment wound",
    "\u5979\u5fc3\u60f3",
    "\u4ed6\u5fc3\u60f3",
    "\u5fc3\u91cc\u60f3",
    "\u5185\u5fc3",
    "\u521b\u4f24",
    "\u6e34\u671b\u88ab\u8ba4\u53ef",
}

PSYCHOLOGY_EXPLANATION_MARKERS = {
    "because her",
    "because his",
    "because their",
    "attachment wound",
    "wants validation",
    "is about",
    "everyone understands",
    "\u56e0\u4e3a\u5979",
    "\u56e0\u4e3a\u4ed6",
    "\u5185\u5fc3\u539f\u56e0",
    "\u89e3\u91ca\u4e86\u52a8\u673a",
}

MINOR_ROLE_MARKERS = {"char_c", "char_d", "C-tier", "D-tier", "C\u7ea7", "D\u7ea7"}

PLACEHOLDER_OR_INSTRUCTION_MARKERS = {
    "concrete detail",
    "end by making",
    "making the next step concrete",
    "chapter focus",
    "move at least",
    "name the first",
    "distinctive procedure",
    "scene-specific evidence movement",
    "cannot solve the beat alone",
    "present this as belief",
    "not objective fact",
    "d-tier continuity hint",
    "tier continuity hint",
    "\u5177\u4f53\u7ec6\u8282",
    "\u5f00\u573a\u94a9\u5b50",
    "\u65b0\u4fe1\u606f",
    "\u672b\u5c3e\u94a9\u5b50",
}


def classify_issues(issue_codes: list[str]) -> tuple[list[str], list[str]]:
    repairable = [code for code in unique_strings(issue_codes) if code in REPAIRABLE_ISSUE_CODES]
    blocking = [code for code in unique_strings(issue_codes) if code in BLOCKING_ISSUE_CODES]
    return repairable, blocking


def language_for_text(text: str) -> str:
    return "zh" if CJK_RE.search(str(text or "")) else "en"


def contains_any(text: str, markers: set[str]) -> bool:
    lowered = str(text or "").casefold()
    return any(marker.casefold() in lowered for marker in markers)


def blocking_markers(text: str) -> list[str]:
    lowered = str(text or "").casefold()
    return unique_strings(
        [code for marker, code in RAW_BLOCKING_MARKERS.items() if marker.casefold() in lowered]
    )


def sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?\u3002\uff01\uff1f\n]+", str(text or "")) if part.strip()])


def word_count(text: str) -> int:
    cjk_count = len(CJK_RE.findall(str(text or "")))
    english_count = len(re.findall(r"[A-Za-z][A-Za-z'-]*", str(text or "")))
    return max(english_count, cjk_count // 2)


def safe_excerpt(text: str, limit: int = 220) -> str:
    value = " ".join(str(text or "").split())
    for marker in RAW_BLOCKING_MARKERS:
        value = re.sub(re.escape(marker), "[redacted-marker]", value, flags=re.IGNORECASE)
    return value[:limit]


def unique_strings(values: list[Any]) -> list[str]:
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
