"""Persistent domain models for the discovery pipeline.

These SQLModel entities are the system's long-term memory: candidate data is
temporary, but verified institutions, jobs, search runs, and evidence records
survive across requests for deduplication, auditing, and UI reporting. The
schema is intentionally conservative about identity, using root domain and
normalized URL as the stable keys that connect search, verification, and
storage.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


class InstitutionType(str, Enum):
    """Normalized institution categories used across prompts, storage, and API output."""

    UNIVERSITY = "university"
    COMPANY = "company"
    NONPROFIT = "nonprofit"
    GOVERNMENT = "government"
    RESEARCH_LAB = "research_lab"
    OTHER = "other"


class ExperienceLevel(str, Enum):
    """Normalized experience buckets that collapse noisy model output into stable filters."""

    INTERN = "intern"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


class SearchRunStatus(str, Enum):
    """Lifecycle states that make long-running search execution observable to clients."""

    INITIATED = "initiated"
    SEARCHING = "searching"
    VERIFYING = "verifying"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationCheckName(str, Enum):
    """Stable identifiers for pipeline checks used in evidence rows and logs."""

    URL_WELLFORMED = "url_wellformed"
    NOT_AGGREGATOR = "not_aggregator"
    DNS_RESOLVES = "dns_resolves"
    HTTP_REACHABLE = "http_reachable"
    CONTENT_SIGNALS = "content_signals"


class Institution(SQLModel, table=True):
    """A hiring organization identified by its root domain.

    The system stores institutions separately from jobs so repeated discovery of
    the same employer can enrich one canonical record instead of fragmenting the
    history across many pages or searches.
    """

    __tablename__ = "institutions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    domain: str = Field(unique=True, index=True)
    careers_url: Optional[str] = None
    institution_type: Optional[InstitutionType] = None
    description: Optional[str] = None
    location: Optional[str] = None
    is_verified: bool = Field(default=False)
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    jobs: list["Job"] = Relationship(back_populates="institution")


class Job(SQLModel, table=True):
    """A single job posting identified by its normalized source URL.

    URL identity is intentionally stricter than title-based matching because job
    titles are noisy and often reused, while a normalized posting URL gives the
    persistence layer a deterministic way to merge rediscovered roles.
    """

    __tablename__ = "jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(index=True)
    url: str = Field(unique=True, index=True)
    institution_id: uuid.UUID = Field(foreign_key="institutions.id", index=True)
    description: Optional[str] = None
    location: Optional[str] = None
    experience_level: Optional[ExperienceLevel] = None
    salary_range: Optional[str] = None
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)
    source_query: Optional[str] = None
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_verified_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    institution: Optional["Institution"] = Relationship(back_populates="jobs")


class SearchRun(SQLModel, table=True):
    """Audit record for one orchestrated discovery attempt.

    Search runs capture counts, durations, raw model output, and failures so the
    API and operators can understand not only what was stored, but also what the
    pipeline saw and where it broke down.
    """

    __tablename__ = "search_runs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    query: str
    status: SearchRunStatus = Field(default=SearchRunStatus.INITIATED)
    initiated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    candidates_raw: int = Field(default=0)
    candidates_verified: int = Field(default=0)
    institutions_new: int = Field(default=0)
    institutions_updated: int = Field(default=0)
    jobs_new: int = Field(default=0)
    jobs_updated: int = Field(default=0)
    error_detail: Optional[str] = None
    raw_response: Optional[str] = None
    duration_ms: Optional[int] = None
    pipeline_trace: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )

    verification_evidence: list["VerificationEvidence"] = Relationship(
        back_populates="search_run",
    )


class VerificationEvidence(SQLModel, table=True):
    """Result of one verification check against one candidate URL.

    Evidence rows preserve intermediate decisions even when the candidate later
    fails, which is critical for debugging false positives, tuning check order,
    and explaining to users why a candidate did or did not persist.
    """

    __tablename__ = "verification_evidence"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    search_run_id: uuid.UUID = Field(foreign_key="search_runs.id", index=True)
    candidate_url: str
    candidate_name: Optional[str] = None
    check_name: VerificationCheckName
    passed: bool
    detail: Optional[str] = None
    duration_ms: Optional[int] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)

    search_run: Optional["SearchRun"] = Relationship(
        back_populates="verification_evidence",
    )
