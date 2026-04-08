"""Unit tests for Gemini response parsing helpers."""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.response_parser import parse_gemini_response


def test_parse_gemini_response_handles_valid_wrapped_json():
    raw = json.dumps(
        {
            "institutions": [
                {
                    "name": "OpenAI",
                    "careers_url": "https://openai.com/careers",
                    "jobs": [
                        {
                            "title": "Engineer",
                            "url": "https://openai.com/jobs/1",
                        }
                    ],
                }
            ]
        }
    )

    result, error = parse_gemini_response(raw)

    assert error is None
    assert result is not None
    assert result.total_institutions == 1
    assert result.total_jobs == 1


def test_parse_gemini_response_extracts_json_from_code_block():
    raw = """
    Here are the results:
    ```json
    {"institutions": [{"name": "OpenAI", "careers_url": "https://openai.com/careers"}]}
    ```
    """

    result, error = parse_gemini_response(raw)

    assert error is None
    assert result is not None
    assert result.total_institutions == 1


def test_parse_gemini_response_handles_prose_before_and_after_json():
    raw = """
    Summary first.
    [{"name": "Anthropic", "careers_url": "https://anthropic.com/careers", "jobs": []}]
    Additional note after the JSON.
    """

    result, error = parse_gemini_response(raw)

    assert error is None
    assert result is not None
    assert result.total_institutions == 1
    assert result.institutions[0].name == "Anthropic"


def test_parse_gemini_response_maps_results_key():
    raw = json.dumps(
        {
            "results": [
                {
                    "name": "Example Org",
                    "careers_url": "https://example.org/careers",
                    "jobs": [],
                }
            ]
        }
    )

    result, error = parse_gemini_response(raw)

    assert error is None
    assert result is not None
    assert result.total_institutions == 1


def test_parse_gemini_response_wraps_single_institution():
    raw = json.dumps(
        {
            "name": "Single Org",
            "careers_url": "https://single.example/careers",
            "jobs": [],
        }
    )

    result, error = parse_gemini_response(raw)

    assert error is None
    assert result is not None
    assert result.total_institutions == 1
    assert result.institutions[0].name == "Single Org"


def test_parse_gemini_response_rejects_empty_input():
    result, error = parse_gemini_response("")

    assert result is None
    assert error == "Empty response from Gemini"


def test_parse_gemini_response_surfaces_validation_errors():
    raw = json.dumps(
        {
            "institutions": [
                {
                    "name": "Broken Org",
                    "jobs": [],
                }
            ]
        }
    )

    result, error = parse_gemini_response(raw)

    assert result is None
    assert error is not None
    assert "Validation error:" in error
    assert "careers_url" in error


def test_parse_gemini_response_reports_non_json_response():
    result, error = parse_gemini_response("No structured data was returned.")

    assert result is None
    assert error is not None
    assert "Failed to parse JSON from Gemini response" in error
