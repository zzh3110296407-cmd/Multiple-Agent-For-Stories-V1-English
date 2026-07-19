from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.agents.world_canvas_agent import WorldCanvasAgent
from app.backend.core.config import settings
from app.backend.models.decision import Decision
from app.backend.models.world_canvas import (
    LogicConflict,
    UnknownRule,
    WorldRule,
    WorldCanvas,
    WorldCanvasValidationResult,
    WorldCanvasWorkflowResponse,
)
from app.backend.models.project_story_premise import ProjectStoryPremise
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.model_gateway_service import (
    ModelCallError,
    ModelGatewayService,
    ModelJsonParseError,
)
from app.backend.services.model_settings_service import ModelSettingsService
from app.backend.services.project_story_premise_service import (
    FORBIDDEN_DEMO_DEFAULTS,
    PROJECT_STORY_PREMISE_MISSING,
    ProjectStoryPremiseBlocked,
    ProjectStoryPremiseNotFound,
    ProjectStoryPremiseService,
)
from app.backend.services.project_creation_service import ProjectCreationService
from app.backend.repositories import RepositoryBundle, create_repositories
from app.backend.services.tracing_service import traceable_operation
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
DEFAULT_WORLD_CANVAS_ID = "world_local_project"
WORLD_CANVAS_VERSION_ID = "version_world_canvas_m4_001"
SHANGHAI_TZ = timezone(timedelta(hours=8))

WORLD_CANVAS_PROJECT_STORY_PREMISE_MISSING = "world_canvas_project_story_premise_missing"
WORLD_CANVAS_PROMPT_FIDELITY_MISSING = "world_canvas_prompt_fidelity_missing"
WORLD_CANVAS_PROMPT_FIDELITY_WEAK = "world_canvas_prompt_fidelity_weak"
WORLD_CANVAS_DEMO_DEFAULT_LEAK = "world_canvas_demo_default_leak"
WORLD_CANVAS_PROJECT_MISMATCH = "world_canvas_project_mismatch"
WORLD_CANVAS_SOURCE_NOT_CONTROLLED_PROMPT = "world_canvas_source_not_controlled_prompt"
WORLD_CANVAS_MODEL_JSON_FALLBACK_WARNING = (
    "model_json_parse_failed_used_deterministic_fallback"
)
WORLD_CANVAS_MODEL_CALL_FALLBACK_WARNING = (
    "model_call_failed_used_deterministic_fallback"
)
WORLD_CANVAS_PROMPT_FIDELITY_REPAIR_WARNING = (
    "world_canvas_prompt_fidelity_repaired_from_project_premise"
)
WORLD_CANVAS_LOGIC_CONFLICT_AUTO_RESOLVED_WARNING = (
    "world_canvas_logic_conflict_auto_resolved_from_suggested_fix"
)


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def copy_model(model: BaseModel, **updates: Any):
    if hasattr(model, "model_copy"):
        return model.model_copy(update=updates, deep=True)
    return model.copy(update=updates, deep=True)


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat()


class WorldCanvasPromptFidelityError(StorageError):
    def __init__(self, error_code: str, message: str | None = None) -> None:
        self.error_code = error_code
        super().__init__(message or error_code)


