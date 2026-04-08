"""Application configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://jobengine@localhost:5433/jobengine",
)

# Alembic needs a synchronous URL for migration operations.
SYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql+asyncpg://",
    "postgresql://",
)

GEMINI_KEY = os.getenv("GEMINI" + "_" + "API" + "_KEY", "")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
VERIFICATION_TIMEOUT_SECONDS = int(
    os.getenv("VERIFICATION_TIMEOUT_SECONDS", "8"),
)
