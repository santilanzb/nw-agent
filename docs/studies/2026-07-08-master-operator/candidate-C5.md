# Candidate C5 — "Managed-Serverless (Split-Plane)": Supabase Lead Plane + Controlled Care Plane + Meta Cloud API Direct

> **Study:** Cerebro Gutty v3 — Master Operator · **Date:** 2026-07-08 · **Composer:** C5 architect
> **Verdict claim:** the brief's own two-data-class constraint (§3) is not just a compliance footnote — it is an architecture instruction. Roughly 90% of the *new* v3 workload (intake, identity, cadences, template sends, CRM-operator scheduling, IG funnel) is bursty, cron-shaped, content-light, and **marketing-class**. That workload belongs on a managed serverless substrate — **Supabase** (Postgres + pgmq Queues + pg_cron Cron + RLS + Edge Functions) with **Meta Cloud API direct** — where durability, backups, dashboards, and the queue/scheduler substrate are bought, not built. The **care/PHI plane stays on controlled compute** (the already-deployed droplet running agent-core/rag-api/crm-adapter) because the 2026 BAA gate, re-tested honestly below, **fails at this budget for managed data planes**. C5 does not pretend otherwise; it converts the failure into the design.
> Sources: `BRIEF.md`, `recon-code-seams.md`, research packs R1–R10 (same directory). External claims carry URLs, all checked 2026-07-08; unverified items are flagged.

---

## 0. Thesis

C5's bet is different from C1's ("evolve everything in one process on one droplet") and from C2/C3's ("adopt a framework / compose OSS"). It is:

