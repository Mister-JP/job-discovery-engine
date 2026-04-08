"""HTTP endpoints for starting and inspecting search runs.

These handlers expose the orchestrator and its audit trail to the frontend
without leaking internal ORM objects or service-layer details. Keeping the API
surface thin but explicit makes it easier to evolve the pipeline while
preserving a stable contract for UI and debugging workflows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import col

from app.core.database import get_session
from app.models.entities import SearchRun
from app.services.orchestrator import execute_search_run

router = APIRouter(prefix="/api/search-runs", tags=["search-runs"])


class SearchRunRequest(BaseModel):
    """Request body for triggering a new search run."""

    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        examples=["AI safety labs hiring researchers"],
    )


class SearchRunResponse(BaseModel):
    """API response for a completed or failed search run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    query: str
    status: str
    candidates_raw: int
    candidates_verified: int
    institutions_new: int
    institutions_updated: int
    jobs_new: int
    jobs_updated: int
    duration_ms: int | None
    error_detail: str | None


class VerificationEvidenceResponse(BaseModel):
    """A single verification check result."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    candidate_url: str
    candidate_name: str | None
    check_name: str
    passed: bool
    detail: str | None
    duration_ms: int | None
    checked_at: datetime


class SearchRunStageResponse(BaseModel):
    """A single recorded pipeline stage for a search run."""

    stage: str
    label: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    details: dict[str, Any] = Field(default_factory=dict)


class SearchRunDetailResponse(SearchRunResponse):
    """Full search run detail with verification evidence."""

    initiated_at: datetime
    completed_at: datetime | None
    raw_response: str | None
    pipeline_trace: list[SearchRunStageResponse]
    verification_evidence: list[VerificationEvidenceResponse]


@router.get("", response_model=list[SearchRunResponse])
async def list_search_runs(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[SearchRunResponse]:
    """Return recent search runs for dashboard-style inspection.

    The endpoint intentionally caps result volume and returns a summary shape so
    the frontend can render history views cheaply without loading full evidence
    payloads for every run.

    Args:
        limit: Requested maximum number of runs, capped server-side.
        session: Request-scoped database session.

    Returns:
        list[SearchRunResponse]: Recent runs ordered from newest to oldest.
    """
    limit = min(limit, 500)

    stmt = select(SearchRun).order_by(col(SearchRun.initiated_at).desc()).limit(limit)
    result = await session.execute(stmt)
    runs = result.scalars().all()

    return [
        SearchRunResponse(
            id=str(run.id),
            query=run.query,
            status=run.status.value,
            candidates_raw=run.candidates_raw,
            candidates_verified=run.candidates_verified,
            institutions_new=run.institutions_new,
            institutions_updated=run.institutions_updated,
            jobs_new=run.jobs_new,
            jobs_updated=run.jobs_updated,
            duration_ms=run.duration_ms,
            error_detail=run.error_detail,
        )
        for run in runs
    ]


@router.get("/{run_id}", response_model=SearchRunDetailResponse)
async def get_search_run_detail(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> SearchRunDetailResponse:
    """Return one search run together with its verification evidence.

    Detailed inspection is separated from the list endpoint because evidence can
    be large, and most UI views only need summary metrics. This endpoint is the
    audit/debugging surface when a run behaved unexpectedly.

    Args:
        run_id: Identifier of the search run to retrieve.
        session: Request-scoped database session.

    Returns:
        SearchRunDetailResponse: Search run summary plus ordered evidence rows.

    Raises:
        HTTPException: If the requested search run does not exist.
    """
    stmt = (
        select(SearchRun)
        .where(col(SearchRun.id) == cast(Any, run_id))
        .options(selectinload(cast(Any, SearchRun.verification_evidence)))
    )
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail=f"SearchRun {run_id} not found")

    evidence = [
        VerificationEvidenceResponse(
            id=str(item.id),
            candidate_url=item.candidate_url,
            candidate_name=item.candidate_name,
            check_name=item.check_name.value,
            passed=item.passed,
            detail=item.detail,
            duration_ms=item.duration_ms,
            checked_at=item.checked_at,
        )
        for item in sorted(run.verification_evidence, key=lambda item: item.checked_at)
    ]
    pipeline_trace = [
        SearchRunStageResponse(**item) for item in (run.pipeline_trace or [])
    ]

    return SearchRunDetailResponse(
        id=str(run.id),
        query=run.query,
        status=run.status.value,
        initiated_at=run.initiated_at,
        completed_at=run.completed_at,
        candidates_raw=run.candidates_raw,
        candidates_verified=run.candidates_verified,
        institutions_new=run.institutions_new,
        institutions_updated=run.institutions_updated,
        jobs_new=run.jobs_new,
        jobs_updated=run.jobs_updated,
        duration_ms=run.duration_ms,
        error_detail=run.error_detail,
        raw_response=run.raw_response,
        pipeline_trace=pipeline_trace,
        verification_evidence=evidence,
    )


@router.post("", response_model=SearchRunResponse)
async def create_search_run(
    request: SearchRunRequest,
    session: AsyncSession = Depends(get_session),
) -> SearchRunResponse:
    """Trigger the orchestrator and return the resulting run summary.

    The API keeps the handler thin so orchestration logic, error handling, and
    metrics remain centralized in the service layer rather than duplicated at
    the HTTP boundary.

    Args:
        request: Search request payload containing the user query.
        session: Request-scoped database session.

    Returns:
        SearchRunResponse: Final status and summary counters for the run.
    """
    search_run = await execute_search_run(session, request.query)

    return SearchRunResponse(
        id=str(search_run.id),
        query=search_run.query,
        status=search_run.status.value,
        candidates_raw=search_run.candidates_raw,
        candidates_verified=search_run.candidates_verified,
        institutions_new=search_run.institutions_new,
        institutions_updated=search_run.institutions_updated,
        jobs_new=search_run.jobs_new,
        jobs_updated=search_run.jobs_updated,
        duration_ms=search_run.duration_ms,
        error_detail=search_run.error_detail,
    )
