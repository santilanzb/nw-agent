"""
COQL literal safety.

Zoho's COQL endpoint takes a single `select_query` string and offers no bind
parameters, so genuine parametrization is not available. The only defence is
validating and escaping every value before it is interpolated — which matters
now that LLM-derived values are about to reach these queries.

Escaping verified live against Zoho on 2026-08-11:

    where Last_Name = 'O\\'Brien'   -> {"code":"SYNTAX_ERROR", "near":"Brien"}
    where Last_Name = 'O''Brien'    -> parses, returns []
    where id = '4806334000196115218' -> returns the record

So: a single quote is escaped by **doubling** it, not with a backslash, and
record ids may be quoted like any other literal.
"""
from __future__ import annotations

import re

# Zoho record ids are numeric strings, currently 18-19 digits. Anything else is a
# bug in the caller rather than a value to be escaped.
_ZOHO_ID = re.compile(r"^[0-9]{6,20}$")
_NON_DIGITS = re.compile(r"\D")


class CoqlValueError(ValueError):
    """A value cannot be safely placed into a COQL query."""


def quote(value: str) -> str:
    """
    Escape a value and wrap it as a COQL string literal.

    Doubling the quote is what Zoho actually accepts; a backslash is a syntax
    error. NUL is rejected outright — it has no valid escape and no legitimate
    source in a phone number, email or name.
    """
    if value is None:
        raise CoqlValueError("cannot quote None")
    text = str(value)
    if "\x00" in text:
        raise CoqlValueError("NUL byte in COQL literal")
    return "'" + text.replace("'", "''") + "'"


def record_id(value: str) -> str:
    """Validate a Zoho record id and return it as a quoted literal."""
    text = str(value).strip()
    if not _ZOHO_ID.match(text):
        raise CoqlValueError(f"not a Zoho record id: {value!r}")
    return quote(text)


def like_contains(value: str, *, digits_only: bool = False) -> str:
    """
    Build a quoted `%value%` LIKE pattern.

    `digits_only` strips everything but digits, which is what phone matching
    wants — it removes the wildcards along with the punctuation, so a caller
    cannot smuggle `%` or `_` into the pattern.
    """
    text = _NON_DIGITS.sub("", str(value)) if digits_only else str(value)
    if not text:
        raise CoqlValueError("empty LIKE pattern")
    return quote(f"%{text}%")


def limit(value: int, *, default: int = 5, maximum: int = 200) -> int:
    """Coerce and clamp a LIMIT. Interpolated bare, so it must be a real int."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return default
    return min(n, maximum)


def identifier(value: str, allowed: frozenset[str]) -> str:
    """
    Validate a module or field name against an explicit allowlist.

    Identifiers cannot be quoted, so an allowlist is the only safe form. Also
    guards the label-vs-api_name trap recorded in cerebro/facts.md: COQL resolves
    api_names only, and querying a label can silently return a different
    population rather than failing.
    """
    if value not in allowed:
        raise CoqlValueError(f"identifier {value!r} is not in the allowlist")
    return value
