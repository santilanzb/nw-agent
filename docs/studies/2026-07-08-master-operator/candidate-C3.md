# Candidate C3 — "OSS Best-of-Breed": Compose Mature Products, Own Only the Brain

> **Study:** Cerebro Gutty v3 — Master Operator · **Date:** 2026-07-08 · **Composer:** C3 architect
> **Verdict claim:** at operator scope, most of what is missing (F2–F10) is **commodity capability that mature OSS products have already hardened over years of production use**: an omnichannel inbox with human handoff and agent-bot API (Chatwoot, MIT), an integration/automation runtime (n8n), an LLM gateway (LiteLLM, MIT), a durable-execution library (DBOS Transact, MIT), a PDF renderer (Gotenberg, MIT), OTel-native observability (Arize Phoenix). C3 composes these around the two assets genuinely worth keeping — the intent-classifier+RAG spine and the Postgres data plane — and confines owned code to the three things no product sells: the **Gutty conversational brain**, the **CrmWriteGate**, and the **identity broker**. Least custom code to maintain = fewest owned bugs for a 1–3 person team.
> Sources: `BRIEF.md`, repo recon `recon-code-seams.md`, research packs R1–R10 (same directory), plus component verification done 2026-07-08 (URLs inline). Unverified items are flagged.

---

## 0. Thesis

The brief's scope expansion is not conversational — it is **operational**. F3 demands a *real* ticket system; F6–F8 demand an intake bus, a cadence engine, template transport, and audit surfaces; F10 demands an IG inbox; F12 demands review tooling. A tiny team that hand-builds inbox UIs, ticket lifecycles, transport wiring, template management, provider routers, schedulers, and trace viewers will spend its entire build budget on plumbing that Chatwoot, LiteLLM, DBOS, and Phoenix ship today with thousands of production deployments behind them.

C3's core bet, stated falsifiably:

