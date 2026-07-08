import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.backend.models.composite_agent import (
    COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES,
    COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES,
    PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
    CompositeAgentDefinition,
    CompositeAgentOutputContract,
    CompositeAgentRegistry,
    CompositeAgentRequiredServiceSequence,
    CompositeAgentRunRequest,
    CompositeAgentRunResult,
    CompositeAgentRunTrace,
    CompositeAgentServiceStep,
    CompositeAgentStoryFactDelta,
    GateReviewRequest,
    GateReviewReceipt,
    IntegratorReport,
    SubAgentTrace,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "app"
DOCS_DIR = APP_DIR / "docs"

M0_INTAKE_REPORT_PATH = DOCS_DIR / "phase85c_m0_composite_runtime_intake_report.json"
M0_AGENT_LIKE_INVENTORY_PATH = DOCS_DIR / "phase85c_m0_agent_like_inventory.json"
M0_CONTRACT_GAP_REPORT_PATH = DOCS_DIR / "phase85c_m0_contract_gap_report.json"
M0_READINESS_REPORT_PATH = DOCS_DIR / "phase85c_m0_readiness_report.md"
M11_HANDOFF_PATH = DOCS_DIR / "phase85b_m11_composite_agent_handoff.json"

COMPOSITE_AGENT_OUTPUT_CONTRACT_ID = "phase85c_m1_composite_agent_output_contract_v1"


class CompositeAgentRegistryService:
    """Builds M1 contract-only Composite Agent registry objects.

    This service intentionally reads only audit/report artifacts. It does not
    call runtime business services and does not write source story data.
    """

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        docs_dir: Path | None = None,
    ) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.docs_dir = docs_dir or (self.repo_root / "app" / "docs")
        self.m0_intake_path = self.docs_dir / M0_INTAKE_REPORT_PATH.name
        self.m0_inventory_path = self.docs_dir / M0_AGENT_LIKE_INVENTORY_PATH.name
        self.m0_gap_path = self.docs_dir / M0_CONTRACT_GAP_REPORT_PATH.name
        self.m0_readiness_path = self.docs_dir / M0_READINESS_REPORT_PATH.name
        self.m11_handoff_path = self.docs_dir / M11_HANDOFF_PATH.name

    def load_m0_intake_report(self) -> dict[str, Any]:
        return self._read_json(self.m0_intake_path)

    def load_m0_agent_like_inventory(self) -> dict[str, Any]:
        return self._read_json(self.m0_inventory_path)

    def load_m0_contract_gap_report(self) -> dict[str, Any]:
        return self._read_json(self.m0_gap_path)

    def load_m11_handoff(self) -> dict[str, Any]:
        return self._read_json(self.m11_handoff_path)

    def load_m0_artifacts(self) -> dict[str, Any]:
        return {
            "intake_report": self.load_m0_intake_report(),
            "agent_like_inventory": self.load_m0_agent_like_inventory(),
            "contract_gap_report": self.load_m0_contract_gap_report(),
            "readiness_report_exists": self.m0_readiness_path.exists(),
            "readiness_report_path": self._report_path(self.m0_readiness_path),
        }

    def m11_allowed_responsibilities(self) -> list[str]:
        handoff = self.load_m11_handoff()
        return _unique_strings(handoff.get("allowed_composite_agent_responsibilities"))

    def m11_forbidden_actions(self) -> list[str]:
        handoff = self.load_m11_handoff()
        return _unique_strings(handoff.get("forbidden_composite_agent_actions"))

    def m11_required_service_sequence(self) -> list[str]:
        handoff = self.load_m11_handoff()
        return _unique_strings(handoff.get("required_service_sequence"))

    def build_output_contract(self) -> CompositeAgentOutputContract:
        return CompositeAgentOutputContract(
            output_contract_id=COMPOSITE_AGENT_OUTPUT_CONTRACT_ID,
            version_id=PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
            allowed_output_types=sorted(COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES),
            forbidden_output_types=sorted(COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES),
            default_authority_level="candidate",
            candidate_only_default=True,
            can_write_story_facts_directly=False,
            safe_summary=(
                "Composite Agent outputs are candidate-only contract payloads in M1."
            ),
        )

    def build_default_registry(self) -> CompositeAgentRegistry:
        allowed = self.m11_allowed_responsibilities()
        forbidden = self.m11_forbidden_actions()
        output_contract = self.build_output_contract()
        return CompositeAgentRegistry(
            registry_id="phase85c_m1_default_composite_agent_registry",
            version_id=PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
            agents=self._default_agent_definitions(
                allowed=allowed,
                forbidden=forbidden,
                output_contract_id=output_contract.output_contract_id,
            ),
            required_service_sequence=self.build_required_service_sequence(),
            source_handoff_path=self._report_path(self.m11_handoff_path),
            source_m0_report_path=self._report_path(self.m0_intake_path),
            safe_summary=(
                "M1 registry defines contract-only Composite Agent boundaries; no "
                "runtime orchestration is enabled."
            ),
            warnings=[
                "contract_only_registry_no_agent_execution",
                "scene_environment_stage_agent_future_only",
            ],
        )

    def build_required_service_sequence(self) -> CompositeAgentRequiredServiceSequence:
        sequence = self.m11_required_service_sequence()
        gap_report = self.load_m0_contract_gap_report()
        concept_mapping = gap_report.get("concept_name_mapping", {})
        steps: list[CompositeAgentServiceStep] = []
        for index, concept_name in enumerate(sequence):
            mapping_items = concept_mapping.get(concept_name, [])
            paths = [
                str(item.get("path", "")).strip()
                for item in mapping_items
                if isinstance(item, dict) and item.get("path")
            ]
            step_id = _slug(concept_name)
            steps.append(
                CompositeAgentServiceStep(
                    step_id=step_id,
                    step_name=concept_name,
                    order_index=index,
                    concept_name=concept_name,
                    current_implementation_paths=paths,
                    must_run_before=[_slug(sequence[index + 1])]
                    if index + 1 < len(sequence)
                    else [],
                    must_run_after=[_slug(sequence[index - 1])] if index > 0 else [],
                    safe_summary=f"Contract sequence step for {concept_name}.",
                )
            )
        return CompositeAgentRequiredServiceSequence(
            sequence_id="phase85c_m1_required_service_sequence",
            version_id=PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
            steps=steps,
            must_preserve_candidate_gate_commit_writeback_order=True,
            safe_summary=(
                "Required sequence preserves candidate, gate, user confirmation, "
                "commit, and writeback ordering."
            ),
        )

    def normalize_run_request(
        self, request: CompositeAgentRunRequest
    ) -> CompositeAgentRunRequest:
        if request.run_id.strip():
            return request
        seed_payload = {
            "agent_name": request.agent_name,
            "project_id": request.project_id,
            "chapter_id": request.chapter_id,
            "scene_id": request.scene_id,
            "scene_index": request.scene_index,
            "target_scope": request.target_scope,
            "source_context_ids": request.source_context_ids,
            "input_refs": request.input_refs,
            "requested_output_contract_id": request.requested_output_contract_id,
            "requested_authority_level": request.requested_authority_level,
            "caller": request.caller,
        }
        digest = hashlib.sha256(
            json.dumps(seed_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return request.copy(update={"run_id": f"composite_run_{digest}"})

    def build_contract_only_run_result(
        self,
        request: CompositeAgentRunRequest,
    ) -> CompositeAgentRunResult:
        normalized = self.normalize_run_request(request)
        trace = SubAgentTrace(
            sub_agent_name=normalized.agent_name,
            node_kind="contract_registry_fixture",
            output_type="candidate",
            authority_level=normalized.requested_authority_level,
            confidence=1.0,
            source_ids=normalized.source_context_ids,
            input_fingerprint=_fingerprint(normalized.dict()),
            output_summary="Contract-only candidate fixture; no agent execution.",
            warnings=["contract_only_no_runtime_execution"],
            created_at=now_iso(),
        )
        integrator = IntegratorReport(
            integrator_report_id=f"integrator_{normalized.run_id}",
            agent_name=normalized.agent_name,
            merged_output_types=["candidate"],
            source_trace_ids=[trace.input_fingerprint],
            conflict_categories=[],
            confidence=1.0,
            candidate_only=True,
            can_write_story_facts_directly=False,
            safe_summary="M1 integrator fixture merges no runtime outputs.",
            warnings=["contract_only_integrator_placeholder"],
        )
        gate_request = GateReviewRequest(
            gate_review_request_id=f"gate_request_{normalized.run_id}",
            agent_name=normalized.agent_name,
            requested_gates=[
                "continuity_gate",
                "apparent_contradiction_gate",
                "quality_gate",
                "objective_fact_boundary",
            ],
            candidate_output_refs=[f"candidate_output_{normalized.run_id}"],
            reason="M1 contract fixture records required downstream gate review.",
            does_not_mark_gate_passed=True,
            candidate_only=True,
            safe_summary="Gate review request placeholder; no gate was executed.",
        )
        gate_receipt = GateReviewReceipt(
            gate_review_receipt_id=f"gate_receipt_{normalized.run_id}",
            gate_name="contract_placeholder_gate",
            decision="not_executed_contract_only",
            source_request_id=gate_request.gate_review_request_id,
            issued_by="phase85c_m1_registry_service",
            does_not_commit_story_facts=True,
            safe_summary="Contract placeholder receipt does not mark any gate passed.",
            warnings=["no_gate_pipeline_execution"],
        )
        return CompositeAgentRunResult(
            run_id=normalized.run_id,
            agent_name=normalized.agent_name,
            status="contract_only_not_executed",
            authority_level=normalized.requested_authority_level,
            candidate_only=True,
            can_write_story_facts_directly=False,
            sub_agent_traces=[trace],
            integrator_report=integrator,
            gate_review_requests=[gate_request],
            gate_review_receipts=[gate_receipt],
            candidate_outputs=[
                {
                    "candidate_output_id": f"candidate_output_{normalized.run_id}",
                    "output_type": "candidate",
                    "authority_level": normalized.requested_authority_level,
                    "safe_summary": "Schema fixture only; no story fact mutation.",
                }
            ],
            output_refs=[f"candidate_output_{normalized.run_id}"],
            blocking_findings=[],
            warnings=["contract_only_result_fixture"],
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary="Composite Agent M1 contract fixture returned no runtime output.",
            created_at=now_iso(),
        )

    def build_contract_only_run_trace(
        self,
        request: CompositeAgentRunRequest,
        result: CompositeAgentRunResult,
    ) -> CompositeAgentRunTrace:
        normalized = self.normalize_run_request(request)
        return CompositeAgentRunTrace(
            run_trace_id=f"trace_{normalized.run_id}",
            run_id=normalized.run_id,
            agent_name=normalized.agent_name,
            version_id=PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
            source_context_ids=normalized.source_context_ids,
            input_refs=normalized.input_refs,
            sub_agent_traces=result.sub_agent_traces,
            integrator_report=result.integrator_report,
            gate_review_requests=result.gate_review_requests,
            gate_review_receipts=result.gate_review_receipts,
            authority_level=result.authority_level,
            candidate_only=True,
            can_write_story_facts_directly=False,
            story_fact_delta=CompositeAgentStoryFactDelta(),
            safe_summary="Composite Agent M1 trace fixture; no runtime execution.",
            warnings=["contract_only_trace_fixture"],
            created_at=now_iso(),
        )

    def source_paths(self) -> dict[str, str]:
        return {
            "m0_intake_report": self._report_path(self.m0_intake_path),
            "m0_agent_like_inventory": self._report_path(self.m0_inventory_path),
            "m0_contract_gap_report": self._report_path(self.m0_gap_path),
            "m0_readiness_report": self._report_path(self.m0_readiness_path),
            "m11_handoff": self._report_path(self.m11_handoff_path),
        }

    def _default_agent_definitions(
        self,
        *,
        allowed: list[str],
        forbidden: list[str],
        output_contract_id: str,
    ) -> list[CompositeAgentDefinition]:
        def responsibilities(*items: str) -> list[str]:
            return [item for item in items if item in allowed]

        now = now_iso()
        defaults = [
            {
                "agent_name": "ChapterAgent",
                "display_name": "Chapter Agent",
                "target_scope": "chapter",
                "runtime_status": "contract_only",
                "agent_kind": "runtime_agent",
                "allowed_responsibilities": responsibilities(
                    "orchestrate", "aggregate", "route state"
                ),
                "default_authority_level": "candidate",
                "required_input_contracts": [
                    "chapter_role_input_builder",
                    "framework_package_contract",
                ],
                "required_gates": ["quality_gate"],
                "implementation_anchor": ["app/backend/agents/chapter_agent.py"],
                "safe_summary": "ChapterAgent is registered as contract-only in M1.",
            },
            {
                "agent_name": "SceneAgent",
                "display_name": "Scene Agent",
                "target_scope": "scene",
                "runtime_status": "adapter_ready",
                "agent_kind": "runtime_agent",
                "allowed_responsibilities": responsibilities(
                    "orchestrate", "aggregate", "route state", "link evidence"
                ),
                "default_authority_level": "candidate",
                "required_input_contracts": [
                    "scene_participation_package",
                    "scene_memory_pack",
                    "abcd_story_information_package",
                ],
                "required_gates": [
                    "continuity_gate",
                    "apparent_contradiction_gate",
                    "quality_gate",
                    "objective_fact_boundary",
                ],
                "implementation_anchor": [
                    "app/backend/agents/scene_information_agent.py",
                    "app/backend/services/scene_generation_service.py",
                    "app/backend/services/composite_scene_agent_service.py",
                    "app/backend/scripts/verify_phase85c_m4_sceneagent_composite_wrapper.py",
                ],
                "safe_summary": "SceneAgent has an M4 backend composite wrapper.",
            },
            {
                "agent_name": "SceneEnvironmentStageAgent",
                "display_name": "Scene Environment Stage Agent",
                "target_scope": "scene_environment",
                "runtime_status": "future_only",
                "agent_kind": "future_placeholder",
                "allowed_responsibilities": responsibilities("coordinate fallback"),
                "default_authority_level": "read_only",
                "required_input_contracts": ["future_environment_context"],
                "required_gates": [],
                "implementation_anchor": [],
                "safe_summary": (
                    "SceneEnvironmentStageAgent is a future-only placeholder in M1."
                ),
                "warnings": ["future_phase_not_implemented"],
            },
            {
                "agent_name": "CharacterPsychologyActionIntentAgent",
                "display_name": "Character Psychology Action Intent Agent",
                "target_scope": "character_scene_intent",
                "runtime_status": "adapter_ready",
                "agent_kind": "runtime_agent",
                "allowed_responsibilities": responsibilities(
                    "aggregate", "link evidence", "merge candidates"
                ),
                "default_authority_level": "candidate",
                "required_input_contracts": [
                    "scene_participation_package",
                    "tiered_character_context",
                ],
                "required_gates": ["objective_fact_boundary", "quality_gate"],
                "implementation_anchor": [
                    "app/backend/services/character_intent_service.py",
                    "app/backend/models/character_intent.py",
                    "app/backend/services/composite_character_intent_agent_service.py",
                    "app/backend/scripts/verify_phase85c_m3_character_intent_composite_agent.py",
                ],
                "safe_summary": (
                    "CharacterPsychologyActionIntentAgent has an M3 backend composite wrapper."
                ),
            },
            {
                "agent_name": "AuthorialIntentAgent",
                "display_name": "Authorial Intent Agent",
                "target_scope": "authorial_intent",
                "runtime_status": "contract_only",
                "agent_kind": "runtime_agent",
                "allowed_responsibilities": responsibilities("link evidence"),
                "default_authority_level": "read_only",
                "required_input_contracts": ["authorial_intent_context"],
                "required_gates": ["quality_gate"],
                "implementation_anchor": [
                    "app/backend/agents/authorial_intent_agent.py",
                    "app/backend/services/authorial_intent_service.py",
                ],
                "safe_summary": (
                    "AuthorialIntentAgent is soft intent only and never a hard rule."
                ),
            },
            {
                "agent_name": "WriterAgent",
                "display_name": "Writer Agent",
                "target_scope": "writer_candidate_draft",
                "runtime_status": "adapter_ready",
                "agent_kind": "writer_adapter",
                "allowed_responsibilities": responsibilities(
                    "aggregate", "link evidence"
                ),
                "default_authority_level": "candidate",
                "required_input_contracts": [
                    "abcd_story_information_package",
                    "gate_reviewed_writer_input",
                ],
                "required_gates": [
                    "continuity_gate",
                    "apparent_contradiction_gate",
                    "quality_gate",
                    "objective_fact_boundary",
                    "user_confirmation_boundary",
                ],
                "implementation_anchor": [
                    "app/backend/agents/write_agent.py",
                    "app/backend/services/composite_writer_agent_service.py",
                    "app/backend/scripts/verify_phase85c_m6_writeragent_composite_wrapper.py",
                ],
                "safe_summary": (
                    "WriterAgent has an M6 backend composite wrapper for "
                    "candidate-only synopsis/prose drafting from reviewed writer inputs."
                ),
            },
            {
                "agent_name": "MemoryCuratorAgent",
                "display_name": "Memory Curator Agent",
                "target_scope": "memory_candidate",
                "runtime_status": "adapter_ready",
                "agent_kind": "memory_adapter",
                "allowed_responsibilities": responsibilities(
                    "aggregate", "link evidence", "merge candidates"
                ),
                "default_authority_level": "candidate",
                "required_input_contracts": [
                    "scene_commit_context",
                    "tiered_memory_writeback_contract",
                ],
                "required_gates": ["objective_fact_boundary"],
                "implementation_anchor": [
                    "app/backend/agents/memory_curator_agent.py",
                    "app/backend/services/composite_memory_curator_agent_service.py",
                    "app/backend/scripts/verify_phase85c_m5_memory_curator_composite_agent.py",
                ],
                "safe_summary": (
                    "MemoryCuratorAgent has an M5 backend composite wrapper for "
                    "candidate-only memory context, promotion, and writeback-plan projection."
                ),
            },
            {
                "agent_name": "ContinuityAgent",
                "display_name": "Continuity Agent",
                "target_scope": "gate_review",
                "runtime_status": "contract_only",
                "agent_kind": "gate_adapter",
                "allowed_responsibilities": responsibilities(
                    "aggregate", "link evidence", "route state"
                ),
                "default_authority_level": "read_only",
                "required_input_contracts": [
                    "continuity_context",
                    "apparent_contradiction_context",
                    "quality_gate_context",
                ],
                "required_gates": ["continuity_gate"],
                "implementation_anchor": [
                    "app/backend/services/continuity_gate_service.py",
                    "app/backend/services/abcd_runtime_gate_integration_service.py",
                ],
                "safe_summary": (
                    "ContinuityAgent is a gate adapter only; it does not resolve issues."
                ),
            },
        ]
        return [
            CompositeAgentDefinition(
                **item,
                version_id=PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
                forbidden_actions=forbidden,
                output_contract_id=output_contract_id,
                candidate_only_default=True,
                can_write_story_facts_directly=False,
                sub_agent_visibility="internal_only",
                created_at=now,
                updated_at=now,
            )
            for item in defaults
        ]

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Missing Composite Agent artifact: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _report_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            return str(path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _slug(value: str) -> str:
    result = []
    previous_was_sep = False
    for char in value.lower():
        if char.isalnum():
            result.append(char)
            previous_was_sep = False
        elif not previous_was_sep:
            result.append("_")
            previous_was_sep = True
    return "".join(result).strip("_")


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        raw_values: list[Any] = []
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
