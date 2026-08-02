# Synthesis — Cerebro Gutty v3 "Master Operator"

> **Study:** `docs/studies/2026-07-08-master-operator/` · **Date:** 2026-07-08 · **Author:** synthesizer agent
> **Inputs:** `BRIEF.md`, `recon-code-seams.md`, `research-R1..R10.md`, `candidate-C1..C5.md`, 3 judge score sets (operator-pragmatist, platform-architect, compliance-precision; 5 candidates × 5 lenses each).
> **Verdict in one line:** **C2 ("gutty-core": Pydantic AI v2 + DBOS Transact, one durable execution model on the existing droplet/Postgres) wins narrowly over C1, conditional on a written Stage-0 spike gate, with C1 as the pre-committed fallback and four losing-candidate grafts folded in — most importantly C3's Chatwoot human console, pulled forward from "optional Stage 5" to a committed Stage-3 deliverable.**

---

## 1. Aggregate scoreboard

Per-lens scores are the mean of the three judges. Overall = mean of the three judges' per-candidate averages. Scale 1–10.

| Candidate | Cost · Latency | Scale · Extensibility | Pragmatism · Risk | Operator fitness | Precision · Reliability | **Overall** | Rank |
|---|---|---|---|---|---|---|---|
| **C2 — Agent-Platform Ground-Up (Pydantic AI + DBOS)** | 7.67 | **8.67** | 6.00 | **7.67** | **8.33** | **7.67** | **1** |
| C1 — Evolve-Current v3 (FSM spine + 4 subsystems) | **8.00** | 7.00 | **8.00** | 7.33 | 7.67 | 7.60 | 2 |
| C5 — Managed-Serverless (Supabase split-plane) | **8.00** | 6.67 | 6.00 | 6.67 | 6.67 | 6.80 | 3 |
| C3 — OSS Best-of-Breed (Chatwoot/n8n/LiteLLM) | 6.67 | 6.67 | 5.00 | **8.00** | 6.33 | 6.53 | 4 |
| C4 — Zoho-Native Maximalist | 6.00 | 5.00 | 5.33 | 7.00 | 6.00 | 5.87 | 5 |

Per-judge overall averages and rankings:

| Judge | C1 | C2 | C3 | C4 | C5 | Ranking |
|---|---|---|---|---|---|---|
| operator-pragmatist | **7.6** | 7.4 | 6.8 | 6.0 | 7.0 | C1 > C2 > C5 > C3 > C4 |
| platform-architect | 7.4 | **7.8** | 6.2 | 5.6 | 6.4 | C2 > C1 > C5 > C3 > C4 |
| compliance-precision | 7.8 | **7.8** (tiebreak to C2) | 6.6 | 6.0 | 7.0 | C2 > C1 > C5 > C3 > C4 |

### 1.1 Judge concordance and the one disagreement worth adjudicating

The panel is unusually concordant: **no per-lens spread across judges exceeds 2 points**, and only one lens hits exactly 2 — **C4 scale/extensibility** (operator-pragmatist 6 vs platform-architect 4, compliance 5). Adjudication: **the architect is closer to right.** The Deluge 10k `invokeurl`/day cap is the only candidate-specific 10× cliff in the study, and a "package" that bottoms out in a Zoho click-ops manifest with an admitted manual UI checklist structurally fails the brief's zero-central-edit package criterion (§3). The pragmatist's 6 gave credit for team-editable cadence copy/segments/prices — a real virtue, but it belongs in operator fitness (where all three judges gave C4 a 7). Effective consensus: C4's extensibility is a 4–5, and its rank-5 finish is robust.

Second-order note (not a numeric disagreement, but a framing split): the pragmatist ranks C1 first on the 3am-question and surfaces-to-keep-alive logic; the architect and compliance judge rank C2 first on uniform-durability and uniform-idempotency logic. All three explicitly agree on the same hinge: **C2's margin exists if and only if the Stage-0 DBOSAgent spike holds; if it fails, C1 takes rank 1.** That agreement is what makes the winner declaration below safe to act on.

