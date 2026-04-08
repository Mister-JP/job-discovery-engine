"""Unit tests for individual URL verification checks."""

from pathlib import Path
import socket
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.prompt_builder import AGGREGATOR_BLOCKLIST
from app.services.verification_checks import (
    MIN_SIGNALS_THRESHOLD,
    CAREERS_SIGNALS,
    JOB_SIGNALS,
    check_content_signals,
    check_dns_resolves,
    check_http_reachable,
    check_not_aggregator,
    check_url_wellformed,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_detail"),
    [
        ("https://openai.com/careers", "scheme=https, host=openai.com"),
        ("http://example.com/jobs/123", "scheme=http, host=example.com"),
        ("HTTPS://Example.com/jobs", "scheme=https, host=example.com"),
        (
            "https://a.b.c.d.example.com/deep/path",
            "scheme=https, host=a.b.c.d.example.com",
        ),
    ],
)
async def test_check_url_wellformed_accepts_valid_urls(url, expected_detail):
    passed, detail = await check_url_wellformed(url)

    assert passed is True
    assert expected_detail in detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_detail"),
    [
        ("", "URL is empty or whitespace"),
        ("   ", "URL is empty or whitespace"),
        ("not-a-url", "URL missing scheme"),
        ("https://", "URL has no hostname"),
        ("https://localhost", "Hostname has no TLD"),
        ("ftp://example.com", "Invalid scheme"),
        ("https://exa_mple.com/jobs", "Hostname label has invalid characters"),
        ("https://example..com/jobs", "Hostname has empty components"),
        ("https://example.com:abc/jobs", "Invalid port"),
    ],
)
async def test_check_url_wellformed_rejects_invalid_urls(url, expected_detail):
    passed, detail = await check_url_wellformed(url)

    assert passed is False
    assert expected_detail in detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_detail"),
    [
        ("https://openai.com/careers", "Not an aggregator: openai.com"),
        ("https://anthropic.com/careers/research", "Not an aggregator: anthropic.com"),
        ("https://stripe.com/jobs/engineer", "Not an aggregator: stripe.com"),
    ],
)
async def test_check_not_aggregator_accepts_primary_source_domains(
    url, expected_detail
):
    passed, detail = await check_not_aggregator(url)

    assert passed is True
    assert expected_detail in detail


@pytest.mark.asyncio
async def test_check_not_aggregator_allows_google_careers_host():
    passed, detail = await check_not_aggregator("https://careers.google.com/")

    assert passed is True
    assert detail == "Allowed primary-source careers host: careers.google.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_detail"),
    [
        ("https://indeed.com/viewjob?id=123", "Aggregator site rejected: indeed.com"),
        (
            "https://www.linkedin.com/jobs/view/456",
            "Aggregator site rejected: linkedin.com",
        ),
        (
            "https://glassdoor.com/job-listing/789",
            "Aggregator site rejected: glassdoor.com",
        ),
        ("https://jobs.lever.co/stripe/abc", "Aggregator site rejected: lever.co"),
        (
            "https://boards.greenhouse.io/anthropic/123",
            "Aggregator site rejected: greenhouse.io",
        ),
        (
            "https://www.google.com/search?q=openai+jobs",
            "Aggregator site rejected: google.com",
        ),
    ],
)
async def test_check_not_aggregator_rejects_known_aggregators(url, expected_detail):
    passed, detail = await check_not_aggregator(url)

    assert passed is False
    assert expected_detail in detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_detail"),
    [
        ("not-a-url", "Domain extraction failed"),
        ("https://localhost/jobs", "Domain extraction failed"),
        (None, "Domain extraction failed"),
    ],
)
async def test_check_not_aggregator_fails_closed_on_bad_domains(url, expected_detail):
    passed, detail = await check_not_aggregator(url)

    assert passed is False
    assert expected_detail in detail


@pytest.mark.asyncio
async def test_check_dns_resolves_accepts_resolvable_host(monkeypatch):
    def fake_getaddrinfo(host, port, family, socktype):
        assert host == "openai.com"
        assert port is None
        assert family == socket.AF_UNSPEC
        assert socktype == socket.SOCK_STREAM
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("104.18.33.45", 0),
            ),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    passed, detail = await check_dns_resolves("https://openai.com/careers")

    assert passed is True
    assert "DNS resolves: openai.com -> 104.18.33.45" in detail


@pytest.mark.asyncio
async def test_check_dns_resolves_rejects_host_with_no_records(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])

    passed, detail = await check_dns_resolves(
        "https://missing.example.invalid/jobs/123",
    )

    assert passed is False
    assert "DNS returned no records for missing.example.invalid" in detail


