"""Institution persistence helpers built around domain identity.

Institutions are the durable anchor for the rest of the dataset, so the merge
policy here is intentionally conservative: new discoveries can fill blanks and
refresh timestamps, but they do not overwrite richer data already stored for
the same employer. That bias favors stability over aggressive correction when
the system repeatedly rediscovers the same organization with incomplete AI
output.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.core.url_utils import extract_root_domain, normalize_url
from app.models.entities import Institution, InstitutionType


async def upsert_institution(
    session: AsyncSession,
    name: str,
    careers_url: str,
    institution_type: Optional[InstitutionType] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    is_verified: bool = False,
    commit: bool = True,
) -> tuple[Institution, bool]:
    """Insert or merge an institution record using root domain identity.

    Domain-level upsert is the main defense against duplicate employers showing
    up under different careers subdomains or prompt variants. The merge strategy
    only fills missing optional fields and never overwrites populated values,
    because later model output is often sparser or less trustworthy than what is
    already stored. That conservative approach can leave stale metadata in place
    until manually corrected, but it avoids accidental regressions from noisy
    rediscovery.

    Args:
        session: Active database session participating in the current unit of
            work.
        name: Institution display name from the verified candidate.
        careers_url: Institution careers URL used for normalization and domain
            extraction.
        institution_type: Optional normalized institution classification.
        description: Optional institution summary text.
        location: Optional institution location text.
        is_verified: Whether this observation came from a verified candidate.
        commit: Whether to commit immediately or only flush for batch writes.

    Returns:
        tuple[Institution, bool]: The persisted institution and a flag
        indicating whether it was newly created.
    """
    domain = extract_root_domain(careers_url)
    normalized_careers_url = normalize_url(careers_url)

    stmt = select(Institution).where(col(Institution.domain) == domain)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        now = datetime.utcnow()
        existing.last_seen_at = now
        existing.updated_at = now

        if existing.careers_url is None and normalized_careers_url is not None:
            existing.careers_url = normalized_careers_url
        if existing.institution_type is None and institution_type is not None:
            existing.institution_type = institution_type
        if existing.description is None and description is not None:
            existing.description = description
        if existing.location is None and location is not None:
            existing.location = location
        if is_verified:
            existing.is_verified = True

        if commit:
            await session.commit()
        else:
            await session.flush()
        await session.refresh(existing)
        return existing, False

    institution = Institution(
        name=name,
        domain=domain,
        careers_url=normalized_careers_url,
        institution_type=institution_type,
        description=description,
        location=location,
        is_verified=is_verified,
    )
    session.add(institution)
    if commit:
        await session.commit()
    else:
        await session.flush()
    await session.refresh(institution)
    return institution, True


async def get_institution_by_domain(
    session: AsyncSession,
    domain: str,
) -> Optional[Institution]:
    """Fetch the canonical institution record for a root domain.

    Services use this lookup when they need a stable employer record without
    reimplementing domain-based deduplication logic in multiple places.

    Args:
        session: Active database session used for the query.
        domain: Root domain that uniquely identifies the institution.

    Returns:
        Institution | None: Matching institution when present, otherwise
        ``None``.
    """
    stmt = select(Institution).where(col(Institution.domain) == domain)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_all_known_domains(session: AsyncSession) -> list[str]:
    """Return the set of already-known institution domains.

    The search prompt uses this list to steer Gemini toward novel discovery
    without forbidding rediscovery entirely. Keeping the query in the service
    layer avoids leaking storage details into prompt construction code.

    Args:
        session: Active database session used for the query.

    Returns:
        list[str]: All stored institution domains.
    """
    stmt = select(col(Institution.domain))
    result = await session.execute(stmt)
    return list(result.scalars().all())
