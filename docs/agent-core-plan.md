# Agent Core — Build Plan (Phase 2)

> **Audience:** an engineer (human or AI) implementing this without prior conversation context. Everything needed to execute is here. Read top-to-bottom before touching code.

## Why we're building this

Phase 1 (intent router) proved the classifier works: 99.1% accuracy on the intent eval set, canonical phrases scoring ≥0.98. The problem is not classification — it is LLM orchestration.

After Phase 1 was deployed, live WhatsApp testing on Sonnet 4.6 still produced zero tool calls per turn. The full gateway log for a `handoff_specialist_recommendation` message showed a single `model_call` entry, no `tool_invoke` lines, a Spanish reply composed directly from training knowledge, and no `handoff_state` row written. The failure shape:

- Model emits "Hola 😊 Entiendo lo difícil que puede ser..." without calling `check_handoff_state` or `classify_intent`.
- OR model emits "Let me check the handoff state first:" followed by the patient reply — English narration, still no tool call.
- Handoff state row is never written. Human asesora is never notified. Mute never engages.

Root cause: **LLM instruction-following is probabilistic. Tool-call policy is categorical.** Telling the model "you MUST call these tools" in a system prompt is not a contract — it is a hint. No instruction density in AGENTS.md or SKILL.md changes that.

The fix is architectural: stop using the LLM as the policy enforcer. Pull the deterministic parts of the pipeline (handoff muting, handoff triggers, direct FAQ) into a Node.js hook that runs before the LLM is ever invoked. The LLM only runs for the cases that actually require language generation.

This is **Phase 2**. Phase 1 (intent classifier) is a prerequisite and must already be deployed. The LLM is still used for kb_search composition, patient-specific data, and conversational turns (greeting, farewell, clarify, fallback_llm).

## What "done" looks like

Acceptance is the union of these:

1. `inbound_claim` hook registered in the existing `customer-service-tools` plugin. Hook is the first code that runs on every inbound WhatsApp message.
2. Active handoff muting: if `check_handoff_state` returns `active=true`, the hook returns `{ handled: true }` (no reply). The LLM is never invoked. Patient receives silence.
3. Handoff intents: for any `handoff_*` intent with `decision=execute`, the hook calls `/v1/handoff` and returns the static handoff phrase. No LLM involved.
4. Direct FAQ intents: for `faq_location`, `faq_services`, `faq_consultation_plans`, `faq_payment_methods` with `decision=execute`, the hook returns the hardcoded WhatsApp-native answer. No LLM involved.
5. Acknowledgment: `intent=acknowledgment` with `decision=execute` returns `{ handled: true }` (silent end of turn). No reply, no LLM.
6. All other intents (`faq_consultation_call`, `faq_protocol_3r`, `faq_supplements_general`, `faq_exams_general`, `patient_*`, `greeting`, `farewell`, `clarify`, `fallback_llm`) return `{ handled: false }` — LLM runs normally.
7. End-to-end smoke test: sending `"Necesito que me recomiendes un especialista, tengo gastritis crónica"` from `+584241329676` produces: (a) no LLM call in the gateway log, (b) `/v1/handoff` called, (c) `handoff_state` row with `status=pending`, (d) handoff phrase sent to patient.
8. Mute smoke test: sending a follow-up message to the same phone after the handoff produces no reply.
9. FAQ smoke test: sending `"qué planes tienen"` returns the consultation plans text directly, no LLM latency.
10. Rollback plan documented and tested (single `git revert` + plugin reinstall).

## Architecture

```
Patient WhatsApp message arrives
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  inbound_claim hook  (Node.js, customer-service-tools)  │
│                                                         │
│  isGroup?  ──yes──▶  handled: false  (LLM handles       │
│                       team group commands)               │
│  !senderId ──────▶   handled: false                     │
│     │                                                   │
│     ▼                                                   │
│  POST /v1/handoff/state/check                          │
│     active=true  ──▶  handled: true   ← SILENT MUTE    │
│     active=false ─┐                                    │
│                   ▼                                     │
│  POST /v1/classify_intent                              │
│     error/timeout ──▶ handled: false  (fail open)      │
│     decision≠execute ▶ handled: false (LLM path)       │
│     decision=execute ─┐                                │
│                       ▼                                 │
│  dispatch.tool == "handoff_human"                      │
│    ──▶ POST /v1/handoff  (fire & continue on error)    │
│    ──▶ handled: true + reply: handoff phrase           │← DETERMINISTIC HANDOFF
│                                                         │
│  intent in DIRECT_FAQ_REPLIES                          │
│    ──▶ handled: true + reply: faq text                 │← DETERMINISTIC FAQ
│                                                         │
│  intent == "acknowledgment"                            │
│    ──▶ handled: true  (no reply)                       │← SILENT ACK
│                                                         │
│  else ──▶ handled: false                               │
└──────────────────────────────┬──────────────────────────┘
                               │ handled: false
                               ▼
         ┌───────────────────────────────────────┐
         │  OpenClaw LLM agent (Sonnet 4.6)      │
         │                                       │
         │  Calls check_handoff_state (redundant │
         │  but harmless — already checked)      │
         │  Calls classify_intent (redundant)    │
         │  Composes reply for:                  │
         │    • greeting / farewell              │
         │    • faq_consultation_call            │
         │    • faq_protocol_3r                  │
         │    • faq_supplements_general          │
         │    • faq_exams_general                │
         │    • patient_plan_status              │
         │    • patient_appointment_status       │
         │    • patient_exam_status              │
         │    • clarify / fallback_llm           │
         └───────────────────────────────────────┘
```

