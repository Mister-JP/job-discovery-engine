"""Unit tests for the Gemini client wrapper."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import gemini_client


class RecordingModels:
    """Fake Gemini models API that records calls for assertions."""

    def __init__(self, response=None, error=None, responses=None):
        self.response = response
        self.error = error
        self.responses = list(responses) if responses is not None else None
        self.calls = []

    def _resolve_response(self):
        if self.responses is not None:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self.error is not None:
            raise self.error
        return self.response

    def generate_content(self, **kwargs):
        self.calls.append({"method": "generate_content", **kwargs})
        return self._resolve_response()

    def get(self, **kwargs):
        self.calls.append({"method": "get", **kwargs})
        return self._resolve_response()


class FakeClient:
    """Fake Gemini client with a configurable models surface."""

    def __init__(self, response=None, error=None, responses=None):
        self.models = RecordingModels(
            response=response,
            error=error,
            responses=responses,
        )


@pytest.fixture(autouse=True)
def reset_client_cache(monkeypatch):
    monkeypatch.setattr(gemini_client, "_client", None)


@pytest.mark.asyncio
async def test_grounded_search_returns_structured_result(monkeypatch):
    response = SimpleNamespace(
        text='[{"name":"OpenAI","careers_url":"https://openai.com/careers"}]',
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=[
                        SimpleNamespace(
                            web=SimpleNamespace(
                                uri="https://openai.com/careers",
                                title="OpenAI Careers",
                            )
                        ),
                        SimpleNamespace(web=None),
                    ],
                    web_search_queries=["AI researchers hiring right now"],
                )
            )
        ],
    )
    client = FakeClient(response=response)
    monkeypatch.setattr(gemini_client, "get_client", lambda: client)

    result = await gemini_client.grounded_search(
        query="What are 3 companies hiring AI researchers right now?",
        system_prompt="Return JSON only.",
        temperature=0.2,
    )

    assert result == {
        "text": '[{"name":"OpenAI","careers_url":"https://openai.com/careers"}]',
        "grounding_metadata": {
            "chunks": [
                {
                    "uri": "https://openai.com/careers",
                    "title": "OpenAI Careers",
                }
            ]
        },
        "search_queries": ["AI researchers hiring right now"],
        "error": None,
    }

    call = client.models.calls[0]
    assert call["model"] == gemini_client._GROUNDED_MODEL
    assert call["contents"] == "What are 3 companies hiring AI researchers right now?"
    assert call["config"].system_instruction == "Return JSON only."
    assert call["config"].response_mime_type is None
    assert call["config"].temperature == 0.2
    assert len(call["config"].tools) == 1
    assert call["config"].tools[0].google_search is not None


@pytest.mark.asyncio
async def test_grounded_search_falls_back_when_grounded_text_is_empty(monkeypatch):
    grounded_response = SimpleNamespace(
        text=None,
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=[],
                    web_search_queries=["climate tech nonprofits hiring engineers"],
                ),
                content=SimpleNamespace(parts=[]),
            )
        ],
    )
    fallback_response = SimpleNamespace(
        text='{"institutions":[]}',
        candidates=[],
    )
    grounded_client = FakeClient(response=grounded_response)
    fallback_client = FakeClient(response=fallback_response)
    monkeypatch.setattr(gemini_client, "get_client", lambda: grounded_client)
    monkeypatch.setattr(gemini_client, "_new_client", lambda: fallback_client)

    result = await gemini_client.grounded_search(
        query="Search the web for climate tech nonprofits hiring engineers",
        system_prompt="Return JSON only.",
        temperature=0.1,
        source_query="climate tech nonprofits hiring engineers",
    )

    assert result == {
        "text": '{"institutions":[]}',
        "grounding_metadata": {"chunks": []},
        "search_queries": ["climate tech nonprofits hiring engineers"],
        "error": None,
    }

    grounded_call = grounded_client.models.calls[0]
    fallback_call = fallback_client.models.calls[0]
    assert grounded_call["model"] == gemini_client._GROUNDED_MODEL
    assert len(grounded_call["config"].tools) == 1
    assert grounded_call["config"].response_mime_type is None

    assert fallback_call["model"] == gemini_client._FALLBACK_MODEL
    assert fallback_call["config"].response_mime_type == "application/json"
    assert (
        fallback_call["config"].response_json_schema
        == gemini_client._FALLBACK_JSON_SCHEMA
    )
    assert fallback_call["config"].tools is None
    assert "climate tech nonprofits hiring engineers" in fallback_call["contents"]


@pytest.mark.asyncio
async def test_grounded_search_catches_errors(monkeypatch):
    client = FakeClient(error=RuntimeError("boom"))
    monkeypatch.setattr(gemini_client, "get_client", lambda: client)

    result = await gemini_client.grounded_search(
        query="test query",
        system_prompt="Return JSON only.",
    )

    assert result["text"] == ""
    assert result["grounding_metadata"] is None
    assert result["search_queries"] is None
    assert result["error"] == "Gemini API error: RuntimeError: boom"


def test_get_client_requires_api_key(monkeypatch):
    monkeypatch.setattr(gemini_client, "GEMINI_API_KEY", "")

    with pytest.raises(
        ValueError, match="GEMINI_API_KEY environment variable is not set"
    ):
        gemini_client.get_client()


@pytest.mark.asyncio
async def test_check_gemini_health_returns_true_on_ok(monkeypatch):
    client = FakeClient(response=SimpleNamespace(name="models/gemini-2.5-flash"))
    monkeypatch.setattr(gemini_client, "get_client", lambda: client)

    assert await gemini_client.check_gemini_health() is True
    assert client.models.calls == [
        {
            "method": "get",
            "model": gemini_client._GROUNDED_MODEL,
        }
    ]


@pytest.mark.asyncio
async def test_check_gemini_health_returns_false_on_failure(monkeypatch):
    client = FakeClient(error=RuntimeError("unreachable"))
    monkeypatch.setattr(gemini_client, "get_client", lambda: client)

    assert await gemini_client.check_gemini_health() is False


@pytest.mark.asyncio
async def test_check_gemini_health_logs_expected_api_failures_without_stack_trace(
    monkeypatch,
):
    client = FakeClient(
        error=gemini_client.genai_errors.ClientError(
            429,
            {"error": {"status": "RESOURCE_EXHAUSTED"}},
            None,
        )
    )
    warning = Mock()
    exception = Mock()

    monkeypatch.setattr(gemini_client, "get_client", lambda: client)
    monkeypatch.setattr(gemini_client.logger, "warning", warning)
    monkeypatch.setattr(gemini_client.logger, "exception", exception)

    assert await gemini_client.check_gemini_health() is False
    warning.assert_called_once()
    exception.assert_not_called()
