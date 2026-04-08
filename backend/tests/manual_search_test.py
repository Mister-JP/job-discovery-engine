"""Manual integration test for the AI search layer.

Run with:
    python -m tests.manual_search_test
    python -m tests.manual_search_test "AI safety research labs hiring"

This script:
1. Builds a search prompt
2. Calls Gemini with grounded search
3. Parses the response
4. Prints structured results

It is intentionally not part of the automated test suite because it
requires a valid GEMINI_API_KEY and live network access.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import GEMINI_API_KEY
from app.services.gemini_client import grounded_search
from app.services.prompt_builder import AGGREGATOR_BLOCKLIST, build_search_prompt
from app.services.response_parser import parse_gemini_response


def _find_aggregator_urls(urls: list[str]) -> list[str]:
    """Return URLs that match the configured aggregator blocklist."""
    lowered_blocklist = tuple(domain.lower() for domain in AGGREGATOR_BLOCKLIST)
    return [
        url
        for url in urls
        if any(domain in url.lower() for domain in lowered_blocklist)
    ]


async def main() -> None:
    """Run a full manual search against Gemini and print parsed results."""
    query = (
        " ".join(sys.argv[1:]).strip()
        if len(sys.argv) > 1
        else "AI safety research labs hiring researchers"
    )

    print(f"\n{'=' * 60}")
    print(f"Query: {query}")
    print(f"{'=' * 60}\n")

    system_prompt, user_message = build_search_prompt(
        query=query,
        known_domains=[],
    )

    print(f"System prompt length: {len(system_prompt)} chars")
    print(f"User message: {user_message[:100]}...\n")

    if not GEMINI_API_KEY:
        print(
            "ERROR: GEMINI_API_KEY is not set. Add it to your shell environment "
            "or the repo-root .env file and rerun this script."
        )
        return

    print("Calling Gemini 2.5 Flash with grounding...")
    response = await grounded_search(
        query=user_message,
        system_prompt=system_prompt,
    )

    if response["error"]:
        print(f"\nERROR: {response['error']}")
        return

    response_text = str(response["text"])
    print(f"Response length: {len(response_text)} chars")

    search_queries = response.get("search_queries")
    if search_queries:
        print(f"Web searches used: {search_queries}")

    grounding_metadata = response.get("grounding_metadata") or {}
    grounding_chunks = grounding_metadata.get("chunks") or []
    if grounding_chunks:
        print(f"Citations returned: {len(grounding_chunks)}")
    print()

    result, parse_error = parse_gemini_response(response_text)
    if parse_error:
        print(f"\nERROR: {parse_error}")
        print(f"\nRaw response preview:\n{response_text[:500]}")
        return

    assert result is not None

    print(
        f"Found {result.total_institutions} institutions "
        f"with {result.total_jobs} total jobs\n"
    )

    for index, institution in enumerate(result.institutions, start=1):
        print(f"  [{index}] {institution.name}")
        print(f"      Type: {institution.institution_type}")
        print(f"      Careers: {institution.careers_url}")
        if institution.location:
            print(f"      Location: {institution.location}")
        if institution.description:
            print(f"      Description: {institution.description[:80]}...")

        for job_index, job in enumerate(institution.jobs, start=1):
            print(f"      Job {job_index}: {job.title}")
            print(f"             URL: {job.url}")
            if job.location:
                print(f"             Location: {job.location}")
            if job.experience_level:
                print(f"             Level: {job.experience_level}")
            if job.salary_range:
                print(f"             Salary: {job.salary_range}")
        print()

    aggregator_urls = _find_aggregator_urls(result.all_urls())
    if aggregator_urls:
        print(f"WARNING: {len(aggregator_urls)} URLs from aggregators detected:")
        for url in aggregator_urls:
            print(f"  - {url}")
    else:
        print("No aggregator URLs detected; all results are from primary sources.")

    print(f"\n{'=' * 60}")
    print("Raw JSON response (first 1000 chars):")
    print(response_text[:1000])


if __name__ == "__main__":
    asyncio.run(main())
