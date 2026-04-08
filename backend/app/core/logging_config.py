"""Structured logging configuration for the application."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import LOG_FORMAT, LOG_LEVEL

_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
}


def _extract_extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Return custom fields attached via ``logger.*(..., extra=...)``."""
    extras: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _STANDARD_LOG_RECORD_FIELDS or key.startswith("_"):
            continue
        extras[key] = value
    return extras


def _format_extra_value(value: Any) -> str:
    """Render custom fields safely in human-readable logs."""
    if isinstance(value, str):
        return repr(value) if any(char.isspace() for char in value) else value
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, default=str, sort_keys=True)
    return str(value)


def _timestamp_from_record(record: logging.LogRecord, *, utc: bool) -> str:
    """Render a stable timestamp derived from the record creation time."""
    tz = timezone.utc if utc else None
    timestamp = datetime.fromtimestamp(record.created, tz=tz)
    return timestamp.isoformat(timespec="milliseconds")


def log_extra(**kwargs: Any) -> dict[str, Any]:
    """Drop ``None`` values before passing extras into the logger."""
    return {key: value for key, value in kwargs.items() if value is not None}


class StructuredFormatter(logging.Formatter):
    """JSON formatter for production and log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        extras = _extract_extra_fields(record)
        message = record.getMessage()
        log_entry = {
            "timestamp": _timestamp_from_record(record, utc=True),
            "level": record.levelname,
            "component": record.name,
            "message": message,
            "event": extras.pop("event", message),
        }
        log_entry.update(extras)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        extras = _extract_extra_fields(record)
        extra_text = ""
        if extras:
            extra_text = " " + " ".join(
                f"{key}={_format_extra_value(value)}"
                for key, value in sorted(extras.items())
            )

        message = (
            f"{timestamp} | {record.levelname:<7} | {record.name:<40} | "
            f"{record.getMessage()}{extra_text}"
        )

        if record.exc_info:
            return f"{message}\n{self.formatException(record.exc_info)}"

        return message


def is_json_logging_enabled(log_format: str | None = None) -> bool:
    """Return whether logs should use the structured JSON formatter."""
    return (log_format or LOG_FORMAT).strip().lower() == "json"


def setup_logging(json_format: bool | None = None) -> None:
    """Configure root logging for the application."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    use_json = is_json_logging_enabled() if json_format is None else json_format
    handler.setFormatter(StructuredFormatter() if use_json else ReadableFormatter())
    root_logger.addHandler(handler)

    for logger_name in (
        "httpx",
        "httpcore",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "uvicorn.access",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
