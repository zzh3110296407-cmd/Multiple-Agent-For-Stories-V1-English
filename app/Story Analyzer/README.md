# Story Analyzer Code Layout

This directory is organized to match the ProjectCodes packaging shape:

- `backend/`: analyzer runtime, CLI entrypoints, tests, tools, and the `story_analyzer_v1` package.
- `data/`: local analyzer data, vocabulary files, sample handoff package data, and logs.
- `docs/`: historical design notes, implementation guides, and archived README content.
- `frontend/`: reserved frontend workspace. The current UI is still embedded in `backend/analyzer_web_ui.py`.

Compatibility entrypoints remain at the root so existing commands keep working:

```powershell
python analyzer_web_ui.py --host 127.0.0.1 --port 8765
python book_analyzer_v2.py split "<story.txt>" "<output_dir>"
python -m story_analyzer_v1 --help
python -m unittest discover backend/tests
```

For new ProjectCodes integration work, treat `backend/`, `data/`, `docs/`, and `frontend/` as the canonical folders.

