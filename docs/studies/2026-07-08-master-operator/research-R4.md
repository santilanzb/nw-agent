# R4 — Conversational Sales Agent Design (Gutty as seller, F8/F9)

> Researcher: R4 · Date: 2026-07-08 · Study: Cerebro Gutty v3 "Master Operator"
> Scope: qualification frameworks under LLM implementation; objection handling with FIXED prices; mode3→mode2 graduation gates (eval design, transcript sampling); guardrails for health-adjacent claims; REAL AI-SDR outcome data; LatAm WhatsApp selling norms.

## 0. Business context anchors (from repo)

- Fixed price points: Plan 1 $229 / Plan 3 $559 / Plan 5 $789; installments TDC-only +3% commission; exams NOT included in plan price ([customer_service.py:41-56](../../../src/company_agent/agent_core/tasks/customer_service.py)). The free 15-min informative call is the existing low-friction conversion offer.
- Existing policy already bans price invention, amount calculation, and medical advice, and routes `handoff_discount` to a human ([SKILL.md hard rules 1-2-5](../../../openclaw/skills/customer-service-policy/SKILL.md), `HANDOFF_INTENTS` in customer_service.py). The sales agent is an *extension* of this spine, not a new persona.
- Inbound media (voice notes) is currently dropped (`waha.py:42` per brief §4) — relevant because LatAm buyers send voice notes; a text-only seller must gracefully ask for text or hand off.

## 1. Qualification frameworks that survive LLM implementation

**Finding 1.1 — Frameworks survive as *typed slot schemas*, not as prompt prose.** The 2025-26 pattern across tools that actually ship (Sybill, Oliv, Avoma) is: the LLM *extracts* framework fields from conversation and *populates CRM fields*; deterministic code decides what is still missing and what to ask next. Prompt-only "act like a BANT qualifier" degrades — the model forgets slots, re-asks, or hallucinates completeness. Sources: https://www.sybill.ai/blogs/bant-vs-meddic , https://www.oliv.ai/blog/meddic-sales-methodology , https://www.avoma.com/blog/bant-sales-framework , https://routine.co/blog/posts/bant-meddic-spiced-comparison .

