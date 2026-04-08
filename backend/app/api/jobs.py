"""HTTP endpoints for browsing discovered job postings.

The jobs API exposes a flattened, feed-like view of postings that already exist
in the persistence layer. It keeps filtering and institution join behavior on
the server so clients can stay simple and consistent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import col

from app.core.database import get_session
from app.models.entities import ExperienceLevel, Job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobListResponse(BaseModel):
    """Serialized job returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    url: str
    institution_name: str
    institution_domain: str
    location: str | None
    experience_level: str | None
    salary_range: str | None
    is_active: bool
    is_verified: bool
    source_query: str | None
    first_seen_at: datetime
    last_seen_at: datetime


@router.get("", response_model=list[JobListResponse])
async def list_jobs(
    is_active: bool | None = Query(None, description="Filter by active status"),
    experience_level: str | None = Query(
        None,
        description="Filter by experience level",
    ),
    limit: int = Query(100, ge=1, description="Maximum number of results to return"),
    session: AsyncSession = Depends(get_session),
) -> list[JobListResponse]:
    """List jobs with lightweight filters for feed and search views.

    The endpoint intentionally supports only the filters the current UI needs,
    which keeps the query predictable and the response shape stable while still
    letting users focus on active roles or a rough experience band.

    Args:
        is_active: Optional filter for active vs. inactive jobs.
        experience_level: Optional experience-level filter expressed as a string
            enum value.
        limit: Requested maximum number of jobs, capped server-side.
        session: Request-scoped database session.

    Returns:
        list[JobListResponse]: Matching jobs ordered by most recent sighting
        first.
    """
    limit = min(limit, 500)

    stmt = (
        select(Job)
        .options(selectinload(cast(Any, Job.institution)))
        .order_by(col(Job.last_seen_at).desc())
    )

    if is_active is not None:
        stmt = stmt.where(col(Job.is_active) == is_active)

    if experience_level:
        try:
            level = ExperienceLevel(experience_level.lower())
        except ValueError:
            level = None

        if level is not None:
            stmt = stmt.where(col(Job.experience_level) == level)

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    jobs = result.scalars().all()

    return [
        JobListResponse(
            id=str(job.id),
            title=job.title,
            url=job.url,
            institution_name=(
                job.institution.name if job.institution is not None else "Unknown"
            ),
            institution_domain=(
                job.institution.domain if job.institution is not None else ""
            ),
            location=job.location,
            experience_level=(
                job.experience_level.value if job.experience_level is not None else None
            ),
            salary_range=job.salary_range,
            is_active=job.is_active,
            is_verified=job.is_verified,
            source_query=job.source_query,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
        )
        for job in jobs
    ]
