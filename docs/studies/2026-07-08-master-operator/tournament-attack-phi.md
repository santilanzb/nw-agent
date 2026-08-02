# Tournament Red-Team — Attacker "phi" (PHI / GDPR / BAA lane)

> **Study:** Cerebro Gutty v3 — Master Operator · **Stage:** Tournament red-team · **Date:** 2026-07-10
> **Target:** surviving base **C1 "Evolve-Current v3"** (`candidate-C1.md`) **with synthesis grafts G1–G10 applied** (`synthesis.md` §3), plus the C1-advocate grafts G-a…G-f where they bear on privacy.
> **Method:** every load-bearing legal/product claim re-verified on the web 2026-07-10 (URLs inline); repo claims verified in code. Unverified items marked UNVERIFIED.
> **Verdict:** **graft_required.** The base shape (one droplet, in-process DBOS, few vendors, content-gated split) is privacy-*favorable* — but as written it violates the brief's own hard constraint ("PHI never touches a provider without BAA", BRIEF §3) in two places by construction, cannot execute an Art. 17 erasure end-to-end, and is missing the entire GDPR administrative layer. All fixable with the six mandatory grafts in §3. No flaw found that requires abandoning the base.

---

## 0. The attacker's frame

C1+grafts claims its compliance boundary is: **content-gated class split mounted at the classifier + Art. 9(2)(a) consent micro-flow + class-routed models/stores/retention**, with redaction explicitly demoted to "defense-in-depth, never the compliance boundary" (C1 L13, R8 §4). My attack strategy is to walk the actual data path of one message — *"Hola, tengo hipotiroidismo y me mandaron un perfil tiroideo, ¿cuánto cuesta?"* sent by a brand-new lead — and enumerate every place it lands **before, around, and after** that boundary. The boundary turns out to sit downstream of two third-party disclosures and upstream of at least five stores the erasure design never reaches.

R8's legal analysis (content triggers Art. 9, not CRM status; unsolicited receipt counts; GDPR is the binding regime, HIPAA voluntary) is correct and well-sourced — I attack the *implementation geometry*, not the legal theory.

---

## 1. Findings

### F1 — FATAL(-as-designed) · The privacy gate is mounted *behind* an ungated third-party disclosure: every inbound message is sent raw to OpenAI before any class exists

The design mounts the health-content gate "at the classifier (which already inspects every turn, zero added latency)" (C1 L13; R8 §2 Pattern C). But the classifier **is** an OpenAI API call: `rag_api/intent.py` → `EmbeddingClient` embeds the raw message text (OpenAI, 1536-dim — verified in repo: `src/company_agent/rag_api/intent.py:53-57`, `src/company_agent/common/embeddings.py`; CLAUDE.md confirms `EMBEDDING_PROVIDER=openai`). The same applies to every `kb_search` / `/v1/retrieve` query embedding once F1's RAG wiring lands (C1 L4), and to any health-turn text that reaches ingest-side embedding.

So for the test message above, the sequence is: raw Art. 9 content → **OpenAI embeddings API (US, no BAA, no ZDR, no DPA named anywhere in the study)** → *then* the gate fires → *then* consent is asked. The disclosure precedes the boundary on 100% of turns, by architecture. Neither candidate-C1.md, the synthesis, nor any research note mentions an OpenAI BAA or DPA — the provider inventory in L12 covers Anthropic and Google only.

