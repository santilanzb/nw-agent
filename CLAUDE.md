# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A production-safe scaffold for **NutriWhite's WhatsApp customer service agent** ("Gutty"). The stack is in active transition:

- **Pre-cutover (current):** agent runtime is **OpenClaw** (systemd + Node 24 on the Ubuntu host). The backend services (`rag-api`, `crm-adapter`, Postgres) are live and unchanged.
- **Post-cutover (imminent):** transport moves to **WAHA** (Docker) and orchestration moves to **agent-core** (FastAPI + hand-written FSM, port 8083). Both are already deployed on the droplet running alongside OpenClaw. Cutover is Stage 3 of §9 in `docs/nutriwhite-brain-plan.md`.

The design intentionally keeps company knowledge, customer state, and tool policy in three separable services so each can be hardened independently.

## Common commands

```bash
# Local stack (Postgres + RAG API + CRM adapter)
docker compose up --build postgres rag-api crm-adapter

# Full Brain stack (all services including WAHA, agent-core, Langfuse)
docker compose up -d

# Ingest knowledge from knowledge/raw/ into Postgres (one-shot)
docker compose run --rm ingest-worker python -m company_agent.ingest_worker.main sync

# Seed intent vectors from intents/intent_seeds.yaml into Postgres (one-shot; --reset for full re-seed)
docker compose run --rm ingest-worker python -m company_agent.intent_seeder.main sync

# Tests (pytest, src/ on pythonpath via pyproject.toml)
pip install -e ".[dev]"
pytest
pytest tests/test_search.py::test_reciprocal_rank_fuse_merges_rankings

# Lint
ruff check .

# Model eval harness (compares Haiku 4.5 / Sonnet 4.6 / GPT-5 / Gemini 3 against NutriWhite cases)
pip install -e ".[eval]"
python -m eval.run_eval --models haiku-4.5
python -m eval.run_eval --models haiku-4.5,gemini-3-flash,gpt-5-mini
python -m eval.run_eval --mode intent          # tool-correctness: hits rag-api /v1/classify_intent, asserts expected_intent

# Smoke tests (read .env from project root automatically)
python scripts/zoho_smoke_test.py          # verifies Zoho OAuth + COQL against sandbox
python scripts/model_smoke_test.py         # sends "Hola" to each model
python scripts/openclaw_pending_messages.py   # scans the message journal for unanswered WhatsApp messages
python scripts/smoke_test_phase1.py        # Phase 1 Brain smoke test — 6 turns against agent-core webhook
```

## Architecture: the three-service split

OpenClaw is the agent runtime, **not** a business backend. The agent reaches business systems only through narrow HTTP tools defined in [openclaw/plugins/customer-service-tools/index.js](openclaw/plugins/customer-service-tools/index.js). Those tools call two FastAPI services:

- **[rag-api](src/company_agent/rag_api/)** (port 8081) — hybrid retrieval over `knowledge_chunks` in Postgres. Combines lexical (Postgres `tsvector` + `websearch_to_tsquery`) and semantic (`pgvector` cosine) results via **reciprocal-rank fusion** (`rrf_k=60`) in [search.py:79](src/company_agent/rag_api/search.py:79). Semantic retrieval is gated on `EMBEDDING_PROVIDER=openai`; lexical works without an API key.
- **[crm-adapter](src/company_agent/crm_adapter/)** (port 8082) — `MockCrmAdapter` for local dev, `ZohoCrmAdapter` for prod. Switched by `CRM_PROVIDER` env var in [main.py:_build_adapter](src/company_agent/crm_adapter/main.py). Both implement the same `BaseCrmAdapter` interface.
- **[ingest-worker](src/company_agent/ingest_worker/)** — one-shot CLI (not a long-running service). Walks `knowledge/raw/`, chunks via [chunk_markdown](src/company_agent/common/text.py) (1200-char chunks, 180-char overlap), embeds (OpenAI 1536-dim), upserts on `source_uri`. Deletes and re-inserts chunks per document on each sync.

Both API services require the shared `INTERNAL_API_KEY` via `X-Internal-API-Key` header — enforced by [require_internal_api_key](src/company_agent/common/auth.py). The OpenClaw plugin sets this header on every call. The plugin also **rejects non-loopback URLs** ([index.js:localHttpBaseUrl](openclaw/plugins/customer-service-tools/index.js)) — services are expected to be reachable only over `127.0.0.1` on the OpenClaw host.

