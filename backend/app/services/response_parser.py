"""Parse Gemini output into candidate models the backend can trust.

Even with JSON mode enabled, model responses still drift in formatting and key
names. This module absorbs that variability so the orchestrator sees either a
validated ``SearchResult`` or a high-signal parse error, rather than a mix of
half-parsed ad hoc cases throughout the codebase.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from app.core.logging_config import log_extra
from app.models.candidates import InstitutionCandidate, SearchResult

logger = logging.getLogger(__name__)

_CODE_BLOCK_PATTERNS = (
    r"```json\s*(.*?)\s*```",
    r"```\s*(.*?)\s*```",
)


def parse_gemini_response(
    raw_text: str,
    *,
    search_run_id: str | None = None,
    query: str | None = None,
) -> tuple[SearchResult | None, str | None]:
    """Parse Gemini's raw text response into validated candidate models.

    The parser intentionally tries a few narrow recovery strategies before
    giving up because model output is often "almost valid" in repeatable ways,
    such as fenced code blocks or trailing commentary. Centralizing that
    tolerance improves resilience without forcing later stages to accept
    ambiguous or partially validated data.

    Args:
        raw_text: Raw text returned by Gemini.
        search_run_id: Optional search run identifier for structured logging.
        query: Optional originating user query for log correlation.

    Returns:
        tuple[SearchResult | None, str | None]: Parsed search result on success
        or an error message explaining why parsing/validation failed.
    """
    if not raw_text or not raw_text.strip():
        return None, "Empty response from Gemini"

    parsed = _try_json_parse(raw_text)
    if parsed is not None:
        return _validate_parsed(
            parsed,
            search_run_id=search_run_id,
            query=query,
        )

    code_block = _extract_code_block(raw_text)
    if code_block:
        parsed = _try_json_parse(code_block)
        if parsed is not None:
            return _validate_parsed(
                parsed,
                search_run_id=search_run_id,
                query=query,
            )

    json_fragment = _find_json_start(raw_text)
    if json_fragment:
        parsed = _try_json_parse(json_fragment)
        if parsed is not None:
            return _validate_parsed(
                parsed,
                search_run_id=search_run_id,
                query=query,
            )

    preview = raw_text[:200].replace("\n", " ")
    error = f"Failed to parse JSON from Gemini response. Preview: {preview}"
    logger.error(
        error,
        extra=log_extra(search_run_id=search_run_id, query=query),
    )
    return None, error


def _try_json_parse(text: str) -> dict | list | None:
    """Attempt JSON parsing with a narrow fallback for trailing prose.

    Gemini often emits valid JSON followed by an explanatory sentence. Using
    ``raw_decode`` as a second pass lets the parser salvage that common case
    without opening the door to arbitrary "fix up" behavior that could mask
    real schema issues.

    Args:
        text: Candidate text that may begin with a JSON container.

    Returns:
        dict | list | None: Parsed JSON container when a safe parse succeeds.
    """
    if not isinstance(text, str):
        return None

    candidate = text.strip()
    if not candidate:
        return None

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    try:
        parsed, _ = json.JSONDecoder().raw_decode(candidate)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, (dict, list)) else None


def _extract_code_block(text: str) -> str | None:
    """Return JSON-like content from the first fenced code block, if present.

    This fallback exists because models frequently wrap otherwise valid JSON in
    markdown fences even when instructed not to. Restricting extraction to code
    fences keeps the recovery path predictable and easy to reason about.

    Args:
        text: Raw model output that may contain fenced JSON.

    Returns:
        str | None: Extracted code block content or ``None`` when absent.
    """
    for pattern in _CODE_BLOCK_PATTERNS:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _find_json_start(text: str) -> str | None:
    """Return the earliest plausible JSON payload embedded in free text.

    This is the loosest recovery strategy and is intentionally tried last. It
    helps when Gemini prefixes JSON with a short explanation, but it still
    refuses to invent closing braces or otherwise guess at malformed output.

    Args:
        text: Raw model output that may contain leading commentary.

    Returns:
        str | None: Substring starting at the first ``{`` or ``[`` marker.
    """
    positions = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not positions:
        return None
    return text[min(positions) :].strip()


def _validate_parsed(
    data: dict | list,
    *,
    search_run_id: str | None = None,
    query: str | None = None,
) -> tuple[SearchResult | None, str | None]:
    """Validate parsed JSON while tolerating a few common response shapes.

    The prompt asks for one exact schema, but the parser still accepts a bare
    institution list or a ``results`` key because those are low-risk structural
    deviations from otherwise useful output. Any broader coercion would hide
    prompt regressions, so this function intentionally keeps the adaptation set
    small and heavily logged.

    Args:
        data: Parsed JSON object or list from Gemini output.
        search_run_id: Optional search run identifier for structured logging.
        query: Optional originating user query for log correlation.

    Returns:
        tuple[SearchResult | None, str | None]: Validated search result on
        success or a validation error message on failure.
    """
    try:
        if isinstance(data, list):
            logger.info(
                "Gemini response used a bare list; wrapping in SearchResult",
                extra=log_extra(search_run_id=search_run_id, query=query),
            )
            result = SearchResult(
                institutions=[
                    InstitutionCandidate.model_validate(item) for item in data
                ]
            )
        elif "institutions" in data:
            result = SearchResult.model_validate(data)
        elif "results" in data:
            logger.info(
                "Gemini response used 'results' instead of 'institutions'; remapping",
                extra=log_extra(search_run_id=search_run_id, query=query),
            )
            result = SearchResult(
                institutions=[
                    InstitutionCandidate.model_validate(item)
                    for item in data["results"]
                ]
            )
        else:
            logger.info(
                "Gemini response looked like a single institution; wrapping",
                extra=log_extra(search_run_id=search_run_id, query=query),
            )
            result = SearchResult(
                institutions=[InstitutionCandidate.model_validate(data)]
            )
    except ValidationError as exc:
        error = f"Validation error: {exc}"
        logger.error(
            error,
            extra=log_extra(search_run_id=search_run_id, query=query),
        )
        return None, error
    except TypeError as exc:
        error = f"Validation error: {type(exc).__name__}: {exc}"
        logger.error(
            error,
            extra=log_extra(search_run_id=search_run_id, query=query),
        )
        return None, error

    logger.info(
        "Parsed %s institutions with %s total jobs",
        result.total_institutions,
        result.total_jobs,
        extra=log_extra(
            search_run_id=search_run_id,
            query=query,
            candidate_count=result.total_institutions,
            job_count=result.total_jobs,
        ),
    )
    return result, None
