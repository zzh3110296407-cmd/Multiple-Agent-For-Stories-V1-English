from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.continuity import (
    ContinuityIssue,
    ContinuityResolutionRefreshResult,
    DEFAULT_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS,
    PriorStoryCompletionCandidateDecision,
    PriorStoryCompletionCandidateResponse,
    PriorStoryCompletionCandidate,
    PriorStoryCompletionCandidateWritePlan,
    PriorStoryCompletionLineage,
    REQUIRED_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS,
)
from app.backend.models.event import Event
from app.backend.models.memory_record import MemoryRecord
from app.backend.repositories.factory import RepositoryBundle, create_repositories
from app.backend.services.continuity_gate_service import (
    ContinuityGateService,
    model_to_dict,
    now_iso,
)
from app.backend.services.active_project_story_data import (
    current_story_workspace_project_id,
)
from app.backend.services.continuity_resolution_refresh_service import (
    ContinuityResolutionRefreshService,
)
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
NON_OBJECTIVE_TRUTH_STATUSES = {"rumor", "lie", "misinformation", "unverified_claim"}
CONFIRMABLE_PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES = {"pending"}
REJECTABLE_PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES = {"pending", "blocked"}
REVISABLE_PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES = {"pending", "blocked"}


class PriorStoryCompletionScopeGuard:
    def validate_confirm(
        self,
        *,
        candidate: PriorStoryCompletionCandidate,
        source_issue: ContinuityIssue,
        active_project_id: str,
        repositories: RepositoryBundle,
    ) -> None:
        self._validate_common(
            candidate=candidate,
            source_issue=source_issue,
            active_project_id=active_project_id,
        )
        if candidate.status not in CONFIRMABLE_PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_STATUS_INVALID: Candidate is not pending and cannot be confirmed."
            )
        if source_issue.status != "open":
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SOURCE_ISSUE_NOT_ACTIONABLE: Source issue must be open before confirmation."
            )
        if not candidate.requires_user_confirmation:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_CONFIRMATION_REQUIRED: Candidate confirmation must require user confirmation."
            )
        self._validate_write_scope(candidate, repositories)

    def validate_reject(
        self,
        *,
        candidate: PriorStoryCompletionCandidate,
        source_issue: ContinuityIssue,
        active_project_id: str,
    ) -> None:
        self._validate_common(
            candidate=candidate,
            source_issue=source_issue,
            active_project_id=active_project_id,
        )
        if candidate.status not in REJECTABLE_PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_STATUS_INVALID: Candidate cannot be rejected in its current status."
            )

    def validate_revise(
        self,
        *,
        candidate: PriorStoryCompletionCandidate,
        source_issue: ContinuityIssue,
        active_project_id: str,
    ) -> None:
        self._validate_common(
            candidate=candidate,
            source_issue=source_issue,
            active_project_id=active_project_id,
        )
        if candidate.status not in REVISABLE_PRIOR_STORY_COMPLETION_CANDIDATE_STATUSES:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_STATUS_INVALID: Candidate cannot be revised in its current status."
            )
        if source_issue.status != "open":
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SOURCE_ISSUE_NOT_ACTIONABLE: Source issue must be open before revision."
            )

    def _validate_common(
        self,
        *,
        candidate: PriorStoryCompletionCandidate,
        source_issue: ContinuityIssue,
        active_project_id: str,
    ) -> None:
        if not candidate.candidate_id:
            raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate id is required.")
        if not candidate.source_issue_id:
            raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Source issue id is required.")
        if candidate.source_issue_id != source_issue.issue_id:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate source issue does not match loaded issue."
            )
        if candidate.project_id != active_project_id:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate project scope does not match the active story workspace."
            )
        if not REQUIRED_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS.issubset(
            set(candidate.forbidden_write_targets)
        ):
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate forbidden write targets are incomplete."
            )

    def _validate_write_scope(
        self,
        candidate: PriorStoryCompletionCandidate,
        repositories: RepositoryBundle,
    ) -> None:
        allowed = set(candidate.allowed_write_targets)
        forbidden = set(candidate.forbidden_write_targets)
        actual_targets: set[str] = set()
        if candidate.proposed_event:
            actual_targets.add("event")
        if candidate.proposed_memory_record:
            actual_targets.add("memory_record")
        if candidate.existing_event_ids:
            actual_targets.add("event")
        if candidate.existing_memory_ids:
            actual_targets.add("memory_record")
        if not actual_targets:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate has no declared write or link scope."
            )
        if actual_targets - allowed:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate writes outside allowed targets."
            )
        if actual_targets & forbidden:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate writes to a forbidden target."
            )
        if candidate.proposed_event:
            event_id = str(candidate.proposed_event.get("event_id") or "")
            if not event_id:
                raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Proposed event id is required.")
            if repositories.events.get_by_id(event_id):
                raise StorageError(
                    "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Proposed event id already exists."
                )
        if candidate.proposed_memory_record:
            memory_id = str(candidate.proposed_memory_record.get("memory_id") or "")
            if not memory_id:
                raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Proposed memory id is required.")
            if repositories.memory.get_by_id(memory_id):
                raise StorageError(
                    "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Proposed memory id already exists."
                )
        for event_id in candidate.existing_event_ids:
            if not repositories.events.get_by_id(event_id):
                raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Linked event does not exist.")
        for memory_id in candidate.existing_memory_ids:
            if not repositories.memory.get_by_id(memory_id):
                raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Linked memory does not exist.")


