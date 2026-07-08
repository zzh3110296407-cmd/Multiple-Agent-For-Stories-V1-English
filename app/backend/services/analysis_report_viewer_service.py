import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.models.analysis_report_viewer import (
    AnalysisReportReferenceLink,
    AnalysisReportSectionView,
    AnalysisReportViewerDetail,
    AnalysisReportViewerIssue,
    AnalysisReportViewerListResponse,
    AnalysisReportViewerResult,
    AnalysisReportViewerReviewResult,
    AnalysisReportViewerState,
)
from app.backend.models.analyze_stories_import import (
    AnalyzeStoriesImportedArtifact,
    AnalyzeStoriesImportDetail,
    AnalyzeStoriesInputFingerprint,
    StoryAnalysisReportRef,
)
from app.backend.models.framework_package_candidate import FrameworkPackageCandidate
from app.backend.services.analyze_stories_import_service import AnalyzeStoriesImportService
from app.backend.services.framework_package_candidate_service import FrameworkPackageCandidateService
from app.backend.storage.json_store import JsonStore, StorageError


VIEWER_STATES_FILE = "analysis_report_viewer_states.json"
SECTION_VIEWS_FILE = "analysis_report_section_views.json"
REFERENCE_LINKS_FILE = "analysis_report_reference_links.json"
SCHEMA_VERSION = "phase5_m3_story_analysis_report_viewer_v1"
LOCAL_PROJECT_ID = "local_project"

UNSAFE_NORMALIZED_KEYS = {
    "apikey",
    "authorization",
    "bearer",
    "rawprompt",
    "rawmodelprompt",
    "rawresponse",
    "rawmodelresponse",
    "hiddenreasoning",
    "internalreasoning",
    "chainofthought",
    "providersecret",
    "langsmithapikey",
    "secretkey",
}
UNSAFE_TEXT_FIELD_KEYS = {
    "fullprose",
    "prosetext",
    "revisedprosetext",
    "storytext",
    "chaptertext",
    "fullstorytext",
    "completestorytext",
    "rawstoryinput",
}
UNSAFE_VALUE_MARKERS = [
    "RAW_PROMPT",
    "RAW_RESPONSE",
    "HIDDEN_REASONING",
    "INTERNAL_REASONING",
    "CHAIN_OF_THOUGHT",
    "chain-of-thought",
    "raw prompt",
    "raw response",
    "hidden reasoning",
]
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{8,}"),
    re.compile(r"\blsv2_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE),
]

