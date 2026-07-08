"""Compatibility entrypoint for backend.analyzer_web_ui."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.analyzer_web_ui", run_name="__main__")
else:
    import sys
    from backend import analyzer_web_ui as _impl

    sys.modules[__name__] = _impl