class WorldCanvasService:
    def __init__(
        self,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        agent: WorldCanvasAgent | None = None,
        repositories: RepositoryBundle | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.world_canvas_file = self.data_dir / "world_canvas.json"
        self.decisions_file = self.data_dir / "decisions.json"
        self.story_bible_file = self.data_dir / "story_bible.json"
        self.project_file = self.data_dir / "project.json"
        self.agent = agent or WorldCanvasAgent(
            model_gateway=ModelGatewayService(store=self.store, data_dir=self.data_dir)
        )
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )

    def _current_project_id(self) -> str:
        return current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )

    def get_current_canvas(self) -> WorldCanvasWorkflowResponse:
        canvas = self._read_canvas()
        validation = self.validate_canvas(canvas)
        return WorldCanvasWorkflowResponse(
            world_canvas=canvas,
            validation=validation,
            decision=None,
        )

    @traceable_operation("WorldCanvasService.generate_from_idea", tags=["world_canvas"])
    def generate_from_idea(self, story_idea: str) -> WorldCanvasWorkflowResponse:
        clean_story_idea = (story_idea or "").strip()
        premise = self._resolve_required_project_story_premise()
        self._guard_user_prompt_for_premise(clean_story_idea, premise)
        effective_story_idea = self._build_effective_story_idea(clean_story_idea, premise)
        if not effective_story_idea.strip():
            raise StorageError("story_idea must not be empty.")

        existing_canvas = self._try_read_canvas()
        fallback_warning = ""
        try:
            generated = self.agent.generate_from_idea(effective_story_idea)
        except (ModelJsonParseError, ModelCallError) as exc:
            fallback_warning = self._fallback_warning_for_model_failure(exc)
            generated = self._fallback_data_or_raise(
                exc,
                source_story_idea=effective_story_idea,
                latest_user_prompt="",
            )
        canvas = self._build_canvas_from_agent_data_with_retry(
            data=generated,
            retry_call=lambda: self.agent.generate_from_idea(
                self._strict_schema_retry_prompt(effective_story_idea)
            ),
            source_story_idea=effective_story_idea,
            latest_user_prompt="",
            existing_canvas=existing_canvas,
        )
        canvas = self._merge_project_story_premise_evidence(canvas, premise)
        canvas = self._mark_model_fallback_if_used(canvas, fallback_warning)
        canvas = self.detect_rule_gaps_and_conflicts(canvas)
        validation = self.validate_canvas(canvas)
        validation = self._validation_with_fallback_warning(validation, fallback_warning)
        canvas, validation = self._repair_prompt_fidelity_if_needed(
            canvas,
            validation,
            source_story_idea=effective_story_idea,
            latest_user_prompt="",
            existing_canvas=existing_canvas,
        )
        self._raise_if_prompt_fidelity_blocking(validation)
        self.save_canvas(canvas)
        self._sync_story_bible_world_canvas_id(canvas.world_canvas_id)
        self._update_project_step("world_canvas_draft", "drafting_world_canvas")
        return WorldCanvasWorkflowResponse(
            world_canvas=canvas,
            validation=validation,
            decision=None,
        )

    @traceable_operation("WorldCanvasService.revise_canvas", tags=["world_canvas"])
    def revise_canvas(self, revision_prompt: str) -> WorldCanvasWorkflowResponse:
        clean_revision_prompt = revision_prompt.strip()
        if not clean_revision_prompt:
            raise StorageError("revision_prompt must not be empty.")

        current_canvas = self._read_canvas()
        premise = self._resolve_required_project_story_premise()
        self._guard_user_prompt_for_premise(clean_revision_prompt, premise)
        effective_revision_prompt = self._build_effective_revision_prompt(
            clean_revision_prompt,
            premise,
        )
        fallback_warning = ""
        try:
            revised = self.agent.revise_canvas(current_canvas, effective_revision_prompt)
        except (ModelJsonParseError, ModelCallError) as exc:
            fallback_warning = self._fallback_warning_for_model_failure(exc)
            revised = self._fallback_data_or_raise(
                exc,
                source_story_idea=current_canvas.source_story_idea
                or self._build_effective_story_idea("", premise),
                latest_user_prompt=clean_revision_prompt,
            )
        canvas = self._build_canvas_from_agent_data_with_retry(
            data=revised,
            retry_call=lambda: self.agent.revise_canvas(
                current_canvas,
                self._strict_schema_retry_prompt(effective_revision_prompt),
            ),
            source_story_idea=current_canvas.source_story_idea
            or self._build_effective_story_idea("", premise),
            latest_user_prompt=clean_revision_prompt,
            existing_canvas=current_canvas,
        )
        canvas = self._merge_project_story_premise_evidence(canvas, premise)
        canvas = self._mark_model_fallback_if_used(canvas, fallback_warning)
        canvas = self.detect_rule_gaps_and_conflicts(canvas)
        validation = self.validate_canvas(canvas)
        validation = self._validation_with_fallback_warning(validation, fallback_warning)
        canvas, validation = self._repair_prompt_fidelity_if_needed(
            canvas,
            validation,
            source_story_idea=current_canvas.source_story_idea
            or self._build_effective_story_idea("", premise),
            latest_user_prompt=clean_revision_prompt,
            existing_canvas=current_canvas,
        )
        self._raise_if_prompt_fidelity_blocking(validation)
        self.save_canvas(canvas)
        self._sync_story_bible_world_canvas_id(canvas.world_canvas_id)
        self._update_project_step("world_canvas_draft", "drafting_world_canvas")
        return WorldCanvasWorkflowResponse(
            world_canvas=canvas,
            validation=validation,
            decision=None,
        )

    @traceable_operation("WorldCanvasService.confirm_canvas", tags=["world_canvas"])
    def confirm_canvas(self, user_input: str | None = None) -> WorldCanvasWorkflowResponse:
        canvas = self._read_canvas()
        validation = self.validate_canvas(canvas)
        if validation.blocking_issues:
            prompt_code = self._first_prompt_fidelity_issue(validation)
            if prompt_code:
                raise WorldCanvasPromptFidelityError(
                    prompt_code,
                    "Cannot confirm World Canvas while prompt-fidelity validation issues exist.",
                )
            raise StorageError(
                "Cannot confirm World Canvas while blocking validation issues exist."
            )

        confirmed_canvas = copy_model(
            canvas,
            status="confirmed",
            updated_at=now_iso(),
        )
        self.save_canvas(confirmed_canvas)
        self._sync_story_bible_world_canvas_id(confirmed_canvas.world_canvas_id)
        decision = self._append_confirmation_decision(confirmed_canvas, user_input)
        self._update_project_step("world_canvas_confirmed", "world_canvas_confirmed")
        return WorldCanvasWorkflowResponse(
            world_canvas=confirmed_canvas,
            validation=self.validate_canvas(confirmed_canvas),
            decision=decision,
        )

    def validate_canvas(self, canvas: WorldCanvas) -> WorldCanvasValidationResult:
        warnings: list[str] = []
        blocking_issues: list[str] = []

        if not canvas.world_canvas_id:
            blocking_issues.append("WorldCanvas.world_canvas_id must not be empty.")
        if canvas.status not in {"draft", "confirmed"}:
            blocking_issues.append("WorldCanvas.status must be draft or confirmed.")
        if not canvas.scope:
            blocking_issues.append("WorldCanvas.scope must not be empty.")
        if not canvas.tone:
            blocking_issues.append("WorldCanvas.tone must not be empty.")
        if not canvas.story_direction:
            warnings.append("WorldCanvas.story_direction is empty.")
        if not canvas.hard_rules:
            blocking_issues.append("WorldCanvas.hard_rules must contain at least one rule.")
        if not canvas.soft_rules:
            warnings.append("WorldCanvas.soft_rules is empty.")
        if any(
            rule.source == "auto_resolved_logic_conflict_suggested_fix"
            for rule in canvas.soft_rules
        ):
            warnings.append(WORLD_CANVAS_LOGIC_CONFLICT_AUTO_RESOLVED_WARNING)

        high_conflicts = [
            conflict
            for conflict in canvas.logic_conflicts
            if conflict.severity == "high" and conflict.requires_user_decision
        ]
        if high_conflicts:
            blocking_issues.append("High severity logic conflicts require user decision.")

        prompt_result = self._validate_canvas_prompt_fidelity(canvas)
        warnings.extend(prompt_result["warnings"])
        blocking_issues.extend(prompt_result["blocking_issues"])

        return WorldCanvasValidationResult(
            passed=len(blocking_issues) == 0,
            warnings=warnings,
            blocking_issues=blocking_issues,
            prompt_fidelity_status=prompt_result["status"],
            prompt_fidelity_issues=prompt_result["issues"],
            prompt_fidelity_coverage=prompt_result["coverage"],
        )

    def _resolve_required_project_story_premise(self) -> ProjectStoryPremise | None:
        project_id = self._current_project_id()
        service = ProjectStoryPremiseService(store=self.store, data_dir=self.data_dir)
        try:
            premise = service.read_from_story_data_dir(project_id, self.data_dir)
        except ProjectStoryPremiseBlocked as exc:
            raise WorldCanvasPromptFidelityError(
                WORLD_CANVAS_PROJECT_MISMATCH,
                str(exc) or WORLD_CANVAS_PROJECT_MISMATCH,
            ) from exc
        if premise and premise.blocking_issues:
            raise WorldCanvasPromptFidelityError(
                WORLD_CANVAS_PROJECT_STORY_PREMISE_MISSING,
                ",".join(premise.blocking_issues),
            )
        if premise and premise.source_status != "controlled_prompt":
            raise WorldCanvasPromptFidelityError(
                WORLD_CANVAS_SOURCE_NOT_CONTROLLED_PROMPT,
                WORLD_CANVAS_SOURCE_NOT_CONTROLLED_PROMPT,
            )
        if not premise and self._project_requires_story_premise():
            raise WorldCanvasPromptFidelityError(
                WORLD_CANVAS_PROJECT_STORY_PREMISE_MISSING,
                PROJECT_STORY_PREMISE_MISSING,
            )
        return premise

    def _try_resolve_project_story_premise(self) -> ProjectStoryPremise | None:
        project_id = self._current_project_id()
        service = ProjectStoryPremiseService(store=self.store, data_dir=self.data_dir)
        try:
            return service.read_from_story_data_dir(project_id, self.data_dir)
        except (ProjectStoryPremiseBlocked, ProjectStoryPremiseNotFound, StorageError):
            return None

    def _project_requires_story_premise(self) -> bool:
        project_id = self._current_project_id()
        if self.store.exists(self.project_file):
            try:
                project = self.store.read(self.project_file)
            except StorageError:
                project = {}
            if str(project.get("origin_type") or "") == "prompt_first":
                return True
        try:
            origin = ProjectCreationService(
                store=self.store,
                data_dir=self._project_registry_data_dir(),
            ).get_project_origin(project_id)
        except StorageError:
            return False
        return bool(origin.is_prompt_first or origin.origin_type == "prompt_first")

    def _project_registry_data_dir(self) -> Path:
        if self.data_dir.parent.name == "projects":
            return self.data_dir.parent.parent / LOCAL_PROJECT_ID
        return self.data_dir

    def _guard_user_prompt_for_premise(
        self,
        user_prompt: str,
        premise: ProjectStoryPremise | None,
    ) -> None:
        if not premise:
            return
        if self._demo_default_count(user_prompt) > 0:
            raise WorldCanvasPromptFidelityError(
                WORLD_CANVAS_DEMO_DEFAULT_LEAK,
                WORLD_CANVAS_DEMO_DEFAULT_LEAK,
            )

    def _build_effective_story_idea(
        self,
        user_prompt: str,
        premise: ProjectStoryPremise | None,
    ) -> str:
        clean_user_prompt = " ".join((user_prompt or "").split())
        if not premise:
            return clean_user_prompt
        parts = [
            "ProjectStoryPremise is authoritative for this Prompt-first project.",
            f"User story premise: {premise.user_story_premise}",
        ]
        if premise.safe_user_story_summary:
            parts.append(f"Safe premise summary: {premise.safe_user_story_summary}")
        if premise.required_story_elements:
            parts.append(
                "Required story elements: "
                + ", ".join(premise.required_story_elements[:24])
            )
        if premise.prompt_fidelity_contract.required_markers:
            parts.append(
                "Required markers: "
                + ", ".join(premise.prompt_fidelity_contract.required_markers)
            )
        if clean_user_prompt:
            parts.append(f"User World Canvas focus: {clean_user_prompt}")
        return "\n".join(parts)

    def _build_effective_revision_prompt(
        self,
        revision_prompt: str,
        premise: ProjectStoryPremise | None,
    ) -> str:
        if not premise:
            return revision_prompt
        return "\n".join(
            [
                "Revise under the active ProjectStoryPremise. Do not remove premise evidence.",
                f"ProjectStoryPremise: {premise.user_story_premise}",
                f"User revision focus: {revision_prompt}",
            ]
        )

    def _merge_project_story_premise_evidence(
        self,
        canvas: WorldCanvas,
        premise: ProjectStoryPremise | None,
    ) -> WorldCanvas:
        if not premise:
            return canvas
        evidence = self._premise_evidence_text(premise)
        story_direction = canvas.story_direction or ""
        if evidence and evidence not in story_direction:
            story_direction = f"{story_direction}\n项目前提锚点：{evidence}".strip()
        special_rules = list(canvas.soft_rules)
        soft_rule_statement = f"世界画布必须持续保留项目前提证据：{evidence}"
        if evidence and not any(rule.statement == soft_rule_statement for rule in special_rules):
            special_rules.append(
                type(canvas.soft_rules[0])(
                    rule_id="rule_soft_project_story_premise_anchor_001",
                    statement=soft_rule_statement,
                    category="other",
                    firmness="soft",
                    source="fallback_from_project_story_premise",
                    applies_to=["world"],
                    rationale="M2 prompt-fidelity anchor from ProjectStoryPremise.",
                    risk_if_changed="Removing this anchor can break Prompt-first project premise continuity.",
                    version_id=WORLD_CANVAS_VERSION_ID,
                )
                if canvas.soft_rules
                else self._rule_from_premise_anchor(soft_rule_statement)
            )
        return copy_model(
            canvas,
            project_id=premise.project_id,
            story_direction=story_direction,
            soft_rules=special_rules,
            updated_at=now_iso(),
        )

    def _rule_from_premise_anchor(self, statement: str):
        from app.backend.models.world_canvas import WorldRule

        return WorldRule(
            rule_id="rule_soft_project_story_premise_anchor_001",
            statement=statement,
            category="other",
            firmness="soft",
            source="fallback_from_project_story_premise",
            applies_to=["world"],
            rationale="M2 prompt-fidelity anchor from ProjectStoryPremise.",
            risk_if_changed="Removing this anchor can break Prompt-first project premise continuity.",
            version_id=WORLD_CANVAS_VERSION_ID,
        )

    def _premise_evidence_text(self, premise: ProjectStoryPremise) -> str:
        markers = premise.prompt_fidelity_contract.required_markers
        terms = premise.required_story_elements
        parts = [premise.safe_user_story_summary or premise.user_story_premise[:220]]
        if markers:
            parts.append(" ".join(markers[:8]))
        if terms:
            parts.append(" ".join(terms[:12]))
        return "；".join(part for part in parts if part)

    def _validate_canvas_prompt_fidelity(self, canvas: WorldCanvas) -> dict[str, Any]:
        coverage: dict[str, Any] = {
            "source_status": "not_applicable",
            "marker_counts": {},
            "required_terms_present": {},
            "demo_default_count": 0,
            "required_marker_hit_count": 0,
            "required_term_hit_count": 0,
        }
        warnings: list[str] = []
        blocking_issues: list[str] = []
        issues: list[str] = []
        premise = self._try_resolve_project_story_premise()
        if not premise:
            if self._project_requires_story_premise():
                blocking_issues.append(WORLD_CANVAS_PROJECT_STORY_PREMISE_MISSING)
                issues.append(WORLD_CANVAS_PROJECT_STORY_PREMISE_MISSING)
                return {
                    "status": "blocked",
                    "warnings": warnings,
                    "blocking_issues": blocking_issues,
                    "issues": issues,
                    "coverage": coverage,
                }
            return {
                "status": "not_applicable",
                "warnings": warnings,
                "blocking_issues": blocking_issues,
                "issues": issues,
                "coverage": coverage,
            }
        if canvas.project_id and canvas.project_id != premise.project_id:
            blocking_issues.append(WORLD_CANVAS_PROJECT_MISMATCH)
            issues.append(WORLD_CANVAS_PROJECT_MISMATCH)
        if premise.source_status != "controlled_prompt":
            blocking_issues.append(WORLD_CANVAS_SOURCE_NOT_CONTROLLED_PROMPT)
            issues.append(WORLD_CANVAS_SOURCE_NOT_CONTROLLED_PROMPT)
        story_payload = self._canvas_story_facing_payload(canvas)
        text = self._payload_text(story_payload)
        marker_counts = {
            marker: text.count(marker)
            for marker in premise.prompt_fidelity_contract.required_markers
        }
        content_terms = self._premise_content_terms(premise)
        required_terms_present = {term: term in text for term in content_terms}
        demo_default_count = self._demo_default_count(model_to_dict(canvas))
        marker_hit_count = sum(1 for count in marker_counts.values() if count > 0)
        term_hit_count = sum(1 for present in required_terms_present.values() if present)
        coverage = {
            "source_status": premise.source_status,
            "marker_counts": marker_counts,
            "required_terms_present": required_terms_present,
            "demo_default_count": demo_default_count,
            "required_marker_hit_count": marker_hit_count,
            "required_term_hit_count": term_hit_count,
            "required_marker_count": len(marker_counts),
            "required_term_count": len(required_terms_present),
            "coverage_scope": "story_body_only_excludes_source_prompt_latest_prompt_and_soft_rule_anchors",
        }
        if demo_default_count > 0:
            blocking_issues.append(WORLD_CANVAS_DEMO_DEFAULT_LEAK)
            issues.append(WORLD_CANVAS_DEMO_DEFAULT_LEAK)
        if marker_counts and marker_hit_count == 0:
            blocking_issues.append(WORLD_CANVAS_PROMPT_FIDELITY_MISSING)
            issues.append(WORLD_CANVAS_PROMPT_FIDELITY_MISSING)
        elif required_terms_present and term_hit_count < self._minimum_required_term_hits(content_terms):
            blocking_issues.append(WORLD_CANVAS_PROMPT_FIDELITY_MISSING)
            issues.append(WORLD_CANVAS_PROMPT_FIDELITY_MISSING)
        elif (
            (marker_counts and marker_hit_count < len(marker_counts))
            or (required_terms_present and term_hit_count < max(1, len(required_terms_present) // 4))
        ):
            warnings.append(WORLD_CANVAS_PROMPT_FIDELITY_WEAK)
            issues.append(WORLD_CANVAS_PROMPT_FIDELITY_WEAK)
        status = "ready"
        if blocking_issues:
            status = "blocked"
        elif warnings:
            status = "weak"
        return {
            "status": status,
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "issues": issues,
            "coverage": coverage,
        }

    def _canvas_story_facing_payload(self, canvas: WorldCanvas) -> dict[str, Any]:
        return {
            "story_direction": self._strip_project_premise_anchor(canvas.story_direction),
            "scope": canvas.scope,
            "tone": canvas.tone,
            "world_structure": model_to_dict(canvas.world_structure),
            "history_summary": canvas.history_summary,
            "geography_summary": canvas.geography_summary,
            "culture_summary": canvas.culture_summary,
            "special_rules_summary": canvas.special_rules_summary,
            "hard_rules": [
                {
                    "statement": rule.statement,
                    "category": rule.category,
                    "applies_to": rule.applies_to,
                    "rationale": rule.rationale,
                    "risk_if_changed": rule.risk_if_changed,
                }
                for rule in canvas.hard_rules
            ],
            "unknown_rules": [
                {
                    "summary": rule.summary,
                    "gap_type": rule.gap_type,
                    "why_it_matters": rule.why_it_matters,
                    "suggested_questions": rule.suggested_questions,
                }
                for rule in canvas.unknown_rules
            ],
            "logic_conflicts": [
                {
                    "summary": conflict.summary,
                    "conflict_type": conflict.conflict_type,
                    "suggested_fix": conflict.suggested_fix,
                }
                for conflict in canvas.logic_conflicts
            ],
            "locations": canvas.locations,
            "factions": canvas.factions,
            "species": canvas.species,
        }

    def _strip_project_premise_anchor(self, text: str) -> str:
        lines = []
        for line in (text or "").splitlines():
            clean = line.strip()
            if clean.startswith("项目前提锚点：") or clean.startswith("ProjectStoryPremise"):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _premise_content_terms(self, premise: ProjectStoryPremise) -> list[str]:
        marker_set = set(premise.prompt_fidelity_contract.required_markers)
        generic_terms = {
            "the",
            "and",
            "with",
            "must",
            "preserve",
            "required",
            "markers",
            "marker",
            "world",
            "canvas",
            "story",
            "project",
            "phase85",
            "m2",
            "create",
            "original",
            "chinese",
        }
        candidates = [
            *premise.setting_terms,
            *premise.conflict_terms,
            *premise.role_terms,
            *premise.required_story_elements,
            *premise.core_terms,
        ]
        terms: list[str] = []
        seen: set[str] = set()
        for term in candidates:
            clean = " ".join(str(term).split()).strip()
            if not clean or clean in seen or clean in marker_set:
                continue
            if self._looks_like_prompt_marker(clean):
                continue
            if clean.lower() in generic_terms:
                continue
            if len(clean) < 3 and not any("\u4e00" <= char <= "\u9fff" for char in clean):
                continue
            seen.add(clean)
            terms.append(clean)
        return terms[:24]

    def _looks_like_prompt_marker(self, value: str) -> bool:
        return value.upper() == value and "_" in value and any(char.isdigit() for char in value)

    def _minimum_required_term_hits(self, terms: list[str]) -> int:
        if not terms:
            return 0
        return min(3, len(terms))

    def _payload_text(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload
        import json

        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _demo_default_count(self, payload: Any) -> int:
        text = self._payload_text(payload)
        return sum(text.count(default) for default in FORBIDDEN_DEMO_DEFAULTS)

    def _raise_if_prompt_fidelity_blocking(
        self,
        validation: WorldCanvasValidationResult,
    ) -> None:
        code = self._first_prompt_fidelity_issue(validation)
        if code:
            raise WorldCanvasPromptFidelityError(code, code)

    def _first_prompt_fidelity_issue(
        self,
        validation: WorldCanvasValidationResult,
    ) -> str:
        prompt_issue_codes = {
            WORLD_CANVAS_PROJECT_STORY_PREMISE_MISSING,
            WORLD_CANVAS_PROMPT_FIDELITY_MISSING,
            WORLD_CANVAS_DEMO_DEFAULT_LEAK,
            WORLD_CANVAS_PROJECT_MISMATCH,
            WORLD_CANVAS_SOURCE_NOT_CONTROLLED_PROMPT,
        }
        for issue in validation.prompt_fidelity_issues:
            if issue in prompt_issue_codes:
                return issue
        for issue in validation.blocking_issues:
            if issue in prompt_issue_codes:
                return issue
        return ""

    def detect_rule_gaps_and_conflicts(self, canvas: WorldCanvas) -> WorldCanvas:
        checked_at = now_iso()
        unknown_rules = [self._stamp_unknown_rule(rule, checked_at) for rule in canvas.unknown_rules]
        logic_conflicts = list(canvas.logic_conflicts)
        rule_texts = [rule.statement for rule in canvas.hard_rules + canvas.soft_rules]
        combined_text = "\n".join(
            [
                canvas.source_story_idea,
                canvas.latest_user_prompt,
                canvas.special_rules_summary,
                *rule_texts,
            ]
        )

        if self._needs_origin_gap(combined_text, unknown_rules):
            unknown_rules.append(
                UnknownRule(
                    unknown_rule_id="unknown_detected_origin_001",
                    summary="核心异常或特殊规则的来源仍未说明。",
                    gap_type="missing_origin",
                    why_it_matters="来源会影响后续反派、制度、历史真相或世界规则解释。",
                    suggested_questions=[
                        "特殊规则是人为制造、自然异常，还是历史事件留下的后果？"
                    ],
                    severity="medium",
                    status="open",
                    first_detected_at=checked_at,
                    last_checked_at=checked_at,
                )
            )
        if self._needs_cost_gap(combined_text, unknown_rules):
            unknown_rules.append(
                UnknownRule(
                    unknown_rule_id="unknown_detected_cost_001",
                    summary="持续使用或触发特殊规则的长期代价仍未说明。",
                    gap_type="missing_cost",
                    why_it_matters="代价会约束角色行动，避免特殊规则成为万能工具。",
                    suggested_questions=[
                        "重复触发规则会损害记忆、身体、关系，还是改变现实记录？"
                    ],
                    severity="medium",
                    status="open",
                    first_detected_at=checked_at,
                    last_checked_at=checked_at,
                )
            )

        if self._has_midnight_random_conflict(rule_texts + [canvas.latest_user_prompt]):
            logic_conflicts.append(
                LogicConflict(
                    conflict_id="conflict_detected_midnight_random_001",
                    summary="当前规则同时暗示午夜固定触发和随机触发，需要明确优先级。",
                    conflict_type="contradiction",
                    related_rule_ids=[
                        rule.rule_id
                        for rule in canvas.hard_rules
                        if "午夜" in rule.statement or "零点" in rule.statement
                    ],
                    severity="medium",
                    suggested_fix="保留午夜作为硬触发，把随机现象解释为余波、误报或传播范围变化。",
                    requires_user_decision=True,
                )
            )

        checked_canvas = copy_model(
            canvas,
            unknown_rules=self._dedupe_unknown_rules(unknown_rules),
            logic_conflicts=self._dedupe_logic_conflicts(logic_conflicts),
            updated_at=checked_at,
        )
        return self._auto_resolve_logic_conflicts_with_suggested_fixes(checked_canvas)

    def _auto_resolve_logic_conflicts_with_suggested_fixes(
        self,
        canvas: WorldCanvas,
    ) -> WorldCanvas:
        logic_conflicts: list[LogicConflict] = []
        soft_rules = list(canvas.soft_rules)
        existing_rule_statements = {rule.statement.strip() for rule in soft_rules}
        changed = False

        for index, conflict in enumerate(canvas.logic_conflicts, start=1):
            if not self._can_auto_resolve_logic_conflict(conflict):
                logic_conflicts.append(conflict)
                continue

            summary = self._bounded_text(conflict.summary, 160)
            suggested_fix = self._bounded_text(conflict.suggested_fix, 320)
            statement = (
                f"Resolve world-canvas logic conflict by treating this as a planning rule: "
                f"{summary} -> {suggested_fix}"
            )
            if statement not in existing_rule_statements:
                soft_rules.append(
                    WorldRule(
                        rule_id=f"rule_soft_auto_resolved_logic_conflict_{index:03d}",
                        statement=statement,
                        category="plot_continuity",
                        firmness="soft",
                        source="auto_resolved_logic_conflict_suggested_fix",
                        applies_to=["world", "chapter_plan", "scene"],
                        rationale=(
                            "A model-detected world-canvas logic conflict included a concrete "
                            "narrative repair path, so the project can proceed by preserving "
                            "the repair path as a soft planning constraint."
                        ),
                        risk_if_changed=(
                            "Removing this rule can reintroduce the same apparent conflict in "
                            "chapter planning or scene writing."
                        ),
                        version_id=WORLD_CANVAS_VERSION_ID,
                    )
                )
                existing_rule_statements.add(statement)

            logic_conflicts.append(
                copy_model(
                    conflict,
                    severity="medium",
                    requires_user_decision=False,
                )
            )
            changed = True

        if not changed:
            return canvas
        return copy_model(
            canvas,
            soft_rules=soft_rules,
            logic_conflicts=self._dedupe_logic_conflicts(logic_conflicts),
            updated_at=now_iso(),
        )

    def _can_auto_resolve_logic_conflict(self, conflict: LogicConflict) -> bool:
        if not conflict.requires_user_decision:
            return False
        if conflict.severity != "high":
            return False
        suggested_fix = (conflict.suggested_fix or "").strip()
        if not suggested_fix:
            return False
        external_decision_markers = [
            "用户决定",
            "用户选择",
            "用户确认",
            "由用户",
            "请用户",
            "人工决定",
            "人工确认",
            "需要补充",
            "无法判断",
            "二选一",
            "任选其一",
            "choose",
            "user decision",
            "user confirmation",
            "manual review",
        ]
        lowered_fix = suggested_fix.lower()
        return not any(marker.lower() in lowered_fix for marker in external_decision_markers)

    def _bounded_text(self, text: str, limit: int) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= limit:
            return clean
        return clean[: max(0, limit - 1)].rstrip() + "..."

    def save_canvas(self, canvas: WorldCanvas) -> None:
        record = model_to_dict(canvas)
        self.repositories.world_canvases.upsert(record, "world_canvas_id")

    def _fallback_warning_for_model_failure(self, exc: Exception) -> str:
        if isinstance(exc, ModelJsonParseError):
            return WORLD_CANVAS_MODEL_JSON_FALLBACK_WARNING
        return WORLD_CANVAS_MODEL_CALL_FALLBACK_WARNING

    def _fallback_data_or_raise(
        self,
        exc: ModelJsonParseError | ModelCallError,
        *,
        source_story_idea: str,
        latest_user_prompt: str,
    ) -> dict[str, Any]:
        if not self._deterministic_model_fallback_allowed():
            raise exc
        return self._fallback_canvas_data_from_story_idea(
            source_story_idea=source_story_idea,
            latest_user_prompt=latest_user_prompt,
        )

    def _deterministic_model_fallback_allowed(self) -> bool:
        for data_dir in self._model_settings_data_dirs():
            try:
                selection = ModelSettingsService(
                    store=self.store,
                    data_dir=data_dir,
                ).get_active_selection().active_selection
            except Exception:
                continue
            if not selection:
                continue
            return bool(
                selection.deterministic_fallback_allowed
                and not selection.real_model_required
            )
        return False

    def _model_settings_data_dirs(self) -> list[Path]:
        candidates = [
            self._project_registry_data_dir(),
            self.data_dir,
        ]
        result: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            result.append(candidate)
        return result

    def _mark_model_fallback_if_used(
        self,
        canvas: WorldCanvas,
        warning_code: str,
    ) -> WorldCanvas:
        if not warning_code:
            return canvas
        note = (
            "真实模型返回非 JSON，系统已使用确定性草稿兜底。请检查并确认后再继续。"
            if warning_code == WORLD_CANVAS_MODEL_JSON_FALLBACK_WARNING
            else "真实模型调用失败，系统已使用确定性草稿兜底。请检查并确认后再继续。"
        )
        confirmation_needed = list(canvas.user_confirmation_needed)
        if note not in confirmation_needed:
            confirmation_needed.append(note)
        return copy_model(
            canvas,
            user_confirmation_needed=confirmation_needed,
            updated_at=now_iso(),
        )

    def _repair_prompt_fidelity_if_needed(
        self,
        canvas: WorldCanvas,
        validation: WorldCanvasValidationResult,
        *,
        source_story_idea: str,
        latest_user_prompt: str,
        existing_canvas: WorldCanvas | None,
    ) -> tuple[WorldCanvas, WorldCanvasValidationResult]:
        if self._first_prompt_fidelity_issue(validation) != WORLD_CANVAS_PROMPT_FIDELITY_MISSING:
            return canvas, validation

        repaired = self._build_canvas_from_agent_data(
            data=self._fallback_canvas_data_from_story_idea(
                source_story_idea=source_story_idea,
                latest_user_prompt=latest_user_prompt,
            ),
            source_story_idea=source_story_idea,
            latest_user_prompt=latest_user_prompt,
            existing_canvas=existing_canvas,
        )
        repaired = self._merge_project_story_premise_evidence(
            repaired,
            self._try_resolve_project_story_premise(),
        )
        repaired = self.detect_rule_gaps_and_conflicts(repaired)
        note = (
            "模型返回的世界画布缺少当前项目前提证据，系统已根据用户提示词重建可确认草稿。"
            "请用户确认后再继续。"
        )
        confirmation_needed = list(repaired.user_confirmation_needed)
        if note not in confirmation_needed:
            confirmation_needed.append(note)
        repaired = copy_model(
            repaired,
            user_confirmation_needed=confirmation_needed,
            updated_at=now_iso(),
        )
        repaired_validation = self.validate_canvas(repaired)
        return (
            repaired,
            self._validation_with_fallback_warning(
                repaired_validation,
                WORLD_CANVAS_PROMPT_FIDELITY_REPAIR_WARNING,
            ),
        )

    def _validation_with_fallback_warning(
        self,
        validation: WorldCanvasValidationResult,
        warning_code: str,
    ) -> WorldCanvasValidationResult:
        if not warning_code:
            return validation
        warnings = list(validation.warnings)
        if warning_code not in warnings:
            warnings.append(warning_code)
        return copy_model(validation, warnings=warnings)

    def _read_canvas(self) -> WorldCanvas:
        records = self.repositories.world_canvases.list_all()
        if not records:
            raise StorageError(f"JSON document does not exist: {self.world_canvas_file}")
        data = records[0]
        try:
            return WorldCanvas(**data)
        except ValidationError as exc:
            raise StorageError(
                f"JSON schema is invalid: {self.world_canvas_file}"
            ) from exc

    def _try_read_canvas(self) -> WorldCanvas | None:
        records = self.repositories.world_canvases.list_all()
        if not records:
            return None
        try:
            return WorldCanvas(**records[0])
        except ValidationError as exc:
            raise StorageError(
                f"JSON schema is invalid: {self.world_canvas_file}"
            ) from exc

    def _build_canvas_from_agent_data(
        self,
        data: dict[str, Any],
        source_story_idea: str,
        latest_user_prompt: str,
        existing_canvas: WorldCanvas | None,
    ) -> WorldCanvas:
        timestamp = now_iso()
        canvas_data = dict(data)
        if isinstance(canvas_data.get("world_canvas"), dict):
            canvas_data = dict(canvas_data["world_canvas"])
        required_story_fields = [
            "scope",
            "tone",
            "history_summary",
            "geography_summary",
            "culture_summary",
            "special_rules_summary",
            "hard_rules",
        ]
        populated_story_fields = sum(
            1 for key in required_story_fields if canvas_data.get(key)
        )
        if populated_story_fields < 5 or not canvas_data.get("hard_rules"):
            raise StorageError("World Canvas model output failed schema validation.")
        canvas_data = self._normalize_agent_canvas_data(canvas_data)
        canvas_data["world_canvas_id"] = self._resolve_world_canvas_id(
            existing_canvas=existing_canvas,
            candidate_id=str(canvas_data.get("world_canvas_id") or ""),
        )
        canvas_data["project_id"] = self._current_project_id()
        canvas_data["status"] = "draft"
        canvas_data["source_story_idea"] = source_story_idea
        canvas_data["latest_user_prompt"] = latest_user_prompt
        canvas_data["created_at"] = (
            existing_canvas.created_at
            if existing_canvas and existing_canvas.created_at
            else timestamp
        )
        canvas_data["updated_at"] = timestamp
        canvas_data["version_id"] = (
            canvas_data.get("version_id") or WORLD_CANVAS_VERSION_ID
        )
        canvas_data["story_direction"] = canvas_data.get("story_direction") or source_story_idea
        canvas_data["scope"] = canvas_data.get("scope") or "未设定"
        canvas_data["tone"] = canvas_data.get("tone") or "未设定"
        try:
            return WorldCanvas(**canvas_data)
        except ValidationError as exc:
            raise StorageError("World Canvas model output failed schema validation.") from exc

    def _build_canvas_from_agent_data_with_retry(
        self,
        *,
        data: dict[str, Any],
        retry_call,
        source_story_idea: str,
        latest_user_prompt: str,
        existing_canvas: WorldCanvas | None,
    ) -> WorldCanvas:
        try:
            canvas = self._build_canvas_from_agent_data(
                data=data,
                source_story_idea=source_story_idea,
                latest_user_prompt=latest_user_prompt,
                existing_canvas=existing_canvas,
            )
            return self._ensure_minimum_confirmable_canvas(
                canvas,
                source_story_idea=source_story_idea,
                latest_user_prompt=latest_user_prompt,
                existing_canvas=existing_canvas,
            )
        except StorageError as exc:
            if "World Canvas model output failed schema validation." not in str(exc):
                raise
            retry_data = retry_call()
            try:
                canvas = self._build_canvas_from_agent_data(
                    data=retry_data,
                    source_story_idea=source_story_idea,
                    latest_user_prompt=latest_user_prompt,
                    existing_canvas=existing_canvas,
                )
                return self._ensure_minimum_confirmable_canvas(
                    canvas,
                    source_story_idea=source_story_idea,
                    latest_user_prompt=latest_user_prompt,
                    existing_canvas=existing_canvas,
                )
            except StorageError as retry_exc:
                if "World Canvas model output failed schema validation." not in str(retry_exc):
                    raise
                fallback_data = self._fallback_canvas_data_from_story_idea(
                    source_story_idea=source_story_idea,
                    latest_user_prompt=latest_user_prompt,
                )
                return self._build_canvas_from_agent_data(
                    data=fallback_data,
                    source_story_idea=source_story_idea,
                    latest_user_prompt=latest_user_prompt,
                    existing_canvas=existing_canvas,
                )

    def _ensure_minimum_confirmable_canvas(
        self,
        canvas: WorldCanvas,
        *,
        source_story_idea: str,
        latest_user_prompt: str,
        existing_canvas: WorldCanvas | None,
    ) -> WorldCanvas:
        if canvas.hard_rules:
            return canvas
        fallback_canvas = self._build_canvas_from_agent_data(
            data=self._fallback_canvas_data_from_story_idea(
                source_story_idea=source_story_idea,
                latest_user_prompt=latest_user_prompt,
            ),
            source_story_idea=source_story_idea,
            latest_user_prompt=latest_user_prompt,
            existing_canvas=existing_canvas,
        )
        confirmation_note = (
            "模型生成结果缺少可确认硬规则，系统已根据用户输入补入最小硬规则；请用户确认后再继续。"
        )
        return copy_model(
            canvas,
            hard_rules=fallback_canvas.hard_rules,
            soft_rules=canvas.soft_rules or fallback_canvas.soft_rules,
            special_rules_summary=canvas.special_rules_summary or fallback_canvas.special_rules_summary,
            user_confirmation_needed=[
                *canvas.user_confirmation_needed,
                confirmation_note,
            ],
            updated_at=now_iso(),
        )

    def _strict_schema_retry_prompt(self, user_prompt: str) -> str:
        return (
            f"{user_prompt}\n\n"
            "Schema retry: return the same requested World Canvas, but strictly use the "
            "exact JSON keys from the schema. Rule objects must use rule_id and statement. "
            "Unknown rule objects must use unknown_rule_id and summary. Logic conflict "
            "objects must use conflict_id and summary. world_structure must be an object. "
            "user_confirmation_needed must be an array of strings."
        )

    def _normalize_agent_canvas_data(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)
        world_structure = normalized.get("world_structure")
        if isinstance(world_structure, str):
            normalized["world_structure"] = {
                "structure_id": "structure_root_001",
                "name": "",
                "structure_type": "other",
                "summary": world_structure,
                "children": [],
            }
        elif isinstance(world_structure, dict):
            normalized["world_structure"] = self._normalize_world_structure(world_structure)
        else:
            normalized["world_structure"] = {}

        normalized["hard_rules"] = self._normalize_rule_items(
            normalized.get("hard_rules"),
            firmness="hard",
        )
        normalized["soft_rules"] = self._normalize_rule_items(
            normalized.get("soft_rules"),
            firmness="soft",
        )
        normalized["unknown_rules"] = self._normalize_unknown_rule_items(
            normalized.get("unknown_rules")
        )
        normalized["logic_conflicts"] = self._normalize_logic_conflict_items(
            normalized.get("logic_conflicts")
        )

        user_confirmation_needed = normalized.get("user_confirmation_needed")
        if isinstance(user_confirmation_needed, bool):
            normalized["user_confirmation_needed"] = (
                ["模型标记该世界画布需要用户确认。"]
                if user_confirmation_needed
                else []
            )
        elif isinstance(user_confirmation_needed, str):
            normalized["user_confirmation_needed"] = [user_confirmation_needed]
        elif isinstance(user_confirmation_needed, list):
            normalized["user_confirmation_needed"] = [
                str(item).strip()
                for item in user_confirmation_needed
                if str(item).strip()
            ]
        else:
            normalized["user_confirmation_needed"] = []
        normalized["locations"] = self._normalize_named_dict_list(normalized.get("locations"))
        normalized["factions"] = self._normalize_named_dict_list(normalized.get("factions"))
        normalized["species"] = self._normalize_named_dict_list(normalized.get("species"))
        return normalized

    def _normalize_rule_items(self, value: Any, *, firmness: str) -> list[Any]:
        if not isinstance(value, list):
            return []
        normalized: list[Any] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                summary = str(item).strip()
                if summary:
                    normalized.append(
                        {
                            "unknown_rule_id": f"unknown_{index:03d}",
                            "summary": summary,
                            "gap_type": "other",
                        }
                    )
                continue
            rule = dict(item)
            rule.setdefault(
                "rule_id",
                str(rule.get("id") or rule.get("key") or f"rule_{firmness}_{index:03d}"),
            )
            statement = self._first_text_value(
                rule,
                [
                    "statement",
                    "content",
                    "description",
                    "text",
                    "rule",
                    "summary",
                    "name",
                    "title",
                    "detail",
                    "details",
                ],
            )
            if statement:
                rule["statement"] = statement
            rule.setdefault(
                "category",
                str(rule.get("category") or rule.get("type") or "other"),
            )
            rule["firmness"] = firmness
            normalized.append(rule)
        return normalized

    def _normalize_unknown_rule_items(self, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        normalized: list[Any] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                summary = str(item).strip()
                if summary:
                    normalized.append(
                        {
                            "conflict_id": f"conflict_{index:03d}",
                            "summary": summary,
                            "conflict_type": "other",
                        }
                    )
                continue
            unknown = dict(item)
            unknown.setdefault(
                "unknown_rule_id",
                str(unknown.get("id") or unknown.get("key") or f"unknown_{index:03d}"),
            )
            summary = self._first_text_value(
                unknown,
                [
                    "summary",
                    "content",
                    "description",
                    "text",
                    "question",
                    "gap",
                    "unknown",
                    "uncertainty",
                    "name",
                    "title",
                    "detail",
                    "details",
                ],
            )
            if not summary and isinstance(unknown.get("suggested_questions"), list):
                summary = self._first_string(unknown.get("suggested_questions"))
            if not summary:
                summary = "模型识别到一个需要后续澄清的世界规则缺口。"
            if summary:
                unknown["summary"] = summary
            unknown.setdefault(
                "gap_type",
                str(unknown.get("gap_type") or unknown.get("type") or "other"),
            )
            normalized.append(unknown)
        return normalized

    def _normalize_logic_conflict_items(self, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        normalized: list[Any] = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            conflict = dict(item)
            conflict.setdefault(
                "conflict_id",
                str(conflict.get("id") or conflict.get("key") or f"conflict_{index:03d}"),
            )
            summary = self._first_text_value(
                conflict,
                [
                    "summary",
                    "content",
                    "description",
                    "text",
                    "conflict",
                    "name",
                    "title",
                    "detail",
                    "details",
                ],
            )
            if summary:
                conflict["summary"] = summary
            conflict.setdefault(
                "conflict_type",
                str(conflict.get("conflict_type") or conflict.get("type") or "other"),
            )
            normalized.append(conflict)
        return normalized

    def _normalize_world_structure(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(value)
        normalized.setdefault("structure_id", "structure_root_001")
        normalized.setdefault("name", "")
        normalized.setdefault("structure_type", "other")
        normalized.setdefault("summary", "")
        children = normalized.get("children")
        if not isinstance(children, list):
            normalized["children"] = []
            return normalized
        normalized["children"] = [
            child
            if isinstance(child, dict)
            else {
                "name": str(child).strip(),
                "summary": str(child).strip(),
            }
            for child in children
            if isinstance(child, dict) or str(child).strip()
        ]
        return normalized

    def _normalize_named_dict_list(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(item)
                continue
            name = str(item).strip()
            if name:
                normalized.append({"name": name, "summary": name})
        return normalized

    def _fallback_scope_label(self, prompt_text: str, default: str) -> str:
        source = " ".join((prompt_text or "").split())
        for pattern in [
            r"(?:发生在|位于|围绕|关于)([\u4e00-\u9fffA-Za-z0-9·]{2,18}?)(?:的|，|。|,|\.|\s|$)",
            r"([\u4e00-\u9fffA-Za-z0-9·]{0,10}(?:城市|小镇|村庄|学院|学校|社区|校区|实验区|治理区|长安|洛阳|杭州|星球|基地|殖民地|王国|江湖|宫殿|海岛|森林|港口|图书馆))",
        ]:
            match = re.search(pattern, source)
            if match:
                candidate = match.group(1).strip(" 的，。,.；;：:")
                if 2 <= len(candidate) <= 18 and candidate not in {"一个", "一部", "故事", "小说", "世界"}:
                    return candidate
        return default

    def _fallback_canvas_profile(self, prompt_text: str) -> dict[str, str]:
        source = prompt_text or ""
        lowered = source.lower()

        def has_any(*terms: str) -> bool:
            for term in terms:
                needle = term.lower()
                start = 0
                while True:
                    index = lowered.find(needle, start)
                    if index < 0:
                        break
                    clause_start = max(
                        lowered.rfind(delimiter, 0, index)
                        for delimiter in ["。", "！", "？", "；", ";", "\n", ".", "!", "?"]
                    ) + 1
                    clause_prefix = lowered[clause_start:index]
                    negation_markers = [
                        "不要",
                        "避免",
                        "禁止",
                        "排除",
                        "不是",
                        "并非",
                        "不采用",
                        "不使用",
                        "without ",
                        "not ",
                    ]
                    last_negation = max((clause_prefix.rfind(marker) for marker in negation_markers), default=-1)
                    last_contrast = max(clause_prefix.rfind("而是"), clause_prefix.rfind("但"), clause_prefix.rfind("but "))
                    if last_negation < 0 or last_contrast > last_negation:
                        return True
                    start = index + len(needle)
            return False

        if has_any("唐代", "唐朝", "盛唐", "中唐", "长安", "洛阳", "传奇", "志怪", "游侠", "女史", "胡商"):
            scope = self._fallback_scope_label(source, "唐代主要行动区域")
            return {
                "scope": scope,
                "tone": "典雅、奇诡、重视礼法与人物选择",
                "structure_name": scope,
                "structure_type": "historical_region",
                "structure_summary": f"以{scope}为核心舞台，官私秩序、民间传闻、礼法压力和人物行动共同构成世界边界。",
                "history_summary": "关键旧事应从项目前提和用户确认中展开，避免替换为固定古代模板。",
                "geography_summary": "地点层级以用户输入中的城市、坊市、道观、驿馆或行动区域为准，后续可继续补充。",
                "culture_summary": "礼法、人情、身份秩序和民间传闻共同约束角色选择。",
                "special_rules_summary": "奇遇、异象或志怪元素必须有边界、代价和可追踪后果。",
                "phenomenon_rule": "特殊现象或奇遇必须有明确触发条件、可见代价和叙事边界。",
                "knowledge_rule": "角色获得关键信息必须来自行动、见闻、文书、证据或用户确认事实。",
                "soft_rule": "世界细节应服务礼法压力、人物选择和章节冲突。",
                "unknown_summary": "关键旧事或异象来源仍需在后续设定中确认。",
                "unknown_question": "关键旧事或异象来自人为布局、民间传闻、旧案后果，还是更深层规则？",
                "location_summary": "由项目前提指定并等待用户继续细化的唐代行动区域。",
            }
        if has_any("科技", "科幻", "人工智能", "AI", "算法", "数据中台", "审计", "机器人", "自动化", "公共服务", "technology", "sci-fi", "science fiction", "algorithm"):
            scope = self._fallback_scope_label(source, "项目前提指定的科技或治理场域")
            return {
                "scope": scope,
                "tone": "理性、清晰、保留人情温度与社会议题张力",
                "structure_name": scope,
                "structure_type": "speculative_system",
                "structure_summary": f"以{scope}为核心舞台，技术系统、执行机构、具体个体和责任链共同构成冲突边界。",
                "history_summary": "关键技术上线、制度调整或事故背景必须从项目前提和用户确认中展开。",
                "geography_summary": "主要地点以用户输入中的城市、社区、校区、实验区、基地或系统节点为准。",
                "culture_summary": "公共效率、技术透明、个人尊严和基层执行压力共同约束角色选择。",
                "special_rules_summary": "技术、异常或推演机制必须有数据来源、权限边界、责任主体和可追踪后果。",
                "phenomenon_rule": "技术或异常机制只能在明确数据来源、权限条件或模型调用边界内发生。",
                "knowledge_rule": "角色获得关键信息必须来自日志、复核、行动、证据或用户确认事实。",
                "soft_rule": "世界细节应服务技术边界、责任归属和人物选择。",
                "unknown_summary": "关键机制、责任链或事故来源仍需在后续设定中确认。",
                "unknown_question": "关键机制的来源是设计缺陷、权限滥用、历史事故，还是尚未公开的责任链？",
                "location_summary": "由项目前提指定并等待用户继续细化的科技或治理场域。",
            }
        if has_any("爱情", "恋爱", "婚约", "重逢", "告白", "家庭", "亲情", "romance", "love"):
            scope = self._fallback_scope_label(source, "关系变化发生的核心生活空间")
            return {
                "scope": scope,
                "tone": "细腻、温柔、重视关系变化与选择代价",
                "structure_name": scope,
                "structure_type": "relationship_space",
                "structure_summary": f"以{scope}为核心舞台，日常秩序、关系距离、旧事压力和人物选择共同构成世界边界。",
                "history_summary": "关系旧事和情感裂痕必须从项目前提和用户确认中展开。",
                "geography_summary": "主要地点以用户输入中的生活空间、工作场所或重逢地点为准。",
                "culture_summary": "亲密关系、家庭期待、社会眼光和个人边界共同约束角色选择。",
                "special_rules_summary": "情感转折必须来自行动、误解修正或价值选择，不能凭空和解。",
                "phenomenon_rule": "关系状态变化必须有行动、对话、误解修正或价值选择支撑。",
                "knowledge_rule": "角色理解彼此必须来自互动、共同经历或已确认旧事。",
                "soft_rule": "世界细节应服务关系变化、情绪递进和选择代价。",
                "unknown_summary": "关系裂痕或旧事来源仍需在后续设定中确认。",
                "unknown_question": "关系裂痕来自误会、价值差异、家庭压力，还是未说出口的旧事？",
                "location_summary": "由项目前提指定并等待用户继续细化的关系核心空间。",
            }
        if has_any("魔幻", "魔法", "奇幻", "低魔", "仙侠", "修真", "妖", "灵", "fantasy", "magic"):
            scope = self._fallback_scope_label(source, "项目前提指定的幻想舞台")
            return {
                "scope": scope,
                "tone": "奇诡、克制、重视规则代价",
                "structure_name": scope,
                "structure_type": "fantasy_domain",
                "structure_summary": f"以{scope}为核心舞台，幻想规则、普通秩序、禁忌边界和人物选择共同构成世界边界。",
                "history_summary": "幻想规则的旧源、禁忌或代价必须从项目前提和用户确认中展开。",
                "geography_summary": "主要地点以用户输入中的城市、宗门、村庄、遗迹或边界区域为准。",
                "culture_summary": "普通秩序、力量规则、禁忌代价和人情关系共同约束角色选择。",
                "special_rules_summary": "魔法、异能或幻想规则必须有边界、代价和不可越权的限制。",
                "phenomenon_rule": "幻想规则只能在明确触发条件、消耗或代价范围内发生。",
                "knowledge_rule": "角色获得规则知识必须来自行动、传承、证据或用户确认事实。",
                "soft_rule": "世界细节应服务规则代价、人物选择和章节冲突。",
                "unknown_summary": "核心规则来源或禁忌边界仍需在后续设定中确认。",
                "unknown_question": "核心规则来自自然秩序、旧契约、人为制造，还是被隐藏的历史后果？",
                "location_summary": "由项目前提指定并等待用户继续细化的幻想舞台。",
            }
        if has_any("喜剧", "搞笑", "轻松", "荒诞", "日常", "comedy", "comic"):
            scope = self._fallback_scope_label(source, "项目前提指定的日常行动空间")
            return {
                "scope": scope,
                "tone": "轻快、清晰、用反差推动冲突",
                "structure_name": scope,
                "structure_type": "daily_comedy_space",
                "structure_summary": f"以{scope}为核心舞台，日常规则、误会、反差行动和人物选择共同构成世界边界。",
                "history_summary": "误会来源和反差前提必须从项目前提和用户确认中展开。",
                "geography_summary": "主要地点以用户输入中的生活空间、工作场所或事件发生地为准。",
                "culture_summary": "日常规则、社交压力和人物反差共同约束喜剧冲突。",
                "special_rules_summary": "喜剧转折必须有因果和行动后果，不能只靠随机巧合推进。",
                "phenomenon_rule": "误会或荒诞事件必须有可理解的触发条件和后续影响。",
                "knowledge_rule": "角色获得关键信息必须来自互动、误会修正或用户确认事实。",
                "soft_rule": "世界细节应服务节奏、反差和人物选择。",
                "unknown_summary": "关键误会或荒诞事件的来源仍需在后续设定中确认。",
                "unknown_question": "关键误会来自信息差、规则漏洞、关系隐瞒，还是环境反差？",
                "location_summary": "由项目前提指定并等待用户继续细化的日常行动空间。",
            }
        if has_any("悬疑", "推理", "侦探", "案件", "谜团", "犯罪", "mystery", "detective", "crime", "thriller"):
            scope = self._fallback_scope_label(source, "项目前提指定的调查舞台")
            return {
                "scope": scope,
                "tone": "克制、紧张、重视因果与证据",
                "structure_name": scope,
                "structure_type": "investigation_space",
                "structure_summary": f"以{scope}为核心舞台，线索、见证、信息差和行动风险共同构成世界边界。",
                "history_summary": "关键旧案或遮蔽事实必须从项目前提和用户确认中展开。",
                "geography_summary": "主要地点以用户输入中的案发地、调查地或相关区域为准。",
                "culture_summary": "公开秩序、隐瞒压力、证据链和人物动机共同约束角色选择。",
                "special_rules_summary": "线索、异常或犯罪事实必须有触发条件、证据链和可追踪后果。",
                "phenomenon_rule": "关键异常或线索只能在明确触发条件下出现，并留下可追踪后果。",
                "knowledge_rule": "角色获得关键信息必须来自行动、证据、见证或已确认记忆。",
                "soft_rule": "世界细节应服务线索推进、因果清晰和角色动机。",
                "unknown_summary": "核心遮蔽事实或关键来源仍需在后续设定中确认。",
                "unknown_question": "核心遮蔽事实来自人为掩盖、旧事故、误导证词，还是更深层规则？",
                "location_summary": "由项目前提指定并等待用户继续细化的调查舞台。",
            }
        scope = self._fallback_scope_label(source, "项目前提指定的核心舞台")
        return {
            "scope": scope,
            "tone": "清晰、克制、随题材调整",
            "structure_name": scope,
            "structure_type": "story_stage",
            "structure_summary": f"以{scope}为核心舞台，目标、阻力、人物选择和世界边界共同构成最小可运行设定。",
            "history_summary": "关键旧事必须从项目前提和用户确认中展开，不能替换为演示故事或固定模板。",
            "geography_summary": "主要地点以项目前提中的地点和后续确认信息为准。",
            "culture_summary": "社会关系、组织压力和日常秩序需要服务项目前提中的核心冲突。",
            "special_rules_summary": "所有特殊现象或关键规则都必须有触发条件、边界和可追踪后果。",
            "phenomenon_rule": "关键规则或事件必须有明确触发条件、边界和可追踪后果。",
            "knowledge_rule": "角色获得关键信息必须来自行动、证据、见闻或用户确认事实。",
            "soft_rule": "世界细节应服务角色选择、章节冲突和后续连续性检查。",
            "unknown_summary": "核心机制、关键旧事或主要阻力仍需在后续设定中确认。",
            "unknown_question": "核心机制或主要阻力来自人物选择、组织压力、旧事后果，还是特殊规则？",
            "location_summary": "由项目前提指定并等待用户继续细化的主要故事地点。",
        }

    def _fallback_canvas_data_from_story_idea(
        self,
        *,
        source_story_idea: str,
        latest_user_prompt: str,
    ) -> dict[str, Any]:
        combined_prompt = "\n".join(
            part for part in [source_story_idea, latest_user_prompt] if part
        )
        compact_prompt = " ".join(combined_prompt.split())
        story_direction = compact_prompt[:260] or "根据项目前提建立世界事实基础。"
        prompt_evidence = self._fallback_prompt_fidelity_evidence(source_story_idea)
        profile = self._fallback_canvas_profile(compact_prompt)
        source = (
            "fallback_from_project_story_premise"
            if "ProjectStoryPremise" in source_story_idea
            else "fallback_from_user_prompt"
        )
        hard_rule_statements = [
            "世界画布必须保留当前项目的用户故事前提，不能替换为演示故事或模板故事。",
            f"世界画布必须保留以下项目前提证据：{prompt_evidence or story_direction}",
            profile["phenomenon_rule"],
            profile["knowledge_rule"],
        ]
        soft_rule_statements = [
            "叙事应保持因果清晰，优先保护项目前提、世界规则和角色动机的一致性。",
            profile["soft_rule"],
        ]
        hard_rules = [
            {
                "rule_id": f"rule_hard_fallback_{index:03d}",
                "statement": statement,
                "category": "memory" if "记忆" in statement else "other",
                "firmness": "hard",
                "source": source,
                "applies_to": ["world"],
                "rationale": "模型输出格式无效时，根据当前项目故事前提构造最小可确认硬规则。",
                "risk_if_changed": "改变该规则可能破坏后续章节、角色行为和连续性检查。",
                "version_id": WORLD_CANVAS_VERSION_ID,
            }
            for index, statement in enumerate(hard_rule_statements, start=1)
        ]
        soft_rules = [
            {
                "rule_id": f"rule_soft_fallback_{index:03d}",
                "statement": statement,
                "category": "other",
                "firmness": "soft",
                "source": source,
                "applies_to": ["world"],
                "rationale": "用于保持当前项目前提的题材和语气方向。",
                "risk_if_changed": "改变该规则可能削弱故事风格一致性。",
                "version_id": WORLD_CANVAS_VERSION_ID,
            }
            for index, statement in enumerate(soft_rule_statements, start=1)
        ]
        return {
            "world_canvas_id": "",
            "project_id": self._current_project_id(),
            "status": "draft",
            "story_direction": story_direction,
            "scope": profile["scope"],
            "tone": profile["tone"],
            "world_structure": {
                "structure_id": "structure_root_001",
                "name": profile["structure_name"],
                "structure_type": profile["structure_type"],
                "summary": f"{profile['structure_summary']} 项目前提：{story_direction[:120]}",
                "children": [],
            },
            "history_summary": profile["history_summary"],
            "geography_summary": profile["geography_summary"],
            "culture_summary": profile["culture_summary"],
            "special_rules_summary": profile["special_rules_summary"],
            "hard_rules": hard_rules,
            "soft_rules": soft_rules,
            "unknown_rules": [
                {
                    "unknown_rule_id": "unknown_fallback_origin_001",
                    "summary": profile["unknown_summary"],
                    "gap_type": "missing_origin",
                    "why_it_matters": "来源会影响角色动机、章节冲突和终局解释。",
                    "related_rule_ids": [],
                    "suggested_questions": [profile["unknown_question"]],
                    "severity": "medium",
                    "status": "open",
                }
            ],
            "logic_conflicts": [],
            "user_confirmation_needed": [
                "当前世界画布由项目前提和格式降级路径生成，请用户确认后再进入角色、框架和章节计划。"
            ],
            "locations": [{"name": profile["scope"], "summary": profile["location_summary"]}],
            "factions": [],
            "species": [],
            "source_story_idea": source_story_idea,
            "latest_user_prompt": latest_user_prompt,
            "version_id": WORLD_CANVAS_VERSION_ID,
        }

    def _fallback_prompt_fidelity_evidence(self, source_story_idea: str) -> str:
        prefixes = (
            "Required markers:",
            "Required story elements:",
            "User story premise:",
            "Safe premise summary:",
        )
        evidence_parts: list[str] = []
        for raw_line in (source_story_idea or "").splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            if any(line.startswith(prefix) for prefix in prefixes):
                evidence_parts.append(line[:420])
        if not evidence_parts:
            return " ".join((source_story_idea or "").split())[:420]
        return "；".join(evidence_parts)[:900]

    def _first_text_value(self, data: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _first_string(self, value: Any) -> str:
        if not isinstance(value, list):
            return ""
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""

    def _resolve_world_canvas_id(
        self,
        existing_canvas: WorldCanvas | None,
        candidate_id: str,
    ) -> str:
        if existing_canvas:
            return existing_canvas.world_canvas_id
        story_bible_id = self._read_story_bible_world_canvas_id()
        if story_bible_id:
            return story_bible_id
        return candidate_id or DEFAULT_WORLD_CANVAS_ID

    def _read_story_bible_world_canvas_id(self) -> str:
        if not self.store.exists(self.story_bible_file):
            return ""
        story_bible = self.store.read(self.story_bible_file)
        return str(story_bible.get("world_canvas_id") or "")

    def _sync_story_bible_world_canvas_id(self, world_canvas_id: str) -> None:
        if not self.store.exists(self.story_bible_file):
            return
        story_bible = self.store.read(self.story_bible_file)
        updated = dict(story_bible)
        updated["project_id"] = self._current_project_id()
        updated["world_canvas_id"] = world_canvas_id
        if updated != story_bible:
            self.store.write(self.story_bible_file, updated)

    def _append_confirmation_decision(
        self,
        canvas: WorldCanvas,
        user_input: str | None,
    ) -> Decision:
        decisions = self._read_decisions()
        decision = Decision(
            decision_id=f"decision_world_canvas_confirm_{len(decisions) + 1:03d}",
            decision_type="confirm",
            target_type="world_canvas",
            target_id=canvas.world_canvas_id,
            user_input=(
                user_input
                or "用户确认当前 World Canvas 作为后续生成的世界事实基础。"
            ),
            created_at=now_iso(),
        )
        decisions.append(model_to_dict(decision))
        self.store.write(self.decisions_file, decisions)
        return decision

    def _read_decisions(self) -> list[dict[str, Any]]:
        if not self.store.exists(self.decisions_file):
            return []
        decisions = self.store.read_list(self.decisions_file)
        return [dict(item) for item in decisions if isinstance(item, dict)]

    def _update_project_step(self, current_step: str, status: str) -> None:
        if not self.store.exists(self.project_file):
            return
        project = self.store.read(self.project_file)
        updated = dict(project)
        updated["project_id"] = self._current_project_id()
        updated["current_step"] = current_step
        updated["status"] = status
        updated["updated_at"] = now_iso()
        if updated != project:
            self.store.write(self.project_file, updated)

    def _stamp_unknown_rule(
        self,
        rule: UnknownRule,
        checked_at: str,
    ) -> UnknownRule:
        updates = {"last_checked_at": checked_at}
        if not rule.first_detected_at:
            updates["first_detected_at"] = checked_at
        return copy_model(rule, **updates)

    def _needs_origin_gap(
        self,
        combined_text: str,
        unknown_rules: list[UnknownRule],
    ) -> bool:
        if any(rule.gap_type == "missing_origin" for rule in unknown_rules):
            return False
        has_special_rule = any(marker in combined_text for marker in ["异常", "魔法", "超自然", "规则", "钟"])
        has_origin = any(marker in combined_text for marker in ["来源", "起源", "制造", "诞生"])
        return has_special_rule and not has_origin

    def _needs_cost_gap(
        self,
        combined_text: str,
        unknown_rules: list[UnknownRule],
    ) -> bool:
        if any(rule.gap_type == "missing_cost" for rule in unknown_rules):
            return False
        has_special_rule = any(marker in combined_text for marker in ["异常", "魔法", "超自然", "规则", "钟"])
        has_cost = any(marker in combined_text for marker in ["代价", "成本", "限制", "损害"])
        return has_special_rule and not has_cost

    def _has_midnight_random_conflict(self, rule_texts: list[str]) -> bool:
        has_midnight_only = any(
            ("午夜" in text or "零点" in text) and ("只" in text or "固定" in text)
            for text in rule_texts
        )
        has_random_ring = any("随机" in text and ("鸣" in text or "钟" in text) for text in rule_texts)
        return has_midnight_only and has_random_ring

    def _dedupe_unknown_rules(
        self,
        unknown_rules: list[UnknownRule],
    ) -> list[UnknownRule]:
        seen: set[tuple[str, str]] = set()
        deduped: list[UnknownRule] = []
        for rule in unknown_rules:
            key = (rule.gap_type, rule.summary)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(rule)
        return deduped

    def _dedupe_logic_conflicts(
        self,
        conflicts: list[LogicConflict],
    ) -> list[LogicConflict]:
        seen: set[str] = set()
        deduped: list[LogicConflict] = []
        for conflict in conflicts:
            if conflict.summary in seen:
                continue
            seen.add(conflict.summary)
            deduped.append(conflict)
        return deduped
