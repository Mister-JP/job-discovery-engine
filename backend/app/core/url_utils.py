"""Canonical URL helpers used by discovery, verification, and persistence.

The backend deduplicates both institutions and jobs using URLs and domains, so
small variations such as mixed casing, tracking parameters, or stray `www`
prefixes can otherwise create false duplicates. These helpers centralize that
normalization logic so storage, verification, and observability all talk about
the same canonical address.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Tracking parameters to strip (common across job boards and websites)
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "fbclid",
    "gclid",
    "gclsrc",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "si",
    "spm",
    "s",
    "share",
    "_ga",
    "_gl",
    "_hsenc",
    "_hsmi",
    "trk",
    "trkInfo",
    "originalSubdomain",
}

# Known country-code second-level domains (for extract_root_domain)
CC_SLDS = {
    "co.uk",
    "org.uk",
    "ac.uk",
    "gov.uk",
    "co.jp",
    "or.jp",
    "ac.jp",
    "co.kr",
    "or.kr",
    "co.nz",
    "org.nz",
    "co.za",
    "org.za",
    "co.in",
    "org.in",
    "com.au",
    "org.au",
    "edu.au",
    "com.br",
    "org.br",
    "co.il",
}


def normalize_url(url: str) -> str:
    """Return a canonical URL string for deduplication and comparison.

    The discovery pipeline sees the same page through many equivalent URL
    variants, especially when Gemini cites marketing links or redirect-heavy
    ATS pages. Normalizing once up front prevents those variants from creating
    duplicate institutions/jobs and keeps verification evidence tied to a
    stable identifier.

    Args:
        url: The URL to normalize. Can be with or without scheme.

    Returns:
        str: A deterministic canonical URL with obvious noise removed.

    Examples:
        >>> normalize_url("https://WWW.Example.com/jobs?utm_source=google#apply")
        'https://example.com/jobs'
        >>> normalize_url("example.com/careers/")
        'https://example.com/careers'
    """
    url = url.strip()

    # Ensure scheme.
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)

    # Lowercase scheme and hostname.
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    # Remove www. prefix.
    if hostname.startswith("www."):
        hostname = hostname[4:]

    # Remove default ports.
    port = parsed.port
    if port in (80, 443, None):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    # Filter and sort query parameters for deterministic output.
    if parsed.query:
        params = parse_qsl(parsed.query, keep_blank_values=True)
        filtered = [
            (key, value) for key, value in params if key.lower() not in TRACKING_PARAMS
        ]
        query = urlencode(sorted(filtered), doseq=True) if filtered else ""
    else:
        query = ""

    # Clean path: remove trailing slash (but keep root /).
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    normalized = urlunparse((scheme, netloc, path, "", query, ""))
    return normalized


def extract_root_domain(url: str) -> str:
    """Extract the registrable root domain used for institution identity.

    Institution deduplication happens at the organization-domain level rather
    than per subdomain because careers, jobs, and department sites usually
    belong to the same employer. The country-code second-level domain handling
    exists to avoid incorrectly collapsing domains such as `ox.ac.uk` to
    `ac.uk`, which would destroy identity precision.

    Args:
        url: A URL string (with or without scheme).

    Returns:
        str: The root domain, such as ``"openai.com"`` or ``"ox.ac.uk"``.

    Examples:
        >>> extract_root_domain("https://careers.openai.com/jobs/123")
        'openai.com'
        >>> extract_root_domain("https://www.cs.ox.ac.uk/research")
        'ox.ac.uk'
        >>> extract_root_domain("https://jobs.bbc.co.uk/apply")
        'bbc.co.uk'
    """
    # Normalize first to handle www. and scheme.
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    hostname = parsed.hostname or ""

    parts = hostname.split(".")

    if len(parts) <= 2:
        return hostname

    # Check for country-code second-level domains.
    last_two = ".".join(parts[-2:])
    if last_two in CC_SLDS and len(parts) >= 3:
        return ".".join(parts[-3:])

    return ".".join(parts[-2:])


def is_valid_url(url: str) -> bool:
    """Return whether a string is structurally URL-like without network I/O.

    This helper exists for lightweight guards and UI-facing validation where a
    full verification pass would be too expensive or too strict. It deliberately
    stops at syntax because reachability and job relevance are handled later by
    the verification pipeline.

    Args:
        url: String to validate.

    Returns:
        bool: ``True`` when the input looks like an absolute HTTP(S) URL.
    """
    try:
        if not url or not url.strip():
            return False

        # Add scheme if missing for parsing.
        test_url = url.strip()
        if not test_url.lower().startswith(("http://", "https://")):
            test_url = "https://" + test_url

        parsed = urlparse(test_url)
        return bool(parsed.scheme and parsed.netloc and "." in parsed.netloc)
    except Exception:
        return False
