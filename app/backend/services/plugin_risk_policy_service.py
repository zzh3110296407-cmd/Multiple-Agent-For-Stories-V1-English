from __future__ import annotations

from pathlib import Path

from ..models.plugin_protocol import PluginRiskDeclaration
from ..storage.json_store import JsonStore
from .plugin_manifest_service import PluginManifestService


class PluginRiskPolicyService:
    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.manifest_service = PluginManifestService(store=store, data_dir=data_dir)

    def get_risk_declaration(self, plugin_id: str) -> PluginRiskDeclaration:
        return self.manifest_service.get_risk_declaration(plugin_id)
