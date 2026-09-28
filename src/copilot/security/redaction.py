"""PII-/Secret-Redaction für Logs (Allowlist-Logging bleibt Grundprinzip, das hier ist das Netz darunter)."""

from __future__ import annotations

import logging
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w-])(?:\+|00|0)\d[\d\s/().-]{6,}\d")
_KEYVAL = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization)\b\s*[=:]\s*\S+")
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def redact(text: str) -> str:
    text = _KEYVAL.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _SK.sub("[REDACTED]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE.sub("[PHONE]", text)
    return text


class RedactingFilter(logging.Filter):
    """Redigiert Nachricht und unterdrückt Traceback-Inhalte (nur Exception-Typ bleibt)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact(record.getMessage())
        if record.exc_info and record.exc_info[0] is not None:
            message += f" [exc={record.exc_info[0].__name__}]"
        record.msg, record.args = message, ()
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True
