from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError

from .arcs.candidate_segmenter import propose_arc_candidates
from .arcs.review_service import confirm_arc_candidates
from .analysis.canonical_builder import build_canonical_chapters
from .evidence.claim_extraction import extract_claims_from_value
from .evidence.evidence_retrieval import EVIDENCE_RETRIEVAL_VERSION, retrieve_evidence_for_claim
from .evidence.raw_source_index_builder import build_raw_source_index
from .generator_import.contract_fixture import (
    build_generator_import_fixture,
    validate_generator_import_fixture,
)
from .generator_handoff.handoff_repair import repair_generator_handoff
from .generator_handoff.handoff_validator import (
    build_http_semantic_validator,
    is_generator_handoff_deliverable,
    validate_generator_handoff,
)
from .handoff.compiler import compile_generator_handoff
from .handoff.exporter import export_handoff_package
from .handoff.validator import validate_handoff_package
from .ingestion.source_manifest_builder import (
    build_source_manifest,
    load_source_manifest,
    write_source_manifest,
)
from .legacy_adapter.v2_adapter import adapt_legacy_v2_outputs
from .modules.arc_module_extractor import analyze_arc_modules
from .modules.book_module_extractor import build_book_modules
from .modules.chapter_module_extractor import analyze_chapter_modules
from .modules.conflict_report import build_module_conflict_report
from .pipeline.orchestrator import continue_run, prepare_run
from .pipeline.resume import plan_downstream_rebuild, resume_from_invalidation
from .quality.metrics_report import build_quality_metrics_report
from .quality.quality_gate import run_quality_gate
from .regression.longzu_regression import run_longzu_regression
from .repair.targeted_repair import repair_chapter
from .semantic_provider.batch_runner import build_semantic_chapter_inputs
from .semantic_provider.providers import SemanticProviderError, build_semantic_provider
from .schema_exporter import export_model_schemas
from .state.pipeline_state import invalidate_for_change, record_pipeline_step
from .synthesis.cross_work import build_cross_work_pattern_synthesis
from .trackers.candidate_extractor import extract_tracker_candidates
from .trackers.edit_report import build_tracker_edit_report
from .trackers.foreshadowing_reconciler import reconcile_foreshadowing_tracker
from .trackers.manual_override import apply_tracker_manual_override, merge_tracker_items, split_tracker_item
from .trackers.mystery_reconciler import reconcile_mystery_tracker
from .trackers.relationship_debt_reconciler import reconcile_relationship_debt_tracker
from .trackers.world_rule_reveal_reconciler import reconcile_world_rule_reveal_tracker


STEP_STATUS_CHOICES = ["pending", "running", "completed", "failed", "blocked", "invalidated"]
TRACKER_TYPE_CHOICES = ["foreshadowing", "mystery", "relationship_debt", "world_rule_reveal"]
TRACKER_STATUS_CHOICES = ["open", "partially_resolved", "resolved", "abandoned", "uncertain"]
SEMANTIC_PROVIDER_CHOICES = ["mock", "http"]
GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_ENDPOINT_ENV = "GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_ENDPOINT"
GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_API_KEY_ENV_ENV = "GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_API_KEY_ENV"
CHANGE_TYPE_CHOICES = [
    "source_chapter_text_changed",
    "chapter_title_manual_corrected",
    "canonical_schema_compatible_changed",
    "chapter_repair_succeeded",
    "arc_boundary_user_adjusted",
    "tracker_manual_override",
    "module_envelope_schema_changed",
    "generator_profile_rule_changed",
]


def _add_generator_handoff_semantic_validator_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--semantic-validator-endpoint",
        default="",
        help=(
            "Optional HTTP endpoint for generator handoff source-fidelity semantic validation. "
            f"Falls back to {GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_ENDPOINT_ENV}."
        ),
    )
    parser.add_argument(
        "--semantic-validator-api-key-env",
        default="",
        help=(
            "Optional environment variable name containing the semantic validator bearer token. "
            f"Falls back to {GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_API_KEY_ENV_ENV}."
        ),
    )
    parser.add_argument(
        "--semantic-validator-timeout",
        type=float,
        default=60.0,
        help="HTTP semantic validator timeout in seconds.",
    )


def _generator_handoff_semantic_validator_from_args(args: argparse.Namespace):
    endpoint = (
        getattr(args, "semantic_validator_endpoint", "")
        or os.environ.get(GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_ENDPOINT_ENV, "")
    ).strip()
    if not endpoint:
        return None
    api_key_env = (
        getattr(args, "semantic_validator_api_key_env", "")
        or os.environ.get(GENERATOR_HANDOFF_SEMANTIC_VALIDATOR_API_KEY_ENV_ENV, "")
    ).strip()
    timeout_seconds = float(getattr(args, "semantic_validator_timeout", 60.0) or 60.0)
    return build_http_semantic_validator(
        endpoint,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
    )


def _parse_scope_items(items: list[str] | None) -> dict[str, object]:
    scope: dict[str, object] = {}
    for item in items or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise ValueError(f"scope must use key=value format: {item}")
        normalized_value: object = value
        if value.isdigit():
            normalized_value = int(value)
        elif value.lower() in {"true", "false"}:
            normalized_value = value.lower() == "true"
        scope[key] = normalized_value
    return scope


def _read_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _inspect_source(args: argparse.Namespace) -> int:
    manifest = build_source_manifest(args.input, work_title=args.title)
    manifest_path = write_source_manifest(manifest, args.out)
    record_pipeline_step(
        args.out,
        step_id="source_manifest",
        step_type="source_manifest",
        status="completed",
        input_fingerprints=[manifest.source_sha256],
        output_refs=[manifest_path.name],
    )
    print(f"Wrote source manifest: {manifest_path}")
    print(f"Chapters: {len(manifest.chapters)}")
    suspicious = [
        chapter
        for chapter in manifest.chapters
        if chapter.boundary_status != "ok" or chapter.title_status == "suspicious"
    ]
    if suspicious:
        print(f"Warnings: {len(suspicious)} suspicious chapter boundaries/titles")
    return 0


def _validate_source(args: argparse.Namespace) -> int:
    try:
        manifest = load_source_manifest(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"source manifest validation failed: {exc}", file=sys.stderr)
        return 1

    failed = [chapter for chapter in manifest.chapters if chapter.boundary_status == "failed"]
    if failed:
        print(f"source manifest has failed chapter boundaries: {len(failed)}", file=sys.stderr)
        return 1

    print(f"source manifest valid: {Path(args.run_dir) / 'source_input_manifest.json'}")
    print(f"Chapters: {len(manifest.chapters)}")
    return 0


