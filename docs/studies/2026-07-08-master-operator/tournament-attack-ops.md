# Tournament Red-Team — Attack Lane: Tiny-Team Ops & Framework Churn

> **Attacker:** ops · **Date:** 2026-07-10 · **Target:** synthesis winner — C2 "gutty-core" (Pydantic AI v2 + DBOS Transact) WITH grafts G1–G10 (`synthesis.md`), honestly compared against the pre-committed C1 fallback (`candidate-C1.md`).
> **Buyer reality:** 1–3 person ops team, ONE developer, who also operates live OpenClaw production, does the cutover, the Meta verification, the template approvals, and the BAA paperwork. No platform engineer, no second reviewer, no on-call rotation.
> **Verdict: `graft_required`.** The base survives this lane, but only with six named fixes. One finding (deploy-versioning × long-sleeping workflows) is fatal-if-unfixed and is now *verified from vendor docs*, upgrading it from the synthesis's "UNVERIFIED spike item (c)" to a confirmed design collision with a known fix.

---

## 1. Findings

### F-1 (SERIOUS→FATAL if unfixed, VERIFIED): DBOS deploy-versioning collides with C2's 30-day-sleeping cadence workflows

The synthesis carried this as UNVERIFIED spike rubric item (c) ("deploy-versioning semantics … are understood and workable"). It is no longer unverified. DBOS's own docs:

