# Repo Recon — Code Seams for Cerebro Gutty v3 (F1–F12 mapping)

Date: 2026-07-08 · Scope: repo-only recon (no web research). All paths relative to repo root `C:\Users\Nutriwhite\Trabajo\05_Proyectos\nw-agent`. All claims verified by reading source this session.

## 1. Function-by-function mapping

### F1 Customer service (established) — LARGELY BUILT
- **Exists:** full turn pipeline in `src/company_agent/agent_core/` — `main.py` (webhook + HMAC), `fsm.py` (TurnFSM), `tasks/customer_service.py` (deterministic FAQ dict `DIRECT_FAQ_REPLIES` for 4 FAQs, handoff intents, greeting/farewell/clarify/fallback LLM composition via Haiku/Sonnet tiers), `llm/anthropic.py` + `llm/composition.py` (Spanish-VE prompts), rag-api hybrid retrieval (`src/company_agent/rag_api/search.py`, RRF k=60) and classifier (`rag_api/intent.py`). Legacy parallel implementation in `openclaw/plugins/customer-service-tools/index.js` still serves prod.
- **Gaps:** `waha.py:42-43` drops ALL non-text inbound (image/audio/document → `return None`); no RAG call from CustomerServiceTask (fallback prompt is LLM-only — `kb_search`/retrieve is only wired in the OpenClaw plugin, NOT in agent-core; `build_fallback_prompt` takes only the inbound text). No conversation history: each turn is composed stateless (no episode read).
- **Seams:** `TaskRegistry` (`tasks/base.py`), `TurnContext`/`TaskResult` models (`models.py`), rag-api `/v1/retrieve`.

### F2 Auto presupuesto (Zoho Quotes) — MISSING ENTIRELY
- Zero code touching Zoho `Quotes` or `Products` modules. `grep -i "quote|presupuesto|product"` over `src/` returns nothing. `zoho_client.py` reads only Contacts/Deals/Consultas/Examenes; only write is `create_note_on_contact` (Notes REST).
- **Seams to attach:** `ZohoClient._post`/`coql` low-level methods (`crm_adapter/zoho_client.py:105-128`); `BaseCrmAdapter` interface (`crm_adapter/adapters.py`); new crm-adapter endpoints alongside `/v1/customer/*`; dispatch mechanism (`intents/intent_seeds.yaml` `dispatch.tool` → new task module).
- No PDF/template handling anywhere; no deterministic amount-check code.

### F3 Real ticket system + handoff — PARTIAL (Notes-as-ticket, no real ticket system)
- **Exists:** `handoff_state` table (`sql/002_handoff_state.sql`): pending→claimed→resumed|expired, 24h default expiry, partial index on active phone. Store: `src/company_agent/common/handoff_state.py`. crm-adapter endpoints: `/v1/handoff` (creates Zoho Note + state row), `/v1/handoff/state/check` (hot path mute gate), `/v1/handoff/claim` (first-to-claim race with `already_claimed` distinction), `/v1/handoff/resume` (`crm_adapter/main.py:155-254`). agent-core side: `routing/handoff_client.py`, group commands `@Gutty tomo/resume +phone` in `fsm.py:242-311`, team-group push notification (`customer_service.py:_build_team_notification`).
- **Gaps:** "ticket" = a Zoho Note on the Contact; no ticket lifecycle/context-package beyond `last_message` + reason; handoff with no `contact_phone` silently skips the state row (`crm_adapter/main.py:172-181`); FSM handoff-check is fail-open (`fsm.py:103-106`); expiry sweep is only an index, no sweeper job found.

### F4 Proactive weekly outbound — MISSING ENTIRELY
- No scheduler, no cron, no outbound queue, no template management anywhere in `src/`. `WahaClient` has only `send_text` / `send_to_group` (`transport/waha.py:89-105`) — no media, no templates, no typing indicators, no read receipts. Whole system is webhook-reactive; nothing initiates a conversation.
- **Seams:** WahaClient (would need media/template methods), Postgres (pg_cron not installed; extensions present: `vector`, `pg_trgm`, `pgcrypto` — `sql/001_init.sql:1-3`), `patient_episodes` table (empty stub) for opt-in tracking would need new tables.

