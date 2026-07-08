import re
from dataclasses import dataclass
from typing import Any


MAX_SAFE_ERROR_LENGTH = 500

OPENAI_KEY_PATTERN = re.compile(r"\bs" + r"k-[A-Za-z0-9_\-]{8,}")
LANGSMITH_KEY_PATTERN = re.compile(r"\blsv2_pt[_A-Za-z0-9\-]{8,}")
BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]+", re.IGNORECASE)
AUTHORIZATION_PATTERN = re.compile(
    r"(Authorization\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SafeRuntimeError:
    stage: str
    error_type: str
    error_message_safe: str
    retryable: bool
    suggested_action: str
    user_visible_message: str


class RuntimeErrorSanitizer:
    def sanitize(
        self,
        error: BaseException | str,
        *,
        stage: str = "unknown",
        error_type: str | None = None,
    ) -> SafeRuntimeError:
        raw_text = self._safe_text(error)
        inferred_stage = stage
        inferred_type = error_type or self._infer_error_type(raw_text, error)
        if inferred_type == "missing_api_key":
            inferred_stage = "config_check"
        elif inferred_type == "json_parse_error":
            inferred_stage = "json_parse"
        elif inferred_type in {
            "provider_http_error",
            "provider_timeout",
            "provider_rate_limit",
            "provider_auth_error",
        }:
            inferred_stage = "adapter_request"

        message, retryable, action = self._message_for_type(inferred_type)
        return SafeRuntimeError(
            stage=inferred_stage,
            error_type=inferred_type,
            error_message_safe=message,
            retryable=retryable,
            suggested_action=action,
            user_visible_message=f"{message}{action}",
        )

    def redact_text(self, value: Any) -> str:
        text = str(value or "")
        text = AUTHORIZATION_PATTERN.sub(r"\1[redacted]", text)
        text = BEARER_PATTERN.sub("Bearer [redacted]", text)
        text = OPENAI_KEY_PATTERN.sub("[redacted-key]", text)
        text = LANGSMITH_KEY_PATTERN.sub("[redacted-key]", text)
        if len(text) > MAX_SAFE_ERROR_LENGTH:
            text = f"{text[:MAX_SAFE_ERROR_LENGTH]}..."
        return text

    def _safe_text(self, error: BaseException | str) -> str:
        parts: list[str] = []
        if isinstance(error, BaseException):
            current: BaseException | None = error
            depth = 0
            while current is not None and depth < 4:
                parts.append(f"{current.__class__.__name__}: {current}")
                current = current.__cause__ or current.__context__
                depth += 1
        else:
            parts.append(str(error))
        return self.redact_text(" | ".join(parts)).lower()

    def _infer_error_type(
        self,
        raw_text: str,
        error: BaseException | str,
    ) -> str:
        class_names = ""
        if isinstance(error, BaseException):
            current: BaseException | None = error
            names: list[str] = []
            while current is not None and len(names) < 4:
                names.append(current.__class__.__name__.lower())
                current = current.__cause__ or current.__context__
            class_names = " ".join(names)

        combined = f"{raw_text} {class_names}"
        if "json" in combined and ("parse" in combined or "decode" in combined):
            return "json_parse_error"
        if "api key" in combined or "api_key" in combined or "env variable is not set" in combined:
            return "missing_api_key"
        if "timeout" in combined or "timed out" in combined:
            return "provider_timeout"
        if "rate limit" in combined or "status=429" in combined or " 429" in combined:
            return "provider_rate_limit"
        if (
            "status=401" in combined
            or "status=403" in combined
            or " 401" in combined
            or " 403" in combined
            or "unauthorized" in combined
            or "authentication" in combined
        ):
            return "provider_auth_error"
        if (
            "http" in combined
            or "provider call failed" in combined
            or "urlerror" in combined
            or "httperror" in combined
        ):
            return "provider_http_error"
        return "unknown_model_error"

    def _message_for_type(self, error_type: str) -> tuple[str, bool, str]:
        if error_type == "missing_api_key":
            return (
                "模型 API Key 未配置。",
                False,
                "请在启动后端的 PowerShell 中设置对应环境变量后重启后端。",
            )
        if error_type == "provider_timeout":
            return (
                "模型服务响应超时。",
                True,
                "请稍后手动重试，或检查网络与模型服务状态。",
            )
        if error_type == "provider_rate_limit":
            return (
                "模型服务触发限流。",
                True,
                "请稍后手动重试，或降低短时间内的调用频率。",
            )
        if error_type == "provider_auth_error":
            return (
                "模型服务认证失败。",
                False,
                "请检查环境变量中的 API Key 是否有效，并避免把明文 key 写入项目文件。",
            )
        if error_type == "provider_http_error":
            return (
                "模型服务调用失败。",
                True,
                "请稍后手动重试，或检查模型 provider 配置。",
            )
        if error_type == "json_parse_error":
            return (
                "模型返回内容不是合法 JSON。",
                True,
                "请重试，或降低输出复杂度。",
            )
        if error_type == "schema_validation_error":
            return (
                "模型返回内容未通过结构校验。",
                True,
                "请重试，或收窄输入要求。",
            )
        return (
            "模型调用出现未知错误。",
            True,
            "请重试；如果持续失败，请检查模型配置和最近调用记录。",
        )
