"""API tests for the search-runs endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import search_runs
from app.main import app
from app.models.entities import (
    SearchRun,
    SearchRunStatus,
    VerificationCheckName,
    VerificationEvidence,
)


async def _override_get_session():
    yield object()


class _FakeScalarResult:
    def __init__(self, runs):
        self._runs = runs

    def all(self):
        return self._runs


class _FakeExecuteResult:
    def __init__(self, runs):
        self._runs = runs

    def scalars(self):
        return _FakeScalarResult(self._runs)


class _FakeListSession:
    def __init__(self, runs):
        self._runs = runs
        self.observed_limits = []

    async def execute(self, statement):
        order_by = statement._order_by_clauses
        assert len(order_by) == 1
        assert str(order_by[0]) == "search_runs.initiated_at DESC"

        limit = statement._limit_clause.value
        self.observed_limits.append(limit)

        ordered_runs = sorted(
            self._runs,
            key=lambda run: run.initiated_at,
            reverse=True,
        )
        return _FakeExecuteResult(ordered_runs[:limit])


class _FakeDetailExecuteResult:
    def __init__(self, run):
        self._run = run

    def scalar_one_or_none(self):
        return self._run


class _FakeDetailSession:
    def __init__(self, run):
        self._run = run
        self.observed_run_ids = []

    async def execute(self, statement):
        params = statement.compile().params
        self.observed_run_ids.append(next(iter(params.values())))
        return _FakeDetailExecuteResult(self._run)


def _make_search_run(index: int, initiated_at: datetime) -> SearchRun:
    return SearchRun(
        query=f"query-{index}",
        status=SearchRunStatus.COMPLETED,
        initiated_at=initiated_at,
        candidates_raw=index,
        candidates_verified=max(index - 1, 0),
        institutions_new=index % 3,
        institutions_updated=index % 2,
        jobs_new=index + 1,
        jobs_updated=index // 2,
        duration_ms=index * 10,
        error_detail=None,
    )


def _make_verification_evidence(
    search_run_id,
    candidate_url: str,
    check_name: VerificationCheckName,
    checked_at: datetime,
    *,
    candidate_name: str | None = None,
    passed: bool = True,
    detail: str | None = None,
    duration_ms: int | None = None,
) -> VerificationEvidence:
    return VerificationEvidence(
        search_run_id=search_run_id,
        candidate_url=candidate_url,
        candidate_name=candidate_name,
        check_name=check_name,
        passed=passed,
        detail=detail,
        duration_ms=duration_ms,
        checked_at=checked_at,
    )


def test_create_search_run_returns_orchestrator_metrics(monkeypatch):
    fake_search_run = SearchRun(
        query="AI safety labs hiring",
        status=SearchRunStatus.COMPLETED,
        candidates_raw=4,
        candidates_verified=3,
        institutions_new=2,
        institutions_updated=1,
        jobs_new=5,
        jobs_updated=2,
        duration_ms=1234,
        error_detail=None,
    )

    async def fake_execute_search_run(session, query):
        assert session is not None
        assert query == "AI safety labs hiring"
        return fake_search_run

    monkeypatch.setattr(search_runs, "execute_search_run", fake_execute_search_run)
    app.dependency_overrides[search_runs.get_session] = _override_get_session

    try:
        client = TestClient(app)
        response = client.post(
            "/api/search-runs",
            json={"query": "AI safety labs hiring"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "id": str(fake_search_run.id),
        "query": "AI safety labs hiring",
        "status": "completed",
        "candidates_raw": 4,
        "candidates_verified": 3,
        "institutions_new": 2,
        "institutions_updated": 1,
        "jobs_new": 5,
        "jobs_updated": 2,
        "duration_ms": 1234,
        "error_detail": None,
    }


def test_list_search_runs_returns_recent_runs_with_default_limit():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_runs = [
        _make_search_run(index, base_time + timedelta(minutes=index))
        for index in range(150)
    ]
    fake_session = _FakeListSession(list(reversed(fake_runs)))

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[search_runs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/search-runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert fake_session.observed_limits == [100]
    assert len(body) == 100
    assert body[0]["query"] == "query-149"
    assert body[-1]["query"] == "query-50"
    assert body[0]["candidates_raw"] == 149
    assert body[0]["status"] == "completed"


def test_list_search_runs_respects_custom_limit_and_caps_at_500():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_runs = [
        _make_search_run(index, base_time + timedelta(minutes=index))
        for index in range(600)
    ]
    fake_session = _FakeListSession(fake_runs)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[search_runs.get_session] = override_get_session

    try:
        client = TestClient(app)
        limited_response = client.get("/api/search-runs?limit=5")
        capped_response = client.get("/api/search-runs?limit=999")
    finally:
        app.dependency_overrides.clear()

    assert limited_response.status_code == 200
    assert [item["query"] for item in limited_response.json()] == [
        "query-599",
        "query-598",
        "query-597",
        "query-596",
        "query-595",
    ]

    assert capped_response.status_code == 200
    assert len(capped_response.json()) == 500
    assert fake_session.observed_limits == [5, 500]


def test_list_search_runs_returns_empty_list_when_no_runs_exist():
    fake_session = _FakeListSession([])

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[search_runs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/search-runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_get_search_run_detail_returns_full_detail_sorted_by_checked_at(monkeypatch):
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_run = SearchRun(
        query="AI safety faculty jobs",
        status=SearchRunStatus.COMPLETED,
        initiated_at=base_time,
        completed_at=base_time + timedelta(minutes=4),
        candidates_raw=3,
        candidates_verified=2,
        institutions_new=1,
        institutions_updated=1,
        jobs_new=4,
        jobs_updated=1,
        duration_ms=240000,
        error_detail=None,
        raw_response='{"institutions": []}',
    )
    fake_run.pipeline_trace = [
        {
            "stage": "initiated",
            "label": "Search run created",
            "status": "completed",
            "started_at": "2026-04-08T12:00:00",
            "completed_at": "2026-04-08T12:00:00",
            "duration_ms": 0,
            "details": {"query": "AI safety faculty jobs"},
        },
        {
            "stage": "verification",
            "label": "Verify candidate URLs",
            "status": "completed",
            "started_at": "2026-04-08T12:02:00",
            "completed_at": "2026-04-08T12:03:00",
            "duration_ms": 60000,
            "details": {
                "candidate_count": 3,
                "verified_count": 2,
                "rejected_count": 1,
            },
        },
    ]
    fake_run.verification_evidence = [
        _make_verification_evidence(
            fake_run.id,
            "https://gamma.example/careers",
            VerificationCheckName.HTTP_REACHABLE,
            base_time + timedelta(seconds=30),
            candidate_name="Gamma Lab",
            passed=True,
            detail="200 OK",
            duration_ms=220,
        ),
        _make_verification_evidence(
            fake_run.id,
            "https://alpha.example/jobs",
            VerificationCheckName.URL_WELLFORMED,
            base_time + timedelta(seconds=10),
            candidate_name="Alpha University",
            passed=True,
            detail="Valid HTTPS URL",
            duration_ms=5,
        ),
        _make_verification_evidence(
            fake_run.id,
            "https://alpha.example/jobs",
            VerificationCheckName.CONTENT_SIGNALS,
            base_time + timedelta(seconds=20),
            candidate_name="Alpha University",
            passed=False,
            detail="No careers keywords found",
            duration_ms=120,
        ),
    ]
    fake_session = _FakeDetailSession(fake_run)
    selectinload_calls = []
    real_selectinload = search_runs.selectinload

    def tracking_selectinload(attribute):
        selectinload_calls.append(attribute)
        return real_selectinload(attribute)

    monkeypatch.setattr(search_runs, "selectinload", tracking_selectinload)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[search_runs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get(f"/api/search-runs/{fake_run.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert fake_session.observed_run_ids == [str(fake_run.id)]
    assert selectinload_calls == [SearchRun.verification_evidence]
    assert body["id"] == str(fake_run.id)
    assert body["query"] == "AI safety faculty jobs"
    assert body["status"] == "completed"
    assert body["initiated_at"] == "2026-04-08T12:00:00"
    assert body["completed_at"] == "2026-04-08T12:04:00"
    assert body["raw_response"] == '{"institutions": []}'
    assert body["pipeline_trace"] == [
        {
            "stage": "initiated",
            "label": "Search run created",
            "status": "completed",
            "started_at": "2026-04-08T12:00:00",
            "completed_at": "2026-04-08T12:00:00",
            "duration_ms": 0,
            "details": {"query": "AI safety faculty jobs"},
        },
        {
            "stage": "verification",
            "label": "Verify candidate URLs",
            "status": "completed",
            "started_at": "2026-04-08T12:02:00",
            "completed_at": "2026-04-08T12:03:00",
            "duration_ms": 60000,
            "details": {
                "candidate_count": 3,
                "verified_count": 2,
                "rejected_count": 1,
            },
        },
    ]
    assert body["verification_evidence"] == [
        {
            "id": str(fake_run.verification_evidence[1].id),
            "candidate_url": "https://alpha.example/jobs",
            "candidate_name": "Alpha University",
            "check_name": "url_wellformed",
            "passed": True,
            "detail": "Valid HTTPS URL",
            "duration_ms": 5,
            "checked_at": "2026-04-08T12:00:10",
        },
        {
            "id": str(fake_run.verification_evidence[2].id),
            "candidate_url": "https://alpha.example/jobs",
            "candidate_name": "Alpha University",
            "check_name": "content_signals",
            "passed": False,
            "detail": "No careers keywords found",
            "duration_ms": 120,
            "checked_at": "2026-04-08T12:00:20",
        },
        {
            "id": str(fake_run.verification_evidence[0].id),
            "candidate_url": "https://gamma.example/careers",
            "candidate_name": "Gamma Lab",
            "check_name": "http_reachable",
            "passed": True,
            "detail": "200 OK",
            "duration_ms": 220,
            "checked_at": "2026-04-08T12:00:30",
        },
    ]


def test_get_search_run_detail_returns_404_when_run_is_missing():
    fake_session = _FakeDetailSession(None)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[search_runs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/search-runs/missing-run")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert fake_session.observed_run_ids == ["missing-run"]
    assert response.json() == {"detail": "SearchRun missing-run not found"}
