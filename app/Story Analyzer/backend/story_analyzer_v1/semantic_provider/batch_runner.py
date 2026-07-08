from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from pydantic import ValidationError

from ..analysis.semantic_normalizer import (
    RAW_SEMANTIC_SCHEMA_VERSION,
    SEMANTIC_PROVIDER_RUN_FILENAME,
    load_chapter_text,
    semantic_input_dir,
)
from ..config import DEFAULT_ENCODING, ensure_dir
from ..ingestion.source_manifest_builder import load_source_manifest
from ..models.common import sha256_text
from ..models.semantic import RawSemanticChapterInput
from .providers import SemanticChapterRequest, SemanticProvider, SemanticProviderError


PROVIDER_RUN_SCHEMA_VERSION = "story_analyzer.semantic_provider_run.v1"


def semantic_provider_run_path(run_dir: str | Path) -> Path:
    return semantic_input_dir(run_dir) / SEMANTIC_PROVIDER_RUN_FILENAME


def _relative_to_run(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def _normalized_raw(raw: RawSemanticChapterInput, request: SemanticChapterRequest) -> RawSemanticChapterInput:
    updates: dict[str, Any] = {
        "schema_version": RAW_SEMANTIC_SCHEMA_VERSION,
        "chapter_id": request.chapter.chapter_id,
        "chapter_index": request.chapter.chapter_index,
    }
    if not raw.source_text_sha256:
        updates["source_text_sha256"] = sha256_text(request.chapter_text)
    return raw.model_copy(update=updates)


def build_semantic_chapter_inputs(
    run_dir: str | Path,
    *,
    provider: SemanticProvider,
    output_dir: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    manifest = load_source_manifest(run_path)
    run_id = f"semantic_{manifest.source_sha256[:12] or run_path.name}"
    out_dir = ensure_dir(Path(output_dir) if output_dir is not None else semantic_input_dir(run_path))
    chapters: list[dict[str, Any]] = []

    for chapter in manifest.chapters:
        out_path = out_dir / f"{chapter.chapter_id}.json"
        if out_path.exists() and not overwrite:
            chapters.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "skipped_existing",
                    "output_ref": _relative_to_run(run_path, out_path),
                    "semantic_source": "llm_provider",
                    "analyzer_id": getattr(provider, "analyzer_id", ""),
                }
            )
            continue
        text = load_chapter_text(manifest, chapter)
        request = SemanticChapterRequest(
            run_id=run_id,
            work_title=manifest.work_title,
            chapter=chapter,
            chapter_text=text,
        )
        try:
            raw = _normalized_raw(provider.analyze_chapter(request), request)
            RawSemanticChapterInput.model_validate(raw.model_dump(mode="json"))
            _write_json(out_path, raw.model_dump(mode="json"))
            chapters.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "produced",
                    "output_ref": _relative_to_run(run_path, out_path),
                    "semantic_source": "llm_provider",
                    "analyzer_id": raw.analyzer_id,
                    "source_text_sha256": raw.source_text_sha256,
                }
            )
        except (OSError, ValidationError, SemanticProviderError, ValueError) as exc:
            chapters.append(
                {
                    "chapter_id": chapter.chapter_id,
                    "chapter_index": chapter.chapter_index,
                    "status": "failed",
                    "semantic_source": "llm_provider",
                    "analyzer_id": getattr(provider, "analyzer_id", ""),
                    "error": str(exc),
                }
            )

    produced_count = sum(1 for item in chapters if item["status"] in {"produced", "skipped_existing"})
    failed_count = sum(1 for item in chapters if item["status"] == "failed")
    status = "failed" if produced_count == 0 and failed_count else "partial" if failed_count else "completed"
    summary = {
        "schema_version": PROVIDER_RUN_SCHEMA_VERSION,
        "status": status,
        "provider_type": getattr(provider, "provider_type", "unknown"),
        "semantic_source": "llm_provider",
        "analyzer_id": getattr(provider, "analyzer_id", ""),
        "run_id": run_id,
        "work_title": manifest.work_title,
        "chapter_count": len(manifest.chapters),
        "produced_count": produced_count,
        "failed_count": failed_count,
        "provider_run_ref": _relative_to_run(run_path, out_dir / SEMANTIC_PROVIDER_RUN_FILENAME),
        "chapters": chapters,
    }
    _write_json(out_dir / SEMANTIC_PROVIDER_RUN_FILENAME, summary)
    return summary
