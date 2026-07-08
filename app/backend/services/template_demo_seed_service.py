import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.project_creation import (
    DemoSeedProfile,
    ProjectCreationDecision,
    ProjectCreationRequest,
    ProjectOriginMetadata,
)
from app.backend.models.template_demo_seed import (
    CreateTemplateInstantiationRequest,
    DemoSeedIsolationAudit,
    DemoSeedRunRecord,
    ProjectOriginBadge,
    ProjectTemplate,
    ProjectTemplatesResponse,
    RunDemoSeedRequest,
    TemplateDemoSeedSafetyScanReport,
    TemplateInstantiationReport,
    TemplateInstantiationRequest,
    TemplateInstantiationValidationReport,
)
from app.backend.services.model_runtime_log_service import utc_now
from app.backend.services.project_creation_service import (
    ProjectCreationService,
    model_to_dict,
)
from app.backend.storage.json_store import JsonStore, StorageError


PROJECT_TEMPLATES_FILE = "project_templates.json"
TEMPLATE_INSTANTIATION_REQUESTS_FILE = "template_instantiation_requests.json"
TEMPLATE_INSTANTIATION_VALIDATION_REPORTS_FILE = (
    "template_instantiation_validation_reports.json"
)
TEMPLATE_INSTANTIATION_REPORTS_FILE = "template_instantiation_reports.json"
DEMO_SEED_RUNS_FILE = "demo_seed_runs.json"
DEMO_SEED_ISOLATION_AUDITS_FILE = "demo_seed_isolation_audits.json"
PROJECT_ORIGIN_BADGES_FILE = "project_origin_badges.json"

STORY_FACT_AND_ARTIFACT_FILES = [
    "story_bible.json",
    "world_canvas.json",
    "characters.json",
    "relationships.json",
    "framework.json",
    "chapters.json",
    "scenes.json",
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "final_story_package_snapshots.json",
    "plugin_output_artifacts.json",
    "plugin_output_artifact_versions.json",
]

SECRET_LIKE_RE = re.compile(
    r"(?<![A-Za-z])sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_\-]{8,}|(?i:bearer\s+[A-Za-z0-9._\-]{8,})|(?i:authorization\s*:)"
)
UNSAFE_VALUE_MARKERS = (
    "api_key_ref",
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
    "provider_payload",
    "provider payload",
    "provider_response",
    "provider response",
    "authorization:",
    "bearer ",
)


class TemplateDemoSeedError(RuntimeError):
    """Base error for Phase 8 M4 template/demo operations."""


class TemplateDemoSeedNotFound(TemplateDemoSeedError):
    """Raised when an M4 record cannot be found."""


class TemplateDemoSeedBlocked(TemplateDemoSeedError):
    """Raised when M4 origin or isolation rules block an operation."""


class TemplateDemoSeedSafetyError(TemplateDemoSeedError):
    """Raised when M4 safety scanning rejects a payload."""


