import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.backend.core.model_endpoint_policy import (
    ModelEndpointPolicyError,
    validate_model_endpoint_policy,
    validate_model_key_ref,
)
from app.backend.services.model_settings_service import ModelSettingsService


class ModelEndpointPolicyTests(unittest.TestCase):
    def test_accepts_qwen_endpoint_and_key_declared_by_server_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QWEN_BASE_URL": "https://models.example.com/v1",
                "QWEN_API_KEY": "test-only",
            },
            clear=False,
        ):
            normalized = validate_model_endpoint_policy(
                provider_type="qwen",
                base_url="https://models.example.com/v1/",
                api_key_ref="env:QWEN_API_KEY",
            )

        self.assertEqual(normalized, "https://models.example.com/v1")

    def test_rejects_arbitrary_model_host(self) -> None:
        with patch.dict(
            os.environ,
            {"QWEN_BASE_URL": "https://models.example.com/v1"},
            clear=False,
        ):
            with self.assertRaises(ModelEndpointPolicyError):
                validate_model_endpoint_policy(
                    provider_type="qwen",
                    base_url="https://attacker.example/v1",
                    api_key_ref="env:QWEN_API_KEY",
                )

    def test_rejects_arbitrary_environment_key_reference(self) -> None:
        with patch.dict(
            os.environ,
            {"QWEN_BASE_URL": "https://models.example.com/v1"},
            clear=False,
        ):
            with self.assertRaises(ModelEndpointPolicyError):
                validate_model_endpoint_policy(
                    provider_type="qwen",
                    base_url="https://models.example.com/v1",
                    api_key_ref="env:MULTIPLE_AGENT_STORIES_DATABASE_URL",
                )
            with self.assertRaises(ModelEndpointPolicyError):
                validate_model_key_ref(
                    provider_type="qwen",
                    api_key_ref="env:MULTIPLE_AGENT_STORIES_DATABASE_URL",
                )

    def test_rejects_non_https_and_private_ip_endpoints(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MULTIPLE_AGENT_STORIES_MODEL_ENDPOINT_ALLOWLIST": (
                    "internal.example,127.0.0.1"
                )
            },
            clear=False,
        ):
            for endpoint in (
                "http://internal.example/v1",
                "https://127.0.0.1/v1",
            ):
                with self.subTest(endpoint=endpoint):
                    with self.assertRaises(ModelEndpointPolicyError):
                        validate_model_endpoint_policy(
                            provider_type="qwen",
                            base_url=endpoint,
                            api_key_ref="env:QWEN_API_KEY",
                        )

    def test_rejects_documentation_placeholder_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "QWEN_BASE_URL": (
                    "https://your-openai-compatible-endpoint/v1"
                )
            },
            clear=False,
        ):
            with self.assertRaises(ModelEndpointPolicyError):
                validate_model_endpoint_policy(
                    provider_type="qwen",
                    base_url="https://your-openai-compatible-endpoint/v1",
                    api_key_ref="env:QWEN_API_KEY",
                )

    def test_accepts_deepseek_fixed_endpoint_and_key(self) -> None:
        normalized = validate_model_endpoint_policy(
            provider_type="deepseek",
            base_url="https://api.deepseek.com",
            api_key_ref="env:DEEPSEEK_API_KEY",
        )

        self.assertEqual(normalized, "https://api.deepseek.com")

    def test_settings_status_does_not_probe_arbitrary_environment_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"MULTIPLE_AGENT_STORIES_DATABASE_URL": "test-only"},
            clear=False,
        ):
            service = ModelSettingsService(data_dir=Path(temp_dir))

            configured = service._api_key_configured(
                "qwen",
                "env:MULTIPLE_AGENT_STORIES_DATABASE_URL",
            )

        self.assertFalse(configured)


if __name__ == "__main__":
    unittest.main()
