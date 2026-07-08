from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis.canonical_builder import load_canonical_chapters
from ..arcs.arc_store import major_arcs_path, sub_arcs_path
from ..models.arcs import ArcCandidate
from ..models.common import EvidenceClaimType, GenerationMode, SourceSpecificity, make_evidence_ref
from ..models.modules import ModuleEnvelope
from .arc_module_extractor import load_confirmed_arcs
from .catalog_builder import build_module_catalog
from .conflict_report import build_module_conflict_report
from .module_store import arc_modules_path, book_modules_path, read_json, write_json


BOOK_MODULE_SPECS = [
    ("story_rhythm_framework", "rhythm", SourceSpecificity.TRANSFERABLE),
    ("structure_node_graph", "plot", SourceSpecificity.HYBRID),
    ("reader_experience_curve", "rhythm", SourceSpecificity.HYBRID),
    ("conflict_escalation_framework", "plot", SourceSpecificity.TRANSFERABLE),
    ("information_release_framework", "information", SourceSpecificity.HYBRID),
    ("theme_module", "theme", SourceSpecificity.HYBRID),
    ("multi_protagonist_arc_module", "character", SourceSpecificity.HYBRID),
    ("relationship_dynamics_module", "relationship", SourceSpecificity.HYBRID),
]

ALL_MODES = [
    GenerationMode.ORIGINAL_WRITING,
    GenerationMode.CONTINUATION_OR_REVISION,
    GenerationMode.HYBRID_ADAPTATION,
]


def _load_arc_module_ids(run_dir: str | Path) -> set[str]:
    path = arc_modules_path(run_dir)
    if not path.exists():
        raise ValueError("Arc modules are required before building book modules")
    payload = read_json(path)
    if payload.get("schema_version") != "story_analyzer.arc_modules.v1":
        raise ValueError("Invalid arc_modules schema_version")
    return {module["module_instance_id"] for module in payload.get("modules", [])}


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
    if module_id == "information_release_framework":
        return EvidenceClaimType.MYSTERY_STATE_CHANGE
    if module_id == "multi_protagonist_arc_module":
        return EvidenceClaimType.CHARACTER_DECISION
    if module_id == "relationship_dynamics_module":
        return EvidenceClaimType.RELATIONSHIP_SHIFT
    if module_id == "theme_module":
        return EvidenceClaimType.CANONICAL_CHAPTER
    return EvidenceClaimType.SCENE_TURN


def _sub_arc_nodes(sub_arcs: list[ArcCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "arc_id": arc.arc_candidate_id,
            "parent_arc_id": arc.parent_candidate_id,
            "chapters_included": arc.chapters_included,
            "boundary_signals": arc.boundary_signals,
            "stage_goal": arc.stage_goal,
            "stage_question": arc.stage_question,
            "dominant_conflict": arc.dominant_conflict,
            "reader_experience": arc.dominant_reader_experience,
        }
        for arc in sub_arcs
    ]


def _hybrid_fields(module_id: str, source_elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reusable_mechanism": {
            "module_id": module_id,
            "mechanism": "Use the extracted structural relation as a reusable generation constraint.",
        },
        "source_specific_elements": source_elements,
        "replacement_required": True,
        "replacement_suggestions": [
            "Replace source-specific names, events, and settings while preserving this structural mechanism.",
        ],
    }


