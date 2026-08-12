"""
What an asesora is handed when she opens a ticket.

The team group gets a reference and nothing else — a WhatsApp group has no
retention policy and no erasure path, so the patient's words must not land in
it. That rule only works if the reference resolves to something: the whole point
of by-reference is that the content lives somewhere with a lock on the door.
This is that somewhere.

Assembled from agent-core's own tables, with the ticket itself fetched from
crm-adapter over HTTP. Neither service reads the other's tables, at the cost of
one hop on a path a human walks, not a patient.

**Every section degrades on its own.** A failing sub-read yields an empty section
and a line in `errors`, never a 500. Someone is holding a live conversation while
they read this; a partial package beats an error page.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from psycopg_pool import AsyncConnectionPool

from company_agent.common.phone import canonicalize

from ..identity import IdentityBroker
from ..routing.handoff_client import HandoffClient
from .episodes import EpisodeStore

logger = logging.getLogger(__name__)

DEFAULT_TURNS = 20
MAX_TURNS = 50
MAX_MEDIA = 20
MAX_TICKETS = 10

# Facts a patient has told us, as they stand now. `patient_facts` is append-only:
# a changed fact closes the old row and inserts a new one, so "current" is the
# open-ended one.
CURRENT_FACTS = """
SELECT fact_key, fact_value, confidence, valid_from
FROM patient_facts
WHERE identity_id = %(identity_id)s AND valid_to IS NULL
ORDER BY fact_key
"""

# Slots derived from what the conversation already shows, rather than from an
# extractor that does not exist yet.
DERIVED_SLOTS = """
SELECT min(created_at) AS first_seen,
       max(created_at) AS last_seen,
       count(*) FILTER (WHERE direction = 'inbound') AS patient_turns,
       count(*) FILTER (WHERE direction = 'outbound') AS agent_turns
