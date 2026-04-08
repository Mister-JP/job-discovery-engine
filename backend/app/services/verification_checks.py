"""Deterministic verification checks used by the candidate pipeline.

These checks form a cost-aware trust ladder: cheap structural filters run first,
and more expensive network/content checks run only after the candidate has
survived earlier gates. Each check returns a boolean plus a human-readable
detail string so the pipeline can stop early without losing the reasoning needed
for evidence records and debugging.
"""

from __future__ import annotations

import asyncio
import logging
import re
import socket
from urllib.parse import urlparse

import httpx

from app.core.aggregator_domains import AGGREGATOR_DOMAINS
from app.core.config import VERIFICATION_TIMEOUT_SECONDS
from app.core.url_utils import extract_root_domain, normalize_url

logger = logging.getLogger(__name__)

_HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_AGGREGATOR_DOMAIN_SET = frozenset(AGGREGATOR_DOMAINS)
_PRIMARY_SOURCE_HOST_ALLOWLIST = frozenset({"careers.google.com"})

JOB_SIGNALS = [
    "apply now",
    "apply for this",
    "submit application",
    "apply online",
    "job description",
    "job details",
    "job posting",
    "responsibilities",
    "qualifications",
    "requirements",
    "experience required",
    "years of experience",
    "salary",
    "compensation",
    "benefits",
    "full-time",
    "full time",
    "part-time",
    "part time",
    "contract",
    "remote",
    "hybrid",
    "on-site",
    "onsite",
    "equal opportunity",
    "eeo",
]

CAREERS_SIGNALS = [
    "careers",
    "career opportunities",
    "open positions",
    "open roles",
    "job openings",
    "we're hiring",
    "we are hiring",
    "join us",
    "join our team",
    "work with us",
    "work at",
    "current openings",
    "view all jobs",
    "see all positions",
    "talent",
    "recruitment",
    "employer",
]

MIN_SIGNALS_THRESHOLD = 3


def _extract_url_signals(url: str) -> list[str]:
    """Return low-cost job/careers hints derived from the URL itself."""
    normalized = url.lower()
    matches: list[str] = []

    if "career" in normalized:
        matches.append("careers(url)")
    if any(token in normalized for token in ("/jobs", "/job/", "jobs.", "job.")):
        matches.append("jobs(url)")
    if "work-with-us" in normalized:
        matches.append("work-with-us(url)")
    if any(token in normalized for token in ("join-us", "join-our-team")):
        matches.append("join-us(url)")

    return matches


async def check_url_wellformed(url: str, **kwargs) -> tuple[bool, str]:
    """Reject URLs that are syntactically broken before any other work happens.

    This check sits first because downstream verification assumes it can safely
    parse scheme, host, and port information. Running it up front avoids wasting
    blocklist lookups or network I/O on clearly malformed strings. It can still
    produce false negatives for unusual but technically valid edge-case hosts,
    but the bias toward conservative rejection is acceptable because fabricated
    or badly extracted URLs are common in model output.

    Args:
        url: The URL to validate.
        **kwargs: Unused compatibility parameters to keep a shared check
            signature across the pipeline.

    Returns:
        tuple[bool, str]: Whether the URL passed structural validation and the
        reason recorded in verification evidence.
    """
    try:
        if not url or not url.strip():
            return False, "URL is empty or whitespace"

        test_url = url.strip()
        parsed = urlparse(test_url)

        if not parsed.scheme:
            return False, f"URL missing scheme (http/https): {url[:80]}"

        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return False, f"Invalid scheme: {parsed.scheme}"

        if not parsed.hostname:
            return False, "URL has no hostname"

        try:
            parsed.port
        except ValueError as exc:
            return False, f"Invalid port: {exc}"

        hostname = parsed.hostname

        if "." not in hostname:
            return False, f"Hostname has no TLD: {hostname}"

        if len(hostname) > 253:
            return False, f"Hostname too long: {len(hostname)} chars"

        parts = hostname.split(".")
        if any(not part for part in parts):
            return False, f"Hostname has empty components: {hostname}"

        for part in parts:
            if len(part) > 63:
                return False, f"Hostname label too long: {part}"
            if not _HOSTNAME_LABEL_RE.fullmatch(part):
                return False, f"Hostname label has invalid characters: {part}"

        return True, f"URL is well-formed: scheme={scheme}, host={hostname}"
    except Exception as exc:
        logger.exception("Unexpected error while validating URL structure")
        return False, f"URL parsing error: {type(exc).__name__}: {exc}"


