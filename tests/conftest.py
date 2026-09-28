from __future__ import annotations

from pathlib import Path

import pytest

from copilot.app import App
from copilot.config import Settings

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings.from_env({
        "COPILOT_HOME": str(REPO),
        "COPILOT_CONFIG_DIR": str(REPO / "config"),
        "COPILOT_DATA_DIR": str(tmp_path / "data"),
        "COPILOT_ACTOR": "test",
    })


@pytest.fixture
def app(settings):
    a = App.open(settings)
    yield a
    a.close()


@pytest.fixture
def synthetic_file() -> Path:
    return FIXTURES / "synthetic_practices.txt"


@pytest.fixture
def scan_source() -> Path:
    return FIXTURES / "synthetic_scan_source.txt"
