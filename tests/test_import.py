import pytest

from copilot.connectors.imports.csv_practices import CsvPracticeSource
from copilot.connectors.imports.mapping import load_mapping
from copilot.connectors.imports.service import PracticeImporter
from copilot.errors import ConfigError, ImportFailed


def importer(app):
    return PracticeImporter(app.knowledge, app.pipeline, app.audit, app.conn)


def test_synthetic_import(app, synthetic_file):
    report = importer(app).run(CsvPracticeSource(synthetic_file))
    assert report.rows == 10
    assert (report.created, report.updated, report.failed) == (7, 1, 2)   # Duplikat Alpha -> updated
    codes = {i.row: i.codes for i in report.issues}
    assert codes[9] == ["missing_name"] and codes[10] == ["invalid_plz"]
    assert "unknown_specialty" in codes[7] and "outside_territory" in codes[8]
    assert report.warnings["unknown_specialty"] == 1 and report.warnings["outside_territory"] == 1
    # Duplikat wurde gemerged: Alpha hat beide Ärzte-Einträge (3) und beide Fachrichtungs-Varianten (1 Code)
    alpha = app.knowledge_repo.find_practice_by_key("synth hausarztpraxis alpha|66111|teststrasse 1")
    assert len(app.knowledge_repo.doctors_of(alpha.id)) == 3
    assert [s.code for s in app.knowledge_repo.practice_specialties(alpha.id)] == ["allgemeinmedizin"]
    assert alpha.region == "saarland" and alpha.geo_precision.value == "place"
    # Berichte enthalten nur Zeilennummern + Codes
    assert "SYNTH" not in repr(report.issues)


def test_reimport_is_idempotent(app, synthetic_file):
    importer(app).run(CsvPracticeSource(synthetic_file))
    again = importer(app).run(CsvPracticeSource(synthetic_file))
    assert (again.created, again.updated, again.unchanged) == (0, 0, 8)
    assert app.conn.execute("SELECT count(*) FROM k_practice").fetchone()[0] == 7


def test_dry_run_writes_nothing(app, synthetic_file):
    report = importer(app).run(CsvPracticeSource(synthetic_file), dry_run=True)
    assert report.created == 7
    assert app.conn.execute("SELECT count(*) FROM k_practice").fetchone()[0] == 0
    assert app.audit.tail() == []


def test_audit_event_has_no_pii(app, synthetic_file):
    importer(app).run(CsvPracticeSource(synthetic_file))
    (event,) = app.audit.tail()
    assert event["event_type"] == "import.practices"
    assert "SYNTH" not in event["details"] and "SYNTH" not in event["summary"]


def test_roles_customers_and_prospects(app, synthetic_file):
    r = importer(app).run(CsvPracticeSource(synthetic_file), role="customers")
    assert r.customers_marked == 7
    r2 = importer(app).run(CsvPracticeSource(synthetic_file), role="prospects")
    assert r2.prospects_created == 0     # Kunden werden nicht zu Prospects
    assert app.conn.execute("SELECT count(*) FROM p_prospect").fetchone()[0] == 0


def test_generic_formats_comma_cp1252_combined_plz_ort_and_aliases(app, tmp_path):
    # Anderer Export: Komma, cp1252, andere Kopfzeilen, PLZ+Ort kombiniert, Straße/Hausnummer getrennt
    content = ("Account Name,Anschrift,Hausnummer,PLZ Ort,Fachgebiet,Homepage\n"
               "SYNTH Praxis Iota,Teststraße,12,66111 Saarbrücken,Hausarzt / Kardiologie,synth-iota.invalid\n")
    f = tmp_path / "export.dat"
    f.write_bytes(content.encode("cp1252"))
    src = CsvPracticeSource(f)
    assert src.delimiter == ","
    report = importer(app).run(src)
    assert report.created == 1 and not report.failed
    p = app.knowledge_repo.list_practices()[0]
    assert (p.street, p.plz, p.ort, p.website_url) == ("Teststraße 12", "66111", "Saarbrücken", "https://synth-iota.invalid")
    assert {s.code for s in app.knowledge_repo.practice_specialties(p.id)} == {"allgemeinmedizin", "kardiologie"}


def test_explicit_mapping_file(app, tmp_path):
    (tmp_path / "m.yaml").write_text("columns:\n  name: Einrichtungsbezeichnung\n  ort: Sitz\n", encoding="utf-8")
    (tmp_path / "x.txt").write_text("Einrichtungsbezeichnung;Sitz\nSYNTH Praxis Kappa;Trier\n", encoding="utf-8")
    src = CsvPracticeSource(tmp_path / "x.txt", load_mapping(tmp_path / "m.yaml"))
    assert importer(app).run(src).created == 1
    with pytest.raises(ConfigError):
        (tmp_path / "bad.yaml").write_text("columns:\n  wat: X\n")
        load_mapping(tmp_path / "bad.yaml")


def test_missing_name_column_gives_helpful_error(tmp_path):
    (tmp_path / "x.txt").write_text("Foo;Bar\n1;2\n", encoding="utf-8")
    with pytest.raises(ImportFailed) as exc:
        CsvPracticeSource(tmp_path / "x.txt")
    assert exc.value.code == "no_name_column" and "Foo" in exc.value.message


def test_extra_cells_are_reported_not_dropped(app, tmp_path):
    (tmp_path / "x.txt").write_text("Praxis;Ort\nSYNTH Praxis Lambda;Trier;überzählig\n", encoding="utf-8")
    report = importer(app).run(CsvPracticeSource(tmp_path / "x.txt"))
    assert report.failed == 1 and report.issues[0].codes == ["column_count_mismatch"]
