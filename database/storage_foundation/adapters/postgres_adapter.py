from dataclasses import dataclass
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, urlunsplit


class PostgresAdapterBlocked(RuntimeError):
    """Raised when psql cannot run because connection details are missing."""


@dataclass(frozen=True)
class PsqlConnectionConfig:
    database: str = "postgres"
    connection_uri: str = ""
    psql_executable: str = "psql"
    no_password_prompt: bool = True
    timeout_seconds: int = 30


@dataclass(frozen=True)
class PsqlExecutionResult:
    ok: bool
    command: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


def redact_connection_uri(connection_uri: str) -> str:
    """Redact the password segment of a PostgreSQL URI for logs/reports."""
    try:
        parsed = urlsplit(connection_uri)
    except ValueError:
        return connection_uri

    if not parsed.scheme or not parsed.netloc:
        return connection_uri

    at_index = parsed.netloc.rfind("@")
    if at_index < 0:
        return connection_uri

    userinfo = parsed.netloc[:at_index]
    hostinfo = parsed.netloc[at_index + 1 :]
    if ":" not in userinfo:
        return connection_uri

    username = userinfo.split(":", 1)[0]
    redacted_netloc = f"{username}:***@{hostinfo}"
    return urlunsplit(
        (
            parsed.scheme,
            redacted_netloc,
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


class PsqlPostgresAdapter:
    """Minimal psql-backed adapter skeleton for M0/M1 prototypes.

    This avoids adding a Python PostgreSQL dependency to the main backend.
    """

    def __init__(self, config: PsqlConnectionConfig | None = None) -> None:
        self.config = config or PsqlConnectionConfig()

    def command_for_sql(self, sql: str) -> list[str]:
        command = self._base_command(redact=True)
        command.extend(["-c", sql])
        return command

    def command_for_file(self, sql_file: Path) -> list[str]:
        command = self._base_command(redact=True)
        command.extend(["-f", str(sql_file)])
        return command

    def check_connection(self) -> PsqlExecutionResult:
        return self.run_sql("select current_database() as database_name, current_user as user_name;")

    def apply_sql_file(self, sql_file: Path) -> PsqlExecutionResult:
        path = sql_file.resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        return self._run(self._raw_command_for_file(path))

    def run_sql(self, sql: str) -> PsqlExecutionResult:
        if not sql.strip():
            raise ValueError("sql is required")
        return self._run(self._raw_command_for_sql(sql))

    def _raw_command_for_sql(self, sql: str) -> list[str]:
        command = self._base_command(redact=False)
        command.extend(["-c", sql])
        return command

    def _raw_command_for_file(self, sql_file: Path) -> list[str]:
        command = self._base_command(redact=False)
        command.extend(["-f", str(sql_file)])
        return command

    def _base_command(self, *, redact: bool) -> list[str]:
        command = [
            self.config.psql_executable,
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        if self.config.no_password_prompt:
            command.append("-w")
        if self.config.connection_uri:
            connection_uri = self.config.connection_uri
            if redact:
                connection_uri = redact_connection_uri(connection_uri)
            command.append(connection_uri)
        else:
            command.extend(["-d", self.config.database])
        return command

    def _run(self, command: list[str]) -> PsqlExecutionResult:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
            shell=False,
            check=False,
        )
        return PsqlExecutionResult(
            ok=completed.returncode == 0,
            command=tuple(redact_connection_uri(part) for part in command),
            returncode=completed.returncode,
            stdout=self._redact_text(completed.stdout),
            stderr=self._redact_text(completed.stderr),
        )

    def _redact_text(self, value: str) -> str:
        if not self.config.connection_uri:
            return value
        return value.replace(
            self.config.connection_uri,
            redact_connection_uri(self.config.connection_uri),
        )
