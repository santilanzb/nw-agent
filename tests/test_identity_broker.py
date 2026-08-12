"""
Identity resolution against a real Postgres.

The behaviour worth pinning is what happens when the system is *unsure*.
`ZohoClient.find_by_phone` ends with `return rows[0]` when a suffix match hits
several records — it picks a patient and says nothing. `identity_registry`
replaces that with a row a human resolves.
"""
from __future__ import annotations

import asyncio
import random
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import psycopg
import pytest
from _stack import SKIP_DB, db_available, db_url

from company_agent.agent_core.identity import IdentityBroker, canonicalize
from company_agent.common.db import make_async_pool

pytestmark = pytest.mark.skipif(not db_available(), reason=SKIP_DB)

# psycopg's async driver hangs rather than errors on Windows' ProactorEventLoop.
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


def _wa_id() -> str:
    """A fresh Venezuelan mobile per test — identities persist across runs."""
    return f"58414{random.randint(1000000, 9999999)}"


def _query(sql: str, params: tuple) -> list[tuple]:
    with psycopg.connect(db_url()) as conn:
        return conn.execute(sql, params).fetchall()


def test_a_new_number_gets_an_identity() -> None:
    wa_id = _wa_id()

    async def scenario(pool):
        return await IdentityBroker(pool).resolve(canonicalize(wa_id), display_name="Ana")

    record = run_with_pool(scenario)
    assert record is not None
    assert record.wa_id == wa_id
    assert record.phone_e164 == f"+{wa_id}"
    assert record.merge_state == "active"
    assert not record.needs_review


def test_the_same_number_resolves_to_the_same_identity() -> None:
    """Idempotent by construction — every inbound turn calls this."""
    wa_id = _wa_id()

    async def scenario(pool):
        broker = IdentityBroker(pool)
        first = await broker.resolve(canonicalize(wa_id))
        second = await broker.resolve(canonicalize(wa_id))
        return first, second

    first, second = run_with_pool(scenario)
    assert first.id == second.id


def test_formatting_differences_do_not_create_a_second_identity() -> None:
    digits = _wa_id()
    formatted = f"+{digits[:2]} {digits[2:5]}-{digits[5:]}"

    async def scenario(pool):
        broker = IdentityBroker(pool)
        return (
            await broker.resolve(canonicalize(digits)),
            await broker.resolve(canonicalize(formatted)),
        )

    plain, spaced = run_with_pool(scenario)
    assert plain.id == spaced.id


def test_concurrent_first_turns_produce_one_identity() -> None:
    """
    Two messages from a new number arriving together. The webhook spawns turns
    without waiting, so this races in production.
    """
    wa_id = _wa_id()

    async def scenario(pool):
        broker = IdentityBroker(pool)
        return await asyncio.gather(
            *(broker.resolve(canonicalize(wa_id)) for _ in range(5))
        )

    records = run_with_pool(scenario)
    assert len({r.id for r in records}) == 1

    rows = _query("select count(*) from identity_registry where wa_id = %s", (wa_id,))
    assert rows[0][0] == 1


def test_two_addresses_for_one_number_are_flagged_rather_than_merged() -> None:
    """
    A Mexican number reaching us as 52... and as 521... is one E.164 and two
    addresses. Guessing which is 'the' identity is what `return rows[0]` did.
    """
    local = f"55{random.randint(10000000, 99999999)}"
    without_one = f"52{local}"
    with_one = f"521{local}"
    assert canonicalize(with_one).e164 == canonicalize(without_one).e164

    async def scenario(pool):
        broker = IdentityBroker(pool)
        first = await broker.resolve(canonicalize(without_one))
        second = await broker.resolve(canonicalize(with_one))
        return first, second

    first, second = run_with_pool(scenario)

    assert first.id != second.id, "distinct addresses stay distinct rows"
    assert second.needs_review, "the second address must be flagged, not silently merged"

    rows = _query(
        "select merge_state from identity_registry where id = %s", (first.id,)
    )
    assert rows[0][0] == "review", "the original is flagged too — a human decides"


def test_an_unparseable_number_is_stored_for_review_not_dropped() -> None:
    junk = f"9{random.randint(100000, 999999)}"

    async def scenario(pool):
        return await IdentityBroker(pool).resolve(canonicalize(junk))

    record = run_with_pool(scenario)
    assert record is not None
    assert record.needs_review


def test_an_empty_number_resolves_to_nothing() -> None:
    async def scenario(pool):
        return await IdentityBroker(pool).resolve(canonicalize(""))

    assert run_with_pool(scenario) is None
