"""HTTP endpoints for browsing verified institutions and their jobs.

The institution API is a read-focused projection of the persistence layer. It
translates ORM entities into frontend-friendly response models while keeping
filter semantics and ordering rules consistent across clients.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import col

from app.core.database import get_session
from app.models.entities import Institution, InstitutionType

router = APIRouter(prefix="/api/institutions", tags=["institutions"])


class InstitutionResponse(BaseModel):
    """Serialized institution returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    domain: str
    careers_url: str | None
    institution_type: str | None
    description: str | None
    location: str | None
    is_verified: bool
    first_seen_at: datetime
    last_seen_at: datetime


class JobResponse(BaseModel):
    """Serialized job returned with institution details."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    url: str
    location: str | None
    experience_level: str | None
    salary_range: str | None
    is_active: bool
    is_verified: bool
    first_seen_at: datetime
    last_seen_at: datetime


class InstitutionDetailResponse(InstitutionResponse):
    """Institution with all associated job listings."""

    jobs: list[JobResponse]


@router.get("", response_model=list[InstitutionResponse])
async def list_institutions(
    verified: bool | None = Query(
        None,
        description="Filter by verification status",
    ),
    type: str | None = Query(
        None,
        description="Filter by institution type",
    ),
    limit: int = Query(100, ge=1, description="Maximum number of results to return"),
    session: AsyncSession = Depends(get_session),
) -> list[InstitutionResponse]:
    """List institutions using lightweight verification and type filters.

    The endpoint favors simple, composable filters so the frontend can build a
    browseable directory view without needing to understand the underlying data
    model or join behavior.

    Args:
        verified: Optional filter for verified vs. unverified institutions.
        type: Optional institution type filter expressed as a string enum value.
        limit: Requested maximum number of institutions, capped server-side.
        session: Request-scoped database session.

    Returns:
        list[InstitutionResponse]: Matching institutions ordered by most recent
        sighting first.
    """
    limit = min(limit, 500)

    stmt = select(Institution).order_by(col(Institution.last_seen_at).desc())

    if verified is not None:
        stmt = stmt.where(col(Institution.is_verified) == verified)

    if type:
        try:
            institution_type = InstitutionType(type.lower())
        except ValueError:
            institution_type = None

        if institution_type is not None:
            stmt = stmt.where(col(Institution.institution_type) == institution_type)

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    institutions = result.scalars().all()

    return [
        InstitutionResponse(
            id=str(institution.id),
            name=institution.name,
            domain=institution.domain,
            careers_url=institution.careers_url,
            institution_type=(
                institution.institution_type.value
                if institution.institution_type is not None
                else None
            ),
            description=institution.description,
            location=institution.location,
            is_verified=institution.is_verified,
            first_seen_at=institution.first_seen_at,
            last_seen_at=institution.last_seen_at,
        )
        for institution in institutions
    ]


@router.get("/{institution_id}", response_model=InstitutionDetailResponse)
async def get_institution_detail(
    institution_id: str,
    session: AsyncSession = Depends(get_session),
) -> InstitutionDetailResponse:
    """Return one institution together with its associated jobs.

    The detail endpoint performs the join once on the server so the frontend can
    render an institution-centric view without coordinating additional job
    queries or reapplying sort rules client-side.

    Args:
        institution_id: Identifier of the institution to retrieve.
        session: Request-scoped database session.

    Returns:
        InstitutionDetailResponse: Institution metadata and jobs ordered by
        recent sightings.

    Raises:
        HTTPException: If the institution does not exist.
    """
    stmt = (
        select(Institution)
        .where(col(Institution.id) == cast(Any, institution_id))
        .options(selectinload(cast(Any, Institution.jobs)))
    )
    result = await session.execute(stmt)
    institution = result.scalar_one_or_none()

    if institution is None:
        raise HTTPException(status_code=404, detail="Institution not found")

    jobs = [
        JobResponse(
            id=str(job.id),
            title=job.title,
            url=job.url,
            location=job.location,
            experience_level=(
                job.experience_level.value if job.experience_level is not None else None
            ),
            salary_range=job.salary_range,
            is_active=job.is_active,
            is_verified=job.is_verified,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
        )
        for job in sorted(
            institution.jobs,
            key=lambda job: job.last_seen_at,
            reverse=True,
        )
    ]

    return InstitutionDetailResponse(
        id=str(institution.id),
        name=institution.name,
        domain=institution.domain,
        careers_url=institution.careers_url,
        institution_type=(
            institution.institution_type.value
            if institution.institution_type is not None
            else None
        ),
        description=institution.description,
        location=institution.location,
        is_verified=institution.is_verified,
        first_seen_at=institution.first_seen_at,
        last_seen_at=institution.last_seen_at,
        jobs=jobs,
    )
