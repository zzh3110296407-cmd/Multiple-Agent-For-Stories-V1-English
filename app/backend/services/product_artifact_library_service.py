from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.product_artifacts import (
    FinalStoryPackageProductView,
    FinalStoryPackageProductViewListResponse,
    PluginOutputProductView,
    PluginOutputProductViewListResponse,
    ProductArtifactAuthorityBadge,
    ProductArtifactEntry,
    ProductArtifactEntryListResponse,
    ProductArtifactLibraryState,
    ProductArtifactSafePreview,
    ProductArtifactSafetySummary,
)
from app.backend.services.active_project_story_data import (
    active_project_story_data_dir,
    active_project_without_story_data,
    current_story_workspace_project_id,
    story_data_dir_for_project,
)
from app.backend.storage.json_store import JsonStore, StorageError


FINAL_STORY_PACKAGE_SNAPSHOTS_FILE = "final_story_package_snapshots.json"
FINAL_STORY_PACKAGE_PREVIEW_SECTIONS_FILE = "final_story_package_preview_sections.json"
FINAL_STORY_PACKAGE_EVIDENCE_INDEXES_FILE = "final_story_package_evidence_indexes.json"
FINAL_STORY_PACKAGE_SAFETY_AUDITS_FILE = "final_story_package_safety_audits.json"
PLUGIN_OUTPUT_ARTIFACTS_FILE = "plugin_output_artifacts.json"
PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE = "plugin_output_artifact_versions.json"
PLUGIN_RUN_SAFETY_REPORTS_FILE = "plugin_run_safety_reports.json"
SCREENPLAY_DRAFT_ARTIFACTS_FILE = "screenplay_draft_artifacts.json"
STORYBOARD_PACKAGES_FILE = "storyboard_packages.json"
DIGITAL_ASSET_PACKAGES_FILE = "digital_asset_packages.json"


SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")
UNSAFE_VALUE_MARKERS = (
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "authorization",
    "bearer ",
    "provider_secret",
    "provider secret",
    "langsmith key",
)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


class ProductArtifactNotFound(StorageError):
    pass


