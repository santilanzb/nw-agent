"""
Durable ingress inbox.

Replaces the in-memory `_SEEN` OrderedDict. That cache was per-process and lost
on every restart, so a WAHA redelivery after a deploy re-answered the patient;
and because the webhook returned 200 before processing, a crash between the ACK
and the reply lost the message with no record it had ever arrived.

The contract now: verify -> insert -> ACK. Nothing is acknowledged that is not
durable, and (source, source_event_id) makes redelivery a no-op.

The stored payload contains the patient's message and is therefore PHI-bearing.
It is a first-class store in the retention and Art. 17 erasure design.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..transport.base import InboundEvent

logger = logging.getLogger(__name__)

# An event still 'pending' this long after arrival was almost certainly dropped by
# a process that died mid-turn; the sweeper re-drives it.
DEFAULT_PENDING_GRACE_SECONDS = 60
# A row left 'processing' this long belongs to a worker that is gone.
DEFAULT_STALE_LOCK_SECONDS = 300
# Past this, stop retrying and leave the row for a human. Re-driving forever
# would mean a poison payload re-sending the same reply on every tick.
DEFAULT_MAX_ATTEMPTS = 5


@dataclass(slots=True)
class InboxRow:
    id: uuid.UUID
    source: str
    source_event_id: str
    payload: dict[str, Any]
    attempts: int


class InboxWriter:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._pool = pool
        self._max_attempts = max_attempts

    async def record(self, event: InboundEvent) -> uuid.UUID | None:
        """
        Persist an inbound event. Returns its row id, or None when this exact
        delivery has been seen before — the caller should ACK and do nothing.
        """
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO intake_events (source, source_event_id, payload)
                VALUES (%(source)s, %(source_event_id)s, %(payload)s)
                ON CONFLICT (source, source_event_id) DO NOTHING
                RETURNING id
                """,
                {
                    "source": event.source,
                    "source_event_id": event.source_event_id,
                    "payload": Jsonb(event.raw),
                },
            )
            row = await cur.fetchone()

        if row is None:
            logger.info(
                "duplicate_delivery source=%s event_id=%s — already durable, skipping",
                event.source,
                event.source_event_id,
            )
            return None
        return row["id"]

    async def mark_processing(self, event_id: uuid.UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE intake_events
                   SET status = 'processing', locked_at = NOW(), attempts = attempts + 1
                 WHERE id = %(id)s
                """,
                {"id": event_id},
            )

    async def mark_processed(self, event_id: uuid.UUID, turn_id: uuid.UUID | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE intake_events
                   SET status = 'processed', processed_at = NOW(), turn_id = %(turn_id)s,
                       locked_at = NULL, last_error = NULL
                 WHERE id = %(id)s
                """,
                {"id": event_id, "turn_id": turn_id},
            )

    async def mark_skipped(self, event_id: uuid.UUID, reason: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE intake_events
                   SET status = 'skipped', processed_at = NOW(), last_error = %(reason)s,
                       locked_at = NULL
                 WHERE id = %(id)s
                """,
                {"id": event_id, "reason": reason[:500]},
            )

    async def mark_failed(self, event_id: uuid.UUID, error: str) -> None:
        """
        Release the row for another attempt, or retire it once attempts are spent.
        Retiring is deliberate: a payload that fails deterministically would
        otherwise be re-driven forever.
        """
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE intake_events
                   SET status = CASE WHEN attempts >= %(max_attempts)s THEN 'failed'
                                     ELSE 'pending' END,
                       last_error = %(error)s,
                       locked_at = NULL
                 WHERE id = %(id)s
                """,
                {"id": event_id, "error": error[:500], "max_attempts": self._max_attempts},
            )

    async def claim_stale(
        self,
        *,
        limit: int = 20,
        pending_grace_seconds: int = DEFAULT_PENDING_GRACE_SECONDS,
        stale_lock_seconds: int = DEFAULT_STALE_LOCK_SECONDS,
    ) -> list[InboxRow]:
        """
        Atomically claim events that nobody finished, for the sweeper.

        FOR UPDATE SKIP LOCKED means two workers never claim the same row, so this
        stays correct if agent-core is ever run with more than one replica.
        """
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE intake_events
                   SET status = 'processing', locked_at = NOW(), attempts = attempts + 1
                 WHERE id IN (
                        SELECT id
                          FROM intake_events
                         WHERE attempts < %(max_attempts)s
                           AND (
                                (status = 'pending'
                                 AND received_at < NOW() - make_interval(secs => %(grace)s))
                             OR (status = 'processing'
                                 AND locked_at < NOW() - make_interval(secs => %(stale)s))
                               )
                         ORDER BY received_at
                           FOR UPDATE SKIP LOCKED
                         LIMIT %(limit)s
                       )
             RETURNING id, source, source_event_id, payload, attempts
                """,
                {
                    "max_attempts": self._max_attempts,
                    "grace": pending_grace_seconds,
                    "stale": stale_lock_seconds,
                    "limit": limit,
                },
            )
            rows = await cur.fetchall()

        return [
            InboxRow(
                id=r["id"],
                source=r["source"],
                source_event_id=r["source_event_id"],
                payload=r["payload"],
                attempts=r["attempts"],
            )
            for r in rows
        ]
