"""
COQL injection guards.

Zoho's COQL endpoint has no bind parameters — the body is one `select_query`
string — so every value is interpolated and validation is the only defence.
These queries are about to receive LLM-derived values.

The escaping rule was verified live against Zoho on 2026-08-11: a single quote is
escaped by doubling it; the backslash form returns SYNTAX_ERROR.
"""
from __future__ import annotations

import pytest

from company_agent.crm_adapter import coql
from company_agent.crm_adapter.zoho_client import ZohoClient

# ── quote ─────────────────────────────────────────────────────────────────────

def test_quote_doubles_single_quotes() -> None:
    assert coql.quote("O'Brien") == "'O''Brien'"


def test_quote_neutralises_a_query_breaking_payload() -> None:
    hostile = "x' OR '1'='1"
    quoted = coql.quote(hostile)
    # The payload survives as data, and every quote inside it is doubled, so it
    # cannot close the literal it sits in.
    assert quoted == "'x'' OR ''1''=''1'"
    assert quoted.startswith("'")
    assert quoted.endswith("'")
    assert quoted.count("'") % 2 == 0


def test_quote_rejects_nul() -> None:
    with pytest.raises(coql.CoqlValueError):
        coql.quote("bad\x00value")


def test_quote_rejects_none() -> None:
    with pytest.raises(coql.CoqlValueError):
        coql.quote(None)


# ── record_id ─────────────────────────────────────────────────────────────────

def test_record_id_accepts_a_real_zoho_id() -> None:
    assert coql.record_id("4806334000196115218") == "'4806334000196115218'"


@pytest.mark.parametrize(
    "hostile",
    [
        "1 OR 1=1",
        "123'; delete from Contacts; --",
        "abc",
        "",
        "12345678901234567890123456",  # too long to be an id
    ],
)
def test_record_id_rejects_anything_that_is_not_an_id(hostile: str) -> None:
    with pytest.raises(coql.CoqlValueError):
        coql.record_id(hostile)


# ── like_contains ─────────────────────────────────────────────────────────────

def test_like_contains_strips_wildcards_from_phone_input() -> None:
    """digits_only removes % and _ along with the punctuation, so a caller
    cannot widen the pattern."""
    assert coql.like_contains("%_5610594", digits_only=True) == "'%5610594%'"


def test_like_contains_rejects_an_empty_pattern() -> None:
    with pytest.raises(coql.CoqlValueError):
        coql.like_contains("no-digits-here", digits_only=True)


# ── limit ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("value", "expected"),
    [(5, 5), (0, 5), (-3, 5), ("7", 7), ("; drop", 5), (10_000, 200), (None, 5)],
)
def test_limit_coerces_and_clamps(value: object, expected: int) -> None:
    assert coql.limit(value) == expected


# ── identifier ────────────────────────────────────────────────────────────────

def test_identifier_requires_an_allowlist_entry() -> None:
    allowed = frozenset({"Contacts", "Leads"})
    assert coql.identifier("Leads", allowed) == "Leads"
    with pytest.raises(coql.CoqlValueError):
        coql.identifier("Contactos", allowed)  # a label, not an api_name


# ── The queries the client actually builds ───────────────────────────────────

class _CapturingClient(ZohoClient):
    """Captures the query instead of sending it."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def coql(self, query: str) -> list[dict]:  # type: ignore[override]
        self.queries.append(query)
        return []


def test_hostile_email_cannot_escape_its_literal() -> None:
    client = _CapturingClient()
    client.find_contact_by_email("a' OR Email like '%")

    query = client.queries[0]
    assert "'a'' OR Email like ''%'" in query
    # One WHERE, one comparison — the payload did not add a clause.
    assert query.count("WHERE") == 1
    assert " OR " not in query.replace("'a'' OR Email like ''%'", "")


def test_hostile_contact_id_is_rejected_before_any_query_is_built() -> None:
    client = _CapturingClient()
    with pytest.raises(coql.CoqlValueError):
        client.list_deals_for_contact("1 OR 1=1")
    assert client.queries == []


def test_phone_lookup_uses_the_normalized_suffix() -> None:
    """A formatted number must produce the same 9-digit suffix as a bare one."""
    bare = _CapturingClient()
    bare.find_contact_by_phone("+584145610594")
    formatted = _CapturingClient()
    formatted.find_contact_by_phone("+58 414-5610594")

    assert "'%145610594%'" in bare.queries[0]
    assert bare.queries[0] == formatted.queries[0]
