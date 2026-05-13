# Intent Router — Build Plan (Phase 1)

> **Audience:** an engineer (human or AI) implementing this without prior conversation context. Everything needed to execute is here. Read top-to-bottom before touching code.

## Why we're building this

The current `nw-cs-agent` is a single LLM (`claude-haiku-4-5`) doing intent classification, tool selection, parameter extraction, response generation, and style enforcement all in one forward pass per turn. Failure modes observed in production WhatsApp testing:

1. **Tool-call hallucination.** Agent emits text like `"I need to check the handoff status first. Let me do that now."` then sends the canned handoff phrase to the patient, never invoking `handoff_human` or `check_handoff_state`. State row is never written, mute never engages, team is never notified.
2. **Language leakage.** Agent emits internal-reasoning text in English to a Spanish patient.
3. **Policy fatigue.** As the policy in [SKILL.md](../openclaw/skills/customer-service-policy/SKILL.md) and [AGENTS.md](../openclaw/workspace/AGENTS.md) grows (~250 lines combined), Haiku's adherence drops.

Switching to Sonnet 4.6 would mask the symptom but not the architecture. The fix is to stop asking the LLM to be the policy enforcer. Move routing to a deterministic classifier; let the LLM dispatch and compose.

This is **Phase 1**. Phase 2 (server-side handoff pre-hook bypassing the LLM entirely for high-confidence intents) is documented at the bottom but not in scope.

## What "done" looks like

Acceptance is the union of these:

1. New `intent_vectors` table populated with 8–15 seed phrases per intent class (~20 classes, ~200 rows).
2. New endpoint `POST /v1/classify_intent` on `rag-api` returning intent + confidence + dispatch hint in <200 ms p95.
3. New tool `classify_intent` exposed by the customer-service-tools plugin.
4. Updated SKILL.md and AGENTS.md where the policy is "call `classify_intent` first, then dispatch on its output." Sections describing intent routing are replaced; style/tone/hard-rule sections remain.
5. Eval harness in `eval/` has ≥5 cases per intent class. Running `python -m eval.run_eval` against `claude-haiku-4-5` gets ≥95% correct tool selection on the eval set (vs whatever the current baseline is — capture it before changing the policy).
6. End-to-end smoke test on the droplet: sending the message `"Necesito que me recomiendes un especialista, tengo gastritis crónica"` produces (a) a `classify_intent` log line, (b) a `handoff_human` log line with `contact_phone` populated, (c) a `handoff_state` row with `status=pending`, (d) a single Spanish handoff message to the patient. No English narration, no missing tool calls.
7. Rollback plan documented and tested (revert one commit + restart).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Patient WhatsApp message arrives                             │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │  check_handoff_state   │  (unchanged — keeps mute working)
                └────────────┬───────────┘
                             │
                  active=true → stay silent
                  active=false ↓
                             │
                             ▼
                ┌────────────────────────┐
                │   classify_intent      │  NEW
                │  embed → cosine → top-K│
                └────────────┬───────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
       conf ≥ 0.80      0.55 ≤ conf < 0.80     conf < 0.55
        execute            clarify             fallback_llm
              │              │              │
              ▼              ▼              ▼
   call mandatory_next_tool  ask user      LLM uses
   with suggested_params     to clarify    its own judgment
              │              │              │
              └──────────────┼──────────────┘
                             ▼
              Agent composes Spanish reply
              using policy tone rules
              (which stay in SKILL.md)
