import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


STORAGE_MODE_JSON_PRIMARY = "json_primary"
STORAGE_MODE_POSTGRES_SHADOW = "postgres_shadow"
STORAGE_MODE_POSTGRES_PRIMARY = "postgres_primary"
STORAGE_MODE_JSON_EXPORT_ONLY = "json_export_only"

SUPPORTED_STORAGE_MODES = {
    STORAGE_MODE_JSON_PRIMARY,
    STORAGE_MODE_POSTGRES_SHADOW,
    STORAGE_MODE_POSTGRES_PRIMARY,
    STORAGE_MODE_JSON_EXPORT_ONLY,
}


class StorageConfigurationError(RuntimeError):
    """Raised when the configured runtime storage mode is unsafe to start."""


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


def _cors_origins_from_env(default: list[str]) -> list[str]:
    raw = os.environ.get("MULTIPLE_AGENT_STORIES_CORS_ORIGINS", "").strip()
    if not raw:
        return default
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or default


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _paths_from_semicolon_env(name: str, default: tuple[Path, ...]) -> tuple[Path, ...]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return tuple(path.expanduser().resolve() for path in default)
    paths = tuple(
        Path(item.strip()).expanduser().resolve()
        for item in raw.split(";")
        if item.strip()
    )
    return paths or tuple(path.expanduser().resolve() for path in default)


def _storage_mode_from_env(default: str = STORAGE_MODE_JSON_PRIMARY) -> tuple[str, str, str]:
    raw = os.environ.get("MULTIPLE_AGENT_STORIES_STORAGE_MODE", "").strip().lower()
    if not raw:
        return default, "", ""
    if raw not in SUPPORTED_STORAGE_MODES:
        return (
            default,
            raw,
            f"Unsupported storage mode {raw!r}; falling back to {default}.",
        )
    return raw, raw, ""


def redact_database_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return "[redacted-database-url]"
    if not parts.scheme or not parts.netloc:
        return "[redacted-database-url]"

    host = parts.hostname or ""
    if not host:
        return "[redacted-database-url]"

    user = parts.username or ""
    userinfo = f"{user}:***@" if user else "***@"
    port = f":{parts.port}" if parts.port is not None else ""
    safe_netloc = f"{userinfo}{host}{port}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, "", ""))


class Settings:
    app_root: Path = Path(__file__).resolve().parents[2]
    data_dir: Path = _path_from_env(
        "MULTIPLE_AGENT_STORIES_DATA_DIR",
        app_root / "data" / "local_project",
    )
    project_file: Path = data_dir / "project.json"
    max_analyze_stories_body_bytes: int = _positive_int_from_env(
        "MULTIPLE_AGENT_STORIES_MAX_ANALYZE_STORIES_BODY_BYTES",
        16 * 1024 * 1024,
    )
    analyzer_output_roots: tuple[Path, ...] = _paths_from_semicolon_env(
        "MULTIPLE_AGENT_STORIES_ANALYZER_OUTPUT_ROOTS",
        (
            data_dir / "analyzer_outputs",
            app_root / "Story Analyzer" / "data" / "handoff_exports",
        ),
    )
    cors_origins: list[str] = _cors_origins_from_env(
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    storage_mode: str
    storage_mode_raw: str
    storage_mode_warning: str
    storage_mode, storage_mode_raw, storage_mode_warning = _storage_mode_from_env()
    database_url: str = os.environ.get("MULTIPLE_AGENT_STORIES_DATABASE_URL", "").strip()
    redacted_database_url: str = redact_database_url(database_url)

    @property
    def database_url_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def postgres_primary_enabled(self) -> bool:
        return self.storage_mode == STORAGE_MODE_POSTGRES_PRIMARY

    def validate_storage_runtime(self) -> None:
        if self.storage_mode == STORAGE_MODE_POSTGRES_PRIMARY and not self.database_url:
            raise StorageConfigurationError(
                "postgres_primary storage mode requires "
                "MULTIPLE_AGENT_STORIES_DATABASE_URL; no password or connection string "
                "was logged."
            )


settings = Settings()
