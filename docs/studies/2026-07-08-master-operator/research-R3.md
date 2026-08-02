# R3 — LLM-as-CRM-operator safety (Cerebro Gutty v3 Master Operator)

Researcher: R3. Date: 2026-07-08. Note: the orchestrator's brief path arrived as `undefined`; scope reconstructed from the task description + repo CLAUDE.md + the v2 architecture artifact (https://claude.ai/code/artifact/a7de0eb8-8e3a-41f2-b6ec-d9800e7f99be, fetched 2026-07-08). F1–F12 definitions were NOT available — flagged as an open question.

## 1. Current state (repo-verified)

- **Write surface today is Notes-only.** `src/company_agent/crm_adapter/zoho_client.py` — reads via COQL, single write path `create_note_on_contact()` (REST POST /Notes). "Full CRM write authority" for v3 is a categorical jump, not an increment.
- **Injection surface exists before writes even land:** COQL queries are built by f-string interpolation (`find_contact_by_email` interpolates the email straight into the COQL string, zoho_client.py:160–165; phone suffix likewise). Today inputs are phone numbers (normalized to digits — safe-ish); once an LLM with write authority supplies arbitrary params, every interpolated COQL string is an injection vector. Parametrize/escape as a precondition to any write expansion.
- **A Zoho sandbox is already provisioned and smoke-tested** (`scripts/zoho_smoke_test.py`, `scripts/zoho_inspect_sandbox.py`, `ZOHO_SANDBOX` in `CrmSettings`). This is a free, already-working shadow-mode target.
- The v2 artifact already commits to the right primitives for writes: DBOS Transact wrapping multi-step sagas with "claves de idempotencia antes de cada llamada externa" (Layer 02), curated allowlist examen→item_id for estimates, "chequeo determinista de monto + confirmación humana" in Etapa 1, and single-agent-for-writes ("un solo agente para escrituras, HITL explícito").
- `turn_log` already SHA-256-hashes phone numbers — extend the same convention to the write ledger (PHI containment).

## 2. Zoho CRM v8 API facts (verified against zoho.com, 2026-07-08)

Source: https://www.zoho.com/crm/developer/docs/api/v8/api-limits.html

