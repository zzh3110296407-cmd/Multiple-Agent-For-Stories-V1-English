import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.analyze_stories_adapter import (
    AdapterCandidateFamily,
    AdapterCandidateStatus,
    AnalyzeStoriesAdapterCandidateAction,
    AnalyzeStoriesAdapterCandidateActionRequest,
    AnalyzeStoriesAdapterCandidateActionResult,
    AnalyzeStoriesAdapterCandidateDetail,
    AnalyzeStoriesAdapterCandidateListResponse,
    AnalyzeStoriesAdapterDerivationListResponse,
    AnalyzeStoriesAdapterDerivationReport,
    AnalyzeStoriesAdapterDerivationRequest,
    AnalyzeStoriesAdapterDerivationResult,
    AnalyzeStoriesAdapterIssue,
    AnalyzeStoriesAdapterSourceRef,
    AnalyzeStoriesApparentContradictionTemplateCandidate,
    AnalyzeStoriesChapterArchiveCandidate,
    AnalyzeStoriesClosedThreadCandidate,
    AnalyzeStoriesNarrativeDebtCandidate,
    AnalyzeStoriesOpenThreadCandidate,
    AnalyzeStoriesPayoffCandidate,
)
from app.backend.models.analysis_report_viewer import AnalysisReportSectionView
from app.backend.models.full_book_bundle_validation import (
    BundleChapterEntry,
    FullBookBundleDetail,
)
from app.backend.services.analysis_report_viewer_service import AnalysisReportViewerService
from app.backend.services.full_book_bundle_validation_service import FullBookBundleValidationService
from app.backend.services.imported_framework_workbench_service import ImportedFrameworkWorkbenchService
from app.backend.storage.json_store import JsonStore, StorageError


SCHEMA_VERSION = "phase5_m6_analyze_stories_adapter_v1"
LOCAL_PROJECT_ID = "local_project"

DERIVATION_REPORTS_FILE = "analyze_stories_adapter_derivation_reports.json"
CHAPTER_ARCHIVE_CANDIDATES_FILE = "analyze_stories_chapter_archive_candidates.json"
NARRATIVE_DEBT_CANDIDATES_FILE = "analyze_stories_narrative_debt_candidates.json"
OPEN_THREAD_CANDIDATES_FILE = "analyze_stories_open_thread_candidates.json"
CLOSED_THREAD_CANDIDATES_FILE = "analyze_stories_closed_thread_candidates.json"
PAYOFF_CANDIDATES_FILE = "analyze_stories_payoff_candidates.json"
APPARENT_CONTRADICTION_TEMPLATE_CANDIDATES_FILE = "analyze_stories_apparent_contradiction_template_candidates.json"
ACTIONS_FILE = "analyze_stories_adapter_candidate_actions.json"

FAMILY_TO_FILE = {
    "chapter_archive": CHAPTER_ARCHIVE_CANDIDATES_FILE,
    "narrative_debt": NARRATIVE_DEBT_CANDIDATES_FILE,
    "open_thread": OPEN_THREAD_CANDIDATES_FILE,
    "closed_thread": CLOSED_THREAD_CANDIDATES_FILE,
    "payoff": PAYOFF_CANDIDATES_FILE,
    "apparent_contradiction_template": APPARENT_CONTRADICTION_TEMPLATE_CANDIDATES_FILE,
}

FAMILY_TO_MODEL = {
    "chapter_archive": AnalyzeStoriesChapterArchiveCandidate,
    "narrative_debt": AnalyzeStoriesNarrativeDebtCandidate,
    "open_thread": AnalyzeStoriesOpenThreadCandidate,
    "closed_thread": AnalyzeStoriesClosedThreadCandidate,
    "payoff": AnalyzeStoriesPayoffCandidate,
    "apparent_contradiction_template": AnalyzeStoriesApparentContradictionTemplateCandidate,
}

