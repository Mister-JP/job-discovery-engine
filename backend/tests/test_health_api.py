"""API tests for the health endpoint."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import TextClause

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import health
from app.main import app
from app.models.entities import SearchRun, SearchRunStatus


class _FakeExecuteResult:
    def __init__(self, run: SearchRun | None):
        self._run = run

    def scalar_one_or_none(self) -> SearchRun | None:
        return self._run


class _FakeHealthSession:
    def __init__(
        self,
        *,
        last_run: SearchRun | None = None,
        database_error: Exception | None = None,
        last_run_error: Exception | None = None,
    ):
        self.last_run = last_run
        self.database_error = database_error
        self.last_run_error = last_run_error
        self.calls = []

    async def execute(self, statement):
        self.calls.append(statement)

        if isinstance(statement, TextClause):
            assert str(statement) == "SELECT 1"
            if self.database_error is not None:
                raise self.database_error
            return object()

        order_by = statement._order_by_clauses
        assert len(order_by) == 1
        assert str(order_by[0]) == "search_runs.completed_at DESC"
        assert statement._limit_clause.value == 1

        criteria = list(statement._where_criteria)
        assert len(criteria) == 1
        assert criteria[0].left.name == "status"
        assert criteria[0].right.value == SearchRunStatus.COMPLETED

        if self.last_run_error is not None:
            raise self.last_run_error

        return _FakeExecuteResult(self.last_run)


def _make_search_run(*, query: str, completed_at: datetime) -> SearchRun:
    return SearchRun(
        query=query,
        status=SearchRunStatus.COMPLETED,
        completed_at=completed_at,
    )


def test_health_endpoint_returns_dependency_status_for_healthy_system(monkeypatch):
    completed_at = datetime(2026, 4, 7, 9, 30, 0)
    fake_session = _FakeHealthSession(
        last_run=_make_search_run(
            query="AI safety research jobs",
            completed_at=completed_at,
        ),
    )

    async def override_get_session():
        yield fake_session

    async def fake_check_gemini_health():
        return True

    monkeypatch.setattr(health, "check_gemini_health", fake_check_gemini_health)
    app.dependency_overrides[health.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "database": {"status": "connected", "healthy": True},
        "gemini_api": {"status": "reachable", "healthy": True},
        "last_successful_run": {
            "timestamp": completed_at.isoformat(),
            "query": "AI safety research jobs",
            "healthy": True,
        },
    }
    assert len(fake_session.calls) == 2


def test_health_endpoint_degrades_when_gemini_is_unreachable(monkeypatch):
    fake_session = _FakeHealthSession(last_run=None)

    async def override_get_session():
        yield fake_session

    async def fake_check_gemini_health():
        return False

    monkeypatch.setattr(health, "check_gemini_health", fake_check_gemini_health)
    app.dependency_overrides[health.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": {"status": "connected", "healthy": True},
        "gemini_api": {"status": "unreachable", "healthy": False},
        "last_successful_run": {
            "timestamp": None,
            "query": None,
            "healthy": True,
            "note": "No search runs completed yet",
        },
    }


def test_health_endpoint_handles_dependency_exceptions_gracefully(monkeypatch):
    fake_session = _FakeHealthSession(
        database_error=RuntimeError("database offline"),
        last_run_error=RuntimeError("search history unavailable"),
    )

    async def override_get_session():
        yield fake_session

    async def fake_check_gemini_health():
        raise RuntimeError("gemini timeout")

    monkeypatch.setattr(health, "check_gemini_health", fake_check_gemini_health)
    app.dependency_overrides[health.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": {"status": "error: database offline", "healthy": False},
        "gemini_api": {"status": "error: gemini timeout", "healthy": False},
        "last_successful_run": {
            "status": "error: search history unavailable",
            "healthy": False,
        },
    }
