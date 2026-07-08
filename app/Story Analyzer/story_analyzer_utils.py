"""Compatibility module for backend.story_analyzer_utils."""

import sys
from backend import story_analyzer_utils as _impl

sys.modules[__name__] = _impl

