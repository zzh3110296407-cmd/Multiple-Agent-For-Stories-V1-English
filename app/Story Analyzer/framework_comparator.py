"""Compatibility entrypoint for backend.framework_comparator."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.framework_comparator", run_name="__main__")
else:
    import sys
    from backend import framework_comparator as _impl

    sys.modules[__name__] = _impl

