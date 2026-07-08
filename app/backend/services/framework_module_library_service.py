import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.framework_module_library import (
    CopyrightSourceRecord,
    CopyrightSourceRecordListResponse,
    FrameworkLibraryActionRequest,
    FrameworkLibraryBuildFromAdapterDerivationRequest,
    FrameworkLibraryBuildFromConfirmedImportRequest,
    FrameworkLibraryBuildFromSelectedCandidatesRequest,
    FrameworkLibraryBuildFromVocabularyArtifactRequest,
    FrameworkLibraryBuildReport,
    FrameworkLibraryBuildResult,
    FrameworkLibraryCollection,
    FrameworkLibraryIssue,
    FrameworkLibraryItemPatchRequest,
    FrameworkLibraryListResponse,
    FrameworkLibrarySourceRef,
    FrameworkMaturityRecord,
    FrameworkMaturityRecordListResponse,
    FrameworkModuleLibraryItem,
    FrameworkPatternListResponse,
    FrameworkPatternRecord,
    ModuleCompositionRule,
    ModuleCompositionRuleListResponse,
    SystemRecommendedFramework,
    SystemRecommendedFrameworkListResponse,
    UserPrivateFramework,
    UserPrivateFrameworkCreateRequest,
    UserPrivateFrameworkListResponse,
)
from app.backend.storage.json_store import JsonStore, StorageError


SCHEMA_VERSION = "phase5_m7_framework_module_library_v1"
LOCAL_PROJECT_ID = "local_project"

ITEMS_FILE = "framework_module_library_items.json"
PATTERNS_FILE = "framework_pattern_records.json"
COMPOSITION_RULES_FILE = "module_composition_rules.json"
MATURITY_FILE = "framework_maturity_records.json"
COPYRIGHT_FILE = "copyright_source_records.json"
PRIVATE_FRAMEWORKS_FILE = "user_private_frameworks.json"
SYSTEM_RECOMMENDATIONS_FILE = "system_recommended_frameworks.json"
COLLECTIONS_FILE = "framework_library_collections.json"
BUILD_REPORTS_FILE = "framework_library_build_reports.json"
DEFAULT_LIBRARY_SOURCE_ID = "project_codes_default_framework_library"
REPAIRABLE_TEXT_FIELDS = {
    "label",
    "description",
    "safe_summary",
    "title",
    "message",
    "safe_detail",
}

M4_DECISIONS_FILE = "imported_framework_decisions.json"
M4_SESSIONS_FILE = "imported_framework_edit_sessions.json"
M4_PLANS_FILE = "imported_framework_activation_plans.json"
FRAMEWORK_CANDIDATES_FILE = "framework_package_candidates.json"
M6_DERIVATION_REPORTS_FILE = "analyze_stories_adapter_derivation_reports.json"
M6_CANDIDATE_FILES = [
    "analyze_stories_chapter_archive_candidates.json",
    "analyze_stories_narrative_debt_candidates.json",
    "analyze_stories_open_thread_candidates.json",
    "analyze_stories_closed_thread_candidates.json",
    "analyze_stories_payoff_candidates.json",
    "analyze_stories_apparent_contradiction_template_candidates.json",
]

