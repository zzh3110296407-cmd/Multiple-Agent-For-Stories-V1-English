from __future__ import annotations

import re

from app.backend.models.writer_prose_engine import (
    ProseStyleInspectionReport,
    ProseStyleProfile,
    WriterProseDraftPackage,
)
from app.backend.services.writer_quality_shared import (
    ABSTRACT_MARKERS,
    EMPTY_MYSTERY_MARKERS,
    PLACEHOLDER_OR_INSTRUCTION_MARKERS,
    classify_issues,
    contains_any,
    word_count,
)


class ProseStyleInspectorService:
    def inspect(
        self,
        package: WriterProseDraftPackage,
        profile: ProseStyleProfile | None = None,
    ) -> ProseStyleInspectionReport:
        style = profile or ProseStyleProfile(style_profile_id=package.style_profile_id)
        text = package.candidate_prose
        issue_codes: list[str] = []
        metaphor_markers = {"like a", "as if", "sea of", "ocean of", "\u50cf", "\u4eff\u4f5b", "\u5982\u540c"}
        metaphor_density = round(
            sum(1 for marker in metaphor_markers if marker.casefold() in text.casefold())
            / max(1, word_count(text)),
            4,
        )
        repeated = [
            sentence
            for sentence, count in _sentence_counts(text).items()
            if count >= 2 and len(sentence) >= 8
        ]
        plain_score = max(
            0.0,
            round(1.0 - package.abstract_language_density - package.adjective_density - metaphor_density, 4),
        )
        if package.abstract_language_density > style.scene_style.abstract_language_budget or contains_any(
            text,
            ABSTRACT_MARKERS,
        ):
            issue_codes.append("abstract_language_too_high")
        if package.adjective_density > style.adjective_budget:
            issue_codes.append("adjective_density_high")
        if package.empty_mystery_density > style.suspense_style.empty_mystery_budget or contains_any(
            text,
            EMPTY_MYSTERY_MARKERS,
        ):
            issue_codes.append("empty_mystery_too_high")
        if metaphor_density > style.metaphor_budget:
            issue_codes.append("over_poetic_metaphor")
        if plain_score < 0.45:
            issue_codes.append("plain_language_profile_failed")
        if contains_any(text, PLACEHOLDER_OR_INSTRUCTION_MARKERS):
            issue_codes.append("placeholder_or_instruction_text_leak")

        repairable, blocking = classify_issues(issue_codes)
        return ProseStyleInspectionReport(
            prose_style_inspection_report_id=f"prose_style_report_{package.draft_package_id}",
            source_draft_package_id=package.draft_package_id,
            abstract_language_density=package.abstract_language_density,
            adjective_density=package.adjective_density,
            empty_mystery_density=package.empty_mystery_density,
            metaphor_density=metaphor_density,
            repeated_poetic_patterns=repeated,
            plain_language_score=plain_score,
            issue_codes=issue_codes,
            repairable_issue_codes=repairable,
            blocking_issue_codes=blocking,
            passed=not issue_codes,
            candidate_only=True,
        )


def _sentence_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sentence in re.split(r"[.!?\u3002\uff01\uff1f\n]+", str(text or "")):
        normalized = " ".join(sentence.casefold().split())
        if normalized:
            counts[normalized] = counts.get(normalized, 0) + 1
    return counts
