"""Pipeline orchestration for candidate verification checks.

This module turns a list of individual checks into one coherent contract for
the orchestrator: candidates are verified in a cost-aware order, failures stop
further work quickly, and every attempted decision is preserved as evidence.
That separation keeps check implementations simple while making concurrency,
ordering, and auditability explicit in one place.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.core.logging_config import log_extra
from app.models.entities import VerificationCheckName, VerificationEvidence
from app.services.verification_checks import (
    check_content_signals,
    check_dns_resolves,
    check_http_reachable,
    check_not_aggregator,
    check_url_wellformed,
)

logger = logging.getLogger(__name__)

# Ordered from cheapest to most expensive. The pipeline is fail-fast, so this
# order directly affects both latency and observability.
CHECKS = [
    (VerificationCheckName.URL_WELLFORMED, check_url_wellformed),
    (VerificationCheckName.NOT_AGGREGATOR, check_not_aggregator),
    (VerificationCheckName.DNS_RESOLVES, check_dns_resolves),
    (VerificationCheckName.HTTP_REACHABLE, check_http_reachable),
    (VerificationCheckName.CONTENT_SIGNALS, check_content_signals),
]


@dataclass
class CandidateVerificationResult:
    """Normalized verification result returned to the orchestrator.

    Bundling the pass/fail flag together with evidence keeps later pipeline
    stages from re-deriving summary state and ensures storage/logging code sees
    the exact same verification outcome.
    """

    url: str
    name: Optional[str]
    passed: bool
    evidence: list[VerificationEvidence]


async def verify_candidate(
    url: str,
    search_run_id: UUID,
    candidate_name: Optional[str] = None,
    skip_content_check: bool = False,
) -> tuple[bool, list[VerificationEvidence]]:
    """Run the ordered verification pipeline for one candidate URL.

    The checks run from cheapest to most expensive and stop on first failure so
    the system avoids unnecessary network traffic and preserves the ordering
    rationale encoded in ``CHECKS``. This fail-fast behavior does mean later
    failure modes are invisible once an earlier check fails, but that tradeoff
    keeps verification latency bounded while still leaving an evidence trail for
    every attempted step.

    Args:
        url: Candidate URL to verify.
        search_run_id: Parent search run id for evidence records.
        candidate_name: Optional display name for logs and evidence.
        skip_content_check: When true, omits the most expensive heuristic check,
            which is useful for lower-cost smoke tests or targeted debugging.

    Returns:
        tuple[bool, list[VerificationEvidence]]: Overall pass/fail decision and
        the ordered evidence generated before success or first failure.
    """
    candidate_started_at = time.perf_counter()
    evidence_list: list[VerificationEvidence] = []
    all_passed = True
    name_label = candidate_name or url[:60]
    search_run_id_str = str(search_run_id)

    checks_to_run = CHECKS
    if skip_content_check:
        checks_to_run = [
            check
            for check in CHECKS
            if check[0] != VerificationCheckName.CONTENT_SIGNALS
        ]

    for check_name, check_fn in checks_to_run:
        start = time.perf_counter()

        try:
            passed, detail = await check_fn(url)
        except Exception as exc:  # pragma: no cover - exercised via unit tests
            passed = False
            detail = (
                f"Unexpected error in {check_name.value}: {type(exc).__name__}: {exc}"
            )
            logger.exception(
                "Verification check raised unexpectedly: %s",
                check_name.value,
                extra=log_extra(
                    event="verification_check_exception",
                    search_run_id=search_run_id_str,
                    candidate_name=name_label,
                    candidate_url=url,
                    check_name=check_name.value,
                    check_outcome="FAILED",
                ),
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        evidence = VerificationEvidence(
            search_run_id=search_run_id,
            candidate_url=url,
            candidate_name=candidate_name,
            check_name=check_name,
            passed=passed,
            detail=detail,
            duration_ms=duration_ms,
        )
        evidence_list.append(evidence)

        if passed:
            logger.debug(
                "  ✓ %s (%sms): %s",
                check_name.value,
                duration_ms,
                name_label,
                extra=log_extra(
                    event="verification_check_completed",
                    search_run_id=search_run_id_str,
                    candidate_name=name_label,
                    candidate_url=url,
                    check_name=check_name.value,
                    check_outcome="PASSED",
                    duration_ms=duration_ms,
                ),
            )
            continue

        logger.info(
            "  ✗ %s (%sms): %s - %s",
            check_name.value,
            duration_ms,
            name_label,
            detail,
            extra=log_extra(
                event="verification_check_completed",
                search_run_id=search_run_id_str,
                candidate_name=name_label,
                candidate_url=url,
                check_name=check_name.value,
                check_outcome="FAILED",
                detail=detail,
                duration_ms=duration_ms,
            ),
        )
        all_passed = False
        break

    passed_count = sum(1 for evidence in evidence_list if evidence.passed)
    total_count = len(evidence_list)
    total_duration_ms = int((time.perf_counter() - candidate_started_at) * 1000)
    logger.info(
        "Verification %s: %s (%s/%s checks passed)",
        "PASSED" if all_passed else "FAILED",
        name_label,
        passed_count,
        total_count,
        extra=log_extra(
            event="verification_candidate_completed",
            search_run_id=search_run_id_str,
            candidate_name=name_label,
            candidate_url=url,
            verification_outcome="PASSED" if all_passed else "FAILED",
            passed_count=passed_count,
            check_count=total_count,
            duration_ms=total_duration_ms,
        ),
    )

    return all_passed, evidence_list


async def verify_candidates_parallel(
    candidates: list[dict],
    search_run_id: UUID,
    max_concurrency: int = 15,
    skip_content_check: bool = False,
) -> list[CandidateVerificationResult]:
    """Verify many candidates concurrently while preserving result order.

    Search runs often contain enough institutions that sequential verification
    would dominate total latency, so this function parallelizes candidate-level
    work behind a semaphore. Preserving input order lets the orchestrator zip
    results back to parsed candidates without adding fragile identifier-matching
    logic, while exception wrapping ensures one bad task does not abort the
    entire run.

    Args:
        candidates: Candidate dictionaries containing at least a ``url`` key.
        search_run_id: Parent search run id for generated evidence.
        max_concurrency: Upper bound on simultaneous candidate verifications.
        skip_content_check: Whether to omit the final heuristic content check
            for every candidate in this batch.

    Returns:
        list[CandidateVerificationResult]: One ordered result per input
        candidate, including synthesized failure evidence when a task crashes.

    Raises:
        ValueError: If ``max_concurrency`` is less than 1.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    search_run_id_str = str(search_run_id)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _verify_with_semaphore(candidate: dict) -> CandidateVerificationResult:
        async with semaphore:
            url = candidate["url"]
            name = candidate.get("name")
            passed, evidence = await verify_candidate(
                url=url,
                search_run_id=search_run_id,
                candidate_name=name,
                skip_content_check=skip_content_check,
            )
            return CandidateVerificationResult(
                url=url,
                name=name,
                passed=passed,
                evidence=evidence,
            )

    start = time.perf_counter()
    tasks = [_verify_with_semaphore(candidate) for candidate in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    duration_ms = int((time.perf_counter() - start) * 1000)

    processed_results: list[CandidateVerificationResult] = []
    for index, result in enumerate(results):
        if isinstance(result, BaseException):
            candidate = candidates[index]
            url = candidate.get("url", "<missing-url>")
            name = candidate.get("name")
            logger.exception(
                "Verification exception for %s",
                url,
                exc_info=result,
                extra=log_extra(
                    event="verification_candidate_exception",
                    search_run_id=search_run_id_str,
                    candidate_name=name,
                    candidate_url=url,
                    verification_outcome="FAILED",
                ),
            )
            processed_results.append(
                CandidateVerificationResult(
                    url=url,
                    name=name,
                    passed=False,
                    evidence=[
                        VerificationEvidence(
                            search_run_id=search_run_id,
                            candidate_url=url,
                            candidate_name=name,
                            check_name=VerificationCheckName.URL_WELLFORMED,
                            passed=False,
                            detail=(
                                f"Verification exception: {type(result).__name__}: {result}"
                            ),
                            duration_ms=0,
                        )
                    ],
                )
            )
            continue

        processed_results.append(result)

    passed_count = sum(1 for result in processed_results if result.passed)
    total_count = len(processed_results)
    logger.info(
        "Parallel verification complete: %s/%s passed in %sms (concurrency=%s)",
        passed_count,
        total_count,
        duration_ms,
        max_concurrency,
        extra=log_extra(
            event="verification_batch_completed",
            search_run_id=search_run_id_str,
            verified_count=passed_count,
            candidate_count=total_count,
            duration_ms=duration_ms,
            max_concurrency=max_concurrency,
        ),
    )

    return processed_results
