# Story Analyzer Code Layout

This directory contains the standalone analyzer runtime and the data needed by
the main application:

- `backend/`: analyzer runtime, CLI entrypoints, and the `story_analyzer_v1` package.
- `data/`: the framework vocabulary and the baseline recommended framework used
  by the main application.

Compatibility entrypoints remain at the root so existing commands keep working:

```powershell
python analyzer_web_ui.py --host 127.0.0.1 --port 8765
python book_analyzer_v2.py split "<story.txt>" "<output_dir>"
python -m story_analyzer_v1 --help
```

