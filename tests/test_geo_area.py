import pytest

from copilot.domain.geo import Certainty, GeoPoint, classify, format_distance
from copilot.errors import ValidationFailed
from copilot.knowledge.records import PracticeRecord
from copilot.scanner.area import (AreaRequest, CustomerRadiusArea, LocationResolver, PlaceArea, RadiusArea,
                                  RegionArea)

CENTER = GeoPoint(49.2402, 6.9969, 0.0, "definition")


def test_classify_is_three_valued():
    near_exact = GeoPoint(49.2450, 6.9969, 0.0, "exact")            # ~0.5 km
    assert classify(CENTER, near_exact, 10)[0] is Certainty.INSIDE
    far_exact = GeoPoint(49.4430, 6.6390, 0.0, "exact")             # Merzig ~ 32 km
    assert classify(CENTER, far_exact, 10)[0] is Certainty.OUTSIDE
    # Völklingen ~12 km, Ortsmittelpunkt ±5: liegt je nach echtem Standort drinnen oder draußen
    voelk = GeoPoint(49.2510, 6.8320, 5.0, "place")
    certainty, distance, uncertainty = classify(CENTER, voelk, 10)
    assert certainty is Certainty.POSSIBLE and 11 < distance < 13 and uncertainty == 5.0
    assert classify(CENTER, voelk, 20)[0] is Certainty.INSIDE       # 12 + 5 <= 20
    assert classify(CENTER, voelk, 6)[0] is Certainty.OUTSIDE       # 12 - 5 > 6


def test_no_false_precision_in_output():
    assert format_distance(3.24, 0) == "3.2 km"
    assert format_distance(3.24, 5) == "≈3 km (±5 km)"
    assert "0 km" not in format_distance(0.0, 5) and "±5" in format_distance(0.0, 5)    # keine Distanz „0“ behaupten


def test_territory_points_carry_uncertainty(app):
    p = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH A", plz="66111", ort="Saarbrücken")).practice
    point = app.territory.point_for(p)
    assert point.precision == "place" and point.uncertainty_km == 5.0
    exact = app.knowledge.set_exact_location(p.id, 49.2500, 7.0100)
    point = app.territory.point_for(exact)
    assert point.precision == "exact" and point.uncertainty_km == 0.0
    # Praxis ohne Ort/Geodaten: nie eine Position raten
    nowhere = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Nirgends")).practice
    assert app.territory.point_for(nowhere) is None


def test_exact_coordinates_from_import_beat_place_centroid_and_never_downgrade(app):
    rec = dict(name="SYNTH B", plz="66111", street="Weg 1", ort="Saarbrücken")
    app.knowledge.upsert_practice(PracticeRecord(**rec))
    exact = app.knowledge.upsert_practice(PracticeRecord(**rec, lat=49.25, lon=7.0)).practice
    assert exact.geo_precision.value == "exact" and (exact.lat, exact.lon) == (49.25, 7.0)
    again = app.knowledge.upsert_practice(PracticeRecord(**rec)).practice     # Wiederholung ohne Koordinaten
    assert again.geo_precision.value == "exact"


def resolver(app):
    return LocationResolver(app.territory, app.knowledge_repo, app.pipeline_repo, app.network.rules, app.policies.scanner)


def test_resolver_area_kinds_and_errors(app):
    r = resolver(app)
    assert isinstance(r.resolve(AreaRequest(scope="saarbruecken")), PlaceArea)
    assert isinstance(r.resolve(AreaRequest(scope="Vulkaneifel")), RegionArea)
    area = r.resolve(AreaRequest(scope="Wittlich", radius_km=10))
    assert isinstance(area, RadiusArea) and area.radius_km == 10 and area.center.precision == "definition"
    for req, code in [(AreaRequest(scope="Berlin"), "unknown_scope"),
                      (AreaRequest(), "scope_required"),
                      (AreaRequest(scope="Saarland", radius_km=5), "radius_needs_place"),
                      (AreaRequest(scope="Trier", radius_km=500), "radius_out_of_range"),
                      (AreaRequest(scope="Trier", radius_km=0), "radius_out_of_range"),
                      (AreaRequest(around_practice=999), "practice_not_found"),
                      (AreaRequest(scope="Saarbrücken", around_customers=True), "no_customer_anchors")]:
        with pytest.raises(ValidationFailed) as exc:
            r.resolve(req)
        assert exc.value.code == code


def test_around_practice_needs_geo_and_excludes_itself(app):
    p = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH C", plz="66111", ort="Saarbrücken")).practice
    q = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH D", plz="66113", ort="Saarbrücken")).practice
    area = resolver(app).resolve(AreaRequest(around_practice=p.id, radius_km=5))
    assert area.match(p, app.territory.point_for(p), set()) is None            # sich selbst nie
    m = area.match(q, app.territory.point_for(q), set())
    assert m is not None and m.certainty is Certainty.POSSIBLE                 # zwei ungenaue Punkte: ±10 km
    nowhere = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Nirgends")).practice
    with pytest.raises(ValidationFailed) as exc:
        resolver(app).resolve(AreaRequest(around_practice=nowhere.id))
    assert exc.value.code == "center_without_geo"


def test_upgrading_to_exact_turns_possible_into_certain(app):
    a = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH E", plz="66111", ort="Saarbrücken")).practice
    b = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH F", plz="66113", ort="Saarbrücken")).practice
    a = app.knowledge.set_exact_location(a.id, 49.2402, 6.9969)
    b = app.knowledge.set_exact_location(b.id, 49.2500, 7.0000)
    area = resolver(app).resolve(AreaRequest(around_practice=a.id, radius_km=5))
    assert area.match(b, app.territory.point_for(b), set()).certainty is Certainty.INSIDE


def test_customer_area_uses_referral_rules_per_anchor(app):
    gp = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH GP", plz="66111", ort="Saarbrücken",
                                                      specialty_labels=["Hausarzt"])).practice
    app.pipeline.mark_customer(gp.id)
    area = resolver(app).resolve(AreaRequest(scope="Saarbrücken", around_customers=True))
    assert isinstance(area, CustomerRadiusArea) and len(area.anchors) == 1
    ortho = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH O", plz="66113", ort="Saarbrücken",
                                                         specialty_labels=["Orthopädie"])).practice
    psych = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH P", plz="66113", ort="Saarbrücken",
                                                         specialty_labels=["Psychiatrie"])).practice
    assert area.match(ortho, app.territory.point_for(ortho), {"orthopaedie"}).anchor_practice_id == gp.id
    assert area.match(psych, app.territory.point_for(psych), {"psychiatrie"}) is None   # keine Regel für diese Fachrichtung
