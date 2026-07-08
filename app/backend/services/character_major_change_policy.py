from typing import Any


MAJOR_CHANGE_TYPES = {
    "goal",
    "relationship",
    "knowledge",
    "secret",
    "health",
    "resource",
    "promise",
    "betrayal",
    "arc",
}

A_TIER_MAJOR_PATCH_PATHS = {
    "current_state.active_goal",
    "current_state.current_desire",
    "current_state.knowledge",
    "current_state.resources",
    "current_state.secrets",
    "profile.goals",
    "profile.secrets",
    "profile.hard_limits",
    "profile.knowledge_scope",
    "profile.forbidden_knowledge",
    "profile.personality_baseline.bottom_line",
    "relationship_refs",
}

A_TIER_MAJOR_PATCH_ROOTS = {"arc_state"}


def patch_paths(patch: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in patch.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.add(path)
        if isinstance(value, dict):
            paths.update(patch_paths(value, path))
    return paths


def a_tier_major_patch_paths(patch: dict[str, Any]) -> list[str]:
    return sorted(
        path
        for path in patch_paths(patch)
        if path in A_TIER_MAJOR_PATCH_PATHS
        or any(
            path == root or path.startswith(f"{root}.")
            for root in A_TIER_MAJOR_PATCH_ROOTS
        )
    )


def a_tier_change_requires_confirmation(
    change_type: str,
    impact_level: str,
    patch: dict[str, Any],
) -> bool:
    if impact_level == "major":
        return True
    if change_type in MAJOR_CHANGE_TYPES:
        return True
    return bool(a_tier_major_patch_paths(patch))
