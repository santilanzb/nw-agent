"""
Postgres-backed handoff state for the Gutty agent.

Lifecycle (per contact_phone):
    pending  → handoff_human just fired; logistics team has been notified
    claimed  → a logistics member took the case; agent stays silent
    resumed  → human is done; agent answers that patient again
    expired  → the window ran out without a resume; agent answers again

Two windows, not one. A case nobody picks up is the team missing a patient and
should surface fast; a case that was picked up is an asesora working, and should
get the long clock — measured from the claim, not from the creation, or a case
taken at hour 23 of a 24h TTL expires an hour later, mid-conversation. Both land
on the same `expires_at` column, so the sweep stays one indexed comparison.

Lookups are by normalized E.164 phone (with leading +). Reads are very hot
(every inbound patient message calls check_active) so we keep the table small
and indexed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from psycopg.types.json import Jsonb  # noqa: F401  (kept for future metadata col)

from company_agent.common.db import connect

HandoffStatus = Literal["pending", "claimed", "resumed", "expired"]
HandoffPriority = Literal["low", "normal", "high", "urgent"]


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class HandoffStateRecord:
    id: str
    contact_phone: str
    identity_id: str | None
    contact_id: str | None
    patient_name: str | None
    conversation_id: str | None
    status: HandoffStatus
    reason: str | None
    priority: HandoffPriority
    last_message: str | None
    zoho_note_id: str | None
    claimed_by_phone: str | None
    claimed_by_name: str | None
    created_at: datetime
    claimed_at: datetime | None
    resumed_at: datetime | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExpiredHandoff:
    """
    A case the sweep closed, and enough to say so out loud.

    `previous_status` is the difference between "nobody picked this up" and "the
    asesora who did never closed it" — two different messages to the team, and
    the UPDATE that expires the row destroys the distinction unless it is read
    first.
    """

    id: str
    contact_phone: str
    identity_id: str | None
    previous_status: HandoffStatus
    reason: str | None
    priority: HandoffPriority
    patient_name: str | None
    claimed_by_name: str | None
    created_at: datetime
    claimed_at: datetime | None
    expires_at: datetime


def _row_to_record(row: dict) -> HandoffStateRecord:
    return HandoffStateRecord(
        id=str(row["id"]),
        contact_phone=row["contact_phone"],
        identity_id=str(row["identity_id"]) if row.get("identity_id") else None,
        contact_id=row["contact_id"],
        patient_name=row["patient_name"],
        conversation_id=row["conversation_id"],
        status=row["status"],
        reason=row["reason"],
        priority=row["priority"],
        last_message=row["last_message"],
        zoho_note_id=row["zoho_note_id"],
        claimed_by_phone=row["claimed_by_phone"],
        claimed_by_name=row["claimed_by_name"],
        created_at=row["created_at"],
        claimed_at=row["claimed_at"],
        resumed_at=row["resumed_at"],
        expires_at=row["expires_at"],
    )


# ── Store ─────────────────────────────────────────────────────────────────────

class HandoffStateStore:
    """Thin Postgres CRUD for handoff_state. Stateless, safe to share."""

    def __init__(
        self,
        database_url: str,
        pending_expire_hours: int = 4,
        claimed_expire_hours: int = 24,
    ) -> None:
        self._database_url = database_url
        self._pending_expire_hours = pending_expire_hours
        self._claimed_expire_hours = claimed_expire_hours

    # ── reads ────────────────────────────────────────────────────────────────

    def check_active(self, contact_phone: str) -> HandoffStateRecord | None:
        """
        Return the active (pending or claimed) handoff for this phone, if any.

        A row past its window is not active, and the read says so immediately
        rather than waiting for the sweep — the patient stops being muted the
        moment the clock runs out.

        It no longer *flips* the row on the way past, and that matters: whoever
        flips it owns telling the team the case was dropped. Expiring here would
        have quietly consumed the row the sweeper exists to announce, so the
        transition would only ever be visible to the one patient who happened to
        write again. It also took an unconditional table-wide UPDATE off the path
        of every inbound message.
        """
        with connect(self._database_url) as conn:
            row = conn.execute(
                """
                SELECT * FROM handoff_state
                WHERE contact_phone = %(phone)s
                  AND status IN ('pending', 'claimed')
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {"phone": contact_phone},
            ).fetchone()
        return _row_to_record(row) if row else None

    def get_by_id(self, handoff_id: str) -> HandoffStateRecord | None:
        with connect(self._database_url) as conn:
            row = conn.execute(
                "SELECT * FROM handoff_state WHERE id = %(id)s::uuid",
                {"id": handoff_id},
            ).fetchone()
        return _row_to_record(row) if row else None

    # ── writes ───────────────────────────────────────────────────────────────

    def create(
        self,
        contact_phone: str,
        reason: str,
        priority: HandoffPriority = "high",
        contact_id: str | None = None,
        patient_name: str | None = None,
        conversation_id: str | None = None,
        last_message: str | None = None,
        zoho_note_id: str | None = None,
        identity_id: str | None = None,
    ) -> HandoffStateRecord:
        """
        Create a new pending handoff. If one already exists for this phone,
        mark it resumed first so we never have two active rows.
        """
        expires_at = datetime.now(UTC) + timedelta(hours=self._pending_expire_hours)

        with connect(self._database_url) as conn:
            # Close any prior active handoff for this phone
            conn.execute(
                """
                UPDATE handoff_state
                SET status = 'resumed', resumed_at = NOW()
                WHERE contact_phone = %(phone)s
                  AND status IN ('pending', 'claimed')
                """,
                {"phone": contact_phone},
            )
            row = conn.execute(
                """
                INSERT INTO handoff_state (
                    contact_phone, contact_id, patient_name, conversation_id,
                    status, reason, priority, last_message, zoho_note_id,
                    expires_at, identity_id
                )
                VALUES (
                    %(phone)s, %(contact_id)s, %(name)s, %(conv)s,
                    'pending', %(reason)s, %(priority)s, %(last_msg)s, %(note)s,
                    %(expires)s, %(identity_id)s
                )
                RETURNING *
                """,
                {
                    "phone": contact_phone,
                    "contact_id": contact_id,
                    "name": patient_name,
                    "conv": conversation_id,
                    "reason": reason,
                    "priority": priority,
                    "last_msg": last_message,
                    "note": zoho_note_id,
                    "expires": expires_at,
                    "identity_id": identity_id,
                },
            ).fetchone()
        return _row_to_record(row)

    def claim(
        self,
        contact_phone: str,
        claimer_phone: str,
        claimer_name: str,
    ) -> HandoffStateRecord | None:
        """
        First-to-claim. Atomically moves pending → claimed for this phone IF
        no one has claimed yet. Returns the row if this caller won the race,
        None if it was already claimed by someone else.
        """
        with connect(self._database_url) as conn:
            row = conn.execute(
                """
                UPDATE handoff_state
                SET status = 'claimed',
                    claimed_at = NOW(),
                    claimed_by_phone = %(by_phone)s,
                    claimed_by_name = %(by_name)s,
                    -- The clock restarts on the claim. Whoever took the case
                    -- gets the full window to work it, however long it sat
                    -- unclaimed first.
                    expires_at = NOW() + make_interval(hours => %(claimed_hours)s)
                WHERE contact_phone = %(phone)s
                  AND status = 'pending'
                  AND id = (
                      SELECT id FROM handoff_state
                      WHERE contact_phone = %(phone)s
                        AND status = 'pending'
                      ORDER BY created_at DESC
                      LIMIT 1
                  )
                RETURNING *
                """,
                {
                    "phone": contact_phone,
                    "by_phone": claimer_phone,
                    "by_name": claimer_name,
                    "claimed_hours": self._claimed_expire_hours,
                },
            ).fetchone()
        return _row_to_record(row) if row else None

    def already_claimed(self, contact_phone: str) -> HandoffStateRecord | None:
        """
        If a live handoff for this phone is already claimed, return it; else None.

        Past the window it is not "ya lo tomó Ana" — it is a case that ran out.
        Telling an asesora someone else holds a dead ticket sends her to ask a
        colleague who long since moved on.
        """
        with connect(self._database_url) as conn:
            row = conn.execute(
                """
                SELECT * FROM handoff_state
                WHERE contact_phone = %(phone)s
                  AND status = 'claimed'
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {"phone": contact_phone},
            ).fetchone()
        return _row_to_record(row) if row else None

    def resume(self, contact_phone: str) -> HandoffStateRecord | None:
        """Close the active handoff for this phone (any state pending|claimed)."""
        with connect(self._database_url) as conn:
            row = conn.execute(
                """
                UPDATE handoff_state
                SET status = 'resumed', resumed_at = NOW()
                WHERE contact_phone = %(phone)s
                  AND status IN ('pending', 'claimed')
                  AND id = (
                      SELECT id FROM handoff_state
                      WHERE contact_phone = %(phone)s
                        AND status IN ('pending', 'claimed')
                      ORDER BY created_at DESC
                      LIMIT 1
                  )
                RETURNING *
                """,
                {"phone": contact_phone},
            ).fetchone()
        return _row_to_record(row) if row else None

    # ── housekeeping ─────────────────────────────────────────────────────────

    def sweep_expired(self) -> list[ExpiredHandoff]:
        """
        Close every case whose window ran out, and say which ones.

        Returning the rows is the whole point. Expiry has always happened; what
        never happened was anyone finding out. A case that expires unclaimed is a
        patient the team never reached, and it was indistinguishable from a case
        an asesora closed properly.

        `FOR UPDATE SKIP LOCKED` means two sweepers cannot both report the same
        case, so the team is told once. The CTE captures `status` before the
        UPDATE overwrites it — an announcement has to say whether anyone had
        picked the case up.
        """
        with connect(self._database_url) as conn:
            rows = conn.execute(
                """
                WITH due AS (
                    SELECT id, status AS previous_status
                    FROM handoff_state
                    WHERE status IN ('pending', 'claimed')
                      AND expires_at < NOW()
                    FOR UPDATE SKIP LOCKED
                ), swept AS (
                    UPDATE handoff_state h
                    SET status = 'expired'
                    FROM due
                    WHERE h.id = due.id
                    RETURNING h.id, h.contact_phone, h.identity_id, h.reason,
                              h.priority, h.patient_name, h.claimed_by_name,
                              h.created_at, h.claimed_at, h.expires_at
                )
                SELECT swept.*, due.previous_status
                FROM swept JOIN due ON due.id = swept.id
                ORDER BY swept.created_at
                """,
            ).fetchall()

        return [
            ExpiredHandoff(
                id=str(row["id"]),
                contact_phone=row["contact_phone"],
                identity_id=str(row["identity_id"]) if row["identity_id"] else None,
                previous_status=row["previous_status"],
                reason=row["reason"],
                priority=row["priority"],
                patient_name=row["patient_name"],
                claimed_by_name=row["claimed_by_name"],
                created_at=row["created_at"],
                claimed_at=row["claimed_at"],
                expires_at=row["expires_at"],
            )
            for row in rows
        ]