- "All workflows are tagged with the application version on which they started."
- "When DBOS tries to recover workflows, it only recovers workflows whose version matches the current application version."
- Recommended strategy: "blue-green code upgrades … launch new processes running your new code version, but retain some processes running your old code version"; "once all workflows of the old version are complete, you can retire the old code version."
  (https://docs.dbos.dev/typescript/tutorials/upgrading-workflows, fetched 2026-07-10; same model documented for Python. DBOS FAQ: when self-hosted workflows "don't make progress, the cause is often version mismatch" — https://docs.dbos.dev/faq.)

Now overlay C2's design (L9): **one enrollment workflow per lead with durable sleep between toques**, cadences spanning 2–4+ weeks; F2 presupuesto sagas sleep 3 days; F5 sequences are multi-day by definition. At 1,000 leads/mo that is **~500–1,000 PENDING workflows sleeping at any moment**. The vendor-recommended deploy procedure for that state is to keep old-version processes running **until the last old workflow completes — i.e., up to a month**. A solo developer deploying weekly through Stages 1–4 (which is exactly what the rollout plan requires — the cadence engine itself is being built while enrollments run) would need to operate ~4 concurrent app versions on one droplet, or manually fork/patch in-flight workflows per deploy, or pin `application_version` to a constant and guarantee workflow-code backward compatibility forever — during the most code-churn-heavy phase of the project. None of this is priced in candidate-C2, the synthesis stages, or the 12–15-week estimate.

**Why this is not base_breaking:** the fix is known and cheap, and it is (ironically) C1's cadence design: authoritative state in **domain tables** (`cadence_enrollments.next_run_at`, state machine), executed by **short-lived workflows launched from a scheduled tick**, never by a workflow that sleeps across deploys. Short workflows (seconds–minutes) drain naturally before any deploy matters. C2 already has the tables (L9 names `cadence_definitions`/enrollments and `(enrollment_id, step_no)` send-intent keys) — the graft is to make the rows authoritative and the workflows disposable. See MANDATORY GRAFT MG-1.

**Spike-rubric upgrade demanded:** rubric item (c) must change from "semantics understood" to a **pass/fail behavior test**: start a workflow with a durable sleep, deploy a changed app version, and demonstrate either clean resumption or a tested drain/fork procedure. If that test can't be made to pass in the spike, the pre-committed C1 fallback (G6) triggers on this item alone.

### F-2 (SERIOUS, VERIFIED): Pydantic AI's breaking-change velocity is real, measured, and accelerating by policy

- V1 released September 2025. **V2.0 stable released 2026-06-23** — a full major, "harness-first" redesign with a new core primitive ("capabilities"), after seven betas (https://pydantic.dev/articles/pydantic-ai-v2). That is a **major architectural re-conceptualization 9.5 months after 1.0**.
- The project's own version policy: majors "won't arrive sooner than 3 months after a stable release" — i.e., the no-breaking-changes window was **reduced from six months to three** at V2 — and old majors get **security fixes for only ~6 months** after the next major ships (https://pydantic.dev/docs/ai/project/version-policy/; https://pydantic.dev/articles/pydantic-ai-v2).
- C2's doc cites "v2.6.0 released 2026-07-08" — six minor releases in the ~15 days after 2.0 stable. Minor releases now carry a no-intentional-breakage commitment (an improvement over the 0.x era), but the measured cadence is: **expect a migration-scale event roughly yearly, with a 3-month contractual floor, on the library that sits on the hot path of every customer turn.**
- The `DBOSAgent` integration is the newest, least-exercised piece of the pairing and must track BOTH libraries' velocities; DBOS itself is at v2.26.x from a small single-vendor OSS company whose viability C2 itself flags.

**Consequence for one developer:** the realistic steady states are (a) freeze at v2.x pinned and accept a shrinking security tail and a growing gap versus the docs/community/LLM-assistant knowledge, or (b) budget a recurring upgrade tax (~1 week/quarter: read changelog, bump, run eval suite, canary) that appears nowhere in the 12–15-week estimate or the −80% story. Both are survivable; neither is currently in the plan. See MG-2.

**Honest C1 comparison:** C1 pins the same DBOS and (in synthesis form) the same grafts; but C1's hot path is plain owned code and Pydantic AI is absent, so its churn exposure is confined to the background/saga layer. C2's mitigations (narrow surface, agents as plain objects, MIT + vendorable, documented `TemporalAgent` exit) are real. This finding demands a policy and a budget, not a base change.

### F-3 (SERIOUS): The 12–15 eng-week estimate is ~2x optimistic against this repo's own measured velocity

The estimate covers: a 17-layer build, 12 functions, an F1/F3 port behind an eval-parity gate, intake bus + identity broker, cadence engine, WriteGate + shadow + ladder, presupuesto saga + local PDF pipeline, sales agent + claims classifier, privacy split + redaction + retention workflows, Alembic baseline, Phoenix migration, chaos tests, Chatwoot deployment + retention wiring — executed by one developer who is simultaneously operating live production.

The empirical anchor is in the repo: **Phase 1** (agent-core skeleton + WAHA + Langfuse — a small fraction of Stage 0–1 scope) consumed multiple weeks of this same developer's time and still shipped with 12 punch-list defects and no production cutover (`docs/brain-status.md`, BRIEF §4). New evidence this lane adds: solo work has no reviewer, and DBOS workflow code has a bug class plain FastAPI does not (nondeterministic workflow bodies, side effects outside steps, unpicklable payload changes) that a second pair of eyes normally catches. Calendar math: 12–15 eng-weeks at a realistic 60–70% focus factor (production support, paperwork, Meta/BAA lead times which are external-party-bound) = **5–8 calendar months to Stage 4**, not "weeks 1–13".

**Why not fatal:** the stages are value-ordered and each is independently shippable; slipping calendars does not invalidate the architecture. But selling the −80% on a 13-week clock sets the buyer up to judge the project failed at month 3 when it is actually on a normal solo-dev pace. Gates must be criteria-bound, not date-bound. See MG-3. (This finding applies ~equally to C1's 10–12-week claim; C2 is worse only by the framework ramp and the port.)

### F-4 (SERIOUS, VERIFIED): Chatwoot's production spec equals the entire planned droplet

Chatwoot self-hosted requirements: minimum "CPU: 2 cores, RAM: 4GB"; **production "CPU: 4+ cores, RAM: 8GB+"**, plus PostgreSQL 12+ and Redis 6+ (https://developers.chatwoot.com/self-hosted/, fetched 2026-07-10). The synthesis plans it on the same 8GB droplet already running Postgres+pgvector, gutty-core, rag-api, crm-adapter, Phoenix, and (pre-retirement) WAHA, with a "+$24–48 second-droplet fallback if RAM forces it." The vendor's own production floor says the fallback is the base case — plan the second droplet from day one and stop pretending it's contingent.

Ops-surface reality for the team: Chatwoot is a Rails+Sidekiq+Redis stack that **nobody on the team can debug**, with a monthly-ish release cadence, its own DB migrations on upgrade, and a second PHI-bearing Postgres that must be wired into retention (the synthesis already requires this). The saving grace — and the reason this is graft-not-breaking — is G1's containment rule: **console + mirror only, never in the send path**. That containment must be *verified as a failure-mode test* (kill Chatwoot; assert conversations, approvals-via-fallback-DM, and sends continue), exactly as tournament item 10 says, and the team needs a written "Chatwoot is down / needs upgrading" runbook that treats it as sacrificial. Note: this cost is candidate-neutral — the C1 fallback inherits G1 too — so it does not move the C1-vs-C2 needle; it moves the honesty of the cost model. See MG-4.

### F-5 (SERIOUS): G9 "single-clock law" makes compliance jobs silently hostage to the framework's health

G9 (correctly) makes DBOS the only scheduler. Combined with L14, that puts **GDPR retention purges (12-mo lead purge, 30-day unconsented-health deletion), nightly write reconciliation, and the G10 drift audit on the same clock that F-1 shows can silently stall on version mismatch** ("workflows don't make progress … version mismatch" — DBOS FAQ). A stalled scheduler after a bad deploy doesn't page anyone; it just quietly stops deleting data it is legally required to delete, and the audit that would notice runs on the same stalled clock. The fix is cheap and standard: an **external dead-man's switch** (healthchecks.io-class ping or a host-level systemd timer) that asserts heartbeats from compliance-critical scheduled workflows and pages on absence. One evening of work; not currently in any layer. See MG-5.

### F-6 (MINOR): 3am debugging — the lane's headline attack mostly *fails* against C2, with two residuals

Attempted attack: "one dev cannot debug durable workflows at 3am." Honest result: at 3am, C2 offers ONE mechanism (query `dbos.workflow_status` + steps tables in the same Postgres, resume/fork by id, Phoenix trace per turn) versus C1's four bespoke guard subsystems whose failure modes live only in the author's head. The pragmatist judge's 3am point favored C1's *plain code*; but plain code with four hand-threaded guard patterns is not obviously easier at 3am than one framework pattern with a queryable state table. Two residuals stand:

1. **Niche ecosystem.** DBOS community is small; self-hosted has **no bundled UI** — the vendor's answer is Conductor, a hosted control plane (https://www.dbos.dev/dbos-conductor; metadata-only per https://docs.dbos.dev/architecture, free-tier terms UNVERIFIED), and the community's answer is a third-party read-only viewer (https://github.com/tmarkovski/dbos-argus). Stack Overflow / LLM-assistant coverage of v2-era APIs is thin-to-wrong. Budget for reading source.
2. **Pickled checkpoint blobs vs dependency upgrades.** A pip bump that changes a class used in a workflow payload can strand in-flight state as unpicklable. G4's no-raw-text rule already pushes payloads toward references; harden it to **primitives-only** (str ids, ints, enums — never model instances) and this bug class disappears. Fold into G4. See MG-6.

### F-7 (MINOR): Bus factor when the developer leaves — a wash between C2 and C1, and the study should say so

What a successor inherits under C2: ~2–3k lines of owned domain code + two documented MIT frameworks with public docs, where HITL/retry/scheduling behavior is *framework-specified*. Under C1: ~3–4k lines of owned code including four correctness-critical guard subsystems whose invariants are documented nowhere but the repo, plus the same DBOS. Hiring reality (LatAm/remote Python market): FastAPI is commodity; Pydantic AI is learnable from good docs; DBOS is obscure either way. Neither candidate is meaningfully more survivable than the other; the *dominant* bus-factor risk is candidate-independent — it is the mission (a bespoke operator brain at a $150–350/mo infra budget) — and the buyer accepted it when the genuinely low-bus-factor candidates (C3/C4/C5) lost on the merits. The real mitigation is a **continuity runbook** (deploy+drain procedure, restore-from-backup drill, kill-switch, vendor-pin manifest, "how to turn it all off and run manually for a week") written for a stranger and *executed once by a non-author* (María José can follow steps; the test is that the doc suffices). Folded into MG-3.

---

## 2. Attacks attempted that did NOT land (for the record)

- **"Bespoke framework = unmaintainable"** — gutty-core is not a bespoke framework; it is ~400 owned lines on two maintained MIT libraries with a documented exit (`TemporalAgent`) and all state in owned Postgres. The bespoke-correctness surface is *smaller* than the C1 fallback's.
- **"DBOS admin/migrations burden"** — DBOS system-table migrations ride the library upgrade; no separate service, no admin server self-hosted; the burden is the versioning discipline (F-1), not the surface area.
- **"Chatwoot breaks the send path"** — G1 already forbids that by construction; the residual is verifying the containment, not redesigning it.
- **"Ops load beats C1 fallback"** — service inventory is near-identical (same droplet, same Postgres, same Phoenix, same Chatwoot graft, gutty-core vs agent-core+DBOS). The honest deltas are churn exposure (C2 worse, F-2) versus bespoke-guard ownership (C1 worse). Neither delta flips the base; both are graftable.

## 3. Mandatory grafts (this lane's price for `base_holds`-equivalent survival)

| # | Graft | Fixes |
|---|---|---|
| MG-1 | **Short-workflow / rebuildable-state law:** no workflow may sleep across a deploy boundary (guideline: max sleep = hours). Long waits live in domain tables (`next_run_at`) consumed by scheduled ticks that launch short-lived workflows. Every deploy runs a tested drain-or-fork script. Spike rubric item (c) becomes a pass/fail behavior test: deploy over a sleeping workflow, prove resumption or drain. | F-1 |
| MG-2 | **Churn budget + pinning policy:** exact-pin Pydantic AI v2.x, DBOS, and transitive deps; vendored mirrors; quarterly ~1-week upgrade window with eval-gated canary; written trigger for the `TemporalAgent` / bare-loop exits. Add the quarterly week to the effort model. | F-2 |
| MG-3 | **Re-baseline + continuity runbook:** publish stages as criteria-gated (not week-numbered); communicate 5–8 calendar months to Stage 4 as the honest solo-dev pace; continuity runbook (deploy/drain, restore drill, kill-switch, pin manifest) executed once by a non-author. | F-3, F-7 |
| MG-4 | **Chatwoot on its own droplet from day one** (+$24–48 in the base cost model, not a fallback); upgrade policy + sacrificial-console runbook; containment failure-test (kill Chatwoot → ops continue) as a Stage-3 acceptance gate. | F-4 |
| MG-5 | **External dead-man's switch** independent of the DBOS clock for compliance-critical schedules (retention purges, reconciliation, drift audit): host-level timer or healthchecks.io-class ping asserting job heartbeats. | F-5 |
| MG-6 | **G4 hardening: primitives-only workflow payloads** (ids, ints, enums; never model/class instances) so dependency upgrades cannot strand unpicklable in-flight state; enforce in the same CI check G4 already mandates. | F-6 |

## 4. Verdict

**`graft_required`.** No finding in this lane breaks the base: every failure mode has a named, cheap, verifiable fix, and the pre-committed C1 fallback (G6) does not escape the two worst ones (it shares DBOS versioning for its sagas and shares the Chatwoot graft) while carrying a larger bespoke-correctness surface. But the base as synthesized is **not deployable by this team without MG-1 through MG-6**: as written, a routine Friday deploy in Stage 2 strands a month of sleeping cadence workflows (vendor-documented behavior, now verified), the compliance clock has no independent watchdog, the console's real cost is understated by one droplet, and the calendar is sold at ~2x the developer's demonstrated velocity on a framework that just re-architected itself 9.5 months after its 1.0 and reserves the right to do so again every 3 months.

**Confidence: high** on F-1/F-2/F-4 (vendor-doc-verified), medium on F-3 (estimate archaeology), high on the verdict.

### Sources (load-bearing)
- https://docs.dbos.dev/typescript/tutorials/upgrading-workflows — version-tagged workflows; recovery only on version match; blue-green + drain guidance (fetched 2026-07-10)
- https://docs.dbos.dev/faq — stalled self-hosted workflows ↔ version mismatch
- https://docs.dbos.dev/production/workflow-recovery — single-server recovery of PENDING workflows
- https://pydantic.dev/articles/pydantic-ai-v2 — V2 stable 2026-06-23; harness-first redesign; 3-month major window (was 6)
- https://pydantic.dev/docs/ai/project/version-policy/ — minor-release stability; ~6-month security tail for old majors
- https://developers.chatwoot.com/self-hosted/ — Chatwoot minimum 4GB / production 8GB+ RAM, Postgres + Redis
- https://www.dbos.dev/dbos-conductor, https://github.com/tmarkovski/dbos-argus — self-host ops tooling reality
- UNVERIFIED: Conductor free-tier terms; DBOS Inc corporate runway.
