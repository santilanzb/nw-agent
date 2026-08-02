# Candidate C4 — "Zoho-Native Maximalist": Zoho as the Operator's Body, a Slim Kernel as the Voice

> Composer: C4 advocate · 2026-07-08 · Study: Cerebro Gutty v3 "Master Operator"
> Sources: BRIEF.md §1–8; recon-code-seams.md; recon-zoho-surface (scratchpad); research R1–R10. Every load-bearing external claim carries a URL; unverifiable claims are marked **UNVERIFIED**.

## 0. Thesis

NutriWhite already pays for, staffs, and trusts one platform: Zoho CRM. Every other candidate builds a second operational universe next to it — cadence tables, identity brokers, ticket inboxes, admin consoles — that a 1–3 person team must then learn, operate, and keep synchronized with the CRM they actually live in. C4 inverts that: **Zoho is not merely the system of record; it becomes the process engine, the business-state store, the team console, and the self-serve configuration surface.** The custom brain shrinks to a **conversational kernel** that does only what Zoho verifiably cannot do: the Gutty WhatsApp persona (Spanish-VE), the intent classifier + RAG, the PHI boundary, and a single **Send/Write Gate** that gives the whole system its exactly-once semantics.

The honest core of this candidate is a **verified boundary**, not enthusiasm: Zoho has **no conversational WhatsApp brain**. Zoho's own documentation states that its CRM WhatsApp integration does not support chatbots or bulk messaging (https://help.zoho.com/portal/en/kb/crm/connect-with-customers/business-messaging/articles/business-messaging-using-whatsapp-for-business-integration-with-zoho-crm); SalesIQ's Zobot runs WhatsApp bots only on a Meta Cloud API number and reasons over SalesIQ/Desk resources, not our pgvector RAG or intent seeds (https://help.zoho.com/portal/en/kb/salesiq-2-0/for-administrators/channels/articles/whatsapp-channel-integration); Zia Agents operate on email inside CRM, with no documented WhatsApp channel for conversational work (https://www.zoho.com/crm/zia/agentic-ai.html). C4 does not pretend otherwise. What Zoho **can** do — and does better than anything we would build — is records, dedup, quotes with pinned prices, workflows, schedules, tasks, audit, segmentation, campaigns, and team chat. C4 pushes 10 of 16 layers onto that substrate and keeps the kernel under ~6 kLOC.

**Why this wins for THIS business:** (1) the brief's own F2 decision (Zoho Quotes + curated Products, verified live 2026-07-01) is already a Zoho-native deterministic money path — C4 generalizes that pattern; (2) cadence state, sales slots, consent, and quote lifecycle live as **CRM fields the team can see and edit** — the −80% target includes removing the engineering bottleneck, not just the messaging bottleneck; (3) the smallest owned codebase of any candidate means the smallest permanent maintenance surface for a team with no platform engineer.

## 1. Where the Zoho-native line actually falls (verified capability inventory)

**Zoho verifiably CAN (C4 pushes these in):**
- **Create/update/upsert all needed modules** via v8 REST: Leads, Contacts, Deals, Tasks, Notes, Quotes (Quoted_Items subform mandatory, products pinned via `Product_Name:{id}`) — https://www.zoho.com/crm/developer/docs/api/v8/insert-records.html
- **Native dedup**: upsert with `duplicate_check_fields` (incl. custom unique fields → add canonical `Phone_E164`), and the v8 Merge Records API for after-the-fact repair — https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html ; https://www.zoho.com/crm/developer/docs/api/v8/merge-records.html
- **Deal stage moves** = plain `PUT` on `Stage` (NutriWhite runs no Blueprint) — recon-zoho-surface.
- **Audit**: per-record Timeline API with old/new field values; org-wide Audit Log Export jobs (CSV/ZIP, 1M entries); Recycle Bin restore (60 days) — https://www.zoho.com/crm/developer/docs/api/v8/timeline-of-a-record.html ; https://www.zoho.com/crm/developer/docs/api/v8/restore-recycle-bin-records.html
- **Event triggers**: workflow-rule webhooks fire on create/edit including API-sourced writes, no expiry (beats Notification API's 1-day watch channels) — https://help.zoho.com/portal/en/kb/crm/automate-business-processes/actions/articles/webhooks-workflow
- **Scheduled automation**: workflow scheduled actions + Deluge functions (`invokeurl` to external HTTP; 10,000 calls/day or 200×licenses) — https://www.zoho.com/crm/developer/docs/functions/functions-limits.html
- **WhatsApp template campaigns** (segmentation, scheduling, Meta template approval) via Marketing Automation 2.0 — the best native fit anywhere for F4 — https://www.zoho.com/marketingautomation/multi-channel-marketing/whatsapp-marketing.html
- **Meta Lead Ads sync** without Meta App Review via the LeadChain extension — https://help.zoho.com/portal/en/kb/zoho-lead-chain/creating-chains/facebook/articles/integrating-facebook-lead-ads-with-zoho-crm
- **Compliance substrate**: Zoho signs BAAs and supports field-level encryption for designated ePHI fields — https://www.zoho.com/crm/data-security/hipaa.html
- **API headroom**: Standard-edition floor 50k credits/24h vs ~3.7k/day worst case at 2,000 leads/mo — credits are a non-issue; real ceilings are concurrency (10–20) and 20-credit `send_mail` — https://www.zoho.com/crm/developer/docs/api/v8/api-limits.html

**Zoho verifiably CANNOT (the kernel floor):**
- Run a WhatsApp chatbot on the CRM integration ("chatbot functionality not supported"; bulk not supported) — help doc cited above.
- Host our brain in SalesIQ: Zobot's Answer Bot uses SalesIQ/Desk knowledge, not our RAG/intents/persona; requires a Meta Cloud API number anyway — SalesIQ doc cited above.
- **Fetch a rendered Quote PDF via API**: `send_mail` with `inventory_details` can *email* the inventory-template PDF (20 credits) but no v8 endpoint returns the rendered file — WhatsApp PDF delivery must render outside Zoho — https://www.zoho.com/crm/developer/docs/api/v8/send-mail.html ; https://www.zoho.com/crm/developer/docs/api/v8/inventory_templates.html (metadata-only). Zoho Writer merge-to-PDF as a native workaround: **UNVERIFIED**.
- Provide idempotency keys: no native mechanism; `duplicate_check_fields` upsert is the only surrogate — exactly-once must be built client-side (R3).
- Give conversational Zia on WhatsApp: Zia agents are email-channel in CRM; whether Zia can attach to the CRM WhatsApp channel is undocumented (**UNVERIFIED**, likely no); Zia BYOK offers no Anthropic; Zia/ZKS BAA coverage **UNVERIFIED** — https://www.zoho.com/agents/pricing.html
- Deterministic prices from Zia's Quote Generator: it is LLM-driven — banned from the money path by brief §3 (R10).
- Durable retry semantics in Deluge/Flow: failed `invokeurl` is lost unless caught; Flow is glue, not a brain — https://www.zoho.com/flow/pricing.html

**Design law derived from this inventory:** *Zoho owns state, schedule, and screen; the kernel owns speech, secrets (PHI), and the gate.* Zoho automations never call Meta and never write records directly on the agent's behalf — they only **signal intent** to the kernel's gate, which enforces idempotency, consent, and policy, then performs the effect.

## 2. Architecture at a glance

```
IG (ManyChat) ─────┐                              ┌─→ Zoho CRM  (Leads/Contacts/Deals/Quotes/
Meta Lead Ads ─→ LeadChain ─→ ┌──────────────┐    │   Products/Consultas/Examenes/Tasks/Notes)
manual entry ──→ Zoho ─wf-webhook→ │              │←──┘   · cadence fields on Lead
existing autom.────────────────→   │  GUTTY       │       · sales-slot fields
                                   │  KERNEL      │       · consent/opt-in fields
WhatsApp Cloud API  ⇄ webhooks ⇄   │ (agent-core, │       · Quote_Stage lifecycle
(bot number; WAHA retiring)        │  rag-api,    │       · Timeline/Audit/Recycle Bin
                                   │  crm-adapter)│   Zoho Schedules/Workflows ─intent─→ kernel gate
Zoho Cliq (team console) ⇄ buttons │  + Send/Write│   Zoho Marketing Automation 2.0 → F4 campaigns
                                   │  GATE (DBOS, │   Zia pilot (internal hygiene only, BAA-gated)
Postgres (droplet): pgvector RAG,  │  idempotency)│
turn_log, WAL ledger, inbox/outbox └──────────────┘ → Anthropic (care, BAA) / Gemini 3.5 Flash (mkt, eval-gated)
```

## 3. F1–F12 coverage map

| F | Where it lives | Mode |
|---|---|---|
| F1 customer service | Kernel: FSM + intent + RAG + LLM fallback (hardened; retrieve wired into fallback) | reuse+harden |
| F2 presupuesto | Zoho Quotes+Products (mandated); kernel gate composes, checks amount, renders PDF, sends via Cloud API | hybrid |
| F3 tickets/handoff | Reuse handoff FSM; ticket = Zoho Task+Note+context package; team console = Zoho Cliq bot | hybrid |
| F4 weekly outbound | Zoho Marketing Automation 2.0 WhatsApp campaigns; double opt-in fields on Contact; replies → kernel | buy |
| F5 Fase-2 seam | Function-as-package convention: repo package + versioned Zoho config manifest; nutrition follow-up = a cadence package on the same substrate | designed now |
| F6 CRM master operator | Zoho-native writes through kernel Write Gate; dedup via upsert/Merge API; audit via Gutty OAuth user + Timeline + WAL; autonomy ladder → full autonomy with budgets + anomaly alerts | hybrid |
| F7 lead intake | LeadChain (Meta forms) + ManyChat External Request + one Zoho workflow-webhook for ALL record arrivals; identity = Phone_E164 unique field + canonicalization in kernel | buy+hybrid |
| F8 toques cadence | Cadence state as Lead fields; Zoho Schedules advance steps; kernel send-time gate + idempotency; first touch event-driven <1 min; call-touch = Zoho Task (voice seam) | hybrid |
| F9 sales agent | Kernel: slot schema in Zoho Lead fields, bounded objection loop, claims classifier; mode-3 shadow → mode-2 gates | build |
| F10 IG intake | ManyChat default flow: short reply + ref-token wa.me funnel; payload → kernel → Zoho Lead with IGSID | buy+hybrid |
| F11 knowledge | Reuse rag-api/pgvector + Spanish tsconfig + contextual retrieval; Drive folder polling; tacit CDM loop; prices NEVER retrieved (Products is SoT) | hybrid |
| F12 self-learning | turn_log + learning_queue authoritative; judge on 100% LLM-composed turns; weekly Cliq digest; reseed gates | reuse+build |

## 4. The 16-layer stack

### L1 · WhatsApp transport — BUY (Meta Cloud API direct; WAHA as retiring bridge)
New Cloud API bot number immediately (template legality, `ctwa_clid` attribution, 72h CTWA free windows, future Calling API); legacy Gutty number migrates at cutover — state lives in Postgres/Zoho, so hard migration is acceptable (https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/migrate-existing-whatsapp-number-to-a-business-account/). Proactive outbound on WAHA is Meta's textbook ban profile (WAHA issue #1362; 2026 unanswered-outbound heuristics — R7).
**Rejected:** Zoho CRM native WhatsApp as the bot channel — explicitly no chatbot/bulk, Enterprise+-gated, and one number cannot serve both Zoho's integration and the kernel's Cloud API registration (**UNVERIFIED** but consistent with Meta's one-active-client registration model); SalesIQ Zobot (wrong brain); Twilio/360dialog (markup/base fee buys nothing at this volume — R7).

### L2 · Conversational kernel (F1) — REUSE (agent-core FSM, hardened)
Keep the TurnFSM — the 2026 production pattern for customer-facing agents is an owned loop (https://github.com/humanlayer/12-factor-agents ; https://www.anthropic.com/research/building-effective-agents). Harden per punch-list: Postgres inbox replaces in-memory `_SEEN` (fsm.py:39), HMAC fail-closed (main.py:80), constant-time key compare (auth.py:12), bounded ingress, deterministic greetings (customer_service.py:172–209), and **wire rag-api `/v1/retrieve` into the LLM fallback** (today agent-core never calls it — recon).
**Rejected:** SalesIQ Answer Bot / Zia as the brain (channel + knowledge mismatch, persona uncontrollable); LangGraph rewrite (serialization footguns, no cadence answer — R5).

### L3 · Intent & routing spine — REUSE (rag-api classifier + intent_seeds.yaml)
~99% on seeds; dispatch table already drives tool choice. New functions ship as seed packages + TaskModules; fix the silent first-match registry (base.py:24) to explicit-claim-or-error.
**Rejected:** Zia topic routing (email-centric, no seed-level control, no VE-Spanish eval harness).

### L4 · Knowledge & retrieval (F11) — HYBRID (reuse RAG stack + build connectors/quality)
Fix Spanish tsconfig + unaccent (the `simple` config cripples the lexical RRF leg today — sql/001_init.sql:26–28); add contextual-retrieval prefixes (~$1 per full re-index at this corpus size — https://www.anthropic.com/engineering/contextual-retrieval); Drive "Gutty Knowledge" shared folder + `changes.list` polling + `files.export` markdown (https://developers.google.com/workspace/drive/api/guides/manage-changes); monthly CDM tacit interviews → LLM-drafted SOP → owner sign-off (R6). Freshness metadata + weekly stale-doc Cliq report.
**Graph-RAG / Apache AGE — committed position: REJECT now, evidence-gated revisit (brief §4b).** C4's entire premise is minimizing the owned data plane; AGE demands a custom Postgres image alongside pgvector plus a graph-maintenance pipeline — precisely the complexity C4 exists to avoid. NutriWhite's genuinely relational questions (exam↔protocol↔condition↔price) are better served in C4 by **structured COQL reads over Products/Examenes/Consultas** — the relations already live in Zoho as lookups, curated by calidad@, no second graph to sync. Seam kept: `corpus` column + entity tags in chunk metadata. Revisit trigger (explicit, not hand-waved): if the retrieval eval set shows >10% of failures classified as multi-hop after tsconfig+contextual fixes, adopt AGE at that stage with the documented image swap.
**Rejected:** ZKS/Zia knowledge (BAA **UNVERIFIED**, untunable, no VE eval); managed RAG SaaS (vendor + egress for a tiny corpus); AGE now (above).

### L5 · System of record, identity & dedup (F6/F7 substrate) — REUSE (Zoho-native, maximal)
Add custom unique `Phone_E164` on Leads+Contacts; ALL identity writes go through **upsert with `duplicate_check_fields`**; residual dupes repaired via **Merge Records API** (logged, audited). Kernel contributes only country-aware canonicalization (libphonenumber; Mexico 521/Argentina 549/Brazil ninth-digit wa_id quirks — R1) and a thin `wa_id↔zoho_id` cache. The last-9-digit LIKE heuristic and f-string COQL in zoho_client.py:28–34,138–165 are retired/parametrized before any write authority widens.
**Rejected:** owned Postgres identity broker as primary (C1's answer) — creates a second source of truth the team can't see and a permanent sync liability; fuzzy auto-merge (human review only).

### L6 · Lead + IG intake (F7, F10) — BUY + HYBRID
(a) Meta Lead Ads → **LeadChain** (Zoho's Meta app; zero App Review/Business Verification — R1); (b) ManyChat External Request (Pro) pushes IG leads mid-flow with full contact data to a kernel normalizer → Zoho upsert; ManyChat has no subscriber-enumeration API, so a Sheets-export reconciliation lane backs missed webhooks (https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-request); (c)+(d) records landing in Zoho via existing automations or manual entry need nothing — **one Zoho workflow-rule webhook on record-create is the single brain trigger for ALL four sources**, carrying `{module, record_id, event}` only; the kernel re-fetches via COQL. Loop guard: rule excludes the Gutty integration user's own writes. F10: ManyChat default flow gives the short reply + **ref-token wa.me link** — the only deterministic IGSID→phone join and the IG→WhatsApp funnel in one mechanic (R1); IG stays intake-only per brief.
**Rejected:** direct Meta leadgen app (days–weeks of Advanced Access review; escalate only if LeadChain misses the minutes bar); Notification API watch channels (1-day expiry); iPaaS bridges ($30–80/mo for what O1+O2 already covers).

### L7 · Cadence engine "toques" (F8) — HYBRID (Zoho-stateful, kernel-gated)
**C4's signature move.** Cadence state lives as fields on the Lead: `Cadence_Name`, `Cadence_Step`, `Next_Touch_At`, `Cadence_Status` (active/replied/opted_out/exhausted/paused_handoff/channel_invalid) — every asesora sees exactly where every lead is, in the CRM they already use, and edits cadence copy/timing in a Zoho-visible catalog. Mechanics: enrollment set by the L6 workflow at lead-create; **first touch is event-driven** through the same webhook (<1 min — contact within 5 min = ~21× qualification odds, MIT/InsideSales: https://25649.fs1.hubspotusercontent-na2.net/hub/25649/file-13535879-pdf/docs/mit_study.pdf); touches 2..N advanced by a Zoho Schedule (Deluge, `invokeurl`) — minimum schedule granularity **UNVERIFIED**, so the kernel runs a 5-min **reconciliation poller** (COQL for `Next_Touch_At <= now`) as the authoritative clock backstop. Every touch passes the kernel **send-time gate**: idempotency key `lead_id|cadence_id|step_no`, reply-kill (`last_inbound_at` check), consent + suppression, **US +1 branch** (marketing templates hard-blocked to US since 2025-04 — R2), per-user cap awareness via status webhooks. Call-touch = task type that creates a **Zoho Task with script + context** today; a voice agent serves the same task type later (F8 voice seam, R7). Inbound reply sets `Cadence_Status=Replied` via the Write Gate — kills future touches at source AND at send time.
**Rejected:** DBOS-owned cadence state (C1) — correct semantics but invisible to the team and editable only by engineers; Marketing Automation journeys for per-lead toques (broadcast-shaped; replies don't reach a reasoning agent — recon); n8n (skips missed ticks, second brain); Temporal (3+ services for ~300–800 jobs/day — R2/R5).

### L8 · Proactive customer outbound (F4) — BUY (Zoho Marketing Automation 2.0)
Weekly Google-review nudges, repurchase, referrals as **MA 2.0 WhatsApp template campaigns**: segmentation, scheduling, Meta template approval, and double-opt-in fields synced from CRM — all in a UI the marketing team drives without engineering (https://www.zoho.com/marketingautomation/multi-channel-marketing/whatsapp-marketing.html). Replies land on the bot number and flow into the kernel like any inbound turn (the known MA limitation — replies don't reach a reasoning agent — is thereby neutralized: the kernel IS the reply handler).
**Rejected:** kernel-built broadcast engine (reinvents segmentation UI for the one function Zoho natively owns); CRM-native WhatsApp workflow sends (no bulk); WAHA blasts (ban).

### L9 · Presupuesto engine (F2) — HYBRID (Zoho Quotes+Products mandated; kernel builds delivery + checks)
Products module (curated by calidad@: `Product_Code`/`Unit_Price`/`Product_Category`/`Product_Active`) is the **single price source of truth**. Kernel composes the Quote via the Write Gate: `Quoted_Items` pinned by **product `id` allowlist** (never name-search), amount = deterministic sum of `Unit_Price × Quantity` re-verified against a catalog-max cap; `Quote_Stage` picklist drives lifecycle follow-ups via workflow. **Kills the 7-place price duplication** (recon): a nightly Products COQL pull renders `facts/prices.yaml`, which generates the FAQ price strings in both runtimes and the eval assertions; a regex output guard blocks any LLM-composed dollar amount not in the fact table (R6). Delivery: WhatsApp document message from a kernel-rendered PDF that mirrors the CRM inventory template (no API fetches the rendered PDF — verified above); email path uses native `send_mail` (20 credits). Zoho Writer merge as a native render path: **UNVERIFIED**, pilot in week 5.
**Rejected:** Zia Quote Generator (LLM-priced — categorically forbidden by brief §3); Zoho Books (user-forbidden, §4b); email-only delivery (WhatsApp is the channel).

### L10 · CRM Write Gate & autonomy ladder (F6) — BUILD (small, load-bearing)
Single choke point in crm-adapter: **enumerated typed actions** (Pydantic; no generic update tool), Postgres **WAL ledger** with deterministic idempotency key (`turn_id|action|canonical-params`) + pre-write field snapshot (undo = compensating update; deletes denied at OAuth scope), custom `External_Id` fields on Quotes/Tasks so even ledger loss cannot duplicate. **Dedicated Gutty Zoho user** (~1 license) so Timeline/audit attributes agent vs human writes natively (R3; attribution mechanism **UNVERIFIED** as an explicit doc statement). Autonomy ladder per action type: 2 weeks shadow against the already-provisioned Zoho **sandbox** (scripts/zoho_smoke_test.py proves it exists) → Ask-first via Cliq buttons → autonomous. Brief F6 requires *no per-write approval at target*: autonomy is reached and **kept** under deterministic write budgets (~30/hr, ~200/day, per-contact caps, catalog-max amounts) whose breach flips all action types back to Ask-first and pings Cliq — anomaly alerts as adoption features, not just safety (Agentforce field data: visible 8% error rates kill rep trust — https://solutions4sf.com/blog/agentforce-b2b-reality-check/).
**Rejected:** raw LLM tool-calls (injection-shaped COQL + no idempotency — R3); Zia digital-employee as the writer (maturity, BAA **UNVERIFIED**, no WhatsApp turn context); permanent human approval (defeats F6).

### L11 · Sales agent (F9) — BUILD (thin, on the spine)
7-slot SPICED-lite qualification: **typed slots stored as Zoho Lead fields** (LLM extracts, code controls next question; max one question per turn — LatAm relational norm, R4), with a marketing/health tier split (health-tier slots ride the PHI path, L13). Bounded objection loop: diagnose → ONE approved value-reframe → payment-terms (TDC +3%) or free 15-min call → escalate with packaged negotiation context; price decompositions precomputed, never LLM arithmetic. **Approved-claims registry + claims classifier on 100% of outbound sales turns** (FTC AI-health-claims scrutiny active 2025–26 — https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance). Mode 3 IS shadow mode: log Gutty's recommended action at tee-up; asesora's decision = free ground-truth label; graduate per product line via gates (offline suite 100% on price/claim probes → ≥50 shadow convs ≥90% agreement, 0 critical → 2-week 10% canary, 100% review of payment-link sends → standing auto-demote). Consultation plans graduate before exam presupuestos. Justification is speed-to-lead + coverage, **not** AI out-closing humans (11x/ZoomInfo evidence — https://techcrunch.com/2025/03/24/a16z-and-benchmark-backed-11x-has-been-claiming-customers-it-doesnt-have/).
**Rejected:** buy AI-SDR (documented 70–80% churn, English/B2B/email-first — R10); freeform persona prompt (slot drift, unauditable).

### L12 · Handoff, tickets & team console (F3) — HYBRID (reuse FSM; Zoho Cliq replaces the WhatsApp team group)
Reuse handoff_state machine + escalation triggers; fix fail-open mute (fsm.py:103–106) and the missing expiry sweeper. Ticket = **Zoho Task + Note + context package** on the Contact/Lead (structured: transcript summary, slots, cadence position, negotiation context). Team surface moves to **Zoho Cliq**: a Cliq bot posts tickets with Tomar/Devolver buttons and a "reply-as-Gutty" command relaying through the kernel — necessary because Cloud API does not support WhatsApp groups (consistently absent from Meta docs; **UNVERIFIED** as an explicit "no"), and native because the team already lives in Zoho. CRM record buttons (Deluge `invokeurl`) mirror the same actions.
**Rejected:** Chatwoot (a second inbox to operate — C3's answer, +1 service +1 UI); keeping the WAHA team group (dies with WAHA); custom ops console (later, if Cliq proves insufficient).

### L13 · Privacy & data-class boundary — BUILD (content-gated split; non-delegable)
GDPR Art. 9 triggers on **content**, not CRM status — a lead volunteering symptoms in message 1 is already special-category data (ICO; R8). Health-content gate mounts on the existing classifier (zero added latency) + Spanish consent micro-flow promotes a conversation to care class mid-thread. Routing: **care = synchronous Anthropic Messages API under BAA only** (Batch explicitly excluded — https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers); marketing = cheaper models/Batch on redacted text. **Zoho side: sign the BAA and enable field-level encryption on Consultas/Examenes + health-tier slot fields** (https://www.zoho.com/crm/data-security/hipaa.html). Fix the two live leaks (raw text → Langfuse, anthropic.py:68–74; raw turn_log) with self-hosted Presidio+GLiNER2-PII + custom V-/E-cédula and RIF recognizers before every derived-store write; VE-WhatsApp-register accuracy is unbenchmarked → build a 100–200-turn in-house redaction eval; redaction is defense-in-depth, never the boundary (R8). Retention: pg_cron purge (12-mo lost leads + suppression tombstones; 30-day unconsented health turns). **Zia is banned from patient content until Zoho confirms Zia/ZKS BAA coverage in writing** (R10).
**Rejected:** everything-is-PHI (kills Batch economics, dishonest — Meta signs no WhatsApp BAA on any path); static lead/patient split (legally wrong).

### L14 · Model layer & routing — HYBRID (thin provider seam; buy inference)
Fix config.py's Anthropic-only lock with a provider seam (code-level; LiteLLM proxy rejected as +1 service for 2 providers). Per brief §4b: **Gemini 3.5 Flash is the leading TIER-1 candidate for marketing-class turns** ($1.50/$9.00, 1M ctx, native multimodal — brief-verified) — confirm via eval/run_eval.py on Spanish-VE cases before commitment; Haiku 4.5 ($1.00/$5.00) as cost fallback; Sonnet-class for sales/objection composition. PHI rule binds: Gemini touches care-class only via Vertex AI + BAA; default care path stays Anthropic sync under BAA. Judge = Haiku-class on 100% of LLM-composed turns (~$5–20/mo — R9).
**Rejected:** Zia BYOK/ZKS as model plane (no Anthropic, 1 USD = 1,000 credits markup path, BAA **UNVERIFIED**); single-provider lock (persona quality is reputational — keep the eval-gated choice open).

### L15 · Observability, evals & learning (F12) — HYBRID
**turn_log + learning_queue stay the authoritative system of record** (already built, PHI-controlled, review workflow + auto-apply-with-rollback designed — R9). Re-instrument the LLM client via OpenTelemetry → **Arize Phoenix single container** on the existing Postgres (Langfuse v2 is maintenance-only; v3 self-host needs ClickHouse+Redis+S3 — https://langfuse.com/self-hosting ; https://github.com/arize-ai/phoenix). Add `--mode crm` to eval/run_eval.py: field-level read-after-write assertions against the Zoho sandbox for every typed write action, + nightly production reconciliation (every write-dispatching turn ↔ matching Zoho record) — the plan-and-parameters eval pattern stolen from Agentforce Testing Center (https://engineering.salesforce.com/inside-the-brain-of-agentforce-revealing-the-atlas-reasoning-engine/). Win-rate proxies = weekly SQL joins turn_log × Zoho Deals. Weekly clustered review lands as a **Cliq digest** (≤2h/wk for María José); per-function cost logging + budget alarms in turn_log from day one (Agentforce cost-ballooning lesson — R10).
**Rejected:** Langfuse v3 (ops), cloud eval SaaS (PHI egress, BAA-gated tiers), judge-gated autonomy without deterministic checks.

### L16 · Internal hygiene automation, Zia pilot & function packaging (F5/F6 hygiene) — HYBRID
Deluge scheduled hygiene jobs where they're trivially native: null-`Contact_Name` Quote report (a real, brief-cited hygiene debt), stale-stage nudges, task-overdue digests → Cliq. **Zia Agents: bounded pilot only** — follow-up scheduler + dedup suggestions + closure reminders, running as its own audited digital-employee identity (the one Zia pattern worth importing: https://www.zoho.com/crm/zia/agentic-ai.html), gated on written BAA confirmation, banned from money path and patient content, kill-switch documented. Honest maturity note: platform launched broadly in 2025–26, no independent production track record at this scope; treat as free leverage inside the fixed Zoho estate, not a foundation. **Function-as-package (F5):** a new function = repo folder (intent seeds + TaskModule + evals + optional cadence definition) **plus a versioned Zoho config manifest** (custom fields, workflow rules, cadence catalog rows, Cliq actions) applied via a provisioning script using Zoho's fields/metadata APIs where possible and an explicit manual checklist where not (some Zoho config is UI-only — honest limit). Fase-2 nutrition follow-up (F5) is then literally: one package = seeds + slots + a multi-day cadence + plan-PDF task + evals, zero central edits.
**Rejected:** Zia as conversational brain or quote writer (verified channel/determinism gaps); unbounded Zia autonomy; treating Zoho config as un-versioned click-ops (drift is C4's #1 self-inflicted risk — see §8).

## 5. Precision & exactly-once design (brief §3's explicit requirement)

1. **One gate, all effects.** Zoho workflows/Schedules/Deluge and MA never call Meta and never write CRM records for the agent — they signal intent to the kernel gate with a natural key. The gate holds the UNIQUE-constrained ledger; Zoho's at-least-once automation semantics (double-fired schedules, workflow retries) physically cannot double-send or double-write.
2. **Idempotency keys everywhere Zoho has none** (verified gap): sends keyed `lead_id|cadence_id|step_no`; writes keyed `turn_id|action|params-hash`; Quotes/Tasks carry a custom unique `External_Id` field so even ledger loss cannot duplicate; identity writes ride upsert `duplicate_check_fields`.
3. **DBOS Transact** (library on existing Postgres — https://docs.dbos.dev/architecture) wraps the few kernel-owned workflows: durable send outbox (fixing WAHA-era fire-and-forget), quote saga (create → verify amount → render → send → stage update, compensating undo from WAL snapshots), webhook inbox dedup. Steps are at-least-once → every external call sits behind the keyed ledger. C4's DBOS footprint is deliberately smaller than C1's: Zoho owns the schedules.
4. **Money is deterministic end-to-end:** Products.`Unit_Price` → Quote line items pinned by id allowlist → deterministic sum + catalog-max cap → regex output guard blocking any un-tabled dollar amount in LLM prose → prices in FAQ strings generated nightly from Products. Zia Quote Generator banned. Discounts never granted — escalated with packaged context (F9).
5. **Send-time predicate re-check:** consent, suppression, `Cadence_Status`, `last_inbound_at`, US-branch, and daily caps are re-evaluated at the moment of send, so stale Zoho signals degrade to no-ops, never to wrong sends.
6. **Graceful degradation:** classifier down → LLM fallback (existing); Zoho API down → gate queues durably and reconciles; Cloud API down → outbox retries with backoff + Cliq alert; kernel down → Zoho keeps accumulating state, reconciliation poller drains on recovery.

## 6. Staged rollout (value-first; weeks 1–3 on the current droplet)

| Stage | Weeks | Ships | User-visible value |
|---|---|---|---|
| S1 CRM hygiene + console | 1–2 | Gutty OAuth user; `Phone_E164` field; COQL parametrization; dedup backfill via Merge API; null-Contact_Name Quote report; Cliq bot skeleton; punch-list security fixes | Team sees a **clean CRM** + first Cliq digests; zero outbound risk |
| S2 Quote button (F2 v1) | 2–3 | CRM record button → kernel builds Quote (pinned ids, amount check) + PDF; asesora reviews & sends; email path via `send_mail` | **Presupuesto in ~1 min instead of 15** — the single biggest per-task save, live in week 2–3 on the droplet |
| S3 Intake + first touch | 2–4 | LeadChain live; ManyChat External Request → normalizer → upsert; single workflow-webhook trigger; Cloud API number provisioned (start verification day 1); first touch <1 min | Every new lead answered in minutes, 100% coverage |
| S4 Cadences (F8) | 3–5 | Lead cadence fields + catalog; Zoho Schedule + kernel poller; send-time gate; consent ledger; US branch; call-touch → Zoho Task | Full toques sequence runs itself; asesoras see cadence state on the record |
| S5 Presupuesto auto + Write Gate ladder | 5–7 | Intent-triggered F2 in Ask-first mode (Cliq approve); Quote_Stage follow-ups; shadow-mode writes vs sandbox → Ask-first | Auto-presupuesto with one-tap approval |
| S6 Sales agent + F4 | 7–9 | F9 mode 3 (slots, objection loop, claims classifier, shadow logging); MA 2.0 weekly campaigns + double opt-in backfill | Qualified, context-packaged handoffs; weekly outbound without manual list work |
| S7 Autonomy + knowledge + learning | 9–12 | F6 per-action autonomous under budgets + anomaly Cliq alerts; Drive ingestion + tacit loop; judge + weekly review digest; Zia hygiene pilot (BAA-gated) | Operator runs without per-write babysitting; knowledge stays current |
| S8 Cutover & retirement | 12+ | Legacy number migration to Cloud API; WAHA + OpenClaw retired; F5 package template documented with nutrition-follow-up dry run | One runtime, one number strategy, Fase-2 seam proven |

## 7. Monthly cost model @ 1,000 leads/mo

**Infra (brief target ≲$150–350/mo, excl. tokens + templates):**

| Item | $/mo | Note |
|---|---|---|
| Droplet (existing, upgraded for Phoenix headroom) | 48 | today 24 |
| Zoho: dedicated Gutty user license | 23–40 | edition-dependent (Professional $23 / Enterprise $40); edition **UNVERIFIED** |
| Zoho Marketing Automation 2.0 | 25–60 | contact-tiered SKU |
| LeadChain extension | 10–25 | marketplace pricing **UNVERIFIED** |
| Zoho Cliq | 0 | free tier suffices for 3 users |
| ManyChat Pro | 0–29 | likely already paid (R1) |
| DBOS / Phoenix / Presidio / pg | 0 | libraries + existing Postgres |
| **Infra total** | **≈106–202** | comfortably inside band; no new always-on services beyond Phoenix |

**Modeled separately (per brief §3):**
- **WhatsApp templates** (Rest-of-LatAm ≈ marketing $0.0625 / utility $0.008 — secondary-corroborated, **primary rate card UNVERIFIED**; R7): first touch (60% marketing-template, 40% CTWA-free) ≈ $38; cadence avg 2 net marketing + 1 utility per lead ≈ $133; F4 campaigns to ~400 customers/wk ≈ $108. **≈ $150–280/mo** (window-aware copy that elicits replies pushes toward the low end; US +1 leads get utility/call-task touches only).
- **LLM tokens:** ~5–8k LLM-composed turns (Gemini 3.5 Flash/Haiku mix) + Sonnet-class sales subset + 100% Haiku-judge + embeddings ≈ **$45–95/mo**.
- **Zoho API credits:** $0 — worst case <8% of the Standard 50k/24h floor (https://www.zoho.com/crm/developer/docs/api/v8/api-limits.html).

**All-in typical ≈ $330–450/mo.** C4's trade is explicit: ~$60–125/mo of SKU spend buys the cadence UI, campaign manager, segmentation, dedup machinery, and audit trail that C1/C3 spend engineer-weeks building and forever maintaining.

## 8. Top 5 risks

| # | Risk | Sev | Mitigation |
|---|---|---|---|
| 1 | **Split-brain policy drift**: business logic smeared across Zoho workflows/Deluge AND the kernel; click-ops config drifts from repo | High | Single-trigger convention (ONE workflow-webhook + ONE Schedule may call the kernel); gates live only in the kernel; Zoho config as versioned manifest in repo + weekly automated drift audit via metadata APIs; any un-manifested workflow flagged in Cliq |
| 2 | **Zoho automation reliability**: Deluge has no durable retry, silent `invokeurl` failures, 10k calls/day cap, Schedule granularity **UNVERIFIED** | High | Zoho only signals intent; kernel 5-min reconciliation poller is the authoritative clock; all effects idempotent behind the gate; daily due-vs-executed health check |
| 3 | **SKU/edition gating & cost creep**: MA 2.0, LeadChain, audit-log, native WhatsApp are edition/SKU-gated; pricing partly UNVERIFIED | Med-High | Week-1 edition/feature confirmation; per-SKU pilot with a named kernel-side fallback (MA→cadence engine handles F4; LeadChain→direct Meta app); budget alarm at $250 infra |
| 4 | **Zia immaturity + BAA gap**: no production track record at this scope; Zia/ZKS BAA coverage unconfirmed | Med | Bounded internal-hygiene pilot only; written BAA gate before any patient-adjacent use; own audited identity; banned from money path; kill-switch |
| 5 | **WhatsApp channel constraints**: no groups on Cloud API (team-group commands die); one-number-one-client (**UNVERIFIED**) blocks Zoho's native inbox alongside the kernel; US marketing block; per-user marketing caps | Med | Cliq replaces the team group (native to C4); bot number owned by kernel, Zoho native inbox not used; country-code branch day one; status-webhook-driven reschedules, never fire-and-forget |

## 9. The −80% logistics story (functions → hours)

Baseline manual logistics at ~1,000 leads/mo (estimates; validate against Zoho activity data in S1):

| Workstream | Today h/mo | With C4 | Saved by |
|---|---|---|---|
| First touch + triage (1,000 × ~5 min) | 83 | ~4 (exceptions) | F7/F8: event-driven first touch, 100% coverage |
| Follow-up toques (manual chasing) | 60 | ~6 (call-task touches) | F8 cadences, reply-kill, re-engagement |
| Presupuestos (~150 × 15 min) | 37 | ~5 (approval taps → autonomy) | F2 quote saga, deterministic amounts |
| CRM data entry, dedup, linking, stage moves | 20 | ~4 (review of anomalies) | F6 Write Gate + upsert/Merge + hygiene jobs |
| Weekly outbound assembly + sends | 12 | ~2 (MA UI edits) | F4 campaigns |
| **Total** | **~212** | **~41** | **≈ −81%** |

Remaining human hours are exactly the brief's "high-judgment" residue: selling on escalated handoffs, payment verification, Ask-first approvals during ladders, María José's ≤2h/wk review. Marketing inbox relief (F10) is additive: uncaught IG DMs get a short reply + funnel automatically. **C4's distinctive bonus:** the team changes cadence copy, campaign segments, and prices (Products module) in Zoho UIs — no engineering queue — so the −80% doesn't silently regress into "waiting on the one developer."

## 10. Open questions carried forward (for judges / red-team)

1. NutriWhite's exact Zoho edition + which features it gates (Cadences module availability, audit-log export, sandbox parity with Consultas/Examenes custom modules).
2. Zoho Schedules minimum granularity and Deluge `invokeurl` failure semantics — determines how much the kernel poller carries (**UNVERIFIED**).
3. Zia/ZKS written BAA coverage; whether Zia can act on custom modules and respect pinned prices (sandbox test before anything F2-adjacent).
4. LeadChain real sync latency, per-lead cost, custom-field fidelity (**UNVERIFIED** — live pilot in S3).
5. Can one WABA number serve both Zoho's native WhatsApp integration and the kernel's Cloud API registration (assumed no; if yes, the native inbox becomes a free human-side console).
6. Zoho Writer merge-to-PDF as a native quote-render path (**UNVERIFIED** — would delete the kernel's PDF renderer).
7. Whether "Modified_By follows the OAuth token owner" is documented officially (attribution assumption behind the Gutty user).

## 11. Why C4 beats its rivals at this scope (advocate's summary)

- **vs C1 (Evolve-Current v3):** C1 builds a cadence engine, identity broker, campaign tooling, and an approvals surface as owned code — then owns their bugs forever, invisible to the ops team. C4 gets each of those as maintained Zoho product surface the team can SEE and EDIT, and spends its build budget on the only genuinely custom assets: persona, RAG, PHI, and the gate. Same kernel hardening is needed either way; C4 simply builds less around it.
- **vs C2 (framework rebuild):** the 2026 evidence (12-factor agents, Anthropic's own guidance) says own the loop; C4 keeps the working FSM and adds zero framework risk.
- **vs C3 (OSS best-of-breed):** Chatwoot+n8n+Windmill is three more services, three more UIs, and a second automation brain for a team of 1–3 — C4 gets inbox-equivalent (Cliq+CRM), automations (workflows/Schedules), and campaigns (MA) inside the platform they already operate.
- **vs C5 (managed-serverless):** Supabase/serverless still leaves the CRM-operator, cadence-state, and campaign layers to be built; C4's insight is that the incumbent platform already ships them.
- **The honest concession:** C4 lives or dies on discipline at the Zoho/kernel boundary (risk #1) and on unverified SKU details (risks #2–3). Its mitigations are structural (single-trigger convention, intent-not-effect signaling, config manifests), not aspirational. If the red-team breaks anything, it will be here — and the fallback for every Zoho-native layer is a named, bounded kernel-side implementation, which degrades C4 gracefully toward C1 rather than collapsing it.
