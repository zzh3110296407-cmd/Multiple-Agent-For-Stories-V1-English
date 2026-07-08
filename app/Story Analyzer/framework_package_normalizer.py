"""Compatibility module for backend.framework_package_normalizer."""

import sys
from backend import framework_package_normalizer as _impl

sys.modules[__name__] = _impl