async def check_not_aggregator(url: str, **kwargs) -> tuple[bool, str]:
    """Reject known aggregator domains so only primary sources survive.

    This runs immediately after structural validation because it is still cheap
    and removes a large class of unwanted results before network calls begin.
    The check catches obvious job boards and ATS-hosted pages, which protects
    the database from unstable or indirect URLs. False positives are possible
    when an institution legitimately uses a blocked platform, while false
    negatives remain possible for unknown aggregators not yet in the blocklist.

    Args:
        url: The URL to check.
        **kwargs: Unused compatibility parameters to keep a shared check
            signature across the pipeline.

    Returns:
        tuple[bool, str]: Whether the URL appears to come from a primary-source
        employer domain and the rationale for that decision.
    """
    try:
        normalized_url = normalize_url(url)
        hostname = urlparse(normalized_url).hostname or ""
        domain = extract_root_domain(normalized_url).lower()

        if not domain or "." not in domain:
            return (
                False,
                f"Domain extraction failed: invalid domain: {domain or '<empty>'}",
            )

        if hostname in _PRIMARY_SOURCE_HOST_ALLOWLIST:
            return True, f"Allowed primary-source careers host: {hostname}"

        if domain in _AGGREGATOR_DOMAIN_SET:
            return False, f"Aggregator site rejected: {domain}"

        for agg_domain in _AGGREGATOR_DOMAIN_SET:
            if hostname.endswith("." + agg_domain):
                return (
                    False,
                    f"Aggregator site rejected: {hostname} (matches {agg_domain})",
                )

        return True, f"Not an aggregator: {domain}"

    except Exception as exc:
        # If we can't extract the domain, fail closed (reject).
        return False, f"Domain extraction failed: {type(exc).__name__}: {exc}"


async def check_dns_resolves(url: str, **kwargs) -> tuple[bool, str]:
    """Reject domains that do not resolve before paying for a full HTTP fetch.

    DNS resolution is the first networked check because it is usually much
    cheaper than an HTTP request yet still catches a common failure mode:
    fabricated or dead domains returned by the model. False negatives are
    possible during transient DNS outages, and false positives remain possible
    because a resolving host can still serve non-job or broken content.

    Args:
        url: The URL to check.
        **kwargs: Unused compatibility parameters to keep a shared check
            signature across the pipeline.

    Returns:
        tuple[bool, str]: Whether the hostname resolved and the evidence detail
        explaining the outcome.
    """
    hostname: str | None = None

    try:
        parsed = urlparse(url.strip() if isinstance(url, str) else "")
        hostname = parsed.hostname

        if not hostname:
            return False, "No hostname to resolve"

        loop = asyncio.get_running_loop()
        addr_info = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(
                hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            ),
        )

        if not addr_info:
            return False, f"DNS returned no records for {hostname}"

        first_ip = addr_info[0][4][0]
        return True, f"DNS resolves: {hostname} -> {first_ip}"

    except socket.gaierror as exc:
        return False, f"DNS resolution failed for {hostname or '<unknown>'}: {exc}"
    except Exception as exc:
        return False, f"DNS check error: {type(exc).__name__}: {exc}"


