"""Job persistence helpers centered on normalized posting URLs.

Jobs are more volatile than institutions, so the persistence layer treats a
normalized URL as the best available identity key and uses rediscovery as a
signal that the posting is still active. As with institution merges, updates
are conservative: new observations can fill blanks and refresh freshness data
without overwriting fields that may already be higher quality.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.url_utils import normalize_url
from app.models.entities import ExperienceLevel, Job


async def upsert_job(
    session: AsyncSession,
    title: str,
    url: str,
    institution_id: UUID,
    description: Optional[str] = None,
    location: Optional[str] = None,
    experience_level: Optional[ExperienceLevel] = None,
    salary_range: Optional[str] = None,
    source_query: Optional[str] = None,
    is_verified: bool = False,
    commit: bool = True,
) -> tuple[Job, bool]:
    """Insert or merge a job record using its normalized posting URL.

    URL-based upsert prevents the same posting from being duplicated across
    repeated searches or slightly different prompt phrasings. The merge policy
    intentionally fills only missing optional fields and flips existing jobs
    back to active when rediscovered, because a live URL is stronger freshness
    evidence than the latest model-generated metadata.

    Args:
        session: Active database session participating in the current unit of
            work.
        title: Job title returned by the verified candidate.
        url: Source job posting URL to normalize and deduplicate on.
        institution_id: Parent institution that owns the job.
        description: Optional job description text.
        location: Optional job location text.
        experience_level: Optional normalized experience level.
        salary_range: Optional salary text.
        source_query: Optional search query that rediscovered this job.
        is_verified: Whether this observation came from a verified candidate.
        commit: Whether to commit immediately or only flush for batch writes.

    Returns:
        tuple[Job, bool]: The persisted job and a flag indicating whether it was
        newly created.
    """
    normalized_url = normalize_url(url)

    stmt = select(Job).where(col(Job.url) == normalized_url)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    now = datetime.utcnow()

    if existing is not None:
        existing.is_active = True
        existing.last_seen_at = now
        existing.updated_at = now

        if is_verified:
            existing.is_verified = True
            existing.last_verified_at = now
        if existing.description is None and description is not None:
            existing.description = description
        if existing.location is None and location is not None:
            existing.location = location
        if existing.experience_level is None and experience_level is not None:
            existing.experience_level = experience_level
        if existing.salary_range is None and salary_range is not None:
            existing.salary_range = salary_range
        if existing.source_query is None and source_query is not None:
            existing.source_query = source_query

        if commit:
            await session.commit()
        else:
            await session.flush()
        await session.refresh(existing)
        return existing, False

    job = Job(
        title=title,
        url=normalized_url,
        institution_id=institution_id,
        description=description,
        location=location,
        experience_level=experience_level,
        salary_range=salary_range,
        source_query=source_query,
        is_verified=is_verified,
        last_verified_at=now if is_verified else None,
    )
    session.add(job)
    if commit:
        await session.commit()
    else:
        await session.flush()
    await session.refresh(job)
    return job, True


async def get_jobs_by_institution(
    session: AsyncSession,
    institution_id: UUID,
    active_only: bool = True,
) -> list[Job]:
    """Fetch jobs for one institution in recency order.

    The institution detail view wants the freshest postings first, and the
    caller often needs the option to hide inactive jobs without re-encoding that
    filter logic at the API boundary.

    Args:
        session: Active database session used for the query.
        institution_id: Institution whose jobs should be returned.
        active_only: Whether to exclude jobs that are currently marked inactive.

    Returns:
        list[Job]: Matching jobs ordered by most recent sighting first.
    """
    stmt = select(Job).where(col(Job.institution_id) == institution_id)
    if active_only:
        stmt = stmt.where(col(Job.is_active).is_(True))
    stmt = stmt.order_by(col(Job.last_seen_at).desc())

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_jobs(
    session: AsyncSession,
    experience_level: Optional[ExperienceLevel] = None,
    limit: int = 100,
) -> list[Job]:
    """Fetch currently active jobs for feed-style API views.

    This query powers broad job browsing, so it keeps the filtering surface
    intentionally small and orders by recency to favor jobs the pipeline has
    seen live most recently.

    Args:
        session: Active database session used for the query.
        experience_level: Optional normalized experience-level filter.
        limit: Maximum number of jobs to return.

    Returns:
        list[Job]: Active jobs matching the optional filter, newest first.
    """
    stmt = select(Job).where(col(Job.is_active).is_(True))
    if experience_level is not None:
        stmt = stmt.where(col(Job.experience_level) == experience_level)
    stmt = stmt.order_by(col(Job.last_seen_at).desc()).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())