UNSAFE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|raw[_-]?prompt|raw[_-]?response|"
    r"hidden[_-]?reasoning|internal[_-]?reasoning|chain[_-]?of[_-]?thought|"
    r"full[_-]?prose|complete[_-]?story|story[_-]?text|chapter[_-]?text|secret)",
    re.IGNORECASE,
)
UNSAFE_VALUE_RE = re.compile(
    r"(RAW_PROMPT|RAW_RESPONSE|HIDDEN_REASONING|INTERNAL_REASONING|CHAIN_OF_THOUGHT|"
    r"chain-of-thought|raw prompt|raw response|hidden reasoning|internal reasoning|"
    r"full prose|complete story text|\bsk-[A-Za-z0-9_\-]{8,}|lsv2_|"
    r"Bearer\s+[A-Za-z0-9_\-\.]{8,})",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class FrameworkModuleLibraryService:
    _ensure_lock = threading.RLock()

    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.items_file = self.data_dir / ITEMS_FILE
        self.patterns_file = self.data_dir / PATTERNS_FILE
        self.rules_file = self.data_dir / COMPOSITION_RULES_FILE
        self.maturity_file = self.data_dir / MATURITY_FILE
        self.copyright_file = self.data_dir / COPYRIGHT_FILE
        self.private_frameworks_file = self.data_dir / PRIVATE_FRAMEWORKS_FILE
        self.system_recommendations_file = self.data_dir / SYSTEM_RECOMMENDATIONS_FILE
        self.collections_file = self.data_dir / COLLECTIONS_FILE
        self.build_reports_file = self.data_dir / BUILD_REPORTS_FILE

    def build_from_confirmed_import(
        self,
        request: FrameworkLibraryBuildFromConfirmedImportRequest,
    ) -> FrameworkLibraryBuildResult:
        self._start_id_session()
        self._ensure_storage_files()
        self._guard_safe_payload(request.safe_user_note)
        decision = self._find_by_id(
            self.data_dir / M4_DECISIONS_FILE,
            "decision_id",
            request.imported_framework_decision_id,
            "FRAMEWORK_LIBRARY_IMPORTED_DECISION_NOT_FOUND",
        )
        decision_type = str(decision.get("decision_type") or "")
        activation_mode = str(decision.get("activation_mode") or "")
        if not decision_type.startswith("confirm_") or activation_mode not in {"merge", "reference_only"}:
            return self._blocked_result(
                "m4_confirmed_import",
                request.imported_framework_decision_id,
                [
                    self._issue(
                        "imported_framework_decision_not_eligible",
                        "blocking",
                        "Only confirm_merge and confirm_reference_only imported framework decisions can create M7 library assets.",
                        "decision_type",
                    )
                ],
            )
        session = self._find_by_id(
            self.data_dir / M4_SESSIONS_FILE,
            "edit_session_id",
            str(decision.get("edit_session_id") or ""),
            "FRAMEWORK_LIBRARY_IMPORTED_SESSION_NOT_FOUND",
        )
        plan_id = str(decision.get("plan_id") or "")
        plan = self._find_optional_by_id(self.data_dir / M4_PLANS_FILE, "plan_id", plan_id)
        validation = session.get("latest_validation_report") or session.get("validation_report") or {}
        if isinstance(plan, dict) and isinstance(plan.get("validation_report"), dict):
            validation = plan["validation_report"]
        if validation.get("blocking_issues"):
            return self._blocked_result(
                "m4_confirmed_import",
                request.imported_framework_decision_id,
                [
                    self._issue(
                        "source_validation_has_blocking_issues",
                        "blocking",
                        "The imported framework validation report has blocking issues.",
                        "validation_report.blocking_issues",
                    )
                ],
            )
        package = session.get("working_framework_package")
        if not isinstance(package, dict):
            return self._blocked_result(
                "m4_confirmed_import",
                request.imported_framework_decision_id,
                [
                    self._issue(
                        "working_framework_package_missing",
                        "blocking",
                        "The imported framework edit session has no working framework package.",
                        "working_framework_package",
                    )
                ],
            )
        self._guard_safe_payload(package)
        timestamp = now_iso()
        source_type = "m4_confirmed_import" if activation_mode == "merge" else "m4_reference_only"
        visibility = "project_local" if activation_mode == "merge" else "private"
        maturity_level = "user_confirmed" if activation_mode == "merge" else "user_reviewed"
        constraint_strength = "user_confirmed" if activation_mode == "merge" else "reference"
        candidate = self._find_optional_by_id(
            self.data_dir / FRAMEWORK_CANDIDATES_FILE,
            "candidate_id",
            str(session.get("candidate_id") or ""),
        )
        fingerprint_ids = self._candidate_fingerprint_ids(candidate)
        source_refs = self._m4_source_refs(decision, session, candidate, source_type, fingerprint_ids)
        copyright_record = self._create_copyright_record(
            source_type,
            request.imported_framework_decision_id,
            fingerprint_ids=fingerprint_ids,
            risk_level="low" if fingerprint_ids else "medium",
            visibility_limit=visibility,
            timestamp=timestamp,
            warnings=[] if fingerprint_ids else [
                self._issue(
                    "source_input_fingerprint_missing",
                    "warning",
                    "Source input fingerprints were missing; no system recommendation can be created.",
                    "source_input_fingerprint_ids",
                )
            ],
        )
        maturity_record = self._create_maturity_record(
            source_type,
            request.imported_framework_decision_id,
            maturity_level,
            timestamp,
            safe_summary=f"Library assets from {decision_type}.",
        )
        items: list[FrameworkModuleLibraryItem] = []
        for component in self._macro_components(package):
            items.append(
                self._create_item(
                    item_type="macro_component",
                    source_type=source_type,
                    label=self._component_label(component, "macro_component"),
                    description=self._component_description(component),
                    safe_summary=self._short(self._component_description(component), 260),
                    source_refs=source_refs,
                    visibility=visibility,
                    constraint_strength=constraint_strength,
                    maturity_record_id=maturity_record.maturity_record_id,
                    copyright_source_record_id=copyright_record.copyright_source_record_id,
                    timestamp=timestamp,
                )
            )
        for module in self._chapter_modules(package):
            items.append(
                self._create_item(
                    item_type="chapter_module",
                    source_type=source_type,
                    label=self._component_label(module, "chapter_module"),
                    description=self._component_description(module),
                    safe_summary=self._short(self._component_description(module), 260),
                    source_refs=source_refs,
                    visibility=visibility,
                    constraint_strength=constraint_strength,
                    maturity_record_id=maturity_record.maturity_record_id,
                    copyright_source_record_id=copyright_record.copyright_source_record_id,
                    timestamp=timestamp,
                )
            )
        for component in self._module_components(package):
            items.append(
                self._create_item(
                    item_type="module_component",
                    source_type=source_type,
                    label=self._component_label(component, "module_component"),
                    description=self._component_description(component),
                    safe_summary=self._short(self._component_description(component), 260),
                    source_refs=source_refs,
                    visibility=visibility,
                    constraint_strength=constraint_strength,
                    maturity_record_id=maturity_record.maturity_record_id,
                    copyright_source_record_id=copyright_record.copyright_source_record_id,
                    timestamp=timestamp,
                )
            )
        for item in items:
            self._append(self.items_file, model_to_dict(item))
        self._append(self.maturity_file, model_to_dict(maturity_record))
        self._append(self.copyright_file, model_to_dict(copyright_record))
        report = self._create_build_report(
            source_type,
            request.imported_framework_decision_id,
            timestamp,
            item_ids=[item.library_item_id for item in items],
            maturity_ids=[maturity_record.maturity_record_id],
            copyright_ids=[copyright_record.copyright_source_record_id],
            warnings=[],
            blocking=[],
        )
        return FrameworkLibraryBuildResult(
            success=bool(items),
            build_report=report,
            items=items,
            maturity_records=[maturity_record],
            copyright_sources=[copyright_record],
        )

    def build_from_adapter_derivation(
        self,
        request: FrameworkLibraryBuildFromAdapterDerivationRequest,
    ) -> FrameworkLibraryBuildResult:
        self._start_id_session()
        self._ensure_storage_files()
        self._guard_safe_payload(request.safe_user_note)
        report = self._find_by_id(
            self.data_dir / M6_DERIVATION_REPORTS_FILE,
            "derivation_report_id",
            request.derivation_report_id,
            "FRAMEWORK_LIBRARY_ADAPTER_DERIVATION_NOT_FOUND",
        )
        if report.get("derivation_status") not in {"completed", "completed_with_warnings"}:
            return self._blocked_result(
                "m6_reviewed_candidate",
                request.derivation_report_id,
                [
                    self._issue(
                        "adapter_derivation_not_eligible",
                        "blocking",
                        "Only completed adapter derivations can create M7 library assets.",
                        "derivation_status",
                    )
                ],
            )
        candidates = [
            candidate
            for candidate in self._read_all_m6_candidates()
            if candidate.get("derivation_report_id") == request.derivation_report_id
        ]
        return self._build_from_m6_candidates(
            candidates,
            source_id=request.derivation_report_id,
            source_kind="derivation",
        )

    def build_from_selected_candidates(
        self,
        request: FrameworkLibraryBuildFromSelectedCandidatesRequest,
    ) -> FrameworkLibraryBuildResult:
        self._start_id_session()
        self._ensure_storage_files()
        self._guard_safe_payload(request.safe_user_note)
        if not request.candidate_ids:
            return self._blocked_result(
                "m6_reviewed_candidate",
                "selected_candidates",
                [self._issue("candidate_ids_required", "blocking", "At least one candidate id is required.", "candidate_ids")],
            )
        all_candidates = self._read_all_m6_candidates()
        by_id = {str(item.get("candidate_id")): item for item in all_candidates}
        missing = [candidate_id for candidate_id in request.candidate_ids if candidate_id not in by_id]
        if missing:
            raise StorageError(f"FRAMEWORK_LIBRARY_ADAPTER_CANDIDATE_NOT_FOUND: {missing[0]}")
        return self._build_from_m6_candidates(
            [by_id[candidate_id] for candidate_id in request.candidate_ids],
            source_id="selected_candidates",
            source_kind="selected_candidates",
        )

    def build_from_vocabulary_artifact(
        self,
        request: FrameworkLibraryBuildFromVocabularyArtifactRequest,
    ) -> FrameworkLibraryBuildResult:
        self._start_id_session()
        self._ensure_storage_files()
        self._guard_safe_payload(request.safe_user_note)
        self._guard_safe_payload(request.artifact)
        timestamp = now_iso()
        source_id = str(request.source_ref.get("source_id") or "vocabulary_fixture")
        source_refs = [
            FrameworkLibrarySourceRef(
                source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
                source_type="analyze_stories_vocabulary",
                source_id=source_id,
                relationship="supports",
                field_path="artifact",
                source_import_id=str(request.source_ref.get("source_import_id") or "") or None,
                source_artifact_id=str(request.source_ref.get("source_artifact_id") or "") or None,
                source_input_fingerprint_ids=[
                    str(item) for item in request.source_ref.get("source_input_fingerprint_ids", []) if item
                ],
                safe_summary=self._short(request.source_ref.get("safe_summary") or "Analyze Stories vocabulary artifact.", 180),
            )
        ]
        records, warnings, authority_downgraded = self._extract_vocabulary_records(request.artifact)
        copyright_record = self._create_copyright_record(
            "analyze_stories_vocabulary",
            source_id,
            fingerprint_ids=source_refs[0].source_input_fingerprint_ids,
            risk_level="medium",
            visibility_limit="private",
            timestamp=timestamp,
            warnings=warnings,
            examples_stripped=True,
            authority_downgraded=authority_downgraded,
        )
        maturity_record = self._create_maturity_record(
            "analyze_stories_vocabulary",
            source_id,
            "raw_import",
            timestamp,
            safe_summary="Vocabulary-derived records are private references only.",
        )
        items = [
            self._create_item(
                item_type=record["item_type"],
                source_type="analyze_stories_vocabulary",
                label=record["label"],
                description=record["description"],
                safe_summary=record["safe_summary"],
                source_refs=source_refs,
                visibility="private",
                constraint_strength="reference",
                maturity_record_id=maturity_record.maturity_record_id,
                copyright_source_record_id=copyright_record.copyright_source_record_id,
                timestamp=timestamp,
                warnings=warnings,
            )
            for record in records
        ]
        for item in items:
            self._append(self.items_file, model_to_dict(item))
        self._append(self.maturity_file, model_to_dict(maturity_record))
        self._append(self.copyright_file, model_to_dict(copyright_record))
        report = self._create_build_report(
            "analyze_stories_vocabulary",
            source_id,
            timestamp,
            item_ids=[item.library_item_id for item in items],
            maturity_ids=[maturity_record.maturity_record_id],
            copyright_ids=[copyright_record.copyright_source_record_id],
            warnings=warnings,
            blocking=[],
        )
        return FrameworkLibraryBuildResult(
            success=bool(items),
            build_report=report,
            items=items,
            maturity_records=[maturity_record],
            copyright_sources=[copyright_record],
        )

    def list_items(
        self,
        *,
        item_type: str | None = None,
        source_type: str | None = None,
        visibility: str | None = None,
        maturity_level: str | None = None,
        risk_level: str | None = None,
    ) -> FrameworkLibraryListResponse:
        self._ensure_storage_files()
        maturity_by_id = {
            item.get("maturity_record_id"): item
            for item in self._read_list(self.maturity_file)
        }
        copyright_by_id = {
            item.get("copyright_source_record_id"): item
            for item in self._read_list(self.copyright_file)
        }
        records = []
        for item in self._read_list(self.items_file):
            if item_type and item.get("item_type") != item_type:
                continue
            if source_type and item.get("source_type") != source_type:
                continue
            if visibility and item.get("visibility") != visibility:
                continue
            maturity = maturity_by_id.get(item.get("maturity_record_id")) or {}
            copyright_record = copyright_by_id.get(item.get("copyright_source_record_id")) or {}
            if maturity_level and maturity.get("maturity_level") != maturity_level:
                continue
            if risk_level and copyright_record.get("risk_level") != risk_level:
                continue
            records.append(FrameworkModuleLibraryItem(**item))
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return FrameworkLibraryListResponse(items=records, total_count=len(records))

    def get_item(self, library_item_id: str) -> FrameworkModuleLibraryItem:
        self._ensure_storage_files()
        return FrameworkModuleLibraryItem(
            **self._find_by_id(self.items_file, "library_item_id", library_item_id, "FRAMEWORK_LIBRARY_ITEM_NOT_FOUND")
        )

    def patch_item(
        self,
        library_item_id: str,
        request: FrameworkLibraryItemPatchRequest,
    ) -> FrameworkModuleLibraryItem:
        self._guard_safe_payload(request.safe_user_note)
        record = self._find_by_id(self.items_file, "library_item_id", library_item_id, "FRAMEWORK_LIBRARY_ITEM_NOT_FOUND")
        if request.visibility:
            self._validate_item_visibility_patch(record, request.visibility)
            record["visibility"] = request.visibility
        record["updated_at"] = now_iso()
        self._replace(self.items_file, "library_item_id", library_item_id, record)
        return FrameworkModuleLibraryItem(**record)

    def archive_item(
        self,
        library_item_id: str,
        request: FrameworkLibraryActionRequest | None = None,
    ) -> FrameworkModuleLibraryItem:
        request = request or FrameworkLibraryActionRequest()
        self._guard_safe_payload(request.safe_user_note)
        record = self._find_by_id(self.items_file, "library_item_id", library_item_id, "FRAMEWORK_LIBRARY_ITEM_NOT_FOUND")
        record["visibility"] = "archived"
        record["updated_at"] = now_iso()
        self._replace(self.items_file, "library_item_id", library_item_id, record)
        return FrameworkModuleLibraryItem(**record)

    def list_patterns(self, pattern_type: str | None = None, source_type: str | None = None) -> FrameworkPatternListResponse:
        self._ensure_storage_files()
        records = []
        for item in self._read_list(self.patterns_file):
            if pattern_type and item.get("pattern_type") != pattern_type:
                continue
            if source_type and item.get("source_type") != source_type:
                continue
            records.append(FrameworkPatternRecord(**item))
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return FrameworkPatternListResponse(patterns=records, total_count=len(records))

    def get_pattern(self, pattern_id: str) -> FrameworkPatternRecord:
        self._ensure_storage_files()
        return FrameworkPatternRecord(
            **self._find_by_id(self.patterns_file, "pattern_id", pattern_id, "FRAMEWORK_LIBRARY_PATTERN_NOT_FOUND")
        )

    def list_composition_rules(self, status: str | None = None) -> ModuleCompositionRuleListResponse:
        self._ensure_storage_files()
        records = []
        for item in self._read_list(self.rules_file):
            if status and item.get("rule_status") != status:
                continue
            records.append(ModuleCompositionRule(**item))
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return ModuleCompositionRuleListResponse(composition_rules=records, total_count=len(records))

    def get_composition_rule(self, rule_id: str) -> ModuleCompositionRule:
        self._ensure_storage_files()
        return ModuleCompositionRule(
            **self._find_by_id(self.rules_file, "rule_id", rule_id, "FRAMEWORK_LIBRARY_RULE_NOT_FOUND")
        )

    def mark_composition_rule_reviewed(self, rule_id: str, request: FrameworkLibraryActionRequest | None = None) -> ModuleCompositionRule:
        return self._set_rule_status(rule_id, "reviewed", request)

    def reject_composition_rule(self, rule_id: str, request: FrameworkLibraryActionRequest | None = None) -> ModuleCompositionRule:
        return self._set_rule_status(rule_id, "rejected", request)

    def list_maturity_records(self) -> FrameworkMaturityRecordListResponse:
        self._ensure_storage_files()
        records = [FrameworkMaturityRecord(**item) for item in self._read_list(self.maturity_file)]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return FrameworkMaturityRecordListResponse(maturity_records=records, total_count=len(records))

    def list_copyright_sources(self, risk_level: str | None = None) -> CopyrightSourceRecordListResponse:
        self._ensure_storage_files()
        records = []
        for item in self._read_list(self.copyright_file):
            if risk_level and item.get("risk_level") != risk_level:
                continue
            records.append(CopyrightSourceRecord(**item))
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return CopyrightSourceRecordListResponse(copyright_sources=records, total_count=len(records))

    def create_private_framework(
        self,
        request: UserPrivateFrameworkCreateRequest,
    ) -> FrameworkLibraryBuildResult:
        self._start_id_session()
        self._ensure_storage_files()
        self._guard_safe_payload(request.safe_user_note)
        self._validate_private_framework_refs(request)
        timestamp = now_iso()
        private_framework = UserPrivateFramework(
            private_framework_id=self._next_id(self.private_frameworks_file, "private_framework_id", "private_framework"),
            title=self._short(request.title, 120) or "Private framework collection",
            item_ids=request.item_ids,
            pattern_ids=request.pattern_ids,
            composition_rule_ids=request.composition_rule_ids,
            safe_summary=self._short(f"Private framework with {len(request.item_ids)} items, {len(request.pattern_ids)} patterns, and {len(request.composition_rule_ids)} rules.", 260),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._append(self.private_frameworks_file, model_to_dict(private_framework))
        collection = FrameworkLibraryCollection(
            collection_id=self._next_id(self.collections_file, "collection_id", "framework_library_collection"),
            title=private_framework.title,
            item_ids=private_framework.item_ids,
            pattern_ids=private_framework.pattern_ids,
            composition_rule_ids=private_framework.composition_rule_ids,
            safe_summary=private_framework.safe_summary,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._append(self.collections_file, model_to_dict(collection))
        report = self._create_build_report(
            "user_created",
            private_framework.private_framework_id,
            timestamp,
            private_framework_ids=[private_framework.private_framework_id],
            warnings=[],
            blocking=[],
        )
        return FrameworkLibraryBuildResult(
            success=True,
            build_report=report,
            private_frameworks=[private_framework],
        )

    def list_private_frameworks(self) -> UserPrivateFrameworkListResponse:
        self._ensure_storage_files()
        records = [UserPrivateFramework(**item) for item in self._read_list(self.private_frameworks_file)]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return UserPrivateFrameworkListResponse(private_frameworks=records, total_count=len(records))

    def list_system_recommendations(self) -> SystemRecommendedFrameworkListResponse:
        self._ensure_storage_files()
        records = [
            SystemRecommendedFramework(**item)
            for item in self._read_list(self.system_recommendations_file)
        ]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return SystemRecommendedFrameworkListResponse(system_recommendations=records, total_count=len(records))

    def _build_from_m6_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        source_id: str,
        source_kind: str,
    ) -> FrameworkLibraryBuildResult:
        timestamp = now_iso()
        eligible = []
        skipped = []
        for candidate in candidates:
            if candidate.get("candidate_status") != "reviewed":
                skipped.append(candidate)
                continue
            if candidate.get("candidate_family") == "chapter_archive":
                skipped.append(candidate)
                continue
            if candidate.get("reliability_level") == "blocked" or candidate.get("blocking_issues"):
                skipped.append(candidate)
                continue
            eligible.append(candidate)
        if not eligible:
            return self._blocked_result(
                "m6_reviewed_candidate",
                source_id,
                [
                    self._issue(
                        "no_reviewed_semantic_candidates",
                        "blocking",
                        "M7 library records require reviewed, non-blocked semantic M6 candidates.",
                        source_kind,
                    )
                ],
            )
        patterns: list[FrameworkPatternRecord] = []
        items: list[FrameworkModuleLibraryItem] = []
        rules: list[ModuleCompositionRule] = []
        maturity_records: list[FrameworkMaturityRecord] = []
        copyright_records: list[CopyrightSourceRecord] = []
        for candidate in eligible:
            family = str(candidate.get("candidate_family") or "")
            candidate_id = str(candidate.get("candidate_id") or "")
            source_refs = self._m6_source_refs(candidate)
            if not source_refs:
                continue
            copyright_record = self._create_copyright_record(
                "m6_reviewed_candidate",
                candidate_id,
                fingerprint_ids=self._candidate_source_fingerprint_ids(candidate),
                risk_level="medium",
                visibility_limit="private",
                timestamp=timestamp,
                warnings=[
                    self._issue(
                        "source_input_fingerprint_missing",
                        "warning",
                        "M6 adapter candidate source fingerprints are not directly present; record remains private/project-local reference only.",
                        "source_refs",
                    )
                ],
            )
            maturity_record = self._create_maturity_record(
                "m6_reviewed_candidate",
                candidate_id,
                "user_reviewed",
                timestamp,
                safe_summary=f"Reviewed M6 {family} candidate.",
            )
            copyright_records.append(copyright_record)
            maturity_records.append(maturity_record)
            pattern_type = self._pattern_type_for_family(family)
            pattern = FrameworkPatternRecord(
                pattern_id=self._next_id(self.patterns_file, "pattern_id", "framework_pattern"),
                pattern_type=pattern_type,
                source_type="m6_reviewed_candidate",
                label=self._label_for_candidate(candidate),
                safe_summary=self._short(candidate.get("safe_summary") or self._candidate_text(candidate), 260),
                source_refs=source_refs,
                visibility="private",
                maturity_record_id=maturity_record.maturity_record_id,
                copyright_source_record_id=copyright_record.copyright_source_record_id,
                requires_user_confirmation=True,
                warnings=[],
                created_at=timestamp,
                updated_at=timestamp,
                version_id=SCHEMA_VERSION,
            )
            patterns.append(pattern)
            if family in {"apparent_contradiction_template", "narrative_debt"}:
                items.append(
                    self._create_item(
                        item_type="apparent_contradiction_template" if family == "apparent_contradiction_template" else "narrative_debt_pattern",
                        source_type="m6_reviewed_candidate",
                        label=pattern.label,
                        description=pattern.safe_summary,
                        safe_summary=pattern.safe_summary,
                        source_refs=source_refs,
                        visibility="private",
                        constraint_strength="suggestion",
                        maturity_record_id=maturity_record.maturity_record_id,
                        copyright_source_record_id=copyright_record.copyright_source_record_id,
                        timestamp=timestamp,
                    )
                )
            if family in {"open_thread", "closed_thread", "payoff"}:
                rules.append(
                    ModuleCompositionRule(
                        rule_id=self._next_id(self.rules_file, "rule_id", "module_composition_rule"),
                        relation_type=self._relation_type_for_family(family),
                        source_type="m6_reviewed_candidate",
                        source_pattern_ids=[pattern.pattern_id],
                        rule_status="candidate",
                        requires_user_confirmation=True,
                        source_refs=source_refs,
                        safe_summary=self._short(f"{pattern.label} is a reusable suggestion, not a hard constraint.", 260),
                        warnings=[],
                        created_at=timestamp,
                        updated_at=timestamp,
                        version_id=SCHEMA_VERSION,
                    )
                )
        for record in maturity_records:
            self._append(self.maturity_file, model_to_dict(record))
        for record in copyright_records:
            self._append(self.copyright_file, model_to_dict(record))
        for pattern in patterns:
            self._append(self.patterns_file, model_to_dict(pattern))
        for item in items:
            self._append(self.items_file, model_to_dict(item))
        for rule in rules:
            self._append(self.rules_file, model_to_dict(rule))
        report = self._create_build_report(
            "m6_reviewed_candidate",
            source_id,
            timestamp,
            item_ids=[item.library_item_id for item in items],
            pattern_ids=[pattern.pattern_id for pattern in patterns],
            rule_ids=[rule.rule_id for rule in rules],
            maturity_ids=[record.maturity_record_id for record in maturity_records],
            copyright_ids=[record.copyright_source_record_id for record in copyright_records],
            warnings=[
                self._issue(
                    "non_reviewed_candidates_skipped",
                    "warning",
                    f"Skipped {len(skipped)} non-reviewed, chapter_archive, rejected, deferred, candidate, or blocked M6 candidates.",
                    "candidate_status",
                )
            ] if skipped else [],
            blocking=[],
        )
        return FrameworkLibraryBuildResult(
            success=bool(patterns or items or rules),
            build_report=report,
            items=items,
            patterns=patterns,
            composition_rules=rules,
            maturity_records=maturity_records,
            copyright_sources=copyright_records,
        )

    def _blocked_result(
        self,
        source_type: str,
        source_id: str,
        blocking: list[FrameworkLibraryIssue],
    ) -> FrameworkLibraryBuildResult:
        timestamp = now_iso()
        report = self._create_build_report(
            source_type,
            source_id,
            timestamp,
            warnings=[],
            blocking=blocking,
            append=True,
        )
        return FrameworkLibraryBuildResult(success=False, build_report=report)

    def _create_build_report(
        self,
        source_type: str,
        source_id: str,
        timestamp: str,
        *,
        item_ids: list[str] | None = None,
        pattern_ids: list[str] | None = None,
        rule_ids: list[str] | None = None,
        maturity_ids: list[str] | None = None,
        copyright_ids: list[str] | None = None,
        private_framework_ids: list[str] | None = None,
        warnings: list[FrameworkLibraryIssue] | None = None,
        blocking: list[FrameworkLibraryIssue] | None = None,
        append: bool = True,
    ) -> FrameworkLibraryBuildReport:
        item_ids = item_ids or []
        pattern_ids = pattern_ids or []
        rule_ids = rule_ids or []
        maturity_ids = maturity_ids or []
        copyright_ids = copyright_ids or []
        private_framework_ids = private_framework_ids or []
        warnings = warnings or []
        blocking = blocking or []
        total = len(item_ids) + len(pattern_ids) + len(rule_ids) + len(private_framework_ids)
        status = "blocked" if blocking else "completed_with_warnings" if warnings else "completed" if total else "no_records"
        report = FrameworkLibraryBuildReport(
            build_report_id=self._next_id(self.build_reports_file, "build_report_id", "framework_library_build_report"),
            build_status=status,
            source_type=source_type,
            source_id=source_id,
            created_library_item_ids=item_ids,
            created_pattern_ids=pattern_ids,
            created_composition_rule_ids=rule_ids,
            created_maturity_record_ids=maturity_ids,
            created_copyright_source_record_ids=copyright_ids,
            created_private_framework_ids=private_framework_ids,
            warnings=warnings,
            blocking_issues=blocking,
            safe_summary=self._short(f"M7 library build from {source_type}: {total} reusable records.", 260),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        if append:
            self._append(self.build_reports_file, model_to_dict(report))
        return report

    def _create_maturity_record(
        self,
        source_type: str,
        source_id: str,
        maturity_level: str,
        timestamp: str,
        *,
        safe_summary: str,
    ) -> FrameworkMaturityRecord:
        return FrameworkMaturityRecord(
            maturity_record_id=self._next_id(self.maturity_file, "maturity_record_id", "framework_maturity"),
            maturity_level=maturity_level,  # type: ignore[arg-type]
            source_type=source_type,  # type: ignore[arg-type]
            source_id=source_id,
            requires_user_confirmation=True,
            safe_summary=self._short(safe_summary, 260),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _create_copyright_record(
        self,
        source_type: str,
        source_id: str,
        *,
        fingerprint_ids: list[str],
        risk_level: str,
        visibility_limit: str,
        timestamp: str,
        warnings: list[FrameworkLibraryIssue],
        examples_stripped: bool = False,
        authority_downgraded: bool = False,
    ) -> CopyrightSourceRecord:
        return CopyrightSourceRecord(
            copyright_source_record_id=self._next_id(self.copyright_file, "copyright_source_record_id", "copyright_source"),
            source_type=source_type,  # type: ignore[arg-type]
            source_id=source_id,
            risk_level=risk_level,  # type: ignore[arg-type]
            visibility_limit=visibility_limit,  # type: ignore[arg-type]
            has_source_fingerprint=bool(fingerprint_ids),
            source_input_fingerprint_ids=fingerprint_ids,
            examples_stripped=examples_stripped,
            authority_downgraded=authority_downgraded,
            warnings=warnings,
            safe_summary=self._short(
                "Source is bounded to safe summaries and references; no raw prose or secrets stored.",
                260,
            ),
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _create_item(
        self,
        *,
        item_type: str,
        source_type: str,
        label: str,
        description: str,
        safe_summary: str,
        source_refs: list[FrameworkLibrarySourceRef],
        visibility: str,
        constraint_strength: str,
        maturity_record_id: str,
        copyright_source_record_id: str,
        timestamp: str,
        warnings: list[FrameworkLibraryIssue] | None = None,
    ) -> FrameworkModuleLibraryItem:
        self._guard_safe_payload({"label": label, "description": description, "safe_summary": safe_summary})
        return FrameworkModuleLibraryItem(
            library_item_id=self._next_id(self.items_file, "library_item_id", "framework_library_item"),
            item_type=item_type,  # type: ignore[arg-type]
            source_type=source_type,  # type: ignore[arg-type]
            label=self._short(label, 120) or item_type,
            description=self._short(description, 500),
            safe_summary=self._short(safe_summary or description, 260),
            source_refs=source_refs,
            visibility=visibility,  # type: ignore[arg-type]
            constraint_strength=constraint_strength,  # type: ignore[arg-type]
            maturity_record_id=maturity_record_id,
            copyright_source_record_id=copyright_source_record_id,
            requires_user_confirmation=True,
            warnings=warnings or [],
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

    def _m4_source_refs(
        self,
        decision: dict[str, Any],
        session: dict[str, Any],
        candidate: dict[str, Any] | None,
        source_type: str,
        fingerprint_ids: list[str],
    ) -> list[FrameworkLibrarySourceRef]:
        refs = [
            FrameworkLibrarySourceRef(
                source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
                source_type=source_type,
                source_id=str(decision.get("decision_id") or ""),
                relationship="confirms",
                field_path="imported_framework_decisions",
                source_import_id=str(session.get("import_id") or "") or None,
                source_artifact_id=str(session.get("artifact_id") or "") or None,
                source_candidate_id=str(session.get("candidate_id") or "") or None,
                source_imported_framework_decision_id=str(decision.get("decision_id") or "") or None,
                source_input_fingerprint_ids=fingerprint_ids,
                safe_summary=self._short(decision.get("safe_summary") or "Confirmed imported framework decision.", 180),
            )
        ]
        for source_ref in session.get("source_refs") or []:
            if not isinstance(source_ref, dict):
                continue
            refs.append(
                FrameworkLibrarySourceRef(
                    source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
                    source_type=source_type,
                    source_id=str(source_ref.get("source_id") or session.get("candidate_id") or ""),
                    relationship=str(source_ref.get("relationship") or "supports"),
                    field_path="imported_framework_edit_sessions.source_refs",
                    source_import_id=str(session.get("import_id") or "") or None,
                    source_artifact_id=str(session.get("artifact_id") or "") or None,
                    source_candidate_id=str(session.get("candidate_id") or "") or None,
                    source_viewer_state_id=(
                        str(source_ref.get("source_id"))
                        if source_ref.get("source_type") == "analysis_report_viewer"
                        else None
                    ),
                    source_input_fingerprint_ids=fingerprint_ids,
                    safe_summary=self._short(source_ref.get("safe_summary") or source_ref.get("source_type") or "", 180),
                )
            )
        if candidate:
            refs.append(
                FrameworkLibrarySourceRef(
                    source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
                    source_type=source_type,
                    source_id=str(candidate.get("candidate_id") or ""),
                    relationship="supports",
                    field_path="framework_package_candidates",
                    source_import_id=str(candidate.get("import_id") or "") or None,
                    source_artifact_id=str(candidate.get("artifact_id") or "") or None,
                    source_candidate_id=str(candidate.get("candidate_id") or "") or None,
                    source_input_fingerprint_ids=fingerprint_ids,
                    safe_summary="Inactive normalized framework candidate.",
                )
            )
        return refs

    def _m6_source_refs(self, candidate: dict[str, Any]) -> list[FrameworkLibrarySourceRef]:
        refs = []
        base_source_refs = candidate.get("source_refs") or []
        if not isinstance(base_source_refs, list):
            base_source_refs = []
        refs.append(
            FrameworkLibrarySourceRef(
                source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
                source_type="m6_reviewed_candidate",
                source_id=str(candidate.get("candidate_id") or ""),
                relationship="supports",
                field_path="analyze_stories_adapter_candidates",
                source_import_id=str(candidate.get("import_id") or "") or None,
                source_artifact_id=str(candidate.get("artifact_id") or "") or None,
                source_candidate_id=str(candidate.get("candidate_id") or "") or None,
                source_derivation_report_id=str(candidate.get("derivation_report_id") or "") or None,
                source_viewer_state_id=str(candidate.get("viewer_state_id") or "") or None,
                source_report_section_id=",".join(str(item) for item in candidate.get("section_view_ids") or []) or None,
                safe_summary=self._short(candidate.get("safe_summary") or self._candidate_text(candidate), 180),
            )
        )
        for source_ref in base_source_refs[:8]:
            if not isinstance(source_ref, dict):
                continue
            refs.append(
                FrameworkLibrarySourceRef(
                    source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
                    source_type="m6_reviewed_candidate",
                    source_id=str(source_ref.get("source_id") or candidate.get("candidate_id") or ""),
                    relationship=str(source_ref.get("relationship") or "supports"),
                    field_path=str(source_ref.get("field_path") or "source_refs"),
                    source_import_id=str(candidate.get("import_id") or "") or None,
                    source_artifact_id=str(candidate.get("artifact_id") or "") or None,
                    source_candidate_id=str(candidate.get("candidate_id") or "") or None,
                    source_derivation_report_id=str(candidate.get("derivation_report_id") or "") or None,
                    source_viewer_state_id=str(candidate.get("viewer_state_id") or "") or None,
                    safe_summary=self._short(source_ref.get("safe_summary") or "", 180),
                )
            )
        return refs

    def _extract_vocabulary_records(self, artifact: dict[str, Any]) -> tuple[list[dict[str, str]], list[FrameworkLibraryIssue], bool]:
        records: list[dict[str, str]] = []
        warnings: list[FrameworkLibraryIssue] = []
        authority_downgraded = False
        vocabulary = artifact.get("vocabulary") if isinstance(artifact.get("vocabulary"), dict) else artifact
        candidate_lists = []
        if isinstance(vocabulary, dict):
            for key in ["module_components", "macro_components", "chapter_modules", "components", "items"]:
                value = vocabulary.get(key)
                if isinstance(value, list):
                    candidate_lists.append((key, value))
        for key, values in candidate_lists:
            for index, item in enumerate(values[:50]):
                if not isinstance(item, dict):
                    continue
                write_policy = str(item.get("write_policy") or "")
                if write_policy and write_policy != "reference_only":
                    authority_downgraded = True
                    warnings.append(
                        self._issue(
                            "vocabulary_authority_downgraded",
                            "warning",
                            f"Vocabulary write_policy={write_policy} was downgraded to reference/no_formal_write.",
                            f"vocabulary.{key}[{index}].write_policy",
                        )
                    )
                if item.get("examples") or item.get("example") or item.get("long_example"):
                    warnings.append(
                        self._issue(
                            "vocabulary_examples_stripped",
                            "warning",
                            "Vocabulary examples were stripped; M7 stores reusable labels and summaries only.",
                            f"vocabulary.{key}[{index}]",
                        )
                    )
                label = self._first_str(item.get("label"), item.get("name"), item.get("component_id"), item.get("module_id")) or f"{key}_{index + 1}"
                description = self._first_str(item.get("description"), item.get("instruction"), item.get("summary")) or label
                item_type = "chapter_module" if key == "chapter_modules" else "macro_component" if key == "macro_components" else "module_component"
                records.append(
                    {
                        "item_type": item_type,
                        "label": self._short(label, 120),
                        "description": self._short(description, 500),
                        "safe_summary": self._short(description, 260),
                    }
                )
        return records, warnings, authority_downgraded

    def _macro_components(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        macro = package.get("macro_framework") if isinstance(package.get("macro_framework"), dict) else {}
        components = macro.get("components") if isinstance(macro, dict) else []
        return [item for item in components if isinstance(item, dict)]

    def _chapter_modules(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        vocabulary = package.get("component_vocabulary") if isinstance(package.get("component_vocabulary"), dict) else {}
        modules = vocabulary.get("chapter_modules") if isinstance(vocabulary, dict) else []
        return [item for item in modules if isinstance(item, dict)]

    def _module_components(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        vocabulary = package.get("component_vocabulary") if isinstance(package.get("component_vocabulary"), dict) else {}
        results: list[dict[str, Any]] = []
        if isinstance(vocabulary, dict):
            for key in ["module_components", "macro_components"]:
                values = vocabulary.get(key)
                if isinstance(values, list):
                    results.extend(item for item in values if isinstance(item, dict))
            for module in vocabulary.get("chapter_modules") or []:
                if not isinstance(module, dict):
                    continue
                allowed = module.get("allowed_components")
                if isinstance(allowed, list):
                    results.extend(item for item in allowed if isinstance(item, dict))
        return results

    def _component_label(self, item: dict[str, Any], fallback: str) -> str:
        return self._short(
            self._first_str(
                item.get("label"),
                item.get("name"),
                item.get("component_id"),
                item.get("module_id"),
            ) or fallback,
            120,
        )

    def _component_description(self, item: dict[str, Any]) -> str:
        return self._short(
            self._first_str(
                item.get("instruction"),
                item.get("description"),
                item.get("summary"),
                item.get("purpose"),
                item.get("write_policy"),
            ) or self._component_label(item, "component"),
            500,
        )

    def _pattern_type_for_family(self, family: str) -> str:
        return {
            "narrative_debt": "narrative_debt",
            "open_thread": "information_release",
            "closed_thread": "foreshadowing_payoff",
            "payoff": "foreshadowing_payoff",
            "apparent_contradiction_template": "apparent_contradiction",
        }.get(family, family)

    def _relation_type_for_family(self, family: str) -> str:
        return {
            "open_thread": "sets_up",
            "closed_thread": "closes",
            "payoff": "payoff_for",
        }.get(family, "suggests")

    def _label_for_candidate(self, candidate: dict[str, Any]) -> str:
        family = str(candidate.get("candidate_family") or "pattern")
        text = self._candidate_text(candidate)
        return self._short(text or family.replace("_", " ").title(), 120)

    def _candidate_text(self, candidate: dict[str, Any]) -> str:
        for key in [
            "safe_summary",
            "setup_summary_candidate",
            "closure_summary_candidate",
            "payoff_summary_candidate",
            "surface_contradiction_candidate",
            "archive_summary_candidate",
        ]:
            if candidate.get(key):
                return str(candidate[key])
        return ""

    def _candidate_fingerprint_ids(self, candidate: dict[str, Any] | None) -> list[str]:
        if not isinstance(candidate, dict):
            return []
        return [str(item) for item in candidate.get("input_fingerprint_ids") or [] if item]

    def _candidate_source_fingerprint_ids(self, candidate: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for source_ref in candidate.get("source_refs") or []:
            if isinstance(source_ref, dict):
                ids.extend(str(item) for item in source_ref.get("source_input_fingerprint_ids") or [] if item)
        return sorted(set(ids))

    def _set_rule_status(
        self,
        rule_id: str,
        status: str,
        request: FrameworkLibraryActionRequest | None,
    ) -> ModuleCompositionRule:
        request = request or FrameworkLibraryActionRequest()
        self._guard_safe_payload(request.safe_user_note)
        record = self._find_by_id(self.rules_file, "rule_id", rule_id, "FRAMEWORK_LIBRARY_RULE_NOT_FOUND")
        record["rule_status"] = status
        record["updated_at"] = now_iso()
        self._replace(self.rules_file, "rule_id", rule_id, record)
        return ModuleCompositionRule(**record)

    def _validate_item_visibility_patch(self, record: dict[str, Any], visibility: str) -> None:
        if visibility == "system_recommended_candidate":
            raise StorageError(
                "FRAMEWORK_LIBRARY_SYSTEM_RECOMMENDATION_PROMOTION_BLOCKED: "
                "direct item PATCH cannot create system recommendation candidates in M7 v1"
            )
        if visibility == "blocked":
            raise StorageError(
                "FRAMEWORK_LIBRARY_DIRECT_BLOCK_VISIBILITY_BLOCKED: "
                "direct item PATCH may not mark library items as blocked"
            )
        if visibility in {"private", "archived"}:
            return
        if visibility == "project_local" and self._item_allows_project_local(record):
            return
        raise StorageError(
            "FRAMEWORK_LIBRARY_ITEM_VISIBILITY_AUTHORITY_BLOCKED: "
            f"source_type={record.get('source_type') or 'unknown'} cannot set visibility={visibility}"
        )

    def _item_allows_project_local(self, record: dict[str, Any]) -> bool:
        if record.get("source_type") != "m4_confirmed_import":
            return False
        copyright_record = self._find_optional_by_id(
            self.copyright_file,
            "copyright_source_record_id",
            str(record.get("copyright_source_record_id") or ""),
        )
        if not copyright_record:
            return False
        if copyright_record.get("visibility_limit") != "project_local":
            return False
        if copyright_record.get("risk_level") in {"high", "blocked"}:
            return False
        maturity_record = self._find_optional_by_id(
            self.maturity_file,
            "maturity_record_id",
            str(record.get("maturity_record_id") or ""),
        )
        return bool(maturity_record and maturity_record.get("maturity_level") == "user_confirmed")

    def _validate_private_framework_refs(self, request: UserPrivateFrameworkCreateRequest) -> None:
        missing_parts: list[str] = []
        item_ids = {str(item.get("library_item_id") or "") for item in self._read_list(self.items_file)}
        pattern_ids = {str(item.get("pattern_id") or "") for item in self._read_list(self.patterns_file)}
        rule_ids = {str(item.get("rule_id") or "") for item in self._read_list(self.rules_file)}
        missing_item_count = len([item_id for item_id in request.item_ids if item_id not in item_ids])
        missing_pattern_count = len([pattern_id for pattern_id in request.pattern_ids if pattern_id not in pattern_ids])
        missing_rule_count = len([rule_id for rule_id in request.composition_rule_ids if rule_id not in rule_ids])
        if missing_item_count:
            missing_parts.append(f"item_ids missing={missing_item_count}")
        if missing_pattern_count:
            missing_parts.append(f"pattern_ids missing={missing_pattern_count}")
        if missing_rule_count:
            missing_parts.append(f"composition_rule_ids missing={missing_rule_count}")
        if missing_parts:
            raise StorageError(
                "FRAMEWORK_LIBRARY_PRIVATE_FRAMEWORK_MISSING_REFS: "
                + "; ".join(missing_parts)
            )

    def _read_all_m6_candidates(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for file_name in M6_CANDIDATE_FILES:
            records.extend(self._read_list(self.data_dir / file_name))
        return records

    def _ensure_storage_files(self) -> None:
        with self._ensure_lock:
            for path in [
                self.items_file,
                self.patterns_file,
                self.rules_file,
                self.maturity_file,
                self.copyright_file,
                self.private_frameworks_file,
                self.system_recommendations_file,
                self.collections_file,
                self.build_reports_file,
            ]:
                self.store.write_if_missing(path, [])
            self._ensure_default_framework_library()
            self._repair_library_text_fields()

    def _ensure_default_framework_library(self) -> None:
        if self._read_list(self.items_file):
            return
        previous_runtime_counts = getattr(self, "_runtime_id_counts", None)
        self._runtime_id_counts = {}
        try:
            self._seed_default_framework_library()
        finally:
            if previous_runtime_counts is None:
                try:
                    delattr(self, "_runtime_id_counts")
                except AttributeError:
                    pass
            else:
                self._runtime_id_counts = previous_runtime_counts

    def _seed_default_framework_library(self) -> None:
        artifact = self._load_default_framework_artifact()
        vocabulary = artifact.get("component_vocabulary") if isinstance(artifact.get("component_vocabulary"), dict) else {}
        macro_components = vocabulary.get("macro_components") if isinstance(vocabulary, dict) else []
        chapter_modules = vocabulary.get("chapter_modules") if isinstance(vocabulary, dict) else []
        if not isinstance(macro_components, list) or not isinstance(chapter_modules, list):
            return
        timestamp = now_iso()
        maturity_record = self._create_maturity_record(
            "system_default",
            DEFAULT_LIBRARY_SOURCE_ID,
            "validated",
            timestamp,
            safe_summary="Default full-book and chapter framework library for generator composition.",
        )
        copyright_record = self._create_copyright_record(
            "system_default",
            DEFAULT_LIBRARY_SOURCE_ID,
            fingerprint_ids=[],
            risk_level="low",
            visibility_limit="private",
            timestamp=timestamp,
            warnings=[],
            examples_stripped=True,
            authority_downgraded=False,
        )
        self._append(self.maturity_file, model_to_dict(maturity_record))
        self._append(self.copyright_file, model_to_dict(copyright_record))

        source_ref = FrameworkLibrarySourceRef(
            source_ref_id=self._next_id(self.collections_file, "source_ref_id", "framework_lib_source_ref"),
            source_type="system_default",
            source_id=DEFAULT_LIBRARY_SOURCE_ID,
            relationship="seeds",
            field_path="Story Analyzer/data/handoff_package/recommended_framework.json",
            safe_summary="Built-in reusable framework vocabulary seed.",
        )

        items: list[FrameworkModuleLibraryItem] = []
        macro_item_ids: list[str] = []
        chapter_item_ids: list[str] = []
        module_component_ids_by_module: dict[str, list[str]] = {}

        for component in macro_components:
            if not isinstance(component, dict):
                continue
            item = self._create_item(
                item_type="macro_component",
                source_type="system_default",
                label=self._component_label(component, "macro_component"),
                description=self._component_description(component),
                safe_summary=self._component_description(component),
                source_refs=[source_ref],
                visibility="private",
                constraint_strength="suggestion",
                maturity_record_id=maturity_record.maturity_record_id,
                copyright_source_record_id=copyright_record.copyright_source_record_id,
                timestamp=timestamp,
            )
            items.append(item)
            macro_item_ids.append(item.library_item_id)

        for module in chapter_modules:
            if not isinstance(module, dict):
                continue
            module_id = str(module.get("module_id") or module.get("id") or "")
            module_item = self._create_item(
                item_type="chapter_module",
                source_type="system_default",
                label=self._component_label(module, "chapter_module"),
                description=self._component_description(module),
                safe_summary=self._component_description(module),
                source_refs=[source_ref],
                visibility="private",
                constraint_strength="suggestion",
                maturity_record_id=maturity_record.maturity_record_id,
                copyright_source_record_id=copyright_record.copyright_source_record_id,
                timestamp=timestamp,
            )
            items.append(module_item)
            chapter_item_ids.append(module_item.library_item_id)
            module_component_ids_by_module[module_id] = []
            allowed_components = module.get("allowed_components")
            if not isinstance(allowed_components, list):
                continue
            for component in allowed_components:
                if not isinstance(component, dict):
                    continue
                component_item = self._create_item(
                    item_type="module_component",
                    source_type="system_default",
                    label=self._component_label(component, "module_component"),
                    description=self._component_description(component),
                    safe_summary=self._component_description(component),
                    source_refs=[source_ref],
                    visibility="private",
                    constraint_strength="suggestion",
                    maturity_record_id=maturity_record.maturity_record_id,
                    copyright_source_record_id=copyright_record.copyright_source_record_id,
                    timestamp=timestamp,
                )
                items.append(component_item)
                chapter_item_ids.append(component_item.library_item_id)
                module_component_ids_by_module[module_id].append(component_item.library_item_id)

        patterns = self._default_patterns(chapter_modules, source_ref, maturity_record, copyright_record, timestamp)
        rules = self._default_composition_rules(
            chapter_modules,
            module_component_ids_by_module,
            source_ref,
            timestamp,
        )
        private_frameworks = self._default_private_frameworks(
            macro_item_ids,
            chapter_item_ids,
            [pattern.pattern_id for pattern in patterns],
            [rule.rule_id for rule in rules],
            timestamp,
        )
        system_recommendation = SystemRecommendedFramework(
            system_recommendation_id=self._next_id(
                self.system_recommendations_file,
                "system_recommendation_id",
                "system_framework_recommendation",
            ),
            status="candidate",
            item_ids=macro_item_ids + chapter_item_ids,
            pattern_ids=[pattern.pattern_id for pattern in patterns],
            requires_user_confirmation=True,
            safe_summary="Default reusable full-book and chapter framework library candidate.",
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )

        for item in items:
            self._append(self.items_file, model_to_dict(item))
        for pattern in patterns:
            self._append(self.patterns_file, model_to_dict(pattern))
        for rule in rules:
            self._append(self.rules_file, model_to_dict(rule))
        for private_framework in private_frameworks:
            self._append(self.private_frameworks_file, model_to_dict(private_framework))
        self._append(self.system_recommendations_file, model_to_dict(system_recommendation))
        for collection in self._default_collections(private_frameworks, timestamp):
            self._append(self.collections_file, model_to_dict(collection))
        report = self._create_build_report(
            "system_default",
            DEFAULT_LIBRARY_SOURCE_ID,
            timestamp,
            item_ids=[item.library_item_id for item in items],
            pattern_ids=[pattern.pattern_id for pattern in patterns],
            rule_ids=[rule.rule_id for rule in rules],
            maturity_ids=[maturity_record.maturity_record_id],
            copyright_ids=[copyright_record.copyright_source_record_id],
            private_framework_ids=[private_framework.private_framework_id for private_framework in private_frameworks],
            warnings=[],
            blocking=[],
            append=False,
        )
        self._append(self.build_reports_file, model_to_dict(report))

    def _load_default_framework_artifact(self) -> dict[str, Any]:
        path = (
            settings.app_root
            / "Story Analyzer"
            / "data"
            / "handoff_package"
            / "recommended_framework.json"
        )
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "component_vocabulary": {
                "macro_components": [
                    {"label": "Opening", "instruction": "Establish the story world, protagonist, tone, and first problem."},
                    {"label": "Inciting Event", "instruction": "Break the initial balance and start the main story movement."},
                    {"label": "Development", "instruction": "Escalate pursuit, conflict, and world complexity."},
                    {"label": "Crisis", "instruction": "Force a costly choice that changes the route."},
                    {"label": "Climax", "instruction": "Bring the central conflict to peak intensity."},
                    {"label": "Resolution", "instruction": "Release or transform the central tension."},
                ],
                "chapter_modules": [
                    {
                        "module_id": "chapter_function",
                        "label": "Chapter Function",
                        "instruction": "Define what the chapter must structurally accomplish.",
                        "allowed_components": [
                            {"label": "Setup", "instruction": "Prepare world, relationship, or conflict context."},
                            {"label": "Turn", "instruction": "Change the current situation through action or revelation."},
                            {"label": "Payoff", "instruction": "Resolve or partially resolve a prior setup."},
                        ],
                    },
                    {
                        "module_id": "reader_emotion",
                        "label": "Reader Emotion",
                        "instruction": "Set the chapter's intended reader experience.",
                        "allowed_components": [
                            {"label": "Curiosity", "instruction": "Open a question the reader wants answered."},
                            {"label": "Tension", "instruction": "Create pressure around risk or uncertainty."},
                            {"label": "Relief", "instruction": "Release pressure after a meaningful beat."},
                        ],
                    },
                ],
            }
        }

    def _repair_library_text_fields(self) -> None:
        for path in [
            self.items_file,
            self.patterns_file,
            self.rules_file,
            self.maturity_file,
            self.copyright_file,
            self.private_frameworks_file,
            self.system_recommendations_file,
            self.collections_file,
            self.build_reports_file,
        ]:
            if not path.exists():
                continue
            try:
                data = self.store.read_any(path)
            except StorageError:
                continue
            repaired, changed = self._repair_text_node(data)
            if changed:
                self.store.write(path, repaired)

    def _repair_text_node(self, value: Any) -> tuple[Any, bool]:
        if isinstance(value, dict):
            changed = False
            repaired: dict[str, Any] = {}
            for key, child in value.items():
                if key in REPAIRABLE_TEXT_FIELDS and isinstance(child, str):
                    fixed = self._repair_mojibake_text(child)
                    repaired[key] = fixed
                    changed = changed or fixed != child
                    continue
                fixed_child, child_changed = self._repair_text_node(child)
                repaired[key] = fixed_child
                changed = changed or child_changed
            return repaired, changed
        if isinstance(value, list):
            changed = False
            repaired_list = []
            for child in value:
                fixed_child, child_changed = self._repair_text_node(child)
                repaired_list.append(fixed_child)
                changed = changed or child_changed
            return repaired_list, changed
        return value, False

    def _repair_mojibake_text(self, text: str) -> str:
        if not text:
            return text
        try:
            candidate = text.encode("latin1").decode("utf-8")
        except UnicodeError:
            return text
        if self._cjk_count(candidate) > self._cjk_count(text):
            return candidate
        return text

    def _cjk_count(self, text: str) -> int:
        return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")

    def _default_patterns(
        self,
        chapter_modules: list[Any],
        source_ref: FrameworkLibrarySourceRef,
        maturity_record: FrameworkMaturityRecord,
        copyright_record: CopyrightSourceRecord,
        timestamp: str,
    ) -> list[FrameworkPatternRecord]:
        patterns: list[FrameworkPatternRecord] = []
        for module in chapter_modules:
            if not isinstance(module, dict):
                continue
            recommended_defaults = module.get("recommended_defaults")
            if not isinstance(recommended_defaults, list) or not recommended_defaults:
                continue
            module_id = str(module.get("module_id") or "chapter_module")
            label = self._component_label(module, module_id)
            summary = f"{label}: " + " / ".join(str(item) for item in recommended_defaults[:8] if item)
            patterns.append(
                FrameworkPatternRecord(
                    pattern_id=self._next_id(self.patterns_file, "pattern_id", "framework_pattern"),
                    pattern_type=module_id,
                    source_type="system_default",
                    label=label,
                    safe_summary=self._short(summary, 260),
                    source_refs=[source_ref],
                    visibility="private",
                    maturity_record_id=maturity_record.maturity_record_id,
                    copyright_source_record_id=copyright_record.copyright_source_record_id,
                    requires_user_confirmation=True,
                    warnings=[],
                    created_at=timestamp,
                    updated_at=timestamp,
                    version_id=SCHEMA_VERSION,
                )
            )
        return patterns

    def _default_composition_rules(
        self,
        chapter_modules: list[Any],
        module_component_ids_by_module: dict[str, list[str]],
        source_ref: FrameworkLibrarySourceRef,
        timestamp: str,
    ) -> list[ModuleCompositionRule]:
        rules: list[ModuleCompositionRule] = []
        for module in chapter_modules:
            if not isinstance(module, dict):
                continue
            module_id = str(module.get("module_id") or "")
            target_ids = module_component_ids_by_module.get(module_id, [])[:8]
            if not target_ids:
                continue
            label = self._component_label(module, module_id or "chapter_module")
            rules.append(
                ModuleCompositionRule(
                    rule_id=self._next_id(self.rules_file, "rule_id", "framework_composition_rule"),
                    relation_type=f"{module_id or 'chapter_module'}_allows_components",
                    source_type="system_default",
                    source_pattern_ids=[],
                    source_library_item_ids=[],
                    target_pattern_ids=[],
                    target_library_item_ids=target_ids,
                    rule_status="reviewed",
                    requires_user_confirmation=True,
                    source_refs=[source_ref],
                    safe_summary=self._short(f"{label} can be composed with its default module components.", 260),
                    warnings=[],
                    created_at=timestamp,
                    updated_at=timestamp,
                    version_id=SCHEMA_VERSION,
                )
            )
        return rules

    def _default_private_frameworks(
        self,
        macro_item_ids: list[str],
        chapter_item_ids: list[str],
        pattern_ids: list[str],
        rule_ids: list[str],
        timestamp: str,
    ) -> list[UserPrivateFramework]:
        frameworks: list[UserPrivateFramework] = []
        if macro_item_ids:
            frameworks.append(
                UserPrivateFramework(
                    private_framework_id=self._next_id(self.private_frameworks_file, "private_framework_id", "private_framework"),
                    title="Default full-book framework library",
                    item_ids=macro_item_ids,
                    pattern_ids=[],
                    composition_rule_ids=[],
                    visibility="private",
                    requires_user_confirmation=True,
                    safe_summary="Reusable full-book macro framework components.",
                    created_at=timestamp,
                    updated_at=timestamp,
                    version_id=SCHEMA_VERSION,
                )
            )
        if chapter_item_ids:
            frameworks.append(
                UserPrivateFramework(
                    private_framework_id=self._next_id(self.private_frameworks_file, "private_framework_id", "private_framework"),
                    title="Default chapter framework library",
                    item_ids=chapter_item_ids,
                    pattern_ids=pattern_ids,
                    composition_rule_ids=rule_ids,
                    visibility="private",
                    requires_user_confirmation=True,
                    safe_summary="Reusable chapter modules, module components, and composition rules.",
                    created_at=timestamp,
                    updated_at=timestamp,
                    version_id=SCHEMA_VERSION,
                )
            )
        return frameworks

    def _default_collections(
        self,
        private_frameworks: list[UserPrivateFramework],
        timestamp: str,
    ) -> list[FrameworkLibraryCollection]:
        return [
            FrameworkLibraryCollection(
                collection_id=self._next_id(self.collections_file, "collection_id", "framework_library_collection"),
                title=private_framework.title,
                item_ids=private_framework.item_ids,
                pattern_ids=private_framework.pattern_ids,
                composition_rule_ids=private_framework.composition_rule_ids,
                safe_summary=private_framework.safe_summary,
                created_at=timestamp,
                updated_at=timestamp,
                version_id=SCHEMA_VERSION,
            )
            for private_framework in private_frameworks
        ]

    def _guard_safe_payload(self, value: Any) -> None:
        violations: list[str] = []

        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    key_text = str(key)
                    child_path = f"{path}.{key_text}" if path else key_text
                    if UNSAFE_KEY_RE.search(key_text):
                        violations.append(child_path)
                    walk(child, child_path)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]")
            elif isinstance(node, str):
                if UNSAFE_VALUE_RE.search(node) or len(node) > 12000:
                    violations.append(path)

        walk(value, "$")
        if violations:
            raise StorageError(f"FRAMEWORK_LIBRARY_UNSAFE_PAYLOAD_BLOCKED: {violations[0]}")

    def _issue(
        self,
        code: str,
        severity: str,
        safe_detail: str,
        field_path: str | None = None,
    ) -> FrameworkLibraryIssue:
        return FrameworkLibraryIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            field_path=field_path,
            safe_detail=self._short(safe_detail, 260),
        )

    def _first_str(self, *values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _short(self, value: Any, limit: int) -> str:
        text = self._repair_mojibake_text(str(value or ""))
        text = text.replace("\r", " ").replace("\n", " ").strip()
        text = " ".join(text.split())
        return text[:limit]

    def _find_by_id(self, path: Path, key: str, value: str, error_code: str) -> dict[str, Any]:
        for item in self._read_list(path):
            if item.get(key) == value:
                return item
        raise StorageError(f"{error_code}: {value}")

    def _find_optional_by_id(self, path: Path, key: str, value: str) -> dict[str, Any] | None:
        if not value:
            return None
        for item in self._read_list(path):
            if item.get(key) == value:
                return item
        return None

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        items.append(item)
        self.store.write(path, items)

    def _replace(self, path: Path, key: str, value: str, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        for index, existing in enumerate(items):
            if existing.get(key) == value:
                items[index] = item
                self.store.write(path, items)
                return
        raise StorageError(f"FRAMEWORK_LIBRARY_RECORD_NOT_FOUND: {value}")

    def _next_id(self, path: Path, key: str, prefix: str) -> str:
        max_index = 0
        for item in self._read_list(path):
            value = str(item.get(key) or "")
            if value.startswith(f"{prefix}_"):
                suffix = value.removeprefix(f"{prefix}_")
                if suffix.isdigit():
                    max_index = max(max_index, int(suffix))
        runtime_counts = getattr(self, "_runtime_id_counts", None)
        if isinstance(runtime_counts, dict):
            runtime_key = f"{path.name}:{key}:{prefix}"
            offset = int(runtime_counts.get(runtime_key, 0))
            runtime_counts[runtime_key] = offset + 1
            max_index += offset
        return f"{prefix}_{max_index + 1:03d}"

    def _start_id_session(self) -> None:
        self._runtime_id_counts = {}
