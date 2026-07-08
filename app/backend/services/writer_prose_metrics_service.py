from __future__ import annotations

import re
from typing import Any


ABSTRACT_LANGUAGE_MARKERS = {
    "truth",
    "destiny",
    "fate",
    "mystery",
    "darkness",
    "silence",
    "fear",
    "hope",
    "meaning",
    "memory",
    "shadow",
    "unknown",
    "abstract",
    "uncertain",
}

EMPTY_MYSTERY_MARKERS = {
    "something",
    "somehow",
    "secret",
    "mysterious",
    "unknown",
    "unseen",
    "hidden truth",
    "no one knew",
    "only time would tell",
}

COMMON_ADJECTIVE_SUFFIXES = ("ive", "ous", "ful", "less", "al", "ic", "ary", "ent", "ant")
SAFE_ID_PATTERN = re.compile(
    r"\b(?:project|chapter|scene|char|memory|event|state|writer|beat_sheet|"
    r"scene_prose_plan|psych_visibility_plan|writer_planner_output)_[A-Za-z0-9_]+\b"
)


class WriterProseMetricsService:
    def density_report(self, text: str) -> dict[str, float]:
        words = self._words(text)
        if not words:
            return {
                "empty_mystery_density": 0.0,
                "abstract_language_density": 0.0,
                "adjective_density": 0.0,
            }
        lowered = " ".join(words)
        abstract_count = sum(1 for word in words if word in ABSTRACT_LANGUAGE_MARKERS)
        adjective_count = sum(
            1
            for word in words
            if len(word) > 4 and word.endswith(COMMON_ADJECTIVE_SUFFIXES)
        )
        empty_mystery_count = sum(1 for marker in EMPTY_MYSTERY_MARKERS if marker in lowered)
        denominator = max(1, len(words))
        return {
            "empty_mystery_density": round(empty_mystery_count / denominator, 4),
            "abstract_language_density": round(abstract_count / denominator, 4),
            "adjective_density": round(adjective_count / denominator, 4),
        }

    def contains_source_id(self, text: Any) -> bool:
        return bool(SAFE_ID_PATTERN.search(str(text or "")))

    def _words(self, text: str) -> list[str]:
        return [
            word.casefold()
            for word in re.findall(r"[A-Za-z][A-Za-z'-]*", str(text or ""))
            if word.strip()
        ]
