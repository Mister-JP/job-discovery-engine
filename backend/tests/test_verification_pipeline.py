"""Unit tests for the ordered verification pipeline."""

import asyncio
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.entities import VerificationCheckName
from app.services import verification_pipeline


def make_check(recorder, name, passed=True, detail=None, error=None):
    """Create an async check stub that records its execution."""

    async def _check(url: str, **kwargs) -> tuple[bool, str]:
        recorder.append((name, url, kwargs))
        if error is not None:
            raise error
        return passed, detail or f"{name} {'passed' if passed else 'failed'}"

    return _check


@pytest.mark.asyncio
async def test_verify_candidate_runs_all_checks_and_collects_evidence(
    monkeypatch, caplog
):
    calls = []
    monkeypatch.setattr(
        verification_pipeline,
        "CHECKS",
        [
            (
                VerificationCheckName.URL_WELLFORMED,
                make_check(calls, VerificationCheckName.URL_WELLFORMED.value),
            ),
            (
                VerificationCheckName.NOT_AGGREGATOR,
                make_check(calls, VerificationCheckName.NOT_AGGREGATOR.value),
            ),
            (
                VerificationCheckName.DNS_RESOLVES,
                make_check(calls, VerificationCheckName.DNS_RESOLVES.value),
            ),
            (
                VerificationCheckName.HTTP_REACHABLE,
                make_check(calls, VerificationCheckName.HTTP_REACHABLE.value),
            ),
            (
                VerificationCheckName.CONTENT_SIGNALS,
                make_check(calls, VerificationCheckName.CONTENT_SIGNALS.value),
            ),
        ],
    )

    with caplog.at_level("DEBUG"):
        passed, evidence = await verification_pipeline.verify_candidate(
            url="https://openai.com/careers",
            search_run_id=uuid.uuid4(),
            candidate_name="OpenAI",
        )

    assert passed is True
    assert [call[0] for call in calls] == [
        "url_wellformed",
        "not_aggregator",
        "dns_resolves",
        "http_reachable",
        "content_signals",
    ]
    assert [item.check_name for item in evidence] == [
        VerificationCheckName.URL_WELLFORMED,
        VerificationCheckName.NOT_AGGREGATOR,
        VerificationCheckName.DNS_RESOLVES,
        VerificationCheckName.HTTP_REACHABLE,
        VerificationCheckName.CONTENT_SIGNALS,
    ]
    assert all(item.passed is True for item in evidence)
    assert all(item.candidate_url == "https://openai.com/careers" for item in evidence)
    assert all(item.candidate_name == "OpenAI" for item in evidence)
    assert all(
        isinstance(item.duration_ms, int) and item.duration_ms >= 0 for item in evidence
    )
    assert "Verification PASSED: OpenAI (5/5 checks passed)" in caplog.text
    summary_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "verification_candidate_completed"
    )
    assert summary_record.verification_outcome == "PASSED"
    assert summary_record.passed_count == 5
    assert summary_record.check_count == 5
    assert isinstance(summary_record.duration_ms, int)
    assert summary_record.duration_ms >= 0


@pytest.mark.asyncio
async def test_verify_candidate_fails_fast_on_first_failed_check(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(
        verification_pipeline,
        "CHECKS",
        [
            (
                VerificationCheckName.URL_WELLFORMED,
                make_check(calls, VerificationCheckName.URL_WELLFORMED.value),
            ),
            (
                VerificationCheckName.NOT_AGGREGATOR,
                make_check(
                    calls,
                    VerificationCheckName.NOT_AGGREGATOR.value,
                    passed=False,
                    detail="Aggregator site rejected: indeed.com",
                ),
            ),
            (
                VerificationCheckName.DNS_RESOLVES,
                make_check(calls, VerificationCheckName.DNS_RESOLVES.value),
            ),
        ],
    )

    with caplog.at_level("INFO"):
        passed, evidence = await verification_pipeline.verify_candidate(
            url="https://indeed.com/viewjob?id=123",
            search_run_id=uuid.uuid4(),
            candidate_name="Indeed Job",
        )

    assert passed is False
    assert [call[0] for call in calls] == ["url_wellformed", "not_aggregator"]
    assert len(evidence) == 2
    assert evidence[0].passed is True
    assert evidence[1].passed is False
    assert evidence[1].detail == "Aggregator site rejected: indeed.com"
    assert "Verification FAILED: Indeed Job (1/2 checks passed)" in caplog.text
    failed_check_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "verification_check_completed"
        and getattr(record, "check_outcome", None) == "FAILED"
    )
    assert failed_check_record.check_name == "not_aggregator"
    assert failed_check_record.detail == "Aggregator site rejected: indeed.com"

    summary_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "verification_candidate_completed"
    )
    assert summary_record.verification_outcome == "FAILED"
    assert summary_record.passed_count == 1
    assert summary_record.check_count == 2
    assert isinstance(summary_record.duration_ms, int)
    assert summary_record.duration_ms >= 0


