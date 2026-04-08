"""Gemini API integration for grounded web discovery.

This module isolates vendor-specific client setup, request/response handling,
and observability so the rest of the pipeline can treat Gemini as a structured
search provider instead of a raw SDK dependency. Keeping the integration thin
and centralized also makes future model or provider swaps less invasive.
"""

import asyncio
import logging
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import GEMINI_API_KEY
from app.core.logging_config import log_extra

logger = logging.getLogger(__name__)

_client: genai.Client | None = None
_GROUNDED_MODEL = "gemini-2.5-flash"
_FALLBACK_MODEL = "gemini-2.5-flash-lite"
_FALLBACK_MAX_RESULTS = 3
_FALLBACK_MAX_JOBS = 2
_FALLBACK_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "institutions": {
            "type": "array",
            "maxItems": _FALLBACK_MAX_RESULTS,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "careers_url": {"type": "string"},
                    "institution_type": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "jobs": {
                        "type": "array",
                        "maxItems": _FALLBACK_MAX_JOBS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "location": {"type": ["string", "null"]},
                                "experience_level": {"type": "string"},
                                "salary_range": {"type": ["string", "null"]},
                            },
                            "required": ["title", "url"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "careers_url", "jobs"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["institutions"],
    "additionalProperties": False,
}


def _new_client() -> genai.Client:
    """Create a new Gemini SDK client after validating credentials."""
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY environment variable is not set. "
            "Get a key from https://aistudio.google.com/apikey"
        )

    return genai.Client(api_key=GEMINI_API_KEY)


def _build_fallback_prompt(query: str, max_results: int = _FALLBACK_MAX_RESULTS) -> str:
    """Build a compact fallback prompt for structured, non-grounded discovery.

    Gemini's Google Search tool currently returns empty candidate content for
    some job-discovery prompts on the 2.5 Flash family. When that happens, we
    fall back to a smaller structured-output request and let the verification
    pipeline filter out any uncertain URLs before persistence.
    """
    return (
        "Return ONLY raw JSON that matches the provided schema. "
        f"Find up to {max_results} real institutions actively hiring for roles related to: {query}. "
        "Prefer official employer careers pages, not job aggregators. "
        f"For each institution include a direct careers_url and up to {_FALLBACK_MAX_JOBS} direct job posting URLs if you know them. "
        "Keep descriptions concise and only include data you are confident about. "
        "If a careers URL is uncertain, omit that institution instead of guessing."
    )


async def _structured_fallback_search(
    query: str,
    *,
    search_run_id: str | None = None,
    source_query: str | None = None,
) -> str:
    """Retry discovery without built-in tools when grounded output is empty."""
    # Use a fresh client for the fallback call. Reusing the same client
    # immediately after a grounded tool request has been observed to stall.
    client = _new_client()
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=_FALLBACK_MODEL,
        contents=_build_fallback_prompt(source_query or query),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=_FALLBACK_JSON_SCHEMA,
            temperature=0.1,
        ),
    )

    text = response.text or ""
    logger.info(
        "Gemini fallback response received: %s chars",
        len(text),
        extra=log_extra(
            search_run_id=search_run_id,
            query=source_query or query,
            response_chars=len(text),
            fallback_model=_FALLBACK_MODEL,
        ),
    )
    return text


def get_client() -> genai.Client:
    """Return the shared Gemini SDK client for this process.

    The backend reuses one lazily created client so request handlers do not pay
    repeated construction overhead and configuration stays consistent across
    health checks and real search runs.

    Returns:
        genai.Client: Configured Gemini client bound to the current API key.

    Raises:
        ValueError: If no API key is configured for Gemini access.
    """
    global _client

    if _client is None:
        _client = _new_client()

    return _client


def _extract_grounding_data(
    response: types.GenerateContentResponse,
) -> tuple[dict[str, list[dict[str, str | None]]] | None, list[str] | None]:
    """Extract the grounding subset the rest of the backend actually uses.

    Gemini responses contain a large amount of provider-specific metadata. This
    helper reduces that to citations and search queries so observability and
    verification code can benefit from grounding without depending on the full
    SDK response shape.

    Args:
        response: Raw SDK response from ``generate_content``.

    Returns:
        tuple[dict[str, list[dict[str, str | None]]] | None, list[str] | None]:
            Citation metadata and emitted search queries when grounding exists,
            otherwise ``(None, None)``.
    """
    if not response.candidates:
        return None, None

    candidate = response.candidates[0]
    grounding_metadata = candidate.grounding_metadata

    if grounding_metadata is None:
        return None, None

    chunks = []
    for chunk in grounding_metadata.grounding_chunks or []:
        web_chunk = getattr(chunk, "web", None)
        if web_chunk is None:
            continue

        chunks.append(
            {
                "uri": getattr(web_chunk, "uri", None),
                "title": getattr(web_chunk, "title", None),
            }
        )

    return {"chunks": chunks}, list(grounding_metadata.web_search_queries or [])


