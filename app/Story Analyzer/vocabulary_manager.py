"""Compatibility entrypoint for backend.vocabulary_manager."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.vocabulary_manager", run_name="__main__")
else:
    import sys
    from backend import vocabulary_manager as _impl

    sys.modules[__name__] = _impl