@pytest.mark.asyncio
async def test_verify_candidate_skips_content_check_when_requested(monkeypatch):
    calls = []
    monkeypatch.setattr(
        verification_pipeline,
        "CHECKS",
        [
            (
                VerificationCheckName.URL_WELLFORMED,
                make_check(calls, VerificationCheckName.URL_WELLFORMED.value),
            ),
            (
                VerificationCheckName.NOT_AGGREGATOR,
                make_check(calls, VerificationCheckName.NOT_AGGREGATOR.value),
            ),
            (
                VerificationCheckName.DNS_RESOLVES,
                make_check(calls, VerificationCheckName.DNS_RESOLVES.value),
            ),
            (
                VerificationCheckName.HTTP_REACHABLE,
                make_check(calls, VerificationCheckName.HTTP_REACHABLE.value),
            ),
            (
                VerificationCheckName.CONTENT_SIGNALS,
                make_check(calls, VerificationCheckName.CONTENT_SIGNALS.value),
            ),
        ],
    )

    passed, evidence = await verification_pipeline.verify_candidate(
        url="https://openai.com/careers",
        search_run_id=uuid.uuid4(),
        skip_content_check=True,
    )

    assert passed is True
    assert [call[0] for call in calls] == [
        "url_wellformed",
        "not_aggregator",
        "dns_resolves",
        "http_reachable",
    ]
    assert len(evidence) == 4
    assert all(
        item.check_name != VerificationCheckName.CONTENT_SIGNALS for item in evidence
    )


@pytest.mark.asyncio
async def test_verify_candidate_converts_unexpected_exceptions_to_failed_evidence(
    monkeypatch, caplog
):
    calls = []
    monkeypatch.setattr(
        verification_pipeline,
        "CHECKS",
        [
            (
                VerificationCheckName.URL_WELLFORMED,
                make_check(calls, VerificationCheckName.URL_WELLFORMED.value),
            ),
            (
                VerificationCheckName.NOT_AGGREGATOR,
                make_check(
                    calls,
                    VerificationCheckName.NOT_AGGREGATOR.value,
                    error=RuntimeError("boom"),
                ),
            ),
            (
                VerificationCheckName.DNS_RESOLVES,
                make_check(calls, VerificationCheckName.DNS_RESOLVES.value),
            ),
        ],
    )

    with caplog.at_level("ERROR"):
        passed, evidence = await verification_pipeline.verify_candidate(
            url="https://example.com/careers",
            search_run_id=uuid.uuid4(),
        )

    assert passed is False
    assert [call[0] for call in calls] == ["url_wellformed", "not_aggregator"]
    assert len(evidence) == 2
    assert evidence[1].passed is False
    assert (
        evidence[1].detail == "Unexpected error in not_aggregator: RuntimeError: boom"
    )
    assert "Verification check raised unexpectedly: not_aggregator" in caplog.text
    exception_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "verification_check_exception"
    )
    assert exception_record.check_name == "not_aggregator"
    assert exception_record.check_outcome == "FAILED"


