"""Compatibility entrypoint for backend.handoff_exporter."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.handoff_exporter", run_name="__main__")
else:
    import sys
    from backend import handoff_exporter as _impl

    sys.modules[__name__] = _impl

