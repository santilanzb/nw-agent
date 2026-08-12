"""
Two clocks, and a handoff that ends by itself.

A case nobody picks up and a case someone picked up are different failures. The
first is the team missing a patient and should surface fast; the second is an
asesora working, and restarting her clock at the claim is the only way a case
taken at hour 23 of a 24h window does not expire an hour later, mid-conversation.

Expiry itself was never invisible — `check_active` expires stale rows lazily on
read, so the patient's *next* message did get through. What was invisible was
everything else: a patient who never writes again leaves the row `claimed`
forever, and nobody is ever told a case was dropped. The sweep makes the
transition happen on a clock and hand back what it changed, so agent-core can
say so in the team group.

Talks to the store directly — it is synchronous, so this needs no event loop —
and to the crm-adapter container for the endpoint.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import psycopg
import pytest
from _stack import SKIP_DB, SKIP_STACK, db_available, db_url, service_available

from company_agent.common.handoff_state import HandoffStateStore

pytestmark = pytest.mark.skipif(not db_available(), reason=SKIP_DB)

CRM_URL = os.environ["CRM_ADAPTER_URL"]
HEADERS = {"X-Internal-API-Key": os.environ["INTERNAL_API_KEY"]}

PHONE = "+584145550001"
CLAIMER = "+584149253088"


@pytest.fixture
def store() -> HandoffStateStore:
    return HandoffStateStore(db_url(), pending_expire_hours=4, claimed_expire_hours=24)


@pytest.fixture(autouse=True)
def _clean():
    def wipe() -> None:
        with psycopg.connect(db_url()) as conn:
            conn.execute("DELETE FROM handoff_state WHERE contact_phone = %s", (PHONE,))

    wipe()
    yield
    wipe()


def _hours_out(when: datetime) -> float:
    return (when - datetime.now(UTC)).total_seconds() / 3600


def test_an_unclaimed_case_runs_on_the_short_clock(store: HandoffStateStore) -> None:
    created = store.create(contact_phone=PHONE, reason="nadie lo ha tomado")
    assert 3.9 < _hours_out(created.expires_at) <= 4.0


def test_the_clock_restarts_when_someone_takes_the_case(store: HandoffStateStore) -> None:
    """
    The bug this closes: a case claimed at the last minute of the window used to
    expire minutes later, pulling Gutty back into a live human conversation.
    """
    store.create(contact_phone=PHONE, reason="lo van a tomar")

    with psycopg.connect(db_url()) as conn:
        conn.execute(
            "UPDATE handoff_state SET expires_at = NOW() + INTERVAL '1 minute' "
            "WHERE contact_phone = %s",
            (PHONE,),
        )

    claimed = store.claim(contact_phone=PHONE, claimer_phone=CLAIMER, claimer_name="Ana")
    assert claimed is not None
    assert 23.9 < _hours_out(claimed.expires_at) <= 24.0


# ── The sweep ────────────────────────────────────────────────────────────────

def _past_due(status: str = "pending") -> str:
    """A row whose window ran out while nobody was looking."""
    with psycopg.connect(db_url()) as conn:
        row = conn.execute(
            """
            INSERT INTO handoff_state (contact_phone, status, reason, priority, expires_at,
                                       claimed_by_name)
            VALUES (%s, %s, 'prueba de expiración', 'normal', NOW() - INTERVAL '1 hour', %s)
            RETURNING id
            """,
            (PHONE, status, "Ana" if status == "claimed" else None),
        ).fetchone()
    return str(row[0])


def test_the_sweep_reports_what_it_expired(store: HandoffStateStore) -> None:
    handoff_id = _past_due("claimed")

    # The sweep is global by nature, so every assertion here is scoped to this
    # test's own number — anything else would be a claim about the whole table.
    swept = [r for r in store.sweep_expired() if r.contact_phone == PHONE]

    assert [r.id for r in swept] == [handoff_id]
    assert swept[0].previous_status == "claimed"
    assert swept[0].claimed_by_name == "Ana"


def test_the_sweep_is_the_only_one_to_report_a_row(store: HandoffStateStore) -> None:
    """
    Whoever flips the row owns the announcement. If a second pass could report
    the same row, the team would be told twice that one case was dropped.
    """
    _past_due()

    assert len([r for r in store.sweep_expired() if r.contact_phone == PHONE]) == 1
    assert [r for r in store.sweep_expired() if r.contact_phone == PHONE] == []


def test_an_expired_case_stops_muting_the_patient(store: HandoffStateStore) -> None:
    _past_due("claimed")
    store.sweep_expired()
    assert store.check_active(PHONE) is None


def test_a_live_case_is_left_alone(store: HandoffStateStore) -> None:
    store.create(contact_phone=PHONE, reason="todavía dentro de la ventana")
    assert [r for r in store.sweep_expired() if r.contact_phone == PHONE] == []
    assert store.check_active(PHONE) is not None


@pytest.mark.skipif(not service_available(CRM_URL), reason=SKIP_STACK)
def test_the_sweep_endpoint_answers_with_the_same_shape() -> None:
    handoff_id = _past_due()

    resp = httpx.post(f"{CRM_URL}/v1/handoff/sweep", headers=HEADERS, timeout=10)

    assert resp.status_code == 200, resp.text
    mine = [r for r in resp.json()["expired"] if r["handoff_id"] == handoff_id]
    assert len(mine) == 1
    assert mine[0]["previous_status"] == "pending"
    assert mine[0]["contact_phone"] == PHONE
