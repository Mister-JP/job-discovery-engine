"""Compact verification-check tests for CI-friendly coverage."""

from __future__ import annotations

import pytest

from app.services.verification_checks import check_not_aggregator, check_url_wellformed


@pytest.mark.asyncio
class TestUrlWellformed:
    async def test_valid_https(self):
        passed, _ = await check_url_wellformed("https://example.com/jobs")

        assert passed is True

    async def test_missing_scheme(self):
        passed, _ = await check_url_wellformed("example.com/jobs")

        assert passed is False

    async def test_empty(self):
        passed, _ = await check_url_wellformed("")

        assert passed is False


@pytest.mark.asyncio
class TestNotAggregator:
    async def test_primary_source(self):
        passed, _ = await check_not_aggregator("https://openai.com/careers")

        assert passed is True

    async def test_indeed(self):
        passed, _ = await check_not_aggregator("https://indeed.com/viewjob")

        assert passed is False

    async def test_linkedin(self):
        passed, _ = await check_not_aggregator("https://linkedin.com/jobs/view/123")

        assert passed is False

    async def test_greenhouse(self):
        passed, _ = await check_not_aggregator(
            "https://boards.greenhouse.io/company/123"
        )

        assert passed is False
