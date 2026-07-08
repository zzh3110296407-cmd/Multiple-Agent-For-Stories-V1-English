from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.backend.core.config import settings
from app.backend.models.background_budget import (
    BACKGROUND_BUDGET_SCHEMA_VERSION,
    EXECUTION_STRATEGIES,
    M6_NO_MODEL_POLICY_TYPES,
    BackgroundBudgetProfile,
    BackgroundBudgetProfileListResponse,
    BackgroundBudgetProfilePatchRequest,
    BackgroundBudgetStatusResponse,
    ModelRoutingDecisionRecord,
    TaskBudgetDecision,
    TaskBudgetEvaluateResponse,
    TaskBudgetUsageListResponse,
    TaskBudgetUsageRecord,
    TaskModelPolicy,
    TaskModelPolicyListResponse,
    TaskModelPolicyPatchRequest,
)
from app.backend.services.model_runtime_log_service import ModelRuntimeLogService
from app.backend.storage.json_store import JsonStore, StorageError


LOCAL_PROJECT_ID = "local_project"
SHANGHAI_TZ = timezone(timedelta(hours=8))
MAX_SAFE_TEXT_LENGTH = 700
MAX_SAFE_LABEL_LENGTH = 260
MAX_USAGE_RECORDS = 500
MAX_ROUTING_DECISIONS = 500
PROFILES_FILE_NAME = "background_budget_profiles.json"
POLICIES_FILE_NAME = "task_model_policies.json"
USAGE_FILE_NAME = "task_budget_usage_records.json"
ROUTING_FILE_NAME = "model_routing_decisions.json"
NO_MODEL_POLICY_TYPES = M6_NO_MODEL_POLICY_TYPES

UNSAFE_KEY_NAMES = {
    "prompt",
    "messages",
    "raw_prompt",
    "raw_response",
    "raw_text",
    "hidden_reasoning",
    "internal_reasoning",
    "chain_of_thought",
    "chain-of-thought",
    "cot",
    "prose_text",
    "revised_prose_text",
    "full_prose",
    "api_key",
    "api_key_ref",
    "authorization",
    "secret_key",
    "secret_token",
    "bearer_token",
}
UNSAFE_VALUE_MARKERS = {
    "MODEL_PROMPT_SHOULD_NOT_STORE",
    "raw_prompt",
    "raw prompt",
    "raw_response",
    "raw response",
    "raw_text",
    "raw text",
    "hidden_reasoning",
    "hidden reasoning",
    "internal_reasoning",
    "internal reasoning",
    "chain-of-thought",
    "chain of thought",
    "chain_of_thought",
    "prose_text",
    "prose text",
    "revised_prose_text",
    "revised prose text",
    "full_prose",
    "bearer ",
}
SECRET_LIKE_PATTERNS = [
    re.compile(r"(?i)(?:^|[^a-z0-9])sk-[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(r"(?i)(?:^|[^a-z0-9])lsv2_[a-z0-9][a-z0-9_\-]{8,}"),
    re.compile(
        r"(?i)(?:api[_\-\s]?key|secret[_\-\s]?(?:key|token)|authorization)\s*[:=]\s*[a-z0-9_\-]{8,}"
    ),
]


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).replace(microsecond=0).isoformat()


