# Study Brief — Cerebro Gutty v3: "Master Operator" Architecture

> **Date:** 2026-07-08 · **Requested by:** NutriWhite (calidad@nutriwhitesalud.com)
> **Method:** Workflow 1 = fan-out research + candidate composition + judge panel + synthesis. Workflow 2 = tournament + red-team.
> **Repo:** `C:\Users\Nutriwhite\Trabajo\05_Proyectos\nw-agent` (read CLAUDE.md first for current-state detail)
> **Study output dir:** `docs/studies/2026-07-08-master-operator/`

## 0. Anchor warning (read this)

A prior study (2026-07-01, "Cerebro Gutty — Arquitectura objetivo v2") chose **Evolve-Current** (keep the FastAPI TurnFSM + embedding-classifier spine; add DBOS sagas, tickets+Chatwoot, presupuesto engine, pg_cron/pgmq outbound, LiteLLM router, Supabase). That verdict is **RE-OPENED**. The scope below is materially broader than what v2 was judged against. Do NOT anchor on v2's winner. Argue from the new scope. It is acceptable — expected, if warranted — to conclude something different. It is equally acceptable to re-confirm Evolve-Current if it genuinely wins again at this scope.

## 1. Mission

Gutty (WhatsApp agent persona — name is fixed) grows from customer-service bot into the **principal operator of NutriWhite's Zoho CRM** and a **proactive sales/lead-ops agent**, cutting the logistics team's workload by **~80%** and meaningfully reducing the marketing team's inbox time. The logistics team narrows to high-judgment work (selling, payment verification, edge cases). The system is a **company brain**: continuously extensible, new business functions plug in as packages without core rewrites, scalable "to all" of NutriWhite's operations over time.

## 2. Functions — ALL must be present in every candidate architecture

Established (from Fase 1 scope, already validated — must not regress):
- F1 **Customer service** on WhatsApp (deterministic FAQ + RAG + LLM fallback, Spanish VE register).
- F2 **Auto presupuesto**: generate + send exam budgets. Mechanism = **Zoho CRM `Quotes` module** (localized "Presupuesto") built from the curated **`Products`** module, with the CRM inventory template (PDF), `Quote_Stage` picklist lifecycle. NOT Zoho Books (superseded decision; verified live in Zoho 2026-07-01). Line items pinned by product `id` allowlist, never name-search. Deterministic amount check.
- F3 **Real ticket system + handoff**: Gutty first contact → ticket for human asesoras with context package; clear claim/resume; deterministic escalation triggers.
- F4 **Proactive weekly outbound** (existing customers): Google review nudges, supplement repurchase, referrals. Double opt-in, approved templates.
- F5 **Fase 2 seam: post-consult nutrition follow-up** (multi-day sequences, plan PDFs) — pluggable later, seam designed now.

