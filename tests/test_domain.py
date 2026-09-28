from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from copilot.domain.enums import EntityType, RelationOrigin, RelationType
from copilot.domain.models import Fact, FactDraft, NetworkRelationship, Practice, Source
from copilot.domain.normalize import fold, normalize_url, practice_key, split_doctor_name
from copilot.domain.territory import Territory

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_fold_and_keys():
    assert fold("Saarbrücken") == fold("Saarbruecken") == "saarbruecken"
    assert practice_key("Praxis Dr. Müller", "66111", "Bahnhofstr. 5") == practice_key("Praxis Dr. Müller", "66111", "Bahnhofstraße 5")


def test_split_doctor_name():
    assert split_doctor_name("Prof. Dr. med. Karl Probe") == ("Prof. Dr. med.", "Karl Probe")
    assert split_doctor_name("Max Beispielmann") == (None, "Max Beispielmann")


def test_url_normalization_and_rejection():
    assert normalize_url("www.example.invalid") == "https://www.example.invalid"
    for bad in ("ftp://x.de", "javascript:alert(1)", "https://user:pw@x.de"):
        with pytest.raises(ValueError):
            normalize_url(bad)


def test_practice_validation():
    with pytest.raises(ValidationError):
        Practice(name="x", canonical_key="k", plz="661")
    with pytest.raises(ValidationError):
        Practice(name="x", canonical_key="k", lat=49.0)  # lat ohne lon


def test_observed_relationship_requires_fact_and_derived_requires_rule():
    base = dict(from_type=EntityType.PRACTICE, from_id=1, to_type=EntityType.PRACTICE, to_id=2, rel_type=RelationType.REFERS_TO)
    with pytest.raises(ValidationError):
        NetworkRelationship(**base, origin=RelationOrigin.OBSERVED)
    with pytest.raises(ValidationError):
        NetworkRelationship(**base, origin=RelationOrigin.DERIVED)
    with pytest.raises(ValidationError):
        NetworkRelationship(**base, origin=RelationOrigin.DERIVED, rule_id="r", fact_id=1)  # derived darf keinen Beleg tragen
    NetworkRelationship(**base, origin=RelationOrigin.OBSERVED, fact_id=1)
    NetworkRelationship(**base, origin=RelationOrigin.DERIVED, rule_id="r")


def test_fact_needs_source_and_ordered_dates():
    common = dict(subject_type=EntityType.PRACTICE, subject_id=1, key="k", value=1, confidence=0.5, observed_at=NOW)
    with pytest.raises(ValidationError):
        Fact(**common)  # source_id fehlt
    with pytest.raises(ValidationError):
        Fact(**common, source_id=1, stale_after=NOW - timedelta(days=1))
    with pytest.raises(ValidationError):
        Fact(**{**common, "observed_at": datetime(2026, 1, 1)}, source_id=1)  # naive Zeit


def test_factdraft_rejects_empty_values():
    for empty in (None, "", [], {}):
        with pytest.raises(ValidationError):
            FactDraft(key="k", value=empty)


def test_web_source_requires_url():
    with pytest.raises(ValidationError):
        Source(source_type="practice_website", retrieved_at=NOW, robots_status="allowed", reliability=3)


def test_territory_resolution():
    from tests.conftest import REPO
    t = Territory.load(REPO / "config")
    assert t.resolve("Saarbruecken").region == "saarland"
    assert t.resolve("Neunkirchen").place.name == "Neunkirchen/Saar"
    assert t.resolve("Unbekanntdorf", "66999").region == "saarland"   # PLZ-Präfix
    assert t.resolve("Köln", "50667").region is None
    assert t.parse_scope("wittlich").place.name == "Wittlich"
    assert t.parse_scope("Vulkaneifel").kind == "region"
    assert t.parse_scope("Berlin") is None
