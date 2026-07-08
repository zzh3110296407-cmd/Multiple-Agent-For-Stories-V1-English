"""Compatibility entrypoint for backend.framework_synthesizer."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.framework_synthesizer", run_name="__main__")
else:
    import sys
    from backend import framework_synthesizer as _impl

    sys.modules[__name__] = _impl