class TemplateDemoSeedService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        project_creation_service: ProjectCreationService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.project_creation_service = project_creation_service or ProjectCreationService(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.project_templates_file = self.data_dir / PROJECT_TEMPLATES_FILE
        self.template_requests_file = self.data_dir / TEMPLATE_INSTANTIATION_REQUESTS_FILE
        self.template_validation_reports_file = (
            self.data_dir / TEMPLATE_INSTANTIATION_VALIDATION_REPORTS_FILE
        )
        self.template_reports_file = self.data_dir / TEMPLATE_INSTANTIATION_REPORTS_FILE
        self.demo_seed_runs_file = self.data_dir / DEMO_SEED_RUNS_FILE
        self.demo_seed_audits_file = self.data_dir / DEMO_SEED_ISOLATION_AUDITS_FILE
        self.project_origin_badges_file = self.data_dir / PROJECT_ORIGIN_BADGES_FILE

    def list_templates(self) -> ProjectTemplatesResponse:
        return ProjectTemplatesResponse(templates=self._templates_or_seed_defaults())

    def get_template(self, template_id: str) -> ProjectTemplate:
        for template in self._templates_or_seed_defaults():
            if template.template_id == template_id:
                return template
        raise TemplateDemoSeedNotFound(f"Project template not found: {template_id}")

    def create_template_instantiation_request(
        self,
        template_id: str,
        payload: CreateTemplateInstantiationRequest,
    ) -> TemplateInstantiationRequest:
        self._guard_safe_payload(model_to_dict(payload))
        template = self.get_template(template_id)
        self._assert_template_hard_rules(template)
        origin = self._template_origin_or_block(payload.project_id, template_id)
        creation_request = self._resolve_creation_request(
            payload.creation_request_id,
            project_id=payload.project_id,
            expected_mode_type="template_project",
            expected_ref=template_id,
        )
        creation_decision = self._resolve_creation_decision(
            payload.creation_decision_id,
            project_id=payload.project_id,
            creation_request_id=creation_request.creation_request_id if creation_request else None,
        )
        if creation_decision and not creation_decision.does_not_confirm_story_facts:
            raise TemplateDemoSeedBlocked("template_project_decision_confirmed_story_facts")

        now = utc_now()
        request = TemplateInstantiationRequest(
            template_instantiation_request_id=f"template_instantiation_request_{uuid4().hex[:12]}",
            project_id=payload.project_id,
            creation_request_id=creation_request.creation_request_id if creation_request else None,
            creation_decision_id=(
                creation_decision.creation_decision_id if creation_decision else None
            ),
            project_origin_metadata_id=origin.origin_metadata_id,
            template_id=template.template_id,
            template_version_id=template.template_version_id,
            target_workspace=self._safe_workspace(payload.target_workspace),
            request_status="created",
            explicit_user_selection=True,
            safe_user_note=self._safe_note(payload.safe_user_note),
            safe_summary=(
                "Template instantiation request records starter intent only; "
                "no story facts are written."
            ),
            warnings=self._dedupe(origin.warnings),
            created_at=now,
            updated_at=now,
        )
        records = self._read_template_requests()
        records.append(request)
        self._write_template_requests(records)
        return request

    def get_template_instantiation_request(
        self,
        request_id: str,
    ) -> TemplateInstantiationRequest:
        return self._get_template_request(request_id)

    def validate_template_instantiation(
        self,
        request_id: str,
    ) -> TemplateInstantiationValidationReport:
        request = self._get_template_request(request_id)
        template = self.get_template(request.template_id)
        origin = self.project_creation_service.get_project_origin(request.project_id)
        blocking: list[str] = []
        project_origin_present = origin.origin_type != "unknown_origin"
        origin_type_is_template = origin.origin_type == "template"
        template_id_matches_origin = origin.template_id == request.template_id
        template_is_enabled = template.template_status == "enabled"
        template_is_not_demo_material = not template.is_demo_material
        template_source_is_safe = template.source_type in {
            "built_in_safe_template",
            "phase8_m4_builtin",
        } and template.license_status in {"built_in_safe", "safe_to_use"}
        no_full_story_prose = not template.contains_full_story_prose
        no_full_screenplay_text = not template.contains_full_screenplay_text
        no_user_private_content = not template.contains_user_private_content
        requires_downstream_confirmation = template.requires_downstream_confirmation
        will_not_write_story_facts = not template.creates_story_facts_now

        checks = {
            "project_origin_metadata_missing": project_origin_present,
            "origin_type_is_not_template": origin_type_is_template,
            "template_id_does_not_match_origin": template_id_matches_origin,
            "template_is_not_enabled": template_is_enabled,
            "template_is_demo_material": template_is_not_demo_material,
            "template_source_is_not_safe": template_source_is_safe,
            "template_contains_full_story_prose": no_full_story_prose,
            "template_contains_full_screenplay_text": no_full_screenplay_text,
            "template_contains_user_private_content": no_user_private_content,
            "template_would_write_story_facts": will_not_write_story_facts,
            "template_does_not_require_downstream_confirmation": requires_downstream_confirmation,
        }
        blocking.extend(code for code, passed in checks.items() if not passed)
        can_instantiate = len(blocking) == 0
        report = TemplateInstantiationValidationReport(
            template_instantiation_validation_report_id=f"template_instantiation_validation_{uuid4().hex[:12]}",
            template_instantiation_request_id=request.template_instantiation_request_id,
            project_id=request.project_id,
            template_id=request.template_id,
            validation_status="passed" if can_instantiate else "blocked",
            can_instantiate=can_instantiate,
            project_origin_metadata_present=project_origin_present,
            origin_type_is_template=origin_type_is_template,
            template_id_matches_origin=template_id_matches_origin,
            template_is_enabled=template_is_enabled,
            template_is_not_demo_material=template_is_not_demo_material,
            template_source_is_safe=template_source_is_safe,
            no_full_story_prose=no_full_story_prose,
            no_full_screenplay_text=no_full_screenplay_text,
            no_user_private_content=no_user_private_content,
            will_not_write_story_facts=will_not_write_story_facts,
            requires_downstream_confirmation=requires_downstream_confirmation,
            blocking_issues=blocking,
            warnings=self._dedupe(request.warnings + template.warnings),
            safe_summary=(
                "Template instantiation is eligible for starter handoff only."
                if can_instantiate
                else f"Template instantiation blocked by {len(blocking)} issue(s)."
            ),
            created_at=utc_now(),
        )
        records = self._read_template_validation_reports()
        records.append(report)
        self._write_template_validation_reports(records)
        self._update_template_request_validation(
            request.template_instantiation_request_id,
            report.template_instantiation_validation_report_id,
            "validated" if can_instantiate else "blocked",
        )
        return report

    def instantiate_template(self, request_id: str) -> TemplateInstantiationReport:
        request = self._get_template_request(request_id)
        validation = self._latest_template_validation(request_id)
        if validation is None:
            validation = self.validate_template_instantiation(request_id)
        if not validation.can_instantiate or validation.blocking_issues:
            raise TemplateDemoSeedBlocked("; ".join(validation.blocking_issues))
        template = self.get_template(request.template_id)
        self._assert_template_hard_rules(template)
        self._template_origin_or_block(request.project_id, request.template_id)

        now = utc_now()
        report = TemplateInstantiationReport(
            template_instantiation_report_id=f"template_instantiation_report_{uuid4().hex[:12]}",
            template_instantiation_request_id=request.template_instantiation_request_id,
            project_id=request.project_id,
            project_origin_metadata_id=request.project_origin_metadata_id,
            template_id=template.template_id,
            template_version_id=template.template_version_id,
            report_status="created",
            starter_material_refs=list(template.starter_material_refs),
            safe_template_preview=template.safe_preview,
            target_workspace=request.target_workspace,
            handoff_status="requires_downstream_confirmation",
            creates_user_owned_story_facts_now=False,
            requires_downstream_confirmation=True,
            wrote_confirmed_world_canvas=False,
            wrote_confirmed_character=False,
            wrote_active_framework=False,
            wrote_chapter_plan=False,
            wrote_scene_event_memory_state=False,
            wrote_final_story_package=False,
            wrote_plugin_output_artifact=False,
            safe_summary=(
                "Template starter refs and handoff metadata created; downstream "
                "workspace confirmation is still required."
            ),
            warnings=self._dedupe(request.warnings + template.warnings),
            created_at=now,
            updated_at=now,
        )
        self._assert_template_report_no_writes(report)
        records = self._read_template_reports()
        records.append(report)
        self._write_template_reports(records)
        self._update_template_request_status(request_id, "instantiated")
        return report

    def get_template_instantiation_report(
        self,
        report_id: str,
    ) -> TemplateInstantiationReport:
        for record in self._read_template_reports():
            if record.template_instantiation_report_id == report_id:
                return record
        raise TemplateDemoSeedNotFound(f"Template instantiation report not found: {report_id}")

    def list_demo_seed_profiles(self) -> list[DemoSeedProfile]:
        return self.project_creation_service.list_demo_seed_profiles().demo_seed_profiles

    def get_demo_seed_profile(self, demo_seed_id: str) -> DemoSeedProfile:
        for profile in self.list_demo_seed_profiles():
            if profile.demo_seed_id == demo_seed_id:
                return profile
        raise TemplateDemoSeedNotFound(f"Demo seed profile not found: {demo_seed_id}")

    def run_demo_seed(
        self,
        demo_seed_id: str,
        payload: RunDemoSeedRequest,
    ) -> DemoSeedRunRecord:
        self._guard_safe_payload(model_to_dict(payload))
        if not payload.explicit_user_selection:
            raise TemplateDemoSeedBlocked("demo_seed_requires_explicit_user_selection")
        profile = self.get_demo_seed_profile(demo_seed_id)
        self._assert_demo_seed_profile_hard_rules(profile)
        origin = self._demo_origin_or_block(payload.project_id, demo_seed_id)
        if not origin.explicit_user_selection_recorded:
            raise TemplateDemoSeedBlocked("demo_seed_origin_missing_explicit_selection")

        creation_request = self._resolve_creation_request(
            payload.creation_request_id,
            project_id=payload.project_id,
            expected_mode_type="demo_seed_project",
            expected_ref=demo_seed_id,
        )
        creation_decision = self._resolve_creation_decision(
            payload.creation_decision_id,
            project_id=payload.project_id,
            creation_request_id=creation_request.creation_request_id if creation_request else None,
        )
        if creation_decision and not creation_decision.confirms_demo_seed_if_any:
            raise TemplateDemoSeedBlocked("demo_seed_creation_decision_not_confirmed")

        now = utc_now()
        run = DemoSeedRunRecord(
            demo_seed_run_id=f"demo_seed_run_{uuid4().hex[:12]}",
            project_id=payload.project_id,
            creation_request_id=creation_request.creation_request_id if creation_request else None,
            creation_decision_id=(
                creation_decision.creation_decision_id if creation_decision else None
            ),
            project_origin_metadata_id=origin.origin_metadata_id,
            demo_seed_id=profile.demo_seed_id,
            run_status="created",
            explicit_user_selection_verified=True,
            demo_marker=profile.required_marker,
            is_demo_project=True,
            creates_demo_project_only=True,
            writes_real_project_storage=False,
            created_demo_storage_ref=f"{DEMO_SEED_RUNS_FILE}:{profile.demo_seed_id}",
            copied_to_real_project=False,
            demo_to_real_conversion_blocked=True,
            safe_summary="Demo seed run records demo-only evidence and writes no real project storage.",
            warnings=self._dedupe(origin.warnings + profile.warnings),
            created_at=now,
            updated_at=now,
        )
        self._assert_demo_run_hard_rules(run)
        records = self._read_demo_seed_runs()
        records.append(run)
        self._write_demo_seed_runs(records)
        return run

    def get_demo_seed_run(self, run_id: str) -> DemoSeedRunRecord:
        return self._get_demo_seed_run(run_id)

    def create_demo_seed_isolation_audit(
        self,
        run_id: str,
    ) -> DemoSeedIsolationAudit:
        run = self._get_demo_seed_run(run_id)
        origin = self.project_creation_service.get_project_origin(run.project_id)
        profile = self.get_demo_seed_profile(run.demo_seed_id)
        storage_issues = self._unsafe_storage_issues_for_audit()

        explicit_selection = run.explicit_user_selection_verified
        demo_marker_present = run.demo_marker == profile.required_marker
        origin_present = origin.origin_type != "unknown_origin"
        origin_type_is_demo_seed = origin.origin_type == "demo_seed"
        project_marked_demo = origin.is_demo_project and run.is_demo_project
        no_demo_data_in_real_project = not origin.is_real_user_project and run.writes_real_project_storage is False
        no_legacy_debug_data = origin.origin_type != "legacy_debug"
        no_auto_opened_as_real = not origin.is_real_user_project
        no_conversion_without_audit = run.demo_to_real_conversion_blocked and not run.copied_to_real_project

        violations = []
        checks = {
            "explicit_user_selection_not_verified": explicit_selection,
            "demo_marker_missing": demo_marker_present,
            "project_origin_metadata_missing": origin_present,
            "origin_type_is_not_demo_seed": origin_type_is_demo_seed,
            "project_not_marked_demo": project_marked_demo,
            "demo_data_in_real_project": no_demo_data_in_real_project,
            "legacy_debug_data_in_real_project": no_legacy_debug_data,
            "demo_seed_auto_opened_as_real": no_auto_opened_as_real,
            "demo_to_real_conversion_without_audit": no_conversion_without_audit,
            "unsafe_storage_marker": len(storage_issues) == 0,
        }
        violations.extend(code for code, passed in checks.items() if not passed)
        violations.extend(storage_issues)
        passed = len(violations) == 0
        audit = DemoSeedIsolationAudit(
            demo_seed_isolation_audit_id=f"demo_seed_isolation_audit_{uuid4().hex[:12]}",
            demo_seed_run_id=run.demo_seed_run_id,
            project_id=run.project_id,
            project_origin_metadata_id=run.project_origin_metadata_id,
            demo_seed_id=run.demo_seed_id,
            passed=passed,
            explicit_user_selection_verified=explicit_selection,
            demo_marker_present=demo_marker_present,
            project_origin_metadata_present=origin_present,
            origin_type_is_demo_seed=origin_type_is_demo_seed,
            project_marked_demo=project_marked_demo,
            no_demo_data_in_real_project=no_demo_data_in_real_project,
            no_legacy_debug_data_in_real_project=no_legacy_debug_data,
            no_demo_seed_auto_opened_as_real=no_auto_opened_as_real,
            no_demo_to_real_conversion_without_audit=no_conversion_without_audit,
            no_final_story_fact_write=True,
            no_final_story_package_write=True,
            no_plugin_output_artifact_write=True,
            no_raw_prompt_in_debug=True,
            no_raw_response=True,
            no_hidden_reasoning=True,
            no_api_key=True,
            no_authorization_header=True,
            no_bearer_token=True,
            no_uncontrolled_full_story_prose=True,
            no_full_screenplay_text=True,
            violations=violations,
            warnings=run.warnings,
            safe_summary=(
                "Demo seed isolation audit passed."
                if passed
                else f"Demo seed isolation audit blocked by {len(violations)} issue(s)."
            ),
            created_at=utc_now(),
        )
        records = self._read_demo_seed_audits()
        records.append(audit)
        self._write_demo_seed_audits(records)
        return audit

    def get_demo_seed_isolation_audit(self, audit_id: str) -> DemoSeedIsolationAudit:
        for record in self._read_demo_seed_audits():
            if record.demo_seed_isolation_audit_id == audit_id:
                return record
        raise TemplateDemoSeedNotFound(f"Demo seed isolation audit not found: {audit_id}")

    def project_origin_badge(self, project_id: str) -> ProjectOriginBadge:
        origin = self.project_creation_service.get_project_origin(project_id)
        return self._badge_from_origin(origin)

    def safety_scan(self) -> TemplateDemoSeedSafetyScanReport:
        targets = [
            self.project_templates_file,
            self.template_requests_file,
            self.template_validation_reports_file,
            self.template_reports_file,
            self.demo_seed_runs_file,
            self.demo_seed_audits_file,
            self.project_origin_badges_file,
            self.project_creation_service.origin_metadata_file,
            self.project_creation_service.registry_file,
            self.project_creation_service.requests_file,
            self.project_creation_service.decisions_file,
            self.project_creation_service.demo_seed_profiles_file,
            *[self.data_dir / filename for filename in STORY_FACT_AND_ARTIFACT_FILES],
        ]
        scanned: list[str] = []
        issues: list[str] = []
        for target in targets:
            if not target.exists():
                continue
            scanned.append(target.name)
            try:
                payload = self.store.read_any(target)
            except StorageError as exc:
                issues.append(f"{target.name}:storage_error")
                continue
            issues.extend(self._unsafe_payload_issues(payload, target.name))
        return TemplateDemoSeedSafetyScanReport(
            ok=len(issues) == 0,
            scanned_targets=scanned,
            issues=self._dedupe(issues),
        )

    def _default_templates(self) -> list[ProjectTemplate]:
        now = utc_now()
        return [
            ProjectTemplate(
                template_id="template_story_foundation",
                display_name="Story Foundation Starter",
                template_version_id="template_story_foundation_v1",
                source_type="built_in_safe_template",
                source_ref="phase8_m4_builtin:story_foundation",
                safe_preview="Reusable setup prompts for world scope, main conflict, and chapter direction.",
                starter_material_refs=[
                    "starter_ref:world_scope",
                    "starter_ref:main_conflict",
                    "starter_ref:chapter_direction",
                ],
                recommended_entry_workspace="world_canvas",
                provenance_summary="Built-in Phase 8 starter authored for safe project setup.",
                safe_summary="Template provides reusable starter metadata only.",
                created_at=now,
                updated_at=now,
            ),
            ProjectTemplate(
                template_id="template_character_drama",
                display_name="Character Drama Starter",
                template_version_id="template_character_drama_v1",
                source_type="built_in_safe_template",
                source_ref="phase8_m4_builtin:character_drama",
                safe_preview="Reusable character arc questions and relationship setup prompts.",
                starter_material_refs=[
                    "starter_ref:character_arc_questions",
                    "starter_ref:relationship_setup",
                ],
                recommended_entry_workspace="characters",
                provenance_summary="Built-in Phase 8 starter authored for safe project setup.",
                safe_summary="Template provides character planning starter metadata only.",
                created_at=now,
                updated_at=now,
            ),
            ProjectTemplate(
                template_id="template_mystery_serial",
                display_name="Mystery Serial Starter",
                template_version_id="template_mystery_serial_v1",
                source_type="built_in_safe_template",
                source_ref="phase8_m4_builtin:mystery_serial",
                safe_preview="Reusable clue cadence, reveal timing, and continuity planning prompts.",
                starter_material_refs=[
                    "starter_ref:clue_cadence",
                    "starter_ref:reveal_timing",
                    "starter_ref:continuity_questions",
                ],
                recommended_entry_workspace="chapter_plan",
                provenance_summary="Built-in Phase 8 starter authored for safe project setup.",
                safe_summary="Template provides serial planning starter metadata only.",
                created_at=now,
                updated_at=now,
            ),
        ]

    def _templates_or_seed_defaults(self) -> list[ProjectTemplate]:
        templates = self._read_project_templates()
        if templates:
            return templates
        templates = self._default_templates()
        self._write_project_templates(templates)
        return templates

    def _template_origin_or_block(
        self,
        project_id: str,
        template_id: str,
    ) -> ProjectOriginMetadata:
        self.project_creation_service.get_project(project_id)
        origin = self.project_creation_service.get_project_origin(project_id)
        if origin.origin_type == "unknown_origin":
            raise TemplateDemoSeedBlocked("project_origin_metadata_missing")
        if origin.origin_type != "template" or not origin.is_template_derived:
            raise TemplateDemoSeedBlocked("project_origin_is_not_template")
        if origin.template_id != template_id:
            raise TemplateDemoSeedBlocked("template_id_does_not_match_project_origin")
        return origin

    def _demo_origin_or_block(
        self,
        project_id: str,
        demo_seed_id: str,
    ) -> ProjectOriginMetadata:
        self.project_creation_service.get_project(project_id)
        origin = self.project_creation_service.get_project_origin(project_id)
        if origin.origin_type == "unknown_origin":
            raise TemplateDemoSeedBlocked("project_origin_metadata_missing")
        if origin.origin_type != "demo_seed" or not origin.is_demo_project:
            raise TemplateDemoSeedBlocked("project_origin_is_not_demo_seed")
        if origin.demo_seed_id != demo_seed_id:
            raise TemplateDemoSeedBlocked("demo_seed_id_does_not_match_project_origin")
        return origin

    def _resolve_creation_request(
        self,
        creation_request_id: str | None,
        project_id: str,
        expected_mode_type: str,
        expected_ref: str,
    ) -> ProjectCreationRequest | None:
        requests = self.project_creation_service._read_requests()
        matches = [
            request
            for request in requests
            if request.mode_type == expected_mode_type
            and (
                (expected_mode_type == "template_project" and request.template_id == expected_ref)
                or (
                    expected_mode_type == "demo_seed_project"
                    and request.demo_seed_id == expected_ref
                )
            )
        ]
        if creation_request_id:
            for request in matches:
                if request.creation_request_id == creation_request_id:
                    return request
            raise TemplateDemoSeedBlocked("creation_request_does_not_match_project_origin")
        decisions = self.project_creation_service._read_decisions()
        request_ids_for_project = {
            decision.creation_request_id
            for decision in decisions
            if decision.created_project_id == project_id
        }
        for request in reversed(matches):
            if request.creation_request_id in request_ids_for_project:
                return request
        return None

    def _resolve_creation_decision(
        self,
        creation_decision_id: str | None,
        project_id: str,
        creation_request_id: str | None,
    ) -> ProjectCreationDecision | None:
        decisions = self.project_creation_service._read_decisions()
        project_matches = [
            decision
            for decision in decisions
            if decision.created_project_id == project_id
            and (
                creation_request_id is None
                or decision.creation_request_id == creation_request_id
            )
        ]
        if creation_decision_id:
            for decision in project_matches:
                if decision.creation_decision_id == creation_decision_id:
                    return decision
            raise TemplateDemoSeedBlocked("creation_decision_does_not_match_project_origin")
        return project_matches[-1] if project_matches else None

    def _badge_from_origin(self, origin: ProjectOriginMetadata) -> ProjectOriginBadge:
        label_map = {
            "blank": ("Blank real project", "real_user"),
            "prompt_first": ("Prompt-first project", "prompt_first"),
            "template": ("Template starter project", "template"),
            "demo_seed": ("Demo-only project", "demo"),
            "analyze_stories_import": ("Analyze Stories import project", "analyze_stories"),
            "existing_project": ("Existing project", "existing"),
            "legacy_debug": ("Legacy debug project", "legacy_debug"),
            "unknown_origin": ("Unknown origin", "unknown"),
        }
        label, kind = label_map.get(origin.origin_type, (origin.origin_type, origin.origin_type))
        requires_review = origin.origin_type in {"legacy_debug", "unknown_origin"}
        return ProjectOriginBadge(
            project_id=origin.project_id,
            project_origin_metadata_id=origin.origin_metadata_id,
            origin_type=origin.origin_type,
            badge_label=label,
            badge_kind=kind,
            is_real_user_project=origin.is_real_user_project,
            is_demo_project=origin.is_demo_project,
            is_template_derived=origin.is_template_derived,
            is_prompt_first=origin.is_prompt_first,
            is_analyze_stories_derived=origin.is_analyze_stories_derived,
            is_legacy_debug_project=origin.is_legacy_debug_project,
            requires_origin_review=requires_review,
            safe_summary=f"Project origin badge derived from M2 origin metadata: {origin.origin_type}.",
            warnings=origin.warnings,
        )

    def _assert_template_hard_rules(self, template: ProjectTemplate) -> None:
        if template.is_demo_material:
            raise TemplateDemoSeedSafetyError("project_template_cannot_be_demo_material")
        if template.creates_story_facts_now:
            raise TemplateDemoSeedSafetyError("project_template_cannot_create_story_facts")
        if not template.requires_downstream_confirmation:
            raise TemplateDemoSeedSafetyError("project_template_must_require_downstream_confirmation")
        if template.contains_full_story_prose:
            raise TemplateDemoSeedSafetyError("project_template_contains_full_story_prose")
        if template.contains_full_screenplay_text:
            raise TemplateDemoSeedSafetyError("project_template_contains_full_screenplay_text")
        if template.contains_user_private_content:
            raise TemplateDemoSeedSafetyError("project_template_contains_user_private_content")

    def _assert_template_report_no_writes(
        self,
        report: TemplateInstantiationReport,
    ) -> None:
        if report.creates_user_owned_story_facts_now or not report.requires_downstream_confirmation:
            raise TemplateDemoSeedSafetyError("template_report_story_fact_boundary_violation")
        write_flags = [
            report.wrote_confirmed_world_canvas,
            report.wrote_confirmed_character,
            report.wrote_active_framework,
            report.wrote_chapter_plan,
            report.wrote_scene_event_memory_state,
            report.wrote_final_story_package,
            report.wrote_plugin_output_artifact,
        ]
        if any(write_flags):
            raise TemplateDemoSeedSafetyError("template_report_write_flag_violation")

    def _assert_demo_seed_profile_hard_rules(self, profile: DemoSeedProfile) -> None:
        if profile.demo_seed_status != "enabled":
            raise TemplateDemoSeedBlocked("demo_seed_profile_not_enabled")
        if not profile.creates_demo_project_only:
            raise TemplateDemoSeedSafetyError("demo_seed_must_create_demo_project_only")
        if profile.may_be_copied_to_real_project:
            raise TemplateDemoSeedSafetyError("demo_seed_cannot_be_copied_to_real_project")
        if profile.required_marker != "explicit_demo_seed_selection":
            raise TemplateDemoSeedSafetyError("demo_seed_required_marker_invalid")

    def _assert_demo_run_hard_rules(self, run: DemoSeedRunRecord) -> None:
        if not run.explicit_user_selection_verified:
            raise TemplateDemoSeedSafetyError("demo_run_missing_explicit_selection")
        if not run.is_demo_project or not run.creates_demo_project_only:
            raise TemplateDemoSeedSafetyError("demo_run_not_demo_only")
        if run.writes_real_project_storage:
            raise TemplateDemoSeedSafetyError("demo_run_writes_real_project_storage")
        if run.copied_to_real_project or not run.demo_to_real_conversion_blocked:
            raise TemplateDemoSeedSafetyError("demo_to_real_conversion_not_blocked")

    def _unsafe_storage_issues_for_audit(self) -> list[str]:
        issues: list[str] = []
        for path in [
            self.project_templates_file,
            self.template_requests_file,
            self.template_validation_reports_file,
            self.template_reports_file,
            self.demo_seed_runs_file,
            self.project_creation_service.origin_metadata_file,
            self.project_creation_service.registry_file,
        ]:
            if not path.exists():
                continue
            try:
                payload = self.store.read_any(path)
            except StorageError:
                issues.append(f"{path.name}:storage_error")
                continue
            issues.extend(self._unsafe_payload_issues(payload, path.name))
        return self._dedupe(issues)

    def _safe_workspace(self, value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9_\-]+", "_", (value or "world_canvas").lower()).strip("_")
        return cleaned[:80] or "world_canvas"

    def _safe_note(self, note: str) -> str:
        self._guard_safe_payload({"safe_user_note": note})
        return " ".join((note or "").split())[:240]

    def _guard_safe_payload(self, payload: Any) -> None:
        issues = self._unsafe_payload_issues(payload, "payload")
        if issues:
            raise TemplateDemoSeedSafetyError("; ".join(issues))

    def _unsafe_payload_issues(self, payload: Any, label: str) -> list[str]:
        issues: list[str] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, BaseModel):
                visit(model_to_dict(value), path)
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized_key = str(key).lower().replace("-", "_")
                    if normalized_key in {
                        "authorization",
                        "bearer",
                        "api_key_ref",
                        "api_key_plaintext",
                        "raw_key",
                        "raw_provider_response",
                    }:
                        issues.append(f"{label}:{path}.{key}:unsafe_key")
                    visit(child, f"{path}.{key}")
                return
            if isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")
                return
            if not isinstance(value, str):
                return
            if SECRET_LIKE_RE.search(value):
                issues.append(f"{label}:{path}:secret_like_value")
            lowered = value.lower()
            for marker in UNSAFE_VALUE_MARKERS:
                if marker in lowered:
                    issues.append(f"{label}:{path}:unsafe_marker:{marker}")

        visit(payload, "$")
        return self._dedupe(issues)

    def _read_project_templates(self) -> list[ProjectTemplate]:
        return self._read_model_list(self.project_templates_file, ProjectTemplate)

    def _write_project_templates(self, records: list[ProjectTemplate]) -> None:
        for record in records:
            self._assert_template_hard_rules(record)
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(self.project_templates_file, [model_to_dict(item) for item in records])

    def _read_template_requests(self) -> list[TemplateInstantiationRequest]:
        return self._read_model_list(self.template_requests_file, TemplateInstantiationRequest)

    def _write_template_requests(self, records: list[TemplateInstantiationRequest]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(self.template_requests_file, [model_to_dict(item) for item in records])

    def _read_template_validation_reports(self) -> list[TemplateInstantiationValidationReport]:
        return self._read_model_list(
            self.template_validation_reports_file,
            TemplateInstantiationValidationReport,
        )

    def _write_template_validation_reports(
        self,
        records: list[TemplateInstantiationValidationReport],
    ) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(
            self.template_validation_reports_file,
            [model_to_dict(item) for item in records],
        )

    def _read_template_reports(self) -> list[TemplateInstantiationReport]:
        return self._read_model_list(self.template_reports_file, TemplateInstantiationReport)

    def _write_template_reports(self, records: list[TemplateInstantiationReport]) -> None:
        for record in records:
            self._assert_template_report_no_writes(record)
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(self.template_reports_file, [model_to_dict(item) for item in records])

    def _read_demo_seed_runs(self) -> list[DemoSeedRunRecord]:
        return self._read_model_list(self.demo_seed_runs_file, DemoSeedRunRecord)

    def _write_demo_seed_runs(self, records: list[DemoSeedRunRecord]) -> None:
        for record in records:
            self._assert_demo_run_hard_rules(record)
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(self.demo_seed_runs_file, [model_to_dict(item) for item in records])

    def _read_demo_seed_audits(self) -> list[DemoSeedIsolationAudit]:
        return self._read_model_list(self.demo_seed_audits_file, DemoSeedIsolationAudit)

    def _write_demo_seed_audits(self, records: list[DemoSeedIsolationAudit]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(self.demo_seed_audits_file, [model_to_dict(item) for item in records])

    def _read_origin_badges(self) -> list[ProjectOriginBadge]:
        return self._read_model_list(self.project_origin_badges_file, ProjectOriginBadge)

    def _write_origin_badges(self, records: list[ProjectOriginBadge]) -> None:
        self._guard_safe_payload([model_to_dict(item) for item in records])
        self.store.write(self.project_origin_badges_file, [model_to_dict(item) for item in records])

    def _read_model_list(self, path: Path, model_type: type[BaseModel]) -> list[Any]:
        if not self.store.exists(path):
            return []
        try:
            data = self.store.read_list(path)
            return [model_type(**item) for item in data]
        except (StorageError, ValidationError, TypeError) as exc:
            raise StorageError(f"Storage file is invalid: {path.name}") from exc

    def _get_template_request(self, request_id: str) -> TemplateInstantiationRequest:
        for record in self._read_template_requests():
            if record.template_instantiation_request_id == request_id:
                return record
        raise TemplateDemoSeedNotFound(f"Template instantiation request not found: {request_id}")

    def _latest_template_validation(
        self,
        request_id: str,
    ) -> TemplateInstantiationValidationReport | None:
        matches = [
            record
            for record in self._read_template_validation_reports()
            if record.template_instantiation_request_id == request_id
        ]
        return matches[-1] if matches else None

    def _get_demo_seed_run(self, run_id: str) -> DemoSeedRunRecord:
        for record in self._read_demo_seed_runs():
            if record.demo_seed_run_id == run_id:
                return record
        raise TemplateDemoSeedNotFound(f"Demo seed run not found: {run_id}")

    def _update_template_request_validation(
        self,
        request_id: str,
        validation_report_id: str,
        status: str,
    ) -> None:
        records = self._read_template_requests()
        for record in records:
            if record.template_instantiation_request_id == request_id:
                record.validation_report_id = validation_report_id
                record.request_status = status
                record.updated_at = utc_now()
                self._write_template_requests(records)
                return
        raise TemplateDemoSeedNotFound(f"Template instantiation request not found: {request_id}")

    def _update_template_request_status(self, request_id: str, status: str) -> None:
        records = self._read_template_requests()
        for record in records:
            if record.template_instantiation_request_id == request_id:
                record.request_status = status
                record.updated_at = utc_now()
                self._write_template_requests(records)
                return
        raise TemplateDemoSeedNotFound(f"Template instantiation request not found: {request_id}")

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