class ProductArtifactLibraryService:
    """Builds read-only product-facing views over Phase 7 output artifacts."""

    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.store = store or JsonStore()
        self._explicit_data_dir = data_dir is not None
        self._base_data_dir = data_dir or settings.data_dir
        self.data_dir = self._base_data_dir
        self._missing_active_project_id = ""
        self._project_id = ""
        self._workspace_resolved = False

    @property
    def project_id(self) -> str:
        self._resolve_workspace()
        return self._project_id

    def library(self, *, project_id: str | None = None) -> ProductArtifactLibraryState:
        self._assert_active_story_data_available(project_id)
        effective_project_id = self._effective_project_id(project_id)
        final_views = self.final_story_package_views(project_id=effective_project_id).views
        plugin_views = self.plugin_output_views(project_id=effective_project_id).views
        entries: list[ProductArtifactEntry] = []
        entries.extend(self._entry_from_final_view(view) for view in final_views)
        entries.extend(self._entry_from_plugin_view(view) for view in plugin_views)
        entries.extend(self._screenplay_entries(project_id=effective_project_id))
        entries.extend(self._storyboard_entries(project_id=effective_project_id))
        entries.extend(self._digital_asset_entries(project_id=effective_project_id))
        category_counts = dict(Counter(entry.artifact_category for entry in entries))
        return ProductArtifactLibraryState(
            project_id=effective_project_id or "",
            entries=entries,
            final_story_package_views=final_views,
            plugin_output_views=plugin_views,
            total_count=len(entries),
            category_counts=category_counts,
            safe_summary="只读产品成果库，不会写回故事或插件成果。",
        )

    def entries(self, *, project_id: str | None = None) -> ProductArtifactEntryListResponse:
        self._assert_active_story_data_available(project_id)
        entries = self.library(project_id=project_id).entries
        return ProductArtifactEntryListResponse(
            entries=entries,
            total_count=len(entries),
            safe_summary="产品成果条目只包含安全摘要和引用。",
        )

    def get_entry(self, artifact_entry_id: str, *, project_id: str | None = None) -> ProductArtifactEntry:
        for entry in self.library(project_id=project_id).entries:
            if entry.artifact_entry_id == artifact_entry_id:
                return entry
        raise ProductArtifactNotFound(f"PRODUCT_ARTIFACT_ENTRY_NOT_FOUND:{artifact_entry_id}")

    def get_authority_badge(
        self,
        artifact_entry_id: str,
        *,
        project_id: str | None = None,
    ) -> ProductArtifactAuthorityBadge:
        return self.get_entry(artifact_entry_id, project_id=project_id).authority_badge

    def get_safe_preview(
        self,
        artifact_entry_id: str,
        *,
        project_id: str | None = None,
    ) -> ProductArtifactSafePreview:
        return self.get_entry(artifact_entry_id, project_id=project_id).safe_preview

    def get_safety_summary(
        self,
        artifact_entry_id: str,
        *,
        project_id: str | None = None,
    ) -> ProductArtifactSafetySummary:
        return self.get_entry(artifact_entry_id, project_id=project_id).safety_summary

    def final_story_package_views(
        self,
        *,
        project_id: str | None = None,
    ) -> FinalStoryPackageProductViewListResponse:
        self._assert_active_story_data_available(project_id)
        effective_project_id = self._effective_project_id(project_id)
        snapshots = self._filter_project(
            self._read_records(FINAL_STORY_PACKAGE_SNAPSHOTS_FILE, project_id=effective_project_id),
            effective_project_id,
        )
        snapshots.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        safety_by_snapshot = {
            item.get("snapshot_id", ""): item
            for item in self._read_records(FINAL_STORY_PACKAGE_SAFETY_AUDITS_FILE, project_id=effective_project_id)
            if item.get("snapshot_id")
        }
        sections_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        for section in self._read_records(FINAL_STORY_PACKAGE_PREVIEW_SECTIONS_FILE, project_id=effective_project_id):
            sections_by_snapshot.setdefault(section.get("snapshot_id", ""), []).append(section)
        evidence_by_snapshot = {
            item.get("snapshot_id", ""): item
            for item in self._read_records(FINAL_STORY_PACKAGE_EVIDENCE_INDEXES_FILE, project_id=effective_project_id)
            if item.get("snapshot_id")
        }

        views: list[FinalStoryPackageProductView] = []
        for snapshot in snapshots:
            snapshot_id = str(snapshot.get("snapshot_id") or "")
            sections = sections_by_snapshot.get(snapshot_id, [])
            evidence = evidence_by_snapshot.get(snapshot_id, {})
            audit = safety_by_snapshot.get(snapshot_id)
            source_ref_ids = self._string_list(snapshot.get("source_ref_ids"))
            preview = self._safe_preview(
                title=f"最终故事包 {snapshot_id or '未命名'}",
                excerpt=snapshot.get("safe_summary", ""),
                counts={
                    "sections": len(sections),
                    "preview_sections": len(sections),
                    "source_refs": len(source_ref_ids),
                    "source_versions": len(self._string_list(snapshot.get("source_version_ids"))),
                    "known_residuals": len(self._string_list(snapshot.get("known_residual_codes"))),
                    "complete_story_chars": int(snapshot.get("complete_story_text_char_count") or 0),
                },
                metadata={
                    "snapshot_id": snapshot_id,
                    "package_type": snapshot.get("package_type", ""),
                    "readiness_status": snapshot.get("readiness_status", ""),
                    "content_schema_version": snapshot.get("content_schema_version", ""),
                },
                source_ref_ids=source_ref_ids[:20],
                content_hash=snapshot.get("complete_story_text_hash", ""),
            )
            views.append(
                FinalStoryPackageProductView(
                    view_id=self._entry_id("final_story_package", snapshot_id),
                    snapshot_id=snapshot_id,
                    project_id=str(snapshot.get("project_id") or ""),
                    display_title=f"最终故事包 {snapshot_id or '未命名'}",
                    display_status=str(snapshot.get("snapshot_status") or snapshot.get("readiness_status") or "unknown"),
                    authority_badge=self._final_package_badge(snapshot),
                    safe_preview=preview,
                    safety_summary=self._safety_from_final_audit(audit),
                    section_count=len(sections),
                    evidence_ref_count=len(self._string_list(evidence.get("source_ref_ids"))),
                    source_version_count=len(self._string_list(snapshot.get("source_version_ids"))),
                    known_residual_codes=self._string_list(snapshot.get("known_residual_codes")),
                    can_be_used_by_plugins=bool(snapshot.get("can_be_used_by_plugins")),
                    safe_summary="最终故事包产品视图只展示受控摘要和引用。",
                )
            )
        return FinalStoryPackageProductViewListResponse(
            views=views,
            total_count=len(views),
            safe_summary="最终故事包产品视图已隔离调试数据。",
        )

    def get_final_story_package_view(
        self,
        view_id: str,
        *,
        project_id: str | None = None,
    ) -> FinalStoryPackageProductView:
        for view in self.final_story_package_views(project_id=project_id).views:
            if view.view_id == view_id:
                return view
        raise ProductArtifactNotFound(f"FINAL_STORY_PACKAGE_PRODUCT_VIEW_NOT_FOUND:{view_id}")

    def plugin_output_views(
        self,
        *,
        project_id: str | None = None,
    ) -> PluginOutputProductViewListResponse:
        self._assert_active_story_data_available(project_id)
        effective_project_id = self._effective_project_id(project_id)
        artifacts = self._filter_project(
            self._read_records(PLUGIN_OUTPUT_ARTIFACTS_FILE, project_id=effective_project_id),
            effective_project_id,
        )
        versions_by_artifact: dict[str, list[dict[str, Any]]] = {}
        for version in self._read_records(PLUGIN_OUTPUT_ARTIFACT_VERSIONS_FILE, project_id=effective_project_id):
            versions_by_artifact.setdefault(version.get("artifact_id", ""), []).append(version)
        safety_by_run = {
            item.get("plugin_run_id", ""): item
            for item in self._read_records(PLUGIN_RUN_SAFETY_REPORTS_FILE, project_id=effective_project_id)
            if item.get("plugin_run_id")
        }

        views: list[PluginOutputProductView] = []
        for artifact in artifacts:
            artifact_id = str(artifact.get("artifact_id") or "")
            versions = sorted(
                versions_by_artifact.get(artifact_id, []),
                key=lambda item: int(item.get("version_number") or 0),
                reverse=True,
            )
            current_version = self._find_current_version(artifact, versions)
            preview = self._safe_preview(
                title=str(artifact.get("safe_title") or f"插件成果 {artifact_id}"),
                excerpt=current_version.get("safe_preview") or artifact.get("safe_summary", ""),
                counts={"versions": len(versions), "warnings": len(self._string_list(artifact.get("warnings")))},
                metadata={
                    "artifact_id": artifact_id,
                    "artifact_type": artifact.get("artifact_type", ""),
                    "plugin_id": artifact.get("plugin_id", ""),
                    "plugin_run_id": artifact.get("plugin_run_id", ""),
                },
                source_ref_ids=[item for item in [artifact.get("source_package_snapshot_id"), artifact.get("source_manifest_id")] if item],
                content_hash=current_version.get("content_hash", ""),
            )
            views.append(
                PluginOutputProductView(
                    view_id=self._entry_id("plugin_output", artifact_id),
                    artifact_id=artifact_id,
                    project_id=str(artifact.get("project_id") or ""),
                    plugin_run_id=str(artifact.get("plugin_run_id") or ""),
                    plugin_id=str(artifact.get("plugin_id") or ""),
                    artifact_type=str(artifact.get("artifact_type") or "plugin_output"),
                    display_title=str(artifact.get("safe_title") or f"插件成果 {artifact_id}"),
                    display_status=str(artifact.get("artifact_status") or "unknown"),
                    current_version_id=str(artifact.get("current_version_id") or current_version.get("artifact_version_id") or ""),
                    version_count=len(versions),
                    source_package_snapshot_id=str(artifact.get("source_package_snapshot_id") or ""),
                    authority_badge=self._derivative_badge("plugin_output"),
                    safe_preview=preview,
                    safety_summary=self._safety_from_plugin_report(safety_by_run.get(artifact.get("plugin_run_id", ""))),
                    safe_summary="插件输出产品视图只展示派生成果摘要，不应用回源故事。",
                )
            )
        return PluginOutputProductViewListResponse(
            views=views,
            total_count=len(views),
            safe_summary="插件输出产品视图已隔离调试数据。",
        )

    def get_plugin_output_view(self, view_id: str, *, project_id: str | None = None) -> PluginOutputProductView:
        for view in self.plugin_output_views(project_id=project_id).views:
            if view.view_id == view_id:
                return view
        raise ProductArtifactNotFound(f"PLUGIN_OUTPUT_PRODUCT_VIEW_NOT_FOUND:{view_id}")

    def _screenplay_entries(self, *, project_id: str | None) -> list[ProductArtifactEntry]:
        rows = self._filter_project(self._read_records(SCREENPLAY_DRAFT_ARTIFACTS_FILE, project_id=project_id), project_id)
        safety_by_run = self._safety_reports_by_run(project_id=project_id)
        entries: list[ProductArtifactEntry] = []
        for row in rows:
            ref_id = str(row.get("screenplay_draft_id") or "")
            unit_count = len(row.get("script_units") if isinstance(row.get("script_units"), list) else [])
            entries.append(
                self._derivative_entry(
                    category="screenplay_draft",
                    kind="screenplay_draft",
                    ref_id=ref_id,
                    project_id=str(row.get("project_id") or ""),
                    title=f"剧本草稿 {ref_id or '未命名'}",
                    status=str(row.get("draft_status") or "unknown"),
                    preview=self._safe_preview(
                        title=f"剧本草稿 {ref_id or '未命名'}",
                        excerpt=row.get("safe_summary", ""),
                        counts={"script_units": unit_count, "warnings": len(self._string_list(row.get("warnings")))},
                        metadata={
                            "screenplay_draft_id": ref_id,
                            "plugin_run_id": row.get("plugin_run_id", ""),
                            "snapshot_id": row.get("final_story_package_snapshot_id", ""),
                        },
                        source_ref_ids=[item for item in [row.get("final_story_package_snapshot_id"), row.get("plugin_output_artifact_id")] if item],
                    ),
                    safety=self._safety_from_plugin_report(safety_by_run.get(row.get("plugin_run_id", ""))),
                    source_refs=[item for item in [row.get("final_story_package_snapshot_id"), row.get("plugin_output_artifact_id")] if item],
                    warnings=self._string_list(row.get("warnings")),
                )
            )
        return entries

    def _storyboard_entries(self, *, project_id: str | None) -> list[ProductArtifactEntry]:
        rows = self._filter_project(self._read_records(STORYBOARD_PACKAGES_FILE, project_id=project_id), project_id)
        safety_by_run = self._safety_reports_by_run(project_id=project_id)
        entries: list[ProductArtifactEntry] = []
        for row in rows:
            ref_id = str(row.get("storyboard_package_id") or "")
            entries.append(
                self._derivative_entry(
                    category="storyboard_package",
                    kind="storyboard_package",
                    ref_id=ref_id,
                    project_id=str(row.get("project_id") or ""),
                    title=f"分镜包 {ref_id or '未命名'}",
                    status=str(row.get("package_status") or "unknown"),
                    preview=self._safe_preview(
                        title=f"分镜包 {ref_id or '未命名'}",
                        excerpt=row.get("safe_summary", ""),
                        counts={
                            "key_storyboards": len(self._string_list(row.get("key_storyboard_artifact_ids"))),
                            "scene_storyboards": len(self._string_list(row.get("scene_storyboard_artifact_ids"))),
                            "warnings": len(self._string_list(row.get("warnings"))),
                        },
                        metadata={
                            "storyboard_package_id": ref_id,
                            "plugin_run_id": row.get("plugin_run_id", ""),
                            "snapshot_id": row.get("final_story_package_snapshot_id", ""),
                        },
                        source_ref_ids=[item for item in [row.get("final_story_package_snapshot_id"), row.get("source_screenplay_draft_artifact_id")] if item],
                    ),
                    safety=self._safety_from_plugin_report(safety_by_run.get(row.get("plugin_run_id", ""))),
                    source_refs=[item for item in [row.get("final_story_package_snapshot_id"), row.get("source_screenplay_draft_artifact_id")] if item],
                    warnings=self._string_list(row.get("warnings")),
                )
            )
        return entries

    def _digital_asset_entries(self, *, project_id: str | None) -> list[ProductArtifactEntry]:
        rows = self._filter_project(self._read_records(DIGITAL_ASSET_PACKAGES_FILE, project_id=project_id), project_id)
        safety_by_run = self._safety_reports_by_run(project_id=project_id)
        entries: list[ProductArtifactEntry] = []
        for row in rows:
            ref_id = str(row.get("digital_asset_package_id") or "")
            entries.append(
                self._derivative_entry(
                    category="digital_asset_package",
                    kind="digital_asset_package",
                    ref_id=ref_id,
                    project_id=str(row.get("project_id") or ""),
                    title=f"数字资产包 {ref_id or '未命名'}",
                    status=str(row.get("package_status") or "unknown"),
                    preview=self._safe_preview(
                        title=f"数字资产包 {ref_id or '未命名'}",
                        excerpt=row.get("safe_summary", ""),
                        counts={
                            "asset_lists": len(
                                [
                                    item
                                    for item in [
                                        row.get("character_asset_list_id"),
                                        row.get("location_asset_list_id"),
                                        row.get("prop_asset_list_id"),
                                        row.get("motif_asset_list_id"),
                                        row.get("costume_continuity_list_id"),
                                    ]
                                    if item
                                ]
                            ),
                            "warnings": len(self._string_list(row.get("warnings"))),
                        },
                        metadata={
                            "digital_asset_package_id": ref_id,
                            "plugin_run_id": row.get("plugin_run_id", ""),
                            "snapshot_id": row.get("final_story_package_snapshot_id", ""),
                        },
                        source_ref_ids=[item for item in [row.get("final_story_package_snapshot_id"), row.get("source_storyboard_package_id")] if item],
                    ),
                    safety=self._safety_from_plugin_report(safety_by_run.get(row.get("plugin_run_id", ""))),
                    source_refs=[item for item in [row.get("final_story_package_snapshot_id"), row.get("source_storyboard_package_id")] if item],
                    warnings=self._string_list(row.get("warnings")),
                )
            )
        return entries

    def _entry_from_final_view(self, view: FinalStoryPackageProductView) -> ProductArtifactEntry:
        return ProductArtifactEntry(
            artifact_entry_id=view.view_id,
            project_id=view.project_id,
            artifact_category="final_story_package",
            artifact_kind="snapshot",
            artifact_ref_id=view.snapshot_id,
            display_title=view.display_title,
            display_status=view.display_status,
            authority_badge=view.authority_badge,
            safe_preview=view.safe_preview,
            safety_summary=view.safety_summary,
            source_authority_refs=view.safe_preview.source_ref_ids,
            is_derivative_artifact=False,
            can_open_controlled_product_view=True,
            safe_summary=view.safe_summary,
        )

    def _entry_from_plugin_view(self, view: PluginOutputProductView) -> ProductArtifactEntry:
        return ProductArtifactEntry(
            artifact_entry_id=view.view_id,
            project_id=view.project_id,
            artifact_category="plugin_output",
            artifact_kind=view.artifact_type,
            artifact_ref_id=view.artifact_id,
            display_title=view.display_title,
            display_status=view.display_status,
            authority_badge=view.authority_badge,
            safe_preview=view.safe_preview,
            safety_summary=view.safety_summary,
            source_authority_refs=view.safe_preview.source_ref_ids,
            is_derivative_artifact=True,
            can_open_controlled_product_view=True,
            safe_summary=view.safe_summary,
        )

    def _derivative_entry(
        self,
        *,
        category: str,
        kind: str,
        ref_id: str,
        project_id: str,
        title: str,
        status: str,
        preview: ProductArtifactSafePreview,
        safety: ProductArtifactSafetySummary,
        source_refs: list[str],
        warnings: list[str],
    ) -> ProductArtifactEntry:
        return ProductArtifactEntry(
            artifact_entry_id=self._entry_id(category, ref_id),
            project_id=project_id,
            artifact_category=category,
            artifact_kind=kind,
            artifact_ref_id=ref_id,
            display_title=title,
            display_status=status,
            authority_badge=self._derivative_badge(category),
            safe_preview=preview,
            safety_summary=safety,
            source_authority_refs=source_refs,
            is_derivative_artifact=True,
            can_open_controlled_product_view=True,
            warnings=warnings,
            safe_summary="派生产物条目只展示安全摘要，不写回源故事。",
        )

    def _final_package_badge(self, snapshot: dict[str, Any]) -> ProductArtifactAuthorityBadge:
        return ProductArtifactAuthorityBadge(
            authority_kind="final_story_package_snapshot",
            authority_label="最终故事包快照",
            authority_scope=str(snapshot.get("snapshot_id") or ""),
            not_source_story_fact=True,
            is_plugin_input_authority=bool(snapshot.get("can_be_used_by_plugins")),
            is_derivative_output=False,
            safe_summary="该快照可作为插件输入边界，但产品视图本身不写入故事。",
        )

    def _derivative_badge(self, category: str) -> ProductArtifactAuthorityBadge:
        labels = {
            "plugin_output": "插件派生成果",
            "screenplay_draft": "剧本派生成果",
            "storyboard_package": "分镜派生成果",
            "digital_asset_package": "资产派生成果",
        }
        return ProductArtifactAuthorityBadge(
            authority_kind=category,
            authority_label=labels.get(category, "派生成果"),
            authority_scope="artifact_output_only",
            not_source_story_fact=True,
            is_plugin_input_authority=False,
            is_derivative_output=True,
            safe_summary="该成果是派生输出，不是源故事事实。",
        )

    def _safety_from_final_audit(self, audit: dict[str, Any] | None) -> ProductArtifactSafetySummary:
        if not audit:
            return ProductArtifactSafetySummary(
                passed=False,
                warning_codes=["safety_audit_missing"],
                safe_summary="未找到对应安全审计，只允许只读查看摘要。",
            )
        return ProductArtifactSafetySummary(
            passed=bool(audit.get("passed")),
            blocking_codes=self._string_list(audit.get("blocking_findings")),
            warning_codes=self._string_list(audit.get("warning_findings")),
            residual_risks=self._string_list(audit.get("residual_risks")),
            no_source_story_write=bool(audit.get("forbidden_story_fact_files_unchanged", True)),
            no_final_package_mutation=True,
            no_plugin_output_mutation=bool(audit.get("forbidden_plugin_runtime_files_absent", True)),
            safe_summary=self._safe_text(audit.get("safe_summary", "")) or "最终故事包安全审计摘要。",
        )

    def _safety_from_plugin_report(self, report: dict[str, Any] | None) -> ProductArtifactSafetySummary:
        if not report:
            return ProductArtifactSafetySummary(
                passed=False,
                warning_codes=["plugin_safety_report_missing"],
                safe_summary="未找到对应插件安全报告，只允许只读查看摘要。",
            )
        return ProductArtifactSafetySummary(
            passed=bool(report.get("passed")),
            blocking_codes=self._string_list(report.get("violations")),
            warning_codes=self._string_list(report.get("warnings")),
            no_source_story_write=all(
                bool(report.get(field, True))
                for field in [
                    "no_scene_prose_write",
                    "no_event_write",
                    "no_memory_record_write",
                    "no_state_change_write",
                    "no_chapter_archive_write",
                    "no_narrative_debt_write",
                    "no_story_bible_write",
                ]
            ),
            no_final_package_mutation=bool(report.get("no_final_story_package_mutation", True)),
            no_plugin_output_mutation=True,
            safe_summary=self._safe_text(report.get("safe_summary", "")) or "插件安全报告摘要。",
        )

    def _safe_preview(
        self,
        *,
        title: str,
        excerpt: Any,
        counts: dict[str, int],
        metadata: dict[str, Any],
        source_ref_ids: list[str] | None = None,
        content_hash: str = "",
    ) -> ProductArtifactSafePreview:
        safe_title = self._safe_text(title, limit=120)
        safe_excerpt = self._safe_text(excerpt, limit=360)
        safe_metadata = {
            str(key): self._safe_scalar(value)
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        return ProductArtifactSafePreview(
            safe_title=safe_title,
            safe_excerpt=safe_excerpt,
            metadata=safe_metadata,
            counts=counts,
            source_ref_ids=self._string_list(source_ref_ids)[:20],
            content_hash=self._safe_text(content_hash, limit=128),
            bounded_char_count=len(safe_excerpt),
            safe_summary="安全预览只包含摘要、计数和引用。",
        )

    def _find_current_version(
        self,
        artifact: dict[str, Any],
        versions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        current_version_id = artifact.get("current_version_id")
        for version in versions:
            if version.get("artifact_version_id") == current_version_id:
                return version
        return versions[0] if versions else {}

    def _safety_reports_by_run(self, *, project_id: str | None) -> dict[str, dict[str, Any]]:
        return {
            item.get("plugin_run_id", ""): item
            for item in self._read_records(PLUGIN_RUN_SAFETY_REPORTS_FILE, project_id=project_id)
            if item.get("plugin_run_id")
        }

    def _read_records(self, file_name: str, *, project_id: str | None = None) -> list[dict[str, Any]]:
        path = self._records_dir_for_project(project_id) / file_name
        if not self.store.exists(path):
            return []
        try:
            payload = self.store.read_any(path)
        except StorageError as exc:
            raise StorageError(f"PRODUCT_ARTIFACT_STORAGE_INVALID:{file_name}") from exc
        rows: list[Any]
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            list_values = [value for value in payload.values() if isinstance(value, list)]
            rows = list_values[0] if list_values else [payload]
        else:
            raise StorageError(f"PRODUCT_ARTIFACT_STORAGE_SHAPE_INVALID:{file_name}")
        return [row for row in rows if isinstance(row, dict)]

    def _filter_project(self, rows: list[dict[str, Any]], project_id: str | None) -> list[dict[str, Any]]:
        if not project_id:
            return []
        return [row for row in rows if str(row.get("project_id") or "") == project_id]

    def _effective_project_id(self, project_id: str | None) -> str | None:
        if project_id:
            return project_id
        self._resolve_workspace()
        return self.project_id or None

    def _records_dir_for_project(self, project_id: str | None) -> Path:
        self._resolve_workspace()
        if self._explicit_data_dir or not project_id:
            return self.data_dir
        return story_data_dir_for_project(project_id, settings.data_dir)

    def _assert_active_story_data_available(self, project_id: str | None = None) -> None:
        if project_id:
            return
        self._resolve_workspace()
        if self._missing_active_project_id:
            safe_project_id = self._safe_text(self._missing_active_project_id, limit=96) or "unknown"
            raise StorageError(f"ACTIVE_PROJECT_STORY_DATA_NOT_FOUND:{safe_project_id}")

    def _resolve_workspace(self) -> None:
        if self._workspace_resolved:
            return
        if self._explicit_data_dir:
            self.data_dir = self._base_data_dir
            self._missing_active_project_id = ""
        else:
            active_dir = active_project_story_data_dir(self.store, settings.data_dir)
            self.data_dir = active_dir or settings.data_dir
            self._missing_active_project_id = "" if active_dir else active_project_without_story_data(
                self.store,
                settings.data_dir,
            )
        self._project_id = current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback="local_project",
        )
        self._workspace_resolved = True

    def _string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._safe_text(item, limit=160) for item in value if self._safe_text(item, limit=160)]
        safe = self._safe_text(value, limit=160)
        return [safe] if safe else []

    def _safe_scalar(self, value: Any) -> Any:
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return self._safe_text(value, limit=160)

    def _safe_text(self, value: Any, *, limit: int = 360) -> str:
        if value is None:
            return ""
        text = value if isinstance(value, str) else json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
        lowered = text.lower()
        if SECRET_LIKE_RE.search(text) or any(marker in lowered for marker in UNSAFE_VALUE_MARKERS):
            return "[redacted]"
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 3)]}..."

    def _entry_id(self, category: str, ref_id: str) -> str:
        safe_ref = re.sub(r"[^a-zA-Z0-9_\-]+", "_", ref_id or "unknown").strip("_")
        return f"artifact_entry_{category}_{safe_ref or 'unknown'}"
