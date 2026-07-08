"""Compatibility entrypoint for backend.web_extractor."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.web_extractor", run_name="__main__")
else:
    import sys
    from backend import web_extractor as _impl

    sys.modules[__name__] = _impl