```

Key property: the LLM never decides *which* tool to call for high-confidence intents. It just dispatches. Composition + tone stays its job.

## Intent taxonomy (final)

20 intents grouped by handler:

### FAQ — deterministic canned answer (existing `faq_*` tools)
| Intent | Maps to tool | Example seeds (es) |
|---|---|---|
| `faq_location` | `faq_location` | "donde están ubicados", "cuál es la dirección", "tienen sede" |
| `faq_services` | `faq_services` | "qué ofrecen", "qué servicios tienen", "qué venden" |
| `faq_consultation_plans` | `faq_consultation_plans` | "qué planes tienen", "cuánto cuesta el Plan 3", "precios", "qué incluye Plan 5" |
| `faq_payment_methods` | `faq_payment_methods` | "cómo pagar", "puedo pagar en cuotas", "TDC", "aceptan Zelle" |
| `faq_consultation_call` | (compose from KB) | "llamada gratis", "evaluación gratis", "15 minutos" |
| `faq_protocol_3r` | `kb_search` | "qué es el Protocolo 3R", "remover reponer recuperar" |
| `faq_supplements_general` | `kb_search` | "qué suplementos venden", "Fullscript", "cómo compro suplementos" |
| `faq_exams_general` | `kb_search` | "qué exámenes hacen", "GI MAP", "microbiota" |

### Patient-specific — needs `customer_lookup` first
| Intent | Maps to tool sequence | Example seeds |
|---|---|---|
| `patient_plan_status` | `customer_lookup` → `customer_orders` | "cuál es mi plan", "cuántas consultas me quedan" |
| `patient_appointment_status` | `customer_lookup` → `customer_consultas` | "cuándo es mi consulta", "link de mi cita" |
| `patient_exam_status` | `customer_lookup` → `customer_examenes` | "llegó mi examen", "resultados", "mi GI MAP" |

### Handoff triggers — call `handoff_human` directly
| Intent | suggested reason | Example seeds |
|---|---|---|
| `handoff_specialist_recommendation` | "specialist_recommendation" | "qué especialista me recomiendan", "cuál doctora es mejor" |
| `handoff_scheduling` | "scheduling" | "cuándo puede verme", "agendar cita", "disponibilidad" |
| `handoff_discount` | "discount_negotiation" | "tienen descuento", "promoción", "plan familiar" |
| `handoff_medical_advice` | "medical_advice" | "tengo dolor", "qué tomo para", "me duele" |
| `handoff_refund` | "refund_billing" | "reembolso", "factura", "disputa de pago" |
| `handoff_post_payment_logistics` | "logistics" | "ya pagué dónde está", "mi kit no llega" |
| `handoff_english` | "english_language" | "i need help", "do you speak english", "hello can you" |
| `handoff_distress` | "patient_distress" | (abusive/distressed seeds — keep short list) |

### Conversational — direct response, no tools
| Intent | Behavior |
|---|---|
| `greeting` | Warm greeting + ask how to help |
| `farewell` | Warm farewell |
| `acknowledgment` | No reply OR brief acknowledgment ("Quedo atenta 🩵") |
| `unknown` | Confidence too low; LLM falls back to existing rules |

## Components and file-by-file plan

### 1. Postgres migration

**File:** `sql/003_intent_vectors.sql` (new)

```sql
CREATE TABLE IF NOT EXISTS intent_vectors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_class TEXT NOT NULL,
  example_text TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'es',
  embedding VECTOR(1536),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (intent_class, example_text, language)
);

CREATE INDEX IF NOT EXISTS idx_intent_vectors_class
  ON intent_vectors (intent_class);

CREATE INDEX IF NOT EXISTS idx_intent_vectors_embedding_hnsw
  ON intent_vectors USING HNSW (embedding vector_cosine_ops);
```

Apply on the droplet with:
```bash
docker exec -i cs-agent-postgres psql -U agent -d company_agent < sql/003_intent_vectors.sql
```

### 2. Seed file

**File:** `intents/intent_seeds.yaml` (new)

Format:
```yaml
intents:
  faq_location:
    description: "Patient asks where NutriWhite is located"
    dispatch:
      tool: faq_location
      params: {}
    examples:
      - "donde están ubicados"
      - "cuál es la dirección"
      - "dónde queda la sede"
      - "en qué parte de Caracas están"
      - "ubicación"
      - "puedo ir a la sede física"
      - "tienen una oficina"
      - "donde te encuentro"

  handoff_specialist_recommendation:
    description: "Patient asks which specialist/doctor to see"
    dispatch:
      tool: handoff_human
      params:
        reason: "specialist_recommendation"
        priority: "high"
    examples:
      - "qué especialista me recomiendan"
      - "cuál doctora es mejor para mi caso"
      - "necesito que me recomienden alguien"
      - "tengo gastritis quién me atiende"
      - "qué nutricionista para problemas digestivos"
      - "a quién debería ver"
      - "cuál es la mejor especialista para mí"
      - "recomiéndame una doctora"

  # ... one block per intent in the taxonomy above
