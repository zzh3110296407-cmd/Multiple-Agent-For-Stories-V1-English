"""Source abstraction utilities for generator-ready profiles."""

from .source_entity_inventory import build_source_entity_inventory, entity_placeholder_map
from .structure_profile_builder import build_structure_only_profile

__all__ = [
    "build_source_entity_inventory",
    "build_structure_only_profile",
    "entity_placeholder_map",
]
