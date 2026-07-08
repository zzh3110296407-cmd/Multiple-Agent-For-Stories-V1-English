from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.storage.json_store import JsonStore


class CompositeRuntimeReadService:
    """Read-only view service for Phase 8.5-C Composite Runtime evidence."""

    REPORT_FILE = "phase85c_m7_composite_runtime_graph_report.json"
    PROJECT_RUNS_FILE = "composite_runtime_graph_runs.json"

    def __init__(
        self,
        docs_dir: Path | None = None,
        data_dir: Path | None = None,
        store: JsonStore | None = None,
        allow_default_data_dir: bool = True,
        allow_static_fallback: bool = True,
        blocked_reason: str = "",
    ) -> None:
        self.docs_dir = docs_dir or Path(__file__).resolve().parents[2] / "docs"
        self.data_dir = data_dir if data_dir is not None else (
            settings.data_dir if allow_default_data_dir else None
        )
        self.store = store or JsonStore()
        self.allow_static_fallback = allow_static_fallback
        self.blocked_reason = str(blocked_reason or "").strip()

    def latest_run(
        self,
        *,
        chapter_id: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        include_expert: bool = False,
    ) -> dict[str, Any]:
        filters = {
            "chapter_id": chapter_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
        }
        if self.blocked_reason:
            return self._empty_payload(
                self.blocked_reason,
                status="blocked",
                filters=filters,
                include_expert=include_expert,
            )
        project_report = self._load_project_runtime_report()
        project_check = self._select_matching_check(
            project_report,
            chapter_id=chapter_id,
            scene_id=scene_id,
            scene_index=scene_index,
        )
        if project_check:
            return self._payload_from_check(
                project_report,
                project_check,
                requested_filters=filters,
                include_expert=include_expert,
            )
        if chapter_id or scene_id or scene_index is not None:
            return self._empty_payload(
                "No current-project Composite Runtime evidence matches the selected chapter, scene id, and scene index.",
                filters=filters,
                include_expert=include_expert,
            )

        if not self.allow_static_fallback:
            return self._empty_payload(
                "Composite Runtime evidence is not available for the active project.",
                include_expert=include_expert,
            )
        report = self._load_m7_report()
        if not report:
            return self._empty_payload(
                "Composite Runtime evidence is not available yet.",
                include_expert=include_expert,
            )
        check = self._select_check(report)
        return self._payload_from_check(report, check, include_expert=include_expert)

    def get_run(self, graph_run_id: str, *, include_expert: bool = False) -> dict[str, Any]:
        if self.blocked_reason:
            return self._empty_payload(
                self.blocked_reason,
                status="blocked",
                include_expert=include_expert,
            )
        project_report = self._load_project_runtime_report()
        for check in self._iter_run_checks(project_report):
            if check.get("graph_run_id") == graph_run_id:
                return self._payload_from_check(project_report, check, include_expert=include_expert)
        if not self.allow_static_fallback:
            return self._empty_payload(
                f"Composite Runtime run was not found for the active project: {graph_run_id}",
                status="not_found",
                include_expert=include_expert,
            )
        report = self._load_m7_report()
        if not report:
            return self._empty_payload(
                "Composite Runtime evidence is not available yet.",
                include_expert=include_expert,
            )
        for check in self._iter_run_checks(report):
            if check.get("graph_run_id") == graph_run_id:
                return self._payload_from_check(report, check, include_expert=include_expert)
        return self._empty_payload(
            f"Composite Runtime run was not found: {graph_run_id}",
            status="not_found",
            include_expert=include_expert,
        )

    def node_receipts(self, graph_run_id: str) -> dict[str, Any]:
        payload = self.get_run(graph_run_id, include_expert=True)
        expert = self._dict(payload.get("expert_summary"))
        return {
            "graph_run_id": graph_run_id,
            "status": payload.get("status", "empty"),
            "node_receipts": expert.get("node_timeline", []),
            "gate_receipts": expert.get("gate_receipts", []),
            "read_only": True,
        }

    def authority_audit(self, graph_run_id: str) -> dict[str, Any]:
        payload = self.get_run(graph_run_id, include_expert=True)
        expert = self._dict(payload.get("expert_summary"))
        return {
            "graph_run_id": graph_run_id,
            "status": payload.get("status", "empty"),
            "authority_audit": expert.get("authority_audit", {}),
            "no_write_summary": payload.get("no_write_summary", {}),
            "read_only": True,
        }

    def expert_summary(self, graph_run_id: str) -> dict[str, Any]:
        payload = self.get_run(graph_run_id, include_expert=True)
        return {
            "graph_run_id": graph_run_id,
            "status": payload.get("status", "empty"),
            "expert_summary": payload.get("expert_summary", {}),
            "read_only": True,
        }

    def _load_m7_report(self) -> dict[str, Any]:
        path = self.docs_dir / self.REPORT_FILE
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _load_project_runtime_report(self) -> dict[str, Any]:
        if self.data_dir is None:
            return {}
        path = self.data_dir / self.PROJECT_RUNS_FILE
        if not self.store.exists(path):
            return {}
        try:
            value = self.store.read_any(path)
        except Exception:
            return {}
        runs: list[dict[str, Any]] = []
        if isinstance(value, list):
            runs = [item for item in value if isinstance(item, dict)]
        elif isinstance(value, dict):
            raw_runs = value.get("runs")
            if isinstance(raw_runs, list):
                runs = [item for item in raw_runs if isinstance(item, dict)]
        if not runs:
            return {}
        latest = runs[-1]
        return {
            "graph_id": latest.get("graph_id", "scene_generation_candidate_graph_v1"),
            "final_decision": latest.get("final_decision", "unknown"),
            "safe_summary": "Current-project Composite Runtime read-only evidence.",
            "source_kind": "live_project_runtime",
            "checks": {"project_runtime_runs": runs},
        }

    def _iter_run_checks(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        checks = self._dict(report.get("checks"))
        candidates = [
            *self._list(checks.get("project_runtime_runs")),
            checks.get("commit_boundary_preview"),
            checks.get("candidate_preview"),
        ]
        return [self._dict(item) for item in candidates if isinstance(item, dict)]

    def _select_check(self, report: dict[str, Any]) -> dict[str, Any]:
        checks = self._dict(report.get("checks"))
        return self._dict(checks.get("commit_boundary_preview") or checks.get("candidate_preview"))

    def _select_matching_check(
        self,
        report: dict[str, Any],
        *,
        chapter_id: str | None,
        scene_id: str | None,
        scene_index: int | None,
    ) -> dict[str, Any]:
        if not report:
            return {}
        for check in reversed(self._iter_run_checks(report)):
            candidate = self._dict(check.get("candidate_scene_output"))
            if self._matches_filter(
                candidate,
                chapter_id=chapter_id,
                scene_id=scene_id,
                scene_index=scene_index,
            ):
                return check
        return {}

    def _payload_from_check(
        self,
        report: dict[str, Any],
        check: dict[str, Any],
        *,
        requested_filters: dict[str, Any] | None = None,
        include_expert: bool = False,
    ) -> dict[str, Any]:
        candidate = self._dict(check.get("candidate_scene_output"))
        node_receipts = self._list(check.get("node_receipts"))
        authority = self._dict(check.get("authority_audit"))
        writeback_ref = self._dict(check.get("writeback_plan_preview_ref"))
        final_decision = str(check.get("final_decision") or report.get("final_decision") or "unknown")
        status = self._status_from_decision(final_decision)
        gate_summary = self._gate_summary(final_decision, check)
        participant_summary = self._participant_summary(candidate, node_receipts)
        memory_summary = self._memory_summary(node_receipts, writeback_ref)
        no_write_summary = self._no_write_summary(candidate, check, writeback_ref)
        source_artifacts = self._source_artifacts(candidate, node_receipts, writeback_ref)
        graph_run_id = str(check.get("graph_run_id") or "")
        filters = requested_filters or {}
        requested_scene_id = str(filters.get("scene_id") or "").strip()
        current_scene_match = True
        if requested_scene_id:
            current_scene_match = str(candidate.get("scene_id") or "").strip() == requested_scene_id
        runtime_evidence_status = self._runtime_evidence_status(status, current_scene_match)

        ordinary = {
            "graph_run_id": graph_run_id,
            "status": status,
            "safe_summary": check.get("trace", {}).get("safe_summary")
            if isinstance(check.get("trace"), dict)
            else report.get("safe_summary", "Composite Runtime read-only summary."),
            "final_decision": final_decision,
            "chapter_id": candidate.get("chapter_id"),
            "scene_id": candidate.get("scene_id"),
            "scene_index": candidate.get("scene_index"),
            "candidate_scene_output_ref": check.get("candidate_scene_output_ref"),
            "commit_boundary_receipt_ref": check.get("commit_boundary_receipt_ref"),
            "participants": participant_summary,
            "gate_summary": gate_summary,
            "memory_summary": memory_summary,
            "no_write_summary": no_write_summary,
            "state_examples": self._state_examples(),
            "ordinary_payload": {
                "contains_raw_prompt": False,
                "contains_raw_response": False,
                "contains_candidate_prose": False,
                "expert_internals_redacted": True,
            },
            "read_only": True,
            "write_endpoints_available": False,
            "source_kind": check.get("source_kind") or report.get("source_kind") or "static_verification_report",
            "current_scene_match": current_scene_match,
            "runtime_evidence_status": runtime_evidence_status,
            "runtime_evidence_scope": "current_scene"
            if current_scene_match and requested_scene_id
            else "filtered_scene" if current_scene_match else "scope_mismatch",
            "freshness_timestamp": str(
                check.get("completed_at")
                or check.get("created_at")
                or check.get("updated_at")
                or check.get("generated_at")
                or ""
            ),
            "blocking_reasons": [self._safe_id(item) for item in self._list(check.get("blocking_findings"))],
            "degraded_reasons": [self._safe_id(item) for item in self._list(check.get("warnings"))],
            "source_refs": self._source_refs(check, candidate, graph_run_id),
        }
        if include_expert:
            ordinary["expert_summary"] = self._expert_summary(
                report=report,
                check=check,
                node_receipts=node_receipts,
                authority=authority,
                source_artifacts=source_artifacts,
                gate_summary=gate_summary,
                no_write_summary=no_write_summary,
            )
        return ordinary

    def _empty_payload(
        self,
        safe_summary: str,
        *,
        status: str = "empty",
        filters: dict[str, Any] | None = None,
        include_expert: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "graph_run_id": "",
            "status": status,
            "safe_summary": safe_summary,
            "final_decision": status,
            "filters": filters or {},
            "source_kind": "live_project_runtime" if filters else "none",
            "current_scene_match": False,
            "runtime_evidence_status": self._runtime_evidence_status(status, False),
            "runtime_evidence_scope": "missing",
            "freshness_timestamp": "",
            "blocking_reasons": [status] if status in {"blocked", "failed"} else [],
            "degraded_reasons": [status] if status in {"unavailable", "degraded"} else [],
            "source_refs": [],
            "participants": [],
            "gate_summary": {
                "status": status,
                "final_decision": status,
                "blocking_count": 0,
                "warning_count": 0,
                "requires_user_confirmation": False,
                "safe_summary": safe_summary,
            },
            "memory_summary": {
                "scene_memory_pack_id": "",
                "tiered_context_package_id": "",
                "retrieved_previous_scene_memory": False,
                "safe_summary": "No Composite Runtime memory evidence is available.",
            },
            "no_write_summary": {
                "candidate_only": True,
                "can_write_story_facts_directly": False,
                "story_fact_delta_empty": True,
                "active_memory_write_executed": False,
            },
            "state_examples": self._state_examples(),
            "ordinary_payload": {
                "contains_raw_prompt": False,
                "contains_raw_response": False,
                "contains_candidate_prose": False,
                "expert_internals_redacted": True,
            },
            "read_only": True,
            "write_endpoints_available": False,
        }
        if include_expert:
            payload["expert_summary"] = {
                "graph_overview": {"status": status, "node_count": 0},
                "node_timeline": [],
                "gate_receipts": [],
                "authority_audit": {"status": status, "read_only": True},
                "source_artifacts": {},
                "redaction": self._redaction_summary(),
            }
        return payload

    def _matches_filter(
        self,
        candidate: dict[str, Any],
        *,
        chapter_id: str | None,
        scene_id: str | None,
        scene_index: int | None,
    ) -> bool:
        if not chapter_id and not scene_id and scene_index is None:
            return True
        if chapter_id and str(candidate.get("chapter_id") or "") != str(chapter_id):
            return False
        if scene_id and str(candidate.get("scene_id") or "") != str(scene_id):
            return False
        if scene_index is not None:
            try:
                candidate_scene_index = int(candidate.get("scene_index"))
            except (TypeError, ValueError):
                return False
            if candidate_scene_index != int(scene_index):
                return False
        return True

    def _runtime_evidence_status(self, status: str, current_scene_match: bool) -> str:
        if not current_scene_match:
            return "stale"
        if status in {"pass", "warning", "needs_user_confirmation"}:
            return "ready"
        if status in {"empty", "not_found"}:
            return "missing"
        if status in {"blocked", "failed"}:
            return "blocked"
        if status in {"unavailable", "degraded"}:
            return status
        return "pending"

    def _source_refs(
        self,
        check: dict[str, Any],
        candidate: dict[str, Any],
        graph_run_id: str,
    ) -> list[str]:
        refs: list[str] = []
        if graph_run_id:
            refs.append(f"composite_runtime_graph_run:{graph_run_id}")
        for key in (
            "candidate_scene_output_ref",
            "commit_boundary_receipt_ref",
            "writeback_plan_preview_ref",
        ):
            value = check.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
            elif isinstance(value, dict):
                ref = value.get("ref") or value.get("id") or value.get("artifact_id")
                if isinstance(ref, str) and ref.strip():
                    refs.append(ref.strip())
        scene_id = str(candidate.get("scene_id") or "").strip()
        if scene_id:
            refs.append(f"scene:{scene_id}")
        return refs

    def _status_from_decision(self, final_decision: str) -> str:
        if final_decision == "pass":
            return "pass"
        if final_decision in {"pass_with_warnings", "warning"}:
            return "warning"
        if final_decision in {"needs_user_confirmation", "requires_user_confirmation"}:
            return "needs_user_confirmation"
        if final_decision in {"blocked", "failed"}:
            return final_decision
        return "unknown"

    def _gate_summary(self, final_decision: str, check: dict[str, Any]) -> dict[str, Any]:
        blocking = self._list(check.get("blocking_findings"))
        warnings = self._list(check.get("warnings"))
        requires = final_decision in {"needs_user_confirmation", "requires_user_confirmation"}
        return {
            "status": self._status_from_decision(final_decision),
            "final_decision": final_decision,
            "blocking_count": len(blocking),
            "warning_count": len(warnings),
            "requires_user_confirmation": requires,
            "blocking_refs": [self._safe_id(item) for item in blocking],
            "warning_refs": [self._safe_id(item) for item in warnings],
            "safe_summary": "Composite Runtime gate passed."
            if final_decision == "pass"
            else f"Composite Runtime gate status: {final_decision}.",
        }

    def _participant_summary(
        self,
        candidate: dict[str, Any],
        node_receipts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = {}
        scene_refs = [
            ref
            for ref in self._all_refs(node_receipts)
            if ref.startswith("scene_participation") or ref.startswith("scene_selection")
        ]
        for node in node_receipts:
            node_refs = self._node_refs(node)
            for marker in self._list(node.get("warnings")) + self._list(node.get("blocking_findings")):
                match = re.search(r"active_character_missing:(char_[A-Za-z0-9_]+)", str(marker))
                if not match:
                    continue
                self._merge_participant_evidence(
                    evidence,
                    match.group(1).lower(),
                    origin="scene_participation_package",
                    selection_reason="Selected by structured SceneAgent / SceneParticipationPackage evidence.",
                    source_refs=scene_refs + node_refs,
                )
            for ref in node_refs:
                role_match = re.search(r"(char_[A-Za-z0-9_]+)$", ref)
                if not role_match or not ref.startswith("role_entry_"):
                    continue
                self._merge_participant_evidence(
                    evidence,
                    role_match.group(1).lower(),
                    origin="role_memory_writeback_evidence",
                    selection_reason="Observed in structured MemoryCurator role-memory writeback preview evidence.",
                    source_refs=[ref] + scene_refs,
                )
        tier_by_id = {"char_a": "A", "char_b": "B", "char_c": "C", "char_d": "D"}
        tier_order = {"A": 0, "B": 1, "C": 2, "D": 3, "unknown": 9}
        return [
            {
                "character_id": character_id,
                "tier": tier_by_id.get(character_id, "unknown"),
                "origin": data.get("origin", "structured_runtime_evidence"),
                "selection_reason": data.get(
                    "selection_reason",
                    "Selected by structured Composite Runtime evidence.",
                ),
                "source_refs": sorted(data.get("source_refs", [])),
            }
            for character_id, data in sorted(
                evidence.items(),
                key=lambda item: (tier_order.get(tier_by_id.get(item[0], "unknown"), 9), item[0]),
            )
        ]

    def _merge_participant_evidence(
        self,
        evidence: dict[str, dict[str, Any]],
        character_id: str,
        *,
        origin: str,
        selection_reason: str,
        source_refs: list[str],
    ) -> None:
        current = evidence.setdefault(
            character_id,
            {"origin": origin, "selection_reason": selection_reason, "source_refs": set()},
        )
        if current.get("origin") == "role_memory_writeback_evidence" and origin == "scene_participation_package":
            current["origin"] = origin
            current["selection_reason"] = selection_reason
        current_refs = current.setdefault("source_refs", set())
        if isinstance(current_refs, set):
            current_refs.update(ref for ref in source_refs if ref)

    def _memory_summary(
        self,
        node_receipts: list[dict[str, Any]],
        writeback_ref: dict[str, Any],
    ) -> dict[str, Any]:
        refs = self._all_output_refs(node_receipts)
        scene_pack_id = self._first_ref(refs, "scene_pack_")
        context_id = self._first_ref(refs, "tiered_context_")
        usage_ref = self._first_ref(refs, "usage_")
        return {
            "scene_memory_pack_id": scene_pack_id,
            "tiered_context_package_id": context_id,
            "retrieved_previous_scene_memory": bool(usage_ref),
            "usage_ref": usage_ref,
            "writeback_plan_ref_id": writeback_ref.get("writeback_plan_ref_id", ""),
            "active_memory_write_executed": bool(writeback_ref.get("active_memory_write_executed")),
            "safe_summary": "Composite Runtime used scene memory context and kept writeback as preview-only evidence.",
        }

    def _no_write_summary(
        self,
        candidate: dict[str, Any],
        check: dict[str, Any],
        writeback_ref: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "candidate_only": candidate.get("candidate_only") is not False,
            "can_write_story_facts_directly": bool(candidate.get("can_write_story_facts_directly")),
            "story_fact_delta_empty": bool(check.get("story_fact_delta_empty", True)),
            "writeback_plan_only": writeback_ref.get("writeback_plan_only") is not False,
            "dry_run": writeback_ref.get("dry_run") is not False,
            "active_memory_write_executed": bool(writeback_ref.get("active_memory_write_executed")),
        }

    def _source_artifacts(
        self,
        candidate: dict[str, Any],
        node_receipts: list[dict[str, Any]],
        writeback_ref: dict[str, Any],
    ) -> dict[str, Any]:
        refs = self._all_output_refs(node_receipts)
        return {
            "candidate_scene_output_id": candidate.get("candidate_scene_output_id", ""),
            "writer_candidate_draft_id": candidate.get("writer_candidate_draft_id", ""),
            "scene_participation_package_id": self._first_ref(refs, "scene_participation"),
            "scene_participant_selection_id": self._first_ref(refs, "scene_selection"),
            "scene_memory_pack_id": self._first_ref(refs, "scene_pack_"),
            "chapter_memory_pack_id": self._first_ref(refs, "chapter_pack_"),
            "tiered_context_package_id": self._first_ref(refs, "tiered_context_"),
            "tiered_intent_package_id": self._first_ref(refs, "tiered_character_intent_"),
            "abcd_story_information_package_id": self._first_ref(refs, "abcd_story_information_"),
            "writeback_plan_ref_id": writeback_ref.get("writeback_plan_ref_id", ""),
        }

    def _expert_summary(
        self,
        *,
        report: dict[str, Any],
        check: dict[str, Any],
        node_receipts: list[dict[str, Any]],
        authority: dict[str, Any],
        source_artifacts: dict[str, Any],
        gate_summary: dict[str, Any],
        no_write_summary: dict[str, Any],
    ) -> dict[str, Any]:
        node_timeline = [
            {
                "node_receipt_id": node.get("node_receipt_id", ""),
                "node_id": node.get("node_id", ""),
                "order_index": node.get("order_index"),
                "status": node.get("status", ""),
                "agent_name": node.get("agent_name", ""),
                "wrapper_run_id": node.get("wrapper_run_id", ""),
                "input_ref_count": len(self._list(node.get("input_refs"))),
                "output_ref_count": len(self._list(node.get("output_refs"))),
                "gate_receipt_ids": self._list(node.get("gate_receipt_ids")),
                "blocking_count": len(self._list(node.get("blocking_findings"))),
                "warning_count": len(self._list(node.get("warnings"))),
                "candidate_only": node.get("candidate_only") is not False,
                "can_write_story_facts_directly": bool(node.get("can_write_story_facts_directly")),
                "safe_summary": node.get("safe_summary", ""),
            }
            for node in node_receipts
        ]
        gate_receipts = [
            {
                "gate_receipt_id": receipt_id,
                "status": gate_summary.get("status"),
                "final_decision": gate_summary.get("final_decision"),
            }
            for receipt_id in self._list(check.get("gate_receipt_ids"))
        ]
        return {
            "graph_overview": {
                "graph_id": report.get("graph_id", "phase85c_composite_runtime_graph"),
                "graph_run_id": check.get("graph_run_id", ""),
                "mode": check.get("mode", ""),
                "status": check.get("status", ""),
                "final_decision": check.get("final_decision", report.get("final_decision", "")),
                "node_count": len(node_timeline),
                "node_order": self._list(check.get("node_order")),
            },
            "node_timeline": node_timeline,
            "sub_agent_trace_summary": {
                "agent_run_ids": self._list(check.get("agent_run_ids")),
                "agent_count": len([node for node in node_timeline if node.get("agent_name")]),
            },
            "integrator_summary": {
                "integrator_refs": [
                    ref for ref in self._all_output_refs(node_receipts) if "integrator" in ref
                ],
                "pipeline_bundle_refs": [
                    ref for ref in self._all_output_refs(node_receipts) if "pipeline_bundle" in ref
                ],
            },
            "gate_receipts": gate_receipts,
            "authority_audit": self._safe_authority_audit(authority, no_write_summary),
            "source_artifacts": source_artifacts,
            "redaction": self._redaction_summary(),
        }

    def _safe_authority_audit(
        self,
        authority: dict[str, Any],
        no_write_summary: dict[str, Any],
    ) -> dict[str, Any]:
        safe = deepcopy(authority)
        safe.pop("raw_payload", None)
        safe.pop("raw_model_response", None)
        safe["read_only"] = True
        safe["no_write_summary"] = no_write_summary
        return safe

    def _state_examples(self) -> list[dict[str, Any]]:
        return [
            {
                "status": "empty",
                "safe_summary": "No Composite Runtime evidence is available for this scene.",
            },
            {
                "status": "blocked",
                "safe_summary": "Composite Runtime gate blocked candidate downstream use.",
            },
            {
                "status": "needs_user_confirmation",
                "safe_summary": "Composite Runtime requires explicit user confirmation before commit boundary.",
            },
        ]

    def _redaction_summary(self) -> dict[str, bool]:
        return {
            "raw_prompt_exposed": False,
            "raw_response_exposed": False,
            "candidate_prose_exposed": False,
            "ordinary_payload_contains_expert_internals": False,
        }

    def _all_output_refs(self, node_receipts: list[dict[str, Any]]) -> list[str]:
        refs: list[str] = []
        for node in node_receipts:
            refs.extend(str(item) for item in self._list(node.get("output_refs")) if item)
        return refs

    def _all_refs(self, node_receipts: list[dict[str, Any]]) -> list[str]:
        refs: list[str] = []
        for node in node_receipts:
            refs.extend(self._node_refs(node))
        return refs

    def _node_refs(self, node: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        refs.extend(str(item) for item in self._list(node.get("input_refs")) if item)
        refs.extend(str(item) for item in self._list(node.get("output_refs")) if item)
        return refs

    def _has_ref(self, node_receipts: list[dict[str, Any]], prefix: str) -> bool:
        return any(prefix in ref for ref in self._all_output_refs(node_receipts))

    def _first_ref(self, refs: list[str], prefix: str) -> str:
        return next((ref for ref in refs if ref.startswith(prefix) or prefix in ref), "")

    def _safe_id(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("id") or value.get("finding_code") or value.get("issue_id") or "finding")
        return str(value)

    def _dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []
