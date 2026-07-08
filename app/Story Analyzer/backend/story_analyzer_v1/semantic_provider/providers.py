from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import json
import os
import urllib.error
import urllib.request

from ..analysis.semantic_normalizer import extract_raw_semantics_from_text
from ..models.semantic import RawSemanticChapterInput
from ..models.source import ChapterSource


class SemanticProviderError(ValueError):
    pass


@dataclass(frozen=True)
class SemanticChapterRequest:
    run_id: str
    work_title: str
    chapter: ChapterSource
    chapter_text: str


class SemanticProvider(Protocol):
    provider_type: str
    analyzer_id: str

    def analyze_chapter(self, request: SemanticChapterRequest) -> RawSemanticChapterInput:
        ...


class MockSemanticProvider:
    provider_type = "mock"
    analyzer_id = "mock_semantic_provider_v1"

    def analyze_chapter(self, request: SemanticChapterRequest) -> RawSemanticChapterInput:
        raw = extract_raw_semantics_from_text(request.chapter, request.chapter_text)
        return raw.model_copy(update={"analyzer_id": self.analyzer_id})


class HttpSemanticProvider:
    provider_type = "http"

    def __init__(
        self,
        *,
        endpoint: str,
        analyzer_id: str = "http_semantic_provider_v1",
        api_key_env: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not endpoint.strip():
            raise SemanticProviderError("http semantic provider requires endpoint")
        self.endpoint = endpoint
        self.analyzer_id = analyzer_id
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def analyze_chapter(self, request: SemanticChapterRequest) -> RawSemanticChapterInput:
        payload = {
            "contract_version": "story_analyzer.semantic_provider_request.v1",
            "run_id": request.run_id,
            "work_title": request.work_title,
            "chapter": request.chapter.model_dump(mode="json"),
            "chapter_text": request.chapter_text,
            "expected_response_schema": "story_analyzer.raw_semantic_chapter.v1",
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key_env:
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise SemanticProviderError(f"missing API key environment variable: {self.api_key_env}")
            headers["Authorization"] = f"Bearer {api_key}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_obj = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request_obj, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise SemanticProviderError(f"http semantic provider request failed: {exc}") from exc
        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise SemanticProviderError(f"http semantic provider returned invalid JSON: {exc}") from exc
        if "chapter" in data and isinstance(data["chapter"], dict):
            data = data["chapter"]
        if not isinstance(data, dict):
            raise SemanticProviderError("http semantic provider response must be an object")
        data.setdefault("schema_version", "story_analyzer.raw_semantic_chapter.v1")
        data.setdefault("chapter_id", request.chapter.chapter_id)
        data.setdefault("chapter_index", request.chapter.chapter_index)
        data.setdefault("analyzer_id", self.analyzer_id)
        return RawSemanticChapterInput.model_validate(data)


def build_semantic_provider(
    provider_name: str,
    *,
    endpoint: str | None = None,
    api_key_env: str | None = None,
    analyzer_id: str | None = None,
    timeout_seconds: float = 60.0,
) -> SemanticProvider:
    if provider_name == "mock":
        return MockSemanticProvider()
    if provider_name == "http":
        return HttpSemanticProvider(
            endpoint=endpoint or "",
            analyzer_id=analyzer_id or "http_semantic_provider_v1",
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
        )
    raise SemanticProviderError(f"unknown semantic provider: {provider_name}")
