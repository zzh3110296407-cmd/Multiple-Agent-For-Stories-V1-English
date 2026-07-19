from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import SplitResult, urlsplit, urlunsplit


DEEPSEEK_HOST = "api.deepseek.com"
PLACEHOLDER_MODEL_HOSTS = {"your-openai-compatible-endpoint"}
MODEL_ENDPOINT_ALLOWLIST_ENV = "MULTIPLE_AGENT_STORIES_MODEL_ENDPOINT_ALLOWLIST"
MODEL_KEY_ENV_ALLOWLIST_ENV = "MULTIPLE_AGENT_STORIES_MODEL_KEY_ENV_ALLOWLIST"
ALLOWED_PROVIDER_KEY_ENVS = {
    "deepseek": {"DEEPSEEK_API_KEY"},
    "qwen": {"QWEN_API_KEY", "DASHSCOPE_API_KEY"},
}
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ModelEndpointPolicyError(ValueError):
    """Raised when a provider could send credentials to an untrusted endpoint."""


def validate_model_endpoint_policy(
    *,
    provider_type: str,
    base_url: str,
    api_key_ref: str,
) -> str:
    provider = str(provider_type or "").strip().lower()
    if provider == "local":
        if str(base_url or "").strip() or str(api_key_ref or "").strip():
            raise ModelEndpointPolicyError(
                "Local providers must not configure a remote endpoint or API key."
            )
        return ""
    if provider not in ALLOWED_PROVIDER_KEY_ENVS:
        raise ModelEndpointPolicyError(
            f"Remote provider type {provider!r} is not enabled by the endpoint policy."
        )

    validate_model_key_ref(
        provider_type=provider,
        api_key_ref=api_key_ref,
    )

    parts = _validated_https_url(base_url)
    endpoint_authority = _endpoint_authority(parts)
    if endpoint_authority not in _allowed_endpoint_authorities(provider):
        raise ModelEndpointPolicyError(
            "The provider endpoint is not allowed by server configuration."
        )

    normalized_netloc = endpoint_authority
    normalized = SplitResult(
        scheme="https",
        netloc=normalized_netloc,
        path=parts.path.rstrip("/"),
        query="",
        fragment="",
    )
    return urlunsplit(normalized).rstrip("/")


def validate_model_key_ref(*, provider_type: str, api_key_ref: str) -> str:
    provider = str(provider_type or "").strip().lower()
    if provider not in ALLOWED_PROVIDER_KEY_ENVS:
        raise ModelEndpointPolicyError(
            f"Remote provider type {provider!r} is not enabled by the key policy."
        )
    env_name = _api_key_env_name(api_key_ref)
    allowed_key_envs = set(ALLOWED_PROVIDER_KEY_ENVS[provider])
    allowed_key_envs.update(_configured_key_env_allowlist())
    if env_name not in allowed_key_envs:
        raise ModelEndpointPolicyError(
            "The provider API key reference is not allowed by server configuration."
        )
    return env_name


def _api_key_env_name(api_key_ref: str) -> str:
    clean_ref = str(api_key_ref or "").strip()
    if not clean_ref.startswith("env:"):
        raise ModelEndpointPolicyError(
            "Remote provider API keys must use an env: reference."
        )
    env_name = clean_ref.removeprefix("env:").strip()
    if not ENV_NAME_PATTERN.fullmatch(env_name):
        raise ModelEndpointPolicyError("The provider API key environment name is invalid.")
    return env_name


def _validated_https_url(base_url: str) -> SplitResult:
    clean_url = str(base_url or "").strip()
    if not clean_url:
        raise ModelEndpointPolicyError("The provider endpoint is required.")
    try:
        parts = urlsplit(clean_url)
        _ = parts.port
    except ValueError as exc:
        raise ModelEndpointPolicyError("The provider endpoint URL is invalid.") from exc
    if parts.scheme.lower() != "https":
        raise ModelEndpointPolicyError("Remote provider endpoints must use HTTPS.")
    if not parts.hostname:
        raise ModelEndpointPolicyError("The provider endpoint host is required.")
    if parts.username or parts.password:
        raise ModelEndpointPolicyError("Provider endpoint user info is not allowed.")
    if parts.query or parts.fragment:
        raise ModelEndpointPolicyError(
            "Provider endpoint query strings and fragments are not allowed."
        )

    host = parts.hostname.lower().rstrip(".")
    if host in PLACEHOLDER_MODEL_HOSTS:
        raise ModelEndpointPolicyError(
            "Replace the placeholder provider endpoint before enabling a real model."
        )
    if host == "localhost" or host.endswith(".localhost"):
        raise ModelEndpointPolicyError("Loopback model endpoints are not allowed.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ModelEndpointPolicyError(
            "Private, loopback, link-local, or reserved model IPs are not allowed."
        )
    return parts


def _endpoint_authority(parts: SplitResult) -> str:
    host = str(parts.hostname or "").lower().rstrip(".")
    port = parts.port
    return f"{host}:{port}" if port is not None and port != 443 else host


def _allowed_endpoint_authorities(provider: str) -> set[str]:
    allowed = {DEEPSEEK_HOST} if provider == "deepseek" else set()
    qwen_base_url = os.environ.get("QWEN_BASE_URL", "").strip()
    if provider == "qwen" and qwen_base_url:
        allowed.add(_allowlist_entry_authority(qwen_base_url))

    for entry in os.environ.get(MODEL_ENDPOINT_ALLOWLIST_ENV, "").split(","):
        clean_entry = entry.strip()
        if clean_entry:
            allowed.add(_allowlist_entry_authority(clean_entry))
    return {entry for entry in allowed if entry}


def _allowlist_entry_authority(entry: str) -> str:
    candidate = entry if "://" in entry else f"https://{entry}"
    parts = _validated_https_url(candidate)
    return _endpoint_authority(parts)


def _configured_key_env_allowlist() -> set[str]:
    configured: set[str] = set()
    for entry in os.environ.get(MODEL_KEY_ENV_ALLOWLIST_ENV, "").split(","):
        env_name = entry.strip()
        if env_name and ENV_NAME_PATTERN.fullmatch(env_name):
            configured.add(env_name)
    return configured
