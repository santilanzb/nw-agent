# R2 — Cadence ("toques") engine + WhatsApp economics

> Researcher R2 · 2026-07-08 · Sources fetched live this session. Anything marked UNVERIFIED could not be confirmed against a primary source.

## 1. WhatsApp Business Platform economics, 2026 state

### 1.1 Pricing model — per-message, not per-conversation

- Meta deprecated conversation-based pricing on **2025-07-01**; billing is now **per delivered template message**, priced by template category × recipient's country calling code, with rate updates allowed only on quarter starts (Jan/Apr/Jul/Oct 1). Current rate cards effective **2026-07-01**. Source: Meta official pricing doc — https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Categories: **Marketing** (charged, no volume discounts), **Utility** (charged outside the service window; volume-tiered), **Authentication** (volume-tiered), **Service** (free since 2024-11-01; the old 1,000-free-conversations construct is gone).
- **Free sends** (the biggest cost lever for a cadence engine):
  - Any non-template message inside an open **24-hour customer-service window** (opened by any inbound user message).
  - **Utility templates inside an open service window** are also free (Meta doc, ibid.).
  - **72-hour free entry point** after a user messages via a **Click-to-WhatsApp ad** or FB Page CTA — *all* message types free for 72h. Sources: Meta doc ibid.; https://www.uptail.ai/blog/whatsapp-business-api-pricing-2026-what-it-costs-and-how-billing-works

### 1.2 Rates relevant to NutriWhite (USD, per delivered message, 2026)

| Market | Marketing | Utility | Notes |
|---|---|---|---|
| **Venezuela / "Rest of Latin America"** | **$0.074** | **$0.0113** | Confirms the brief's ~$0.074 figure. Source: https://mazkara.studio/en/newsletter/whatsapp-penetration-latin-america-2026/ (secondary; Meta's CSV rate card at https://business.whatsapp.com/products/platform-pricing#rates is the primary — page renders rates via JS, could not be scraped this session, so the exact 2026-07-01 figure is **corroborated-secondary, not primary-verified**) |
| Colombia | $0.0125 | $0.0008 | Cheapest LatAm market |
| Mexico | $0.0305 | ~$0.0085 | |
| Brazil | $0.0625 | ~$0.0068 | |
| **USA (+1 numbers)** | **BLOCKED** | $0.004 | See 1.4 |

Marketing is **6.5×** the cost of utility in the Rest-of-LatAm bucket. Utility/auth get volume-tier discounts; marketing never does (Meta doc, ibid.).

### 1.3 Template categorization enforcement (2025–2026)

- Since **2025-04-09** Meta actively scans template content and **recategorizes utility→marketing**, and since 2025-04-16 repeat offenders get recategorized **without the previous 24h notice**. Utility must be strictly tied to an existing user-initiated action (order, booking, request), factual/neutral, no upsell language. Sources: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization ; https://help.egrow.com/en/article/whatsapp-template-category-guide-how-to-keep-your-templates-in-the-utility-category
- Practical implication for F8/F2: **"Aquí está el presupuesto que solicitaste"** (quote the lead explicitly asked for) is a legitimate Utility template ($0.0113). **Cold follow-up touches, re-engagement, review nudges, repurchase reminders are Marketing** ($0.074) — do not try to game the category; recategorization + warnings damage the WABA.

### 1.4 US marketing pause — directly hits NutriWhite's US patients

- Meta **paused ALL marketing-category templates to +1 (US) numbers from 2025-04-01**; as of mid-2026 the pause is still in force with **no announced end date** ("we'll evaluate when the market is ready"). Sends fail with error 131049. Sources: https://help.manychat.com/hc/en-us/articles/19328856186780-Temporary-pause-on-WhatsApp-Marketing-Templates-in-the-US ; https://www.messagecentral.com/blog/whatsapp-marketing-usa-what-is-allowed
- Consequence: the cadence engine MUST branch on country code. US leads/patients can only be reached business-initiated via **utility templates**, **auth templates**, the **72h CTWA window**, or the **24h service window**. Proactive F4 marketing (review nudges, repurchase) to US numbers on WhatsApp is simply not possible today → design an alternate touch type (human call task, email) for +1.

