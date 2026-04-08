"""Health check endpoint for system observability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.database import get_session
from app.models.entities import SearchRun, SearchRunStatus
from app.services.gemini_client import check_gemini_health

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Serialized system health response."""

    status: str
    database: dict[str, Any]
    gemini_api: dict[str, Any]
    last_successful_run: dict[str, Any]


def _format_error_status(exc: Exception) -> str:
    """Return a short, JSON-safe error description for health responses."""
    return f"error: {str(exc)[:100]}"


@router.get("/api/health", response_model=HealthResponse)
async def health_check(
    session: AsyncSession = Depends(get_session),
) -> HealthResponse:
    """Return dependency health for the database, Gemini, and search history."""
    checks: dict[str, dict[str, Any]] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = {"status": "connected", "healthy": True}
    except Exception as exc:
        checks["database"] = {
            "status": _format_error_status(exc),
            "healthy": False,
        }

    try:
        gemini_healthy = await check_gemini_health()
        checks["gemini_api"] = {
            "status": "reachable" if gemini_healthy else "unreachable",
            "healthy": gemini_healthy,
        }
    except Exception as exc:
        checks["gemini_api"] = {
            "status": _format_error_status(exc),
            "healthy": False,
        }

    try:
        stmt = (
            select(SearchRun)
            .where(col(SearchRun.status) == SearchRunStatus.COMPLETED)
            .order_by(col(SearchRun.completed_at).desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        last_run = result.scalar_one_or_none()

        if last_run is None:
            checks["last_successful_run"] = {
                "timestamp": None,
                "query": None,
                "healthy": True,
                "note": "No search runs completed yet",
            }
        else:
            checks["last_successful_run"] = {
                "timestamp": (
                    last_run.completed_at.isoformat()
                    if last_run.completed_at is not None
                    else None
                ),
                "query": last_run.query,
                "healthy": True,
            }
    except Exception as exc:
        checks["last_successful_run"] = {
            "status": _format_error_status(exc),
            "healthy": False,
        }

    overall_healthy = all(check.get("healthy") is True for check in checks.values())

    return HealthResponse(
        status="healthy" if overall_healthy else "degraded",
        database=checks["database"],
        gemini_api=checks["gemini_api"],
        last_successful_run=checks["last_successful_run"],
    )
