from __future__ import annotations

import asyncio
import uuid

from company_agent.agent_core.models import ClassificationResult, TurnContext
from company_agent.agent_core.tasks.customer_service import (
    CANNED_FAREWELL,
    CANNED_GREETING,
    DIRECT_FAQ_REPLIES,
    CustomerServiceTask,
)


class _ExplodingLLM:
    """Any composition attempt fails the test loudly."""

    def model(self, tier: str) -> str:
        raise AssertionError(f"model({tier!r}) consulted on a turn that must not compose")

    async def compose(self, **kwargs: object) -> tuple[str, int, int]:
        raise AssertionError("LLM composed a reply on a turn that must not compose")


def _ctx(
    intent: str,
    *,
    decision: str = "execute",
    deterministic_only: bool = False,
    text: str = "hola",
) -> TurnContext:
    return TurnContext(
        turn_id=uuid.uuid4(),
        phone="+584145610594",
        contact_id=None,
        inbound_text=text,
        inbound_event_id="evt-1",
        classification=ClassificationResult(
            intent=intent,
            confidence=0.93,
            decision=decision,  # type: ignore[arg-type]
            dispatch=None,
            top_matches=[],
        ),
        deterministic_only=deterministic_only,
    )


def _handle(ctx: TurnContext):
    return asyncio.run(CustomerServiceTask(llm=_ExplodingLLM()).handle(ctx))


# ── Canned greetings: no model call on the highest-volume intents ─────────────

def test_greeting_is_canned_and_never_calls_the_model() -> None:
    result = _handle(_ctx("greeting"))
    assert result.reply_text == CANNED_GREETING
    assert result.composed_by_llm is False


def test_farewell_is_canned_and_never_calls_the_model() -> None:
    result = _handle(_ctx("farewell"))
    assert result.reply_text == CANNED_FAREWELL
    assert result.composed_by_llm is False


# ── deterministic_only: the mute check failed, a human may be on the line ─────

def test_deterministic_only_still_answers_a_direct_faq() -> None:
    """Deterministic answers stay available — they are exact and pre-approved."""
    result = _handle(_ctx("faq_location", deterministic_only=True))
    assert result.reply_text == DIRECT_FAQ_REPLIES["faq_location"]
    assert result.composed_by_llm is False


def test_deterministic_only_still_hands_off() -> None:
    result = _handle(_ctx("handoff_medical_advice", deterministic_only=True))
    assert result.handoff is not None
    assert result.task_outcome == "handoff"


def test_deterministic_only_stays_silent_instead_of_composing_a_fallback() -> None:
    """
    The regression this guards: an unreachable crm-adapter made check_active return
    False, so Gutty composed a reply into a conversation a human asesora had already
    claimed. Silence is the correct degradation.
    """
    result = _handle(_ctx("patient_plan_status", deterministic_only=True, text="¿y mi plan?"))
    assert result.reply_text is None
    assert result.task_outcome == "silent"


def test_deterministic_only_does_not_compose_a_clarify_question() -> None:
    result = _handle(
        _ctx("faq_supplements_general", decision="clarify", deterministic_only=True)
    )
    assert result.reply_text is None
    assert result.task_outcome == "silent"


def test_acknowledgment_is_silent() -> None:
    result = _handle(_ctx("acknowledgment", text="ok gracias"))
    assert result.task_outcome == "silent"
