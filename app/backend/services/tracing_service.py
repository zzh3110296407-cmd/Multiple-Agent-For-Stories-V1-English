import os
from functools import wraps
from typing import Any, Callable, TypeVar

from app.backend.models.tracing import TracingStatus


DEFAULT_LANGSMITH_PROJECT = "multiple-agent-stories-phase8-5"
LEGACY_LANGSMITH_PROJECTS = {"multiple-agent-stories-phase2"}
TRACING_PHASE = "phase8_5"
F = TypeVar("F", bound=Callable[..., Any])


def _env_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class TracingService:
    """Small LangSmith boundary that stays no-op when tracing is unavailable."""

    def __init__(self) -> None:
        self.project = self._resolve_project(os.environ.get("LANGSMITH_PROJECT"))
        self.endpoint = os.environ.get("LANGSMITH_ENDPOINT") or ""

    def get_status(self) -> TracingStatus:
        requested = _env_true(os.environ.get("LANGSMITH_TRACING"))
        api_key_configured = bool(os.environ.get("LANGSMITH_API_KEY"))
        package_available = self._package_available()
        issues: list[str] = []
        if requested and not api_key_configured:
            issues.append("LANGSMITH_API_KEY is not configured.")
        if requested and api_key_configured and not package_available:
            issues.append("langsmith package is not installed.")
        return TracingStatus(
            enabled=requested and api_key_configured and package_available,
            project=self.project,
            api_key_configured=api_key_configured,
            package_available=package_available,
            requested=requested,
            endpoint=self.endpoint,
            issues=issues,
        )

    def run_operation(
        self,
        name: str,
        call: Callable[[], Any],
        *,
        run_type: str = "chain",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        inputs: Any = None,
    ) -> Any:
        status = self.get_status()
        if not status.enabled:
            return call()

        try:
            from langsmith import traceable
        except ImportError:
            return call()

        executed = False
        call_succeeded = False
        call_error: Exception | None = None
        call_result: Any = None

        def invoke(payload: Any = None) -> Any:
            nonlocal call_error, call_result, call_succeeded, executed
            executed = True
            try:
                call_result = call()
            except Exception as exc:
                call_error = exc
                raise
            call_succeeded = True
            return call_result

        trace_metadata = {
            "phase": TRACING_PHASE,
            **(metadata or {}),
        }
        trace_tags = [TRACING_PHASE, *(tags or [])]

        try:
            decorated = traceable(
                name=name,
                run_type=run_type,
                metadata=trace_metadata,
                tags=trace_tags,
                project_name=status.project,
            )(invoke)
        except TypeError:
            try:
                decorated = traceable(
                    name=name,
                    run_type=run_type,
                    metadata=trace_metadata,
                    tags=trace_tags,
                )(invoke)
            except Exception:
                return call()
        except Exception:
            return call()

        try:
            return decorated(inputs)
        except Exception:
            if call_error is not None:
                raise call_error
            if executed and call_succeeded:
                return call_result
            return call()

    def _package_available(self) -> bool:
        try:
            import langsmith  # noqa: F401
        except ImportError:
            return False
        return True

    def _resolve_project(self, configured_project: str | None) -> str:
        project = (configured_project or "").strip()
        if not project or project in LEGACY_LANGSMITH_PROJECTS:
            return DEFAULT_LANGSMITH_PROJECT
        return project


def traceable_operation(
    name: str,
    *,
    run_type: str = "chain",
    tags: list[str] | None = None,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            service_name = args[0].__class__.__name__ if args else ""
            metadata = {
                "service": service_name,
                "operation": name,
            }
            inputs = {
                "args_count": max(len(args) - 1, 0),
                "kwargs_keys": sorted(kwargs.keys()),
            }
            return TracingService().run_operation(
                name,
                lambda: func(*args, **kwargs),
                run_type=run_type,
                metadata=metadata,
                tags=tags or [service_name, name],
                inputs=inputs,
            )

        return wrapper  # type: ignore[return-value]

    return decorator
