"""Integration-oriented API smoke tests for the main backend endpoints."""

from __future__ import annotations

from datetime import datetime
import json

from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import TextClause

from app.api import health, institutions, jobs, search_runs
from app.main import app
from app.models.entities import (
    ExperienceLevel,
    Institution,
    InstitutionType,
    Job,
    SearchRun,
    SearchRunStatus,
)
from tests.conftest import MOCK_GEMINI_RESPONSE

client = TestClient(app)


def _session_override(session):
    async def override():
        yield session

    return override


class _ListResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _SingleResult:
    def __init__(self, item):
        self._item = item

    def scalar_one_or_none(self):
        return self._item


class _FakeHealthSession:
    def __init__(self, last_run: SearchRun | None):
        self._last_run = last_run

    async def execute(self, statement):
        if isinstance(statement, TextClause):
            return object()
        return _SingleResult(self._last_run)


class _FakeListSession:
    def __init__(self, items):
        self._items = items

    async def execute(self, _statement):
        return _ListResult(self._items)


class _FakeDetailSession:
    def __init__(self, item):
        self._item = item

    async def execute(self, _statement):
        return _SingleResult(self._item)


class TestHealthEndpoint:
    def test_health_returns_200(self, monkeypatch):
        fake_run = SearchRun(
            query="test search query",
            status=SearchRunStatus.COMPLETED,
            completed_at=datetime(2026, 4, 8, 12, 0, 0),
        )

        async def fake_check_gemini_health():
            return True

        monkeypatch.setattr(health, "check_gemini_health", fake_check_gemini_health)
        app.dependency_overrides[health.get_session] = _session_override(
            _FakeHealthSession(fake_run)
        )

        try:
            response = client.get("/api/health")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"]["healthy"] is True
        assert data["gemini_api"]["healthy"] is True

    def test_root_returns_200(self):
        response = client.get("/")

        assert response.status_code == 200
        assert response.json()["message"] == "Job Discovery Engine API"


class TestSearchRunsEndpoint:
    def test_list_runs_empty(self):
        app.dependency_overrides[search_runs.get_session] = _session_override(
            _FakeListSession([])
        )

        try:
            response = client.get("/api/search-runs")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == []

    def test_create_search_run(self, monkeypatch):
        payload = json.loads(MOCK_GEMINI_RESPONSE["text"])
        institution = payload["institutions"][0]

        fake_run = SearchRun(
            query="test search query",
            status=SearchRunStatus.COMPLETED,
            candidates_raw=len(payload["institutions"]),
            candidates_verified=1,
            institutions_new=1,
            institutions_updated=0,
            jobs_new=len(institution["jobs"]),
            jobs_updated=0,
            duration_ms=250,
        )

        async def fake_execute_search_run(session, query):
            assert session is not None
            assert query == "test search query"
            return fake_run

        monkeypatch.setattr(search_runs, "execute_search_run", fake_execute_search_run)
        app.dependency_overrides[search_runs.get_session] = _session_override(object())

        try:
            response = client.post(
                "/api/search-runs",
                json={"query": "test search query"},
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "test search query"
        assert data["status"] == "completed"
        assert data["candidates_raw"] == 1
        assert data["jobs_new"] == 1

    def test_create_search_run_short_query(self):
        app.dependency_overrides[search_runs.get_session] = _session_override(object())

        try:
            response = client.post("/api/search-runs", json={"query": "ab"})
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422


class TestInstitutionsEndpoint:
    def test_list_institutions(self):
        institution = Institution(
            name="TestCorp AI",
            domain="testcorp-ai.example.com",
            careers_url="https://testcorp-ai.example.com/careers",
            institution_type=InstitutionType.COMPANY,
            is_verified=True,
            first_seen_at=datetime(2026, 4, 1, 12, 0, 0),
            last_seen_at=datetime(2026, 4, 8, 12, 0, 0),
        )
        app.dependency_overrides[institutions.get_session] = _session_override(
            _FakeListSession([institution])
        )

        try:
            response = client.get("/api/institutions")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()[0]["name"] == "TestCorp AI"

    def test_list_institutions_with_filters(self):
        institution = Institution(
            name="Verified Company",
            domain="verified-company.example.com",
            careers_url="https://verified-company.example.com/careers",
            institution_type=InstitutionType.COMPANY,
            is_verified=True,
            first_seen_at=datetime(2026, 4, 1, 12, 0, 0),
            last_seen_at=datetime(2026, 4, 8, 12, 0, 0),
        )
        app.dependency_overrides[institutions.get_session] = _session_override(
            _FakeListSession([institution])
        )

        try:
            response = client.get("/api/institutions?verified=true&type=company")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200

    def test_institution_not_found(self):
        app.dependency_overrides[institutions.get_session] = _session_override(
            _FakeDetailSession(None)
        )

        try:
            response = client.get(
                "/api/institutions/00000000-0000-0000-0000-000000000000"
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404


class TestJobsEndpoint:
    def test_list_jobs(self):
        institution = Institution(
            name="TestCorp AI",
            domain="testcorp-ai.example.com",
            careers_url="https://testcorp-ai.example.com/careers",
            institution_type=InstitutionType.COMPANY,
            is_verified=True,
            first_seen_at=datetime(2026, 4, 1, 12, 0, 0),
            last_seen_at=datetime(2026, 4, 8, 12, 0, 0),
        )
        job = Job(
            title="ML Engineer",
            url="https://testcorp-ai.example.com/careers/ml-eng-1",
            institution_id=institution.id,
            experience_level=ExperienceLevel.ENTRY,
            is_active=True,
            is_verified=True,
            first_seen_at=datetime(2026, 4, 1, 12, 0, 0),
            last_seen_at=datetime(2026, 4, 8, 12, 0, 0),
        )
        job.institution = institution
        app.dependency_overrides[jobs.get_session] = _session_override(
            _FakeListSession([job])
        )

        try:
            response = client.get("/api/jobs")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()[0]["title"] == "ML Engineer"

    def test_list_jobs_with_filters(self):
        institution = Institution(
            name="TestCorp AI",
            domain="testcorp-ai.example.com",
            careers_url="https://testcorp-ai.example.com/careers",
            institution_type=InstitutionType.COMPANY,
            is_verified=True,
            first_seen_at=datetime(2026, 4, 1, 12, 0, 0),
            last_seen_at=datetime(2026, 4, 8, 12, 0, 0),
        )
        job = Job(
            title="Entry ML Engineer",
            url="https://testcorp-ai.example.com/careers/ml-eng-entry",
            institution_id=institution.id,
            experience_level=ExperienceLevel.ENTRY,
            is_active=True,
            is_verified=True,
            first_seen_at=datetime(2026, 4, 1, 12, 0, 0),
            last_seen_at=datetime(2026, 4, 8, 12, 0, 0),
        )
        job.institution = institution
        app.dependency_overrides[jobs.get_session] = _session_override(
            _FakeListSession([job])
        )

        try:
            response = client.get("/api/jobs?is_active=true&experience_level=entry")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