@pytest.mark.asyncio
async def test_check_dns_resolves_handles_socket_gaierror(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    passed, detail = await check_dns_resolves(
        "https://thisisafakedomainthatdoesnotexist12345.com/jobs",
    )

    assert passed is False
    assert (
        "DNS resolution failed for thisisafakedomainthatdoesnotexist12345.com" in detail
    )


@pytest.mark.asyncio
async def test_check_dns_resolves_rejects_missing_hostname():
    passed, detail = await check_dns_resolves("not-a-url")

    assert passed is False
    assert detail == "No hostname to resolve"


class FakeAsyncClient:
    """Minimal async client stub for testing check_http_reachable."""

    request_url = None
    request_headers = None
    init_kwargs = None
    response = None
    error = None

    def __init__(self, **kwargs):
        type(self).init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers):
        type(self).request_url = url
        type(self).request_headers = headers
        if type(self).error is not None:
            raise type(self).error
        return type(self).response


@pytest.fixture
def fake_http_client(monkeypatch):
    FakeAsyncClient.request_url = None
    FakeAsyncClient.request_headers = None
    FakeAsyncClient.init_kwargs = None
    FakeAsyncClient.response = None
    FakeAsyncClient.error = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


@pytest.mark.asyncio
async def test_check_http_reachable_accepts_success_status(fake_http_client):
    fake_http_client.response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://openai.com/careers"),
    )

    passed, detail = await check_http_reachable("https://openai.com/careers")

    assert passed is True
    assert detail == "HTTP 200"
    assert fake_http_client.request_url == "https://openai.com/careers"
    assert fake_http_client.request_headers["User-Agent"].startswith("Mozilla/5.0")
    assert fake_http_client.init_kwargs["follow_redirects"] is True
    assert fake_http_client.init_kwargs["max_redirects"] == 10
    assert fake_http_client.init_kwargs["verify"] is True
    assert fake_http_client.init_kwargs["timeout"] == httpx.Timeout(8)


@pytest.mark.asyncio
async def test_check_http_reachable_includes_redirect_target(fake_http_client):
    fake_http_client.response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://www.openai.com/careers/"),
    )

    passed, detail = await check_http_reachable("https://openai.com/careers")

    assert passed is True
    assert detail == "HTTP 200 (redirected to https://www.openai.com/careers/)"


@pytest.mark.asyncio
async def test_check_http_reachable_rejects_error_status(fake_http_client):
    fake_http_client.response = httpx.Response(
        404,
        request=httpx.Request("GET", "https://example.com/missing"),
    )

    passed, detail = await check_http_reachable("https://example.com/missing")

    assert passed is False
    assert detail == "HTTP 404 Not Found"


@pytest.mark.asyncio
async def test_check_http_reachable_handles_timeout(fake_http_client):
    request = httpx.Request("GET", "https://example.com/slow")
    fake_http_client.error = httpx.ReadTimeout("timed out", request=request)

    passed, detail = await check_http_reachable("https://example.com/slow", timeout=3)

    assert passed is False
    assert detail == "HTTP timeout after 3s"


@pytest.mark.asyncio
async def test_check_http_reachable_handles_connection_error(fake_http_client):
    request = httpx.Request("GET", "https://missing.example.invalid/jobs")
    fake_http_client.error = httpx.ConnectError("all attempts failed", request=request)

    passed, detail = await check_http_reachable("https://missing.example.invalid/jobs")

    assert passed is False
    assert "HTTP connection failed: all attempts failed" in detail


@pytest.mark.asyncio
async def test_check_http_reachable_handles_too_many_redirects(fake_http_client):
    request = httpx.Request("GET", "https://example.com/loop")
    fake_http_client.error = httpx.TooManyRedirects(
        "Exceeded redirect limit", request=request
    )

    passed, detail = await check_http_reachable("https://example.com/loop")

    assert passed is False
    assert detail == "HTTP too many redirects (>10)"


@pytest.mark.asyncio
async def test_check_http_reachable_handles_http_status_error(fake_http_client):
    request = httpx.Request("GET", "https://example.com/server-error")
    response = httpx.Response(503, request=request)
    fake_http_client.error = httpx.HTTPStatusError(
        "Server error",
        request=request,
        response=response,
    )

    passed, detail = await check_http_reachable("https://example.com/server-error")

    assert passed is False
    assert detail == "HTTP status error: 503"


@pytest.mark.asyncio
async def test_check_http_reachable_handles_unexpected_http_error(fake_http_client):
    request = httpx.Request("GET", "https://example.com/weird")
    fake_http_client.error = httpx.ProtocolError(
        "broken HTTP/2 stream", request=request
    )

    passed, detail = await check_http_reachable("https://example.com/weird")

    assert passed is False
    assert "HTTP error: ProtocolError: broken HTTP/2 stream" in detail


