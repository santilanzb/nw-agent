"""
Conversational memory: what was said in this conversation before now.

`patient_episodes` has had a schema since the Stage 0 baseline and **zero
readers or writers** — the whole episodic layer was a table nobody used. Without
it every turn is the patient's first: "¿y cuánto cuesta ese?" has no antecedent,
and Gutty answers a question nobody asked.

Keyed on `identity_id`, not on the phone string. The phone is kept alongside for
operator queries, but the join that survives a patient reaching us in two
formats is the identity.

Writes are best-effort in the same sense as `turn_log`: memory failing must not
cost the patient their answer.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

MAX_EPISODE_CHARS = 4000

INSERT_EPISODE = """
INSERT INTO patient_episodes (
    identity_id, contact_phone, direction, text, intent, confidence,
    decision, task, composed_by_llm, model_used, turn_id
) VALUES (
    %(identity_id)s, %(contact_phone)s, %(direction)s, %(text)s, %(intent)s, %(confidence)s,
    %(decision)s, %(task)s, %(composed_by_llm)s, %(model_used)s, %(turn_id)s
)
"""

# Newest-first, then reversed by the caller: the index is (identity_id,
# created_at DESC), so this reads it directly instead of sorting the history.
#
# `direction DESC` is the tiebreaker and it is load-bearing. Both halves of a
# turn are written in one transaction, and Postgres' NOW() is transaction-start
# time — so they share a created_at to the microsecond and their relative order
# is otherwise undefined. Without this the transcript can show Gutty answering
# before the patient asks, which is precisely the confusion history exists to
# prevent. 'outbound' > 'inbound' alphabetically, so DESC here becomes
# inbound-then-outbound once the caller reverses.
RECENT_EPISODES = """
SELECT direction, text, created_at
FROM patient_episodes
WHERE identity_id = %(identity_id)s
ORDER BY created_at DESC, direction DESC
LIMIT %(limit)s
"""


@dataclass(frozen=True, slots=True)
class Episode:
    direction: str
    text: str
    # Only the context package needs it — a composition prompt reads the turns in
    # order and has no use for a timestamp — so it stays optional rather than
    # forcing every caller to carry one.
    created_at: datetime | None = None


class EpisodeStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def recent(self, identity_id: uuid.UUID | None, limit: int = 6) -> list[Episode]:
        """
        The last N turns, oldest first — the order a transcript reads in.

        Returns nothing when the identity is unknown rather than falling back to
        the phone: a wrong history is worse than none, because the model would
        answer with confidence about the wrong patient.
        """
        if identity_id is None:
            return []
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    RECENT_EPISODES, {"identity_id": identity_id, "limit": limit}
                )
                rows = await cur.fetchall()
        except Exception:
            logger.exception("episode read failed identity=%s", identity_id)
            return []
        return [
            Episode(direction=r["direction"], text=r["text"], created_at=r["created_at"])
            for r in reversed(rows)
        ]

    async def record(
        self,
        *,
        identity_id: uuid.UUID | None,
        contact_phone: str,
        turn_id: uuid.UUID,
        inbound_text: str,
        reply_text: str | None,
        intent: str | None = None,
        confidence: float | None = None,
        decision: str | None = None,
        task: str | None = None,
        composed_by_llm: bool = False,
        model_used: str | None = None,
    ) -> None:
        """Record both halves of a turn. Silent turns write only the inbound half."""
        rows = [
            {
                "identity_id": identity_id,
                "contact_phone": contact_phone,
                "direction": "inbound",
                "text": inbound_text[:MAX_EPISODE_CHARS],
                "intent": intent,
                "confidence": confidence,
                "decision": decision,
                "task": task,
                "composed_by_llm": False,
                "model_used": None,
                "turn_id": turn_id,
            }
        ]
        if reply_text:
            rows.append(
                {
                    "identity_id": identity_id,
                    "contact_phone": contact_phone,
                    "direction": "outbound",
                    "text": reply_text[:MAX_EPISODE_CHARS],
                    "intent": intent,
                    "confidence": confidence,
                    "decision": decision,
                    "task": task,
                    "composed_by_llm": composed_by_llm,
                    "model_used": model_used,
                    "turn_id": turn_id,
                }
            )

        try:
            async with self._pool.connection() as conn:
                for row in rows:
                    await conn.execute(INSERT_EPISODE, row)
        except Exception:
            logger.exception("episode write failed turn=%s", turn_id)
