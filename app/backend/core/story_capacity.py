"""Shared story scale limits for the Phase 8.5 product workbench."""

CHAPTER_COUNT_MIN = 1
CHAPTER_COUNT_MAX = 20
DEFAULT_CHAPTER_COUNT = 5

SCENE_COUNT_MIN = 1
SCENE_COUNT_MAX = 20
DEFAULT_SCENE_COUNT = 5


def chapter_count_range_label() -> str:
    return f"{CHAPTER_COUNT_MIN} and {CHAPTER_COUNT_MAX}"


def scene_count_range_label() -> str:
    return f"{SCENE_COUNT_MIN} and {SCENE_COUNT_MAX}"


def clamp_chapter_count(value: int | str | None, *, default: int = DEFAULT_CHAPTER_COUNT) -> int:
    return _clamp_int(value, minimum=CHAPTER_COUNT_MIN, maximum=CHAPTER_COUNT_MAX, default=default)


def clamp_scene_count(value: int | str | None, *, default: int = DEFAULT_SCENE_COUNT) -> int:
    return _clamp_int(value, minimum=SCENE_COUNT_MIN, maximum=SCENE_COUNT_MAX, default=default)


def _clamp_int(value: int | str | None, *, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))
