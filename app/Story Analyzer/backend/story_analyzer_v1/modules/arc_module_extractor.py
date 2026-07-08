from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis.canonical_builder import load_canonical_chapters
from ..arcs.arc_store import major_arcs_path, read_json as read_arc_json, sub_arcs_path
from ..models.arcs import ArcCandidate
from ..models.common import EvidenceClaimType, GenerationMode, SourceSpecificity, make_evidence_ref
from ..models.modules import ModuleEnvelope
from .catalog_builder import build_module_catalog
from .module_store import arc_modules_path, write_json


SUB_ARC_MODULE_SPECS = [
    ("stage_function", "plot"),
    ("entry_exit_state", "plot"),
    ("stage_goal", "plot"),
    ("stage_question", "information"),
    ("dominant_conflict", "plot"),
    ("reader_experience", "rhythm"),
    ("turning_points", "plot"),
    ("state_changes_committed", "character"),
]

MAJOR_ARC_MODULE_SPECS = [
    ("reader_experience_progression", "rhythm"),
    ("major_turning_point", "plot"),
    ("major_exit_state", "plot"),
]

ALL_MODES = [
    GenerationMode.ORIGINAL_WRITING,
    GenerationMode.CONTINUATION_OR_REVISION,
    GenerationMode.HYBRID_ADAPTATION,
]


def load_confirmed_arcs(path: Path, schema_version: str) -> list[ArcCandidate]:
    if not path.exists():
        raise ValueError("Confirmed arc files are required before arc analysis")
    payload = read_arc_json(path)
    if payload.get("schema_version") != schema_version:
        raise ValueError(f"Invalid confirmed arc schema_version in {path}")
    if payload.get("status") != "user_confirmed":
        raise ValueError("Arc analysis can only use user_confirmed arcs")
    return [ArcCandidate.model_validate(item) for item in payload.get("arcs", [])]


def _chapter_evidence(
    chapter_numbers: list[int],
    claim_type: EvidenceClaimType = EvidenceClaimType.CANONICAL_CHAPTER,
) -> list[dict[str, Any]]:
    return [
        make_evidence_ref(
            claim_type=claim_type,
            ref_type="canonical_chapter",
            chapter_index=chapter_index,
        )
        for chapter_index in chapter_numbers
    ]


def _module_claim_type(module_id: str) -> EvidenceClaimType:
    if module_id in {"entry_exit_state", "state_changes_committed", "major_exit_state"}:
        return EvidenceClaimType.CHARACTER_DECISION
    if module_id in {"stage_question"}:
        return EvidenceClaimType.MYSTERY_STATE_CHANGE
    return EvidenceClaimType.SCENE_TURN


def _hybrid_content(arc: ArcCandidate, module_id: str, extracted_value: Any) -> dict[str, Any]:
    return {
        "arc_id": arc.arc_candidate_id,
        "parent_arc_id": arc.parent_candidate_id,
        "chapters_included": arc.chapters_included,
        "boundary_signals": arc.boundary_signals,
        "extracted_value": extracted_value,
        "reusable_mechanism": {
            "module_id": module_id,
            "mechanism": "Preserve the narrative function and transition logic, not the original names or setting.",
            "boundary_reason": {
                "starts_here": arc.why_boundary_starts_here,
                "ends_here": arc.why_boundary_ends_here,
            },
        },
        "source_specific_elements": [
            {
                "element_type": "chapter_range",
                "value": arc.chapters_included,
            }
        ],
        "replacement_required": True,
        "replacement_suggestions": [
            "Replace source-specific names, settings, and surface events while keeping this stage function.",
        ],
    }


def _sub_arc_value(arc: ArcCandidate, module_id: str) -> Any:
    if module_id == "stage_function":
        return {
            "stage_goal": arc.stage_goal,
            "dominant_conflict": arc.dominant_conflict,
            "boundary_score": arc.boundary_score,
        }
    if module_id == "entry_exit_state":
        return {
            "entry_state": arc.entry_state,
            "exit_state": arc.exit_state,
        }
    if module_id == "stage_goal":
        return arc.stage_goal
    if module_id == "stage_question":
        return arc.stage_question
    if module_id == "dominant_conflict":
        return arc.dominant_conflict
    if module_id == "reader_experience":
        return arc.dominant_reader_experience
    if module_id == "turning_points":
        return arc.turning_points
    if module_id == "state_changes_committed":
        return {
            "entry_state": arc.entry_state,
            "exit_state": arc.exit_state,
            "requires_semantic_chapter_analysis": not bool(arc.entry_state or arc.exit_state),
        }
    return {}