Verified 2026-07-10: OpenAI signs API BAAs, but coverage extends **only to Zero-Data-Retention-eligible endpoints, with ZDR approval requested in advance and configured per call**; embeddings are ZDR-eligible, and a signed BAA with non-ZDR calls is out of scope on those calls ([OpenAI — data controls](https://developers.openai.com/api/docs/guides/your-data); [Protecto — what the OpenAI BAA covers](https://www.protecto.ai/blog/openai-hipaa-baa-what-it-actually-covers-and-what-leaves-phi-exposed/); [AccountableHQ](https://www.accountablehq.com/post/is-openai-hipaa-compliant-current-status-baas-and-secure-alternatives)). Default non-ZDR retention is 30 days for abuse monitoring.

Under the brief's hard constraint this is a violation on every symptom-bearing turn. Under GDPR it is Art. 9 processing via a US processor with no documented Art. 28 DPA, no Art. 46 transfer tool, and no Art. 9(2) basis at time of disclosure (consent hasn't been asked yet).

**Why not base_breaking:** the fix is cheap and does not disturb the spine. (a) Immediately: execute the OpenAI BAA + approved ZDR on the embeddings endpoint and treat the embedding call as inside the care boundary (also sign the OpenAI DPA/SCCs for the GDPR leg). (b) Structurally (Stage 4): move classification + query embedding to a **local multilingual embedding model** (bge-m3 / multilingual-e5-class, CPU-viable at 65 msgs/day on the droplet) and re-seed `intent_vectors`; this removes the third party from the pre-gate path entirely and is the only version in which "the gate is the boundary" is actually true. → **Mandatory graft M1.**

### F2 — SERIOUS · The Batch API path launders conversation-derived Art. 9 content through the BAA exclusion, with an admittedly-unproven redactor as the only boundary

C1 L12/L14: nightly judge + learning proposals run "on **redacted marketing text only** via Batch at 50% discount"; the judge covers "100% of LLM-composed **sales** turns." Verified 2026-07-10: the Batch API is *"Not covered under Anthropic BAA and not accessible for HIPAA-Ready API users"* ([Anthropic BAA article](https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers) — also confirms sync Messages **is** covered, with the 30-day-retention / no-ZDR condition on Covered Models).

Two stacked failure layers stand between patient symptoms and that excluded endpoint:

1. **Class assignment** — an embedding gate with **no measured recall on VE-Spanish WhatsApp register** (R8 §4: "no tool is benchmarked for this register"; the eval set is a Stage-4 deliverable). Sales conversations at a health-services company are precisely where leads volunteer conditions (R8 §1: "NutriWhite's leads self-select by health condition and will state it unprompted") — so the population feeding the judge is the highest-risk population, not the lowest.
2. **Redaction** — which the design itself declares "defense-in-depth, never the compliance boundary" (C1 L13). For Batch inputs there is nothing else: redaction **is** the boundary, in direct contradiction of the design's own framing.

Expected-leak arithmetic: at ~4,000 composed turns/mo with even a 5% gate false-negative rate on health content and 85–90% redaction recall on names (optimistic for an unbenchmarked register), tens of identifiable health-content turns per month flow to a non-BAA endpoint — as a *scheduled job*, not a tail event.

The economics being protected are ~$7–15/mo (50% of a ~$15 judge line, C1 §7). That is noise against the risk. → **Mandatory graft M2:** no conversation-derived text (redacted or not) to Batch until the in-house VE redaction eval exists and a named owner (María José / calidad@) signs a recall threshold; run judge + learning jobs on the sync BAA path meanwhile; pull the redaction eval forward from Stage 4 to a precondition.

### F3 — SERIOUS · The handoff context package pushes raw conversation text into Zoho Notes and a consumer WhatsApp group — both outside every L13 control

C1 L10/F3: ticket = **Note on the Contact** carrying a context package of "qualification slots, cadence history, **last-N turns**, negotiation context"; team coordination (claim/resume, ask-first approvals pre-G1) runs in a **WAHA WhatsApp team group** until Chatwoot lands at Stage 3 (G1).

Consequences for a care-class conversation:

- **Zoho Notes** cannot be field-level encrypted (Zoho's encryption applies to designated fields, not Notes bodies — [Zoho HIPAA settings](https://help.zoho.com/portal/en/kb/crm/security-control/compliance-setting/hipaa/articles/hipaa-compliance-with-zoho-crm)); Notes are visible to every CRM user, are copied into Zoho exports/backups, and sit on **no retention clock** — the 12-mo/30-d purge workflows (L13) enumerate Postgres stores, not CRM Notes. An Art. 17 request cannot be honored without a manual Zoho Notes sweep nobody has specified. Zoho's Recycle Bin (60-day restore — cited by C1 L7 as an undo *feature*) also means a "deleted" Note is not erased for 60 more days.
- **WAHA team group**: the context package replicates onto every asesora's **personal phone** in consumer WhatsApp — no retention, no access control, no erasure path, ever. Between Stage 0 and Stage 3 this is the *primary* approval/handoff surface, and G1 does not retro-purge it.

→ **Mandatory graft M3:** context-by-reference — the Note and the group message carry ticket id + deep link (to Chatwoot post-G1; to a minimal authed console view or redacted 2-line summary pre-G1), never raw turns; wire Zoho Notes into the retention workflows; document the group as class-restricted (care-class handoffs get reference-only pushes) until retired.

### F4 — SERIOUS · Art. 17 erasure is not implementable end-to-end: backups, outbox, DBOS step outputs, Phoenix, Chatwoot-Redis, and derived memory stores are all outside the purge design

The retention design (L13, R8 §5) purges `turn_log` + CRM records on 12-mo/30-d clocks keyed on `phone_hash`. Walk an actual erasure request against every store the architecture creates:

| Store | Covered by design? | Gap |
|---|---|---|
| `turn_log` raw `inbound_text`/`reply_text` (verified: `brain/turn_log.py:37,50`) | Yes (purge job) | keyed on phone_hash only; needs identity_registry join for multi-channel identities |
| **Nightly `pg_dump` → DO Spaces** (L16) | **No** | PHI-bearing full dumps; no stated retention; a purge is silently undone by any restore; no restore-repurge SOP |
| **`send_intents` outbox** | **No** | rows written *before* transport necessarily carry the rendered outbound text (or enough to re-send); G4's no-raw-text rule covers **DBOS workflow payloads only**, not this table |
| **DBOS system tables** (completed workflow/step history) | Partially (G4/G-a) | G4 bars raw text in workflow *inputs/step outputs* — but a saga's LLM-compose step *output is the message text* unless the rule is extended to step outputs by reference; quarterly audit is the only enforcement named |
| `patient_facts` / `episode_summaries` / `patient_episodes` | **No** | derived Art. 9 content; no temporal validity (punch-list, acknowledged), no erasure key, no purge job named |
| Phoenix traces (L14) | Partially | redaction-before-write claimed, but retention/purge for traces never specified; see also F10 (error-path spans) |
| Chatwoot (G1) | Partially | G1 wires Chatwoot **Postgres** into retention; Sidekiq/Redis job payloads and ActiveStorage attachments (inbound media, quote PDFs) are separate stores |
| Zoho Notes / Recycle Bin | **No** | see F3 |
| WAHA team group | **No** | see F3; structurally unerasable |

→ **Mandatory graft M4:** one owned **erasure workflow** keyed on `identity_registry` that enumerates every store above; backup retention ≤ 30–35 days with a documented restore-repurge step; extend G4's rule to `send_intents` (store template ref + variable refs or a turn_log FK, never rendered text) and to DBOS **step outputs**; give `patient_facts`/episodes validity + erasure keys (the punch-list fix, made a compliance deliverable).

### F5 — SERIOUS · The class gate fails open into a non-BAA consumer Gemini endpoint, and the design never states the default

Marketing-class turns route to Gemini 3.5 Flash via the plain Google SDK (C1 L12). Verified 2026-07-10: the **consumer Gemini API is not on Google's HIPAA-covered list; only enumerated Vertex AI / Gemini Enterprise services under the GCP BAA are covered** ([Google Cloud HIPAA](https://cloud.google.com/security/compliance/hipaa)) — exactly what G5 documents, while deferring Vertex setup. So every gate **false negative** — unmeasured on this register (F2) — is an Art. 9 disclosure to an uncovered US endpoint, and every classifier **outage** hits an unspecified default: the repo's classifier failure mode is `fallback_llm` (CLAUDE.md; `classifier_client.py`), and nothing in C1 says which *data class* an unclassifiable turn assumes. A privacy design whose failure mode is undefined fails open.

(GDPR leg, weaker but real: Google's paid Gemini API offers processing terms, but no DPA/SCC execution is named anywhere in the study — see F7.)

→ **Mandatory graft M6:** written **fail-closed rule** — gate error, classifier degradation, low-confidence class, or any turn carrying an unresolved health signal routes to the care path (Anthropic sync BAA) and redacted observability; add a gate-recall metric (weekly review labels feed it) with an alarm threshold; misclass discovered in review retroactively re-classes the conversation and triggers the F4 erasure workflow against non-care stores.

### F6 — SERIOUS · Consent-scope conflation: Art. 9(2)(a) consent to *be advised about your health* is not consent to *be sold to using your health data*

The micro-flow wording ("Para poder orientarte sobre tu salud necesito tu permiso para guardar y procesar esa información…", R8 §1) establishes a care-orientation purpose. But F9 then stores **health-tier qualification slots on Zoho Lead fields** and uses them to select pitches, objection reframes, and exam presupuestos (C1 L9) — and the cadence engine may later re-engage the same contact with marketing templates. GDPR consent must be purpose-specific and granular; using volunteered symptoms for sales personalization is a *distinct purpose* needing its own consent record, and profiling with special-category data for commercial targeting is the fact pattern EU regulators actually fine ([ICO conditions for processing](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-are-the-conditions-for-processing/)). Second gap: C1 L6 checks "consent ledger + suppression" before every send — **conversation_class is not listed as a cadence-eligibility input**, so a care-promoted or consent-declined lead can be re-enrolled in marketing cadences that reference nothing health-specific yet are *selected because of* health data.

→ Fold into **M5**: purpose-granular consent flags (care-processing / sales-use-of-health-data / marketing-contact) in the consent ledger, one extra Spanish sentence in the micro-flow; cadence eligibility gains a `conversation_class` + consent-purpose check; consent-declined → suppress health-adjacent templates automatically.

### F7 — SERIOUS (paperwork, but legally load-bearing) · The entire GDPR administrative layer is missing: Art. 27 representative, Art. 35 DPIA, Art. 30 RoPA, and a DPA/SCC inventory

NutriWhite is a non-EU controller squarely inside Art. 3(2) (services knowingly offered to EU residents — brief §3). Consequences no study document mentions:

- **Art. 27 EU representative is mandatory.** The exemption requires *cumulatively*: occasional processing AND no large-scale special-category processing AND unlikely risk ([Art. 27](https://gdpr-info.eu/art-27-gdpr/); [IAPP on Art. 27](https://iapp.org/news/a/representatives-under-art-27-of-the-gdpr-all-your-questions-answered)). Systematic Art. 9 processing of an EU patient cohort fails at least two prongs. Fines up to €10M/2% under Art. 83(4)(a). Cost to fix: ~€500–1,500/yr for a representative service.
- **Art. 35 DPIA** is triggered on its face: large-scale(ish) special-category data + systematic evaluation + innovative technology (LLM agent). The DPIA is also exactly where the F1/F2/F5 data-path decisions get documented and defended.
- **Chapter V transfers:** disclosures by a GDPR-subject controller to US processors are "transfers" (EDPB Guidelines 05/2021 criteria); every vendor in the stack — DigitalOcean (droplet + Spaces backups), OpenAI, Anthropic, Google, Meta/WhatsApp, ManyChat, Zoho — needs an executed DPA with SCCs or DPF reliance. **Zero DPAs are inventoried anywhere in the five candidates or the synthesis.** All are routinely available; none are signed by accident.
- Related: ManyChat holds raw IG DMs (symptom-bearing first messages) as a US SaaS with no privacy treatment in the design at all (C1 L2/F10) — include it in the inventory and configure minimal payload forwarding.

→ **Mandatory graft M5:** a Stage 0–1 compliance work-package: EU representative, DPIA, RoPA, per-vendor DPA/SCC checklist (incl. OpenAI and ManyChat), plus the F6 consent granularity. Days of work + small recurring cost; without it the architecture's GDPR story is oral tradition.

### F8 — MINOR · 12-month full-transcript retention for lost leads is at the indefensible end for a weeks-long sales cycle

R8's own sources say 6–12 months is "probably too long" when the cycle is ~3 months ([DMA retention guidance](https://dma.org.uk/uploads/misc/5a37d2135f15c-data-retention_4_5a37d2135f0aa.pdf)); NutriWhite's lead→consulta cycle is *weeks* (R8 §5). Holding full transcripts — including consented health content whose care purpose lapsed with the lead — for 12 months is a documented-but-weak Art. 5(1)(e) position. Recommend: 6 months for lost-lead transcripts; care-class content of lost leads on the shorter clock; suppression tombstone unchanged.

### F9 — MINOR · Anthropic BAA feasibility is a single point of failure with no defined GDPR fallback posture

BAA execution for a small Venezuelan non-covered-entity is sales-gated and UNVERIFIED (R8 O2; C1 open question 3). If Anthropic declines, the design's care path has no lawful provider *under its own rule* — yet the rule is voluntary (HIPAA doesn't bind — R8 §3), and a GDPR-sufficient fallback exists: Anthropic commercial DPA + SCCs + no-training + 30-day retention on sync Messages. Name that fallback now and have the user sign the posture choice, so a BAA refusal at Stage 0 doesn't stall cutover or, worse, get papered over silently.

### F10 — MINOR · Error-path telemetry bypasses the redactor

Synthesis stress-test #4 asked this of C2; C1+grafts has the same hole in different clothes: the owned provider router instruments via OTel → Phoenix (L14), and default GenAI semconv span conventions record prompt/completion content; exception payloads and retry context (httpx errors carrying request bodies) route around a "redact before trace write" step implemented at the happy path. Fix inside M4/M6: allowlist span attributes; never record `gen_ai.prompt`/`completion` for care-class turns or when redaction fails; scrub exception messages of request bodies at the router boundary.

---

## 2. What survives the attack (credit where due)

- **R8's legal spine is right**: content-triggered Art. 9, GDPR-binding/HIPAA-voluntary framing, consent micro-flow, content-gated split. The *placement* is wrong (F1/F5), not the theory.
- **Honesty about redaction** (unsolved for VE Spanish, defense-in-depth only) is real — the design just fails to notice two places where it quietly re-promotes redaction to sole boundary (F2) or forgets the boundary entirely (F3).
- The **single-droplet, in-process, few-vendor shape** is the most erasure-friendly and transfer-minimal topology of the five candidates; C5's extra vendor plane and C3's service sprawl would have made F4/F7 strictly worse. This is why the verdict is graft_required, not base_breaking.
- G4/G-a (no-raw-text workflow payloads) is the right instinct — it just needs its scope extended (step outputs, `send_intents`) to actually close the Art. 17 gap it was invented for.

## 3. Mandatory grafts (the price of survival in this lane)

| # | Graft | Fixes | Cost |
|---|---|---|---|
| M1 | **Close the pre-gate embedding leak**: OpenAI BAA + approved per-call ZDR on embeddings **now** + OpenAI DPA/SCCs; migrate classifier/query embeddings to a local multilingual model (re-seed `intent_vectors`) by Stage 4 so the gate truly precedes all third-party disclosure | F1 | days now; ~1 wk at Stage 4 |
| M2 | **No conversation-derived text to Batch API** until the in-house VE-redaction eval passes a recall threshold signed by calidad@; judge/learning jobs on sync BAA path meanwhile; redaction eval pulled forward to a Batch precondition | F2 | +$7–15/mo interim |
| M3 | **Handoff context-by-reference**: no raw turns in Zoho Notes or the WAHA team group (ticket id + link / redacted summary); Zoho Notes wired into retention; Recycle-Bin purge step in erasure | F3 | days |
| M4 | **End-to-end erasure workflow** keyed on identity_registry over all stores (incl. patient_facts/episodes, Phoenix, Chatwoot Redis/attachments); backup retention ≤35 d + restore-repurge SOP; G4 no-raw-text rule extended to `send_intents` and DBOS step outputs; error-path span scrubbing | F4, F10 | ~1 wk |
| M5 | **GDPR admin package**: Art. 27 EU representative, Art. 35 DPIA, Art. 30 RoPA, per-vendor DPA/SCC inventory (DO, OpenAI, Anthropic, Google, Meta, ManyChat, Zoho); purpose-granular consent flags + class-aware cadence suppression; lost-lead retention to 6 mo | F6, F7, F8 | days + ~€500–1,500/yr |
| M6 | **Fail-closed class routing**: gate error / low confidence / classifier degradation → care path (BAA sync) + redacted observability; gate-recall metric with alarm; retro-reclass + erasure on discovered misses; written Anthropic-BAA-refusal fallback posture (DPA+SCCs) for user sign-off | F5, F9 | days |

## 4. Verdict

**graft_required.** Two of the findings (F1, F2) are violations of the brief's hard privacy constraint *as designed*, not as misoperated — so the base does not hold unmodified. But every finding is closed by boundary re-placement, scope extension of an existing graft, or paperwork; none requires replacing the FSM+DBOS+Postgres base, and the base's topology is the best privacy substrate in the candidate field. Confidence: **high** on F1–F5 and F7 (code- and primary-source-verified); medium on F6 magnitude (regulator appetite for a VE controller is untested) and on F8.

### Source index (load-bearing)
- Anthropic BAA scope (Messages covered; Batch excluded; 30-day retention condition): https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers (fetched 2026-07-10)
- Google Cloud HIPAA covered services (Vertex yes; consumer Gemini API absent): https://cloud.google.com/security/compliance/hipaa (fetched 2026-07-10)
- OpenAI BAA = ZDR-eligible endpoints only, per-call ZDR: https://developers.openai.com/api/docs/guides/your-data · https://www.protecto.ai/blog/openai-hipaa-baa-what-it-actually-covers-and-what-leaves-phi-exposed/ · https://www.accountablehq.com/post/is-openai-hipaa-compliant-current-status-baas-and-secure-alternatives
- GDPR Art. 27 + cumulative exemption: https://gdpr-info.eu/art-27-gdpr/ · https://iapp.org/news/a/representatives-under-art-27-of-the-gdpr-all-your-questions-answered
- Art. 9 content trigger / conditions: https://gdpr-info.eu/art-9-gdpr/ · https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-are-the-conditions-for-processing/
- Zoho HIPAA settings (field-level, not Notes): https://help.zoho.com/portal/en/kb/crm/security-control/compliance-setting/hipaa/articles/hipaa-compliance-with-zoho-crm
- Repo verifications: `src/company_agent/rag_api/intent.py:53-57` (raw message → embedding), `src/company_agent/agent_core/brain/turn_log.py:37,50` (raw text stored), CLAUDE.md (`EMBEDDING_PROVIDER=openai`, classifier pipeline).
- UNVERIFIED: Anthropic BAA execution for small VE entity; Google paid-Gemini-API DPA execution mechanics; EDPB Pseudonymisation Guidelines final text; actual gate/redaction recall on VE-Spanish WhatsApp register (the eval set does not exist yet — that absence is itself finding F2/F5's fuel).