### 1.2 Why the precision lens decided it

C1 and C2 are ~80% the same design — same Meta Cloud API transport with retiring WAHA bridge, same intake bus + identity broker, same classifier/RAG reuse, same CrmWriteGate policy, same cadence tables, same presupuesto saga, same privacy split, same Phoenix observability, same DBOS library. The fork is *where durability lives*:

- **C1:** DBOS beside the FSM; reactive turns outside durable execution; exactly-once re-derived per seam with hand-placed guards (inbox, outbox, WAL, cadence keys). C1's own High risk #2 names the failure mode: a guard bug = double send/double quote — the exact failure the brief (§3 precision) forbids.
- **C2:** every unit of work (turn, touch, saga, write plan) is a checkpointed workflow; idempotency keys derive mechanically from workflow identity; HITL approvals, retries, multi-day sleeps, and dedup are one primitive; typed/schema-validated write payloads fail before Zoho; the payload-by-reference rule keeps PHI out of checkpoint blobs (a GDPR Art.17 erasure gap C1-as-written leaves open). The compliance judge scored this 9 vs C1's 8 and it broke the tie; the architect scored scale/extensibility 9 because packages are framework-typed objects that fail at import, not in production.

The brief's two new lenses (operator fitness, precision/reliability) were added precisely because v3's scope makes time + exactly-once the dominant axis. On that axis C2's structural answer beats C1's disciplined answer. On every axis where C1 wins (pragmatism 8.00 vs 6.00 is the largest gap in the study), the gap is exactly the framework-novelty risk the spike gate is designed to retire or expose within two weeks.

---

## 2. Winner: C2, spike-gated, with C1 as the pre-committed fallback

**Provisional winner: C2 — "gutty-core" (Pydantic AI v2 + DBOS Transact as one durable execution model), on the existing droplet and Postgres, with all proven assets (intent classifier ~99% on seeds, hybrid RRF RAG, crm-adapter, handoff_state schema, turn_log/learning_queue) reused byte-for-byte.**

Conditions attached (these are part of the verdict, not caveats to it):

