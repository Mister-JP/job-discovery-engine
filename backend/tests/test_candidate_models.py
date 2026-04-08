"""Unit tests for Gemini candidate response models."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.candidates import InstitutionCandidate, JobCandidate, SearchResult


def test_search_result_counts_and_collects_all_urls():
    result = SearchResult(
        institutions=[
            InstitutionCandidate(
                name="OpenAI",
                careers_url="https://openai.com/careers",
                institution_type="company",
                jobs=[
                    JobCandidate(
                        title="Research Engineer",
                        url="https://openai.com/careers/research-engineer",
                        experience_level="mid",
                    )
                ],
            )
        ]
    )

    assert result.total_institutions == 1
    assert result.total_jobs == 1
    assert result.all_urls() == [
        "https://openai.com/careers",
        "https://openai.com/careers/research-engineer",
    ]


def test_job_candidate_normalizes_experience_level_and_url():
    job = JobCandidate(
        title="Test Role",
        url="example.com/job",
        experience_level="INVALID",
    )

    assert job.experience_level == "unknown"
    assert job.url == "https://example.com/job"


def test_institution_candidate_normalizes_type_and_careers_url():
    institution = InstitutionCandidate(
        name="Example Org",
        careers_url="example.org/careers",
        institution_type="NOT-A-TYPE",
    )

    assert institution.institution_type == "other"
    assert institution.careers_url == "https://example.org/careers"


def test_required_fields_are_enforced():
    with pytest.raises(ValueError):
        JobCandidate(title="", url="https://example.com/job")