def _book_content(
    module_id: str,
    major_arcs: list[ArcCandidate],
    sub_arcs: list[ArcCandidate],
    source_specificity: SourceSpecificity,
) -> dict[str, Any]:
    nodes = _sub_arc_nodes(sub_arcs)
    source_elements = [
        {
            "element_type": "confirmed_arc",
            "arc_id": arc.arc_candidate_id,
            "chapters_included": arc.chapters_included,
        }
        for arc in [*major_arcs, *sub_arcs]
    ]

    if module_id == "story_rhythm_framework":
        content = {
            "rhythm_nodes": [
                {
                    "position": index + 1,
                    "chapter_span": arc.chapters_included,
                    "structural_role": "confirmed narrative stage",
                    "boundary_signal_count": len(arc.boundary_signals),
                }
                for index, arc in enumerate(sub_arcs)
            ],
            "reusable_mechanism": {
                "module_id": module_id,
                "mechanism": "Generate the book through confirmed stage transitions instead of fixed chapter batches.",
            },
        }
    elif module_id == "structure_node_graph":
        content = {
            "nodes": nodes,
            "edges": [
                {
                    "from": sub_arcs[index].arc_candidate_id,
                    "to": sub_arcs[index + 1].arc_candidate_id,
                    "edge_type": "next_stage",
                }
                for index in range(max(0, len(sub_arcs) - 1))
            ],
        }
    elif module_id == "reader_experience_curve":
        content = {
            "curve": [
                {
                    "arc_id": arc.arc_candidate_id,
                    "position": index + 1,
                    "reader_experience": arc.dominant_reader_experience,
                }
                for index, arc in enumerate(sub_arcs)
            ]
        }
    elif module_id == "conflict_escalation_framework":
        content = {
            "escalation_steps": [
                {
                    "arc_id": arc.arc_candidate_id,
                    "position": index + 1,
                    "dominant_conflict": arc.dominant_conflict,
                    "boundary_score": arc.boundary_score,
                }
                for index, arc in enumerate(sub_arcs)
            ],
            "reusable_mechanism": {
                "module_id": module_id,
                "mechanism": "Escalate conflict at confirmed semantic boundaries.",
            },
        }
    elif module_id == "information_release_framework":
        content = {
            "release_points": [
                {
                    "arc_id": arc.arc_candidate_id,
                    "stage_question": arc.stage_question,
                    "boundary_signals": arc.boundary_signals,
                }
                for arc in sub_arcs
            ]
        }
    elif module_id == "theme_module":
        content = {
            "theme_candidates": [],
            "requires_semantic_chapter_analysis": True,
            "evidence_basis": "canonical chapter skeleton plus confirmed arcs",
        }
    elif module_id == "multi_protagonist_arc_module":
        content = {
            "protagonist_arcs": [],
            "arc_weight_definition": "Structural weight in the confirmed book arc, not literary value.",
            "requires_semantic_chapter_analysis": True,
        }
    elif module_id == "relationship_dynamics_module":
        content = {
            "relationship_dynamics": [],
            "requires_semantic_chapter_analysis": True,
        }
    else:
        content = {}

    if source_specificity == SourceSpecificity.HYBRID:
        content.update(_hybrid_fields(module_id, source_elements))
    return content


def _dependencies_for(module_id: str, arc_module_ids: set[str], sub_arcs: list[ArcCandidate]) -> list[str]:
    if module_id in {"story_rhythm_framework", "structure_node_graph"}:
        return [
            f"{arc.arc_candidate_id}_stage_function"
            for arc in sub_arcs
            if f"{arc.arc_candidate_id}_stage_function" in arc_module_ids
        ]
    if module_id == "reader_experience_curve":
        return [
            f"{arc.arc_candidate_id}_reader_experience"
            for arc in sub_arcs
            if f"{arc.arc_candidate_id}_reader_experience" in arc_module_ids
        ]
    if module_id == "conflict_escalation_framework":
        return [
            f"{arc.arc_candidate_id}_dominant_conflict"
            for arc in sub_arcs
            if f"{arc.arc_candidate_id}_dominant_conflict" in arc_module_ids
        ]
    if module_id == "information_release_framework":
        return [
            f"{arc.arc_candidate_id}_stage_question"
            for arc in sub_arcs
            if f"{arc.arc_candidate_id}_stage_question" in arc_module_ids
        ]
    return []


def build_book_modules(run_dir: str | Path) -> dict[str, Any]:
    chapters = sorted(load_canonical_chapters(run_dir), key=lambda chapter: chapter.chapter_index)
    chapter_numbers = [chapter.chapter_index for chapter in chapters]
    major_arcs = load_confirmed_arcs(major_arcs_path(run_dir), "story_analyzer.major_arcs.v1")
    sub_arcs = load_confirmed_arcs(sub_arcs_path(run_dir), "story_analyzer.sub_arcs.v1")
    arc_module_ids = _load_arc_module_ids(run_dir)

    modules: list[ModuleEnvelope] = []
    for module_id, module_type, source_specificity in BOOK_MODULE_SPECS:
        modules.append(
            ModuleEnvelope(
                module_id=module_id,
                module_instance_id=f"book_{module_id}_001",
                scope="book",
                module_type=module_type,
                source_specificity=source_specificity,
                recommended_modes=ALL_MODES,
                confidence_score=0.55,
                evidence_refs=_chapter_evidence(chapter_numbers, _module_claim_type(module_id)),
                depends_on=_dependencies_for(module_id, arc_module_ids, sub_arcs),
                content=_book_content(module_id, major_arcs, sub_arcs, source_specificity),
            )
        )

    payload = {
        "schema_version": "story_analyzer.book_modules.v1",
        "status": "built_from_confirmed_arcs",
        "source_refs": {
            "arc_modules_ref": "modules/arc_modules.json",
            "major_arcs_ref": "arcs/major_arcs.json",
            "sub_arcs_ref": "arcs/sub_arcs.json",
        },
        "module_count": len(modules),
        "modules": [module.model_dump(mode="json") for module in modules],
    }
    write_json(book_modules_path(run_dir), payload)
    build_module_catalog(run_dir)
    build_module_conflict_report(run_dir)
    return payload
