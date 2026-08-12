from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

# Inbound wire shapes live in transport/base.py as the transport-neutral
# InboundEvent. Nothing above the transport layer sees a provider's payload.

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
    # The durable key for this patient. None when identity resolution failed —
    # the turn still gets answered, it just has no history to draw on.
    inbound_text: str
    inbound_event_id: str
    classification: ClassificationResult
    identity_id: uuid.UUID | None = None
    sender_name: str | None = None
    is_group: bool = False
    group_jid: str | None = None
    participant_phone: str | None = None
    # Set when a pre-send gate could not be evaluated — today, when the handoff
    # mute check failed. Task modules must answer from deterministic sources only
    # and never compose with the LLM: we may be talking into a live human handoff.
    deterministic_only: bool = False


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
    def with_handoff(cls, reply_text: str, handoff: HandoffArgs) -> TaskResult:
        """
        A task says a human is needed. What the team is *told* is the FSM's, not
        the task's: a task module cannot know the ticket id, and the one that
        tried to write the notification put the patient's message in it.
        """
        return cls(reply_text=reply_text, handoff=handoff, task_outcome="handoff")

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
