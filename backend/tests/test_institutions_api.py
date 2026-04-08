"""API tests for the institutions endpoint."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import BindParameter, False_, True_

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import institutions
from app.main import app
from app.models.entities import ExperienceLevel, Institution, InstitutionType, Job


class _FakeScalarResult:
    def __init__(self, institutions_):
        self._institutions = institutions_

    def all(self):
        return self._institutions


class _FakeExecuteResult:
    def __init__(self, institutions_):
        self._institutions = institutions_

    def scalars(self):
        return _FakeScalarResult(self._institutions)


class _FakeDetailExecuteResult:
    def __init__(self, institution_):
        self._institution = institution_

    def scalar_one_or_none(self):
        return self._institution


class _FakeInstitutionSession:
    def __init__(self, institutions_):
        self._institutions = institutions_
        self.observed_limits = []
        self.observed_filters = []

    async def execute(self, statement):
        order_by = statement._order_by_clauses
        assert len(order_by) == 1
        assert str(order_by[0]) == "institutions.last_seen_at DESC"

        limit = statement._limit_clause.value
        self.observed_limits.append(limit)

        filtered = list(self._institutions)
        filters = {}
        for criterion in statement._where_criteria:
            field_name = criterion.left.name
            if field_name == "is_verified":
                if isinstance(criterion.right, True_):
                    filters[field_name] = True
                elif isinstance(criterion.right, False_):
                    filters[field_name] = False
                else:
                    raise AssertionError("Unexpected boolean criterion shape")
            elif field_name == "institution_type":
                assert isinstance(criterion.right, BindParameter)
                filters[field_name] = criterion.right.value
            else:
                raise AssertionError(f"Unexpected filter field: {field_name}")

        self.observed_filters.append(filters)

        if "is_verified" in filters:
            filtered = [
                institution_
                for institution_ in filtered
                if institution_.is_verified == filters["is_verified"]
            ]

        if "institution_type" in filters:
            filtered = [
                institution_
                for institution_ in filtered
                if institution_.institution_type == filters["institution_type"]
            ]

        ordered = sorted(
            filtered,
            key=lambda institution_: institution_.last_seen_at,
            reverse=True,
        )
        return _FakeExecuteResult(ordered[:limit])


class _FakeInstitutionDetailSession:
    def __init__(self, institution_):
        self._institution = institution_
        self.observed_institution_ids = []

    async def execute(self, statement):
        params = statement.compile().params
        self.observed_institution_ids.append(next(iter(params.values())))
        return _FakeDetailExecuteResult(self._institution)


def _make_institution(
    name: str,
    domain: str,
    *,
    last_seen_at: datetime,
    institution_type: InstitutionType | None = None,
    is_verified: bool = False,
) -> Institution:
    return Institution(
        name=name,
        domain=domain,
        careers_url=f"https://{domain}/careers",
        institution_type=institution_type,
        description=f"{name} description",
        location="Chicago, IL",
        is_verified=is_verified,
        first_seen_at=last_seen_at - timedelta(days=30),
        last_seen_at=last_seen_at,
    )


def _make_job(
    institution_id,
    title: str,
    *,
    url: str,
    last_seen_at: datetime,
    experience_level: ExperienceLevel | None = None,
    location: str | None = "Chicago, IL",
    salary_range: str | None = None,
    is_active: bool = True,
    is_verified: bool = False,
) -> Job:
    return Job(
        title=title,
        url=url,
        institution_id=institution_id,
        location=location,
        experience_level=experience_level,
        salary_range=salary_range,
        is_active=is_active,
        is_verified=is_verified,
        first_seen_at=last_seen_at - timedelta(days=7),
        last_seen_at=last_seen_at,
    )


def test_list_institutions_returns_recent_results_with_default_limit():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_institutions = [
        _make_institution(
            f"Institution {index}",
            f"institution-{index}.example.com",
            last_seen_at=base_time + timedelta(minutes=index),
            institution_type=InstitutionType.COMPANY,
            is_verified=index % 2 == 0,
        )
        for index in range(150)
    ]
    fake_session = _FakeInstitutionSession(list(reversed(fake_institutions)))

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/institutions")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert fake_session.observed_limits == [100]
    assert fake_session.observed_filters == [{}]
    assert len(body) == 100
    assert body[0]["name"] == "Institution 149"
    assert body[-1]["name"] == "Institution 50"
    assert body[0]["institution_type"] == "company"
    assert body[0]["domain"] == "institution-149.example.com"


def test_list_institutions_filters_by_verified_status():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_session = _FakeInstitutionSession(
        [
            _make_institution(
                "Verified University",
                "verified.example.edu",
                last_seen_at=base_time + timedelta(minutes=3),
                institution_type=InstitutionType.UNIVERSITY,
                is_verified=True,
            ),
            _make_institution(
                "Unverified Company",
                "unverified.example.com",
                last_seen_at=base_time + timedelta(minutes=2),
                institution_type=InstitutionType.COMPANY,
                is_verified=False,
            ),
            _make_institution(
                "Verified Lab",
                "lab.example.org",
                last_seen_at=base_time + timedelta(minutes=1),
                institution_type=InstitutionType.RESEARCH_LAB,
                is_verified=True,
            ),
        ]
    )

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/institutions?verified=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == [
        "Verified University",
        "Verified Lab",
    ]
    assert fake_session.observed_filters == [{"is_verified": True}]


def test_list_institutions_filters_by_type_case_insensitively():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_session = _FakeInstitutionSession(
        [
            _make_institution(
                "Research Lab",
                "lab.example.org",
                last_seen_at=base_time + timedelta(minutes=3),
                institution_type=InstitutionType.RESEARCH_LAB,
            ),
            _make_institution(
                "University",
                "university.example.edu",
                last_seen_at=base_time + timedelta(minutes=2),
                institution_type=InstitutionType.UNIVERSITY,
            ),
            _make_institution(
                "Company",
                "company.example.com",
                last_seen_at=base_time + timedelta(minutes=1),
                institution_type=InstitutionType.COMPANY,
            ),
        ]
    )

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/institutions?type=RESEARCH_LAB")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(fake_session._institutions[0].id),
            "name": "Research Lab",
            "domain": "lab.example.org",
            "careers_url": "https://lab.example.org/careers",
            "institution_type": "research_lab",
            "description": "Research Lab description",
            "location": "Chicago, IL",
            "is_verified": False,
            "first_seen_at": "2026-03-09T12:03:00",
            "last_seen_at": "2026-04-08T12:03:00",
        }
    ]
    assert fake_session.observed_filters == [
        {"institution_type": InstitutionType.RESEARCH_LAB}
    ]


def test_list_institutions_ignores_invalid_type_filter():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_session = _FakeInstitutionSession(
        [
            _make_institution(
                "University",
                "university.example.edu",
                last_seen_at=base_time + timedelta(minutes=2),
                institution_type=InstitutionType.UNIVERSITY,
            ),
            _make_institution(
                "Company",
                "company.example.com",
                last_seen_at=base_time + timedelta(minutes=1),
                institution_type=InstitutionType.COMPANY,
            ),
        ]
    )

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/institutions?type=unknown-value")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["University", "Company"]
    assert fake_session.observed_filters == [{}]


def test_list_institutions_caps_limit_at_500():
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_institutions = [
        _make_institution(
            f"Institution {index}",
            f"institution-{index}.example.com",
            last_seen_at=base_time + timedelta(minutes=index),
            institution_type=InstitutionType.COMPANY,
        )
        for index in range(600)
    ]
    fake_session = _FakeInstitutionSession(fake_institutions)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        limited_response = client.get("/api/institutions?limit=5")
        capped_response = client.get("/api/institutions?limit=999")
    finally:
        app.dependency_overrides.clear()

    assert limited_response.status_code == 200
    assert [item["name"] for item in limited_response.json()] == [
        "Institution 599",
        "Institution 598",
        "Institution 597",
        "Institution 596",
        "Institution 595",
    ]

    assert capped_response.status_code == 200
    assert len(capped_response.json()) == 500
    assert fake_session.observed_limits == [5, 500]


def test_get_institution_detail_returns_jobs_sorted_by_last_seen_desc(monkeypatch):
    base_time = datetime(2026, 4, 8, 12, 0, 0)
    fake_institution = _make_institution(
        "Research Lab",
        "lab.example.org",
        last_seen_at=base_time,
        institution_type=InstitutionType.RESEARCH_LAB,
        is_verified=True,
    )
    fake_institution.jobs = [
        _make_job(
            fake_institution.id,
            "ML Research Engineer",
            url="https://lab.example.org/jobs/ml-research-engineer",
            last_seen_at=base_time + timedelta(hours=1),
            experience_level=ExperienceLevel.MID,
            location="Remote",
            salary_range="$140k-$180k",
            is_active=True,
            is_verified=True,
        ),
        _make_job(
            fake_institution.id,
            "Research Intern",
            url="https://lab.example.org/jobs/research-intern",
            last_seen_at=base_time + timedelta(minutes=15),
            experience_level=ExperienceLevel.INTERN,
            location=None,
            salary_range=None,
            is_active=False,
            is_verified=False,
        ),
        _make_job(
            fake_institution.id,
            "Senior Scientist",
            url="https://lab.example.org/jobs/senior-scientist",
            last_seen_at=base_time + timedelta(hours=3),
            experience_level=ExperienceLevel.SENIOR,
            location="Chicago, IL",
            salary_range="$200k+",
            is_active=True,
            is_verified=True,
        ),
    ]
    fake_session = _FakeInstitutionDetailSession(fake_institution)
    selectinload_calls = []
    real_selectinload = institutions.selectinload

    def tracking_selectinload(attribute):
        selectinload_calls.append(attribute)
        return real_selectinload(attribute)

    monkeypatch.setattr(institutions, "selectinload", tracking_selectinload)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get(f"/api/institutions/{fake_institution.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()

    assert fake_session.observed_institution_ids == [str(fake_institution.id)]
    assert selectinload_calls == [Institution.jobs]
    assert body["id"] == str(fake_institution.id)
    assert body["name"] == "Research Lab"
    assert body["domain"] == "lab.example.org"
    assert body["institution_type"] == "research_lab"
    assert body["jobs"] == [
        {
            "id": str(fake_institution.jobs[2].id),
            "title": "Senior Scientist",
            "url": "https://lab.example.org/jobs/senior-scientist",
            "location": "Chicago, IL",
            "experience_level": "senior",
            "salary_range": "$200k+",
            "is_active": True,
            "is_verified": True,
            "first_seen_at": "2026-04-01T15:00:00",
            "last_seen_at": "2026-04-08T15:00:00",
        },
        {
            "id": str(fake_institution.jobs[0].id),
            "title": "ML Research Engineer",
            "url": "https://lab.example.org/jobs/ml-research-engineer",
            "location": "Remote",
            "experience_level": "mid",
            "salary_range": "$140k-$180k",
            "is_active": True,
            "is_verified": True,
            "first_seen_at": "2026-04-01T13:00:00",
            "last_seen_at": "2026-04-08T13:00:00",
        },
        {
            "id": str(fake_institution.jobs[1].id),
            "title": "Research Intern",
            "url": "https://lab.example.org/jobs/research-intern",
            "location": None,
            "experience_level": "intern",
            "salary_range": None,
            "is_active": False,
            "is_verified": False,
            "first_seen_at": "2026-04-01T12:15:00",
            "last_seen_at": "2026-04-08T12:15:00",
        },
    ]


def test_get_institution_detail_returns_404_when_institution_is_missing():
    fake_session = _FakeInstitutionDetailSession(None)

    async def override_get_session():
        yield fake_session

    app.dependency_overrides[institutions.get_session] = override_get_session

    try:
        client = TestClient(app)
        response = client.get("/api/institutions/missing-institution")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Institution not found"}