@pytest.mark.asyncio
async def test_check_content_signals_accepts_job_related_pages(fake_http_client):
    html = """
    <html>
      <body>
        <h1>Careers</h1>
        <p>Apply now to join our team.</p>
        <p>Review the job description, responsibilities, and benefits.</p>
        <p>This is a full-time remote role.</p>
      </body>
    </html>
    """
    fake_http_client.response = httpx.Response(
        200,
        content=html.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", "https://openai.com/careers"),
    )

    passed, detail = await check_content_signals("https://openai.com/careers")

    assert passed is True
    assert "page signals" in detail
    assert "apply now" in detail
    assert (
        fake_http_client.request_headers["Accept"]
        == "text/html,application/xhtml+xml,*/*;q=0.8"
    )
    assert fake_http_client.init_kwargs["follow_redirects"] is True
    assert fake_http_client.init_kwargs["max_redirects"] == 10
    assert fake_http_client.init_kwargs["verify"] is True


@pytest.mark.asyncio
async def test_check_content_signals_rejects_pages_with_too_few_matches(
    fake_http_client,
):
    html = """
    <html>
      <body>
        <h1>Python</h1>
        <p>Python is a programming language with many benefits.</p>
      </body>
    </html>
    """
    fake_http_client.response = httpx.Response(
        200,
        content=html.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", "https://example.com/python"),
    )

    passed, detail = await check_content_signals("https://example.com/python")

    assert passed is False
    assert detail == (
        f"Only 1 signals found (need {MIN_SIGNALS_THRESHOLD}+). "
        "Matched: benefits. Page may not be job-related."
    )


@pytest.mark.asyncio
async def test_check_content_signals_limits_scan_to_first_10k_chars(fake_http_client):
    filler = "x" * 10000
    html = (
        "<html><body>"
        f"{filler}"
        "<p>careers apply now responsibilities qualifications benefits</p>"
        "</body></html>"
    )
    fake_http_client.response = httpx.Response(
        200,
        content=html.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", "https://example.com/late-signals"),
    )

    passed, detail = await check_content_signals("https://example.com/late-signals")

    assert passed is False
    assert detail == (
        f"Only 0 signals found (need {MIN_SIGNALS_THRESHOLD}+). "
        "Matched: none. Page may not be job-related."
    )


@pytest.mark.asyncio
async def test_check_content_signals_handles_http_error_status(fake_http_client):
    fake_http_client.response = httpx.Response(
        503,
        request=httpx.Request("GET", "https://example.com/unavailable"),
    )

    passed, detail = await check_content_signals("https://example.com/unavailable")

    assert passed is False
    assert detail == "Cannot analyze content: HTTP 503"


@pytest.mark.asyncio
async def test_check_content_signals_handles_timeout(fake_http_client):
    request = httpx.Request("GET", "https://example.com/slow-content")
    fake_http_client.error = httpx.ReadTimeout("timed out", request=request)

    passed, detail = await check_content_signals(
        "https://example.com/slow-content", timeout=4
    )

    assert passed is False
    assert detail == "Content fetch timeout after 4s"


@pytest.mark.asyncio
async def test_check_content_signals_handles_unexpected_errors(fake_http_client):
    fake_http_client.error = RuntimeError("decoder exploded")

    passed, detail = await check_content_signals("https://example.com/bad-content")

    assert passed is False
    assert detail == "Content analysis error: RuntimeError: decoder exploded"


@pytest.mark.asyncio
async def test_check_content_signals_accepts_sparse_page_with_careers_url_hint(
    fake_http_client,
):
    html = """
    <html>
      <head><title>Home | Microsoft Careers</title></head>
      <body>
        <p>Benefits and rewards for every employee.</p>
      </body>
    </html>
    """
    fake_http_client.response = httpx.Response(
        200,
        content=html.encode("utf-8"),
        headers={"Content-Type": "text/html; charset=utf-8"},
        request=httpx.Request(
            "GET", "https://careers.microsoft.com/v2/global/en/home.html"
        ),
    )

    passed, detail = await check_content_signals(
        "https://careers.microsoft.com/v2/global/en/home.html"
    )

    assert passed is True
    assert "URL hints" in detail
    assert "careers(url)" in detail


def test_aggregator_blocklist_includes_expected_domains():
    assert "indeed.com" in AGGREGATOR_BLOCKLIST
    assert "linkedin.com" in AGGREGATOR_BLOCKLIST
    assert "glassdoor.com" in AGGREGATOR_BLOCKLIST
    assert "lever.co" in AGGREGATOR_BLOCKLIST
    assert "greenhouse.io" in AGGREGATOR_BLOCKLIST
    assert "workday.com" in AGGREGATOR_BLOCKLIST
    assert "smartrecruiters.com" in AGGREGATOR_BLOCKLIST
    assert "google.com" in AGGREGATOR_BLOCKLIST
    assert len(AGGREGATOR_BLOCKLIST) >= 30


def test_content_signal_lists_meet_expected_size():
    assert len(JOB_SIGNALS) >= 15
    assert len(CAREERS_SIGNALS) >= 10