1. **Stage-0 spike with a written pass/fail rubric** (≤2 weeks, before anything ships): (a) DBOSAgent wraps a real turn workflow and survives crash-recovery on the droplet; (b) a deferred-tool (`requires_approval=True`) workflow pauses and resumes correctly across a process restart; (c) deploy-versioning semantics for in-flight multi-day workflows are understood and workable (DBOS pins recovery to application version — UNVERIFIED detail per C2 §12.1); (d) chaos kill mid-saga produces zero duplicate sends. Sources: https://pydantic.dev/docs/ai/integrations/durable_execution/dbos/, https://ai.pydantic.dev/deferred-tools/, https://github.com/dbos-inc/dbos-transact-py (MIT verified by two candidates + judges).
2. **On spike failure: build C1 without re-litigation.** Same tables, same seams, same rollout; the FSM stays, the guards go in by hand, DBOS is used narrowly (or replaced by C1's priced SKIP-LOCKED worker fallback, ~2 wks). All three judges pre-agreed this branch; treating it as a branch instead of a new study saves a month.
3. **The grafts in §3 are mandatory**, because the judges' shared #1 concern about the C1/C2 spine — the thin human surface — is the single most likely place the −80% quietly stalls.

Why not C1 outright, given its pragmatism win and the razor-thin 0.07 margin? Because the two candidates' *costs* are symmetric but their *upsides* are not: C1's advantage (no framework ramp, no port) is a one-time ~2-week saving; C2's advantage (uniform durability, typed packages, one HITL primitive, mechanical idempotency) compounds with every future function package — and "continuously extensible company brain" is the mission sentence (BRIEF §1). The spike converts C2's main risk from a standing bet into a cheap, early, falsifiable test — C2's own words: "cheap, early, and decisive" (candidate-C2.md §11). Two of three judges independently reached this conclusion; the third concedes C2's uniform-durability argument is "the strongest single architectural idea in the study."

---

## 3. Grafts from losing candidates (mandatory unless marked optional)

| # | Graft (source) | What, concretely | Where it slots |
|---|---|---|---|
| G1 | **Chatwoot human console, pulled forward** (C3) | Self-hosted Chatwoot (MIT) as the asesoras' working surface: one-click ask-first approvals (rendered from `DeferredToolRequests`), ticket claim/resume, context-package display, IG inbox mirror, CSAT + agent reports. **Console + mirror only, never in the send path** — gutty-core keeps direct Cloud API ingress/egress, so C3's UNVERIFIED Agent-Bot hop latency and retry semantics are never load-bearing. Chatwoot's Postgres DB must be wired into the retention/purge design (the compliance judge's standing objection to C3: a second PHI-bearing store outside the 12-mo/30-d purge). Commit at **Stage 3** (when ask-first volume starts), replacing "optional Stage 5". All three judges flagged the group-command/DM approval surface as the throughput cap on the residual 20% of conversations — which is what caps the −80%. Cost: ~1 container set (Rails+Redis+Sidekiq), likely the 8GB droplet already planned; second-droplet fallback +$24–48 if RAM forces it (C3 cost model). | New L17 (human console) serving F3 + F6 ask-first + F10; retires the WAHA team group |
| G2 | **Nightly Zoho Products → `facts/prices.yaml` pull** (C4) | The Products module (curated by calidad@) is the single price source; a scheduled workflow regenerates `facts/prices.yaml`, FAQ price strings, and eval assertions nightly. The team edits prices in the Zoho UI with zero engineering queue; the dollar-amount output guard keys off the same generated table. Best price-single-sourcing in the study (compliance judge, C4 justification). | L13 knowledge facts + L11 presupuesto composer |
| G3 | **Team-editable cadence content** (C4) | Cadence copy lives in Meta's template library (the team already edits templates there for approval) and in versioned `cadence_definitions` data rows referencing template names + variables — never in code. Add a lightweight edit path (Chatwoot-adjacent admin page or reviewed sheet-sync) so cadence timing/copy changes don't queue on the one developer. This is C4's one genuinely superior story ("the −80% does not silently regress into waiting on the one developer") imported without its split-brain cost. | L9 cadence engine |
| G4 | **Schema-level no-raw-text rule for workflow state** (C5) | Harden C2's payload-by-reference *convention* into a *structural* rule: workflow input/step-output Pydantic models expose no free-text fields — only typed references (turn_log ids, enrollment ids, template refs, Zoho ids). Enforce with a CI check over workflow signatures + a quarterly audit query over DBOS checkpoint blobs. Closes the checkpoint-blob PHI/erasure gap for good rather than by memory. | L4 durable substrate + L14 privacy |
| G5 | **Vertex AI + GCP BAA as the legal Gemini-for-PHI route** (C5) | If the §4b eval prefers Gemini 3.5 Flash and the business later wants it on care-class turns, the only lawful managed route at budget is Vertex AI under the GCP org BAA (https://cloud.google.com/security/compliance/hipaa — verified by C5; consumer Gemini API is NOT covered). Document it now; stand it up only if/when the eval + user decide. | L5 model routing |
| G6 | **Spike fallback pre-commitment** (C1) | C1's priced SKIP-LOCKED worker + per-seam guard design is the written Plan B, on the identical schema. The Stage-0 spike rubric (§2.1) plus this pre-commitment turn "framework risk" into a two-week bounded experiment. | Stage 0 |
| G7 | **Zoho-native hygiene arm** (C4) | Before any autonomy: Merge Records API dedup backfill, null-`Contact_Name` Quotes report, unique `Phone_E164` field + upsert `duplicate_check_fields` (already in C2 L3), and Timeline/Recycle Bin (60-day restore) as the native undo complement to the WAL snapshots. Zoho's machinery executes; the identity broker decides. | L3 identity broker + L10 WriteGate, Stage 1–2 hygiene sweeps |
| G8 | **Instrumented −80%** (C3) | Week-1 manual time log (validates the 9.5 h/day baseline assumption); `resolved-without-human` KPI in turn_log from Stage 1; post-G1, Chatwoot agent reports as the free measurement plane. Baseline at Stage 1, tracked at every stage gate. C3 was the only candidate that measured the mission instead of asserting it. | L15 observability / F12 |
| G9 | **Single-clock law** (C5) | DBOS is the only scheduler in the system. No pg_cron, no n8n timers, no Zoho Schedules calling the brain. Any platform-side automation (Zoho workflow rules) may only *signal intent* into the intake bus; the brain's clock decides execution. Prevents the dueling-scheduler drift that sank C4. | L4 design law |
| G10 | **Weekly config-drift audit** (C4) | Automated diff of deployed surface (Meta template library, cadence rows, registered Zoho workflow webhooks) vs the repo manifest; unmanifested config flagged to the team surface. Cheap insurance imported from C4's own mitigation for its #1 risk. | L16 ops |

Explicitly **not** grafted: C3's n8n (second-brain anti-pattern; connectors are two webhook routes — R1/R2), C4's Marketing Automation 2.0 (its F4 sends bypass the one-gate law — the internal inconsistency the compliance judge caught), C5's Supabase plane (adds a vendor to the PHI story for queues/cron DBOS provides in-process; both single-process judges concur).

---

## 4. The v3 proposal — full layer stack (C2 + grafts)

Strategy legend: REUSE / HYBRID / BUILD / BUY.

| Layer | Choice | Strategy |
|---|---|---|
| L1 Transport | Meta Cloud API direct for ALL business-initiated sends from Stage 1 (new number now; legacy migrates at cutover, Coexistence if eligible); WAHA = retiring legacy-inbound bridge only | HYBRID |
| L2 Ingress bus | `/webhooks/{meta,waha,manychat,zoho}` per-source verified normalizers → transport-neutral `InboundEvent` → durable `intake_events` inbox (UNIQUE source+event_id), ACK after insert; **DBOS workflow id = inbox event id** (redelivery cannot double-process) | BUILD |
| L3 Identity broker | Postgres `identity_registry` (country-aware E.164, wa_id, email, IGSID; advisory-lock merges; fuzzy → human review) + **G7** Zoho upsert `duplicate_check_fields` / Merge API / hygiene sweeps | BUILD |
| L4 Durable substrate | DBOS Transact (MIT) in-process: scheduled cron, durable sleep, checkpointed steps, priority/rate-limited queues (Zoho concurrency + Meta pacing as config) + **G9** single-clock law + **G4** no-raw-text workflow payloads | BUY |
| L5 Agent framework & models | Pydantic AI v2: typed Agents/tools, structured outputs, deferred tools as the single HITL primitive, DBOSAgent checkpointing. Routing: care → Anthropic sync Messages under BAA (Batch excluded — https://privacy.claude.com/en/articles/8114513, primary-verified by compliance judge); marketing → Gemini 3.5 Flash eval-gated vs Haiku 4.5 (§4b); **G5** Vertex+BAA documented for Gemini-on-PHI | BUY |
| L6 Conversation reactor | ~400-line `turn_workflow`: identity → privacy gate → fail-degraded mute check → classify → package dispatch → agent run → outbox send; every stage a checkpointed step; eval-harness parity gates the F1/F3 port | BUILD |
| L7 Package runtime | Package = {Agent+toolset, seeds fragment, workflows/schedules, pydantic-evals Dataset, write-policy manifest}; registrar with explicit-claim collision detection + rag-api dispatch hot-reload; malformed packages fail at import | BUILD |
| L8 Intent spine | rag-api `/v1/classify_intent` + `intent_seeds.yaml` + seeder, byte-for-byte; add hot-reload + sales/objection seed families | REUSE |
| L9 Cadence engine | Versioned `cadence_definitions` + enrollment workflows with durable sleep; consent ledger + suppression per send; send-intent rows before transport; reply-kill in turn workflow; US(+1) branch; TOUCH_CALL→Zoho Task (voice seam); window engineering (CTWA 72h, utility-first) + **G3** team-editable cadence content | BUILD |
| L10 CRM WriteGate | Enumerated typed write actions; `crm_write_log` WAL with workflow-derived idempotency keys + pre-write snapshots; ladder shadow→ask-first(`requires_approval`)→auto per action type; write budgets + kill-switch; dedicated Gutty Zoho user; nightly read-after-write reconciliation + **G7** Timeline/Recycle-Bin undo complement | HYBRID |
| L11 Presupuesto (F2) | Deterministic composer from Products id-allowlist → twice-computed amount check → Zoho **Quotes** (`Quote_Stage`) → local HTML→PDF (no Zoho API returns the rendered PDF) → WhatsApp utility document send → durable-sleep follow-up; one checkpointed saga; never Zoho Books | BUILD |
| L12 Sales agent (F9) | 7-slot SPICED-lite via structured outputs (code controls, LLM extracts); bounded one-reframe objection loop with precomputed price decompositions; claims registry + classifier on 100% of sales turns; tee-up = deferred tool (asesora decision = free ground-truth label); mode-3-as-shadow → per-product mode-2 gates | BUILD |
| L13 Knowledge (F11) | Reuse rag-api/pgvector; Spanish+unaccent tsconfig; contextual retrieval (~$1/re-index); Drive `changes.list` connector as scheduled workflow; tacit CDM interview loop; **G2** nightly Products→`facts/prices.yaml` + dollar guard; Graph-RAG/AGE = seam now (entity tables), Stage-5 adoption only on >20% multi-hop eval failure | HYBRID |
| L14 Privacy | Content-gated marketing/care split at the classifier mount + Art. 9(2)(a) consent micro-flow; Presidio+GLiNER2+VE cedula/RIF redaction before derived stores (defense-in-depth, never the boundary — VE register unbenchmarked, flagged); retention workflows (12-mo lost leads, 30-d unconsented health turns) + **G4** structural no-text rule over checkpoints | BUILD |
| L15 Observability & learning (F12) | turn_log + learning_queue authoritative; Pydantic AI OTel → Arize Phoenix (1 container; Langfuse v2 retired); 100% judge on LLM-composed sales turns (~$5–20/mo); `--mode crm` read-after-write evals + nightly reconciliation; weekly ≤2h review; reseed auto-revert + **G8** resolved-without-human KPI + time-log baseline | HYBRID |
| L16 Data & ops | Same droplet (8GB), same pgvector image; Alembic from Stage 0; nightly pg_dump to Spaces; staging = MockCrmAdapter + Zoho sandbox + test number; net containers shrink post-cutover + **G10** weekly config-drift audit | REUSE |
| **L17 Human console (new, G1)** | Chatwoot self-hosted as console + mirror: ask-first approval cards, claim/resume, context packages, IG inbox, agent reports; never on the send path; retention-wired | BUY |

## 5. Staged rollout (C2's plan + graft insertions)

| Stage | Weeks | Ships | Graft deltas |
|---|---|---|---|
| 0 — Spike + seed | 1–2 | gutty-core container (FastAPI+DBOS+Pydantic AI) on current droplet; **Stage-0 spike vs written rubric (§2.1)**; durable inbox; `facts/prices.yaml` + dollar guard; Alembic baseline; F1 ported as turn_workflow with RAG + episode memory wired for the first time; eval parity gate vs OpenClaw; BAA letters initiated | **G6** fallback pre-commitment signed; **G8** week-1 time log runs now |
| 1 — Cutover + first touch | 2–3 | Production WhatsApp cutover to gutty-core; Cloud API number live; intake bus + identity broker MVP; every new lead first-touched <5 min (event-triggered F8 slice); IG capture → wa.me ref-token funnel → CRM insert (F10 MVP); LeadChain latency pilot | **G7** hygiene sweeps begin (Merge backfill, null-Contact_Name report); **G8** KPI baseline |
| 2 — Cadence + shadow authority | 4–6 | Full cadence engine (touches 2..N, consent, suppression, US branch, TOUCH_CALL); handoff context package + sweeper; F9 mode-3 slots with shadow-label tee-ups; CrmWriteGate shadow vs Zoho sandbox; **chaos-test acceptance: kill mid-saga → zero duplicates** | **G3** cadence content editable as data rows; **G2** nightly Products pull live |
| 3 — Operator authority + console | 7–10 | Autonomy ladder ask-first→auto per action type (F6) via deferred tools; presupuesto end-to-end (Quotes + PDF + WhatsApp doc) in mode 3; F4 weekly outbound; nightly write reconciliation | **G1** Chatwoot live as the approval/claim surface (+~1 wk vs C2's plan); WAHA team group retired here instead of Stage 5 |
| 4 — Knowledge + learning | 11–13 | Drive connector + Spanish tsconfig + contextual re-index; tacit interview loop; F12 closes (100% sales-turn judge, weekly ≤2h review, reseed auto-revert); Phoenix live, Langfuse v2 retired | **G10** drift audit scheduled |
| 5 — Graduation + seams | months 4–6 | Mode-2 graduation for consultation plans via gates; legacy number migration; WAHA/OpenClaw/agent-core fully retired; AGE multi-hop eval gate decided; voice pilot decision (Calling API seam stubbed since Stage 1) | — |

Build effort: **~12–15 engineer-weeks** (C2's 11–14 + ~1 for Chatwoot config/retention wiring; G2/G3/G9/G10 are days, not weeks).

## 6. Cost model @ 1,000 leads/mo (winner + grafts)

Unchanged from the C1/C2 convergent model — grafts add ≈$0 licenses (Chatwoot MIT) and possibly $0–48 droplet/second-droplet headroom:

| Item | $/mo |
|---|---|
| Droplet 8GB + backups (Chatwoot RAM measured; +$24–48 second-droplet fallback if forced) | 53–101 |
| Zoho Gutty user | 14–52 |
| WhatsApp templates (2,000 cadence mktg × $0.0625 + 1,000 F4 × $0.0625 + 2,000 utility × $0.008; RoLatAm rates secondary-corroborated — primary CSV verification open) | ≈204 (band 130–320) |
| LLM (conversational ~$15–24 eval-decided; extraction/claims ~$15; judge + redacted Batch ~$15) | ≈54 |
| Embeddings | ≈5 |
| Licenses (Pydantic AI, DBOS, Chatwoot MIT; Phoenix ELv2; Presidio MIT) | 0 |
| **All-in** | **≈$330–420** (infra-only ≈$70–150, inside the $150–350 target which excludes tokens/templates) |

Dominant sensitivity: template spend; shifting ad spend to Click-to-WhatsApp (72h free window) pushes to the low end.

## 7. What the tournament (next workflow) should stress-test hardest

1. **The Stage-0 spike claims** — DBOSAgent deferred-tool pause/resume across process restarts; deploy-versioning of in-flight multi-day workflows (both UNVERIFIED by C2's own admission). This is the load-bearing hinge of the whole verdict.
2. **Chaos exactly-once** — kill gutty-core mid-presupuesto-saga and mid-cadence-touch; assert zero duplicate quotes/sends on recovery; probe the residual "crash mid-step after external call landed" window at the Meta and Zoho seams.
3. **F1/F3 port regression** — is eval-harness parity (generation + intent) plus turn_log traffic replay actually sufficient to protect live customer service at cutover?
4. **G4 red-team** — hunt a code path where raw message text lands in a DBOS checkpoint blob despite the no-text rule (e.g., exception payloads, retry context, agent message history).
5. **Human-approval throughput** — simulate ask-first volume at 1,000 leads/mo pre- and post-Chatwoot; find the point where the approval queue, not the agent, caps the −80%.
6. **Cost-band adversarial check** — primary verification of the Meta RoLatAm rate card; template volume if reply rates halve; error-131049 per-user-cap behavior under F4 batches.
7. **WAHA ban-window exposure** — quantify pre-cutover risk on the legacy number and the acceleration option.
8. **Identity broker edge cases** — MX 521/52, AR 549, BR legacy ninth digit round-trips; fuzzy-merge queue volume estimate.
9. **VE-Spanish redaction recall** — the in-house 100–200-turn eval set design; what recall number is "good enough for defense-in-depth" and who signs it.
10. **Chatwoot containment** — verify it can be run mirror-only (no send path) with retention wired; measure RAM; confirm the degradation story (console dies → operations continue).

## 8. Open decisions for the user

1. **Approve the spike-gated branch plan** (C2 with written go/no-go rubric; C1 fallback without re-study).
2. **Chatwoot at Stage 3** — accept +1 self-operated service (Rails/Redis/Sidekiq) in exchange for asesora throughput, vs staying on DM approvals to Stage 5.
3. **Provision the Meta Cloud API number + Business verification now**; decide legacy-number migration timing (check Coexistence eligibility of the current Gutty number).
4. **Execute Anthropic + Zoho BAAs in writing** (Stage-0 launch gates); feasibility for a small non-US entity is unconfirmed.
5. **Run the §4b model eval** (Gemini 3.5 Flash vs Haiku 4.5, Spanish-VE) and sign off the marketing-class model; decide whether to stand up Vertex AI + GCP BAA now or defer (G5).
6. **Confirm budget** ≈$330–420/mo all-in; appetite for CTWA ad-spend shift to cut template costs.
7. **Buy the dedicated Gutty Zoho user license** ($14–52/mo edition-dependent) and confirm sandbox access for shadow mode.
8. **Assign the week-1 time log** (the 9.5 h/day baseline the −80% is measured against is a stated assumption until logged).
9. **LeadChain vs direct Meta Lead Ads app** after the Stage-1 latency pilot (LeadChain pricing/latency UNVERIFIED).
10. **Who approves ask-first actions day-to-day** until the console lands, and the share of +1 US numbers in the base (sizes the F8/F4 US branch).

---

### Appendix — per-judge notes (condensed)

- **operator-pragmatist** (ranked C1 first, 7.6): discriminators were surfaces-to-keep-alive, the 3am question, migration risk, and the −80% evidence base. Found every candidate's −80% claim "plausible-but-unproven" on the same evidence (100% first-touch <5 min at 21× qualify odds + drudgery absorption; explicitly NOT AI out-closing humans). Urged the synthesis to bolt C3's console onto the C1/C2 spine rather than leave it Stage-5 optional — adopted (G1). Called C2's uniform-durability argument "the strongest single architectural idea in the study" while docking it for stacked framework bets — resolved by the spike gate.
- **platform-architect** (ranked C2 first, 7.8): C2 is the only candidate where all four workload shapes (reactive/proactive/saga/write-plan) share one checkpointed execution model; package quality ordering C2 > C1 > C5 > C3 > C4; C4's Deluge cap is the study's only 10× cliff; caveat that C2's margin "rests entirely on the Stage-0 spike holding" — adopted verbatim into the verdict conditions.
- **compliance-precision** (C1/C2 tied 7.8, tiebreak to C2): independently verified the repo punch-list (`auth.py:12`, `fsm.py:39`, `anthropic.py:68-74` live Langfuse PHI leak), the Anthropic BAA Batch exclusion (https://privacy.claude.com/en/articles/8114513, primary), and Supabase hosted-only HIPAA posture (https://supabase.com/docs/guides/security/hipaa-compliance). Decisive findings: C2's workflow-derived idempotency + payload-by-reference rule close gaps C1 leaves open (checkpoint-blob PHI = GDPR erasure gap); C4 has an internal F4 inconsistency (MA 2.0 native sends bypass its own one-gate law); C3's Chatwoot is a second PHI store outside its retention design — which is why G1 requires retention wiring.

**Not anchored on v2:** the v2 winner's lineage (C1) placed second on the merits of the new precision lens; the panel's C2 verdict follows from the v3 scope itself — at operator scope, time + exactly-once dominate, and that flips the owned-thin-loop consensus's own logic.
