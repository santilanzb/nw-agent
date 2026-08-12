from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx

from .base import InboundEvent, InboundMedia, MediaKind
from .hmac_verify import verify_waha_hmac

logger = logging.getLogger(__name__)

_JID_DIGITS = re.compile(r"^(\d+)@")

# WAHA message types -> our transport-neutral media kinds. Anything not listed
# is carried as 'unknown' rather than dropped: an unrecognised type is still a
# patient trying to tell us something.
_MEDIA_KINDS: dict[str, MediaKind] = {
    "image": "image",
    "audio": "audio",
    "ptt": "audio",  # push-to-talk voice note — the common one for questions
    "voice": "audio",
    "document": "document",
    "video": "video",
    "sticker": "sticker",
}

_TEXT_TYPES = frozenset({"chat", "text", ""})


def _e164(jid: str) -> str:
    """
    Convert a WAHA JID like '584145610594@c.us' to '+584145610594'.

    Deliberately NOT country-canonicalised. This string becomes
    `conversation_key`, which `address_for` turns back into a JID to send the
    reply — and a Mexican wa_id (`521...`) canonicalises to a number that is not
    the deliverable address. Canonicalisation happens in the identity broker,
    which stores `phone_e164` and `wa_id` separately for exactly this reason.
    See `common/phone.py`.
    """
    m = _JID_DIGITS.match(jid)
    return f"+{m.group(1)}" if m else jid


class WahaTransport:
    """
    WAHA / NOWEB transport.

    Legacy inbound bridge with a scheduled retirement: it cannot send templates,
    and proactive outbound over an unofficial client is Meta's documented ban
    profile. It stays because it is what is deployed today.
    """

    name = "waha"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        hmac_key: str = "",
        session: str = "default",
        *,
        allow_unverified: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._hmac_key = hmac_key
        self._allow_unverified = allow_unverified
        self._client = httpx.AsyncClient(
            timeout=15.0,
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        )

    # ── Inbound ──────────────────────────────────────────────────────────────

    def verify(self, body: bytes, headers: Mapping[str, str]) -> bool:
        if not self._hmac_key:
            # Only reachable when the operator opted out explicitly; agent-core
            # refuses to boot otherwise.
            return self._allow_unverified
        signature = headers.get("X-Webhook-Hmac") or headers.get("x-webhook-hmac") or ""
        if not signature:
            logger.warning("waha webhook missing X-Webhook-Hmac header")
            return False
        return verify_waha_hmac(body, signature, self._hmac_key)

    def normalize(self, raw: dict[str, Any]) -> InboundEvent | None:
        if raw.get("event") != "message":
            return None

        payload: dict[str, Any] = raw.get("payload") or {}
        from_jid: str = payload.get("from") or ""
        event_id: str = payload.get("id") or ""
        if not event_id:
            logger.warning("waha message with no id — cannot dedup, dropping")
            return None

        msg_type: str = payload.get("type") or "chat"
        body: str = payload.get("body") or ""
        is_group: bool = bool(payload.get("isGroup", False))
        data: dict[str, Any] = payload.get("_data") or {}

        media = None
        if msg_type not in _TEXT_TYPES:
            raw_media: dict[str, Any] = payload.get("media") or {}
            caption = data.get("caption") or (body if body.strip() else None)
            media = InboundMedia(
                kind=_MEDIA_KINDS.get(msg_type, "unknown"),
                mime_type=raw_media.get("mimetype") or payload.get("mimetype"),
                url=raw_media.get("url"),
                caption=caption,
                provider_media_id=raw_media.get("id") or payload.get("mediaKey"),
                filename=raw_media.get("filename"),
            )
            # A caption is the patient's actual words; keep it as the text.
            body = caption or ""

        if not body.strip() and media is None:
            return None

        participant_jid: str | None = payload.get("participant") or None
        sender_e164 = _e164(participant_jid) if participant_jid else (
            _e164(from_jid) if from_jid and not is_group else None
        )

        return InboundEvent(
            source=self.name,
            source_event_id=event_id,
            conversation_key=from_jid if is_group else (_e164(from_jid) if from_jid else from_jid),
            text=body,
            sender_e164=sender_e164,
            sender_name=data.get("notifyName") or payload.get("senderName") or None,
            is_group=is_group,
            group_id=from_jid if is_group else None,
            from_me=bool(payload.get("fromMe", False)),
            is_status=bool(payload.get("isStatus", False)),
            timestamp=int(payload.get("timestamp") or 0),
            media=media,
            raw=raw,
        )

    # ── Outbound ─────────────────────────────────────────────────────────────

    def address_for(self, e164: str) -> str:
        return f"{e164.lstrip('+')}@c.us"

    async def send_text(self, address: str, text: str) -> str | None:
        resp = await self._client.post(
            f"{self._base_url}/api/sendText",
            json={"chatId": address, "text": text, "session": self._session},
        )
        if resp.status_code >= 400:
            logger.error(
                "waha send_text failed status=%s body=%s", resp.status_code, resp.text[:200]
            )
            resp.raise_for_status()
        try:
            return (resp.json() or {}).get("id")
        except Exception:  # noqa: BLE001 - a 2xx with an unparseable body still sent
            return None

    async def send_to_group(self, group_id: str, text: str) -> str | None:
        return await self.send_text(group_id, text)

    async def aclose(self) -> None:
        await self._client.aclose()