def _prepare_run(args: argparse.Namespace) -> int:
    try:
        summary = prepare_run(args.input, args.out, work_title=args.title)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"pipeline prepare failed: {exc}", file=sys.stderr)
        return 1
    print(f"pipeline status: {summary['status']}")
    print(f"current stage: {summary['current_stage']}")
    print(f"next action: {summary['next_action']}")
    return 0 if summary["status"] == "awaiting_arc_review" else 1


def _continue_run(args: argparse.Namespace) -> int:
    try:
        summary = continue_run(
            args.run_dir,
            review_file=args.review_file,
            package_out=args.package_out,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"pipeline continue failed: {exc}", file=sys.stderr)
        return 1
    print(f"pipeline status: {summary['status']}")
    print(f"current stage: {summary['current_stage']}")
    print(f"next action: {summary['next_action']}")
    return 0 if summary["status"] == "completed" else 1


def _build_canonical(args: argparse.Namespace) -> int:
    try:
        paths = build_canonical_chapters(args.run_dir, semantic_input=args.semantic_input)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"canonical build failed: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        chapter = _read_json_file(path)
        chapter_index = chapter["chapter_index"]
        record_pipeline_step(
            args.run_dir,
            step_id=f"canonical_chapter_{chapter_index:03d}",
            step_type="chapter_canonical_analysis",
            status="completed",
            input_fingerprints=[chapter["source"]["text_sha256"]],
            schema_version=chapter.get("schema_version", ""),
            output_refs=[path.relative_to(Path(args.run_dir)).as_posix()],
            scope={"chapter_index": chapter_index, "chapter_id": chapter["chapter_id"]},
        )
    print(f"canonical chapters written: {len(paths)}")
    return 0


def _build_raw_source_index(args: argparse.Namespace) -> int:
    try:
        report = build_raw_source_index(
            args.run_dir,
            segment_chars=args.segment_chars,
            overlap_chars=args.overlap_chars,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"raw source index build failed: {exc}", file=sys.stderr)
        return 1
    print(f"raw source index status: {report['status']}")
    print(f"raw source index: {report['raw_source_index']}")
    print(f"raw source segments: {report['raw_source_segments']}")
    print(f"segments: {report['segment_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="raw_source_index",
        step_type="raw_source_index",
        status="completed",
        output_refs=[
            "evidence/raw_source_index.json",
            "evidence/raw_source_segments.jsonl",
        ],
    )
    return 0


def _split_cli_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace("；", ";").replace("，", ",").replace(";", ",").split(",") if item.strip()]


def _retrieve_scope_from_args(args: argparse.Namespace) -> dict:
    scope: dict[str, object] = {}
    if args.source_chapter_range:
        scope["source_chapter_range"] = args.source_chapter_range
    if args.analysis_unit_range:
        scope["analysis_unit_range"] = args.analysis_unit_range
    segment_ids = _split_cli_list(args.segment_ids)
    if segment_ids:
        scope["segment_ids"] = segment_ids
    return scope


def _raw_scope_from_refs(source_refs: list[str], source_index: dict) -> dict:
    references = source_index.get("references") if isinstance(source_index, dict) else {}
    if not isinstance(references, dict):
        return {}
    segment_ids: list[str] = []
    source_ranges: list[str] = []
    analysis_ranges: list[str] = []
    for ref in source_refs:
        entry = references.get(ref)
        if not isinstance(entry, dict):
            continue
        raw_scope = entry.get("raw_source_scope") if isinstance(entry.get("raw_source_scope"), dict) else {}
        for segment_id in raw_scope.get("segment_ids") or []:
            if segment_id and segment_id not in segment_ids:
                segment_ids.append(str(segment_id))
        if raw_scope.get("source_chapter_range"):
            source_ranges.append(str(raw_scope["source_chapter_range"]))
        if raw_scope.get("analysis_unit_range"):
            analysis_ranges.append(str(raw_scope["analysis_unit_range"]))
    scope: dict[str, object] = {}
    if segment_ids:
        scope["segment_ids"] = segment_ids
    if source_ranges:
        scope["source_chapter_range"] = ",".join(source_ranges)
    if analysis_ranges:
        scope["analysis_unit_range"] = ",".join(analysis_ranges)
    return scope


def _evidence_report_markdown(report: dict) -> str:
    lines = [
        "# Evidence Retrieval Report",
        "",
        f"- status: {report.get('status', '')}",
        f"- retrieval_version: {report.get('retrieval_version', '')}",
        f"- target: {report.get('target', '')}",
        f"- packet_count: {report.get('packet_count', 0)}",
        "",
        "## Packets",
    ]
    for packet in report.get("packets", []):
        lines.extend(
            [
                "",
                f"### {packet.get('packet_id', '')}",
                f"- target_path: {packet.get('target_path', '')}",
                f"- support_status: {packet.get('support_status', '')}",
                f"- claim: {packet.get('claim_text', '')}",
            ]
        )
        for item in packet.get("evidence_items", [])[:3]:
            lines.append(f"- {item.get('evidence_id', '')} {item.get('segment_id', '')}: {item.get('quote', '')}")
    return "\n".join(lines) + "\n"


def _retrieve_evidence(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    packets: list[dict] = []
    target = args.target
    try:
        if target == "claim":
            if not args.claim_text:
                print("retrieve-evidence requires --claim-text when --target claim", file=sys.stderr)
                return 1
            claim = {
                "claim_id": "CLAIM_001",
                "target_path": args.target_path or "manual_claim",
                "claim_type": "event_fact",
                "claim_text": args.claim_text,
                "source_terms": _split_cli_list(args.source_terms),
                "action_terms": _split_cli_list(args.action_terms),
                "state_terms": [],
            }
            packets.append(
                retrieve_evidence_for_claim(
                    run_dir,
                    claim,
                    retrieval_scope=_retrieve_scope_from_args(args),
                    top_k=args.top_k,
                )
            )
        else:
            handoff_dir = run_dir / "generator_handoff"
            handoff = json.loads((handoff_dir / "unified_generator_handoff.json").read_text(encoding="utf-8"))
            source_index = json.loads((handoff_dir / "source_reference_index.json").read_text(encoding="utf-8"))
            for material_index, material in enumerate(handoff.get("generator_materials") or []):
                if not isinstance(material, dict) or material.get("source_dependence") != "source_bound":
                    continue
                source_refs = [str(ref) for ref in material.get("source_refs") or [] if ref]
                retrieval_scope = _raw_scope_from_refs(source_refs, source_index)
                for claim in extract_claims_from_value(
                    material.get("content"),
                    target_path=f"generator_materials[{material_index}].content",
                    max_claims=args.max_claims,
                ):
                    packets.append(
                        retrieve_evidence_for_claim(
                            run_dir,
                            claim,
                            retrieval_scope=retrieval_scope,
                            top_k=args.top_k,
                        )
                    )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"evidence retrieval failed: {exc}", file=sys.stderr)
        return 1

    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "story_analyzer.evidence_retrieval_report.v1",
        "retrieval_version": EVIDENCE_RETRIEVAL_VERSION,
        "status": "completed",
        "target": target,
        "packet_count": len(packets),
        "packets": packets,
    }
    report_path = evidence_dir / "evidence_retrieval_report.json"
    markdown_path = evidence_dir / "evidence_retrieval_report.md"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_evidence_report_markdown(report), encoding="utf-8")
    print(f"evidence retrieval status: {report['status']}")
    print(f"packets: {report['packet_count']}")
    print(f"report: {report_path}")
    record_pipeline_step(
        args.run_dir,
        step_id="evidence_retrieval",
        step_type="evidence_retrieval",
        status="completed",
        output_refs=[
            "evidence/evidence_retrieval_report.json",
            "evidence/evidence_retrieval_report.md",
        ],
    )
    return 0


