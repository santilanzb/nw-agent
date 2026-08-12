from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .base import InboundEvent, InboundMedia, MediaKind
from .hmac_verify import verify_waha_hmac

logger = logging.getLogger(__name__)

_JID_DIGITS = re.compile(r"^(\d+)@")

# WhatsApp's LID addressing. `payload.from` is increasingly a *linked id* —
# `65575912997059@lid` — an opaque per-contact handle that is not a phone number
# and never was. The real number rides alongside, in `_data.key.remoteJidAlt`.
#
# Read the LID as if it were a number and everything downstream is quietly wrong:
# the identity broker registers a patient at `+65575912997059`, the ticket is
# keyed on it so no asesora can ever claim the case, and the reply is addressed
# to a JID that does not resolve. Verified live on 2026-08-12, first inbound
# message from a real phone — the simulated transport never produced a LID, so
# nothing in the suite had ever seen one.
_LID_SUFFIX = "@lid"
_GROUP_SUFFIX = "@g.us"


def _addressable(payload: dict[str, Any], jid: str, alt_key: str) -> str:
    """
    The phone-bearing JID behind a LID, or the JID unchanged.

    Falls back to the LID rather than dropping the message: an unaddressable
    conversation is still a patient talking to us, and `merge_state='review'` is
    where an unparseable number is supposed to land.
    """
    if not jid or not jid.endswith(_LID_SUFFIX):
        return jid
    alt = ((payload.get("_data") or {}).get("key") or {}).get(alt_key) or ""
    if not alt:
        logger.warning(
            "LID %s carries no %s — the conversation has no usable number", jid, alt_key
        )
        return jid
    return str(alt)

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


def _media_kind(msg_type: str, mimetype: str | None) -> MediaKind:
    """
    What kind of thing the patient sent, from whatever the payload offers.

    `type` is authoritative when present and absent in WAHA 2026.7, so the
    mimetype is the fallback. Getting this wrong is not fatal — the acknowledgement
    is the same either way — but it is what the asesora reads next to the
    reference, so "audio" for a voice note beats "unknown" for everything.
    """
    if msg_type in _MEDIA_KINDS:
        return _MEDIA_KINDS[msg_type]

    mime = (mimetype or "").split(";")[0].strip().lower()
    if not mime:
        return "unknown"
    # WhatsApp stickers are webp; a photo is jpeg or png.
    if mime == "image/webp":
        return "sticker"
    top = mime.split("/")[0]
    if top in ("image", "audio", "video"):
        return top  # type: ignore[return-value]
    return "document"


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

    def _media_url(self, url: str | None) -> str | None:
        """
        Resolve a media URL against the address we know WAHA by.

        WAHA reports its file endpoint as `http://localhost:3000/...` — its own
        localhost, from inside its own container. agent-core following that
        literally connects to itself and fails, so every payment proof was
        recorded as `fetch_failed` while sitting one hostname away. The host WAHA
        believes it has is never more authoritative than the one we configured to
        reach it.
        """
        if not url:
            return url
        parsed = urlsplit(url)
        if not parsed.netloc:
            return url
        base = urlsplit(self._base_url)
        if not base.netloc or parsed.netloc == base.netloc:
            return url
        return urlunsplit(
            (base.scheme or parsed.scheme, base.netloc, parsed.path, parsed.query, "")
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
        # Resolved before anything reads it: a LID that reaches conversation_key
        # becomes a fake patient, an unclaimable ticket and an undeliverable reply.
        from_jid: str = _addressable(payload, payload.get("from") or "", "remoteJidAlt")
        event_id: str = payload.get("id") or ""
        if not event_id:
            logger.warning("waha message with no id — cannot dedup, dropping")
            return None

        msg_type: str = payload.get("type") or "chat"
        body: str = payload.get("body") or ""
        # Derived from the address, not from a flag. WAHA 2026.7 sends no
        # `isGroup` at all, so trusting it made every team-group message look
        # like a direct message from a "patient" whose number was the group id —
        # the claim command was refused by the DM allowlist and the case could
        # never be taken. A JID ending in @g.us *is* a group; that is WhatsApp's
        # own addressing and it does not depend on a provider's field surviving
        # a version bump. The flag is still honoured when present.
        is_group: bool = bool(payload.get("isGroup", False)) or from_jid.endswith(_GROUP_SUFFIX)
        data: dict[str, Any] = payload.get("_data") or {}

        media = None
        raw_media: dict[str, Any] = payload.get("media") or {}
        # Media is detected from the payload's own evidence, not from `type`.
        # WAHA 2026.7 sends no `type` at all, so every inbound photo looked like
        # an empty text message and normalize dropped it — returning None, which
        # answers 204 and writes nothing, so a patient's payment proof vanished
        # with no record it had ever arrived. This is the third field this
        # transport stopped sending today.
        has_media = bool(payload.get("hasMedia")) or bool(raw_media.get("url"))
        if has_media or msg_type not in _TEXT_TYPES:
            mimetype = raw_media.get("mimetype") or payload.get("mimetype")
            caption = data.get("caption") or (body if body.strip() else None)
            media = InboundMedia(
                kind=_media_kind(msg_type, mimetype),
                mime_type=mimetype,
                url=self._media_url(raw_media.get("url")),
                caption=caption,
                provider_media_id=raw_media.get("id") or payload.get("mediaKey"),
                filename=raw_media.get("filename"),
            )
            # A caption is the patient's actual words; keep it as the text.
            body = caption or ""

        if not body.strip() and media is None:
            return None

        # Same treatment for the group sender: the participant list this org's
        # groups return is LID-addressed, so an asesora's claim would be recorded
        # against an id that is not her phone.
        participant_jid: str | None = (
            _addressable(payload, payload.get("participant") or "", "participantAlt") or None
        )
        sender_e164 = _e164(participant_jid) if participant_jid else (
            _e164(from_jid) if from_jid and not is_group else None
        )

        return InboundEvent(
            source=self.name,
            source_event_id=event_id,
            conversation_key=from_jid if is_group else (_e164(from_jid) if from_jid else from_jid),
            text=body,
            sender_e164=sender_e164,
            # `pushName` first: WAHA 2026.7 sends that and no `notifyName`, so
            # every patient arrived anonymous. The team notice showed a phone
            # number where the asesora needed a name, and the context package's
            # display_name was null for everyone. The older keys stay as
            # fallbacks rather than being swapped out.
            sender_name=(
                data.get("pushName")
                or data.get("notifyName")
                or payload.get("senderName")
                or None
            ),
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
