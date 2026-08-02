# Tournament Advocacy Brief — Champion for C5 "Managed-Serverless (Split-Plane)"

> **Study:** Cerebro Gutty v3 — Master Operator · **Stage:** Tournament · **Date:** 2026-07-10
> **Advocate for:** `candidate-C5.md` (Supabase lead plane + controlled care plane + Meta Cloud API direct)
> **Against:** `synthesis.md` provisional winner C2 (`candidate-C2.md`, Pydantic AI v2 + DBOS "gutty-core")
> All new external claims below were re-verified by live fetch on **2026-07-10**; URLs inline. Claims I could not verify are marked UNVERIFIED. This brief is honest by design: §5 concedes where C2 genuinely wins.

---

## 1. The best case for C5, in one paragraph

C5 is the only candidate whose architecture is **derived from the brief's constraints rather than bet against them**. The two-data-class privacy split (§3 of the brief) is not a compliance footnote — it is a fact about the workload: ~90% of the *new* v3 work (intake, identity, cadence scheduling, template sends, IG funnel) is bursty, cron-shaped, content-light marketing-class work, and the remaining conversational/PHI work already runs, healthy, on controlled compute. C5 buys the reliability substrate the punch-list proves this team cannot hand-operate — queues, cron, backups, RLS, an admin console — as **GA managed Postgres primitives for $25/mo** (pgmq: https://supabase.com/docs/guides/queues; pg_cron: https://supabase.com/docs/guides/cron), and keeps the proven droplet spine for every conversational turn, so latency and PHI posture are untouched. Every load-bearing component of C5 is either **already deployed and healthy** (agent-core, rag-api, crm-adapter, Postgres) or **boring, multi-year-GA infrastructure**. C2, by contrast, rebuilds the orchestration heart of a money-and-health-critical operator on a framework pairing whose stable major version was **15 days old on study day** and whose two most load-bearing behaviors were — by C2's own admission (§12.1–12.2) and by the synthesis's own words ("the load-bearing hinge of the whole verdict") — **unverified at the moment it was declared the winner**. A tournament should not crown a coin-flip. C5 asks the judges to weigh a certainty: *the flagship value of this study — 100% first-touch coverage in under five minutes, the single input to the −80% target with actual evidence behind it (21× qualification odds) — survives a droplet outage, a bad deploy, and a framework regression under C5, and survives none of them under C2.*

---

## 2. What the scoreboard got right about C5 — and what it mispriced

The synthesis scoreboard (synthesis.md §1): C5 = 6.80 overall (rank 3), C2 = 7.67 (rank 1). Three observations before the attacks:

1. **C5 already won a piece of this tournament.** Three of the ten mandatory grafts onto the winner are C5's ideas: **G4** (structural no-raw-text rule over checkpoint state — closing what the compliance judge called C2's "GDPR erasure gap"), **G5** (Vertex AI + GCP BAA as the only lawful Gemini-for-PHI route at budget), and **G9** (single-clock law). The winning design needed C5's safety discipline to be declared safe. That is not what losing looks like; it is what being the study's compliance-and-reliability brain looks like.
2. **C5 tied C2 on the lens where C2 is weakest** — Pragmatism·Risk, both 6.00 — and *beat* C2 on Cost·Latency (8.00 vs 7.67). C2's margin lives entirely in Scale·Extensibility (8.67 vs 6.67) and Precision (8.33 vs 6.67), and both of those scores were awarded **conditional on an unrun spike** (§3.1 below) and **before** the graft that quietly demolished C2's ops story (§3.4 below).
3. **C5's Precision 6.67 undersells a structural fact:** C5 is the only candidate in which the PHI/no-text rule is enforced by *schema* (no content columns exist in the plane that holds schedule state), not by convention, CI check, or reviewer memory. The synthesis itself ranked that idea highly enough to make it mandatory (G4) — it just scored the candidate that originated it as if the idea belonged to someone else.

---

## 3. Attacks on C2

### 3.1 — The verdict is a conditional, and the condition is still unverified (SERIOUS)

