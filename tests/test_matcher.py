import pytest

from copilot.knowledge.records import DoctorRecord, PracticeRecord
from copilot.scanner.matcher import ExistingDataMatcher, MatchKind, name_similarity


@pytest.fixture
def matcher(app):
    def add(**kw):
        return app.knowledge.upsert_practice(PracticeRecord(**kw)).practice
    add(name="SYNTH Kardiologie Beta", street="Musterweg 2", plz="66113", ort="Saarbrücken",
        website="synth-beta.invalid", doctors=[DoctorRecord(full_name="Karl Probe", title="Prof. Dr.")])
    add(name="SYNTH Orthopädie Gamma", street="Probeallee 3", plz="66115", ort="Saarbrücken")
    return ExistingDataMatcher(app.knowledge_repo, app.merge_repo).load()


def rec(**kw):
    kw.setdefault("name", "SYNTH Irgendwas")
    return PracticeRecord(**kw)


def test_same_key_is_exact_regardless_of_spelling(matcher):
    m = matcher.match(rec(name="synth kardiologie beta", street="Musterweg 2", plz="66113"), "local_import")
    assert m.kind is MatchKind.EXACT and m.confidence == 1.0 and "same_key" in m.candidates[0][2]
    street_variant = matcher.match(rec(name="SYNTH Kardiologie Beta", street="Musterweg  2", plz="66113"), "local_import")
    assert street_variant.kind is MatchKind.EXACT


def test_same_website_and_street_is_exact_even_with_other_name(matcher):
    m = matcher.match(rec(name="SYNTH Herzzentrum", street="Musterweg 2", plz="66113", website="https://www.synth-beta.invalid/x"),
                      "local_import")
    assert m.kind is MatchKind.EXACT and m.confidence == 0.97


@pytest.mark.parametrize("kw,reason", [
    (dict(name="SYNTH MVZ Nachfolge", street="Probeallee 3", plz="66115"), "same_street"),         # gleiche Adresse, anderer Name
    (dict(name="SYNTH Orthopädie Gamma", street="Andere Str. 9", plz="66115"), "same_name"),       # gleicher Name, andere Adresse
    (dict(name="SYNTH Filiale", street="Nebenstr. 1", plz="66999", website="synth-beta.invalid"), "same_website"),
    (dict(name="SYNTH Neu", ort="Saarbrücken", doctors=[DoctorRecord(full_name="Karl Probe")]), "shared_doctor"),
])
def test_uncertain_cases_are_possible_never_exact(matcher, kw, reason):
    m = matcher.match(rec(**kw), "local_import")
    assert m.kind is MatchKind.POSSIBLE
    assert reason in m.candidates[0][2] and 0.5 <= m.confidence < 0.9


def test_unrelated_candidates_do_not_match(matcher):
    assert matcher.match(rec(name="SYNTH HNO Omega", street="Neuweg 10", plz="66119", ort="Saarbrücken"),
                         "local_import").kind is MatchKind.NONE
    assert matcher.match(rec(name="SYNTH Orthopädie Gamma", street="Weg 1", plz="54290", ort="Trier"),
                         "local_import").kind is MatchKind.NONE                    # gleicher Name, anderer Ort


def test_name_only_similarity_never_yields_exact(matcher):
    m = matcher.match(rec(name="SYNTH Kardiologie Beta Praxis", ort="Saarbrücken"), "local_import")
    assert m.kind is MatchKind.POSSIBLE                                              # nie automatisch


def test_generic_words_do_not_create_similarity():
    assert name_similarity("Praxis Dr. Müller", "Praxis Dr. Meier") < 0.85
    assert name_similarity("Gemeinschaftspraxis Dr. Müller", "Praxis Mueller") >= 0.85


def test_ambiguous_exact_is_downgraded_to_possible(app):
    a = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Alt A", street="Weg 1", plz="66111", website="gemeinsam.invalid")).practice
    b = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Alt B", street="Weg 1", plz="66111", website="gemeinsam.invalid")).practice
    m = ExistingDataMatcher(app.knowledge_repo, app.merge_repo).load().match(
        rec(name="SYNTH Neu C", street="Weg 1", plz="66111", website="gemeinsam.invalid"), "local_import")
    assert m.kind is MatchKind.POSSIBLE and {c[0] for c in m.candidates} == {a.id, b.id}
    assert all("ambiguous_exact" in c[2] for c in m.candidates)
