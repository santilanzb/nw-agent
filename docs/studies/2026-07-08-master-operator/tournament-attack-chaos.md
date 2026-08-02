# Tournament Red-Team — Attacker "chaos": Exactly-Once Chaos Walk vs C1 + Grafts G1–G10

> **Study:** Cerebro Gutty v3 · **Date:** 2026-07-10 · **Attacker lane:** exactly-once / duplicate-send / lost-turn chaos
> **Target:** `candidate-C1.md` ("Evolve-Current v3") as the surviving base, WITH synthesis grafts G1–G10 applied (`synthesis.md` §3). C1 is the pre-committed fallback (G6) if the C2 Stage-0 spike fails, so its exactly-once story must stand on its own.
> **Method:** step-by-step walks of six concrete failure scenarios against the mechanisms C1 *names in writing* (§5 precision design; L2 inbox; L5 DBOS; L6 cadence; L7 WriteGate; L8 saga). For each: does the written design prevent duplicate sends / duplicate quotes / lost turns? Exact mechanism or exact gap.
> **Ground rules honored:** C1's own honest framing is accepted — literal exactly-once against Meta/Zoho does not exist; the standard is *effectively-once via guards*. The attack tests whether the guards, **as written**, actually close the windows.

---

## 0. The mechanisms on trial (C1's written claims)

| # | Claim (location) | Mechanism |
|---|---|---|
| M1 | §5.1 | `intake_events` inbox, UNIQUE `(source, source_event_id)`; ACK after durable insert; "processing is a DBOS workflow keyed to the inbox row" |
| M2 | §5.2 | `send_intents` outbox row written *before* transport call, keyed `(enrollment_id, step_no)` / `(turn_id, seq)`; "a send step first checks intent status"; Cloud API message-id stored on success; content-hash dedup window for WAHA |
| M3 | §5.3 / L7 | `crm_write_log` WAL, deterministic key `hash(turn_id|action|canonical_params)` "checked before dispatch"; Zoho upsert `duplicate_check_fields` belt-and-suspenders; pre-write snapshots; no deletes at OAuth scope |
| M4 | §5.6 / L14 | `--mode crm` read-after-write evals + **nightly** production reconciliation; mismatch → page + flip to ask-first |
| M5 | L5 | DBOS steps at-least-once, checkpointed; `@DBOS.scheduled` ticks; durable sleep for multi-day sagas (F2 follow-ups, F5) |
| M6 | L6 | replies kill pending touches synchronously in the inbound path; consent/suppression checked synchronously before every send; status-webhook-driven rescheduling |
| M7 | L7 | autonomy ladder: shadow → ask-first ("team approvals") → auto; write budgets; kill-switch |
| M8 | L4 | "DBOS is not on the hot path"; deterministic hot path <1s |

Note the M1↔M8 tension immediately: M1 says turn processing *is* a DBOS workflow; M8 says DBOS is *not* on the hot path; and the synthesis (§1.2) reads C1 as "reactive turns outside durable execution; exactly-once re-derived per seam with hand-placed guards." This ambiguity is itself Finding F2 — under chaos it matters enormously which one is true.

---

## Scenario 1 — Process killed mid-saga, between Zoho Quote create and Cloud API send

**Setup.** F2 presupuesto saga (L8): compose → WriteGate `create_quote` → render PDF → Cloud API document send → log → schedule follow-up. Each stage a DBOS step. `kill -9` at four points.

**Walk.**