**Finding 1.2 — Framework fit for NutriWhite.** BANT is designed for high-velocity, small-deal, 1-2 decision-maker sales (https://nimitai.com/blog/sales-qualification-framework) — closest to a $229-789 B2C health-service purchase. SPICED (Winning by Design) adds Pain/Impact/Critical-Event, which maps naturally to health motivation ("what symptom, how long, what changed this week"). MEDDIC is enterprise-only; discard. **Recommended: a SPICED-lite / BANT hybrid slot schema of ~7 slots**, stored as Zoho Lead/Contact fields (F6 gives write authority):

| Slot | Example | Notes |
|---|---|---|
| `who_for` | self / child / spouse | decision-maker proxy (Authority) |
| `concern_domain` | digestive / autoimmune / energy / pediatric | ⚠ PHI boundary — see 1.4 |
| `duration_trigger` | "3 years, worse this month" | Critical Event |
| `prior_attempts` | doctors seen, diets tried | Pain depth |
| `location` | VE / LatAm / US / EU | drives supplement logistics + privacy class |
| `budget_signal` | asked prices? balked? asked installments? | Budget (never asked directly — inferred) |
| `next_step_readiness` | wants free call / wants plan now / browsing | Timeline |

Code (not the LLM) computes `qualification_complete` and picks the next question from a priority list; the LLM only phrases the question in Gutty's register and extracts answers into slots (schema-constrained JSON output). This matches the repo's existing deterministic-spine philosophy (classifier → dispatch → task module) and the brief's Precision lens.

**Finding 1.3 — Don't interrogate.** LatAm WhatsApp selling is relational; a checklist-sounding bot kills trust ("trust is personal—consumers trust the person selling to them rather than the system", https://sherlockcomms.com/whatsapp-commerce-in-latin-america/). Design rule: max ONE qualification question per turn, always attached to a value-giving statement; slots may fill in any order across turns; never re-ask a filled slot (this is exactly what slot state prevents).

**Finding 1.4 — The PHI trap in qualification (cross-ref R8).** `concern_domain` and `prior_attempts` are health data. The moment a lead describes symptoms, GDPR Art. 9 / HIPAA-adjacent handling attaches (brief §3 flags the boundary question). Design consequence: qualification slots must be split into a marketing tier (who_for, location, budget_signal, next_step_readiness) and a health tier (concern_domain, duration, prior_attempts) with the health tier stored/processed on the PHI path (sync Anthropic API under BAA, hashed/limited logging — `anthropic.py:69-72` currently leaks raw text to Langfuse, punch-list item). Do NOT hand-wave this; it constrains which model/provider composes sales turns.

## 2. Objection handling under FIXED prices

**Finding 2.1 — Discount requests will be frequent and culturally normal.** In LatAm WhatsApp commerce "price negotiation is normal and purchase decisions depend on the relationship with the seller" (https://sherlockcomms.com/whatsapp-commerce-in-latin-america/). A policy of instant-handoff on any price pushback would flood the tiny team. Current repo policy hands off `handoff_discount` immediately.

**Finding 2.2 — The non-discount playbook is well established** (https://blog.hubspot.com/sales/price-objection-responses , https://www.thesalesblog.com/blog/how-to-handle-pricing-objections-without-discounting , https://close.com/blog/what-is-usually-hidden-behind-the-price-objection-in-sales):
1. **Diagnose**: budget objection vs cash-flow objection vs value doubt vs stalling.
2. **Value reframe**: outcome, not sticker (Protocolo 3R accompaniment, embajadoras, Academia access are real differentiators already in FAQ copy).
3. **Price decomposition**: "$559 en 3 meses ≈ $6/día" — SAFE because it is presentation, not calculation of a *new amount*; must be precomputed constants, never LLM arithmetic (SKILL.md rule 2 stays).
4. **Payment-terms flexibility as the only lever**: TDC installments +3% already exist and are the sanctioned "concession."
5. **De-risk step-down**: the free 15-min call is the natural counter-offer to "lo voy a pensar" / price hesitation.
6. **Escalate packaged**: after ONE reframe turn, an explicit discount demand escalates with a negotiation context package (lead slots, objection type, quote id) — matches brief F9 "discount requests escalate with packaged negotiation context."

**Recommended objection taxonomy → intent seeds** (each becomes `intent_seeds.yaml` entries + a scripted/composed response): `objection_price`, `objection_skepticism` ("¿esto de verdad funciona?" — highest health-claims risk, see §4), `objection_timing` ("ahora no puedo"), `objection_decision_maker` ("tengo que hablar con mi esposo"), `objection_payment_friction` (VE currency/Zelle/pago móvil), `objection_exam_cost` (exams not included — known sticker-shock point), `stall_generic` ("lo voy a pensar"). Responses: deterministic skeleton + LLM phrasing, price facts always from constants/Quote records.

**Finding 2.3 — Design rule: one reframe, then escalate or park.** Multi-turn objection wrestling by an LLM is where invented concessions happen. Bound the loop in code: objection intent → 1 composed reframe (from an approved move list) → if objection repeats, either offer free call (timing/skepticism) or handoff with context (price/discount). Deterministic, auditable, cheap.

## 3. Graduation gates: mode 3 → mode 2 (eval design)

**Finding 3.1 — Mode 3 IS shadow mode for mode 2.** This is the central design insight. In mode 3, Gutty qualifies and tees up a human who then decides whether to send the presupuesto/payment link. That human decision is a **free ground-truth label** for the counterfactual "what would mode-2 Gutty have done?" Log Gutty's *recommended action* (send Quote X / don't) at tee-up time and compare with what the asesora actually did. Agreement rate over N conversations is the primary promotion metric — no extra labeling work for the 1-person quality team. This mirrors the 2026 industry-standard shadow→canary→segment pipeline (https://www.getcargo.ai/blog/llm-evals-for-revenue-agents-2026 , https://tianpan.co/blog/2026-04-09-llm-gradual-rollout-shadow-canary-ab-testing , https://futureagi.com/blog/llm-eval-shadow-traffic-canary-2026/).

**Finding 3.2 — Concrete gate proposal (per product line, per brief F9 "launch every product in mode 3"):**

- **Gate A — offline suite**: 50–200 test cases per product workflow (Cargo's recommended size: "50–200 examples per workflow is enough to catch big regressions", URL above). Must include: exact-price recall (100% required), quote-amount determinism (100%), objection scripts, forbidden-claim probes, escalation triggers. Any money/health case failure = hard fail.
- **Gate B — shadow agreement**: ≥50 mode-3 conversations for that product where Gutty's recommended action was logged; ≥90% action-agreement with the human asesora AND **zero critical failures** (wrong price stated, invented claim, missed mandatory escalation, wrong contact linked). 50 clean conversations bounds the true critical-failure rate below ~6% at 95% confidence (rule of three: 3/n); if you need <2%, require 150 clean.
- **Gate C — canary**: mode 2 enabled for 10% of that product's leads (or one segment, e.g. VE-only) for 2 weeks; **100% human post-hoc review of every payment-link/quote send** during canary (volume is small: at 1,000 leads/mo and ~10% reaching quote stage, canary ≈ 2-3 sends/week — trivially reviewable). Segment-level monitoring, not global averages ("an agent can be great for SMB and terrible for enterprise" — Cargo).
- **Gate D — standing rollback triggers**: any single critical failure in production → auto-demote product to mode 3; weekly sampled review (see 3.3) drift check.

**Finding 3.3 — Transcript review sampling for a 1-person QA team (María José).** Review budget ~1-2 h/week ≈ 15-25 transcripts. Stratify, don't randomize uniformly: (a) 100% of quote/payment sends while any product is in canary; (b) 100% of discount escalations and health-tier conversations flagged by the claims classifier (§4); (c) random 10/week of ordinary sales conversations stratified by outcome (won / lost / ghosted). Statistical honesty: 10/week random sampling detects only gross drift (defect rates >~25% per week, >~7% per month); the safety net for rare failures must be the deterministic checks + claims classifier on 100% of turns, with human review reserved for calibration. LLM-as-judge (Langfuse-hosted rubric: 1-5 on Spanish register, qualification progress, claim compliance, correct next step) triages which transcripts surface to her queue — standard 2026 practice (https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide , https://www.adaline.ai/blog/complete-guide-llm-ai-agent-evaluation-2026). Judge scores gate NOTHING alone; they only rank the human review queue.

## 4. Guardrails for health-adjacent selling claims

**Finding 4.1 — Regulatory exposure is real for the US slice of the base.** FTC has brought 120+ cases on supplement health claims in a decade (https://www.ftc.gov/news-events/topics/truth-advertising/health-claims); the operative standard is the Health Products Compliance Guidance (https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance): claims need competent substantiation; disease claims are off-limits without authorization. FTC opened 6(b) inquiries into consumer AI chatbots in Sept 2025 with an explicit health-care nexus (https://www.americanbar.org/groups/health_law/news/2025/ftc-consumer-ai-chatbots-health-care/) and AI-chatbot medical claims drew fresh regulatory scrutiny in June 2026 (https://www.cooley.com/news/insight/2026/2026-06-25-ai-chatbots-medical-claims-draw-regulatory-scrutiny). EU residents add EFSA/UCPD constraints (not researched in depth — R8). Venezuela enforcement is weak but the constraint is reputational + the US/EU patient slices.

**Finding 4.2 — Guardrail architecture (converging industry pattern**, e.g. https://qredible.com/ai-meets-supplement-compliance-how-technology-can-help-businesses-manage-product-information/**):**
1. **Approved-claims registry**: a curated whitelist of structure/function phrasings per product/plan, versioned like the Products `id` allowlist (F2). Sales composition may only assert claims present in the registry; everything else is phrased as "esto se evalúa en tu consulta."
2. **Disease-claim blocklist + output classifier**: cheap classifier (Haiku-tier or regex+embedding) on EVERY outbound sales turn flagging cure/treat/diagnose language ("cura", "trata", "elimina tu tiroiditis", "revierte la diabetes"). Block-and-rewrite or block-and-canned, log to review queue. This runs on 100% of turns — it, not sampling, is the real safety net.
3. **Mandatory framing**: SKILL.md rule 5 ("frame as needing a consulta") generalizes into the sales system prompt: *the product being sold is evaluation + accompaniment, never a health outcome*. Testimonial-style claims ("a nuestros pacientes les ha ido excelente con X síntoma") are FTC-risky too — registry-gate them.
4. **Cost-of-inaction reframes are the danger zone**: "si no atiendes tu intestino esto empeora" is a fear-based implied disease claim. The objection playbook (§2) must exclude health-outcome cost-of-inaction; only convenience/price-of-delay framings allowed.
5. **RAG output is not claim-safe by default**: retrieved marketing copy from `knowledge/raw/` may contain aspirational claims; sales-path composition must pass retrieved text through the same claims classifier (F11 will ingest heterogeneous Drive content).

## 5. REAL measured AI-SDR outcomes (skeptical read)

**Finding 5.1 — Independent evidence says full-autonomy AI sellers underperform humans on close-quality.** The strongest documented datapoint is TechCrunch's Mar-2025 investigation of 11x (a16z/Benchmark-backed): ~70-80% customer churn, ARR counted from broken trial contracts (~$3M real vs $14M claimed), and ZoomInfo stating the product "performed significantly worse than our SDR employees" in a live pilot (https://techcrunch.com/2025/03/24/a16z-and-benchmark-backed-11x-has-been-claiming-customers-it-doesnt-have/). Founder stepped down May 2025.

**Finding 5.2 — Head-to-head experiment (weak but directional):** a $15K experiment (attributed to Dashly, secondary-reported; methodology, sample size, timeframe NOT published — **UNVERIFIED beyond secondary reporting**) found the human SDR generated 2.6× more revenue ($147K vs $56K) with 71% vs 52% meeting show rate, while the AI was ~54× cheaper (https://salesmotion.io/blog/ai-sdrs-vs-human-sdrs). Topo.io's "only 2% of AI SDR implementations stick; 50-70% churn within a year" is likewise secondary/**UNVERIFIED**. Vendor-side counterclaims (35% higher conversion, 60% lower CPL — https://www.landbase.com/blog/how-ai-sdr-agents-boost-conversions-by-70-2025) are marketing; discount them.

**Finding 5.3 — Where AI verifiably wins: speed and coverage, not closing.** MIT/InsideSales 2007 (Oldroyd; 6 companies, 15k+ leads): contact within 5 min vs 30 min → 21× odds of qualifying, 100× odds of contact. HBR 2011 audit (2,241 firms): average response 42 h, 23% never respond (https://ainora.lt/blog/lead-response-time-statistics-every-study-2026 , https://greetnow.com/blog/lead-response-time-statistics). Old but never overturned; every 2026 source still anchors on them. **Transferability caveat in NutriWhite's favor:** the damning AI-SDR data is from *cold outbound B2B email* (domain burn, spam-pattern replies). Gutty's job is *inbound/warm* lead response on the buyer's preferred channel — the segment where speed dominates and where AI's weaknesses (relationship depth, complex negotiation) are exactly what mode 3 hands to humans. The hybrid consensus ("AI handles volume + early qualification; humans handle judgment", https://leadsatscale.com/insights/ai-wont-replace-sdr-team-data-how-smart-companies-use-both/) is precisely the brief's mode-3 design — the evidence endorses launching mode 3 and being genuinely conservative about mode 2.

**Finding 5.4 — Implication for the −80% logistics target:** the defensible mechanism is not "AI closes better" (it doesn't, per 5.1-5.2) but (a) 100% of leads touched in <1 min instead of hours (21× qualify odds), (b) humans only enter pre-qualified, context-packaged conversations, (c) mode 2 only for products whose purchase decision is already made by the time the link is sent (low-judgment closes). Model hours saved on qualification/first-touch, not on closing.

## 6. LatAm WhatsApp selling norms

- **Response-time expectation is brutal**: 60% expect <10 min; >30 min is unacceptable for 82%; actual LatAm business average is 2-4 h (https://www.aurorainbox.com/en/2026/03/04/response-time-sales-impact/ — vendor blog, plausible; **treat exact %s as soft**). An always-on agent's biggest lever is simply existing.
- **Channel dominance**: ~72% of LatAm conversational-commerce volume runs through WhatsApp; conversion benchmarks of 5-25%+ circulate but are vendor-reported (https://www.aurorainbox.com/en/2026/03/04/ecommerce-statistics-whatsapp-latam/ , https://mazkara.studio/en/newsletter/whatsapp-penetration-latin-america-2026/) — **UNVERIFIED, do not build the business case on them**.
- **Norms that shape the agent**: business is personal and informal; relationship beats brand; negotiation attempts are normal (§2); voice notes are common (inbound media currently dropped — need at least a graceful "¿me lo escribes?" or transcription later); conversations sprawl across days (the FSM + Zoho state must resume mid-qualification without re-asking); small talk / blessings ("Dios te bendiga") are normal and the VE register must handle them warmly (persona strength already).
- **Venezuela-specific**: payment friction is a first-class objection class (Zelle, pago móvil, cash, currency mix — already in FAQ copy); purchasing power spread means the free 15-min call is the universal safe next step.

## 7. Options assessed (verdicts)

| # | Option | Verdict |
|---|---|---|
| O1 | **Slot-schema qualification (SPICED-lite, 7 slots in Zoho fields; code picks next question, LLM extracts+phrases)** | RECOMMEND — the only pattern with production evidence of surviving LLM implementation; fits existing deterministic spine |
| O2 | Freeform persona-prompt sales agent (no structured qualification state) | REJECT — slot drift, re-asking, hallucinated completeness; unreviewable |
| O3 | Buy an AI-SDR product (11x/Artisan class) | REJECT — 70-80% churn + credibility collapse (TechCrunch), English/B2B-cold-email-centric, no PHI posture, no VE Spanish |
| O4 | **Mode-3-as-shadow-mode graduation harness** (log recommended action at tee-up; human decision = free label; gates A-D per product) | RECOMMEND — zero extra labeling cost for 1-person QA; statistically honest promotion |
| O5 | Permanent mode 3 (never send payment links autonomously) | VIABLE FALLBACK — keep as default state; mode 2 is an earned per-product privilege, not a launch requirement |
| O6 | **Approved-claims registry + 100%-of-turns claim classifier** for health-adjacent copy | MUST-HAVE regardless of architecture — sampling alone cannot catch rare claim violations; FTC AI-chatbot scrutiny is active |
| O7 | One-reframe-then-escalate bounded objection loop with precomputed price-decomposition constants | RECOMMEND — bounds the highest-hallucination-risk conversation pattern |

## 8. Open questions

1. Where exactly does the PHI boundary sit when a *lead* volunteers symptoms during qualification (R8 to answer) — determines which model/provider path composes sales turns and whether health-tier slots can live in Zoho Lead fields at all.
2. No independent data exists on AI sales-agent win rates for *inbound WhatsApp B2C health services in Spanish* — the closest data is cold-B2B-email and vendor LatAm commerce claims; NutriWhite will be generating its own primary evidence (which is what gates A-D are for).
3. What fraction of current won deals involve human negotiation beyond one reframe? (Zoho Deals history could answer; determines mode-2 ceiling per product line.)
4. Exam presupuestos (F2) vs consultation plans may deserve different mode-2 gates — exams are itemized quotes (higher wrong-amount risk), plans are 3 fixed SKUs (lower). Suggest plans graduate first.
5. Voice-note inbound: transcribe (Whisper-class, PHI-safe hosting?) or deflect? Affects qualification completion rates materially in LatAm; currently dropped at `waha.py:42`.