### F5 Post-consult nutrition seam — MISSING; registry is the only seam
- The intended plug point is `TaskRegistry.register()` (`tasks/base.py:20`) + intent seeds. But nothing supports multi-day sequences: no durable jobs, no timers, no per-patient sequence state. `patient_episodes`/`episode_summaries`/`patient_facts` exist as schema-only stubs (`sql/004_brain.sql:48-97`) with **zero reader/writer code** (grep over `src/` = no hits).

### F6 Master CRM operator — MISSING; read-only + Notes today
- Zoho surface (`crm_adapter/zoho_client.py`): COQL reads on Contacts (fields incl. `Idioma`, `Estado_de_Paciente`, `Especialista`), Deals (`Contact_Name` join), Consultas/Examenes (`Comunidad_NW` join); phone match = last-9-digit LIKE (`phone_search_suffix`, line 28). Writes: **Notes only**. No Leads, no Quotes, no Tasks, no Deal-stage updates, no record create/update, no dedup/merge, no audit trail, no idempotency keys.
- **Injection note:** COQL queries are built by f-string interpolation (`find_contact_by_email` line 160-165, phone suffix line 138-143) — no parameterization; a write-authority expansion must not copy this pattern.
- **Seams:** `ZohoTokenManager` (thread-safe refresh, 401 retry-once), `_request` retry wrapper, `BaseCrmAdapter`/`MockCrmAdapter` pair (mock keeps tests hermetic), `CRM_PROVIDER` switch in `crm_adapter/main.py:_build_adapter`.

### F7 Multi-source lead intake — MISSING ENTIRELY
- Only ingress in the entire system is `POST /webhooks/waha` (`agent_core/main.py:75`). No ManyChat/Meta Lead Ads/Zoho-webhook receivers, no identity-resolution code (the only identity logic is phone-suffix contact lookup in zoho_client). `grep -i lead` over src/ = no hits.
- **Seams:** FastAPI app in agent_core (add webhook routes), HMAC verify helper (`transport/hmac_verify.py`, SHA-512) reusable for new webhook sources, `normalize_waha_event` as the pattern for per-source normalizers.

### F8 Cadence engine ("toques") — MISSING ENTIRELY
- Same gap as F4: no scheduling substrate, no touch-sequence state, no task-type abstraction for "human call task." Closest primitive: `handoff_state` (a one-shot human-task row with claim semantics) could inspire but not serve a cadence table.

### F9 Sales agent — MISSING
- No qualification/objection/mode-2/mode-3 logic. Prices ARE deterministic today but hardcoded twice: `customer_service.py:41-56` (Plan 1 $229 / Plan 3 $559 / Plan 5 $789) and duplicated in `openclaw/plugins/customer-service-tools/index.js` — a dual-maintenance hazard and no Products-module source of truth. `handoff_discount` intent exists (escalates discount asks — `customer_service.py:70`, seeds line 284) — the only sales-adjacent behavior.
- **Seams:** intent classes + dispatch table; task registry; LLM tier system (`default`/`escalation` in `llm/anthropic.py:45`); eval harness `eval/run_eval.py` (generation + intent modes) is the graduation-gate skeleton.

### F10 MKT inbox relief (IG intake) — MISSING ENTIRELY
- No Instagram code of any kind. Transport is WAHA-only, single hardcoded session `"default"` (`waha.py:94`). `normalize_waha_event` → `WahaInboundMessage` is the normalization seam a second transport would mirror; `models.py` types are WAHA-named (would need a transport-neutral inbound model).

### F11 Company knowledge at full breadth — PARTIAL (manual markdown only)
- **Exists:** `ingest-worker` one-shot CLI (`src/company_agent/ingest_worker/main.py`) walks `knowledge/raw/` markdown, chunks 1200/180 (`common/text.py`), embeds OpenAI 1536-dim, delete-and-reinsert per `source_uri`. `knowledge_documents`/`knowledge_chunks` tables with GIN FTS + HNSW.
- **Gaps:** no Drive/website/Academy connectors; no continuous ingestion (manual `docker compose run`); no tacit-knowledge pipeline; FTS uses `to_tsvector('simple', ...)` — **not Spanish tsconfig** (`sql/001_init.sql:27`), so no Spanish stemming in lexical retrieval; `search_tsv` is GENERATED ALWAYS so a tsconfig change requires column rebuild. `corpus` column exists (default `'default'`) — an unused multi-corpus seam.