Key property: the LLM is never invoked for handoff triggers, active-handoff muting, or direct FAQ answers. These are the three most critical and highest-frequency paths.

## Deterministic dispatch map

| Intent | Hook action | Reply |
|---|---|---|
| Active handoff (`active=true`) | `handled: true` | *(none)* |
| `handoff_specialist_recommendation` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `handoff_scheduling` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `handoff_discount` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `handoff_medical_advice` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `handoff_refund` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `handoff_post_payment_logistics` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `handoff_english` | POST `/v1/handoff` + `handled: true` | English handoff phrase |
| `handoff_distress` | POST `/v1/handoff` + `handled: true` | handoff phrase |
| `faq_location` | `handled: true` | hardcoded location text |
| `faq_services` | `handled: true` | hardcoded services text |
| `faq_consultation_plans` | `handled: true` | hardcoded plans text |
| `faq_payment_methods` | `handled: true` | hardcoded payment text |
| `acknowledgment` | `handled: true` | *(none)* |
| All others | `handled: false` | LLM runs |

## Components and file-by-file plan

### 1. `openclaw/plugins/customer-service-tools/index.js` — main change

**Two additions to this file, nothing removed:**

#### 1a. Extract FAQ answers into a shared constant

At the top of the file, before `definePluginEntry`, define `DIRECT_FAQ_REPLIES`. Pull the answer strings from the existing `faq_*` tool execute functions and reformat them as WhatsApp-native text (short paragraphs, conversational Spanish, no JSON wrapping, no `instruction` field).

The implementing agent must rewrite each answer as a standalone WhatsApp message — not a data dump. 2–4 short paragraphs, plain sentences, one clear closing line. The existing tool answer strings in `faqAnswer()` calls are the source; adapt them.

```javascript
const DIRECT_FAQ_REPLIES = {
  faq_location:
    "<WhatsApp-native location answer — 2-3 sentences, Caracas friendly>",
  faq_services:
    "<WhatsApp-native services answer — what NutriWhite offers, bulleted or short paragraphs>",
  faq_consultation_plans:
    "<WhatsApp-native plans answer — Plan 1/3/5 prices, what's included, one closing CTA>",
  faq_payment_methods:
    "<WhatsApp-native payment answer — methods, cuotas 3% commission, insurance note>",
};
```

Then update the existing `faq_*` tool execute functions to return `faqAnswer(topic, DIRECT_FAQ_REPLIES[intentKey], sourceUri)` instead of the inline string. This eliminates duplication.

#### 1b. Register `inbound_claim` hook

