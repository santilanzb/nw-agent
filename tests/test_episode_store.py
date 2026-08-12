"""
Conversational memory against a real Postgres.

`patient_episodes` had a schema and no readers or writers since the baseline.
The ordering is the part worth pinning: history reaches the prompt as a
transcript, so it must arrive oldest-first even though the index that makes the
query cheap is newest-first.
"""
from __future__ import annotations

import asyncio
import random
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from _stack import SKIP_DB, db_available, db_url

from company_agent.agent_core.brain.episodes import EpisodeStore
from company_agent.agent_core.identity import IdentityBroker, canonicalize
from company_agent.common.db import make_async_pool

pytestmark = pytest.mark.skipif(not db_available(), reason=SKIP_DB)

_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None


def run_with_pool[T](fn: Callable[[Any], Awaitable[T]]) -> T:
    async def main() -> T:
        pool = make_async_pool(db_url(), min_size=1, max_size=3)
        await pool.open(wait=True, timeout=10)
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return asyncio.run(main(), loop_factory=_LOOP_FACTORY)


def _phone() -> str:
    return f"+58414{random.randint(1_000_000, 9_999_999)}"


def test_a_turn_is_recorded_as_both_halves() -> None:
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = EpisodeStore(pool)
        await store.record(
            identity_id=identity.id,
            contact_phone=phone,
            turn_id=uuid.uuid4(),
            inbound_text="tienen plan de 3 consultas?",
            reply_text="Sí, cuesta $559.",
            intent="faq_consultation_plans",
            task="customer_service",
        )
        return await store.recent(identity.id)

    episodes = run_with_pool(scenario)
    assert [(e.direction, e.text) for e in episodes] == [
        ("inbound", "tienen plan de 3 consultas?"),
        ("outbound", "Sí, cuesta $559."),
    ]


def test_history_reads_oldest_first() -> None:
    """A transcript in the wrong order is worse than no transcript."""
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = EpisodeStore(pool)
        for i in range(4):
            await store.record(
                identity_id=identity.id,
                contact_phone=phone,
                turn_id=uuid.uuid4(),
                inbound_text=f"pregunta {i}",
                reply_text=f"respuesta {i}",
            )
        return await store.recent(identity.id, limit=4)

    episodes = run_with_pool(scenario)
    # The most recent 4 of 8 halves — turns 2 and 3, each patient-then-Gutty.
    assert [e.text for e in episodes] == [
        "pregunta 2",
        "respuesta 2",
        "pregunta 3",
        "respuesta 3",
    ]


def test_a_silent_turn_records_only_what_the_patient_said() -> None:
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = EpisodeStore(pool)
        await store.record(
            identity_id=identity.id,
            contact_phone=phone,
            turn_id=uuid.uuid4(),
            inbound_text="ok gracias",
            reply_text=None,
        )
        return await store.recent(identity.id)

    episodes = run_with_pool(scenario)
    assert [e.direction for e in episodes] == ["inbound"]


def test_one_conversation_never_sees_another() -> None:
    """A wrong history is worse than none — the model would answer confidently."""
    first, second = _phone(), _phone()

    async def scenario(pool):
        broker, store = IdentityBroker(pool), EpisodeStore(pool)
        a = await broker.resolve(canonicalize(first))
        b = await broker.resolve(canonicalize(second))
        await store.record(
            identity_id=a.id,
            contact_phone=first,
            turn_id=uuid.uuid4(),
            inbound_text="soy la paciente A",
            reply_text=None,
        )
        return await store.recent(b.id)

    assert run_with_pool(scenario) == []


def test_an_unknown_identity_has_no_history() -> None:
    async def scenario(pool):
        return await EpisodeStore(pool).recent(None)

    assert run_with_pool(scenario) == []


def test_erasing_an_identity_takes_its_memory_with_it() -> None:
    """
    Migration 0004 makes the FK ON DELETE CASCADE, unlike turn_log's SET NULL:
    conversation memory is the thing Art. 17 erases, turn_log is the audit trail
    it is measured against.
    """
    phone = _phone()

    async def scenario(pool):
        identity = await IdentityBroker(pool).resolve(canonicalize(phone))
        store = EpisodeStore(pool)
        await store.record(
            identity_id=identity.id,
            contact_phone=phone,
            turn_id=uuid.uuid4(),
            inbound_text="dato personal",
            reply_text="respuesta",
        )
        before = len(await store.recent(identity.id))
        async with pool.connection() as conn:
            await conn.execute(
                "DELETE FROM identity_registry WHERE id = %s", (identity.id,)
            )
        after = len(await store.recent(identity.id))
        return before, after

    before, after = run_with_pool(scenario)
    assert before == 2
    assert after == 0
