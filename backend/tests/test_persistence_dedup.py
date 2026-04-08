"""Regression tests for persistence-layer deduplication behavior."""

from pathlib import Path
import sys

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.entities import ExperienceLevel, Institution, InstitutionType, Job
from app.services.institution_service import upsert_institution
from app.services.job_service import upsert_job


class AsyncSessionAdapter:
    """Small async wrapper around a synchronous SQLModel session for unit tests."""

    def __init__(self, session: Session):
        self.sync_session = session

    def add(self, obj):
        self.sync_session.add(obj)

    def add_all(self, objects):
        self.sync_session.add_all(list(objects))

    async def execute(self, statement):
        return self.sync_session.execute(statement)

    async def commit(self):
        self.sync_session.commit()

    async def flush(self):
        self.sync_session.flush()

    async def refresh(self, obj):
        self.sync_session.refresh(obj)


@pytest.fixture
def session() -> AsyncSessionAdapter:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as sync_session:
        yield AsyncSessionAdapter(sync_session)


@pytest.mark.asyncio
async def test_upsert_institution_deduplicates_www_variants_and_refreshes_last_seen(
    session: AsyncSessionAdapter,
):
    institution, created = await upsert_institution(
        session=session,
        name="OpenAI",
        careers_url="https://www.openai.com/careers/",
        institution_type=InstitutionType.COMPANY,
        is_verified=False,
    )
    first_id = institution.id
    first_last_seen = institution.last_seen_at

    rediscovered, created_again = await upsert_institution(
        session=session,
        name="OpenAI",
        careers_url="https://openai.com/careers",
        institution_type=InstitutionType.COMPANY,
        is_verified=True,
    )

    institutions = session.sync_session.exec(select(Institution)).all()

    assert created is True
    assert created_again is False
    assert rediscovered.id == first_id
    assert len(institutions) == 1
    assert rediscovered.domain == "openai.com"
    assert rediscovered.careers_url == "https://openai.com/careers"
    assert rediscovered.is_verified is True
    assert rediscovered.last_seen_at >= first_last_seen


@pytest.mark.asyncio
async def test_upsert_job_deduplicates_tracking_params_and_refreshes_last_seen(
    session: AsyncSessionAdapter,
):
    institution = Institution(
        name="Example",
        domain="example.com",
        institution_type=InstitutionType.COMPANY,
    )
    session.add(institution)
    await session.commit()
    await session.refresh(institution)

    job, created = await upsert_job(
        session=session,
        title="Software Engineer",
        url="https://jobs.example.com/roles/123?utm_source=google&role=engineer",
        institution_id=institution.id,
        location="Remote",
        experience_level=ExperienceLevel.MID,
        source_query="first query",
        is_verified=False,
    )
    first_id = job.id
    first_last_seen = job.last_seen_at

    rediscovered, created_again = await upsert_job(
        session=session,
        title="Software Engineer",
        url="https://jobs.example.com/roles/123?role=engineer&utm_medium=cpc&fbclid=abc123",
        institution_id=institution.id,
        location="Remote",
        experience_level=ExperienceLevel.MID,
        source_query="second query",
        is_verified=True,
    )

    jobs = session.sync_session.exec(select(Job)).all()

    assert created is True
    assert created_again is False
    assert rediscovered.id == first_id
    assert len(jobs) == 1
    assert rediscovered.url == "https://jobs.example.com/roles/123?role=engineer"
    assert rediscovered.is_verified is True
    assert rediscovered.last_seen_at >= first_last_seen
