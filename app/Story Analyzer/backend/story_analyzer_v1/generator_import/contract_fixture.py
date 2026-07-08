from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import shutil

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import DEFAULT_ENCODING
from ..handoff.package_store import GENERATOR_CONTRACT_VERSION, now_iso, read_json, write_json
from ..handoff.validator import validate_handoff_package


FIXTURE_SCHEMA_VERSION = "story_generator_import_fixture.v1"
IMPORT_REQUESTS_SCHEMA_VERSION = "story_generator.import_requests.v1"
EXPECTED_PREVIEW_SCHEMA_VERSION = "story_generator.import_preview_contract.v1"
FIXTURE_VALIDATION_SCHEMA_VERSION = "story_generator_import_fixture.validation.v1"
GENERATION_MODES = ["original_writing", "continuation_or_revision", "hybrid_adaptation"]
FORBIDDEN_KEYS = {
    "generation_profile",
    "selected_generation_profile",
    "formal_story_bible_write",
    "formal_state_write",
}


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    generation_mode: str
    import_stage: str = "preview"
    selected_module_instance_ids: list[str] = Field(default_factory=list)
    selection_policy: dict[str, Any] = Field(default_factory=dict)
    requires_profile_compilation: bool = True
    requires_user_confirmation_before_formal_write: bool = True
    can_write_formal_state: bool = False


class ImportRequestsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = IMPORT_REQUESTS_SCHEMA_VERSION
    contract_version: str = GENERATOR_CONTRACT_VERSION
    package_manifest_ref: str = "handoff_package_v1/package_manifest.json"
    requests: list[ImportRequest] = Field(default_factory=list)


class FixtureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = FIXTURE_SCHEMA_VERSION
    contract_version: str = GENERATOR_CONTRACT_VERSION
    source: str = "analyze_stories"
    authority: str = "advisory_only"
    can_write_formal_state: bool = False
    handoff_package_ref: str = "handoff_package_v1/package_manifest.json"
    import_requests_ref: str = "import_requests.json"
    expected_preview_contract_ref: str = "expected_preview_contract.json"
    validation_summary_ref: str = "fixture_validation_summary.json"
    fixture_checks: dict[str, Any] = Field(default_factory=dict)


def _issue(code: str, message: str, path: str = "") -> dict[str, str]:
    issue = {"code": code, "message": message}
    if path:
        issue["path"] = path
    return issue


def _ensure_empty_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _copy_package(package_dir: Path, fixture_dir: Path) -> Path:
    target = fixture_dir / "handoff_package_v1"
    if target.exists():
        raise ValueError(f"Fixture package target already exists: {target}")
    shutil.copytree(package_dir, target)
    return target


def _load_catalog(package_dir: Path) -> dict[str, Any]:
    return read_json(package_dir / "modules" / "module_catalog.json")


