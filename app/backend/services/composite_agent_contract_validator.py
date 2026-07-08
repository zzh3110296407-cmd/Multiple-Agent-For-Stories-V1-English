import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.backend.core.config import settings
from app.backend.models.composite_agent import (
    COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES,
    COMPOSITE_AGENT_AUTHORITY_LEVELS,
    COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES,
    COMPOSITE_AGENT_M1_DEFAULT_AUTHORITY_LEVELS,
    PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_VERSION,
    CompositeAgentDefinition,
    CompositeAgentRegistry,
    CompositeAgentRunRequest,
    CompositeAgentRunResult,
    CompositeAgentRunTrace,
    CompositeAgentStoryFactDelta,
    SubAgentTrace,
)
from app.backend.services.composite_agent_registry_service import (
    COMPOSITE_AGENT_OUTPUT_CONTRACT_ID,
    CompositeAgentRegistryService,
)


PASS_MARKER = "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: PASS"

BLOCKED_MARKERS = {
    "missing_m0": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_MISSING_M0_BASELINE",
    "missing_m11": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_MISSING_M11_HANDOFF",
    "invalid_handoff": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_INVALID_HANDOFF",
    "registry": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_AGENT_REGISTRY_INCOMPLETE",
    "authority": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_AUTHORITY_GUARD",
    "schema": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_SCHEMA_VALIDATION",
    "compile": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_BACKEND_COMPILE",
    "story_fact_mutation": "PHASE85C_M1_COMPOSITE_AGENT_CONTRACT_REGISTRY: BLOCKED_STORY_FACT_MUTATION",
}

REQUIRED_AGENT_NAMES = [
    "ChapterAgent",
    "SceneAgent",
    "SceneEnvironmentStageAgent",
    "CharacterPsychologyActionIntentAgent",
    "AuthorialIntentAgent",
    "WriterAgent",
    "MemoryCuratorAgent",
    "ContinuityAgent",
]

SOURCE_STORY_FACT_FILES = [
    "events.json",
    "memory_records.json",
    "state_changes.json",
    "characters.json",
    "relationships.json",
    "scenes.json",
    "story_information_items.json",
]

EXPECTED_M11_SEQUENCE = [
    "ChapterRoleInputBuilder",
    "CDRoleFunctionNeed",
    "SceneRoleNeedResolver",
    "SceneParticipantSelection",
    "SceneParticipationPackage",
    "SceneMemoryPack / TieredCharacterContext",
    "MemoryRetrievalUsage / Chapter promotion",
    "CharacterPsychologyTrace",
    "CharacterActionIntentionCandidate",
    "ABCDStoryInformationPackage",
    "Writer",
    "Continuity / Apparent / Quality / ObjectiveFact Gate",
    "User confirmation / Scene commit",
    "TieredMemoryWriteback",
]

REPO_ROOT = Path(__file__).resolve().parents[3]


