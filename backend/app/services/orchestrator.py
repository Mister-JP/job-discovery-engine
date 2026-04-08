"""End-to-end orchestration for search, verification, and persistence.

This module is the pipeline's control plane: it sequences Gemini discovery,
grounding extraction, response parsing, verification, storage, and metrics
updates into one auditable search run. Concentrating that workflow here keeps
failure handling and status transitions consistent instead of scattering them
across API handlers and lower-level services.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import log_extra
from app.models.entities import (
    ExperienceLevel,
    InstitutionType,
    SearchRun,
    SearchRunStatus,
)
from app.services.gemini_client import grounded_search
from app.services.grounding_metadata import (
    cross_reference_candidates,
    extract_grounding_info,
)
from app.services.institution_service import get_all_known_domains, upsert_institution
from app.services.job_service import upsert_job
from app.services.prompt_builder import build_search_prompt
from app.services.response_parser import parse_gemini_response
from app.services.verification_pipeline import verify_candidates_parallel

logger = logging.getLogger(__name__)


def _json_ready(value: Any) -> Any:
    """Convert trace metadata into JSON-serializable primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _json_ready(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value


def _trace_details(**kwargs: Any) -> dict[str, Any]:
    """Drop empty values and normalize nested trace metadata."""
    return {
        key: _json_ready(value) for key, value in kwargs.items() if value is not None
    }


def _append_pipeline_stage(
    search_run: SearchRun,
    *,
    stage: str,
    label: str,
    status: str,
    started_at: datetime,
    completed_at: datetime | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one persistent pipeline stage record to the search run."""
    finished_at = completed_at or datetime.utcnow()
    duration_ms = max(
        int((finished_at - started_at).total_seconds() * 1000),
        0,
    )
    entry = {
        "stage": stage,
        "label": label,
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": finished_at.isoformat(),
        "duration_ms": duration_ms,
        "details": _trace_details(**(details or {})),
    }
    search_run.pipeline_trace = [*(search_run.pipeline_trace or []), entry]
    return entry


def _log_pipeline_stage(
    *,
    search_run_id: str,
    entry: dict[str, Any],
) -> None:
    """Emit a structured log line for one pipeline stage transition."""
    logger.info(
        "Search stage completed",
        extra=log_extra(
            event="search_stage_completed",
            search_run_id=search_run_id,
            stage=entry["stage"],
            stage_label=entry["label"],
            stage_status=entry["status"],
            duration_ms=entry["duration_ms"],
            **entry["details"],
        ),
    )


def _verification_trace_details(all_evidence: list) -> dict[str, Any]:
    """Aggregate verification evidence into debugging-friendly summary stats."""
    failure_counts: dict[str, int] = {}
    duration_buckets: dict[str, list[int]] = {}

    for evidence in all_evidence:
        check_name = evidence.check_name.value
        if evidence.duration_ms is not None:
            duration_buckets.setdefault(check_name, []).append(evidence.duration_ms)
        if not evidence.passed:
            failure_counts[check_name] = failure_counts.get(check_name, 0) + 1

    check_timing_ms = {
        check_name: {
            "count": len(durations),
            "avg": round(sum(durations) / len(durations), 1),
            "max": max(durations),
        }
        for check_name, durations in duration_buckets.items()
        if durations
    }

    slowest_check_name = None
    slowest_check_avg = None
    if check_timing_ms:
        slowest_check_name, slowest_bucket = max(
            check_timing_ms.items(),
            key=lambda item: item[1]["avg"],
        )
        slowest_check_avg = slowest_bucket["avg"]

    return _trace_details(
        failure_counts=failure_counts or None,
        check_timing_ms=check_timing_ms or None,
        slowest_check=(
            {
                "check_name": slowest_check_name,
                "avg_duration_ms": slowest_check_avg,
            }
            if slowest_check_name is not None
            else None
        ),
    )


async def execute_search_run(
    session: AsyncSession,
    query: str,
) -> SearchRun:
    """Execute one full discovery run from prompt building to persistence.

    The stages are intentionally ordered as: create audit record, load known
    domains, call Gemini, parse and inspect grounding, verify institution URLs,
    then persist verified institutions/jobs. That order preserves observability
    at every stage, avoids storing unverified data, and lets the run fail with a
    meaningful status regardless of whether the problem was model, parsing,
    verification, or database related. Metrics are collected incrementally on
    the ``SearchRun`` record so partially successful runs still leave useful
    counts, durations, and raw model output behind for debugging.

    Args:
        session: Active database session that will own the entire search run.
        query: User search query describing the hiring targets to discover.

    Returns:
        SearchRun: Completed or failed search run populated with counts, timing,
        raw response text, and error detail when applicable.
    """
    start_time = time.perf_counter()

    search_run = SearchRun(query=query, status=SearchRunStatus.INITIATED)
    _append_pipeline_stage(
        search_run,
        stage="initiated",
        label="Search run created",
        status="completed",
        started_at=search_run.initiated_at,
        completed_at=search_run.initiated_at,
        details={"query": query},
    )
    session.add(search_run)
    await session.commit()
    await session.refresh(search_run)
    run_id = search_run.id
    run_id_str = str(run_id)

    current_stage_name: str | None = None
    current_stage_label: str | None = None
    current_stage_started_at: datetime | None = None

    logger.info(
        "Search run initiated",
        extra=log_extra(
            event="search_initiated",
            search_run_id=run_id_str,
            query=query,
        ),
    )

    try:
        current_stage_name = "known_domains_loaded"
        current_stage_label = "Load known domains"
        current_stage_started_at = datetime.utcnow()
        known_domains = await get_all_known_domains(session)
        known_domains_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={"known_domain_count": len(known_domains)},
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=known_domains_stage)
        logger.info(
            "Known domains loaded",
            extra=log_extra(
                event="known_domains_loaded",
                search_run_id=run_id_str,
                query=query,
                known_domain_count=len(known_domains),
                duration_ms=known_domains_stage["duration_ms"],
            ),
        )
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        search_run.status = SearchRunStatus.SEARCHING
        await session.commit()

        current_stage_name = "prompt_built"
        current_stage_label = "Build Gemini prompt"
        current_stage_started_at = datetime.utcnow()
        system_prompt, user_message = build_search_prompt(
            query=query,
            known_domains=known_domains,
        )
        prompt_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={
                "known_domain_count": len(known_domains),
                "user_message_chars": len(user_message),
                "system_prompt_chars": len(system_prompt),
            },
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=prompt_stage)
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        current_stage_name = "gemini_search"
        current_stage_label = "Call Gemini grounded search"
        current_stage_started_at = datetime.utcnow()
        gemini_response = await grounded_search(
            query=user_message,
            system_prompt=system_prompt,
            search_run_id=run_id_str,
            source_query=query,
        )
        if gemini_response["error"]:
            raise RuntimeError(str(gemini_response["error"]))

        raw_response = str(gemini_response.get("text") or "")
        search_queries = cast(list[str] | None, gemini_response.get("search_queries"))
        grounding_metadata = cast(
            dict[str, list[dict[str, str | None]]] | None,
            gemini_response.get("grounding_metadata"),
        )
        search_run.raw_response = raw_response
        gemini_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={
                "response_chars": len(raw_response),
                "search_query_count": len(search_queries or []),
                "citation_count": len((grounding_metadata or {}).get("chunks") or []),
            },
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=gemini_stage)
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        current_stage_name = "response_parsed"
        current_stage_label = "Parse Gemini response"
        current_stage_started_at = datetime.utcnow()
        grounding_info = extract_grounding_info(
            gemini_response,
            search_run_id=run_id_str,
            query=query,
        )
        search_result, parse_error = parse_gemini_response(
            raw_response,
            search_run_id=run_id_str,
            query=query,
        )
        if parse_error or search_result is None:
            raise RuntimeError(f"Response parse error: {parse_error}")

        search_run.candidates_raw = search_result.total_institutions
        parse_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={
                "candidate_count": search_result.total_institutions,
                "job_count": search_result.total_jobs,
            },
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=parse_stage)
        logger.info(
            "Gemini response received",
            extra=log_extra(
                event="gemini_response_parsed",
                search_run_id=run_id_str,
                query=query,
                candidate_count=search_result.total_institutions,
                job_count=search_result.total_jobs,
                duration_ms=parse_stage["duration_ms"],
            ),
        )
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        current_stage_name = "grounding_analyzed"
        current_stage_label = "Analyze grounding metadata"
        current_stage_started_at = datetime.utcnow()
        grounded_count = 0
        grounded_candidates: dict[str, bool] = {}
        if grounding_info.has_grounding:
            grounded_candidates = cross_reference_candidates(
                grounding_info,
                search_result.all_urls(),
                search_run_id=run_id_str,
                query=query,
            )
            grounded_count = sum(1 for value in grounded_candidates.values() if value)
            logger.info(
                "Grounding metadata cross-referenced",
                extra=log_extra(
                    event="grounding_cross_referenced",
                    search_run_id=run_id_str,
                    query=query,
                    search_query_count=len(grounding_info.search_queries),
                    citation_count=len(grounding_info.chunks),
                    grounded_count=grounded_count,
                    candidate_count=len(grounded_candidates),
                ),
            )
        grounding_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={
                "has_grounding": grounding_info.has_grounding,
                "search_queries": grounding_info.search_queries or None,
                "search_query_count": len(grounding_info.search_queries),
                "citation_count": len(grounding_info.chunks),
                "cited_domains": sorted(grounding_info.cited_domains) or None,
                "grounded_count": grounded_count if grounding_info.has_grounding else 0,
                "candidate_count": len(grounded_candidates)
                if grounding_info.has_grounding
                else 0,
            },
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=grounding_stage)
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        search_run.status = SearchRunStatus.VERIFYING
        await session.commit()

        verification_candidates = [
            {"url": institution.careers_url, "name": institution.name}
            for institution in search_result.institutions
        ]
        current_stage_name = "verification"
        current_stage_label = "Verify candidate URLs"
        current_stage_started_at = datetime.utcnow()
        verification_started_at = time.perf_counter()
        verification_results = await verify_candidates_parallel(
            candidates=verification_candidates,
            search_run_id=run_id,
        )
        verification_duration_ms = int(
            (time.perf_counter() - verification_started_at) * 1000
        )

        all_evidence = [
            evidence
            for verification_result in verification_results
            for evidence in verification_result.evidence
        ]
        if all_evidence:
            session.add_all(all_evidence)

        search_run.candidates_verified = sum(
            1
            for verification_result in verification_results
            if verification_result.passed
        )
        verification_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={
                "candidate_count": len(verification_results),
                "verified_count": search_run.candidates_verified,
                "rejected_count": len(verification_results)
                - search_run.candidates_verified,
                "evidence_count": len(all_evidence),
                "batch_duration_ms": verification_duration_ms,
                **_verification_trace_details(all_evidence),
            },
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=verification_stage)
        logger.info(
            "Verification complete",
            extra=log_extra(
                event="verification_complete",
                search_run_id=run_id_str,
                query=query,
                verified_count=search_run.candidates_verified,
                candidate_count=len(verification_results),
                duration_ms=verification_duration_ms,
            ),
        )
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        search_run.status = SearchRunStatus.STORING
        await session.commit()

        institutions_new = 0
        institutions_updated = 0
        jobs_new = 0
        jobs_updated = 0

        current_stage_name = "storage"
        current_stage_label = "Persist verified results"
        current_stage_started_at = datetime.utcnow()
        for institution_candidate, verification_result in zip(
            search_result.institutions,
            verification_results,
            strict=True,
        ):
            if not verification_result.passed:
                continue

            try:
                institution_type = InstitutionType(
                    institution_candidate.institution_type
                )
            except ValueError:
                institution_type = InstitutionType.OTHER

            institution, is_new_institution = await upsert_institution(
                session=session,
                name=institution_candidate.name,
                careers_url=institution_candidate.careers_url,
                institution_type=institution_type,
                description=institution_candidate.description,
                location=institution_candidate.location,
                is_verified=True,
                commit=False,
            )

            if is_new_institution:
                institutions_new += 1
            else:
                institutions_updated += 1

            for job_candidate in institution_candidate.jobs:
                try:
                    experience_level = ExperienceLevel(job_candidate.experience_level)
                except ValueError:
                    experience_level = ExperienceLevel.UNKNOWN

                _, is_new_job = await upsert_job(
                    session=session,
                    title=job_candidate.title,
                    url=job_candidate.url,
                    institution_id=institution.id,
                    description=None,
                    location=job_candidate.location,
                    experience_level=experience_level,
                    salary_range=job_candidate.salary_range,
                    source_query=query,
                    is_verified=True,
                    commit=False,
                )

                if is_new_job:
                    jobs_new += 1
                else:
                    jobs_updated += 1

        search_run.institutions_new = institutions_new
        search_run.institutions_updated = institutions_updated
        search_run.jobs_new = jobs_new
        search_run.jobs_updated = jobs_updated
        search_run.status = SearchRunStatus.COMPLETED
        search_run.completed_at = datetime.utcnow()
        search_run.duration_ms = int((time.perf_counter() - start_time) * 1000)

        stored_count = institutions_new + jobs_new
        updated_count = institutions_updated + jobs_updated
        storage_stage = _append_pipeline_stage(
            search_run,
            stage=current_stage_name,
            label=current_stage_label,
            status="completed",
            started_at=current_stage_started_at,
            details={
                "stored_count": stored_count,
                "updated_count": updated_count,
                "institution_new_count": institutions_new,
                "institution_updated_count": institutions_updated,
                "job_new_count": jobs_new,
                "job_updated_count": jobs_updated,
            },
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=storage_stage)
        current_stage_name = None
        current_stage_label = None
        current_stage_started_at = None

        completion_stage = _append_pipeline_stage(
            search_run,
            stage="completed",
            label="Search run finished",
            status="completed",
            started_at=search_run.completed_at,
            completed_at=search_run.completed_at,
            details={"total_duration_ms": search_run.duration_ms},
        )
        _log_pipeline_stage(search_run_id=run_id_str, entry=completion_stage)

        await session.commit()
        await session.refresh(search_run)

        logger.info(
            "Results stored",
            extra=log_extra(
                event="search_results_stored",
                search_run_id=run_id_str,
                query=query,
                stored_count=stored_count,
                updated_count=updated_count,
                institution_new_count=institutions_new,
                institution_updated_count=institutions_updated,
                job_new_count=jobs_new,
                job_updated_count=jobs_updated,
                duration_ms=storage_stage["duration_ms"],
            ),
        )
        logger.info(
            "Search run completed",
            extra=log_extra(
                event="search_completed",
                search_run_id=run_id_str,
                query=query,
                duration_ms=search_run.duration_ms,
                stored_count=stored_count,
                updated_count=updated_count,
                institution_new_count=institutions_new,
                institution_updated_count=institutions_updated,
                job_new_count=jobs_new,
                job_updated_count=jobs_updated,
            ),
        )
        return search_run
    except Exception as exc:
        search_run.status = SearchRunStatus.FAILED
        search_run.error_detail = f"{type(exc).__name__}: {exc}"
        search_run.completed_at = datetime.utcnow()
        search_run.duration_ms = int((time.perf_counter() - start_time) * 1000)
        failed_stage_name = current_stage_name or "search_run"
        failed_stage_label = current_stage_label or "Search run execution"
        failed_stage_started_at = current_stage_started_at or search_run.initiated_at
        failure_stage = _append_pipeline_stage(
            search_run,
            stage=failed_stage_name,
            label=failed_stage_label,
            status="failed",
            started_at=failed_stage_started_at,
            completed_at=search_run.completed_at,
            details={"error_detail": search_run.error_detail},
        )
        await session.commit()
        await session.refresh(search_run)

        logger.error(
            "Search stage failed",
            extra=log_extra(
                event="search_stage_failed",
                search_run_id=run_id_str,
                stage=failed_stage_name,
                stage_label=failed_stage_label,
                stage_status="failed",
                duration_ms=failure_stage["duration_ms"],
                error_detail=search_run.error_detail,
            ),
        )
        logger.exception(
            "Search run failed",
            extra=log_extra(
                event="search_failed",
                search_run_id=run_id_str,
                query=query,
                duration_ms=search_run.duration_ms,
                failed_stage=failed_stage_name,
                error_detail=search_run.error_detail,
            ),
        )
        return search_run
