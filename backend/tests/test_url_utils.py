"""Unit tests for URL normalization and domain extraction utilities.

Tests are organized by function, then by concern (normal cases, edge cases).
Run with: pytest tests/test_url_utils.py -v
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.url_utils import extract_root_domain, is_valid_url, normalize_url


class TestNormalizeUrl:
    """Tests for the normalize_url() function."""

    def test_strips_www_prefix(self):
        assert (
            normalize_url("https://www.example.com/jobs") == "https://example.com/jobs"
        )

    def test_adds_https_scheme_when_missing(self):
        assert normalize_url("example.com/jobs") == "https://example.com/jobs"

    def test_lowercases_scheme_and_host(self):
        assert (
            normalize_url("HTTPS://WWW.EXAMPLE.COM/Jobs") == "https://example.com/Jobs"
        )

    def test_removes_fragment(self):
        assert (
            normalize_url("https://example.com/jobs#apply")
            == "https://example.com/jobs"
        )

    def test_removes_utm_tracking_params(self):
        url = "https://example.com/jobs?utm_source=google&utm_medium=cpc&role=engineer"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "role=engineer" in result

    def test_removes_fbclid(self):
        url = "https://example.com/careers?fbclid=abc123"
        result = normalize_url(url)
        assert "fbclid" not in result

    def test_removes_gclid(self):
        url = "https://example.com/careers?gclid=xyz789&position=dev"
        result = normalize_url(url)
        assert "gclid" not in result
        assert "position=dev" in result

    def test_sorts_query_params(self):
        url1 = "https://example.com/search?b=2&a=1"
        url2 = "https://example.com/search?a=1&b=2"
        assert normalize_url(url1) == normalize_url(url2)

    def test_removes_trailing_slash(self):
        assert normalize_url("https://example.com/jobs/") == "https://example.com/jobs"

    def test_keeps_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_adds_root_slash_for_bare_domain(self):
        assert normalize_url("https://example.com") == "https://example.com/"

    def test_removes_default_port_80(self):
        assert normalize_url("http://example.com:80/jobs") == "http://example.com/jobs"

    def test_removes_default_port_443(self):
        assert (
            normalize_url("https://example.com:443/jobs") == "https://example.com/jobs"
        )

    def test_keeps_non_default_port(self):
        result = normalize_url("https://example.com:8080/jobs")
        assert ":8080" in result

    def test_strips_whitespace(self):
        assert (
            normalize_url("  https://example.com/jobs  ") == "https://example.com/jobs"
        )

    def test_idempotent(self):
        """Normalizing an already-normalized URL should return the same result."""
        url = "https://example.com/careers?role=engineer"
        first = normalize_url(url)
        second = normalize_url(first)
        assert first == second

    def test_preserves_path_case(self):
        """Paths can be case-sensitive; don't lowercase them."""
        result = normalize_url("https://example.com/CaReErS/EnGiNeEr")
        assert "/CaReErS/EnGiNeEr" in result

    def test_preserves_meaningful_query_params(self):
        url = "https://example.com/jobs?department=engineering&level=senior"
        result = normalize_url(url)
        assert "department=engineering" in result
        assert "level=senior" in result

    def test_empty_query_after_filtering(self):
        url = "https://example.com/jobs?utm_source=google"
        result = normalize_url(url)
        assert result == "https://example.com/jobs"
        assert "?" not in result

    def test_filters_tracking_params_case_insensitively(self):
        url = "https://example.com/jobs?UTM_SOURCE=google&role=engineer"
        result = normalize_url(url)
        assert "UTM_SOURCE" not in result
        assert "role=engineer" in result


class TestExtractRootDomain:
    """Tests for the extract_root_domain() function."""

    def test_simple_domain(self):
        assert extract_root_domain("https://openai.com/careers") == "openai.com"

    def test_strips_subdomain(self):
        assert extract_root_domain("https://careers.openai.com/jobs") == "openai.com"

    def test_strips_www(self):
        assert extract_root_domain("https://www.openai.com") == "openai.com"

    def test_deep_subdomain(self):
        assert extract_root_domain("https://jobs.eng.openai.com") == "openai.com"

    def test_co_uk(self):
        assert extract_root_domain("https://jobs.bbc.co.uk") == "bbc.co.uk"

    def test_ac_uk(self):
        assert extract_root_domain("https://www.cs.ox.ac.uk/research") == "ox.ac.uk"

    def test_com_au(self):
        assert extract_root_domain("https://careers.csiro.com.au") == "csiro.com.au"

    def test_co_jp(self):
        assert extract_root_domain("https://jobs.example.co.jp") == "example.co.jp"

    def test_org_domain(self):
        assert extract_root_domain("https://www.mozilla.org/careers") == "mozilla.org"

    def test_bare_domain_no_path(self):
        assert extract_root_domain("https://stripe.com") == "stripe.com"

    def test_without_scheme(self):
        assert extract_root_domain("example.com/jobs") == "example.com"

    def test_with_port(self):
        assert extract_root_domain("https://example.com:8080/jobs") == "example.com"


class TestIsValidUrl:
    """Tests for the is_valid_url() function."""

    def test_valid_https_url(self):
        assert is_valid_url("https://example.com/jobs") is True

    def test_valid_http_url(self):
        assert is_valid_url("http://example.com") is True

    def test_valid_without_scheme(self):
        assert is_valid_url("example.com/careers") is True

    def test_valid_with_whitespace(self):
        assert is_valid_url("  example.com/careers  ") is True

    def test_empty_string(self):
        assert is_valid_url("") is False

    def test_whitespace_only(self):
        assert is_valid_url("   ") is False

    def test_no_tld(self):
        assert is_valid_url("https://localhost") is False

    def test_plain_text(self):
        assert is_valid_url("not a url at all") is False

    def test_none_value(self):
        assert is_valid_url(None) is False

    def test_just_scheme(self):
        assert is_valid_url("https://") is False
