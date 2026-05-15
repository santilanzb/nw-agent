from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..models import WahaInboundMessage

logger = logging.getLogger(__name__)

_JID_DIGITS = re.compile(r"^(\d+)@")


def _e164(jid: str) -> str:
    """Convert a WAHA JID like '584145610594@c.us' to '+584145610594'."""
    m = _JID_DIGITS.match(jid)
    return f"+{m.group(1)}" if m else jid


def normalize_waha_event(raw: dict[str, Any]) -> WahaInboundMessage | None:
    """
    Parse a raw WAHA webhook body into a WahaInboundMessage.
    Returns None for events we should skip (non-message, status updates).
    """
    event_type = raw.get("event", "")
    if event_type != "message":
        return None

    payload = raw.get("payload", {})
    from_jid: str = payload.get("from", "")
    from_me: bool = payload.get("fromMe", False)
    body: str = payload.get("body") or ""
    is_group: bool = payload.get("isGroup", False)
    timestamp: int = payload.get("timestamp", 0)
    msg_type: str = payload.get("type", "chat")
    event_id: str = payload.get("id", "")
    sender_name: str | None = payload.get("_data", {}).get("notifyName") or payload.get("senderName") or None

    # Skip non-text message types (image, audio, document, etc.)
    if msg_type not in ("chat", "text", ""):
        return None

    # Skip empty bodies
    if not body.strip():
        return None

    # Status updates: WAHA sends isStatus=True on status messages
    is_status: bool = payload.get("isStatus", False)

    # For group messages WAHA puts the actual sender in 'participant'
    participant_jid: str | None = payload.get("participant") or None
    participant_phone: str | None = _e164(participant_jid) if participant_jid else None

    if is_group:
        group_jid = from_jid
        phone = group_jid  # We'll use group JID as the routing key for groups
    else:
        group_jid = None
        phone = _e164(from_jid) if from_jid else from_jid

    return WahaInboundMessage(
        event_id=event_id,
        from_jid=from_jid,
        phone=phone,
        group_jid=group_jid if is_group else None,
        participant_jid=participant_jid,
        participant_phone=participant_phone,
        text=body,
        is_group=is_group,
        from_me=from_me,
        is_status=is_status,
        timestamp=timestamp,
        sender_name=sender_name,
    )


class WahaClient:
    """Thin async client for the WAHA REST API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self._api_key, "Content-Type": "application/json"}

    async def send_text(self, chat_id: str, text: str) -> None:
        """Send a text message to a DM or group JID."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._base_url}/api/sendText",
                json={"chatId": chat_id, "text": text, "session": "default"},
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                logger.error(
                    "waha send_text failed status=%s body=%s", resp.status_code, resp.text[:200]
                )
                resp.raise_for_status()

    async def send_to_group(self, group_jid: str, text: str) -> None:
        """Send a message to the team group."""
        await self.send_text(group_jid, text)

    def dm_jid(self, phone: str) -> str:
        """Convert E.164 phone to WAHA DM JID."""
        digits = phone.lstrip("+")
        return f"{digits}@c.us"
