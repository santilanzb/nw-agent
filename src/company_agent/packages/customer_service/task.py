from __future__ import annotations

import logging

from company_agent.agent_core.llm.anthropic import LLMClient
from company_agent.agent_core.llm.composition import (
    CLARIFY_SYSTEM,
    FALLBACK_SYSTEM,
    build_clarify_prompt,
    build_fallback_prompt,
)
from company_agent.agent_core.models import HandoffArgs, TaskResult, TurnContext

from .policy import (
    CANNED_FAREWELL,
    CANNED_GREETING,
    CLARIFY_FAILED_REPLY,
    COMPOSE_FAILED_REPLY,
    DIRECT_FAQ_REPLIES,
    FAREWELL_INTENTS,
    GREETING_INTENTS,
    HANDOFF_ENGLISH_PHRASE,
    HANDOFF_INTENTS,
    HANDOFF_PHRASE,
)

logger = logging.getLogger(__name__)


class CustomerServiceTask:
    """
    The patient-facing turn handler: deterministic FAQ, handoff, LLM fallback.

    `handled_intents` is **injected, not declared**. It used to be a
    hand-maintained frozenset of 22 names whose only job was to equal the keys of
    a YAML file in another directory, with nothing asserting they matched. The
    registrar now derives it from this package's own `seeds.yaml` plus the
    manifest's `synthetic_intents`, which removes the drift class rather than
    detecting it.

    The default is empty so the class stays constructible in isolation — several
    tests build it directly to assert gate behaviour, and those tests are about
    what `handle()` does with a classification, not about who claims what.
    """

    name = "customer_service"

    def __init__(self, llm: LLMClient, *, handled_intents: frozenset[str] = frozenset()) -> None:
        self._llm = llm
        self.handled_intents = handled_intents

    async def handle(self, ctx: TurnContext) -> TaskResult:
        cls = ctx.classification
        intent = cls.intent
        decision = cls.decision

        # ── 1. Handoff triggers ───────────────────────────────────────────────
        if (
            intent in HANDOFF_INTENTS
            or (cls.dispatch and cls.dispatch.tool == "handoff_human")
        ):
            reason = (
                (cls.dispatch.params.get("reason") if cls.dispatch else None)
                or intent
            )
            priority = (
                (cls.dispatch.params.get("priority") if cls.dispatch else None)
                or "high"
            )
            phrase = HANDOFF_ENGLISH_PHRASE if intent == "handoff_english" else HANDOFF_PHRASE
            team_notif = self._build_team_notification(ctx, reason)
            return TaskResult.with_handoff(
                reply_text=phrase,
                handoff=HandoffArgs(
                    reason=reason,
                    priority=priority,
                    patient_name=ctx.sender_name,
                    last_message=ctx.inbound_text,
                    conversation_id=ctx.inbound_event_id,
                ),
                team_notification_text=team_notif,
            )

        # ── 2. Direct FAQ ─────────────────────────────────────────────────────
        if intent in DIRECT_FAQ_REPLIES and decision == "execute":
            return TaskResult.canned(DIRECT_FAQ_REPLIES[intent])

        # ── 3. Acknowledgment — silent ────────────────────────────────────────
        if intent == "acknowledgment":
            return TaskResult.silent()

        # ── 4. Clarify — the model composes the disambiguating question ───────
        if decision == "clarify" and not ctx.deterministic_only:
            try:
                prompt = build_clarify_prompt(ctx.inbound_text, cls.top_matches)
                text, tok_in, tok_out = await self._llm.compose(
                    turn_id=ctx.turn_id,
                    tier="escalation",
                    system=CLARIFY_SYSTEM,
                    user_message=prompt,
                    max_tokens=256,
                    trace_name="clarify",
                )
                return TaskResult.llm_composed(
                    text, self._llm.model("escalation"), tok_in, tok_out
                )
            except Exception as exc:  # noqa: BLE001 - any model failure degrades to canned
                logger.error("clarify compose failed: %s", exc)
                return TaskResult.canned(CLARIFY_FAILED_REPLY)

        # ── 5. Greeting / farewell — canned, no model call ────────────────────
        if intent in GREETING_INTENTS:
            return TaskResult.canned(CANNED_GREETING)

        if intent in FAREWELL_INTENTS:
            return TaskResult.canned(CANNED_FAREWELL)

        # ── 6. Everything below composes. If a pre-send gate could not be ────
        # evaluated we stop here rather than risk answering into a live handoff.
        if ctx.deterministic_only:
            logger.warning(
                "deterministic_only turn has no deterministic answer intent=%s — staying silent",
                intent,
            )
            return TaskResult.silent()

        # ── 7. Fallback / unknown / patient-specific ──────────────────────────
        try:
            prompt = build_fallback_prompt(ctx.inbound_text)
            text, tok_in, tok_out = await self._llm.compose(
                turn_id=ctx.turn_id,
                tier="escalation",
                system=FALLBACK_SYSTEM,
                user_message=prompt,
                max_tokens=512,
                trace_name="fallback",
            )
            return TaskResult.llm_composed(
                text, self._llm.model("escalation"), tok_in, tok_out
            )
        except Exception as exc:  # noqa: BLE001 - any model failure degrades to canned
            logger.error("fallback compose failed: %s", exc)
            return TaskResult.canned(COMPOSE_FAILED_REPLY)

    def _build_team_notification(self, ctx: TurnContext, reason: str) -> str:
        label = ctx.sender_name or ctx.phone
        return (
            f"🚨 *Handoff* — {label}\n"
            f"📱 {ctx.phone}\n"
            f"Motivo: {reason}\n"
            f"Última pregunta: \"{ctx.inbound_text[:200]}\"\n\n"
            "Quien toma el caso, responde \"TOMO\" en este grupo."
        )
