from __future__ import annotations

import logging

from ..llm.anthropic import LLMClient
from ..llm.composition import (
    CLARIFY_SYSTEM,
    FALLBACK_SYSTEM,
    build_clarify_prompt,
    build_fallback_prompt,
)
from ..models import HandoffArgs, TaskResult, TurnContext

logger = logging.getLogger(__name__)

# Hardcoded canonical FAQ replies (mirrors the OpenClaw plugin DIRECT_FAQ_REPLIES)
DIRECT_FAQ_REPLIES: dict[str, str] = {
    "faq_location": (
        "¡Hola! NutriWhite está en Caracas, Venezuela 📍\n\n"
        "Nos encontramos en Alta Florida, Avenida Los Mangos, "
        "Centro Deportivo Caracas MultiSport, Piso 1.\n\n"
        "También ofrecemos consultas 100% online, así que puedes atenderte desde donde estés. "
        "¿Te gustaría conocer nuestros planes?"
    ),
    "faq_services": (
        "En NutriWhite te ofrecemos todo lo que necesitas para mejorar tu salud de forma integral 🌿\n\n"
        "✅ Consultas de inmunonutrición y nutrición\n"
        "✅ Exámenes especializados\n"
        "✅ Suplementos específicos según tu caso y ubicación\n"
        "✅ Protocolo 3R de acompañamiento\n"
        "✅ Evaluación gratuita de salud\n"
        "✅ Llamada informativa gratis de 15 minutos\n\n"
        "Para suplementos fuera de Venezuela trabajamos con Fullscript y Wholescripts; "
        "en Venezuela lo coordina nuestro equipo de logística. "
        "¿Quieres conocer nuestros planes de consulta?"
    ),
    "faq_consultation_plans": (
        "Tenemos dos líneas de planes para acompañarte 💙\n\n"
        "*PLAN INMUNONUTRICIÓN* — con nuestros especialistas\n"
        "• 1 consulta — $249 USD\n"
        "• 2 consultas — $399 USD\n"
        "• 4 consultas — $599 USD\n"
        "• 6 consultas — $799 USD\n\n"
        "*PLAN NUTRICIÓN* — con nuestro equipo de nutricionistas\n"
        "• 1 consulta — $149 USD\n"
        "• 2 consultas — $279 USD\n"
        "• 3 consultas — $329 USD\n"
        "• 5 consultas — $450 USD\n\n"
        "Los exámenes se recomiendan dentro del plan y no están incluidos en el precio. "
        "Las cuotas son solo con TDC y tienen 3% de comisión bancaria.\n\n"
        "¿Te agendo tu llamada gratuita de 15 minutos para ver cuál se adapta mejor a tu caso?"
    ),
    "faq_payment_methods": (
        "Aceptamos varias formas de pago para tu comodidad 💳\n\n"
        "• PayPal\n• Zelle\n• Tarjeta de crédito (TDC)\n• Efectivo\n• Pago móvil (Venezuela)\n\n"
        "Las cuotas están disponibles solo con TDC y se añade un 3% de comisión bancaria.\n\n"
        "NutriWhite no trabaja directamente con seguros, pero podemos emitir factura para que "
        "gestiones el reembolso con tu corredor si tu seguro cubre nutrición. "
        "¿Tienes alguna otra pregunta?"
    ),
}

HANDOFF_INTENTS = frozenset({
    "handoff_specialist_recommendation",
    "handoff_scheduling",
    "handoff_discount",
    "handoff_medical_advice",
    "handoff_refund",
    "handoff_post_payment_logistics",
    "handoff_english",
    "handoff_distress",
})

HANDOFF_PHRASE = (
    "Para esto te conecto con una asesora que te dará la mejor recomendación "
    "según tu caso 🩵 Un momento por favor."
)
HANDOFF_ENGLISH_PHRASE = "Let me connect you with a colleague who'll attend you in English 🩵"

GREETING_INTENTS = frozenset({"greeting"})
FAREWELL_INTENTS = frozenset({"farewell"})

# Greetings and farewells are the highest-volume intents in the whole product and
# there is nothing for a model to decide in them. Composing them burned an LLM
# call per "hola" and added latency to the first impression.
CANNED_GREETING = "¡Hola! 🩵 Soy Gutty, de NutriWhite. ¿En qué te puedo ayudar hoy?"
CANNED_FAREWELL = "¡Hasta pronto! 🩵 Cuídate mucho."


class CustomerServiceTask:
    name = "customer_service"
    handled_intents = frozenset(
        set(DIRECT_FAQ_REPLIES)
        | HANDOFF_INTENTS
        | GREETING_INTENTS
        | FAREWELL_INTENTS
        | {
            "faq_consultation_call",
            "faq_protocol_3r",
            "faq_supplements_general",
            "faq_exams_general",
            "patient_plan_status",
            "patient_appointment_status",
            "patient_exam_status",
            "acknowledgment",
            "unknown",
        }
    )

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

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
                return TaskResult.canned(
                    "¿Me puedes dar más detalles sobre lo que necesitas? 🩵"
                )

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
            return TaskResult.canned(
                "Tengo un problema técnico, ya te conecto con una asesora 🩵"
            )

    def _build_team_notification(self, ctx: TurnContext, reason: str) -> str:
        label = ctx.sender_name or ctx.phone
        return (
            f"🚨 *Handoff* — {label}\n"
            f"📱 {ctx.phone}\n"
            f"Motivo: {reason}\n"
            f"Última pregunta: \"{ctx.inbound_text[:200]}\"\n\n"
            "Quien toma el caso, responde \"TOMO\" en este grupo."
        )
