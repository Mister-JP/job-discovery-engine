"""Focused parser tests for common Gemini response shapes."""

from __future__ import annotations

import json

from app.services.response_parser import parse_gemini_response


class TestResponseParser:
    def test_valid_json(self):
        data = json.dumps(
            {
                "institutions": [
                    {
                        "name": "Test",
                        "careers_url": "https://test.com/careers",
                        "jobs": [],
                    }
                ]
            }
        )

        result, error = parse_gemini_response(data)

        assert result is not None
        assert error is None
        assert result.total_institutions == 1

    def test_empty_response(self):
        result, error = parse_gemini_response("")

        assert result is None
        assert error is not None

    def test_invalid_json(self):
        result, error = parse_gemini_response("not json at all")

        assert result is None
        assert error is not None

    def test_bare_list(self):
        data = json.dumps(
            [{"name": "Test", "careers_url": "https://test.com/careers", "jobs": []}]
        )

        result, error = parse_gemini_response(data)

        assert result is not None
        assert error is None
        assert result.total_institutions == 1