The synthesis is explicit: "C2's margin exists **if and only if** the Stage-0 DBOSAgent spike holds; if it fails, C1 takes rank 1" (synthesis.md §1.1), and lists the spike claims as "the load-bearing hinge of the whole verdict" (§7.1). I re-checked the two hinge behaviors on 2026-07-10:

- **Deferred-tool pause/resume across process restarts:** the official DBOS integration page for Pydantic AI (https://pydantic.dev/docs/ai/integrations/durable_execution/dbos/) contains **no discussion of deferred tools or human-in-the-loop across restarts at all** (verified by fetch 2026-07-10). C2's entire autonomy ladder — the mechanism for F6, mode-3→mode-2 graduation, and discount escalation — rests on an interaction between two libraries that the integration's own documentation does not describe. This is not "documented pattern, mechanics to confirm" (C2 §12.2's framing); it is undocumented behavior at the exact intersection C2 needs.
- **What the docs *do* document is unfriendly:** pickle serialization of all workflow inputs/step outputs with a recommended ~2 MB cap; `Agent.run_stream()` unsupported inside workflows; dynamic toolsets raising `UserError` if passed per-run (same page, fetched 2026-07-10).

A tournament winner whose #1 risk mitigation is "we pre-committed to building the runner-up instead" is functionally a **two-week delay on the real decision**. C5 has no equivalent gate: pgmq and pg_cron semantics are documented, GA, and already carrying production workloads across thousands of Supabase projects; the conversational spine is the code already running on the droplet. If the judges' actual confidence in the spike is p, the honest expected value of "C2" is p·C2 + (1−p)·C1 minus two burned weeks — and nobody on the panel stated p.

### 3.2 — Framework churn is not a hypothetical; it is measurable, and it is extreme (SERIOUS)

C2 (§2 caveat 4) concedes "Pydantic AI moved fast to v2" and the synthesis notes "v2.6.0 released 2026-07-08" as if it were evidence of maturity. Verified against the release page on 2026-07-10 (https://github.com/pydantic/pydantic-ai/releases):

- **v2.0.0 stable: June 23, 2026** — after seven betas. The "stable" major version of C2's core framework was **15 days old on study day**.
- **Nine releases in sixteen days**: v2.0.0 (06-23) → v2.1.0 (06-29) → v2.2.0 (06-30) → v2.3.0 (07-01) → v2.4.0 (07-02) → v2.5.0 (07-03) → v2.5.1 (07-06) → v2.6.0 (07-07) → v2.7.0 (07-08) → **v2.8.0 (07-09)**. A v1→v2 major with a published upgrade guide (i.e., breaking changes) shipped less than a year into the framework's stable life.

This is a healthy, fast-moving project — and precisely the wrong dependency posture for a **1–3 person team with no platform engineer** (brief §3) to place underneath a PHI-handling, money-writing operator. Every one of those minor releases is a decision the one developer must make: upgrade (and re-run parity evals over a surface that includes model classes, deferred tools, and the DBOS wrapper) or pin (and watch the gap to upstream grow while the `DBOSAgent` integration — "the newest piece of the pairing," C2 risk #1 — tracks a moving target on both sides). C2's mitigation ("the used surface is narrow… worst case is vendoring") means the worst case is *this tiny team maintaining a private fork of an agent framework*. C5's equivalent dependency surface is: Postgres, pg_cron, pgmq, and the team's own already-running Python — the newest of which is years old. DBOS Transact itself is MIT and real, but small: **1.5k stars** (https://github.com/dbos-inc/dbos-transact-py, fetched 2026-07-10), single-vendor, and the study's own R5 flags "company viability is a real open question" (research-R5.md §1).

### 3.3 — C2's cadence design collides with DBOS's documented deploy model (SERIOUS — the strongest verified attack)

C2 represents every cadence enrollment as **"one enrollment workflow per lead with durable sleep to next touch"** (C2 §4 F8, L9). Cadences span days to weeks; at 1,000 leads/mo the system holds **hundreds to low-thousands of sleeping in-flight workflows at any moment**. Now the verified DBOS deploy semantics (https://docs.dbos.dev/python/tutorials/upgrading-workflows, fetched 2026-07-10):

> "All workflows are tagged with the application version on which they started… [recovery] only recovers workflows whose version matches the current application version."

By default the application version is a **hash of the source code** — so *every deploy of gutty-core* strands every sleeping enrollment workflow on an old version. DBOS's own recommended remedy is **blue-green deployment**: "Launch new processes running your new code version, but retain some processes running your old code version" until old workflows drain. For multi-week cadences, "drain" means **running N concurrent versions of gutty-core for weeks**, on one droplet, operated by the same 1–3 people the Pragmatism lens worries about. The alternatives are equally bad: pin a manual version string and accept that any change to step order in *any* workflow silently breaks recovery ("a breaking change to a workflow is any change in what steps run or the order in which steps run" — same page), or fork/patch in-flight workflows by hand. C2 filed this exact issue as "operational detail UNVERIFIED, verify in Stage-0 spike" (§2 caveat 3a). **It is now verified, and it is structural, not a detail.** The spike cannot make it go away; it can only measure how much it hurts.

Contrast the R2-convergent SDR pattern that C5 (and C1) use: cadence state is **data rows** (`enrollments.next_run_at`, state machine columns) swept by a stateless tick. Rows are deploy-invariant. You can redeploy fifty times mid-cadence and nothing strands, drains, or forks. Representing month-long business state as *suspended code* instead of *data* is the single most consequential architectural mistake in C2 — and it is the part of C2 that its precision score of 8.33 was awarded for.

### 3.4 — The single-process totality, and the graft that killed C2's ops claim (SERIOUS)

Under C2, one container — gutty-core — is simultaneously: webhook ingress for four sources, the reactive conversational brain, the only scheduler ("single-clock law"), the saga engine, the cadence executor, and the CRM write path. The droplet is a single DigitalOcean VM with nightly pg_dump as its stated backup posture (C2 L16). Consequences:

- **A droplet outage or a bad deploy stops everything at once**: conversations, first touches, cadences, quote sagas, reconciliation. Meta's webhook retry covers inbound messages for a while; nothing covers the *proactive* plane, which is the plane the −80% target actually depends on. Under C5, Plane S (managed, 99.9%+ substrate) keeps ingesting leads, resolving identity, and firing first touches and lead-class cadence sends while the droplet is down or mid-deploy. C5 protects the flagship value; C2 concentrates it onto its most fragile component.
- **A PHI-bearing Postgres whose durability story is a nightly dump** means up to 24 hours of consent-ledger, crm_write_log, and DBOS-checkpoint loss — i.e., the system could *forget who opted out* and *forget which Zoho writes it already made* (the exactly-once ledger!) in the same incident. C5's lead plane gets managed backups and optional PITR ($100/7-day) as a checkbox; C5's cost model priced it (candidate-C5.md §6).
- **C2's "net service count decreases" claim (L16) did not survive synthesis.** Graft G1 commits Chatwoot — Rails + Redis + Sidekiq, three self-hosted stateful services — onto the same droplet at Stage 3, *because* the judges found C2's DM-card human surface too thin. The Pragmatism 6.00 that C2 was scored on was for the pre-graft, Chatwoot-less C2; the post-graft system the synthesis actually proposes has **more** self-operated stateful surface than C5 (droplet + Rails + Redis + Sidekiq + Phoenix vs droplet + Phoenix + one managed SaaS), while C5's lead-ops console (Supabase Studio, RLS-scoped) costs zero operated services. Nobody re-scored pragmatism after G1. It would not have gone up.

### 3.5 — PHI in pickle blobs: C2's fix is a convention; C5's is a schema (MINOR-to-SERIOUS)

C2 concedes (caveat 3b) that PHI-bearing payloads would land in pickled checkpoint blobs "opaque to retention jobs," and mitigates with a *rule*: payloads carry references, never raw text. The synthesis found the rule insufficient as stated and hardened it into G4 — a CI check over workflow signatures plus a quarterly audit query — **imported from C5**. Even hardened, the residue the synthesis itself flags for red-teaming (§7.4) remains: exception payloads, retry context, and agent message history are exactly the places raw text sneaks into checkpoints, and pickled blobs cannot be redacted by the SQL retention workflows that C2's own L14 relies on — Art. 17 erasure against opaque pickles is a standing audit finding waiting to happen. C5's equivalent guarantee needs no CI vigilance: the plane that holds schedule state **has no text columns**, and the care plane's state lives in relational tables (turn_log) that the redactor and retention jobs already govern. One design cannot leak by construction; the other cannot leak so long as everyone keeps remembering.

### 3.6 — C2's stated rejection of C5 is a strawman (MINOR, but it shaped the judging)

C2 §11: "Serverless cold starts also fight the <1 s deterministic-turn budget." **False as applied**: C5 never puts a conversational turn on serverless — turns run on the identical droplet path as C2's (candidate-C5.md L8, §9: "conversational latency unchanged; turns never leave the droplet path"). Edge Functions handle only lead-source webhooks and template sends, where a cold start costs nothing user-visible. Likewise "adds a vendor to the PHI story": Plane S holds **no PHI by schema** — Zoho IDs, phone hashes, schedule state, under a signed DPA for marketing-class data (https://supabase.com/legal/dpa). The synthesis repeated both framings when declining the Supabase graft ("adds a vendor to the PHI story," §3 non-grafts). If judges scored C5's Precision and Operator-fitness partly through this mischaracterization, those scores are contaminated and worth revisiting on the record as written.

### 3.7 — The extensibility score assumes the framework carries it; the mission only needs the contract (MINOR)

C2's 8.67 Scale·Extensibility rests on packages being "framework-typed objects that fail at import." Real, and elegant (conceded in §5). But note what the mission sentence actually requires (brief §1, §3): a new function ships as a self-contained package with **zero central-dispatch edits**. C5's L16 contract meets that bar with the same mechanisms C2 uses where it matters — embedding-routed intents, explicit-claim registry with collision detection, cadences as versioned *data rows*, write-gate policy rows — no framework required. The delta between "fails at import" and "fails at registrar startup check" is small; the price C2 pays for it (§§3.1–3.3) is not.

---

## 4. Rebuttals pre-empted

- *"C5's two planes are two mental models — Deno + Python."* True and conceded (§5). But compare like with like: C2-post-grafts is Python + a 2-week-old agent framework + a durable-execution library + Rails/Redis/Sidekiq (Chatwoot) + Phoenix. C5's Edge code is thin I/O glue (verify → insert → enqueue), explicitly designed to be trivially portable; the "second mental model" is ~hundreds of lines of TypeScript that a code-generation era makes nearly free to maintain.
- *"C5's cross-plane HTTP boundary is its own bespoke correctness surface."* Also true and conceded. But that surface is idempotent-by-ledger, reconciled nightly, and — critically — **it degrades partially** (one plane survives the other's failure), where C2's uniform substrate degrades **totally**. Bespoke code at a boundary you can see beats framework behavior at an intersection nobody has documented (§3.1).
- *"pgmq/pg_cron give queue-level guarantees; business-level effectively-once is still DIY."* C5 said so itself, in bold, in its own candidate doc (§0 point 2, risk #3) — and C2 is in the identical position: DBOS steps are at-least-once ("steps are tried at least once… a step may be retried" — https://docs.dbos.dev/python/tutorials/workflow-tutorial, fetched 2026-07-10), so C2 needs the same send-intent/write-intent ledgers at the Meta and Zoho seams (C2 §6.3–6.4 admits this). Neither candidate escapes the ledgers. Only one of them also inherits pickle versioning, spike risk, and blue-green drains to get the same place.

---

## 5. Honest concession — where C2 genuinely beats C5

Stated plainly, because an advocate who won't concede isn't credible:

1. **Extensibility as typed artifacts is the best single idea in the study for the mission sentence.** A function package whose parts are an `Agent`, a workflow, and an eval `Dataset` — malformed packages failing at import — is genuinely stronger than C5's convention-plus-registrar contract, and C5's packages that span both planes really do carry two deploy targets and two failure domains. The 8.67-vs-6.67 gap is directionally right even if I dispute its size.
2. **One HITL primitive is better than C5's artisanal approval surfaces.** `requires_approval=True` as the *same* mechanism for the CRM ladder, mode-3 tee-ups, and discount escalation — with the asesora's decision doubling as a free ground-truth label — is cleaner than C5's DM cards + Studio console split. If the deferred-tool-across-restart behavior verifies, this is a real, compounding advantage.
3. **Workflow-derived idempotency keys are more mechanical than C5's hand-built ledgers.** `hash(workflow_id|action|params)` generated by substrate beats keys a developer must remember to thread — *if* the substrate's own versioning problem (§3.3) is designed around.
4. **C5's split-brain risk is real.** My client's own risk #2 names it: cross-plane drift, HTTP boundary failures, two consoles. The single-clock and single-write-gate laws bound it, but a 1–3 person team will feel the seam, and the judges' Pragmatism 6.00 for C5 was fair.
5. **If the Stage-0 spike passes all four rubric items cleanly** — including a demonstrated answer to the versioning/drain problem in §3.3 — then C2-with-grafts is a defensible winner, and C5's remaining case reduces to the outage-isolation and managed-backup arguments, which grafts can partially import.

---

## 6. Grafts C5 offers the winner (whoever it is)

Already adopted by synthesis — provenance for the record: **G4** (structural no-raw-text rule), **G5** (Vertex AI + GCP BAA Gemini-for-PHI route), **G9** (single-clock law).

New offers, in priority order:

1. **Cadence-state-as-data-rows (kills §3.3).** Replace "one durable-sleep workflow per enrollment" with the R2-convergent pattern: `enrollments(next_run_at, state, step_no)` rows swept by ONE short-lived scheduled workflow per tick. DBOS still checkpoints the *tick* and the *send steps*; no workflow ever sleeps longer than a tick; deploys never strand business state; `DBOS.list_workflows` drain management becomes unnecessary. This keeps every C2 advantage (checkpointed sends, queue rate limits) and deletes the blue-green obligation.
2. **Managed durability for the droplet Postgres.** A PHI + consent-ledger + exactly-once-ledger database deserves better than a nightly pg_dump: WAL-G/pgBackRest continuous archiving to DO Spaces, or DO Managed Postgres (~$15–30/mo, PITR included). Cheap insurance against the incident class in §3.4; fits the infra budget.
3. **Plane-separable schema discipline.** Keep intake/identity/cadence/consent tables vanilla SQL with no DBOS/framework types in their columns, exactly as C5 specified them — so the lead plane remains portable to a managed substrate (Supabase or DO Managed PG) later if droplet ops ever overwhelm the team. Costs nothing now; preserves C5 as a live escape hatch instead of a re-architecture.
4. **Dependency-pinning covenant for the framework layer.** Pin exact Pydantic AI + DBOS versions; upgrades land quarterly, behind the eval-harness parity gate and the chaos suite, never mid-stage. Given nine upstream releases in sixteen days (§3.2), "float and pray" is not a policy.
5. **Outage-isolation drill at Stage 2.** Add to the chaos rubric: droplet down for 60 minutes at peak intake — measure leads lost, first touches missed, cadence sends delayed. If the numbers are ugly, the answer is either accept-and-document or adopt graft #3's managed lead plane; either way the decision is made on data, not on which judge's mental model won.
6. **Studio-grade lead-ops visibility.** Whatever console wins (Chatwoot or DMs), give María José read-only SQL dashboards over enrollments/consent/intake health from Stage 1 — C5's zero-cost operational transparency habit, portable to any Postgres.

---

## 7. Closing

The synthesis crowned the candidate with the best *idea* (uniform durability) while its own text concedes the crown is conditional on an experiment nobody has run, on a framework whose stable major was two weeks old, with a deploy model that — now verified — fights the very cadence workload the operator exists to run. C5 is the candidate that took the brief's constraints seriously enough to let them draw the architecture: precision where money moves (deterministic, ledgered, reconciled), managed substrate where the team is smallest, controlled compute where the data is most sensitive, and the study's flagship value — first touch in minutes, every lead, always — running on the one plane that keeps working when everything else is having a bad day. If the panel still prefers C2's compounding extensibility, take it **with C5's grafts #1–#4 as conditions of the verdict**, because without them the winner's precision score is an IOU written against a spike.

— Champion Advocate, C5
