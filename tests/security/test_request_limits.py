import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.backend.api.analyze_stories import router as analyze_stories_router
from app.backend.core.config import settings
from app.backend.core.request_limits import read_limited_request_body


class FakeRequest:
    def __init__(self, chunks: list[bytes], content_length: str | None = None) -> None:
        self._chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = content_length

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


class RequestLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_body_within_limit(self) -> None:
        request = FakeRequest([b'{"ok":', b"true}"], content_length="11")

        body = await read_limited_request_body(request, max_bytes=32)

        self.assertEqual(body, b'{"ok":true}')

    async def test_rejects_declared_oversized_body_before_streaming(self) -> None:
        request = FakeRequest([b"small"], content_length="1024")

        with self.assertRaises(HTTPException) as context:
            await read_limited_request_body(request, max_bytes=16)

        self.assertEqual(context.exception.status_code, 413)

    async def test_rejects_chunked_body_when_accumulated_size_exceeds_limit(self) -> None:
        request = FakeRequest([b"12345678", b"9"])

        with self.assertRaises(HTTPException) as context:
            await read_limited_request_body(request, max_bytes=8)

        self.assertEqual(context.exception.status_code, 413)

    async def test_rejects_invalid_content_length(self) -> None:
        request = FakeRequest([b"{}"], content_length="-1")

        with self.assertRaises(HTTPException) as context:
            await read_limited_request_body(request, max_bytes=8)

        self.assertEqual(context.exception.status_code, 400)


class AnalyzeStoriesImportEndpointLimitTests(unittest.TestCase):
    def test_real_import_endpoint_returns_413_for_oversized_body(self) -> None:
        app = FastAPI()
        app.include_router(analyze_stories_router, prefix="/api/analyze-stories")
        original_limit = settings.max_analyze_stories_body_bytes
        settings.max_analyze_stories_body_bytes = 8
        try:
            response = TestClient(app).post(
                "/api/analyze-stories/imports",
                content=b"123456789",
                headers={"content-type": "application/json"},
            )
        finally:
            settings.max_analyze_stories_body_bytes = original_limit

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
