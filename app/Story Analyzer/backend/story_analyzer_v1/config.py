from pathlib import Path


DEFAULT_ENCODING = "utf-8"
SOURCE_MANIFEST_FILENAME = "source_input_manifest.json"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
