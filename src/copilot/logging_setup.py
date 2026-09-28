from __future__ import annotations

import logging
import sys

from copilot.security.redaction import RedactingFilter


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("copilot")
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False