def _module_by_id(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {module["module_instance_id"]: module for module in catalog.get("modules", [])}


def _eligible_modules(catalog: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    modules = [
        module
        for module in catalog.get("modules", [])
        if mode in module.get("recommended_modes", [])
    ]
    if mode == "original_writing":
        modules = [
            module
            for module in modules
            if module.get("source_specificity") in {"transferable", "hybrid"}
            and not module.get("depends_on")
        ]
    elif mode == "continuation_or_revision":
        modules = [module for module in modules if not module.get("depends_on")]
    else:
        modules = [
            module
            for module in modules
            if module.get("source_specificity") in {"hybrid", "transferable"}
            and not module.get("depends_on")
        ]
    return modules


def _selection_policy(mode: str) -> dict[str, Any]:
    if mode == "original_writing":
        return {
            "include_transferable": True,
            "include_hybrid": True,
            "include_source_specific": False,
            "requires_deidentification": True,
        }
    if mode == "continuation_or_revision":
        return {
            "include_transferable": True,
            "include_hybrid": True,
            "include_source_specific": True,
            "requires_deidentification": False,
        }
    return {
        "include_transferable": True,
        "include_hybrid": True,
        "include_source_specific": "user_selected",
        "requires_deidentification": "for_reused_source_specific_elements",
    }


def _build_import_requests(package_dir: Path) -> dict[str, Any]:
    catalog = _load_catalog(package_dir)
    requests: list[dict[str, Any]] = []
    for mode in GENERATION_MODES:
        selected_modules = _eligible_modules(catalog, mode)[:8]
        requests.append(
            ImportRequest(
                request_id=f"preview_{mode}",
                generation_mode=mode,
                selected_module_instance_ids=[
                    module["module_instance_id"] for module in selected_modules
                ],
                selection_policy=_selection_policy(mode),
            ).model_dump(mode="json")
        )
    return ImportRequestsPayload(requests=[ImportRequest.model_validate(item) for item in requests]).model_dump(mode="json")


def _build_expected_preview_contract() -> dict[str, Any]:
    return {
        "schema_version": EXPECTED_PREVIEW_SCHEMA_VERSION,
        "contract_version": GENERATOR_CONTRACT_VERSION,
        "expected_generator_behavior": {
            "import_stage": "preview",
            "must_validate_handoff_package": True,
            "must_compile_generation_profile_on_generator_side": True,
            "must_require_user_confirmation_before_formal_write": True,
            "formal_write_allowed_during_preview": False,
            "analyzer_package_authority": "advisory_only",
        },
        "expected_response_fields": [
            "import_status",
            "package_validation_status",
            "generation_mode",
            "selected_module_count",
            "generation_profile_status",
            "requires_user_confirmation_before_formal_write",
            "can_write_formal_state",
        ],
        "forbidden_analyzer_outputs": sorted(FORBIDDEN_KEYS),
    }


def _walk_json(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _scan_forbidden_keys(root: Path, issues: list[dict[str, str]]) -> None:
    for path in sorted(root.rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            issues.append(_issue("INVALID_JSON", str(exc), rel))
            continue
        for key, value in _walk_json(data):
            if key in FORBIDDEN_KEYS:
                issues.append(_issue("FINAL_PROFILE_IN_FIXTURE", f"forbidden key found: {key}", rel))
            if key == "can_write_formal_state" and value is True:
                issues.append(_issue("FORMAL_WRITE_PERMISSION", "formal write permission is not allowed", rel))


def _validate_request_payload(
    fixture_dir: Path,
    package_dir: Path,
    issues: list[dict[str, str]],
) -> ImportRequestsPayload | None:
    path = fixture_dir / "import_requests.json"
    try:
        payload = ImportRequestsPayload.model_validate(read_json(path))
    except (OSError, ValidationError, ValueError) as exc:
        issues.append(_issue("INVALID_IMPORT_REQUESTS", str(exc), "import_requests.json"))
        return None

    catalog = _load_catalog(package_dir)
    modules = _module_by_id(catalog)
    modes = {request.generation_mode for request in payload.requests}
    if modes != set(GENERATION_MODES):
        issues.append(_issue("MISSING_GENERATION_MODE", "fixture must include all three generation modes", "import_requests.json"))

    for request in payload.requests:
        if request.import_stage != "preview":
            issues.append(_issue("NON_PREVIEW_IMPORT_STAGE", "fixture requests must be preview-only", "import_requests.json"))
        if request.can_write_formal_state:
            issues.append(_issue("FORMAL_WRITE_REQUEST", "fixture request must not write formal state", "import_requests.json"))
        if not request.requires_profile_compilation:
            issues.append(_issue("MISSING_PROFILE_COMPILATION_REQUIREMENT", "generator must compile profile", "import_requests.json"))
        if not request.requires_user_confirmation_before_formal_write:
            issues.append(_issue("MISSING_USER_CONFIRMATION_REQUIREMENT", "user confirmation is required", "import_requests.json"))

        for module_id in request.selected_module_instance_ids:
            module = modules.get(module_id)
            if module is None:
                issues.append(_issue("UNKNOWN_SELECTED_MODULE", f"selected module not found: {module_id}", "import_requests.json"))
                continue
            if request.generation_mode not in module.get("recommended_modes", []):
                issues.append(_issue("MODE_NOT_RECOMMENDED_FOR_MODULE", f"{module_id} does not support {request.generation_mode}", "import_requests.json"))
            if request.generation_mode == "original_writing" and module.get("source_specificity") == "source_specific":
                issues.append(_issue("SOURCE_SPECIFIC_IN_ORIGINAL_MODE", f"{module_id} cannot be selected for original mode", "import_requests.json"))
    return payload


def _write_readme(fixture_dir: Path) -> None:
    readme = (
        "# Story Generator Import Contract Fixture\n\n"
        "This fixture is generated by Story Analyzer v1 for generator-side import tests. "
        "It is preview-only and advisory-only. The generator owns generation profile compilation "
        "and must require user confirmation before formal writes.\n"
    )
    (fixture_dir / "README.md").write_text(readme, encoding=DEFAULT_ENCODING)


def validate_generator_import_fixture(fixture_dir: str | Path) -> dict[str, Any]:
    root = Path(fixture_dir)
    blocking_issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    manifest_path = root / "fixture_manifest.json"
    package_dir = root / "handoff_package_v1"
    if not root.exists():
        blocking_issues.append(_issue("FIXTURE_NOT_FOUND", f"fixture not found: {root}"))
    if not manifest_path.exists():
        blocking_issues.append(_issue("MISSING_FIXTURE_MANIFEST", "fixture_manifest.json is missing"))
    if not package_dir.exists():
        blocking_issues.append(_issue("MISSING_HANDOFF_PACKAGE", "handoff_package_v1 is missing"))

    manifest: FixtureManifest | None = None
    if manifest_path.exists():
        try:
            manifest = FixtureManifest.model_validate(read_json(manifest_path))
        except (OSError, ValidationError, ValueError) as exc:
            blocking_issues.append(_issue("INVALID_FIXTURE_MANIFEST", str(exc), "fixture_manifest.json"))
        else:
            if manifest.contract_version != GENERATOR_CONTRACT_VERSION:
                blocking_issues.append(_issue("INVALID_CONTRACT_VERSION", "contract_version mismatch", "fixture_manifest.json"))
            if manifest.authority != "advisory_only":
                blocking_issues.append(_issue("NON_ADVISORY_AUTHORITY", "fixture must be advisory_only", "fixture_manifest.json"))
            if manifest.can_write_formal_state:
                blocking_issues.append(_issue("FORMAL_WRITE_PERMISSION", "fixture cannot write formal state", "fixture_manifest.json"))
            for ref in [
                manifest.handoff_package_ref,
                manifest.import_requests_ref,
                manifest.expected_preview_contract_ref,
            ]:
                if not (root / ref).exists():
                    blocking_issues.append(_issue("MISSING_REFERENCE", f"missing fixture reference: {ref}", "fixture_manifest.json"))

    if package_dir.exists():
        package_summary = validate_handoff_package(package_dir)
        if package_summary["validation_status"] != "passed":
            blocking_issues.append(_issue("INVALID_HANDOFF_PACKAGE", "embedded handoff package validation failed", "handoff_package_v1"))
        _validate_request_payload(root, package_dir, blocking_issues)

    expected_path = root / "expected_preview_contract.json"
    if expected_path.exists():
        expected = read_json(expected_path)
        if expected.get("schema_version") != EXPECTED_PREVIEW_SCHEMA_VERSION:
            blocking_issues.append(_issue("INVALID_EXPECTED_PREVIEW_CONTRACT", "invalid expected preview schema", "expected_preview_contract.json"))
        behavior = expected.get("expected_generator_behavior", {})
        if behavior.get("formal_write_allowed_during_preview") is not False:
            blocking_issues.append(_issue("FORMAL_WRITE_PERMISSION", "preview contract must disallow formal write", "expected_preview_contract.json"))
    else:
        blocking_issues.append(_issue("MISSING_EXPECTED_PREVIEW_CONTRACT", "expected_preview_contract.json is missing"))

    if root.exists():
        _scan_forbidden_keys(root, blocking_issues)

    status = "failed" if blocking_issues else "passed_with_warnings" if warnings else "passed"
    summary = {
        "schema_version": FIXTURE_VALIDATION_SCHEMA_VERSION,
        "validation_status": status,
        "checked_at": now_iso(),
        "blocking_issue_count": len(blocking_issues),
        "warning_count": len(warnings),
        "checks": {
            "handoff_package": "passed"
            if not any(issue["code"] == "INVALID_HANDOFF_PACKAGE" for issue in blocking_issues)
            else "failed",
            "preview_only": "passed"
            if not any(issue["code"] in {"FORMAL_WRITE_REQUEST", "NON_PREVIEW_IMPORT_STAGE"} for issue in blocking_issues)
            else "failed",
            "mode_coverage": "passed"
            if not any(issue["code"] == "MISSING_GENERATION_MODE" for issue in blocking_issues)
            else "failed",
            "profile_compiler_boundary": "passed"
            if not any(issue["code"] == "FINAL_PROFILE_IN_FIXTURE" for issue in blocking_issues)
            else "failed",
        },
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }
    if root.exists():
        write_json(root / "fixture_validation_summary.json", summary)
    return summary


def build_generator_import_fixture(
    package_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    source_package = Path(package_dir)
    fixture_dir = Path(output_dir)
    package_summary = validate_handoff_package(source_package)
    if package_summary["validation_status"] != "passed":
        raise ValueError("Cannot build generator import fixture from invalid handoff package")
    _ensure_empty_output_dir(fixture_dir)
    embedded_package = _copy_package(source_package, fixture_dir)

    import_requests = _build_import_requests(embedded_package)
    write_json(fixture_dir / "import_requests.json", import_requests)
    write_json(fixture_dir / "expected_preview_contract.json", _build_expected_preview_contract())
    manifest = FixtureManifest(
        fixture_checks={
            "handoff_validation_status": package_summary["validation_status"],
            "includes_all_generation_modes": True,
            "requires_profile_compiler": True,
            "no_final_generation_profile": True,
            "preview_only": True,
        }
    )
    write_json(fixture_dir / "fixture_manifest.json", manifest.model_dump(mode="json"))
    _write_readme(fixture_dir)
    validation_summary = validate_generator_import_fixture(fixture_dir)
    return {
        "fixture_dir": str(fixture_dir),
        "fixture_manifest": manifest.model_dump(mode="json"),
        "validation_summary": validation_summary,
    }

