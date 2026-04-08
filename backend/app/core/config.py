"""Central configuration for the backend runtime.

This module resolves environment variables once at import time so the rest of
the application can depend on stable settings instead of repeating path and
fallback logic. It also bridges local development and deployed environments by
loading both repo-level and backend-local `.env` files in a predictable order.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_CONFIG_PATH = Path(__file__).resolve()
_BACKEND_DIR = _CONFIG_PATH.parents[2]
_PROJECT_DIR = _CONFIG_PATH.parents[3]

# Support running commands from `backend/` while keeping the shared repo-level
# `.env` in `job-discovery-engine/`.
load_dotenv(_PROJECT_DIR / ".env")
load_dotenv(_BACKEND_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://jobengine@localhost:5433/jobengine",
)

# Alembic needs a synchronous URL for migration operations.
SYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql+asyncpg://",
    "postgresql://",
)

GEMINI_API_KEY = os.getenv("GEMINI" + "_" + "API" + "_KEY", "")
# Backward-compatible alias for any code still importing the old name.
GEMINI_KEY = GEMINI_API_KEY
ENVIRONMENT = (
    os.getenv(
        "ENVIRONMENT",
        os.getenv("APP_ENV", "development"),
    )
    .strip()
    .lower()
)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = (
    os.getenv(
        "LOG_FORMAT",
        "json" if ENVIRONMENT in {"production", "prod"} else "readable",
    )
    .strip()
    .lower()
)
VERIFICATION_TIMEOUT_SECONDS = int(
    os.getenv("VERIFICATION_TIMEOUT_SECONDS", "8"),
)