### 1.5 Per-user marketing frequency cap (error 131049 outside the US too)

- Meta caps how many marketing templates any *user* receives **across all businesses** (unpublished; ecosystem reports ≈2/day per recipient). A first-ever message to a lead can bounce because *other* businesses exhausted the recipient's cap. Marketing templates sent **inside an open 24h window do not count** against the cap and deliver. Utility/auth are exempt. Mitigation: treat 131049 as a soft-fail → retry ≥24h later, or wait for a window. Sources: https://help-center.qontak.com/hc/en-us/articles/40306675591449 ; https://blog.campaignhq.co/whatsapp-healthy-ecosystem-error-131049
- Design consequence: **delivery of any given cadence step is not guaranteed** — the engine needs per-step delivery-status tracking (sent → delivered/failed(code)) and rescheduling logic, not fire-and-forget.

### 1.6 Business-initiated volume limits & quality rating

- Messaging limits apply to **unique contacts receiving business-initiated templates per rolling 24h**: unverified 250 → verified 1K → 10K → 100K → unlimited. Auto-upgrade when quality is high and you've used ≥50% of the limit in 7 days; Meta re-evaluates every ~6h (2026); verified businesses can reportedly jump straight to 100K (UNVERIFIED — vendor blog claim). Since **Oct 2025 limits are shared across the whole Meta Business Portfolio**, not per number. Sources: https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits ; https://www.uptail.ai/blog/how-many-messages-can-you-send-on-whatsapp-business-limits-explained-for-2026 ; https://chatarmin.com/en/blog/whats-app-messaging-limits
- Quality rating (Green/Yellow/Red) driven by blocks/reports; low quality → template pausing and tier downgrades. Service-window replies are unlimited and don't count.
- Fit check: 500–2,000 leads/mo = 15–65 new leads/day; even a 5-touch cadence keeps daily unique business-initiated contacts well under 1K. **F4 weekly batches to the existing patient base are the sizing driver** — a 2,000-patient blast in one day needs the 10K tier; batching over a week keeps the 1K tier sufficient. 10× headroom is reachable organically via auto-upgrades; no risk here if quality stays green.

### 1.7 WAHA/unofficial for outbound (re-verification, brief §3)

- WAHA (NOWEB) pairs as a linked device — it **cannot send approved template messages at all**, so official-API pricing/windows don't apply; but Meta ToS prohibit unofficial clients, and 2026 spam heuristics now count **unanswered outbound** (many proactive messages with no replies → flag). Real ban reports exist (e.g., two numbers banned: https://github.com/devlikeapro/waha/issues/1362). "68% of businesses using unofficial tools had a ban event in 12 months" circulates but traces to a vendor blog citing an unverifiable "Meta 2025 Policy Enforcement Report" — **UNVERIFIED, treat as directional**. Sources: https://wapisimo.dev/blog/en/whatsapp-unofficial-api-ban-risk ; https://achiya-automation.com/en/blog/whatsapp-spam-detection-2026/
- Verdict: WAHA is tolerable for **reactive** F1 traffic pre-cutover, but running F8 proactive cadences (hundreds of cold first-touches/week) over WAHA is the textbook high-risk profile (proactive + unofficial + non-repliers). **Official Cloud API is mandatory for the cadence engine.** Losing the production Gutty number mid-rollout would be an existential incident for the whole program.

### 1.8 Cost model at 1,000 leads/mo (F8 + F4, Rest-of-LatAm rates)

Assumptions: 5-step cadence, ~45% of leads reply by step 2 (subsequent touches free in-window), avg **3.2 billable marketing templates per non-replying lead**, ~55% non-repliers; F2 presupuesto sends are Utility.

