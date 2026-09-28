from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class EntityType(_StrEnum):
    PRACTICE = "practice"
    DOCTOR = "doctor"
    SPECIALTY = "specialty"
    EVENT = "event"


class RelationType(_StrEnum):
    REFERS_TO = "refers_to"
    SAME_PRACTICE = "same_practice"
    SHARED_LOCATION = "shared_location"
    COLLEAGUE = "colleague"


class RelationOrigin(_StrEnum):
    DERIVED = "derived"    # aus Regel abgeleitet – NICHT belegt
    OBSERVED = "observed"  # durch einen Fact mit Quelle belegt
    MANUAL = "manual"      # vom Nutzer erfasst


class SourceType(_StrEnum):
    PRACTICE_WEBSITE = "practice_website"
    DOCTOLIB_PUBLIC = "doctolib_public"
    EVENT_PAGE = "event_page"
    REGISTRY = "registry"
    MANUAL = "manual"
    LINKEDIN_MANUAL = "linkedin_manual"


class RobotsStatus(_StrEnum):
    ALLOWED = "allowed"
    NOT_APPLICABLE = "not_applicable"  # z. B. manuelle Quelle


class FactStatus(_StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class ResearchStatus(_StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class ProspectStage(_StrEnum):
    IDENTIFIED = "identified"
    RESEARCHED = "researched"
    CONTACTED = "contacted"
    MEETING = "meeting"
    PROPOSAL = "proposal"
    WON = "won"
    LOST = "lost"
    PARKED = "parked"


class GeoPrecision(_StrEnum):
    EXACT = "exact"
    PLACE = "place"  # nur Ortsmittelpunkt
