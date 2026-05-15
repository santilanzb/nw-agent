# NutriWhite Brain — Architecture & Build Plan

> **Audience:** a fresh Claude Code session executing this without prior conversation context. Read top-to-bottom before writing any code. Every decision is grounded in the existing repo state, real Zoho schema, and operational lessons from Phases 1–3. Each non-boring technology choice is justified in place.
>
> **Authoring session:** Opus 4.7, planning only, 2026-05-15. No code was written in this session.
>
> **Scope:** the plan covers Phases 1–4 of the NutriWhite Brain pivot. Phase 5+ (additional task modules) is sketched but not specified.

---

## 0. TL;DR

We are pivoting **only the orchestration and transport layers** of the Gutty WhatsApp agent. The backend services that work today (Postgres + pgvector, `rag-api`, `crm-adapter`, ingest worker, intent seeder, eval harness) stay exactly as they are.

The two things we are replacing:

1. **Transport.** OpenClaw → **WAHA Core** (self-hosted WhatsApp HTTP API in Docker).
2. **Orchestration.** OpenClaw's plugin + hook pipeline → **`agent-core`**, a new FastAPI service implementing a hand-written state machine.

The three new layers we are adding on top of the existing backend:

3. **Graph layer.** Apache AGE inside the existing Postgres, holding the relational view of NutriWhite's domain (Contact ⇄ Plan ⇄ Consulta ⇄ Especialista ⇄ Examen ⇄ Condition ⇄ Supplement). Bootstrapped from Zoho.
4. **Episodic memory.** A new `patient_episodes` table plus `episode_summaries` vector index — per-patient turn log and semantic recall over older summaries.
5. **Self-learning loop.** Every turn writes to a `turn_log`. A weekly review job surfaces low-confidence + clarify + fallback turns to a queue. Reviewed items become new intent seeds and graph nodes.

Routing is **deterministic-first**. The Phase 1 classifier (99.1% on its eval set) keeps owning the high-confidence path. The LLM is invoked only when composition adds real value: patient-specific data, graph reasoning, clarify, fallback. Default composition model is **Claude Haiku 4.5** with **Sonnet 4.6** as the escalation tier for ambiguous routing and patient-aware composition.

Tasks (customer-service, future patient-follow-up, future exam-result-notification) plug into the brain through a small `TaskModule` protocol. The brain owns memory and the graph; tasks own dispatch and composition for their intent surface.

---

## 1. Architecture overview

```mermaid
graph TB
    subgraph Internet
        Patient[("Patient<br/>WhatsApp")]
        Team[("Team Group<br/>'Gutty Agent'")]
        Meta[(WhatsApp servers)]
    end

    subgraph Droplet["Ubuntu Droplet"]
        subgraph Transport["Transport · NEW"]
            WAHA["WAHA Core<br/>:3000<br/>NOWEB engine"]
        end

        subgraph Brain["NutriWhite Brain · NEW"]
            AC["agent-core<br/>:8083<br/>FastAPI · hand-written FSM"]
            TaskCS["CustomerServiceTask"]
            TaskCS -. registered .- AC
        end

        subgraph Backend["Backend · REUSED AS-IS"]
            RAG["rag-api · :8081<br/>/v1/retrieve<br/>/v1/classify_intent"]
            CRM["crm-adapter · :8082<br/>/v1/handoff/*<br/>/v1/customer/*"]
            PG[("Postgres 16<br/>+ pgvector<br/>+ Apache AGE<br/>:5432")]
            Ingest["ingest-worker<br/>(oneshot)"]
            Seeder["intent_seeder<br/>(oneshot)"]
        end

        subgraph Observability["Optional"]
            LF["Langfuse<br/>self-hosted<br/>(Phase 4)"]
        end
    end

    subgraph External
        OAI["OpenAI<br/>text-embedding-3-small"]
        Anth["Anthropic API<br/>Haiku 4.5 · Sonnet 4.6"]
        Zoho[("Zoho CRM v8")]
    end

    Patient <-->|messages| Meta
    Team <-->|messages| Meta
    Meta <-->|WhatsApp Web protocol| WAHA

    WAHA -->|webhook POST /webhooks/waha| AC
    AC -->|POST /api/sendText| WAHA

    AC -->|HTTP loopback| RAG
    AC -->|HTTP loopback| CRM
    AC -. on composition .->|LLM| Anth
    AC -->|psycopg<br/>graph + episodes + turn_log| PG

    RAG <-->|psycopg| PG
    RAG -->|embed query| OAI
    CRM <-->|psycopg| PG
    CRM <-->|OAuth + COQL| Zoho
    Ingest -->|UPSERT chunks| PG
    Seeder -->|UPSERT vectors| PG

    AC -. traces .-> LF

    classDef new fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    classDef reused fill:#e3f2fd,stroke:#1565c0
    classDef storage fill:#f3e5f5,stroke:#6a1b9a
    classDef external fill:#fff3e0,stroke:#e65100
    classDef opt fill:#fffde7,stroke:#f9a825,stroke-dasharray:5
    class WAHA,AC,TaskCS new
    class RAG,CRM,Ingest,Seeder reused
    class PG storage
    class OAI,Anth,Zoho,Patient,Team,Meta external
    class LF opt
```

### Two distinct layers

- **Brain layer** = `agent-core` + Postgres extensions (pgvector, AGE) + memory tables. Owns: classifier dispatch, graph retrieval, episodic memory recall/write, LLM composition orchestration, transport adapter, turn logging.
- **Task layer** = `TaskModule` instances registered with the brain. A task declares the intents it handles, the graph entities it reads/writes, the tools it can call, and its response composition strategy. Customer Service is the first task; patient-follow-up and exam-result-notification are sketched in §7.

### Inbound data flow (one turn)

```
1. Patient sends WhatsApp message
2. WAHA receives via WhatsApp Web protocol, POSTs webhook to agent-core
3. agent-core verifies HMAC, normalizes payload → {phone, text, isGroup, ts, sessionKey}
4. State machine runs:
   a. check_handoff_state(phone) — mute if active
   b. classify_intent(text) — get intent + decision + dispatch
   c. resolve task module (intent → TaskModule.handle)
   d. task.handle:
      - optional graph_lookup (Cypher via AGE)
      - optional episodic_memory_recall
      - either: deterministic reply (canned text or null+silence)
      - or:   LLM composition with curated context
   e. turn_log.write(...)
   f. episodic_memory.append(...)
5. agent-core POSTs reply to WAHA via /api/sendText
6. WAHA delivers to WhatsApp
```

### What is new vs reused

| Component | Status | Notes |
|---|---|---|
| WAHA Core | **NEW** | Replaces OpenClaw transport. Single Docker container. |
| agent-core | **NEW** | New FastAPI service. Owns the FSM. |
| `nw_graph` (AGE graph) | **NEW** | Lives inside the existing Postgres. |
| `patient_episodes`, `episode_summaries`, `turn_log`, `learning_queue` | **NEW** | Tables added via `sql/004_brain.sql`. |
| `TaskModule` protocol + `CustomerServiceTask` | **NEW** | Python classes in `agent-core`. |
| `rag-api` | **REUSED** | No changes. |
| `crm-adapter` | **REUSED** | No changes. |
| Postgres + pgvector | **REUSED** | Adds AGE extension and four tables. |
| `knowledge_chunks`, `intent_vectors`, `handoff_state` | **REUSED** | Unchanged. |
| `ingest-worker`, `intent_seeder` | **REUSED** | Unchanged. |
| `eval/` harness + seeds | **REUSED** | Extends with brain-level evals over time. |
| Zoho integration | **REUSED** | Reads via existing `crm-adapter` only. The brain does **not** call Zoho directly. |
| OpenClaw + customer-service-tools plugin | **DECOMMISSIONED** | After cutover. Kept as cold standby for 2 weeks. |

---

## 2. Transport replacement: WAHA

### Why WAHA (and not the alternatives)

The decision matrix:

| Option | Cost | Self-host | Group support | Reliability of long-running session | Migration friction |
|---|---|---|---|---|---|
| **Meta WhatsApp Cloud API** | Free up to ~1k convos/mo, tiered after | No (Meta) | Yes (but limited) | High — Meta manages it | High — requires Meta Business onboarding, phone migration, template approval for messaging windows |
| **Twilio WhatsApp** | $0.005/msg + Meta fees | No | Limited (no group send) | High | Medium |
| **whatsapp-web.js (direct)** | Free | Yes | Yes | Medium — Chromium drift, frequent breakage | High — we'd write a transport service ourselves |
| **Baileys (direct)** | Free | Yes | Yes | Medium-high — Go/Node lib, breaks on WhatsApp protocol updates | High — same as above |
| **WAHA Core** | Free (Plus is paid) | Yes (Docker) | Yes | Medium-high — wraps Baileys/whatsapp-web.js under a stable HTTP surface | **Low — drop-in Docker, REST API matches what we'd build anyway** |

