# Tournament Red-Team — Lane: COST — Attack on C1 (+ grafts G1–G10) $330–420/mo all-in claim

> **Attacker:** red-team "cost" · **Date:** 2026-07-10 · **Target:** `candidate-C1.md` §7 cost model as adopted verbatim by `synthesis.md` §6 ("Unchanged from the C1/C2 convergent model") and put in front of the user as open decision #6 ("Confirm budget ≈$330–420/mo all-in").
> **Method:** recompute every line at 1,000 leads/mo using (a) the study's own research pack R2, (b) live re-verification of the Meta rate card this session, (c) the brief's literal F4/F8 requirements, (d) adversarial-but-realistic cadence-pressure scenarios the synthesis itself nominated (§7 item 6) but never priced.
> **Verdict: GRAFT_REQUIRED.** The architecture survives this lane — template economics are channel physics that hit all five candidates identically, and C1 already owns the right control-skeleton (budget governors, send governance) to cap spend. The **number does not survive**: it uses the wrong Meta rate row, silently reinterprets F4 "weekly" as ~monthly, omits F8 re-engagement entirely, and its own component bands sum past its published top. Realistic pressured all-in at 1,000 leads/mo is **≈$560–780**, i.e. 1.5–2× the figure the user is being asked to sign.

---

## 1. Finding F-1 (SERIOUS): the model prices Venezuela at Brazil's rate

C1 §7 uses **marketing $0.0625 / utility $0.008** and dismisses the brief's $0.074 as "stale." Three independent lines say the opposite:

