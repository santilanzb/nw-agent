"""
Integration tests for the durable inbox and the send outbox.

These need a real Postgres — the behaviour under test is the constraint and the
locking, which a mock cannot express. Skipped when no database is reachable:

    docker compose up -d postgres
    alembic upgrade head
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from company_agent.agent_core.ingress.inbox import InboxWriter
from company_agent.agent_core.outbox.sender import SendOutbox
from company_agent.agent_core.transport.base import InboundEvent
from company_agent.common.db import make_async_pool

DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://agent:agent@localhost:5432/company_agent"),
)

def _db_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DB_URL, connect_timeout=3) as conn:
            conn.execute("select 1 from intake_events limit 1")
        return True
    except Exception:  # noqa: BLE001 - any failure at all means "skip these tests"
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="no Postgres with the Stage 0 schema; run docker compose up -d postgres && alembic upgrade head",
)


# psycopg refuses to run async on Windows' default ProactorEventLoop, and
# AsyncConnectionPool then retries the failing connection forever rather than
# raising — the failure mode is a hang, not an error. Linux (where the services
# actually run) needs none of this.
_LOOP_FACTORY = asyncio.SelectorEventLoop if sys.platform == "win32" else None


def run_with_pool[T](fn: Callable[[Any], Awaitable[T]]) -> T:
    """Each test gets its own loop and pool; a pool outlives neither."""

    async def main() -> T:
        pool = make_async_pool(DB_URL, min_size=1, max_size=3)
        # wait+timeout so a bad URL fails the test instead of hanging it.
        await pool.open(wait=True, timeout=10)
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return asyncio.run(main(), loop_factory=_LOOP_FACTORY)


def _event(source_event_id: str, text: str = "hola") -> InboundEvent:
    return InboundEvent(
        source="test",
        source_event_id=source_event_id,
        conversation_key="+584145610594",
        text=text,
        sender_e164="+584145610594",
        raw={"event": "message", "payload": {"id": source_event_id, "body": text}},
    )


class _FakeTransport:
    name = "waha"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self._fail = fail

    def verify(self, body: bytes, headers: Any) -> bool:
        return True

    def normalize(self, raw: dict[str, Any]) -> InboundEvent | None:
        return None

    def address_for(self, e164: str) -> str:
        return e164

    async def send_text(self, address: str, text: str) -> str | None:
        if self._fail:
            raise RuntimeError("transport exploded")
        self.sent.append((address, text))
        return f"provider-{len(self.sent)}"

    async def aclose(self) -> None:
        return None


# ── Inbox ────────────────────────────────────────────────────────────────────

def test_redelivery_is_a_no_op() -> None:
    """The regression: _SEEN was per-process, so a redelivery after a restart
    double-answered the patient."""
    eid = f"evt-{uuid.uuid4()}"

    async def scenario(pool: Any) -> tuple[Any, Any]:
        inbox = InboxWriter(pool)
        first = await inbox.record(_event(eid))
        second = await inbox.record(_event(eid))
        return first, second

    first, second = run_with_pool(scenario)
    assert first is not None
    assert second is None


def test_unfinished_event_is_reclaimed_by_the_sweeper() -> None:
    eid = f"evt-{uuid.uuid4()}"

    async def scenario(pool: Any) -> list[Any]:
        inbox = InboxWriter(pool)
        await inbox.record(_event(eid))
        # Never marked processed — the process died mid-turn.
        claimed = await inbox.claim_stale(limit=50, pending_grace_seconds=0)
        return [row for row in claimed if row.source_event_id == eid]

    mine = run_with_pool(scenario)
    assert len(mine) == 1
    assert mine[0].attempts == 1


def test_processed_events_are_not_reclaimed() -> None:
    eid = f"evt-{uuid.uuid4()}"

    async def scenario(pool: Any) -> list[Any]:
        inbox = InboxWriter(pool)
        row_id = await inbox.record(_event(eid))
        await inbox.mark_processed(row_id, uuid.uuid4())
        claimed = await inbox.claim_stale(limit=50, pending_grace_seconds=0)
        return [row for row in claimed if row.source_event_id == eid]

    assert run_with_pool(scenario) == []


def test_a_poison_event_is_retired_rather_than_re_driven_forever() -> None:
    eid = f"evt-{uuid.uuid4()}"

    async def scenario(pool: Any) -> str:
        inbox = InboxWriter(pool, max_attempts=2)
        row_id = await inbox.record(_event(eid))
        for _ in range(3):
            await inbox.mark_processing(row_id)
            await inbox.mark_failed(row_id, "boom")
        async with pool.connection() as conn:
            cur = await conn.execute(
                "select status from intake_events where id = %s", (row_id,)
            )
            return (await cur.fetchone())["status"]

    assert run_with_pool(scenario) == "failed"


# ── Outbox ───────────────────────────────────────────────────────────────────

def test_send_records_then_dispatches() -> None:
    key = f"turn:{uuid.uuid4()}:0"

    async def scenario(pool: Any) -> tuple[Any, Any, list[Any]]:
        wire = _FakeTransport()
        outbox = SendOutbox(pool, {"waha": wire})
        result = await outbox.send(
            transport="waha",
            recipient="+584145610594",
            text="hola",
            message_class="reply",
            idempotency_key=key,
        )
        async with pool.connection() as conn:
            cur = await conn.execute(
                "select status, provider_message_id from send_intents where idempotency_key = %s",
                (key,),
            )
            row = await cur.fetchone()
        return result, row, wire.sent

    result, row, sent = run_with_pool(scenario)
    assert result.sent is True
    assert row["status"] == "dispatched"
    assert row["provider_message_id"] == "provider-1"
    assert sent == [("+584145610594", "hola")]


def test_same_idempotency_key_does_not_send_twice() -> None:
    key = f"turn:{uuid.uuid4()}:0"

    async def scenario(pool: Any) -> tuple[Any, list[Any]]:
        wire = _FakeTransport()
        outbox = SendOutbox(pool, {"waha": wire})
        for _ in range(3):
            last = await outbox.send(
                transport="waha",
                recipient="+584145610594",
                text="hola",
                message_class="reply",
                idempotency_key=key,
            )
        return last, wire.sent

    last, sent = run_with_pool(scenario)
    assert last.sent is False
    assert last.skipped_reason == "duplicate"
    assert len(sent) == 1


def test_transport_failure_is_recorded_not_raised() -> None:
    key = f"turn:{uuid.uuid4()}:0"

    async def scenario(pool: Any) -> Any:
        outbox = SendOutbox(pool, {"waha": _FakeTransport(fail=True)})
        await outbox.send(
            transport="waha",
            recipient="+584145610594",
            text="hola",
            message_class="reply",
            idempotency_key=key,
        )
        async with pool.connection() as conn:
            cur = await conn.execute(
                "select status, last_error from send_intents where idempotency_key = %s",
                (key,),
            )
            return await cur.fetchone()

    row = run_with_pool(scenario)
    assert row["status"] == "failed"
    assert "exploded" in row["last_error"]


def test_marketing_send_rejects_raw_text() -> None:
    """graft 11: no raw content in send_intents — templates go by reference."""

    async def scenario(pool: Any) -> None:
        outbox = SendOutbox(pool, {"waha": _FakeTransport()})
        with pytest.raises(ValueError, match="template reference"):
            await outbox.send(
                transport="waha",
                recipient="+584145610594",
                text="¡Oferta!",
                message_class="marketing",
                idempotency_key=f"mkt:{uuid.uuid4()}",
            )

    run_with_pool(scenario)


def test_in_doubt_reply_is_resent_but_marketing_is_abandoned() -> None:
    reply_key = f"turn:{uuid.uuid4()}:0"
    mkt_key = f"mkt:{uuid.uuid4()}"

    async def scenario(pool: Any) -> tuple[Any, Any, list[Any]]:
        wire = _FakeTransport()
        outbox = SendOutbox(pool, {"waha": wire})
        # Two rows stranded in 'pending' by a crash between insert and dispatch.
        async with pool.connection() as conn:
            for key, cls, body in (
                (reply_key, "reply", "ya te conecto"),
                (mkt_key, "marketing", None),
            ):
                await conn.execute(
                    """
                    INSERT INTO send_intents
                        (idempotency_key, transport, recipient, message_class, body_text,
                         created_at)
                    VALUES (%s, 'waha', '+584145610594', %s, %s, NOW() - interval '10 minutes')
                    """,
                    (key, cls, body),
                )
        await outbox.recover_in_doubt(older_than_seconds=1, limit=50)
        async with pool.connection() as conn:
            cur = await conn.execute(
                "select idempotency_key, status from send_intents where idempotency_key = any(%s)",
                ([reply_key, mkt_key],),
            )
            rows = {r["idempotency_key"]: r["status"] for r in await cur.fetchall()}
        return rows[reply_key], rows[mkt_key], wire.sent

    reply_status, mkt_status, sent = run_with_pool(scenario)
    assert reply_status == "dispatched"
    assert mkt_status == "abandoned"
    assert sent == [("+584145610594", "ya te conecto")]