def _build_semantic_inputs(args: argparse.Namespace) -> int:
    try:
        provider = build_semantic_provider(
            args.provider,
            endpoint=args.endpoint,
            api_key_env=args.api_key_env,
            analyzer_id=args.analyzer_id,
            timeout_seconds=args.timeout_seconds,
        )
        summary = build_semantic_chapter_inputs(
            args.run_dir,
            provider=provider,
            output_dir=args.out,
            overwrite=args.overwrite,
        )
    except (OSError, ValidationError, ValueError, SemanticProviderError) as exc:
        print(f"semantic provider build failed: {exc}", file=sys.stderr)
        return 1
    output_refs = [summary.get("provider_run_ref") or "semantic_chapter_inputs/semantic_provider_run.json"]
    output_refs.extend(
        item["output_ref"]
        for item in summary.get("chapters", [])
        if item.get("status") in {"produced", "skipped_existing"} and item.get("output_ref")
    )
    record_pipeline_step(
        args.run_dir,
        step_id="semantic_provider_run",
        step_type="semantic_provider_run",
        status="completed" if summary["status"] == "completed" else "blocked",
        schema_version=summary.get("schema_version", ""),
        output_refs=output_refs,
        warnings=[item["error"] for item in summary.get("chapters", []) if item.get("status") == "failed"],
    )
    print(f"semantic provider status: {summary['status']}")
    print(f"provider: {summary['provider_type']}")
    print(f"semantic chapters produced: {summary['produced_count']}")
    print(f"semantic chapters failed: {summary['failed_count']}")
    return 0 if summary["status"] == "completed" else 1


def _adapt_legacy_v2(args: argparse.Namespace) -> int:
    try:
        summary = adapt_legacy_v2_outputs(
            args.legacy_run_dir,
            args.run_dir,
            output_dir=args.out,
            overwrite=args.overwrite,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"legacy v2 adapter failed: {exc}", file=sys.stderr)
        return 1
    output_refs = [summary.get("adapter_report_ref", "semantic_chapter_inputs/legacy_v2_adapter_report.json")]
    output_refs.extend(summary.get("output_refs", []))
    warnings = []
    errors = []
    for chapter in summary.get("chapters", []):
        warnings.extend(chapter.get("warnings", []))
        if chapter.get("error"):
            errors.append(chapter["error"])
    record_pipeline_step(
        args.run_dir,
        step_id="legacy_v2_adapter",
        step_type="legacy_v2_adapter",
        status="completed" if summary["status"] == "completed" else "blocked",
        schema_version=summary.get("schema_version", ""),
        output_refs=output_refs,
        warnings=warnings,
        errors=errors,
    )
    print(f"legacy adapter status: {summary['status']}")
    print(f"legacy chapters adapted: {summary['adapted_count']}")
    print(f"legacy chapters skipped: {summary['skipped_count']}")
    print(f"legacy chapters missing: {summary['missing_count']}")
    print(f"legacy adapter warnings: {summary['warning_count']}")
    return 0 if summary["status"] == "completed" else 1


def _quality_gate(args: argparse.Namespace) -> int:
    try:
        report = run_quality_gate(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"quality gate failed: {exc}", file=sys.stderr)
        return 1
    print(f"quality gate status: {report['status']}")
    print(f"Blocking issues: {report['blocking_issue_count']}")
    print(f"Warnings: {report['warning_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="quality_gate",
        step_type="quality_gate",
        status="blocked" if report["status"] == "blocked" else "completed",
        schema_version=report.get("schema_version", ""),
        output_refs=["quality/quality_report.json"],
        warnings=[issue["message"] for issue in report.get("issues", []) if issue.get("severity") == "warning"],
        errors=[issue["message"] for issue in report.get("issues", []) if issue.get("severity") == "blocking"],
    )
    return 1 if report["status"] == "blocked" else 0


def _build_quality_metrics_report(args: argparse.Namespace) -> int:
    try:
        report = build_quality_metrics_report(args.run_dir, package_dir=args.package_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"quality metrics report failed: {exc}", file=sys.stderr)
        return 1
    print(f"quality metrics report status: {report['status']}")
    print(f"available metrics: {report['available_metric_count']}")
    print(f"report: {Path(args.run_dir) / 'quality' / 'quality_metrics_report.json'}")
    return 0


def _repair_chapter(args: argparse.Namespace) -> int:
    try:
        attempt = repair_chapter(
            args.run_dir,
            chapter_id=args.chapter_id,
            max_attempts=args.max_attempts,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"chapter repair failed: {exc}", file=sys.stderr)
        return 1
    print(f"chapter repair status: {attempt['status']}")
    print(f"attempt: {attempt['attempt_id']}")
    print(f"reason: {attempt['reason']}")
    return 0 if attempt["status"] in {"applied", "noop"} else 1


