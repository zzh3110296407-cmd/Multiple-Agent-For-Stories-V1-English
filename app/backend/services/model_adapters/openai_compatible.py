import json
import http.client
import socket
import time
from typing import Any
from urllib import error, request as urllib_request

from app.backend.models.model_gateway import ModelGatewayRequest
from app.backend.models.model_provider import ModelProviderProfile
from app.backend.services.model_adapters.base import ModelAdapter, ModelAdapterError


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


class NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Prevent bearer credentials from being forwarded across redirects."""

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


class OpenAICompatibleModelAdapter(ModelAdapter):
    def __init__(
        self,
        provider: ModelProviderProfile,
        api_key: str | None,
        timeout_seconds: int = 180,
        max_attempts: int = 4,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self._opener = urllib_request.build_opener(NoRedirectHandler())

    def generate_text(self, request: ModelGatewayRequest) -> str:
        return self._call_chat_completions(request, response_format=None)

    def generate_json(self, request: ModelGatewayRequest) -> str:
        return self._call_chat_completions(
            request,
            response_format={"type": "json_object"},
        )

    def _call_chat_completions(
        self,
        request: ModelGatewayRequest,
        response_format: dict[str, str] | None,
    ) -> str:
        if not self.provider.base_url:
            raise ModelAdapterError("OpenAI-compatible provider base_url is missing.")

        endpoint = f"{self.provider.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": request.model_name,
            "messages": [model_to_dict(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        headers = {"Content-Type": "application/json"}
        if self.provider.auth_type in {"api_key", "bearer"}:
            if not self.api_key:
                raise ModelAdapterError("Provider API key is not available.")
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.provider.auth_type == "custom_header":
            raise ModelAdapterError("custom_header auth is not implemented in Milestone 3.5.")
        elif self.provider.auth_type != "none":
            raise ModelAdapterError("Provider auth_type is not supported.")

        http_request = urllib_request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        response_body = self._urlopen_with_retries(http_request)

        try:
            response_data = json.loads(response_body)
            content = response_data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelAdapterError("Provider response shape is not supported.") from exc

        if not isinstance(content, str):
            raise ModelAdapterError("Provider response content must be text.")
        return content

    def _urlopen_with_retries(self, http_request: urllib_request.Request) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self._opener.open(
                    http_request,
                    timeout=self.timeout_seconds,
                ) as response:
                    return response.read().decode("utf-8")
            except error.HTTPError as exc:
                if not self._retryable_http_status(exc.code) or attempt >= self.max_attempts:
                    raise ModelAdapterError(f"Provider HTTP error status={exc.code}.") from exc
                last_error = exc
            except (socket.timeout, TimeoutError) as exc:
                if attempt >= self.max_attempts:
                    raise ModelAdapterError("Provider call timed out.") from exc
                last_error = exc
            except error.URLError as exc:
                reason = str(exc.reason).lower()
                if self._retryable_url_error(reason):
                    if attempt >= self.max_attempts:
                        if "timed out" in reason or "timeout" in reason:
                            raise ModelAdapterError("Provider call timed out.") from exc
                        raise ModelAdapterError("Provider transient connection failed.") from exc
                    last_error = exc
                else:
                    raise ModelAdapterError("Provider call failed.") from exc
            except http.client.IncompleteRead as exc:
                if attempt >= self.max_attempts:
                    raise ModelAdapterError("Provider response ended before completion.") from exc
                last_error = exc
            except OSError as exc:
                if attempt >= self.max_attempts:
                    raise ModelAdapterError("Provider call failed.") from exc
                last_error = exc
            time.sleep(min(2 ** (attempt - 1), 8))
        raise ModelAdapterError("Provider call failed.") from last_error

    def _retryable_http_status(self, status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code < 600

    def _retryable_url_error(self, reason: str) -> bool:
        lowered = str(reason or "").lower()
        if "certificate" in lowered or "cert_verify" in lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "timed out",
                "timeout",
                "unexpected_eof",
                "eof occurred",
                "remote end closed",
                "connection reset",
                "connection aborted",
                "forcibly closed",
                "temporarily unavailable",
                "ssl",
            )
        )
