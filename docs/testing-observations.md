# Agent Testing & Observations Log

A shared log for the NutriWhite team to record what they see when testing **Gutty**, the WhatsApp customer service agent. Treat this file as the single source of truth for "what broke", "what felt off", and "what worked surprisingly well" while we tune the agent.

> Not a bug tracker. Real bugs that need engineering work move to issues. This file is the upstream feed — raw observations, examples, and discussion.

---

## How to use this document

1. **Add a new entry** under [Observations](#observations) using the [entry template](#entry-template). Newest at the top.
2. **Comment on existing entries** under their `Notes & comments` block. Sign each comment with your name and the date.
3. **Don't edit someone else's entry body.** Add a comment instead. If a fix lands, change the `Status` line and add a closing comment with the commit / PR link.
4. **Attach evidence.** Screenshot, journal record id, or eval run path — anything that lets the next person reproduce what you saw.
5. **One observation per entry.** If you find five things in one conversation, file five entries that reference the same conversation id.

---

## What to test

The agent's job is narrow: respond to WhatsApp messages as Gutty, in Spanish, using only approved tools and approved knowledge. The categories below mirror the [policy](../openclaw/skills/customer-service-policy/SKILL.md) — please cover each at least once per round.

### 1. Persona & tone
- Default language is Spanish, Caracas-friendly, "tú" by default.
- Warm opener ("Hola buenos días! Gusto en saludarte").
- Soft emojis only (💙 🩵 ✅ 😊 🤗). No clownish or excessive emoji.
- WhatsApp formatting: `*negritas*`, `_cursivas_`, ✅ bullets.
- Closes with one clear next step or question.

### 2. Tool routing (most failures live here)
- General FAQ → `kb_search` or the matching `faq_*` tool.
- Plan / price questions → `faq_consultation_plans` (NOT `customer_lookup`).
- Patient-specific status (their plan, citas, exámenes) → `customer_lookup` first, then orders/consultas/examenes.
- Anything requiring judgment → `handoff_human`.
- The agent should **not** ask a clarifying question before `kb_search` for broad FAQ phrasings ("planes", "donde están ubicados", "métodos de pago", etc.).

### 3. Handoff triggers (must escalate)
- English-language message.
- Specialist recommendations or availability.
- Discounts, refunds, billing disputes, plan negotiations.
- Medical advice or diagnosis.
- Post-payment logistics (paid patients are handled by humans).
- Abusive or distressed users.
- Weak / no `kb_search` results.

### 4. Hallucination & invented details
- Made-up prices, dosis, dates, specialist names, product categories.
- Forbidden categories unless KB explicitly contains them: "vitalidad", "antioxidantes", "refuerzo inmunológico", "bienestar digestivo".
- Claiming an action completed when no tool was actually called.
- Calculating installment totals or applied commissions (allowed to cite the +3% TDC rule; not allowed to compute the final number).

### 5. Identity & privacy
- Phone number of WhatsApp sender must match a Zoho Contact before revealing any private detail (orders, citas, exámenes).
- If no match → polite confirmation / new-contact flow, never a leak.

### 6. Knowledge accuracy
- Plan 1 = $229 USD, 1 mes, 1 consulta de 90 min.
- Plan 3 = $559 USD, 3 meses, 3 consultas.
- Plan 5 = $789 USD, 5 meses, 5 consultas.
- Ubicación: Caracas, Alta Florida, Avenida Los Mangos, Centro Deportivo Caracas MultiSport, Piso 1 (+ online).
- Pagos: PayPal, Zelle, TDC, Efectivo, Pago móvil. Cuotas solo TDC +3%.
- Cita free: 15 min.

### 7. Failure modes to watch for
- Mixed-language filler ("Let me buscar", "No problem").
- Standalone "un momento" without an actual tool call.
- Robotic / repetitive phrasing across turns.
- Losing thread when the user changes topic mid-conversation.

---

## Test environment notes

- **Mock CRM contact** for local testing: `cust_1001` — Camila Valecillos, `+584145610594` (see [`MockCrmAdapter`](../src/company_agent/crm_adapter/adapters.py)). Use this when you don't want to touch Zoho sandbox.
- **Zoho sandbox** is gated by `CRM_PROVIDER=zoho` + `ZOHO_SANDBOX=true`. Smoke test before each session: `python scripts/zoho_smoke_test.py`.
- **Eval cases** live in [`eval/seeds.yaml`](../eval/seeds.yaml). If you find a new scenario worth testing repeatedly, add it there too.
- **Message journal** at `/root/nw-agent/runtime/openclaw-message-journal.jsonl` on the OpenClaw host captures every inbound/outbound. Use `scripts/openclaw_pending_messages.py` to scan for unanswered messages.

---

## Severity & status conventions

**Severity**
- `blocker` — agent gives wrong information that could harm the business (wrong price, leaked private data, missed handoff on medical/English).
- `high` — clear policy violation but recoverable (wrong tool, invented product category).
- `medium` — tone or style miss that a patient would notice.
- `low` — minor phrasing, formatting, emoji choice.
- `nit` — purely subjective preference.

**Status**
- `open` — newly filed.
- `investigating` — someone is actively looking.
- `fixed` — change merged; please verify before closing.
- `verified` — fix confirmed in a new conversation.
- `wontfix` — by design or out of scope (add reason in comments).
- `duplicate` — link to the original entry.

---

## Entry template

Copy this block when adding a new observation.

```markdown
### YYYY-MM-DD — Short title — Reporter name

- **Severity:** blocker | high | medium | low | nit
- **Status:** open
- **Category:** persona | routing | handoff | hallucination | privacy | knowledge | other
- **Model / build:** e.g. haiku-4.5 (eval) or OpenClaw gateway v2026.3.24-beta.2
- **Channel:** WhatsApp live | eval harness | manual REST
- **Conversation id / evidence:** journal id, screenshot path, or eval results dir
- **Reproducibility:** always | sometimes | one-off

**Scenario**
What were you trying to test, and what state was the contact / sandbox in.

**Input**
> The exact patient message (or sequence). Paste in Spanish if it was sent in Spanish.

**Expected**
What the policy says should happen.

**Observed**
What actually happened. Paste the agent's reply verbatim. Include tool calls if visible.

**Notes & comments**
- _[YYYY-MM-DD, Name]_: comment
```

---

## Observations

<!-- Newest at the top. Use --- between entries. -->

### 2026-05-12 — Example: agent invented a supplement category — Santiago (template, delete when first real entry lands)

- **Severity:** high
- **Status:** open
- **Category:** hallucination
- **Model / build:** haiku-4.5 (eval)
- **Channel:** eval harness
- **Conversation id / evidence:** `eval/results/20260512T120000Z/haiku-4.5.jsonl`, case `supplements_general`
- **Reproducibility:** sometimes (2 of 5 runs)

**Scenario**
Asked an open question about what supplements NutriWhite sells, to see whether the agent stays within approved framing.

**Input**
> ¿Qué suplementos venden? ¿Tienen algo para energía y vitalidad?

**Expected**
Use `faq_services` or `kb_search`. Frame supplements as coordinated by specialist / logistics interna (Venezuela) or Fullscript/Wholescripts (internacional). Should **not** name a "vitalidad" line — that category is explicitly forbidden unless KB returns it.

**Observed**
Agent answered with a "línea de vitalidad y antioxidantes" that does not exist, without calling any tool first. No `source_uri` cited.

**Notes & comments**
- _[2026-05-12, Santiago]_: This is the template entry. Delete once the first real observation is filed.

---

<!-- Add new entries above this line. -->

## Open discussion

Use this section for topics that aren't tied to one observation — broader patterns, proposed policy changes, "should we add a new tool for X?". Sign your contributions.

- _[YYYY-MM-DD, Name]_: prompt for discussion…

---

## Closed / verified

When an entry is `verified` and at least a week old, move it down here so the active log stays short. Keep the full entry body — we want the history for future regression tests.
