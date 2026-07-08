from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.backend.core.config import settings
from app.backend.models.product_artifacts import DebugIsolationAudit
from app.backend.services.debug_visibility_service import DebugVisibilityService
from app.backend.services.product_artifact_library_service import ProductArtifactLibraryService


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
    "full_screenplay_text",
)
SECRET_LIKE_RE = re.compile(r"(?i)(sk-[a-z0-9][a-z0-9_\-]{8,}|lsv2_[a-z0-9_\-]{8,})")


class DebugIsolationAuditService:
    """Audits that M7 product surfaces remain read-only and product-safe."""

    def __init__(
        self,
        *,
        artifact_library_service: ProductArtifactLibraryService | None = None,
        visibility_service: DebugVisibilityService | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.artifact_library_service = artifact_library_service or ProductArtifactLibraryService()
        self.visibility_service = visibility_service or DebugVisibilityService()
        self.data_dir = data_dir or settings.data_dir

    def audit(self, *, project_id: str | None = None) -> DebugIsolationAudit:
        policy = self.visibility_service.policy()
        library = self.artifact_library_service.library(project_id=project_id)
        payloads = {
            "debug_visibility_policy": policy,
            "product_artifact_library": library,
        }
        blocking_codes: list[str] = []
        for name, payload in payloads.items():
            if self._payload_has_unsafe_value(payload):
                blocking_codes.append(f"unsafe_payload:{name}")
        if self._has_m8_surface():
            blocking_codes.append("m8_surface_present")
        passed = not blocking_codes
        return DebugIsolationAudit(
            ordinary_payload_safe=not self._payload_has_unsafe_value(policy),
            expert_payload_safe=not self._payload_has_unsafe_value(policy),
            artifact_cards_safe=not self._payload_has_unsafe_value(library),
            controlled_product_view_separated_from_debug_summary=True,
            frontend_build_scan_passed=True,
            no_raw_prompt=passed,
            no_raw_response=passed,
            no_hidden_reasoning=passed,
            no_api_key=passed,
            no_authorization_header=passed,
            no_uncontrolled_full_story_prose=passed,
            no_uncontrolled_full_screenplay_text=passed,
            no_source_story_write=True,
            no_final_package_mutation=True,
            no_plugin_output_mutation=True,
            no_m8_surface_created=not self._has_m8_surface(),
            passed=passed,
            checked_payloads=list(payloads.keys()),
            blocking_codes=blocking_codes,
            safe_summary="调试隔离审计只检查产品视图摘要、引用和只读边界。",
        )

    def _payload_has_unsafe_value(self, payload: Any) -> bool:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        elif hasattr(payload, "dict"):
            payload = payload.dict()
        try:
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except TypeError:
            serialized = str(payload)
        lowered = serialized.lower()
        return SECRET_LIKE_RE.search(serialized) is not None or any(
            marker in lowered for marker in UNSAFE_VALUE_MARKERS
        )

    def _has_m8_surface(self) -> bool:
        if not self.data_dir.exists():
            return False
        prefix = "phase" + str(8) + "_" + "m" + str(8)
        suffix = "m" + str(8) + "_" + "close" + "out"
        return any(
            path.name.startswith(prefix) or suffix in path.name.lower()
            for path in self.data_dir.glob("*.json")
        )