WAHA wins on the migration-friction axis. The core insight: every alternative either binds us to a paid third party (Meta/Twilio, plus their template-approval/24-hour-window rules that don't fit a 24/7 customer-service agent), or requires us to write and maintain our own WhatsApp transport (whatsapp-web.js, Baileys). WAHA is the same thing we'd build, already built.

**Honest tradeoffs:**

- WAHA uses an **unofficial WhatsApp protocol path** (via Baileys/NOWEB or Chromium/WEBJS). Meta can ban the phone number for ToS violations. This is the same risk as whatsapp-web.js or Baileys direct — WAHA does not change the risk surface, only the implementation overhead. Mitigation: use a dedicated WhatsApp Business number (already the case for `+584123251172`), keep volume reasonable, and have a Meta Cloud API fallback documented.
- The Plus edition gates some features (media send, advanced session storage). The free Core edition supports text receive + send + groups, which is what we need. We do not plan to send media in Phase 1.
- WAHA's free Core may lag behind Plus on engine fixes. The `NOWEB` engine (no Chromium) is the recommended choice for low resource footprint and stable reconnect behavior. `WEBJS` is Chromium-based and heavier; `GOWS` is a future Go-based replacement for NOWEB.

### Docker Compose service

Append to `docker-compose.yml`:

```yaml
  waha:
    image: devlikeapro/waha:latest
    container_name: nw-waha
    restart: unless-stopped
    ports:
      - "3000:3000"           # Dashboard + REST API + Swagger
    volumes:
      - waha_sessions:/app/.sessions
      - waha_files:/tmp/whatsapp-files
    environment:
      WHATSAPP_DEFAULT_ENGINE: NOWEB
      WHATSAPP_HOOK_URL: http://agent-core:8083/webhooks/waha
      WHATSAPP_HOOK_EVENTS: "message,session.status"
      WHATSAPP_HOOK_HMAC_KEY: ${WAHA_HOOK_HMAC_KEY}
      WHATSAPP_HOOK_RETRIES_POLICY: linear
      WHATSAPP_HOOK_RETRIES_DELAY_SECONDS: 2
      WHATSAPP_HOOK_RETRIES_ATTEMPTS: 4
      WAHA_API_KEY_PLAIN: ${WAHA_API_KEY}
      WAHA_DASHBOARD_USERNAME: admin
      WAHA_DASHBOARD_PASSWORD: ${WAHA_DASHBOARD_PASSWORD}
      WHATSAPP_SWAGGER_ENABLED: "true"
      WHATSAPP_RESTART_ALL_SESSIONS: "True"
      WAHA_LOG_FORMAT: JSON
      WAHA_LOG_LEVEL: info
      TZ: America/Caracas
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3000/api/ping"]
      interval: 30s
      timeout: 5s
      retries: 3

  agent-core:
    build:
      context: .
      dockerfile: Dockerfile.python
    container_name: nw-agent-core
    restart: unless-stopped
    env_file:
      - .env
    environment:
      DATABASE_URL: ${DATABASE_URL:-postgresql://agent:agent@postgres:5432/company_agent}
      RAG_API_URL: http://rag-api:8081
      CRM_ADAPTER_URL: http://crm-adapter:8082
      WAHA_BASE_URL: http://waha:3000
      WAHA_API_KEY: ${WAHA_API_KEY}
      WAHA_HOOK_HMAC_KEY: ${WAHA_HOOK_HMAC_KEY}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}
      PORT: 8083
    command: uvicorn company_agent.agent_core.main:app --host 0.0.0.0 --port 8083
    ports:
      - "8083:8083"
    depends_on:
      postgres:
        condition: service_healthy
      rag-api:
        condition: service_started
      crm-adapter:
        condition: service_started
      waha:
        condition: service_healthy

volumes:
  postgres_data:
  waha_sessions:
  waha_files:
```

### `.env.example` additions

```bash
# WAHA
WAHA_API_KEY=<generate: openssl rand -hex 24>
WAHA_HOOK_HMAC_KEY=<generate: openssl rand -hex 32>
WAHA_DASHBOARD_PASSWORD=<set manually>

# Anthropic for agent-core compositions
ANTHROPIC_API_KEY=<existing>
ANTHROPIC_DEFAULT_MODEL=claude-haiku-4-5
ANTHROPIC_ESCALATION_MODEL=claude-sonnet-4-6

# Team push
HANDOFF_TEAM_GROUP_JID=<discovered from WAHA, e.g. 120363...@g.us>
```

### Pairing flow

WAHA pairing is done **once** via the Dashboard at `http://<droplet>:3000` (proxied behind Caddy with basic auth in production):

1. Open the dashboard, log in with `WAHA_DASHBOARD_USERNAME` / `_PASSWORD`.
2. Create a session named `default`.
3. Start the session → status flips `STOPPED → SCAN_QR`.
4. Click the camera icon → QR code rendered.
5. On the Gutty phone (`+58 412 325 1172`), open WhatsApp → Linked Devices → Link a device → scan.
6. Status flips `SCAN_QR → WORKING`. WAHA persists auth in `/app/.sessions` (Docker volume `waha_sessions`).

The session survives container restarts as long as the `waha_sessions` volume is intact. If the volume is wiped, re-pair from scratch.

### Inbound webhook flow

WAHA's `message` event payload (when `WHATSAPP_HOOK_EVENTS=message,session.status`) looks roughly like (verify against `https://waha.devlike.pro/docs/how-to/webhooks` when implementing):

```json
{
  "event": "message",
  "session": "default",
  "payload": {
    "id": "false_584145610594@c.us_3EB0...",
    "from": "584145610594@c.us",
    "fromMe": false,
    "body": "Necesito un especialista, tengo gastritis",
    "timestamp": 1747340000,
    "isGroup": false,
    "isForwarded": false,
    "type": "chat"
  }
}
```

The `from` field uses `<digits>@c.us` for DMs and `<digits>@g.us` for groups. The `agent-core` webhook handler normalizes `from` to E.164 (`+584145610594`) before calling `crm-adapter` or `rag-api`.

**HMAC verification:** WAHA signs each webhook with the `WHATSAPP_HOOK_HMAC_KEY` via an `X-Webhook-Hmac` header (SHA-512 HMAC of the raw body). `agent-core` MUST verify this on every inbound request and 401 on mismatch. Without verification, anyone with the webhook URL can inject patient messages.

### Outbound send

```python
# agent-core/transport/waha.py
async def send_text(self, to_jid: str, text: str) -> None:
    await self._http.post(
        f"{self._base_url}/api/sendText",
        json={"chatId": to_jid, "text": text, "session": "default"},
        headers={"X-Api-Key": self._api_key},
        timeout=15.0,
    )
```

Patient replies use `chatId = "<digits>@c.us"`. Team-group push uses `chatId = HANDOFF_TEAM_GROUP_JID` (a `@g.us` JID).

### Migrating the production number from OpenClaw → WAHA

WhatsApp allows **up to 5 linked devices** per phone. The migration path that avoids ambiguity:

1. Stand up WAHA in parallel with OpenClaw still running on a different droplet port. **At this stage the production number is NOT paired with WAHA.**
2. Pair a **test number** with WAHA and validate the full flow (smoke test in §10 Phase 1 acceptance).
3. On cutover day:
   - Stop OpenClaw (`systemctl --user stop openclaw-gateway.service`).
   - On the Gutty phone: WhatsApp → Linked Devices → unlink the OpenClaw session.
   - Pair the production number with WAHA via the dashboard QR.
   - Expected downtime: **5–15 minutes** during the pairing scan.
4. Keep OpenClaw on the droplet but stopped for 2 weeks as cold standby. After 2 weeks of stable WAHA operation, uninstall OpenClaw and its plugin.

**Risk:** during the 5–15 min downtime, incoming patient messages are received by the Gutty phone but not seen by any agent. WhatsApp's "Online" indicator will be off — patients sending during the window will see no read receipt. Mitigation: announce the maintenance window in the team group; pick a low-traffic time (early morning Caracas time).

There is no clean way to migrate Linked Devices state. Pairing creates a fresh session; in-flight messages are not transferred to the new device pairing. Active conversations are not broken — they continue once WAHA pairs.

---

## 3. Agent-core orchestration service

### Tech stack: FastAPI + hand-written state machine

We default to a **hand-written state machine in plain Python**, not LangGraph.

**Why not LangGraph:**

- LangGraph's value is graph-shaped workflows with branching, cycles, and parallel fan-out. Our pipeline is a near-linear FSM with one optional branch (LLM composition or not). The graph abstraction is overhead.
- LangGraph couples us to LangChain's release cadence and abstraction layer. Past experience across the team (and the broader community) is that LangChain churn is high; we want orchestration logic we can read in one file.
- Phase 1's deterministic-first posture means most turns never invoke an LLM at all. A graph framework optimized for "LLM-as-node" workflows is solving the wrong problem.
- The state machine is ~150 lines of Python and fits in one module. The cost of writing it is less than the cost of reading LangGraph's docs.

We will revisit if Phase 4 self-learning or Phase 5+ tasks introduce true graph-shaped routing (parallel fan-out across multiple task modules, retries with state transitions, etc.). Until then, plain code.

**Service layout:**

```
src/company_agent/agent_core/
  __init__.py
  main.py                   # FastAPI app: /webhooks/waha, /health, /admin/*
  config.py                 # Settings (env-based)
  fsm.py                    # Turn state machine
  transport/
    waha.py                 # WAHA send + payload normalization
    hmac.py                 # webhook signature verification
  routing/
    classifier_client.py    # thin httpx client for /v1/classify_intent
    handoff_client.py       # thin httpx client for /v1/handoff/*
  tasks/
    base.py                 # TaskModule protocol + registry
    customer_service.py     # CustomerServiceTask
  brain/
    graph.py                # AGE Cypher wrapper
    episodes.py             # Episodic memory read/write
    turn_log.py             # Turn log write
  llm/
    anthropic.py            # Anthropic SDK wrapper with tool_choice support
    composition.py          # Composition prompt assembly
  models.py                 # Pydantic models (TurnContext, Decision, TaskResult)
```

### The turn state machine

```python
# Pseudo-code — full implementation in fsm.py
async def handle_turn(event: WahaInboundMessage) -> None:
    # 0. Bail-outs
    if event.from_me:        return
    if event.is_status:      return

    phone = e164(event.from_jid)
    if event.is_group:
        await handle_group_turn(event, phone)   # team commands
        return

    # 1. Handoff mute
    state = await crm.check_handoff_state(phone)
    if state.active:
        await turn_log.write(phone, event.text, intent="muted_handoff",
                             decision="silent", reply=None)
        return  # silent

    # 2. Classify
    cls = await rag.classify_intent(event.text)

    # 3. Resolve task
    task = registry.resolve(cls.intent, cls.decision)

    # 4. Build TurnContext (this is the brain → task interface)
    ctx = await build_turn_context(phone, event, cls)
    # build_turn_context fans out:
    #   - episodes.recent(phone, n=5)       (last 5 raw turns)
    #   - episodes.semantic_recall(phone, event.text, k=3)
    #   - graph.patient_overview(phone)     (if intent is patient-specific)
    # All three are parallelized with asyncio.gather and individually circuit-broken
    # — any one of them failing returns empty results, not an error.

    # 5. Task handles
    result: TaskResult = await task.handle(ctx)

    # 6. Side effects
    if result.handoff:
        await crm.handoff(phone, **result.handoff_args)
        await transport.send_to_team(team_jid, result.team_notification_text)

    # 7. Reply
    if result.reply_text is not None:
        await transport.send(phone_jid, result.reply_text)

    # 8. Persist
    await episodes.append(phone, event, result)
    await turn_log.write(phone, event.text, cls, result)
```

### Per-turn timing budget

| Stage | Budget | Hard timeout |
|---|---|---|
| HMAC verify + normalize | 5 ms | n/a |
| check_handoff_state | 100 ms | 500 ms |
| classify_intent | 200 ms | 1000 ms |
| build_turn_context (parallel) | 300 ms | 1500 ms (gather with per-task timeouts) |
| Task handle (deterministic) | 50 ms | n/a |
| Task handle (LLM compose) | 2000 ms | 8000 ms |
| WAHA send | 200 ms | 5000 ms |
| **Total deterministic** | **~600 ms** | — |
| **Total LLM composition** | **~2800 ms** | — |

Targets are p50. Hard timeouts return a fallback path (LLM if classify_intent times out; silent + alarm if WAHA send times out).

### Retry + circuit-breaker policy

- **WAHA → agent-core webhook**: WAHA already retries with linear backoff up to 4 attempts. agent-core is idempotent by message id (de-dupe via `seen_message_ids` LRU cache, 10k entries).
- **agent-core → rag-api / crm-adapter**: 1 retry with 250 ms jitter on 5xx or network error. No retry on 4xx.
- **agent-core → Anthropic API**: 1 retry on 5xx/429 with exponential backoff (1s, 2s). Total budget 8s.
- **agent-core → WAHA send**: 2 retries with 500 ms backoff. If all fail, log loudly and write a `failed_send` row to `turn_log` for the watchdog.
- **Circuit breakers** (per downstream): open after 5 failures in 30s, half-open after 60s. Open state degrades gracefully:
  - rag-api open → return `decision=fallback_llm` with `intent=unknown`, route to LLM with full policy.
  - crm-adapter open → skip handoff state check (fail open), continue. Skip handoff writes (degrade to LLM-only response without persistence).
  - Anthropic open → respond with a static safe-mode message: *"Tengo un problema técnico, ya te conecto con una asesora 🩵"* and force a handoff write.

### LLM integration

Direct Anthropic SDK, no wrapper framework. Two model tiers:

| Tier | Model | Used for | Reasoning |
|---|---|---|---|
| Composition default | `claude-haiku-4-5` | FAQ paraphrase, greeting, farewell, patient-status composition where the intent is clear | Cheap, fast, Spanish-strong, tool-calling reliable per BFCL |
| Escalation | `claude-sonnet-4-6` | `decision=clarify`, `decision=fallback_llm`, novel reasoning over graph results | Better instruction-following on ambiguous routing |

`tool_choice` is used in two places:

1. **Clarify path:** force the model to call a `ask_clarification` tool with structured `clarifying_question` + `top_intents_offered` so we can log what was asked. Prevents the model from skipping clarification and inventing an answer.
2. **Graph-aware composition:** force the model to call `compose_from_graph` with `{include_plan, include_consultas, include_examenes}` so the composition step is auditable.

The actual `messages.create` calls live in `llm/anthropic.py` and are thin. The prompts (system + few-shot examples) live in `llm/composition.py` as Python constants — not loaded from disk per turn.

### Observability

**Minimum (Phase 1):** structured JSON logs to stdout, captured by the host's journal. Every turn emits exactly one `turn` log line with:
- `turn_id` (uuid), `phone_hash` (sha256 of phone, never the raw phone in logs), `intent`, `confidence`, `decision`, `task`, `composed_by_llm` (bool), `latency_ms`, `outcome`
- Plus a per-stage breakdown (`stage_latency_ms.{handoff_check, classify, build_context, task_handle, send}`)

Phone numbers are PII and are written to `turn_log` (the DB table) but not to stdout logs. Phone-keyed analytics happen via the DB; log search goes via `turn_id`.

**Phase 4 (recommended):** Langfuse self-hosted via Docker Compose, integrated through Anthropic's SDK callback hook. Captures full prompt + completion + tool calls per LLM-using turn. Lets us replay and diff prompts when a composition regresses. See §11 open decision.

---

## 4. Graph layer

### Why a graph layer is correct for NutriWhite specifically

Vector retrieval and `customer_lookup` answer "what does this say" and "what is this patient's plan." They cannot answer relational, multi-hop questions:

| Question | Vector? | `customer_lookup`? | Graph? |
|---|---|---|---|
| "Tell me about the GI MAP exam" | ✅ retrieves the catalog entry | ❌ | ❌ |
| "What plan does this patient have?" | ❌ | ✅ one COQL hit | ✅ |
| "Which especialistas have seen patients with gastritis in the last 90 days?" | ❌ no facts | ❌ no aggregation | ✅ traversal |
| "For this patient with hipotiroidismo, which exam would the specialist most likely order, based on prior similar patients?" | ❌ partial | ❌ no across-patient view | ✅ k-hop traversal + filter |
| "Which patients in Caracas have a Plan 3 and a pending GI MAP?" | ❌ | ❌ — would need N×M COQL calls | ✅ one query |
| "Did this patient mention a condition we don't yet have in the graph?" | ❌ | ❌ | ✅ entity-extraction + write-back |

The third and fourth examples are the ones that mature an "agent" into a "brain." A nutritionist's reasoning is graph-shaped — conditions imply tests imply specialists imply protocols imply supplements. We need the same shape on the bot side.

The graph is also the natural home for **self-learning entity growth.** When a patient says "tengo SIBO," the LLM extracts `SIBO` as a Condition node candidate. If it's new, the graph writes a `Condition {name: "SIBO", first_seen_from: <turn_id>, status: "pending_review"}` node and queues it for human review. This is how the brain grows.

### Database choice: Apache AGE in the existing Postgres

**Defaults:** Apache AGE extension installed in the same Postgres instance that already runs pgvector. Single DB, single backup, single connection pool.

**Justification of the "same DB" choice:** Postgres has not failed us — every operational pain point in Phases 1–3 was at the OpenClaw layer or above. AGE is a Postgres extension that adds Cypher and graph storage. The price is one custom Docker image (base = pgvector image, layer in AGE compiled for PG16), plus per-connection `LOAD 'age'` and `SET search_path = ag_catalog, "$user", public`.

**Tradeoffs accepted:**

- AGE on PG16 is supported but the Apache AGE docs largely target PG11–15. The build agent must verify `apache/age:PG16` exists at the moment of work; if not, build AGE from source against `pgvector/pgvector:pg16`. Either way, this is one Dockerfile, not a stack change.
- AGE's `LOAD 'age'` is per-connection. psycopg pool setup must call it on every new connection via `connect_args` / a post-connect hook. Compose-wide pool churn isn't a concern at our volume (≤10k turns/day for the foreseeable future).
- AGE and pgvector cohabit at the database level (different schemas, different operator namespaces). The build agent must run a local smoke test that creates a graph, queries with `cypher()`, queries pgvector cosine in the same connection, and confirms both work. If they collide (extremely unlikely but possible), fall back to a **separate Postgres instance** named `pg-graph` on a different port — same image, dedicated to the graph. This is the operational escape hatch.

**Rejected alternatives:**

- **Neo4j.** Industry standard for property graphs but introduces a second database, a second backup strategy, a second JDBC/driver, and JVM tuning. Not justified for a domain graph that will hold maybe 50–500 thousand nodes for years.
- **NetworkX in-process.** Fine for prototyping but doesn't persist, doesn't query across processes, doesn't survive a restart. Not viable.
- **Just denormalize into Postgres tables.** This is what `crm-adapter` already does for the four flat reads. It works for "patient's plan" — it does not work for "find me patients in Caracas with Plan 3 and a pending GI MAP" without writing increasingly baroque SQL. The graph isn't replacing those denormalized reads; it's enabling the queries SQL can't.

### Initial schema — grounded in the actual Zoho data

The schema below is derived from the live Zoho field metadata pulled during planning (modules `Contacts`, `Deals`, `Consultas`, `Examenes`, plus the lookup targets `Especialistas`, `Especialistas_Junior`, `M_dicos_Aliados`, `Atendido_por`, `Paquetes`). It is **not invented.** Field names match Zoho API names exactly so the bootstrap loader is a direct mapping.

**Nodes:**

| Node | Source module | Key fields (from Zoho) | Notes |
|---|---|---|---|
| `Contact` | Zoho `Contacts` | `id`, `First_Name`, `Last_Name`, `Phone`, `Email`, `Idioma`, `Estado_de_Paciente`, `Paciente`, `Tipo_de_Comunidad`, `Tipo_de_paciente`, `G_nero`, `Tipo_de_sangre` | Patient |
| `Plan` | Zoho `Deals` | `id`, `Deal_Name`, `Stage`, `Amount`, `Estado_del_plan`, `Vigencia_del_plan`, `Consultas_del_Plan`, `Total_Consultas_Vistas`, `Ex_menes_Pendientes`, `Formas_de_pago`, `Clasificaci_n_del_Paciente`, `Motivo_de_Cancelaci_n` | A purchased plan |
| `Consulta` | Zoho `Consultas` | `id`, `N_de_Consulta`, `Tipo_de_consulta`, `Fecha_Programada`, `Estado_de_la_Cita`, `Link_de_Conexi_n` | An appointment |
| `Examen` | Zoho `Examenes` | `id`, `Nombre_del_examen`, `Estatus_del_Proceso`, `Fecha_Env_o_Kit`, `Fecha_Resultados_Recibidos`, `Estado_Administrativo` | A lab exam instance |
| `Especialista` | Zoho `Especialistas` | `id`, `name`, modality, area of focus | NutriWhite specialist (Mariana White, Andreina White, Mercedes White, Dra. Julie Verzura, Dr. Andrés Marcano, etc.) |
| `EspecialistaJunior` | Zoho `Especialistas_Junior` | `id`, `name` | Junior specialist tier |
| `MedicoAliado` | Zoho `M_dicos_Aliados` | `id`, `name` | Allied medical doctor (referrer) |
| `Operator` | Zoho `Atendido_por` | `id`, `name`, `phone` | Logistics team member (María, etc.) |
| `Paquete` | Zoho `Paquetes` | `id`, `name`, `Amount`, `Vigencia` | Package SKU |
| `Service` | seed-only | `id`, `name` (Inmunonutrición, Nutrición general, ...) | From `knowledge/raw/01_company_overview.md` |
| `Condition` | derived | `id`, `name` (Gastritis, Colon irritable, SIBO, Hipotiroidismo, TEA, ...) | Seeded from `Motivo_de_Consulta` multi-select picklist values in Zoho + grown by self-learning |
| `Supplement` | seed-only | `id`, `name`, `category` | From `knowledge/raw/04_supplements.md` (currently sparse; expand in Phase 2 as needed) |
| `Location` | seed-only | `id`, `name` (Caracas, USA, LATAM, Europa) | From the four routing zones used in exams/supplements logistics |
| `ExamCatalog` | seed-only | `id`, `name`, `price_usd`, `country_restriction` | The 20+ exam SKUs from `knowledge/raw/03_exams_catalog.md`. Distinct from the per-patient `Examen` instance node. |

**Edges** (directed, named after the relationship's natural reading):

| Edge | From → To | Source | Cardinality |
|---|---|---|---|
| `HAS_PLAN` | Contact → Plan | `Deals.Contact_Name` | 1:n |
| `HAS_CONSULTA` | Contact → Consulta | `Consultas.Comunidad_NW` | 1:n |
| `HAS_EXAMEN` | Contact → Examen | `Examenes.Comunidad_NW` | 1:n |
| `ASSIGNED_TO` | Contact → Especialista | `Contacts.Especialista` | n:1 |
| `JUNIOR_OF` | EspecialistaJunior → Especialista | `Especialistas_Junior.Especialista` (verify field) | n:1 |
| `CONSULTA_WITH` | Consulta → Especialista | `Consultas.Especialista` | n:1 |
| `PLAN_FOR_SERVICE` | Plan → Service | derived from `Deal_Name` heuristic ("Plan 3", "Plan 5", ...) | n:1 |
| `PLAN_INCLUDES_PACKAGE` | Plan → Paquete | `Deals.Aplicar_Paquete` | n:1 |
| `EXAMEN_OF_TYPE` | Examen → ExamCatalog | `Examenes.Nombre_del_examen` (lookup → catalog) | n:1 |
| `OPERATED_BY` | Plan → Operator | `Deals.Atendido_por` | n:1 |
| `LOGISTICS_FOR` | Contact → Operator | `Contacts.Asesora_de_log_stica` | n:1 |
| `REPORTS_CONDITION` | Contact → Condition | `Contacts.Motivo_de_Consulta` (multi-select) | n:m |
| `RECOMMENDED_FOR` | ExamCatalog → Condition | seed-only — curated from `knowledge/raw/03_exams_catalog.md` indicaciones | n:m |
| `SPECIALIZES_IN` | Especialista → Condition | seed-only — from `knowledge/raw/05_specialists.md` Especialidad notes | n:m |
| `INDICATED_FOR` | Supplement → Condition | seed-only — curated | n:m |
| `LOCATED_IN` | Contact → Location | derived from `Phone` country code | n:1 |
| `REFERRED_BY` | Contact → Contact | `Contacts.Referido_Paciente` | n:1 |
| `REFERRED_BY_MEDICO` | Contact → MedicoAliado | `Contacts.Referido_Aliado` | n:1 |
| `REFERRED_BY_ESPECIALISTA` | Contact → Especialista | `Contacts.Referido_Especialista` | n:1 |

### Query interface from agent-core

We use AGE's Cypher inside Postgres. The wrapper is thin:

```python
# src/company_agent/agent_core/brain/graph.py
class GraphStore:
    GRAPH_NAME = "nw_graph"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _conn(self) -> Iterator[Connection]:
        with connect(self._database_url) as conn:
            conn.execute("LOAD 'age';")
            conn.execute('SET search_path = ag_catalog, "$user", public;')
            yield conn

    def cypher(self, query: str, params: dict, columns: list[str]) -> list[dict]:
        col_spec = ", ".join(f"{c} agtype" for c in columns)
        sql = f"SELECT * FROM cypher('{self.GRAPH_NAME}', $${query}$$, %(params)s) AS ({col_spec});"
        with self._conn() as conn:
            return list(conn.execute(sql, {"params": Jsonb(params)}).fetchall())

    def patient_overview(self, contact_id: str) -> PatientOverviewResult:
        """
        Given a Zoho contact_id, return:
          - the active Plan (or None)
          - the next scheduled Consulta (by Fecha_Programada, future-most-imminent)
          - the assigned Especialista on that Consulta
          - any Examenes with Estatus_del_Proceso != 'Completado'
        """
        rows = self.cypher(
            """
            MATCH (c:Contact {id: $cid})
            OPTIONAL MATCH (c)-[:HAS_PLAN]->(p:Plan {Estado_del_plan: 'Activo'})
            OPTIONAL MATCH (c)-[:HAS_CONSULTA]->(co:Consulta)
              WHERE co.Fecha_Programada >= date()
              AND co.Estado_de_la_Cita IN ['Programada','Confirmada']
            OPTIONAL MATCH (co)-[:CONSULTA_WITH]->(e:Especialista)
            OPTIONAL MATCH (c)-[:HAS_EXAMEN]->(ex:Examen)
              WHERE ex.Estatus_del_Proceso <> 'Completado'
            RETURN p, co, e, collect(ex) as pending_examenes
            ORDER BY co.Fecha_Programada ASC
            LIMIT 1
            """,
            {"cid": contact_id},
            columns=["p", "co", "e", "pending_examenes"],
        )
        return PatientOverviewResult.from_rows(rows)
```

The wrapper exposes named methods (`patient_overview`, `specialists_for_condition`, `examenes_recommended_for_condition`, `recent_consultas_for_specialist`, etc.). The brain calls named methods; tasks never write raw Cypher. This keeps the query surface auditable.

**A worked example for the patient-status path** (this is what `patient_appointment_status` intent resolves to):

```python
# CustomerServiceTask.handle for patient_appointment_status
overview = await ctx.graph.patient_overview(contact_id=ctx.contact_id)
if overview.next_consulta is None:
    return TaskResult.handoff(reason="no_active_consulta_scheduling_needed")
return TaskResult.llm_compose(
    template="patient_next_appointment",
    template_context={
        "consulta_date": overview.next_consulta.scheduled_date,
        "specialist_name": overview.next_consulta_specialist_name,
        "connection_link": overview.next_consulta.connection_link,
        "pending_examenes": overview.pending_examenes,
    },
    composition_model="haiku",  # this is a templated composition
)
```

### Bootstrap strategy

**One-shot bootstrap (Phase 2 Day 1):**

A new CLI: `python -m company_agent.graph_bootstrap.main sync` runs against the live Zoho. The job:

1. Pages through `Contacts` (10k rows expected, 200-row pages via COQL), upserting `Contact` nodes.
2. Pages through `Deals`, upserting `Plan` nodes and `HAS_PLAN` edges.
3. Pages through `Consultas`, upserting `Consulta` + `HAS_CONSULTA` + `CONSULTA_WITH`.
4. Pages through `Examenes`, upserting `Examen` + `HAS_EXAMEN` + `EXAMEN_OF_TYPE`.
5. Pages through `Especialistas`, `Especialistas_Junior`, `M_dicos_Aliados`, `Atendido_por`, `Paquetes` — pure node upserts.
6. Loads seed-only nodes from `knowledge/raw/` (Service, Condition, Supplement, Location, ExamCatalog) and seed-only edges from a new `graph_seeds.yaml`.
7. Computes derived edges (`LOCATED_IN` by Phone country code, `REPORTS_CONDITION` from `Motivo_de_Consulta` array per contact).

Each step is idempotent (`MERGE` instead of `CREATE` in Cypher) so re-runs are safe.

**Ongoing sync model:**

Three options were considered. Recommendation: **on-demand fetch with TTL cache, with a nightly full refresh.**

| Option | Latency | Operational complexity | Recommendation |
|---|---|---|---|
| Zoho webhooks → push to graph | seconds | High — Zoho webhook config, retry, dedupe | Defer to Phase 4 if real-time matters. Zoho webhook reliability is mixed. |
| Periodic poll (cron every 15 min) | up to 15 min | Medium — needs a delta-detection strategy | Decent baseline but writes a lot of graph traffic to detect nothing changed |
| **On-demand fetch with TTL cache, plus nightly full sync** | ~Zoho latency on first hit, instant on subsequent | Low | **Picked.** |

How on-demand works:

- When `graph.patient_overview(contact_id)` is called, the wrapper first checks node freshness — if `last_synced_at` on the `Contact` node is younger than `GRAPH_TTL_HOURS=2`, return graph state directly. Otherwise, fetch the patient's full subtree from `crm-adapter` (a new endpoint `/v1/patient/full_subtree`), upsert the graph, mark fresh, then query.
- A nightly cron at 03:00 Caracas time runs the bootstrap CLI as a full refresh. This catches Zoho changes that didn't trigger a fetch (a Deal stage change for a patient who didn't message us).

This trades freshness for simplicity and avoids the Zoho webhook integration tax. The on-demand path means an active patient always sees fresh data; a dormant patient might see day-old data, which is fine.

---

## 5. Episodic memory

### Why this layer exists

Today, every patient turn is stateless beyond the `handoff_state` row. The agent has no idea what the patient asked yesterday. This causes:

- Repeated FAQ delivery ("we already told them the address; they're asking for hours now") read as cold.
- No ability to follow up on a multi-turn thread ("on Tuesday they asked about GI MAP; today they're asking about pricing — connect those").
- No learning of patient-specific register (formal vs casual, Spanish slang, emoji-heavy or terse).

Episodic memory closes this. The brain stores per-patient turns and summaries; composition reads them; the LLM composition step is given enough recent context to feel like it remembers.

### Schema

`sql/004_brain.sql` adds:

```sql
-- Raw turn log. PII-bearing (text + phone). 90-day default retention.
CREATE TABLE IF NOT EXISTS patient_episodes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_phone TEXT NOT NULL,            -- E.164
  contact_id TEXT,                        -- Zoho Contact id when known
  direction TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
  text TEXT NOT NULL,
  intent TEXT,                            -- only on inbound turns
  confidence NUMERIC(5,4),
  decision TEXT,                          -- 'execute' | 'clarify' | 'fallback_llm' | 'muted_handoff'
  task TEXT,                              -- 'customer_service' | future tasks
  composed_by_llm BOOLEAN NOT NULL DEFAULT false,
  model_used TEXT,                        -- 'haiku' | 'sonnet' | null
  turn_id UUID NOT NULL,                  -- groups inbound+outbound of one turn
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_patient_episodes_phone_time
  ON patient_episodes (contact_phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_patient_episodes_turn
  ON patient_episodes (turn_id);

-- Rolling summary embeddings for k-NN recall over older history.
-- One row per "summary window" (~20 raw turns or 7 days, whichever first).
CREATE TABLE IF NOT EXISTS episode_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_phone TEXT NOT NULL,
  summary TEXT NOT NULL,                  -- ~400 chars, generated by haiku
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  turn_count INT NOT NULL,
  embedding VECTOR(1536),                 -- 1536-dim, same model as knowledge
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_episode_summaries_phone
  ON episode_summaries (contact_phone, window_end DESC);
CREATE INDEX IF NOT EXISTS idx_episode_summaries_embedding
  ON episode_summaries USING HNSW (embedding vector_cosine_ops);

-- Per-patient learned facts. Small key-value store.
-- "register": 'casual'|'formal', "tone_preference": 'short'|'detailed',
-- "language": 'es'|'en', "interested_in_plan": 'Plan 3', etc.
CREATE TABLE IF NOT EXISTS patient_facts (
  contact_phone TEXT NOT NULL,
  fact_key TEXT NOT NULL,
  fact_value TEXT NOT NULL,
  confidence NUMERIC(5,4) NOT NULL DEFAULT 1.0,
  learned_from_turn_id UUID,
  learned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (contact_phone, fact_key)
);
```

**PII-sensitive fields:** `patient_episodes.text`, `patient_facts.fact_value`, `episode_summaries.summary`. These are subject to the retention policy below.

### Retrieval strategy

When `build_turn_context` is called:

1. **Recent raw turns:** `SELECT * FROM patient_episodes WHERE contact_phone = $1 ORDER BY created_at DESC LIMIT 5`. Gives the LLM the immediate context (the last 2–3 exchanges).
2. **Semantic recall:** for the current inbound text, embed it (OpenAI 1536-dim) and `SELECT summary FROM episode_summaries WHERE contact_phone = $1 ORDER BY embedding <=> $2::vector LIMIT 3`. Gives the LLM relevant older context ("two weeks ago they asked about GI MAP and didn't buy") without flooding the prompt.
3. **Facts:** `SELECT fact_key, fact_value FROM patient_facts WHERE contact_phone = $1`. Tiny key-value record passed as a structured block.

Total context budget per turn: **~1200 tokens** for episodic memory. Composition stays cheap (Haiku at ~1.5k input tokens is sub-cent).

### Summary window job

A small loop in agent-core (running as an in-process asyncio task, not a separate service): every 30 minutes, scan `patient_episodes` for any `(contact_phone)` whose last summary window ended >7 days ago OR whose un-summarized turn count >20. For each, call Haiku with the raw turns and a tight Spanish prompt:

> Summarize this WhatsApp exchange in 3–4 sentences. Capture: patient's primary concern, any plan/exam they mentioned, the resolution of the thread, their tone (casual/formal), language register. Do not include phone numbers, addresses, or third-party PII.

Insert the summary into `episode_summaries`. The raw turns stay for 90 days then are deleted (see retention).

### Privacy and retention

| Data | Retention | Wipe on patient request | At-rest encryption |
|---|---|---|---|
| `patient_episodes` (raw turns) | 90 days, then hard-deleted by cron | Yes — `DELETE WHERE contact_phone = $1` | See below |
| `episode_summaries` | 365 days, then hard-deleted | Yes | See below |
| `patient_facts` | Indefinite while patient is active; cleared on request | Yes | See below |
| `turn_log` (analytics, see §6) | 365 days; phone is hashed | Yes — replace hash with `tombstone` marker | See below |

**At-rest encryption:** as long as Postgres lives on the droplet's local disk, encryption-at-rest depends on the droplet's disk encryption (DigitalOcean's standard for new volumes). When migrating to DO Managed PostgreSQL (planned per `MEMORY.md` infra notes), DO provides encryption at rest by default. No app-layer field encryption is added — overkill at this volume and would complicate vector queries. Phone numbers in stdout logs are SHA256-hashed; the DB still holds the raw phone (it has to, in order to match WhatsApp inbound).

**Patient-request wipe endpoint:**

```python
# crm-adapter or agent-core — placement TBD; recommend agent-core to keep
# brain-owned data inside the brain
POST /v1/privacy/wipe   { "contact_phone": "+58..." }
```

Wipes `patient_episodes`, `episode_summaries`, `patient_facts`, and tombstones the relevant `turn_log` rows (keeps the row for analytics but replaces text content with `<wiped>`). Does **not** touch the graph (graph stays as the operational record of the Zoho-side relationship). Logs the wipe to a separate `privacy_wipes` table for audit.

### Working memory note

`handoff_state` already exists and serves as working memory for the active-handoff gate. Nothing changes there. Episodic memory is for cross-session continuity; handoff_state is for within-active-handoff muting.

---

## 6. Self-learning loop

### What gets logged per turn

A new `turn_log` table — distinct from `patient_episodes` because it is analytics-focused, not PII-bearing in the same way (phone is hashed):

```sql
CREATE TABLE IF NOT EXISTS turn_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  turn_id UUID NOT NULL UNIQUE,
  phone_hash TEXT NOT NULL,               -- sha256(phone), not phone
  inbound_text TEXT NOT NULL,
  classified_intent TEXT,
  confidence NUMERIC(5,4),
  decision TEXT,
  dispatch_tool TEXT,
  dispatch_params JSONB,
  task TEXT,
  task_outcome TEXT,                      -- 'replied' | 'silent' | 'handoff' | 'error'
  composed_by_llm BOOLEAN NOT NULL DEFAULT false,
  model_used TEXT,
  composition_tokens_in INT,
  composition_tokens_out INT,
  latency_ms INT,
  reply_text TEXT,                        -- for review; cleared on retention
  follow_up_within_minutes INT,           -- did the patient send another msg within 30 min?
  handoff_fired BOOLEAN NOT NULL DEFAULT false,
  graph_used BOOLEAN NOT NULL DEFAULT false,
  episodic_used BOOLEAN NOT NULL DEFAULT false,
  review_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (review_status IN ('unreviewed','accepted','rejected','reseed_pending','reseed_done')),
  reviewer TEXT,
  review_notes TEXT,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_turn_log_decision_conf
  ON turn_log (decision, confidence);
CREATE INDEX IF NOT EXISTS idx_turn_log_unreviewed
  ON turn_log (review_status, created_at)
  WHERE review_status = 'unreviewed';
```

`follow_up_within_minutes` is the **implicit feedback signal:** if the patient sent another message within 30 minutes of an outbound reply, the conversation likely didn't resolve and the reply may have been wrong. Computed by a small loop that updates the prior turn when the next inbound arrives.

### The review queue

A new module `src/company_agent/learning_review/` contains:

- A weekly job (`python -m company_agent.learning_review.main run`) that:
  1. Selects all `turn_log` rows in the last 7 days with `review_status='unreviewed'` AND any of: `decision='clarify'`, `decision='fallback_llm'`, `confidence < 0.65`, `follow_up_within_minutes < 5` (patient kept asking).
  2. Buckets them by `inbound_text` similarity (k-NN over a fast embedding of `inbound_text`) so the reviewer sees clusters, not 200 unrelated rows.
  3. Writes a Markdown review file to `learning_review/queue/YYYY-WW.md` with one section per cluster: the cluster's representative text, the 5–10 raw turns, the model's reply, and three review actions:
     - **Reseed:** add these phrases to `intent_seeds.yaml` under intent `<X>`.
     - **New intent:** create a new intent class and re-run the seeder.
     - **Graph add:** extract entities (mostly Condition nodes) and queue them for the graph review queue (`learning_queue` table).

A second table holds the queue:

```sql
CREATE TABLE IF NOT EXISTS learning_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_turn_id UUID REFERENCES turn_log(turn_id),
  kind TEXT NOT NULL CHECK (kind IN ('reseed','new_intent','new_condition','new_entity','prompt_fix')),
  proposed_payload JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','approved','rejected','applied')),
  proposer TEXT,                          -- 'auto' | reviewer name
  reviewer TEXT,
  reviewed_at TIMESTAMPTZ,
  applied_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Approval gate:** `learning_queue` items are NOT auto-applied. A human approves them (initially in Markdown review files, later through a small admin page if needed). When approved, an `apply` step runs:

- `reseed` → write to `intents/intent_seeds.yaml`, re-run `python -m company_agent.intent_seeder.main sync`, then re-run the eval harness. If the eval regresses by >2%, roll back the seed addition automatically and mark the queue row `rejected`.
- `new_intent` → same plus a new dispatch rule in the task module (manual code change required).
- `new_condition` → write a `Condition {name: ..., status: 'pending_review'}` node into the graph plus a curated `RECOMMENDED_FOR` / `SPECIALIZES_IN` edge set.

See §11 open decision on whether to keep the human-approval gate or move to auto-apply after a confidence threshold is reached.

### The first three "wins" we should be able to demonstrate

By the end of Phase 4 (T+25 days from kickoff), we must be able to show all three:

1. **A net-new intent seed.** A cluster of supplement-related misclassifications (e.g., "tengo el suplemento de magnesio, cuánto debo tomar") was reseeded into `intent_seeds.yaml` under a refined `faq_supplements_general` cluster (or a new sub-intent like `patient_supplement_dosage_question`), the seeder re-ran, the eval pass-rate held or improved, and similar new questions now route deterministically without clarify.
2. **A net-new Condition node in the graph.** A patient mentioned "endometriosis" — not in our `Motivo_de_Consulta` picklist enumeration. The brain extracted it (via the Haiku entity-extraction prompt in composition), wrote a `Condition {name: 'Endometriosis', status: 'pending_review'}` node, surfaced it in the weekly queue, and a reviewer approved it with curated `SPECIALIZES_IN` edges to relevant Especialistas.
3. **A clarification pattern collapsed into deterministic dispatch.** A pattern of "no entendí mi factura" → "puedes explicarme el cobro" → "el monto que me pasaron está mal" was previously dispatching `clarify` (3 different sub-asks). After two cycles of review, the cluster is split into two new intents (`handoff_invoice_question`, `handoff_payment_dispute`) with proper dispatch, and the clarify rate for billing-shaped messages drops to ~5%.

These are concrete and measurable. The acceptance criterion for Phase 4 (§10) ties to this list.

---

## 7. Task framework

### The TaskModule protocol

```python
# src/company_agent/agent_core/tasks/base.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class TaskModule(Protocol):
    """A task module owns a set of intents and the dispatch+composition for them."""

    name: str
    handled_intents: frozenset[str]
    graph_reads: frozenset[str]   # node labels this task may read (audit-only)
    graph_writes: frozenset[str]  # node labels this task may write
    composition_tools: frozenset[str]  # Anthropic tool names this task may use

    async def handle(self, ctx: TurnContext) -> TaskResult: ...

    def healthcheck(self) -> dict: ...  # for /admin/tasks endpoint
```

`TurnContext` is built by the brain and holds:
- `phone`, `contact_id` (if known), `inbound_text`, `inbound_event_id`
- `classification: ClassifyIntentResponse`
- `recent_episodes: list[Episode]` (last 5)
- `recalled_summaries: list[EpisodeSummary]` (top-3 semantic)
- `patient_facts: dict[str, str]`
- `graph_overview: PatientOverviewResult | None` (only fetched for intents that declared they need it)
- `clients`: `RagClient`, `CrmClient`, `GraphStore`, `LLMClient`, `Transport`

`TaskResult` declares the side-effects:
- `reply_text: str | None` — outbound to patient
- `team_notification_text: str | None`
- `handoff: HandoffArgs | None`
- `facts_to_write: list[FactWrite]`
- `graph_writes: list[GraphWrite]` — must intersect with `graph_writes` declared by the task; brain enforces

### CustomerServiceTask — the first concrete module

```python
class CustomerServiceTask:
    name = "customer_service"
    handled_intents = frozenset({
        "faq_location","faq_services","faq_consultation_plans","faq_payment_methods",
        "faq_consultation_call","faq_protocol_3r","faq_supplements_general","faq_exams_general",
        "patient_plan_status","patient_appointment_status","patient_exam_status",
        "handoff_specialist_recommendation","handoff_scheduling","handoff_discount",
        "handoff_medical_advice","handoff_refund","handoff_post_payment_logistics",
        "handoff_english","handoff_distress",
        "greeting","farewell","acknowledgment","unknown",
    })
    graph_reads = frozenset({"Contact","Plan","Consulta","Examen","Especialista","Condition","ExamCatalog"})
    graph_writes = frozenset({"Condition"})  # only allowed to PROPOSE new Condition nodes
    composition_tools = frozenset({"ask_clarification","compose_from_graph","extract_condition"})
```

Each branch of `handle(ctx)` is roughly the same shape as the current `before_dispatch` hook plus the graph-aware paths. The full dispatch table mirrors the current `DIRECT_FAQ_REPLIES` + intent-router decision tree (which the build agent already understands from `docs/agent-core-plan.md`), with three additions:

- **Graph-backed `patient_*` intents** call `ctx.graph.patient_overview(ctx.contact_id)` and compose with Haiku.
- **`fallback_llm`** with `cls.intent='unknown'` triggers an entity-extraction step (Haiku, `tool_choice=extract_condition`) before composition, so unknown Condition mentions feed the graph.
- **Handoff intents** fire the `team_notification_text` to the team JID via the brain's `transport.send_to_team(jid, text)`.

### Two future tasks (interface-only sketches)

Both sketches are intentionally minimal — the point is to prove the framework holds, not to design them now.

**PatientFollowUpTask** (Phase 5+):

```python
class PatientFollowUpTask:
    name = "patient_followup"
    handled_intents = frozenset()  # not patient-initiated — runs on a schedule
    graph_reads = frozenset({"Contact","Plan","Consulta","Examen"})
    graph_writes = frozenset()
    composition_tools = frozenset({"compose_followup"})

    async def run_daily(self) -> None:
        """Find Contacts whose Plan stage is 'Closed Won' but who have no Consulta
        scheduled within 7 days. Compose a gentle scheduling nudge via Haiku.
        Push outbound through agent-core's transport."""
```

Note this task is **not** invoked by the per-turn FSM — it's a scheduled job. The framework supports both modes: `handled_intents` non-empty → reactive task; otherwise → scheduled task with a `run_daily()` / `run_hourly()` method.

**ExamResultNotificationTask** (Phase 5+):

```python
class ExamResultNotificationTask:
    name = "exam_result_notification"
    handled_intents = frozenset()
    graph_reads = frozenset({"Contact","Examen"})
    graph_writes = frozenset()
    composition_tools = frozenset({"compose_exam_ready"})

    async def react_to_zoho_change(self, examen_id: str) -> None:
        """Triggered by a Zoho webhook (Phase 5) on Examen.Estatus_del_Proceso
        flipping to 'Resultados Recibidos'. Looks up the Contact, composes a
        notification respecting the patient's last language register from
        patient_facts. Outbound through agent-core's transport. Always pairs with
        a handoff_human row so the asesora knows the conversation has been opened."""
```

Both task sketches share the same brain (graph, episodes, transport, LLM client) — no duplication of those layers.

### Routing model

Two routing surfaces:

1. **Per-turn (reactive):** brain classifies → looks up the unique task module that `handled_intents` for the top intent → calls `task.handle(ctx)`. Exactly one task per turn.
2. **Scheduled / event-driven:** scheduled tasks register a `run_*` method; the brain has a small scheduler (APScheduler in-process, or a simple `asyncio.create_task` loop with `asyncio.sleep`). Event-driven tasks (like ExamResultNotificationTask) listen on Zoho webhooks — out of scope until Phase 5.

The brain enforces the `graph_writes` and `composition_tools` declarations as capability constraints. A task that writes a `Plan` node when it only declared `Condition` writes is rejected at `TaskResult` apply time. This is the brain's policy gate.

---

## 8. What we keep (do not rewrite)

The build session **must not touch** the following files except to read them for understanding. Any change is out of scope for Phases 1–4 of the brain.

| Path | Reason it stays |
|---|---|
| `src/company_agent/rag_api/` (entire dir) | 99.1% classifier accuracy. Not the failure surface. |
| `src/company_agent/crm_adapter/` (entire dir) | Handoff lifecycle is correct. Zoho integration is correct. |
| `src/company_agent/common/` (entire dir — db, embeddings, text, auth, logging, handoff_state) | Shared primitives, all working. |
| `src/company_agent/ingest_worker/` (entire dir) | Works. |
| `src/company_agent/intent_seeder/` (entire dir) | Works. |
| `sql/001_init.sql`, `sql/002_handoff_state.sql`, `sql/003_intent_vectors.sql` | The Postgres bootstrap path. New SQL files (`004_brain.sql`, `005_graph.sql`) are additive. |
| `knowledge/raw/` (all `*.md`) | Knowledge content. Edits go through the existing `ingest-worker` flow. |
| `intents/intent_seeds.yaml` | Source of truth for classifier. Edits go through `intent_seeder`. |
| `eval/` (entire dir) | Eval harness. Extended only; not rewritten. |
| Docker images for `postgres`, `rag-api`, `crm-adapter`, `ingest-worker` | The Postgres image is the only one that needs changes — to add AGE. The Python services are untouched. |

**Reasoning:** Phases 1 and 2 proved this code is solid. Every reliability failure in the OpenClaw era was at the orchestration/transport layer, not in `rag-api`, `crm-adapter`, or the Postgres backend. The brain wraps the backend; it does not replace it. If we touch `rag-api` or `crm-adapter` for "while we're at it" reasons, we're inheriting risk we don't need to inherit.

The **OpenClaw plugin** (`openclaw/plugins/customer-service-tools/index.js`), the OpenClaw skill/workspace files (`openclaw/skills/*`, `openclaw/workspace/AGENTS.md`), and the `openclaw/hooks/nw-message-journal` are explicitly NOT carried forward into the new architecture. They are decommissioned after cutover (§9).

---

## 9. Migration / cutover plan

```mermaid
gantt
    title NutriWhite Brain — cutover sequencing
    dateFormat YYYY-MM-DD
    section WAHA
    WAHA Compose service stand-up                 :a1, 2026-05-17, 1d
    WAHA paired with test number                  :a2, after a1, 1d

    section agent-core
    agent-core skeleton + FSM                     :b1, after a1, 2d
    Customer Service task (existing classifier)   :b2, after b1, 1d
    Smoke test on test number                     :b3, after b2, 1d

    section Cutover
    Pre-cutover dry-run                           :c1, after b3, 1d
    Unpair OpenClaw, pair WAHA on prod number     :crit, c2, after c1, 1d
    Observation period 1                          :c3, after c2, 7d

    section Decom
    Stop OpenClaw service                         :d1, after c2, 1d
    Keep OpenClaw cold standby                    :d2, after d1, 14d
    Uninstall OpenClaw + plugin                   :d3, after d2, 1d
```

**Stage 1 — parallel stand-up (no production impact, ~3 days):**

- WAHA Compose service comes up on the droplet alongside running OpenClaw.
- agent-core comes up listening on `:8083`, configured to point at WAHA's webhook.
- WAHA pairs with a **separate test number** (or the developer's personal WhatsApp on a spare device). Production Gutty number is untouched.

**Stage 2 — end-to-end smoke test (~1 day):**

The smoke test must pass before cutover:

1. Test phone sends `"qué planes tienen?"` → agent-core logs a `turn` with `intent=faq_consultation_plans, decision=execute, task=customer_service, composed_by_llm=false`. Reply matches the canonical `faq_consultation_plans` text.
2. Test phone sends `"Necesito un especialista, tengo gastritis"` → `intent=handoff_specialist_recommendation, decision=execute, handoff_fired=true`. `handoff_state` row written. Team-group WhatsApp pushes a notification.
3. Test phone sends a follow-up message → `decision=silent` (mute path). No reply.
4. Operator types `@Gutty resume +...` in the team group → handoff resumes. Test phone sends another message → agent replies.
5. Test phone sends an ambiguous message that scores `decision=clarify` → Sonnet composes a clarification using the top-3 intents from the classifier.
6. Test phone sends an English message → `intent=handoff_english, decision=execute`. English handoff phrase sent.

If any of the six fails, do not proceed to Stage 3.

**Stage 3 — production cutover (~15 min downtime):**

1. Announce maintenance window in the team group.
2. `systemctl --user stop openclaw-gateway.service` on the droplet.
3. On the Gutty phone (`+58 412 325 1172`): WhatsApp → Linked Devices → unlink OpenClaw.
4. WAHA dashboard → start `default` session → scan QR with the Gutty phone.
5. Run the same six-step smoke test against the production number with one operator on standby.
6. Announce cutover complete.

**Stage 4 — observation (14 days):**

- agent-core's `turn_log` is the primary instrument. Watch for failed sends, elevated `fallback_llm` rate, missing handoff writes.
- OpenClaw remains installed but stopped on the droplet (`systemctl --user status` should show `inactive (dead)`).
- If any class of bug requires a rollback, the inverse of Stage 3 takes ~10 minutes (unpair WAHA, re-pair OpenClaw, restart gateway).

**Stage 5 — decommission (T+21):**

- Uninstall the OpenClaw plugin from the droplet (`openclaw plugins uninstall customer-service-tools`).
- Stop and disable the OpenClaw systemd unit.
- Remove the OpenClaw npm install (`rm -rf /root/.openclaw /usr/lib/node_modules/openclaw`).
- The repo's `openclaw/` directory is renamed `openclaw_archive/` and a CHANGELOG note is added. The directory is kept for one release cycle then deleted.

---

## 10. Phased timeline with acceptance criteria

All targets are working-day estimates assuming one engineer (or one focused build session per phase).

### Phase 1 — WAHA + agent-core skeleton + CS task on existing classifier — target T+3 days

**Scope:**
- WAHA Compose service running, paired with a test number.
- `agent-core` service deployed, listening on `:8083`.
- The state machine described in §3 implemented for: `handoff mute`, `classify_intent`, deterministic dispatch (FAQ, handoff, acknowledgment), and LLM fallback for the rest.
- `CustomerServiceTask` registered as the sole task.
- `turn_log` table + writing on every turn.
- Team-group push on handoff fire (the Phase 3 OpenClaw effort completed).
- WAHA → agent-core HMAC verification working.
- All smoke tests in §9 Stage 2 passing on the test number.

**Acceptance:** the test number, sent the same six messages as the §9 Stage 2 smoke test, produces identical patient-facing behavior to today's OpenClaw stack PLUS a team-group push notification — and `turn_log` has one row per turn with the correct fields populated.

### Phase 2 — Graph layer bootstrapped from Zoho, agent-core uses it for patient-status intents — target T+8 days

**Scope:**
- Custom Postgres image with AGE + pgvector. Verified cohabitation via a smoke query.
- `sql/005_graph.sql` creates the `nw_graph` AGE graph.
- `python -m company_agent.graph_bootstrap.main sync` populates the graph from Zoho via a new `crm-adapter` endpoint `/v1/patient/full_subtree` (this endpoint IS allowed — it composes the existing COQL calls; it does not change adapter logic).
- `GraphStore.patient_overview(contact_id)` works against the live graph.
- `CustomerServiceTask` uses `patient_overview` for `patient_plan_status`, `patient_appointment_status`, `patient_exam_status` instead of the current `customer_lookup → customer_orders` chain.
- Nightly graph refresh cron runs at 03:00 Caracas.
- Two graph-only queries pass an integration test: "next consulta for contact X" and "specialists who treat gastritis."

**Acceptance:** a patient sending `"cuándo es mi próxima consulta"` produces a reply composed with graph-derived `consulta_date`, `specialist_name`, and `connection_link` — verified end-to-end on a test contact with a real Zoho record.

### Phase 3 — Episodic memory layer, patient-aware composition — target T+15 days

**Scope:**
- `sql/004_brain.sql` deployed: `patient_episodes`, `episode_summaries`, `patient_facts`, `learning_queue`.
- Episode write on every turn (both inbound and outbound).
- Summary window job running (every 30 min, in-process).
- `build_turn_context` fetches recent + recalled summaries + facts and passes them into composition.
- The composition prompt for `patient_appointment_status` (and a few others) is updated to use the patient-context block. Tone is tuned via the `patient_facts.register` value.
- `/v1/privacy/wipe` endpoint live on agent-core.
- A retention cron deletes 90-day-old `patient_episodes`.

**Acceptance:** a patient who sent a message 2 weeks ago about GI MAP and is now asking about pricing receives a reply that acknowledges the prior thread ("retomando lo del GI MAP que vimos antes..."), produced by the composition step using `episode_summaries` recall — verified by inspecting the `turn_log.episodic_used = true` row and reading the LLM trace.

### Phase 4 — Self-learning loop, review queue, demonstrated wins — target T+25 days

**Scope:**
- `learning_review` module with weekly review job (`python -m company_agent.learning_review.main run`).
- `learning_queue` table populated by the job.
- Markdown review files generated to `learning_review/queue/YYYY-WW.md`.
- Apply flow (`python -m company_agent.learning_review.main apply --id <queue_id>`) implemented for `reseed`, `new_condition`. (`new_intent` and `prompt_fix` remain manual code changes — explicitly NOT automated.)
- Implicit-feedback follow-up tracking (`turn_log.follow_up_within_minutes`) running.
- Langfuse self-hosted (decision pending, §11). If we ship Langfuse, the agent-core's Anthropic calls emit traces.

**Acceptance:** at least one of each of the three concrete wins (§6) has been produced from the live production traffic, with a paper trail of `turn_log` rows → review file → `learning_queue` row → applied change → post-apply eval pass.

### Phase 5+ — additional task modules — not specified in this plan

Sketched in §7; not built in the build session this plan kicks off.

---

## 11. Open decisions for the user (these gate the build)

Each item is a real fork. The build session needs answers before kickoff.

### 11.1 Composition model in production

The plan defaults to **Haiku 4.5** for composition with **Sonnet 4.6** as escalation. The team's prior infra-stack memory called for Haiku 4.5 with Sonnet 4.6 fallback (matches). Confirm — or pick differently:

- **Option A (recommended):** Haiku 4.5 default; Sonnet 4.6 for clarify and fallback_llm. Cost: ~$0.10 per 1k turns of all-Haiku, ~$0.40/1k mixed.
- **Option B:** Sonnet 4.6 across the board. Higher cost; better instruction-following on edge cases.
- **Option C:** Sonnet 4.6 for everything until we have eval evidence Haiku is good enough for patient-aware composition.

### 11.2 Where to host WAHA's session and engine

- **Option A (recommended):** same droplet as the rest of the stack. NOWEB engine keeps RAM usage low (<300 MB). Single failure domain we already accept.
- **Option B:** separate droplet for WAHA. Insulates WhatsApp transport from agent-core crashes. Cost: one more droplet (~$12/mo) plus VPC routing.

Engine choice within WAHA: NOWEB recommended (lighter, no Chromium). WEBJS is the fallback if NOWEB has feature gaps we hit.

### 11.3 Langfuse now or later

- **Option A (recommended):** ship Langfuse self-hosted in Phase 4 only. Phases 1–3 use stdout JSON logs and `turn_log` for analytics. Avoids one moving part during the cutover-sensitive period.
- **Option B:** ship Langfuse in Phase 1 alongside agent-core. Better observability from day one; one more service to keep running during cutover.

### 11.4 Episodic memory retention windows

Plan defaults are 90 days for raw turns, 365 days for summaries, indefinite for facts. Confirm or set differently. Venezuelan privacy law (LOPDP) does not currently mandate a retention max for this kind of data, but a published policy is good hygiene. Pick the limits we'll publish to patients.

### 11.5 Self-learning ingestion gate

- **Option A (recommended):** human-approval gate via the Markdown review queue. Reseed/new-condition items are queued and require a `learning_review apply --approve` invocation.
- **Option B:** auto-apply with rollback. Once a reseed cluster has ≥10 similar misclassifications and confidence is high, the seed is added automatically and the eval re-runs. If the eval regresses, the seed is rolled back.

Option B is "real" self-learning but riskier in the first months when reviewers are still calibrating.

### 11.6 Where to put graph storage if AGE+pgvector cohabit poorly

- **Option A (recommended):** same Postgres, custom image (`pgvector + AGE`). Confirmed during Phase 2 Day 1 by a smoke test.
- **Option B:** separate Postgres container (`pg-graph`) on the same droplet. Same Docker image, dedicated to the graph. Defensive choice if the cohabitation smoke test fails.

The build agent picks B if and only if the cohabitation test fails. The user should pre-authorize the fork so the build session doesn't stall.

### 11.7 Webhook from Zoho for ExamResultNotificationTask (Phase 5)

This is a Phase 5+ task and out of scope for the build session this plan kicks off — listing it here only so the user is aware that introducing it later means standing up a Zoho webhook receiver. Not a Phase 1–4 decision.

---

## 12. Reading list for the build agent

Inside the repo (in this order):

1. [CLAUDE.md](../CLAUDE.md) — repo overview
2. [docs/architecture-diagrams.md](architecture-diagrams.md) — current state + reliability scorecard
3. [docs/intent-router-plan.md](intent-router-plan.md) — Phase 1 classifier plan (shipped)
4. [docs/agent-core-plan.md](agent-core-plan.md) — Phase 2 hook architecture (orientation, not blueprint)
5. [docs/hook-fix-before-dispatch-plan.md](hook-fix-before-dispatch-plan.md) — for context on why we are leaving OpenClaw
6. [docs/phase-3-team-push-plan.md](phase-3-team-push-plan.md) — for the team-push pattern that agent-core inherits
7. **[docs/nutriwhite-brain-plan.md](nutriwhite-brain-plan.md)** — this document

Backend code the brain wraps (read-only):

- [src/company_agent/rag_api/main.py](../src/company_agent/rag_api/main.py)
- [src/company_agent/rag_api/intent.py](../src/company_agent/rag_api/intent.py) — classifier internals
- [src/company_agent/rag_api/search.py](../src/company_agent/rag_api/search.py) — RRF fusion
- [src/company_agent/crm_adapter/main.py](../src/company_agent/crm_adapter/main.py)
- [src/company_agent/crm_adapter/adapters.py](../src/company_agent/crm_adapter/adapters.py) — MockCrmAdapter and ZohoCrmAdapter
- [src/company_agent/crm_adapter/zoho_client.py](../src/company_agent/crm_adapter/zoho_client.py) — COQL queries to mirror in the graph bootstrap
- [src/company_agent/crm_adapter/models.py](../src/company_agent/crm_adapter/models.py)
- [src/company_agent/common/handoff_state.py](../src/company_agent/common/handoff_state.py)
- [src/company_agent/common/db.py](../src/company_agent/common/db.py), [embeddings.py](../src/company_agent/common/embeddings.py) — primitives to reuse in agent-core

Knowledge content (for entity seeding):

- [knowledge/raw/01_company_overview.md](../knowledge/raw/01_company_overview.md)
- [knowledge/raw/02_consultation_plans.md](../knowledge/raw/02_consultation_plans.md)
- [knowledge/raw/03_exams_catalog.md](../knowledge/raw/03_exams_catalog.md)
- [knowledge/raw/04_supplements.md](../knowledge/raw/04_supplements.md)
- [knowledge/raw/05_specialists.md](../knowledge/raw/05_specialists.md)
- [knowledge/raw/06_faq.md](../knowledge/raw/06_faq.md)
- [knowledge/raw/07_contact_channels.md](../knowledge/raw/07_contact_channels.md)
- [knowledge/raw/08_agent_voice.md](../knowledge/raw/08_agent_voice.md)

Schema:

- [sql/001_init.sql](../sql/001_init.sql)
- [sql/002_handoff_state.sql](../sql/002_handoff_state.sql)
- [sql/003_intent_vectors.sql](../sql/003_intent_vectors.sql)

Intent and eval:

- [intents/intent_seeds.yaml](../intents/intent_seeds.yaml)
- [eval/seeds.yaml](../eval/seeds.yaml)
- [eval/intent_eval.yaml](../eval/intent_eval.yaml)
- [eval/run_eval.py](../eval/run_eval.py)

External docs:

- **WAHA:** https://waha.devlike.pro/docs/overview/quick-start/, https://waha.devlike.pro/docs/how-to/config/, https://waha.devlike.pro/docs/how-to/webhooks, https://waha.devlike.pro/docs/how-to/engines/
- **Apache AGE:** https://age.apache.org/age-manual/master/intro/setup.html, https://age.apache.org/age-manual/master/clauses/clauses.html
- **pgvector + AGE cohabitation:** there is no canonical doc. The build agent must confirm via a local smoke query: `CREATE EXTENSION vector;`, `CREATE EXTENSION age;`, then run a `cypher()` query and a `<=>` cosine query in the same connection. If they collide, fall back to two Postgres instances per §11.6.
- **Anthropic SDK Python:** https://github.com/anthropics/anthropic-sdk-python (for `tool_choice` + tool use)
- **WhatsApp JID format:** `<digits>@c.us` (DM), `<digits>@g.us` (group). E.164 normalization happens at the agent-core boundary.

Zoho field schema (for the graph bootstrap) — already confirmed during planning:

- Modules: `Contacts`, `Deals`, `Consultas`, `Examenes`, `Especialistas`, `Especialistas_Junior`, `M_dicos_Aliados`, `Atendido_por`, `Paquetes`.
- Lookups: `Deals.Contact_Name → Contacts`, `Consultas.Comunidad_NW → Contacts`, `Examenes.Comunidad_NW → Contacts`, `Contacts.Especialista → Especialistas`, `Deals.Especialista → Especialistas`, `Contacts.Asesora_de_log_stica → Atendido_por`, `Deals.Atendido_por → Atendido_por`, `Contacts.Referido_Paciente → Contacts`, `Contacts.Referido_Especialista → Especialistas`, `Contacts.Referido_Aliado → M_dicos_Aliados`, `Deals.Aplicar_Paquete → Paquetes`.
- Picklists relevant to the graph: `Contacts.Motivo_de_Consulta` (multi-select), `Contacts.Estado_de_Paciente`, `Contacts.Tipo_de_Comunidad`, `Deals.Estado_del_plan`, `Deals.Vigencia_del_plan`, `Consultas.Estado_de_la_Cita`, `Examenes.Estatus_del_Proceso`.

---

## 13. Anti-scope (what this plan does NOT include)

Explicit list. The build session should reject any expansion request that lands here without a separate plan:

- **Voice channel** (WhatsApp voice notes, IVR, transcription). Out of scope.
- **Multi-tenant clinic support.** The brain is single-tenant (NutriWhite only). No org-id namespacing.
- **Spanish ↔ English bidirectional translation.** English is a handoff trigger. We will not auto-translate.
- **Model fine-tuning.** Self-learning grows the seed set and graph; it does not fine-tune Anthropic models. Anthropic does not offer fine-tuning on Claude as of 2026-01.
- **Rewriting `rag-api`, `crm-adapter`, or the Postgres bootstrap schema.** Backend is reused as-is.
- **Replacing Postgres with another DB.** Postgres has not failed us.
- **Replacing OpenAI embeddings with a self-hosted model.** Existing `text-embedding-3-small` is cheap and adequate.
- **A web admin UI.** Review queue is Markdown files for Phases 1–4. A UI is Phase 5+ if needed.
- **Mobile app, customer portal, or anything beyond the WhatsApp transport.**
- **Patient self-service appointment booking.** That's the `handoff_scheduling` intent today; it stays as a human handoff in Phase 1–4.
- **Sales pipeline automation.** Deals stay in Zoho; the brain reads, never writes Deal records.
- **Direct Zoho writes from agent-core.** All Zoho writes go through `crm-adapter` (which today only writes Notes, by design).
- **Replacing WAHA with Meta Cloud API.** Documented as a fallback in §2 but explicitly not built in Phases 1–4.
- **Multi-language Spanish-region variants.** "tú" register (Caracas/LATAM-friendly) is the only mode.
- **Auto-applying `new_intent` learning queue items.** Always a code change. Self-learning auto-applies reseeds and graph entity proposals only.
- **Calendar integration** (Google Calendar, Acuity, etc.) for the free 15-min call. The link in `knowledge/raw/07_contact_channels.md` stays as-is.

---

## Final note for the build agent

This plan is dense on purpose. Read §0 first to get the shape, then §3 (agent-core) and §4 (graph) for the meat. The other sections fill in detail when you hit them in the timeline.

If you find a section underspecified mid-build, stop and ask the user rather than guess. The fork points are §11. Anything outside §11 should be specified enough; if it isn't, that's a planning bug, not a license to invent.

Do not commit anything in Phase 1 until the test-number smoke test in §9 Stage 2 passes. The cutover is the bet-the-bot moment and skipping the smoke test makes the rollback path harder than it needs to be.
