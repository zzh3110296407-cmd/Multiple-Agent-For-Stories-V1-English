from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.models.character import Character
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.services.project_creation_service import ProjectCreationService
from app.backend.services.project_story_premise_service import (
    FORBIDDEN_DEMO_DEFAULTS,
    PROJECT_STORY_PREMISE_MISSING,
    ProjectStoryPremiseBlocked,
    ProjectStoryPremiseService,
)
from app.backend.services.prompt_anchor_classification_service import (
    classify_project_story_premise,
    extract_positive_prompt_terms,
    is_prompt_anchor_candidate,
)
from app.backend.storage.json_store import JsonStore, StorageError


CHARACTER_PROJECT_STORY_PREMISE_MISSING = "character_project_story_premise_missing"
CHARACTER_PROMPT_FIDELITY_MISSING = "character_prompt_fidelity_missing"
CHARACTER_PROMPT_ABSORPTION_MISSING = "character_prompt_absorption_missing"
CHARACTER_DUPLICATE_NAME = "character_duplicate_name"
CHARACTER_DUPLICATE_STORY_FUNCTION = "character_duplicate_story_function"
CHARACTER_DUPLICATE_ACTIVE_GOAL = "character_duplicate_active_goal"
CHARACTER_TIER_MISMATCH = "character_tier_mismatch"
CHARACTER_DEMO_DEFAULT_LEAK = "character_demo_default_leak"

ROLE_GENERATION_PROJECT_STORY_PREMISE_MISSING = "role_generation_project_story_premise_missing"
ROLE_GENERATION_PROMPT_FIDELITY_MISSING = "role_generation_prompt_fidelity_missing"
ROLE_GENERATION_PROMPT_ABSORPTION_MISSING = "role_generation_prompt_absorption_missing"
ROLE_GENERATION_DUPLICATE_NAME = "role_generation_duplicate_name"
ROLE_GENERATION_DUPLICATE_STORY_FUNCTION = "role_generation_duplicate_story_function"
ROLE_GENERATION_DUPLICATE_ACTIVE_GOAL = "role_generation_duplicate_active_goal"
ROLE_GENERATION_TIER_MISMATCH = "role_generation_tier_mismatch"
ROLE_GENERATION_DEMO_DEFAULT_LEAK = "role_generation_demo_default_leak"

LOCAL_PROJECT_ID = "local_project"
PROMPT_MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){2,}\b")
CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
ASCII_TERM_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_\-]{2,}\b")

GENERIC_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "but",
    "can",
    "character",
    "characters",
    "create",
    "draft",
    "generate",
    "generated",
    "generation",
    "hint",
    "main",
    "marker",
    "markers",
    "must",
    "one",
    "phase85",
    "project",
    "prompt",
    "role",
    "story",
    "tier",
    "user",
    "with",
    "world",
    "canvas",
}

PROMPT_FIDELITY_META_TERM_MARKERS = (
    "用户提供",
    "用户输入",
    "提示词",
    "原典提示",
    "文言原文",
    "原文中出现",
    "明确指涉",
    "创作一部",
    "长篇中文故事",
    "故事人物",
    "只能来自",
    "只能来源",
    "不得",
    "现代校园",
    "现代侦探",
    "模板",
    "非原文",
    "每章",
    "每幕",
    "要求",
    "角色可自主",
    "自主行动",
    "心理推进",
    "冲突转折",
    "主角自述",
    "主角奔走",
    "主角在现实",
)
PROMPT_FIDELITY_GENERIC_CJK_TERMS = {
    "人物",
    "角色",
    "故事",
    "神灵",
    "君主",
    "历史人物",
    "媒介者",
    "象征性人格",
    "媒介者与象征性人格",
}

EXPLICIT_MIRROR_TERMS = {
    "intentional mirror",
    "intentional duplicate",
    "mirror role",
    "mirrored role",
    "parallel function",
    "deliberate echo",
    "mirror",
    "\u955c\u50cf",
    "\u5e73\u884c\u5bf9\u7167",
    "\u6709\u610f\u91cd\u590d",
    "\u590d\u523b",
}


def model_to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, BaseModel):
        return value.dict()
    if isinstance(value, list):
        return [model_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): model_to_plain(item) for key, item in value.items()}
    return value


def compact_json_text(value: Any) -> str:
    return json.dumps(model_to_plain(value), ensure_ascii=False, sort_keys=True)


def project_registry_data_dir(data_dir: Path) -> Path:
    if data_dir.parent.name == "projects":
        return data_dir.parent.parent / LOCAL_PROJECT_ID
    return data_dir


