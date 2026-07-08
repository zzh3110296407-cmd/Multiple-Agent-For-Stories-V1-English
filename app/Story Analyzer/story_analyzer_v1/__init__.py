"""Compatibility package for backend/story_analyzer_v1."""

from pathlib import Path

_BACKEND_PACKAGE = Path(__file__).resolve().parent.parent / "backend" / "story_analyzer_v1"
__path__ = [str(_BACKEND_PACKAGE)]

__all__ = ["__version__"]
__version__ = "0.1.0"

