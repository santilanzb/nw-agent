from __future__ import annotations

import logging

from ..models import HandoffArgs, TaskResult, TurnContext

logger = logging.getLogger(__name__)

FALLBACK_PHRASE = (
    "Déjame conectarte con una asesora para que te atienda como mereces 🩵 "
    "Un momento por favor."
)


class FallbackTask:
    """
    Terminal handler for intents no package claimed.

    Reaching this is a configuration defect — an intent exists in
    a package's seeds.yaml that no task module declares. The registry already
    logged it; this module makes sure the patient is not left unanswered while the
    defect is fixed, by escalating to a human instead of guessing.
    """

    name = "fallback"
    handled_intents: frozenset[str] = frozenset()

    async def handle(self, ctx: TurnContext) -> TaskResult:
        logger.error(
            "fallback_handler turn_id=%s intent=%s — escalating to human",
            ctx.turn_id,
            ctx.classification.intent,
        )
        return TaskResult.with_handoff(
            reply_text=FALLBACK_PHRASE,
            handoff=HandoffArgs(
                reason=f"unclaimed_intent:{ctx.classification.intent}",
                priority="normal",
                patient_name=ctx.sender_name,
            ),
        )