FROM patient_episodes
WHERE identity_id = %(identity_id)s
"""

LAST_INTENT = """
SELECT intent
FROM patient_episodes
WHERE identity_id = %(identity_id)s AND intent IS NOT NULL
ORDER BY created_at DESC
LIMIT 1
"""

# Never storage_path: an asesora needs to find the receipt, not to learn where
# the volume keeps it.
MEDIA_REFS = """
SELECT id, kind, mime_type, byte_size, status, caption, created_at
FROM media_artifacts
WHERE identity_id = %(identity_id)s
ORDER BY created_at DESC
LIMIT %(limit)s
"""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class ContextPackageBuilder:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        episodes: EpisodeStore,
        identity: IdentityBroker,
        handoff: HandoffClient,
    ) -> None:
        self._pool = pool
        self._episodes = episodes
        self._identity = identity
        self._handoff = handoff

    async def build(self, handoff_id: str, *, turns: int = DEFAULT_TURNS) -> dict[str, Any] | None:
        """
        The package behind a ticket reference. None when no such ticket exists.

        Ordering matters: the ticket resolves the patient, and everything else
        hangs off the identity it carries. A ticket opened by the OpenClaw
        runtime has no identity, so the number is used to find one — read-only,
        because a lookup that mints identities would create a patient every time
        someone opened a stale reference.
        """
        turns = max(1, min(turns, MAX_TURNS))
        errors: list[str] = []

        # The one read that is not allowed to degrade. Everything else hangs off
        # the ticket, and "crm-adapter is down" must not be answered with the
        # same 404 as "no such ticket" — one is a retry, the other is a typo.
        ticket = await self._handoff.get_handoff(handoff_id)
        if ticket is None:
            return None

        phone = ticket.get("contact_phone") or ""
        identity = await self._resolve_identity(ticket, phone, errors)
        identity_id = identity.id if identity else None

        return {
            "ticket": self._ticket_view(ticket),
            "patient": self._patient_view(identity, phone),
            "slots": await self._slots(identity_id, errors),
            "history": await self._history(phone, identity_id, errors),
            "transcript": await self._transcript(identity_id, turns, errors),
            "media": await self._media(identity_id, errors),
            "errors": errors,
        }

    # ── Sections ─────────────────────────────────────────────────────────────

    async def _resolve_identity(self, ticket: dict, phone: str, errors: list[str]):
        raw = ticket.get("identity_id")
        if raw:
            try:
                return await self._identity.find_by_id(uuid.UUID(raw))
            except ValueError:
                errors.append(f"ticket carries a malformed identity_id: {raw!r}")
        if phone:
            return await self._identity.find_by_phone(canonicalize(phone))
        return None

    def _ticket_view(self, ticket: dict) -> dict[str, Any]:
        return {
            "handoff_id": ticket.get("handoff_id"),
            "reference": str(ticket.get("handoff_id") or "")[:8],
            "status": ticket.get("status"),
            "active": ticket.get("active"),
            "reason": ticket.get("reason"),
            "priority": ticket.get("priority"),
            "claimed_by": ticket.get("claimed_by_name"),
            "created_at": ticket.get("created_at"),
            "claimed_at": ticket.get("claimed_at"),
            "expires_at": ticket.get("expires_at"),
            "zoho_contact_id": ticket.get("contact_id"),
        }

    def _patient_view(self, identity, phone: str) -> dict[str, Any]:
        if identity is None:
            # A ticket whose patient is not in the registry still names a number.
            return {"phone_e164": phone, "identity_id": None, "known": False}
        return {
            "identity_id": str(identity.id),
            "display_name": identity.display_name,
            "phone_e164": identity.phone_e164 or phone,
            # The address, which is not always the number: see common/phone.py.
            "wa_id": identity.wa_id,
            "zoho_module": identity.zoho_module,
            "zoho_record_id": identity.zoho_record_id,
            # Surfaced, not hidden: two addresses resolved to one number and a
            # human has to decide whether it is one patient.
            "needs_review": identity.needs_review,
            "known": True,
        }

    async def _slots(self, identity_id: uuid.UUID | None, errors: list[str]) -> dict[str, Any]:
        """
        What we know about this patient, structured.

        Two sources, deliberately. `patient_facts` is where an extractor will
        write — it has no writer anywhere in the repo today, so this reads it
        forward-compatibly rather than shipping a field that is empty by
        construction. The derived slots are computed from the conversation that
        already happened, which is real signal an asesora can act on now:
        whether this is a first contact or a fourth, and what they last asked
        about.
        """
        slots: dict[str, Any] = {"learned": [], "derived": {}}
        if identity_id is None:
            return slots

        try:
            async with self._pool.connection() as conn:
                rows = await (await conn.execute(CURRENT_FACTS, {"identity_id": identity_id})).fetchall()
                slots["learned"] = [
                    {
                        "key": r["fact_key"],
                        "value": r["fact_value"],
                        "confidence": float(r["confidence"]) if r["confidence"] is not None else None,
                        "since": _iso(r["valid_from"]),
                    }
                    for r in rows
                ]

                derived = await (await conn.execute(DERIVED_SLOTS, {"identity_id": identity_id})).fetchone()
                intent = await (await conn.execute(LAST_INTENT, {"identity_id": identity_id})).fetchone()
        except Exception as exc:
            logger.exception("context package: slots failed identity=%s", identity_id)
            errors.append(f"slots unavailable: {exc}")
            return slots

        if derived:
            slots["derived"] = {
                "first_seen": _iso(derived["first_seen"]),
                "last_seen": _iso(derived["last_seen"]),
                "patient_turns": derived["patient_turns"],
                "agent_turns": derived["agent_turns"],
                "returning": (derived["patient_turns"] or 0) > 1,
                "last_intent": intent["intent"] if intent else None,
            }
        return slots

    async def _history(
        self, phone: str, identity_id: uuid.UUID | None, errors: list[str]
    ) -> list[dict[str, Any]]:
        """
        Every previous time a human was pulled in.

        Not the cadence history the brief eventually wants — there is no cadence
        engine yet — and labelled as tickets so nobody reads it as one.
        """
        if not phone:
            return []
        try:
            rows = await self._handoff.history(
                contact_phone=phone,
                identity_id=str(identity_id) if identity_id else None,
                limit=MAX_TICKETS,
            )
        except Exception as exc:
            logger.exception("context package: history failed phone=%s", phone)
            errors.append(f"ticket history unavailable: {exc}")
            return []
        return [
            {
                "handoff_id": r.get("handoff_id"),
                "status": r.get("status"),
                "reason": r.get("reason"),
                "claimed_by": r.get("claimed_by_name"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]

    async def _transcript(
        self, identity_id: uuid.UUID | None, turns: int, errors: list[str]
    ) -> list[dict[str, Any]]:
        """
        The conversation, oldest first — the order a transcript reads in.

        `EpisodeStore.recent` returns nothing for an unknown identity rather than
        falling back to the phone, and that restraint holds here: a transcript
        showing the wrong patient is worse than no transcript at all.
        """
        if identity_id is None:
            errors.append("no identity for this ticket, so no conversation history")
            return []
        episodes = await self._episodes.recent(identity_id, limit=turns)
        return [
            {"direction": e.direction, "text": e.text, "at": _iso(e.created_at)}
            for e in episodes
        ]

    async def _media(
        self, identity_id: uuid.UUID | None, errors: list[str]
    ) -> list[dict[str, Any]]:
        """
        References to what the patient sent — the payment proof, the lab result.

        The 8-character reference is the one printed in the team group, so an
        asesora can match the message she saw to the file she is looking for.
        """
        if identity_id is None:
            return []
        try:
            async with self._pool.connection() as conn:
                rows = await (
                    await conn.execute(MEDIA_REFS, {"identity_id": identity_id, "limit": MAX_MEDIA})
                ).fetchall()
        except Exception as exc:
            logger.exception("context package: media failed identity=%s", identity_id)
            errors.append(f"media references unavailable: {exc}")
            return []
        return [
            {
                "reference": str(r["id"])[:8],
                "kind": r["kind"],
                "mime_type": r["mime_type"],
                "byte_size": r["byte_size"],
                "status": r["status"],
                "caption": r["caption"],
                "at": _iso(r["created_at"]),
            }
            for r in rows
        ]