UNSAFE_RE = re.compile(
    r"(RAW_PROMPT|RAW_RESPONSE|HIDDEN_REASONING|INTERNAL_REASONING|CHAIN_OF_THOUGHT|"
    r"chain-of-thought|raw prompt|raw response|hidden reasoning|internal reasoning|"
    r"\bsk-[A-Za-z0-9_\-]{8,}|lsv2_|Bearer\s+[A-Za-z0-9_\-]{8,})",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class AnalyzeStoriesAdapterService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        bundle_service: FullBookBundleValidationService | None = None,
        analysis_report_viewer_service: AnalysisReportViewerService | None = None,
        imported_framework_workbench_service: ImportedFrameworkWorkbenchService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.bundle_service = bundle_service or FullBookBundleValidationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.analysis_report_viewer_service = (
            analysis_report_viewer_service
            or AnalysisReportViewerService(store=self.store, data_dir=self.data_dir)
        )
        self.imported_framework_workbench_service = imported_framework_workbench_service
        self.derivation_reports_file = self.data_dir / DERIVATION_REPORTS_FILE
        self.actions_file = self.data_dir / ACTIONS_FILE
        self.candidate_files = {
            family: self.data_dir / file_name
            for family, file_name in FAMILY_TO_FILE.items()
        }

    def derive_from_bundle(
        self,
        bundle_manifest_id: str,
        request: AnalyzeStoriesAdapterDerivationRequest | None = None,
    ) -> AnalyzeStoriesAdapterDerivationResult:
        request = request or AnalyzeStoriesAdapterDerivationRequest()
        self._guard_safe_text(request.safe_user_note)
        detail = self.bundle_service.get_bundle(bundle_manifest_id)
        timestamp = now_iso()
        known_gaps = self._known_package_gaps(detail)
        derivation_report_id = self._next_id(
            self.derivation_reports_file,
            "derivation_report_id",
            "as_adapter_derivation",
        )
        family_filter = set(request.include_candidate_families or FAMILY_TO_FILE.keys())
        base_report_kwargs = self._base_report_kwargs(
            detail,
            derivation_report_id,
            known_gaps,
            timestamp,
        )

        blocking = self._bundle_blocking_issues(detail)
        if blocking:
            report = AnalyzeStoriesAdapterDerivationReport(
                **base_report_kwargs,
                derivation_status="blocked",
                reliability_level="blocked",
                blocking_issues=blocking,
                safe_summary=self._short("Adapter derivation blocked because the M5 bundle is not M6-adapter-ready.", 260),
            )
            self._append(self.derivation_reports_file, model_to_dict(report))
            return AnalyzeStoriesAdapterDerivationResult(success=False, derivation_report=report)

        viewer_details, viewer_warnings = self._collect_viewer_details(detail, request)
        if not viewer_details:
            report = AnalyzeStoriesAdapterDerivationReport(
                **base_report_kwargs,
                derivation_status="blocked",
                reliability_level="blocked",
                warnings=viewer_warnings,
                blocking_issues=[
                    self._issue(
                        "viewer_context_unavailable",
                        "blocking",
                        "chapter_archive",
                        "viewer_state_ids",
                        bundle_manifest_id,
                        None,
                        "No M3 viewer states were available for adapter derivation.",
                    )
                ],
                safe_summary="Adapter derivation blocked because no safe M3 viewer states were available.",
            )
            self._append(self.derivation_reports_file, model_to_dict(report))
            return AnalyzeStoriesAdapterDerivationResult(success=False, derivation_report=report)

        chapter_by_viewer = self._chapter_index_by_viewer(detail, viewer_details, request)
        entries_by_chapter = self._entries_by_chapter(detail)
        all_section_view_ids: list[str] = []
        unhandled: list[AnalyzeStoriesAdapterSourceRef] = []
        unsupported_counts: Counter[str] = Counter()
        warnings = list(viewer_warnings)
        candidates_by_family: dict[str, list[Any]] = {family: [] for family in FAMILY_TO_FILE}
        self._runtime_candidate_counts = {family: 0 for family in FAMILY_TO_FILE}

        for viewer_detail in viewer_details:
            viewer = viewer_detail.viewer_state
            chapter_index = chapter_by_viewer.get(viewer.viewer_state_id)
            sections = list(viewer_detail.section_views)
            all_section_view_ids.extend(section.section_view_id for section in sections)
            section_by_type: dict[str, list[AnalysisReportSectionView]] = {}
            for section in sections:
                section_by_type.setdefault(section.section_type, []).append(section)

            if "chapter_archive" in family_filter:
                overview = self._first_section(section_by_type, "overview")
                if overview is None:
                    overview = self._first_section_by_marker(sections, ["chapter_summary"])
                if overview is not None:
                    candidate = self._build_chapter_archive_candidate(
                        derivation_report_id,
                        detail,
                        viewer.viewer_state_id,
                        chapter_index,
                        overview,
                        section_by_type,
                        entries_by_chapter.get(chapter_index),
                        known_gaps,
                        timestamp,
                    )
                    if candidate is not None:
                        candidates_by_family["chapter_archive"].append(candidate)

            for section in sections:
                family = self._explicit_family_for_section(section)
                if family is None:
                    if section.section_type not in {"overview", "macro_structure", "theme", "emotion_curve"}:
                        unsupported_counts[section.section_type or "other"] += 1
                        unhandled.append(self._section_ref(viewer.viewer_state_id, section, chapter_index, "unhandled"))
                    continue
                if family not in family_filter:
                    unsupported_counts[section.section_type or family] += 1
                    unhandled.append(self._section_ref(viewer.viewer_state_id, section, chapter_index, "filtered_out"))
                    continue
                built = self._build_explicit_candidate(
                    family,
                    derivation_report_id,
                    detail,
                    viewer.viewer_state_id,
                    chapter_index,
                    section,
                    known_gaps,
                    timestamp,
                )
                if built is not None:
                    candidates_by_family[family].append(built)

        for family, candidates in candidates_by_family.items():
            for candidate in candidates:
                self._append(self.candidate_files[family], model_to_dict(candidate))

        candidate_ids_by_family = {
            family: [candidate.candidate_id for candidate in candidates]
            for family, candidates in candidates_by_family.items()
        }
        candidate_count_by_family = {
            family: len(candidates)
            for family, candidates in candidates_by_family.items()
        }
        candidate_total = sum(candidate_count_by_family.values())
        status = (
            "no_candidates"
            if candidate_total == 0
            else "completed_with_warnings"
            if warnings or unsupported_counts
            else "completed"
        )
        report = AnalyzeStoriesAdapterDerivationReport(
            **base_report_kwargs,
            derivation_status=status,
            reliability_level=self._adapter_reliability(detail),
            viewer_state_ids=[item.viewer_state.viewer_state_id for item in viewer_details],
            section_view_ids=all_section_view_ids,
            imported_framework_decision_ids=self._imported_framework_decision_ids(),
            candidate_ids_by_family=candidate_ids_by_family,
            candidate_count_by_family=candidate_count_by_family,
            unsupported_section_count_by_type=dict(unsupported_counts),
            unhandled_sections=unhandled,
            warnings=warnings,
            blocking_issues=[],
            safe_summary=self._short(
                f"Derived {candidate_total} Analyze Stories adapter candidates from M3/M5 safe evidence only.",
                260,
            ),
        )
        self._append(self.derivation_reports_file, model_to_dict(report))
        return AnalyzeStoriesAdapterDerivationResult(
            success=True,
            derivation_report=report,
            chapter_archive_candidates=candidates_by_family["chapter_archive"],
            narrative_debt_candidates=candidates_by_family["narrative_debt"],
            open_thread_candidates=candidates_by_family["open_thread"],
            closed_thread_candidates=candidates_by_family["closed_thread"],
            payoff_candidates=candidates_by_family["payoff"],
            apparent_contradiction_template_candidates=candidates_by_family["apparent_contradiction_template"],
        )

    def list_derivation_reports(self) -> AnalyzeStoriesAdapterDerivationListResponse:
        reports = [
            AnalyzeStoriesAdapterDerivationReport(**item)
            for item in self._read_list(self.derivation_reports_file)
        ]
        reports.sort(key=lambda item: item.updated_at, reverse=True)
        return AnalyzeStoriesAdapterDerivationListResponse(derivation_reports=reports)

    def get_derivation_report(self, derivation_report_id: str) -> AnalyzeStoriesAdapterDerivationReport:
        for item in self._read_list(self.derivation_reports_file):
            if item.get("derivation_report_id") == derivation_report_id:
                return AnalyzeStoriesAdapterDerivationReport(**item)
        raise StorageError(f"ANALYZE_STORIES_ADAPTER_DERIVATION_NOT_FOUND: {derivation_report_id}")

    def list_candidates(
        self,
        *,
        family: str | None = None,
        status: str | None = None,
        bundle_manifest_id: str | None = None,
        derivation_report_id: str | None = None,
    ) -> AnalyzeStoriesAdapterCandidateListResponse:
        if family and family not in FAMILY_TO_FILE:
            raise StorageError(f"ANALYZE_STORIES_ADAPTER_INVALID_FAMILY_FILTER: {family}")
        if status and status not in {"candidate", "reviewed", "deferred", "rejected", "blocked"}:
            raise StorageError(f"ANALYZE_STORIES_ADAPTER_INVALID_STATUS_FILTER: {status}")
        records: list[dict[str, Any]] = []
        families = [family] if family else list(FAMILY_TO_FILE)
        for item_family in families:
            for record in self._read_list(self.candidate_files[item_family]):
                if status and record.get("candidate_status") != status:
                    continue
                if bundle_manifest_id and record.get("bundle_manifest_id") != bundle_manifest_id:
                    continue
                if derivation_report_id and record.get("derivation_report_id") != derivation_report_id:
                    continue
                records.append(record)
        records.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return AnalyzeStoriesAdapterCandidateListResponse(candidates=records)

    def get_candidate(self, candidate_id: str) -> AnalyzeStoriesAdapterCandidateDetail:
        family, record = self._find_candidate_record(candidate_id)
        return AnalyzeStoriesAdapterCandidateDetail(candidate=record)

    def mark_candidate_reviewed(
        self,
        candidate_id: str,
        request: AnalyzeStoriesAdapterCandidateActionRequest | None = None,
    ) -> AnalyzeStoriesAdapterCandidateActionResult:
        return self._transition(candidate_id, "mark_reviewed", "reviewed", request)

    def defer_candidate(
        self,
        candidate_id: str,
        request: AnalyzeStoriesAdapterCandidateActionRequest | None = None,
    ) -> AnalyzeStoriesAdapterCandidateActionResult:
        return self._transition(candidate_id, "defer", "deferred", request)

    def reject_candidate(
        self,
        candidate_id: str,
        request: AnalyzeStoriesAdapterCandidateActionRequest | None = None,
    ) -> AnalyzeStoriesAdapterCandidateActionResult:
        return self._transition(candidate_id, "reject", "rejected", request)

    def _transition(
        self,
        candidate_id: str,
        action_type: str,
        after_status: str,
        request: AnalyzeStoriesAdapterCandidateActionRequest | None,
    ) -> AnalyzeStoriesAdapterCandidateActionResult:
        request = request or AnalyzeStoriesAdapterCandidateActionRequest()
        self._guard_safe_text(request.safe_user_note)
        family, record = self._find_candidate_record(candidate_id)
        before_status = record.get("candidate_status", "candidate")
        if before_status == "blocked":
            raise StorageError(f"ANALYZE_STORIES_ADAPTER_CANDIDATE_BLOCKED: {candidate_id}")
        allowed = {
            "mark_reviewed": {"candidate"},
            "defer": {"candidate", "reviewed"},
            "reject": {"candidate", "reviewed", "deferred"},
        }
        if before_status not in allowed[action_type]:
            raise StorageError(
                f"ANALYZE_STORIES_ADAPTER_INVALID_STATUS_TRANSITION: {before_status}->{after_status}"
            )
        timestamp = now_iso()
        record["candidate_status"] = after_status
        record["updated_at"] = timestamp
        self._replace_record(self.candidate_files[family], "candidate_id", candidate_id, record)
        action = AnalyzeStoriesAdapterCandidateAction(
            action_id=self._next_id(self.actions_file, "action_id", "as_adapter_action"),
            candidate_id=candidate_id,
            candidate_family=family,  # type: ignore[arg-type]
            action_type=action_type,  # type: ignore[arg-type]
            before_status=before_status,  # type: ignore[arg-type]
            after_status=after_status,  # type: ignore[arg-type]
            safe_user_note=self._short(request.safe_user_note, 260),
            created_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._append(self.actions_file, model_to_dict(action))
        return AnalyzeStoriesAdapterCandidateActionResult(success=True, candidate=record, action=action)

    def _base_report_kwargs(
        self,
        detail: FullBookBundleDetail,
        derivation_report_id: str,
        known_gaps: list[str],
        timestamp: str,
    ) -> dict[str, Any]:
        manifest = detail.manifest
        validation_report = detail.validation_report
        return {
            "derivation_report_id": derivation_report_id,
            "project_id": LOCAL_PROJECT_ID,
            "bundle_manifest_id": manifest.bundle_manifest_id,
            "bundle_validation_report_id": validation_report.validation_report_id if validation_report else None,
            "import_id": manifest.import_id,
            "artifact_id": manifest.artifact_id,
            "source": "analyze_stories",
            "can_be_used_as_reference": bool(manifest.can_be_used_as_reference),
            "can_proceed_to_m6_adapter": bool(manifest.can_proceed_to_m6_adapter),
            "known_package_gaps_carried": known_gaps,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version_id": SCHEMA_VERSION,
        }

    def _bundle_blocking_issues(self, detail: FullBookBundleDetail) -> list[AnalyzeStoriesAdapterIssue]:
        manifest = detail.manifest
        report = detail.validation_report
        issues: list[AnalyzeStoriesAdapterIssue] = []
        if report is None:
            issues.append(self._issue("m5_validation_report_missing", "blocking", None, "validation_report_id", manifest.bundle_manifest_id, None, "M5 validation report is missing."))
        if not manifest.can_be_used_as_reference:
            issues.append(self._issue("bundle_not_reference_ready", "blocking", None, "can_be_used_as_reference", manifest.bundle_manifest_id, None, "M5 bundle cannot be used as reference."))
        if not manifest.can_proceed_to_m6_adapter:
            issues.append(self._issue("bundle_not_m6_adapter_ready", "blocking", None, "can_proceed_to_m6_adapter", manifest.bundle_manifest_id, None, "M5 bundle is not ready for M6 adapter candidate derivation."))
        if manifest.reliability_level in {"provisional", "blocked"}:
            issues.append(self._issue("bundle_reliability_not_allowed_for_m6", "blocking", None, "reliability_level", manifest.bundle_manifest_id, None, f"reliability_level={manifest.reliability_level}"))
        return issues

    def _collect_viewer_details(
        self,
        detail: FullBookBundleDetail,
        request: AnalyzeStoriesAdapterDerivationRequest,
    ) -> tuple[list[Any], list[AnalyzeStoriesAdapterIssue]]:
        viewer_ids = list(request.viewer_state_ids)
        warnings: list[AnalyzeStoriesAdapterIssue] = []
        if not viewer_ids and detail.consistency_check:
            for ref_id in detail.consistency_check.linked_story_analysis_report_ref_ids:
                try:
                    viewer_detail = self.analysis_report_viewer_service.get_viewer_state_for_report(ref_id)
                    viewer_ids.append(viewer_detail.viewer_state.viewer_state_id)
                except StorageError:
                    warnings.append(self._issue("linked_viewer_missing", "warning", None, "linked_story_analysis_report_ref_ids", ref_id, None, "Linked story report viewer was not available."))
        if not viewer_ids:
            try:
                for viewer in self.analysis_report_viewer_service.list_viewer_states().viewer_states:
                    if viewer.import_id == detail.manifest.import_id:
                        viewer_ids.append(viewer.viewer_state_id)
            except StorageError:
                pass
        details = []
        seen: set[str] = set()
        for viewer_id in viewer_ids:
            if viewer_id in seen:
                continue
            seen.add(viewer_id)
            try:
                viewer_detail = self.analysis_report_viewer_service.get_viewer_state(viewer_id)
            except StorageError:
                warnings.append(self._issue("viewer_state_missing", "warning", None, "viewer_state_ids", viewer_id, None, "Requested viewer state was not found."))
                continue
            if viewer_detail.viewer_state.viewer_status == "blocked":
                warnings.append(self._issue("viewer_state_blocked", "warning", None, "viewer_status", viewer_id, None, "Blocked viewer state was skipped."))
                continue
            details.append(viewer_detail)
        return details, warnings

    def _chapter_index_by_viewer(
        self,
        detail: FullBookBundleDetail,
        viewer_details: list[Any],
        request: AnalyzeStoriesAdapterDerivationRequest,
    ) -> dict[str, int | None]:
        entries = [
            entry for entry in (detail.chapter_inventory.entries if detail.chapter_inventory else [])
            if entry.chapter_index is not None
        ]
        entries.sort(key=lambda item: item.chapter_order)
        report_ref_ids = detail.consistency_check.linked_story_analysis_report_ref_ids if detail.consistency_check else []
        mapping: dict[str, int | None] = {}
        if report_ref_ids and len(report_ref_ids) == len(entries):
            ref_to_index = {
                ref_id: entries[index].chapter_index
                for index, ref_id in enumerate(report_ref_ids)
            }
            for viewer_detail in viewer_details:
                mapping[viewer_detail.viewer_state.viewer_state_id] = ref_to_index.get(
                    viewer_detail.viewer_state.story_analysis_report_ref_id
                )
        else:
            for index, viewer_detail in enumerate(viewer_details):
                mapping[viewer_detail.viewer_state.viewer_state_id] = (
                    entries[index].chapter_index if index < len(entries) else None
                )
        return mapping

    def _entries_by_chapter(self, detail: FullBookBundleDetail) -> dict[int | None, BundleChapterEntry]:
        entries: dict[int | None, BundleChapterEntry] = {}
        if detail.chapter_inventory:
            for entry in detail.chapter_inventory.entries:
                entries[entry.chapter_index] = entry
        return entries

    def _build_chapter_archive_candidate(
        self,
        derivation_report_id: str,
        detail: FullBookBundleDetail,
        viewer_state_id: str,
        chapter_index: int | None,
        overview: AnalysisReportSectionView,
        section_by_type: dict[str, list[AnalysisReportSectionView]],
        entry: BundleChapterEntry | None,
        known_gaps: list[str],
        timestamp: str,
    ) -> AnalyzeStoriesChapterArchiveCandidate | None:
        unsafe_issue = self._section_unsafe_issue("chapter_archive", overview, chapter_index)
        if unsafe_issue:
            return None
        emotion = self._first_section(section_by_type, "emotion_curve")
        macro = self._first_section(section_by_type, "macro_structure")
        refs = [
            self._bundle_ref(detail, chapter_index),
            self._section_ref(viewer_state_id, overview, chapter_index, "supports"),
        ]
        for optional in [emotion, macro, self._first_section(section_by_type, "theme")]:
            if optional is not None:
                refs.append(self._section_ref(viewer_state_id, optional, chapter_index, "context"))
        if entry is not None:
            refs.append(
                AnalyzeStoriesAdapterSourceRef(
                    source_type="bundle_chapter_entry",
                    source_id=entry.entry_id,
                    relationship="supports",
                    field_path="chapter_inventory.entries",
                    chapter_index=chapter_index,
                    safe_summary=self._short(entry.safe_summary or entry.input_filename or "", 180),
                )
            )
        return AnalyzeStoriesChapterArchiveCandidate(
            **self._candidate_base(
                "chapter_archive",
                derivation_report_id,
                detail,
                viewer_state_id,
                [overview.section_view_id],
                chapter_index,
                known_gaps,
                refs,
                timestamp,
            ),
            archive_summary_candidate=self._short(overview.safe_preview, 500),
            chapter_goal_result_candidate=self._short(macro.safe_preview if macro else overview.safe_preview, 260),
            reader_emotion_result_candidate=self._short(emotion.safe_preview if emotion else "", 260),
            conflict_state_candidate=self._short(macro.safe_preview if macro else "", 260),
            safe_summary=self._short(f"Chapter {chapter_index or 'unknown'} archive candidate from explicit overview section.", 260),
        )

    def _build_explicit_candidate(
        self,
        family: str,
        derivation_report_id: str,
        detail: FullBookBundleDetail,
        viewer_state_id: str,
        chapter_index: int | None,
        section: AnalysisReportSectionView,
        known_gaps: list[str],
        timestamp: str,
    ) -> Any | None:
        unsafe_issue = self._section_unsafe_issue(family, section, chapter_index)
        if unsafe_issue:
            return None
        refs = [self._bundle_ref(detail, chapter_index), self._section_ref(viewer_state_id, section, chapter_index, "supports")]
        base = self._candidate_base(
            family,
            derivation_report_id,
            detail,
            viewer_state_id,
            [section.section_view_id],
            chapter_index,
            known_gaps,
            refs,
            timestamp,
        )
        preview = self._short(section.safe_preview, 260)
        if family == "narrative_debt":
            return AnalyzeStoriesNarrativeDebtCandidate(
                **base,
                debt_type=self._debt_type(section),
                payoff_required=section.section_type not in {"open_thread"},
                open_ambiguity_allowed=section.section_type in {"open_thread", "foreshadowing"},
                symbolic_unresolved=section.section_type in {"foreshadowing"},
                payoff_deadline_hint="",
                safe_summary=preview,
            )
        if family == "open_thread":
            return AnalyzeStoriesOpenThreadCandidate(
                **base,
                thread_type=self._thread_type(section),
                setup_summary_candidate=preview,
                expected_payoff_hint="",
                safe_summary=preview,
            )
        if family == "closed_thread":
            return AnalyzeStoriesClosedThreadCandidate(
                **base,
                thread_type=self._thread_type(section),
                closure_summary_candidate=preview,
                safe_summary=preview,
            )
        if family == "payoff":
            warning = self._issue("related_thread_unlinked", "warning", "payoff", "related_open_thread_candidate_ids", section.section_view_id, chapter_index, "Explicit payoff has no exact related open-thread id/reference.")
            base["warnings"] = [warning]
            return AnalyzeStoriesPayoffCandidate(
                **base,
                payoff_type=self._thread_type(section),
                payoff_summary_candidate=preview,
                safe_summary=preview,
            )
        if family == "apparent_contradiction_template":
            return AnalyzeStoriesApparentContradictionTemplateCandidate(
                **base,
                contradiction_type="apparent_contradiction",
                surface_contradiction_candidate=preview,
                expected_gate_action="review_quality",
                requires_narrative_debt=True,
                safe_summary=preview,
            )
        return None

    def _candidate_base(
        self,
        family: str,
        derivation_report_id: str,
        detail: FullBookBundleDetail,
        viewer_state_id: str,
        section_view_ids: list[str],
        chapter_index: int | None,
        known_gaps: list[str],
        refs: list[AnalyzeStoriesAdapterSourceRef],
        timestamp: str,
    ) -> dict[str, Any]:
        manifest = detail.manifest
        return {
            "candidate_id": self._next_candidate_id(family),
            "candidate_family": family,
            "candidate_status": "candidate",
            "project_id": LOCAL_PROJECT_ID,
            "source": "analyze_stories",
            "derivation_report_id": derivation_report_id,
            "bundle_manifest_id": manifest.bundle_manifest_id,
            "import_id": manifest.import_id,
            "artifact_id": manifest.artifact_id,
            "viewer_state_id": viewer_state_id,
            "section_view_ids": section_view_ids,
            "chapter_index": chapter_index,
            "reliability_level": self._adapter_reliability(detail),
            "derivation_confidence": "explicit",
            "evidence_strength": "explicit_section",
            "source_refs": refs,
            "known_package_gaps_carried": known_gaps,
            "warnings": [],
            "blocking_issues": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "version_id": SCHEMA_VERSION,
        }

    def _explicit_family_for_section(self, section: AnalysisReportSectionView) -> str | None:
        section_type = self._norm(section.section_type)
        marker = self._norm(f"{section.section_id} {section.title}")
        if section_type in {"narrative_debt", "risk_warning"} or "narrative_debt" in marker:
            return "narrative_debt"
        if section_type == "foreshadowing" or "foreshadowing" in marker:
            return "open_thread"
        if section_type == "open_thread" or "open_thread" in marker:
            return "open_thread"
        if section_type == "closed_thread" or "closed_thread" in marker or "closure" in marker:
            return "closed_thread"
        if section_type == "payoff" or "payoff" in marker:
            return "payoff"
        if section_type == "apparent_contradiction" or "apparent_contradiction" in marker:
            return "apparent_contradiction_template"
        return None

    def _section_unsafe_issue(
        self,
        family: str,
        section: AnalysisReportSectionView,
        chapter_index: int | None,
    ) -> AnalyzeStoriesAdapterIssue | None:
        blob = json.dumps(model_to_dict(section), ensure_ascii=False, sort_keys=True)
        if UNSAFE_RE.search(blob):
            return self._issue("unsafe_section_payload_blocked", "blocking", family, "section_view", section.section_view_id, chapter_index, "Unsafe raw/secret marker detected in safe section view.")
        return None

    def _first_section(
        self,
        section_by_type: dict[str, list[AnalysisReportSectionView]],
        section_type: str,
    ) -> AnalysisReportSectionView | None:
        values = section_by_type.get(section_type) or []
        return values[0] if values else None

    def _first_section_by_marker(
        self,
        sections: list[AnalysisReportSectionView],
        markers: list[str],
    ) -> AnalysisReportSectionView | None:
        for section in sections:
            text = self._norm(f"{section.section_id} {section.title}")
            if any(marker in text for marker in markers):
                return section
        return None

    def _section_ref(
        self,
        viewer_state_id: str,
        section: AnalysisReportSectionView,
        chapter_index: int | None,
        relationship: str,
    ) -> AnalyzeStoriesAdapterSourceRef:
        return AnalyzeStoriesAdapterSourceRef(
            source_type="analysis_report_section_view",
            source_id=section.section_view_id,
            relationship=relationship,
            field_path="section_views",
            section_type=section.section_type,
            chapter_index=chapter_index,
            safe_summary=self._short(section.safe_preview or section.title, 180),
        )

    def _bundle_ref(
        self,
        detail: FullBookBundleDetail,
        chapter_index: int | None,
    ) -> AnalyzeStoriesAdapterSourceRef:
        return AnalyzeStoriesAdapterSourceRef(
            source_type="full_book_bundle_manifest",
            source_id=detail.manifest.bundle_manifest_id,
            relationship="supports",
            field_path="bundle_manifest_id",
            chapter_index=chapter_index,
            safe_summary=self._short(detail.manifest.safe_summary, 180),
        )

    def _issue(
        self,
        code: str,
        severity: str,
        family: str | None,
        field_path: str | None,
        source_id: str | None,
        chapter_index: int | None,
        safe_detail: str,
    ) -> AnalyzeStoriesAdapterIssue:
        return AnalyzeStoriesAdapterIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            candidate_family=family,  # type: ignore[arg-type]
            field_path=field_path,
            source_id=source_id,
            chapter_index=chapter_index,
            safe_detail=self._short(safe_detail, 260),
        )

    def _adapter_reliability(self, detail: FullBookBundleDetail) -> str:
        reliability = detail.manifest.reliability_level
        if reliability == "validated_with_warnings":
            return "validated_with_warnings"
        if reliability == "stable":
            return "stable"
        return "blocked"

    def _known_package_gaps(self, detail: FullBookBundleDetail) -> list[str]:
        manifest = detail.manifest
        if manifest.schema_version == "analyze_stories_handoff.v1" and manifest.exporter_version == "1.4":
            return ["character_arc_empty_by_design"]
        return []

    def _imported_framework_decision_ids(self) -> list[str]:
        path = self.data_dir / "imported_framework_decisions.json"
        if not path.exists():
            return []
        return [
            str(item.get("decision_id"))
            for item in self._read_list(path)
            if item.get("decision_id")
        ][:50]

    def _debt_type(self, section: AnalysisReportSectionView) -> str:
        if section.section_type in {"foreshadowing", "open_thread", "risk_warning"}:
            return section.section_type
        return "narrative_debt"

    def _thread_type(self, section: AnalysisReportSectionView) -> str:
        return section.section_type if section.section_type != "other" else "unknown"

    def _guard_safe_text(self, value: str | None) -> None:
        if value and UNSAFE_RE.search(value):
            raise StorageError("ANALYZE_STORIES_ADAPTER_UNSAFE_NOTE_BLOCKED")

    def _short(self, value: Any, limit: int) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        text = " ".join(text.split())
        return text[:limit]

    def _norm(self, value: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        items.append(item)
        self.store.write(path, items)

    def _replace_record(self, path: Path, key: str, key_value: str, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        for index, existing in enumerate(items):
            if existing.get(key) == key_value:
                items[index] = item
                self.store.write(path, items)
                return
        raise StorageError(f"ANALYZE_STORIES_ADAPTER_CANDIDATE_NOT_FOUND: {key_value}")

    def _next_id(self, path: Path, key: str, prefix: str) -> str:
        max_index = 0
        for item in self._read_list(path):
            value = str(item.get(key) or "")
            if value.startswith(f"{prefix}_"):
                suffix = value.removeprefix(f"{prefix}_")
                if suffix.isdigit():
                    max_index = max(max_index, int(suffix))
        return f"{prefix}_{max_index + 1:03d}"

    def _next_candidate_id(self, family: str) -> str:
        prefix = f"as_{family}_candidate"
        next_persisted_id = self._next_id(self.candidate_files[family], "candidate_id", prefix)
        next_index = int(next_persisted_id.rsplit("_", 1)[-1])
        runtime_counts = getattr(self, "_runtime_candidate_counts", None)
        if isinstance(runtime_counts, dict):
            offset = int(runtime_counts.get(family, 0))
            runtime_counts[family] = offset + 1
            next_index += offset
        return f"{prefix}_{next_index:03d}"

    def _find_candidate_record(self, candidate_id: str) -> tuple[str, dict[str, Any]]:
        for family, path in self.candidate_files.items():
            for record in self._read_list(path):
                if record.get("candidate_id") == candidate_id:
                    return family, record
        raise StorageError(f"ANALYZE_STORIES_ADAPTER_CANDIDATE_NOT_FOUND: {candidate_id}")
