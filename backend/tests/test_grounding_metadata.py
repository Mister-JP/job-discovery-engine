"""Unit tests for Gemini grounding metadata helpers."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.grounding_metadata import (
    GroundingChunk,
    GroundingInfo,
    cross_reference_candidates,
    extract_grounding_info,
)


def test_extract_grounding_info_parses_queries_and_chunks():
    gemini_response = {
        "text": "{}",
        "search_queries": ["AI safety labs hiring 2026"],
        "grounding_metadata": {
            "chunks": [
                {
                    "uri": "https://anthropic.com/careers",
                    "title": "Anthropic Careers",
                },
                {
                    "uri": "https://openai.com/careers",
                    "title": "OpenAI Jobs",
                },
            ]
        },
        "error": None,
    }

    info = extract_grounding_info(gemini_response)

    assert info.has_grounding is True
    assert info.search_queries == ["AI safety labs hiring 2026"]
    assert info.chunks == [
        GroundingChunk(
            uri="https://anthropic.com/careers",
            title="Anthropic Careers",
        ),
        GroundingChunk(
            uri="https://openai.com/careers",
            title="OpenAI Jobs",
        ),
    ]
    assert info.cited_domains == {"anthropic.com", "openai.com"}
    assert info.to_dict() == {
        "has_grounding": True,
        "search_queries": ["AI safety labs hiring 2026"],
        "cited_domains": ["anthropic.com", "openai.com"],
        "chunks": [
            {
                "uri": "https://anthropic.com/careers",
                "title": "Anthropic Careers",
            },
            {
                "uri": "https://openai.com/careers",
                "title": "OpenAI Jobs",
            },
        ],
    }


def test_extract_grounding_info_handles_missing_metadata_gracefully():
    info = extract_grounding_info(
        {
            "text": "{}",
            "grounding_metadata": None,
            "search_queries": None,
            "error": None,
        }
    )

    assert info == GroundingInfo()
    assert info.to_dict() == {
        "has_grounding": False,
        "search_queries": [],
        "cited_domains": [],
        "chunks": [],
    }


def test_extract_grounding_info_ignores_invalid_chunks():
    info = extract_grounding_info(
        {
            "search_queries": ["query"],
            "grounding_metadata": {
                "chunks": [
                    {
                        "uri": "https://careers.deepmind.google/jobs",
                        "title": "DeepMind Careers",
                    },
                    None,
                    "not-a-dict",
                ]
            },
        }
    )

    assert info.has_grounding is True
    assert info.chunks == [
        GroundingChunk(
            uri="https://careers.deepmind.google/jobs",
            title="DeepMind Careers",
        )
    ]
    assert info.cited_domains == {"deepmind.google"}


def test_cross_reference_candidates_marks_grounded_domains():
    grounding_info = GroundingInfo(
        chunks=[
            GroundingChunk(
                uri="https://anthropic.com/careers", title="Anthropic Careers"
            ),
            GroundingChunk(uri="https://openai.com/careers", title="OpenAI Jobs"),
        ],
        search_queries=["AI safety labs hiring 2026"],
        has_grounding=True,
    )

    refs = cross_reference_candidates(
        grounding_info,
        [
            "https://anthropic.com/careers/researcher",
            "https://deepmind.google/careers",
            "not a real url",
        ],
    )

    assert refs == {
        "https://anthropic.com/careers/researcher": True,
        "https://deepmind.google/careers": False,
        "not a real url": False,
    }