- **Credits (24h rolling window):** Free 5,000; Standard 50,000 + 250/user (cap 100k); Professional 50,000 + 500/user (cap 3M); Enterprise/Zoho One 50,000 + 1,000/user (cap 5M); Ultimate 50,000 + 2,000/user.
- **Credit costs:** insert/update/upsert = 1 credit per 10 records (max 100 records/call); COQL = 1–3 credits by LIMIT; Convert Lead = 5; **Bulk Write initialize = 500 credits**; Mass Convert = 200. Exceeding → `TOO_MANY_REQUESTS`.
- **Concurrency:** 5/10/15/20/25 simultaneous calls by edition; sub-concurrency 10 for heavy ops (COQL, bulk).
- **Scale math for this business:** 2,000 leads/mo × ~10 writes each ≈ 670 writes/day ≈ ≤67 write-credits + ~2–6k read-credits/day — **1–10% of even the Standard-edition floor. Rate limits are a non-issue; concurrency (10–20) is the only limit an agent retry-storm could hit.**
- **Bulk Write API:** async CSV job, up to 25,000 records / 200 columns per job (https://www.zoho.com/crm/developer/docs/api/v8/bulk-write/overview.html). Relevant only for backfills/migrations at this volume; Timeline history is captured for bulk-write updates too (help.zoho.com community thread).
- **No idempotency-key mechanism.** The upsert API (https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html) is the closest native surrogate: `duplicate_check_fields` (system-defined fields like Email, or custom fields marked unique) decide insert-vs-update, and the response carries `"action": "insert"|"update"` per record. `If-Unmodified-Since` exists for optimistic concurrency, not idempotency. **Exactly-once must be built client-side.**

## 3. Undo / recovery from wrong writes (verified)

Three native Zoho mechanisms:

1. **Recycle Bin restore API** — `POST /crm/v8/settings/recycle_bin/{id}/actions/restore` (single + bulk); restoring a record also restores its Recycle-Binned Notes/Attachments/Activities. **60-day window, then permanent** (https://www.zoho.com/crm/developer/docs/api/v8/restore-recycle-bin-records.html; help.zoho.com Kaizen #235).
2. **Timeline API** — per-record `field_history` with field API name + **old and new values**, actor, audited_time (https://www.zoho.com/crm/developer/docs/api/v8/timeline-of-a-record.html). This is per-record undo data, but view-only (no export).
3. **Audit Log export API** — async job, CSV/ZIP, up to 1,000,000 entries, up to 3 years back (https://www.zoho.com/crm/developer/docs/api/v8/create-export-audit-log.html). **Edition-gated:** help docs say audit log on Enterprise/Ultimate (one source says Professional+) — https://help.zoho.com/portal/en/kb/crm/security-control/audit-log/articles/monitor-audit-log. NutriWhite's edition is unknown → treat native audit log as unavailable and build your own.

**Practical undo strategy:** updates are the dangerous class (deletes can simply be denied to the agent; creates are visible and low-harm). Native Timeline gives old values post-hoc, but the robust pattern is **read-before-write snapshot**: the write gate reads the touched fields, stores `{action_key, module, record_id, old_values, new_values, actor=gutty, turn_id}` in a Postgres `crm_write_log`, then writes. Undo = compensating update from `old_values` (idempotent, replayable). This also gives you an audit trail independent of Zoho edition and keeps PHI audit data in-house.

## 4. How the CRM vendors gate autonomous writes (2026)

- **Salesforce Agentforce:** topics + **enumerated actions** (never free-form), configurable guardrails on by default, flows can require approval/escalation "based on risk, context, or sensitivity"; 2026 positioning stresses audit trails + HITL as the scaling constraint (https://admin.salesforce.com/blog/2026/the-importance-of-human-in-the-loop-for-agentforce; https://architect.salesforce.com/fundamentals/agentic-patterns; https://www.reco.ai/hub/agentforce-security).
- **HubSpot Breeze:** two explicit autonomy modes per agent — **review-before-send vs fully autonomous** — plus guardrails that apply *even in autonomous mode*: send windows, min-days-between-touches, max-emails-per-enrollment, exclusion lists; vendor guidance is "start in review mode, graduate after watching drafts" with weekly audit reviews (https://knowledge.hubspot.com/prospecting/use-the-prospecting-agent; https://www.onthefuze.com/hubspot-insights-blog/hubspot-breeze-ai-agents-2026).
- **Zoho Zia Agent Studio (July 2025 launch):** agents are **registered in Zoho Directory with their own identity, role, and profile "like any user — so every action it takes is auditable"**; admin-controlled roles/permissions per agent; custom guardrails (e.g., discount limits); 700+ enumerated actions (https://www.zoho.com/crm/zia/agentic-ai.html; https://futurumgroup.com/insights/zoho-unveils-zia-llm-no%E2%80%91code-agent-studio-and-open-agent-interoperability/).

**Convergent pattern across all three:** (a) enumerated typed actions, never raw API access; (b) the agent is a first-class *identity* with its own least-privilege permission set; (c) autonomy is *per action type* and graduated review→auto; (d) hard guardrails (caps, exclusions, windows) survive full autonomy.

## 5. Cross-industry production patterns (2026)

- **Staged autonomy ladder:** shadow mode (~2 weeks minimum) → review-before-write → autonomous for low-risk actions → autonomous in-policy; confidence thresholds on every production agent; "Three-Tier Boundary System": Always / Ask-first / Never as explicit policy config (https://iain.so/security-for-production-ai-agents-in-2026; https://www.digitalapplied.com/blog/human-in-the-loop-escalation-design-ai-agents-2026; https://ancaonuta.medium.com/what-ai-agents-can-actually-run-unsupervised-and-what-they-cant-f7756504d270).
- **Idempotency:** generate + persist the idempotency key *before* the external call / approval interruption so a resumed or retried flow runs exactly once ("the difference between a recoverable incident and a runaway one") — same source set. DBOS Transact (already chosen in the artifact) provides this shape natively.
- **Identity + audit:** per-agent OAuth clients/keys, default-deny, unique agent identity separate from any human; unified audit trail answering "which user, task, tool, and policy gate produced this write" (https://tyk.io/learning-center/ai-agent-api-governance-auth-audit-trails-and-zero-trust/; https://www.ibm.com/think/tutorials/ai-agent-security).
- **Anomaly detection:** at enterprise scale this is ML-on-telemetry (https://www.wiz.io/academy/ai-security/llm-guardrails); at 1–3-person scale the right translation is **deterministic write budgets**: per-hour/day write caps per module, distinct-contacts-touched cap, monetary caps on estimates, and a kill-switch that flips all actions back to Ask-first when a budget trips.
- **Attribution in Zoho:** API writes are attributed to the user who authorized the OAuth refresh token (token is user-specific) — so a **dedicated "Gutty" Zoho user** makes Timeline/audit distinguish agent vs human writes, mirroring Zia's agent-identity pattern. UNVERIFIED against a single official doc page, but consistent across Zoho OAuth docs (https://www.zoho.com/crm/developer/docs/api/v8/oauth-overview.html) and integrator guides. Costs one extra license (~$14–52/user/mo by edition).

## 6. Options considered

| # | Option | Verdict |
|---|--------|---------|
| A | Direct LLM tool-calls to Zoho write endpoints, no gate | REJECT — no idempotency, no undo, injection surface, uncapped blast radius |
| B | **CrmWriteGate in crm-adapter**: typed Pydantic write schemas per action; policy table `action_type → {shadow, approve, auto}`; Postgres write-ahead ledger (idempotency key + pre-write snapshot); deterministic caps | **RECOMMEND** — one choke point, edition-independent audit, fits existing FSM + INTERNAL_API_KEY seam |
| C | Zoho Zia Agent Studio does the writes | REJECT for v3 — second orchestration brain, PHI through Zia LLM/cloud, poor fit with WhatsApp-first FSM, lock-in; its *identity* pattern is worth copying |
| D | Permanent human-approval-for-everything | SAFE BUT DEFEATS THE MISSION — use only as ladder stage 2 |
| E | DBOS-wrapped saga writes + compensating undo + Recycle Bin/Timeline recovery | ADOPT as complement to B for multi-step flows (estimate + note + deal update) — already the artifact's Layer 02 choice |

## 7. Recommendation (for 500–2,000 leads/mo, 1–3 person team, PHI)

Build **Option B + E**, concretely:

1. **Single choke point:** every agent write goes through crm-adapter (never a new direct path). New `/v1/crm/write/{action_type}` endpoints with strict Pydantic schemas — enumerated actions (create_lead, update_lead_status, create_estimate, create_note, update_deal_stage…), enumerated writable fields per action. No generic "update record" tool.
2. **Idempotency + audit ledger (build, ~1–2 days):** Postgres `crm_write_log` — deterministic `action_key = hash(turn_id | action_type | canonical_params)`, unique index; pre-write field snapshot (old values) fetched in the same transaction scope; response `action: insert|update` recorded. Undo = compensating update from snapshot; deletes denied to the agent entirely (drop delete scopes from the OAuth grant; use only `ZohoCRM.modules.{...}.{READ,CREATE,UPDATE}` — least privilege at the token, not just the prompt).
3. **Staged autonomy ladder, per action type:** (i) 2 weeks **shadow** against the existing sandbox (log intended writes, execute nothing in prod); (ii) **Ask-first** via the team WhatsApp group (`@Gutty aprueba <id>` — the group-command plumbing already exists in the FSM); (iii) **auto** after N consecutive approvals with zero corrections (suggest N=50 per action type). Estimates keep the artifact's deterministic amount cap + human confirmation until Etapa 3 at least.
4. **Deterministic anomaly budgets, not ML:** e.g., ≤30 writes/hr, ≤200/day, ≤1 write per contact per intent per day, estimate amount ≤ catalog max; tripping any budget flips ALL actions to Ask-first and posts to the team group. This is the 1–3-person-team translation of "anomaly detection".
5. **Dedicated Gutty Zoho user** owning the refresh token, so Timeline/`Modified_By` separates agent from human writes (one extra license).
6. **Preconditions:** fix COQL string interpolation before granting write params to the LLM; keep the write ledger phone-hashed per the existing turn_log convention (PHI stays in-house; don't ship write telemetry to third-party anomaly SaaS).

Zoho API cost impact: zero incremental (credits are far under any paid-edition floor); do NOT buy Enterprise just for the native audit log — the WAL replaces it.

## 8. Open questions

1. Which Zoho CRM edition does NutriWhite run? (audit-log availability, credit ceiling, sandbox entitlement — the sandbox demonstrably exists, so likely Professional+.)
2. Does the sandbox mirror the custom modules (Consultas, Examenes) and can Zoho Books estimates be shadow-tested at all (Books has no sandbox equivalent — UNVERIFIED)?
3. Brief F1–F12 were unreachable (brief path `undefined`): which functions actually need write authority beyond estimates/notes/lead-field updates? The ladder design depends on the full action inventory.
4. Where should Ask-first approvals land long-term — team WhatsApp group (now) vs the planned ops console (artifact's future UI)?
5. Is one extra Zoho license for the agent identity acceptable, or is token-owner attribution under an existing user's account tolerable for audit?
