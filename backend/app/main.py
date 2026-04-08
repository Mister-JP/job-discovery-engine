"""FastAPI application entrypoint for the Job Discovery Engine."""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.institutions import router as institutions_router
from app.api.jobs import router as jobs_router
from app.api.search_runs import router as search_runs_router
from app.core.logging_config import log_extra, setup_logging

setup_logging()

logger = logging.getLogger("app.middleware")

app = FastAPI(
    title="Job Discovery Engine",
    description="AI-assisted job discovery with verified results",
    version="0.1.0",
)

# Allow React frontend to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request with structured timing metadata."""
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.exception(
            "HTTP request failed",
            extra=log_extra(
                event="http_request_failed",
                method=request.method,
                path=request.url.path,
                query_string=request.url.query or None,
                duration_ms=duration_ms,
            ),
        )
        raise

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "HTTP request completed",
        extra=log_extra(
            event="http_request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        ),
    )
    return response


app.include_router(search_runs_router)
app.include_router(institutions_router)
app.include_router(jobs_router)
app.include_router(health_router)


@app.get("/")
async def root():
    return {"message": "Job Discovery Engine API", "version": "0.1.0"}