- **Kill A — after Zoho 201, before crm-adapter updates the WAL row to success.** WriteGate lives in crm-adapter (a *separate HTTP service*, port 8082). Sequence: DBOS step → HTTP → crm-adapter writes WAL row (pending) → Zoho REST insert → Zoho 201 → crm-adapter WAL success + record id → HTTP 200 → DBOS checkpoint. Kill crm-adapter between Zoho 201 and WAL success. On retry (DBOS re-runs the step, at-least-once per M5/R5), WriteGate finds a WAL row in **pending** state for the same key. The design says the key is "checked before dispatch" — but it never says what a *pending* row means on recovery. Two options, both bad as written:
  - Treat pending as not-done → re-issue Zoho insert → **duplicate Quote record**. Quotes have no unique field usable by `duplicate_check_fields` (upsert dedup works for Contacts/Leads on `Phone_E164`; R3 is explicit: "No idempotency-key mechanism… exactly-once must be built client-side" — https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html). The nightly reconciliation (M4) catches it ~hours later — after the patient may have received a quote referencing the wrong record, and after F6 hygiene metrics are polluted. Nightly is the wrong timescale for a recovery decision that happens seconds after restart.
  - Treat pending as done → if the kill actually landed *before* the Zoho call, the quote silently never exists; the saga proceeds to render a PDF from local data and sends a document for a Quote record that isn't in Zoho. Reconciliation flags it that night.
  - **Gap G-1a:** the WAL has no in-doubt resolution protocol. The fix is known and cheap: stamp the idempotency key into a **custom field on every created Zoho record** (Quote/Deal/Task), and define pending-row recovery = parametrized COQL lookup by that marker field → adopt the found record id, else safely re-create. Without the marker, the ledger C1 itself calls "load-bearing" (crack #3) cannot answer "did my write land?" for any module that isn't upsert-dedupable.

- **Kill B — after WAL success, before the DBOS checkpoint commits.** DBOS re-runs the step; WriteGate finds a **success** WAL row for the same key and returns the stored Zoho id. **HOLDS** — provided the WriteGate returns the recorded result rather than erroring on key conflict. The doc's "checked before dispatch" is consistent with this; credit given, but the return-stored-result semantics should be written down.

- **Kill C — after Quote exists, mid-send: send_intent row written (pending), Cloud API POST fired, killed before message-id stored.** Recovery re-runs the send step, which "first checks intent status" (M2) — and finds **pending**, the exactly ambiguous state. The Cloud API `POST /messages` has no documented client idempotency key (UNVERIFIED as an explicit "no" in Meta reference — consistently absent; R5 flags the same for WAHA), and without the message-id you cannot query whether the send landed. As written the design must blindly choose: resend (duplicate document message to the patient; for a cadence marketing template, a duplicate *billed* send and spam signal) or drop (patient never receives the quote they were promised). The content-hash dedup window is specified **for WAHA only** — the Cloud API path, which carries all business-initiated sends from Stage 1, has no stated guard.
  - **Gap G-1b:** send_intents needs three states (pending → dispatched → confirmed-by-status-webhook) plus a per-message-class in-doubt policy: conversational replies and utility documents are resend-safe (worst case a duplicate message, accept it); marketing templates are never blind-resent — wait for the status webhook correlation window, then degrade to a human task. None of this is in the text.

- **Kill D — after send, before "schedule follow-up".** DBOS resumes; follow-up scheduling is internal (DB write) and idempotent under workflow replay. **HOLDS.**

**Scenario verdict:** the happy-path guards are right, but both external seams have an unhandled in-doubt window, and the only named backstop (nightly reconciliation) is 1,000× too slow for recovery-time decisions. Duplicate quote records and duplicate/lost patient sends are reachable with a single well-timed kill. → Findings F1, F3.

---

## Scenario 2 — Duplicate webhook delivery

**Walk per source.**

- **Meta Cloud API:** redelivers on non-2xx with stable WhatsApp message ids → UNIQUE `(source, source_event_id)` rejects the second insert. **HOLDS** (M1 is the exact mechanism).
- **WAHA (legacy bridge):** stable message ids → same. **HOLDS.**
- **ManyChat External Request:** C1's own L2 notes ManyChat "likely never retries" and has no subscriber-enumeration API. But duplication here comes from *flow re-entry* (user re-triggers the IG automation), and the External Request payload has no documented delivery id — the normalizer must synthesize `source_event_id`. Synthesize from `subscriber_id + text + coarse timestamp` and legitimate rapid re-sends collide; synthesize from receipt time and true duplicates pass. **Underspecified** — minor, but it's the one ingress where the UNIQUE constraint is only as good as an unwritten synthesis rule.
- **Zoho workflow-rule webhook `{module, record_id, event}`:** Zoho retries failed webhook deliveries, and the payload carries no delivery id. A redelivery is indistinguishable from a legitimate second edit of the same record. Downstream blast radius: a duplicate `lead_created` intake event → **duplicate cadence enrollment** → the lead receives two interleaved touch streams (each individually well-guarded by `(enrollment_id, step_no)` keys — the keys dedup *within* an enrollment, not *across* enrollments). C1 never states a uniqueness constraint on enrollments. **Gap G-2a:** `cadence_enrollments` needs UNIQUE `(identity_id, cadence_definition_id)` WHERE state='active', enforced at enrollment, making duplicate intake events harmless here.
- **The orphaned-inbox-row hole (worse than any duplicate):** M1 ACKs *after* insert and processes async. Kill the process between the durable insert (ACK'd — the source will never redeliver) and the start of the processing workflow. If turn processing genuinely is a DBOS workflow whose **workflow id = inbox row id**, a restart-time sweep can idempotently start it (starting an existing workflow id is a no-op). But C1 never commits to that id scheme (the synthesis stack does, at L2 — for C2), and L4/M8 says DBOS is *off* the hot path, in which case nothing ever re-drives the row: **the patient's message is durably stored and never answered — a lost turn with a false sense of security.** No sweeper over unprocessed `intake_events` appears anywhere in C1. The advocate's G-f ("selective turn durability") makes this *worse* for the case that matters: pure-conversational turns — the bulk of F1 — stay on the non-durable path by design, so "¿cuánto cuesta la consulta?" killed mid-turn is silently dropped. → Finding F2.

**Scenario verdict:** dedup-at-ingress holds for the two high-volume sources; the Zoho/ManyChat synthesized-id rules and the enrollment uniqueness are unwritten; and redelivery's mirror twin — the ACK'd-but-never-processed row — is an unhandled lost-turn path that contradicts the candidate's own framing.

---

## Scenario 3 — Zoho 429 / 5xx mid write-plan

**Setup.** A multi-write plan (F7 intake: upsert Contact → create Deal → link → create Task) hits Zoho trouble at step 2.

**Walk.**

- **429 / concurrency:** R3's math says credits are a non-issue (1–10% of the Standard floor) but names the real limit: **concurrency (10–20 simultaneous calls) is the only limit an agent retry-storm could hit.** C1's write budgets (~30/hr, ~200/day) are *behavioral* budgets on the agent, not a client-side concurrency limiter. Graft **G7 makes this concrete**: the Merge-Records dedup backfill and hygiene sweeps run bulk write traffic *concurrently with* live turn/saga writes through the same adapter. Nothing in C1 or the grafts serializes them. A backfill burst + DBOS retries on the resulting 429s is a self-inflicted retry storm; DBOS queues support rate limiting but C1 never states a global Zoho concurrency budget as config. **Gap G-3a** (moderate; two-line fix: one DBOS queue for all Zoho writes with concurrency ≤5).
- **5xx ambiguous-outcome:** Zoho returns 502/504 but may have applied the write. Retry:
  - Contacts/Leads: upsert with `duplicate_check_fields` on unique `Phone_E164` → retry converges to update. **HOLDS** — this is the exact mechanism, and it's the *only* module class where it exists.
  - **Deals, Quotes, Tasks, Notes:** no unique field, no upsert dedup, no native idempotency (R3). Retry after ambiguous 5xx → **duplicate Deal/Quote/Task**. Same root cause and same fix as Scenario 1 Kill A (marker field + lookup-before-retry). The WAL alone cannot disambiguate: it knows the call was *sent*, not whether it *landed*.
- **Mid-plan partial failure + no rollback:** deletes are impossible at OAuth scope (a good decision C1 made on purpose), so compensating "undo" cannot undo a *create* — sagas are forward-only. A plan that dies at step 2 leaves an orphan Contact-without-Deal until the retry lands or nightly reconciliation flags it. Acceptable — but C1 sells "pre-write snapshots make undo a compensating update" without stating the create-undo asymmetry. Honesty gap, not a defect: the design should say "forward recovery only; orphans are flagged, not rolled back."

**Scenario verdict:** holds for upsertable modules, open for exactly the modules the operator functions (F2, F6) write most. → Finding F1 (shared root cause), F6.

---

## Scenario 4 — Two replicas racing on one lead

**Setup.** C1 is single-process by design, but (a) its own scale-out path is "additional DBOS workers on the same Postgres" (crack #9), and (b) even at launch, a compose re-deploy or crash-looping supervisor gives brief two-instance overlap windows.

**Walk.**

- **Two schedulers ticking:** `@DBOS.scheduled` workflows have deterministic per-interval workflow ids — double-start across workers is a no-op (DBOS docs, https://docs.dbos.dev/python/tutorials/scheduled-workflows). **HOLDS**, and G9 (single-clock law) prevents any *third* scheduler existing. Credit.
- **Cadence touch vs. inbound reply (the domain race that exists even single-process, because tick workflows and turn handling are concurrent tasks):** tick reads enrollment (active, due) → writes send_intent → calls Meta. Concurrently the lead replies; the turn path "synchronously kills pending touches" (M6). Interleave: kill lands *after* the tick's read but *before* its intent write — the kill sees nothing pending to kill; the tick then writes the intent and dispatches. **The lead gets a follow-up template after they already replied** — precisely the spam-signal behavior R2 warns drives quality-rating drops. As written, nothing makes read-decide-write atomic. **Gap G-4a:** the send step must claim the touch with a CAS in one transaction — `UPDATE cadence_enrollments SET current_step = N+1 WHERE id = $1 AND state='active' AND current_step = N` + intent insert in the same tx; reply-kill does the inverse CAS; a send step that lost the CAS aborts before transport. Cheap, mandatory, absent.
- **Same lead, two concurrent turn events (double-text, or WAHA + Meta both delivering during the bridge period):** two turn workflows classify and reply concurrently → interleaved replies (embarrassing, not fatal) — but both may also *start the same saga* (both turns classify as `presupuesto_request` seconds apart) → two Quote sagas, each internally idempotent, jointly duplicated: the WAL key is `hash(turn_id|…)` and the turn_ids differ, so the ledger sees two distinct legitimate writes. **Duplicate quote by construction, no kill required.** **Gap G-4b:** per-identity serialization (Postgres advisory lock on identity_id for the side-effect tail of a turn, or a business-level guard: one open Quote per Deal per N hours enforced in the WriteGate).
- **Identity merges:** `pg_advisory_xact_lock` around multi-key merges + ON CONFLICT canonical keys + Zoho upsert. **HOLDS** — this seam was designed properly.

**Scenario verdict:** infrastructure races are handled by DBOS + G9; the two *domain* races (reply-vs-touch, double-intent saga start) are real, reachable without any crash, and unaddressed in the text. → Findings F5, F6.

---

## Scenario 5 — Clock skew / time chaos on cadence steps

**Walk.**

- **Cross-node skew:** one droplet, one clock at launch — moot until scale-out; on scale-out, next_run_at comparisons happen against Postgres `now()` if written that way (unstated but easy). Minor.
- **NTP step-back / tick replay:** a due enrollment processed twice by adjacent ticks is stopped by the `(enrollment_id, step_no)` intent key and the (missing, see G-4a) step CAS. With G-4a in place, **HOLDS**.
- **The real time bomb — deploy versioning of sleeping workflows:** L5 commits multi-day flows (F2 quote follow-ups, all of F5) to **DBOS durable sleep**. DBOS pins workflow recovery to the application version that started the workflow (synthesis §7.1 flags this as UNVERIFIED-and-load-bearing for C2 — the *identical* exposure exists in C1's L5 and nobody transferred the flag). Consequence: every routine deploy during a 3-day quote-follow-up sleep risks stranding those workflows — cadence-adjacent sagas that silently never wake. Silent, unpaged (reconciliation checks Zoho writes, not workflow liveness), and it will happen weekly because deploys are weekly. **Gap G-5a:** rule — no durable sleep longer than the deploy cadence. Multi-day waits belong in `cadence_enrollments.next_run_at` rows swept by the scheduler (C1 already has the table!); durable sleep reserved for intra-day steps; plus a written deploy drill for DBOS version handling (fork/resume or `DBOS_APPLICATION_VERSION` pinning), validated in the Stage-2 chaos acceptance. Note the irony: C1's cadence engine (rows + ticks) has the right shape; it's the F2/F5 *sagas* that reach for the sleep primitive and inherit the versioning trap.
- **Service-window edge:** a send decided in-window but dispatched after the 24h window lapsed (queue delay, retry backoff) fails hard at Meta. R2 mandates suppression checks at send time, not enqueue time; the same must hold for window checks. C1 states the suppression half, not the window half. Minor; the status-webhook reschedule loop (M6) mops up the failure but burns a failed send + delay.
- **US branch / DST:** business-hours windows for +1 leads cross DST; VE does not observe DST. A one-hour drift on send windows is cosmetic. Minor.

**Scenario verdict:** cadence table design is skew-robust once the CAS lands; the durable-sleep versioning exposure is the serious item and is currently flagged only against C2 despite binding C1 equally. → Finding F4.

---

## Scenario 6 — Approval granted after context changed

**Setup.** Ask-first rung of the ladder (M7): agent proposes `create_quote` (params frozen: product ids, computed amount) → asesora approves — pre-G1 via team DM, post-G1 via a Chatwoot card. Between ask and approve: (a) calidad@ edits a product price in Zoho; G2's nightly pull regenerates `facts/prices.yaml`; or (b) a human claims the conversation (handoff); or (c) the lead replies "ya no me interesa" and the cadence marks them exhausted.

**Walk.**

- **Price change (a):** the proposal froze `canonical_params` at compose time; the approval executes the frozen payload. The asesora approved what the card showed — but the business price changed underneath. Gutty sends a quote at the superseded price, *with human approval as cover*. Alternatively, if implementation re-derives the payload at execute time, then what executes ≠ what was approved — worse. **Nothing in C1 or the grafts binds the approval to a payload hash, stamps the facts version (prices.yaml revision) into the proposal, sets an approval TTL, or revalidates the amount against current facts at execute.** The dollar-amount output guard (L11) checks LLM-composed *text* against the fact table — it does not gate WriteGate *payload execution*. G2 actually **sharpens** this attack: it guarantees prices change nightly without engineering involvement, widening the ask→approve staleness window into a routinely-armed trap. This is the classic TOCTOU on the one path the brief says must never be wrong (fixed prices, deterministic amounts). **Gap G-6a.**
- **Handoff claimed between ask and approve (b):** the mute check lives in the *turn* path (L4). The approval-execute path is not a turn; nothing re-checks `handoff_state` before the send fires. Gutty sends a quote into a conversation a human asesora is actively working. **Gap G-6b:** approval-execute must run the same pre-send gates as any send: mute check, suppression, consent, window.
- **Double-approve (two asesoras tap the same card; or Chatwoot webhook redelivers):** execute funnels through the WAL with the same idempotency key (same turn_id, action, params) → second execute is a recorded no-op. **HOLDS** — provided the Chatwoot→gutty-core approval callback is itself inboxed like any webhook (G1 says console "never in the send path", which implies a callback route that must join the M1 inbox; unstated but consistent).
- **Approve-after-expiry (c):** no TTL exists, so a 5-day-old approval fires into an exhausted/opted-out conversation. Suppression "checked synchronously before every send" (M6) catches the opted-out case **if** the approval-execute path routes through the cadence send gate — for WriteGate-triggered sends this is, again, unstated.

**Scenario verdict:** the idempotency half of approvals holds; the *validity* half — is this approval still about the current world? — has no mechanism at all. On a money path, with G2 guaranteeing nightly context drift. → Finding F4 (approval TOCTOU), the single most brief-violating finding in this lane.

---

## Cross-cutting: the idempotency-key scheme is incomplete

`hash(turn_id|action|canonical_params)` (M3) presumes a turn. F4 weekly outbound writes, G7 hygiene sweeps, retention jobs, reconciliation auto-fixes, and cadence-driven Zoho Tasks (TOUCH_CALL) have **no turn_id**. The key scheme for the entire scheduled/proactive half of the operator is undefined — exactly the half that runs unattended at 3am. The C1 advocate already conceded this (advocate G-d: workflow-derived keys `hash(workflow_id|…)` for everything under DBOS); it must be promoted from advocate-suggestion to mandatory. → folded into Finding F6.

---

## Findings (ranked)

| # | Finding | Sev | Scenario | Fix |
|---|---|---|---|---|
| F1 | **In-doubt window at the Zoho seam for non-upsertable modules** (Quotes/Deals/Tasks/Notes): WAL pending-state has no recovery protocol; crash-after-201 or ambiguous 5xx → duplicate Quote/Deal or silently missing record; nightly reconciliation is 1,000× too slow to arbitrate | serious | 1A, 3 | MG1: marker field + lookup-before-retry |
| F2 | **Reactive-turn durability is self-contradictory** (§5.1 "workflow keyed to inbox row" vs L4 "DBOS not on the hot path"); ACK'd-but-never-processed inbox rows have no sweeper → lost turns on the most common chaos event (restart mid-turn) | serious | 2 | MG2: workflow-id = inbox id + sweeper |
| F3 | **Send in-doubt at the Cloud API seam**: intent 'pending' is ambiguous on recovery; no idempotency key on POST /messages; content-hash guard specified for WAHA only → blind resend (duplicate billed template / duplicate patient message) or blind drop (lost quote delivery) | serious | 1C | MG3: three-state intents + per-class policy |
| F4 | **Approval TOCTOU + sleeping-saga versioning**: no payload-hash binding, facts-version stamp, TTL, or execute-time revalidation on ask-first approvals (G2's nightly price pull arms this daily); approval-execute skips the mute/suppression gates; separately, L5 durable sleeps inherit the DBOS deploy-versioning strand risk flagged only against C2 | serious | 5, 6 | MG4 + MG5 |
| F5 | **Reply-vs-touch race**: read-decide-write on enrollments is not atomic; a lead who replies during the tick window still receives the follow-up template — the exact quality-rating poison R2 warns about | serious | 4 | MG6: CAS claim |
| F6 | **Duplicate-saga and keyless-scheduled-write gaps**: two near-simultaneous presupuesto intents → two legitimate-per-ledger Quotes (turn-scoped keys can't see each other); scheduled/proactive writes have no turn_id and thus no key scheme at all | serious | 4, cross | MG6 (advisory lock) + advocate G-d promoted into MG1 |
| F7 | Zoho concurrency (10–20) unprotected: G7 backfill + live writes + DBOS retries share one adapter with no global concurrency budget → self-inflicted 429 storm | minor | 3 | single DBOS queue for all Zoho writes, concurrency ≤5 |
| F8 | Synthesized `source_event_id` rules for Zoho-webhook and ManyChat ingress are unwritten; `cadence_enrollments` has no active-uniqueness constraint → duplicate enrollment = double touch stream | minor | 2 | UNIQUE (identity, cadence_def) WHERE active; write the synthesis rules |
| F9 | Forward-only recovery is undisclosed: undo-by-compensating-update cannot undo creates (deletes barred by design) — orphans are flagged, not rolled back; the doc should say so | minor | 3 | one honest paragraph + reconciliation orphan report |

## Mandatory grafts (all implementable inside C1; none require re-platforming)

- **MG1 — Zoho write-marker protocol:** stamp the idempotency key into a custom field on every record the WriteGate creates (Quotes, Deals, Tasks; Notes via title convention); WAL `pending` recovery and every ambiguous-5xx retry = parametrized COQL lookup by marker before any re-create; adopt-or-create. Extend key derivation to `hash(workflow_id|action|canonical_params)` for non-turn work (promotes advocate G-d).
- **MG2 — Turn durability rule:** every intake event's processing is a DBOS workflow with **workflow id = intake_events id** (double-start = no-op); add a scheduled sweeper over unprocessed inbox rows (SKIP LOCKED, idempotent by the id rule). Accept the few-ms checkpoint cost; delete the "DBOS not on the hot path" sentence or scope it to FAQ-only turns that produce no side effects and are covered by the sweeper.
- **MG3 — Three-state send_intents** (pending → dispatched → confirmed via status webhook) with a written per-message-class in-doubt policy: replies/utility resend-safe; marketing templates never blind-resent — await status-webhook correlation, then degrade to human task. Applies to the Cloud API path, not just WAHA.
- **MG4 — Approval binding:** ask-first proposals carry `{payload_hash, facts_version (prices.yaml revision), TTL ≤24–72h}`; at execute, recompute the payload from current facts and re-run the pre-send gates (handoff mute, suppression, consent, window); any mismatch or expiry voids the approval and re-asks with a diff. Chatwoot approval callbacks enter through the M1 inbox like any webhook.
- **MG5 — No durable sleep beyond deploy cadence:** multi-day waits (F2 follow-ups, F5 sequences) live in `next_run_at` rows swept by `@DBOS.scheduled`; durable sleep only intra-day; document and chaos-test the DBOS deploy-versioning drill at Stage 2 (the synthesis §7.1 UNVERIFIED flag binds C1 too).
- **MG6 — Atomic touch claim + per-identity serialization:** send step claims the enrollment step via CAS in the same transaction as the intent insert; reply-kill/human-claim do the inverse CAS; the side-effect tail of a turn takes a Postgres advisory lock on identity_id (and the WriteGate enforces one open Quote per Deal per 24h as the business-level backstop).

## Verdict

**graft_required.** The base architecture is sound in shape — inbox, outbox, WAL, ladder, and reconciliation are the correct five organs, and several walks (1B, 1D, 2-Meta/WAHA, 4-scheduler, 5-tick-replay, 6-double-approve) hold on the exact mechanisms named. But **as written**, six of the walked scenarios reach a forbidden outcome (duplicate quote, duplicate send, lost turn, wrong-price approved send) through gaps that are specification omissions, not structural flaws: every mandatory graft above is a table constraint, a state column, a CAS, a marker field, or a written policy — days of work, all inside C1's own process and Postgres. Nothing found requires abandoning the base (no base_breaking): the in-doubt windows at the Meta/Zoho seams are irreducible under *any* architecture (C2 included — its workflow-derived keys inherit F1/F3 identically at the external seams), and C1+MG1–MG6 closes them as tightly as the APIs permit. C1's own Risk #2 predicted this lane ("a subtle guard bug = double quote or double send"); the finding of this attack is that the guard bugs are not hypothetical — six are already visible in the spec — and all six are nameable and fixable before a line of code is written. The Stage-2 chaos acceptance test ("kill mid-saga → zero duplicates") must be extended to cover: kill-between-201-and-WAL, ambiguous-5xx retry on Quotes, ACK'd-unprocessed inbox row, reply-during-tick, price-change-between-ask-and-approve, and deploy-during-durable-sleep.