class CompositeAgentContractValidator:
    def __init__(
        self,
        registry_service: CompositeAgentRegistryService | None = None,
        *,
        repo_root: Path | None = None,
    ) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.registry_service = registry_service or CompositeAgentRegistryService(
            repo_root=self.repo_root
        )

    def validate_m0_readiness(self) -> dict[str, Any]:
        issues: list[str] = []
        paths = self.registry_service.source_paths()
        try:
            m0 = self.registry_service.load_m0_intake_report()
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "blocking_findings": [f"missing_or_invalid_m0_intake:{exc}"],
                "paths": paths,
            }
        try:
            gap = self.registry_service.load_m0_contract_gap_report()
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            return {
                "ok": False,
                "blocking_findings": [f"missing_or_invalid_m0_gap:{exc}"],
                "paths": paths,
            }
        checks = {
            "status_ready_for_m1": m0.get("status") == "ready_for_m1",
            "final_marker_pass": m0.get("final_marker")
            == "PHASE85C_M0_COMPOSITE_RUNTIME_BASELINE: PASS",
            "m11_baseline_valid": m0.get("m11_baseline_valid") is True,
            "composite_runtime_currently_implemented_false": (
                m0.get("composite_runtime_currently_implemented") is False
            ),
            "no_source_story_fact_mutation": (
                m0.get("no_source_story_fact_mutation") is True
            ),
            "m0_contract_gap_m1_ready": gap.get("m1_ready") is True,
        }
        for key, ok in checks.items():
            if not ok:
                issues.append(key)
        return {
            "ok": not issues,
            "checks": checks,
            "blocking_findings": issues,
            "paths": paths,
            "status": m0.get("status"),
            "final_marker": m0.get("final_marker"),
        }

    def validate_m11_handoff(self) -> dict[str, Any]:
        issues: list[str] = []
        try:
            handoff = self.registry_service.load_m11_handoff()
        except FileNotFoundError as exc:
            return {
                "ok": False,
                "missing_handoff": True,
                "invalid_handoff": False,
                "blocking_findings": [f"missing_m11_handoff:{exc}"],
            }
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "missing_handoff": False,
                "invalid_handoff": True,
                "blocking_findings": [f"invalid_m11_handoff_json:{exc}"],
            }
        contract = handoff.get("orchestration_contract", {})
        checks = {
            "handoff_status_ready_with_known_residuals": (
                handoff.get("handoff_status") == "ready_with_known_residuals"
            ),
            "contract_only_true": contract.get("contract_only") is True,
            "runtime_not_implemented": (
                contract.get("composite_agent_runtime_implemented") is False
            ),
            "preserves_candidate_gate_commit_writeback_order": (
                contract.get("must_preserve_candidate_gate_commit_writeback_order")
                is True
            ),
            "allowed_responsibilities_present": bool(
                handoff.get("allowed_composite_agent_responsibilities")
            ),
            "forbidden_actions_present": bool(
                handoff.get("forbidden_composite_agent_actions")
            ),
            "required_service_sequence_matches": (
                handoff.get("required_service_sequence") == EXPECTED_M11_SEQUENCE
            ),
        }
        for key, ok in checks.items():
            if not ok:
                issues.append(key)
        return {
            "ok": not issues,
            "missing_handoff": False,
            "invalid_handoff": bool(issues),
            "checks": checks,
            "blocking_findings": issues,
            "handoff_status": handoff.get("handoff_status"),
            "contract": contract,
            "allowed_responsibilities": handoff.get(
                "allowed_composite_agent_responsibilities", []
            ),
            "forbidden_actions": handoff.get(
                "forbidden_composite_agent_actions", []
            ),
            "required_service_sequence": handoff.get("required_service_sequence", []),
        }

    def validate_default_registry(
        self,
        registry: CompositeAgentRegistry,
        *,
        allowed_responsibilities: list[str],
        forbidden_actions: list[str],
    ) -> dict[str, Any]:
        issues: list[str] = []
        agents_by_name = {agent.agent_name: agent for agent in registry.agents}
        missing = [name for name in REQUIRED_AGENT_NAMES if name not in agents_by_name]
        if missing:
            issues.append("missing_default_agents:" + ",".join(missing))
        extra_runtime_enabled = [
            agent.agent_name
            for agent in registry.agents
            if agent.runtime_status == "runtime_enabled"
        ]
        if extra_runtime_enabled:
            issues.append("default_agents_runtime_enabled:" + ",".join(extra_runtime_enabled))
        for agent in registry.agents:
            disallowed_responsibilities = [
                value
                for value in agent.allowed_responsibilities
                if value not in allowed_responsibilities
            ]
            missing_forbidden = [
                value for value in forbidden_actions if value not in agent.forbidden_actions
            ]
            if disallowed_responsibilities:
                issues.append(
                    f"{agent.agent_name}:disallowed_responsibilities:"
                    + ",".join(disallowed_responsibilities)
                )
            if missing_forbidden:
                issues.append(
                    f"{agent.agent_name}:missing_forbidden_actions:"
                    + ",".join(missing_forbidden)
                )
            if agent.default_authority_level not in COMPOSITE_AGENT_M1_DEFAULT_AUTHORITY_LEVELS:
                issues.append(f"{agent.agent_name}:unsafe_default_authority")
            if not agent.candidate_only_default:
                issues.append(f"{agent.agent_name}:candidate_only_default_false")
            if agent.can_write_story_facts_directly:
                issues.append(f"{agent.agent_name}:direct_story_fact_write_true")

        scene_environment = agents_by_name.get("SceneEnvironmentStageAgent")
        if not scene_environment or scene_environment.runtime_status != "future_only":
            issues.append("scene_environment_stage_agent_not_future_only")
        continuity = agents_by_name.get("ContinuityAgent")
        if not continuity or continuity.agent_kind != "gate_adapter":
            issues.append("continuity_agent_not_gate_adapter")
        if not continuity or continuity.runtime_status != "contract_only":
            issues.append("continuity_agent_not_contract_only")

        return {
            "ok": not issues,
            "blocking_findings": issues,
            "required_agent_names": REQUIRED_AGENT_NAMES,
            "agent_count": len(registry.agents),
            "default_agents_runtime_enabled_count": len(extra_runtime_enabled),
            "all_agents_candidate_only_default": all(
                agent.candidate_only_default for agent in registry.agents
            ),
            "all_agents_no_direct_story_fact_write": all(
                not agent.can_write_story_facts_directly for agent in registry.agents
            ),
            "scene_environment_stage_agent_future_only": (
                bool(scene_environment)
                and scene_environment.runtime_status == "future_only"
            ),
            "continuity_agent_gate_adapter_contract_only": (
                bool(continuity)
                and continuity.agent_kind == "gate_adapter"
                and continuity.runtime_status == "contract_only"
            ),
        }

    def validate_service_sequence(
        self,
        registry: CompositeAgentRegistry,
    ) -> dict[str, Any]:
        steps = registry.required_service_sequence.steps
        by_name = {step.step_name: step.order_index for step in steps}
        issues: list[str] = []

        sequence_order_valid = [step.step_name for step in steps] == EXPECTED_M11_SEQUENCE
        if not sequence_order_valid:
            issues.append("service_sequence_does_not_match_m11")

        candidate_names = [
            "SceneParticipantSelection",
            "SceneParticipationPackage",
            "CharacterPsychologyTrace",
            "CharacterActionIntentionCandidate",
            "ABCDStoryInformationPackage",
        ]
        gate_name = "Continuity / Apparent / Quality / ObjectiveFact Gate"
        confirmation_name = "User confirmation / Scene commit"
        writeback_name = "TieredMemoryWriteback"
        writer_name = "Writer"

        candidate_before_gate = all(
            by_name.get(name, 10_000) < by_name.get(gate_name, -1)
            for name in candidate_names
        )
        gate_before_confirmation = by_name.get(gate_name, 10_000) < by_name.get(
            confirmation_name, -1
        )
        writeback_after_scene_commit = by_name.get(writeback_name, -1) > by_name.get(
            confirmation_name, 10_000
        )
        writer_before_gate = by_name.get(writer_name, 10_000) < by_name.get(
            gate_name, -1
        )
        writer_raw_unchecked_output_blocked = writer_before_gate and gate_before_confirmation

        checks = {
            "sequence_order_valid": sequence_order_valid,
            "candidate_before_gate": candidate_before_gate,
            "gate_before_user_confirmation_scene_commit": gate_before_confirmation,
            "writeback_after_scene_commit": writeback_after_scene_commit,
            "writer_raw_unchecked_output_consumption_blocked": (
                writer_raw_unchecked_output_blocked
            ),
            "m1_sequence_not_executed": True,
        }
        for key, ok in checks.items():
            if not ok:
                issues.append(key)
        return {
            "ok": not issues,
            "blocking_findings": issues,
            "checks": checks,
            "steps": [
                {
                    "step_name": step.step_name,
                    "order_index": step.order_index,
                    "current_implementation_paths": step.current_implementation_paths,
                }
                for step in steps
            ],
        }

    def validate_run_envelope(
        self,
        registry: CompositeAgentRegistry,
    ) -> dict[str, Any]:
        issues: list[str] = []
        invalid_rejections: dict[str, bool] = {}
        request = CompositeAgentRunRequest(
            agent_name="SceneAgent",
            project_id="local_project",
            chapter_id="chapter_001",
            scene_id="scene_001",
            scene_index=1,
            target_scope="scene",
            source_context_ids=["scene_participation_package_001"],
            input_refs=["scene_memory_pack_001"],
            requested_output_contract_id=COMPOSITE_AGENT_OUTPUT_CONTRACT_ID,
            requested_authority_level="candidate",
            dry_run=True,
        )
        normalized = self.registry_service.normalize_run_request(request)
        result = self.registry_service.build_contract_only_run_result(normalized)
        trace = self.registry_service.build_contract_only_run_trace(normalized, result)

        serialization_passed = True
        for item in [request, normalized, result, trace, registry]:
            try:
                json.dumps(_model_to_dict(item), ensure_ascii=False, sort_keys=True)
            except TypeError:
                serialization_passed = False
                issues.append(f"serialization_failed:{type(item).__name__}")

        invalid_rejections["direct_write_result"] = self._rejects(
            CompositeAgentRunResult,
            {
                **_model_to_dict(result),
                "can_write_story_facts_directly": True,
            },
        )
        invalid_rejections["non_candidate_result"] = self._rejects(
            CompositeAgentRunResult,
            {
                **_model_to_dict(result),
                "candidate_only": False,
            },
        )
        invalid_rejections["non_empty_story_fact_delta"] = self._rejects(
            CompositeAgentRunResult,
            {
                **_model_to_dict(result),
                "story_fact_delta": {"created": ["event_001"], "modified": [], "removed": []},
            },
        )
        base_agent = _model_to_dict(registry.agents[0])
        invalid_rejections["runtime_enabled_default_agent"] = (
            self._registry_validator_rejects_runtime_enabled_default_agent(registry)
        )
        runtime_enabled_model_allowed = not self._rejects(
            CompositeAgentDefinition,
            {
                **base_agent,
                "agent_name": "RuntimeEnabledFutureAgent",
                "runtime_status": "runtime_enabled",
            },
        )
        invalid_rejections["forbidden_sub_agent_output"] = self._rejects(
            SubAgentTrace,
            {
                "sub_agent_name": "InvalidSubAgent",
                "node_kind": "test",
                "output_type": "committed_fact",
                "authority_level": "candidate",
                "output_summary": "Invalid forbidden output fixture.",
            },
        )

        if not all(invalid_rejections.values()):
            issues.append("invalid_fixtures_not_rejected")
        if not runtime_enabled_model_allowed:
            issues.append("runtime_enabled_model_not_expressive")
        if not normalized.run_id:
            issues.append("normalized_request_missing_run_id")
        if not result.candidate_only:
            issues.append("result_candidate_only_false")
        if result.can_write_story_facts_directly:
            issues.append("result_direct_write_true")
        if not result.story_fact_delta.is_empty():
            issues.append("result_story_fact_delta_not_empty")

        return {
            "ok": not issues,
            "blocking_findings": issues,
            "constructed_request_fixture_count": 2,
            "constructed_result_fixture_count": 1,
            "constructed_trace_fixture_count": len(result.sub_agent_traces),
            "constructed_run_trace_fixture_count": 1,
            "serialization_passed": serialization_passed,
            "normalized_request_has_non_empty_run_id": bool(normalized.run_id),
            "result_candidate_only": result.candidate_only,
            "result_can_write_story_facts_directly": (
                result.can_write_story_facts_directly
            ),
            "result_story_fact_delta_empty": result.story_fact_delta.is_empty(),
            "invalid_fixtures_rejected": invalid_rejections,
            "runtime_enabled_model_allowed_for_future_contract": (
                runtime_enabled_model_allowed
            ),
            "request_fixture": _model_to_dict(normalized),
            "result_fixture": _model_to_dict(result),
            "run_trace_fixture": _model_to_dict(trace),
        }

    def validate_authority_guard(
        self,
        schema_report: dict[str, Any],
        registry: CompositeAgentRegistry,
    ) -> dict[str, Any]:
        default_authority_levels = sorted(
            {agent.default_authority_level for agent in registry.agents}
        )
        rejected = schema_report.get("invalid_fixtures_rejected", {})
        checks = {
            "default_authority_levels_safe": all(
                level in COMPOSITE_AGENT_M1_DEFAULT_AUTHORITY_LEVELS
                for level in default_authority_levels
            ),
            "forbidden_output_type_rejected": rejected.get(
                "forbidden_sub_agent_output"
            )
            is True,
            "direct_write_result_rejected": rejected.get("direct_write_result") is True,
            "non_candidate_result_rejected": rejected.get("non_candidate_result") is True,
            "story_fact_delta_result_rejected": rejected.get(
                "non_empty_story_fact_delta"
            )
            is True,
            "registry_no_direct_story_fact_write": all(
                not agent.can_write_story_facts_directly for agent in registry.agents
            ),
            "registry_candidate_only_defaults": all(
                agent.candidate_only_default for agent in registry.agents
            ),
        }
        issues = [key for key, ok in checks.items() if not ok]
        return {
            "ok": not issues,
            "authority_guard_passed": not issues,
            "blocking_findings": issues,
            "allowed_authority_levels": sorted(COMPOSITE_AGENT_AUTHORITY_LEVELS),
            "default_authority_levels": default_authority_levels,
            "allowed_output_types": sorted(COMPOSITE_AGENT_ALLOWED_OUTPUT_TYPES),
            "forbidden_output_types": sorted(COMPOSITE_AGENT_FORBIDDEN_OUTPUT_TYPES),
            "rejected_forbidden_output_type_fixtures": checks[
                "forbidden_output_type_rejected"
            ],
            "rejected_direct_write_result_fixtures": checks[
                "direct_write_result_rejected"
            ],
            "rejected_non_candidate_result_fixtures": checks[
                "non_candidate_result_rejected"
            ],
            "rejected_story_fact_delta_fixtures": checks[
                "story_fact_delta_result_rejected"
            ],
            "checks": checks,
        }

    def snapshot_source_story_facts(self) -> dict[str, str]:
        result: dict[str, str] = {}
        data_dir = settings.data_dir
        for file_name in SOURCE_STORY_FACT_FILES:
            path = data_dir / file_name
            if path.exists() and path.is_file():
                result[file_name] = _sha256_file(path)
        return result

    def diff_source_story_fact_snapshots(
        self, before: dict[str, str], after: dict[str, str]
    ) -> dict[str, list[str]]:
        before_keys = set(before)
        after_keys = set(after)
        return {
            "created": sorted(after_keys - before_keys),
            "removed": sorted(before_keys - after_keys),
            "modified": sorted(
                key for key in before_keys & after_keys if before[key] != after[key]
            ),
        }

    def validate_no_story_fact_mutation(
        self, before: dict[str, str], after: dict[str, str]
    ) -> dict[str, Any]:
        delta = self.diff_source_story_fact_snapshots(before, after)
        no_delta = not (delta["created"] or delta["removed"] or delta["modified"])
        return {
            "ok": no_delta,
            "no_source_story_fact_mutation": no_delta,
            "source_story_fact_delta": delta,
            "source_story_fact_files_checked": sorted(before.keys() | after.keys()),
        }

    def validate_runtime_non_implementation(self) -> dict[str, Any]:
        issues: list[str] = []
        api_path = self.repo_root / "app/backend/api/composite_agents.py"
        runtime_service_path = (
            self.repo_root / "app/backend/services/composite_agent_runtime_service.py"
        )
        orchestration_service_path = (
            self.repo_root
            / "app/backend/services/composite_runtime_orchestration_service.py"
        )
        if api_path.exists():
            issues.append("composite_agents_api_file_exists")
        if runtime_service_path.exists():
            issues.append("composite_agent_runtime_service_exists")
        orchestration_service_present_after_m7 = orchestration_service_path.exists()

        route_hits = _scan_for_text(
            [
                self.repo_root / "app/backend/api",
                self.repo_root / "app/frontend/src",
            ],
            "/api/composite-agents",
        )
        route_hits = [
            hit
            for hit in route_hits
            if not hit.endswith("verify_phase85c_m1_composite_agent_contract_registry.py")
        ]
        if route_hits:
            issues.append("composite_agents_route_marker_present:" + ",".join(route_hits))

        frontend_hits = _scan_for_any_text(
            [self.repo_root / "app/frontend/src"],
            ["CompositeAgent", "Composite Agent", "composite-agent"],
        )
        if frontend_hits:
            issues.append("frontend_composite_agent_surface_present:" + ",".join(frontend_hits))

        return {
            "ok": not issues,
            "runtime_orchestration_implemented": False
            if not (
                runtime_service_path.exists() or orchestration_service_path.exists()
            )
            else True,
            "m1_contract_runtime_absence_at_m1_evidence": True,
            "current_runtime_service_present_after_m7": orchestration_service_present_after_m7,
            "product_api_added": bool(api_path.exists() or route_hits),
            "frontend_surface_added": bool(frontend_hits),
            "blocking_findings": issues,
            "checked_absent_paths": [
                _rel(api_path, self.repo_root),
                _rel(runtime_service_path, self.repo_root),
                _rel(orchestration_service_path, self.repo_root),
            ],
            "route_marker_hits": route_hits,
            "frontend_surface_hits": frontend_hits,
        }

    def _rejects(self, model_class: type, payload: dict[str, Any]) -> bool:
        try:
            model_class(**payload)
        except (ValidationError, ValueError):
            return True
        return False

    def _registry_validator_rejects_runtime_enabled_default_agent(
        self,
        registry: CompositeAgentRegistry,
    ) -> bool:
        invalid_agent_payload = {
            **_model_to_dict(registry.agents[0]),
            "agent_name": "InvalidRuntimeAgent",
            "runtime_status": "runtime_enabled",
        }
        try:
            invalid_agent = CompositeAgentDefinition(**invalid_agent_payload)
            invalid_registry = registry.copy(
                update={"agents": [invalid_agent, *registry.agents[1:]]}
            )
            validation = self.validate_default_registry(
                invalid_registry,
                allowed_responsibilities=self.registry_service.m11_allowed_responsibilities(),
                forbidden_actions=self.registry_service.m11_forbidden_actions(),
            )
        except (ValidationError, ValueError):
            return True
        return validation.get("ok") is False


def _model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_for_text(roots: list[Path], needle: str) -> list[str]:
    return _scan_for_any_text(roots, [needle])


def _scan_for_any_text(roots: list[Path], needles: list[str]) -> list[str]:
    hits: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            if any(needle in text for needle in needles):
                hits.append(_rel(path, REPO_ROOT))
    return sorted(set(hits))


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
