"""Create transferable mechanism statements from canonical analysis facts."""

from __future__ import annotations


STAGE_BY_MACRO = {
    "macro_opening": "baseline_setup",
    "macro_inciting_incident": "threshold_call",
    "macro_development_escalation": "pressure_escalation",
    "macro_crisis_local_climax": "costly_choice_crisis",
    "macro_resolution_aftermath": "aftermath_and_future_debt",
    "macro_resolution_hook": "aftermath_and_future_debt",
}

MECHANISM_TEXT = {
    "baseline_setup": {
        "mechanism_type": "baseline_setup",
        "abstract_statement": "A stable but incomplete starting identity is established before external pressure arrives.",
        "input_state": "ordinary or emotionally unresolved baseline",
        "pressure": "latent dissatisfaction and weak external disturbance",
        "transition": "the narrative plants a gap between current life and a larger order",
        "output_state": "reader expects the protagonist to cross a threshold",
        "reader_experience": "orientation with controlled curiosity",
    },
    "threshold_call": {
        "mechanism_type": "identity_transition",
        "abstract_statement": "An outside system calls the protagonist across a threshold and makes refusal increasingly costly.",
        "input_state": "low-agency protagonist facing a hidden invitation",
        "pressure": "new rules expose a gap in the protagonist's self-understanding",
        "transition": "choice pressure turns curiosity into commitment",
        "output_state": "expanded conflict scope and a new identity obligation",
        "reader_experience": "wonder mixed with anxiety",
    },
    "pressure_escalation": {
        "mechanism_type": "conflict_escalation",
        "abstract_statement": "Local goals escalate into system-level conflict through repeated tests and partial revelations.",
        "input_state": "new identity is unstable and under-tested",
        "pressure": "external threats and incomplete information accumulate",
        "transition": "each test converts hidden rules into practical danger",
        "output_state": "stakes rise from survival to responsibility",
        "reader_experience": "accelerating tension and pattern recognition",
    },
    "costly_choice_crisis": {
        "mechanism_type": "costly_choice",
        "abstract_statement": "At peak pressure, the protagonist accepts a costly choice that resolves the immediate crisis while creating a longer debt.",
        "input_state": "insufficient power under maximum emotional pressure",
        "pressure": "immediate loss becomes unavoidable without sacrifice",
        "transition": "the protagonist trades safety, innocence, or future freedom for action",
        "output_state": "short-term victory with unresolved long-horizon cost",
        "reader_experience": "release, shock, and concern about consequences",
    },
    "aftermath_and_future_debt": {
        "mechanism_type": "aftermath_hook",
        "abstract_statement": "After the crisis, emotional residue and unresolved costs reframe the victory as an opening to the next arc.",
        "input_state": "crisis has ended but consequences remain active",
        "pressure": "relationships, identity, or world rules demand later payment",
        "transition": "quiet aftermath converts plot closure into future expectation",
        "output_state": "new baseline with visible unresolved debt",
        "reader_experience": "bittersweet closure and forward pull",
    },
}


def stage_from_macros(macros: list[str] | tuple[str, ...] | None) -> str:
    macros = list(macros or [])
    for macro in (
        "macro_crisis_local_climax",
        "macro_resolution_aftermath",
        "macro_resolution_hook",
        "macro_development_escalation",
        "macro_inciting_incident",
        "macro_opening",
    ):
        if macro in macros:
            return STAGE_BY_MACRO.get(macro, "pressure_escalation")
    return "pressure_escalation"


def mechanism_for_macros(macros: list[str] | tuple[str, ...] | None) -> dict:
    stage = stage_from_macros(macros)
    return dict(MECHANISM_TEXT[stage])


def build_abstract_mechanism_catalog(arcs: list[dict], chapters: list[dict] | None = None) -> dict:
    mechanisms: list[dict] = []
    for arc in arcs or []:
        macros = arc.get("arc_macros") or arc.get("macro_components") or []
        mechanism = mechanism_for_macros(macros)
        mechanism.update(
            {
                "mechanism_id": f"M{len(mechanisms) + 1:03d}",
                "source_specificity": "transferable",
                "source_entities_removed": [],
                "structural_inputs": [mechanism["input_state"], mechanism["pressure"]],
                "structural_outputs": [mechanism["output_state"], mechanism["reader_experience"]],
                "blocked_source_terms": [],
                "evidence_refs": [
                    {
                        "source": "arc",
                        "arc_index": arc.get("arc_index"),
                        "source_chapter_range": arc.get("source_chapter_range") or arc.get("arc_chapter_range"),
                    }
                ],
            }
        )
        mechanisms.append(mechanism)

    return {
        "schema_version": "story_analyzer.abstract_mechanism_catalog.v1",
        "items": mechanisms,
        "mechanism_count": len(mechanisms),
    }
