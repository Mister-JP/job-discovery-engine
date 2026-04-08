"""Helpers for turning Gemini grounding metadata into observability signals.

Grounding metadata is optional and vendor-specific, so the rest of the backend
should not have to understand the SDK's exact response structure. This module
converts that metadata into small, backend-friendly objects that can support
debugging, trust analysis, and future ranking decisions.
"""

from dataclasses import dataclass, field
import logging
from typing import Optional

from app.core.logging_config import log_extra
from app.core.url_utils import extract_root_domain

logger = logging.getLogger(__name__)


@dataclass
class GroundingChunk:
    """A single web page cited by Gemini."""

    uri: Optional[str] = None
    title: Optional[str] = None


@dataclass
class GroundingInfo:
    """Structured grounding metadata from a Gemini response."""

    chunks: list[GroundingChunk] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    has_grounding: bool = False

    @property
    def cited_domains(self) -> set[str]:
        """Return the set of institution domains cited by Gemini grounding.

        Domain-level matching is intentionally coarser than URL-level matching
        because Gemini may cite a page adjacent to the one it returned. That
        still provides useful evidence that the model actually searched the
        institution's site, which is enough for observability and lightweight
        trust signals.

        Returns:
            set[str]: Unique root domains extracted from citation URLs.
        """
        domains = set()
        for chunk in self.chunks:
            if not chunk.uri:
                continue

            try:
                domains.add(extract_root_domain(chunk.uri))
            except Exception:
                logger.debug(
                    "Failed to extract domain from grounding chunk", exc_info=True
                )

        return domains

    def to_dict(self) -> dict:
        """Serialize grounding info into plain Python structures for storage.

        ``SearchRun`` metadata needs a JSON-friendly representation so the API
        and logs can expose grounding details without depending on dataclass
        instances or repeated extraction logic.

        Returns:
            dict: JSON-serializable grounding summary with queries, domains, and
            citation chunks.
        """
        return {
            "has_grounding": self.has_grounding,
            "search_queries": self.search_queries,
            "cited_domains": sorted(self.cited_domains),
            "chunks": [
                {"uri": chunk.uri, "title": chunk.title} for chunk in self.chunks
            ],
        }


def extract_grounding_info(
    gemini_response: dict,
    *,
    search_run_id: str | None = None,
    query: str | None = None,
) -> GroundingInfo:
    """Extract structured grounding info from the Gemini client response.

    This function is deliberately tolerant of partial metadata because grounding
    is an observability enhancement, not a hard dependency for discovery. It
    captures what is present, logs what is missing, and leaves the core search
    flow free to continue.

    Args:
        gemini_response: The dict returned by gemini_client.grounded_search().
        search_run_id: Optional search run identifier for structured logging.
        query: Optional originating user query for log correlation.

    Returns:
        GroundingInfo: Parsed grounding metadata and derived domain signals.
    """
    info = GroundingInfo()

    if not gemini_response:
        logger.warning(
            "No Gemini response provided for grounding extraction",
            extra=log_extra(search_run_id=search_run_id, query=query),
        )
        return info

    search_queries = gemini_response.get("search_queries")
    if search_queries:
        info.search_queries = list(search_queries)
        info.has_grounding = True

    metadata = gemini_response.get("grounding_metadata") or {}
    for chunk_data in metadata.get("chunks") or []:
        if not isinstance(chunk_data, dict):
            logger.debug("Skipping non-dict grounding chunk: %r", chunk_data)
            continue

        info.chunks.append(
            GroundingChunk(
                uri=chunk_data.get("uri"),
                title=chunk_data.get("title"),
            )
        )

    if info.chunks:
        info.has_grounding = True

    if info.has_grounding:
        logger.info(
            "Grounding info: %s queries, %s citations, %s unique domains",
            len(info.search_queries),
            len(info.chunks),
            len(info.cited_domains),
            extra=log_extra(
                search_run_id=search_run_id,
                query=query,
                search_query_count=len(info.search_queries),
                citation_count=len(info.chunks),
                domain_count=len(info.cited_domains),
            ),
        )
    else:
        logger.warning(
            "No grounding metadata found in Gemini response",
            extra=log_extra(search_run_id=search_run_id, query=query),
        )

    return info


def cross_reference_candidates(
    grounding_info: GroundingInfo,
    candidate_urls: list[str],
    *,
    search_run_id: str | None = None,
    query: str | None = None,
) -> dict[str, bool]:
    """Check which candidate URLs appear to be supported by grounding data.

    Matching at the domain level is a deliberate compromise: it is strong enough
    to show that Gemini searched an institution's site, but loose enough to
    tolerate redirects and nearby citation pages. That means false positives are
    possible when a cited domain contains many unrelated pages, and false
    negatives remain possible when grounding is absent or incomplete.

    Args:
        grounding_info: The extracted grounding metadata.
        candidate_urls: List of candidate URLs to check.
        search_run_id: Optional search run identifier for structured logging.
        query: Optional originating user query for log correlation.

    Returns:
        dict[str, bool]: Mapping of candidate URL to whether its root domain was
        observed in the grounding citations.
    """
    cited_domains = grounding_info.cited_domains
    result = {}

    for url in candidate_urls:
        try:
            domain = extract_root_domain(url)
            result[url] = domain in cited_domains
        except Exception:
            result[url] = False

    grounded_count = sum(1 for is_grounded in result.values() if is_grounded)
    logger.info(
        "Cross-reference: %s/%s candidate URLs are grounded",
        grounded_count,
        len(candidate_urls),
        extra=log_extra(
            search_run_id=search_run_id,
            query=query,
            grounded_count=grounded_count,
            candidate_count=len(candidate_urls),
        ),
    )

    return result
