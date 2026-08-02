# Red-Team Attack "eighty" — The −80% & Approval-Throughput Attack

> **Study:** Cerebro Gutty v3 — Master Operator · **Stage:** Tournament red-team · **Date:** 2026-07-10
> **Target:** surviving base **C1 "Evolve-Current v3"** (candidate-C1.md) **with synthesis grafts G1–G10 applied** (synthesis.md §3–5), plus C1-advocate grafts G-a..G-f where relevant.
> **Lane:** the causal chain behind the mission sentence — "cutting the logistics team's workload by ~80%" (BRIEF §1). Task inventory → end-to-end vs assist → ask-first approval queue as the new bottleneck → handoff quality → mode3→mode2 ramp → the honest number.
> **Verdict up front: GRAFT_REQUIRED.** The spine survives this lane. The −80% as accounted does not: C1 §9 excludes selling/payment-verification from the denominator, the flat ask-first autonomy ladder converts CRM-entry labor into approval labor at 1:1 or worse during weeks 7–14, and the mode-3 launch state moves the latency cliff to the highest-intent moment of the funnel. Six named grafts fix it. No graft-proof flaw found — the base does not break.

---

## 1. The logistics task inventory, and what is actually automated end-to-end

C1 §9 is the only quantified inventory in the study (baseline stated-assumption, 9.5 h/day team-total at ~50 leads/day; G8's week-1 time log is the validation — good). Reclassified honestly:

| # | Task | h/day | C1 mechanism | E2E or assist? |
|---|---|---|---|---|
| 1 | First contact + follow-up chasing | 3.0 | F8 cadence, event-triggered first touch <5 min | **E2E** from Stage 1–2 (strongest line in the design; 21× qualify-odds evidence real — R4 §5.3) |
| 2 | FAQ / status / logistics answering | 2.0 | F1 deterministic FAQ + RAG + memory | **E2E-mostly** (validated behavior; residual edge cases honest) |
| 3 | Presupuesto create + send + chase | 1.0 | F2 saga | **ASSIST until mode 2.** Brief F9: *every* product launches mode 3. In mode 3 + ask-first, a human reviews/approves every quote send. Compose time is saved; decision + send + chase-judgment is not. |
| 4 | CRM entry, linking, dedup, stage moves | 1.5 | F6 WriteGate + F7 broker | **E2E only after ladder graduation.** During ask-first, every write still crosses a human — as an approval card instead of a form. Converted, not eliminated (see §2). |
| 5 | Weekly outbound (F4) | 0.5 | scheduled cadences, pre-approved templates | **E2E** (sends need no approval; G3 makes copy team-editable) |
| 6 | MKT inbox triage (IG) | 1.0 | F10 capture → reply → funnel → CRM | **E2E-mostly** |
| 7 | Qualification + tee-up | 0.5 | F9 slots + context package | **E2E for qualification; tee-up hands the sell to a human by design** |
| — | **Selling post-tee-up, payment verification, escalations** | **not in the 9.5** | retained (brief §1: team "narrows to" this) | **HUMAN — and volume GROWS under mode 3** (see §5) |

Finding: of 9.5 h, only ~6.0 h (rows 1, 2, 5, 6, and half of 7) are end-to-end automated at the mode-3 launch state. Rows 3, 4 and the excluded selling block are assist-or-converted until (a) the autonomy ladder graduates and (b) mode 2 graduates per product — both months away (§4, §5).

## 2. The ask-first approval queue is the new bottleneck — quantified, which no study document did

Synthesis stress-test item #5 asks for exactly this simulation; no candidate ran it. Synthesis open decision #10 admits even *who approves* is unassigned. Here is the math the design owes:

**Writes per new lead** (from C1 L7's enumerated actions + F7/F9 flows): create_lead/upsert_contact 1–2 · update_contact_fields 2–4 (7 qualification slots filling across turns) · move_deal_stage 1–2 · create_note 1–2 · create_task ~0.3 (TOUCH_CALL) · create_quote ~0.1 · link_records ~0.5 ≈ **6–11 writes/lead**.

**At 33–65 leads/day** (1,000–2,000/mo, brief §3): **~200–700 ask-first cards/day** if all action types sit in ask-first simultaneously at Stage 3; **60–250/day** even with types staggered 2–3 at a time. At a realistic 30–60 s per decision (read context, sanity-check the payload, tap), that is **1.7–5.8 h/day of new approval labor** for a 1–3 person team — replacing the **1.5 h/day** of CRM data entry the gate was built to eliminate. **During weeks 7–14 the ladder as specified can consume more human time than it saves on that line.** The −80% does not merely stall; on row 4 it can go negative.

**The graduation rule makes the tax standing, not transient.** R3/C1: auto after **N=50 consecutive zero-correction approvals per action type** (8 types → ≥400 clean approvals minimum). "Consecutive" is statistically brittle: an action type that is 98% correct has a per-window pass probability of 0.98⁵⁰ ≈ **36%** — a single mis-extracted field every ~50 writes traps the type in ask-first indefinitely. Nothing in C1/C2/synthesis prices months of ask-first residence.

**Latency coupling breaks conversation and hygiene.** Ask-first on identity-critical writes (create_lead, upsert_contact, link_records) cannot wait for a human: turn N+1 needs the record to persist slots and link the quote. Approval latency (minutes in-hours; overnight off-hours) either stalls the pipeline mid-conversation or forces provisional unlinked writes — recreating exactly the null-`Contact_Name`/dup hygiene failures F6+G7 exist to fix. These action types are structurally incompatible with per-write approval in a real-time channel.

**Off-hours reality.** VE leads message evenings/weekends (R4 §6: <10-min response expectation); asesoras work business hours. An estimated 30–40% of ask-first actions are born off-hours → 8–14 h queue latency. Until Chatwoot lands (G1, Stage 3 +1 wk), approval cards ride the **WAHA team group** (`@Gutty aprueba <id>`, R3 §66) — a group chat on the retiring, bannable transport: diffusion of responsibility, no SLA, no queue depth visibility, cards scrolled away.

## 3. Handoff quality — does the asesora redo work?

The context package (qualification slots + cadence history + last-N turns + negotiation context, C1 L10) is the right shape. Two verified gaps:

1. **Slot-extraction accuracy is never a gated metric.** Gates A–D measure exact-price recall, claims, and *action-agreement* — not whether `who_for`/`prior_attempts`/`duration_trigger` were extracted correctly. A wrong slot makes the asesora re-qualify, and re-asking filled questions is precisely the trust-killer R4 §1.3 warns about. If asesoras learn to distrust the package, they re-read the whole thread every time — the 0.5→0.05 h claim on row 7 evaporates.
2. **No claim/tee-up SLA exists anywhere.** handoff_state has an expiry sweeper but no latency target; there is no booking automation for the free 15-min call (TOUCH_CALL = a Zoho Task for a human to *make* a call). The qualified-and-ready lead who was first-touched in <5 min now waits hours-to-overnight at the close moment. **Mode 3 relocates the latency cliff from "hello" (where the 21× evidence lives) to the highest-intent moment of the funnel (where no evidence says waiting is cheap).** The speed advantage is spent where it matters least and lost where it matters most.

## 4. The mode3→mode2 ramp curve, honestly dated

Quote-stage volume: ~10% of 1,000 leads/mo ≈ **100 quote-stage conversations/mo** (R4 Gate-C math), split roughly plans/exams. Gate B needs ≥50 shadow conversations *per product line* at ≥90% action-agreement + 0 critical; shadow labels start Stage 2 (weeks 4–6):

- **Plans (3 fixed SKUs, pooled):** 50 shadow convs ≈ 3–5 weeks after logging starts → canary weeks ~10–12 → 2-wk canary → **mode 2 ≈ month 4**.
- **Exam presupuestos (itemized, higher risk):** graduates later → **month 5–6+**. C1's own Stage 5 says "months 4–6".

So for the **first ~4 months, 100% of quote sends and closes are human**. Yet C1 §9 books presupuesto at 1.0→0.1 and tee-up at 0.5→0.05 with **no time index** — the steady-state end-state presented as the outcome. Any correction event auto-demotes to mode 3 (Gate D, correct) — meaning the ramp is also non-monotonic; one bad week resets a product line.

## 5. The denominator trick, and the honest number

C1 §9's bottom line: "≈1.3 h + **selling/payment-verification time**" → "−80%". Selling and payment verification are **excluded from the 9.5 baseline and excluded from the residual arithmetic**. But the mission sentence targets the *logistics team's workload*, and the brief itself says the team narrows to "selling, payment verification, edge cases" — that time is in the workload. Worse, **mode 3 grows it**: 100% first-touch + qualification is *designed* to deliver more qualified conversations to human sellers than today (that is what 21× qualify-odds means). AI does not out-close humans (R4 §5.1–5.2, 11x/ZoomInfo); the humans do the closing, on more volume.

Arithmetic with S = today's selling+verification time (unknown; G8 will measure — assume 2 h/day, sensitivity noted):

| Point in time | Automatable 9.5h → | Approval overhead | Selling S → | Total (11.5 baseline) | **Honest −%** |
|---|---|---|---|---|---|
| Month 3 (Stage 3 mid; all mode 3; ladders in ask-first) | ~3.0 (rows 1,2,5,6 automated; 3,4 assist) | +0.5–1.5 h NEW | S×1.2–1.4 ≈ 2.4–2.8 | ~6.2–7.3 | **−37% to −46%** |
| Month 6 (plans mode 2; ladders mostly graduated; grafts landed) | ~1.6–2.2 | +0.2–0.4 | S×1.3 ≈ 2.6 | ~4.4–5.2 | **−55% to −62%** |
| Month 9+ (most quote volume mode 2; verification tooling; booking automation) | ~1.3–1.8 | ~0.1 | S trimmed by tooling ≈ 2.0–2.3 | ~3.4–4.2 | **−63% to −70%** |
| Subset-only accounting (C1 §9's own denominator) | 9.5 → 1.3–1.9 | — | excluded | — | "−80–86%" |

**The honest claim: −80% is achievable only on the automatable subset (and only from ~month 6, not at Stage 3). On total logistics workload the defensible number is ≈ −55–65% at month 6, ≈ −65–70% at month 9**, with S the dominant unknown — which is exactly why G8's time log must capture selling/verification hours, not just the 9.5. If S turns out to be 4 h/day (a selling-heavy team), total-workload −80% is arithmetically out of reach for any architecture that keeps humans closing — and the mission sentence should be re-scoped now, not discovered at month 6.

None of this is a C1-vs-C2 discriminator: C2 §262 books the identical table with the identical exclusion. It is a **base-design + accounting flaw shared by the whole study**, attached here to the surviving base.

## 6. Mandatory grafts (the design changes that move the number up)

| # | Graft | What it fixes | Mechanism |
|---|---|---|---|
| **E1 — Risk-tiered autonomy ladder** (replaces the flat per-action ask-first) | §2's 200–700 cards/day; the identity-write deadlock | Reversible, non-customer-visible writes (create_note, create_task, update_contact_fields, create_lead/upsert_contact *with dedup guard*, link_records) go **shadow → auto-with-audit**: WAL + pre-write snapshots + Recycle Bin 60-d + nightly reconciliation — all already in C1 L7 — are the compensating control instead of per-write approval. Ask-first reserved for **customer-visible or irreversible** actions only: quote/payment-link send, stage=won/lost, record merge. Cuts approvals to **~10–25/day**. Replace "N=50 consecutive" with a windowed gate: ≥98% over trailing 100 writes AND 0 critical (0.98⁵⁰ ≈ 36% pass makes the consecutive rule a trap). |
| **E2 — Approval-throughput engineering** | Off-hours latency; unowned queue | Close synthesis open decision #10 **before Stage 3**: named approver rota. One-tap approve/deny cards with batch-approve in Chatwoot (G1) + mobile push; SLA 15 min business-hours; explicit off-hours policy = Gutty sends a holding message + booking link, never silently stalls. Queue depth + approval latency P50/P95 on the G8 dashboard from day 1 of ask-first. Never run approvals through the WAHA group at Stage 3 — if Chatwoot slips, approvals slip with it (make G1 a hard Stage-3 dependency, not "+1 wk"). |
| **E3 — Booking automation for the free 15-min call** | The relocated latency cliff at the close moment (§3.2) | Zoho Bookings-class self-serve slot link attached to every tee-up and TOUCH_CALL; off-hours tee-ups convert asynchronously instead of waiting for a human claim. Single highest-leverage addition for revenue and for perceived responsiveness; ~days of work. |
| **E4 — Honest denominator + stage-indexed targets** | §5's accounting trick | G8's week-1 time log MUST log selling + payment-verification + escalation hours. −80% is re-based on total logged hours; publish ramp targets per stage gate (M3 ≈ −40–50%, M6 ≈ −55–65%, M9 ≈ −70%+) so the mission fails loudly, not silently. |
| **E5 — Payment-proof media path at Stage 1–2** | Retained verification work is under-tooled | Payment verification is explicitly kept human, but inbound media is dropped (`waha.py:42`) and C1 defers it — so humans chase Zelle/pago-móvil screenshots outside the system. Minimal fix: store inbound image, attach to ticket/handoff context, ack in-channel. (Also enables the graceful voice-note deflect R4 §6 asks for.) |
| **E6 — Slot-accuracy gate** | §3.1 re-qualification risk | Add sampled slot-extraction accuracy (≥95% over the 7 slots) to Gate B, and an asesora one-tap "package was wrong" flag in Chatwoot feeding learning_queue. Protects the row-7 saving and the asesora trust the whole handoff design depends on. |

## 7. Verdict

**GRAFT_REQUIRED.** The C1+grafts base holds structurally in this lane — the cadence/first-touch/FAQ/intake automation is real, evidence-backed, and end-to-end; the FSM/DBOS split is orthogonal to this attack (C2 inherits every finding above unchanged). What does not hold: (1) the flat ask-first ladder, which un-priced converts the mission's biggest saving into approval labor and deadlocks identity writes; (2) the absence of any approval SLA/owner/surface until mid-Stage-3; (3) the mode-3 close-moment latency cliff with no booking path; (4) the −80% accounting, which excludes the work the brief says the team keeps and which mode 3 grows. With grafts E1–E6: **≈ −55–65% of total logistics workload at month 6, ≈ −70% at month 9, −80%+ only on the automatable subset or after broad mode-2 graduation.** Without E1/E2, Stage 3 is a net-negative period for the team and the likeliest place the program loses the asesoras' trust — the documented Agentforce failure mode C1 itself cites.

*Confidence: high on the structural findings (all derived from the candidates' own numbers: 6–11 writes/lead × 33–65 leads/day; N=50-consecutive rule; 100 quote-convs/mo vs 50-conv Gate B; §9's excluded-selling residual). Medium on the specific percentage bands — they inherit the unvalidated 9.5 h/day baseline and the S=2 h assumption, which is exactly why E4 makes G8 measure them.*
