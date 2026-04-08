"""Shared pytest fixtures and configuration for backend tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


MOCK_GEMINI_RESPONSE = {
    "text": json.dumps(
        {
            "institutions": [
                {
                    "name": "TestCorp AI",
                    "careers_url": "https://testcorp-ai.example.com/careers",
                    "institution_type": "company",
                    "description": "AI research company",
                    "location": "San Francisco",
                    "jobs": [
                        {
                            "title": "ML Engineer",
                            "url": "https://testcorp-ai.example.com/careers/ml-eng-1",
                            "experience_level": "mid",
                        }
                    ],
                }
            ]
        }
    ),
    "grounding_metadata": {"chunks": []},
    "search_queries": ["test query"],
    "error": None,
}


@pytest.fixture
def mock_gemini_response() -> dict[str, object]:
    """Return a fresh Gemini response payload for tests that mutate it."""
    return copy.deepcopy(MOCK_GEMINI_RESPONSE)
