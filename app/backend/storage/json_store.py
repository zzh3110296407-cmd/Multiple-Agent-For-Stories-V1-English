import json
import os
from pathlib import Path
import threading
import time
from typing import Any


class StorageError(RuntimeError):
    """Raised when local JSON storage cannot be read or written."""


class JsonStore:
    _READ_RETRY_ATTEMPTS = 5
    _READ_RETRY_SECONDS = 0.02
    _WRITE_REPLACE_ATTEMPTS = 5
    _WRITE_REPLACE_SECONDS = 0.02
    _LOCKS_GUARD = threading.Lock()
    _PATH_LOCKS: dict[str, threading.RLock] = {}

    def __init__(self, *, force_json_primary: bool = False) -> None:
        self._delegate: Any | None = None
        if force_json_primary:
            return

        from app.backend.core.config import settings

        if not settings.postgres_primary_enabled:
            return

        settings.validate_storage_runtime()
        from app.backend.storage.postgres_json_store import PostgresJsonStore

        self._delegate = PostgresJsonStore(
            database_url=settings.database_url,
            data_dir=settings.data_dir,
        )

    @classmethod
    def _path_lock(cls, path: Path) -> threading.RLock:
        key = str(path.resolve(strict=False))
        with cls._LOCKS_GUARD:
            lock = cls._PATH_LOCKS.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._PATH_LOCKS[key] = lock
            return lock

    def exists(self, path: Path) -> bool:
        if self._delegate is not None:
            return bool(self._delegate.exists(path))
        return path.exists()

    def read_any(self, path: Path) -> Any:
        if self._delegate is not None:
            return self._delegate.read_any(path)
        lock = self._path_lock(path)
        last_decode_error: json.JSONDecodeError | None = None
        last_os_error: OSError | None = None
        for attempt in range(self._READ_RETRY_ATTEMPTS):
            try:
                with lock:
                    with path.open("r", encoding="utf-8") as file:
                        data = json.load(file)
                return data
            except FileNotFoundError as exc:
                raise StorageError(f"JSON file does not exist: {path}") from exc
            except json.JSONDecodeError as exc:
                last_decode_error = exc
            except OSError as exc:
                last_os_error = exc
            if attempt < self._READ_RETRY_ATTEMPTS - 1:
                time.sleep(self._READ_RETRY_SECONDS)

        if last_decode_error is not None:
            raise StorageError(f"JSON file is invalid: {path}") from last_decode_error
        if last_os_error is not None:
            raise StorageError(f"Cannot read JSON file: {path}") from last_os_error
        raise StorageError(f"Cannot read JSON file: {path}")

    def read(self, path: Path) -> dict[str, Any]:
        data = self.read_any(path)
        if not isinstance(data, dict):
            raise StorageError(f"JSON root must be an object: {path}")
        return data

    def read_list(self, path: Path) -> list[Any]:
        data = self.read_any(path)
        if not isinstance(data, list):
            raise StorageError(f"JSON root must be a list: {path}")
        return data

    def write(self, path: Path, data: Any) -> None:
        if self._delegate is not None:
            self._delegate.write(path, data)
            return
        lock = self._path_lock(path)
        tmp_path: Path | None = None
        with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = path.with_name(
                    f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
                )
                with tmp_path.open("w", encoding="utf-8") as file:
                    json.dump(data, file, ensure_ascii=False, indent=2)
                    file.write("\n")
                    file.flush()
                    os.fsync(file.fileno())
                for attempt in range(self._WRITE_REPLACE_ATTEMPTS):
                    try:
                        os.replace(tmp_path, path)
                        break
                    except PermissionError:
                        if attempt >= self._WRITE_REPLACE_ATTEMPTS - 1:
                            raise
                        time.sleep(self._WRITE_REPLACE_SECONDS)
            except OSError as exc:
                raise StorageError(f"Cannot write JSON file: {path}") from exc
            finally:
                if tmp_path is not None and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

    def write_if_missing(self, path: Path, data: Any) -> bool:
        if self._delegate is not None:
            return bool(self._delegate.write_if_missing(path, data))
        if path.exists():
            return False

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
        except FileExistsError:
            return False
        except OSError as exc:
            raise StorageError(f"Cannot write JSON file: {path}") from exc
        return True