@pytest.mark.asyncio
async def test_verify_candidates_parallel_preserves_order_and_passes_options(
    monkeypatch, caplog
):
    calls = []

    async def fake_verify_candidate(
        url: str,
        search_run_id,
        candidate_name=None,
        skip_content_check=False,
    ):
        calls.append((url, search_run_id, candidate_name, skip_content_check))
        await asyncio.sleep(0.02 if candidate_name == "slow" else 0.0)
        passed = candidate_name != "fail"
        return passed, []

    monkeypatch.setattr(
        verification_pipeline, "verify_candidate", fake_verify_candidate
    )

    candidates = [
        {"url": "https://example.com/1", "name": "slow"},
        {"url": "https://example.com/2", "name": "fail"},
        {"url": "https://example.com/3", "name": "fast"},
    ]
    search_run_id = uuid.uuid4()

    with caplog.at_level("INFO"):
        results = await verification_pipeline.verify_candidates_parallel(
            candidates=candidates,
            search_run_id=search_run_id,
            max_concurrency=3,
            skip_content_check=True,
        )

    assert [result.url for result in results] == [
        candidate["url"] for candidate in candidates
    ]
    assert [result.name for result in results] == [
        candidate["name"] for candidate in candidates
    ]
    assert [result.passed for result in results] == [True, False, True]
    assert calls == [
        ("https://example.com/1", search_run_id, "slow", True),
        ("https://example.com/2", search_run_id, "fail", True),
        ("https://example.com/3", search_run_id, "fast", True),
    ]
    assert "Parallel verification complete: 2/3 passed" in caplog.text
    batch_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "verification_batch_completed"
    )
    assert batch_record.search_run_id == str(search_run_id)
    assert batch_record.verified_count == 2
    assert batch_record.candidate_count == 3
    assert batch_record.max_concurrency == 3
    assert isinstance(batch_record.duration_ms, int)
    assert batch_record.duration_ms >= 0


@pytest.mark.asyncio
async def test_verify_candidates_parallel_converts_candidate_exceptions_to_failed_results(
    monkeypatch, caplog
):
    async def fake_verify_candidate(
        url: str,
        search_run_id,
        candidate_name=None,
        skip_content_check=False,
    ):
        if "boom" in url:
            raise RuntimeError("kaboom")
        return True, []

    monkeypatch.setattr(
        verification_pipeline, "verify_candidate", fake_verify_candidate
    )

    candidates = [
        {"url": "https://example.com/good", "name": "good"},
        {"url": "https://example.com/boom", "name": "bad"},
    ]
    search_run_id = uuid.uuid4()

    with caplog.at_level("ERROR"):
        results = await verification_pipeline.verify_candidates_parallel(
            candidates=candidates,
            search_run_id=search_run_id,
            max_concurrency=2,
        )

    assert [result.passed for result in results] == [True, False]
    failed_result = results[1]
    assert failed_result.url == "https://example.com/boom"
    assert failed_result.name == "bad"
    assert len(failed_result.evidence) == 1
    assert failed_result.evidence[0].check_name == VerificationCheckName.URL_WELLFORMED
    assert failed_result.evidence[0].passed is False
    assert (
        failed_result.evidence[0].detail
        == "Verification exception: RuntimeError: kaboom"
    )
    assert "Verification exception for https://example.com/boom" in caplog.text
    exception_record = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "verification_candidate_exception"
    )
    assert exception_record.search_run_id == str(search_run_id)
    assert exception_record.candidate_name == "bad"
    assert exception_record.candidate_url == "https://example.com/boom"
    assert exception_record.verification_outcome == "FAILED"


@pytest.mark.asyncio
async def test_verify_candidates_parallel_respects_concurrency_limit(monkeypatch):
    current_concurrency = 0
    peak_concurrency = 0

    async def fake_verify_candidate(
        url: str,
        search_run_id,
        candidate_name=None,
        skip_content_check=False,
    ):
        nonlocal current_concurrency, peak_concurrency
        current_concurrency += 1
        peak_concurrency = max(peak_concurrency, current_concurrency)
        try:
            await asyncio.sleep(0.02)
            return True, []
        finally:
            current_concurrency -= 1

    monkeypatch.setattr(
        verification_pipeline, "verify_candidate", fake_verify_candidate
    )

    candidates = [
        {"url": f"https://example.com/{index}", "name": f"candidate-{index}"}
        for index in range(6)
    ]

    results = await verification_pipeline.verify_candidates_parallel(
        candidates=candidates,
        search_run_id=uuid.uuid4(),
        max_concurrency=2,
    )

    assert len(results) == 6
    assert peak_concurrency == 2