| Line | Volume/mo | Rate | Cost |
|---|---|---|---|
| F8 cadence marketing templates (naive: all touches marketing, no window exploitation) | ~3,500 | $0.074 | **$259** |
| F8 window-aware (first touch marketing, replies handled in-window, utility where honest) | ~1,400 mkt + 800 util | $0.074 / $0.0113 | **~$113** |
| F8 CTWA-heavy intake (leads arrive via click-to-WhatsApp ad → 72h free) | ~700 mkt | $0.074 | **~$52** |
| F4 monthly-cadence marketing to 1,500 existing patients (1 template/patient/mo avg) | 1,500 | $0.074 | **$111** |
| F2 presupuesto utility sends | 400 | $0.0113 | $4.50 |

**Realistic band: $120–370/mo in template fees at 1k leads/mo** depending on how aggressively the design exploits (a) CTWA 72h windows at intake, (b) reply-first cadence copy that reopens free windows, (c) honest utility classification. This is the same order of magnitude as the entire infra budget — **window engineering is a first-class architecture concern, not an optimization**. Also note: replies routed through CTWA make the *lead-gen ad itself* the cheapest cadence step.

## 2. Opt-in / consent law

- **Meta policy**: documented, explicit, business-named opt-in required before any business-initiated message; opt-out must be easy and honored; missing consent/opt-out handling is the leading cause of WABA restrictions in 2026. Sources: https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in ; https://gmcsco.com/your-simple-guide-to-whatsapp-api-compliance-2026/
- **GDPR (EU-resident leads/patients)**: marketing messages need consent that is freely given, specific, informed, unambiguous (Art. 6(1)(a)); WhatsApp messages fall under the ePrivacy "electronic mail" regime, so the email soft-opt-in exception is at best narrow; German case law effectively requires **double opt-in** evidence. The brief's F4 double-opt-in mandate is the correct bar; extend it to F8 for EU leads. Health-topic replies from a lead escalate the data class to Art. 9 (R8's territory). Source: https://academy.insiderone.com/docs/metas-new-opt-in-policy-and-gdpr-policy-compliance
- **Venezuela**: no omnibus data-protection law and no DPA; constitutional habeas data (Art. 28) + the 2011 TSJ ruling require **prior, free, informed, unequivocal, revocable consent** for collection/use of personal data. A consent-first, opt-out-honoring design satisfies VE by construction. Sources: https://www.dlapiperdataprotection.com/index.html?t=law&c=VE ; https://iapp.org/news/a/venezuela-data-breach-highlights-scattered-privacy-regulation
- Engine requirements derived: an immutable **consent ledger** (who, when, wording shown, source: lead-ad checkbox / ManyChat flow / web form / verbal-logged), per-purpose scopes (transactional vs marketing), a **suppression list** honored synchronously before every send ("no más"/"stop"/emoji-only rejections count), and consent recency checks (Meta best practice: re-confirm stale opt-ins).

## 3. SDR cadence-engine design patterns

