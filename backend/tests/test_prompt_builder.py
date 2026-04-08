"""Unit tests for prompt construction helpers."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.prompt_builder import (
    AGGREGATOR_BLOCKLIST,
    build_search_prompt,
    build_verification_prompt,
)


def test_build_search_prompt_injects_known_domains_and_schema():
    system_prompt, user_message = build_search_prompt(
        query="climate tech startups hiring engineers",
        known_domains=["openai.com", "stripe.com", "openai.com"],
        max_results=12,
    )

    assert "Return UP TO 12 results." in system_prompt
    assert '"institutions": [' in system_prompt
    assert "KNOWN DOMAINS" in system_prompt
    assert "openai.com, stripe.com" in system_prompt
    assert AGGREGATOR_BLOCKLIST[0] in system_prompt
    assert AGGREGATOR_BLOCKLIST[-1] in system_prompt
    assert "Return ONLY raw JSON." in system_prompt
    assert "Search the web for: climate tech startups hiring engineers" in user_message
    assert "Direct employer websites" in user_message


def test_build_search_prompt_handles_empty_known_domains():
    system_prompt, _ = build_search_prompt(
        query="robotics internships",
        known_domains=[],
    )

    assert "No institutions are in the database yet." in system_prompt
    assert "KNOWN DOMAINS" not in system_prompt


def test_build_verification_prompt_truncates_page_content():
    long_content = "A" * 6000

    prompt = build_verification_prompt(
        url="https://example.com/jobs/123",
        page_content=long_content,
    )

    assert "URL: https://example.com/jobs/123" in prompt
    assert '"is_job_related": true/false' in prompt
    assert "A" * 5000 in prompt
    assert "A" * 5001 not in prompt