def _major_arc_value(arc: ArcCandidate, module_id: str, child_sub_arcs: list[ArcCandidate]) -> Any:
    if module_id == "reader_experience_progression":
        return [
            {
                "sub_arc_id": child.arc_candidate_id,
                "chapters_included": child.chapters_included,
                "reader_experience": child.dominant_reader_experience,
            }
            for child in child_sub_arcs
        ]
    if module_id == "major_turning_point":
        return {
            "turning_points": arc.turning_points,
            "boundary_signals": arc.boundary_signals,
        }
    if module_id == "major_exit_state":
        return {
            "exit_state": arc.exit_state,
            "child_exit_states": [
                {
                    "sub_arc_id": child.arc_candidate_id,
                    "exit_state": child.exit_state,
                }
                for child in child_sub_arcs
            ],
        }
    return {}


def _make_module(
    *,
    arc: ArcCandidate,
    module_id: str,
    module_type: str,
    scope: str,
    content: dict[str, Any],
    depends_on: list[str] | None = None,
) -> ModuleEnvelope:
    return ModuleEnvelope(
        module_id=module_id,
        module_instance_id=f"{arc.arc_candidate_id}_{module_id}",
        scope=scope,
        module_type=module_type,
        source_specificity=SourceSpecificity.HYBRID,
        recommended_modes=ALL_MODES,
        confidence_score=max(0.35, arc.confidence_score),
        evidence_refs=_chapter_evidence(arc.chapters_included, _module_claim_type(module_id)),
        depends_on=depends_on or [],
        content=content,
    )


def analyze_arc_modules(run_dir: str | Path) -> dict[str, Any]:
    load_canonical_chapters(run_dir)
    major_arcs = load_confirmed_arcs(major_arcs_path(run_dir), "story_analyzer.major_arcs.v1")
    sub_arcs = load_confirmed_arcs(sub_arcs_path(run_dir), "story_analyzer.sub_arcs.v1")
    children_by_major: dict[str, list[ArcCandidate]] = {arc.arc_candidate_id: [] for arc in major_arcs}
    for sub_arc in sub_arcs:
        if sub_arc.parent_candidate_id in children_by_major:
            children_by_major[sub_arc.parent_candidate_id].append(sub_arc)

    modules: list[ModuleEnvelope] = []
    for sub_arc in sub_arcs:
        for module_id, module_type in SUB_ARC_MODULE_SPECS:
            modules.append(
                _make_module(
                    arc=sub_arc,
                    module_id=module_id,
                    module_type=module_type,
                    scope="sub_arc",
                    content=_hybrid_content(sub_arc, module_id, _sub_arc_value(sub_arc, module_id)),
                )
            )

    for major_arc in major_arcs:
        for module_id, module_type in MAJOR_ARC_MODULE_SPECS:
            modules.append(
                _make_module(
                    arc=major_arc,
                    module_id=module_id,
                    module_type=module_type,
                    scope="major_arc",
                    content=_hybrid_content(
                        major_arc,
                        module_id,
                        _major_arc_value(major_arc, module_id, children_by_major.get(major_arc.arc_candidate_id, [])),
                    ),
                    depends_on=[
                        f"{child.arc_candidate_id}_reader_experience"
                        for child in children_by_major.get(major_arc.arc_candidate_id, [])
                    ]
                    if module_id == "reader_experience_progression"
                    else [],
                )
            )

    payload = {
        "schema_version": "story_analyzer.arc_modules.v1",
        "status": "built_from_user_confirmed_arcs",
        "source_arcs": {
            "major_arcs_ref": "arcs/major_arcs.json",
            "sub_arcs_ref": "arcs/sub_arcs.json",
        },
        "module_count": len(modules),
        "modules": [module.model_dump(mode="json") for module in modules],
    }
    write_json(arc_modules_path(run_dir), payload)
    build_module_catalog(run_dir)
    return payload
