"""Strukturierte Fehler. Meldungen enthalten keine personenbezogenen Daten."""

from __future__ import annotations

from typing import Any


class CopilotError(Exception):
    code = "copilot_error"
    exit_code = 1

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "details": self.details}


class ConfigError(CopilotError):
    code, exit_code = "config_error", 2


class ValidationFailed(CopilotError):
    code, exit_code = "validation_failed", 3


class NotFound(CopilotError):
    code, exit_code = "not_found", 4


class IntegrityViolation(CopilotError):
    code, exit_code = "integrity_violation", 5


class PolicyViolation(CopilotError):
    """Aktion durch Policy-Gate (Domain, robots.txt, Automatisierungsstufe …) blockiert."""

    code, exit_code = "policy_violation", 6


class FetchError(CopilotError):
    code, exit_code = "fetch_error", 7


class ImportFailed(CopilotError):
    code, exit_code = "import_failed", 8