1. **The differentiated 20% is small and known.** The Gutty brain (turn loop + task modules on the ~99%-accurate classifier spine), the typed Zoho write gate, the identity broker, the deterministic presupuesto composer, and the privacy gate. Everything R1/R3 says "must be owned code under every candidate" *is* owned here — C3 does not outsource judgment, money, or identity.
2. **The commodity 80% should be community-maintained.** Every hour NOT spent maintaining an inbox UI, WhatsApp media handling, Sidekiq retry semantics, or a spend-tracking dashboard is an hour available for evals, knowledge curation, and the autonomy ladder — the activities that actually produce the −80%.
3. **Humans need a console, not group commands.** F3 says "real ticket system + handoff." The current design (and C1's evolution of it) coordinates asesoras through `@Gutty tomo +phone` WhatsApp group commands and Zoho Notes. That is a CLI for salespeople. Chatwoot gives asesoras assignment, teams, labels, private notes, canned responses, contact history across WhatsApp+IG, CSAT, and agent reports — **for zero lines of owned code** (https://github.com/chatwoot/chatwoot, MIT). The −80% target is capped by human throughput on the remaining 20% of conversations; a real console is what raises that throughput.

Honesty requirement up front: best-of-breed buys maintenance relief at the price of **integration seams and a heavier container stack**. §12 names every seam and what breaks there; §13 says where C3 loses to C1.

---

## 1. Component verdicts (verified 2026-07-08)

| Component | Role in C3 | License / stack | Verification |
|---|---|---|---|
| **Chatwoot** | Omnichannel inbox, ticket lifecycle, human console, WhatsApp Cloud API + Instagram channels, Agent Bot ingress | MIT; Rails + Vue + Postgres + Redis + Sidekiq | https://github.com/chatwoot/chatwoot (MIT, channels list incl. WhatsApp + Instagram). WhatsApp Cloud API channel with embedded signup or manual Meta setup: https://www.chatwoot.com/hc/user-guide/articles/1677832735-how-to-setup-a-whats_app-channel, https://developers.chatwoot.com/self-hosted/configuration/features/integrations/whatsapp-embedded-signup. Agent Bot: receives `message_created` webhooks, replies via Create-Message API, hands off by toggling conversation `pending→open`: https://www.chatwoot.com/docs/product/others/agent-bots. Chatwoot even documents the exact wa_id quirks (BR/MX/AR) our identity broker must handle: https://www.chatwoot.com/hc/user-guide/articles/1758697086-inconsistencies-for-whats_app-numbers-in-brazil-mexico-and-argentina — evidence it is battle-tested on precisely our channel. |
| **DBOS Transact (Python)** | Durable execution: cadence scheduling, multi-day sagas, exactly-once event processing, durable queues — as a library inside the brain | **MIT** (verified — closes R5's open license question); "no additional infrastructure besides Postgres" | https://github.com/dbos-inc/dbos-transact-py — durable workflows checkpointed in Postgres, cron-syntax scheduled workflows, durable sleep for days/weeks, queues with concurrency/rate limits, "exactly-once event processing" for webhooks |
| **LiteLLM proxy** | LLM gateway: class-based routing (PHI→Anthropic sync BAA; marketing→Gemini 3.5 Flash), fallbacks, per-key budgets + spend tracking, cost alarms | MIT core (enterprise features under commercial license — not needed) | https://github.com/BerriAI/litellm — virtual keys, spend tracking, load balancing, fallbacks; Anthropic, Gemini AND Vertex AI among 100+ providers |
| **n8n** | Integration glue ONLY: intake webhook normalization, Zoho/Drive connectors, reconciliation crons, reports. Never state, never policy, never cadence timing | Sustainable Use License (fair-code; free self-hosted) — per R2 | https://docs.n8n.io/sustainable-use-license/ (R2); production posture = Postgres + Redis queue mode |
| **Gotenberg** | HTML→PDF rendering for presupuestos and F5 plan PDFs (Zoho v8 cannot emit the rendered quote PDF — Zoho recon) | MIT; single Docker container, headless Chromium | https://gotenberg.dev/ — verified MIT, HTML/Markdown→PDF API, 68M+ Docker pulls |
| **Arize Phoenix** | Traces + evals + human annotation, OTel-native, single container on existing Postgres | Elastic 2.0 (free for internal self-hosted use) — per R9 | https://github.com/arize-ai/phoenix (R9: v17.20.0 as of 2026-07-07) |
| **Presidio + GLiNER2-PII** | Self-hosted redaction before derived stores (Spanish-VE custom recognizers) | OSS, self-hosted — per R8 | https://microsoft.github.io/presidio/supported_entities/; https://arxiv.org/abs/2605.09973 |

UNVERIFIED details flagged for Stage-1 measurement: (a) Chatwoot Agent-Bot webhook **retry/delivery semantics** under bot downtime — mitigated by enqueue-then-ACK + reconciliation poll of the Chatwoot conversations API; (b) API-initiated **template sends with `template_params`** through the Chatwoot WhatsApp channel (dashboard template sending is documented; API parameter shape needs a live test — fallback: cadence sends go Cloud-API-direct, §5-L7); (c) Chatwoot self-host RAM footprint (community guidance ~2 vCPU/4 GB class for this volume — UNVERIFIED exact figure, sized into the cost model with headroom).

---

## 2. Target architecture

```
   CHANNELS                                    HUMANS (asesoras + María José)
   WhatsApp Cloud API ──┐                      Chatwoot UI: inbox · assignment ·
   (new number now;     │                      labels · private notes · canned
   legacy Gutty number  │                      responses · CSAT · agent reports
   migrates at cutover) │                                   ▲
   Instagram DM ────────┤                                   │
                        ▼                                   │
              ┌──── Chatwoot (self-hosted, MIT) ────────────┴──┐
              │  conversations = tickets (pending→open→resolved)│
              │  WhatsApp Cloud channel · IG channel · contacts │
              └──────┬──────────────────────────▲──────────────┘
       Agent Bot webhook (message_created)      │ Create-Message API
                     ▼                          │ (replies, templates*, PDFs)
   ┌────────────── Gutty Brain (FastAPI, owned, slim agent-core) ─────────────┐
   │ intake_events inbox (UNIQUE source+event_id)  ← n8n intake flows        │
   │ Identity Broker: E.164/wa_id/email/IGSID canonical keys → Zoho upsert   │
   │ TurnFSM (reactive router, kept) → privacy gate (marketing|care)         │
   │   → rag-api /v1/classify_intent → TaskRegistry (explicit claims)        │
   │     customer_service · sales(F9) · presupuesto(F2) · crm_ops(F6)        │
   │     mkt_inbox(F10) · nutrition_followup(F5 seam)                        │
   │ DBOS Transact (MIT, in-process): @scheduled cadence ticks · durable     │
   │   sagas (presupuesto, F5 sequences) · send_intents outbox · retention   │
   └───┬───────────────┬─────────────────────┬───────────────────┬──────────┘
       ▼               ▼                     ▼                   ▼
   LiteLLM proxy   rag-api :8081        crm-adapter :8082    Gotenberg
   care→Anthropic  hybrid RRF +         parametrized COQL    HTML→PDF
   sync (BAA)      Spanish tsconfig +   reads + CrmWriteGate (presupuestos,
   mkt→Gemini 3.5  contextual retrieval (typed actions, WAL, plan PDFs)
   Flash (eval-    + intent classifier  autonomy ladder)
   gated) budgets/       │                    │
   alarms per fn         ▼                    ▼
   ┌── n8n (glue only, flows in git): ManyChat External Request · Zoho
   │   workflow-rule webhook · LeadChain lead landing · Drive changes.list
   │   poll → ingest-worker · nightly reconciliation · stale-doc report
   └──────────────────────────────────────────────────────────────────
   Postgres (one instance; separate DBs: app+DBOS / chatwoot / n8n):
   knowledge_chunks · intent_vectors · turn_log · learning_queue ·
   identity_registry · intake_events · cadence_defs/enrollments ·
   consent_ledger · suppression_list · send_intents · crm_write_log ·
   quotes_ledger · claims_registry · DBOS system tables
   Phoenix (OTel traces, single container) · Zoho CRM = system of record
```

\* Template sends through Chatwoot API are UNVERIFIED (§1); the brain holds a direct Cloud-API send client as designed fallback either way — Chatwoot is a **console and hub, never the only path to the wire**.

---

## 3. F1–F12 coverage map

| Fn | Status today (recon) | C3 mechanism | Owned code? |
|---|---|---|---|
| F1 Customer service | Built but no RAG/history in agent-core fallback; media dropped (`waha.py:42`) | Keep classifier→FAQ→LLM pipeline; wire `/v1/retrieve` + history into CustomerServiceTask; canned greetings (kill `customer_service.py:172-209` LLM burn); **media arrives via Chatwoot** (its channel handles WhatsApp media natively) — images/docs attached to the conversation for humans even before the bot understands them; voice notes deflected politely pending a PHI-safe transcription decision (R4) | Brain task module (reuse) |
| F2 Auto presupuesto | Zero code | Deterministic composer: Products **id-allowlist** → Zoho `Quotes` (Quote_Stage lifecycle) via CrmWriteGate → **Gotenberg** renders branded HTML→PDF (Zoho v8 has no rendered-PDF fetch endpoint — https://www.zoho.com/crm/developer/docs/api/v8/inventory_templates.html) → document send to the patient's conversation → all one DBOS saga with deterministic amount check + `quotes_ledger` idempotency. Zoho Books excluded per brief §4b. | Composer + saga (~500 LOC); PDF/transport bought |
| F3 Real ticket + handoff | handoff_state machine + group commands | **Chatwoot conversations ARE the tickets**: bot runs while `pending`; deterministic escalation triggers toggle `open` + assign team/label + post a context package (qualification slots, cadence history, last-N turns) as a private note (https://www.chatwoot.com/docs/product/others/agent-bots). Claim = assignment; resume = back to `pending`. Existing `handoff_state` table kept as the brain's mute authority (fail-closed, fixing `fsm.py:103-106`); Zoho Note still written for CRM trace. Group commands retired after transition. | Escalation logic only; lifecycle/UI bought |
| F4 Weekly outbound | Zero substrate | Cadence engine (L7) with `weekly_outbound` cadence defs: review nudges, repurchase, referrals; marketing templates via Cloud API; **double opt-in consent ledger + suppression list checked synchronously**; batching under Meta messaging-limit tiers (https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits) | Cadence tables + DBOS jobs (shared with F8) |
| F5 Nutrition follow-up seam | Schema-only stubs | Function package (§8) = seeds + task module + **DBOS cadence/saga defs** + eval cases; multi-day = DBOS durable sleep; plan PDFs reuse Gotenberg + document send. Seam proven in Stage 4 by building the package skeleton. | Package contract |
| F6 Master CRM operator | Reads + Notes only; f-string COQL | **CrmWriteGate** (owned, L9): enumerated typed actions over Leads/Contacts/Deals(stage)/Quotes/Tasks/Notes; `crm_write_log` WAL with pre-write snapshots + deterministic idempotency keys; staged autonomy shadow→ask-first→auto per action type; deterministic write budgets (~30/hr, 200/day) whose breach flips everything to ask-first; parametrized COQL precondition; dedicated Gutty Zoho user for attribution (R3). Hygiene (dedup/linking) ships **before** autonomy — the Agentforce dirty-data lesson (https://solutions4sf.com/blog/agentforce-b2b-reality-check/). | Fully owned — never outsourced |
| F7 Multi-source intake | Single WAHA ingress | n8n intake flows normalize: (a) ManyChat External Request (https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-request), (b) Meta Lead Ads via Zoho LeadChain, (c) existing-automation/manual records via one Zoho workflow-rule webhook `{module, record_id, event}` with integration-user loop guard, (d) reconciliation lanes (nightly Meta bulk read, ManyChat Sheets export — ManyChat has **no subscriber-enumeration API**, R1). All flows POST to ONE brain endpoint feeding `intake_events`; **identity broker is owned Postgres** (canonical keys, unique constraints, advisory-lock merges, Zoho upsert on `duplicate_check_fields`, fuzzy→human review). n8n transforms; it never decides. | Broker owned; connectors bought |
| F8 Cadence "toques" | Zero substrate | First touch **event-triggered at intake** (<5 min; 21× qualify odds — https://25649.fs1.hubspotusercontent-na2.net/hub/25649/file-13535879-pdf/docs/mit_study.pdf); touches 2..N = DBOS scheduled workflows over versioned `cadence_defs` + per-lead `cadence_enrollments` (state machine active→replied/opted_out/exhausted/paused_handoff); reply kills pending touches synchronously in the inbound path; **US(+1) branch** (marketing templates hard-blocked to US — https://www.messagecentral.com/blog/whatsapp-marketing-usa-what-is-allowed); status-webhook-driven with reschedule on error 131049 (per-user marketing cap, R2). TOUCH_CALL task type creates a prepared Zoho Task + Chatwoot label today; voice agent later (L1 seam). | Cadence state + logic owned; scheduler substrate = DBOS |
| F9 Sales agent | Only handoff_discount intent | Sales TaskModule: 7-slot SPICED-lite qualification (code-controlled, LLM-extracted, persisted via WriteGate; marketing/health slot-tier split); objection intents with one-reframe-then-escalate; precomputed price decompositions from `facts/prices.yaml` (never LLM arithmetic); **claims registry + claims classifier on 100% of outbound sales turns** (FTC AI-health scrutiny active — https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance); mode-3-as-shadow-mode: log recommended action at tee-up, asesora's Chatwoot decision = free ground-truth label; graduation gates per product (offline suite → ≥50 shadow convs ≥90% agreement → 2-wk 10% canary with 100% payment-link review → standing auto-demote) (R4) | Fully owned |
| F10 MKT inbox relief | Zero IG code | Two lanes: (a) ManyChat-caught DMs → External Request → intake bus → short reply + **wa.me ref-token link** (doubles as the only deterministic IGSID↔wa_id join — https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/user-profile); (b) **uncaught IG DMs land in Chatwoot's Instagram channel inbox** — bot posts a suggested short reply + funnel link as private note (or auto-sends once graduated), humans see everything in the same console. IG stays intake-only per brief; native IG conversation later = enabling the bot on that channel (config, not code). | Funnel logic owned; IG inbox bought |
| F11 Knowledge breadth | Manual markdown CLI | Reuse rag-api/pgvector; **Spanish+unaccent tsconfig migration + contextual retrieval at ingest (~$1/full re-index — https://www.anthropic.com/engineering/contextual-retrieval)**; Drive: n8n schedule polls `changes.list` on one curated shared folder → triggers ingest-worker run (https://developers.google.com/workspace/drive/api/guides/manage-changes); website sitemap+hash scrape via n8n; tacit loop: monthly CDM interview → LLM-drafted SOP → owner sign-off → Drive (R6); `facts/prices.yaml` single source for all price strings + dollar-amount output guard. Reranker deferred until evals prove misses (PHI/DPA gate — R6). | Ingest-worker reused; connectors = n8n |
| F12 Self-learning | Schema only | Keep turn_log + learning_queue as **authoritative system of record** (R9); Haiku-class judge on 100% of LLM-composed sales turns (~$5–20/mo); `--mode crm` added to eval/run_eval.py (COQL read-after-write assertions vs Zoho sandbox + nightly prod write reconciliation); weekly clustered review ≤2h; reseeds via intent_seeder with eval-regression auto-revert; **Phoenix annotation UI** if Markdown queue fails the quality owner | Loop owned; tooling bought |

---

## 4. The 16-layer stack

Legend: **REUSE** (existing repo asset, kept/hardened) · **HYBRID** (existing + significant addition) · **BUILD** (new owned code) · **BUY** (external service or adopted OSS product — "buy" here means *adopt and operate, don't write*).

### L1 · WhatsApp + voice-seam transport — BUY (Meta Cloud API direct)
**Choice:** New Cloud API number immediately (via Chatwoot embedded signup) for all business-initiated sends; legacy Gutty number migrates at cutover (Coexistence if Business-App-eligible, else hard migration — state lives in Postgres keyed on E.164: https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/migrate-existing-whatsapp-number-to-a-business-account/). WAHA demoted to legacy-inbound bridge with scheduled retirement. Voice seam: reserved `calls` webhook route + TOUCH_CALL task type now; WhatsApp Business Calling API (GA) + Pipecat-class agent at Fase 2+ (https://docs.pipecat.ai/pipecat/features/whatsapp).
**Rationale:** WAHA cannot send templates and proactive outbound over unofficial clients is Meta's textbook ban profile with documented 2025-26 ban waves (https://github.com/devlikeapro/waha/issues/1362; https://github.com/WhiskeySockets/Baileys/issues/1869). Cloud API is the only path to template legality, `ctwa_clid` attribution, and voice.
**Rejected:** WAHA-only (existential ban risk); Twilio BSP (+$0.005–0.010/msg buys managed voice we don't need yet — revisit at voice stage); 360dialog (€49/mo wins only ≳10k paid msgs/mo — https://360dialog.com/pricing).

### L2 · Omnichannel inbox, tickets, human console — BUY (Chatwoot self-hosted, MIT)
**Choice:** Chatwoot as messaging hub and the asesoras' working surface: WhatsApp Cloud channel, Instagram channel, conversation lifecycle (`pending`=bot, `open`=human, `resolved`), teams, labels, assignment, private notes, canned responses, contact timeline, CSAT, agent reports. The Gutty brain attaches as an **Agent Bot** (https://www.chatwoot.com/docs/product/others/agent-bots).
**Rationale:** This is the single largest code-avoidance in the study: F3's "real ticket system," F10's IG inbox, media handling, and the human-throughput UX all become configuration. It also gives management the reporting needed to *measure* the −80% (agent workload reports, resolution counts) for free. Self-hosted ⇒ PHI stays on the droplet.
**Rejected:** BUILD custom handoff console (C1's posture — months of UI work or a permanent group-command CLI that caps human throughput); Zoho Desk/SalesIQ (SaaS PHI egress, second policy brain — R10/Zoho recon); FreeScout/Zammad (no comparable WhatsApp-Cloud+IG+agent-bot maturity — UNVERIFIED depth, not pursued); Botmaker/Treble-class LatAm SaaS (generic LLM, no BAA posture, brain locked in vendor — R10).

### L3 · Conversational brain (turn loop) — REUSE + BUILD (slim agent-core behind the Agent Bot)
**Choice:** Keep the hand-rolled TurnFSM + TaskRegistry as the reactive router — re-pointed from the WAHA webhook to the Chatwoot Agent-Bot webhook via a transport-neutral `InboundEvent` normalizer. Fix the punch-list items in passing (constant-time key compare, Postgres inbox dedup replacing `_SEEN`, fail-closed mute, bounded ingress, explicit-claim registry).
**Rationale:** 2026 production consensus for customer-facing agents is a thin owned loop (https://github.com/humanlayer/12-factor-agents; https://www.anthropic.com/research/building-effective-agents); routing scale lives in the classifier, not code (R5). C3 is "least custom code," not "no custom code" — the brain is precisely the code worth owning.
**Rejected:** LangGraph rewrite (serialization footguns, worse debugging, still no scheduler — R5); OpenAI Agents SDK (model lock-in); Mastra (TS fragmentation); Botpress/Rasa/Typebot-class OSS conversational platforms (genuinely tempting for C3's angle, but they impose their own NLU/flow model over our proven embedding classifier, fragment persona policy, and none solves CRM writes or cadences — they'd *add* a brain, not remove code).

### L4 · Intent routing — REUSE (classifier spine, untouched)
**Choice:** `intents/intent_seeds.yaml` + `intent_vectors` + rag-api `/v1/classify_intent` (~99% on seeds) with dispatch hot-reload added; new objection/sales intents added as seed packs.
**Rationale:** The single best asset in the repo; every candidate keeps it. Thresholded execute/clarify/fallback with tie-break already implements the deterministic-first constraint.
**Rejected:** LLM-based routing (cost/latency/nondeterminism on every turn); vendor NLU (Dialogflow/Lex — egress, Spanish-VE control).

### L5 · LLM gateway — BUY (LiteLLM proxy, MIT)
**Choice:** LiteLLM as the one place models are named: virtual keys per function package, **class-based routing** (care→Anthropic synchronous Messages under BAA — Batch contractually excluded per https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers; marketing→Gemini 3.5 Flash pending the §4b eval gate, via Vertex+BAA if it ever touches care), fallbacks, per-key budgets + spend alarms (the R10 cost-governance rule as configuration).
**Rationale:** Solves the `config.py:15-16` no-provider-seam punch-list item, the §4b model-preference question (a config change after `eval/run_eval.py` Spanish-VE runs, not a refactor), and per-function cost logging — all without owning a router.
**Rejected:** hand-rolled provider seam (owned code for a solved problem); OpenRouter (data egress, no BAA); direct per-provider SDKs scattered through task modules (the current anti-pattern).

### L6 · Durable execution + exactly-once substrate — BUY (DBOS Transact, MIT) + BUILD (ledgers)
**Choice:** DBOS Transact embedded in the brain: `@DBOS.scheduled` for cadence ticks/retention/reconciliation, durable sleep for multi-day sequences, checkpointed steps + durable queues for sagas; paired with owned Postgres ledgers — `intake_events` inbox (UNIQUE `source+source_event_id`), `send_intents` outbox keyed `(enrollment_id, step_no)` / `(turn_id, seq)` written **before** any transport call, `crm_write_log` WAL.
**Rationale:** R5's recommendation, now license-deconfirmed: **MIT, verified** (https://github.com/dbos-inc/dbos-transact-py), zero infra beyond the Postgres already deployed. Steps are at-least-once ⇒ the honest guarantee is *effectively-once via idempotency guards* — the strongest any candidate can offer against Zoho/Meta/Chatwoot APIs, none of which accept idempotency keys.
**Rejected:** Temporal (multi-service cluster or Cloud payload egress; ~3 orders of magnitude over-scoped — R5); Restate (second stateful runtime + BSL — R5); n8n schedules for business timing (silently skips missed ticks — R2); pg_cron/pgmq (custom pg image + restart, no backoff policy — R2); hand-rolled SKIP-LOCKED worker (the documented fallback if DBOS disappoints, ~2 weeks).

### L7 · Cadence engine (F8 + F4) — BUILD (state) on L6 (substrate)
**Choice:** Versioned `cadence_defs` separate from per-lead `cadence_enrollments` (explicit state machine, `next_run_at`, exit-on-reply in the inbound path); consent ledger + suppression list checked synchronously; window engineering as architecture (CTWA 72h free window, reply-eliciting copy to reopen free 24h service windows, utility vs marketing classification honesty); country-code branch for US(+1). Sends via Chatwoot API for unified history where template support verifies, else Cloud-API-direct with a conversation-note mirror.
**Rationale:** R2's convergent SDR-engine pattern; cadence state must live in owned Postgres under every candidate — the OSS question is only *what executes it*, and DBOS wins on missed-tick semantics and durability.
**Rejected:** n8n as cadence owner (R2 — verbatim: splits agent policy into a second brain); Zoho Marketing Automation (broadcast-shaped; replies don't reach the reasoning agent — Zoho recon); Temporal (above).

### L8 · Lead intake bus + identity broker (F7) — HYBRID (n8n connectors + owned broker)
**Choice:** n8n webhook flows do per-source normalization and forward to ONE brain endpoint; the **identity broker is owned**: `identity_registry` with canonical keys (country-aware E.164 via libphonenumber, observed wa_id, lower(email), IGSID), `INSERT..ON CONFLICT`, `pg_advisory_xact_lock` merges, Zoho upsert with `duplicate_check_fields` on a custom unique Phone_E164 field, v8 Merge Records for repair, fuzzy→human review (never auto-merge). Meta Lead Ads enter via Zoho LeadChain (no Meta App Review — https://help.zoho.com/portal/en/kb/zoho-lead-chain/creating-chains/facebook/articles/integrating-facebook-lead-ads-with-zoho-crm), reaching the brain through the Zoho workflow-rule webhook with an integration-user loop guard.
**Rationale:** wa_id ≠ typed E.164 (MX 521/52, AR 549, BR ninth-digit — https://www.zoko.io/learning-article/whatsapp-id-brazil-mexico); the current last-9-digit LIKE with silent `rows[0]` fails exactly there. R1: the broker must be owned code under every candidate. n8n's value here is real: Meta/ManyChat/Zoho/Sheets connectors, retry UI, execution logs — the reconciliation lanes (nightly Meta bulk read, ManyChat Sheets export) are one flow each instead of owned scripts.
**Rejected:** direct Meta leadgen app (Advanced Access review + Business Verification, days–weeks for this team — R1; escalation path if LeadChain misses the minutes bar); Zapier/Make (SaaS egress + $30–80/mo); building connectors by hand (the exact plumbing C3 exists to avoid).

### L9 · CRM write authority (F6) — BUILD (CrmWriteGate — never outsourced)
**Choice:** Single choke point in crm-adapter: enumerated Pydantic write actions (no generic update tool); `crm_write_log` WAL with deterministic idempotency key (hash of `turn_id|action|canonical params`) + pre-write field snapshots (undo = compensating update; deletes denied at OAuth scope); per-action-type autonomy ladder (2 wks shadow vs the existing Zoho sandbox → ask-first via **Chatwoot private-note approvals** → auto after ~50 clean approvals; estimates keep deterministic amount cap + human confirmation longest); deterministic write budgets with breach→ask-first + team alert; parametrized COQL as a precondition; dedicated Gutty Zoho user (~$14–52/mo) for native Timeline attribution (https://www.zoho.com/crm/developer/docs/api/v8/timeline-of-a-record.html).
**Rationale:** R3's B+E+F verdict; all three 2026 CRM vendors converge on typed actions + agent identity + graduated autonomy + surviving hard guardrails. Zoho credits are a non-issue at this volume (https://www.zoho.com/crm/developer/docs/api/v8/api-limits.html).
**Rejected:** n8n Zoho nodes for writes (no idempotency/policy/WAL — connectors are for reads and reconciliation only); Zia Agent Studio as writer (second brain, PHI through Zia LLM, no deterministic money guarantees — R10; bounded written-BAA-gated hygiene pilot only); direct LLM tool-calls (uncapped blast radius).

### L10 · Presupuesto engine (F2) — BUILD (small) + BUY (Gotenberg)
**Choice:** Deterministic composer: curated Products id-allowlist → line items pinned by product `id` → amount check against catalog constants → Zoho `Quotes` insert (Quoted_Items subform, Quote_Stage lifecycle — https://www.zoho.com/crm/developer/docs/api/v8/insert-records.html) via CrmWriteGate → Gotenberg renders the branded PDF → WhatsApp document send → Quote_Stage update — one DBOS saga, `quotes_ledger` idempotency, human confirmation while in ask-first.
**Rationale:** Zoho v8 can only *email* the rendered inventory-template PDF (20 credits) and offers **no endpoint to fetch it** (Zoho recon) — WhatsApp delivery requires rendering outside Zoho. Gotenberg is the mature MIT answer (single container, HTML→PDF).
**Rejected:** Zoho `send_mail` (email-only, wrong channel); LLM-generated quote content in any form (brief §3); Zoho Books (excluded per §4b, user re-confirmed 2026-07-08).

### L11 · Sales agent (F9) — BUILD (thin, on the spine)
**Choice:** Per R4: 7-slot SPICED-lite qualification (code picks the next question, LLM extracts and phrases; one question per turn; slots persist — never re-ask across days); objection intent seeds (price/skepticism/timing/decision-maker/payment-friction/exam-cost/stall) with a bounded one-reframe-then-escalate loop; the free 15-min call as universal de-risk; payment-terms (TDC +3%) as the only sanctioned concession; discount requests escalate with packaged negotiation context; claims registry + classifier on 100% of outbound sales turns; mode-3 shadow logging with per-product graduation gates.
**Rationale:** Independent data says AI does not out-close humans (https://techcrunch.com/2025/03/24/a16z-and-benchmark-backed-11x-has-been-claiming-customers-it-doesnt-have/); the honest value is <1-min 100% first-touch + qualification + context-packaged tee-ups. Consultation plans (3 fixed SKUs) graduate to mode 2 before itemized exam presupuestos.
**Rejected:** buying an AI-SDR (70–80% churn, English/cold-B2B-first, no PHI posture — R4/R10); freeform persona prompt (slot drift, unauditable).

### L12 · Knowledge + continuous ingestion (F11) — HYBRID
**Choice:** Reuse rag-api/pgvector + ingest-worker. Fix retrieval first: Spanish+unaccent tsconfig migration (the `'simple'` config makes the lexical RRF leg accent- and stem-blind in a Spanish-only corpus — `sql/001_init.sql:26-28`) + contextual-retrieval prefixes (~$1 per full re-index). Drive: one curated "Gutty Knowledge" shared folder, service account, n8n schedule polls `changes.list` (persisted pageToken) → content-hash skip → `files.export` markdown → existing chunker; tombstone deletes. Website via sitemap+hash n8n cron. Tacit: monthly CDM interview → LLM-drafted SOP → sign-off → Drive; asesora-answer mining through learning_queue with **mandatory de-identification before anything becomes a retrievable chunk**. Freshness: `verified_at`/TTL metadata + weekly stale-doc report.
**Graph-RAG (Apache AGE) committed position (§4b):** **Seam now, adopt at Stage 4+ only if evals prove multi-hop failures.** The seam = plain-Postgres entity/relation tables (services↔exams↔protocols↔conditions) populated at ingest, queryable by SQL joins today and migratable into AGE graphs verbatim. Honest ops note: AGE requires a custom pg image alongside pgvector plus `shared_preload_libraries` restarts — a permanent image-maintenance burden that directly contradicts C3's least-ops thesis, adopted only against demonstrated retrieval failures, not speculatively. This is a *committed conditional*, not the v2 auto-defer: the eval set (multi-hop questions over services/exams/protocols) is built in Stage 4 regardless, so the trigger is measured, not vibes.
**Rejected:** managed RAG SaaS (Ragie/Vectorize/LlamaCloud — vendor + egress to duplicate a working pipeline at trivial corpus size — R6); external reranker now (PHI/DPA unverified; deferred behind evals).

### L13 · Privacy & two-class split — BUILD + BUY (Presidio/GLiNER2 self-hosted)
**Choice:** Content-gated dynamic split (R8): health-content gate mounted on the existing classifier (zero added latency) + Spanish Art. 9(2)(a) consent micro-flow promoting conversations to `care` class mid-thread; class routing — care = Anthropic sync BAA only, redacted observability, encrypted Zoho health fields (Zoho signs BAAs — https://www.zoho.com/crm/data-security/hipaa.html); marketing = cheaper models, Batch allowed on redacted text. Fix the two live leaks (raw text to Langfuse `anthropic.py:68-74`; raw turn_log) with a self-hosted Presidio + GLiNER2-PII redactor + custom V-/E-cédula and RIF recognizers **before every derived-store write** — validated by an in-house VE-Spanish eval set because no tool is benchmarked on this register (flagged, not hand-waved). Retention: DBOS scheduled purges (12-mo lost leads + suppression tombstone; 30-day unconsented health turns) — no pg_cron, no custom image. Chatwoot and Phoenix are self-hosted precisely so conversation content and traces never leave the droplet.
**Rationale:** GDPR Art. 9 triggers on content, not CRM status (https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/); HIPAA is a voluntary quality bar here (WhatsApp can never be literally HIPAA-compliant — Meta signs no BAA: https://www.hipaajournal.com/whatsapp-hipaa-compliant/).
**Rejected:** everything-as-PHI (kills Batch economics, dishonest on a non-BAA transport); static lead/patient split (legally wrong); cloud redaction as primary (Azure PII kept as managed fallback only).

### L14 · Observability + evals (F12 tooling) — BUY (Phoenix) + REUSE (turn_log system of record)
**Choice:** Arize Phoenix single container on the existing Postgres, OTel instrumentation of the LLM client (which also de-locks the trace platform); Langfuse v2 retired. turn_log + learning_queue stay authoritative; Haiku-class judge on 100% LLM-composed sales turns ($5–20/mo — R9); `--mode crm` deterministic write evals + nightly reconciliation; weekly clustered review ≤2h with strict priority; GEPA/DSPy prompt optimization deferred until ~300 judge-labeled conversations exist (https://arxiv.org/pdf/2507.19457).
**Rationale:** R9's ops-fit verdict: Langfuse v2 is maintenance-only; v3 self-host = ClickHouse+Redis+S3 (three containers + droplet upgrade); Phoenix is one container (https://github.com/arize-ai/phoenix). LiteLLM's native callbacks feed the same OTel pipe.
**Rejected:** Langfuse v3 (ops weight); cloud eval SaaS (PHI egress; BAA behind enterprise tiers — R9).

### L15 · Function-package contract (extensibility) — BUILD (thin convention, enforced)
**Choice:** A function package = one repo folder: `seeds.yaml` (intents + dispatch), task module (explicit-claim registration; collision detection replaces the silent first-match registry `base.py:23-28`), optional DBOS workflow/schedule defs, optional n8n flow export (JSON, version-controlled, deployed via n8n API), Chatwoot config (labels/teams/canned responses as scripted setup), eval cases, claims/policy entries, autonomy defaults for any writes. `nutrition_followup` (F5) is built as the proving skeleton in Stage 4.
**Rationale:** Brief §3 makes this a first-class criterion; the Agentforce topic/action/guardrail packaging is the market-validated shape (R10). Zero central-dispatch edits by construction.
**Rejected:** registry-as-is (silent fallback is an operator-scope hazard); plugin marketplaces/dynamic loading (over-engineering at this team size).

### L16 · Data + deploy plane — REUSE (one droplet, one Postgres instance, compose)
**Choice:** Single DigitalOcean droplet upgraded to 8GB/4vCPU (~$48/mo + backups); one Postgres instance with separate databases (`app`+DBOS / `chatwoot` / `n8n` / `phoenix`); docker-compose remains the deploy unit; Alembic migrations from Stage 0 (initdb SQL frozen as baseline); nightly `pg_dump` + offsite copy; secrets in `.env` with 600 perms (constant-time compare fix in `auth.py:12`).
**Rationale:** Everything here is Postgres-backed by design — DBOS, Chatwoot, n8n, Phoenix, the ledgers — one backup story, one instance to tune, 10× headroom trivially (R2: single-digit scheduled jobs/minute at 2k leads/mo).
**Rejected:** Supabase (C5's territory; managed egress questions for PHI); Kubernetes (absurd at this scale); second droplet (only if RAM measurement in Stage 0 forces it — the honest fallback, +$24–48/mo).

---

## 5. Precision & exactly-once (brief §3's explicit requirement)

The precision constraint is met by **construction, not model quality**, at four seams:

1. **Ingress:** every source (Chatwoot bot webhook, n8n intake flows, Zoho webhook) writes to `intake_events` with `UNIQUE(source, source_event_id)` before ACK — Meta redelivers on non-2xx, ManyChat likely never retries, Chatwoot retry semantics UNVERIFIED; the inbox makes all three safe. The in-memory `_SEEN` anti-pattern (`fsm.py:39`) is deleted, not replicated.
2. **Egress:** `send_intents` row keyed `(enrollment_id, step_no)` or `(turn_id, seq)` written before any transport call; DBOS checkpointed steps resume without re-sending; a content-hash dedup window guards the Chatwoot/Cloud API send (neither accepts idempotency keys). Failed sends park in the outbox with backoff — never silently dropped (fixes the 3-retries-then-lose behavior at `fsm.py:172-185`).
3. **Money:** prices exist in exactly one place (`facts/prices.yaml` → rendered into FAQ strings, knowledge chunks, eval assertions); presupuesto amounts computed from the Products id-allowlist with a deterministic cap check; a regex output guard blocks any LLM-composed reply containing a dollar amount not in the fact table; price decompositions precomputed.
4. **CRM:** every write flows through the WriteGate's WAL with deterministic idempotency keys + Zoho upsert `duplicate_check_fields`; nightly reconciliation (ledger vs COQL read-back) catches silent failures; undo = compensating update from pre-write snapshots; deletes are impossible at OAuth-scope level.

Honest framing: DBOS steps are at-least-once, so the system guarantee is **effectively-once via idempotency guards** — identical to C1's ceiling, because the guarantee is bounded by Zoho/Meta APIs, not by the orchestrator.

**Latency honesty:** the deterministic path gains two hops vs direct ingress (Cloud API → Chatwoot → brain → Chatwoot → Cloud API). Classifier ~150ms + two localhost HTTP hops should hold p95 well under the <1s deterministic target, but this is **measured in Stage 1 with a hard gate**: if the Chatwoot hop costs >~400ms p95, the brain switches to direct Cloud API webhook ingress and Chatwoot degrades gracefully to the human console + mirror (its channel still receives all messages from Meta independently). The architecture is designed so this fallback is a config change, not a rebuild.

---

## 6. Model tier position (brief §4b)

LiteLLM makes this a measured config decision, not an architecture decision. Week 1: run `eval/run_eval.py` Spanish-VE generation cases against Gemini 3.5 Flash ($1.50/$9.00), Haiku 4.5 ($1.00/$5.00), and Gemini 3 Flash ($0.50/$3.00); pick on quality-per-dollar in VE register + latency. Binding rules regardless of winner: care-class turns → Anthropic synchronous Messages under BAA (or Gemini only via Vertex AI + BAA); marketing-class → winner of the eval, Batch API permitted on redacted text for nightly judge/learning jobs (50% discount). Per-turn costs are cents either way at this volume; the router carries both keys so a flip is a one-line model-group change.

---

## 7. Staged rollout (value-first; weeks 1–3 on the current droplet)

| Stage | Weeks | Ships | User-visible value |
|---|---|---|---|
| **0 — Console + rails** | 1 | Chatwoot up (compose, droplet resize); **Instagram channel + new WhatsApp Cloud API number connected via embedded signup**; LiteLLM + Phoenix containers; security punch-list fixes (constant-time compare, HMAC fail-closed, Postgres inbox dedup, fail-closed mute); Alembic baseline; §4b model eval run | **Asesoras get a real shared inbox for IG DMs + the new WA line on day ~5** — F10 relief starts before any AI work; María José sees every conversation in one place |
| **1 — Brain online + first touch** | 2–3 | Gutty brain behind the Agent Bot on the new number (F1 deterministic FAQ + classifier + RAG-wired fallback); identity broker + `intake_events`; n8n flows: ManyChat External Request → broker → Zoho upsert → **instant first-touch send**; Zoho LeadChain + workflow-rule webhook; latency gate measured | **100% of new leads get a correct first touch in <5 minutes** (21× qualify odds) and land deduped in Zoho; handoff = Chatwoot assignment with context note |
| **2 — Cadences + shadow money** | 4–6 | DBOS cadence engine (touches 2..N, consent ledger, suppression, US branch, status-webhook rescheduling); F4 weekly outbound to opted-in customers; presupuesto engine in **shadow** (Gotenberg PDF + draft Quote reviewed in Chatwoot before send); CrmWriteGate in shadow against the existing Zoho sandbox | Every lead worked to exhaustion or reply without human effort; asesoras approve ready-made presupuestos in one click instead of building them |
| **3 — Autonomy + cutover** | 7–10 | WriteGate ask-first → auto per action type (50-clean-approvals rule); sales F9 mode 3 live (slots, objections, claims classifier, tee-up packages); **legacy Gutty number migrates to Cloud API + Chatwoot; WAHA + OpenClaw retired**; group commands retired | One number, one inbox, one brain; logistics workload visibly drops (Chatwoot agent reports + turn_log KPIs make it measurable) |
| **4 — Knowledge + learning + seam proof** | 11–14 | Drive `changes.list` pipeline + tacit CDM loop + Spanish tsconfig migration + contextual retrieval re-index; F12 judge + weekly review + reseed auto-revert; graph-seam entity tables + multi-hop eval set; **F5 `nutrition_followup` package skeleton built to prove L15**; first mode-2 graduation candidates (consultation plans) | Knowledge stops rotting; the review loop runs at ≤2h/week; adding function #13 is demonstrably a package, not a rewrite |

Everything runs on the (resized) current droplet; no migration events except the WhatsApp number cutover, which every candidate shares.

---

## 8. Monthly cost model @ 1,000 leads/mo

| Item | $/mo | Basis |
|---|---|---|
| Droplet 8GB/4vCPU + 20% backups | ~$58 | DigitalOcean basic tier; Chatwoot (Rails+Sidekiq+Redis) is the driver; second-droplet fallback +$24–48 if RAM measurement forces it (UNVERIFIED footprint, headroom priced in) |
| Chatwoot, n8n, DBOS, LiteLLM, Gotenberg, Phoenix, Presidio/GLiNER2 | $0 | All self-hosted OSS (MIT / Sustainable-Use / ELv2-internal — §1) |
| WhatsApp templates | $80–250 | R2/R7: RoLatAm marketing ~$0.0625–0.074/msg, utility ~$0.008–0.0113 (rate-card discrepancy flagged; primary CSV verification open); ~2 paid marketing touches/lead after window engineering (CTWA 72h free, reply-reopened 24h service windows) + F4 outbound ≈ $125–190 central case |
| LLM tokens | $30–70 | ~7.5k turns/mo, ~40% LLM-composed × ~2k in/300 out ≈ $11–17 (Haiku 4.5 vs Gemini 3.5 Flash); judge on 100% LLM-composed sales turns $5–20 (R9); slot extraction + claims classifier $5–15; embeddings + contextual re-index ≈ $1–3 |
| Zoho "Gutty" user license | $14–52 | Dedicated agent identity for write attribution (R3); edition-dependent |
| ManyChat Pro (existing spend) | $29–105 | Already required for IG flows (R1) |
| LeadChain extension | UNVERIFIED | Marketplace pricing unpublished (R1 open question) |
| **Total infra (brief's ≲$150–350 target)** | **~$58–106** | Comfortably inside; softwareless-license by design |
| **Total all-in incl. messages + tokens + SaaS** | **~$210–430** | Central case ≈ $280 at 1,000 leads/mo; scales sub-linearly (droplet flat, templates linear) |

Comparison anchor: the market prices this capability at $0.05–0.50 per conversation *outcome* (Botmaker/Breeze/Agentforce — R10), i.e. $500–1,500+/mo at our volume, without Zoho depth, VE Spanish, or a PHI posture.

---

## 9. The −80% logistics story (functions → hours)

Baseline estimates (to be validated in Stage 1 via Chatwoot agent reports + turn_log — instrumenting the claim is itself a Stage-1 deliverable; the "resolved-without-human" KPI is the market's own metric, R10):

| Work | Manual today (est.) | With C3 | Saved |
|---|---|---|---|
| Lead entry, dedup, Contact↔Deal linking (F6/F7) | 1,000 leads × ~6 min ≈ 100 h | broker + WriteGate + review queue ≈ 5 h | **~95 h** |
| First touch + follow-up touches (F8) | 1,000 × 4 touches × ~2 min ≈ 133 h | cadence engine; humans only claimed handoffs ≈ 15 h | **~118 h** |
| FAQ / customer-service replies (F1) | ~1,200 convs × ~5 min ≈ 100 h | deterministic FAQ + RAG; ~20% escalate ≈ 20 h | **~80 h** |
| Presupuesto build + send (F2) | ~150 × ~15 min ≈ 37 h | composer + PDF; human verifies payment only ≈ 6 h | **~31 h** |
| Weekly outbound campaigns (F4) | ~12 h | cadence defs + consent ledger ≈ 1 h | **~11 h** |
| IG DM triage (F10, MKT team) | ~25 h | ManyChat + Chatwoot IG inbox + funnel bot ≈ 8 h | **~17 h** |
| Handoff context assembly (F3) | ~200 × ~4 min ≈ 13 h | auto context package in Chatwoot ≈ 2 h | **~11 h** |
| **Total** | **~420 h/mo** | **~57 h/mo** | **~363 h ≈ 86% gross → ~80% net** after review queue (~2 h/wk), approvals during the ladder, and fuzzy-identity reviews |

What remains human by design: selling judgment on teed-up conversations, payment verification + deal-won marking, edge-case escalations, quality review — exactly the brief's "high-judgment work." The Klarna reversal (https://www.forbes.com/sites/quickerbettertech/2025/05/18/business-tech-news-klarna-reverses-on-ai-says-customers-like-talking-to-people/) is why C3 targets −80% with a first-class human console, not −100% with none.

---

## 10. Top 5 risks + mitigations

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Chatwoot becomes a heavyweight critical dependency**: Rails+Redis+Sidekiq ops on a tiny team; a second PHI-bearing store (full conversation content); upgrade regressions | High | Self-hosted on-droplet (no egress); pinned versions + staged upgrades; nightly backups in the single-Postgres story; **the brain always holds a direct Cloud-API send client and a transport-neutral ingress** — Chatwoot degrades to console+mirror, it is never the only path to the wire (§5); MIT license verified |
| 2 | **Seam sprawl**: more webhook boundaries (Chatwoot↔brain, n8n↔brain, Zoho↔n8n) than C1's monolith; each is a place messages die | High | Every seam converges on the same two Postgres ledgers (`intake_events` inbox, `send_intents` outbox) wrapped in DBOS steps; nightly reconciliation jobs (Chatwoot API, Zoho COQL, Meta bulk read vs ledger); alerts into the team's own Chatwoot inbox. Seam count is bounded and enumerated (§5) — it does not grow with function count (packages reuse the same seams) |
| 3 | **Policy leaks into n8n flows** (the "second brain" anti-pattern R2 warned about), making behavior undebuggable and unversioned | Medium | Binding rule enforced in review: n8n transforms and transports only — no business state, no policy branches, no timing that matters; all flows exported to git and deployed via API; anything needing state/policy must be a brain package (L15). n8n's blast radius is intake + reports, both reconciled nightly |
| 4 | **Hot-path latency/delivery through the inbox hub** (Agent-Bot webhook semantics UNVERIFIED; two extra hops vs direct ingress) | Medium | Stage-1 hard gate: p95 measured; >~400ms hop cost triggers the designed fallback to direct Cloud API ingress with Chatwoot as mirror/console (config change, not rebuild); enqueue-then-ACK + inbox dedup makes retry behavior irrelevant to correctness |
| 5 | **OSS sustainability drift**: Chatwoot enterprise-ization, n8n license posture, DBOS ecosystem youth (single-vendor OSS) | Medium | All state lives in owned Postgres — every component is individually replaceable (Chatwoot→console swap, n8n→owned scripts, DBOS→SKIP-LOCKED worker ~2 wks, Phoenix→Langfuse v3); MIT verified for the two load-bearing adoptions (Chatwoot, DBOS); no component holds data hostage |

Shared-with-every-candidate risks (not C3-specific, tracked in the study): Meta template pricing/rate-card changes and the US(+1) marketing block; WhatsApp number-migration friction; Spanish-VE redaction immaturity (R8 — defense-in-depth only); Zoho edition entitlements (sandbox exists, so likely Professional+).

---

## 11. Where C3 honestly loses (for the judges)

- **Vs C1 on moving parts:** C3 runs ~6 more containers than C1's monolith. If the team's true capacity is "one FastAPI process and nothing else," C1 is safer — at the price of building a handoff console it will never build, capping F3/F10 UX at group commands, and owning transport/media/template plumbing forever. C3's claim is that *operating* mature products is cheaper than *owning* their equivalent code; that claim is strongest exactly at this scope and weakest if scope shrinks back to F1–F3.
- **Vs C1 on hot-path purity:** the Chatwoot hop is a real latency and semantics unknown until Stage 1 measures it. The fallback is designed, but if triggered, C3 converges toward C1-plus-Chatwoot-console — which is still a defensible outcome (the console was the point).
- **Vs C4 on Zoho leverage:** C3 uses Zoho as system of record + write target only; it forgoes Zia's free-platform agents except as a bounded hygiene pilot (R10) — deliberately, because deterministic money paths and VE-Spanish persona control cannot be delegated to Zia.
- **Custom-code floor:** C3 still owns ~6–9k LOC (brain, broker, WriteGate, presupuesto, cadence state, privacy gate, packages). Anyone promising less than that is outsourcing money, identity, or judgment — which the brief forbids.

---

## 12. Owned-code inventory (the "least custom code" claim, quantified)

| Owned module | Est. LOC | What OSS absorbs next to it |
|---|---|---|
| Brain: TurnFSM + normalizers + task modules (F1/F9/F10 + package contract) | ~2,500 (mostly existing) | Inbox UI, ticket lifecycle, channel wiring, media, CSAT, reports → Chatwoot |
| Identity broker + intake endpoint | ~800 | Source connectors, retries, reconciliation lanes → n8n |
| CrmWriteGate + WAL + autonomy ladder | ~1,200 | — (never outsourced) |
| Cadence state machine + defs | ~700 | Scheduler durability, cron, sleep, queues → DBOS |
| Presupuesto composer + saga | ~500 | PDF rendering → Gotenberg; quote storage → Zoho |
| Privacy gate + redactor config + retention jobs | ~600 | NER models → Presidio/GLiNER2; trace redaction hooks → OTel |
| Evals (`--mode crm`, judge prompts, gates) | ~800 | Trace UI, annotation → Phoenix |
| **Total owned** | **~7,100 LOC** | vs C1 which owns all of the above **plus** transport/template/media plumbing and either a console build or a permanent CLI-for-humans |

---

## 13. Structured summary

**Name:** C3 — OSS Best-of-Breed ("own the brain, operate the rest").
**One-line:** Chatwoot (console+channels) + DBOS (time+exactly-once) + LiteLLM (models+budgets) + n8n (connectors) + Gotenberg (PDFs) + Phoenix (traces) composed around the kept classifier/RAG spine and three owned kernels (brain, identity broker, CrmWriteGate) — every component MIT/fair-code, self-hosted, Postgres-backed, individually replaceable.