SECTION_TYPE_HINTS = [
    ("macro", "macro_structure"),
    ("framework", "macro_structure"),
    ("mapping", "chapter_mapping_reason"),
    ("chapter_summary", "overview"),
    ("summary", "overview"),
    ("theme", "theme"),
    ("emotion", "emotion_curve"),
    ("foreshadow", "foreshadowing"),
    ("伏笔", "foreshadowing"),
    ("payoff", "payoff"),
    ("open_thread", "open_thread"),
    ("thread", "open_thread"),
    ("motif", "motif"),
    ("setting", "setting"),
    ("prop", "prop"),
    ("dialogue", "key_dialogue"),
    ("conflict", "conflict"),
    ("desire", "character_desire"),
    ("character_arc", "character_arc"),
    ("relationship", "relationship"),
    ("risk", "risk_warning"),
    ("warning", "risk_warning"),
]


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AnalysisReportViewerService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        analyze_import_service: AnalyzeStoriesImportService | None = None,
        framework_candidate_service: FrameworkPackageCandidateService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.analyze_import_service = analyze_import_service or AnalyzeStoriesImportService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.framework_candidate_service = framework_candidate_service or FrameworkPackageCandidateService(
            store=self.store,
            data_dir=self.data_dir,
            analyze_import_service=self.analyze_import_service,
        )
        self.viewer_states_file = self.data_dir / VIEWER_STATES_FILE
        self.section_views_file = self.data_dir / SECTION_VIEWS_FILE
        self.reference_links_file = self.data_dir / REFERENCE_LINKS_FILE

    def create_viewer_state(self, report_ref_id: str) -> AnalysisReportViewerResult:
        report_ref = self._get_report_ref(report_ref_id)
        existing = self._find_viewer_by_report_ref(report_ref_id)
        if existing is not None:
            return self.get_viewer_state(existing.viewer_state_id)

        detail = self.analyze_import_service.get_detail(report_ref.import_id)
        artifact = self._get_artifact(detail, report_ref.artifact_id)
        blocking_issues = self._dependency_issues(report_ref, artifact)
        if blocking_issues:
            return self._blocked_result(report_ref, blocking_issues)

        try:
            payload = self.analyze_import_service.read_artifact_payload(
                report_ref.import_id,
                report_ref.artifact_id,
            )
        except StorageError:
            return self._blocked_result(
                report_ref,
                [
                    self._issue(
                        "story_report_payload_unavailable",
                        "blocking",
                        "Safe story analysis report payload is unavailable.",
                        "payload_ref",
                        "Re-import the report with M3 enabled; hash-only reports cannot open a viewer.",
                    )
                ],
            )

        safety_issues = self._scan_safety(payload)
        blocking_safety = [issue for issue in safety_issues if issue.severity == "blocking"]
        if blocking_safety:
            return self._blocked_result(report_ref, blocking_safety)

        timestamp = now_iso()
        viewer_state_id = self._next_viewer_state_id()
        extracted = self._extract_report_payload(payload)
        warnings = list(safety_issues)
        warnings.extend(self._report_shape_warnings(extracted, detail.input_fingerprints))
        candidate, candidate_warning = self._resolve_framework_candidate_context(report_ref, detail)
        if candidate_warning is not None:
            warnings.append(candidate_warning)
        section_views = self._build_section_views(
            viewer_state_id=viewer_state_id,
            report_ref=report_ref,
            sections=extracted["sections"],
            created_at=timestamp,
        )
        reference_links = self._build_reference_links(
            viewer_state_id=viewer_state_id,
            report_ref=report_ref,
            detail=detail,
            artifact=artifact,
            section_views=section_views,
            candidate=candidate,
            created_at=timestamp,
        )
        viewer_state = AnalysisReportViewerState(
            viewer_state_id=viewer_state_id,
            project_id=LOCAL_PROJECT_ID,
            story_analysis_report_ref_id=report_ref.story_analysis_report_ref_id,
            import_id=report_ref.import_id,
            artifact_id=report_ref.artifact_id,
            linked_framework_package_id=report_ref.linked_framework_package_id,
            viewer_status="available_with_warnings" if warnings else "available",
            review_status="not_reviewed",
            safe_title=extracted["safe_title"],
            safe_summary=extracted["safe_summary"],
            section_view_ids=[item.section_view_id for item in section_views],
            reference_link_ids=[item.reference_link_id for item in reference_links],
            warning_count=len(warnings),
            blocking_issue_count=0,
            warnings=warnings,
            blocking_issues=[],
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        self._append(self.viewer_states_file, model_to_dict(viewer_state))
        for section in section_views:
            self._append(self.section_views_file, model_to_dict(section))
        for link in reference_links:
            self._append(self.reference_links_file, model_to_dict(link))
        return AnalysisReportViewerResult(
            success=True,
            viewer_state=viewer_state,
            section_views=section_views,
            reference_links=reference_links,
        )

    def get_viewer_state_for_report(self, report_ref_id: str) -> AnalysisReportViewerDetail:
        viewer_state = self._find_viewer_by_report_ref(report_ref_id)
        if viewer_state is None:
            raise StorageError(f"ANALYSIS_REPORT_VIEWER_NOT_FOUND: {report_ref_id}")
        return self.get_viewer_state(viewer_state.viewer_state_id)

    def get_viewer_state(self, viewer_state_id: str) -> AnalysisReportViewerDetail:
        viewer_state = self._get_viewer_state(viewer_state_id)
        section_views = [
            AnalysisReportSectionView(**item)
            for item in self._read_list(self.section_views_file)
            if item.get("viewer_state_id") == viewer_state_id
        ]
        reference_links = [
            AnalysisReportReferenceLink(**item)
            for item in self._read_list(self.reference_links_file)
            if item.get("viewer_state_id") == viewer_state_id
        ]
        section_views.sort(key=lambda item: item.section_index)
        reference_links.sort(key=lambda item: item.reference_link_id)
        return AnalysisReportViewerDetail(
            viewer_state=viewer_state,
            section_views=section_views,
            reference_links=reference_links,
        )

    def list_viewer_states(self) -> AnalysisReportViewerListResponse:
        states = [
            AnalysisReportViewerState(**item)
            for item in self._read_list(self.viewer_states_file)
        ]
        states.sort(key=lambda item: item.updated_at, reverse=True)
        return AnalysisReportViewerListResponse(viewer_states=states)

    def mark_reviewed(self, viewer_state_id: str) -> AnalysisReportViewerReviewResult:
        return self._update_review_status(viewer_state_id, "reviewed")

    def flag(self, viewer_state_id: str, note: str | None = None) -> AnalysisReportViewerReviewResult:
        self._validate_safe_note(note)
        return self._update_review_status(viewer_state_id, "flagged")

    def dismiss(self, viewer_state_id: str, note: str | None = None) -> AnalysisReportViewerReviewResult:
        self._validate_safe_note(note)
        return self._update_review_status(viewer_state_id, "dismissed")

    def _update_review_status(
        self,
        viewer_state_id: str,
        review_status: str,
    ) -> AnalysisReportViewerReviewResult:
        items = self._read_list(self.viewer_states_file)
        updated: AnalysisReportViewerState | None = None
        timestamp = now_iso()
        for index, item in enumerate(items):
            if item.get("viewer_state_id") == viewer_state_id:
                item["review_status"] = review_status
                item["updated_at"] = timestamp
                items[index] = item
                updated = AnalysisReportViewerState(**item)
                break
        if updated is None:
            raise StorageError(f"ANALYSIS_REPORT_VIEWER_NOT_FOUND: {viewer_state_id}")
        self.store.write(self.viewer_states_file, items)
        return AnalysisReportViewerReviewResult(success=True, viewer_state=updated)

    def _dependency_issues(
        self,
        report_ref: StoryAnalysisReportRef,
        artifact: AnalyzeStoriesImportedArtifact | None,
    ) -> list[AnalysisReportViewerIssue]:
        issues: list[AnalysisReportViewerIssue] = []
        if report_ref.viewer_status in {"blocked", "invalid", "missing"}:
            issues.append(
                self._issue(
                    "story_report_ref_not_available",
                    "blocking",
                    "Story analysis report ref is not available for viewer creation.",
                    "viewer_status",
                    f"viewer_status={report_ref.viewer_status}",
                )
            )
        if artifact is None:
            issues.append(
                self._issue(
                    "story_report_artifact_missing",
                    "blocking",
                    "Story analysis report artifact is missing.",
                    "artifact_id",
                    report_ref.artifact_id,
                )
            )
            return issues
        if artifact.file_kind != "story_analysis_report":
            issues.append(
                self._issue(
                    "artifact_not_story_analysis_report",
                    "blocking",
                    "Artifact is not a story analysis report.",
                    "file_kind",
                    artifact.file_kind,
                )
            )
        if artifact.raw_storage_status != "stored" or not artifact.payload_ref:
            issues.append(
                self._issue(
                    "story_report_payload_unavailable",
                    "blocking",
                    "Safe story analysis report payload is unavailable.",
                    "payload_ref",
                    "Blocked, invalid, or historical hash-only reports cannot open a viewer.",
                )
            )
        return issues

    def _blocked_result(
        self,
        report_ref: StoryAnalysisReportRef,
        blocking_issues: list[AnalysisReportViewerIssue],
    ) -> AnalysisReportViewerResult:
        timestamp = now_iso()
        state = AnalysisReportViewerState(
            viewer_state_id=f"blocked_{report_ref.story_analysis_report_ref_id}",
            project_id=LOCAL_PROJECT_ID,
            story_analysis_report_ref_id=report_ref.story_analysis_report_ref_id,
            import_id=report_ref.import_id,
            artifact_id=report_ref.artifact_id,
            linked_framework_package_id=report_ref.linked_framework_package_id,
            viewer_status="blocked",
            review_status="not_reviewed",
            safe_title=report_ref.safe_title or "Story analysis report unavailable",
            safe_summary="Viewer was not created because the report payload is unavailable or unsafe.",
            section_view_ids=[],
            reference_link_ids=[],
            warning_count=0,
            blocking_issue_count=len(blocking_issues),
            warnings=[],
            blocking_issues=blocking_issues,
            created_at=timestamp,
            updated_at=timestamp,
            version_id=SCHEMA_VERSION,
        )
        return AnalysisReportViewerResult(
            success=False,
            viewer_state=state,
            section_views=[],
            reference_links=[],
        )

    def _build_section_views(
        self,
        *,
        viewer_state_id: str,
        report_ref: StoryAnalysisReportRef,
        sections: list[Any],
        created_at: str,
    ) -> list[AnalysisReportSectionView]:
        views: list[AnalysisReportSectionView] = []
        if not sections:
            return views
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            section_id = self._first_str(section.get("section_id"), section.get("id")) or f"section_{index + 1:03d}"
            title = self._short(
                self._first_str(section.get("title"), section.get("heading")) or section_id,
                100,
            )
            declared_type = self._first_str(section.get("section_type"), section.get("type"))
            inferred_type = self._infer_section_type(section_id, title, declared_type)
            warnings = []
            safe_preview = self._short(
                self._first_str(
                    section.get("summary"),
                    section.get("safe_summary"),
                    section.get("preview"),
                    section.get("description"),
                )
                or "",
                360,
            )
            if not safe_preview and self._has_redacted_section_content(section):
                safe_preview = "Content is available only as a safe hash or was hidden by the viewer safety policy."
                warnings.append("content_hash_only_or_redacted")
            if inferred_type == "other" and not declared_type:
                warnings.append("missing_section_type")
            display_status = "collapsed" if inferred_type == "other" else "visible"
            views.append(
                AnalysisReportSectionView(
                    section_view_id=f"{viewer_state_id}_section_{index + 1:03d}",
                    viewer_state_id=viewer_state_id,
                    story_analysis_report_ref_id=report_ref.story_analysis_report_ref_id,
                    section_index=index + 1,
                    section_id=self._short(section_id, 80),
                    title=title,
                    section_type=inferred_type,
                    inferred_section_type=not bool(declared_type),
                    display_status=display_status,
                    safe_preview=safe_preview,
                    safe_field_paths=self._safe_field_paths(section),
                    evidence_refs=self._safe_evidence_refs(section.get("evidence_refs")),
                    warning_codes=warnings,
                    created_at=created_at,
                    version_id=SCHEMA_VERSION,
                )
            )
        return views

    def _has_redacted_section_content(self, section: dict[str, Any]) -> bool:
        for key in ("content", "body", "text", "raw_content", "content_sha256"):
            value = section.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, (dict, list)) and value:
                return True
        return False

    def _build_reference_links(
        self,
        *,
        viewer_state_id: str,
        report_ref: StoryAnalysisReportRef,
        detail: AnalyzeStoriesImportDetail,
        artifact: AnalyzeStoriesImportedArtifact,
        section_views: list[AnalysisReportSectionView],
        candidate: FrameworkPackageCandidate | None,
        created_at: str,
    ) -> list[AnalysisReportReferenceLink]:
        links: list[AnalysisReportReferenceLink] = []

        def add(
            source_type: str,
            source_id: str,
            source_label: str,
            field_path: str | None = None,
            safe_summary: str = "",
            relationship: str = "supports",
        ) -> None:
            links.append(
                AnalysisReportReferenceLink(
                    reference_link_id=f"{viewer_state_id}_ref_{len(links) + 1:03d}",
                    viewer_state_id=viewer_state_id,
                    story_analysis_report_ref_id=report_ref.story_analysis_report_ref_id,
                    source_type=source_type,  # type: ignore[arg-type]
                    source_id=self._short(source_id, 120),
                    source_label=self._short(source_label, 120),
                    relationship=relationship,  # type: ignore[arg-type]
                    field_path=field_path,
                    safe_summary=self._short(safe_summary, 260),
                    created_at=created_at,
                    version_id=SCHEMA_VERSION,
                )
            )

        add("import", detail.manifest.import_id, "Analyze Stories import", "manifest.import_id", detail.manifest.import_status, "supports")
        add("artifact", artifact.artifact_id, "Story analysis report artifact", "artifact.artifact_id", artifact.safe_summary, "supports")
        for fingerprint in detail.input_fingerprints[:12]:
            add(
                "input_fingerprint",
                fingerprint.fingerprint_id,
                fingerprint.input_filename or f"chapter_{fingerprint.chapter_index or 'unknown'}",
                "input_fingerprint_ids",
                self._fingerprint_summary(fingerprint),
                "supports",
            )

        if candidate is not None:
            add(
                "framework_candidate",
                candidate.candidate_id,
                "Inactive normalized framework candidate",
                "candidate_id",
                candidate.candidate_status,
                "supports",
            )
            add(
                "normalization_report",
                candidate.normalization_report_id,
                "Framework normalization report",
                "normalization_report_id",
                "Optional M2 candidate context only; not activated by this viewer.",
                "explains",
            )
            self._add_macro_component_links(add, candidate, section_views)

        for section in section_views:
            add(
                "report_section",
                section.section_view_id,
                section.title,
                f"sections[{section.section_index - 1}]",
                section.section_type,
                "explains",
            )
        return links

    def _add_macro_component_links(
        self,
        add: Any,
        candidate: FrameworkPackageCandidate,
        section_views: list[AnalysisReportSectionView],
    ) -> None:
        package = candidate.normalized_framework_package or {}
        macro_framework = package.get("macro_framework")
        if not isinstance(macro_framework, dict):
            return
        components = macro_framework.get("components")
        if not isinstance(components, list):
            return
        searchable = " ".join(
            " ".join(
                [
                    section.section_id,
                    section.title,
                    section.safe_preview,
                    " ".join(str(ref.get("safe_excerpt", "")) for ref in section.evidence_refs),
                ]
            )
            for section in section_views
        ).lower()
        for component in components:
            if not isinstance(component, dict):
                continue
            component_id = self._first_str(component.get("component_id"))
            label = self._first_str(component.get("label"))
            if not component_id:
                continue
            haystack_tokens = {component_id.lower()}
            if label:
                haystack_tokens.add(label.lower())
            if any(token and token in searchable for token in haystack_tokens):
                add(
                    "macro_component",
                    component_id,
                    label or component_id,
                    "normalized_framework_package.macro_framework.components",
                    "Matched by safe report section reference.",
                    "explains",
                )

    def _resolve_framework_candidate_context(
        self,
        report_ref: StoryAnalysisReportRef,
        detail: AnalyzeStoriesImportDetail,
    ) -> tuple[FrameworkPackageCandidate | None, AnalysisReportViewerIssue | None]:
        try:
            candidates = self.framework_candidate_service.list_candidates().candidates
        except StorageError:
            return None, self._issue(
                "candidate_context_unavailable",
                "warning",
                "Framework candidate context is unavailable.",
                "framework_candidates",
                "Candidate store could not be read; viewer remains explanation-only.",
            )
        if not candidates:
            return None, self._issue(
                "candidate_context_unavailable",
                "warning",
                "No inactive M2 framework candidate context is available.",
                "framework_candidates",
                "Viewer remains available without candidate links.",
            )
        linked = self._normalize_key(report_ref.linked_framework_package_id or "")
        if linked:
            for candidate in candidates:
                package = candidate.normalized_framework_package or {}
                macro = package.get("macro_framework") if isinstance(package, dict) else {}
                framework_id = ""
                if isinstance(macro, dict):
                    framework_id = self._first_str(macro.get("framework_id")) or ""
                if linked in {
                    self._normalize_key(candidate.candidate_id),
                    self._normalize_key(framework_id),
                }:
                    return candidate, None
            return None, self._issue(
                "candidate_context_conflict",
                "warning",
                "Report linked framework id does not match any inactive M2 candidate.",
                "linked_framework_package_id",
                f"linked_framework_package_id={report_ref.linked_framework_package_id}",
            )
        fingerprint_ids = set(detail.manifest.input_fingerprint_ids)
        fingerprint_ids.update(
            item.fingerprint_id for item in detail.input_fingerprints if item.fingerprint_id
        )
        if not fingerprint_ids:
            return None, self._issue(
                "candidate_context_unavailable",
                "warning",
                "Report has no comparable input fingerprint for candidate context matching.",
                "input_fingerprint_ids",
                "Viewer remains available without candidate links.",
            )
        for candidate in candidates:
            if set(candidate.input_fingerprint_ids) & fingerprint_ids:
                return candidate, None
        return None, self._issue(
            "candidate_context_conflict",
            "warning",
            "Existing M2 candidates do not match this report import identity.",
            "input_fingerprint_ids",
            "Candidate links were not created to avoid false provenance.",
        )

    def _extract_report_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        nested = payload.get("story_analysis_report")
        report = nested if isinstance(nested, dict) else payload
        title = self._first_str(
            payload.get("report_title"),
            payload.get("title"),
            report.get("title") if isinstance(report, dict) else None,
        )
        summary = self._first_str(
            payload.get("analysis_summary"),
            payload.get("summary"),
            report.get("summary") if isinstance(report, dict) else None,
        )
        raw_sections = payload.get("report_sections")
        if not isinstance(raw_sections, list):
            raw_sections = payload.get("sections")
        if not isinstance(raw_sections, list) and isinstance(report, dict):
            raw_sections = report.get("sections")
        return {
            "safe_title": self._short(title or "Analyze Stories report", 120),
            "safe_summary": self._short(summary or "", 700),
            "sections": raw_sections if isinstance(raw_sections, list) else [],
        }

    def _report_shape_warnings(
        self,
        extracted: dict[str, Any],
        fingerprints: list[AnalyzeStoriesInputFingerprint],
    ) -> list[AnalysisReportViewerIssue]:
        warnings: list[AnalysisReportViewerIssue] = []
        if not extracted["safe_summary"]:
            warnings.append(
                self._issue(
                    "possible_empty_report_summary",
                    "warning",
                    "Report summary is empty or missing.",
                    "summary",
                    "Viewer shows sections only.",
                )
            )
        if not extracted["sections"]:
            warnings.append(
                self._issue(
                    "missing_report_sections",
                    "warning",
                    "Report sections are missing.",
                    "sections",
                    "Viewer can only show title and summary.",
                )
            )
        for fingerprint in fingerprints:
            if self._suspicious_input_title(fingerprint.input_title):
                warnings.append(
                    self._issue(
                        "suspicious_or_incomplete_input_metadata",
                        "warning",
                        "Input metadata title looks too verbose for display.",
                        "input_title",
                        f"fingerprint={fingerprint.fingerprint_id}; title_length={len(fingerprint.input_title or '')}",
                    )
                )
                break
        return warnings

    def _scan_safety(self, value: Any) -> list[AnalysisReportViewerIssue]:
        issues: list[AnalysisReportViewerIssue] = []

        def walk(node: Any, path: str, key_hint: str = "") -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    key_text = str(key)
                    normalized = self._normalize_key(key_text)
                    child_path = f"{path}.{key_text}" if path else key_text
                    if normalized in UNSAFE_NORMALIZED_KEYS:
                        issues.append(self._unsafe_issue("unsafe_field_name", child_path))
                    if normalized in UNSAFE_TEXT_FIELD_KEYS and isinstance(child, str) and len(child.strip()) > 80:
                        issues.append(self._unsafe_issue("unsafe_full_prose_field", child_path))
                    walk(child, child_path, normalized)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]", key_hint)
            elif isinstance(node, str):
                if self._looks_like_secret(node):
                    issues.append(self._unsafe_issue("unsafe_secret_value", path))
                elif any(marker in node for marker in UNSAFE_VALUE_MARKERS):
                    issues.append(self._unsafe_issue("unsafe_marker_value", path))
                elif key_hint in UNSAFE_TEXT_FIELD_KEYS and len(node.strip()) > 80:
                    issues.append(self._unsafe_issue("unsafe_full_prose_value", path))
                elif len(node) > 12000:
                    issues.append(self._unsafe_issue("unsafe_long_text_value", path))

        walk(value, "$")
        deduped: dict[tuple[str, str | None], AnalysisReportViewerIssue] = {}
        for issue in issues:
            deduped[(issue.code, issue.field_path)] = issue
        return list(deduped.values())

    def _unsafe_issue(self, code: str, path: str) -> AnalysisReportViewerIssue:
        return self._issue(
            code,
            "blocking",
            "Story analysis report payload contains unsafe raw or secret-like data.",
            self._redacted_field_path(path),
            "Value redacted; viewer was not created.",
        )

    def _safe_field_paths(self, section: dict[str, Any]) -> list[str]:
        paths = []
        for key in ["section_id", "title", "section_type", "summary", "safe_summary", "preview", "evidence_refs"]:
            if key in section:
                paths.append(key)
        return paths

    def _safe_evidence_refs(self, refs: Any) -> list[dict[str, Any]]:
        if not isinstance(refs, list):
            return []
        safe_refs: list[dict[str, Any]] = []
        for ref in refs[:12]:
            if not isinstance(ref, dict):
                continue
            safe_item: dict[str, Any] = {}
            for key, value in ref.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    safe_item[self._short(str(key), 60)] = self._short(str(value), 140)
            if safe_item:
                safe_refs.append(safe_item)
        return safe_refs

    def _infer_section_type(
        self,
        section_id: str,
        title: str,
        declared_type: str | None,
    ) -> str:
        if declared_type:
            normalized = self._normalize_key(declared_type)
            if normalized:
                return self._short(normalized, 80)
        searchable = f"{section_id} {title}".lower()
        for hint, section_type in SECTION_TYPE_HINTS:
            if hint in searchable:
                return section_type
        return "other"

    def _get_report_ref(self, report_ref_id: str) -> StoryAnalysisReportRef:
        for item in self._read_list(self.analyze_import_service.report_refs_file):
            if item.get("story_analysis_report_ref_id") == report_ref_id:
                return StoryAnalysisReportRef(**item)
        raise StorageError(f"STORY_ANALYSIS_REPORT_REF_NOT_FOUND: {report_ref_id}")

    def _get_artifact(
        self,
        detail: AnalyzeStoriesImportDetail,
        artifact_id: str,
    ) -> AnalyzeStoriesImportedArtifact | None:
        return next((item for item in detail.artifacts if item.artifact_id == artifact_id), None)

    def _get_viewer_state(self, viewer_state_id: str) -> AnalysisReportViewerState:
        for item in self._read_list(self.viewer_states_file):
            if item.get("viewer_state_id") == viewer_state_id:
                return AnalysisReportViewerState(**item)
        raise StorageError(f"ANALYSIS_REPORT_VIEWER_NOT_FOUND: {viewer_state_id}")

    def _find_viewer_by_report_ref(self, report_ref_id: str) -> AnalysisReportViewerState | None:
        for item in self._read_list(self.viewer_states_file):
            if item.get("story_analysis_report_ref_id") == report_ref_id:
                return AnalysisReportViewerState(**item)
        return None

    def _next_viewer_state_id(self) -> str:
        return f"analysis_report_viewer_{len(self._read_list(self.viewer_states_file)) + 1:03d}"

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not self.store.exists(path):
            return []
        data = self.store.read_list(path)
        return [item for item in data if isinstance(item, dict)]

    def _append(self, path: Path, item: dict[str, Any]) -> None:
        items = self._read_list(path)
        items.append(item)
        self.store.write(path, items)

    def _issue(
        self,
        code: str,
        severity: str,
        message: str,
        field_path: str | None = None,
        safe_detail: str | None = None,
    ) -> AnalysisReportViewerIssue:
        return AnalysisReportViewerIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            field_path=field_path,
            safe_detail=self._short(safe_detail, 260) if safe_detail else None,
        )

    def _fingerprint_summary(self, fingerprint: AnalyzeStoriesInputFingerprint) -> str:
        parts = [
            f"chapter={fingerprint.chapter_index}" if fingerprint.chapter_index is not None else "",
            f"hash={fingerprint.input_content_sha256[:12]}..." if fingerprint.input_content_sha256 else "",
            f"status={fingerprint.completeness_status}",
        ]
        return "; ".join(part for part in parts if part)

    def _suspicious_input_title(self, title: str | None) -> bool:
        if not title:
            return True
        stripped = title.strip()
        if len(stripped) > 120:
            return True
        punctuation_count = sum(1 for char in stripped if char in "，。！？；,.!?;:")
        return len(stripped) > 80 and punctuation_count >= 3

    def _validate_safe_note(self, note: str | None) -> None:
        if not note:
            return
        issues = self._scan_safety({"note": note})
        if any(issue.severity == "blocking" for issue in issues):
            raise StorageError("ANALYSIS_REPORT_VIEWER_UNSAFE_NOTE_BLOCKED")

    def _looks_like_secret(self, value: str) -> bool:
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)

    def _normalize_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _redacted_field_path(self, path: str) -> str:
        parts = []
        for part in path.split("."):
            normalized = self._normalize_key(part)
            if normalized in UNSAFE_NORMALIZED_KEYS or normalized in UNSAFE_TEXT_FIELD_KEYS:
                parts.append("[redacted]")
            else:
                parts.append(part[:80])
        return ".".join(parts)

    def _first_str(self, *values: Any) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(value)
        return None

    def _short(self, value: Any, limit: int = 240) -> str:
        text = "" if value is None else str(value)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."
