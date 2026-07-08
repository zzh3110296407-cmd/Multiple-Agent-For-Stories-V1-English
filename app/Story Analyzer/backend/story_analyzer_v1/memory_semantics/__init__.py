"""Memory semantics layer for narrative threads and foreshadowing."""

from .foreshadowing_event_log import apply_foreshadowing_semantic_contract
from .promotion_gate import apply_promotion_gate

__all__ = ["apply_foreshadowing_semantic_contract", "apply_promotion_gate"]
