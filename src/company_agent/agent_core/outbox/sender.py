"""
Send outbox.

Before this, a reply was three in-process retries and then a log line: the patient
got silence and nothing recorded that a reply was owed. Now a send_intents row is
written *before* the transport call, so a send is always either visibly pending or
visibly finished.

The in-doubt window — crashed after the transport accepted but before we recorded
it — cannot be eliminated against an external API, only policed. That policy is
per message class and is the reason `message_class` exists:

  reply, utility : re-sendable. A duplicate "ya te conecto con una asesora" is
                   mildly awkward; silence is worse.
  marketing      : never blind re-sent. Meta bills it, the patient sees it twice,
                   and it counts against the per-user cap. It waits for status
                   correlation and then becomes a human task.
  team           : re-sendable; the group is internal.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..transport.base import MessageClass, Transport

logger = logging.getLogger(__name__)

RESENDABLE: frozenset[str] = frozenset({"reply", "utility", "team"})


@dataclass(slots=True)
class SendResult:
    sent: bool
    intent_id: uuid.UUID | None
    provider_message_id: str | None = None
    skipped_reason: str | None = None


class SendOutbox:
    def __init__(self, pool: AsyncConnectionPool, transports: dict[str, Transport]) -> None:
        self._pool = pool
        self._transports = transports

    async def send(
        self,
        *,
        transport: str,
        recipient: str,
        text: str,
        message_class: MessageClass,
        idempotency_key: str,
        turn_id: uuid.UUID | None = None,
        identity_id: uuid.UUID | None = None,
    ) -> SendResult:
        if message_class == "marketing" and text:
            raise ValueError(
                "marketing sends carry a template reference, never raw text — "
                "raw content in send_intents defeats the retention and erasure design"
            )

        claimed = await self._claim(
            transport=transport,
            recipient=recipient,
            text=text,
            message_class=message_class,
            idempotency_key=idempotency_key,
            turn_id=turn_id,
            identity_id=identity_id,
        )
        if claimed is None:
            logger.info("send_intent already exists key=%s — not re-sending", idempotency_key)
            return SendResult(sent=False, intent_id=None, skipped_reason="duplicate")

        return await self._dispatch(claimed, transport, recipient, text)

    async def _claim(
        self,
        *,
        transport: str,
        recipient: str,
        text: str,
        message_class: MessageClass,
        idempotency_key: str,
        turn_id: uuid.UUID | None,
        identity_id: uuid.UUID | None,
    ) -> uuid.UUID | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO send_intents (
                    idempotency_key, transport, recipient, message_class,
                    body_ref, body_text, turn_id, identity_id
                ) VALUES (
                    %(key)s, %(transport)s, %(recipient)s, %(message_class)s,
                    %(body_ref)s, %(body_text)s, %(turn_id)s, %(identity_id)s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                {
                    "key": idempotency_key,
                    "transport": transport,
                    "recipient": recipient,
                    "message_class": message_class,
                    "body_ref": Jsonb({}),
                    "body_text": text or None,
                    "turn_id": turn_id,
                    # Who this message is about, so an erasure can find it. A
                    # team-group ping names the patient's number even though it
                    # is addressed to the team, which makes it their data too.
                    "identity_id": identity_id,
                },
            )
            row = await cur.fetchone()
        return row["id"] if row else None

    async def _dispatch(
        self, intent_id: uuid.UUID, transport: str, recipient: str, text: str
    ) -> SendResult:
        wire = self._transports.get(transport)
        if wire is None:
            await self._fail(intent_id, f"unknown transport {transport!r}")
            return SendResult(sent=False, intent_id=intent_id, skipped_reason="unknown_transport")

        try:
            provider_id = await wire.send_text(recipient, text)
        except Exception as exc:  # noqa: BLE001 - any transport failure is recorded, not raised
            logger.error("send failed intent=%s transport=%s: %s", intent_id, transport, exc)
            await self._fail(intent_id, str(exc))
            return SendResult(sent=False, intent_id=intent_id, skipped_reason="transport_error")

        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE send_intents
                   SET status = 'dispatched', dispatched_at = NOW(),
                       provider_message_id = %(pid)s, attempts = attempts + 1
                 WHERE id = %(id)s
                """,
                {"id": intent_id, "pid": provider_id},
            )
        return SendResult(sent=True, intent_id=intent_id, provider_message_id=provider_id)

    async def _fail(self, intent_id: uuid.UUID, error: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE send_intents
                   SET status = 'failed', last_error = %(err)s, attempts = attempts + 1
                 WHERE id = %(id)s
                """,
                {"id": intent_id, "err": error[:500]},
            )

    async def recover_in_doubt(self, *, older_than_seconds: int = 120, limit: int = 20) -> int:
        """
        Resolve sends left mid-flight by a crash. Returns how many were acted on.

        Re-sendable classes get exactly one more attempt. Marketing is abandoned
        rather than repeated — a duplicate template is billed, visible to the
        patient, and counts against Meta's per-user cap.
        """
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT id, transport, recipient, body_text, message_class, attempts
                  FROM send_intents
                 WHERE status = 'pending'
                   AND created_at < NOW() - make_interval(secs => %(age)s)
                 ORDER BY created_at
                   FOR UPDATE SKIP LOCKED
                 LIMIT %(limit)s
                """,
                {"age": older_than_seconds, "limit": limit},
            )
            rows = await cur.fetchall()

        acted = 0
        for row in rows:
            if row["message_class"] not in RESENDABLE:
                await self._abandon(
                    row["id"],
                    "marketing template in doubt after crash — never blind re-sent; "
                    "needs status correlation or a human",
                )
                acted += 1
                continue
            if row["attempts"] >= 2:
                await self._abandon(row["id"], "retries exhausted")
                acted += 1
                continue
            await self._dispatch(row["id"], row["transport"], row["recipient"], row["body_text"] or "")
            acted += 1
        return acted

    async def _abandon(self, intent_id: uuid.UUID, reason: str) -> None:
        logger.warning("send_intent abandoned id=%s reason=%s", intent_id, reason)
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE send_intents
                   SET status = 'abandoned', last_error = %(reason)s
                 WHERE id = %(id)s
                """,
                {"id": intent_id, "reason": reason[:500]},
            )