### F12 Self-learning loop — SCHEMA ONLY
- **Exists:** `turn_log` written on every turn (`agent_core/brain/turn_log.py`, sync psycopg wrapped in `asyncio.create_task`; phone SHA-256; review fields `review_status/reviewer/review_notes` with `reseed_pending/reseed_done` states; `follow_up_within_minutes` implicit-feedback column — never populated). `learning_queue` table (`sql/004_brain.sql:99-115`): kinds `reseed|new_intent|new_condition|new_entity|prompt_fix`, status pipeline pending→approved→applied.
- **Gaps:** zero code reads `turn_log.review_*` or touches `learning_queue` (grep = no hits). No review UI, no proposer, no applier. The reseed path would close the loop via `intent_seeder` (`src/company_agent/intent_seeder/main.py`, upsert on `(intent_class, example_text, language)`, `--reset`).

## 2. Component inventories

### WAHA client capabilities (`agent_core/transport/waha.py`)
- `send_text(chat_id, text)` → `POST /api/sendText`, session hardcoded `"default"`, fresh httpx client per call, 15s timeout. `send_to_group` = alias. `dm_jid(phone)` → `{digits}@c.us`.
- **Cannot:** send media/documents/PDFs (F2 needs PDF quotes!), templates, buttons/lists, reactions, presence/typing, session management, multi-session. Inbound: text only; media events dropped at normalize (`waha.py:42`); group sender via `participant`; `notifyName` as sender name.
- FSM send retry: 3 attempts, 0.5s sleep, then logs and marks outcome `error` — the patient reply is lost (no queue/dead-letter).

### crm-adapter endpoints (`crm_adapter/main.py`, port 8082, all POST, `X-Internal-API-Key` guarded)
- `/v1/customer/profile` (404 if not found), `/v1/customer/orders` (Deals), `/v1/customer/tickets` + `/v1/customer/consultas` (aliases → Consultas), `/v1/customer/examenes`, `/v1/tickets/draft` (Note draft), `/v1/handoff`, `/v1/handoff/state/check`, `/v1/handoff/claim`, `/v1/handoff/resume`, `GET /health`.
- Endpoints are **sync def** (FastAPI threadpool) using sync httpx → Zoho; fine at current volume, a consideration at 10×.

### handoff_state machine
- Table `sql/002_handoff_state.sql`; statuses `pending|claimed|resumed|expired`; priority `low|normal|high|urgent`; `expires_at` default NOW()+24h; audit ref `zoho_note_id`; claim fields `claimed_by_phone/name`. Store `common/handoff_state.py` (phone-normalized lookups). Active = status IN (pending, claimed).

### Intent classifier + dispatch
- `intents/intent_seeds.yaml`: 22 intent classes (4 direct FAQ, 3+ general FAQ, 3 patient-status, 8 handoff_*, greeting/farewell/acknowledgment). Each has `dispatch.tool`/`dispatch.params`.
- `rag_api/intent.py`: cosine-NN over `intent_vectors` (per-language bucket, `es` only seeded); thresholds from `RagSettings` (`intent_threshold_execute`/`_clarify`/`intent_tiebreak_margin`); tie-break downgrades execute→clarify; embeddings-disabled ⇒ always `fallback_llm`. Dispatch table loaded from the YAML **at rag-api startup** (`_load_dispatch_table`) — new intents require reseed (intent_seeder) + rag-api restart. This YAML+seeder+registry triple is the "new function as package" routing seam; it currently requires zero central-dispatch edits for routing but the `TaskRegistry` default-to-first fallback (`base.py:28`) makes unclaimed intents silently land in customer_service.
- Consumers: agent-core `routing/classifier_client.py` (retry once, per-turn client) and OpenClaw plugin — same endpoint.

