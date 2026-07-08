"""Compatibility entrypoint for backend.book_analyzer_v2."""

if __name__ == "__main__":
    import runpy

    runpy.run_module("backend.book_analyzer_v2", run_name="__main__")
else:
    import sys
    from backend import book_analyzer_v2 as _impl

    sys.modules[__name__] = _impl