def _build_trackers(args: argparse.Namespace) -> int:
    try:
        candidate_paths = extract_tracker_candidates(args.run_dir)
        foreshadowing_tracker = reconcile_foreshadowing_tracker(args.run_dir)
        mystery_tracker = reconcile_mystery_tracker(args.run_dir)
        relationship_debt_tracker = reconcile_relationship_debt_tracker(args.run_dir)
        world_rule_reveal_tracker = reconcile_world_rule_reveal_tracker(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"tracker build failed: {exc}", file=sys.stderr)
        return 1
    for path in candidate_paths:
        payload = _read_json_file(path)
        chapter_index = payload["chapter_index"]
        record_pipeline_step(
            args.run_dir,
            step_id=f"tracker_candidates_chapter_{chapter_index:03d}",
            step_type="tracker_candidate_extraction",
            status="completed",
            schema_version=payload.get("schema_version", ""),
            output_refs=[path.relative_to(Path(args.run_dir)).as_posix()],
            scope={"chapter_index": chapter_index, "chapter_id": payload["chapter_id"]},
        )
    record_pipeline_step(
        args.run_dir,
        step_id="foreshadowing_tracker",
        step_type="foreshadowing_tracker",
        status="completed",
        schema_version=foreshadowing_tracker.get("schema_version", ""),
        output_refs=["trackers/foreshadowing_tracker.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="mystery_tracker",
        step_type="mystery_tracker",
        status="completed",
        schema_version=mystery_tracker.get("schema_version", ""),
        output_refs=["trackers/mystery_tracker.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="relationship_debt_tracker",
        step_type="relationship_debt_tracker",
        status="completed",
        schema_version=relationship_debt_tracker.get("schema_version", ""),
        output_refs=["trackers/relationship_debt_tracker.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="world_rule_reveal_tracker",
        step_type="world_rule_reveal_tracker",
        status="completed",
        schema_version=world_rule_reveal_tracker.get("schema_version", ""),
        output_refs=["trackers/world_rule_reveal_tracker.json"],
    )
    print(f"tracker candidate files written: {len(candidate_paths)}")
    print(f"foreshadowing tracker items: {foreshadowing_tracker['item_count']}")
    print(f"mystery tracker items: {mystery_tracker['item_count']}")
    print(f"relationship debt tracker items: {relationship_debt_tracker['item_count']}")
    print(f"world rule reveal tracker items: {world_rule_reveal_tracker['item_count']}")
    return 0


def _override_tracker(args: argparse.Namespace) -> int:
    try:
        tracker = apply_tracker_manual_override(
            args.run_dir,
            tracker_type=args.tracker_type,
            tracker_item_id=args.tracker_item_id,
            status=args.status,
            resolved_chapter_index=args.resolved_chapter_index,
            resolution_method=args.resolution_method,
            reason=args.reason,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"tracker override failed: {exc}", file=sys.stderr)
        return 1
    print(f"tracker override applied: {args.tracker_type}/{args.tracker_item_id}")
    print(f"tracker items: {tracker['item_count']}")
    return 0


def _merge_tracker_items(args: argparse.Namespace) -> int:
    try:
        tracker = merge_tracker_items(
            args.run_dir,
            tracker_type=args.tracker_type,
            target_item_id=args.target_item_id,
            source_item_ids=args.source_item_id,
            reason=args.reason,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"tracker merge failed: {exc}", file=sys.stderr)
        return 1
    print(f"tracker merge applied: {args.tracker_type}/{args.target_item_id}")
    print(f"tracker items: {tracker['item_count']}")
    return 0


def _split_tracker_item(args: argparse.Namespace) -> int:
    try:
        new_items = json.loads(Path(args.new_items_file).read_text(encoding="utf-8-sig"))
        if not isinstance(new_items, list):
            raise ValueError("new items file must contain a JSON list")
        tracker = split_tracker_item(
            args.run_dir,
            tracker_type=args.tracker_type,
            source_item_id=args.source_item_id,
            new_items=new_items,
            reason=args.reason,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"tracker split failed: {exc}", file=sys.stderr)
        return 1
    print(f"tracker split applied: {args.tracker_type}/{args.source_item_id}")
    print(f"tracker items: {tracker['item_count']}")
    return 0


def _build_tracker_edit_report(args: argparse.Namespace) -> int:
    try:
        report = build_tracker_edit_report(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"tracker edit report failed: {exc}", file=sys.stderr)
        return 1
    record_pipeline_step(
        args.run_dir,
        step_id="tracker_edit_report",
        step_type="tracker_edit_report",
        status="completed",
        schema_version=report.get("schema_version", ""),
        output_refs=[
            "trackers/tracker_edit_report.json",
            "trackers/tracker_edit_report.md",
            "trackers/tracker_semantic_recommendation_report.json",
        ],
    )
    print(f"tracker edit report status: {report['status']}")
    print(f"tracker edit operations: {report['operation_count']}")
    print(f"manual override items: {report['manual_override_item_count']}")
    return 0


def _propose_arcs(args: argparse.Namespace) -> int:
    try:
        proposal = propose_arc_candidates(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"arc proposal failed: {exc}", file=sys.stderr)
        return 1
    print(f"major arc candidates: {len(proposal['major_arcs'])}")
    print(f"sub arc candidates: {len(proposal['sub_arcs'])}")
    print("arc review status: pending_user_review")
    record_pipeline_step(
        args.run_dir,
        step_id="arc_candidates",
        step_type="arc_candidates",
        status="completed",
        schema_version=proposal.get("schema_version", ""),
        output_refs=["arcs/arc_candidates.json", "arcs/arc_review.json", "arcs/arc_review.md"],
    )
    return 0


def _confirm_arcs(args: argparse.Namespace) -> int:
    try:
        review = confirm_arc_candidates(args.run_dir, review_file=args.review_file)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"arc confirmation failed: {exc}", file=sys.stderr)
        return 1
    print(f"arc review status: {review['status']}")
    print(f"confirmed version: {review['confirmed_version']}")
    record_pipeline_step(
        args.run_dir,
        step_id="arc_confirmation",
        step_type="arc_confirmation",
        status="completed",
        schema_version=review.get("schema_version", ""),
        output_refs=["arcs/major_arcs.json", "arcs/sub_arcs.json", "arcs/arc_review.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="major_arcs",
        step_type="major_arcs",
        status="completed",
        output_refs=["arcs/major_arcs.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="sub_arcs",
        step_type="sub_arcs",
        status="completed",
        output_refs=["arcs/sub_arcs.json"],
    )
    return 0


def _analyze_arcs(args: argparse.Namespace) -> int:
    try:
        payload = analyze_arc_modules(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"arc analysis failed: {exc}", file=sys.stderr)
        return 1
    print(f"arc modules written: {payload['module_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="arc_modules",
        step_type="arc_modules",
        status="completed",
        schema_version=payload.get("schema_version", ""),
        output_refs=["modules/arc_modules.json", "modules/module_catalog.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="module_catalog",
        step_type="module_catalog",
        status="completed",
        output_refs=["modules/module_catalog.json"],
    )
    return 0


def _analyze_chapters(args: argparse.Namespace) -> int:
    try:
        payload = analyze_chapter_modules(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"chapter analysis failed: {exc}", file=sys.stderr)
        return 1
    print(f"chapter modules written: {payload['module_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="chapter_modules",
        step_type="chapter_modules",
        status="completed",
        schema_version=payload.get("schema_version", ""),
        output_refs=["modules/chapter_modules.json", "modules/module_catalog.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="module_catalog",
        step_type="module_catalog",
        status="completed",
        output_refs=["modules/module_catalog.json"],
    )
    return 0


def _build_book_modules(args: argparse.Namespace) -> int:
    try:
        payload = build_book_modules(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"book module build failed: {exc}", file=sys.stderr)
        return 1
    print(f"book modules written: {payload['module_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="book_modules",
        step_type="book_modules",
        status="completed",
        schema_version=payload.get("schema_version", ""),
        output_refs=["modules/book_modules.json", "modules/module_catalog.json", "modules/module_conflict_report.json"],
    )
    record_pipeline_step(
        args.run_dir,
        step_id="module_catalog",
        step_type="module_catalog",
        status="completed",
        output_refs=["modules/module_catalog.json"],
    )
    return 0


def _build_module_conflict_report(args: argparse.Namespace) -> int:
    try:
        report = build_module_conflict_report(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"module conflict report failed: {exc}", file=sys.stderr)
        return 1
    print(f"module conflict report status: {report['status']}")
    print(f"module conflicts: {report['conflict_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="module_conflict_report",
        step_type="module_conflict_report",
        status="completed",
        schema_version=report.get("schema_version", ""),
        output_refs=["modules/module_conflict_report.json"],
    )
    return 0


def _export_handoff(args: argparse.Namespace) -> int:
    if args.format != "v1":
        print(f"unsupported handoff format: {args.format}", file=sys.stderr)
        return 1
    try:
        result = export_handoff_package(args.run_dir, output_dir=args.out)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"handoff export failed: {exc}", file=sys.stderr)
        return 1
    summary = result["validation_summary"]
    print(f"handoff package: {result['package_dir']}")
    print(f"validation status: {summary['validation_status']}")
    record_pipeline_step(
        args.run_dir,
        step_id="handoff_package",
        step_type="handoff_package",
        status="completed" if summary["validation_status"] == "passed" else "blocked",
        output_refs=[str(Path(result["package_dir"]))],
        errors=[issue["message"] for issue in summary.get("blocking_issues", [])],
        warnings=[issue["message"] for issue in summary.get("warnings", [])],
    )
    return 0 if summary["validation_status"] == "passed" else 1


def _compile_generator_handoff(args: argparse.Namespace) -> int:
    try:
        report = compile_generator_handoff(args.run_dir, work_title=args.work_title or "")
    except (OSError, ValidationError, ValueError) as exc:
        print(f"generator handoff compile failed: {exc}", file=sys.stderr)
        return 1
    handoff_dir = Path(args.run_dir) / "generator_handoff"
    print(f"generator handoff: {handoff_dir}")
    print(f"compiler status: {report['compiler_status']}")
    print(f"blocking errors: {report['blocking_error_count']}")
    print(f"warnings: {report['warning_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="generator_handoff_compiler",
        step_type="generator_handoff_compiler",
        status="completed" if report["compiler_status"] == "compiled" else "blocked",
        schema_version=report.get("schema_version", ""),
        output_refs=[
            "generator_handoff/unified_generator_handoff.json",
            "generator_handoff/source_reference_index.json",
            "generator_handoff/compiler_report.json",
        ],
        errors=[issue["message"] for issue in report.get("blocking_errors", [])],
        warnings=[issue["message"] for issue in report.get("warnings", [])],
    )
    return 0 if report["compiler_status"] == "compiled" else 1


def _validate_handoff(args: argparse.Namespace) -> int:
    try:
        summary = validate_handoff_package(args.package_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"handoff validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"validation status: {summary['validation_status']}")
    print(f"blocking issues: {summary['blocking_issue_count']}")
    print(f"warnings: {summary['warning_count']}")
    return 0 if summary["validation_status"] == "passed" else 1


def _validate_generator_handoff(args: argparse.Namespace) -> int:
    try:
        semantic_validator = _generator_handoff_semantic_validator_from_args(args)
        report = validate_generator_handoff(
            args.run_dir,
            attempt_index=args.attempt_index,
            evidence_mode=args.evidence_mode,
            semantic_validator=semantic_validator,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"generator handoff validation failed: {exc}", file=sys.stderr)
        return 1
    deliverable = is_generator_handoff_deliverable(report)
    print(f"generator handoff validation status: {report['validation_status']}")
    print(f"blocking issues: {report['blocking_issue_count']}")
    print(f"warnings: {report['warning_count']}")
    record_pipeline_step(
        args.run_dir,
        step_id="generator_handoff_validator",
        step_type="generator_handoff_validator",
        status="completed" if deliverable else "blocked",
        schema_version=report.get("schema_version", ""),
        output_refs=[
            "generator_handoff/validation_report.json",
            "generator_handoff/validation_report.md",
        ],
        errors=[issue["message"] for issue in report.get("issues", []) if issue.get("severity") == "blocking"],
        warnings=[issue["message"] for issue in report.get("issues", []) if issue.get("severity") == "warning"],
    )
    return 0 if deliverable else 1


def _repair_generator_handoff(args: argparse.Namespace) -> int:
    try:
        semantic_validator = _generator_handoff_semantic_validator_from_args(args)
        summary = repair_generator_handoff(
            args.run_dir,
            max_attempts=args.max_attempts,
            evidence_mode=args.evidence_mode,
            semantic_validator=semantic_validator,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"generator handoff repair failed: {exc}", file=sys.stderr)
        return 1
    print(f"generator handoff repair status: {summary['repair_status']}")
    print(f"attempts: {summary['attempt_count']}")
    print(f"validation status: {summary['validation_status']}")
    if summary.get("validated_handoff"):
        print(f"validated handoff: {summary['validated_handoff']}")
    if summary.get("failed_report"):
        print(f"failed report: {summary['failed_report']}")
    record_pipeline_step(
        args.run_dir,
        step_id="generator_handoff_repair",
        step_type="generator_handoff_repair",
        status="completed" if summary["repair_status"] == "passed" else "blocked",
        output_refs=[
            "generator_handoff/repair_history.json",
            "generator_handoff/unified_generator_handoff.validated.json"
            if summary["repair_status"] == "passed"
            else "generator_handoff/handoff_failed_report.json",
        ],
        errors=[] if summary["repair_status"] == "passed" else [summary.get("failure_reason", "handoff_repair_failed")],
    )
    return 0 if summary["repair_status"] == "passed" else 1


def _build_cross_work_synthesis(args: argparse.Namespace) -> int:
    try:
        report = build_cross_work_pattern_synthesis(args.manifest, args.out)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"cross-work synthesis failed: {exc}", file=sys.stderr)
        return 1
    print(f"cross-work synthesis status: {report['status']}")
    print(f"patterns: {report['pattern_count']}")
    print(f"report: {Path(args.out) / 'cross_work_pattern_synthesis_report.json'}")
    return 0 if report["status"] == "ready" else 1


def _run_longzu_regression(args: argparse.Namespace) -> int:
    try:
        report = run_longzu_regression(args.source_run, args.out)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"longzu regression failed: {exc}", file=sys.stderr)
        return 1
    print(f"longzu regression status: {report['status']}")
    print(f"report: {Path(args.out) / 'longzu_regression_report.json'}")
    print(f"handoff package: {report['handoff']['package_dir']}")
    return 0 if report["status"] == "passed" else 1


def _record_state_step(args: argparse.Namespace) -> int:
    try:
        scope = _parse_scope_items(args.scope)
        record = record_pipeline_step(
            args.run_dir,
            step_id=args.step_id,
            step_type=args.step_type,
            status=args.status,
            input_fingerprints=args.input_fingerprint or [],
            dependency_fingerprints=args.dependency_fingerprint or [],
            schema_version=args.schema_version or "",
            prompt_version=args.prompt_version or "",
            model=args.model or "",
            output_refs=args.output_ref or [],
            warnings=args.warning or [],
            errors=args.error or [],
            scope=scope,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"state step record failed: {exc}", file=sys.stderr)
        return 1
    print(f"recorded state step: {record['step_id']} status={record['status']}")
    return 0


def _invalidate_state(args: argparse.Namespace) -> int:
    scope: dict[str, object] = {}
    if args.chapter_index is not None:
        scope["chapter_index"] = args.chapter_index
    if args.arc_id:
        scope["arc_id"] = args.arc_id
    if args.tracker_item_id:
        scope["tracker_item_id"] = args.tracker_item_id
    try:
        event = invalidate_for_change(
            args.run_dir,
            change_type=args.change_type,
            scope=scope,
            reason=args.reason or "",
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"state invalidation failed: {exc}", file=sys.stderr)
        return 1
    print(f"invalidation event: {event['event_id']}")
    print(f"invalidated steps: {len(event['invalidated_step_ids'])}")
    return 0


def _plan_downstream_rebuild(args: argparse.Namespace) -> int:
    try:
        summary = plan_downstream_rebuild(args.run_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"downstream rebuild plan failed: {exc}", file=sys.stderr)
        return 1
    print(f"rebuild plan status: {summary['status']}")
    print(f"next action: {summary['next_action']}")
    print(f"invalidated steps: {len(summary['invalidated_step_ids'])}")
    print(f"planned stages: {', '.join(summary['planned_stages']) if summary['planned_stages'] else 'none'}")
    return 0


def _resume_from_invalidation(args: argparse.Namespace) -> int:
    try:
        summary = resume_from_invalidation(
            args.run_dir,
            package_out=args.package_out,
            dry_run=args.dry_run,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"resume from invalidation failed: {exc}", file=sys.stderr)
        return 1
    print(f"rebuild status: {summary['status']}")
    print(f"next action: {summary['next_action']}")
    print(f"rebuilt stages: {', '.join(summary['rebuilt_stages']) if summary['rebuilt_stages'] else 'none'}")
    package_dir = summary.get("handoff", {}).get("package_dir")
    if package_dir:
        print(f"handoff package: {package_dir}")
    return 0 if summary["status"] in {"completed", "noop", "awaiting_arc_review", "ready"} else 1


def _build_generator_import_fixture(args: argparse.Namespace) -> int:
    try:
        result = build_generator_import_fixture(args.package_dir, args.out)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"generator import fixture build failed: {exc}", file=sys.stderr)
        return 1
    summary = result["validation_summary"]
    print(f"generator import fixture: {result['fixture_dir']}")
    print(f"validation status: {summary['validation_status']}")
    return 0 if summary["validation_status"] == "passed" else 1


def _validate_generator_import_fixture(args: argparse.Namespace) -> int:
    try:
        summary = validate_generator_import_fixture(args.fixture_dir)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"generator import fixture validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"validation status: {summary['validation_status']}")
    print(f"blocking issues: {summary['blocking_issue_count']}")
    print(f"warnings: {summary['warning_count']}")
    return 0 if summary["validation_status"] == "passed" else 1


def _export_model_schemas(args: argparse.Namespace) -> int:
    try:
        result = export_model_schemas(args.out)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"schema export failed: {exc}", file=sys.stderr)
        return 1
    print(f"schema export: {Path(args.out)}")
    print(f"schemas: {result['schema_count']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="story_analyzer_v1")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_source = subparsers.add_parser("inspect-source", help="Create source_input_manifest.json")
    inspect_source.add_argument("input", help="Source .txt/.md file or folder of chapter files")
    inspect_source.add_argument("--out", required=True, help="Run output directory")
    inspect_source.add_argument("--title", help="Override work title")
    inspect_source.set_defaults(func=_inspect_source)

    validate_source = subparsers.add_parser("validate-source", help="Validate source_input_manifest.json")
    validate_source.add_argument("run_dir", help="Run output directory containing source_input_manifest.json")
    validate_source.set_defaults(func=_validate_source)

    prepare = subparsers.add_parser("prepare-run", help="Run v1 pipeline through arc proposal and stop for review")
    prepare.add_argument("input", help="Source .txt/.md file or folder of chapter files")
    prepare.add_argument("--out", required=True, help="Run output directory")
    prepare.add_argument("--title", help="Override work title")
    prepare.set_defaults(func=_prepare_run)

    continue_parser = subparsers.add_parser("continue-run", help="Continue a prepared v1 run after arc review")
    continue_parser.add_argument("run_dir", help="Prepared run output directory")
    continue_parser.add_argument("--review-file", help="Optional arc review JSON path, relative to run_dir or absolute")
    continue_parser.add_argument("--package-out", help="Output handoff package directory")
    continue_parser.set_defaults(func=_continue_run)

    build_canonical = subparsers.add_parser("build-canonical", help="Build canonical chapter analyses")
    build_canonical.add_argument("run_dir", help="Run output directory containing source_input_manifest.json")
    build_canonical.add_argument(
        "--semantic-input",
        help="Optional raw semantic JSON file or directory containing chapter_XXX.json files",
    )
    build_canonical.set_defaults(func=_build_canonical)

    raw_source_index = subparsers.add_parser(
        "build-raw-source-index",
        help="Build Evidence Layer V2 raw source index from source_input_manifest or web input/book.txt",
    )
    raw_source_index.add_argument("run_dir", help="Run output directory or analyzer output directory")
    raw_source_index.add_argument("--segment-chars", type=int, default=2200)
    raw_source_index.add_argument("--overlap-chars", type=int, default=200)
    raw_source_index.set_defaults(func=_build_raw_source_index)

    retrieve_evidence = subparsers.add_parser(
        "retrieve-evidence",
        help="Retrieve Evidence Layer V2 raw source packets for a claim or generator handoff",
    )
    retrieve_evidence.add_argument("run_dir", help="Run output directory containing evidence/raw_source_index.json")
    retrieve_evidence.add_argument("--target", choices=["claim", "generator_handoff"], default="claim")
    retrieve_evidence.add_argument("--claim-text", default="", help="Claim text when --target claim")
    retrieve_evidence.add_argument("--target-path", default="manual_claim")
    retrieve_evidence.add_argument("--source-terms", default="", help="Comma-separated source/entity terms")
    retrieve_evidence.add_argument("--action-terms", default="", help="Comma-separated action/state terms")
    retrieve_evidence.add_argument("--source-chapter-range", default="")
    retrieve_evidence.add_argument("--analysis-unit-range", default="")
    retrieve_evidence.add_argument("--segment-ids", default="", help="Comma-separated raw source segment ids")
    retrieve_evidence.add_argument("--top-k", type=int, default=5)
    retrieve_evidence.add_argument("--max-claims", type=int, default=12)
    retrieve_evidence.set_defaults(func=_retrieve_evidence)

    build_semantic = subparsers.add_parser("build-semantic-inputs", help="Build raw semantic chapter JSON via a provider")
    build_semantic.add_argument("run_dir", help="Run output directory containing source_input_manifest.json")
    build_semantic.add_argument("--provider", required=True, choices=SEMANTIC_PROVIDER_CHOICES)
    build_semantic.add_argument("--out", help="Output semantic input directory; defaults to run_dir/semantic_chapter_inputs")
    build_semantic.add_argument("--overwrite", action="store_true", help="Overwrite existing chapter semantic JSON files")
    build_semantic.add_argument("--endpoint", help="HTTP provider endpoint")
    build_semantic.add_argument("--api-key-env", help="Environment variable containing HTTP provider bearer token")
    build_semantic.add_argument("--analyzer-id", help="Analyzer id to stamp onto HTTP provider outputs")
    build_semantic.add_argument("--timeout-seconds", type=float, default=60.0)
    build_semantic.set_defaults(func=_build_semantic_inputs)

    adapt_legacy = subparsers.add_parser(
        "adapt-legacy-v2",
        help="Adapt book_analyzer_v2 outputs into raw semantic chapter JSON",
    )
    adapt_legacy.add_argument("legacy_run_dir", help="Legacy book_analyzer_v2 output directory")
    adapt_legacy.add_argument("--run-dir", required=True, help="v1 run directory containing source_input_manifest.json")
    adapt_legacy.add_argument(
        "--out",
        help="Output semantic input directory; defaults to run_dir/semantic_chapter_inputs",
    )
    adapt_legacy.add_argument("--overwrite", action="store_true", help="Overwrite existing adapted semantic JSON files")
    adapt_legacy.set_defaults(func=_adapt_legacy_v2)

    quality_gate = subparsers.add_parser("quality-gate", help="Run deterministic quality gate")
    quality_gate.add_argument("run_dir", help="Run output directory containing canonical_chapter_analysis")
    quality_gate.set_defaults(func=_quality_gate)

    quality_metrics = subparsers.add_parser(
        "build-quality-metrics-report",
        help="Build advisory quality metrics report",
    )
    quality_metrics.add_argument("run_dir", help="Run output directory")
    quality_metrics.add_argument("--package-dir", help="Optional handoff package directory for handoff pass metric")
    quality_metrics.set_defaults(func=_build_quality_metrics_report)

    repair_chapter_parser = subparsers.add_parser("repair-chapter", help="Run targeted repair for one chapter")
    repair_chapter_parser.add_argument("run_dir", help="Run output directory containing canonical_chapter_analysis")
    repair_chapter_parser.add_argument("--chapter-id", required=True, help="Canonical chapter id, e.g. chapter_001")
    repair_chapter_parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Maximum repair attempts allowed for this chapter",
    )
    repair_chapter_parser.set_defaults(func=_repair_chapter)

    build_trackers = subparsers.add_parser("build-trackers", help="Build tracker candidates and v1 trackers")
    build_trackers.add_argument("run_dir", help="Run output directory containing canonical_chapter_analysis")
    build_trackers.set_defaults(func=_build_trackers)

    override_tracker = subparsers.add_parser("override-tracker", help="Apply an audited manual override to one tracker item")
    override_tracker.add_argument("run_dir", help="Run output directory containing trackers")
    override_tracker.add_argument("--tracker-type", required=True, choices=TRACKER_TYPE_CHOICES)
    override_tracker.add_argument("--tracker-item-id", required=True)
    override_tracker.add_argument("--status", choices=TRACKER_STATUS_CHOICES)
    override_tracker.add_argument("--resolved-chapter-index", type=int)
    override_tracker.add_argument("--resolution-method")
    override_tracker.add_argument("--reason")
    override_tracker.set_defaults(func=_override_tracker)

    merge_tracker = subparsers.add_parser("merge-tracker-items", help="Merge tracker items with an audit log entry")
    merge_tracker.add_argument("run_dir", help="Run output directory containing trackers")
    merge_tracker.add_argument("--tracker-type", required=True, choices=TRACKER_TYPE_CHOICES)
    merge_tracker.add_argument("--target-item-id", required=True)
    merge_tracker.add_argument("--source-item-id", required=True, action="append")
    merge_tracker.add_argument("--reason")
    merge_tracker.set_defaults(func=_merge_tracker_items)

    split_tracker = subparsers.add_parser("split-tracker-item", help="Split one tracker item into manually supplied items")
    split_tracker.add_argument("run_dir", help="Run output directory containing trackers")
    split_tracker.add_argument("--tracker-type", required=True, choices=TRACKER_TYPE_CHOICES)
    split_tracker.add_argument("--source-item-id", required=True)
    split_tracker.add_argument("--new-items-file", required=True, help="JSON list of new tracker item definitions")
    split_tracker.add_argument("--reason")
    split_tracker.set_defaults(func=_split_tracker_item)

    tracker_report = subparsers.add_parser("build-tracker-edit-report", help="Build JSON and Markdown tracker edit reports")
    tracker_report.add_argument("run_dir", help="Run output directory containing trackers")
    tracker_report.set_defaults(func=_build_tracker_edit_report)

    propose_arcs = subparsers.add_parser("propose-arcs", help="Build major/sub arc candidates")
    propose_arcs.add_argument("run_dir", help="Run output directory containing canonical_chapter_analysis")
    propose_arcs.set_defaults(func=_propose_arcs)

    confirm_arcs = subparsers.add_parser("confirm-arcs", help="Confirm reviewed major/sub arc candidates")
    confirm_arcs.add_argument("run_dir", help="Run output directory containing arcs/arc_candidates.json")
    confirm_arcs.add_argument("--review-file", help="Optional arc review JSON path, relative to run_dir or absolute")
    confirm_arcs.set_defaults(func=_confirm_arcs)

    analyze_chapters = subparsers.add_parser("analyze-chapters", help="Build chapter-level module envelopes")
    analyze_chapters.add_argument("run_dir", help="Run output directory containing canonical chapters")
    analyze_chapters.set_defaults(func=_analyze_chapters)

    analyze_arcs = subparsers.add_parser("analyze-arcs", help="Build module envelopes from confirmed arcs")
    analyze_arcs.add_argument("run_dir", help="Run output directory containing confirmed arcs")
    analyze_arcs.set_defaults(func=_analyze_arcs)

    build_book = subparsers.add_parser("build-book-modules", help="Build book-level module envelopes and catalog")
    build_book.add_argument("run_dir", help="Run output directory containing arc modules")
    build_book.set_defaults(func=_build_book_modules)

    module_conflicts = subparsers.add_parser(
        "build-module-conflict-report",
        help="Build advisory module conflict report",
    )
    module_conflicts.add_argument("run_dir", help="Run output directory containing module files")
    module_conflicts.set_defaults(func=_build_module_conflict_report)

    export_handoff = subparsers.add_parser("export-handoff", help="Export Story Analyzer Handoff Package")
    export_handoff.add_argument("run_dir", help="Run output directory containing v1 artifacts")
    export_handoff.add_argument("--format", default="v1", choices=["v1"], help="Handoff package format")
    export_handoff.add_argument("--out", help="Output package directory")
    export_handoff.set_defaults(func=_export_handoff)

    compile_generator_handoff_parser = subparsers.add_parser(
        "compile-generator-handoff",
        help="Compile analyzer outputs into one generator-facing handoff payload",
    )
    compile_generator_handoff_parser.add_argument("run_dir", help="Run output directory containing analyzer artifacts")
    compile_generator_handoff_parser.add_argument("--work-title", default="", help="Optional title override")
    compile_generator_handoff_parser.set_defaults(func=_compile_generator_handoff)

    validate_generator_handoff_parser = subparsers.add_parser(
        "validate-generator-handoff",
        help="Validate unified generator handoff before generator import",
    )
    validate_generator_handoff_parser.add_argument("run_dir", help="Run output directory containing generator_handoff")
    validate_generator_handoff_parser.add_argument("--attempt-index", type=int, default=0)
    validate_generator_handoff_parser.add_argument("--evidence-mode", choices=["auto", "v1", "v2"], default="auto")
    _add_generator_handoff_semantic_validator_args(validate_generator_handoff_parser)
    validate_generator_handoff_parser.set_defaults(func=_validate_generator_handoff)

    repair_generator_handoff_parser = subparsers.add_parser(
        "repair-generator-handoff",
        help="Repair and revalidate unified generator handoff before generator import",
    )
    repair_generator_handoff_parser.add_argument("run_dir", help="Run output directory containing generator_handoff")
    repair_generator_handoff_parser.add_argument("--max-attempts", type=int, default=5)
    repair_generator_handoff_parser.add_argument("--evidence-mode", choices=["auto", "v1", "v2"], default="auto")
    _add_generator_handoff_semantic_validator_args(repair_generator_handoff_parser)
    repair_generator_handoff_parser.set_defaults(func=_repair_generator_handoff)

    validate_handoff = subparsers.add_parser("validate-handoff", help="Validate Story Analyzer Handoff Package")
    validate_handoff.add_argument("package_dir", help="Handoff package directory")
    validate_handoff.set_defaults(func=_validate_handoff)

    cross_work = subparsers.add_parser(
        "build-cross-work-synthesis",
        help="Build an advisory cross-work transferable pattern synthesis report",
    )
    cross_work.add_argument("manifest", help="Cross-work input manifest JSON")
    cross_work.add_argument("--out", required=True, help="Output directory for synthesis report")
    cross_work.set_defaults(func=_build_cross_work_synthesis)

    longzu_regression = subparsers.add_parser(
        "run-longzu-regression",
        help="Run the M8 Longzu regression and generator handoff smoke check",
    )
    longzu_regression.add_argument("--source-run", required=True, help="Legacy Longzu web run directory")
    longzu_regression.add_argument("--out", required=True, help="Regression output directory")
    longzu_regression.set_defaults(func=_run_longzu_regression)

    record_state = subparsers.add_parser("record-state-step", help="Record or update one pipeline state step")
    record_state.add_argument("run_dir", help="Run output directory")
    record_state.add_argument("--step-id", required=True)
    record_state.add_argument("--step-type", required=True)
    record_state.add_argument("--status", required=True, choices=STEP_STATUS_CHOICES)
    record_state.add_argument("--input-fingerprint", action="append")
    record_state.add_argument("--dependency-fingerprint", action="append")
    record_state.add_argument("--schema-version")
    record_state.add_argument("--prompt-version")
    record_state.add_argument("--model")
    record_state.add_argument("--output-ref", action="append")
    record_state.add_argument("--warning", action="append")
    record_state.add_argument("--error", action="append")
    record_state.add_argument("--scope", action="append", help="Scope key=value, repeatable")
    record_state.set_defaults(func=_record_state_step)

    invalidate_state = subparsers.add_parser("invalidate-state", help="Invalidate pipeline state after a scoped change")
    invalidate_state.add_argument("run_dir", help="Run output directory")
    invalidate_state.add_argument("--change-type", required=True, choices=CHANGE_TYPE_CHOICES)
    invalidate_state.add_argument("--chapter-index", type=int)
    invalidate_state.add_argument("--arc-id")
    invalidate_state.add_argument("--tracker-item-id")
    invalidate_state.add_argument("--reason")
    invalidate_state.set_defaults(func=_invalidate_state)

    plan_rebuild = subparsers.add_parser("plan-downstream-rebuild", help="Plan rebuild stages for invalidated pipeline state")
    plan_rebuild.add_argument("run_dir", help="Run output directory containing run_state")
    plan_rebuild.set_defaults(func=_plan_downstream_rebuild)

    resume_rebuild = subparsers.add_parser("resume-from-invalidation", help="Rebuild invalidated downstream artifacts")
    resume_rebuild.add_argument("run_dir", help="Run output directory containing invalidated run_state")
    resume_rebuild.add_argument("--package-out", help="Optional new handoff package output directory")
    resume_rebuild.add_argument("--dry-run", action="store_true", help="Only report planned rebuild stages")
    resume_rebuild.set_defaults(func=_resume_from_invalidation)

    build_fixture = subparsers.add_parser(
        "build-generator-import-fixture",
        help="Build a self-contained generator import contract fixture from a handoff package",
    )
    build_fixture.add_argument("package_dir", help="Validated Story Analyzer handoff package")
    build_fixture.add_argument("--out", required=True, help="Output fixture directory")
    build_fixture.set_defaults(func=_build_generator_import_fixture)

    validate_fixture = subparsers.add_parser(
        "validate-generator-import-fixture",
        help="Validate a generator import contract fixture",
    )
    validate_fixture.add_argument("fixture_dir", help="Generator import fixture directory")
    validate_fixture.set_defaults(func=_validate_generator_import_fixture)

    schema_export = subparsers.add_parser(
        "export-model-schemas",
        help="Export Story Analyzer v1 Pydantic model JSON Schemas",
    )
    schema_export.add_argument("--out", required=True, help="Output directory")
    schema_export.set_defaults(func=_export_model_schemas)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
