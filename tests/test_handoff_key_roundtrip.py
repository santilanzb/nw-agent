"""
The handoff a human can actually take back.

Two paths write and read one row, and they used to spell the key differently:

  * agent-core opens the handoff with `event.conversation_key` — the raw wa_id
    with a `+`, deliberately uncanonicalized, because the reply address is
    derived from it (`transport/waha.py`).
  * an asesora's "@Gutty tomo +52…" resolves the canonical E.164
    (`fsm._target_phone`).

For a Mexican id carrying the legacy `1`, an Argentine id missing the mobile `9`
or an eight-digit Brazilian id, those are different strings. The claim matched no
row and answered "no tengo handoff activo"; the resume matched no row either, so
the row stayed `pending` and **Gutty stayed silent to that patient for the full
TTL while the team was told there was no case**. Venezuela is the one country
where both forms coincide — and every fixture in this repo was Venezuelan, which
is why a green test suite proved nothing here.

This runs against the real crm-adapter container, because the canonicalization
lives in its request models: an in-process fake would test the wrong boundary.
"""
from __future__ import annotations

import os

import httpx
import psycopg
import pytest
from _stack import SKIP_STACK, db_available, db_url, service_available

from company_agent.agent_core.fsm import _target_phone
from company_agent.common.phone import canonical_key

CRM_URL = os.environ["CRM_ADAPTER_URL"]
HEADERS = {"X-Internal-API-Key": os.environ["INTERNAL_API_KEY"]}
CLAIMER = "+584149253088"

pytestmark = pytest.mark.skipif(
    not (db_available() and service_available(CRM_URL)), reason=SKIP_STACK
)

# (label, what WhatsApp sends as the wa_id). Venezuela is the control: it passed
# before this fix and must keep passing after it.
ROUND_TRIP_CASES = [
    ("venezuela", "584145610594"),
    ("mexico with the legacy 1", "5215512345678"),
    ("argentina without the mobile 9", "541123456789"),
    ("brazil eight-digit local", "551187654321"),
]


def _post(path: str, payload: dict) -> httpx.Response:
    return httpx.post(f"{CRM_URL}{path}", json=payload, headers=HEADERS, timeout=10)


@pytest.fixture(autouse=True)
def _clean_rows():
    """Leave no handoff behind: a stale active row would mute a later test."""
    yield
    keys = [canonical_key("+" + wa_id) for _, wa_id in ROUND_TRIP_CASES]
    with psycopg.connect(db_url()) as conn:
        conn.execute("DELETE FROM handoff_state WHERE contact_phone = ANY(%s)", (keys,))


@pytest.mark.parametrize(("label", "wa_id"), ROUND_TRIP_CASES)
def test_the_asesora_can_claim_and_resume_what_the_dm_path_opened(label: str, wa_id: str) -> None:
    dm_key = "+" + wa_id                        # what fsm._fire_handoff sends
    typed = _target_phone(f"tomo +{wa_id}")     # what the group command resolves
    assert typed is not None, label

    created = _post(
        "/v1/handoff",
        {"contact_phone": dm_key, "reason": f"round-trip de prueba {label}", "priority": "normal"},
    )
    assert created.status_code == 200, created.text

    muted = _post("/v1/handoff/state/check", {"contact_phone": dm_key})
    assert muted.json()["active"] is True, f"{label}: the handoff never muted Gutty"

    claimed = _post(
        "/v1/handoff/claim",
        {"contact_phone": typed, "claimer_phone": CLAIMER, "claimer_name": "Asesora de prueba"},
    )
    assert claimed.json()["success"] is True, f"{label}: the claim found no row — {claimed.text}"

    resumed = _post("/v1/handoff/resume", {"contact_phone": typed})
    assert resumed.json()["success"] is True, f"{label}: the resume found no row — {resumed.text}"

    after = _post("/v1/handoff/state/check", {"contact_phone": dm_key})
    assert after.json()["active"] is False, f"{label}: Gutty is still muted after the resume"


@pytest.mark.parametrize(("label", "wa_id"), ROUND_TRIP_CASES)
def test_the_row_is_stored_under_the_canonical_key(label: str, wa_id: str) -> None:
    """
    One patient, one key, whichever caller opened the ticket. This is what makes
    the context package and the erasure join possible at all.
    """
    dm_key = "+" + wa_id
    created = _post(
        "/v1/handoff",
        {"contact_phone": dm_key, "reason": f"clave canónica {label}", "priority": "normal"},
    )
    assert created.status_code == 200, created.text

    with psycopg.connect(db_url()) as conn:
        rows = conn.execute(
            "SELECT contact_phone FROM handoff_state WHERE id = %s::uuid",
            (created.json()["handoff_id"],),
        ).fetchall()

    assert rows, f"{label}: no state row was written"
    assert rows[0][0] == canonical_key(dm_key), label


def test_a_phone_with_no_digits_is_refused() -> None:
    """The one key a handoff cannot hang on."""
    refused = _post("/v1/handoff/state/check", {"contact_phone": ""})
    assert refused.status_code == 422, refused.text
