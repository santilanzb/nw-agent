# nw-agent — domain facts

<!-- verified: 2026-08-01 -->

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

## Open, and it needs a live check

- **Is `Product_Code` safe as the key for the nightly Products → `facts/prices.yaml` pull?**
  `candidate-C4.md:109` and `tournament-verdict.md:98` (graft G2) designate `Products` as "the
  single price source of truth". Verified live 2026-08-01: **`Product_Code` is NOT unique and can
  be null** — `PLAN-2CONS-FULL-05` exists twice. Keying on it will silently collapse or drop rows,
  and this feeds prices. Decide the key before that pull is built.