## Two retrieval paths: deterministic FAQ vs `kb_search`

The plugin exposes both kinds of "knowledge" tools:

- **`kb_search`** — calls `rag-api` for hybrid retrieval. Used for anything off the common path.
- **`faq_location` / `faq_services` / `faq_consultation_plans` / `faq_payment_methods`** — return **hardcoded** Spanish answers inline from [index.js](openclaw/plugins/customer-service-tools/index.js). No retrieval, no LLM round-trip. These exist because they're the highest-frequency questions and we want zero latency / zero hallucination risk on prices and plan details.

If you edit FAQ wording, edit the strings in `index.js` directly — they are not sourced from `knowledge/raw/` at runtime. The agent skill ([openclaw/skills/customer-service-policy/SKILL.md](openclaw/skills/customer-service-policy/SKILL.md)) tells the model which path to prefer for which question shape.

## The intent classifier (the routing brain)

Both runtimes (OpenClaw and agent-core) route every patient turn through a single classifier before doing anything else. This is the deterministic spine — neither the LLM nor the FSM is allowed to skip it (`SKILL.md` / `AGENTS.md` make `classify_intent` mandatory after the handoff-state check).

The pipeline:

1. **`intents/intent_seeds.yaml`** — source of truth. ~10 Spanish example phrases per `intent_class`, each with a `dispatch.tool` (the first tool to call for that intent; `null` for conversational intents) and `dispatch.params`. Edit wording here, not in the DB.
2. **[intent_seeder](src/company_agent/intent_seeder/main.py)** — one-shot CLI (like ingest-worker). Embeds each example (OpenAI 1536-dim) and upserts into the `intent_vectors` table on `(intent_class, example_text, language)`. All seeds go into the `es` bucket. Re-run after editing the YAML; use `--reset` for a full wipe-and-reseed.
3. **rag-api `/v1/classify_intent`** ([intent.py](src/company_agent/rag_api/intent.py)) — embeds the inbound message, does cosine-NN against `intent_vectors`, and returns `intent` + `confidence` + a `decision` of `execute` / `clarify` / `fallback_llm`. Thresholds (`intent_threshold_execute`, `intent_threshold_clarify`, `intent_tiebreak_margin`) come from `RagSettings`/`.env`. Tie-break logic downgrades `execute`→`clarify` when the top-2 intents are within the margin. If embeddings are disabled, it always returns `fallback_llm` (so lexical-only deployments degrade to the LLM, not a crash).
4. **Consumers:** the OpenClaw plugin's `classify_intent` tool ([index.js](openclaw/plugins/customer-service-tools/index.js)) and agent-core's [classifier_client.py](src/company_agent/agent_core/routing/classifier_client.py) both POST to the same endpoint. agent-core's client retries once before raising; on failure the FSM falls through to the LLM.

The `dispatch` table in the response is loaded from the same `intent_seeds.yaml` at rag-api startup — so the YAML drives both *which intent matches* (via the embedded examples) and *what to do about it* (via `dispatch`).

## Zoho CRM module mapping

The Zoho adapter ([zoho_client.py](src/company_agent/crm_adapter/zoho_client.py)) maps NutriWhite-specific Zoho modules:

