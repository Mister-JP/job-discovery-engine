"""Unit tests for the search orchestrator."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.candidates import InstitutionCandidate, JobCandidate, SearchResult
from app.models.entities import (
    SearchRun,
    SearchRunStatus,
    VerificationCheckName,
    VerificationEvidence,
)
from app.services.grounding_metadata import GroundingChunk, GroundingInfo
from app.services.orchestrator import execute_search_run
from app.services.verification_pipeline import CandidateVerificationResult


class RecordingSession:
    """Minimal async-session stub for orchestrator tests."""

    def __init__(self):
        self.objects = []
        self.search_runs = []
        self.commit_statuses = []

    def add(self, obj):
        self.objects.append(obj)
        if isinstance(obj, SearchRun):
            self.search_runs.append(obj)

    def add_all(self, objects):
        for obj in objects:
            self.add(obj)

    async def commit(self):
        if self.search_runs:
            self.commit_statuses.append(self.search_runs[-1].status)

    async def refresh(self, _obj):
        return None

    async def flush(self):
        return None


def _make_search_result() -> SearchResult:
    return SearchResult(
        institutions=[
            InstitutionCandidate(
                name="OpenAI",
                careers_url="https://openai.com/careers",
                institution_type="company",
                description="AI research and deployment company",
                location="San Francisco, CA",
                jobs=[
                    JobCandidate(
                        title="Research Engineer",
                        url="https://openai.com/careers/research-engineer",
                        location="San Francisco, CA",
                        experience_level="mid",
                        salary_range="$200k-$300k",
                    ),
                    JobCandidate(
                        title="Research Scientist",
                        url="https://openai.com/careers/research-scientist",
                        location="Remote",
                        experience_level="senior",
                    ),
                ],
            ),
            InstitutionCandidate(
                name="Anthropic",
                careers_url="https://anthropic.com/careers",
                institution_type="research_lab",
                description="AI safety and research lab",
                location="San Francisco, CA",
                jobs=[
                    JobCandidate(
                        title="Member of Technical Staff",
                        url="https://anthropic.com/careers/mts",
                        location="San Francisco, CA",
                        experience_level="mid",
                    )
                ],
            ),
        ]
    )


@pytest.mark.asyncio
async def test_execute_search_run_completes_and_persists_metrics(monkeypatch, caplog):
    session = RecordingSession()
    search_result = _make_search_result()

    async def fake_get_all_known_domains(_session):
        return ["openai.com"]

    def fake_build_search_prompt(query, known_domains):
        assert query == "AI safety research labs hiring"
        assert known_domains == ["openai.com"]
        return "system prompt", "user message"

    async def fake_grounded_search(
        query,
        system_prompt,
        *,
        search_run_id=None,
        source_query=None,
    ):
        assert query == "user message"
        assert system_prompt == "system prompt"
        assert search_run_id is not None
        assert source_query == "AI safety research labs hiring"
        return {
            "text": '{"institutions": []}',
            "grounding_metadata": {
                "chunks": [
                    {"uri": "https://openai.com/careers", "title": "OpenAI Careers"}
                ]
            },
            "search_queries": ["ai safety labs hiring"],
            "error": None,
        }

    def fake_extract_grounding_info(_response, *, search_run_id=None, query=None):
        assert search_run_id is not None
        assert query == "AI safety research labs hiring"
        return GroundingInfo(
            chunks=[
                GroundingChunk(uri="https://openai.com/careers", title="OpenAI Careers")
            ],
            search_queries=["ai safety labs hiring"],
            has_grounding=True,
        )

    def fake_parse_gemini_response(raw_text, *, search_run_id=None, query=None):
        assert raw_text == '{"institutions": []}'
        assert search_run_id is not None
        assert query == "AI safety research labs hiring"
        return search_result, None

    async def fake_verify_candidates_parallel(candidates, search_run_id):
        assert candidates == [
            {"url": "https://openai.com/careers", "name": "OpenAI"},
            {"url": "https://anthropic.com/careers", "name": "Anthropic"},
        ]
        return [
            CandidateVerificationResult(
                url="https://openai.com/careers",
                name="OpenAI",
                passed=True,
                evidence=[
                    VerificationEvidence(
                        search_run_id=search_run_id,
                        candidate_url="https://openai.com/careers",
                        candidate_name="OpenAI",
                        check_name=VerificationCheckName.URL_WELLFORMED,
                        passed=True,
                        detail="ok",
                        duration_ms=1,
                    )
                ],
            ),
            CandidateVerificationResult(
                url="https://anthropic.com/careers",
                name="Anthropic",
                passed=True,
                evidence=[
                    VerificationEvidence(
                        search_run_id=search_run_id,
                        candidate_url="https://anthropic.com/careers",
                        candidate_name="Anthropic",
                        check_name=VerificationCheckName.URL_WELLFORMED,
                        passed=True,
                        detail="ok",
                        duration_ms=1,
                    )
                ],
            ),
        ]

    async def fake_upsert_institution(
        session,
        name,
        careers_url,
        institution_type,
        description,
        location,
        is_verified,
        commit,
    ):
        assert session is not None
        assert is_verified is True
        assert commit is False
        return SimpleNamespace(
            id=uuid.uuid4(), name=name, careers_url=careers_url
        ), name == "OpenAI"

    async def fake_upsert_job(
        session,
        title,
        url,
        institution_id,
        description,
        location,
        experience_level,
        salary_range,
        source_query,
        is_verified,
        commit,
    ):
        assert session is not None
        assert institution_id is not None
        assert source_query == "AI safety research labs hiring"
        assert is_verified is True
        assert commit is False
        return SimpleNamespace(title=title, url=url), title != "Research Scientist"

    monkeypatch.setattr(
        "app.services.orchestrator.get_all_known_domains", fake_get_all_known_domains
    )
    monkeypatch.setattr(
        "app.services.orchestrator.build_search_prompt", fake_build_search_prompt
    )
    monkeypatch.setattr(
        "app.services.orchestrator.grounded_search", fake_grounded_search
    )
    monkeypatch.setattr(
        "app.services.orchestrator.extract_grounding_info", fake_extract_grounding_info
    )
    monkeypatch.setattr(
        "app.services.orchestrator.parse_gemini_response", fake_parse_gemini_response
    )
    monkeypatch.setattr(
        "app.services.orchestrator.verify_candidates_parallel",
        fake_verify_candidates_parallel,
    )
    monkeypatch.setattr(
        "app.services.orchestrator.upsert_institution", fake_upsert_institution
    )
    monkeypatch.setattr("app.services.orchestrator.upsert_job", fake_upsert_job)

    with caplog.at_level("INFO", logger="app.services.orchestrator"):
        search_run = await execute_search_run(session, "AI safety research labs hiring")

    assert search_run.status == SearchRunStatus.COMPLETED
    assert search_run.raw_response == '{"institutions": []}'
    assert search_run.candidates_raw == 2
    assert search_run.candidates_verified == 2
    assert search_run.institutions_new == 1
    assert search_run.institutions_updated == 1
    assert search_run.jobs_new == 2
    assert search_run.jobs_updated == 1
    assert isinstance(search_run.duration_ms, int) and search_run.duration_ms >= 0
    assert session.commit_statuses == [
        SearchRunStatus.INITIATED,
        SearchRunStatus.SEARCHING,
        SearchRunStatus.VERIFYING,
        SearchRunStatus.STORING,
        SearchRunStatus.COMPLETED,
    ]
    evidence_rows = [
        obj for obj in session.objects if isinstance(obj, VerificationEvidence)
    ]
    assert len(evidence_rows) == 2
    assert [entry["stage"] for entry in search_run.pipeline_trace] == [
        "initiated",
        "known_domains_loaded",
        "prompt_built",
        "gemini_search",
        "response_parsed",
        "grounding_analyzed",
        "verification",
        "storage",
        "completed",
    ]
    verification_stage = next(
        entry for entry in search_run.pipeline_trace if entry["stage"] == "verification"
    )
    assert verification_stage["status"] == "completed"
    assert verification_stage["details"]["verified_count"] == 2
    assert verification_stage["details"]["candidate_count"] == 2

    orchestrator_records = [
        record
        for record in caplog.records
        if record.name == "app.services.orchestrator"
    ]
    initiated_record = next(
        record
        for record in orchestrator_records
        if record.getMessage() == "Search run initiated"
    )
    assert initiated_record.event == "search_initiated"
    assert initiated_record.search_run_id == str(search_run.id)
    assert initiated_record.query == "AI safety research labs hiring"

    parsed_record = next(
        record
        for record in orchestrator_records
        if record.getMessage() == "Gemini response received"
    )
    assert parsed_record.event == "gemini_response_parsed"
    assert parsed_record.candidate_count == 2
    assert parsed_record.job_count == 3

    verification_record = next(
        record
        for record in orchestrator_records
        if record.getMessage() == "Verification complete"
    )
    assert verification_record.event == "verification_complete"
    assert verification_record.verified_count == 2
    assert verification_record.candidate_count == 2
    assert isinstance(verification_record.duration_ms, int)
    assert verification_record.duration_ms >= 0

    completed_record = next(
        record
        for record in orchestrator_records
        if record.getMessage() == "Search run completed"
    )
    assert completed_record.event == "search_completed"
    assert completed_record.stored_count == 3
    assert completed_record.updated_count == 2
    assert isinstance(completed_record.duration_ms, int)
    assert completed_record.duration_ms >= 0


@pytest.mark.asyncio
async def test_execute_search_run_marks_failures_and_keeps_raw_response(
    monkeypatch, caplog
):
    session = RecordingSession()

    async def fake_get_all_known_domains(_session):
        return []

    def fake_build_search_prompt(query, known_domains):
        assert query == "bad query"
        assert known_domains == []
        return "system", "message"

    async def fake_grounded_search(
        query,
        system_prompt,
        *,
        search_run_id=None,
        source_query=None,
    ):
        assert query == "message"
        assert system_prompt == "system"
        assert search_run_id is not None
        assert source_query == "bad query"
        return {
            "text": "not valid json",
            "grounding_metadata": None,
            "search_queries": None,
            "error": None,
        }

    def fake_extract_grounding_info(_response, *, search_run_id=None, query=None):
        assert search_run_id is not None
        assert query == "bad query"
        return GroundingInfo()

    def fake_parse_gemini_response(raw_text, *, search_run_id=None, query=None):
        assert raw_text == "not valid json"
        assert search_run_id is not None
        assert query == "bad query"
        return None, "boom"

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("verification/upsert should not run after parse failure")

    monkeypatch.setattr(
        "app.services.orchestrator.get_all_known_domains", fake_get_all_known_domains
    )
    monkeypatch.setattr(
        "app.services.orchestrator.build_search_prompt", fake_build_search_prompt
    )
    monkeypatch.setattr(
        "app.services.orchestrator.grounded_search", fake_grounded_search
    )
    monkeypatch.setattr(
        "app.services.orchestrator.extract_grounding_info", fake_extract_grounding_info
    )
    monkeypatch.setattr(
        "app.services.orchestrator.parse_gemini_response", fake_parse_gemini_response
    )
    monkeypatch.setattr(
        "app.services.orchestrator.verify_candidates_parallel", fail_if_called
    )
    monkeypatch.setattr("app.services.orchestrator.upsert_institution", fail_if_called)
    monkeypatch.setattr("app.services.orchestrator.upsert_job", fail_if_called)

    with caplog.at_level("ERROR", logger="app.services.orchestrator"):
        search_run = await execute_search_run(session, "bad query")

    assert search_run.status == SearchRunStatus.FAILED
    assert search_run.raw_response == "not valid json"
    assert search_run.error_detail == "RuntimeError: Response parse error: boom"
    assert isinstance(search_run.duration_ms, int) and search_run.duration_ms >= 0
    assert session.commit_statuses == [
        SearchRunStatus.INITIATED,
        SearchRunStatus.SEARCHING,
        SearchRunStatus.FAILED,
    ]
    assert search_run.pipeline_trace[-1]["stage"] == "response_parsed"
    assert search_run.pipeline_trace[-1]["status"] == "failed"
    assert (
        search_run.pipeline_trace[-1]["details"]["error_detail"]
        == "RuntimeError: Response parse error: boom"
    )

    failed_record = next(
        record
        for record in caplog.records
        if record.name == "app.services.orchestrator"
        and record.getMessage() == "Search run failed"
    )
    assert failed_record.event == "search_failed"
    assert failed_record.search_run_id == str(search_run.id)
    assert failed_record.query == "bad query"
    assert failed_record.error_detail == "RuntimeError: Response parse error: boom"
    assert isinstance(failed_record.duration_ms, int)
    assert failed_record.duration_ms >= 0