class IssueResolutionService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        repositories: RepositoryBundle | None = None,
        continuity_gate_service: ContinuityGateService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.repositories = repositories or create_repositories(
            store=self.store,
            data_dir=self.data_dir,
        )
        self.continuity_gate_service = continuity_gate_service or ContinuityGateService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.refresh_service = ContinuityResolutionRefreshService(
            store=self.store,
            data_dir=self.data_dir,
            repositories=self.repositories,
        )
        self.scope_guard = PriorStoryCompletionScopeGuard()

    def _ensure_issue_open_for_resolution(self, issue: ContinuityIssue) -> None:
        if issue.status != "open":
            raise StorageError(
                "CONTINUITY_RESOLUTION_ISSUE_NOT_OPEN: Resolution actions can only execute for open issues."
            )

    def resolve_issue(
        self,
        issue_id: str,
        *,
        action_type: str,
        user_input: str = "",
        revision_prompt: str = "",
        truth_status: str = "",
    ) -> dict[str, Any]:
        issue = self._issue(issue_id)
        self._ensure_issue_open_for_resolution(issue)
        if action_type == "complete_prior_story":
            candidate = self.create_prior_story_completion_candidate(
                issue_id,
                user_input=user_input,
            )
            refresh = self.refresh_after_issue_action(
                action_type="complete_prior_story",
                action_status="created_candidate",
                issue_id=issue_id,
                affected_issue_ids=[issue_id],
            )
            candidate_response = self.prior_story_completion_candidate_response(
                candidate,
                decision=self._decision_by_id(candidate.decision_id),
                action_type="complete_prior_story",
                action_status="created_candidate",
            )
            return {
                "success": True,
                "issue": model_to_dict(self._issue(issue_id)),
                "candidate": model_to_dict(candidate),
                "decision": candidate_response.decision,
                "candidate_decision": (
                    model_to_dict(candidate_response.candidate_decision)
                    if candidate_response.candidate_decision
                    else None
                ),
                "write_plan": (
                    model_to_dict(candidate_response.write_plan)
                    if candidate_response.write_plan
                    else None
                ),
                "lineage": (
                    model_to_dict(candidate_response.lineage)
                    if candidate_response.lineage
                    else None
                ),
                "refresh": model_to_dict(refresh),
            }
        if action_type == "revise_current_scene":
            response = self.start_scene_revision(
                issue_id,
                revision_prompt=revision_prompt or user_input,
            )
            return response
        if action_type == "mark_as_misinformation_or_lie":
            issue, memory, decision = self.mark_as_misinformation_or_lie(
                issue_id,
                user_input=user_input,
                truth_status=truth_status or "misinformation",
            )
            return {
                "success": True,
                "issue": model_to_dict(issue),
                "memory_record": model_to_dict(memory),
                "decision": decision,
                "refresh": model_to_dict(
                    self.refresh_after_issue_action(
                        action_type="mark_as_misinformation_or_lie",
                        action_status="resolved_issue",
                        issue_id=issue.issue_id,
                        affected_issue_ids=[issue.issue_id],
                        recompute_quality_report=True,
                    )
                ),
            }
        raise StorageError("CONTINUITY_RESOLUTION_ACTION_INVALID: 不支持的连续性处理方式。")

    def create_prior_story_completion_candidate(
        self,
        issue_id: str,
        *,
        user_input: str = "",
    ) -> PriorStoryCompletionCandidate:
        issue = self._issue(issue_id)
        self._ensure_issue_open_for_resolution(issue)
        existing = self._candidate_for_issue(issue_id)
        if existing and existing.status == "pending":
            return self._ensure_candidate_project_scope(existing, issue)
        timestamp = now_iso()
        summary = (user_input or issue.user_visible_message or issue.technical_summary).strip()
        if not summary:
            summary = "补全当前连续性问题所需的前情事实。"
        candidate_id = f"prior_story_completion_candidate_{len(self.repositories.prior_story_completion_candidates.list_all()) + 1:03d}"
        event_id = f"event_{candidate_id}"
        memory_id = f"memory_{candidate_id}"
        project_id = self._current_project_id(issue)
        existing_event_ids, existing_memory_ids = self._find_existing_canon_sources(
            issue,
            summary,
        )
        has_existing_sources = bool(existing_event_ids or existing_memory_ids)
        write_mode = "link_existing_sources" if has_existing_sources else "create_new_event_memory"
        candidate_version_number = self._next_candidate_version_number(issue.issue_id)
        candidate = PriorStoryCompletionCandidate(
            candidate_id=candidate_id,
            issue_id=issue.issue_id,
            project_id=project_id,
            chapter_id=issue.chapter_id,
            scene_id=issue.scene_id,
            status="pending",
            candidate_status_reason="waiting_for_user_confirmation",
            proposed_event={} if has_existing_sources else {
                "event_id": event_id,
                "scene_id": issue.scene_id,
                "summary": summary,
                "participants": issue.source_character_ids,
                "location_id": "",
                "cause": "用户选择补全前情以处理连续性问题。",
                "result": summary,
                "tags": ["continuity_resolution", issue.category],
                "status": "confirmed",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
            proposed_memory_record={} if has_existing_sources else {
                "memory_id": memory_id,
                "project_id": project_id,
                "source_object_type": "continuity_issue",
                "source_object_id": issue.issue_id,
                "chapter_id": issue.chapter_id,
                "scene_id": issue.scene_id,
                "memory_type": "event",
                "summary": summary,
                "keywords": ["continuity_resolution", issue.category],
                "character_ids": issue.source_character_ids,
                "relationship_ids": issue.source_relationship_ids,
                "location": None,
                "event_ids": [event_id],
                "importance": "medium",
                "status": "active",
                "truth_status": "objective_fact",
                "objective_truth": True,
                "source_issue_id": issue.issue_id,
                "version_id": "phase2_m2_memory_source_index_v1",
                "created_at": timestamp,
                "updated_at": timestamp,
                "source_type": "continuity_issue",
                "object_type": "continuity_issue",
                "object_id": issue.issue_id,
                "tags": ["continuity_resolution", issue.category],
                "embedding_ref": "",
            },
            existing_event_ids=existing_event_ids,
            existing_memory_ids=existing_memory_ids,
            user_visible_summary=summary,
            source_issue_id=issue.issue_id,
            completion_scope_summary=self._completion_scope_summary(
                write_mode=write_mode,
                proposed_event={} if has_existing_sources else {"event_id": event_id},
                proposed_memory_record={} if has_existing_sources else {"memory_id": memory_id},
                existing_event_ids=existing_event_ids,
                existing_memory_ids=existing_memory_ids,
            ),
            resolves_issue_explanation=(
                f"Candidate resolves continuity issue {issue.issue_id} only after user confirmation."
            ),
            write_mode=write_mode,
            allowed_write_targets=["event", "memory_record"],
            forbidden_write_targets=list(DEFAULT_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS),
            requires_user_confirmation=True,
            candidate_version_number=candidate_version_number,
            created_at=timestamp,
            updated_at=timestamp,
        )
        candidate = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(candidate),
                "write_scope_hash": self._write_scope_hash(model_to_dict(candidate)),
            }
        )
        decision = self._write_decision(
            "create_prior_story_completion_candidate",
            "prior_story_completion_candidate",
            candidate.candidate_id,
            user_input or "创建前情补全候选，等待用户确认。",
        )
        candidate = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(candidate),
                "decision_id": decision["decision_id"],
            }
        )
        self.repositories.prior_story_completion_candidates.append(model_to_dict(candidate))
        self._record_legacy_candidate_creation_noop(
            "create_prior_story_completion_candidate",
            "continuity_issue",
            issue.issue_id,
            user_input or "创建前情补全候选，等待用户确认。",
        )
        return candidate

    def confirm_prior_story_completion_candidate(
        self,
        candidate_id: str,
        user_input: str = "",
    ) -> tuple[PriorStoryCompletionCandidate, dict[str, Any]]:
        candidate = self._candidate(candidate_id)
        issue = self._issue(candidate.source_issue_id or candidate.issue_id)
        candidate = self._ensure_candidate_project_scope(candidate, issue)
        if candidate.status == "confirmed":
            return candidate, self._decision_by_id(candidate.decision_id)
        if candidate.status in {"superseded", "blocked"}:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_STATUS_INVALID: Candidate cannot be confirmed in its current status."
            )
        if candidate.status == "rejected":
            raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_REJECTED: 前情补全候选已拒绝。")
        if candidate.status == "confirmed":
            decision = self._write_decision(
                "confirm_prior_story_completion_candidate",
                "prior_story_completion_candidate",
                candidate.candidate_id,
                user_input or "前情补全候选已经确认。",
            )
            return candidate, decision
        timestamp = now_iso()
        project_id = self._current_project_id(issue)
        self.scope_guard.validate_confirm(
            candidate=candidate,
            source_issue=issue,
            active_project_id=project_id,
            repositories=self.repositories,
        )
        if candidate.existing_event_ids or candidate.existing_memory_ids:
            self._attach_existing_sources_to_issue(candidate)
        if candidate.proposed_event:
            event = Event(**{**candidate.proposed_event, "status": "confirmed", "updated_at": timestamp})
            self.repositories.events.upsert(model_to_dict(event), "event_id")
        if candidate.proposed_memory_record:
            memory = MemoryRecord(
                **{
                    **candidate.proposed_memory_record,
                    "project_id": project_id,
                    "status": "active",
                    "truth_status": "objective_fact",
                    "objective_truth": True,
                    "updated_at": timestamp,
                }
            )
            self.repositories.memory.upsert(model_to_dict(memory), "memory_id")
        decision = self._write_decision(
            "confirm_prior_story_completion_candidate",
            "prior_story_completion_candidate",
            candidate.candidate_id,
            user_input or "确认前情补全候选，并写入正式事件和记忆。",
        )
        confirmed = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(candidate),
                "project_id": project_id,
                "status": "confirmed",
                "candidate_status_reason": "confirmed_by_user",
                "decision_id": decision["decision_id"],
                "updated_at": timestamp,
            }
        )
        self.repositories.prior_story_completion_candidates.upsert(
            model_to_dict(confirmed),
            "candidate_id",
        )
        self.continuity_gate_service.mark_issue_resolved(
            candidate.source_issue_id or candidate.issue_id,
            user_input or "前情补全候选已确认。",
        )
        return confirmed, decision

    def reject_prior_story_completion_candidate(
        self,
        candidate_id: str,
        user_input: str = "",
    ) -> tuple[PriorStoryCompletionCandidate, dict[str, Any]]:
        candidate = self._candidate(candidate_id)
        issue = self._issue(candidate.source_issue_id or candidate.issue_id)
        candidate = self._ensure_candidate_project_scope(candidate, issue)
        self.scope_guard.validate_reject(
            candidate=candidate,
            source_issue=issue,
            active_project_id=self._current_project_id(issue),
        )
        if candidate.status == "confirmed":
            raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_CONFIRMED: 已确认的前情补全候选不能拒绝。")
        decision = self._write_decision(
            "reject_prior_story_completion_candidate",
            "prior_story_completion_candidate",
            candidate.candidate_id,
            user_input or "拒绝前情补全候选。",
        )
        rejected = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(candidate),
                "project_id": self._current_project_id(issue),
                "status": "rejected",
                "candidate_status_reason": "rejected_by_user",
                "decision_id": decision["decision_id"],
                "updated_at": now_iso(),
            }
        )
        self.repositories.prior_story_completion_candidates.upsert(
            model_to_dict(rejected),
            "candidate_id",
        )
        return rejected, decision

    def start_scene_revision(
        self,
        issue_id: str,
        *,
        revision_prompt: str,
    ) -> dict[str, Any]:
        issue = self._issue(issue_id)
        self._ensure_issue_open_for_resolution(issue)
        prompt = (revision_prompt or "").strip()
        if not prompt:
            raise StorageError("CONTINUITY_REVISION_PROMPT_REQUIRED: 修改当前幕需要填写修订提示。")
        from app.backend.services.scene_revision_service import SceneRevisionService

        revision_service = SceneRevisionService(data_dir=self.data_dir)
        existing = self._active_revision_candidate_for_issue(issue)
        if existing is not None:
            scene_data, candidate_data = existing
            resolved = self._link_issue_to_revision_candidate(
                issue,
                candidate_data,
                lifecycle_status="pending_revision_candidate",
                lifecycle_message="Existing linked scene revision candidate is awaiting user confirmation.",
            )
            refresh = self.refresh_after_issue_action(
                action_type="revise_current_scene",
                action_status="revision_candidate_reused",
                issue_id=resolved.issue_id,
                affected_issue_ids=[resolved.issue_id],
                recompute_quality_report=True,
            )
            return {
                "success": True,
                "issue": model_to_dict(resolved),
                "scene_revision_response": {
                    "success": True,
                    "scene": scene_data,
                    "candidate": candidate_data,
                    "current_candidate": candidate_data,
                    "revision_intent": candidate_data.get("revision_intent") or "",
                    "quality_report": candidate_data.get("quality_report") or {},
                },
                "refresh": model_to_dict(refresh),
            }
        response = revision_service.revise_scene(
            issue.scene_id,
            prompt,
            source_continuity_issue_id=issue.issue_id,
        )
        response_data = (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else response.dict()
        )
        revision_candidate = (
            response_data.get("candidate")
            or response_data.get("current_candidate")
            or {}
        )
        resolved = self._link_issue_to_revision_candidate(
            issue,
            revision_candidate,
            lifecycle_status="pending_revision_candidate",
            lifecycle_message="Scene revision candidate created; source issue remains open until candidate confirmation.",
        )
        refresh = self.refresh_after_issue_action(
            action_type="revise_current_scene",
            action_status="revision_candidate_created",
            issue_id=resolved.issue_id,
            affected_issue_ids=[resolved.issue_id],
            recompute_quality_report=True,
        )
        return {
            "success": True,
            "issue": model_to_dict(resolved),
            "scene_revision_response": response_data,
            "refresh": model_to_dict(refresh),
        }

    def mark_as_misinformation_or_lie(
        self,
        issue_id: str,
        *,
        user_input: str,
        truth_status: str = "misinformation",
    ) -> tuple[ContinuityIssue, MemoryRecord, dict[str, Any]]:
        issue = self._issue(issue_id)
        self._ensure_issue_open_for_resolution(issue)
        clean_status = truth_status if truth_status in NON_OBJECTIVE_TRUTH_STATUSES else "misinformation"
        summary = (user_input or issue.evidence_text or issue.user_visible_message).strip()
        if not summary:
            summary = "当前说法被记录为非客观事实。"
        timestamp = now_iso()
        memory_id = issue.source_memory_ids[0] if issue.source_memory_ids else f"memory_non_objective_{issue.issue_id}"
        raw_memory = self.repositories.memory.get_by_id(memory_id) or {}
        memory = MemoryRecord(
            **{
                **raw_memory,
                "memory_id": memory_id,
                "project_id": self._current_project_id(issue),
                "source_object_type": raw_memory.get("source_object_type") or "continuity_issue",
                "source_object_id": raw_memory.get("source_object_id") or issue.issue_id,
                "chapter_id": raw_memory.get("chapter_id") or issue.chapter_id,
                "scene_id": raw_memory.get("scene_id") or issue.scene_id,
                "memory_type": raw_memory.get("memory_type") or "event",
                "summary": raw_memory.get("summary") or summary,
                "keywords": [
                    *list(raw_memory.get("keywords") or raw_memory.get("tags") or []),
                    "non_objective_truth",
                    clean_status,
                ],
                "character_ids": raw_memory.get("character_ids") or issue.source_character_ids,
                "relationship_ids": raw_memory.get("relationship_ids") or issue.source_relationship_ids,
                "location": raw_memory.get("location") or None,
                "event_ids": raw_memory.get("event_ids") or issue.source_event_ids,
                "importance": raw_memory.get("importance") or "medium",
                "status": raw_memory.get("status") or "active",
                "truth_status": clean_status,
                "objective_truth": False,
                "source_issue_id": issue.issue_id,
                "speaker_character_id": raw_memory.get("speaker_character_id") or "",
                "believed_by_character_ids": raw_memory.get("believed_by_character_ids") or [],
                "known_false_by_character_ids": raw_memory.get("known_false_by_character_ids") or [],
                "version_id": raw_memory.get("version_id") or "phase2_m2_memory_source_index_v1",
                "created_at": raw_memory.get("created_at") or timestamp,
                "updated_at": timestamp,
                "source_type": raw_memory.get("source_type") or "continuity_issue",
                "object_type": raw_memory.get("object_type") or "continuity_issue",
                "object_id": raw_memory.get("object_id") or issue.issue_id,
                "tags": [
                    *list(raw_memory.get("tags") or raw_memory.get("keywords") or []),
                    "non_objective_truth",
                    clean_status,
                ],
                "embedding_ref": raw_memory.get("embedding_ref") or "",
            }
        )
        self.repositories.memory.upsert(model_to_dict(memory), "memory_id")
        decision = self._write_decision(
            "mark_non_objective_truth",
            "continuity_issue",
            issue.issue_id,
            user_input or f"将相关说法标记为 {clean_status}。",
        )
        resolved = self.continuity_gate_service.mark_issue_resolved(
            issue.issue_id,
            user_input or "相关说法已标记为非客观事实。",
        )
        return resolved, memory, decision

    def refresh_after_issue_action(
        self,
        *,
        action_type: str,
        action_status: str,
        issue_id: str,
        affected_issue_ids: list[str] | None = None,
        mode: str = "manual",
        recompute_quality_report: bool = False,
    ) -> ContinuityResolutionRefreshResult:
        return self.refresh_service.build_refresh_after_issue_action(
            action_type=action_type,
            action_status=action_status,
            issue_id=issue_id,
            affected_issue_ids=affected_issue_ids,
            mode=mode,
            recompute_quality_report=recompute_quality_report,
        )

    def refresh_for_candidate_action(
        self,
        candidate: PriorStoryCompletionCandidate,
        *,
        action_type: str,
        action_status: str,
        mode: str = "manual",
        recompute_quality_report: bool = False,
    ) -> ContinuityResolutionRefreshResult:
        issue_id = candidate.source_issue_id or candidate.issue_id
        return self.refresh_after_issue_action(
            action_type=action_type,
            action_status=action_status,
            issue_id=issue_id,
            affected_issue_ids=[issue_id],
            mode=mode,
            recompute_quality_report=recompute_quality_report,
        )

    def prior_story_completion_candidate_response(
        self,
        candidate: PriorStoryCompletionCandidate,
        *,
        decision: dict[str, Any] | None = None,
        action_type: str = "read_prior_story_completion_candidate",
        action_status: str = "current_candidate",
    ) -> PriorStoryCompletionCandidateResponse:
        refresh = self.refresh_for_candidate_action(
            candidate,
            action_type=action_type,
            action_status=action_status,
        )
        return PriorStoryCompletionCandidateResponse(
            candidate=candidate,
            decision=decision or {},
            candidate_decision=self.candidate_decision_view(candidate, decision or {}),
            write_plan=self.write_plan_for_candidate(candidate),
            lineage=self.lineage_for_candidate(candidate),
            refresh=refresh,
        )

    def get_prior_story_completion_candidate(
        self,
        candidate_id: str,
    ) -> PriorStoryCompletionCandidate:
        candidate = self._candidate(candidate_id)
        issue = self._issue(candidate.source_issue_id or candidate.issue_id)
        return self._ensure_candidate_project_scope(candidate, issue, persist=False)

    def list_prior_story_completion_candidates_for_issue(
        self,
        issue_id: str,
    ) -> list[PriorStoryCompletionCandidate]:
        candidates: list[PriorStoryCompletionCandidate] = []
        for raw in self.repositories.prior_story_completion_candidates.list_all():
            if not isinstance(raw, dict):
                continue
            source_issue_id = str(raw.get("source_issue_id") or raw.get("issue_id") or "")
            if source_issue_id != issue_id:
                continue
            try:
                candidates.append(PriorStoryCompletionCandidate(**raw))
            except ValidationError as exc:
                raise StorageError("PriorStoryCompletionCandidate JSON schema is invalid.") from exc
        return sorted(
            candidates,
            key=lambda item: (
                item.candidate_version_number,
                item.created_at,
                item.candidate_id,
            ),
            reverse=True,
        )

    def write_plan_for_candidate(
        self,
        candidate: PriorStoryCompletionCandidate,
    ) -> PriorStoryCompletionCandidateWritePlan:
        return PriorStoryCompletionCandidateWritePlan(
            candidate_id=candidate.candidate_id,
            source_issue_id=candidate.source_issue_id or candidate.issue_id,
            write_mode=candidate.write_mode,
            event_write_preview=dict(candidate.proposed_event or {}),
            memory_write_preview=dict(candidate.proposed_memory_record or {}),
            existing_event_ids=list(candidate.existing_event_ids),
            existing_memory_ids=list(candidate.existing_memory_ids),
            allowed_write_targets=list(candidate.allowed_write_targets),
            forbidden_write_targets=list(candidate.forbidden_write_targets),
            requires_user_confirmation=candidate.requires_user_confirmation,
            write_scope_hash=candidate.write_scope_hash,
            safe_summary=candidate.completion_scope_summary or candidate.user_visible_summary,
        )

    def candidate_decision_view(
        self,
        candidate: PriorStoryCompletionCandidate,
        decision: dict[str, Any] | None = None,
    ) -> PriorStoryCompletionCandidateDecision:
        raw_decision = decision or self._decision_by_id(candidate.decision_id)
        decision_id = str(raw_decision.get("decision_id") or candidate.decision_id or "")
        return PriorStoryCompletionCandidateDecision(
            candidate_decision_id=f"candidate_decision_{candidate.candidate_id}_{decision_id or 'current'}",
            candidate_id=candidate.candidate_id,
            source_issue_id=candidate.source_issue_id or candidate.issue_id,
            decision_type=_candidate_decision_type(raw_decision.get("decision_type")),
            user_input=str(raw_decision.get("user_input") or ""),
            decision_id=decision_id,
            does_not_confirm_other_issues=True,
            does_not_write_beyond_candidate_scope=True,
            created_at=str(raw_decision.get("created_at") or candidate.updated_at or candidate.created_at),
        )

    def lineage_for_candidate(
        self,
        candidate: PriorStoryCompletionCandidate,
    ) -> PriorStoryCompletionLineage:
        candidates_by_id = {
            str(raw.get("candidate_id") or ""): raw
            for raw in self.repositories.prior_story_completion_candidates.list_all()
            if isinstance(raw, dict) and raw.get("candidate_id")
        }
        superseded_candidate_ids: list[str] = []
        parent_id = candidate.parent_candidate_id
        while parent_id and parent_id in candidates_by_id:
            superseded_candidate_ids.append(parent_id)
            parent_id = str(candidates_by_id[parent_id].get("parent_candidate_id") or "")
        linked_event_ids = list(candidate.existing_event_ids)
        linked_memory_ids = list(candidate.existing_memory_ids)
        if candidate.status == "confirmed":
            event_id = str((candidate.proposed_event or {}).get("event_id") or "")
            memory_id = str((candidate.proposed_memory_record or {}).get("memory_id") or "")
            linked_event_ids = _unique_strings([*linked_event_ids, event_id])
            linked_memory_ids = _unique_strings([*linked_memory_ids, memory_id])
        chain_candidate_ids = _unique_strings(
            [
                candidate.candidate_id,
                *superseded_candidate_ids,
                candidate.superseded_by_candidate_id,
            ]
        )
        decision_ids = [
            str(item.get("decision_id") or "")
            for item in self.repositories.decisions.list_all()
            if str(item.get("target_id") or "") in chain_candidate_ids
        ]
        if candidate.decision_id:
            decision_ids.append(candidate.decision_id)
        return PriorStoryCompletionLineage(
            lineage_id=f"prior_story_completion_lineage_{candidate.candidate_id}",
            candidate_id=candidate.candidate_id,
            source_issue_id=candidate.source_issue_id or candidate.issue_id,
            parent_candidate_id=candidate.parent_candidate_id,
            superseded_candidate_ids=_unique_strings(superseded_candidate_ids),
            superseded_by_candidate_id=candidate.superseded_by_candidate_id,
            linked_event_ids=_unique_strings(linked_event_ids),
            linked_memory_ids=_unique_strings(linked_memory_ids),
            created_decision_ids=_unique_strings(decision_ids),
            safe_summary=candidate.user_visible_summary or candidate.completion_scope_summary,
        )

    def revise_prior_story_completion_candidate(
        self,
        candidate_id: str,
        *,
        user_input: str = "",
        revision_prompt: str = "",
    ) -> tuple[PriorStoryCompletionCandidate, dict[str, Any]]:
        candidate = self._candidate(candidate_id)
        issue = self._issue(candidate.source_issue_id or candidate.issue_id)
        candidate = self._ensure_candidate_project_scope(candidate, issue)
        project_id = self._current_project_id(issue)
        self.scope_guard.validate_revise(
            candidate=candidate,
            source_issue=issue,
            active_project_id=project_id,
        )
        prompt = (revision_prompt or user_input or "").strip()
        if not prompt:
            raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_REVISION_PROMPT_REQUIRED: Revision requires user input.")
        timestamp = now_iso()
        new_candidate_id = (
            f"prior_story_completion_candidate_{len(self.repositories.prior_story_completion_candidates.list_all()) + 1:03d}"
        )
        new_event_id = f"event_{new_candidate_id}"
        new_memory_id = f"memory_{new_candidate_id}"
        existing_event_ids, existing_memory_ids = self._find_existing_canon_sources(
            issue,
            prompt,
            include_issue_source_refs=False,
            include_issue_text=False,
        )
        has_existing_sources = bool(existing_event_ids or existing_memory_ids)
        write_mode = "link_existing_sources" if has_existing_sources else "create_new_event_memory"
        proposed_event = {}
        proposed_memory_record = {}
        if not has_existing_sources:
            proposed_event = {
                **(candidate.proposed_event or {}),
                "event_id": new_event_id,
                "scene_id": candidate.scene_id or issue.scene_id,
                "summary": prompt,
                "participants": list((candidate.proposed_event or {}).get("participants") or []),
                "location_id": str((candidate.proposed_event or {}).get("location_id") or "prior_story"),
                "cause": str((candidate.proposed_event or {}).get("cause") or "User revised prior-story completion candidate."),
                "result": prompt,
                "tags": _unique_strings(
                    [
                        *((candidate.proposed_event or {}).get("tags") or []),
                        "prior_story_completion_revision",
                    ]
                ),
                "status": "confirmed",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            proposed_memory_record = {
                **(candidate.proposed_memory_record or {}),
                "memory_id": new_memory_id,
                "project_id": project_id,
                "source_object_type": "continuity_issue",
                "source_object_id": candidate.source_issue_id or candidate.issue_id,
                "chapter_id": candidate.chapter_id or issue.chapter_id,
                "scene_id": candidate.scene_id or issue.scene_id,
                "memory_type": "event",
                "summary": prompt,
                "keywords": _unique_strings(
                    [
                        *((candidate.proposed_memory_record or {}).get("keywords") or []),
                        "prior_story_completion_revision",
                    ]
                ),
                "event_ids": [new_event_id],
                "status": "active",
                "truth_status": "objective_fact",
                "objective_truth": True,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        new_candidate = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(candidate),
                "candidate_id": new_candidate_id,
                "status": "pending",
                "candidate_status_reason": "revision_requested",
                "project_id": project_id,
                "user_visible_summary": prompt,
                "proposed_event": proposed_event,
                "proposed_memory_record": proposed_memory_record,
                "existing_event_ids": existing_event_ids,
                "existing_memory_ids": existing_memory_ids,
                "source_issue_id": candidate.source_issue_id or candidate.issue_id,
                "completion_scope_summary": self._completion_scope_summary(
                    write_mode=write_mode,
                    proposed_event=proposed_event,
                    proposed_memory_record=proposed_memory_record,
                    existing_event_ids=existing_event_ids,
                    existing_memory_ids=existing_memory_ids,
                ),
                "resolves_issue_explanation": (
                    f"Candidate revision still resolves continuity issue {candidate.source_issue_id or candidate.issue_id} only after user confirmation."
                ),
                "write_mode": write_mode,
                "allowed_write_targets": ["event", "memory_record"],
                "parent_candidate_id": candidate.candidate_id,
                "candidate_version_number": candidate.candidate_version_number + 1,
                "superseded_by_candidate_id": "",
                "decision_id": "",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        new_candidate = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(new_candidate),
                "write_scope_hash": self._write_scope_hash(model_to_dict(new_candidate)),
            }
        )
        decision = self._write_decision(
            "revise_prior_story_completion_candidate",
            "prior_story_completion_candidate",
            new_candidate.candidate_id,
            user_input or revision_prompt,
        )
        new_candidate = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(new_candidate),
                "decision_id": decision["decision_id"],
            }
        )
        superseded = PriorStoryCompletionCandidate(
            **{
                **model_to_dict(candidate),
                "status": "superseded",
                "candidate_status_reason": "superseded_by_revision",
                "superseded_by_candidate_id": new_candidate.candidate_id,
                "updated_at": timestamp,
            }
        )
        self.repositories.prior_story_completion_candidates.upsert(
            model_to_dict(superseded),
            "candidate_id",
        )
        self.repositories.prior_story_completion_candidates.append(model_to_dict(new_candidate))
        return new_candidate, decision

    def _find_existing_canon_sources(
        self,
        issue: ContinuityIssue,
        summary: str,
        *,
        include_issue_source_refs: bool = True,
        include_issue_text: bool = True,
    ) -> tuple[list[str], list[str]]:
        probe_values: list[Any] = [summary]
        if include_issue_text:
            probe_values.extend(
                [
                    issue.evidence_text,
                    issue.user_visible_message,
                    issue.technical_summary,
                ]
            )
        probes = _fact_match_probes(
            probe_values
        )
        event_ids = self._existing_event_ids(
            issue,
            probes,
            include_issue_source_refs=include_issue_source_refs,
        )
        memory_ids = self._existing_memory_ids(
            issue,
            probes,
            include_issue_source_refs=include_issue_source_refs,
        )
        return event_ids, memory_ids

    def _existing_event_ids(
        self,
        issue: ContinuityIssue,
        probes: list[str],
        *,
        include_issue_source_refs: bool = True,
    ) -> list[str]:
        event_ids: list[str] = []
        by_id = {
            str(event.get("event_id") or ""): event
            for event in self.repositories.events.list_all()
            if isinstance(event, dict)
        }
        if include_issue_source_refs:
            for event_id in issue.source_event_ids:
                event = by_id.get(event_id) or {}
                if str(event.get("status") or "") == "confirmed":
                    event_ids.append(event_id)
        for event_id, event in by_id.items():
            if not event_id or str(event.get("status") or "") != "confirmed":
                continue
            text = " ".join(
                [
                    str(event.get("summary") or ""),
                    str(event.get("result") or ""),
                    str(event.get("cause") or ""),
                ]
            )
            if _fact_matches(probes, text):
                event_ids.append(event_id)
        return _unique_strings(event_ids)

    def _existing_memory_ids(
        self,
        issue: ContinuityIssue,
        probes: list[str],
        *,
        include_issue_source_refs: bool = True,
    ) -> list[str]:
        memory_ids: list[str] = []
        by_id = {
            str(memory.get("memory_id") or ""): memory
            for memory in self.repositories.memory.list_all()
            if isinstance(memory, dict)
        }
        if include_issue_source_refs:
            for memory_id in issue.source_memory_ids:
                memory = by_id.get(memory_id) or {}
                if self._is_active_objective_memory(memory):
                    memory_ids.append(memory_id)
        for memory_id, memory in by_id.items():
            if not memory_id or not self._is_active_objective_memory(memory):
                continue
            text = " ".join(
                [
                    str(memory.get("summary") or ""),
                    " ".join(str(item) for item in memory.get("keywords") or []),
                    " ".join(str(item) for item in memory.get("tags") or []),
                ]
            )
            if _fact_matches(probes, text):
                memory_ids.append(memory_id)
        return _unique_strings(memory_ids)

    def _is_active_objective_memory(self, memory: dict[str, Any]) -> bool:
        if not memory or str(memory.get("status") or "") != "active":
            return False
        if memory.get("objective_truth") is False:
            return False
        return str(memory.get("truth_status") or "objective_fact") == "objective_fact"

    def _attach_existing_sources_to_issue(
        self,
        candidate: PriorStoryCompletionCandidate,
    ) -> None:
        issue_id = candidate.source_issue_id or candidate.issue_id
        raw = self.repositories.continuity_issues.get_by_id(issue_id)
        if raw is None:
            return
        updated = dict(raw)
        updated["source_event_ids"] = _unique_strings(
            [
                *list(updated.get("source_event_ids") or []),
                *candidate.existing_event_ids,
            ]
        )
        updated["source_memory_ids"] = _unique_strings(
            [
                *list(updated.get("source_memory_ids") or []),
                *candidate.existing_memory_ids,
            ]
        )
        updated["updated_at"] = now_iso()
        self.repositories.continuity_issues.upsert(updated, "issue_id")

    def _active_revision_candidate_for_issue(
        self,
        issue: ContinuityIssue,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        linked_candidate_id = issue.linked_revision_candidate_id
        for scene in self.repositories.scenes.list_all():
            if not isinstance(scene, dict):
                continue
            if scene.get("scene_id") != issue.scene_id:
                continue
            active_revision_id = str(scene.get("active_revision_id") or "")
            for candidate in scene.get("revision_history") or []:
                if not isinstance(candidate, dict):
                    continue
                revision_id = str(candidate.get("revision_id") or "")
                if candidate.get("status") != "candidate":
                    continue
                if active_revision_id and active_revision_id != revision_id:
                    continue
                source_issue_id = str(candidate.get("source_continuity_issue_id") or "")
                if source_issue_id == issue.issue_id or (
                    linked_candidate_id and revision_id == linked_candidate_id
                ):
                    return dict(scene), dict(candidate)
        return None

    def _link_issue_to_revision_candidate(
        self,
        issue: ContinuityIssue,
        candidate_data: dict[str, Any],
        *,
        lifecycle_status: str,
        lifecycle_message: str,
    ) -> ContinuityIssue:
        revision_id = str(candidate_data.get("revision_id") or "")
        candidate_status = str(candidate_data.get("status") or "candidate")
        updated = ContinuityIssue(
            **{
                **model_to_dict(issue),
                "status": "open",
                "linked_revision_candidate_id": revision_id,
                "linked_revision_candidate_status": candidate_status,
                "resolution_lifecycle_status": lifecycle_status,
                "resolution_lifecycle_message": lifecycle_message,
                "updated_at": now_iso(),
            }
        )
        self.repositories.continuity_issues.upsert(model_to_dict(updated), "issue_id")
        return updated

    def _issue(self, issue_id: str) -> ContinuityIssue:
        return self.continuity_gate_service.get_issue(issue_id)

    def _current_project_id(self, issue: ContinuityIssue | None = None) -> str:
        if issue is not None and issue.project_id and issue.project_id != LOCAL_PROJECT_ID:
            return issue.project_id
        project_id = current_story_workspace_project_id(
            self.store,
            self.data_dir,
            fallback=LOCAL_PROJECT_ID,
        )
        if project_id and project_id != LOCAL_PROJECT_ID:
            return project_id
        return issue.project_id if issue is not None and issue.project_id else project_id

    def _candidate(self, candidate_id: str) -> PriorStoryCompletionCandidate:
        raw = self.repositories.prior_story_completion_candidates.get_by_id(candidate_id)
        if raw is None:
            raise StorageError("PRIOR_STORY_COMPLETION_CANDIDATE_MISSING: 前情补全候选不存在。")
        try:
            return PriorStoryCompletionCandidate(**raw)
        except ValidationError as exc:
            raise StorageError("PriorStoryCompletionCandidate JSON schema is invalid.") from exc

    def _candidate_for_issue(self, issue_id: str) -> PriorStoryCompletionCandidate | None:
        candidates: list[PriorStoryCompletionCandidate] = []
        for raw in self.repositories.prior_story_completion_candidates.list_all():
            if not isinstance(raw, dict):
                continue
            try:
                candidate = PriorStoryCompletionCandidate(**raw)
            except ValidationError as exc:
                raise StorageError("PriorStoryCompletionCandidate JSON schema is invalid.") from exc
            if (candidate.source_issue_id or candidate.issue_id) != issue_id:
                continue
            if candidate.status != "pending":
                continue
            candidates.append(candidate)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                item.candidate_version_number,
                item.created_at,
                item.candidate_id,
            ),
            reverse=True,
        )[0]

    def _ensure_candidate_project_scope(
        self,
        candidate: PriorStoryCompletionCandidate,
        issue: ContinuityIssue,
        *,
        persist: bool = True,
    ) -> PriorStoryCompletionCandidate:
        project_id = self._current_project_id(issue)
        if candidate.project_id not in {"", LOCAL_PROJECT_ID, project_id}:
            raise StorageError(
                "PRIOR_STORY_COMPLETION_CANDIDATE_SCOPE_INVALID: Candidate project scope does not match active project."
            )
        proposed_memory = dict(candidate.proposed_memory_record or {})
        if proposed_memory:
            proposed_memory["project_id"] = project_id
        write_mode = candidate.write_mode
        if candidate.existing_event_ids or candidate.existing_memory_ids:
            write_mode = "link_existing_sources" if not (
                candidate.proposed_event or candidate.proposed_memory_record
            ) else "mixed"
        elif candidate.proposed_event or candidate.proposed_memory_record:
            write_mode = "create_new_event_memory"
        candidate_data = {
            **model_to_dict(candidate),
            "project_id": project_id,
            "proposed_memory_record": proposed_memory,
            "source_issue_id": candidate.source_issue_id or candidate.issue_id,
            "completion_scope_summary": candidate.completion_scope_summary
            or self._completion_scope_summary(
                write_mode=write_mode,
                proposed_event=candidate.proposed_event,
                proposed_memory_record=proposed_memory,
                existing_event_ids=candidate.existing_event_ids,
                existing_memory_ids=candidate.existing_memory_ids,
            ),
            "resolves_issue_explanation": candidate.resolves_issue_explanation
            or f"Candidate resolves continuity issue {candidate.source_issue_id or candidate.issue_id} only after user confirmation.",
            "write_mode": write_mode,
            "allowed_write_targets": candidate.allowed_write_targets or ["event", "memory_record"],
            "forbidden_write_targets": _unique_strings(
                [
                    *candidate.forbidden_write_targets,
                    *DEFAULT_PRIOR_STORY_COMPLETION_FORBIDDEN_WRITE_TARGETS,
                ]
            ),
            "requires_user_confirmation": True,
            "candidate_version_number": max(1, candidate.candidate_version_number),
            "updated_at": candidate.updated_at or now_iso(),
        }
        if not candidate_data.get("write_scope_hash"):
            candidate_data["write_scope_hash"] = self._write_scope_hash(candidate_data)
        scoped = PriorStoryCompletionCandidate(
            **candidate_data
        )
        if persist and model_to_dict(scoped) != model_to_dict(candidate):
            self.repositories.prior_story_completion_candidates.upsert(
                model_to_dict(scoped),
                "candidate_id",
            )
        return scoped

    def _next_candidate_version_number(self, issue_id: str) -> int:
        versions: list[int] = []
        for raw in self.repositories.prior_story_completion_candidates.list_all():
            if not isinstance(raw, dict):
                continue
            source_issue_id = str(raw.get("source_issue_id") or raw.get("issue_id") or "")
            if source_issue_id != issue_id:
                continue
            try:
                versions.append(max(1, int(raw.get("candidate_version_number") or 1)))
            except (TypeError, ValueError):
                versions.append(1)
        return (max(versions) + 1) if versions else 1

    def _completion_scope_summary(
        self,
        *,
        write_mode: str,
        proposed_event: dict[str, Any],
        proposed_memory_record: dict[str, Any],
        existing_event_ids: list[str],
        existing_memory_ids: list[str],
    ) -> str:
        if write_mode == "link_existing_sources":
            return (
                "Links existing event/memory sources only: "
                f"events={len(existing_event_ids)}, memories={len(existing_memory_ids)}."
            )
        event_id = str((proposed_event or {}).get("event_id") or "")
        memory_id = str((proposed_memory_record or {}).get("memory_id") or "")
        return f"Can create declared event {event_id} and memory {memory_id} after user confirmation."

    def _write_scope_hash(self, candidate_data: dict[str, Any]) -> str:
        payload = {
            "candidate_id": candidate_data.get("candidate_id"),
            "source_issue_id": candidate_data.get("source_issue_id") or candidate_data.get("issue_id"),
            "write_mode": candidate_data.get("write_mode"),
            "proposed_event": candidate_data.get("proposed_event") or {},
            "proposed_memory_record": candidate_data.get("proposed_memory_record") or {},
            "existing_event_ids": candidate_data.get("existing_event_ids") or [],
            "existing_memory_ids": candidate_data.get("existing_memory_ids") or [],
            "allowed_write_targets": candidate_data.get("allowed_write_targets") or [],
            "forbidden_write_targets": candidate_data.get("forbidden_write_targets") or [],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _decision_by_id(self, decision_id: str) -> dict[str, Any]:
        if not decision_id:
            return {}
        return self.repositories.decisions.get_by_id(decision_id) or {}

    def _record_legacy_candidate_creation_noop(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {}

    def _write_decision(
        self,
        decision_type: str,
        target_type: str,
        target_id: str,
        user_input: str,
    ) -> dict[str, Any]:
        decisions = self.repositories.decisions.list_all()
        decision = {
            "decision_id": f"decision_continuity_resolution_{len(decisions) + 1:03d}",
            "decision_type": decision_type,
            "target_type": target_type,
            "target_id": target_id,
            "user_input": user_input,
            "created_at": now_iso(),
        }
        decisions.append(decision)
        self.repositories.decisions.write_all(decisions)
        return decision


def _fact_match_probes(values: list[Any]) -> list[str]:
    probes: list[str] = []
    for value in values:
        normalized = _normalize_fact_text(value)
        if len(normalized) >= 8:
            probes.append(normalized)
    return _unique_strings(probes)


def _fact_matches(probes: list[str], value: Any) -> bool:
    normalized = _normalize_fact_text(value)
    if len(normalized) < 8:
        return False
    return any(
        probe in normalized or normalized in probe
        for probe in probes
        if len(probe) >= 8
    )


def _normalize_fact_text(value: Any) -> str:
    return "".join(
        character.casefold()
        for character in str(value or "")
        if character.isalnum()
    )


def _candidate_decision_type(decision_type: Any) -> str:
    text = str(decision_type or "")
    if text in {"create", "create_prior_story_completion_candidate"}:
        return "create"
    if text in {"confirm", "confirm_prior_story_completion_candidate"}:
        return "confirm"
    if text in {"reject", "reject_prior_story_completion_candidate"}:
        return "reject"
    if text in {"request_revision", "revise_prior_story_completion_candidate"}:
        return "request_revision"
    if text == "supersede":
        return "supersede"
    return "create"


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
