from __future__ import annotations

from pathlib import Path

from ..models.plugin_protocol import PluginRegistryDetailResponse, PluginRegistryListResponse
from ..storage.json_store import JsonStore
from .plugin_manifest_service import PluginManifestService


class PluginRegistryService:
    def __init__(self, *, store: JsonStore | None = None, data_dir: Path | None = None) -> None:
        self.manifest_service = PluginManifestService(store=store, data_dir=data_dir)

    def list_plugins(self) -> PluginRegistryListResponse:
        return self.manifest_service.list_plugins()

    def get_plugin(self, plugin_id: str) -> PluginRegistryDetailResponse:
        return self.manifest_service.get_plugin(plugin_id)
