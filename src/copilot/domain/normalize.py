"""Normalisierung für Dedupe/Matching. Nur deterministische String-Regeln, keine Heuristik-Magie."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def fold(text: str | None) -> str:
    """casefold, Umlaute -> ae/oe/ue/ss, Satzzeichen -> Leerzeichen, Whitespace kollabieren."""
    if not text:
        return ""
    text = text.casefold().translate(_UMLAUTS)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def fold_street(street: str | None) -> str:
    text = fold(street)
    text = re.sub(r"(?<=\w)str(?=\s|$)", "strasse", text)
    return re.sub(r"\bstr(?=\s|$)", "strasse", text)


def practice_key(name: str, plz: str | None, street: str | None) -> str:
    return f"{fold(name)}|{plz or ''}|{fold_street(street)}"


def doctor_key(full_name: str) -> str:
    return fold(full_name)


def normalize_url(raw: str | None) -> str | None:
    """Ergänzt fehlendes Schema (https), lehnt alles außer http(s) ab. Gibt None für leere Eingabe."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if "://" not in raw:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:(?!\d+(/|$))", raw):  # z. B. javascript:, mailto: (kein host:port)
            raise ValueError("only http(s) URLs are allowed")
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http(s) URLs are allowed")
    try:
        parts.port
    except ValueError as exc:
        raise ValueError("invalid port") from exc
    if parts.username or parts.password:
        raise ValueError("URLs with credentials are not allowed")
    return raw


_TITLE_TOKENS = {"dr", "med", "dent", "prof", "pd", "priv", "doz", "dipl", "univ", "habil", "rer", "nat", "phil", "mult"}


def split_doctor_name(raw: str) -> tuple[str | None, str]:
    """'Dr. med. Anna Muster' -> ('Dr. med.', 'Anna Muster'). Titel = führende Titel-Token."""
    tokens = raw.split()
    title: list[str] = []
    while len(tokens) > 1 and fold(tokens[0].rstrip(".")) in _TITLE_TOKENS | {"dipl med", "dipl", "med"}:
        title.append(tokens.pop(0))
    return (" ".join(title) or None, " ".join(tokens))