Distilled from sales-engagement tooling (Salesloft/Outreach cadence mechanics, Salesforce Agentforce SDR pattern) and queue-engineering practice. No vendor publishes engine internals; the following is the convergent pattern (sources: https://architect.salesforce.com/docs/architect/fundamentals/guide/agentic-patterns.html ; https://www.mo-data.com/mo-sales/what-should-your-sdr-cadence-sequence-look-like/ ; https://help.salesloft.com/s/article/Run-Cadence-Steps ; https://mfyz.com/durable-queue-workers-with-just-postgres):

1. **Cadence definition ≠ enrollment state.** Definitions are versioned, declarative step lists: `(step_no, offset_from_prev, channel, template_ref, precondition, category)`. Enrolled leads pin the version (copy-on-write on edit) so mid-flight leads never see a half-edited sequence.
2. **One enrollment row per (lead, cadence)** with a state machine: `active → replied | converted | opted_out | exhausted | paused_handoff | channel_invalid | failed`. Enforce single active enrollment with a partial unique index. The enrollment row carries `current_step`, `next_run_at`, `last_delivery_status`.
3. **Exit conditions are events, not polls**: inbound reply (kills/pauses pending touches — the inbound webhook must check enrollments synchronously in the turn path), opt-out keyword, deal-stage change in CRM (qualified/won/lost), human claim (F3 handoff), hard bounce (131026 not-on-WhatsApp → `channel_invalid` + human task), cadence exhausted.
4. **First touch is event-triggered, not scheduler-ticked.** Speed-to-lead evidence: contacting within 5 minutes yields ~21× higher qualification odds vs 30 minutes (Oldroyd/InsideSales-MIT study: https://25649.fs1.hubspotusercontent-na2.net/hub/25649/file-13535879-pdf/docs/mit_study.pdf ). The intake pipeline (R1) should enqueue touch #1 immediately; only touches 2..N belong to the scheduler.
5. **Idempotency & exactly-once sends** (brief lens 5): write a send-intent row keyed `(enrollment_id, step_no)` BEFORE calling the transport; store the WhatsApp message id on accept; retry only on transport-level failure, never after acceptance. This is precisely where a durable-execution layer or a carefully-written worker matters.
6. **Delivery-status feedback loop**: webhook statuses (delivered/read/failed+code) update the enrollment; 131049 → reschedule +24h (max 2 retries) or convert the step to an in-window opportunistic send; repeated failures degrade to a human call task.
7. **Send governance**: business-hours + lead-timezone send windows, jitter, per-day global budget, ≤1 marketing template per lead per day, country-code branch (US = no marketing), suppression-list check at send time (not enqueue time).
8. **Human/voice touch as a task type** (F8 requirement): a step whose executor creates a Zoho Task with script + context package instead of sending a message — same enrollment state machine, different effector. This is the clean voice-agent seam: later, the same task type gets a `voice_agent` executor.

## 4. Scheduling infrastructure — honest comparison for a 1–3 person team

Workload reality check: 65 leads/day × ~4 scheduled touches + weekly F4 batches ≈ **300–800 jobs/day, single-digit jobs/minute peak**. Every option below is 1000× over-provisioned on throughput; the differentiators are **durability semantics, ops burden, and where cadence state lives**.

| Option | Verdict | Key facts |
|---|---|---|
| **Simple worker loop** (Postgres table + `next_run_at` + `FOR UPDATE SKIP LOCKED` poll in a sidecar of agent-core) | **Strong fit / baseline** | Zero new infra; cadence state must live in Postgres tables anyway (it's business data the FSM and humans need to see). You hand-write: lease/timeout recovery for crashed sends, idempotency keys, backoff. At this volume the known SKIP-LOCKED failure modes (dead-tuple vacuum spirals at ~800 jobs/sec — https://mfyz.com/durable-queue-workers-with-just-postgres) are irrelevant. |
| **pg_cron + pgmq** | Viable, minor friction | Both are Postgres-native, no new service. BUT the deployed image `pgvector/pgvector:pg16` (docker-compose.yml:3) bundles **neither** — needs a custom Dockerfile (apt `postgresql-16-cron` + pgmq from PGXN) plus `shared_preload_libraries` change = a prod DB restart. pgmq retry = visibility-timeout redelivery only, **no configurable backoff/max-attempts** (https://github.com/pgmq/pgmq via https://supabase.com/docs/guides/queues) — you still write the retry policy in the worker. Net: buys little over the plain table at this volume. |
| **DBOS Transact** (Python library, Postgres-backed durable workflows) | **Strong fit — best durability-per-ops-dollar** | Library inside the existing FastAPI process; workflows/steps checkpointed to Postgres; exactly-once steps, scheduled + delayed workflows, crash recovery for free; no new service to run (https://github.com/dbos-inc/dbos-transact-py ; https://www.tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution). Solves precisely §3.5 (exactly-once sends) and multi-day F5 sequences. Risks: younger ecosystem, single-vendor OSS, Python-version coupling. Was v2's pick; at R2's scope it still holds. |
| **Temporal** (self-host or Cloud) | Overkill | Self-host = 3+ services to operate (frontend/history/matching + its own DB) — disproportionate for this team. Cloud = greater of $100/mo or 5% consumption, 1M actions included (https://temporal.io/pricing ; https://docs.temporal.io/cloud/pricing) — affordable, but adds a second programming model, a vendor, and PHI-adjacent workflow payloads leaving the droplet (BAA question). Choose only if the whole orchestration core moves to Temporal (R5's call), never for the cadence engine alone. |
| **n8n** (self-hosted, Sustainable Use License — free for internal business use: https://docs.n8n.io/sustainable-use-license/) | Poor as cadence owner; fine as intake glue | Schedule trigger has **no backfill** — a missed tick during downtime is silently skipped (https://thinkpeak.ai/scheduling-n8n-workflows-with-cron/ via search synthesis); per-lead multi-day state lives awkwardly in workflow static data or bolted-on DB nodes; production posture needs Postgres+Redis queue mode anyway (https://tobias-weiss.org/content/devops/n8n-production-docker-compose-postgres-redis/). It splits agent policy across two brains — exactly what the brief's extensibility criterion (§3, package-based functions) forbids. Acceptable role: webhook adapters for Meta Lead Ads/ManyChat intake (R1), never the cadence state machine. |

**Recommendation (R2 scope):** cadence state = plain Postgres tables (definitions, enrollments, consent ledger, suppression list, send-intents) owned by agent-core; execution = **DBOS Transact workflows inside agent-core** (or, if the composers reject DBOS, a hand-rolled SKIP-LOCKED worker loop — the delta is ~2 weeks of careful idempotency/recovery code and permanently owning those bugs). Transport = **official WhatsApp Cloud API** for every business-initiated send; WAHA never sends cadence touches.

## 5. Implications the composers must not miss

1. **Template spend rivals infra spend.** $120–370/mo at 1k leads/mo. Architectures that funnel intake through Click-to-WhatsApp ads and design cadence copy to elicit replies (reopening free windows) cut WhatsApp COGS 2–3×.
2. **US branch is mandatory day one** — marketing templates to +1 fail hard (131049), pause 15 months old with no end date.
3. **Delivery is probabilistic** (per-user caps) → the engine needs status-webhook-driven state, not fire-and-forget; this argues for the cadence engine living next to the message-status webhook consumer (agent-core), not in an external tool.
4. **Quality rating is a shared, portfolio-level asset**: one careless F4 blast that draws blocks degrades F1 customer service and F2 presupuesto delivery on the same number. Send governance (caps, batching, suppression) is a reliability feature, not politeness.
5. **Consent ledger + suppression list are schema, not policy prose** — every candidate needs these tables and a synchronous pre-send check.
6. **Utility-vs-marketing honesty**: presupuesto delivery and appointment/payment confirmations are legitimately Utility (6.5× cheaper); everything proactive is Marketing — gaming categorization now carries no-notice recategorization.

## Open questions (for other researchers / the requester)

- Exact 2026-07-01 Meta CSV rate for "Rest of Latin America" marketing/utility — corroborated at $0.074/$0.0113 via secondary sources; someone with browser access should download the CSV from https://business.whatsapp.com/products/platform-pricing#rates to primary-verify.
- What share of NutriWhite's lead base is +1 (US) numbers? Determines how much the US branch (no marketing templates) hurts F4/F8 reach.
- Can Meta Lead Ads intake be shifted toward Click-to-WhatsApp ads? (Changes cadence economics fundamentally: 72h free window + guaranteed opt-in signal.)
- Where does the *first* cadence touch sit legally for an EU-resident lead who filled a Meta form but never messaged first — consent wording on the form must name WhatsApp explicitly (R8 overlap).
- Does the team accept a custom Postgres image (pg_cron/pgmq) or a prod DB restart? If not, DBOS/worker-loop are the only Postgres-native paths.