```

**Seed sourcing instructions for the build agent:** 8–15 phrases per intent. Pull from (in order of preference):

1. The 5 cases in [eval/seeds.yaml](../eval/seeds.yaml) already relevant.
2. The FAQ phrasings in [knowledge/raw/06_faq.md](../knowledge/raw/06_faq.md).
3. The hardcoded FAQ tool descriptions in [openclaw/plugins/customer-service-tools/index.js](../openclaw/plugins/customer-service-tools/index.js).
4. Natural Spanish paraphrases. Use "tú" (Caracas-friendly).

Vary surface form: word order, with/without question mark, with/without accents, capitalization variants. Embeddings handle this but vector diversity helps.

For `handoff_english`, include English phrases. For `handoff_distress`, keep it to 4-5 clear distress markers (don't reward profanity-based variants).

### 3. Intent seeder CLI

**File:** `src/company_agent/intent_seeder/__init__.py` (new, empty)
**File:** `src/company_agent/intent_seeder/main.py` (new)

CLI: `python -m company_agent.intent_seeder.main sync`

Behavior:
1. Load `intents/intent_seeds.yaml`.
2. For each example: embed via existing `EmbeddingClient` (1536-dim, `text-embedding-3-small`).
3. Upsert into `intent_vectors` (unique on `intent_class + example_text + language`).
4. Optionally: clear-and-reseed mode via `--reset`.

Mirror the patterns in [src/company_agent/ingest_worker/main.py](../src/company_agent/ingest_worker/main.py).

Config: reuse `EMBEDDING_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL` from existing env. Add a new optional `INTENT_SEEDS_PATH` (default `intents/intent_seeds.yaml`).

### 4. classify_intent endpoint

**Files to modify:**
- `src/company_agent/rag_api/schemas.py` — add request/response models
- `src/company_agent/rag_api/main.py` — add endpoint
- `src/company_agent/rag_api/intent.py` (new) — classifier logic
- `src/company_agent/rag_api/config.py` — add thresholds

**Request shape:**
```python
class ClassifyIntentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language_hint: str | None = None  # "es" or "en", default es
    top_k: int = Field(default=5, ge=1, le=20)
```

**Response shape:**
```python
class IntentMatch(BaseModel):
    intent: str
    score: float
    example: str       # the seed phrase that matched, for debugging

class IntentDispatch(BaseModel):
    tool: str | None      # e.g. "handoff_human" or None for direct
    params: dict          # suggested params, e.g. {"reason": "specialist_recommendation"}

class ClassifyIntentResponse(BaseModel):
    intent: str                       # top-1 intent class
    confidence: float                 # top-1 score [0, 1]
    decision: Literal["execute", "clarify", "fallback_llm"]
    dispatch: IntentDispatch | None   # populated when decision="execute"
    top_matches: list[IntentMatch]    # top_k for debugging / multi-intent