Add a `registerHook` call inside `register(api)`, BEFORE the `registerTool` calls (order doesn't matter functionally, but leading with the hook makes the hot path obvious):

```javascript
api.registerHook("inbound_claim", async (event) => {
  // Group messages are team commands — let LLM handle
  if (event.isGroup) return { handled: false };

  const phone = event.senderId;
  if (!phone) return { handled: false };

  // ── Step 1: Active handoff mute ──────────────────────────────────────────
  let handoffState;
  try {
    handoffState = await postJson(
      crmAdapterUrl, internalApiKey,
      "/v1/handoff/state/check", { contact_phone: phone }
    );
  } catch {
    return { handled: false }; // fail open — LLM will retry
  }
  if (handoffState.active) return { handled: true }; // silent

  // ── Step 2: Classify intent ──────────────────────────────────────────────
  let cls;
  try {
    cls = await postJson(
      ragApiUrl, internalApiKey,
      "/v1/classify_intent", {
        message: event.content,
        language_hint: "es",
        top_k: 3,
      }
    );
  } catch {
    return { handled: false }; // fail open
  }

  // Only deterministically handle high-confidence executes
  if (cls.decision !== "execute") return { handled: false };

  const { intent, dispatch } = cls;

  // ── Step 3a: Handoff triggers ────────────────────────────────────────────
  if (dispatch?.tool === "handoff_human") {
    try {
      await postJson(crmAdapterUrl, internalApiKey, "/v1/handoff", {
        contact_phone: phone,
        reason: dispatch.params?.reason ?? intent,
        priority: dispatch.params?.priority ?? "high",
        last_message: event.content,
        patient_name: event.senderName ?? null,
        conversation_id: event.conversationId ?? event.sessionKey ?? "",
      });
    } catch (err) {
      // Log but still reply — do not surface API errors to patient
      console.error("[nw-hook] /v1/handoff error:", err.message);
    }

    const phrase =
      intent === "handoff_english"
        ? "Let me connect you with a colleague who'll attend you in English 🩵"
        : "Para esto te conecto con una asesora que te dara la mejor recomendacion segun tu caso 🩵 Un momento por favor.";

    return { handled: true, reply: { text: phrase } };
  }

  // ── Step 3b: Direct FAQ ──────────────────────────────────────────────────
  const faqText = DIRECT_FAQ_REPLIES[intent];
  if (faqText) return { handled: true, reply: { text: faqText } };

  // ── Step 3c: Acknowledgment — silent end of turn ─────────────────────────
  if (intent === "acknowledgment") return { handled: true };

  // ── Step 3d: Everything else — LLM composes ─────────────────────────────
  return { handled: false };
});
```

**Exact method name to use:** verify `api.registerHook` against the type definitions at
`/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-types.d.ts`
before writing. The key type is `PluginHookInboundClaimResult = { handled: boolean; reply?: ReplyPayload }`.

The `crmAdapterUrl`, `ragApiUrl`, and `internalApiKey` variables come from the existing `pluginConfig(api)` call — they are already available in the `register` closure.

### 2. `openclaw/workspace/AGENTS.md` — minimal update

Add one sentence to the top of the "Tool flow" section noting that the hook already handles muting, handoff, and direct FAQ before the LLM sees the message. The mandatory `check_handoff_state` + `classify_intent` calls remain — they are the safety net for LLM-handled turns.

Add before the numbered list:

```markdown
> **Note:** The `inbound_claim` hook in the plugin handles handoff muting, all `handoff_*`
> intents, `faq_location/services/plans/payment`, and `acknowledgment` deterministically —
> the LLM is NOT called for those cases. The tool flow below applies only to turns the
> hook passed through (`decision≠execute` or non-deterministic intents).
```

### 3. No other files change

No new Python code. No new Docker services. No new endpoints. No SQL migrations. The crm-adapter and rag-api are called as-is over the same loopback HTTP paths.

## Build order

Do not parallelize — each step depends on the previous.

1. Read the existing `index.js` in full. Read the SDK type definitions for `registerHook` and `PluginHookInboundClaimResult`.
2. Write `DIRECT_FAQ_REPLIES` — craft each as a WhatsApp message, not a raw data string. Run the existing local tests to confirm no regressions in the tools that use the FAQ answer text.
3. Refactor the four `faq_*` execute functions to reference `DIRECT_FAQ_REPLIES[key]` instead of the inline string.
4. Write the `registerHook` call. Keep it as the first call in `register(api)`.
5. Install plugin locally and run `pytest` to confirm nothing in Python-side tests broke.
6. Commit and push.
7. Deploy to droplet (see commands below).
8. Run the three smoke tests in "What done looks like" items 7, 8, 9.

## Deploy commands (droplet)

```bash
cd /root/nw-agent
git pull --ff-only

# Reinstall plugin so OpenClaw picks up the hook registration
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools

# Sync workspace prompt
cp /root/nw-agent/openclaw/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md

# Restart gateway
systemctl --user restart openclaw-gateway.service
sleep 10
openclaw status 2>&1 | head -30
openclaw gateway probe
```

**Verify hook is registered:**

```bash
openclaw plugins list 2>&1 | grep customer-service-tools
# Should show the plugin with hooks listed, or at minimum no errors
```

**Smoke test — handoff path:**

```bash
# Send from test phone: "Necesito que me recomiendes un especialista tengo gastritis crónica"
# Then verify the state row:
INTERNAL_API_KEY=$(grep '^INTERNAL_API_KEY=' /root/nw-agent/.env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8082/v1/handoff/state/check \
  -H "X-Internal-API-Key: $INTERNAL_API_KEY" \
  -H "content-type: application/json" \
  -d '{"contact_phone":"+584241329676"}' | jq .
# Want: "active": true, "status": "pending"
```

**Verify in gateway log:**

```bash
openclaw logs --follow 2>&1 | head -30
# Want: NO model_call line for the handoff message
# Want: a log line showing the hook handled the message (or absence of model_call is the evidence)
```

## Rollback

If the hook causes errors or breaks existing behavior:

```bash
git revert <agent-core-commit-sha>
git push
# On droplet:
cd /root/nw-agent && git pull --ff-only
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools
cp /root/nw-agent/openclaw/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md
systemctl --user restart openclaw-gateway.service
```

The revert restores the previous `index.js` (no hook). OpenClaw resumes its LLM-driven path. The session for `+584241329676` may need to be deleted if it cached the hook-modified state.

## Open decisions

1. **Silence format for `{ handled: true }` with no reply.** If OpenClaw requires a `reply` field to be present for `handled: true`, use `reply: { text: "" }`. Test whether an empty string is dropped by the WhatsApp channel layer or sent as a blank message. The `ReplyPayload` type has `text?: string` (optional), so omitting it should be valid — but verify against live behavior before shipping.

2. **`conversation_id` in `/v1/handoff`.** `event.conversationId` may be `undefined` for some session configurations. The current `HandoffRequest` Pydantic model requires `conversation_id` as `str`. If the field is absent from the event, passing `""` may cause a Zoho note write failure. If this is an issue: make `conversation_id` optional in `HandoffRequest` (one-line change in `src/company_agent/crm_adapter/models.py`).

3. **Double classification for LLM-handled turns.** When the hook passes through (`handled: false`), the LLM will call `check_handoff_state` and `classify_intent` again. This is ~300 ms of redundant API calls per LLM turn. For a Phase 3 optimization, inject the classify result via an `agent_turn_prepare` hook so the LLM gets it pre-computed in context. Not in scope here.

4. **FAQ text quality.** The `DIRECT_FAQ_REPLIES` strings must be conversational WhatsApp-native Spanish — 2–4 short paragraphs, no JSON, no markdown headers. The existing `faqAnswer()` answer strings are the source of truth for facts but are not formatted as messages. The implementing agent must rewrite them.

5. **`registerHook` method name.** Verify the exact API before writing. The SDK was inspected at `/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-types.d.ts`. The registration method may be `api.registerHook`, `api.hook`, or `api.on` — check the type for `PluginAPI` or `PluginHookRegistrar`.

## Alternative: Meta WhatsApp Cloud API (if hook approach fails)

If `inbound_claim` hook registration is blocked, times out on HTTP calls, or the silence/reply mechanisms don't work as expected:

- Stand up a dedicated Python FastAPI service that receives webhooks directly from Meta Cloud API
- Service runs the full pipeline: `check_handoff_state` → `classify_intent` → deterministic dispatch → `send via Meta Graph API`
- OpenClaw is kept only for the human team group (not for patient messages)
- The patient phone number is migrated to the Meta Cloud API Business Phone Number
- Cost: Meta Cloud API is free up to 1000 conversations/month; additional cost is Meta tier pricing
- Effort: ~3 additional days (Meta Business onboarding, webhook server, phone migration, send API integration)
- Upside: complete control over the pipeline, no dependency on OpenClaw internals

The hook approach is strongly preferred — it reuses all existing infrastructure. Only escalate to the Cloud API path after a concrete failure of the hook approach.

## What this does NOT change

- `handoff_state` table, `handoff_state.create`, claim/resume flow: unchanged.
- `crm_adapter` endpoints: unchanged. No new endpoints.
- `rag_api` `/v1/classify_intent` endpoint: unchanged.
- `intents/intent_seeds.yaml` and `intent_vectors` table: unchanged.
- Zoho integration: unchanged.
- The existing 15 `registerTool` calls in `index.js`: unchanged.
- The LLM path for kb_search, patient_*, greeting, farewell, clarify, fallback_llm: unchanged — LLM still handles these exactly as before.
- SKILL.md: unchanged (the note goes in AGENTS.md only).

## Reading list for the build agent

Files to read before writing code:

- `openclaw/plugins/customer-service-tools/index.js` — existing plugin; where the hook and constants go
- `/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-types.d.ts` — `PluginHookInboundClaimResult`, `PluginHookInboundClaimContext`, hook registration API
- `/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/plugins/hook-message.types.d.ts` — `PluginHookInboundClaimEvent` (fields: `content`, `senderId`, `isGroup`, `conversationId`, `sessionKey`, `senderName`)
- `/usr/lib/node_modules/openclaw/dist/plugin-sdk/src/auto-reply/reply-payload.d.ts` — `ReplyPayload` (`text?`, `mediaUrl?`, etc.)
- `openclaw/workspace/AGENTS.md` — current workspace prompt; where to add the note
- `src/company_agent/crm_adapter/models.py` — check `conversation_id` field optionality in `HandoffRequest`
- `docs/intent-router-plan.md` — Phase 1 plan; background on the classifier this plan builds on
