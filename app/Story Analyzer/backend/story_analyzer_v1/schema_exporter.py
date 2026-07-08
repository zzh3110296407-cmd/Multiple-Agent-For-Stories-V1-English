from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from pydantic import BaseModel

from .config import DEFAULT_ENCODING
from .models import (
    ArcCandidate,
    ArcReview,
    CanonicalChapterAnalysis,
    ChapterSource,
    HandoffPackageManifest,
    ModuleEnvelope,
    SourceInputManifest,
    TrackerCandidate,
    TrackerItem,
)


SCHEMA_EXPORT_VERSION = "story_analyzer.model_schema_export.v1"
MODEL_TYPES: list[type[BaseModel]] = [
    ArcCandidate,
    ArcReview,
    CanonicalChapterAnalysis,
    ChapterSource,
    HandoffPackageManifest,
    ModuleEnvelope,
    SourceInputManifest,
    TrackerCandidate,
    TrackerItem,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING)
    return path


def export_model_schemas(output_dir: str | Path) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    schemas = []
    for model in MODEL_TYPES:
        filename = f"{model.__name__}.schema.json"
        schema = model.model_json_schema()
        _write_json(out / filename, schema)
        schemas.append(
            {
                "model": model.__name__,
                "schema_ref": filename,
                "title": schema.get("title", model.__name__),
                "property_count": len(schema.get("properties", {})),
            }
        )
    index = {
        "schema_version": SCHEMA_EXPORT_VERSION,
        "generated_at": _now_iso(),
        "schema_count": len(schemas),
        "schemas": schemas,
    }
    _write_json(out / "schema_index.json", index)
    return index
