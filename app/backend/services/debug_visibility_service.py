from __future__ import annotations

from app.backend.models.product_artifacts import DebugVisibilityPolicy


class DebugVisibilityService:
    """Read-only policy for separating ordinary product UI from expert diagnostics."""

    def policy(self) -> DebugVisibilityPolicy:
        return DebugVisibilityPolicy(
            ordinary_mode_debug_visible=False,
            ordinary_mode_raw_payload_visible=False,
            expert_mode_safe_diagnostics_visible=True,
            expert_mode_raw_payload_visible=False,
            debug_routes_mutable=False,
            display_preference_only=True,
            permission_authority=False,
            safe_summary="普通模式隐藏诊断入口，专家模式只展示安全诊断摘要。",
        )