def project_requires_story_premise(
    *,
    store: JsonStore,
    data_dir: Path,
    project_id: str,
    project_file: Path | None = None,
) -> bool:
    if project_file and store.exists(project_file):
        try:
            project = store.read(project_file)
        except StorageError:
            project = {}
        if str(project.get("origin_type") or "") == "prompt_first":
            return True
    try:
        origin = ProjectCreationService(
            store=store,
            data_dir=project_registry_data_dir(data_dir),
        ).get_project_origin(project_id)
    except StorageError:
        return False
    return bool(origin.is_prompt_first or origin.origin_type == "prompt_first")


def require_project_story_premise_for_generation(
    *,
    store: JsonStore,
    data_dir: Path,
    project_id: str,
    missing_code: str,
    project_file: Path | None = None,
) -> ProjectStoryPremise | None:
    service = ProjectStoryPremiseService(store=store, data_dir=data_dir)
    try:
        premise = service.read_from_story_data_dir(project_id, data_dir)
    except ProjectStoryPremiseBlocked as exc:
        raise StorageError(f"{missing_code}: {exc}") from exc
    if premise and premise.blocking_issues:
        raise StorageError(f"{missing_code}: {','.join(premise.blocking_issues)}")
    if premise and premise.source_status != "controlled_prompt":
        raise StorageError(f"{missing_code}: source_not_controlled_prompt")
    if not premise and project_requires_story_premise(
        store=store,
        data_dir=data_dir,
        project_id=project_id,
        project_file=project_file,
    ):
        raise StorageError(f"{missing_code}: {PROJECT_STORY_PREMISE_MISSING}")
    return premise


def try_read_project_story_premise(
    *,
    store: JsonStore,
    data_dir: Path,
    project_id: str,
) -> ProjectStoryPremise | None:
    try:
        return ProjectStoryPremiseService(
            store=store,
            data_dir=data_dir,
        ).read_from_story_data_dir(project_id, data_dir)
    except (ProjectStoryPremiseBlocked, StorageError):
        return None


def story_facing_character_payload(character: Character) -> dict[str, Any]:
    profile = character.profile
    baseline = profile.personality_baseline
    state = character.current_state
    arc = character.arc_state
    memory = character.memory_summary
    return {
        "name": character.name,
        "tier": character.tier,
        "role": character.role,
        "profile": {
            "description": profile.description,
            "identity": profile.identity,
            "story_function": profile.story_function,
            "background_summary": profile.background_summary,
            "species_or_group": profile.species_or_group,
            "faction_or_origin": profile.faction_or_origin,
            "appearance_summary": profile.appearance_summary,
            "traits": profile.traits,
            "goals": profile.goals,
            "fears": profile.fears,
            "secrets": profile.secrets,
            "personality_baseline": {
                "traits": baseline.traits,
                "values": baseline.values,
                "bottom_line": baseline.bottom_line,
                "speech_style_hint": baseline.speech_style_hint,
            },
            "hard_limits": [
                {
                    "statement": limit.statement,
                    "reason": limit.reason,
                }
                for limit in profile.hard_limits
            ],
            "knowledge_scope": profile.knowledge_scope,
            "forbidden_knowledge": profile.forbidden_knowledge,
        },
        "current_state": {
            "emotional_state": state.emotional_state,
            "knowledge": state.knowledge,
            "active_goal": state.active_goal,
            "current_desire": state.current_desire,
            "current_fear": state.current_fear,
            "resources": state.resources,
            "secrets": state.secrets,
        },
        "arc_state": {
            "current_arc": arc.current_arc,
            "starting_point": arc.starting_point,
            "pressure": arc.pressure,
            "inner_conflict": arc.inner_conflict,
            "next_possible_change": arc.next_possible_change,
            "possible_direction": arc.possible_direction,
            "locked_future_events": arc.locked_future_events,
        },
        "memory_summary": {
            "summary": memory.summary,
            "open_threads": memory.open_threads,
        },
    }


def extract_prompt_terms(text: str, limit: int = 32) -> list[str]:
    return extract_positive_prompt_terms(text, limit=limit)
    source = str(text or "")
    terms: list[str] = []
    seen: set[str] = set()
    for marker in PROMPT_MARKER_RE.findall(source):
        if marker not in seen:
            seen.add(marker)
            terms.append(marker)
    for term in CJK_TERM_RE.findall(source):
        clean = term.strip()
        if clean and clean not in seen:
            seen.add(clean)
            terms.append(clean)
    for term in ASCII_TERM_RE.findall(source):
        clean = term.strip()
        lower = clean.lower()
        if lower in GENERIC_TERMS:
            continue
        if clean not in seen:
            seen.add(clean)
            terms.append(clean)
    return terms[:limit]


