"""
Transport-neutral inbound/outbound contract.

The FSM used to speak WAHA's payload shape directly, which meant adding Meta
Cloud API would have touched every layer. Everything above this module now sees
an InboundEvent and an address string, and never learns which wire carried them.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# Drives the in-doubt policy in the send outbox. Replies and utility messages are
# safe to re-send after an ambiguous failure; a marketing template is not — Meta
# bills it and the patient sees it twice — so it waits for status correlation and
# then degrades to a human task.
MessageClass = Literal["reply", "utility", "marketing", "team"]

MediaKind = Literal["image", "audio", "document", "video", "sticker", "unknown"]


@dataclass(slots=True, frozen=True)
class InboundMedia:
    """
    Patients send payment proofs as photos and questions as voice notes. WAHA's
    normalizer used to return None for all of these, so they vanished with no log
    line and no reply — the patient saw silence.
    """

    kind: MediaKind
    mime_type: str | None = None
    url: str | None = None
    caption: str | None = None
    provider_media_id: str | None = None
    filename: str | None = None


@dataclass(slots=True)
class InboundEvent:
    """One inbound message, normalized. `source` + `source_event_id` is the inbox key."""

    source: str
    source_event_id: str
    # Routing key: E.164 for a direct message, the group id for a group.
    conversation_key: str
    text: str
    sender_e164: str | None = None
    sender_name: str | None = None
    is_group: bool = False
    group_id: str | None = None
    from_me: bool = False
    is_status: bool = False
    timestamp: int = 0
    media: InboundMedia | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


@runtime_checkable
class Transport(Protocol):
    """A wire that carries WhatsApp messages. WAHA today, Meta Cloud API next."""

    name: str

    def verify(self, body: bytes, headers: Mapping[str, str]) -> bool:
        """Authenticate a raw webhook delivery. Must fail closed."""
        ...

    def normalize(self, raw: dict[str, Any]) -> InboundEvent | None:
        """Parse a webhook body. None means 'not a message we route'."""
        ...

    def address_for(self, e164: str) -> str:
        """Transport-specific address for a phone number (a JID, a wa_id, ...)."""
        ...

    async def send_text(self, address: str, text: str) -> str | None:
        """Send text. Returns the provider message id when the transport gives one."""
        ...

    async def aclose(self) -> None: ...
