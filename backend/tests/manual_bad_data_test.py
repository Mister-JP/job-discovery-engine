"""Manual test that the verification pipeline rejects known-bad data.

Run with:
    python -m tests.manual_bad_data_test

This script intentionally exercises fail-fast behavior against a handful of
invalid candidates and prints the first failed check plus the evidence count
recorded before rejection.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.entities import VerificationEvidence
from app.services.verification_pipeline import verify_candidate


BAD_CANDIDATES = [
    {
        "url": "https://indeed.com/viewjob?id=abc123",
        "name": "Indeed Aggregator",
        "expected_fail_at": "not_aggregator",
        "expected_evidence_count": 2,
    },
    {
        "url": "https://totally-fake-ai-research-corp.com/careers",
        "name": "Hallucinated Domain",
        "expected_fail_at": "dns_resolves",
        "expected_evidence_count": 3,
    },
    {
        "url": "not-even-a-url",
        "name": "Malformed URL",
        "expected_fail_at": "url_wellformed",
        "expected_evidence_count": 1,
    },
    {
        "url": "https://boards.greenhouse.io/fakecompany/jobs/999",
        "name": "ATS Platform URL",
        "expected_fail_at": "not_aggregator",
        "expected_evidence_count": 2,
    },
    {
        "url": "ftp://example.com/jobs",
        "name": "Wrong Scheme (FTP)",
        "expected_fail_at": "url_wellformed",
        "expected_evidence_count": 1,
    },
]


def _first_failed_evidence(
    evidence_rows: list[VerificationEvidence],
) -> VerificationEvidence | None:
    """Return the first failed evidence row from a fail-fast run."""
    return next((row for row in evidence_rows if not row.passed), None)


async def main() -> int:
    """Run the bad-data checks and return a shell-friendly status code."""
    run_id = uuid.uuid4()
    all_correct = True

    print(f"\n{'=' * 60}")
    print("BAD DATA VERIFICATION TEST")
    print(f"Run ID: {run_id}")
    print(f"{'=' * 60}\n")

    for candidate in BAD_CANDIDATES:
        passed, evidence = await verify_candidate(
            url=candidate["url"],
            search_run_id=run_id,
            candidate_name=candidate["name"],
        )

        if passed:
            print(f"FAIL: should have been rejected: {candidate['name']}")
            print(f"  URL: {candidate['url']}")
            print(f"  Evidence records: {len(evidence)}")
            print()
            all_correct = False
            continue

        failed_check = _first_failed_evidence(evidence)
        actual_check = failed_check.check_name.value if failed_check else "unknown"
        expected_evidence_count = candidate["expected_evidence_count"]

        if actual_check == candidate["expected_fail_at"]:
            print(f"PASS: correctly rejected: {candidate['name']}")
            print(f"  Failed at: {actual_check}")
            if failed_check and failed_check.detail:
                print(f"  Reason: {failed_check.detail}")
        else:
            print(f"FAIL: rejected at wrong check: {candidate['name']}")
            print(f"  Expected fail at: {candidate['expected_fail_at']}")
            print(f"  Actually failed at: {actual_check}")
            if failed_check and failed_check.detail:
                print(f"  Reason: {failed_check.detail}")
            all_correct = False

        if len(evidence) == expected_evidence_count:
            print(f"  Evidence records: {len(evidence)}")
        else:
            print(
                "  Evidence records: "
                f"{len(evidence)} (expected {expected_evidence_count})"
            )
            all_correct = False

        if failed_check and failed_check.detail:
            pass
        else:
            print("  Missing failure detail in evidence")
            all_correct = False

        print()

    print(f"{'=' * 60}")
    if all_correct:
        print("ALL BAD DATA CORRECTLY REJECTED")
    else:
        print("SOME BAD DATA WAS NOT CAUGHT")
    print(f"{'=' * 60}")

    return 0 if all_correct else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
