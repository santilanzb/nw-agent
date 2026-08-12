from __future__ import annotations

GUTTY_SYSTEM = """\
Eres Gutty, ejecutiva de atención al paciente de NutriWhite. Eres empática, cálida y observadora.
Atiendes pacientes sobre inmunonutrición, el Protocolo 3R, consultas, exámenes y suplementos.

Reglas:
- Responde siempre en español (Caracas-friendly, tuteo).
- Sé concisa y cálida: 2-4 párrafos cortos máximo.
- Usa emojis suaves: 💙 🩵 ✅ 😊 — nunca en exceso.
- Formato WhatsApp: *negritas*, _cursivas_, ✅ puntos.
- Cierra siempre con un próximo paso claro o una pregunta.
- Nunca inventes precios, fechas, nombres de especialistas ni recomendaciones médicas.
- Si no tienes la información exacta, deriva a una asesora.
"""

GREETING_SYSTEM = GUTTY_SYSTEM + """
El paciente acaba de saludar. Saluda de vuelta con calidez y ofrece ayuda.
Ejemplo de apertura: "Hola buenos días 🩵 Soy Gutty de NutriWhite. ¿En qué te puedo ayudar hoy?"
"""

FAREWELL_SYSTEM = GUTTY_SYSTEM + """
El paciente se está despidiendo. Despídete con calidez, deja la puerta abierta para futuras consultas.
"""

CLARIFY_SYSTEM = GUTTY_SYSTEM + """
El mensaje del paciente es ambiguo entre varias intenciones. Formula UNA sola pregunta corta para aclarar.
Ofrece las opciones más probables de forma natural dentro de la pregunta.
No respondas la pregunta todavía — solo pide la aclaración.
"""

FALLBACK_SYSTEM = GUTTY_SYSTEM + """
La intención del paciente no fue clasificada con certeza. Responde con tu mejor criterio dentro
de las políticas de NutriWhite. Si hay riesgo de inventar datos específicos (precios, fechas,
disponibilidad, recomendaciones médicas), deriva a una asesora en lugar de inventar.
"""


def build_clarify_prompt(message: str, top_matches: list) -> str:
    options = ""
    for m in top_matches[:3]:
        options += f"- {m.intent} (score: {m.score:.2f})\n"
    return (
        f"Mensaje del paciente: \"{message}\"\n\n"
        f"Posibles intenciones detectadas:\n{options}\n"
        "Escribe una pregunta corta para aclarar cuál es su necesidad."
    )


MAX_CONTEXT_CHARS = 3000


def build_fallback_prompt(
    message: str,
    context: list | None = None,
    history: list | None = None,
) -> str:
    """
    The composed-answer prompt.

    This used to pass the patient's message and nothing else, so every off-FAQ
    answer came from the model's own knowledge of NutriWhite — which is none.
    Two things are added, and the order matters: the conversation so far, then
    the retrieved documentation, then the question.

    The instruction to answer ONLY from the provided context is what turns
    "don't invent prices" from a request into something checkable — an answer
    that cites nothing is a visible failure rather than a plausible paragraph.
    """
    sections: list[str] = []

    if history:
        turns = "\n".join(
            f"{'Paciente' if e.direction == 'inbound' else 'Gutty'}: {e.text}" for e in history
        )
        sections.append(f"Conversación reciente:\n{turns}")

    if context:
        used = 0
        excerpts: list[str] = []
        for chunk in context:
            text = chunk.content.strip()
            if used + len(text) > MAX_CONTEXT_CHARS:
                break
            excerpts.append(f"[{chunk.source_uri}]\n{text}")
            used += len(text)
        if excerpts:
            sections.append("Información de NutriWhite:\n\n" + "\n\n".join(excerpts))

    sections.append(f'Mensaje del paciente: "{message}"')

    if context:
        sections.append(
            "Responde ÚNICAMENTE con información presente arriba. Si la respuesta no está ahí, "
            "dilo con naturalidad y ofrece conectar con una asesora — no la deduzcas."
        )
    else:
        sections.append(
            "Responde como Gutty con tu mejor criterio. Si no tienes la información exacta, "
            "indica que conectarás con una asesora."
        )

    return "\n\n".join(sections)


def build_greeting_prompt(message: str) -> str:
    return f"El paciente dice: \"{message}\"\n\nSaluda de vuelta y ofrece ayuda."


def build_farewell_prompt(message: str) -> str:
    return f"El paciente dice: \"{message}\"\n\nDespídete con calidez."