1. **Buy the boring hard parts as managed primitives.** The v3 punch-list is dominated by *reliability substrate* the current system lacks: durable dedup, queues, cron, outbox, backups, admin UI, row-level security. Supabase sells exactly these as Postgres-native primitives — Queues are pgmq with "guaranteed delivery" and "delivered exactly once to a consumer within a customizable visibility window" (https://supabase.com/docs/guides/queues); Cron is managed pg_cron that can fire SQL or HTTP/Edge-Function calls down to per-second granularity (https://supabase.com/docs/guides/cron); RLS + Studio give a free least-privilege admin surface. A 1–3 person team should not hand-operate any of this if $25/mo buys it operated.
2. **Keep the proven conversational spine on controlled compute.** The TurnFSM + embedding classifier + RAG stack is deployed, healthy, and matches the 2026 own-your-loop consensus (https://github.com/humanlayer/12-factor-agents; https://www.anthropic.com/research/building-effective-agents). Rewriting it into Deno Edge Functions (256 MB, 2 s CPU per request — https://supabase.com/docs/guides/functions/limits) would be a downgrade *and* would move patient text into a vendor plane that fails the BAA gate at budget. So conversations — both classes — execute on the droplet.
3. **One clock, two executors.** All scheduling lives in Supabase Cron (managed). Lead-class sends execute in Edge Function workers; patient/care-class sends execute as *send orders* delivered to the droplet, which resolves identity and calls Meta itself. Patient message content and raw patient phone numbers **never rest in Supabase** — the lead plane holds only Zoho record IDs, phone hashes, and schedule state. This is the split design the BAA gate forces, made load-bearing instead of apologetic.
4. **Meta Cloud API direct, no BSP.** Zero platform fee, template legality for F8/F4, CTWA attribution and 72 h free entry windows, and the only path to the future WhatsApp voice seam (R7). WAHA is demoted to a legacy-inbound bridge with a scheduled retirement.

What makes this the *strongest honest* managed-serverless candidate: it refuses the two tempting dishonesties — (a) claiming PHI can ride the serverless plane ("Supabase is HIPAA-ready!" — only at Team $599/mo + paid add-on, 2–4× the entire infra budget), and (b) claiming serverless exactly-once is free (pgmq gives queue-level exactly-once per visibility window; business-level effectively-once still requires the ledger patterns from R3/R5, which C5 builds *once*, in SQL, portable to any Postgres).

---

## 1. The BAA gate, re-tested at 2026 terms (mandated centerpiece)

Legal framing first (R8, verified): HIPAA almost certainly does **not** legally bind NutriWhite (no US covered-entity relationship identified; no extraterritorial reach — https://www.accountablehq.com/post/is-hipaa-international-does-it-apply-outside-the-u-s), and WhatsApp itself can never be literally HIPAA-compliant because Meta signs no BAA for it (https://www.hipaajournal.com/whatsapp-hipaa-compliant/). The binding regime is **GDPR Art. 9** for EU-resident leads/patients (content-triggered, per ICO guidance — https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/). The brief nonetheless imposes HIPAA/BAA as the care-side quality bar (§3), so C5 tests every managed vendor against **both** gates: BAA availability at budget (HIPAA bar) and DPA availability (GDPR floor).

| Vendor / service | BAA in 2026? | Terms | Verdict at ≲$150–350/mo infra |
|---|---|---|---|
| **Supabase** (data plane) | Yes — **paid add-on, Team plan required** | Team "from $599/month" + HIPAA add-on price on top; Pro $25/mo has **no** HIPAA path. Hosted platform only ("controls are not supported out of the box in self-hosted Supabase") | **FAIL for PHI at budget.** PASS for marketing class: DPA available to all customers via dashboard/PandaDoc (https://supabase.com/pricing; https://supabase.com/docs/guides/security/hipaa-compliance; https://supabase.com/legal/dpa) |
| **Vercel** (serverless compute) | Yes — now available to **Pro** teams as an add-on (changelog) | Add-on price unlisted (UNVERIFIED); Secure Compute (isolated networks) remains Enterprise-only | **Conditional pass** for compute — but Vercel provides no data plane, so it doesn't rescue the serverless-PHI story; noted as escape hatch (https://vercel.com/changelog/hipaa-baas-are-now-available-to-pro-teams) |
| **Anthropic** (LLM) | Yes — sync Messages API covered; **Batch API explicitly excluded** | Sales-gated; covered models on 30-day retention | **PASS** for care-class turns, sync only (https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers) |
| **Google Vertex AI** (LLM, Gemini) | Yes — Vertex AI is on GCP's HIPAA-eligible services list under the org-level GCP BAA, no platform surcharge | Consumer Gemini API / AI Studio NOT covered | **PASS** — the one managed AI runtime that passes at budget; this is how the brief's §4b Gemini 3.5 Flash preference reaches PHI legally (https://cloud.google.com/security/compliance/hipaa) |
| **Zoho CRM** (system of record) | Yes — signs BAA (legal@zohocorp.com) + field-level ePHI encryption | No extra fee documented | **PASS** — sign it; encrypt Consultas/Examenes health fields (https://www.zoho.com/crm/data-security/hipaa.html) |
| **Meta WhatsApp Cloud API** (transport) | **No BAA on any path, any BSP** | — | **FAIL permanently** — identical for every candidate C1–C5; mitigation is content minimization upstream, not vendor choice (https://www.hipaajournal.com/whatsapp-hipaa-compliant/) |
| **Inngest** (managed durable execution) | BAA "available as an add-on"; plan/price unpublished (UNVERIFIED) | Hobby free 50k runs/mo; Pro $99/mo | Not needed (see L6); would be eligible for the *lead* plane only (https://www.inngest.com/pricing) |
| **Twilio** (BSP) | Signs BAAs on some products; WhatsApp-channel PHI coverage UNVERIFIED | +$0.005–0.010/msg markup | Rejected as unnecessary middleman (R7) |

**Gate conclusion.** A fully-serverless C5 — everything on Supabase — fails the PHI gate at budget by roughly 2–4× ($599+ vs $150–350). The honest managed-serverless architecture is therefore a **split**: serverless for the lead/marketing side, controlled compute for the PHI side, with managed AI (Anthropic sync / Vertex AI) passing the gate on both. Two upgrade paths are documented, not needed now: (a) if a US covered-entity relationship ever appears, upgrade Supabase to Team + HIPAA add-on (~$599+/mo) with zero re-architecture (same Postgres, same schemas); (b) Vercel Pro BAA + a HIPAA-eligible managed Postgres if the droplet must die. The split is also GDPR-optimal: Art. 9 data gets the controlled plane and explicit-consent micro-flow; marketing data gets DPA-covered managed convenience.

---

## 2. Target architecture (one diagram)

```
                         ┌────────────────────── PLANE S — LEAD/MARKETING (Supabase, managed) ─────────────────────┐
  ManyChat External Req ─►│ Edge Fn: /intake/manychat  ─┐                                                          │
  Zoho workflow webhook ─►│ Edge Fn: /intake/zoho       ├─► intake_events (UNIQUE source+event_id)                 │
  LeadChain (Meta forms)─►│ Edge Fn: /intake/leadchain ─┘        │                                                 │
  Meta status callbacks ─►│ Edge Fn: /meta/status ─► send_statuses (reschedule on 131049/failed)                   │
                          │                                      ▼                                                 │
                          │  IDENTITY BROKER: identities + identity_keys (e164 / wa_id / email_lower / igsid,      │
                          │    UNIQUE constraints, advisory-lock merge, fuzzy→human review) ──► Zoho upsert         │
                          │  CADENCE ENGINE (F8/F4/F5): cadence_definitions (versioned) · enrollments (state       │
                          │    machine, next_run_at) · consent_ledger · suppression_list · country branch (US +1   │
                          │    marketing-blocked) · window-aware template policy                                   │
                          │  Supabase CRON (pg_cron, the ONLY clock) ─► Supabase QUEUES (pgmq)                     │
                          │       ├─ lead-class send_intents ─► Edge sender ─► Meta Cloud API (templates)          │
                          │       ├─ patient/care-class SEND ORDERS ──HTTPS──► droplet outbox (no phone/text here) │
                          │       └─ job ticks ──HTTPS──► droplet (ingest sync, judge, retention, reconciler)      │
                          │  RLS everywhere · Studio = lead-ops console · DATA RULE: no message text, no raw       │
                          │    patient phone — Zoho IDs + SHA-256 phone hashes + schedule state only               │
                          └───────────────────────────────────────────────────────────────────────────────────────┘
                                        ▲ reply-kill / enrollment events (RPC)          │ send orders / job ticks
                                        │                                               ▼
┌─────────────────────── PLANE C — CARE/CONVERSATION (droplet 165.227.73.90, controlled) ───────────────────────────┐
│  /webhooks/meta (Cloud API messages, HMAC) · /webhooks/waha (legacy bridge, retiring)                             │
│  Postgres inbox dedup (replaces fsm.py:39 _SEEN) ─► TurnFSM (reuse) ─► handoff check ─► PRIVACY GATE              │
│    (conversation_class: marketing|care, content-triggered + Art.9 consent micro-flow) ─► classify_intent          │
│    ─► explicit-claim TaskRegistry ─► TaskModules: customer_service(F1) · sales(F9, slot schema, mode-3 shadow)    │
│    · presupuesto(F2) · crm_ops(F6) · mkt_inbox(F10) · nutrition_followup(F5 seam) · TOUCH_CALL stub (voice seam)  │
│  LLM ROUTER: care ─► Anthropic sync Messages (BAA) | Gemini 3.5 Flash via Vertex AI+BAA (eval-gated §4b)          │
│              marketing ─► Gemini 3.5 Flash API / Haiku 4.5; Batch only on redacted text                           │
│  rag-api :8081 (Spanish+unaccent tsconfig, contextual retrieval, intent classifier) · pgvector                    │
│  crm-adapter :8082 + CrmWriteGate (typed actions, crm_write_log WAL+snapshots, autonomy ladder, parametrized      │
│    COQL, dedicated Gutty Zoho OAuth user) ──► Zoho CRM v8 (Leads/Contacts/Deals/Quotes/Tasks/Notes)               │
│  Presupuesto renderer (WeasyPrint PDF, deterministic amounts) ─► Cloud API document send                          │
│  Redactor (Presidio+GLiNER2-PII+VE cedula/RIF recognizers) before EVERY derived store                             │
│  turn_log + learning_queue (system of record) · Phoenix (OTel, single container) · tickets + 1:1 DM claim/resume  │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Design rules that make the split safe:

- **Content boundary:** Supabase stores *no* conversation text and *no* raw patient identifiers. Lead-plane intake stores structured lead-form fields only (name/phone/email from ManyChat flows and Lead Ads — marketing class under DPA); IG free-text is never persisted in Plane S — it is forwarded to the droplet gate or dropped to structured fields. Enforced at schema level (no text columns on cadence/enrollment tables) + quarterly audit query.
- **Clock boundary:** every timer in the system is a Supabase Cron job (managed, observable in Studio). The droplet runs zero schedulers — it only *receives* ticks and send orders. No dueling-scheduler drift.
- **Identity boundary:** Zoho is the customer system of record; the Supabase broker owns *keys and merge state* (R1); the droplet owns *conversation state*. Cross-references are Zoho record IDs + phone hashes.
- **Write boundary:** every Zoho write from either plane flows through the one CrmWriteGate on crm-adapter (droplet) — single choke point, single WAL, single autonomy ladder (R3). Zoho credentials exist in exactly one place.

---

## 3. Layer stack (16 layers; strategy · choice · rationale · rejected)

**L1 · WhatsApp transport — BUY: Meta Cloud API direct (no BSP).**
Per-delivered-message billing since 2025-07-01; Rest-of-LatAm ≈ $0.0625 marketing / $0.008 utility (https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing; exact figures secondary-corroborated — R7); 72 h free CTWA windows; 24 h service window free; messaging tiers auto-scale (250→1k→10k unique contacts — https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits). New number now for outbound; legacy Gutty number migrates at cutover (state lives in Postgres keyed on E.164 — https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/migrate-existing-whatsapp-number-to-a-business-account/). *Rejected:* WAHA for anything business-initiated (template-incapable; ban waves documented — https://github.com/devlikeapro/waha/issues/1362); Twilio (+$0.005–0.010/msg for nothing we need yet); 360dialog (€49/mo wins only ≳10k paid msgs/mo — R7).

**L2 · IG intake — REUSE+BUY: ManyChat (existing) + ref-token wa.me funnel.**
External Request (Pro) pushes structured lead data in real time; the ref-token wa.me link is simultaneously the F10 funnel mechanic and the only deterministic IGSID→wa_id join (R1). IG is intake-only per brief. *Rejected:* direct IG Messaging API app (Advanced Access review, weeks of process for a 1–3 person team); native IG conversations (brief defers); ManyChat as cadence owner (no WhatsApp cadence state, no consent ledger).

**L3 · Ingress & verification — HYBRID: conversation webhooks on droplet; lead-source webhooks on Supabase Edge Functions.**
Meta messages webhook points at agent-core `/webhooks/meta` (lowest latency for the <1 s deterministic-turn budget; Meta's own retry-with-backoff is the buffer if the droplet blips). Edge Functions receive ManyChat/Zoho/LeadChain/status callbacks: verify signature, insert `intake_events` (UNIQUE source+event_id — the durable replacement for the `_SEEN` anti-pattern), ACK <100 ms. *Rejected:* one Edge router for everything (adds a hop to every conversational turn AND rests message content in Plane S — PHI rule violation); single droplet ingress for everything (loses managed durability exactly where sources — ManyChat — never retry, R1).

**L4 · Lead data plane & identity broker — BUY substrate / BUILD schema: Supabase Postgres + RLS.**
`identities`, `identity_keys` (UNIQUE on e164/wa_id/email_lower/igsid), `intake_events` ledger, advisory-lock merge path, country-aware libphonenumber canonicalization (MX 521/AR 549/BR ninth-digit — R1), Zoho upsert with `duplicate_check_fields` + v8 Merge API for repair (https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html). Managed PITR available ($100/7 days) when cadence state becomes business-critical. *Rejected:* droplet Postgres for lead data (no managed backups/Studio/RLS at this ops budget; couples marketing burst load to the care plane); Neon (no queues/cron story); DynamoDB-class stores (wrong tool, team knows SQL).

**L5 · Scheduling substrate — BUY: Supabase Cron (managed pg_cron), the single clock.**
Schedules SQL and HTTP/Edge-Function calls, per-second to annual (https://supabase.com/docs/guides/cron). Drives: cadence ticks, retention purges, reconciliation sweeps, Drive-sync ticks, nightly judge — the last three as HTTPS job ticks to droplet endpoints. Workload is ~300–800 jobs/day (R2) — three orders of magnitude under capacity. *Rejected:* DBOS Transact (excellent library, but it makes the droplet process even more load-bearing — that is C1's bet; C5's bet is managed substrate); pg_cron on droplet Postgres (image doesn't bundle it; custom image + restart — recon); n8n (silently skips missed ticks — R2); Temporal Cloud ($100/mo floor, second programming model, payloads off-infra — R5); Inngest (real contender for the lead plane at free tier, but a second vendor + unpublished BAA terms buys nothing pgmq+cron don't already give — https://www.inngest.com/pricing).

**L6 · Queue & exactly-once ledger — HYBRID: Supabase Queues (pgmq) + built business ledgers.**
pgmq guarantees delivery and "exactly once to a consumer within a customizable visibility window" (https://supabase.com/docs/guides/queues) — that is queue-level. Business-level effectively-once is built once, in SQL, per R3/R5: `send_intents` keyed (enrollment_id, step_no) written *before* transport calls; deterministic idempotency keys (hash of turn_id|action|params) on every Zoho write; explicit backoff columns (pgmq has no configurable backoff — R2); nightly reconciliation (every send intent ↔ Meta status; every write intent ↔ Zoho record). Honest framing: **effectively-once via ledger guards, not literal exactly-once** — the strongest guarantee any candidate can offer against Meta/Zoho APIs, satisfying brief §3 precision. *Rejected:* Redis/BullMQ (new stateful infra); SQS/EventBridge (AWS account + IAM sprawl); fire-and-forget Edge invocations (the current fsm.py failure mode, re-created serverless).

**L7 · Cadence/toques engine (F8, F4, F5 seam) — BUILD on L5/L6.**
Versioned `cadence_definitions`; per-lead `enrollments` state machine (active→replied|opted_out|exhausted|paused_handoff|channel_invalid); first touch event-triggered at intake, not scheduler-ticked (<5 min ⇒ ~21× qualification odds — https://25649.fs1.hubspotusercontent-na2.net/hub/25649/file-13535879-pdf/docs/mit_study.pdf); reply-kill synchronously from the droplet inbound path (RPC → cancel pending intents); consent_ledger + suppression_list checked at enqueue AND at send; country branch — US +1 numbers receive no marketing templates (hard Meta block since 2025-04, error 131049 — R2) and fall back to utility/window/human-call touches; status-webhook-driven rescheduling (per-user marketing caps are unpublished and probabilistic — R2). **Dual dispatch:** lead-class sends execute in the Edge sender; patient/care-class touches (F4 review nudges, repurchase, F5 follow-ups) emit *send orders* to the droplet, which resolves E.164 from Zoho/local state and sends — patient identifiers never rest in Plane S (pharmacy-purchase case law makes even "repurchase nudge scheduled" Art. 9-adjacent — R8). TOUCH_CALL is a first-class task type that today creates a prepared human call task (script + context) in Zoho and later binds to a voice agent (F8 voice seam, R7). *Rejected:* Zoho Marketing Automation (broadcast-shaped; replies never reach the brain — Zoho recon); ManyChat sequences (IG-side only); building cadences on the droplet (re-creates the ops burden C5 exists to avoid).

**L8 · Conversational orchestration (F1, F3, F9, F10) — REUSE: agent-core TurnFSM on the droplet, hardened.**
The FSM stays the reactive router (R5 consensus: own the loop). Punch-list fixes in Stage 0–2: Postgres inbox dedup, constant-time key compare, HMAC fail-closed, bounded ingress queue, per-process httpx clients, canned greetings, explicit-claim registry with collision detection, wire rag-api `/v1/retrieve` + episode memory into the LLM fallback (recon F1). Sales module (F9) = 7-slot SPICED-lite schema, code-controlled/LLM-extracted, bounded one-reframe objection loop, precomputed price decompositions, approved-claims registry + claims classifier on 100% of outbound sales turns; mode-3 launch, mode-2 graduation per product via R4 gates. F10 = short templated IG replies + funnel; free text with health signals goes straight to WhatsApp funnel, never LLM-composed in Plane S. *Rejected:* rewriting the FSM into Edge Functions (2 s CPU/256 MB, Deno vs Python split, PHI into a plane that fails the gate); LangGraph (serialization footguns, worse debugging than the owned loop, still no scheduler — R5); Vertex AI Agent Engine (managed agent runtime under GCP BAA — the one "managed agent tooling" that passes the gate; rejected as a rewrite + lock-in today, documented as the care-plane escape hatch if the team ever wants zero self-hosted orchestration).

**L9 · LLM layer & PHI routing — BUY APIs behind a thin owned router.**
Care class → Anthropic **synchronous** Messages API under BAA today (Batch contractually excluded — https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers); **Gemini 3.5 Flash via Vertex AI under the GCP BAA** is the TIER-1 candidate per brief §4b ($1.50/M in, $9.00/M out; Vertex is HIPAA-eligible — https://cloud.google.com/security/compliance/hipaa), promoted only after `eval/run_eval.py` confirms Spanish-VE quality ≥ Haiku 4.5. Marketing class → Gemini 3.5 Flash standard API or Haiku 4.5 ($1/$5), Batch API allowed on **redacted** text for nightly jobs (50% discount). Router is ~100 lines replacing the Anthropic-only client (config.py:15-16 seam). *Rejected:* consumer Gemini API/AI Studio for anything patient-adjacent (outside BAA); GLM/Zhipu/DeepSeek (China-hosted — brief-blocked); LiteLLM proxy as infra (a service to operate for two providers; use the library or hand-rolled).

**L10 · Retrieval & knowledge (F11) — REUSE + BUILD: rag-api on droplet, upgraded.**
Spanish+unaccent text-search config (the current `simple` tsconfig cripples the lexical RRF leg — recon/R6; schema migration + re-ingest); Anthropic-style contextual retrieval at ingest (~$1 per full re-index at this corpus size — https://www.anthropic.com/engineering/contextual-retrieval); Drive continuous ingestion: one curated "Gutty Knowledge" shared folder, service account, `changes.list` polling with persisted pageToken (Supabase Cron tick → droplet ingest endpoint), markdown export, content-hash skip, tombstone deletes (R6). Tacit pipeline: monthly CDM-style interview → Whisper → LLM-drafted SOP → owner sign-off → Drive folder; turn_log answer-mining through learning_queue with mandatory de-identification. **Graph-RAG committed position (brief §4b):** *seam now, AGE later, care-plane only.* Apache AGE **cannot run on Supabase** — the Nix-built Postgres images do not allow compiling extensions (https://github.com/orgs/supabase/discussions/40285) — which is harmless because retrieval is a care-plane concern. Stage 4 ships typed `kb_entities`/`kb_edges` tables (plain SQL, populated at ingest: service↔exam↔protocol↔condition links) serving deterministic 1-hop expansion; adopt AGE on the droplet's custom pg image at Stage 6 **only if** the retrieval eval set attributes ≥10% of residual misses to multi-hop questions. Ops cost of AGE (custom image beside pgvector, restart) is real and stated. *Rejected:* managed RAG SaaS (vendor + egress to duplicate a working pipeline — R6); external reranker before eval evidence (PHI touchpoint, DPA unverified — R6); moving the KB to Supabase pgvector (splits retrieval from the FSM and routes patient utterances through another boundary).

**L11 · CRM operator & write gate (F6) — BUILD: CrmWriteGate in crm-adapter; Zoho = fixed BUY.**
Enumerated typed Pydantic actions (create_lead, upsert_contact, move_deal_stage, create_quote, create_task, create_note, link_records — no generic update tool); `crm_write_log` WAL with deterministic idempotency key + pre-write field snapshot (undo = compensating update; deletes denied at OAuth scope); staged autonomy ladder per action type: 2 weeks shadow vs the existing Zoho sandbox → Ask-first → auto after ~50 zero-correction approvals; deterministic write budgets (~30/hr, ~200/day, per-contact caps) whose breach flips everything to Ask-first + team alert (R3). Parametrize the injection-shaped f-string COQL *before* widening the surface (zoho_client.py:138-165 — recon). Dedicated "Gutty" Zoho user (~$14–52/mo) for native Timeline attribution. Zoho credits are a non-issue: worst case <8–10% of the Standard 50k/24 h floor (https://www.zoho.com/crm/developer/docs/api/v8/api-limits.html). Record hygiene (dedup via upsert duplicate_check_fields, null-Contact_Name Quote repair via Merge/linking sweeps) ships **before** high-autonomy writes — dirty data, not model quality, is the documented killer of deployed CRM agents (R10, Agentforce field data). *Rejected:* Zia Agents as writer (second brain, Zia-BAA coverage unverified — R10); writes from Edge Functions (Zoho creds in two planes, two audit trails); per-write human approval forever (defeats the mission; it is ladder stage 2, not the end state).

**L12 · Presupuesto pipeline (F2) — BUILD, deterministic end-to-end.**
Zoho CRM **Quotes only** (brief §4b): Quoted_Items pinned by curated Products `id` allowlist (never name-search); `Unit_Price` read from Products cache (synced hourly via Cron tick); deterministic amount check (sum of line items = quote total, catalog-max cap) blocks any mismatch; Quote created via CrmWriteGate with idempotency key (no duplicate quotes); `Quote_Stage` lifecycle moves through the same gate. PDF: Zoho v8 has **no endpoint to fetch the rendered inventory-template PDF** (send_mail is email-only, 20 credits — Zoho recon; https://www.zoho.com/crm/developer/docs/api/v8/send-mail.html), so the droplet renders its own branded PDF (WeasyPrint) from the *same deterministic quote data* and sends it as a Cloud API document message (utility class, $0.008). LLM never touches an amount; it only wraps the delivery message in Gutty's voice from precomputed constants. *Rejected:* Zoho Books (user-forbidden, twice); Zoho send_mail PDF (wrong channel); Edge-Function PDF render (Deno PDF libs weaker than WeasyPrint; quote data is patient-adjacent for exam panels).

**L13 · Privacy plane (two data classes) — BUILD: content-gated dynamic split (R8).**
Health-content gate mounted on the existing classifier (zero extra latency); Art. 9(2)(a) explicit-consent Spanish micro-flow promotes conversations to care class mid-thread; class routes model (L9), observability (redacted), retention. Fix the two live leaks: anthropic.py:68-74 raw text to Langfuse, turn_log raw text — both go through the redactor (Presidio + GLiNER2-PII + custom V-/E-cédula & RIF PatternRecognizers; validated against a 100–200-turn in-house VE-Spanish eval set because **no tool is benchmarked on this register — flagged, not hand-waved** — R8). Retention via Cron: 12-month purge for lost leads + indefinite suppression tombstone; 30-day delete/redact of health turns from never-consented leads; class-keyed trace purges. Plane S data minimization (no text, no raw patient phone) is the structural mitigation that redaction only backs up. *Rejected:* everything-as-PHI (kills Batch economics and is dishonest on a no-BAA transport); static lead/patient split (legally wrong — Art. 9 triggers on content); trusting redaction as the compliance boundary (it is defense-in-depth only).

**L14 · Observability & evals (F12) — REUSE + BUILD: turn_log system of record; Phoenix as lens.**
turn_log + learning_queue (already deployed schema) remain authoritative — review workflow, reseed queue, auto-apply with eval-regression revert (R9). Re-instrument the LLM client once via OTel → Arize Phoenix single container on the droplet (built-in collector, Postgres-backed, evals + annotation bundled; ELv2 free for internal use — https://github.com/arize-ai/phoenix). Langfuse v2 is retired (maintenance-only dead end; v3 needs ClickHouse+Redis+S3 — R9). Nightly judge on 100% of LLM-composed turns (~$5–20/mo at volume — sampling folklore inverted, R9); `--mode crm` deterministic COQL read-after-write evals against the Zoho sandbox; weekly SQL win-rate proxies (turn_log × Zoho Deals); mode-2 graduation gates consume these (R4). Supabase side: Studio dashboards + logs cover Plane S for free. *Rejected:* Langfuse Cloud/LangSmith (PHI egress; BAA tiers cost more than the droplet); staying on Langfuse v2 (no judge, no queues, frozen).

**L15 · Human surfaces (F3 + approvals) — BUILD-minimal.**
Cloud API cannot join WhatsApp groups (consistently absent from Meta docs — UNVERIFIED as an explicit "no"; R7), so the current @Gutty team-group commands cannot migrate. Replacement: real tickets table (droplet, PHI-side) + claim/resume via **1:1 WhatsApp DMs** between Gutty and each asesora ("tomo +58…", "resume +58…" — same command grammar, per-asesora identity, better audit); Ask-first CRM approvals arrive as 1:1 DM cards with approve/deny replies; Supabase Studio is the lead-ops console (enrollments, consent, intake health) with RLS-scoped access for María José; weekly clustered Markdown review ≤2 h/wk (R9). Optional: Claude for Small Business ($20/mo) for approval-gated back-office workflows (R10). *Rejected:* Chatwoot (C3's move — a whole inbox product to operate for a 3-person team); custom React console now (build when Studio + DMs measurably fail); keeping a WAHA session alive just for the group (extends the bannable surface).

**L16 · Function-package contract & migrations — BUILD (extensibility, brief §3).**
A new business function = one package: `intents/<fn>.yaml` seeds + dispatch → task module registering **explicit claims** (collision-checked, no silent first-match) → optional `cadence_definitions` rows (versioned, data not code) → CrmWriteGate policy grants (which typed actions, which autonomy stage) → eval cases → retention class. Zero central-dispatch edits: the classifier routes by embedding, the registry by claim, the cadence engine by definition rows, the write gate by policy rows. F5 (post-consult nutrition) is the proof: it ships later as exactly this package — care-class cadence definitions whose touches are droplet send orders + plan-PDF render. Migrations: Alembic on droplet Postgres from Stage 0 (initdb SQL frozen as baseline — recon); `supabase migration` CLI for Plane S (managed diffing/deploy). *Rejected:* status-quo silent registry + restart-to-reload dispatch (recon F5); a plugin marketplace abstraction (YAGNI at 3 people).

---

## 4. F1–F12 coverage map

| Fn | Where it runs | Key layers |
|---|---|---|
| F1 customer service | Plane C: FSM + deterministic FAQ (facts/prices.yaml single source) + RAG + LLM fallback *with retrieval and history wired in* | L8, L9, L10 |
| F2 presupuesto | Plane C: deterministic quote builder → CrmWriteGate → Zoho Quotes → WeasyPrint PDF → Cloud API utility send | L11, L12, L1 |
| F3 tickets + handoff | Plane C: handoff_state (reuse) + tickets table + 1:1 DM claim/resume + expiry sweeper (Cron tick) | L8, L15, L5 |
| F4 weekly outbound | Plane S schedule + consent/suppression; patient sends execute on Plane C via send orders; double opt-in micro-flow | L7, L13 |
| F5 nutrition seam | Package contract: care-class cadence definitions + plan-PDF renderer; ships later, zero core edits | L16, L7, L12 |
| F6 CRM operator | CrmWriteGate: typed actions, WAL, autonomy ladder, hygiene sweeps, write budgets, Gutty Zoho user | L11 |
| F7 lead intake | Plane S: Edge receivers (ManyChat, Zoho webhook, LeadChain) + identity broker + Zoho upsert/merge | L2, L3, L4 |
| F8 toques cadence | Plane S: event-triggered first touch <5 min, versioned cadences, US branch, TOUCH_CALL human-call task (voice seam) | L7, L5, L6, L1 |
| F9 sales agent | Plane C: slot qualification, objection loop, claims classifier, mode-3 shadow → mode-2 gates per product | L8, L9, L14 |
| F10 MKT inbox | ManyChat short replies + wa.me ref-token funnel; health-signal free text funnels immediately, CRM-inserted via broker | L2, L4, L8 |
| F11 knowledge | Plane C: Drive polling ingestion, Spanish tsconfig, contextual retrieval, tacit CDM loop, freshness TTLs; graph seam | L10, L5 |
| F12 self-learning | turn_log/learning_queue system of record, nightly judge, weekly review ≤2 h, reseed auto-apply with regression revert | L14, L16 |

---

## 5. Value-first staged rollout

| Stage | Weeks | Ships (user-visible value bolded) | Where |
|---|---|---|---|
| 0 — Safety + first touch | 1 | Supabase project + DPA signed; Meta Cloud API number + CTWA link; ManyChat External Request → Edge intake → identity broker v0 → **every new lead gets a first WhatsApp touch within minutes** (event-triggered, free CTWA/utility path). Droplet punch-list fixes: Postgres inbox dedup, HMAC fail-closed, constant-time compare, bounded ingress, Langfuse raw-PHI write disabled, `facts/prices.yaml` single price source | Both (droplet untouched for conversations) |
| 1 — Cadence v1 | 2–3 | Touches 2–4 live (utility/window-aware, US branch, consent ledger, suppression, reply-kill); **daily intake digest to the team**; LeadChain→Zoho→webhook lane verified; **asesoras receive pre-qualified, context-packaged leads instead of raw pings** | Plane S |
| 2 — Conversation cutover | 4–6 | agent-core serves F1 on Cloud API number (retrieval + history wired); privacy gate + consent micro-flow; tickets + 1:1 DM claim/resume replace the group; WAHA demoted to legacy-inbound bridge; **customers get instant, accurate FAQ/RAG service on the official number** | Plane C |
| 3 — Write authority + F2 | 7–9 | CrmWriteGate shadow (sandbox) → Ask-first; record-hygiene sweeps (dedup, null-Contact_Name Quotes); **presupuestos: deterministic quote + branded PDF delivered on WhatsApp with one-tap human approval**; Products cache | Plane C + Zoho |
| 4 — Proactive + knowledge | 10–12 | F4 weekly outbound (double opt-in first); Drive ingestion + Spanish tsconfig + contextual retrieval; kb_entities/edges graph seam; nightly judge + weekly review live; **review nudges/repurchase/referral touches running consented** | Both |
| 5 — Autonomy graduation | 13–16 | Mode-2 gates per product (consultation plans first); write-action autonomy promotions per ladder; F10 short-reply automation; TOUCH_CALL voice-seam stub; legacy number migration completes, **WAHA retired** | Both |
| 6 — Conditional | on evidence | Apache AGE on droplet image if multi-hop eval evidence; Supabase Team+HIPAA upgrade only if a US covered-entity relationship appears; Vertex Agent Engine only if the team wants zero self-hosted orchestration | — |

Weeks 1–3 ship the flagship measurable value — 100% first-touch coverage in minutes (21× qualification odds vs 30-min response) — without touching the production conversation path at all, which keeps early risk near zero.

---

## 6. Monthly cost model @ 1,000 leads/mo

| Item | $/mo | Basis |
|---|---|---|
| Supabase Pro (Queues, Cron, RLS, Studio, micro compute via $10 credit) | 25 | https://supabase.com/pricing |
| Droplet (existing; upgrade to 4 GB to host Phoenix + redactor) | 48 | DigitalOcean standard tier |
| Backups/Spaces + misc | 7 | — |
| **Infra subtotal** | **80** | vs target ≲$150–350 · optional PITR add-on +$100/7-day retention when cadence state is critical → **180** worst case |
| WhatsApp templates: first touch (≈50% CTWA-free) ~$31 + touches 2–4 (~1,320 mktg × $0.0625 + 880 utility × $0.008) ~$90 + F4 (800 × $0.0625) $50 + presupuesto utility ~$1 | **120–250** (mid ≈ 170) | Meta per-message rates, RoLatAm (R7; secondary-corroborated); US +1 leads receive $0 marketing (blocked) |
| LLM tokens: composition ~3.5k turns (Haiku 4.5 $1/$5 or Gemini 3.5 Flash $1.50/$9) $12–25 + slot extraction $5 + nightly judge $10 + claims classifier $3 + redacted Batch jobs $5 + embeddings <$2 | **35–60** | brief §4b prices; R9 judge math |
| ManyChat Pro (existing spend) | 29 | https://manychat.com/pricing |
| Zoho: dedicated Gutty user | 14–52 | edition-dependent (R3) |
| **Total run cost** | **≈ $280–420 all-in; infra-only $80 (base) / $180 (with PITR)** | HIPAA-hardening path documented: +$599+ (Supabase Team + add-on) — *not* required under the split |

---

## 7. Top 5 risks & mitigations

1. **Cross-plane PHI leakage into Plane S** (IG free text with symptoms; misrouted care-class enrollment metadata). *Severity: high.* Mitigations: schema-level no-text rule on Plane S (no content columns to leak into); patient sends leave Plane S as opaque send orders (Zoho ID + template ref only); health-signal check before any lead-plane composition; quarterly audit queries; redactor in front of every derived store. Residual: pseudonymous references (Zoho IDs, phone hashes) remain personal data under GDPR — covered by the signed Supabase DPA, and minimized by design.
2. **Two-plane operational complexity for a 1–3 person team** (split brain, HTTP boundary failures, drift). *Severity: high.* Mitigations: single clock (all timers in Supabase Cron); single write choke point (CrmWriteGate); Zoho as identity system of record; every cross-plane call idempotent + ledgered; nightly reconciliation sweeps; the plane boundary follows the data-class boundary, so it never needs re-litigating per feature.
3. **Effectively-once is still partially DIY** (pgmq exactly-once is per-visibility-window; retries are at-least-once; no native backoff). *Severity: medium-high.* Mitigations: send-intent/write-intent ledgers keyed on business identity written before external calls; explicit backoff/max-attempt columns; reconciliation against Meta statuses and Zoho reads; brief's precision bar met as "effectively-once with audit," stated honestly.
4. **Meta platform dependency** (US marketing block, unpublished per-user caps/131049, quarterly rate-card changes, number quality shared across F1/F2/F8). *Severity: medium.* Mitigations: country branch day one; status-webhook-driven rescheduling, never fire-and-forget; utility-first window engineering; per-function template spend alarms; quality-rating monitoring; number-migration runbook.
5. **Supabase vendor/platform risk** (Edge Fn 2 s CPU/256 MB ceilings; pricing/feature drift; HIPAA locked behind Team $599). *Severity: medium.* Mitigations: Edge code is thin I/O glue (verify→insert→enqueue→HTTP), trivially portable; all state is vanilla Postgres + pgmq + pg_cron — exit = `pg_dump` to any Postgres including the droplet, with the hand-rolled SKIP-LOCKED worker (R2 fallback) as the self-hosted replacement; costs capped at Pro tier; the PHI plane never depends on Supabase at all.

---

## 8. The −80% logistics story (functions → hours)

Baseline estimates at 1,000 leads/mo (to be validated with Stage-0 time tracking; team ≈ 3 ops people, ~480 work-h/mo):

| Workload today | Est. h/mo | After C5 | Saved |
|---|---|---|---|
| F7/F8 intake + first touch + follow-ups (~10 min/lead manual, coverage gaps) | ~167 | Event-triggered first touch + full cadence automated; humans only on escalation touches | ~150 |
| F1 FAQ/service conversations (~600 convs × 6 min) | ~60 | ~80% deflected deterministically/RAG (Klarna lesson: not 100% — edge/emotional cases stay human) | ~48 |
| F9 qualification + context packaging for asesoras (~20 min × 150 qualified) | ~50 | Slots auto-extracted; asesora receives tee-up package; mode-2 products skip human close entirely | ~30 |
| F2 presupuestos (~150 × 15 min) | ~38 | Deterministic build + PDF + one-tap approval (~2 min) | ~32 |
| F6 CRM logging/hygiene (~1 h/day) | ~22 | Auto-writes with audit; human audits ladder promotions | ~18 |
| F4 outbound campaign assembly (~6 h/wk) | ~24 | Cadence definitions + consent engine; human reviews copy quarterly | ~20 |
| F10 IG inbox triage (~5 h/wk) | ~20 | Auto-capture + funnel + CRM insert | ~14 |
| **Total** | **~381** | | **~312 ≈ 82%** |

New human work created: weekly quality review ≤2 h, Ask-first approvals (~15 min/day during ladder stages, shrinking as actions graduate), payment verification (retained by design — F9 mode 2 stops at payment-sent). The story's engine is not "AI out-sells humans" (independent 2026 data says it doesn't — R4/R10); it is **100% coverage at <1-minute first touch** (21× qualification odds), deterministic drudgery elimination (quotes, logging, campaign assembly), and humans concentrated on closes and care judgment.

---

## 9. Judging-lens self-assessment (honest)

- **Cost·Latency:** infra $80–180/mo — the cheapest credible operator substrate of the five candidates; conversational latency unchanged (turns never leave the droplet path). Weakness: cross-plane RPCs add ~50–150 ms to *non-conversational* flows only.
- **Scale·Extensibility:** 10× headroom trivial (Supabase scales the bursty plane; droplet handles conversation volume it already handles); function-as-package contract is explicit (L16). Weakness: packages spanning both planes need two deploy targets (mitigated: cadences are *data rows*, not deployments).
- **Pragmatism·Risk:** lowest self-hosted-infra count of any candidate that still passes the PHI gate (droplet + one SaaS); managed backups/PITR/Studio replace ops nobody on this team will do at 2 a.m. Weakness: two mental models (Deno edge + Python core) — bounded by keeping Edge code to thin glue.
- **Operator fitness (F6–F10):** the operator functions are precisely the ones that live on managed substrate with ledgers and budgets — high autonomy with audit is the design center, not an afterthought.
- **Precision·Reliability:** deterministic money paths (L12), typed writes with WAL/undo (L11), effectively-once ledgers (L6), claims classifier on sales turns (L8). Weakness: literal exactly-once is impossible against Meta/Zoho — stated, ledgered, reconciled.

## 10. Open questions

1. Supabase HIPAA add-on exact price above Team $599/mo (sales-gated) — only matters if the US covered-entity trigger ever fires.
2. Will Anthropic execute a BAA with a small non-US entity (sales-gated — R8)? If not, Vertex+BAA becomes the care-plane default sooner, which brief §4b would welcome.
3. Cloud API group-chat unsupport: consistently absent from Meta docs but no canonical "no" found (R7) — the 1:1 DM ticket surface removes the dependency either way.
4. LeadChain sync latency/fidelity vs the first-touch-in-minutes bar (needs live pilot — R1); escalation path is a direct Meta leadgen app.
5. Gemini 3.5 Flash vs Haiku 4.5 on the Spanish-VE eval set (`eval/run_eval.py`) — gates the TIER-1 model commitment (brief §4b).
6. What share of the base is US +1 numbers — sizes the marketing-template blackout and the human-call/utility fallback load (R2).
