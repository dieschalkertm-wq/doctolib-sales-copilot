"""Domain-Modelle (Pydantic). Vier getrennte Schichten – siehe docs/ARCHITECTURE.md §5:
K Knowledge (dauerhaft) · R Research (zeitabhängig, belegt) · P Pipeline · A Actions/Audit.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from copilot.domain.enums import (
    EntityType,
    FactStatus,
    GeoPrecision,
    ProspectStage,
    RelationOrigin,
    RelationType,
    ResearchStatus,
    RobotsStatus,
    SourceType,
)
from copilot.domain.normalize import normalize_url

_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, use_enum_values=False)


def _url(value: str | None) -> str | None:
    try:
        return normalize_url(value)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


# ---- K: Knowledge (dauerhaft) ----------------------------------------------------------------


class Specialty(_Model):
    id: int | None = None
    code: str
    name: str = Field(min_length=1, max_length=120)
    parent_id: int | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _SNAKE.match(v):
            raise ValueError("code must be snake_case")
        return v


class Practice(_Model):
    id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    street: str | None = Field(default=None, max_length=200)
    plz: str | None = Field(default=None, pattern=r"^\d{5}$")
    ort: str | None = Field(default=None, max_length=120)
    ort_key: str | None = None
    region: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    geo_precision: GeoPrecision | None = None
    website_url: str | None = None
    canonical_key: str
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None

    _v_url = field_validator("website_url")(lambda cls, v: _url(v))

    @model_validator(mode="after")
    def _geo(self) -> "Practice":
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be set together")
        if self.lat is not None and self.geo_precision is None:
            raise ValueError("geo_precision required when coordinates are set")
        return self


class Doctor(_Model):
    id: int | None = None
    full_name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=60)
    canonical_key: str


class NetworkRelationship(_Model):
    id: int | None = None
    from_type: EntityType
    from_id: int
    to_type: EntityType
    to_id: int
    rel_type: RelationType
    origin: RelationOrigin
    strength: float | None = Field(default=None, ge=0, le=1)
    distance_km: float | None = Field(default=None, ge=0)
    fact_id: int | None = None
    rule_id: str | None = None
    note: str | None = Field(default=None, max_length=300)
    created_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _origin_rules(self) -> "NetworkRelationship":
        if self.origin is RelationOrigin.OBSERVED and self.fact_id is None:
            raise ValueError("observed relationship requires a fact_id (evidence)")
        if self.origin is RelationOrigin.DERIVED and not self.rule_id:
            raise ValueError("derived relationship requires a rule_id")
        if self.origin is not RelationOrigin.OBSERVED and self.fact_id is not None:
            raise ValueError("only observed relationships may reference a fact")
        if (self.from_type, self.from_id) == (self.to_type, self.to_id):
            raise ValueError("relationship endpoints must differ")
        return self


# ---- R: Research (zeitabhängig, belegt) ------------------------------------------------------


class Source(_Model):
    id: int | None = None
    source_type: SourceType
    url: str | None = None
    publisher: str | None = Field(default=None, max_length=200)
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    robots_status: RobotsStatus
    tos_ref: str | None = Field(default=None, max_length=300)
    reliability: int = Field(ge=1, le=5)
    raw_ref: str | None = None

    _v_url = field_validator("url")(lambda cls, v: _url(v))

    @model_validator(mode="after")
    def _web_needs_url(self) -> "Source":
        if self.source_type is not SourceType.MANUAL and not self.url:
            raise ValueError("non-manual sources require a url")
        return self


class Research(_Model):
    id: int | None = None
    subject_type: EntityType
    subject_id: int
    kind: str
    provider: str
    status: ResearchStatus = ResearchStatus.STARTED
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    error_code: str | None = None


class FactDraft(_Model):
    """Vom Provider geliefert; wird erst mit Source + Zeitstempel zum Fact."""
    key: str
    value: Any
    confidence: float = Field(default=0.8, ge=0, le=1)
    evidence: str | None = Field(default=None, max_length=500)  # Textstelle / URL, aus der der Fact stammt

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _SNAKE.match(v):
            raise ValueError("fact key must be snake_case")
        return v

    @field_validator("value")
    @classmethod
    def _value(cls, v: Any) -> Any:
        if v is None or v == "" or v == [] or v == {}:
            raise ValueError("a fact needs a non-empty value (absence of evidence is not a fact)")
        return v


class Fact(_Model):
    """Was behauptet wird (key/value), woher (source_id, evidence), wann (observed_at), wie lange gültig."""
    id: int | None = None
    subject_type: EntityType
    subject_id: int
    key: str
    value: Any
    source_id: int  # Pflicht: ohne Quelle kein Fact
    research_id: int | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None
    observed_at: AwareDatetime
    stale_after: AwareDatetime | None = None
    status: FactStatus = FactStatus.ACTIVE
    superseded_by: int | None = None

    @model_validator(mode="after")
    def _dates(self) -> "Fact":
        if self.stale_after is not None and self.stale_after < self.observed_at:
            raise ValueError("stale_after must not be before observed_at")
        return self


class Event(_Model):
    id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    ort: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    url: str | None = None
    registration_deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    distance_km: float | None = Field(default=None, ge=0)
    source_id: int  # Pflicht
    specialty_ids: list[int] = Field(default_factory=list)

    _v_url = field_validator("url")(lambda cls, v: _url(v))


# ---- P: Pipeline -----------------------------------------------------------------------------


class Customer(_Model):
    id: int | None = None
    practice_id: int
    since: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")
    products: list[str] = Field(default_factory=list)
    notes: str | None = None


class Prospect(_Model):
    id: int | None = None
    practice_id: int
    stage: ProspectStage = ProspectStage.IDENTIFIED
    score: float | None = None
    score_reasons: list[dict[str, Any]] = Field(default_factory=list)
    scored_at: AwareDatetime | None = None
    notes: str | None = None