### turn_log / learning_queue schemas
- See F12 above. Extra: `turn_log` has `graph_used`/`episodic_used` booleans (never set true), `reply_text` "cleared on retention cycle" per comment — no retention job exists. `learning_queue.source_turn_id` FKs `turn_log(turn_id)`.

## 3. Brief §4 punch-list re-verification (ALL 12 CONFIRMED)

| Claim | Verified at | Note |
|---|---|---|
| `auth.py:12` `!=` key compare | `common/auth.py:12` | non-constant-time `received_key != expected_key` |
| `fsm.py:39` in-memory `_SEEN` dedup | `agent_core/fsm.py:39-53` | OrderedDict LRU 10k, lost on restart, per-process |
| `fsm.py:104-106` fail-open handoff mute | `fsm.py:102-106` | exception ⇒ `is_muted=False` ⇒ Gutty talks over the human |
| `main.py:99` unbounded `asyncio.create_task` | `agent_core/main.py:99` | no backpressure, task refs not held (GC risk), returns 200 before processing |
| `main.py:80` HMAC fail-open on empty key | `main.py:80` | `if settings.waha_hook_hmac_key:` — empty ⇒ no verification; default is `""` (`config.py:12`) |
| `classifier_client.py:21` per-turn httpx client | `routing/classifier_client.py:21` | also `waha.py:91` and handoff client share the pattern |
| `customer_service.py:173-209` greetings hit LLM | `tasks/customer_service.py:172-209` | Haiku per greeting/farewell; canned only on exception |
| `base.py:24` silent first-match registry | `tasks/base.py:23-28` | no collision detection; default = first registered |
| `anthropic.py:69-72` raw PHI to Langfuse | `llm/anthropic.py:68-74` | full system+messages as trace input, no redaction; output too (line 88) |
| `config.py:15-16` no provider seam | `agent_core/config.py:15-16` | Anthropic-only model fields; `LLMClient` imports `anthropic` SDK directly |
| `waha.py:42` inbound media dropped | `transport/waha.py:42-43` | `msg_type not in ("chat","text","")` ⇒ None, silently |
| `patient_facts` lacks temporal validity | `sql/004_brain.sql:89-97` | PK `(contact_phone, fact_key)`, only `learned_at`; no valid_from/valid_to, upsert overwrites history |

## 4. Cross-cutting observations for candidates

- **Reactive-only skeleton:** every code path starts at the WAHA webhook. F4/F5/F8 (proactive/multi-day) have no substrate — the biggest architectural delta of v3 scope.
- **No durable execution:** side effects (send, handoff write, note create) are best-effort with logs; no outbox, no idempotency keys, no saga. Exactly-once (brief §3 precision) is unmet at every seam.
- **Dedup is not idempotency:** `_SEEN` is process-memory; WAHA webhook retries after an agent-core restart will double-process (double replies possible).
- **The extensibility story that exists:** intent_seeds.yaml (routing + dispatch) → intent_seeder → rag-api dispatch table → TaskRegistry task module. Missing package pieces per brief §3: per-package schedules/sagas, evals, policy bundles.
- **Two policy surfaces still live:** OpenClaw (`SKILL.md`, `AGENTS.md`, plugin tool descriptions + FAQ strings) and agent-core (`llm/composition.py` + `DIRECT_FAQ_REPLIES`) duplicate persona and prices. Pre-cutover fact; any candidate inherits the dedup task.
- **DB bootstrap, no migrations:** `sql/00x` via initdb order + `scripts/apply_brain_sql.sh` for prod. Operator-scope schema growth (leads, cadences, quotes, audit) needs a migration story.
- **Docker Compose stack (docker-compose.yml):** postgres (pgvector), rag-api :8081, crm-adapter :8082, ingest-worker (one-shot), waha :3000, agent-core :8083, langfuse :3001. OpenClaw on host systemd, outside Compose.
- **Spanish lexical retrieval is 'simple' tsconfig** — no stemming; brief R6 "Spanish tsconfig" is a real, verified gap, and the GENERATED column makes it a rebuild.
- **COQL f-string interpolation** in zoho_client is an injection-shaped pattern that must not scale into F6 write authority.
