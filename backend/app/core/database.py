"""Database connectivity primitives shared across the backend.

The API layer and service layer both depend on a single async engine/session
factory so transaction behavior stays consistent no matter which entrypoint
invoked the work. Keeping that setup here also gives FastAPI a lightweight
dependency hook instead of coupling request handlers to SQLAlchemy internals.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session for a single unit of work.

    FastAPI dependencies call this per request so handlers and services can
    share the same session object, commit boundaries, and identity map during a
    request. Using a generator here keeps session cleanup automatic even when a
    downstream handler raises.

    Yields:
        AsyncSession: A live session bound to the shared async engine.
    """
    async with async_session() as session:
        yield session
