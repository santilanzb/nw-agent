# R1 — Lead Intake & Identity Resolution (Cerebro Gutty v3)

> Researcher: R1 · Date: 2026-07-08 · Scope: brief §6 R1 — ManyChat/IG outbound webhooks + export mechanics; Meta Lead Ads API (leadgen webhook, 90-day retention, CRM integrations); Zoho workflow triggers/webhooks; identity resolution/dedup across phone (E.164 quirks) / IG handle / email; two-channel race conditions.

---

## 1. Intake source mechanics (2026 state)

### 1.1 ManyChat (IG automations) — push works, pull doesn't

- **External Request** (Dev Tools action inside a flow) is the real-time export path: an action block that POSTs JSON to any URL, with headers, mid-flow. Body can be a custom JSON mapping of ManyChat fields or the one-click "Add full contact data" payload. **Pro-plan feature.** Source: [ManyChat Help — Dev Tools: External Request](https://help.manychat.com/hc/en-us/articles/14281285374364-Dev-Tools-External-request) (page 403s to automated fetch; capabilities corroborated by [Make's ManyChat app docs](https://apps.make.com/manychat) and [community threads](https://community.manychat.com/general-q-a-43/external-request-5586)).
- **No bulk pull:** the ManyChat API cannot list all subscribers; it only reads/writes a *known* contact by id, tags, custom fields, and sends flows ([API swagger](https://api.manychat.com/swagger), [community confirmation](https://community.manychat.com/general-q-a-43/api-subscribers-list-2130)). Bulk export is manual CSV / Google-Sheets-action only ([export help](https://help.manychat.com/hc/en-us/articles/14281439451036-How-to-export-contacts-data)). **Design consequence: capture-at-flow-time push is mandatory; there is no reliable backfill API if a webhook is missed.** Mitigation: a Google-Sheets export action in the same flow as belt-and-suspenders, or periodic manual CSV reconciliation.
- **IG contacts carry no phone/email by default.** Instagram messaging identifies people by **IGSID** (Instagram-scoped user id, unique per business account) plus public profile fields (username, name, profile pic, follower count). Phone/email exist in ManyChat **only if the flow asks for them**. Source: [Meta — Instagram User Profile API](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/user-profile), [legacy Messenger-platform doc](https://developers.facebook.com/docs/messenger-platform/instagram/features/user-profile/).
- **Pricing 2026:** Pro from ~$29/mo for 2,500 active contacts; overage ~$0.05/contact/mo (monthly billing); AI add-on ~$29/mo; the Free tier was cut to 25 active contacts + 4 automations on 2026-03-02. Sources: [manychat.com/pricing](https://manychat.com/pricing), [SetSmart pricing analysis](https://setsmart.io/blog/manychat-pricing), [creatorflow analysis](https://creatorflow.so/blog/manychat-pricing-trap/). At 500–2,000 leads/mo NutriWhite plausibly stays in the 2,500–5,000 active-contact band → **$29–$105/mo** if contacts are archived aggressively (overage math UNVERIFIED against their actual account).
- Retry behavior of External Request on target-endpoint failure is **UNVERIFIED** (doc unreachable to fetcher; community reports suggest no durable retry). Assume at-most-once from ManyChat → our intake endpoint must be fast (enqueue-then-200) and we must tolerate silent loss (reconciliation via tag + Sheets export).

### 1.2 Meta Lead Ads — webhook is metadata-only; 90-day hard retention

- The `leadgen` webhook payload contains **only** `leadgen_id`, `page_id`, `form_id`, `ad_id`, `adgroup_id`, `created_time` — *no field data*. You must call the Graph API with the `leadgen_id` to fetch answers. Source: [Meta — Webhooks for Leadgen](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-leadgen/) (fetched 2026-07-08).
- **Retention: leads are retrievable for 90 days after submission; after that they are gone via Ads Manager, Business Suite, and API.** Sources: [Meta Business Help — Download or retrieve your leads](https://www.facebook.com/business/help/734933888443065?locale=en_GB) (title-confirmed; body blocked to fetcher), corroborated by [LeadSync guide](https://leadsync.me/blog/meta-lead-gen-api-guide/) and [dltHub source docs](https://dlthub.com/context/source/facebook-lead-ads). Page-level read rate limit ≈ `200 × 24 × leads_created_past_90d` ([Meta — Retrieving Leads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving)) — a non-issue at 2k/mo.
- **Access cost is bureaucratic, not technical:** App Review with **Advanced Access** for `leads_retrieval` + `pages_manage_ads` (plus `pages_show_list`, `pages_read_engagement`, `ads_management`, `pages_manage_metadata` for the subscription), Page access token from a user with ADVERTISE task, page subscribed via `subscribed_apps` with the `leadgen` field, and **Business Verification**. As of May 2026 Meta dropped the screen-recording requirement and shows approval criteria in the App Dashboard. Sources: [Meta — Lead Ads](https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads), [Meta webhooks doc above](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-leadgen/), [Advanced Access explainer](https://singhamandeep.com/what-is-meta-advanced-access/). For a 1–3-person team this is days-to-weeks of process, and the app must stay compliant thereafter.
- **The Zoho-native alternative avoids all of the above:** Zoho Social's Lead Forms module was **deprecated for new signups 2024-04-19**; the current native path is the **Zoho LeadChain** marketplace extension, which syncs Meta Lead Ads forms into Zoho CRM (Zoho holds the Meta app + permissions, not us). Sources: [Zoho Social FAQ noting deprecation → LeadChain](https://help.zoho.com/portal/en/kb/social/faqs/integrations/articles/why-are-my-leads-from-facebook-leads-ads-not-in-sync-with-zoho-crm), [Zoho — Connecting Facebook Lead ads with Zoho CRM (LeadChain)](https://help.zoho.com/portal/en/kb/zoho-lead-chain/creating-chains/facebook/articles/integrating-facebook-lead-ads-with-zoho-crm), [marketplace listing](https://marketplace.zoho.com/app/crm/connect-facebook-leads-to-zoho-crm). LeadChain sync latency and per-lead pricing: **UNVERIFIED** — must be piloted. Third-party bridges (LeadsBridge ~$… , Zapier) exist ([LeadsBridge Zoho guide](https://leadsbridge.com/blog/zoho-crm/)) but add a vendor + monthly fee for something Zoho covers.

### 1.3 Zoho-side triggers (records already landing in Zoho, incl. manual entry)

Two mechanisms to get "a record appeared/changed in Zoho" into the brain:

1. **Workflow rule → webhook (instant action).** Fires on create/edit/field-update conditions; no expiry; limits: 6 webhooks per rule (1 instant + 5 time-based), 125 rules/module (75 active), 2,500 org-wide, and historically **~10 CRM fields max per webhook payload**. Sources: [Zoho — Creating Webhooks](https://help.zoho.com/portal/en/kb/crm/automate-business-processes/actions/articles/webhooks-workflow), [Workflow limits API](https://www.zoho.com/crm/developer/docs/api/v8/workflow-limits.html), [Configure Workflow Rule API](https://www.zoho.com/crm/developer/docs/api/v8/config-workflow.html). **Design consequence: send `{module, record_id, event}` only; the brain re-fetches the full record via COQL** — sidesteps the field cap and stale-payload problems.
2. **Notification API ("watch").** Channel-based subscriptions to `Leads.create`, `Contacts.edit`, etc., with per-field filtering since v6 — but **max channel expiry is 1 day (default 1 hour)**, so it needs a renewal cron and re-subscribe-on-failure logic. Source: [Zoho — Notifications API overview](https://www.zoho.com/crm/developer/docs/api/v8/notifications/overview.html). Verdict: unnecessary moving part for this team; workflow webhooks win. Watch is the fallback if a needed trigger shape isn't expressible as a workflow rule.

Manual entries need nothing special: workflow rules fire regardless of how the record was created — **including via API**, which creates a **feedback-loop hazard**: the brain's own writes re-trigger the webhook. Loop guard required (condition on the record's `Source`/owner, or drop events whose `Modified_By` is the integration API user; exact rule-condition mechanics UNVERIFIED against a live org — no Zoho access this session).

---

## 2. Identity resolution & dedup

### 2.1 Phone is the spine — but E.164 ↔ wa_id is not identity

Known divergences between the dialable E.164 number and the WhatsApp id (`wa_id`):

- **Mexico:** legacy `521…` (mobile "1" after country code) vs modern `52…`; both forms exist in the wild and in stored CRMs.
- **Argentina:** wa_id is `549` + area + number (13 digits), and the local "15" mobile prefix must be dropped; Meta normalizes on send and returns the corrected `wa_id` (a *mismatch event*).
- **Brazil:** ninth-digit rollout means numbers outside area codes 11–19/21/22/24/27/28 often keep a **legacy 8-digit wa_id without the 9** even though the dialable number has it.

Sources: [Zoko note on BR/MX wa_id inconsistencies](https://www.zoko.io/learning-article/whatsapp-id-brazil-mexico), [Gupshup equivalent](https://support.gupshup.io/hc/en-us/articles/4407840924953), [Chatwoot guide (BR/MX/AR)](https://www.chatwoot.com/hc/user-guide/articles/1758697086-inconsistencies-for-whats_app-numbers-in-brazil-mexico-and-argentina), [Wassenger normalization guide](https://wassenger.com/blog/en/how-to-normalize-international-phone-numbers-for-whatsapp), [chatwoot#13932 (AR #131030 errors)](https://github.com/chatwoot/chatwoot/issues/13932).

**Venezuela itself is clean** (+58 + 10-digit national, mobiles 4xx) but the patient base spans LatAm/EU/US, so normalization must be country-aware (`libphonenumber`), and identity should key on **canonical wa_id observed from inbound traffic** (ground truth) with the E.164 dialable form stored alongside.

### 2.2 Current repo state (verified in code 2026-07-08)

`src/company_agent/crm_adapter/zoho_client.py`:

- `normalize_phone` = strip non-digits; `phone_search_suffix` = **last 9 digits** for a `LIKE '%suffix%'` COQL match (`find_contact_by_phone`, lines 138–151), LIMIT 3 with exact-normalized preference. Pragmatic, but:
  1. **Brazil legacy-wa_id contacts defeat it** — the stored number (with 9) and the wa_id (without 9) differ *within* the last 9 digits.
  2. Last-9 collisions across countries are possible (different country/area prefix, same tail); LIMIT 3 + first-row fallback silently picks a wrong contact instead of flagging ambiguity.
  3. `LIKE '%…%'` is an unindexed scan server-side; fine at NutriWhite's volume, but it's a read-time heuristic, not an identity model.
  4. `find_contact_by_email` interpolates the raw email into COQL (injection + no case-normalization) — hygiene fix needed before email becomes a match key.
- There is **no local identity table** today; nothing joins IGSID ↔ phone ↔ email ↔ Zoho id.

### 2.3 Zoho-native dedup machinery (what to lean on)

- **Upsert API** with `duplicate_check_fields` — dedupes on system unique fields (e.g. `Email`) and **custom "do not allow duplicate values" fields**; ordered check; update-if-found else insert. Sources: [Upsert Records v8](https://www.zoho.com/crm/developer/docs/api/v8/upsert-records.html), [Kaizen #56](https://help.zoho.com/portal/en/community/topic/kaizen-56-upsert-records-api). **Recommended: add a custom unique `Phone_E164_Canonical` field on Leads/Contacts and always upsert through it.** (That custom unique fields participate in upsert dedup is documented; exact behavior on Contacts with the phone field type: UNVERIFIED live, verify in sandbox.)
- **Merge Records API v8** — `POST /{module}/{master_id}/actions/merge`, master + up to 2 child records, per-field survivorship choices, async job if a child has >1,000 related records. Works on Leads, Contacts, Deals, custom modules. Sources: [Merge Records API](https://www.zoho.com/crm/developer/docs/api/v8/merge-records.html), [Get Merge Status](https://www.zoho.com/crm/developer/docs/api/v8/get-merge-status.html). This is the after-the-fact repair tool for two-channel dupes; every merge must be logged (F6 audit trail).

### 2.4 The IG-handle join problem

IGSID/username **cannot** be deterministically joined to a phone or email — Meta exposes only public profile fields (§1.1). Reliable joins are *behavioral*:

1. **In-flow capture:** ManyChat flow asks for phone (and validates format) before External Request fires. Highest-fidelity, adds friction.
2. **Ref-token click-to-WhatsApp (recommended):** intake service mints a short opaque code per IG contact; the ManyChat flow sends a `wa.me/<gutty>?text=<prefilled containing code>` link; the first WhatsApp inbound containing the code links `wa_id ↔ IGSID` deterministically, then the code is burned. This also *is* the F10 IG→WhatsApp funnel mechanic — identity linking rides for free on it.
3. **Fuzzy fallback (name/username similarity):** never auto-merge; emit a `learning_queue`-style human-review item. (Probabilistic identity merging on a health-adjacent CRM is a precision-lens fail.)

### 2.5 Race conditions: same human via two channels

Scenario: person fills a Meta Lead Ad form (phone+email) and DMs the IG account within the same minute; or messages WhatsApp while their LeadChain record is still syncing.

Design that survives it (standard engineering; no external citation needed):

- **Single intake bus:** every source (ManyChat webhook, LeadChain-created Zoho record via workflow webhook, manual Zoho entry via same webhook, future sources) funnels into **one normalizer endpoint** on agent-core. No source writes to Zoho directly except LeadChain.
- **Local identity broker in Postgres** (`lead_identity`: id, phone_e164_canonical UNIQUE, wa_id UNIQUE, email_lower UNIQUE, igsid UNIQUE, zoho_lead_id, zoho_contact_id, merged_into, created_from_source, timestamps). Claim identity with `INSERT … ON CONFLICT` on canonical keys inside one transaction; per-key uniqueness makes two concurrent arrivals converge on one row (second writer becomes an update/link, not a dupe). A `pg_advisory_xact_lock(hash(phone_e164))` around the match-then-write section serializes the check-merge path where multiple keys are involved.
- **Idempotency ledger:** `intake_events(source, source_event_id UNIQUE, processed_at)` — `leadgen_id` for Meta, ManyChat contact id + flow step ts, Zoho record id + `Modified_Time` for workflow webhooks. Meta redelivers webhooks on non-2xx; ManyChat may not retry at all; both extremes are handled by (a) enqueue-then-ACK fast, (b) uniqueness on source_event_id. Note the existing punch-list item `fsm.py:39` in-memory `_SEEN` dedup — the same in-memory anti-pattern must NOT be replicated for intake; this table is the durable answer.
- **Zoho as convergence point, not arbiter:** after local claim, upsert to Zoho keyed on the custom canonical-phone unique field (or Email when phone absent); if the person later proves to be an existing Contact (suffix/wa_id match), link instead of insert, and use Merge API when two records slipped through. Zoho's own duplicate check is the *second* guard, never the only one.
- **Loop guard** on Zoho workflow webhooks (§1.3) so brain-originated writes don't re-enter intake.

---

## 3. Options assessed

| # | Option | Verdict |
|---|--------|---------|
| O1 | **Custom intake bus**: ManyChat External Request + Zoho workflow-rule webhooks (record-id-only payload) → one normalizer in agent-core + Postgres identity broker + Zoho upsert/merge | **Adopt** — the identity broker and normalizer must be owned code regardless of overall architecture candidate; fits current stack (FastAPI + Postgres already deployed) |
| O2 | **Meta Lead Ads via Zoho LeadChain** (Zoho-held Meta app), leads land in Zoho, workflow webhook feeds the bus | **Adopt for launch** — zero Meta App Review/Business Verification burden; pilot latency + field mapping (UNVERIFIED); direct Meta integration (O3) is the upgrade path if LeadChain lags >~2 min against F8's "first touch within minutes" |
| O3 | **Direct Meta leadgen webhook** (own app: Advanced Access `leads_retrieval` etc.) | **Defer** — fastest and most controlled, but App Review + Business Verification + ongoing app compliance is real overhead for a 1–3-person team; adopt only if O2 fails the latency/fidelity pilot |
| O4 | **iPaaS bridge** (LeadsBridge/Zapier/Make/n8n) for Meta→Zoho or ManyChat→anywhere | **Reject as default** — adds $30–80/mo + a vendor for paths O1/O2 cover; n8n reappears only if candidate C3 wins overall |
| O5 | **Zoho Notification API (watch channels)** as primary Zoho trigger | **Reject** — 1-day max channel expiry forces renewal infra; workflow webhooks don't expire; keep watch as fallback for trigger shapes rules can't express |
| O6 | **Polling/exports as primary** (Meta bulk read, ManyChat CSV) | **Reject as primary** (breaks F8 first-touch-in-minutes); **adopt as reconciliation**: nightly Meta bulk read per form (inside 90-day window) + ManyChat Sheets export to catch dropped webhooks |

## 4. Recommendation (for THIS business)

Hybrid **O1 + O2 + O6-reconciliation**: one owned intake-normalizer + Postgres identity broker (canonical keys: country-aware E.164 via libphonenumber, observed wa_id, lower-cased email, IGSID; unique constraints + idempotency ledger + advisory-lock merge path); ManyChat pushes via External Request with the ref-token wa.me link doing double duty as IG→WhatsApp funnel *and* deterministic IGSID↔wa_id join; Meta Lead Ads enter through Zoho LeadChain and reach the brain via a Zoho workflow-rule webhook that carries only `{module, record_id, event}` (brain re-fetches via COQL; loop-guard on the integration user). Zoho gets a custom unique canonical-phone field and all brain writes go through upsert-with-duplicate_check_fields; Merge Records API + a human-review queue handle residual dupes (never auto-merge on fuzzy name). This is source-agnostic (new intake source = new adapter posting to the same bus — satisfies the extensibility criterion) and orchestrator-agnostic (survives whichever of C1–C5 wins).

Incremental cost ≈ $0 infra (runs on existing droplet/Postgres); ManyChat Pro $29–105/mo (likely already paid); LeadChain pricing TBD.

## 5. Open questions

1. LeadChain: actual sync latency, per-lead cost, custom-field mapping fidelity — needs a live pilot (no Zoho access this session).
2. What are the "existing automations" already landing records in Zoho (brief F7c) concretely — which modules, which Source values? Determines workflow-rule conditions and loop-guard design.
3. Does NutriWhite's ManyChat account have Pro + is phone capture already in the IG flows? Determines whether ref-token linking is the primary or only join.
4. Can Zoho workflow rules condition on `Modified_By` = specific (API) user for the loop guard, or is a `Source` picklist convention required? Verify in sandbox.
5. Custom unique field on Contacts for canonical phone: confirm upsert `duplicate_check_fields` accepts it on both Leads and Contacts in the org's edition.