async def check_http_reachable(url: str, **kwargs) -> tuple[bool, str]:
    """Confirm that the candidate page can be fetched over HTTP.

    This check comes after DNS because many bad candidates fail before an HTTP
    request is necessary. It catches dead links, redirect loops, and hosts that
    are technically real but unusable as source material. False negatives can
    happen when legitimate sites block bots or are temporarily down, while false
    positives remain possible because a reachable page may still be unrelated to
    hiring.

    Args:
        url: The URL to check.
        **kwargs: Optional overrides such as ``timeout`` for network behavior.

    Returns:
        tuple[bool, str]: Whether the URL returned an acceptable HTTP response
        and a detail string suitable for evidence storage.
    """
    timeout = kwargs.get("timeout", VERIFICATION_TIMEOUT_SECONDS)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=10,
            timeout=httpx.Timeout(timeout),
            verify=True,
        ) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; JobDiscoveryBot/1.0; "
                        "+https://github.com/job-discovery-engine)"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )

        status = response.status_code
        if 200 <= status <= 399:
            final_url = str(response.url)
            detail = f"HTTP {status}"
            if final_url != url:
                detail += f" (redirected to {final_url[:100]})"
            return True, detail

        return False, f"HTTP {status} {response.reason_phrase or 'error'}"
    except httpx.TimeoutException:
        return False, f"HTTP timeout after {timeout}s"
    except httpx.ConnectError as exc:
        return False, f"HTTP connection failed: {str(exc)[:100]}"
    except httpx.TooManyRedirects:
        return False, "HTTP too many redirects (>10)"
    except httpx.HTTPStatusError as exc:
        return False, f"HTTP status error: {exc.response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"HTTP error: {type(exc).__name__}: {str(exc)[:100]}"
    except Exception as exc:
        return False, f"HTTP error: {type(exc).__name__}: {str(exc)[:100]}"


async def check_content_signals(url: str, **kwargs) -> tuple[bool, str]:
    """Look for textual hiring signals on the fetched page itself.

    This is intentionally the last check because it repeats an HTTP fetch and
    uses heuristic content analysis, making it the most expensive and the most
    subjective stage. It catches pages that are reachable but not actually job
    or careers content. False positives are possible on generic recruiting or
    company pages that mention enough hiring language, and false negatives are
    possible on sparse or JavaScript-heavy pages where the relevant text is not
    present in the initial HTML.

    Args:
        url: The URL to fetch and analyze.
        **kwargs: Optional overrides such as ``timeout`` for network behavior.

    Returns:
        tuple[bool, str]: Whether the page looks job-related and the evidence
        detail describing matched or missing signals.
    """
    timeout = kwargs.get("timeout", VERIFICATION_TIMEOUT_SECONDS)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=10,
            timeout=httpx.Timeout(timeout),
            verify=True,
        ) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; JobDiscoveryBot/1.0; "
                        "+https://github.com/job-discovery-engine)"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                },
            )

        if response.status_code >= 400:
            return False, f"Cannot analyze content: HTTP {response.status_code}"

        content = response.text[:10000].lower()

        matched_job_signals = [signal for signal in JOB_SIGNALS if signal in content]
        matched_career_signals = [
            signal for signal in CAREERS_SIGNALS if signal in content
        ]
        all_matched = matched_job_signals + matched_career_signals
        total_signals = len(all_matched)
        url_signals = _extract_url_signals(str(response.url))
        strong_url_hint = bool(url_signals)

        if total_signals >= MIN_SIGNALS_THRESHOLD or (
            total_signals >= 1 and strong_url_hint
        ):
            examples = (all_matched + url_signals)[:5]
            detail = f"{total_signals} page signals"
            if strong_url_hint:
                detail += f" + {len(url_signals)} URL hints"
            detail += f" found: {', '.join(examples)}"
            extra_count = total_signals + len(url_signals) - len(examples)
            if extra_count > 0:
                detail += f" (+{extra_count} more)"
            return True, detail

        matched_text = ", ".join(all_matched) if all_matched else "none"
        return (
            False,
            f"Only {total_signals} signals found (need {MIN_SIGNALS_THRESHOLD}+). "
            f"Matched: {matched_text}. Page may not be job-related.",
        )
    except httpx.TimeoutException:
        return False, f"Content fetch timeout after {timeout}s"
    except Exception as exc:
        return False, f"Content analysis error: {type(exc).__name__}: {str(exc)[:100]}"
