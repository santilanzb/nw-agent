from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


# ── WAHA payload shapes ───────────────────────────────────────────────────────

@dataclass(slots=True)
class WahaInboundMessage:
    event_id: str           # WAHA message id (used for dedup)
    from_jid: str           # raw JID from WAHA (e.g. "584145610594@c.us")
    phone: str              # normalized E.164 ("+584145610594"); group JID for groups
    group_jid: str | None   # set when is_group=True; same as from_jid
    participant_jid: str | None  # actual sender inside a group
    participant_phone: str | None  # E.164 of the group sender
    text: str               # message body
    is_group: bool
    from_me: bool
    is_status: bool         # WhatsApp status update (skip)
    timestamp: int
    sender_name: str | None


# ── Intent/dispatch shapes (mirror rag_api.schemas, kept local to avoid coupling) ──

@dataclass(slots=True)
class IntentDispatch:
    tool: str | None
    params: dict[str, Any]


@dataclass(slots=True)
class IntentMatch:
    intent: str
    score: float
    example: str


@dataclass(slots=True)
class ClassificationResult:
    intent: str
    confidence: float
    decision: Literal["execute", "clarify", "fallback_llm"]
    dispatch: IntentDispatch | None
    top_matches: list[IntentMatch]


# ── Task context and result ───────────────────────────────────────────────────

@dataclass
class TurnContext:
    turn_id: uuid.UUID
    phone: str
    contact_id: str | None
    inbound_text: str
    inbound_event_id: str
    classification: ClassificationResult
    sender_name: str | None = None
    is_group: bool = False
    group_jid: str | None = None
    participant_phone: str | None = None


@dataclass
class HandoffArgs:
    reason: str
    priority: str = "high"
    contact_id: str | None = None
    patient_name: str | None = None
    last_message: str | None = None
    conversation_id: str | None = None


@dataclass
class TaskResult:
    reply_text: str | None = None
    team_notification_text: str | None = None
    handoff: HandoffArgs | None = None
    task_outcome: str = "replied"           # 'replied' | 'silent' | 'handoff' | 'error'
    composed_by_llm: bool = False
    model_used: str | None = None
    composition_tokens_in: int | None = None
    composition_tokens_out: int | None = None

    @classmethod
    def silent(cls) -> TaskResult:
        return cls(reply_text=None, task_outcome="silent")

    @classmethod
    def canned(cls, text: str) -> TaskResult:
        return cls(reply_text=text, task_outcome="replied")

    @classmethod
    def with_handoff(
        cls,
        reply_text: str,
        handoff: HandoffArgs,
        team_notification_text: str | None = None,
    ) -> TaskResult:
        return cls(
            reply_text=reply_text,
            handoff=handoff,
            team_notification_text=team_notification_text,
            task_outcome="handoff",
        )

    @classmethod
    def llm_composed(
        cls,
        text: str,
        model: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> TaskResult:
        return cls(
            reply_text=text,
            task_outcome="replied",
            composed_by_llm=True,
            model_used=model,
            composition_tokens_in=tokens_in,
            composition_tokens_out=tokens_out,
        )