def model_to_dict(model: BaseModel | Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _short_text(value: Any, limit: int = MAX_SAFE_LABEL_LENGTH) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def _safe_string_list(value: Any, limit: int = 30) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _short_text(item, MAX_SAFE_LABEL_LENGTH)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


class BackgroundBudgetService:
    def __init__(
        self,
        *,
        store: JsonStore | None = None,
        data_dir: Path | None = None,
        runtime_logs: ModelRuntimeLogService | None = None,
    ) -> None:
        self.store = store or JsonStore()
        self.data_dir = data_dir or settings.data_dir
        self.profiles_file = self.data_dir / PROFILES_FILE_NAME
        self.policies_file = self.data_dir / POLICIES_FILE_NAME
        self.usage_file = self.data_dir / USAGE_FILE_NAME
        self.routing_file = self.data_dir / ROUTING_FILE_NAME
        self.runtime_logs = runtime_logs or ModelRuntimeLogService(
            store=self.store,
            data_dir=self.data_dir,
        )

    def seed_defaults_if_missing(self) -> None:
        timestamp = now_iso()
        if not self.store.exists(self.profiles_file):
            self._write_profiles(self._default_profiles(timestamp))
        if not self.store.exists(self.policies_file):
            self._write_policies(self._default_policies(timestamp))
        if not self.store.exists(self.usage_file):
            self._write_usage([])
        if not self.store.exists(self.routing_file):
            self._write_routing_decisions([])

    def list_profiles(self) -> list[BackgroundBudgetProfile]:
        self.seed_defaults_if_missing()
        return sorted(self._read_profiles(), key=lambda item: item.profile_id)

    def list_policies(self) -> list[TaskModelPolicy]:
        self.seed_defaults_if_missing()
        return sorted(self._read_policies(), key=lambda item: item.policy_id)

    def get_status(self, limit: int = 8) -> BackgroundBudgetStatusResponse:
        profiles = self.list_profiles()
        policies = self.list_policies()
        usage = self.list_usage(limit=limit)
        routing = self.list_routing_decisions(limit=limit)
        status = BackgroundBudgetStatusResponse(
            profile_count=len(profiles),
            policy_count=len(policies),
            enabled_profile_ids=[
                profile.profile_id for profile in profiles if profile.enabled
            ],
            active_background_profile_ids=[
                profile.profile_id
                for profile in profiles
                if profile.profile_id.startswith("background_")
                and profile.enabled
                and profile.allow_task_execution
            ],
            recent_usage_records=usage,
            recent_routing_decisions=routing,
            model_runtime_status=self._model_runtime_summary(),
        )
        status.safety = self._safety(model_to_dict(status))
        self._guard_safe_payload(status)
        return status

    def profile_response(self) -> BackgroundBudgetProfileListResponse:
        profiles = self.list_profiles()
        response = BackgroundBudgetProfileListResponse(profiles=profiles, count=len(profiles))
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def policy_response(self) -> TaskModelPolicyListResponse:
        policies = self.list_policies()
        response = TaskModelPolicyListResponse(policies=policies, count=len(policies))
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def usage_response(
        self,
        *,
        limit: int = 50,
        task_type: str = "",
        task_id: str = "",
    ) -> TaskBudgetUsageListResponse:
        usage = self.list_usage(limit=limit, task_type=task_type, task_id=task_id)
        routing = self.list_routing_decisions(limit=limit, task_type=task_type, task_id=task_id)
        response = TaskBudgetUsageListResponse(
            usage_records=usage,
            routing_decisions=routing,
            count=len(usage),
        )
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def evaluate_task_execution(
        self,
        *,
        task_type: str,
        task_id: str = "",
        requested_profile_id: str = "",
        requested_execution_strategy: str = "",
        snapshot_ids: list[str] | None = None,
        source_object_type: str = "",
        source_object_id: str = "",
    ) -> TaskBudgetEvaluateResponse:
        self.seed_defaults_if_missing()
        clean_task_type = _short_text(task_type, MAX_SAFE_LABEL_LENGTH)
        clean_task_id = _short_text(task_id, MAX_SAFE_LABEL_LENGTH)
        clean_requested_strategy = _short_text(requested_execution_strategy, MAX_SAFE_LABEL_LENGTH)
        clean_profile_id = _short_text(requested_profile_id, MAX_SAFE_LABEL_LENGTH)
        clean_snapshot_ids = _safe_string_list(snapshot_ids or [])
        self._guard_safe_payload(
            {
                "task_type": clean_task_type,
                "task_id": clean_task_id,
                "requested_profile_id": clean_profile_id,
                "requested_execution_strategy": clean_requested_strategy,
                "snapshot_ids": clean_snapshot_ids,
                "source_object_type": source_object_type,
                "source_object_id": source_object_id,
            }
        )

        policies_by_type = {policy.task_type: policy for policy in self._read_policies()}
        policy = policies_by_type.get(clean_task_type)
        if policy is None:
            decision = self._decision(
                allowed=False,
                task_type=clean_task_type,
                task_id=clean_task_id,
                policy_id="",
                profile_id=clean_profile_id,
                requested_execution_strategy=clean_requested_strategy,
                selected_execution_strategy="blocked",
                decision_reason="Unknown task type is blocked by the background budget guard.",
                warnings=["unknown_task_type"],
            )
            routing = self.record_routing_decision(decision, fallback_reason="unknown_task_type")
            return self._evaluate_response(decision, routing)

        if policy.status == "disabled":
            decision = self._decision(
                allowed=False,
                task_type=clean_task_type,
                task_id=clean_task_id,
                policy_id=policy.policy_id,
                profile_id=policy.default_profile_id,
                requested_execution_strategy=clean_requested_strategy,
                selected_execution_strategy="blocked",
                decision_reason="Task policy is disabled.",
                warnings=["policy_disabled"],
            )
            routing = self.record_routing_decision(decision, fallback_reason="policy_disabled")
            return self._evaluate_response(decision, routing)

        profiles_by_id = {profile.profile_id: profile for profile in self._read_profiles()}
        profile_id = clean_profile_id or policy.default_profile_id
        warnings: list[str] = []
        if profile_id not in policy.allowed_profile_ids:
            warnings.append("requested_profile_not_allowed")
            profile_id = policy.fallback_profile_id or policy.default_profile_id
        profile = profiles_by_id.get(profile_id)
        if profile is None:
            decision = self._decision(
                allowed=False,
                task_type=clean_task_type,
                task_id=clean_task_id,
                policy_id=policy.policy_id,
                profile_id=profile_id,
                requested_execution_strategy=clean_requested_strategy,
                selected_execution_strategy="blocked",
                decision_reason="Budget profile is missing.",
                warnings=warnings + ["profile_missing"],
            )
            routing = self.record_routing_decision(decision, fallback_reason="profile_missing")
            return self._evaluate_response(decision, routing)

        if policy.require_snapshot_refs and not clean_snapshot_ids:
            decision = self._decision_from_profile(
                profile=profile,
                policy=policy,
                task_type=clean_task_type,
                task_id=clean_task_id,
                requested_execution_strategy=clean_requested_strategy,
                selected_execution_strategy="blocked",
                allowed=False,
                decision_reason="Required snapshot refs are missing; task is blocked.",
                warnings=warnings + ["snapshot_refs_required"],
            )
            routing = self.record_routing_decision(decision, fallback_reason="snapshot_refs_required")
            return self._evaluate_response(decision, routing)

        if not profile.enabled or not profile.allow_task_execution or profile.default_execution_strategy == "blocked":
            decision = self._decision_from_profile(
                profile=profile,
                policy=policy,
                task_type=clean_task_type,
                task_id=clean_task_id,
                requested_execution_strategy=clean_requested_strategy,
                selected_execution_strategy="blocked",
                allowed=False,
                decision_reason="Selected budget profile blocks task execution.",
                warnings=warnings + ["profile_blocks_execution"],
            )
            routing = self.record_routing_decision(decision, fallback_reason="profile_blocks_execution")
            return self._evaluate_response(decision, routing)

        selected_strategy = clean_requested_strategy or profile.default_execution_strategy
        if selected_strategy not in EXECUTION_STRATEGIES:
            selected_strategy = self._policy_fallback_strategy(policy, profile)
            warnings.append("requested_strategy_invalid")
        if selected_strategy not in profile.allowed_execution_strategies:
            selected_strategy = self._policy_fallback_strategy(policy, profile)
            warnings.append("requested_strategy_not_allowed_by_profile")
        if selected_strategy == "model_gateway" and (
            not policy.allow_model_gateway
            or not profile.allow_model_gateway
            or profile.max_model_calls_per_task <= 0
        ):
            selected_strategy = self._policy_fallback_strategy(policy, profile)
            warnings.append("model_gateway_not_allowed")
        if selected_strategy == "model_gateway" and clean_task_type in NO_MODEL_POLICY_TYPES:
            selected_strategy = self._policy_fallback_strategy(policy, profile)
            warnings.append("m6_no_model_policy")
        if selected_strategy == "blocked":
            allowed = False
            reason = "Budget guard selected blocked execution."
        else:
            allowed = True
            reason = (
                "Model gateway is allowed for this task."
                if selected_strategy == "model_gateway"
                else "Task will use safe deterministic or no-model execution."
            )

        decision = self._decision_from_profile(
            profile=profile,
            policy=policy,
            task_type=clean_task_type,
            task_id=clean_task_id,
            requested_execution_strategy=clean_requested_strategy,
            selected_execution_strategy=selected_strategy,
            allowed=allowed,
            decision_reason=reason,
            warnings=warnings,
        )
        fallback_reason = ";".join(warnings) if warnings else ""
        routing = self.record_routing_decision(decision, fallback_reason=fallback_reason)
        return self._evaluate_response(decision, routing)

    def record_routing_decision(
        self,
        decision: TaskBudgetDecision,
        *,
        fallback_reason: str = "",
    ) -> ModelRoutingDecisionRecord:
        self.seed_defaults_if_missing()
        records = self._read_routing_decisions()
        record = ModelRoutingDecisionRecord(
            routing_decision_id=f"model_routing_decision_{len(records) + 1:06d}",
            task_type=decision.task_type,
            task_id=decision.task_id,
            policy_id=decision.policy_id,
            profile_id=decision.profile_id,
            requested_execution_strategy=decision.requested_execution_strategy,
            selected_execution_strategy=decision.selected_execution_strategy,
            selected_model_role=decision.selected_model_role,
            model_gateway_allowed=decision.model_gateway_allowed,
            allowed=decision.allowed,
            decision_reason=_short_text(decision.decision_reason, 260),
            fallback_reason=_short_text(fallback_reason, 260),
            created_at=now_iso(),
        )
        records.append(record)
        self._write_routing_decisions(records[-MAX_ROUTING_DECISIONS:])
        return record

    def record_task_usage(
        self,
        *,
        task_type: str,
        task_id: str = "",
        source_object_type: str = "",
        source_object_id: str = "",
        decision: TaskBudgetDecision | None = None,
        policy_id: str = "",
        profile_id: str = "",
        requested_execution_strategy: str = "",
        selected_execution_strategy: str = "",
        model_gateway_allowed: bool = False,
        model_call_ids: list[str] | None = None,
        fallback_used: bool = False,
        deterministic_used: bool = False,
        blocked: bool = False,
        status: str = "recorded",
        safe_error: dict[str, Any] | None = None,
    ) -> TaskBudgetUsageRecord:
        self.seed_defaults_if_missing()
        clean_call_ids = _safe_string_list(model_call_ids or [], limit=20)
        model_records = [
            self.runtime_logs.get_call(call_id)
            for call_id in clean_call_ids
        ]
        model_records = [record for record in model_records if record is not None]
        provider_types = _safe_string_list([record.provider_type for record in model_records], limit=10)
        model_names = _safe_string_list([record.model_name for record in model_records], limit=10)
        usage = self._read_usage()
        selected = selected_execution_strategy or (decision.selected_execution_strategy if decision else "")
        requested = requested_execution_strategy or (decision.requested_execution_strategy if decision else "")
        record = TaskBudgetUsageRecord(
            usage_record_id=f"task_budget_usage_{len(usage) + 1:06d}",
            task_type=_short_text(task_type, MAX_SAFE_LABEL_LENGTH),
            task_id=_short_text(task_id, MAX_SAFE_LABEL_LENGTH),
            source_object_type=_short_text(source_object_type, MAX_SAFE_LABEL_LENGTH),
            source_object_id=_short_text(source_object_id, MAX_SAFE_LABEL_LENGTH),
            policy_id=policy_id or (decision.policy_id if decision else ""),
            profile_id=profile_id or (decision.profile_id if decision else ""),
            requested_execution_strategy=requested,
            selected_execution_strategy=selected,
            model_gateway_allowed=(
                bool(model_gateway_allowed)
                or bool(decision.model_gateway_allowed if decision else False)
            ),
            model_call_ids=clean_call_ids,
            model_call_count=len(clean_call_ids),
            model_success_count=sum(1 for record in model_records if record.success),
            model_failure_count=sum(1 for record in model_records if not record.success),
            provider_types=provider_types,
            model_names=model_names,
            fallback_used=bool(fallback_used),
            deterministic_used=bool(deterministic_used),
            blocked=bool(blocked),
            status=status,
            safe_error=self._sanitize_payload(safe_error or {}),
            created_at=now_iso(),
        )
        self._guard_safe_payload(record)
        usage.append(record)
        self._write_usage(usage[-MAX_USAGE_RECORDS:])
        return record

    def list_usage(
        self,
        *,
        limit: int = 50,
        task_type: str = "",
        task_id: str = "",
    ) -> list[TaskBudgetUsageRecord]:
        self.seed_defaults_if_missing()
        clean_type = str(task_type or "").strip()
        clean_id = str(task_id or "").strip()
        records = list(reversed(self._read_usage()))
        if clean_type:
            records = [record for record in records if record.task_type == clean_type]
        if clean_id:
            records = [record for record in records if record.task_id == clean_id]
        return records[: max(1, min(int(limit or 50), 200))]

    def list_routing_decisions(
        self,
        *,
        limit: int = 50,
        task_type: str = "",
        task_id: str = "",
    ) -> list[ModelRoutingDecisionRecord]:
        self.seed_defaults_if_missing()
        clean_type = str(task_type or "").strip()
        clean_id = str(task_id or "").strip()
        records = list(reversed(self._read_routing_decisions()))
        if clean_type:
            records = [record for record in records if record.task_type == clean_type]
        if clean_id:
            records = [record for record in records if record.task_id == clean_id]
        return records[: max(1, min(int(limit or 50), 200))]

    def patch_profile(
        self,
        profile_id: str,
        request: BackgroundBudgetProfilePatchRequest | dict[str, Any],
    ) -> BackgroundBudgetProfile:
        self.seed_defaults_if_missing()
        normalized = (
            request
            if isinstance(request, BackgroundBudgetProfilePatchRequest)
            else BackgroundBudgetProfilePatchRequest(**request)
        )
        patch = self._request_dict(normalized)
        self._guard_patch_payload(patch)
        profiles = self._read_profiles()
        target = next((profile for profile in profiles if profile.profile_id == profile_id), None)
        if target is None:
            raise StorageError("BACKGROUND_BUDGET_PROFILE_NOT_FOUND: profile does not exist.")
        candidate_data = {**model_to_dict(target), **patch, "updated_at": now_iso()}
        candidate = BackgroundBudgetProfile(**candidate_data)
        self._validate_profile(candidate)
        updated = [candidate if profile.profile_id == profile_id else profile for profile in profiles]
        self._ensure_background_execution_available(updated)
        self._write_profiles(updated)
        return candidate

    def patch_policy(
        self,
        policy_id: str,
        request: TaskModelPolicyPatchRequest | dict[str, Any],
    ) -> TaskModelPolicy:
        self.seed_defaults_if_missing()
        normalized = (
            request
            if isinstance(request, TaskModelPolicyPatchRequest)
            else TaskModelPolicyPatchRequest(**request)
        )
        patch = self._request_dict(normalized)
        self._guard_patch_payload(patch)
        policies = self._read_policies()
        target = next((policy for policy in policies if policy.policy_id == policy_id), None)
        if target is None:
            raise StorageError("BACKGROUND_BUDGET_POLICY_NOT_FOUND: policy does not exist.")
        candidate_data = {**model_to_dict(target), **patch, "updated_at": now_iso()}
        candidate = TaskModelPolicy(**candidate_data)
        self._validate_policy(candidate)
        if candidate.task_type in NO_MODEL_POLICY_TYPES and candidate.allow_model_gateway:
            raise StorageError(
                "BACKGROUND_BUDGET_POLICY_INVALID: M6 v1 does not allow model gateway for this policy."
            )
        updated = [candidate if policy.policy_id == policy_id else policy for policy in policies]
        self._write_policies(updated)
        return candidate

    def debug_summary(self) -> dict[str, Any]:
        status = self.get_status(limit=8)
        payload = {
            "available": True,
            "profile_count": status.profile_count,
            "policy_count": status.policy_count,
            "enabled_profile_ids": status.enabled_profile_ids,
            "active_background_profile_ids": status.active_background_profile_ids,
            "recent_usage_records": [
                self._usage_debug(record) for record in status.recent_usage_records
            ],
            "recent_routing_decisions": [
                self._routing_debug(record) for record in status.recent_routing_decisions
            ],
            "model_runtime_status": status.model_runtime_status,
            "storage_files": [
                PROFILES_FILE_NAME,
                POLICIES_FILE_NAME,
                USAGE_FILE_NAME,
                ROUTING_FILE_NAME,
            ],
            "safety": status.safety,
        }
        self._guard_safe_payload(payload)
        return payload

    def _evaluate_response(
        self,
        decision: TaskBudgetDecision,
        routing: ModelRoutingDecisionRecord,
    ) -> TaskBudgetEvaluateResponse:
        response = TaskBudgetEvaluateResponse(decision=decision, routing_decision=routing)
        response.safety = self._safety(model_to_dict(response))
        self._guard_safe_payload(response)
        return response

    def _decision(
        self,
        *,
        allowed: bool,
        task_type: str,
        task_id: str,
        policy_id: str,
        profile_id: str,
        requested_execution_strategy: str,
        selected_execution_strategy: str,
        decision_reason: str,
        warnings: list[str],
    ) -> TaskBudgetDecision:
        return TaskBudgetDecision(
            allowed=allowed,
            task_type=_short_text(task_type, MAX_SAFE_LABEL_LENGTH),
            task_id=_short_text(task_id, MAX_SAFE_LABEL_LENGTH),
            policy_id=_short_text(policy_id, MAX_SAFE_LABEL_LENGTH),
            profile_id=_short_text(profile_id, MAX_SAFE_LABEL_LENGTH),
            requested_execution_strategy=_short_text(requested_execution_strategy, MAX_SAFE_LABEL_LENGTH),
            selected_execution_strategy=selected_execution_strategy,
            fallback_execution_strategy="deterministic_fallback",
            decision_reason=_short_text(decision_reason, 260),
            warnings=_safe_string_list(warnings, 10),
        )

    def _decision_from_profile(
        self,
        *,
        profile: BackgroundBudgetProfile,
        policy: TaskModelPolicy,
        task_type: str,
        task_id: str,
        requested_execution_strategy: str,
        selected_execution_strategy: str,
        allowed: bool,
        decision_reason: str,
        warnings: list[str],
    ) -> TaskBudgetDecision:
        model_allowed = (
            selected_execution_strategy == "model_gateway"
            and policy.allow_model_gateway
            and profile.allow_model_gateway
            and profile.max_model_calls_per_task > 0
        )
        return TaskBudgetDecision(
            allowed=allowed,
            task_type=task_type,
            task_id=task_id,
            policy_id=policy.policy_id,
            profile_id=profile.profile_id,
            requested_execution_strategy=requested_execution_strategy,
            selected_execution_strategy=selected_execution_strategy,
            selected_model_role=profile.selected_model_role,
            model_gateway_allowed=model_allowed,
            max_model_calls_per_task=profile.max_model_calls_per_task if model_allowed else 0,
            max_retry_count=profile.max_retry_count if model_allowed else 0,
            max_output_tokens=profile.max_output_tokens if model_allowed else 0,
            temperature=profile.temperature if model_allowed else 0.0,
            fallback_execution_strategy=self._policy_fallback_strategy(policy, profile),
            decision_reason=_short_text(decision_reason, 260),
            warnings=_safe_string_list(warnings, 10),
        )

    def _policy_fallback_strategy(
        self,
        policy: TaskModelPolicy,
        profile: BackgroundBudgetProfile,
    ) -> str:
        strategy = policy.fallback_execution_strategy or profile.fallback_execution_strategy
        if strategy not in EXECUTION_STRATEGIES:
            return "deterministic_fallback"
        return strategy

    def _default_profiles(self, timestamp: str) -> list[BackgroundBudgetProfile]:
        def profile(**kwargs: Any) -> BackgroundBudgetProfile:
            return BackgroundBudgetProfile(updated_at=timestamp, **kwargs)

        return [
            profile(
                profile_id="foreground_high_quality",
                label="Foreground high quality",
                description="Foreground task profile for high quality model use.",
                allow_model_gateway=True,
                allowed_execution_strategies=["model_gateway", "deterministic_fallback"],
                default_execution_strategy="model_gateway",
                selected_model_role="scene",
                max_model_calls_per_task=1,
                max_retry_count=1,
                max_output_tokens=6000,
                temperature=0.7,
            ),
            profile(
                profile_id="foreground_standard",
                label="Foreground standard",
                description="Foreground task profile for standard model use.",
                allow_model_gateway=True,
                allowed_execution_strategies=["model_gateway", "deterministic_fallback"],
                default_execution_strategy="model_gateway",
                selected_model_role="scene",
                max_model_calls_per_task=1,
                max_retry_count=1,
                max_output_tokens=4000,
                temperature=0.7,
            ),
            profile(
                profile_id="background_standard",
                label="Background standard",
                description="Background tasks default to deterministic fallback while allowing explicit model use.",
                allow_model_gateway=True,
                allowed_execution_strategies=["deterministic_fallback", "model_gateway"],
                default_execution_strategy="deterministic_fallback",
                selected_model_role="scene",
                max_model_calls_per_task=1,
                max_retry_count=0,
                max_output_tokens=1200,
                temperature=0.2,
            ),
            profile(
                profile_id="background_low",
                label="Background low",
                description="No-model low budget background profile.",
                allow_model_gateway=False,
                allowed_execution_strategies=["deterministic_fallback", "no_model"],
                default_execution_strategy="deterministic_fallback",
                max_model_calls_per_task=0,
                max_retry_count=0,
                max_output_tokens=0,
                temperature=0,
            ),
            profile(
                profile_id="background_disabled",
                label="Background disabled",
                description="Blocks background task execution.",
                enabled=True,
                allow_task_execution=False,
                allow_model_gateway=False,
                allowed_execution_strategies=["blocked"],
                default_execution_strategy="blocked",
                max_model_calls_per_task=0,
                max_retry_count=0,
                max_output_tokens=0,
                temperature=0,
                fallback_execution_strategy="blocked",
            ),
            profile(
                profile_id="background_high",
                label="Background high",
                description="Compatibility profile for existing M2 background_high tasks.",
                allow_model_gateway=True,
                allowed_execution_strategies=["model_gateway", "deterministic_fallback"],
                default_execution_strategy="model_gateway",
                selected_model_role="scene",
                max_model_calls_per_task=1,
                max_retry_count=1,
                max_output_tokens=2000,
                temperature=0.2,
                compatibility_alias_for="foreground_standard",
            ),
        ]

    def _default_policies(self, timestamp: str) -> list[TaskModelPolicy]:
        def policy(**kwargs: Any) -> TaskModelPolicy:
            return TaskModelPolicy(updated_at=timestamp, **kwargs)

        return [
            policy(
                policy_id="policy_foreground_scene_generation",
                task_type="foreground_scene_generation",
                default_profile_id="foreground_standard",
                allowed_profile_ids=["foreground_standard", "foreground_high_quality"],
                allow_model_gateway=True,
                safe_failure_mode="fallback",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_foreground_scene_revision",
                task_type="foreground_scene_revision",
                default_profile_id="foreground_standard",
                allowed_profile_ids=["foreground_standard", "foreground_high_quality"],
                allow_model_gateway=True,
                safe_failure_mode="fallback",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_background_thinking",
                task_type="background_thinking",
                default_profile_id="background_standard",
                allowed_profile_ids=[
                    "background_low",
                    "background_standard",
                    "background_high",
                    "background_disabled",
                ],
                allow_model_gateway=True,
                require_snapshot_refs=True,
                safe_failure_mode="fallback",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_pre_modify_candidate",
                task_type="pre_modify_candidate",
                default_profile_id="background_low",
                allowed_profile_ids=["background_low", "background_disabled"],
                allow_model_gateway=False,
                safe_failure_mode="record_only",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_candidate_cache_visibility",
                task_type="candidate_cache_visibility",
                default_profile_id="background_low",
                allowed_profile_ids=["background_low", "background_disabled"],
                allow_model_gateway=False,
                safe_failure_mode="record_only",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_future_issue_extraction",
                task_type="future_issue_extraction",
                default_profile_id="background_low",
                allowed_profile_ids=["background_low", "background_disabled"],
                allow_model_gateway=False,
                safe_failure_mode="record_only",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_delayed_question_generation",
                task_type="delayed_question_generation",
                default_profile_id="background_low",
                allowed_profile_ids=["background_low", "background_disabled"],
                allow_model_gateway=False,
                safe_failure_mode="record_only",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_chapter_framework_build",
                task_type="chapter_framework_build",
                default_profile_id="foreground_standard",
                allowed_profile_ids=["foreground_standard", "foreground_high_quality", "background_low"],
                allow_model_gateway=True,
                safe_failure_mode="fallback",
                fallback_profile_id="background_low",
            ),
            policy(
                policy_id="policy_modification_impact_preview",
                task_type="modification_impact_preview",
                default_profile_id="background_low",
                allowed_profile_ids=["background_low", "background_disabled"],
                allow_model_gateway=False,
                safe_failure_mode="record_only",
                fallback_profile_id="background_low",
            ),
        ]

    def _validate_profile(self, profile: BackgroundBudgetProfile) -> None:
        if not profile.allow_model_gateway and profile.max_model_calls_per_task != 0:
            raise StorageError(
                "BACKGROUND_BUDGET_PROFILE_INVALID: max_model_calls_per_task must be 0 when model gateway is disabled."
            )
        if profile.default_execution_strategy not in profile.allowed_execution_strategies:
            raise StorageError(
                "BACKGROUND_BUDGET_PROFILE_INVALID: default strategy must be allowed."
            )
        if profile.fallback_execution_strategy not in profile.allowed_execution_strategies and profile.fallback_execution_strategy != "deterministic_fallback":
            raise StorageError(
                "BACKGROUND_BUDGET_PROFILE_INVALID: fallback strategy must be allowed."
            )

    def _validate_policy(self, policy: TaskModelPolicy) -> None:
        profile_ids = {profile.profile_id for profile in self._read_profiles()}
        if policy.default_profile_id not in profile_ids:
            raise StorageError("BACKGROUND_BUDGET_POLICY_INVALID: default profile does not exist.")
        if policy.default_profile_id not in policy.allowed_profile_ids:
            raise StorageError("BACKGROUND_BUDGET_POLICY_INVALID: default profile must be allowed.")
        if policy.fallback_profile_id and policy.fallback_profile_id not in profile_ids:
            raise StorageError("BACKGROUND_BUDGET_POLICY_INVALID: fallback profile does not exist.")
        for profile_id in policy.allowed_profile_ids:
            if profile_id not in profile_ids:
                raise StorageError("BACKGROUND_BUDGET_POLICY_INVALID: allowed profile does not exist.")

    def _ensure_background_execution_available(self, profiles: list[BackgroundBudgetProfile]) -> None:
        active = [
            profile
            for profile in profiles
            if profile.profile_id in {"background_low", "background_standard", "background_high"}
            and profile.enabled
            and profile.allow_task_execution
        ]
        if not active:
            raise StorageError(
                "BACKGROUND_BUDGET_PROFILE_INVALID: at least one executable background profile must remain enabled."
            )

    def _model_runtime_summary(self) -> dict[str, Any]:
        calls = self.runtime_logs.recent_calls(limit=20)
        logs = self.runtime_logs.read_logs()
        provider_health = logs.provider_health[:5]
        return {
            "recent_call_count": len(calls),
            "recent_success_count": sum(1 for call in calls if call.success),
            "recent_failure_count": sum(1 for call in calls if not call.success),
            "provider_health": [
                {
                    "provider_type": _short_text(item.provider_type, 80),
                    "model_name": _short_text(item.model_name, 120),
                    "status": _short_text(item.status, 80),
                    "configured": bool(item.configured),
                    "recent_success_count": item.recent_success_count,
                    "recent_failure_count": item.recent_failure_count,
                }
                for item in provider_health
            ],
        }

    def _usage_debug(self, record: TaskBudgetUsageRecord) -> dict[str, Any]:
        return {
            "usage_record_id": record.usage_record_id,
            "task_type": record.task_type,
            "task_id": record.task_id,
            "source_object_type": record.source_object_type,
            "source_object_id": record.source_object_id,
            "profile_id": record.profile_id,
            "selected_execution_strategy": record.selected_execution_strategy,
            "model_call_count": record.model_call_count,
            "model_success_count": record.model_success_count,
            "model_failure_count": record.model_failure_count,
            "fallback_used": record.fallback_used,
            "deterministic_used": record.deterministic_used,
            "blocked": record.blocked,
            "status": record.status,
            "safe_error": record.safe_error,
            "created_at": record.created_at,
        }

    def _routing_debug(self, record: ModelRoutingDecisionRecord) -> dict[str, Any]:
        return {
            "routing_decision_id": record.routing_decision_id,
            "task_type": record.task_type,
            "task_id": record.task_id,
            "profile_id": record.profile_id,
            "requested_execution_strategy": record.requested_execution_strategy,
            "selected_execution_strategy": record.selected_execution_strategy,
            "model_gateway_allowed": record.model_gateway_allowed,
            "allowed": record.allowed,
            "decision_reason": record.decision_reason,
            "fallback_reason": record.fallback_reason,
            "created_at": record.created_at,
        }

    def _read_profiles(self) -> list[BackgroundBudgetProfile]:
        if not self.store.exists(self.profiles_file):
            return []
        result: list[BackgroundBudgetProfile] = []
        try:
            for item in self.store.read_list(self.profiles_file):
                result.append(BackgroundBudgetProfile(**item))
        except (StorageError, ValidationError) as exc:
            raise StorageError("BACKGROUND_BUDGET_SCHEMA_INVALID: profile storage schema is invalid.") from exc
        return result

    def _read_policies(self) -> list[TaskModelPolicy]:
        if not self.store.exists(self.policies_file):
            return []
        result: list[TaskModelPolicy] = []
        try:
            for item in self.store.read_list(self.policies_file):
                result.append(TaskModelPolicy(**item))
        except (StorageError, ValidationError) as exc:
            raise StorageError("BACKGROUND_BUDGET_SCHEMA_INVALID: policy storage schema is invalid.") from exc
        return result

    def _read_usage(self) -> list[TaskBudgetUsageRecord]:
        if not self.store.exists(self.usage_file):
            return []
        result: list[TaskBudgetUsageRecord] = []
        try:
            for item in self.store.read_list(self.usage_file):
                result.append(TaskBudgetUsageRecord(**item))
        except (StorageError, ValidationError) as exc:
            raise StorageError("BACKGROUND_BUDGET_SCHEMA_INVALID: usage storage schema is invalid.") from exc
        return result

    def _read_routing_decisions(self) -> list[ModelRoutingDecisionRecord]:
        if not self.store.exists(self.routing_file):
            return []
        result: list[ModelRoutingDecisionRecord] = []
        try:
            for item in self.store.read_list(self.routing_file):
                result.append(ModelRoutingDecisionRecord(**item))
        except (StorageError, ValidationError) as exc:
            raise StorageError("BACKGROUND_BUDGET_SCHEMA_INVALID: routing storage schema is invalid.") from exc
        return result

    def _write_profiles(self, profiles: list[BackgroundBudgetProfile]) -> None:
        for profile in profiles:
            self._validate_profile(profile)
        self._guard_safe_payload(profiles)
        self.store.write(self.profiles_file, [model_to_dict(item) for item in profiles])

    def _write_policies(self, policies: list[TaskModelPolicy]) -> None:
        self._guard_safe_payload(policies)
        self.store.write(self.policies_file, [model_to_dict(item) for item in policies])

    def _write_usage(self, records: list[TaskBudgetUsageRecord]) -> None:
        self._guard_safe_payload(records)
        self.store.write(self.usage_file, [model_to_dict(item) for item in records[-MAX_USAGE_RECORDS:]])

    def _write_routing_decisions(self, records: list[ModelRoutingDecisionRecord]) -> None:
        self._guard_safe_payload(records)
        self.store.write(self.routing_file, [model_to_dict(item) for item in records[-MAX_ROUTING_DECISIONS:]])

    def _request_dict(self, request: BaseModel) -> dict[str, Any]:
        if hasattr(request, "model_dump"):
            return request.model_dump(exclude_none=True)
        return request.dict(exclude_none=True)

    def _guard_patch_payload(self, payload: dict[str, Any]) -> None:
        self._guard_safe_payload(payload)

    def _sanitize_payload(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            value = model_to_dict(value)
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                clean_key = _short_text(key, 120)
                if clean_key.lower() in UNSAFE_KEY_NAMES:
                    continue
                result[clean_key] = self._sanitize_payload(item)
            return result
        if isinstance(value, list):
            return [self._sanitize_payload(item) for item in value[:50]]
        if isinstance(value, str):
            return _short_text(value, MAX_SAFE_TEXT_LENGTH)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return _short_text(value, MAX_SAFE_TEXT_LENGTH)

    def _safety(self, payload: Any) -> dict[str, Any]:
        issues = self._scan_for_unsafe_payload(payload)
        return {
            "safe": not issues,
            "issues": issues,
            "no_prompt_or_raw_output": not any(issue.startswith("unsafe_key:") for issue in issues),
            "no_secret_value": not any(issue.startswith("secret_value:") for issue in issues),
        }

    def _guard_safe_payload(self, payload: Any) -> None:
        issues = self._scan_for_unsafe_payload(payload)
        if issues:
            raise StorageError(
                "BACKGROUND_BUDGET_UNSAFE_PAYLOAD_BLOCKED: background budget payload failed safety scan."
            )

    def _scan_for_unsafe_payload(self, payload: Any, path: str = "root") -> list[str]:
        issues: list[str] = []
        if isinstance(payload, BaseModel):
            payload = model_to_dict(payload)
        if isinstance(payload, dict):
            for key, value in payload.items():
                key_text = str(key or "")
                key_lower = key_text.lower()
                child_path = f"{path}.{key_text}"
                if key_lower in UNSAFE_KEY_NAMES:
                    issues.append(f"unsafe_key:{child_path}")
                issues.extend(self._scan_for_unsafe_payload(value, child_path))
        elif isinstance(payload, list):
            for index, value in enumerate(payload):
                issues.extend(self._scan_for_unsafe_payload(value, f"{path}[{index}]"))
        elif isinstance(payload, str):
            lower = payload.lower()
            for marker in UNSAFE_VALUE_MARKERS:
                if marker.lower() in lower:
                    issues.append(f"unsafe_value:{path}:{marker}")
            for pattern in SECRET_LIKE_PATTERNS:
                if pattern.search(payload):
                    issues.append(f"secret_value:{path}")
        return issues[:20]
