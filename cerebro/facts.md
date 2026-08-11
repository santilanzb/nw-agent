# nw-agent — domain facts

<!-- verified: 2026-08-11 (Zoho facts re-read live; 2026-08-01 items unchanged) -->

Only what is specific to this project. Machine, harness and method facts belong in the master
brain at `C:\Users\santi\.claude\cerebro`, not here.

These are what survived draining the 43 claims rescued from the old laptop, on 2026-08-01:
**34 were already documented in this repo** and were discarded rather than copied, 2 were stale,
2 were refuted, 1 needs a live check, and 4 were proposed as doctrine — of which **2 survived an
adversarial pass** that tried to kill each one three ways (already documented / overstated / not
actually external). Both survivors are facts about **Zoho's live configuration**, which is exactly
the share a repo cannot hold about itself.

## Two Zoho module labels are INVERTED relative to their api_names

Verified live 2026-08-01 via `getModules` (107 modules), DC `.com`:

- api **`Leads`** is labelled **"Contactos"**
- api **`Contacts`** is labelled **"Comunidad NW"**
- api **`Accounts`** is labelled **"Formas de Pago"** — it is *not* a companies module

**"Comunidad NW" is not a separate module.** The only `Comunidad*` api_names are the linking
modules `Comunidad_X_Comunidad` / `2`.

**The failure mode is silent, and it is not the one you would guess.** COQL resolves api_names
only, so querying the *label* fails loudly and safely —
`select id, Last_Name from Contactos where id is not null limit 2` → `{"code":"INVALID_MODULE"}`.
The dangerous path is the opposite: you read "Contactos" in the UI, write `from Contacts`, and it
**succeeds while returning the Comunidad NW population**. Verified live 2026-08-01 — `from Contacts`
and `from Leads` returned two disjoint sets of records, no surname in common. Different populations,
no error either way.

> **To query what the UI calls "Contactos", select `from Leads`.**

**Never resolve a module by label.** "Presupuestos" is ambiguous in this org: it is the
`plural_label` of **both** `Quotes` and `CustomModule5002`, both visible and api-supported. Go
through `getModules` and use the api_name.

*Paired COQL gotcha:* COQL requires a `WHERE` clause, and omitting it returns
`SYNTAX_ERROR` / "missing clause: where" **before the module name is validated** — so a bad module
name can masquerade as a syntax error.

*What this repo already gets right, and must not be duplicated here:* `Deals`=Tratos
(`CLAUDE.md:87`, `docs/studies/2026-07-08-master-operator/BRIEF.md:42`), `Quotes`="Presupuesto"
(`BRIEF.md:20,42`), and `Consultas`/`Examenes` as real unaccented custom api_names
(`CLAUDE.md:88-89`). What it gets **wrong** is this inversion: `README.md:70` lists
"Contacts, Comunidad NW" as two separate modules in a five-module list. They are one module.

## `Quotes.Quote_Stage` speaks the Spanish label, not the `actual_value`

UI label "Fase de Presupuesto". 16 options, single layout `Standard__s`, read live 2026-08-01 via
`getFields{module:Quotes}`.

**9 of the 16 carry a divergent `actual_value`** — Enviado→`Negotiation`, No Tiene
Fondos→`On Hold`, Contactar a Futuro→`Confirmed`, Concretó→`Closed Won`, Concretó de forma
parcial→`Cerrado ganado parcial`, Concretó (Otro presupuesto)→`Cerrado ganado (Otro presupuesto)`,
Borrador→`Draft`, Cerrado perdido→`Closed Lost`, Entregado→`Delivered`.

**Using that column fails silently.** COQL `where Quote_Stage = 'Closed Won'` returns `[]` with no
error, while `= 'Concretó'` returns rows; `getRecord` likewise returns `"Concretó"`.
**Write and filter on the label.**

- **In use** (`type:"used"`, 12): Enviado · Ignorado · No Tiene Fondos · No Desea Realizarlos ·
  Contactar a Futuro · Pendiente por concretar · Contacto especialista · Contacto soporte exámenes ·
  Concretó · Concretó de forma parcial · Concretó (Otro presupuesto) · Presupuesto Vencido
- **Selectable but unused** (`type:"unused"`, 4): Borrador · Cancelado · Cerrado perdido · Entregado

Note the exact accents — `Contacto soporte exámenes`, `Concretó` — and that COQL `like` does **not**
fold accents. The field is `system_mandatory:false`, `api_create`/`api_update:true`.

**Not verified:** whether an off-list value draws a hard `INVALID_DATA`/400. That needs a write and
only reads were run, so treat this as the safe write inventory, not a proven rejection boundary.
Any CRM admin can change the set in the UI — re-read `getFields` before trusting it in new code.

## Leads keep their phone in a CUSTOM field; `Phone` and `Mobile` are empty

Verified live 2026-08-11. On api `Leads` (labelled **"Contactos"**), the standard
`Phone` and `Mobile` fields return **nothing at all** — `where Phone is not null` and
`where Mobile is not null` both come back empty across the module. The number lives in:

> **`Tel_fono_con_c_digo_de_pa_s1`** — label "Teléfono (con código de país)", type `phone`

api `Contacts` (**"Comunidad NW"**, the patients) *does* use the standard `Phone`.

**The failure mode is silence, and it hit the most common case.** Looking a WhatsApp number
up only in `Contacts.Phone` — which is all `find_contact_by_phone` did — finds existing patients
and misses every inbound **lead**, i.e. most new traffic: no name, no history, and a handoff with
no CRM record to attach to. `ZohoClient.find_by_phone` now tries `Contacts` first (a patient is
the stronger match, carrying plan, specialist and consultation history) and falls back to `Leads`.

Two related traps:

- **Stored formats are inconsistent** — `+58 4241568769`, `+584123138118`, `6692771132`,
  `528124319415`. Matching is a last-9-digit `LIKE` on normalized digits for exactly this reason.
- **A Note must name the module its parent lives in.** `$se_module: "Contacts"` cannot attach to a
  Lead, so a lead's handoff would silently lose its CRM trail. `create_note(..., module=...)` takes
  it, allowlisted.

*Also verified:* COQL's default universe **excludes converted leads**, which is the behaviour we
want here — a converted lead has a Contact, and that is the better match. (See the master-brain
note on the same default hiding 3,536 converted leads from a count.)

## COQL escapes a single quote by DOUBLING it, and has no bind parameters

Verified live 2026-08-11:

- `where Last_Name = 'O\'Brien'` → `{"code":"SYNTAX_ERROR","details":{"line":1,"column":55}}`
- `where Last_Name = 'O''Brien'` → parses, returns `[]`
- `where id = '4806334000196115218'` → returns the record, so **record ids may be quoted** like
  any other literal.

The request body is a single `select_query` string — there is no parameter binding, so every value
is interpolated and escaping is the only defence. All of it lives in one place:
`src/company_agent/crm_adapter/coql.py` (`quote` / `record_id` / `like_contains` / `limit` /
`identifier`). Do not hand-build a COQL literal anywhere else.

## `Product_Code` cannot key the Products pull — RESOLVED, use the record `id`

The open question from 2026-08-01 is closed. Verified live 2026-08-11 across all **178 active**
products, and it is worse than first recorded:

- **~60% of active products have `Product_Code = null`** — the entire Nordic, Zoomer, DUTCH and
  current plan families.
- Codes repeat across **active** rows at *different prices*: `PLAN-MANT-1CONS-FULL-01` is both
  id `4806334000196115227` "Plan de 1 consulta Mantenimiento" **$149** and id
  `4806334000196115282` "…Mantenimiento F&F" **$135**. Same for `-02` ($279 / $249) and
  `-03` ($309 / $299).

⇒ The nightly Products → `facts/prices.yaml` pull (graft G2) **keys on the Zoho record `id`**.
`Product_Code` is carried as a non-unique display field, and the pull emits a hygiene report of
null/duplicate codes for calidad@.

## The consultation catalogue was restructured; the $229 plan is inactive

Verified live 2026-08-11. `PLAN-1CONS-FULL-01` "PLAN 1 CONSULTA" **$229 is `Product_Active:
false`** — there is no active $229 plan. The active families are:

| Family | Prices (F&F variant) |
|---|---|
| PLAN INMUNONUTRICIÓN 1 / 2 / 4 / 6 | $249 / $399 / $599 / $799 ($224 / $359 / $539 / $719) |
| PLAN NUTRICIÓN 1 / 2 / 3 / 5 | $149 / $279 / $329 / $450 ($134 / $251 / $296 / $405) |
| PLAN CONTROL (EE / EN / NN) | $369 / $329 / $279 ($332 / $296 / $251) |
| Legacy still active | 3 CONSULTAS $559 · 5 CONSULTAS $789 · Mantenimiento $149 / $279 / $309 |

Every family has a parallel **F&F** row at a lower price. F&F is excluded from what Gutty may
quote — an unqualified discount is a silent revenue leak with no audit trail.

**What each family is, from calidad@ (2026-08-11):** PLAN NUTRICIÓN is delivered by the
**nutricionistas** — the role previously called "acompañantes"; PLAN INMUNONUTRICIÓN by the
**especialistas**. This is the distinction the patient is actually asking about when they compare
$149 against $249, and it existed nowhere in the repo.

**Fixed 2026-08-11:** the $229 quote is gone from all five surfaces that carried it — both policy
surfaces, both knowledge-corpus files (re-ingested), and the eval system prompt and assertions.
`tests/test_faq_parity.py` now fails if the two policy surfaces diverge or if $229 returns. Gutty
quotes the two main families only; Control, Mantenimiento and the legacy 3/5-consulta plans stay in
the corpus for an asesora but are not offered unprompted.

## Open

Nothing outstanding. The one unproven item — whether an off-list `Quote_Stage` value draws a hard
`INVALID_DATA`/400 — is recorded inline in that section, where anyone about to write the field will
actually read it.
