# R8 — Privacy architecture for the two data classes (lead/marketing vs patient PHI)

> Researcher R8 · 2026-07-08 · Study: Cerebro Gutty v3 "Master Operator"
> Scope per BRIEF §6 R8: legal boundary when a lead spontaneously discusses symptoms pre-patient; split-processing architectures; HIPAA/BAA scope sales-side vs care-side; Spanish-VE PII/PHI redaction state 2026; retention for lost leads.

---

## 1. Where the legal boundary actually sits: content, not CRM status

**GDPR Art. 9 triggers on what a message reveals, not on whether the sender is a "lead" or a "patient".** Health data is "personal data related to the physical or mental health of a natural person which reveal information about his or her health status" — there is no carve-out for pre-customer contacts ([gdpr-info.eu Art. 9](https://gdpr-info.eu/art-9-gdpr/); [ICO — What is special category data?](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/)).

Three load-bearing points from regulator guidance and case law:

1. **Inadvertent/unsolicited receipt still counts.** Data that indirectly reveals health information must be treated as health data even if the organisation never intended to collect it. The online-pharmacy line of cases (CJEU *Lindenapotheke* logic): purchase/inquiry information is health data "regardless of whether the information relates to the purchaser or another person, whether the information is correct or whether the controller intended to use it" ([Fieldfisher — inadvertent special category processing](https://www.fieldfisher.com/en/insights/may-you-inadvertently-be-processing-special-catego); [URM Consulting](https://www.urmconsulting.com/blog/are-you-processing-special-category-personal-data-without-knowing-it)).
2. **Inference threshold:** ICO draws the line at inference "with a reasonable degree of certainty" — a firm inference is Art. 9 data; a mere "possible inference / educated guess" is not ([ICO guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/)). A lead writing "tengo hipotiroidismo, ¿qué perfil me recomiendan?" is far past that threshold. Merely clicking a Meta ad for a thyroid webinar is closer to the line, but context+content combinations (e.g. exam-specific pages) can already qualify ([Jentis — Art. 9 and digital tracking](https://www.jentis.com/blog/what-is-article-9-of-the-gdpr-sensitive-data-explained-and-how-companies-remain-compliant)).
3. **Purpose is irrelevant to classification.** "Whether the data is processed for tracking, analytics, or marketing purposes is irrelevant" — if the content reveals health status, Art. 9 applies to the marketing pipeline too ([Jentis](https://www.jentis.com/blog/what-is-article-9-of-the-gdpr-sensitive-data-explained-and-how-companies-remain-compliant)).

**Consequence for Gutty:** the moment a WhatsApp lead's *first message* mentions symptoms, that turn — stored in `turn_log`, embedded for intent classification, sent to an LLM, traced to Langfuse — is Art. 9 processing. A **static** split ("Leads pipeline = marketing class until Deal converts") is legally wrong for this business, because NutriWhite's leads self-select by health condition and will state it unprompted. The split must be **content-gated at ingress, per conversation**, with class promotion mid-conversation.

**Lawful basis on each side of the gate:**
- Marketing side (no health content): Art. 6(1)(a) consent or 6(1)(f) legitimate interests for B2C outreach, plus ePrivacy/opt-in rules for proactive messaging (R2's domain).
- The moment health content appears, an Art. 9(2) condition is needed **in addition** to Art. 6. For a private company selling services the realistic conditions are **9(2)(a) explicit consent** (pre-patient) and **9(2)(h) provision of health care** under professional-secrecy obligations (once they are actually under a nutritionist's care) ([ICO — conditions for processing](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-are-the-conditions-for-processing/); [Legiscope Art. 9 overview](https://www.legiscope.com/blog/gdpr-article-9-special-categories.html)). Legitimate interests is effectively unavailable for Art. 9.
- **Design implication:** Gutty needs an explicit-consent micro-flow — when the health gate fires for a non-consented contact, the bot asks one short Spanish question ("Para poder orientarte sobre tu salud necesito tu permiso para guardar y procesar esa información…") and records the consent event (who/when/wording) before continuing the medical thread. Decline → generic answer + human handoff, and the health content is redacted/expired from stores.

**Which laws actually bind, by residency:**
- **EU residents:** GDPR applies extraterritorially under Art. 3(2) (offering services to EU data subjects). Binding.
- **Venezuela:** **no comprehensive data-protection statute exists** — protection rests on Constitution Arts. 28/60 (habeas data) and TSJ Constitutional Chamber jurisprudence; ruling No. 759 of 21 May 2025 consolidated habeas data as the remedy for suppression/rectification/confidentiality of records ([Transparencia Venezuela](https://transparenciave.org/project/en-venezuela-no-existe-una-ley-que-resguarde-los-datos-personales/); [Badell & Grau on TSJ 759/2025](https://badellgrau.com/sala-constitucional-del-tsj-establecio-el-habeas-data-como-mecanismo-para-la-proteccion-de-datos-personales/)). Practical exposure in VE is low but non-zero; sensitive-data consent principles appear in the jurisprudence.
- **US persons:** see §3 — HIPAA almost certainly does **not** legally bind NutriWhite.

So the **binding spine is GDPR Art. 9**; HIPAA-style controls are a voluntary hardening layer. This matters for cost: it licenses the architecture to use HIPAA controls selectively rather than everywhere.

---

## 2. Split-processing architecture patterns

Given the content-gated boundary, the workable pattern set (from GDPR pseudonymisation guidance + standard PHI-segmentation practice):

**Pattern A — single store, treat-everything-as-PHI.** Simple mentally, but: forces BAA-covered sync LLM on 100% of traffic (blocks the cheap Batch path for evals/self-learning — see §3), makes every analytics/marketing query a sensitive-data access, and still doesn't achieve literal HIPAA on WhatsApp (§3). Honest verdict: pays the full cost and buys almost nothing extra legally. Reject.

**Pattern B — static split by record status.** Lead tables = marketing class; patient tables = health class; promotion at conversion. Reject: contradicts the content-trigger law above; NutriWhite leads state conditions in message 1.

**Pattern C — content-gated dynamic split (recommended).**
- **Ingress gate:** every inbound turn passes a health-content detector *before* durable storage and before any non-BAA processing. Implementation: the existing embedding intent classifier already routes turns; add a `health_content: bool` signal (keyword/regex + classifier intent classes like `sintomas`, `consulta_medica` already exist in `intents/intent_seeds.yaml` territory) plus the redactor (§4) as backstop.
- **Two logical stores in the one Postgres:** `marketing` schema (lead records, cadence state, opt-ins, non-health transcripts) and `care` schema (health-flagged transcripts, `patient_facts`, episodes). Enforce with separate DB roles + RLS/grants; column-level encryption (pgcrypto) for health text. Physical separation (second instance) is not needed at 1–3-person scale — EDPB treats pseudonymisation + access segregation as the operative safeguard, and pseudonymised data remains personal data anyway ([EDPB Guidelines 01/2025 on Pseudonymisation, adopted for consultation 16 Jan 2025](https://www.edpb.europa.eu/public-consultations/guidelines-012025-on-pseudonymisation_en); final version publication UNVERIFIED as of 2026-07-08).
- **Class promotion:** conversation flagged health → consent micro-flow → contact's conversation class flips to `care`; all subsequent LLM calls route to the BAA-covered sync path; observability switches to redacted mode.
- **Model routing per class:** marketing class → any allowed provider incl. Batch API for offline work; care class → BAA-covered synchronous Messages API only (§3). China-hosted providers (GLM/Zhipu/DeepSeek) blocked for care class per brief constraint.
- **Derived-data discipline:** embeddings of health turns, Langfuse traces, `turn_log.inbound_text`, eval datasets, and the self-learning `learning_queue` are all "copies" of Art. 9 data. Each needs either the care-class controls or redaction-before-write. **Current code violates this twice:** `anthropic.py:69-72` sends raw system+user text to Langfuse traces, and `turn_log.py` stores raw `inbound_text`/`reply_text` (phone SHA-256-hashed, but hashing the phone is pseudonymisation, not anonymisation — the content itself identifies). Both verified in repo (`src/company_agent/agent_core/llm/anthropic.py`, `src/company_agent/agent_core/brain/turn_log.py`).

**Pattern D — full physical separation (two DBs, two agent deployments, two model accounts).** Correct for a hospital; over-engineered for this team. Only worth revisiting if a US entity/covered-entity relationship appears.

**CRM leg:** Zoho CRM **will sign a BAA** (request via legal@zohocorp.com) and supports field-level encryption for designated ePHI fields ([Zoho CRM HIPAA compliance](https://www.zoho.com/crm/data-security/hipaa.html); [Zoho help — HIPAA compliance settings](https://help.zoho.com/portal/en/kb/crm/security-control/compliance-setting/hipaa/articles/hipaa-compliance-with-zoho-crm)). Since patient exam results/consultas already live in Zoho custom modules, do this regardless of candidate: sign the BAA, mark `Examenes`/`Consultas` health fields encrypted, and keep Gutty's F6 write-authority audit trail (R3) as the access log. Lead-side Zoho records stay ordinary fields.

---

## 3. HIPAA/BAA scope: sales-side vs care-side — the honest read

**Threshold fact the brief glosses over:** HIPAA binds *covered entities* (US providers/plans/clearinghouses that transmit health data in HIPAA standard transactions, i.e. US insurance billing) and their *business associates*. It has no extraterritorial reach; a foreign clinic treating US citizens abroad is generally **not** subject to HIPAA unless it acts as a BA of a US covered entity or itself bills US health plans electronically ([AccountableHQ — Is HIPAA international?](https://www.accountablehq.com/post/is-hipaa-international-does-it-apply-outside-the-u-s); [HHS FAQ on offshore CSPs](https://www.hhs.gov/hipaa/for-professionals/faq/2083/do-the-hipaa-rules-allow-a-covered-entity-or-business-associate-to-use-a-csp-that-stores-ephi-on-servers-outside-of-the-united-states/index.html)). NutriWhite is a Venezuelan cash-pay operation on WhatsApp — almost certainly **not a covered entity** (open question O1 confirms). 

**Reinforcing evidence that literal HIPAA is unachievable on this channel anyway:** WhatsApp Business API is not HIPAA-compliant and **Meta does not sign a BAA** for it; WhatsApp's own Business Terms disclaim regulated-industry fitness ([HIPAA Journal](https://www.hipaajournal.com/whatsapp-hipaa-compliant/); [TeachMeHIPAA](https://teachmehipaa.com/hipaa-baa/communication/whatsapp/)). If HIPAA genuinely applied, the entire product (official Cloud API included) would be non-compliant at the transport layer. Therefore the rational posture is: **GDPR Art. 9 is the binding regime; HIPAA controls are adopted voluntarily as a quality bar on the care side only** — which is exactly the "exploit the split where honest" instruction in the brief.

**Anthropic BAA state (verified 2026-07-08, [Anthropic Privacy Center — BAA for Commercial Customers](https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers)):**
- Covered on the 1P API: **Messages API** (incl. prompt caching, structured outputs, memory, web search, bash/text-editor tools), token counting, models/org/compliance APIs.
- **Batch API explicitly excluded**: "Not covered under Anthropic BAA and not accessible for HIPAA-Ready API users." Also excluded: Files API, Skills API, Code Execution, Computer Use, Web Fetch, most betas. This confirms the brief's constraint: **PHI → synchronous Messages API only.**
- Nuance found: "Covered Models require 30-day data retention and aren't available with zero data retention (ZDR) enabled" for the standard HIPAA-ready path — i.e., HIPAA-readiness is now decoupled from ZDR ([Strac 2026 guide](https://www.strac.io/blog/is-claude-hipaa-compliant); [Aptible](https://www.aptible.com/hipaa/claude-baa)). BAA execution is sales-gated; whether Anthropic signs with a small Venezuelan entity that is not a US covered entity is UNVERIFIED (open question O2).

**What the split buys concretely:**
- **Sales-side (marketing class):** no BAA required → Batch API usable for nightly self-learning/eval jobs on lead conversations **after redaction** (50% batch discount), cheaper non-Anthropic models via a router are permissible, Langfuse traces can keep fuller payloads. This is where most volume lives (500–2,000 leads/mo vs a much smaller patient base).
- **Care-side (health class):** BAA'd sync Messages API; redacted or self-hosted-only observability; Zoho BAA + encrypted fields; retention limits; access restricted to asesoras + María José.

---

## 4. Spanish-VE PII/PHI redaction — 2026 state

Still no turnkey answer for Venezuelan conversational Spanish; the pieces have improved:

- **Presidio (OSS, MIT):** remains the standard framework; 2025–26 releases added a **MedicalNERRecognizer**, **GLiNER/Transformers/Stanza engine support with GPU acceleration (4–10×)**, batch REST processing, ONNX runtime, and a surrogate-anonymization operator ([IntuitionLabs open-source PHI de-id review](https://intuitionlabs.ai/articles/open-source-phi-de-identification-tools); [Presidio docs](https://microsoft.github.io/presidio/supported_entities/)). Multilingual support works via pluggable NLP engines (spaCy `es_core_news_lg`, Stanza es, GLiNER) but Presidio is still English-optimized; Spanish recall must be measured, not assumed ([Presidio — additional languages](https://microsoft.github.io/presidio/tutorial/05_languages/)).
- **Venezuelan identifiers: no off-the-shelf recognizers exist.** Presidio ships `EsNifRecognizer`/`EsNieRecognizer` for **Spain** only ([predefined recognizers](https://microsoft.github.io/presidio/supported_entities/)). V-/E- cédula (`[VE]-?\d{6,8}`) and RIF (`[JVEGP]-?\d{8}-?\d`, with public check-digit algorithm) are regex+checksum-friendly → a `PatternRecognizer` each is a ~1-day task ([adding recognizers](https://microsoft.github.io/presidio/analyzer/adding_recognizers/)). Phone numbers (+58 and diaspora formats) are already covered by libphonenumber-based recognizers.
- **GLiNER2-PII** (released ~May 2026): 0.3B multilingual model, 42 PII entity types at span resolution, best span-F1 on the SPY benchmark among five systems incl. OpenAI Privacy Filter; runs CPU-viable and plugs into Presidio as an engine ([arXiv 2605.09973](https://arxiv.org/abs/2605.09973)). Strongest OSS option for the person-name/address/free-text gap that regexes miss. No Venezuelan-Spanish or WhatsApp-register benchmark exists — UNVERIFIED accuracy on this text.
- **Managed alternative — Azure AI Language PII/PHI:** detects+redacts PII and PHI categories; **Spanish supported** for text PII and (preview) conversational PII ([language support](https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/language-support); [entity categories incl. PHI](https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/concepts/entity-categories)). Microsoft's HIPAA BAA is included by default in the Product Terms/DPA for in-scope Azure services ([Microsoft HIPAA offering](https://learn.microsoft.com/en-us/azure/compliance/offerings/offering-hipaa-us)); Azure AI Language's presence on the in-scope list is behind the Service Trust Portal — UNVERIFIED here. Won't know V-cédula/RIF; would still need the regex layer.
- **John Snow Labs Medical De-identification:** clinically strongest incl. Spanish clinical models, but commercial licensing and Spark-shaped ops are wrong-sized for this team ([JSL vs Presidio](https://www.johnsnowlabs.com/comparing-john-snow-labs-medical-text-de-identification-with-microsoft-presidio/)).
- **LLM-as-redactor:** Haiku-class model via the BAA-covered sync API, prompt-constrained to emit placeholder-tagged text. Handles VE colloquialisms ("me mandaron unos exámenes de la tiroides en el CDI de Guarenas") better than NER, but non-deterministic → use as the *semantic* layer over the deterministic regex layer, never alone for identifiers.

**Honest position (per brief: flag, don't hand-wave):** Spanish-VE redaction remains **unsolved to a certifiable standard**. Treat redaction as **risk reduction for derived stores** (Langfuse, eval sets, learning_queue, Batch inputs), not as the compliance boundary itself. The compliance boundary is the consent gate + class routing (§2). Build a 100–200-turn in-house redaction eval set from real (consented) traffic before trusting any of these tools.

**Recommended stack:** Presidio + spaCy-es + GLiNER2-PII engine + custom V-cédula/RIF/phone `PatternRecognizer`s, self-hosted on the droplet (CPU fine at 65 msgs/day; ~$0 marginal cost) → applied before Langfuse trace write, before turn_log persistence of health-class turns to marketing-visible copies, and before any Batch API job. Azure AI Language as the managed fallback if the in-house eval shows OSS recall <90% on names.

---

## 5. Retention for lost leads

- **GDPR sets no fixed period** — Art. 5(1)(e) storage limitation requires a purpose-tied, documented, enforced period; "indefinitely" is non-compliant ([ICO via GDPR Local CRM guidance](https://gdprlocal.com/crm-data-retention-and-compliance/); [DPO Centre — CRM retention](https://www.dpocentre.com/blog/crm-data-retention-gdpr-compliance/)).
- Practitioner guidance keys retention to sales-cycle length: if sales close within ~3 months, keeping open/unclosed leads beyond 6–12 months "is probably too long" ([DMA data-retention guidance](https://dma.org.uk/uploads/misc/5a37d2135f15c-data-retention_4_5a37d2135f0aa.pdf); [DPO Centre](https://www.dpocentre.com/blog/crm-data-retention-gdpr-compliance/)). NutriWhite's cycle (lead → consulta) is weeks, not years.
- **Meta's own norm:** Lead Ads form data is deleted from Meta after **90 days**, API and UI alike ([Meta Business Help — expired leads](https://en-gb.facebook.com/business/help/1526849577619206); [Meta developers — retrieving leads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving)) — retrieval automation is R1's problem, but it anchors "90 days" as a defensible industry reference point for raw lead-form payloads.

**Proposed policy (cheap to implement with pg_cron):**
- Lost/unresponsive lead (cadence end-state `lost`): retain full record **12 months** from last contact, then purge CRM record + transcripts; keep a minimal **suppression tombstone** (phone hash + opt-out flag + date) indefinitely under legitimate interests, so re-imported leads don't get re-messaged — this mirrors standard suppression-list practice.
- **Health-content turns from never-consented leads:** redact or delete within **30 days** (they are Art. 9 data held without an Art. 9(2) basis; speed matters more here than anywhere).
- Converted patients: clinical-record retention follows professional/medical rules (out of R8 scope; longer).
- `turn_log`/Langfuse traces: align to the same clocks; add a purge job keyed on `phone_hash` + conversation class. `patient_facts` lacking temporal validity (brief §4 punch-list) also blocks correct expiry — fix belongs in any candidate.

---

## 6. Repo findings (verified in code)

| File | Finding |
|---|---|
| `src/company_agent/agent_core/llm/anthropic.py:68-74` | Langfuse trace `input={"system": ..., "messages": ...}` — raw, unredacted turn content leaves the request path into the trace store (self-hosted, but marketing-class access). |
| `src/company_agent/agent_core/brain/turn_log.py:18-52` | Phone SHA-256 hashed (pseudonymisation only), but `inbound_text`/`reply_text` stored raw up to 4,000 chars; no class flag, no retention key. |
| `turn_log` schema (`sql/004_brain.sql`) | No `conversation_class` column, no consent-event table — both needed for the content-gated split. |
| `intents/intent_seeds.yaml` pipeline | The classifier already inspects every turn pre-dispatch — the natural mount point for the `health_content` gate with near-zero added latency. |

---

## 7. Options assessed

| # | Option | Verdict |
|---|---|---|
| 1 | Treat everything as PHI (single class, HIPAA posture everywhere) | Reject — pays full control cost on ~90% marketing traffic, blocks Batch-API economics, and still can't be literally HIPAA on WhatsApp. |
| 2 | Static split by CRM record status (lead vs patient) | Reject — legally wrong: Art. 9 triggers on message content; NutriWhite leads state conditions in message 1. |
| 3 | **Content-gated dynamic split**: ingress health detector + explicit-consent micro-flow + per-conversation class routing (models, stores, observability, retention) | **Recommend** — matches the law, exploits the split honestly, ~1–2 weeks of work on the existing FSM/classifier spine, near-zero run cost. |
| 4 | Full physical separation (2 DBs / 2 deployments / 2 model orgs) | Defer — hospital-grade; revisit only if a US covered-entity relationship appears. |
| 5 | Redaction: Presidio + GLiNER2-PII + custom V-/E-cédula & RIF recognizers (self-hosted) vs Azure AI Language PII (managed, ES support, Azure BAA) vs LLM-redactor | Hybrid — OSS stack as default (~$0/mo), regex layer is deterministic for VE IDs; Azure as fallback pending in-house eval; LLM-redactor only as semantic top-up. All UNVERIFIED on VE-Spanish WhatsApp register — build the eval set. |
| 6 | Retention engine: pg_cron purge jobs + suppression tombstones (12 mo lost leads / 30 d unconsented health turns) | Adopt — trivial cost, closes the Art. 5(1)(e) gap. |

## 8. Open questions

1. Does NutriWhite bill any US health plan or operate a US legal entity? (Determines whether HIPAA binds at all; current read: no → voluntary posture.)
2. Will Anthropic execute a BAA with a small non-US, non-covered-entity company? Sales-gated; UNVERIFIED.
3. Is Azure AI Language on the current HIPAA in-scope services list (Service Trust Portal is gated)? UNVERIFIED.
4. EDPB Pseudonymisation Guidelines 01/2025 — final post-consultation version status as of mid-2026 UNVERIFIED; design to the draft.
5. What consent wording/registry does Zoho already hold for existing marketing sends (affects whether the Art. 9 micro-flow can piggyback on an existing consent record)?
