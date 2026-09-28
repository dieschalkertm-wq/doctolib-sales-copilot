import logging
import subprocess
from pathlib import Path

import pytest

from copilot.config import Settings, load_dotenv, load_env, load_policies
from copilot.errors import ConfigError
from copilot.logging_setup import configure_logging
from copilot.security.redaction import redact
from copilot.security.secrets import Secret, assert_no_secret_keys, get_secret

REPO = Path(__file__).resolve().parents[1]


def test_redaction():
    text = "mail a.b@praxis.de tel +49 681 123456 api_key=abc123 sk-abcdefghijklmnopqrstuvwx ok 2026-09-28 66111"
    out = redact(text)
    assert "praxis.de" not in out and "123456" not in out and "abc123" not in out and "sk-abc" not in out
    assert "2026-09-28" in out and "66111" in out          # Daten/PLZ bleiben lesbar


def test_logging_filter_redacts_and_hides_tracebacks(capfd):
    configure_logging("INFO")
    log = logging.getLogger("copilot.test")
    try:
        raise ValueError("geheim: max@example.com")
    except ValueError:
        log.error("fehler bei %s", "erika@example.com", exc_info=True)
    err = capfd.readouterr().err
    assert "example.com" not in err and "[EMAIL]" in err and "exc=ValueError" in err and "Traceback" not in err


def test_secret_never_printed():
    s = Secret("topsecret")
    assert "topsecret" not in repr(s) and "topsecret" not in f"{s}" and s.reveal() == "topsecret"
    assert get_secret("NOPE", {}) is None
    with pytest.raises(ConfigError):
        get_secret("NOPE", {}, required=True)


def test_config_files_may_not_contain_secret_keys():
    with pytest.raises(ConfigError):
        assert_no_secret_keys({"research": {"api_key": "x"}})
    for f in (REPO / "config").glob("*.yaml"):                      # committete Konfig ist sauber
        import yaml
        assert_no_secret_keys(yaml.safe_load(f.read_text(encoding="utf-8")), f.name)


def test_env_precedence_and_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# c\nCOPILOT_LOG_LEVEL=DEBUG\nCOPILOT_ACTOR='tim'\n", encoding="utf-8")
    assert load_dotenv(tmp_path / ".env") == {"COPILOT_LOG_LEVEL": "DEBUG", "COPILOT_ACTOR": "tim"}
    monkeypatch.setenv("COPILOT_ACTOR", "override")
    env = load_env(tmp_path)
    assert env["COPILOT_ACTOR"] == "override" and env["COPILOT_LOG_LEVEL"] == "DEBUG"
    assert Settings.from_env({"COPILOT_HOME": str(tmp_path)}).data_dir == (tmp_path / "data").resolve()


def test_default_policy_blocks_all_domains():
    assert load_policies(REPO / "config").research.allowed_domains == []


def test_gitignore_still_protects_sensitive_paths():
    for path in (".env", ".env.local", "data/copilot.sqlite3", "export.csv", "kunden.xlsx", "x.sqlite", "secrets/key.pem", "logs/a.log"):
        r = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO)
        assert r.returncode == 0, f"{path} muss ignoriert sein"
    assert subprocess.run(["git", "check-ignore", "-q", ".env.example"], cwd=REPO).returncode == 1


def test_no_tracked_secret_or_data_files():
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split()
    assert not [t for t in tracked if t.endswith((".sqlite3", ".sqlite", ".db", ".csv", ".xlsx", ".pem", ".key")) or t == ".env"]
