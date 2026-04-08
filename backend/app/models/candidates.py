"""Transient candidate models produced by Gemini before verification.

These schemas sit between the raw model response and the persistent entity
layer. They intentionally accept slightly noisy AI output, normalize it into a
stable shape, and keep unverified discoveries separate from stored institutions
and jobs until the verification pipeline has decided they are trustworthy.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator

from app.models.entities import ExperienceLevel, InstitutionType

_http_url_adapter = TypeAdapter(HttpUrl)
_VALID_EXPERIENCE_LEVELS = {level.value for level in ExperienceLevel}
_VALID_INSTITUTION_TYPES = {kind.value for kind in InstitutionType}


def _normalize_url(value: Any) -> str:
    """Coerce model-produced URL text into a strict absolute HTTP(S) string.

    Gemini sometimes returns URLs without schemes or with extra whitespace. This
    helper keeps that repair logic in one place so field validators stay
    consistent and the parser can reject malformed data before verification.

    Args:
        value: Raw field value emitted by the model.

    Returns:
        str: A cleaned absolute URL accepted by ``pydantic.HttpUrl``.

    Raises:
        TypeError: If the incoming value is not string-like enough to repair.
        ValueError: If URL validation fails after normalization.
    """
    if not isinstance(value, str):
        raise TypeError("URL must be a string")

    normalized = value.strip()
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"

    return str(_http_url_adapter.validate_python(normalized))


def _normalize_enum_value(value: Any, valid_values: set[str], fallback: str) -> str:
    """Map noisy free-form model text onto a controlled enum vocabulary.

    The prompt asks Gemini for a closed set of values, but model output can
    still drift in casing or wording. Falling back instead of raising keeps one
    imperfect field from discarding an otherwise useful candidate record.

    Args:
        value: Raw field value emitted by the model.
        valid_values: Accepted normalized enum values.
        fallback: Value to use when the model output is missing or unknown.

    Returns:
        str: A valid enum string suitable for downstream conversion.
    """
    if value is None:
        return fallback
    if not isinstance(value, str):
        return fallback

    normalized = value.strip().lower()
    return normalized if normalized in valid_values else fallback


class JobCandidate(BaseModel):
    """A potential job posting returned by Gemini. Not yet verified."""

    title: str = Field(..., min_length=1, max_length=500)
    url: str = Field(..., min_length=10)
    location: str | None = None
    experience_level: str = Field(default=ExperienceLevel.UNKNOWN.value)
    salary_range: str | None = None

    @field_validator("experience_level", mode="before")
    @classmethod
    def validate_experience_level(cls, value: Any) -> str:
        """Normalize experience level text before model validation.

        The parser prefers graceful degradation here because experience level is
        useful metadata, not an identity field. Converting unknown labels to a
        safe default avoids losing the entire job candidate over one fuzzy value.

        Args:
            value: Raw value returned by Gemini.

        Returns:
            str: A normalized experience level supported by the entity enum.
        """
        return _normalize_enum_value(
            value,
            valid_values=_VALID_EXPERIENCE_LEVELS,
            fallback=ExperienceLevel.UNKNOWN.value,
        )

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: Any) -> str:
        """Repair and validate job URLs before candidates enter verification.

        Verification checks assume they receive absolute URLs, so this validator
        performs the minimal cleanup required to keep later pipeline stages
        focused on trustworthiness rather than syntactic repair.

        Args:
            value: Raw URL value returned by Gemini.

        Returns:
            str: A normalized absolute job URL.

        Raises:
            TypeError: If the model supplied a non-string URL value.
            ValueError: If the repaired string is still not a valid HTTP(S) URL.
        """
        return _normalize_url(value)


class InstitutionCandidate(BaseModel):
    """A potential institution returned by Gemini. Not yet verified."""

    name: str = Field(..., min_length=1, max_length=500)
    careers_url: str = Field(..., min_length=10)
    institution_type: str = Field(default=InstitutionType.OTHER.value)
    description: str | None = None
    location: str | None = None
    jobs: list[JobCandidate] = Field(default_factory=list)

    @field_validator("institution_type", mode="before")
    @classmethod
    def validate_institution_type(cls, value: Any) -> str:
        """Normalize institution type text into the supported taxonomy.

        Institution type drives filtering and prompt conditioning, but it is not
        strong enough to justify rejecting an otherwise valid institution. This
        validator therefore biases toward preserving the record with a safe
        fallback instead of forcing strict model compliance.

        Args:
            value: Raw value returned by Gemini.

        Returns:
            str: A normalized institution type supported by the entity enum.
        """
        return _normalize_enum_value(
            value,
            valid_values=_VALID_INSTITUTION_TYPES,
            fallback=InstitutionType.OTHER.value,
        )

    @field_validator("careers_url", mode="before")
    @classmethod
    def validate_careers_url(cls, value: Any) -> str:
        """Repair and validate institution careers URLs before verification.

        Careers URLs anchor institution identity and later deduplication, so the
        parser normalizes them as early as possible to reduce downstream drift
        between equivalent representations of the same page.

        Args:
            value: Raw careers URL returned by Gemini.

        Returns:
            str: A normalized absolute careers URL.

        Raises:
            TypeError: If the model supplied a non-string URL value.
            ValueError: If the repaired string is still not a valid HTTP(S) URL.
        """
        return _normalize_url(value)


class SearchResult(BaseModel):
    """The top-level Gemini search response."""

    institutions: list[InstitutionCandidate] = Field(default_factory=list)

    @property
    def total_institutions(self) -> int:
        """Return how many institution candidates survived parsing.

        This count is stored on ``SearchRun`` records and used in logs so the
        system can distinguish model yield from later verification yield.

        Returns:
            int: Number of parsed institution candidates.
        """
        return len(self.institutions)

    @property
    def total_jobs(self) -> int:
        """Return the total number of job candidates nested under institutions.

        Tracking this separately from institution count helps operators see when
        the model is finding organizations but failing to surface concrete job
        URLs, which is a common prompt-quality signal.

        Returns:
            int: Total parsed job candidates across all institutions.
        """
        return sum(len(institution.jobs) for institution in self.institutions)

    def all_urls(self) -> list[str]:
        """Flatten every candidate URL into one list for downstream analysis.

        Verification, grounding cross-reference, and logging all benefit from a
        simple URL list that ignores the nested response shape. Centralizing that
        flattening avoids subtle mismatches between those subsystems.

        Returns:
            list[str]: Careers and job URLs in discovery order.
        """
        urls: list[str] = []
        for institution in self.institutions:
            urls.append(institution.careers_url)
            urls.extend(job.url for job in institution.jobs)
        return urls
