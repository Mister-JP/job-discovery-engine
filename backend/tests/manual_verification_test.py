"""Manual integration test for the verification pipeline.

Run with:
    python -m tests.manual_verification_test

This script exercises the full verification pipeline against live URLs that
cover the expected scenarios:
1. A direct careers page that should pass all checks
2. A malformed URL
3. An aggregator URL
4. A hallucinated / non-resolving domain
5. A reachable URL that returns HTTP 404
6. A reachable non-job page that fails content analysis
7. A URL that redirects to a login page

It is intentionally not part of the automated test suite because it requires
live network access and site behavior may drift over time.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.entities import VerificationCheckName, VerificationEvidence
from app.services.verification_pipeline import (
    CHECKS,
    verify_candidate,
    verify_candidates_parallel,
)


CHECK_ORDER = [check_name for check_name, _ in CHECKS]


@dataclass(frozen=True)
class ManualCase:
    """A single manual verification scenario."""

    name: str
    url: str
    expected_passed: bool
    expected_failure_check: VerificationCheckName | None = None
    expected_detail_substring: str | None = None


PASS_CANDIDATES = [
    {
        "url": "https://www.figma.com/careers/",
        "name": "Figma Careers (should PASS)",
    },
    {
        "url": "https://www.datadoghq.com/careers/",
        "name": "Datadog Careers (should PASS)",
    },
    {
        "url": "https://www.salesforce.com/company/careers/",
        "name": "Salesforce Careers (should PASS)",
    },
]


STATIC_TEST_CASES = [
    ManualCase(
        name="Malformed URL (should FAIL at wellformed)",
        url="not-a-url-at-all",
        expected_passed=False,
        expected_failure_check=VerificationCheckName.URL_WELLFORMED,
        expected_detail_substring="missing scheme",
    ),
    ManualCase(
        name="LinkedIn Job (AGGREGATOR — should FAIL)",
        url="https://www.linkedin.com/jobs/view/12345",
        expected_passed=False,
        expected_failure_check=VerificationCheckName.NOT_AGGREGATOR,
        expected_detail_substring="Aggregator site rejected",
    ),
    ManualCase(
        name="Hallucinated Domain (should FAIL at DNS)",
        url="https://careers.this-domain-should-not-exist-2026.invalid/jobs",
        expected_passed=False,
        expected_failure_check=VerificationCheckName.DNS_RESOLVES,
        expected_detail_substring="DNS resolution failed",
    ),
    ManualCase(
        name="HTTP 404 page (should FAIL at HTTP)",
        url="https://www.figma.com/this-path-should-not-exist-xyz",
        expected_passed=False,
        expected_failure_check=VerificationCheckName.HTTP_REACHABLE,
        expected_detail_substring="HTTP 404",
    ),
    ManualCase(
        name="Non-job page (should FAIL at content_signals)",
        url="https://www.figma.com/blog/",
        expected_passed=False,
        expected_failure_check=VerificationCheckName.CONTENT_SIGNALS,
        expected_detail_substring="signals found",
    ),
    ManualCase(
        name="Redirect-to-login page (should FAIL at content_signals)",
        url="https://www.figma.com/files/recent/",
        expected_passed=False,
        expected_failure_check=VerificationCheckName.CONTENT_SIGNALS,
        expected_detail_substring="redirected to https://www.figma.com/login",
    ),
]


def _first_failed_check(
    evidence: list[VerificationEvidence],
) -> VerificationCheckName | None:
    """Return the first failed check name, if any."""
    for item in evidence:
        if not item.passed:
            return item.check_name
    return None


def _expected_evidence_count(case: ManualCase) -> int:
    """Expected evidence count for a fail-fast pipeline result."""
    if case.expected_failure_check is None:
        return len(CHECK_ORDER)
    return CHECK_ORDER.index(case.expected_failure_check) + 1


def _format_evidence(evidence: list[VerificationEvidence]) -> list[str]:
    """Render evidence rows for the terminal."""
    rows: list[str] = []
    for item in evidence:
        icon = "PASS" if item.passed else "FAIL"
        detail = (item.detail or "").replace("\n", " ").strip()
        rows.append(
            f"    {icon:<4} {item.check_name.value:<16} "
            f"({item.duration_ms:>4}ms) {detail[:110]}"
        )
    return rows


def _compare_to_expectation(
    case: ManualCase,
    passed: bool,
    evidence: list[VerificationEvidence],
) -> list[str]:
    """Return a list of validation errors for a case."""
    errors: list[str] = []
    failed_check = _first_failed_check(evidence)
    expected_evidence = _expected_evidence_count(case)

    if passed != case.expected_passed:
        errors.append(f"expected passed={case.expected_passed}, got {passed}")

    if failed_check != case.expected_failure_check:
        errors.append(
            "expected failure check="
            f"{case.expected_failure_check.value if case.expected_failure_check else None}, "
            f"got {failed_check.value if failed_check else None}"
        )

    if len(evidence) != expected_evidence:
        errors.append(
            f"expected {expected_evidence} evidence rows, got {len(evidence)}"
        )

    if case.expected_detail_substring:
        details = " | ".join(item.detail or "" for item in evidence)
        if case.expected_detail_substring.lower() not in details.lower():
            errors.append(
                f"expected detail containing {case.expected_detail_substring!r}"
            )

    return errors


async def _select_pass_case() -> tuple[
    ManualCase, list[tuple[dict, bool, list[VerificationEvidence]]]
]:
    """Choose the first known-good careers page that passes all checks."""
    probe_run_id = uuid.uuid4()
    attempts: list[tuple[dict, bool, list[VerificationEvidence]]] = []

    for candidate in PASS_CANDIDATES:
        passed, evidence = await verify_candidate(
            url=candidate["url"],
            search_run_id=probe_run_id,
            candidate_name=candidate["name"],
        )
        attempts.append((candidate, passed, evidence))
        if passed:
            return (
                ManualCase(
                    name=candidate["name"],
                    url=candidate["url"],
                    expected_passed=True,
                ),
                attempts,
            )

    fallback = PASS_CANDIDATES[0]
    return (
        ManualCase(
            name=fallback["name"],
            url=fallback["url"],
            expected_passed=True,
        ),
        attempts,
    )


async def main() -> int:
    """Run the manual verification test suite and return an exit status."""
    run_id = uuid.uuid4()
    pass_case, pass_attempts = await _select_pass_case()
    test_cases = [pass_case, *STATIC_TEST_CASES]

    print(f"\n{'=' * 78}")
    print("VERIFICATION PIPELINE MANUAL TEST")
    print(f"Run ID: {run_id}")
    print(f"{'=' * 78}\n")

    print("=== Pass Candidate Selection ===\n")
    for candidate, passed, evidence in pass_attempts:
        status = (
            "SELECTED" if candidate["url"] == pass_case.url and passed else "SKIPPED"
        )
        if candidate["url"] == pass_case.url and not passed:
            status = "FAILED"
        failed_check = _first_failed_check(evidence)
        print(
            f"  {status:<8} {candidate['name']}: "
            f"{'PASS' if passed else 'FAIL'}"
            f"{f' at {failed_check.value}' if failed_check else ''}"
        )
        for row in _format_evidence(evidence):
            print(row)
        print()

    print("=== Sequential Verification ===\n")
    sequential_results: list[
        tuple[ManualCase, bool, list[VerificationEvidence], list[str]]
    ] = []
    sequential_start = time.perf_counter()
    for case in test_cases:
        passed, evidence = await verify_candidate(
            url=case.url,
            search_run_id=run_id,
            candidate_name=case.name,
        )
        errors = _compare_to_expectation(case, passed, evidence)
        sequential_results.append((case, passed, evidence, errors))

        status = "PASS" if passed else "FAIL"
        match = "OK" if not errors else "UNEXPECTED"
        print(f"  {status:<4} [{match:<10}] {case.name}")
        print(f"         URL: {case.url}")
        for row in _format_evidence(evidence):
            print(row)
        if errors:
            for error in errors:
                print(f"    ERROR {error}")
        print()

    sequential_elapsed = time.perf_counter() - sequential_start
    sequential_matches = sum(1 for _, _, _, errors in sequential_results if not errors)
    sequential_evidence_count = sum(
        len(evidence) for _, _, evidence, _ in sequential_results
    )
    print(
        f"Sequential matches: {sequential_matches}/{len(sequential_results)} "
        f"in {sequential_elapsed:.1f}s"
    )
    print(f"Sequential evidence records: {sequential_evidence_count}\n")

    print("=== Parallel Verification ===\n")
    candidates = [{"url": case.url, "name": case.name} for case in test_cases]
    parallel_start = time.perf_counter()
    parallel_results = await verify_candidates_parallel(
        candidates=candidates,
        search_run_id=run_id,
        max_concurrency=min(10, len(candidates)),
    )
    parallel_elapsed = time.perf_counter() - parallel_start
    parallel_evidence_count = sum(len(result.evidence) for result in parallel_results)

    parallel_errors: list[str] = []
    for (
        case,
        sequential_passed,
        sequential_evidence,
        sequential_case_errors,
    ) in sequential_results:
        result = parallel_results[
            candidates.index({"url": case.url, "name": case.name})
        ]
        sequential_failed_check = _first_failed_check(sequential_evidence)
        parallel_failed_check = _first_failed_check(result.evidence)
        sequential_checks = [item.check_name for item in sequential_evidence]
        parallel_checks = [item.check_name for item in result.evidence]

        status = "PASS" if result.passed else "FAIL"
        comparison_errors: list[str] = []
        if sequential_passed != result.passed:
            comparison_errors.append(
                f"parallel passed={result.passed}, sequential passed={sequential_passed}"
            )
        if parallel_failed_check != sequential_failed_check:
            comparison_errors.append(
                "parallel failure check="
                f"{parallel_failed_check.value if parallel_failed_check else None}, "
                f"sequential failure check="
                f"{sequential_failed_check.value if sequential_failed_check else None}"
            )
        if parallel_checks != sequential_checks:
            comparison_errors.append(
                f"parallel checks={parallel_checks}, sequential checks={sequential_checks}"
            )
        if sequential_case_errors:
            comparison_errors.append("sequential case already mismatched expectation")

        print(
            f"  {status:<4} [{'OK' if not comparison_errors else 'MISMATCH':<10}] {case.name}"
        )
        print(f"         URL: {case.url}")
        for row in _format_evidence(result.evidence):
            print(row)
        if comparison_errors:
            parallel_errors.extend(
                f"{case.name}: {error}" for error in comparison_errors
            )
            for error in comparison_errors:
                print(f"    ERROR {error}")
        print()

    print(
        f"Parallel results: {sum(1 for result in parallel_results if result.passed)}/"
        f"{len(parallel_results)} passed in {parallel_elapsed:.1f}s"
    )
    print(f"Parallel evidence records: {parallel_evidence_count}")

    failures: list[str] = []
    for case, _, _, errors in sequential_results:
        failures.extend(f"{case.name}: {error}" for error in errors)
    failures.extend(parallel_errors)

    print(f"\n{'=' * 78}")
    if failures:
        print("PIPELINE TEST FAILED")
        for failure in failures:
            print(f"  - {failure}")
        print(f"{'=' * 78}")
        return 1

    print("PIPELINE TEST PASSED")
    print("Phase 3 verification behavior matched expectations across all scenarios.")
    print(f"{'=' * 78}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