```

**Endpoint:**
```
POST /v1/classify_intent
Headers: X-Internal-API-Key: <key>
Body: ClassifyIntentRequest
Response: ClassifyIntentResponse
```

**Algorithm:**
1. Validate. Strip + lowercase the message (embedding model handles case but normalize for hashing).
2. Embed the message.
3. SQL: `SELECT intent_class, example_text, 1 - (embedding <=> $1::vector) AS score FROM intent_vectors WHERE language = $lang ORDER BY embedding <=> $1::vector LIMIT $top_k`
4. Compute top-1 confidence = the highest score.
5. Decision tree:
   - `confidence ≥ THRESHOLD_EXECUTE` (default 0.80): `decision = "execute"`, look up dispatch from the seed file's `dispatch` block for that intent class. Load seeds once at boot into an in-memory dict keyed on intent_class.
   - `THRESHOLD_CLARIFY ≤ confidence < THRESHOLD_EXECUTE` (0.55 ≤ x < 0.80): `decision = "clarify"`. No dispatch returned. Top matches let the agent ask a targeted clarification.
   - `confidence < THRESHOLD_CLARIFY` (default 0.55): `decision = "fallback_llm"`. No dispatch.
6. **Tie-break safety:** if top-1 and top-2 are within 0.05 of each other AND both confidence ≥ threshold_execute, downgrade to `clarify`. Prevents confidently-wrong dispatches when two intents are equally close (e.g. "qué consulta tengo" vs "qué tipos de consulta hay").

**Config additions to `RagSettings`:**
```python
intent_threshold_execute: float = 0.80
intent_threshold_clarify: float = 0.55
intent_tiebreak_margin: float = 0.05
intent_seeds_path: str = "intents/intent_seeds.yaml"
```

Load seeds once at startup; expose the dispatch table via a method on the searcher class.

### 5. Plugin tool

**File:** `openclaw/plugins/customer-service-tools/index.js` (modify)

Add a new tool BEFORE the existing FAQ tools:

```javascript
api.registerTool(
  {
    name: "classify_intent",
    description:
      "OBLIGATORIA después de check_handoff_state y antes de cualquier otra acción. " +
      "Clasifica el mensaje del paciente para decidir qué hacer. Devuelve un objeto con " +
      "{intent, confidence, decision, dispatch}. " +
      "Si decision='execute' y dispatch.tool tiene un nombre, llama EXACTAMENTE a esa tool con dispatch.params " +
      "(fusionado con los parámetros que tú conozcas del contexto, como contact_phone). " +
      "Si decision='clarify', pregunta al paciente para desambiguar (sugiere top_matches en tu pregunta). " +
      "Si decision='fallback_llm', usa tu juicio con las reglas habituales.",
    parameters: Type.Object({
      message: Type.String({ minLength: 1 }),
      language_hint: Type.Optional(Type.String()),
    }),
    async execute(_id, params) {
      const result = await postJson(ragApiUrl, internalApiKey, "/v1/classify_intent", {
        message: params.message,
        language_hint: params.language_hint ?? "es",
        top_k: 5,
      });
      return asText(result);
    },
  },
);
```

Also update `openclaw/plugins/customer-service-tools/openclaw.plugin.json` — add `"classify_intent"` to `contracts.tools`.

### 6. Policy rewrite

**File:** `openclaw/skills/customer-service-policy/SKILL.md`

Replace the "Required tool order" and "Hard handoff triggers" sections with:

```markdown
## Tool flow (every patient turn, in order)

1. `check_handoff_state(contact_phone)` — if active=true, return empty and end turn.
2. `classify_intent(message=<patient_message>)` — get the route.
3. Dispatch based on the response:
   - `decision="execute"` + `dispatch.tool="handoff_human"`: call `handoff_human` merging dispatch.params with your context (always include `contact_phone`, `patient_name` if known from `customer_lookup`, `last_message`). Then send the patient the standard handoff line.
   - `decision="execute"` + `dispatch.tool="faq_location"` (or other faq_*): call that tool, respond from its content. Cite source_uri.
   - `decision="execute"` + `dispatch.tool="customer_lookup"` (patient_*): call customer_lookup with the phone, then the matching sub-tool (customer_orders / customer_consultas / customer_examenes).
   - `decision="execute"` + `dispatch.tool=null`: intent is conversational (greeting/farewell/acknowledgment). Respond directly in tone.
   - `decision="clarify"`: ask the patient one short clarifying question, referencing the top intents you saw.
   - `decision="fallback_llm"`: use judgment based on the rest of this policy.