New (this study's expansion):
- F6 **Master CRM operator**: full write authority over Leads, Contacts, Deals (stage moves), Quotes, Tasks, Notes in Zoho — autonomous, with audit trail + anomaly alerts (no per-write human approval). Proper record hygiene: dedup, correct linking (Contact↔Deal↔Quote), pipeline stage discipline.
- F7 **Multi-source lead intake**: normalize + ingest leads from (a) ManyChat-style IG automations (webhook), (b) Meta Lead Ads forms, (c) records already landing in Zoho via existing automations, (d) manual entries. Identity resolution across phone/IG handle/email; no duplicate contacts.
- F8 **Proactive lead outreach — "toques"**: a cadence engine that reaches EVERY new lead and executes the full touch sequence (first contact within minutes, spaced follow-ups, re-engagement) via WhatsApp text. **Voice calls are Fase 2+**: design the call-touch as a task type that TODAY creates a prepared human call task (script + context) and LATER can be served by a voice agent. Clear handoff to logistics when a touch needs a human.
- F9 **Sales agent**: qualifies, pitches, handles objections, and — per product line policy — either (mode 3) tees up a human asesora with full context, or (mode 2) goes to payment: sends presupuesto/payment instructions; human verifies payment + marks deal won. **Launch every product in mode 3, graduate to mode 2 via eval gates.** Prices are FIXED: Gutty never alters a price; discount requests escalate with a packaged negotiation context.
- F10 **MKT inbox relief**: IG DMs/questions not caught by automations get captured, answered with a short reply + funnel to WhatsApp, and properly inserted into CRM. **IG is intake-only** (funnel to WhatsApp); native IG conversation is a later pluggable transport.
- F11 **Company knowledge at full breadth**: everything "NutriWhite" — services, exams, prices, protocols, policies, brand voice. Sources: Google Drive docs/PDFs, website/Academy content, and **tacit knowledge** (María José, asesoras, and the founder-level knowledge of the requester) needing a structured extraction pipeline (interviews → SOPs → ingestion). Must keep growing over time (continuous ingestion).
- F12 **Self-learning loop** (retained from v2): review queue, frozen weights, human review; eval gates before behavior changes.

## 3. Hard constraints

- **Persona:** Gutty, Spanish (Venezuelan register). Quality of Spanish is reputational.
- **Privacy:** patient base spans Venezuela/LatAm + EU residents + US persons → GDPR Art. 9 AND HIPAA/BAA both apply to patient-health data. NOTE the two data classes: **lead/marketing data** (not yet health data — GDPR marketing consent rules) vs **patient PHI** (strict). Architectures should exploit this split where honest. PHI never touches a provider without BAA or with disqualifying residency (GLM/Zhipu/DeepSeek China-hosted = blocked). Anthropic Batch API is OUTSIDE the BAA → PHI must use synchronous Messages API. Spanish-VE PHI redaction is unsolved (English-first NER) — flag, don't hand-wave.
- **Volume:** 500–2,000 new leads/month (~15–65/day) + existing patient conversations. Design for 10× headroom, don't gold-plate for 100×.
- **Team:** tiny (1–3 people ops side; María José is quality owner). No platform-engineer hire. Low-ops bias is real but must be weighed against the broadened scope honestly.
- **Budget:** target infra ≲ $150–350/mo pre-scale (excl. LLM tokens + WhatsApp template costs, which must be modeled at the stated volume).
- **WhatsApp:** WAHA/NOWEB unofficial = ban risk for proactive outbound at scale (15–30%/yr claims — re-verify). Official Cloud API for outbound is the presumption to re-test, incl. template pricing (~$0.074/msg marketing LatAm — re-verify current Meta pricing).
- **CRM:** Zoho CRM is fixed (the company runs on it). v8 API, COQL reads, REST writes. Modules: Contacts, Deals(Tratos), Quotes(Presupuesto, custom `Quote_Stage`), Products (curated by calidad@, `Product_Code`/`Unit_Price`/`Product_Category`/`Product_Active`), Consultas (custom), Examenes (custom), Notes. Some Quotes have null `Contact_Name` (hygiene). NO live Zoho access this session — use repo code + public Zoho docs.
- **Latency:** conversational turns must feel instant-ish on WhatsApp (<1s deterministic, ~1–2s LLM-composed).
- **Precision & execution reliability (explicit user requirement):** answers and CRM writes must be precise and accurate — exact prices/amounts (deterministic, never LLM-generated), correct record linking, exactly-once side effects (no double sends, no duplicate quotes), hallucination containment on anything money- or health-adjacent. Sloppy-but-fast loses to precise-and-fast; both are required.
- **Extensibility (first-class criterion):** adding a new business function must be a self-contained package (routing seeds + policy/skill + task handler + optional saga/schedule + evals) with zero central-dispatch edits.

## 4. Current state (verified 2026-07-08)

- Deployed on droplet 165.227.73.90: WAHA (:3000, NOWEB, session NOT yet QR-paired), agent-core FastAPI FSM (:8083, healthy), Langfuse v2 (:3001), rag-api (:8081, hybrid RRF retrieval + intent classifier ~99% on seeds), crm-adapter (:8082, Zoho adapter: COQL reads + Notes writes only), Postgres (pgvector; turn_log, patient_episodes, episode_summaries, patient_facts, learning_queue, handoff_state, intent_vectors).
- OpenClaw (legacy runtime) still serves production WhatsApp; cutover not done. **Nothing of the v2 target design is built.**
- Code punch-list (all still true; verify if you cite): `auth.py:12` `!=` key compare; `fsm.py:39` in-memory `_SEEN` dedup; `fsm.py:104-106` fail-open handoff mute; `main.py:99` unbounded ingress `asyncio.create_task`; `main.py:80` HMAC fail-open on empty key; `classifier_client.py:21` per-turn httpx client; `customer_service.py:173-209` greetings hit LLM; `base.py:24` silent first-match registry; `anthropic.py:69-72` raw PHI to Langfuse; `config.py:15-16` no provider seam; `waha.py:42` inbound media dropped; `patient_facts` lacks temporal validity.

## 4b. User directives (added 2026-07-08 mid-study — binding on Compose/Judge/Synthesize phases)

- **No bias, modern tools fully on the table.** Supabase, Vercel, DigitalOcean, LangGraph and any modern framework are all available and acceptable. Judge every option strictly on merit for THIS business. "We already built X" is a real switching-cost input but not a veto; equally, novelty is not a virtue by itself.
- **Graph-RAG with Apache AGE must be evaluated seriously** as a knowledge-layer option (same Postgres, AGE extension; entity/relationship graph over NutriWhite services/exams/protocols/patient-facts + hybrid graph+vector retrieval). Do NOT auto-defer it the way the v2 study did ("only if multi-hop reasoning justifies") — the user is explicitly open to it. Composers: state a committed position (adopt now / seam now + adopt at stage N / reject) with rationale. Note the ops cost honestly (AGE requires a custom pg image alongside pgvector).
- **Presupuesto = Zoho CRM Quotes ONLY. Nothing with Zoho Books.** (User confirmed again 2026-07-08.) Any candidate that routes presupuestos through Books is wrong.
- **TIER-1 model preference signal:** the user believes **Gemini 3.5 Flash** (released 2026-05-19; $1.50/M in, $9.00/M out, $0.15 cached in; 1M ctx; native multimodal — verified 2026-07-08) offers better product value than Claude Haiku 4.5 ($1.00/$5.00). Note Haiku is cheaper per token and Gemini 3 Flash ($0.50/$3.00) cheaper still; per-turn WhatsApp costs are small either way, so QUALITY-per-dollar in Venezuelan Spanish + latency + multimodal (future media handling) should decide. Treat Gemini 3.5 Flash as the leading TIER-1 candidate to be confirmed by the repo's own eval harness (eval/run_eval.py) on Spanish-VE cases before commitment. PHI routing rules still bind: Gemini touches patient-PHI only via Vertex AI + BAA; the lead/marketing side has more freedom (see §3 privacy split).

## 5. Candidate architectures (compose ALL of these; equal effort each)

- **C1 Evolve-Current v3** — keep FSM+classifier spine; extend to operator brain (intake normalizer, cadence engine, CRM write layer, sales task modules). Prove the spine holds at operator scope or say where it cracks.
- **C2 Agent-Platform Ground-Up** — rebuild orchestration on a 2026 agent framework (evaluate honestly: LangGraph, OpenAI Agents SDK, Claude Agent SDK, Mastra, Temporal-based, etc.) designed from day one as a multi-function operator (reactive + proactive + multi-day sagas as one model).
- **C3 OSS Best-of-Breed** — compose mature OSS: e.g. Chatwoot (inbox), n8n/Windmill (automations/cadences), LiteLLM, existing RAG stack, a workflow engine — custom code only as glue.
- **C4 Zoho-Native Maximalist** — push maximum work INTO the Zoho platform: Zoho Flow/Deluge, Zia agents, SalesIQ, Campaigns, Zoho's WhatsApp integration, Marketing Automation. Custom brain only where Zoho genuinely can't. (New candidate — deserved now that the agent is "principal CRM operator".)
- **C5 Managed-Serverless** — Supabase (DB/queues/cron/RLS) + serverless compute + managed conversational infra (e.g. Twilio/Meta Cloud API direct) + managed agent tooling. Re-test the BAA gate honestly at 2026 terms.

Every candidate MUST: cover F1–F12; give a 14–16 layer stack with reuse/hybrid/build/buy per layer + rationale + rejected alternatives; a value-first staged rollout (what ships in weeks 1–3 on the current droplet, what migrates when); a monthly cost model at 1,000 leads/mo (infra + LLM tokens + WhatsApp templates); top 5 risks with mitigations; and an explicit story for how it achieves the −80% logistics target (map functions → hours saved).

## 6. Research dimensions (Workflow 1 fan-out; researchers use web + repo)

- R1 Lead intake & identity resolution: ManyChat/Chatfuel export mechanics, Meta Lead Ads API (webhooks, retention limits), Zoho workflow triggers/webhooks, dedup & identity-merge patterns (phone/IG/email), 2026 state.
- R2 Cadence/"toques" engine: SDR cadence engines' design patterns; WhatsApp Business messaging windows + template categories + 2026 Meta pricing (per-message vs per-conversation changes!); opt-in law (GDPR marketing + local); scheduling infra options (pg_cron/pgmq vs n8n vs Temporal vs DBOS).
- R3 LLM-as-CRM-operator safety: full-write agent patterns 2026 (audit trails, anomaly detection, idempotency keys, dry-run/shadow modes, staged autonomy); Zoho API v8 rate limits/quotas/bulk APIs; schema-constrained writes.
- R4 Conversational sales agent: qualification frameworks that survive LLM implementation; objection handling with fixed prices; mode3→mode2 graduation gates (eval design); guardrails for health-adjacent selling claims; measured win-rate impacts of AI SDRs (real data, not vendor claims).
- R5 Orchestration core stress-test: at THIS scope (reactive chat + proactive cadences + multi-day sagas + CRM operator + future voice), what do 2026 production systems actually use? Hand-rolled FSM vs LangGraph vs Agents SDKs vs Temporal/DBOS/Restate — evidence of each at comparable scope; failure stories; the honest answer on where hand-rolled cracks.
- R6 Knowledge & tacit extraction: Drive→RAG continuous-ingestion pipelines; website/Academy scraping; interview→SOP structured extraction methods; RAG evolution (contextual retrieval, rerankers, Spanish tsconfig) at broadened domain; keeping prices/facts deterministic vs retrieved.
- R7 Transport strategy: WAHA vs official Cloud API in 2026 (ban-risk evidence, coexistence, number migration); IG→WhatsApp funnel mechanics (link, click-to-WhatsApp ads, ManyChat handoff); voice-agent seam design (what to stub now so voice plugs in later, VE Spanish TTS/ASR maturity).
- R8 Privacy architecture for the two data classes: lead/marketing data vs patient PHI; where the boundary legally sits when a lead discusses symptoms pre-becoming-a-patient (!); GDPR Art.9 + HIPAA split-processing patterns; Spanish-VE PII/PHI redaction 2026 state (Presidio-class tools, multilingual).
- R9 Observability/eval/learning at operator scale: sales-conversation evals, CRM-write correctness evals, turn review UX for a 1-person quality team, Langfuse/OTel 2026.
- R10 Reference scan — how the market builds this in 2026: Salesforce Agentforce, HubSpot Breeze, Zoho Zia agents, Claude for Small Business workflows, AI-SDR products (Artisan, 11x, etc.), WhatsApp commerce agents in LatAm: architecture patterns worth stealing, and cautionary tales.

## 7. Judging lenses (same 3 as v2, plus one)

1. Cost · Latency (build cost, run cost at 1k leads/mo, conversational latency)
2. Scale · Extensibility (10× headroom; new-function-as-package quality; "scalable to all")
3. Pragmatism · Risk (tiny team, low-ops, migration risk, vendor risk, compliance risk)
4. **Operator fitness** (NEW): how well it actually does F6–F10 — the master-operator functions — at high autonomy without human babysitting.
5. **Precision · Reliability** (NEW, explicit user requirement): accuracy of answers and CRM writes; deterministic-first money/health paths; exactly-once execution of side effects; hallucination containment; graceful degradation under partial failure.

## 8. Output conventions (for workflow agents)

- Researchers: Write full notes to `docs/studies/2026-07-08-master-operator/research-<Rn>.md`; return compact structured JSON only.
- Composers: Write full architecture to `docs/studies/2026-07-08-master-operator/candidate-<Cn>.md`; return compact structured JSON only.
- Judges/synthesis: Write to the same dir. Final synthesis = `synthesis.md`.
- Cite sources with URLs for every load-bearing external claim. Mark unverified claims as such. Today is 2026-07-08.
