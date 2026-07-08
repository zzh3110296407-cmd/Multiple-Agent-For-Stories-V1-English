from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import AdvisoryAuthority


class HandoffArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_input_manifest: str = ""
    canonical_chapters_root: str = ""
    full_book_bundle: str = ""
    major_arcs: str = ""
    sub_arcs: str = ""
    foreshadowing_tracker: str = ""
    mystery_tracker: str = ""
    relationship_debt_tracker: str = ""
    world_rule_reveal_tracker: str = ""
    tracker_override_log: str = ""
    tracker_edit_report: str = ""
    tracker_edit_report_markdown: str = ""
    tracker_semantic_recommendation_report: str = ""
    chapter_modules: str = ""
    arc_modules: str = ""
    book_modules: str = ""
    module_catalog: str = ""
    module_conflict_report: str = ""
    book_framework_package: str = ""
    quality_report: str = ""
    validation_summary: str = ""
    checksums: str = ""


class GeneratorCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supports_original_writing: bool = True
    supports_continuation_or_revision: bool = True
    supports_hybrid_adaptation: bool = True
    requires_profile_compilation: bool = True
    requires_user_confirmation_before_formal_write: bool = True


class HandoffPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "story_analyzer_handoff.v1"
    contract_version: str = "story_generator_import.v1"
    source: str = "analyze_stories"
    authority: AdvisoryAuthority = AdvisoryAuthority.ADVISORY_ONLY
    can_write_formal_state: bool = False
    work_title: str = ""
    run_id: str = ""
    artifacts: HandoffArtifacts = Field(default_factory=HandoffArtifacts)
    generator_capabilities: GeneratorCapabilities = Field(default_factory=GeneratorCapabilities)