You do not have authority to skip step 1 or step 2.
```

Keep these sections unchanged:
- Identity, Language, Tone rules
- ⛔ Forbidden behaviors (the existing block at the top)
- What you CAN answer autonomously (informative for the LLM)
- Hard rules (never invent, never calculate, etc.)
- Team-group operations
- Response style

Delete or radically shrink:
- The big "Required tool order" with the per-message-type rules — it's now in the seed file.
- "Hard handoff triggers" — also in seeds.

**File:** `openclaw/workspace/AGENTS.md`

Mirror the same tool-flow section. Keep it shorter than SKILL.md (AGENTS.md is loaded into every turn — keep it tight).

### 7. Eval cases

**File:** `eval/intent_seeds.yaml` (new) OR extend `eval/seeds.yaml`

Add ≥5 cases per intent class with these fields per case:
```yaml
- id: handoff_specialist_recommendation_001
  category: handoff
  expected_intent: handoff_specialist_recommendation
  expected_tool: handoff_human
  sender_phone: "+584145610594"
  input: "Necesito que me recomiendes un especialista, tengo gastritis crónica"
  expected:
    - tool_called: handoff_human
    - response_contains: "asesora"
    - language: es
```

Update `eval/run_eval.py` to:
- Add a "tool-correctness" pass that hits classify_intent directly and asserts the intent matches `expected_intent`.
- Continue the existing free-form generation pass (don't remove it; it tests style).

**Tuning loop:** if an intent class scores <90% on its eval cases after seeding, add more seed phrases for that class or split it into sub-intents.

### 8. .env additions

Append to `.env.example`:
```
# Intent classifier thresholds
INTENT_THRESHOLD_EXECUTE=0.80
INTENT_THRESHOLD_CLARIFY=0.55
INTENT_TIEBREAK_MARGIN=0.05
INTENT_SEEDS_PATH=intents/intent_seeds.yaml
```

Match in `RagSettings`.

## Build order (recommended)

Do not parallelize — each step depends on the previous.

1. Migration + table.
2. Seed file with FULL taxonomy (don't ship half).
3. Intent seeder CLI; sync seeds locally; verify ~200 rows.
4. classify_intent endpoint + unit test.
5. Smoke test endpoint manually with curl against 5 known phrases per category.
6. Plugin tool.
7. SKILL.md / AGENTS.md rewrite. **Keep a backup of the old versions in `docs/archived/`** for rollback reference.
8. Eval cases. Run eval. Iterate seeds until ≥95% intent accuracy.
9. Deploy to droplet. Smoke test the failing case from the original conversation ("Necesito que me recomiendes un especialista, tengo gastritis crónica").

## Deploy commands (droplet)

```bash
cd /root/nw-agent
git pull --ff-only

# Apply new migration
docker exec -i cs-agent-postgres psql -U agent -d company_agent < sql/003_intent_vectors.sql

# Seed intent vectors (one-shot)
docker compose run --rm ingest-worker python -m company_agent.intent_seeder.main sync

# Rebuild rag-api with new endpoint
docker compose up -d --build rag-api

