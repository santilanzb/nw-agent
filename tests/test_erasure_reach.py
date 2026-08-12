"""
What an Art. 17 erasure reaches, and what it must not take with it.

Deleting an `identity_registry` row is the shape the Phase 6 erasure takes. Two
things have to be true at once, and they pull in opposite directions:

  * the conversation memory goes — episodes, summaries, facts, media (CASCADE)
  * the ledgers stay — inbox, outbox, ticket, turn_log (SET NULL)

The second half is not squeamishness about audit trails. Each of those rows
carries an idempotency key: drop the `intake_events` row and a redelivered
webhook is processed as new; drop the `send_intents` row and a re-driven turn
messages the person who just asked to be forgotten.

Before this, none of the three had any foreign key at all — the delete would have
run, reported success, and left the patient's own words in `intake_events.payload`
with no key to find them by. That is what the Phase 6 drill was going to discover.

Needs Postgres with the Stage 0 substrate at revision 0006.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from _stack import SKIP_DB, db_available, db_url

from company_agent.agent_core.identity import IdentityBroker, canonicalize
from company_agent.common.db import make_async_pool

pytestmark = pytest.mark.skipif(not db_available(), reason=SKIP_DB)

# psycopg's async driver will not run on Windows' default ProactorEventLoop, and
# the pool then retries forever — a hang, not an error.
_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None

PHONE = "+584149876543"

CASCADES = ("patient_episodes", "media_artifacts")
SURVIVES = ("intake_events", "send_intents", "handoff_state")


def run_with_pool[T](fn: Callable[[Any], Awaitable[T]]) -> T:
    async def main() -> T:
        pool = make_async_pool(db_url(), min_size=1, max_size=3)
        await pool.open(wait=True, timeout=10)
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return asyncio.run(main(), loop_factory=_LOOP_FACTORY)


async def _seed(pool: Any, identity_id: uuid.UUID, key: str) -> None:
    """One row in every table that carries a patient's data."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO intake_events (source, source_event_id, payload, identity_id)
            VALUES ('test', %s, '{"payload": {"body": "me duele el estómago"}}', %s)
            """,
            (f"erasure-{key}", identity_id),
        )
        await conn.execute(
            """
            INSERT INTO send_intents (idempotency_key, transport, recipient,
                                      message_class, body_text, identity_id)
            VALUES (%s, 'waha', '584149876543@c.us', 'reply', 'ya te contacto 🩵', %s)
            """,
            (f"erasure-{key}", identity_id),
        )
        await conn.execute(
            """
            INSERT INTO handoff_state (contact_phone, status, reason, priority, expires_at, identity_id)
            VALUES (%s, 'pending', 'erasure-test', 'normal', NOW() + INTERVAL '1 hour', %s)
            """,
            (PHONE, identity_id),
        )
        await conn.execute(
            """
            INSERT INTO patient_episodes (identity_id, contact_phone, direction, text, turn_id)
            VALUES (%s, %s, 'inbound', 'me duele el estómago', gen_random_uuid())
            """,
            (identity_id, PHONE),
        )
        await conn.execute(
            """
            INSERT INTO media_artifacts (identity_id, source, kind, storage_path)
            VALUES (%s, 'waha', 'image', '2026/08/12/receipt.jpg')
            """,
            (identity_id,),
        )


async def _counts(pool: Any, identity_id: uuid.UUID, key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    async with pool.connection() as conn:
        for table in CASCADES:
            cur = await conn.execute(
                f"SELECT count(*) AS n FROM {table} WHERE identity_id = %s", (identity_id,)
            )
            out[table] = (await cur.fetchone())["n"]
        cur = await conn.execute(
            "SELECT count(*) AS n FROM intake_events WHERE source_event_id = %s", (f"erasure-{key}",)
        )
        out["intake_events"] = (await cur.fetchone())["n"]
        cur = await conn.execute(
            "SELECT count(*) AS n FROM send_intents WHERE idempotency_key = %s", (f"erasure-{key}",)
        )
        out["send_intents"] = (await cur.fetchone())["n"]
        cur = await conn.execute(
            "SELECT count(*) AS n FROM handoff_state WHERE contact_phone = %s", (PHONE,)
        )
        out["handoff_state"] = (await cur.fetchone())["n"]
    return out


async def _cleanup(pool: Any, key: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM intake_events WHERE source_event_id = %s", (f"erasure-{key}",))
        await conn.execute("DELETE FROM send_intents WHERE idempotency_key = %s", (f"erasure-{key}",))
        await conn.execute("DELETE FROM handoff_state WHERE contact_phone = %s", (PHONE,))


def test_erasure_takes_the_memory_and_leaves_the_ledgers() -> None:
    key = uuid.uuid4().hex[:12]

    async def scenario(pool: Any) -> tuple[dict[str, int], dict[str, int], list[Any]]:
        identity = await IdentityBroker(pool).resolve(canonicalize(PHONE))
        assert identity is not None
        await _seed(pool, identity.id, key)
        before = await _counts(pool, identity.id, key)

        async with pool.connection() as conn:
            await conn.execute("DELETE FROM identity_registry WHERE id = %s", (identity.id,))

        after = await _counts(pool, identity.id, key)

        async with pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT (SELECT identity_id FROM intake_events WHERE source_event_id = %s) AS inbox,
                       (SELECT identity_id FROM send_intents WHERE idempotency_key = %s) AS outbox,
                       (SELECT identity_id FROM handoff_state WHERE contact_phone = %s) AS ticket
                """,
                (f"erasure-{key}", f"erasure-{key}", PHONE),
            )
            orphans = list((await cur.fetchone()).values())

        await _cleanup(pool, key)
        return before, after, orphans

    before, after, orphans = run_with_pool(scenario)

    # Everything was reachable by the key in the first place — the whole point.
    assert all(before[t] == 1 for t in CASCADES + SURVIVES), before

    # The conversation is gone.
    assert all(after[t] == 0 for t in CASCADES), after

    # The ledgers, and their idempotency keys, are not.
    assert all(after[t] == 1 for t in SURVIVES), after

    # ...and they no longer point at a person.
    assert orphans == [None, None, None]
