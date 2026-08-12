"""
Resolving a conversation to a durable identity.

`identity_registry` gives every patient one id that outlives their phone
formatting, their CRM record and their WhatsApp session. Two things need it:

  - **Erasure.** Art. 17 requires enumerating everything held about one person.
    Today `turn_log` is joined to a human only by `sha256(phone)`, and the hash
    changes if the phone string changes — so a patient whose number reached us in
    two formats has two unrelated histories.
  - **Ambiguity.** `ZohoClient.find_by_phone` matches on a 9-digit suffix and
    ends with `return rows[0]` when several records match. That silently picks a
    patient. Ambiguity now becomes a row a human resolves, not a coin flip.

The table has four separate single-column unique keys (`phone_e164`, `wa_id`,
`email_lower`, `igsid`), so one `ON CONFLICT` cannot cover a lookup across two of
them. Resolution is therefore a short sequence rather than a single statement,
with the insert made race-safe by `ON CONFLICT (wa_id)`.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from psycopg import errors
from psycopg_pool import AsyncConnectionPool

from company_agent.common.phone import CanonicalPhone

logger = logging.getLogger(__name__)

SELECT_BY_WA_ID = """
SELECT id, phone_e164, wa_id, display_name, merge_state, zoho_module, zoho_record_id
FROM identity_registry WHERE wa_id = %(wa_id)s
"""

SELECT_BY_E164 = """
SELECT id, phone_e164, wa_id, display_name, merge_state, zoho_module, zoho_record_id
FROM identity_registry WHERE phone_e164 = %(e164)s
"""

INSERT_IDENTITY = """
INSERT INTO identity_registry (phone_e164, wa_id, display_name, merge_state)
VALUES (%(e164)s, %(wa_id)s, %(display_name)s, %(merge_state)s)
ON CONFLICT (wa_id) DO UPDATE SET
    updated_at = NOW(),
    display_name = COALESCE(EXCLUDED.display_name, identity_registry.display_name)
RETURNING id, phone_e164, wa_id, display_name, merge_state, zoho_module, zoho_record_id
"""

ADOPT_WA_ID = """
UPDATE identity_registry
SET wa_id = %(wa_id)s, updated_at = NOW(),
    display_name = COALESCE(%(display_name)s, display_name)
WHERE id = %(id)s AND wa_id IS NULL
RETURNING id, phone_e164, wa_id, display_name, merge_state, zoho_module, zoho_record_id
"""

FLAG_FOR_REVIEW = """
UPDATE identity_registry SET merge_state = 'review', updated_at = NOW()
WHERE id = %(id)s AND merge_state = 'active'
"""


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    id: uuid.UUID
    phone_e164: str | None
    wa_id: str | None
    display_name: str | None
    merge_state: str
    zoho_module: str | None = None
    zoho_record_id: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.merge_state == "review"


def _record(row: dict) -> IdentityRecord:
    return IdentityRecord(
        id=row["id"],
        phone_e164=row["phone_e164"],
        wa_id=row["wa_id"],
        display_name=row["display_name"],
        merge_state=row["merge_state"],
        zoho_module=row.get("zoho_module"),
        zoho_record_id=row.get("zoho_record_id"),
    )


class IdentityBroker:
    """Resolves a canonical phone to a durable identity, creating one if needed."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def resolve(
        self, phone: CanonicalPhone, *, display_name: str | None = None
    ) -> IdentityRecord | None:
        """
        The identity for this conversation. `None` only if the lookup itself
        failed — the caller degrades rather than dropping the turn.

        An unparseable number still gets an identity, flagged for review: a
        conversation we cannot name is still a conversation we must not lose.
        """
        if not phone.wa_id:
            return None
        try:
            return await self._resolve(phone, display_name)
        except Exception:
            logger.exception("identity resolution failed wa_id=%s", phone.wa_id)
            return None

    async def _resolve(
        self, phone: CanonicalPhone, display_name: str | None
    ) -> IdentityRecord:
        async with self._pool.connection() as conn:
            # 1. The overwhelmingly common path: we have seen this wa_id before.
            cur = await conn.execute(SELECT_BY_WA_ID, {"wa_id": phone.wa_id})
            row = await cur.fetchone()
            if row:
                return _record(row)

            # 2. Same person, different address form — e.g. a Mexican number that
            #    reached us once as +52... and once as 521...
            cur = await conn.execute(SELECT_BY_E164, {"e164": phone.e164})
            row = await cur.fetchone()
            if row:
                if row["wa_id"] is None:
                    cur = await conn.execute(
                        ADOPT_WA_ID,
                        {"id": row["id"], "wa_id": phone.wa_id, "display_name": display_name},
                    )
                    adopted = await cur.fetchone()
                    if adopted:
                        return _record(adopted)
                    row = await (await conn.execute(SELECT_BY_E164, {"e164": phone.e164})).fetchone()
                    return _record(row)

                if row["wa_id"] != phone.wa_id:
                    # Two WhatsApp addresses canonicalize to one number. That is
                    # either one person on two handsets or a canonicalization
                    # bug, and guessing is what identity_registry replaced.
                    await conn.execute(FLAG_FOR_REVIEW, {"id": row["id"]})
                    logger.warning(
                        "identity ambiguity: e164=%s already held by wa_id=%s, saw wa_id=%s "
                        "— flagged for review",
                        phone.e164,
                        row["wa_id"],
                        phone.wa_id,
                    )
                    return await self._insert(
                        conn, phone, display_name, merge_state="review"
                    )
                return _record(row)

            # 3. New.
            return await self._insert(
                conn, phone, display_name, merge_state="active" if phone.valid else "review"
            )

    async def _insert(
        self, conn, phone: CanonicalPhone, display_name: str | None, *, merge_state: str
    ) -> IdentityRecord:
        params = {
            "e164": phone.e164 or None,
            "wa_id": phone.wa_id,
            "display_name": display_name,
            "merge_state": merge_state,
        }
        try:
            # Savepoint, not a bare execute. A UniqueViolation aborts the whole
            # transaction in Postgres, so without this the recovery INSERT below
            # dies with InFailedSqlTransaction and the conversation is lost —
            # which is precisely the case this branch exists to handle.
            async with conn.transaction():
                cur = await conn.execute(INSERT_IDENTITY, params)
                row = await cur.fetchone()
            if row:
                return _record(row)
        except errors.UniqueViolation:
            # phone_e164 is taken by a different wa_id and the ON CONFLICT clause
            # only covers wa_id. Store the address without the canonical number
            # rather than losing the conversation; the review row carries the
            # ambiguity.
            logger.warning(
                "phone_e164=%s already claimed by another identity — storing wa_id=%s for review",
                phone.e164,
                phone.wa_id,
            )
            cur = await conn.execute(
                INSERT_IDENTITY, {**params, "e164": None, "merge_state": "review"}
            )
            row = await cur.fetchone()
            if row:
                return _record(row)

        row = await (await conn.execute(SELECT_BY_WA_ID, {"wa_id": phone.wa_id})).fetchone()
        return _record(row)
