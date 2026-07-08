from __future__ import annotations

from ..models.canonical import BoundarySignals


MAJOR_BOUNDARY_SIGNALS = {
    "setting_or_social_system_changed",
    "identity_state_changed",
    "major_question_answered",
    "time_or_space_jump",
}


def active_boundary_signals(signals: BoundarySignals) -> list[str]:
    return [name for name, value in signals.model_dump().items() if value is True]


def boundary_score(signal_names: list[str]) -> float:
    if not signal_names:
        return 0.0
    major_signal_count = len(MAJOR_BOUNDARY_SIGNALS.intersection(signal_names))
    score = 0.55 + 0.1 * len(signal_names) + 0.1 * major_signal_count
    return min(score, 1.0)


def starts_major_arc(signal_names: list[str]) -> bool:
    return bool(MAJOR_BOUNDARY_SIGNALS.intersection(signal_names))