- `Contacts` → `CustomerProfile` (lookup by phone/id/email; phone uses **last-9-digits LIKE match** because WhatsApp E.164 and Zoho's stored format diverge — see `phone_search_suffix`)
- `Deals` (Tratos) → `DealRecord`, joined on `Contact_Name`
- `Consultas` (custom module) → `ConsultaRecord`, joined on `Comunidad_NW`
- `Examenes` (custom module) → `ExamenRecord`, joined on `Comunidad_NW`
- `Notes` on a Contact = the **handoff/ticket-draft signal**. There is no separate ticketing module; a human asesora picks up the conversation by seeing a new Note in the CRM.

Reads use **COQL** (`/crm/v8/coql`). Writes (Notes only) use REST. Token refresh is cached in [ZohoTokenManager](src/company_agent/crm_adapter/zoho_client.py) and retries once on 401.

## Agent policy lives in two places (both read by OpenClaw)

- [openclaw/skills/customer-service-policy/SKILL.md](openclaw/skills/customer-service-policy/SKILL.md) — full Gutty persona, hard handoff triggers, retrieval query guidance.
- [openclaw/workspace/AGENTS.md](openclaw/workspace/AGENTS.md) — workspace-level system prompt (shorter, runtime-loaded).

When changing agent behavior, update both — they reinforce each other but are loaded in different OpenClaw contexts. Tool descriptions in [openclaw/plugins/customer-service-tools/index.js](openclaw/plugins/customer-service-tools/index.js) are also part of the policy surface (the model uses descriptions to decide when to call a tool); they're written in Spanish on purpose.

## Postgres schema: Alembic is authoritative, `sql/` is the frozen baseline

**Schema changes are Alembic migrations. Do not edit `sql/*.sql`** — those files are frozen at
revision `0001` and survive only because `docker-entrypoint-initdb.d/` still uses them to bootstrap
a fresh local database.

```bash
export DATABASE_URL=postgresql://agent:agent@localhost:5432/company_agent
alembic upgrade head          # apply; idempotent, safe over an initdb-built database
alembic upgrade head --sql    # render the DDL for review before touching prod
alembic current               # what this database is at
alembic stamp 0001            # existing droplet DB: adopt the baseline without re-running it
```

`alembic/env.py` reads `DATABASE_URL` from the environment (never from `alembic.ini`) and rewrites
`postgresql://` to `postgresql+psycopg://`, since the runtime uses psycopg 3 and psycopg2 is not
installed. There are no ORM models — migrations are raw SQL via `op.execute`, so
`--autogenerate` does not work here.

Both bootstrap paths converge on the same schema, verified 2026-08-11: initdb-then-`upgrade head`
and `upgrade head` on an empty database both yield 16 tables. `0001` is idempotent (`IF NOT
EXISTS` throughout); `0002` round-trips through `downgrade`.

Revisions: `0001` baseline (freezes `000`–`004`) · `0002` Stage 0 substrate (`intake_events`,
`send_intents`, `identity_registry`, `approval_requests`, `crm_write_log`, `consent_events`; adds
`conversation_class` to `turn_log`, temporal validity to `patient_facts`, and a `visibility` flag
on the knowledge tables).

Two schema details that bite: the chunk's `search_tsv` is `GENERATED ALWAYS AS` — do not insert
into it, and changing its tsconfig rebuilds the column. `patient_facts` is now append-only: a
changed fact means setting `valid_to` on the old row and inserting a new one, guarded by the
partial unique index `uq_patient_facts_current`. Indexes: GIN on `search_tsv`, HNSW (cosine) on
the 1536-dim `embedding`.

`scripts/apply_brain_sql.sh` is superseded by `alembic upgrade head`.

## NutriWhite Brain (agent-core) — deployed, pre-cutover

The Brain is the replacement for OpenClaw orchestration. All services are deployed and running on the droplet (`165.227.73.90`). Full design in `docs/nutriwhite-brain-plan.md`.

### New services (all in docker-compose.yml)

| Service | Container | Port | Notes |
|---|---|---|---|
| `waha` | `nw-waha` | 3000 | WhatsApp transport. NOWEB engine. Healthcheck uses `GET /api/sessions`. |
| `agent-core` | `nw-agent-core` | 8083 | FastAPI FSM. `/webhooks/waha`, `/health`, `/admin/*`. |
| `langfuse` | `nw-langfuse` | 3001 | Self-hosted traces. Dashboard: `http://165.227.73.90:3001`. |

### agent-core layout

```
src/company_agent/agent_core/
  main.py           # FastAPI: verify → normalize → inbox.record → ACK → spawn turn; sweeper task
  config.py         # AgentCoreSettings (all from .env)
  fsm.py            # TurnFSM: mute → media gate → classify → task → side-effects → outbox
                    #   turn_id_for(event) — deterministic turn ids, see below
  models.py         # TurnContext, TaskResult, ClassificationResult, HandoffArgs
  transport/
    base.py         # Transport Protocol + InboundEvent/InboundMedia + MessageClass
    waha.py         # WahaTransport: verify/normalize/address_for/send_text
    hmac_verify.py  # verify_waha_hmac() — SHA-512
  ingress/
    inbox.py        # InboxWriter: record (dedup), mark_*, claim_stale (FOR UPDATE SKIP LOCKED)
  outbox/
    sender.py       # SendOutbox: row before transport call, per-class in-doubt policy
  routing/
    classifier_client.py  # POST /v1/classify_intent → ClassificationResult
    handoff_client.py     # check_active (raises — see below), create_handoff, resume, claim
  tasks/
    base.py               # TaskModule Protocol + explicit-claim TaskRegistry
    customer_service.py   # deterministic FAQ, handoff, LLM fallback
    fallback.py           # unclaimed intents → loud log + human escalation
  brain/
    turn_log.py           # TurnLogWriter (phone SHA-256 hashed)
  llm/
    anthropic.py          # LLMClient with Langfuse tracing (trace_id = turn_id)
    composition.py        # Spanish system prompts + prompt builders
```

### The durability rules — these are load-bearing, don't undo them

- **Nothing is ACKed that is not durable.** The webhook verifies, normalizes,
  inserts into `intake_events`, and only then returns 200. `(source, source_event_id)`
  makes redelivery a no-op. The old in-memory `_SEEN` cache is gone; it was
  per-process and lost on restart.
- **Turn ids are deterministic**: `turn_id_for(event) = uuid5(NAMESPACE_URL, "nw-agent:turn:{source}:{id}")`.
  A random id per attempt would give a re-driven event a fresh `turn_log` row *and* a
  fresh send idempotency key, so the sweeper would answer the patient twice. Send keys
  are likewise derived from the inbound event, never from the clock.
- **Sends go through the outbox**, never straight to a transport. `message_class`
  decides in-doubt behaviour: `reply`/`utility`/`team` may be re-sent once; `marketing`
  is **never** blind re-sent (Meta bills it, the patient sees it twice, it counts
  against the per-user cap) — it degrades to a human task.
- **`handoff_client.check_active` raises on failure and must stay that way.** An
  exception is not "no human is on this conversation". The FSM catches it, sets
  `TurnContext.deterministic_only`, and the task layer answers from FAQ/handoff only —
  never composing over a live handoff.
- **Media is acknowledged, not dropped.** `waha.py` used to return `None` for every
  image and voice note, so payment proofs vanished silently.
- The sweeper is a plain asyncio loop for now — the C1 fallback design. It becomes a
  DBOS scheduled tick once the Stage-0 spike passes.

### Running agent-core on Windows

psycopg's async driver **refuses to run on Windows' default ProactorEventLoop**, and
`AsyncConnectionPool` then retries the failed connection forever — so the symptom is a
hang with no output, not an error. `main.py` sets the selector policy on `win32`; async
tests pass `loop_factory=asyncio.SelectorEventLoop`. Irrelevant in Docker/Linux, which is
where the services actually run.

### Key implementation notes

- **WAHA API key env var:** use `WAHA_API_KEY` (not `WAHA_API_KEY_PLAIN`). The latter is ignored by current WAHA versions.
- **WAHA healthcheck endpoint:** `/api/ping` does not exist in WAHA Core. Use `GET /api/sessions`.
- **Langfuse account setup:** no web signup API in self-hosted v2. Account + org + project + API keys must be inserted directly into the `langfuse` Postgres DB (see `docs/nutriwhite-brain-plan.md` §Phase 1 deployment notes).
- **Langfuse credentials:** project `agent-core`, public key `pk-lf-FDYPt8YUi2j5_NKRTWHRg83bTBA`, secret key in `.env` as `LANGFUSE_SECRET_KEY`.
- **WAHA QR scan required:** WAHA must be paired with a WhatsApp number via the dashboard (`http://165.227.73.90:3000/dashboard`) before it can send/receive messages. Use a TEST phone for Phase 1; do NOT use the production Gutty number until Stage 3 cutover.
- **Group commands:** the FSM responds to `@Gutty tomo +phone` and `@Gutty resume +phone` in the team group (JID set via `HANDOFF_TEAM_GROUP_JID` in `.env`).

### New tables (sql/004_brain.sql — applied to prod)

- `turn_log` — every turn; phone SHA-256 hashed; review fields for self-learning (Phase 4)
- `patient_episodes`, `episode_summaries`, `patient_facts` — episodic memory stubs (Phase 3)
- `learning_queue` — self-learning review queue (Phase 4)

### .env additions for the Brain

```bash
WAHA_API_KEY=<hex32>                    # passed to container as WAHA_API_KEY
WAHA_HOOK_HMAC_KEY=<hex32>             # HMAC-SHA512 signing key
WAHA_DASHBOARD_PASSWORD=<string>
ANTHROPIC_API_KEY=<existing>
HANDOFF_TEAM_GROUP_JID=<jid>@g.us      # set after WAHA pairing
LANGFUSE_PUBLIC_KEY=pk-lf-FDYPt8YUi2j5_NKRTWHRg83bTBA
LANGFUSE_SECRET_KEY=sk-lf-...          # set in droplet .env
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_NEXTAUTH_SECRET=<base64-32>
LANGFUSE_SALT=<base64-32>
```

## OpenClaw deployment posture

OpenClaw runs **on the Ubuntu host** (not in Compose) via `systemd` + Node 24. The plugin is installed locally:

```bash
# Use --force so the extensions/ copy picks up any updated index.js
openclaw plugins install /root/nw-agent/openclaw/plugins/customer-service-tools --force
systemctl --user restart openclaw-gateway.service

# Verify the before_dispatch hook is registered in live Gateway memory:
openclaw plugins inspect customer-service-tools --runtime --json | jq '.hooks // .runtimeHooks'
# Expected: an entry naming "before_dispatch"
```

The plugin expects `RAG_API_URL`, `CRM_ADAPTER_URL`, and `INTERNAL_API_KEY` in the OpenClaw host environment. Tool allow/deny policy is documented in [docs/openclaw-setup.md](docs/openclaw-setup.md) — start from `profile: minimal` and the explicit allowlist there. **Do not** expose `group:runtime`, `group:fs`, `browser`, `web_search`, or `web_fetch` to the customer-facing agent.

The plugin's `before_dispatch` hook requires the `allowConversationAccess` permission flag in `~/.openclaw/openclaw.json`; without it, `event.content` is empty. Set it once on the droplet:

```bash
jq '.plugins.entries["customer-service-tools"].hooks = { allowConversationAccess: true }'   ~/.openclaw/openclaw.json > /tmp/oc.json   && mv /tmp/oc.json ~/.openclaw/openclaw.json
chmod 600 ~/.openclaw/openclaw.json
```

The [openclaw/hooks/nw-message-journal](openclaw/hooks/nw-message-journal/) hook appends every `message:received` / `message:sent` event to `/root/nw-agent/runtime/openclaw-message-journal.jsonl` so [scripts/openclaw_pending_messages.py](scripts/openclaw_pending_messages.py) can flag missed replies.

## Eval harness

[eval/run_eval.py](eval/run_eval.py) has two modes:

- **`--mode generation`** (default) — loads cases from `seeds.yaml`, runs them against each model in `MODEL_REGISTRY` (Anthropic/OpenAI/Google SDKs), writes JSONL to `eval/results/<timestamp>/<model>.jsonl`. **No tool calls** — evaluates raw response quality (Spanish naturalness, persona match, whether the model says it would hand off, hallucination).
- **`--mode intent`** — tool-correctness: hits rag-api `/v1/classify_intent` for each case and asserts the returned intent matches `expected_intent`. This is how the classifier's accuracy is measured (the docs cite ~99% on the seed set).

Results dir is gitignored. The harness loads `.env` itself with a custom path resolver (it does NOT use `python-dotenv`).

## graphify — the code graph

`graphify-out/graph.json` is a tree-sitter graph of this repo. Rebuilt automatically by the
post-commit and post-checkout hooks (`graphify update .` — AST only, no API cost, ~2 s).

- **Ask the graph before grepping.** `graphify query "<question>"` ·
  `graphify path "<A>" "<B>"` · `graphify explain "<symbol>"` · `graphify god-nodes` ·
  `graphify affected "<symbol>"`. Node labels for methods carry a leading dot — `.check_active()`,
  not `check_active` — and `affected` needs the exact label or it answers "no unique node match".
- **It finds structure, not defects.** A call graph does not encode `except: ... = False`. It gets
  you to the right file faster; the bug is still found by reading the body. Measured 2026-08-01.
- **`--code-only` is not optional here.** Without it, docs and images are sent to an LLM, and the
  backend is auto-selected in an order that reaches Kimi — Moonshot, in China — second. This repo
  is patient-adjacent. Rebuild with `graphify extract . --code-only --no-cluster`, and verify no
  model was called by checking `input_tokens: 0` in `graph.json`.
- **`graph.json` is not pure structure.** It embeds the first 80 characters of docstrings and
  `NOTE:`/`TODO:` comments, so it carries this code's sensitivity. It is gitignored; keep it so.
- **A graphify edge is never doctrine.** `confidence` is `EXTRACTED` or `INFERRED`, both
  `_origin: ast`. If it surfaces something durable about Zoho, WAHA or Stripe, a human writes that
  into `cerebro/facts.md` with its read-only check.
- **Never run `graphify claude install`** — it appends to this file and installs a PreToolUse hook
  intercepting every tool call. This section is the hand-written equivalent, without the hook.
