from __future__ import annotations

from pydantic import BaseModel, Field


SCENE_PATTERN_SIMILARITY_WARNING = "scene_pattern_similarity_warning"
SCENE_PATTERN_SIMILARITY_TOO_HIGH = "scene_pattern_similarity_too_high"
CHAPTER_SCENE_BEATS_MISSING = "chapter_scene_beats_missing"
CHAPTER_SCENE_BEAT_MISSING_FOR_SCENE = "chapter_scene_beat_missing_for_scene"
SCENE_BEAT_DELTA_MISSING = "scene_beat_delta_missing"
SCENE_CONTINUITY_ANCHOR_MISUSED_AS_REPETITION = (
    "scene_continuity_anchor_misused_as_repetition"
)
SCENE_MEMORY_CONTEXT_DUPLICATE_AMPLIFICATION = (
    "scene_memory_context_duplicate_amplification"
)


class ScenePatternSignature(BaseModel):
    signature_id: str = ""
    project_id: str = ""
    chapter_id: str = ""
    scene_id: str = ""
    scene_index: int = 1
    source_target_type: str = "scene"
    source_target_id: str = ""

    scene_function_family: str = "unknown"
    action_mode: str = "unknown"
    setting_signature: str = "unknown"
    time_signature: str = "unknown"
    cast_signature: list[str] = Field(default_factory=list)
    cast_tier_signature: list[str] = Field(default_factory=list)

    information_delta_type: str = "unknown"
    character_state_delta_type: str = "unknown"
    conflict_turn_type: str = "unknown"
    ending_hook_type: str = "unknown"

    has_new_information: bool = False
    has_character_state_delta: bool = False
    has_conflict_turn: bool = False
    has_cost_or_risk_delta: bool = False
    has_distinct_ending_hook: bool = False

    text_fingerprint: str = ""
    source_refs: list[str] = Field(default_factory=list)


class ScenePatternSimilarityAxisScore(BaseModel):
    axis: str
    score: float = 0.0
    weight: float = 1.0
    reason: str = ""


class ScenePatternSimilarityFinding(BaseModel):
    code: str
    severity: str = "info"
    verdict: str = "pass"
    machine_repairable: bool = True
    user_visible: bool = False
    technical_summary: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    source_scene_ids: list[str] = Field(default_factory=list)
    suggested_repair_focus: list[str] = Field(default_factory=list)


class ScenePatternSimilarityReport(BaseModel):
    report_id: str = ""
    target_type: str = "scene"
    target_id: str = ""
    scene_id: str = ""
    chapter_id: str = ""
    scene_index: int = 1
    current_signature: ScenePatternSignature = Field(
        default_factory=ScenePatternSignature
    )
    compared_signature_ids: list[str] = Field(default_factory=list)
    axis_scores: list[ScenePatternSimilarityAxisScore] = Field(default_factory=list)
    structural_similarity_score: float = 0.0
    text_similarity_score: float = 0.0
    verdict: str = "pass"
    findings: list[ScenePatternSimilarityFinding] = Field(default_factory=list)
    safe_to_show_user: bool = False
    source_refs: list[str] = Field(default_factory=list)
