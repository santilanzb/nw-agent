"""
What Gutty says, and when — the customer_service package's policy surface.

Separate from `task.py` on purpose. This module imports nothing but `__future__`,
so the copy a patient reads can be loaded, diffed and regenerated without
touching the task, the LLM client or agent-core's settings.
`tests/test_faq_parity.py` reads it to check the OpenClaw plugin still says the
same thing.

**The prices here are generated data pretending to be source.** They were
hand-corrected on 2026-08-11 after Zoho retired the $229 plan while both policy
surfaces kept quoting it. Graft G2 replaces this block with a render of
`facts/prices.yaml`, pulled from Zoho Products keyed on record id. Until then, a
price changed here must be changed in
`openclaw/plugins/customer-service-tools/index.js` in the same commit.
"""
from __future__ import annotations

# Deterministic answers. These exist because they are the highest-frequency
# questions and we want zero latency and zero hallucination risk on prices and
# plan details — no retrieval, no model call.
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

# Intents that always reach a human. The classifier's dispatch tool
# (`handoff_human`) is the other trigger; either is sufficient.
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

CLARIFY_FAILED_REPLY = "¿Me puedes dar más detalles sobre lo que necesitas? 🩵"
COMPOSE_FAILED_REPLY = "Tengo un problema técnico, ya te conecto con una asesora 🩵"
