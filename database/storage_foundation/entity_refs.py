from dataclasses import dataclass, field
from typing import Any


def _required_text(value: str, field_name: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} is required")
    return clean


@dataclass(frozen=True)
class EntityRef:
    project_id: str
    entity_type: str
    business_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _required_text(self.project_id, "project_id"))
        object.__setattr__(self, "entity_type", _required_text(self.entity_type, "entity_type"))
        object.__setattr__(self, "business_id", _required_text(self.business_id, "business_id"))

    def key(self) -> str:
        return f"{self.project_id}:{self.entity_type}:{self.business_id}"

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "entity_type": self.entity_type,
            "business_id": self.business_id,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "EntityRef":
        return cls(
            project_id=str(payload.get("project_id") or ""),
            entity_type=str(payload.get("entity_type") or payload.get("type") or ""),
            business_id=str(payload.get("business_id") or payload.get("id") or ""),
        )


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    source_id: str = ""
    source_path: str = ""
    source_hash: str = ""
    locator: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class PackDependencyRef:
    entity_ref: EntityRef
    dependency_reason: str
    source_refs: tuple[SourceRef, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_ref": self.entity_ref.to_dict(),
            "dependency_reason": self.dependency_reason,
            "source_refs": [source_ref.to_dict() for source_ref in self.source_refs],
        }