async def grounded_search(
    query: str,
    system_prompt: str,
    temperature: float = 0.1,
    *,
    search_run_id: str | None = None,
    source_query: str | None = None,
) -> dict[str, object]:
    """Execute one grounded Gemini search and normalize its result envelope.

    The orchestrator needs a stable contract regardless of whether Gemini
    succeeds, fails, or returns partial grounding metadata. Returning a small
    dict instead of the raw SDK object keeps later pipeline stages focused on
    parsing and verification rather than provider-specific branching.

    Args:
        query: User-facing search instruction sent as the content payload.
        system_prompt: System instruction that constrains response structure.
        temperature: Sampling temperature kept low to favor deterministic JSON.
        search_run_id: Optional search run identifier for structured logging.
        source_query: Optional original query for logs when ``query`` is the
            expanded user message rather than the raw user input.

    Returns:
        dict[str, object]: Result envelope containing ``text``,
        ``grounding_metadata``, ``search_queries``, and ``error`` keys.
    """
    start = time.perf_counter()
    query_preview = query if len(query) <= 80 else f"{query[:77]}..."

    try:
        client = get_client()
        logger.info(
            "Gemini grounded search started: %s",
            query_preview,
            extra=log_extra(
                search_run_id=search_run_id,
                query=source_query or query_preview,
            ),
        )

        grounding_metadata = None
        search_queries = None

        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=_GROUNDED_MODEL,
                contents=query,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=temperature,
                ),
            )
            text = response.text or ""
            grounding_metadata, search_queries = _extract_grounding_data(response)
        except (genai_errors.ClientError, genai_errors.ServerError) as exc:
            logger.warning(
                "Gemini grounded search failed at the API level; retrying with structured fallback",
                extra=log_extra(
                    search_run_id=search_run_id,
                    query=source_query or query_preview,
                    grounded_model=_GROUNDED_MODEL,
                    fallback_model=_FALLBACK_MODEL,
                    api_error_type=type(exc).__name__,
                ),
            )
            text = await _structured_fallback_search(
                query=query,
                search_run_id=search_run_id,
                source_query=source_query,
            )

        if not text.strip():
            logger.warning(
                "Gemini grounded search returned empty text; retrying with structured fallback",
                extra=log_extra(
                    search_run_id=search_run_id,
                    query=source_query or query_preview,
                    fallback_model=_FALLBACK_MODEL,
                    search_query_count=len(search_queries or []),
                ),
            )
            text = await _structured_fallback_search(
                query=query,
                search_run_id=search_run_id,
                source_query=source_query,
            )

        citation_count = len(grounding_metadata["chunks"]) if grounding_metadata else 0
        duration_ms = int((time.perf_counter() - start) * 1000)

        logger.info(
            "Gemini response received: %s chars, %s citations",
            len(text),
            citation_count,
            extra=log_extra(
                search_run_id=search_run_id,
                query=source_query or query_preview,
                duration_ms=duration_ms,
                response_chars=len(text),
                citation_count=citation_count,
                search_query_count=len(search_queries or []),
            ),
        )

        return {
            "text": text,
            "grounding_metadata": grounding_metadata,
            "search_queries": search_queries,
            "error": None,
        }
    except Exception as exc:
        error_msg = f"Gemini API error: {type(exc).__name__}: {exc}"
        logger.exception(
            "Gemini grounded search failed",
            extra=log_extra(
                search_run_id=search_run_id,
                query=source_query or query_preview,
                duration_ms=int((time.perf_counter() - start) * 1000),
            ),
        )
        return {
            "text": "",
            "grounding_metadata": None,
            "search_queries": None,
            "error": error_msg,
        }


async def check_gemini_health() -> bool:
    """Return whether Gemini is reachable with the current credentials.

    Fetching model metadata keeps the health check lightweight and avoids
    spending `generate_content` quota just to prove that credentials and API
    reachability are still valid. This is enough to distinguish
    configuration/connectivity failures from downstream parsing or verification
    problems without making the health endpoint itself contribute to quota
    exhaustion.

    Returns:
        bool: ``True`` when Gemini responds successfully to a model metadata
        request.
    """
    try:
        client = get_client()
        await asyncio.to_thread(
            client.models.get,
            model=_GROUNDED_MODEL,
        )
    except ValueError as exc:
        logger.warning("Gemini health check unavailable: %s", exc)
        return False
    except (genai_errors.ClientError, genai_errors.ServerError) as exc:
        logger.warning("Gemini health check failed: %s", exc)
        return False
    except Exception:
        logger.exception("Gemini health check failed unexpectedly")
        return False

    return True