def premise_required_terms(premise: ProjectStoryPremise | None, limit: int = 40) -> list[str]:
    if not premise:
        return []
    return classify_project_story_premise(premise, limit=limit).positive_required_anchors[:limit]
    marker_set = set(premise.prompt_fidelity_contract.required_markers)
    candidates = [
        *marker_set,
        *premise.role_terms,
        *premise.required_story_elements,
        *premise.core_terms,
        *premise.setting_terms,
        *premise.conflict_terms,
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = " ".join(str(candidate or "").split()).strip()
        if not clean or clean in seen:
            continue
        if clean.lower() in GENERIC_TERMS:
            continue
        if not is_story_anchor_prompt_term(clean):
            continue
        if clean in marker_set or len(clean) >= 3 or any("\u4e00" <= char <= "\u9fff" for char in clean):
            seen.add(clean)
            terms.append(clean)
    return terms[:limit]


def is_story_anchor_prompt_term(value: str) -> bool:
    return is_prompt_anchor_candidate(value)
    clean = " ".join(str(value or "").split()).strip()
    if not clean:
        return False
    lowered = clean.lower()
    if lowered in GENERIC_TERMS:
        return False
    if clean in PROMPT_FIDELITY_GENERIC_CJK_TERMS:
        return False
    if clean.startswith("-") or clean.startswith("要求"):
        return False
    if any(marker in clean for marker in PROMPT_FIDELITY_META_TERM_MARKERS):
        return False
    if len(clean) > 18 and not PROMPT_MARKER_RE.fullmatch(clean):
        return False
    return True


def first_prompt_evidence(text: str, limit: int = 6) -> str:
    return " ".join(extract_prompt_terms(text, limit=limit))


def first_premise_evidence(premise: ProjectStoryPremise | None, limit: int = 8) -> str:
    if not premise:
        return ""
    parts = []
    if premise.safe_user_story_summary:
        parts.append(premise.safe_user_story_summary)
    terms = premise_required_terms(premise, limit=limit)
    if terms:
        parts.append(" ".join(terms))
    return " ".join(parts)[:420]


def prompt_absorption_coverage(
    *,
    character: Character,
    premise: ProjectStoryPremise | None,
    latest_user_prompt: str,
) -> dict[str, Any]:
    story_text = compact_json_text(story_facing_character_payload(character))
    prompt_terms = extract_prompt_terms(latest_user_prompt)
    premise_terms = premise_required_terms(premise)
    prompt_hits = [term for term in prompt_terms if term and term in story_text]
    premise_hits = [term for term in premise_terms if term and term in story_text]
    demo_default_count = sum(story_text.count(default) for default in FORBIDDEN_DEMO_DEFAULTS)
    return {
        "prompt_terms": prompt_terms,
        "prompt_hits": prompt_hits,
        "prompt_hit_count": len(prompt_hits),
        "premise_terms": premise_terms,
        "premise_hits": premise_hits,
        "premise_hit_count": len(premise_hits),
        "demo_default_count": demo_default_count,
        "coverage_scope": "character_story_facing_fields_only",
    }


def prompt_hit_matches_premise_anchor(
    *,
    coverage: dict[str, Any],
    premise: ProjectStoryPremise | None,
) -> bool:
    if not premise:
        return False
    prompt_hits = [
        str(term or "").strip()
        for term in coverage.get("prompt_hits", [])
        if len(str(term or "").strip()) >= 2
    ]
    if not prompt_hits:
        return False
    premise_anchors = [
        *premise.role_terms,
        *premise.required_story_elements,
        *premise.core_terms,
        *premise.setting_terms,
        *premise.conflict_terms,
    ]
    clean_anchors = [
        " ".join(str(anchor or "").split()).strip()
        for anchor in premise_anchors
        if str(anchor or "").strip()
    ]
    for hit in prompt_hits:
        for anchor in clean_anchors:
            if hit == anchor or hit in anchor or anchor in hit:
                return True
    return False


def normalize_for_duplicate(value: str) -> str:
    return re.sub(r"[\s\u3000,.;:!?，。；：！？\"'`]+", "", str(value or "")).lower()


def prompt_allows_mirror(user_prompt: str) -> bool:
    lower = str(user_prompt or "").lower()
    return any(term in lower for term in EXPLICIT_MIRROR_TERMS)


def validate_character_prompt_absorption(
    *,
    character: Character,
    requested_tier: str,
    existing_characters: list[Character],
    premise: ProjectStoryPremise | None,
    latest_user_prompt: str,
    issue_prefix: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    if issue_prefix == "character":
        codes = {
            "premise": CHARACTER_PROJECT_STORY_PREMISE_MISSING,
            "fidelity": CHARACTER_PROMPT_FIDELITY_MISSING,
            "absorption": CHARACTER_PROMPT_ABSORPTION_MISSING,
            "name": CHARACTER_DUPLICATE_NAME,
            "function": CHARACTER_DUPLICATE_STORY_FUNCTION,
            "goal": CHARACTER_DUPLICATE_ACTIVE_GOAL,
            "tier": CHARACTER_TIER_MISMATCH,
            "demo": CHARACTER_DEMO_DEFAULT_LEAK,
        }
    else:
        codes = {
            "premise": ROLE_GENERATION_PROJECT_STORY_PREMISE_MISSING,
            "fidelity": ROLE_GENERATION_PROMPT_FIDELITY_MISSING,
            "absorption": ROLE_GENERATION_PROMPT_ABSORPTION_MISSING,
            "name": ROLE_GENERATION_DUPLICATE_NAME,
            "function": ROLE_GENERATION_DUPLICATE_STORY_FUNCTION,
            "goal": ROLE_GENERATION_DUPLICATE_ACTIVE_GOAL,
            "tier": ROLE_GENERATION_TIER_MISMATCH,
            "demo": ROLE_GENERATION_DEMO_DEFAULT_LEAK,
        }

    blocking: list[str] = []
    warnings: list[str] = []
    requested = str(requested_tier or "").upper()
    if character.tier != requested:
        blocking.append(codes["tier"])

    coverage = prompt_absorption_coverage(
        character=character,
        premise=premise,
        latest_user_prompt=latest_user_prompt,
    )
    has_prompt_premise_anchor = prompt_hit_matches_premise_anchor(
        coverage=coverage,
        premise=premise,
    )
    if not premise:
        blocking.append(codes["premise"])
    elif coverage["premise_terms"] and coverage["premise_hit_count"] == 0:
        if has_prompt_premise_anchor:
            warnings.append(f"{codes['fidelity']}:prompt_anchor")
        else:
            blocking.append(codes["fidelity"])
    elif (
        coverage["premise_terms"]
        and coverage["premise_hit_count"] < min(2, len(coverage["premise_terms"]))
    ):
        if has_prompt_premise_anchor:
            warnings.append(f"{codes['fidelity']}:prompt_anchor")
        else:
            warnings.append(f"{codes['fidelity']}:weak")

    if coverage["prompt_terms"] and coverage["prompt_hit_count"] == 0:
        blocking.append(codes["absorption"])
    elif coverage["prompt_terms"] and coverage["prompt_hit_count"] < min(2, len(coverage["prompt_terms"])):
        warnings.append(f"{codes['absorption']}:weak")

    if coverage["demo_default_count"] > 0:
        blocking.append(codes["demo"])

    current_name = normalize_for_duplicate(character.name)
    current_function = normalize_for_duplicate(character.profile.story_function)
    current_goal = normalize_for_duplicate(character.current_state.active_goal)
    mirror_allowed = prompt_allows_mirror(latest_user_prompt)
    same_tier = [
        item
        for item in existing_characters
        if item.character_id != character.character_id and item.tier == requested
    ]
    all_existing = [
        item
        for item in existing_characters
        if item.character_id != character.character_id
    ]
    if current_name and any(normalize_for_duplicate(item.name) == current_name for item in all_existing):
        blocking.append(codes["name"])
    if current_function and any(
        normalize_for_duplicate(item.profile.story_function) == current_function
        for item in same_tier
    ):
        if mirror_allowed:
            warnings.append(f"{codes['function']}:intentional_mirror")
        elif requested in {"C", "D"}:
            warnings.append(f"{codes['function']}:tier_pool_overlap")
        else:
            blocking.append(codes["function"])
    if current_goal and any(
        normalize_for_duplicate(item.current_state.active_goal) == current_goal
        for item in same_tier
    ):
        if mirror_allowed:
            warnings.append(f"{codes['goal']}:intentional_mirror")
        else:
            blocking.append(codes["goal"])

    return unique_preserve_order(blocking), unique_preserve_order(warnings), coverage


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
