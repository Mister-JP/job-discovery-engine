"""Tests for application logging configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import logging_config
from app.main import app


def _make_record(message: str, *, extra: dict | None = None) -> logging.LogRecord:
    logger = logging.getLogger("app.test")
    return logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        message,
        args=(),
        exc_info=None,
        extra=extra,
    )


def test_structured_formatter_outputs_json_with_extra_fields():
    record = _make_record(
        "Search run completed",
        extra={
            "event": "search_completed",
            "search_run_id": "run-123",
            "query": "AI safety labs hiring",
            "candidate_count": 4,
            "duration_ms": 1234,
        },
    )

    payload = json.loads(logging_config.StructuredFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["component"] == "app.test"
    assert payload["message"] == "Search run completed"
    assert payload["event"] == "search_completed"
    assert payload["search_run_id"] == "run-123"
    assert payload["query"] == "AI safety labs hiring"
    assert payload["candidate_count"] == 4
    assert payload["duration_ms"] == 1234
    assert "timestamp" in payload


def test_readable_formatter_includes_event_and_extras():
    record = _make_record(
        "Parallel verification complete",
        extra={
            "search_run_id": "run-123",
            "query": "AI safety labs hiring",
            "verified_count": 3,
            "candidate_count": 4,
            "duration_ms": 890,
        },
    )

    output = logging_config.ReadableFormatter().format(record)

    assert "INFO" in output
    assert "app.test" in output
    assert "Parallel verification complete" in output
    assert "search_run_id=run-123" in output
    assert "query='AI safety labs hiring'" in output
    assert "verified_count=3" in output
    assert "candidate_count=4" in output
    assert "duration_ms=890" in output


def test_setup_logging_uses_log_format_when_no_override(monkeypatch):
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level

    monkeypatch.setattr(logging_config, "LOG_LEVEL", "INFO")
    monkeypatch.setattr(logging_config, "LOG_FORMAT", "json")

    try:
        logging_config.setup_logging()

        assert root_logger.level == logging.INFO
        assert len(root_logger.handlers) == 1
        assert isinstance(
            root_logger.handlers[0].formatter,
            logging_config.StructuredFormatter,
        )
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_root_level)


def test_setup_logging_respects_explicit_override_and_suppresses_noisy_loggers(
    monkeypatch,
):
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level
    original_levels = {
        name: logging.getLogger(name).level
        for name in (
            "httpx",
            "httpcore",
            "sqlalchemy.engine",
            "sqlalchemy.pool",
            "uvicorn.access",
        )
    }

    monkeypatch.setattr(logging_config, "LOG_LEVEL", "DEBUG")

    try:
        logging_config.setup_logging(json_format=True)

        assert root_logger.level == logging.DEBUG
        assert len(root_logger.handlers) == 1
        assert isinstance(
            root_logger.handlers[0].formatter,
            logging_config.StructuredFormatter,
        )
        for logger_name in original_levels:
            assert logging.getLogger(logger_name).level == logging.WARNING
    finally:
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)
        root_logger.setLevel(original_root_level)
        for logger_name, level in original_levels.items():
            logging.getLogger(logger_name).setLevel(level)


def test_request_logging_middleware_attaches_http_metadata(caplog):
    client = TestClient(app)

    with caplog.at_level("INFO", logger="app.middleware"):
        response = client.get("/")

    assert response.status_code == 200

    matching_records = [
        record
        for record in caplog.records
        if record.name == "app.middleware"
        and record.getMessage() == "HTTP request completed"
    ]
    assert matching_records

    record = matching_records[-1]
    assert record.event == "http_request_completed"
    assert record.method == "GET"
    assert record.path == "/"
    assert record.status_code == 200
    assert isinstance(record.duration_ms, int)
    assert record.duration_ms >= 0
