"""API tests for the jobs endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import BindParameter, False_, True_

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import jobs
from app.main import app
from app.models.entities import ExperienceLevel, Institution, Job


class _FakeScalarResult:
    def __init__(self, jobs_):
        self._jobs = jobs_

    def all(self):
        return self._jobs


class _FakeExecuteResult:
    def __init__(self, jobs_):
        self._jobs = jobs_

    def scalars(self):
        return _FakeScalarResult(self._jobs)


class _FakeJobSession:
    def __init__(self, jobs_):
        self._jobs = jobs_
        self.observed_limits = []
        self.observed_filters = []

    async def execute(self, statement):
        order_by = statement._order_by_clauses
        assert len(order_by) == 1
        assert str(order_by[0]) == "jobs.last_seen_at DESC"

        limit = statement._limit_clause.value
        self.observed_limits.append(limit)

        filtered = list(self._jobs)
        filters = {}
        for criterion in statement._where_criteria:
            field_name = criterion.left.name
            if field_name == "is_active":
                if isinstance(criterion.right, True_):
                    filters[field_name] = True
                elif isinstance(criterion.right, False_):
                    filters[field_name] = False
                else:
                    raise AssertionError("Unexpected boolean criterion shape")
            elif field_name == "experience_level":
                assert isinstance(criterion.right, BindParameter)
                filters[field_name] = criterion.right.value
            else:
                raise AssertionError(f"Unexpected filter field: {field_name}")

        self.observed_filters.append(filters)

        if "is_active" in filters:
            filtered = [
                job for job in filtered if job.is_active == filters["is_active"]
            ]

        if "experience_level" in filters:
            filtered = [
                job
                for job in filtered
                if job.experience_level == filters["experience_level"]
            ]

        ordered = sorted(filtered, key=lambda job: job.last_seen_at, reverse=True)
        return _FakeExecuteResult(ordered[:limit])


def _make_institution(name: str, domain: str) -> Institution:
    return Institution(
        name=name,
        domain=domain,
        careers_url=f"https://{domain}/careers",
        description=f"{name} description",
        location="Chicago, IL",
        is_verified=True,
    )


def _make_job(
    institution: Institution,
    title: str,
    *,
    url: str,
    last_seen_at: datetime,
    experience_level: ExperienceLevel | None = None,
    location: str | None = "Chicago, IL",
    salary_range: str | None = None,
    is_active: bool = True,
    is_verified: bool = False,
    source_query: str | None = None,
) -> Job:
    job = Job(
        title=title,
        url=url,
        institution_id=institution.id,
        location=location,
        experience_level=experience_level,
        salary_range=salary_range,
        is_active=is_active,
        is_verified=is_verified,
        source_query=source_query,
        first_seen_at=last_seen_at - timedelta(days=7),
        last_seen_at=last_seen_at,
    )
    job.institution = institution
    return job


def test_list_jobs_returns_recent_results_with_default_limit(monkeypatch):
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_jobs = [
        _make_job(
            _make_institution(
                f"Institution {index}",
                f"institution-{index}.example.com",
            ),
            f"Role {index}",
            url=f"https://institution-{index}.example.com/jobs/{index}",
            last_seen_at=base_time + timedelta(minutes=index),
            experience_level=ExperienceLevel.ENTRY,
            salary_range="$120k-$140k",
            is_active=index % 2 == 0,
            is_verified=True,
            source_query=f"query-{index}",
        )
        for index in range(150)
    ]
    fake_session = _FakeJobSession(list(reversed(fake_jobs)))
    selectinload_calls = []
    real_selectinload = jobs.selectinload

    def tracking_selectinload(attribute):
        selectinload_calls.append(attribute)
        return real_selectinload(attribute)

    monkeypatch.setattr(jobs, "selectinload", tracking_selectinload)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[jobs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/jobs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert fake_session.observed_limits == [100]
    assert fake_session.observed_filters == [{}]
    assert selectinload_calls == [Job.institution]
    assert len(body) == 100
    assert body[0] == {
        "id": str(fake_jobs[149].id),
        "title": "Role 149",
        "url": "https://institution-149.example.com/jobs/149",
        "institution_name": "Institution 149",
        "institution_domain": "institution-149.example.com",
        "location": "Chicago, IL",
        "experience_level": "entry",
        "salary_range": "$120k-$140k",
        "is_active": False,
        "is_verified": True,
        "source_query": "query-149",
        "first_seen_at": "2026-04-01T14:29:00",
        "last_seen_at": "2026-04-08T14:29:00",
    }
    assert body[-1]["title"] == "Role 50"


def test_list_jobs_filters_by_active_status():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    institution = _make_institution("Research Lab", "lab.example.org")
    fake_session = _FakeJobSession(
        [
            _make_job(
                institution,
                "Active Research Engineer",
                url="https://lab.example.org/jobs/active-research-engineer",
                last_seen_at=base_time + timedelta(minutes=3),
                is_active=True,
            ),
            _make_job(
                institution,
                "Archived Scientist",
                url="https://lab.example.org/jobs/archived-scientist",
                last_seen_at=base_time + timedelta(minutes=2),
                is_active=False,
            ),
            _make_job(
                institution,
                "Active Intern",
                url="https://lab.example.org/jobs/active-intern",
                last_seen_at=base_time + timedelta(minutes=1),
                is_active=True,
            ),
        ]
    )

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[jobs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/jobs?is_active=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == [
        "Active Research Engineer",
        "Active Intern",
    ]
    assert fake_session.observed_filters == [{"is_active": True}]


def test_list_jobs_filters_by_experience_level_case_insensitively():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    institution = _make_institution("Frontier AI", "frontier.example.com")
    fake_session = _FakeJobSession(
        [
            _make_job(
                institution,
                "Senior Applied Scientist",
                url="https://frontier.example.com/jobs/senior-applied-scientist",
                last_seen_at=base_time + timedelta(minutes=3),
                experience_level=ExperienceLevel.SENIOR,
            ),
            _make_job(
                institution,
                "Mid-Level Engineer",
                url="https://frontier.example.com/jobs/mid-level-engineer",
                last_seen_at=base_time + timedelta(minutes=2),
                experience_level=ExperienceLevel.MID,
            ),
            _make_job(
                institution,
                "Senior ML Engineer",
                url="https://frontier.example.com/jobs/senior-ml-engineer",
                last_seen_at=base_time + timedelta(minutes=1),
                experience_level=ExperienceLevel.SENIOR,
            ),
        ]
    )

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[jobs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/jobs?experience_level=SENIOR")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == [
        "Senior Applied Scientist",
        "Senior ML Engineer",
    ]
    assert fake_session.observed_filters == [
        {"experience_level": ExperienceLevel.SENIOR}
    ]


def test_list_jobs_ignores_invalid_experience_level_filter():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    institution = _make_institution("Open Research", "open.example.org")
    fake_session = _FakeJobSession(
        [
            _make_job(
                institution,
                "Research Engineer",
                url="https://open.example.org/jobs/research-engineer",
                last_seen_at=base_time + timedelta(minutes=2),
                experience_level=ExperienceLevel.ENTRY,
            ),
            _make_job(
                institution,
                "Staff Engineer",
                url="https://open.example.org/jobs/staff-engineer",
                last_seen_at=base_time + timedelta(minutes=1),
                experience_level=ExperienceLevel.LEAD,
            ),
        ]
    )

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[jobs.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/jobs?experience_level=not-a-level")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == [
        "Research Engineer",
        "Staff Engineer",
    ]
    assert fake_session.observed_filters == [{}]


def test_list_jobs_respects_custom_limit_and_caps_at_500():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_jobs = [
        _make_job(
            _make_institution(
                f"Institution {index}",
                f"institution-{index}.example.com",
            ),
            f"Role {index}",
            url=f"https://institution-{index}.example.com/jobs/{index}",
            last_seen_at=base_time + timedelta(minutes=index),
        )
        for index in range(600)
    ]
    fake_session = _FakeJobSession(fake_jobs)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[jobs.get_session] = override_get_session

    try:
        client = TestClient(app)
        limited_response = client.get("/api/jobs?limit=5")
        capped_response = client.get("/api/jobs?limit=999")
    finally:
        app.dependency_overrides.clear()

    assert limited_response.status_code == 200
    assert [item["title"] for item in limited_response.json()] == [
        "Role 599",
        "Role 598",
        "Role 597",
        "Role 596",
        "Role 595",
    ]

    assert capped_response.status_code == 200
    assert len(capped_response.json()) == 500
    assert fake_session.observed_limits == [5, 500]
