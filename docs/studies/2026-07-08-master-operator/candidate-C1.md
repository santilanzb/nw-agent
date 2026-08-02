# Candidate C1 — "Evolve-Current v3": the FSM+Classifier Spine, Extended into the Master Operator

> **Study:** Cerebro Gutty v3 — Master Operator · **Date:** 2026-07-08 · **Composer:** C1 architect
> **Verdict claim:** the deployed FastAPI TurnFSM + embedding-classifier spine is the correct *reactive turn router* for this business, and it survives operator scope **only if** four missing substrates are added around it: a durable-execution layer (time + exactly-once), a gated CRM write layer (authority + audit), a multi-source intake bus with an identity broker (identity), and a formalized function-package contract (extensibility). This document specifies all four, is honest about every place the current spine cracks, and shows the build fits a 1–3 person team on the existing droplet.
> Sources: brief `BRIEF.md`, repo recon `recon-code-seams.md`, research packs R1–R10 (same directory). External claims carry URLs; unverified items are flagged.

---

## 0. Thesis

Two independent 2026 evidence lines say the same thing about the core:

- The production consensus for customer-facing conversational agents is a **thin, owned deterministic loop**, not an agent framework — "own your control flow" (12-factor agents, https://github.com/humanlayer/12-factor-agents) and "start with LLM APIs directly; frameworks obscure prompts" (Anthropic, https://www.anthropic.com/research/building-effective-agents). Agent-core's ~300-line TurnFSM *is* that pattern, already deployed and healthy on the droplet.
- Routing scale is not the constraint. The FSM routes intent→module via the embedding classifier (~99% on seeds, `rag_api/intent.py`) and a registry lookup; 20–50 disjoint TaskModules scale linearly. The real scaling risk is intent-overlap in the classifier — a seed-data problem solved with evals, not a rewrite.

So C1 does **not** defend the status quo. The recon is unambiguous: F2, F4, F5, F6 (beyond reads+Notes), F7, F8, F9, F10 have **zero substrate** — the entire system starts at `POST /webhooks/waha` and every side effect is best-effort. C1's bet is that the cheapest, lowest-risk path to the operator brain is to keep the proven 20% (turn loop, classifier, RAG stack, handoff machine, crm-adapter seam, turn_log/learning schema) and build the missing 80% as **four additive subsystems in the same process and the same Postgres**, rather than re-platforming a working spine onto a framework that still would not provide cadence scheduling, CRM write-gating, or identity resolution (none of LangGraph / Agents SDKs / Mastra do — R5).

---

## 1. Where the spine cracks at operator scope (honest inventory)

C1's credibility depends on naming these before the red-team does. Each crack gets a designed compensation; residual risk is stated.

| # | Crack | Evidence | Compensation (layer) | Residual risk |
|---|---|---|---|---|
| 1 | **Reactive-only.** No scheduler, cron, queue, or any code path that initiates a conversation. F4/F5/F8 have zero substrate. | recon §4; `agent_core/main.py:75` single ingress | DBOS Transact durable execution: `@DBOS.scheduled`, durable sleep, queues (L5). License verified MIT, v2.26.0 released 2026-06-30 (https://github.com/dbos-inc/dbos-transact-py, fetched 2026-07-08) | DBOS ecosystem youth / single-vendor OSS; Stage-0 integration spike remains the gate (fallback: hand-rolled SKIP-LOCKED worker, ~2 wks) |
| 2 | **No exactly-once anywhere.** In-memory `_SEEN` dedup wiped on restart (`fsm.py:39`); webhook 200-before-processing (`main.py:99`); WAHA send gives up after 3 retries, reply lost; handoff-create failures swallowed (`fsm.py:228`); no outbox, no idempotency keys. | recon §3, §4 | Postgres inbox (source+event_id unique) + send-intent outbox + deterministic idempotency keys on every external call, wrapped in DBOS checkpointed steps (L5, §5) | Steps are at-least-once; we deliver *effectively-once via idempotency guards*, not literal exactly-once — honest framing, and the strongest guarantee any candidate can offer against Zoho/Meta APIs |
| 3 | **Write authority does not exist, and the read path is injection-shaped.** Only Zoho write is `create_note_on_contact`; COQL built by f-string interpolation (`zoho_client.py:138-165`). | recon F6 | CrmWriteGate: enumerated typed actions, WAL ledger + snapshots, staged autonomy, parametrized COQL, dedicated Gutty Zoho user (L7) | Zoho has no native idempotency-key mechanism (https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html) — client-side ledger is load-bearing |
| 4 | **Single-ingress identity model.** Identity = last-9-digit phone LIKE with silent `rows[0]` fallback; no ManyChat/Meta/Zoho receivers; no IGSID/email/phone join table. | recon F7; `zoho_client.py:28-34` | Intake bus + Postgres identity broker with canonical keys, unique constraints, advisory-lock merges, Zoho upsert on `duplicate_check_fields` (L2, L3) | Fuzzy merges go to human review — some manual work remains by design |
| 5 | **Registry is a silent trap.** First-match resolve, unclaimed intents silently land in customer_service (`tasks/base.py:23-28`); dispatch table only reloads on rag-api restart; packages have no place for schedules/sagas/evals/policy. | recon §1-F5, intent pipeline | Function-package contract + explicit-claim registry with collision detection + dispatch hot-reload (L15) | None material; this is cheap to fix |
| 6 | **F1 is weaker than advertised.** agent-core never calls rag-api `/v1/retrieve`; LLM fallback is stateless (no retrieval, no history); inbound media dropped silently (`waha.py:42`); greetings burn LLM calls. | recon F1 | Wire retrieval + episode memory into CustomerServiceTask; canned greetings; media acknowledged-and-deflected until transcription path exists (L4) | Voice-note handling deferred (PHI-safe transcription is its own decision — R4 open question) |
| 7 | **Transport monogamy on a bannable channel.** WAHA/NOWEB cannot send templates; proactive outbound on unofficial clients is Meta's textbook ban profile (real ban waves: https://github.com/devlikeapro/waha/issues/1362, https://github.com/WhiskeySockets/Baileys/issues/1869). | R7 | Dual transport: Meta Cloud API direct for ALL business-initiated sends from day 1; WAHA demoted to legacy-inbound bridge with a scheduled retirement (L1) | Number-migration friction at cutover; state lives in Postgres keyed on E.164 so system memory survives (https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/migrate-existing-whatsapp-number-to-a-business-account/) |
| 8 | **Live privacy leaks.** Raw system+user text to Langfuse (`anthropic.py:68-74`); raw text in turn_log; no conversation_class, no consent tables; Anthropic-only client with no provider seam (`config.py:15-16`). | recon §3; R8 | Content-gated two-class split at the classifier mount + redaction before derived stores + thin provider router (L12, L13) | Spanish-VE redaction is unsolved to a certifiable standard (no VE recognizers in Presidio; GLiNER2-PII unbenchmarked on VE WhatsApp register — R8). Treated as defense-in-depth, never the compliance boundary. Flagged, not hand-waved. |
| 9 | **One process, one droplet.** agent-core becomes ingress+FSM+DBOS+cadence in a single FastAPI process. | design consequence | Bounded ingress queue, DBOS crash-recovery makes restarts safe, workers scale out on the same Postgres if needed; load math says single-digit jobs/minute peak at 2k leads/mo (R2) | Concentration is real; the documented escape hatch is Temporal Cloud (HIPAA BAA, https://temporal.io/blog/temporal-cloud-is-now-hipaa-compliant) if the business outgrows the library model |
| 10 | **Schema is initdb-bootstrapped, no migrations.** Operator scope adds ~12 tables. | recon §4 | Alembic migrations from Stage 0; initdb SQL frozen as baseline (L16) | Low |

---

## 2. Target architecture (one diagram)

```
  INGRESS (all durable-inboxed, per-source signature verify)
  ┌ /webhooks/waha        (legacy inbound, HMAC-SHA512)         ┐
  ├ /webhooks/meta        (Cloud API msgs+statuses+calls stub)  │
  ├ /webhooks/manychat    (IG External Request)                 ├─► intake_events (Postgres inbox,
  ├ /webhooks/zoho        (workflow-rule webhook {module,id})   │    UNIQUE source+source_event_id)
  └ /webhooks/leadchain   (Meta Lead Ads via Zoho — same route) ┘         │
                                                                          ▼
        ┌─────────────── agent-core (FastAPI, :8083, one process) ────────────────┐
        │  Normalizers → InboundEvent (transport-neutral)                         │
        │  Identity Broker ── canonical keys: E.164/wa_id/email/IGSID ──► Zoho    │
        │  TurnFSM (reactive router)                                              │
        │    ├ handoff mute check ─► handoff_state                                │
        │    ├ privacy gate: conversation_class (marketing|care)                  │
        │    ├ classify ─► rag-api /v1/classify_intent (dispatch table)           │
        │    └ TaskRegistry (explicit claims) ─► TaskModules                      │
        │         customer_service · sales(F9) · presupuesto(F2) · crm_ops(F6)    │
        │         mkt_inbox(F10) · nutrition_followup(F5 seam) ...                │
        │  DBOS Transact (in-process durable execution)                           │
        │    ├ @scheduled: cadence ticks, expiry sweeper, retention, reconciler   │
        │    ├ durable workflows: presupuesto saga, cadence enrollments, F5 seqs  │
        │    └ outbox: send_intents (exactly-once guards) ─► transports           │
        │  LLM Router: care→Anthropic sync (BAA) · marketing→Gemini 3.5 Flash*    │
        └──────────────────────────────────────────────────────────────────────────┘
              │                      │                              │
              ▼                      ▼                              ▼
        rag-api :8081          crm-adapter :8082               Transports
        hybrid RRF +           reads (parametrized COQL)       Meta Cloud API (templates,
        Spanish tsconfig +     CrmWriteGate: typed actions,    docs/PDF, CTWA referral,
        contextual retrieval   crm_write_log WAL, autonomy     calls-webhook stub)
        + intent classifier    ladder, write budgets           WAHA (legacy bridge, retiring)
              │                      │
              ▼                      ▼
        Postgres (pgvector, same instance): knowledge_chunks · intent_vectors ·
        turn_log · learning_queue · handoff_state · identity_registry · intake_events ·
        cadence_defs/enrollments · consent_ledger · suppression_list · send_intents ·
        crm_write_log · quotes_ledger · claims_registry · DBOS system tables
        Phoenix (OTel traces, single container, replaces Langfuse v2)
```

*Gemini 3.5 Flash for marketing-class turns is **eval-gated** (brief §4b): confirmed via `eval/run_eval.py` Spanish-VE cases before commitment; Haiku 4.5 is the incumbent fallback.

---

## 3. F1–F12 coverage map

| Fn | Status today (recon) | C1 mechanism |
|---|---|---|
| F1 Customer service | Largely built, but no RAG/history in agent-core fallback | Keep pipeline; wire `/v1/retrieve` + episode memory into CustomerServiceTask; canned greetings (kill `customer_service.py:172-209` LLM burn); media politely deflected pending transcription decision |
| F2 Auto presupuesto | Missing entirely | Presupuesto engine (L8): deterministic composer from Products id-allowlist → Zoho **Quotes** (Quote_Stage lifecycle) → **local HTML→PDF render** (Zoho v8 has no endpoint to fetch the rendered quote PDF — https://www.zoho.com/crm/developer/docs/api/v8/inventory_templates.html) → WhatsApp document send via Cloud API, all as one DBOS saga with amount check. Zoho Books: excluded per brief §4b. |
| F3 Ticket + handoff | Substantially built | Reuse handoff_state machine + claim/resume commands; add context package (qualification slots, cadence history, last-N turns), DBOS expiry sweeper, fix the no-phone silent skip (`crm_adapter/main.py:172-181`) and fail-open mute policy |
| F4 Weekly outbound | Missing entirely | Cadence engine (L6) with marketing templates via Cloud API, double opt-in consent ledger, suppression list, batching under Meta messaging-limit tiers (https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits) |
| F5 Nutrition follow-up seam | Missing; registry-only seam | Function package = seeds + task module + **cadence/saga defs** + evals; multi-day sequences = DBOS durable sleep; plan PDFs reuse the F2 renderer + document send. Seam is real code (package contract), not a promise. |
| F6 Master CRM operator | Reads + Notes only | CrmWriteGate (L7): enumerated typed actions over Leads/Contacts/Deals(stage)/Quotes/Tasks/Notes; WAL + snapshots + undo; staged autonomy shadow→ask-first→auto; dedup via identity broker + Zoho upsert/Merge APIs; hygiene ships **before** autonomy (Agentforce dirty-data lesson, https://solutions4sf.com/blog/agentforce-b2b-reality-check/) |
| F7 Multi-source intake | Missing entirely | Intake bus (L2) + identity broker (L3): ManyChat External Request, Meta Lead Ads via Zoho LeadChain, Zoho workflow-rule webhook `{module, record_id, event}` with integration-user loop guard, manual entries via same Zoho webhook |
| F8 Cadence "toques" | Missing entirely | Event-triggered first touch at intake (<5 min; 21× qualify odds — https://25649.fs1.hubspotusercontent-na2.net/hub/25649/file-13535879-pdf/docs/mit_study.pdf); touches 2..N scheduled; state machine per enrollment; US(+1) branch (marketing templates hard-blocked to US — https://www.messagecentral.com/blog/whatsapp-marketing-usa-what-is-allowed); TOUCH_CALL task type creates a prepared Zoho Task today, voice agent later |
| F9 Sales agent | Missing (only handoff_discount) | Sales TaskModule (L9): 7-slot SPICED-lite qualification (code-controlled, LLM-extracted), objection intents with one-reframe-then-escalate, precomputed price decompositions, claims registry + classifier on 100% of outbound sales turns, mode-3-as-shadow-mode graduation gates per product |
| F10 MKT inbox relief | Missing entirely | ManyChat default-reply flow → intake bus; short templated IG reply + wa.me ref-token link (doubles as the only deterministic IGSID↔wa_id join — https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/user-profile); CRM insert via broker + WriteGate. IG stays intake-only per brief. |
| F11 Knowledge breadth | Manual markdown ingest only | Drive shared-folder `changes.list` polling connector (https://developers.google.com/workspace/drive/api/guides/manage-changes), website sitemap+hash scraper, tacit CDM interview→SOP loop, Spanish+unaccent tsconfig migration, contextual retrieval (~$1/full re-index — https://www.anthropic.com/engineering/contextual-retrieval), `facts/prices.yaml` deterministic fact table + dollar-amount output guard |
| F12 Self-learning | Schema only (zero readers) | Build the missing proposer/review/applier over existing turn_log + learning_queue; Haiku-class judge on 100% LLM-composed sales turns (~$5–20/mo at volume — R9); reseed closes via intent_seeder with eval-regression auto-revert |

---

## 4. The 16-layer stack

Legend: **REUSE** (keep as-is / harden), **HYBRID** (existing + significant addition), **BUILD** (new owned code), **BUY** (external service/API).

### L1 · WhatsApp transport — HYBRID (buy Meta Cloud API direct; reuse WAHA as retiring bridge)
**Choice:** New Cloud API number immediately for all business-initiated sends (templates, cadences, quote PDFs, CTWA funnels); legacy Gutty number migrates at cutover (Coexistence if Business-App-eligible, else hard migration — Postgres keeps all state). WAHA survives only as legacy-inbound + internal team-group bridge with scheduled retirement.
**Rationale:** WAHA cannot send template messages at all, and proactive outbound to non-repliers over unofficial clients is the canonical ban profile with documented 2025-26 ban waves (R7). Cloud API is also the only path to CTWA `ctwa_clid` attribution and the GA WhatsApp Business Calling API (voice seam) — https://docs.pipecat.ai/pipecat/features/whatsapp. Meta-direct = $0 platform fee; agent-core is already a webhook host.
**Rejected:** WAHA-only (existential ban risk for F8); Twilio BSP (+$0.005–0.010/msg buys only managed voice we don't need yet); 360dialog (€49/mo wins only ≳10k paid msgs/mo — https://360dialog.com/pricing).

### L2 · Ingress & intake bus — BUILD
**Choice:** One normalizer service *inside agent-core*: `/webhooks/{waha,meta,manychat,zoho}` routes, per-source signature verification (reusing the `verify_waha_hmac` pattern), per-source normalizers emitting a transport-neutral `InboundEvent`, all writes going first to a durable `intake_events` inbox (UNIQUE on `source + source_event_id`). Replaces the in-memory `_SEEN` dedup for every ingress.
**Rationale:** Meta redelivers on non-2xx; ManyChat likely never retries and has **no API to enumerate subscribers** — enqueue-then-ACK plus a Sheets-export reconciliation lane is mandatory (https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-request). A new intake source = a new normalizer posting to the same bus — the extensibility criterion at the ingress layer.
**Rejected:** n8n as intake glue (second brain, silently skips missed schedule ticks — R2); iPaaS bridges ($30–80/mo for what two webhook routes cover — R1).

### L3 · Identity broker — BUILD
**Choice:** Postgres `identity_registry`: canonical keys (country-aware E.164 via libphonenumber, observed wa_id, lower(email), IGSID) with unique constraints, `INSERT..ON CONFLICT`, `pg_advisory_xact_lock` around multi-key merges; Zoho writes only via upsert with `duplicate_check_fields` on a custom unique Phone_E164 field; v8 Merge Records API for after-the-fact repair; fuzzy matches → human review queue, never auto-merge.
**Rationale:** wa_id ≠ typed E.164 (Mexico 521/52, Argentina 549, Brazil legacy 9th-digit — https://www.zoko.io/learning-article/whatsapp-id-brazil-mexico); the current last-9-digit LIKE fails exactly there and silently picks `rows[0]`. Identity is the foundation of F6 hygiene and F7 dedup; it must be owned code under *every* candidate (R1), so building it on the incumbent stack carries zero switching cost.
**Rejected:** keep suffix-LIKE (fails on Brazil legacy IDs, ambiguity-silent); Zoho-only dedup (no IGSID/wa_id concept in Zoho).

### L4 · Orchestration core: TurnFSM — REUSE (harden)
**Choice:** Keep the hand-rolled TurnFSM as the reactive router. Stage-0 hardening: inbox-table dedup (kills `_SEEN`), bounded ingress queue with backpressure (kills unbounded `create_task`), HMAC fail-closed on empty key, constant-time API-key compare, shared httpx clients, mute check fail-degraded (on error: answer FAQ-deterministic only, never talk over a human on LLM paths), registry explicit-claim (L15), retrieval + episode memory wired into the fallback path (activates the stub `patient_episodes`/`episode_summaries` tables with real reader/writer code).
**Rationale:** matches the 2026 owned-loop consensus (R5); every alternative replaces working, understood code with an abstraction that still lacks the four missing substrates. Deterministic hot path stays <1s (FAQ dict + dispatch; DBOS is not on the hot path).
**Rejected:** LangGraph rewrite (checkpoint serialization footguns, debugging "worse than a custom loop", still no cadence cron — R5); OpenAI Agents SDK (model-centric, no durability); Mastra (TypeScript fragmentation); Claude Agent SDK (wrong shape for webhook-driven multi-conversation; reconsider narrowly later as an inner engine for deep CRM-ops tasks).

### L5 · Durable execution & scheduling — HYBRID (adopt DBOS Transact library + build the tables)
**Choice:** DBOS Transact (Python) inside the agent-core process: `@DBOS.scheduled` for cadence ticks/sweepers/retention/reconciliation; durable workflows with `DBOS.sleep` for multi-day sagas (F2 quote follow-ups, F5 sequences); checkpointed steps + durable queues for side effects. State in the existing Postgres ("no infrastructure required besides Postgres" — https://docs.dbos.dev/architecture).
**Rationale:** the spine's #1 crack is time and #2 is exactly-once; both are durable-execution problems, not framework problems (R5). Workload is ~300–800 scheduled jobs/day — every engine is 1000× over-provisioned on throughput, so the decision axis is ops burden, and a library beats a cluster for a 1–3 person team. Steps are at-least-once → idempotency guards are mandatory (§5).
**Rejected:** Temporal (self-host = multi-service cluster ~$2.5–4.5k/mo all-in per third-party TCO, UNVERIFIED single source; Cloud = payloads off-infra + second programming model; documented escape hatch, not the start — https://automationatlas.io/guides/temporal-cloud-vs-self-hosted-2026/); Restate (second stateful runtime with its own PHI-bearing journal); pg_cron/pgmq (needs custom pg image + restart, and retry policy gets hand-written anyway); n8n (rejected as cadence owner — R2).
**Gate (updated 2026-07-08):** license is **verified MIT** and the project is actively maintained (v2.26.0 released 2026-06-30; durable workflows, `@DBOS.scheduled` cron, durable sleep, and Postgres-backed queues all confirmed in repo docs — https://github.com/dbos-inc/dbos-transact-py). The remaining Stage-0 gate is a 2-day integration spike (FastAPI coexistence, crash-recovery behavior on the droplet) plus a vendor-viability judgment call; fallback is a hand-rolled `FOR UPDATE SKIP LOCKED` worker (~2 weeks, permanent bug ownership — priced in as the honest fallback).

### L6 · Cadence engine ("toques", F8 + F4 + F5 substrate) — BUILD (on L5)
**Choice:** Versioned `cadence_definitions` separate from per-lead `cadence_enrollments` (current_step, next_run_at, state machine active→replied|opted_out|exhausted|paused_handoff|channel_invalid); replies kill pending touches synchronously in the inbound path; consent ledger + suppression list checked synchronously before every send; send-intent row keyed `(enrollment_id, step_no)` written before the transport call; first touch event-triggered at intake, touches 2..N scheduled with business-hours/timezone windows; **country-code branch** (US +1 gets utility/CTWA/service-window/human-task touches only); status-webhook-driven rescheduling (per-user marketing caps make delivery probabilistic — error 131049, https://blog.campaignhq.co/whatsapp-healthy-ecosystem-error-131049); TOUCH_CALL = Zoho Task with script + context (the voice seam, today).
**Rationale:** this is the convergent SDR cadence pattern (R2) expressed as ~6 Postgres tables + DBOS workflows; window engineering (CTWA 72h free, service-window replies free, utility 6.5× cheaper than marketing) is treated as architecture because it cuts template spend 2–3× (R2).
**Rejected:** Zoho Marketing Automation (broadcast-shaped; replies don't reach the brain — R2/Zoho recon); n8n; fire-and-forget sends.

### L7 · CRM write layer: CrmWriteGate — BUILD (in crm-adapter)
**Choice:** Single choke point for every agent write: enumerated typed Pydantic actions (`create_lead`, `upsert_contact`, `update_contact_fields`, `move_deal_stage`, `create_quote`, `create_task`, `create_note`, `link_records` — no generic update tool, **no delete actions at OAuth-scope level**); `crm_write_log` WAL with deterministic idempotency key (hash of `turn_id|action|canonical_params`) + pre-write snapshot of touched fields (undo = compensating update; Recycle Bin API covers accidents 60 days — https://www.zoho.com/crm/developer/docs/api/v8/restore-recycle-bin-records.html); per-action-type autonomy ladder: ≥2 weeks shadow against the **already-provisioned Zoho sandbox** (`scripts/zoho_smoke_test.py`) → ask-first via team approvals → auto after ~50 consecutive zero-correction approvals; deterministic write budgets (~30/hr, ~200/day, per-contact caps, catalog-max amount checks) whose breach flips everything back to ask-first + kill-switch ping; dedicated "Gutty" Zoho user (~$14–52/mo) so Timeline attributes agent vs human writes; all COQL parametrized/escaped before any LLM-derived value flows in.
**Rationale:** all three 2026 CRM vendors converge on enumerated actions + agent identity + graduated autonomy + hard guardrails (Zia/Breeze/Agentforce — R3); Zoho credits are a non-issue at this volume (Standard floor 50k/24h vs ~1–10% usage — https://www.zoho.com/crm/developer/docs/api/v8/api-limits.html); the binding constraint is trust, and the ledger + ladder is what builds it.
**Rejected:** direct LLM tool-calls to Zoho (no idempotency/undo, live injection surface); Zia Agent Studio as the writer (second brain, PHI through Zia LLM, BAA coverage UNVERIFIED — R10); permanent human approval (defeats the mission; valid only as ladder stage 2).

### L8 · Presupuesto engine (F2) — BUILD
**Choice:** Deterministic quote composer: line items pinned by Products-module `id` allowlist (curated by calidad@; `Product_Active` respected), amount check = independently computed total vs sum of `Quoted_Items` before any send; Zoho **Quotes** record created via WriteGate with `Quote_Stage` lifecycle (Quoted_Items subform mandatory, `Product_Name:{id}` pinning — https://www.zoho.com/crm/developer/docs/api/v8/insert-records.html); **PDF rendered locally** (HTML template → WeasyPrint-class) from the same line-item data, because Zoho v8 can email a quote PDF but exposes **no endpoint to fetch the rendered PDF** (https://www.zoho.com/crm/developer/docs/api/v8/send-mail.html); delivered as a WhatsApp document message (utility template out-of-window: $0.008–0.0113); the whole flow is one DBOS saga (create → render → send → log → schedule follow-up touch) with idempotency at each step so retries never double-create quotes.
**Rationale:** satisfies the brief's F2 mechanism exactly (Quotes + Products + PDF + stage lifecycle, never Books) and the deterministic-amount constraint by construction — the LLM never generates a number; it selects products from an allowlist and the composer does arithmetic.
**Rejected:** Zoho Books (forbidden §4b); Zoho `send_mail` for delivery (email-only, 20 credits, not WhatsApp); LLM-composed line items or totals (forbidden §3); Zia Quote Generator (LLM-priced — fails the fixed-price rule; R10).

### L9 · Sales agent (F9) — BUILD (as TaskModules on the spine)
**Choice:** SPICED-lite ~7-slot typed qualification schema — code controls the next question and completeness, LLM only extracts and phrases; max one qualification question per turn (LatAm relational norm — R4); slots persist in Zoho Lead fields with a marketing/health tier split (health-tier slots ride the BAA sync path only); objection taxonomy as intent seeds (objection_price, objection_skepticism, objection_timing, objection_decision_maker, objection_payment_friction, objection_exam_cost, stall_generic); bounded one-value-reframe-then-escalate loop with precomputed price decompositions (constants, never LLM arithmetic) and the free 15-min call as universal de-risk; versioned approved-claims registry + claims classifier on **100% of outbound sales turns** (FTC AI-chatbot health scrutiny is active — https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance); discounts always escalate with packaged negotiation context (prices fixed). Mode 3 launch everywhere; **mode 3 is shadow mode for mode 2**: log Gutty's recommended action at tee-up, asesora's actual decision = free ground-truth label; graduate per product via gates (offline suite 100% on price/claim probes → ≥50 shadow convs at ≥90% action-agreement, 0 critical failures → 2-week 10% canary with 100% review of payment-link sends → standing auto-demote). Consultation plans (3 fixed SKUs) graduate before itemized exam presupuestos.
**Rationale:** independent evidence says AI does not out-close humans (11x/ZoomInfo — https://techcrunch.com/2025/03/24/a16z-and-benchmark-backed-11x-has-been-claiming-customers-it-doesnt-have/); the value case is <1-minute 100% first-touch coverage + qualification + tee-up. The slot-schema pattern is the only one with production evidence of surviving LLM implementation (R4), and it is a *thin extension of the existing classifier spine* — C1's home turf.
**Rejected:** buy an AI-SDR (documented 70–80% churn, English/B2B-first, no PHI posture); freeform persona prompt (unauditable for a 1-person QA team).

### L10 · Ticketing & handoff (F3) — REUSE (extend)
**Choice:** Keep handoff_state machine (pending→claimed→resumed|expired), claim/resume semantics, team push. Add: context package (qualification slots, cadence history, last-N turns, negotiation context) attached to the ticket; DBOS expiry sweeper; fix the contact_phone-less silent skip; mute check degrades safe (deterministic-only replies on check failure). Team group coordination stays on a WAHA internal session short-term — Cloud API does not support group chats (consistently absent from Meta reference; UNVERIFIED as an explicit "no") — and migrates to the ops console surface at Stage 5.
**Rationale:** F3 is the one operator function that is substantially built and validated; extending beats replacing.
**Rejected:** Chatwoot now (v2's choice; a real inbox UI is valuable but is +1 service and its own PHI store — deferred to an optional Stage 5 decision, explicitly not load-bearing); Zoho Desk (new SKU, team lives in WhatsApp).

### L11 · Knowledge & retrieval (F11) — HYBRID (reuse RAG stack + build connectors/quality)
**Choice:** Keep hybrid RRF retrieval + pgvector. Fix quality near-free: custom Spanish snowball + unaccent-dictionary tsconfig (the `simple` config currently breaks stemming/accents for a Spanish-only corpus — `sql/001_init.sql:27`; GENERATED column means one rebuild migration) and contextual-retrieval chunk prefixes (~$1/full re-index). Build connectors: Drive shared-folder polling (service account, one curated "Gutty Knowledge" folder = the approval gate; `files.export` to markdown; content-hash skip + tombstone deletes), website sitemap+lastmod+hash cron; never ingest paid Academy course bodies (catalog only). Tacit loop: monthly CDM-style case-anchored interview → Whisper transcript → LLM-drafted SOP → owner sign-off → Drive folder → existing ingest (~1 staff-hour/mo — R6). Deterministic fact boundary: `facts/prices.yaml` single source rendering FAQ strings in agent-core, price lines in knowledge/raw, and eval assertions (prices currently hardcoded in ~7 places — grep-verified R6), plus a regex output guard blocking any LLM-composed reply containing a dollar amount not in the fact table. Freshness: verified_at/valid_until/owner chunk metadata, weekly stale-doc report to the team group.
**Graph-RAG (Apache AGE) — committed position (§4b): seam now, adopt at Stage 5 only on eval failure.** Seam = keep the unused `corpus` column, add entity-mention extraction at ingest into plain relational tables (entities, entity_mentions) so a graph can be projected later without re-chunking. Adoption gate: a 20-case multi-hop eval (exam↔protocol↔condition↔service joins) run at Stage 5; adopt AGE only if hybrid+contextual retrieval fails >20% of it. Honest ops note: AGE requires a custom pg image alongside pgvector plus a restart — the exact ops cost L5 was chosen to avoid — so it must buy demonstrated multi-hop wins, not vibes. Rejecting it outright would be anchoring; adopting it now would be gold-plating a corpus of dozens of documents.
**Rejected:** managed ingestion SaaS ($50–500/mo + data egress to duplicate a working pipeline); external reranker now (defer until an eval set proves misses; rerank queries are patient utterances = PHI touchpoint with UNVERIFIED vendor DPA terms — R6).

### L12 · Model layer & routing — HYBRID (build thin router; buy inference)
**Choice:** Replace the Anthropic-only client with a ~150-line owned provider router (Anthropic SDK + Google SDK behind one interface), routing on **data class × task tier**: care-class turns → Anthropic synchronous Messages API under BAA (Batch is contractually excluded from the BAA — https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers); marketing-class turns → **Gemini 3.5 Flash** ($1.50/$9.00 per M, 1M ctx, native multimodal — brief §4b, verified there) *pending confirmation by `eval/run_eval.py` on Spanish-VE cases against Haiku 4.5 ($1/$5)*; escalation tier stays Sonnet-class; nightly offline jobs (judge, learning proposals) run on **redacted marketing text only** via Batch at 50% discount. Gemini touches patient PHI only if/when routed via Vertex AI + BAA (not at launch).
**Rationale:** honors the user's TIER-1 preference signal as an eval-gated commitment, not faith; fixes the `config.py:15-16` no-provider-seam punch item; keeps the PHI routing rule enforceable in one place.
**Rejected:** LiteLLM proxy (a service + config surface for 2–3 providers a thin interface covers; revisit if provider count grows); status-quo Anthropic-only; GLM/Zhipu/DeepSeek (China-hosted — blocked §3).

### L13 · Privacy & data-class boundary — BUILD
**Choice:** Content-gated dynamic split (R8): a health-content gate mounted at the classifier (which already inspects every turn, zero added latency) + Spanish Art. 9(2)(a) consent micro-flow that promotes a conversation to `care` class mid-thread; `conversation_class` on turn_log + consent-event tables; class routes models (L12), observability redaction, retention. Fix the two live leaks: Presidio + GLiNER2-PII + custom V-/E-cédula and RIF recognizers redact before every derived-store write (traces, eval sets, learning_queue, Batch inputs); validated by a 100–200-turn in-house VE-Spanish redaction eval because **no tool is benchmarked for this register — redaction is defense-in-depth, never the compliance boundary** (flagged per brief). Retention as DBOS scheduled jobs: lost leads purged at 12 months + indefinite suppression tombstone; health turns from never-consented leads deleted/redacted at 30 days; Zoho BAA signed (https://www.zoho.com/crm/data-security/hipaa.html) + field-level encryption on Examenes/Consultas health fields. Framing: GDPR Art. 9 is the binding regime; HIPAA is a voluntary care-side quality bar (NutriWhite is almost certainly not a covered entity; WhatsApp transport can never be literally HIPAA-compliant — https://www.hipaajournal.com/whatsapp-hipaa-compliant/).
**Rationale:** matches how the law actually triggers (on content, not CRM status), and honestly exploits the two-class split: ~90% of volume runs at commodity cost.
**Rejected:** treat-everything-as-PHI (blocks Batch economics, still not literally compliant); static lead/patient split (legally wrong — leads volunteer symptoms in message 1); full physical separation (hospital-grade overkill).

### L14 · Observability, evals & learning loop (F12) — HYBRID
**Choice:** Postgres turn_log + learning_queue stay the **authoritative system of record** (already designed for it; R9). Re-instrument the LLM client once via OpenTelemetry and point traces at **Arize Phoenix** (single container on the existing Postgres, evals + annotation bundled, ELv2 free self-host — https://github.com/arize-ai/phoenix), retiring Langfuse v2 (maintenance-only dead end; v3 needs ClickHouse+Redis+S3 = 3 containers + droplet upgrade — https://langfuse.com/self-hosting). Judge 100% of LLM-composed sales turns nightly with a Haiku-class judge (tone, groundedness vs retrieved context, price/claim accuracy, next-step, missed handoff) — ~$5–20/mo at this volume, so sampling folklore doesn't apply; deterministic turns are never judged. Add `--mode crm` to eval/run_eval.py: COQL read-after-write assertions against the Zoho sandbox for every write action; nightly production write-reconciliation (every write-dispatching turn must match a Zoho record). Weekly clustered review ≤2h with strict priority; reseeds auto-apply behind eval-regression auto-revert (>2% pass-rate drop reverts), ≤3/day. Per-function cost logging + budget alarms in turn_log from day one (consumption-cost governance is a documented failure axis — https://www.salesforceben.com/4-ways-salesforce-customers-risk-losing-millions-because-of-ai-agents/). Defer GEPA/DSPy prompt optimization until ~300 judge-labeled conversations exist.
**Rejected:** Langfuse v3 self-host (ops-heavy for 1–3 people); cloud eval SaaS (PHI leaves droplet; BAA = enterprise tiers); Postgres-only with no trace lens (debugging cost).

### L15 · Function-as-package framework — BUILD (small, load-bearing)
**Choice:** Formalize the package contract the brief demands: a function package = `{intent seed fragment, task module, policy/prompt fragment, write-action manifest (which CrmWriteGate actions + autonomy defaults), optional cadence/saga definitions, eval cases, cost budget}` in one directory, installed by a registrar that (a) merges seeds and triggers intent_seeder + **dispatch-table hot-reload endpoint on rag-api** (killing the restart requirement), (b) registers the task with an **explicit-claim registry** — collision on overlapping `handled_intents` is a startup error; unclaimed intents route to an explicit `fallback` handler that logs loudly, never silently to customer_service, (c) registers evals with the harness and cadences with L6.
**Rationale:** this is the difference between "extensibility exists" (today: YAML + registry with silent first-match) and "new function ships as a package with zero central-dispatch edits" (brief §3, first-class criterion). It's also the layer that makes F5 a real seam. Pattern imported from Agentforce's topic/action/guardrail packaging + plan-level evals (https://engineering.salesforce.com/inside-the-brain-of-agentforce-revealing-the-atlas-reasoning-engine/).
**Rejected:** leaving the silent registry (recon flags it as a trap); a plugin marketplace abstraction (YAGNI at 1 team).

### L16 · Data platform & ops — REUSE (extend)
**Choice:** Same droplet, same `pgvector/pgvector:pg16` image (DBOS needs no extension; AGE deliberately deferred to keep it that way); Alembic migrations from Stage 0 with the initdb SQL frozen as baseline; nightly pg_dump to DO Spaces or equivalent (PHI-bearing DB currently has no stated backup posture — fix); secrets stay in `.env` with a rotation checklist; staging = MockCrmAdapter + Zoho sandbox + a WAHA/Cloud API test number; compose stack unchanged except +Phoenix, −Langfuse.
**Rationale:** the droplet has 10× headroom by load math (65 leads/day peak ≈ single-digit jobs/minute — R2); a migration story is non-negotiable once operator scope adds ~12 tables.
**Rejected:** Supabase re-platform (C5's thesis; adds a vendor + migration for queues/cron DBOS already covers); Kubernetes/managed containers (gold-plating).

---

## 5. Precision & exactly-once design (brief §3's explicit requirement)

The honest statement: against external APIs (Meta, Zoho) literal exactly-once does not exist; C1 delivers **effectively-once** — at-least-once execution with deterministic idempotency guards at every seam — plus deterministic-only money paths. Concretely:

1. **Inbound:** `intake_events` inbox, UNIQUE `(source, source_event_id)`; webhook ACKs only after durable insert; processing is a DBOS workflow keyed to the inbox row → redeliveries and restarts cannot double-process (kills `fsm.py:39`).
2. **Outbound:** `send_intents` outbox row written *before* any transport call, keyed `(enrollment_id, step_no)` for cadences and `(turn_id, seq)` for replies; a send step first checks intent status; Cloud API message-id stored on success; a content-hash dedup window guards WAHA (which has no idempotency support — R5 open question, mitigated not solved).
3. **CRM writes:** deterministic idempotency key `hash(turn_id|action|canonical_params)` in `crm_write_log` checked before dispatch; Zoho-side belt-and-suspenders via upsert `duplicate_check_fields`; pre-write snapshots make undo a compensating update; deletes are impossible at OAuth-scope level.
4. **Money:** prices only from `facts/prices.yaml` + Products module by id; quote totals computed twice (composer + verifier) and matched before send; regex output guard blocks unknown dollar amounts in any LLM-composed reply; discount = escalation, never a write.
5. **Health claims:** approved-claims registry + classifier on 100% of outbound sales turns (sampling cannot catch rare violations — R4).
6. **Verification loop:** `--mode crm` read-after-write evals in CI/sandbox + nightly production reconciliation; any mismatch pages the team group and flips the action type to ask-first.

---

## 6. Staged rollout (value-first; weeks 1–3 on the current droplet)

| Stage | Weeks | Ships (user-visible in bold) | Notes |
|---|---|---|---|
| 0 — Harden + cutover | 1–2 | Punch-list fixes (inbox dedup, HMAC fail-closed, constant-time auth, backpressure, shared clients, safe mute, canned greetings); `facts/prices.yaml` + dollar guard; Alembic baseline; **RAG + episode memory wired into agent-core fallback**; WAHA pairing + smoke test; **OpenClaw→agent-core cutover** (one runtime, one policy surface) | All on current droplet; the cutover retires the duplicated persona/price surface — a live drift risk today |
| 1 — First-touch value | 2–3 | Cloud API number live; intake bus (`/webhooks/{manychat,zoho}`) + identity broker MVP; **every new lead gets Gutty first contact within minutes** (event-triggered; the single highest-value F8 slice); **IG default-reply capture → short reply + wa.me ref-token funnel + CRM insert** (F10 MVP) | LeadChain pilot for Meta Lead Ads latency/fidelity (UNVERIFIED — measure against the minutes bar) |
| 2 — Cadence + shadow | 4–6 | DBOS in (license gate passed) ; full cadence engine (touches 2..N, consent ledger, suppression, US branch, TOUCH_CALL→Zoho Task); handoff context package + sweeper; qualification slots live (F9 mode 3, shadow-action logging on); **CrmWriteGate in shadow mode** against Zoho sandbox | Nothing autonomous writes to prod Zoho yet |
| 3 — Operator authority | 7–9 | CrmWriteGate ladder: ask-first → auto per action type as gates pass (F6); **presupuesto end-to-end** (Quotes + local PDF + WhatsApp doc) in mode 3; **F4 weekly outbound** to opted-in existing customers; nightly write reconciliation | Estimates keep human confirmation longest |
| 4 — Knowledge + learning | 10–12 | Drive connector + Spanish tsconfig migration + contextual retrieval re-index; tacit interview loop starts; **F12 loop closes** (proposer/review/applier + 100% sales-turn judge); Phoenix OTel swap (Langfuse v2 retired) | ~$1 re-index; ≤2h/week review cadence begins |
| 5 — Graduation + seams | Months 4–6 | Mode-2 graduation for consultation plans (gates §4-L9); legacy number migration completes, WAHA retired; AGE multi-hop eval gate decided; voice pilot decision (Calling API seam already stubbed); optional Chatwoot decision | Everything here is gated, nothing assumed |

---

## 7. Monthly cost model @ 1,000 leads/mo

Assumptions: ~10,000 conversational turns/mo (1,000 leads × ~8 turns + existing patients), ~40% LLM-composed; cadence avg 2 paid marketing templates/lead (window engineering: CTWA 72h free + in-window replies free); F4 ≈ 1,000 marketing sends/mo to opted-in patients; quote/status utility sends ≈ 1,000/mo. Meta RoLatAm rates: marketing ≈ $0.0625/msg, utility ≈ $0.008/msg (secondary-corroborated 2026-07 rate card; brief's $0.074 stale — https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing; primary CSV verification is an open item).

| Item | $/mo | Basis |
|---|---|---|
| Droplet (existing, sized up to 8GB if Phoenix needs it) | 48 | DO pricing; DBOS+Phoenix add no service beyond one container |
| Backups/object storage | 5 | nightly pg_dump to Spaces |
| Zoho "Gutty" user license | 14–52 | dedicated write-attribution identity (R3) |
| WhatsApp templates — cadence marketing (2,000 × $0.0625) | 125 | L6 window-aware design |
| WhatsApp templates — F4 outbound (1,000 × $0.0625) | 63 | opted-in patient base, batched under tier limits |
| WhatsApp utility (2,000 × $0.008) | 16 | quote delivery, confirmations |
| LLM — conversational (4,000 composed turns ≈ 10M in / 1M out, Gemini 3.5 Flash $1.50/$9) | ~24 | Haiku 4.5 variant ≈ $15; eval decides |
| LLM — slot extraction + claims classifier + escalations (Haiku/Sonnet mix) | ~15 | schema-constrained small calls |
| LLM — judge on 100% composed sales turns + nightly Batch jobs (redacted, 50% off) | ~15 | R9 math |
| Embeddings (OpenAI 1536-dim, queries + re-index amortized) | ~5 | contextual re-index ≈ $1/run |
| **Total** | **≈ $330–370/mo all-in** | **Infra-only ≈ $70–105/mo — well inside the $150–350 target (which excludes tokens/templates)** |

Sensitivity: template spend is the dominant variable ($130–320 band depending on CTWA share and reply rates — R2); a shift of ad spend toward Click-to-WhatsApp pushes it to the low end. One-time costs: ~10–12 engineer-weeks across Stages 0–4 (the build is additive modules, no migration of working components), plus $0 licenses (DBOS verified MIT; Phoenix ELv2 free for internal self-host; Presidio MIT).

---

## 8. Top 5 risks

| # | Risk | Sev | Mitigation |
|---|---|---|---|
| 1 | **WAHA ban / loss of the Gutty number before cutover** — proactive outbound on unofficial clients is Meta's ban fingerprint; 2025-26 ban waves documented | High | All business-initiated sends on official Cloud API from Stage 1; WAHA inbound-reactive only with scheduled retirement; state keyed on E.164 in Postgres so a number event costs the phone history, not the brain; accelerate legacy-number migration |
| 2 | **Effectively-once retrofit fails in the tails** — DBOS steps are at-least-once; WAHA has no idempotency support; a subtle guard bug = double quote or double send (the exact failure the brief forbids) | High | Send-intent outbox + deterministic keys at every seam (§5); chaos tests (kill agent-core mid-saga) in Stage 2 acceptance; `--mode crm` read-after-write evals + nightly reconciliation; DBOS integration spike at Stage 0 (license already verified MIT) with the hand-rolled SKIP-LOCKED worker as a priced fallback |
| 3 | **Autonomy erodes team trust** — a 92%-correct agent was abandoned in 2 weeks because visible errors destroyed rep trust (Agentforce field data); dirty CRM data is the documented killer | High | Hygiene before autonomy (identity broker + dedup ship before any auto write); ≥2-week shadow per action type against the sandbox; write budgets + kill-switch to ask-first; ledger-based undo; Gutty's writes attributed to its own Zoho user so humans can audit natively |
| 4 | **Single-process concentration** — ingress, FSM, DBOS workflows, and cadence all in one FastAPI process on one droplet; a crash-loop stalls both reactive and proactive work | Med | Durable inbox/outbox means restarts lose nothing (recovery is DBOS's core property); bounded queues + health-restart; scale-out path = additional DBOS workers on the same Postgres; documented escape hatch to Temporal Cloud (HIPAA BAA) if scope outgrows the library model |
| 5 | **Compliance residuals** — VE-Spanish redaction unsolved to a certifiable standard; Anthropic BAA availability for a small non-US company unconfirmed; WhatsApp can never be literally HIPAA-compliant | Med | Content-gated class split makes the care path narrow and auditable; redaction is defense-in-depth with an in-house VE eval set, never the boundary; confirm Anthropic BAA + Zoho BAA in writing at Stage 0 (both are launch gates for care-class LLM turns and health-field writes); PHI never in templates; honest documentation of the transport limitation |

---

## 9. The −80% logistics story (functions → hours)

No time-study exists; the baseline below is a stated assumption to be validated in week 1 (one-week manual time log by the logistics team) and re-measured monthly via turn_log + the "resolved-without-human" KPI (the market's own outcome metric — https://www.hubspot.com/company-news/hubspots-customer-agent-and-prospecting-agent-now-you-pay-when-the-task-is-complete).

Assumed current logistics workload at ~50 leads/day + patient base (team total ≈ 9.5 h/day):

| Work | Today (h/day) | After C1 | Mechanism | Residual human (h/day) |
|---|---|---|---|---|
| First contact + follow-up chasing on new leads | 3.0 | F8 cadence: 100% first touch <5 min, touches 2..N automatic, replies routed to sales module | 0.3 (cadence exceptions) |
| FAQ / status / logistics answering | 2.0 | F1 deterministic FAQ + RAG + memory; F3 mutes on handoff | 0.4 (edge cases) |
| Presupuesto creation + sending + chasing | 1.0 | F2 saga: compose→Quote→PDF→send→follow-up, deterministic amounts | 0.1 (approval while in mode 3) |
| CRM data entry, linking, dedup, stage moves | 1.5 | F6 WriteGate autonomy + F7 identity broker; hygiene automated | 0.2 (review queue) |
| Weekly outbound (reviews, repurchase, referrals) | 0.5 | F4 scheduled cadences | 0.05 |
| MKT inbox triage (IG) | 1.0 | F10 capture→reply→funnel→CRM | 0.2 (uncaught DMs) |
| Qualification + tee-up before human selling | 0.5 | F9 slots + context package | 0.05 |
| **Total** | **9.5** | | **≈ 1.3 + selling/payment-verification time** |

Automatable-work reduction ≈ 86%; with the retained high-judgment work (selling post-tee-up, payment verification, escalations) the team lands at roughly **-80% of logistics load**, which is the mission target — achieved through coverage and speed (the evidentially-supported wins), not through AI out-closing humans (which the evidence says not to promise — R4). María José's quality-owner load is designed at ≤2 h/week (L14).

---

## 10. Open questions carried forward (for judges / red-team)

1. ~~DBOS Transact license~~ — **resolved 2026-07-08: verified MIT, actively maintained (v2.26.0, 2026-06-30)**. Remaining: 2-day Stage-0 integration spike + vendor-viability judgment (fallback priced).
2. LeadChain real latency/fidelity vs the minutes bar (Stage-1 pilot; direct Meta app is the escalation).
3. Anthropic BAA execution for a small non-US entity; Zoho BAA scope over sandbox + Zia (writing required).
4. Primary verification of the 2026-07 Meta RoLatAm rate card (CSV download; figures used are secondary-corroborated).
5. Share of +1 US numbers in the base (sizes the F4/F8 US-branch impact).
6. Whether the WhatsApp Business App runs the current Gutty number (Coexistence eligibility at migration).
7. VE-Spanish redaction recall — in-house eval set is the only way to know (built Stage 4).

## 11. Why C1 beats its rivals at this scope (advocate's summary)

- **vs C2 (framework ground-up):** every framework evaluated still lacks cadence scheduling, CRM write-gating, and identity resolution — the actual missing 80% — while discarding a deployed, understood spine. C1 spends the rewrite budget on the missing subsystems instead.
- **vs C3 (OSS best-of-breed):** n8n/Chatwoot/etc. fragment agent policy across brains and add services a 1–3 person team must operate; C1 adds one library and one container.
- **vs C4 (Zoho-native):** a Zoho-native conversational WhatsApp operator does not exist (CRM's WhatsApp integration explicitly does not support chatbots; Zia operates on email; SalesIQ requires a Meta Cloud number *and* abandons our RAG/intents — Zoho recon). C1 still adopts Zoho's best ideas: agent identity, upsert dedup, Timeline audit.
- **vs C5 (managed-serverless):** re-platforming the DB/queues/cron to Supabase buys managed versions of exactly the things DBOS gives us in-process for $0 on infrastructure we already run — and adds a vendor to the PHI story.
- **Honesty clause:** if the Stage-0 DBOS integration spike fails (license risk is now retired — verified MIT) AND the hand-rolled worker estimate doubles, the durable-execution premise weakens and C2-on-Temporal becomes the serious contender; that is the falsifiable core of this candidate.