# Sanity check
INTERNAL_API_KEY=$(grep '^INTERNAL_API_KEY=' /root/nw-agent/.env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8081/v1/classify_intent \
  -H "X-Internal-API-Key: $INTERNAL_API_KEY" \
  -H "content-type: application/json" \
  -d '{"message":"qué planes tienen?"}' | jq .
# Expect: intent=faq_consultation_plans, decision=execute, dispatch.tool=faq_consultation_plans

# Reinstall plugin so OpenClaw sees classify_intent
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools

# Sync workspace prompt
cp /root/nw-agent/openclaw/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md

# Restart gateway
systemctl --user restart openclaw-gateway.service
sleep 10
openclaw status
```

## Rollback

If the new pipeline misbehaves in production, single commit revert restores the old behavior:

```bash
git revert <intent-router-commit-sha>
git push
# On droplet:
cd /root/nw-agent && git pull --ff-only
cp /root/nw-agent/openclaw/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md
systemctl --user restart openclaw-gateway.service
```

The new table and seeds can be left in Postgres — they're inert without the endpoint and tool.

## Open decisions — RESOLVED

1. **Confidence thresholds: defaults.** `INTENT_THRESHOLD_EXECUTE=0.80`, `INTENT_THRESHOLD_CLARIFY=0.55`, `INTENT_TIEBREAK_MARGIN=0.05`. Tune from real traffic after launch; do not over-engineer up front.
2. **Acknowledgment intent: no reply.** When the classifier returns `acknowledgment` (patient said "okay" / "gracias" / "perfecto" / "👍" with no question), Gutty does NOT reply. End the turn silently. Do NOT echo "🩵" or "Quedo atenta". Treat this like a courtesy beat — the patient is signaling end of exchange, not asking for engagement.
3. **Seeds: synthetic-only for v1.** No WhatsApp history export. Source seeds from:
   - The hardcoded Spanish FAQ strings in [openclaw/plugins/customer-service-tools/index.js](../openclaw/plugins/customer-service-tools/index.js).
   - The eval cases in [eval/seeds.yaml](../eval/seeds.yaml).
   - The voice doc [knowledge/raw/08_agent_voice.md](../knowledge/raw/08_agent_voice.md) and FAQ [knowledge/raw/06_faq.md](../knowledge/raw/06_faq.md).
   - Spanish paraphrases generated by the build agent — vary word order, accent stripping, question-mark presence, casual vs formal phrasings ("tú" preferred), short vs long forms.
   - For `handoff_english`: 4-6 English seeds.
   - For `handoff_distress`: 4-5 short distress markers, no profanity-bait seeds.

   Plan to iterate from real traffic post-launch: every misclassified message logged in production becomes a candidate new seed in a follow-up batch.

## Future — Phase 2 (out of scope here)

Once Phase 1 is stable for a week, the next step removes the LLM from the hot path entirely for high-confidence dispatches:

- An OpenClaw hook on `message:received` calls `classify_intent` directly.
- If `decision=execute` AND the intent maps to a deterministic FAQ or handoff, the hook calls the tool via crm-adapter HTTP and sends the canned response, never invoking the agent.
- The LLM is only invoked for `decision=clarify` or `fallback_llm`.

Blocked on discovering OpenClaw's `send-to-JID` plugin API (needed for the team group notification on handoff). Document that discovery when undertaken.

## What this does NOT change

- The existing `handoff_state` table, mute behavior, and team claim/resume flow stay as-is.
- The crm-adapter and Zoho integration are untouched.
- The knowledge_chunks pipeline (rag-api hybrid retrieval) is untouched. `kb_search` still exists for the long tail.
- The existing `faq_*` tools remain — classify_intent dispatches to them instead of policy prose telling the LLM to pick them.

## Reading list for the build agent

Files to read before writing code:
- [README.md](../README.md) — repo overview
- [CLAUDE.md](../CLAUDE.md) — architecture summary
- [src/company_agent/rag_api/search.py](../src/company_agent/rag_api/search.py) — embedding + cosine pattern to mirror
- [src/company_agent/ingest_worker/main.py](../src/company_agent/ingest_worker/main.py) — CLI + embedding pattern to mirror
- [src/company_agent/common/handoff_state.py](../src/company_agent/common/handoff_state.py) — Postgres-store pattern to mirror
- [openclaw/plugins/customer-service-tools/index.js](../openclaw/plugins/customer-service-tools/index.js) — current tools, the tool to add fits the same shape
- [openclaw/skills/customer-service-policy/SKILL.md](../openclaw/skills/customer-service-policy/SKILL.md) — current policy
- [eval/run_eval.py](../eval/run_eval.py) — eval harness to extend