- The study's **own researcher** (R2 §1.2, fetched live 2026-07-08): Venezuela / "Rest of Latin America" = **$0.074 marketing / $0.0113 utility**; the table's **Brazil row is $0.0625** — C1's figure is a region-row transposition, not a newer card.
- Live re-verification this session: https://flowcall.co/blog/whatsapp-business-api-pricing-2026 → "Rest of Latin America: Marketing $0.074, Utility $0.0113" (secondary).
- Live search corroboration: Brazil marketing $0.0625, Colombia $0.0125, Mexico $0.0305 — $0.0625 is identifiably Brazil (https://www.messagecentral.com/blog/whatsapp-business-api-pricing-in-brazil; https://mazkara.studio/en/newsletter/whatsapp-penetration-latin-america-2026/).
- Primary CSV (https://business.whatsapp.com/products/platform-pricing#rates) remains JS-rendered and **primary-unverified** — an open item C1 itself acknowledges (§10.4) while nonetheless choosing the *cheaper* disputed figure.

Impact at claimed volumes: 3,000 marketing × $0.074 + 2,000 utility × $0.0113 = **$244.6 vs the claimed $203.5** (+20% on the dominant line). One more risk on this line: search results indicate Meta is moving additional markets **off "Rest Of" regional cards to standalone rates effective 2026-07-01** (UNVERIFIED which markets; rate updates land only on quarter starts per R2 §1.1) — Venezuela's rate is a moving target the model treats as a constant.

## 2. Finding F-2 (FATAL to the claim): F4 "weekly outbound" is silently repriced as ~monthly-or-less

Brief F1–F5 (established scope, "must not regress"): F4 = "**Proactive weekly outbound** (existing customers): Google review nudges, supplement repurchase, referrals."

C1 prices F4 at **1,000 marketing sends/mo** against a 1,500–2,000 patient base (R2 uses 1,500; R2 §1.6 sizes a "2,000-patient blast") — i.e. **~0.5–0.67 touches/patient/month**. That is not a "weekly" program under any reading; it is monthly-minus.

| F4 reading | Sends/mo (1,750-patient midpoint) | Cost @ $0.074 |
|---|---|---|
| As modeled (~0.57 touch/patient/mo) | 1,000 | $74 |
| 1 touch/patient/mo | 1,750 | $130 |
| 2 touches/patient/mo (3 concurrent programs, each sub-monthly) | 3,500 | $259 |
| Literal weekly per opted-in patient | 7,600 | **$562** |

The literal reading is probably not intended (and per-user frequency caps + quality-rating risk argue against it), but **nobody decided this** — the cost model quietly made a product decision the brief's text contradicts. The delta between defensible readings is **$56–488/mo**, larger than the entire infra budget. This is the single biggest blow-past vector.

Secondary effect: at ≥2 touches/patient/mo the weekly batch needs the 10K messaging tier and clean quality rating (R2 §1.6); a Yellow-rating event pauses templates and degrades F2 quote delivery on the same number — the "cap" here arrives as an outage, not a saving.

## 3. Finding F-3 (SERIOUS): F8 "re-engagement" is a stock cost, and it is modeled at $0

Brief F8: first contact within minutes, spaced follow-ups, **and re-engagement**. C1's "avg 2 paid marketing templates/lead" covers only the initial 5-touch sequence on the monthly *flow* of new leads. Re-engagement targets the accumulated *stock* of non-converted leads — retained 12 months under C1's own L13 retention policy — and that stock grows every month:

- Stock at steady state ≈ 12 mo × 1,000 leads × ~85% non-converted ≈ **10,200 leads**.
- Conservative program (one re-engagement touch at day-30 and day-90 per lost lead): ≈1,700 sends/mo → **$126/mo** from month 3.
- Quarterly-sweep interpretation (whole eligible stock / 3): ≈3,400 sends/mo → **$252/mo** at steady state.
- Every send is Marketing category by R2 §1.3's own honesty rule ("re-engagement … are Marketing — do not game the category").

No candidate modeled this line. It compounds silently and, unlike the initial cadence, has **no reply-driven free-window offset** (cold stock rarely replies — that's why it's being re-engaged).

## 4. Finding F-4 (SERIOUS): cadence-pressure scenario named by the synthesis, never priced

Synthesis §7 item 6 told this tournament to price "template volume if reply rates halve." Done:

- R2 base: 45% reply by step 2; 55% non-repliers consume 3.2 billable marketing templates → C1's ~2.0/lead is defensible **at base rates** (≈ 0.45×0.4 + 0.55×3.2 ≈ 1.9–2.1, assuming ~40% of intake is Meta Lead-Ads forms whose touch #1 is itself a paid template — form leads never messaged first, so no window exists).
- Reply rates halved (≈22%): 78% non-repliers × 3.5–4 billables + form-lead first touches → **≈2.9–3.2 billables/lead** → 3,000 × $0.074 ≈ **$222/mo** on the F8 initial-cadence line vs the modeled $125.
- Per-user cross-business frequency caps (error 131049, R2 §1.5) make some step-1 sends bounce and reschedule — retries are re-billed only if delivered, but the cap pushes sends *out* of engineered windows, raising the billable share further (direction: up; magnitude small, UNVERIFIED).

## 5. Finding F-5 (MINOR): the published band fails its own arithmetic

Synthesis §6's component bands: droplet 53–101 + Zoho 14–52 + templates 130–320 + LLM ≈54 + embeddings ≈5. Component-top sum = **$532**; component-low sum = $256. The published "≈$330–420" is a narrative band, not the sum of its own table — the top understates its own stated worst case by ~$110 before any of F-1…F-4 is applied.

## 6. Finding F-6 (MINOR): the CTWA "low end" is an ad-budget transfer, not a saving

Both C1 §7 and synthesis §6 present "shift ad spend to Click-to-WhatsApp" as the lever that pushes templates to the band's low end. The 72h free entry point is real (R2 §1.1) but it is **purchased with ad spend** the model excludes entirely; wa.me organic links from IG open nothing until the user sends first, and CTWA CPCs are the marketing team's budget, not the architecture's. The lever also belongs to a team (marketing) outside this project's control. The architecture may *cite* the lever; it may not *claim* the low band on the strength of it.

## 7. Finding F-7 (MINOR): LLM line is optimistic but not the blow-out

C1's conversational line assumes 2,500 in / 250 out tokens per composed turn, single call. Sales-module turns carry slot state, claims-registry context, retrieval chunks and history; tool-loop turns re-send the prompt 2–3×. Realistic input is 1.5–2× → conversational $24 → $37–50 (Gemini 3.5 Flash $1.50/$9, brief §4b; context caching at $0.15/M mitigates — apply it, it is not in the model either). Judge/extraction lines check out at R9's math. Realistic LLM total: **$60–100 vs $54**. Embeddings ($5) fine. Not a budget-killer; worth restating honestly.

## 8. Finding F-8 (MINOR, UNVERIFIED): the Zoho seat may not be a seat

The model prices "Zoho Gutty user $14–52/mo." L13 requires HIPAA compliance settings + field-level encryption on Examenes/Consultas. Zoho's HIPAA docs (https://help.zoho.com/portal/en/kb/crm/security-control/compliance-setting/hipaa/articles/hipaa-compliance-with-zoho-crm) describe the feature set but this session could **not confirm which editions carry it**. If those features gate on Enterprise and the org runs a lower edition, the upgrade is **org-wide** (every seat, not just Gutty's): ~5 seats × ($40−$23) ≈ +$85/mo, or +$130/mo from Standard. **UNVERIFIED — must be checked against the org's current edition before the seat line is trusted.** Related zero-cost note: Meta Business verification (required for >250 msgs/day tier and green-check) carries **no fee** — correctly omitted; the only transport one-time cost is a phone number (~$0–5/mo if virtual).

## 9. Recomputed model @ 1,000 leads/mo (month 4+, corrected rates, priced pressure)

| Item | Claimed | Corrected base | Pressured (reply rates halve; F4 @2/patient/mo) |
|---|---|---|---|
| Droplet(s) + backups (incl. G1 Chatwoot fallback) | 53–101 | 53–101 | 53–101 |
| Zoho seat (edition risk excluded, see F-8) | 14–52 | 14–52 | 14–52 |
| F8 initial cadence marketing | 125 | 2,100 × 0.074 = **155** | 3,000 × 0.074 = **222** |
| F8 re-engagement stock (NEW LINE) | 0 | 1,700 × 0.074 = **126** | 3,400 × 0.074 = **252** |
| F4 outbound marketing | 63 | 1,750 × 0.074 = **130** | 3,500 × 0.074 = **259** |
| Utility (quotes, confirmations) | 16 | 2,000 × 0.0113 = **23** | 23 |
| LLM (all lines, incl. tool-loop amplification, caching applied) | 54 | 60–80 | 70–100 |
| Embeddings | 5 | 5 | 5 |
| **All-in** | **330–420** | **≈$566–672** | **≈$698–1,014** |

Template subtotal is the blow-past: claimed ≈$204 → corrected ≈$434 → pressured ≈$756. **The marketing-template line crosses the entire published all-in band by itself** once F4 semantics and re-engagement are priced. At the brief's stated volume ceiling (2,000 leads/mo) the flow-driven lines double: all-in **>$1,100** — template spend, not infra, is the binding scaling constraint, and the "10× headroom" language never mentions it.

Note the brief's *formal* budget constraint (§3: infra ≲$150–350 **excluding** tokens/templates) is still met — infra is $70–150 in every scenario. The casualty is the **all-in number the user was asked to confirm** (synthesis open decision #6), which is the number that determines whether this program is economically sane versus hiring hours back.

## 10. What caps it — mandatory grafts (this lane's price of survival)

- **MG-C1 — Correct the rate card and gate on primary verification.** Re-state the model at $0.074/$0.0113 (RoLatAm); make primary CSV download a Stage-0 checklist item; add a small scheduled workflow that re-reads the rate card each quarter-start (Meta re-prices Jan/Apr/Jul/Oct-1; markets are being split off "Rest Of" cards from 2026-07-01) and alerts on change. Sources: R2 §1.1–1.2; https://flowcall.co/blog/whatsapp-business-api-pricing-2026.
- **MG-C2 — Template budget governor, mirroring L7's write budgets.** Hard monthly marketing-template dollar cap (user-set, e.g. $300) enforced in the cadence engine at send time: per-category counters in Postgres, auto-degrade to in-window/utility/human-task touches as the cap approaches, kill-to-ask-first on breach + team ping. C1 already has this exact pattern for CRM writes; it is a copy-paste of philosophy, days not weeks.
- **MG-C3 — Pin F4/F8 frequency policy as versioned data, priced.** Decide F4 semantics explicitly (recommended: event-triggered nudges + ≤1 marketing template/patient/mo floor, weekly *batch job* not weekly *per-patient*) and cap F8 re-engagement (≤2 touches per lost lead, ever, at day-30/day-90). Store caps in `cadence_definitions` next to G3's team-editable copy so policy changes re-price visibly.
- **MG-C4 — Add the re-engagement stock line to the model and re-baseline.** Publish the corrected all-in (≈$570–680 base, ≈$700–1,000 pressured at the caps chosen in MG-C3) and re-run synthesis open decision #6 against the honest number.
- **MG-C5 — Move CTWA to the marketing-budget ledger.** The 72h-window saving may be reported as a joint marketing/engineering KPI; the architecture band must be quoted without it.
- **MG-C6 — Verify Zoho edition gating for HIPAA settings before trusting the seat line** (F-8; conditional, UNVERIFIED).

## 11. Why not base_breaking

Meta's template rates are identical for all five candidates — C2, C3, C4, C5 would each pay the same $0.074 per marketing touch; C4 (Zoho Marketing Automation) and C5 (Twilio BSP +$0.005–0.01/msg) would pay *more*. Nothing in the C1+grafts design causes the overspend; the design merely *mispriced* it, and the design's own governor pattern (write budgets → template budgets) is the natural cap. A cost lane can break a candidate only if its spend is architecture-induced; here it is scope-induced (F4/F8 as written) and the correct response is grafts MG-C1…C6 plus an honest re-baseline, not a different base.

**Confidence: medium.** Rate figures are twice-corroborated secondary (primary CSV still unfetched); F4/F8 volumes are interpretation bands, not measurements; Zoho edition gating and 2026-07 regional card splits are UNVERIFIED.
